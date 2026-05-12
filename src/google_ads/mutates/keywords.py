"""Mutate builders for keyword (ad_group_criterion) operations."""

from typing import Any

from google.protobuf.field_mask_pb2 import FieldMask

from src.google_ads.mutates._common import register_builder


@register_builder("update_keyword_status")
def build_update_keyword_status(
    client: Any, customer_id: str, payload: dict[str, Any]
) -> list[Any]:
    """payload: {keywords: [{ad_group_id: str, criterion_id: str}], new_status: 'ENABLED'|'PAUSED'|'REMOVED'}"""
    new_status = payload["new_status"].upper()
    operations = []
    criterion_service = client.get_service("AdGroupCriterionService")
    status_enum = client.enums.AdGroupCriterionStatusEnum
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
            FieldMask(paths=["status"]),
        )
        operations.append(op)
    return operations


@register_builder("update_keyword_bid")
def build_update_keyword_bid(client: Any, customer_id: str, payload: dict[str, Any]) -> list[Any]:
    """payload: {bids: [{ad_group_id: str, criterion_id: str, new_cpc_bid_micros: int}]}

    new_cpc_bid_micros == 0 means "clear the override, inherit from ad group".
    The Google Ads API rejects literal cpc_bid_micros=0 as "Too low" because BRL
    accounts enforce a minimum CPC. To clear, leave the field unset on the proto
    but keep "cpc_bid_micros" in the update_mask — the API reads that as "set to
    default / clear" for optional int64 fields with presence semantics.
    """
    operations = []
    criterion_service = client.get_service("AdGroupCriterionService")
    for bid_change in payload["bids"]:
        op = client.get_type("MutateOperation")
        crit_op = op.ad_group_criterion_operation
        crit = crit_op.update
        crit.resource_name = criterion_service.ad_group_criterion_path(
            customer_id, bid_change["ad_group_id"], bid_change["criterion_id"]
        )
        new_micros = int(bid_change["new_cpc_bid_micros"])
        if new_micros > 0:
            crit.cpc_bid_micros = new_micros
        # else: don't set — mask alone signals "clear override"
        client.copy_from(
            crit_op.update_mask,
            FieldMask(paths=["cpc_bid_micros"]),
        )
        operations.append(op)
    return operations


@register_builder("add_keywords")
def build_add_keywords(client: Any, customer_id: str, payload: dict[str, Any]) -> list[Any]:
    """payload: {ad_group_id: str, keywords: [{text: str, match_type: 'EXACT'|'PHRASE'|'BROAD', cpc_bid_micros?: int}]}

    Each keyword becomes one MutateOperation with ad_group_criterion_operation.create:
      - ad_group resource path (1 ad_group per call by design)
      - status = ENABLED (new criteria active by default; gestor pauses via update_keyword_status if needed)
      - keyword.text + keyword.match_type
      - optional cpc_bid_micros (omit = inherit ad_group default bid)
    """
    ad_group_id = payload["ad_group_id"]
    keywords = payload["keywords"]
    operations: list[Any] = []

    ad_group_service = client.get_service("AdGroupService")
    ad_group_resource = ad_group_service.ad_group_path(customer_id, ad_group_id)
    match_type_enum = client.enums.KeywordMatchTypeEnum
    status_enabled = client.enums.AdGroupCriterionStatusEnum.ENABLED

    for kw in keywords:
        op = client.get_type("MutateOperation")
        crit_op = op.ad_group_criterion_operation
        crit = crit_op.create
        crit.ad_group = ad_group_resource
        crit.status = status_enabled
        crit.keyword.text = kw["text"]
        mt = kw["match_type"].upper()
        crit.keyword.match_type = match_type_enum[mt]
        if "cpc_bid_micros" in kw:
            crit.cpc_bid_micros = int(kw["cpc_bid_micros"])
        operations.append(op)

    return operations
