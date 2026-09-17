"""Toda rota POST do painel tem guard de autorização — não só de autenticação.

`current_manager` responde "quem é você"; `_require_admin` responde "você
pode". Uma rota de mutação administrativa com só o primeiro deixa qualquer
gestor logado disparar a ação — foi o caso de
`POST /oauth/meta/refresh-accounts`, que re-sincroniza o inventário inteiro de
contas Meta contra o Graph usando o token de system user.

Por que a lista de isenções é por ROTA e traz motivo escrito: prefixo herda
tudo que um `APIRouter(prefix=…)` pendurar ali depois, sem revisão (F106), e a
mesma lógica vale para qualquer isenção larga.

Duas decisões medidas antes de escrever o casador (não assumidas):

1. **`create_app()` vem de `src.app`, não de `src.web`** — `src/web/__init__.py`
   está vazio. `from src.web import create_app` (como um rascunho anterior
   sugeria) falha com `ImportError` antes de examinar rota nenhuma.

2. **O casador precisa olhar dependências E corpo da função — corpo não é
   opcional.** `_require_admin` tem 25 call sites hoje e NENHUM é
   `Depends(_require_admin)`: todas as rotas admin do painel chamam
   `_require_admin(user)` como primeira linha do corpo (padrão visível em
   `src/web/routes/admin_*.py`). Um casador que olha só
   `r.dependant.dependencies` (a lista de injeção do FastAPI) nunca vê essas
   25 chamadas — elas rodam DEPOIS da injeção, dentro da função — e acusaria
   todas as 25 rotas corretas como ofensoras. Medido: rodar o casador só-por-
   dependências contra a árvore de rotas real desta app aponta as 12 rotas
   POST admin (de um total de 19 POST fora `/mcp`) como "sem guard", quando
   `_require_admin` está lá, só que no corpo. `_calls_require_admin_no_corpo`
   below faz uma checagem por AST (não substring) — não é enganada por um
   comentário ou docstring que apenas MENCIONE `_require_admin` sem chamá-lo.

Também medido: `app.routes` no nível superior expõe só `/mcp`, `/health`,
`/docs` etc. como `APIRoute` puro — os três routers de verdade (`oauth`,
`meta_oauth`, o `web_router` de 9 módulos) chegam envolvidos em
`_IncludedRouter`, mesmo sem nenhum `prefix`/`dependencies` explícito nesta
versão do FastAPI. `test_tabela_de_rotas_e_estavel.py` já resolveu esse
problema (`_flatten`, via `effective_candidates()`) para `src.web.routes.router`
— este teste reusa a MESMA função contra `app.routes` inteiro, porque
`refresh-accounts` mora em `src.auth.meta_oauth`, fora daquele router (por
isso não está no snapshot da tabela de rotas — confirmado por inspeção: o
snapshot é gerado a partir de `src.web.routes.router`, que nunca inclui
`meta_oauth_module.router`). Reimplementar o resolvedor aqui arriscaria
divergir dele silenciosamente; importar mantém os dois sincronizados por
construção.
"""

from __future__ import annotations

import ast
import inspect
import textwrap
from collections.abc import Callable
from typing import Any

from fastapi.routing import APIRoute

from tests.unit.test_tabela_de_rotas_e_estavel import _flatten

# Rotas POST que legitimamente NÃO exigem admin, cada uma com o motivo.
_SEM_ADMIN_COM_MOTIVO = {
    "/logout": (
        "Não recebe nem `current_manager`: só limpa o cookie de sessão de "
        "quem chamou. Sem recurso de terceiro em jogo — seguro pra deslogado "
        "também (POST-only existe pra evitar logout-CSRF, não pra restringir "
        "quem loga)."
    ),
    "/oauth/meta/data-deletion-callback": (
        "Webhook do Meta App Review, não rota de painel: não recebe "
        "`current_manager` — quem chama é o servidor do Meta, autenticado "
        "via HMAC do `signed_request` assinado com `meta_app_secret`, não "
        "por sessão de gestor."
    ),
    "/oauth/meta/revoke": (
        "Autosserviço: revoga a conexão Meta ATIVA do próprio "
        "`user.id` (`get_active_for_manager(conn, user.id)`) — não aceita "
        "alvo de terceiro, não há o que um admin precisaria autorizar."
    ),
    "/sessions/new": (
        "Autosserviço: cria uma sessão MCP com `manager_id=user.id`, sempre a do próprio chamador."
    ),
    "/sessions/{session_id}/revoke": (
        "Autosserviço com posse checada no corpo: busca a sessão em "
        "`list_for_manager(conn, user.id, ...)` e 404 se o `session_id` não "
        "pertence a quem chamou — não dá pra revogar sessão alheia."
    ),
    "/accounts/{connection_id}/revoke": (
        "Autosserviço com posse checada no corpo: 404 se "
        "`owner != user.id` antes de revogar a conexão OAuth Google — não dá "
        "pra revogar conexão alheia."
    ),
}


def _calls_require_admin_no_corpo(endpoint: Callable[..., Any]) -> bool:
    """True se o corpo do endpoint contém uma CHAMADA a `_require_admin`.

    Por AST, não substring: uma docstring ou comentário que só MENCIONE
    `_require_admin` não deve contar (é exatamente o tipo de guard "verdadeiro
    independente da implementação" que não vale nada). Varre a árvore inteira
    (`ast.walk`) em vez de só o primeiro statement — hoje toda chamada real é
    incondicional e é a primeira linha, mas o teste não depende dessa posição
    pra não quebrar por reordenação inofensiva.
    """
    try:
        source = inspect.getsource(endpoint)
    except (OSError, TypeError):
        return False
    tree = ast.parse(textwrap.dedent(source))
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_require_admin"
        for node in ast.walk(tree)
    )


def test_toda_rota_post_do_painel_exige_admin_ou_tem_motivo() -> None:
    # Lazy import (mesmo padrão de tests/conftest.py e tests/integration/conftest.py):
    # src/app.py roda `app = create_app()` no NÍVEL DE MÓDULO (linha 163, pra
    # uvicorn/Buildpacks). Um `from src.app import create_app` no topo deste
    # arquivo dispara essa chamada na COLETA do pytest — antes da fixture
    # autouse `_test_env` (tests/conftest.py) rodar, porque fixture roda na
    # INVOCAÇÃO do teste, não na coleta. `get_settings()` explode por env
    # faltando. Import dentro da função evita a ordem errada.
    from src.app import create_app

    app = create_app(skip_db_init=True)
    ofensores: list[str] = []
    examinadas = 0
    for r in _flatten(app.routes):
        if not isinstance(r, APIRoute) and not hasattr(r, "dependant"):
            continue
        if "POST" not in r.methods:
            continue
        if r.path.startswith("/mcp"):
            continue
        examinadas += 1
        deps = {
            d.call.__name__
            for d in r.dependant.dependencies
            if getattr(d, "call", None) is not None and hasattr(d.call, "__name__")
        }
        if "_require_admin" in deps:
            continue
        if _calls_require_admin_no_corpo(r.endpoint):
            continue
        if r.path in _SEM_ADMIN_COM_MOTIVO:
            continue
        ofensores.append(f"{r.path} ({r.name})")

    assert examinadas >= 19, (
        f"o scanner viu {examinadas} rotas POST (esperava >= 19) — guard que "
        "varre de menos passa por vacuidade. Confira se create_app() registra "
        "os três routers (oauth, meta_oauth, web) e se _flatten resolve os "
        "wrappers _IncludedRouter."
    )
    assert not ofensores, (
        f"rota POST sem `_require_admin` (corpo ou dependência) e sem motivo "
        f"escrito: {ofensores}. Ou acrescente a chamada, ou registre em "
        "_SEM_ADMIN_COM_MOTIVO com uma frase dizendo por que um gestor comum "
        "pode disparar."
    )
