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

_REPOS = h.SRC / "db" / "repositories"
_MOTIVOS = _REPOS / "motivos.py"
_INVENTARIOS = {
    _REPOS / "google_ads_accounts.py": "manager_account_access",
    _REPOS / "meta_ad_accounts.py": "manager_meta_account_access",
}


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


def _imports_do_modulo(arv: ast.Module, modulo: str) -> list[int]:
    """Linhas de qualquer import (topo ou local, absoluto ou relativo) de `modulo`."""
    linhas: list[int] = []
    for no in ast.walk(arv):
        if isinstance(no, ast.ImportFrom):
            nomes = [(no.module or "")] + [f"{no.module or ''}.{a.name}" for a in no.names]
            if any(n.split(".")[-1] == modulo for n in nomes):
                linhas.append(no.lineno)
        elif isinstance(no, ast.Import):
            if any(a.name.split(".")[-1] == modulo for a in no.names):
                linhas.append(no.lineno)
    return sorted(linhas)


def test_inventario_nao_importa_o_acesso() -> None:
    """O ciclo inventário <-> acesso: o inventário não importa o acesso, nem local."""
    for caminho, modulo in _INVENTARIOS.items():
        assert caminho.is_file(), h.rel(caminho)  # não vacuidade
        arv = h.arvore(caminho)
        assert _imports_do_modulo(arv, modulo) == [], h.rel(caminho)


def test_detector_do_ciclo_pega_import_local_e_relativo() -> None:
    fonte = "\n".join(
        [
            "def f():",
            "    from src.db.repositories.manager_account_access import X",
            "from . import manager_account_access",
            "from .manager_account_access import Y",
            "import src.db.repositories.manager_account_access",
            "import os",
        ]
    )
    assert _imports_do_modulo(ast.parse(fonte), "manager_account_access") == [2, 3, 4, 5]


def test_literais_dos_motivos_sao_fixos() -> None:
    """Valores gravados em `revoked_reason` — os testes de integração comparam com a
    própria constante, então só este pin pega uma troca de literal."""
    from src.db.repositories import motivos

    assert motivos.LEFT_MCC_REASON == "left_mcc"
    assert motivos.ADMIN_REVOKED_REASON == "admin_revoked"
    assert motivos.PARTNERSHIP_ENDED_REASON == "partnership_ended"
    assert motivos.BULK_COPY_REPLACED_REASON == "bulk_copy_replaced"
