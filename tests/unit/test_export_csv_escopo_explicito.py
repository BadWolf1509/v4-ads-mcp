"""O escopo do export CSV do audit e explicito: sem `manager_id`, a chamada falha.

Ate 04/11 `manager_id` tinha default `None`, e `None` quer dizer "todos os gestores" —
o export global do admin. Uma chamada que esquecesse o argumento exportava o audit da
unidade inteira em silencio (falha aberta). As duas rotas sempre passaram o gestor;
o risco era o proximo chamador. Agora o argumento e obrigatorio e `None` so vale
quando quem chama o escreve.
"""

from typing import Any

import pytest

from src.db.repositories import audit_log


def test_export_sem_manager_id_falha_na_chamada() -> None:
    conn: Any = object()
    with pytest.raises(TypeError, match="manager_id"):
        audit_log.export_csv_rows(conn, days=7)  # type: ignore[call-arg]


def test_export_global_continua_possivel_quando_escrito() -> None:
    conn: Any = object()
    gerador = audit_log.export_csv_rows(conn, manager_id=None, days=7)
    assert hasattr(gerador, "__anext__")
