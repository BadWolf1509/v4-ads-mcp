# Phase 3b.36 — manual smoke runbook (`audit_zombie_keywords`)

**Purpose:** Validar Sprint 3b.36 — nova tool `audit_zombie_keywords` (56ª MCP tool) que detecta keywords ENABLED com zero activity (`impressions=0 AND clicks=0`) em window LAST_30_DAYS (default). Pre-cleanup decision tool: gestor identifica waste antes de pausar/remover em massa. Output flat list ordenada por `ad_group_name ASC + keyword_text ASC` pra agrupar visualmente. Filtros server-side hardcoded: `status=ENABLED` + `negative=FALSE`. Pure aggregator + wrapper sobre 1 GAQL query em `keyword_view` (padrão Sprint 3b.30/3b.31/3b.33/3b.35). ICE 315, cleanup massivo recurring dogfood MO-JP 19/05.

**Operator:** wellinton.ribeiro@v4company.com
**Account principal:** `7862230676` Mestre da Obra JP (production V4 — caso real cleanup massivo recurring lição 41+)
**Account secundária:** `7455088726` ML Antiguidades (e-commerce — T5 conta clean baseline)

**Spec:** `docs/superpowers/specs/2026-05-21-sprint-3b-36-audit-zombie-keywords-design.md`
**Plan:** `docs/superpowers/plans/2026-05-21-sprint-3b-36-audit-zombie-keywords.md`
**Dogfood source:** `docs/operacao/dogfood-2026-05-19-mestre-da-obra-jp-cleanup-massivo.md` (#11 backlog, ICE 315)

> **Escopo V0 confirmado:**
> - Input: `customer_id` (req, pattern `^[0-9]{10}$`) + `ad_group_ids` (optional, max 50) + `limit` (default 200, max 1000) + `date_range` preset OR `start_date`+`end_date` custom
> - Output: `customer_id` + `date_range_resolved` + `filters_applied` echo + `total_zombies` + `truncated` + `returned_count` + `zombies[]` flat list
> - Definição zombie V0: `impressions=0 AND clicks=0` (pure waste, máximo confidence)
> - Window default: `LAST_30_DAYS`
> - Sort: `ad_group_name ASC, keyword_text ASC` (stable visual grouping)
> - Truncation pattern F22: `truncated=true` se `total_zombies > limit`, `returned_count` reflete actual array length
> - Server-side hardcoded: `WHERE status='ENABLED' AND negative=FALSE`
> - `audit_this_call=True` (sensitive read, lista keywords config completa)
> - Tool count: 55 → **56**
> - F46 imune (não usa change_event)

## Production URL

`https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app`

## Pre-flight

- [ ] Deploy lands successfully (CI + Deploy green em commit final A1/A2/A3/A4)
- [ ] Service `/health` returns 200 (`{"status":"ok","version":"0.1.0"}`)
- [ ] Tool `audit_zombie_keywords` registered (test_registered_tool_count_matches_files_on_disk 56==56 PASS)
- [ ] Pre-push gate `python scripts/check_pre_push.py` 5/5 PASS
- [ ] Schema regression `test_no_composition_keywords_in_any_schema` passa
- [ ] Unit tests `tests/unit/test_flag_zombie_keywords.py` 10/10 PASS (pure module algorithm)
- [ ] Unit tests `tests/unit/test_audit_zombie_keywords_queries.py` 4/4 PASS (GAQL builder + boundary parser)
- [ ] Integration tests `tests/integration/test_audit_zombie_keywords.py` 3/3 PASS
- [ ] MCP Inspector / Claude client conectado à URL de produção e enxerga `audit_zombie_keywords` na tool list

Production revisions: `v4-ads-mcp-XXXXX-xxx` (preencher após deploy final).

## Smoke results

Preencher conforme execução. Marcar resultado final no fim do arquivo.

| # | Test | Result | Notes |
|---|---|---|---|
| T1 | Default LAST_30_DAYS panorâmico em MO-JP | ⬜ pending | |
| T2 | `ad_group_ids` filter em MO-JP (1 ad_group específico) | ⬜ pending | |
| T3 | Custom date range em MO-JP (`start_date`+`end_date`) | ⬜ pending | |
| T4 | `limit=10` truncation em MO-JP (conta com 20+ zombies) | ⬜ pending | |
| T5 | Conta clean em ML Antiguidades (poucos zombies) | ⬜ pending | |
| T6 | Caso real cleanup massivo MO-JP recurring (dogfood numbers) | ⬜ pending | |

**Effective result:** N/6 PASS + Y DEFERRED

### F-findings emerged

_Preencher durante smoke. Template: `**F## (SEV)** — <symptom>. Fix: <plan>. Family: <bug class>.`_

Se zero F-findings: documentar explicitly "Zero F-findings novos. Sprint clean."

### Sign-off

- [ ] Pre-push gate 5/5 PASS
- [ ] Spec compliance + code quality reviewers APPROVED (A1, A2, A3)
- [ ] Production `/health` 200 (revisão final)
- [ ] T1, T2, T3, T6 PASS em MO-JP (cenários determinísticos com conta real)
- [ ] T4 PASS ou DEFERRED (env limitation se MO-JP <20 zombies — threshold ajustável)
- [ ] T5 PASS ou DEFERRED (env limitation se ML inesperadamente tem muitos zombies — pattern F41/F45)
- [ ] CLAUDE.md sprint counter atualizado (3b.35 → 3b.36) + tool count 55 → 56
- [ ] sprint-history.md updated com entry Sprint 3b.36
- [ ] findings-catalog.md atualizado se F-findings emergiram (`/findings-add` skill)
- [ ] Tool count 56 confirmado em produção (test_registered_tool_count_matches_files_on_disk 56==56)

---

## Pre-smoke setup

### Step 1: Sanity check no MCP client

Conectar Claude/Inspector à URL de produção (`https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app`) e verificar que `audit_zombie_keywords` aparece na lista de tools com parâmetros corretos:

```
# Introspect — esperar ver audit_zombie_keywords com:
# - customer_id required (pattern ^[0-9]{10}$)
# - ad_group_ids optional (array of string, max 50)
# - limit optional (integer, default 200, max 1000)
# - date_range optional (enum: LAST_7_DAYS, LAST_14_DAYS, LAST_30_DAYS, LAST_90_DAYS)
# - start_date, end_date optional (YYYY-MM-DD, pattern ^\d{4}-\d{2}-\d{2}$)
# - additionalProperties: false
```

Se `audit_zombie_keywords` não aparece ou tool count ainda 55, deploy não landed — abortar smoke.

### Step 2: Reference numbers pré-smoke MO-JP

Capturar baseline raw via `run_gaql` direto pra validação cruzada em T1/T2/T4/T6:

```
# Baseline zombies (keywords ENABLED com zero activity) em MO-JP LAST_30_DAYS
SELECT
  ad_group_criterion.criterion_id,
  ad_group_criterion.keyword.text,
  ad_group_criterion.keyword.match_type,
  ad_group_criterion.status,
  ad_group.id,
  ad_group.name,
  campaign.name,
  metrics.impressions,
  metrics.clicks,
  metrics.cost_micros,
  metrics.conversions
FROM keyword_view
WHERE segments.date DURING LAST_30_DAYS
  AND ad_group_criterion.status = 'ENABLED'
  AND ad_group_criterion.negative = FALSE
  AND metrics.impressions = 0
  AND metrics.clicks = 0
ORDER BY ad_group.name ASC, ad_group_criterion.keyword.text ASC
```

Conta esperada: MO-JP `7862230676`. Anotar:
- **Total de zombies** (esperado: 20+ pra T4 truncation funcionar — se <20, T4 DEFERRED ou ajustar threshold)
- Lista de `ad_group_id` distintos (anotar 1 ad_group com 3+ zombies pra T2 filter)
- Verificar primeiros 5 entries: nomes + ad_groups + texts (pra cross-validate T1 ordering)

```
# Count rápido de zombies em MO-JP
SELECT
  ad_group.id,
  ad_group.name,
  metrics.impressions,
  metrics.clicks
FROM keyword_view
WHERE segments.date DURING LAST_30_DAYS
  AND ad_group_criterion.status = 'ENABLED'
  AND ad_group_criterion.negative = FALSE
  AND metrics.impressions = 0
  AND metrics.clicks = 0
```

Anotar count total. Se MO-JP tem <20 zombies em LAST_30_DAYS, T4 DEFERRED (não tem volume pra truncate em limit=10) ou substituir por `limit=5` em conta com 10+ zombies.

### Step 3: Reference numbers pré-smoke ML Antiguidades

```
# Baseline zombies em ML Antiguidades (e-commerce ativo — esperado output pequeno)
SELECT
  ad_group_criterion.criterion_id,
  ad_group_criterion.keyword.text,
  ad_group.name,
  metrics.impressions,
  metrics.clicks
FROM keyword_view
WHERE segments.date DURING LAST_30_DAYS
  AND ad_group_criterion.status = 'ENABLED'
  AND ad_group_criterion.negative = FALSE
  AND metrics.impressions = 0
  AND metrics.clicks = 0
```

Conta `7455088726`. Anotar:
- Total de zombies em ML (esperado: 0 ou poucos — e-commerce ativo, keywords gerando tráfego)
- Se ML tem >50 zombies: T5 DEFERRED (env limitation, ML não é mais "conta clean") + procurar outra conta clean V4

### Step 4: Identificar ad_group target pra T2

Do baseline Step 2, escolher 1 `ad_group_id` específico de MO-JP que tenha 3+ zombies (ex.: ad_group `[GPC][JPA][LEADS][SEG][MESTRE DA OBRA]` se contiver candidatas). Anotar o ID exato pra T2 tool call.

### Step 5: Identificar date window pra T3

Pra T3 custom range, escolher window que não seja LAST_30_DAYS preset. Opções:
- **LAST_14_DAYS equivalente:** `start_date = today - 13 days`, `end_date = today`
- **Quinzena anterior:** `start_date = today - 30 days`, `end_date = today - 16 days`

Documentar window escolhido na T3 tool call.

---

## Test T1 — Default LAST_30_DAYS panorâmico em MO-JP

**Setup:** Use case primário — gestor quer scan account-wide pra detectar TODOS os zombies em 30 dias. Defaults aplicados: `date_range=LAST_30_DAYS`, `limit=200`, sem `ad_group_ids` filter.

**Tool call:**

```
audit_zombie_keywords(
  customer_id="7862230676"
)
```

**Expected output (shape):**

```json
{
  "customer_id": "7862230676",
  "date_range_resolved": {
    "start": "2026-04-21",
    "end": "2026-05-21",
    "days": 30
  },
  "filters_applied": {
    "ad_group_ids": null,
    "limit": 200
  },
  "total_zombies": N,
  "truncated": false,
  "returned_count": N,
  "zombies": [
    {
      "ad_group_id": "...",
      "ad_group_name": "...",
      "campaign_name": "...",
      "keyword_id": "...",
      "keyword_text": "...",
      "match_type": "BROAD" | "PHRASE" | "EXACT",
      "impressions": 0,
      "clicks": 0,
      "cost_brl": 0.0,
      "conversions": 0,
      "status": "ENABLED"
    },
    /* sorted ad_group_name ASC, keyword_text ASC */
  ]
}
```

**Validação:**

- [ ] Response tem `customer_id` = `"7862230676"`
- [ ] `date_range_resolved.days` == 30 (LAST_30_DAYS default)
- [ ] `date_range_resolved.start` + `end` formato YYYY-MM-DD
- [ ] `filters_applied.ad_group_ids` = `null` (sem filter)
- [ ] `filters_applied.limit` = 200 (default)
- [ ] `total_zombies` é integer >= 0
- [ ] `total_zombies` bate com baseline GAQL do Step 2
- [ ] `truncated` = `false` (se total <= 200)
- [ ] `returned_count` == `len(zombies)` == `total_zombies` (sem truncation)
- [ ] `zombies[]` ordenado: validar primeiros 3 entries têm `ad_group_name` ASC (e dentro do mesmo ad_group_name, `keyword_text` ASC)
- [ ] Cada entry: TODAS as 11 fields presentes (`ad_group_id`, `ad_group_name`, `campaign_name`, `keyword_id`, `keyword_text`, `match_type`, `impressions`, `clicks`, `cost_brl`, `conversions`, `status`)
- [ ] Cada entry tem `impressions: 0` E `clicks: 0` (definição zombie strict)
- [ ] Cada entry tem `status: "ENABLED"` (server-side filter ativo)
- [ ] `match_type` em whitelist `{"BROAD", "PHRASE", "EXACT"}` (proto-plus `.name` access, Sprint 3b.7 lesson)
- [ ] Audit_log entry criada (verificar via `/admin/audit` ou DB) — esperar 1 entry (`audit_zombie_keywords`)
- [ ] Rate_counter +1

**Result:** ⬜ pending

---

## Test T2 — `ad_group_ids` filter em MO-JP (1 ad_group específico)

**Setup:** Use case focado — gestor quer cleanup em ad_group específico (ex.: ad_group identificado pelo Step 4 com 3+ zombies). Tool deve restringir scan apenas àquele ad_group via GAQL `WHERE ad_group.id IN (X)`.

**Tool call:**

```
audit_zombie_keywords(
  customer_id="7862230676",
  ad_group_ids=["<AD_GROUP_ID_FROM_STEP_4>"]
)
```

*(Substituir `<AD_GROUP_ID_FROM_STEP_4>` pelo ID exato escolhido no pre-smoke setup Step 4.)*

**Expected output (shape):**

```json
{
  "customer_id": "7862230676",
  "date_range_resolved": {"start": "2026-04-21", "end": "2026-05-21", "days": 30},
  "filters_applied": {
    "ad_group_ids": ["<AD_GROUP_ID>"],
    "limit": 200
  },
  "total_zombies": N (apenas do ad_group),
  "truncated": false,
  "returned_count": N,
  "zombies": [
    /* TODAS as entries têm o mesmo ad_group_id */
  ]
}
```

**Validação:**

- [ ] `filters_applied.ad_group_ids` echo correto (`["<ID>"]`)
- [ ] `total_zombies` <= T1 total (subset filtrado)
- [ ] `total_zombies` bate com count GAQL específico daquele ad_group
- [ ] **Crítico:** TODAS as entries em `zombies[]` têm o MESMO `ad_group_id` (== `<AD_GROUP_ID>`)
- [ ] Nenhuma entry com `ad_group_id` diferente do filtrado
- [ ] Cada entry mantém `status: "ENABLED"` + `impressions: 0` + `clicks: 0`
- [ ] Ordering ainda por `ad_group_name ASC, keyword_text ASC` (apenas 1 ad_group, então só keyword_text matters)
- [ ] Audit_log +1 entry com `params_summary.ad_group_ids` capturado
- [ ] Rate_counter +1

**Fallback se ad_group escolhido em Step 4 tem zero zombies:**
- Substituir por outro ad_group de MO-JP com zombies confirmados via GAQL
- Documentar substituição: "ad_group_id atualizado de `<old>` para `<new>` — original tinha 0 zombies em LAST_30_DAYS"

**Result:** ⬜ pending

---

## Test T3 — Custom date range em MO-JP

**Setup:** Validar que `start_date` + `end_date` overrides `date_range` preset. Window escolhido em Step 5 (ex.: quinzena anterior). Verifica honra do `resolve_date_window` helper (`_common.py`, Sprint 3b.20).

**Tool call:**

```
audit_zombie_keywords(
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
    "ad_group_ids": null,
    "limit": 200
  },
  "total_zombies": N (apenas do window 14d),
  ...
}
```

**Validação:**

- [ ] `date_range_resolved.start` == `"2026-05-01"` (echo input)
- [ ] `date_range_resolved.end` == `"2026-05-14"` (echo input)
- [ ] `date_range_resolved.days` == 14 (cálculo: `end - start + 1` inclusive)
- [ ] **Crítico:** window honored — NÃO sobrepoe LAST_30_DAYS default
- [ ] `total_zombies` reflete keywords zombies no window específico (pode ser maior ou menor que T1 dependendo do período)
- [ ] Schema aceita ambos `start_date` + `end_date` em formato YYYY-MM-DD
- [ ] Cada entry mantém invariants (status ENABLED, impressions=0, clicks=0)
- [ ] Audit_log +1 entry com `params_summary.date_window: "2026-05-01 to 2026-05-14"`

**Validação adicional (resolve_date_window correctness):**
- [ ] Se window for 1 dia (`start == end`): `days == 1` (inclusive math)
- [ ] Se window for 30 dias completos: `days == 30`

**Result:** ⬜ pending

---

## Test T4 — `limit=10` truncation em MO-JP (conta com 20+ zombies)

**Setup:** Validar truncation pattern F22 (Sprint 3b.23 lineage). MO-JP confirmado pelo Step 2 ter 20+ zombies em LAST_30_DAYS. Tool deve retornar 10 entries + `truncated=true` + `total_zombies` reflete count TOTAL pre-truncate.

**Tool call:**

```
audit_zombie_keywords(
  customer_id="7862230676",
  limit=10
)
```

**Expected output (shape):**

```json
{
  "customer_id": "7862230676",
  "date_range_resolved": {"start": "...", "end": "...", "days": 30},
  "filters_applied": {
    "ad_group_ids": null,
    "limit": 10
  },
  "total_zombies": 20+ (count completo da conta),
  "truncated": true,
  "returned_count": 10,
  "zombies": [
    /* exatamente 10 entries, primeiros 10 pelo sort */
  ]
}
```

**Validação:**

- [ ] `filters_applied.limit` == 10 (echo input)
- [ ] `total_zombies` >= 11 (caso contrário truncation não disparou — invalid test)
- [ ] **Crítico:** `truncated == true`
- [ ] **Crítico:** `returned_count == 10`
- [ ] `len(zombies)` == 10 (array length matches `returned_count`)
- [ ] **Crítico:** `total_zombies > returned_count` (truncation real)
- [ ] Entries são os 10 PRIMEIROS pelo sort `ad_group_name ASC + keyword_text ASC` (validar comparando com T1 primeiros 10)
- [ ] Audit_log +1 entry com `params_summary.limit: 10`

**Fallback se MO-JP tem <20 zombies:**
- Ajustar `limit` pra valor menor: se MO-JP tem 12 zombies, usar `limit=5` (forces truncate de 12→5)
- Se MO-JP tem <11 zombies total: T4 DEFERRED — env limitation, conta sem volume pra truncar
- Documentar: "T4 DEFERRED — MO-JP tem apenas X zombies em LAST_30_DAYS (<11). Truncation testada via unit test `test_truncation_limit_exceeded` (50 rows + limit=10)."

**Result:** ⬜ pending

---

## Test T5 — Conta clean em ML Antiguidades (poucos zombies)

**Setup:** ML Antiguidades é e-commerce ativo — keywords geralmente gerando tráfego. Esperado: output pequeno (0-3 zombies) OR empty. Valida que tool funciona em conta cross + caso "conta saudável" (sem cleanup necessário). Verificação implícita: sort stable em N pequeno.

**Tool call:**

```
audit_zombie_keywords(
  customer_id="7455088726"
)
```

**Expected output (shape):**

```json
{
  "customer_id": "7455088726",
  "date_range_resolved": {"start": "...", "end": "...", "days": 30},
  "filters_applied": {
    "ad_group_ids": null,
    "limit": 200
  },
  "total_zombies": 0-3 (esperado pequeno),
  "truncated": false,
  "returned_count": 0-3,
  "zombies": [
    /* possivelmente [] OR poucas entries */
  ]
}
```

**Validação:**

- [ ] `customer_id` == `"7455088726"`
- [ ] `total_zombies` < 10 (esperado em conta clean — se >50, DEFERRED)
- [ ] `truncated == false` (sem necessidade de truncar)
- [ ] `returned_count == total_zombies == len(zombies)` (consistência)
- [ ] Shape válido mesmo se `zombies == []` (empty list, não null)
- [ ] Output bate com baseline GAQL do Step 3
- [ ] Audit_log +1 entry

**Fallback se ML Antiguidades tem >50 zombies:**
- T5 **DEFERRED** — env limitation, ML inesperadamente "suja"
- Anotar: "T5 DEFERRED — ML Antiguidades retornou X zombies (esperado <10 em conta clean). Pattern F41/F45 (env limitation, não bug). Coverage via unit `test_empty_rows_returns_empty` + `test_total_count_pre_truncate_preserved`."
- Alternativa: procurar outra conta clean V4 (ex.: account novinha sem histórico) e re-rodar

**Result:** ⬜ pending *(possível DEFERRED — env limitation)*

---

## Test T6 — Caso real cleanup massivo MO-JP recurring (dogfood numbers)

**Setup:** Reproduz workflow recurring V4 — dogfood 2026-05-19 cleanup massivo MO-JP. Wellington periodicamente identifica zombies pra pause/remove. Tool deve consolidar workflow (antes: `get_keyword_performance` → mental filter → decision) em 1 call retornando lista actionable.

**Tool call:**

```
audit_zombie_keywords(
  customer_id="7862230676"
)
```

*(Mesma call que T1 — diferença é foco da validação operacional, não shape.)*

**Expected output (operational interpretation):**

```json
{
  "total_zombies": N (N >= 10 esperado em MO-JP recurring),
  "zombies": [
    /* keywords ENABLED com zero activity:
       - Provavelmente novas (criadas semana passada, ainda aprendendo) 
       - OR antigas com targeting errado
       - OR keywords muito específicas sem busca
    */
  ]
}
```

**Validação:**

- [ ] `total_zombies >= 10` (MO-JP é conta production V4 com keywords reais — esperado volume)
- [ ] Pelo menos 3 entries diferentes em `zombies[]` (sample de variedade)
- [ ] Cada entry tem `keyword_text` realista (não placeholder, não vazio)
- [ ] Cada entry tem `ad_group_name` + `campaign_name` populated (não vazios)
- [ ] Match_type distribution: pelo menos 2 dos 3 tipos (BROAD, PHRASE, EXACT) presentes — sugere diversidade real
- [ ] **Insight operacional:** Wellington pode usar output como input pra `pause_keywords` (mutate tool existente). Keywords listadas são candidates legítimas pra pause/remove. Tool entrega valor real (cleanup decision em 1 call vs ~5 queries manuais).
- [ ] Audit_log +1 entry

**Validação cross-tool (cleanup workflow real):**

Após T6, simular workflow next-step (não executar mutate, só verificar viabilidade):

- [ ] Capturar `keyword_id` de 1 zombie do output
- [ ] Confirmar via `get_keyword_performance` que mesma keyword retorna metrics zero
- [ ] Mental model: gestor pode passar lista de `keyword_id`s do output pra `pause_keywords({customer_id, keyword_ids: [...]})` next call

**Fallback se MO-JP retorna <5 zombies em LAST_30_DAYS:**
- Provavelmente Wellington fez cleanup recente — conta "limpa" temporariamente
- T6 **PASS com nota:** "Workflow validado, count baixo confirma cleanup recente. Re-run em sprint próxima com window LAST_90_DAYS (`date_range=LAST_90_DAYS`) pra recapturar volume histórico."
- Alternativa: rodar com `date_range=LAST_90_DAYS` pra forçar volume

**Result:** ⬜ pending

---

## Per-value empirical probe (Sprint 3b.19A.1 convention)

**Probe do enum `date_range`** — Schema declara whitelist 4 valores: `LAST_7_DAYS`, `LAST_14_DAYS`, `LAST_30_DAYS`, `LAST_90_DAYS`. Como `audit_zombie_keywords` é tool **read-only puro**, probe verifica que cada preset é aceito + resolvido corretamente pelo `resolve_date_window` (Sprint 3b.20):

| # | Enum value | Expected `days` | Result |
|---|---|---|---|
| P1 | `LAST_7_DAYS` | 7 | ⬜ pending |
| P2 | `LAST_14_DAYS` | 14 | ⬜ pending |
| P3 | `LAST_30_DAYS` | 30 | ⬜ pending (coverage via T1/T2/T4/T5/T6) |
| P4 | `LAST_90_DAYS` | 90 | ⬜ pending |
| P5 | `LAST_60_DAYS` (NOT_IN_WHITELIST) | Schema reject (HTTP 400) | ⬜ pending |

**Tool calls (probe rápido):**

```
# P1
audit_zombie_keywords(customer_id="7862230676", date_range="LAST_7_DAYS")
# expect: date_range_resolved.days == 7

# P2
audit_zombie_keywords(customer_id="7862230676", date_range="LAST_14_DAYS")
# expect: date_range_resolved.days == 14

# P4
audit_zombie_keywords(customer_id="7862230676", date_range="LAST_90_DAYS")
# expect: date_range_resolved.days == 90

# P5 (negative test — schema rejection)
audit_zombie_keywords(customer_id="7862230676", date_range="LAST_60_DAYS")
# expect: schema validation error (HTTP 400 or MCP equivalent)
```

**Validação por probe:**
- [ ] P1: `date_range_resolved.days == 7`, response shape correto
- [ ] P2: `date_range_resolved.days == 14`, response shape correto
- [ ] P3: cobertura herdada de T1/T2/T4/T5/T6 (já validado em testes principais)
- [ ] P4: `date_range_resolved.days == 90`, response shape correto
- [ ] P5: schema reject `LAST_60_DAYS` (não está no enum whitelist)

**Critério PASS do probe completo:** 4 presets aceitos + 1 valor fora whitelist rejeitado.

**Convention:** every value in tool schema whitelist MUST be empirically validated. Bug history: F17/F18/F19/F25/F27/F31/F32/F34/F36/F44 — design-gap-via-SDK-ambiguity. Pra esta tool (read-only com preset enum), validation = preset resolve corretamente em `resolve_date_window`.

---

## V4 invariants validation

| Invariant | Aplicável | Enforcement | How smoke verifies |
|---|---|---|---|
| country_code = BR | N/A | N/A — tool não toca geo data | — |
| language_code = pt-BR | ✅ Description | Tool description string PT-BR ("Detecta keywords zumbis...", "Pre-cleanup decision tool...") | Pre-flight: inspector mostra description PT-BR |
| currency_code = BRL | ✅ Output | `cost_brl` field name explícito (não `cost_micros` raw); `cost_micros / 1_000_000.0` em `parse_keyword_view_row` | T1 valida cada entry tem `cost_brl: 0.0` (zombie definição) |
| timezone = -03:00 | N/A | N/A — tool não retorna timestamps em response shape V0; date_range usa GAQL `segments.date` que respeita account timezone server-side | — |
| LGPD consent | N/A | Read-only sem envio de PII; keywords config já era exposta via outros tools (`get_keyword_performance`, `run_gaql`) | Audit_log captura quem acessou (Wellington) — herdado de `run_report(audit_this_call=True)` |
| Schema whitelist (3b.19A) | ✅ Input | Enum `date_range` 4 V4 valores | Per-value probe P1-P5 |
| status=ENABLED-only filter | ✅ Hardcoded | GAQL `WHERE ad_group_criterion.status = 'ENABLED'` server-side | T1/T6 validam cada entry tem `status: "ENABLED"` exclusively |
| negative=FALSE filter | ✅ Hardcoded | GAQL `WHERE ad_group_criterion.negative = FALSE` server-side | Implicit (tool não retorna negative keywords) |
| No composition keywords (3b.19B.1) | ✅ Schema | Schema sem `oneOf/allOf/anyOf` em qualquer nesting level | Regression `test_no_composition_keywords_in_any_schema` (pre-push) |
| F22 truncation pattern (3b.23) | ✅ Output | `total_zombies` POST-filter + `truncated: bool` + `returned_count <= total_zombies` | T4 valida `truncated=true` quando exceeds limit |
| F46 imune | ✅ Architecture | Não usa `change_event` (GAQL `keyword_view` orthogonal); `gaql_date_clause` from `_common.py` é date semantics independente | N/A — implicit immunity |

---

## Cleanup post-smoke

Não há cleanup necessário:
- `audit_zombie_keywords` é read-only puro (zero mutations)
- 1 GAQL call em `keyword_view` por chamada tool
- Audit_log entries ficam permanentes (rastreio histórico, `audit_this_call=True`)
- Rate_counter incrementa normalmente: 6 testes principais × 1 call + 4 probes × 1 call = 10 GAQL calls total no smoke

---

## Notas pra Wellington pós-smoke

1. **Uso real após smoke:** workflow cleanup massivo recurring. Cadência sugerida: Wellington roda `audit_zombie_keywords(customer_id=<conta>)` semanalmente OR após batch de keyword creation. Output identifica candidates pra pause/remove em massa. Decisão informada: zombies novos (criados <14d) provavelmente aprendendo, zombies antigos (>30d) candidates fortes pra remove.
2. **Workflow combinado:** Tool retorna `keyword_id[]` no array. Gestor pode passar lista direto pra `pause_keywords({customer_id, keyword_ids: [...]})` (mutate existente) numa segunda call. Atômico em batch via `apply_change(confirm_token=...)` se mutate exigir confirmação.
3. **Se T4 DEFERRED (MO-JP <20 zombies):** unit test `test_truncation_limit_exceeded` (50 rows + limit=10) garante cobertura algorítmica. DEFERRED é env limitation (pattern F41/F45), não bug.
4. **Se T5 DEFERRED (ML inesperadamente "suja"):** procurar outra conta clean V4 OR documentar que ML "mudou perfil" desde brainstorming. Pattern F41/F45 mantido.
5. **Se T6 retorna <5 zombies:** PROVÁVEL que Wellington fez cleanup recente. Re-run com `date_range=LAST_90_DAYS` pra recapturar volume histórico OR aceitar como sinal positivo de hygiene da conta.
6. **V1+ candidates:** `min_impressions` threshold (soft zombie semantics), variant `audit_unproductive_keywords` (cost>0 + conv=0), severity tiers, ad_group_name search filter.
7. **F46 imune:** tool não usa `change_event` → orthogonal ao GAQL BETWEEN end_date midnight bug. Cross-checked no único GAQL query do tool (usa `keyword_view` + `segments.date` DURING/BETWEEN via `gaql_date_clause` que aplica `+1 day` em end_date pós-F46 fix Sprint 3b.34).
8. **Sprint 3b.37+ candidates:** audit_orphan_smart_actions (ICE 288), audit_negative_criterion_overlap, W3 `audit_goal_attribution` follow-up se emergir gap, ou audit_log gap fix em `run_gaql`/`get_my_audit_log`/`get_my_rate_limit_status`. Decisão Wellington baseada em dogfood real.
9. **Tool count:** atualizar CLAUDE.md sprint counter (3b.35 → 3b.36) e sprint-history.md após signoff.
