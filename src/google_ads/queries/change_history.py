"""GAQL builder for the change_event resource (used by get_change_history tool)."""

from datetime import date


class RangeTooWideError(ValueError):
    """Raised when the requested date_range exceeds the 30-day API limit."""


# Google Ads change_event has a documented ~30-day retention.
# Empirically (smoke 2026-05-11) the `DURING LAST_30_DAYS` GAQL preset
# can hit "too old" depending on edge timing; our path uses explicit
# BETWEEN dates which has worked at exactly 30 days. If the API tightens
# further, drop this to 29 and resolve LAST_30_DAYS in parse_date_range
# accordingly, OR translate Google's "too old" error to a friendly
# PT-BR retry hint.
_MAX_DAYS = 30


def _quote_literal(s: str) -> str:
    """Escape single quotes for GAQL string literal (double them per spec)."""
    return s.replace("'", "''")


def _format_in_clause(values: list[str]) -> str:
    """Format ('val1', 'val2', ...) for a GAQL IN clause."""
    escaped = [f"'{_quote_literal(v)}'" for v in values]
    return f"({', '.join(escaped)})"


def change_history_query(
    *,
    start: date,
    end: date,
    resource_types: list[str] | None,
    operation_types: list[str] | None,
    user_emails: list[str] | None,
    client_types: list[str] | None,
    limit: int,
) -> str:
    """Build the GAQL for fetching change_event rows with optional filters.

    Raises RangeTooWideError if (end - start) > 30 days.

    All filter args, when provided, must be non-empty lists; pass None to omit.
    """
    range_days = (end - start).days + 1
    if range_days > _MAX_DAYS:
        raise RangeTooWideError(
            f"Janela maxima de {_MAX_DAYS} dias para historico de mudancas — "
            f"recebido {range_days} dias. Limite da API do Google Ads."
        )

    where: list[str] = [
        f"change_event.change_date_time BETWEEN '{start.isoformat()}' AND '{end.isoformat()}'"
    ]

    if resource_types:
        where.append(f"change_event.change_resource_type IN {_format_in_clause(resource_types)}")
    if operation_types:
        where.append(
            f"change_event.resource_change_operation IN {_format_in_clause(operation_types)}"
        )
    if user_emails:
        where.append(f"change_event.user_email IN {_format_in_clause(user_emails)}")
    if client_types:
        where.append(f"change_event.client_type IN {_format_in_clause(client_types)}")

    where_clause = " AND ".join(where)

    return f"""
        SELECT
          change_event.change_date_time,
          change_event.user_email,
          change_event.client_type,
          change_event.change_resource_type,
          change_event.change_resource_name,
          change_event.resource_change_operation,
          change_event.changed_fields,
          change_event.campaign,
          change_event.ad_group
        FROM change_event
        WHERE {where_clause}
        ORDER BY change_event.change_date_time DESC
        LIMIT {limit}
    """.strip()


def negative_criterion_creations_query(*, start: date, end: date) -> str:
    """Build GAQL for fetching campaign_criterion CREATE events.

    Used by get_negative_keywords_audit to enrich each negative keyword with
    its created_date + added_by_email. Filters to CAMPAIGN_CRITERION resource
    type + CREATE operation. Sprint 3b.21.

    Raises RangeTooWideError if range exceeds ~30 days (change_event API limit).
    """
    range_days = (end - start).days + 1
    if range_days > _MAX_DAYS:
        raise RangeTooWideError(
            f"Janela maxima de {_MAX_DAYS} dias para historico de mudancas — "
            f"recebido {range_days} dias. Limite da API do Google Ads."
        )

    return f"""
        SELECT
          change_event.change_resource_name,
          change_event.change_date_time,
          change_event.user_email
        FROM change_event
        WHERE change_event.change_date_time BETWEEN '{start.isoformat()}' AND '{end.isoformat()}'
          AND change_event.change_resource_type = 'CAMPAIGN_CRITERION'
          AND change_event.resource_change_operation = 'CREATE'
        ORDER BY change_event.change_date_time DESC
        LIMIT 10000
    """.strip()
