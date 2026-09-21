"""O fake de `Any.Unpack` tem de devolver `bool`, como o proto real devolve.

Sondado em 2026-09-21 contra o protobuf instalado:

    Unpack(tipo CERTO)  -> True
    Unpack(tipo ERRADO) -> False   (sem excecao, e o alvo fica intocado)

O fake antigo devolvia `None`. Enquanto a producao descartava o retorno isso
nao aparecia; no minuto em que ela passou a ler, `None` virou falsy e os
testes de partial failure teriam ficado vermelhos SEM bug nenhum — o modo
"o mock que bloqueia o conserto".

Este guard existe para que o fake nao volte a mentir sobre a forma do proto.
Teste que codifica a convencao errada e PIOR que teste ausente (F87, F89).
"""

import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _guard_harness as h  # noqa: E402

# Medido em 2026-09-21: 6 arquivos stubam `Unpack`. O piso vem da CONTAGEM,
# nunca de estimativa — um piso chutado ja disparou por engano neste repo.
PISO_DE_ARQUIVOS = 6


def _funcoes_fake_unpack() -> list[tuple[str, ast.FunctionDef]]:
    achados: list[tuple[str, ast.FunctionDef]] = []
    for arq in h.testes_py():
        arv = h.arvore(arq)
        for no in ast.walk(arv):
            if isinstance(no, ast.FunctionDef) and no.name == "fake_unpack":
                achados.append((h.rel(arq), no))
    return achados


def test_todo_fake_unpack_devolve_bool() -> None:
    achados = _funcoes_fake_unpack()
    arquivos = {nome for nome, _ in achados}
    if len(arquivos) < PISO_DE_ARQUIVOS:
        raise h.EscopoVazioError(
            f"esperava >= {PISO_DE_ARQUIVOS} arquivos com `fake_unpack`, "
            f"achei {len(arquivos)}: {sorted(arquivos)}. O fake foi renomeado "
            "ou removido — este guard parou de olhar para alguma coisa."
        )

    culpados = [
        f"{nome}:{fn.lineno}"
        for nome, fn in achados
        if not any(isinstance(no, ast.Return) and no.value is not None for no in ast.walk(fn))
    ]
    assert not culpados, (
        "fake_unpack sem `return`: o proto real devolve bool, e um fake que "
        f"devolve None faz a producao ler falsy sem bug. Culpados: {culpados}"
    )
