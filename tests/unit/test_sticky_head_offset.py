"""F97: `v4-table--sticky-head` grudava em `top: 0` sob ~208px de chrome opaco.

A regra vive no design system e seu UNICO consumidor e `/admin/audit` —
justamente a pagina com a pilha sticky mais profunda: header (65) + subnav
admin (55) + barra de filtros (88+, que embrulha). Todos opacos e em
`z-index: 10`; o cabecalho de colunas fica em `z-index: 1`. Ao rolar, o
cabecalho encostava em 0 e sumia atras do chrome — sticky que nao gruda em
lugar nenhum visivel.

E a classe **F79** sobrevivendo: o pacote de 08-11 mediu e corrigiu os offsets
nas TEMPLATES, mas nao alcancou este, que estava na regra CSS. Licao: ao varrer
uma classe de bug, varra tambem o design system, nao so os call-sites.
"""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_STATIC = _ROOT / "src" / "web" / "static"
_TEMPLATES = _ROOT / "src" / "web" / "templates"


def _corpo_da_regra(css: str, seletor: str) -> str:
    """Devolve o bloco `{...}` do seletor — sem depender da formatacao."""
    match = re.search(re.escape(seletor) + r"\s*\{([^}]*)\}", css)
    assert match is not None, f"seletor `{seletor}` sumiu do design system"
    return match.group(1)


def test_sticky_head_nao_gruda_no_topo_da_janela() -> None:
    """F97: `top: 0` so seria correto numa pagina sem chrome sticky nenhum."""
    css = (_STATIC / "v4-components.css").read_text(encoding="utf-8")
    corpo = _corpo_da_regra(css, ".v4-table--sticky-head thead th")

    top = re.search(r"top:\s*([^;]+);", corpo)
    assert top is not None, "a regra perdeu o `top` — sticky sem offset nao gruda"
    assert "--v4-sticky-head-offset" in top.group(1), (
        "o offset tem que ser variavel: a mesma regra serve paginas com pilhas "
        f"de chrome diferentes. Hoje: top:{top.group(1).strip()}"
    )


def test_admin_audit_declara_o_offset_da_sua_pilha() -> None:
    """F97: header + subnav + barra de filtros — os tres empilhados e opacos."""
    css = (_STATIC / "v4-components.css").read_text(encoding="utf-8")
    assert "--v4-sticky-head-offset" in css, "nenhum modificador define o offset"

    html = (_TEMPLATES / "admin" / "audit.html").read_text(encoding="utf-8")
    tabela = re.search(r'<table class="([^"]*v4-table--sticky-head[^"]*)"', html)
    assert tabela is not None, "a tabela sticky sumiu de /admin/audit"
    assert "v4-table--sticky-head-under-filters" in tabela.group(1), (
        "a unica consumidora da regra nao declara sob qual chrome ela vive"
    )


def test_barra_de_filtros_do_admin_audit_e_medida() -> None:
    """F97: sem a medicao, o offset usa um fallback aferido em OUTRA barra.

    `--v4-filter-bar-h: 88px` foi medido na barra de `/audit` (flex-wrap). A de
    `/admin/audit` e um grid de 5 colunas com altura propria, e embrulha em
    larguras diferentes. Sem `data-sticky-measure` aqui, o cabecalho gruda no
    lugar errado em toda janela que nao bate com o literal — que foi exatamente
    o modo de falha do F79.
    """
    html = (_TEMPLATES / "admin" / "audit.html").read_text(encoding="utf-8")
    assert "data-sticky-measure" in html, (
        "a barra de filtros de /admin/audit precisa ser medida em runtime"
    )
