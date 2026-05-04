"""Mutate builders for keyword (ad_group_criterion) operations."""

from typing import Any

from src.google_ads.mutates._common import register_builder


@register_builder("update_keyword_status")
def build_update_keyword_status(
    client: Any, customer_id: str, payload: dict[str, Any]
) -> list[Any]:
    """payload: {keywords: [{ad_group_id: str, criterion_id: str}], new_status: 'ENABLED'|'PAUSED'|'REMOVED'}"""
    new_status = payload["new_status"].upper()
    operations = []
    criterion_service = client.get_service("AdGroupCriterionService")
    status_enum = client.enums.AdGroupCriterionStatusEnum.AdGroupCriterionStatus
    for kw in payload["keywords"]:
        op = client.get_type("MutateOperation")
        crit_op = op.ad_group_criterion_operation
        crit = crit_op.update
        crit.resource_name = criterion_service.ad_group_criterion_path(
            customer_id, kw["ad_group_id"], kw["criterion_id"]
        )
        crit.status = status_enum[new_status]
        client.copy_from(
            crit_op.update_mask,
            client.get_type("FieldMask")(paths=["status"]),
        )
        operations.append(op)
    return operations


@register_builder("update_keyword_bid")
def build_update_keyword_bid(client: Any, customer_id: str, payload: dict[str, Any]) -> list[Any]:
    """payload: {bids: [{ad_group_id: str, criterion_id: str, new_cpc_bid_micros: int}]}"""
    operations = []
    criterion_service = client.get_service("AdGroupCriterionService")
    for bid_change in payload["bids"]:
        op = client.get_type("MutateOperation")
        crit_op = op.ad_group_criterion_operation
        crit = crit_op.update
        crit.resource_name = criterion_service.ad_group_criterion_path(
            customer_id, bid_change["ad_group_id"], bid_change["criterion_id"]
        )
        crit.cpc_bid_micros = int(bid_change["new_cpc_bid_micros"])
        client.copy_from(
            crit_op.update_mask,
            client.get_type("FieldMask")(paths=["cpc_bid_micros"]),
        )
        operations.append(op)
    return operations
