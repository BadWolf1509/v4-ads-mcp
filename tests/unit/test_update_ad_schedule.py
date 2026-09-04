"""update_ad_schedule (spec §4): grade completa, dry-run com CPA, orcamento compartilhado, no-op."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from src.google_ads.queries.ad_schedule import GRADE_LIMIT
from src.governance.blast_radius import RiskLevel, classify
from src.mcp.tools import update_ad_schedule as mod
from src.mcp.tools._registry import get_tool


def test_classify_conhece_a_operacao_e_confirma() -> None:
    """Sem entrada propria a tool cai no 'unknown operation — default seguro' (nota do estado-atual)."""
    r = classify(operation="update_ad_schedule", params={"target_count": 3})
    assert r.level is RiskLevel.CONFIRM
    assert "unknown" not in r.reason


@pytest.fixture(autouse=True)
def _ctx():
    from src.mcp.context import McpRequestContext, clear_current, set_current

    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    yield
    clear_current()


class _FakeConn:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _FakePool:
    def acquire(self):
        return _FakeConn()


def _janela_row(cid="1", day="MONDAY", sh=7, eh=17, crit="9", bm=None) -> dict[str, Any]:
    return {
        "campaign_id": cid,
        "campaign_name": "A",
        "criterion_id": crit,
        "resource_name": f"customers/1234567890/campaignCriteria/{cid}~{crit}",
        "day_of_week": day,
        "start_hour": sh,
        "start_minute": 0,
        "end_hour": eh,
        "end_minute": 0,
        "bid_modifier": bm,
        "status": "ENABLED",
    }


def _orc(
    cid="1", shared=False, rn="customers/1234567890/campaignBudgets/77", status="ENABLED"
) -> dict[str, Any]:
    return {
        "campaign_id": cid,
        "campaign_name": "A",
        "budget_resource_name": rn,
        "budget_id": "77",
        "explicitly_shared": shared,
        "amount_brl": 310.0,
        "status": status,
    }


def _cell(cid="1", day="SATURDAY", hour=10, cost=100.0, conv=5.0) -> dict[str, Any]:
    return {
        "campaign_id": cid,
        "day_of_week": day,
        "hour": hour,
        "cost_micros": int(cost * 1_000_000),
        "conversions": conv,
    }


def _wire(monkeypatch, *, grade, orcamentos, metricas, irmas=None):
    """run_report falso despachado por FROM/segments; create_pending capturado; pool falso."""
    captured: dict[str, Any] = {}

    async def _run(**kwargs: Any):
        q = kwargs["query"]
        if "FROM campaign_criterion" in q:
            return grade
        if "segments.hour" in q:
            return metricas
        if "campaign.campaign_budget IN" in q:
            return irmas or []
        if "FROM campaign" in q:
            return orcamentos
        return []

    async def _create_pending(conn, **kwargs):
        captured.update(kwargs)
        return "TOKEN123"

    monkeypatch.setattr("src.mcp.tools.update_ad_schedule.run_report", _run)
    monkeypatch.setattr("src.mcp.tools.update_ad_schedule.create_pending", _create_pending)
    monkeypatch.setattr("src.mcp.tools.update_ad_schedule.connection.get_pool", lambda: _FakePool())
    return captured


SEG_SEX = [
    {"day_of_week": d, "start_hour": 7, "end_hour": 17}
    for d in ("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY")
]


def test_tool_registrada_como_defer_e_schema_sem_composicao() -> None:
    import json

    t = get_tool("update_ad_schedule")
    assert t is not None and t.bucket == "defer"
    assert not any(k in json.dumps(t.input_schema) for k in ("oneOf", "allOf", "anyOf"))


@pytest.mark.asyncio
async def test_minuto_invalido_e_recusado_antes_de_qualquer_query(monkeypatch) -> None:
    """Spec §8.1."""
    chamou = []

    async def _run(**kwargs):
        chamou.append(1)
        return []

    monkeypatch.setattr("src.mcp.tools.update_ad_schedule.run_report", _run)
    out = await mod.update_ad_schedule(
        {
            "customer_id": "1234567890",
            "campaign_ids": ["1"],
            "windows": [
                {"day_of_week": "MONDAY", "start_hour": 7, "start_minute": 10, "end_hour": 17}
            ],
        }
    )
    assert (
        out["status"] == "error" and "15" in out["error_message"] and "45" in out["error_message"]
    )
    assert chamou == []


@pytest.mark.asyncio
async def test_grade_completa_uma_janela_numa_campanha_com_cinco_remove_quatro(monkeypatch) -> None:
    """Spec §8.2 — a guarda do conjunto-vs-incremento, agora pela TOOL."""
    grade = [
        _janela_row(day=d, crit=str(i))
        for i, d in enumerate(("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY"))
    ]
    captured = _wire(monkeypatch, grade=grade, orcamentos=[_orc()], metricas=[])
    out = await mod.update_ad_schedule(
        {
            "customer_id": "1234567890",
            "campaign_ids": ["1"],
            "windows": [{"day_of_week": "MONDAY", "start_hour": 7, "end_hour": 17}],
        }
    )
    assert out["status"] == "dry_run"
    p = out["preview"]["1"]
    assert len(p["windows_removed"]) == 4 and p["windows_added"] == []
    ops = captured["payload"]["ops"]
    assert sum(1 for o in ops if o["kind"] == "remove") == 4 and not any(
        o["kind"] == "add" for o in ops
    )


@pytest.mark.asyncio
async def test_grade_identica_devolve_no_changes_sem_token(monkeypatch) -> None:
    """Spec §8.9 — zero operacoes, nenhum token."""
    grade = [_janela_row(day=d, crit=str(i)) for i, d in enumerate(("MONDAY", "TUESDAY"))]
    captured = _wire(monkeypatch, grade=grade, orcamentos=[_orc()], metricas=[])
    out = await mod.update_ad_schedule(
        {
            "customer_id": "1234567890",
            "campaign_ids": ["1"],
            "windows": [
                {"day_of_week": "MONDAY", "start_hour": 7, "end_hour": 17},
                {"day_of_week": "TUESDAY", "start_hour": 7, "end_hour": 17},
            ],
        }
    )
    assert out["status"] == "no_changes" and out["no_changes"] is True
    assert "confirmation_token" not in out
    assert captured == {}, "create_pending nao pode ter sido chamado"


@pytest.mark.asyncio
async def test_preview_traz_cpa_do_que_sai_e_do_que_fica(monkeypatch) -> None:
    """Spec §8.3 — dry-run sem `conversions` nao passa. Campanha 24x7 vira seg-sex."""
    metricas = [
        _cell(day="SATURDAY", cost=100.0, conv=5.0),
        _cell(day="SUNDAY", cost=50.0, conv=5.0),
        _cell(day="MONDAY", hour=9, cost=300.0, conv=10.0),
    ]
    _wire(monkeypatch, grade=[], orcamentos=[_orc()], metricas=metricas)
    out = await mod.update_ad_schedule(
        {"customer_id": "1234567890", "campaign_ids": ["1"], "windows": SEG_SEX}
    )
    m = out["preview"]["1"]["metrics"]
    assert m["leaving"] == {"cost_brl": 150.0, "conversions": 10.0, "cpa_brl": 15.0, "cells": 2}
    assert m["staying"]["cpa_brl"] == 30.0
    assert out["preview"]["1"]["was_24x7"] is True
    assert out["metrics_window"]["days"] == 30


@pytest.mark.asyncio
async def test_orcamento_compartilhado_chega_ao_preview_com_as_irmas_fora_do_lote(
    monkeypatch,
) -> None:
    """Spec §8.4 + decisao 03/09: avisar agrupado por orcamento, nao recusar."""
    irmas = [
        {
            "campaign_id": "1",
            "campaign_name": "A",
            "budget_resource_name": "customers/1234567890/campaignBudgets/77",
            "status": "ENABLED",
        },
        {
            "campaign_id": "2",
            "campaign_name": "B",
            "budget_resource_name": "customers/1234567890/campaignBudgets/77",
            "status": "ENABLED",
        },
    ]
    _wire(monkeypatch, grade=[], orcamentos=[_orc(shared=True)], metricas=[], irmas=irmas)
    out = await mod.update_ad_schedule(
        {"customer_id": "1234567890", "campaign_ids": ["1"], "windows": SEG_SEX}
    )
    sb = out["shared_budgets"]
    assert len(sb) == 1 and sb[0]["budget_id"] == "77" and sb[0]["explicitly_shared"] is True
    assert sb[0]["campaigns_in_batch"] == ["1"] and sb[0]["campaigns_outside_batch"] == [
        {"campaign_id": "2", "campaign_name": "B", "status": "ENABLED"}
    ]
    assert sb[0]["ativas_fora_do_lote"] == 1
    assert "realoca" in sb[0]["warning_pt"].lower()
    assert out["status"] == "dry_run"


@pytest.mark.asyncio
async def test_orcamento_nao_compartilhado_nao_gera_bloco(monkeypatch) -> None:
    _wire(monkeypatch, grade=[], orcamentos=[_orc(shared=False)], metricas=[])
    out = await mod.update_ad_schedule(
        {"customer_id": "1234567890", "campaign_ids": ["1"], "windows": SEG_SEX}
    )
    assert out["shared_budgets"] == []


@pytest.mark.asyncio
async def test_payload_pendente_leva_partial_failure_e_target_count_igual_ao_numero_de_ops(
    monkeypatch,
) -> None:
    captured = _wire(monkeypatch, grade=[], orcamentos=[_orc()], metricas=[])
    await mod.update_ad_schedule(
        {"customer_id": "1234567890", "campaign_ids": ["1"], "windows": SEG_SEX}
    )
    p = captured["payload"]
    assert p["__partial_failure__"] is True and p["__target_count__"] == 5 == len(p["ops"])
    assert captured["operation_type"] == "update_ad_schedule"


@pytest.mark.asyncio
async def test_payload_leva_a_grade_pedida_e_o_fingerprint_do_baseline(monkeypatch) -> None:
    """Important 2/3: sem a grade PEDIDA no payload, apply_change nao tem contra o que
    comparar a resultante; sem o fingerprint do baseline OBSERVADO, ele aplica um delta
    de ate 10 min atras contra um estado que ninguem verificou (Ruling 10)."""
    grade = [_janela_row(day="MONDAY", crit="9"), _janela_row(day="SATURDAY", crit="10")]
    captured = _wire(monkeypatch, grade=grade, orcamentos=[_orc()], metricas=[])
    await mod.update_ad_schedule(
        {
            "customer_id": "1234567890",
            "campaign_ids": ["1"],
            "windows": [{"day_of_week": "MONDAY", "start_hour": 7, "end_hour": 17}],
        }
    )
    p = captured["payload"]
    assert p["windows"] == [
        {
            "day_of_week": "MONDAY",
            "start_hour": 7,
            "start_minute": 0,
            "end_hour": 17,
            "end_minute": 0,
        }
    ]
    assert p["current_keys"] == {"1": [["MONDAY", 7, 0, 17, 0], ["SATURDAY", 7, 0, 17, 0]]}, (
        "listas, nao tuplas: o payload atravessa JSON"
    )


@pytest.mark.asyncio
async def test_campaign_id_inexistente_e_recusado_antes_de_montar_preview(monkeypatch) -> None:
    """Sem linha de orcamento a campanha nao existe na conta — nao pode virar 'servia 24x7'."""
    captured = _wire(monkeypatch, grade=[], orcamentos=[_orc(cid="1")], metricas=[])
    out = await mod.update_ad_schedule(
        {"customer_id": "1234567890", "campaign_ids": ["1", "999"], "windows": SEG_SEX}
    )
    assert out["status"] == "error" and "999" in out["error_message"]
    assert captured == {}


@pytest.mark.asyncio
async def test_grade_atual_truncada_nao_e_diffada(monkeypatch) -> None:
    """Important 4: `ad_schedule_query` pede limit+1 como sentinela e o caminho de
    MUTACAO nunca checava. Grade parcial gera `add` de janela que ja existe E omite
    `remove` de janela nunca vista — o diff erra nas duas direcoes, numa escrita."""
    grade = [_janela_row(day="MONDAY", crit=str(i)) for i in range(GRADE_LIMIT + 1)]
    captured = _wire(monkeypatch, grade=grade, orcamentos=[_orc()], metricas=[])
    out = await mod.update_ad_schedule(
        {"customer_id": "1234567890", "campaign_ids": ["1"], "windows": SEG_SEX}
    )
    assert out["status"] == "error"
    assert str(GRADE_LIMIT) in out["error_message"]
    assert captured == {}, "nenhum token pode ser mintado sobre grade truncada"


@pytest.mark.asyncio
async def test_campanha_removed_e_recusada_citando_o_id(monkeypatch) -> None:
    """Important 5(a): com `campaign_ids`, campaign_budget_query NAO derruba REMOVED —
    a campanha e encontrada e passava direto, enquanto a mensagem de recusa afirmava
    checar remocao. Agora a checagem existe e a mensagem e verdadeira."""
    captured = _wire(
        monkeypatch,
        grade=[],
        orcamentos=[_orc(cid="1"), _orc(cid="2", status="REMOVED")],
        metricas=[],
    )
    out = await mod.update_ad_schedule(
        {"customer_id": "1234567890", "campaign_ids": ["1", "2"], "windows": SEG_SEX}
    )
    assert out["status"] == "error" and "2" in out["error_message"]
    assert "REMOVED" in out["error_message"]
    assert captured == {}


@pytest.mark.asyncio
async def test_mensagem_de_id_ausente_nao_afirma_checagem_que_nao_faz(monkeypatch) -> None:
    """Important 5(a): a mensagem antiga dizia 'nao encontradas nesta conta (ou
    removidas)' — mas removida E encontrada por essa query. Nao afirmar o que nao checa."""
    _wire(monkeypatch, grade=[], orcamentos=[_orc(cid="1")], metricas=[])
    out = await mod.update_ad_schedule(
        {"customer_id": "1234567890", "campaign_ids": ["1", "999"], "windows": SEG_SEX}
    )
    assert out["status"] == "error" and "999" in out["error_message"]
    assert "removidas" not in out["error_message"].lower()


@pytest.mark.asyncio
async def test_campanha_pausada_avisa_mas_nao_recusa(monkeypatch) -> None:
    """Important 5(b), familia F52/F90: toda a narrativa de CPA da §4.2 pode ser sobre
    campanha inerte. As irmas ja tinham `ativas_fora_do_lote`; a ALVO ficou cega."""
    _wire(monkeypatch, grade=[], orcamentos=[_orc(status="PAUSED")], metricas=[])
    out = await mod.update_ad_schedule(
        {"customer_id": "1234567890", "campaign_ids": ["1"], "windows": SEG_SEX}
    )
    assert out["status"] == "dry_run"
    p = out["preview"]["1"]
    assert p["campaign_status"] == "PAUSED"
    assert p["aviso_status"] is not None and "PAUSED" in p["aviso_status"]
    assert "historicas" in p["aviso_status"]


@pytest.mark.asyncio
async def test_campanha_ativa_nao_ganha_aviso_de_status(monkeypatch) -> None:
    _wire(monkeypatch, grade=[], orcamentos=[_orc(status="ENABLED")], metricas=[])
    out = await mod.update_ad_schedule(
        {"customer_id": "1234567890", "campaign_ids": ["1"], "windows": SEG_SEX}
    )
    p = out["preview"]["1"]
    assert p["campaign_status"] == "ENABLED" and p["aviso_status"] is None


@pytest.mark.asyncio
async def test_irma_pausada_nao_conta_como_ativa_no_aviso(monkeypatch) -> None:
    irmas = [
        {
            "campaign_id": "1",
            "campaign_name": "A",
            "budget_resource_name": "customers/1234567890/campaignBudgets/77",
            "status": "ENABLED",
        },
        {
            "campaign_id": "2",
            "campaign_name": "B",
            "budget_resource_name": "customers/1234567890/campaignBudgets/77",
            "status": "PAUSED",
        },
        {
            "campaign_id": "3",
            "campaign_name": "C",
            "budget_resource_name": "customers/1234567890/campaignBudgets/77",
            "status": "ENABLED",
        },
    ]
    _wire(monkeypatch, grade=[], orcamentos=[_orc(shared=True)], metricas=[], irmas=irmas)
    out = await mod.update_ad_schedule(
        {"customer_id": "1234567890", "campaign_ids": ["1"], "windows": SEG_SEX}
    )
    sb = out["shared_budgets"][0]
    assert sb["ativas_fora_do_lote"] == 1
    assert {(c["campaign_id"], c["status"]) for c in sb["campaigns_outside_batch"]} == {
        ("2", "PAUSED"),
        ("3", "ENABLED"),
    }


@pytest.mark.asyncio
async def test_periodo_invalido_vira_error_envelope(monkeypatch) -> None:
    _wire(monkeypatch, grade=[], orcamentos=[_orc()], metricas=[])
    out = await mod.update_ad_schedule(
        {
            "customer_id": "1234567890",
            "campaign_ids": ["1"],
            "windows": SEG_SEX,
            "start_date": "2026-08-01",
        }
    )
    assert out["status"] == "error" and "periodo" in out["error_message"].lower()
