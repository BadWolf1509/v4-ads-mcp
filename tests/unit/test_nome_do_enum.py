"""`nome_do_enum` e o unico lugar de `src/` com o idioma `hasattr(x, "name")`."""

from __future__ import annotations

import ast

from google.ads.googleads.v25.enums.types.campaign_status import CampaignStatusEnum

from src.google_ads.queries._common import nome_do_enum
from tests.unit import _guard_harness as h


def test_enum_real_do_sdk_devolve_o_nome() -> None:
    assert nome_do_enum(CampaignStatusEnum.CampaignStatus.PAUSED) == "PAUSED"


def test_int_vira_str() -> None:
    assert nome_do_enum(29) == "29"


def test_str_continua_str() -> None:
    assert nome_do_enum("ENABLED") == "ENABLED"


def test_none_vira_texto_none() -> None:
    assert nome_do_enum(None) == "None"


def _usa_hasattr_name(no: ast.Call) -> bool:
    """`hasattr(<qualquer>, "name")` — AST, entao pega a forma multilinha."""
    return (
        isinstance(no.func, ast.Name)
        and no.func.id == "hasattr"
        and len(no.args) >= 2
        and isinstance(no.args[1], ast.Constant)
        and no.args[1].value == "name"
    )


def test_idioma_so_no_helper() -> None:
    fora: list[str] = []
    for caminho in h.fontes_py():
        arv = h.arvore(caminho)
        # `funcoes` + intervalo de linhas: dentro de `nome_do_enum` e permitido.
        permitido: set[int] = set()
        for fn in h.funcoes(arv):
            if fn.name == "nome_do_enum" and h.rel(caminho) == "src/google_ads/queries/_common.py":
                permitido.update(range(fn.lineno, (fn.end_lineno or fn.lineno) + 1))
        for no in ast.walk(arv):
            if isinstance(no, ast.Call) and _usa_hasattr_name(no) and no.lineno not in permitido:
                fora.append(f"{h.rel(caminho)}:{no.lineno}")
    assert not fora, (
        "hasattr(x, 'name') fora de nome_do_enum — use "
        f"src.google_ads.queries._common.nome_do_enum: {fora}"
    )
