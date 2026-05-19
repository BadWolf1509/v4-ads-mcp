"""Shared helpers for GAQL query construction."""

from __future__ import annotations

import contextlib
import json
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from src.google_ads.reports import run_report


class InvalidDateRangeError(ValueError):
    """Raised when a date range cannot be parsed."""


_PRESETS = {
    "TODAY",
    "YESTERDAY",
    "LAST_7_DAYS",
    "LAST_14_DAYS",
    "LAST_30_DAYS",
    "LAST_90_DAYS",
    "THIS_MONTH",
    "LAST_MONTH",
    "THIS_WEEK",
    "LAST_WEEK",
}


def _today() -> date:
    return datetime.now(UTC).date()


def _yesterday() -> date:
    return _today() - timedelta(days=1)


def parse_date_range(arg: str | dict[str, str]) -> tuple[date, date]:
    """Resolve a date_range param into (start_date, end_date) inclusive.

    Accepts either a preset string (e.g., 'LAST_7_DAYS') or an explicit
    dict {from: ISO_DATE, to: ISO_DATE}.

    Sprint 3b.20 safety net: if `arg` is a string that looks like a JSON object,
    parse it before applying preset matching. This recovers from cases where
    Claude serialized a dict as a JSON string (relatorio 2026-05-17 finding #1).
    """
    if isinstance(arg, str) and arg.strip().startswith("{"):
        with contextlib.suppress(ValueError):
            arg = json.loads(arg)
        # if parse failed, fall through to preset matching with original string

    if isinstance(arg, dict):
        try:
            start = date.fromisoformat(arg["from"])
            end = date.fromisoformat(arg["to"])
        except (KeyError, ValueError) as e:
            raise InvalidDateRangeError(f"Invalid date dict {arg}: {e}") from e
        if start > end:
            raise InvalidDateRangeError(f"date_range from ({start}) is after to ({end})")
        return start, end

    if not isinstance(arg, str):
        raise InvalidDateRangeError(f"date_range must be string or dict, got {type(arg)}")

    preset = arg.upper()
    if preset not in _PRESETS:
        raise InvalidDateRangeError(
            f"Unknown date_range preset '{preset}'. Valid presets: {', '.join(sorted(_PRESETS))}"
        )

    today = _today()
    yesterday = _yesterday()

    if preset == "TODAY":
        return today, today
    if preset == "YESTERDAY":
        return yesterday, yesterday
    if preset == "LAST_7_DAYS":
        return yesterday - timedelta(days=6), yesterday
    if preset == "LAST_14_DAYS":
        return yesterday - timedelta(days=13), yesterday
    if preset == "LAST_30_DAYS":
        return yesterday - timedelta(days=29), yesterday
    if preset == "LAST_90_DAYS":
        return yesterday - timedelta(days=89), yesterday
    if preset == "THIS_MONTH":
        return today.replace(day=1), yesterday
    if preset == "LAST_MONTH":
        first_this = today.replace(day=1)
        last_prev = first_this - timedelta(days=1)
        first_prev = last_prev.replace(day=1)
        return first_prev, last_prev
    if preset == "THIS_WEEK":
        # ISO week starts Monday; today.weekday() = 0 for Monday
        monday = today - timedelta(days=today.weekday())
        return monday, yesterday if yesterday >= monday else monday
    if preset == "LAST_WEEK":
        last_sunday = today - timedelta(days=today.weekday() + 1)
        last_monday = last_sunday - timedelta(days=6)
        return last_monday, last_sunday

    raise InvalidDateRangeError(f"Unhandled preset {preset}")  # unreachable


def resolve_date_window(
    date_range: str | dict[str, str] | None,
    start_date: str | None,
    end_date: str | None,
) -> tuple[date, date]:
    """Resolve date_range preset OR explicit start_date+end_date pair into (start, end).

    Precedence: if both start_date and end_date are provided, those win over date_range.
    Mismatched pair (only one of start_date/end_date) is rejected.

    Sprint 3b.20: replaces direct parse_date_range calls in tool bodies so that custom
    periods can be expressed via two top-level params (each with explicit `type: "string"`)
    instead of a single composite param without `type`, which caused Claude to serialize
    the dict as a JSON string and break the parser (relatorio 2026-05-17, finding #1).
    """
    if start_date is not None and end_date is None:
        raise InvalidDateRangeError("end_date e obrigatorio quando start_date e informado.")
    if end_date is not None and start_date is None:
        raise InvalidDateRangeError("start_date e obrigatorio quando end_date e informado.")
    if start_date is not None and end_date is not None:
        return parse_date_range({"from": start_date, "to": end_date})
    return parse_date_range(date_range if date_range is not None else "LAST_30_DAYS")


def get_comparison_range(start: date, end: date) -> tuple[date, date]:
    """Given a date range, return the immediately-previous period of equal length.

    Example: for [2026-04-08, 2026-04-14] (7 days), returns [2026-04-01, 2026-04-07].
    """
    period_days = (end - start).days + 1
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=period_days - 1)
    return prev_start, prev_end


def gaql_date_clause(start: date, end: date) -> str:
    """Format a GAQL `segments.date BETWEEN '...' AND '...'` clause."""
    return f"segments.date BETWEEN '{start.isoformat()}' AND '{end.isoformat()}'"


# Plural-form keys in sync with resource types Google Ads emits via change_event.
# Compound IDs (e.g., {campaign_id}~{criterion_id}) returned as-is — caller splits if needed.
# Sprint 3b.21: extracted from get_change_history.py for cross-tool reuse.
_RESOURCE_PLURAL_TO_TYPE: dict[str, str] = {
    "campaigns": "campaign",
    "adGroups": "ad_group",
    "adGroupAds": "ad_group_ad",
    "adGroupCriteria": "ad_group_criterion",
    "campaignCriteria": "campaign_criterion",
    "campaignBudgets": "campaign_budget",
    "biddingStrategies": "bidding_strategy",
    "conversionActions": "conversion_action",
    "customerNegativeCriteria": "customer_negative_criterion",
    "assets": "asset",
    "campaignAssets": "campaign_asset",
    "adGroupAssets": "ad_group_asset",
}


def parse_resource_path(path: str) -> tuple[str | None, str | None]:
    """Parse 'customers/{cid}/{resource_plural}/{id}[...]' into (resource_type, id).

    Returns:
      (resource_type, id) when path matches known pattern.
      (None, id) when plural is unknown but id is parseable.
      (None, None) when path is malformed.

    Adding a new resource type? Update `_RESOURCE_PLURAL_TO_TYPE` above.
    """
    parts = path.split("/")
    if len(parts) < 4 or parts[0] != "customers":
        return None, None
    resource_plural = parts[2]
    resource_id = parts[3] if len(parts) > 3 else None
    return _RESOURCE_PLURAL_TO_TYPE.get(resource_plural), resource_id


# Common metric SELECT fragments — reuse across many tools
METRIC_FIELDS = {
    "impressions": "metrics.impressions",
    "clicks": "metrics.clicks",
    "cost_micros": "metrics.cost_micros",
    "conversions": "metrics.conversions",
    "conversions_value": "metrics.conversions_value",
    "ctr": "metrics.ctr",
    "average_cpc": "metrics.average_cpc",
    "cost_per_conversion": "metrics.cost_per_conversion",
    "value_per_conversion": "metrics.value_per_conversion",
}


def micros_to_currency(micros: int | float) -> float:
    """Google Ads stores money in micros (millionths). 1_500_000 micros = R$ 1.50."""
    return round(micros / 1_000_000.0, 2)


def value_proxy_warning(conversions: float, conversions_value: float) -> str | None:
    """Returns warning string PT-BR if conversions_value == conversions (1:1 placeholder
    tracking), else None.

    Real revenue tracking would have value != count (unless every conversion is
    coincidentally R$ 1.00 — extremely unlikely). 1:1 ratio strong signals that
    conversion action uses default value=1.0 BRL placeholder, making ROAS misleading.

    Sprint 3b.7 (P1b dogfood UX-1 finding).
    """
    if conversions > 0 and conversions == conversions_value:
        return (
            "conversions_value == conversions (1:1 ratio). Tracking provavelmente "
            "sem revenue real — ROAS pode ser misleading."
        )
    return None


async def validate_manual_cpc_strategy(
    manager_id: UUID,
    session_id: UUID,
    customer_id: str,
    ad_group_ids: list[str],
) -> str | None:
    """Returns PT-BR error string if any ad_group is in non-MANUAL_CPC/ENHANCED_CPC
    campaign; else None.

    Performs 1 GAQL batch lookup. Whitelist {MANUAL_CPC, ENHANCED_CPC} matches
    strategies que honram cpc_bid_micros field (Google Ads API v23 docs:
    https://developers.google.com/google-ads/api/docs/campaigns/bidding/override-strategies).

    Sprint 3b.8 (P3 dogfood F12 finding — silent-acceptance bug family 6th variant).
    """
    if not ad_group_ids:
        return None

    ids_clause = ", ".join(ad_group_ids)
    query = (
        f"SELECT ad_group.id, campaign.id, campaign.name, "
        f"campaign.bidding_strategy_type "
        f"FROM ad_group WHERE ad_group.id IN ({ids_clause})"
    )

    def _format(row: Any) -> dict[str, str]:
        return {
            "ad_group_id": str(row.ad_group.id),
            "campaign_id": str(row.campaign.id),
            "campaign_name": row.campaign.name,
            "strategy": row.campaign.bidding_strategy_type.name,
        }

    rows = await run_report(
        manager_id=manager_id,
        session_id=session_id,
        customer_id=customer_id,
        query=query,
        row_formatter=_format,
        operation_name="validate_manual_cpc_strategy",
    )

    whitelist = {"MANUAL_CPC", "ENHANCED_CPC"}
    for r in rows:
        if r["strategy"] not in whitelist:
            return (
                f"Campaign '{r['campaign_name']}' (id {r['campaign_id']}) usa "
                f"bidding_strategy_type '{r['strategy']}'. Manual CPC bids sao "
                f"ignorados nesta estrategia (Google API silent-failure). Mude "
                f"para MANUAL_CPC via update_campaign_bidding, ou ajuste budget/"
                f"targeting via outras tools."
            )
    return None


async def validate_parent_campaigns_for_ad_group_create(
    manager_id: UUID,
    session_id: UUID,
    customer_id: str,
    ad_groups: list[dict[str, Any]],
) -> str | None:
    """Returns PT-BR error string if any parent campaign fails validation; else None.

    Validates per ad_group spec:
    1. Parent campaign exists
    2. campaign.status != REMOVED
    3. ad_group.type matches campaign.advertising_channel_type
       (SEARCH_STANDARD → SEARCH; SHOPPING_PRODUCT_ADS → SHOPPING)
    4. If cpc_bid_micros provided, campaign.bidding_strategy_type IN
       {MANUAL_CPC, ENHANCED_CPC} (F12 lesson — Sprint 3b.8)

    Performs 1 GAQL batch lookup for all unique campaign_ids.
    Returns first-found offender error message (matches Sprint 3b.5 A3 pattern).
    """
    campaign_ids = list({ag["campaign_id"] for ag in ad_groups})
    if not campaign_ids:
        return None

    ids_clause = ", ".join(campaign_ids)
    query = (
        f"SELECT campaign.id, campaign.name, campaign.status, "
        f"campaign.advertising_channel_type, campaign.bidding_strategy_type "
        f"FROM campaign WHERE campaign.id IN ({ids_clause})"
    )

    def _format(row: Any) -> dict[str, str]:
        return {
            "campaign_id": str(row.campaign.id),
            "campaign_name": row.campaign.name,
            "status": row.campaign.status.name,
            "channel_type": row.campaign.advertising_channel_type.name,
            "strategy": row.campaign.bidding_strategy_type.name,
        }

    rows = await run_report(
        manager_id=manager_id,
        session_id=session_id,
        customer_id=customer_id,
        query=query,
        row_formatter=_format,
        operation_name="validate_parent_campaigns_for_ad_group_create",
    )

    by_id = {r["campaign_id"]: r for r in rows}

    type_to_channel = {
        "SEARCH_STANDARD": "SEARCH",
        "SHOPPING_PRODUCT_ADS": "SHOPPING",
    }
    manual_strategies = {"MANUAL_CPC", "ENHANCED_CPC"}

    for ag in ad_groups:
        cid = ag["campaign_id"]
        camp = by_id.get(cid)

        if camp is None:
            return f"Campaign {cid} nao encontrada na conta. Verifique o campaign_id."

        if camp["status"] == "REMOVED":
            return (
                f"Campaign '{camp['campaign_name']}' (id {cid}) esta REMOVED. "
                f"Nao e possivel criar ad_group em campaign removida."
            )

        ag_type = ag.get("type", "SEARCH_STANDARD")
        expected_channel = type_to_channel.get(ag_type)
        if expected_channel and camp["channel_type"] != expected_channel:
            return (
                f"Ad_group type '{ag_type}' incompativel com campaign "
                f"'{camp['campaign_name']}' (id {cid}) — advertising_channel_type "
                f"= '{camp['channel_type']}'. Use type matching o canal."
            )

        if "cpc_bid_micros" in ag and camp["strategy"] not in manual_strategies:
            return (
                f"Campaign '{camp['campaign_name']}' (id {cid}) usa "
                f"bidding_strategy_type '{camp['strategy']}'. cpc_bid_micros "
                f"sera ignorado silenciosamente pela Google nesta estrategia "
                f"(Sprint 3b.8 F12 lesson). Remova cpc_bid_micros do payload "
                f"ou mude campaign para MANUAL_CPC."
            )

    return None


async def validate_parent_ad_groups_for_rsa_create(
    manager_id: UUID,
    session_id: UUID,
    customer_id: str,
    rsas: list[dict[str, Any]],
) -> str | None:
    """Returns PT-BR error string if any parent ad_group fails validation; else None.

    Validates per RSA spec:
    1. Parent ad_group exists
    2. ad_group.status != REMOVED
    3. ad_group's parent campaign.advertising_channel_type IN {SEARCH, SEARCH_PARTNERS}

    Performs 1 GAQL batch lookup for unique ad_group_ids.
    Returns first-found offender error message (matches Sprint 3b.5 A3 pattern).
    """
    ad_group_ids = list({rsa["ad_group_id"] for rsa in rsas})
    if not ad_group_ids:
        return None

    ids_clause = ", ".join(ad_group_ids)
    query = (
        f"SELECT ad_group.id, ad_group.name, ad_group.status, "
        f"campaign.id, campaign.name, campaign.advertising_channel_type "
        f"FROM ad_group WHERE ad_group.id IN ({ids_clause})"
    )

    def _format(row: Any) -> dict[str, str]:
        return {
            "ad_group_id": str(row.ad_group.id),
            "ad_group_name": row.ad_group.name,
            "ad_group_status": row.ad_group.status.name,
            "campaign_id": str(row.campaign.id),
            "campaign_name": row.campaign.name,
            "channel_type": row.campaign.advertising_channel_type.name,
        }

    rows = await run_report(
        manager_id=manager_id,
        session_id=session_id,
        customer_id=customer_id,
        query=query,
        row_formatter=_format,
        operation_name="validate_parent_ad_groups_for_rsa_create",
    )

    by_id = {r["ad_group_id"]: r for r in rows}
    valid_channels = {"SEARCH", "SEARCH_PARTNERS"}

    for rsa in rsas:
        agid = rsa["ad_group_id"]
        ag = by_id.get(agid)

        if ag is None:
            return f"Ad_group {agid} nao encontrado na conta. Verifique o ad_group_id."

        if ag["ad_group_status"] == "REMOVED":
            return (
                f"Ad_group '{ag['ad_group_name']}' (id {agid}) esta REMOVED. "
                f"Nao e possivel criar RSA em ad_group removido."
            )

        if ag["channel_type"] not in valid_channels:
            return (
                f"Ad_group '{ag['ad_group_name']}' (id {agid}) pertence a campaign "
                f"'{ag['campaign_name']}' com advertising_channel_type "
                f"'{ag['channel_type']}'. RSAs (Responsive Search Ads) so funcionam "
                f"em campaigns SEARCH ou SEARCH_PARTNERS."
            )

    return None


async def validate_existing_rsas_for_update(
    manager_id: UUID,
    session_id: UUID,
    customer_id: str,
    updates: list[dict[str, Any]],
) -> str | None:
    """Returns PT-BR error string if any ad fails validation; else None.

    Validates per update spec:
    1. Ad exists
    2. ad.type == RESPONSIVE_SEARCH_AD (cannot update other types via this tool)
    3. Parent ad_group.status != REMOVED
    4. Parent campaign.advertising_channel_type IN {SEARCH, SEARCH_PARTNERS}

    Performs 1 GAQL batch lookup for unique ad_ids.
    Returns first-found offender error message.
    """
    ad_ids = list({u["ad_id"] for u in updates})
    if not ad_ids:
        return None

    ids_clause = ", ".join(ad_ids)
    query = (
        f"SELECT ad_group_ad.ad.id, ad_group_ad.ad.type, "
        f"ad_group.id, ad_group.name, ad_group.status, "
        f"campaign.id, campaign.name, campaign.advertising_channel_type "
        f"FROM ad_group_ad WHERE ad_group_ad.ad.id IN ({ids_clause})"
    )

    def _format(row: Any) -> dict[str, str]:
        return {
            "ad_id": str(row.ad_group_ad.ad.id),
            "ad_type": row.ad_group_ad.ad.type.name,
            "ad_group_id": str(row.ad_group.id),
            "ad_group_name": row.ad_group.name,
            "ad_group_status": row.ad_group.status.name,
            "campaign_id": str(row.campaign.id),
            "campaign_name": row.campaign.name,
            "channel_type": row.campaign.advertising_channel_type.name,
        }

    rows = await run_report(
        manager_id=manager_id,
        session_id=session_id,
        customer_id=customer_id,
        query=query,
        row_formatter=_format,
        operation_name="validate_existing_rsas_for_update",
    )

    by_id = {r["ad_id"]: r for r in rows}
    valid_channels = {"SEARCH", "SEARCH_PARTNERS"}

    for u in updates:
        aid = u["ad_id"]
        ad = by_id.get(aid)

        if ad is None:
            return f"Ad {aid} nao encontrado na conta. Verifique o ad_id."

        if ad["ad_type"] != "RESPONSIVE_SEARCH_AD":
            return (
                f"Ad {aid} tem type '{ad['ad_type']}', nao RESPONSIVE_SEARCH_AD. "
                f"update_rsa so suporta RSAs — outros types (ETA legacy, Display, "
                f"Video) precisam de tools dedicados."
            )

        if ad["ad_group_status"] == "REMOVED":
            return (
                f"Ad_group '{ad['ad_group_name']}' (id {ad['ad_group_id']}) parent "
                f"do Ad {aid} esta REMOVED. Nao e possivel atualizar RSA em "
                f"ad_group removido."
            )

        if ad["channel_type"] not in valid_channels:
            return (
                f"Campaign '{ad['campaign_name']}' (id {ad['campaign_id']}) parent "
                f"do Ad {aid} tem channel_type '{ad['channel_type']}'. RSAs so "
                f"funcionam em campaigns SEARCH ou SEARCH_PARTNERS."
            )

    return None


async def validate_conversion_action_create(
    manager_id: UUID,
    session_id: UUID,
    customer_id: str,
    actions: list[dict[str, Any]],
) -> str | None:
    """Returns PT-BR error string if any ConversionAction name already exists; else None.

    Validates name uniqueness per Google API constraint:
    - ConversionAction.name is unique per customer (server-side enforced)

    Performs 1 GAQL batch lookup over input names. Returns first-found
    offender error message in INPUT order (deterministic UX).

    Mirrors Sprint 3b.16 validate_parent_ad_groups_for_rsa_create pattern.
    """
    if not actions:
        return None

    names = [a["name"] for a in actions]
    # Single-quote-escape per GAQL string literal syntax (doubled-quote pattern,
    # same as SQL). Names may contain "'" → must be escaped to avoid injection.
    quoted = ", ".join("'" + n.replace("'", "''") + "'" for n in names)
    query = (
        f"SELECT conversion_action.name FROM conversion_action "
        f"WHERE conversion_action.name IN ({quoted})"
    )

    def _format(row: Any) -> dict[str, str]:
        return {"conversion_action_name": row.conversion_action.name}

    rows = await run_report(
        manager_id=manager_id,
        session_id=session_id,
        customer_id=customer_id,
        query=query,
        row_formatter=_format,
        operation_name="validate_conversion_action_create",
    )

    existing = {r["conversion_action_name"] for r in rows}

    for a in actions:
        if a["name"] in existing:
            return (
                f"ConversionAction '{a['name']}' ja existe na conta. "
                "Use outro nome (nomes sao unicos por customer)."
            )

    return None


async def validate_campaign_for_value_rule_set(
    manager_id: UUID,
    session_id: UUID,
    customer_id: str,
    campaign_id: str,
) -> str | None:
    """Returns PT-BR error string if campaign invalid for value rule set attachment; else None.

    Validates:
    1. Campaign exists
    2. campaign.status != REMOVED

    Sprint 3b.19B — pre-flight for create_conversion_value_rule_set when
    attachment_type=CAMPAIGN.
    """
    # int() cast: fail-fast on non-numeric input + defense against future callers
    # bypassing schema validation. campaign.id is numeric so bare interpolation
    # is safe (no quotes needed).
    query = (
        f"SELECT campaign.id, campaign.name, campaign.status "
        f"FROM campaign WHERE campaign.id = {int(campaign_id)}"
    )

    def _format(row: Any) -> dict[str, str]:
        return {
            "campaign_id": str(row.campaign.id),
            "campaign_name": row.campaign.name,
            "campaign_status": row.campaign.status.name,
        }

    rows = await run_report(
        manager_id=manager_id,
        session_id=session_id,
        customer_id=customer_id,
        query=query,
        row_formatter=_format,
        operation_name="validate_campaign_for_value_rule_set",
    )

    if not rows:
        return f"Campaign {campaign_id} nao encontrada na conta. Verifique o campaign_id."

    camp = rows[0]
    if camp["campaign_status"] == "REMOVED":
        return (
            f"Campaign '{camp['campaign_name']}' (id {camp['campaign_id']}) "
            f"esta REMOVED. Nao e possivel anexar RuleSet a campaign removida."
        )

    return None


async def validate_geo_target_constants_br_only(
    manager_id: UUID,
    session_id: UUID,
    customer_id: str,
    geo_paths: list[str],
) -> str | None:
    """Returns PT-BR error string if any geo target is non-BR; else None.

    Validates each geo_target_constant resource_name:
    1. Exists in Google Ads (queryable via GAQL)
    2. country_code == "BR" (V4 invariant — all V4 accounts in Brazil)

    Performs 1 GAQL batch lookup. Returns first-offender error in INPUT order.

    Sprint 3b.19B (initial) + 3b.24 (renamed generic) — pre-flight for any
    create_* tool that accepts BR-only geo_target_constant paths.
    """
    if not geo_paths:
        return None

    # Single-quote-escape per GAQL string literal syntax (mirror 3b.19A helper)
    quoted = ", ".join("'" + p.replace("'", "''") + "'" for p in geo_paths)
    query = (
        f"SELECT geo_target_constant.resource_name, "
        f"geo_target_constant.country_code, geo_target_constant.name "
        f"FROM geo_target_constant "
        f"WHERE geo_target_constant.resource_name IN ({quoted})"
    )

    def _format(row: Any) -> dict[str, str]:
        return {
            "resource_name": row.geo_target_constant.resource_name,
            "country_code": row.geo_target_constant.country_code,
            "name": row.geo_target_constant.name,
        }

    rows = await run_report(
        manager_id=manager_id,
        session_id=session_id,
        customer_id=customer_id,
        query=query,
        row_formatter=_format,
        operation_name="validate_geo_target_constants_br_only",
    )

    by_path = {r["resource_name"]: r for r in rows}

    for path in geo_paths:
        row = by_path.get(path)
        if row is None:
            return f"Geo target '{path}' nao encontrado. Verifique o resource path."
        if row["country_code"] != "BR":
            return (
                f"Geo target '{row['name']}' ({path}) tem country_code "
                f"'{row['country_code']}', esperado 'BR' (V4 invariant: todas "
                "contas V4 sao do Brasil)."
            )

    return None


async def validate_conversion_action_for_upload(
    *,
    manager_id: UUID,
    session_id: UUID,
    customer_id: str,
    conversion_action_id: str,
) -> str | None:
    """GAQL pre-flight: conversion_action exists + type=UPLOAD_CLICKS + status != REMOVED.

    Sprint 3b.26 — pre-flight for import_offline_conversions tool.
    Returns PT-BR error message OR None if valid.
    """
    query = (
        "SELECT conversion_action.id, conversion_action.type, conversion_action.status "
        "FROM conversion_action "
        f"WHERE conversion_action.id = {conversion_action_id}"
    )

    def _format(row: Any) -> dict[str, Any]:
        return {
            "conversion_action": {
                "id": str(row.conversion_action.id),
                "type": row.conversion_action.type.name
                if hasattr(row.conversion_action.type, "name")
                else str(row.conversion_action.type),
                "status": row.conversion_action.status.name
                if hasattr(row.conversion_action.status, "name")
                else str(row.conversion_action.status),
            }
        }

    rows = await run_report(
        manager_id=manager_id,
        session_id=session_id,
        customer_id=customer_id,
        query=query,
        row_formatter=_format,
        operation_name="validate_conversion_action_for_upload",
    )

    if not rows:
        return (
            f"conversion_action_id={conversion_action_id} não existe em customer_id={customer_id}"
        )

    row = rows[0]["conversion_action"]
    if row["type"] != "UPLOAD_CLICKS":
        return (
            f"conversion_action_id={conversion_action_id} tem type={row['type']}; "
            f"UploadClickConversions requer type=UPLOAD_CLICKS. Crie ConversionAction "
            f"nova via create_conversion_action com type=UPLOAD_CLICKS."
        )

    if row["status"] == "REMOVED":
        return f"conversion_action_id={conversion_action_id} está REMOVED; não aceita uploads."

    return None
