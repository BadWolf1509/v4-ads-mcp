"""Pure client-side competitor brand matching (Sprint 3b.31).

Match algorithm: substring case-insensitive contra positive keywords +
search terms. Aggregate cost wasted + sugere negative keywords (EXACT +
PHRASE per brand matched).

Pure function, zero Google SDK imports — testable standalone.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class KeywordRow:
    """Positive keyword da query keyword_view (negative=FALSE, status=ENABLED)."""

    ad_group_id: str
    ad_group_name: str
    campaign_name: str
    keyword_id: str
    keyword_text: str
    match_type: str  # "EXACT" | "PHRASE" | "BROAD"


@dataclass(frozen=True, slots=True)
class SearchTermRow:
    """Search term real query do search_term_view com metrics."""

    search_term: str
    ad_group_name: str
    campaign_name: str
    impressions: int
    clicks: int
    cost_brl: float


@dataclass(frozen=True, slots=True)
class MatchedKeyword:
    """KeywordRow + matched_brand + status."""

    ad_group_id: str
    ad_group_name: str
    campaign_name: str
    keyword_id: str
    keyword_text: str
    match_type: str
    matched_brand: str
    status: str  # always "ENABLED" em V0


@dataclass(frozen=True, slots=True)
class MatchedSearchTerm:
    """SearchTermRow + matched_brand."""

    search_term: str
    matched_brand: str
    ad_group_name: str
    campaign_name: str
    impressions: int
    clicks: int
    cost_brl: float


@dataclass(frozen=True, slots=True)
class SuggestedNegative:
    """Suggestion pra add_negative_keywords (V4 manual apply)."""

    text: str
    match_type: str  # "EXACT" | "PHRASE"
    reason: str


def normalize_brand(brand: str) -> str:
    """Lowercase + strip pra comparison consistente."""
    return brand.strip().lower()


def _find_matching_brand(text: str, normalized_brands: list[str]) -> str | None:
    """Return first brand (insertion order) que é substring de text.lower(), else None."""
    text_lower = text.lower()
    for brand in normalized_brands:
        if brand in text_lower:
            return brand
    return None


def match_competitor_brands(
    *,
    keyword_rows: list[KeywordRow],
    search_term_rows: list[SearchTermRow],
    competitor_brands: list[str],
    limit: int,
) -> tuple[
    list[MatchedKeyword],
    list[MatchedSearchTerm],
    list[SuggestedNegative],
    dict[str, int | bool],
    float,
]:
    """Match keywords + search terms vs brands; aggregate cost; suggest negatives.

    Pure function — zero Google SDK imports; testable standalone.

    Args:
        keyword_rows: positive keywords da query keyword_view (ENABLED + negative=FALSE).
        search_term_rows: search terms da query search_term_view (date-filtered).
        competitor_brands: lista de brand names (gestor passa marcas locais).
        limit: max entries por lista (positive_keywords + search_terms separadamente).

    Returns:
        Tuple of (matched_keywords_truncated, matched_search_terms_truncated,
                  suggested_negatives, totals_dict, total_cost_wasted_brl).

        totals_dict keys: positive_count, positive_truncated, search_count,
                          search_truncated, suggested_count.
    """
    # 1. Normalize brands (preserve insertion order)
    normalized = [normalize_brand(b) for b in competitor_brands]

    # 2. Match positive keywords
    matched_kw: list[MatchedKeyword] = []
    for row in keyword_rows:
        brand = _find_matching_brand(row.keyword_text, normalized)
        if brand:
            matched_kw.append(
                MatchedKeyword(
                    ad_group_id=row.ad_group_id,
                    ad_group_name=row.ad_group_name,
                    campaign_name=row.campaign_name,
                    keyword_id=row.keyword_id,
                    keyword_text=row.keyword_text,
                    match_type=row.match_type,
                    matched_brand=brand,
                    status="ENABLED",
                )
            )

    # 3. Match search terms + aggregate cost
    matched_st: list[MatchedSearchTerm] = []
    total_cost = 0.0
    for st_row in search_term_rows:
        brand = _find_matching_brand(st_row.search_term, normalized)
        if brand:
            matched_st.append(
                MatchedSearchTerm(
                    search_term=st_row.search_term,
                    matched_brand=brand,
                    ad_group_name=st_row.ad_group_name,
                    campaign_name=st_row.campaign_name,
                    impressions=st_row.impressions,
                    clicks=st_row.clicks,
                    cost_brl=st_row.cost_brl,
                )
            )
            total_cost += st_row.cost_brl

    # 4. Sort
    matched_kw.sort(key=lambda k: (k.matched_brand, k.ad_group_name))
    matched_st.sort(key=lambda s: -s.cost_brl)

    # 5. Per-brand stats pra suggested_negatives reasons
    pos_count: dict[str, int] = {}
    st_count: dict[str, int] = {}
    st_cost: dict[str, float] = {}
    for k in matched_kw:
        pos_count[k.matched_brand] = pos_count.get(k.matched_brand, 0) + 1
    for s in matched_st:
        st_count[s.matched_brand] = st_count.get(s.matched_brand, 0) + 1
        st_cost[s.matched_brand] = st_cost.get(s.matched_brand, 0.0) + s.cost_brl

    # 6. Suggested negatives — apenas pra brands com hit (alphabetical)
    suggested: list[SuggestedNegative] = []
    matched_brands_with_hit = sorted(set(pos_count.keys()) | set(st_count.keys()))
    for brand in matched_brands_with_hit:
        p = pos_count.get(brand, 0)
        st = st_count.get(brand, 0)
        cost = st_cost.get(brand, 0.0)
        suggested.append(
            SuggestedNegative(
                text=brand,
                match_type="EXACT",
                reason=(
                    f"Brand competidora encontrada em {p} keyword(s) positive "
                    f"+ {st} search term(s) (R$ {cost:.2f} cost)"
                ),
            )
        )
        suggested.append(
            SuggestedNegative(
                text=brand,
                match_type="PHRASE",
                reason="Brand competidora — PHRASE bloqueia qualquer query contendo o termo",
            )
        )

    # 7. Truncate + build totals
    pos_total = len(matched_kw)
    st_total = len(matched_st)
    totals: dict[str, int | bool] = {
        "positive_count": pos_total,
        "positive_truncated": pos_total > limit,
        "search_count": st_total,
        "search_truncated": st_total > limit,
        "suggested_count": len(suggested),
    }

    return (
        matched_kw[:limit],
        matched_st[:limit],
        suggested,
        totals,
        total_cost,
    )
