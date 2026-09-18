"""Rotas do painel, por responsabilidade.

Era um arquivo de 1839 linhas. O `router` agregado continua importável do mesmo
lugar (`from src.web.routes import router`), então nenhum call-site externo
mudou — o split é interno ao pacote. Oito módulos de rota mais `_shared.py`
pros helpers comuns (`oauth_panel.py` saiu na rodada 1 da Task 2: zero das 42
rotas de `routes.py` era tela de conexão OAuth — as duas páginas OAuth do
painel vivem em `src/auth/oauth.py`, fora do escopo deste split; ver o
relatório da Task 2 pra medição completa).

A ordem de inclusão importa em UM ponto: rotas com caminho literal têm que ser
registradas antes de rotas com parâmetro que possam casá-las (`/admin/access`
antes de `/admin/{secao}`, se existir).
`test_pares_sombreados_tem_literal_antes_do_parametrico`, em
`tests/unit/test_tabela_de_rotas_e_estavel.py`, pega qualquer troca de ordem
que mude o casamento nos pares conhecidos — ao contrário do teste de
snapshot no mesmo arquivo, que ordena por path e por isso NÃO vê ordem.
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
):
    router.include_router(_modulo.router)

__all__ = ["router"]
