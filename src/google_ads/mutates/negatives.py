"""Mutate builders for campaign-level negative keywords (add and remove)."""

from typing import Any

from src.google_ads.mutates._common import register_builder

_MATCH_TYPE_MAP = {
    "EXACT": "EXACT",
    "PHRASE": "PHRASE",
    "BROAD": "BROAD",
}


@register_builder("add_negative_keywords")
def build_add_negative_keywords(
    client: Any, customer_id: str, payload: dict[str, Any]
) -> list[Any]:
    """payload: {campaign_id: str, keywords: [{text: str, match_type: 'EXACT'|'PHRASE'|'BROAD'}]}"""
    campaign_id = payload["campaign_id"]
    keywords = payload["keywords"]

    operations = []
    campaign_service = client.get_service("CampaignService")
    match_type_enum = client.enums.KeywordMatchTypeEnum
    campaign_resource = campaign_service.campaign_path(customer_id, campaign_id)

    for kw in keywords:
        text = kw["text"]
        mt = _MATCH_TYPE_MAP.get(kw["match_type"].upper(), "EXACT")
        op = client.get_type("MutateOperation")
        crit_op = op.campaign_criterion_operation
        criterion = crit_op.create
        criterion.campaign = campaign_resource
        criterion.negative = True
        criterion.keyword.text = text
        criterion.keyword.match_type = match_type_enum[mt]
        operations.append(op)

    return operations


@register_builder("remove_negative_keywords")
def build_remove_negative_keywords(
    client: Any, customer_id: str, payload: dict[str, Any]
) -> list[Any]:
    """payload: {campaign_id: str, criterion_ids: [str]}"""
    campaign_id = payload["campaign_id"]
    criterion_ids = payload["criterion_ids"]

    operations = []
    cc_service = client.get_service("CampaignCriterionService")

    for crit_id in criterion_ids:
        op = client.get_type("MutateOperation")
        crit_op = op.campaign_criterion_operation
        crit_op.remove = cc_service.campaign_criterion_path(customer_id, campaign_id, crit_id)
        operations.append(op)

    return operations


@register_builder("add_negatives_from_search_terms")
def build_add_negatives_from_search_terms(
    client: Any, customer_id: str, payload: dict[str, Any]
) -> list[Any]:
    """Build mutate operations for negatives derived from search_terms_report.

    payload: {
      negatives: [
        {
          search_term: str,
          match_type: 'EXACT' | 'PHRASE' | 'BROAD' (default 'EXACT'),
          scope: 'campaign' | 'ad_group' | 'shared_set',
          scope_id: str (the id of the campaign / ad_group / shared_set)
        }
      ]
    }

    Returns list of MutateOperation messages — heterogeneous (mixes
    campaign_criterion_operation, ad_group_criterion_operation,
    shared_set_criterion_operation as needed by each row's scope).
    """
    negatives = payload["negatives"]
    operations: list[Any] = []

    match_type_enum = client.enums.KeywordMatchTypeEnum
    campaign_service = client.get_service("CampaignService")
    ad_group_service = client.get_service("AdGroupService")
    shared_set_service = client.get_service("SharedSetService")

    for n in negatives:
        text = n["search_term"]
        mt_raw = n.get("match_type", "EXACT").upper()
        mt = _MATCH_TYPE_MAP.get(mt_raw, "EXACT")
        scope = n["scope"]
        scope_id = n["scope_id"]

        op = client.get_type("MutateOperation")

        if scope == "campaign":
            crit_op = op.campaign_criterion_operation
            criterion = crit_op.create
            criterion.campaign = campaign_service.campaign_path(customer_id, scope_id)
            criterion.negative = True
            criterion.keyword.text = text
            criterion.keyword.match_type = match_type_enum[mt]
        elif scope == "ad_group":
            crit_op = op.ad_group_criterion_operation
            criterion = crit_op.create
            criterion.ad_group = ad_group_service.ad_group_path(customer_id, scope_id)
            criterion.negative = True
            criterion.keyword.text = text
            criterion.keyword.match_type = match_type_enum[mt]
        elif scope == "shared_set":
            crit_op = op.shared_criterion_operation
            criterion = crit_op.create
            criterion.shared_set = shared_set_service.shared_set_path(customer_id, scope_id)
            criterion.keyword.text = text
            criterion.keyword.match_type = match_type_enum[mt]
        else:
            raise ValueError(
                f"Unknown scope '{scope}' — expected 'campaign', 'ad_group', or 'shared_set'"
            )

        operations.append(op)

    return operations
