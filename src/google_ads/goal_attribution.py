"""Pure client-side goal attribution audit (Sprint 3b.35 audit_goal_attribution).

Cruza conversion_action com customer_conversion_goal pra revelar biddable flag
por (category, origin) — pre-flight check antes de mexer em primary_for_goal
via update_conversion_action. Resolve falsa premissa "cosmético KPI" descoberta
em dogfood 2026-05-21 lição 47.

Pure function, zero Google SDK imports — testable standalone.
"""

from dataclasses import dataclass
from typing import Any

# Status filter: tool retorna apenas ENABLED actions (PAUSED/REMOVED não afetam Smart Bidding).
_INCLUDED_STATUSES = frozenset({"ENABLED"})

_WARNING_BIDDABLE_TRUE = (
    "biddable=true: promover Secondary→Primary AFETA Smart Bidding "
    "(action vira biddable em todas campaigns que usam esta "
    "category+origin). NÃO é cosmético KPI."
)


@dataclass(frozen=True, slots=True)
class ConversionActionRow:
    """Boundary input — dict de conversion_action GAQL converte pra cá."""

    id: str
    name: str
    category: str
    origin: str
    primary_for_goal: bool
    include_in_conversions_metric: bool
    status: str


@dataclass(frozen=True, slots=True)
class CustomerConversionGoalRow:
    """Boundary input — dict de customer_conversion_goal GAQL converte pra cá."""

    category: str
    origin: str
    biddable: bool


@dataclass(frozen=True, slots=True)
class ActionSummary:
    """Output action representation (subset de ConversionActionRow)."""

    id: str
    name: str
    include_in_conversions_metric: bool
    status: str


@dataclass(frozen=True, slots=True)
class OriginSummary:
    category: str
    origin: str
    biddable: bool
    warning: str | None
    primary_count: int
    secondary_count: int
    primary_actions: tuple[ActionSummary, ...]
    secondary_actions: tuple[ActionSummary, ...]


@dataclass(frozen=True, slots=True)
class GoalAttributionResult:
    customer_id: str
    category_filter: str | None
    origin_summary: dict[str, OriginSummary]
    total_actions_audited: int
    origins_audited: tuple[str, ...]
    categories_audited: tuple[str, ...]


def dict_to_conversion_action_row(d: dict[str, Any]) -> ConversionActionRow:
    """Convert conversion_action row dict to ConversionActionRow dataclass.

    Defensive: missing fields default to "" or False.
    """
    return ConversionActionRow(
        id=str(d.get("id", "")),
        name=str(d.get("name", "")),
        category=str(d.get("category", "")),
        origin=str(d.get("origin", "")),
        primary_for_goal=bool(d.get("primary_for_goal", False)),
        include_in_conversions_metric=bool(d.get("include_in_conversions_metric", False)),
        status=str(d.get("status", "")),
    )


def dict_to_customer_conversion_goal_row(d: dict[str, Any]) -> CustomerConversionGoalRow:
    """Convert customer_conversion_goal row dict to CustomerConversionGoalRow dataclass.

    Defensive: missing fields default to "" or False.
    """
    return CustomerConversionGoalRow(
        category=str(d.get("category", "")),
        origin=str(d.get("origin", "")),
        biddable=bool(d.get("biddable", False)),
    )


def audit_goal_attribution(
    actions: list[ConversionActionRow],
    goals: list[CustomerConversionGoalRow],
    *,
    category_filter: str | None,
    customer_id: str,
) -> GoalAttributionResult:
    """Aggregate conversion_actions by (category, origin), cross-ref biddable.

    Algorithm:
    1. Filter actions: status ∈ _INCLUDED_STATUSES (ENABLED-only) — defensive,
       complementa o `WHERE status='ENABLED'` server-side; protege contra
       Google retornar inadvertidamente PAUSED/REMOVED em edge cases.
       If category_filter, also filter by category.
    2. Build goals_lookup: {(category, origin): biddable} from goals list.
    3. Group filtered actions by (category, origin) tuple.
    4. Per group: split into primary_actions (primary_for_goal=true)
       + secondary_actions (primary_for_goal=false).
    5. Lookup biddable from goals_lookup; default False if absent (defensive).
    6. Generate warning_pt only if biddable=true (else None).
    7. Build origin_summary dict — key strategy:
       - if category_filter set: key = origin (e.g., "WEBSITE")
       - else: key = "{category}__{origin}" composite (e.g., "CONTACT__WEBSITE")
    8. Sort actions within primary/secondary lists by name ASC (stable display).
    9. Build metadata: total_actions_audited, origins_audited (sorted unique),
       categories_audited (sorted unique).

    Pure function — zero IO, zero Google SDK, fully testable.
    """
    # 1. Filter actions
    filtered: list[ConversionActionRow] = []
    for action in actions:
        if action.status not in _INCLUDED_STATUSES:
            continue
        if category_filter is not None and action.category != category_filter:
            continue
        filtered.append(action)

    # 2. Goals lookup
    goals_lookup: dict[tuple[str, str], bool] = {(g.category, g.origin): g.biddable for g in goals}

    # 3. Group by (category, origin)
    groups: dict[tuple[str, str], list[ConversionActionRow]] = {}
    for action in filtered:
        key = (action.category, action.origin)
        groups.setdefault(key, []).append(action)

    # 4-8. Build origin_summary
    origin_summary: dict[str, OriginSummary] = {}
    for (category, origin), group_actions in groups.items():
        # 4. Split primary/secondary
        primary = [a for a in group_actions if a.primary_for_goal]
        secondary = [a for a in group_actions if not a.primary_for_goal]

        # 5. Lookup biddable (default False)
        biddable = goals_lookup.get((category, origin), False)

        # 6. Warning only if biddable=true
        warning = _WARNING_BIDDABLE_TRUE if biddable else None

        # 8. Sort by name ASC
        primary_sorted = sorted(primary, key=lambda a: a.name)
        secondary_sorted = sorted(secondary, key=lambda a: a.name)

        # Build ActionSummary tuples
        primary_summaries = tuple(
            ActionSummary(
                id=a.id,
                name=a.name,
                include_in_conversions_metric=a.include_in_conversions_metric,
                status=a.status,
            )
            for a in primary_sorted
        )
        secondary_summaries = tuple(
            ActionSummary(
                id=a.id,
                name=a.name,
                include_in_conversions_metric=a.include_in_conversions_metric,
                status=a.status,
            )
            for a in secondary_sorted
        )

        # 7. Key strategy
        key_str = origin if category_filter is not None else f"{category}__{origin}"

        origin_summary[key_str] = OriginSummary(
            category=category,
            origin=origin,
            biddable=biddable,
            warning=warning,
            primary_count=len(primary_summaries),
            secondary_count=len(secondary_summaries),
            primary_actions=primary_summaries,
            secondary_actions=secondary_summaries,
        )

    # 9. Metadata
    total_audited = len(filtered)
    origins_audited = tuple(sorted({a.origin for a in filtered}))
    categories_audited = tuple(sorted({a.category for a in filtered}))

    return GoalAttributionResult(
        customer_id=customer_id,
        category_filter=category_filter,
        origin_summary=origin_summary,
        total_actions_audited=total_audited,
        origins_audited=origins_audited,
        categories_audited=categories_audited,
    )
