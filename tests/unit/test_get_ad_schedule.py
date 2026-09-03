"""get_ad_schedule (spec §3): grade + resumo por campanha; vazio quer dizer 24x7."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from src.mcp.tools import get_ad_schedule as mod
from src.mcp.tools._registry import get_tool


@pytest.fixture(autouse=True)
def _ctx():
    from src.mcp.context import McpRequestContext, clear_current, set_current

    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    yield
    clear_current()


def _fake_run_report(por_recurso: dict[str, list[dict[str, Any]]]):
    """Despacha por `FROM <recurso>` — mesmo padrao de test_get_assets.py."""
    chamadas: list[str] = []

    async def _run(**kwargs: Any) -> list[dict[str, Any]]:
        q = kwargs["query"]
        chamadas.append(q)
        for recurso, linhas in por_recurso.items():
            if f"FROM {recurso}" in q:
                return linhas
        return []

    return _run, chamadas


def _janela(cid="1", nome="A", day="MONDAY", sh=7, eh=17, bm=None, crit="9") -> dict[str, Any]:
    return {
        "campaign_id": cid,
        "campaign_name": nome,
        "criterion_id": crit,
        "resource_name": f"customers/1/campaignCriteria/{cid}~{crit}",
        "day_of_week": day,
        "start_hour": sh,
        "start_minute": 0,
        "end_hour": eh,
        "end_minute": 0,
        "bid_modifier": bm,
        "status": "ENABLED",
    }


def _orcamento(cid="1", nome="A", shared=False) -> dict[str, Any]:
    return {
        "campaign_id": cid,
        "campaign_name": nome,
        "budget_resource_name": "customers/1/campaignBudgets/77",
        "budget_id": "77",
        "explicitly_shared": shared,
        "amount_brl": 310.0,
    }


def test_tool_registrada_como_defer() -> None:
    t = get_tool("get_ad_schedule")
    assert t is not None and t.bucket == "defer"


def test_schema_sem_composicao() -> None:
    import json

    s = json.dumps(get_tool("get_ad_schedule").input_schema)
    assert not any(k in s for k in ("oneOf", "allOf", "anyOf"))


@pytest.mark.asyncio
async def test_campanha_sem_criterio_aparece_no_resumo_como_24x7(monkeypatch) -> None:
    """A distincao central da §3: lista vazia NAO pode ficar implicita."""
    run, _ = _fake_run_report({"campaign_criterion": [], "campaign": [_orcamento(cid="1")]})
    monkeypatch.setattr("src.mcp.tools.get_ad_schedule.run_report", run)
    out = await mod.get_ad_schedule({"customer_id": "1234567890", "campaign_ids": ["1"]})
    assert out["windows"] == []
    assert out["schedule_summary"]["1"]["has_schedule"] is False
    assert out["schedule_summary"]["1"]["hours_per_week"] == 168.0
    assert out["schedule_summary"]["1"]["budget_is_shared"] is False


@pytest.mark.asyncio
async def test_resumo_por_campanha_com_horas_e_orcamento_compartilhado(monkeypatch) -> None:
    run, _ = _fake_run_report(
        {
            "campaign_criterion": [_janela(day="MONDAY"), _janela(day="TUESDAY", crit="10")],
            "campaign": [_orcamento(shared=True)],
        }
    )
    monkeypatch.setattr("src.mcp.tools.get_ad_schedule.run_report", run)
    out = await mod.get_ad_schedule({"customer_id": "1234567890"})
    s = out["schedule_summary"]["1"]
    assert s == {
        "campaign_name": "A",
        "has_schedule": True,
        "windows": 2,
        "hours_per_week": 20.0,
        "budget_is_shared": True,
    }
    assert len(out["windows"]) == 2 and out["truncated"] is False


@pytest.mark.asyncio
async def test_limit_trunca_e_avisa(monkeypatch) -> None:
    run, chamadas = _fake_run_report(
        {"campaign_criterion": [_janela(crit=str(i)) for i in range(3)], "campaign": [_orcamento()]}
    )
    monkeypatch.setattr("src.mcp.tools.get_ad_schedule.run_report", run)
    out = await mod.get_ad_schedule({"customer_id": "1234567890", "limit": 2})
    assert len(out["windows"]) == 2 and out["truncated"] is True
    assert any("LIMIT 3" in q for q in chamadas), "a query pede limit+1 como sentinela"


@pytest.mark.asyncio
async def test_a_consulta_da_grade_e_auditada_e_a_de_orcamento_nao(monkeypatch) -> None:
    """Padrao de get_assets/get_change_history: UMA linha de audit por chamada do gestor."""
    vistos: list[bool] = []

    async def _run(**kwargs: Any):
        vistos.append(bool(kwargs.get("audit_this_call", False)))
        return []

    monkeypatch.setattr("src.mcp.tools.get_ad_schedule.run_report", _run)
    await mod.get_ad_schedule({"customer_id": "1234567890"})
    assert vistos.count(True) == 1
