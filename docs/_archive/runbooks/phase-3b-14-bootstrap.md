# Phase 3b.14 — manual smoke runbook (`create_ad_group`)

**Purpose:** Verify Sprint 3b.14 `create_ad_group` (primeiro create-pattern do MCP) em conta real. Test pre-flight rejections + happy paths + cleanup.

**Operator:** wellinton.ribeiro@v4company.com
**Account:** `1163862076` Rayane Ribeiro - Nutry (sandbox preferida) OR `7862230676` Mestre da Obra JP (active acquisition).

**Spec:** `docs/superpowers/specs/2026-05-12-sprint-3b.14-design.md`
**Plan:** `docs/superpowers/plans/2026-05-12-sprint-3b.14-plan.md`

## Pre-flight

- [x] Deploy lands successfully (`gh run watch <id>` → green)
- [x] Service `/health` returns 200
- [x] Reload MCP client (Claude Code session) — **2 reloads necessários** (ver Sprint 3b.14.1 finding)
- [x] `list_my_accounts` shows target account (Nutry sandbox `1163862076`)
- [x] Identified parent campaigns: `22782946457` (TARGET_SPEND, SEARCH, PAUSED) + `22804468687` (TARGET_SPEND, SEARCH, PAUSED)

Production revision: `v4-ads-mcp-00142-dzf` (post Sprint 3b.14.1 registry fix).

## Test T1 — Happy path (1 PAUSED ad_group em SEARCH campaign)

Pick a SEARCH campaign with MAXIMIZE_CONVERSIONS (or any auto-bidding) — don't include cpc_bid_micros.

```
create_ad_group(
  customer_id="<sandbox>",
  ad_groups=[{
    "campaign_id": "<search_campaign_id>",
    "name": "[TEST 3b.14] Smoke T1 - PAUSED default"
  }]
)
```

Expected:
- [x] Response `status: "dry_run"` com `confirmation_token` (`4H2VANXH`)
- [x] `ad_groups_preview[0].type == "SEARCH_STANDARD"`, `status == "PAUSED"` (defaults)
- [x] `blast_summary` mencionando "1 ad_group(s) em 1 campaign(s). Types: SEARCH_STANDARD(1). Status inicial: PAUSED(1)."
- [x] Apply via `apply_change` → `status: "applied"`, `applied_count: 1`, `google_request_id: "8T_qya4a0La2D6_0c-cl9w"`
- [x] Verificado via GAQL: ad_group_id **`193677695262`** criado em PAUSED status

**Result: ✅ PASS** — ad_group_id `193677695262` para cleanup tracker.

## Test T2 — Pre-flight rejection (missing campaign)

```
create_ad_group(
  customer_id="<sandbox>",
  ad_groups=[{
    "campaign_id": "99999999",
    "name": "[TEST 3b.14] Smoke T2 - missing parent"
  }]
)
```

Expected:
- [x] Response `status: "error"` com `error: "Campaign 99999999 nao encontrada na conta. Verifique o campaign_id."`
- [x] Sem confirmation_token (nenhum mutation registrado)

**Result: ✅ PASS** — pre-flight rejection PT-BR clara.

## Test T3 — Pre-flight rejection (channel mismatch)

Pick the SAME SEARCH campaign de T1, mas force tipo SHOPPING_PRODUCT_ADS:

```
create_ad_group(
  customer_id="<sandbox>",
  ad_groups=[{
    "campaign_id": "<search_campaign_id>",
    "name": "[TEST 3b.14] Smoke T3 - channel mismatch",
    "type": "SHOPPING_PRODUCT_ADS"
  }]
)
```

Expected:
- [x] Response `status: "error"` com `error: "Ad_group type 'SHOPPING_PRODUCT_ADS' incompativel com campaign '[NUTRI RAYANE] [SEARCH] [SITE] [2025] [01] [GT PEDRO]' (id 22782946457) — advertising_channel_type = 'SEARCH'. Use type matching o canal."`
- [x] Sem token

**Result: ✅ PASS** — channel type validation funciona, mensagem inclui campaign name + actual channel.

## Test T4 — Pre-flight rejection (F12: cpc_bid_micros em auto-bidding)

Mesma SEARCH campaign de T1 (MAXIMIZE_CONVERSIONS), mas passa cpc_bid_micros:

```
create_ad_group(
  customer_id="<sandbox>",
  ad_groups=[{
    "campaign_id": "<search_campaign_id>",
    "name": "[TEST 3b.14] Smoke T4 - cpc_bid in auto-bid",
    "cpc_bid_micros": 1500000
  }]
)
```

Expected:
- [x] Response `status: "error"` com `error` mencionando `cpc_bid_micros` + `TARGET_SPEND` (campaign actual strategy)
- [x] Mention "Sprint 3b.8 F12 lesson" no error message
- [x] Sem token

**Result: ✅ PASS** — F12 cross-context validation works (caught at create time, not just update). Empirically validates auto-discovery + pre-flight integration.

## Test T5 — Batch (2-3 ad_groups em campaigns diferentes se disponível)

Se sandbox tiver 2+ campaigns:

```
create_ad_group(
  customer_id="<sandbox>",
  ad_groups=[
    {"campaign_id": "<camp1>", "name": "[TEST 3b.14] Smoke T5-A"},
    {"campaign_id": "<camp1>", "name": "[TEST 3b.14] Smoke T5-B", "status": "ENABLED"},
    {"campaign_id": "<camp2>", "name": "[TEST 3b.14] Smoke T5-C"}
  ]
)
```

Expected:
- [x] `status: "dry_run"` com token (`0IXLGDX0`)
- [x] `blast_summary`: "Criar 3 ad_group(s) em 2 campaign(s). Types: SEARCH_STANDARD(3). Status inicial: ENABLED(1), PAUSED(2)."
- [x] `apply_change(token)` → applied_count=3, google_request_id: `vfYZA_FsZHyxA_prfJ71mg`
- [x] Verificado via GAQL: 3 novos ad_groups criados (T5-A `193677770782` PAUSED, T5-B `193677770822` ENABLED, T5-C `193677770862` PAUSED)

**Result: ✅ PASS** — batch creation cross-campaign funciona corretamente.

**Cleanup IDs:** `193677770782`, `193677770822`, `193677770862`.

## Test T6 — Idempotency check (NÃO idempotente — Google permite duplicates)

Rodar T1 novamente com mesmo name:

```
create_ad_group(
  customer_id="<sandbox>",
  ad_groups=[{
    "campaign_id": "<search_campaign_id>",
    "name": "[TEST 3b.14] Smoke T1 - PAUSED default"  # mesmo name do T1
  }]
)
```

Expected (per spec):
- [ ] ~~Dry_run + apply_change → cria SEGUNDA ad_group com mesmo name (duplicate)~~
- [ ] ~~Verificar em Google Ads UI: 2 ad_groups com mesmo name~~

**Result: ⚠ FAIL (spec assumption WRONG) — but actually GOOD outcome**:
- Dry_run accepted (token `UPY101L9`)
- `apply_change` returned error: **"AdGroup with the same name already exists for the campaign."**

**Google ENFORCES** uniqueness within campaign — spec said "NAO idempotente" but reality is Google rejects duplicate names server-side. Tool description em `create_ad_group.py` está incorreta. Spec §2 decision 5 incorreta.

**F14 finding** — documented separately. Tool description needs update.

**No cleanup needed** (T6 não criou ad_group).

## Cleanup (mandatory)

Para CADA ad_group criada nos tests acima (T1, T5), executar:

```
update_ad_group_status(
  customer_id="1163862076",
  ad_group_ids=["193677770822"],  # apenas T5-B (única ENABLED)
  new_status="PAUSED"
)
```

**Executed:**
- T5-B `193677770822`: ENABLED → PAUSED ✅ (`Sf9nymYhJxmAzq-cQBIGqA`)
- T1 + T5-A + T5-C: já estão PAUSED (defaults aplicados) ✓
- T6: não criou ad_group (Google rejected, ver F14)

**4 test ad_groups paused** em Nutry sandbox com prefix `[TEST 3b.14]`. Remove permanente via Google Ads UI quando conveniente (ad_group_ids: 193677695262, 193677770782, 193677770822, 193677770862). Campaigns parent estão PAUSED entao zero risk de ad serving acidental.

Note: Sprint 3b.5 A2 schema-restrict prevents `update_ad_group_status(REMOVED)` via MCP — aguardar future `remove_ad_group` tool ou usar Google Ads UI.

## Sign-off final

- [x] T1 happy path: dry_run + apply funcionaram, ad_group `193677695262` criado em PAUSED
- [x] T2 missing campaign: erro PT-BR apropriado
- [x] T3 channel mismatch: erro PT-BR mencionando type + channel
- [x] T4 F12 cpc_bid: erro PT-BR mencionando F12 + auto-bidding (TARGET_SPEND)
- [x] T5 batch: 3 ad_groups criados em distribuição correta (PAUSED×2 + ENABLED×1)
- [x] T6 non-idempotency assumption WRONG — F14 finding: Google REJECTS duplicate names within campaign
- [x] Cleanup: todos test ad_groups marcados PAUSED (T5-B atualizado, others já default)
- [x] Production revision `v4-ads-mcp-00142-dzf` (post Sprint 3b.14.1 registry fix)
- [x] CLAUDE.md atualizado: Sprint 3b.14 shipped, tool count 41 → 42

**Date completed:** 2026-05-12 (post-Sprint 3b.14.1 fix)

## Findings (post-execution)

### F13 (UX) — Response shape para create operations não retorna entity IDs criadas

**Severity:** Low-medium.

**Behavior atual:** `create_ad_group` (e `apply_change` que consume token) retornam `applied_count: N` + `google_request_id`, mas **não** retornam os `ad_group_id` ou `resource_name` dos entities criadas. Gestor tem que fazer GAQL query separada pra discover IDs novos antes de fazer follow-up (`add_keywords`, etc).

**Spec §3.5 design.md mencionava:**
```python
"created_ad_groups": [
    {"ad_group_id": "111", "name": "...", "campaign_id": "...",
     "resource_name": "customers/X/adGroups/111"}, ...
]
```

Mas o implementation atual em `create_ad_group.py` só retorna o response shape pra dry_run path. O `apply_change.py` é generic e não tem custom logic pra extract `mutate_response.results[].resource_name`.

**Suggested fix (next sprint):** extract `resource_names` from MutateGoogleAdsResponse e injetar no applied response. Pattern reusable pra futuros creates (`create_rsa`, `create_campaign`, etc).

**Workaround atual:** gestor faz GAQL query `SELECT ad_group.id FROM ad_group WHERE ad_group.name = '...'` post-create.

### F14 — Spec assumption wrong: Google ENFORCES ad_group name uniqueness within campaign

**Severity:** Low (cosmetic — tool description incorreta, but actual behavior is safer than docs claimed).

**Spec §2 decision 5 (idempotency):** "Not idempotent — Google permits duplicate names"

**Reality from T6:** `apply_change` retornou:
```
"Google Ads retornou: AdGroup with the same name already exists for the campaign."
```

Google **rejects** duplicate names server-side. **Idempotency-by-error** at the Google level — re-running same create call fails safely.

**Caveat:** uniqueness é per-campaign. Two ad_groups com mesmo name em campaigns diferentes é OK.

**Suggested fix:**
1. Update tool description em `create_ad_group.py` — remove "NAO idempotente — Google permite nomes duplicados" claim
2. Optional: add pre-flight name uniqueness check (1 more GAQL query) pra caught at dry_run instead of apply_change. YAGNI candidate — gestor tipicamente usa unique names anyway.

### F15 (process) — Registry auto-discovery prevents whole bug class

**Critical bug discovered + fixed durante smoke setup:**

`src/mcp/tools/_registry.py::import_all_tools()` era uma hardcoded list que LAGGED behind actual tool files. Sprints 3b.12 + 3b.13 + 3b.14 shipparam 3 tools mas esqueceram atualizar a lista → 3 tools DEAD em produção apesar de "shipped" status + CI verde.

**Why tests didn't catch:** pytest imports tool modules via test files → `@register_tool` decorator runs as side effect → `_TOOLS` dict populated → tests passam. Production `import_all_tools()` runs WITHOUT those side effects → 3 tools missing.

**Fixed em Sprint 3b.14.1** (commit `14d3d7b`, production rev `v4-ads-mcp-00142-dzf`):
- Replace manual list com `pkgutil.iter_modules` auto-discovery
- Add regression test `test_registered_tool_count_matches_files_on_disk` (1:1 count match)
- Self-maintaining — new tools auto-registered just by file existing

**Lesson:** test side effects can mask production bugs. Tests must verify production behavior, not just internal state.

## Result summary

| Test | Result | Notes |
|---|---|---|
| T1 | ✅ PASS | ad_group `193677695262` PAUSED |
| T2 | ✅ PASS | Pre-flight missing campaign |
| T3 | ✅ PASS | Pre-flight channel mismatch |
| T4 | ✅ PASS | Pre-flight F12 (TARGET_SPEND + cpc_bid) |
| T5 | ✅ PASS | Batch 3 cross-campaign |
| T6 | ⚠ Spec wrong | F14: Google rejects duplicates (better than docs claimed) |

**4 test ad_groups created em Nutry sandbox** (T1 + T5-A/B/C). All PAUSED post-cleanup. Campaigns parent são PAUSED — zero risk de ad serving.

**3 new findings (F13/F14/F15):** UX gap (no IDs in response), spec correction (idempotency assumption wrong), critical bug fixed inline (registry auto-discovery).

**Sprint 3b.14 core functionality:** ✅ working as designed. Pre-flight rejections catch all 3 risk patterns (missing campaign, channel mismatch, F12 auto-bidding). Batch operations work correctly cross-campaign.
