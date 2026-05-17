# Phase 3b.20 — manual smoke runbook (date_range clarification + search_terms default)

**Purpose:** Verify Sprint 3b.20 fixes em conta real — re-execute relatorio
2026-05-17 finding #1 (custom periods que falharam em MO-JP) + finding #2
(search_terms cap).

**Operator:** wellinton.ribeiro@v4company.com
**Account:** `7862230676` "Mestre da Obra - João Pessoa" (mesma conta exercida
em report 15/05/2026 onde o bug foi descoberto)

## Pre-flight

- [ ] Deploy lands successfully (`gh run watch <id>` shows green Deploy)
- [ ] Service `/health` returns 200
- [ ] Reload MCP client (restart Claude Code session)

Production revision: `<fill-in>`.

## Test T1 — Regression: preset `LAST_7_DAYS` (must not break)

```
get_account_overview(customer_id="7862230676", date_range="LAST_7_DAYS")
```

Expected:
- [ ] Returns `current` + `previous` blocks com `impressions`, `clicks`,
      `cost_brl`, `conversions`, etc populated
- [ ] `period.from` + `period.to` cover last 7 complete days (ending yesterday)
- [ ] No errors

**Result:** ⬜ pending

## Test T2 — Custom period: o caso que falhou no relatorio

Period que falhou em 15/05 (08-14/05). Para reproduzir hoje sem time-travel,
use os 7 dias completos anteriores a ontem:

```
get_account_overview(
  customer_id="7862230676",
  start_date="<8 days ago YYYY-MM-DD>",
  end_date="<2 days ago YYYY-MM-DD>"
)
```

Expected:
- [ ] Returns `current` block com os dados desse range custom
- [ ] `period.from` + `period.to` match the exact dates passed
- [ ] **NO error** "Unknown date_range preset" (the bug from relatorio finding #1)
- [ ] `previous` block compares against the 7 days BEFORE start_date

**Result:** ⬜ pending

## Test T3 — Schema rejection: only start_date informed

```
get_account_overview(customer_id="7862230676", start_date="2026-05-08")
```

Expected:
- [ ] Erro retornado pelo MCP server: schema validation OR
      `resolve_date_window` raises PT-BR `"end_date e obrigatorio quando
      start_date e informado"`

**Result:** ⬜ pending

## Test T4 — Schema rejection: invalid YYYY-MM-DD format

```
get_account_overview(
  customer_id="7862230676",
  start_date="08/05/2026",
  end_date="14/05/2026"
)
```

Expected:
- [ ] Erro retornado pelo MCP server: schema validation rejects `pattern`
      mismatch (DD/MM/YYYY != YYYY-MM-DD)

**Result:** ⬜ pending

## Test T5 — Precedence: both preset and custom range

```
get_account_overview(
  customer_id="7862230676",
  date_range="LAST_30_DAYS",
  start_date="<3 days ago YYYY-MM-DD>",
  end_date="<2 days ago YYYY-MM-DD>"
)
```

Expected:
- [ ] Custom range WINS (response covers the 2-day range, not 30 days)
- [ ] `period.from` + `period.to` match start_date/end_date exactly
- [ ] No warning/error about conflicting inputs (precedence is intentional)

**Result:** ⬜ pending

## Test T6 — Token cap relief: search_terms default 50

```
get_search_terms_report(customer_id="7862230676", date_range="LAST_7_DAYS")
```

(NO `limit` arg — relies on default.)

Expected:
- [ ] Returns top 50 search terms (was 500 before, would exceed token cap)
- [ ] Response size compact enough to fit in single MCP response (no "saved
      to file" overflow message)
- [ ] Sorted by cost_micros DESC

**Result:** ⬜ pending

## Test T7 — Cross-tool sanity check on 2 other retrofitted tools

Pick 2 read tools at random (eg `get_campaign_performance` + `get_funnel_metrics`)
and run each twice — once with preset, once with custom period:

```
get_campaign_performance(customer_id="7862230676", date_range="LAST_14_DAYS")
get_campaign_performance(
  customer_id="7862230676",
  start_date="<14 days ago>",
  end_date="<1 day ago>"
)
```

Expected:
- [ ] Both calls succeed
- [ ] Both return identical date ranges (or near-identical, ±1 day depending
      on how the preset resolves)
- [ ] No "preset rejected" errors

**Result:** ⬜ pending

## Findings

Document any new findings here. If T1-T7 all pass clean, this is the **10th
consecutive sprint sem novos bugs no smoke** (continues 3b.7→3b.18 streak,
broken only by 3b.19A F17/F18 which were design gaps, not regressions).

If a finding emerges:
- Add to "Findings" section here with reproducer
- Spawn-task for fix or document as accepted limitation
- Update CLAUDE.md "Shipped + in production" row to note the finding
