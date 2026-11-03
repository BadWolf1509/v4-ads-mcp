"""Boundary de erro do dispatcher MCP: exceções viram envelope seguro (sem vazar internals)."""

from datetime import date, timedelta
from uuid import uuid4

import pytest

from src.google_ads.access import AccountAccessDeniedError
from src.google_ads.change_scan import consultar_change_history
from src.google_ads.errors import GoogleAdsFriendlyError
from src.google_ads.queries._common import EntradaInvalidaError
from src.governance.rate_limit import QuotaExhausted
from src.mcp.context import McpRequestContext, clear_current, set_current
from src.mcp.server import _error_envelope
from src.meta_ads.client import MetaAccessDeniedError


def test_generic_exception_is_scrubbed() -> None:
    env = _error_envelope("get_campaign_performance", KeyError("internal_secret_xyz"))
    assert env["status"] == "error"
    assert "internal_secret_xyz" not in env["error_message"]
    assert env["error_message"] == "Erro interno ao executar a ferramenta. O time foi notificado."


def test_account_denied_preserves_ptbr_message() -> None:
    env = _error_envelope("x", AccountAccessDeniedError("Você não tem acesso à conta 1234567890."))
    assert env["status"] == "denied"
    assert "1234567890" in env["error_message"]


def test_meta_denied_is_denied_status() -> None:
    env = _error_envelope("x", MetaAccessDeniedError("Você não tem acesso à conta act_123."))
    assert env["status"] == "denied"
    assert "act_123" in env["error_message"]


def test_google_friendly_error_preserved() -> None:
    env = _error_envelope("x", GoogleAdsFriendlyError("Quota diária esgotada, aguarde."))
    assert env["status"] == "error"
    assert env["error_message"] == "Quota diária esgotada, aguarde."


def test_quota_exhausted_preserved() -> None:
    env = _error_envelope("x", QuotaExhausted("limite diário atingido"))
    assert env["status"] == "error"
    assert "limite diário atingido" in env["error_message"]


_INTERNO = "Erro interno ao executar a ferramenta. O time foi notificado."


def test_entrada_invalida_repassa_mensagem() -> None:
    env = _error_envelope("x", EntradaInvalidaError("janela fora"))
    assert env == {"status": "error", "error_message": "janela fora"}


def test_value_error_cru_segue_escondido() -> None:
    env = _error_envelope("x", ValueError("SELECT ... internals"))
    assert env["error_message"] == _INTERNO


@pytest.mark.asyncio
async def test_change_history_janela_inteira_fora_da_retencao() -> None:
    hoje = date(2026, 11, 3)
    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    try:
        with pytest.raises(EntradaInvalidaError) as info:
            await consultar_change_history(
                {
                    "customer_id": "1234567890",
                    "start_date": (hoje - timedelta(days=60)).isoformat(),
                    "end_date": (hoje - timedelta(days=40)).isoformat(),
                },
                today=hoje,
                manager_id=uuid4(),
                session_id=uuid4(),
            )
    finally:
        clear_current()
    assert type(info.value) is EntradaInvalidaError


@pytest.mark.asyncio
async def test_run_gaql_agregacao_com_rows_demais_chega_ao_gestor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.mcp.tools.run_gaql as run_gaql

    async def _rows_demais(**_kw: object) -> list[dict[str, object]]:
        return [{"campaign.id": 1}] * (run_gaql._MAX_RAW_ROWS_FOR_AGGREGATE + 1)

    monkeypatch.setattr(run_gaql, "execute_gaql_raw", _rows_demais)
    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    try:
        with pytest.raises(EntradaInvalidaError) as info:
            await run_gaql.run_gaql(
                {
                    "customer_id": "1234567890",
                    "query": "SELECT campaign.id FROM campaign",
                    "aggregate_by": ["campaign.id"],
                }
            )
    finally:
        clear_current()
    assert type(info.value) is EntradaInvalidaError
