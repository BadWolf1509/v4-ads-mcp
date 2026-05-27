"""Integration tests for update_keyword_status (Sprint 3b.40 A1).

A1: DRY_RUN path (>5 keywords) inclui sample_keywords (top 5).
AUTO_APPLY path (<=5 keywords) NÃO inclui sample_keywords (sem preview).
"""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from testcontainers.postgres import PostgresContainer

from src.db import connection, migrate
from src.mcp.context import McpRequestContext, clear_current, set_current

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def pg() -> PostgresContainer:
    with PostgresContainer("postgres:16-alpine") as container:
        yield container


@pytest.fixture
async def db(pg: PostgresContainer):
    dsn = pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
    await connection.init_pool(dsn, min_size=1, max_size=4)
    try:
        await migrate.run_all()
        yield connection.get_pool()
    finally:
        await connection.close_pool()


@pytest.fixture
def bound_context():
    ctx = McpRequestContext(manager_id=uuid4(), session_id=uuid4())
    set_current(ctx)
    yield ctx
    clear_current()


@pytest.mark.integration
async def test_a1_dry_run_with_more_than_5_keywords_includes_sample_top_5(
    db, bound_context
):
    """A1: 6 keywords → CONFIRM path → response inclui sample_keywords top 5 + sample_truncated=true."""
    from src.mcp.tools.update_keyword_status import update_keyword_status

    keywords = [{"ad_group_id": "1001", "criterion_id": str(i)} for i in range(1, 7)]

    fake_lookup = {
        ("1001", str(i)): {
            "keyword_text": f"keyword #{i}",
            "match_type": "BROAD",
        }
        for i in range(1, 7)
    }

    with (
        patch(
            "src.mcp.tools.update_keyword_status.validate_keyword_criterion_types",
            AsyncMock(return_value=None),  # pre-flight passa
        ),
        patch(
            "src.mcp.tools.update_keyword_status.fetch_keyword_texts",
            AsyncMock(return_value=fake_lookup),
        ),
    ):
        result = await update_keyword_status(
            {
                "customer_id": "1234567890",
                "keywords": keywords,
                "new_status": "PAUSED",
            }
        )

    assert result["status"] == "dry_run"
    assert "sample_keywords" in result
    assert len(result["sample_keywords"]) == 5  # top 5 fixo V0
    assert result["sample_truncated"] is True
    # Top 5 = primeiros 5 da lista caller (preserva intent caller-defined)
    assert result["sample_keywords"][0]["criterion_id"] == "1"
    assert result["sample_keywords"][0]["keyword_text"] == "keyword #1"
    assert result["sample_keywords"][0]["match_type"] == "BROAD"
    assert result["sample_keywords"][4]["criterion_id"] == "5"
    assert "confirmation_token" in result


@pytest.mark.integration
async def test_a1_auto_apply_with_5_or_fewer_keywords_omits_sample(db, bound_context):
    """A1: 3 keywords (≤5) → AUTO path → response NÃO contém sample_keywords."""
    from src.mcp.tools.update_keyword_status import update_keyword_status

    keywords = [{"ad_group_id": "1001", "criterion_id": str(i)} for i in range(1, 4)]

    fake_run_mutation = AsyncMock(
        return_value={"applied_count": 3, "provider_request_id": "fake-trace-id"}
    )

    with (
        patch(
            "src.mcp.tools.update_keyword_status.validate_keyword_criterion_types",
            AsyncMock(return_value=None),
        ),
        patch(
            "src.mcp.tools.update_keyword_status.run_mutation",
            fake_run_mutation,
        ),
    ):
        result = await update_keyword_status(
            {
                "customer_id": "1234567890",
                "keywords": keywords,
                "new_status": "PAUSED",
            }
        )

    assert result["status"] == "applied"
    assert "sample_keywords" not in result
    assert result["applied_count"] == 3


@pytest.mark.integration
async def test_a1_dry_run_with_partial_fetch_returns_none_for_missing(db, bound_context):
    """A1 edge: fetch retorna partial → sample_keywords contains None pra missing IDs."""
    from src.mcp.tools.update_keyword_status import update_keyword_status

    keywords = [{"ad_group_id": "1001", "criterion_id": str(i)} for i in range(1, 7)]

    # Fetch retorna apenas IDs 1, 2, 3 (4, 5, 6 missing)
    fake_lookup_partial = {
        ("1001", str(i)): {
            "keyword_text": f"keyword #{i}",
            "match_type": "BROAD",
        }
        for i in range(1, 4)
    }

    with (
        patch(
            "src.mcp.tools.update_keyword_status.validate_keyword_criterion_types",
            AsyncMock(return_value=None),
        ),
        patch(
            "src.mcp.tools.update_keyword_status.fetch_keyword_texts",
            AsyncMock(return_value=fake_lookup_partial),
        ),
    ):
        result = await update_keyword_status(
            {
                "customer_id": "1234567890",
                "keywords": keywords,
                "new_status": "PAUSED",
            }
        )

    assert result["status"] == "dry_run"
    assert len(result["sample_keywords"]) == 5
    # IDs 1, 2, 3 resolved
    assert result["sample_keywords"][0]["keyword_text"] == "keyword #1"
    assert result["sample_keywords"][2]["keyword_text"] == "keyword #3"
    # IDs 4, 5 missing → keyword_text/match_type = None, but ids preserved
    assert result["sample_keywords"][3]["keyword_text"] is None
    assert result["sample_keywords"][3]["match_type"] is None
    assert result["sample_keywords"][3]["criterion_id"] == "4"
    assert result["sample_keywords"][4]["keyword_text"] is None
    assert result["sample_keywords"][4]["criterion_id"] == "5"
