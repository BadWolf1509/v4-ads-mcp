"""Mutate builders for audience attachment (AdGroupCriterion + CampaignCriterion)."""

from typing import Any

from src.google_ads.mutates._common import register_builder


@register_builder("apply_audience")
def build_apply_audience(client: Any, customer_id: str, payload: dict[str, Any]) -> list[Any]:
    """payload: {target_type: 'ad_group'|'campaign', mode: 'observation'|'exclusion',
                 attachments: [{target_id, audience_type, audience_resource_name, bid_modifier?}, ...]}

    Each attachment becomes one MutateOperation:
      - target_type='ad_group' → ad_group_criterion_operation.create with crit.ad_group path
      - target_type='campaign' → campaign_criterion_operation.create with crit.campaign path

    Common fields set on the criterion:
      - status = ENABLED
      - negative = (mode == 'exclusion')
      - user_list.user_list OR user_interest.user_interest_category (per audience_type)
      - bid_modifier (only when present AND mode == 'observation')
    """
    target_type = payload["target_type"]
    mode = payload["mode"]
    attachments = payload["attachments"]

    if target_type == "ad_group":
        path_service = client.get_service("AdGroupService")
        status_enabled = client.enums.AdGroupCriterionStatusEnum.ENABLED
    else:  # campaign
        path_service = client.get_service("CampaignService")
        status_enabled = client.enums.CampaignCriterionStatusEnum.ENABLED

    is_exclusion = mode == "exclusion"

    ops: list[Any] = []
    for att in attachments:
        op = client.get_type("MutateOperation")
        if target_type == "ad_group":
            crit_op = op.ad_group_criterion_operation
            crit = crit_op.create
            crit.ad_group = path_service.ad_group_path(customer_id, att["target_id"])
        else:
            crit_op = op.campaign_criterion_operation
            crit = crit_op.create
            crit.campaign = path_service.campaign_path(customer_id, att["target_id"])

        crit.status = status_enabled
        crit.negative = is_exclusion

        if att["audience_type"] == "user_list":
            crit.user_list.user_list = att["audience_resource_name"]
        else:  # user_interest
            crit.user_interest.user_interest_category = att["audience_resource_name"]

        if "bid_modifier" in att and not is_exclusion:
            crit.bid_modifier = float(att["bid_modifier"])

        ops.append(op)

    return ops


@register_builder("remove_audience")
def build_remove_audience(client: Any, customer_id: str, payload: dict[str, Any]) -> list[Any]:
    """payload: {target_type: 'ad_group'|'campaign', target_id: str, criterion_ids: [str]}

    Each criterion_id becomes one MutateOperation with remove (not create):
      - target_type='ad_group' → ad_group_criterion_operation.remove = resource_name
        Resource format: customers/{cid}/adGroupCriteria/{target_id}~{criterion_id}
      - target_type='campaign' → campaign_criterion_operation.remove = resource_name
        Resource format: customers/{cid}/campaignCriteria/{criterion_id}
        (FLAT path — campaign_criterion has no compound key)

    Critical correctness: AdGroupCriterion uses ~-compound key (ad_group_id~criterion_id),
    CampaignCriterion is flat (just criterion_id). Builder constructs paths inline.
    """
    target_type = payload["target_type"]
    target_id = payload["target_id"]
    criterion_ids = payload["criterion_ids"]

    ops: list[Any] = []
    for crit_id in criterion_ids:
        op = client.get_type("MutateOperation")
        if target_type == "ad_group":
            crit_op = op.ad_group_criterion_operation
            crit_op.remove = f"customers/{customer_id}/adGroupCriteria/{target_id}~{crit_id}"
        else:  # campaign
            crit_op = op.campaign_criterion_operation
            crit_op.remove = f"customers/{customer_id}/campaignCriteria/{crit_id}"
        ops.append(op)
    return ops
