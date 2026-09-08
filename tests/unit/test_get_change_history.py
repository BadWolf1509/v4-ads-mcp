"""Unit tests for the get_change_history MCP tool's pure logic.

The output-formatting + summary aggregation pieces are testable without
SDK or DB. Full I/O integration is covered in tests/integration/.
"""

from uuid import uuid4

import pytest
from jsonschema import ValidationError, validate


@pytest.fixture(autouse=True)
def _ctx():
    from src.mcp.context import McpRequestContext, clear_current, set_current

    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    yield
    clear_current()


def test_schema_accepts_minimal():
    from src.mcp.tools.get_change_history import _SCHEMA

    validate({"customer_id": "1234567890"}, _SCHEMA)


def test_schema_accepts_full():
    from src.mcp.tools.get_change_history import _SCHEMA

    validate(
        {
            "customer_id": "1234567890",
            "date_range": "LAST_7_DAYS",
            "resource_types": ["CAMPAIGN", "AD_GROUP"],
            "operation_types": ["UPDATE"],
            "user_emails": ["fulano@v4company.com"],
            "client_types": ["GOOGLE_ADS_WEB_CLIENT"],
            "limit": 500,
        },
        _SCHEMA,
    )


def test_schema_rejects_unknown_resource_type():
    from src.mcp.tools.get_change_history import _SCHEMA

    with pytest.raises(ValidationError):
        validate(
            {"customer_id": "1234567890", "resource_types": ["GALAXY"]},
            _SCHEMA,
        )


def test_schema_rejects_unknown_client_type():
    from src.mcp.tools.get_change_history import _SCHEMA

    with pytest.raises(ValidationError):
        validate(
            {"customer_id": "1234567890", "client_types": ["MARS_ROVER"]},
            _SCHEMA,
        )


def test_summary_aggregation_with_mixed_events():
    """Given 8 mock rows (3 auto-apply, 5 manual), summary must aggregate correctly."""
    from src.mcp.tools.get_change_history import _build_summary

    rows = [
        {
            "user_email": "fulano@v4company.com",
            "client_type": "GOOGLE_ADS_WEB_CLIENT",
            "resource_type": "CAMPAIGN",
            "operation": "UPDATE",
        },
        {
            "user_email": "fulano@v4company.com",
            "client_type": "GOOGLE_ADS_WEB_CLIENT",
            "resource_type": "AD_GROUP_CRITERION",
            "operation": "UPDATE",
        },
        {
            "user_email": "fulano@v4company.com",
            "client_type": "GOOGLE_ADS_WEB_CLIENT",
            "resource_type": "AD_GROUP_CRITERION",
            "operation": "CREATE",
        },
        {
            "user_email": "ana@v4company.com",
            "client_type": "GOOGLE_ADS_WEB_CLIENT",
            "resource_type": "BIDDING_STRATEGY",
            "operation": "UPDATE",
        },
        {
            "user_email": "ana@v4company.com",
            "client_type": "GOOGLE_ADS_WEB_CLIENT",
            "resource_type": "CAMPAIGN",
            "operation": "REMOVE",
        },
        {
            "user_email": "google-ads-svc@google.com",
            "client_type": "GOOGLE_ADS_RECOMMENDATIONS",
            "resource_type": "CAMPAIGN",
            "operation": "UPDATE",
        },
        {
            "user_email": "google-ads-svc@google.com",
            "client_type": "GOOGLE_ADS_RECOMMENDATIONS",
            "resource_type": "AD_GROUP",
            "operation": "UPDATE",
        },
        {
            "user_email": "google-ads-svc@google.com",
            "client_type": "GOOGLE_ADS_RECOMMENDATIONS",
            "resource_type": "AD_GROUP",
            "operation": "CREATE",
        },
    ]
    summary = _build_summary(rows)

    assert summary["total_changes"] == 8
    assert summary["by_user"] == {
        "fulano@v4company.com": 3,
        "ana@v4company.com": 2,
        "auto-apply": 3,  # auto-apply rows collapsed into synthetic bucket
    }
    assert summary["by_resource_type"] == {
        "CAMPAIGN": 3,
        "AD_GROUP_CRITERION": 2,
        "BIDDING_STRATEGY": 1,
        "AD_GROUP": 2,
    }
    assert summary["by_operation"] == {"UPDATE": 5, "CREATE": 2, "REMOVE": 1}
    assert summary["auto_applied_count"] == 3


def test_summary_empty_input():
    from src.mcp.tools.get_change_history import _build_summary

    summary = _build_summary([])
    assert summary == {
        "total_changes": 0,
        "by_user": {},
        "by_resource_type": {},
        "by_operation": {},
        "auto_applied_count": 0,
    }


@pytest.mark.asyncio
async def test_tool_returns_period_and_rows(monkeypatch):
    """Smoke: tool returns customer_id, period, rows, summary even with empty result."""
    from src.mcp.tools import get_change_history as mod

    async def fake_run_report(**kwargs):
        return []

    monkeypatch.setattr(mod, "run_report", fake_run_report)

    # _resolve_names is async — replace with an async stub returning empty dict
    async def fake_resolve_names(**kwargs):
        return {}

    monkeypatch.setattr(mod, "_resolve_names", fake_resolve_names)

    result = await mod.get_change_history(
        {"customer_id": "1234567890", "date_range": "LAST_7_DAYS"}
    )

    assert result["customer_id"] == "1234567890"
    assert "period" in result
    assert "rows" in result
    assert "summary" in result
    assert result["summary"]["total_changes"] == 0


@pytest.mark.asyncio
async def test_custom_old_start_date_clamped(monkeypatch):
    """Custom start_date > 30 dias é CLAMPADO (não rejeitado) + warning — preset OU custom.

    Antes do hardening, custom dates antigas erravam com "start date too old" do
    Google (visto na prática nas sessões Codex do Pedro). Agora clampa pro teto.
    """
    from datetime import UTC, datetime, timedelta
    from unittest.mock import AsyncMock

    from src.mcp.tools import get_change_history as mod
    from src.mcp.tools.get_change_history import _RETENTION_SAFETY_DAYS

    monkeypatch.setattr(mod, "run_report", AsyncMock(return_value=[]))
    monkeypatch.setattr(mod, "_resolve_names", AsyncMock(return_value={}))

    today = datetime.now(UTC).date()
    result = await mod.get_change_history(
        {
            "customer_id": "1234567890",
            "start_date": (today - timedelta(days=60)).isoformat(),
            "end_date": today.isoformat(),
        }
    )

    assert "date_range_warning" in result
    assert "coerced" in result["date_range_warning"]
    # start clampado pro teto de retenção (não mais o today-60 original)
    assert result["period"]["from"] == (today - timedelta(days=_RETENTION_SAFETY_DAYS)).isoformat()


@pytest.mark.asyncio
async def test_custom_window_entirely_outside_retention_errors(monkeypatch):
    """Janela custom inteiramente > 30 dias atrás → ValueError claro (sem dado a retornar)."""
    from datetime import UTC, datetime, timedelta
    from unittest.mock import AsyncMock

    from src.mcp.tools import get_change_history as mod

    monkeypatch.setattr(mod, "run_report", AsyncMock(return_value=[]))
    monkeypatch.setattr(mod, "_resolve_names", AsyncMock(return_value={}))

    today = datetime.now(UTC).date()
    with pytest.raises(ValueError, match="retenção"):
        await mod.get_change_history(
            {
                "customer_id": "1234567890",
                "start_date": (today - timedelta(days=90)).isoformat(),
                "end_date": (today - timedelta(days=60)).isoformat(),
            }
        )


@pytest.mark.asyncio
async def test_f23_last_30_days_clamped_with_warning(monkeypatch):
    """F23 fix Sprint 3b.38: LAST_30_DAYS preset resolves to yesterday-29 = today-30,
    bate na borda exclusiva do Google API (start_date deve ser > today-30).

    Tool clampa start_date pra today-28 (margem 2-day) + adiciona
    `date_range_warning` explicativo na response. Non-breaking change —
    existing consumers podem ignorar o field novo.

    Dogfood 2026-05-25 MO-JP descobriu: LAST_30_DAYS resultava em "The
    requested start date is too old" mesmo com preset disponível no schema.
    """
    from src.mcp.tools import get_change_history as mod

    async def fake_run_report(**kwargs):
        return []

    monkeypatch.setattr(mod, "run_report", fake_run_report)

    async def fake_resolve_names(**kwargs):
        return {}

    monkeypatch.setattr(mod, "_resolve_names", fake_resolve_names)

    result = await mod.get_change_history(
        {"customer_id": "1234567890", "date_range": "LAST_30_DAYS"}
    )

    # Clamp aplicado: warning presente
    assert "date_range_warning" in result
    assert "F23" in result["date_range_warning"]
    assert "coerced" in result["date_range_warning"]
    # Period reflete data pós-clamp
    assert "period" in result


@pytest.mark.asyncio
async def test_f23_no_warning_when_within_retention_window(monkeypatch):
    """F23 fix Sprint 3b.38: window dentro da retention (LAST_7_DAYS) não dispara
    o clamp — `date_range_warning` ausente na response.

    Negative test pra evitar regressão (warning persistente em todos os calls).
    """
    from src.mcp.tools import get_change_history as mod

    async def fake_run_report(**kwargs):
        return []

    monkeypatch.setattr(mod, "run_report", fake_run_report)

    async def fake_resolve_names(**kwargs):
        return {}

    monkeypatch.setattr(mod, "_resolve_names", fake_resolve_names)

    result = await mod.get_change_history(
        {"customer_id": "1234567890", "date_range": "LAST_7_DAYS"}
    )

    # Sem clamp: warning ausente
    assert "date_range_warning" not in result
    assert "period" in result
    assert result["summary"]["total_changes"] == 0


# ---------------------------------------------------------------------------
# O cap DURO do change_event (10k) contra o contrato publico do schema.
#
# Medido em 2026-09-07 via `validate_gaql` na 786-223-0676: `LIMIT 10001` em
# `FROM change_event` volta "Change event requests must specify a LIMIT less
# than or equal to 10k", `LIMIT 10000` passa, e `FROM campaign ... LIMIT 10001`
# passa — o cap e DESTE recurso, nao da GAQL.
#
# A saida NAO e estreitar `maximum` pra 9999: `src/mcp/server.py` valida o
# schema server-side e, por F140, a sessao ja aberta continua com o catalogo
# antigo em maos — o gestor pediria o maximo que o schema DELE anuncia e
# levaria erro duro de validacao. Acrescentar campo e aditivo; estreitar
# dominio de entrada nao e. O idioma e `fetch n+1` com teto de API: pedir
# `min(limit + 1, CAP)` e ler `len == CAP` como corte na borda.
# ---------------------------------------------------------------------------

_CONTA = "1234567890"


def _linha_de_mudanca(i: int) -> dict:
    """`campaign_id`/`ad_group_id` None: `_resolve_names` nao consulta nada."""
    return {
        "change_date_time": "2026-09-05 10:00:00",
        "user_email": "fulano@v4company.com",
        "client_type": "GOOGLE_ADS_WEB_CLIENT",
        "resource_type": "CAMPAIGN",
        "resource_id": str(i),
        "resource_name": "",
        "_resource_path": f"customers/{_CONTA}/campaigns/{i}",
        "operation": "UPDATE",
        "changed_fields": [],
        "campaign_id": None,
        "ad_group_id": None,
        "old_status": None,
        "new_status": None,
    }


def _mock_run_report(monkeypatch, linhas: list[dict], capturadas: list[str]) -> None:
    from src.mcp.tools import get_change_history as mod

    async def fake_run_report(**kwargs):
        capturadas.append(kwargs["query"])
        if kwargs["operation_name"] == "get_change_history":
            return linhas
        return []  # a sonda de fronteira

    monkeypatch.setattr(mod, "run_report", fake_run_report)


def test_limit_maximo_do_schema_continua_10000():
    """F140: `maximum` e contrato publico ja negociado no handshake.

    Estreitar pra 9999 nao chega na sessao aberta — ela segue anunciando
    10000 e passa a receber erro duro de validacao onde antes funcionava. O
    cap da API se resolve DENTRO da tool, nao no dominio de entrada.
    """
    from src.mcp.tools.get_change_history import _SCHEMA

    assert _SCHEMA["properties"]["limit"]["maximum"] == 10000
    validate({"customer_id": _CONTA, "limit": 10000}, _SCHEMA)


@pytest.mark.asyncio
async def test_no_teto_a_query_nao_ultrapassa_o_cap_do_change_event(monkeypatch):
    """`limit: 10000` + sentinela daria `LIMIT 10001`, que o Google RECUSA.

    O pedido e `min(limit + 1, CAP)` — no teto, exatamente o cap.
    """
    from src.mcp.tools import get_change_history as mod

    capturadas: list[str] = []
    _mock_run_report(monkeypatch, [], capturadas)

    await mod.get_change_history({"customer_id": _CONTA, "limit": 10000})

    principal = capturadas[0]
    assert "LIMIT 10000" in principal
    assert "LIMIT 10001" not in principal


@pytest.mark.asyncio
async def test_abaixo_do_teto_a_sentinela_continua_sendo_pedida(monkeypatch):
    """O cap so morde no teto: com `limit` folgado, `limit + 1` inteiro.

    Sem esta metade, um `min` escrito errado (que pedisse sempre o cap, ou
    sempre `limit`) passaria no teste de cima.
    """
    from src.mcp.tools import get_change_history as mod

    capturadas: list[str] = []
    _mock_run_report(monkeypatch, [], capturadas)

    await mod.get_change_history({"customer_id": _CONTA, "limit": 200})

    assert "LIMIT 201" in capturadas[0]


@pytest.mark.asyncio
async def test_no_teto_o_cap_do_google_e_lido_como_corte(monkeypatch):
    """A borda que o `min` cria: no teto nao ha sentinela para comparar.

    Com `limit == CAP`, `len(linhas) > limit` e falso por construcao — e um
    `truncated: false` ali seria a mentira exata que este PR existe pra
    matar. `len(linhas) == CAP` fecha o buraco, degradando na direcao segura
    (num universo de exatamente 10000 mudancas, avisa corte que nao houve).
    """
    from src.mcp.tools import get_change_history as mod

    linhas = [_linha_de_mudanca(i) for i in range(10_000)]
    _mock_run_report(monkeypatch, linhas, [])

    fora = await mod.get_change_history({"customer_id": _CONTA, "limit": 10000})

    assert fora["truncated"] is True
    assert len(fora["rows"]) == 10_000
    assert fora["summary"]["total_changes"] == 10_000
