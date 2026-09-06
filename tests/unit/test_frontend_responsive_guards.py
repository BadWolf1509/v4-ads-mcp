"""Guards de responsividade do painel (grep-based).

Motivados pela revisao de 2026-08-20, que rodou as 24 telas em 320/375/414/
640/768/900/1024px medindo `scrollWidth x clientWidth`. Nove telas rolavam na
horizontal em 375px (a pior, /admin/audit, com +751px) e o header estourava
todas elas em 768px. Cada guard abaixo cita o que foi MEDIDO, nao o que parecia
provavel — e deriva a lista de alvos do proprio source, porque guard que lista
pagina a mao foi o que deixou /admin/audit de fora no F79.

Espelha o padrao de test_frontend_a11y_guards.py.
"""

import re
from pathlib import Path

import pytest

from tests.unit import _guard_harness as h

_ROOT = Path(__file__).resolve().parents[2]
_STATIC = _ROOT / "src" / "web" / "static"
_TEMPLATES = _ROOT / "src" / "web" / "templates"

# Classes que abrem um contentor de scroll horizontal para tabela.
_MARCADORES_SCROLL = ("v4-table-wrap", "overflow-x-auto")


def _templates() -> list[Path]:
    return h.templates_html()


def _mascara_comentarios(texto: str) -> str:
    """Apaga o CONTEUDO de comentarios Jinja/HTML preservando as quebras.

    O comentario que explica um fix cita, por necessidade, o padrao que o guard
    proibe — e ai o guard casa a propria prosa. Ja aconteceu 4x neste repo (do
    F87 ao F116); aqui o `<main id="conteudo">` citado no comentario do
    help.html derrubou este proprio teste na primeira execucao. Mascarar em vez
    de remover mantem a numeracao de linha das mensagens de erro.
    """
    return re.sub(
        r"\{#.*?#\}|<!--.*?-->",
        lambda m: "".join("\n" if c == "\n" else " " for c in m.group(0)),
        texto,
        flags=re.DOTALL,
    )


def _linhas(caminho: Path) -> list[str]:
    return _mascara_comentarios(caminho.read_text(encoding="utf-8")).splitlines()


def test_toda_tabela_vive_num_contentor_de_scroll():
    """Tabela larga sem contentor rola a PAGINA inteira, nao a si mesma.

    Medido em 375px: /admin/audit +751px, /admin/managers +545px, /accounts
    +275px. Com a pagina rolando na horizontal o header sticky sai de baixo do
    conteudo e o layout inteiro desalinha. As duas primeiras estavam fora do
    padrao de proposito (sticky-head e dropdown); a solucao foi manter o
    contentor e resolver cada conflito na sua camada, nao abrir excecao.
    """
    faltando = []
    for template in _templates():
        linhas = _linhas(template)
        for i, linha in enumerate(linhas):
            if "<table" not in linha:
                continue
            janela = "\n".join(linhas[max(0, i - 3) : i + 1])
            if not any(m in janela for m in _MARCADORES_SCROLL):
                faltando.append(f"{template.relative_to(_TEMPLATES)}:{i + 1}")
    assert not faltando, (
        "tabela sem contentor de scroll (rola a pagina inteira no celular): " + ", ".join(faltando)
    )


def test_contentor_de_scroll_e_alcancavel_por_teclado():
    """Scroller nao-focavel prende as colunas cortadas fora do teclado.

    Chrome 127+ tornou scroller focavel por default; Firefox e Safari nao. Sem
    tabindex o usuario de teclado nao alcanca as colunas escondidas (WCAG
    2.1.1). Padrao: role=region + aria-label + tabindex=0.

    A lista sai do proprio source: qualquer div nova que abra scroll de tabela
    cai aqui sem ninguem lembrar de atualizar o teste.
    """
    incompletos = []
    for template in _templates():
        for i, linha in enumerate(_linhas(template)):
            if "<div" not in linha:
                continue
            if not any(m in linha for m in _MARCADORES_SCROLL):
                continue
            falta = [
                atributo
                for atributo in ('tabindex="0"', 'role="region"', "aria-label=")
                if atributo not in linha
            ]
            if falta:
                incompletos.append(
                    f"{template.relative_to(_TEMPLATES)}:{i + 1} falta {' '.join(falta)}"
                )
    assert not incompletos, "contentor de scroll sem afordancia de teclado: " + "; ".join(
        incompletos
    )


def test_sparkline_nao_estoura_o_container():
    """O Preflight do Tailwind da `max-width:100%` a img e video — nao a svg.

    /admin renderiza sparkline(width=600) e media 669px de scrollWidth num
    viewport de 375. Com max-width o viewBox reescala pra 222px.
    """
    css = (_STATIC / "v4-components.css").read_text(encoding="utf-8")
    bloco = re.search(r"\.v4-sparkline\s*\{[^}]*\}", css)
    assert bloco, ".v4-sparkline sumiu do design system"
    assert "max-width: 100%" in bloco.group(0), (
        ".v4-sparkline precisa de max-width:100% — svg nao herda o reset de img"
    )


def test_layout_de_pagina_nao_vaza_para_main_aninhado():
    """`main { margin: 0 auto }` desligava o stretch do flex no /help.

    Margem auto no eixo cruzado cancela o stretch, entao o <main> aninhado
    virava fit-content do bloco de codigo (586px) e estourava a pagina em
    295px. Escopar a regra ao main de topo mata a classe inteira; a template
    tambem para de emitir dois landmarks `main`.
    """
    css = (_STATIC / "v4-base.css").read_text(encoding="utf-8")
    assert not re.search(r"(?m)^main\s*\{", css), (
        "regra de layout no seletor de elemento `main` vaza pra qualquer <main> "
        "aninhado; escope (ex.: `body > main`)"
    )

    aninhados = [
        f"{t.relative_to(_TEMPLATES)}"
        for t in _templates()
        if t.name != "_base.html" and "<main" in _mascara_comentarios(t.read_text(encoding="utf-8"))
    ]
    assert not aninhados, (
        "so _base.html pode abrir <main> (landmark unico por documento): " + ", ".join(aninhados)
    )


def test_header_nao_estoura_entre_768_e_800():
    """Em 768px o modo mobile desliga e o header desktop precisa de ~800px.

    Medido com admin (6 itens de nav) + email de 33 chars: estoura de 768 a
    799px — exatamente o iPad em retrato. Truncar o email e o unico dos tres
    fixes testados que NAO muda a altura do header, e os offsets sticky do F79
    estao calibrados em 65/61px.
    """
    css = (_STATIC / "v4-base.css").read_text(encoding="utf-8")
    bloco = re.search(r"\.v4-header__user\s*\{[^}]*\}", css)
    assert bloco, ".v4-header__user sumiu"
    assert "min-width: 0" in bloco.group(0), (
        "sem min-width:0 o item flex nao encolhe abaixo do min-content e empurra "
        "o header pra fora da tela"
    )
    assert "text-overflow: ellipsis" in css, "o email do gestor precisa truncar"


def test_dropdown_escapa_do_contentor_de_scroll():
    """`overflow-x:auto` forca `overflow-y:auto`, e o menu absoluto era clipado.

    Medido em /admin/managers a 375px: menu em left=711/right=891 dentro de um
    scroller que termina em 320 — invisivel. Reposicionado por CSSOM (permitido
    sob a CSP; so `style=` em atributo e bloqueado) cai em 187..367, dentro da
    tela. Sem isso, envolver a tabela tiraria do admin a acao de promover ou
    desativar gestor no celular.
    """
    js = (_STATIC / "v4-panel.js").read_text(encoding="utf-8")
    css = (_STATIC / "v4-components.css").read_text(encoding="utf-8")
    assert "is-detached" in js, "v4DropdownToggle precisa destacar o menu no scroller"
    assert ".v4-dropdown__menu.is-detached" in css, (
        "a classe que troca o menu pra position:fixed sumiu do design system"
    )
    assert "position: fixed" in re.search(
        r"\.v4-dropdown__menu\.is-detached\s*\{[^}]*\}", css
    ).group(0)


@pytest.mark.parametrize(
    "caminho",
    [
        "audit_detail.html",
        "admin/access_manager_detail.html",
        "admin/access_manager_detail_meta.html",
        "admin/access_by_manager.html",
        "admin/access_by_manager_meta.html",
    ],
)
def test_email_longo_quebra_em_vez_de_estourar(caminho: str):
    """Email de gestor V4 (~33 chars) e uma palavra so, sem ponto de quebra.

    Medido: /audit/<id> +164px, /admin/access/<id> +96px, by-manager +66px em
    375px. Em contexto flex/grid a quebra sozinha nao basta — o min-content
    continua ditando a largura da faixa —, dai o minmax(0,...)/min-w-0 junto.
    """
    html = (_TEMPLATES / caminho).read_text(encoding="utf-8")
    assert "break-words" in html or "[overflow-wrap:anywhere]" in html, (
        f"{caminho}: email/identificador longo precisa de quebra explicita"
    )
