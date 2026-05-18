# Phase 3b.25 — manual smoke runbook (`create_and_link_assets`)

**Purpose:** Validar Sprint 3b.25 — sexto create-pattern do MCP, foundation pra onboarding completo V4 via Claude/Codex (text-extensions).

**Operator:** wellinton.ribeiro@v4company.com
**Account:** `1163862076` Nutry (sandbox — campaigns PAUSED do Sprint 3b.24 anexamos assets sem serving impact)

**Spec:** `docs/superpowers/specs/2026-05-18-sprint-3b-25-create-and-link-assets-design.md`
**Plan:** `docs/superpowers/plans/2026-05-18-sprint-3b-25-create-and-link-assets.md`

**Sprint 3b.19A.1 lesson aplicado:** T3, T6, T7 explicit per-value/per-level empirical probe.

## Pre-flight

- [x] Deploy lands successfully (CI green em 26048190492, Deploy success em 26048190375)
- [x] Service `/health` returns 200
- [ ] Tool `create_and_link_assets` visível em MCP tool list (count 47 → 48) — Wellington verifica em sessão Claude pós-restart
- [ ] F28 reproducer: gestor pode precisar restart Claude Code session pro schema cache propagar

Production revision: `v4-ads-mcp-00188-cwv` (Deploy verde, /health 200, CI green pós-fix CI red Sprint 3b.24 + Sprint 3b.25 typo).

## Reference: Nutry sandbox campaigns (from Sprint 3b.24)

Use the 5 PAUSED campaigns criadas no Sprint 3b.24 smoke:
- T1: `customers/1163862076/campaigns/<id_t1>`
- T2: `customers/1163862076/campaigns/<id_t2>`
- T4: `customers/1163862076/campaigns/<id_t4>`
- T5: `customers/1163862076/campaigns/<id_t5>`
- T6: `customers/1163862076/campaigns/<id_t6>`

Confirm via GAQL pré-smoke:

```
SELECT campaign.id, campaign.name, campaign.status FROM campaign
WHERE campaign.name LIKE '[3b.24 smoke]%'
```

Selecionar 1 campaign + 1 ad_group pra T2/T3/T9 (CAMPAIGN/AD_GROUP probes).

## Test T1 — SITELINK CUSTOMER (account-wide)

```
create_and_link_assets(
  customer_id="1163862076",
  assets=[{
    "type": "SITELINK",
    "attachment_level": "CUSTOMER",
    "attachment_id": "1163862076",
    "link_text": "Sobre nós",
    "final_urls": ["https://nutry.com.br/sobre"]
  }]
)
```

Expected:
- [ ] dry_run com confirmation_token + summary.asset_count=1, by_type={SITELINK:1}, by_level={CUSTOMER:1}
- [ ] apply → applied_count=2, resource_names array com 2 paths (1 asset + 1 customer_asset)
- [ ] GAQL verify: `SELECT asset.id, asset.sitelink_asset.link_text, customer_asset.field_type FROM customer_asset WHERE asset.id = <id from resource_names[0]>`

**Result:** ⬜ pending

## Test T2 — SITELINK CAMPAIGN (most common V4 workflow)

```
create_and_link_assets(
  customer_id="1163862076",
  assets=[
    {"type": "SITELINK", "attachment_level": "CAMPAIGN", "attachment_id": "<campaign T2>",
     "link_text": "Serviços", "final_urls": ["https://nutry.com.br/servicos"]},
    {"type": "SITELINK", "attachment_level": "CAMPAIGN", "attachment_id": "<campaign T2>",
     "link_text": "Contato", "final_urls": ["https://nutry.com.br/contato"]},
    {"type": "SITELINK", "attachment_level": "CAMPAIGN", "attachment_id": "<campaign T2>",
     "link_text": "Blog", "final_urls": ["https://nutry.com.br/blog"]},
    {"type": "SITELINK", "attachment_level": "CAMPAIGN", "attachment_id": "<campaign T2>",
     "link_text": "FAQ", "final_urls": ["https://nutry.com.br/faq"]}
  ]
)
```

Expected:
- [ ] dry_run summary.asset_count=4, by_type={SITELINK:4}, by_level={CAMPAIGN:4}
- [ ] apply → applied_count=8, resource_names array com 8 paths

**Result:** ⬜ pending

## Test T3 — SITELINK AD_GROUP (rare granular probe)

```
create_and_link_assets(
  customer_id="1163862076",
  assets=[{
    "type": "SITELINK",
    "attachment_level": "AD_GROUP",
    "attachment_id": "<ad_group T2>",
    "link_text": "Promoção",
    "final_urls": ["https://nutry.com.br/promo"]
  }]
)
```

Expected:
- [ ] Either: apply → applied_count=2 (Google supports AD_GROUP for SITELINK)
- [ ] OR: Google rejects with INVALID_ASSET_LEVEL or similar — **document as F-class finding** if rejected

**Result:** ⬜ pending

## Test T4 — CALLOUT CUSTOMER (brand callouts)

```
create_and_link_assets(
  customer_id="1163862076",
  assets=[
    {"type": "CALLOUT", "attachment_level": "CUSTOMER", "attachment_id": "1163862076",
     "callout_text": "Atendimento 24h"},
    {"type": "CALLOUT", "attachment_level": "CUSTOMER", "attachment_id": "1163862076",
     "callout_text": "Frete grátis"},
    {"type": "CALLOUT", "attachment_level": "CUSTOMER", "attachment_id": "1163862076",
     "callout_text": "Entrega 7 dias"}
  ]
)
```

Expected:
- [ ] dry_run summary.by_type={CALLOUT:3}, by_level={CUSTOMER:3}
- [ ] apply → applied_count=6

**Result:** ⬜ pending

## Test T5 — CALLOUT CAMPAIGN

Similar a T4 mas attachment_level=CAMPAIGN. 2 assets.

**Result:** ⬜ pending

## Test T6 — STRUCTURED_SNIPPET CUSTOMER (header=SERVICE_CATALOG)

```
create_and_link_assets(
  customer_id="1163862076",
  assets=[{
    "type": "STRUCTURED_SNIPPET",
    "attachment_level": "CUSTOMER",
    "attachment_id": "1163862076",
    "header": "SERVICE_CATALOG",
    "values": ["Vitaminas", "Suplementos", "Probióticos"]
  }]
)
```

Expected:
- [ ] apply → applied_count=2
- [ ] GAQL verify: `SELECT asset.structured_snippet_asset.header, asset.structured_snippet_asset.values FROM customer_asset WHERE asset.id = <id>`

**Result:** ⬜ pending

## Test T7 — STRUCTURED_SNIPPET CAMPAIGN (header=BRANDS)

Similar a T6 mas header=BRANDS, attachment_level=CAMPAIGN.

**Result:** ⬜ pending

## Test T8 — CALL CAMPAIGN (V4 lead-gen phone)

```
create_and_link_assets(
  customer_id="1163862076",
  assets=[{
    "type": "CALL",
    "attachment_level": "CAMPAIGN",
    "attachment_id": "<campaign T4>",
    "phone_number": "(11) 98765-4321"
  }]
)
```

Expected:
- [ ] apply → applied_count=2
- [ ] GAQL verify country_code=BR enforced (V4 invariant):
  `SELECT asset.call_asset.country_code, asset.call_asset.phone_number FROM campaign_asset WHERE asset.id = <id>`

**Result:** ⬜ pending

## Test T9 — CALL AD_GROUP (granular probe)

Similar a T8 mas attachment_level=AD_GROUP. Same as T3 — may reject.

**Result:** ⬜ pending

## Test T10 — PROMOTION percent_off=20.0 (critical: micros formula)

```
create_and_link_assets(
  customer_id="1163862076",
  assets=[{
    "type": "PROMOTION",
    "attachment_level": "CAMPAIGN",
    "attachment_id": "<campaign T5>",
    "promotion_target": "Verão 2026",
    "discount_modifier": "UP_TO",
    "percent_off": 20.0,
    "final_urls": ["https://nutry.com.br/promo"]
  }]
)
```

Expected:
- [ ] apply → applied_count=2
- [ ] **GAQL critical assertion:** `SELECT asset.promotion_asset.percent_off FROM campaign_asset WHERE asset.id = <id>` → **200_000** (NOT 20_000_000 — R6 risk verified)

**Result:** ⬜ pending

## Test T11 — PROMOTION money_amount_off_brl=50.0

```
create_and_link_assets(
  customer_id="1163862076",
  assets=[{
    "type": "PROMOTION",
    "attachment_level": "CAMPAIGN",
    "attachment_id": "<campaign T5>",
    "promotion_target": "Verão 2026",
    "discount_modifier": "NONE",
    "money_amount_off_brl": 50.0,
    "final_urls": ["https://nutry.com.br/promo"]
  }]
)
```

Expected:
- [ ] apply → applied_count=2
- [ ] GAQL: `SELECT asset.promotion_asset.money_amount_off.amount_micros, asset.promotion_asset.money_amount_off.currency_code` → 50_000_000 + BRL

**Result:** ⬜ pending

## Test T12 — Mixed batch (V4 onboarding workflow)

```
create_and_link_assets(
  customer_id="1163862076",
  assets=[
    # 4 sitelinks CAMPAIGN
    {"type": "SITELINK", "attachment_level": "CAMPAIGN", "attachment_id": "<campaign T6>",
     "link_text": "L1", "final_urls": ["https://nutry.com.br/l1"]},
    {"type": "SITELINK", "attachment_level": "CAMPAIGN", "attachment_id": "<campaign T6>",
     "link_text": "L2", "final_urls": ["https://nutry.com.br/l2"]},
    {"type": "SITELINK", "attachment_level": "CAMPAIGN", "attachment_id": "<campaign T6>",
     "link_text": "L3", "final_urls": ["https://nutry.com.br/l3"]},
    {"type": "SITELINK", "attachment_level": "CAMPAIGN", "attachment_id": "<campaign T6>",
     "link_text": "L4", "final_urls": ["https://nutry.com.br/l4"]},
    # 2 callouts CUSTOMER
    {"type": "CALLOUT", "attachment_level": "CUSTOMER", "attachment_id": "1163862076",
     "callout_text": "Atendimento PT-BR"},
    {"type": "CALLOUT", "attachment_level": "CUSTOMER", "attachment_id": "1163862076",
     "callout_text": "Frete BR"},
    # 1 call CAMPAIGN
    {"type": "CALL", "attachment_level": "CAMPAIGN", "attachment_id": "<campaign T6>",
     "phone_number": "(11) 98765-4321"}
  ]
)
```

Expected:
- [ ] dry_run summary.asset_count=7, by_type={SITELINK:4, CALLOUT:2, CALL:1}, by_level={CAMPAIGN:5, CUSTOMER:2}
- [ ] apply → applied_count=14, resource_names array com 14 paths
- [ ] Response size < MCP cap (~36k chars projetado, bem abaixo de 100k cap)

**Result:** ⬜ pending

## Test T13 — Schema regression: SITELINK + callout_text rejected

```
create_and_link_assets(
  customer_id="1163862076",
  assets=[{
    "type": "SITELINK",
    "attachment_level": "CAMPAIGN",
    "attachment_id": "<campaign T1>",
    "link_text": "Test",
    "final_urls": ["https://example.com"],
    "callout_text": "BAD — should reject"
  }]
)
```

Expected:
- [ ] Tool returns status=error pre-Google call: "campo 'callout_text' não aplicável a type=SITELINK"

**Result:** ⬜ pending

## Test T14 — Schema regression: PROMOTION sem desconto rejected

```
create_and_link_assets(
  customer_id="1163862076",
  assets=[{
    "type": "PROMOTION",
    "attachment_level": "CAMPAIGN",
    "attachment_id": "<campaign T5>",
    "promotion_target": "Verão",
    "discount_modifier": "NONE",
    "final_urls": ["https://example.com"]
    # Missing percent_off AND money_amount_off_brl
  }]
)
```

Expected:
- [ ] Tool returns status=error: "PROMOTION requer exatamente um de 'percent_off' OU 'money_amount_off_brl'"

**Result:** ⬜ pending

## Test T15 — F22-equivalent: 20 assets em single batch (response cap test)

20 SITELINKs CAMPAIGN attached a 1 campaign. Verify response < MCP cap.

```
create_and_link_assets(
  customer_id="1163862076",
  assets=[
    {"type": "SITELINK", "attachment_level": "CAMPAIGN", "attachment_id": "<campaign T6>",
     "link_text": f"Link {i}", "final_urls": [f"https://nutry.com.br/l{i}"]}
    for i in range(1, 21)
  ]
)
```

Expected:
- [ ] dry_run summary.asset_count=20, by_type={SITELINK:20}
- [ ] apply → applied_count=40, resource_names array com 40 paths
- [ ] Response chars total < 100k (projetado ~36k)

**Result:** ⬜ pending

## Cleanup post-smoke

Assets ficam paused (campaigns Sprint 3b.24 já PAUSED, zero serving impact). Spawn-task pra Sprint 3b.28 (`remove_*` bundle) cleanup.

## Findings discovered

(Preencher pós-smoke se findings reais surgirem — F38+ candidates documented em findings-catalog.md)

| # | Finding | Severity | Documented | Fix |
|---|---|---|---|---|
| F38 | (pending) | — | — | — |

## Sign-off

- [ ] Pre-push gate 5/5 PASS
- [ ] Production /health 200
- [ ] 12+/15 tests PASS (T3/T9 podem ser documentados findings sem blocker)
- [ ] CLAUDE.md sprint row added
- [ ] findings-catalog.md updated se F38+ surgir
- [ ] Tool count 47 → 48 confirmed in production tool list

Signed-off: ⬜ pending
