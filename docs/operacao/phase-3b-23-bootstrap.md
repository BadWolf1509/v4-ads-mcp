# Phase 3b.23 — manual smoke runbook (F22 limit param)

**Purpose:** Validar Sprint 3b.23 — adiciona `limit` param + `truncated`/`returned_count` fields em `get_negative_keywords_audit` pra destravar UX em contas grandes (F22 finding do Sprint 3b.21 smoke).

**Operator:** wellinton.ribeiro@v4company.com
**Account:** `7862230676` Mestre da Obra JP (467 negativas — F22 reproducer original)

## Pre-flight

- [ ] Deploy lands successfully
- [ ] Service `/health` returns 200
- [ ] Reload MCP client
- [ ] Tool `get_negative_keywords_audit` schema atualizado em prod (limit param visível)

Production revision: `<fill-in>`.

## Test T1 — Default limit (100) em conta grande resolve token cap

```
get_negative_keywords_audit(customer_id="7862230676")
```

Expected:
- [ ] Response volta com sucesso (não exceeds MCP cap)
- [ ] `total_negatives: 467` (full account count preserved)
- [ ] `returned_count: 100` (default limit applied)
- [ ] `truncated: true`
- [ ] `limit: 100`
- [ ] `by_campaign` tem ~100 negativas total
- [ ] `additions_summary` continua computado sobre FULL set: `last_30_days: ~243`, `pre_30_days_or_unknown: ~224`

**Result:** ⬜ pending

## Test T2 — Ordering: recentes primeiro

Continue T1 result inspection:

Expected:
- [ ] Primeiras N negativas em `by_campaign[*].negatives[*]` têm `created_date != null`
- [ ] Sort DESC por `created_date` (ex: 2026-05-09 antes de 2026-05-06)
- [ ] Após recentes, vêm as null (older) em ordem de campanha

**Result:** ⬜ pending

## Test T3 — Custom limit lower (50)

```
get_negative_keywords_audit(customer_id="7862230676", limit=50)
```

Expected:
- [ ] `returned_count: 50`, `truncated: true`, `limit: 50`
- [ ] As 50 mais recentes apenas

**Result:** ⬜ pending

## Test T4 — Custom limit higher (500) — borderline com MCP cap

```
get_negative_keywords_audit(customer_id="7862230676", limit=500)
```

Expected:
- [ ] **Pode** ainda exceder MCP cap dado response size proporcional a 500 negativas (~100k chars). Se exceder, documentar como known limitation (gestor que pede mais aceita o risco).
- [ ] Se não exceder, `returned_count: 467` (todas as negativas), `truncated: false` (total ≤ limit).

**Result:** ⬜ pending

## Test T5 — Low-volume account (sem truncation)

```
get_negative_keywords_audit(customer_id="7455088726")
```

Expected:
- [ ] `total_negatives: 13` (ML Antiguidades)
- [ ] `returned_count: 13`
- [ ] `truncated: false`
- [ ] `limit: 100` (default)
- [ ] Shape consistente com T1 (mesmos fields)

**Result:** ⬜ pending

## Findings

Document any new findings. Se T1-T5 all PASS clean, Sprint 3b.23 continua streak iniciado em 3b.22.

## Real biz value

- **F22 fechado:** gestor agora pode rodar `get_negative_keywords_audit` em conta MO-JP sem token cap. Default limit=100 cobre o weekly report use case (ver as ~100 negativas mais recentes em uma única chamada).
- **Audit completo via limit=1000** se gestor precisar (pode exceder cap em accounts >500 negs, mas é opt-in).
- **Ordering recente-first** alinhado com use case "X negativas adicionadas no período" — gestor lê primeiro o que importa pro report semanal.
- **Pattern consistente com Sprint 3b.20 fix** (search_terms_report 500→50). 2 reads tools agora têm limit + truncation pattern.
