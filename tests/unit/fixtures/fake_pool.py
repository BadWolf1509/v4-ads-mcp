"""Pool falso compartilhado pelos testes unitários.

`FakePool` substitui o `asyncpg.Pool`: `acquire()` devolve um async context
manager que entrega a conexão dada (ou um `MagicMock` novo, se nenhuma foi
dada) e conta quantas vezes foi chamado em `acquires`.

`patch_pool` troca `get_pool` (ou outro atributo) de um ou mais módulos por uma
função que devolve o pool — a forma dominante nos testes: `lambda: pool`.

Fica de fora, por testar comportamento próprio do pool: o fake de
`test_hot_reads_reconnect.py` (entrega conexões em sequência e conta acquires
para provar o fresh-acquire no retry), `test_db_connection.py`,
`test_health_resilience.py`, `test_pool_validado.py` e o `_Pool` de
`test_mutate_common.py` (que registra a ordem acquire/release).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest


class _Acquire:
    def __init__(self, conn: Any) -> None:
        self._conn = conn

    async def __aenter__(self) -> Any:
        return self._conn

    async def __aexit__(self, *exc: object) -> bool:
        return False


class FakePool:
    """`acquire()` entrega `conn` (um `MagicMock` quando omitida) e incrementa `acquires`."""

    def __init__(self, conn: Any = None) -> None:
        self.conn = MagicMock() if conn is None else conn
        self.acquires = 0

    def acquire(self) -> _Acquire:
        self.acquires += 1
        return _Acquire(self.conn)


def patch_pool(monkeypatch: pytest.MonkeyPatch, pool: Any, *alvos: str) -> None:
    """Faz cada `alvo` ("modulo.atributo", ex. "src.db.connection.get_pool") devolver `pool`."""
    for alvo in alvos:
        monkeypatch.setattr(alvo, lambda *_a, **_k: pool)
