# Phase 3b.16 — manual smoke runbook (`create_rsa`)

**Purpose:** Verify Sprint 3b.16 `create_rsa` (segundo create-pattern do MCP). **Primeira validation empírica do F13 resource_names benefit** (Sprint 3b.15 cross-cutting fix) em produção.

**Operator:** wellinton.ribeiro@v4company.com
**Account:** `1163862076` Rayane Ribeiro - Nutry (sandbox preferida — campaigns + ad_groups já existem from Sprint 3b.14 smoke)

**Spec:** `docs/superpowers/specs/2026-05-12-sprint-3b.16-design.md`
**Plan:** `docs/superpowers/plans/2026-05-12-sprint-3b.16-plan.md`

## Pre-flight

- [x] Deploy lands successfully — Sprint 3b.16 deployed em `v4-ads-mcp-00147-mx2`, **F16 fix** post-smoke em `v4-ads-mcp-00149-jjz`
- [x] Service `/health` returns 200
- [x] Reload MCP client (Claude Code session)
- [x] Tool `create_rsa` visível em MCP client tool list
- [x] Sprint 3b.14 test ad_groups exist (PAUSED): `193677695262`, `193677770782`, `193677770822`, `193677770862`

Production revision: `v4-ads-mcp-00149-jjz` (post Sprint 3b.16.1 F16 fix).

## Test T1 — Happy path 1 RSA (F13 verification)

Primeira test em produção do F13 resource_names benefit.

```
create_rsa(
  customer_id="1163862076",
  rsas=[{
    "ad_group_id": "193677695262",
    "headlines": [
      "[TEST 3b.16] H1",
      "[TEST 3b.16] H2",
      "[TEST 3b.16] H3",
      "[TEST 3b.16] H4",
      "[TEST 3b.16] H5"
    ],
    "descriptions": [
      "Description teste 1 Sprint 3b.16 F13 verification em producao",
      "Description teste 2 segunda valida para schema 2-4 items"
    ],
    "final_urls": ["https://example.com/v4-test-3b16"]
  }]
)
```

Expected:
- [x] Response `status: "dry_run"` com `confirmation_token` (`6B1SZJYG` initial, but **first apply hit F16 bug**, recovered with token `1RENHT7U` post-fix)
- [x] `rsas_preview[0].headlines_count == 5`, `descriptions_count == 2`, `status == "PAUSED"`
- [x] `blast_summary`: "Criar 1 RSA(s) em 1 ad_group(s). Status inicial: PAUSED(1). Avg 5.0 headlines + 2.0 descriptions per RSA."
- [x] Apply via `apply_change` → `status: "applied"`, `applied_count: 1`, `google_request_id: "r7yEVynOHDTVkcCymCoA5A"`
- [x] **F13 PRODUCTION VALIDATION SUCCESS:** `resource_names: ["customers/1163862076/adGroupAds/193677695262~808633585084"]` — Sprint 3b.15 cross-cutting fix works in real production!

**Result: ✅ PASS (post F16 fix).** ad_id `808633585084` created.

### F16 finding (CRITICAL bug — fixed inline durante smoke)

**First apply** (token `6B1SZJYG`) returned `Erro inesperado ao falar com o Google Ads (AttributeError)`.

Root cause (production logs):
```
AttributeError: 'RepeatedComposite' object has no attribute 'add'
File "/workspace/src/google_ads/mutates/ads.py", line 53, in build_create_rsa
    h = rsa.headlines.add()
```

**Bug class A4 redux:** ProtoFieldCapture `_RepeatedCapture` (Sprint 3b.16 Task 2 fixture extension) mocked `.add()` (raw protobuf API) — tests passed. But real google-ads SDK uses proto-plus, which has `.append()` with typed instance, NOT `.add()` on repeated message fields.

**Fixed em commit `1c5ec69` (Sprint 3b.16.1):**
```python
# BEFORE (broken in production):
h = rsa.headlines.add()
h.text = headline_text

# AFTER (proto-plus correct):
h = client.get_type("AdTextAsset")
h.text = headline_text
rsa.headlines.append(h)
```

Production revision `v4-ads-mcp-00149-jjz` post-fix. **Retry T1 PASSED** ✅.

**7th variant of silent-acceptance/mock-fidelity bug family:** A1 (3b.3 dedupe), A3 (3b.4 drop), A4 (3b.4 override), A5 (3b.6 path), F11 (P3 enum no-decode), F12 (3b.8 silent ignore), **F16 (3b.16.1 builder API mismatch)**.

**Lesson reaffirmed:** mock fidelity matters. Future ProtoFieldCapture improvements should mirror proto-plus API surface, not raw protobuf. Spawn-task documented to remove `.add()` support from `_RepeatedCapture` in cleanup sprint.

## Test T2 — Schema rejection (2 headlines, below min 3)

```
create_rsa(
  customer_id="1163862076",
  rsas=[{
    "ad_group_id": "193677695262",
    "headlines": ["[TEST 3b.16] H1", "[TEST 3b.16] H2"],
    "descriptions": ["d1 longer", "d2 another"],
    "final_urls": ["https://example.com/"]
  }]
)
```

Expected:
- [x] Schema validation rejection: `"Input validation error: ['[TEST 3b.16] H1', '[TEST 3b.16] H2'] is too short"`

**Result: ✅ PASS** — JSONSchema rejects pre-runtime, no token consumed.

## Test T3 — Pre-flight missing ad_group

```
create_rsa(
  customer_id="1163862076",
  rsas=[{
    "ad_group_id": "999999999",
    "headlines": ["H1", "H2", "H3"],
    "descriptions": ["d1 longer text", "d2 another"],
    "final_urls": ["https://example.com/"]
  }]
)
```

Expected:
- [x] Response `status: "error"` com error: `"Ad_group 999999999 nao encontrado na conta. Verifique o ad_group_id."`
- [x] Sem token

**Result: ✅ PASS** — pre-flight rejection PT-BR.

## Test T4 — Batch of 3 RSAs cross-ad_groups + path1+path2

```
create_rsa(
  customer_id="1163862076",
  rsas=[
    {
      "ad_group_id": "193677770782",
      "headlines": ["[TEST 3b.16] T4-A H1", "[TEST 3b.16] T4-A H2", "[TEST 3b.16] T4-A H3"],
      "descriptions": ["T4-A description um", "T4-A description dois"],
      "final_urls": ["https://example.com/"],
      "path1": "test",
      "path2": "3b16"
    },
    {
      "ad_group_id": "193677770782",
      "headlines": ["[TEST 3b.16] T4-B H1", "[TEST 3b.16] T4-B H2", "[TEST 3b.16] T4-B H3"],
      "descriptions": ["T4-B description um", "T4-B description dois"],
      "final_urls": ["https://example.com/"]
    },
    {
      "ad_group_id": "193677770822",
      "headlines": ["[TEST 3b.16] T4-C H1", "[TEST 3b.16] T4-C H2", "[TEST 3b.16] T4-C H3"],
      "descriptions": ["T4-C description um", "T4-C description dois"],
      "final_urls": ["https://example.com/"],
      "status": "ENABLED"
    }
  ]
)
```

Expected:
- [x] dry_run com token `6FPPR4X0`
- [x] `blast_summary`: "Criar 3 RSA(s) em 2 ad_group(s). Status inicial: ENABLED(1), PAUSED(2). Avg 3.0 headlines + 2.0 descriptions per RSA."
- [x] `rsas_preview[0].has_path1 == true`, `has_path2 == true`
- [x] `rsas_preview[1].has_path1 == false`
- [x] Apply → applied_count 3 + 3 resource_names: `808633628608`, `808633628611`, `808633628614`

**Result: ✅ PASS** — batch cross-ad_groups + path1/path2 working. F13 returns all 3 resource_names.

## Test T5 — Path validation (path1 > 15 chars → schema rejection)

```
create_rsa(
  customer_id="1163862076",
  rsas=[{
    "ad_group_id": "193677695262",
    "headlines": ["H1", "H2", "H3"],
    "descriptions": ["d1 longer", "d2 another"],
    "final_urls": ["https://example.com/"],
    "path1": "this-is-a-very-long-path-segment-too-long"
  }]
)
```

Expected:
- [x] Schema validation rejection: `"Input validation error: 'this-is-too-long' is too long"`

**Result: ✅ PASS** — JSONSchema maxLength 15 enforced pre-runtime (string `"this-is-too-long"` = 16 chars).

## Cleanup

Para CADA RSA criada (T1 + T4 batch de 3), executar:

```
update_ad_status(
  customer_id="1163862076",
  ads=[{"ad_group_id": "<ag>", "ad_id": "<ad>"}, ...],
  new_status="PAUSED"
)
```

T1 + T4-A + T4-B já nascem PAUSED por default — só T4-C precisa PAUSE.

**Executed:**
- T4-C `808633628614`: ENABLED → PAUSED ✅ (`4uhYuCxdeOi1sOg0V87lMw`)
- T1 (`808633585084`) + T4-A (`808633628608`) + T4-B (`808633628611`): já PAUSED ✓

**4 test RSAs paused** em Nutry sandbox com prefix `[TEST 3b.16]` headlines. Ad_groups parent (`193677695262`, `193677770782`, `193677770822`) também PAUSED desde Sprint 3b.14 → **zero risk de ad serving**. Cleanup permanente via Google Ads UI quando conveniente.

## Sign-off final

- [x] T1 happy path: dry_run + apply + **F13 resource_names PRODUCTION VALIDATION SUCCESS** (post F16 fix)
- [x] T2 schema rejection: minItems 3 enforced antes do tool runtime
- [x] T3 pre-flight: ad_group inexistente rejected com PT-BR
- [x] T4 batch + path1+path2: 3 RSAs criados cross-ad_groups com path display
- [x] T5 schema validation: path1 maxLength 15 enforced
- [x] Cleanup: T4-C ENABLED → PAUSED (others já default)
- [x] Production revision verificada: `v4-ads-mcp-00149-jjz`
- [x] CLAUDE.md atualizado: Sprint 3b.16 shipped, tool count 42 → 43

**Date completed:** 2026-05-12

## Findings summary

**5/5 tests PASS** (T1 + T2 + T3 + T4 + T5) **post F16 fix**.

**1 critical bug discovered + fixed inline (F16):** ProtoFieldCapture mocked `.add()` (raw protobuf API) but proto-plus repeated message fields require `.append(typed_instance)`. Tests passed but production broke. Fix shipped em commit `1c5ec69` (Sprint 3b.16.1). **7th variant of mock-fidelity bug family.**

**F13 PRODUCTION VALIDATION SUCCESS:** Sprint 3b.15 cross-cutting `resource_names` extraction confirmed working in real Google Ads SDK against production. T1 returned `customers/1163862076/adGroupAds/193677695262~808633585084`, T4 returned 3 resource_names matching applied_count. All future creates inherit this benefit.

**4 test RSAs created em Nutry sandbox** (all PAUSED, ad_group parents PAUSED — zero serving risk):
- T1: `808633585084` em ad_group `193677695262`
- T4-A: `808633628608` em ad_group `193677770782` (com path1+path2)
- T4-B: `808633628611` em ad_group `193677770782`
- T4-C: `808633628614` em ad_group `193677770822` (criado ENABLED, manualmente PAUSED)

Cleanup permanente via Google Ads UI quando conveniente. RSAs identificáveis via prefix `[TEST 3b.16]` em headlines.
