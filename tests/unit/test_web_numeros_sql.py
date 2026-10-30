"""`contagem_por_dia`: o filtro de gestor tem que ser SARGAVEL.

`($3::uuid IS NULL OR manager_id = $3)` impede o planner de usar
`idx_audit_manager_time (manager_id, occurred_at)`: o predicado vira filtro. Sao
duas queries, e a de gestor leva `manager_id = $3` direto.
"""

from datetime import date
from typing import Any
from uuid import uuid4

import pytest

from src.web import numeros


class _Conn:
    def __init__(self) -> None:
        self.chamadas: list[tuple[str, tuple[Any, ...]]] = []

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        self.chamadas.append((query, args))
        return []


@pytest.mark.asyncio
async def test_com_gestor_o_predicado_e_igualdade_direta() -> None:
    conn = _Conn()
    mid = uuid4()
    await numeros.contagem_por_dia(conn, [date(2026, 10, 30)], manager_id=mid)  # type: ignore[arg-type]
    query, args = conn.chamadas[0]
    assert "manager_id = $3" in query
    assert "IS NULL" not in query
    assert args[2] == mid


@pytest.mark.asyncio
async def test_sem_gestor_nao_filtra_por_gestor() -> None:
    conn = _Conn()
    await numeros.contagem_por_dia(conn, [date(2026, 10, 30)])  # type: ignore[arg-type]
    query, args = conn.chamadas[0]
    assert "manager_id" not in query
    assert len(args) == 2
