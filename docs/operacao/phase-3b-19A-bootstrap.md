# Phase 3b.19A — manual smoke runbook (`create_conversion_action`)

**Purpose:** Verify Sprint 3b.19A `create_conversion_action` (terceiro create-pattern do MCP). Resolve gap UX-1 (Sprint 3b.7) ao habilitar gestor a configurar tracking via MCP.

**Operator:** wellinton.ribeiro@v4company.com
**Account:** `1163862076` Rayane Ribeiro - Nutry (sandbox preferida)

**Spec:** `docs/superpowers/specs/2026-05-13-sprint-3b.19A-design.md`
**Plan:** `docs/superpowers/plans/2026-05-13-sprint-3b.19A-plan.md`

## Pre-flight

- [ ] Deploy lands successfully
- [ ] Service `/health` returns 200
- [ ] Reload MCP client (Claude Code session)
- [ ] Tool `create_conversion_action` visível em MCP client tool list
- [ ] Tool count via `get_my_audit_log` ou local introspection = 45

Production revision: `v4-ads-mcp-00155-v5p`.

## Test T1 — Single WEBPAGE LEAD (most common V4 shape, F13 verification)

```
create_conversion_action(
  customer_id="1163862076",
  conversion_actions=[{
    "name": "[TEST 3b.19A] Lead WhatsApp Site",
    "category": "LEAD",
    "type": "WEBPAGE"
  }]
)
```

Expected:
- [ ] `status: "dry_run"` com `confirmation_token`
- [ ] `actions_preview[0]` tem name + category=LEAD + type=WEBPAGE + counting_type=ONE_PER_CLICK + has_value_settings=False
- [ ] `blast_summary` mencionando "Criar 1 conversion_action(s): categorias {'LEAD': 1}, tipos {'WEBPAGE': 1}."
- [ ] Apply via `apply_change` → `status: "applied"`, `applied_count: 1`, `google_request_id` presente
- [ ] **F13 critical:** `resource_names` returns `["customers/1163862076/conversionActions/<new_id>"]` (top-level ConversionAction format) — TERCEIRA validação F13 in-prod (1ª create_rsa via ad_group_ad_operation, 2ª update_rsa via ad_operation, 3ª agora via conversion_action_operation)
- [ ] GAQL verify: `SELECT conversion_action.id, conversion_action.name, conversion_action.category, conversion_action.type, conversion_action.status FROM conversion_action WHERE conversion_action.name = '[TEST 3b.19A] Lead WhatsApp Site'` retorna 1 row com status=ENABLED, type=WEBPAGE, category=LEAD

## Test T2 — Schema rejection (missing required `category`)

```
create_conversion_action(
  customer_id="1163862076",
  conversion_actions=[{
    "name": "[TEST 3b.19A] Sem Category",
    "type": "WEBPAGE"
  }]
)
```

Expected:
- [ ] Schema validation rejection (BEFORE tool runs) — JSON Schema reject menciona `category` required

## Test T3 — Pre-flight duplicate name (re-tentar T1 name)

```
create_conversion_action(
  customer_id="1163862076",
  conversion_actions=[{
    "name": "[TEST 3b.19A] Lead WhatsApp Site",
    "category": "LEAD",
    "type": "WEBPAGE"
  }]
)
```

Expected:
- [ ] Response `status: "error"` com error: `"ConversionAction '[TEST 3b.19A] Lead WhatsApp Site' ja existe na conta..."`
- [ ] Sem token

## Test T4 — Batch 2 with value_settings (e-commerce + offline shape)

```
create_conversion_action(
  customer_id="1163862076",
  conversion_actions=[
    {
      "name": "[TEST 3b.19A] Compra Webhook PURCHASE",
      "category": "PURCHASE",
      "type": "WEBPAGE",
      "counting_type": "MANY_PER_CLICK",
      "value_settings": {
        "default_value_brl": 50.00,
        "always_use_default_value": true
      }
    },
    {
      "name": "[TEST 3b.19A] Lead CRM Empsis",
      "category": "IMPORTED_LEAD",
      "type": "UPLOAD_CLICKS"
    }
  ]
)
```

Expected:
- [ ] `blast_summary`: "Criar 2 conversion_action(s): categorias {'PURCHASE': 1, 'IMPORTED_LEAD': 1}, tipos {'WEBPAGE': 1, 'UPLOAD_CLICKS': 1}."
- [ ] Apply → applied_count 2, 2 resource_names
- [ ] GAQL verify ad1 (`'[TEST 3b.19A] Compra Webhook PURCHASE'`): conversion_action.value_settings.default_value = 50.0, default_currency_code = "BRL", always_use_default_value = true, counting_type = MANY_PER_CLICK
- [ ] GAQL verify ad2: type=UPLOAD_CLICKS, category=IMPORTED_LEAD

## Test T5 — UPLOAD_CALLS PHONE_CALL_LEAD (call import shape)

```
create_conversion_action(
  customer_id="1163862076",
  conversion_actions=[{
    "name": "[TEST 3b.19A] Call Lead Offline",
    "category": "PHONE_CALL_LEAD",
    "type": "UPLOAD_CALLS"
  }]
)
```

Expected:
- [ ] dry_run com token
- [ ] `actions_preview[0].type == "UPLOAD_CALLS"`, `category == "PHONE_CALL_LEAD"`
- [ ] Apply → applied
- [ ] GAQL verify: type=UPLOAD_CALLS persisted

## Cleanup

5 ConversionActions criadas em Nutry sandbox. ConversionAction não pode ser deleted via Google Ads UI (apenas REMOVED status). Aceitar como sandbox junk — zero impact (ad_groups parents continuam PAUSED desde Sprint 3b.16, então mesmo se tracking ativasse, sem traffic). Spawn-task: implement `remove_conversion_action` se demanda surgir.

## Sign-off final

- [ ] T1 happy path: F13 resource_name retornado + GAQL confirma status=ENABLED + correct type/category
- [ ] T2 schema rejection: missing required field rejected pre-runtime
- [ ] T3 pre-flight: duplicate name rejected com PT-BR
- [ ] T4 batch: 2 actions diferentes (PURCHASE com value_settings + IMPORTED_LEAD UPLOAD_CLICKS), ambos applied + GAQL verifica fields
- [ ] T5 UPLOAD_CALLS: applied + GAQL confirma type
- [ ] Production revision verificada
- [ ] CLAUDE.md atualizado: Sprint 3b.19A shipped, tool count 44 → 45

**Date completed:** ____

## Findings (post-execution)

(Inline — surfaceados durante smoke)
