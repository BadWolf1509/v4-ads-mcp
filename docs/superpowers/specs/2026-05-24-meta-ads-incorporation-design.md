# Meta Ads Incorporation — Design Doc

**Sprint family:** M.1 – M.25 (Meta Ads platform parity with Google Ads)
**Author:** Wellington Ribeiro + Claude (brainstorming session 2026-05-24)
**Status:** Approved, pronto pra writing-plans phase
**Estimativa:** ~25 sprints, ~3-6 meses (~75-125 dias úteis)

---

## 0. Contexto e motivador

V4 Ads MCP hoje é Google Ads only — 57 tools em produção, 37 sprints (3b.1 → 3b.37), 4+ meses de uso interno por Wellington (dogfood). Sucesso da arquitetura provou: gestores pedem em PT-BR via Claude/Codex/Cursor → executa via tools curadas com governance (audit_log, rate_limit, always-CONFIRM em mutates de blast radius alto). Substituiu Supermetrics.

**Motivador desta sprint family:** o MCP oficial da Meta (lançado Out/2025) tem limitações **e** não conecta via Codex. V4 precisa de implementação nativa Meta, sob mesmo padrão de governança, que funcione em Claude + Codex + Cursor pra os 3+ colaboradores futuros da V4 Lima Soares & Co (João Pessoa, PB).

**Decisão estratégica:** replicar arquitetura Google Ads em paralelo para Meta. Naming `meta_*` prefix em tools Meta; Google tools mantêm nomes sem prefix (zero breaking change pros workflows existentes).

**Escopo V0:** paridade quase total com Google Ads (~45 tools Meta planejadas — reads, audits, mutates, audiences, conversions, lookalike). Cortes deliberados: search terms / keywords (não aplicáveis), recommendations (API instável), conversion value rule sets (semântica muito diferente).

---

## 1. Architecture Overview

**Princípio diretor:** Meta como plano paralelo à camada Google Ads, reusando tudo que for genérico (governance, registry, MCP transport, web auth, audit_log) e duplicando o que for plataforma-específico (SDK, queries, OAuth flow).

```
src/
├── google_ads/           ← existe hoje (intocado)
│   ├── client.py
│   ├── reports.py
│   ├── queries/
│   └── mutates/
│
├── meta_ads/             ← NOVO (paralelo)
│   ├── client.py         ← factory facebook_business SDK
│   ├── reports.py        ← run_meta_insights() executor
│   ├── insights/         ← Meta Insights API builders (paralelo a queries/)
│   ├── mutates/          ← Meta mutation builders
│   ├── enum_to_label.py  ← Meta enum → label string
│   └── errors.py         ← Meta error → friendly PT-BR
│
├── mcp/tools/            ← REUSA registry (auto-discovery)
│   ├── get_campaign_performance.py    ← Google (intocado)
│   ├── meta_get_campaign_performance.py  ← NOVO
│   ├── _meta_common.py   ← helpers Meta-specific (date_preset, coerções)
│   └── ...
│
├── auth/
│   ├── oauth.py          ← Google (intocado)
│   └── meta_oauth.py     ← NOVO (routes /oauth/meta/*)
│
├── governance/           ← REUSA tudo (rate_limit, dry_run, audit_log)
└── db/repositories/
    ├── google_oauth_connections.py   ← intocado
    ├── meta_oauth_connections.py     ← NOVO
    ├── google_ads_accounts.py        ← intocado
    ├── meta_ad_accounts.py           ← NOVO
    └── manager_meta_account_access.py ← NOVO
```

**O que NÃO muda:**
- `_registry.py` decorator pattern (já agnóstico)
- `src/mcp/server.py` (todas tools passam pelo mesmo Server + StreamableHTTPServerTransport)
- `audit_log`, `rate_counters`, `pending_confirmations` tabelas (com pequeno ALTER para `platform` column)
- `src/mcp/context.py` (manager_id + session_id genéricos)
- Webapp shell, Tailwind, HTMX, login/admin paths

**O que muda na webapp:**
- `/oauth/meta/start` + `/oauth/meta/callback` (paralelos a `/oauth/google/*`)
- Admin page `/admin/connections` mostra ambas conexões per manager (status Google + Meta + ações)
- Help page documenta tools Meta com prefix

**O que muda em CLAUDE.md:**
- Tagline: "V4 Ads MCP conecta Google Ads + Meta Ads accounts..."
- Stack: adiciona `facebook-business>=21.0.0`
- "Current state": nova subseção Meta com sprints M.1-M.X
- "Read these first": inclui specs Meta + smoke runbooks `phase-M-*`
- "Don't do": adiciona convenções Meta-specific (global API state, token expiration)

**Custo arquitetural:** ~40% duplicação code-wise (client/reports/error mapping), mas zero risco de quebrar Google. ~0% duplicação em governance/registry/tests pattern.

---

## 2. DB Schema

Migration nova: `003_meta_schema.sql`. Append-only — não toca migrations 001/002 existentes. Migration follow-up: `004_audit_log_provider_id.sql` para rename minor.

### Novas tabelas (003_meta_schema.sql)

```sql
-- meta_oauth_connections: 1 conexão Meta por (manager, fb_user_id)
CREATE TABLE meta_oauth_connections (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    manager_id            UUID NOT NULL REFERENCES managers(id) ON DELETE CASCADE,
    fb_user_id            TEXT NOT NULL,              -- Facebook user numeric ID
    fb_email              TEXT NOT NULL,
    access_token_enc      BYTEA NOT NULL,             -- long-lived token cifrado (~60d)
    token_expires_at      TIMESTAMPTZ NOT NULL,       -- Meta retorna expires_in
    scopes                TEXT[] NOT NULL,            -- ads_management, ads_read, business_management
    connected_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at            TIMESTAMPTZ,
    UNIQUE (manager_id, fb_user_id)
);

-- meta_ad_accounts: ad accounts visíveis pra V4 (sync via /me/adaccounts)
CREATE TABLE meta_ad_accounts (
    ad_account_id     TEXT PRIMARY KEY,               -- e.g., "act_123456789"
    business_id       TEXT,                           -- BM ID dono (NULL = personal)
    business_name     TEXT,
    account_name      TEXT NOT NULL,
    currency          TEXT,                           -- BRL, USD, etc
    timezone_name     TEXT,                           -- e.g., "America/Sao_Paulo"
    account_status    INT,                            -- 1=ACTIVE, 2=DISABLED, etc (Meta enum)
    is_active         BOOLEAN NOT NULL DEFAULT true,
    synced_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- manager_meta_account_access: M:N entre manager e meta ad accounts
CREATE TABLE manager_meta_account_access (
    manager_id        UUID NOT NULL REFERENCES managers(id) ON DELETE CASCADE,
    ad_account_id     TEXT NOT NULL REFERENCES meta_ad_accounts(ad_account_id) ON DELETE CASCADE,
    access_level      TEXT NOT NULL DEFAULT 'write',
    granted_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    granted_by        UUID REFERENCES managers(id),
    PRIMARY KEY (manager_id, ad_account_id),
    CONSTRAINT mmaa_access_level_check CHECK (access_level IN ('read', 'write'))
);

-- meta_rate_counters: tracks Meta API throttling per (app, account, day)
CREATE TABLE meta_rate_counters (
    app_id            TEXT NOT NULL,                  -- Meta App ID (hashed)
    ad_account_id     TEXT NOT NULL,                  -- pra BUC tracking
    date              DATE NOT NULL,
    calls_used        INT NOT NULL DEFAULT 0,
    last_throttle_pct INT NOT NULL DEFAULT 0,         -- último X-Business-Use-Case-Usage %
    PRIMARY KEY (app_id, ad_account_id, date)
);

-- audit_log + pending_confirmations: adiciona platform pra disambiguar
ALTER TABLE audit_log
    ADD COLUMN platform TEXT NOT NULL DEFAULT 'google';
CREATE INDEX idx_audit_platform_time ON audit_log (platform, occurred_at DESC);

ALTER TABLE pending_confirmations
    ADD COLUMN platform TEXT NOT NULL DEFAULT 'google';
```

### Migration follow-up (004_audit_log_provider_id.sql)

```sql
-- Rename pra clareza multi-platform
ALTER TABLE audit_log RENAME COLUMN google_request_id TO provider_request_id;
```

### Decisões deliberadas no schema

| Decisão | Por quê |
|---|---|
| Campo `access_token_enc` (Meta) em vez de `refresh_token_enc` (Google) | Meta não tem refresh_token padrão. Long-lived token expira ~60 dias → webapp UI pede reconectar. |
| `token_expires_at` NOT NULL | Pra job background avisar gestor antes de expirar (V1). |
| `meta_rate_counters` separado de `rate_counters` | Modelos de quota muito diferentes (Meta BUC granular per ad_account; Google developer_token global). |
| `account_status INT` | Meta retorna enum int (1=ACTIVE, 2=DISABLED, 3=UNSETTLED, 7=PENDING_RISK_REVIEW, etc). Mantém raw + interpreta no app. |
| `business_id` NULL allowed | Ad account "personal" (sem BM) é raro em V4, mas legal Meta. |
| `platform` column em audit_log + pending_confirmations | Permite admin filtrar e relatórios "audit log Meta vs Google" sem JOINs complexos. |
| `provider_request_id` rename | Coluna Google-named em rows Meta é confuso. Rename safe (read-side only). |

### Repositories novos

```
src/db/repositories/
├── meta_oauth_connections.py    ← upsert, get_active_for_manager, revoke
├── meta_ad_accounts.py          ← upsert_many (sync), get_by_id, list_for_manager
└── manager_meta_account_access.py ← grant, revoke, list_for_manager
```

Cada repository segue padrão estabelecido em `google_oauth_connections.py` (asyncpg raw SQL, dataclass frozen+slots, _row_to_X helpers).

---

## 3. OAuth Flow Meta

### Routes novas em `src/auth/meta_oauth.py`

```
GET  /oauth/meta/start          → redirect pra Meta consent (state HMAC-signed)
GET  /oauth/meta/callback       → exchange code → token → upsert connection → sync accounts
POST /oauth/meta/revoke         → flag revoked_at + opcionalmente revogar no Meta (DELETE /me/permissions)
```

Webapp `/admin/connections` lista ambas Google + Meta conexões por gestor + botões "Conectar Google" / "Conectar Meta" / "Reconectar" / "Revogar".

### Scopes V0

```python
META_REQUIRED_SCOPES = [
    "email",                  # standard
    "public_profile",         # standard
    "ads_read",               # App Review obrigatório
    "ads_management",         # App Review obrigatório
    "business_management",    # App Review obrigatório
]
```

**Granular permissions:** Meta permite usuário aceitar só algumas scopes no consent. Callback DEVE checar `granted_scopes` no response e bloquear se faltar `ads_read` ou `ads_management`. UX: mostrar "Você não concedeu permissão X — reconecte e marque todas as opções".

### Token model Meta (diferente de Google)

```
Step 1: callback recebe `code` short-lived (~10 min validity)
Step 2: exchange code → short-lived access_token (~1-2h)
        POST /v22.0/oauth/access_token?code=...&client_id=...&client_secret=...
Step 3: exchange short-lived → long-lived access_token (~60 dias)
        GET /v22.0/oauth/access_token?grant_type=fb_exchange_token
            &client_id=...&client_secret=...&fb_exchange_token=<short_lived>
Step 4: cifra long-lived com AES master key (reusa src.auth.tokens)
Step 5: persiste em meta_oauth_connections com token_expires_at
Step 6: chama GET /me/adaccounts → upsert em meta_ad_accounts + manager_meta_account_access
```

### Token refresh / re-auth (sem flow automático V0)

Meta **não tem refresh_token padrão**. Estratégia:

- **Reactive (V0):** quando tool MCP chama API e recebe `OAuthException` com `error_subcode=458/467` (expired/invalid), retorna PT-BR amigável: "Sua conexão Meta expirou. Acesse o painel admin e clique em 'Reconectar Meta'."
- **Proactive (V1):** job background diário (`src/jobs/meta_token_refresh.py`) lista conexões com `token_expires_at - now() < 7 days`, tenta `GET /me?access_token=X`, extend via `?grant_type=fb_exchange_token`. Se expirado: flag + email banner pro gestor.

V0 ship apenas Reactive (custo baixo, sem cron novo).

### State validation

Reusa `src.auth.oauth_state` (já é genérico) — só muda `aud` no HMAC pra `"meta_oauth"`.

### App Review timing

- **M.1:** cria Meta App em Business Manager V4 Lima Soares & Co, configura Facebook Login product, define Privacy Policy URL + Terms URL (reusa páginas legais existentes). App fica em Development Mode.
- **M.2:** submete App Review request pra `ads_read`, `ads_management`, `business_management`. Screencast mostra uso interno V4. Estimativa Meta: 3-10 dias úteis.
- **Enquanto review pendente:** Wellington + 3 colaboradores usam o app em Development Mode (até 25 app admins/devs sem review).
- **Quando aprovar:** flip pra Live Mode.

---

## 4. Meta SDK Integration

### Library

```
facebook-business>=21.0.0   (Meta official Python SDK, ativo, segue Graph API versions)
```

Add to `pyproject.toml` deps. Não substitui google-ads — coexistem.

### `src/meta_ads/client.py` — factory

```python
async def build_meta_api_for_manager(*, manager_id: UUID) -> FacebookAdsApi:
    """Initialize Meta SDK with manager's long-lived access_token.

    Decrypts access_token from meta_oauth_connections, calls
    FacebookAdsApi.init() with app_id/app_secret/access_token.
    """
    from facebook_business.api import FacebookAdsApi  # noqa: PLC0415

    settings = get_settings()
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        oc = await meta_oauth_connections.get_active_for_manager(conn, manager_id)
    if oc is None:
        raise NoMetaConnectionError(
            "Gestor não tem conexão Meta Ads ativa. "
            "Acesse o painel admin → 'Conectar Meta'."
        )
    if oc.token_expires_at <= datetime.now(UTC):
        raise MetaTokenExpiredError(
            "Sua conexão Meta expirou. Reconecte via painel admin."
        )

    master_key = derive_master_key_from_settings(settings.aes_master_key)
    access_token = decrypt_oauth_token(oc.access_token_enc, master_key)

    return FacebookAdsApi.init(
        app_id=settings.meta_app_id,
        app_secret=settings.meta_app_secret,
        access_token=access_token,
        api_version="v22.0",
    )
```

**Diferença vs Google:** Meta SDK usa global state (`FacebookAdsApi.set_default_api(api)`) por default — perigoso em async multi-manager. **Solução:** sempre passar `api=` explicit pra cada SDK call (e.g., `AdAccount(act_id, api=api).get_campaigns(...)`). Convenção codificada em todos os builders.

### `src/meta_ads/reports.py` — Insights executor

```python
async def run_meta_insights(
    *,
    manager_id: UUID,
    session_id: UUID,
    ad_account_id: str,                    # "act_123..."
    level: Literal["account", "campaign", "adset", "ad"],
    fields: list[str],                     # ["spend", "impressions", "clicks", "ctr"]
    breakdowns: list[str] | None = None,   # ["age", "gender", "country"]
    time_range: dict[str, str] | None = None,  # {"since": "2026-05-01", "until": "2026-05-21"}
    date_preset: str | None = None,        # "last_7d", "last_30d", etc
    filtering: list[dict] | None = None,
    row_formatter: Callable[[dict], dict[str, Any]],
    operation_name: str,
    estimated_calls: int = 1,
    audit_this_call: bool = False,
    params_summary: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Run Meta Insights com paginação automática.

    Mirror semantics of run_report (Google): rate_limit before/after, audit opt-in,
    PT-BR errors, paginação cursor-based até esgotar.
    """
```

### Quirks específicos Meta a tratar

| Quirk | Tratamento |
|---|---|
| **Insights pode ser async** (response vem por job polling) | V0: sempre **sync** (`async=False`). Aceita timeouts em range >90 dias. V1: detecta range grande → submete `async=True` + polling. |
| **Paginação cursor obrigatória** | `for ad in adaccount.get_ads()` é generator que pagina sozinho. Wrappar com counter + early-break se MAX_ROWS excedido. |
| **Rate limits BUC headers** | Cada response tem header `X-Business-Use-Case-Usage` (JSON). Parsear pra atualizar `meta_rate_counters.last_throttle_pct` + structlog alert se >75%. |
| **Field validation upfront** | Meta retorna 400 se field não existir pra level. Helper `validate_insights_fields(level, fields)` em `src/meta_ads/insights/validate.py` com whitelist por level. |
| **Date_preset vs time_range mutex** | Tool input schema aceita um OU outro, helper `resolve_meta_date_window` em `_meta_common.py`. |
| **Enum returns como int cru** | `account_status=1` em vez de `'ACTIVE'`. Helpers `enum_to_label.py` traduzem. |
| **Object IDs prefix** | `act_123` (ad account), `act_123/123_456` (campaign full path). Helper `parse_meta_id()`. |
| **Tokens em logs** | NUNCA logar access_token. Strict redaction em todos os structlog calls. |

### `src/meta_ads/mutates/_common.py` — pre-flight + builders convention

Paralelo a `src/google_ads/mutates/_common.py`:
- Helper validators (e.g., `validate_meta_campaigns_exist`)
- Pre-flight pattern: GET antes de mutate pra confirmar entity existe
- Dispatcher pattern pra batch mutations
- Convenção: builders retornam dicts (Meta SDK usa native dicts) — substituí `ProtoFieldCapture` por `MetaCaptureClient` em tests

### Error mapping — `src/meta_ads/errors.py`

```python
def to_friendly_meta_error(e: Exception) -> MetaAdsFriendlyError:
    """Mapeia exceções Meta SDK pra mensagens PT-BR amigáveis."""
    if isinstance(e, FacebookRequestError):
        subcode = e.api_error_subcode()
        if subcode in (458, 467):
            return MetaAdsFriendlyError(
                "Sua conexão Meta expirou. Reconecte via painel admin.",
                retryable=False)
        if subcode == 2635:
            return MetaAdsFriendlyError(
                "Limite Meta atingido. Tente novamente em alguns minutos.",
                retryable=True)
        code = e.api_error_code()
        if code == 190:
            return MetaAdsFriendlyError(
                "Permissão insuficiente. Peça admin atualizar scopes.",
                retryable=False)
        if code == 100:
            return MetaAdsFriendlyError(
                "Campo inválido para o nível solicitado.",
                retryable=False)
    return MetaAdsFriendlyError(f"Erro Meta API: {e}", retryable=False)
```

---

## 5. Tool Layout & Registry

### Filesystem layout

```
src/mcp/tools/
├── (Google — 57 tools intocadas)
│
├── meta_list_my_ad_accounts.py
├── meta_get_account_overview.py
├── meta_get_campaign_performance.py
├── meta_get_ad_set_performance.py
├── meta_get_ad_performance.py
├── meta_get_audience_performance.py
├── meta_get_geo_performance.py
├── meta_get_device_performance.py
├── meta_get_hourly_performance.py
├── meta_get_funnel_metrics.py
├── meta_get_budget_pacing.py
├── meta_get_top_creatives.py
├── meta_get_change_history.py
├── meta_get_conversion_events.py
│
├── meta_get_pages_for_business.py       ← Meta-specific superpower
├── meta_get_pixel_diagnostics.py        ← Meta-specific superpower
│
├── meta_update_campaign_status.py
├── meta_update_ad_set_status.py
├── meta_update_ad_status.py
├── meta_update_campaign_budget.py
├── meta_update_ad_set_budget.py
├── meta_update_ad_set_bid.py
├── meta_update_campaign_bid_strategy.py
├── meta_create_campaign.py
├── meta_create_ad_set.py
├── meta_create_ad.py
├── meta_create_creative.py
├── meta_apply_audience.py
├── meta_remove_audience.py
├── meta_create_custom_audience.py
├── meta_create_lookalike_audience.py    ← Meta-specific
├── meta_upload_custom_audience_users.py
├── meta_upload_offline_conversions.py
├── meta_create_custom_conversion.py
├── meta_update_custom_conversion.py
├── meta_add_negative_targeting.py
├── meta_remove_negative_targeting.py
├── meta_bulk_pause_by_filter.py
├── meta_apply_change.py                 ← router branch
│
├── meta_audit_zombie_ads.py
├── meta_audit_orphan_pixels.py
├── meta_audit_goal_attribution.py
├── meta_audit_delivery_health.py
├── meta_detect_drift.py
│
├── _meta_common.py                      ← helpers Meta-specific
```

### Registry behavior — ZERO mudança

`_registry.py` já é decorator + auto-discovery via `pkgutil.iter_modules`. Novas tools Meta são descobertas automaticamente quando os módulos forem criados.

### Mapeamento Google ↔ Meta planned

Subconjunto: tools Google sem equivalente Meta (skip):
- `get_search_terms_report`, `get_keyword_performance`, `add_keywords`, `update_keyword_*`, `add_negatives_from_search_terms` — Meta não é search engine
- `run_gaql`, `validate_gaql`, `list_gaql_resources` — Meta usa Graph API REST, sem query language
- `audit_competitor_keywords` — N/A
- `get_recommendations`, `create_conversion_value_rule_set` — V1 candidates (API limitada / semântica diferente)

Subconjunto: tools modificadas (adicionam `platform` param):
- `get_my_audit_log` — `platform: "google"|"meta"|"all"` (default "all")
- `get_my_rate_limit_status` — retorna dict com keys "google" e "meta"

Mapeamento full Google ↔ Meta refinado nos plans individuais por sprint (cada sprint M.X declara explicitamente quais tools Google espelha).

### Schema convention para Meta tools

```python
{
    "type": "object",
    "required": ["ad_account_id"],
    "properties": {
        "ad_account_id": {"type": "string", "pattern": "^act_\\d+$"},
        "date_preset": {
            "type": "string",
            "enum": ["today", "yesterday", "last_7d", "last_14d", "last_28d",
                     "last_30d", "last_90d", "this_month", "last_month",
                     "this_quarter", "last_quarter", "this_year", "last_year"],
            "description": "Use date_preset OU (since+until), nunca ambos."
        },
        "since": {"type": "string", "pattern": "^\\d{4}-\\d{2}-\\d{2}$"},
        "until": {"type": "string", "pattern": "^\\d{4}-\\d{2}-\\d{2}$"},
        "fields": {
            "type": "array",
            "items": {"type": "string"},
            "default": ["campaign_name", "spend", "impressions", "clicks",
                        "ctr", "cpc", "actions", "cost_per_action_type"]
        },
        "breakdowns": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Opcional. Ex: ['age','gender']. Aumenta cardinalidade."
        },
        "limit": {"type": "integer", "minimum": 1, "maximum": 500, "default": 100}
    },
    "additionalProperties": False
}
```

**Sem oneOf/allOf/anyOf** (3b.19B.1 convention). Cross-field constraints em `_validate_meta_date_window()` helper privado.

---

## 6. Governance Reuse

### Reuso total (zero código novo)

| Componente | Localização | Como reusa |
|---|---|---|
| MCP transport | `src/mcp/server.py` | Tools Meta passam pelo mesmo `build_server()`. |
| Tool registry | `src/mcp/tools/_registry.py` | `@register_tool` decorator agnóstico + auto-discovery. |
| Per-request context | `src/mcp/context.py` | `manager_id` + `session_id` válidos pra ambas. |
| Auth Bearer + session | `src/mcp/session.py` | Mesma Bearer Token funciona pra Google + Meta tools. |
| Pending confirmations | `src/db/repositories/pending_confirmations.py` | `payload jsonb` agnóstico. Schema só adiciona `platform`. |
| AES encryption | `src/auth/tokens.py` | `encrypt_*` / `decrypt_*` são bytes→bytes. Renomeia internamente para clareza. |
| OAuth state HMAC | `src/auth/oauth_state.py` | Já genérico — passar `aud="meta_oauth"`. |
| Domain allowlist | `src/auth/domain_check.py` | `@v4company.com` check vale pra ambas. |
| Panel session | `src/auth/panel_session.py` | Login painel único — gestor conecta Google + Meta separadamente. |
| Settings/secrets | `src/config.py` | Adiciona `meta_app_id`, `meta_app_secret`. |

### Adaptações pontuais

| Componente | Mudança |
|---|---|
| `src/governance/rate_limit.py` | Funções `before_call_meta()` + `record_actual_meta()` que escrevem em `meta_rate_counters`. |
| `src/governance/dry_run.py` | `make_confirmation_token(operation_type, payload, platform)` aceita platform. |
| `src/db/repositories/audit_log.py` | `record()` aceita `platform: Literal["google","meta"]` (default "google"). |
| `src/mcp/tools/get_my_audit_log.py` | Schema ganha optional `platform` param. Filtra SQL. |
| `src/mcp/tools/get_my_rate_limit_status.py` | Retorna dict com keys "google" e "meta". |
| `src/mcp/tools/apply_change.py` | Router branch detect `platform` from `pending_confirmations` → dispatcha pra handler correto. |

### CONFIRM flow — paralelo, sem unificar

```python
async def handle_apply_change(args):
    token = args["confirmation_token"]
    confirmation = await get_pending_confirmation(token)
    if confirmation.platform == "google":
        return await dispatch_google_mutation(confirmation)
    elif confirmation.platform == "meta":
        return await dispatch_meta_mutation(confirmation)
```

Mutations Meta retornam token via `meta_apply_change` semantically idêntico ao Google flow.

### Audit log — schema unificado

`audit_log.record()` chamado por Meta tools com:
- `customer_id` = ad_account_id (e.g., "act_123456789")  ← reusa coluna
- `action_type` = "mutate" / "read" / "auth" / "system"  ← mesmas constants
- `platform` = "meta"
- `provider_request_id` = `x-fb-trace-id` header

### Rate limit — quotas separadas

V0 estratégia simplificada:
- `meta_rate_counters` armazena per `(app_id, ad_account_id, date)`
- **Sem pre-flight Meta** (caro). Confia em response headers post-call.
- Pós-cada-call: parse `X-Business-Use-Case-Usage` header, atualiza `last_throttle_pct`, structlog alert se >75%.

V1: pre-flight throttle prediction baseado em rolling window.

### Helpers compartilhados

| Helper | Reuso direto? |
|---|---|
| `src.mcp.tools._common.resolve_date_window` | ❌ Não — semântica diferente. Cria paralelo. |
| `src.mcp.tools._common.parse_date_range` | ❌ idem. |
| `src.mcp.tools._common.coerce_*` (input coercion) | ✅ Reuso direto. |

---

## 7. Roadmap (25 sprints)

### Foundation (2 sprints — SEM tool exposta)

| Sprint | Entrega |
|---|---|
| **M.1** | Migrations `003_meta_schema.sql` + `004_audit_log_provider_id.sql` + repositories Meta + Meta App criado em BM V4 Lima Soares & Co (Development Mode) + secrets `meta_app_id`/`meta_app_secret` em Secret Manager + privacy policy URL public. |
| **M.2** | OAuth flow Meta (`src/auth/meta_oauth.py` + routes + webapp UI) + Meta SDK integration (`src/meta_ads/client.py` + `reports.py`) + 2 tools (`meta_list_my_ad_accounts` + `meta_get_account_overview`) + smoke runbook + **submeter Meta App Review** pra `ads_read`+`ads_management`+`business_management`. |

### Read tools (8 sprints, 2-3 tools cada)

| Sprint | Tools | Google equivalentes |
|---|---|---|
| **M.3** | `meta_get_campaign_performance`, `meta_get_ad_set_performance`, `meta_get_ad_performance` | get_campaign_performance, get_ad_group_performance, get_ad_performance |
| **M.4** | `meta_get_geo_performance`, `meta_get_device_performance`, `meta_get_hourly_performance` | idem |
| **M.5** | `meta_get_audience_performance`, `meta_get_top_creatives` | get_audience_performance, get_top_keywords_creatives |
| **M.6** | `meta_get_budget_pacing`, `meta_get_funnel_metrics` | idem |
| **M.7** | `meta_get_change_history`, `meta_get_conversion_events` | get_change_history, get_conversion_actions |
| **M.8** | `meta_get_pages_for_business`, `meta_get_pixel_diagnostics` | (Meta-specific) |
| **M.9** | `meta_bulk_pause_by_filter` (read+dry-run preview) | bulk_pause_by_query (read-side only) |
| **M.10** | `get_my_audit_log` + `get_my_rate_limit_status` Meta-aware (mods de existentes) | (modificação) |

### Audits Meta (5 sprints)

| Sprint | Tools |
|---|---|
| **M.11** | `meta_audit_zombie_ads` (ads com 0 impressões em 30d) |
| **M.12** | `meta_audit_orphan_pixels` (Pixel events sem conversões 30d) |
| **M.13** | `meta_audit_goal_attribution` (Custom Conversions vs Standard Events parity) |
| **M.14** | `meta_audit_delivery_health` (auction lost, learning phase stuck, frequency cap) |
| **M.15** | `meta_detect_drift` (auto-apply + multi-user em activities log) |

### Mutates light → heavy (7 sprints)

| Sprint | Tools |
|---|---|
| **M.16** | `meta_update_campaign_status`, `meta_update_ad_set_status`, `meta_update_ad_status` + apply_change router branch |
| **M.17** | `meta_update_campaign_budget`, `meta_update_ad_set_budget` (CBO + ABO) |
| **M.18** | `meta_update_ad_set_bid`, `meta_update_campaign_bid_strategy` |
| **M.19** | `meta_create_campaign` (objectives whitelist + per-value smoke) |
| **M.20** | `meta_create_ad_set` (targeting + budget + schedule) |
| **M.21** | `meta_create_ad` + `meta_create_creative` (image_hash/video_id upload) |
| **M.22** | `meta_bulk_pause_by_filter` (execute branch + dry-run mature) + polish apply_change Meta |

### Audiences + conversions (3 sprints)

| Sprint | Tools |
|---|---|
| **M.23** | `meta_apply_audience`, `meta_remove_audience`, `meta_create_custom_audience` |
| **M.24** | `meta_create_lookalike_audience` + `meta_upload_custom_audience_users` (SHA-256 hashing) |
| **M.25** | `meta_upload_offline_conversions` + `meta_create_custom_conversion` + `meta_update_custom_conversion` |

### Gates de qualidade por sprint

Cada sprint Meta segue padrão estabelecido (Sprint 3b.27+):
1. Brainstorming + spec doc
2. Plano (writing-plans skill)
3. Subagent-driven execution (haiku/sonnet/opus per task complexity)
4. 2-stage code review (spec compliance + mcp-tool-quality-reviewer)
5. Smoke runbook (`smoke-runbook-generator` subagent)
6. Pre-push gate (`check_pre_push.py` 5/5 PASS; full sweep pra mutates)
7. CI + Deploy green
8. Smoke real Wellington (conta V4 Lima Soares & Co Meta)
9. Signoff (CLAUDE.md + findings-catalog se F-finding novo + sprint-history.md)

### Tempo total estimado

25 sprints × 3-5 dias = ~75-125 dias úteis = **3-6 meses**. App Review Meta: paralelo, ~3-10 dias úteis após M.2 submit.

---

## 8. Testing Strategy

### Padrões reusados direto

| Padrão | Reuso |
|---|---|
| Pure module + boundary parser separation | Mirror em `src/meta_ads/<pure_module>.py`. Zero SDK imports → testáveis standalone. |
| Schema regression guards | `tests/unit/test_no_composition_keywords_in_any_schema.py` recursive — pega Meta tools auto. |
| Date range schema explicit | Adapt: validar Meta tools tem `date_preset` + `since`/`until` corretamente. |
| Schema enum coverage | Mesma convenção (3b.19A.1) — per-value probe em smoke runbook pra Meta enums. |

### MetaCaptureClient (paralelo a ProtoFieldCapture)

```python
# tests/unit/fixtures/meta_capture.py
class MetaCaptureClient:
    """Intercepta api_create/api_update/api_get calls em testes.

    Replaces facebook_business SDK calls com gravação dict + retorno mock.
    Validates payload exato sendo enviado para Meta API.
    """
    def __init__(self):
        self.calls: list[CapturedCall] = []

    def capture(self, *, endpoint: str, method: str, payload: dict) -> dict:
        self.calls.append(CapturedCall(endpoint=endpoint, method=method, payload=payload))
        return {"id": "mock_id"}

    def field(self, call_idx: int, path: str) -> Any:
        """Dot-notation field lookup em call payload."""
        ...

    def has(self, call_idx: int, path: str) -> bool:
        """Returns True iff path exists em payload."""
        ...
```

**Convenção:** todos builders Meta MUST usar `MetaCaptureClient` em tests. **Nunca MagicMock** (F16/F42/F44 lições).

### Pre-flight test convention Meta

Mesmo padrão Sprint 3b.5/3b.8 — mock no namespace **da tool**, não do helper.

### Enum mapping tests

```python
def test_parse_account_status_handles_int_to_label():
    """Regression guard: Meta retorna 1, parser traduz pra 'ACTIVE'."""
    fake_row = {"account_status": 1, ...}
    result = dict_to_meta_account_row(fake_row)
    assert result["account_status"] == "ACTIVE"
```

### Integration tests com `respx`

```python
@pytest.mark.integration
async def test_meta_get_campaign_performance_happy_path(respx_mock):
    respx_mock.get("https://graph.facebook.com/v22.0/act_123/insights").respond(
        200, json={"data": [...], "paging": {"cursors": {...}}}
    )
    # call tool handler, assert structured response
```

Reusa `respx` infra que já roda em outras integration tests Google.

### Smoke runbook pattern Meta

Mesma estrutura `docs/operacao/phase-M-XX-bootstrap.md` (paralelo a `phase-3b-XX`):
- T1: smoke happy path
- T2: edge case
- T3: error path
- T4 (mutates): dry-run preview
- T5 (mutates): confirm + execute
- T6 (mutates): pre-flight detection
- T7+: per-value enum probes

`smoke-runbook-generator` subagent updated em M.1 pra entender prefixo `meta_*`.

### CI gates

Mesmo `scripts/check_pre_push.py` 5/5 PASS. Steps 1-4 pegam Meta auto. Step 5 (integration sem DB) idem. Full sweep `check_pre_push_full.py` mandatory pra mutate-touching changes.

### Quality reviewer subagent

`mcp-tool-quality-reviewer` updated em M.1 pra entender bug classes Meta:
- Global API state contamination (sempre `api=`)
- Long-lived token expiration handling
- Pagination cursor exhaust correctness
- BUC rate limit header parsing
- Granular permission validation no callback

### Findings catalog

`docs/operacao/findings-catalog.md` cresce com F47, F48... (sem prefixar M.X — continuidade Google + Meta).

---

## 9. Open Questions & Risks

### Decisões deliberadamente adiadas (V1+)

| Decisão | Por que não V0 |
|---|---|
| **Async Insights jobs** | Sync cobre 95% dos casos. Async adiciona polling + report_run_id state. |
| **Proactive token refresh job** | V0 reactive (erro PT-BR pede reconectar). Cron job daily só vale com 10+ conexões. |
| **Cross-platform aggregate reports** | "Gasto total Google+Meta últimos 7d" precisa view DB ou tool nova. Validar demanda real. |
| **Pre-flight throttle prediction Meta** | V0 post-call accounting. Pre-flight pra Meta exige predict — complexo. |
| **`meta_get_recommendations`** | Meta "Opportunity Score" tem API limitada e instável. Watch. |
| **`meta_create_conversion_value_rule_set`** | Semântica muito diferente de Google — investigar separado. |
| **Bulk operations Meta Batch API** | Útil pra mass mutates (até 50 ops/call). V1 candidate. |

### Riscos conhecidos + mitigação

| Risk | Prob. | Impacto | Mitigation |
|---|---|---|---|
| Meta App Review reject inicial | Média | Alto | Screencast + privacy policy + caso "internal tool only". Development Mode permite uso até 25 admins. |
| Meta Graph API breaking changes | Baixa | Médio | Pin `api_version="v22.0"`. Re-test trimestral. |
| `facebook-business` SDK quirks late | Média | Médio | M.2 valida pipeline ponta-a-ponta antes de invest mais sprints. Fallback: raw httpx. |
| Insights API timeout >90d | Alta | Médio | V0 enforce range max 90d em schema. V1 async jobs. |
| 3 colaboradores nunca migrarem | Média | Alto | Validar após M.10. Se zero conexões, parar mutates Meta. |
| Custos Cloud Run subirem | Baixa | Baixo | Cloud Run free-tier-friendly em volume V4. Monitor billing pós-M.10. |
| Wellington sem tempo pra smoke real | Média | Alto | Smoke sintético quando possível. Smoke real só pra mutates alto blast radius. |
| UX multi-platform confuso | Média | Médio | Help page clara: "Use prefix meta_ para Meta, sem prefix para Google". |
| Meta App quota Development Mode apertada | Média | Alto | Validar com 1 tool em M.2 antes de scale. |

### Dependências externas

| Dependência | Owner | Timing |
|---|---|---|
| Meta App em BM V4 Lima Soares & Co | Wellington (admin BM) | M.1 |
| Meta App Review aprovado (ads_read+ads_management+business_management) | Meta Review team | M.2 submit → ~3-10 dias úteis |
| Secrets `meta_app_id` + `meta_app_secret` em Secret Manager | Wellington (admin GCP) | M.1 |
| Privacy Policy + Terms URLs públicos | Wellington / Web dev | M.1 |
| Email notif Meta App Review status | Wellington (BM admin email) | M.2 + monitor |

### Convenções novas a estabelecer (CLAUDE.md updates)

- Meta SDK global state warning — sempre `api=` em SDK calls
- Long-lived token expiration check — toda Meta tool valida `token_expires_at` antes de chamar API
- `MetaCaptureClient` em todos builder tests
- `_meta_common.py` parallel a `_common.py` (não unificar)
- Smoke runbook namespace `phase-M-XX-bootstrap.md`

### Pontos de validação pós-V0 (após M.10)

| Métrica | Threshold | Decisão se não bate |
|---|---|---|
| Wellington usou Meta tools em workflow real | ≥3 sessões/semana | Re-avaliar ROI; pause M.11+ |
| Algum dos 3 colaboradores conectou Meta | ≥1 conexão ativa | Continuar full paridade |
| Tools Meta evitaram trip pra Meta Ads Manager UI | ≥50% das tasks Meta | Validar value prop |
| F-findings Meta criados | <5 por sprint | Caminho saudável |
| Smoke runbooks 100% PASS primeira tentativa | ≥80% | Padrão Google replicado bem |

### V1 release criteria

- M.1-M.10 ship + smoke real V4 Lima Soares & Co
- Meta App Review APPROVED (Live Mode)
- 1+ colaborador além Wellington conectou Meta
- Audit log ≥50 chamadas Meta/semana
- Zero F-finding crítico Tier 1 aberto

---

## 10. Pre-V0 checklist (antes de invocar writing-plans)

- [x] Brainstorming completo + design aprovado (todas seções)
- [ ] Spec doc commitado (este arquivo)
- [ ] Wellington review do spec
- [ ] writing-plans skill invocado pra **Sprint M.1 isolado** (NÃO pra família inteira)

### Escopo do writing-plans

writing-plans deve gerar plan **APENAS para Sprint M.1** (foundation: migrations + repositories + Meta App Dev Mode + secrets). Sprints subsequentes M.2 → M.25 ganham seu próprio plan via `/sprint-bootstrap` quando chegar a vez. Razão: este spec é a sprint family strategy doc; planos individuais por sprint mantêm-se enxutos e focados.

---

**Sprint ready to start:** M.1 (foundation — DB schema + Meta App setup, ZERO tool exposed). Estimativa M.1 isolado: ~3-5 dias.
