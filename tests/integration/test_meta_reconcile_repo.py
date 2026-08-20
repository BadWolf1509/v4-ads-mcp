# tests/integration/test_meta_reconcile_repo.py
"""O repositorio APLICA o plano; nao decide nada. Contra banco real porque o
que importa aqui e o efeito do SQL, nao a chamada (licao do F85)."""

from uuid import uuid4

import pytest

from src.db.repositories import manager_meta_account_access, managers, meta_ad_accounts
from src.db.repositories.manager_meta_account_access import PARTNERSHIP_ENDED_REASON

CONTA = {
    "ad_account_id": "act_1",
    "business_id": "bm",
    "business_name": "BM",
    "account_name": "Conta 1",
    "currency": "BRL",
    "timezone_name": "America/Sao_Paulo",
    "account_status": 1,
}
OUTRA = {**CONTA, "ad_account_id": "act_2", "account_name": "Conta 2"}


@pytest.mark.integration
async def test_apply_absences_incrementa_e_zera(db) -> None:
    async with db.acquire() as conn:
        await meta_ad_accounts.upsert_many(conn, [CONTA, OUTRA])

        await meta_ad_accounts.apply_absences(conn, bump=["act_2"], reset=[])
        await meta_ad_accounts.apply_absences(conn, bump=["act_2"], reset=[])
        assert (await meta_ad_accounts.get_by_id(conn, "act_2")).missed_syncs == 2

        await meta_ad_accounts.apply_absences(conn, bump=[], reset=["act_2"])
        assert (await meta_ad_accounts.get_by_id(conn, "act_2")).missed_syncs == 0


@pytest.mark.integration
async def test_deactivate_so_mexe_no_que_foi_pedido(db) -> None:
    async with db.acquire() as conn:
        await meta_ad_accounts.upsert_many(conn, [CONTA, OUTRA])

        n = await meta_ad_accounts.deactivate(conn, ad_account_ids=["act_2"])

        assert n == 1
        assert (await meta_ad_accounts.get_by_id(conn, "act_1")).is_active is True
        assert (await meta_ad_accounts.get_by_id(conn, "act_2")).is_active is False


@pytest.mark.integration
async def test_lista_vazia_e_noop_em_todas_as_operacoes(db) -> None:
    """F85: lista vazia quase sempre e falha de leitura, nao 'todas sumiram'."""
    async with db.acquire() as conn:
        await meta_ad_accounts.upsert_many(conn, [CONTA, OUTRA])

        assert await meta_ad_accounts.deactivate(conn, ad_account_ids=[]) == 0
        await meta_ad_accounts.apply_absences(conn, bump=[], reset=[])
        await meta_ad_accounts.set_reachable(conn, reachable_ids=[], scope_ids=["act_1"])

        assert len(await meta_ad_accounts.list_all(conn)) == 2
        assert (await meta_ad_accounts.get_by_id(conn, "act_1")).su_reachable is True


@pytest.mark.integration
async def test_set_reachable_marca_quem_esta_fora_do_alcance(db) -> None:
    async with db.acquire() as conn:
        await meta_ad_accounts.upsert_many(conn, [CONTA, OUTRA])

        await meta_ad_accounts.set_reachable(
            conn, reachable_ids=["act_1"], scope_ids=["act_1", "act_2"]
        )

        assert (await meta_ad_accounts.get_by_id(conn, "act_1")).su_reachable is True
        assert (await meta_ad_accounts.get_by_id(conn, "act_2")).su_reachable is False


@pytest.mark.integration
async def test_set_reachable_nao_toca_em_conta_fora_do_escopo(db) -> None:
    """M4: o UPDATE e escopado a parceria.

    Sem o WHERE, marcar alcance sobre a parceria carimbava su_reachable=false
    em TODA conta que nao viesse em /me/adaccounts — inclusive conta ja
    desativada ou em carencia, pra quem "o SU nao alcanca" nao e sinal
    acionavel nenhum (spec §3: o alerta e pra conta que ESTA na parceria).
    """
    async with db.acquire() as conn:
        await meta_ad_accounts.upsert_many(conn, [CONTA, OUTRA])
        # act_2 sai da parceria: fora do escopo do proximo set_reachable.
        await meta_ad_accounts.deactivate(conn, ad_account_ids=["act_2"])

        await meta_ad_accounts.set_reachable(conn, reachable_ids=["act_1"], scope_ids=["act_1"])

        assert (await meta_ad_accounts.get_by_id(conn, "act_1")).su_reachable is True
        assert (await meta_ad_accounts.get_by_id(conn, "act_2")).su_reachable is True, (
            "conta fora do escopo nao pode ser marcada como 'sem SU' — ela nem "
            "esta mais na parceria, entao o sinal nao tem acao associada"
        )


@pytest.mark.integration
async def test_list_inventory_rows_devolve_o_que_o_plano_consome(db) -> None:
    async with db.acquire() as conn:
        await meta_ad_accounts.upsert_many(conn, [CONTA, OUTRA])
        await meta_ad_accounts.deactivate(conn, ad_account_ids=["act_2"])

        linhas = {r.ad_account_id: r for r in await meta_ad_accounts.list_inventory_rows(conn)}

        assert linhas["act_1"].is_active is True
        assert linhas["act_2"].is_active is False
        assert linhas["act_1"].missed_syncs == 0


@pytest.mark.integration
async def test_list_queues_sem_su_tem_precedencia_sobre_sem_delegacao(db) -> None:
    """Fix round 1 (review): conta sem gestor E sem SU caia nas DUAS filas
    antes deste fix — caso real em producao (CA - V4 Lima Soares, CHUTE 07).
    sem_su ganha: delegar um gestor numa conta que o SU nao alcanca so produz
    #200 quando ele tenta usar; a ordem certa do admin e SU primeiro,
    delegacao depois — por isso as filas tem que ser exclusivas."""
    async with db.acquire() as conn:
        await meta_ad_accounts.upsert_many(conn, [CONTA, OUTRA])
        # act_1 fica alcancavel (cai em sem_delegacao, o caso normal); act_2
        # fica de fora (sem SU E sem gestor — o caso que se sobrepunha).
        await meta_ad_accounts.set_reachable(
            conn, reachable_ids=["act_1"], scope_ids=["act_1", "act_2"]
        )

        queues = await meta_ad_accounts.list_queues(conn)

        sem_delegacao_ids = {a.ad_account_id for a in queues.sem_delegacao}
        sem_su_ids = {a.ad_account_id for a in queues.sem_su}

        assert sem_delegacao_ids == {"act_1"}
        assert sem_su_ids == {"act_2"}
        assert not (sem_delegacao_ids & sem_su_ids), "as filas nao podem se sobrepor"


async def _gestor_com_grant(conn, ad_account_id: str, email: str):
    mid = uuid4()
    await managers.create(conn, manager_id=mid, email=email, full_name=None)
    await manager_meta_account_access.bulk_grant(
        conn, manager_id=mid, ad_account_ids=[ad_account_id], granted_by=mid
    )
    return mid


@pytest.mark.integration
async def test_fila_saiu_segue_a_conta_depois_que_a_parceria_volta(db) -> None:
    """C1: a conta que VOLTOU tem de continuar na fila, com o botao alcancavel.

    Este e o cenario da §8 ("a parceria voltou") reproduzido pelo caminho que a
    PRODUCAO percorre — desativa, revoga por churn, e so entao reaparece na
    parceria (upsert_many reativa). Com a fila key-ada em `is_active = false`, a
    conta sumia exatamente aqui, junto com o unico chamador de
    `restore_for_account` no src/; e clicar ANTES nao adiantava, porque o gate
    nega enquanto a conta esta inativa.
    """
    async with db.acquire() as conn:
        await meta_ad_accounts.upsert_many(conn, [CONTA])
        mid = await _gestor_com_grant(conn, "act_1", "voltou@v4company.com")
        await meta_ad_accounts.deactivate(conn, ad_account_ids=["act_1"])
        await manager_meta_account_access.revoke_for_account(
            conn, ad_account_id="act_1", reason=PARTNERSHIP_ENDED_REASON
        )
        # A parceria volta: o job faz upsert_many, que reativa e zera a carencia.
        await meta_ad_accounts.upsert_many(conn, [CONTA])

        queues = await meta_ad_accounts.list_queues(conn)

        saiu = {c.ad_account_id: (c, n) for c, n in queues.saiu_da_parceria}
        assert "act_1" in saiu, "a conta sumiu da fila justamente ao virar restauravel"
        conta, revogados = saiu["act_1"]
        assert conta.is_active is True
        assert revogados == 1
        # Precedencia: quem tem grant restauravel nao aparece tambem na fila de
        # delegacao, senao o painel convida a refazer a mao o que o botao devolve.
        assert "act_1" not in {a.ad_account_id for a in queues.sem_delegacao}

        # E o botao funciona de verdade neste estado (era o outro lado do C1: o
        # restore rodava, o flash dizia "restaurado", e o gate seguia negando).
        assert (
            await manager_meta_account_access.restore_for_account(conn, ad_account_id="act_1") == 1
        )
        assert await manager_meta_account_access.can_manager_access(conn, mid, "act_1") is True
        depois = await meta_ad_accounts.list_queues(conn)
        assert "act_1" not in {c.ad_account_id for c, _ in depois.saiu_da_parceria}


@pytest.mark.integration
async def test_fila_saiu_poe_quem_voltou_antes_do_historico(db) -> None:
    """A conta acionavel nao pode afundar no meio de quem saiu e nao voltou."""
    async with db.acquire() as conn:
        # OUTRA ("Conta 2") ordena depois de CONTA ("Conta 1") por nome — se a
        # ordenacao fosse so por account_name, a que voltou viria em segundo.
        await meta_ad_accounts.upsert_many(conn, [CONTA, OUTRA])
        await _gestor_com_grant(conn, "act_1", "hist@v4company.com")
        await _gestor_com_grant(conn, "act_2", "volta@v4company.com")
        await meta_ad_accounts.deactivate(conn, ad_account_ids=["act_1", "act_2"])
        for aid in ("act_1", "act_2"):
            await manager_meta_account_access.revoke_for_account(
                conn, ad_account_id=aid, reason=PARTNERSHIP_ENDED_REASON
            )
        await meta_ad_accounts.upsert_many(conn, [OUTRA])  # so act_2 volta

        queues = await meta_ad_accounts.list_queues(conn)

        assert [c.ad_account_id for c, _ in queues.saiu_da_parceria] == ["act_2", "act_1"]


@pytest.mark.integration
async def test_fila_saiu_conta_so_o_que_o_restore_devolve(db) -> None:
    """I5: o numero exibido e o mesmo conjunto que o botao reconcede.

    Um gestor destogglado a mao (`manual`) numa conta que depois sai da parceria
    entrava na contagem: o painel mostrava 2, o Restaurar devolvia 1, e a
    contagem caia sem o admin entender por que.
    """
    async with db.acquire() as conn:
        await meta_ad_accounts.upsert_many(conn, [CONTA])
        mid_manual = await _gestor_com_grant(conn, "act_1", "manual@v4company.com")
        await _gestor_com_grant(conn, "act_1", "churn@v4company.com")
        await manager_meta_account_access.revoke(
            conn, manager_id=mid_manual, ad_account_id="act_1", reason="manual"
        )
        await meta_ad_accounts.deactivate(conn, ad_account_ids=["act_1"])
        await manager_meta_account_access.revoke_for_account(
            conn, ad_account_id="act_1", reason=PARTNERSHIP_ENDED_REASON
        )

        queues = await meta_ad_accounts.list_queues(conn)

        (_conta, revogados) = next(
            (c, n) for c, n in queues.saiu_da_parceria if c.ad_account_id == "act_1"
        )
        restaurados = await manager_meta_account_access.restore_for_account(
            conn, ad_account_id="act_1"
        )
        assert revogados == restaurados == 1


@pytest.mark.integration
async def test_fila_saiu_ignora_conta_sem_revogacao_por_churn(db) -> None:
    """Revogacao manual sozinha nao poe a conta na fila de churn."""
    async with db.acquire() as conn:
        await meta_ad_accounts.upsert_many(conn, [CONTA])
        mid = await _gestor_com_grant(conn, "act_1", "so-manual@v4company.com")
        await manager_meta_account_access.revoke(
            conn, manager_id=mid, ad_account_id="act_1", reason="manual"
        )

        queues = await meta_ad_accounts.list_queues(conn)

        assert queues.saiu_da_parceria == []
        # Sem grant vivo e sem churn pendente, ela e caso de delegacao mesmo.
        assert "act_1" in {a.ad_account_id for a in queues.sem_delegacao}
