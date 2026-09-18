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

Um segundo teste, `test_pares_sombreados_tem_literal_antes_do_parametrico`,
cobre o que o snapshot não cobre: ORDEM de registro. `_tabela()` termina em
`sorted(...)` pra virar um snapshot estável — e isso apaga a posição relativa
que decide qual rota casa primeiro quando duas podem casar a mesma URL
(Starlette é primeiro-que-casa-vence). Ver o docstring daquele teste.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.routing import APIRoute

from src.web.routes import router

_SNAPSHOT = Path(__file__).resolve().parent / "fixtures" / "tabela_de_rotas.json"


def _flatten(routes: list[Any]) -> list[Any]:
    """Resolve `router.include_router(...)` até as rotas EFETIVAS.

    Correção 1/5 da Task 2 (Bloqueador 1 da revisão). A primeira versão deste
    resolvedor (escrita durante a própria Task 2, pra corrigir o guard nunca
    achando nenhuma das 42 rotas — ver histórico do commit `372ae41`) descia
    por `getattr(r, "original_router", None).routes`: o router CRU do
    submódulo, do jeito que ele existe ANTES de qualquer `include_router`
    aplicar prefix/dependencies/tags. Isso resolvia o sintoma (o guard
    voltando `[]` sempre), mas ficava cego ao que `include_router` de fato
    muda: uma rota puxada via
    `router.include_router(sub, dependencies=[Depends(guarda_admin)])`
    aparecia com `dependant.dependencies == []`, porque essa dependência não
    mora no `APIRoute` do submódulo — só existe depois que o FastAPI MESCLA o
    `include_context` (prefix + dependencies + tags de toda a cadeia) na
    rota. Repro medido (ver relatório, rodada 1): um router `sub` com uma
    rota sem nenhum `Depends` própria, incluído via
    `mid.include_router(sub, prefix="/admin", dependencies=[Depends(algo)])`
    — a travessia por `original_router.routes` cru devolve
    `path=/x name=x deps=[]`; dispatch real serve `/admin/x` com `algo`
    aplicado, e `/x` isolado nem existe (404).

    O objeto certo é `effective_candidates()`: método que todo wrapper de
    `include_router` (`_IncludedRouter`, injetado nesta versão do FastAPI
    mesmo sem nenhum prefix/tags/dependencies) expõe pra resolver, sob
    demanda, cada rota do submódulo já mesclada com o `include_context` do
    pai — um `_EffectiveRouteContext` cujos `path`/`name`/`methods`/
    `dependant` já refletem prefix+dependencies+tags de TODA a cadeia de
    `include_router` até a raiz, não só o último nível. Mesmo repro, agora
    certo: `path=/admin/x name=x deps=['algo']`.

    A busca continua por NOME de atributo (`effective_candidates`,
    `original_route`, `dependant`), não por `isinstance` contra as classes
    privadas `_IncludedRouter`/`_EffectiveRouteContext` (prefixo `_`, em
    `fastapi.routing`) — mesma razão de resiliência a mudança de versão que
    já valia pro `original_router` da primeira versão deste resolvedor.

    Dispatch real (`app(scope, receive, send)`) resolve os wrappers sozinho
    — confirmado com um `TestClient` de dois níveis de `include_router`
    batendo 200 — então isto sempre foi só um problema de INTROSPECÇÃO deste
    teste, não de comportamento da aplicação.

    Pra um `APIRouter` sem nenhum `include_router` (o caso de antes do
    split, se algum dia voltar a existir), `router.routes` já é só
    `APIRoute` puro — o ramo `isinstance(r, APIRoute)` cobre esse caso
    direto, sem passar por `effective_candidates()` nenhuma. Comportamento
    pré-split continua sendo subconjunto exato deste.
    """
    achados: list[Any] = []
    for r in routes:
        if isinstance(r, APIRoute):
            achados.append(r)
            continue
        efetivas = getattr(r, "effective_candidates", None)
        if efetivas is not None:
            achados.extend(_flatten(efetivas()))
            continue
        original = getattr(r, "original_route", None)
        if isinstance(original, APIRoute) and hasattr(r, "dependant"):
            achados.append(r)
    return achados


def _tabela() -> list[dict[str, object]]:
    linhas: list[dict[str, object]] = []
    for r in _flatten(router.routes):
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


# --- Bloqueador 2 (rodada 1): ordem de registro, não só o conjunto ---------
#
# Os 4 pares literal/paramétrico reais das 42 rotas (medido por inspeção da
# tabela da Task 2): o segundo elemento de cada par PODE casar o primeiro, e
# Starlette resolve primeiro-que-casa-vence. Hoje os quatro pares estão
# CORRETOS (literal antes do paramétrico) — e os quatro vivem dentro do MESMO
# módulo (3 em `admin_access.py`, 1 em `audit.py`): quem move a rota
# paramétrica pra cima da literal dentro do arquivo, ou extrai uma delas pra
# outro módulo incluído antes, quebra o casamento sem tocar método nem
# caminho isolados — exatamente o que `_tabela()` (ordenada) não vê.
_PARES_SOMBREADOS: tuple[tuple[str, str], ...] = (
    ("/audit/export.csv", "/audit/{audit_id}"),
    ("/admin/access/by-manager", "/admin/access/{manager_id}"),
    ("/admin/access/meta", "/admin/access/{manager_id}"),
    ("/admin/access/meta/by-manager", "/admin/access/meta/{manager_id}"),
)


def _ordem_de_registro() -> list[str]:
    """Caminhos na ordem em que o FastAPI de fato os resolve.

    Ao contrário de `_tabela()` — que ordena por `(path, methods)` pra virar
    um snapshot estável e por isso apaga a ordem —, esta função devolve
    `_flatten(router.routes)` sem reordenar: a ordem em que
    `include_router`/`@router.get(...)` registraram cada rota, que é a mesma
    ordem em que `effective_candidates()` as visita (insertion order do
    `APIRouter.routes` original) e portanto a mesma ordem em que Starlette
    testa cada candidata contra uma URL recebida.
    """
    return [r.path for r in _flatten(router.routes)]


def test_pares_sombreados_tem_literal_antes_do_parametrico() -> None:
    """Cobre o que `test_a_tabela_de_rotas_bate_com_o_snapshot` não cobre.

    Bloqueador 2 da rodada 1 (Task 2): o docstring de
    `src/web/routes/__init__.py` promete que "a tabela fixada... pega
    qualquer troca de ordem que mude o casamento" — era falso enquanto só
    existia o teste de snapshot, porque `_tabela()` termina em
    `sorted(linhas, key=...)`: uma inversão completa da ordem de inclusão dos
    8 módulos passa por ali em silêncio (medido na revisão: guard verde).
    Este teste é o que torna a frase verdadeira — é o único que lê
    `_flatten` SEM ordenar.

    Prova (rodada 1, ver relatório): invertida a ordem física de
    `audit_export_csv`/`audit_detail` dentro de `audit.py`, este teste (e só
    ele) ficou vermelho; `test_a_tabela_de_rotas_bate_com_o_snapshot`
    continuou verde, porque o snapshot ordenado não muda com a troca.
    """
    ordem = _ordem_de_registro()
    for literal, parametrico in _PARES_SOMBREADOS:
        assert literal in ordem, f"{literal} sumiu da tabela de rotas efetiva"
        assert parametrico in ordem, f"{parametrico} sumiu da tabela de rotas efetiva"
        assert ordem.index(literal) < ordem.index(parametrico), (
            f"{literal} está registrado DEPOIS de {parametrico} — no dispatch "
            f"real (primeiro-que-casa-vence), {parametrico} vai engolir "
            f"{literal} antes que ele seja tentado."
        )
