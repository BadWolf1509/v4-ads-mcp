"""Integration tests Sprint M.2b: /oauth/meta/data-deletion-callback endpoint."""

import base64
import hashlib
import hmac
import json

import pytest

from src.db import connection

pytestmark = pytest.mark.asyncio

_SIGNING_KEY = "x" * 32
_AES_MASTER = "y" * 43
APP_SECRET = "test_app_secret_xyz"


def _make_signed_request(payload: dict, secret: str = APP_SECRET) -> str:
    payload_json = json.dumps(payload, separators=(",", ":"))
    payload_b64 = base64.urlsafe_b64encode(payload_json.encode()).decode().rstrip("=")
    sig = hmac.new(secret.encode(), payload_b64.encode(), hashlib.sha256).digest()
    sig_b64 = base64.urlsafe_b64encode(sig).decode().rstrip("=")
    return f"{sig_b64}.{payload_b64}"


@pytest.fixture(autouse=True)
def _meta_env(monkeypatch):
    """Env extra além do padrão do conftest (DATABASE_URL/SESSION_SIGNING_KEY/AES_MASTER_KEY)."""
    monkeypatch.setenv("META_APP_ID", "test_app_id")
    monkeypatch.setenv("META_APP_SECRET", APP_SECRET)


@pytest.mark.integration
async def test_data_deletion_callback_valid_signature(client):
    """Valid HMAC signed_request → 200 + return {url, confirmation_code} + audit_log row."""
    payload = {
        "algorithm": "HMAC-SHA256",
        "user_id": "fb_user_9999",
        "expires": 1747824000,
        "issued_at": 1747820400,
    }
    signed_request = _make_signed_request(payload)

    resp = await client.post(
        "/oauth/meta/data-deletion-callback",
        data={"signed_request": signed_request},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "url" in body
    assert "confirmation_code" in body
    assert body["url"].endswith(body["confirmation_code"])

    pool = connection.get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT operation, platform, params_summary FROM audit_log "
            "WHERE operation = 'meta_data_deletion_request' "
            "ORDER BY occurred_at DESC LIMIT 1"
        )
    assert row is not None
    assert row["platform"] == "meta"
    # params_summary is JSONB, may need to parse JSON
    params = (
        json.loads(row["params_summary"])
        if isinstance(row["params_summary"], str)
        else row["params_summary"]
    )
    assert params["meta_user_id"] == "fb_user_9999"
    assert params["confirmation_code"] == body["confirmation_code"]


@pytest.mark.integration
async def test_data_deletion_callback_invalid_signature(client):
    """Wrong secret → 400 Bad Request."""
    payload = {"algorithm": "HMAC-SHA256", "user_id": "fb_user_9999"}
    signed_request = _make_signed_request(payload, secret="wrong_secret")

    resp = await client.post(
        "/oauth/meta/data-deletion-callback",
        data={"signed_request": signed_request},
    )
    assert resp.status_code == 400


@pytest.mark.integration
async def test_data_deletion_callback_missing_signed_request(client):
    """Empty form body → 400 Bad Request."""
    resp = await client.post("/oauth/meta/data-deletion-callback", data={})
    assert resp.status_code == 400
