"""Mutate builder for adding campaign-level negative keywords."""

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
