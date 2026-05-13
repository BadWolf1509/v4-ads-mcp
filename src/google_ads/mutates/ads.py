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
        # NOTE (Sprint 3b.16 F16 fix): proto-plus repeated message fields use
        # .append() with new typed instance, NOT .add() (raw protobuf API).
        # Smoke test in Nutry caught this — tests passed with ProtoFieldCapture
        # mock supporting .add() but real google-ads SDK doesn't.
        for headline_text in rsa_spec["headlines"]:
            h = client.get_type("AdTextAsset")
            h.text = headline_text
            rsa.headlines.append(h)
        for desc_text in rsa_spec["descriptions"]:
            d = client.get_type("AdTextAsset")
            d.text = desc_text
            rsa.descriptions.append(d)
        for url in rsa_spec["final_urls"]:
            ad.final_urls.append(url)
        if "path1" in rsa_spec:
            rsa.path1 = rsa_spec["path1"]
        if "path2" in rsa_spec:
            rsa.path2 = rsa_spec["path2"]
        operations.append(op)
    return operations


@register_builder("update_rsa")
def build_update_rsa(client: Any, customer_id: str, payload: dict[str, Any]) -> list[Any]:
    """payload: {updates: [{ad_id, headlines?, descriptions?, final_urls?,
                            path1?, path2?}]}

    Uses AdService (not AdGroupAdService) — Ad resource holds RSA content.
    Builds update_mask from set fields. Provided list replaces existing
    (proto-plus semantics with field_mask).

    Note (Sprint 3b.17 F16 lesson): repeated message fields use .append()
    with typed instance, NOT .add(). Mirrors create_rsa pattern.
    """
    operations: list[Any] = []
    ad_service = client.get_service("AdService")
    for spec in payload["updates"]:
        op = client.get_type("MutateOperation")
        ad_op = op.ad_operation
        ad = ad_op.update
        ad.resource_name = ad_service.ad_path(customer_id, spec["ad_id"])
        rsa = ad.responsive_search_ad
        mask_paths: list[str] = []
        if "headlines" in spec:
            for headline_text in spec["headlines"]:
                h = client.get_type("AdTextAsset")
                h.text = headline_text
                rsa.headlines.append(h)
            mask_paths.append("responsive_search_ad.headlines")
        if "descriptions" in spec:
            for desc_text in spec["descriptions"]:
                d = client.get_type("AdTextAsset")
                d.text = desc_text
                rsa.descriptions.append(d)
            mask_paths.append("responsive_search_ad.descriptions")
        if "final_urls" in spec:
            for url in spec["final_urls"]:
                ad.final_urls.append(url)
            mask_paths.append("final_urls")
        if "path1" in spec:
            rsa.path1 = spec["path1"]
            mask_paths.append("responsive_search_ad.path1")
        if "path2" in spec:
            rsa.path2 = spec["path2"]
            mask_paths.append("responsive_search_ad.path2")
        client.copy_from(ad_op.update_mask, FieldMask(paths=mask_paths))
        operations.append(op)
    return operations
