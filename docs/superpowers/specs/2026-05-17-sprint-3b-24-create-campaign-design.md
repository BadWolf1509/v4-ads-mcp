# Sprint 3b.24 — `create_campaign` SEARCH v0 design

**Status:** Draft → user review pending
**Owner:** Wellington (`wellinton.ribeiro@v4company.com`)
**Date:** 2026-05-17
**Predecessor:** Sprint 3b.23 (F22 limit param) — começa fase de finalização (5 sprints restantes pra cobertura completa de gestão V4 via MCP)
**Successors planejados:** 3b.25 (`create_asset` + `link_assets`), 3b.26 (`import_offline_conversions`), 3b.27 (`upload_customer_match_list` + A4 fix), 3b.28 (`remove_*` bundle)

## Goal

Primeiro mutation tool de campaign create no MCP V4. Permite gestor onboardar cliente novo completamente via Claude/Codex sem cair pra Google Ads UI — `create_ad_group/rsa/add_keywords` (já shipped) ficam isolados sem `create_campaign` pra atachar.

V4 use case: lead-gen agency Brazil, dogfood real em accounts MO-JP / Nutry / ML Antiguidades / Expresso. Pattern atual = onboarding via UI Google Ads + edição via MCP. Após 3b.24, onboarding completo via MCP.

## Context / why now

- **Wellington decisão:** roadmap de finalização confirmado, sequência 3b.24→3b.28 começando por foundation (`create_campaign`).
- **Scope decisões v0** (validated brainstorming 2026-05-17):
  - Bidding: 6 strategies (MAX_CONVERSIONS, MAX_CONVERSION_VALUE, TARGET_CPA, TARGET_ROAS, MANUAL_CPC, MAX_CLICKS)
  - Geo: required explicit (V4 pre-flight valida BR-only)
  - Language: auto-default PT
  - Conversion goals: inherit account default (sem override field v0)
  - Channel: SEARCH only (PMAX/DISPLAY/SHOPPING ficam pra v1 com real demand)
- **Sem dependência de Standard Access** (análise empírica 2026-05-17: uso atual 0.07% do limit Basic)
- **Padrão consolidado:** quinto create-pattern (`create_ad_group` 3b.14, `create_rsa` 3b.16, `create_conversion_action` 3b.19A, `create_conversion_value_rule_set` 3b.19B + 3b.22 cleanup, `create_campaign` 3b.24)
- **Chained mutation reused:** Sprint 3b.19B established pattern (N+1 ops em single MutateGoogleAdsRequest); 3b.24 reusa com N+M+2 ops (budget + campaign + N geo criterions + M language criterion)

## Non-goals (v0)

- **PMAX (Performance Max) channel** — v1 quando V4 onboardar caso real (significativamente diferente de SEARCH: asset groups, audience signals, no keywords)
- **DISPLAY / SHOPPING / VIDEO channels** — v1
- **Portfolio bidding strategies (shared)** — gestor usa daily fixed budget; portfolio bidding fica pra v1
- **Campaign budget RESERVATIONS / Shared budgets** — daily fixed only
- **AdServingOptimizationStatus override** — defaults Google
- **Frequency cap** — display-specific, irrelevant SEARCH
- **Audience targeting at campaign level** — fica pra ad_group level via `apply_audience` (já shipped) ou re-evaluar v1
- **Custom conversion goals override** — inherit account default (Q3 brainstorm answer)
- **ENHANCED_CPC como standalone strategy** — Google deprecou ENHANCED_CPC; manual_cpc + enhanced_cpc:true flag é o caminho atual
- **Name uniqueness pre-flight** — Sprint 3b.14 F14 lesson aplicado: Google's próprio rejection é claro o suficiente
- **Batch create (múltiplas campaigns por chamada)** — V4 onboarding workflow = 1 campaign por chamada típico, YAGNI
- **Schedule / ad rotation settings** — defaults Google

## Tool surface

### Name
`create_campaign`

### Description (PT-BR)

```
Cria 1 SEARCH campaign nova em uma conta V4. Always-CONFIRM. Schema requer
name + bidding_strategy + daily_budget_brl + geo_targets (lista de
geoTargetConstants resource paths, validados como BR via pre-flight V4).
Status sempre PAUSED on create — gestor liga manualmente apos review.
Language defaults Portuguese. Search Partners + Display Network OFF
(V4 defaults). Bidding strategies suportadas v0: MAXIMIZE_CONVERSIONS,
MAXIMIZE_CONVERSION_VALUE, TARGET_CPA (requer target_cpa_brl),
TARGET_ROAS (requer target_roas), MANUAL_CPC (opcional enhanced_cpc),
MAXIMIZE_CLICKS (opcional cpc_bid_ceiling_brl). Conversion goals
inherit account-default (override fica pra v1). Channel SEARCH only
v0 (PMAX/DISPLAY/SHOPPING v1). Builder usa chained mutation pattern
(budget op + campaign op + N geo criterion ops + 1 language criterion
op em single MutateGoogleAdsRequest). F13 resource_names auto-retorna
todos paths criados.
```

### Input schema (JSONSchema, sem composition keywords per 3b.19B.1)

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["customer_id", "name", "bidding_strategy", "daily_budget_brl", "geo_targets"],
  "properties": {
    "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
    "name": {"type": "string", "minLength": 1, "maxLength": 256},
    "bidding_strategy": {
      "type": "object",
      "additionalProperties": false,
      "required": ["type"],
      "properties": {
        "type": {
          "type": "string",
          "enum": [
            "MAXIMIZE_CONVERSIONS",
            "MAXIMIZE_CONVERSION_VALUE",
            "TARGET_CPA",
            "TARGET_ROAS",
            "MANUAL_CPC",
            "MAXIMIZE_CLICKS"
          ]
        },
        "target_cpa_brl": {"type": "number", "minimum": 0.01},
        "target_roas": {"type": "number", "minimum": 0.01},
        "cpc_bid_ceiling_brl": {"type": "number", "minimum": 0.01},
        "enhanced_cpc": {"type": "boolean"}
      }
    },
    "daily_budget_brl": {"type": "number", "minimum": 1.0},
    "geo_targets": {
      "type": "array",
      "minItems": 1,
      "uniqueItems": true,
      "items": {
        "type": "string",
        "pattern": "^geoTargetConstants/[0-9]+$"
      }
    },
    "start_date": {
      "type": "string",
      "pattern": "^\\d{4}-\\d{2}-\\d{2}$"
    },
    "end_date": {
      "type": "string",
      "pattern": "^\\d{4}-\\d{2}-\\d{2}$"
    }
  }
}
```

### Runtime payload validation (`_validate_payload_shape`)

Replaces schema-level `allOf if/then` (rejected by Anthropic API per Sprint 3b.19B.1). Returns PT-BR error string or None.

Rules:

| condition | error |
|---|---|
| `bidding_strategy.type == "TARGET_CPA"` AND `target_cpa_brl` ausente | "TARGET_CPA requer bidding_strategy.target_cpa_brl" |
| `bidding_strategy.type == "TARGET_ROAS"` AND `target_roas` ausente | "TARGET_ROAS requer bidding_strategy.target_roas" |
| `enhanced_cpc` presente AND `type != "MANUAL_CPC"` | "enhanced_cpc só é válido com MANUAL_CPC" |
| `cpc_bid_ceiling_brl` presente AND `type != "MAXIMIZE_CLICKS"` | "cpc_bid_ceiling_brl só é válido com MAXIMIZE_CLICKS" |
| `target_cpa_brl` presente AND `type not in ("TARGET_CPA", "MAXIMIZE_CONVERSIONS")` | "target_cpa_brl válido apenas para TARGET_CPA ou MAXIMIZE_CONVERSIONS (eCPC mode)" |
| `target_roas` presente AND `type not in ("TARGET_ROAS", "MAXIMIZE_CONVERSION_VALUE")` | "target_roas válido apenas para TARGET_ROAS ou MAXIMIZE_CONVERSION_VALUE" |
| `start_date` presente AND `end_date` presente AND `start_date > end_date` | "start_date posterior a end_date" |

### V4 hardcoded invariants (no builder, no schema)

| field | valor hardcoded | rationale |
|---|---|---|
| `Campaign.status` | `PAUSED` | V4 invariant — never enable on create (gestor manual review post-create). Consistente com create_ad_group/create_rsa/create_conversion_action. |
| `Campaign.advertising_channel_type` | `SEARCH` | v0 SEARCH-only scope |
| `Campaign.network_settings.target_search_network` | `True` | SEARCH primary target |
| `Campaign.network_settings.target_content_network` | `False` | V4 default — no Display Network expansion |
| `Campaign.network_settings.target_partner_search_network` | `False` | V4 default — no Search Partners |
| `CampaignBudget.delivery_method` | `STANDARD` | V4 default (não accelerated) |
| `CampaignBudget.amount_micros` | `daily_budget_brl × 1_000_000` | BRL→micros conversion |
| `CampaignCriterion(LANGUAGE)` | `languageConstants/1014` (Portuguese) | V4 invariant. Always auto-added. |
| `CampaignCriterion(LOCATION)` | from `geo_targets` array | Required explicit per gestor decision |

## Architecture

### Files

- **New:** `src/google_ads/mutates/campaigns.py` (builder)
- **New:** `src/mcp/tools/create_campaign.py` (tool)
- **Modify:** `src/google_ads/queries/_common.py` (extend `validate_geo_target_constants_for_value_rule` OR add `validate_geo_target_constants_for_campaign` if signature differs)
- **New tests:** `tests/unit/test_create_campaign.py`, `tests/unit/test_create_campaign_builder.py`, `tests/integration/test_create_campaign.py`
- **Optional retrofit:** `tests/unit/fixtures/proto_capture.py` — extend mocks for CampaignService + CampaignBudgetService + GoogleAdsService.campaign_path/campaign_budget_path/campaign_criterion_path if not already present

### Chained mutation operations

Builder produces **N+M+2 operations** in single MutateGoogleAdsRequest. Temp resource names use negative IDs (Google replaces post-create):

```
ops[0]: campaign_budget_operation.create
  resource_name = customers/{cid}/campaignBudgets/-1
  name = "{campaign_name} - budget"
  amount_micros = daily_budget_brl × 1_000_000
  delivery_method = STANDARD

ops[1]: campaign_operation.create
  resource_name = customers/{cid}/campaigns/-2
  name = payload.name
  status = PAUSED
  advertising_channel_type = SEARCH
  campaign_budget = customers/{cid}/campaignBudgets/-1  (temp ref)
  bidding_strategy_type = payload.bidding_strategy.type (mapped to enum)
  + conditional scalar fields per strategy type
  network_settings.target_search_network = True
  network_settings.target_content_network = False
  network_settings.target_partner_search_network = False
  start_date = payload.start_date (if provided)
  end_date = payload.end_date (if provided)

ops[2..N+1]: campaign_criterion_operation.create × N (geo)
  campaign = customers/{cid}/campaigns/-2  (temp ref)
  location.geo_target_constant = each path from geo_targets array

ops[N+2]: campaign_criterion_operation.create × 1 (language)
  campaign = customers/{cid}/campaigns/-2  (temp ref)
  language.language_constant = "languageConstants/1014"  (PT hardcoded)
```

**Total ops:** 1 + 1 + N + 1 where N = len(geo_targets).

F13 cross-cutting (Sprint 3b.15) auto-returns `resource_names` array with real IDs post-create.

### Bidding strategy → proto field mapping

| schema `type` | proto field | conditional scalars |
|---|---|---|
| `MAXIMIZE_CONVERSIONS` | `campaign.maximize_conversions` | optional `target_cpa_micros` (eCPC mode) |
| `MAXIMIZE_CONVERSION_VALUE` | `campaign.maximize_conversion_value` | optional `target_roas` |
| `TARGET_CPA` | `campaign.target_cpa` | required `target_cpa_micros = target_cpa_brl × 1_000_000` |
| `TARGET_ROAS` | `campaign.target_roas` | required `target_roas` (decimal, e.g., 5.0 = 500%) |
| `MANUAL_CPC` | `campaign.manual_cpc` | optional `enhanced_cpc_enabled` |
| `MAXIMIZE_CLICKS` | `campaign.target_spend` | optional `cpc_bid_ceiling_micros` |

### Pre-flights

**Active:** `validate_geo_target_constants_for_campaign` — reuse existing `validate_geo_target_constants_for_value_rule` helper from Sprint 3b.19B em `_common.py`. **Decision point:** if signature compatible (same args: manager_id, session_id, customer_id, geo_paths) and returns same shape (Optional[str] error PT-BR), reuse directly. Otherwise create thin wrapper or rename helper to generic `validate_geo_target_constants_br_only` (since the logic is identical: query GAQL, assert country_code='BR', return PT-BR error).

**Recommended:** rename helper to `validate_geo_target_constants_br_only` (generic) and use from both create_conversion_value_rule_set + create_campaign. Sprint 3b.19B convention "extract to _common.py for cross-tool reuse" applies (similar to Sprint 3b.21 extraction of parse_resource_path).

**Not active (intentional v0):**
- Name uniqueness check — Sprint 3b.14 F14 lesson: Google's rejection is clear enough, no pre-flight needed
- conversion_action_categories validation — N/A for campaign (no such field in v0 schema)
- Bidding strategy compatibility (deprecation check) — Google handles via API rejection

### F13 auto-return validation

Sprint 3b.15 `resource_names` field auto-extracted from `MutateGoogleAdsResponse`. Tool returns array:
```
[
  "customers/{cid}/campaignBudgets/{budget_id}",
  "customers/{cid}/campaigns/{campaign_id}",
  "customers/{cid}/campaignCriteria/{campaign_id}~{location_id_1}",
  ...,
  "customers/{cid}/campaignCriteria/{campaign_id}~{language_id}"
]
```

Total length = 2 + N + 1 (budget + campaign + N locations + 1 language).

## Audit + governance

- **Always CONFIRM** (sensitive create, per spec §7.1). Returns `dry_run` + `confirmation_token` on first call; `apply_change(token)` executes.
- **Blast radius:** classify as `target_count = 2 + N + 1` (1 budget + 1 campaign + N geo criterions + 1 language criterion).
- **Audit log:**
  - `operation_type = "create_campaign"`
  - `target_count = 2 + N + 1`
  - `google_request_id` from response
  - `params_summary`: counts only per spec §3.6 — `{"bidding_strategy_type": str, "daily_budget_brl": float, "geo_count": int, "has_schedule": bool}` — no name or geo path content (compliance with audit-safe redaction)
- **Quota cost:** 2 + N + 1 reserved ops (1 per resource created). Trivial vs 15k/day Basic.

## Testing strategy

### Unit tests

**`tests/unit/test_create_campaign.py`** (~10 tests):

1. `test_schema_requires_core_fields` — missing customer_id/name/bidding_strategy/daily_budget_brl/geo_targets all reject
2. `test_schema_rejects_additional_properties` — `additionalProperties: false` enforced (no `advertising_channel_type`, no `status` allowed)
3. `test_schema_rejects_unknown_bidding_strategy` — enum constraint
4. `test_runtime_target_cpa_requires_target_cpa_brl` — runtime PT-BR error
5. `test_runtime_target_roas_requires_target_roas`
6. `test_runtime_enhanced_cpc_only_with_manual_cpc`
7. `test_runtime_cpc_bid_ceiling_only_with_maximize_clicks`
8. `test_runtime_target_cpa_brl_invalid_with_target_roas_strategy`
9. `test_runtime_inverted_dates_rejected` — start_date > end_date
10. `test_geo_pre_flight_rejects_non_br` — mock helper returns error, tool propagates with PT-BR

**`tests/unit/test_create_campaign_builder.py`** (~7 tests using ProtoFieldCapture):

1. `test_builder_happy_path_max_conversions_minimal` — 1 geo, MAX_CONV, defaults. Asserts: 4 ops total (budget + campaign + 1 geo + 1 lang), status=PAUSED, channel=SEARCH, partners=False, content=False, budget micros conversion.
2. `test_builder_target_cpa_sets_target_cpa_micros` — TARGET_CPA + target_cpa_brl=50 → target_cpa_micros=50_000_000
3. `test_builder_target_roas_sets_target_roas` — TARGET_ROAS + target_roas=4.0 → target_roas=4.0 (no micros)
4. `test_builder_manual_cpc_with_enhanced_cpc_flag` — MANUAL_CPC + enhanced_cpc=True
5. `test_builder_maximize_clicks_with_ceiling` — MAX_CLICKS + cpc_bid_ceiling_brl=2.5 → cpc_bid_ceiling_micros=2_500_000
6. `test_builder_multiple_geo_targets_emit_multiple_criteria_ops` — 3 geos → 6 ops (1+1+3+1)
7. `test_builder_language_criterion_always_present` — confirms `languageConstants/1014` criterion added regardless of input

**Pre-flight helper:** if reusing `validate_geo_target_constants_br_only`, no new tests needed (Sprint 3b.19B already covers). If renaming, retrofit existing tests.

### Integration test

**`tests/integration/test_create_campaign.py`** (1 e2e test):

`test_create_campaign_e2e_with_mocked_sdk` — uses testcontainers postgres + mocks Google Ads SDK responses. Verifies:
- dry_run returns token + blast_summary
- apply_change consumes token + builder runs
- audit_log row written with target_count = 4 (1+1+1+1 for minimal config)
- google_request_id propagated
- params_summary has correct keys (bidding_strategy_type, daily_budget_brl, geo_count, has_schedule)

### Smoke runbook (Nutry sandbox)

Account `1163862076` Nutry. Test campaigns will be PAUSED — zero serving impact.

**T1 — Happy path minimal SEARCH + MAX_CONVERSIONS**

```
create_campaign(
  customer_id="1163862076",
  name="[3b.24 smoke] Test 1 - max_conv",
  bidding_strategy={"type": "MAXIMIZE_CONVERSIONS"},
  daily_budget_brl=10.0,
  geo_targets=["geoTargetConstants/2076"]  # Brazil whole
)
→ dry_run → apply
```

Expected:
- dry_run preview com blast_summary "Criar 1 campanha SEARCH (PAUSED) + budget BRL 10/dia + 1 geo target + PT language. Bidding: MAXIMIZE_CONVERSIONS."
- apply → applied_count = 4, resource_names array com 4 paths
- GAQL verify: `SELECT campaign.id, campaign.name, campaign.status, campaign.advertising_channel_type, campaign_budget.amount_micros FROM campaign WHERE campaign.id = <id>` retorna status=PAUSED, channel=SEARCH, budget=10_000_000 micros

**T2 — TARGET_CPA happy path**

```
bidding_strategy={"type": "TARGET_CPA", "target_cpa_brl": 25.0}
```

Expected: dry_run → apply → GAQL confirms target_cpa_micros = 25_000_000.

**T3 — Runtime rejection: TARGET_CPA sem target_cpa_brl**

```
bidding_strategy={"type": "TARGET_CPA"}  # missing target_cpa_brl
```

Expected: error PT-BR `"TARGET_CPA requer bidding_strategy.target_cpa_brl"` antes do pre-flight.

**T4 — Geo pre-flight rejection (Canada)**

```
geo_targets=["geoTargetConstants/20114"]  # British Columbia
```

Expected: pre-flight V4 BR-invariant rejeita com PT-BR mencionando country_code='CA'.

**T5 — Per-strategy probe (validate each enum)**

6 calls, one per bidding strategy, minimal config for each:
- MAXIMIZE_CONVERSIONS (already T1)
- MAXIMIZE_CONVERSION_VALUE — no extra fields
- TARGET_CPA (already T2)
- TARGET_ROAS + target_roas=3.0
- MANUAL_CPC + enhanced_cpc=true
- MAXIMIZE_CLICKS + cpc_bid_ceiling_brl=1.5

Expected: all apply successfully. If any combo fails → F2x finding documented.

**T6 — F13 chained mutation verification**

Inspect T1 apply response — `resource_names` array length = 4, format:
```
[
  "customers/1163862076/campaignBudgets/<id>",
  "customers/1163862076/campaigns/<id>",
  "customers/1163862076/campaignCriteria/<campaign_id>~<location_id>",
  "customers/1163862076/campaignCriteria/<campaign_id>~<language_id>"
]
```

**T7 — Multi-geo + schedule probe**

```
geo_targets=["geoTargetConstants/2076", "geoTargetConstants/20180"]  # Brasil + SP state
start_date="2026-05-20"
end_date="2026-12-31"
```

Expected: 5 ops total, GAQL verify campaign has 2 location criteria + start/end dates set.

**Cleanup:** test campaigns stay PAUSED in Nutry sandbox. Cannot be deleted via API v0 (only via Sprint 3b.28 `remove_campaign` future). Acceptable as sandbox junk per spec § Cleanup.

## Quality gates

- `python scripts/check_pre_push.py` 5/5 PASS antes do push
- Smoke T1-T7 PASS first try em Nutry sandbox antes de signoff
- Streak status: pos-3b.22 + 3b.23 clean smokes, 3b.24 SHOULD continue streak (test-driven + ProtoFieldCapture + pre-flight reuse de 3b.19B = mock-fidelity high)

## Open questions / decisions log

- **Decisão Q1 (brainstorming):** 6 bidding strategies (V4 wider coverage > minimal v0)
- **Decisão Q2 (brainstorming):** Geo required explicit + language auto-default PT
- **Decisão Q3 (brainstorming):** Conversion goals inherit account default (no override v0)
- **Decisão (design):** Helper `validate_geo_target_constants_for_value_rule` renamed to generic `validate_geo_target_constants_br_only` em `_common.py` for cross-tool reuse (extension of Sprint 3b.21 parse_resource_path extraction pattern)
- **Decisão (design):** Builder em novo file `src/google_ads/mutates/campaigns.py` (consistent com `conversion_value_rules.py`/`negative_keywords.py` pattern: 1 file per resource family)
- **Decisão (design):** No name uniqueness pre-flight (3b.14 F14 lesson: rely on Google's clear error)
- **Open question (to be empirically validated em smoke):** Does `languageConstants/1014` actually correspond to "pt" or "pt-BR" in Google Ads? Per Google docs `1014 = Portuguese`. Smoke T1 will verify via GAQL `SELECT campaign_criterion.language.language_constant FROM campaign_criterion WHERE campaign.id = <id>` → if shows pt-BR (constant 1014 returns Portuguese label), validated. If wrong constant ID → fix builder + retest.

## Out-of-scope follow-ups (spawn-task candidates)

- **`update_campaign`** — modify name, bidding strategy params, geo, budget, dates post-create. Útil pra ajustes pós-onboarding. Sprint candidate post-3b.28 se demand.
- **`remove_campaign`** — Sprint 3b.28 candidate (bundle com remove_keyword/ad_group/ad)
- **Audience criterion at campaign level** — future v1 (3b.X) se gestor pedir
- **Custom conversion goals override** (campaign_conversion_goals API) — v1 com real demand
- **PMAX channel** — future sprint, significativamente diferente (asset groups, audience signals, no keywords)
- **Saved audiences attachment** — v1 com real demand

## Real biz value (post-ship)

- **Gestor V4 ganha onboarding completo via MCP:** new client flow = `create_campaign` → `create_ad_group` → `create_rsa` → `add_keywords` → done. Zero saltos pra Google Ads UI.
- **Foundation pra Sprints 3b.25-3b.28:** `create_asset` + `link_assets` precisam de campaign existente; `import_offline_conversions` precisa de conversion action (já tem); `upload_customer_match_list` independente; `remove_*` precisa de entities pra remover (campaign now creatable).
- **Pattern reusable:** chained mutation pattern de 3b.19B validated quarta vez (3b.19B RuleSet + 3b.24 Campaign budget+campaign+criteria). Próximo create-pattern hereditará.
