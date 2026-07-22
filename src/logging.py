"""Structured logging via structlog. JSON in prod, pretty in dev."""

import logging
import sys
from collections.abc import MutableMapping
from typing import Any

import structlog


def add_cloud_logging_severity(
    _logger: object, _method_name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Mirror structlog's `level` into a top-level `severity` field.

    Cloud Run/Cloud Logging derives an entry's severity from a `severity` key in
    the structured payload; structlog emits `level` (lowercase), which is NOT
    recognized, so every log lands as severity=DEFAULT and severity-based alerts
    miss ERROR logs (F76 sub-note). structlog's level names uppercase directly to
    valid Cloud Logging LogSeverity values (info→INFO, error→ERROR, …).
    """
    level = event_dict.get("level")
    if isinstance(level, str):
        event_dict["severity"] = level.upper()
    return event_dict


def _build_processors(json_output: bool) -> list[Any]:
    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    if json_output:
        # After add_log_level (needs `level`); before the renderer (must mutate
        # the event dict, not the rendered string).
        processors.append(add_cloud_logging_severity)
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer(colors=True))
    return processors


def configure_logging(level: str = "info", json_output: bool = True) -> None:
    """Configure root logger and structlog.

    Call once at app startup. After that, get loggers via
    `structlog.get_logger(__name__)` from any module.
    """
    log_level = getattr(logging, level.upper())

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
    )

    structlog.configure(
        processors=_build_processors(json_output),
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def bind_request_context(**kwargs: Any) -> None:
    """Attach contextual fields to all logs in current async task."""
    structlog.contextvars.bind_contextvars(**kwargs)


def clear_request_context() -> None:
    """Clear contextual fields between requests."""
    structlog.contextvars.clear_contextvars()
