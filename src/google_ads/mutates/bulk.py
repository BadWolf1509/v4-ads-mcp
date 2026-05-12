"""Bulk-pause mutate builder for bulk_pause_by_query.

Reads the dry-run-captured payload {target_type, entities} and emits
MutateOperation messages of the right oneof field per target_type. Each
entity is mutated with update_mask=['status'] and the appropriate
StatusEnum.PAUSED.
"""

from typing import Any

from google.protobuf.field_mask_pb2 import FieldMask

from src.google_ads.mutates._common import register_builder

_SUPPORTED_TARGETS = ("keyword", "ad", "campaign", "ad_group")


@register_builder("bulk_pause_by_query")
def build_bulk_pause(client: Any, customer_id: str, payload: dict[str, Any]) -> list[Any]:
    """payload: {target_type: 'keyword'|'ad'|'campaign'|'ad_group', entities: [...]}.

    Entity shape depends on target_type:
      keyword:   {ad_group_id: str, criterion_id: str}
      ad:        {ad_group_id: str, ad_id: str}
      campaign:  {campaign_id: str}
      ad_group:  {ad_group_id: str}

    Returns list[MutateOperation] — heterogeneous-safe (all-same target_type
    in one call, but the builder picks the right oneof field per row).
    """
    target_type = payload["target_type"]
    if target_type not in _SUPPORTED_TARGETS:
        raise ValueError(
            f"target_type='{target_type}' invalido. Aceitos: {list(_SUPPORTED_TARGETS)}."
        )

    entities = payload["entities"]
    operations: list[Any] = []
    mask = FieldMask(paths=["status"])

    if target_type == "keyword":
        service = client.get_service("AdGroupCriterionService")
        status_enum = client.enums.AdGroupCriterionStatusEnum
        for e in entities:
            op = client.get_type("MutateOperation")
            crit_op = op.ad_group_criterion_operation
            crit = crit_op.update
            crit.resource_name = service.ad_group_criterion_path(
                customer_id, e["ad_group_id"], e["criterion_id"]
            )
            crit.status = status_enum.PAUSED
            client.copy_from(crit_op.update_mask, mask)
            operations.append(op)
    elif target_type == "ad":
        service = client.get_service("AdGroupAdService")
        status_enum = client.enums.AdGroupAdStatusEnum
        for e in entities:
            op = client.get_type("MutateOperation")
            ad_op = op.ad_group_ad_operation
            ad_obj = ad_op.update
            ad_obj.resource_name = service.ad_group_ad_path(
                customer_id, e["ad_group_id"], e["ad_id"]
            )
            ad_obj.status = status_enum.PAUSED
            client.copy_from(ad_op.update_mask, mask)
            operations.append(op)
    elif target_type == "campaign":
        service = client.get_service("CampaignService")
        status_enum = client.enums.CampaignStatusEnum
        for e in entities:
            op = client.get_type("MutateOperation")
            camp_op = op.campaign_operation
            camp = camp_op.update
            camp.resource_name = service.campaign_path(customer_id, e["campaign_id"])
            camp.status = status_enum.PAUSED
            client.copy_from(camp_op.update_mask, mask)
            operations.append(op)
    elif target_type == "ad_group":
        service = client.get_service("AdGroupService")
        status_enum = client.enums.AdGroupStatusEnum
        for e in entities:
            op = client.get_type("MutateOperation")
            ag_op = op.ad_group_operation
            ag = ag_op.update
            ag.resource_name = service.ad_group_path(customer_id, e["ad_group_id"])
            ag.status = status_enum.PAUSED
            client.copy_from(ag_op.update_mask, mask)
            operations.append(op)

    return operations
