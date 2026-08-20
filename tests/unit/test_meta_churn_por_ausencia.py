"""F128: conta que sai do alcance do system user precisa cair sozinha.

A deteccao de churn do Meta e escopada por `business_id` (F65): agrupa o que
veio em `/me/adaccounts` e, para cada BM visto, desativa o que faltou. Isso
cobre "conta removida de um BM ainda visivel" e NAO cobre o caso que mais
acontece na operacao — o cliente deixa de ser parceiro, o system user perde o
acesso e o BM INTEIRO some do payload. Sem BM no payload nao ha keep-list, e a
conta fica `is_active=true` pra sempre.

Verificado em producao em 2026-08-20 com `Mestre da Obra Petrolina`
(`act_468463369497370`, BM `1012131859922651`): o Graph respondeu
`(#200) Ad account owner has NOT grant ads_management or ads_read permission` e
a conta seguia ativa e concedida no MCP.

O contador de ausencias escopa por TEMPO em vez de por BM, entao independe de o
BM estar visivel. Contrato coberto aqui:

- so sync COMPLETO conta ausencia (F93 — sobre inventario truncado, "ausente"
  significa "pagina que nao veio");
- lista de vistas vazia e NO-OP, nunca "todo mundo sumiu" (F85 — foi assim que
  o lado Google desativou as 25 contas do MCC de uma vez);
- a desativacao so acontece ao cruzar o limiar, nao na primeira ausencia;
- ver a conta de novo zera o contador (cliente que volta nao fica marcado).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.db.repositories import meta_ad_accounts


def _conn(*resultados: str) -> MagicMock:
    conn = MagicMock()
    conn.execute = AsyncMock(side_effect=list(resultados) or ["UPDATE 0"])
    return conn


@pytest.mark.asyncio
async def test_lista_de_vistas_vazia_e_noop() -> None:
    """F85 no lado Meta: inventario vazio nao pode significar 'todas sumiram'."""
    conn = _conn()

    marcadas, desativadas = await meta_ad_accounts.bump_missing(conn, seen_ad_account_ids=[])

    assert (marcadas, desativadas) == (0, 0)
    conn.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_conta_ausente_e_marcada_e_desativada_no_limiar() -> None:
    """Duas escritas: incrementa quem faltou, desativa quem cruzou o limiar."""
    conn = _conn("UPDATE 2", "UPDATE 1")

    marcadas, desativadas = await meta_ad_accounts.bump_missing(
        conn, seen_ad_account_ids=["act_1", "act_2"], threshold=3
    )

    assert (marcadas, desativadas) == (2, 1)
    assert conn.execute.await_count == 2
    incremento = conn.execute.await_args_list[0].args[0]
    assert "missed_syncs = missed_syncs + 1" in incremento
    # so conta ATIVA entra na contagem: reprocessar nao afunda quem ja caiu
    assert "is_active = true" in incremento
    desativacao = conn.execute.await_args_list[1].args[0]
    assert "is_active = false" in desativacao
    assert conn.execute.await_args_list[1].args[1] == 3


@pytest.mark.asyncio
async def test_upsert_zera_o_contador_de_quem_reapareceu() -> None:
    """Cliente que volta nao pode carregar ausencia antiga rumo ao limiar."""
    conn = MagicMock()
    conn.executemany = AsyncMock()

    await meta_ad_accounts.upsert_many(
        conn, [{"ad_account_id": "act_1", "account_name": "Conta 1"}]
    )

    sql = conn.executemany.await_args.args[0]
    assert "missed_syncs = 0" in sql


@pytest.mark.asyncio
async def test_resync_nao_conta_ausencia_em_inventario_truncado() -> None:
    """F93: pagina que falhou nao e churn — a mesma regra do _deactivate_churned."""
    from src.auth.meta_oauth import AdAccountsFetch
    from src.jobs import meta_resync

    conn = MagicMock()
    with (
        patch.object(
            meta_resync,
            "_fetch_all_adaccounts",
            new=AsyncMock(
                return_value=AdAccountsFetch(
                    accounts=[{"id": "act_1", "name": "C1"}], complete=False
                )
            ),
        ),
        patch.object(meta_ad_accounts, "upsert_many", new=AsyncMock(return_value=1)),
        patch.object(meta_ad_accounts, "bump_missing", new=AsyncMock(return_value=(0, 0))) as bump,
        patch.object(meta_resync, "record_job_run", new=AsyncMock()),
        patch.object(
            meta_resync.connection, "get_pool", new=MagicMock(return_value=_pool_devolvendo(conn))
        ),
        patch.object(
            meta_resync,
            "get_settings",
            new=MagicMock(return_value=MagicMock(meta_system_user_token="tok")),
        ),
    ):
        await meta_resync.resync_meta()

    bump.assert_not_awaited()


@pytest.mark.asyncio
async def test_resync_conta_ausencia_em_inventario_completo() -> None:
    """O caminho que fecha o F128: inventario completo alimenta o contador."""
    from src.auth.meta_oauth import AdAccountsFetch
    from src.jobs import meta_resync

    conn = MagicMock()
    with (
        patch.object(
            meta_resync,
            "_fetch_all_adaccounts",
            new=AsyncMock(
                return_value=AdAccountsFetch(
                    accounts=[
                        {"id": "act_1", "name": "C1", "business": {"id": "b1", "name": "BM"}}
                    ],
                    complete=True,
                )
            ),
        ),
        patch.object(meta_ad_accounts, "upsert_many", new=AsyncMock(return_value=1)),
        patch.object(meta_ad_accounts, "mark_inactive_except", new=AsyncMock(return_value=0)),
        patch.object(meta_ad_accounts, "bump_missing", new=AsyncMock(return_value=(2, 1))) as bump,
        patch.object(meta_resync, "record_job_run", new=AsyncMock()) as audit,
        patch.object(
            meta_resync.connection, "get_pool", new=MagicMock(return_value=_pool_devolvendo(conn))
        ),
        patch.object(
            meta_resync,
            "get_settings",
            new=MagicMock(return_value=MagicMock(meta_system_user_token="tok")),
        ),
    ):
        await meta_resync.resync_meta()

    bump.assert_awaited_once()
    assert bump.await_args.kwargs["seen_ad_account_ids"] == ["act_1"]
    # o resultado precisa aparecer na trilha: churn silencioso foi o F93
    resumo = audit.await_args.kwargs["params_summary"]
    assert resumo["missing"] == 2
    assert resumo["aged_out"] == 1


def _pool_devolvendo(conn: MagicMock) -> MagicMock:
    """Pool cujo `async with pool.acquire()` entrega o conn dado."""
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=ctx)
    return pool
