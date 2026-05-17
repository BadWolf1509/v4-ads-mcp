# Phase 3b.22 — manual smoke runbook (F25+F27 schema cleanup)

**Purpose:** Validar Sprint 3b.22 schema cleanup em `create_conversion_value_rule_set` — closes Sprint 3b.19B findings F25 + F27. Schema agora rejeita os 2 enum values dead-code antes que cheguem ao Google API.

**Operator:** wellinton.ribeiro@v4company.com
**Account:** `1163862076` Nutry (sandbox; já tem 3 RuleSets criados em Sprint 3b.19B smoke 17/05)

**Spec:** Sprint 3b.19B findings F25 + F27 + F26 (em `docs/operacao/phase-3b-19B-bootstrap.md`)

## Pre-flight

- [x] Deploy lands successfully (`gh run watch 26006189396` shows green Deploy)
- [x] Service `/health` returns 200
- [x] Reload MCP client (auto-refresh)
- [x] Tool `create_conversion_value_rule_set` schema atualizado em prod

Production revision: `v4-ads-mcp-00170-5k5`.

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
- [x] **Schema validation rejection** (não chega ao tool body, nem pre-flight, nem Google API)
- [x] Error message menciona `condition_type` ou enum constraint
- [x] Sprint 3b.19B silent-acceptance via Google API runtime substituído por explicit schema rejection

**Result:** ✅ PASS. Server retornou `"Input validation error: 'NO_CONDITION' is not one of ['DEVICE', 'GEO_LOCATION']"`. Schema-time rejection via jsonschema.validate em server.py:55, antes do tool body. Mensagem explicita o que é válido — UX claro. F25 fix verified end-to-end.

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
- [x] Schema validation rejection via `additionalProperties: false` — field não existe no schema v0
- [x] Error message menciona `conversion_action_categories` not allowed

**Result:** ✅ PASS. Server retornou `"Input validation error: Additional properties are not allowed ('conversion_action_categories' was unexpected)"`. F27 fix verified end-to-end — `additionalProperties: false` catches the dead-code field schema-time. Cleaner UX que o Google API runtime error que vinha pre-cleanup.

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
- [x] dry_run com confirmation_token
- [x] preview NÃO inclui `has_category_filter` field (removed in Sprint 3b.22)
- [x] params_summary NÃO inclui `with_category_filter` ou `category_filter_count`
- [ ] Apply → applied_count 2, F13 returns 2 resource_names (blocked by F26 — both PAUSED campaigns Nutry já têm RuleSets do 3b.19B smoke)

**Result:** ✅ PASS (split). Dry_run com token `L09JGAYA`, preview clean:
```
{"attachment_type": "CAMPAIGN", "rule_count": 1, "operations": ["ADD"], "condition_types": ["DEVICE"]}
```
**`has_category_filter` field REMOVIDO do preview** ✓. `blast_summary` correto. Apply rejeitado por F26 ("conflicted with existing data") — Nutry sandbox tem apenas 2 PAUSED campaigns + ambas já com RuleSet do 3b.19B smoke. F26 constraint validado meta-vez: **a doc note adicionada em 3b.22 description está accurate**. Builder pattern já validado end-to-end em 3b.19B smoke T1/T4/T6 (3 RuleSets ENABLED via mesma builder code que não foi tocada em 3b.22 — apenas dead-code branches removidas).

## Test T4 — Updated tool description (F26 doc)

Verified via MCP schema reload:
- [x] Description PT-BR menciona "Google limita 1 RuleSet CUSTOMER-level por conta — sprint 3b.19B F26"
- [x] Description menciona "v0 NAO suporta AUDIENCE/ITINERARY conditions nem categorias filter (Google API restringe filter a STORE_VISIT/STORE_SALE — out of scope v0)"

**Result:** ✅ PASS. F26 + F27 documentados no description PT-BR; gestor lê context antes de tentar combos inválidos.

## Findings

**ZERO new findings.** Sprint 3b.22 = **clean smoke first try**. Restart streak depois de 3b.21 + 3b.19B (sucessivos com findings).

T3 apply blocked by F26 NÃO é finding novo — é **validação meta** da F26 doc note adicionada em 3b.22 (constraint Google documentada, gestor encontra error claro, comportamento esperado).

## Real biz value

- **F25 + F27 schema design gaps closed:** schema agora rejeita `NO_CONDITION` + `conversion_action_categories` schema-time em vez de Google API runtime. UX cleaner (mensagem PT-BR clara) + zero possibility de gestor passar combos inválidos.
- **F26 doc note in description:** gestor recebe context antes de tentar criar 2 RuleSets CUSTOMER em 1 conta.
- **Bug class 11ª variante finalizada** (design-gap-via-SDK-ambiguity family).
- **Sprint 3b.19A.1 convention reafirmada** — per-value empirical probe pegou F25+F27 antes de gestor encontrar em uso real.
- **Streak restart:** Sprint 3b.22 limpo após 2 sprints (3b.19B + 3b.21) com findings reais. Próximas stabilization sprints (3b.23 candidate F22 limit param) devem continuar streak.

Sprint 3b.22 = **shipped + signed-off em 2 hours total wall-clock** (incluindo brainstorm escolhe-pular + code + tests + smoke runbook + deploy + smoke validation + commit). Net source change: ~-30 LOC dead code removed.
