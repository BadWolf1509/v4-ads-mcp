"""Árvore sintética SEM a violação. Nenhum guard pode acusar este arquivo."""

from src.db.connection import _DROPPED_CONNECTION_ERRORS


def leitura_protegida() -> None:
    try:
        pass
    except _DROPPED_CONNECTION_ERRORS:
        pass
