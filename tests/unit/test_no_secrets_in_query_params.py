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

import pytest

_SRC = Path(__file__).resolve().parents[2] / "src"

# Chaves que nunca deveriam viajar na query string de um GET.
#
# Onda final do F190 (2026-09-21): `appsecret_proof` e `authorization` entraram
# aqui. Os dois faltavam apesar de serem exatamente a familia que o F190 trata —
# o SDK injetava `appsecret_proof` junto com o `access_token`, sem opt-out, e
# `authorization` na QUERY nao e o cabecalho legitimo, e o cabecalho no lugar
# errado. A comparacao e por `.lower()` porque a forma que alguem escreveria e
# `{"Authorization": ...}`, com a maiuscula do header; casar so minusculo
# deixaria passar a unica grafia plausivel.
#
# A checagem olha SO o kwarg `params=`. E isso que permite listar
# `authorization` sem acusar os 4 dicts de cabecalho legitimos em `headers=`
# (inclusive `reports.py`, que E o fix do F190) nem os 3 `{"client_secret": …}`
# em `data=`, que sao o formato que o proprio F82 exigiu — um guard que acusa o
# proprio fix ensina a contornar o guard.
_CHAVES_SECRETAS = {
    "access_token",
    "appsecret_proof",
    "authorization",
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
    """Chaves sensiveis num dict construido no lugar (vazio se nao for um).

    Cobre as DUAS sintaxes de montar o dict: o literal `{"k": v}` e a chamada
    `dict(k=v)`. Cobrir so uma reproduziria, dentro do proprio guard, a
    assimetria que a onda final do F190 fechou em `_METODOS_CLIENTE_HTTP` entre
    `httpx` e `aiohttp` — a forma nao coberta e a que o proximo escape usa.

    Comparacao por `.lower()`: a grafia plausivel de um cabecalho e
    `{"Authorization": …}`, e casar so minusculo deixaria passar justamente ela.
    """
    if isinstance(no, ast.Dict):
        return {
            k.value
            for k in no.keys
            if isinstance(k, ast.Constant)
            and isinstance(k.value, str)
            and k.value.lower() in _CHAVES_SECRETAS
        }
    if isinstance(no, ast.Call) and isinstance(no.func, ast.Name) and no.func.id == "dict":
        return {
            kw.arg
            for kw in no.keywords
            if kw.arg is not None and kw.arg.lower() in _CHAVES_SECRETAS
        }
    return set()


def _achados_na_arvore(arvore: ast.Module, rel: str) -> list[tuple[str, int, str, str]]:
    """(arquivo, linha, funcao, chave) de cada segredo que vai como `params=`.

    Pega as duas formas. O dict INLINE (`params={... "access_token": t}`) e o
    obvio; o que quase escapou foi o dict montado numa VARIAVEL e passado
    depois (`params = {...}` … `http.get(url, params=params)`) — a forma que
    `_fetch_all_adaccounts` usa por causa da paginacao. Guard que so via a
    forma inline daria verde no call-site mais importante dos tres.

    Separada de `_achados()` (onda final F190) pra que os probes de contrato
    exercitem ESTA travessia, e nao uma copia dela num teste. Guard cujo probe
    reimplementa a logica nao distingue codigo bom de quebrado: os dois lados
    mudariam juntos.
    """
    fora: list[tuple[str, int, str, str]] = []

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
                fora.append((rel, no.lineno, _funcao_que_contem(arvore, no) or "<modulo>", chave))
    return fora


def _achados() -> list[tuple[str, int, str, str]]:
    """`_achados_na_arvore` sobre `src/` inteiro."""
    fora: list[tuple[str, int, str, str]] = []
    for caminho in _SRC.rglob("*.py"):
        arvore = ast.parse(caminho.read_text(encoding="utf-8"))
        fora.extend(_achados_na_arvore(arvore, str(caminho.relative_to(_SRC))))
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


# (id, fonte, acusa?) — contrato de `_chaves_secretas`, forma a forma.
#
# Onda final do F190: ate aqui o detector so era exercitado pela arvore real, que
# tem UM residuo conhecido (`input_token`). Isso prova que ele nao esta vazio, e
# nao prova mais nada — nenhuma forma NOVA (chave nova, `dict(...)`, maiuscula)
# tinha asserção, e os NEGATIVOS nao tinham nenhuma. Os negativos importam tanto
# quanto: sao os sites reais que uma versao "reforcada" pra qualquer dict passaria
# a acusar, incluindo o proprio fix do F190 em `headers=`.
_FORMAS_SEGREDO_EM_PARAMS = [
    ("params_access_token", 'http.get(u, params={"access_token": t})', True),
    ("params_appsecret_proof", 'http.get(u, params={"appsecret_proof": p})', True),
    ("params_client_secret", 'http.get(u, params={"client_secret": s})', True),
    ("params_authorization", 'http.get(u, params={"authorization": a})', True),
    # A grafia plausivel de um cabecalho: sem `.lower()` isto escapava.
    ("params_authorization_maiusculo", 'http.get(u, params={"Authorization": a})', True),
    ("params_via_dict_call", "http.get(u, params=dict(access_token=t))", True),
    # A forma que quase escapou no desenho original: dict na variavel.
    ("params_dict_em_variavel", 'p = {"access_token": t}\nhttp.get(u, params=p)', True),
    # NEGATIVOS — o fix do F190 e o do F82 nao podem acender o guard.
    ("headers_authorization", 'http.get(u, headers={"Authorization": f"Bearer {t}"})', False),
    ("data_client_secret", 'http.post(u, data={"client_secret": s})', False),
    ("params_sem_segredo", 'http.get(u, params={"level": "campaign"})', False),
    ("leitura_da_resposta", 't = r.json()["access_token"]', False),
]


@pytest.mark.parametrize(
    ("fonte", "acusa"),
    [(fonte, acusa) for _, fonte, acusa in _FORMAS_SEGREDO_EM_PARAMS],
    ids=[ident for ident, _, _ in _FORMAS_SEGREDO_EM_PARAMS],
)
def test_detector_acusa_a_violacao_e_so_ela(fonte: str, acusa: bool) -> None:
    """Contrato do detector, pela MESMA travessia que `_achados()` usa em `src/`.

    Chama `_achados_na_arvore` de proposito, em vez de reimplementar a
    travessia aqui: probe que copia a logica muda junto com ela e para de
    distinguir codigo bom de quebrado.
    """
    achados = _achados_na_arvore(ast.parse(fonte), "probe.py")

    assert bool(achados) is acusa, (
        f"veredito errado: esperado {'ACUSA' if acusa else 'passa'}, "
        f"obtido {achados or 'passa'} para:\n{fonte}"
    )
