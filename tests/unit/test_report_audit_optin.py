"""Os 8 reports consolidados pela 2A devem passar audit_this_call=True (gate da Fase 2B)."""

import importlib
from datetime import date
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from src.db import connection
from src.db.repositories import audit_log
from src.google_ads.access import AccountAccessDeniedError
from src.mcp.tools import _common
from src.mcp.tools._registry import get_tool
from tests.unit.fixtures.fake_pool import FakePool, patch_pool

# (módulo do tool, nome registrado)
_REPORTS = [
    ("src.mcp.tools.get_campaign_performance", "get_campaign_performance"),
    ("src.mcp.tools.get_ad_group_performance", "get_ad_group_performance"),
    ("src.mcp.tools.get_ad_performance", "get_ad_performance"),
    ("src.mcp.tools.get_keyword_performance", "get_keyword_performance"),
    ("src.mcp.tools.get_audience_performance", "get_audience_performance"),
    ("src.mcp.tools.get_device_performance", "get_device_performance"),
    ("src.mcp.tools.get_geo_performance", "get_geo_performance"),
    ("src.mcp.tools.get_hourly_performance", "get_hourly_performance"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("module_path, tool_name", _REPORTS)
async def test_report_opts_into_audit(
    module_path: str, tool_name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    mod = importlib.import_module(module_path)

    ctx = MagicMock()
    ctx.manager_id = uuid4()
    ctx.session_id = uuid4()
    monkeypatch.setattr(mod, "get_current", lambda: ctx)

    captured: dict[str, Any] = {}

    async def _fake_run_report(**kwargs: Any) -> list[Any]:
        captured.update(kwargs)
        return []

    monkeypatch.setattr(mod, "run_report", _fake_run_report)

    tool = get_tool(tool_name)
    assert tool is not None
    await tool.handler({"customer_id": "1234567890", "date_range": "LAST_7_DAYS"})

    assert captured.get("audit_this_call") is True, f"{tool_name} não opta por audit_this_call"


# --- A-01 (P0, 15/11): as 6 leituras Google que não gravavam no sucesso ----------
#
# Cada uma grava UMA linha por chamada: o opt-in vai só na leitura principal. As
# secundárias (período anterior, gasto de hoje, criações de negativa, criativos)
# ficam sem, senão uma chamada viraria várias linhas e a medição de uso contaria
# chamada a mais. A linha que conta sai sob o nome da própria tool.

_HOJE = date(2026, 11, 15)

# (módulo, tool, args)
_LEITURAS_SEM_TRILHA_ATE_15_11 = [
    (
        "src.mcp.tools.get_account_overview",
        "get_account_overview",
        {"customer_id": "1234567890", "date_range": "LAST_7_DAYS"},
    ),
    ("src.mcp.tools.get_budget_pacing", "get_budget_pacing", {"customer_id": "1234567890"}),
    (
        "src.mcp.tools.get_funnel_metrics",
        "get_funnel_metrics",
        {"customer_id": "1234567890", "date_range": "LAST_7_DAYS"},
    ),
    (
        "src.mcp.tools.get_negative_keywords_audit",
        "get_negative_keywords_audit",
        {"customer_id": "1234567890"},
    ),
    (
        "src.mcp.tools.get_search_terms_report",
        "get_search_terms_report",
        {"customer_id": "1234567890", "date_range": "LAST_7_DAYS"},
    ),
    (
        "src.mcp.tools.get_top_keywords_creatives",
        "get_top_keywords_creatives",
        {"customer_id": "1234567890", "date_range": "LAST_7_DAYS"},
    ),
]

# Linha de campanha NÃO compartilhada: faz `get_budget_pacing` ler o gasto de
# hoje (`_gasto_por`), a leitura secundária que tem de ficar sem opt-in. O fake
# só a devolve para `get_budget_pacing`; as outras recebem lista vazia.
_LINHA_PACING = {
    "campaign_id": "111",
    "campaign_name": "Campanha",
    "daily_budget_brl": 10.0,
    "delivery_method": "STANDARD",
    "budget_id": "222",
    "budget_name": "Orçamento",
    "orcamento_compartilhado": False,
    "cost_micros": 5_000_000,
}


def _contexto_falso(mod: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = MagicMock()
    ctx.manager_id = uuid4()
    ctx.session_id = uuid4()
    monkeypatch.setattr(mod, "get_current", lambda: ctx)

    async def _hoje(_customer_id: str) -> date:
        return _HOJE

    # `janela_da_conta` resolve `hoje` em `_common`; as que não usam a janela
    # importam `resolve_account_today` direto.
    monkeypatch.setattr(_common, "resolve_account_today", _hoje)
    if hasattr(mod, "resolve_account_today"):
        monkeypatch.setattr(mod, "resolve_account_today", _hoje)


@pytest.mark.asyncio
@pytest.mark.parametrize(("module_path", "tool_name", "args"), _LEITURAS_SEM_TRILHA_ATE_15_11)
async def test_leitura_grava_uma_linha_por_chamada(
    module_path: str, tool_name: str, args: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    mod = importlib.import_module(module_path)
    _contexto_falso(mod, monkeypatch)

    chamadas: list[dict[str, Any]] = []

    async def _fake_run_report(**kwargs: Any) -> list[Any]:
        chamadas.append(kwargs)
        return [dict(_LINHA_PACING)] if tool_name == "get_budget_pacing" else []

    monkeypatch.setattr(mod, "run_report", _fake_run_report)

    tool = get_tool(tool_name)
    assert tool is not None
    await tool.handler(dict(args))

    auditadas = [c for c in chamadas if c.get("audit_this_call") is True]
    assert len(auditadas) == 1, (
        f"{tool_name}: {len(auditadas)} leituras com audit_this_call=True em "
        f"{len(chamadas)} chamadas (esperado: exatamente 1)"
    )
    assert auditadas[0]["operation_name"] == tool_name
    resto = [c for c in chamadas if c is not auditadas[0]]
    assert all(c.get("audit_this_call", False) is False for c in resto)
    if tool_name == "get_budget_pacing":
        # Controle: a leitura de hoje aconteceu de fato, e ficou sem opt-in.
        assert len(chamadas) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(("module_path", "tool_name", "args"), _LEITURAS_SEM_TRILHA_ATE_15_11)
async def test_negacao_grava_so_a_linha_do_gate(
    module_path: str, tool_name: str, args: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Com o `run_report` real, a negação do gate grava a linha `denied` e
    nada mais: o opt-in de audit não acrescenta linha de erro do executor,
    porque o gate levanta antes do `try` cujo `finally` audita."""
    from src.google_ads import reports

    mod = importlib.import_module(module_path)
    _contexto_falso(mod, monkeypatch)
    patch_pool(monkeypatch, FakePool(), "src.db.connection.get_pool")

    registros: list[dict[str, Any]] = []

    async def _fake_record(_conn: Any, **kwargs: Any) -> None:
        registros.append(kwargs)

    monkeypatch.setattr(audit_log, "record", _fake_record)

    gates: list[str] = []

    async def _gate_que_nega(conn: Any, **kwargs: Any) -> None:
        gates.append(kwargs["operation_name"])
        await audit_log.record(
            conn,
            manager_id=kwargs["manager_id"],
            session_id=kwargs["session_id"],
            customer_id=kwargs["customer_id"],
            action_type="read",
            operation=kwargs["operation_name"],
            target_count=None,
            params_summary=None,
            status="denied",
        )
        raise AccountAccessDeniedError("sem acesso")

    async def _com_conexao(op: Any, **_kw: Any) -> Any:
        return await op(MagicMock())

    monkeypatch.setattr(reports, "ensure_account_access", _gate_que_nega)
    monkeypatch.setattr(connection, "run_with_reconnect", _com_conexao)

    tool = get_tool(tool_name)
    assert tool is not None
    with pytest.raises(AccountAccessDeniedError):
        await tool.handler(dict(args))

    assert gates, "o gate não rodou: o teste não exercitou a negação"
    assert [r["status"] for r in registros] == ["denied"] * len(gates)
    # Leitura em série para na primeira negação; só a que dispara as duas
    # leituras em paralelo (`asyncio.gather`) chega a gatear duas vezes.
    esperado = 2 if tool_name == "get_negative_keywords_audit" else 1
    assert len(gates) == esperado
