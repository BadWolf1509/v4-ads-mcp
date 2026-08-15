"""F87: escape de string literal GAQL usa BARRA INVERTIDA, nao doubling de SQL.

O codigo usava `s.replace("'", "''")` com um comentario afirmando "same as SQL".
GAQL nao e SQL nisso. Verificado empiricamente contra a API real via
`validate_gaql` na conta sandbox (2026-08-14):

| GAQL                                      | valid |
|-------------------------------------------|-------|
| `... IN ('O\\'Brien')`   (barra invertida) | true  |
| `... IN ('O''Brien')`    (doubling SQL)    | false — "invalid value 'Brien'" |
| `... IN ('Promo \\')`    (barra crua)      | false — a string engoliu o `')` |
| `... IN ('Promo \\\\')`  (barra escapada)  | true  |

Duas consequencias, e a primeira e a que realmente dolorosa no dia a dia:

1. **Nome legitimo quebrava a query.** `Lead - D'Or` virava `'Lead - D''Or'`, que
   o parser le como duas strings coladas → o pre-flight de nome duplicado do
   `create_conversion_action` falhava com erro opaco do Google pra um nome
   perfeitamente valido.
2. **Barra invertida no fim escapava a aspa de fechamento** (3a linha da tabela),
   deixando a string engolir o resto da query. Impacto de injecao e baixo — a
   query e read-only e o customer_id e campo separado da request, entao o
   hard-gate segue intacto — mas e quebra de sintaxe garantida.

A ORDEM importa: escapar `\\` DEPOIS de `'` transformaria o `\\` que acabamos de
inserir, corrompendo o escape. Por isso barra invertida primeiro.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from src.google_ads.queries._gaql import gaql_string_literal


def test_aspa_simples_vira_barra_invertida_e_nao_doubling() -> None:
    """O core do F87: `'` → `\\'`, jamais `''`."""
    assert gaql_string_literal("O'Brien") == r"'O\'Brien'"
    assert "''" not in gaql_string_literal("O'Brien")


def test_barra_invertida_e_escapada() -> None:
    """`Promo \\` sem escape engole a aspa de fechamento (provado na API real)."""
    assert gaql_string_literal("Promo \\") == r"'Promo \\'"


def test_barra_invertida_e_escapada_antes_da_aspa() -> None:
    """Ordem: se escapasse a aspa primeiro, o `\\` inserido seria re-escapado.

    Entrada com os dois caracteres adjacentes (`\\` seguido de `'`) so sai correta
    se a barra for tratada primeiro.
    """
    assert gaql_string_literal("a\\'b") == r"'a\\\'b'"


def test_tentativa_de_injecao_nao_produz_aspa_solta() -> None:
    """O payload que fecharia a string e emendaria clausula fica inerte."""
    out = gaql_string_literal("a\\' OR 1=1 OR '")
    corpo = out[1:-1]  # tira as aspas delimitadoras que nos mesmos colocamos
    # Nenhuma aspa do corpo pode estar desacompanhada de uma barra que a escape.
    for i, ch in enumerate(corpo):
        if ch == "'":
            barras = len(corpo[:i]) - len(corpo[:i].rstrip("\\"))
            assert barras % 2 == 1, f"aspa nao escapada em {i}: {out!r}"


def test_string_sem_caractere_especial_so_ganha_as_aspas() -> None:
    assert gaql_string_literal("Lead WhatsApp") == "'Lead WhatsApp'"


@pytest.mark.asyncio
async def test_preflight_de_conversion_action_escapa_o_nome(monkeypatch) -> None:
    """F87 no call-site real: `Lead - D'Or` e um nome legitimo e nao pode quebrar."""
    capturado: dict[str, str] = {}

    async def fake_run_report(**kwargs: Any) -> list[dict[str, str]]:
        capturado["query"] = kwargs["query"]
        return []

    monkeypatch.setattr("src.google_ads.queries._common.run_report", fake_run_report)
    from src.google_ads.queries._common import validate_conversion_action_create

    await validate_conversion_action_create(
        manager_id=uuid4(),
        session_id=uuid4(),
        customer_id="1234567890",
        actions=[{"name": "Lead - D'Or", "category": "SUBMIT_LEAD_FORM", "type": "WEBPAGE"}],
    )

    assert r"'Lead - D\'Or'" in capturado["query"]
    assert "D''Or" not in capturado["query"]


def test_in_clause_do_change_history_escapa_com_barra() -> None:
    """`user_emails` chega como texto livre (o `format: email` do schema NAO e
    enforced — jsonschema.validate roda sem format_checker)."""
    from src.google_ads.queries.change_history import _format_in_clause

    out = _format_in_clause(["o'brien@v4company.com"])
    assert out == r"('o\'brien@v4company.com')"
