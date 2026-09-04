"""get_ad_schedule (spec §3): grade + resumo por campanha; vazio quer dizer 24x7."""

from __future__ import annotations

from datetime import date
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


def _fake_run_report(
    por_recurso: dict[str, list[dict[str, Any]]], *, metricas: list[dict[str, Any]] | None = None
):
    """Despacha por `FROM <recurso>` — mesmo padrao de test_get_assets.py.

    `metricas` e um desvio ANTES do despacho generico: `campaign_budget_query` e
    `day_hour_metrics_query` comecam as DUAS com `FROM campaign` (a segunda so se
    distingue pelo `segments.hour` no SELECT), entao o dispatch por `FROM <recurso>`
    sozinho nao as separa — mesmo problema que `_wire` resolve em
    test_update_ad_schedule.py, casando `segments.hour` primeiro. Retrocompativel:
    chamada sem `metricas` (default None) nunca entra nesse ramo, entao os 4
    call-sites antigos deste helper ficam intactos.
    """
    chamadas: list[str] = []

    async def _run(**kwargs: Any) -> list[dict[str, Any]]:
        q = kwargs["query"]
        chamadas.append(q)
        if metricas is not None and "segments.hour" in q:
            return metricas
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


def _orcamento(cid="1", nome="A", shared=False, status="ENABLED") -> dict[str, Any]:
    return {
        "campaign_id": cid,
        "campaign_name": nome,
        "budget_resource_name": "customers/1/campaignBudgets/77",
        "budget_id": "77",
        "explicitly_shared": shared,
        "amount_brl": 310.0,
        "status": status,
    }


def _metrica(cid="1", day="MONDAY", hour=9, cost=100.0, conv=5.0) -> dict[str, Any]:
    return {
        "campaign_id": cid,
        "day_of_week": day,
        "hour": hour,
        "cost_micros": int(cost * 1_000_000),
        "conversions": conv,
    }


def test_tool_registrada_como_always() -> None:
    t = get_tool("get_ad_schedule")
    assert t is not None and t.bucket == "always"


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
            "campaign": [_orcamento(shared=True, status="PAUSED")],
        }
    )
    monkeypatch.setattr("src.mcp.tools.get_ad_schedule.run_report", run)
    out = await mod.get_ad_schedule({"customer_id": "1234567890"})
    s = out["schedule_summary"]["1"]
    assert s == {
        "campaign_name": "A",
        "campaign_status": "PAUSED",
        "has_schedule": True,
        "windows": 2,
        "hours_per_week": 20.0,
        "budget_is_shared": True,
    }, "grade de campanha PAUSED nao afeta entrega — o resumo tem que dizer isso (F52/F90)"
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


@pytest.mark.asyncio
async def test_include_metrics_traz_cpa_por_bloco_sem_exigir_mutacao(monkeypatch) -> None:
    """O ponto do sprint: decidir grade deixa de passar pela tool de escrita."""
    run, _ = _fake_run_report(
        {"campaign_criterion": [], "campaign": [_orcamento(cid="1")]},
        metricas=[_metrica(cid="1", day="MONDAY", hour=9, cost=100.0, conv=5.0)],
    )
    monkeypatch.setattr("src.mcp.tools.get_ad_schedule.run_report", run)
    out = await mod.get_ad_schedule(
        {"customer_id": "1234567890", "campaign_ids": ["1"], "include_metrics": True}
    )
    blocos = out["schedule_summary"]["1"]["metrics_por_bloco"]
    assert blocos["comercial"]["cost_brl"] == 100.0
    assert blocos["comercial"]["cpa_brl"] == 20.0
    assert blocos["fim_de_semana"]["cells"] == 0
    # Fix Important 2 (revisao final): sem `period`, o gestor nao sabe de fora
    # qual janela concreta o preset resolveu (no fuso da conta) — so aparece
    # quando include_metrics de fato pediu a janela.
    assert set(out["period"]) == {"from", "to"}
    assert date.fromisoformat(out["period"]["from"]) <= date.fromisoformat(out["period"]["to"])


@pytest.mark.asyncio
async def test_sem_a_flag_nao_ha_consulta_de_metricas(monkeypatch) -> None:
    """A conjunta dia x hora e cara; a tool de leitura tem que continuar barata."""
    run, chamadas = _fake_run_report(
        {"campaign_criterion": [], "campaign": [_orcamento(cid="1")]}, metricas=[]
    )
    monkeypatch.setattr("src.mcp.tools.get_ad_schedule.run_report", run)
    out = await mod.get_ad_schedule({"customer_id": "1234567890", "campaign_ids": ["1"]})
    assert not any("segments.hour" in q for q in chamadas)
    assert "metrics_por_bloco" not in out["schedule_summary"]["1"]
    # Fix Important 2 (revisao final): aditivo — sem a flag, `period` tambem
    # fica de fora (nao muda o contrato de quem so le a grade).
    assert "period" not in out


@pytest.mark.asyncio
async def test_include_metrics_sem_campaign_ids_e_recusado(monkeypatch) -> None:
    """`day_hour_metrics_query` recusa lista vazia (ValueError) — a tool tem que barrar
    ANTES, sem deixar a conjunta cara escapar sobre a conta inteira (nota do brief)."""
    run, chamadas = _fake_run_report({}, metricas=[])
    monkeypatch.setattr("src.mcp.tools.get_ad_schedule.run_report", run)
    out = await mod.get_ad_schedule({"customer_id": "1234567890", "include_metrics": True})
    assert out["status"] == "error"
    assert "campaign_ids" in out["error_message"]
    assert not any("segments.hour" in q for q in chamadas)


@pytest.mark.asyncio
async def test_include_metrics_mantem_uma_linha_de_audit(monkeypatch) -> None:
    """A conjunta dia x hora e leitura ADICIONAL, nao um segundo evento de audit —
    mesma invariante de test_a_consulta_da_grade_e_auditada_e_a_de_orcamento_nao,
    agora tambem sob include_metrics."""
    vistos: list[bool] = []

    async def _run(**kwargs: Any):
        vistos.append(bool(kwargs.get("audit_this_call", False)))
        q = kwargs["query"]
        if "segments.hour" in q:
            return [_metrica(cid="1")]
        if "FROM campaign_criterion" in q:
            return []
        if "FROM campaign" in q:
            return [_orcamento(cid="1")]
        return []

    monkeypatch.setattr("src.mcp.tools.get_ad_schedule.run_report", _run)
    await mod.get_ad_schedule(
        {"customer_id": "1234567890", "campaign_ids": ["1"], "include_metrics": True}
    )
    assert vistos.count(True) == 1
