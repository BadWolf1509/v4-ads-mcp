"""Mutate builders for campaign operations.

Each builder is registered via @register_builder and turns a payload
dict (saved by the dry-run flow) into a list of MutateOperation messages
ready to send to GoogleAdsService.mutate.
"""

from typing import Any

from google.protobuf.field_mask_pb2 import FieldMask

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
            FieldMask(paths=["status"]),
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
        FieldMask(paths=["amount_micros"]),
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
            FieldMask(paths=["target_cpa.target_cpa_micros"]),
        )
    elif strategy == "TARGET_ROAS":
        campaign.target_roas.target_roas = float(payload["target_roas"])
        client.copy_from(
            campaign_op.update_mask,
            FieldMask(paths=["target_roas.target_roas"]),
        )
    elif strategy == "MAXIMIZE_CONVERSIONS":
        target_micros = int(payload.get("target_value_micros", 0))
        campaign.maximize_conversions.target_cpa_micros = target_micros
        client.copy_from(
            campaign_op.update_mask,
            FieldMask(paths=["maximize_conversions.target_cpa_micros"]),
        )
    else:
        raise ValueError(f"Unsupported bidding strategy: {strategy}")
    return [op]


def _brl_to_micros(brl: float) -> int:
    """Convert BRL to micros (1 BRL = 1_000_000 micros).

    Sprint 3b.24 — used by build_create_campaign for budget + bidding strategy
    targets. Other create patterns use similar conversion (e.g., create_conversion_action).
    """
    return int(brl * 1_000_000)


@register_builder("create_campaign")
def build_create_campaign(client: Any, customer_id: str, payload: dict[str, Any]) -> list[Any]:
    """Build N+M+2 chained operations for create_campaign (Sprint 3b.24).

    payload schema (post-_validate_payload_shape):
      name: str
      bidding_strategy: {type: str, target_cpa_brl?: float, target_roas?: float,
                         cpc_bid_ceiling_brl?: float}
                         # enhanced_cpc removed F35 Sprint 3b.24.4
      daily_budget_brl: float
      geo_targets: list[str]  (geoTargetConstants/{id} paths)
      start_date?: str  (YYYY-MM-DD)
      end_date?: str    (YYYY-MM-DD)

    Returns list[MutateOperation] in order:
      [0] campaign_budget_operation.create (temp resource: campaignBudgets/-1)
      [1] campaign_operation.create (temp resource: campaigns/-2, refs budget -1)
      [2..N+1] campaign_criterion_operation.create × N (locations, ref campaign -2)
      [N+2] campaign_criterion_operation.create (PT language, ref campaign -2)

    Chained mutation pattern (Sprint 3b.19B established): N+M+2 ops em single
    MutateGoogleAdsRequest. Google replaces temp resource names with real IDs
    post-create. F13 (Sprint 3b.15) auto-returns resource_names array.

    V4 invariants hardcoded:
    - status PAUSED on create
    - advertising_channel_type SEARCH (v0)
    - network: target_google_search=True, target_search_network=False,
      target_content_network=False (V4 defaults)
    - language: languageConstants/1014 (Portuguese)
    - budget delivery_method STANDARD

    Bidding strategy → oneof field mapping (proto-plus):
    - MAXIMIZE_CONVERSIONS → campaign.maximize_conversions (optional target_cpa_micros)
    - MAXIMIZE_CONVERSION_VALUE → campaign.maximize_conversion_value (optional target_roas)
    - TARGET_CPA → campaign.target_cpa (required target_cpa_micros)
    - TARGET_ROAS → campaign.target_roas (required target_roas, decimal e.g. 4.0 = 400%)
    - MANUAL_CPC → campaign.manual_cpc (empty instance; enhanced_cpc_enabled REMOVED F35)
    - MAXIMIZE_CLICKS → campaign.target_spend (optional cpc_bid_ceiling_micros)

    Sprint 3b.24.4 F33 reversal: ``client.get_type("X")`` returns an INSTANCE directly
    (not a class). Sprint 3b.24.3 added ``()`` to 3 branches, causing TypeError in
    production. Correct pattern for no-scalar branches: assign the instance directly
    without calling it. For scalar-bearing branches: bare sub-field access
    (``campaign.target_cpa.target_cpa_micros = X``) initialises the oneof in one step.

    Sprint 3b.24.4 F34: Google now REQUIRES ``contains_eu_political_advertising`` on
    Campaign create. V4 is Brazilian — hardcoded DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING.

    Sprint 3b.24.4 F35: ``manual_cpc.enhanced_cpc_enabled`` is deprecated by Google and
    is rejected on Campaign create (OPERATION_NOT_PERMITTED_FOR_CONTEXT). Removed from
    schema + builder. MANUAL_CPC branch now assigns an empty ManualCpc instance.
    """
    operations: list[Any] = []

    # Enums needed
    budget_delivery_enum = client.enums.BudgetDeliveryMethodEnum
    channel_enum = client.enums.AdvertisingChannelTypeEnum
    status_enum = client.enums.CampaignStatusEnum

    # Temp resource paths
    budget_temp_path = f"customers/{customer_id}/campaignBudgets/-1"
    campaign_temp_path = f"customers/{customer_id}/campaigns/-2"

    # ----- Op 0: Campaign Budget -----
    budget_op_wrap = client.get_type("MutateOperation")
    budget_op = budget_op_wrap.campaign_budget_operation
    budget = budget_op.create
    budget.resource_name = budget_temp_path
    budget.name = f"{payload['name']} - budget"
    budget.amount_micros = _brl_to_micros(payload["daily_budget_brl"])
    budget.delivery_method = budget_delivery_enum.STANDARD
    budget.explicitly_shared = False  # V4 invariant — standalone budget; shared=True is only
    # for portfolio bidding strategies. Standalone strategies (MAX_CONVERSIONS, TARGET_CPA, etc)
    # require explicitly_shared=False. Sprint 3b.24.2 F32 fix.
    operations.append(budget_op_wrap)

    # ----- Op 1: Campaign -----
    campaign_op_wrap = client.get_type("MutateOperation")
    campaign_op = campaign_op_wrap.campaign_operation
    campaign = campaign_op.create
    campaign.resource_name = campaign_temp_path
    campaign.name = payload["name"]
    campaign.status = status_enum.PAUSED  # V4 invariant
    campaign.advertising_channel_type = channel_enum.SEARCH  # v0
    campaign.campaign_budget = budget_temp_path  # temp ref

    # F34 (Sprint 3b.24.4): Google added contains_eu_political_advertising as
    # REQUIRED on Campaign create. V4 is Brazilian — no EU political ads (hardcoded).
    campaign.contains_eu_political_advertising = (
        client.enums.EuPoliticalAdvertisingStatusEnum.DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING
    )

    # Network settings V4 invariants
    campaign.network_settings.target_google_search = True
    campaign.network_settings.target_search_network = False  # No Search Partners
    campaign.network_settings.target_content_network = False  # No Display

    # Bidding strategy oneof — Sprint 3b.24.3 F33 fix.
    #
    # CANONICAL PATTERN (verified via context7 / google-ads-python official examples):
    # Use bare attribute access to set sub-message fields. Accessing
    # `campaign.maximize_conversions.field = value` IS the correct way to mark
    # the oneof in proto-plus — it initialises the sub-message and marks it as
    # the active oneof member in a single step.
    #
    # Sprint 3b.24.1 F30 "fix" was WRONG: it used `client.get_type("X")` without
    # parens, which returns a CLASS (not an instance). Assigning a class to a
    # proto-plus field is silently accepted but does NOT initialize the oneof.
    # The bare attribute access pattern (e.g. `campaign.target_cpa.target_cpa_micros`)
    # is what the official Google Ads Python SDK examples use:
    #   campaign.maximize_conversion_value.target_roas = 3.5  (PMax example)
    #   campaign.target_cpa.target_cpa_micros = 1_000_000     (Demand Gen example)
    #
    # For strategies with no configurable sub-fields (MANUAL_CPC, MAXIMIZE_CLICKS),
    # use client.get_type("X")() WITH parens to create an instance, then assign —
    # this matches the simple create_campaign SDK example pattern.
    bs = payload["bidding_strategy"]
    bs_type = bs["type"]
    if bs_type == "MAXIMIZE_CONVERSIONS":
        if "target_cpa_brl" in bs:
            campaign.maximize_conversions.target_cpa_micros = _brl_to_micros(bs["target_cpa_brl"])
        else:
            # No optional fields — assign instance to mark the oneof.
            # F33 reversal (Sprint 3b.24.4): get_type returns INSTANCE directly; no parens.
            campaign.maximize_conversions = client.get_type("MaximizeConversions")
    elif bs_type == "MAXIMIZE_CONVERSION_VALUE":
        if "target_roas" in bs:
            campaign.maximize_conversion_value.target_roas = bs["target_roas"]
        else:
            # No optional fields — assign instance to mark the oneof.
            # F33 reversal (Sprint 3b.24.4): get_type returns INSTANCE directly; no parens.
            campaign.maximize_conversion_value = client.get_type("MaximizeConversionValue")
    elif bs_type == "TARGET_CPA":
        campaign.target_cpa.target_cpa_micros = _brl_to_micros(bs["target_cpa_brl"])
    elif bs_type == "TARGET_ROAS":
        campaign.target_roas.target_roas = bs["target_roas"]
    elif bs_type == "MANUAL_CPC":
        # F35 (Sprint 3b.24.4): enhanced_cpc_enabled is deprecated; rejected by Google
        # on Campaign create (OPERATION_NOT_PERMITTED_FOR_CONTEXT). Use canonical
        # empty-instance assignment to mark the oneof without setting any sub-fields.
        campaign.manual_cpc = client.get_type("ManualCpc")
    elif bs_type == "MAXIMIZE_CLICKS":
        # MAXIMIZE_CLICKS maps to TargetSpend proto message (Google's naming).
        if "cpc_bid_ceiling_brl" in bs:
            campaign.target_spend.cpc_bid_ceiling_micros = _brl_to_micros(bs["cpc_bid_ceiling_brl"])
        else:
            # No optional fields — assign instance to mark the oneof.
            # F33 reversal (Sprint 3b.24.4): get_type returns INSTANCE directly; no parens.
            campaign.target_spend = client.get_type("TargetSpend")

    # Schedule (optional)
    if "start_date" in payload:
        campaign.start_date = payload["start_date"]
    if "end_date" in payload:
        campaign.end_date = payload["end_date"]

    operations.append(campaign_op_wrap)

    # ----- Ops 2..N+1: Geo Criterion ops -----
    for geo_path in payload["geo_targets"]:
        geo_op_wrap = client.get_type("MutateOperation")
        geo_op = geo_op_wrap.campaign_criterion_operation
        geo_crit = geo_op.create
        geo_crit.campaign = campaign_temp_path  # temp ref
        geo_crit.location.geo_target_constant = geo_path
        operations.append(geo_op_wrap)

    # ----- Op N+2: PT Language Criterion -----
    lang_op_wrap = client.get_type("MutateOperation")
    lang_op = lang_op_wrap.campaign_criterion_operation
    lang_crit = lang_op.create
    lang_crit.campaign = campaign_temp_path  # temp ref
    lang_crit.language.language_constant = "languageConstants/1014"  # PT (V4)
    operations.append(lang_op_wrap)

    return operations
