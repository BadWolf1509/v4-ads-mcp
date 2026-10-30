"""O detalhe do audit traduz `denied` como a listagem: "⊘ Negado", nao o valor cru."""

from datetime import UTC, datetime
from types import SimpleNamespace

from jinja2 import ChoiceLoader, DictLoader

from src.web.routes._shared import templates


def _html(status: str) -> str:
    env = templates.env.overlay(
        loader=ChoiceLoader(
            [
                DictLoader({"_base.html": "{% block content %}{% endblock %}"}),
                templates.env.loader,  # type: ignore[list-item]
            ]
        )
    )
    event = SimpleNamespace(
        occurred_at=datetime(2026, 10, 30, 12, tzinfo=UTC),
        operation="update_campaign_status",
        status=status,
        manager_email="g@v4company.com",
        session_label=None,
        customer_id=None,
        account_name=None,
        action_type=None,
        target_count=None,
        duration_ms=None,
        provider_request_id=None,
        error_message=None,
        params_summary=None,
    )
    return env.get_template("audit_detail.html").render(
        event=event, current_user=SimpleNamespace(id="x", is_admin=False)
    )


def test_denied_vira_negado() -> None:
    html = _html("denied")
    assert "⊘ Negado" in html
    assert ">denied<" not in html


def test_ok_e_erro_seguem_iguais() -> None:
    assert "✓ OK" in _html("success")
    assert "✗ Erro" in _html("error")
