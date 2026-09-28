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
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from tests.unit import _guard_harness as h

_MIGRATIONS = h.SRC / "db" / "migrations"

# Exceções à regra do desempate: {(tabela, coluna final): a constraint UNIQUE que a garante}.
_DESEMPATE_POR_CHAVE_UNICA: dict[tuple[str, str], str] = {}

_REVOGA = re.compile(r"\bUPDATE\s+(\w+)\b.*?\bSET\b.*?\brevoked_at\s*=\s*now\(\)", re.I | re.S)
_SO_LINHA_VIVA = re.compile(r"\bWHERE\b.*\b(?:\w+\.)?revoked_at\s+IS\s+NULL\b", re.I | re.S)
_ESCOLHE_UMA = re.compile(r"\bFROM\s+(\w+)\b.*?\bORDER\s+BY\s+(.+?)\s+LIMIT\s+1\b", re.I | re.S)


def _texto(no: ast.AST) -> str | None:
    if isinstance(no, ast.Constant) and isinstance(no.value, str):
        return no.value
    if isinstance(no, ast.JoinedStr):
        return "".join(v.value if isinstance(v, ast.Constant) else "{}" for v in no.values)
    return None


def _literais(raiz: Path) -> list[tuple[str, str]]:
    achados = []
    for arquivo in h.fontes_py(raiz):
        for no in ast.walk(h.arvore(arquivo)):
            texto = _texto(no)
            if texto is not None:
                achados.append((f"{h.rel(arquivo)}:{no.lineno}", texto))  # type: ignore[attr-defined]
    return achados


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
        m = _ESCOLHE_UMA.search(t)
        if m and m.group(1).lower() in tabelas:
            achadas.append((onde, m.group(1).lower(), _ultima_chave(m.group(2))))
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
