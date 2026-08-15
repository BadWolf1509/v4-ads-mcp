"""F96: `/accounts/{id}/revoke` era o unico endpoint HTMX que devolvia 303 cru.

O XHR do htmx **segue** o redirect, entao o handler respondia com o documento
`/accounts` inteiro; a template compensava mandando injetar isso em
`body.innerHTML` e so entao dando `location.reload()`. Funciona porque o reload
mascara — ao custo de 2 round-trips, um flash de pagina aninhada, e a
compensacao morando na template em vez do handler.

E a classe do 2o pacote de 07-04 (303 cru em `hx-post`), instancia remanescente:
os outros 6 endpoints acionados por HTMX ja respondem `204`+`HX-Refresh`/
`HX-Redirect` ou fragmento.

O guard abaixo e generico de proposito — a assinatura do problema e "swap no
`body`", que nunca e legitimo: se o htmx precisa trocar o documento inteiro, o
handler e que deveria ter mandado o browser navegar.
"""

from __future__ import annotations

import re
from pathlib import Path

_TEMPLATES = Path(__file__).resolve().parents[2] / "src" / "web" / "templates"


def test_nenhuma_template_faz_swap_no_body() -> None:
    """F96: trocar `body.innerHTML` via htmx e sempre compensacao de handler."""
    ofensores: list[str] = []
    for tpl in _TEMPLATES.rglob("*.html"):
        texto = tpl.read_text(encoding="utf-8")
        for atributo in ('data-v4-target="body"', 'hx-target="body"'):
            if atributo in texto:
                ofensores.append(f"{tpl.relative_to(_TEMPLATES)} — {atributo}")
    assert not ofensores, (
        "swap no <body> inteiro indica handler devolvendo pagina em vez de "
        "204+HX-Refresh/HX-Redirect: " + "; ".join(ofensores)
    )


def test_revoke_de_conexao_nao_carrega_compensacao() -> None:
    """F96: o botao tem que ficar igual ao de `/sessions` — so o `data-v4-post`."""
    html = (_TEMPLATES / "accounts.html").read_text(encoding="utf-8")
    botao = re.search(r"<button[^>]*data-v4-post=\"/accounts/[^\"]*revoke\"[^>]*>", html)
    assert botao is not None, "botao de revoke sumiu da template — teste desatualizado"
    marcado = botao.group(0)
    for compensacao in ("data-v4-reload", "data-v4-swap", "data-v4-target"):
        assert compensacao not in marcado, (
            f"`{compensacao}` sobrou no botao de revoke: a compensacao pertence "
            "ao handler (204 + HX-Refresh), nao a template"
        )
