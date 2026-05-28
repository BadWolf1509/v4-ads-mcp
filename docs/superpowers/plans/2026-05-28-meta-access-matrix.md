# Meta Access Matrix + System User Token — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Trazer o acesso Meta pro painel admin (matriz gestor×conta) e fazer as tools Meta executarem via um token de system user compartilhado, com a matriz como gate real.

**Architecture:** Modelo B (ver spec `docs/superpowers/specs/2026-05-28-meta-access-matrix-design.md`). Token do system user vem do Secret Manager; `run_meta_graph_get` passa a usar esse token e a checar `manager_meta_account_access` antes de cada chamada (hard-gate). UI espelha o admin Google com abas Google|Meta. Sem migration nova (tabelas da M.1 já existem).

**Tech Stack:** Python 3.12, FastAPI + Jinja2 + Tailwind CDN + HTMX 2, asyncpg, facebook_business, pydantic-settings, pytest.

---

## File Structure

**Backend (modify):**
- `src/config.py` — novo setting `meta_system_user_token`
- `src/meta_ads/client.py` — `build_meta_api()` (system user) + exceções `MetaSystemUserTokenMissingError`, `MetaAccessDeniedError`
- `src/meta_ads/reports.py` — `run_meta_graph_get` usa `build_meta_api()` + hard-gate
- `src/db/repositories/manager_meta_account_access.py` — adicionar `copy_access`
- `src/auth/meta_oauth.py` — `meta_oauth_refresh_accounts` via system user + remove auto-grant
- `src/web/routes.py` — rotas Meta admin (access + accounts)
- `src/web/templates/admin/_subnav.html` — fix `startswith('/admin/accounts')`

**UI (create):**
- `src/web/templates/admin/_access_tabs.html` — barra de abas Google|Meta (acesso)
- `src/web/templates/admin/_accounts_tabs.html` — barra de abas Google|Meta (contas)
- `src/web/templates/admin/access_meta.html` — grid de acesso Meta
- `src/web/templates/admin/access_by_manager_meta.html` — view por-gestor Meta
- `src/web/templates/admin/access_manager_detail_meta.html` — detalhe por-gestor Meta
- `src/web/templates/admin/accounts_meta.html` — inventário Meta + status do token + refresh

**Tests:**
- `tests/unit/test_meta_client.py` — `build_meta_api()`
- `tests/unit/test_meta_reports_gate.py` — hard-gate
- `tests/integration/test_repositories.py` — `copy_access` Meta
- `tests/integration/test_meta_refresh_accounts.py` — sync via system user
- `tests/integration/test_admin_meta_access.py` — rotas admin Meta

---

## Phase 1 — Backend: token do system user + execução

### Task 1: `build_meta_api()` (system user) + config + exceções

**Files:**
- Modify: `src/config.py` (após `meta_app_secret`, linha ~41)
- Modify: `src/meta_ads/client.py`
- Test: `tests/unit/test_meta_client.py`

- [ ] **Step 1: Adicionar o setting**

Em `src/config.py`, logo após `meta_app_secret: str = ""`:

```python
    # Meta Ads — system user token (Modelo B, Secret Manager: meta-system-user-token).
    # Token NÃO expira; vazio = feature de execução Meta indisponível (erro PT-BR amigável).
    meta_system_user_token: str = ""
```

- [ ] **Step 2: Escrever o teste falhando**

Em `tests/unit/test_meta_client.py` (criar se não existir; já existe per CLAUDE.md M.2a):

```python
import pytest
from src.meta_ads import client


def test_build_meta_api_raises_when_token_missing(monkeypatch):
    monkeypatch.setenv("META_SYSTEM_USER_TOKEN", "")
    from src.config import Settings
    monkeypatch.setattr(client, "get_settings_for_test", None, raising=False)
    with pytest.raises(client.MetaSystemUserTokenMissingError):
        client.build_meta_api(system_user_token="", app_id="x", app_secret="y")


def test_build_meta_api_builds_with_system_user_token():
    api = client.build_meta_api(system_user_token="TKN", app_id="111", app_secret="sec")
    assert api is not None  # FacebookAdsApi instance
```

- [ ] **Step 3: Rodar o teste — deve falhar**

Run: `python -m pytest tests/unit/test_meta_client.py -k build_meta_api -v`
Expected: FAIL (`AttributeError: module ... has no attribute 'MetaSystemUserTokenMissingError'`)

- [ ] **Step 4: Implementar**

Em `src/meta_ads/client.py`, adicionar as exceções (junto das existentes) e a factory:

```python
class MetaSystemUserTokenMissingError(Exception):
    """Raised when the shared system-user token secret isn't configured."""


class MetaAccessDeniedError(Exception):
    """Raised when a manager has no grant for the requested Meta ad account."""

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


def build_meta_api(
    *,
    system_user_token: str,
    app_id: str,
    app_secret: str,
    api_version: str = META_GRAPH_API_VERSION,
) -> Any:
    """Build a FacebookAdsApi from the shared system-user token (Modelo B).

    Unlike build_meta_api_for_manager, no per-manager DB lookup and no expiry
    check (system-user tokens don't expire). Raises if the secret is empty.
    """
    if not system_user_token:
        raise MetaSystemUserTokenMissingError(
            "Token do system user Meta não configurado. "
            "O admin precisa subir o secret meta-system-user-token."
        )
    return build_facebook_ads_api(
        app_id=app_id,
        app_secret=app_secret,
        access_token=system_user_token,
    )
```

- [ ] **Step 5: Rodar o teste — deve passar**

Run: `python -m pytest tests/unit/test_meta_client.py -k build_meta_api -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/config.py src/meta_ads/client.py tests/unit/test_meta_client.py
git commit -m "feat(meta_ads): build_meta_api() system-user factory + access-denied error"
```

---

### Task 2: Hard-gate + rewire de token no `run_meta_graph_get`

**Files:**
- Modify: `src/meta_ads/reports.py:58-65` (substituir `build_meta_api_for_manager`) + inserir gate antes da chamada
- Test: `tests/unit/test_meta_reports_gate.py` (criar)

- [ ] **Step 1: Escrever o teste falhando**

```python
import pytest
from unittest.mock import AsyncMock, patch
from uuid import uuid4
from src.meta_ads import reports
from src.meta_ads.client import MetaAccessDeniedError


@pytest.mark.asyncio
async def test_run_meta_graph_get_denies_without_grant():
    mid, sid = uuid4(), uuid4()
    with (
        patch("src.meta_ads.reports.manager_meta_account_access.can_manager_access",
              AsyncMock(return_value=False)),
        patch("src.meta_ads.reports.connection.get_pool"),
    ):
        with pytest.raises(MetaAccessDeniedError):
            await reports.run_meta_graph_get(
                manager_id=mid, session_id=sid,
                edge="/act_999/insights", params={"ad_account_id": "act_999"},
                operation_name="meta_get_campaign_performance",
            )
```

- [ ] **Step 2: Rodar — deve falhar**

Run: `python -m pytest tests/unit/test_meta_reports_gate.py -v`
Expected: FAIL (gate não existe → tenta chamar API / build)

- [ ] **Step 3: Implementar o gate + rewire**

Em `src/meta_ads/reports.py`, no topo trocar o import:

```python
from src.db.repositories import audit_log, manager_meta_account_access
from src.meta_ads.client import MetaAccessDeniedError, build_meta_api
```

Substituir a construção da api (linha ~59) e inserir o gate ANTES:

```python
    settings = get_settings()

    # Hard-gate (Modelo B): manager precisa de grant na conta. O token é compartilhado,
    # então a matriz manager_meta_account_access é o ÚNICO freio.
    ad_account_id = (params or {}).get("ad_account_id")
    if ad_account_id:
        async with connection.get_pool().acquire() as conn:
            allowed = await manager_meta_account_access.can_manager_access(
                conn, manager_id, ad_account_id, level="read"
            )
        if not allowed:
            if audit_this_call:
                async with connection.get_pool().acquire() as conn:
                    await audit_log.record(
                        conn,
                        manager_id=manager_id,
                        session_id=session_id,
                        customer_id=ad_account_id,
                        action_type="read",
                        operation=operation_name,
                        params_summary=params_summary,
                        status="denied",
                        error_message="Gestor sem acesso à conta Meta",
                        platform="meta",
                    )
            raise MetaAccessDeniedError(
                f"Você não tem acesso à conta {ad_account_id}. "
                f"Peça ao admin pra liberar no painel."
            )

    api = build_meta_api(
        system_user_token=settings.meta_system_user_token,
        app_id=settings.meta_app_id,
        app_secret=settings.meta_app_secret,
    )
```

> Nota: contas-scoped Meta calls já carregam `ad_account_id` em `params` (contrato que o BUC em `reports.py:98` já assume). Calls account-agnostic pulam o gate.

- [ ] **Step 4: Rodar — deve passar**

Run: `python -m pytest tests/unit/test_meta_reports_gate.py -v`
Expected: PASS

- [ ] **Step 5: Rodar a suíte Meta existente (regressão)**

Run: `python -m pytest tests/ -k meta -v`
Expected: PASS (tools de perf chamam `run_meta_graph_get`; ajustar mocks que esperavam `build_meta_api_for_manager` → agora `build_meta_api` + `can_manager_access`). Onde testes mockam acesso, adicionar `patch("src.meta_ads.reports.manager_meta_account_access.can_manager_access", AsyncMock(return_value=True))`.

- [ ] **Step 6: Commit**

```bash
git add src/meta_ads/reports.py tests/unit/test_meta_reports_gate.py tests/integration/test_meta_*.py
git commit -m "feat(meta_ads): hard-gate can_manager_access + system-user token em run_meta_graph_get"
```

---

## Phase 2 — Backend: repo + sync

### Task 3: `copy_access` no repo Meta

**Files:**
- Modify: `src/db/repositories/manager_meta_account_access.py` (remover o comentário NOTE final, linhas 137-139)
- Test: `tests/integration/test_repositories.py`

- [ ] **Step 1: Escrever o teste falhando**

Em `tests/integration/test_repositories.py` (perto dos testes Meta existentes, ~linha 520):

```python
@pytest.mark.integration
async def test_meta_copy_access_replaces_destination(db):
    async with db.acquire() as conn:
        # seed: 2 managers, 2 accounts, grants no manager A
        ... # criar managers m_a, m_b + meta_ad_accounts act_1, act_2 (use helpers do arquivo)
        await manager_meta_account_access.grant(conn, manager_id=m_a, ad_account_id="act_1")
        await manager_meta_account_access.grant(conn, manager_id=m_b, ad_account_id="act_2")
        n = await manager_meta_account_access.copy_access(
            conn, from_manager_id=m_a, to_manager_id=m_b, granted_by=m_a
        )
        assert n == 1
        accts = await manager_meta_account_access.list_accounts_for_manager(conn, m_b)
        assert {a.ad_account_id for a in accts} == {"act_1"}  # destino virou cópia do origem
```

- [ ] **Step 2: Rodar — deve falhar**

Run: `python -m pytest tests/integration/test_repositories.py -k meta_copy_access -v` (requer Docker/testcontainers)
Expected: FAIL (`copy_access` não existe)

- [ ] **Step 3: Implementar** (mirror exato do Google em `manager_account_access.py:137-160`)

Em `src/db/repositories/manager_meta_account_access.py`, substituir o comentário NOTE final por:

```python
async def copy_access(
    conn: asyncpg.Connection,
    *,
    from_manager_id: UUID,
    to_manager_id: UUID,
    granted_by: UUID,
) -> int:
    """Replace destination's Meta access with source's access. Atomic."""
    async with conn.transaction():
        await conn.execute(
            "DELETE FROM manager_meta_account_access WHERE manager_id = $1",
            to_manager_id,
        )
        result = await conn.execute(
            """INSERT INTO manager_meta_account_access
                   (manager_id, ad_account_id, access_level, granted_by)
               SELECT $1, ad_account_id, access_level, $2
               FROM manager_meta_account_access
               WHERE manager_id = $3""",
            to_manager_id,
            granted_by,
            from_manager_id,
        )
    return int(result.rsplit(" ", 1)[-1])
```

- [ ] **Step 4: Rodar — deve passar**

Run: `python -m pytest tests/integration/test_repositories.py -k meta_copy_access -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/db/repositories/manager_meta_account_access.py tests/integration/test_repositories.py
git commit -m "feat(db): copy_access para manager_meta_account_access (paridade Google)"
```

---

### Task 4: Sync de inventário via system user (drop auto-grant)

**Files:**
- Modify: `src/auth/meta_oauth.py:466-550` (`meta_oauth_refresh_accounts`)
- Test: `tests/integration/test_meta_refresh_accounts.py`

- [ ] **Step 1: Ajustar o teste**

O refresh deixa de usar o token pessoal e o auto-grant. Atualizar `test_meta_refresh_accounts.py`:

```python
# Esperar que o refresh:
#  - use build_meta_api (system user), não decrypt do token pessoal
#  - faça upsert_many em meta_ad_accounts
#  - NÃO chame manager_meta_account_access.grant
# Assert: após refresh, meta_ad_accounts populado; nenhuma linha nova em manager_meta_account_access.
```

- [ ] **Step 2: Rodar — deve falhar**

Run: `python -m pytest tests/integration/test_meta_refresh_accounts.py -v`
Expected: FAIL (ainda faz auto-grant / usa token pessoal)

- [ ] **Step 3: Implementar**

Em `meta_oauth_refresh_accounts` ([`src/auth/meta_oauth.py:466`](../../../src/auth/meta_oauth.py)):
1. Trocar a obtenção do token: em vez de `get_active_for_manager` + `decrypt_refresh_token`, usar `settings.meta_system_user_token` direto na chamada `/me/adaccounts` (o `/me` aqui é o system user). Se vazio → HTTP 422 PT-BR "token do system user não configurado".
2. Remover o bloco `for a in accounts_payload: await manager_meta_account_access.grant(...)` (linhas ~526-531) — no Modelo B o grant é da matriz, não do sync.
3. Manter `upsert_many` + audit (`operation="meta_refresh_accounts"`).

```python
    settings = get_settings()
    token = settings.meta_system_user_token
    if not token:
        raise HTTPException(status_code=422, detail="Token do system user Meta não configurado.")

    async with httpx.AsyncClient(timeout=30.0) as http:
        adacc_resp = await http.get(
            f"{META_GRAPH_BASE}/me/adaccounts",
            params={
                "fields": "id,name,business,account_status,currency,timezone_name",
                "access_token": token,
            },
        )
        ad_accounts_data = adacc_resp.json().get("data", []) if adacc_resp.status_code == 200 else []
    # ... montar accounts_payload (igual hoje) ...
    async with pool.acquire() as conn:
        if accounts_payload:
            await meta_ad_accounts.upsert_many(conn, accounts_payload)
        # (sem loop de grant)
        await audit_log.record(conn, manager_id=user.id, session_id=None, customer_id=None,
            action_type="auth", operation="meta_refresh_accounts",
            target_count=len(accounts_payload), status="success", platform="meta")
```

- [ ] **Step 4: Rodar — deve passar**

Run: `python -m pytest tests/integration/test_meta_refresh_accounts.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/auth/meta_oauth.py tests/integration/test_meta_refresh_accounts.py
git commit -m "feat(meta_ads): refresh de contas via system user; matriz controla grants"
```

---

## Phase 3 — Admin UI: matriz de acesso Meta

### Task 5: Abas + rota do grid Meta

**Files:**
- Create: `src/web/templates/admin/_access_tabs.html`
- Create: `src/web/templates/admin/access_meta.html`
- Modify: `src/web/templates/admin/access.html` (incluir as abas)
- Modify: `src/web/templates/admin/_subnav.html:13` (startswith em Contas)
- Modify: `src/web/routes.py` (nova rota `/admin/access/meta`)
- Test: `tests/integration/test_admin_meta_access.py`

- [ ] **Step 1: Criar a barra de abas** — `_access_tabs.html`:

```html
{# Abas Google|Meta pras telas de acesso #}
<div class="v4-tabs" role="tablist" style="margin-bottom:1rem">
  <a href="/admin/access" role="tab"
     class="v4-tab {% if not request.url.path.startswith('/admin/access/meta') and 'meta' not in request.url.path %}is-active{% endif %}">Google</a>
  <a href="/admin/access/meta" role="tab"
     class="v4-tab {% if 'meta' in request.url.path %}is-active{% endif %}">Meta</a>
</div>
```

- [ ] **Step 2: Incluir as abas no template Google** — em `access.html`, logo após `<header>` (linha ~12) adicionar `{% include "admin/_access_tabs.html" %}`.

- [ ] **Step 3: Fix subnav** — em `_subnav.html:13`, trocar `request.url.path == '/admin/accounts'` por `request.url.path.startswith('/admin/accounts')`.

- [ ] **Step 4: Escrever o teste falhando**

```python
@pytest.mark.integration
async def test_admin_access_meta_renders(client_admin):
    r = await client_admin.get("/admin/access/meta")
    assert r.status_code == 200
    assert "Matriz de acessos" in r.text  # grid Meta renderizou

@pytest.mark.integration
async def test_admin_access_meta_requires_admin(client_gestor):
    r = await client_gestor.get("/admin/access/meta")
    assert r.status_code == 403
```

- [ ] **Step 5: Rodar — deve falhar**

Run: `python -m pytest tests/integration/test_admin_meta_access.py -k renders -v`
Expected: FAIL (404 — rota não existe)

- [ ] **Step 6: Criar o template `access_meta.html`** — mirror **exato** de `admin/access.html` com estas substituições (o engenheiro deve abrir `access.html` e copiar, trocando):
  - `customer_id` → `ad_account_id` (em `data-account-id`, `hx-vals`, hidden inputs, filtro JS)
  - `a.descriptive_name` → `a.account_name`; adicionar linha cliente: `<div class="text-xs text-v4-gray-300">{{ a.business_name }}</div>`
  - badge de status: usar `a.account_status` (1=●ativo verde; outros=●cinza/vermelho) ao lado do nome
  - endpoints: `/admin/access/toggle` → `/admin/access/meta/toggle`; `/admin/access/bulk-grant` → `/admin/access/meta/bulk-grant`; `/admin/access/bulk-copy` → `/admin/access/meta/bulk-copy`; link "por gestor" → `/admin/access/meta/by-manager`
  - incluir `{% include "admin/_access_tabs.html" %}` após o header
  - texto do empty_state de contas: "Nenhuma conta Meta sincronizada. Rode o refresh em Contas → Meta."

- [ ] **Step 7: Adicionar a rota** em `src/web/routes.py` (mirror de `admin_access`, linha 761):

```python
@router.get("/admin/access/meta", response_class=HTMLResponse)
async def admin_access_meta(
    request: Request,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
) -> HTMLResponse:
    _require_admin(user)
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        managers_rows = await conn.fetch(
            "SELECT id, email, full_name, role FROM managers WHERE is_active = true ORDER BY email"
        )
        from src.db.repositories import meta_ad_accounts
        accounts = await meta_ad_accounts.list_all(conn)
        access_rows = await conn.fetch(
            "SELECT manager_id, ad_account_id FROM manager_meta_account_access"
        )
    access_set = {(str(r["manager_id"]), r["ad_account_id"]) for r in access_rows}
    pending = await pending_invites_count()
    return templates.TemplateResponse(
        request, "admin/access_meta.html",
        {"current_user": user, "managers_list": [dict(r) for r in managers_rows],
         "accounts": accounts, "access_set": access_set, "pending_invites_count": pending},
    )
```

- [ ] **Step 8: Rodar — deve passar**

Run: `python -m pytest tests/integration/test_admin_meta_access.py -k "renders or requires_admin" -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add src/web/templates/admin/_access_tabs.html src/web/templates/admin/access_meta.html src/web/templates/admin/access.html src/web/templates/admin/_subnav.html src/web/routes.py tests/integration/test_admin_meta_access.py
git commit -m "feat(web): aba Meta na matriz de acesso (grid)"
```

---

### Task 6: Mutations Meta (toggle, bulk-grant, bulk-copy, by-manager, detail)

**Files:**
- Modify: `src/web/routes.py` (5 rotas novas, mirror das Google)
- Create: `src/web/templates/admin/access_by_manager_meta.html`, `access_manager_detail_meta.html`
- Test: `tests/integration/test_admin_meta_access.py`

- [ ] **Step 1: Escrever os testes falhando**

```python
@pytest.mark.integration
async def test_admin_access_meta_toggle_grants_then_revokes(client_admin, seeded_meta):
    mid, aid = seeded_meta["manager_id"], seeded_meta["ad_account_id"]
    r1 = await client_admin.post("/admin/access/meta/toggle",
        data={"manager_id": str(mid), "ad_account_id": aid})
    assert "checked" in r1.text
    r2 = await client_admin.post("/admin/access/meta/toggle",
        data={"manager_id": str(mid), "ad_account_id": aid})
    assert "checked" not in r2.text
```

- [ ] **Step 2: Rodar — deve falhar** (404). Run: `python -m pytest tests/integration/test_admin_meta_access.py -k toggle -v`

- [ ] **Step 3: Implementar as 5 rotas** em `routes.py` (mirror exato das Google `admin_access_toggle`:894, `admin_access_bulk_grant`:790, `admin_access_bulk_copy`:809, `admin_access_by_manager`:830, `admin_access_manager_detail`:860), trocando:
  - tabela `manager_account_access` → `manager_meta_account_access`; `customer_id` → `ad_account_id`
  - `google_ads_accounts` → `meta_ad_accounts`
  - redirects `/admin/access` → `/admin/access/meta`; templates `*_meta.html`
  - o fragmento HTMX do toggle aponta pra `/admin/access/meta/toggle`

Exemplo (toggle):

```python
@router.post("/admin/access/meta/toggle", response_class=HTMLResponse)
async def admin_access_meta_toggle(
    request: Request,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
    manager_id: str = Form(...),
    ad_account_id: str = Form(...),
) -> HTMLResponse:
    _require_admin(user)
    from src.db.repositories import manager_meta_account_access
    pool = connection.get_pool()
    target_mid = UUID(manager_id)
    async with pool.acquire() as conn:
        exists = await conn.fetchval(
            "SELECT 1 FROM manager_meta_account_access WHERE manager_id=$1 AND ad_account_id=$2",
            target_mid, ad_account_id)
        if exists:
            await manager_meta_account_access.revoke(conn, manager_id=target_mid, ad_account_id=ad_account_id)
            granted = False
        else:
            await manager_meta_account_access.grant(conn, manager_id=target_mid,
                ad_account_id=ad_account_id, access_level="write", granted_by=user.id)
            granted = True
    state = "checked" if granted else ""
    return HTMLResponse(
        f'<input type="checkbox" {state} hx-post="/admin/access/meta/toggle" '
        f'hx-vals=\'{{"manager_id": "{manager_id}", "ad_account_id": "{ad_account_id}"}}\' '
        f'hx-trigger="change" hx-swap="outerHTML">')
```

Bulk-copy usa o novo `manager_meta_account_access.copy_access` (Task 3). By-manager/detail: mirror dos templates Google trocando os campos (incluir `_access_tabs.html`).

- [ ] **Step 4: Rodar — deve passar**

Run: `python -m pytest tests/integration/test_admin_meta_access.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/web/routes.py src/web/templates/admin/access_by_manager_meta.html src/web/templates/admin/access_manager_detail_meta.html tests/integration/test_admin_meta_access.py
git commit -m "feat(web): toggle/bulk-grant/copy/by-manager Meta access"
```

---

## Phase 4 — Admin UI: inventário Meta + token status

### Task 7: Aba Meta em Contas + status do token + refresh

**Files:**
- Create: `src/web/templates/admin/_accounts_tabs.html`, `accounts_meta.html`
- Modify: `src/web/templates/admin/accounts.html` (incluir abas)
- Modify: `src/web/routes.py` (rota `/admin/accounts/meta`)
- Test: `tests/integration/test_admin_meta_access.py`

- [ ] **Step 1: Criar `_accounts_tabs.html`** (mesmo padrão do `_access_tabs.html`, links `/admin/accounts` e `/admin/accounts/meta`).

- [ ] **Step 2: Incluir abas em `accounts.html`** (após o header). E incluir `_accounts_tabs.html`.

- [ ] **Step 3: Escrever o teste falhando**

```python
@pytest.mark.integration
async def test_admin_accounts_meta_renders_with_token_status(client_admin, monkeypatch):
    monkeypatch.setenv("META_SYSTEM_USER_TOKEN", "")
    r = await client_admin.get("/admin/accounts/meta")
    assert r.status_code == 200
    assert "Token do system user" in r.text
    assert "não configurado" in r.text  # status quando secret vazio
```

- [ ] **Step 4: Rodar — deve falhar** (404). Run: `python -m pytest tests/integration/test_admin_meta_access.py -k accounts_meta -v`

- [ ] **Step 5: Criar `accounts_meta.html`** — tabela do inventário (`account_name`, `business_name`, status badge, `currency`, `synced_at`) + widget de status do token + botão refresh:

```html
{% extends "_base.html" %}
{% block content %}
<section class="max-w-7xl mx-auto py-6 px-4">
  <header class="mb-6"><h1 class="text-3xl font-extrabold">Contas Meta</h1></header>
  {% include "admin/_accounts_tabs.html" %}

  <div class="v4-card mb-4 flex items-center gap-3">
    <span class="font-semibold">Token do system user:</span>
    {% if token_configured %}
      <span class="v4-badge v4-badge--success">configurado ✓</span>
    {% else %}
      <span class="v4-badge v4-badge--danger">não configurado</span>
      <span class="text-sm text-v4-gray-700">Suba o secret <code>meta-system-user-token</code>.</span>
    {% endif %}
    <form method="POST" action="/oauth/meta/refresh-accounts" class="ml-auto">
      <button type="submit" class="v4-btn v4-btn--small v4-btn--secondary">Sincronizar contas</button>
    </form>
  </div>

  <div class="overflow-x-auto v4-card" style="padding:0">
    <table class="v4-table v4-table--compact">
      <thead><tr><th>Conta</th><th>Cliente</th><th>Status</th><th>Moeda</th><th>Sync</th></tr></thead>
      <tbody>
        {% for a in accounts %}
        <tr>
          <td><strong>{{ a.account_name }}</strong><div class="text-xs font-mono text-v4-gray-300">{{ a.ad_account_id }}</div></td>
          <td>{{ a.business_name or "—" }}</td>
          <td>{% if a.account_status == 1 %}<span style="color:#16a34a">●ativo</span>{% else %}<span style="color:#dc2626">●{{ a.account_status }}</span>{% endif %}</td>
          <td>{{ a.currency or "—" }}</td>
          <td class="text-xs text-v4-gray-300">{{ a.synced_at.strftime('%d/%m %H:%M') }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</section>
{% endblock %}
```

- [ ] **Step 6: Adicionar a rota** em `routes.py` (mirror de `admin_accounts`:738):

```python
@router.get("/admin/accounts/meta", response_class=HTMLResponse)
async def admin_accounts_meta(
    request: Request,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
) -> HTMLResponse:
    _require_admin(user)
    from src.db.repositories import meta_ad_accounts
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        accounts = await meta_ad_accounts.list_all(conn)
    pending = await pending_invites_count()
    token_configured = bool(get_settings().meta_system_user_token)
    return templates.TemplateResponse(
        request, "admin/accounts_meta.html",
        {"current_user": user, "accounts": accounts,
         "token_configured": token_configured, "pending_invites_count": pending},
    )
```

- [ ] **Step 7: Rodar — deve passar**

Run: `python -m pytest tests/integration/test_admin_meta_access.py -k accounts_meta -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add src/web/templates/admin/_accounts_tabs.html src/web/templates/admin/accounts_meta.html src/web/templates/admin/accounts.html src/web/routes.py tests/integration/test_admin_meta_access.py
git commit -m "feat(web): aba Meta em Contas + status do token system user + refresh"
```

---

## Phase 5 — Verificação final

### Task 8: Full sweep + sanity

- [ ] **Step 1: Rodar a verificação completa**

Run: `python scripts/check_pre_push.py`
Expected: 5/5 PASS (ruff + format + mypy + unit + non-DB integration)

- [ ] **Step 2: Full sweep (toca reports.py + config/secret)**

Run: `python scripts/check_pre_push_full.py`
Expected: 6/6 PASS (requer Docker). Sem Docker (Windows Wellington): rodar via CI no push.

- [ ] **Step 3: Grep de regressão (renomeações)**

Confirmar que nada ainda referencia o caminho antigo de execução nas tools:
Run: `grep -rn "build_meta_api_for_manager" src/mcp/ src/meta_ads/reports.py`
Expected: zero matches em `src/mcp/` e em `reports.py` (a função permanece só pro fluxo OAuth dormante).

- [ ] **Step 4: Commit final (se houver ajustes)**

```bash
git add -A
git commit -m "chore(meta_ads): ajustes finais Meta access matrix"
```

---

## Rollout (manual, fora do código — gestor/admin)

1. Criar system user no BM V4 + atribuir as ~12 contas + gerar token (`ads_read`, `ads_management`, `business_management`).
2. Subir secret (F47 — arquivo binary, nunca pipe):
   ```powershell
   python -c "open('tmp.bin','wb').write(b'<TOKEN>')"
   gcloud secrets create meta-system-user-token --data-file=tmp.bin   # ou versions add se já existe
   Remove-Item tmp.bin; Clear-History
   ```
3. Cloud Run: `gcloud run services update v4-ads-mcp --region=southamerica-east1 --update-secrets="META_SYSTEM_USER_TOKEN=meta-system-user-token:latest"`.
4. `/admin/accounts/meta` → "Sincronizar contas" (popula inventário via system user).
5. `/admin/access/meta` → conceder acesso por gestor.

## Self-review (preenchido)

- **Cobertura da spec:** §3 data model (sem migration) ✓ Task 3; §4 token Secret Manager ✓ Task 1 + rollout; §5 hard-gate ✓ Task 2; §6 sync ✓ Task 4; §7 opt-in ✓ (grants só via matriz, Task 4 remove auto-grant); §8 UI abas+grid+por-gestor+inventário+token status ✓ Tasks 5-7; §9 audit ✓ (preservado). D1/D2/D3 cobertos. OAuth por-gestor dormante: `build_meta_api_for_manager` mantida (Task 8 step 3 confirma sem uso em mcp/reports).
- **Placeholders:** test de `copy_access` (Task 3 step 1) tem `...` pro seed — o engenheiro reusa os helpers de seed já presentes em `test_repositories.py` (managers/meta_ad_accounts). Demais steps com código completo.
- **Consistência de tipos:** `ad_account_id` (str) consistente; `can_manager_access(conn, manager_id, ad_account_id, level=)` bate com o repo; `build_meta_api(system_user_token=, app_id=, app_secret=)` consistente entre Task 1 e Task 2.

## Out-of-scope (ver spec §11)
Remover OAuth por-gestor; matriz unificada Google+Meta; papéis ricos; mutates Meta (M.16+) e teste de `ads_management` write; retrofit hard-gate no Google.
