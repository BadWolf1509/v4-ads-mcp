# Phase 3b.19B — manual smoke runbook (`create_conversion_value_rule_set`)

**Purpose:** Verify Sprint 3b.19B (quarto create-pattern do MCP). Complementa Sprint 3b.19A — gestor configura valores condicionais sobre ConversionActions existentes (device boost, geo boost).

**Operator:** wellinton.ribeiro@v4company.com
**Account:** `1163862076` Nutry (sandbox; tem 14+ ConversionActions criadas em 3b.19A)

**Spec:** `docs/superpowers/specs/2026-05-13-sprint-3b.19B-design.md`
**Plan:** `docs/superpowers/plans/2026-05-13-sprint-3b.19B-plan.md`

**Sprint 3b.19A.1 lesson applied:** T6 explicit per-value empirical probe pra todos 7 novos enums.

## Pre-flight

- [ ] Deploy lands successfully
- [ ] Service `/health` returns 200
- [ ] Reload MCP client
- [ ] Tool `create_conversion_value_rule_set` visível em MCP client tool list
- [ ] Tool count = 46

Production revision: `v4-ads-mcp-00160-jhb`.

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
- [ ] `status: "dry_run"` com `confirmation_token`
- [ ] `preview.attachment_type == "CUSTOMER"`, `rule_count: 1`
- [ ] `blast_summary` mencionando "RuleSet (CUSTOMER)" + "1 rule(s)" + ADD/DEVICE
- [ ] Apply → `applied_count: 2`, `google_request_id` presente
- [ ] **F13 chained:** `resource_names` returns 2 paths — 1 `conversionValueRules/<id>` + 1 `conversionValueRuleSets/<id>` (chained mutation works end-to-end)
- [ ] GAQL verify via `run_gaql`:
  ```
  SELECT conversion_value_rule_set.id, conversion_value_rule_set.attachment_type, conversion_value_rule_set.status
  FROM conversion_value_rule_set
  WHERE conversion_value_rule_set.id = <id from resource_names[1]>
  ```
  retorna status=ENABLED, attachment_type=CUSTOMER

## Test T2 — Schema rejection (CAMPAIGN sem campaign_id)

```
create_conversion_value_rule_set(
  customer_id="1163862076",
  attachment_type="CAMPAIGN",
  rules=[{
    "action": {"operation": "ADD", "value": 10.0},
    "condition_type": "DEVICE",
    "device_condition": {"device_types": ["MOBILE"]}
  }]
)
```

Expected:
- [ ] JSON Schema rejection (BEFORE tool runs) via `allOf if/then` constraint — error menciona `campaign_id` required

## Test T3 — Pre-flight rejection (campaign_id inexistente)

```
create_conversion_value_rule_set(
  customer_id="1163862076",
  attachment_type="CAMPAIGN",
  campaign_id="999999999",
  rules=[{
    "action": {"operation": "ADD", "value": 10.0},
    "condition_type": "NO_CONDITION"
  }]
)
```

Expected:
- [ ] Response `status: "error"` com error: `"Campaign 999999999 nao encontrada..."`
- [ ] Sem token

## Test T4 — CAMPAIGN attachment, 2 rules (DESKTOP MULTIPLY + GEO SP ADD), category filter

Find a real campaign id via `run_gaql`:
```
SELECT campaign.id, campaign.name FROM campaign WHERE campaign.status = 'PAUSED' LIMIT 1
```

```
create_conversion_value_rule_set(
  customer_id="1163862076",
  attachment_type="CAMPAIGN",
  campaign_id="<real_campaign_id>",
  conversion_action_categories=["PURCHASE"],
  rules=[
    {
      "action": {"operation": "MULTIPLY", "value": 1.5},
      "condition_type": "DEVICE",
      "device_condition": {"device_types": ["DESKTOP"]}
    },
    {
      "action": {"operation": "ADD", "value": 30.0},
      "condition_type": "GEO_LOCATION",
      "geo_condition": {
        "geo_target_constants": ["geoTargetConstants/20114"],
        "geo_match_type": "ANY"
      }
    }
  ]
)
```

Expected:
- [ ] `blast_summary`: "RuleSet (CAMPAIGN) com 2 rule(s): operations {'MULTIPLY': 1, 'ADD': 1}, conditions {'DEVICE': 1, 'GEO_LOCATION': 1}."
- [ ] Apply → applied_count 3, 3 resource_names
- [ ] GAQL verify: RuleSet has `attachment_type=CAMPAIGN`, `campaign=<campaign_path>`, `conversion_action_categories=[PURCHASE]`, 2 rules attached

## Test T5 — NO_CONDITION fallback (customer-level)

```
create_conversion_value_rule_set(
  customer_id="1163862076",
  attachment_type="CUSTOMER",
  rules=[{
    "action": {"operation": "SET", "value": 50.0},
    "condition_type": "NO_CONDITION"
  }]
)
```

Expected:
- [ ] dry_run + token
- [ ] preview.condition_types includes "NO_CONDITION"
- [ ] Apply → applied
- [ ] GAQL verify: rule sem device/geo conditions; dimensions=[NO_CONDITION]

## Test T6 — Per-value empirical probe (Sprint 3b.19A.1 lesson)

Goal: validate every enum value em todos 7 whitelists antes que design gap surface em produção.

**T6.1 Operations** (3 values, 1 minimal NO_CONDITION rule each):
- ADD: `{action: {operation: "ADD", value: 1.0}, condition_type: "NO_CONDITION"}` em CUSTOMER set
- MULTIPLY: idem com `operation: "MULTIPLY"`, `value: 1.0`
- SET: idem com `operation: "SET"`

**T6.2 Device types** (3 values, 1 DEVICE rule each):
- MOBILE: `device_condition: {device_types: ["MOBILE"]}`
- DESKTOP: idem
- TABLET: idem

**T6.3 Geo match types** (2 values, 1 GEO rule each, geo_target = Brazil):
- ANY: `geo_match_type: "ANY"` + `geo_target_constants: ["geoTargetConstants/2076"]`
- LOCATION_OF_PRESENCE: idem com match=LOCATION_OF_PRESENCE

**T6.4 Attachment types** (2 values):
- CUSTOMER: any minimal rule
- CAMPAIGN: with valid `campaign_id`

Expected:
- [ ] All 10 probe combos APPLIED — schema is empirically validated
- [ ] If any combo fails → document as F2x finding em Sprint 3b.19B.1 follow-up + remove from schema

## Cleanup

N RuleSets + (10+) Rules criadas em Nutry sandbox. Não podem ser deleted via API (apenas REMOVED status). Aceitar como sandbox junk — zero serving impact.

## Sign-off final

- [ ] T1 happy path: F13 chained returns 2 resource_names; GAQL confirms structure
- [ ] T2 schema rejection: allOf if/then enforced antes do runtime
- [ ] T3 pre-flight: campaign inexistente rejected com PT-BR
- [ ] T4 CAMPAIGN + GEO + filter: applied + GAQL verifies all fields
- [ ] T5 NO_CONDITION: applied + dimensions inferred
- [ ] T6 per-value probe: all 10 enum combos APPLIED (or F2x findings documented)
- [ ] Production revision verificada
- [ ] CLAUDE.md atualizado: Sprint 3b.19B shipped, tool count 45 → 46

**Date completed:** ____

## Findings (post-execution)

(Inline — surfaceados durante smoke.)
