"""O menu do gestor só oferece o toggle que de fato muda o estado real.

F84: `is_active` e `status` divergem e nada os sincroniza. O badge segue
`Manager.is_deactivated`; a rota `toggle-active` só inverte `is_active`. Com
`status='inactive'` o toggle não muda nada, então o menu não pode oferecer
"Desativar" nem "Reativar" ali.
"""

import re
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from jinja2 import ChoiceLoader, DictLoader

from src.web.routes._shared import templates

MID = "00000000-0000-0000-0000-0000000000aa"


def _gestor(is_active: bool, status: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=MID,
        email="g@v4company.com",
        full_name="G",
        role="gestor",
        is_active=is_active,
        status=status,
        is_deactivated=(not is_active) or status == "inactive",
        created_at=datetime(2026, 10, 1, tzinfo=UTC),
        last_seen_at=None,
    )


def _html(m: SimpleNamespace) -> str:
    env = templates.env.overlay(
        loader=ChoiceLoader(
            [
                DictLoader({"_base.html": "{% block content %}{% endblock %}"}),
                templates.env.loader,  # type: ignore[list-item]
            ]
        )
    )
    return env.get_template("admin/managers.html").render(
        managers=[m], current_user=SimpleNamespace(id="outro"), flash=None
    )


def _toggle_buttons(html: str) -> list[str]:
    return re.findall(r"<button[^>]*toggle-active[^>]*>[^<]*</button>", html)


@pytest.mark.parametrize(
    ("is_active", "status", "label"),
    [(True, "active", "Desativar"), (True, "invited", "Desativar"), (False, "active", "Reativar")],
)
def test_toggle_oferecido_quando_muda_o_estado(is_active: bool, status: str, label: str) -> None:
    botoes = _toggle_buttons(_html(_gestor(is_active, status)))
    assert len(botoes) == 1
    assert botoes[0].rstrip().endswith(f">{label}</button>")
    assert ("data-v4-confirm-title" in botoes[0]) == (label == "Desativar")


@pytest.mark.parametrize("is_active", [True, False])
def test_status_inactive_nao_oferece_toggle(is_active: bool) -> None:
    html = _html(_gestor(is_active, "inactive"))
    assert _toggle_buttons(html) == []
    assert "toggle-active" not in html
    assert "Desativar —" not in html
    item = re.search(
        r'<[^>]*role="menuitem"[^>]*aria-disabled="true"[^>]*>[^<]*Inativo por status', html
    )
    assert item is not None
