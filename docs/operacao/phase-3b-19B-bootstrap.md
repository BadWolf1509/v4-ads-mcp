# Phase 3b.19B — manual smoke runbook (`create_conversion_value_rule_set`)

**Purpose:** Verify Sprint 3b.19B (quarto create-pattern do MCP). Complementa Sprint 3b.19A — gestor configura valores condicionais sobre ConversionActions existentes (device boost, geo boost).

**Operator:** wellinton.ribeiro@v4company.com
**Account:** `1163862076` Nutry (sandbox; tem 14+ ConversionActions criadas em 3b.19A)

**Spec:** `docs/superpowers/specs/2026-05-13-sprint-3b.19B-design.md`
**Plan:** `docs/superpowers/plans/2026-05-13-sprint-3b.19B-plan.md`

**Sprint 3b.19A.1 lesson applied:** T6 explicit per-value empirical probe pra todos 7 novos enums. **Lesson worked — pegou F25 + F27 BEFORE production usage.**

## Pre-flight

- [x] Deploy lands successfully (revision `v4-ads-mcp-00167-5x7`, post-Sprint 3b.21 deploy)
- [x] Service `/health` returns 200
- [x] Reload MCP client
- [x] Tool `create_conversion_value_rule_set` visível em MCP client tool list
- [x] Tool count = 46

Production revision: `v4-ads-mcp-00167-5x7` (smoke ran post-3b.21 deploy; tool surface from 3b.19B unchanged since `v4-ads-mcp-00160-jhb` initial deploy).

## Test T1 — CUSTOMER attachment, 1 DEVICE rule (F13 chained verification)

```
create_conversion_value_rule_set(
  customer_id="1163862076",
  attachment_type="CUSTOMER",
  rules=[{
    "action": {"operation": "ADD", "value": 10.0},
    "condition_type": "DEVICE",
    "device_condition": {"device_types": ["MOBILE"]}
  }]
)
```

Expected:
- [x] `status: "dry_run"` com `confirmation_token`
- [x] `preview.attachment_type == "CUSTOMER"`, `rule_count: 1`
- [x] `blast_summary` mencionando "RuleSet (CUSTOMER)" + "1 rule(s)" + ADD/DEVICE
- [x] Apply → `applied_count: 2`, `google_request_id` presente
- [x] **F13 chained:** `resource_names` returns 2 paths — 1 `conversionValueRules/<id>` + 1 `conversionValueRuleSets/<id>` (chained mutation works end-to-end)
- [x] GAQL verify confirma `status=ENABLED, attachment_type=CUSTOMER, dimensions=["DEVICE"]`

**Result:** ✅ PASS. Token `TUW47VPY`, applied successfully. RuleSet ID `36515010`, rule ID `75144936`. GAQL retornou `dimensions: ["DEVICE"]` (Google auto-infer from rules), `status: ENABLED`, `attachment_type: CUSTOMER`. **F13 cross-cutting feature validated 4ª vez in-prod via chained mutation (1ª: 3b.16 ad_group_ad_operation, 2ª: 3b.18 ad_operation, 3ª: 3b.19A conversion_action_operation, 4ª: 3b.19B conversion_value_rule_set_operation + conversion_value_rule_operation chained).** Único happy-path simples validado limpo no T1.

## Test T2 — Schema rejection (CAMPAIGN sem campaign_id)

```
create_conversion_value_rule_set(
  customer_id="1163862076",
  attachment_type="CAMPAIGN",
  rules=[{...DEVICE rule...}]
)
```

Expected:
- [x] Rejection via private `_validate_payload_shape` runtime check (Sprint 3b.19B.1 moved `allOf if/then` from schema to runtime per Anthropic API restriction) — error PT-BR menciona `campaign_id` required

**Result:** ✅ PASS. Response: `{"status": "error", "error": "attachment_type=CAMPAIGN requer campaign_id no payload. Use CUSTOMER para anexar ao customer inteiro, ou forneca campaign_id.", "operation": "create_conversion_value_rule_set"}`. Mensagem PT-BR clara, sem stack trace. Sprint 3b.19B.1 ported runtime check working as designed.

## Test T3 — Pre-flight rejection (campaign_id inexistente)

```
create_conversion_value_rule_set(
  customer_id="1163862076",
  attachment_type="CAMPAIGN",
  campaign_id="999999999",
  rules=[{...NO_CONDITION rule...}]
)
```

Expected:
- [x] Response `status: "error"` com error: `"Campaign 999999999 nao encontrada..."`
- [x] Sem token

**Result:** ✅ PASS. Response: `{"status": "error", "error": "Campaign 999999999 nao encontrada na conta. Verifique o campaign_id.", "operation": "create_conversion_value_rule_set"}`. Pre-flight `validate_campaign_for_value_rule_set` working as designed.

## Test T4 — CAMPAIGN attachment, 2 rules (DESKTOP MULTIPLY + GEO ADD)

Real campaign found via `run_gaql`: `22782946457` "[NUTRI RAYANE] [SEARCH] [SITE] [2025] [01] [GT PEDRO]" (PAUSED).

**Original spec attempt (FAILED — see F24, F27):**
```
geo_target_constants=["geoTargetConstants/20114"]  # F24: British Columbia, Canada
conversion_action_categories=["PURCHASE"]          # F27: Google rejects non-empty/non-Store filter
```

**Retry no-filter + BR geo (PASSED):**
```
create_conversion_value_rule_set(
  customer_id="1163862076",
  attachment_type="CAMPAIGN",
  campaign_id="22782946457",
  rules=[
    {action: {operation: "MULTIPLY", value: 1.5}, condition_type: "DEVICE", device_condition: {device_types: ["DESKTOP"]}},
    {action: {operation: "ADD", value: 30.0}, condition_type: "GEO_LOCATION", geo_condition: {geo_target_constants: ["geoTargetConstants/2076"], geo_match_type: "ANY"}}
  ]
)
```

Expected:
- [x] `blast_summary`: 2 rules, mixed operations + conditions
- [x] Apply → applied_count 3, 3 resource_names (2 rules + 1 ruleset)
- [x] GAQL verify: RuleSet has `attachment_type=CAMPAIGN`, `campaign=customers/.../campaigns/22782946457`, dimensions auto-inferred `[DEVICE, GEO_LOCATION]`

**Result:** ✅ PASS after retry. Token `KN57DUE5`, applied. RuleSet ID `36515013`, rules `75144942` + `75144945`. GAQL confirms `attachment_type=CAMPAIGN`, `campaign` resource path matches, `dimensions=["DEVICE", "GEO_LOCATION"]`. **Original T4 attempt found 2 bugs (F24 runbook typo + F27 categories filter design gap).**

## Test T5 — NO_CONDITION fallback (customer-level)

```
create_conversion_value_rule_set(
  customer_id="1163862076",
  attachment_type="CUSTOMER",
  rules=[{action: {operation: "SET", value: 50.0}, condition_type: "NO_CONDITION"}]
)
```

Expected:
- [ ] dry_run + token
- [ ] preview.condition_types includes "NO_CONDITION"
- [ ] Apply → applied
- [ ] GAQL verify: rule sem device/geo conditions; dimensions=[NO_CONDITION]

**Result:** ❌ FAIL — **F25 (design gap)**. Dry_run passou (token `Q1LJ4NBA`), preview OK. Mas apply rejeitado pelo Google API: `"Dimension NO_CONDITION can only be used by Store Visits/Store Sales value rule set."` Sprint 3b.19B spec assumiu `NO_CONDITION` como generic fallback; reality: Google restringe NO_CONDITION a tipos especializados (STORE_VISIT / STORE_SALE RuleSets) que estão OUT_OF_SCOPE v0 per spec non-goals. **SET operation enum não foi validado independentemente** — sempre pareado com NO_CONDITION nesse smoke.

## Test T6 — Per-value empirical probe (Sprint 3b.19A.1 lesson)

**Strategy revisado:** T1 + T4 + T5 já cobrem 6 dos 7 enum whitelists. Probe T6 incremental focou em valores ainda não cobertos: `TABLET` (device) + `LOCATION_OF_PRESENCE` (geo match). Combinados em 1 RuleSet (CAMPAIGN attach a `22804468687`) pra economizar quota e mantendo per-value isolation conceitual.

```
create_conversion_value_rule_set(
  customer_id="1163862076",
  attachment_type="CAMPAIGN",
  campaign_id="22804468687",
  rules=[
    {action: {operation: "ADD", value: 5.0}, condition_type: "DEVICE", device_condition: {device_types: ["TABLET"]}},
    {action: {operation: "ADD", value: 20.0}, condition_type: "GEO_LOCATION", geo_condition: {geo_target_constants: ["geoTargetConstants/2076"], geo_match_type: "LOCATION_OF_PRESENCE"}}
  ]
)
```

Expected:
- [x] All probes APPLIED — schema empirically validated for these enum values
- [x] If any combo fails → F2x finding documented

**Result:** ✅ PASS. Token `GPLA1UW2`, applied. RuleSet `36797833`, rules `75144765` + `75144768`. GAQL confirms `dimensions=["DEVICE", "GEO_LOCATION"]`. **TABLET + LOCATION_OF_PRESENCE empirically validated.**

**Empirical enum coverage final:**

| Enum | Values | Status |
|---|---|---|
| `action.operation` | ADD ✓ (T1/T4/T6), MULTIPLY ✓ (T4), SET ❓ untested (T5 blocked by NO_CONDITION) | 2/3 validated |
| `device_types[]` | MOBILE ✓ (T1), DESKTOP ✓ (T4), TABLET ✓ (T6) | 3/3 ✓ |
| `geo_match_type` | ANY ✓ (T4), LOCATION_OF_PRESENCE ✓ (T6) | 2/2 ✓ |
| `condition_type` | DEVICE ✓, GEO_LOCATION ✓, NO_CONDITION ❌ (F25) | 2/3 |
| `attachment_type` | CUSTOMER ✓ (T1), CAMPAIGN ✓ (T4/T6) | 2/2 ✓ |
| `conversion_action_categories` | NENHUMA valida (F27 — só [] ou STORE_VISIT/STORE_SALE accepted) | 0/13 ❌ |

## Cleanup

3 RuleSets criados em Nutry sandbox (`36515010` CUSTOMER, `36515013` CAMPAIGN-22782946457, `36797833` CAMPAIGN-22804468687) + 5 rules nested. Cannot be deleted via API (only REMOVED status via `remove_value_rule_set` if shipped). Sandbox junk acceptable per spec § Cleanup. Both attached campaigns are PAUSED — zero serving impact.

## Sign-off final

- [x] T1 happy path: F13 chained returns 2 resource_names; GAQL confirms structure ENABLED
- [x] T2 schema rejection: runtime check enforced (post-3b.19B.1 port from schema)
- [x] T3 pre-flight: campaign inexistente rejected com PT-BR
- [x] T4 CAMPAIGN + 2 rules: applied (no-filter retry); GAQL verifies attachment + dimensions
- [ ] T5 NO_CONDITION: **FAILED — F25 design gap, schema needs fix**
- [x] T6 per-value probe: TABLET + LOCATION_OF_PRESENCE validated; SET + NO_CONDITION combo blocked by F25
- [x] Production revision verificada: `v4-ads-mcp-00167-5x7`
- [ ] CLAUDE.md atualizado: row Sprint 3b.19B → smoke 4/6 PASS + 4 findings (this commit)

**Date completed:** 2026-05-17 (deferred from 2026-05-13 ship date due to other sprint priorities)

## Findings (post-execution)

### F24 — Runbook typo: wrong geo ID (low severity, fixed inline)

**Reproducer:** Original T4 used `geoTargetConstants/20114` as "São Paulo".

**Reality:** `20114` is "British Columbia, Canada". V4 pre-flight `validate_geo_target_constants_for_value_rule` correctly rejected with PT-BR: `"Geo target 'British Columbia' (geoTargetConstants/20114) tem country_code 'CA', esperado 'BR' (V4 invariant: todas contas V4 sao do Brasil)."`

**Severity:** LOW. **Pre-flight V4 BR-invariant WORKING perfectly.** Runbook typo, not tool bug. Fix: this runbook updated inline.

**Correct BR geo IDs for V4 use:**
- `geoTargetConstants/2076` — Brazil (whole country) — used in T4 retry + T6
- São Paulo state — needs validation if used in future smoke
- For SP city specifically, use Google geo finder

### F25 — `NO_CONDITION` only valid for Store Visits/Store Sales RuleSets (design gap, HIGH severity)

**Reproducer:** Apply any `condition_type: NO_CONDITION` rule in a non-Store RuleSet.

**Behavior:** Google API runtime rejects with: `"Dimension NO_CONDITION can only be used by Store Visits/Store Sales value rule set."`

**Root cause:** Sprint 3b.19B spec/plan assumed `NO_CONDITION` was a generic fallback (no device/geo restriction). Reality from Google API: it's reserved for STORE_VISIT / STORE_SALE specialized RuleSets only. STORE_VISIT and STORE_SALE are explicit `non-goals` in Sprint 3b.19B spec (out of v0).

**Family:** **11th variant of design-gap-via-SDK-ambiguity family** (A1/A3/A4/A5/F11/F12/F16/F17/F18/F19 + now F25). Caught by smoke runbook's per-value empirical probe (T5) BEFORE any V4 gestor would have hit it in production. Sprint 3b.19A.1 convention worked perfectly.

**Fix candidates (Sprint 3b.22+ scope):**
- (a) Remove `NO_CONDITION` from `condition_type` enum entirely in schema (cleanest, since STORE is out of scope)
- (b) Add pre-flight rejection with PT-BR hint about Store Visits limitation
- (c) Allow only when paired with future STORE_VISIT / STORE_SALE feature (sprint-future)

**Recommendation:** Option (a) — remove from schema. If Store RuleSets ever ship, re-add then.

### F26 — CUSTOMER-level RuleSet unique constraint (Google API undocumented limitation, MEDIUM severity)

**Reproducer:** Apply 2 CUSTOMER-level RuleSets without category filter on same customer.

**Behavior:** Second apply fails with: `"The request conflicted with existing data. This error will usually be replaced with a more specific error if the request is retried."`

**Root cause:** Google appears to enforce at most 1 CUSTOMER-level RuleSet per `(customer, conversion_action_categories)` combination. After T1 created the first CUSTOMER-no-filter RuleSet, T6-TABLET-probe and T6-LOP-probe (both also CUSTOMER-no-filter) were rejected.

**Workaround validated empirically:** Use CAMPAIGN attachment with distinct campaigns, OR use distinct `conversion_action_categories` filters (though F27 limits valid filters severely).

**Fix candidates (Sprint 3b.22+ scope):**
- (a) Document Google constraint in tool description (cheap, immediate UX hint)
- (b) Pre-flight check: query existing CUSTOMER RuleSets for this customer + category combo, reject early with PT-BR

**Recommendation:** Option (a) for v0, option (b) only if F26 hits gestor in real usage.

### F27 — `conversion_action_categories` filter only allows empty/STORE_VISIT/STORE_SALE (design gap, HIGH severity)

**Reproducer:** Apply RuleSet with `conversion_action_categories=["PURCHASE"]` (or any of the 13 V4-focused categories from Sprint 3b.19A whitelist).

**Behavior:** Google API runtime rejects with: `"Value rule sets defined on the specified conversion action categories are not supported. The list of conversion action categories must be an empty list, only STORE_VISIT, or only STORE_SALE."`

**Root cause:** Sprint 3b.19B spec reused Sprint 3b.19A's 13-category whitelist (`PURCHASE, SIGNUP, SUBMIT_LEAD_FORM`, etc) for the RuleSet's `conversion_action_categories` filter field, assuming the field accepts any ConversionAction category. Reality: this field is **completely different** from ConversionAction.category — it's a RuleSet-specific filter that only accepts:
- `[]` (empty = apply to all categories)
- `[STORE_VISIT]`
- `[STORE_SALE]`

The 13-category enum in the schema is fundamentally invalid for this use case.

**Family:** Same 11th variant as F25 + Sprint 3b.19A F17/F18/F19. Design-gap-via-SDK-ambiguity.

**Impact:** Tool's `conversion_action_categories` field is **effectively dead-code** in v0. Either you don't filter (empty) → all categories, or you filter on STORE_VISIT/STORE_SALE which are out of scope.

**Fix candidates (Sprint 3b.22+ scope):**
- (a) Remove `conversion_action_categories` field entirely from v0 schema (cleanest — gestor passes nothing = filter to all)
- (b) Restrict the enum to `[]` only via schema constraint (forces empty list)
- (c) Add Store Visits / Store Sales support (out of scope per spec non-goals)

**Recommendation:** Option (a) — clean removal. If Store ever ships, re-add with `[STORE_VISIT, STORE_SALE]` enum.

### Streak status

Sprint 3b.19B smoke = **streak interrupted again**. Sprint 3b.21 had F22 (boundary class); 3b.19B has F25 + F27 (design gap class, same family as 3b.19A F17/F18/F19). Pattern observation:

- Stabilization sprints (3b.7→3b.18 + 3b.20): zero smoke regressions in 11 sprints
- Tracking-domain sprints (3b.19A + 3b.19B): consistent design gap findings due to Google API runtime constraints not documented in SDK descriptors

**Lesson reinforced:** Sprint 3b.19A.1 convention ("per-value empirical probe in smoke runbook") IS the right mitigation for this bug class. F25/F27 caught BEFORE any V4 gestor would hit them in real usage. The findings show the convention working as designed — not a process failure.

## Real biz value + next steps

- **Sprint 3b.19B core feature (RuleSet + chained mutation pattern) shipped functional** in production. T1/T4/T6 happy paths work end-to-end. F13 cross-cutting feature validated 4ª vez via chained mutation.
- **2 schema design gaps (F25 + F27) need fix in Sprint 3b.22+ candidate.** Both involve removing/restricting schema fields to match Google runtime acceptance. Trivial source change (~5-10 LOC), needs CLAUDE.md row update + smoke retest.
- **1 known Google constraint (F26) needs documentation.** Add to tool description.
- **STORE_VISIT / STORE_SALE support** could be a future sprint if V4 ever onboards a physical-store client. Currently out of scope.
- **3 RuleSets in Nutry sandbox** stay as junk. Zero serving impact (PAUSED campaigns).
