"""Mutate builders for ad_group operations."""

from typing import Any

from google.protobuf.field_mask_pb2 import FieldMask

from src.google_ads.mutates._common import register_builder


@register_builder("update_ad_group_status")
def build_update_ad_group_status(
    client: Any, customer_id: str, payload: dict[str, Any]
) -> list[Any]:
    """payload: {ad_group_ids: [str], new_status: 'ENABLED'|'PAUSED'|'REMOVED'}"""
    new_status = payload["new_status"].upper()
    operations = []
    ad_group_service = client.get_service("AdGroupService")
    status_enum = client.enums.AdGroupStatusEnum
    for agid in payload["ad_group_ids"]:
        op = client.get_type("MutateOperation")
        ag_op = op.ad_group_operation
        ag = ag_op.update
        ag.resource_name = ad_group_service.ad_group_path(customer_id, agid)
        ag.status = status_enum[new_status]
        client.copy_from(
            ag_op.update_mask,
            FieldMask(paths=["status"]),
        )
        operations.append(op)
    return operations


@register_builder("update_ad_group_bid")
def build_update_ad_group_bid(client: Any, customer_id: str, payload: dict[str, Any]) -> list[Any]:
    """payload: {bids: [{ad_group_id: str, new_cpc_bid_micros: int}]}

    new_cpc_bid_micros == 0 means "clear the override, inherit from campaign".
    See update_keyword_bid builder for the rationale on field-mask-without-value.
    """
    operations = []
    ad_group_service = client.get_service("AdGroupService")
    for bid_change in payload["bids"]:
        op = client.get_type("MutateOperation")
        ag_op = op.ad_group_operation
        ag = ag_op.update
        ag.resource_name = ad_group_service.ad_group_path(customer_id, bid_change["ad_group_id"])
        new_micros = int(bid_change["new_cpc_bid_micros"])
        if new_micros > 0:
            ag.cpc_bid_micros = new_micros
        # else: don't set — mask alone signals "clear override"
        client.copy_from(
            ag_op.update_mask,
            FieldMask(paths=["cpc_bid_micros"]),
        )
        operations.append(op)
    return operations


@register_builder("create_ad_group")
def build_create_ad_group(client: Any, customer_id: str, payload: dict[str, Any]) -> list[Any]:
    """payload: {ad_groups: [{campaign_id, name, type?, status?, cpc_bid_micros?}]}

    Defaults: type=SEARCH_STANDARD, status=PAUSED. cpc_bid_micros optional
    (only valid in MANUAL_CPC/ENHANCED_CPC campaigns — pre-flight in tool
    validates via validate_parent_campaigns_for_ad_group_create).

    Note: Google's AdGroup proto uses `type_` (trailing underscore) because
    `type` is Python reserved word.
    """
    operations = []
    campaign_service = client.get_service("CampaignService")
    type_enum = client.enums.AdGroupTypeEnum
    status_enum = client.enums.AdGroupStatusEnum
    for ag_spec in payload["ad_groups"]:
        op = client.get_type("MutateOperation")
        ag_op = op.ad_group_operation
        ag = ag_op.create
        ag.name = ag_spec["name"]
        ag.campaign = campaign_service.campaign_path(customer_id, ag_spec["campaign_id"])
        ag.type_ = type_enum[ag_spec.get("type", "SEARCH_STANDARD")]
        ag.status = status_enum[ag_spec.get("status", "PAUSED")]
        if "cpc_bid_micros" in ag_spec:
            ag.cpc_bid_micros = ag_spec["cpc_bid_micros"]
        operations.append(op)
    return operations
