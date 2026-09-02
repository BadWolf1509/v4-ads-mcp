"""Mutate builder for create_and_link_assets (Sprint 3b.25).

Chained mutation pattern (Sprint 3b.19B established + Sprint 3b.24 expanded):
emits 2N ops in single MutateGoogleAdsRequest:
- N asset_operation.create (temp resource names: customers/{cid}/assets/-{i})
- N {customer|campaign|ad_group}_asset_operation.create (refs temp asset paths)

Atomic: all 2N ops succeed or all fail. Google substitutes real IDs at apply
time. F13 (Sprint 3b.15) auto-extracts 2N resource_names from response.

V4 invariants hardcoded (no schema fields):
- CallAsset.country_code = "BR"
- PromotionAsset.language_code = "pt-BR" (F39 Sprint 3b.25.1: BCP 47 region-qualified;
  Google rejects bare "pt" with "The language code is not supported.")
- PromotionAsset.money_amount_off.currency_code = "BRL"

Proto field names verified via context7 against /websites/developers_google_google-ads_api
on 2026-05-18:
- SitelinkAsset: link_text, description1, description2 (NOT description_line_1)
- CallAsset: phone_number (raw format), country_code (2-letter ISO)
- CalloutAsset: callout_text
- StructuredSnippetAsset: header (enum), values (3-10 strings)
- PromotionAsset: percent_off in micros (1_000_000 = 100%; multiply by 10_000),
  money_amount_off.{amount_micros, currency_code} (1 BRL = 1_000_000 micros)
- final_urls is Asset-level (parent), NOT inside sub-message
"""

from __future__ import annotations

from typing import Any

from src.google_ads.mutates._common import register_builder


@register_builder("create_and_link_assets")
def build_create_and_link_assets(
    client: Any, customer_id: str, payload: dict[str, Any]
) -> list[Any]:
    """Build 2N chained operations for create_and_link_assets (Sprint 3b.25).

    payload schema (post-_validate_payload_shape):
      assets: list of {type, attachment_level, attachment_id, ...per-type fields}

    Returns list[MutateOperation] in order:
      Op[0]   asset_operation.create     (Asset #1, temp customers/{cid}/assets/-1)
      Op[1]   {C|Camp|AG}_asset_operation.create (Link #1, refs Op[0])
      Op[2]   asset_operation.create     (Asset #2, temp .../assets/-2)
      Op[3]   ...
      ...

    Chained mutation guarantee: atomic. Temp negative IDs replaced by Google.
    """
    operations: list[Any] = []
    field_type_enum = client.enums.AssetFieldTypeEnum
    discount_mod_enum = client.enums.PromotionExtensionDiscountModifierEnum

    for i, a in enumerate(payload["assets"], start=1):
        temp_asset_path = f"customers/{customer_id}/assets/-{i}"

        # ----- Asset create op -----
        asset_op_wrap = client.get_type("MutateOperation")
        asset_op = asset_op_wrap.asset_operation
        asset = asset_op.create
        asset.resource_name = temp_asset_path

        atype = a["type"]
        if atype == "SITELINK":
            asset.sitelink_asset.link_text = a["link_text"]
            if "description1" in a:
                asset.sitelink_asset.description1 = a["description1"]
                asset.sitelink_asset.description2 = a["description2"]
            for url in a["final_urls"]:
                asset.final_urls.append(url)

        elif atype == "CALLOUT":
            asset.callout_asset.callout_text = a["callout_text"]

        elif atype == "STRUCTURED_SNIPPET":
            asset.structured_snippet_asset.header = a["header"]
            for v in a["values"]:
                asset.structured_snippet_asset.values.append(v)

        elif atype == "CALL":
            asset.call_asset.phone_number = a["phone_number"]
            asset.call_asset.country_code = "BR"  # V4 invariant

        elif atype == "PROMOTION":
            promo = asset.promotion_asset
            promo.promotion_target = a["promotion_target"]
            # F40 (Sprint 3b.25.2): discount_modifier now optional.
            # Omit field for exact discount; pass UP_TO for "até X% off" rendering.
            if "discount_modifier" in a:
                promo.discount_modifier = discount_mod_enum[a["discount_modifier"]]
            if "percent_off" in a:
                # 1_000_000 micros = 100% per Google spec; multiply by 10_000
                promo.percent_off = int(a["percent_off"] * 10_000)
            else:
                # 1 BRL = 1_000_000 micros
                promo.money_amount_off.amount_micros = int(a["money_amount_off_brl"] * 1_000_000)
                promo.money_amount_off.currency_code = "BRL"  # V4 invariant
            promo.language_code = (
                "pt-BR"  # V4 invariant (F39 Sprint 3b.25.1: BCP 47 region-qualified)
            )
            for url in a["final_urls"]:
                asset.final_urls.append(url)
            if "start_date" in a:
                promo.start_date = a["start_date"]
            if "end_date" in a:
                promo.end_date = a["end_date"]

        else:
            raise ValueError(f"unexpected asset type: {atype!r}")

        operations.append(asset_op_wrap)

        # ----- Link op (branches on attachment_level) -----
        link_op_wrap = client.get_type("MutateOperation")
        alevel = a["attachment_level"]
        ft = field_type_enum[atype]  # type-to-AssetFieldType is 1:1 v0

        if alevel == "CUSTOMER":
            ca = link_op_wrap.customer_asset_operation.create
            ca.asset = temp_asset_path
            ca.field_type = ft

        elif alevel == "CAMPAIGN":
            cm = link_op_wrap.campaign_asset_operation.create
            cm.asset = temp_asset_path
            cm.campaign = a["attachment_id"]
            cm.field_type = ft

        elif alevel == "AD_GROUP":
            ag = link_op_wrap.ad_group_asset_operation.create
            ag.asset = temp_asset_path
            ag.ad_group = a["attachment_id"]
            ag.field_type = ft

        else:
            raise ValueError(f"unexpected attachment_level: {alevel!r}")

        operations.append(link_op_wrap)

    return operations


@register_builder("remove_asset_link")
def build_remove_asset_link(client: Any, customer_id: str, payload: dict[str, Any]) -> list[Any]:
    """Uma MutateOperation de `remove` por vinculo, no operation do nivel certo.

    Remove o VINCULO (`*_asset`), nunca a entidade `Asset` — asset orfao e inerte,
    e remover a entidade e irreversivel numa coisa que pode estar linkada onde a
    varredura nao alcancou (spec secao 2). Por isso nao ha branch para
    `asset_operation` aqui, e ha teste exigindo a ausencia dele.
    """
    campo_por_nivel = {
        "CUSTOMER": "customer_asset_operation",
        "CAMPAIGN": "campaign_asset_operation",
        "AD_GROUP": "ad_group_asset_operation",
    }
    ops: list[Any] = []
    for link in payload["links"]:
        op = client.get_type("MutateOperation")
        alvo = getattr(op, campo_por_nivel[link["level"]])
        alvo.remove = link["resource_name"]
        ops.append(op)
    return ops
