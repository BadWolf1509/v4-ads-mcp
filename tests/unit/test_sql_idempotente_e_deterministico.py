"""Revogar é idempotente e escolher uma linha é determinístico (spec 2026-09-28 §3.2, itens 1 e 2).

Os dois guards são derivados do SQL, não de uma lista de funções — a mesma técnica do
guard do escritor único (F197): varrem os literais de string de `src/` e cobram a
propriedade de todo statement da forma, inclusive do próximo que alguém escrever.

1. **Revogar só pega linha viva.** Todo `UPDATE … SET revoked_at = now()` tem
   `revoked_at IS NULL` no `WHERE`. Sem ele, revogar de novo re-carimba a linha: no
   `manager_meta_account_access`, com outro motivo, ela ficaria fora do
   `restore_for_account` (que filtra por `revoked_reason`) sem ninguém ver. Medido em
   28/09: 9 revogações em `src/`, 3 sem o predicado (a Meta manual e as duas das conexões
   OAuth). O `restore`, que grava `revoked_at = NULL`, fica fora por definição.
2. **Escolher uma linha desempata por `id`.** Todo `ORDER BY … LIMIT 1` sobre tabela do
   nosso banco tem `id` como última chave. `ORDER BY connected_at DESC LIMIT 1` com duas
   conexões vivas no mesmo instante escolhia a credencial de forma arbitrária. Tabela "do
   nosso banco" = criada numa migration: é o que separa o SQL da GAQL (`change_event`,
   `campaign`), cujo `LIMIT 1` lê um valor, não escolhe linha.

Os casadores cobrem as formas que um refactor plausível produziria (revisão da Task 2): SQL
montado com `+`, nome de tabela interpolado (`UPDATE {tabela}`, `FROM {tabela}` — tabela
desconhecida é cobrada: erra acusando) e subquery ou CTE antes do `FROM` principal (cada
`ORDER BY … LIMIT 1` do literal é cobrado, não só o que segue o primeiro `FROM`).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from tests.unit import _guard_harness as h

_MIGRATIONS = h.SRC / "db" / "migrations"

# Os pisos abaixo (9 revogações, 3 escolhas de uma linha, medidos em 28/09) são OBSERVAÇÃO,
# não teto: código novo só os faz subir. Existem porque um casador que parasse de casar
# devolveria "nenhum ofensor" e ficaria verde para sempre.

# Exceções à regra do desempate: {(tabela, coluna final): a constraint UNIQUE que a garante}.
_DESEMPATE_POR_CHAVE_UNICA: dict[tuple[str, str], str] = {}

_REVOGA = re.compile(
    r"\bUPDATE\s+[\w{}.]+.*?\bSET\b.*?\brevoked_at\s*=\s*"
    r"(?:now\(\)|current_timestamp\b|clock_timestamp\(\)|\$\d+)",
    re.I | re.S,
)
_SO_LINHA_VIVA = re.compile(r"\bWHERE\b.*\b(?:\w+\.)?revoked_at\s+IS\s+NULL\b", re.I | re.S)
_TABELA_CITADA = re.compile(r"\b(?:FROM|JOIN)\s+(?:\w+\.)?(\w+|\{\})", re.I)
# Cada `ORDER BY` até o SEU `LIMIT 1`, sem atravessar outro `ORDER BY`, outro `LIMIT` ou `)`.
_ORDENA_E_PEGA_UMA = re.compile(
    r"\bORDER\s+BY\s+((?:(?!\bORDER\s+BY\b|\bLIMIT\b)[^)])+?)\s*\bLIMIT\s+1\b", re.I | re.S
)


def _texto(no: ast.AST) -> str | None:
    """O texto de um literal. `+` entre pedaços é juntado; o que não é literal (nome,
    chamada, interpolação) vira `{}`."""
    if isinstance(no, ast.Constant) and isinstance(no.value, str):
        return no.value
    if isinstance(no, ast.JoinedStr):
        return "".join(v.value if isinstance(v, ast.Constant) else "{}" for v in no.values)
    if isinstance(no, ast.BinOp) and isinstance(no.op, ast.Add):
        esquerda, direita = _texto(no.left), _texto(no.right)
        if esquerda is None and direita is None:
            return None
        return (esquerda if esquerda is not None else "{}") + (
            direita if direita is not None else "{}"
        )
    return None


def _literais_da_arvore(arv: ast.AST) -> list[tuple[int, str]]:
    """Só a expressão de texto INTEIRA: um pedaço de dentro de um `+` ou de uma f-string
    casaria sozinho a metade de um statement (o `UPDATE … SET` sem o `WHERE`)."""
    dentro_de_texto = {
        id(filho)
        for pai in ast.walk(arv)
        if isinstance(pai, ast.JoinedStr) or _texto(pai) is not None
        for filho in ast.iter_child_nodes(pai)
    }
    return [
        (no.lineno, t)  # type: ignore[attr-defined]
        for no in ast.walk(arv)
        if id(no) not in dentro_de_texto and (t := _texto(no)) is not None
    ]


def _literais(raiz: Path) -> list[tuple[str, str]]:
    return [
        (f"{h.rel(arquivo)}:{linha}", texto)
        for arquivo in h.fontes_py(raiz)
        for linha, texto in _literais_da_arvore(h.arvore(arquivo))
    ]


def _tabelas_do_banco(pasta: Path) -> set[str]:
    return {
        m.group(1).lower()
        for arq in sorted(pasta.glob("*.sql"))
        for m in re.finditer(
            r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)",
            arq.read_text(encoding="utf-8"),
            re.I,
        )
    }


def _revogacoes(literais: list[tuple[str, str]]) -> list[tuple[str, str]]:
    return [(onde, t) for onde, t in literais if _REVOGA.search(t)]


def _revogacoes_sem_predicado(literais: list[tuple[str, str]]) -> list[str]:
    return [onde for onde, t in _revogacoes(literais) if not _SO_LINHA_VIVA.search(t)]


def _ultima_chave(order_by: str) -> str:
    ultima = order_by.split(",")[-1].strip()
    ultima = re.sub(r"\s+(ASC|DESC)\b.*$|\s+NULLS\s+(FIRST|LAST)$", "", ultima, flags=re.I)
    return ultima.split(".")[-1].strip().lower()


def _escolhas_de_uma_linha(
    literais: list[tuple[str, str]], tabelas: set[str]
) -> list[tuple[str, str, str]]:
    achadas = []
    for onde, t in literais:
        citadas = {m.group(1).lower() for m in _TABELA_CITADA.finditer(t)}
        do_banco = sorted(citadas & (tabelas | {"{}"}))
        if not do_banco:
            continue
        for m in _ORDENA_E_PEGA_UMA.finditer(t):
            achadas.append((onde, ",".join(do_banco), _ultima_chave(m.group(1))))
    return achadas


def _escolhas_sem_desempate(literais: list[tuple[str, str]], tabelas: set[str]) -> list[str]:
    return [
        f"{onde} ({tabela}, termina em {chave!r})"
        for onde, tabela, chave in _escolhas_de_uma_linha(literais, tabelas)
        if chave != "id" and (tabela, chave) not in _DESEMPATE_POR_CHAVE_UNICA
    ]


def test_toda_revogacao_so_pega_linha_viva() -> None:
    literais = _literais(h.SRC)
    populacao = _revogacoes(literais)
    assert len(populacao) >= 9, (
        f"piso medido em 28/09: 9 revogações em src/; achou {len(populacao)} — "
        "o casador parou de casar?"
    )
    faltam = _revogacoes_sem_predicado(literais)
    assert not faltam, (
        f"revogação sem `revoked_at IS NULL` no WHERE: {faltam}. Revogar de novo re-carimba "
        "a linha (e, com outro motivo, a tira do restore) — spec 2026-09-28 §3.2.1."
    )


def test_toda_escolha_de_uma_linha_desempata_por_id() -> None:
    tabelas = _tabelas_do_banco(_MIGRATIONS)
    assert {"google_oauth_connections", "meta_oauth_connections", "audit_log"} <= tabelas
    literais = _literais(h.SRC)
    populacao = _escolhas_de_uma_linha(literais, tabelas)
    assert len(populacao) >= 3, (
        f"piso medido em 28/09: 3 `ORDER BY … LIMIT 1` sobre tabela do banco; achou "
        f"{len(populacao)}"
    )
    faltam = _escolhas_sem_desempate(literais, tabelas)
    assert not faltam, (
        f"`ORDER BY … LIMIT 1` sem `id` como última chave: {faltam}. Empate na ordenação "
        "escolhe a linha de forma arbitrária — spec 2026-09-28 §3.2.2."
    )


def test_os_casadores_veem_o_que_devem_e_so_isso() -> None:
    """Controle positivo e negativo dos dois casadores."""
    literais = [
        ("sem", "UPDATE x SET revoked_at = now() WHERE id = $1"),
        ("com", "UPDATE x SET revoked_at = now() WHERE id = $1 AND revoked_at IS NULL"),
        ("alias", "UPDATE x m SET revoked_at = now() FROM y WHERE m.revoked_at IS NULL"),
        ("restore", "UPDATE x SET revoked_at = NULL WHERE revoked_at IS NOT NULL"),
    ]
    assert [o for o, _ in _revogacoes(literais)] == ["sem", "com", "alias"]
    assert _revogacoes_sem_predicado(literais) == ["sem"]

    tabelas = {"conexoes"}
    escolhas = [
        ("empate", "SELECT * FROM conexoes WHERE a = $1 ORDER BY criado DESC LIMIT 1"),
        ("ok", "SELECT * FROM conexoes ORDER BY criado DESC, id DESC LIMIT 1"),
        ("gaql", "SELECT change_event.t FROM change_event ORDER BY change_event.t DESC LIMIT 1"),
        ("dez", "SELECT * FROM conexoes ORDER BY criado DESC LIMIT 10"),
    ]
    assert _escolhas_sem_desempate(escolhas, tabelas) == ["empate (conexoes, termina em 'criado')"]


_REFACTOR = """
a = f"UPDATE {tabela} SET revoked_at = now() WHERE id = $1"
b = "UPDATE conexoes " + "SET revoked_at = now() " + "WHERE id = $1"
c = "SELECT * FROM " + tabela + " ORDER BY criado DESC LIMIT 1"
d = "UPDATE conexoes " + "SET revoked_at = now() " + "WHERE id = $1 AND revoked_at IS NULL"
e = "UPDATE conexoes SET revoked_at = CURRENT_TIMESTAMP WHERE id = $1"
f = "UPDATE conexoes SET revoked_at = $2 WHERE id = $1"
g = "SELECT * FROM public.conexoes ORDER BY criado LIMIT 1"
"""


def test_os_casadores_veem_as_formas_de_um_refactor() -> None:
    """Controle das formas que as revisões apontaram como fora do casador: tabela interpolada,
    SQL montado com `+`, CTE/subquery antes do `FROM` principal, o carimbo por
    `CURRENT_TIMESTAMP` ou parâmetro e a tabela com schema. E o `d`: montado com `+` e
    CORRETO — um pedaço intermediário não pode acusar sozinho."""
    literais = [(f"l{n}", t) for n, t in _literais_da_arvore(ast.parse(_REFACTOR))]
    assert _revogacoes_sem_predicado(literais) == ["l2", "l3", "l6", "l7"]
    assert _escolhas_sem_desempate(literais, {"conexoes"}) == [
        "l4 ({}, termina em 'criado')",
        "l8 (conexoes, termina em 'criado')",
    ]

    cte = [
        (
            "cte",
            "WITH ultimas AS (SELECT * FROM conexoes WHERE vivo) "
            "SELECT * FROM ultimas ORDER BY criado DESC LIMIT 1",
        ),
        (
            "sub",
            "SELECT (SELECT n FROM conexoes c ORDER BY c.criado LIMIT 1) AS n "
            "FROM outra ORDER BY x DESC LIMIT 5",
        ),
    ]
    assert _escolhas_sem_desempate(cte, {"conexoes"}) == [
        "cte (conexoes, termina em 'criado')",
        "sub (conexoes, termina em 'criado')",
    ]
