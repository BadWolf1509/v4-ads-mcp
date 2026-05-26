# Phase M.3 — manual smoke runbook (Meta performance trio: campaign + ad_set + ad)

**Purpose:** Validar Sprint M.3 — 3 tools Meta de performance core (`meta_get_campaign_performance` + `meta_get_ad_set_performance` + `meta_get_ad_performance`) com paridade direta Google `get_*_performance`. Single shared module `src/meta_ads/insights.py` (~150 LOC) + 3 thin handlers (~30 LOC cada) reusando `run_meta_graph_get` + `resolve_meta_date_window` + `meta_ad_accounts.get_by_id`. Bucket=always pra campaign (Pareto Meta top usage), bucket=defer pra ad_set + ad. Sprint contribui +3-6 calls/dia ao Caminho B+ Meta volume (500 calls/15d threshold pra Full Access re-submit).

**Operator:** wellinton.ribeiro@v4company.com
**Business Manager Meta:** V4 Lima Soares & Co (João Pessoa, PB)
**Ad accounts smoke sugeridos:**
- ATIVO + spend recente + Pixel purchase configurado: ICSER `act_1489398022911451` ou Wellington personal `act_383566922510173`
- Alternativa qualquer conta V4 LS&Co com spend > 0 últimos 30 dias

**Spec:** `docs/superpowers/specs/2026-05-26-sprint-m-3-meta-campaign-performance-design.md`
**Plan:** `docs/superpowers/plans/2026-05-26-sprint-m-3-meta-campaign-performance.md`
**Sprint family parent:** `docs/superpowers/specs/2026-05-24-meta-ads-incorporation-design.md` (M.1 → M.25)
**Predecessor:** `docs/operacao/phase-M-2b-bootstrap.md` (M.2b — `meta_get_account_overview` + App Review prep)

> **Escopo M.3 confirmado:**
> - Tool count: 59 → **62** (3 novas Meta MCP tools = 4 total na família Meta)
> - Bucket distribution: 21+1 always = **22 always** + 38+2 defer = **40 defer**
> - Shipped commits: `e76b7f2` + `7f67009` + `6f70231` + `7bb4484` + `940cb57`
> - ZERO migrations novas (reusa `audit_log.platform`, `meta_rate_counters` shipped M.2a)
> - ZERO endpoints novos (read-only sprint, sem OAuth touch)

## Production URL

`https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app`

## Pre-flight

- [ ] Deploy lands successfully (CI + Deploy green em commit final M.3, SHA `940cb57` ou later)
- [ ] Service `/health` returns 200 (`{"status":"ok","version":"0.1.0"}`)
- [ ] 3 tools `meta_get_campaign_performance` + `meta_get_ad_set_performance` + `meta_get_ad_performance` registered (`test_registered_tool_count_matches_files_on_disk` 62==62 PASS)
- [ ] Bucket count guard: `test_list_tools_anthropic_alwaysload_count_matches_always_bucket` 22 always = 22 alwaysLoad PASS
- [ ] Pre-push gate `python scripts/check_pre_push.py` 5/5 PASS
- [ ] Schema regression `test_no_composition_keywords_in_any_schema` passa pra 3 tools novas
- [ ] Date schema regression `test_date_range_schemas_are_explicit` passa pra 3 tools novas
- [ ] Unit tests `tests/unit/test_meta_insights.py` PASS (~17 tests pure module)
- [ ] Integration tests `tests/integration/test_meta_get_campaign_performance.py` PASS (~6 tests)
- [ ] Integration tests `tests/integration/test_meta_get_ad_set_performance.py` PASS (~4 tests)
- [ ] Integration tests `tests/integration/test_meta_get_ad_performance.py` PASS (~4 tests)
- [ ] OAuth Meta Wellington ativo desde M.2b smoke (não foi revogado) — `meta_oauth_connections.revoked_at IS NULL` pra `<wellington_uuid>` + `token_expires_at > now() + 7d`
- [ ] `meta_ad_accounts` cache populado pós-M.2a/M.2b (12 ad accounts V4 LS&Co BM sincronizadas, conta de teste ATIVO presente)
- [ ] MCP client (Claude Code) conectado à URL produção e enxerga 3 tools novas após restart

Production revisions: `v4-ads-mcp-XXXXX-xxx` (preencher após deploy final M.3).

## Smoke results

Preencher conforme execução. Marcar resultado final no fim do arquivo.

| # | Test | Result | Notes |
|---|---|---|---|
| T1 | `meta_get_campaign_performance` happy path (conta V4 ATIVO + spend recente + Pixel) | ⬜ pending | |
| T2 | `meta_get_ad_set_performance` happy path (mesma conta T1) | ⬜ pending | |
| T3 | `meta_get_ad_performance` happy path (mesma conta T1) | ⬜ pending | |
| T4 | `effective_status="ALL"` inclui ARCHIVED rows (count_all ≥ count_active) | ⬜ pending | |
| T5 | Custom date range `start_date`+`end_date` sobrescreve `date_range` preset | ⬜ pending | |
| T6 | Per-value probe — cada `effective_status` enum (ACTIVE/PAUSED/ARCHIVED/ALL) | ⬜ pending | |
| T7 | Error path — `ad_account_id` inexistente retorna friendly error PT-BR | ⬜ pending | |
| T8 | Error path — token expirado retorna PT-BR reconnect message (skippable) | ⬜ pending | |
| T9 | BUC tracking — após 5 calls, `meta_rate_counters.calls_used` incrementa | ⬜ pending | |
| T10 | `audit_log.platform='meta'` + `provider_request_id` populated | ⬜ pending | |

**Effective result:** N/10 PASS

### F-findings emerged

_Preencher durante smoke. Template: `**F## (SEV)** — <symptom>. Fix: <plan>. Family: <bug class>.`_

Se zero F-findings: documentar explicitly "Zero F-findings novos. Sprint clean."

### Sign-off

- [ ] Pre-push gate 5/5 PASS
- [ ] Spec compliance + code quality reviewers APPROVED
- [ ] Production `/health` 200 (revisão final)
- [ ] T1 PASS (campaign happy path — proof of life Meta Insights pipeline)
- [ ] T2 PASS (ad set happy path + `ad_set_id` snake_case + `daily_budget_brl` cents conversion)
- [ ] T3 PASS (ad happy path + creative_id + parents campaign/ad_set)
- [ ] T4 PASS (effective_status ALL inclui ARCHIVED — filter logic correta)
- [ ] T5 PASS (custom date range override — params.time_range custom não preset)
- [ ] T6 PASS (4 enum values empiricamente validados — remover/documentar rejeitados)
- [ ] T7 PASS (ad_account_id inexistente → friendly PT-BR, sem Graph API call wasted)
- [ ] T8 PASS ou DEFERRED (token expirado — skip OK se sem conta secundária)
- [ ] T9 PASS (BUC tracking incrementa — Caminho B+ volume counting works)
- [ ] T10 PASS (audit_log gravado com platform='meta' + provider_request_id)
- [ ] CLAUDE.md "Shipped — 59 MCP tools" tabela updated (59 → 62) + Last updated stamp
- [ ] sprint-history.md entry Sprint M.3
- [ ] findings-catalog.md atualizado se F-findings emergiram (`/findings-add` skill)
- [ ] Tool count 62 confirmado em produção (`test_registered_tool_count_matches_files_on_disk` 62==62)

---

## Pre-smoke setup

### Step 1: Sanity check no MCP client + restart pra refresh tool cache

Após deploy final M.3, reiniciar Claude Code pra refresh tool cache:

1. Sair completamente do Claude Code (Cmd+Q / Alt+F4)
2. Reabrir
3. Verificar que MCP server v4-ads conecta sem erro
4. Sistema reminder/tool list deve mostrar **3 novas tools Meta** (62 total — 22 always + 40 defer)
5. Especificamente verificar:
   - `meta_get_campaign_performance` aparece como **always-loaded** (bucket=always, `_meta.anthropic/alwaysLoad: true`)
   - `meta_get_ad_set_performance` aparece **deferred** (bucket=defer)
   - `meta_get_ad_performance` aparece **deferred** (bucket=defer)

Se 3 tools não aparecem ou count ainda 59, deploy não landed completamente — abortar smoke e investigar Cloud Run logs.

### Step 2: Wellington UUID + escolha de ad_account_id de smoke

Capturar `manager_id` UUID Wellington pra queries SQL em T9/T10:

```sql
-- Via Supabase SQL Editor (mcp__supabase__execute_sql ou dashboard)
SELECT id, email FROM managers WHERE email = 'wellinton.ribeiro@v4company.com';
-- Anotar id retornado (UUID) — usar em queries SQL deste smoke
```

Anotar `<wellington_uuid>` pra todas as queries SQL deste smoke.

Escolher ad_account_id de smoke (precisa ser ATIVO + ter spend > 0 últimos 30 dias + ≥1 purchase event Pixel configurado pra validar `purchases` extraction):

```sql
SELECT ad_account_id, account_name, account_status, currency
FROM meta_ad_accounts
WHERE account_status = 1  -- ATIVO
ORDER BY account_name;
```

Sugerido **ICSER `act_1489398022911451`** ou **Wellington personal `act_383566922510173`**. Anotar `<smoke_account_id>` + `<smoke_account_name>` pra usar em T1-T6.

### Step 3: Baseline DB state pré-smoke

Pre-smoke baseline `meta_rate_counters` pra ad account escolhida (delta T9):

```sql
SELECT app_id, ad_account_id, date, calls_used, last_throttle_pct
FROM meta_rate_counters
WHERE ad_account_id = '<smoke_account_id>'
  AND date = CURRENT_DATE
ORDER BY date DESC LIMIT 1;
-- Anotar calls_used baseline (pode ser 0 se primeiro uso do dia)
```

Pre-smoke baseline `audit_log` Meta entries (delta lookback):

```sql
SELECT COUNT(*) AS meta_entries_pre_smoke
FROM audit_log
WHERE platform = 'meta'
  AND occurred_at >= CURRENT_DATE;
-- Anotar count — smoke adicionará ≥10 entries (T1+T2+T3+T4+T5+T6×4+T7+T9×5+T10 audit calls)
```

Pre-smoke baseline OAuth token expiry check:

```sql
SELECT manager_id, fb_email, token_expires_at, revoked_at,
       EXTRACT(DAY FROM token_expires_at - NOW()) AS days_left
FROM meta_oauth_connections
WHERE manager_id = '<wellington_uuid>'
  AND revoked_at IS NULL;
-- Esperar days_left > 7 — se ≤7, reconnect via /admin ANTES de iniciar smoke
```

### Step 4: Cloud Run logs streaming setup

Em terminal separado, manter logs streaming pra captar errors durante Graph calls:

```bash
gcloud run services logs read v4-ads-mcp \
  --region=southamerica-east1 \
  --project=v4-ads-mcp-prod \
  --limit=50
```

Pra streaming contínuo, usar `--follow`.

---

## Test T1 — `meta_get_campaign_performance` happy path

**Setup:** Primeira tool Meta de performance core. Wellington invoca via Claude Code em ad_account ATIVO com spend recente + Pixel purchase configurado. Valida ponta-a-ponta: OAuth token check → 1 Graph call `/insights?level=campaign` → parse rows → sort spend_brl DESC → return shape com campaign_id/name/objective + métricas comuns + purchases/leads extracted top-level. Validação Pareto Meta — esta é a tool que gestor V4 pede primeiro.

**Pré-requisito:** Step 2 setup done. `<smoke_account_id>` escolhido + tem campanha com spend > 0 últimos 30 dias + Pixel `purchase` event configurado.

**Steps:**

1. Claude Code → prompt PT-BR: **"Me mostra a performance das campanhas Meta da conta `<smoke_account_id>` últimos 30 dias"**
2. Claude resolve intent → invoca:

```
meta_get_campaign_performance(
  ad_account_id="<smoke_account_id>",
  date_range="LAST_30_DAYS"
)
```

3. Tool internally:
   - `resolve_meta_date_window` → `(today - 29d, today)` LAST_30_DAYS
   - `meta_ad_accounts.get_by_id` → row ATIVO
   - `build_insights_call(level="campaign", ...)` → `(edge, params)` com `filtering=[{"field":"effective_status","operator":"IN","value":["ACTIVE"]}]`
   - `run_meta_graph_get` (audit_this_call=True, estimated_calls=1)
   - `parse_insights_row(row, "campaign")` por linha
   - sort `spend_brl` DESC
   - return

**Expected response shape:**

```json
{
  "status": "success",
  "ad_account_id": "<smoke_account_id>",
  "ad_account_name": "<smoke_account_name>",
  "currency": "BRL",
  "date_range": {"start": "2026-04-26", "end": "2026-05-25"},
  "rows": [
    {
      "campaign_id": "23842...",
      "campaign_name": "...",
      "objective": "OUTCOME_SALES",
      "effective_status": "ACTIVE",
      "effective_status_label": "ATIVO",
      "spend_brl": 1234.56,
      "impressions": 50000,
      "clicks": 800,
      "ctr": 0.016,
      "cpc_brl": 1.54,
      "reach": 12345,
      "frequency": 4.05,
      "purchases": 12,
      "purchases_value_brl": 5500.00,
      "purchase_roas": 4.45,
      "leads": 3
    }
    // ... ordenado por spend_brl DESC
  ],
  "total_rows": N
}
```

**Validação:**

- [ ] Tool invocada sem ImportError facebook-business / sem MetaTokenExpiredError
- [ ] `status == "success"`
- [ ] `ad_account_id` matches `<smoke_account_id>`
- [ ] `ad_account_name` matches `<smoke_account_name>` (do cache local meta_ad_accounts)
- [ ] `currency == "BRL"` (V4 invariant)
- [ ] `date_range.start` = `today - 29d` (LAST_30_DAYS inclusivo hoje)
- [ ] `date_range.end` = `today`
- [ ] `rows` é array não-vazio (conta tem campanhas ativas)
- [ ] `rows[0].spend_brl >= rows[1].spend_brl >= ...` (ordenação DESC validada)
- [ ] `rows[0]` contém TODAS as keys: `campaign_id`, `campaign_name`, `objective`, `effective_status`, `effective_status_label`, `spend_brl`, `impressions`, `clicks`, `ctr`, `cpc_brl`, `reach`, `frequency`, `purchases`, `purchases_value_brl`, `purchase_roas`, `leads`
- [ ] `effective_status_label == "ATIVO"` (PT-BR enum, NÃO Meta raw "ACTIVE")
- [ ] `rows[0].purchases` é int >= 1 (Pixel purchase configurado — sanity check)
- [ ] `rows[0].purchases_value_brl` é float >= 0
- [ ] `rows[0].ctr` é float entre 0.0 e 1.0 (decimal, NÃO percentual — Meta 1.6 → 0.016)
- [ ] `total_rows == len(rows)` (consistência)
- [ ] Response time < 5s (1 Graph call sequencial)
- [ ] Cloud Run logs sem ERROR/CRITICAL durante execução

**Result:** ⬜ pending

---

## Test T2 — `meta_get_ad_set_performance` happy path

**Setup:** Segunda tool — granular ad set level. Mesma conta T1. Valida: `ad_set_id` (snake_case na response, NÃO `adset_id` raw Meta) + `daily_budget_brl` conversion cents/100 (Meta retorna em cents) ou `None` pra CBO campaigns + `optimization_goal` + `billing_event` populados.

**Pré-requisito:** T1 PASS. Mesmo `<smoke_account_id>`.

**Steps:**

1. Claude Code → prompt: **"Performance dos ad sets dessa mesma conta últimos 30 dias"**
2. Claude invoca:

```
meta_get_ad_set_performance(
  ad_account_id="<smoke_account_id>",
  date_range="LAST_30_DAYS"
)
```

3. Tool internally: mesmo padrão T1 com `level="adset"` em `build_insights_call`

**Expected response shape (foco diferenças vs T1):**

```json
{
  "status": "success",
  "ad_account_id": "<smoke_account_id>",
  ...
  "rows": [
    {
      "ad_set_id": "1234567...",          // snake_case (NÃO adset_id)
      "ad_set_name": "...",
      "campaign_id": "23842...",          // parent campaign
      "campaign_name": "...",
      "optimization_goal": "OFFSITE_CONVERSIONS",
      "billing_event": "IMPRESSIONS",
      "daily_budget_brl": 50.00,          // cents/100 conversion OR null se CBO
      "effective_status": "ACTIVE",
      "effective_status_label": "ATIVO",
      // ... common fields T1 ...
    }
  ],
  "total_rows": N
}
```

**Validação:**

- [ ] `status == "success"`
- [ ] `rows[0]` contém key `ad_set_id` (snake_case — NÃO `adset_id`)
- [ ] `rows[0]` contém key `ad_set_name` (snake_case)
- [ ] `rows[0]` contém parents `campaign_id` + `campaign_name`
- [ ] `rows[0].optimization_goal` populado (string Meta enum, ex: `OFFSITE_CONVERSIONS`, `LINK_CLICKS`, `LEAD_GENERATION`)
- [ ] `rows[0].billing_event` populado (string Meta enum, ex: `IMPRESSIONS`, `LINK_CLICKS`)
- [ ] `rows[0].daily_budget_brl`:
   - SE ad set tem daily budget ABO → float > 0 (validar Wellington manualmente: valor / 100 ≈ valor visualizado no Meta Business Suite)
   - SE ad set é CBO (orçamento no campaign level) → `null` (Python None → JSON null)
- [ ] Mesmas common metrics validadas em T1 (spend_brl, impressions, clicks, ctr decimal, cpc_brl, reach, frequency, purchases, purchases_value_brl, purchase_roas, leads)
- [ ] `rows` ordenadas `spend_brl` DESC
- [ ] `total_rows == len(rows)`

**Failure modes investigation:**

- `rows[0]` retorna `adset_id` em vez de `ad_set_id` → bug em `parse_insights_row` level="adset" branch não está convertendo snake_case
- `daily_budget_brl` retorna em centavos (5000 em vez de 50.00) → bug parser não está dividindo por 100
- `daily_budget_brl` retorna 0.0 em vez de null pra CBO → bug `if row.get("daily_budget")` truthy check, validar lógica
- `optimization_goal` / `billing_event` vazios → conta sem ad sets ATIVOS recentes, escolher conta diferente

**Result:** ⬜ pending

---

## Test T3 — `meta_get_ad_performance` happy path

**Setup:** Terceira tool — granular ad level. Mesma conta T1. Valida: `ad_id` + `creative_id` (pode ser None se ad sem creative associado — raro mas possível) + parents `ad_set_id` + `campaign_id`.

**Pré-requisito:** T1 + T2 PASS. Mesmo `<smoke_account_id>`.

**Steps:**

1. Claude Code → prompt: **"Performance dos ads (criativos) dessa conta últimos 30 dias"**
2. Claude invoca:

```
meta_get_ad_performance(
  ad_account_id="<smoke_account_id>",
  date_range="LAST_30_DAYS"
)
```

3. Tool internally: mesmo padrão com `level="ad"` em `build_insights_call`

**Expected response shape (foco diferenças vs T1/T2):**

```json
{
  "status": "success",
  ...
  "rows": [
    {
      "ad_id": "9999...",
      "ad_name": "...",
      "ad_set_id": "1234567...",        // snake_case parent ad set
      "ad_set_name": "...",
      "campaign_id": "23842...",        // parent campaign
      "campaign_name": "...",
      "creative_id": "8888...",         // ad creative ref OR null
      "effective_status": "ACTIVE",
      "effective_status_label": "ATIVO",
      // ... common fields ...
    }
  ],
  "total_rows": N
}
```

**Validação:**

- [ ] `status == "success"`
- [ ] `rows[0]` contém key `ad_id`
- [ ] `rows[0]` contém key `ad_name`
- [ ] `rows[0]` contém parent `ad_set_id` (snake_case)
- [ ] `rows[0]` contém parent `ad_set_name`
- [ ] `rows[0]` contém parent `campaign_id`
- [ ] `rows[0]` contém parent `campaign_name`
- [ ] `rows[0].creative_id` populado (string Meta ID) OU `null` (raro, ad sem creative ref)
- [ ] Mesmas common metrics validadas em T1
- [ ] `rows` ordenadas `spend_brl` DESC
- [ ] `total_rows == len(rows)`

**Failure modes investigation:**

- `creative_id` field ausente do response → bug `parse_insights_row` ad branch não retornando key, ou Meta não retornando creative_id pro ad (validar Graph response raw nos logs)
- Ad sem creative_id e tool falha em vez de retornar None → bug parser não tolera missing field

**Result:** ⬜ pending

---

## Test T4 — `effective_status="ALL"` inclui ARCHIVED rows

**Setup:** Validar lógica de filtering em `build_insights_call`: quando `effective_status="ALL"`, parâmetro `filtering` é OMITIDO do Graph call (mais permissivo). Quando `effective_status` é qualquer outro valor, `filtering=[{"field":"effective_status","operator":"IN","value":["<VAL>"]}]` é injetado.

**Pré-requisito:** Conta tem pelo menos 1 campanha ARCHIVED na história (Wellington pode arquivar campanha de teste manualmente no Business Suite SE necessário).

**Steps:**

1. Run com `effective_status="ACTIVE"` (default):

```
meta_get_campaign_performance(
  ad_account_id="<smoke_account_id>",
  date_range="LAST_30_DAYS"
  // effective_status default = "ACTIVE"
)
```

Anotar `count_active = total_rows`.

2. Run com `effective_status="ALL"`:

```
meta_get_campaign_performance(
  ad_account_id="<smoke_account_id>",
  date_range="LAST_30_DAYS",
  effective_status="ALL"
)
```

Anotar `count_all = total_rows`.

3. Inspecionar `rows` da 2ª run — esperar pelo menos 1 row com `effective_status: "ARCHIVED"` OU `effective_status: "PAUSED"`.

**Validação:**

- [ ] Ambas runs retornam `status: "success"`
- [ ] `count_all >= count_active` (ALL é superset)
- [ ] Pelo menos 1 row em 2ª run tem `effective_status` diferente de `"ACTIVE"` (PAUSED/ARCHIVED/etc)
- [ ] Se conta tem ARCHIVED histórico: pelo menos 1 row com `effective_status: "ARCHIVED"` + `effective_status_label: "ARQUIVADO"` (PT-BR)
- [ ] Cloud Run logs 1ª run: params da Graph call contém `filtering` (validar via DEBUG log `meta.graph.call.start`)
- [ ] Cloud Run logs 2ª run: params da Graph call NÃO contém `filtering` (ALL = sem filter injection)

**Failure modes investigation:**

- `count_all == count_active` → conta não tem outros statuses ARCHIVED/PAUSED, T4 INCONCLUSIVO. Escolher outra conta OR Wellington arquiva 1 campanha de teste.
- `count_all < count_active` → bug serious em `build_insights_call` — ALL está injetando filter restritivo
- `effective_status="ALL"` retorna erro Meta → bug `build_insights_call` está enviando `filtering=null` em vez de omit completo

**Result:** ⬜ pending

---

## Test T5 — Custom date range `start_date`+`end_date` sobrescreve preset

**Setup:** Validar `resolve_meta_date_window`: quando `start_date` + `end_date` ambos fornecidos, sobrescreve `date_range` preset. Custom range é prioridade.

**Pré-requisito:** Wellington escolhe período passado conhecido com spend > 0 (e.g. Abril 2026 inteiro).

**Steps:**

1. Run com preset `LAST_7_DAYS`:

```
meta_get_campaign_performance(
  ad_account_id="<smoke_account_id>",
  date_range="LAST_7_DAYS"
)
```

Anotar `date_range_preset` retornado (deve ser `{"start": "<today-6d>", "end": "<today>"}`).

2. Run com custom range (mesmo `date_range="LAST_7_DAYS"` propositadamente — deve ser IGNORADO):

```
meta_get_campaign_performance(
  ad_account_id="<smoke_account_id>",
  date_range="LAST_7_DAYS",
  start_date="2026-04-01",
  end_date="2026-04-30"
)
```

Anotar `date_range_custom` retornado.

**Validação:**

- [ ] 1ª run retorna `date_range.start == today - 6d` E `date_range.end == today` (preset aplicado)
- [ ] 2ª run retorna `date_range.start == "2026-04-01"` E `date_range.end == "2026-04-30"` (custom sobrescreve preset)
- [ ] 2ª run retorna `rows` diferentes da 1ª (período diferente, campanhas/spend diferentes)
- [ ] Cloud Run logs 2ª run: `params.time_range` JSON contém `"since":"2026-04-01","until":"2026-04-30"` (não datas LAST_7_DAYS)

**Failure modes investigation:**

- 2ª run retorna `date_range` LAST_7_DAYS dates → bug `resolve_meta_date_window` não está priorizando custom range
- 2ª run retorna error PT-BR "Datas inválidas" → bug parsing start_date/end_date — validar formato `YYYY-MM-DD` aceito pelo schema regex
- Schema validation rejeita request (Anthropic-level) → bug schema patterns `^\d{4}-\d{2}-\d{2}$` mal escritas

**Result:** ⬜ pending

---

## Test T6 — Per-value probe (Sprint 3b.19A.1 convention) — `effective_status` enum

**Setup:** Per-value empirical validation de TODOS os 4 valores do `effective_status` enum. Cada valor é run real contra Graph API real — se algum retornar `error`, é F-finding novo + REMOVER valor do schema. Convenção CLAUDE.md mandatory.

**Pré-requisito:** T1 PASS. Conta `<smoke_account_id>` ainda válida.

**Steps:**

Pra cada `<status>` em `[ACTIVE, PAUSED, ARCHIVED, ALL]`:

```
meta_get_campaign_performance(
  ad_account_id="<smoke_account_id>",
  date_range="LAST_30_DAYS",
  effective_status="<status>"
)
```

Anotar `status` retornado + `total_rows` + qualquer error.

**Resultado per-value:**

| Enum value | Esperado | Actual `status` | Actual `total_rows` | Pass/Fail |
|---|---|---|---|---|
| `ACTIVE` | `status="success"` (pode ter 0 rows OK) | ⬜ pending | ⬜ pending | ⬜ |
| `PAUSED` | `status="success"` (pode ter 0 rows OK) | ⬜ pending | ⬜ pending | ⬜ |
| `ARCHIVED` | `status="success"` (pode ter 0 rows OK) | ⬜ pending | ⬜ pending | ⬜ |
| `ALL` | `status="success"` (pode ter 0 rows OK) | ⬜ pending | ⬜ pending | ⬜ |

**Validação:**

- [ ] Todos 4 valores retornam `status: "success"` (mesmo que `rows: []` empty)
- [ ] Pra cada `effective_status` específico (NÃO ALL), rows retornadas (se houver) tem `effective_status` matching o filter (ex: filter=PAUSED → todas rows.effective_status=PAUSED)
- [ ] `ALL` retorna rows com `effective_status` variado (não restrito)
- [ ] Cloud Run logs sem ERROR pra nenhum dos 4 valores

**Se algum valor retorna `error`:**
- Documentar como F-finding novo via `/findings-add` (família: schema_enum_runtime_reject)
- Remover valor do schema enum em `src/mcp/tools/meta_get_campaign_performance.py` + `meta_get_ad_set_performance.py` + `meta_get_ad_performance.py` (todas 3 tools usam mesmo enum)
- Re-run pre-push + deploy + re-run T6 com enum reduzido pra confirmar

**Convention reinforcement:** Sprint 3b.19A.1 = "every value in a tool's schema whitelist MUST be empirically validated. SDK descriptors contain values runtime rejects." Bug family: F17/F18/F19/F25/F27/F31/F32/F34/F36/F44 (10+ findings descobertos por essa convention só).

**Result:** ⬜ pending

---

## Test T7 — Error path: `ad_account_id` inexistente

**Setup:** Validar guard de pre-check `meta_ad_accounts.get_by_id`: account_id não-cached retorna error friendly PT-BR ANTES de fazer Graph call (waste prevention). Mensagem deve mencionar `meta_refresh_accounts` (instrução acionável).

**Steps:**

1. Claude Code → invocar com account_id que NÃO existe no cache:

```
meta_get_campaign_performance(
  ad_account_id="act_999999999",
  date_range="LAST_7_DAYS"
)
```

2. Repetir com `meta_get_ad_set_performance` + `meta_get_ad_performance` (todas 3 tools tem mesmo guard)

**Expected response:**

```json
{
  "status": "error",
  "error_message": "Ad account act_999999999 não encontrada. Use meta_refresh_accounts ou reconnect via /oauth/meta/start."
}
```

**Validação:**

- [ ] `status == "error"` pra todas 3 tools
- [ ] `error_message` contém `"act_999999999"` exato (account_id no echo)
- [ ] `error_message` contém `"não encontrada"` (PT-BR)
- [ ] `error_message` menciona `meta_refresh_accounts` OU `/oauth/meta/start` (instrução acionável)
- [ ] **Crítico:** ZERO Graph API calls feitas — validar Cloud Run logs: NÃO deve haver `meta.graph.call.start` pro account inválido (guard funcionou)
- [ ] **Crítico:** NENHUMA error_message expõe English OR Python traceback raw
- [ ] Audit_log entry com `status='error'`? **Não esperado** — guard retorna antes do `run_meta_graph_get` que faz audit. Validar via:

```sql
SELECT COUNT(*) FROM audit_log
WHERE platform = 'meta'
  AND operation IN ('meta_get_campaign_performance', 'meta_get_ad_set_performance', 'meta_get_ad_performance')
  AND status = 'error'
  AND params_summary->>'ad_account_id' = 'act_999999999';
-- Esperar 0 — guard executou ANTES do audit (account check é pre-flight)
```

**Failure modes investigation:**

- Tool dispara Graph call mesmo com account não-cached → bug guard `if account is None` faltando antes do build_insights_call block
- error_message em English → bug error message string literal não traduzido PT-BR
- error_message não menciona `meta_refresh_accounts` → bug instrução acionável faltando

**Result:** ⬜ pending

---

## Test T8 — Error path: token expirado retorna PT-BR reconnect message (DEFERRABLE)

**Setup:** Validar que `run_meta_graph_get` → `build_meta_api_for_manager` valida `token_expires_at` e retorna error PT-BR friendly quando token expirou. **Difícil em smoke real** sem conta secundária com token expirado de teste.

**Cenários de execução:**

**Opção A (DEFERRABLE — recomendado):** Skip teste manual. Documentar que validação acontece via:
- Integration tests `tests/integration/test_meta_get_campaign_performance.py::test_token_expired_returns_friendly_error` (se existir) OR
- Foundation M.2a unit test `tests/unit/test_meta_client.py` cobre `build_meta_api_for_manager` rejeitando token expirado

**Opção B (manual via DB UPDATE — only if Wellington wants):** Forçar token expiry via DB UPDATE manual, run tool, validar error, RESTORE imediatamente.

```sql
-- ANTES: anotar token_expires_at original
SELECT token_expires_at FROM meta_oauth_connections
WHERE manager_id = '<wellington_uuid>' AND revoked_at IS NULL;
-- Anotar valor pra restore

-- UPDATE forçando expired (1 dia no passado)
UPDATE meta_oauth_connections
SET token_expires_at = NOW() - INTERVAL '1 day'
WHERE manager_id = '<wellington_uuid>' AND revoked_at IS NULL;
```

Run tool:

```
meta_get_campaign_performance(
  ad_account_id="<smoke_account_id>",
  date_range="LAST_7_DAYS"
)
```

**Expected response:**

```json
{
  "status": "error",
  "error_message": "Token Meta expirado. Reconecte via /admin → 'Conectar Meta' pra reativar tools."
}
```

**RESTORE IMEDIATO (CRÍTICO se Opção B):**

```sql
UPDATE meta_oauth_connections
SET token_expires_at = '<original_value_anotado>'
WHERE manager_id = '<wellington_uuid>';
```

**Validação:**

- [ ] **Se Opção A (skip):** Marcado como DEFERRED + nota explicando integration tests cobrem essa validação
- [ ] **Se Opção B (manual):**
  - [ ] `status == "error"`
  - [ ] `error_message` em PT-BR ("Token Meta expirado" + "Reconecte via /admin")
  - [ ] NENHUMA tool call subsequente disparada (guard funciona)
  - [ ] **RESTORE token_expires_at** original pré-passar pra T9

**Result:** ⬜ pending ou DEFERRED

---

## Test T9 — BUC tracking — após 5 calls, `meta_rate_counters.calls_used` incrementa

**Setup:** Validar `record_actual_meta()` em `run_meta_graph_get` post-call: parseia `X-Business-Use-Case-Usage` header response Meta + persiste em `meta_rate_counters` (incrementa `calls_used` per ad_account_id + date). Essencial pra Caminho B+ tracking (500 calls/15d threshold pra Full Access re-submit).

**Pré-requisito:** Step 3 baseline anotado (`calls_used` pre-smoke). Não precisa OAuth refresh.

**Steps:**

1. Run any combinação das 3 tools, total 5 calls:

```
# 5 chamadas — pode misturar tools
meta_get_campaign_performance(ad_account_id="<smoke_account_id>", date_range="LAST_7_DAYS")
meta_get_ad_set_performance(ad_account_id="<smoke_account_id>", date_range="LAST_7_DAYS")
meta_get_ad_performance(ad_account_id="<smoke_account_id>", date_range="LAST_7_DAYS")
meta_get_campaign_performance(ad_account_id="<smoke_account_id>", date_range="LAST_14_DAYS")
meta_get_campaign_performance(ad_account_id="<smoke_account_id>", date_range="LAST_30_DAYS")
```

2. Query SQL pra validar incrementer:

```sql
SELECT app_id, ad_account_id, date, calls_used, last_throttle_pct, last_call_at
FROM meta_rate_counters
WHERE ad_account_id = '<smoke_account_id>'
  AND date = CURRENT_DATE
ORDER BY last_call_at DESC LIMIT 1;
```

**Validação:**

- [ ] Row existe pra (`<app_id_hash>`, `<smoke_account_id>`, `CURRENT_DATE`)
- [ ] `calls_used >= baseline + 5` (pré-smoke baseline em Step 3 + 5 calls T9)
- [ ] `last_throttle_pct` populado (float, esperado < 75 — se >75 warning Cloud Run logs)
- [ ] `last_call_at` ≈ now() ± 1 minuto
- [ ] `app_id` é hash (não plaintext — security check)

**Failure modes investigation:**

- `calls_used` não incrementou → bug `record_actual_meta` não está sendo chamado pós-call OR upsert SQL com bug
- Row não existe → bug primeira call não está inserindo (INSERT ON CONFLICT path)
- `last_throttle_pct` é null → header `X-Business-Use-Case-Usage` ausente da response Meta (Limited Access pode não retornar?) OR parser bug
- `app_id` em plaintext → bug security, hash não está sendo aplicado antes do persist

**Result:** ⬜ pending

---

## Test T10 — `audit_log.platform='meta'` + `provider_request_id` populated

**Setup:** Validar A5 fix + M.2a convention: tools Meta gravam `audit_log` com `platform='meta'` (default seria `'google'`) + `provider_request_id` populated com `X-FB-Trace-ID` header response Meta. Essencial pra observability multi-platform + Meta debugging.

**Pré-requisito:** Pelo menos 1 das tools M.3 invocada com sucesso (T1 ou T9 já satisfaz).

**Steps:**

1. Run any tool 1× (T1 pode contar):

```
meta_get_campaign_performance(
  ad_account_id="<smoke_account_id>",
  date_range="LAST_7_DAYS"
)
```

2. Query SQL pra inspecionar audit_log row:

```sql
SELECT
  occurred_at,
  manager_id,
  session_id,
  platform,
  action_type,
  operation,
  status,
  provider_request_id,
  params_summary
FROM audit_log
WHERE platform = 'meta'
  AND operation IN ('meta_get_campaign_performance', 'meta_get_ad_set_performance', 'meta_get_ad_performance')
ORDER BY occurred_at DESC LIMIT 1;
```

**Expected row:**

| Field | Expected |
|---|---|
| `platform` | `'meta'` (NÃO `'google'` default) |
| `action_type` | `'read'` (tools são read-only) |
| `operation` | um dos 3 nomes: `meta_get_campaign_performance`, `meta_get_ad_set_performance`, `meta_get_ad_performance` |
| `status` | `'success'` |
| `provider_request_id` | populated (string ≥ 1 char — formato Meta `x-fb-trace-id`) |
| `params_summary` | JSON contém `ad_account_id`, `level`, `start`, `end`, `effective_status` |
| `manager_id` | `<wellington_uuid>` |
| `session_id` | UUID válido |

**Validação:**

- [ ] Row existe pra operation Meta
- [ ] `platform == 'meta'` (NÃO `'google'`)
- [ ] `action_type == 'read'`
- [ ] `operation` matches uma das 3 tools M.3
- [ ] `status == 'success'`
- [ ] `provider_request_id` é string não-null não-vazia (Meta trace_id retornado)
- [ ] `params_summary` é JSON válido contendo todas as 5 keys esperadas
- [ ] `manager_id` matches Wellington UUID

**Failure modes investigation:**

- `platform == 'google'` → bug tool não está passando `platform="meta"` em `audit_log.record()` (default kwarg)
- `provider_request_id` null → bug não está reading `x-fb-trace-id` header response Meta, OR Limited Access não retorna esse header (improvável — header standard FB)
- `operation` retorna nome genérico (e.g. `run_meta_graph_get`) → bug `operation_name` kwarg não sendo passado per-tool
- `params_summary` ausente ou null → bug tool não está passando dict em `params_summary` kwarg
- `action_type == 'mutate'` → bug Meta tools (read-only) classificadas erroneamente como mutate

**Result:** ⬜ pending

---

## Per-value empirical probe summary (Sprint 3b.19A.1 convention)

`effective_status` enum tem 4 valores. Todos DEVEM ser empiricamente validados em T6.

| Enum field | Value | Expected | Actual | Pass/Fail |
|---|---|---|---|---|
| `effective_status` | `ACTIVE` | `status="success"` | ⬜ pending | ⬜ |
| `effective_status` | `PAUSED` | `status="success"` | ⬜ pending | ⬜ |
| `effective_status` | `ARCHIVED` | `status="success"` | ⬜ pending | ⬜ |
| `effective_status` | `ALL` | `status="success"` | ⬜ pending | ⬜ |

**Convention:** every value in a tool's schema whitelist MUST be empirically validated by creating/reading a real entity. SDK descriptors contain values runtime rejects (legacy, system-managed, type-restricted). Bug history: 14 of 38 findings caught here.

---

## V4 invariants validation

| Invariant | Enforcement | How smoke verifies |
|---|---|---|
| `currency='BRL'` | Validated em `meta_ad_accounts.currency` field (cached from Graph) | T1/T2/T3 valida `currency == "BRL"` em response |
| `platform='meta'` em audit_log | Hardcoded em tool handler: `audit_log.record(..., platform="meta")` via `run_meta_graph_get` | T10 valida SQL row tem `platform='meta'` |
| `action_type='read'` em audit_log | Hardcoded via `run_meta_graph_get` (read-only sprint) | T10 valida SQL row tem `action_type='read'` |
| PT-BR error messages | Hardcoded strings em tool handlers + `to_friendly_meta_error` translator | T7 valida error_message contém PT-BR + sem English/traceback |
| `effective_status_label` em PT-BR | `META_EFFECTIVE_STATUS_LABELS` map em `_meta_common.py` (ATIVO/PAUSADO/ARQUIVADO/etc) | T1 valida `effective_status_label == "ATIVO"` (não "ACTIVE") |
| `ctr` decimal (não percentual) | Hardcoded `round(float(ctr) / 100, 4)` em `parse_insights_row` | T1 valida `0.0 <= ctr <= 1.0` (decimal, NÃO Meta % raw) |
| `daily_budget_brl` em BRL (não cents) | Hardcoded `round(float(daily_budget) / 100, 2)` em `parse_insights_row` adset | T2 valida `daily_budget_brl ≈ spend visualizado Business Suite` |
| `ad_set_id` snake_case (não `adset_id`) | Hardcoded em `parse_insights_row` adset/ad branches | T2/T3 valida response contém key `ad_set_id` (não `adset_id`) |
| Limite cap 500 rows | Schema `"limit": {"maximum": 500}` | Implicit T1 — schema validation Anthropic rejeita >500 |
| Audit_log `provider_request_id` populated | Hardcoded `x-fb-trace-id` header read em `run_meta_graph_get` | T10 valida SQL row tem `provider_request_id` não-null |
| BUC tracking incrementa | `record_actual_meta()` em `run_meta_graph_get` post-call | T9 valida `meta_rate_counters.calls_used >= baseline + 5` |
