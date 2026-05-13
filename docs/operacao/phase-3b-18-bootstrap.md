# Phase 3b.18 — manual smoke runbook (`update_rsa`)

**Purpose:** Verify Sprint 3b.18 `update_rsa` (segundo update tool após `update_ad_status`). Completes RSA CRUD parcial — create em 3b.16, update em 3b.18.

**Operator:** wellinton.ribeiro@v4company.com
**Account:** `1163862076` Rayane Ribeiro - Nutry (sandbox preferida — RSAs existem from Sprint 3b.16 smoke)

**Spec:** `docs/superpowers/specs/2026-05-13-sprint-3b.18-design.md`
**Plan:** `docs/superpowers/plans/2026-05-13-sprint-3b.18-plan.md`

## Pre-flight

- [ ] Deploy lands successfully
- [ ] Service `/health` returns 200
- [ ] Reload MCP client (Claude Code session)
- [ ] Tool `update_rsa` visível em MCP client tool list
- [ ] Sprint 3b.16 test RSAs ainda existem (all PAUSED):
  - `808633585084` em ad_group `193677695262` (T1 do 3b.16)
  - `808633628608` em ad_group `193677770782` (T4-A com path1+path2)
  - `808633628611` em ad_group `193677770782` (T4-B)
  - `808633628614` em ad_group `193677770822` (T4-C, paused manually)

Production revision: TBD post-deploy.

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
- [ ] `status: "dry_run"` com `confirmation_token`
- [ ] `updates_preview[0].fields_updated == ["headlines"]`
- [ ] `blast_summary` mencionando "1 RSA(s) (1 unicos). Campos: headlines(1)."
- [ ] Apply via `apply_change` → `status: "applied"`, `applied_count: 1`, `google_request_id` presente
- [ ] **F13 critical:** `resource_names` returns `["customers/1163862076/ads/808633585084"]` (top-level Ad format)
- [ ] Verify em Google Ads UI: T1 RSA agora tem 3 headlines começando com "[TEST 3b.18] Updated" (substituindo as 5 originais "[TEST 3b.16] H1-H5")

## Test T2 — Schema rejection (no mutable field, only ad_id)

```
update_rsa(
  customer_id="1163862076",
  updates=[{"ad_id": "808633585084"}]
)
```

Expected:
- [ ] Schema validation rejection (BEFORE tool runs) — `anyOf` constraint enforces at least one mutable field

## Test T3 — Pre-flight missing ad_id

```
update_rsa(
  customer_id="1163862076",
  updates=[{"ad_id": "999999999", "path1": "abc"}]
)
```

Expected:
- [ ] Response `status: "error"` com error: `"Ad 999999999 nao encontrado..."`
- [ ] Sem token

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
- [ ] dry_run com token
- [ ] `updates_preview[0].fields_updated == ["path1"]`
- [ ] Apply → applied
- [ ] Verify em Google Ads UI: RSA T4-A path1 agora é "novo" (substitui "test"), mas headlines/descriptions/path2 UNCHANGED (proto-plus field_mask precision)

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
- [ ] `blast_summary`: "Atualizar 2 RSA(s) (2 unicos). Campos: descriptions(1), final_urls(1)."
- [ ] Apply → applied_count 2, 2 resource_names
- [ ] Google Ads UI: T4-B (`808633628611`) tem novas descriptions; T4-C (`808633628614`) tem novo final_url

## Cleanup

RSAs já estão PAUSED (Sprint 3b.16 cleanup). Updates não mudam status. Nenhum cleanup adicional necessário.

Note: ad_group parents continuam PAUSED → zero serving risk.

## Sign-off final

- [ ] T1 happy path: headlines replace + F13 resource_name returned
- [ ] T2 schema rejection: anyOf enforced antes do tool runtime
- [ ] T3 pre-flight: ad_id inexistente rejected com PT-BR
- [ ] T4 partial update: path1 substituído, outros campos preservados
- [ ] T5 batch: 2 updates fields diferentes, ambos applied
- [ ] Production revision verificada
- [ ] CLAUDE.md atualizado: Sprint 3b.18 shipped, tool count 43 → 44

**Date completed:** ____

## Findings (post-execution)

(Inline — surfaceados durante smoke)
