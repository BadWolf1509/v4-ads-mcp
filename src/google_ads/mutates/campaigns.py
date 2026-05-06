"""Mutate builders for campaign operations.

Each builder is registered via @register_builder and turns a payload
dict (saved by the dry-run flow) into a list of MutateOperation messages
ready to send to GoogleAdsService.mutate.
"""

from typing import Any

from src.google_ads.mutates._common import register_builder


@register_builder("update_campaign_status")
def build_update_campaign_status(
    client: Any, customer_id: str, payload: dict[str, Any]
) -> list[Any]:
    """payload: {campaign_ids: [str], new_status: 'ENABLED'|'PAUSED'|'REMOVED'}"""
    new_status = payload["new_status"].upper()
    operations = []
    campaign_service = client.get_service("CampaignService")
    status_enum = client.enums.CampaignStatusEnum
    for cid in payload["campaign_ids"]:
        op = client.get_type("MutateOperation")
        campaign_op = op.campaign_operation
        campaign = campaign_op.update
        campaign.resource_name = campaign_service.campaign_path(customer_id, cid)
        campaign.status = status_enum[new_status]
        # Set field mask
        client.copy_from(
            campaign_op.update_mask,
            client.get_type("FieldMask")(paths=["status"]),
        )
        operations.append(op)
    return operations


@register_builder("update_campaign_budget")
def build_update_campaign_budget(
    client: Any, customer_id: str, payload: dict[str, Any]
) -> list[Any]:
    """payload: {campaign_budget_resource_name: str, new_amount_micros: int}

    The tool resolves campaign_id -> campaign_budget_resource_name BEFORE
    saving the payload, so this builder just applies the new amount.
    """
    op = client.get_type("MutateOperation")
    budget_op = op.campaign_budget_operation
    budget = budget_op.update
    budget.resource_name = payload["campaign_budget_resource_name"]
    budget.amount_micros = int(payload["new_amount_micros"])
    client.copy_from(
        budget_op.update_mask,
        client.get_type("FieldMask")(paths=["amount_micros"]),
    )
    return [op]


@register_builder("update_campaign_bidding")
def build_update_campaign_bidding(
    client: Any, customer_id: str, payload: dict[str, Any]
) -> list[Any]:
    """payload: {campaign_id, strategy: 'TARGET_CPA'|'TARGET_ROAS'|'MAXIMIZE_CONVERSIONS', target_value_micros?, target_roas?}"""
    op = client.get_type("MutateOperation")
    campaign_op = op.campaign_operation
    campaign = campaign_op.update
    campaign.resource_name = client.get_service("CampaignService").campaign_path(
        customer_id, payload["campaign_id"]
    )
    strategy = payload["strategy"].upper()
    if strategy == "TARGET_CPA":
        campaign.target_cpa.target_cpa_micros = int(payload["target_value_micros"])
        client.copy_from(
            campaign_op.update_mask,
            client.get_type("FieldMask")(paths=["target_cpa.target_cpa_micros"]),
        )
    elif strategy == "TARGET_ROAS":
        campaign.target_roas.target_roas = float(payload["target_roas"])
        client.copy_from(
            campaign_op.update_mask,
            client.get_type("FieldMask")(paths=["target_roas.target_roas"]),
        )
    elif strategy == "MAXIMIZE_CONVERSIONS":
        target_micros = int(payload.get("target_value_micros", 0))
        campaign.maximize_conversions.target_cpa_micros = target_micros
        client.copy_from(
            campaign_op.update_mask,
            client.get_type("FieldMask")(paths=["maximize_conversions.target_cpa_micros"]),
        )
    else:
        raise ValueError(f"Unsupported bidding strategy: {strategy}")
    return [op]
