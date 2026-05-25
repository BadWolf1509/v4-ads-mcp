"""Unit tests pra _verify_meta_signed_request HMAC validation (Sprint M.2b)."""

import base64
import hashlib
import hmac
import json

from src.auth.meta_oauth import _verify_meta_signed_request  # noqa: E402

APP_SECRET = "test_app_secret_xyz"


def _make_signed_request(payload: dict, secret: str = APP_SECRET) -> str:
    """Generate signed_request matching Meta spec format."""
    payload_json = json.dumps(payload, separators=(",", ":"))
    payload_b64 = base64.urlsafe_b64encode(payload_json.encode()).decode().rstrip("=")
    sig = hmac.new(secret.encode(), payload_b64.encode(), hashlib.sha256).digest()
    sig_b64 = base64.urlsafe_b64encode(sig).decode().rstrip("=")
    return f"{sig_b64}.{payload_b64}"


def test_verify_signed_request_valid():
    payload = {
        "algorithm": "HMAC-SHA256",
        "user_id": "9999",
        "expires": 1747824000,
        "issued_at": 1747820400,
    }
    signed_request = _make_signed_request(payload)
    result = _verify_meta_signed_request(signed_request, APP_SECRET)
    assert result is not None
    assert result["user_id"] == "9999"
    assert result["algorithm"] == "HMAC-SHA256"


def test_verify_signed_request_invalid_signature():
    payload = {"algorithm": "HMAC-SHA256", "user_id": "9999"}
    signed_request = _make_signed_request(payload, secret="wrong_secret")
    result = _verify_meta_signed_request(signed_request, APP_SECRET)
    assert result is None


def test_verify_signed_request_missing_dot():
    result = _verify_meta_signed_request("no_dot_separator", APP_SECRET)
    assert result is None


def test_verify_signed_request_invalid_base64():
    result = _verify_meta_signed_request("!!!.!!!", APP_SECRET)
    assert result is None


def test_verify_signed_request_invalid_json_payload():
    """Payload base64-decodes mas não é JSON válido."""
    bogus_payload = base64.urlsafe_b64encode(b"not json").decode().rstrip("=")
    sig = hmac.new(APP_SECRET.encode(), bogus_payload.encode(), hashlib.sha256).digest()
    sig_b64 = base64.urlsafe_b64encode(sig).decode().rstrip("=")
    result = _verify_meta_signed_request(f"{sig_b64}.{bogus_payload}", APP_SECRET)
    assert result is None


def test_verify_signed_request_wrong_algorithm():
    payload = {"algorithm": "RSA-SHA256", "user_id": "9999"}
    signed_request = _make_signed_request(payload)
    result = _verify_meta_signed_request(signed_request, APP_SECRET)
    assert result is None


def test_verify_signed_request_base64url_padding_variations():
    """Meta base64url tem padding stripped. Helper must handle both."""
    payload = {"algorithm": "HMAC-SHA256", "user_id": "1"}
    signed_request = _make_signed_request(payload)
    result = _verify_meta_signed_request(signed_request, APP_SECRET)
    assert result is not None


def test_verify_signed_request_empty_payload_missing_algorithm():
    payload = {"user_id": "9999"}
    signed_request = _make_signed_request(payload)
    result = _verify_meta_signed_request(signed_request, APP_SECRET)
    assert result is None
