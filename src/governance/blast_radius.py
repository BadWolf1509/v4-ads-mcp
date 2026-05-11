"""Blast radius classifier — decides auto-apply vs require-confirmation per operation.

Defaults are conservative. Unknown operations always require confirmation.
Each rule cites the spec section it implements (§7.1).
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class RiskLevel(StrEnum):
    AUTO = "auto"
    CONFIRM = "confirm"


@dataclass(slots=True, frozen=True)
class RiskClassification:
    level: RiskLevel
    reason: str  # Human-readable PT-BR explanation


# Threshold constants from spec §7.1
_BULK_THRESHOLD = 5
_BID_DELTA_PCT_THRESHOLD = 20.0


def _bulk_status_classify(operation: str, target_count: int) -> RiskClassification:
    if target_count <= 0:
        return RiskClassification(
            RiskLevel.CONFIRM,
            f"{operation}: target_count={target_count} desconhecido — confirmar por seguranca",
        )
    if target_count == 1:
        return RiskClassification(
            RiskLevel.AUTO,
            f"{operation}: single entity — auto",
        )
    if target_count <= _BULK_THRESHOLD:
        return RiskClassification(
            RiskLevel.AUTO,
            f"{operation}: bulk pequeno ({target_count} entities <= {_BULK_THRESHOLD}) — auto",
        )
    return RiskClassification(
        RiskLevel.CONFIRM,
        f"{operation}: more than {_BULK_THRESHOLD} entities ({target_count}) — confirmar",
    )


def _bid_classify(operation: str, target_count: int, max_delta_pct: float) -> RiskClassification:
    if target_count <= 0:
        return RiskClassification(
            RiskLevel.CONFIRM,
            f"{operation}: target_count={target_count} desconhecido — confirmar",
        )
    if max_delta_pct > _BID_DELTA_PCT_THRESHOLD:
        return RiskClassification(
            RiskLevel.CONFIRM,
            f"{operation}: variacao maxima {max_delta_pct:.1f}% > 20% — confirmar",
        )
    if target_count > _BULK_THRESHOLD:
        return RiskClassification(
            RiskLevel.CONFIRM,
            f"{operation}: more than {_BULK_THRESHOLD} entities ({target_count}) — confirmar",
        )
    return RiskClassification(
        RiskLevel.AUTO,
        f"{operation}: small variation ({max_delta_pct:.1f}%) AND {target_count} entities — auto",
    )


def classify(*, operation: str, params: dict[str, Any]) -> RiskClassification:
    """Classify a mutation operation as auto-apply or requires-confirmation.

    `params` is a dict like {target_count: int, delta_pct?: float, max_delta_pct?: float}.
    """
    target_count = int(params.get("target_count", 0))

    # Status changes (campaign/ad_group/keyword) — bulk-aware
    if operation in (
        "update_campaign_status",
        "update_ad_group_status",
        "update_keyword_status",
    ):
        return _bulk_status_classify(operation, target_count)

    # Budget mutations — always confirm (spec §7.1)
    if operation == "update_campaign_budget":
        return RiskClassification(
            RiskLevel.CONFIRM,
            "Mudanca de orcamento de campanha — confirmar sempre (budget)",
        )

    # Bidding strategy mutations — always confirm
    if operation == "update_campaign_bidding":
        return RiskClassification(
            RiskLevel.CONFIRM,
            "Mudanca de estrategia de bidding — confirmar sempre",
        )

    # Bid mutations (ad_group_bid, keyword_bid) — variation+count aware
    if operation in ("update_ad_group_bid", "update_keyword_bid"):
        max_delta_pct = float(params.get("max_delta_pct", 100.0))  # unknown = high
        return _bid_classify(operation, target_count, max_delta_pct)

    # Negatives — safe, always auto (spec §7.1)
    if operation in (
        "add_negative_keywords",
        "remove_negative_keywords",
        "add_negatives_from_search_terms",
    ):
        return RiskClassification(
            RiskLevel.AUTO,
            f"{operation} ({target_count} negatives) — auto, negatives raramente quebram",
        )

    # Recommendations — Google's own suggestions; auto-apply
    if operation in ("apply_recommendation", "dismiss_recommendation"):
        return RiskClassification(
            RiskLevel.AUTO,
            f"{operation} — auto, recommendation flow do Google",
        )

    # Unknown operation — default safe to confirm
    return RiskClassification(
        RiskLevel.CONFIRM,
        f"{operation}: unknown operation — default seguro: confirmar",
    )
