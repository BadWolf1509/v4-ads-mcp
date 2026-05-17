# Phase 3b.22 — manual smoke runbook (F25+F27 schema cleanup)

**Purpose:** Validar Sprint 3b.22 schema cleanup em `create_conversion_value_rule_set` — closes Sprint 3b.19B findings F25 + F27. Schema agora rejeita os 2 enum values dead-code antes que cheguem ao Google API.

**Operator:** wellinton.ribeiro@v4company.com
**Account:** `1163862076` Nutry (sandbox; já tem 3 RuleSets criados em Sprint 3b.19B smoke 17/05)

**Spec:** Sprint 3b.19B findings F25 + F27 + F26 (em `docs/operacao/phase-3b-19B-bootstrap.md`)

## Pre-flight

- [ ] Deploy lands successfully
- [ ] Service `/health` returns 200
- [ ] Reload MCP client
- [ ] Tool `create_conversion_value_rule_set` schema atualizado (sem `conversion_action_categories`, sem `NO_CONDITION`)

Production revision: `<fill-in>`.

## Test T1 — Schema rejection: NO_CONDITION

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
- [ ] **Schema validation rejection** (não chega ao tool body, nem pre-flight, nem Google API)
- [ ] Error message menciona `condition_type` ou enum constraint
- [ ] Sprint 3b.19B silent-acceptance via Google API runtime substituído por explicit schema rejection

**Result:** ⬜ pending

## Test T2 — Schema rejection: conversion_action_categories field

```
create_conversion_value_rule_set(
  customer_id="1163862076",
  attachment_type="CUSTOMER",
  conversion_action_categories=["PURCHASE"],
  rules=[{
    "action": {"operation": "ADD", "value": 10.0},
    "condition_type": "DEVICE",
    "device_condition": {"device_types": ["MOBILE"]}
  }]
)
```

Expected:
- [ ] Schema validation rejection via `additionalProperties: false` — field não existe no schema v0
- [ ] Error message menciona `conversion_action_categories` not allowed

**Result:** ⬜ pending

## Test T3 — Happy path preserved (CUSTOMER + DEVICE/DESKTOP, since CUSTOMER+MOBILE may conflict with T1 do 3b.19B smoke)

```
create_conversion_value_rule_set(
  customer_id="1163862076",
  attachment_type="CAMPAIGN",
  campaign_id="22782946457",
  rules=[{
    "action": {"operation": "ADD", "value": 5.0},
    "condition_type": "DEVICE",
    "device_condition": {"device_types": ["DESKTOP"]}
  }]
)
```

Expected:
- [ ] dry_run com confirmation_token
- [ ] preview NÃO inclui `has_category_filter` field (removed in Sprint 3b.22)
- [ ] params_summary NÃO inclui `with_category_filter` ou `category_filter_count`
- [ ] Apply → applied_count 2, F13 returns 2 resource_names

Note: usar CAMPAIGN attach (22782946457 já tem RuleSet do 3b.19B smoke, mas Google permite múltiplos CAMPAIGN-level com scope diferente; se conflict, usar `22804468687` mas esse também já tem). Se ambas falharem por conflict, criar test campaign novo via Google Ads UI primeiro, OU pular T3 (happy path já validado em 3b.19B T1/T4/T6).

**Result:** ⬜ pending

## Test T4 — Updated tool description visible (F26 doc)

```
list_tools (or examine schema)
```

Verify the tool description PT-BR menciona:
- [ ] "Google limita 1 RuleSet CUSTOMER-level por conta — sprint 3b.19B F26"
- [ ] "v0 NAO suporta AUDIENCE/ITINERARY conditions nem categorias filter"

**Result:** ⬜ pending

## Findings

Document any new findings here. Se T1-T4 all PASS clean, restart streak (Sprint 3b.21 + 3b.19B + 3b.22 series).
