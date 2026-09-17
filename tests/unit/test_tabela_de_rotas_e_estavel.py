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
from typing import Any

from fastapi.routing import APIRoute

from src.web.routes import router

_SNAPSHOT = Path(__file__).resolve().parent / "fixtures" / "tabela_de_rotas.json"


def _flatten(routes: list[Any]) -> list[APIRoute]:
    """Resolve `router.include_router(...)` até achar os `APIRoute` de verdade.

    Achado na Task 2 (split de `routes.py`), não hipotético: nesta versão do
    FastAPI, `include_router` NUNCA copia os `APIRoute` do sub-router pro pai —
    ele sempre acrescenta um `_IncludedRouter` (resolução tardia, ver
    `fastapi.routing`), mesmo sem prefix/tags/dependencies. Isso não existia
    quando este guard foi escrito (Task 1): o `router` de `routes.py`, arquivo
    único, nunca chamava `include_router` sobre si mesmo, então `.routes` já
    saía achatado. O split (Task 2) introduz `__init__.py` agregando nove
    módulos via `include_router` — e a partir daí `router.routes` passa a
    conter só wrappers, nenhum `APIRoute` direto, e o filtro original
    (`isinstance(r, APIRoute)`) devolve `[]` sempre, não porque uma rota
    sumiu, mas porque nenhuma rota nunca chega a essa checagem.

    Dispatch real (`app(scope, receive, send)`) resolve os wrappers sozinho —
    confirmado com um `TestClient` de dois níveis de `include_router` batendo
    200 — então isto é só um problema de INTROSPECÇÃO deste teste, não de
    comportamento da aplicação. A busca é pelo nome do atributo
    (`original_router`), não pela classe `_IncludedRouter` (privada, prefixo
    `_`, em `fastapi.routing`): mais resiliente a mudança de versão, e o
    dataclass que a FastAPI usa hoje expõe exatamente esse atributo.

    Continua achatando um `APIRouter` comum sem nenhum `_IncludedRouter` do
    jeito que sempre achatou — `getattr(r, "original_router", None)` é `None`
    pra um `APIRoute` puro, então o ramo novo nunca dispara nesse caso e o
    comportamento pré-split é subconjunto exato deste.
    """
    achados: list[APIRoute] = []
    for r in routes:
        if isinstance(r, APIRoute):
            achados.append(r)
            continue
        sub_router = getattr(r, "original_router", None)
        if sub_router is not None:
            achados.extend(_flatten(sub_router.routes))
    return achados


def _tabela() -> list[dict[str, object]]:
    linhas: list[dict[str, object]] = []
    for r in _flatten(router.routes):
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
