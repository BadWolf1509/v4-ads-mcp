# Phase 3b.33 — manual smoke runbook (`detect_drift`)

**Purpose:** Validar Sprint 3b.33 — nova tool `detect_drift` (54ª MCP tool) que detecta mudanças NÃO-autorizadas em conta Google Ads (workflow co-management V4 pós-batch). Compara `change_event` rows com `responsible_user_emails[]`: tudo NÃO-listado conta como drift. Auto-apply Recommendations sempre conta como drift. Output: `summary` (counts + by_user/resource_type/operation) + `flags[]` (auto_apply_detected, multiple_users_detected, structural_change) + `changes[]` (até limit, default 100 max 500) + `truncated` + `returned_count`. Wrapper sobre `get_change_history` (DRY máximo — zero novos GAQL).

**Operator:** wellinton.ribeiro@v4company.com
**Account principal:** `7862230676` Mestre da Obra JP (production V4 — caso real Pedro Vytor 20/05 dentro de window 30d)
**Account secundária:** `7455088726` ML Antiguidades (conta clean — T6)

**Spec:** `docs/superpowers/specs/2026-05-21-sprint-3b-33-detect-drift-design.md`
**Plan:** `docs/superpowers/plans/2026-05-21-sprint-3b-33-detect-drift.md`
**Dogfood source:** `docs/operacao/dogfood-2026-05-21-mestre-da-obra-jp-drift-detection.md` (W1, ICE 486)

> **Escopo V0 confirmado:**
> - Input: `customer_id` (req) + `responsible_user_emails[]` (optional, max 20, format email) + `date_range` preset (default `LAST_2_DAYS`) + `start_date+end_date` custom (override preset) + `limit` (default 100, max 500)
> - Output: `summary` (total_drift_changes + total_changes_in_window + by_user/by_resource_type/by_operation) + `flags[]` + `changes[]` (DESC by change_date_time) + `truncated` + `returned_count` + `period` + echo `responsible_user_emails`
> - 3 flags V0: `auto_apply_detected` (low), `multiple_users_detected` (medium), `structural_change` (high — REMOVE em CAMPAIGN/AD_GROUP/CONVERSION_ACTION)
> - Auto-apply (`client_type=GOOGLE_ADS_RECOMMENDATIONS`) SEMPRE conta como drift (bucket sintético "auto-apply" em by_user)
> - Email matching case-insensitive (normalize lowercase + strip)
> - Sempre auditado (`audit_this_call=True` herdado de `get_change_history`)
> - Tool count: 53 → **54**

## Production URL

`https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app`

## Pre-flight

- [ ] Deploy lands successfully (CI + Deploy green em commit final A2/A3/A4)
- [ ] Service `/health` returns 200 (`{"status":"ok","version":"0.1.0"}`)
- [ ] Tool `detect_drift` registered (test_registered_tool_count_matches_files_on_disk 54==54 PASS)
- [ ] Pre-push gate `python scripts/check_pre_push.py` 5/5 PASS
- [ ] Schema regression `test_no_composition_keywords_in_any_schema` passa
- [ ] Unit tests `tests/unit/test_drift_detection.py` 19/19 PASS (16 algorithm + 3 boundary)
- [ ] Integration tests `tests/integration/test_detect_drift.py` 3/3 PASS
- [ ] MCP Inspector / Claude client conectado à URL de produção e enxerga `detect_drift` na tool list

Production revisions: `v4-ads-mcp-XXXXX-xxx` (preencher após deploy final).

## Smoke results

Preencher conforme execução. Marcar resultado final no fim do arquivo.

| # | Test | Result | Notes |
|---|---|---|---|
| T1 | Schema default — sem `responsible_user_emails` (incident mode) em MO-JP | ⬜ pending | |
| T2 | Co-management — `responsible_user_emails=[wellinton]` LAST_2_DAYS em MO-JP (Pedro Vytor cluster) | ⬜ pending | |
| T3 | Custom date range — `start_date=2026-05-20 end_date=2026-05-20` em MO-JP (reproduz cluster exato) | ⬜ pending | |
| T4 | Limit truncation — `limit=2` em conta com 5+ drift (MO-JP) | ⬜ pending | |
| T5 | Flag `structural_change` — conta com REMOVE em CAMPAIGN/AD_GROUP/CONVERSION_ACTION últimos 7d | ⬜ pending | |
| T6 | Empty drift — conta clean (ML Antiguidades) | ⬜ pending | |

**Effective result:** N/6 PASS + Y DEFERRED

### F-findings emerged

_Preencher durante smoke. Template: `**F## (SEV)** — <symptom>. Fix: <plan>. Family: <bug class>.`_

Se zero F-findings: documentar explicitly "Zero F-findings novos. Sprint clean."

### Sign-off

- [ ] Pre-push gate 5/5 PASS
- [ ] Spec compliance + code quality reviewers APPROVED (A1, A2)
- [ ] Production `/health` 200 (revisão final)
- [ ] T1-T4 PASS (incident mode + co-management + custom range + truncation em MO-JP)
- [ ] T5 PASS ou DEFERRED (env limitation se sem REMOVE recente — pattern F41/F45)
- [ ] T6 PASS ou DEFERRED (env limitation se ML sem mudanças mensuráveis)
- [ ] CLAUDE.md sprint counter atualizado (3b.32 → 3b.33) + tool count 53 → 54
- [ ] sprint-history.md updated com entry Sprint 3b.33
- [ ] findings-catalog.md atualizado se F-findings emergiram (`/findings-add` skill)
- [ ] Tool count 54 confirmado em produção (test_registered_tool_count_matches_files_on_disk 54==54)

---

## Pre-smoke setup

### Step 1: Sanity check no MCP client

Conectar Claude/Inspector à URL de produção (`https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app`) e verificar que `detect_drift` aparece na lista de tools com parâmetros corretos:

```
# Introspect — esperar ver detect_drift com:
# - customer_id required (pattern ^[0-9]{10}$)
# - responsible_user_emails optional (array of email, maxItems 20)
# - date_range optional (enum: LAST_2_DAYS|TODAY|YESTERDAY|LAST_7_DAYS|LAST_14_DAYS|LAST_30_DAYS, default LAST_2_DAYS)
# - start_date, end_date optional (YYYY-MM-DD, custom range override)
# - limit optional (integer 1-500, default 100)
```

Se `detect_drift` não aparece ou tool count ainda 53, deploy não landed — abortar smoke.

### Step 2: Reference numbers pré-smoke

Capturar baseline via `get_change_history` direto pra validação cruzada nos cenários T1-T4:

```
# Baseline raw changes em MO-JP janela LAST_2_DAYS (raw para comparar com detect_drift)
get_change_history(
  customer_id="7862230676",
  date_range="LAST_2_DAYS",
  limit=500
)
```

Anotar:
- `total` raw (= `total_changes_in_window` esperado em detect_drift T1)
- Lista de `user_email` distintos no período (esperado: wellinton + pedro.vytor)
- Cluster 4 changes de Pedro Vytor em 2026-05-20 ~10:13 (campaigns CAB + JPA, AI Max + TEXT_ASSET_AUTOMATION)
- Qualquer `client_type=GOOGLE_ADS_RECOMMENDATIONS` (auto-apply rows)

```
# Baseline raw changes em ML Antiguidades janela LAST_2_DAYS (T6)
get_change_history(
  customer_id="7455088726",
  date_range="LAST_2_DAYS",
  limit=500
)
```

Anotar:
- `total` raw (esperar 0 ou muito baixo se ML clean)
- Se >0 changes: anotar `user_email` distintos (T6 pode precisar `responsible_user_emails` apropriado)

### Step 3: Identificar conta candidata pra T5 (structural_change)

T5 precisa de conta com REMOVE em CAMPAIGN/AD_GROUP/CONVERSION_ACTION nos últimos 7 dias. Wellington escolhe best-effort:

```
# Probe em MO-JP primeiro
get_change_history(
  customer_id="7862230676",
  date_range="LAST_7_DAYS",
  limit=500
)
# Filtrar mentalmente operation=REMOVE em rows com resource_type em CAMPAIGN/AD_GROUP/CONVERSION_ACTION
```

Se nenhum REMOVE estrutural em MO-JP: probar outras contas (ML Antiguidades, accounts MCC `6436352492`). Se nenhuma conta acessível tem REMOVE estrutural recente → T5 DEFERRED com nota (env limitation, pattern F41/F45).

---

## Test T1 — Schema default sem `responsible_user_emails` (incident mode)

**Setup:** Caso "incident mode" — sem lista de autorizados, TODOS os changes contam como drift. Smoke valida shape default + that lista vazia funciona.

**Tool call:**

```
detect_drift(
  customer_id="7862230676"
)
```

**Expected output (shape):**

```json
{
  "customer_id": "7862230676",
  "period": {
    "from": "2026-05-19",
    "to": "2026-05-21",
    "days": 3
  },
  "responsible_user_emails": [],
  "summary": {
    "total_drift_changes": N,
    "total_changes_in_window": N,
    "by_user": {
      "wellinton.ribeiro@v4company.com": ...,
      "pedro.vytor@v4company.com": ...
    },
    "by_resource_type": {...},
    "by_operation": {...}
  },
  "flags": [
    /* possível auto_apply_detected se houver auto-apply rows */
    /* possível multiple_users_detected se 2+ users na janela */
  ],
  "changes": [
    /* todos os changes do período como DriftChange rows, DESC by change_date_time */
  ],
  "truncated": false,
  "returned_count": N
}
```

*(Datas exatas dependem do dia. Hoje 2026-05-21 → LAST_2_DAYS resolve para [2026-05-19, 2026-05-21] ou [2026-05-20, 2026-05-21] dependendo da implementação `resolve_date_window`.)*

**Validação:**

- [ ] Response tem `customer_id` = `"7862230676"`
- [ ] `period.days` está entre 2 e 3 (LAST_2_DAYS inclusive)
- [ ] `responsible_user_emails` = `[]` (default echo)
- [ ] `summary.total_drift_changes` == `summary.total_changes_in_window` (incident mode — tudo é drift)
- [ ] `summary.by_user` lista TODOS os users (wellinton, pedro.vytor, etc) com count > 0
- [ ] `summary.by_resource_type` e `summary.by_operation` populated com counts coerentes
- [ ] `flags[]` pode conter `multiple_users_detected` (se 2+ users distintos não-autorizados na janela)
- [ ] `flags[]` pode conter `auto_apply_detected` (se algum row com `client_type=GOOGLE_ADS_RECOMMENDATIONS`)
- [ ] `changes[]` length == `returned_count` && <= 100 (default limit)
- [ ] `changes[]` ordenados DESC por `change_date_time` (primeiro entry é o mais recente)
- [ ] `truncated` = `false` se `total_drift_changes <= 100`, `true` caso contrário
- [ ] Audit_log entry criada (verificar via `/admin/audit` ou DB)
- [ ] Rate_counter +1

**Result:** ⬜ pending

---

## Test T2 — Co-management `responsible_user_emails=[wellinton]` LAST_2_DAYS

**Setup:** Use case primário V0 — Wellington é gestor responsável, lista a si mesmo como autorizado. Pedro Vytor 20/05 cluster aparece como drift (4 changes). Wellington próprias changes NÃO aparecem.

**Tool call:**

```
detect_drift(
  customer_id="7862230676",
  responsible_user_emails=["wellinton.ribeiro@v4company.com"],
  date_range="LAST_2_DAYS"
)
```

**Expected:**

```json
{
  "customer_id": "7862230676",
  "period": {"from": "2026-05-19", "to": "2026-05-21", "days": 3},
  "responsible_user_emails": ["wellinton.ribeiro@v4company.com"],
  "summary": {
    "total_drift_changes": 4,
    "total_changes_in_window": N,
    "by_user": {
      "pedro.vytor@v4company.com": 4
    },
    "by_resource_type": {"CAMPAIGN": 4},
    "by_operation": {"UPDATE": 4}
  },
  "flags": [
    /* multiple_users_detected NÃO emitida (apenas 1 user não-autorizado: pedro.vytor) */
    /* auto_apply_detected NÃO emitida (Pedro Vytor mexeu via WEB_CLIENT) */
  ],
  "changes": [
    {
      "change_date_time": "2026-05-20 10:13:00...",
      "user_email": "pedro.vytor@v4company.com",
      "client_type": "GOOGLE_ADS_WEB_CLIENT",
      "resource_type": "CAMPAIGN",
      "resource_id": "...",
      "resource_name": "CAB - Geral" ou "JPA - Geral",
      "operation": "UPDATE",
      "changed_fields": ["campaign.ai_max_setting.enable_ai_max" ou "...text_asset_automation..."],
      "campaign_id": "...",
      "ad_group_id": null
    },
    /* mais 3 entries Pedro Vytor, todos no cluster 20/05 ~10:13 */
  ],
  "truncated": false,
  "returned_count": 4
}
```

*(Caso depende do cluster Pedro Vytor estar dentro de window 30d. Se já fora — DEFERRED.)*

**Validação:**

- [ ] `responsible_user_emails` = `["wellinton.ribeiro@v4company.com"]` (echo)
- [ ] `summary.total_changes_in_window` >= `summary.total_drift_changes` (alguns changes wellinton excluídos)
- [ ] `summary.total_drift_changes` >= 4 (cluster Pedro Vytor)
- [ ] `summary.by_user` NÃO contém `wellinton.ribeiro@v4company.com` (filtrado)
- [ ] `summary.by_user["pedro.vytor@v4company.com"]` >= 4
- [ ] `flags[]` NÃO contém `multiple_users_detected` (apenas Pedro Vytor não-autorizado)
- [ ] `changes[]` contém entries com `user_email = "pedro.vytor@v4company.com"` (zero wellinton)
- [ ] Pelo menos 1 entry tem `changed_fields` contendo `"ai_max"` OU `"text_asset_automation"` (matching caso 20/05)
- [ ] `resource_name` preenchido (não vazio) — `get_change_history._resolve_names` herdado
- [ ] Audit_log +1 entry

**Result:** ⬜ pending

---

## Test T3 — Custom date range `start_date=2026-05-20 end_date=2026-05-20`

**Setup:** Custom range overriding preset — pinpoint exato no dia do incidente Pedro Vytor. Valida `start_date+end_date` override + `period.days=1`.

**Tool call:**

```
detect_drift(
  customer_id="7862230676",
  responsible_user_emails=["wellinton.ribeiro@v4company.com"],
  start_date="2026-05-20",
  end_date="2026-05-20"
)
```

**Expected:**

```json
{
  "period": {"from": "2026-05-20", "to": "2026-05-20", "days": 1},
  "summary": {
    "total_drift_changes": 4,
    "total_changes_in_window": N,
    "by_user": {"pedro.vytor@v4company.com": 4},
    "by_resource_type": {"CAMPAIGN": 4}
  },
  "changes": [
    /* exatamente 4 entries Pedro Vytor, todos 2026-05-20 */
  ],
  "returned_count": 4
}
```

**Validação:**

- [ ] `period.from` = `"2026-05-20"` && `period.to` = `"2026-05-20"`
- [ ] `period.days` = `1` (BETWEEN inclusive: 1 - 1 + 1 = 1)
- [ ] Custom range OVERRIDE do `date_range` preset (LAST_2_DAYS default ignorado)
- [ ] `summary.total_drift_changes` == 4 (cluster exato Pedro Vytor)
- [ ] Todos `changes[].change_date_time` começam com `"2026-05-20"`
- [ ] Pelo menos 2 campaigns distintos: CAB-Geral (`22169885957`) E JPA-Geral (`21359547724`)
- [ ] `changed_fields` cobre 2 fields: `ai_max_setting.enable_ai_max` E `text_guidelines.text_asset_automation` (ou similar)

**Fallback se Pedro Vytor cluster fora window 30d:** marcar DEFERRED — env limitation. Note: "Caso 20/05 fora de window — pattern F41/F45 (env limitation = doc only, não bug). Coverage via integration test `test_co_management_filter_pedro_drift` suficiente."

**Result:** ⬜ pending

---

## Test T4 — Limit truncation `limit=2` em conta com 5+ drift

**Setup:** Forçar truncate. Em janela com 5+ drift changes, `limit=2` retorna apenas 2 entries em `changes[]` mas `summary.total_drift_changes` reflete contagem total real.

**Tool call:**

```
detect_drift(
  customer_id="7862230676",
  responsible_user_emails=["wellinton.ribeiro@v4company.com"],
  date_range="LAST_7_DAYS",
  limit=2
)
```

**Expected:**

```json
{
  "period": {"from": "2026-05-14", "to": "2026-05-21", "days": 8},
  "summary": {
    "total_drift_changes": N (>= 5),
    "total_changes_in_window": M (>= N)
  },
  "changes": [
    /* exatamente 2 entries, os 2 mais recentes (DESC by change_date_time) */
  ],
  "truncated": true,
  "returned_count": 2
}
```

**Validação:**

- [ ] `summary.total_drift_changes` >= 5 (assume MO-JP tem volume nos últimos 7d incluindo cluster Pedro Vytor)
- [ ] `returned_count` = 2
- [ ] `len(changes)` = 2
- [ ] `truncated` = `true`
- [ ] `summary.by_user` reflete contagem TOTAL (não truncada — summary é pre-limit)
- [ ] `summary.by_resource_type` reflete contagem TOTAL
- [ ] `changes[0].change_date_time >= changes[1].change_date_time` (DESC ordering)

**Fallback se MO-JP <5 drift no período:** rodar com `date_range=LAST_30_DAYS` ou aumentar window. Se ainda <5 → marcar PASS com nota "truncated=false esperado (volume insuficiente, env limitation)" e validar shape preservation. Safety net via integration tests + unit `test_truncation_limit_exceeded`.

**Result:** ⬜ pending

---

## Test T5 — Flag `structural_change` em conta com REMOVE estrutural recente

**Setup:** Best-effort — flag `structural_change` (severity high) emitida quando há `operation=REMOVE` em `resource_type ∈ {CAMPAIGN, AD_GROUP, CONVERSION_ACTION}` no período. Wellington identificou conta candidata em pre-smoke setup Step 3.

**Tool call (conta a determinar em pre-smoke):**

```
detect_drift(
  customer_id="<CONTA_COM_REMOVE>",
  date_range="LAST_7_DAYS"
)
```

**Expected:**

```json
{
  "flags": [
    {
      "code": "structural_change",
      "severity": "high",
      "message_pt": "N REMOVE(s) em recursos estruturais (CAMPAIGN/AD_GROUP/CONVERSION_ACTION). Investigação obrigatória.",
      "evidence": {
        "removed_resources": [
          {"resource_type": "CAMPAIGN" | "AD_GROUP" | "CONVERSION_ACTION", "resource_id": "..."}
        ]
      }
    }
  ],
  "changes": [
    /* incluindo o(s) REMOVE row(s) */
  ]
}
```

**Validação:**

- [ ] `flags[]` contém entry com `code = "structural_change"`
- [ ] `severity = "high"`
- [ ] `message_pt` começa com count e menciona "REMOVE" + tipos estruturais
- [ ] `evidence.removed_resources` é array não-vazio
- [ ] Cada entry em `removed_resources` tem `resource_type` ∈ {CAMPAIGN, AD_GROUP, CONVERSION_ACTION} e `resource_id` numérico
- [ ] `changes[]` contém pelo menos 1 row com `operation = "REMOVE"` e `resource_type` matching

**Fallback se nenhuma conta acessível tem REMOVE estrutural recente:**
- Marcar T5 **DEFERRED** — env limitation, não bug
- Anotar: "T5 DEFERRED — nenhuma conta acessível com REMOVE em CAMPAIGN/AD_GROUP/CONVERSION_ACTION nos últimos 7 dias. Pattern F41/F45 (env limitation = doc only, não bug). Coverage via unit test `test_flag_structural_change_positive` + integration `test_structural_change_flag_emitted`."

**Result:** ⬜ pending *(possível DEFERRED — env limitation)*

---

## Test T6 — Empty drift em conta clean (ML Antiguidades)

**Setup:** Conta clean — sem changes mensuráveis na janela. Valida que `detect_drift` retorna `summary` zerado + `flags=[]` + `changes=[]` gracefully (sem erros).

**Tool call:**

```
detect_drift(
  customer_id="7455088726",
  date_range="LAST_2_DAYS"
)
```

**Expected:**

```json
{
  "customer_id": "7455088726",
  "period": {"from": "2026-05-19", "to": "2026-05-21", "days": 3},
  "responsible_user_emails": [],
  "summary": {
    "total_drift_changes": 0,
    "total_changes_in_window": 0,
    "by_user": {},
    "by_resource_type": {},
    "by_operation": {}
  },
  "flags": [],
  "changes": [],
  "truncated": false,
  "returned_count": 0
}
```

**Validação:**

- [ ] `summary.total_drift_changes` = 0
- [ ] `summary.total_changes_in_window` = 0
- [ ] `summary.by_user` = `{}` (dict vazio)
- [ ] `summary.by_resource_type` = `{}`
- [ ] `summary.by_operation` = `{}`
- [ ] `flags` = `[]`
- [ ] `changes` = `[]`
- [ ] `truncated` = `false`
- [ ] `returned_count` = 0
- [ ] Sem erro / exception (empty é comportamento correto)

**Fallback se ML Antiguidades não está tão clean (algum change na janela):**
- Aceitar `total_drift_changes > 0` como válido (apenas validar shape)
- Anotar valores reais
- OU expandir `responsible_user_emails` pra incluir gestores ML → resultaria em drift=0 e PASS limpo

**Fallback se ML Antiguidades sem dados mensuráveis no período:**
- Marcar PASS (empty é o expected)
- Anotar: "T6 PASS — ML Antiguidades clean no período. Pattern F41/F45 esperado."

OU se ML totalmente inacessível: **DEFERRED** — env limitation, coverage via unit `test_empty_responsible_list_all_drift` com rows vazios.

**Result:** ⬜ pending

---

## Per-value empirical probe (Sprint 3b.19A.1 convention)

**N/A** — `detect_drift` não tem enum whitelist em schema com valores SDK:

- `date_range` enum (`LAST_2_DAYS`, `TODAY`, `YESTERDAY`, `LAST_7_DAYS`, `LAST_14_DAYS`, `LAST_30_DAYS`) é Google-side preset, não SDK whitelist — valores padrão testados pelo `resolve_date_window` helper (stable em 16+ tools). `LAST_2_DAYS` é preset novo desta sprint — validado em T1 (default) e T4 (explícito via LAST_7_DAYS).
- `responsible_user_emails` é input livre do gestor — sem enum (apenas validação `format: email` no schema).
- `flags[].code` no output é constant string-set (auto_apply_detected, multiple_users_detected, structural_change) — pure module convention, sem SDK lookup.

Convention 3b.19A.1 não aplica. Schema regression coberta por `test_every_tool_has_valid_schema` + `test_no_composition_keywords_in_any_schema`.

---

## V4 invariants validation

**N/A** — Tool é read-only puro (sem mutations):

| Invariant | Aplicável | How smoke verifies |
|---|---|---|
| country_code = BR | N/A | Tool não toca geo data |
| language_code = pt-BR | ✅ Parcial | `flags[].message_pt` em PT-BR (validado T1/T2/T5) |
| currency_code = BRL | N/A | Tool não retorna metrics monetárias (apenas count/structure) |
| timezone = -03:00 | N/A | `change_date_time` herdado de `get_change_history` (string raw) |
| LGPD consent | N/A | Read-only, sem envio de PII; `user_email` já era exposto via `get_change_history` |

---

## Cleanup post-smoke

Não há cleanup necessário:
- `detect_drift` é read-only puro (zero mutations)
- Wrapper sobre `get_change_history` (1 API call ao Google Ads por chamada)
- Audit_log entries ficam permanentes (rastreio histórico, `audit_this_call=True` herdado)
- Rate_counter incrementa normalmente (1 GAQL call por chamada smoke T1-T6 = 6 calls total)

---

## Notas pra Wellington pós-smoke

1. **B1 lag warning (3b.32 lesson):** `change_event` API do Google tem lag até HORAS pra surfacing. Se Wellington testar T2/T3 IMEDIATAMENTE após Pedro Vytor fazer um change, pode não ver. Caso 20/05 já tem >24h — lag não é problema. Tool description já hardenada com nota: "drift detection é lagging indicator. Use `run_gaql FROM campaign` pra current state se timing crítico."
2. **Se T5 DEFERRED por nenhuma conta com REMOVE estrutural recente:** unit test `test_flag_structural_change_positive` + integration `test_structural_change_flag_emitted` já garantem cobertura. DEFERRED é env limitation (pattern F41/F45), não bug.
3. **Se T6 ML Antiguidades inacessível:** unit test `test_empty_responsible_list_all_drift` + boundary tests cobrem empty path. DEFERRED N/A.
4. **Uso real após smoke:** workflow co-management diário — Wellington roda `detect_drift(customer_id=<conta>, responsible_user_emails=[<seu_email>])` D+1 após batch estrutural. Em ~30s, recebe lista filtrada de mudanças NÃO-suas. Substitui ~10min de inspeção manual `get_change_history`.
5. **Sprint 3b.34+ candidates:** W3 audit_goal_attribution (ICE 360), audit_zombie_keywords (ICE 315), audit_orphan_smart_actions (ICE 288), ou A4 OPEN Customer Match exclusion investigation. Decisão Wellington baseada em dogfood real.
6. **Tool count:** atualizar CLAUDE.md sprint counter (3b.32 → 3b.33) e sprint-history.md após signoff.

---
