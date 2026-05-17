# Phase 3b.21 — manual smoke runbook (negative_keywords_audit enrichment)

**Purpose:** Verify Sprint 3b.21 enrichment em conta real — closes último finding aberto do relatório 2026-05-17 (§1.3: created_date + added_by_email per criterion + additions_summary block).

**Operator:** wellinton.ribeiro@v4company.com
**Account:** `7862230676` "Mestre da Obra - João Pessoa" (467 negativas conforme relatório 15/05 — bulk shape conhecido)

## Pre-flight

- [ ] Deploy lands successfully (`gh run watch <id>` shows green Deploy)
- [ ] Service `/health` returns 200
- [ ] Reload MCP client (restart Claude Code session)

Production revision: `<fill-in>`.

## Test T1 — Basic enrichment + summary block presence

```
get_negative_keywords_audit(customer_id="7862230676")
```

Expected:
- [ ] Response inclui novo bloco `additions_summary` com 3 fields: `last_7_days`, `last_30_days`, `pre_30_days_or_unknown` (all int).
- [ ] Cada negativa em `by_campaign[*].negatives[*]` inclui novos fields `created_date` (string YYYY-MM-DD ou null) + `added_by_email` (string ou null).
- [ ] `total_negatives` mantém shape (provavelmente ~467 para MO-JP, +/- depending de cleanup recente).

**Result:** ⬜ pending

## Test T2 — Retention boundary: ao menos 1 negativa enriquecida

Wellington rodou Sprint 3b.20 smoke em 17/05 — não adicionou negativas. Sprints 3b.6 e antes podem ter adicionado. Cross-reference com `get_change_history`:

```
get_change_history(
  customer_id="7862230676",
  date_range="LAST_30_DAYS",
  resource_types=["CAMPAIGN_CRITERION"],
  operation_types=["CREATE"]
)
```

Compare with `additions_summary.last_30_days` do T1:

Expected:
- [ ] `additions_summary.last_30_days` >= número de CAMPAIGN_CRITERION CREATEs recentes (deve match exato após filtro de keyword negative).
- [ ] Para cada negativa com `created_date != null` em T1, existe evento correspondente em `get_change_history` result.

**Result:** ⬜ pending

## Test T3 — Bulk pre-30d coverage

Expected (sabendo que MO-JP tem ~467 negativas e algumas são antigas):
- [ ] `additions_summary.pre_30_days_or_unknown` é o bulk (provavelmente >400).
- [ ] Maior parte das negativas tem `created_date: null` (esperado — retention ~30d).

**Result:** ⬜ pending

## Test T4 — Invariant check

Expected:
- [ ] `additions_summary.last_30_days + additions_summary.pre_30_days_or_unknown == total_negatives` (exato).
- [ ] `additions_summary.last_7_days <= additions_summary.last_30_days` (inclusion).

**Result:** ⬜ pending

## Test T5 — Cross-account sanity (diferente volume)

Rodar em 1 conta menor (e.g., ML Antiguidades `7455088726` que pegamos em Sprint 3b.7) pra validar shape consistente em low-volume account:

```
get_negative_keywords_audit(customer_id="7455088726")
```

Expected:
- [ ] Response inclui `additions_summary` mesmo se conta tem 0 negativas (summary com zeros).
- [ ] Se 0 negativas, `total_negatives=0`, `by_campaign=[]`.
- [ ] Sem crash ou erro.

**Result:** ⬜ pending

## Findings

Document any new findings here. Se T1-T5 all PASS clean, este será o **11º sprint consecutivo sem novos bugs no smoke** (continua streak 3b.7→3b.18 + 3b.20).

Se finding emerger:
- Add à seção "Findings" com reproducer
- Spawn-task para fix ou aceitar como limitação
- Update CLAUDE.md row do 3b.21 com finding noted
