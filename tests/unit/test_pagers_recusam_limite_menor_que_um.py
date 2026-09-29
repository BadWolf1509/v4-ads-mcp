"""Os pagers keyset do audit recusam `limit < 1` na entrada (spec 2026-09-28 §3.2.3).

Com `limit=0` e uma linha no filtro, a consulta interna (`LIMIT limit + 1`) devolve uma
linha, a página fica vazia, `len(fetched) > limit` é verdadeiro e o `page[-1]` estoura
`IndexError`. As rotas fixam 50 hoje; a função pública não impedia o próximo chamador.
A recusa vem ANTES de tocar no banco — a conexão abaixo explode se for usada.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from src.db.repositories import audit_log


class _ConexaoIntocavel:
    def __getattr__(self, nome: str) -> Any:
        raise AssertionError(f"a recusa tinha de vir antes do banco; usou conn.{nome}")


@pytest.mark.parametrize("limit", [0, -1])
async def test_pagina_do_gestor_recusa_limite_menor_que_um(limit: int) -> None:
    with pytest.raises(ValueError, match="limit"):
        await audit_log.list_page_for_manager(
            _ConexaoIntocavel(),  # type: ignore[arg-type]
            manager_id=uuid4(),
            limit=limit,
        )


@pytest.mark.parametrize("limit", [0, -1])
async def test_pagina_do_admin_recusa_limite_menor_que_um(limit: int) -> None:
    with pytest.raises(ValueError, match="limit"):
        await audit_log.list_page_admin(_ConexaoIntocavel(), limit=limit)  # type: ignore[arg-type]
