"""F85: resposta vazia da API do Google nao pode desativar o MCC inteiro.

`fetch_account_details` pode devolver `[]` SEM levantar excecao — search com 0
linhas, mudanca de semantica do `customer_client`, hiccup de permissao. O
`keep_ids` sai vazio e `mark_inactive_except` caia num branch deliberado que
marcava TODO o inventario como inativo: as 25 contas do MCC sumiam do painel, de
`list_my_accounts` e de `grant_all_active` ate o resync seguinte, 24h depois.

O lado Meta escolheu o oposto e documentou (F65): payload vazio nao desativa
nada. A assimetria fail-deactivate vs fail-safe nao parecia intencional — e o
lado que falha inseguro era justamente o do inventario que os gestores usam.

Contrato coberto aqui:
- keep-list vazia NAO desativa nada por default (fail-safe);
- desativacao em massa continua possivel, mas so por opt-in EXPLICITO;
- o job trata inventario vazio como anomalia: pula a desativacao e audita
  `status="error"` (espelha o que a F93 fez pro lado Meta).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.db.repositories import google_ads_accounts


def _conn(update_result: str = "UPDATE 25") -> MagicMock:
    conn = MagicMock()
    conn.execute = AsyncMock(return_value=update_result)
    return conn


@pytest.mark.asyncio
async def test_keep_list_vazia_nao_desativa_nada_por_default() -> None:
    """F85: o caso perigoso vira no-op — nenhum UPDATE chega ao banco."""
    conn = _conn()

    n = await google_ads_accounts.mark_inactive_except(
        conn, mcc_id="6436352492", keep_customer_ids=[]
    )

    assert n == 0
    (
        conn.execute.assert_not_awaited(),
        ("keep-list vazia quase sempre significa falha de leitura, nao 'o MCC ficou vazio'"),
    )


@pytest.mark.asyncio
async def test_desativacao_em_massa_segue_possivel_com_opt_in_explicito() -> None:
    """F85: a capacidade nao foi removida, so deixou de ser o default silencioso."""
    conn = _conn("UPDATE 25")

    n = await google_ads_accounts.mark_inactive_except(
        conn,
        mcc_id="6436352492",
        keep_customer_ids=[],
        allow_full_deactivation=True,
    )

    assert n == 25
    conn.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_keep_list_normal_segue_desativando_o_que_sumiu() -> None:
    """Regressao: o caminho feliz (deletion detection real) nao pode mudar."""
    conn = _conn("UPDATE 2")

    n = await google_ads_accounts.mark_inactive_except(
        conn, mcc_id="6436352492", keep_customer_ids=["1111111111", "2222222222"]
    )

    assert n == 2
    conn.execute.assert_awaited_once()
    args = conn.execute.await_args.args
    assert args[1] == "6436352492"
    assert args[2] == ["1111111111", "2222222222"]


@pytest.mark.asyncio
async def test_job_com_inventario_vazio_pula_desativacao_e_audita_erro() -> None:
    """F85 no job: `[]` é anomalia, não 'o MCC esvaziou'."""
    from types import SimpleNamespace

    from src.jobs import account_resync
    from tests.unit.test_account_resync import _base_patches, _fake_pool

    pool = _fake_pool(MagicMock())
    oc = SimpleNamespace(refresh_token_enc=b"enc")
    mocks = _base_patches(pool=pool, oc=oc, accounts=[], upsert_return=0)

    with (
        mocks["init_pool"],
        mocks["close_pool"],
        mocks["get_pool"],
        mocks["pick"],
        mocks["derive"],
        mocks["decrypt"],
        mocks["build_client"],
        mocks["list_customers"],
        mocks["fetch"],
        mocks["upsert"],
        mocks["mark_inactive"] as mark_inactive,
        mocks["record"] as record,
        mocks["purge"],
        patch("src.jobs.meta_resync.resync_meta", AsyncMock(return_value=0)),
    ):
        await account_resync.run()

    mark_inactive.assert_not_awaited(), "inventario vazio nao pode alimentar deletion detection"
    resync_call = next(
        c for c in record.await_args_list if c.kwargs.get("operation") == "account_resync"
    )
    assert resync_call.kwargs["status"] == "error"
    assert resync_call.kwargs["error_message"]
