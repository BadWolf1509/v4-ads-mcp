# Sprint 3b.25 — `create_and_link_assets` design

**Status:** Draft → user review pending
**Owner:** Wellington (`wellinton.ribeiro@v4company.com`)
**Date:** 2026-05-18
**Predecessor:** Sprint 3b.24 (`create_campaign` SEARCH v0)
**Successors planejados:** 3b.26 (`import_offline_conversions`), 3b.27 (`upload_customer_match_list` + A4 fix), 3b.28 (`remove_*` bundle)

## Goal

Segundo mutation tool da fase de finalização (3b.24-3b.28). Permite gestor V4 configurar text-extensions completas (sitelinks, callouts, snippets, call, promotions) de uma conta nova via Claude/Codex MCP, fechando o loop de onboarding iniciado em Sprint 3b.24 (`create_campaign`).

V4 use case típico: após criar campanha pelo MCP, gestor diz "configure as extensões da campanha X" → Claude chama `create_and_link_assets` 1× com 4 sitelinks + 2 callouts + 1 snippet + 1 call = 8 assets criados + 8 links em chained mutation atomic. Sem fallback pra Google Ads UI.

## Context / why now

- **Wellington decisão (brainstorming 2026-05-18):** scope confirmado durante brainstorming:
  - Asset types v0: SITELINK + CALLOUT + STRUCTURED_SNIPPET + CALL + PROMOTION (5 text-extension types)
  - API surface: 1 fused tool `create_and_link_assets` (não 2 tools como spec original previa)
  - Attachment levels: CUSTOMER + CAMPAIGN + AD_GROUP (3 levels — full Google Ads model)
  - Batch: N mixed-type, mixed-level (max 20 por call)
  - V4 invariants hardcoded: BR + PT + BRL
  - Pre-flight async: nenhuma (trust Google errors per Sprint 3b.19A.1 F14 lesson)

- **Padrão consolidado:** sexto create-pattern (`create_ad_group` 3b.14, `create_rsa` 3b.16, `create_conversion_action` 3b.19A, `create_conversion_value_rule_set` 3b.19B, `create_campaign` 3b.24, `create_and_link_assets` 3b.25)

- **Chained mutation reused:** Sprint 3b.19B established pattern; 3b.24 expandiu pra N+M+2 ops; 3b.25 usa 2N ops (N CreateAsset + N Create{Customer,Campaign,AdGroup}Asset link ops) em single MutateGoogleAdsRequest

- **Sem dependência de Standard Access** (análise empírica 2026-05-17 em CLAUDE.md mostra uso atual 0.07% Basic limit, headroom 30x worst-case)

- **Proto field names validados via context7** (2026-05-18) usando `/websites/developers_google_google-ads_api`:
  - `SitelinkAsset.{link_text, description1, description2}` confirmados
  - `CallAsset.{phone_number (raw format), country_code (2-letter ISO)}` confirmados
  - `CalloutAsset.callout_text` confirmado
  - `PromotionAsset.{promotion_target, discount_modifier, percent_off (micros: 1M = 100%), money_amount_off.{amount_micros, currency_code}, language_code, start_date, end_date, redemption_start_date, redemption_end_date}` confirmados
  - `final_urls` é Asset-level (pai), não dentro do sub-message — aplicado direto em `asset_operation.create.final_urls`

## Non-goals (v0)

- **IMAGE_ASSET / VIDEO_ASSET** — display/PMAX-focused, V4 é 100% SEARCH lead-gen
- **LOCATION_ASSET** — exige sync com Google Business Profile, auto-managed
- **PRICE_ASSET** — V4 raramente usa pricing tables (B2B leads)
- **APP_ASSET / LEAD_FORM_ASSET / HOTEL_CALLOUT** — fora do scope V4
- **DEMAND_GEN_TOUR_ASSET / HEADLINE_ASSET (PMAX-specific)** — N/A SEARCH
- **AssetSet** + AssetSetAsset linkage (asset grouping mechanism) — out of scope v0; v1 candidate se demand surgir
- **Asset reuse cross-campaign** (linkar Asset existente a novo Campaign) — fused tool sempre cria asset novo. Reuse via separate `link_assets` tool fica v1 se demand surgir.
- **Asset update / remove / unlink** — Sprint 3b.28 (`remove_*` bundle) territory
- **`redemption_start_date` / `redemption_end_date`** (PROMOTION redemption window — quando customer pode redeem) — v0 só expõe `start_date`/`end_date` (asset effectiveness — quando ad serve). v1 pode separar.
- **`ad_schedule_targets`** (per-asset scheduling) — out of scope v0; defaults Google (always serving)
- **`call_conversion_action` + `call_conversion_reporting_state`** (CALL asset call-tracking) — v0 usa Google defaults; gestor configura post-create via Google Ads UI se quiser tracking
- **`occasion`** (PromotionAsset.occasion enum — MOTHERS_DAY, BLACK_FRIDAY, etc, com auto-date-window) — out of scope v0; gestor passa `start_date`/`end_date` manualmente
- **Pre-flight async validations** (attachment_id exists, cap limit checks) — trust Google errors per Sprint 3b.19A.1 F14 lesson
- **Asset reuse no mesmo call** (gestor passa mesmo asset_payload 2× pra linkar em 2 lugares) — v0 sempre cria 2 assets distintos; reuse via futuro `link_assets` tool

## Tool surface

### Name
`create_and_link_assets`

### Description (PT-BR)

```
Cria N text-assets novos (1-20 por call) e linka cada um ao escopo solicitado
(CUSTOMER/CAMPAIGN/AD_GROUP) em chained mutation atomic. Always-CONFIRM.
Tipos suportados v0: SITELINK, CALLOUT, STRUCTURED_SNIPPET, CALL, PROMOTION
(text-extension family, SEARCH-relevant). V4 invariants hardcoded: country_code=BR
para CALL, language_code=pt para PROMOTION, currency_code=BRL para
PROMOTION.money_amount_off. Cada item da lista `assets` carrega `type` +
`attachment_level` + `attachment_id` + payload type-specific. Builder usa
chained mutation (N CreateAsset ops + N Create{Customer,Campaign,AdGroup}Asset
link ops em single MutateGoogleAdsRequest com temp resource_names).
F13 cross-cutting auto-retorna 2N resource_names (assets criados + links criados).
```

### Input schema (JSONSchema, sem composition keywords per Sprint 3b.19B.1 convention)

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["customer_id", "assets"],
  "properties": {
    "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
    "assets": {
      "type": "array",
      "minItems": 1,
      "maxItems": 20,
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["type", "attachment_level", "attachment_id"],
        "properties": {
          "type": {
            "type": "string",
            "enum": ["SITELINK", "CALLOUT", "STRUCTURED_SNIPPET", "CALL", "PROMOTION"]
          },
          "attachment_level": {
            "type": "string",
            "enum": ["CUSTOMER", "CAMPAIGN", "AD_GROUP"]
          },
          "attachment_id": {
            "type": "string",
            "description": "customer_id (CUSTOMER), campaign resource path 'customers/X/campaigns/Y' (CAMPAIGN), ad_group resource path 'customers/X/adGroups/Y' (AD_GROUP)"
          },

          "link_text": {
            "type": "string", "minLength": 1, "maxLength": 25,
            "description": "SITELINK — display text (1-25 chars)"
          },
          "final_urls": {
            "type": "array", "items": {"type": "string", "format": "uri"},
            "minItems": 1, "maxItems": 5,
            "description": "SITELINK / PROMOTION — destination URLs (1-5 URLs)"
          },
          "description1": {
            "type": "string", "minLength": 1, "maxLength": 35,
            "description": "SITELINK optional — first description line; must be paired with description2"
          },
          "description2": {
            "type": "string", "minLength": 1, "maxLength": 35,
            "description": "SITELINK optional — second description line; must be paired with description1"
          },

          "callout_text": {
            "type": "string", "minLength": 1, "maxLength": 25,
            "description": "CALLOUT — text content (1-25 chars)"
          },

          "header": {
            "type": "string",
            "enum": [
              "AMENITIES", "BRANDS", "COURSES", "DEGREE_PROGRAMS", "DESTINATIONS",
              "FEATURED_HOTELS", "INSURANCE_COVERAGE", "MODELS", "NEIGHBORHOODS",
              "SERVICE_CATALOG", "SHOWS", "STYLES", "TYPES"
            ],
            "description": "STRUCTURED_SNIPPET — Google whitelist of 13 headers"
          },
          "values": {
            "type": "array", "items": {"type": "string", "minLength": 1, "maxLength": 25},
            "minItems": 3, "maxItems": 10,
            "description": "STRUCTURED_SNIPPET — 3-10 short labels under the header"
          },

          "phone_number": {
            "type": "string", "pattern": "^[\\d\\s\\(\\)\\-]{10,20}$",
            "description": "CALL — BR phone number (raw format aceitos: '11987654321', '(11) 98765-4321', '11 9 8765-4321'). Country code 'BR' hardcoded V4 invariant."
          },

          "promotion_target": {
            "type": "string", "minLength": 1, "maxLength": 20,
            "description": "PROMOTION — short freeform target (e.g., 'Verão 2026')"
          },
          "discount_modifier": {
            "type": "string", "enum": ["NONE", "UP_TO"],
            "description": "PROMOTION — UP_TO renders 'até X% off' (default NONE = exact)"
          },
          "percent_off": {
            "type": "number", "minimum": 0.01, "maximum": 100.0,
            "description": "PROMOTION — percent value 0.01-100. XOR with money_amount_off_brl. Stored as micros (value * 10_000) where 100% = 1_000_000 micros."
          },
          "money_amount_off_brl": {
            "type": "number", "minimum": 0.01,
            "description": "PROMOTION — BRL value off. XOR with percent_off. Currency BRL hardcoded."
          },
          "start_date": {
            "type": "string", "pattern": "^\\d{4}-\\d{2}-\\d{2}$",
            "description": "PROMOTION optional — asset effectiveness start (yyyy-MM-dd)"
          },
          "end_date": {
            "type": "string", "pattern": "^\\d{4}-\\d{2}-\\d{2}$",
            "description": "PROMOTION optional — asset effectiveness end (yyyy-MM-dd); must >= start_date"
          }
        }
      }
    }
  }
}
```

### Per-type field map (enforced by runtime `_validate_payload_shape`)

| Type | Required fields | Optional fields |
|---|---|---|
| **SITELINK** | `link_text`, `final_urls` | `description1` + `description2` (paired) |
| **CALLOUT** | `callout_text` | — |
| **STRUCTURED_SNIPPET** | `header` (whitelist), `values` (3-10) | — |
| **CALL** | `phone_number` | — |
| **PROMOTION** | `promotion_target`, `discount_modifier`, (`percent_off` XOR `money_amount_off_brl`), `final_urls` | `start_date` + `end_date` |

### Always-CONFIRM dry_run flow

1. Tool valida schema (jsonschema) + runtime (`_validate_payload_shape`)
2. Retorna `dry_run` preview com `assets_summary` (counts by type/level) + `confirmation_token`
3. Gestor confirma via `apply_change(confirmation_token=...)`
4. `apply_change` dispara `run_mutation` → `build_create_and_link_assets()` → MutateGoogleAdsRequest
5. F13 auto-extracts `resource_names` (2N: N asset paths + N link paths em ordering Op[0]Asset, Op[1]Link, Op[2]Asset, Op[3]Link, ...)
6. `audit_log` row registra `target_count=2N` + custom `params_summary` (counts by type/level, sem conteúdo)

### Dry-run preview structure

```json
{
  "status": "dry_run",
  "operation": "create_and_link_assets",
  "confirmation_token": "<short-lived UUID>",
  "summary": {
    "asset_count": 8,
    "by_type": {"SITELINK": 4, "CALLOUT": 2, "STRUCTURED_SNIPPET": 1, "CALL": 1},
    "by_level": {"CUSTOMER": 2, "CAMPAIGN": 5, "AD_GROUP": 1},
    "attachment_ids_distinct": 3,
    "total_ops_chained": 16
  }
}
```

## Builder architecture

### Module layout

Novo módulo: `src/google_ads/mutates/assets.py` (paralelo a `campaigns.py`, `ads.py`).

**Função pública:** `build_create_and_link_assets(client, customer_id, payload) -> list[MutateOperation]`

### Ops layout em single MutateGoogleAdsRequest

Para N assets, gera **2N ops** sequenciais:

```
Op[0]     asset_operation.create              → customers/{cid}/assets/-1   (Asset #1)
Op[1]     {customer|campaign|ad_group}_asset_operation.create
                                              → links Op[0] to scope #1     (Link #1)

Op[2]     asset_operation.create              → customers/{cid}/assets/-2   (Asset #2)
Op[3]     {customer|campaign|ad_group}_asset_operation.create
                                              → links Op[2] to scope #2     (Link #2)

... continues for N assets, 2 ops each
```

**Temp resource_name scheme:**
- Asset #i uses temp `customers/{cid}/assets/-{i}` (negative ints, Sprint 3b.24 convention)
- Link op references the temp asset path → Google substitutes real ID at apply time
- Atomic: all 2N ops succeed or all fail (chained mutation guarantee)

### Per-type proto assignment

```python
def build_create_and_link_assets(client, customer_id, payload):
    ops = []
    for i, a in enumerate(payload["assets"], start=1):
        temp_asset_path = f"customers/{customer_id}/assets/-{i}"

        # === Step 1: CreateAssetOp ===
        asset_op = client.get_type("MutateOperation")
        asset_op.asset_operation.create.resource_name = temp_asset_path

        if a["type"] == "SITELINK":
            sitelink = asset_op.asset_operation.create.sitelink_asset
            sitelink.link_text = a["link_text"]
            if "description1" in a:
                sitelink.description1 = a["description1"]
                sitelink.description2 = a["description2"]
            asset_op.asset_operation.create.final_urls.extend(a["final_urls"])

        elif a["type"] == "CALLOUT":
            asset_op.asset_operation.create.callout_asset.callout_text = a["callout_text"]

        elif a["type"] == "STRUCTURED_SNIPPET":
            snippet = asset_op.asset_operation.create.structured_snippet_asset
            snippet.header = a["header"]
            snippet.values.extend(a["values"])

        elif a["type"] == "CALL":
            call = asset_op.asset_operation.create.call_asset
            call.phone_number = a["phone_number"]
            call.country_code = "BR"  # V4 invariant

        elif a["type"] == "PROMOTION":
            promo = asset_op.asset_operation.create.promotion_asset
            promo.promotion_target = a["promotion_target"]
            promo.discount_modifier = client.enums.PromotionExtensionDiscountModifierEnum[a["discount_modifier"]]
            if "percent_off" in a:
                promo.percent_off = int(a["percent_off"] * 10_000)  # 1M = 100%
            else:
                promo.money_amount_off.amount_micros = int(a["money_amount_off_brl"] * 1_000_000)
                promo.money_amount_off.currency_code = "BRL"  # V4 invariant
            promo.language_code = "pt"  # V4 invariant
            asset_op.asset_operation.create.final_urls.extend(a["final_urls"])
            if "start_date" in a:
                promo.start_date = a["start_date"]
            if "end_date" in a:
                promo.end_date = a["end_date"]

        ops.append(asset_op)

        # === Step 2: Link Op (branches on attachment_level) ===
        link_op = client.get_type("MutateOperation")
        field_type = client.enums.AssetFieldTypeEnum[a["type"]]

        if a["attachment_level"] == "CUSTOMER":
            ca = link_op.customer_asset_operation.create
            ca.asset = temp_asset_path
            ca.field_type = field_type

        elif a["attachment_level"] == "CAMPAIGN":
            cm = link_op.campaign_asset_operation.create
            cm.asset = temp_asset_path
            cm.campaign = a["attachment_id"]
            cm.field_type = field_type

        elif a["attachment_level"] == "AD_GROUP":
            ag = link_op.ad_group_asset_operation.create
            ag.asset = temp_asset_path
            ag.ad_group = a["attachment_id"]
            ag.field_type = field_type

        ops.append(link_op)

    return ops
```

### Field type mapping (1:1 v0)

```python
# In v0 every user-facing type maps directly to AssetFieldType enum value:
# SITELINK → AssetFieldTypeEnum.SITELINK
# CALLOUT → AssetFieldTypeEnum.CALLOUT
# STRUCTURED_SNIPPET → AssetFieldTypeEnum.STRUCTURED_SNIPPET
# CALL → AssetFieldTypeEnum.CALL
# PROMOTION → AssetFieldTypeEnum.PROMOTION
```

(Helper anti-pattern v0; inline mapping é mais legível. Se v1 expandir pra types não-1:1, refactor pra helper.)

### F13 resource_names auto-extraction

`run_mutation` em `src/google_ads/mutations.py` já tem `WhichOneof("response")` walker (Sprint 3b.15). For each of 2N `mutate_operation_responses`:

- Op[2i] → `asset_result.resource_name` → `customers/{cid}/assets/{real_id}`
- Op[2i+1] → one of `customer_asset_result` / `campaign_asset_result` / `ad_group_asset_result`.resource_name

Result: `apply_result["resource_names"]` array com 2N paths, ordering matches input.

### audit_log params_summary (no PII content)

```python
params_summary = {
    "asset_count": len(payload["assets"]),
    "by_type": {"SITELINK": 4, "CALLOUT": 2, "CALL": 1},
    "by_level": {"CUSTOMER": 0, "CAMPAIGN": 6, "AD_GROUP": 1},
    "attachment_ids_distinct": 3,
}
```

Sem texto/URLs/phone/promotion content em `params_summary` (consistente com spec §3.6 "audit_log não armazena PII").

## Validation layers

### Layer 1: JSONSchema (jsonschema lib)

Coberto pelo schema em "Tool surface" acima. Runs em tool entry, antes de qualquer outro work.

### Layer 2: Runtime `_validate_payload_shape` (em tool body)

Private helper top of `create_and_link_assets.py`. Returns `{"status": "error", "error": "<PT-BR>", "operation": "create_and_link_assets"}` or `None`.

**6 checks (per-asset loop):**

```python
def _validate_payload_shape(payload: dict) -> dict | None:
    customer_id = payload["customer_id"]

    per_type_required = {
        "SITELINK": ["link_text", "final_urls"],
        "CALLOUT": ["callout_text"],
        "STRUCTURED_SNIPPET": ["header", "values"],
        "CALL": ["phone_number"],
        "PROMOTION": ["promotion_target", "discount_modifier", "final_urls"],
    }
    per_type_allowed = {
        "SITELINK": {"link_text", "final_urls", "description1", "description2"},
        "CALLOUT": {"callout_text"},
        "STRUCTURED_SNIPPET": {"header", "values"},
        "CALL": {"phone_number"},
        "PROMOTION": {"promotion_target", "discount_modifier", "percent_off",
                      "money_amount_off_brl", "final_urls", "start_date", "end_date"},
    }
    common_keys = {"type", "attachment_level", "attachment_id"}

    for idx, a in enumerate(payload["assets"]):
        atype = a["type"]
        alevel = a["attachment_level"]
        aid = a["attachment_id"]

        # Check 1: attachment_id consistency with attachment_level
        if alevel == "CUSTOMER":
            if aid != customer_id:
                return _err(idx, f"attachment_id deve igualar customer_id ('{customer_id}') quando attachment_level=CUSTOMER")
        elif alevel == "CAMPAIGN":
            if not aid.startswith(f"customers/{customer_id}/campaigns/"):
                return _err(idx, f"attachment_id deve ser resource path 'customers/{customer_id}/campaigns/<id>' quando attachment_level=CAMPAIGN")
        elif alevel == "AD_GROUP":
            if not aid.startswith(f"customers/{customer_id}/adGroups/"):
                return _err(idx, f"attachment_id deve ser resource path 'customers/{customer_id}/adGroups/<id>' quando attachment_level=AD_GROUP")

        # Check 2: per-type required fields
        for f in per_type_required[atype]:
            if f not in a:
                return _err(idx, f"campo '{f}' obrigatório quando type={atype}")

        # Check 3: per-type forbidden fields (defense-in-depth vs additionalProperties:false)
        for f in set(a.keys()) - common_keys:
            if f not in per_type_allowed[atype]:
                return _err(idx, f"campo '{f}' não aplicável a type={atype}")

        # Check 4: SITELINK description1/description2 paired
        if atype == "SITELINK":
            d1 = "description1" in a
            d2 = "description2" in a
            if d1 != d2:
                return _err(idx, "description1 e description2 devem ser ambos presentes ou ambos ausentes")

        # Check 5: PROMOTION discount XOR
        if atype == "PROMOTION":
            has_pct = "percent_off" in a
            has_amt = "money_amount_off_brl" in a
            if has_pct == has_amt:
                return _err(idx, "PROMOTION requer exatamente um de 'percent_off' OU 'money_amount_off_brl'")

            # Check 6: PROMOTION dates ordering
            if "start_date" in a and "end_date" in a:
                if a["end_date"] < a["start_date"]:  # ISO YYYY-MM-DD lex == date order
                    return _err(idx, f"end_date ({a['end_date']}) deve ser >= start_date ({a['start_date']})")

    return None


def _err(idx: int, msg: str) -> dict:
    return {
        "status": "error",
        "error": f"assets[{idx}]: {msg}",
        "operation": "create_and_link_assets",
    }
```

### Layer 3: Google API runtime (trust Google's errors)

Per Sprint 3b.19A.1 F14 lesson — sem async pre-flight. Google's rejection passa por `_classify_partial` que mapeia pra PT-BR se class conhecida, senão passthrough.

**Expected Google errors covered:**
- `CAMPAIGN_NOT_FOUND` / `AD_GROUP_NOT_FOUND` — attachment_id aponta entity inexistente
- `DUPLICATE_ASSETS` — sitelink/callout idêntico já existe
- `CAMPAIGN_LINKED_CRITERION_LIMIT_EXCEEDED` — cap de 20 sitelinks/callouts/etc por campaign
- `INVALID_PROMOTION_DATE_RANGE` — past dates ou intervalo > 2y
- `INVALID_ASSET_LEVEL` / `OPERATION_NOT_PERMITTED_FOR_CONTEXT` — se algum type não suporta certo level (e.g., expected finding F38+ pra CALL AD_GROUP)

### V4 Invariants hardcoded (resumo)

| Field | Hardcoded value | Aplicação |
|---|---|---|
| `CallAsset.country_code` | `"BR"` | builder: `call.country_code = "BR"` |
| `PromotionAsset.language_code` | `"pt"` | builder: `promo.language_code = "pt"` |
| `PromotionAsset.money_amount_off.currency_code` | `"BRL"` | builder: `promo.money_amount_off.currency_code = "BRL"` |
| `phone_number` BR-only | regex `^[\d\s\(\)\-]{10,20}$` | schema layer 1 (cliente non-BR rejeitado) |
| Sem `language_code` exposed | — | gestor não controla; v0 PT-only |
| Sem `country_code` exposed | — | gestor não controla; v0 BR-only |

## Tests

### Unit tests

**Builder tests** (`tests/unit/test_create_and_link_assets_builder.py`) — ~18 tests usando `make_capture_client` (post-3b.5 convention):

Per-type happy path (5): SITELINK minimal, SITELINK with descriptions, CALLOUT, STRUCTURED_SNIPPET, CALL.
PROMOTION variants (3): percent_off, money_amount_off, with date range.
Attachment level branching (3): CUSTOMER, CAMPAIGN, AD_GROUP per type.
Chained mutation invariants (4): emits 2N ops, links temp resources correctly, field_type set on link op, mixed types/levels in single call.
V4 invariants (3): CALL always BR, PROMOTION always pt, PROMOTION money always BRL.

**Tool tests** (`tests/unit/test_create_and_link_assets.py`) — ~15 tests:

Schema validation (5): missing customer_id, empty array, >20 assets, invalid phone, no composition keywords.
Runtime `_validate_payload_shape` (8): SITELINK with callout_text rejected, PROMOTION with both discounts, PROMOTION without discounts, description pair, attachment_id consistency CUSTOMER, attachment_id consistency CAMPAIGN, end_date < start_date, accepts minimal valid.
Dry-run flow (2): returns token + summary, summary counts by type/level.

### Integration tests

`tests/integration/test_create_and_link_assets.py` — 2 tests (matches Sprint 3b.24 pattern):

1. `test_create_and_link_assets_dry_run_emits_token_and_audit_pending`
2. `test_create_and_link_assets_full_cycle_returns_2N_resource_names_and_audit_applied`

### Smoke runbook (`docs/operacao/phase-3b-25-bootstrap.md`)

Per-value empirical probe (Sprint 3b.19A.1 convention). 15 tests em Nutry sandbox:

| # | Test | Type | Level | Notes |
|---|---|---|---|---|
| T1 | SITELINK CUSTOMER | SITELINK | CUSTOMER | 1 asset, resource_names=2 |
| T2 | SITELINK CAMPAIGN (most common V4) | SITELINK | CAMPAIGN | 4 assets, resource_names=8 |
| T3 | SITELINK AD_GROUP (rare granular) | SITELINK | AD_GROUP | 1 asset; if Google reject, document as F-class |
| T4 | CALLOUT CUSTOMER (brand callouts) | CALLOUT | CUSTOMER | 3 assets, resource_names=6 |
| T5 | CALLOUT CAMPAIGN | CALLOUT | CAMPAIGN | 2 assets, resource_names=4 |
| T6 | STRUCTURED_SNIPPET CUSTOMER (header=SERVICE_CATALOG) | SNIPPET | CUSTOMER | 1 asset |
| T7 | STRUCTURED_SNIPPET CAMPAIGN (header=BRANDS) | SNIPPET | CAMPAIGN | 1 asset |
| T8 | CALL CAMPAIGN (V4 lead-gen phone) | CALL | CAMPAIGN | 1 asset; assert country_code=BR enforced |
| T9 | CALL AD_GROUP (granular) | CALL | AD_GROUP | 1 asset; if Google reject, document |
| T10 | PROMOTION percent_off=20.0 | PROMOTION | CAMPAIGN | 1 asset; assert percent_off=200_000 micros (NOT 20_000_000) |
| T11 | PROMOTION money_amount_off_brl=50.0 | PROMOTION | CAMPAIGN | 1 asset; assert BRL invariant |
| T12 | Mixed batch V4 onboarding | mixed | mixed | 4 SITELINKs + 2 CALLOUTs CUSTOMER + 1 CALL CAMPAIGN = 7 assets, resource_names=14 |
| T13 | Schema regression: SITELINK + callout_text rejected | — | — | Tool returns status=error pre-Google call |
| T14 | Schema regression: PROMOTION sem desconto rejected | — | — | Tool returns status=error |
| T15 | F22-equivalent: 20 assets batch (response cap test) | mixed | CAMPAIGN | 20 SITELINKs, response < MCP cap (~36k chars projetado) |

**Expected F-class findings (similar to Sprint 3b.24 F36):**
- T3 (SITELINK AD_GROUP) — pode rejeitar com `INVALID_ASSET_LEVEL` se Google não suporta
- T9 (CALL AD_GROUP) — same; CALL é tipicamente CUSTOMER/CAMPAIGN
- Document as F38+ se confirmado; remover do schema enum em fix iteration 3b.25.1

**Account scope:** Nutry sandbox (mesmo do Sprint 3b.24). 5 campaigns já PAUSED criadas no Sprint 3b.24 — anexar assets sem serving impact.

**Cleanup pós-smoke:** spawn-task pra Sprint 3b.28 (`remove_*` bundle). Assets ficam paused (campaigns paused, zero serving impact).

### CI gates

- `tests/unit/test_tools_schemas.py::test_no_composition_keywords_in_any_schema` (auto-cobre novo schema)
- `tests/unit/test_tools_schemas.py` (add `create_and_link_assets` ao expected allowlist)
- `tests/unit/test_tools_registry.py` (Sprint 3b.14.1 auto-discovery)

## Implementation steps

```
[1] context7 lookup (DONE 2026-05-18): SitelinkAsset/CalloutAsset/StructuredSnippetAsset/CallAsset/PromotionAsset proto field names v23/v24
    → description1/description2 confirmed
    → phone_number raw format, NOT E.164
    → percent_off micros: value * 10_000 (1M = 100%)
    → PromotionAsset: start_date/end_date (effectiveness) vs redemption_start_date/redemption_end_date (separate); v0 uses effectiveness only

[2] failing tests for schema + _validate_payload_shape (~13 tests)
    → tests/unit/test_create_and_link_assets.py — RED state

[3] schema + _validate_payload_shape in tool body
    → src/mcp/tools/create_and_link_assets.py (skeleton + schema + validator) — GREEN [2]

[4] failing builder tests (~18 tests)
    → tests/unit/test_create_and_link_assets_builder.py — RED state

[5] build_create_and_link_assets in mutates module
    → src/google_ads/mutates/assets.py (NEW module) — GREEN [4]

[6] tool body finalization (dry_run, audit_log, run_mutation dispatch)
    → src/mcp/tools/create_and_link_assets.py — GREEN remaining unit tests
    → register em test_tools_schemas allowlist (1 LOC)

[7] integration tests (2 tests)
    → tests/integration/test_create_and_link_assets.py — testcontainers + F13

[8] scaffold smoke runbook
    → docs/operacao/phase-3b-25-bootstrap.md — 15 testes T1-T15
    → CLAUDE.md "Current state" + sprint row

[9] pre-push gate: scripts/check_pre_push.py (5/5 PASS, ~30s)

[10] commit + push → deploy → /health 200 → smoke execution → fix iterations Sprint 3b.25.1+ se findings
```

### Files touched

| File | Change | LOC |
|---|---|---|
| `src/mcp/tools/create_and_link_assets.py` | NEW | ~250 |
| `src/google_ads/mutates/assets.py` | NEW | ~200 |
| `src/google_ads/mutations.py` | MODIFY | +1 line (tool→builder mapping) |
| `tests/unit/test_create_and_link_assets.py` | NEW | ~250 |
| `tests/unit/test_create_and_link_assets_builder.py` | NEW | ~350 |
| `tests/integration/test_create_and_link_assets.py` | NEW | ~120 |
| `tests/unit/test_tools_schemas.py` | MODIFY | +1 line (allowlist) |
| `docs/operacao/phase-3b-25-bootstrap.md` | NEW | ~200 |
| `CLAUDE.md` | MODIFY | +1 row em sprint table |

**Total LOC estimate: ~1370 LOC** (similar a Sprint 3b.24 ~1200 LOC).

### Sprint timeline

| Day | Tasks |
|---|---|
| Day 1 AM | Steps 2-3 (schema + validator) |
| Day 1 PM | Steps 4-5 (builder TDD via proto_capture) |
| Day 2 AM | Steps 6-7 (tool body + integration tests) |
| Day 2 PM | Steps 8-10 (smoke scaffold + pre-push + push + deploy + smoke) |
| Day 3 | Fix iterations Sprint 3b.25.1+ se findings (paridade Sprint 3b.24 que teve 5 iterations) |

## Risk register

| Risk | Mitigation |
|---|---|
| **R1: Proto field names diferentes em v24** | Pre-empted via context7 (DONE 2026-05-18); proto names locked em spec |
| **R2: AD_GROUP-level support não funciona pra alguns types** (T3, T9 smoke) | Document as F-class finding (out of scope v0), schema fix em 3b.25.x se confirmado |
| **R3: PROMOTION oneof gotcha similar a Sprint 3b.24 F30** | `promo.percent_off` é scalar (não oneof) — bare access funciona. `promo.money_amount_off.amount_micros` é sub-message scalar — bare access auto-inits (3b.24.4 pattern). |
| **R4: STRUCTURED_SNIPPET header whitelist 13 valores deprecated** (Sprint 3b.19A F17 family) | Per-value smoke probe em T6+T7 valida 2 headers; backlog probe outros 11 antes de v1 release |
| **R5: Phone regex aceita inválidos** | Schema regex `^[\d\s\(\)\-]{10,20}$` permissive; Google API rejecta phone inválido com clear error → trust Google |
| **R6: percent_off micros formula error** (Sprint 3b.24-style F-class) | Spec explicitly captures `* 10_000` (NOT `* 1_000_000`); T10 smoke asserts `200_000` micros for 20.0 percent |
| **R7: Token cap em mixed batch T12 (7 assets = 14 resource_names)** | Single MCP response cap ~100k chars; 14 resource_names = ~1k + dry_run summary = ~5k. Bem abaixo do cap. |

## Success criteria (sprint signoff)

- [ ] Pre-push gate 5/5 PASS
- [ ] Production /health 200 pós-deploy
- [ ] Smoke runbook signed-off (12+/15 tests PASS; T3/T9 pode ser documentado finding sem blocker)
- [ ] CLAUDE.md sprint row added
- [ ] findings-catalog.md updated se F38+ surgir
- [ ] Tool count 47 → 48 in production

## Open questions captured during brainstorming (resolved)

| # | Question | Resolution |
|---|---|---|
| Q1 | Asset types v0 scope | SITELINK + CALLOUT + STRUCTURED_SNIPPET + CALL + PROMOTION (full text-extension family) |
| Q2 | API surface (2 tools vs fused) | 1 fused tool `create_and_link_assets` (atomic create+link) |
| Q3 | Attachment levels v0 | CUSTOMER + CAMPAIGN + AD_GROUP (full Google Ads model) |
| Q4 | Batch granularity | N mixed-type, mixed-level (max 20) |
| Q5 | V4 invariants approach | Hardcode máximo BR + PT + BRL |
| Q6 | Pre-flight async depth | None — trust Google errors (Sprint 3b.19A.1 F14 lesson) |
| Q7 | Proto field uncertainty | Resolved via context7 (description1/description2, raw phone, percent_off * 10_000) |

## References

- Sprint 3b.24 design: `docs/superpowers/specs/2026-05-17-sprint-3b-24-create-campaign-design.md` (predecessor pattern)
- Sprint 3b.19B design: `docs/superpowers/specs/2026-05-13-sprint-3b.19B-design.md` (chained mutation precedent)
- Sprint 3b.19B.1 convention: no JSONSchema composition keywords (CLAUDE.md)
- Sprint 3b.19A.1 convention: per-value empirical probe in smoke (CLAUDE.md)
- Sprint 3b.5+3b.8 convention: pre-flight test mock at tool namespace (findings-catalog §F-class)
- Sprint 3b.5 convention: `make_capture_client` over MagicMock for builder tests
- Findings catalog: `docs/operacao/findings-catalog.md`
- Original V4 Ads MCP design: `docs/superpowers/specs/2026-05-03-v4-ads-mcp-design.md` §"Assets/extensões"
- Google Ads API SitelinkAsset/CalloutAsset/StructuredSnippetAsset/CallAsset/PromotionAsset proto: `https://developers.google.com/google-ads/api/diff-tool/v23/versus-v22/diffs/full/common/asset_types`
