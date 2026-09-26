"""Unit tests for the bulk_pause GAQL builder."""

from datetime import date

import pytest

from src.google_ads.queries.bulk_pause import bulk_pause_query


def test_target_to_resource_mapping_keyword():
    from src.google_ads.queries.bulk_pause import bulk_pause_query

    q, _ = bulk_pause_query(
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

    q, _ = bulk_pause_query(
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

    q, _ = bulk_pause_query(
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

    q, _ = bulk_pause_query(
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

    q, _ = bulk_pause_query(
        target_type="keyword",
        filter_clause="metrics.cost_micros > 100000000 AND metrics.conversions = 0",
        start=date(2026, 5, 1),
        end=date(2026, 5, 11),
    )
    assert "segments.date BETWEEN '2026-05-01' AND '2026-05-11'" in q


def test_date_clause_injected_even_when_filter_has_no_metrics():
    """Ate 4eade8a a janela so entrava com `metrics.` no filtro; filtro so de
    entidade (como este) ficava sem ela, e o custo do preview virava o de TODA
    A VIDA da entidade em vez do periodo (spec 2026-09-25, §4.1;
    test_filtro_so_de_entidade_ganha_a_janela cobre o caso com os valores
    exatos do achado)."""
    from src.google_ads.queries.bulk_pause import bulk_pause_query

    q, _ = bulk_pause_query(
        target_type="campaign",
        filter_clause="campaign.status = 'PAUSED'",
        start=date(2026, 5, 1),
        end=date(2026, 5, 11),
    )
    assert "segments.date BETWEEN '2026-05-01' AND '2026-05-11'" in q


def test_filtro_so_de_entidade_ganha_a_janela() -> None:
    """Antes: sem `metrics.` no filtro, a janela nao entrava e o custo do preview
    era o de TODA A VIDA da entidade (medido em 25/09: R$ 3.013,88 contra
    R$ 638,05 nos 30 dias)."""
    gaql, filtros = bulk_pause_query(
        target_type="keyword",
        filter_clause="ad_group_criterion.status = 'ENABLED'",
        start=date(2026, 9, 1),
        end=date(2026, 9, 30),
    )
    assert "segments.date BETWEEN '2026-09-01' AND '2026-09-30'" in gaql
    assert filtros["date_range"] == {"start": "2026-09-01", "end": "2026-09-30"}
    assert filtros["filtro_do_gestor"] == "ad_group_criterion.status = 'ENABLED'"


def test_filtro_com_janela_propria_nao_ganha_outra() -> None:
    gaql, filtros = bulk_pause_query(
        target_type="campaign",
        filter_clause="segments.date DURING LAST_7_DAYS AND metrics.cost_micros > 0",
        start=date(2026, 9, 1),
        end=date(2026, 9, 30),
    )
    assert gaql.count("segments.date") == 1
    assert "date_range" not in filtros


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
