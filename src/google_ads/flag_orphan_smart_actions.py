"""Pure client-side orphan ConversionAction detection (Sprint 3b.37 audit_orphan_smart_actions).

Filtra ConversionActions ENABLED com zero activity (all_conversions=0.0) em
window de N dias. Sort por (category, origin, name) ASC pra agrupar visualmente.
Cleanup recurring MO-JP (dogfood 19/05 lição 41+).

Pure function, zero Google SDK imports — testable standalone.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ConversionActionRow:
    """Boundary input — dict de conversion_action GAQL converte pra cá."""

    conversion_action_id: str
    name: str
    category: str
    origin: str
    primary_for_goal: bool
    status: str
    all_conversions: float


@dataclass(frozen=True, slots=True)
class OrphanAction:
    """Output: ConversionAction flagged como orphan (all_conversions=0)."""

    conversion_action_id: str
    name: str
    category: str
    origin: str
    primary_for_goal: bool
    status: str
    all_conversions: float


def flag_orphan_smart_actions(
    rows: list[ConversionActionRow],
    *,
    limit: int,
) -> tuple[list[OrphanAction], int]:
    """Filter orphans, sort, truncate.

    Args:
        rows: list[ConversionActionRow] from GAQL conversion_action (já filtered
              server-side por status=ENABLED + optional category).
        limit: max output entries.

    Returns:
        (orphans, total_pre_truncate). Sorted by category ASC, origin ASC, name ASC.

    Algorithm:
    1. Filter: keep only rows com all_conversions == 0.0 (zero conversion activity).
    2. Sort: category ASC, origin ASC, name ASC (visual grouping).
    3. Truncate to limit. Return (orphans, total_pre_truncate).

    Pure function — zero IO, zero Google SDK, fully testable.
    """
    orphans = [
        OrphanAction(
            conversion_action_id=r.conversion_action_id,
            name=r.name,
            category=r.category,
            origin=r.origin,
            primary_for_goal=r.primary_for_goal,
            status=r.status,
            all_conversions=r.all_conversions,
        )
        for r in rows
        if r.all_conversions == 0.0
    ]
    orphans.sort(key=lambda o: (o.category, o.origin, o.name))
    total = len(orphans)
    return orphans[:limit], total
