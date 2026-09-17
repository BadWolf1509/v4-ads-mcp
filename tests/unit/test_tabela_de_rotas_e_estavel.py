"""A tabela de rotas do painel é um contrato — o split não pode mexer nela.

Este guard nasce ANTES do split (PR 5, Task 1) e existe para uma coisa só:
tornar falseável a afirmação "movimentação sem mudança de comportamento". A
suíte passar não basta — uma rota que trocasse de método, de caminho ou de
guard de autenticação no meio de um recorte de 1839 linhas passaria em todo
teste que não a exercitasse.

O snapshot é a lista ORDENADA de (método, caminho, nome do endpoint, nomes das
dependências). Inclui as dependências de propósito: perder um
`Depends(current_manager)` num recorte é exatamente o tipo de erro que o split
pode introduzir, e ele não muda nem método nem caminho.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.routing import APIRoute

from src.web.routes import router

_SNAPSHOT = Path(__file__).resolve().parent / "fixtures" / "tabela_de_rotas.json"


def _tabela() -> list[dict[str, object]]:
    linhas: list[dict[str, object]] = []
    for r in router.routes:
        if not isinstance(r, APIRoute):
            continue
        deps = sorted(
            d.call.__name__
            for d in r.dependant.dependencies
            if getattr(d, "call", None) is not None and hasattr(d.call, "__name__")
        )
        linhas.append(
            {
                "path": r.path,
                "methods": sorted(r.methods),
                "name": r.name,
                "deps": deps,
            }
        )
    return sorted(linhas, key=lambda x: (str(x["path"]), str(x["methods"])))


def test_a_tabela_de_rotas_bate_com_o_snapshot() -> None:
    atual = _tabela()
    assert _SNAPSHOT.exists(), (
        f"snapshot ausente em {_SNAPSHOT}. Ele é gravado UMA vez, antes do "
        "split, e nunca regenerado para fazer um teste passar — regenerar é "
        "apagar a única prova de que o split não mudou comportamento."
    )
    esperado = json.loads(_SNAPSHOT.read_text(encoding="utf-8"))
    assert atual == esperado, (
        "a tabela de rotas mudou. Se foi o split, ele NÃO foi movimentação "
        "pura — compare linha a linha e reponha o que se perdeu. Se a mudança "
        "é intencional (rota nova), atualize o snapshot no MESMO commit que a "
        "introduz, e diga por quê na mensagem."
    )


def test_o_snapshot_nao_esta_vazio() -> None:
    """Controle positivo: snapshot vazio faria o teste acima passar por vacuidade."""
    esperado = json.loads(_SNAPSHOT.read_text(encoding="utf-8"))
    assert len(esperado) >= 40, (
        f"snapshot tem {len(esperado)} rotas; o painel tinha 42 quando este "
        "guard foi escrito. Um snapshot truncado passa por vacuidade."
    )
