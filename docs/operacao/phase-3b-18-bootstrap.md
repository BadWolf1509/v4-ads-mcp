# Phase 3b.18 — manual smoke runbook (`update_rsa`)

**Purpose:** Verify Sprint 3b.18 `update_rsa` (segundo update tool após `update_ad_status`). Completes RSA CRUD parcial — create em 3b.16, update em 3b.18.

**Operator:** wellinton.ribeiro@v4company.com
**Account:** `1163862076` Rayane Ribeiro - Nutry (sandbox preferida — RSAs existem from Sprint 3b.16 smoke)

**Spec:** `docs/superpowers/specs/2026-05-13-sprint-3b.18-design.md`
**Plan:** `docs/superpowers/plans/2026-05-13-sprint-3b.18-plan.md`

## Pre-flight

- [x] Deploy lands successfully
- [x] Service `/health` returns 200
- [x] Reload MCP client (Claude Code session)
- [x] Tool `update_rsa` visível em MCP client tool list
- [x] Sprint 3b.16 test RSAs ainda existem (all PAUSED):
  - `808633585084` em ad_group `193677695262` (T1 do 3b.16)
  - `808633628608` em ad_group `193677770782` (T4-A com path1+path2)
  - `808633628611` em ad_group `193677770782` (T4-B)
  - `808633628614` em ad_group `193677770822` (T4-C, paused manually)

Production revision: `v4-ads-mcp-00153-hkl`.

## Test T1 — Update headlines only (F13 verification + replace semantics)

```
update_rsa(
  customer_id="1163862076",
  updates=[{
    "ad_id": "808633585084",
    "headlines": [
      "[TEST 3b.18] Updated H1",
      "[TEST 3b.18] Updated H2",
      "[TEST 3b.18] Updated H3"
    ]
  }]
)
```

Expected:
- [x] `status: "dry_run"` com `confirmation_token` → token `WRTZXCSI`
- [x] `updates_preview[0].fields_updated == ["headlines"]`
- [x] `blast_summary` mencionando "Atualizar 1 RSA(s) (1 unicos). Campos: headlines(1)."
- [x] Apply via `apply_change` → `status: "applied"`, `applied_count: 1`, `google_request_id: "4vX9c6TlYKd9Twc3I6DlNQ"` presente
- [x] **F13 critical:** `resource_names: ["customers/1163862076/ads/808633585084"]` (top-level Ad format) ✅ — 2ª validação F13 in-prod (1ª em create_rsa Sprint 3b.16; agora em update_rsa via `ad_operation`)
- [x] Verify via GAQL: T1 RSA agora tem 3 headlines `[TEST 3b.18] Updated H1/H2/H3` (substituindo as 5 originais `[TEST 3b.16] H1-H5`); descriptions UNCHANGED (proto-plus field_mask precision validated)

## Test T2 — Schema rejection (no mutable field, only ad_id)

```
update_rsa(
  customer_id="1163862076",
  updates=[{"ad_id": "808633585084"}]
)
```

Expected:
- [x] Schema validation rejection (BEFORE tool runs) — `anyOf` constraint enforces at least one mutable field. Error: `"{'ad_id': '808633585084'} is not valid under any of the given schemas"` ✅

## Test T3 — Pre-flight missing ad_id

```
update_rsa(
  customer_id="1163862076",
  updates=[{"ad_id": "999999999", "path1": "abc"}]
)
```

Expected:
- [x] Response `status: "error"` com error: `"Ad 999999999 nao encontrado na conta. Verifique o ad_id."` ✅
- [x] Sem token ✅

## Test T4 — Partial update (only path1)

```
update_rsa(
  customer_id="1163862076",
  updates=[{
    "ad_id": "808633628608",
    "path1": "novo"
  }]
)
```

Expected:
- [x] dry_run com token `09KZW0T5`
- [x] `updates_preview[0].fields_updated == ["path1"]`
- [x] Apply → applied (`google_request_id: "k_b42xCbS0IRUB7zrvcwMQ"`)
- [x] Verify via GAQL: RSA T4-A `path1: "novo"` (substitui "test"); `path2: "3b16"` UNCHANGED; 3 headlines `[TEST 3b.16] T4-A H1/H2/H3` UNCHANGED; descriptions `T4-A description um/dois` UNCHANGED ✅ — field_mask precision works (touches only what gestor specified)

## Test T5 — Batch of 2 updates different fields

```
update_rsa(
  customer_id="1163862076",
  updates=[
    {
      "ad_id": "808633628611",
      "descriptions": [
        "T5 desc atualizada um descrição mais longa nova",
        "T5 desc atualizada dois segunda descrição"
      ]
    },
    {
      "ad_id": "808633628614",
      "final_urls": ["https://example.com/3b18-test"]
    }
  ]
)
```

Expected:
- [x] `blast_summary`: "Atualizar 2 RSA(s) (2 unicos). Campos: descriptions(1), final_urls(1)." ✅ (token `P5MTSMD7`)
- [x] Apply → applied_count 2, 2 resource_names (`google_request_id: "y_QIul3LQkNzQM6Vx4QoSQ"`)
- [x] GAQL verify: T4-B (`808633628611`) descriptions = `T5 desc atualizada um/dois`, final_urls UNCHANGED (`https://example.com/`); T4-C (`808633628614`) final_urls = `[https://example.com/3b18-test]`, descriptions UNCHANGED (`T4-C description um/dois`) ✅ — batch field_mask precision validated cross-update

## Cleanup

RSAs já estão PAUSED (Sprint 3b.16 cleanup). Updates não mudam status. Nenhum cleanup adicional necessário.

Note: ad_group parents continuam PAUSED → zero serving risk.

## Sign-off final

- [x] T1 happy path: headlines replace + F13 resource_name returned ✅
- [x] T2 schema rejection: anyOf enforced antes do tool runtime ✅
- [x] T3 pre-flight: ad_id inexistente rejected com PT-BR ✅
- [x] T4 partial update: path1 substituído, outros campos preservados (field_mask precision) ✅
- [x] T5 batch: 2 updates fields diferentes, ambos applied (cross-update precision) ✅
- [x] Production revision verificada: `v4-ads-mcp-00153-hkl`
- [x] CLAUDE.md atualizado: Sprint 3b.18 shipped, tool count 43 → 44

**Date completed:** 2026-05-13

## Findings (post-execution)

**ZERO findings.** Smoke 5/5 PASS first try.

Highlights:
1. **F13 validated 2ª vez in-prod via `ad_operation`** (Sprint 3b.15 cross-cutting feature). 1ª foi Sprint 3b.16 `create_rsa` via `ad_group_ad_operation`. Auto-inherited via `run_mutation` — zero new code. T1 + T4 + T5 todos retornaram `resource_names` no top-level Ad format (`customers/{cid}/ads/{ad_id}`).
2. **proto-plus field_mask precision validated triplo:** T4 single-field partial (path1 changes, path2/headlines/descriptions UNCHANGED), T5 batch cross-update (descriptions changed em ad1 só, final_urls changed em ad2 só). `update_mask` derivado dinamicamente do builder funciona com Google API.
3. **9ª sprint consecutiva sem novos bugs no smoke** (3b.7 + P2 + 3b.8 + 3b.9 + 3b.10 + 3b.11 + 3b.12 + 3b.13 + 3b.18 — stabilization compounding mantido). Sprint 3b.16 quebrou o streak com F16 mock-fidelity; Sprint 3b.17 defensive cleanup + uso correto desde início no 3b.18 evitou regressão.
4. **Mock-fidelity lesson empiricamente honrada:** `update_rsa` builder usou `client.get_type("AdTextAsset") + .append()` pattern desde o initial draft (no commit history sem `.add()` regression). Sprint 3b.17 cleanup do fixture (`.add()` removed) garantiu que regressões futuras vão AttributeError loudly em test time. Defense-in-depth working.

Cleanup status: 4 test RSAs em Nutry sandbox continuam PAUSED (parent ad_groups PAUSED, zero serving risk). Headlines/descriptions/path1/final_urls atualizados via smoke ficam como artefatos do test — sem cleanup necessário.
