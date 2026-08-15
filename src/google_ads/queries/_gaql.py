"""Primitivas de montagem de GAQL. Sem dependencias — importavel de qualquer builder.

GAQL nao tem prepared statements: toda query e string montada. Quando um valor de
texto livre entra numa clausula, o escape e a unica defesa — e ele NAO segue a
convencao de SQL.

**F87 — GAQL escapa com BARRA INVERTIDA, nao com doubling.** O codigo anterior
fazia `s.replace("'", "''")`, com um comentario afirmando "same as SQL". Verificado
empiricamente contra a API real (`validate_gaql`, conta sandbox, 2026-08-14):

    ... IN ('O\\'Brien')     -> valid: true
    ... IN ('O''Brien')      -> valid: false  ("invalid value 'Brien'")
    ... IN ('Promo \\')      -> valid: false  (a string engoliu o `')`)
    ... IN ('Promo \\\\')    -> valid: true

O dano cotidiano era o primeiro caso invertido: um nome legitimo como
`Lead - D'Or` virava `'Lead - D''Or'`, o parser lia duas strings coladas, e o
pre-flight de nome duplicado do `create_conversion_action` falhava com erro opaco
do Google pra um nome perfeitamente valido. O segundo (barra invertida solta
escapando a aspa de fechamento) e o vetor de quebra de sintaxe / clausula extra;
o impacto e contido porque a query e read-only e o `customer_id` viaja em campo
separado da request, entao o hard-gate nao e afetado.
"""

from __future__ import annotations


def gaql_escape(value: str) -> str:
    """Escapa o CONTEUDO de um string literal GAQL (sem as aspas delimitadoras).

    A ordem e load-bearing: a barra invertida vem PRIMEIRO. Escapando a aspa
    antes, as barras que nos mesmos acabamos de inserir seriam re-escapadas no
    passo seguinte, corrompendo o resultado.
    """
    return value.replace("\\", "\\\\").replace("'", "\\'")


def gaql_string_literal(value: str) -> str:
    """Valor de texto livre -> string literal GAQL pronta, COM as aspas.

    Use isto (e nao interpolacao manual) sempre que um valor vindo de param de
    tool entrar numa query.
    """
    return f"'{gaql_escape(value)}'"


def gaql_in_list(values: list[str]) -> str:
    """Lista de strings -> `('a', 'b')` pra clausula IN, com cada item escapado."""
    return f"({', '.join(gaql_string_literal(v) for v in values)})"
