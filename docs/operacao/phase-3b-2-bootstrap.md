# Phase 3b.2 — manual smoke runbook

**Purpose:** Verify `update_ad_status` + `bulk_pause_by_query` work against real V4 accounts before declaring Sprint 3b.2 done.

**Operator:** Claude (Sonnet 4.7) executando em sessão dirigida por wellinton.ribeiro@v4company.com
**Account (low-risk mutation):** `1163862076` "Rayane Ribeiro - Nutry" (paused campaigns, zero traffic — same sandbox used in 3b.1 smoke)
**Account (overflow read-only):** `7862230676` "Mestre da Obra - João Pessoa"
**Date completed:** 2026-05-11
**Production revision tested:** `v4-ads-mcp-00092-cqq` (commit `24854dc`, includes pre-smoke bug fixes for GAQL parens + REMOVED retrofit gap)

## Pre-flight

- [x] Deploy lands successfully — revision `v4-ads-mcp-00092-cqq` on commit `24854dc`
- [x] Service `/health` returns 200
- [x] MCP client reloaded (post session restart) — tools list includes `update_ad_status` + `bulk_pause_by_query`

## Test 1 — `update_ad_status` PAUSE 1 ad (AUTO path) ✅

Target ad: `764187280240` in ad_group `183008426336` (campaign `22804468687` "[CP][RAYANE][GT LUCAS][PESQUISA]").

Call:
```
update_ad_status(
  customer_id="1163862076",
  ads=[{ad_group_id: "183008426336", ad_id: "764187280240"}],
  new_status="PAUSED"
)
```

Response:
```json
{
  "status": "applied",
  "applied_count": 1,
  "google_request_id": "MMTpOTH3e5XmiXAbv6gFWA",
  "auto_applied_reason": "update_ad_status: single entity — auto"
}
```

- [x] `status: "applied"`, `applied_count: 1`, real `google_request_id`
- [x] AUTO path triggered correctly (single entity + new_status != REMOVED)

## Test 2 — `update_ad_status` REMOVE 1 ad (CONFIRM despite count=1) ✅

Target ad: `763193623577` in ad_group `183298670618` (campaign `22782946457`).

Call with `new_status="REMOVED"`:

Response:
```json
{
  "status": "dry_run",
  "confirmation_token": "WSEHHLMY",
  "confirmation_reason": "update_ad_status: new_status=REMOVED — remove qualquer coisa sempre confirma (spec §7.1)"
}
```

- [x] `status: "dry_run"` (not applied — REMOVED requires CONFIRM even with count=1)
- [x] `confirmation_token` returned
- [x] PT-BR reason explicitly cites spec §7.1
- [x] **Deliberately did NOT call `apply_change`** (avoids permanent removal of a real ad)

**Validates the Task 1 retrofit** (REMOVED-always-confirm for all 4 status ops). Pre-smoke bug fix (`24854dc`) was the critical pre-requisite — without it, REMOVED with count=1 would auto-apply.

## Test 3 — `bulk_pause_by_query` keyword target, dry_run + apply ✅

Filter: 3 specific keywords by criterion_id (no traffic — campaign paused):

Call:
```
bulk_pause_by_query(
  customer_id="1163862076",
  target_type="keyword",
  filter="ad_group_criterion.status = 'ENABLED' AND ad_group_criterion.criterion_id IN (379376135, 309491469759, 389350615846)"
)
```

Dry-run response:
```json
{
  "status": "dry_run",
  "confirmation_token": "PY7OSRT5",
  "preview": {
    "target_type": "keyword",
    "matched_count": 3,
    "total_cost_brl": 224.19,
    "sample": [
      {"id": "379376135", "label": "nutricionista", "context": "[CP][RAYANE][GT LUCAS][PESQUISA] > Grupo de anúncios 1", "cost_brl": 57.76},
      {"id": "309491469759", "label": "nutricionista esportiva", ..., "cost_brl": 72.57},
      {"id": "389350615846", "label": "Nutricionista Online", ..., "cost_brl": 93.86}
    ]
  }
}
```

Apply via `apply_change("PY7OSRT5")`:
```json
{
  "status": "applied",
  "applied_count": 3,
  "google_request_id": "9OMClAqvtxAuseoxGKqE4Q"
}
```

- [x] Dry-run preview correto com 3 keywords, custo total R$ 224.19, sample com names + context
- [x] `apply_change` consumiu token e aplicou 3 pauses
- [x] Real `google_request_id` retornado
- [x] End-to-end cycle dry-run → apply funcionou

**Insight:** `total_cost_brl: 224.19` mostra histórico real dos 30d mesmo com campanha paused atualmente — comportamento útil para auditoria.

## Test 4 — `bulk_pause_by_query` overflow (>100 matches) ✅

Filter amplo em conta ativa (Mestre da Obra JP):

```
bulk_pause_by_query(
  customer_id="7862230676",
  target_type="keyword",
  filter="ad_group_criterion.status = 'ENABLED'"
)
```

Response:
```json
{
  "status": "error",
  "matched_count": "100+",
  "error": "Sua query matched 100+ entidades — acima do limite de 100 por chamada (decisão MVP). Refine o filtro pra reduzir alcance, ou divida em multiplas chamadas. Ex: adicionar AND segments.date DURING LAST_7_DAYS, filtrar campaign.id especifico, ou metricas mais restritivas."
}
```

- [x] `status: "error"`, `matched_count: "100+"`
- [x] PT-BR error mentioning the cap + suggesting refinements
- [x] No `confirmation_token` in response
- [x] No mutation, no quota consumed beyond the 1 dry-run read op

## Test 5 — `bulk_pause_by_query` no matches ✅

Filter impossível (clicks > 99999999):

Response:
```json
{
  "status": "no_op",
  "matched_count": 0,
  "message": "Nenhuma entidade matched o filtro. Nada a pausar."
}
```

- [x] `status: "no_op"`, `matched_count: 0`
- [x] No `confirmation_token`
- [x] Clear PT-BR message

## Test 6 — `bulk_pause_by_query` filter injection rejection ✅

Filter com `;` semicolon:

```
filter="ad_group_criterion.status = 'ENABLED'; DROP TABLE users"
```

Response:
```json
{
  "status": "error",
  "error": "Filter nao pode conter ';' (ponto-e-virgula) — apenas a clausula WHERE eh aceita."
}
```

- [x] `status: "error"`, PT-BR error mentioning "ponto-e-virgula"
- [x] Pre-flight rejection — no query reached Google Ads API
- [x] No quota consumed

## Cleanup ✅

- [x] Ad `764187280240` re-enabled via `update_ad_status` ENABLED (req `6yOuZIqVcNRjVT_ku0Qu2A`)
- [x] 3 keywords (379376135, 309491469759, 389350615846) re-enabled via `update_keyword_status` ENABLED (req `1j66nNlxvpEu9htdW_Q1RQ`)
- [x] T2 token `WSEHHLMY` deliberately left unconsumed (will expire after 10min TTL — safe)
- [x] Conta `1163862076` voltou ao estado original (todos ads + keywords enabled)

## Bugs encontrados e CORRIGIDOS no pre-smoke (não chegaram ao smoke "real")

Durante a pre-validação via `validate_gaql` na conta `1163862076`, ANTES de executar o smoke real:

### B1: GAQL com parênteses agrupando WHERE — Google rejeita

`bulk_pause_query` envolvia user filter em `({filter_clause})`. Google Ads GAQL parser não suporta parens em WHERE — rejeita com `"invalid field name '('"`. **Toda chamada a `bulk_pause_by_query` falharia em produção.**

Fix em commit `24854dc`: drop os parens; `validate_filter` já restringe a AND-chained conditions.

### B2: REMOVED-always-confirm retrofit estava parcial

Spec §3.3 afirmava que os 3 status ops existentes (campaign/ad_group/keyword) ganhavam o retrofit. `blast_radius.classify` foi extendida em Task 1, MAS os 3 tools nunca passaram `new_status` no params dict. Resultado: `update_campaign_status(new_status="REMOVED", target_count=1)` ainda **AUTO-aplicava** (sem dry-run), defeating spec §7.1.

Fix em commit `24854dc`: 3 tools agora passam `params={target_count, new_status}` (1 linha cada). Tests do `test_blast_radius` (Task 1) agora exercitam o caminho real end-to-end.

**Lição:** o uso de `validate_gaql` como pre-flight DURANTE o smoke é vital — pegou bug B1 sem nenhum cost de mutação, antes de qualquer execução real.

## Findings da API observados

- **`total_cost_brl: 224.19` no preview do T3** apesar de `get_account_overview` retornar zero — comportamento esperado: `keyword_view.metrics.cost_micros` mostra histórico real. Útil para auditoria.
- **Overflow trigger preciso**: Google Ads aceitou `LIMIT 101` e devolveu 101 rows quando filter era amplo na conta ativa. O `matched_count: "100+"` é semanticamente correto (excedeu o cap de 100).
- **`apply_change` funcionou cleanly** com payload incluindo `__partial_failure__: True` (fix do final review pre-push) — 3 pauses aplicadas atomicamente.

## Sign-off final

- [x] Todos os 6 tests passaram limpos (✅✅✅✅✅✅)
- [x] Cleanup completo — conta `1163862076` no estado original
- [x] 2 bugs reais pegos no pre-smoke (`24854dc` fix shipou antes do smoke)
- [x] Production revision: `v4-ads-mcp-00092-cqq` (commit `24854dc`)
- [x] CLAUDE.md a ser atualizado: Sprint 3b.2 smoke signed-off 2026-05-11

**Date completed:** 2026-05-11 (executado por Claude em sessão dirigida por wellinton.ribeiro@v4company.com)
