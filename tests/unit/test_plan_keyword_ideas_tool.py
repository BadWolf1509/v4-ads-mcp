"""plan_keyword_ideas: chamadas por origem x cidade, falha parcial e erros claros.

O client falso devolve mensagens REAIS do SDK v25; o executor e trocado por um que
roda `chamadas` na hora, com o client falso.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from google.ads.googleads.errors import GoogleAdsException
from google.ads.googleads.v25.common.types.keyword_plan_common import KeywordPlanHistoricalMetrics
from google.ads.googleads.v25.errors.types.errors import ErrorCode, GoogleAdsError, GoogleAdsFailure
from google.ads.googleads.v25.errors.types.quota_error import QuotaErrorEnum
from google.ads.googleads.v25.resources.types.geo_target_constant import GeoTargetConstant
from google.ads.googleads.v25.services.types.geo_target_constant_service import (
    GeoTargetConstantSuggestion,
    SuggestGeoTargetConstantsRequest,
    SuggestGeoTargetConstantsResponse,
)
from google.ads.googleads.v25.services.types.keyword_plan_idea_service import (
    GenerateKeywordIdeaResult,
    GenerateKeywordIdeasRequest,
)

from src.mcp.context import McpRequestContext, clear_current, set_current
from src.mcp.tools import plan_keyword_ideas as modulo

_CONTA = "6728568947"


@pytest.fixture(autouse=True)
def _ctx() -> Iterator[None]:
    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    yield
    clear_current()


def _sug(id_: int, nome: str, tipo: str, canonical: str, termo: str) -> Any:
    return GeoTargetConstantSuggestion(
        search_term=termo,
        geo_target_constant=GeoTargetConstant(
            resource_name=f"geoTargetConstants/{id_}",
            id=id_,
            name=nome,
            country_code="BR",
            target_type=tipo,
            canonical_name=canonical,
        ),
    )


_GEO = [
    _sug(1001622, "João Pessoa", "City", "Joao Pessoa,State of Paraiba,Brazil", "João Pessoa"),
    _sug(
        1001621,
        "Campina Grande",
        "City",
        "Campina Grande,State of Paraiba,Brazil",
        "Campina Grande",
    ),
]


def _ideia(texto: str, volume: int | None) -> Any:
    r = GenerateKeywordIdeaResult(text=texto)
    if volume is not None:
        r.keyword_idea_metrics = KeywordPlanHistoricalMetrics(avg_monthly_searches=volume)
    return r


def _falha(codigo: str) -> GoogleAdsException:
    erro = GoogleAdsError(message="x")
    if codigo == "QUOTA_ERROR":
        erro.error_code = ErrorCode(quota_error=QuotaErrorEnum.QuotaError.RESOURCE_EXHAUSTED)
    else:
        erro.error_code = ErrorCode(internal_error=2)
    failure = GoogleAdsFailure(errors=[erro])
    return GoogleAdsException(MagicMock(), MagicMock(), failure, "rid")


class _Falso:
    """Client falso: registra requests e devolve mensagens reais."""

    def __init__(
        self,
        ideias: Callable[[Any], list[Any]] | None = None,
        sugestoes: list[Any] | None = None,
    ) -> None:
        self.requests: list[Any] = []
        self.geo_requests: list[Any] = []
        self._ideias = ideias or (lambda req: [_ideia("aluguel de andaime", 40)])
        self._sugestoes = _GEO if sugestoes is None else sugestoes
        self.enums = SimpleNamespace(
            KeywordPlanNetworkEnum=SimpleNamespace(GOOGLE_SEARCH="GOOGLE_SEARCH")
        )

    def get_type(self, nome: str) -> Any:
        return {
            "GenerateKeywordIdeasRequest": GenerateKeywordIdeasRequest,
            "SuggestGeoTargetConstantsRequest": SuggestGeoTargetConstantsRequest,
        }[nome]()

    def get_service(self, nome: str) -> Any:
        if nome == "KeywordPlanIdeaService":
            return SimpleNamespace(generate_keyword_ideas=self._gerar)
        return SimpleNamespace(suggest_geo_target_constants=self._sugerir)

    def _gerar(self, request: Any) -> list[Any]:
        self.requests.append(request)
        return self._ideias(request)

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
            return await modulo.plan_keyword_ideas({"customer_id": _CONTA, **args})

    import asyncio

    return asyncio.run(chama()), capturado


def test_sementes_e_site_em_chamadas_separadas() -> None:
    falso = _Falso()
    _roda(falso, {"sementes": ["aluguel de andaime"], "site": "https://www.mestredaobra.com.br"})
    seeds = [r._pb.WhichOneof("seed") for r in falso.requests]
    assert sorted(seeds) == ["keyword_seed", "url_seed"]
    assert "keyword_and_url_seed" not in seeds
    assert falso.requests[0].page_size == 1000
    assert falso.requests[0].language == "languageConstants/1014"


def test_uma_chamada_por_cidade() -> None:
    falso = _Falso()
    resp, _ = _roda(
        falso,
        {
            "sementes": ["a"],
            "site": "https://x.com.br",
            "cidades": ["João Pessoa", "Campina Grande"],
        },
    )
    assert len(falso.requests) == 4
    assert len(falso.geo_requests) == 1
    assert list(falso.geo_requests[0].location_names.names) == ["João Pessoa", "Campina Grande"]
    assert {r.geo_target_constants[0] for r in falso.requests} == {
        "geoTargetConstants/1001622",
        "geoTargetConstants/1001621",
    }
    assert set(resp["ideias"][0]["por_cidade"]) == {"João Pessoa (PB)", "Campina Grande (PB)"}


def test_cidade_com_uf_usa_so_o_nome_e_aviso_quando_difere() -> None:
    sug = [
        _sug(1001621, "Campina Grande", "City", "Campina Grande,State of Paraiba,Brazil", "Campina")
    ]
    falso = _Falso(sugestoes=sug)
    resp, _ = _roda(falso, {"sementes": ["a"], "cidades": ["Campina, PB"]})
    assert list(falso.geo_requests[0].location_names.names) == ["Campina"]
    assert resp["avisos"] == ["cidade pedida 'Campina' resolvida como 'Campina Grande'"]


def test_sem_cidade_e_brasil() -> None:
    falso = _Falso()
    resp, _ = _roda(falso, {"sementes": ["a"]})
    assert falso.geo_requests == []
    assert falso.requests[0].geo_target_constants[0] == "geoTargetConstants/2076"
    assert resp["recorte"]["cidades"] == "Brasil (geoTargetConstants/2076)"
    assert set(resp["ideias"][0]["por_cidade"]) == {"Brasil"}
    assert resp["volume_em_degraus"] is True


def test_url_concorrente_falha_e_resto_volta() -> None:
    def ideias(req: Any) -> list[Any]:
        if req.url_seed.url == "https://www.rival.com.br":
            raise _falha("INTERNAL_ERROR")
        return [_ideia("andaime", 90)]

    resp, _ = _roda(
        _Falso(ideias),
        {"sementes": ["a"], "concorrentes": ["https://www.rival.com.br", "https://ok.com.br"]},
    )
    assert [f["origem"] for f in resp["origens_com_falha"]] == ["concorrente:rival.com.br"]
    assert resp["origens_com_falha"][0]["cidade"] == "Brasil"
    assert resp["origens_com_falha"][0]["erro"]
    assert resp["ideias"][0]["origens"] == ["semente", "concorrente:ok.com.br"]


def test_quota_na_url_derruba_tudo() -> None:
    def ideias(req: Any) -> list[Any]:
        if GenerateKeywordIdeasRequest.pb(req).WhichOneof("seed") == "url_seed":
            raise _falha("QUOTA_ERROR")
        return [_ideia("andaime", 90)]

    with pytest.raises(GoogleAdsException):
        _roda(_Falso(ideias), {"sementes": ["a"], "site": "https://x.com.br"})


def test_falha_na_semente_derruba_tudo() -> None:
    def ideias(req: Any) -> list[Any]:
        raise _falha("INTERNAL_ERROR")

    with pytest.raises(GoogleAdsException):
        _roda(_Falso(ideias), {"sementes": ["a"]})


def test_cidade_nao_resolvida_vira_erro_claro() -> None:
    falso = _Falso(sugestoes=[_GEO[0]])
    resp, _ = _roda(falso, {"sementes": ["a"], "cidades": ["Atlantida"]})
    assert resp["status"] == "error"
    assert "Atlantida" in resp["error_message"]
    assert "Joao Pessoa,State of Paraiba,Brazil" in resp["error_message"]
    assert falso.requests == []


def test_sem_entrada_recusa() -> None:
    resp, cap = _roda(_Falso(), {})
    assert resp["status"] == "error"
    assert "sementes" in resp["error_message"]
    assert cap == {}


def test_estimated_ops() -> None:
    _, cap = _roda(
        _Falso(),
        {
            "sementes": ["a"],
            "site": "https://x.com.br",
            "concorrentes": ["https://a.com.br", "https://b.com.br"],
            "cidades": ["João Pessoa"],
        },
    )
    assert cap["estimated_ops"] == 5
    assert cap["operation_name"] == "plan_keyword_ideas"
    assert cap["params_summary"]["cidades"] == ["João Pessoa"]
    assert cap["params_summary"]["concorrentes"] == ["a.com.br", "b.com.br"]


def test_estimated_ops_sem_cidade() -> None:
    _, cap = _roda(_Falso(), {"sementes": ["a"], "site": "https://x.com.br"})
    assert cap["estimated_ops"] == 2


def test_ordem_limit_e_nao_medido_nao_e_zero() -> None:
    def ideias(req: Any) -> list[Any]:
        return [_ideia("b", None), _ideia("a", 10), _ideia("c", 90)]

    resp, _ = _roda(_Falso(ideias), {"sementes": ["x"], "limit": 2})
    assert [i["termo"] for i in resp["ideias"]] == ["c", "a"]
    assert resp["total_ideias"] == 3
    assert resp["truncated"] is True
    resp2, _ = _roda(_Falso(ideias), {"sementes": ["x"]})
    ultimo = resp2["ideias"][-1]
    assert ultimo["termo"] == "b"
    assert ultimo["volume_maximo"] is None
    assert ultimo["por_cidade"]["Brasil"]["volume_mensal"] is None
    assert resp2["truncated"] is False


def test_schema_limit_tem_minimo_e_maximo() -> None:
    p = modulo._SCHEMA["properties"]["limit"]
    assert (p["minimum"], p["maximum"], p["default"]) == (1, 1000, 200)


def test_description_diz_degraus_null_e_estimativa() -> None:
    from src.mcp.tools._registry import all_tools, import_all_tools

    import_all_tools()
    d = next(t for t in all_tools() if t.name == "plan_keyword_ideas").description
    assert d.startswith("[DEFER] ")
    for frase in (
        "degraus",
        "`null` significa",
        "estimativa de topo de página",
        "não depende da conta",
    ):
        assert frase in d
