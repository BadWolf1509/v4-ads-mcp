"""dry_run module integration tests against testcontainers Postgres."""

from uuid import uuid4

import pytest
from testcontainers.postgres import PostgresContainer

from src.db import connection, migrate
from src.db.repositories import managers, mcp_sessions
from src.governance.dry_run import (
    ConsumeResult,
    InvalidTokenError,
    consume,
    create_pending,
    generate_token,
)


@pytest.fixture
async def pg() -> PostgresContainer:
    with PostgresContainer("postgres:16-alpine") as container:
        yield container


@pytest.fixture
async def db(pg: PostgresContainer):
    dsn = pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
    await connection.init_pool(dsn, min_size=1, max_size=4)
    try:
        await migrate.run_all()
        yield connection.get_pool()
    finally:
        await connection.close_pool()


@pytest.fixture
async def session_id(db):
    """Create a manager + session for the tests."""
    pool = db
    async with pool.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="t@v4.com", full_name=None)
        from src.auth.sessions import generate_session_token, hash_session_token

        token = generate_session_token()
        sess = await mcp_sessions.create(
            conn, manager_id=mid, token_hash=hash_session_token(token), label="t"
        )
        yield sess.id


@pytest.mark.integration
async def test_generate_token_format() -> None:
    """Tokens are 8 alphanumeric chars (uppercase + digits)."""
    import re

    for _ in range(20):
        t = generate_token()
        assert re.match(r"^[A-Z0-9]{8}$", t), f"Got {t!r}"


@pytest.mark.integration
async def test_create_and_consume_roundtrip(db, session_id) -> None:
    pool = db
    async with pool.acquire() as conn:
        token = await create_pending(
            conn,
            session_id=session_id,
            customer_id="1234567890",
            operation_type="update_campaign_budget",
            payload={"campaign_id": "111", "new_amount_micros": 100_000_000},
            blast_summary="Budget mudara de R$ 50 pra R$ 100",
        )
        assert len(token) == 8

    async with pool.acquire() as conn:
        result = await consume(conn, token=token, session_id=session_id)
        assert isinstance(result, ConsumeResult)
        assert result.customer_id == "1234567890"
        assert result.operation_type == "update_campaign_budget"
        assert result.payload["campaign_id"] == "111"

    # Second consume must fail (already consumed)
    async with pool.acquire() as conn:
        with pytest.raises(InvalidTokenError, match="already consumed"):
            await consume(conn, token=token, session_id=session_id)


@pytest.mark.integration
async def test_consume_rejects_unknown_token(db, session_id) -> None:
    pool = db
    async with pool.acquire() as conn:
        with pytest.raises(InvalidTokenError, match="not found"):
            await consume(conn, token="ABCD1234", session_id=session_id)


@pytest.mark.integration
async def test_consume_rejects_wrong_session(db, session_id) -> None:
    """Token from session A can't be applied by session B."""
    pool = db
    other_session = uuid4()
    async with pool.acquire() as conn:
        token = await create_pending(
            conn,
            session_id=session_id,
            customer_id="1234567890",
            operation_type="update_campaign_budget",
            payload={},
            blast_summary="...",
        )

    async with pool.acquire() as conn:
        with pytest.raises(InvalidTokenError, match="session"):
            await consume(conn, token=token, session_id=other_session)


@pytest.mark.integration
async def test_consume_rejects_expired_token(db, session_id) -> None:
    """Tokens older than 10 minutes can't be applied."""
    pool = db
    async with pool.acquire() as conn:
        token = await create_pending(
            conn,
            session_id=session_id,
            customer_id="1234567890",
            operation_type="update_campaign_budget",
            payload={},
            blast_summary="...",
        )
        # Manually expire it
        await conn.execute(
            "UPDATE pending_confirmations SET expires_at = now() - interval '1 minute' WHERE token = $1",
            token,
        )

    async with pool.acquire() as conn:
        with pytest.raises(InvalidTokenError, match="expired"):
            await consume(conn, token=token, session_id=session_id)
