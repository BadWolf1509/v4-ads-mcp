"""Mutate builders for conversion_value_rule + conversion_value_rule_set operations.

Sprint 3b.19B — primeiro arquivo desta categoria. ConversionValueRuleSet
attaches a CUSTOMER ou CAMPAIGN. Rules vivem INSIDE the RuleSet via
resource_name references (Sprint 3b.22 removeu `conversion_action_categories`
filter — Google API só aceita [] OU STORE_VISIT OU STORE_SALE para esse
campo, STORE out of scope v0).

Chained mutation pattern (validated via context7 + Google Ads API docs):
- N rule operations com temp resource_names (negative IDs)
- 1 RuleSet operation referencing temp paths via rs.conversion_value_rules
  (repeated STRING field — resource paths)
- Google Ads server executes em ordem; replaces temp paths com real IDs
- F13 retorna real resource_names no apply response

V4 invariants:
- status: sempre ENABLED on create (consistent com 3b.19A ConversionAction)
- geo targets validated as BR-only via pre-flight helper (Task 1)

Proto attribute notes (validated via context7 google-ads API docs pre-Task 2):
- rs.conversion_value_rules is repeated string (resource paths, NOT
  inline messages) — confirmed: "The conversion_value_rules field lists
  the resource names of the rules included in the set"
- rs.dimensions must be set explicitly to match the condition types used
  in the rules (Google requires consistency between rules and declared
  dimensions). Inferred from unique rule condition_types in this builder.
- rule.action.value accepts float directly (no micros) — consistent with
  all conversion value APIs (not bid/budget which use micros)
- rule.geo_location_condition.geo_target_constants is repeated string
  (resource paths like geoTargetConstants/2076)
- Chained mutation with temp negative IDs confirmed as standard best
  practice: "customers/<CID>/conversionValueRules/-1" etc.
"""

from typing import Any

from src.google_ads.mutates._common import register_builder


@register_builder("create_conversion_value_rule_set")
def build_create_conversion_value_rule_set(
    client: Any, customer_id: str, payload: dict[str, Any]
) -> list[Any]:
    """Chained mutation: N rules with temp resource_names + 1 RuleSet referencing them.

    payload schema (post-Sprint 3b.22 cleanup):
      attachment_type: CUSTOMER | CAMPAIGN
      campaign_id?: str  (required when attachment_type == CAMPAIGN)
      rules: list of rule specs, each:
        action: {operation: ADD|MULTIPLY|SET, value: float}
        condition_type: DEVICE | GEO_LOCATION
        device_condition?: {device_types: list[str]}
        geo_condition?: {
          geo_target_constants: list[str],
          geo_match_type?: ANY|LOCATION_OF_PRESENCE
        }

    Sprint 3b.22 removed (per smoke 3b.19B findings F25 + F27):
    - condition_type=NO_CONDITION (Google API restricts to Store Visits/Sales)
    - conversion_action_categories field (Google API restricts to [] OR
      [STORE_VISIT] OR [STORE_SALE]; STORE out of scope v0)

    Returns a list of MutateOperation instances: N rule ops followed by
    1 RuleSet op. The server resolves temp paths to real IDs on execution.
    F13 (Sprint 3b.15) auto-returns resource_names from apply response.
    """
    operations: list[Any] = []

    op_enum = client.enums.ValueRuleOperationEnum
    device_enum = client.enums.ValueRuleDeviceTypeEnum
    match_enum = client.enums.ValueRuleGeoLocationMatchTypeEnum
    attach_enum = client.enums.ValueRuleSetAttachmentTypeEnum
    dim_enum = client.enums.ValueRuleSetDimensionEnum
    rule_status_enum = client.enums.ConversionValueRuleStatusEnum
    set_status_enum = client.enums.ConversionValueRuleSetStatusEnum

    rule_temp_paths: list[str] = []

    # Build rule ops with temp resource names (negative IDs, unique within request)
    for i, rule_spec in enumerate(payload["rules"]):
        op = client.get_type("MutateOperation")
        rule_op = op.conversion_value_rule_operation
        rule = rule_op.create

        # Temp resource name: negative ID — Google replaces with real ID post-create
        temp_path = f"customers/{customer_id}/conversionValueRules/-{i + 1}"
        rule.resource_name = temp_path
        rule_temp_paths.append(temp_path)

        # action
        rule.action.operation = op_enum[rule_spec["action"]["operation"]]
        rule.action.value = rule_spec["action"]["value"]

        # condition
        condition_type = rule_spec["condition_type"]
        if condition_type == "DEVICE":
            for device_type in rule_spec["device_condition"]["device_types"]:
                rule.device_condition.device_types.append(device_enum[device_type])
        elif condition_type == "GEO_LOCATION":
            geo_cond = rule_spec["geo_condition"]
            for gtc in geo_cond["geo_target_constants"]:
                rule.geo_location_condition.geo_target_constants.append(gtc)
            rule.geo_location_condition.geo_match_type = match_enum[
                geo_cond.get("geo_match_type", "ANY")
            ]

        rule.status = rule_status_enum.ENABLED  # V4 invariant: always ENABLED on create
        operations.append(op)

    # Build RuleSet op referencing temp paths
    set_op = client.get_type("MutateOperation")
    rs_op = set_op.conversion_value_rule_set_operation
    rs = rs_op.create

    rs.attachment_type = attach_enum[payload["attachment_type"]]

    if payload["attachment_type"] == "CAMPAIGN":
        camp_svc = client.get_service("CampaignService")
        rs.campaign = camp_svc.campaign_path(customer_id, payload["campaign_id"])

    # Dimensions inferred from unique rule condition_types.
    # Google requires dimensions to match condition types used in the rules.
    # Sorted for deterministic ordering.
    unique_condition_types = {r["condition_type"] for r in payload["rules"]}
    for dim in sorted(unique_condition_types):
        rs.dimensions.append(dim_enum[dim])

    # Sprint 3b.22 (F27 cleanup): removed conversion_action_categories filter.
    # Google API only accepts empty / [STORE_VISIT] / [STORE_SALE] for this
    # field; the 13-cat whitelist herdada de 3b.19A was invalid here.

    rs.status = set_status_enum.ENABLED  # V4 invariant: always ENABLED on create

    # Reference temp paths via rs.conversion_value_rules (repeated STRING field)
    # "The conversion_value_rules field lists the resource names of the rules
    # included in the set." — Google Ads API docs
    for tp in rule_temp_paths:
        rs.conversion_value_rules.append(tp)

    operations.append(set_op)
    return operations
