"""update_campaign_budget (C1): o preview declara as campanhas irmas do portfolio.

O builder escreve no **recurso orcamento** (`src/google_ads/mutates/campaigns.py`,
update_mask `["amount_micros"]`), nao na campanha. Quando esse orcamento e do
portfolio (`campaign_budget.explicitly_shared: true`), mudar o valor atinge TODAS
as campanhas penduradas nele — e ate 2026-09-07 o preview nomeava uma so.

Medido na conta `7862230676` em 02-04/09: as duas campanhas nao-removidas dividem
o orcamento `15803241252`, `explicitly_shared: true`, R$ 310,00/dia.

**Por que os fakes daqui montam a row a partir do SELECT da propria GAQL:**
proto-plus nunca omite atributo — campo que a query NAO pediu chega com o
zero-value do proto, nao com erro (F145). Devolver dicts prontos do fake esconderia
exatamente isso: tirar `campaign_budget.explicitly_shared` da query passaria verde.
Por isso o fake aplica o `row_formatter` de verdade sobre uma row que so carrega o
que o SELECT pediu.
"""

from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

import pytest

from src.mcp.tools import update_campaign_budget as mod

_CUSTOMER = "7862230676"
_ALVO_ID = "21359547724"
_IRMA_ID = "22169885957"
_BUDGET_ID = "15803241252"
_BUDGET_RN = f"customers/{_CUSTOMER}/campaignBudgets/{_BUDGET_ID}"

# Zero-value do proto para o campo que a GAQL nao pediu. E a metade do fake que
# faz a sabotagem morder: sem `explicitly_shared` no SELECT, o valor lido e False.
_DEFAULTS: dict[str, Any] = {
    "campaign.id": 0,
    "campaign.name": "",
    "campaign.status": "UNSPECIFIED",
    "campaign.campaign_budget": "",
    "campaign_budget.id": 0,
    "campaign_budget.resource_name": "",
    "campaign_budget.amount_micros": 0,
    "campaign_budget.explicitly_shared": False,
}


class _No:
    """Nó de acesso por atributo (`row.campaign_budget.explicitly_shared`)."""

    def __init__(self, campos: dict[str, Any]) -> None:
        for k, v in campos.items():
            setattr(self, k, v)


def _campos_do_select(query: str) -> set[str]:
    m = re.search(r"\bSELECT\b(.+?)\bFROM\b", query, re.S | re.I)
    assert m is not None, f"GAQL sem SELECT..FROM: {query!r}"
    return {c.strip() for c in m.group(1).split(",") if c.strip()}


def _linha(query: str, valores: dict[str, Any]) -> Any:
    """Monta a row como o Google monta: o SELECT manda; o resto vem no default."""
    pedidos = _campos_do_select(query)
    aninhado: dict[str, dict[str, Any]] = {}
    for caminho, default in _DEFAULTS.items():
        raiz, campo = caminho.split(".", 1)
        aninhado.setdefault(raiz, {})[campo] = (
            valores.get(caminho, default) if caminho in pedidos else default
        )
    return _No({raiz: _No(campos) for raiz, campos in aninhado.items()})


def _valores_alvo(*, explicitly_shared: bool) -> dict[str, Any]:
    return {
        "campaign.id": int(_ALVO_ID),
        "campaign.name": "[GPC][JPA]",
        "campaign.status": "ENABLED",
        "campaign.campaign_budget": _BUDGET_RN,
        "campaign_budget.id": int(_BUDGET_ID),
        "campaign_budget.resource_name": _BUDGET_RN,
        "campaign_budget.amount_micros": 310_000_000,
        "campaign_budget.explicitly_shared": explicitly_shared,
    }


def _valores_irma(irma: dict[str, str]) -> dict[str, Any]:
    return {
        "campaign.id": int(irma["campaign_id"]),
        "campaign.name": irma["campaign_name"],
        "campaign.status": irma["status"],
        "campaign.campaign_budget": irma.get("budget_resource_name", _BUDGET_RN),
    }


class _FakeConn:
    async def __aenter__(self) -> _FakeConn:
        return self

    async def __aexit__(self, *a: Any) -> bool:
        return False


class _FakePool:
    def acquire(self) -> _FakeConn:
        return _FakeConn()


def _wire(
    monkeypatch: pytest.MonkeyPatch,
    *,
    explicitly_shared: bool,
    irmas: list[dict[str, str]],
) -> dict[str, Any]:
    """`run_report` falso despachado pela GAQL; `create_pending` capturado; pool falso."""
    captured: dict[str, Any] = {}

    async def _run(**kwargs: Any) -> list[dict[str, Any]]:
        q: str = kwargs["query"]
        fmt = kwargs["row_formatter"]
        if "campaign.campaign_budget IN" in q:
            # `campaigns_on_budgets_query` ja filtra REMOVED server-side.
            return [fmt(_linha(q, _valores_irma(i))) for i in irmas]
        return [fmt(_linha(q, _valores_alvo(explicitly_shared=explicitly_shared)))]

    async def _create_pending(conn: Any, **kwargs: Any) -> str:
        captured.update(kwargs)
        return "TOKEN123"

    monkeypatch.setattr(mod, "run_report", _run)
    monkeypatch.setattr(mod, "create_pending", _create_pending)
    monkeypatch.setattr(mod.connection, "get_pool", lambda: _FakePool())
    return captured


@pytest.fixture(autouse=True)
def _ctx() -> Any:
    from src.mcp.context import McpRequestContext, clear_current, set_current

    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    yield
    clear_current()


async def _preview_com(
    monkeypatch: pytest.MonkeyPatch,
    *,
    explicitly_shared: bool,
    irmas: list[dict[str, str]],
    novo_brl: float = 100.0,
) -> dict[str, Any]:
    _wire(monkeypatch, explicitly_shared=explicitly_shared, irmas=irmas)
    return await mod.update_campaign_budget(
        {
            "customer_id": _CUSTOMER,
            "campaign_id": _ALVO_ID,
            "new_daily_budget_brl": novo_brl,
        }
    )


_IRMA_CAB = {"campaign_id": _IRMA_ID, "campaign_name": "[GPC][CAB]", "status": "ENABLED"}


async def test_preview_declara_as_irmas_quando_o_orcamento_e_compartilhado(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C1: o preview nomeia UMA campanha e a mutacao atinge o portfolio.

    Sem isto, baixar o orcamento "da JPA" de R$ 310 para R$ 100 corta tambem a
    CAB, que nao aparece em lugar nenhum do preview.
    """
    envelope = await _preview_com(
        monkeypatch,
        explicitly_shared=True,
        irmas=[
            {"campaign_id": _ALVO_ID, "campaign_name": "[GPC][JPA]", "status": "ENABLED"},
            _IRMA_CAB,
        ],
    )
    sb = envelope["shared_budget"]
    assert sb is not None, "orcamento compartilhado nao declarado no preview"
    assert sb["campaigns_outside_batch"] == [
        {"campaign_id": _IRMA_ID, "campaign_name": "[GPC][CAB]", "status": "ENABLED"}
    ]
    assert "atinge" in sb["warning_pt"].lower()


async def test_orcamento_exclusivo_nao_gera_bloco(monkeypatch: pytest.MonkeyPatch) -> None:
    """Contraprova: sem ela, um `shared_budget` sempre-presente passaria verde."""
    envelope = await _preview_com(monkeypatch, explicitly_shared=False, irmas=[])
    assert envelope["shared_budget"] is None


async def test_bloco_espelha_as_chaves_do_update_ad_schedule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Simetria e requisito: quem aprendeu a ler o aviso numa tool reconhece na outra.

    A unica divergencia deliberada e `shared_budget` (dict|None) contra
    `shared_budgets` (lista): esta tool escreve em UM recurso orcamento, entao
    lista de no maximo um elemento seria ruido.
    """
    sb = (
        await _preview_com(
            monkeypatch,
            explicitly_shared=True,
            irmas=[
                {"campaign_id": _ALVO_ID, "campaign_name": "[GPC][JPA]", "status": "ENABLED"},
                _IRMA_CAB,
                {"campaign_id": "33", "campaign_name": "[GPC][REC]", "status": "PAUSED"},
            ],
        )
    )["shared_budget"]
    assert set(sb) == {
        "budget_id",
        "budget_resource_name",
        "explicitly_shared",
        "amount_brl",
        "campaigns_in_batch",
        "campaigns_outside_batch",
        "ativas_fora_do_lote",
        "warning_pt",
    }
    assert sb["budget_id"] == _BUDGET_ID
    assert sb["budget_resource_name"] == _BUDGET_RN
    assert sb["explicitly_shared"] is True
    assert sb["amount_brl"] == 310.0
    # A campanha alvo e a unica "no lote"; PAUSED entra na lista de fora mas nao conta como ativa.
    assert sb["campaigns_in_batch"] == [_ALVO_ID]
    assert [c["campaign_id"] for c in sb["campaigns_outside_batch"]] == [_IRMA_ID, "33"]
    assert sb["ativas_fora_do_lote"] == 1


async def test_blast_summary_carrega_o_portfolio(monkeypatch: pytest.MonkeyPatch) -> None:
    """`apply_change` reexibe o `blast_summary`, nao o `shared_budget`.

    Se o aviso vivesse so no envelope do dry-run, quem confirma dez minutos depois
    veria de novo "Orcamento de '[GPC][JPA]'" e nada sobre as irmas.
    """
    captured = _wire(monkeypatch, explicitly_shared=True, irmas=[_IRMA_CAB])
    envelope = await mod.update_campaign_budget(
        {"customer_id": _CUSTOMER, "campaign_id": _ALVO_ID, "new_daily_budget_brl": 100.0}
    )
    for texto in (envelope["blast_summary"], captured["blast_summary"]):
        assert "compartilhado" in texto.lower()
        assert _BUDGET_ID in texto


async def test_summary_de_orcamento_exclusivo_nao_fala_em_portfolio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Contraprova do summary: a frase nao pode ser incondicional."""
    envelope = await _preview_com(monkeypatch, explicitly_shared=False, irmas=[])
    assert "compartilhado" not in envelope["blast_summary"].lower()
    assert "[GPC][JPA]" in envelope["blast_summary"]


async def test_orcamento_compartilhado_sem_irma_ainda_declara_o_bloco(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Portfolio com uma campanha so segue sendo portfolio.

    `explicitly_shared` e propriedade do RECURSO, nao contagem de vinculos: outra
    campanha pode ser pendurada nele a qualquer momento, e a mutacao continua sendo
    no orcamento. Mesma leitura do `update_ad_schedule`, que emite o bloco pelo
    flag e nao pelo tamanho da lista.
    """
    sb = (
        await _preview_com(
            monkeypatch,
            explicitly_shared=True,
            irmas=[{"campaign_id": _ALVO_ID, "campaign_name": "[GPC][JPA]", "status": "ENABLED"}],
        )
    )["shared_budget"]
    assert sb is not None
    assert sb["campaigns_outside_batch"] == []
    assert sb["ativas_fora_do_lote"] == 0


async def test_campanha_inexistente_continua_error_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _run(**kwargs: Any) -> list[dict[str, Any]]:
        return []

    monkeypatch.setattr(mod, "run_report", _run)
    out = await mod.update_campaign_budget(
        {"customer_id": _CUSTOMER, "campaign_id": "999", "new_daily_budget_brl": 100.0}
    )
    assert out["status"] == "error"
    assert "999" in out["error_message"]


async def test_a_query_das_irmas_nao_sai_quando_o_orcamento_e_exclusivo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Orcamento exclusivo nao paga a segunda ida a API."""
    queries: list[str] = []

    async def _run(**kwargs: Any) -> list[dict[str, Any]]:
        queries.append(kwargs["query"])
        fmt = kwargs["row_formatter"]
        return [fmt(_linha(kwargs["query"], _valores_alvo(explicitly_shared=False)))]

    monkeypatch.setattr(mod, "run_report", _run)

    async def _create_pending(conn: Any, **kwargs: Any) -> str:
        return "TOKEN123"

    monkeypatch.setattr(mod, "create_pending", _create_pending)
    monkeypatch.setattr(mod.connection, "get_pool", lambda: _FakePool())
    await mod.update_campaign_budget(
        {"customer_id": _CUSTOMER, "campaign_id": _ALVO_ID, "new_daily_budget_brl": 100.0}
    )
    assert len(queries) == 1
    assert "campaign.campaign_budget IN" not in queries[0]
