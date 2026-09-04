"""Tests for audit_log repository extensions (Phase 4)."""

from datetime import datetime, timedelta  # noqa: F401
from uuid import uuid4

import pytest

from src.db.repositories import audit_log


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_by_id_returns_full_row(db):
    mid = uuid4()
    sid = uuid4()
    pool = db
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO managers (id, email, status, role) VALUES ($1, 'a@v4company.com', 'active', 'gestor')""",
            mid,
        )
        await conn.execute(
            """INSERT INTO mcp_sessions (id, manager_id, label, token_hash) VALUES ($1, $2, 'test', 'h')""",
            sid,
            mid,
        )
        # audit_log.id is BIGSERIAL — let DB generate, capture via RETURNING.
        aid = await conn.fetchval(
            """INSERT INTO audit_log (manager_id, session_id, customer_id, action_type, operation, status,
                                       target_count, params_summary, error_message, duration_ms, occurred_at)
               VALUES ($1, $2, '1234567890', 'read', 'list_my_accounts', 'success',
                       23, '{}'::jsonb, NULL, 7, now())
               RETURNING id""",
            mid,
            sid,
        )
        result = await audit_log.get_by_id(conn, audit_id=aid, manager_id=mid)
    assert result is not None
    assert result["operation"] == "list_my_accounts"
    assert result["target_count"] == 23


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_by_id_scopes_to_manager(db):
    """Gestor passing manager_id can't see other gestores' events."""
    mid = uuid4()
    other = uuid4()
    pool = db
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO managers (id, email, status, role) VALUES
               ($1, 'a@v4company.com', 'active', 'gestor'),
               ($2, 'b@v4company.com', 'active', 'gestor')""",
            mid,
            other,
        )
        aid = await conn.fetchval(
            """INSERT INTO audit_log (manager_id, action_type, operation, status, occurred_at)
               VALUES ($1, 'read', 'op', 'success', now())
               RETURNING id""",
            other,  # belongs to OTHER manager
        )
        result = await audit_log.get_by_id(conn, audit_id=aid, manager_id=mid)
    assert result is None  # mid can't see other's row


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_by_id_admin_sees_any(db):
    """When manager_id=None (admin context), any audit_id is reachable."""
    other = uuid4()
    pool = db
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO managers (id, email, status, role) VALUES ($1, 'b@v4company.com', 'active', 'gestor')""",
            other,
        )
        aid = await conn.fetchval(
            """INSERT INTO audit_log (manager_id, action_type, operation, status, occurred_at)
               VALUES ($1, 'read', 'op', 'success', now())
               RETURNING id""",
            other,
        )
        result = await audit_log.get_by_id(conn, audit_id=aid, manager_id=None)
    assert result is not None
    assert result["operation"] == "op"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_for_manager_expoe_dry_run_para_distinguir_tentativa_de_aplicacao(db):
    """Residuo do F148: o registro ficou certo e a LEITURA ficou ambigua.

    Uma mutacao aplicada e um preview gravam os MESMOS valores em `action_type`
    ('mutate') e `target_count` (o planejado). Pela tool os dois casos ficam
    identicos nesses campos, e num incidente a pergunta e exatamente "isso foi
    tentativa ou foi aplicado?".

    O unico diferenciador acidental hoje e `duration_ms` NULL — que nao e sinal
    desenhado E nao e exclusivo: `admin_access_grant` tambem grava `mutate` com
    duracao nula. Medido em producao em 04/09.
    """
    mid = uuid4()
    sid = uuid4()
    pool = db
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO managers (id, email, status, role) "
            "VALUES ($1, 'dryrun@v4company.com', 'active', 'gestor')",
            mid,
        )
        await conn.execute(
            "INSERT INTO mcp_sessions (id, manager_id, label, token_hash) "
            "VALUES ($1, $2, 'test', 'h-dry')",
            sid,
            mid,
        )
        # Duas linhas indistinguiveis por action_type + target_count: a tentativa
        # (preview) e a aplicacao. So a coluna nova as separa.
        for dry, dur in ((True, None), (None, 812)):
            await conn.execute(
                "INSERT INTO audit_log (manager_id, session_id, customer_id, action_type, "
                "operation, status, target_count, duration_ms, dry_run, occurred_at) "
                "VALUES ($1, $2, '1234567890', 'mutate', 'update_ad_schedule', 'success', "
                "10, $3, $4, now())",
                mid,
                sid,
                dur,
                dry,
            )

        linhas = await audit_log.list_for_manager(conn, manager_id=mid, days=7, limit=10)

    assert len(linhas) == 2
    assert all("dry_run" in r for r in linhas), f"campo ausente na resposta: {linhas}"

    previews = [r for r in linhas if r["dry_run"] is True]
    aplicadas = [r for r in linhas if not r["dry_run"]]
    assert len(previews) == 1 and len(aplicadas) == 1

    # A prova de que a coluna e necessaria: sem ela, as duas sao iguais.
    assert previews[0]["action_type"] == aplicadas[0]["action_type"] == "mutate"
    assert previews[0]["target_count"] == aplicadas[0]["target_count"] == 10
