"""Static catalog of GAQL resources + their commonly attributable fields.

Used by list_gaql_resources tool. NOT a complete reflection of the SDK; this
is a curated set covering the 15 most-used resources at V4. Future expansion
can scrape from the SDK or Google's reference docs.
"""

from typing import Any

RESOURCES: dict[str, Any] = {
    "customer": {
        "description": "Conta Google Ads (level mais alto).",
        "fields": [
            "customer.id",
            "customer.descriptive_name",
            "customer.currency_code",
            "customer.time_zone",
            "customer.test_account",
            "customer.manager",
            "customer.status",
            "metrics.impressions",
            "metrics.clicks",
            "metrics.cost_micros",
            "metrics.conversions",
            "metrics.conversions_value",
            "segments.date",
            "segments.device",
        ],
    },
    "customer_client": {
        "description": "Contas filhas de um MCC (usar com login_customer_id no MCC).",
        "fields": [
            "customer_client.id",
            "customer_client.descriptive_name",
            "customer_client.currency_code",
            "customer_client.time_zone",
            "customer_client.test_account",
            "customer_client.manager",
        ],
    },
    "campaign": {
        "description": "Campanhas (Search, Display, Video, Performance Max, etc).",
        "fields": [
            "campaign.id",
            "campaign.name",
            "campaign.status",
            "campaign.advertising_channel_type",
            "campaign.bidding_strategy_type",
            "campaign.start_date",
            "campaign.end_date",
            "campaign_budget.amount_micros",
            "campaign_budget.delivery_method",
            "metrics.impressions",
            "metrics.clicks",
            "metrics.cost_micros",
            "metrics.conversions",
            "metrics.conversions_value",
            "segments.date",
        ],
    },
    "ad_group": {
        "description": "Grupos de anuncios dentro de campanhas.",
        "fields": [
            "ad_group.id",
            "ad_group.name",
            "ad_group.status",
            "ad_group.cpc_bid_micros",
            "ad_group.type",
            "campaign.id",
            "campaign.name",
            "metrics.impressions",
            "metrics.clicks",
            "metrics.cost_micros",
            "metrics.conversions",
            "metrics.conversions_value",
        ],
    },
    "keyword_view": {
        "description": "Performance + Quality Score por palavra-chave.",
        "fields": [
            "ad_group_criterion.criterion_id",
            "ad_group_criterion.keyword.text",
            "ad_group_criterion.keyword.match_type",
            "ad_group_criterion.status",
            "ad_group_criterion.quality_info.quality_score",
            "ad_group_criterion.quality_info.creative_quality_score",
            "ad_group_criterion.quality_info.post_click_quality_score",
            "ad_group_criterion.quality_info.search_predicted_ctr",
            "ad_group_criterion.position_estimates.first_page_cpc_micros",
            "ad_group_criterion.position_estimates.top_of_page_cpc_micros",
            "ad_group.id",
            "ad_group.name",
            "campaign.id",
            "campaign.name",
            "metrics.impressions",
            "metrics.clicks",
            "metrics.cost_micros",
            "metrics.conversions",
            "metrics.conversions_value",
        ],
    },
    "search_term_view": {
        "description": "Termos de busca reais que dispararam anuncios (com status added/excluded/none).",
        "fields": [
            "search_term_view.search_term",
            "search_term_view.status",
            "ad_group.id",
            "ad_group.name",
            "campaign.id",
            "campaign.name",
            "metrics.impressions",
            "metrics.clicks",
            "metrics.cost_micros",
            "metrics.conversions",
            "metrics.conversions_value",
        ],
    },
    "ad_group_ad": {
        "description": "Anuncios. RSA + DSA + outros tipos.",
        "fields": [
            "ad_group_ad.ad.id",
            "ad_group_ad.status",
            "ad_group_ad.ad.type",
            "ad_group_ad.ad.responsive_search_ad.headlines",
            "ad_group_ad.ad.responsive_search_ad.descriptions",
            "ad_group_ad.ad.final_urls",
            "ad_group_ad.ad_strength",
            "ad_group.id",
            "ad_group.name",
            "campaign.id",
            "campaign.name",
            "metrics.impressions",
            "metrics.clicks",
            "metrics.cost_micros",
            "metrics.conversions",
            "metrics.conversions_value",
        ],
    },
    "campaign_criterion": {
        "description": "Criterios em nivel de campanha (negativas, locations, devices).",
        "fields": [
            "campaign_criterion.criterion_id",
            "campaign_criterion.type",
            "campaign_criterion.negative",
            "campaign_criterion.keyword.text",
            "campaign_criterion.keyword.match_type",
            "campaign_criterion.location.geo_target_constant",
            "campaign_criterion.device.type",
            "campaign.id",
            "campaign.name",
        ],
    },
    "ad_group_audience_view": {
        "description": "Audiencias aplicadas em ad groups.",
        "fields": [
            "ad_group_audience_view.resource_name",
            "ad_group_criterion.criterion_id",
            "ad_group_criterion.user_list.user_list",
            "ad_group_criterion.user_interest.user_interest_category",
            "ad_group.id",
            "ad_group.name",
            "campaign.id",
            "campaign.name",
            "metrics.impressions",
            "metrics.clicks",
            "metrics.cost_micros",
            "metrics.conversions",
        ],
    },
    "conversion_action": {
        "description": "Acoes de conversao configuradas na conta.",
        "fields": [
            "conversion_action.id",
            "conversion_action.name",
            "conversion_action.status",
            "conversion_action.category",
            "conversion_action.type",
            "conversion_action.counting_type",
            "conversion_action.attribution_model_settings.attribution_model",
            "conversion_action.value_settings.default_value",
        ],
    },
    "geographic_view": {
        "description": "Performance por geografia (country_criterion_id).",
        "fields": [
            "geographic_view.country_criterion_id",
            "geographic_view.location_type",
            "metrics.impressions",
            "metrics.clicks",
            "metrics.cost_micros",
            "metrics.conversions",
        ],
    },
    "recommendation": {
        "description": (
            "Recomendacoes pendentes do Google Ads. "
            "Campos de impacto (base_metrics.*, potential_metrics.*) sao "
            "selectable_with-restricted no v24 e devem ser consultados por tipo "
            "especifico via run_gaql."
        ),
        "fields": [
            "recommendation.resource_name",
            "recommendation.type",
            "recommendation.dismissed",
        ],
    },
    "asset": {
        "description": "Assets (sitelinks, callouts, structured snippets, etc).",
        "fields": [
            "asset.id",
            "asset.name",
            "asset.type",
            "asset.sitelink_asset.link_text",
            "asset.sitelink_asset.description1",
            "asset.callout_asset.callout_text",
        ],
    },
    "campaign_budget": {
        "description": "Orcamentos de campanha (compartilhados ou nao).",
        "fields": [
            "campaign_budget.id",
            "campaign_budget.name",
            "campaign_budget.amount_micros",
            "campaign_budget.delivery_method",
            "campaign_budget.explicitly_shared",
            "campaign_budget.status",
        ],
    },
    "user_list": {
        "description": "Listas de remarketing / Customer Match.",
        "fields": [
            "user_list.id",
            "user_list.name",
            "user_list.description",
            "user_list.size_for_display",
            "user_list.size_for_search",
            "user_list.membership_status",
            "user_list.membership_life_span",
        ],
    },
}


# Common segment fields applicable across many resources
SEGMENTS: list[str] = [
    "segments.date",
    "segments.device",
    "segments.day_of_week",
    "segments.hour",
    "segments.month",
    "segments.quarter",
    "segments.week",
    "segments.year",
    "segments.click_type",
    "segments.conversion_action_category",
    "segments.conversion_action_name",
    "segments.network_type",
]
