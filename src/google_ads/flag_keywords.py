"""Pure client-side keyword flag computation (Sprint 3b.30 audit_quality_score).

3 flags:
- candidate_pause: QS<=2 + impressions>=min_impressions + clicks==0 (waste)
- candidate_promote_exact: QS>=7 + match_type=='BROAD' + conversions>=1 (promote pra EXACT)
- duplicate_intent: keyword_text exato em multi ad_groups (amplification only --
  so adicionado quando outra flag ja presente; reduz false positives)

Pure function, zero Google SDK imports -- testable standalone.
"""

from dataclasses import dataclass

# QS thresholds são Google research convention (não config — guard rail hardcoded).
# Documented em CLAUDE.md/spec section 2 "Thresholds QS hardcoded".
_QS_PAUSE_MAX = 2  # QS 1-2 = waste signal (Google: low relevance)
_QS_PROMOTE_MIN = 7  # QS 7-10 = high relevance (Google: promote para EXACT)


@dataclass(frozen=True, slots=True)
class KeywordRow:
    """Input row from keyword_view GAQL query (Google-agnostic representation)."""

    ad_group_id: str
    ad_group_name: str
    campaign_name: str
    keyword_id: str
    keyword_text: str
    match_type: str  # "EXACT" | "PHRASE" | "BROAD"
    quality_score: int  # 1-10
    impressions: int
    clicks: int
    conversions: int
    cost_brl: float


@dataclass(frozen=True, slots=True)
class FlaggedKeyword:
    """Output: KeywordRow + flags tuple."""

    ad_group_id: str
    ad_group_name: str
    campaign_name: str
    keyword_id: str
    keyword_text: str
    match_type: str
    quality_score: int
    impressions: int
    clicks: int
    conversions: int
    cost_brl: float
    flags: tuple[str, ...]


def flag_keywords(
    rows: list[KeywordRow],
    *,
    min_impressions: int,
    limit: int,
) -> tuple[list[FlaggedKeyword], int]:
    """Compute flags, amplify duplicates, sort, truncate.

    Args:
        rows: list[KeywordRow] from GAQL keyword_view.
        min_impressions: threshold pra candidate_pause flag (Google low-volume guard).
        limit: max output entries (truncate sort post-amplification).

    Returns:
        (flagged_list, total_pre_truncate). Sorted by quality_score ASC,
        impressions DESC tie-break.
    """
    # 1. Per-row primary flags
    candidates: list[tuple[KeywordRow, list[str]]] = []
    for row in rows:
        flags: list[str] = []
        if (
            row.quality_score <= _QS_PAUSE_MAX
            and row.impressions >= min_impressions
            and row.clicks == 0
        ):
            flags.append("candidate_pause")
        if (
            row.quality_score >= _QS_PROMOTE_MIN
            and row.match_type == "BROAD"
            and row.conversions >= 1
        ):
            flags.append("candidate_promote_exact")
        if flags:
            candidates.append((row, flags))

    # 2. text -> ad_groups map (apenas em flagged subset; noise reduction)
    text_to_adgroups: dict[str, set[str]] = {}
    for row, _ in candidates:
        text_to_adgroups.setdefault(row.keyword_text, set()).add(row.ad_group_id)

    # 3. Amplify with duplicate_intent (only if text em >1 ad_group).
    # Copia primary_flags pra all_flags (evita mutar lista de candidates —
    # trap pra futuro maintainer se adicionar 2nd pass sobre candidates).
    flagged: list[FlaggedKeyword] = []
    for row, primary_flags in candidates:
        all_flags = list(primary_flags)
        if len(text_to_adgroups[row.keyword_text]) > 1:
            all_flags.append("duplicate_intent")
        flagged.append(
            FlaggedKeyword(
                ad_group_id=row.ad_group_id,
                ad_group_name=row.ad_group_name,
                campaign_name=row.campaign_name,
                keyword_id=row.keyword_id,
                keyword_text=row.keyword_text,
                match_type=row.match_type,
                quality_score=row.quality_score,
                impressions=row.impressions,
                clicks=row.clicks,
                conversions=row.conversions,
                cost_brl=row.cost_brl,
                flags=tuple(all_flags),
            )
        )

    # 4. Sort: QS ASC, impressions DESC tie-break
    flagged.sort(key=lambda f: (f.quality_score, -f.impressions))

    # 5. Truncate, return total pre-truncate
    total = len(flagged)
    return flagged[:limit], total
