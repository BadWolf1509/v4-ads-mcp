"""Unit tests for src.google_ads.aggregation.aggregate_rows (Sprint 3b.29 B5).

Pure function tests — sem fixture Google SDK. COUNT only por design (V0).
"""

from src.google_ads.aggregation import aggregate_rows


def test_empty_rows_returns_empty_groups():
    assert aggregate_rows([], ["field_type"]) == []


def test_single_field_group_by():
    rows = [
        {"field_type": "SITELINK"},
        {"field_type": "STRUCTURED_SNIPPET"},
        {"field_type": "STRUCTURED_SNIPPET"},
        {"field_type": "SITELINK"},
        {"field_type": "STRUCTURED_SNIPPET"},
    ]
    result = aggregate_rows(rows, ["field_type"])
    # STRUCTURED_SNIPPET first (3 > SITELINK 2)
    assert result == [
        {"key": {"field_type": "STRUCTURED_SNIPPET"}, "count": 3},
        {"key": {"field_type": "SITELINK"}, "count": 2},
    ]


def test_multi_field_group_by():
    rows = [
        {"field_type": "SITELINK", "asset": {"type": "SITELINK"}},
        {"field_type": "STRUCTURED_SNIPPET", "asset": {"type": "STRUCTURED_SNIPPET"}},
        {"field_type": "STRUCTURED_SNIPPET", "asset": {"type": "STRUCTURED_SNIPPET"}},
    ]
    result = aggregate_rows(rows, ["field_type", "asset.type"])
    assert len(result) == 2
    top = result[0]
    assert top["count"] == 2
    assert top["key"]["field_type"] == "STRUCTURED_SNIPPET"
    assert top["key"]["asset.type"] == "STRUCTURED_SNIPPET"


def test_nested_field_path_dotted_lookup():
    rows = [
        {"campaign": {"id": "123"}},
        {"campaign": {"id": "456"}},
        {"campaign": {"id": "123"}},
    ]
    result = aggregate_rows(rows, ["campaign.id"])
    # campaign.id=123 has 2; 456 has 1
    assert result == [
        {"key": {"campaign.id": "123"}, "count": 2},
        {"key": {"campaign.id": "456"}, "count": 1},
    ]


def test_missing_field_yields_none_key():
    rows = [
        {"field_type": "SITELINK"},
        {"field_type": "SITELINK", "asset": {"type": "SITELINK"}},
        {"asset": {"type": "X"}},  # no field_type
    ]
    result = aggregate_rows(rows, ["field_type"])
    # 2 groups: SITELINK (2) + None (1)
    assert len(result) == 2
    assert result[0] == {"key": {"field_type": "SITELINK"}, "count": 2}
    assert result[1] == {"key": {"field_type": None}, "count": 1}


def test_sort_is_count_desc():
    rows = [{"x": "a"}] + [{"x": "b"}] * 5 + [{"x": "c"}] * 3
    result = aggregate_rows(rows, ["x"])
    counts_only = [g["count"] for g in result]
    assert counts_only == [5, 3, 1]


def test_ties_in_count_preserves_insertion_order():
    rows = [{"x": "a"}, {"x": "b"}, {"x": "a"}, {"x": "b"}]
    result = aggregate_rows(rows, ["x"])
    # both have count 2; "a" was inserted first
    assert result[0]["key"] == {"x": "a"}
    assert result[1]["key"] == {"x": "b"}


def test_single_row_returns_one_group_count_1():
    result = aggregate_rows([{"x": "a"}], ["x"])
    assert result == [{"key": {"x": "a"}, "count": 1}]


def test_group_by_field_not_in_any_row():
    rows = [{"a": 1}, {"a": 2}, {"a": 3}]
    result = aggregate_rows(rows, ["nonexistent"])
    assert result == [{"key": {"nonexistent": None}, "count": 3}]
