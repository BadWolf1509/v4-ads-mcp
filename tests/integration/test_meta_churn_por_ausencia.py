"""F128 contra banco real: o contador de ausencias precisa do SQL, nao do mock.

O unit prova que as escritas certas sao EMITIDAS; aqui prova-se o EFEITO — que
e o que importava no F85, onde o mock passava e o banco desativava o inventario
inteiro. Cobre o ciclo completo do cenario que motivou o finding: conta de BM
que sumiu por inteiro (parceria encerrada) atravessa o limiar e cai; cliente que
volta zera o contador e reativa.
"""

import pytest

from src.db.repositories import meta_ad_accounts

_CONTA_VIVA = {
    "ad_account_id": "act_viva",
    "business_id": "bm_ativo",
    "business_name": "BM que segue visivel",
    "account_name": "Cliente Ativo",
    "currency": "BRL",
    "timezone_name": "America/Sao_Paulo",
    "account_status": 1,
}
_CONTA_ORFA = {
    "ad_account_id": "act_orfa",
    "business_id": "bm_que_sumiu",
    "business_name": "Mestre da Obra Petrolina",
    "account_name": "Cliente que saiu da parceria",
    "currency": "BRL",
    "timezone_name": "America/Bahia",
    "account_status": 1,
}


@pytest.mark.integration
async def test_bm_que_some_inteiro_cai_no_limiar(db) -> None:
    """O caso que o `mark_inactive_except` nao ve: BM ausente do payload."""
    async with db.acquire() as conn:
        await meta_ad_accounts.upsert_many(conn, [_CONTA_VIVA, _CONTA_ORFA])

        # A deteccao escopada por BM nao alcanca: o BM da orfa nao veio no
        # payload, entao nao ha keep-list pra ele. Isto e o bug do F128.
        deactivated = await meta_ad_accounts.mark_inactive_except(
            conn, business_id="bm_ativo", keep_ad_account_ids=["act_viva"]
        )
        assert deactivated == 0
        assert (await meta_ad_accounts.get_by_id(conn, "act_orfa")).is_active is True

        # Contador: duas ausencias marcam sem desativar...
        for esperado in (1, 2):
            marcadas, saiu = await meta_ad_accounts.bump_missing(
                conn, seen_ad_account_ids=["act_viva"], threshold=3
            )
            assert (marcadas, saiu) == (1, 0)
            orfa = await meta_ad_accounts.get_by_id(conn, "act_orfa")
            assert (orfa.missed_syncs, orfa.is_active) == (esperado, True)

        # ...e a terceira cruza o limiar.
        marcadas, saiu = await meta_ad_accounts.bump_missing(
            conn, seen_ad_account_ids=["act_viva"], threshold=3
        )
        assert (marcadas, saiu) == (1, 1)
        assert (await meta_ad_accounts.get_by_id(conn, "act_orfa")).is_active is False

        # A conta que apareceu em toda execucao nao foi tocada.
        viva = await meta_ad_accounts.get_by_id(conn, "act_viva")
        assert (viva.is_active, viva.missed_syncs) == (True, 0)

        # Conta ja desativada nao segue contando: o WHERE exige is_active.
        marcadas, _ = await meta_ad_accounts.bump_missing(
            conn, seen_ad_account_ids=["act_viva"], threshold=3
        )
        assert marcadas == 0


@pytest.mark.integration
async def test_cliente_que_volta_zera_o_contador(db) -> None:
    """Reaparecer precisa reativar E limpar a serie — senao cai de novo amanha."""
    async with db.acquire() as conn:
        await meta_ad_accounts.upsert_many(conn, [_CONTA_VIVA, _CONTA_ORFA])
        for _ in range(3):
            await meta_ad_accounts.bump_missing(conn, seen_ad_account_ids=["act_viva"], threshold=3)
        assert (await meta_ad_accounts.get_by_id(conn, "act_orfa")).is_active is False

        await meta_ad_accounts.upsert_many(conn, [_CONTA_VIVA, _CONTA_ORFA])

        voltou = await meta_ad_accounts.get_by_id(conn, "act_orfa")
        assert (voltou.is_active, voltou.missed_syncs) == (True, 0)


@pytest.mark.integration
async def test_inventario_vazio_nao_derruba_nada(db) -> None:
    """F85 no lado Meta, provado no banco: o no-op nao chega a emitir UPDATE."""
    async with db.acquire() as conn:
        await meta_ad_accounts.upsert_many(conn, [_CONTA_VIVA, _CONTA_ORFA])

        marcadas, saiu = await meta_ad_accounts.bump_missing(
            conn, seen_ad_account_ids=[], threshold=3
        )

        assert (marcadas, saiu) == (0, 0)
        assert len(await meta_ad_accounts.list_all(conn)) == 2


@pytest.mark.integration
async def test_list_out_of_reach_mostra_as_duas_rotas_de_churn(db) -> None:
    """O painel precisa ver tanto a desativada quanto a que esta a caminho."""
    async with db.acquire() as conn:
        await meta_ad_accounts.upsert_many(conn, [_CONTA_VIVA, _CONTA_ORFA])
        # rota 1: desativada pelo caminho escopado por BM (sem contador)
        await meta_ad_accounts.mark_inactive_except(
            conn, business_id="bm_ativo", keep_ad_account_ids=[]
        )
        # rota 2: ainda ativa, mas ja acumulando ausencia
        await meta_ad_accounts.bump_missing(conn, seen_ad_account_ids=["act_viva"], threshold=3)

        fora = {a.ad_account_id: a for a in await meta_ad_accounts.list_out_of_reach(conn)}

        assert set(fora) == {"act_viva", "act_orfa"}
        assert fora["act_viva"].is_active is False  # caiu por BM, contador zerado
        assert fora["act_orfa"].missed_syncs == 1  # a caminho, ainda ativa
