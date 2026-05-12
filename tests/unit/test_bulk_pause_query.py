"""Unit tests for the bulk_pause GAQL builder."""

from datetime import date

import pytest


def test_target_to_resource_mapping_keyword():
    from src.google_ads.queries.bulk_pause import bulk_pause_query

    q = bulk_pause_query(
        target_type="keyword",
        filter_clause="ad_group_criterion.status = 'ENABLED'",
        start=date(2026, 5, 1),
        end=date(2026, 5, 11),
    )
    assert "FROM keyword_view" in q
    assert "ad_group_criterion.criterion_id" in q
    assert "ad_group.id" in q
    assert "LIMIT 101" in q


def test_target_to_resource_mapping_ad():
    from src.google_ads.queries.bulk_pause import bulk_pause_query

    q = bulk_pause_query(
        target_type="ad",
        filter_clause="ad_group_ad.status = 'ENABLED'",
        start=date(2026, 5, 1),
        end=date(2026, 5, 11),
    )
    assert "FROM ad_group_ad" in q
    assert "ad_group_ad.ad.id" in q
    assert "LIMIT 101" in q


def test_target_to_resource_mapping_campaign():
    from src.google_ads.queries.bulk_pause import bulk_pause_query

    q = bulk_pause_query(
        target_type="campaign",
        filter_clause="campaign.status = 'ENABLED'",
        start=date(2026, 5, 1),
        end=date(2026, 5, 11),
    )
    assert "FROM campaign" in q
    assert "campaign.id" in q
    assert "LIMIT 101" in q


def test_target_to_resource_mapping_ad_group():
    from src.google_ads.queries.bulk_pause import bulk_pause_query

    q = bulk_pause_query(
        target_type="ad_group",
        filter_clause="ad_group.status = 'ENABLED'",
        start=date(2026, 5, 1),
        end=date(2026, 5, 11),
    )
    assert "FROM ad_group" in q
    assert "ad_group.id" in q
    assert "LIMIT 101" in q


def test_date_clause_injected_when_filter_uses_metrics():
    from src.google_ads.queries.bulk_pause import bulk_pause_query

    q = bulk_pause_query(
        target_type="keyword",
        filter_clause="metrics.cost_micros > 100000000 AND metrics.conversions = 0",
        start=date(2026, 5, 1),
        end=date(2026, 5, 11),
    )
    assert "segments.date BETWEEN '2026-05-01' AND '2026-05-11'" in q


def test_date_clause_not_injected_when_filter_has_no_metrics():
    from src.google_ads.queries.bulk_pause import bulk_pause_query

    q = bulk_pause_query(
        target_type="campaign",
        filter_clause="campaign.status = 'PAUSED'",
        start=date(2026, 5, 1),
        end=date(2026, 5, 11),
    )
    # No date clause needed for entity-only filters
    assert "segments.date BETWEEN" not in q


def test_filter_validation_rejects_semicolon():
    from src.google_ads.queries.bulk_pause import (
        FilterValidationError,
        validate_filter,
    )

    with pytest.raises(FilterValidationError) as e:
        validate_filter("campaign.status = 'PAUSED'; DROP TABLE users")
    assert "ponto-e-virgula" in str(e.value).lower() or ";" in str(e.value)


def test_filter_validation_rejects_select_keyword():
    from src.google_ads.queries.bulk_pause import (
        FilterValidationError,
        validate_filter,
    )

    with pytest.raises(FilterValidationError):
        validate_filter("SELECT 1 FROM campaign")


def test_filter_validation_rejects_from_keyword():
    from src.google_ads.queries.bulk_pause import (
        FilterValidationError,
        validate_filter,
    )

    with pytest.raises(FilterValidationError):
        validate_filter("FROM campaign WHERE x=1")


def test_filter_validation_rejects_oversized():
    from src.google_ads.queries.bulk_pause import (
        FilterValidationError,
        validate_filter,
    )

    big = "campaign.status = 'PAUSED' AND " * 100  # ~3000+ chars
    with pytest.raises(FilterValidationError) as e:
        validate_filter(big)
    assert "1000" in str(e.value)


def test_filter_validation_accepts_valid_complex_filter():
    from src.google_ads.queries.bulk_pause import validate_filter

    # Should not raise
    validate_filter(
        "metrics.cost_micros > 100000000 AND metrics.conversions = 0 "
        "AND campaign.advertising_channel_type = 'SEARCH'"
    )
