"""Mutate builders for conversion_action operations.

Sprint 3b.19A — primeiro arquivo dessa categoria. ConversionAction é
customer-level (sem parent campaign/ad_group). V4 invariants:
- status: sempre ENABLED on create (diferente de create_ad_group/create_rsa
  que defaultam PAUSED — gestor quer ativacao imediata)
- currency_code: hardcoded "BRL" (V4 = Brazil only)
- counting_type: defaults to ONE_PER_CLICK when omitted

Proto attribute notes (validated via context7 google-ads-python pre-Task 2):
- ca.type_ (underscore suffix) because `type` is Python reserved word.
  Confirmed: context7 example shows `conversion_action.type_ = client.enums
  .ConversionActionTypeEnum.WEBPAGE` explicitly.
- ca.value_settings.default_value accepts float directly (no micros
  conversion) — different from CPC bids which use micros. Confirmed:
  context7 example shows `value_settings.default_value = 50.0`.
- ConversionActionService is used via client.get_service("ConversionActionService")
  and has conversion_action_path(cid, action_id) for resource paths.

Builder uses MutateOperation.conversion_action_operation (GoogleAdsService
batch pattern) — consistent with all other builders in this codebase (Sprint
3b.16/3b.18 ads.py pattern).
"""

from typing import Any

from src.google_ads.mutates._common import register_builder


@register_builder("create_conversion_action")
def build_create_conversion_action(
    client: Any, customer_id: str, payload: dict[str, Any]
) -> list[Any]:
    """payload: {conversion_actions: [{name, category, type, counting_type?, value_settings?}]}

    Returns list of MutateOperation messages ready for GoogleAdsService.mutate.

    value_settings (optional dict):
        default_value_brl: float  — default conversion value in BRL
        always_use_default_value: bool — whether to always use the default value
    """
    operations: list[Any] = []
    cat_enum = client.enums.ConversionActionCategoryEnum
    type_enum = client.enums.ConversionActionTypeEnum
    status_enum = client.enums.ConversionActionStatusEnum
    counting_enum = client.enums.ConversionActionCountingTypeEnum

    for spec in payload["conversion_actions"]:
        op = client.get_type("MutateOperation")
        ca_op = op.conversion_action_operation
        ca = ca_op.create
        ca.name = spec["name"]
        ca.category = cat_enum[spec["category"]]
        ca.type_ = type_enum[spec["type"]]
        ca.status = status_enum.ENABLED  # V4 invariant: always ENABLED on create
        ca.counting_type = counting_enum[
            spec.get("counting_type", "ONE_PER_CLICK")  # V4 invariant default
        ]

        if "value_settings" in spec:
            vs = spec["value_settings"]
            ca.value_settings.default_currency_code = "BRL"  # V4 invariant
            if "default_value_brl" in vs:
                ca.value_settings.default_value = vs["default_value_brl"]
            if "always_use_default_value" in vs:
                ca.value_settings.always_use_default_value = vs["always_use_default_value"]

        operations.append(op)
    return operations
