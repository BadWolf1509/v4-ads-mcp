"""Mutate builders for ad_group_ad (individual ad) operations."""

from typing import Any

from google.protobuf.field_mask_pb2 import FieldMask

from src.google_ads.mutates._common import register_builder


@register_builder("update_ad_status")
def build_update_ad_status(client: Any, customer_id: str, payload: dict[str, Any]) -> list[Any]:
    """payload: {ads: [{ad_group_id: str, ad_id: str}], new_status: 'ENABLED'|'PAUSED'|'REMOVED'}"""
    new_status = payload["new_status"].upper()
    operations: list[Any] = []
    ad_service = client.get_service("AdGroupAdService")
    status_enum = client.enums.AdGroupAdStatusEnum
    for ad in payload["ads"]:
        op = client.get_type("MutateOperation")
        ad_op = op.ad_group_ad_operation
        ad_obj = ad_op.update
        ad_obj.resource_name = ad_service.ad_group_ad_path(
            customer_id, ad["ad_group_id"], ad["ad_id"]
        )
        ad_obj.status = status_enum[new_status]
        client.copy_from(
            ad_op.update_mask,
            FieldMask(paths=["status"]),
        )
        operations.append(op)
    return operations
