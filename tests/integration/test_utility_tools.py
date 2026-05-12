"""Tests for utility tools — run_gaql, validate_gaql, list_gaql_resources."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.mcp.context import McpRequestContext, clear_current, set_current


@pytest.fixture
def bound_context():
    ctx = McpRequestContext(manager_id=uuid4(), session_id=uuid4())
    set_current(ctx)
    yield ctx
    clear_current()


@pytest.mark.asyncio
async def test_run_gaql_returns_rows_and_truncation_flag(bound_context):
    from src.mcp.tools.run_gaql import run_gaql

    fake_rows = [{"customer.id": str(i)} for i in range(50)]
    with patch(
        "src.mcp.tools.run_gaql.execute_gaql_raw",
        AsyncMock(return_value=fake_rows),
    ):
        result = await run_gaql(
            {
                "customer_id": "1234567890",
                "query": "SELECT customer.id FROM customer",
            }
        )
    assert result["row_count"] == 50
    assert result["truncated"] is False
    assert len(result["rows"]) == 50


@pytest.mark.asyncio
async def test_run_gaql_truncates_above_1000(bound_context):
    from src.mcp.tools.run_gaql import run_gaql

    fake_rows = [{"customer.id": str(i)} for i in range(1500)]
    with patch(
        "src.mcp.tools.run_gaql.execute_gaql_raw",
        AsyncMock(return_value=fake_rows),
    ):
        result = await run_gaql(
            {
                "customer_id": "1234567890",
                "query": "SELECT customer.id FROM customer",
            }
        )
    assert result["row_count"] == 1500
    assert result["truncated"] is True
    assert len(result["rows"]) == 1000


@pytest.mark.asyncio
async def test_validate_gaql_returns_valid_when_no_error(bound_context):
    from src.mcp.tools.validate_gaql import validate_gaql

    fake_client = MagicMock()
    fake_client.get_type = MagicMock(return_value=MagicMock())
    fake_service = MagicMock()
    fake_service.search = MagicMock(return_value=iter([]))
    fake_client.get_service = MagicMock(return_value=fake_service)

    with patch(
        "src.mcp.tools.validate_gaql.build_client_for_manager",
        AsyncMock(return_value=fake_client),
    ):
        result = await validate_gaql(
            {
                "customer_id": "1234567890",
                "query": "SELECT customer.id FROM customer",
            }
        )
    assert result["valid"] is True
    assert result["error"] is None


@pytest.mark.asyncio
async def test_validate_gaql_returns_invalid_with_error(bound_context):
    from src.mcp.tools.validate_gaql import validate_gaql

    fake_client = MagicMock()
    fake_client.get_type = MagicMock(return_value=MagicMock())
    fake_service = MagicMock()
    fake_service.search = MagicMock(side_effect=Exception("Bad GAQL"))
    fake_client.get_service = MagicMock(return_value=fake_service)

    with patch(
        "src.mcp.tools.validate_gaql.build_client_for_manager",
        AsyncMock(return_value=fake_client),
    ):
        result = await validate_gaql(
            {
                "customer_id": "1234567890",
                "query": "SELECT bad FROM nothing",
            }
        )
    assert result["valid"] is False
    assert result["error"] is not None


@pytest.mark.asyncio
async def test_list_gaql_resources_returns_catalog():
    from src.mcp.tools.list_gaql_resources import list_gaql_resources

    result = await list_gaql_resources({})
    assert "resources" in result
    assert "segments" in result
    assert len(result["resources"]) >= 15
    # Sanity: every resource has a name + description + fields
    for r in result["resources"]:
        assert "name" in r
        assert "description" in r
        assert "fields" in r
        assert isinstance(r["fields"], list)
        assert len(r["fields"]) > 0
    # Common resources must be present
    names = {r["name"] for r in result["resources"]}
    assert "campaign" in names
    assert "keyword_view" in names
    assert "search_term_view" in names
