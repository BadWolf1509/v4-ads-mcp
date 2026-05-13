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


@register_builder("create_rsa")
def build_create_rsa(client: Any, customer_id: str, payload: dict[str, Any]) -> list[Any]:
    """payload: {rsas: [{ad_group_id, headlines[], descriptions[], final_urls[],
                        path1?, path2?, status?}]}

    Defaults: status=PAUSED. Headlines/descriptions/final_urls counts validated
    by JSONSchema layer (3-15/2-4/1+). path1/path2 only set if provided.
    """
    operations: list[Any] = []
    ag_service = client.get_service("AdGroupService")
    status_enum = client.enums.AdGroupAdStatusEnum
    for rsa_spec in payload["rsas"]:
        op = client.get_type("MutateOperation")
        ad_op = op.ad_group_ad_operation
        aga = ad_op.create
        aga.ad_group = ag_service.ad_group_path(customer_id, rsa_spec["ad_group_id"])
        aga.status = status_enum[rsa_spec.get("status", "PAUSED")]
        ad = aga.ad
        rsa = ad.responsive_search_ad
        for headline_text in rsa_spec["headlines"]:
            h = rsa.headlines.add()
            h.text = headline_text
        for desc_text in rsa_spec["descriptions"]:
            d = rsa.descriptions.add()
            d.text = desc_text
        for url in rsa_spec["final_urls"]:
            ad.final_urls.append(url)
        if "path1" in rsa_spec:
            rsa.path1 = rsa_spec["path1"]
        if "path2" in rsa_spec:
            rsa.path2 = rsa_spec["path2"]
        operations.append(op)
    return operations
