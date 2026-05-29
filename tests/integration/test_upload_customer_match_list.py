"""Integration tests for upload_customer_match_list tool (Sprint 3b.28).

Mock helper at TOOL's namespace (NOT _common's) — convention pós-3b.5/3b.8
(F-class "Pre-flight test mocks"). Patching at _common.py would slip the
local pre-push gate (which doesn't run DB integration) and surface only
in CI.

LGPD test: verifica que pending_confirmations payload NÃO contém plaintext
email/phone_number — apenas hashed_email/hashed_phone_number (SHA-256 hex).
"""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from testcontainers.postgres import PostgresContainer

from src.db import connection, migrate
from src.db.repositories import google_ads_accounts, manager_account_access, managers, mcp_sessions
from src.mcp.context import McpRequestContext, clear_current, set_current


@pytest.fixture
async def pg() -> PostgresContainer:
    with PostgresContainer("postgres:16-alpine") as container:
        yield container


@pytest.fixture
async def db(pg):
    dsn = pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
    await connection.init_pool(dsn, min_size=1, max_size=4)
    try:
        await migrate.run_all()
        yield connection.get_pool()
    finally:
        await connection.close_pool()


@pytest.fixture
async def session_ctx(db):
    pool = db
    async with pool.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="t@v4.com", full_name=None)
        from src.auth.sessions import generate_session_token, hash_session_token

        token = generate_session_token()
        sess = await mcp_sessions.create(
            conn, manager_id=mid, token_hash=hash_session_token(token), label="t"
        )
    # Seed google_ads_accounts + grant write access so ensure_account_access passes.
    # This file uses customer_id="1163862076" (not the default 1234567890).
    async with pool.acquire() as conn:
        await google_ads_accounts.upsert_many(
            conn,
            [{"customer_id": "1163862076", "mcc_id": "0000000000", "descriptive_name": "Test"}],
        )
        await manager_account_access.grant(
            conn, manager_id=mid, customer_id="1163862076", access_level="write", granted_by=mid
        )
    ctx = McpRequestContext(manager_id=mid, session_id=sess.id)
    set_current(ctx)
    yield ctx
    clear_current()


@pytest.mark.integration
async def test_layer2_rejects_already_hashed_email(db, session_ctx):
    """Layer 2 catches plaintext-pretending-to-be-hashed input (SHA-256 hex pattern)."""
    from src.mcp.tools.upload_customer_match_list import upload_customer_match_list

    args = {
        "customer_id": "1163862076",
        "user_list_id": "1234567890",
        "operation": "add",
        "members": [{"email": "5e884898da28047151d0e56f8dc6292773603d0d6aabbdd62a11ef721d1542d8"}],
    }
    result = await upload_customer_match_list(args)
    assert result["status"] == "error"
    assert "já parece SHA-256" in result["error"] or "já parece" in result["error"]


@pytest.mark.integration
async def test_preflight_missing_user_list_returns_error(db, session_ctx):
    """Mock preflight at TOOL's namespace (convention pós-3b.5/3b.8).

    Patching src.mcp.tools.upload_customer_match_list.validate_user_list_for_upload
    — NOT src.google_ads.queries._common.validate_user_list_for_upload.
    """
    from src.mcp.tools.upload_customer_match_list import upload_customer_match_list

    args = {
        "customer_id": "1163862076",
        "user_list_id": "9999999999",
        "operation": "add",
        "members": [{"email": "user@example.com"}],
    }
    mock_error = {
        "error": "user_list_id=9999999999 não existe em customer_id=1163862076.",
        "missing_id": "9999999999",
    }
    with patch(
        "src.mcp.tools.upload_customer_match_list.validate_user_list_for_upload",
        AsyncMock(return_value=mock_error),
    ):
        result = await upload_customer_match_list(args)
    assert result["status"] == "error"
    assert result["missing_id"] == "9999999999"


@pytest.mark.integration
async def test_happy_path_returns_dry_run_token(db, session_ctx):
    """Layer 1+2+3 pass → dry_run + confirmation_token + members_count retornado."""
    from src.mcp.tools.upload_customer_match_list import upload_customer_match_list

    args = {
        "customer_id": "1163862076",
        "user_list_id": "1234567890",
        "operation": "add",
        "members": [
            {"email": "user1@example.com"},
            {"phone_number": "+5511987654321"},
        ],
    }
    with patch(
        "src.mcp.tools.upload_customer_match_list.validate_user_list_for_upload",
        AsyncMock(return_value=None),
    ):
        result = await upload_customer_match_list(args)
    assert result["status"] == "dry_run"
    assert "confirmation_token" in result
    assert result["members_count"] == 2
    assert result["operation_type"] == "add"


@pytest.mark.integration
async def test_remove_operation_passes_through_to_payload(db, session_ctx):
    """operation='remove' é preservado no dry_run response (pro dispatcher apply_change)."""
    from src.mcp.tools.upload_customer_match_list import upload_customer_match_list

    args = {
        "customer_id": "1163862076",
        "user_list_id": "1234567890",
        "operation": "remove",
        "members": [{"email": "user1@example.com"}],
    }
    with patch(
        "src.mcp.tools.upload_customer_match_list.validate_user_list_for_upload",
        AsyncMock(return_value=None),
    ):
        result = await upload_customer_match_list(args)
    assert result["status"] == "dry_run"
    assert result["operation_type"] == "remove"


@pytest.mark.integration
async def test_payload_contains_only_hashed_members_no_plaintext(db, session_ctx):
    """LGPD: pending_confirmations NÃO armazena plaintext email/phone.

    Verifica via raw query no pending_confirmations.payload (JSONB) que:
    - hashed_email presente e é SHA-256 hex (64 chars)
    - 'email' e 'phone_number' plaintext keys ausentes
    - hashed_email != plaintext literal
    """
    from src.mcp.tools.upload_customer_match_list import upload_customer_match_list

    args = {
        "customer_id": "1163862076",
        "user_list_id": "1234567890",
        "operation": "add",
        "members": [{"email": "secret@example.com"}],
    }
    with patch(
        "src.mcp.tools.upload_customer_match_list.validate_user_list_for_upload",
        AsyncMock(return_value=None),
    ):
        result = await upload_customer_match_list(args)

    assert result["status"] == "dry_run"
    token = result["confirmation_token"]

    # Raw query no pending_confirmations — verifica payload JSONB sem plaintext
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT payload FROM pending_confirmations WHERE token = $1", token
        )
    assert row is not None, f"Token '{token}' not found in pending_confirmations"

    payload = row["payload"]
    # asyncpg deserializes JSONB columns automatically — may arrive as dict or str
    if isinstance(payload, str):
        import json

        payload = json.loads(payload)

    assert "hashed_members" in payload, "payload deve ter chave 'hashed_members'"
    hashed_member = payload["hashed_members"][0]

    # CRITICAL LGPD: hashed_email presente
    assert "hashed_email" in hashed_member, "hashed_email deve estar no payload"

    # CRITICAL LGPD: plaintext keys NEVER stored
    assert "email" not in hashed_member, (
        "plaintext 'email' não deve aparecer no payload (LGPD minimização)"
    )
    assert "phone_number" not in hashed_member, (
        "plaintext 'phone_number' não deve aparecer no payload (LGPD minimização)"
    )

    # Hash value não deve ser o plaintext literal
    assert hashed_member["hashed_email"] != "secret@example.com"

    # SHA-256 hex length (64 lowercase hex chars)
    assert len(hashed_member["hashed_email"]) == 64
    assert all(c in "0123456789abcdef" for c in hashed_member["hashed_email"])
