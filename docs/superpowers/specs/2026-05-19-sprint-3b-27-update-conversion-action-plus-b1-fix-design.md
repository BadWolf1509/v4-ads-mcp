# Sprint 3b.27 — `update_conversion_action` + B1/F43 pre-flight fix (design spec)

**Date:** 2026-05-19
**Operator:** wellinton.ribeiro@v4company.com
**Sprint shape:** combo (nova tool + fix em tool existente) num único sprint
**Deadline driver:** Opção C SIMPLIFICADA MO 23/05 (sex) — gestor precisa rebaixar Store visits action pra non-biddable
**Source da priorização:** [dogfood-2026-05-19-mestre-da-obra-jp-cleanup-massivo.md](../../operacao/dogfood-2026-05-19-mestre-da-obra-jp-cleanup-massivo.md) §priorização ICE

---

## Background

### Por que esse combo

Dogfood D+7 em conta MO-JP 2026-05-19 produziu 2 pendências top-ICE com **sinergia técnica** (mesmo padrão pre-flight async via GAQL):

| # | ICE | Origem | Conteúdo |
|---|---|---|---|
| 1 | 630 (HIGH) | dogfood §B1 | `update_keyword_status` aceita batch silenciosamente quando inclui criterion com `negative=true`; `apply_change` falha com erro Google genérico "Negative ad group criteria are not updateable" que não identifica IDs problematicos. Catalogado como [F43](../../operacao/findings-catalog.md) na sessão pós-dogfood. |
| 2 | 540 (#2) | dogfood §gaps + UX-B | Gestor precisa rebaixar Store visits action pra non-biddable sem afetar outras actions da categoria; sem tool MCP hoje. Workaround atual = Google Ads UI. Prazo MO 23/05. |

### Insight crítico durante brainstorming 2026-05-19

A pendência #2 do dogfood mencionou candidato `update_customer_conversion_goal` (categoria-wide). **Pesquisa via context7 google-ads SDK v24** revelou que o caminho mais cirúrgico é `ConversionAction.primary_for_goal=false`:

> "If a conversion action's primary_for_goal bit is false, the conversion action is non-biddable for all campaigns regardless of their customer conversion goal or campaign conversion goal."
> — google-ads-python v24 `conversion_action.py:primary_for_goal`

Isso permite **rebaixar uma action específica** (não a categoria inteira). Mais simétrico ao `create_conversion_action` que já existe. Tool escolhida pro V0: **`update_conversion_action`** com 3 fields mutáveis (`name`, `primary_for_goal`, `include_in_conversions_metric`).

`update_customer_conversion_goal` vira candidate futuro (Sprint 3b.27.x ou +) se demanda real surgir pra desligar categoria inteira de uma vez.

---

## Goal

Entregar até **22/05 (qui)** em produção:

1. Nova tool MCP `update_conversion_action` (3 fields mutáveis minimal)
2. Fix B1/F43 em `update_keyword_status` (pre-flight async que separa positive vs negative criterion_ids)

Pra que em **23/05 (sex) Wellington execute a Opção C SIMPLIFICADA MO** rebaixando Store visits action sem precisar UI Google.

## Non-goals

- Não entregar `update_customer_conversion_goal` (candidate futuro, fora do escopo V0)
- Não adicionar fields além dos 3 minimal em `update_conversion_action` (value_settings, counting_type, lookback windows, attribution_model — candidates futuros)
- Não adicionar `status: "ENABLED" | "PAUSED"` em `update_conversion_action` V0 (foi avaliado e descartado pra minimizar surface)
- Não adicionar tool de "desnegativar keyword" (workaround = Google Ads UI, mencionado na mensagem de error do fix B1)
- Não cobrir B2/B3/B4/B5 do dogfood (LOW severity, sprint posterior)

---

## Architecture

### Padrão técnico unificado

Tanto a tool nova quanto o fix usam o mesmo pattern de **pre-flight async via GAQL** já consolidado em `update_keyword_bid` (Sprint 3b.8), `apply_audience` (Sprint 3b.5), e `import_offline_conversions` (Sprint 3b.26):

```
tool entry (args)
  ↓
  [Layer 1] schema validation (jsonschema) — minItems, regex, enum, max
  ↓
  [Layer 2] _validate_payload_shape (síncrono Python — duplicados, contradições)
  ↓
  [Layer 3] pre-flight async (helper em _common.py — 1 GAQL pra validar contra estado Google)
  ↓
  classify() risk → AUTO (auto_apply) ou CONFIRM (dry_run + token)
  ↓
  run_mutation() ou create_pending() + apply_change()
```

### Módulos novos vs modificados

| Arquivo | Mudança | Linhas estimadas |
|---|---|---|
| `src/mcp/tools/update_conversion_action.py` | **NOVO** — tool MCP | ~180 |
| `src/google_ads/mutations.py` | **MODIFICADO** — adicionar branch `update_conversion_action` no router + builder dedicado | ~50 |
| `src/google_ads/queries/_common.py` | **MODIFICADO** — adicionar `validate_conversion_actions_exist` + `validate_keyword_criterion_types` | ~80 |
| `src/mcp/tools/update_keyword_status.py` | **MODIFICADO** — chamar `validate_keyword_criterion_types` antes do classify | ~25 |
| `src/mcp/tools/apply_change.py` | **MODIFICADO** — adicionar branch `update_conversion_action` no router | ~3 |
| `src/governance/blast_radius.py` | **MODIFICADO** — adicionar entry `update_conversion_action` em `classify()` | ~10 |
| `tests/unit/test_update_conversion_action.py` | **NOVO** — builder + schema (ProtoFieldCapture) | ~250 |
| `tests/unit/test_update_keyword_status_preflight.py` | **NOVO** — pre-flight B1 fix (unit) | ~120 |
| `tests/integration/test_keyword_mutations.py` | **MODIFICADO** — adicionar 3 cases pro B1 fix com mock no namespace da tool | ~80 |
| `docs/operacao/findings-catalog.md` | **MODIFICADO** — F43 row "open" → "Fixed Sprint 3b.27"; summary Open 2→1 | ~5 |
| `CLAUDE.md` | **MODIFICADO** — row Sprint 3b.27 "shipped" + count 49→50 | ~3 |
| `docs/operacao/phase-3b-27-bootstrap.md` | **NOVO** — runbook smoke (gerado via subagent `smoke-runbook-generator`) | ~280 |

**Total:** ~1090 linhas (50% código, 50% testes + docs). 6 modificados, 4 novos.

### Princípio de design

**DRY entre os 2 pre-flights novos.** Ambos seguem template idêntico ao `validate_conversion_action_for_upload` (Sprint 3b.26) — 1 GAQL + row_formatter + retorno `str | None` ou `dict | None`. Helpers vivem em `_common.py`; tools importam.

---

## Component A — `update_conversion_action`

### Schema (`_SCHEMA`)

```python
{
  "type": "object",
  "properties": {
    "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
    "updates": {
      "type": "array",
      "minItems": 1,
      "maxItems": 50,
      "items": {
        "type": "object",
        "properties": {
          "conversion_action_id": {"type": "string", "pattern": "^[0-9]+$"},
          "name": {"type": "string", "minLength": 1, "maxLength": 100},
          "primary_for_goal": {"type": "boolean"},
          "include_in_conversions_metric": {"type": "boolean"}
        },
        "required": ["conversion_action_id"],
        "additionalProperties": False
      }
    }
  },
  "required": ["customer_id", "updates"],
  "additionalProperties": False
}
```

**Características:**
- `maxItems: 50` — proteção contra payload bombing (família F2/F22 do catalog)
- 3 fields opcionais — usuário define quais quer atualizar; Layer 2 garante ≥1 mutável
- Sem composition keywords (oneOf/allOf/anyOf) — convention pós-3b.19B.1

### Layer 2 — `_validate_payload_shape` (helper privado)

Função privada no tool file (não em `_common.py` — específica desta tool):

- **Reject 1:** item do `updates[]` que não tem **nenhum** field mutável (só `conversion_action_id`). Mensagem PT-BR:
  ```
  "update item N (conversion_action_id=X) só tem conversion_action_id sem nenhum field mutável (name, primary_for_goal, include_in_conversions_metric). Inclua ao menos 1 field pra atualizar."
  ```
- **Reject 2:** `conversion_action_id` duplicado no batch. Mensagem:
  ```
  "conversion_action_ids duplicados no batch: [123, 456]. Cada ID deve aparecer no máximo 1 vez."
  ```

### Layer 3 — `validate_conversion_actions_exist` (novo helper em `_common.py`)

```python
async def validate_conversion_actions_exist(
    *,
    manager_id: UUID,
    session_id: UUID,
    customer_id: str,
    conversion_action_ids: list[str],
) -> dict[str, Any] | None:
    """GAQL pre-flight: each ID exists + status != REMOVED.

    Returns:
        None se todos válidos
        dict com {error, missing_ids} ou {error, removed_ids} se algum problema

    Sprint 3b.27 — pre-flight for update_conversion_action tool.
    """
    ids_clause = ", ".join(int(cid) for cid in conversion_action_ids)
    query = (
        "SELECT conversion_action.id, conversion_action.status "
        "FROM conversion_action "
        f"WHERE conversion_action.id IN ({ids_clause})"
    )
    # ... formatter + run_report + check missing → removed → return
```

**Curto-circuito:** se algum missing, retorna apenas `missing_ids` (não verifica REMOVED). Se todos existem mas algum REMOVED, retorna `removed_ids`.

### Builder em `mutations.py`

```python
def _build_update_conversion_action_operations(
    client: Any,
    customer_id: str,
    updates: list[dict[str, Any]],
) -> list[Any]:
    """Build mutate operations for update_conversion_action.

    Field mask is constructed dynamically based on which fields are present
    in each update item. Resource name follows
    customers/{customer_id}/conversionActions/{action_id}.
    """
    ops = []
    for update in updates:
        op = client.get_type("ConversionActionOperation")
        ca = op.update
        ca.resource_name = (
            f"customers/{customer_id}/conversionActions/"
            f"{update['conversion_action_id']}"
        )
        fields_to_mask = []
        if "name" in update:
            ca.name = update["name"]
            fields_to_mask.append("name")
        if "primary_for_goal" in update:
            ca.primary_for_goal = update["primary_for_goal"]
            fields_to_mask.append("primary_for_goal")
        if "include_in_conversions_metric" in update:
            ca.include_in_conversions_metric = update["include_in_conversions_metric"]
            fields_to_mask.append("include_in_conversions_metric")
        op.update_mask.paths.extend(fields_to_mask)
        ops.append(op)
    return ops
```

**Critical:** field mask **dinâmico por item** — cada update tem mask próprio, não compartilhado. Sem isso, Google update overrideia fields não-presentes com default value (= bug silencioso).

### Risk classification

Nova entry em `src/governance/blast_radius.py::classify()`:

```python
elif operation == "update_conversion_action":
    updates = params["updates"]
    # AUTO se: batch size == 1 AND nenhum field é primary_for_goal=False ou include_in_conversions_metric=False
    has_unsafe_disable = any(
        u.get("primary_for_goal") is False or u.get("include_in_conversions_metric") is False
        for u in updates
    )
    if len(updates) == 1 and not has_unsafe_disable:
        return RiskLevel.AUTO, "1 ConversionAction sem desligar signals"
    return RiskLevel.CONFIRM, f"{len(updates)} ConversionAction(s); requer preview"
```

**Justificativa:** setar `primary_for_goal=False` ou `include_in_conversions_metric=False` desliga signal do Smart Bidding — efeito alto. CONFIRM (preview + token).

### V4 invariants

**N/A** — `ConversionAction` resource não tem campos `country_code`/`language_code`/`currency_code`. Os 3 fields mutáveis V0 são neutros geográfica/linguisticamente.

### Return shape

**Apply success:**
```json
{
  "status": "applied",
  "operation": "update_conversion_action",
  "customer_id": "1163862076",
  "applied_count": 3,
  "google_request_id": "<google-id>",
  "changes": [
    {"conversion_action_id": "123", "fields_updated": ["primary_for_goal"]},
    {"conversion_action_id": "456", "fields_updated": ["name", "include_in_conversions_metric"]}
  ]
}
```

**Dry_run:**
```json
{
  "status": "dry_run",
  "operation": "update_conversion_action",
  "customer_id": "1163862076",
  "blast_summary": "Atualizar 3 ConversionAction(s).",
  "changes": [...],
  "confirmation_token": "...",
  "expires_in_minutes": 10
}
```

---

## Component B — Fix B1/F43 em `update_keyword_status`

### Novo helper em `_common.py` — `validate_keyword_criterion_types`

```python
async def validate_keyword_criterion_types(
    *,
    manager_id: UUID,
    session_id: UUID,
    customer_id: str,
    keyword_pairs: list[tuple[str, str]],  # [(ad_group_id, criterion_id), ...]
) -> dict[str, Any] | None:
    """GAQL pre-flight: each (ad_group_id, criterion_id) exists + is positive.

    Returns:
        None se todos positive válidos
        dict com {error, negative_ids_blocked, positive_ids_safe, missing_ids}
        se há mistura ou problemas

    Sprint 3b.27 — fix B1/F43 (Silent-acceptance design gap family).
    """
    crit_ids = sorted({c for _, c in keyword_pairs})
    ids_clause = ", ".join(int(c) for c in crit_ids)
    query = (
        "SELECT ad_group.id, ad_group_criterion.criterion_id, "
        "ad_group_criterion.negative, ad_group_criterion.type "
        "FROM ad_group_criterion "
        f"WHERE ad_group_criterion.criterion_id IN ({ids_clause})"
    )
    # ... formatter + run_report + split logic
```

### Lógica de retorno (3 caminhos)

1. **Missing IDs → curto-circuita primeiro:**
   ```python
   if missing:
       return {
           "error": f"criterion_ids não encontrados em customer_id={cid}: {[m['criterion_id'] for m in missing]}. ...",
           "missing_ids": missing,
       }
   ```

2. **Mistura (ou 100% negative) → hard reject com listas:**
   ```python
   if negative_blocked:
       return {
           "error": f"{len(neg)}/{len(pairs)} criterion_ids são ad_group_criterion com negative=true. ...",
           "negative_ids_blocked": negative_blocked,
           "positive_ids_safe": positive_safe,
           "to_retry_with": f"update_keyword_status(customer_id='{cid}', keywords=positive_ids_safe, new_status=<your_status>)",
       }
   ```

3. **All positive → None (segue fluxo normal):**
   ```python
   return None
   ```

### Modificação em `update_keyword_status.py`

Adicionar no início da função, ANTES do `classify()`:

```python
from src.google_ads.queries._common import validate_keyword_criterion_types

async def update_keyword_status(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    keywords = args["keywords"]
    new_status = args["new_status"]

    # Sprint 3b.27 fix B1/F43: pre-flight async — Google API rejects negative
    # ad_group_criterion updates with generic error that doesn't identify
    # which IDs were the problem. Splits batch into positive vs negative.
    keyword_pairs = [(k["ad_group_id"], k["criterion_id"]) for k in keywords]
    preflight_error = await validate_keyword_criterion_types(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        keyword_pairs=keyword_pairs,
    )
    if preflight_error:
        return {
            "status": "error",
            "operation": "update_keyword_status",
            "customer_id": customer_id,
            **preflight_error,
        }

    target_count = len(keywords)
    # ... resto inalterado
```

### Mensagens PT-BR específicas

**Missing:**
```
"criterion_ids não encontrados em customer_id=Y: [12345, 67890]. Verifique se IDs estão corretos (ad_group_id + criterion_id) e se o gestor ainda tem acesso à conta."
```

**Negative (B1/F43 core):**
```
"5/22 criterion_ids são ad_group_criterion com negative=true. Google API rejeita updates em negative criteria (state machine separada). Re-chame update_keyword_status apenas com os criterion_ids POSITIVE listados em positive_ids_safe. Pra desnegativar uma keyword, use Google Ads UI (sem tool MCP dedicada hoje)."
```

### Defesa em profundidade

Se por race condition o preflight passar mas o `apply_change` ainda receber erro Google "Negative ad group criteria are not updateable", o error path existente em `run_mutation` captura. F43 fica fechado mas safety net preservada.

---

## Data flow

### Flow A — `update_conversion_action` happy path (CONFIRM)

```
Claude → update_conversion_action(customer_id, updates=[...])
   ↓
[update_conversion_action.py]
   ├── Layer 1 (jsonschema, automático via _registry)
   ├── Layer 2 (_validate_payload_shape sync)
   ├── Layer 3 (validate_conversion_actions_exist → GAQL)
   │     └── audit_log entry (preflight)
   ├── classify() → CONFIRM
   └── create_pending() → dry_run_tokens
   ↓
{status: "dry_run", confirmation_token: "...", changes: [...]}

Gestor revisa preview, decide aplicar:

Claude → apply_change(confirmation_token="...")
   ↓
[apply_change.py]
   ├── token lookup (TTL 10min, single-use)
   └── route → operation_type="update_conversion_action"
   ↓
[mutations.py → run_mutation]
   ├── _build_update_conversion_action_operations (proto-plus + field_mask)
   ├── rate_counter +N (N ops)
   └── GoogleAdsService.mutate(...)
   ↓
[Google Ads API] → MutateGoogleAdsResponse
   └── audit_log entry (mutate, google_request_id)
   ↓
{status: "applied", applied_count: N, google_request_id: "..."}
```

### Flow B — `update_keyword_status` happy path (com novo pre-flight)

```
Claude → update_keyword_status(customer_id, keywords=[...], new_status="PAUSED")
   ↓
[update_keyword_status.py]
   ├── Layer 1 (existente)
   ├── Layer 3 NOVO (validate_keyword_criterion_types → GAQL)
   │     └── audit_log entry (preflight)
   │   - Todos positive → segue
   │   - Algum negative/missing → Flow D (abort)
   ├── classify() (existente — não muda)
   └── run_mutation OU create_pending
```

### Flow C — `update_conversion_action` error path (pre-flight reject)

```
[update_conversion_action.py]
   ├── Layer 3: validate_conversion_actions_exist
   │     └── 2 IDs encontrados, esperava 3 → missing_ids=[12345]
   ↓
{status: "error", error: "...", missing_ids: ["12345"]}

NOTAS:
- rate_counter NÃO incrementa para mutate (operação abortada pré-Google)
- audit_log da GAQL preflight FICA (debug)
```

### Flow D — `update_keyword_status` error path (B1/F43 trigger)

```
[update_keyword_status.py]
   ├── Layer 3: validate_keyword_criterion_types
   │     └── 22 rows retornados, 5 com negative=true → split
   ↓
{
  status: "error",
  operation: "update_keyword_status",
  customer_id: "7862230676",
  error: "5/22 criterion_ids são negative...",
  negative_ids_blocked: [...×5],
  positive_ids_safe: [...×17],
  to_retry_with: "update_keyword_status(..., keywords=positive_ids_safe, ...)"
}

Claude → oferece ao gestor: "5 negativas (lista). Prosseguir com 17 positives?"
Gestor aprova → re-call com positive_ids_safe → flow normal.
```

### Integrações com infra existente

| Componente | Como interage | Comportamento novo? |
|---|---|---|
| `audit_log` table | Cada GAQL preflight + cada mutate gera entry. Padrão das tools 3b.20+ | Não |
| `rate_counters` | Incrementa por op (GAQL = 1 op, mutate batch = N ops) | Não |
| `dry_run_tokens` (CONFIRM) | TTL 10min, single-use, store payload+blast_summary | Não |
| `_registry.py` (auto-discovery) | Pega `update_conversion_action.py` via pkgutil.iter_modules pós-3b.14.1 | Não (out-of-box) |
| `apply_change.py` router | +1 branch `operation_type == "update_conversion_action"` | Sim mas trivial (~3 linhas) |

---

## Error handling

### Mapa de erros por camada

| Camada | Trigger | Failure mode | Response shape | Rate counter? | Audit log? |
|---|---|---|---|---|---|
| **Layer 1** schema | `additionalProperties=False`, regex, min/max | `validation_error` antes do tool executar | MCP transport error | ❌ | ❌ |
| **Layer 2** `_validate_payload_shape` (`update_conversion_action`) | Item sem mutable; duplicate id | `{status: "error", error: "..."}` | ❌ | ❌ |
| **Layer 3** `validate_conversion_actions_exist` | ID não existe; ID REMOVED | `{status: "error", missing_ids/removed_ids: [...]}` | ✅ +1 (GAQL) | ✅ preflight entry |
| **Layer 3** `validate_keyword_criterion_types` | criterion_id missing; mistura negative+positive | `{status: "error", negative_ids_blocked: [...], positive_ids_safe: [...]}` | ✅ +1 (GAQL) | ✅ preflight entry |
| **Mutate Google API** | Race condition / cache lag pós-preflight | `{status: "error_google_api", ...}` (path existente em `run_mutation`) | ✅ +N | ✅ entry |
| **Token expired** (apply_change) | Token > 10min | `{status: "error_token_expired"}` | ❌ | ❌ |
| **Rate limit** Basic Access | >15k ops/dia (improvável dado uso atual 0.07%) | `{status: "error_rate_limit"}` | ❌ | ✅ rate_limit_hit |

### Strategy de fallback em case de race

Se preflight passar mas `run_mutation` falhar com erro Google sobre negative ad_group_criterion (race condition), captura via `partial_failure` path existente em `run_mutation`. Cloud Logging tem traceback completo. **Esse caso vira F-finding novo** se ocorrer em produção (provavelmente raro).

### Verificações no smoke (recuperação F43)

T11 smoke valida que após o reject hard:
- ✅ Response `status: "error"` com listas split
- ✅ `audit_log` tem entry de preflight, ZERO de mutate
- ✅ `rate_counters` incrementa só +1 (GAQL), não +N (mutate)

---

## Testing strategy

### Unit tests — `tests/unit/test_update_conversion_action.py` (NOVO)

**Pattern obrigatório:** `make_capture_client` de `tests/unit/fixtures/proto_capture.py`. NUNCA MagicMock (F16/F42 lessons).

Test cases planejados (~10):

| Test | Valida |
|---|---|
| `test_schema_has_no_composition_keywords` | Regression guard (F18/F25). Sem oneOf/allOf/anyOf |
| `test_schema_explicit_types` | F1 lesson — todo property tem `type` |
| `test_validate_payload_shape_missing_mutable_field` | Layer 2 reject 1 |
| `test_validate_payload_shape_duplicate_conversion_action_id` | Layer 2 reject 2 |
| `test_build_op_sets_only_name_when_only_name_provided` | Builder field_mask só `name` |
| `test_build_op_sets_primary_for_goal_field` | Critical: assignment em `update.primary_for_goal` — ProtoFieldCapture catches mismatch |
| `test_build_op_sets_include_in_conversions_metric` | UX-B do dogfood — campo crítico |
| `test_build_op_constructs_correct_resource_name` | `customers/{cid}/conversionActions/{caid}` (A5 lesson) |
| `test_build_ops_handles_batch_of_3_different_field_combos` | Cada op tem field_mask próprio |
| `test_risk_classify_single_rename_is_auto_others_confirm` | Rename de 1 = AUTO; qualquer False = CONFIRM |

### Unit tests — `tests/unit/test_update_keyword_status_preflight.py` (NOVO)

Test cases planejados (~7):

| Test | Valida |
|---|---|
| `test_validate_keyword_criterion_types_all_positive_returns_none` | Happy path |
| `test_validate_keyword_criterion_types_all_negative_returns_blocked_list` | 100% negative edge |
| `test_validate_keyword_criterion_types_mixed_returns_split_response` | F43 core — split |
| `test_validate_keyword_criterion_types_missing_id_returns_missing_dict` | Missing curto-circuita |
| `test_validate_keyword_criterion_types_pt_br_messages` | Mensagens PT-BR conforme spec |
| `test_validate_keyword_criterion_types_to_retry_with_includes_positive_ids` | Mensagem `to_retry_with` lista positive_ids_safe |
| `test_validate_keyword_criterion_types_empty_input_returns_none` | Empty input no-op |

**Mock approach:** mockar `run_report` no namespace de `_common.py` (helper vive lá).

### Integration tests — `tests/integration/test_keyword_mutations.py` (MODIFICADO)

Adiciona ~3 cases pro F43 fix:

| Test | Valida |
|---|---|
| `test_update_keyword_status_preflight_rejects_negative` | Pre-flight mockado retorna mistura → tool retorna error sem chamar mutate |
| `test_update_keyword_status_preflight_passes_only_positive` | Pre-flight retorna None → mutate normal (regression pré-F43 preservado) |
| `test_update_keyword_status_preflight_missing_id_short_circuits` | Pre-flight retorna missing → response sem `negative_ids_blocked` |

**Mock pattern CRÍTICO (convention pós-3b.5/3b.8):**

```python
with patch(
    "src.mcp.tools.update_keyword_status.validate_keyword_criterion_types",
    AsyncMock(return_value=None),
):
    ...
```

NÃO `patch("src.google_ads.queries._common.validate_keyword_criterion_types", ...)`.

### Cross-cutting tests (existentes)

| Test | Garante |
|---|---|
| `test_no_composition_keywords_in_any_schema` (cross-cutting) | Walk recursivo — `update_conversion_action` automaticamente coberto após auto-discovery |
| `test_status_tools_schema_restrict` | `update_keyword_status.new_status` continua `[ENABLED, PAUSED]` (regression F11) |
| `test_run_mutation_resource_names` | Possivelmente +1 case pra `update_conversion_action` retornar resource_names (F13 convention) |

### Smoke runbook — `docs/operacao/phase-3b-27-bootstrap.md` (NOVO)

Gerado via subagent `smoke-runbook-generator`. Conteúdo planejado (~12 tests):

**Pre-flight setup:**
- T0a: GAQL pré-smoke — listar 3-5 ConversionActions existentes em Nutry
- T0b: GAQL pré-smoke — listar ad_group_criterion misturados positive + negative em Nutry

**`update_conversion_action` tests:**
- T1: dry_run happy path — `name` em 1 action (preview + token)
- T2: apply T1 → verify GAQL
- T3: pre-flight reject — conversion_action_id não existe
- T4: Layer 2 reject — item sem field mutável
- T5: Layer 2 reject — duplicate conversion_action_id
- T6: batch dry_run — 3 actions com fields diferentes
- T7: apply T6 + verify GAQL — Store visits action vira non-biddable (caso MO 23/05)
- T8: schema regression — `maxItems` 51 rejected

**`update_keyword_status` F43 fix tests:**
- T9: regression — só positives (5 PAUSED) funciona como antes
- T10: F43 trigger — 100% negativos → hard reject
- T11: F43 trigger — mistura 3 positives + 2 negatives → split lists
- T12: missing IDs — criterion_id inexistente → `missing_ids` curto-circuita

**Expected:** 12/12 PASS pra signoff. F-findings esperados: 0-2 (média histórica).

### Defense-in-depth: `mcp-tool-quality-reviewer` antes do push

```
Agent(subagent_type: mcp-tool-quality-reviewer, prompt: "Audite src/mcp/tools/update_conversion_action.py + src/mcp/tools/update_keyword_status.py (pos-fix B1/F43). Sprint 3b.27, combo nova tool + B1 fix. Use F43 como referência.")
```

Reviewer flag-rá especialmente Group 2.1 (ProtoFieldCapture vs MagicMock — F42 lesson).

---

## Open questions / risks

### Risk 1 — `primary_for_goal` proto field optional flag

Doc context7 mostra:
> "`primary_for_goal: bool = proto.Field(proto.BOOL, number=31, optional=True)`"

E:
> "By default, primary_for_goal will be true if not set. In V9, primary_for_goal can only be set to false after creation through an 'update' operation because it's not declared as optional."

**Mitigação:** smoke T7 valida empiricamente que `primary_for_goal=False` funciona em update (independente do que SDK descriptor diga). Se rejeitar com error "field not optional", F-finding novo + investigação SDK v24/v25.

### Risk 2 — `include_in_conversions_metric` proto field type

Doc não confirma o tipo exato (suspeito `bool`). Pesquisa adicional pode ser necessária no dia da implementação via `python -c "from google.ads.googleads.v24.resources.types.conversion_action import ConversionAction; help(ConversionAction)"`.

**Mitigação:** ProtoFieldCapture nos unit tests vai falhar loud se o tipo divergir do esperado, antes do smoke.

### Risk 3 — Nutry sandbox edge cases

Se Nutry não tem 3-5 ConversionActions em estado mutável (alguma REMOVED, alguma já com primary_for_goal=false), pode ser necessário criar test entities via `create_conversion_action` antes do T1. Pre-flight setup T0a verifica.

### Risk 4 — Prazo apertado

3 dias úteis (20-22/05) com smoke + possíveis fix iterations. Buffer histórico: Sprint 3b.24 teve 5 fix iterations (3b.24.1-3b.24.5). Pra esse sprint:
- Cap implícito de 2 fix iterations (3b.27.1, 3b.27.2)
- Se chegar a 3b.27.3, considerar dividir em 2 sprints (postponer fix B1 pra 3b.27.x ou 3b.28)

---

## Refs

- **Source priorização:** [dogfood-2026-05-19-mestre-da-obra-jp-cleanup-massivo.md](../../operacao/dogfood-2026-05-19-mestre-da-obra-jp-cleanup-massivo.md) §B1, §gaps, §UX-B, §priorização ICE
- **Bug familiy A1-A5 + F43:** [findings-catalog.md](../../operacao/findings-catalog.md) §"Silent-acceptance design gap"
- **Pre-flight template canônico:** `update_keyword_bid` Sprint 3b.8 (`validate_manual_cpc_strategy` em `_common.py:222`)
- **Pre-flight template recente:** `import_offline_conversions` Sprint 3b.26 (`validate_conversion_action_for_upload` em `_common.py:689`)
- **Builder template (field mask dinâmico):** Google Ads doc — `update_audience_target_restriction.py` example
- **Test pattern obrigatório:** `tests/unit/fixtures/proto_capture.py::make_capture_client` (lessons F16/F42)
- **Mock namespace pattern:** convention pós-3b.5/3b.8 (patch no namespace da tool, não do `_common.py`)
- **Schema invariants:** CLAUDE.md "No JSON Schema composition keywords" + "Schema whitelist empirical validation"

---

## Sign-off plan

Para considerar Sprint 3b.27 shipped:

- [ ] Pre-push gate 5/5 PASS (`python scripts/check_pre_push.py`)
- [ ] Pre-push full 6/6 PASS (`python scripts/check_pre_push_full.py` — Docker required, validar mock no namespace correto)
- [ ] mcp-tool-quality-reviewer subagent PASS (FAIL aceitável só em convention-drift baixa magnitude com justificativa)
- [ ] Production deploy `/health` 200
- [ ] Smoke 12/12 PASS em Nutry (deferred OK se Nutry environment limitation tipo F41 do 3b.26)
- [ ] CLAUDE.md row Sprint 3b.27 atualizada (in_progress → shipped, count 49→50)
- [ ] findings-catalog F43 row movida open → Fixed Sprint 3b.27 + summary Open 2→1
- [ ] Wellington Wellington executa Opção C SIMPLIFICADA MO 23/05 via MCP (validação produção real)
