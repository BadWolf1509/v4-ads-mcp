# Phase 3b.26 — manual smoke runbook (`import_offline_conversions`)

**Purpose:** Validar Sprint 3b.26 — primeiro tool V4 que NÃO usa GoogleAdsService.mutate (usa ConversionUploadService). Foundation pra V4 lead-gen attribution loop (Smart Bidding signals from WhatsApp/CRM leads).

**Operator:** wellinton.ribeiro@v4company.com
**Account:** `1163862076` Nutry (sandbox)

**Spec:** `docs/superpowers/specs/2026-05-18-sprint-3b-26-import-offline-conversions-design.md`
**Plan:** `docs/superpowers/plans/2026-05-18-sprint-3b-26-import-offline-conversions.md`

## Pre-flight

- [ ] Deploy lands successfully
- [ ] Service `/health` returns 200
- [ ] Tool `import_offline_conversions` visível em MCP tool list (count 48 → 49)
- [ ] F28 reproducer: gestor pode precisar restart Claude Code session pro schema cache propagar

Production revision: `<PREENCHER pós-deploy>`.

## Pre-smoke setup: capture real gclids + create UPLOAD_CLICKS ConversionAction

### Step 1: Identify or create UPLOAD_CLICKS ConversionAction

GAQL pre-smoke (find existing UPLOAD_CLICKS in Nutry):

```
SELECT
  conversion_action.id,
  conversion_action.name,
  conversion_action.type,
  conversion_action.status
FROM conversion_action
WHERE conversion_action.type = 'UPLOAD_CLICKS'
```

If none exists with status=ENABLED, create one via `create_conversion_action`:

```
create_conversion_action(
  customer_id="1163862076",
  conversion_actions=[{
    "name": "[3b.26-smoke] V4 lead-gen offline",
    "category": "SUBMIT_LEAD_FORM",
    "type": "UPLOAD_CLICKS",
    "default_value": 50.0
  }]
)
```

Note the resulting `conversion_action.id` (e.g., `123456789`) for use in T1, T4-T7.

### Step 2: Capture real gclids from Nutry click_view

GAQL pre-smoke:

```
SELECT
  click_view.gclid,
  segments.date
FROM click_view
WHERE segments.date DURING LAST_30_DAYS
LIMIT 10
```

Save 5-10 gclids for use in T4-T6 (real Google-issued gclids — fake strings rejected by Google).

If `click_view` access limited, alternative: use Google Ads UI > Reports > Predefined Reports > Other > Click ID History.

## Test T1 — Pre-flight: valid UPLOAD_CLICKS ConversionAction

```
import_offline_conversions(
  customer_id="1163862076",
  conversion_action_id="<ID from setup>",
  conversions=[{
    "gclid": "<real_gclid_1>",
    "conversion_date_time": "2026-05-17 14:30:00",
    "conversion_value_brl": 100.0
  }]
)
```

Expected:
- [ ] dry_run com confirmation_token + summary.conversion_count=1, sum_value_brl=100.0

**Result:** ⬜ pending

## Test T2 — Pre-flight: conversion_action_id não existe

```
import_offline_conversions(
  customer_id="1163862076",
  conversion_action_id="999999999",
  conversions=[{...}]
)
```

Expected:
- [ ] status=error, error contém `"não existe em customer_id=1163862076"`

**Result:** ⬜ pending

## Test T3 — Pre-flight: WEBPAGE type ConversionAction (type mismatch)

Encontrar uma WEBPAGE ConversionAction em Nutry e usar o ID em:

```
import_offline_conversions(
  customer_id="1163862076",
  conversion_action_id="<WEBPAGE_ID>",
  conversions=[{...}]
)
```

Expected:
- [ ] status=error, error contém `"type=WEBPAGE"` e `"requer type=UPLOAD_CLICKS"`

**Result:** ⬜ pending

## Test T4 — Happy path: 1 conversion, real gclid

Use T1 setup + real gclid + apply.

Expected:
- [ ] apply status=applied, applied_count=1, failed_count=0, failures=[]
- [ ] GAQL verify (3-24h post-upload): conversion appears in customer.metrics.conversions

**Result:** ⬜ pending

## Test T5 — Happy path: batch 5 real gclids

Expected:
- [ ] dry_run summary.conversion_count=5, sum_value_brl=<total>, gclids_distinct=5
- [ ] apply applied_count=5, failed_count=0

**Result:** ⬜ pending

## Test T6 — Some conversions com order_id

Expected:
- [ ] dry_run summary.order_ids_present=<count>
- [ ] apply applied_count=<count>, failed_count=0

**Result:** ⬜ pending

## Test T7 — Partial failure: 3 valid + 2 fake gclids

```
conversions=[
  {"gclid": "<real_gclid_1>", ...},
  {"gclid": "<real_gclid_2>", ...},
  {"gclid": "Cj0KCQjwTEST-FAKE-001", ...},
  {"gclid": "<real_gclid_3>", ...},
  {"gclid": "Cj0KCQjwTEST-FAKE-002", ...}
]
```

Expected:
- [ ] apply applied_count=3, failed_count=2
- [ ] failures[] com row_index=2 e row_index=4, error_code (INVALID_GCLID ou EXPIRED_GCLID)

**Result:** ⬜ pending

## Test T8 — Layer 2: conversion no futuro

```
conversions=[{
  "gclid": "Cj0_test",
  "conversion_date_time": "2099-12-31 23:59:59",
  "conversion_value_brl": 100.0
}]
```

Expected:
- [ ] status=error pre-Google: `"está no futuro"`

**Result:** ⬜ pending

## Test T9 — Layer 2: conversion > 90 dias

Use data ~5 meses atrás.

Expected:
- [ ] status=error pre-Google: contém `"90 dias"`

**Result:** ⬜ pending

## Test T10 — Layer 2: duplicate gclid in batch

```
conversions=[
  {"gclid": "Cj0_same", ...},
  {"gclid": "Cj0_same", ...}
]
```

Expected:
- [ ] status=error: `"gclids duplicados no batch"`

**Result:** ⬜ pending

## Test T11 — Layer 2: duplicate order_id in batch

```
conversions=[
  {"gclid": "Cj0_x", "order_id": "crm-dup", ...},
  {"gclid": "Cj0_y", "order_id": "crm-dup", ...}
]
```

Expected:
- [ ] status=error: `"order_id duplicados no batch"`

**Result:** ⬜ pending

## Test T12 — Schema regression: 101 conversions

Expected:
- [ ] JSONSchema validation error: maxItems exceeded

**Result:** ⬜ pending

## Cleanup post-smoke

Conversões uploadadas afetam ROAS/Smart Bidding em Nutry. Strategy:
- ConversionAction `[3b.26-smoke]` criada em setup pode ser PAUSED via Google Ads UI post-smoke
- Conversões uploadadas: 8-10 total (T4 + T5 + T6 + T7 successes), valores baixos
- Impact em ROAS Nutry: pequeno noise, diluído em métricas reais

## Findings discovered

(Preencher pós-smoke se findings reais surgirem)

| # | Finding | Severity | Documented | Fix |
|---|---|---|---|---|
| F41 | (pending) | — | — | — |

## Sign-off

- [ ] Pre-push gate 5/5 PASS
- [ ] Production /health 200
- [ ] 10+/12 tests PASS (T4-T6 require real gclids — partial passage acceptable)
- [ ] CLAUDE.md sprint row added
- [ ] findings-catalog.md updated se F41+ surgir
- [ ] Tool count 48 → 49 confirmed in production tool list
- [ ] At least 1 real conversion uploaded em Nutry via T4 (proves dispatcher end-to-end)

Signed-off: ⬜ pending
