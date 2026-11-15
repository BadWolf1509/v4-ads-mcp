# Sprint M.2b — Meta Get Account Overview + App Review Prep — Design Doc

**Sprint:** M.2b (parte 2 do Sprint M.2 dividido em M.2a + M.2b)
**Author:** Wellington Ribeiro + Claude (brainstorming session 2026-05-25)
**Status:** Approved, pronto pra writing-plans phase
**Estimativa:** ~3-4 dias úteis

**Companion specs:**
- [Sprint family M design](2026-05-24-meta-ads-incorporation-design.md) (overall roadmap M.1-M.25)
- [Sprint M.2a design](2026-05-24-sprint-m2a-meta-oauth-first-tool-design.md) (predecessor — OAuth + first tool)
- [Sprint M.2a plan](../plans/2026-05-24-sprint-m2a-meta-oauth-first-tool.md)

---

## 0. Contexto

Sprint M.2a (shipped 2026-05-25, 14 commits, smoke 4/7 PASS) entregou: OAuth flow Meta ponta-a-ponta + facebook_business v21 SDK + 1ª tool MCP `meta_list_my_ad_accounts` + admin UI card OAuth connections + audit_log multi-platform + 2 findings (A6 + F47).

**Sprint M.2b fecha o gap "first real Graph API call + Meta App Review ready":**
- 1ª tool que faz call real Graph API (não cache local): `meta_get_account_overview` — valida toda a infra M.2a (token check, FacebookAdsApi instance, BUC parsing, audit log, PT-BR error translation) em produção
- 2 endpoints novos OAuth: `/oauth/meta/data-deletion-callback` (pré-req App Review obrigatório) + `/oauth/meta/refresh-accounts` (sync sem reconnect)
- 1 fix tool existente: `get_my_audit_log` retorna `platform` field (A5 OPEN)
- 2 botões admin UI: "Revogar" + "Atualizar lista" no card OAuth Meta
- 1 smoke runbook: `phase-M-2b-bootstrap.md` (8 tests, per-value probes incluído)
- 1 ação Wellington fora-MCP: Meta App Review submit (5-30d Meta timeline)

**Princípio diretor:** validar Graph API pipeline em produção via tool single-purpose (read-only overview) antes de escalar pra suite completa Meta (M.3+). Se essa tool funciona end-to-end, infra está validada pra todas as Meta tools subsequentes.

**Decision gate pós-M.2b:** 2 semanas dogfood Wellington — ≥3 usos/semana = continua M.3-M.25; senão pause + foca Google backlog (Sprint 3b.38 candidates).

---

## 1. Architecture Overview

```
src/
├── auth/
│   └── meta_oauth.py            ← +POST /oauth/meta/data-deletion-callback
│                                ← +POST /oauth/meta/refresh-accounts
│                                ← +_verify_meta_signed_request() helper
├── meta_ads/
│   └── account_overview.py     ← NEW pure module (date math, deltas, warnings)
├── mcp/tools/
│   ├── meta_get_account_overview.py  ← NEW 2ª tool Meta
│   ├── _meta_common.py         ← +resolve_meta_date_window helper
│   └── get_my_audit_log.py     ← MINOR: A5 fix, surface platform field
├── db/repositories/
│   └── audit_log.py            ← MINOR: list_for_manager adiciona platform na SELECT
└── web/
    ├── routes.py               ← +POST /oauth/meta/refresh-accounts handler view
    │                            ← +admin index enrichment (already covered M.2a)
    └── templates/
        ├── admin/index.html    ← +botões Revogar + Atualizar Lista no card Meta
        └── legal/
            └── data_deletion_status.html  ← NEW page status callback

tests/
├── unit/
│   ├── test_meta_account_overview.py  ← NEW ~20 tests pure module
│   ├── test_meta_signed_request.py    ← NEW HMAC validation tests
│   └── test_get_my_audit_log_platform.py  ← NEW A5 regression
└── integration/
    ├── test_meta_get_account_overview.py  ← NEW respx mock Graph
    ├── test_meta_data_deletion_callback.py  ← NEW signed_request synthetic
    └── test_meta_refresh_accounts.py  ← NEW endpoint integration

docs/operacao/
└── phase-M-2b-bootstrap.md  ← NEW smoke runbook (~8 tests Wellington manual)

scripts/
└── test_meta_deletion_callback.py  ← NEW helper local pra T6 smoke (gera signed_request HMAC-valid)
```

### O que NÃO muda

- M.1 + M.2a infra (DB tables, OAuth flow start/callback/revoke, SDK client, errors, rate_limit BUC parser) — todas reused as-is
- Settings em config.py — META_APP_ID + META_APP_SECRET já populados
- MCP server, registry, context — agnostic infra
- Google tools — zero touch

### Migrations

**Zero migrations novas.** Coluna `audit_log.platform` já existe (M.2a migration 004). A5 fix é só SQL SELECT change + tool return passthrough.

---

## 2. Tool `meta_get_account_overview`

### 2.1 Schema (input)

```python
{
    "type": "object",
    "properties": {
        "ad_account_id": {
            "type": "string",
            "pattern": "^act_\\d+$",
            "description": "Meta ad account ID (formato act_<numeric>). Use meta_list_my_ad_accounts pra descobrir."
        },
        "date_range": {
            "type": "string",
            "enum": ["LAST_7_DAYS", "LAST_14_DAYS", "LAST_30_DAYS", "LAST_90_DAYS", "TODAY", "YESTERDAY"],
            "description": "Janela temporal preset. Default LAST_7_DAYS se start_date+end_date não fornecidos."
        },
        "start_date": {
            "type": "string",
            "pattern": "^\\d{4}-\\d{2}-\\d{2}$",
            "description": "Custom range start (YYYY-MM-DD). Sobrescreve date_range preset. Requires end_date."
        },
        "end_date": {
            "type": "string",
            "pattern": "^\\d{4}-\\d{2}-\\d{2}$",
            "description": "Custom range end (YYYY-MM-DD). Sobrescreve date_range preset. Requires start_date."
        }
    },
    "required": ["ad_account_id"],
    "additionalProperties": false
}
```

**Note: ZERO composition keywords** (`oneOf/allOf/anyOf`) — Anthropic validator hard-fail (lição 3b.19B.1). Cross-field constraint expressa em `_validate_input` helper.

### 2.2 Pure module `src/meta_ads/account_overview.py`

Funções puras (zero IO, fácil unit test):

```python
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

# Conversion actions a totalizar (cross-platform pattern)
CONVERSION_ACTION_TYPES = frozenset({
    "purchase",
    "lead",
    "complete_registration",
    "offsite_conversion.fb_pixel_purchase",
    "offsite_conversion.fb_pixel_lead",
    "offsite_conversion.fb_pixel_complete_registration",
})


def resolve_meta_date_window(
    preset: str | None,
    start_date: str | None,
    end_date: str | None,
    today: date,
) -> tuple[date, date]:
    """Resolve preset OR (start, end) → (start, end) date tuple.

    Custom (start+end) overrides preset. Default LAST_7_DAYS se ambos None.
    Raises ValueError se inconsistent (one of start/end without other).
    """
    if start_date and end_date:
        return (date.fromisoformat(start_date), date.fromisoformat(end_date))
    if start_date or end_date:
        raise ValueError("start_date e end_date devem ser fornecidos juntos")
    preset = preset or "LAST_7_DAYS"
    if preset == "TODAY":
        return (today, today)
    if preset == "YESTERDAY":
        y = today - timedelta(days=1)
        return (y, y)
    days = {"LAST_7_DAYS": 7, "LAST_14_DAYS": 14, "LAST_30_DAYS": 30, "LAST_90_DAYS": 90}[preset]
    return (today - timedelta(days=days - 1), today)


def shift_to_previous_period(start: date, end: date) -> tuple[date, date]:
    """Calculate previous period of same length (e.g., LAST_7_DAYS → 7d before that)."""
    length = (end - start).days + 1
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=length - 1)
    return (prev_start, prev_end)


def parse_insights_response(data: dict[str, Any]) -> dict[str, float | int]:
    """Parse Graph /insights response → normalized metrics dict.

    Graph response format:
    {"data": [{"spend": "1234.56", "impressions": "45000", "actions": [{"action_type": "purchase", "value": "12"}, ...], ...}]}

    Returns dict with strict types. Empty/missing fields → 0.
    """
    if not data.get("data"):
        return _empty_metrics()
    row = data["data"][0]
    actions = _parse_actions(row.get("actions", []), CONVERSION_ACTION_TYPES)
    action_values = _parse_actions(row.get("action_values", []), CONVERSION_ACTION_TYPES)
    return {
        "spend": float(row.get("spend", 0) or 0),
        "impressions": int(row.get("impressions", 0) or 0),
        "clicks": int(row.get("clicks", 0) or 0),
        "ctr": float(row.get("ctr", 0) or 0),
        "cpc": float(row.get("cpc", 0) or 0),
        "reach": int(row.get("reach", 0) or 0),
        "frequency": float(row.get("frequency", 0) or 0),
        "conversions": int(actions),
        "conversion_value": float(action_values),
        "purchase_roas": _extract_purchase_roas(row.get("purchase_roas", [])),
    }


def _parse_actions(actions: list[dict], filter_types: frozenset[str]) -> float:
    """Sum 'value' field across actions matching filter_types."""
    return sum(
        float(a.get("value", 0) or 0)
        for a in actions
        if a.get("action_type") in filter_types
    )


def _extract_purchase_roas(roas_arr: list[dict]) -> float:
    """Graph retorna purchase_roas como [{"action_type": "omni_purchase", "value": "6.8"}]."""
    for entry in roas_arr:
        if entry.get("action_type") in ("purchase", "omni_purchase"):
            return float(entry.get("value", 0) or 0)
    return 0.0


def compute_deltas(current: dict, previous: dict) -> dict[str, float]:
    """Returns dict with `_pct` suffix per metric. None if previous=0 (division undefined)."""
    out: dict[str, float | None] = {}
    for key in ("spend", "impressions", "clicks", "conversions", "conversion_value", "purchase_roas"):
        prev_val = previous.get(key, 0)
        curr_val = current.get(key, 0)
        if prev_val == 0:
            out[f"{key}_pct"] = None  # divisão indefinida — Claude interpreta como N/A
        else:
            out[f"{key}_pct"] = round((curr_val - prev_val) / prev_val * 100, 2)
    return out


def build_warnings(
    account_status_label: str,
    token_expires_at: datetime | None,
    now: datetime,
) -> list[str]:
    """Returns lista PT-BR warnings ativos (account_status problema + token <7d)."""
    out: list[str] = []
    if account_status_label != "ATIVO":
        out.append(
            f"account_status={account_status_label} — métricas podem estar desatualizadas ou ad serving suspenso. "
            f"Verificar billing/status no Meta Business Suite."
        )
    if token_expires_at:
        days_left = (token_expires_at - now).days
        if days_left < 7:
            iso_date = token_expires_at.date().isoformat()
            out.append(
                f"Token OAuth Meta expira em {days_left} dias ({iso_date}). "
                f"Reconectar via /admin → 'Conectar Meta' pra evitar interrupção das tools."
            )
    return out


def _empty_metrics() -> dict[str, float | int]:
    return {
        "spend": 0.0, "impressions": 0, "clicks": 0, "ctr": 0.0, "cpc": 0.0,
        "reach": 0, "frequency": 0.0, "conversions": 0, "conversion_value": 0.0,
        "purchase_roas": 0.0,
    }
```

### 2.3 Tool orchestrator `src/mcp/tools/meta_get_account_overview.py`

```python
"""meta_get_account_overview — 1ª tool Meta com Graph API real call (Sprint M.2b)."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import structlog

from src.db import connection
from src.db.repositories import meta_ad_accounts, meta_oauth_connections
from src.mcp.tools._meta_common import META_ACCOUNT_STATUS_LABELS
from src.meta_ads.account_overview import (
    build_warnings,
    compute_deltas,
    parse_insights_response,
    resolve_meta_date_window,
    shift_to_previous_period,
)
from src.meta_ads.reports import run_meta_graph_get

log = structlog.get_logger(__name__)


def classify() -> dict[str, Any]:
    return {
        "tool": "meta_get_account_overview",
        "blast_radius": "read_only",
        "platform": "meta",
        "estimated_buc_per_call": 2,  # current + previous = 2 Graph calls
    }


async def meta_get_account_overview(
    manager_id: UUID,
    session_id: UUID,
    *,
    ad_account_id: str,
    date_range: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    """Account-level overview com comparativo período anterior."""
    pool = connection.get_pool()

    # 1. Resolve date window (cheap, validate antes de hit DB/Graph)
    today = datetime.now(UTC).date()
    try:
        current_start, current_end = resolve_meta_date_window(date_range, start_date, end_date, today)
    except ValueError as e:
        return {"status": "error", "error_message": f"Parâmetros de data inválidos: {e}"}
    prev_start, prev_end = shift_to_previous_period(current_start, current_end)

    # 2. Get account metadata + oc (pra account_status + token_expires_at warnings)
    async with pool.acquire() as conn:
        account = await meta_ad_accounts.get_by_id(conn, ad_account_id)
        if account is None:
            return {"status": "error", "error_message": f"Ad account {ad_account_id} não encontrada. Use meta_refresh_accounts ou reconnect."}
        oc = await meta_oauth_connections.get_active_for_manager(conn, manager_id)
        if oc is None:
            return {"status": "error", "error_message": "Nenhuma conexão Meta ativa. Conectar via /oauth/meta/start."}

    account_status_label = META_ACCOUNT_STATUS_LABELS.get(account.account_status or 0, "DESCONHECIDO")

    # 3. Graph API calls (current + previous via shared executor)
    # run_meta_graph_get internally: builds api, records BUC, records audit when audit_this_call=True,
    # raises MetaAdsFriendlyError on any failure. Returns parsed dict body.
    fields = "spend,impressions,clicks,ctr,cpc,reach,frequency,actions,action_values,purchase_roas"

    try:
        current_resp = await run_meta_graph_get(
            manager_id=manager_id,
            session_id=session_id,
            edge=f"/{ad_account_id}/insights",
            params={
                "fields": fields,
                "time_range": f'{{"since":"{current_start.isoformat()}","until":"{current_end.isoformat()}"}}',
                "level": "account",
                "ad_account_id": ad_account_id,  # required pra BUC counter parsing
            },
            operation_name="meta_get_account_overview",
            estimated_calls=1,
            audit_this_call=True,
            params_summary={
                "ad_account_id": ad_account_id,
                "date_range": str(date_range),
                "period": "current",
                "start": current_start.isoformat(),
                "end": current_end.isoformat(),
            },
        )
        previous_resp = await run_meta_graph_get(
            manager_id=manager_id,
            session_id=session_id,
            edge=f"/{ad_account_id}/insights",
            params={
                "fields": fields,
                "time_range": f'{{"since":"{prev_start.isoformat()}","until":"{prev_end.isoformat()}"}}',
                "level": "account",
                "ad_account_id": ad_account_id,
            },
            operation_name="meta_get_account_overview",
            estimated_calls=1,
            audit_this_call=False,  # only audit current call (previous is just delta math input)
        )
    except Exception as e:
        # MetaAdsFriendlyError já tem .message PT-BR
        if hasattr(e, "message"):
            return {"status": "error", "error_message": e.message}
        return {"status": "error", "error_message": str(e)}

    current_metrics = parse_insights_response(current_resp)
    previous_metrics = parse_insights_response(previous_resp)
    deltas = compute_deltas(current_metrics, previous_metrics)

    # 4. Build warnings
    warnings = build_warnings(account_status_label, oc.token_expires_at, datetime.now(UTC))

    # Audit_log + BUC counter já gravados em run_meta_graph_get (audit_this_call=True na current call)

    return {
        "status": "success",
        "ad_account_id": ad_account_id,
        "account_name": account.account_name,
        "account_status_label": account_status_label,
        "currency": account.currency,
        "date_range": {"start": current_start.isoformat(), "end": current_end.isoformat()},
        "current": current_metrics,
        "previous": previous_metrics,
        "deltas": deltas,
        "_warnings": warnings,
    }
```

### 2.4 apply_change router branch

```python
# src/mcp/apply_change.py — adicionar branch
if tool_name == "meta_get_account_overview":
    return await meta_get_account_overview.meta_get_account_overview(**kwargs)
```

Read-only → executa direto sem CONFIRM workflow (consistente com `meta_list_my_ad_accounts`).

---

## 3. Endpoints novos OAuth

### 3.1 `POST /oauth/meta/data-deletion-callback`

**Especificação Meta:** https://developers.facebook.com/docs/development/create-an-app/app-dashboard/data-deletion-callback

```python
# src/auth/meta_oauth.py — adicionar endpoint
import base64
import hmac
import hashlib
import json
from uuid import uuid4


@router.post("/data-deletion-callback", response_model=None)
async def meta_data_deletion_callback(request: Request) -> dict[str, str]:
    """V0 callback: log + confirmation_code (NÃO deleta data imediatamente).

    Wellington processa manualmente em até 30 dias (LGPD/GDPR window).
    Meta App Review requirement.
    """
    settings = get_settings()
    form = await request.form()
    signed_request = form.get("signed_request", "")
    if not signed_request:
        raise HTTPException(status_code=400, detail="signed_request required")

    payload = _verify_meta_signed_request(signed_request, settings.meta_app_secret)
    if payload is None:
        log.warning("meta_data_deletion_invalid_signature")
        raise HTTPException(status_code=400, detail="Invalid signature")

    meta_user_id = payload.get("user_id")
    confirmation_code = str(uuid4())

    pool = connection.get_pool()
    async with pool.acquire() as conn:
        await audit_log.record(
            conn,
            manager_id=None,
            session_id=None,
            customer_id=None,
            action_type="auth",
            operation="meta_data_deletion_request",
            params_summary={
                "meta_user_id": meta_user_id,
                "confirmation_code": confirmation_code,
                "expires": payload.get("expires"),
            },
            status="success",
            platform="meta",
        )

    log.info(
        "meta_data_deletion_request_logged",
        meta_user_id=meta_user_id,
        confirmation_code=confirmation_code,
    )

    # Spec Meta: required response shape
    return {
        "url": f"https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/legal/data-deletion-status/{confirmation_code}",
        "confirmation_code": confirmation_code,
    }


def _verify_meta_signed_request(signed_request: str, app_secret: str) -> dict | None:
    """Validate Meta signed_request HMAC SHA256.

    Format: base64url(signature).base64url(json_payload)
    Returns parsed payload dict, ou None se invalid.
    """
    try:
        encoded_sig, encoded_payload = signed_request.split(".", 1)
    except ValueError:
        return None

    # base64url padding fix
    sig = base64.urlsafe_b64decode(encoded_sig + "=" * (-len(encoded_sig) % 4))
    payload_bytes = base64.urlsafe_b64decode(encoded_payload + "=" * (-len(encoded_payload) % 4))

    expected_sig = hmac.new(
        app_secret.encode("utf-8"),
        encoded_payload.encode("utf-8"),
        hashlib.sha256,
    ).digest()

    if not hmac.compare_digest(sig, expected_sig):
        return None

    try:
        payload = json.loads(payload_bytes)
    except json.JSONDecodeError:
        return None

    if payload.get("algorithm") != "HMAC-SHA256":
        return None

    return payload
```

**Public status page (`src/web/routes.py`):**

```python
@app.get("/legal/data-deletion-status/{code}", response_class=HTMLResponse)
async def data_deletion_status(code: str):
    # Minimal page V0 — render confirmation message
    return templates.TemplateResponse("legal/data_deletion_status.html", {"request": ..., "confirmation_code": code})
```

Template `data_deletion_status.html` (minimal jinja2): "Solicitação de exclusão de dados recebida (código: {{ confirmation_code }}). Wellington (administrador V4) processará em até 30 dias úteis. Contato: wellinton.ribeiro@v4company.com"

### 3.2 `POST /oauth/meta/refresh-accounts`

```python
# src/auth/meta_oauth.py — adicionar endpoint
@router.post("/refresh-accounts")
async def meta_oauth_refresh_accounts(
    user: CurrentUser = Depends(current_manager),
) -> RedirectResponse:
    """Re-sync meta_ad_accounts list via Graph /me/adaccounts.

    Útil quando cliente novo entra no BM ou ad account é renomeada.
    Não requer reconnect OAuth (usa long-lived token existente).
    """
    settings = get_settings()
    pool = connection.get_pool()

    async with pool.acquire() as conn:
        oc = await meta_oauth_connections.get_active_for_manager(conn, user.id)
        if oc is None:
            raise HTTPException(status_code=404, detail="No active Meta connection")

        # Check token expiry (proactive — antes de hit Graph)
        if oc.token_expires_at and (oc.token_expires_at - datetime.now(UTC)).days < 0:
            raise HTTPException(
                status_code=422,
                detail="Token Meta expirou. Reconectar via /oauth/meta/start.",
            )

        master_key = derive_master_key_from_settings(settings.aes_master_key)
        access_token = decrypt_refresh_token(oc.access_token_enc, master_key)

    async with httpx.AsyncClient(timeout=30.0) as http:
        adacc_resp = await http.get(
            f"{META_GRAPH_BASE}/me/adaccounts",
            params={
                "fields": "id,name,business,account_status,currency,timezone_name",
                "access_token": access_token,
            },
        )
        ad_accounts_data = adacc_resp.json().get("data", []) if adacc_resp.status_code == 200 else []

    # Upsert + grant (idempotent, mesma lógica callback M.2a Step 8)
    accounts_payload: list[dict[str, Any]] = []
    for a in ad_accounts_data:
        ad_id_raw = a.get("id", "")
        if not ad_id_raw.startswith("act_"):
            ad_id_raw = f"act_{ad_id_raw}"
        business = a.get("business") or {}
        accounts_payload.append({
            "ad_account_id": ad_id_raw,
            "business_id": business.get("id"),
            "business_name": business.get("name"),
            "account_name": a.get("name", ad_id_raw),
            "currency": a.get("currency"),
            "timezone_name": a.get("timezone_name"),
            "account_status": a.get("account_status"),
        })

    async with pool.acquire() as conn:
        if accounts_payload:
            await meta_ad_accounts.upsert_many(conn, accounts_payload)
            for a in accounts_payload:
                await manager_meta_account_access.grant(
                    conn, manager_id=user.id, ad_account_id=a["ad_account_id"],
                )

        await audit_log.record(
            conn,
            manager_id=user.id,
            session_id=None,
            customer_id=None,
            action_type="auth",
            operation="meta_refresh_accounts",
            target_count=len(accounts_payload),
            status="success",
            platform="meta",
        )

    log.info("meta_accounts_refreshed", manager_id=str(user.id), count=len(accounts_payload))
    return RedirectResponse("/admin?meta_refreshed=1", status_code=302)
```

---

## 4. UI admin extensions

### 4.1 Card OAuth Meta — botões Revogar + Atualizar Lista

Extend M.2a Task 10 template:

```html
<!-- src/web/templates/admin/index.html, dentro do card Meta connection -->
{% if meta_conn %}
  <div class="meta-conn-info">
    <!-- ... existing M.2a content (fb_email, scopes, expiry) ... -->
  </div>

  <!-- NEW M.2b: actions -->
  <div class="meta-conn-actions" style="margin-top: 16px; display: flex; gap: 8px;">
    <form method="post" action="/oauth/meta/refresh-accounts" style="margin: 0;">
      <button type="submit" class="btn btn-secondary">
        Atualizar lista
      </button>
    </form>
    <button
      onclick="document.getElementById('meta-revoke-modal').showModal()"
      class="btn btn-danger">
      Revogar conexão
    </button>
  </div>

  {% if meta_token_expiring_soon %}
    <div class="warning-banner" style="margin-top: 12px; padding: 8px; background: #fff3cd; border-left: 4px solid #ffa500;">
      ⚠ Token expira em {{ meta_days_until_expiry }} dia(s). Recomendado reconectar.
    </div>
  {% endif %}

  <!-- Modal confirm revoke -->
  <dialog id="meta-revoke-modal" style="border: 1px solid #ccc; padding: 24px; max-width: 480px;">
    <h3>Revogar conexão Meta</h3>
    <p>Vai desativar todas as tools Meta até reconnect via /oauth/meta/start.</p>
    <p><strong>Confirma?</strong></p>
    <form method="post" action="/oauth/meta/revoke" style="display: flex; gap: 8px; justify-content: flex-end;">
      <button type="button" onclick="this.closest('dialog').close()" class="btn btn-secondary">Cancelar</button>
      <button type="submit" class="btn btn-danger">Revogar</button>
    </form>
  </dialog>
{% endif %}
```

**Sem JS framework** — vanilla `<dialog>` + standard `<form>` POST. Consistente design system V4 ("no build step").

**Flash messages (`admin_index` handler):** já handle `?meta_connected=1` (M.2a), `?meta_revoked=1` (M.2a). Adicionar `?meta_refreshed=1` (M.2b) com mensagem "Lista de ad accounts atualizada. {{count}} accounts sincronizadas."

---

## 5. A5 fix: `get_my_audit_log` retorna `platform` field

### 5.1 Repository change

Adiciona `platform` à SELECT existente em `list_for_manager`:

```python
# src/db/repositories/audit_log.py
# Current SELECT (M.2a):
#   id, occurred_at, operation, customer_id, action_type,
#   target_count, status, duration_ms, provider_request_id, error_message
# Change: append `platform` no SELECT
sql = f"""SELECT id, occurred_at, operation, customer_id, action_type,
                 target_count, status, duration_ms, provider_request_id,
                 error_message, platform
          FROM audit_log
          WHERE {" AND ".join(where)}
          ORDER BY occurred_at DESC
          LIMIT ${idx}"""
```

**Backward-compat:** rows pré-M.2a têm `platform="google"` (DEFAULT da column ALTER TABLE em migration 003/004). Nenhuma row NULL — safe.

### 5.2 Tool passthrough

```python
# src/mcp/tools/get_my_audit_log.py — return dict já vai propagar campo platform
# Sem mudanças necessárias se já fazia dict(r) no retorno
```

### 5.3 Test (regression)

```python
# tests/unit/test_get_my_audit_log_platform.py
async def test_audit_log_return_includes_platform_field(db):
    # Insert mixed rows: google + meta
    async with db.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="t@v4company.com", full_name="T")
        await audit_log.record(conn, manager_id=mid, ..., platform="google")
        await audit_log.record(conn, manager_id=mid, ..., platform="meta")

    rows = await get_my_audit_log({"manager_id": mid, "limit": 10})
    assert all("platform" in r for r in rows["data"])
    platforms = {r["platform"] for r in rows["data"]}
    assert "google" in platforms
    assert "meta" in platforms
```

---

## 6. Smoke runbook `phase-M-2b-bootstrap.md`

8 tests Wellington manual, ~45 min total:

| # | Test | Pre-condições | Sucesso | Failure modes investigation |
|---|---|---|---|---|
| **T1** | `meta_get_account_overview` happy path | OAuth Meta válido, real ad_account ATIVO (sugest: ICSER `act_1489398022911451` ou Wellington personal `act_383566922510173`), LAST_7_DAYS | Return contém current+previous+deltas+_warnings empty array. Fields populados (spend>0 se campanha ativa). x_fb_trace_id presente | Token expired → reconnect; account inativa → escolher outra; Graph 400 → investigar params time_range JSON encoding |
| **T2** | Per-value probe individual fields | Mesmo account T1 | Cada field tipo correto (spend float, impressions int, ctr % 0-100). frequency = impressions/reach calculation. conversions = sum(actions[type IN CONVERSION_ACTION_TYPES]) | F17/F18 (numeric format mismatch), action filtering wrong (e.g. "fb_pixel_purchase" vs "purchase" — Meta retorna ambos, parsing precisa filter set) |
| **T3** | account_status warning surfaced | Real account PAGAMENTO_PENDENTE (ML Antiguidades `act_370008662`) | `_warnings: ["account_status=PAGAMENTO_PENDENTE — métricas..."]` presente. Tool ainda retorna métricas válidas (sem fail) | Warning PT-BR string correto (NÃO numeric code) |
| **T4** | Token expiry warning surfaced | UPDATE Supabase manual: `UPDATE meta_oauth_connections SET token_expires_at = NOW() + INTERVAL '5 days' WHERE manager_id = '<wellington_id>';` (dev only — restaurar após teste) | `_warnings: ["Token OAuth Meta expira em 5 dias..."]` presente | Restore: `SET token_expires_at = NOW() + INTERVAL '60 days'` (ou re-OAuth) |
| **T5** | PT-BR error translation | Invalid ad_account_id (`act_999999999`), invalid date format | Tool retorna `{"status": "error", "error_message": "..."}` em PT-BR (NÃO Python traceback raw, NÃO English) | Fallback English exposed → bug to_friendly_meta_error |
| **T6** | data-deletion-callback synthetic | `python scripts/test_meta_deletion_callback.py` (gera signed_request HMAC-valid local) → curl POST endpoint | Return `{url, confirmation_code}` válidos. audit_log row criada com operation=meta_data_deletion_request | Signature invalid → 400 (verify META_APP_SECRET match); persistence falhou → debug audit_log insert |
| **T7** | Revoke button UX | Admin UI logado | Modal abre, confirm dispara POST /oauth/meta/revoke, redirect /admin?meta_revoked=1, card mostra "Sem conexão Meta ativa" | HTMX/JS errors no console; modal não fecha; redirect URL errado |
| **T8** | Refresh button UX | Admin UI logado + adicionar 1 ad account nova no BM Meta antes do teste | Click "Atualizar lista" → redirect /admin?meta_refreshed=1 + card mostra nova account na lista | Token <7d → 422 PT-BR; nova account não aparece → upsert lógica falha; race condition se 2 clicks rápidos |

### 6.1 Per-value probe convention reminder

Mesma convention de Sprint 3b.19A.1 — cada campo validado em real Graph response antes de claim "schema field works". **Especialmente importante pra `actions[]` (Meta tem 50+ action types possíveis, parsing wrong vira metric incorreto silencioso).**

### 6.2 Script helper T6 (`scripts/test_meta_deletion_callback.py`)

```python
"""Gerar signed_request HMAC-valid pra testar /oauth/meta/data-deletion-callback localmente."""
import base64
import hashlib
import hmac
import json
import sys

APP_SECRET = sys.argv[1] if len(sys.argv) > 1 else input("META_APP_SECRET: ")

payload = {
    "algorithm": "HMAC-SHA256",
    "user_id": "9999999999",
    "expires": 1747824000,
    "issued_at": 1747820400,
}
payload_json = json.dumps(payload, separators=(",", ":"))
payload_b64 = base64.urlsafe_b64encode(payload_json.encode()).decode().rstrip("=")
sig = hmac.new(APP_SECRET.encode(), payload_b64.encode(), hashlib.sha256).digest()
sig_b64 = base64.urlsafe_b64encode(sig).decode().rstrip("=")
print(f"{sig_b64}.{payload_b64}")

# Usage:
# python scripts/test_meta_deletion_callback.py <META_APP_SECRET>
# curl -X POST https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/oauth/meta/data-deletion-callback \
#   -d "signed_request=<output_above>"
```

---

## 7. Meta App Review submit (Task G — Wellington fora-MCP)

### 7.1 Pré-requisitos validados em M.2b

| Item | URL | Owner |
|---|---|---|
| Privacy policy | `/legal/privacy` | M.1.1 shipped |
| Terms of service | `/legal/terms` | M.1.1 shipped |
| Data deletion callback URL | `/oauth/meta/data-deletion-callback` | M.2b 3.1 ship |
| User data deletion status URL | `/legal/data-deletion-status/{code}` | M.2b 3.1 ship |

### 7.2 Wellington wizard pós-M.2b

1. **Meta App settings → App Review tab**
2. **Request advanced permissions** (3 scopes):
   - `ads_read`: "Internal V4 Company tool — managers consultam métricas (spend/impressions/conversions/ROAS) de 12 BM ad accounts via Claude/MCP. Tool meta_get_account_overview é primary use case."
   - `ads_management`: "Future M.3+ tools (campaign CRUD, bid adjustments). V0 read-only. Solicitar upfront pra evitar 2 review rounds."
   - `business_management`: "Listar ad accounts sob BM V4 Lima Soares & Co. Sem essa permission, manager precisa hardcoded list. Plataforma standard."
3. **Screencast required** (~3-5 min):
   - Login fluxo `/oauth/meta/start`
   - Granular permissions screen (user consent — Meta dashboard)
   - Callback redirect `/admin?meta_connected=1`
   - Card OAuth Meta no admin mostrando connection ativa
   - Demo `meta_get_account_overview` via Claude Desktop terminal:
     - Comando real ad_account_id query
     - Response PT-BR formatado (current+previous+deltas+warnings)
4. **Demo video upload** Meta App settings
5. **Submit** → Meta review timeline 5-30 dias business

### 7.3 Fallback se rejected

Dev Mode permite 25 admins sem App Review. M.X+ adiciona 3 colaboradores V4 LS&Co como admins enquanto re-submit App Review com feedback adjustments.

---

## 8. Testing Strategy

### 8.1 Unit tests (~30 novos)

| Module | Tests | Foco |
|---|---|---|
| `account_overview.py` | ~20 | date math, deltas (incluindo previous=0 edge), action filtering, warnings, parse_insights edge cases |
| `_verify_meta_signed_request` (em test_meta_signed_request.py) | ~8 | HMAC valid/invalid, base64url padding, missing algorithm, json malformed |
| `get_my_audit_log` (platform field) | ~2 | mixed google+meta rows return platform field; backward-compat NULL platform → google default |

### 8.2 Integration tests (~5 novos)

| Test | Mocks | Foco |
|---|---|---|
| `test_meta_get_account_overview.py` happy | `patch("src.mcp.tools.meta_get_account_overview.run_meta_graph_get", AsyncMock(side_effect=[current_body, previous_body]))` + DB fixtures (meta_ad_accounts row + meta_oauth_connections valid) | full pipeline: oc fetch + account fetch + 2 graph calls + parse + deltas + warnings empty + return shape |
| `test_meta_get_account_overview.py` account_status_warning | Same as happy + meta_ad_accounts row com `account_status=3` (PAGAMENTO_PENDENTE) | `_warnings: ["account_status=PAGAMENTO_PENDENTE — ..."]` presente |
| `test_meta_get_account_overview.py` token_expired_warning | Same as happy + meta_oauth_connections row com `token_expires_at = now + 5d` | `_warnings: ["Token OAuth Meta expira em 5 dias..."]` presente |
| `test_meta_get_account_overview.py` no_oc | DB sem meta_oauth_connections active | return `{"status": "error", "error_message": "Nenhuma conexão Meta ativa..."}` |
| `test_meta_data_deletion_callback.py` | curl synthetic signed_request HMAC-valid via TestClient + `monkeypatch.setenv("META_APP_SECRET", "test_secret")` | audit_log insert (operation=meta_data_deletion_request) + return shape `{url, confirmation_code}` + invalid signature → 400 |
| `test_meta_refresh_accounts.py` | respx mock httpx `/me/adaccounts` + meta_oauth_connections fixture | upsert + grant + audit_log row + redirect /admin?meta_refreshed=1 + token expired → 422 |

**Padrão para tool integration tests:** mock `run_meta_graph_get` diretamente (não respx do facebook_business SDK) — testa comportamento da tool, não SDK internals. SDK behaviour já coberto em M.2a `test_meta_oauth_flow.py` integration test (real httpx via respx pra OAuth endpoints).

### 8.3 Smoke real (Wellington manual)

8 tests em `phase-M-2b-bootstrap.md` (Section 6).

### 8.4 Verification commands

```bash
# Pre-commit (mandatory)
python scripts/check_pre_push.py        # ruff + format + mypy + unit + non-DB integration (~30s)

# Pre-push full (mandatory — DB migration touch via 005? NÃO, M.2b sem migration. Mas OAuth flow integration test usa testcontainers)
python scripts/check_pre_push_full.py   # +integration via testcontainers (~60-90s, Docker required)
```

---

## 9. Risks & Open Questions

### 9.1 Riscos

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Meta Graph API quirks em actions[] parsing (fb_pixel_purchase vs purchase duplo-count) | MED | MED | Per-value probe T2 + filter set explícito `CONVERSION_ACTION_TYPES` (não pega tudo) |
| Date range JSON encoding edge cases (time_range = `{"since":"...","until":"..."}` requires double-quote escaping) | MED | LOW | Test T1 + unit test resolve_meta_date_window |
| Token expiry edge case: expira ENTRE 2 calls (current + previous) → 2ª falha | LOW | LOW | `run_meta_graph_get` raise `MetaAdsFriendlyError` (PT-BR `.message`), orchestrator capture genérico via `hasattr(e, "message")` retorna `{"status": "error", "error_message": ...}` consistent |
| App Review rejected primeira submissão | HIGH (industry norm) | LOW | Dev Mode fallback 25 admins; iterate feedback |
| HTMX vs vanilla form POST inconsistency em Revoke button | LOW | LOW | Vanilla form POST chosen (simpler, no HTMX dependency for state-mutating action) |
| Signed_request signature validation false-negative (legitimate Meta callback rejected) | LOW | MED | Conservative compare_digest + log warnings; manual signoff Wellington queue |
| Data deletion callback abuse (unauthed POST flood) | LOW | LOW | HMAC validation rejeita 99%; rate limit Cloud Run em endpoint level (post-V0 se issue real) |
| `meta_refresh_accounts` race condition (2 clicks rápidos) | LOW | LOW | DB upsert idempotente; meta_ad_accounts.upsert_many usa ON CONFLICT |

### 9.2 Open questions (decisões já feitas, listadas pra confirmation)

| Question | Decision |
|---|---|
| Single account_id ou multi? | Single (paridade Google get_account_overview) |
| Comparativo período anterior incluído? | SIM (paridade Google, custa 2 BUC) |
| Account_status warning surfaced? | SIM |
| Token expiry warning surfaced? | SIM (threshold <7d) |
| BUC throttle warning surfaced? | NÃO V0 (structlog warn já cobre) |
| Zero-spend warning surfaced? | NÃO V0 (manager deduz do `spend: 0`) |
| Data-deletion: V0 log only ou V1 actually delete? | V0 log + manual signoff (LGPD 30d window) |
| Sprint single ou split? | Single M.2b (paridade Google sprints maiores) |
| Per-value probes em smoke runbook? | SIM (convention 3b.19A.1) |

### 9.3 Out of scope (deferred pra M.3+ ou hold YAGNI)

- **Campaign breakdown em overview** — separate tool `meta_get_campaign_performance` (M.3+)
- **Actions individuais detalhadas** (purchase vs lead breakdown) — separate tool ou enhancement V1
- **Multi-account overview** (compare ICSER vs Fardim) — separate tool `meta_compare_accounts` (M.4+)
- **BUC throttle warning surface** — structlog warn cobre dev/ops; surface no return só se manager pedir
- **Public status page rich content** (timeline, contato form) — V0 minimal text suficiente pra App Review
- **Email alert Wellington pra data-deletion-request** — webhook V1 (manual via audit_log scan suficiente V0)
- **Cron processing deletion queue** — V0 manual signoff, automate em M.X+ se volume justifica

---

## 10. Pre-V0 checklist (antes de invocar writing-plans)

- [x] User aprovou Section 1 (architecture overview)
- [x] User aprovou Section 2 (tool meta_get_account_overview design)
- [x] User aprovou Section 3 (endpoints novos OAuth)
- [x] User aprovou Section 4 (UI admin extensions)
- [x] User aprovou Section 5 (smoke runbook + App Review)
- [x] Spec doc written + committed
- [ ] Spec self-review (placeholders, internal consistency, scope, ambiguity)
- [ ] User reviews written spec
- [ ] Invoke superpowers:writing-plans skill

---

**Última atualização:** 2026-05-25 (brainstorming session).
**Próximo:** spec self-review → user review → writing-plans skill.
