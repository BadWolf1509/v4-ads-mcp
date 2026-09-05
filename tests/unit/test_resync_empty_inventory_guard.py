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
- o job trata inventario vazio como anomalia e audita `status="error"` (espelha
  o que a F93 fez pro lado Meta).

Task 5 (2026-09-05): o job PAROU de chamar `mark_inactive_except` — a decisao
de quem desativar passou pra `build_plan()` (`src/google_ads/reconcile.py`),
aplicada via `reconcile_google` (`src/jobs/account_resync.py`). A propriedade
"inventario vazio -> zero desativacao E zero revogacao, mesmo com a trava
ligada" tem cobertura NOVA contra banco real em
`test_inventario_vazio_nao_desativa_nem_revoga_mesmo_com_trava_ligada`
(tests/integration/test_repositories.py) — os 3 testes de
`mark_inactive_except` abaixo continuam valendo (a funcao nao foi apagada, e
caminho de emergencia via `allow_full_deactivation`), mas so provam a funcao
em si; o teste de job mais abaixo (`test_job_com_inventario_vazio_...`) foi
reescrito pra provar so a FIACAO (accounts=[] -> complete=False chega em
`reconcile_google`) — mocka-la por inteiro e continuar afirmando que
`mark_inactive_except` nao roda seria um guard vacuo: ela nunca mais roda,
pra NENHUMA entrada, entao a asercao passaria sempre e nao provaria nada.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.db.repositories import google_ads_accounts
from src.meta_ads.reconcile import Plan


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
    """F85 no job: `[]` é anomalia, não 'o MCC esvaziou'.

    Task 5: a decisão em si (zero desativação, zero revogação com inventário
    vazio, mesmo com a trava ligada) migrou pra dentro de `reconcile_google` —
    coberta contra banco real em
    `test_inventario_vazio_nao_desativa_nem_revoga_mesmo_com_trava_ligada`
    (tests/integration/test_repositories.py). Este teste, mockado, prova só a
    FIAÇÃO que alimenta aquela decisão: `run()` tem que passar `complete=False`
    quando `fetch_account_details` devolve `[]`, e o audit tem que sair
    `status=error`. Antes ele mockava `mark_inactive_except` e afirmava que a
    função não era chamada — depois que o job parou de chamar essa função pra
    QUALQUER entrada, aquela asserção passaria sempre, sozinha, sem provar mais
    nada (o guard vácuo que a revisão apontou).
    """
    from types import SimpleNamespace

    from src.jobs import account_resync
    from tests.unit.test_account_resync import _base_patches, _fake_pool, _reconcile_result

    pool = _fake_pool(MagicMock())
    oc = SimpleNamespace(refresh_token_enc=b"enc")
    # O que `reconcile_google` de fato devolve pra complete=False (build_plan
    # recusa to_remove e preenche blocked_reason) — não é um valor arbitrário.
    resumo_bloqueado = _reconcile_result(
        upserted=0, complete=False, blocked_reason="leitura incompleta"
    )
    mocks = _base_patches(pool=pool, oc=oc, accounts=[], reconcile_result=resumo_bloqueado)

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
        mocks["reconcile_google"] as reconcile_google,
        mocks["avisar_sem_grant"],
        mocks["record"] as record,
        mocks["purge"],
        patch("src.jobs.meta_resync.reconcile_meta", AsyncMock(return_value=Plan())),
    ):
        await account_resync.run()

    assert reconcile_google.call_args.kwargs["complete"] is False, (
        "inventario vazio tem que chegar em reconcile_google como complete=False "
        "— e esse valor que faz build_plan recusar to_remove"
    )
    resync_call = next(
        c for c in record.await_args_list if c.kwargs.get("operation") == "google_reconcile"
    )
    assert resync_call.kwargs["status"] == "error"
    assert resync_call.kwargs["error_message"]
