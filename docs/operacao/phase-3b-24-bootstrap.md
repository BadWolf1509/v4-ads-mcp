# Phase 3b.24 — manual smoke runbook (`create_campaign` SEARCH v0)

**Purpose:** Validar Sprint 3b.24 — quinto create-pattern do MCP, foundation pra onboarding completo V4 via Claude/Codex.

**Operator:** wellinton.ribeiro@v4company.com
**Account:** `1163862076` Nutry (sandbox — campaigns serão PAUSED, zero serving impact)

**Spec:** `docs/superpowers/specs/2026-05-17-sprint-3b-24-create-campaign-design.md`
**Plan:** `docs/superpowers/plans/2026-05-17-sprint-3b-24-create-campaign.md`

**Sprint 3b.19A.1 lesson aplicado:** T5 explicit per-strategy empirical probe pra todas 6 bidding strategies.

## Pre-flight

- [x] Deploy lands successfully (`gh run watch 26008265894` green em ~3m)
- [x] Service `/health` returns 200
- [ ] **Wellington action: restart Claude Code session pra schema cache atualizar com novo tool** (F28 reproducer — controller session pre-deploy não vê `create_campaign`)
- [ ] Tool `create_campaign` visível em MCP tool list (count 46 → 47) — verificar post-restart

Production revision: `v4-ads-mcp-00175-dfn`.

## Test T1 — Happy path: MAX_CONVERSIONS + 1 geo (Brazil whole)

```
create_campaign(
  customer_id="1163862076",
  name="[3b.24 smoke] T1 - max_conv brazil",
  bidding_strategy={"type": "MAXIMIZE_CONVERSIONS"},
  daily_budget_brl=10.0,
  geo_targets=["geoTargetConstants/2076"]
)
```

Expected:
- [ ] dry_run com confirmation_token
- [ ] blast_summary: "Criar 1 campanha SEARCH (PAUSED) + budget BRL 10.00/dia + 1 geo target(s) + PT language. Bidding: MAXIMIZE_CONVERSIONS."
- [ ] preview com bidding_strategy_type, daily_budget_brl, geo_count=1, has_schedule=false
- [ ] apply → applied_count = 4 (budget + campaign + 1 geo + 1 language)
- [ ] resource_names array com 4 paths
- [ ] GAQL verify:
```
SELECT campaign.id, campaign.name, campaign.status, campaign.advertising_channel_type,
  campaign.bidding_strategy_type, campaign_budget.amount_micros
FROM campaign
WHERE campaign.id = <id from resource_names[1]>
```
Retorna: status=PAUSED, channel=SEARCH, strategy=MAXIMIZE_CONVERSIONS, budget=10_000_000 micros.

**Result:** ⬜ pending

## Test T2 — TARGET_CPA happy path

```
create_campaign(
  customer_id="1163862076",
  name="[3b.24 smoke] T2 - target_cpa 25brl",
  bidding_strategy={"type": "TARGET_CPA", "target_cpa_brl": 25.0},
  daily_budget_brl=10.0,
  geo_targets=["geoTargetConstants/2076"]
)
```

Expected:
- [ ] dry_run + apply
- [ ] GAQL verify: `SELECT campaign.target_cpa.target_cpa_micros FROM campaign WHERE campaign.id = <id>` → 25_000_000

**Result:** ⬜ pending

## Test T3 — Runtime rejection: TARGET_CPA sem target_cpa_brl

```
create_campaign(
  customer_id="1163862076",
  name="[3b.24 smoke] T3 - invalid",
  bidding_strategy={"type": "TARGET_CPA"},  # missing target_cpa_brl
  daily_budget_brl=10.0,
  geo_targets=["geoTargetConstants/2076"]
)
```

Expected:
- [ ] response status=error
- [ ] error message PT-BR: "TARGET_CPA requer bidding_strategy.target_cpa_brl."
- [ ] sem confirmation_token

**Result:** ⬜ pending

## Test T4 — Pre-flight V4 BR rejection (Canada geo)

```
create_campaign(
  customer_id="1163862076",
  name="[3b.24 smoke] T4 - canada geo",
  bidding_strategy={"type": "MAXIMIZE_CONVERSIONS"},
  daily_budget_brl=10.0,
  geo_targets=["geoTargetConstants/20114"]  # British Columbia, Canada
)
```

Expected:
- [ ] response status=error
- [ ] error message PT-BR menciona country_code='CA' esperado 'BR'
- [ ] sem confirmation_token

**Result:** ⬜ pending

## Test T5 — Per-strategy empirical probe (Sprint 3b.19A.1 lesson)

Validate every bidding strategy enum value works end-to-end. Each call creates a campaign with minimal config for that strategy.

T5.1 MAXIMIZE_CONVERSION_VALUE:
```
bidding_strategy={"type": "MAXIMIZE_CONVERSION_VALUE"}
```

T5.2 TARGET_ROAS:
```
bidding_strategy={"type": "TARGET_ROAS", "target_roas": 3.0}
```

T5.3 MANUAL_CPC + enhanced_cpc:
```
bidding_strategy={"type": "MANUAL_CPC", "enhanced_cpc": true}
```

T5.4 MAXIMIZE_CLICKS + ceiling:
```
bidding_strategy={"type": "MAXIMIZE_CLICKS", "cpc_bid_ceiling_brl": 1.5}
```

Expected:
- [ ] All 4 probes APPLY successfully (combined com MAX_CONVERSIONS T1 + TARGET_CPA T2 = 6/6 strategies validated)
- [ ] If any combo fails → F2x finding documentado + remover strategy do schema enum

**Result:** ⬜ pending

## Test T6 — F13 chained mutation verification

Inspect T1 apply response. `resource_names` should be 4-element array:

```
[
  "customers/1163862076/campaignBudgets/<budget_id>",
  "customers/1163862076/campaigns/<campaign_id>",
  "customers/1163862076/campaignCriteria/<campaign_id>~<location_id>",
  "customers/1163862076/campaignCriteria/<campaign_id>~<language_id>"
]
```

Expected:
- [ ] Length = 4
- [ ] Order: budget, campaign, geo criterion, language criterion
- [ ] Each path has correct prefix
- [ ] Campaign criteria use compound `{campaign_id}~{criterion_id}` format (Sprint 3b.6 A5 pattern)

**Result:** ⬜ pending

## Test T7 — Multi-geo + schedule probe

```
create_campaign(
  customer_id="1163862076",
  name="[3b.24 smoke] T7 - multigeo + schedule",
  bidding_strategy={"type": "MAXIMIZE_CONVERSIONS"},
  daily_budget_brl=15.0,
  geo_targets=["geoTargetConstants/2076", "geoTargetConstants/20106"],  # Brasil + SP state
  start_date="2026-05-20",
  end_date="2026-12-31"
)
```

Expected:
- [ ] dry_run + apply, applied_count = 5 (1 budget + 1 campaign + 2 geos + 1 language)
- [ ] resource_names length = 5
- [ ] GAQL verify campaign has start_date=2026-05-20, end_date=2026-12-31
- [ ] GAQL verify 2 location criteria exist for campaign
- [ ] **Validate languageConstants/1014 open question:** GAQL `SELECT campaign_criterion.language.language_constant FROM campaign_criterion WHERE campaign.id = <id> AND campaign_criterion.type = LANGUAGE` retorna "languageConstants/1014" + Google's display = "Portuguese". Se diferente, documentar F2x + ajustar builder hardcoded constant.

**Result:** ⬜ pending

## Cleanup

7 test campaigns serão criadas em Nutry sandbox. Cannot be deleted via API v0 (Sprint 3b.28 vai shipar `remove_campaign`). Aceitar como sandbox junk per spec § Cleanup. All campaigns PAUSED — zero serving impact.

## Sign-off final

- [ ] T1 happy path: F13 chained returns 4 resource_names; GAQL confirms structure
- [ ] T2 TARGET_CPA: applied + GAQL confirms target_cpa_micros
- [ ] T3 runtime rejection: TARGET_CPA sem target_cpa_brl rejected antes do pre-flight
- [ ] T4 V4 BR pre-flight: Canada geo rejected com PT-BR
- [ ] T5 per-strategy probe: 4 remaining strategies (MAX_CONV_VALUE + TARGET_ROAS + MANUAL_CPC + MAX_CLICKS) all applied
- [ ] T6 F13 chained: 4-element resource_names array em ordem correta
- [ ] T7 multi-geo + schedule: 5 ops + dates persisted + languageConstants/1014 validated
- [ ] Production revision verificada
- [ ] CLAUDE.md atualizado: Sprint 3b.24 shipped, tool count 46 → 47

**Date completed:** ____

## Findings (post-execution)

(Inline — surfaceados durante smoke.)
