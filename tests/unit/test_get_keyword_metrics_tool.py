"""get_keyword_metrics: uma chamada por cidade, ausencia de dado e ordem dos termos.

Client falso com mensagens REAIS do SDK v25; o executor roda `chamadas` na hora.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from google.ads.googleads.v25.common.types.keyword_plan_common import KeywordPlanHistoricalMetrics
from google.ads.googleads.v25.enums.types.keyword_plan_network import KeywordPlanNetworkEnum
from google.ads.googleads.v25.resources.types.geo_target_constant import GeoTargetConstant
from google.ads.googleads.v25.services.types.geo_target_constant_service import (
    GeoTargetConstantSuggestion,
    SuggestGeoTargetConstantsRequest,
    SuggestGeoTargetConstantsResponse,
)
from google.ads.googleads.v25.services.types.keyword_plan_idea_service import (
    GenerateKeywordHistoricalMetricsRequest,
    GenerateKeywordHistoricalMetricsResponse,
    GenerateKeywordHistoricalMetricsResult,
)

from src.mcp.context import McpRequestContext, clear_current, set_current
from src.mcp.tools import get_keyword_metrics as modulo

_CONTA = "6728568947"


@pytest.fixture(autouse=True)
def _ctx() -> Iterator[None]:
    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    yield
    clear_current()


def _sug(id_: int, nome: str, canonical: str) -> Any:
    return GeoTargetConstantSuggestion(
        search_term=nome,
        geo_target_constant=GeoTargetConstant(
            resource_name=f"geoTargetConstants/{id_}",
            id=id_,
            name=nome,
            country_code="BR",
            target_type="City",
            canonical_name=canonical,
        ),
    )


_GEO = [
    _sug(1001622, "João Pessoa", "Joao Pessoa,State of Paraiba,Brazil"),
    _sug(1001621, "Campina Grande", "Campina Grande,State of Paraiba,Brazil"),
]


def _res(texto: str, volume: int | None, variantes: tuple[str, ...] = ()) -> Any:
    r = GenerateKeywordHistoricalMetricsResult(text=texto, close_variants=list(variantes))
    if volume is not None:
        r.keyword_metrics = KeywordPlanHistoricalMetrics(avg_monthly_searches=volume)
    return r


class _Falso:
    def __init__(
        self,
        resultados: Callable[[Any], list[Any]] | None = None,
        sugestoes: list[Any] | None = None,
    ) -> None:
        self.requests: list[Any] = []
        self.geo_requests: list[Any] = []
        self._resultados = resultados or (lambda req: [_res(k, 10) for k in req.keywords])
        self._sugestoes = _GEO if sugestoes is None else sugestoes
        self.enums = SimpleNamespace(
            KeywordPlanNetworkEnum=SimpleNamespace(
                GOOGLE_SEARCH=KeywordPlanNetworkEnum.KeywordPlanNetwork.GOOGLE_SEARCH
            )
        )

    def get_type(self, nome: str) -> Any:
        return {
            "GenerateKeywordHistoricalMetricsRequest": GenerateKeywordHistoricalMetricsRequest,
            "SuggestGeoTargetConstantsRequest": SuggestGeoTargetConstantsRequest,
        }[nome]()

    def get_service(self, nome: str) -> Any:
        if nome == "KeywordPlanIdeaService":
            return SimpleNamespace(generate_keyword_historical_metrics=self._gerar)
        return SimpleNamespace(suggest_geo_target_constants=self._sugerir)

    def _gerar(self, request: Any) -> Any:
        self.requests.append(request)
        return GenerateKeywordHistoricalMetricsResponse(results=self._resultados(request))

    def _sugerir(self, request: Any) -> Any:
        self.geo_requests.append(request)
        return SuggestGeoTargetConstantsResponse(geo_target_constant_suggestions=self._sugestoes)


def _roda(falso: _Falso, args: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
    capturado: dict[str, Any] = {}

    async def executor(**kw: Any) -> Any:
        capturado.update(kw)
        return kw["chamadas"](falso)

    async def chama() -> dict[str, Any]:
        with patch.object(modulo, "run_keyword_planning", executor):
            return await modulo.get_keyword_metrics({"customer_id": _CONTA, **args})

    return asyncio.run(chama()), capturado


def test_termo_inexistente_vai_para_sem_dado_com_metricas_none() -> None:
    def resultados(req: Any) -> list[Any]:
        return [_res("andaime", 90), _res("xkqzw", None)]

    resp, _ = _roda(_Falso(resultados), {"termos": ["andaime", "xkqzw"]})
    por_termo = {t["termo"]: t for t in resp["termos"]}
    assert por_termo["xkqzw"]["por_cidade"]["Brasil"]["volume_mensal"] is None
    assert por_termo["andaime"]["por_cidade"]["Brasil"]["volume_mensal"] == 90
    assert resp["sem_dado"] == ["xkqzw"]


def test_sem_dado_so_se_faltar_em_todas_as_cidades() -> None:
    def resultados(req: Any) -> list[Any]:
        com_dado = req.geo_target_constants[0] == "geoTargetConstants/1001622"
        return [_res("andaime", 90 if com_dado else None)]

    resp, _ = _roda(
        _Falso(resultados), {"termos": ["andaime"], "cidades": ["João Pessoa", "Campina Grande"]}
    )
    assert resp["sem_dado"] == []
    por = resp["termos"][0]["por_cidade"]
    assert por["João Pessoa (PB)"]["volume_mensal"] == 90
    assert por["Campina Grande (PB)"]["volume_mensal"] is None


def test_variantes_ecoadas() -> None:
    def resultados(req: Any) -> list[Any]:
        return [_res("andaime", 90, ("andaimes", "andaime tubular"))]

    resp, _ = _roda(_Falso(resultados), {"termos": ["andaime"]})
    assert resp["termos"][0]["variantes"] == ["andaimes", "andaime tubular"]


def test_ordem_dos_termos_pedidos() -> None:
    def resultados(req: Any) -> list[Any]:
        return [_res("c", 5), _res("a", 900), _res("b", 50)]

    resp, _ = _roda(_Falso(resultados), {"termos": ["b", "c", "a"]})
    assert [t["termo"] for t in resp["termos"]] == ["b", "c", "a"]


def test_uma_chamada_por_cidade() -> None:
    falso = _Falso()
    resp, cap = _roda(falso, {"termos": ["a", "b"], "cidades": ["João Pessoa", "Campina Grande"]})
    assert len(falso.requests) == 2
    assert len(falso.geo_requests) == 1
    assert {r.geo_target_constants[0] for r in falso.requests} == {
        "geoTargetConstants/1001622",
        "geoTargetConstants/1001621",
    }
    assert list(falso.requests[0].keywords) == ["a", "b"]
    assert falso.requests[0].language == "languageConstants/1014"
    assert (
        falso.requests[0].keyword_plan_network
        == KeywordPlanNetworkEnum.KeywordPlanNetwork.GOOGLE_SEARCH
    )
    assert cap["estimated_ops"] == 3
    assert cap["operation_name"] == "get_keyword_metrics"
    assert set(resp["termos"][0]["por_cidade"]) == {"João Pessoa (PB)", "Campina Grande (PB)"}


def test_sem_cidade_e_brasil_e_estimated_ops() -> None:
    falso = _Falso()
    resp, cap = _roda(falso, {"termos": ["a"]})
    assert falso.geo_requests == []
    assert falso.requests[0].geo_target_constants[0] == "geoTargetConstants/2076"
    assert cap["estimated_ops"] == 1
    assert resp["recorte"]["cidades"] == "Brasil (geoTargetConstants/2076)"
    assert resp["volume_em_degraus"] is True


def test_cidade_repetida_vira_aviso() -> None:
    falso = _Falso()
    resp, _ = _roda(falso, {"termos": ["a"], "cidades": ["João Pessoa", "Joao Pessoa, PB"]})
    assert len(falso.requests) == 1
    assert any("repetida" in a for a in resp["avisos"])


def test_schema_termos_e_cidades() -> None:
    p = modulo._SCHEMA["properties"]
    assert (p["termos"]["minItems"], p["termos"]["maxItems"]) == (1, 1000)
    assert p["cidades"]["maxItems"] == 5
    assert modulo._SCHEMA["required"] == ["customer_id", "termos"]


def test_description_diz_degraus_null_e_estimativa() -> None:
    from src.mcp.tools._registry import all_tools, import_all_tools

    import_all_tools()
    d = next(t for t in all_tools() if t.name == "get_keyword_metrics").description
    assert d.startswith("[DEFER] ")
    for frase in (
        "degraus",
        "`null` significa",
        "estimativa de topo de página",
        "assumem conta BRL",
        "não depende da conta",
        "sem soma",
    ):
        assert frase in d


@pytest.mark.asyncio
async def test_cidade_nao_resolvida_audita_erro_e_nao_cobra_quota() -> None:
    """Executor REAL: cidade nao resolvida (modulo compartilhado) e erro de auditoria."""
    from tests.unit.test_run_keyword_planning import _pool_with_transactable_conn

    mod = "src.google_ads.keyword_planning"
    falso = _Falso(sugestoes=[_GEO[0]])
    with (
        patch(f"{mod}.before_call", AsyncMock(return_value=1)),
        patch(f"{mod}.record_actual", AsyncMock()) as rec,
        patch(f"{mod}.audit_log.record", AsyncMock(return_value=1)) as audit,
        patch(f"{mod}.ensure_account_access", AsyncMock()),
        patch(f"{mod}.connection.get_pool", return_value=_pool_with_transactable_conn()),
        patch(f"{mod}.build_client_for_manager", AsyncMock(return_value=falso)),
    ):
        resp = await modulo.get_keyword_metrics(
            {"customer_id": _CONTA, "termos": ["a"], "cidades": ["Atlantida"]}
        )
    assert resp["status"] == "error"
    assert resp["operation"] == "get_keyword_metrics"
    assert "Atlantida" in resp["error_message"]
    assert audit.await_args.kwargs["status"] == "error"
    assert all(c.kwargs["actual_ops"] == 0 for c in rec.await_args_list)
    assert falso.requests == []
