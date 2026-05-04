"""Verify all registered MCP tools have valid JSON Schema and consistent shape."""

import jsonschema
import pytest

from src.mcp.tools._registry import all_tools, import_all_tools


@pytest.fixture(scope="module", autouse=True)
def _load_tools():
    import_all_tools()


def test_every_tool_has_valid_schema():
    for tool in all_tools():
        # Will raise if invalid schema
        jsonschema.Draft202012Validator.check_schema(tool.input_schema)


def test_customer_id_pattern_is_consistent():
    """Every tool that has a customer_id field must use the same pattern."""
    for tool in all_tools():
        props = tool.input_schema.get("properties", {})
        if "customer_id" in props:
            cid = props["customer_id"]
            assert cid.get("pattern") == "^[0-9]{10}$", (
                f"{tool.name} has wrong customer_id pattern: {cid.get('pattern')}"
            )


def test_all_phase_2_tools_registered():
    """All 25 tools (20 Phase 2 + 3 campaign mutations + 2 ad group mutations) registered."""
    expected = {
        "apply_change",
        "list_my_accounts",
        # visao geral
        "get_account_overview",
        "get_budget_pacing",
        "get_recommendations",
        # performance
        "get_campaign_performance",
        "get_ad_group_performance",
        "get_device_performance",
        "get_geo_performance",
        "get_hourly_performance",
        # tactical
        "get_keyword_performance",
        "get_search_terms_report",
        "get_negative_keywords_audit",
        "get_ad_performance",
        "get_audience_performance",
        "get_conversion_actions",
        # client report
        "get_funnel_metrics",
        "get_top_keywords_creatives",
        # utilities
        "run_gaql",
        "validate_gaql",
        "list_gaql_resources",
        # campaign mutations
        "update_campaign_bidding",
        "update_campaign_budget",
        "update_campaign_status",
        # ad group mutations
        "update_ad_group_bid",
        "update_ad_group_status",
    }
    actual = {t.name for t in all_tools()}
    missing = expected - actual
    assert not missing, f"Missing tools: {missing}"


def test_no_unexpected_tools():
    """Catch accidental new tool registrations not in the expected set."""
    expected = {
        "apply_change",
        "list_my_accounts",
        "get_account_overview",
        "get_budget_pacing",
        "get_recommendations",
        "get_campaign_performance",
        "get_ad_group_performance",
        "get_device_performance",
        "get_geo_performance",
        "get_hourly_performance",
        "get_keyword_performance",
        "get_search_terms_report",
        "get_negative_keywords_audit",
        "get_ad_performance",
        "get_audience_performance",
        "get_conversion_actions",
        "get_funnel_metrics",
        "get_top_keywords_creatives",
        "run_gaql",
        "validate_gaql",
        "list_gaql_resources",
        "update_campaign_bidding",
        "update_campaign_budget",
        "update_campaign_status",
        "update_ad_group_bid",
        "update_ad_group_status",
    }
    actual = {t.name for t in all_tools()}
    unexpected = actual - expected
    assert not unexpected, f"Unexpected tools: {unexpected}"


def test_every_tool_has_description():
    for tool in all_tools():
        assert tool.description, f"{tool.name} has no description"
        assert len(tool.description) >= 30, (
            f"{tool.name} description too short: {tool.description!r}"
        )


def test_every_tool_input_schema_disallows_extra_properties():
    """Tools should set additionalProperties: false to catch typos."""
    for tool in all_tools():
        if tool.input_schema.get("type") == "object":
            assert tool.input_schema.get("additionalProperties") is False, (
                f"{tool.name} doesn't have additionalProperties: false"
            )
