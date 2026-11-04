"""GAQL helper pra resolver criterion_id → keyword_text + match_type.

Usado por update_keyword_status dry-run preview (Sprint 3b.40 A1). So monta a query e
formata a linha; a execucao (`fetch_keyword_texts`) vive em `src/google_ads/preflight.py`.
"""

from typing import Any


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
    # `str(int(x))` e a defesa, nao o `pattern` do schema a montante (F87):
    # o builder e publico e o proximo chamador pode nao ter schema nenhum.
    ad_group_clause = ", ".join(str(int(x)) for x in ad_group_ids)
    criterion_clause = ", ".join(str(int(x)) for x in criterion_ids)
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
