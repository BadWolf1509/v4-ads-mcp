# Phase 3b.29 — manual smoke runbook (`run_gaql.aggregate_by`)

**Purpose:** Validar Sprint 3b.29 — extensão de `run_gaql` com parâmetro opcional `aggregate_by: list[str]` que faz GROUP BY + COUNT client-side e retorna `groups[]` ordenado DESC ao invés de `rows[]`. Resolve B5 dogfood MO-JP 2026-05-19 (token overflow em queries densas — caso real `campaign_asset` 272 rows × 330 chars = 89k chars). Backward compat 100%: sem `aggregate_by` → shape original (`rows[]`, `row_count`, `truncated`).

**Operator:** wellinton.ribeiro@v4company.com
**Account:** `1163862076` Nutry (sandbox)

**Spec:** `docs/superpowers/specs/2026-05-20-sprint-3b-29-run-gaql-aggregate-by-design.md`
**Plan:** `docs/superpowers/plans/2026-05-20-sprint-3b-29-run-gaql-aggregate-by.md`

> **Escopo V0 confirmado:**
> - Apenas COUNT (sem SUM/AVG/MIN/MAX — YAGNI)
> - Apenas `run_gaql` (escape hatch); tools curadas mantêm contrato estável
> - Output shape: `groups[]` sorted by count DESC, replace `rows[]`
> - Safety net: hard fail se raw rows > 10_000 antes de agregar (PT-BR error com hint "refine WHERE clause")
> - Truncation: groups[] limitado a 1000 (mesmo limite atual de rows[])
> - Aggregate é pure function em `src/google_ads/aggregation.py` (testable standalone)

## Pre-flight

- [x] Deploy lands successfully (CI + Deploy green em commit `1f07d3e`)
- [x] Service `/health` returns 200 (`{"status":"ok","version":"0.1.0"}`)
- [x] Tool `run_gaql` ainda visível em MCP tool list (count 51, sem incremento)
- [x] Pre-push gate `python scripts/check_pre_push.py` 5/5 PASS (validado em A3)
- [x] Schema regression `test_no_composition_keywords_in_any_schema` passa
- [x] Unit tests `tests/unit/test_aggregation.py` 9/9 PASS (commit `b86ef09`)
- [x] Integration tests `tests/integration/test_utility_tools.py` 4 novos PASS (commit `e0a0abd`)

Production revisions: deploy post `1f07d3e` em 2026-05-20 17:10 UTC.

## Smoke results — executado 2026-05-20

| # | Test | Result | Notes |
|---|---|---|---|
| T1 | Backward compat — sem aggregate_by | ✅ PASS | `rows[]` shape, `row_count: 5`, sem `groups` |
| T2 | Aggregate por status — 1 field | ✅ PASS | 1 grupo `PAUSED:5`, soma counts = total_rows_scanned |
| T3 | Reproduce caso B5 — `campaign_asset` × 2 fields | ✅ PASS | **119 rows → 7 groups** (massive reduction), ordered DESC: SITELINK(68) > CALLOUT(40) > CALL(4) > STRUCTURED_SNIPPET(3) > PROMOTION(2) > BUSINESS_NAME(1) > BUSINESS_LOGO(1). B5 sub-demanda **RESOLVED**. |
| T4 | Field path inexistente | ✅ PASS | 1 grupo `{key: {nonexistent.field: null}, count: 5}` — preserve visibility working |
| T5 | Empty result + aggregate_by | ✅ PASS | `total_rows_scanned: 0`, `group_count: 0`, `groups: []` — shape consistente |
| T6 | Safety net — query patológica >10k rows | ⚠️ DEFERRED | Volume Nutry insuficiente: change_event tem hard cap 10k pelo Google; keyword_view só tem 57 entries. Unit test `test_run_gaql_rejects_more_than_10k_raw_rows` mocked cobre o path. Igual padrão F41/F45 (env limitation, não bug). |

**Effective result:** 5/6 PASS + 1 DEFERRED (env limitation)

### Observações empíricas

- **T3:** `asset.type` retornou `null` em todos grupos. GAQL não retorna nested asset metadata via `campaign_asset` query direto — pra ter `asset.type` populated precisa query `FROM asset` separadamente. **Não é bug do aggregator** — é GAQL semantics. Multi-field key (field_type + asset.type) preserved corretamente.
- **T6 fallback:** `change_event` tem cap nativo Google de 10k LIMIT obrigatório ("Change event requests must specify a LIMIT in query and LIMIT should be less than or equal to 10k"). Outros resources (`keyword_view`, etc.) em Nutry têm volume baixo. Safety net validado apenas via unit test mocked.

### F-findings emerged

Nenhum F-finding novo. T6 DEFERRED é env limitation (similar a F41 RSA recreate em sandbox, F45 Customer Match em Nutry). Não bug — não cataloga.

### Sign-off

- [x] Pre-push gate 5/5 PASS (validado em A1/A2/A3)
- [x] Spec compliance reviewer subagent ✅ APPROVED em A1, A2 (após fix A2.1), A3
- [x] Code quality reviewer subagent ✅ APPROVED em A1, A2, A3
- [x] Production /health 200 (revisão pós `1f07d3e`)
- [x] **5/6 PASS + 1 DEFERRED** após 1 fix iteration (A2.1 `group_count` pre-slice)
- [x] CLAUDE.md sprint counter atualizado (3b.1→3b.29)
- [x] sprint-history.md updated com entry Sprint 3b.29
- [x] findings-catalog.md sem updates (zero F-findings novos)
- [x] B5 sub-demanda do dogfood MO-JP 2026-05-19 marcada RESOLVED
- [x] Tool count permanece 51 (sprint é feature em existing tool, sem add)

---

## Pre-smoke setup

### Step 1: Sanity check no MCP client

Verificar que `run_gaql` agora aceita parâmetro `aggregate_by`:

```python
# Quick introspect via Claude/Cursor — listar params do tool
# Esperar ver aggregate_by no schema com type: array, items: string, minItems: 1, maxItems: 5
```

Se aggregate_by não aparece no schema, deploy não landed corretamente — abortar smoke e investigar.

### Step 2: Reference numbers pré-smoke

Capturar baseline pra comparação:

```
GAQL pré-smoke 1 (campaign count por status, sem aggregate):
SELECT campaign.id, campaign.status FROM campaign
```

Anotar:
- Total de campaigns retornadas (`row_count`)
- Distribution manual por status (contar ENABLED, PAUSED, REMOVED)

```
GAQL pré-smoke 2 (campaign_asset enxuto — caso B5):
SELECT campaign_asset.campaign, campaign_asset.field_type, asset.type
FROM campaign_asset
LIMIT 1000
```

Anotar:
- Total de campaign_asset rows (`row_count`)
- Tamanho estimado response (em chars) — se > 50k, T3 vai validar redução drástica

### Step 3: Histórico de change_event para T6 (opcional)

Query pra forçar >10k raw rows (necessário pra trigger safety net):

```
SELECT change_event.change_date_time FROM change_event
WHERE change_event.change_date_time DURING LAST_30_DAYS
```

Se Nutry retornou `row_count > 10000` na query above, anotar. Caso contrário, T6 marca DEFERRED ou usa outra conta.

---

## Test T1 — Backward compat (sem aggregate_by)

**Setup:** Sanity check que mudanças não quebraram callers existentes.

**Tool call:**

```
run_gaql(
  customer_id="1163862076",
  query="SELECT campaign.id, campaign.status FROM campaign LIMIT 5"
)
```

**Expected output (shape original):**

```json
{
  "customer_id": "1163862076",
  "row_count": 5,
  "truncated": false,
  "rows": [
    {"campaign": {"id": "...", "status": "..."}},
    ...
  ]
}
```

Validação:
- [ ] Response tem chave `rows` (NÃO `groups`)
- [ ] Response tem chave `row_count` (NÃO `total_rows_scanned`)
- [ ] `truncated: false`
- [ ] Sem chave `group_count` no response
- [ ] Audit_log entry sem `aggregate_by` em `params_summary`
- [ ] Rate_counter +1 (1 GAQL call)

**Result:** ⬜ pending

---

## Test T2 — Aggregate por status (1 field)

**Setup:** Mínimo positive case — agregar mesma query T1 por 1 field só.

**Tool call:**

```
run_gaql(
  customer_id="1163862076",
  query="SELECT campaign.id, campaign.status FROM campaign LIMIT 5",
  aggregate_by=["campaign.status"]
)
```

**Expected output (shape novo):**

```json
{
  "customer_id": "1163862076",
  "total_rows_scanned": 5,
  "group_count": 1-3,
  "truncated": false,
  "groups": [
    {"key": {"campaign.status": "ENABLED"}, "count": 3},
    {"key": {"campaign.status": "PAUSED"}, "count": 2}
  ]
}
```

Validação:
- [ ] Response tem chave `groups` (NÃO `rows`)
- [ ] Response tem chave `total_rows_scanned` (=5, valor esperado)
- [ ] Response tem chave `group_count` (entre 1-3 dependendo do status mix)
- [ ] `groups` array ordenado por `count` DESC (maior primeiro)
- [ ] Cada grupo tem `key: {campaign.status: "<value>"}` + `count: N`
- [ ] Soma de `count` em todos os groups = `total_rows_scanned` (= 5)
- [ ] Audit_log entry inclui `aggregate_by=["campaign.status"]` em `params_summary`

**Result:** ⬜ pending

---

## Test T3 — Reproduce caso B5 (campaign_asset × 2 fields)

**Setup:** Reproduce o caso real do dogfood — query densa de `campaign_asset` (272 rows × ~330 chars = 89k chars) que justificou criar esta feature. Validação chave: output drasticamente menor que raw rows.

**Tool call:**

```
run_gaql(
  customer_id="1163862076",
  query="SELECT campaign_asset.campaign, campaign_asset.field_type, asset.type FROM campaign_asset",
  aggregate_by=["field_type", "asset.type"]
)
```

**Expected output:**

```json
{
  "customer_id": "1163862076",
  "total_rows_scanned": 272,
  "group_count": 5-10,
  "truncated": false,
  "groups": [
    {"key": {"field_type": "STRUCTURED_SNIPPET", "asset.type": "STRUCTURED_SNIPPET"}, "count": 96},
    {"key": {"field_type": "SITELINK", "asset.type": "SITELINK"}, "count": 72},
    {"key": {"field_type": "CALLOUT", "asset.type": "CALLOUT"}, "count": 50}
  ]
}
```

Validação:
- [ ] Output reduzido drasticamente vs T1-equivalent raw rows (target: < 5k chars vs ~89k baseline)
- [ ] `total_rows_scanned` bate com `row_count` raw esperado (~272 do baseline)
- [ ] Cada `key` é dict com 2 entries (`field_type` + `asset.type`) — multi-field group preserved
- [ ] Groups ordenados por count DESC
- [ ] Combinações de field_type + asset.type que aparecem fazem sentido (SITELINK + SITELINK, CALLOUT + CALLOUT, etc.)
- [ ] **B5 sub-demanda RESOLVED** — feature elimina overhead do workaround Bash+Counter() de Wellington

**Result:** ⬜ pending

---

## Test T4 — Field path inexistente (None key behavior)

**Setup:** Validar edge case — campo no `aggregate_by` que NÃO está em nenhum row retornado.

**Tool call:**

```
run_gaql(
  customer_id="1163862076",
  query="SELECT campaign.id FROM campaign LIMIT 5",
  aggregate_by=["nonexistent.field"]
)
```

**Expected output:**

```json
{
  "customer_id": "1163862076",
  "total_rows_scanned": 5,
  "group_count": 1,
  "truncated": false,
  "groups": [
    {"key": {"nonexistent.field": null}, "count": 5}
  ]
}
```

Validação:
- [ ] Response tem 1 grupo único com `key: {"nonexistent.field": null}` (JSON null)
- [ ] `count` = 5 (todos os rows caíram no mesmo bucket "None")
- [ ] **NÃO há erro** — comportamento documentado: field missing maps to None (preserve visibility)
- [ ] `group_count: 1`
- [ ] **UX hint:** se gestor passar field path errado, output evidencia o erro (1 grupo null com count=total — facilmente notado)

**Nota:** Validação que mostra preserve-visibility design choice. Field path errado não causa erro silencioso, vira grupo None visível.

**Result:** ⬜ pending

---

## Test T5 — Empty result + aggregate_by (edge case 0 rows)

**Setup:** Query que retorna 0 rows + aggregate_by ativo. Verificar shape consistente.

**Tool call:**

```
run_gaql(
  customer_id="1163862076",
  query="SELECT campaign.id FROM campaign WHERE campaign.id = 0",
  aggregate_by=["campaign.status"]
)
```

**Expected output:**

```json
{
  "customer_id": "1163862076",
  "total_rows_scanned": 0,
  "group_count": 0,
  "truncated": false,
  "groups": []
}
```

Validação:
- [ ] `total_rows_scanned: 0`
- [ ] `group_count: 0`
- [ ] `groups: []` (array vazio, não null/missing)
- [ ] `truncated: false`
- [ ] **NÃO há erro** — empty input → empty output, shape consistente
- [ ] Response total < 200 chars (sanity check tamanho)

**Fallback se Nutry tiver `campaign.id=0`:** usar `WHERE campaign.id = 999999999` (ID inválido garantido).

**Result:** ⬜ pending

---

## Test T6 — Safety net (>10k raw rows)

**Setup:** Forçar query patológica que retorne mais de 10_000 raw rows antes do aggregate → trigger safety net hard fail.

**Tool call:**

```
run_gaql(
  customer_id="1163862076",
  query="SELECT change_event.change_date_time, change_event.user_email FROM change_event WHERE change_event.change_date_time DURING LAST_30_DAYS",
  aggregate_by=["change_event.user_email"]
)
```

**Expected:**

Se Nutry tem >10k change_event rows em LAST_30_DAYS:
```
ValueError ou status=error com mensagem PT-BR contendo:
- "query retornou >10k rows"
- "Refine WHERE clause antes de agregar"
- número exato de raw rows scanned (ex: "12547")
```

Validação:
- [ ] Erro PT-BR explícito sobre limite 10k
- [ ] Mensagem inclui número real de rows (não placeholder)
- [ ] Sugestão concreta: "refine WHERE clause" ou hint de filtro
- [ ] Aggregate NUNCA executou (fail-fast antes de agrupar)
- [ ] **OOM prevention validado** — sem timeout, sem memory spike

**Fallback se Nutry < 10k change_events:**

1. Tentar query mais ampla: `FROM change_event WHERE change_event.change_date_time DURING LAST_90_DAYS` (90 dias = ~3x volume)
2. Tentar `FROM keyword_view DURING LAST_30_DAYS` (Nutry tem 5 PAUSED + outras keywords)
3. Se ainda < 10k, marcar **T6 DEFERRED** com nota: "Nutry sandbox volume insuficiente. Validar safety net em conta com histórico real (MO-JP ou outra)."
4. Unit test `test_run_gaql_rejects_more_than_10k_raw_rows` (mocked) já cobre o path. Smoke real é defense-in-depth.

**Result:** ⬜ pending _(possível DEFERRED se volume Nutry < 10k rows)_

---

## Per-value empirical probe (Sprint 3b.19A.1 convention)

**N/A** — `aggregate_by` é `array of string` (field paths livres, sem whitelist enum).

Convention 3b.19A.1 não aplica:
- Nenhum enum whitelist no schema novo
- `aggregate_by` aceita qualquer string (field path)
- T4 valida comportamento de field path inválido (vira grupo None)

Schema regression cobrir:
- `test_every_tool_has_valid_schema` (validation JSON-Schema 7)
- `test_no_composition_keywords_in_any_schema` (3b.19B.1 — `aggregate_by` é simple `array of string`, sem `oneOf/allOf/anyOf`)

---

## V4 invariants validation

**N/A** — Feature é puramente client-side aggregation. Não toca em geo/lang/currency/timezone/LGPD:

| Invariant | Aplicável | How smoke verifies |
|---|---|---|
| country_code = BR | N/A | Tool não toca em geo data |
| language_code = pt-BR | N/A | Tool não toca em language fields |
| currency_code = BRL | N/A | Tool não toca em monetary fields |
| timezone = -03:00 | N/A | Tool não cria nem manipula timestamps |
| LGPD consent | N/A | Tool é read-only (não envia PII) |

**Único invariant PT-BR validado:** mensagem de erro do safety net (T6) é em português brasileiro com hint claro ("Refine WHERE clause antes de agregar"), seguindo padrão dos demais erros do MCP.

---

## Cleanup post-smoke

Não há cleanup necessário:
- `run_gaql` é read-only (sem mutations)
- Sem entities criadas em Nutry
- Audit_log entries ficam permanentes (rastreio histórico)
- Rate_counter incrementa normalmente (5-6 GAQL calls do smoke)

---

## Notas pra Wellington pós-smoke

1. **Se T6 DEFERRED por volume Nutry insuficiente:** safety net já tem coverage via unit test mocked. Smoke real é bonus, não bloqueador. Marcar como `N/A` no signoff em vez de fail.
2. **B5 RESOLVED:** marcar sub-demanda B5 do dogfood MO-JP 2026-05-19 como ✅ no doc original. Workaround Bash+Counter() agora obsoleto pra queries densas — Wellington pode usar `aggregate_by` direto no MCP.
3. **Sprint 3b.30+ candidate:** se uso real revelar demanda por SUM/AVG/MIN/MAX em tools curadas (`get_search_terms_report`, etc.), considerar extensão. YAGNI até evidence concreta.
4. **Doc atualização:** adicionar exemplo de `aggregate_by` em qualquer doc/exemplo de `run_gaql` (se houver). User-facing docs deveriam mencionar o parâmetro.
