# Phase 3b.16 — manual smoke runbook (`create_rsa`)

**Purpose:** Verify Sprint 3b.16 `create_rsa` (segundo create-pattern do MCP). **Primeira validation empírica do F13 resource_names benefit** (Sprint 3b.15 cross-cutting fix) em produção.

**Operator:** wellinton.ribeiro@v4company.com
**Account:** `1163862076` Rayane Ribeiro - Nutry (sandbox preferida — campaigns + ad_groups já existem from Sprint 3b.14 smoke)

**Spec:** `docs/superpowers/specs/2026-05-12-sprint-3b.16-design.md`
**Plan:** `docs/superpowers/plans/2026-05-12-sprint-3b.16-plan.md`

## Pre-flight

- [ ] Deploy lands successfully (CI verde + new revision active)
- [ ] Service `/health` returns 200
- [ ] Reload MCP client (Claude Code session)
- [ ] Tool `create_rsa` visível em MCP client tool list
- [ ] Sprint 3b.14 test ad_groups ainda existem (PAUSED):
  - `193677695262` em campaign `22782946457`
  - `193677770782`, `193677770822`, `193677770862` (T5-A/B/C)

Production revision: TBD post-deploy.

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
- [ ] Response `status: "dry_run"` com `confirmation_token`
- [ ] `rsas_preview[0].headlines_count == 5`, `descriptions_count == 2`, `status == "PAUSED"`
- [ ] `blast_summary` mencionando "1 RSA(s) em 1 ad_group(s). Status inicial: PAUSED(1)."
- [ ] Apply via `apply_change` → `status: "applied"`, `applied_count: 1`, `google_request_id` presente
- [ ] **F13 critical:** `resource_names` em response, format `customers/1163862076/adGroupAds/193677695262~<ad_id>`
- [ ] Verify em Google Ads UI: novo RSA criado em PAUSED status

**Anotar ad_id from resource_names para cleanup.**

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
- [ ] Schema validation rejection (BEFORE tool runs) — MCP client surfaces error mencionando minItems 3 for headlines

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
- [ ] Response `status: "error"` com error mencionando "999999999" + "nao encontrado"
- [ ] Sem token

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
- [ ] dry_run com token
- [ ] `blast_summary`: "3 RSA(s) em 2 ad_group(s). Status inicial: ENABLED(1), PAUSED(2)."
- [ ] `rsas_preview[0].has_path1 == true`, `has_path2 == true`
- [ ] `rsas_preview[1].has_path1 == false`
- [ ] Apply → applied_count 3 + 3 resource_names

**Anotar 3 ad_ids para cleanup.**

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
- [ ] Schema validation rejection mencionando maxLength 15 for path1

## Cleanup

Para CADA RSA criada (T1 + T4 batch de 3), executar:

```
update_ad_status(
  customer_id="1163862076",
  ads=[{"ad_group_id": "<ag>", "ad_id": "<ad>"}, ...],
  new_status="PAUSED"
)
```

T1 + T4-A + T4-B já nascem PAUSED por default — só T4-C precisa PAUSE. **Total 1 update_ad_status call mínimo.**

Note: ad_groups parent estão PAUSED (Sprint 3b.14 cleanup) → zero risk de ad serving. Cleanup permanente via Google Ads UI quando conveniente (test RSAs marcadas com prefix "[TEST 3b.16]").

## Sign-off final

- [ ] T1 happy path: dry_run + apply + **F13 resource_names returned** (FIRST production validation!)
- [ ] T2 schema rejection: minItems 3 enforced antes do tool runtime
- [ ] T3 pre-flight: ad_group inexistente rejected com PT-BR
- [ ] T4 batch + path1+path2: 3 RSAs criados cross-ad_groups com path display
- [ ] T5 schema validation: path1 maxLength 15 enforced
- [ ] Cleanup: T4-C ENABLED → PAUSED (others já default)
- [ ] Production revision verificada
- [ ] CLAUDE.md atualizado: Sprint 3b.16 shipped, tool count 42 → 43

**Date completed:** ____

## Findings (post-execution)

(Inline — surfaceados durante smoke)
