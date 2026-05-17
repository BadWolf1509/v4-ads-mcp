# Phase 3b.20 — manual smoke runbook (date_range clarification + search_terms default)

**Purpose:** Verify Sprint 3b.20 fixes em conta real — re-execute relatorio
2026-05-17 finding #1 (custom periods que falharam em MO-JP) + finding #2
(search_terms cap).

**Operator:** wellinton.ribeiro@v4company.com
**Account:** `7862230676` "Mestre da Obra - João Pessoa" (mesma conta exercida
em report 15/05/2026 onde o bug foi descoberto)

## Pre-flight

- [x] Deploy lands successfully (`gh run watch 26003463648` shows green Deploy in 3m9s)
- [x] Service `/health` returns 200
- [x] Reload MCP client (restart Claude Code session)

Production revision: `v4-ads-mcp-00163-zm6` (smoke run); subsequent docs-only
deploy bumped to a later revision (no runtime change).

## Test T1 — Regression: preset `LAST_7_DAYS` (must not break)

```
get_account_overview(customer_id="7862230676", date_range="LAST_7_DAYS")
```

Expected:
- [x] Returns `current` + `previous` blocks com `impressions`, `clicks`,
      `cost_brl`, `conversions`, etc populated
- [x] `period.from` + `period.to` cover last 7 complete days (ending yesterday)
- [x] No errors

**Result:** ✅ PASS. `period: 2026-05-10..2026-05-16` (correct — 7 complete days
ending yesterday, today 2026-05-17). Current: `impressions=6244, clicks=432,
cost_brl=3136.83, conversions=130.0, roas=0.04`. Previous auto-computed
`2026-05-03..2026-05-09` com `cost_brl=1178.73`. `tracking_warning` PT-BR
disparou em ambos blocos (1:1 placeholder mantido). Preset path zero
regressions.

## Test T2 — Custom period: o caso que falhou no relatorio

Período EXATO que falhou em 15/05 (08-14/05) — reproduzimos pra confirmar fix.

```
get_account_overview(
  customer_id="7862230676",
  start_date="2026-05-08",
  end_date="2026-05-14"
)
```

Expected:
- [x] Returns `current` block com os dados desse range custom
- [x] `period.from` + `period.to` match the exact dates passed
- [x] **NO error** "Unknown date_range preset" (the bug from relatorio finding #1)
- [x] `previous` block compares against the 7 days BEFORE start_date

**Result:** ✅ PASS — **F1 do relatório 2026-05-17 FIXED em produção.**
`period: 2026-05-08..2026-05-14` (exato como passado). Current: `impressions=6223,
clicks=437, cost_brl=3036.62, conversions=131.94, roas=0.04`. **Cifra `cost_brl
3036.62` confere exatamente** com o workaround LAST_7_DAYS que Wellington usou
em 15/05 (relatório seção 1.1 mencionou que caiu por sorte em LAST_7_DAYS pois
today=15/05). Previous: `2026-05-01..2026-05-07` (semana anterior, mesmo tamanho).
Custom periods agora destrava comparativos como "mesma semana mês passado",
"janela 14-30/04 vs 14-30/05", etc — eliminado o bloqueio principal do report
semanal V4.

## Test T3 — Schema rejection: only start_date informed

```
get_account_overview(customer_id="7862230676", start_date="2026-05-08")
```

Expected:
- [x] Erro retornado pelo MCP server: schema validation OR
      `resolve_date_window` raises PT-BR `"end_date e obrigatorio quando
      start_date e informado"`

**Result:** ✅ PASS. MCP server retornou erro estruturado PT-BR exato:
`"end_date e obrigatorio quando start_date e informado."` — vindo de
`InvalidDateRangeError` propagado por `resolve_date_window`. Mensagem clara
sem stack trace exposed, sem confusion. Gestor recebe feedback acionável.

## Test T4 — Schema rejection: invalid YYYY-MM-DD format

```
get_account_overview(
  customer_id="7862230676",
  start_date="08/05/2026",
  end_date="14/05/2026"
)
```

Expected:
- [x] Erro retornado pelo MCP server: schema validation rejects `pattern`
      mismatch (DD/MM/YYYY != YYYY-MM-DD)

**Result:** ✅ PASS. MCP server retornou erro estruturado:
`"Input validation error: '08/05/2026' does not match '^\\d{4}-\\d{2}-\\d{2}$'"`
— jsonschema validation rejeitou no server.py:55 antes mesmo de chegar no
handler. Schema pattern enforcement working. Mensagem aponta o field offending
+ o pattern esperado.

## Test T5 — Precedence: both preset and custom range

```
get_account_overview(
  customer_id="7862230676",
  date_range="LAST_30_DAYS",
  start_date="2026-05-15",
  end_date="2026-05-16"
)
```

Expected:
- [x] Custom range WINS (response covers the 2-day range, not 30 days)
- [x] `period.from` + `period.to` match start_date/end_date exactly
- [x] No warning/error about conflicting inputs (precedence is intentional)

**Result:** ✅ PASS. `period: 2026-05-15..2026-05-16` (custom 2-day range
ganha, NÃO o LAST_30_DAYS preset). `cost_brl=731.91` para 2 dias vs ~R$
14-15k que LAST_30_DAYS teria retornado. Previous auto-computed
`2026-05-13..2026-05-14` (2 dias antes do start_date — mesmo tamanho do
custom). Precedence `resolve_date_window` funciona conforme design,
silenciosamente — sem warning sobre args conflitantes (intencional).

## Test T6 — Token cap relief: search_terms default 50

```
get_search_terms_report(customer_id="7862230676", date_range="LAST_7_DAYS")
```

(NO `limit` arg — relies on default.)

Expected:
- [x] Returns top 50 search terms (was 500 before, would exceed token cap)
- [x] Response size compact enough to fit in single MCP response (no "saved
      to file" overflow message)
- [x] Sorted by cost_micros DESC

**Result:** ✅ PASS — **F2 do relatório 2026-05-17 FIXED em produção.**
Returns exato 50 rows (default novo aplicado). Top row `projecta cost_brl=160.75`,
last row `locadora de andaimes cost_brl=9.93` — sorted DESC por cost. Response
size compact (~25KB), single MCP response, NO overflow message. Narrative
relatório semanal preservada: top spenders, mix conversion-bearing vs zero-conv,
breakdown JPA vs CAB campaigns. Gestor pode usar default sem fricção pra audits
semanais.

## Test T7 — Cross-tool sanity check on 2 other retrofitted tools

```
get_campaign_performance(customer_id="7862230676", date_range="LAST_14_DAYS")
get_campaign_performance(customer_id="7862230676", start_date="2026-05-03", end_date="2026-05-16")
get_funnel_metrics(customer_id="7862230676", date_range="LAST_7_DAYS")
get_funnel_metrics(customer_id="7862230676", start_date="2026-05-10", end_date="2026-05-16")
```

Expected:
- [x] Both calls succeed
- [x] Both return identical date ranges (or near-identical, ±1 day depending
      on how the preset resolves)
- [x] No "preset rejected" errors

**Result:** ✅ PASS. Equivalence validada bit-a-bit:

| Tool | Preset path | Custom path | Match |
|---|---|---|---|
| `get_campaign_performance` LAST_14_DAYS | `2026-05-03..2026-05-16`, 2 campaigns, cost 2194.07+2121.48 | `2026-05-03..2026-05-16`, idem | ✅ identical |
| `get_funnel_metrics` LAST_7_DAYS | `2026-05-10..2026-05-16`, funnel 6244→432→130 | `2026-05-10..2026-05-16`, idem | ✅ identical |

Zero off-by-one entre preset e custom path. Confirma que `resolve_date_window`
roteamento mantém semântica idêntica para datas equivalentes. Validation
cross-tool em 2 tools além do canônico `get_account_overview` (T1+T2+T5).

## Findings

**ZERO new findings.** Todos os 7 testes PASS first try.

Este é o **10º sprint consecutivo sem novos bugs no smoke** (continua streak
3b.7→3b.18, broken only by 3b.19A F17/F18 which were design gaps via SDK
ambiguity, não regressions de pattern). Sprint 3b.20 stabilization-class
sprint (bugfix + ergonomic improvement, zero new tool surface, zero novos
patterns) seguiu padrão Sprint 3b.7 / Sprint P2: clean smoke esperado dado
backward compat + defense-in-depth.

**Real biz value cumulativo do sprint:**
- F1 relatório fixed: gestor pode usar custom periods via Claude (compare
  semana anterior, janelas custom mês a mês, etc) — destrava workflow report
  semanal V4 que era o caso original do report 15/05.
- F2 relatório fixed: search_terms audit semanal cabe em single MCP response,
  sem overhead de ler arquivo paginado (workaround que Wellington tinha que
  usar em 15/05).
- 14 schemas agora explícitos com type+enum+pattern → defesa contra
  regressões via `test_date_range_schemas_are_explicit`.
- `parse_date_range` defensive JSON parse → safety net para edge cases
  futuros (internal callers, future agents que passem dict-como-string).

**Validação técnica importante:** T7 confirmou que preset e custom paths
produzem dados idênticos para a mesma janela — significa que `resolve_date_window`
+ `parse_date_range` são consistentes via ambos os caminhos. Sem off-by-one,
sem timezone drift entre paths.

**Finding #3 do relatório (`get_negative_keywords_audit` sem `created_date`)
deferred para Sprint 3b.21** — não foi escopo desta sprint. Requer investigação
do change_event JOIN (campaign_criterion não expõe creation_time direto).
