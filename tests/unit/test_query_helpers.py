"""Date range parsing + comparison period tests."""

from datetime import date

import pytest
from freezegun import freeze_time

from src.google_ads.queries._common import (
    InvalidDateRangeError,
    get_comparison_range,
    parse_date_range,
)


@freeze_time("2026-05-15")
def test_parse_last_7_days() -> None:
    start, end = parse_date_range("LAST_7_DAYS")
    assert start == date(2026, 5, 8)
    assert end == date(2026, 5, 14)  # excludes today (incomplete)


@freeze_time("2026-05-15")
def test_parse_last_30_days() -> None:
    start, end = parse_date_range("LAST_30_DAYS")
    assert start == date(2026, 4, 15)
    assert end == date(2026, 5, 14)


@freeze_time("2026-05-15")
def test_parse_yesterday() -> None:
    start, end = parse_date_range("YESTERDAY")
    assert start == date(2026, 5, 14)
    assert end == date(2026, 5, 14)


@freeze_time("2026-05-15")
def test_parse_today() -> None:
    start, end = parse_date_range("TODAY")
    assert start == date(2026, 5, 15)
    assert end == date(2026, 5, 15)


@freeze_time("2026-05-15")
def test_parse_this_month() -> None:
    start, end = parse_date_range("THIS_MONTH")
    assert start == date(2026, 5, 1)
    assert end == date(2026, 5, 14)  # through yesterday


@freeze_time("2026-05-15")
def test_parse_last_month() -> None:
    start, end = parse_date_range("LAST_MONTH")
    assert start == date(2026, 4, 1)
    assert end == date(2026, 4, 30)


def test_parse_explicit_range_dict() -> None:
    start, end = parse_date_range({"from": "2026-01-01", "to": "2026-01-31"})
    assert start == date(2026, 1, 1)
    assert end == date(2026, 1, 31)


def test_parse_inverted_range_raises() -> None:
    with pytest.raises(InvalidDateRangeError, match="from.*after.*to"):
        parse_date_range({"from": "2026-01-31", "to": "2026-01-01"})


def test_parse_unknown_preset_raises() -> None:
    with pytest.raises(InvalidDateRangeError, match="UNKNOWN_PRESET"):
        parse_date_range("UNKNOWN_PRESET")


def test_parse_malformed_dict_raises() -> None:
    with pytest.raises(InvalidDateRangeError):
        parse_date_range({"from": "not-a-date", "to": "2026-01-01"})


def test_comparison_range_is_immediately_previous_period() -> None:
    """For a 7-day range Apr 8-14, previous is Apr 1-7."""
    start, end = date(2026, 4, 8), date(2026, 4, 14)
    prev_start, prev_end = get_comparison_range(start, end)
    assert prev_start == date(2026, 4, 1)
    assert prev_end == date(2026, 4, 7)


def test_comparison_range_handles_single_day() -> None:
    """For a 1-day range, previous is the day before."""
    start = end = date(2026, 5, 14)
    prev_start, prev_end = get_comparison_range(start, end)
    assert prev_start == date(2026, 5, 13)
    assert prev_end == date(2026, 5, 13)
