# Phase 3b.35 — manual smoke runbook (`audit_goal_attribution`)

**Purpose:** Validar Sprint 3b.35 — nova tool `audit_goal_attribution` (55ª MCP tool) que cruza `conversion_action` com `customer_conversion_goal` pra revelar `biddable` flag por (category, origin). Output: `origin_summary` (dict keyed por origin OU `"{category}__{origin}"` composite) com `biddable` + `warning` PT-BR (null se biddable=false) + `primary_actions[]` + `secondary_actions[]` + counts. Pure aggregator + wrapper sobre 2 GAQL queries paralelas via `asyncio.gather` (`conversion_action` + `customer_conversion_goal`). Pre-flight check antes de mexer em `update_conversion_action(primary_for_goal=...)` — resolve falsa premissa "cosmético KPI" descoberta em dogfood 2026-05-21 lição 47.

**Operator:** wellinton.ribeiro@v4company.com
**Account principal:** `7862230676` Mestre da Obra JP (production V4 — caso real lição 47, Frente 3 reavaliação)
**Account secundária:** `7455088726` ML Antiguidades (e-commerce — T3 PURCHASE category)

**Spec:** `docs/superpowers/specs/2026-05-21-sprint-3b-35-audit-goal-attribution-design.md`
**Plan:** `docs/superpowers/plans/2026-05-21-sprint-3b-35-audit-goal-attribution.md`
**Dogfood source:** `docs/operacao/dogfood-2026-05-21-mestre-da-obra-jp-drift-detection.md` (W3, ICE 360)

> **Escopo V0 confirmado:**
> - Input: `customer_id` (req, pattern `^[0-9]{10}$`) + `category` (optional, enum whitelist V4 13 valores — idêntica à `create_conversion_action` 3b.19A pós-F17/F18/F19 fixes)
> - Output: `customer_id` + `category_filter` (echo, null se sem filter) + `origin_summary` dict + `total_actions_audited` + `origins_audited[]` + `categories_audited[]`
> - Key strategy em `origin_summary`:
>   - **Com** `category` filter: key = `origin` simples (ex.: `"WEBSITE"`, `"CALL"`)
>   - **Sem** filter (panorâmico): key = `"{category}__{origin}"` composite (ex.: `"CONTACT__WEBSITE"`)
> - `warning` = string PT-BR fixa só se `biddable=true`, `null` caso contrário
> - `actions` filtradas a `status=ENABLED` (PAUSED/REMOVED não afetam Smart Bidding ativo) — hardcoded em GAQL `WHERE status='ENABLED'` + defensive filter no pure module
> - Actions sorted by `name` ASC em ambos buckets primary/secondary
> - `audit_this_call=True` em ambas calls (sensitive read, expõe goal config)
> - Tool count: 54 → **55**

## Production URL

`https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app`

## Pre-flight

- [ ] Deploy lands successfully (CI + Deploy green em commit final A1/A2/A3/A4)
- [ ] Service `/health` returns 200 (`{"status":"ok","version":"0.1.0"}`)
- [ ] Tool `audit_goal_attribution` registered (test_registered_tool_count_matches_files_on_disk 55==55 PASS)
- [ ] Pre-push gate `python scripts/check_pre_push.py` 5/5 PASS
- [ ] Schema regression `test_no_composition_keywords_in_any_schema` passa
- [ ] Unit tests `tests/unit/test_goal_attribution.py` 18/18 PASS (pure module algorithm)
- [ ] Unit tests `tests/unit/test_audit_goal_attribution_queries.py` 8/8 PASS (4 GAQL + 4 boundary parser)
- [ ] Integration tests `tests/integration/test_audit_goal_attribution.py` 3/3 PASS
- [ ] MCP Inspector / Claude client conectado à URL de produção e enxerga `audit_goal_attribution` na tool list

Production revisions: `v4-ads-mcp-XXXXX-xxx` (preencher após deploy final).

## Smoke results

Preencher conforme execução. Marcar resultado final no fim do arquivo.

| # | Test | Result | Notes |
|---|---|---|---|
| T1 | Default (sem `category` filter) panorâmico em MO-JP | ⬜ pending | |
| T2 | `category=CONTACT` em MO-JP (origin-only keys) | ⬜ pending | |
| T3 | `category=PURCHASE` em ML Antiguidades (e-commerce) | ⬜ pending | |
| T4 | Biddable=true → warning PT-BR emitido em MO-JP | ⬜ pending | |
| T5 | Biddable=false → warning=null em MO-JP (origin cosmético) | ⬜ pending | |
| T6 | Caso real lição 47 MO-JP CONTACT WEBSITE (dogfood numbers) | ⬜ pending | |

**Effective result:** N/6 PASS + Y DEFERRED

### F-findings emerged

_Preencher durante smoke. Template: `**F## (SEV)** — <symptom>. Fix: <plan>. Family: <bug class>.`_

Se zero F-findings: documentar explicitly "Zero F-findings novos. Sprint clean."

### Sign-off

- [ ] Pre-push gate 5/5 PASS
- [ ] Spec compliance + code quality reviewers APPROVED (A1, A2, A3)
- [ ] Production `/health` 200 (revisão final)
- [ ] T1, T2, T4, T5 PASS em MO-JP (cenários determinísticos com conta real)
- [ ] T3 PASS ou DEFERRED (env limitation se ML sem PURCHASE biddable=true — pattern F41/F45)
- [ ] T6 PASS ou DEFERRED (counts re-verificados se não baterem com dogfood — re-check antes de flag bug)
- [ ] CLAUDE.md sprint counter atualizado (3b.34 → 3b.35) + tool count 54 → 55
- [ ] sprint-history.md updated com entry Sprint 3b.35
- [ ] findings-catalog.md atualizado se F-findings emergiram (`/findings-add` skill)
- [ ] Tool count 55 confirmado em produção (test_registered_tool_count_matches_files_on_disk 55==55)

---

## Pre-smoke setup

### Step 1: Sanity check no MCP client

Conectar Claude/Inspector à URL de produção (`https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app`) e verificar que `audit_goal_attribution` aparece na lista de tools com parâmetros corretos:

```
# Introspect — esperar ver audit_goal_attribution com:
# - customer_id required (pattern ^[0-9]{10}$)
# - category optional (enum: 13 V4 categories — DEFAULT/PAGE_VIEW/PURCHASE/SIGNUP/
#                              SUBMIT_LEAD_FORM/BOOK_APPOINTMENT/REQUEST_QUOTE/
#                              GET_DIRECTIONS/OUTBOUND_CLICK/CONTACT/ENGAGEMENT/
#                              STORE_VISIT/STORE_SALE)
# - additionalProperties: false
```

Se `audit_goal_attribution` não aparece ou tool count ainda 54, deploy não landed — abortar smoke.

### Step 2: Reference numbers pré-smoke MO-JP

Capturar baseline raw via `run_gaql` direto pra validação cruzada em T1/T2/T4/T5/T6:

```
# Baseline conversion_action ENABLED em MO-JP
SELECT
  conversion_action.id,
  conversion_action.name,
  conversion_action.category,
  conversion_action.origin,
  conversion_action.primary_for_goal,
  conversion_action.include_in_conversions_metric,
  conversion_action.status
FROM conversion_action
WHERE conversion_action.status = 'ENABLED'
ORDER BY conversion_action.category ASC
```

Conta esperada: MO-JP `7862230676`. Anotar:
- Total de ENABLED actions (esperado: ~22 actions baseline do dogfood — referência lição 47)
- Lista de `(category, origin)` distintos
- Quais actions têm `primary_for_goal=true` (primaries) vs `false` (secondaries)
- Specifically para CONTACT WEBSITE: anotar nomes esperados (dogfood lição 47 lista 7 primary + 13 secondary)

```
# Baseline customer_conversion_goal em MO-JP
SELECT
  customer_conversion_goal.category,
  customer_conversion_goal.origin,
  customer_conversion_goal.biddable
FROM customer_conversion_goal
```

Anotar:
- Mapa completo `(category, origin) → biddable` para MO-JP
- **Crítico:** `CONTACT WEBSITE biddable=?` — dogfood diz `true` (lição 47 — afeta Smart Bidding)
- Quais origins têm `biddable=false` (cosméticos KPI — usar para T5)

### Step 3: Reference numbers pré-smoke ML Antiguidades

```
# Baseline conversion_action ENABLED em ML Antiguidades
SELECT
  conversion_action.id,
  conversion_action.name,
  conversion_action.category,
  conversion_action.origin,
  conversion_action.primary_for_goal,
  conversion_action.status
FROM conversion_action
WHERE conversion_action.status = 'ENABLED'
```

Conta `7455088726`. Anotar:
- Existem actions em `category=PURCHASE`? (ML é e-commerce — expected sim)
- Origin distribution em PURCHASE (provável WEBSITE majority)

```
# Baseline customer_conversion_goal em ML Antiguidades
SELECT
  customer_conversion_goal.category,
  customer_conversion_goal.origin,
  customer_conversion_goal.biddable
FROM customer_conversion_goal
```

Anotar:
- `PURCHASE WEBSITE biddable=?` — esperado `true` em e-commerce (gosta de bidding em compras)
- Se ML PURCHASE sem `biddable=true`: T3 DEFERRED com nota "env limitation pattern F41/F45 — ML sem PURCHASE biddable. Coverage via unit `test_biddable_true_emits_warning_pt`."

---

## Test T1 — Default (sem `category` filter) panorâmico em MO-JP

**Setup:** Use case panorâmico — gestor quer visão geral de TODAS as (category, origin) tuples da conta. Tool retorna composite keys `"{category}__{origin}"` no `origin_summary` dict.

**Tool call:**

```
audit_goal_attribution(
  customer_id="7862230676"
)
```

**Expected output (shape):**

```json
{
  "customer_id": "7862230676",
  "category_filter": null,
  "origin_summary": {
    "CONTACT__WEBSITE": {
      "category": "CONTACT",
      "origin": "WEBSITE",
      "biddable": true,
      "warning": "biddable=true: promover Secondary→Primary AFETA Smart Bidding (action vira biddable em todas campaigns que usam esta category+origin). NÃO é cosmético KPI.",
      "primary_count": N,
      "secondary_count": M,
      "primary_actions": [
        {"id": "...", "name": "...", "include_in_conversions_metric": true, "status": "ENABLED"},
        ...
      ],
      "secondary_actions": [...]
    },
    "CONTACT__CALL": {...},
    "PAGE_VIEW__WEBSITE": {...},
    /* outras (category, origin) tuples */
  },
  "total_actions_audited": N,
  "origins_audited": ["APP", "CALL", "WEBSITE"],
  "categories_audited": ["CONTACT", "PAGE_VIEW", ...]
}
```

**Validação:**

- [ ] Response tem `customer_id` = `"7862230676"`
- [ ] `category_filter` = `null` (default echo, sem filter)
- [ ] `origin_summary` é dict com pelo menos 1 key
- [ ] Pelo menos 1 key segue formato composite `"{CAT}__{ORIGIN}"` (ex.: `"CONTACT__WEBSITE"`) — confirma key strategy panorâmica
- [ ] Cada bucket tem `category` + `origin` echoed explicit (não apenas inferred pela key)
- [ ] `total_actions_audited` >= 1 (MO-JP tem ENABLED actions)
- [ ] `total_actions_audited` bate com baseline raw GAQL (mesmo após filter ENABLED-only)
- [ ] `origins_audited` é array sorted ASC sem duplicatas
- [ ] `categories_audited` é array sorted ASC sem duplicatas
- [ ] Cada `OriginSummary` bucket tem `biddable` boolean + `warning` string OR null + counts coerentes (`primary_count == len(primary_actions)`)
- [ ] Actions em `primary_actions[]` e `secondary_actions[]` ordenados por `name` ASC (validar 2+ entries quando aplicável)
- [ ] Audit_log entry criada (verificar via `/admin/audit` ou DB) — esperar 2 entries (uma per asyncio.gather call: `audit_goal_attribution_actions` + `audit_goal_attribution_goals`)
- [ ] Rate_counter +2

**Result:** ⬜ pending

---

## Test T2 — `category=CONTACT` em MO-JP (origin-only keys)

**Setup:** Filtra audit a uma única ConversionAction.category. Tool retorna keys simples (apenas origin: `"WEBSITE"`, `"CALL"`, `"APP"`) — NÃO mais composite. Use case primário pre-flight antes de mexer em primary_for_goal numa category específica.

**Tool call:**

```
audit_goal_attribution(
  customer_id="7862230676",
  category="CONTACT"
)
```

**Expected output (shape):**

```json
{
  "customer_id": "7862230676",
  "category_filter": "CONTACT",
  "origin_summary": {
    "WEBSITE": {
      "category": "CONTACT",
      "origin": "WEBSITE",
      "biddable": true,
      "warning": "biddable=true: promover Secondary→Primary AFETA Smart Bidding...",
      "primary_count": 7,
      "secondary_count": 13,
      "primary_actions": [...],
      "secondary_actions": [...]
    },
    "CALL": {
      "category": "CONTACT",
      "origin": "CALL",
      "biddable": false | true,
      "warning": null | "...",
      ...
    }
    /* outros origins de CONTACT (APP, etc) */
  },
  "total_actions_audited": N (apenas CONTACT actions),
  "origins_audited": ["WEBSITE", "CALL", ...],
  "categories_audited": ["CONTACT"]
}
```

**Validação:**

- [ ] `category_filter` = `"CONTACT"` (echo)
- [ ] `origin_summary` tem keys apenas em formato origin-simple (ex.: `"WEBSITE"`, `"CALL"`)
- [ ] NENHUMA key contém `"__"` (composite NÃO usado quando filter ativo)
- [ ] Cada bucket tem `category: "CONTACT"` echoed
- [ ] `categories_audited` = `["CONTACT"]` (apenas 1 category — filter ativo)
- [ ] `origins_audited` cobre todos os origins distintos de CONTACT
- [ ] `total_actions_audited` <= baseline T1 (subset filtrado)
- [ ] Pelo menos 1 bucket tem `biddable=true` + warning string PT-BR (CONTACT WEBSITE caso 47)
- [ ] Audit_log +2 entries
- [ ] Rate_counter +2

**Result:** ⬜ pending

---

## Test T3 — `category=PURCHASE` em ML Antiguidades (e-commerce)

**Setup:** ML Antiguidades é e-commerce — esperado ter PURCHASE actions com `biddable=true` (Smart Bidding em compras). Valida que tool funciona em conta cross e em category diferente do MO-JP.

**Tool call:**

```
audit_goal_attribution(
  customer_id="7455088726",
  category="PURCHASE"
)
```

**Expected output (shape):**

```json
{
  "customer_id": "7455088726",
  "category_filter": "PURCHASE",
  "origin_summary": {
    "WEBSITE": {
      "category": "PURCHASE",
      "origin": "WEBSITE",
      "biddable": true,
      "warning": "biddable=true: promover Secondary→Primary AFETA Smart Bidding...",
      "primary_count": N,
      "secondary_count": M,
      "primary_actions": [...],
      "secondary_actions": [...]
    }
    /* possivelmente outros origins (UPLOAD, GOOGLE_HOSTED, etc) */
  },
  "total_actions_audited": N,
  "origins_audited": ["WEBSITE", ...],
  "categories_audited": ["PURCHASE"]
}
```

**Validação:**

- [ ] `customer_id` = `"7455088726"`
- [ ] `category_filter` = `"PURCHASE"` (echo)
- [ ] `origin_summary` tem pelo menos 1 bucket com `category: "PURCHASE"`
- [ ] Pelo menos 1 bucket com `biddable=true` + warning string PT-BR (esperado em e-commerce)
- [ ] Warning text contém `"AFETA Smart Bidding"` E `"NÃO é cosmético KPI"`
- [ ] `categories_audited` = `["PURCHASE"]` (apenas filtered)
- [ ] Keys são origin-simple (`"WEBSITE"`, etc) — filter ativo
- [ ] Audit_log +2 entries

**Fallback se ML sem PURCHASE actions OU sem `biddable=true`:**
- Marcar T3 **DEFERRED** — env limitation, não bug
- Anotar: "T3 DEFERRED — ML Antiguidades sem PURCHASE actions com biddable=true em `customer_conversion_goal`. Pattern F41/F45 (env limitation = doc only, não bug). Coverage via unit `test_biddable_true_emits_warning_pt` + integration `test_warning_emitted_when_biddable_true`."

**Result:** ⬜ pending *(possível DEFERRED — env limitation)*

---

## Test T4 — Biddable=true → warning PT-BR emitido em MO-JP

**Setup:** Validar que tool emite warning string EXATA quando `biddable=true`. Caso 47 dogfood: MO-JP CONTACT WEBSITE biddable=true confirmado. Pode reuse T2 response (filter CONTACT já cobre WEBSITE biddable=true) OU rodar standalone com filter explicit.

**Tool call:**

```
audit_goal_attribution(
  customer_id="7862230676",
  category="CONTACT"
)
```

**Expected:**

```json
{
  "origin_summary": {
    "WEBSITE": {
      "biddable": true,
      "warning": "biddable=true: promover Secondary→Primary AFETA Smart Bidding (action vira biddable em todas campaigns que usam esta category+origin). NÃO é cosmético KPI."
    }
  }
}
```

**Validação:**

- [ ] Pelo menos 1 bucket em `origin_summary` tem `biddable: true`
- [ ] Esse bucket tem `warning` STRING (não null)
- [ ] Warning text contém EXATAMENTE: `"biddable=true:"`
- [ ] Warning text contém: `"AFETA Smart Bidding"`
- [ ] Warning text contém: `"NÃO é cosmético KPI"`
- [ ] Warning text é PT-BR (não inglês, não mixed)
- [ ] Warning text é IDÊNTICA em todos os buckets com `biddable=true` (mesma constante `_WARNING_BIDDABLE_TRUE`)
- [ ] Audit_log +2 entries (se rodou separado de T2)

**Result:** ⬜ pending

---

## Test T5 — Biddable=false → warning=null em MO-JP (origin cosmético)

**Setup:** Validar que tool RETORNA `warning: null` (não vazio "" nem missing key) quando `biddable=false`. Caso real: `customer_conversion_goal` em MO-JP provavelmente tem algum origin com biddable=false (cosmético KPI). Pre-smoke setup Step 2 identificou candidato.

**Tool call:**

```
audit_goal_attribution(
  customer_id="7862230676"
)
```

**Expected (em pelo menos 1 bucket):**

```json
{
  "origin_summary": {
    "<CAT>__<ORIGIN>": {
      "category": "...",
      "origin": "...",
      "biddable": false,
      "warning": null,
      "primary_count": N,
      "secondary_count": M,
      ...
    }
  }
}
```

**Validação:**

- [ ] Pelo menos 1 bucket em `origin_summary` tem `biddable: false`
- [ ] Esse bucket tem `warning: null` (Python None, JSON null — NÃO string vazio, NÃO missing key)
- [ ] Bucket ainda contém actions normais (`primary_actions[]` + `secondary_actions[]` populated if applicable) — apenas warning é null
- [ ] Audit_log +2 entries

**Fallback se TODOS os origins em MO-JP têm biddable=true:**
- Tentar rodar `audit_goal_attribution(customer_id="7455088726")` (ML pode ter origin cosmético)
- Se ML também sem biddable=false: marcar T5 **DEFERRED** — env limitation
- Anotar: "T5 DEFERRED — nenhuma conta acessível tem origin com biddable=false. Pattern F41/F45 (env limitation). Coverage via unit `test_biddable_false_warning_is_null`."

**Result:** ⬜ pending *(possível DEFERRED — env limitation)*

---

## Test T6 — Caso real lição 47 MO-JP CONTACT WEBSITE (dogfood numbers)

**Setup:** Reproduz EXATAMENTE caso da lição 47 dogfood 2026-05-21. Wellington queria promover Secondary→Primary em ConversionAction CONTACT WEBSITE assumindo "cosmético KPI". Investigation revelou biddable=true → afeta Smart Bidding. Tool deve confirmar mesmo achado com counts batendo.

**Tool call:**

```
audit_goal_attribution(
  customer_id="7862230676",
  category="CONTACT"
)
```

**Expected (focado em CONTACT WEBSITE):**

```json
{
  "origin_summary": {
    "WEBSITE": {
      "category": "CONTACT",
      "origin": "WEBSITE",
      "biddable": true,
      "warning": "biddable=true: promover Secondary→Primary AFETA Smart Bidding...",
      "primary_count": 7,
      "secondary_count": 13,
      "primary_actions": [
        /* 7 entries — incluindo "Whatsapp - JPA" entre eles */
      ],
      "secondary_actions": [
        /* 13 entries — incluindo "Alisadora - JPA" entre eles */
      ]
    }
  }
}
```

**Validação:**

- [ ] `origin_summary["WEBSITE"]` existe (filter CONTACT ativo)
- [ ] `biddable: true` confirmed (premissa fundamental da lição 47)
- [ ] `warning` string PT-BR emitida (não null)
- [ ] `primary_count == 7` (dogfood number — re-verify if mismatch)
- [ ] `secondary_count == 13` (dogfood number — re-verify if mismatch)
- [ ] `primary_actions` é array com 7 entries
- [ ] `secondary_actions` é array com 13 entries
- [ ] Todas as actions têm `status: "ENABLED"`
- [ ] Actions ordenadas por `name` ASC em ambos buckets
- [ ] Pelo menos 1 action em primary tem `include_in_conversions_metric: true` (typical Primary semantics)
- [ ] **Insight operacional:** se Wellington promovesse qualquer secondary→primary aqui, AFETARIA Smart Bidding em todas campaigns MO-JP usando CONTACT+WEBSITE goal. Tool emite warning explícito → decisão informada.

**Fallback se counts não baterem com dogfood (7/13):**
- **NÃO flag bug ainda** — re-verify via direct GAQL:
  ```
  SELECT conversion_action.id, conversion_action.name, conversion_action.primary_for_goal
  FROM conversion_action
  WHERE conversion_action.status = 'ENABLED'
    AND conversion_action.category = 'CONTACT'
    AND conversion_action.origin = 'WEBSITE'
  ORDER BY conversion_action.name ASC
  ```
- Contar manualmente primary_for_goal=true vs false
- Se counts atuais != 7/13: provavelmente mudanças desde 20/05 (gestor promoveu/criou actions). Marcar PASS com nota "counts atualizados: P primary + S secondary (era 7/13 em 20/05)."
- Se counts batem em GAQL mas tool retorna diferente: **F-FINDING** — flag bug, abrir investigation.

**Result:** ⬜ pending

---

## Per-value empirical probe (Sprint 3b.19A.1 convention)

**Probe completo do enum `category`** — Schema declara whitelist 13 valores (idêntica à `create_conversion_action` 3b.19A pós-F17/F18/F19 fixes). Como `audit_goal_attribution` é tool **read-only puro**, não cria entidades — então probe é diferente do convention típico de mutates:

- Para cada valor do enum: chamar `audit_goal_attribution(customer_id="7862230676", category=<value>)` e verificar que tool ACEITA o input (não rejeita schema-side).
- Output esperado pode ser `origin_summary={}` se a conta não tem actions naquela category — isso é **válido** (não-bug, env limitation).
- Foco do probe: garantir whitelist está ALINHADA com runtime API (Google aceita category=X em `WHERE conversion_action.category=X` ou row.category retorna X).

| # | Enum value | Expected | Result |
|---|---|---|---|
| P1 | `DEFAULT` | Accept input + return shape (origin_summary pode estar vazio) | ⬜ pending |
| P2 | `PAGE_VIEW` | Accept input + return shape | ⬜ pending |
| P3 | `PURCHASE` | Accept input + return shape | ⬜ pending |
| P4 | `SIGNUP` | Accept input + return shape | ⬜ pending |
| P5 | `SUBMIT_LEAD_FORM` | Accept input + return shape | ⬜ pending |
| P6 | `BOOK_APPOINTMENT` | Accept input + return shape | ⬜ pending |
| P7 | `REQUEST_QUOTE` | Accept input + return shape | ⬜ pending |
| P8 | `GET_DIRECTIONS` | Accept input + return shape | ⬜ pending |
| P9 | `OUTBOUND_CLICK` | Accept input + return shape | ⬜ pending |
| P10 | `CONTACT` | Accept input + return shape (coverage via T2/T4/T5/T6) | ⬜ pending |
| P11 | `ENGAGEMENT` | Accept input + return shape | ⬜ pending |
| P12 | `STORE_VISIT` | Accept input + return shape | ⬜ pending |
| P13 | `STORE_SALE` | Accept input + return shape | ⬜ pending |
| P14 | `NOT_IN_WHITELIST` (ex.: `LEAD`) | Schema reject — Input validation error | ⬜ pending |

**Validação por probe:**
- [ ] P1-P13 retornam HTTP 200 + shape válido (origin_summary pode estar vazio se conta sem actions) — confirma whitelist alinha com runtime
- [ ] P14 retorna schema validation error (HTTP 400 ou MCP equivalent)

**Critério PASS do probe completo:** todos os 13 valores aceitos input-side. Se algum rejeitado pelo runtime API (GAQL `WHERE conversion_action.category=<X>` rejeita): F-finding type "schema-runtime mismatch" + recomendação de remover do whitelist.

**Convention:** every value in tool schema whitelist MUST be empirically validated. SDK descriptors contain values runtime rejects (legacy/system-managed/type-restricted). Bug history: F17/F18/F19/F25/F27/F31/F32/F34/F36/F44 — design-gap-via-SDK-ambiguity. Para esta tool (read-only), validation = `WHERE conversion_action.category=<value>` aceita query side.

**Fallback se probe complete não viável em smoke:** rodar apenas P1+P3+P10+P13+P14 (sample edge values) + documentar que coverage completa fica em integration test futuro (`test_every_enum_value_accepted_input_side`).

---

## V4 invariants validation

| Invariant | Aplicável | Enforcement | How smoke verifies |
|---|---|---|---|
| country_code = BR | N/A | N/A — tool não toca geo data | — |
| language_code = pt-BR | ✅ Output | `_WARNING_BIDDABLE_TRUE` constant string PT-BR (`"AFETA Smart Bidding"`, `"NÃO é cosmético KPI"`) | T4 valida warning text contém substrings PT-BR exatas |
| currency_code = BRL | N/A | N/A — tool não retorna metrics monetárias (apenas counts + flags + actions metadata) | — |
| timezone = -03:00 | N/A | N/A — `conversion_action` resource não retorna timestamps em response shape V0 | — |
| LGPD consent | N/A | Read-only sem envio de PII; `conversion_action.name` já era exposto via outros tools (`get_conversion_actions`) | Audit_log captura quem acessou (Wellington) — herdado de `run_report(audit_this_call=True)` |
| Schema whitelist (3b.19A) | ✅ Input | Enum 13 V4 categories idêntica à `create_conversion_action` pós-F17/F18/F19 fixes | Per-value probe P1-P13 |
| status=ENABLED-only filter | ✅ Hardcoded | GAQL `WHERE status='ENABLED'` server-side + defensive `_INCLUDED_STATUSES = frozenset({"ENABLED"})` em pure module | T6 valida actions returned têm `status: "ENABLED"` exclusively |
| No composition keywords (3b.19B.1) | ✅ Schema | Schema sem `oneOf/allOf/anyOf` em qualquer nesting level | Regression `test_no_composition_keywords_in_any_schema` (pre-push) |

---

## Cleanup post-smoke

Não há cleanup necessário:
- `audit_goal_attribution` é read-only puro (zero mutations)
- 2 GAQL calls paralelas via `asyncio.gather` por chamada tool
- Audit_log entries ficam permanentes (rastreio histórico, `audit_this_call=True` herdado em ambas calls)
- Rate_counter incrementa normalmente: 6 testes × 2 calls = 12 GAQL calls total no smoke (T1-T6). Probe completo adiciona 13 × 2 = 26 calls se rodar 100%.

---

## Notas pra Wellington pós-smoke

1. **Uso real após smoke:** workflow pre-flight antes de `update_conversion_action(primary_for_goal=...)`. Gestor roda `audit_goal_attribution(customer_id=<conta>, category=<cat>)` ANTES de decidir promover Secondary→Primary. Se `biddable=true`: warning + decisão informada (não cosmético, vai mexer Smart Bidding). Se `biddable=false`: safe = cosmético KPI puro.
2. **Cenário composto:** Wellington pode chamar sem `category` primeiro (panorâmico — T1 shape) pra identificar TODAS as origins biddable=true. Daí refinar com filter (T2 shape) pra detalhar uma category específica antes da mutation.
3. **Se T3 DEFERRED (ML sem PURCHASE biddable):** unit test `test_biddable_true_emits_warning_pt` + integration `test_warning_emitted_when_biddable_true` garantem cobertura. DEFERRED é env limitation (pattern F41/F45), não bug.
4. **Se T5 DEFERRED (nenhuma conta com biddable=false):** unit test `test_biddable_false_warning_is_null` garante cobertura. DEFERRED similar a T3.
5. **Se T6 counts não batem (7/13 dogfood):** PROVÁVEL que gestor mexeu em primary_for_goal desde 20/05. Re-verify com GAQL direto **antes** de flag bug. Tool reporta state ATUAL, dogfood foi snapshot momentâneo.
6. **Per-value probe P14 (`LEAD` ou `OTHER`):** confirma schema enum rejeita valores fora whitelist V4. Convention crítica — Sprint 3b.19A.1 caught 14/42 findings nessa categoria.
7. **B1 lag warning N/A:** tool não usa `change_event` → imune a F46 (GAQL BETWEEN end_date midnight bug). Cross-checked nos 3 GAQL queries do tool.
8. **Sprint 3b.36+ candidates:** F46 fix (HIGH urgency — afeta `get_change_history`/`get_negative_keywords_audit`/`detect_drift`), audit_zombie_keywords (ICE 315), audit_orphan_smart_actions (ICE 288), ou A4 OPEN Customer Match exclusion investigation. Decisão Wellington baseada em dogfood real.
9. **Tool count:** atualizar CLAUDE.md sprint counter (3b.34 → 3b.35) e sprint-history.md após signoff.

---
