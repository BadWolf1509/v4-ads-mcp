"""Rotas do painel, por responsabilidade.

Era um arquivo de 1839 linhas. O `router` agregado continua importável do mesmo
lugar (`from src.web.routes import router`), então nenhum call-site externo
mudou — o split é interno ao pacote.

A ordem de inclusão importa em UM ponto: rotas com caminho literal têm que ser
registradas antes de rotas com parâmetro que possam casá-las (`/admin/access`
antes de `/admin/{secao}`, se existir). A tabela fixada em
`tests/unit/test_tabela_de_rotas_e_estavel.py` pega qualquer troca de ordem que
mude o casamento.
"""

from fastapi import APIRouter

from src.web.routes import (
    accounts,
    admin_access,
    admin_accounts,
    admin_audit,
    admin_invites,
    admin_overview,
    audit,
    oauth_panel,
    sessions,
)

router = APIRouter()

for _modulo in (
    sessions,
    accounts,
    audit,
    admin_overview,
    admin_accounts,
    admin_access,
    admin_invites,
    admin_audit,
    oauth_panel,
):
    router.include_router(_modulo.router)

__all__ = ["router"]
