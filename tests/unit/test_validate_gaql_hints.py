"""Test contextual hints in validate_gaql error messages (B2+B3 dogfood MO-JP).

B2: FROM change_event + LAST_30_DAYS rejection ("too old") -> hint about
    30-day inclusive window + suggest LAST_14_DAYS.
B3: segments.conversion_action + metrics.cost_micros conflict -> hint about
    splitting into 2 queries.
"""

from src.mcp.tools.validate_gaql import _augment_error_hint

# ---------- B2: change_event 30-day window ----------


def test_b2_change_event_too_old_adds_hint():
    """FROM change_event + error mentioning 'too old' should append window hint."""
    query = (
        "SELECT change_event.change_date_time, change_event.user_email "
        "FROM change_event WHERE change_event.change_date_time DURING LAST_30_DAYS"
    )
    msg = (
        "Google Ads retornou: The requested start date is too old. It cannot be older than 30 days."
    )
    result = _augment_error_hint(query, msg)
    assert "change_event" in result.lower()
    assert "30 dias" in result or "30d" in result
    # Original message preserved
    assert "too old" in result.lower()


def test_b2_change_event_30_days_phrase_also_triggers():
    """Variant phrasing 'cannot be older than 30 days' should also trigger."""
    query = "SELECT change_event.change_date_time FROM change_event WHERE ... DURING LAST_30_DAYS"
    msg = "Erro: It cannot be older than 30 days."
    result = _augment_error_hint(query, msg)
    assert result != msg  # hint was appended
    assert "LAST_14_DAYS" in result or "14" in result


def test_b2_no_hint_when_query_doesnt_use_change_event():
    """Same 'too old' error on different resource shouldn't trigger change_event hint."""
    query = "SELECT campaign.id FROM campaign WHERE segments.date DURING LAST_30_DAYS"
    msg = "Google Ads retornou: The requested start date is too old."
    result = _augment_error_hint(query, msg)
    # No change_event-specific hint
    assert "change_event tem janela" not in result


def test_b2_no_hint_when_error_unrelated_to_window():
    """change_event query with unrelated error shouldn't get B2 hint."""
    query = "SELECT change_event.invalid_field FROM change_event"
    msg = "Field 'change_event.invalid_field' does not exist."
    result = _augment_error_hint(query, msg)
    assert "change_event tem janela" not in result


# ---------- B3: segments.conversion_action + metrics.cost_micros ----------


def test_b3_conversion_action_with_cost_micros_adds_hint():
    """Query selecting both segments.conversion_action and metrics.cost_micros should trigger hint."""
    query = (
        "SELECT segments.conversion_action, segments.conversion_action_name, "
        "metrics.conversions, metrics.cost_micros FROM campaign "
        "WHERE campaign.id IN (123)"
    )
    msg = (
        "Cannot select the following segments because at least one unsupported metric "
        "is found in SELECT or WHERE clause: 'segments.conversion_action' "
        "(unsupported metrics: 'cost_micros')."
    )
    result = _augment_error_hint(query, msg)
    assert "2 queries" in result.lower() or "duas queries" in result.lower()
    assert "cost_micros" in result.lower()
    # Original message preserved
    assert "unsupported metric" in result.lower()


def test_b3_conversion_action_name_variant_triggers():
    """segments.conversion_action_name variant should also trigger."""
    query = "SELECT segments.conversion_action_name, metrics.cost_micros FROM campaign WHERE ..."
    msg = "unsupported metrics: 'cost_micros'"
    result = _augment_error_hint(query, msg)
    assert result != msg


def test_b3_no_hint_when_only_segments_no_cost_micros():
    """Query with segments.conversion_action only (no cost_micros) shouldn't trigger B3."""
    query = "SELECT segments.conversion_action, metrics.conversions FROM campaign"
    msg = "Some other error."
    result = _augment_error_hint(query, msg)
    assert "2 queries" not in result.lower()


def test_b3_no_hint_when_only_cost_micros_no_segments():
    """Query with metrics.cost_micros only (no segments.conversion_action) shouldn't trigger."""
    query = "SELECT campaign.id, metrics.cost_micros FROM campaign"
    msg = "Some unrelated error."
    result = _augment_error_hint(query, msg)
    assert "2 queries" not in result.lower()


def test_b3_no_hint_when_error_unrelated():
    """Both fields present but error not about unsupported metric -> no hint."""
    query = "SELECT segments.conversion_action, metrics.cost_micros FROM campaign"
    msg = "Some random syntax error."
    result = _augment_error_hint(query, msg)
    assert "2 queries" not in result.lower()


# ---------- Cross-cutting ----------


def test_returns_original_message_when_no_pattern_matches():
    """Generic error on generic query should return original unchanged."""
    query = "SELECT campaign.id FROM campaign"
    msg = "Some random error."
    result = _augment_error_hint(query, msg)
    assert result == msg


def test_case_insensitive_query_detection():
    """Query patterns matched case-insensitively (handles SELECT/select, FROM/from)."""
    query = "select change_event.change_date_time from CHANGE_EVENT where ... during LAST_30_DAYS"
    msg = "The requested start date is too old."
    result = _augment_error_hint(query, msg)
    assert "change_event" in result.lower() and "30 dias" in result


def test_empty_query_returns_message_unchanged():
    result = _augment_error_hint("", "any error")
    assert result == "any error"


def test_empty_message_returns_empty():
    result = _augment_error_hint("SELECT campaign.id FROM campaign", "")
    assert result == ""
