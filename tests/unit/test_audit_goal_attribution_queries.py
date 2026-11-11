"""Unit tests for audit_goal_attribution GAQL builders + boundary parsers (Sprint 3b.35)."""

import pytest

from src.google_ads.goal_attribution import (
    dict_to_conversion_action_row,
    dict_to_customer_conversion_goal_row,
)
from src.google_ads.queries.audit_goal_attribution import (
    build_conversion_action_query,
    build_customer_conversion_goal_query,
)

# === GAQL builder tests (4) ===


def test_build_conversion_action_query_includes_required_fields():
    q = build_conversion_action_query()
    required_fields = [
        "conversion_action.id",
        "conversion_action.name",
        "conversion_action.category",
        "conversion_action.origin",
        "conversion_action.primary_for_goal",
        "conversion_action.include_in_conversions_metric",
        "conversion_action.status",
    ]
    for field in required_fields:
        assert field in q


def test_build_conversion_action_query_filters_enabled_status():
    q = build_conversion_action_query()
    assert "WHERE conversion_action.status = 'ENABLED'" in q
    assert "FROM conversion_action" in q


def test_build_customer_conversion_goal_query_shape():
    q = build_customer_conversion_goal_query()
    assert "customer_conversion_goal.category" in q
    assert "customer_conversion_goal.origin" in q
    assert "customer_conversion_goal.biddable" in q
    assert "FROM customer_conversion_goal" in q


def test_build_customer_conversion_goal_query_no_filter():
    """customer_conversion_goal query não tem WHERE — retorna todos goals."""
    q = build_customer_conversion_goal_query()
    assert "WHERE" not in q


# === Boundary parser tests (4) ===


def _acao(**sobre) -> dict:
    base = {
        "id": "1",
        "name": "Test",
        "category": "CONTACT",
        "origin": "WEBSITE",
        "primary_for_goal": False,
        "include_in_conversions_metric": False,
        "status": "ENABLED",
    }
    return {**base, **sobre}


def test_dict_to_conversion_action_row_chave_ausente_levanta():
    """Campo ausente e bug do formatter: estoura, nao vira ''/False."""
    with pytest.raises(KeyError):
        dict_to_conversion_action_row({"id": "1", "name": "Test"})


def test_dict_to_conversion_action_row_dict_completo():
    row = dict_to_conversion_action_row(_acao())
    assert row.id == "1"
    assert row.name == "Test"
    assert row.status == "ENABLED"
    assert row.primary_for_goal is False


def test_dict_to_conversion_action_row_bool_coercion_for_primary_for_goal():
    """primary_for_goal True/False preserved via bool()."""
    d_true = _acao(primary_for_goal=True)
    d_false = _acao(primary_for_goal=False)
    assert dict_to_conversion_action_row(d_true).primary_for_goal is True
    assert dict_to_conversion_action_row(d_false).primary_for_goal is False


def test_dict_to_customer_conversion_goal_row_chave_ausente_levanta():
    d: dict = {"category": "CONTACT", "origin": "WEBSITE"}
    with pytest.raises(KeyError):
        dict_to_customer_conversion_goal_row(d)


def test_dict_to_customer_conversion_goal_row_full_dict():
    d = {"category": "PURCHASE", "origin": "APP", "biddable": True}
    row = dict_to_customer_conversion_goal_row(d)
    assert row.category == "PURCHASE"
    assert row.origin == "APP"
    assert row.biddable is True
