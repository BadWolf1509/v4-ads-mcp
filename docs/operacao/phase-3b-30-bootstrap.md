# Phase 3b.30 — manual smoke runbook (`audit_quality_score`)

**Purpose:** Validar Sprint 3b.30 — nova tool `audit_quality_score` (52ª MCP tool) que identifica keywords problemáticas com 3 flags acionáveis: `candidate_pause` (QS<=2 + impressions>=threshold + clicks=0 = waste), `candidate_promote_exact` (QS>=7 + BROAD + conv>=1 = promover pra EXACT reduz CPC), `duplicate_intent` (mesma keyword text em multi ad_groups — amplificação only, só quando outra flag ativa). Output flat list ordenada QS ASC + impressions DESC tie-break. Economiza ~30min/sessão em queries manuais via `run_gaql`. Feature nova, sem backward compat issue (tool inexistia antes).

**Operator:** wellinton.ribeiro@v4company.com
**Account:** `1163862076` Nutry (sandbox, low-volume — T2 ajusta `min_impressions=1`)

**Spec:** `docs/superpowers/specs/2026-05-20-sprint-3b-30-audit-quality-score-design.md`
**Plan:** `docs/superpowers/plans/2026-05-20-sprint-3b-30-audit-quality-score.md`

> **Escopo V0 confirmado:**
> - 3 flags: `candidate_pause`, `candidate_promote_exact`, `duplicate_intent` (amplificação only)
> - Output shape: flat list `flagged_keywords[]` ordered QS ASC + impressions DESC, sem grouping
> - Filtros: `customer_id` (required) + `ad_group_ids[]` (optional) + `min_impressions` (default 10) + `limit` (default 200) + date window (preset OR custom)
> - `duplicate_intent` só adicionada quando kw já tem outra flag (noise reduction — kw normal em 2 ad_groups não flagada)
> - QS thresholds hardcoded (1-2 pause / 7-10 promote) — Google research convention
> - Sempre auditado (`audit_this_call=True`)
> - Tool count: 51 → **52**

## Pre-flight

- [x] Deploy lands successfully (CI + Deploy green em commit `668ddb1`)
- [x] Service `/health` returns 200 (`{"status":"ok","version":"0.1.0"}`)
- [x] Tool `audit_quality_score` registered (test_registered_tool_count_matches_files_on_disk 52==52 PASS)
- [x] Pre-push gate `python scripts/check_pre_push.py` 5/5 PASS
- [x] Schema regression `test_no_composition_keywords_in_any_schema` passa
- [x] Unit tests `tests/unit/test_flag_keywords.py` 16/16 PASS (commits `bb8924c`/`f691cd4` — 2 boundary tests added)
- [x] Unit tests `tests/unit/test_audit_quality_score_query.py` 5/5 PASS (commit `d8f4f70`)
- [x] Integration tests `tests/integration/test_audit_quality_score.py` 3/3 PASS (commit `668ddb1`)

## Smoke results — execution pending Wellington next-session

| # | Test | Result | Notes |
|---|---|---|---|
| T1-T8 | Todos os smoke cases | ⏸ PENDING | MCP client desta sessão cacheou tool list pre-deploy — `audit_quality_score` não visível. Wellington executa em nova sessão MCP. Code paths já validados via 24 testes (16 unit pure flags + 5 GAQL builder + 3 integration wire-up). |

**Status efetivo:** Sprint 3b.30 **code shipped** via subagent-driven (pattern 3b.27/3b.28/3b.29). Smoke real diferido pra próxima sessão MCP (igual padrão Sprint 3b.28 que teve T7-T11 DEFERRED por env limitation).

**Confidence em production:**
- ✅ A1 spec compliance reviewer APPROVED + code quality reviewer APPROVED (após I1 fix mutation + M1 named constants + 2 boundary tests)
- ✅ A2 combined reviewer APPROVED (22/22 checks)
- ✅ A3 mcp-tool-quality-reviewer APPROVED (22/22 checks)
- ✅ A4 integration tests 3/3 PASS + CI green + Deploy green + /health 200
- ✅ 24 testes total cobrindo todos os branches do algoritmo

## Pre-smoke setup

### Step 1: Sanity check no MCP client

Verificar que `audit_quality_score` aparece na lista de tools disponíveis com parâmetros corretos:

```
# Introspect — esperar ver audit_quality_score com:
# - customer_id required (pattern ^[0-9]{10}$)
# - ad_group_ids optional (array of string)
# - min_impressions optional (integer, default 10)
# - limit optional (integer, default 200)
# - date_range optional (enum preset)
# - start_date, end_date optional (YYYY-MM-DD)
```

Se `audit_quality_score` não aparece ou tool count ainda 51, deploy não landed — abortar smoke.

### Step 2: Reference numbers pré-smoke

Capturar baseline via `run_gaql` pra validação cruzada em T7:

```
# GAQL baseline pra T7 — keywords com QS baixo em Nutry
SELECT
  ad_group.id, ad_group.name, campaign.name,
  ad_group_criterion.criterion_id,
  ad_group_criterion.keyword.text,
  ad_group_criterion.keyword.match_type,
  ad_group_criterion.quality_info.quality_score,
  metrics.impressions, metrics.clicks, metrics.conversions
FROM keyword_view
WHERE ad_group_criterion.status = 'ENABLED'
  AND ad_group_criterion.quality_info.quality_score IS NOT NULL
  AND segments.date DURING LAST_30_DAYS
ORDER BY ad_group_criterion.quality_info.quality_score ASC
LIMIT 50
```

Anotar:
- Total de keywords ENABLED com QS não-nulo (esperar volume pequeno em Nutry)
- Quaisquer keywords com QS 1-2 + impressions > 0 + clicks = 0 (candidatas ao T7)
- Quaisquer keywords BROAD com QS >= 7 + conversions >= 1 (candidatas promote)

---

## Test T1 — Chamada básica sem filters

**Setup:** Positive case mínimo — account-wide audit com defaults.

**Tool call:**

```
audit_quality_score(
  customer_id="1163862076"
)
```

**Expected output (shape):**

```json
{
  "customer_id": "1163862076",
  "date_range_resolved": {
    "start": "2026-04-20",
    "end": "2026-05-20",
    "days": 30
  },
  "filters_applied": {
    "ad_group_ids": null,
    "min_impressions": 10,
    "limit": 200
  },
  "total_flagged": 0,
  "truncated": false,
  "flagged_keywords": []
}
```

*(Nutry sandbox low-volume — `flagged_keywords` pode ser `[]` com defaults. Se retornar entries, validar shape de cada entry.)*

Validação:
- [ ] Response tem `customer_id` = `"1163862076"`
- [ ] `date_range_resolved` tem `start`, `end`, `days` >= 28 (LAST_30_DAYS)
- [ ] `filters_applied.min_impressions` = 10 (default)
- [ ] `filters_applied.limit` = 200 (default)
- [ ] `filters_applied.ad_group_ids` = null (sem filtro)
- [ ] `total_flagged` é integer >= 0
- [ ] `truncated` é boolean
- [ ] `flagged_keywords` é array (pode ser `[]`)
- [ ] Se não-vazio: cada entry tem `ad_group_id`, `ad_group_name`, `campaign_name`, `keyword_id`, `keyword_text`, `match_type`, `quality_score`, `impressions`, `clicks`, `conversions`, `cost_brl`, `flags`
- [ ] Audit_log entry criada (verificar via `/admin/audit` ou DB)
- [ ] Rate_counter +1

**Result:** ⬜ pending

---

## Test T2 — min_impressions=1 (fallback Nutry low-volume)

**Setup:** Nutry sandbox tem volume baixo — reduzir threshold pra capturar keywords com poucos impressions.

**Tool call:**

```
audit_quality_score(
  customer_id="1163862076",
  min_impressions=1
)
```

**Expected:**

```json
{
  "customer_id": "1163862076",
  "filters_applied": {
    "ad_group_ids": null,
    "min_impressions": 1,
    "limit": 200
  },
  ...
}
```

Validação:
- [ ] `filters_applied.min_impressions` = 1 (confirmado)
- [ ] `total_flagged` >= T1 (threshold menor → mais candidatas)
- [ ] Se flagged: keywords com `impressions >= 1` e `quality_score <= 2` e `clicks == 0` têm flag `candidate_pause`
- [ ] `date_range_resolved.days` ~30 (LAST_30_DAYS default ainda)
- [ ] Se result ainda `[]`: anotar que Nutry zero kw com QS<=2 neste período — T7 DEFERRED com nota

**Fallback se ainda empty:** usar T1 de conta real (MO-JP) pra confirmar tool funciona em conta com volume real.

**Result:** ⬜ pending

---

## Test T3 — Filtro por ad_group_ids

**Setup:** Filtrar audit a um ad_group específico. Isolação garante que só kw daquele ad_group aparecem.

**Tool call:**

```
audit_quality_score(
  customer_id="1163862076",
  ad_group_ids=["193008426336"],
  min_impressions=1
)
```

**Expected:**

- Response shape igual T1/T2
- `filters_applied.ad_group_ids` = `["193008426336"]`
- Todos `flagged_keywords[].ad_group_id` == `"193008426336"` (sem leakage de outros ad_groups)

Validação:
- [ ] `filters_applied.ad_group_ids` = `["193008426336"]`
- [ ] Se flagged_keywords não-vazio: todos entries têm `ad_group_id = "193008426336"`
- [ ] Se empty: confirmar que ad_group existe via `run_gaql` (ID pode ser inválido pra Nutry)
- [ ] GAQL cláusula `AND ad_group.id IN ('193008426336')` presente no audit_log (via params_summary)

**Fallback se ad_group_id não existe em Nutry:** usar qualquer ad_group_id válido da conta (extrair via `run_gaql("SELECT ad_group.id FROM ad_group WHERE ad_group.status = 'ENABLED' LIMIT 1")`).

**Result:** ⬜ pending

---

## Test T4 — Custom date range (start_date + end_date)

**Setup:** Override do preset com datas customizadas. Verifica que `resolve_date_window` processa corretamente e GAQL usa range específico.

**Tool call:**

```
audit_quality_score(
  customer_id="1163862076",
  start_date="2026-05-01",
  end_date="2026-05-14",
  min_impressions=1
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
- [ ] `filters_applied.min_impressions` = 1 (override funciona)

**Result:** ⬜ pending

---

## Test T5 — Truncation via limit=10

**Setup:** Forçar truncate — se total_flagged > 10, deve retornar só 10 e `truncated: true`.

**Tool call:**

```
audit_quality_score(
  customer_id="1163862076",
  limit=10,
  min_impressions=1
)
```

**Expected:**

```json
{
  "filters_applied": {
    "limit": 10,
    ...
  },
  "total_flagged": N,
  "truncated": true,
  "flagged_keywords": [/* 10 entries */]
}
```

*(Se Nutry tem <= 10 flagged: `truncated: false`, `len(flagged_keywords) <= 10`. Ambos casos são válidos.)*

Validação:
- [ ] `filters_applied.limit` = 10
- [ ] `len(flagged_keywords)` <= 10
- [ ] Se `total_flagged > 10`: `truncated: true` e `len(flagged_keywords) == 10`
- [ ] Se `total_flagged <= 10`: `truncated: false` e `len(flagged_keywords) == total_flagged`
- [ ] Ordering: primeiro entry tem menor `quality_score`; tie-break por `impressions` DESC (maior primeiro)

**Fallback se Nutry < 10 flagged:** documentar `truncated: false` como válido. Safety net de truncation coberta por integration test `test_respects_min_impressions_threshold` + unit test `test_truncate_at_limit_returns_total_pre_truncate`.

**Result:** ⬜ pending

---

## Test T6 — Preset date_range="LAST_7_DAYS"

**Setup:** Usar preset explícito diferente do default (LAST_30_DAYS). Validar que `resolve_date_window` resolve corretamente.

**Tool call:**

```
audit_quality_score(
  customer_id="1163862076",
  date_range="LAST_7_DAYS",
  min_impressions=1
)
```

**Expected:**

```json
{
  "date_range_resolved": {
    "start": "2026-05-13",
    "end": "2026-05-20",
    "days": 8
  },
  ...
}
```

*(Datas exatas dependem do dia de execução. Hoje 2026-05-20 → LAST_7_DAYS = [2026-05-13, 2026-05-20].)*

Validação:
- [ ] `date_range_resolved.days` ~7-8 (janela LAST_7_DAYS)
- [ ] `date_range_resolved.end` = data de hoje (2026-05-20)
- [ ] `date_range_resolved.start` = data - 7 dias
- [ ] `total_flagged` <= T2 (janela menor → menos data; pode ser menor ou igual)
- [ ] Response shape consistente com T1-T5

**Result:** ⬜ pending

---

## Test T7 — Empirical validate candidate_pause (manual proof)

**Setup:** Comparar output da tool com query manual GAQL. Prova empírica que flag `candidate_pause` está correta.

**Pré-condição:** T2 retornou pelo menos 1 `candidate_pause` em `flagged_keywords`. Se T2 vazio → T7 DEFERRED (Nutry sem kw com QS<=2 no período — igual padrão F45/F41 env limitation).

**Procedimento:**

1. Pegar 1 keyword da lista `flagged_keywords` com flag `candidate_pause` (ex: `keyword_text="X"`, `ad_group_id="Y"`)
2. Confirmar via `run_gaql`:

```
SELECT
  ad_group_criterion.keyword.text,
  ad_group_criterion.quality_info.quality_score,
  metrics.impressions, metrics.clicks
FROM keyword_view
WHERE ad_group.id = 'Y'
  AND ad_group_criterion.keyword.text = 'X'
  AND ad_group_criterion.status = 'ENABLED'
  AND segments.date DURING LAST_30_DAYS
```

3. Verificar que valores batem com output da tool

Validação:
- [ ] `quality_score` do GAQL == `quality_score` do tool output
- [ ] `impressions` bate (mesmo período)
- [ ] `clicks` == 0 (condição candidate_pause)
- [ ] Confirma: QS <= 2 + impressions >= 10 + clicks == 0 = waste signal válido

**Resultado esperado:** match 1:1. Discrepância = bug de parse ou desfasagem de cache QS (documentada: "QS pode lagar entre queries").

**Fallback se T7 DEFERRED por Nutry vazio:** marcar DEFERRED com nota. Unit tests coverage (14 unit + 3 integration) já garantem lógica. Smoke em conta real (MO-JP, conta Maceió) na próxima sessão.

**Result:** ⬜ pending

---

## Test T8 — Empirical validate duplicate_intent

**Setup:** Validar flag `duplicate_intent` — requer keyword text idêntica em 2+ ad_groups diferentes, ambas já flagadas por outra flag.

**Pré-condição:** Identificar (ou criar) cenário onde mesma keyword text existe em 2 ad_groups E qualquer delas tem QS<=2 ou (QS>=7 + BROAD + conv>=1).

**Procedimento:**

1. Verificar se existe keyword duplicada em Nutry:

```
SELECT
  ad_group.id, ad_group_criterion.keyword.text
FROM keyword_view
WHERE ad_group_criterion.status = 'ENABLED'
  AND segments.date DURING LAST_30_DAYS
ORDER BY ad_group_criterion.keyword.text ASC
```

2. Se existir keyword text repetida em 2+ ad_groups, E pelo menos 1 cumpre outra flag → T8 positivo.
3. Executar `audit_quality_score` e verificar que entry tem `duplicate_intent` no `flags[]`.

Validação:
- [ ] Keyword com text X aparece em >= 2 ad_groups E tem outra flag ativa
- [ ] Tool output inclui `"duplicate_intent"` em `flags` pra essa keyword
- [ ] Keyword text X em apenas 1 ad_group (ou sem outra flag) NÃO tem `duplicate_intent`

**Fallback se Nutry sem cenário de duplicata flagada:**
- Marcar T8 DEFERRED — env limitation, não bug
- Unit tests `test_duplicate_intent_amplifies_existing_pause` + `test_duplicate_intent_NOT_added_without_other_flag` já cobrem a lógica
- Anotar: "T8 DEFERRED — Nutry sandbox sem duplicata flagada em scope. Igual padrão F41/F45. Coverage via unit tests suficiente."

**Result:** ⬜ pending *(possível DEFERRED se cenário Nutry insuficiente)*

---

## Per-value empirical probe (Sprint 3b.19A.1 convention)

**N/A** — `audit_quality_score` não tem enum whitelist em schema:

- `date_range` enum (`LAST_7_DAYS`, `LAST_14_DAYS`, `LAST_30_DAYS`, `LAST_90_DAYS`) é Google-side preset, não SDK whitelist — valores padrão testados pelo `resolve_date_window` helper (stable em 15+ tools)
- `match_type` no output é valor Google SDK (`BROAD`, `PHRASE`, `EXACT`) — read-only, não é input schema
- `min_impressions` e `limit` são integers simples — sem enum

Convention 3b.19A.1 não aplica. Schema regression coberta por `test_every_tool_has_valid_schema` + `test_no_composition_keywords_in_any_schema`.

---

## V4 invariants validation

**N/A** — Tool é read-only, sem mutations:

| Invariant | Aplicável | How smoke verifies |
|---|---|---|
| country_code = BR | N/A | Tool não toca geo data |
| language_code = pt-BR | N/A | Tool não toca language fields |
| currency_code = BRL | ✅ Parcial | `cost_brl` em decimal BRL (convertido de micros) — T1/T2 validam presença do campo |
| timezone = -03:00 | N/A | Tool não cria nem manipula timestamps |
| LGPD consent | N/A | Read-only, sem envio de PII |

**`cost_brl` invariant:** `metrics.cost_micros / 1_000_000.0` converte pra BRL decimal. Validar que `cost_brl` não está em micros (> 10^6 pra valores normais seria bug). T1/T2 validam field presente; se kw tem `cost_brl > 0`, confirmar valor razoável (ex: `cost_brl < 10000` em Nutry sandbox).

---

## Cleanup post-smoke

Não há cleanup necessário:
- `audit_quality_score` é read-only (zero mutations)
- Sem entities criadas em Nutry
- Audit_log entries ficam permanentes (rastreio histórico)
- Rate_counter incrementa normalmente (8 GAQL calls do smoke T1-T8)

---

## Notas pra Wellington pós-smoke

1. **Se T7/T8 DEFERRED por volume Nutry insuficiente:** unit tests (14 unit + 3 integration) já garantem cobertura. DEFERRED é env limitation (igual F41/F45), não bug. Marcar como `N/A` no signoff.
2. **Uso real:** rodar `audit_quality_score` em conta MO-JP (6436352492 ou client accounts) após smoke — volume real vai validar T7/T8 organicamente.
3. **Sprint 3b.31+ candidate:** familia `audit_*` segue fila ICE — `audit_competitor_keywords`, `audit_zombie_keywords`, `audit_orphan_smart_actions`, `audit_negative_criterion_overlap`, `audit_assets_parity_between_campaigns`. Decisão Wellington baseada em dogfood real.
4. **`duplicate_intent` semantics doc:** se gestor questionar por que kw normal em 2 ad_groups não aparece — design intencional (amplificação only). Explicar: noise reduction pra focar em kw já problemáticas.
5. **Tool count:** atualizar CLAUDE.md sprint counter (3b.29→3b.30) e sprint-history.md após signoff.

---

## Sign-off checklist

- [x] Pre-push gate 5/5 PASS
- [x] Spec compliance reviewer subagent APPROVED (A1 com 1 fix iteration → A1.1)
- [x] Code quality reviewer subagent APPROVED (A1, A2, A3)
- [x] Production `/health` 200 (revisão post-`668ddb1`)
- [⏸] T1-T8 smoke real: PENDING Wellington next-session (MCP cache desta sessão pre-deploy)
- [x] CLAUDE.md sprint counter atualizado (3b.29 → 3b.30)
- [x] sprint-history.md updated com entry Sprint 3b.30
- [x] findings-catalog.md sem updates (zero F-findings — não emergiu)
- [x] Tool count 52 confirmado em produção (test_registered_tool_count_matches_files_on_disk 52==52)
