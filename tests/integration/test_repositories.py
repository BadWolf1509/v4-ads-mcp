"""Integration tests for all DB repositories.

One container, one set of migrations, then test each repository's
behavior against real SQL. We don't mock asyncpg — that yields
zero confidence in column names, constraints, or upsert behavior.
"""

import json
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
from src.jobs import account_resync


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
        # Task 3, decisão 3: faltava o caminho True do nível "write" — só o
        # False (conta inativa) era coberto em test_gate_nega_conta_inativa_com_
        # grant_vivo. O gêmeo Meta (test_meta_access_grant_list_revoke) já tinha
        # este assert; o lado Google não.
        assert (
            await manager_account_access.can_manager_access(conn, mid, "111", level="write") is True
        )

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

        # Task 3: a re-execução passou a TOCAR as 2 linhas (era `DO NOTHING`,
        # que devolvia 0). Sob revogação soft a linha revogada persiste, e o
        # `DO NOTHING` pulava em silêncio justo a conta que o gestor tinha
        # perdido — reconceder tem que RESTAURAR, não ignorar (espelha o gêmeo
        # Meta, test_meta_access_grant_all_active).
        n2 = await manager_account_access.grant_all_active(conn, manager_id=mid)
        assert n2 == 2
        assert len(await manager_account_access.list_accounts_for_manager(conn, mid)) == 2


@pytest.mark.integration
async def test_grant_all_active_restaura_grant_revogado(db) -> None:
    """A razão de trocar DO NOTHING por DO UPDATE: sem isso, `grant_all_active`
    reconcede tudo MENOS a conta que o gestor já tinha perdido por revogação —
    um "conceder tudo" que silenciosamente pula justo o caso que motivou o
    clique (espelha test_meta_access_grant_all_active_restaura_grant_revogado).
    """
    async with db.acquire() as conn:
        mid = await _make_manager(conn, "restaura-all@v4company.com")
        await google_ads_accounts.upsert_many(
            conn,
            [
                {"customer_id": "606", "mcc_id": "M1", "descriptive_name": "A"},
                {"customer_id": "607", "mcc_id": "M1", "descriptive_name": "B"},
            ],
        )
        await manager_account_access.grant_all_active(conn, manager_id=mid)
        await manager_account_access.revoke(conn, manager_id=mid, customer_id="606")
        assert await manager_account_access.can_manager_access(conn, mid, "606") is False

        await manager_account_access.grant_all_active(conn, manager_id=mid)

        assert await manager_account_access.can_manager_access(conn, mid, "606") is True
        linha = await conn.fetchrow(
            "SELECT revoked_at, revoked_reason FROM manager_account_access "
            "WHERE manager_id = $1 AND customer_id = '606'",
            mid,
        )
        assert linha["revoked_at"] is None
        assert linha["revoked_reason"] is None


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


@pytest.mark.integration
async def test_revoke_e_soft_e_o_gate_nega(db) -> None:
    async with db.acquire() as conn:
        mid = await _make_manager(conn, "soft@v4company.com")
        await google_ads_accounts.upsert_many(
            conn, [{"customer_id": "601", "mcc_id": "1", "descriptive_name": "X"}]
        )
        await manager_account_access.grant(conn, manager_id=mid, customer_id="601")
        await manager_account_access.revoke(conn, manager_id=mid, customer_id="601")

        # A LINHA FICA — é o que distingue soft de DELETE.
        row = await conn.fetchrow(
            "SELECT revoked_at, revoked_reason FROM manager_account_access "
            "WHERE manager_id = $1 AND customer_id = '601'",
            mid,
        )
        assert row is not None
        assert row["revoked_at"] is not None
        assert row["revoked_reason"] == manager_account_access.ADMIN_REVOKED_REASON
        assert await manager_account_access.can_manager_access(conn, mid, "601") is False


@pytest.mark.integration
async def test_reconceder_limpa_a_revogacao(db) -> None:
    """Sem isto, o `ON CONFLICT DO NOTHING` deixa o gestor bloqueado pra sempre."""
    async with db.acquire() as conn:
        mid = await _make_manager(conn, "regrant@v4company.com")
        await google_ads_accounts.upsert_many(
            conn, [{"customer_id": "602", "mcc_id": "1", "descriptive_name": "Y"}]
        )
        await manager_account_access.grant(conn, manager_id=mid, customer_id="602")
        await manager_account_access.revoke(conn, manager_id=mid, customer_id="602")
        assert await manager_account_access.can_manager_access(conn, mid, "602") is False

        await manager_account_access.bulk_grant(
            conn, manager_id=mid, customer_ids=["602"], granted_by=mid
        )
        assert await manager_account_access.can_manager_access(conn, mid, "602") is True


@pytest.mark.integration
async def test_revoke_for_inactive_pega_o_legado_nao_so_o_novo(db) -> None:
    """Os 34 grants de 2026-09-05 estavam em contas JA inativas.

    Um plano que parte de `ativos` nunca os alcançaria.
    """
    async with db.acquire() as conn:
        mid = await _make_manager(conn, "legado@v4company.com")
        await google_ads_accounts.upsert_many(
            conn, [{"customer_id": "603", "mcc_id": "1", "descriptive_name": "Ex"}]
        )
        await manager_account_access.grant(conn, manager_id=mid, customer_id="603")
        await conn.execute(
            "UPDATE google_ads_accounts SET is_active = false WHERE customer_id = '603'"
        )

        atingidos = await manager_account_access.revoke_for_inactive_accounts(conn)
        assert atingidos == {"603": [str(mid)]}
        row = await conn.fetchrow(
            "SELECT revoked_reason FROM manager_account_access WHERE customer_id = '603'"
        )
        assert row["revoked_reason"] == manager_account_access.LEFT_MCC_REASON


@pytest.mark.integration
async def test_restore_devolve_so_o_churn(db) -> None:
    async with db.acquire() as conn:
        a = await _make_manager(conn, "churn@v4company.com")
        b = await _make_manager(conn, "punido@v4company.com")
        await google_ads_accounts.upsert_many(
            conn, [{"customer_id": "604", "mcc_id": "1", "descriptive_name": "Z"}]
        )
        await manager_account_access.grant(conn, manager_id=a, customer_id="604")
        await manager_account_access.grant(conn, manager_id=b, customer_id="604")
        # b perdeu acesso de propósito; a perdeu por churn.
        await manager_account_access.revoke(conn, manager_id=b, customer_id="604")
        await conn.execute(
            "UPDATE google_ads_accounts SET is_active = false WHERE customer_id = '604'"
        )
        await manager_account_access.revoke_for_inactive_accounts(conn)
        await conn.execute(
            "UPDATE google_ads_accounts SET is_active = true WHERE customer_id = '604'"
        )

        restaurados = await manager_account_access.restore_for_account(conn, customer_id="604")
        assert restaurados == [str(a)]
        assert await manager_account_access.can_manager_access(conn, a, "604") is True
        assert await manager_account_access.can_manager_access(conn, b, "604") is False


@pytest.mark.integration
async def test_count_grants_on_inactive_accounts(db) -> None:
    """O número que o dry-run da Task 5 vai reportar como `revoke_candidates`.

    Leitura pura — não muta nada. Task 5 não roda nesta leva; a função entra
    aqui porque o brief a declarava como interface sem dono.
    """
    async with db.acquire() as conn:
        mid = await _make_manager(conn, "contagem@v4company.com")
        await google_ads_accounts.upsert_many(
            conn, [{"customer_id": "605", "mcc_id": "1", "descriptive_name": "W"}]
        )
        await manager_account_access.grant(conn, manager_id=mid, customer_id="605")
        assert await manager_account_access.count_grants_on_inactive_accounts(conn) == 0

        await conn.execute(
            "UPDATE google_ads_accounts SET is_active = false WHERE customer_id = '605'"
        )
        assert await manager_account_access.count_grants_on_inactive_accounts(conn) == 1

        # Revogado (mesmo em conta inativa) não é mais "grant VIVO" — some da contagem.
        await manager_account_access.revoke(conn, manager_id=mid, customer_id="605")
        assert await manager_account_access.count_grants_on_inactive_accounts(conn) == 0


# ---------- google_ads_accounts.list_queues (Task 6) ----------


@pytest.mark.integration
async def test_fila_delegacao_lista_conta_ativa_sem_grant(db) -> None:
    async with db.acquire() as conn:
        await google_ads_accounts.upsert_many(
            conn, [{"customer_id": "701", "mcc_id": "1", "descriptive_name": "Nova"}]
        )
        q = await google_ads_accounts.list_queues(conn)
        assert [r["customer_id"] for r in q.sem_delegacao] == ["701"]


@pytest.mark.integration
async def test_fila_de_restauracao_aparece_quando_a_conta_volta(db) -> None:
    """C1 da revisão Meta: chavear em is_active=false faz a conta sumir da fila
    exatamente quando ela se torna restaurável.

    Verificado por sabotagem (2026-09-05): trocando `a.is_active = true` por
    `a.is_active = false` no predicado de `voltaram` em `list_queues`, a
    primeira asserção abaixo (fila vazia enquanto a conta está fora do MCC)
    passa a FALHAR — a conta aparece na fila justamente enquanto está
    inativa, o oposto do que a fila existe para garantir. Ver task-6-report.md
    pela saída literal do pytest com a sabotagem aplicada.
    """
    async with db.acquire() as conn:
        mid = await _make_manager(conn, "volta@v4company.com")
        await google_ads_accounts.upsert_many(
            conn, [{"customer_id": "702", "mcc_id": "1", "descriptive_name": "Voltou"}]
        )
        await manager_account_access.grant(conn, manager_id=mid, customer_id="702")
        await conn.execute(
            "UPDATE google_ads_accounts SET is_active = false WHERE customer_id = '702'"
        )
        await manager_account_access.revoke_for_inactive_accounts(conn)

        # Enquanto FORA do MCC: não é restaurável, o gate exige conta ativa.
        q = await google_ads_accounts.list_queues(conn)
        assert [r["customer_id"] for r in q.voltaram_ao_mcc] == []

        # Voltou ao MCC — agora sim.
        await google_ads_accounts.upsert_many(
            conn, [{"customer_id": "702", "mcc_id": "1", "descriptive_name": "Voltou"}]
        )
        q = await google_ads_accounts.list_queues(conn)
        assert [r["customer_id"] for r in q.voltaram_ao_mcc] == ["702"]
        assert [r["customer_id"] for r in q.sem_delegacao] == []  # exclusiva


@pytest.mark.integration
async def test_fila_de_restauracao_ignora_revogacao_administrativa(db) -> None:
    """Revogação por decisão do admin não é churn — não pode aparecer em
    `voltaram_ao_mcc` (só `restore_for_account` lida com isso, e ele também
    ignora `ADMIN_REVOKED_REASON` de propósito) nem sumir de `sem_delegacao`.

    Espelha `test_fila_saiu_ignora_conta_sem_revogacao_por_churn` do gêmeo Meta.
    """
    async with db.acquire() as conn:
        mid = await _make_manager(conn, "admin-revoke@v4company.com")
        await google_ads_accounts.upsert_many(
            conn, [{"customer_id": "703", "mcc_id": "1", "descriptive_name": "Punida"}]
        )
        await manager_account_access.grant(conn, manager_id=mid, customer_id="703")
        await manager_account_access.revoke(conn, manager_id=mid, customer_id="703")

        q = await google_ads_accounts.list_queues(conn)
        assert q.voltaram_ao_mcc == []
        assert [r["customer_id"] for r in q.sem_delegacao] == ["703"]


# ---------- account_resync.reconcile_google (Task 5) ----------


@pytest.mark.integration
async def test_conta_nova_aparece_em_added(db) -> None:
    """Se o upsert rodasse ANTES da leitura, `added` sairia sempre 0.

    `upsert_many` marca is_active=true e zera missed_syncs pra toda conta do
    MCC — lido depois dele, o inventário já parece "em dia" e a auditoria nunca
    reporta conta nova. Achado da revisão do sprint Meta, round 1.
    """
    async with db.acquire() as conn:
        resumo = await account_resync.reconcile_google(
            conn,
            accounts=[{"customer_id": "801", "mcc_id": "1", "descriptive_name": "Nova"}],
            complete=True,
            apply=False,
        )
        assert resumo["added"] == 1

        # Segunda execução: a conta já está no inventário, não é mais "nova".
        resumo = await account_resync.reconcile_google(
            conn,
            accounts=[{"customer_id": "801", "mcc_id": "1", "descriptive_name": "Nova"}],
            complete=True,
            apply=False,
        )
        assert resumo["added"] == 0


@pytest.mark.integration
async def test_conta_reativada_zera_missed_syncs_e_sobrevive_a_ausencia_seguinte(db) -> None:
    """C1 (revisão de branch, 2026-09-05): o F128 do lado Meta tinha voltado no
    Google — faltava `missed_syncs = 0` no `ON CONFLICT DO UPDATE` de
    `upsert_many` (`google_ads_accounts.py`).

    Cenário medido: conta desativada por churn com `missed_syncs=3` (o limiar)
    volta ao MCC. `to_reset` não a alcança — é calculado a partir de `ativos`
    no inventário lido ANTES do upsert, onde ela ainda estava inativa
    (`build_plan` só considera contas ativas pra decidir reset). Sem a
    cláusula no upsert, `missed_syncs` continuava 3 depois de reativada, e
    bastava UMA ausência seguinte (`3 + 1 >= 3`) pra removê-la de novo no
    mesmo dia, levando o grant do gestor junto — carência zero justamente
    para as contas que mais oscilam.
    """
    async with db.acquire() as conn:
        mid = await _make_manager(conn, "reativada@v4company.com")
        await google_ads_accounts.upsert_many(
            conn, [{"customer_id": "901", "mcc_id": "1", "descriptive_name": "Oscila"}]
        )
        await manager_account_access.grant(conn, manager_id=mid, customer_id="901")
        # Simula o estado de uma conta já desativada por churn, no limiar.
        await conn.execute(
            "UPDATE google_ads_accounts SET is_active = false, missed_syncs = 3 "
            "WHERE customer_id = '901'"
        )

        # A conta volta a aparecer no MCC.
        resumo = await account_resync.reconcile_google(
            conn,
            accounts=[{"customer_id": "901", "mcc_id": "1", "descriptive_name": "Oscila"}],
            complete=True,
            apply=True,
        )
        assert resumo["removed"] == 0
        row = await conn.fetchrow(
            "SELECT is_active, missed_syncs FROM google_ads_accounts WHERE customer_id = '901'"
        )
        assert row["is_active"] is True
        assert row["missed_syncs"] == 0, (
            "F128 voltou: upsert_many nao zerou missed_syncs de quem reapareceu"
        )

        # A ausência SEGUINTE não pode remover quem acabou de voltar.
        resumo2 = await account_resync.reconcile_google(
            conn, accounts=[], complete=True, apply=True
        )
        assert resumo2["removed"] == 0, (
            "carencia zero: uma unica ausencia removeu quem acabou de ser reativado"
        )
        ativos = {a.customer_id for a in await google_ads_accounts.list_all(conn)}
        assert "901" in ativos
        assert await manager_account_access.can_manager_access(conn, mid, "901") is True


@pytest.mark.integration
async def test_trava_desligada_nao_revoga_mas_reporta(db) -> None:
    """O dry-run tem de OBSERVAR o que a virada fará, senão o soak não serve."""
    async with db.acquire() as conn:
        mid = await _make_manager(conn, "dry@v4company.com")
        await google_ads_accounts.upsert_many(
            conn, [{"customer_id": "802", "mcc_id": "1", "descriptive_name": "Sai"}]
        )
        await manager_account_access.grant(conn, manager_id=mid, customer_id="802")
        await conn.execute(
            "UPDATE google_ads_accounts SET is_active = false WHERE customer_id = '802'"
        )

        resumo = await account_resync.reconcile_google(
            conn, accounts=[], complete=True, apply=False
        )
        assert resumo["applied"] is False
        assert resumo["revoked_grants"] == 0
        # ...MAS o dry-run tem de OBSERVAR o que a virada fará. Sem este
        # contador, o soak inteiro reporta zero e não distingue "não há o que
        # revogar" de "há 34 e a trava está segurando".
        assert resumo["revoke_candidates"] == 1
        # A linha continua VIVA — a trava governa destruição, não observação.
        assert await conn.fetchval(
            "SELECT revoked_at IS NULL FROM manager_account_access WHERE customer_id = '802'"
        )


@pytest.mark.integration
async def test_revoke_candidates_preve_o_que_esta_execucao_vai_revogar(db) -> None:
    """I1 (revisão de branch, 2026-09-05): `revoke_candidates` só somava o
    backlog (`count_grants_on_inactive_accounts`, contas JÁ `is_active=false`)
    — cego para os grants das contas que O PLANO DESTA EXECUÇÃO vai desativar
    (`plano.to_remove`), porque a contagem roda antes do `deactivate()`.

    Diferença para `test_trava_desligada_nao_revoga_mas_reporta` acima: lá
    "802" já estava inativa ANTES da chamada (puro backlog). Aqui "903" está
    ATIVA a 1 ausência do limiar — é o plano desta MESMA execução que decide
    removê-la, e é exatamente esse caso que o backlog sozinho não alcança.

    Medido (pré-fix): `revoke_candidates=0` nos dois modos (dry-run e apply) —
    o soak reportava zero na véspera de revogar.
    """
    async with db.acquire() as conn:
        mid = await _make_manager(conn, "candidato@v4company.com")
        await google_ads_accounts.upsert_many(
            conn, [{"customer_id": "903", "mcc_id": "1", "descriptive_name": "Vai_Sair"}]
        )
        await conn.execute(
            "UPDATE google_ads_accounts SET missed_syncs = 2 WHERE customer_id = '903'"
        )
        await manager_account_access.grant(conn, manager_id=mid, customer_id="903")

        # Dry-run: nada é revogado de fato, mas o contador tem que PREVER.
        resumo = await account_resync.reconcile_google(
            conn, accounts=[], complete=True, apply=False
        )
        assert resumo["removed"] == 1, "missed_syncs 2+1 >= limiar 3: o plano remove a conta"
        assert resumo["revoked_grants"] == 0
        assert resumo["revoke_candidates"] == 1, (
            "dry-run as cegas pra propria execucao — reporta zero na vespera de revogar"
        )
        assert await manager_account_access.can_manager_access(conn, mid, "903") is True

        # Mesmo estado, agora com apply=True: a MESMA previsão, de fato aplicada.
        resumo2 = await account_resync.reconcile_google(
            conn, accounts=[], complete=True, apply=True
        )
        assert resumo2["removed"] == 1
        assert resumo2["revoke_candidates"] == 1
        assert resumo2["revoked_grants"] == 1
        assert await manager_account_access.can_manager_access(conn, mid, "903") is False


@pytest.mark.integration
async def test_revogacao_automatica_grava_trilha_por_conta(db) -> None:
    """C2 (revisão de branch, 2026-09-05): `revoke_for_inactive_accounts` devolve
    customer_id -> manager_ids — quem perdeu o quê —, mas o job só somava um
    inteiro (`revogados`) e descartava o resto. O ESTADO da tabela não é
    trilha: reconceder por qualquer caminho (`grant`/`bulk_grant`/
    `grant_all_active`/`copy_access`) zera `revoked_at`/`revoked_reason` de
    volta pra NULL, e depois disso não sobra registro nenhum de que um acesso
    humano foi retirado, e por quê. Espelha `meta_resync` (`meta_access_cleanup`).
    """
    async with db.acquire() as conn:
        mid = await _make_manager(conn, "trilha-google@v4company.com")
        await google_ads_accounts.upsert_many(
            conn, [{"customer_id": "904", "mcc_id": "1", "descriptive_name": "Sai_Google"}]
        )
        await conn.execute(
            "UPDATE google_ads_accounts SET missed_syncs = 2 WHERE customer_id = '904'"
        )
        await manager_account_access.grant(conn, manager_id=mid, customer_id="904")

        await account_resync.reconcile_google(conn, accounts=[], complete=True, apply=True)

        row = await conn.fetchrow(
            """SELECT operation, platform, action_type, status, customer_id, params_summary
                 FROM audit_log WHERE operation = 'google_access_cleanup'
                ORDER BY occurred_at DESC LIMIT 1"""
        )
        assert row is not None, "revogacao automatica sem NENHUMA trilha no audit_log"
        assert row["platform"] == "google"
        assert row["action_type"] == "mutate"
        assert row["status"] == "success"
        assert row["customer_id"] == "904"
        params = json.loads(row["params_summary"])
        assert params["reason"] == manager_account_access.LEFT_MCC_REASON
        assert params["managers"] == [str(mid)]


@pytest.mark.integration
async def test_dry_run_nao_revoga_e_nao_audita_revogacao(db) -> None:
    """Contraparte do teste acima: sem `apply`, nada é revogado — e a trilha de
    revogação (`google_access_cleanup`) não pode aparecer vazia de propósito,
    senão o audit mentiria sobre uma revogação que não aconteceu."""
    async with db.acquire() as conn:
        mid = await _make_manager(conn, "dry-trilha@v4company.com")
        await google_ads_accounts.upsert_many(
            conn, [{"customer_id": "905", "mcc_id": "1", "descriptive_name": "Sai_Dry"}]
        )
        await conn.execute(
            "UPDATE google_ads_accounts SET missed_syncs = 2 WHERE customer_id = '905'"
        )
        await manager_account_access.grant(conn, manager_id=mid, customer_id="905")

        await account_resync.reconcile_google(conn, accounts=[], complete=True, apply=False)

        row = await conn.fetchrow(
            "SELECT 1 FROM audit_log WHERE operation = 'google_access_cleanup' "
            "AND customer_id = '905'"
        )
        assert row is None, "dry-run nao pode gravar trilha de uma revogacao que nao aconteceu"


@pytest.mark.integration
async def test_inventario_vazio_nao_desativa_nem_revoga_mesmo_com_trava_ligada(db) -> None:
    """A proteção do F85 mudou de lugar — este é o guard do lugar NOVO.

    Até aqui `mark_inactive_except` era o único guardião (keep-list vazia virava
    no-op). O job diário parou de chamar essa função; quem protege agora é o
    `complete=inventario_ok` que alimenta `build_plan()` dentro de
    `reconcile_google`. Prova a propriedade contra banco real, com a trava
    (`apply`) LIGADA de propósito — o pior caso é leitura vazia no mesmo dia em
    que `google_reconcile_apply` está true, e mesmo assim tem de sair zero.

    "701" está deliberadamente a 1 ausência do limiar (a próxima ausência
    cruzaria `threshold=3`): se `complete` fosse True aqui (em vez de False),
    esta MESMA chamada removeria "701" e revogaria os dois grants. É a
    verificação por sabotagem que a task pediu — feita à parte (não commitada),
    forçando complete=True numa cópia deste teste: `removed` foi de 0 para 1,
    `applied` de False para True, `revoked_grants` de 0 para 2, e a leitura de
    `revoked_at IS NULL` de ambos os grants virou False. O teste como está aqui
    (complete=False) fica VERDE; a variante sabotada fica VERMELHA.
    """
    async with db.acquire() as conn:
        mid = await _make_manager(conn, "sabotagem@v4company.com")
        await google_ads_accounts.upsert_many(
            conn,
            [
                {"customer_id": "701", "mcc_id": "1", "descriptive_name": "Sobrevive"},
                {"customer_id": "702", "mcc_id": "1", "descriptive_name": "Ja_Saiu"},
            ],
        )
        await conn.execute(
            "UPDATE google_ads_accounts SET missed_syncs = 2 WHERE customer_id = '701'"
        )
        # "702" já tinha saído do MCC num resync anterior — grant vivo em conta
        # inativa, exatamente o estado que motivou `revoke_candidates` (34
        # grants em produção em 2026-09-05).
        await conn.execute(
            "UPDATE google_ads_accounts SET is_active = false WHERE customer_id = '702'"
        )
        await manager_account_access.grant(conn, manager_id=mid, customer_id="701")
        await manager_account_access.grant(conn, manager_id=mid, customer_id="702")

        resumo = await account_resync.reconcile_google(
            conn, accounts=[], complete=False, apply=True
        )

        assert resumo["blocked_reason"] is not None
        assert resumo["applied"] is False
        assert resumo["removed"] == 0
        assert resumo["revoked_grants"] == 0
        # Observabilidade não pode morrer com a trava: "702" segue contando.
        assert resumo["revoke_candidates"] == 1

        ativos = {a.customer_id for a in await google_ads_accounts.list_all(conn)}
        assert "701" in ativos, "inventário vazio não pode desativar conta viva"
        for cid in ("701", "702"):
            assert await conn.fetchval(
                "SELECT revoked_at IS NULL FROM manager_account_access "
                "WHERE manager_id = $1 AND customer_id = $2",
                mid,
                cid,
            ), f"grant de {cid} não pode ser revogado com leitura incompleta"


@pytest.mark.integration
async def test_copy_access_nao_ressuscita_grant_revogado(db) -> None:
    """Achado extra (Task 3, fora das 4 decisões originais, E4): o SELECT da
    origem não excluía grant revogado — copiar de um gestor com um grant
    revogado de propósito ressuscitava esse grant como vivo pro destino,
    porque o INSERT não gravava `revoked_at` (ficava NULL por default). Mesmo
    bug que o gêmeo Meta documentou e fechou como C1; antes desta task o
    Google nunca tinha linha revogada pra ressuscitar, porque `revoke` era
    DELETE.

    Não testa a forma do destino (soft-revoke desde o I2) porque `destino`
    aqui começa sem nenhuma linha — ver
    `test_copy_access_nao_apaga_a_trilha_de_left_mcc_do_destino` pra isso.
    """
    async with db.acquire() as conn:
        origem = await _make_manager(conn, "copia-origem@v4company.com")
        destino = await _make_manager(conn, "copia-destino@v4company.com")
        await google_ads_accounts.upsert_many(
            conn, [{"customer_id": "608", "mcc_id": "1", "descriptive_name": "Copiada"}]
        )
        await manager_account_access.grant(conn, manager_id=origem, customer_id="608")
        await manager_account_access.revoke(conn, manager_id=origem, customer_id="608")

        n = await manager_account_access.copy_access(
            conn, from_manager_id=origem, to_manager_id=destino, granted_by=origem
        )

        assert n == 0
        assert await manager_account_access.can_manager_access(conn, destino, "608") is False
        assert await manager_account_access.list_accounts_for_manager(conn, destino) == []


@pytest.mark.integration
async def test_copy_access_nao_apaga_a_trilha_de_left_mcc_do_destino(db) -> None:
    """I2 (revisão de branch, reverte a decisão original do brief): `copy_access`
    soft-revoga o destino (razão própria `bulk_copy_replaced`) em vez de
    apagar — a linha `left_mcc` que o destino já tinha sobrevive à cópia e
    continua restaurável quando a conta volta ao MCC.

    Cenário do achado: conta 609 sai do MCC -> `revoke_for_inactive_accounts`
    marca `destino` como `left_mcc` -> admin copia o acesso de `origem` pra
    `destino` -> sob o DELETE cru do brief original, a linha `left_mcc` de
    `destino` seria apagada aqui -> 609 volta ao MCC -> `restore_for_account`
    devolveria só quem sobrou, nunca mais `destino`, em silêncio e
    permanentemente.
    """
    async with db.acquire() as conn:
        origem = await _make_manager(conn, "trilha-origem@v4company.com")
        destino = await _make_manager(conn, "trilha-destino@v4company.com")
        await google_ads_accounts.upsert_many(
            conn,
            [
                {"customer_id": "609", "mcc_id": "1", "descriptive_name": "Churn"},
                {"customer_id": "610", "mcc_id": "1", "descriptive_name": "Nova"},
            ],
        )

        # destino tinha acesso a 609, que saiu do MCC (churn) antes da cópia.
        await manager_account_access.grant(conn, manager_id=destino, customer_id="609")
        await conn.execute(
            "UPDATE google_ads_accounts SET is_active = false WHERE customer_id = '609'"
        )
        await manager_account_access.revoke_for_inactive_accounts(conn)
        antes = await conn.fetchrow(
            "SELECT revoked_reason FROM manager_account_access "
            "WHERE manager_id = $1 AND customer_id = '609'",
            destino,
        )
        assert antes["revoked_reason"] == manager_account_access.LEFT_MCC_REASON

        # admin copia o acesso (vivo) de outro gestor pro destino.
        await manager_account_access.grant(conn, manager_id=origem, customer_id="610")
        n = await manager_account_access.copy_access(
            conn, from_manager_id=origem, to_manager_id=destino, granted_by=origem
        )
        assert n == 1

        # a trilha left_mcc de 609 sobrevive à cópia — não foi apagada.
        depois = await conn.fetchrow(
            "SELECT revoked_reason FROM manager_account_access "
            "WHERE manager_id = $1 AND customer_id = '609'",
            destino,
        )
        assert depois is not None, "DELETE apagou a trilha left_mcc do destino"
        assert depois["revoked_reason"] == manager_account_access.LEFT_MCC_REASON

        # a cópia funcionou: destino recebeu 610 (vivo, copiado de origem).
        assert await manager_account_access.can_manager_access(conn, destino, "610") is True

        # 609 volta ao MCC — restore_for_account tem que devolver o destino.
        await conn.execute(
            "UPDATE google_ads_accounts SET is_active = true WHERE customer_id = '609'"
        )
        restaurados = await manager_account_access.restore_for_account(conn, customer_id="609")
        assert str(destino) in restaurados
        assert await manager_account_access.can_manager_access(conn, destino, "609") is True


@pytest.mark.integration
async def test_copy_access_recusa_origem_igual_ao_destino(db) -> None:
    """Item 4 da revisão final (mesmo achado T5e do gêmeo Meta,
    test_meta_copy_access_recusa_origem_igual_ao_destino): sem o guard,
    copiar pra si mesmo aniquila o próprio gestor — o UPDATE de limpeza
    revoga (soft) tudo que ele tem de vivo, e o SELECT seguinte, filtrando
    `manager_id = origem AND revoked_at IS NULL`, já não acha nada pra
    reconceder (a origem É o destino, que acabou de ficar todo revogado). A
    rota (`routes.py:1367`) já recusa antes de chamar `copy_access`, mas a
    defesa não pode viver só lá — quem chamar o repositório de outro lugar
    não herda a checagem da rota.
    """
    async with db.acquire() as conn:
        mid = await _make_manager(conn, "self-copy@v4company.com")
        await google_ads_accounts.upsert_many(
            conn, [{"customer_id": "611", "mcc_id": "1", "descriptive_name": "Self"}]
        )
        await manager_account_access.grant_all_active(conn, manager_id=mid)

        with pytest.raises(ValueError):
            await manager_account_access.copy_access(
                conn, from_manager_id=mid, to_manager_id=mid, granted_by=mid
            )

        assert await manager_account_access.can_manager_access(conn, mid, "611") is True


# ---------- meta_resync.reconcile_meta (Task 5) ----------


@pytest.mark.integration
async def test_meta_reconcile_grava_meta_access_cleanup_no_audit(db) -> None:
    """Espelha o teste de Google: revogação automática de acesso Meta grava
    trilha com a operation CORRETA (`meta_access_cleanup`, não `google_access_cleanup`).

    Este teste vai direto na função `record_access_revocation` com `platform="meta"`,
    pois o fluxo completo de `reconcile_meta()` exige mocking complexo de network
    (partnership, adaccounts). O que importa é que a string da operation seja fixada.
    Sabotagem 1: hardcodar `operation="google_access_cleanup"` no helper ficaria vermelha.
    """
    async with db.acquire() as conn:
        mid = await _make_manager(conn, "trilha-meta@v4company.com")
        await meta_ad_accounts.upsert_many(
            conn,
            [
                {
                    "ad_account_id": "act_meta_revoke",
                    "business_id": "bm_test",
                    "account_name": "Test Meta",
                }
            ],
        )
        await manager_meta_account_access.grant(
            conn, manager_id=mid, ad_account_id="act_meta_revoke"
        )

        # Chama record_access_revocation diretamente como faria meta_resync
        # após revogar grants.
        from src.jobs._audit import record_access_revocation

        await record_access_revocation(
            conn,
            platform="meta",
            ad_account_id="act_meta_revoke",
            reason=manager_meta_account_access.PARTNERSHIP_ENDED_REASON,
            manager_ids=[str(mid)],
        )

        # Verifica que a operation gravada é `meta_access_cleanup` (não `google_access_cleanup`).
        row = await conn.fetchrow(
            """SELECT operation, platform, action_type, status, customer_id, params_summary
                 FROM audit_log WHERE operation = 'meta_access_cleanup'
                ORDER BY occurred_at DESC LIMIT 1"""
        )
        assert row is not None, "revogacao meta sem NENHUMA trilha no audit_log"
        assert row["platform"] == "meta"
        assert row["action_type"] == "mutate"
        assert row["status"] == "success"
        assert row["customer_id"] == "act_meta_revoke"
        params = json.loads(row["params_summary"])
        assert params["reason"] == manager_meta_account_access.PARTNERSHIP_ENDED_REASON
        assert params["managers"] == [str(mid)]


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
