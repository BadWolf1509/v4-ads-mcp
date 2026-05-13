# Phase 3b.19A — manual smoke runbook (`create_conversion_action`)

**Purpose:** Verify Sprint 3b.19A `create_conversion_action` (terceiro create-pattern do MCP). Resolve gap UX-1 (Sprint 3b.7) ao habilitar gestor a configurar tracking via MCP.

**Operator:** wellinton.ribeiro@v4company.com
**Account:** `1163862076` Rayane Ribeiro - Nutry (sandbox preferida)

**Spec:** `docs/superpowers/specs/2026-05-13-sprint-3b.19A-design.md`
**Plan:** `docs/superpowers/plans/2026-05-13-sprint-3b.19A-plan.md`

## F17 finding (smoke T1 initial run, fixed via Sprint 3b.19A.1)

T1 inicial falhou com `KeyError: 'LEAD'` (production logs `mutation_raw_exception`). Root cause: `LEAD` foi REMOVIDO do `ConversionActionCategoryEnum` em google-ads SDK v20 (era value 6 historicamente; agora há gap entre SIGNUP=5 e DOWNLOAD=7). Sprint design assumia LEAD válido (legacy docs/common knowledge); context7 não surfacou esse gap pois o exemplo de docs cobriu apenas `type_` (WEBPAGE).

**Fix:** removido `LEAD` do `_CATEGORY_ENUM` whitelist em `create_conversion_action.py`. Smoke runbook + tests atualizados pra usar `SUBMIT_LEAD_FORM` (equivalente semântico mais próximo: form submit via WhatsApp/site). Outras alternativas pro V4: `PHONE_CALL_LEAD` (call-driven), `IMPORTED_LEAD` (CRM), `QUALIFIED_LEAD`/`CONVERTED_LEAD` (lifecycle).

Tool count stays at 45. Schema agora tem 17 categorias (não 18).

## Pre-flight

- [x] Deploy lands successfully
- [x] Service `/health` returns 200
- [x] Reload MCP client (Claude Code session)
- [x] Tool `create_conversion_action` visível em MCP client tool list
- [x] Tool count = 45

Production revision: `v4-ads-mcp-00157-ssp` (smoke run revision — post F17 fix; F18 fix shipado em commit seguinte).

## Test T1 — Single WEBPAGE LEAD (most common V4 shape, F13 verification)

```
create_conversion_action(
  customer_id="1163862076",
  conversion_actions=[{
    "name": "[TEST 3b.19A] Lead WhatsApp Site",
    "category": "SUBMIT_LEAD_FORM",
    "type": "WEBPAGE"
  }]
)
```

Expected:
- [x] `status: "dry_run"` com `confirmation_token` → token `DBFSBFPT`
- [x] `actions_preview[0]` tem name + category=SUBMIT_LEAD_FORM + type=WEBPAGE + counting_type=ONE_PER_CLICK + has_value_settings=False
- [x] `blast_summary` mencionando "Criar 1 conversion_action(s): categorias {'SUBMIT_LEAD_FORM': 1}, tipos {'WEBPAGE': 1}."
- [x] Apply via `apply_change` → `status: "applied"`, `applied_count: 1`, `google_request_id: "xBEQS7hLy1JaFxUj7ntI1g"` presente
- [x] **F13 critical:** `resource_names: ["customers/1163862076/conversionActions/7609413999"]` (top-level ConversionAction format) ✅ — **TERCEIRA validação F13 in-prod** (1ª create_rsa via `ad_group_ad_operation` Sprint 3b.16, 2ª update_rsa via `ad_operation` Sprint 3b.18, 3ª agora via `conversion_action_operation`)
- [x] GAQL verify: 1 row com status=ENABLED, type=WEBPAGE, category=SUBMIT_LEAD_FORM, counting_type=ONE_PER_CLICK ✅

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
- [x] Schema validation rejection (BEFORE tool runs) — Error: `"'category' is a required property"` ✅

## Test T3 — Pre-flight duplicate name (re-tentar T1 name)

```
create_conversion_action(
  customer_id="1163862076",
  conversion_actions=[{
    "name": "[TEST 3b.19A] Lead WhatsApp Site",
    "category": "SUBMIT_LEAD_FORM",
    "type": "WEBPAGE"
  }]
)
```

Expected:
- [x] Response `status: "error"` com error: `"ConversionAction '[TEST 3b.19A] Lead WhatsApp Site' ja existe na conta. Use outro nome (nomes sao unicos por customer)."` ✅
- [x] Sem token ✅

## Test T4 — Batch 2 with value_settings (e-commerce + offline shape)

**Originally:** batch [PURCHASE+WEBPAGE com value_settings, IMPORTED_LEAD+UPLOAD_CLICKS]. **Split em smoke** quando T4 inicial falhou com "enum value is not permitted" — isolated em T4-A (ok) + T4-B (ENUM_VALUE_NOT_PERMITTED em IMPORTED_LEAD). F18 finding documentado abaixo.

### T4-A — PURCHASE + WEBPAGE com value_settings (isolated, ✅ APPLIED)

```
create_conversion_action(
  customer_id="1163862076",
  conversion_actions=[{
    "name": "[TEST 3b.19A] Compra Webhook PURCHASE",
    "category": "PURCHASE",
    "type": "WEBPAGE",
    "counting_type": "MANY_PER_CLICK",
    "value_settings": {"default_value_brl": 50, "always_use_default_value": true}
  }]
)
```

Expected:
- [x] `blast_summary`: "Criar 1 conversion_action(s): categorias {'PURCHASE': 1}, tipos {'WEBPAGE': 1}." ✅ (token `EXWML652`)
- [x] Apply → applied_count 1, resource_name `customers/1163862076/conversionActions/7609002182` (`google_request_id: "864C7FjvWeKaMx44eWLwag"`)
- [x] GAQL verify: `value_settings.default_value=50.0`, `default_currency_code="BRL"` (V4 invariant!), `always_use_default_value=true`, `counting_type=MANY_PER_CLICK` ✅

### T4-B — IMPORTED_LEAD + UPLOAD_CLICKS (isolated, ❌ REJECTED → F18)

```
create_conversion_action(
  customer_id="1163862076",
  conversion_actions=[{
    "name": "[TEST 3b.19A] Lead CRM Empsis",
    "category": "IMPORTED_LEAD",
    "type": "UPLOAD_CLICKS"
  }]
)
```

Resultado:
- [x] dry_run OK (token `MQA6XNMJ`)
- [x] Apply → `Google Ads retornou: The enum value is not permitted.` ✅ — F18 isolated
- [x] **Cross-check probes:**
  - `PURCHASE + UPLOAD_CLICKS` → ✅ APPLIED (UPLOAD_CLICKS not the issue)
  - `PHONE_CALL_LEAD + WEBPAGE` → ✅ APPLIED (other lead variants ok)
  - `QUALIFIED_LEAD + WEBPAGE` → ❌ INVALID_VALUE (system-managed)
  - `CONVERTED_LEAD + WEBPAGE` → ❌ INVALID_VALUE (system-managed)
- [x] Conclusion: `IMPORTED_LEAD`, `QUALIFIED_LEAD`, `CONVERTED_LEAD` são todos system-managed (Google's lead lifecycle workflow). Removed do schema em F18 fix.

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
- [x] dry_run com token `VC51DYOK`
- [x] `actions_preview[0].type == "UPLOAD_CALLS"`, `category == "PHONE_CALL_LEAD"` ✅
- [x] Apply → applied (`google_request_id: "aEuk9DGTYF5T8I6acxuuFg"`, resource `7609002908`)
- [x] GAQL verify: `type=UPLOAD_CALLS`, `category=PHONE_CALL_LEAD`, `counting_type=ONE_PER_CLICK`, `value_settings.default_currency_code="BRL"` ✅

## Cleanup

5 ConversionActions criadas em Nutry sandbox. ConversionAction não pode ser deleted via Google Ads UI (apenas REMOVED status). Aceitar como sandbox junk — zero impact (ad_groups parents continuam PAUSED desde Sprint 3b.16, então mesmo se tracking ativasse, sem traffic). Spawn-task: implement `remove_conversion_action` se demanda surgir.

## Sign-off final

- [x] T1 happy path: F13 resource_name retornado (3ª validação in-prod via `conversion_action_operation`) + GAQL confirma status=ENABLED + SUBMIT_LEAD_FORM/WEBPAGE/ONE_PER_CLICK ✅
- [x] T2 schema rejection: `'category' is a required property` antes do runtime ✅
- [x] T3 pre-flight: duplicate name rejected com PT-BR + sem token ✅
- [x] T4 batch split: T4-A (PURCHASE+WEBPAGE+value_settings) applied ✅; T4-B (IMPORTED_LEAD+UPLOAD_CLICKS) revealed F18 — schema fix shipado em commit seguinte
- [x] T5 UPLOAD_CALLS+PHONE_CALL_LEAD applied + GAQL confirma ✅
- [x] Production revision verificada (`v4-ads-mcp-00157-ssp` smoke run; F18 fix bumpa pra próximo rev)
- [x] CLAUDE.md atualizado: Sprint 3b.19A shipped, tool count = 45

**Date completed:** 2026-05-13

## Findings (post-execution)

**Smoke 5/5 PASS (com 2 findings reais)** após F17 + F18 fixes.

### F17 — `LEAD` removido do SDK v20 (sprint design gap)

T1 inicial (pre-fix) falhou com `KeyError: 'LEAD'` em production logs. Root cause: `LEAD` foi REMOVIDO do `ConversionActionCategoryEnum` em google-ads SDK v20 (era value 6 historicamente; agora há gap entre SIGNUP=5 e DOWNLOAD=7). Sprint design assumiu LEAD válido com base em legacy docs / common knowledge; context7 query pre-builder cobriu apenas exemplo de `type_` (WEBPAGE) mas não validou cada value do category whitelist.

**Fix shipado em commit `d43b141`:** removido `LEAD` do `_CATEGORY_ENUM` whitelist (18 → 17 valores). Tests + smoke runbook usam `SUBMIT_LEAD_FORM` como replacement semântico para V4 lead-gen use case (form submit via WhatsApp/site).

### F18 — Lead lifecycle categorias system-only (Google's lead workflow)

T4-B inicial falhou com `ENUM_VALUE_NOT_PERMITTED` em `IMPORTED_LEAD`. Probes isolando categories revelaram pattern: 3 categorias rejeitadas pelo Google API mesmo válidas no SDK enum:

| Category | Result | Reason |
|---|---|---|
| `IMPORTED_LEAD` | ❌ ENUM_VALUE_NOT_PERMITTED | system-managed via CRM lead import workflow |
| `QUALIFIED_LEAD` | ❌ INVALID_VALUE | system-managed (lead lifecycle) |
| `CONVERTED_LEAD` | ❌ INVALID_VALUE | system-managed (lead lifecycle) |
| `PHONE_CALL_LEAD` | ✅ | user-creatable |
| `SUBMIT_LEAD_FORM` | ✅ | user-creatable |

Google's API documentation não documenta explicitamente quais categorias são "user-creatable" vs "system-managed" — descoberta empírica via smoke. Para V4 lead-gen, gestor usa `SUBMIT_LEAD_FORM` (form submit) ou `PHONE_CALL_LEAD` (call-driven) — categorias system-managed são auto-populated por workflows do Google (Lead Form Asset auto-tagging, CRM imports).

**Fix shipado em commit seguinte:** removido `IMPORTED_LEAD`, `QUALIFIED_LEAD`, `CONVERTED_LEAD` do `_CATEGORY_ENUM` whitelist (17 → 14 valores final). Tool description atualizada com nota explicativa.

### Cumulative findings family

F17 + F18 são membros da **silent-acceptance bug family** (8ª e 9ª variantes):
- F17: design gap (SDK enum removed)
- F18: design gap (enum value valid em SDK mas system-managed pelo Google API)

Ambos compartilham raiz comum: **schema whitelists não foram validados empiricamente** durante design — context7 confirmou ONE example, mas não testou cada enum value. **Lição:** smoke runbook deve incluir explicit per-value validation step OU pre-flight do MCP deve fazer schema-vs-API live check no startup.

### Cumulative real biz value

3 ConversionActions úteis criadas em Nutry sandbox:
- `7609413999` (SUBMIT_LEAD_FORM WEBPAGE — Lead WhatsApp Site)
- `7609002182` (PURCHASE WEBPAGE com R$50 default value — Compra Webhook)
- `7609002908` (PHONE_CALL_LEAD UPLOAD_CALLS — Call Lead Offline)

Plus 3 probes (PURCHASE+UPLOAD_CLICKS, PHONE_CALL_LEAD+WEBPAGE, QUALIFIED_LEAD/CONVERTED_LEAD failures) — todas remain ENABLED em Nutry sandbox. ConversionActions não podem ser deleted via API (Google API limitation), apenas REMOVED status. Aceitar como sandbox junk — zero serving impact (Nutry RSAs continuam PAUSED desde Sprint 3b.16, sem traffic real). Spawn-task: implement `remove_conversion_action` se demanda surgir.

### F13 cross-cutting validado 3ª vez in-prod

`run_mutation` resource_names extraction (Sprint 3b.15) funcionou perfeitamente para `conversion_action_operation`. Sprint 3b.16 (create_rsa via `ad_group_ad_operation`) + Sprint 3b.18 (update_rsa via `ad_operation`) + Sprint 3b.19A (create_conversion_action via `conversion_action_operation`) — cross-cutting feature handles 3 different MutateOperation oneof types automaticamente. Auto-inherited via dynamic `WhichOneof("response")` reading.
