"""Integration tests for meta_list_my_ad_accounts tool (Sprint M.2a Task 9)."""

from uuid import uuid4

import pytest

from src.db.repositories import (
    manager_meta_account_access,
    managers,
    meta_ad_accounts,
)
from src.mcp.context import McpRequestContext, set_current
from src.mcp.tools._registry import get_tool, import_all_tools


@pytest.fixture(autouse=True)
def _tools_registered(db):
    """Este arquivo é o único que resolve tools via get_tool() — o registry
    module-level só é populado por import_all_tools() (idempotente: módulos
    já importados vêm do cache do Python), que o `db` genérico do conftest
    não chama.
    """
    import_all_tools()


@pytest.mark.integration
async def test_full_pipeline(db):
    """Manager + ad accounts + grants → tool returns sorted list."""
    async with db.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="t@v4.com", full_name=None)
        await meta_ad_accounts.upsert_many(
            conn,
            [
                {
                    "ad_account_id": "act_222",
                    "business_id": "bm_X",
                    "account_name": "Beta",
                    "currency": "BRL",
                    "timezone_name": "America/Sao_Paulo",
                    "account_status": 1,
                },
                {
                    "ad_account_id": "act_111",
                    "business_id": "bm_X",
                    "account_name": "Alpha",
                    "currency": "BRL",
                    "timezone_name": "America/Sao_Paulo",
                    "account_status": 1,
                },
            ],
        )
        await manager_meta_account_access.grant(conn, manager_id=mid, ad_account_id="act_111")
        await manager_meta_account_access.grant(conn, manager_id=mid, ad_account_id="act_222")

    set_current(McpRequestContext(manager_id=mid, session_id=uuid4()))
    tool = get_tool("meta_list_my_ad_accounts")
    assert tool is not None
    result = await tool.handler({})
    assert result["total"] == 2
    assert [a["account_name"] for a in result["ad_accounts"]] == ["Alpha", "Beta"]


@pytest.mark.integration
async def test_account_status_label_translation(db):
    """account_status int → PT-BR label."""
    async with db.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="l@v4.com", full_name=None)
        await meta_ad_accounts.upsert_many(
            conn,
            [
                {
                    "ad_account_id": "act_a1",
                    "account_name": "Ativa",
                    "account_status": 1,
                },
                {
                    "ad_account_id": "act_d2",
                    "account_name": "Disabled",
                    "account_status": 2,
                },
                {
                    "ad_account_id": "act_u3",
                    "account_name": "Unknown",
                    "account_status": 999,
                },
            ],
        )
        await manager_meta_account_access.grant(conn, manager_id=mid, ad_account_id="act_a1")
        await manager_meta_account_access.grant(conn, manager_id=mid, ad_account_id="act_d2")
        await manager_meta_account_access.grant(conn, manager_id=mid, ad_account_id="act_u3")

    set_current(McpRequestContext(manager_id=mid, session_id=uuid4()))
    tool = get_tool("meta_list_my_ad_accounts")
    result = await tool.handler({})
    labels = {a["account_name"]: a["account_status_label"] for a in result["ad_accounts"]}
    assert labels["Ativa"] == "ATIVO"
    assert labels["Disabled"] == "DESABILITADO"
    assert labels["Unknown"] == "DESCONHECIDO"


@pytest.mark.integration
async def test_empty_when_no_grants(db):
    """Manager sem grants → lista vazia."""
    async with db.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="e@v4.com", full_name=None)

    set_current(McpRequestContext(manager_id=mid, session_id=uuid4()))
    tool = get_tool("meta_list_my_ad_accounts")
    result = await tool.handler({})
    assert result["total"] == 0
    assert result["ad_accounts"] == []


@pytest.mark.integration
async def test_isolation_per_manager(db):
    """Manager A vê só act_a; Manager B vê só act_b."""
    async with db.acquire() as conn:
        ma = uuid4()
        mb = uuid4()
        await managers.create(conn, manager_id=ma, email="a@v4.com", full_name=None)
        await managers.create(conn, manager_id=mb, email="b@v4.com", full_name=None)
        await meta_ad_accounts.upsert_many(
            conn,
            [
                {"ad_account_id": "act_only_a", "account_name": "A's Account"},
                {"ad_account_id": "act_only_b", "account_name": "B's Account"},
            ],
        )
        await manager_meta_account_access.grant(conn, manager_id=ma, ad_account_id="act_only_a")
        await manager_meta_account_access.grant(conn, manager_id=mb, ad_account_id="act_only_b")

    set_current(McpRequestContext(manager_id=ma, session_id=uuid4()))
    tool = get_tool("meta_list_my_ad_accounts")
    result_a = await tool.handler({})
    assert {a["ad_account_id"] for a in result_a["ad_accounts"]} == {"act_only_a"}

    set_current(McpRequestContext(manager_id=mb, session_id=uuid4()))
    result_b = await tool.handler({})
    assert {a["ad_account_id"] for a in result_b["ad_accounts"]} == {"act_only_b"}
