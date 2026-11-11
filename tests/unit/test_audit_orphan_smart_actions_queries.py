"""Unit tests for audit_orphan_smart_actions GAQL builder + boundary parser (Sprint 3b.37)."""

from datetime import date
from types import SimpleNamespace

import pytest

from src.google_ads.queries.audit_orphan_smart_actions import (
    build_audit_orphan_smart_actions_query,
    dict_to_conversion_action_row,
    parse_conversion_action_row,
)


def test_build_query_includes_required_fields():
    q, _filtros = build_audit_orphan_smart_actions_query(
        start_date=date(2026, 4, 21),
        end_date=date(2026, 5, 21),
        category=None,
    )
    required_fields = [
        "conversion_action.id",
        "conversion_action.name",
        "conversion_action.category",
        "conversion_action.origin",
        "conversion_action.primary_for_goal",
        "conversion_action.status",
        "metrics.all_conversions",
    ]
    for field in required_fields:
        assert field in q
    assert "FROM conversion_action" in q


def test_build_query_filters_enabled():
    q, _filtros = build_audit_orphan_smart_actions_query(
        start_date=date(2026, 4, 21),
        end_date=date(2026, 5, 21),
        category=None,
    )
    assert "conversion_action.status = 'ENABLED'" in q


def test_build_query_category_filter():
    q, _filtros = build_audit_orphan_smart_actions_query(
        start_date=date(2026, 4, 21),
        end_date=date(2026, 5, 21),
        category="CONTACT",
    )
    assert "conversion_action.category = 'CONTACT'" in q


def test_parse_conversion_action_row_handles_enums_and_floats():
    """Regression guard against proto-plus v20+ regression (str(enum) returns int)
    + float casting on all_conversions + int → str on id."""
    fake_row = SimpleNamespace(
        conversion_action=SimpleNamespace(
            id=12345,
            name="Whatsapp - JPA",
            category=SimpleNamespace(name="CONTACT"),
            origin=SimpleNamespace(name="WEBSITE"),
            primary_for_goal=True,
            status=SimpleNamespace(name="ENABLED"),
        ),
        metrics=SimpleNamespace(all_conversions=0.0),
    )
    result = parse_conversion_action_row(fake_row)
    assert result["conversion_action_id"] == "12345"  # int → str
    assert result["category"] == "CONTACT"  # .name resolution
    assert result["origin"] == "WEBSITE"  # .name resolution
    assert result["status"] == "ENABLED"  # .name resolution
    assert result["primary_for_goal"] is True
    assert result["all_conversions"] == 0.0  # float casting
    assert result["name"] == "Whatsapp - JPA"


def test_dict_to_conversion_action_row_chave_ausente_levanta():
    """Campo ausente e bug do formatter: estoura, nao vira zero."""
    d: dict = {"name": "test"}
    with pytest.raises(KeyError):
        dict_to_conversion_action_row(d)
