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
    """payload: {bids: [{ad_group_id: str, new_cpc_bid_micros: int}]}"""
    operations = []
    ad_group_service = client.get_service("AdGroupService")
    for bid_change in payload["bids"]:
        op = client.get_type("MutateOperation")
        ag_op = op.ad_group_operation
        ag = ag_op.update
        ag.resource_name = ad_group_service.ad_group_path(customer_id, bid_change["ad_group_id"])
        ag.cpc_bid_micros = int(bid_change["new_cpc_bid_micros"])
        client.copy_from(
            ag_op.update_mask,
            FieldMask(paths=["cpc_bid_micros"]),
        )
        operations.append(op)
    return operations
