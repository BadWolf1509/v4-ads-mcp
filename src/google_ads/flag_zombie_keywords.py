"""Pure client-side zombie keyword detection (Sprint 3b.36 audit_zombie_keywords).

Filtra keywords ENABLED com zero activity (impressions=0 AND clicks=0) em
window de N dias. Sort por (ad_group_name ASC, keyword_text ASC) pra
agrupar visualmente. Cleanup massivo recurring MO-JP (dogfood 19/05 lição 41+).

Pure function, zero Google SDK imports — testable standalone.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class KeywordRow:
    """Boundary input — dict de keyword_view GAQL converte pra cá."""

    ad_group_id: str
    ad_group_name: str
    ad_group_status: str  # "ENABLED" | "PAUSED" | "REMOVED" — F52 pra detectar órfãs cosméticas
    campaign_name: str
    keyword_id: str
    keyword_text: str
    match_type: str  # "EXACT" | "PHRASE" | "BROAD"
    impressions: int
    clicks: int
    cost_brl: float
    conversions: int
    status: str  # "ENABLED" expected (server-side filter)


@dataclass(frozen=True, slots=True)
class ZombieKeyword:
    """Output: KeywordRow flagged as zombie (impressions=0 AND clicks=0)."""

    ad_group_id: str
    ad_group_name: str
    ad_group_status: str  # F52: revela órfãs em ad_group REMOVED (no-op pra batch real)
    campaign_name: str
    keyword_id: str
    keyword_text: str
    match_type: str
    impressions: int
    clicks: int
    cost_brl: float
    conversions: int
    status: str


def flag_zombie_keywords(
    rows: list[KeywordRow],
    *,
    limit: int,
) -> tuple[list[ZombieKeyword], int]:
    """Filter zombies, sort, truncate.

    Args:
        rows: list[KeywordRow] from GAQL keyword_view (já filtered server-side
              por status=ENABLED + negative=FALSE).
        limit: max output entries.

    Returns:
        (zombies, total_pre_truncate). Sorted by ad_group_name ASC,
        keyword_text ASC.

    Algorithm:
    1. Filter: keep only rows com impressions == 0 AND clicks == 0 (pure waste).
    2. Sort: ad_group_name ASC, keyword_text ASC (stable visual grouping).
    3. Truncate to limit. Return (zombies, total_pre_truncate).

    Pure function — zero IO, zero Google SDK, fully testable.
    """
    zombies = [
        ZombieKeyword(
            ad_group_id=r.ad_group_id,
            ad_group_name=r.ad_group_name,
            ad_group_status=r.ad_group_status,
            campaign_name=r.campaign_name,
            keyword_id=r.keyword_id,
            keyword_text=r.keyword_text,
            match_type=r.match_type,
            impressions=r.impressions,
            clicks=r.clicks,
            cost_brl=r.cost_brl,
            conversions=r.conversions,
            status=r.status,
        )
        for r in rows
        if r.impressions == 0 and r.clicks == 0
    ]
    zombies.sort(key=lambda z: (z.ad_group_name, z.keyword_text))
    total = len(zombies)
    return zombies[:limit], total
