"""Árvore sintética COM a violação, uma de cada classe que o harness precisa
enxergar. Serve de alvo positivo para os testes do harness — nenhum guard de
produção varre este diretório."""

import asyncpg
from asyncpg import PostgresConnectionError as PCE


def repete_a_tupla_literal() -> None:
    try:
        pass
    except asyncpg.ConnectionDoesNotExistError:  # subclasse: o guard tem que ver
        pass


def usa_alias_de_import() -> None:
    try:
        pass
    except PCE:  # alias: o guard tem que ver
        pass


def chama_por_alias() -> None:
    from src.google_ads.client import build_client_for_manager as construir

    construir()
