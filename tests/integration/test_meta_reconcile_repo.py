# tests/integration/test_meta_reconcile_repo.py
"""O repositorio APLICA o plano; nao decide nada. Contra banco real porque o
que importa aqui e o efeito do SQL, nao a chamada (licao do F85)."""

import pytest

from src.db.repositories import meta_ad_accounts

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
