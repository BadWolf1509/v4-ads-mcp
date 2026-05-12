"""Sprint 3b.5 A2: schema-restrict tests for the 3 status tools without dedicated test files.

update_ad_status has its own test file; update_campaign/ad_group/keyword_status
get coverage via this parametrized test for the REMOVED rejection.
"""

import pytest
from jsonschema import ValidationError, validate


def _good_campaign_payload():
    return {
        "customer_id": "1234567890",
        "campaign_ids": ["111"],
        "new_status": "PAUSED",
    }


def _good_ad_group_payload():
    return {
        "customer_id": "1234567890",
        "ad_group_ids": ["111"],
        "new_status": "PAUSED",
    }


def _good_keyword_payload():
    return {
        "customer_id": "1234567890",
        "keywords": [{"ad_group_id": "111", "criterion_id": "222"}],
        "new_status": "PAUSED",
    }


_CASES = [
    ("update_campaign_status", _good_campaign_payload),
    ("update_ad_group_status", _good_ad_group_payload),
    ("update_keyword_status", _good_keyword_payload),
]


@pytest.mark.parametrize("tool_module,payload_factory", _CASES)
def test_schema_rejects_removed_new_status(tool_module, payload_factory):
    """Sprint 3b.5 A2: all status tools must reject REMOVED at schema level."""
    module = __import__(f"src.mcp.tools.{tool_module}", fromlist=["_SCHEMA"])
    bad = payload_factory()
    bad["new_status"] = "REMOVED"
    with pytest.raises(ValidationError):
        validate(bad, module._SCHEMA)


@pytest.mark.parametrize("tool_module,payload_factory", _CASES)
def test_schema_accepts_paused(tool_module, payload_factory):
    """Sanity: PAUSED still works after schema-restrict."""
    module = __import__(f"src.mcp.tools.{tool_module}", fromlist=["_SCHEMA"])
    payload = payload_factory()
    payload["new_status"] = "PAUSED"
    validate(payload, module._SCHEMA)  # should not raise


@pytest.mark.parametrize("tool_module,payload_factory", _CASES)
def test_schema_accepts_enabled(tool_module, payload_factory):
    """Sanity: ENABLED still works after schema-restrict."""
    module = __import__(f"src.mcp.tools.{tool_module}", fromlist=["_SCHEMA"])
    payload = payload_factory()
    payload["new_status"] = "ENABLED"
    validate(payload, module._SCHEMA)  # should not raise
