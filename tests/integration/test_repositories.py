"""Integration tests for all DB repositories.

One container, one set of migrations, then test each repository's
behavior against real SQL. We don't mock asyncpg — that yields
zero confidence in column names, constraints, or upsert behavior.
"""

from uuid import UUID, uuid4

import asyncpg
import pytest

from src.db.repositories import (
    audit_log,
    google_ads_accounts,
    google_oauth_connections,
    manager_account_access,
    manager_meta_account_access,
    managers,
    mcp_sessions,
    meta_ad_accounts,
    meta_oauth_connections,
    meta_rate_counters,
)


async def _make_manager(conn: asyncpg.Connection, email: str) -> UUID:
    """Shared helper: create a manager row with a fresh id, return the id."""
    mid = uuid4()
    await managers.create(conn, manager_id=mid, email=email, full_name=None)
    return mid


# ---------- managers ----------


@pytest.mark.integration
async def test_managers_create_get_by_id_and_email(db) -> None:
    async with db.acquire() as conn:
        mid = uuid4()
        m = await managers.create(
            conn, manager_id=mid, email="x@v4company.com", full_name="X", role="admin"
        )
        assert m.id == mid
        assert m.role == "admin"
        assert m.is_active is True

        by_id = await managers.get_by_id(conn, mid)
        assert by_id is not None
        assert by_id.email == "x@v4company.com"

        by_email = await managers.get_by_email(conn, "x@v4company.com")
        assert by_email is not None
        assert by_email.id == mid


@pytest.mark.integration
async def test_managers_get_missing_returns_none(db) -> None:
    async with db.acquire() as conn:
        assert await managers.get_by_id(conn, uuid4()) is None
        assert await managers.get_by_email(conn, "nobody@v4.com") is None


@pytest.mark.integration
async def test_managers_touch_last_seen(db) -> None:
    async with db.acquire() as conn:
        mid = uuid4()
        m = await managers.create(conn, manager_id=mid, email="t@v4.com", full_name=None)
        assert m.last_seen_at is None
        await managers.touch_last_seen(conn, mid)
        m2 = await managers.get_by_id(conn, mid)
        assert m2 is not None
        assert m2.last_seen_at is not None


# ---------- mcp_sessions ----------


@pytest.mark.integration
async def test_sessions_create_find_revoke(db) -> None:
    async with db.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="s@v4.com", full_name=None)
        s = await mcp_sessions.create(
            conn, manager_id=mid, token_hash="abc" * 21, label="Claude Desktop"
        )
        assert s.label == "Claude Desktop"
        assert s.expires_at is not None

        found = await mcp_sessions.find_by_hash(conn, "abc" * 21)
        assert found is not None
        assert found.id == s.id

        await mcp_sessions.touch_last_used(conn, s.id)
        await mcp_sessions.revoke(conn, s.id)

        # After revoke, find_by_hash returns None
        assert await mcp_sessions.find_by_hash(conn, "abc" * 21) is None


@pytest.mark.integration
async def test_sessions_list_for_manager_excludes_revoked_by_default(db) -> None:
    async with db.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="ml@v4.com", full_name=None)
        s1 = await mcp_sessions.create(conn, manager_id=mid, token_hash="h1" * 32, label="A")
        s2 = await mcp_sessions.create(conn, manager_id=mid, token_hash="h2" * 32, label="B")
        await mcp_sessions.revoke(conn, s2.id)

        active = await mcp_sessions.list_for_manager(conn, mid)
        assert len(active) == 1
        assert active[0].id == s1.id

        all_sessions = await mcp_sessions.list_for_manager(conn, mid, include_revoked=True)
        assert len(all_sessions) == 2


# ---------- google_oauth_connections ----------


@pytest.mark.integration
async def test_oauth_upsert_then_update(db) -> None:
    async with db.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="o@v4.com", full_name=None)
        c1 = await google_oauth_connections.upsert(
            conn,
            manager_id=mid,
            google_email="o@v4.com",
            refresh_token_enc=b"enc-v1",
            scopes=["adwords"],
        )
        c2 = await google_oauth_connections.upsert(
            conn,
            manager_id=mid,
            google_email="o@v4.com",
            refresh_token_enc=b"enc-v2",
            scopes=["adwords"],
        )
        # Same row (UNIQUE constraint), refresh updated.
        assert c1.id == c2.id
        assert c2.refresh_token_enc == b"enc-v2"


@pytest.mark.integration
async def test_oauth_get_active_returns_latest(db) -> None:
    async with db.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="g@v4.com", full_name=None)
        c1 = await google_oauth_connections.upsert(
            conn,
            manager_id=mid,
            google_email="primary@gmail.com",
            refresh_token_enc=b"e1",
            scopes=["adwords"],
        )
        c2 = await google_oauth_connections.upsert(
            conn,
            manager_id=mid,
            google_email="other@gmail.com",
            refresh_token_enc=b"e2",
            scopes=["adwords"],
        )
        active = await google_oauth_connections.get_active_for_manager(conn, mid)
        assert active is not None
        # Most recent — c2 was inserted after c1.
        assert active.id == c2.id

        await google_oauth_connections.revoke(conn, c2.id)
        active_after = await google_oauth_connections.get_active_for_manager(conn, mid)
        assert active_after is not None
        assert active_after.id == c1.id


# ---------- google_ads_accounts ----------


@pytest.mark.integration
async def test_accounts_upsert_and_list(db) -> None:
    async with db.acquire() as conn:
        n = await google_ads_accounts.upsert_many(
            conn,
            [
                {
                    "customer_id": "1234567890",
                    "mcc_id": "9999999999",
                    "descriptive_name": "Cliente Alpha",
                    "currency_code": "BRL",
                    "time_zone": "America/Sao_Paulo",
                    "is_test_account": False,
                },
                {
                    "customer_id": "2345678901",
                    "mcc_id": "9999999999",
                    "descriptive_name": "Cliente Beta",
                    "currency_code": "BRL",
                    "time_zone": "America/Sao_Paulo",
                    "is_test_account": False,
                },
            ],
        )
        assert n == 2
        all_accounts = await google_ads_accounts.list_all(conn)
        assert len(all_accounts) == 2
        names = [a.descriptive_name for a in all_accounts]
        assert names == sorted(names)  # ORDER BY descriptive_name


@pytest.mark.integration
async def test_accounts_mark_inactive_except(db) -> None:
    async with db.acquire() as conn:
        await google_ads_accounts.upsert_many(
            conn,
            [
                {"customer_id": "111", "mcc_id": "MCC1", "descriptive_name": "A"},
                {"customer_id": "222", "mcc_id": "MCC1", "descriptive_name": "B"},
                {"customer_id": "333", "mcc_id": "MCC1", "descriptive_name": "C"},
            ],
        )
        deactivated = await google_ads_accounts.mark_inactive_except(
            conn, mcc_id="MCC1", keep_customer_ids=["111", "333"]
        )
        assert deactivated == 1
        active = await google_ads_accounts.list_all(conn)
        ids = {a.customer_id for a in active}
        assert ids == {"111", "333"}


@pytest.mark.integration
async def test_accounts_mark_inactive_except_keep_list_vazia_e_no_op(db) -> None:
    """F85: contra banco de verdade, keep-list vazia não pode tocar linha alguma.

    O unit test prova que o UPDATE não é emitido; este prova o efeito — as contas
    continuam ativas. Era o caso em que `fetch_account_details` devolvia `[]` sem
    exceção e o MCC inteiro sumia do painel por 24h.
    """
    async with db.acquire() as conn:
        await google_ads_accounts.upsert_many(
            conn,
            [
                {"customer_id": "901", "mcc_id": "MCC_F85", "descriptive_name": "A"},
                {"customer_id": "902", "mcc_id": "MCC_F85", "descriptive_name": "B"},
            ],
        )

        deactivated = await google_ads_accounts.mark_inactive_except(
            conn, mcc_id="MCC_F85", keep_customer_ids=[]
        )
        assert deactivated == 0
        ativos = {a.customer_id for a in await google_ads_accounts.list_all(conn)}
        assert {"901", "902"} <= ativos, "keep-list vazia desativou conta viva"

        # A capacidade não sumiu — só deixou de ser o default silencioso.
        deactivated = await google_ads_accounts.mark_inactive_except(
            conn, mcc_id="MCC_F85", keep_customer_ids=[], allow_full_deactivation=True
        )
        assert deactivated == 2
        ativos = {a.customer_id for a in await google_ads_accounts.list_all(conn)}
        assert not ({"901", "902"} & ativos)


# ---------- manager_account_access ----------


@pytest.mark.integration
async def test_access_grant_list_revoke(db) -> None:
    async with db.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="a@v4.com", full_name=None)
        await google_ads_accounts.upsert_many(
            conn,
            [{"customer_id": "111", "mcc_id": "M1", "descriptive_name": "X"}],
        )
        await manager_account_access.grant(conn, manager_id=mid, customer_id="111")

        accounts = await manager_account_access.list_accounts_for_manager(conn, mid)
        assert len(accounts) == 1
        assert accounts[0].customer_id == "111"

        assert await manager_account_access.can_manager_access(conn, mid, "111") is True
        assert await manager_account_access.can_manager_access(conn, mid, "999") is False

        await manager_account_access.revoke(conn, manager_id=mid, customer_id="111")
        accounts2 = await manager_account_access.list_accounts_for_manager(conn, mid)
        assert accounts2 == []


@pytest.mark.integration
async def test_access_grant_all_active(db) -> None:
    async with db.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="ga@v4.com", full_name=None)
        await google_ads_accounts.upsert_many(
            conn,
            [
                {"customer_id": "111", "mcc_id": "M1", "descriptive_name": "A"},
                {"customer_id": "222", "mcc_id": "M1", "descriptive_name": "B"},
            ],
        )
        n = await manager_account_access.grant_all_active(conn, manager_id=mid)
        assert n == 2
        accounts = await manager_account_access.list_accounts_for_manager(conn, mid)
        assert len(accounts) == 2

        # Idempotent re-run inserts 0 (ON CONFLICT DO NOTHING).
        n2 = await manager_account_access.grant_all_active(conn, manager_id=mid)
        assert n2 == 0


@pytest.mark.integration
async def test_gate_nega_conta_inativa_com_grant_vivo(db) -> None:
    """F-gate: 34 grants vivos em 9 contas fora do MCC (medido 2026-09-05).

    O gate antigo aprovava os 34 — quem os negava era o Google, não nós.
    """
    async with db.acquire() as conn:
        mid = await _make_manager(conn, "gate@v4company.com")
        await google_ads_accounts.upsert_many(
            conn,
            [{"customer_id": "555", "mcc_id": "6436352492", "descriptive_name": "Ex-cliente"}],
        )
        await manager_account_access.grant(conn, manager_id=mid, customer_id="555")
        assert await manager_account_access.can_manager_access(conn, mid, "555") is True

        # A conta sai do MCC.
        await conn.execute(
            "UPDATE google_ads_accounts SET is_active = false WHERE customer_id = '555'"
        )
        assert await manager_account_access.can_manager_access(conn, mid, "555") is False
        assert (
            await manager_account_access.can_manager_access(conn, mid, "555", level="write")
            is False
        )


# ---------- audit_log ----------


@pytest.mark.integration
async def test_audit_record_returns_id(db) -> None:
    async with db.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="al@v4.com", full_name=None)
        log_id = await audit_log.record(
            conn,
            manager_id=mid,
            session_id=None,
            customer_id="1234567890",
            action_type="read",
            operation="list_my_accounts",
            target_count=29,
            params_summary={"foo": "bar"},
            status="success",
            duration_ms=42,
        )
        assert log_id > 0


# ---------- meta_oauth_connections ----------


@pytest.mark.integration
async def test_meta_oauth_upsert_then_update(db) -> None:
    from datetime import datetime, timedelta, timezone

    async with db.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="mo@v4.com", full_name=None)
        future = datetime.now(timezone.utc) + timedelta(days=60)  # noqa: UP017
        c1 = await meta_oauth_connections.upsert(
            conn,
            manager_id=mid,
            fb_user_id="123456789",
            fb_email="mo@gmail.com",
            access_token_enc=b"enc-v1",
            token_expires_at=future,
            scopes=["ads_read", "ads_management"],
        )
        c2 = await meta_oauth_connections.upsert(
            conn,
            manager_id=mid,
            fb_user_id="123456789",
            fb_email="mo@gmail.com",
            access_token_enc=b"enc-v2",
            token_expires_at=future,
            scopes=["ads_read", "ads_management", "business_management"],
        )
        # Same row (UNIQUE on manager_id + fb_user_id), token updated.
        assert c1.id == c2.id
        assert c2.access_token_enc == b"enc-v2"
        assert "business_management" in c2.scopes


@pytest.mark.integration
async def test_meta_oauth_get_active_returns_latest_non_revoked(db) -> None:
    import asyncio
    from datetime import datetime, timedelta, timezone

    async with db.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="mg@v4.com", full_name=None)
        future = datetime.now(timezone.utc) + timedelta(days=60)  # noqa: UP017
        c1 = await meta_oauth_connections.upsert(
            conn,
            manager_id=mid,
            fb_user_id="111",
            fb_email="primary@fb.com",
            access_token_enc=b"e1",
            token_expires_at=future,
            scopes=["ads_read"],
        )
        await asyncio.sleep(0.01)  # force connected_at to differ on fast CI
        c2 = await meta_oauth_connections.upsert(
            conn,
            manager_id=mid,
            fb_user_id="222",
            fb_email="other@fb.com",
            access_token_enc=b"e2",
            token_expires_at=future,
            scopes=["ads_read"],
        )
        active = await meta_oauth_connections.get_active_for_manager(conn, mid)
        assert active is not None
        # Most recent inserted wins.
        assert active.id == c2.id

        await meta_oauth_connections.revoke(conn, c2.id)
        active_after = await meta_oauth_connections.get_active_for_manager(conn, mid)
        assert active_after is not None
        assert active_after.id == c1.id


@pytest.mark.integration
async def test_meta_oauth_get_active_none_when_no_connection(db) -> None:
    async with db.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="mn@v4.com", full_name=None)
        result = await meta_oauth_connections.get_active_for_manager(conn, mid)
        assert result is None


# ---------- meta_ad_accounts ----------


@pytest.mark.integration
async def test_meta_accounts_upsert_and_list(db) -> None:
    async with db.acquire() as conn:
        n = await meta_ad_accounts.upsert_many(
            conn,
            [
                {
                    "ad_account_id": "act_111",
                    "business_id": "bm_999",
                    "business_name": "V4 Lima Soares & Co",
                    "account_name": "Cliente Alpha Meta",
                    "currency": "BRL",
                    "timezone_name": "America/Sao_Paulo",
                    "account_status": 1,
                },
                {
                    "ad_account_id": "act_222",
                    "business_id": "bm_999",
                    "business_name": "V4 Lima Soares & Co",
                    "account_name": "Cliente Beta Meta",
                    "currency": "BRL",
                    "timezone_name": "America/Sao_Paulo",
                    "account_status": 1,
                },
            ],
        )
        assert n == 2
        all_accounts = await meta_ad_accounts.list_all(conn)
        assert len(all_accounts) == 2
        names = [a.account_name for a in all_accounts]
        assert names == sorted(names)  # ORDER BY account_name


# M1 (revisao de branch): `test_meta_accounts_mark_inactive_except` e
# `test_meta_accounts_mark_inactive_empty_keep_list` sairam junto com a funcao
# que testavam. Ela ficou sem chamador quando o reconciliador passou a decidir
# por `build_plan`, e carregava a forma do F85 (keep-list vazia = desative tudo)
# sem o guard que o gemeo Google tem. A desativacao agora e `deactivate()`, que
# so mexe na lista explicita e cujos testes vivem em test_meta_reconcile_repo.py.


@pytest.mark.integration
async def test_meta_accounts_personal_no_business_id(db) -> None:
    """Ad account 'personal' (sem Business Manager) é legal Meta — business_id NULL."""
    async with db.acquire() as conn:
        n = await meta_ad_accounts.upsert_many(
            conn,
            [
                {
                    "ad_account_id": "act_personal",
                    "business_id": None,
                    "account_name": "Personal Account",
                    "account_status": 1,
                }
            ],
        )
        assert n == 1
        all_accounts = await meta_ad_accounts.list_all(conn)
        assert len(all_accounts) == 1
        assert all_accounts[0].business_id is None


@pytest.mark.integration
async def test_meta_accounts_get_by_id(db) -> None:
    async with db.acquire() as conn:
        await meta_ad_accounts.upsert_many(
            conn,
            [{"ad_account_id": "act_xyz", "account_name": "XYZ", "account_status": 1}],
        )
        found = await meta_ad_accounts.get_by_id(conn, "act_xyz")
        assert found is not None
        assert found.ad_account_id == "act_xyz"
        assert found.account_name == "XYZ"

        missing = await meta_ad_accounts.get_by_id(conn, "act_does_not_exist")
        assert missing is None


# ---------- manager_meta_account_access ----------


@pytest.mark.integration
async def test_meta_access_grant_list_revoke(db) -> None:
    async with db.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="ma@v4.com", full_name=None)
        await meta_ad_accounts.upsert_many(
            conn,
            [
                {"ad_account_id": "act_111", "business_id": "bm_X", "account_name": "X"},
            ],
        )
        await manager_meta_account_access.grant(conn, manager_id=mid, ad_account_id="act_111")

        accounts = await manager_meta_account_access.list_accounts_for_manager(conn, mid)
        assert len(accounts) == 1
        assert accounts[0].ad_account_id == "act_111"

        assert await manager_meta_account_access.can_manager_access(conn, mid, "act_111") is True
        assert await manager_meta_account_access.can_manager_access(conn, mid, "act_999") is False

        assert (
            await manager_meta_account_access.can_manager_access(
                conn, mid, "act_111", level="write"
            )
            is True
        )

        await manager_meta_account_access.revoke(conn, manager_id=mid, ad_account_id="act_111")
        accounts2 = await manager_meta_account_access.list_accounts_for_manager(conn, mid)
        assert accounts2 == []


@pytest.mark.integration
async def test_meta_access_grant_all_active(db) -> None:
    async with db.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="mga@v4.com", full_name=None)
        await meta_ad_accounts.upsert_many(
            conn,
            [
                {"ad_account_id": "act_a", "business_id": "bm_A", "account_name": "A"},
                {"ad_account_id": "act_b", "business_id": "bm_A", "account_name": "B"},
            ],
        )
        n = await manager_meta_account_access.grant_all_active(conn, manager_id=mid)
        assert n == 2
        accounts = await manager_meta_account_access.list_accounts_for_manager(conn, mid)
        assert len(accounts) == 2

        # I4 (revisao de branch): a re-execucao passou a tocar as 2 linhas (era
        # `DO NOTHING`, que devolvia 0). O que importa nao e o numero e sim que
        # reconceder RESTAURA: sob revogacao soft a linha revogada persiste, e o
        # `DO NOTHING` pulava em silencio justo a conta em que o gestor tinha
        # perdido acesso — "conceder tudo" dava tudo MENOS o que ele ja perdera.
        n2 = await manager_meta_account_access.grant_all_active(conn, manager_id=mid)
        assert n2 == 2
        assert len(await manager_meta_account_access.list_accounts_for_manager(conn, mid)) == 2


@pytest.mark.integration
async def test_meta_access_grant_all_active_restaura_grant_revogado(db) -> None:
    """I4: a linha revogada nao pode ser pulada pelo ON CONFLICT."""
    async with db.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="mga2@v4.com", full_name=None)
        await meta_ad_accounts.upsert_many(
            conn,
            [
                {"ad_account_id": "act_ga1", "business_id": "bm_A", "account_name": "A"},
                {"ad_account_id": "act_ga2", "business_id": "bm_A", "account_name": "B"},
            ],
        )
        await manager_meta_account_access.grant_all_active(conn, manager_id=mid)
        await manager_meta_account_access.revoke(
            conn, manager_id=mid, ad_account_id="act_ga1", reason="manual"
        )
        assert await manager_meta_account_access.can_manager_access(conn, mid, "act_ga1") is False

        await manager_meta_account_access.grant_all_active(conn, manager_id=mid)

        assert await manager_meta_account_access.can_manager_access(conn, mid, "act_ga1") is True
        linha = await conn.fetchrow(
            "SELECT revoked_at, revoked_reason FROM manager_meta_account_access "
            "WHERE manager_id = $1 AND ad_account_id = 'act_ga1'",
            mid,
        )
        assert linha["revoked_at"] is None
        assert linha["revoked_reason"] is None


@pytest.mark.integration
async def test_meta_copy_access_recusa_origem_igual_ao_destino(db) -> None:
    """T5e: sem o guard, copiar pra si mesmo aniquila o proprio gestor — o
    UPDATE de limpeza revoga tudo e o SELECT seguinte (`revoked_at IS NULL`) ja
    nao acha nada pra reconceder. A rota checa, mas o repositorio tem chamador
    potencial fora dela."""
    async with db.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="self@v4.com", full_name=None)
        await meta_ad_accounts.upsert_many(
            conn, [{"ad_account_id": "act_self", "business_id": "bm_A", "account_name": "A"}]
        )
        await manager_meta_account_access.grant_all_active(conn, manager_id=mid)

        with pytest.raises(ValueError):
            await manager_meta_account_access.copy_access(
                conn, from_manager_id=mid, to_manager_id=mid, granted_by=mid
            )

        assert await manager_meta_account_access.can_manager_access(conn, mid, "act_self") is True


@pytest.mark.integration
async def test_meta_access_bulk_grant_idempotent(db) -> None:
    async with db.acquire() as conn:
        mid = uuid4()
        granter = uuid4()
        await managers.create(conn, manager_id=mid, email="bg@v4.com", full_name=None)
        await managers.create(conn, manager_id=granter, email="granter@v4.com", full_name=None)
        await meta_ad_accounts.upsert_many(
            conn,
            [
                {"ad_account_id": "act_bg1", "business_id": "bm_BG", "account_name": "BG1"},
                {"ad_account_id": "act_bg2", "business_id": "bm_BG", "account_name": "BG2"},
            ],
        )

        n = await manager_meta_account_access.bulk_grant(
            conn,
            manager_id=mid,
            ad_account_ids=["act_bg1", "act_bg2"],
            granted_by=granter,
        )
        # bulk_grant returns len(ids), not actual inserts (documented)
        assert n == 2

        accounts = await manager_meta_account_access.list_accounts_for_manager(conn, mid)
        ids = {a.ad_account_id for a in accounts}
        assert ids == {"act_bg1", "act_bg2"}

        # Idempotent re-run with same ids returns 2 (per documented semantics)
        # but actually inserts 0 rows (ON CONFLICT DO NOTHING)
        n2 = await manager_meta_account_access.bulk_grant(
            conn,
            manager_id=mid,
            ad_account_ids=["act_bg1", "act_bg2"],
            granted_by=granter,
        )
        assert n2 == 2
        accounts_after = await manager_meta_account_access.list_accounts_for_manager(conn, mid)
        # Same accounts visible — no duplicates
        assert {a.ad_account_id for a in accounts_after} == {"act_bg1", "act_bg2"}


@pytest.mark.integration
async def test_meta_access_bulk_grant_empty_list_no_op(db) -> None:
    async with db.acquire() as conn:
        mid = uuid4()
        granter = uuid4()
        await managers.create(conn, manager_id=mid, email="bge@v4.com", full_name=None)
        await managers.create(conn, manager_id=granter, email="granter2@v4.com", full_name=None)
        n = await manager_meta_account_access.bulk_grant(
            conn, manager_id=mid, ad_account_ids=[], granted_by=granter
        )
        assert n == 0


@pytest.mark.integration
async def test_meta_copy_access_replaces_destination(db) -> None:
    async with db.acquire() as conn:
        m_a = uuid4()
        m_b = uuid4()
        await managers.create(conn, manager_id=m_a, email="ca@v4.com", full_name=None)
        await managers.create(conn, manager_id=m_b, email="cb@v4.com", full_name=None)
        await meta_ad_accounts.upsert_many(
            conn,
            [
                {"ad_account_id": "act_1", "business_id": "bm_C", "account_name": "C1"},
                {"ad_account_id": "act_2", "business_id": "bm_C", "account_name": "C2"},
            ],
        )
        await manager_meta_account_access.grant(conn, manager_id=m_a, ad_account_id="act_1")
        await manager_meta_account_access.grant(conn, manager_id=m_b, ad_account_id="act_2")
        n = await manager_meta_account_access.copy_access(
            conn, from_manager_id=m_a, to_manager_id=m_b, granted_by=m_a
        )
        assert n == 1
        accts = await manager_meta_account_access.list_accounts_for_manager(conn, m_b)
        assert {a.ad_account_id for a in accts} == {
            "act_1"
        }  # destination replaced with source's grants


# ---------- meta_rate_counters ----------


@pytest.mark.integration
async def test_meta_rate_counters_increment_creates_row_first_time(db) -> None:
    """First call insert row with calls_used=1."""
    from datetime import date

    async with db.acquire() as conn:
        today = date.today()
        n = await meta_rate_counters.increment_calls(
            conn, app_id="app_hash_abc", ad_account_id="act_111", date=today, by=1
        )
        assert n == 1
        row = await conn.fetchrow(
            "SELECT calls_used FROM meta_rate_counters WHERE app_id = $1 AND ad_account_id = $2 AND date = $3",
            "app_hash_abc",
            "act_111",
            today,
        )
        assert row is not None
        assert row["calls_used"] == 1


@pytest.mark.integration
async def test_meta_rate_counters_increment_adds_to_existing(db) -> None:
    """Subsequent calls increment same row."""
    from datetime import date

    async with db.acquire() as conn:
        today = date.today()
        await meta_rate_counters.increment_calls(
            conn, app_id="app_hash_xyz", ad_account_id="act_222", date=today, by=3
        )
        await meta_rate_counters.increment_calls(
            conn, app_id="app_hash_xyz", ad_account_id="act_222", date=today, by=2
        )
        row = await conn.fetchrow(
            "SELECT calls_used FROM meta_rate_counters WHERE app_id = $1 AND ad_account_id = $2 AND date = $3",
            "app_hash_xyz",
            "act_222",
            today,
        )
        assert row is not None
        assert row["calls_used"] == 5


@pytest.mark.integration
async def test_meta_rate_counters_update_throttle(db) -> None:
    """update_throttle writes pct + creates row if absent."""
    from datetime import date

    async with db.acquire() as conn:
        today = date.today()
        await meta_rate_counters.increment_calls(
            conn, app_id="app_hash_t", ad_account_id="act_t", date=today, by=1
        )
        await meta_rate_counters.update_throttle(
            conn, app_id="app_hash_t", ad_account_id="act_t", date=today, throttle_pct=42
        )
        row = await conn.fetchrow(
            "SELECT last_throttle_pct FROM meta_rate_counters WHERE app_id = $1 AND ad_account_id = $2 AND date = $3",
            "app_hash_t",
            "act_t",
            today,
        )
        assert row is not None
        assert row["last_throttle_pct"] == 42
