"""get_my_rate_limit_status tem que reportar o cap que REALMENTE bloqueia.

Desde o F73 todo executor reserva contra duas chaves: o dev token global
(15.000) e `mgr:<uuid>` com `manager_daily_quota` (default 5.000). Como o
segundo e menor, e ele que barra primeiro — e o tool so lia o primeiro.
"""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.governance.rate_limit import Usage
from src.mcp.context import McpRequestContext
from src.mcp.tools.get_my_rate_limit_status import get_my_rate_limit_status


class _FakeConn:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False


class _FakePool:
    def acquire(self):
        return _FakeConn()


@pytest.mark.asyncio
async def test_reporta_o_cap_por_gestor_alem_da_quota_global() -> None:
    """Cenario real: gestor estourou o proprio cap e o global esta folgado.

    Antes, o tool respondia "5200/15000, 34.7%, restam 9800" enquanto TODAS
    as chamadas do gestor eram rejeitadas por QuotaExhausted. Ou seja, enganava
    exatamente no momento em que era consultado pra diagnosticar.
    """
    manager_id = uuid4()
    ctx = McpRequestContext(manager_id=manager_id, session_id=uuid4())

    async def _usage(_conn, chave, *, daily_limit):
        if chave.startswith("mgr:"):
            assert chave == f"mgr:{manager_id}", "cap tem que ser lido da chave do gestor"
            return Usage(used=5000, limit=daily_limit, pct=5000 / daily_limit)
        return Usage(used=5200, limit=daily_limit, pct=5200 / daily_limit)

    with (
        patch("src.mcp.tools.get_my_rate_limit_status.get_current", return_value=ctx),
        patch(
            "src.mcp.tools.get_my_rate_limit_status.connection.get_pool",
            return_value=_FakePool(),
        ),
        patch("src.mcp.tools.get_my_rate_limit_status.get_today_usage", side_effect=_usage),
        patch(
            "src.mcp.tools.get_my_rate_limit_status.audit_log.record",
            AsyncMock(return_value=None),
        ),
    ):
        r = await get_my_rate_limit_status({})

    # O bloco do gestor existe e traz o cap dele, nao o global.
    assert r["manager"]["used"] == 5000
    assert r["manager"]["limit"] == 5000
    assert r["manager"]["remaining"] == 0

    # O global segue reportado, com o nome dizendo de quem e.
    assert r["account"]["used"] == 5200
    assert r["account"]["limit"] == 15_000

    # E a resposta diz, sem o gestor ter que fazer a conta, quem esta barrando.
    assert r["blocking_scope"] == "manager"


@pytest.mark.asyncio
async def test_aponta_o_global_quando_e_ele_que_esgota_primeiro() -> None:
    """Se o cap do gestor for maior que a folga global, quem barra e o global."""
    ctx = McpRequestContext(manager_id=uuid4(), session_id=uuid4())

    async def _usage(_conn, chave, *, daily_limit):
        if chave.startswith("mgr:"):
            return Usage(used=10, limit=daily_limit, pct=10 / daily_limit)
        return Usage(used=14_999, limit=daily_limit, pct=14_999 / daily_limit)

    with (
        patch("src.mcp.tools.get_my_rate_limit_status.get_current", return_value=ctx),
        patch(
            "src.mcp.tools.get_my_rate_limit_status.connection.get_pool",
            return_value=_FakePool(),
        ),
        patch("src.mcp.tools.get_my_rate_limit_status.get_today_usage", side_effect=_usage),
        patch(
            "src.mcp.tools.get_my_rate_limit_status.audit_log.record",
            AsyncMock(return_value=None),
        ),
    ):
        r = await get_my_rate_limit_status({})

    assert r["account"]["remaining"] == 1
    assert r["manager"]["remaining"] == 4990
    assert r["blocking_scope"] == "account"
