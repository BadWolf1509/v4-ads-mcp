"""Sanity tests for the ProtoFieldCapture fixture itself."""

from tests.unit.fixtures.proto_capture import CapturedOp, make_capture_client


def test_capture_simple_assignment():
    """field() returns the value set on a 1-level attribute."""
    op = CapturedOp()
    op.foo = "bar"
    assert op.field("foo") == "bar"


def test_capture_nested_assignment():
    """field() returns the value at a 3-level deep path."""
    op = CapturedOp()
    op.outer.middle.inner = 42
    assert op.field("outer.middle.inner") == 42


def test_capture_unset_path_returns_none():
    """field() returns None for paths never assigned."""
    op = CapturedOp()
    op.foo.bar = "set"
    assert op.field("foo.unset") is None
    assert op.field("unrelated.path") is None


def test_has_distinguishes_set_from_unset():
    op = CapturedOp()
    op.foo.bar = "set"
    assert op.has("foo.bar") is True
    assert op.has("foo.unset") is False


def test_capture_bool_field():
    """Boolean assignment captured correctly (relevant for `negative` field)."""
    op = CapturedOp()
    op.crit.negative = True
    assert op.field("crit.negative") is True
    assert op.field("crit.negative") is not None  # confirms bool True isn't confused with None


def test_make_capture_client_has_expected_services():
    client = make_capture_client()
    assert (
        client.get_service("AdGroupService").ad_group_path("123", "456")
        == "customers/123/adGroups/456"
    )
    assert (
        client.get_service("CampaignService").campaign_path("123", "789")
        == "customers/123/campaigns/789"
    )


def test_make_capture_client_get_type_returns_captured_op():
    client = make_capture_client()
    op = client.get_type("MutateOperation")
    assert isinstance(op, CapturedOp)
