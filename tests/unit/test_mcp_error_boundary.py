"""Boundary de erro do dispatcher MCP: exceções viram envelope seguro (sem vazar internals)."""

from src.google_ads.access import AccountAccessDeniedError
from src.google_ads.errors import GoogleAdsFriendlyError
from src.governance.rate_limit import QuotaExhausted
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
