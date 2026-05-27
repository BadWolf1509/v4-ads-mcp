# Phase 3b.37 — manual smoke runbook (`audit_orphan_smart_actions`)

**Purpose:** Validar Sprint 3b.37 — nova tool `audit_orphan_smart_actions` (57ª MCP tool) que detecta ConversionActions ENABLED com zero activity (`metrics.all_conversions == 0.0`) em window LAST_30_DAYS (default). Pre-cleanup decision tool: gestor identifica tracking pixels obsoletos, ações de campanhas removidas, conversion actions criadas em testes que continuam ENABLED sem trackar nada útil — usa output como input pra pause/remove decision. Output flat list ordenada por `(category, origin, name)` ASC pra agrupar visualmente. Filtros server-side hardcoded: `status=ENABLED`. Pure aggregator + wrapper sobre 1 GAQL query em `conversion_action` (padrão Sprint 3b.30/3b.31/3b.33/3b.35/3b.36). ICE 288, cleanup recurring ConversionActions dogfood MO-JP 19/05.

**Operator:** wellinton.ribeiro@v4company.com
**Account principal:** `7862230676` Mestre da Obra JP (production V4 — caso real cleanup recurring ConversionActions)
**Account secundária:** `7455088726` ML Antiguidades (e-commerce, PURCHASE category — T5 cross-vertical validation)

**Spec:** `docs/superpowers/specs/2026-05-21-sprint-3b-37-audit-orphan-smart-actions-design.md`
**Plan:** `docs/superpowers/plans/2026-05-21-sprint-3b-37-audit-orphan-smart-actions.md`
**Dogfood source:** `docs/operacao/dogfood-2026-05-19-mestre-da-obra-jp-cleanup-massivo.md` (#12 backlog, ICE 288)

> **Escopo V0 confirmado:**
> - Input: `customer_id` (req, pattern `^[0-9]{10}$`) + `category` (optional, enum 13 V4 categories) + `limit` (default 100, max 500) + `date_range` preset OR `start_date`+`end_date` custom
> - Output: `customer_id` + `date_range_resolved` + `filters_applied` echo + `total_orphans` + `truncated` + `returned_count` + `orphans[]` flat list (7 fields per entry)
> - Definição orphan V0: `all_conversions == 0.0` (zero conversion activity, semantic simples)
> - Window default: `LAST_30_DAYS`
> - Sort: `category ASC, origin ASC, name ASC` (stable visual grouping)
> - Truncation pattern F22: `truncated=true` se `total_orphans > limit`, `returned_count` reflete actual array length
> - Server-side hardcoded: `WHERE status='ENABLED'` (+ optional category)
> - `audit_this_call=True` (sensitive read, lista ConversionActions config completa)
> - `limit` default 100 (lição 3b.36 — não 200, evitar MCP cap overflow)
> - Tool count: 56 → **57**
> - F46 imune (não usa change_event)

## Production URL

`https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app`

## Pre-flight

- [ ] Deploy lands successfully (CI + Deploy green em commit final A1/A2/A3/A4)
- [ ] Service `/health` returns 200 (`{"status":"ok","version":"0.1.0"}`)
- [ ] Tool `audit_orphan_smart_actions` registered (test_registered_tool_count_matches_files_on_disk 57==57 PASS)
- [ ] Pre-push gate `python scripts/check_pre_push.py` 5/5 PASS
- [ ] Schema regression `test_no_composition_keywords_in_any_schema` passa
- [ ] Unit tests `tests/unit/test_flag_orphan_smart_actions.py` 8/8 PASS (pure module algorithm)
- [ ] Unit tests `tests/unit/test_audit_orphan_smart_actions_queries.py` 5/5 PASS (GAQL builder + boundary parser)
- [ ] Integration tests `tests/integration/test_audit_orphan_smart_actions.py` 3/3 PASS
- [ ] MCP Inspector / Claude client conectado à URL de produção e enxerga `audit_orphan_smart_actions` na tool list

Production revisions: `v4-ads-mcp-XXXXX-xxx` (preencher após deploy final).

## Smoke results

Preencher conforme execução. Marcar resultado final no fim do arquivo.

| # | Test | Result | Notes |
|---|---|---|---|
| T1 | Default LAST_30_DAYS panorâmico em MO-JP | ⬜ pending | |
| T2 | `category=CONTACT` filter em MO-JP | ⬜ pending | |
| T3 | Custom date range em MO-JP (`start_date`+`end_date`) | ⬜ pending | |
| T4 | `limit=5` truncation em MO-JP (conta com 10+ orphans) | ⬜ pending | |
| T5 | `category=PURCHASE` em ML Antiguidades | ⬜ pending | |
| T6 | Caso real cleanup ConversionActions MO-JP recurring | ⬜ pending | |

**Effective result:** N/6 PASS + Y DEFERRED

### F-findings emerged

_Preencher durante smoke. Template: `**F## (SEV)** — <symptom>. Fix: <plan>. Family: <bug class>.`_

Se zero F-findings: documentar explicitly "Zero F-findings novos. Sprint clean."

### Sign-off

- [ ] Pre-push gate 5/5 PASS
- [ ] Spec compliance + code quality reviewers APPROVED (A1, A2, A3)
- [ ] Production `/health` 200 (revisão final)
- [ ] T1, T2, T3, T6 PASS em MO-JP (cenários determinísticos com conta real)
- [ ] T4 PASS ou DEFERRED (env limitation se MO-JP <10 orphans — threshold ajustável)
- [ ] T5 PASS ou DEFERRED (env limitation se ML PURCHASE all_conversions>0 — e-commerce ativo)
- [ ] CLAUDE.md sprint counter atualizado (3b.36 → 3b.37) + tool count 56 → 57
- [ ] sprint-history.md updated com entry Sprint 3b.37
- [ ] findings-catalog.md atualizado se F-findings emergiram (`/findings-add` skill)
- [ ] Tool count 57 confirmado em produção (test_registered_tool_count_matches_files_on_disk 57==57)

---

## Pre-smoke setup

### Step 1: Sanity check no MCP client

Conectar Claude/Inspector à URL de produção (`https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app`) e verificar que `audit_orphan_smart_actions` aparece na lista de tools com parâmetros corretos:

```
# Introspect — esperar ver audit_orphan_smart_actions com:
# - customer_id required (pattern ^[0-9]{10}$)
# - category optional (enum: DEFAULT, PAGE_VIEW, PURCHASE, SIGNUP, SUBMIT_LEAD_FORM,
#                     BOOK_APPOINTMENT, REQUEST_QUOTE, GET_DIRECTIONS, OUTBOUND_CLICK,
#                     CONTACT, ENGAGEMENT, STORE_VISIT, STORE_SALE)
# - limit optional (integer, default 100, max 500)
# - date_range optional (enum: LAST_7_DAYS, LAST_14_DAYS, LAST_30_DAYS, LAST_90_DAYS)
# - start_date, end_date optional (YYYY-MM-DD, pattern ^\d{4}-\d{2}-\d{2}$)
# - additionalProperties: false
```

Se `audit_orphan_smart_actions` não aparece ou tool count ainda 56, deploy não landed — abortar smoke.

### Step 2: Reference numbers pré-smoke MO-JP

Capturar baseline raw via `run_gaql` direto pra validação cruzada em T1/T2/T4/T6:

```
# Baseline orphans (ConversionActions ENABLED com zero conversions) em MO-JP LAST_30_DAYS
SELECT
  conversion_action.id,
  conversion_action.name,
  conversion_action.category,
  conversion_action.origin,
  conversion_action.primary_for_goal,
  conversion_action.status,
  metrics.all_conversions
FROM conversion_action
WHERE segments.date DURING LAST_30_DAYS
  AND conversion_action.status = 'ENABLED'
ORDER BY conversion_action.category ASC, conversion_action.origin ASC, conversion_action.name ASC
```

Conta esperada: MO-JP `7862230676`. Anotar:
- **Total de ConversionActions ENABLED** (esperado: 20-50 actions baseado em dogfood 19/05)
- **Total de orphans** (subset com `all_conversions == 0.0`, esperado: 10+ pra T4 truncation funcionar — se <10, T4 DEFERRED ou ajustar threshold)
- Lista de `category` distintos (anotar quantos CONTACT actions pra T2 filter — mínimo 2 esperado)
- Verificar primeiros 5 entries: nomes + categories + origins (pra cross-validate T1 ordering)

```
# Count rápido de orphans por category em MO-JP
SELECT
  conversion_action.category,
  conversion_action.name,
  metrics.all_conversions
FROM conversion_action
WHERE segments.date DURING LAST_30_DAYS
  AND conversion_action.status = 'ENABLED'
```

Anotar count total + breakdown por category. Se MO-JP tem <10 orphans em LAST_30_DAYS, T4 DEFERRED (não tem volume pra truncar em limit=5) ou substituir por `limit=3` em conta com 6+ orphans.

### Step 3: Reference numbers pré-smoke ML Antiguidades

```
# Baseline orphans PURCHASE em ML Antiguidades (e-commerce — esperado activity > 0 OR poucos orphans)
SELECT
  conversion_action.id,
  conversion_action.name,
  conversion_action.category,
  conversion_action.origin,
  conversion_action.status,
  metrics.all_conversions
FROM conversion_action
WHERE segments.date DURING LAST_30_DAYS
  AND conversion_action.status = 'ENABLED'
  AND conversion_action.category = 'PURCHASE'
```

Conta `7455088726`. Anotar:
- Total de PURCHASE actions ENABLED em ML
- Quantos têm `all_conversions == 0.0` (orphans candidates)
- Se TODOS os PURCHASE actions tem `all_conversions > 0`: T5 DEFERRED (e-commerce ativo, sem orphans) — possível PASS com `total_orphans=0` mas operationally trivial

### Step 4: Identificar category target pra T2

Do baseline Step 2, confirmar que MO-JP tem mínimo 2 CONTACT actions com `all_conversions == 0.0`:

```
# CONTACT orphans em MO-JP
SELECT
  conversion_action.id,
  conversion_action.name,
  conversion_action.origin,
  metrics.all_conversions
FROM conversion_action
WHERE segments.date DURING LAST_30_DAYS
  AND conversion_action.status = 'ENABLED'
  AND conversion_action.category = 'CONTACT'
```

Esperado em MO-JP: tracking pixels Whatsapp antigos, formulários removidos, etc. Anotar count. Se zero CONTACT orphans, T2 substituir por outra category com volume (ex.: `SUBMIT_LEAD_FORM`, `PAGE_VIEW`).

### Step 5: Identificar date window pra T3

Pra T3 custom range, escolher window que não seja LAST_30_DAYS preset. Opções:
- **LAST_14_DAYS equivalente:** `start_date = today - 13 days`, `end_date = today`
- **Quinzena anterior:** `start_date = today - 30 days`, `end_date = today - 16 days`

Documentar window escolhido na T3 tool call.

---

## Test T1 — Default LAST_30_DAYS panorâmico em MO-JP

**Setup:** Use case primário — gestor quer scan account-wide pra detectar TODAS as orphan ConversionActions em 30 dias. Defaults aplicados: `date_range=LAST_30_DAYS`, `limit=100`, sem `category` filter.

**Tool call:**

```
audit_orphan_smart_actions(
  customer_id="7862230676"
)
```

**Expected output (shape):**

```json
{
  "customer_id": "7862230676",
  "date_range_resolved": {
    "start": "2026-04-21",
    "end": "2026-05-20",
    "days": 30
  },
  "filters_applied": {
    "category": null,
    "limit": 100
  },
  "total_orphans": N,
  "truncated": false,
  "returned_count": N,
  "orphans": [
    {
      "conversion_action_id": "...",
      "name": "...",
      "category": "CONTACT" | "PURCHASE" | "...",
      "origin": "WEBSITE" | "GOOGLE_ADS_CALL_FROM_ADS" | "...",
      "primary_for_goal": true | false,
      "status": "ENABLED",
      "all_conversions": 0.0
    },
    /* sorted category ASC, origin ASC, name ASC */
  ]
}
```

**Validação:**

- [ ] Response tem `customer_id` = `"7862230676"`
- [ ] `date_range_resolved.days` == 30 (LAST_30_DAYS default)
- [ ] `date_range_resolved.start` + `end` formato YYYY-MM-DD
- [ ] `filters_applied.category` = `null` (sem filter)
- [ ] `filters_applied.limit` = 100 (default)
- [ ] `total_orphans` é integer >= 0
- [ ] `total_orphans` bate com baseline GAQL do Step 2 (subset com `all_conversions == 0.0`)
- [ ] `truncated` = `false` (se total <= 100)
- [ ] `returned_count` == `len(orphans)` == `total_orphans` (sem truncation)
- [ ] `orphans[]` ordenado: validar primeiros 3 entries têm `category` ASC (e dentro do mesmo category, `origin` ASC; dentro do mesmo origin, `name` ASC)
- [ ] Cada entry: TODAS as 7 fields presentes (`conversion_action_id`, `name`, `category`, `origin`, `primary_for_goal`, `status`, `all_conversions`)
- [ ] Cada entry tem `all_conversions == 0.0` (definição orphan strict)
- [ ] Cada entry tem `status: "ENABLED"` (server-side filter ativo)
- [ ] `category` em whitelist V4 13 valores (proto-plus `.name` access, Sprint 3b.7 lesson) — categories fora V4 (ex.: PHONE_CALL_LEAD se aparecer) são aceitas no output mas anotadas como nota
- [ ] `origin` é string non-empty (`.name` resolution, sem integer raw)
- [ ] Audit_log entry criada (verificar via `/admin/audit` ou DB) — esperar 1 entry (`audit_orphan_smart_actions`)
- [ ] Rate_counter +1

**Result:** ⬜ pending

---

## Test T2 — `category=CONTACT` filter em MO-JP

**Setup:** Use case focado — gestor quer cleanup apenas CONTACT actions (Whatsapp, formulários, telefone). Tool deve restringir scan apenas àquela category via GAQL `WHERE conversion_action.category = 'CONTACT'`.

**Tool call:**

```
audit_orphan_smart_actions(
  customer_id="7862230676",
  category="CONTACT"
)
```

**Expected output (shape):**

```json
{
  "customer_id": "7862230676",
  "date_range_resolved": {"start": "2026-04-21", "end": "2026-05-20", "days": 30},
  "filters_applied": {
    "category": "CONTACT",
    "limit": 100
  },
  "total_orphans": N (apenas CONTACT category),
  "truncated": false,
  "returned_count": N,
  "orphans": [
    /* TODAS as entries têm category=CONTACT */
  ]
}
```

**Validação:**

- [ ] `filters_applied.category` echo correto (`"CONTACT"`)
- [ ] `total_orphans` <= T1 total (subset filtrado por category)
- [ ] `total_orphans` bate com count GAQL específico CONTACT (Step 4)
- [ ] **Crítico:** TODAS as entries em `orphans[]` têm `category == "CONTACT"`
- [ ] Nenhuma entry com `category` diferente do filtrado
- [ ] Cada entry mantém `status: "ENABLED"` + `all_conversions == 0.0`
- [ ] Ordering ainda por `(category, origin, name)` ASC (apenas 1 category, então `origin ASC + name ASC` matters)
- [ ] Audit_log +1 entry com `params_summary.category: "CONTACT"` capturado
- [ ] Rate_counter +1

**Fallback se MO-JP tem zero CONTACT orphans:**
- Substituir por outra category com volume confirmado via Step 2 (ex.: `SUBMIT_LEAD_FORM`, `PAGE_VIEW`)
- Documentar substituição: "category atualizada de `CONTACT` para `<new>` — original tinha 0 orphans em LAST_30_DAYS"

**Result:** ⬜ pending

---

## Test T3 — Custom date range em MO-JP

**Setup:** Validar que `start_date` + `end_date` overrides `date_range` preset. Window escolhido em Step 5 (ex.: quinzena anterior). Verifica honra do `resolve_date_window` helper (`_common.py`, Sprint 3b.20).

**Tool call:**

```
audit_orphan_smart_actions(
  customer_id="7862230676",
  start_date="2026-05-01",
  end_date="2026-05-14"
)
```

*(Substituir datas pelo window escolhido no Step 5 — exemplo acima usa primeiros 14 dias de maio.)*

**Expected output (shape):**

```json
{
  "customer_id": "7862230676",
  "date_range_resolved": {
    "start": "2026-05-01",
    "end": "2026-05-14",
    "days": 14
  },
  "filters_applied": {
    "category": null,
    "limit": 100
  },
  "total_orphans": N (apenas do window 14d),
  ...
}
```

**Validação:**

- [ ] `date_range_resolved.start` == `"2026-05-01"` (echo input)
- [ ] `date_range_resolved.end` == `"2026-05-14"` (echo input)
- [ ] `date_range_resolved.days` == 14 (cálculo: `end - start + 1` inclusive)
- [ ] **Crítico:** window honored — NÃO sobrepoe LAST_30_DAYS default
- [ ] `total_orphans` reflete actions orphan no window específico (pode ser maior ou menor que T1 dependendo do período — actions com conversões em 30d mas zero em 14d aparecem aqui)
- [ ] Schema aceita ambos `start_date` + `end_date` em formato YYYY-MM-DD
- [ ] Cada entry mantém invariants (status ENABLED, all_conversions==0.0)
- [ ] Audit_log +1 entry com `params_summary.date_window: "2026-05-01 to 2026-05-14"`

**Validação adicional (resolve_date_window correctness):**
- [ ] Se window for 1 dia (`start == end`): `days == 1` (inclusive math)
- [ ] Se window for 30 dias completos: `days == 30`

**Result:** ⬜ pending

---

## Test T4 — `limit=5` truncation em MO-JP (conta com 10+ orphans)

**Setup:** Validar truncation pattern F22 (Sprint 3b.23 lineage). MO-JP confirmado pelo Step 2 ter 10+ orphans em LAST_30_DAYS. Tool deve retornar 5 entries + `truncated=true` + `total_orphans` reflete count TOTAL pre-truncate.

**Tool call:**

```
audit_orphan_smart_actions(
  customer_id="7862230676",
  limit=5
)
```

**Expected output (shape):**

```json
{
  "customer_id": "7862230676",
  "date_range_resolved": {"start": "...", "end": "...", "days": 30},
  "filters_applied": {
    "category": null,
    "limit": 5
  },
  "total_orphans": 10+ (count completo da conta),
  "truncated": true,
  "returned_count": 5,
  "orphans": [
    /* exatamente 5 entries, primeiros 5 pelo sort */
  ]
}
```

**Validação:**

- [ ] `filters_applied.limit` == 5 (echo input)
- [ ] `total_orphans` >= 6 (caso contrário truncation não disparou — invalid test)
- [ ] **Crítico:** `truncated == true`
- [ ] **Crítico:** `returned_count == 5`
- [ ] `len(orphans)` == 5 (array length matches `returned_count`)
- [ ] **Crítico:** `total_orphans > returned_count` (truncation real)
- [ ] Entries são os 5 PRIMEIROS pelo sort `(category, origin, name)` ASC (validar comparando com T1 primeiros 5)
- [ ] Audit_log +1 entry com `params_summary.limit: 5`

**Fallback se MO-JP tem <10 orphans:**
- Ajustar `limit` pra valor menor: se MO-JP tem 7 orphans, usar `limit=3` (forces truncate de 7→3)
- Se MO-JP tem <6 orphans total: T4 DEFERRED — env limitation, conta sem volume pra truncar
- Documentar: "T4 DEFERRED — MO-JP tem apenas X orphans em LAST_30_DAYS (<6). Truncation testada via unit test `test_truncation_limit_exceeded` (50 rows + limit=10)."

**Result:** ⬜ pending

---

## Test T5 — `category=PURCHASE` em ML Antiguidades

**Setup:** ML Antiguidades é e-commerce ativo — PURCHASE actions geralmente recebendo conversões reais. Esperado: output pequeno (0-3 orphans) OR empty. Valida que tool funciona em conta cross-vertical + caso "category produtiva" (e-commerce com PURCHASE tracking ativo). Verificação implícita: GAQL category filter funciona em conta diferente do MO-JP.

**Tool call:**

```
audit_orphan_smart_actions(
  customer_id="7455088726",
  category="PURCHASE"
)
```

**Expected output (shape):**

```json
{
  "customer_id": "7455088726",
  "date_range_resolved": {"start": "...", "end": "...", "days": 30},
  "filters_applied": {
    "category": "PURCHASE",
    "limit": 100
  },
  "total_orphans": 0-3 (esperado pequeno em e-commerce ativo),
  "truncated": false,
  "returned_count": 0-3,
  "orphans": [
    /* possivelmente [] OR poucas entries PURCHASE com all_conversions=0 */
  ]
}
```

**Validação:**

- [ ] `customer_id` == `"7455088726"`
- [ ] `filters_applied.category` == `"PURCHASE"`
- [ ] `total_orphans` < 5 (esperado em e-commerce ativo — se >20, DEFERRED ou investigar)
- [ ] `truncated == false` (sem necessidade de truncar)
- [ ] `returned_count == total_orphans == len(orphans)` (consistência)
- [ ] Shape válido mesmo se `orphans == []` (empty list, não null)
- [ ] Se houver entries: TODAS têm `category == "PURCHASE"` + `all_conversions == 0.0`
- [ ] Output bate com baseline GAQL do Step 3
- [ ] Audit_log +1 entry

**Fallback se ML Antiguidades tem TODOS PURCHASE actions com `all_conversions > 0`:**
- T5 PASS com `total_orphans == 0` — operational validation que e-commerce está saudável
- Anotar: "T5 PASS — ML PURCHASE 100% productive (zero orphans). E-commerce signal positivo."

**Fallback se ML inesperadamente tem >20 PURCHASE orphans:**
- T5 **DEFERRED** — env limitation, ML PURCHASE com volume incomum
- Anotar: "T5 DEFERRED — ML PURCHASE retornou X orphans (esperado <5 em e-commerce ativo). Pattern F41/F45. Coverage via unit `test_filter_keeps_zero_conversions`."

**Result:** ⬜ pending *(possível PASS com 0 orphans OR DEFERRED)*

---

## Test T6 — Caso real cleanup ConversionActions MO-JP recurring

**Setup:** Reproduz workflow recurring V4 — dogfood 2026-05-19 cleanup massivo MO-JP. Wellington periodicamente identifica ConversionActions orphan (tracking pixels obsoletos, ações de campanhas removidas) pra pause/remove. Tool deve consolidar workflow (antes: `get_conversion_actions` → query manual por action → mental filter → decision) em 1 call retornando lista actionable.

**Tool call:**

```
audit_orphan_smart_actions(
  customer_id="7862230676"
)
```

*(Mesma call que T1 — diferença é foco da validação operacional, não shape.)*

**Expected output (operational interpretation):**

```json
{
  "total_orphans": N (N >= 5 esperado em MO-JP recurring),
  "orphans": [
    /* ConversionActions ENABLED com zero conversions:
       - Tracking pixels Whatsapp antigos (CONTACT/WEBSITE)
       - Formulários removidos (SUBMIT_LEAD_FORM/WEBSITE)
       - Conversion actions criadas em testes (PAGE_VIEW/WEBSITE)
       - Ações de campanhas pausadas faz tempo
    */
  ]
}
```

**Validação:**

- [ ] `total_orphans >= 5` (MO-JP é conta production V4 com history de cleanup recurring — esperado volume)
- [ ] Pelo menos 3 entries diferentes em `orphans[]` (sample de variedade)
- [ ] Cada entry tem `name` realista (não placeholder, não vazio) — nomes legíveis tipo "Whatsapp - Antigo", "Form - Removido", "Pixel teste"
- [ ] Cada entry tem `category` + `origin` populated (não vazios)
- [ ] Category distribution: pelo menos 2 categories distintas (CONTACT + outras) — sugere diversidade real
- [ ] **Insight operacional:** Wellington pode usar output como input pra `update_conversion_action({customer_id, conversion_action_id, status="PAUSED"})` (mutate tool existente). ConversionActions listadas são candidates legítimas pra pause. Tool entrega valor real (cleanup decision em 1 call vs ~10 queries manuais).
- [ ] Audit_log +1 entry

**Validação cross-tool (cleanup workflow real):**

Após T6, simular workflow next-step (não executar mutate, só verificar viabilidade):

- [ ] Capturar `conversion_action_id` de 1 orphan do output
- [ ] Confirmar via `get_conversion_actions` que mesma action retorna `all_conversions=0` em LAST_30_DAYS
- [ ] Mental model: gestor pode passar `conversion_action_id` do output pra `update_conversion_action({customer_id, conversion_action_id: <id>, status: "PAUSED"})` next call (mutate com CONFIRM token blast radius)

**Fallback se MO-JP retorna <5 orphans em LAST_30_DAYS:**
- Provavelmente Wellington fez cleanup recente — conta "limpa" temporariamente
- T6 **PASS com nota:** "Workflow validado, count baixo confirma cleanup recente. Re-run em sprint próxima com window LAST_90_DAYS (`date_range=LAST_90_DAYS`) pra recapturar volume histórico."
- Alternativa: rodar com `date_range=LAST_90_DAYS` pra forçar volume

**Result:** ⬜ pending

---

## Per-value empirical probe (Sprint 3b.19A.1 convention)

**Probe 1: enum `date_range`** — Schema declara whitelist 4 valores. Como tool é **read-only puro**, probe verifica que cada preset é aceito + resolvido corretamente pelo `resolve_date_window` (Sprint 3b.20):

| # | Enum value | Expected `days` | Result |
|---|---|---|---|
| P1 | `LAST_7_DAYS` | 7 | ⬜ pending |
| P2 | `LAST_14_DAYS` | 14 | ⬜ pending |
| P3 | `LAST_30_DAYS` | 30 | ⬜ pending (coverage via T1/T2/T4/T6) |
| P4 | `LAST_90_DAYS` | 90 | ⬜ pending |
| P5 | `LAST_60_DAYS` (NOT_IN_WHITELIST) | Schema reject (HTTP 400) | ⬜ pending |

**Tool calls (probe rápido date_range):**

```
# P1
audit_orphan_smart_actions(customer_id="7862230676", date_range="LAST_7_DAYS")
# expect: date_range_resolved.days == 7

# P2
audit_orphan_smart_actions(customer_id="7862230676", date_range="LAST_14_DAYS")
# expect: date_range_resolved.days == 14

# P4
audit_orphan_smart_actions(customer_id="7862230676", date_range="LAST_90_DAYS")
# expect: date_range_resolved.days == 90

# P5 (negative test — schema rejection)
audit_orphan_smart_actions(customer_id="7862230676", date_range="LAST_60_DAYS")
# expect: schema validation error (HTTP 400 or MCP equivalent)
```

**Probe 2: enum `category`** — Schema declara whitelist 13 V4 valores. Cada deve ser aceito pelo MCP schema validation (não verificamos que cada category tem orphans, apenas que aceita input + passa ao GAQL builder):

| # | Category value | Expected | Result |
|---|---|---|---|
| C1 | `DEFAULT` | Accept + GAQL emits `category='DEFAULT'` | ⬜ pending |
| C2 | `PAGE_VIEW` | Accept | ⬜ pending |
| C3 | `PURCHASE` | Accept (coverage via T5) | ⬜ pending |
| C4 | `SIGNUP` | Accept | ⬜ pending |
| C5 | `SUBMIT_LEAD_FORM` | Accept | ⬜ pending |
| C6 | `BOOK_APPOINTMENT` | Accept | ⬜ pending |
| C7 | `REQUEST_QUOTE` | Accept | ⬜ pending |
| C8 | `GET_DIRECTIONS` | Accept | ⬜ pending |
| C9 | `OUTBOUND_CLICK` | Accept | ⬜ pending |
| C10 | `CONTACT` | Accept (coverage via T2) | ⬜ pending |
| C11 | `ENGAGEMENT` | Accept | ⬜ pending |
| C12 | `STORE_VISIT` | Accept | ⬜ pending |
| C13 | `STORE_SALE` | Accept | ⬜ pending |
| C14 | `PHONE_CALL_LEAD` (NOT_IN_WHITELIST V4) | Schema reject (HTTP 400) | ⬜ pending |
| C15 | `INVALID_CATEGORY` (fictional) | Schema reject (HTTP 400) | ⬜ pending |

**Tool calls (probe rápido category — 1 call per category aceita + 2 negative tests):**

```
# Aceitas — 1 call por valor (response shape válido, total_orphans pode ser 0)
audit_orphan_smart_actions(customer_id="7862230676", category="DEFAULT")
audit_orphan_smart_actions(customer_id="7862230676", category="PAGE_VIEW")
# ... repetir pra cada C1-C13

# C14 negative (não está no whitelist V4 13 valores)
audit_orphan_smart_actions(customer_id="7862230676", category="PHONE_CALL_LEAD")
# expect: schema validation error (HTTP 400)

# C15 negative (category fictional)
audit_orphan_smart_actions(customer_id="7862230676", category="INVALID_CATEGORY")
# expect: schema validation error (HTTP 400)
```

**Validação por probe:**

date_range:
- [ ] P1: `date_range_resolved.days == 7`, response shape correto
- [ ] P2: `date_range_resolved.days == 14`, response shape correto
- [ ] P3: cobertura herdada de T1/T2/T4/T6 (já validado em testes principais)
- [ ] P4: `date_range_resolved.days == 90`, response shape correto
- [ ] P5: schema reject `LAST_60_DAYS` (não está no enum whitelist)

category:
- [ ] C1-C13: cada uma das 13 V4 categorias aceita (response shape válido)
- [ ] **Crítico:** GAQL emite `conversion_action.category = '<value>'` para cada (validar via 1 sample, ex.: capturar query gerada em C5/SUBMIT_LEAD_FORM)
- [ ] Output `filters_applied.category` echo correto pra cada call
- [ ] C14: schema reject `PHONE_CALL_LEAD` (Sprint 3b.35 finding — Google retorna esta category mas V4 whitelist NÃO inclui pra INPUT — design correto, output mostra category bruta)
- [ ] C15: schema reject `INVALID_CATEGORY`

**Critério PASS do probe completo:** 4 presets date_range aceitos + 1 fora whitelist rejeitado + 13 V4 categories aceitas + 2 fora whitelist rejeitadas.

**Convention:** every value in tool schema whitelist MUST be empirically validated. Bug history: F17/F18/F19/F25/F27/F31/F32/F34/F36/F44 — design-gap-via-SDK-ambiguity. Pra esta tool (read-only com 2 enum whitelists), validation = cada valor aceito + cada não-whitelist rejeitado em schema layer.

**Otimização probe:** se ficar oneroso rodar 13 calls de category, agrupar em batch — alternativamente confirmar via schema introspection (`tools/list` mostra enum) + 3 sample calls (DEFAULT + STORE_SALE no end of whitelist + 1 negative) pra reduzir wear. Documentar approach escolhido em smoke notes.

---

## V4 invariants validation

| Invariant | Aplicável | Enforcement | How smoke verifies |
|---|---|---|---|
| country_code = BR | N/A | N/A — tool não toca geo data | — |
| language_code = pt-BR | ✅ Description | Tool description string PT-BR ("Detecta ConversionActions orphan...", "Pre-cleanup decision tool...", "tracking pixels obsoletos...") | Pre-flight: inspector mostra description PT-BR |
| currency_code = BRL | N/A | N/A — tool não retorna cost (conversion_action sem cost metric — vive em campaign_view) | — |
| timezone = -03:00 | N/A | N/A — tool não retorna timestamps em response shape V0; date_range usa GAQL `segments.date` que respeita account timezone server-side | — |
| LGPD consent | N/A | Read-only sem envio de PII; ConversionActions config já era exposta via outros tools (`get_conversion_actions`, `run_gaql`) | Audit_log captura quem acessou (Wellington) — herdado de `run_report(audit_this_call=True)` |
| Schema whitelist V4 categories (3b.19A) | ✅ Input | Enum `category` 13 V4 valores (idêntica audit_goal_attribution 3b.35) | Per-value probe C1-C15 |
| Schema whitelist date_range | ✅ Input | Enum `date_range` 4 valores V4 | Per-value probe P1-P5 |
| status=ENABLED-only filter | ✅ Hardcoded | GAQL `WHERE conversion_action.status = 'ENABLED'` server-side | T1/T6 validam cada entry tem `status: "ENABLED"` exclusively |
| No composition keywords (3b.19B.1) | ✅ Schema | Schema sem `oneOf/allOf/anyOf` em qualquer nesting level | Regression `test_no_composition_keywords_in_any_schema` (pre-push) |
| F22 truncation pattern (3b.23) | ✅ Output | `total_orphans` POST-filter + `truncated: bool` + `returned_count <= total_orphans` | T4 valida `truncated=true` quando exceeds limit |
| F46 imune | ✅ Architecture | Não usa `change_event` (GAQL `conversion_action` orthogonal); `gaql_date_clause` from `_common.py` é date semantics independente | N/A — implicit immunity |
| limit default 100 (lição 3b.36) | ✅ Schema | `default: 100`, max 500 (não 200 — reduce MCP cap overflow risk) | Pre-flight: inspector mostra `default: 100`; T1 valida `filters_applied.limit == 100` quando omit |
| Sort stable (category, origin, name) ASC | ✅ Output | Pure module `orphans.sort(key=lambda o: (o.category, o.origin, o.name))` | T1 valida primeiros 3 entries em ordem ASC |
| Float comparison strict zero | ✅ Algorithm | Pure module `if r.all_conversions == 0.0` (excludes fractional 0.5) | Unit `test_filter_excludes_fractional_conversions` (coverage) + T1 valida cada entry tem exact `0.0` |

---

## Cleanup post-smoke

Não há cleanup necessário:
- `audit_orphan_smart_actions` é read-only puro (zero mutations)
- 1 GAQL call em `conversion_action` por chamada tool
- Audit_log entries ficam permanentes (rastreio histórico, `audit_this_call=True`)
- Rate_counter incrementa normalmente: 6 testes principais × 1 call + 4 probes date_range × 1 call + ~3-13 probes category × 1 call (depende abordagem) = 13-23 GAQL calls total no smoke

---

## Notas pra Wellington pós-smoke

1. **Uso real após smoke:** workflow cleanup ConversionActions recurring. Cadência sugerida: Wellington roda `audit_orphan_smart_actions(customer_id=<conta>)` mensalmente (ou após batch de testes/criação de conversion actions). Output identifica candidates pra pause/remove. Decisão informada: orphans muito antigos (>90d) candidates fortes pra remove; orphans recentes (<14d) podem ser actions de campanhas em ramp-up — investigar antes de pausar.
2. **Workflow combinado:** Tool retorna `conversion_action_id` no array. Gestor pode passar id direto pra `update_conversion_action({customer_id, conversion_action_id, status: "PAUSED"})` (mutate existente) numa segunda call. Atômico em batch via `apply_change(confirm_token=...)` se mutate exigir confirmação.
3. **Se T4 DEFERRED (MO-JP <10 orphans):** unit test `test_truncation_limit_exceeded` (50 rows + limit=10) garante cobertura algorítmica. DEFERRED é env limitation (pattern F41/F45), não bug.
4. **Se T5 PASS com 0 orphans:** ML Antiguidades PURCHASE saudável — sinal positivo cleanup do e-commerce. Documentar como baseline cross-vertical (B2C/e-commerce difere de B2C/serviços tipo MO-JP).
5. **Se T6 retorna <5 orphans:** PROVÁVEL que Wellington fez cleanup recente. Re-run com `date_range=LAST_90_DAYS` pra recapturar volume histórico OR aceitar como sinal positivo de hygiene da conta.
6. **Category whitelist edge case (PHONE_CALL_LEAD):** Sprint 3b.35 finding — Google API retorna `PHONE_CALL_LEAD` category em alguns accounts. V4 schema whitelist NÃO inclui pra INPUT (probe C14 rejeita). Output, no entanto, **mostra a category bruta** vinda do Google (algorithm aceita qualquer category em rows). Design correto: defensive em input, permissive em output. Documentar caso emerja PHONE_CALL_LEAD em T1 orphans output.
7. **V1+ candidates:** cross-ref `campaign_conversion_goal` ("no campaign uses this action" vs "zero conversions"), `min_conversions` threshold (soft orphan: <5 conversions = low-performing), `origin` filter, `include_paused_actions` flag, auto-pause action workflow, reverse-lookup "which campaigns tracked this".
8. **F46 imune:** tool não usa `change_event` → orthogonal ao GAQL BETWEEN end_date midnight bug. Cross-checked no único GAQL query do tool (usa `conversion_action` + `segments.date` DURING/BETWEEN via `gaql_date_clause` que aplica `+1 day` em end_date pós-F46 fix Sprint 3b.34).
9. **Sprint 3b.38+ candidates:** audit_negative_criterion_overlap, audit_assets_parity_between_campaigns, remove_* bundle (delete-via-update_conversion_action+update_keyword status pattern), audit_log gap fix em `run_gaql`/`get_my_audit_log`/`get_my_rate_limit_status`, W2 `verify_campaign_state` (ICE 280). Decisão Wellington baseada em dogfood real.
10. **Tool count:** atualizar CLAUDE.md sprint counter (3b.36 → 3b.37) e sprint-history.md após signoff. Tool count 56 → **57**.
