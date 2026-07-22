"""Unit tests for Cloud Logging severity mapping (src/logging.py).

Guards the F76 sub-note: structlog emits `level` (lowercase), which Cloud Run
does NOT treat as the entry severity — so severity-based alerts miss ERROR logs.
A processor mirrors `level` into a top-level `severity` field Cloud Logging reads.
"""

from __future__ import annotations

import pytest

from src.logging import _build_processors, add_cloud_logging_severity


@pytest.mark.parametrize(
    ("level", "severity"),
    [
        ("debug", "DEBUG"),
        ("info", "INFO"),
        ("warning", "WARNING"),
        ("error", "ERROR"),
        ("critical", "CRITICAL"),
    ],
)
def test_maps_structlog_level_to_cloud_logging_severity(level: str, severity: str) -> None:
    # method_name is deliberately unrelated — the severity must come from the
    # already-set event_dict["level"], not the method name.
    event_dict = add_cloud_logging_severity(None, "method_ignored", {"level": level, "event": "x"})
    assert event_dict["severity"] == severity


def test_noop_when_level_absent() -> None:
    event_dict = add_cloud_logging_severity(None, "info", {"event": "no level here"})
    assert "severity" not in event_dict


def _names(processors: list[object]) -> list[str]:
    return [getattr(p, "__name__", type(p).__name__) for p in processors]


def test_json_pipeline_adds_severity_before_the_renderer() -> None:
    names = _names(_build_processors(json_output=True))
    assert "add_cloud_logging_severity" in names
    # Must run BEFORE JSONRenderer — after it, it would mutate the rendered string.
    assert names.index("add_cloud_logging_severity") < names.index("JSONRenderer")


def test_console_pipeline_omits_severity() -> None:
    names = _names(_build_processors(json_output=False))
    assert "add_cloud_logging_severity" not in names
