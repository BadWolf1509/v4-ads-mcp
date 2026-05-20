# Phase 3b.27 — manual smoke runbook (`update_conversion_action` + B1/F43 fix)

**Purpose:** Validar Sprint 3b.27 combo — (A) nova tool MCP `update_conversion_action` (50º tool, primeiro update em conversion tracking entity); (B) fix B1/F43 em `update_keyword_status` (pre-flight async que separa positive vs negative criterion_ids e mata silent-acceptance). Pre-req pra Opção C SIMPLIFICADA em conta MO-JP em 23/05 (sex) — gestor precisa rebaixar Store visits action pra non-biddable via MCP.

**Operator:** wellinton.ribeiro@v4company.com
**Account:** `1163862076` Nutry (sandbox)

**Spec:** `docs/superpowers/specs/2026-05-19-sprint-3b-27-update-conversion-action-plus-b1-fix-design.md`
**Plan:** `docs/superpowers/plans/2026-05-19-sprint-3b-27-update-conversion-action-plus-b1-fix.md`

## Pre-flight

- [ ] Deploy Phase A lands successfully (`update_conversion_action` em produção)
- [ ] Deploy Phase B lands successfully (`update_keyword_status` F43 fix em produção)
- [ ] Service `/health` returns 200 (ambas revisões)
- [ ] Tool `update_conversion_action` visível em MCP tool list (count 49 → 50)
- [ ] Tool `update_keyword_status` ainda visível (fix em existing tool, count não muda)
- [ ] Pre-push gate `python scripts/check_pre_push.py` 5/5 PASS
- [ ] Pre-push full `python scripts/check_pre_push_full.py` 6/6 PASS (validar mock no namespace correto da tool)

Production revisions: `v4-ads-mcp-XXXXX-xxx` (Phase A, post SHA `6807b27`) → `v4-ads-mcp-XXXXX-xxx` (Phase B, post SHA `9b51b1a`) → [add fix iterations as they happen]

## Smoke results

Preencher conforme execução. Marcar resultado final no fim do arquivo.

| # | Test | Result | Notes |
|---|---|---|---|
| T0a | GAQL setup — listar 3-5 ConversionActions ENABLED em Nutry | ⬜ pending | |
| T0b | GAQL setup — listar ad_group_criterion misturados positive + negative | ⬜ pending | |
| T1 | `update_conversion_action` dry_run rename 2 actions (batch > 1 força CONFIRM) | ⬜ pending | |
| T2 | apply T1 → GAQL verify `conversion_action.name` mudou | ⬜ pending | |
| T3 | pre-flight reject — conversion_action_id `9999999999` não existe (Layer 3) | ⬜ pending | |
| T4 | Layer 2 reject — item sem field mutável (só `conversion_action_id`) | ⬜ pending | |
| T5 | Layer 2 reject — duplicate `conversion_action_id` no batch | ⬜ pending | |
| T6 | batch dry_run — 3 actions com fields diferentes (rename + primary_for_goal=false + include_in_conversions_metric=false) | ⬜ pending | |
| T7 | **CRITICAL** apply T6 + verify GAQL — Store visits action vira non-biddable (caso real MO 23/05) | ⬜ pending | |
| T8 | schema regression — `maxItems` 51 items rejected (boundary 50) | ⬜ pending | |
| T9 | `update_keyword_status` regression — só positives (5 keywords PAUSED) ainda funciona | ⬜ pending | |
| T10 | F43 trigger — 100% negativos (1 negative_id) → hard reject | ⬜ pending | |
| T11 | F43 trigger — mistura 3 positives + 2 negatives → split com listas separadas | ⬜ pending | |
| T12 | missing IDs — `criterion_id=999` inexistente → `missing_ids` curto-circuita | ⬜ pending | |

**Effective result:** N/12 PASS

### F-findings emerged

[Empty placeholder — fill during smoke. Template: `**F## (SEV)** — <symptom>. Fix: <plan>. Family: <bug class>.`]

### Sign-off

- [ ] Pre-push gate 5/5 PASS (Phase A + Phase B)
- [ ] Pre-push full 6/6 PASS
- [ ] mcp-tool-quality-reviewer subagent PASS
- [ ] Production /health 200 (revision final)
- [ ] **12/12 PASS** após [N] fix iterations
- [ ] CLAUDE.md sprint row added (Sprint 3b.27 shipped, count 49 → 50)
- [ ] findings-catalog.md F43 row movida `open` → `Fixed Sprint 3b.27` + summary Open 2→1
- [ ] Tool count 49 → 50 confirmed in production
- [ ] **Wellington executa Opção C SIMPLIFICADA MO 23/05 via MCP** (validação produção real, fora-de-sandbox)

---

## Pre-smoke setup

### T0a — Identificar 3-5 ConversionActions ENABLED em Nutry

GAQL pré-smoke (encontrar candidatos pra T1/T2/T6/T7):

```
SELECT
  conversion_action.id,
  conversion_action.name,
  conversion_action.type,
  conversion_action.category,
  conversion_action.status,
  conversion_action.primary_for_goal,
  conversion_action.include_in_conversions_metric
FROM conversion_action
WHERE conversion_action.status = 'ENABLED'
LIMIT 10
```

Selecionar/registrar:
- **CA_RENAME_1** (T1/T2): action com nome simples, vai mudar `name`
- **CA_RENAME_2** (T1): segunda action pra forçar batch > 1 (CONFIRM)
- **CA_BATCH_NAME** (T6): action pra rename no batch misto
- **CA_BATCH_PRIMARY_FALSE** (T6): action com `primary_for_goal=true` → vamos virar false
- **CA_BATCH_METRIC_FALSE** (T6/T7 STORE_VISIT-like): action com `include_in_conversions_metric=true` → vamos virar false

**Backup plan:** se Nutry < 3 actions ENABLED, criar via `create_conversion_action`:

```
create_conversion_action(
  customer_id="1163862076",
  conversion_actions=[
    {"name": "[3b.27-smoke] Pre-T1", "category": "DEFAULT", "type": "WEBPAGE", "default_value": 1.0},
    {"name": "[3b.27-smoke] Pre-T6 disable-primary", "category": "DEFAULT", "type": "WEBPAGE", "default_value": 1.0},
    {"name": "[3b.27-smoke] Pre-T6 disable-metric", "category": "DEFAULT", "type": "WEBPAGE", "default_value": 1.0}
  ]
)
```

Anotar IDs pra reuse.

### T0b — Identificar ad_group_criterion misturados positive + negative em Nutry

GAQL pré-smoke (encontrar pelo menos 5 positives + 5 negatives — necessários pra T9/T10/T11):

```
SELECT
  ad_group.id,
  ad_group_criterion.criterion_id,
  ad_group_criterion.keyword.text,
  ad_group_criterion.negative,
  ad_group_criterion.status,
  ad_group_criterion.type
FROM ad_group_criterion
WHERE ad_group_criterion.type = 'KEYWORD'
  AND ad_group_criterion.status IN ('ENABLED', 'PAUSED')
LIMIT 50
```

Separar e registrar:
- **POS_5[]**: 5 criterion_id com `negative=false` (T9 regression)
- **NEG_1**: 1 criterion_id com `negative=true` (T10 hard reject 100% negative)
- **POS_3[] + NEG_2[]**: 3 positives + 2 negatives diferentes dos anteriores (T11 mistura)
- **POS_1**: 1 positive existente + `999` fake (T12 missing curto-circuita)

**Backup plan:** se Nutry não tem keyword negativas suficientes, criar via `add_negative_keywords` antes do smoke:

```
add_negative_keywords(
  customer_id="1163862076",
  ad_group_id="<existing_ag>",
  keywords=[
    {"text": "negativa smoke 1", "match_type": "BROAD"},
    {"text": "negativa smoke 2", "match_type": "EXACT"},
    {"text": "negativa smoke 3", "match_type": "PHRASE"}
  ]
)
```

Anotar criterion_ids retornados.

---

## Test T1 — `update_conversion_action` dry_run rename 2 actions (CONFIRM via batch>1)

```
update_conversion_action(
  customer_id="1163862076",
  updates=[
    {"conversion_action_id": "<CA_RENAME_1>", "name": "[3b.27 smoke T1] renamed-1"},
    {"conversion_action_id": "<CA_RENAME_2>", "name": "[3b.27 smoke T1] renamed-2"}
  ]
)
```

Expected:
- [ ] response `status="dry_run"` com `confirmation_token` + `expires_in_minutes=10`
- [ ] `blast_summary` = "Atualizar 2 ConversionAction(s)."
- [ ] `changes` array com 2 entries: `[{conversion_action_id, fields_updated=["name"]}]`
- [ ] sem `applied_count` (não aplicou ainda)
- [ ] rate_counter +1 (GAQL preflight)
- [ ] audit_log com 1 entry preflight, ZERO de mutate

**Result:** ⬜ pending

## Test T2 — apply T1 + verify GAQL

```
apply_change(confirmation_token="<token from T1>")
```

Expected:
- [ ] response `status="applied"`, `applied_count=2`, `google_request_id` presente
- [ ] `changes` array reflete o que foi aplicado
- [ ] resource_names usa pattern `customers/1163862076/conversionActions/{id}` (A5 lesson)
- [ ] GAQL verify:
  ```
  SELECT conversion_action.id, conversion_action.name
  FROM conversion_action
  WHERE conversion_action.id IN (<CA_RENAME_1>, <CA_RENAME_2>)
  ```
  retorna `name="[3b.27 smoke T1] renamed-1"` + `name="[3b.27 smoke T1] renamed-2"`
- [ ] rate_counter +2 (mutate batch=2)
- [ ] audit_log com entry de mutate + google_request_id

**Result:** ⬜ pending

## Test T3 — Layer 3 pre-flight reject: conversion_action_id não existe

```
update_conversion_action(
  customer_id="1163862076",
  updates=[
    {"conversion_action_id": "9999999999", "name": "should-reject"}
  ]
)
```

Expected:
- [ ] response `status="error"`, `operation="update_conversion_action"`
- [ ] error contém `"não encontrad"` ou `"não existe"` + `9999999999`
- [ ] `missing_ids` no payload com `9999999999` listado
- [ ] sem `confirmation_token`
- [ ] sem chamada a `run_mutation` (audit_log só com preflight GAQL)
- [ ] rate_counter +1 (só GAQL), NÃO +N de mutate

**Result:** ⬜ pending

## Test T4 — Layer 2 reject: item sem field mutável

```
update_conversion_action(
  customer_id="1163862076",
  updates=[
    {"conversion_action_id": "<CA_RENAME_1>"}
  ]
)
```

Expected:
- [ ] response `status="error"`
- [ ] error PT-BR contém `"só tem conversion_action_id"` + `"name, primary_for_goal, include_in_conversions_metric"` + `"Inclua ao menos 1 field"`
- [ ] sem `confirmation_token`
- [ ] sem GAQL preflight (Layer 2 antes de Layer 3, abort early)
- [ ] rate_counter incrementa 0

**Result:** ⬜ pending

## Test T5 — Layer 2 reject: duplicate conversion_action_id

```
update_conversion_action(
  customer_id="1163862076",
  updates=[
    {"conversion_action_id": "<CA_RENAME_1>", "name": "first"},
    {"conversion_action_id": "<CA_RENAME_1>", "primary_for_goal": false}
  ]
)
```

Expected:
- [ ] response `status="error"`
- [ ] error PT-BR contém `"conversion_action_ids duplicados no batch"` + lista com `<CA_RENAME_1>`
- [ ] sem `confirmation_token`
- [ ] rate_counter incrementa 0

**Result:** ⬜ pending

## Test T6 — batch dry_run: 3 actions com fields diferentes (field_mask dinâmico)

```
update_conversion_action(
  customer_id="1163862076",
  updates=[
    {"conversion_action_id": "<CA_BATCH_NAME>", "name": "[3b.27 smoke T6] only-rename"},
    {"conversion_action_id": "<CA_BATCH_PRIMARY_FALSE>", "primary_for_goal": false},
    {"conversion_action_id": "<CA_BATCH_METRIC_FALSE>", "name": "[3b.27 smoke T6] rename+disable", "include_in_conversions_metric": false}
  ]
)
```

Expected:
- [ ] response `status="dry_run"` (CONFIRM via `primary_for_goal=False` + `include_in_conversions_metric=False` = unsafe disable)
- [ ] `confirmation_token` presente
- [ ] `changes` array com 3 entries, cada `fields_updated` reflete só os fields enviados:
  - entry 1: `fields_updated=["name"]`
  - entry 2: `fields_updated=["primary_for_goal"]`
  - entry 3: `fields_updated=["name", "include_in_conversions_metric"]`
- [ ] `blast_summary` menciona 3 actions

**Result:** ⬜ pending

## Test T7 — CRITICAL: apply T6 + verify GAQL (Store visits non-biddable, caso MO 23/05)

```
apply_change(confirmation_token="<token from T6>")
```

Expected:
- [ ] response `status="applied"`, `applied_count=3`
- [ ] GAQL verify field_mask dinâmico funcionou (cada action mudou só os fields enviados):
  ```
  SELECT
    conversion_action.id,
    conversion_action.name,
    conversion_action.primary_for_goal,
    conversion_action.include_in_conversions_metric
  FROM conversion_action
  WHERE conversion_action.id IN (<CA_BATCH_NAME>, <CA_BATCH_PRIMARY_FALSE>, <CA_BATCH_METRIC_FALSE>)
  ```
  Bit-a-bit:
  - `<CA_BATCH_NAME>`: `name` mudou, `primary_for_goal` + `include_in_conversions_metric` intactos
  - `<CA_BATCH_PRIMARY_FALSE>`: `primary_for_goal=false`, `name` intacto
  - `<CA_BATCH_METRIC_FALSE>`: `name` mudou + `include_in_conversions_metric=false`, `primary_for_goal` intacto
- [ ] **Critical:** action com `primary_for_goal=false` agora não-bidável (campo dogfood UX-B validado end-to-end)
- [ ] **CRITICAL pra MO 23/05:** Wellington executa esse mesmo padrão na conta MO-JP em produção sexta
- [ ] R1 risk validado empiricamente: SDK descriptor permite `primary_for_goal=false` via update (não só create)

**Result:** ⬜ pending

## Test T8 — Schema regression: maxItems 51 rejected (boundary 50)

```
update_conversion_action(
  customer_id="1163862076",
  updates=[ {"conversion_action_id": str(i), "name": f"x{i}"} for i in range(51) ]
)
```

Expected:
- [ ] JSONSchema validation error pre-Google call: `"is too long"` ou `"maxItems"`
- [ ] sem GAQL preflight (Layer 1 antes)
- [ ] rate_counter incrementa 0

**Result:** ⬜ pending

---

## Test T9 — `update_keyword_status` regression: só positives (5 PAUSED) ainda funciona

```
update_keyword_status(
  customer_id="1163862076",
  keywords=[
    {"ad_group_id": "<ag>", "criterion_id": "<POS_5[0]>"},
    {"ad_group_id": "<ag>", "criterion_id": "<POS_5[1]>"},
    {"ad_group_id": "<ag>", "criterion_id": "<POS_5[2]>"},
    {"ad_group_id": "<ag>", "criterion_id": "<POS_5[3]>"},
    {"ad_group_id": "<ag>", "criterion_id": "<POS_5[4]>"}
  ],
  new_status="PAUSED"
)
```

Expected:
- [ ] response `status="dry_run"` (batch > 1, CONFIRM)
- [ ] **Pre-flight passa silenciosamente** (todos positives) — `validate_keyword_criterion_types` retorna `None`
- [ ] `confirmation_token` presente
- [ ] apply → applied_count=5, GAQL confirma status PAUSED nas 5 keywords
- [ ] Regression: F43 fix não quebrou caminho happy

**Result:** ⬜ pending

## Test T10 — F43 trigger: 100% negativos (1 negative_id) → hard reject

```
update_keyword_status(
  customer_id="1163862076",
  keywords=[
    {"ad_group_id": "<ag>", "criterion_id": "<NEG_1>"}
  ],
  new_status="PAUSED"
)
```

Expected:
- [ ] response `status="error"`, `operation="update_keyword_status"`
- [ ] error PT-BR contém `"1/1 criterion_ids são ad_group_criterion com negative=true"` + `"Google API rejeita updates em negative criteria"` + `"Pra desnegativar uma keyword, use Google Ads UI"`
- [ ] `negative_ids_blocked` com `<NEG_1>` listado
- [ ] `positive_ids_safe` vazio `[]`
- [ ] **NÃO chega ao `run_mutation`** — audit_log só com GAQL preflight
- [ ] rate_counter +1 (só GAQL preflight), NÃO +1 de mutate
- [ ] sem `confirmation_token` (abort pré-classify)

**Result:** ⬜ pending

## Test T11 — F43 trigger: mistura 3 positives + 2 negatives → split com listas

```
update_keyword_status(
  customer_id="1163862076",
  keywords=[
    {"ad_group_id": "<ag>", "criterion_id": "<POS_3[0]>"},
    {"ad_group_id": "<ag>", "criterion_id": "<POS_3[1]>"},
    {"ad_group_id": "<ag>", "criterion_id": "<NEG_2[0]>"},
    {"ad_group_id": "<ag>", "criterion_id": "<POS_3[2]>"},
    {"ad_group_id": "<ag>", "criterion_id": "<NEG_2[1]>"}
  ],
  new_status="PAUSED"
)
```

Expected:
- [ ] response `status="error"`
- [ ] error PT-BR contém `"2/5 criterion_ids são ad_group_criterion com negative=true"`
- [ ] `negative_ids_blocked` com 2 entries (NEG_2[0] + NEG_2[1])
- [ ] `positive_ids_safe` com 3 entries (POS_3[0..2])
- [ ] `to_retry_with` mensagem contém `"update_keyword_status(customer_id='1163862076', keywords=positive_ids_safe, new_status="` (call hint pro re-run)
- [ ] audit_log com 1 entry preflight, ZERO de mutate
- [ ] rate_counter +1 (só GAQL)

**Validação manual:** Wellington faz re-call com `keywords=positive_ids_safe` (3 IDs) → deve passar fluxo normal e aplicar PAUSED em 3 positives. Sanity check do `to_retry_with` workflow.

**Result:** ⬜ pending

## Test T12 — missing IDs: criterion_id 999 inexistente → missing_ids curto-circuita

```
update_keyword_status(
  customer_id="1163862076",
  keywords=[
    {"ad_group_id": "<ag>", "criterion_id": "<POS_1>"},
    {"ad_group_id": "<ag>", "criterion_id": "999"}
  ],
  new_status="PAUSED"
)
```

Expected:
- [ ] response `status="error"`
- [ ] error PT-BR contém `"criterion_ids não encontrados em customer_id=1163862076"` + `[999]` ou `["999"]`
- [ ] `missing_ids` no payload com `999` listado
- [ ] **NÃO** retorna `negative_ids_blocked` (curto-circuita antes do split logic)
- [ ] sem `confirmation_token`
- [ ] audit_log com 1 entry preflight GAQL
- [ ] rate_counter +1 (só GAQL)

**Result:** ⬜ pending

---

## Cleanup post-smoke

- ConversionActions renomeadas em T2 + T7 podem ficar com nomes "[3b.27 smoke T1/T6]" — limpar via Google Ads UI ou aguardar Sprint 3b.28 (`remove_*` bundle)
- Keywords PAUSED em T9 — reverter pra ENABLED via `update_keyword_status` se Nutry vai voltar a ter tráfego (unlikely, mas trivial)
- Action com `primary_for_goal=false` em T7: já documentada como teste; gestor pode reverter via mesma tool (`update_conversion_action` com `primary_for_goal=true`)
- Total entities afetadas: ~5 ConversionActions + ~10 ad_group_criterion (PAUSED). Zero serving impact (Nutry sandbox)

---

## Per-value empirical probe (Sprint 3b.19A.1 convention)

**N/A** — `update_conversion_action` V0 não tem enum whitelist:
- `name`: string livre (1-100 chars)
- `primary_for_goal`: boolean
- `include_in_conversions_metric`: boolean

Sem enum → sem probe per-value necessário. Convention Sprint 3b.19A.1 não aplica.

**Fix em `update_keyword_status`** também não introduz nova enum whitelist (apenas adiciona pre-flight async). Schema `new_status="ENABLED" | "PAUSED"` continua igual (F11 regression coverage existente em `test_status_tools_schema_restrict`).

---

## V4 invariants validation

**N/A pra Component A (`update_conversion_action`)** — campos mutáveis V0 (`name`, `primary_for_goal`, `include_in_conversions_metric`) são geográfica/linguisticamente neutros. Não há `country_code`/`language_code`/`currency_code`/`timezone` envolvidos na proto `ConversionAction` desses 3 fields.

| Invariant | Aplicável | Como smoke verifica |
|---|---|---|
| country_code=BR | N/A | Tool não toca em geo |
| language_code=pt-BR | N/A | Tool não toca em language |
| currency_code=BRL | N/A | Tool não toca em monetary fields V0 (`default_value`/`value_settings` ficam pra futuro) |
| timezone=-03:00 | N/A | Tool não toca em timestamp |
| LGPD consent | N/A | Tool não recebe PII (não é offline conversion / customer match) |

**Component B (`update_keyword_status` fix)** também não envolve V4 invariants — apenas pre-flight de tipo de critério (positive vs negative).

**Quando V0 ganhar fields adicionais (`value_settings.default_value`, `default_currency_code`)** em sprint futuro, runbook desse incremento DEVE adicionar invariant=BRL hardcoded + 1 smoke explícito.
