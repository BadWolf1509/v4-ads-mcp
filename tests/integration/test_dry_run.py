"""dry_run module integration tests against testcontainers Postgres."""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.db.repositories import managers, mcp_sessions
from src.governance.dry_run import (
    ConsumeResult,
    InvalidTokenError,
    consume,
    create_pending,
    generate_token,
)


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
        yield sess.id, mid


@pytest.mark.integration
async def test_generate_token_format() -> None:
    """Tokens are 8 alphanumeric chars (uppercase + digits)."""
    import re

    for _ in range(20):
        t = generate_token()
        assert re.match(r"^[A-Z0-9]{8}$", t), f"Got {t!r}"


@pytest.mark.integration
async def test_create_and_consume_roundtrip(db, session_id) -> None:
    sid, mid = session_id
    pool = db
    with patch("src.governance.dry_run.ensure_account_access", AsyncMock(return_value=None)):
        async with pool.acquire() as conn:
            token = await create_pending(
                conn,
                manager_id=mid,
                session_id=sid,
                customer_id="1234567890",
                operation_type="update_campaign_budget",
                payload={"campaign_id": "111", "new_amount_micros": 100_000_000},
                blast_summary="Budget mudara de R$ 50 pra R$ 100",
            )
            assert len(token) == 8

    async with pool.acquire() as conn:
        result = await consume(conn, token=token, session_id=sid)
        assert isinstance(result, ConsumeResult)
        assert result.customer_id == "1234567890"
        assert result.operation_type == "update_campaign_budget"
        assert result.payload["campaign_id"] == "111"

    # Second consume must fail (already consumed)
    async with pool.acquire() as conn:
        with pytest.raises(InvalidTokenError, match="already consumed"):
            await consume(conn, token=token, session_id=sid)


@pytest.mark.integration
async def test_consume_rejects_unknown_token(db, session_id) -> None:
    pool = db
    async with pool.acquire() as conn:
        with pytest.raises(InvalidTokenError, match="not found"):
            await consume(conn, token="ABCD1234", session_id=session_id)


@pytest.mark.integration
async def test_consume_rejects_wrong_session(db, session_id) -> None:
    """Token from session A can't be applied by session B."""
    sid, mid = session_id
    pool = db
    other_session = uuid4()
    with patch("src.governance.dry_run.ensure_account_access", AsyncMock(return_value=None)):
        async with pool.acquire() as conn:
            token = await create_pending(
                conn,
                manager_id=mid,
                session_id=sid,
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
    sid, mid = session_id
    pool = db
    with patch("src.governance.dry_run.ensure_account_access", AsyncMock(return_value=None)):
        async with pool.acquire() as conn:
            token = await create_pending(
                conn,
                manager_id=mid,
                session_id=sid,
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
            await consume(conn, token=token, session_id=sid)


@pytest.mark.integration
async def test_dry_run_deixa_linha_propria_na_trilha(db, session_id) -> None:
    """F148: o preview grava `mutate` + `dry_run=true` com o target_count PLANEJADO.

    Contra Postgres real, porque o que se quer provar aqui e que a coluna nova
    existe e faz round-trip — o teste unitario so ve o kwarg saindo.
    """
    sid, mid = session_id
    pool = db
    with patch("src.governance.dry_run.ensure_account_access", AsyncMock(return_value=None)):
        async with pool.acquire() as conn:
            await create_pending(
                conn,
                manager_id=mid,
                session_id=sid,
                customer_id="1234567890",
                operation_type="update_ad_schedule",
                payload={"__target_count__": 7, "campaign_ids": ["1"]},
                blast_summary="7 operacoes",
            )

    async with pool.acquire() as conn:
        linhas = await conn.fetch(
            "SELECT action_type, operation, target_count, dry_run, status "
            "FROM audit_log WHERE manager_id = $1 ORDER BY id DESC",
            mid,
        )

    previews = [r for r in linhas if r["dry_run"] is True]
    assert len(previews) == 1, "o preview tem que deixar exatamente uma linha"
    linha = previews[0]
    assert linha["action_type"] == "mutate"
    assert linha["operation"] == "update_ad_schedule"
    assert linha["target_count"] == 7
    assert linha["status"] == "success"


@pytest.mark.integration
async def test_pendencia_e_trilha_vivem_ou_morrem_juntas(db, session_id) -> None:
    """Se a auditoria falhar, a pendencia NAO fica de pe.

    E o defeito do F148 ao contrario: token mintado sem rastro. As duas escritas
    estao na mesma transacao, entao uma sem a outra nao e um estado alcancavel.
    """
    sid, mid = session_id
    pool = db
    with (
        patch("src.governance.dry_run.ensure_account_access", AsyncMock(return_value=None)),
        patch(
            "src.governance.dry_run.audit_log.record",
            AsyncMock(side_effect=RuntimeError("trilha fora do ar")),
        ),
        pytest.raises(RuntimeError, match="trilha fora do ar"),
    ):
        async with pool.acquire() as conn:
            await create_pending(
                conn,
                manager_id=mid,
                session_id=sid,
                customer_id="1234567890",
                operation_type="update_ad_schedule",
                payload={"__target_count__": 3},
                blast_summary="3 operacoes",
            )

    async with pool.acquire() as conn:
        pendentes = await conn.fetchval(
            "SELECT count(*) FROM pending_confirmations WHERE session_id = $1", sid
        )
    assert pendentes == 0, "token ficou de pe sem linha de auditoria — e o proprio F148"
