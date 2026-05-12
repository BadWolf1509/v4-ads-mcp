# Phase 3b.6 — manual smoke runbook (remove_audience + real cleanup)

**Purpose:** Verify Sprint 3b.6 `remove_audience` em conta real + faz cleanup das 5 orphan criteria de Sprints 3b.4 + 3b.5.

**Operator:** wellinton.ribeiro@v4company.com
**Account (sandbox):** `1163862076` "Rayane Ribeiro - Nutry" (paused, zero traffic)
**Account (real cleanup secundário):** `7862230676` "Mestre da Obra - João Pessoa" — apenas se Wellington decidir reverter o criterion `2480650242694` (Sprint 3b.4 T3 Customer Match observation acidental)

## Pre-flight

- [ ] Deploy lands successfully (`gh run watch <id>` shows green Deploy)
- [ ] Service `/health` returns 200
- [ ] Reload MCP client (restart Claude Code session) — tool list inclui `remove_audience`

## Test T1 — Schema rejection: missing criterion_ids

```
remove_audience(
  customer_id="1163862076",
  target_type="ad_group",
  target_id="183008426336"
  # criterion_ids omitted
)
```

Expected:
- [ ] Schema validation error mencionando "criterion_ids is a required property"
- [ ] Tool NÃO executada
- [ ] Zero quota consumida

## Test T2 — Schema rejection: invalid target_type

```
remove_audience(
  customer_id="1163862076",
  target_type="ad_group_alt",  # invalid enum
  target_id="183008426336",
  criterion_ids=["52988066042"]
)
```

Expected:
- [ ] Schema validation error: `'ad_group_alt' is not one of ['ad_group', 'campaign']`
- [ ] Zero quota consumida

## Test T3 — CONFIRM dry_run de 1 criterion REAL (Sprint 3b.5 IN_MARKET 80012)

Primeiro identificar o criterion_id via GAQL (Sprint 3b.5 T2 criou `52988066042`):
```
run_gaql(customer_id="1163862076", query=
  "SELECT ad_group_criterion.criterion_id, ad_group_criterion.user_interest.user_interest_category "
  "FROM ad_group_criterion WHERE ad_group.id = 183008426336 "
  "AND ad_group_criterion.user_interest.user_interest_category = 'customers/1163862076/userInterests/80012'")
```

Then dry_run:
```
remove_audience(
  customer_id="1163862076",
  target_type="ad_group",
  target_id="183008426336",
  criterion_ids=["52988066042"]
)
```

Expected:
- [ ] `status: "dry_run"`, `confirmation_token` returned
- [ ] `confirmation_reason` cita "sempre confirma (spec §7.1 remove)"
- [ ] `blast_summary` clara mencionando 1 criterion + target_id

## Test T4 — Apply T3 token + verify via GAQL que criterion sumiu

```
apply_change(confirmation_token=<T3_token>)
```

Expected:
- [ ] `status: "applied"`, `applied_count: 1`, real `google_request_id`
- [ ] GAQL verification post-apply:
  ```
  run_gaql(customer_id="1163862076", query=
    "SELECT ad_group_criterion.criterion_id FROM ad_group_criterion "
    "WHERE ad_group.id = 183008426336 "
    "AND ad_group_criterion.criterion_id = '52988066042'")
  ```
  Expected: **0 rows** — criterion realmente sumiu

## Test T5 — Re-remove SAME criterion (idempotência via partial_failure)

Re-run dry_run + apply do MESMO criterion `52988066042` (já removido pelo T4):
```
remove_audience(...same payload as T3...)
# then apply
```

Expected:
- [ ] dry_run + token returned (não há schema rejection — schema só checa formato)
- [ ] apply_change retorna `applied_count: 0` OU `applied_count: 1` (depende de Google behavior — silent dedupe vs explicit NOT_FOUND)
- [ ] `/admin/audit` mostra audit_log row com per-row status `"already_removed"` OU `"removed"` (ambos OK)
- [ ] **Nenhum spurious failure** — idempotency works state-wise

## Test T6 — Batch cleanup das remaining orphan criteria (real biz value!)

Primeiro identificar TODAS as orphan criteria via GAQL:
```
run_gaql(customer_id="1163862076", query=
  "SELECT ad_group_criterion.criterion_id, ad_group_criterion.type, "
  "ad_group_criterion.user_interest.user_interest_category, "
  "ad_group_criterion.user_list.user_list "
  "FROM ad_group_criterion WHERE ad_group.id = 183008426336 "
  "AND ad_group_criterion.type IN ('USER_INTEREST', 'USER_LIST')")
```

Expected GAQL output: ~4 rows (criteria de Sprints 3b.4 + 3b.5 minus o `52988066042` já removed em T4):
- `56976936578` — Sprint 3b.4 T1.b IN_MARKET id 80001
- AFFINITY 90100 criterion_id (TBD via GAQL — Sprint 3b.5 T3)
- mais 1 IN_MARKET 80001 ou similar Sprint 3b.5 T4 batch test
- `2484607635720` — Sprint 3b.5 brainstorming user_list 9158136688 negative=True

Batch remove (cap 100, em este caso ~4 criteria):
```
remove_audience(
  customer_id="1163862076",
  target_type="ad_group",
  target_id="183008426336",
  criterion_ids=[<lista de criterion_ids extraidos da GAQL>]
)
# then apply
```

Expected:
- [ ] CONFIRM dry_run + token
- [ ] Apply success: `applied_count` matches numero de criteria que ainda existiam
- [ ] Post-apply GAQL: **0 rows** retornados (cleanup completo do ad_group)
- [ ] **Real biz value:** Nutry sandbox limpo após 4 sprints de testing debt

## Decisão Wellington — Cleanup do Mestre da Obra JP (opcional)

Sprint 3b.4 T3 criou criterion `2480650242694` na Mestre da Obra JP campaign `22169885957` (Customer Match observation acidental — não exclusion como pretendido por A4 silent override). Atualmente é benign observation (zero delivery impact), mas Wellington pode querer revert.

Se decidir aplicar:
```
remove_audience(
  customer_id="7862230676",
  target_type="campaign",
  target_id="22169885957",
  criterion_ids=["2480650242694"]
)
# then apply
```

Decisão fica **com Wellington**:
- (a) Apply: limpa Mestre da Obra JP de criterion residual + valida flow end-to-end em conta com tráfego real
- (b) Skip: criterion é benign observation, sem urgência

## Sign-off final

- [ ] T1 + T2 todos passaram (schema rejection)
- [ ] T3 + T4 todos passaram (dry_run → apply → GAQL verify criterion removed)
- [ ] T5 passou (idempotency — re-remove não causa spurious failure)
- [ ] T6 passou (batch cleanup das orphan criteria — Nutry sandbox limpo)
- [ ] Decisão sobre Mestre da Obra JP documentada (applied or skipped)
- [ ] No errors em service logs
- [ ] `/admin/audit` mostra audit rows com `remove_audience` operation + custom params_summary
- [ ] Production revision verificada
- [ ] CLAUDE.md atualizado: Sprint 3b.6 shipped, tool count 38 → 39

**Date completed:** ____
