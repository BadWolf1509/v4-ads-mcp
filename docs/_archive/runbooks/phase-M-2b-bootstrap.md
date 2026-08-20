# Phase M.2b — manual smoke runbook (Meta `get_account_overview` + App Review prep)

**Purpose:** Validar Sprint M.2b — 1ª tool Meta que faz call real Graph API (não cache local). Cobre (1) `meta_get_account_overview` orquestrando 2 Graph calls (current + previous period) + parsing actions/action_values + deltas + warnings (`account_status` + token expiry) + PT-BR error translation, (2) endpoint `/oauth/meta/data-deletion-callback` (pré-req Meta App Review obrigatório) + helper `_verify_meta_signed_request` HMAC validation + página pública `/legal/data-deletion-status/{code}`, (3) endpoint `/oauth/meta/refresh-accounts` (re-sync ad accounts sem reconnect OAuth), (4) UI admin extensions — botões "Atualizar lista" + "Revogar conexão" + modal + warning banner token <7d, (5) A5 fix `get_my_audit_log` retorna `platform` field. Foundation validada pra escalar Meta tools subsequentes (M.3+).

**Operator:** wellinton.ribeiro@v4company.com
**Business Manager Meta:** V4 Lima Soares & Co (João Pessoa, PB)
**Ad accounts smoke sugeridos:**
- ATIVO: ICSER `act_1489398022911451` ou Wellington personal `act_383566922510173`
- PAGAMENTO_PENDENTE: ML Antiguidades `act_370008662` (T3 — account_status warning)

**Spec:** `docs/superpowers/specs/2026-05-25-sprint-m2b-meta-get-account-overview-design.md`
**Plan:** `docs/superpowers/plans/2026-05-25-sprint-m2b-meta-get-account-overview.md`
**Sprint family parent:** `docs/superpowers/specs/2026-05-24-meta-ads-incorporation-design.md` (M.1 → M.25)
**Predecessor:** `docs/operacao/phase-M-2a-bootstrap.md` (M.2a — OAuth + first tool DB cache)

> **Escopo M.2b confirmado:**
> - Tool count: 58 → **59** (2ª MCP tool Meta — 1ª com Graph API real)
> - 2 endpoints novos OAuth: `/oauth/meta/data-deletion-callback` (HMAC-validated, LGPD/Meta App Review req) + `/oauth/meta/refresh-accounts` (sync sem reconnect)
> - 1 página pública nova: `/legal/data-deletion-status/{code}` (LGPD 30d window manual signoff)
> - 1 fix tool existente: `get_my_audit_log` retorna `platform` field (A5 OPEN)
> - 2 botões admin UI: "Revogar conexão" (modal confirm) + "Atualizar lista" + warning banner token <7d
> - 1 ação Wellington fora-MCP pós-smoke: Meta App Review submit (5-30d Meta timeline)
> - Decision gate pós-M.2b: 2 semanas dogfood Wellington — ≥3 usos/semana = continua M.3-M.25; senão pause + foca Google backlog
> - ZERO migrations novas (coluna `audit_log.platform` já existe M.2a migration 003/004)

## Production URL

`https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app`

## Pre-flight

- [ ] Deploy lands successfully (CI + Deploy green em commit final M.2b Task H, SHA `847dfab` ou later)
- [ ] Service `/health` returns 200 (`{"status":"ok","version":"0.1.0"}`)
- [ ] Tool `meta_get_account_overview` registered (`test_registered_tool_count_matches_files_on_disk` 59==59 PASS)
- [ ] Pre-push gate `python scripts/check_pre_push.py` 5/5 PASS
- [ ] Pre-push gate FULL `python scripts/check_pre_push_full.py` 6/6 PASS (Docker — testcontainers OAuth integration tests)
- [ ] Schema regression `test_no_composition_keywords_in_any_schema` passa
- [ ] Unit tests `tests/unit/test_meta_account_overview.py` PASS (~20 tests pure module: date math, deltas, parsing, warnings)
- [ ] Unit tests `tests/unit/test_meta_signed_request.py` PASS (~8 tests HMAC validation)
- [ ] Unit tests `tests/unit/test_get_my_audit_log_platform.py` PASS (2 tests A5 regression)
- [ ] Integration tests `tests/integration/test_meta_get_account_overview.py` PASS (4 tests: happy + account_status + token_expired + no_oc)
- [ ] Integration tests `tests/integration/test_meta_data_deletion_callback.py` PASS (3 tests: signed_request valid + invalid sig + audit_log insert)
- [ ] Integration tests `tests/integration/test_meta_refresh_accounts.py` PASS (2 tests: happy + token expired 422)
- [ ] OAuth Meta Wellington still ativo desde M.2a smoke (não foi revogado) — `meta_oauth_connections.revoked_at IS NULL` pra `<wellington_uuid>`
- [ ] `meta_ad_accounts` cache populado pós-M.2a (12 ad accounts V4 LS&Co BM sincronizadas)
- [ ] MCP Inspector / Claude Desktop conectado à URL produção e enxerga `meta_get_account_overview` na tool list
- [ ] Secret Manager `META_APP_SECRET` matches valor configurado em Meta App settings (T6 HMAC validation depende)

Production revisions: `v4-ads-mcp-XXXXX-xxx` (preencher após deploy final M.2b Task H).

## Smoke results

Preencher conforme execução. Marcar resultado final no fim do arquivo.

| # | Test | Result | Notes |
|---|---|---|---|
| T1 | `meta_get_account_overview` happy path (real ad_account ATIVO, LAST_7_DAYS) | ⬜ pending | |
| T2 | Per-value probe — individual fields (spend/impressions/ctr/actions parsing) | ⬜ pending | |
| T3 | `account_status` warning surfaced (ML Antiguidades PAGAMENTO_PENDENTE) | ⬜ pending | |
| T4 | Token expiry warning surfaced (<7 dias via DB UPDATE manual) | ⬜ pending | |
| T5 | PT-BR error translation (invalid ad_account_id + invalid date) | ⬜ pending | |
| T6 | `/oauth/meta/data-deletion-callback` synthetic (HMAC-valid signed_request) | ⬜ pending | |
| T7 | Revoke button UX (modal confirm + redirect + card update) | ⬜ pending | |
| T8 | Refresh button UX (add new ad account in BM + sync sem reconnect) | ⬜ pending | |

**Effective result:** N/8 PASS

### F-findings emerged

_Preencher durante smoke. Template: `**F## (SEV)** — <symptom>. Fix: <plan>. Family: <bug class>.`_

Se zero F-findings: documentar explicitly "Zero F-findings novos. Sprint clean."

### Sign-off

- [ ] Pre-push gate 5/5 PASS
- [ ] Pre-push gate FULL 6/6 PASS (Docker — testcontainers OAuth + Meta integration tests)
- [ ] Spec compliance + code quality reviewers APPROVED
- [ ] Production `/health` 200 (revisão final)
- [ ] T1 PASS (happy path Graph API real — proof of life Meta Graph pipeline)
- [ ] T2 PASS (per-value probe — schema fields validados empiricamente, especialmente actions[] parsing)
- [ ] T3 PASS (account_status warning surfaced corretamente em conta PAGAMENTO_PENDENTE)
- [ ] T4 PASS (token expiry warning surfaced quando <7 dias — proactive UX)
- [ ] T5 PASS (PT-BR error translation funcionando — sem English/traceback raw exposed)
- [ ] T6 PASS (data-deletion-callback HMAC-validated + audit_log inserido — pré-req App Review)
- [ ] T7 PASS (revoke UX completo via modal — segurança user-facing)
- [ ] T8 PASS (refresh UX completo + nova ad account aparece no card sem reconnect)
- [ ] CLAUDE.md "Shipped — Meta Ads" tabela updated (M.2a ✅ → M.2b ✅) + tool count 58 → 59
- [ ] CLAUDE.md "Pending / future" Meta entry trimmed (M.2b items movidos pra shipped)
- [ ] sprint-history.md entry Sprint M.2b
- [ ] findings-catalog.md atualizado se F-findings emergiram (`/findings-add` skill)
- [ ] A5 marcada CLOSED em findings-catalog.md (Task A shipped + T1/T2 lookback valida platform field)
- [ ] Tool count 59 confirmado em produção (`test_registered_tool_count_matches_files_on_disk` 59==59)
- [ ] Wellington manual: Meta App Review submit iniciado (Task J — fora-MCP)

---

## Pre-smoke setup

### Step 1: Sanity check no MCP client + webapp admin

Conectar Claude Desktop / Inspector à URL produção (`https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app`) e verificar que `meta_get_account_overview` aparece na lista de tools:

```
# Introspect — esperar ver meta_get_account_overview com:
# - input: ad_account_id (required), date_range OR (start_date + end_date)
# - response shape: current + previous + deltas + _warnings + ad_account_id + account_name + account_status_label + currency + date_range
# - additionalProperties: false
# - SEM oneOf/allOf/anyOf (regression 3b.19B.1)
```

**Disconnect + reconnect Claude Desktop pra refresh tool cache:**
1. Settings → MCP Servers → v4-ads → Disconnect
2. Reconnect (Bearer MCP token já populado)
3. Verify "58 tools" → "59 tools" no Claude UI tool indicator

Se `meta_get_account_overview` não aparece ou tool count ainda 58, deploy não landed — abortar smoke.

Webapp sanity:

```
# Browser → https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/admin (logged in wellinton.ribeiro@v4company.com)
# Esperar ver card "Suas conexões OAuth" → sub-card Meta com:
# - Status "Conectado" + fb_email Wellington + expira em N dias (de M.2a, ainda ativo)
# - NEW botão "Atualizar lista" (secondary)
# - NEW botão "Revogar conexão" (danger)
# - Warning banner amarelo SE token <7d (não esperado no início do smoke)
```

Se botões não aparecem ou card layout quebrado, deploy não landed completamente — abortar smoke.

### Step 2: Wellington UUID + baseline DB state

Capturar `manager_id` UUID Wellington pra queries SQL em T4 (DB UPDATE manual) + T7 (validação revoke) + T8 (validação refresh):

```sql
-- Via Supabase SQL Editor (mcp__supabase__execute_sql ou dashboard)
SELECT id, email FROM managers WHERE email = 'wellinton.ribeiro@v4company.com';
-- Anotar id retornado (UUID) — usar em T4 rollback queries
```

Anotar `<wellington_uuid>` pra todas as queries SQL deste smoke.

Baseline pre-smoke `meta_oauth_connections`:

```sql
SELECT manager_id, fb_email, scopes, token_expires_at, revoked_at, created_at
FROM meta_oauth_connections
WHERE manager_id = '<wellington_uuid>'
ORDER BY created_at DESC LIMIT 1;
```

Esperar 1 row de M.2a ativa (`revoked_at IS NULL`, `token_expires_at ≈ M.2a_smoke_date + 60d`). **ANOTAR `token_expires_at` original** pra rollback T4 (UPDATE volta pra esse valor após teste).

Baseline pre-smoke `meta_ad_accounts` cached:

```sql
SELECT COUNT(*) AS total, COUNT(*) FILTER (WHERE account_status = 1) AS ativos
FROM meta_ad_accounts;
-- Esperar ~12 ad accounts (V4 LS&Co BM)
```

Baseline pre-smoke `audit_log` Meta entries (lookback delta):

```sql
SELECT COUNT(*) AS meta_entries_pre_smoke
FROM audit_log WHERE platform = 'meta';
-- Anotar count — smoke aumentará em ≥7 entries (T1+T2+T3+T4+T6+T7+T8 audit_this_call calls)
```

### Step 3: Cloud Run logs streaming setup

Em terminal separado, manter logs streaming pra captar errors durante Graph calls + OAuth flows:

```
gcloud run services logs read v4-ads-mcp \
  --region=southamerica-east1 \
  --project=v4-ads-mcp-prod \
  --limit=50
```

Pra streaming contínuo, usar `--follow`.

### Step 4: Capturar META_APP_SECRET local (T6 setup)

T6 requer `META_APP_SECRET` real pra gerar `signed_request` HMAC-valid. Buscar via Secret Manager:

```powershell
# PowerShell — copia pra clipboard (NÃO eco pra terminal, evita shell history)
gcloud secrets versions access latest --secret=meta-app-secret --project=v4-ads-mcp-prod | Set-Clipboard
# Cola em script quando solicitado em T6
```

NUNCA cola secret em chat. Após T6 done, `Clear-History` opcional pra higiene.

### Step 5: (T8 only) Adicionar 1 ad account nova no BM antes do smoke

Pré-condição T8 — refresh button só faz sentido se houver delta entre `meta_ad_accounts` cache local e Graph `/me/adaccounts` real.

Antes de iniciar T8:
1. Acessar Meta Business Suite (https://business.facebook.com)
2. Business Manager V4 Lima Soares & Co → Configurações → Contas de anúncios
3. Adicionar NEW ad account (cliente novo OU mover ad account existente pra dentro do BM)
4. Anotar `account_id` (formato numérico) — vai validar em T8 que aparece após refresh

Se não houver ad account nova disponível pra adicionar, T8 vira **DEFERRED** — documentar limitação.

---

## Test T1 — `meta_get_account_overview` happy path (LAST_7_DAYS, real ad_account ATIVO)

**Setup:** Primeira tool Meta com call real Graph API. Wellington invoca via Claude Desktop em ad_account ATIVO com campanha recente (spend > 0 últimos 7d). Valida ponta-a-ponta: OAuth token check OK → 2 Graph calls (current + previous) → parse insights → compute deltas → empty `_warnings` array (conta saudável + token >7d) → return shape consistente com paridade Google `get_account_overview`.

**Pré-requisito:** OAuth Meta Wellington ativo (M.2a, ainda não revogado). Ad account sugerido: **ICSER `act_1489398022911451`** ou **Wellington personal `act_383566922510173`** — escolher account com spend ativo últimos 7d.

**Steps:**

1. Claude Desktop → prompt PT-BR: **"Me dá um overview da conta Meta `act_1489398022911451` últimos 7 dias"**
2. Claude resolve intent → invoca `meta_get_account_overview(ad_account_id="act_1489398022911451", date_range="LAST_7_DAYS")`
3. Tool internally:
   - resolve_meta_date_window → `(today - 6d, today)`
   - shift_to_previous_period → `(today - 13d, today - 7d)`
   - get_active_for_manager → oc com token válido + token_expires_at > now+7d
   - get_by_id → meta_ad_account row com account_status=1 (ATIVO)
   - run_meta_graph_get (current period) → audit_this_call=True
   - run_meta_graph_get (previous period) → audit_this_call=False
   - parse_insights_response (current + previous)
   - compute_deltas
   - build_warnings → empty array (account saudável + token >7d)

**Expected response shape:**

```json
{
  "status": "success",
  "ad_account_id": "act_1489398022911451",
  "account_name": "ICSER",
  "account_status_label": "ATIVO",
  "currency": "BRL",
  "date_range": {"start": "2026-05-19", "end": "2026-05-25"},
  "current": {
    "spend": 1234.56,
    "impressions": 45000,
    "clicks": 800,
    "ctr": 1.78,
    "cpc": 1.54,
    "reach": 32000,
    "frequency": 1.41,
    "conversions": 12,
    "conversion_value": 4500.00,
    "purchase_roas": 3.65
  },
  "previous": {
    "spend": 980.00,
    "impressions": 38000,
    "clicks": 650,
    "ctr": 1.71,
    "cpc": 1.51,
    "reach": 28000,
    "frequency": 1.36,
    "conversions": 8,
    "conversion_value": 2900.00,
    "purchase_roas": 2.96
  },
  "deltas": {
    "spend_pct": 25.98,
    "impressions_pct": 18.42,
    "clicks_pct": 23.08,
    "conversions_pct": 50.0,
    "conversion_value_pct": 55.17,
    "purchase_roas_pct": 23.31
  },
  "_warnings": []
}
```

**Validação:**

- [ ] Tool invocada sem ImportError facebook-business / sem MetaTokenExpiredError
- [ ] Response shape contém TODAS as top-level keys: `status, ad_account_id, account_name, account_status_label, currency, date_range, current, previous, deltas, _warnings`
- [ ] `status == "success"`
- [ ] `account_status_label == "ATIVO"` (PT-BR enum, NÃO Meta raw int)
- [ ] `currency == "BRL"` (V4 invariant)
- [ ] `date_range.start` = `today - 6d` (LAST_7_DAYS inclusivo hoje)
- [ ] `date_range.end` = `today`
- [ ] `current` + `previous` ambos populados (não vazios — campanha ativa últimos 14d)
- [ ] Cada métrica em `current` + `previous` tipo correto: `spend/ctr/cpc/frequency/conversion_value/purchase_roas` float; `impressions/clicks/reach/conversions` int
- [ ] `deltas` populado com `_pct` suffix em 6 metrics: spend, impressions, clicks, conversions, conversion_value, purchase_roas
- [ ] **Crítico:** `_warnings: []` (empty array — account ATIVO + token >7d, nenhum warning ativo)
- [ ] Response time < 5s (2 Graph calls sequenciais + DB)
- [ ] Cloud Run logs sem ERROR/CRITICAL durante execução
- [ ] Audit_log +1 entry (apenas current call audita, previous é `audit_this_call=False`):
  ```sql
  SELECT operation, status, provider_request_id, params_summary
  FROM audit_log WHERE platform='meta' AND operation='meta_get_account_overview'
  ORDER BY occurred_at DESC LIMIT 1;
  ```
  Esperar: `status='success'`, `provider_request_id` populated (`x-fb-trace-id` header), `params_summary` contém `ad_account_id`, `date_range`, `period='current'`, `start`, `end`

**Failure modes investigation:**

- Token expired → reconnect via `/admin` (M.2a flow) e re-rodar T1
- Account inativa → escolher outro ad_account_id ATIVO (`account_status=1`)
- Graph 400 error → investigar params `time_range` JSON encoding (double-quote escaping); check Cloud Run logs `meta.graph.call.error`
- Graph 401 → token revogado externamente; re-OAuth
- Graph 403 → BUC throttle (>75% — verificar `meta_rate_counters` last hour)
- `_warnings` non-empty inesperado → cross-check com T3 (account_status) ou T4 (token expiry); pode ter conta degradada

**Result:** ⬜ pending

---

## Test T2 — Per-value probe (Sprint 3b.19A.1 convention)

**Setup:** Per-value empirical validation de cada field individual no return de `meta_get_account_overview`. Especialmente crítico pra `actions[]` parsing (Meta tem 50+ action types possíveis — filter set `CONVERSION_ACTION_TYPES` precisa estar correto e exclude pixel-prefixed duplicates). Validar tipos JSON, valores plausíveis, cálculos derivados (frequency = impressions/reach), e filtering correto de conversions.

**Pré-requisito:** T1 executou com sucesso. Usar mesma account/period de T1.

**Steps:**

1. Re-invocar tool de T1 (mesmo `ad_account_id` + `date_range="LAST_7_DAYS"`)
2. Para cada métrica abaixo, validar tipo + range + cálculo derivado:

| # | Field | Tipo esperado | Range plausível | Cálculo cross-check |
|---|---|---|---|---|
| F1 | `current.spend` | float | ≥ 0 (BRL) | — |
| F2 | `current.impressions` | int | ≥ 0 | — |
| F3 | `current.clicks` | int | ≥ 0 | ≤ impressions |
| F4 | `current.ctr` | float | 0.0 ≤ x ≤ 100.0 (%) | ≈ (clicks / impressions) × 100 |
| F5 | `current.cpc` | float | ≥ 0 (BRL) | ≈ spend / clicks |
| F6 | `current.reach` | int | ≥ 0 | ≤ impressions |
| F7 | `current.frequency` | float | ≥ 1.0 | ≈ impressions / reach |
| F8 | `current.conversions` | int | ≥ 0 | sum(actions[type IN CONVERSION_ACTION_TYPES]) |
| F9 | `current.conversion_value` | float | ≥ 0 (BRL) | sum(action_values[type IN CONVERSION_ACTION_TYPES]) |
| F10 | `current.purchase_roas` | float | ≥ 0 | extracted from purchase_roas[] action_type IN (purchase, omni_purchase) |

3. Validar TODAS as 10 fields também em `previous` (mesma shape, mesma constraints)

4. Cross-check delta calculation manualmente (Wellington faz sanity check):

```
Esperado: deltas.spend_pct ≈ ((current.spend - previous.spend) / previous.spend) × 100, arredondado 2 casas
Se previous.spend == 0: deltas.spend_pct == null (Python None → JSON null)
```

5. **Crítico actions[] parsing:** validar Graph response raw via Cloud Run logs (debug log do run_meta_graph_get) — confirmar que tool está filtrando apenas action_types em `CONVERSION_ACTION_TYPES` set:

```python
CONVERSION_ACTION_TYPES = {
    "purchase",
    "lead",
    "complete_registration",
    "offsite_conversion.fb_pixel_purchase",
    "offsite_conversion.fb_pixel_lead",
    "offsite_conversion.fb_pixel_complete_registration",
}
```

Se conta Meta retorna `actions: [{"action_type": "page_engagement", "value": "500"}, {"action_type": "purchase", "value": "12"}]`, tool deve retornar `conversions: 12` (NÃO 512 — filtragem correta).

**Validação:**

- [ ] F1-F10 em `current`: tipo + range corretos (10/10 PASS)
- [ ] F1-F10 em `previous`: tipo + range corretos (10/10 PASS)
- [ ] F4 `ctr` calculation cross-check: `(clicks / impressions) × 100` ± 0.1% tolerance
- [ ] F5 `cpc` calculation cross-check: `spend / clicks` ± 0.01 BRL tolerance
- [ ] F7 `frequency` calculation cross-check: `impressions / reach` ± 0.05 tolerance
- [ ] F8 `conversions` — filter set correto, NÃO inclui page_engagement/post_engagement/video_view (Meta retorna esses em `actions[]` por default)
- [ ] F9 `conversion_value` — filter set MESMO de F8 (consistência)
- [ ] F10 `purchase_roas` — extracted from `purchase_roas[]` array, action_type `purchase` ou `omni_purchase` (Meta retorna ambos em conta omnichannel)
- [ ] Deltas `_pct` arredondado 2 casas decimais (não 5-10 casas float raw)
- [ ] **Crítico:** Se `previous.spend == 0`, `deltas.spend_pct` é `null` JSON (NÃO `0`, NÃO `Infinity`, NÃO error) — divisão indefinida tratada como `None` em Python
- [ ] Audit_log +1 entry adicional (T2 re-invoca tool)

**Failure modes investigation:**

- F4-F7 calculation mismatch → bug `parse_insights_response` — campos não convertidos string→float corretamente (F17/F18 family — numeric format mismatch)
- F8 `conversions` includes non-conversion events → filter set incorreto em `_parse_actions`, expandir `CONVERSION_ACTION_TYPES` ou ajustar parsing
- F9 `conversion_value` zero quando F8 conversions > 0 → action_values[] não populated por Meta pra esse account (pixel não enviando value) OR parsing wrong key
- F10 `purchase_roas` zero quando spend + conversion_value > 0 → parse `_extract_purchase_roas` não está iterando corretamente; check Graph response raw em logs
- Deltas `_pct` retorna float não-rounded (e.g. `25.9876543`) → `round(..., 2)` não aplicado em `compute_deltas`

**Result:** ⬜ pending

---

## Test T3 — `account_status` warning surfaced (ML Antiguidades PAGAMENTO_PENDENTE)

**Setup:** Validar que `build_warnings` surface o status problemático da ad account no return field `_warnings`, em PT-BR, sem fail a tool. Usar conta real com `account_status != 1` (sugerido **ML Antiguidades `act_370008662`** — billing pendente conhecido). Tool deve retornar métricas válidas (Graph API serve mesmo com PAGAMENTO_PENDENTE) + warning ativo.

**Pré-requisito:** ML Antiguidades ad_account em `meta_ad_accounts` cache com `account_status` = 3 (PAGAMENTO_PENDENTE). Confirmar antes de T3:

```sql
SELECT ad_account_id, account_name, account_status
FROM meta_ad_accounts
WHERE ad_account_id = 'act_370008662';
-- Esperar: account_status=3 (Meta enum PAGAMENTO_PENDENTE = 3)
```

Se `account_status` != 3, escolher outra conta non-ATIVO OU forçar via UPDATE manual (dev only):

```sql
-- DEV ONLY — restaurar ao final do T3 com refresh
UPDATE meta_ad_accounts SET account_status = 3 WHERE ad_account_id = 'act_370008662';
```

**Steps:**

1. Claude Desktop → prompt: **"Overview Meta `act_370008662` últimos 7 dias"**
2. Tool invocada → mesma orquestração T1 + `build_warnings` adiciona entry no `_warnings`
3. Esperar response shape igual T1 + `_warnings` non-empty

**Expected response shape (foco em `_warnings`):**

```json
{
  "status": "success",
  "ad_account_id": "act_370008662",
  "account_name": "ML Antiguidades",
  "account_status_label": "PAGAMENTO_PENDENTE",
  "currency": "BRL",
  "date_range": {"start": "...", "end": "..."},
  "current": { /* métricas válidas, conta pode ter zero spend mas Graph serve */ },
  "previous": { /* métricas válidas */ },
  "deltas": { /* deltas válidos */ },
  "_warnings": [
    "account_status=PAGAMENTO_PENDENTE — métricas podem estar desatualizadas ou ad serving suspenso. Verificar billing/status no Meta Business Suite."
  ]
}
```

**Validação:**

- [ ] Tool retorna `status: "success"` (NÃO error — account_status problemático não bloqueia leitura)
- [ ] `account_status_label == "PAGAMENTO_PENDENTE"` (PT-BR, NÃO numeric 3)
- [ ] `_warnings` é array com EXATAMENTE 1 entry (token ainda >7d, só account_status warning)
- [ ] Warning string completa em PT-BR — formato: `"account_status=<LABEL> — métricas podem estar desatualizadas ou ad serving suspenso. Verificar billing/status no Meta Business Suite."`
- [ ] Warning menciona `account_status` field name + valor exato `PAGAMENTO_PENDENTE` (não generic "conta com problema")
- [ ] `current` + `previous` ainda populados (Graph API serve histórico mesmo com billing pendente)
- [ ] Audit_log +1 entry — `status='success'` (warning NÃO escala pra error)

**Failure modes investigation:**

- Warning retorna em English ("account_status=PAYMENT_PENDING — metrics may be...") → bug `build_warnings` PT-BR string literal incorreto
- Warning retorna numeric (`"account_status=3 —..."`) → bug usando raw code em vez de label
- `account_status_label` retorna `"DESCONHECIDO"` → bug `META_ACCOUNT_STATUS_LABELS` mapping não inclui código 3
- Tool retorna error `{"status": "error", "error_message": "..."}` → bug `build_warnings` escalando em vez de surfar warning
- `_warnings` não inclui entry → bug `build_warnings` condition `account_status_label != "ATIVO"` não triggou

**Cleanup T3:**

Se forçou `account_status = 3` via UPDATE manual, restaurar via refresh (T8 vai sincronizar do Graph):

```sql
-- Opcional: refresh manual
-- UPDATE meta_ad_accounts SET account_status = 1 WHERE ad_account_id = 'act_370008662';
-- OR aguardar T8 refresh sync com Graph real
```

**Result:** ⬜ pending

---

## Test T4 — Token expiry warning surfaced (<7 dias)

**Setup:** Validar `build_warnings` surface token expiry warning quando OAuth token tem <7 dias restantes. Forçar via DB UPDATE manual em `meta_oauth_connections.token_expires_at` pra `now() + INTERVAL '5 days'`, invocar tool, validar warning ativo, restaurar valor original.

**Pré-requisito:** T1 PASS (token Wellington válido + >60d antes do teste). Backup do `token_expires_at` original anotado em Pre-smoke setup Step 2.

**Steps:**

1. Via Supabase SQL Editor, forçar token expiry pra 5 dias futuros:

```sql
-- ANTES: confirmar valor atual e ANOTAR
SELECT manager_id, token_expires_at
FROM meta_oauth_connections
WHERE manager_id = '<wellington_uuid>' AND revoked_at IS NULL;
-- Anotar token_expires_at original (ex.: '2026-07-24 12:34:56+00')

-- UPDATE pra 5 dias futuros
UPDATE meta_oauth_connections
SET token_expires_at = NOW() + INTERVAL '5 days'
WHERE manager_id = '<wellington_uuid>' AND revoked_at IS NULL;
```

2. (Opcional) Browser hard refresh `/admin` → esperar **warning banner amarelo** "⚠ Token expira em 5 dia(s). Recomendado reconectar."

3. Claude Desktop → re-invocar tool de T1: **"Overview Meta `act_1489398022911451` últimos 7 dias"**

4. Esperar response shape igual T1 + `_warnings` com 1 entry de token expiry

**Expected response shape (foco em `_warnings`):**

```json
{
  "status": "success",
  /* ... fields normais ... */
  "_warnings": [
    "Token OAuth Meta expira em 5 dias (2026-05-30). Reconectar via /admin → 'Conectar Meta' pra evitar interrupção das tools."
  ]
}
```

5. **Restore (CRÍTICO):** restaurar `token_expires_at` original ANTES de continuar pra T5:

```sql
UPDATE meta_oauth_connections
SET token_expires_at = '<original_value_anotado>'
WHERE manager_id = '<wellington_uuid>';
-- OR: re-OAuth via /admin pra refresh real (token_expires_at = now() + 60d)
```

6. Re-rodar tool → confirmar `_warnings: []` empty (back to T1 baseline)

**Validação:**

- [ ] DB UPDATE token_expires_at executa sem erro
- [ ] (Opcional) UI admin mostra warning banner amarelo com texto "Token expira em 5 dia(s)..."
- [ ] Tool re-invocada retorna `status: "success"` (token ainda válido — apenas warning, não error)
- [ ] `_warnings` array com 1 entry (account saudável + token <7d)
- [ ] Warning string completa em PT-BR — formato: `"Token OAuth Meta expira em N dias (YYYY-MM-DD). Reconectar via /admin → 'Conectar Meta' pra evitar interrupção das tools."`
- [ ] Warning menciona dias restantes EXATOS (5) + data ISO YYYY-MM-DD (não Unix timestamp, não Portuguese verbose)
- [ ] Warning menciona path `/admin` e ação `Conectar Meta` (instrução acionável)
- [ ] **Cleanup:** restore `token_expires_at` original PASS → re-invoke tool → `_warnings: []` empty

**Failure modes investigation:**

- Tool retorna error `MetaTokenExpiredError` → bug `build_warnings` threshold incorreto (talvez `<= 0` em vez de `< 7`), OR token check em `run_meta_graph_get` mal calibrado pra antecipar expiry
- Warning em English ("Meta OAuth token expires in 5 days...") → bug string literal
- Warning mostra Unix timestamp ou ISO datetime full (não date-only) → bug `iso_date = token_expires_at.date().isoformat()` não aplicado
- `days_left` calculado errado (e.g. mostra 4 quando esperado 5) → timezone offset entre `datetime.now(UTC)` e `token_expires_at` (DB stores UTC, garantir comparação UTC-aware)
- UI banner não aparece em `/admin` → admin_index handler não está passando `meta_token_expiring_soon` + `meta_days_until_expiry` template vars

**Restore validation:**

- [ ] Pós-restore, `_warnings: []` empty
- [ ] UI admin banner desaparece após hard refresh

**Result:** ⬜ pending

---

## Test T5 — PT-BR error translation (invalid ad_account_id + invalid date)

**Setup:** Validar que tool retorna error messages em PT-BR (não Python traceback raw, não English fallback) em 2 cenários: (1) ad_account_id inválido (não existe em cache local OR Graph 400), (2) start_date/end_date inválidos (formato incorreto OR só um dos dois fornecido). Critical pra UX gestores BR.

**Steps cenário 1 (ad_account_id inválido):**

1. Claude Desktop → prompt: **"Overview Meta `act_999999999` últimos 7 dias"** (account_id que NÃO está no cache local)
2. Tool invocada → `meta_ad_accounts.get_by_id` returna `None` → tool retorna error early antes de Graph call

**Expected:**

```json
{
  "status": "error",
  "error_message": "Ad account act_999999999 não encontrada. Use meta_refresh_accounts ou reconnect."
}
```

**Steps cenário 2 (date params inconsistent):**

1. Claude Desktop → prompt: **"Overview Meta `act_1489398022911451` desde 2026-05-01"** (start_date só, sem end_date)
2. Tool invocada → `resolve_meta_date_window` raises `ValueError` → tool capture + retorna error

**Expected:**

```json
{
  "status": "error",
  "error_message": "Parâmetros de data inválidos: start_date e end_date devem ser fornecidos juntos"
}
```

**Steps cenário 3 (date format inválido):**

1. Claude Desktop → prompt direto: invocar `meta_get_account_overview(ad_account_id="act_1489398022911451", start_date="01/05/2026", end_date="07/05/2026")` (formato DD/MM em vez de YYYY-MM-DD)
2. Schema validation deve rejeitar ANTES de invocar tool (pattern `^\d{4}-\d{2}-\d{2}$`)

**Expected:**

```
Schema validation error (Anthropic-level): "start_date does not match pattern '^\\d{4}-\\d{2}-\\d{2}$'"
```

OR se schema validation passou (Claude formatou wrong), tool capture `ValueError` em `date.fromisoformat` → return error PT-BR.

**Validação:**

- [ ] Cenário 1: `status == "error"` + `error_message` contém "Ad account `act_999999999`" + "não encontrada" (PT-BR)
- [ ] Cenário 1: error_message menciona `meta_refresh_accounts` (instrução acionável)
- [ ] Cenário 1: ZERO Graph API calls feitas (validar Cloud Run logs — não deve haver `meta.graph.call.start` pro account inválido)
- [ ] Cenário 1: Audit_log entry com `status='error'` + `error_message` populated
- [ ] Cenário 2: `status == "error"` + `error_message` contém "Parâmetros de data inválidos" + "start_date e end_date devem ser fornecidos juntos"
- [ ] Cenário 2: error_message NÃO contém Python traceback raw / stack trace
- [ ] Cenário 3 schema: rejection antes da tool ser invocada (Anthropic validator) OR tool capture com PT-BR friendly message
- [ ] **Crítico:** NENHUMA error_message expõe English ("Ad account not found", "Invalid date parameters") — todas PT-BR
- [ ] **Crítico:** NENHUMA error_message expõe stack trace Python (Traceback, File "...", line N)

**Failure modes investigation:**

- Cenário 1 falha com English → bug error_message string literal em meta_get_account_overview.py
- Cenário 1 dispara Graph call mesmo com account não-cached → bug guard `if account is None` faltando antes do Graph block
- Cenário 2 retorna traceback raw → tool não está capturing `ValueError` em try/except — wrap `resolve_meta_date_window` call
- Cenário 3 schema validation não rejeita → schema pattern `^\d{4}-\d{2}-\d{2}$` incorreto OR additionalProperties true
- error_message contém fb_trace_id ou Meta error code raw → não passed por `to_friendly_meta_error` translator (M.2a foundation)

**Result:** ⬜ pending

---

## Test T6 — `/oauth/meta/data-deletion-callback` synthetic (HMAC-valid signed_request)

**Setup:** Validar endpoint `data-deletion-callback` pré-req Meta App Review obrigatório. Helper local `scripts/test_meta_deletion_callback.py` gera `signed_request` HMAC-valid usando `META_APP_SECRET` real. POST pra endpoint deve validar HMAC, inserir row em `audit_log` com `operation=meta_data_deletion_request`, e retornar `{url, confirmation_code}` no shape requerido por Meta.

**Pré-requisito:** `META_APP_SECRET` no clipboard (Pre-smoke Step 4 done).

**Steps:**

1. Gerar `signed_request` via helper script (no shell local, NÃO em production):

```powershell
# PowerShell — script pede META_APP_SECRET via getpass (não eco)
python scripts/test_meta_deletion_callback.py
# Quando pedir "META_APP_SECRET:", colar valor copiado do Secret Manager (Step 4 setup)
# Output: <sig_b64>.<payload_b64>  (string completa signed_request)
```

Anotar output (`<signed_request_string>`) — uso no Step 2.

2. POST pra endpoint production com signed_request gerado:

```powershell
$signedRequest = "<signed_request_string>"  # paste from Step 1
$body = "signed_request=$signedRequest"
Invoke-WebRequest -Uri "https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/oauth/meta/data-deletion-callback" `
  -Method POST `
  -Body $body `
  -ContentType "application/x-www-form-urlencoded"
```

OR via curl (se preferir):

```bash
curl -X POST "https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/oauth/meta/data-deletion-callback" \
  -d "signed_request=<signed_request_string>" \
  -i
```

3. Esperar HTTP 200 + JSON response shape Meta-spec:

```json
{
  "url": "https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/legal/data-deletion-status/<UUID>",
  "confirmation_code": "<UUID>"
}
```

Anotar `<UUID>` retornado.

4. Browser → acessar status page público:

```
https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/legal/data-deletion-status/<UUID>
```

Esperar página HTML minimal em PT-BR mencionando "Solicitação de exclusão de dados recebida (código: `<UUID>`). Wellington (administrador V4) processará em até 30 dias úteis. Contato: wellinton.ribeiro@v4company.com"

5. Validar audit_log row inserida:

```sql
SELECT occurred_at, platform, action_type, operation, status, params_summary
FROM audit_log
WHERE platform = 'meta'
  AND operation = 'meta_data_deletion_request'
ORDER BY occurred_at DESC LIMIT 1;
```

Esperar 1 row:
- `platform = 'meta'`
- `action_type = 'auth'`
- `operation = 'meta_data_deletion_request'`
- `status = 'success'`
- `params_summary` JSON contém: `meta_user_id`, `confirmation_code` (matching UUID retornado), `expires` (Unix timestamp)
- `manager_id = NULL` (callback é unauthenticated — Meta server-to-server)

6. **Negative test — invalid signature:** modificar 1 char do `signed_request` (e.g. flip último char) e re-POST. Esperar HTTP 400 + body `{"detail": "Invalid signature"}`.

```powershell
$tamperedRequest = "<signed_request_with_1_char_changed>"
Invoke-WebRequest -Uri "https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/oauth/meta/data-deletion-callback" `
  -Method POST `
  -Body "signed_request=$tamperedRequest" `
  -ContentType "application/x-www-form-urlencoded" `
  -SkipHttpErrorCheck
```

7. Validar audit_log NÃO tem nova row pro invalid signature attempt (callback aborta antes do `audit_log.record`):

```sql
-- Esperar mesmo count que após Step 5 (não +1)
SELECT COUNT(*) FROM audit_log WHERE operation = 'meta_data_deletion_request';
```

**Validação:**

- [ ] Helper `scripts/test_meta_deletion_callback.py` gera signed_request sem erro (input `META_APP_SECRET` via getpass)
- [ ] POST com signed_request HMAC-valid retorna HTTP 200
- [ ] Response JSON contém `url` e `confirmation_code` keys
- [ ] `url` é absolute (https://...) apontando pra `/legal/data-deletion-status/<code>`
- [ ] `confirmation_code` é UUID válido (8-4-4-4-12 hex format)
- [ ] Browser GET `/legal/data-deletion-status/<UUID>` retorna HTML 200 com texto PT-BR
- [ ] HTML menciona `<UUID>` exato no body
- [ ] HTML menciona "Wellington" + email contato + janela "30 dias"
- [ ] Audit_log +1 entry com fields esperados (operation, params_summary completo, manager_id NULL)
- [ ] `params_summary.confirmation_code` matches UUID retornado no response (consistência)
- [ ] **Crítico negative:** signed_request tampered (1 char change) → HTTP 400 + `"Invalid signature"`
- [ ] **Crítico negative:** audit_log NÃO recebe row pra invalid signature attempt (zero leak via audit)
- [ ] Cloud Run logs negative case: WARN `meta_data_deletion_invalid_signature` (não ERROR — expected adversarial path)

**Failure modes investigation:**

- Helper falha gerar signed_request → bug script (verificar Python 3.12 + base64.urlsafe_b64encode usage)
- HTTP 400 com signed_request válido → `META_APP_SECRET` em Secret Manager DIFERE valor configurado em Meta App settings — F47 family (CRLF mangling); re-upload secret via arquivo binary intermediário
- HTTP 500 sem JSON response → exception não capturada em endpoint; investigate Cloud Run logs full stack
- `confirmation_code` retornado NÃO é UUID → bug `uuid4()` usage incorreto
- `url` retornado sem prefix HTTPS → bug hardcoded path em vez de absolute URL
- Status page 404 → route `/legal/data-deletion-status/{code}` não registrada em routes.py
- Audit_log row inserida pra invalid signature → bug fluxo: `_verify_meta_signed_request` retorno None NÃO está short-circuitando antes do audit_log.record (security/audit pollution)
- Status page em English → bug template `legal/data_deletion_status.html` strings literais

**Cleanup T6:**

Nenhum cleanup destrutivo necessário. Audit_log rows são audit trail (mantidas).

`Clear-History` PowerShell se META_APP_SECRET ficou exposto em buffer (low risk — getpass evita echo).

**Result:** ⬜ pending

---

## Test T7 — Revoke button UX (modal confirm + redirect + card update)

**Setup:** Validar fluxo UI completo de revoke connection via botão admin novo (substituindo POST direto via DevTools de M.2a T6). Esperar modal HTML5 `<dialog>` abrir ao click, confirm dispara POST `/oauth/meta/revoke`, redirect pra `/admin?meta_revoked=1`, card atualiza pra "Desconectado" + botão "Conectar Meta" (restore initial state).

**Pré-requisito:** Wellington logado em `/admin` com OAuth Meta ativo (T1 PASS implica). Modal `<dialog>` requires browser modern (Chrome/Edge/Firefox recent — `dialog.showModal()` API).

**Steps:**

1. Browser → `https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/admin` (logged in wellinton.ribeiro@v4company.com)
2. Localizar sub-card "Meta" no card "Suas conexões OAuth"
3. Verificar botões visíveis (após M.2b deploy):
   - Botão secundário "Atualizar lista" (cinza/light)
   - Botão danger "Revogar conexão" (vermelho)
4. Click "Revogar conexão"
5. Esperar modal `<dialog id="meta-revoke-modal">` abrir centralizado (browser native modal):
   - Título: "Revogar conexão Meta"
   - Texto: "Vai desativar todas as tools Meta até reconnect via /oauth/meta/start."
   - Pergunta: "Confirma?"
   - 2 botões: "Cancelar" (secondary) + "Revogar" (danger, submit form)
6. **Negative cancelar:** Click "Cancelar" → modal fecha sem ação. Connection ainda ativa.
   - Verificar `meta_oauth_connections.revoked_at` ainda NULL via SQL
7. Re-abrir modal (Step 4 repeat) e click "Revogar" (form submit POST `/oauth/meta/revoke`)
8. Esperar HTTP 302 redirect → `/admin?meta_revoked=1`
9. Página re-renderiza com:
   - Flash message verde/info "Conexão Meta revogada com sucesso"
   - Card Meta agora mostra "Desconectado" + botão "Conectar Meta" (sem botões refresh/revoke)
10. Validar DB state:

```sql
SELECT manager_id, fb_email, revoked_at, scopes
FROM meta_oauth_connections
WHERE manager_id = '<wellington_uuid>'
ORDER BY created_at DESC LIMIT 1;
```

Esperar:
- Row T1 ainda EXISTE (não deletada)
- `revoked_at`: timestamp ≈ now() ± 1 minuto
- `fb_email`, `scopes`: mantidos (audit trail)

11. Re-invocar tool Claude Desktop: "Liste minhas contas Meta" — esperar empty/error PT-BR consistente

**Validação:**

- [ ] 2 botões M.2b visíveis no card Meta connection ("Atualizar lista" + "Revogar conexão")
- [ ] Click "Revogar conexão" abre modal `<dialog>` (não window.confirm, não inline div)
- [ ] Modal mostra título, texto, 2 botões corretos
- [ ] Click "Cancelar" fecha modal sem submit (connection mantida ativa)
- [ ] Click "Revogar" submit POST `/oauth/meta/revoke` → HTTP 302 redirect
- [ ] Redirect URL final = `/admin?meta_revoked=1` (exact match)
- [ ] UI admin reflete "Desconectado" sem hard refresh manual necessário
- [ ] Flash message "Conexão Meta revogada com sucesso" (ou similar PT-BR) visible
- [ ] DB row T1 mantida, `revoked_at` populado timestamp recent
- [ ] **Crítico:** Row NÃO deletada (audit trail preserved)
- [ ] Tool `meta_list_my_ad_accounts` pós-revoke retorna empty array OR error PT-BR
- [ ] Audit_log +1 entry: `operation='meta_oauth_revoke'`, `status='success'`, `platform='meta'`
- [ ] Cancelar click cycle NÃO gera audit_log row (cancel é client-side only)

**Failure modes investigation:**

- Botões não aparecem → template `admin/index.html` não atualizado com M.2b code (re-deploy ou cache busted)
- Modal não abre ao click → `dialog.showModal()` JS error (browser old support), inspect DevTools console
- Modal abre mas não fecha em Cancel → bug `onclick="this.closest('dialog').close()"` mal escrito
- Submit "Revogar" não dispara POST → form `action="/oauth/meta/revoke"` ou `method="post"` faltando
- Redirect URL errado (e.g. `/admin` sem query param) → handler `meta_oauth_revoke` em routes.py não retorna `RedirectResponse("/admin?meta_revoked=1")`
- Flash message não aparece → admin_index handler não está reading `?meta_revoked=1` query param OR template não tem `{% if meta_revoked %}` block
- Card Meta ainda mostra "Conectado" pós-redirect → `get_active_for_manager` retorna row revoked (bug: WHERE clause não filter `revoked_at IS NULL`)
- DB row deletada em vez de revoked_at populated → bug revoke handler usa DELETE em vez de UPDATE

**Cleanup T7 → preparar T8:**

Re-conectar Wellington pra deixar OAuth ativo pra T8 e uso normal pós-smoke:

1. `/admin` → "Conectar Meta" → consent screen → "Permitir" todos 5 scopes
2. DB: nova row OR UPSERT existente com novo `token_expires_at ≈ now() + 60d`
3. Verificar `meta_oauth_connections.revoked_at IS NULL` novamente

**Result:** ⬜ pending

---

## Test T8 — Refresh button UX (sync sem reconnect, nova ad account aparece)

**Setup:** Validar fluxo refresh-accounts via botão admin. Pré-condição: 1 ad account NOVA foi adicionada no BM Meta (Pre-smoke Step 5) ANTES do click. Após click "Atualizar lista", esperar redirect `/admin?meta_refreshed=1`, flash message com count atualizado, e nova ad account aparecer na lista do card (sem necessidade de reconnect OAuth).

**Pré-requisito:** T7 cleanup feito (OAuth Wellington ativo novamente). Pre-smoke Step 5 done (1 nova ad account adicionada no BM via Business Suite). Token Wellington >7d (não expirado).

**Steps:**

1. Validar baseline `meta_ad_accounts` cache local antes do refresh:

```sql
SELECT COUNT(*) AS pre_refresh
FROM meta_ad_accounts;
-- Anotar count (e.g. 12 — V4 LS&Co BM pre-Step 5)
```

2. Browser → `/admin` logged in
3. Card Meta connection mostra "Conectado" + 2 botões "Atualizar lista" + "Revogar conexão"
4. Click "Atualizar lista" (form POST submit, sem modal — ação non-destructive)
5. Esperar HTTP 302 redirect → `/admin?meta_refreshed=1`
6. Página re-renderiza com:
   - Flash message verde "Lista de ad accounts atualizada. N accounts sincronizadas." (N = novo total, e.g. 13)
   - Card Meta agora mostra nova ad account na lista (Wellington olha visualmente, depende UX exact display)
7. Validar DB pós-refresh:

```sql
SELECT COUNT(*) AS post_refresh
FROM meta_ad_accounts;
-- Esperar count > pre_refresh (+1 se Step 5 adicionou 1 nova)

-- Verificar nova ad_account_id aparece (Wellington sabe qual foi adicionada em Step 5)
SELECT ad_account_id, account_name, currency, account_status
FROM meta_ad_accounts
WHERE ad_account_id = 'act_<id_novo_step5>';
-- Esperar 1 row com fields populated
```

8. Validar grant `manager_meta_account_access` row criada pra nova account:

```sql
SELECT manager_id, ad_account_id, granted_at
FROM manager_meta_account_access
WHERE manager_id = '<wellington_uuid>'
  AND ad_account_id = 'act_<id_novo_step5>';
-- Esperar 1 row recent (granted_at ≈ now)
```

9. Re-invocar tool: Claude Desktop "Liste minhas contas Meta" — esperar `total_accounts` aumentado em 1, nova account aparece na lista

10. **Negative test — token expirado:** force token expiry pra past (similar T4) + click "Atualizar lista":

```sql
UPDATE meta_oauth_connections
SET token_expires_at = NOW() - INTERVAL '1 day'
WHERE manager_id = '<wellington_uuid>' AND revoked_at IS NULL;
```

Click "Atualizar lista" → esperar HTTP 422 + body em PT-BR "Token Meta expirou. Reconectar via /oauth/meta/start."

Restore: `UPDATE meta_oauth_connections SET token_expires_at = '<original_value>' WHERE ...;` OR re-OAuth.

**Validação:**

- [ ] Botão "Atualizar lista" visível no card (M.2b deploy applied)
- [ ] Click dispara form POST sem modal (UX direto — non-destructive action)
- [ ] HTTP 302 redirect → `/admin?meta_refreshed=1` (exact URL)
- [ ] Flash message PT-BR "Lista de ad accounts atualizada. N accounts sincronizadas." visible
- [ ] N matches post_refresh count exato (consistência)
- [ ] DB `meta_ad_accounts` count aumentou em 1 (nova account de Step 5)
- [ ] Nova `ad_account_id` aparece em DB com fields populated (`account_name`, `currency`, `account_status`, `timezone_name`, `business_id`, `business_name`)
- [ ] `manager_meta_account_access` row criada pra (wellington_uuid, ad_account_id_novo) com `granted_at` recent
- [ ] Tool `meta_list_my_ad_accounts` re-invoke retorna nova account na lista (`total_accounts` +1)
- [ ] Audit_log +1 entry: `operation='meta_refresh_accounts'`, `target_count=N` (count synced), `status='success'`, `platform='meta'`
- [ ] **Negative token expired:** HTTP 422 + body PT-BR "Token Meta expirou. Reconectar via /oauth/meta/start."
- [ ] **Negative token expired:** ZERO Graph API call feita (validar Cloud Run logs sem `meta.graph.call.start` durante negative test)
- [ ] **Negative token expired:** ZERO DB write em `meta_ad_accounts` durante negative test
- [ ] **Negative cleanup:** restore `token_expires_at` original → click refresh novamente → PASS normal

**Failure modes investigation:**

- Botão "Atualizar lista" não aparece → template não updated, re-deploy ou cache busted
- Click não dispara POST → form action/method faltando
- HTTP 302 mas redirect URL errado → handler em routes.py retorna URL diferente
- Flash message com count errado → admin_index handler bug parsing `?meta_refreshed=1` ou template `{% if meta_refreshed_count %}` block
- Nova account NÃO aparece em DB → bug `meta_ad_accounts.upsert_many` (e.g. ON CONFLICT update only, INSERT skipped)
- grant row faltando → bug `manager_meta_account_access.grant` não chamado dentro do loop
- Token expired test retorna HTTP 500 em vez de 422 → bug guard `if oc.token_expires_at and (oc.token_expires_at - now).days < 0` faltando OR raise HTTPException com status_code errado
- Negative test Graph call feita mesmo com token expired → guard mal posicionado (antes do httpx call mas após decryption?)
- Race condition se 2 clicks rápidos consecutivos → upsert idempotent (ON CONFLICT) deve handle; só observar Cloud Run logs

**Cleanup T8:**

Estado final esperado: `meta_ad_accounts` count = pre_smoke_count + 1 (nova account de Step 5 mantida). Não há cleanup destrutivo. Nova account fica sincronizada pra uso futuro.

Se Wellington quiser remover a nova ad account do BM (caso fosse só pra teste), fazer via Business Suite UI — próximo refresh sincronizará deleção.

**Result:** ⬜ pending

---

## Per-value empirical probe (Sprint 3b.19A.1 convention)

**Tool M.2b probe coverage:**

Tool `meta_get_account_overview` tem 1 enum whitelist em schema (`date_range` com 6 values). Probe per-value abaixo cobre todos.

Adicionalmente, `actions[]` parsing (T2) é per-value probe implícito sobre o filter set `CONVERSION_ACTION_TYPES` (6 valores frozenset).

### Probe date_range whitelist (6 values)

Cada value validado empiricamente em T1+T2 (via re-invocações com date_range diferente). Account ATIVO Wellington personal `act_383566922510173` recomendado pra speed.

| # | date_range value | Expected window | Result |
|---|---|---|---|
| D1 | `LAST_7_DAYS` | `(today-6d, today)` | ⬜ pending (T1 cobre) |
| D2 | `LAST_14_DAYS` | `(today-13d, today)` | ⬜ pending |
| D3 | `LAST_30_DAYS` | `(today-29d, today)` | ⬜ pending |
| D4 | `LAST_90_DAYS` | `(today-89d, today)` | ⬜ pending |
| D5 | `TODAY` | `(today, today)` | ⬜ pending |
| D6 | `YESTERDAY` | `(today-1d, today-1d)` | ⬜ pending |

Probe loop sugerido (Wellington batch após T1 PASS):

```
Pra cada D2-D6:
  1. Claude Desktop prompt: "Overview Meta act_383566922510173 <preset>"
  2. Validar response date_range.start + date_range.end matchando tabela
  3. status='success' + _warnings empty (account saudável)
  4. Mark ⬜ → ✅
```

Critério: 6/6 values empiricamente aceitos sem error/warning anômalo = date_range whitelist validado.

### Probe CONVERSION_ACTION_TYPES filter (6 values implicit em T2)

Frozenset em `account_overview.py`:

| # | action_type | Origem | T2 expected |
|---|---|---|---|
| A1 | `purchase` | Web/checkout standard | Incluído em conversions sum |
| A2 | `lead` | Lead form Meta | Incluído em conversions sum |
| A3 | `complete_registration` | Signup flow | Incluído em conversions sum |
| A4 | `offsite_conversion.fb_pixel_purchase` | Pixel-based purchase | Incluído em conversions sum |
| A5 | `offsite_conversion.fb_pixel_lead` | Pixel-based lead | Incluído em conversions sum |
| A6 | `offsite_conversion.fb_pixel_complete_registration` | Pixel-based signup | Incluído em conversions sum |

T2 valida que `conversions` retornado = sum desses 6 types (excluindo outros action_types como `page_engagement`, `post_engagement`, `video_view`, `landing_page_view`, etc.). Critério: filter set não vaza non-conversion events em sum.

**Future probe expansion (M.3+):**

Tools Meta futuros vão ter mais enums whitelist — `objective`, `bid_strategy`, `optimization_goal`, `billing_event`, `placement` (provavelmente 10+ values cada). Per-value probe convention escala — cada sprint M.X+ adicionará tabela probe no smoke runbook.

---

## V4 invariants validation

| Invariant | Aplicável | Enforcement | How smoke verifies |
|---|---|---|---|
| country_code = BR | N/A | N/A — V4 LS&Co BM BR-only por configuração | — |
| language_code = pt-BR | ✅ User-facing | Mensagens error PT-BR (`error_message`), warnings PT-BR (`_warnings`), labels PT-BR (`account_status_label`), tool description PT-BR | T1+T3+T4 valida labels/warnings; T5 valida errors PT-BR |
| currency_code = BRL | ✅ Output | `meta_ad_accounts.currency` cached as Meta returns (BRL pra V4 BM); tool retorna `currency` field passthrough | T1 valida `currency: "BRL"` na response |
| timezone = America/Sao_Paulo | N/A direct return | Account-level metric — timezone afeta time_range interpretação Meta server-side (UTC-3 BR) | Implícito — T1 LAST_7_DAYS valida que datas resolved fazem sense pra BR ops |
| LGPD consent | ✅ Critical | OAuth M.2a consent screen + scope `email` + audit_log captura connect; M.2b `/oauth/meta/data-deletion-callback` endpoint LGPD-required + status page público | T6 valida endpoint + audit_log; LGPD 30d window documentado em status page |
| Schema whitelist (3b.19A) | ✅ Output | Tool input schema com `date_range` enum 6 values; runtime aceita todos via `resolve_meta_date_window` | T1 (LAST_7_DAYS) + probe D2-D6 cobrem 6/6 |
| No composition keywords (3b.19B.1) | ✅ Schema | Input schema sem `oneOf/allOf/anyOf` — cross-field constraint expressa em `_validate_input` helper | Regression `test_no_composition_keywords_in_any_schema` (pre-push) |
| Audit log multi-platform | ✅ Foundation | `audit_log.record(platform="meta", provider_request_id=x_fb_trace_id)` em `run_meta_graph_get` (M.2a) + `meta_data_deletion_request` em T6 | T1 audit_log entry + T6 audit_log entry validam |
| A5 platform field exposed | ✅ A5 fix | `get_my_audit_log` SELECT inclui `platform` column; rows retornadas têm field | Lookback após T1+T6 — re-rodar `get_my_audit_log` pós-smoke e validar entries têm `platform` field populated |
| Token expiry proactive warning | ✅ UX | `build_warnings` threshold <7d; surfaced em `_warnings` array; admin UI banner amarelo | T4 valida warning surface + UI banner |
| Account_status warning surface | ✅ UX | `build_warnings` condition `account_status_label != "ATIVO"`; surfaced em `_warnings` array | T3 valida warning surface (PAGAMENTO_PENDENTE) |
| HMAC validation deletion callback | ✅ Security | `_verify_meta_signed_request` compare_digest constant-time + reject invalid algorithm | T6 valid sig PASS + invalid sig 400 |
| Audit_log unauthed protection | ✅ Security | `meta_data_deletion_callback` insere `manager_id=NULL` (Meta server-to-server) + valid HMAC gate | T6 valida row inserted only com valid sig; invalid sig → ZERO row inserted (no audit pollution) |
| Refresh sem reconnect | ✅ UX | `/oauth/meta/refresh-accounts` usa long-lived token existente; rejected se expired | T8 valida sync + negative test 422 token expired |
| Modal confirm destructive action | ✅ UX | "Revogar conexão" HTML5 `<dialog>` modal blocking; "Atualizar lista" sem modal (non-destructive) | T7 valida modal flow; T8 valida sem modal |
| Read-only Graph call no CONFIRM | ✅ Pattern | `meta_get_account_overview` classify `blast_radius=read_only` → executa direto sem CONFIRM workflow | T1 invocação direta sem prompt CONFIRM |
| BUC counter recording | ✅ Foundation | `run_meta_graph_get` parseia `X-Business-Use-Case-Usage` header → `meta_rate_counters.increment_actual_meta` | Validar `meta_rate_counters` rows pós-T1+T2 — incremento esperado em call_count (BUC pct opcional) |

---

## Cleanup post-smoke

Não há cleanup destrutivo necessário. State pós-smoke esperado:

- `meta_oauth_connections`: 1 row ativa Wellington (re-connected em T7 cleanup) com `revoked_at IS NULL`, `token_expires_at ≈ now() + 60d`
- `meta_ad_accounts`: cache count = pre_smoke + 1 (nova ad account de T8 Step 5 sincronizada — fica no cache pra uso normal)
- `manager_meta_account_access`: +1 grant row pra nova account (idempotente — sem duplicação)
- `audit_log`: ≥7 novas entries Meta (T1 happy + T2 probe + T3 status_warn + T4 token_warn + T5 errors + T6 deletion_request + T7 revoke + T7 reconnect + T8 refresh + T8 negative restore)
- `audit_log`: distribution `platform='meta'` populated, A5 fix expostas via `get_my_audit_log`
- Status: Sprint M.2b shipped ✅, Meta App Review ready (Task J Wellington fora-MCP)

**Rollback se smoke falhou (T1 CRITICAL FAIL ou T6 security fail):**

```sql
-- 1. Marcar connection Meta revogada (limpar state)
UPDATE meta_oauth_connections
SET revoked_at = now()
WHERE manager_id = '<wellington_uuid>' AND revoked_at IS NULL;

-- 2. Limpar audit_log entries M.2b smoke (opcional, geralmente prefere manter audit trail)
-- DELETE FROM audit_log WHERE platform='meta' AND occurred_at >= '<smoke_start_timestamp>';
```

Investigar logs:

```
gcloud run services logs read v4-ads-mcp \
  --region=southamerica-east1 \
  --project=v4-ads-mcp-prod \
  --limit=200
```

Rollback deploy se T1/T5/T6 CRITICAL:

```bash
gcloud run revisions list --service=v4-ads-mcp --region=southamerica-east1 --limit=5

gcloud run services update-traffic v4-ads-mcp \
  --region=southamerica-east1 \
  --to-revisions=<previous_revision>=100
```

Fix forward é preferível a rollback — investigate + corrige + re-deploy.

---

## Notas pra Wellington pós-smoke

1. **Sprint M.2b fecha sprint family M.2** (M.2a foundation + M.2b first real Graph). Próximo: **decision gate 2 semanas dogfood** — Wellington usa `meta_get_account_overview` em real biz (ICSER weekly review, ML Antiguidades billing audit) — ≥3 usos/semana = continua M.3-M.25; <3 = pause Meta + foca Google backlog (3b.38+ candidates).

2. **Meta App Review submit (Task J fora-MCP):** Wellington manual após smoke 8/8 PASS:
   - Meta App settings → App Review tab
   - Request advanced permissions: `ads_read`, `ads_management`, `business_management` (3 scopes)
   - Screencast required ~3-5 min: OAuth flow + admin card + Claude Desktop demo `meta_get_account_overview`
   - Submit → timeline 5-30d business days
   - Fallback se rejected: Dev Mode 25 admins continua válido enquanto re-submit feedback

3. **A5 finding CLOSED:** marcar em `findings-catalog.md` — Task A shipped + smoke validou platform field via lookback `get_my_audit_log` retorno pós-T1+T6. Mover de OPEN → CLOSED.

4. **F47 lesson reforçada em T6:** se T6 HMAC validation falhar com `META_APP_SECRET` que parecia correto, alta probabilidade é CRLF mangling em PowerShell upload. Re-upload via arquivo binary intermediário (procedure em CLAUDE.md "Meta SDK conventions"). Não tentar `gcloud secrets versions add | echo ...`.

5. **Dogfood findings expected:** primeira tool Graph real em prod tipicamente revela 2-3 quirks Meta SDK não-cobertos por docs:
   - actions[] action_types discovery (per account pode ter custom events)
   - purchase_roas multi-window vs default-attribution
   - currency conversion se conta multi-currency (não esperado V4 BR-only, mas worth watching)
   - Documentar em `docs/operacao/dogfood-2026-05-XX-meta-account-overview-findings.md` (criar se Wellington fizer ≥3 real biz queries primeira semana)

6. **Roadmap M.3 candidates:** spec brainstorm próximo:
   - `meta_get_campaign_performance(account_id, date_preset)` — paralelo Google `get_campaign_performance`
   - `meta_list_campaigns(account_id)` — paralelo Google `list_campaigns` (cache strategy similar a `meta_list_my_ad_accounts`?)
   - `meta_get_adset_performance(campaign_id)` — drill-down level
   - Decisão depende dogfood findings (Wellington uso real determina priority)

7. **Tool count tracking:** atualizar CLAUDE.md sprint counter + sprint-history.md após signoff. **Tool count 58 → 59** (1ª Meta Graph API real). Tabela "Shipped — Meta Ads":
   ```
   | Sprint M.2b — first Graph API + App Review prep | ✅ <data> | meta_get_account_overview + data-deletion endpoint + refresh-accounts + UI extensions + A5 fix. Tool count 58→59. |
   ```

8. **F-finding catalog update:** se T1-T8 emergirem F-findings (provável em primeira Graph call real — Meta SDK quirks, parsing edges, token timing), usar `/findings-add` skill. Probable families: F17/F18 (numeric format), parsing wrong action_types, HMAC edge case, UI race condition.

9. **`_warnings` field convention** estabelecida em M.2b: tools Meta futuras com Graph data SHOULD surface anomalies em `_warnings` array (NÃO error/exception). Threshold examples: account_status problemático, token <7d, BUC throttle >75%, data delays Meta >24h, currency mismatch detected. Pattern reutilizável M.3+.

10. **Decision gate calendário:** 2 semanas pós-M.2b ship → revisar `audit_log WHERE platform='meta' AND manager_id='<wellington>' AND occurred_at >= now() - 14d` count. ≥6 calls (3/semana × 2 semanas) = green light M.3-M.25. <6 = pause + retro post-mortem ("ROI real foi menor que esperado, foca onde gera mais valor").
