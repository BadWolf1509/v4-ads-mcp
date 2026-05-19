# Sprint 3b.26 — `import_offline_conversions` design

**Status:** Draft → user review pending
**Owner:** Wellington (`wellinton.ribeiro@v4company.com`)
**Date:** 2026-05-18
**Predecessor:** Sprint 3b.25 (`create_and_link_assets` — 6º create-pattern shipped)
**Successors planejados:** 3b.27 (`upload_customer_match_list` + A4 fix), 3b.28 (`remove_*` bundle)

## Goal

Terceiro mutation tool da fase de finalização (3b.24-3b.28). Permite gestor V4 importar conversões offline (WhatsApp leads, phone calls, in-person sales) pro Google Ads — fechando o loop de attribution + alimentando Smart Bidding com signals reais.

V4 use case típico: cliente clica em ad com `gclid` no URL da landing → V4 captura gclid no lead form → CRM marca lead como convertido (contrato assinado, pagamento confirmado, etc.) → gestor diz **"importa 12 leads do WhatsApp que converteram ontem"** → Claude formata + chama tool 1× com batch. Sem isso, smart bidding fica cego pra V4 lead-gen (Google só vê o click, não a conversão real).

## Context / why now

- **Wellington decisão (brainstorming 2026-05-18):** scope confirmado:
  - Conversion type: ClickConversions only (gclid match) — phone calls / Enhanced Conversions ficam v1
  - Match types: `gclid` only (gbraid/wbraid out of scope V4 lead-gen)
  - Flow: Always-CONFIRM dry_run + `partial_failure=True`
  - Pre-flight async: validate `conversion_action_id` exists + `type=UPLOAD_CLICKS`
  - Timestamp: full `YYYY-MM-DD HH:MM:SS` + V4 invariant timezone `-03:00` hardcoded
  - Batch: 1-100 conversions per call + optional `order_id` (CRM dedupe key)
  - V4 invariants: `currency_code="BRL"`, `consent.ad_user_data="GRANTED"` (LGPD V4-aligned), no custom_variables

- **Padrão consolidado:** 7º create-pattern do MCP, **MAS** primeiro tool que NÃO usa `GoogleAdsService.mutate`. ConversionUploadService.UploadClickConversions tem request/response shape diferente:
  - Request: `UploadClickConversionsRequest{customer_id, conversions, partial_failure}` (Python field `partial_failure`, NÃO `partial_failure_enabled` como Java SDK)
  - Response: `UploadClickConversionsResponse{partial_failure_error, results: [ClickConversionResult]}` — failed rows aparecem como empty messages em `results`
  - F13 cross-cutting (resource_names extraction) **NÃO se aplica** — custom response structure substitui

- **Architectural shift:** Sprint 3b.26 introduz novo dispatcher `run_conversion_upload` paralelo a `run_mutation`. `apply_change` ganha single `if`-branch baseado em `operation_type`. Foundation pra Sprint 3b.27 (`upload_customer_match_list` provavelmente vai usar mesmo padrão com `OfflineUserDataJobService`).

- **Proto field names validados via context7** (2026-05-18) usando `/websites/developers_google_google-ads_api`:
  - `ClickConversion.{conversion_action, gclid, conversion_date_time, conversion_value, currency_code, order_id}` confirmados
  - `ClickConversion.consent.ad_user_data` = `ConsentStatusEnum.GRANTED` (V4 invariant)
  - Request: `partial_failure=True` (Python proto-plus field naming)
  - Response failure detection: empty message em `response.results[i]` = row failed; details em `response.partial_failure_error.details[].value` (deserialized via `GoogleAdsFailure`)

- **Sem dependência de Standard Access** (análise empírica 2026-05-17: uso atual 0.07% Basic; conversion upload é tipicamente low-volume — V4 daily batch <50 conversões)

## Non-goals (v0)

- **CallConversions (phone leads via tracking number)** — `UPLOAD_CALLS` ConversionAction type, separate UploadCallConversions service. V4 raramente usa call tracking; v1 candidate.
- **Enhanced Conversions (hashed email/phone fallback)** — LGPD-compliant SHA-256 hashing requires same infrastructure de Sprint 3b.27 `upload_customer_match_list`. Split pra Sprint 3b.26.x após 3b.27 estabelecer hashing pattern.
- **gbraid / wbraid (iOS Web→App / Web→Web tracking)** — V4 é 100% lead-gen web landing, raramente aplica.
- **Custom variables (per-conversion segmentation tags)** — V4 ainda não usa Google Ads custom variables; CRM tags ficam no CRM.
- **ConversionAdjustmentUploadService (correct/restate uploaded conversions)** — V4 workflow não corrige conversions offline. v2 candidate.
- **`currency_code` exposed em schema (multi-country)** — hardcoded BRL per V4 invariant; refactor se demanda surgir.
- **`consent.ad_user_data` per-conversion override** — hardcoded GRANTED (V4 invariant: gestor garante consent antes do lead entrar no CRM).
- **Session attributes (`session_attributes_encoded` / `session_attributes_key_value_pairs`)** — allowlisted-only Google feature; out of scope.
- **`debug_enabled=true`** — production-grade tool, no debug logs.
- **Date-only timestamp format** (gestor passa só `YYYY-MM-DD`) — escolhemos full timestamp pra higher attribution accuracy (gestor lê do CRM).

## Tool surface

### Name
`import_offline_conversions` (49º MCP tool, count 48 → 49)

### Description (PT-BR)

```
Importa N conversões offline (1-100 por call) match-by-gclid pra Google Ads
attribuir ROAS + alimentar Smart Bidding. Always-CONFIRM. Workflow V4 lead-gen:
gestor captura gclid no URL da landing → salva no CRM → quando lead converte
(WhatsApp confirmation, contrato assinado, pagamento) → chama tool com batch
de gclids + datas + valores. V4 invariants hardcoded: currency_code=BRL,
timezone=-03:00 (São Paulo), consent.ad_user_data=GRANTED (LGPD V4-aligned).
Pre-flight valida conversion_action_id existe + tem type=UPLOAD_CLICKS.
partial_failure=True: conversões com erro individual (gclid expirado, data
inválida) são reportadas em response.failures[] mas não bloqueiam o batch.
Sprint 3b.26 introduz novo dispatcher run_conversion_upload paralelo a
run_mutation (ConversionUploadService NÃO usa GoogleAdsService.mutate).
```

### Input schema (JSONSchema, sem composition keywords)

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["customer_id", "conversion_action_id", "conversions"],
  "properties": {
    "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
    "conversion_action_id": {
      "type": "string",
      "pattern": "^[0-9]+$",
      "description": "ID numérico (NOT resource path) da ConversionAction com type=UPLOAD_CLICKS. Pre-flight valida via GAQL."
    },
    "conversions": {
      "type": "array",
      "minItems": 1,
      "maxItems": 100,
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["gclid", "conversion_date_time", "conversion_value_brl"],
        "properties": {
          "gclid": {
            "type": "string",
            "minLength": 1,
            "maxLength": 256,
            "description": "Google Click ID capturado no URL da landing (e.g., Cj0KCQjw...). String opaque — trust Google validation."
          },
          "conversion_date_time": {
            "type": "string",
            "pattern": "^\\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2}:\\d{2}$",
            "description": "Timestamp BRT (V4 invariant -03:00 anexado pelo builder). Format: YYYY-MM-DD HH:MM:SS"
          },
          "conversion_value_brl": {
            "type": "number",
            "minimum": 0.01,
            "description": "Valor BRL da conversão (V4 invariant currency_code=BRL hardcoded em builder)"
          },
          "order_id": {
            "type": "string",
            "minLength": 1,
            "maxLength": 64,
            "description": "Optional CRM lead ID pra dedupe Google-side (e.g., 'crm-12345'). Google rejeita conversion com mesmo (gclid, conversion_date_time, order_id) já uploaded."
          }
        }
      }
    }
  }
}
```

### Per-field map

| Field | Required | V4 invariant | Notes |
|---|---|---|---|
| `customer_id` | yes | — | Validate via regex 10 digits |
| `conversion_action_id` | yes | — | Numeric ID; pre-flight validates exists + type=UPLOAD_CLICKS |
| `conversions[].gclid` | yes | — | maxLength 256 chars; opaque string trust Google validation |
| `conversions[].conversion_date_time` | yes | timezone -03:00 appended | Full YYYY-MM-DD HH:MM:SS |
| `conversions[].conversion_value_brl` | yes | currency_code=BRL hardcoded | Min 0.01 |
| `conversions[].order_id` | optional | — | Dedupe key Google-side |

### Always-CONFIRM dry_run flow

1. Tool valida schema (jsonschema) + runtime `_validate_payload_shape` (5 checks)
2. Tool roda pre-flight async `validate_conversion_action_for_upload` (1 GAQL)
3. Retorna `dry_run` preview com `summary` + `confirmation_token`
4. Gestor confirma via `apply_change(confirmation_token=...)`
5. `apply_change` branches: `operation_type == "import_offline_conversions"` → `run_conversion_upload` (NOT `run_mutation`)
6. `run_conversion_upload` constructs `UploadClickConversionsRequest` direto (no `@register_builder` pattern); chama `ConversionUploadService.upload_click_conversions(...)`
7. Parse `response.results` (empty = failed) + `response.partial_failure_error` (details per row)
8. Audit log row registra `target_count` + `applied_count` + `params_summary` + custom `extra={"failed_count": N}`
9. Return `{status: "applied", applied_count, failed_count, failures: [...], google_request_id}`

### Dry-run preview structure

```json
{
  "status": "dry_run",
  "operation": "import_offline_conversions",
  "customer_id": "1163862076",
  "confirmation_token": "ABCD1234",
  "blast_summary": "Importar 12 conversões offline (sum R$ 1850.00, range 2026-05-15 09:00 → 2026-05-17 18:30) pra conversion_action_id=987654321",
  "summary": {
    "conversion_count": 12,
    "sum_value_brl": 1850.00,
    "date_range": {"earliest": "2026-05-15 09:00:00", "latest": "2026-05-17 18:30:00"},
    "gclids_distinct": 12,
    "order_ids_present": 8,
    "conversion_action_id": "987654321"
  },
  "expires_in_minutes": 10,
  "to_apply": "Chame apply_change(confirmation_token=<token>) para aplicar.",
  "confirmation_reason": "import_offline_conversions: affects ROAS attribution + Smart Bidding signals"
}
```

### Apply response structure

```json
{
  "status": "applied",
  "operation": "import_offline_conversions",
  "customer_id": "1163862076",
  "applied_count": 10,
  "failed_count": 2,
  "failures": [
    {
      "row_index": 3,
      "gclid": "Cj0KCQjw...",
      "error_code": "EXPIRED_GCLID",
      "error_message": "GCLID is older than 90 days"
    },
    {
      "row_index": 7,
      "gclid": "Cj0KCQjw...",
      "error_code": "INVALID_CONVERSION_DATE",
      "error_message": "Conversion date too far in future"
    }
  ],
  "google_request_id": "req-..."
}
```

## Architecture: `run_conversion_upload` + apply_change branching

### Module layout

Novo módulo: `src/google_ads/conversions.py` (paralelo a `mutations.py`).

**Função pública:** `run_conversion_upload(*, manager_id, session_id, customer_id, operation_type, payload, target_count, params_summary) -> dict[str, Any]`

Mirror de `run_mutation` responsabilidades:
- Rate limit reservation via `before_call()` + `record_actual()` (ops_used = `len(conversions)`)
- Build OAuth client via `build_client_for_manager()`
- Capture `google_request_id` via interceptor
- Audit log row (always — conversions are sensitive)
- Error translation via `to_friendly()`
- **Diferente:** chama `ConversionUploadService.upload_click_conversions()` ao invés de `GoogleAdsService.mutate()`

### apply_change dispatcher branching

`src/mcp/tools/apply_change.py` ganha branching:

```python
async def apply_change(args):
    # ... token validation + load pending row ...

    operation_type = pending["operation_type"]
    payload = pending["payload"]

    if operation_type == "import_offline_conversions":
        # Sprint 3b.26: upload service path (NOT GoogleAdsService.mutate)
        result = await run_conversion_upload(
            manager_id=ctx.manager_id, session_id=ctx.session_id,
            customer_id=pending["customer_id"],
            operation_type=operation_type, payload=payload,
            target_count=payload["__target_count__"],
            params_summary=payload["__params_summary__"],
        )
    else:
        # All other operations use chained mutation pattern (Sprint 3b.1-3b.25)
        result = await run_mutation(...)

    return result
```

Single `if`-branch é clean + extensível. Sprint 3b.27 candidate (`upload_customer_match_list`) provavelmente adiciona segundo branch (ou abstrai pra dispatcher registry depois).

### `run_conversion_upload` flow detail

```python
async def run_conversion_upload(*, manager_id, session_id, customer_id, operation_type,
                                  payload, target_count, params_summary) -> dict[str, Any]:
    # 1. Rate limit reserve (ops_used = len(conversions))
    rate_token = await before_call(...)

    try:
        # 2. Build OAuth client
        client = await build_client_for_manager(manager_id)

        # 3. Construct UploadClickConversionsRequest
        request = client.get_type("UploadClickConversionsRequest")
        request.customer_id = customer_id
        request.partial_failure = True  # Python proto-plus field name (NOT partial_failure_enabled)
        request.debug_enabled = False

        conversion_action_path = (
            f"customers/{customer_id}/conversionActions/{payload['conversion_action_id']}"
        )
        consent_granted = client.enums.ConsentStatusEnum.GRANTED

        for conv in payload["conversions"]:
            click_conv = client.get_type("ClickConversion")
            click_conv.conversion_action = conversion_action_path
            click_conv.gclid = conv["gclid"]
            # V4 invariant: -03:00 timezone appended
            click_conv.conversion_date_time = f"{conv['conversion_date_time']}-03:00"
            click_conv.conversion_value = float(conv["conversion_value_brl"])
            click_conv.currency_code = "BRL"  # V4 invariant
            if "order_id" in conv:
                click_conv.order_id = conv["order_id"]
            # V4 invariant: LGPD consent GRANTED (gestor confirma consent antes do CRM)
            click_conv.consent.ad_user_data = consent_granted
            request.conversions.append(click_conv)

        # 4. Execute upload
        service = client.get_service("ConversionUploadService")
        response = service.upload_click_conversions(request=request)

        # 5. Parse results (empty result = failed row)
        applied_count, failed_count, failures = _parse_upload_response(response, payload, client)

        # 6. Capture google_request_id
        request_id = get_request_id() or ""
        reset_request_id()

        # 7. Audit log
        await audit_log_row(
            manager_id=manager_id, session_id=session_id,
            customer_id=customer_id, operation=operation_type,
            action_type="apply", target_count=target_count,
            applied_count=applied_count, params_summary=params_summary,
            google_request_id=request_id,
        )

        # 8. Record rate counter
        await record_actual(rate_token, ops_used=len(payload["conversions"]))

        return {
            "status": "applied",
            "operation": operation_type,
            "customer_id": customer_id,
            "applied_count": applied_count,
            "failed_count": failed_count,
            "failures": failures,
            "google_request_id": request_id,
        }
    except GoogleAdsException as e:
        await record_actual(rate_token, ops_used=0, failed=True)
        return to_friendly(e)
```

### `_parse_upload_response` helper

```python
def _parse_upload_response(response, payload, client) -> tuple[int, int, list[dict]]:
    """Parse UploadClickConversionsResponse → applied_count + failures list.

    Python proto-plus heuristic (per Google docs): empty/falsy message em
    response.results[i] = row failed. Details em response.partial_failure_error
    .details[].value (deserialized via GoogleAdsFailure.deserialize).
    """
    input_conversions = payload["conversions"]
    applied = 0
    failures: list[dict] = []

    # Parse partial_failure_error first to build row → error mapping
    row_errors: dict[int, dict] = {}
    if response.partial_failure_error and response.partial_failure_error.details:
        GoogleAdsFailure = type(client.get_type("GoogleAdsFailure"))
        for detail in response.partial_failure_error.details:
            failure = GoogleAdsFailure.deserialize(detail.value)
            for error in failure.errors:
                if error.location.field_path_elements:
                    row_idx = error.location.field_path_elements[0].index
                    row_errors[row_idx] = {
                        "error_code": _extract_error_code_name(error.error_code),
                        "error_message": error.message,
                    }

    # Walk results — empty message = failed row
    for idx, result in enumerate(response.results):
        # Per Google docs: "operations from the conversions list that failed will be
        # represented as empty messages."
        # proto-plus heuristic: result.conversion_action is empty string when row failed
        if not result.conversion_action:
            err = row_errors.get(idx, {"error_code": "UNKNOWN", "error_message": "no detail"})
            failures.append({
                "row_index": idx,
                "gclid": input_conversions[idx]["gclid"],
                **err,
            })
        else:
            applied += 1

    return applied, len(failures), failures
```

### audit_log params_summary

```python
{
    "conversion_action_id": "987654321",
    "conversion_count": 12,
    "sum_value_brl": 1850.00,
    "earliest_conversion": "2026-05-15 09:00:00",
    "latest_conversion": "2026-05-17 18:30:00",
    "order_ids_present": 8,
}
```

Sem gclid content (PII-adjacent — gclids podem ser cross-referenced com click data); sem URLs; sem CRM lead IDs. Match spec §3.6.

## Validation layers (4 níveis, fail-fast)

### Layer 1: JSONSchema (jsonschema lib)

Coberto pelo schema em "Tool surface" acima. Runs em tool entry.

### Layer 2: Runtime `_validate_payload_shape` (private helper)

```python
def _validate_payload_shape(payload: dict) -> dict | None:
    """5 checks (per-conversion loop + batch-level).
    Returns None if valid, error dict if invalid.
    """
    from collections import Counter
    from datetime import datetime, timezone, timedelta

    conversions = payload["conversions"]
    now_brt = datetime.now(timezone(timedelta(hours=-3)))

    for idx, conv in enumerate(conversions):
        # Check 1: conversion_date_time parseability (defense-in-depth vs regex)
        try:
            dt = datetime.strptime(conv["conversion_date_time"], "%Y-%m-%d %H:%M:%S")
            dt = dt.replace(tzinfo=timezone(timedelta(hours=-3)))
        except ValueError:
            return _err(idx, f"conversion_date_time '{conv['conversion_date_time']}' não é YYYY-MM-DD HH:MM:SS válido")

        # Check 2: conversion in past (5min clock skew tolerance)
        if dt > now_brt + timedelta(minutes=5):
            return _err(idx, f"conversion_date_time '{conv['conversion_date_time']}' está no futuro; Google rejeita")

        # Check 3: conversion not too old (Google's 90-day click-to-conversion window)
        days_ago = (now_brt - dt).days
        if days_ago > 90:
            return _err(idx, f"conversion_date_time '{conv['conversion_date_time']}' tem {days_ago} dias; Google só aceita até 90 dias")

    # Check 4: gclid duplicates dentro do batch
    gclids = [c["gclid"] for c in conversions]
    if len(gclids) != len(set(gclids)):
        dupes = [g for g, count in Counter(gclids).items() if count > 1]
        return {
            "status": "error",
            "error": f"gclids duplicados no batch: {dupes[:3]}{'...' if len(dupes) > 3 else ''}. Use order_id pra dedupe se intencional.",
            "operation": "import_offline_conversions",
        }

    # Check 5: order_id duplicates (se presente)
    order_ids = [c["order_id"] for c in conversions if "order_id" in c]
    if order_ids and len(order_ids) != len(set(order_ids)):
        dupes = [o for o, count in Counter(order_ids).items() if count > 1]
        return {
            "status": "error",
            "error": f"order_id duplicados no batch: {dupes[:3]}. Cada conversão deve ter order_id único.",
            "operation": "import_offline_conversions",
        }

    return None


def _err(idx: int, msg: str) -> dict:
    return {
        "status": "error",
        "error": f"conversions[{idx}]: {msg}",
        "operation": "import_offline_conversions",
    }
```

### Layer 3: Async pre-flight `validate_conversion_action_for_upload`

Novo helper em `src/google_ads/queries/_common.py` (paralelo a `validate_geo_target_constants_br_only`, `validate_conversion_action_create`):

```python
async def validate_conversion_action_for_upload(
    *, manager_id: UUID, session_id: UUID, customer_id: str,
    conversion_action_id: str,
) -> str | None:
    """GAQL pre-flight: conversion_action exists + type=UPLOAD_CLICKS + status != REMOVED.

    Returns PT-BR error message OR None if valid.
    """
    query = (
        "SELECT conversion_action.id, conversion_action.type, conversion_action.status "
        "FROM conversion_action "
        f"WHERE conversion_action.id = {conversion_action_id}"
    )
    rows = await run_report(
        manager_id=manager_id, session_id=session_id,
        customer_id=customer_id, query=query,
    )
    if not rows:
        return f"conversion_action_id={conversion_action_id} não existe em customer_id={customer_id}"

    row = rows[0]
    action_type = row["conversion_action"]["type"]
    if action_type != "UPLOAD_CLICKS":
        return (
            f"conversion_action_id={conversion_action_id} tem type={action_type}; "
            f"UploadClickConversions requer type=UPLOAD_CLICKS. "
            f"Crie ConversionAction nova via create_conversion_action com type=UPLOAD_CLICKS."
        )

    status = row["conversion_action"]["status"]
    if status == "REMOVED":
        return f"conversion_action_id={conversion_action_id} está REMOVED; não aceita uploads."

    return None
```

### Layer 4: Google API runtime (trust + partial_failure)

`partial_failure=True` → individual conversion failures don't block batch. Errors retornados em `apply_result["failures"]` array.

Common Google error codes (V4-relevant):
- `EXPIRED_GCLID` — gclid > 90 days post-click
- `INVALID_GCLID` — formato gclid corrupto
- `DUPLICATE_GCLID_DATE_TIME_PAIR` — Google detectou conversion já uploaded
- `CONVERSION_PRECEDES_GCLID` — conversion_date_time antes do gclid click date
- `INVALID_CONVERSION_DATE` — data em formato inválido (defense-in-depth Layer 2 deve preemptar)

### V4 Invariants hardcoded (resumo)

| Field | Hardcoded value | Aplicação |
|---|---|---|
| `ClickConversion.currency_code` | `"BRL"` | builder linha `click_conv.currency_code = "BRL"` |
| Conversion datetime timezone | `-03:00` (BRT) | builder linha `f"{conv['conversion_date_time']}-03:00"` |
| `ClickConversion.consent.ad_user_data` | `GRANTED` | builder linha `click_conv.consent.ad_user_data = ConsentStatusEnum.GRANTED` |
| `UploadClickConversionsRequest.partial_failure` | `True` | builder linha `request.partial_failure = True` |
| `UploadClickConversionsRequest.debug_enabled` | `False` | builder linha `request.debug_enabled = False` |

### Edge cases endereçados

1. **Gestor passa conversion no futuro** — Layer 2 Check 2 (5min clock skew tolerance)
2. **Gestor passa conversion > 90 dias atrás** — Layer 2 Check 3 (preemptive vs `EXPIRED_GCLID`)
3. **Gestor envia mesmo gclid 2x no batch** — Layer 2 Check 4
4. **Gestor envia mesmo order_id 2x no batch** — Layer 2 Check 5
5. **Gestor passa conversion_action_id de outro customer** — Layer 3 GAQL retorna 0 rows
6. **Gestor passa conversion_action_id de WEBPAGE type** — Layer 3 type check
7. **ConversionAction REMOVED** — Layer 3 status check
8. **Gestor envia 101 conversions** — Layer 1 (maxItems 100)
9. **Gestor envia gclid expirado (>90 dias post-click)** — Layer 4 (Google `EXPIRED_GCLID`, retornado em failures)
10. **Gestor envia conversion_value <= 0** — Layer 1 (minimum 0.01)

## Tests

### Unit tests

**Tool tests (`tests/unit/test_import_offline_conversions.py`) — ~18 tests:**

Schema validation (6): missing customer_id, missing conversion_action_id, empty array, >100 items, invalid date format, accepts minimal valid.
Runtime `_validate_payload_shape` (8): minimal valid, future, > 90 days, duplicate gclids, duplicate order_ids, distinct order_ids (positive), 5min clock skew tolerance, row_index in error.
Dry-run flow (4): returns token+summary, summary fields (sum_value_brl + date_range), order_ids_present count, pre-flight error pass-through.

**Dispatcher tests (`tests/unit/test_run_conversion_upload.py`) — ~12 tests via MagicMock client:**

- `test_upload_constructs_request_with_correct_customer_id_and_partial_failure_true`
- `test_upload_sets_currency_brl_per_v4_invariant`
- `test_upload_appends_minus_03_timezone_per_v4_invariant`
- `test_upload_sets_consent_granted_per_v4_invariant_lgpd`
- `test_upload_sets_conversion_action_resource_path_correctly`
- `test_upload_includes_order_id_when_present`
- `test_upload_omits_order_id_when_absent`
- `test_upload_request_debug_enabled_false`
- `test_parse_response_counts_applied_correctly`
- `test_parse_response_extracts_failures_with_row_index`
- `test_parse_response_handles_all_success_no_partial_failure`
- `test_parse_response_handles_all_failed`

**apply_change dispatcher tests (`tests/unit/test_apply_change.py`) — +2 regression tests:**

- `test_apply_change_routes_import_offline_conversions_to_run_conversion_upload`
- `test_apply_change_routes_other_operations_to_run_mutation` (regression guard)

### Integration tests (`tests/integration/test_import_offline_conversions.py`) — 2 tests

1. `test_import_offline_conversions_dry_run_emits_token_and_pending_row`
2. `test_import_offline_conversions_full_cycle_returns_applied_count_and_audit`

Both use `session_ctx` fixture (real manager + session). Mock `validate_conversion_action_for_upload` returning None. Test 2 mocks `UploadClickConversionsResponse` with 5 successes + 2 failures, asserts `applied_count==5`, `failed_count==2`, `failures[]` structure, audit_log row.

### Smoke runbook (`docs/operacao/phase-3b-26-bootstrap.md`) — 12 tests

| # | Test | Notes |
|---|---|---|
| T1 | Pre-flight valid UPLOAD_CLICKS ConversionAction | needs existing or freshly-created ConversionAction in Nutry |
| T2 | Pre-flight invalid conversion_action_id (não existe) | PT-BR error pré-Google |
| T3 | Pre-flight WEBPAGE type (type mismatch) | PT-BR error |
| T4 | Happy path: 1 conversion gclid valid | applied_count=1 (note: Google takes 3-24h to register em conversion_action stats) |
| T5 | Happy path: batch 5 conversions | dry_run summary + apply applied_count=5 |
| T6 | Some conversions com order_id | summary.order_ids_present=3 of 5 |
| T7 | Partial failure: 3 valid + 2 fake gclids | applied_count=3, failed_count=2, failures[] com error_code |
| T8 | Layer 2: conversion no futuro | tool returns status=error pre-Google |
| T9 | Layer 2: conversion 95 days old | tool returns status=error |
| T10 | Layer 2: duplicate gclid in batch | tool returns status=error |
| T11 | Layer 2: duplicate order_id in batch | tool returns status=error |
| T12 | Schema regression: 101 conversions | JSONSchema rejection |

**Account scope:** Nutry sandbox (`1163862076`). Precisa de UPLOAD_CLICKS ConversionAction — pode reusar de Sprint 3b.19A smoke ou criar fresh via `create_conversion_action`.

**Test gclids strategy:** Real gclids capturados do Nutry produção pre-smoke. GAQL pre-smoke:

```sql
SELECT
  click_view.gclid,
  click_view.ad_group_ad,
  segments.date
FROM click_view
WHERE segments.date DURING LAST_30_DAYS
LIMIT 10
```

Selecionar 5-10 gclids recentes (<90 dias) pra T4-T6. T7 (partial failure) usa fake gclids intencionais (`"Cj0KCQjwTEST-FAKE-001"`).

**Cleanup post-smoke:** Conversões uploadadas afetam ROAS/Smart Bidding em Nutry. Strategy:
- Use dedicated ConversionAction `[3b.26-smoke]` (criada fresh) que gestor pode pausar/remove post-smoke
- OR aceitar pequeno noise em ROAS Nutry (5-10 conversões de R$ 10-50 cada — diluído em métricas reais)

### CI gates

- `tests/unit/test_tools_schemas.py` (add `import_offline_conversions` ao allowlist + count 48 → 49)
- `tests/unit/test_tools_schemas.py::test_no_composition_keywords_in_any_schema` (auto-cobre novo schema)
- `tests/unit/test_apply_change.py` (regression guard: branching dispatch)

## Implementation steps

```
[Step 0] context7 lookup (DONE 2026-05-18)
  → ConversionUploadService proto field names confirmados:
    - partial_failure (Python; NÃO partial_failure_enabled)
    - consent.ad_user_data = ConsentStatusEnum.GRANTED (V4 invariant LGPD)
    - failure detection: empty result.conversion_action = failed row

[Step 1] failing tests for schema + _validate_payload_shape (~18 tests)
  → tests/unit/test_import_offline_conversions.py — RED state

[Step 2] schema + _validate_payload_shape implementation
  → src/mcp/tools/import_offline_conversions.py (skeleton)
  → GREEN tests [Step 1]

[Step 3] failing tests for run_conversion_upload + _parse_upload_response (~12 tests)
  → tests/unit/test_run_conversion_upload.py — RED state

[Step 4] run_conversion_upload + _parse_upload_response + validate_conversion_action_for_upload
  → src/google_ads/conversions.py (NEW module)
  → src/google_ads/queries/_common.py (+ helper)
  → GREEN tests [Step 3]

[Step 5] tool body finalize (dry_run flow) + apply_change branching
  → src/mcp/tools/import_offline_conversions.py (full body + register_tool)
  → src/mcp/tools/apply_change.py (+ if-branch)
  → tests/unit/test_apply_change.py (+2 dispatcher regression tests)
  → tests/unit/test_tools_schemas.py (+1 line allowlist)

[Step 6] integration tests + smoke scaffold + CLAUDE.md
  → tests/integration/test_import_offline_conversions.py (2 tests)
  → docs/operacao/phase-3b-26-bootstrap.md (12 smoke tests + GCLID capture instructions)
  → CLAUDE.md (+1 sprint row, tool count 48 → 49)

[Step 7] pre-push gate 5/5 + push + watch CI/Deploy + revision capture

[Step 8] Wellington manual smoke + signoff
```

### Files touched

| File | Change | LOC |
|---|---|---|
| `src/mcp/tools/import_offline_conversions.py` | NEW | ~250 |
| `src/google_ads/conversions.py` | NEW | ~220 |
| `src/google_ads/queries/_common.py` | MODIFY | +30 |
| `src/mcp/tools/apply_change.py` | MODIFY | +15 |
| `tests/unit/test_import_offline_conversions.py` | NEW | ~300 |
| `tests/unit/test_run_conversion_upload.py` | NEW | ~280 |
| `tests/integration/test_import_offline_conversions.py` | NEW | ~150 |
| `tests/unit/test_apply_change.py` | MODIFY | +60 |
| `tests/unit/test_tools_schemas.py` | MODIFY | +2 |
| `docs/operacao/phase-3b-26-bootstrap.md` | NEW | ~280 |
| `CLAUDE.md` | MODIFY | +5 |

**Total LOC estimate: ~1590 LOC** (slightly larger than Sprint 3b.25 ~1370 LOC because new `conversions.py` dispatcher module + apply_change refactor).

### Sprint timeline

| Day | Tasks |
|---|---|
| Day 1 AM | Step 1-2 (schema + validator) |
| Day 1 PM | Step 3-4 (run_conversion_upload TDD) |
| Day 2 AM | Step 5 (tool body + apply_change branching) |
| Day 2 PM | Step 6 (integration + smoke + CLAUDE.md) |
| Day 3 AM | Step 7 (push + deploy + revision) |
| Day 3 PM | Step 8 (Wellington smoke + fix iterations Sprint 3b.26.x) |

## Risk register

| Risk | Mitigation |
|---|---|
| **R1: ConversionUploadService proto field names differ in v24 SDK** | PRE-EMPTED via context7 (Step 0 DONE 2026-05-18): `partial_failure` Python field confirmed; `consent.ad_user_data` enum confirmed |
| **R2: `_parse_upload_response` failure-detection heuristic wrong** | Step 3 explicit tests for partial_failure_error.details parsing; smoke T7 (3 valid + 2 fake gclids) validates real Google response format |
| **R3: Timezone -03:00 hardcoded breaks if Google requires IANA tz name** | Spec captures `-03:00` literal per Google docs (BCP 47-style offset); smoke T4 validates real Nutry conversion (GAQL verify post-upload) |
| **R4: GCLID > 256 chars exists in production** | Schema maxLength permissive; trust Google's actual limits — fix iteration if rejected |
| **R5: order_id length 64 vs Google's actual limit** | Trust Google rejection; document as F-finding if hit |
| **R6: ConversionAction REMOVED status check is too aggressive** | Layer 3 check is optional gestor recovery path; doc note: gestor pode "reativar" ConversionAction se acidentalmente paused |
| **R7: Smoke T4-T6 require real gclids that may not be available in Nutry** | Pre-smoke step documented: GAQL `click_view` query extracts recent gclids; doc fallback if GAQL access limited; ultimo recurso skip happy-path em smoke (Layer 2/3 paths still validate dispatcher) |
| **R8: Consent GRANTED hardcoded may violate LGPD for unconsented leads** | Spec assumes V4 captures consent at lead-form time (gestor responsibility); documented in tool description + smoke runbook header |
| **R9: ConversionUploadService rate limit different from GoogleAdsService.mutate** | `before_call` uses standard rate counter; if hit limit, document as F-finding + add per-service quotas |

## Success criteria (sprint signoff)

- [ ] Pre-push gate 5/5 PASS
- [ ] Production /health 200 pós-deploy
- [ ] Smoke runbook signed-off (10+/12 PASS; T4-T6 may need real gclids — partial passage acceptable se Layer 2/3/dispatcher validados)
- [ ] CLAUDE.md sprint row added
- [ ] findings-catalog.md updated se F41+ surgir
- [ ] Tool count 48 → 49 in production
- [ ] At least 1 real conversion uploaded em Nutry sandbox via T4 (proves dispatcher end-to-end)

## Open questions captured during brainstorming (resolved)

| # | Question | Resolution |
|---|---|---|
| Q1 | Conversion type v0 scope | ClickConversions only (gclid match) |
| Q2 | Match types within ClickConversions | gclid only (gbraid/wbraid + Enhanced Conversions v1) |
| Q3 | Always-CONFIRM dry_run vs immediate | Always-CONFIRM + partial_failure=True |
| Q4 | Pre-flight async depth | validate conversion_action_id exists + type=UPLOAD_CLICKS |
| Q5 | conversion_date_time format | Full YYYY-MM-DD HH:MM:SS + V4 invariant -03:00 |
| Q6 | Batch size + order_id | 1-100 batch + optional order_id |
| Q7 | currency + custom_variables | BRL hardcoded + no custom_variables v0 |
| Q8 (new via context7) | LGPD consent.ad_user_data | Hardcoded GRANTED V4 invariant |

## References

- Sprint 3b.25 spec: `docs/superpowers/specs/2026-05-18-sprint-3b-25-create-and-link-assets-design.md` (predecessor pattern, V4 invariants)
- Sprint 3b.24 spec: `docs/superpowers/specs/2026-05-17-sprint-3b-24-create-campaign-design.md` (Always-CONFIRM + V4 invariants pattern)
- Sprint 3b.19A spec: `docs/superpowers/specs/2026-05-13-sprint-3b.19A-design.md` (`create_conversion_action` — ConversionAction creator predecessor)
- Sprint 3b.19B.1 convention: no JSONSchema composition keywords (CLAUDE.md)
- Sprint 3b.19A.1 convention: per-value empirical probe in smoke (CLAUDE.md)
- Sprint 3b.5/3b.8 convention: pre-flight test mock at tool namespace
- Findings catalog: `docs/operacao/findings-catalog.md`
- Original V4 Ads MCP design: `docs/superpowers/specs/2026-05-03-v4-ads-mcp-design.md` §"Conversões"
- Google Ads ConversionUploadService docs: https://developers.google.com/google-ads/api/docs/conversions/upload-clicks
- Google Ads consent policy: https://www.google.com/about/company/user-consent-policy
