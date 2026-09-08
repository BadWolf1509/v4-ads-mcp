"""Um teste de rejeicao por sitio, para os doze da rodada de correcao 1.

Parametrizado por FAMILIA, nao doze arquivos — o que varia entre os sitios e o
alvo e o payload, nao a invariante. A invariante e a mesma nos doze: **id que
nao e id nao entra na query**, e a recusa acontece ANTES de qualquer chamada ao
Google.

Duas familias, e a diferenca entre elas e o que se pode observar:

- **builders puros** (`queries/`) devolvem string, entao a assercao e
  `pytest.raises(ValueError)` direto;
- **helpers e tools async** montam a query e chamam `run_report`, entao alem do
  `ValueError` o teste prende o mais importante: `run_report` NAO pode ter sido
  chamado. Sem essa metade, uma implementacao que so validasse DEPOIS de
  montar a clausula (ou que logasse a query crua) passaria verde.

Sobre o payload `"1) OR 1=1 --"`: ele ilustra a quebra da clausula `IN (...)`,
mas a defesa real e "nao parseia como int", nao "escapa este padrao". Qualquer
string nao-numerica (`"abc"`) provaria o mesmo — o payload so torna visivel o
que esta em jogo quando se le a falha.

O `pattern` do schema a montante nao substitui nada disto (F87): metade destes
alvos sao builders publicos de `queries/`, que qualquer tool ou teste futuro
pode chamar direto, sem schema nenhum no caminho. Tres deles tinham, ate esta
rodada, um comentario dizendo "ids validados `^[0-9]+$` no schema" logo acima
da interpolacao crua.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

_ID_RUIM = "1) OR 1=1 --"


@pytest.fixture(autouse=True)
def _ctx():
    from src.mcp.context import McpRequestContext, clear_current, set_current

    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    yield
    clear_current()


# --------------------------------------------------------------------------
# Familia 1: builders puros de `src/google_ads/queries/` — 6 sitios.
# --------------------------------------------------------------------------


def _keyword_lookup_ad_group() -> str:
    from src.google_ads.queries.keyword_lookup import build_keyword_text_lookup_query

    return build_keyword_text_lookup_query([(_ID_RUIM, "222")])


def _keyword_lookup_criterion() -> str:
    from src.google_ads.queries.keyword_lookup import build_keyword_text_lookup_query

    return build_keyword_text_lookup_query([("111", _ID_RUIM)])


def _ad_schedule_query() -> str:
    from src.google_ads.queries.ad_schedule import ad_schedule_query

    return ad_schedule_query(campaign_ids=[_ID_RUIM], status="enabled", limit=10)


def _campaign_budget_query() -> str:
    from src.google_ads.queries.ad_schedule import campaign_budget_query

    return campaign_budget_query(campaign_ids=[_ID_RUIM])


def _day_hour_metrics_query() -> str:
    from datetime import date

    from src.google_ads.queries.ad_schedule import day_hour_metrics_query

    return day_hour_metrics_query(
        campaign_ids=[_ID_RUIM], start=date(2026, 8, 1), end=date(2026, 8, 31)
    )


def _campaign_asset_query() -> str:
    from src.google_ads.queries.assets import build_campaign_asset_query

    return build_campaign_asset_query(field_type=None, campaign_ids=[_ID_RUIM])


@pytest.mark.parametrize(
    ("sitio", "constroi"),
    [
        (
            "keyword_lookup.py::build_keyword_text_lookup_query (ad_group_ids)",
            _keyword_lookup_ad_group,
        ),
        (
            "keyword_lookup.py::build_keyword_text_lookup_query (criterion_ids)",
            _keyword_lookup_criterion,
        ),
        ("queries/ad_schedule.py::ad_schedule_query", _ad_schedule_query),
        ("queries/ad_schedule.py::campaign_budget_query", _campaign_budget_query),
        ("queries/ad_schedule.py::day_hour_metrics_query", _day_hour_metrics_query),
        ("queries/assets.py::build_campaign_asset_query", _campaign_asset_query),
    ],
)
def test_builder_puro_recusa_id_nao_numerico(sitio: str, constroi: Any) -> None:
    """Pre-fix, cada um destes devolvia uma string com o texto do gestor dentro
    da clausula `IN (...)`. Agora recusa.

    A assercao e "nao ACEITA o que nao e id", nao "escapou o texto": os dois
    de `ad_schedule.py`/`assets.py` interpolavam o `join` INLINE, e um teste
    que procurasse o texto escapado na saida nao distinguiria as duas formas.
    """
    with pytest.raises(ValueError):
        constroi()


# --------------------------------------------------------------------------
# Familia 2: caminhos async — a recusa tem que preceder o `run_report`. 6 sitios.
# --------------------------------------------------------------------------


async def _lookup_country_names() -> Any:
    from src.google_ads.reports import lookup_country_names

    return await lookup_country_names(
        manager_id=uuid4(), session_id=uuid4(), customer_id="1234567890", country_ids={_ID_RUIM}
    )


async def _validate_user_interest() -> Any:
    from src.mcp.context import get_current
    from src.mcp.tools.apply_audience import _validate_user_interest_taxonomies

    return await _validate_user_interest_taxonomies(
        get_current(),
        "1234567890",
        [
            {
                "audience_type": "user_interest",
                "audience_resource_name": f"customers/1234567890/userInterests/{_ID_RUIM}",
            }
        ],
    )


async def _resolve_names_campaign() -> Any:
    from src.mcp.tools.get_change_history import _resolve_names

    return await _resolve_names(
        manager_id=uuid4(),
        session_id=uuid4(),
        customer_id="1234567890",
        rows=[{"campaign_id": _ID_RUIM, "ad_group_id": None}],
    )


async def _update_ad_group_bid() -> Any:
    from src.mcp.tools.update_ad_group_bid import update_ad_group_bid

    # A pre-flight de estrategia roda ANTES e ja valida os MESMOS ids desde
    # `4980eda`, entao ela e neutralizada aqui de proposito: sem isso o teste
    # ficaria verde por causa da defesa do VIZINHO, e o sitio desta linha
    # nunca seria exercitado. Defesa em profundidade so e defesa se cada
    # camada for provada sozinha — a ordem das duas chamadas pode mudar
    # amanha, e o `ag_ids` continuaria indo cru para o GAQL.
    with patch(
        "src.mcp.tools.update_ad_group_bid.validate_manual_cpc_strategy",
        AsyncMock(return_value=None),
    ):
        return await update_ad_group_bid(
            {
                "customer_id": "1234567890",
                "bids": [{"ad_group_id": _ID_RUIM, "new_cpc_bid_brl": 1.05}],
            }
        )


async def _update_keyword_bid() -> Any:
    from src.mcp.tools.update_keyword_bid import update_keyword_bid

    # Aqui o vizinho NAO cobre: a pre-flight valida `ad_group_id`, e o sitio
    # desta rodada interpola `criterion_id`. O id do grupo vai valido de
    # proposito, para o `ValueError` so poder ter vindo do criterion.
    with patch(
        "src.mcp.tools.update_keyword_bid.validate_manual_cpc_strategy",
        AsyncMock(return_value=None),
    ):
        return await update_keyword_bid(
            {
                "customer_id": "1234567890",
                "bids": [{"ad_group_id": "111", "criterion_id": _ID_RUIM, "new_cpc_bid_brl": 1.05}],
            }
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("sitio", "alvo_do_run_report", "chama"),
    [
        (
            "reports.py::lookup_country_names",
            "src.google_ads.reports.run_report",
            _lookup_country_names,
        ),
        (
            "apply_audience.py::_validate_user_interest_taxonomies",
            "src.mcp.tools.apply_audience.run_report",
            _validate_user_interest,
        ),
        (
            "get_change_history.py::_resolve_names (campaign_ids)",
            "src.mcp.tools.get_change_history.run_report",
            _resolve_names_campaign,
        ),
        (
            "update_ad_group_bid.py::update_ad_group_bid",
            "src.mcp.tools.update_ad_group_bid.run_report",
            _update_ad_group_bid,
        ),
        (
            "update_keyword_bid.py::update_keyword_bid",
            "src.mcp.tools.update_keyword_bid.run_report",
            _update_keyword_bid,
        ),
    ],
)
async def test_caminho_async_recusa_antes_de_falar_com_o_google(
    sitio: str, alvo_do_run_report: str, chama: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`ValueError` E `run_report` intocado.

    A segunda metade e a que importa: o mock nao devolve dado, ele FALHA o
    teste se for chamado. Contra o codigo pre-fix a falha e essa — a query com
    o payload cru visivel na mensagem — e nao o `DID NOT RAISE`.
    """

    async def run_report_proibido(**kwargs: Any) -> list[dict[str, Any]]:
        raise AssertionError(f"{sitio}: run_report chamado com query {kwargs.get('query')!r}")

    monkeypatch.setattr(alvo_do_run_report, run_report_proibido)
    with pytest.raises(ValueError):
        await chama()


@pytest.mark.asyncio
async def test_resolve_names_recusa_ad_group_id_depois_de_resolver_campanha(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """O 12o sitio, que so e alcancavel com a PRIMEIRA consulta bem-sucedida.

    `_resolve_names` monta duas clausulas `IN (...)` na mesma funcao, reusando
    o nome `ids_clause`. Para exercitar a segunda, a primeira tem que passar —
    por isso este caso nao cabe na parametrizacao acima, onde `run_report` e
    proibido de ser chamado.

    A excecao e capturada a mao, e nao com `pytest.raises`, porque a ORDEM das
    assercoes e o que decide a mensagem do vermelho. Com `pytest.raises` por
    fora, o pre-fix falha com um `DID NOT RAISE` mudo e as queries emitidas
    nunca sao olhadas; capturando primeiro, a falha mostra a segunda query com
    o payload cru dentro do `IN (...)` — que e o defeito, nao a ausencia de
    excecao. Verificado rodando contra o pre-fix, nao presumido.

    A assercao que prende o sitio e a das queries: exatamente UMA foi emitida
    (a de campanha, com o id valido), e o `ad_group_id` invalido nunca chegou a
    virar texto de query. So o `ValueError` nao diria de qual das duas
    clausulas ele veio.
    """
    from src.mcp.tools.get_change_history import _resolve_names

    emitidas: list[str] = []

    async def fake_run_report(**kwargs: Any) -> list[dict[str, Any]]:
        emitidas.append(str(kwargs.get("query")))
        return []

    monkeypatch.setattr("src.mcp.tools.get_change_history.run_report", fake_run_report)
    recusou = False
    try:
        await _resolve_names(
            manager_id=uuid4(),
            session_id=uuid4(),
            customer_id="1234567890",
            rows=[{"campaign_id": "100", "ad_group_id": _ID_RUIM}],
        )
    except ValueError:
        recusou = True

    assert _ID_RUIM not in " ".join(emitidas), (
        f"o ad_group_id invalido virou texto de query: {emitidas}"
    )
    assert len(emitidas) == 1, f"so a consulta de campanha podia ter saido: {emitidas}"
    assert "campaign.id IN (100)" in emitidas[0], emitidas[0]
    assert recusou, "a segunda clausula tinha que ter recusado o id com ValueError"
