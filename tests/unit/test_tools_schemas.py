"""Verify all registered MCP tools have valid JSON Schema and consistent shape."""

import jsonschema
import pytest

from src.mcp.tools._registry import all_tools, import_all_tools
from src.mcp.tools.update_ad_group_bid import _SCHEMA as AD_GROUP_BID_SCHEMA
from src.mcp.tools.update_keyword_bid import _SCHEMA as KEYWORD_BID_SCHEMA


@pytest.fixture(scope="module", autouse=True)
def _load_tools():
    import_all_tools()


def test_every_tool_has_valid_schema():
    for tool in all_tools():
        # Will raise if invalid schema
        jsonschema.Draft202012Validator.check_schema(tool.input_schema)


def test_registered_tool_count_matches_files_on_disk():
    """Regression for Sprints 3b.12-3b.14 bug: manual import list lagged behind
    actual files, leaving 3 tools dead in production despite tests passing
    (pytest import side effects masked the registry gap).

    With pkgutil auto-discovery in import_all_tools(), this should be
    structurally impossible. Defense-in-depth: verify 1:1 count match.
    """
    import pathlib

    registered_count = len(all_tools())
    tools_dir = pathlib.Path(__file__).resolve().parent.parent.parent / "src" / "mcp" / "tools"
    file_count = sum(1 for f in tools_dir.glob("*.py") if not f.stem.startswith("_"))

    assert registered_count == file_count, (
        f"Tool count mismatch: {registered_count} registered, {file_count} files in tools/. "
        f"Likely cause: a tool file exists but its module wasn't imported by import_all_tools(). "
        f"With pkgutil auto-discovery this should be impossible — check _registry.py."
    )


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
    """All 31 tools (20 Phase 2 + 3 campaign mutations + 2 ad group mutations + 2 keyword mutations + 1 negatives + 2 recommendations + 1 create_ad_group) registered."""
    expected = {
        "add_keywords",
        "create_ad_group",
        "add_negative_keywords",
        "add_negatives_from_search_terms",
        "apply_audience",
        "apply_change",
        "apply_recommendation",
        "bulk_pause_by_query",
        "dismiss_recommendation",
        "list_my_accounts",
        # visao geral
        "get_account_overview",
        "get_budget_pacing",
        "get_recommendations",
        # performance
        "get_campaign_performance",
        "get_change_history",
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
        # ad mutations
        "update_ad_status",
        # keyword mutations
        "update_keyword_bid",
        "update_keyword_status",
        # audience mutations
        "remove_audience",
        # utilities
        "get_my_rate_limit_status",
        "get_my_audit_log",
        # create patterns
        "create_rsa",
        "create_conversion_action",
        "create_conversion_value_rule_set",
        # update patterns
        "update_rsa",
    }
    actual = {t.name for t in all_tools()}
    missing = expected - actual
    assert not missing, f"Missing tools: {missing}"


def test_no_unexpected_tools():
    """Catch accidental new tool registrations not in the expected set."""
    expected = {
        "add_keywords",
        "create_ad_group",
        "add_negative_keywords",
        "add_negatives_from_search_terms",
        "apply_audience",
        "apply_change",
        "apply_recommendation",
        "bulk_pause_by_query",
        "dismiss_recommendation",
        "remove_audience",
        "remove_negative_keywords",
        "list_my_accounts",
        "get_account_overview",
        "get_budget_pacing",
        "get_recommendations",
        "get_campaign_performance",
        "get_change_history",
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
        "update_ad_status",
        "update_keyword_bid",
        "update_keyword_status",
        "get_my_rate_limit_status",
        "get_my_audit_log",
        "create_rsa",
        "create_conversion_action",
        "create_conversion_value_rule_set",
        "update_rsa",
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


def test_update_keyword_bid_accepts_zero_bid():
    """Keyword bid schema should accept new_cpc_bid_brl: 0 to allow inheriting from parent."""
    valid_input = {
        "customer_id": "1234567890",
        "bids": [
            {
                "ad_group_id": "1",
                "criterion_id": "2",
                "new_cpc_bid_brl": 0,
            }
        ],
    }
    # Should not raise ValidationError
    jsonschema.validate(valid_input, KEYWORD_BID_SCHEMA)


def test_update_keyword_bid_rejects_negative_bid():
    """Keyword bid schema should reject new_cpc_bid_brl: -1."""
    invalid_input = {
        "customer_id": "1234567890",
        "bids": [
            {
                "ad_group_id": "1",
                "criterion_id": "2",
                "new_cpc_bid_brl": -1,
            }
        ],
    }
    with pytest.raises(jsonschema.exceptions.ValidationError):
        jsonschema.validate(invalid_input, KEYWORD_BID_SCHEMA)


def test_update_ad_group_bid_accepts_zero_bid():
    """Ad group bid schema should accept new_cpc_bid_brl: 0 to allow inheriting from parent."""
    valid_input = {
        "customer_id": "1234567890",
        "bids": [
            {
                "ad_group_id": "1",
                "new_cpc_bid_brl": 0,
            }
        ],
    }
    # Should not raise ValidationError
    jsonschema.validate(valid_input, AD_GROUP_BID_SCHEMA)


def test_update_ad_group_bid_rejects_negative_bid():
    """Ad group bid schema should reject new_cpc_bid_brl: -1."""
    invalid_input = {
        "customer_id": "1234567890",
        "bids": [
            {
                "ad_group_id": "1",
                "new_cpc_bid_brl": -1,
            }
        ],
    }
    with pytest.raises(jsonschema.exceptions.ValidationError):
        jsonschema.validate(invalid_input, AD_GROUP_BID_SCHEMA)
