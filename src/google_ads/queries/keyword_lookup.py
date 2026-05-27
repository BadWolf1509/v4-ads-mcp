"""GAQL helper pra resolver criterion_id → keyword_text + match_type.

Usado por update_keyword_status dry-run preview (Sprint 3b.40 A1).
Returns partial dict if some pairs not found (no exception).
"""

from typing import Any
from uuid import UUID

from src.google_ads.reports import run_report


def build_keyword_text_lookup_query(
    keyword_pairs: list[tuple[str, str]],
) -> str:
    """Build GAQL pra fetch keyword_text + match_type per (ad_group_id, criterion_id).

    Args:
        keyword_pairs: list de (ad_group_id, criterion_id) — duplicates OK,
            query deduplicates implicit via IN clause + sort ASC for determinism.

    Returns:
        GAQL string sobre ad_group_criterion resource, sem date filter
        (resource é absolute state, não time-series).

    Raises:
        ValueError: if keyword_pairs is empty.

    Note: keyword_view é time-series (requires segments.date). ad_group_criterion
    é absolute state — não precisa date_range, mais barato.
    """
    if not keyword_pairs:
        raise ValueError("keyword_pairs cannot be empty")
    ad_group_ids = sorted({pair[0] for pair in keyword_pairs})
    criterion_ids = sorted({pair[1] for pair in keyword_pairs})
    ad_group_clause = ", ".join(ad_group_ids)
    criterion_clause = ", ".join(criterion_ids)
    return (
        "SELECT "
        "ad_group.id, "
        "ad_group_criterion.criterion_id, "
        "ad_group_criterion.keyword.text, "
        "ad_group_criterion.keyword.match_type "
        "FROM ad_group_criterion "
        f"WHERE ad_group.id IN ({ad_group_clause}) "
        f"AND ad_group_criterion.criterion_id IN ({criterion_clause})"
    )


def _lookup_row_formatter(row: Any) -> dict[str, Any]:
    """Parse SDK row → dict pra lookup index."""
    return {
        "ad_group_id": str(row.ad_group.id),
        "criterion_id": str(row.ad_group_criterion.criterion_id),
        "keyword_text": row.ad_group_criterion.keyword.text,
        "match_type": row.ad_group_criterion.keyword.match_type.name,
    }


async def fetch_keyword_texts(
    *,
    manager_id: UUID,
    session_id: UUID,
    customer_id: str,
    keyword_pairs: list[tuple[str, str]],
) -> dict[tuple[str, str], dict[str, str]]:
    """Resolve (ad_group_id, criterion_id) → {keyword_text, match_type}.

    Used by update_keyword_status DRY_RUN path pra preview sample.
    Graceful: returns partial dict if some pairs not found (no exception).

    Returns:
        dict keyed by (ad_group_id, criterion_id) tuple. Missing pairs
        simply absent from dict — caller iterates pairs e checks presence
        via `.get()`.
    """
    if not keyword_pairs:
        return {}
    query = build_keyword_text_lookup_query(keyword_pairs)
    rows = await run_report(
        manager_id=manager_id,
        session_id=session_id,
        customer_id=customer_id,
        query=query,
        row_formatter=_lookup_row_formatter,
        operation_name="keyword_text_lookup",
    )
    return {
        (r["ad_group_id"], r["criterion_id"]): {
            "keyword_text": r["keyword_text"],
            "match_type": r["match_type"],
        }
        for r in rows
    }
