"""`ORDER BY occurred_at DESC` sem desempate + LIMIT/OFFSET pula e duplica linha.

`occurred_at` empata de verdade: auditoria de lote grava varias linhas no mesmo
instante. Quando duas linhas empatam, o Postgres nao promete ordem estavel entre
duas execucoes — a pagina 2 pode repetir uma linha da pagina 1 e omitir outra.

Por que regex e nao AST: sao literais SQL dentro de strings Python, invisiveis
para o AST. O casador exige que TODA ocorrencia de `ORDER BY ... occurred_at
DESC` seja seguida de uma virgula e outra coluna, em vez de enumerar os sitios
conhecidos — enumerar e o modo de falha 1 do catalogo (o que ficou fora da
lista passa).
"""

from __future__ import annotations

import re

import tests.unit._guard_harness as h

# `occurred_at DESC` que NAO e seguido de `, <coluna>` antes do fim da clausula.
_SEM_DESEMPATE = re.compile(
    r"ORDER\s+BY\s+(?:\w+\.)?occurred_at\s+DESC(?!\s*,\s*(?:\w+\.)?\w+)",
    re.IGNORECASE,
)


def test_todo_order_by_por_occurred_at_tem_desempate() -> None:
    ofensores: list[str] = []
    arquivos = 0
    for p in h.fontes_py(h.SRC):
        texto = p.read_text(encoding="utf-8")
        if "occurred_at" not in texto:
            continue
        arquivos += 1
        for m in _SEM_DESEMPATE.finditer(texto):
            linha = texto[: m.start()].count("\n") + 1
            ofensores.append(f"{h.rel(p)}:{linha}")

    assert arquivos, (
        "o scanner nao viu nenhum arquivo com `occurred_at` — guard que varre "
        "zero arquivos passa por vacuidade."
    )
    assert not ofensores, (
        f"ORDER BY por occurred_at sem desempate: {ofensores}. Acrescente uma "
        "coluna unica e estavel (`, id DESC`): sem ela, LIMIT/OFFSET pula e "
        "duplica linha quando dois occurred_at empatam."
    )
