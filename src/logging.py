"""Structured logging via structlog. JSON in prod, pretty in dev."""

import logging
import sys
from typing import Any

import structlog


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

    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if json_output:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer(colors=True))

    structlog.configure(
        processors=processors,
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
