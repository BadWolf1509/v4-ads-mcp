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

## Smoke results (executed 2026-05-18 em Nutry sandbox 1163862076)

| # | Test | Result | Resource_names | Findings |
|---|---|---|---|---|
| T1 | SITELINK CUSTOMER | ✅ PASS | asset `362248502689` + customerAsset link | — |
| T2 | SITELINK CAMPAIGN (4) | ✅ PASS | 8 (4 assets + 4 campaignAssets) | — |
| T3 | SITELINK AD_GROUP | ✅ PASS | asset `362331550494` + adGroupAsset | **No F-finding** (Google ACCEPTS — predicted F-finding was wrong) |
| T4 | CALLOUT CUSTOMER (3) | ✅ PASS | 6 (3 assets + 3 customerAssets) | — |
| T5 | CALLOUT CAMPAIGN (2) | ✅ PASS | 4 | — |
| T6 | STRUCTURED_SNIPPET CUSTOMER (header=SERVICE_CATALOG) | ❌ FAIL | — | **F38: STRUCTURED_SNIPPET header format mismatch** |
| T7 | STRUCTURED_SNIPPET CAMPAIGN (header=BRANDS) | ❌ FAIL | — | **F38 confirmed not per-value** (both headers reject) |
| T8 | CALL CAMPAIGN | ✅ PASS | asset `362249151148` + campaignAsset; GAQL confirmou `country_code=BR` enforced (V4 invariant ✓) | — |
| T9 | CALL AD_GROUP | ✅ PASS | asset `362331764796` + adGroupAsset | **No F-finding** (Google ACCEPTS) |
| T10 | PROMOTION percent_off=20.0 | ❌ FAIL | — | **F39: language_code='pt' rejected pelo Google** |
| T11 | PROMOTION money_amount_off_brl=50.0 | ❌ FAIL | — | F39 confirmed (segundo path), tambem KeyError em `_classify_partial` (mapping gap) |
| T12 | Mixed batch (4 SITELINK CAMP + 2 CALLOUT CUST + 1 CALL CAMP) | ✅ PASS | 14 resource_names, interleave bit-a-bit corretto | — |
| T13 | Schema regression SITELINK+callout_text | ✅ PASS | — | PT-BR error retornado pre-Google: `"campo 'callout_text' não aplicável a type=SITELINK"` |
| T14 | Schema regression PROMOTION sem desconto | ✅ PASS | — | PT-BR error: `"PROMOTION requer exatamente um de 'percent_off' OU 'money_amount_off_brl'"` |
| T15 | 20 sitelinks batch | ✅ PASS | 40 resource_names (após retry com fresh campaign — campaign inicial já tinha 8 sitelinks de T2+T12 = Google cap 20/campaign atingido. Não é Sprint 3b.25 bug, é smoke setup) | — |

**Effective result: 11/15 PASS** + 2 F-findings (F38, F39).

### F38: STRUCTURED_SNIPPET header schema enum format mismatch

**Severity:** HIGH (STRUCTURED_SNIPPET asset type completely unusable)

**Symptom:** Google API rejects with `"The input string value is invalid for the associated field."` quando passa header=`SERVICE_CATALOG` ou `BRANDS` (any ALL_CAPS value from current schema enum).

**Root cause:** `StructuredSnippetAsset.header` é STRING field (não proto enum). Google espera valores localizados predefinidos por https://developers.google.com/google-ads/api/reference/data/structured-snippet-headers — display strings tipo `"Service catalog"` (en) ou `"Catálogo de serviços"` (pt-BR), NÃO o nome do enum em UPPER_SNAKE_CASE.

**Bug class family:** Mesmo padrão de F17/F25/F27 — schema accepts what Google API runtime rejects (Sprint 3b.19A.1 "schema whitelist empirical validation" convention should have caught it; my schema enum was derived from assumed proto enum names, not empirically validated).

**Fix (Sprint 3b.25.1):** Change schema `_STRUCTURED_SNIPPET_HEADERS` enum para Portuguese display strings (V4 BR-invariant):
```python
_STRUCTURED_SNIPPET_HEADERS = [
    "Bairros", "Catálogo de serviços", "Comodidades", "Cursos",
    "Cursos de graduação", "Destinos", "Estilos", "Hotéis em destaque",
    "Marcas", "Modelos", "Programas", "Tipos", "Tipos de cobertura do seguro",
]
```
Builder doesn't need changes (just passes the string through to proto).

### F39: PromotionAsset.language_code='pt' invalid (BCP 47 requires region-qualified pt-BR)

**Severity:** HIGH (PROMOTION asset type completely unusable)

**Symptom:** Google API rejects with `"The language code is not supported."` quando builder passa `promo.language_code = "pt"` (V4 invariant hardcoded).

**Root cause:** BCP 47 spec says `"pt"` is valid (less specific) but Google Ads PROMOTION asset apparently expects region-qualified (`"pt-BR"`). Same pattern as `languageConstants/1014` which represents "Portuguese (Brazil)" não generic Portuguese.

**Bug class family:** Mesmo padrão de F25/F27/F34 — V4 invariant inferred from spec wasn't validated empirically against Google runtime. Sprint 3b.19A.1 convention applies.

**Fix (Sprint 3b.25.1):** Change builder line in `src/google_ads/mutates/assets.py`:
```python
promo.language_code = "pt-BR"  # was "pt" — F39: BCP 47 requires region qualifier
```
Builder unit test updates the V4 invariant assertion accordingly.

**Bonus:** Sprint 3b.25.1 should also add `language_code` mapping em `_classify_partial` (em `src/google_ads/errors.py`) pra evitar KeyError no T11 (PROMOTION money_amount_off path). Não é regression do Sprint 3b.25 mas surface gap descoberto durante smoke.

### Cleanup post-smoke

Assets ficam paused (campaigns Sprint 3b.24 já PAUSED, zero serving impact). Total criados: ~50 assets em Nutry sandbox + 50 links. Spawn-task pra Sprint 3b.28 (`remove_*` bundle) cleanup futuro.

## Sign-off

- [x] Pre-push gate 5/5 PASS (no Task 5)
- [x] Production /health 200 (revision `v4-ads-mcp-00188-cwv`)
- [x] **11/15 tests PASS** (T3+T9 predicted F-findings NÃO surgiram → bonus; T6+T7 + T10+T11 surfaced F38+F39 que precisam fix iteration Sprint 3b.25.1)
- [x] CLAUDE.md sprint row added (commit 2c0fab0)
- [ ] findings-catalog.md updated com F38 + F39 — **PENDING (signoff commit)**
- [x] Tool count 47 → 48 confirmed in production
- [ ] Sprint 3b.25.1 fix iteration (F38 schema + F39 builder language_code) — **PENDING (next commit)**

**Streak status:** Sprint 3b.25 break F-finding streak iniciada em 3b.22 + 3b.23 (2 sprints clean smoke). F38 + F39 são 12ª variante da família design-gap-via-SDK-ambiguity (F17/F18/F19/F25/F27/F31/F32/F34/F36 + new F38/F39).

Signed-off: 🟡 partial — 3 critical paths (SITELINK, CALLOUT, CALL all levels + mixed batch) work end-to-end. STRUCTURED_SNIPPET + PROMOTION blocked pending Sprint 3b.25.1 fix.
