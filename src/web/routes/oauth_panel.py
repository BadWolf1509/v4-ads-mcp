"""Telas de conexão OAuth do painel — reservado pela tabela de módulos da Task 2.

Vazio por medição, não por preguiça: as 42 rotas de `routes.py` (26 GET + 16
POST, confirmado por grep e batendo com o `docs/superpowers/plans/2026-09-17-
pr5-painel.md`) não incluem nenhuma tela de conexão OAuth. As duas páginas
HTML completas de OAuth do painel (fluxo Meta) vivem em `src/auth/oauth.py:394`
e `:409` — um arquivo fora do escopo desta tarefa, que já é citado à parte no
mesmo plano (seção "O que a medição corrigiu na spec") como alvo da Task 8, não
da Task 2. Este módulo fica registrado (router vazio, `include_router` vira
no-op) para não divergir da estrutura de dez módulos do brief; ver o relatório
da Task 2 para a discrepância completa.
"""

from fastapi import APIRouter

router = APIRouter(tags=["web"])
