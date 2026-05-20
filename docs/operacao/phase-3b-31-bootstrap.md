# Phase 3b.31 — manual smoke runbook (`audit_competitor_keywords`)

**Purpose:** Validar Sprint 3b.31 — nova tool `audit_competitor_keywords` (53ª MCP tool) que detecta gasto em concorrência: keywords positivas ENABLED com text matching competitor brands + search terms entregues no date window com cost. Output: `positive_keywords[]` + `search_terms[]` (sorted cost DESC) + `summary` (total_cost_wasted_brl real) + `suggested_negatives` (EXACT + PHRASE per matched brand). Match: substring case-insensitive. asyncio.gather paralelo em 2 queries (keyword_view + search_term_view). Sempre auditado em ambas calls.

**Operator:** wellinton.ribeiro@v4company.com
**Account:** `1163862076` Nutry (sandbox, low-volume — T1 usa brand "nutry" self-match)

**Spec:** `docs/superpowers/specs/2026-05-20-sprint-3b-31-audit-competitor-keywords-design.md`
**Plan:** `docs/superpowers/plans/2026-05-20-sprint-3b-31-audit-competitor-keywords.md`

> **Escopo V0 confirmado:**
> - Input: `customer_id` (req) + `competitor_brands[]` (3-50 chars cada, 1-20 brands, req) + `date_range` preset OR `start_date+end_date` custom (default LAST_7_DAYS) + `limit` (default 200, max 1000)
> - Output: `positive_keywords[]` + `search_terms[]` + `summary` (counts + truncate flags + `total_cost_wasted_brl`) + `suggested_negatives[]`
> - Match: substring case-insensitive (normalize lowercase + strip)
> - `positive_keywords`: state-based query (sem date filter) — apenas ENABLED + negative=FALSE
> - `search_terms`: date-filtered via search_term_view
> - Suggested negatives: EXACT + PHRASE per brand com hit; brands zero-match omitidas
> - asyncio.gather paralelo em 2 queries; `audit_this_call=True` em ambas
> - Tool count: 52 → **53**

## Pre-flight

- [x] Deploy lands successfully (CI + Deploy green em commit `a01954b`)
- [x] Service `/health` returns 200 (`{"status":"ok","version":"0.1.0"}`)
- [x] Tool `audit_competitor_keywords` registered (test_registered_tool_count_matches_files_on_disk 53==53 PASS)
- [x] Pre-push gate `python scripts/check_pre_push.py` 5/5 PASS
- [x] Schema regression `test_no_composition_keywords_in_any_schema` passa
- [x] Unit tests `tests/unit/test_competitor_analysis.py` 14/14 PASS (commit `24f1903`)
- [x] Unit tests `tests/unit/test_audit_competitor_keywords_query.py` 6/6 PASS (commit `3944d04`)
- [x] Integration tests `tests/integration/test_audit_competitor_keywords.py` 3/3 PASS (commit `a01954b`)

## Smoke results — execution pending Wellington next-session

MCP client desta sessão cacheou tool list pre-deploy → `audit_competitor_keywords` não visível pra controller. Pattern análogo Sprint 3b.30 A5. Wellington executa em nova sessão MCP.

**Confidence em production:**
- ✅ A1 spec + code quality reviewer APPROVED (14/14 reqs + 14/14 tests)
- ✅ A2 combined reviewer APPROVED (6/6 tests + zero issues)
- ✅ A3 mcp-tool-quality-reviewer APPROVED (25/25 checks)
- ✅ A4 integration tests 3/3 PASS + CI green + Deploy green + /health 200
- ✅ 23 testes total cobrindo todos branches do algoritmo

## Smoke results — pendente Wellington

| # | Test | Result | Notes |
|---|---|---|---|
| T1 | brand "nutry" — sanity self-match | ⬜ pending | |
| T2 | brand inexistente "kjadflk" — empty everything | ⬜ pending | |
| T3 | 2 brands [matched, "kjadflk"] — apenas matched em suggested | ⬜ pending | |
| T4 | date_range=LAST_30_DAYS | ⬜ pending | |
| T5 | start_date+end_date custom range | ⬜ pending | |
| T6 | limit=5 — truncation | ⬜ pending | |
| T7 | Empirical match: keyword matched em sandbox | ⬜ pending | Pode ser DEFERRED se Nutry sem match |
| T8 | Schema validation: brand 2-char rejeitada | ⬜ pending | |

## Pre-smoke setup

### Step 1: Sanity check no MCP client

Verificar que `audit_competitor_keywords` aparece na lista de tools disponíveis com parâmetros corretos:

```
# Introspect — esperar ver audit_competitor_keywords com:
# - customer_id required (pattern ^[0-9]{10}$)
# - competitor_brands required (array, items minLength 3, maxLength 50, minItems 1, maxItems 20)
# - date_range optional (enum preset, default LAST_7_DAYS)
# - start_date, end_date optional (YYYY-MM-DD)
# - limit optional (integer 1-1000, default 200)
```

Se `audit_competitor_keywords` não aparece ou tool count ainda 52, deploy não landed — abortar smoke.

### Step 2: Reference numbers pré-smoke

Capturar baseline pra validação cruzada em T7 via `run_gaql`:

```
# Keywords ENABLED com text contendo "nutry" em Nutry
SELECT
  ad_group.id, ad_group.name, campaign.name,
  ad_group_criterion.criterion_id,
  ad_group_criterion.keyword.text,
  ad_group_criterion.keyword.match_type
FROM keyword_view
WHERE ad_group_criterion.status = 'ENABLED'
  AND ad_group_criterion.negative = FALSE
LIMIT 50
```

Anotar:
- Total de keywords ENABLED (esperar volume pequeno em Nutry)
- Quaisquer keywords com text contendo "nutry" (candidatas T7)

```
# Search terms com "nutry" na Nutry sandbox (últimos 7 dias)
SELECT
  search_term_view.search_term,
  ad_group.name, campaign.name,
  metrics.impressions, metrics.clicks, metrics.cost_micros
FROM search_term_view
WHERE segments.date DURING LAST_7_DAYS
LIMIT 50
```

---

## Test T1 — Sanity self-match com brand "nutry"

**Setup:** Positive case mínimo — detectar própria brand da conta Nutry como sanidade de wiring.

**Tool call:**

```
audit_competitor_keywords(
  customer_id="1163862076",
  competitor_brands=["nutry"]
)
```

**Expected output (shape):**

```json
{
  "customer_id": "1163862076",
  "date_range_resolved": {
    "start": "2026-05-13",
    "end": "2026-05-20",
    "days": 8
  },
  "competitor_brands": ["nutry"],
  "summary": {
    "positive_keywords_count": N,
    "positive_keywords_truncated": false,
    "search_terms_count": M,
    "search_terms_truncated": false,
    "total_cost_wasted_brl": X.XX,
    "suggested_negatives_count": 0
  },
  "positive_keywords": [...],
  "search_terms": [...],
  "suggested_negatives": [...]
}
```

*(Self-match: keywords com "nutry" no text são keywords da própria marca. `suggested_negatives_count` pode ser 0 ou 2 conforme existência de matches.)*

Validação:
- [ ] Response tem `customer_id` = `"1163862076"`
- [ ] `date_range_resolved` tem `start`, `end`, `days` >= 7 (LAST_7_DAYS)
- [ ] `competitor_brands` = `["nutry"]` (echo do input)
- [ ] `summary` tem `positive_keywords_count`, `search_terms_count`, `total_cost_wasted_brl`, `suggested_negatives_count` como integers/float
- [ ] `positive_keywords` é array (pode ser `[]`)
- [ ] `search_terms` é array (pode ser `[]`)
- [ ] `suggested_negatives` é array (pode ser `[]`)
- [ ] Se `positive_keywords` não-vazio: cada entry tem `ad_group_id`, `ad_group_name`, `campaign_name`, `keyword_id`, `keyword_text`, `match_type`, `matched_brand`, `status`
- [ ] Se `search_terms` não-vazio: cada entry tem `search_term`, `matched_brand`, `ad_group_name`, `campaign_name`, `impressions`, `clicks`, `cost_brl`
- [ ] Se `suggested_negatives` não-vazio: cada entry tem `text`, `match_type` (EXACT|PHRASE), `reason`
- [ ] Audit_log 2 entries criadas (2 queries = 2 audit calls com `audit_this_call=True`)
- [ ] Rate_counter +2 (2 GAQL calls paralelas)

**Result:** ⬜ pending

---

## Test T2 — Brand inexistente "kjadflk" — empty everything

**Setup:** Brand que certamente não existe em nenhuma keyword ou search term da conta. Valida que tool retorna empty gracefully sem errors.

**Tool call:**

```
audit_competitor_keywords(
  customer_id="1163862076",
  competitor_brands=["kjadflk"]
)
```

**Expected:**

```json
{
  "summary": {
    "positive_keywords_count": 0,
    "positive_keywords_truncated": false,
    "search_terms_count": 0,
    "search_terms_truncated": false,
    "total_cost_wasted_brl": 0.0,
    "suggested_negatives_count": 0
  },
  "positive_keywords": [],
  "search_terms": [],
  "suggested_negatives": []
}
```

Validação:
- [ ] `summary.positive_keywords_count` = 0
- [ ] `summary.search_terms_count` = 0
- [ ] `summary.total_cost_wasted_brl` = 0.0
- [ ] `summary.suggested_negatives_count` = 0
- [ ] `positive_keywords` = `[]`
- [ ] `search_terms` = `[]`
- [ ] `suggested_negatives` = `[]`
- [ ] Sem erro / exception (empty é comportamento correto)

**Result:** ⬜ pending

---

## Test T3 — 2 brands: matched + "kjadflk" — apenas matched em suggested

**Setup:** Mix de brand com match e brand sem match. Valida que `suggested_negatives` inclui apenas brands com hit (brands zero-match omitidas per spec section 2).

**Tool call:**

```
audit_competitor_keywords(
  customer_id="1163862076",
  competitor_brands=["nutry", "kjadflk"]
)
```

**Expected:**

- `competitor_brands` = `["nutry", "kjadflk"]` no output
- Se "nutry" tem hit: `suggested_negatives` contém EXACT + PHRASE para "nutry" apenas
- "kjadflk" NÃO aparece em `suggested_negatives` (zero match → sem evidência)

Validação:
- [ ] `competitor_brands` = `["nutry", "kjadflk"]` (ambas no echo)
- [ ] `suggested_negatives` não contém entry com `text = "kjadflk"` (sem hit)
- [ ] Se "nutry" tem hit: `suggested_negatives` tem exatamente 2 entries (EXACT + PHRASE pra "nutry")
- [ ] `summary.suggested_negatives_count` bate com `len(suggested_negatives)`

**Fallback se "nutry" sem match em Nutry sandbox:** `suggested_negatives = []` é válido. Testar T3 com brand que tem match conhecido na conta (extrair via T1 + baseline).

**Result:** ⬜ pending

---

## Test T4 — date_range=LAST_30_DAYS

**Setup:** Preset diferente do default. Valida que `resolve_date_window` processa corretamente.

**Tool call:**

```
audit_competitor_keywords(
  customer_id="1163862076",
  competitor_brands=["nutry"],
  date_range="LAST_30_DAYS"
)
```

**Expected:**

```json
{
  "date_range_resolved": {
    "start": "2026-04-20",
    "end": "2026-05-20",
    "days": 31
  },
  ...
}
```

*(Datas exatas dependem do dia de execução. Hoje 2026-05-20 → LAST_30_DAYS ≈ 30-31 days.)*

Validação:
- [ ] `date_range_resolved.days` >= 28 (LAST_30_DAYS)
- [ ] `date_range_resolved.end` = data de hoje (2026-05-20)
- [ ] `search_terms` podem ter mais entries que T1 (janela maior → mais search terms)
- [ ] `positive_keywords` idêntico a T1 (state-based, sem date filter)

**Result:** ⬜ pending

---

## Test T5 — Custom date range (start_date + end_date)

**Setup:** Override do preset com datas customizadas. Verifica que custom range override funciona e GAQL usa BETWEEN correto.

**Tool call:**

```
audit_competitor_keywords(
  customer_id="1163862076",
  competitor_brands=["nutry"],
  start_date="2026-05-01",
  end_date="2026-05-14"
)
```

**Expected:**

```json
{
  "date_range_resolved": {
    "start": "2026-05-01",
    "end": "2026-05-14",
    "days": 14
  },
  ...
}
```

Validação:
- [ ] `date_range_resolved.start` = `"2026-05-01"`
- [ ] `date_range_resolved.end` = `"2026-05-14"`
- [ ] `date_range_resolved.days` = 14 (BETWEEN inclusive: 14 - 1 + 1 = 14)
- [ ] Tool NÃO usa `date_range` preset quando `start_date+end_date` passados

**Result:** ⬜ pending

---

## Test T6 — limit=5 — truncation

**Setup:** Forçar truncate nas listas. Se `positive_keywords` ou `search_terms` tem > 5 entries, lista truncada a 5 e `truncated: true`.

**Tool call:**

```
audit_competitor_keywords(
  customer_id="1163862076",
  competitor_brands=["nutry"],
  limit=5
)
```

**Expected:**

```json
{
  "summary": {
    "positive_keywords_truncated": true,
    "search_terms_truncated": true,
    ...
  },
  "positive_keywords": [/* max 5 entries */],
  "search_terms": [/* max 5 entries */]
}
```

*(Se Nutry tem <= 5 matches em cada lista: `truncated: false`. Ambos casos válidos.)*

Validação:
- [ ] `len(positive_keywords)` <= 5
- [ ] `len(search_terms)` <= 5
- [ ] Se `positive_keywords_count > 5`: `positive_keywords_truncated` = `true` e `len(positive_keywords)` = 5
- [ ] Se `search_terms_count > 5`: `search_terms_truncated` = `true` e `len(search_terms)` = 5
- [ ] `search_terms` ordenados por `cost_brl` DESC (maior custo primeiro)
- [ ] `positive_keywords` ordenados por `(matched_brand ASC, ad_group_name ASC)`

**Fallback se Nutry com <= 5 matches em tudo:** documentar `truncated: false` como válido (env limitation — low volume). Safety net via integration test `test_returns_full_shape_with_matched_brands` que valida shape/sorting.

**Result:** ⬜ pending

---

## Test T7 — Empirical match: verificar keyword matched em ad_group sandbox

**Setup:** Prova empírica que match substring funciona — cruzar output da tool com query GAQL manual.

**Pré-condição:** T1 retornou pelo menos 1 `positive_keyword` com `keyword_text` contendo "nutry" OR existe keyword com brand competidora conhecida. Se nenhum match em T1 → T7 precisa de conta alternativa ou brand diferente.

**Procedimento:**

1. Pegar 1 keyword de `positive_keywords` em T1 (ex: `keyword_text="X"`, `matched_brand="B"`)
2. Confirmar via `run_gaql`:

```
SELECT
  ad_group_criterion.keyword.text,
  ad_group_criterion.keyword.match_type,
  ad_group_criterion.status
FROM keyword_view
WHERE ad_group_criterion.status = 'ENABLED'
  AND ad_group_criterion.negative = FALSE
LIMIT 50
```

3. Verificar que `keyword_text` contém `matched_brand` (substring check manual)
4. Para search terms: pegar 1 entry de `search_terms`, confirmar via `run_gaql`:

```
SELECT
  search_term_view.search_term,
  ad_group.name,
  metrics.impressions, metrics.clicks, metrics.cost_micros
FROM search_term_view
WHERE segments.date DURING LAST_7_DAYS
LIMIT 50
```

5. Verificar que `search_term` contém `matched_brand` e que `cost_brl` bate com `cost_micros / 1_000_000`

Validação:
- [ ] `keyword_text` da tool output contém `matched_brand` como substring (case insensitive)
- [ ] `cost_brl` da tool bate com `cost_micros / 1_000_000` da query manual (até 0.01 BRL)
- [ ] `impressions` e `clicks` batem com valores do GAQL

**Fallback se T7 DEFERRED por Nutry sem match:**
- Marcar DEFERRED — env limitation, não bug
- Anotar: "T7 DEFERRED — Nutry sandbox sem keyword/search_term com brand match no período. Igual padrão F41/F45. Coverage via unit tests (14 unit + 3 integration) suficiente."
- Smoke em conta real (MO-JP ou cliente V4 com histórico) na próxima sessão

**Result:** ⬜ pending *(possível DEFERRED — env limitation)*

---

## Test T8 — Schema validation: brand 2-char rejeitada (minLength 3)

**Setup:** Input inválido — brand com 2 chars (`minLength: 3` no schema). Tool deve rejeitar antes de qualquer GAQL call.

**Tool call:**

```
audit_competitor_keywords(
  customer_id="1163862076",
  competitor_brands=["ab"]
)
```

**Expected:** Erro de validação de schema (HTTP 400 ou MCP validation error). Tool NÃO executa GAQL. Mensagem deve indicar que brand "ab" viola `minLength: 3`.

Validação:
- [ ] Request rejeitada com erro de validação
- [ ] Mensagem referencia `minLength` ou `competitor_brands`
- [ ] Zero GAQL calls executadas (sem audit_log entries desta chamada)
- [ ] `competitor_brands=["abc"]` (3 chars) é aceito normalmente (boundary test)

**Result:** ⬜ pending

---

## Per-value empirical probe (Sprint 3b.19A.1 convention)

**N/A** — `audit_competitor_keywords` não tem enum whitelist em schema com valores SDK:

- `date_range` enum (`LAST_7_DAYS`, `LAST_14_DAYS`, `LAST_30_DAYS`, `LAST_90_DAYS`) é Google-side preset, não SDK whitelist — valores padrão testados pelo `resolve_date_window` helper (stable em 15+ tools)
- `match_type` no output é valor Google SDK read-only (não é input schema)
- `competitor_brands` é input livre do gestor — sem enum

Convention 3b.19A.1 não aplica. Schema regression coberta por `test_every_tool_has_valid_schema` + `test_no_composition_keywords_in_any_schema`.

---

## V4 invariants validation

**N/A** — Tool é read-only, sem mutations:

| Invariant | Aplicável | How smoke verifies |
|---|---|---|
| country_code = BR | N/A | Tool não toca geo data |
| language_code = pt-BR | N/A | Tool não toca language fields |
| currency_code = BRL | ✅ Parcial | `cost_brl` em decimal BRL (convertido de micros) — T1 valida presença do campo |
| timezone = -03:00 | N/A | Tool não cria nem manipula timestamps |
| LGPD consent | N/A | Read-only, sem envio de PII |

**`cost_brl` invariant:** `metrics.cost_micros / 1_000_000.0` converte pra BRL decimal. Validar que `cost_brl` não está em micros (> 10^6 pra valores normais seria bug). T1 valida field presente; se search_term tem `cost_brl > 0`, confirmar valor razoável (ex: `cost_brl < 10000` em Nutry sandbox).

---

## Cleanup post-smoke

Não há cleanup necessário:
- `audit_competitor_keywords` é read-only (zero mutations)
- Sem entities criadas em Nutry
- Audit_log entries ficam permanentes (rastreio histórico)
- Rate_counter incrementa normalmente (2 GAQL calls paralelas por chamada smoke)

---

## Notas pra Wellington pós-smoke

1. **Se T7 DEFERRED por volume Nutry insuficiente:** unit tests (14 unit + 3 integration) já garantem cobertura. DEFERRED é env limitation (igual F41/F45), não bug. Marcar como `N/A` no signoff.
2. **Uso real:** rodar `audit_competitor_keywords` em conta MO-JP (6436352492 ou client accounts) com brands reais competidoras (ex: "projecta", "casa do construtor", "promina") — volume real vai validar T7 organicamente.
3. **Fluxo natural de aplicação:** após smoke, usar `add_negative_keywords` com `suggested_negatives[]` da tool pra fechar o loop de waste elimination.
4. **Sprint 3b.32+ candidates:** `audit_zombie_keywords` (#11 ICE 315), `audit_orphan_smart_actions` (#12 ICE 288), `audit_negative_criterion_overlap`, `audit_assets_parity_between_campaigns`. Decisão Wellington baseada em dogfood real.
5. **Tool count:** atualizar CLAUDE.md sprint counter (3b.30→3b.31) e sprint-history.md após signoff.

---

## Sign-off checklist

- [ ] Pre-push gate 5/5 PASS
- [ ] Spec compliance reviewer subagent APPROVED (A1)
- [ ] Code quality reviewer subagent APPROVED (A1, A2, A3)
- [ ] Production `/health` 200
- [ ] T1-T6 PASS (shape + filters + date resolution + truncation)
- [ ] T7 PASS ou DEFERRED (env limitation Nutry — igual padrão F41/F45)
- [ ] T8 PASS (schema validation)
- [ ] CLAUDE.md sprint counter atualizado (3b.30 → 3b.31)
- [ ] sprint-history.md updated com entry Sprint 3b.31
- [ ] findings-catalog.md atualizado se F-findings emergiram
- [ ] Tool count 53 confirmado em produção (test_registered_tool_count_matches_files_on_disk 53==53)
