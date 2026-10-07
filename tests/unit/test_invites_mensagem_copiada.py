"""A mensagem de onboarding copiada pelo botão chega inteira ao clipboard.

O botão "Copiar mensagem" de /admin/invites copia `data-v4-copy-text`. A
mensagem era montada num `{% set %}` em bloco, que sob autoescape vira
`Markup` e não é re-escapada no atributo: a `"` de `(botão "Entrar com
Google V4")` fechava o atributo e o gestor recebia o texto cortado ali
(07/10, convite do Luiz Felipe).

O teste lê o atributo como o browser lê — via parser de HTML, depois de
desfeito o escape — e compara com a mensagem inteira. Asserir só que
`/login` aparece no HTML (o que o teste de integração fazia) passa com a
mensagem cortada.
"""

from datetime import UTC, datetime
from html.parser import HTMLParser

import pytest
from jinja2 import ChoiceLoader, DictLoader

from src.web.routes._shared import templates
from src.web.routes.admin_invites import mensagem_onboarding

PANEL_URL = "https://painel.exemplo"


class _CopyTexts(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.valores: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for nome, valor in attrs:
            if nome == "data-v4-copy-text":
                self.valores.append(valor or "")


def _copiado(full_name: str | None) -> str:
    # O env real do painel (mesmo autoescape de produção); só o _base.html é
    # trocado, porque ele pede request/sessão e não está em jogo aqui.
    env = templates.env.overlay(
        loader=ChoiceLoader(
            [
                DictLoader({"_base.html": "{% block content %}{% endblock %}"}),
                templates.env.loader,  # type: ignore[list-item]
            ]
        )
    )
    invite = {
        "id": "00000000-0000-0000-0000-000000000001",
        "email": "convidado@v4company.com",
        "full_name": full_name,
        "invited_by_email": "admin@v4company.com",
        "invited_at": datetime(2026, 10, 7, 23, 14, tzinfo=UTC),
        "days_pending": 0,
        "onboarding_message": mensagem_onboarding(full_name, PANEL_URL),
    }
    html = env.get_template("admin/invites.html").render(invites=[invite], flash=None)
    parser = _CopyTexts()
    parser.feed(html)
    assert len(parser.valores) == 1
    return parser.valores[0]


@pytest.mark.parametrize(
    "full_name",
    ["Luiz Felipe", None, "Ana D'Ávila", 'Zé "Tráfego" & Cia <b>'],
)
def test_botao_copia_a_mensagem_inteira(full_name: str | None) -> None:
    assert _copiado(full_name) == mensagem_onboarding(full_name, PANEL_URL)


def test_mensagem_tem_os_dois_passos_e_o_fecho() -> None:
    msg = mensagem_onboarding("Luiz Felipe", PANEL_URL)
    assert msg.startswith("Oi Luiz! ")
    assert (
        f'{PANEL_URL}/login e entra com seu email @v4company.com (botão "Entrar com Google V4").'
        in msg
    )
    assert f"{PANEL_URL}/help" in msg
    assert msg.endswith("Qualquer coisa me chama.")


@pytest.mark.parametrize("full_name", [None, "", "   "])
def test_sem_nome_saudacao_sem_espaco_sobrando(full_name: str | None) -> None:
    assert mensagem_onboarding(full_name, PANEL_URL).startswith("Oi! Te convidei")
