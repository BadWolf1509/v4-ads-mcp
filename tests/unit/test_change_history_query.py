"""Unit tests for the change_history GAQL builder."""

from datetime import date

import pytest


def test_no_filters_only_date_range():
    from src.google_ads.queries.change_history import change_history_query

    q = change_history_query(
        start=date(2026, 5, 4),
        end=date(2026, 5, 11),
        resource_types=None,
        operation_types=None,
        user_emails=None,
        client_types=None,
        limit=200,
    )
    assert "FROM change_event" in q
    assert "change_event.change_date_time BETWEEN '2026-05-04'" in q
    assert "AND '2026-05-11'" in q
    # No optional WHERE clauses present
    assert "change_event.change_resource_type IN" not in q
    assert "change_event.resource_change_operation IN" not in q
    assert "change_event.user_email IN" not in q
    assert "change_event.client_type IN" not in q
    assert "LIMIT 200" in q


def test_resource_types_filter():
    from src.google_ads.queries.change_history import change_history_query

    q = change_history_query(
        start=date(2026, 5, 4),
        end=date(2026, 5, 11),
        resource_types=["CAMPAIGN", "AD_GROUP"],
        operation_types=None,
        user_emails=None,
        client_types=None,
        limit=200,
    )
    assert "change_event.change_resource_type IN ('CAMPAIGN', 'AD_GROUP')" in q


def test_operation_types_filter():
    from src.google_ads.queries.change_history import change_history_query

    q = change_history_query(
        start=date(2026, 5, 4),
        end=date(2026, 5, 11),
        resource_types=None,
        operation_types=["UPDATE"],
        user_emails=None,
        client_types=None,
        limit=200,
    )
    assert "change_event.resource_change_operation IN ('UPDATE')" in q


def test_user_emails_filter_escapes_single_quote():
    from src.google_ads.queries.change_history import change_history_query

    q = change_history_query(
        start=date(2026, 5, 4),
        end=date(2026, 5, 11),
        resource_types=None,
        operation_types=None,
        user_emails=["fulano@v4company.com", "ana.o'brien@v4company.com"],
        client_types=None,
        limit=200,
    )
    # Single quote inside email must be doubled per GAQL string literal rules
    assert "change_event.user_email IN ('fulano@v4company.com', 'ana.o''brien@v4company.com')" in q


def test_client_types_filter():
    from src.google_ads.queries.change_history import change_history_query

    q = change_history_query(
        start=date(2026, 5, 4),
        end=date(2026, 5, 11),
        resource_types=None,
        operation_types=None,
        user_emails=None,
        client_types=["GOOGLE_ADS_RECOMMENDATIONS", "GOOGLE_ADS_WEB_CLIENT"],
        limit=200,
    )
    assert (
        "change_event.client_type IN ('GOOGLE_ADS_RECOMMENDATIONS', 'GOOGLE_ADS_WEB_CLIENT')" in q
    )


def test_all_filters_combined():
    from src.google_ads.queries.change_history import change_history_query

    q = change_history_query(
        start=date(2026, 5, 1),
        end=date(2026, 5, 11),
        resource_types=["CAMPAIGN"],
        operation_types=["UPDATE", "REMOVE"],
        user_emails=["x@v4company.com"],
        client_types=["GOOGLE_ADS_WEB_CLIENT"],
        limit=50,
    )
    assert "FROM change_event" in q
    assert "change_event.change_date_time BETWEEN" in q
    assert "change_event.change_resource_type IN ('CAMPAIGN')" in q
    assert "change_event.resource_change_operation IN ('UPDATE', 'REMOVE')" in q
    assert "change_event.user_email IN ('x@v4company.com')" in q
    assert "change_event.client_type IN ('GOOGLE_ADS_WEB_CLIENT')" in q
    assert "LIMIT 50" in q


def test_range_over_30_days_raises():
    from src.google_ads.queries.change_history import RangeTooWideError, change_history_query

    with pytest.raises(RangeTooWideError) as excinfo:
        change_history_query(
            start=date(2026, 4, 1),
            end=date(2026, 5, 11),  # 41 days
            resource_types=None,
            operation_types=None,
            user_emails=None,
            client_types=None,
            limit=200,
        )
    assert "30" in str(excinfo.value)
