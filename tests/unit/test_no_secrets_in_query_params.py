"""F82: segredo em `params=` vai parar na query string — e na URL logada.

O httpx loga `request.url` **completa** em INFO. O vazamento observado ja foi
fechado na origem (`configure_logging` silencia os loggers `httpx`/`httpcore`),
mas isso e uma camada: qualquer outra biblioteca que registre a URL, um proxy,
ou um `Referer` reintroduz a exposicao. O lado Google ja faz certo — `data=` no
corpo do POST e `Authorization` no header, nada na URL.

Este guard impede call-site NOVO com segredo na query. Os 3 remanescentes estao
na allowlist com motivo e condicao de saida explicitos — allowlist que encolhe,
nao que cresce.
"""

from __future__ import annotations

import ast
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"

# Chaves que nunca deveriam viajar na query string de um GET.
_CHAVES_SECRETAS = {
    "access_token",
    "client_secret",
    "app_secret",
    "input_token",
    "refresh_token",
    "password",
}

# Residuo conhecido, por (funcao, chave) — nao por funcao inteira, senao
# reintroduzir `access_token` numa funcao ja allowlistada passaria batido.
#
# `input_token` do `/debug_token` FICA na query porque nao ha alternativa:
# ele nao e credencial do chamador (e o objeto sendo inspecionado, logo nao
# cabe no header `Authorization`) e o endpoint NAO aceita POST — verificado
# contra o Graph real: HTTP 400, code 100, subcode 33 "Unsupported post
# request" (scripts/probe_meta_auth_header.py, item G).
#
# O que saiu da URL na mesma migracao foi o `app_id|app_secret` desse mesmo
# request — o segredo PERMANENTE. O `input_token` e um token de gestor, que
# expira. Sobra risco, mas de outra ordem de grandeza.
_RESIDUO_CONHECIDO = {
    ("meta_oauth_callback", "input_token"),
}


def _funcao_que_contem(arvore: ast.Module, alvo: ast.AST) -> str | None:
    """Nome da funcao que envolve `alvo` (o pai mais proximo)."""
    encontrado: str | None = None
    for no in ast.walk(arvore):
        if isinstance(no, ast.FunctionDef | ast.AsyncFunctionDef):
            for interno in ast.walk(no):
                if interno is alvo:
                    encontrado = no.name
    return encontrado


def _chaves_secretas(no: ast.AST) -> set[str]:
    """Chaves sensiveis num dict literal (vazio se nao for dict literal)."""
    if not isinstance(no, ast.Dict):
        return set()
    return {k.value for k in no.keys if isinstance(k, ast.Constant) and k.value in _CHAVES_SECRETAS}


def _achados() -> list[tuple[str, int, str, str]]:
    """(arquivo, linha, funcao, chave) pra cada segredo que vai como `params=`.

    Pega as duas formas. O dict INLINE (`params={... "access_token": t}`) e o
    obvio; o que quase escapou foi o dict montado numa VARIAVEL e passado
    depois (`params = {...}` … `http.get(url, params=params)`) — a forma que
    `_fetch_all_adaccounts` usa por causa da paginacao. Guard que so via a
    forma inline daria verde no call-site mais importante dos tres.
    """
    fora: list[tuple[str, int, str, str]] = []
    for caminho in _SRC.rglob("*.py"):
        arvore = ast.parse(caminho.read_text(encoding="utf-8"))
        rel = str(caminho.relative_to(_SRC))

        # Variaveis que recebem um dict literal com chave sensivel.
        marcadas: dict[str, set[str]] = {}
        for no in ast.walk(arvore):
            alvos = (
                no.targets
                if isinstance(no, ast.Assign)
                else ([no.target] if isinstance(no, ast.AnnAssign) else [])
            )
            valor = getattr(no, "value", None)
            if valor is None:
                continue
            achadas = _chaves_secretas(valor)
            if not achadas:
                continue
            for alvo in alvos:
                if isinstance(alvo, ast.Name):
                    marcadas.setdefault(alvo.id, set()).update(achadas)

        for no in ast.walk(arvore):
            if not isinstance(no, ast.Call):
                continue
            for kw in no.keywords:
                if kw.arg != "params":
                    continue
                achadas = _chaves_secretas(kw.value)
                if isinstance(kw.value, ast.Name):
                    achadas |= marcadas.get(kw.value.id, set())
                for chave in sorted(achadas):
                    fora.append(
                        (rel, no.lineno, _funcao_que_contem(arvore, no) or "<modulo>", chave)
                    )
    return fora


def test_nenhum_segredo_novo_na_query_string() -> None:
    """F82: allowlist so encolhe — segredo novo na URL quebra aqui."""
    violacoes = [a for a in _achados() if (a[2], a[3]) not in _RESIDUO_CONHECIDO]
    assert not violacoes, (
        "segredo em `params=` (vai pra query string e pra qualquer log de URL). "
        "Use `Authorization` no header, ou `data=` num POST — como "
        "`src/auth/oauth.py` faz no lado Google: "
        + "; ".join(f"{f}:{ln} em {fn}() -> {k}" for f, ln, fn, k in violacoes)
    )


def test_a_allowlist_descreve_a_realidade() -> None:
    """Guard do guard: entrada obsoleta na allowlist esconde regressao futura.

    Se o residuo for eliminado um dia e a entrada ficar, um segredo novo com o
    mesmo nome naquela funcao passaria despercebido.
    """
    reais = {(a[2], a[3]) for a in _achados()}
    obsoletas = _RESIDUO_CONHECIDO - reais
    assert not obsoletas, (
        f"na allowlist mas ja sem segredo em `params=`: {sorted(obsoletas)}. "
        "Remova a entrada — allowlist que nao encolhe vira ponto cego."
    )
