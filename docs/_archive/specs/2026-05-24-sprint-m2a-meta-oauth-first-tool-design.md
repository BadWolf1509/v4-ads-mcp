# Sprint M.2a — Meta OAuth + SDK + First Tool — Design Doc

**Sprint:** M.2a (parte 1 do Sprint M.2 dividido em M.2a + M.2b)
**Author:** Wellington Ribeiro + Claude (brainstorming session 2026-05-24)
**Status:** Approved, pronto pra writing-plans phase
**Estimativa:** ~2-3 dias úteis

**Companion specs:**
- [Sprint family M design](2026-05-24-meta-ads-incorporation-design.md) (overall roadmap M.1-M.25)
- [Sprint M.1 plan](../plans/2026-05-24-sprint-m1-meta-foundation.md) (foundation predecessor)

---

## 0. Contexto

Sprint M.1 (shipped 2026-05-24) entregou a foundation Meta Ads: 4 DB tables vazias, 3 repositories, 2 settings, Meta App em developers.facebook.com configurado, secrets em GCP, env vars Cloud Run. **ZERO MCP tools ainda.**

Sprint M.2a fecha o gap "foundation → first tool ponta-a-ponta funcional": OAuth flow Meta + SDK integration + primeira tool MCP (`meta_list_my_ad_accounts`) + 5 prep tasks descobertas em M.1 final review.

**Princípio diretor:** pipeline ponta-a-ponta validado em **uma única sprint** (~2-3 dias). Risco arquitetural matado cedo (OAuth Meta quirks + SDK global state issue). Segunda tool (M.2b) vira template + adapt.

**Sprint M.2b** (próximo, ~1-2 dias) entrega: `meta_get_account_overview` + endpoint data-deletion-callback + UI polish + Wellington manual: Meta App Review submit.

---

## 1. Architecture Overview

```
src/
├── auth/
│   └── meta_oauth.py            ← NEW: routes /oauth/meta/{start,callback,revoke}
├── meta_ads/                    ← NEW package (paralelo a google_ads/)
│   ├── __init__.py
│   ├── client.py                ← factory FacebookAdsApi(...) + token expiry guard
│   ├── reports.py               ← run_meta_graph_get() helper
│   └── errors.py                ← FacebookRequestError → PT-BR friendly
├── db/repositories/
│   └── meta_rate_counters.py    ← NEW CRUD
├── governance/
│   └── rate_limit.py            ← +record_actual_meta() (BUC header parsing)
├── mcp/tools/
│   ├── meta_list_my_ad_accounts.py  ← 1ª tool Meta MCP
│   └── _meta_common.py          ← helpers (resolve_meta_date_window stub, parse_meta_id)
└── web/
    ├── routes.py                ← +admin index enrichment (Meta connection card)
    └── templates/admin/
        └── index.html           ← +card "Conexões OAuth" (Google | Meta)

tests/
├── unit/
│   ├── test_meta_oauth.py
│   ├── test_meta_errors.py
│   ├── test_meta_rate_counters_repo.py
│   └── test_buc_header_parsing.py
└── integration/
    ├── test_meta_oauth_flow.py             ← respx mock Meta Graph API
    ├── test_meta_list_my_ad_accounts.py
    ├── test_audit_log_platform.py          ← regression: platform kwarg + provider_request_id column
    └── test_repositories.py                 ← +novos testes meta_rate_counters appended

conftest.py: + META_APP_ID, META_APP_SECRET em _TEST_ENV
pyproject.toml: + facebook-business>=21.0.0
```

### Refactor cross-cutting (separate commit dentro do M.2a)

```
src/db/migrations/004_audit_log_provider_id.sql  ← NEW (RENAME COLUMN)
src/db/repositories/audit_log.py                  ← google_request_id → provider_request_id
50 caller files (22 src + 28 tests, 123 ocorrências)
src/web/templates/audit*.html                     ← display column name update
```

### O que NÃO muda

- `src/google_ads/*` — Google tools intocados (só callers fazem keyword arg rename)
- DB Meta tables M.1 — already shipped
- Settings em config.py — already populated
- MCP server, registry, context — agnostic infra

---

## 2. Foundation prep tasks (5 críticas)

Pré-requisitos pra qualquer Meta tool. Vão nos primeiros commits M.2a.

### Task 1: `audit_log.record()` add `platform` param

```python
# src/db/repositories/audit_log.py
async def record(
    conn,
    *,
    manager_id, session_id, customer_id,
    action_type, operation,
    target_count=None, params_summary=None,
    provider_request_id=None,         # renamed (era google_request_id)
    status="success", error_message=None, duration_ms=None,
    platform: Literal["google", "meta"] = "google",  # NEW
) -> int:
    # INSERT now writes platform column too
    ...
```

Default `"google"` preserva backward compat. Meta tools passam `platform="meta"` explicitamente.

### Task 2: Migration 004 + audit_log.py rename

```sql
-- src/db/migrations/004_audit_log_provider_id.sql
ALTER TABLE audit_log RENAME COLUMN google_request_id TO provider_request_id;
```

Migration roda no Cloud Run Job em deploy. Rename é DDL atômica safe.

### Task 3: 50 caller files rename (big bang)

Estratégia: PowerShell/sed find-replace global:
- `audit_log.record(... google_request_id=X)` → `audit_log.record(... provider_request_id=X)`
- `row["google_request_id"]` → `row["provider_request_id"]`
- Strings em templates HTML

Validação: `python scripts/check_pre_push.py` (mypy strict pega keyword args inválidos + ruff + tests).

### Task 4: `meta_rate_counters` repository CRUD

```python
# src/db/repositories/meta_rate_counters.py
@dataclass(slots=True, frozen=True)
class MetaRateCounter:
    app_id: str
    ad_account_id: str
    date: date
    calls_used: int
    last_throttle_pct: int

async def increment_calls(conn, *, app_id, ad_account_id, date, by=1) -> int
async def update_throttle(conn, *, app_id, ad_account_id, date, throttle_pct) -> None
async def get_counter(conn, *, app_id, ad_account_id, date) -> MetaRateCounter | None
```

Plus 3-4 integration tests appended em `test_repositories.py`.

### Task 5: `conftest.py` `_TEST_ENV` Meta env vars

```python
_TEST_ENV = {
    ...existing...,
    "META_APP_ID": "test_meta_app_123",
    "META_APP_SECRET": "test_meta_secret_dummy_value_long_enough_for_validation",
}
```

Permite tests OAuth Meta importarem `Settings()` sem `ValidationError` em CI.

---

## 3. OAuth Flow Meta

Routes paralelas a `/oauth/google/*` mas semântica diferente (long-lived token + granular permissions).

### `src/auth/meta_oauth.py` — 3 routes

```python
router = APIRouter(prefix="/oauth/meta", tags=["meta_oauth"])

META_REQUIRED_SCOPES = [
    "email", "public_profile",         # standard, sem App Review
    "ads_read", "ads_management",      # App Review required (skip Dev Mode)
    "business_management",
]

@router.get("/start")
async def meta_oauth_start(request, current_user):
    # Sign state HMAC com manager_id + aud="meta_oauth"
    # Redirect to https://www.facebook.com/v22.0/dialog/oauth?...
    ...

@router.get("/callback", name="meta_oauth_callback")
async def meta_oauth_callback(request, code, state, error):
    # 1. Verify state HMAC (manager_id, aud="meta_oauth")
    # 2. Exchange code → short-lived token (~1h) via POST /v22.0/oauth/access_token
    # 3. Exchange short-lived → long-lived (~60d) via GET ?grant_type=fb_exchange_token
    # 4. GET /me?fields=id,email,name → fb_user_id + fb_email
    # 5. CRITICAL: check granted scopes via /debug_token endpoint
    #    Block se faltar ads_read OU ads_management → 302 /access-denied?reason=meta_scopes_missing
    # 6. Encrypt access_token (AES via src.auth.tokens — reuse encrypt_refresh_token)
    # 7. upsert em meta_oauth_connections
    # 8. GET /me/adaccounts → sync upsert em meta_ad_accounts + grant_all_active access
    # 9. audit_log.record(action_type="auth", operation="meta_oauth_connect", platform="meta")
    # 10. Redirect /admin com toast "Meta conectado: <fb_email>"

@router.post("/revoke")
async def meta_oauth_revoke(request, current_user):
    # Soft-revoke: meta_oauth_connections.revoke(connection_id)
    # NÃO chama DELETE /me/permissions no Meta (M.2b polish — Meta API call)
    # audit_log.record(action_type="auth", operation="meta_oauth_revoke", platform="meta")
```

### Force HTTPS no callback

Mesmo workaround do Google (`_build_redirect_uri` força `https://` em Cloud Run que termina TLS no GFE).

### State HMAC

Reuse `src.auth.oauth_state.sign_state` + `verify_state` com `aud="meta_oauth"`. Já genérico.

### Granular permission check

```python
debug_resp = await http.get(
    f"https://graph.facebook.com/v22.0/debug_token"
    f"?input_token={long_lived}&access_token={app_id}|{app_secret}"
)
granted = set(debug_resp["data"]["scopes"])
required_essentials = {"ads_read", "ads_management"}
missing = required_essentials - granted
if missing:
    log.warning("meta_oauth_missing_scopes", missing=list(missing))
    return RedirectResponse(
        f"/access-denied?reason=meta_scopes_missing&missing={','.join(missing)}"
    )
```

### `/access-denied.html` template — caso novo

```jinja2
{% elif reason == 'meta_scopes_missing' %}
  <h1>Permissões Meta incompletas</h1>
  <p>Você não concedeu uma das permissões essenciais durante o consent:</p>
  <ul>
    {% for scope in missing_scopes %}<li><code>{{ scope }}</code></li>{% endfor %}
  </ul>
  <p>Por favor, <a href="/oauth/meta/start">conecte novamente</a> e marque
     TODAS as opções no consent screen do Facebook.</p>
{% endif %}
```

### Mount router em `src/app.py`

```python
from src.auth import meta_oauth
app.include_router(meta_oauth.router)
```

### Token model — IMPORTANTE

Meta NÃO tem refresh_token. Long-lived access_token expira ~60 dias. V0 strategy: **Reactive** — quando tool retorna error subcode 458/467, MetaTokenExpiredError pede reconnect. **Proactive cron** (V1) — implementar quando 5+ conexões ativas.

---

## 4. Meta SDK + Reports Executor

### `pyproject.toml` — dep nova

```toml
dependencies = [
    ...existing...,
    "facebook-business>=21.0.0",
]
```

### `src/meta_ads/client.py` — factory + token guard

```python
"""Factory for facebook_business FacebookAdsApi per-manager.

Different from Google SDK: Meta uses GLOBAL state (FacebookAdsApi.set_default_api)
by default — dangerous in async multi-manager. Convention: always construct
FacebookAdsApi(...) instance directly (NOT .init()) and pass api= explicit.
"""

class NoMetaConnectionError(Exception):
    """Raised when manager has no active Meta OAuth connection."""

class MetaTokenExpiredError(Exception):
    """Raised when access_token expired (Meta has no refresh; user must reconnect)."""

async def build_meta_api_for_manager(*, manager_id: UUID) -> FacebookAdsApi:
    """Decrypt access_token + return FacebookAdsApi instance with explicit api=.

    Raises NoMetaConnectionError | MetaTokenExpiredError with PT-BR messages.
    """
    from facebook_business.api import FacebookAdsApi  # lazy import

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
    access_token = decrypt_refresh_token(oc.access_token_enc, master_key)  # reuse helper

    return FacebookAdsApi(
        access_token=access_token,
        app_id=settings.meta_app_id,
        app_secret=settings.meta_app_secret,
        api_version="v22.0",
    )
```

### `src/meta_ads/reports.py` — Graph API GET executor

V0 simpler version. Insights complexity (paginação, async jobs) M.3+.

```python
async def run_meta_graph_get(
    *,
    manager_id: UUID,
    session_id: UUID,
    edge: str,                       # e.g., "/me/adaccounts"
    params: dict[str, Any] | None = None,
    operation_name: str,
    estimated_calls: int = 1,
    audit_this_call: bool = False,
    params_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Mirror semantics of run_report (Google). Rate_limit post-call only (Meta tem
    BUC headers; no pre-flight global counter). Audit opt-in, PT-BR errors."""
    settings = get_settings()
    api = await build_meta_api_for_manager(manager_id=manager_id)
    started = time.monotonic()

    try:
        response = api.call("GET", [edge.lstrip("/")], params=params or {})
        body = response.json()
    except FacebookRequestError as e:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        friendly = to_friendly_meta_error(e)
        if audit_this_call:
            async with connection.get_pool().acquire() as conn:
                await audit_log.record(
                    conn,
                    manager_id=manager_id, session_id=session_id,
                    customer_id=(params_summary or {}).get("ad_account_id"),
                    action_type="read", operation=operation_name,
                    status="error", error_message=friendly.message,
                    duration_ms=elapsed_ms,
                    platform="meta",
                )
        raise friendly from e

    elapsed_ms = int((time.monotonic() - started) * 1000)

    # Parse X-Business-Use-Case-Usage header → meta_rate_counters
    buc_header = response.headers().get("x-business-use-case-usage")
    if buc_header and params and "ad_account_id" in params:
        await record_actual_meta(
            app_id=settings.meta_app_id,
            ad_account_id=params["ad_account_id"],
            buc_header=buc_header,
            calls=estimated_calls,
        )

    if audit_this_call:
        async with connection.get_pool().acquire() as conn:
            await audit_log.record(
                conn,
                manager_id=manager_id, session_id=session_id,
                customer_id=(params_summary or {}).get("ad_account_id"),
                action_type="read", operation=operation_name,
                target_count=len(body.get("data", [])),
                params_summary=params_summary,
                status="success", duration_ms=elapsed_ms,
                platform="meta",
                provider_request_id=response.headers().get("x-fb-trace-id"),
            )

    return body
```

### `src/meta_ads/errors.py` — error → PT-BR

```python
@dataclass(slots=True, frozen=True)
class MetaAdsFriendlyError(Exception):
    message: str
    retryable: bool

def to_friendly_meta_error(e: Exception) -> MetaAdsFriendlyError:
    if isinstance(e, FacebookRequestError):
        subcode = e.api_error_subcode()
        code = e.api_error_code()
        if subcode in (458, 467, 460, 463):
            return MetaAdsFriendlyError(
                "Sua conexão Meta expirou ou foi revogada. Reconecte via painel admin.",
                retryable=False)
        if subcode == 2635 or code == 4:
            return MetaAdsFriendlyError(
                "Limite Meta atingido. Tente novamente em alguns minutos.",
                retryable=True)
        if code == 190:
            return MetaAdsFriendlyError(
                "Permissão insuficiente. Verifique se aceitou ads_read + ads_management.",
                retryable=False)
        if code == 100:
            return MetaAdsFriendlyError(
                f"Campo inválido na requisição Meta: {e.api_error_message()}",
                retryable=False)
        return MetaAdsFriendlyError(
            f"Erro Meta API ({code}/{subcode}): {e.api_error_message()}",
            retryable=False)
    return MetaAdsFriendlyError(f"Erro inesperado: {e}", retryable=False)
```

### Rate limit Meta — `src/governance/rate_limit.py` extensions

```python
async def record_actual_meta(
    *,
    app_id: str,
    ad_account_id: str,
    buc_header: str,                 # X-Business-Use-Case-Usage JSON string
    calls: int = 1,
) -> None:
    """Parse BUC header + update meta_rate_counters.

    BUC format: {"<numeric_ad_account_id>": [{"type":"ads_management", "call_count": 42,
                  "total_cputime": 12, "total_time": 35, "estimated_time_to_regain_access": 0}]}

    Strategy: max(call_count, total_cputime, total_time) as throttle_pct.
    Structlog warning if >75%.
    """
    import hashlib, json
    parsed = json.loads(buc_header)
    pcts = []
    numeric_id = ad_account_id.replace("act_", "")
    for acct_key, usages in parsed.items():
        if acct_key == numeric_id:
            for u in usages:
                pcts.extend([u.get("call_count", 0), u.get("total_cputime", 0),
                            u.get("total_time", 0)])
    throttle_pct = max(pcts) if pcts else 0

    app_id_hash = hashlib.sha256(app_id.encode()).hexdigest()[:32]
    today = date.today()

    pool = connection.get_pool()
    async with pool.acquire() as conn:
        await meta_rate_counters.increment_calls(
            conn, app_id=app_id_hash, ad_account_id=ad_account_id, date=today, by=calls)
        await meta_rate_counters.update_throttle(
            conn, app_id=app_id_hash, ad_account_id=ad_account_id, date=today,
            throttle_pct=throttle_pct)

    if throttle_pct > 75:
        log.warning("meta_rate_limit_warning",
                    ad_account_id=ad_account_id, throttle_pct=throttle_pct)
```

V0: post-call accounting only. Sem pre-flight (caro pra Meta).

---

## 5. Tool `meta_list_my_ad_accounts`

Primeira (e única M.2a) tool MCP Meta. Padrão simétrico a `list_my_accounts` Google.

```python
"""List Meta Ad Accounts that the current manager has access to.

Source: manager_meta_account_access (DB cache, populated on OAuth callback).
NOT Meta API direct. Refresh via reconnect.
"""

_ACCOUNT_STATUS_LABELS = {
    1: "ATIVO",
    2: "DESABILITADO",
    3: "PAGAMENTO_PENDENTE",
    7: "EM_REVISÃO_DE_RISCO",
    101: "FECHADO",
    102: "ANY_ACTIVE",
    201: "FECHAMENTO_PENDENTE",
    202: "LIQUIDAÇÃO_PENDENTE",
}

@register_tool(
    name="meta_list_my_ad_accounts",
    description="Lista as contas de anúncio Meta às quais o gestor tem acesso. "
                "Fonte: cache local (sincronizado quando o gestor conecta Meta via OAuth). "
                "Pra forçar refresh, gestor precisa reconectar via painel admin.",
    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
)
async def handler(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        accounts = await manager_meta_account_access.list_accounts_for_manager(
            conn, ctx.manager_id)

    return {
        "ad_accounts": [
            {
                "ad_account_id": a.ad_account_id,
                "account_name": a.account_name,
                "business_id": a.business_id,
                "business_name": a.business_name,
                "currency": a.currency,
                "timezone_name": a.timezone_name,
                "account_status": a.account_status,
                "account_status_label": _ACCOUNT_STATUS_LABELS.get(
                    a.account_status or 0, "DESCONHECIDO"),
            }
            for a in accounts
        ],
        "total": len(accounts),
    }
```

### Por que NÃO chama Meta API direto?

- OAuth callback já populou `meta_ad_accounts` + `manager_meta_account_access`. Tool MCP lê do cache local.
- Trade-off: dados podem ficar stale se ad account add/remove no BM Meta sem reconnect. Mitigation: M.2b adiciona "Refresh Meta accounts" button.
- Vantagens: zero latency Meta API, zero rate limit consumption.

---

## 6. Webapp UI minimal

`src/web/templates/admin/index.html` — adicionar card "Suas conexões OAuth" entre summary stats e lista de managers:

```jinja2
<section class="v4-card mb-6">
  <h2 class="text-lg font-semibold text-v4-gray-900 mb-4">Suas conexões OAuth</h2>
  <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
    {# Google connection (existing) #}
    <div class="p-4 border border-v4-gray-100 rounded-md">
      <div class="flex items-center justify-between mb-2">
        <span class="font-medium text-v4-gray-900">Google Ads</span>
        {% if google_conn %}
          <span class="text-xs px-2 py-1 bg-v4-green-soft text-v4-green rounded">Conectado</span>
        {% else %}
          <span class="text-xs px-2 py-1 bg-v4-gray-50 text-v4-gray-700 rounded">Desconectado</span>
        {% endif %}
      </div>
      {% if google_conn %}
        <p class="text-sm text-v4-gray-700">{{ google_conn.google_email }}</p>
        <p class="text-xs text-v4-gray-700">Conectado em {{ google_conn.connected_at.strftime('%d/%m/%Y') }}</p>
        <a href="/oauth/google/start?mode=panel_login" class="text-xs text-v4-red hover:underline mt-2 inline-block">Reconectar</a>
      {% else %}
        <a href="/oauth/google/start?mode=panel_login" class="v4-btn v4-btn--small v4-btn--primary mt-2 inline-block">Conectar Google</a>
      {% endif %}
    </div>

    {# Meta connection — NEW #}
    <div class="p-4 border border-v4-gray-100 rounded-md">
      <div class="flex items-center justify-between mb-2">
        <span class="font-medium text-v4-gray-900">Meta Ads</span>
        {% if meta_conn %}
          {% if meta_token_expiring_soon %}
            <span class="text-xs px-2 py-1 bg-v4-gold-soft text-v4-gold rounded">Expira em breve</span>
          {% else %}
            <span class="text-xs px-2 py-1 bg-v4-green-soft text-v4-green rounded">Conectado</span>
          {% endif %}
        {% else %}
          <span class="text-xs px-2 py-1 bg-v4-gray-50 text-v4-gray-700 rounded">Desconectado</span>
        {% endif %}
      </div>
      {% if meta_conn %}
        <p class="text-sm text-v4-gray-700">{{ meta_conn.fb_email }}</p>
        <p class="text-xs text-v4-gray-700">
          Expira em {{ meta_conn.token_expires_at.strftime('%d/%m/%Y') }}
          ({{ meta_days_until_expiry }} dias)
        </p>
        <a href="/oauth/meta/start" class="text-xs text-v4-red hover:underline mt-2 inline-block">Reconectar</a>
      {% else %}
        <a href="/oauth/meta/start" class="v4-btn v4-btn--small v4-btn--primary mt-2 inline-block">Conectar Meta</a>
      {% endif %}
    </div>
  </div>
</section>
```

### Backend — `src/web/routes.py` admin handler enrichment

```python
@router.get("/admin", response_class=HTMLResponse)
async def admin_index(request, user: CurrentUser = Depends(current_manager)):
    _require_admin(user)
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        google_conn = await google_oauth_connections.get_active_for_manager(conn, user.id)
        meta_conn = await meta_oauth_connections.get_active_for_manager(conn, user.id)
        # ... existing summary stats ...

    meta_token_expiring_soon = False
    meta_days_until_expiry = None
    if meta_conn:
        delta = meta_conn.token_expires_at - datetime.now(UTC)
        meta_days_until_expiry = max(0, delta.days)
        meta_token_expiring_soon = delta.days < 7

    return templates.TemplateResponse(request, "admin/index.html", {
        "current_user": user,
        "google_conn": google_conn,
        "meta_conn": meta_conn,
        "meta_token_expiring_soon": meta_token_expiring_soon,
        "meta_days_until_expiry": meta_days_until_expiry,
        # ... existing ...
    })
```

### NÃO incluído em M.2a (cortes deliberados pra M.2b)

- ❌ Card simétrico polish (header com logos, design refinement)
- ❌ Botão "Refresh Meta accounts" (force re-sync sem reconnect)
- ❌ Listagem de Meta ad accounts em `/admin/accounts`
- ❌ Audit log filter por platform no painel UI
- ❌ Botão "Revogar" no card Meta (precisa modal de confirm)

---

## 7. Testing Strategy

### Unit tests

```
tests/unit/test_meta_oauth.py
  - test_callback_decision_blocks_when_missing_essential_scopes
  - test_callback_decision_accepts_when_all_essentials_granted
  - test_callback_decision_blocks_when_email_not_v4company
  - test_state_payload_includes_aud_meta_oauth

tests/unit/test_meta_errors.py
  - test_to_friendly_meta_error_expired_token
  - test_to_friendly_meta_error_rate_limit
  - test_to_friendly_meta_error_permission_denied
  - test_to_friendly_meta_error_invalid_field
  - test_to_friendly_meta_error_unknown_falls_back

tests/unit/test_meta_rate_counters_repo.py  (with mocked conn)
  - test_increment_calls_creates_row_first_time
  - test_increment_calls_adds_to_existing_row
  - test_update_throttle_writes_pct

tests/unit/test_buc_header_parsing.py
  - test_parse_buc_header_extracts_max_pct
  - test_parse_buc_header_handles_empty
  - test_parse_buc_header_handles_malformed_json
```

### Integration tests com `respx` mockando Meta Graph API

```python
# tests/integration/test_meta_oauth_flow.py
@pytest.mark.integration
async def test_oauth_callback_happy_path(db, respx_mock):
    """Mock Meta /oauth/access_token + /me + /debug_token + /me/adaccounts."""
    respx_mock.post("https://graph.facebook.com/v22.0/oauth/access_token").respond(
        200, json={"access_token": "short_lived_xyz", "token_type": "bearer", "expires_in": 3600})
    respx_mock.get("https://graph.facebook.com/v22.0/oauth/access_token").respond(
        200, json={"access_token": "long_lived_60d", "token_type": "bearer", "expires_in": 5184000})
    respx_mock.get("https://graph.facebook.com/v22.0/me").respond(
        200, json={"id": "12345", "email": "test@v4company.com", "name": "Wellington"})
    respx_mock.get("https://graph.facebook.com/v22.0/debug_token").respond(
        200, json={"data": {"scopes": ["ads_read", "ads_management", "business_management", "email", "public_profile"]}})
    respx_mock.get("https://graph.facebook.com/v22.0/me/adaccounts").respond(
        200, json={"data": [{"id": "act_111", "name": "Cliente Alpha", "account_status": 1,
                            "currency": "BRL", "timezone_name": "America/Sao_Paulo"}]})
    # Drive callback → assert connection persisted, account upserted, grant created

@pytest.mark.integration
async def test_oauth_callback_blocks_missing_ads_read_scope(db, respx_mock)
@pytest.mark.integration
async def test_oauth_callback_blocks_non_v4_email(db, respx_mock)
@pytest.mark.integration
async def test_oauth_callback_handles_meta_oauth_error_param(db)
```

```python
# tests/integration/test_meta_list_my_ad_accounts.py
@pytest.mark.integration
async def test_meta_list_my_ad_accounts_full_pipeline(db)
@pytest.mark.integration
async def test_meta_list_my_ad_accounts_translates_account_status_labels(db)
@pytest.mark.integration
async def test_meta_list_my_ad_accounts_isolates_per_manager(db)
@pytest.mark.integration
async def test_meta_list_my_ad_accounts_empty_when_no_grants(db)
```

```python
# tests/integration/test_audit_log_platform.py  (regression para Task 1+2+3)
@pytest.mark.integration
async def test_audit_log_record_default_platform_is_google(db)
@pytest.mark.integration
async def test_audit_log_record_accepts_platform_meta(db)
@pytest.mark.integration
async def test_audit_log_record_writes_provider_request_id(db)
```

### CI Gates

- `python scripts/check_pre_push.py` → 5/5 PASS
- `python scripts/check_pre_push_full.py` → 6/6 PASS (Docker integration tests catch testcontainers issues — **MANDATORY pra este sprint** porque mexe em audit_log)
- CI workflow → ruff + format + mypy + pytest unit + integration
- Deploy workflow → migration 004 + Cloud Run deploy + smoke /health 200 + /mcp 401 gate

### Smoke runbook (`docs/operacao/phase-M-2a-bootstrap.md`)

Generated via `smoke-runbook-generator` subagent + tweaks. Testes Wellington manual:

| Test | Action | Expected |
|---|---|---|
| T1 — OAuth happy path | Acessa `/admin` → click "Conectar Meta" → consent FB | Redirect callback → toast success → card "Conectado" + fb_email |
| T2 — `meta_list_my_ad_accounts` via Claude | "Liste minhas contas Meta" no Claude Desktop | Lista contas V4 Lima Soares & Co com names, currency, status_label PT-BR |
| T3 — Granular permission rejection | OAuth + desmarcar `ads_read` no consent | Redirect `/access-denied?reason=meta_scopes_missing&missing=ads_read` |
| T4 — Audit log entry | Após T1+T2: `get_my_audit_log(platform="meta")` | Retorna entries auth (meta_oauth_connect) + read (meta_list_my_ad_accounts) com platform="meta" |
| T5 — Token expiry simulation | SQL UPDATE `token_expires_at` no passado → re-tenta tool | `MetaTokenExpiredError` PT-BR |
| T6 — Revoke flow | (M.2b) | — |

---

## 8. Risks & Open Questions

### Risks M.2a

| Risk | Prob | Impact | Mitigation |
|---|---|---|---|
| Big bang rename quebra caller que Grep não pegou | Baixa | Alto | Pre-push full sweep (mypy strict) + integration tests + Wellington manual smoke Google em prod pós-deploy |
| `facebook_business` SDK retorna shape inesperado | Média | Médio | respx integration tests + smoke real M.2a valida REAL Graph API |
| Token exchange `expires_in` formato inesperado | Baixa | Médio | Defensive parsing: `int(token_resp.get("expires_in", 5184000))` |
| Meta `debug_token` schema mudou | Baixa | Alto | Pin v22.0 + fallback: skip granular check + warning structlog |
| Cloud Run deploy lento por `facebook-business` dep | Média | Baixo | Aceita +30-60s no Build |
| Migration 004 RENAME bloqueada por conexão ativa | Baixa | Médio | Cloud Run Job migrate window curta, audit_log writes quick |
| Wellington único admin Meta app | Média | Baixo | M.X+ adiciona colaboradores deferred |
| Smoke real toca prod V4 Lima Soares & Co | Alta | Baixo | Tool M.2a read-only, zero blast radius |

### Open questions adiadas

| Question | Resolution V0 | Sprint pra resolver |
|---|---|---|
| Force refresh Meta accounts sem reconnect | UI button | M.2b ou M.3 |
| Revoke chama Meta API ou só local | V0 só local | M.2b |
| Proactive token refresh cron | Reactive V0 | M.X+ |
| MetaCaptureClient fixture pra mutate tests | YAGNI M.2a | M.3+ |

### Sprint M.2b scope (próximo)

- Tool `meta_get_account_overview` (spend, impressions, clicks, ctr, currency, status)
- Endpoint `/oauth/meta/data-deletion-callback` (signed_request validation)
- Webapp polish (cards refinados, refresh button, revoke com modal)
- Per-value smoke probes + edge cases
- Wellington manual: Meta App Review submit
- Smoke runbook + signoff

### V1 release criteria (após M.2a + M.2b)

- M.2a + M.2b ship + smoke real V4 Lima Soares & Co
- Wellington usa ambas tools em workflow ≥3x/semana
- Zero F-finding crítico aberto
- Audit log ≥10 chamadas Meta/semana
- Meta App Review submitted

### Convenções novas CLAUDE.md pós-M.2a

- "Meta SDK global state warning" — construir `FacebookAdsApi(...)` instance, NUNCA `.init()`
- "Long-lived token expiration check" — toda Meta tool MUST chamar `build_meta_api_for_manager` (valida `token_expires_at`)
- "BUC header parsing pós-cada-call" — convention em `_meta_common.py`
- "`platform` kwarg em audit_log.record()" — todos novos callers Meta devem passar explicitamente

---

## 9. Pre-V0 checklist (antes de invocar writing-plans)

- [x] Brainstorming completo + design aprovado (8 sections)
- [ ] Spec doc commitado (este arquivo)
- [ ] Wellington review do spec
- [ ] writing-plans skill invocado pra Sprint M.2a isolado (NÃO Sprint M.2b)

### Escopo do writing-plans

writing-plans deve gerar plan **APENAS para Sprint M.2a** (Tasks 1-5 prep + OAuth + SDK + tool + UI + tests + smoke). Sprint M.2b ganha seu próprio plan via `/sprint-bootstrap` quando chegar a vez.

---

**Sprint ready to start:** M.2a (~2-3 dias). Próximo passo após user review: `superpowers:writing-plans` skill pra gerar plan detalhado bite-sized TDD.
