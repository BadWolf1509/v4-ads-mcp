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


@pytest.fixture
def bypass_gate():
    """validate_gaql roda ensure_account_access (hard-gate) antes de buildar o
    client, e (Task 1.3) rate-limit reserved + audit_log.record em volta do
    search(). Estes testes exercitam a lógica pós-gate/pós-rate-limit, então
    os stubs viram no-op. (Convenção pré-flight: patch no namespace do TOOL,
    não em access/_common/reports.)

    fake_conn.transaction() precisa ser um async context manager de verdade
    (padrão 'reserved' de reports.py: `async with pool.acquire() as conn,
    conn.transaction():`), não um MagicMock puro.
    """
    fake_conn = AsyncMock()
    fake_txn_cm = MagicMock()
    fake_txn_cm.__aenter__ = AsyncMock(return_value=None)
    fake_txn_cm.__aexit__ = AsyncMock(return_value=None)
    fake_conn.transaction = MagicMock(return_value=fake_txn_cm)

    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=fake_conn)
    cm.__aexit__ = AsyncMock(return_value=False)
    fake_pool = MagicMock()
    fake_pool.acquire = MagicMock(return_value=cm)
    with (
        patch("src.mcp.tools.validate_gaql.connection.get_pool", return_value=fake_pool),
        patch(
            "src.mcp.tools.validate_gaql.ensure_account_access",
            AsyncMock(return_value=None),
        ),
        patch("src.mcp.tools.validate_gaql.before_call", AsyncMock(return_value=None)),
        patch("src.mcp.tools.validate_gaql.record_actual", AsyncMock(return_value=None)),
        patch("src.mcp.tools.validate_gaql.audit_log.record", AsyncMock(return_value=1)),
    ):
        yield


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
    """limit explicito no teto (1000) -> 1500 rows corta em 1000."""
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
                "limit": 1000,
            }
        )
    assert result["row_count"] == 1500
    assert result["truncated"] is True
    assert len(result["rows"]) == 1000
    assert result["returned"] == 1000
    assert "hint" in result


@pytest.mark.asyncio
async def test_run_gaql_default_limit_is_100_when_absent(bound_context):
    """Sem `limit` no args -> default 100 (nao mais o teto de 1000 - F2/F22)."""
    from src.mcp.tools.run_gaql import run_gaql

    fake_rows = [{"customer.id": str(i)} for i in range(150)]
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
    assert result["row_count"] == 150
    assert result["truncated"] is True
    assert len(result["rows"]) == 100
    assert result["returned"] == 100
    assert "hint" in result


@pytest.mark.asyncio
async def test_run_gaql_custom_limit_truncates(bound_context):
    """limit customizado (10) corta corretamente + shape truncated true."""
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
                "limit": 10,
            }
        )
    assert result["row_count"] == 50
    assert result["truncated"] is True
    assert len(result["rows"]) == 10
    assert result["returned"] == 10
    assert "limit maior" in result["hint"] or "1000" in result["hint"]


@pytest.mark.asyncio
async def test_run_gaql_limit_equal_to_row_count_not_truncated(bound_context):
    """rows == limit -> truncated false (shape estavel, sem hint)."""
    from src.mcp.tools.run_gaql import run_gaql

    fake_rows = [{"customer.id": str(i)} for i in range(10)]
    with patch(
        "src.mcp.tools.run_gaql.execute_gaql_raw",
        AsyncMock(return_value=fake_rows),
    ):
        result = await run_gaql(
            {
                "customer_id": "1234567890",
                "query": "SELECT customer.id FROM customer",
                "limit": 10,
            }
        )
    assert result["row_count"] == 10
    assert result["truncated"] is False
    assert len(result["rows"]) == 10
    assert result["returned"] == 10


@pytest.mark.asyncio
async def test_run_gaql_limit_clamped_above_max(bound_context):
    """limit acima de 1000 (defensivo, mesmo com schema maximum) clampa a 1000."""
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
                "limit": 5000,
            }
        )
    assert len(result["rows"]) == 1000
    assert result["returned"] == 1000
    assert result["truncated"] is True


@pytest.mark.asyncio
async def test_run_gaql_passes_query_and_limit_to_execute_gaql_raw(bound_context):
    """execute_gaql_raw recebe limit (pra montar params_summary do audit)."""
    from src.mcp.tools.run_gaql import run_gaql

    fake_execute = AsyncMock(return_value=[{"customer.id": "1"}])
    with patch("src.mcp.tools.run_gaql.execute_gaql_raw", fake_execute):
        await run_gaql(
            {
                "customer_id": "1234567890",
                "query": "SELECT customer.id FROM customer",
                "limit": 42,
            }
        )
    fake_execute.assert_awaited_once()
    call_kwargs = fake_execute.call_args.kwargs
    assert call_kwargs["query"] == "SELECT customer.id FROM customer"
    assert call_kwargs["limit"] == 42


@pytest.mark.asyncio
async def test_validate_gaql_returns_valid_when_no_error(bound_context, bypass_gate):
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
async def test_validate_gaql_returns_invalid_with_error(bound_context, bypass_gate):
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
async def test_validate_gaql_appends_b2_hint_for_change_event_window(bound_context, bypass_gate):
    """B2: error 'too old' on FROM change_event query should append window hint."""
    from src.google_ads.errors import GoogleAdsFriendlyError
    from src.mcp.tools.validate_gaql import validate_gaql

    fake_client = MagicMock()
    fake_client.get_type = MagicMock(return_value=MagicMock())
    fake_service = MagicMock()
    fake_service.search = MagicMock(side_effect=Exception("simulated"))
    fake_client.get_service = MagicMock(return_value=fake_service)

    friendly = GoogleAdsFriendlyError(
        "Google Ads retornou: The requested start date is too old. It cannot be older than 30 days.",
        code="QUERY_ERROR",
    )

    with (
        patch(
            "src.mcp.tools.validate_gaql.build_client_for_manager",
            AsyncMock(return_value=fake_client),
        ),
        patch("src.mcp.tools.validate_gaql.to_friendly", return_value=friendly),
    ):
        result = await validate_gaql(
            {
                "customer_id": "1234567890",
                "query": (
                    "SELECT change_event.change_date_time, change_event.user_email "
                    "FROM change_event WHERE change_event.change_date_time DURING LAST_30_DAYS"
                ),
            }
        )

    assert result["valid"] is False
    assert "change_event tem janela" in result["error"].lower() or "30 dias" in result["error"]
    assert "LAST_14_DAYS" in result["error"]


@pytest.mark.asyncio
async def test_validate_gaql_appends_b3_hint_for_conversion_action_cost_micros(
    bound_context, bypass_gate
):
    """B3: 'unsupported metric' with segments.conversion_action + cost_micros should append split-query hint."""
    from src.google_ads.errors import GoogleAdsFriendlyError
    from src.mcp.tools.validate_gaql import validate_gaql

    fake_client = MagicMock()
    fake_client.get_type = MagicMock(return_value=MagicMock())
    fake_service = MagicMock()
    fake_service.search = MagicMock(side_effect=Exception("simulated"))
    fake_client.get_service = MagicMock(return_value=fake_service)

    friendly = GoogleAdsFriendlyError(
        "Cannot select the following segments because at least one unsupported metric is "
        "found in SELECT or WHERE clause: 'segments.conversion_action' "
        "(unsupported metrics: 'cost_micros').",
        code="QUERY_ERROR",
    )

    with (
        patch(
            "src.mcp.tools.validate_gaql.build_client_for_manager",
            AsyncMock(return_value=fake_client),
        ),
        patch("src.mcp.tools.validate_gaql.to_friendly", return_value=friendly),
    ):
        result = await validate_gaql(
            {
                "customer_id": "1234567890",
                "query": (
                    "SELECT segments.conversion_action, metrics.conversions, "
                    "metrics.cost_micros FROM campaign WHERE campaign.id IN (123)"
                ),
            }
        )

    assert result["valid"] is False
    assert "2 queries" in result["error"].lower()
    assert "cost_micros" in result["error"].lower()


@pytest.mark.asyncio
async def test_validate_gaql_denies_without_access(bound_context):
    """Hard-gate (F57 class): sem grant, validate_gaql levanta
    AccountAccessDeniedError e NUNCA chega a buildar o client — não vaza
    existência/schema da conta nem bypassa o rate-limit."""
    from src.google_ads.access import AccountAccessDeniedError
    from src.mcp.tools.validate_gaql import validate_gaql

    fake_conn = MagicMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=fake_conn)
    cm.__aexit__ = AsyncMock(return_value=False)
    fake_pool = MagicMock()
    fake_pool.acquire = MagicMock(return_value=cm)

    build_spy = AsyncMock()
    with (
        patch("src.mcp.tools.validate_gaql.connection.get_pool", return_value=fake_pool),
        patch(
            "src.mcp.tools.validate_gaql.ensure_account_access",
            AsyncMock(side_effect=AccountAccessDeniedError("sem acesso")),
        ),
        patch("src.mcp.tools.validate_gaql.build_client_for_manager", build_spy),
        pytest.raises(AccountAccessDeniedError),
    ):
        await validate_gaql(
            {
                "customer_id": "1234567890",
                "query": "SELECT customer.id FROM customer",
            }
        )
    build_spy.assert_not_awaited()  # gate bloqueou antes de tocar o client


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


@pytest.mark.asyncio
async def test_run_gaql_without_aggregate_by_returns_rows_unchanged(bound_context):
    """Regression: shape original mantido quando aggregate_by ausente."""
    from src.mcp.tools.run_gaql import run_gaql

    fake_rows = [{"campaign": {"id": "123"}}, {"campaign": {"id": "456"}}]

    with patch(
        "src.mcp.tools.run_gaql.execute_gaql_raw",
        AsyncMock(return_value=fake_rows),
    ):
        result = await run_gaql(
            {
                "customer_id": "1234567890",
                "query": "SELECT campaign.id FROM campaign",
            }
        )

    assert result["row_count"] == 2
    assert result["truncated"] is False
    assert "rows" in result
    assert "groups" not in result


@pytest.mark.asyncio
async def test_run_gaql_with_aggregate_by_returns_groups_shape(bound_context):
    """aggregate_by ativo retorna groups[] + metadata, sem rows[]."""
    from src.mcp.tools.run_gaql import run_gaql

    fake_rows = [
        {"field_type": "SITELINK"},
        {"field_type": "STRUCTURED_SNIPPET"},
        {"field_type": "STRUCTURED_SNIPPET"},
        {"field_type": "SITELINK"},
        {"field_type": "STRUCTURED_SNIPPET"},
    ]

    with patch(
        "src.mcp.tools.run_gaql.execute_gaql_raw",
        AsyncMock(return_value=fake_rows),
    ):
        result = await run_gaql(
            {
                "customer_id": "1234567890",
                "query": "SELECT campaign_asset.field_type FROM campaign_asset",
                "aggregate_by": ["field_type"],
            }
        )

    assert "rows" not in result
    assert result["total_rows_scanned"] == 5
    assert result["group_count"] == 2
    assert result["truncated"] is False
    assert result["groups"] == [
        {"key": {"field_type": "STRUCTURED_SNIPPET"}, "count": 3},
        {"key": {"field_type": "SITELINK"}, "count": 2},
    ]


@pytest.mark.asyncio
async def test_run_gaql_aggregate_truncates_at_1000_groups(bound_context):
    """1500 grupos unicos -> truncado a 1000 com truncated:true.

    Tambem valida fix A2.1: group_count reporta 1500 (pre-slice), nao 1000.
    """
    from src.mcp.tools.run_gaql import run_gaql

    # Generate 1500 unique field values
    fake_rows = [{"x": f"val_{i}"} for i in range(1500)]

    with patch(
        "src.mcp.tools.run_gaql.execute_gaql_raw",
        AsyncMock(return_value=fake_rows),
    ):
        result = await run_gaql(
            {
                "customer_id": "1234567890",
                "query": "SELECT x FROM something",
                "aggregate_by": ["x"],
            }
        )

    assert result["total_rows_scanned"] == 1500
    assert len(result["groups"]) == 1000
    assert result["group_count"] == 1500  # regression guard pra fix A2.1
    assert result["truncated"] is True


@pytest.mark.asyncio
async def test_run_gaql_rejects_more_than_10k_raw_rows(bound_context):
    """Safety net hard: >10k raw rows com aggregate_by raises ValueError."""
    from src.mcp.tools.run_gaql import run_gaql

    fake_rows = [{"x": "val"} for _ in range(10_001)]

    with (
        patch(
            "src.mcp.tools.run_gaql.execute_gaql_raw",
            AsyncMock(return_value=fake_rows),
        ),
        pytest.raises(ValueError, match=r"(?i)refine WHERE clause"),
    ):
        await run_gaql(
            {
                "customer_id": "1234567890",
                "query": "SELECT x FROM something",
                "aggregate_by": ["x"],
            }
        )
