"""Retorno que responde "teve efeito?" nao pode ser descartado.

A classe: uma ausencia lida como medicao. `Unpack` devolve `bool` e o retorno
era jogado fora, entao `failure_pb` zerado virava "nenhuma linha falhou";
`delete_invite` devolve `bool` e o retorno era jogado fora, entao o audit
afirmava um cancelamento que podia nao ter ocorrido.

## Por que AST e nao grep

Os arquivos envolvidos CITAM o padrao proibido em prosa para explicar o fix —
grep casaria a propria docstring (modo de falha 1 de guards-que-nao-cobrem).

## Por que `ast.Await` e desembrulhado

Medido em 21/09: `await repo.delete_invite(...)` e
`ast.Expr -> ast.Await -> ast.Call`. Um casador que so olha
`isinstance(no.value, ast.Call)` perde TODO `await` descartado — num codebase
async, quase todos. O desenho original deste guard tinha esse furo e pegava 1
dos 3 alvos.

## O que este guard NAO faz

Nao reafirma o contrato de `erros_por_indice`. Ali o mecanismo e o mypy: o
tipo `LeituraDeFalhas` nao tem `.items()`, entao consumidor que o trate como
dict quebra em type-check. Duas assercoes da mesma regra divergem no dia em
que uma e atualizada. Aqui ele entra so como CONTROLE: se sumir, o guard
perdeu o sujeito.
"""

import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _guard_harness as h  # noqa: E402

# Retorno destes responde "teve efeito?" — descartar e ler ausencia como zero.
ALVOS_QUE_NAO_PODEM_SER_DESCARTADOS = {"Unpack", "delete_invite"}

# Controle anti-vacuidade. Medido em 2026-09-21 sobre 201 arquivos de src/:
# erros_por_indice 3, delete_invite 1, Unpack 1. Piso vem da CONTAGEM — um
# piso chutado (200 contra populacao de 161) ja disparou por engano neste repo.
PISO_DE_CHAMADAS = {"erros_por_indice": 3, "delete_invite": 1, "Unpack": 1}


def _chamada(no: ast.AST) -> ast.Call | None:
    """A `Call` de um statement-expression, desembrulhando `await`.

    Recebe `ast.AST` e nao `ast.stmt` de proposito: `ast.walk` devolve `AST`,
    e anotar `stmt` faria o mypy strict recusar o call-site.
    """
    if not isinstance(no, ast.Expr):
        return None
    valor: ast.expr = no.value
    if isinstance(valor, ast.Await):
        valor = valor.value
    return valor if isinstance(valor, ast.Call) else None


def _nome_chamado(chamada: ast.Call, origens: dict[str, str]) -> str | None:
    caminho = h.caminho_canonico(chamada.func, origens)
    return caminho.split(".")[-1] if caminho else None


def _varrer() -> tuple[list[str], dict[str, int]]:
    descartados: list[str] = []
    contagem = dict.fromkeys(PISO_DE_CHAMADAS, 0)
    for arq in h.fontes_py():
        arv = h.arvore(arq)
        origens = h.origens_de_import(arv)
        for no in ast.walk(arv):
            if isinstance(no, ast.Call):
                nome = _nome_chamado(no, origens)
                if nome in contagem:
                    contagem[nome] += 1
            chamada = _chamada(no)
            if chamada is None:
                continue
            nome = _nome_chamado(chamada, origens)
            if nome in ALVOS_QUE_NAO_PODEM_SER_DESCARTADOS:
                descartados.append(f"{h.rel(arq)}:{no.lineno} ({nome})")
    return descartados, contagem


def test_o_guard_tem_sujeito() -> None:
    """CONTROLE. Sem isto, renomear um alvo deixa a varredura vazia e VERDE."""
    _descartados, contagem = _varrer()
    magros = {k: v for k, v in contagem.items() if v < PISO_DE_CHAMADAS[k]}
    if magros:
        raise h.EscopoVazioError(
            f"alvos abaixo do piso medido: {magros} (esperado >= {PISO_DE_CHAMADAS}). "
            "Foram renomeados ou removidos — este guard parou de olhar para eles."
        )


def test_nenhum_retorno_de_efeito_e_descartado() -> None:
    descartados, _contagem = _varrer()
    assert not descartados, (
        "retorno que responde 'teve efeito?' descartado em:\n  "
        + "\n  ".join(descartados)
        + "\nLer a ausencia como zero e a classe inteira deste guard."
    )
