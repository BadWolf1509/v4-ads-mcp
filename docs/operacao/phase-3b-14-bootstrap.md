# Phase 3b.14 — manual smoke runbook (`create_ad_group`)

**Purpose:** Verify Sprint 3b.14 `create_ad_group` (primeiro create-pattern do MCP) em conta real. Test pre-flight rejections + happy paths + cleanup.

**Operator:** wellinton.ribeiro@v4company.com
**Account:** `1163862076` Rayane Ribeiro - Nutry (sandbox preferida) OR `7862230676` Mestre da Obra JP (active acquisition).

**Spec:** `docs/superpowers/specs/2026-05-12-sprint-3b.14-design.md`
**Plan:** `docs/superpowers/plans/2026-05-12-sprint-3b.14-plan.md`

## Pre-flight

- [ ] Deploy lands successfully (`gh run watch <id>` → green)
- [ ] Service `/health` returns 200
- [ ] Reload MCP client (Claude Code session)
- [ ] `list_my_accounts` shows target account
- [ ] `get_campaign_performance(customer_id=<sandbox>, status="enabled")` — identify campaign(s) para usar como parent

Production revision: TBD post-deploy.

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
- [ ] Response `status: "dry_run"` com `confirmation_token`
- [ ] `ad_groups_preview[0].type == "SEARCH_STANDARD"`, `status == "PAUSED"` (defaults)
- [ ] `blast_summary` mencionando "1 ad_group(s) em 1 campaign(s). Types: SEARCH_STANDARD(1). Status inicial: PAUSED(1)."
- [ ] Apply via `apply_change(confirmation_token=<token>)` → `status: "applied"`, `applied_count: 1`, `google_request_id` presente
- [ ] Verificar em Google Ads UI: novo ad_group criado em PAUSED status

**Anotar ad_group_id criado para cleanup.**

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
- [ ] Response `status: "error"` com `error` mencionando "99999999" + "nao encontrada"
- [ ] Sem confirmation_token (nenhum mutation registrado)

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
- [ ] Response `status: "error"` com `error` mencionando "SHOPPING_PRODUCT_ADS" + "SEARCH"
- [ ] Sem token

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
- [ ] Response `status: "error"` com `error` mencionando "cpc_bid_micros" + "MAXIMIZE_CONVERSIONS" (ou outra auto-bidding strategy do campaign)
- [ ] Mention "Sprint 3b.8 F12 lesson" no error message
- [ ] Sem token

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
- [ ] `status: "dry_run"` com token
- [ ] `blast_summary`: "3 ad_group(s) em 2 campaign(s). Types: SEARCH_STANDARD(3). Status inicial: ENABLED(1), PAUSED(2)."
- [ ] `apply_change(token)` → 3 ad_groups criados, applied_count=3
- [ ] Verificar em Google Ads UI: 3 novos ad_groups (2 PAUSED + 1 ENABLED)

**Anotar 3 ad_group_ids para cleanup.**

Se sandbox tem só 1 campaign, skip T5 e fazer batch de 2 ad_groups na mesma campaign.

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

Expected:
- [ ] Dry_run + apply_change → cria SEGUNDA ad_group com mesmo name (duplicate)
- [ ] Verificar em Google Ads UI: 2 ad_groups com mesmo name (confirma documentação "not idempotent")

**Anotar este ad_group_id para cleanup.**

## Cleanup (mandatory)

Para CADA ad_group criada nos tests acima (T1, T5, T6), executar:

```
update_ad_group_status(
  customer_id="<sandbox>",
  ad_group_ids=["<id1>", "<id2>", ...],
  new_status="PAUSED"  # se ENABLED foi usado, voltar pra PAUSED primeiro
)
```

Note: Sprint 3b.5 A2 schema-restrict prevents `update_ad_group_status(REMOVED)` via MCP. Para deletar permanentemente, usar Google Ads UI (manual cleanup) ou aguardar Sprint 3b.X que ship `remove_ad_group` tool.

**Workaround acceptable for V4 dogfood:** ad_groups PAUSED com nome "[TEST 3b.14]" prefix são fácil de identificar e removable via UI quando conveniente.

## Sign-off final

- [ ] T1 happy path: dry_run + apply funcionaram, ad_group visível em Google Ads UI
- [ ] T2 missing campaign: erro PT-BR apropriado
- [ ] T3 channel mismatch: erro PT-BR mencionando type + channel
- [ ] T4 F12 cpc_bid: erro PT-BR mencionando F12 + auto-bidding
- [ ] T5 batch: 2-3 ad_groups criados em distribuição correct
- [ ] T6 non-idempotency confirmed
- [ ] Cleanup: todos test ad_groups marcados PAUSED (REMOVED via UI quando conveniente)
- [ ] Production revision verificada
- [ ] CLAUDE.md atualizado: Sprint 3b.14 shipped, tool count 41 → 42

**Date completed:** ____

## Findings (populated post-execution)

(Inline findings — bugs, UX issues, surprises — surfaceadas durante smoke)
