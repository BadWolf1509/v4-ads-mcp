"""GAQL builder for bulk_pause_by_query.

Composes the SELECT/FROM/WHERE/LIMIT clauses per target_type. The
LIMIT 101 trick lets us detect overflow (>100 matches) by row count
without a separate COUNT() query.

Filter validation rejects shapes that suggest the user is trying to
inject SQL or escape the WHERE-clause scope.
"""

from datetime import date

from src.google_ads.queries._common import gaql_date_clause


class FilterValidationError(ValueError):
    """Raised when the user-supplied filter fails pre-flight checks."""


_FORBIDDEN_KEYWORDS = ("SELECT ", "FROM ", "LIMIT ", "ORDER BY", "GROUP BY")
_MAX_FILTER_LEN = 1000

# (target_type, FROM resource, list of SELECT fields)
_TARGET_TO_QUERY: dict[str, tuple[str, list[str]]] = {
    "keyword": (
        "keyword_view",
        [
            "ad_group_criterion.criterion_id",
            "ad_group_criterion.keyword.text",
            "ad_group_criterion.status",
            "ad_group.id",
            "ad_group.name",
            "campaign.id",
            "campaign.name",
            "metrics.cost_micros",
        ],
    ),
    "ad": (
        "ad_group_ad",
        [
            "ad_group_ad.ad.id",
            "ad_group_ad.status",
            "ad_group.id",
            "ad_group.name",
            "campaign.id",
            "campaign.name",
            "metrics.cost_micros",
        ],
    ),
    "campaign": (
        "campaign",
        [
            "campaign.id",
            "campaign.name",
            "campaign.status",
            "metrics.cost_micros",
        ],
    ),
    "ad_group": (
        "ad_group",
        [
            "ad_group.id",
            "ad_group.name",
            "ad_group.status",
            "campaign.id",
            "campaign.name",
            "metrics.cost_micros",
        ],
    ),
}


def validate_filter(filter_clause: str) -> None:
    """Pre-flight: reject shapes that suggest injection or non-WHERE intent.

    Raises FilterValidationError with PT-BR message on rejection.
    """
    if ";" in filter_clause:
        raise FilterValidationError(
            "Filter nao pode conter ';' (ponto-e-virgula) — apenas a clausula WHERE eh aceita."
        )
    upper = filter_clause.upper()
    for kw in _FORBIDDEN_KEYWORDS:
        if kw in upper:
            raise FilterValidationError(
                f"Filter nao pode conter '{kw.strip()}' — apenas o corpo da clausula WHERE "
                f'(ex: "metrics.cost_micros > 100000000 AND metrics.conversions = 0").'
            )
    if len(filter_clause) > _MAX_FILTER_LEN:
        raise FilterValidationError(
            f"Filter excede {_MAX_FILTER_LEN} caracteres ({len(filter_clause)}). "
            f"Simplifique o filtro ou divida em multiplas chamadas."
        )


def bulk_pause_query(
    *,
    target_type: str,
    filter_clause: str,
    start: date,
    end: date,
) -> str:
    """Compose the GAQL for the bulk_pause_by_query dry-run.

    target_type must be one of {keyword, ad, campaign, ad_group}.
    filter_clause must already have passed validate_filter().
    start/end provide the segments.date BETWEEN clause (auto-injected
    only when filter mentions metrics.* — entity-only filters skip it).
    """
    if target_type not in _TARGET_TO_QUERY:
        raise ValueError(
            f"target_type='{target_type}' invalido. Aceitos: {sorted(_TARGET_TO_QUERY)}."
        )

    resource, select_fields = _TARGET_TO_QUERY[target_type]
    select_clause = ", ".join(select_fields)

    where_parts = []
    if "metrics." in filter_clause and "segments.date" not in filter_clause:
        where_parts.append(gaql_date_clause(start, end))
    where_parts.append(f"({filter_clause})")
    where_clause = " AND ".join(where_parts)

    return f"""
        SELECT {select_clause}
        FROM {resource}
        WHERE {where_clause}
        LIMIT 101
    """.strip()
