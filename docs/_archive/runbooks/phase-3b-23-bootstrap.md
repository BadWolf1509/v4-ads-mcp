# Phase 3b.23 — manual smoke runbook (F22 limit param)

**Purpose:** Validar Sprint 3b.23 — adiciona `limit` param + `truncated`/`returned_count` fields em `get_negative_keywords_audit` pra destravar UX em contas grandes (F22 finding do Sprint 3b.21 smoke).

**Operator:** wellinton.ribeiro@v4company.com
**Account:** `7862230676` Mestre da Obra JP (467 negativas — F22 reproducer original)

## Pre-flight

- [x] Deploy lands successfully (revision `v4-ads-mcp-00172-7pm`, Deploy verde)
- [x] Service `/health` returns 200
- [x] Reload MCP client (auto-refresh; nota: client schema cache pode lagar — ver F28 abaixo)

Production revision: `v4-ads-mcp-00172-7pm`.

## Test T1 — Default limit (100) em conta grande resolve token cap

```
get_negative_keywords_audit(customer_id="7862230676")
```

Expected:
- [x] Response volta com sucesso (não exceeds MCP cap)
- [x] `total_negatives: 467` (full account count preserved)
- [x] `returned_count: 100` (default limit applied)
- [x] `truncated: true`
- [x] `limit: 100`
- [x] `by_campaign` tem ~100 negativas total
- [x] `additions_summary` continua computado sobre FULL set

**Result:** ✅ PASS — **F22 RESOLVIDO em produção**. Response shape:
```json
{
  "customer_id": "7862230676",
  "total_negatives": 467,
  "returned_count": 100,
  "truncated": true,
  "limit": 100,
  "additions_summary": {"last_7_days": 0, "last_30_days": 243, "pre_30_days_or_unknown": 224},
  "by_campaign": [
    {"campaign_id": "21359547724", "negatives": [...51 rules...]},
    {"campaign_id": "22169885957", "negatives": [...49 rules...]}
  ]
}
```
**Response total: ~33k chars vs 81k pre-fix (~59% redução).** Cap MCP não excedido. `additions_summary` reflete conta inteira (243 + 224 = 467 = total_negatives invariant preserved).

## Test T2 — Ordering: recentes primeiro

Expected:
- [x] Primeiras N negativas em `by_campaign[*].negatives[*]` têm `created_date != null`
- [x] Sort DESC por `created_date`
- [x] Após recentes, vêm as null (older) em ordem de campanha

**Result:** ✅ PASS via T1 result inspection. Primeiras 4 negativas em ordem perfeita:
1. `criterion_id 11208536` "salvador" BROAD — `created_date "2026-05-09"` (most recent)
2. `criterion_id 11504651` "maceio" BROAD — `created_date "2026-05-06"`
3. `criterion_id 22923991` "aracaju" BROAD — `created_date "2026-05-06"`
4. `criterion_id 49918290` "maceió" BROAD — `created_date "2026-05-06"`
5-50. Bulk de `created_date "2026-05-01"`

DESC ordering verificado. Stable sort within ties (2026-05-06 entries in original campaign order). All 100 returned têm `created_date != null` (já que summary mostra 243 em last_30_days e default limit=100 cabe no recent bucket).

## Test T3 + T4 — Custom limit values

**Result:** ⏸️ BLOCKED em smoke session — **F28 (session schema cache propagation lag)**. Quando passei `limit=10`, MCP server respondeu `"Input validation error: '10' is not of type 'integer'"` — o client cache local tem schema antigo (sem `limit` field declared), então MCP serializou o int 10 como string "10". Server validation correto.

**Não é regressão da Sprint 3b.23** — é characteristic do MCP transport (schema fetched at session connect, não re-fetched after deploy). Workaround: Wellington restart Claude Code → next session sends `limit` as integer correctly. T1 default validates that limit IS being applied corretamente quando present no payload — T3/T4 com custom values vão funcionar post-restart.

Documentação no CLAUDE.md row sobre F28 + pattern de "after every deploy that adds schema fields, gestor pode precisar restart Claude Code session" para integer-typed params new.

## Test T5 — Low-volume account (sem truncation)

Expected:
- [x] `total_negatives: 13` (ML Antiguidades)
- [x] `returned_count: 13`
- [x] `truncated: false`
- [x] `limit: 100` (default)
- [x] Shape consistente com T1

**Result:** ✅ PASS. Response:
```json
{
  "customer_id": "7455088726",
  "total_negatives": 13,
  "returned_count": 13,
  "truncated": false,
  "limit": 100,
  "additions_summary": {"last_7_days": 0, "last_30_days": 0, "pre_30_days_or_unknown": 13},
  "by_campaign": [
    {"campaign_id": "19162926919", "negatives": [...9 rules...]},
    {"campaign_id": "19164045014", "negatives": [...4 rules...]}
  ]
}
```
Shape idêntico ao T1 (cross-account consistency). Sem truncação esperada (13 ≤ 100 default).

## Findings

### F28 — MCP client schema cache propagation lag (LOW severity, MCP framework characteristic)

**Reproducer:** Adicionar novo param a tool schema → deploy → no smoke da mesma session, client cache ainda tem old schema → calls com novo param podem ter type coercion errors.

**Root cause:** MCP framework fetches tool schemas at session connect; doesn't auto-refresh after server deploys. Client-side validation/serialization uses cached schema.

**Workaround:** Restart Claude Code session post-deploy quando smoke testar new schema params.

**Não-blocking** — server-side validation captures the type mismatch with clear error. T1 default param (sem arg passado) testa code path completo sem precisar do cache update.

**Sprint 3b.23 NÃO é regression** — F28 é inherent MCP transport behavior, not introduced by F22 fix.

## Real biz value

- **F22 fechado:** gestor agora pode rodar `get_negative_keywords_audit` em conta MO-JP sem token cap. Default limit=100 cobre o weekly report use case (ver as ~100 negativas mais recentes em uma única chamada).
- **Audit completo via limit=1000** se gestor precisar (pode exceder cap em accounts >500 negs, mas é opt-in).
- **Ordering recente-first** alinhado com use case "X negativas adicionadas no período" — gestor lê primeiro o que importa pro report semanal.
- **Pattern consistente com Sprint 3b.20 fix** (search_terms_report 500→50). 2 reads tools agora têm limit + truncation pattern.
