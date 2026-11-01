"""meta_search_targeting e meta_get_delivery_estimate: edges, params, forma e erros."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.mcp.context import McpRequestContext, clear_current, set_current
from src.mcp.tools import meta_get_delivery_estimate as estimativa
from src.mcp.tools import meta_search_targeting as busca
from src.meta_ads import segmentacao

_CONTA = "act_1"


@pytest.fixture(autouse=True)
def _ctx() -> Iterator[None]:
    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    yield
    clear_current()


def _graph(resposta: Any) -> tuple[AsyncMock, Any]:
    g = AsyncMock(side_effect=resposta if isinstance(resposta, list) else [resposta])
    return g, patch.object(segmentacao, "run_meta_graph_get", g)


def _interesses(n: int) -> list[dict[str, Any]]:
    return [
        {
            "id": str(i),
            "name": f"Interesse {i}",
            "type": "interests",
            "path": ["Interests", "Sports"],
            "audience_size_lower_bound": 1000,
            "audience_size_upper_bound": "2000",
        }
        for i in range(n)
    ]


# ---------- busca ----------


@pytest.mark.asyncio
async def test_busca_forma_e_faixa_com_limites_separados() -> None:
    g, p = _graph({"data": _interesses(1)})
    with p:
        r = await busca.meta_search_targeting({"ad_account_id": _CONTA, "q": "futebol"})
    assert r["status"] == "success" and r["truncated"] is False
    item = r["results"][0]
    assert item["audiencia_minima"] == 1000 and item["audiencia_maxima"] == 2000
    assert item["caminho"] == ["Interests", "Sports"] and item["descricao"] is None


@pytest.mark.asyncio
async def test_busca_edge_params_e_auditoria() -> None:
    g, p = _graph({"data": []})
    with p:
        r = await busca.meta_search_targeting(
            {"ad_account_id": _CONTA, "q": "  futebol ", "limit": 10}
        )
    assert r["status"] == "success" and r["results"] == [] and r["truncated"] is False
    kw = g.await_args_list[0].kwargs
    assert kw["edge"] == "/act_1/targetingsearch"
    assert kw["ad_account_id"] == "act_1"
    assert kw["operation_name"] == "meta_search_targeting"
    assert kw["audit_this_call"] is True
    assert kw["params"]["q"] == "futebol" and kw["params"]["limit"] == 11
    assert "audience_size_lower_bound" in kw["params"]["fields"]


@pytest.mark.asyncio
async def test_busca_q_curto_erra_sem_chamar_a_graph() -> None:
    g, p = _graph({"data": []})
    with p:
        for q in ("", "a", "  a  ", "   "):
            r = await busca.meta_search_targeting({"ad_account_id": _CONTA, "q": q})
            assert r["status"] == "error" and "2 caracteres" in r["error_message"]
    g.assert_not_awaited()


@pytest.mark.asyncio
async def test_busca_api_ignora_limit_corta_no_cliente_e_marca_truncated() -> None:
    g, p = _graph({"data": _interesses(40)})
    with p:
        r = await busca.meta_search_targeting({"ad_account_id": _CONTA, "q": "ab", "limit": 25})
    assert len(r["results"]) == 25 and r["total_returned"] == 25
    assert r["truncated"] is True and r["truncated_hint"]


@pytest.mark.asyncio
async def test_busca_paging_next_marca_truncated() -> None:
    g, p = _graph({"data": _interesses(3), "paging": {"next": "https://x"}})
    with p:
        r = await busca.meta_search_targeting({"ad_account_id": _CONTA, "q": "ab", "limit": 5})
    assert r["truncated"] is True


@pytest.mark.asyncio
async def test_busca_limit_fora_da_faixa_erra() -> None:
    g, p = _graph({"data": []})
    with p:
        r = await busca.meta_search_targeting({"ad_account_id": _CONTA, "q": "ab", "limit": 101})
    assert r["status"] == "error"
    g.assert_not_awaited()


@pytest.mark.asyncio
async def test_busca_erro_da_graph_vira_envelope() -> None:
    g, p = _graph([RuntimeError("falhou")])
    with p:
        r = await busca.meta_search_targeting({"ad_account_id": _CONTA, "q": "ab"})
    assert r == {"status": "error", "error_message": "falhou"}


def test_busca_schema_declara_q_minimo_e_limites() -> None:
    props = busca._SCHEMA["properties"]
    assert props["q"]["minLength"] == 2
    assert props["limit"]["default"] == 25 and props["limit"]["maximum"] == 100
    assert busca._SCHEMA["required"] == ["ad_account_id", "q"]


# ---------- estimativa ----------

_SPEC = {"geo_locations": {"countries": ["BR"]}, "age_min": 25}
_LINHA = {
    "estimate_mau_lower_bound": 1000,
    "estimate_mau_upper_bound": 2000,
    "estimate_dau": 300,
    "estimate_ready": True,
    "daily_outcomes_curve": [{"spend": 1, "reach": 2}],
}


@pytest.mark.asyncio
async def test_estimativa_forma_aproximada_sem_curva() -> None:
    g, p = _graph({"data": [_LINHA]})
    with p:
        r = await estimativa.meta_get_delivery_estimate(
            {"ad_account_id": _CONTA, "targeting_spec": _SPEC}
        )
    assert r["status"] == "success" and r["aproximado"] is True
    assert r["estimate"] == {
        "alcance_mensal_minimo": 1000,
        "alcance_mensal_maximo": 2000,
        "alcance_diario": 300,
        "estimativa_pronta": True,
    }
    assert "daily_outcomes_curve" not in json.dumps(r)


@pytest.mark.asyncio
async def test_estimativa_edge_params_json_e_auditoria() -> None:
    g, p = _graph({"data": [_LINHA]})
    with p:
        await estimativa.meta_get_delivery_estimate(
            {"ad_account_id": _CONTA, "targeting_spec": _SPEC}
        )
    kw = g.await_args_list[0].kwargs
    assert kw["edge"] == "/act_1/delivery_estimate"
    assert kw["ad_account_id"] == "act_1"
    assert kw["operation_name"] == "meta_get_delivery_estimate"
    assert kw["audit_this_call"] is True
    assert json.loads(kw["params"]["targeting_spec"]) == _SPEC
    assert isinstance(kw["params"]["targeting_spec"], str)
    assert kw["params"]["optimization_goal"] == "REACH"


@pytest.mark.asyncio
async def test_estimativa_objetivo_explicito_vai_na_chamada() -> None:
    g, p = _graph({"data": [_LINHA]})
    with p:
        r = await estimativa.meta_get_delivery_estimate(
            {
                "ad_account_id": _CONTA,
                "targeting_spec": _SPEC,
                "optimization_goal": "LINK_CLICKS",
            }
        )
    assert g.await_args_list[0].kwargs["params"]["optimization_goal"] == "LINK_CLICKS"
    assert r["optimization_goal"] == "LINK_CLICKS"


@pytest.mark.asyncio
@pytest.mark.parametrize("spec", ["texto", "[1]", '"x"', "5", "null", [1], 5, None])
async def test_estimativa_spec_que_nao_e_objeto_erra_sem_chamar_a_graph(spec: Any) -> None:
    g, p = _graph({"data": []})
    with p:
        r = await estimativa.meta_get_delivery_estimate(
            {"ad_account_id": _CONTA, "targeting_spec": spec}
        )
    assert r["status"] == "error" and "objeto JSON" in r["error_message"]
    g.assert_not_awaited()


@pytest.mark.asyncio
async def test_estimativa_spec_como_texto_json_de_objeto_e_aceito() -> None:
    g, p = _graph({"data": [_LINHA]})
    with p:
        r = await estimativa.meta_get_delivery_estimate(
            {"ad_account_id": _CONTA, "targeting_spec": json.dumps(_SPEC)}
        )
    assert r["status"] == "success"
    assert json.loads(g.await_args_list[0].kwargs["params"]["targeting_spec"]) == _SPEC


@pytest.mark.asyncio
async def test_estimativa_limite_inferior_zero_e_dau_zero_ficam_zero() -> None:
    linha = {"estimate_mau_lower_bound": 0, "estimate_dau": 0, "estimate_ready": True}
    g, p = _graph({"data": [linha]})
    with p:
        r = await estimativa.meta_get_delivery_estimate(
            {"ad_account_id": _CONTA, "targeting_spec": _SPEC}
        )
    assert r["estimate"]["alcance_mensal_minimo"] == 0
    assert r["estimate"]["alcance_diario"] == 0
    assert r["estimate"]["alcance_mensal_maximo"] is None


@pytest.mark.asyncio
async def test_estimativa_objetivo_invalido_erra_sem_chamar_a_graph() -> None:
    g, p = _graph({"data": []})
    with p:
        r = await estimativa.meta_get_delivery_estimate(
            {"ad_account_id": _CONTA, "targeting_spec": _SPEC, "optimization_goal": "X"}
        )
    assert r["status"] == "error"
    g.assert_not_awaited()


@pytest.mark.asyncio
async def test_estimativa_nao_pronta_volta_como_veio_com_limites_null() -> None:
    g, p = _graph({"data": [{"estimate_ready": False}]})
    with p:
        r = await estimativa.meta_get_delivery_estimate(
            {"ad_account_id": _CONTA, "targeting_spec": _SPEC}
        )
    assert r["status"] == "success"
    assert r["estimate"] == {
        "alcance_mensal_minimo": None,
        "alcance_mensal_maximo": None,
        "alcance_diario": None,
        "estimativa_pronta": False,
    }


@pytest.mark.asyncio
async def test_estimativa_data_vazio_e_null_com_motivo_nao_erro() -> None:
    g, p = _graph({"data": []})
    with p:
        r = await estimativa.meta_get_delivery_estimate(
            {"ad_account_id": _CONTA, "targeting_spec": _SPEC}
        )
    assert r["status"] == "success" and r["estimate"] is None
    assert r["aproximado"] is True and r["reason"]


@pytest.mark.asyncio
async def test_estimativa_erro_da_graph_vira_envelope() -> None:
    g, p = _graph([RuntimeError("400")])
    with p:
        r = await estimativa.meta_get_delivery_estimate(
            {"ad_account_id": _CONTA, "targeting_spec": _SPEC}
        )
    assert r == {"status": "error", "error_message": "400"}


def test_estimativa_schema_enum_e_default() -> None:
    props = estimativa._SCHEMA["properties"]
    assert props["targeting_spec"]["type"] == "object"
    assert props["optimization_goal"]["default"] == "REACH"
    assert "REACH" in props["optimization_goal"]["enum"]
    assert "REACH" in props["optimization_goal"]["description"]
