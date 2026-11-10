"""Meta nao depende de Google: `src/meta_ads/` nao importa `src.google_ads`.

Os helpers numericos neutros (`razao`, `arredondado`, `percentual`) vivem em `src/razoes.py`;
importa-los de `src.google_ads.queries._common` acoplava a plataforma Meta ao pacote Google.
"""

from __future__ import annotations

import ast

from tests.unit import _guard_harness as h

_PROIBIDO = "src.google_ads"


def _importa_google(no: ast.AST) -> list[str]:
    if isinstance(no, ast.Import):
        modulos = [a.name for a in no.names]
    elif isinstance(no, ast.ImportFrom) and not no.level and no.module:
        modulos = [no.module, *[f"{no.module}.{a.name}" for a in no.names]]
    else:
        return []
    return [m for m in modulos if m == _PROIBIDO or m.startswith(_PROIBIDO + ".")]


def test_meta_ads_nao_importa_google_ads() -> None:
    fontes = h.fontes_py(h.SRC / "meta_ads")
    ofensores = [
        f"{h.rel(f)}:{no.lineno}"
        for f in fontes
        for no in ast.walk(h.arvore(f))
        if _importa_google(no)
    ]
    assert not ofensores, f"meta_ads importa src.google_ads: {ofensores}"
