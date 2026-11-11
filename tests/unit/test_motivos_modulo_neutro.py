"""`motivos.py` é o módulo NEUTRO dos motivos de revogação: nenhum import de
`src.*`.

Existe para quebrar o ciclo inventário <-> acesso (o inventário precisava de
`LEFT_MCC_REASON`/`PARTNERSHIP_ENDED_REASON` e o acesso importa o inventário).
Se ele passar a importar de qualquer repositório, o ciclo volta — escondido
atrás de um import local — e o inventário volta a depender do acesso.
"""

from __future__ import annotations

import ast

from tests.unit import _guard_harness as h

_MOTIVOS = h.SRC / "db" / "repositories" / "motivos.py"


def _imports_de_src(arv: ast.Module) -> list[str]:
    achados: list[str] = []
    for no in ast.walk(arv):
        if isinstance(no, ast.ImportFrom):
            if no.level > 0 or (no.module or "").startswith("src"):
                achados.append(f"from {'.' * no.level}{no.module or ''}")
        elif isinstance(no, ast.Import):
            achados.extend(f"import {a.name}" for a in no.names if a.name.startswith("src"))
    return achados


def test_motivos_nao_importa_de_src() -> None:
    assert _MOTIVOS.is_file(), h.rel(_MOTIVOS)
    arv = h.arvore(_MOTIVOS)
    # Não vacuidade: o módulo tem as quatro constantes que o resto importa.
    nomes = {
        a.targets[0].id
        for a in arv.body
        if isinstance(a, ast.Assign) and isinstance(a.targets[0], ast.Name)
    }
    assert nomes >= {
        "LEFT_MCC_REASON",
        "ADMIN_REVOKED_REASON",
        "PARTNERSHIP_ENDED_REASON",
        "BULK_COPY_REPLACED_REASON",
    }
    assert _imports_de_src(arv) == []


def test_detector_de_import_pega_import_de_repositorio() -> None:
    fonte = "\n".join(
        [
            "from src.db.repositories.google_ads_accounts import X",
            "from . import y",
            "import src.db",
            "import os",
        ]
    )
    assert _imports_de_src(ast.parse(fonte)) == [
        "from src.db.repositories.google_ads_accounts",
        "from .",
        "import src.db",
    ]
