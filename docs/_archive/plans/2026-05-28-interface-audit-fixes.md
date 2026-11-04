# Interface Audit Fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Corrigir todos os achados da auditoria de interface (2026-05-28) — segurança, bugs funcionais, acessibilidade e consistência/design-system — sem regressões.

**Architecture:** Mudanças concentradas em `src/web/` (routes, templates, static CSS) + `src/auth/` (OAuth pages) + 2 middlewares novos (CSRF Origin-check + security headers). 5 fases independentemente shippáveis; comece pela Segurança. Sem migration de DB.

**Tech Stack:** Python 3.12, FastAPI + Starlette middleware, Jinja2 (autoescape on) + Tailwind(CDN) + HTMX 2, pytest + httpx.

**Source:** achados da auditoria de 2026-05-28 (4 agentes paralelos; 2 falsos positivos já filtrados: route-ordering Google by-manager [ordem está correta], `accounts_meta.synced_at` [coluna é NOT NULL DEFAULT now()]).

---

## File Structure

**Backend (modify):**
- `src/auth/oauth.py` — escapar `_error_page`/`_success_page` (XSS); UUID guards
- `src/auth/meta_oauth.py` — URL-encode redirects de erro
- `src/web/routes.py` — escapar fragmentos de toggle; UUID→404 guards; logout POST; registrar Jinja filter de status; status label
- `src/web/middleware.py` — **novo**: `CSRFOriginMiddleware` + `SecurityHeadersMiddleware`
- `src/web/app.py` (ou onde o FastAPI app é montado — localizar) — registrar os 2 middlewares
- `src/web/templates/_components.html` — pagination preserva filtros; search_input aria-label; close-button aria-label; definir/remover classes fantasma; remover macros mortas

**Templates (modify):** `admin/access.html`, `admin/access_meta.html`, `admin/access_by_manager.html`, `admin/accounts.html`, `admin/accounts_meta.html`, `admin/invites.html`, `admin/index.html`, `dashboard.html`, `audit.html`, `admin/audit.html`, `sessions/detail.html`, `login.html`, `access_denied.html`, `error.html`, `legal/data_deletion_status.html`, `_base.html`, `_subnav.html`, `_access_tabs.html`, `_accounts_tabs.html`

**CSS (modify):** `src/web/static/v4-components.css` (+ `v4-tokens.css` para tokens novos)

**Dead code (remove):** `src/meta_ads/client.py::build_meta_api_for_manager`; macros não usadas em `_components.html`

> **Convenções gerais (todas as tasks):** rodar `python scripts/check_pre_push.py` antes de cada commit (5/5). Integration tests testcontainers NÃO rodam local (sem Docker) → validam no CI; ainda assim escrevê-los. Commitar, NÃO dar push (controller faz). ruff auto-formata. mypy strict. Jinja autoescape está ON (não usar `| safe` com dado de usuário).

---

# PHASE 1 — Segurança

### Task 1: Escapar HTML nas páginas OAuth (XSS refletido)

**Files:**
- Modify: `src/auth/oauth.py` (`_error_page` ~390, `_success_page` ~375, callers ~203/211/253)
- Modify: `src/auth/meta_oauth.py` (redirect de erro ~175)
- Test: `tests/unit/test_oauth_pages_escape.py` (criar)

- [ ] **Step 1: Teste falhando**

```python
from src.auth.oauth import _error_page, _success_page


def test_error_page_escapes_html():
    resp = _error_page("<script>alert(1)</script>", status=400)
    body = resp.body.decode()
    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;" in body


def test_success_page_escapes_email():
    resp = _success_page("a@b.com<script>")
    assert "<script>" not in resp.body.decode()
```

- [ ] **Step 2: Rodar — FAIL.** `python -m pytest tests/unit/test_oauth_pages_escape.py -v`

- [ ] **Step 3: Implementar.** Em `src/auth/oauth.py`, adicionar `import html` no topo. Em `_error_page`, escapar `message` antes de interpolar: trocar `<p>{message}</p>` por `<p>{html.escape(message)}</p>`. Em `_success_page`, trocar `<code>{email}</code>` por `<code>{html.escape(email)}</code>`. (As mensagens já vêm formatadas pelos callers; escapar no ponto de render cobre todos.)

  Em `src/auth/meta_oauth.py`, o redirect de erro (~175) monta `f"/access-denied?reason=meta_oauth_error&detail={msg[:200]}"` — trocar por query encodado:
  ```python
  from urllib.parse import urlencode  # topo do arquivo
  qs = urlencode({"reason": "meta_oauth_error", "detail": msg[:200]})
  return RedirectResponse(f"/access-denied?{qs}", status_code=302)
  ```
  (O template `access_denied.html` já auto-escapa `{{ detail }}` — Jinja autoescape — então o XSS de 2º grau já está coberto; o encode evita injeção de query param adicional.)

- [ ] **Step 4: Rodar — PASS.** `python -m pytest tests/unit/test_oauth_pages_escape.py -v`
- [ ] **Step 5: `python scripts/check_pre_push.py` → 5/5.**
- [ ] **Step 6: Commit** `git add src/auth/oauth.py src/auth/meta_oauth.py tests/unit/test_oauth_pages_escape.py && git commit -m "fix(auth): escapar HTML em páginas OAuth (XSS refletido) + encode redirect Meta"`

---

### Task 2: Escapar fragmentos HTML dos toggles de acesso

**Files:**
- Modify: `src/web/routes.py` (`admin_access_toggle` ~1092-1133 Google; `admin_access_meta_toggle` ~845-880 Meta)
- Test: `tests/unit/test_toggle_fragment_escape.py` (criar — testa só a montagem do fragmento)

- [ ] **Step 1: Teste falhando** — extrair a montagem do fragmento numa função pura testável OU testar via a função. Plano: criar helper `_toggle_checkbox_fragment(*, post_url, vals: dict, checked: bool) -> str` em `routes.py` que escapa os valores, e os dois toggles passam a usá-lo.

```python
from src.web.routes import _toggle_checkbox_fragment


def test_toggle_fragment_escapes_injection():
    frag = _toggle_checkbox_fragment(
        post_url="/admin/access/meta/toggle",
        vals={"manager_id": "m1", "ad_account_id": "act_1' hx-on='evil"},
        checked=True,
    )
    assert "hx-on='evil" not in frag
    assert "&#x27;" in frag or "&#39;" in frag  # quote escaped
```

- [ ] **Step 2: Rodar — FAIL.**
- [ ] **Step 3: Implementar** o helper em `routes.py`:
```python
import html, json

def _toggle_checkbox_fragment(*, post_url: str, vals: dict[str, str], checked: bool) -> str:
    state = "checked" if checked else ""
    hx_vals = html.escape(json.dumps(vals), quote=True)
    return (
        f'<input type="checkbox" {state} hx-post="{post_url}" '
        f"hx-vals='{hx_vals}' hx-trigger=\"change\" hx-swap=\"outerHTML\">"
    )
```
  Trocar o retorno f-string nos DOIS toggles (`admin_access_toggle` e `admin_access_meta_toggle`) por `return HTMLResponse(_toggle_checkbox_fragment(post_url=..., vals={...}, checked=granted))`.

- [ ] **Step 4: Rodar — PASS.**
- [ ] **Step 5: check_pre_push 5/5.**
- [ ] **Step 6: Commit** `git add src/web/routes.py tests/unit/test_toggle_fragment_escape.py && git commit -m "fix(web): escapar valores nos fragmentos HTMX de toggle (XSS admin)"`

> Nota: isto resolve o chip de XSS spawnado anteriormente — fechar o chip depois.

---

### Task 3: Middleware CSRF (Origin/Referer check)

**Files:**
- Create: `src/web/middleware.py`
- Modify: app de montagem do FastAPI (localizar: grep `FastAPI(` em `src/`; provável `src/web/app.py` ou `src/main.py`)
- Test: `tests/integration/test_csrf_middleware.py` (criar)

- [ ] **Step 1: Localizar o app.** `grep -rn "FastAPI(" src/` e `grep -rn "include_router" src/` pra achar onde montar middleware.

- [ ] **Step 2: Teste falhando**
```python
# POST same-origin com Origin correto → passa (200/302/4xx do handler, NÃO 403)
# POST com Origin de outro host → 403
# GET sempre passa
# OAuth callback (GET) e /oauth/meta/data-deletion-callback (POST com HMAC) → isentos
```
Escrever testes httpx contra o app montado: um POST a `/logout`... (use uma rota POST existente isenta de auth se houver; senão mocke). Asserir 403 quando `Origin` != host; passa quando igual ou ausente-com-Referer-correto.

- [ ] **Step 3: Implementar** `src/web/middleware.py`:
```python
from urllib.parse import urlparse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from src.config import get_settings

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}
# Paths isentos (recebem POST de terceiros legítimos com sua própria validação):
_CSRF_EXEMPT_PREFIXES = ("/oauth/", "/mcp")  # OAuth callbacks (GET) + Meta data-deletion (HMAC) + MCP (Bearer)

class CSRFOriginMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method not in _SAFE_METHODS and not request.url.path.startswith(_CSRF_EXEMPT_PREFIXES):
            allowed_host = urlparse(get_settings().public_base_url).netloc
            origin = request.headers.get("origin")
            referer = request.headers.get("referer")
            src_host = urlparse(origin).netloc if origin else (urlparse(referer).netloc if referer else None)
            if src_host is None or src_host != allowed_host:
                return JSONResponse({"detail": "CSRF: origem inválida"}, status_code=403)
        return await call_next(request)
```

- [ ] **Step 4: Registrar** o middleware no app: `app.add_middleware(CSRFOriginMiddleware)`.
- [ ] **Step 5: Rodar testes — PASS** (CI valida; local: os que não precisam de DB). `python scripts/check_pre_push.py` 5/5.
- [ ] **Step 6: Commit** `git add src/web/middleware.py <app_file> tests/integration/test_csrf_middleware.py && git commit -m "feat(web): CSRF Origin/Referer middleware em métodos unsafe"`

---

### Task 4: Middleware de security headers

**Files:**
- Modify: `src/web/middleware.py` (adicionar classe)
- Modify: app de montagem; `_base.html` (SRI nos CDNs)
- Test: `tests/integration/test_security_headers.py` (criar)

- [ ] **Step 1: Teste falhando** — GET `/health` deve retornar headers: `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy`, `Content-Security-Policy`, `Strict-Transport-Security`.

- [ ] **Step 2: Rodar — FAIL.**
- [ ] **Step 3: Implementar** em `middleware.py`:
```python
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        resp = await call_next(request)
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        # CSP permissivo: o painel usa inline <script>/style + HTMX/Tailwind via CDN.
        resp.headers.setdefault("Content-Security-Policy",
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.tailwindcss.com https://unpkg.com; "
            "style-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data:; connect-src 'self'")
        return resp
```
  Registrar `app.add_middleware(SecurityHeadersMiddleware)`. Em `_base.html`, adicionar `integrity="..."` + `crossorigin="anonymous"` nas tags `<script>` do HTMX (unpkg fornece o hash SRI na doc da versão usada). (Tailwind Play CDN não suporta SRI estável — deixar sem SRI, coberto pelo CSP host-allowlist.)

- [ ] **Step 4: Rodar — PASS.** check_pre_push 5/5. **Validar manualmente** que o painel ainda carrega (CSP não quebrou inline/CDN) — abrir `/login` e `/admin` no browser pós-deploy.
- [ ] **Step 5: Commit** `git add src/web/middleware.py <app_file> src/web/templates/_base.html tests/integration/test_security_headers.py && git commit -m "feat(web): security headers (CSP/XFO/XCTO/HSTS) + SRI HTMX"`

---

### Task 5: Logout via POST + escopo de cookie

**Files:**
- Modify: `src/web/routes.py` (`/logout` ~63), `src/auth/oauth.py` (cookie `v4_attempted_email` path ~291), templates que linkam logout (`_base.html`, `access_denied.html`)
- Test: `tests/integration/test_logout_post.py`

- [ ] **Step 1: Teste falhando** — `GET /logout` deve retornar 405; `POST /logout` (same-origin) limpa cookie + 302 `/login`.
- [ ] **Step 2: Rodar — FAIL.**
- [ ] **Step 3: Implementar.** Trocar `@router.get("/logout")` por `@router.post("/logout")`. Nos templates, trocar o link `<a href="/logout">` por um mini-form POST:
  ```html
  <form method="POST" action="/logout" class="inline">{{ button("Sair", variant="ghost", type="submit") }}</form>
  ```
  (localizar em `_base.html` o header "Sair" + `access_denied.html`; também envolver o logout do access_denied em `{% if current_user %}`). Em `oauth.py`, mudar o cookie `v4_attempted_email` para `path="/access-denied"`.
- [ ] **Step 4: PASS** + check_pre_push 5/5.
- [ ] **Step 5: Commit** `git add ... && git commit -m "fix(web): logout via POST (anti logout-CSRF) + escopo cookie attempted_email"`

---

# PHASE 2 — Bugs funcionais

### Task 6: UUID→404 em path params inválidos

**Files:**
- Modify: `src/web/routes.py` (`session_detail` ~265 `UUID(session_id)`; `admin_access_manager_detail` Google ~1058; `admin_access_meta_manager_detail` ~954; `data_deletion_status` ~101 — mudar tipo do param)
- Test: `tests/integration/test_uuid_guards.py`

- [ ] **Step 1: Teste falhando** — `GET /sessions/lixo` → 404 (não 500); idem manager detail. `GET /legal/data-deletion-status/<não-uuid>` → 404/422.
- [ ] **Step 2: Rodar — FAIL** (atualmente 500).
- [ ] **Step 3: Implementar.** Onde há `UUID(session_id)` / `UUID(manager_id)` em path string, envolver:
  ```python
  from uuid import UUID
  try:
      sid = UUID(session_id)
  except ValueError:
      raise HTTPException(status_code=404, detail="Não encontrado")
  ```
  Para `data_deletion_status`, trocar a assinatura `code: str` por `code: UUID` (FastAPI valida e retorna 422 automático). Ajustar o template/uso de `confirmation_code` (string do UUID).
- [ ] **Step 4: PASS** + check_pre_push 5/5.
- [ ] **Step 5: Commit** `git add src/web/routes.py tests/integration/test_uuid_guards.py && git commit -m "fix(web): UUID inválido em path → 404 (não 500)"`

---

### Task 7: Paginação preserva filtros ativos

**Files:**
- Modify: `src/web/templates/_components.html` (macro `pagination` ~110-130); confirmar uso em `audit.html` + `admin/audit.html`
- Test: manual/render (macro Jinja — sem unit test fácil); verificar via grep + smoke

- [ ] **Step 1: Ler** a macro `pagination` e como `audit.html`/`admin/audit.html` a chamam. As views já montam `query_string` (ex: `routes.py:500` `query_string`) — confirmar que é passado pra macro.
- [ ] **Step 2: Implementar.** A macro deve aceitar `query_string` e anexá-lo: trocar `href="{{ base_url }}?{{ query_param }}={{ prev }}"` por `href="{{ base_url }}?{{ query_param }}={{ prev }}{% if query_string %}&{{ query_string }}{% endif %}"`. Garantir que `audit.html` e `admin/audit.html` passam `query_string=query_string` na chamada da macro (as views já o calculam — `audit` em routes.py monta `query_string` sem `page`).
- [ ] **Step 3: Verificar** `python scripts/check_pre_push.py` 5/5 (template compila). Smoke manual pós-deploy: filtrar `/audit?days=30&status=error` → "Próxima" mantém os filtros.
- [ ] **Step 4: Commit** `git add src/web/templates/_components.html src/web/templates/audit.html src/web/templates/admin/audit.html && git commit -m "fix(web): paginação preserva filtros ativos"`

---

### Task 8: Revoke de sessão sem flash de fragmento

**Files:**
- Modify: `src/web/routes.py` (`sessions_revoke` ~346), `src/web/templates/sessions/detail.html` (~89)
- Test: `tests/integration/test_sessions_revoke.py` (ajustar/criar)

- [ ] **Step 1: Teste** — revoke a partir da página de detalhe deve redirecionar pra `/sessions` (via header `HX-Redirect`), não devolver fragmento pra `<body>`.
- [ ] **Step 2: Implementar.** No `detail.html`, trocar o `htmx.ajax(... target:'body').then(redirect)` por um form/botão HTMX simples que faz POST e o handler responde com `HX-Redirect`. No `sessions_revoke`, quando o referer/origem for a página de detalhe (ou sempre, p/ simplicidade), retornar `Response(status_code=204, headers={"HX-Redirect": "/sessions"})`. Manter o comportamento de fragmento `_table.html` para o swap na LISTA (`/sessions`) — diferenciar por um param/header. Mais simples: detail usa `hx-post` + `hx-swap="none"` e o handler sempre manda `HX-Redirect` quando `HX-Request` veio da detail (checar `HX-Current-URL`).
- [ ] **Step 3: PASS** + check_pre_push 5/5.
- [ ] **Step 4: Commit** `git add ... && git commit -m "fix(web): revoke na página de detalhe usa HX-Redirect (sem flash de fragmento)"`

---

# PHASE 3 — Acessibilidade

### Task 9: aria-label nos checkboxes da matriz

**Files:** Modify `admin/access.html` (~63), `admin/access_meta.html` (~68)

- [ ] **Step 1:** em cada `<input type="checkbox">` da grade, adicionar `aria-label="{{ a.descriptive_name }} — {{ m.email.split('@')[0] }}"` (Google) / `aria-label="{{ a.account_name }} — {{ m.email.split('@')[0] }}"` (Meta).
- [ ] **Step 2:** `python scripts/check_pre_push.py` 5/5 (compila). Verificar com grep que todo checkbox da matriz tem `aria-label`.
- [ ] **Step 3: Commit** `git commit -m "fix(a11y): aria-label nos checkboxes da matriz de acesso"`

### Task 10: a11y dos modais inline (bulk-grant/copy)

**Files:** Modify `admin/access.html` (~82-127), `admin/access_meta.html` (~88-133)

- [ ] **Step 1:** em cada `<dialog class="v4-modal">` inline: adicionar `aria-labelledby="<id>-title"` e dar `id="<id>-title"` ao `<h3>`. Em cada `<label class="v4-form__label">` adicionar `for="<x>"` e o `id="<x>"` correspondente no `<select>`. Em cada botão de fechar `×` adicionar `aria-label="Fechar"`. (Aplicar nos 2 modais × 2 arquivos = 4 modais.)
- [ ] **Step 2:** check_pre_push 5/5 + grep confirma `aria-labelledby` em todos `<dialog>` inline.
- [ ] **Step 3: Commit** `git commit -m "fix(a11y): labelledby + label-for + close aria nos modais de acesso"`

### Task 11: `scope` nos `<th>` das tabelas

**Files:** Modify tabelas em `admin/access.html`, `admin/access_meta.html`, `audit.html`, `admin/audit.html`, `admin/managers.html`, `admin/accounts.html`, `admin/accounts_meta.html`, `sessions/_table.html`

- [ ] **Step 1:** adicionar `scope="col"` em todo `<th>` de cabeçalho de coluna. Na matriz de acesso, a 1ª célula sticky de cada linha (nome da conta) vira `<th scope="row">` (hoje é `<td>`).
- [ ] **Step 2:** check_pre_push 5/5 + grep `<th` sem `scope` retorna vazio nas tabelas listadas.
- [ ] **Step 3: Commit** `git commit -m "fix(a11y): scope nos th das tabelas + th scope=row na matriz"`

### Task 12: Linhas expansíveis do audit operáveis por teclado

**Files:** Modify `audit.html` (~81), e o JS `v4ToggleRow` (em `_base.html` ou inline)

- [ ] **Step 1:** no `<tr class="is-expandable" onclick=...>`, adicionar `tabindex="0"`, `role="button"`, `aria-expanded="false"`, e `onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault(); v4ToggleRow('row-{{ r.id }}')}"`. `v4ToggleRow` deve alternar `aria-expanded`.
- [ ] **Step 2:** check_pre_push 5/5. Smoke: Tab até a linha + Enter expande.
- [ ] **Step 3: Commit** `git commit -m "fix(a11y): linhas expansíveis do audit operáveis por teclado"`

### Task 13: Drawer mobile com focus-trap + ESC

**Files:** Modify `_base.html` (`toggleDrawer` ~72-108)

- [ ] **Step 1:** no `toggleDrawer` (open): após exibir, `document.querySelector('.v4-drawer__panel a, .v4-drawer__panel button')?.focus()`. Adicionar listener global `keydown` que fecha o drawer no `Escape` quando aberto. (Focus-trap completo é opcional; ESC + focus inicial cobrem o essencial.)
- [ ] **Step 2:** check_pre_push 5/5. Smoke mobile: abrir drawer → ESC fecha.
- [ ] **Step 3: Commit** `git commit -m "fix(a11y): drawer mobile fecha no ESC + foco inicial"`

### Task 14: aria-current + search aria-label + clipboard aria-live + headings

**Files:** Modify `_subnav.html`, `_access_tabs.html`, `_accounts_tabs.html`, `_components.html` (`search_input` ~40, code-copy ~136), `sessions/detail.html` (~30), `login.html` (~12), `access_denied.html` (titles), `admin/index.html` (sparkline grande ~137)

- [ ] **Step 1 (aria-current):** no link ativo de cada subnav/tab, adicionar `aria-current="page"` na mesma condição do `is-active`.
- [ ] **Step 2 (search):** adicionar parâmetro `aria_label` à macro `search_input` e renderizar `aria-label="{{ aria_label }}"`; passar valores nos call sites (ex: "Buscar gestor", "Buscar conta").
- [ ] **Step 3 (clipboard):** nos botões "Copiar token"/copy de code-block, após `navigator.clipboard.writeText`, chamar `showToast('Copiado!', 'success')` (a região de toast já tem `aria-live="polite"`).
- [ ] **Step 4 (headings):** `login.html` — `<h2 class="text-display">` da tagline vira `<p class="text-display ...">`. `access_denied.html` — os `<div class="text-display">` de título viram `<h1 class="text-display ...">` (hoiste a classe; um `<h1>` por branch). `admin/index.html` — a sparkline 600×80 recebe `role="img"` + `aria-label="Uso 30 dias"` (passar via macro) OU um `<p>` resumo ao lado.
- [ ] **Step 5:** check_pre_push 5/5.
- [ ] **Step 6: Commit** `git commit -m "fix(a11y): aria-current, search aria-label, clipboard aria-live, headings semânticos"`

---

# PHASE 4 — Consistência / Design System

### Task 15: Label de status Meta via Jinja filter

**Files:**
- Modify: `src/web/routes.py` (registrar filter no `templates.env`), `src/mcp/tools/_meta_common.py` (reusar `META_ACCOUNT_STATUS_LABELS`), `admin/accounts_meta.html` (~29), `admin/access_meta.html` (~58-61)
- Test: `tests/unit/test_meta_status_filter.py`

- [ ] **Step 1: Teste** — o filter `meta_status_label(1)` == "ATIVO"; `meta_status_label(3)` == "PAGAMENTO_PENDENTE"; valor desconhecido → "DESCONHECIDO".
- [ ] **Step 2: Implementar.** Em `routes.py`, após criar `templates = Jinja2Templates(...)`:
  ```python
  from src.mcp.tools._meta_common import META_ACCOUNT_STATUS_LABELS
  templates.env.filters["meta_status_label"] = lambda s: META_ACCOUNT_STATUS_LABELS.get(s or 0, "DESCONHECIDO")
  ```
  Nos templates, trocar `● {{ a.account_status }}` por `● {{ a.account_status | meta_status_label }}`, e usar cor via classe (não hex inline): status==1 → `text-v4-green`; senão `text-v4-red-medium`. Garantir que o significado não depende só de cor (o texto-label já carrega).
- [ ] **Step 3: PASS** + check_pre_push 5/5.
- [ ] **Step 4: Commit** `git add ... && git commit -m "fix(web): label PT-BR de status Meta (não número cru) + cor via classe"`

### Task 16: Paridade Google/Meta + drift de labels

**Files:** Modify `admin/access_by_manager.html` (add tab include), `admin/accounts_meta.html` (search toolbar + label "Última sync"), `admin/invites.html` (section wrapper)

- [ ] **Step 1:** `access_by_manager.html` — adicionar `{% include "admin/_access_tabs.html" %}` após o `<header>` (paridade com a versão Meta).
- [ ] **Step 2:** `accounts_meta.html` — adicionar toolbar de busca espelhando `accounts.html` (input `search_input` + JS `filterAccs()` filtrando linhas por nome/cliente/id); trocar `<th>Sync</th>` por `<th scope="col">Última sync</th>`.
- [ ] **Step 3:** `invites.html` — trocar `<div class="max-w-4xl">` por `<section class="max-w-4xl mx-auto py-6 px-4">` + envolver título em `<header class="mb-6">`.
- [ ] **Step 4:** check_pre_push 5/5.
- [ ] **Step 5: Commit** `git commit -m "fix(web): paridade Google/Meta (tabs by-manager, busca em contas Meta) + invites layout"`

### Task 17: Classes CSS fantasma

**Files:** Modify `src/web/static/v4-components.css` (+ `v4-tokens.css` se faltar token)

- [ ] **Step 1:** definir as classes referenciadas mas inexistentes (auditoria DS C1-C5): `.v4-input--small`, `.v4-card__action`, `.v4-modal__footer`, `.v4-sparkline`, `.v4-skeleton-table`, `.v4-btn__icon`, `.v4-btn__label`. Regras mínimas coerentes com os tokens (ex: `.v4-modal__footer { padding: var(--v4-space-4) var(--v4-space-6); border-top:1px solid var(--v4-gray-100); display:flex; justify-content:flex-end; gap:var(--v4-space-2);}`). Para classes em macros mortas que serão removidas na Task 19, pular.
- [ ] **Step 2:** check_pre_push 5/5. Grep confirma que cada classe usada em template existe no CSS.
- [ ] **Step 3: Commit** `git commit -m "fix(design-system): definir classes CSS faltantes referenciadas em templates"`

### Task 18: HTML ad-hoc → macros + páginas fora do DS + tokens

**Files:** Modify `dashboard.html` (stats), `admin/index.html` (stats/badges/alert), `error.html`, `legal/data_deletion_status.html`, `_access_tabs.html`/`_accounts_tabs.html` (token de offset), `audit.html`/`admin/audit.html` (offset)

- [ ] **Step 1 (macros):** `dashboard.html` blocos de stat → `{{ stat(label, value, sublabel) }}` num grid `grid-cols-2 md:grid-cols-4`. `admin/index.html` → chips de conexão via `{{ badge(...) }}`, alerta de expiração via `{{ alert(msg, "warning", title) }}`, stats via `{{ stat(...) }}`.
- [ ] **Step 2 (páginas fora do DS):** `error.html` → `<section class="max-w-xl mx-auto py-16 px-4 text-center">` + classes Tailwind/V4 (sem inline styles). `data_deletion_status.html` → `<div class="max-w-3xl mx-auto px-6 py-16">` espelhando `privacy.html`, `text-v4-gray-700` no lugar de `#666`.
- [ ] **Step 3 (tokens):** definir `--v4-tab-bar-offset` em `v4-tokens.css` (= header+subnav) e usar `style="top: var(--v4-tab-bar-offset)"` em `_access_tabs.html`/`_accounts_tabs.html`; idem `--v4-subnav-offset` para os `top-[53px]/top-[120px]` em audit.
- [ ] **Step 4:** check_pre_push 5/5. Smoke visual das páginas alteradas.
- [ ] **Step 5: Commit** `git commit -m "fix(design-system): macros stat/badge/alert + error/data-deletion no DS + tokens de offset"`

### Task 19: Remover dead code

**Files:** Modify `src/meta_ads/client.py` (remover `build_meta_api_for_manager`), `src/web/templates/_components.html` (remover macros não usadas), `src/web/templates/error.html` (decidir orfã)

- [ ] **Step 1:** confirmar zero callers: `grep -rn "build_meta_api_for_manager" src/ tests/`. Se só definição/docstring + testes próprios, remover a função E seus testes dedicados em `tests/unit/test_meta_client.py` (manter os de `build_facebook_ads_api` e `build_meta_api`).
- [ ] **Step 2:** remover macros sem nenhum call site (auditoria DS D2): `confirm_button`, `skeleton_row`, `skeleton_table`, `textarea` (confirmar com `grep -rn "confirm_button\|skeleton_row\|skeleton_table\|{{ textarea" src/web/templates`). Se alguma for usada, manter.
- [ ] **Step 3:** `error.html` — como nenhuma rota a renderiza, registrar um exception handler que a usa (em `<app_file>`: `@app.exception_handler(StarletteHTTPException)` renderizando `error.html` para respostas HTML) OU remover o arquivo. Recomendado: **wire-up** (melhor UX que JSON cru) — adicionar handler que renderiza `error.html` para 404/500 em requests de browser.
- [ ] **Step 4:** check_pre_push 5/5 (mypy/ruff pegam imports/refs órfãos).
- [ ] **Step 5: Commit** `git commit -m "chore(web): remover dead code (build_meta_api_for_manager, macros não usadas) + wire error.html"`

---

# PHASE 5 — Verificação

### Task 20: Full sweep + smoke

- [ ] **Step 1:** `python scripts/check_pre_push.py` → 5/5.
- [ ] **Step 2:** `python scripts/check_pre_push_full.py` (Docker) → 6/6 — OU via CI no push (Wellington sem Docker local).
- [ ] **Step 3: Smoke manual pós-deploy** (CSP pode quebrar render): abrir `/login`, `/`, `/admin`, `/admin/access` (Google+Meta tabs), `/admin/accounts/meta`, `/audit` — confirmar que carregam, estilos aplicam, HTMX funciona (toggle, paginação com filtro), e o console do browser não acusa violação de CSP.
- [ ] **Step 4:** se CSP quebrou algo, ajustar a diretiva (Task 4) e redeploy.

---

## Self-Review (preenchido)

**Cobertura dos achados:** Segurança — XSS oauth (T1), XSS toggles (T2), CSRF (T3), headers/CSP/SRI (T4), logout-CSRF + cookie path (T5), UUID 404 (T6). Funcional — paginação (T7), revoke flash (T8), UUID (T6). A11y — checkboxes (T9), modais (T10), th scope (T11), teclado audit (T12), drawer (T13), aria-current/search/clipboard/headings (T14). Consistência/DS — status label (T15), paridade (T16), classes fantasma (T17), macros + páginas fora do DS + tokens (T18), dead code (T19). Verificação (T20). **2 falsos positivos da auditoria deliberadamente NÃO viram task** (route-ordering Google — ordem já correta; synced_at None — coluna NOT NULL).

**Placeholders:** tasks de template/CSS dão localização exata + a mudança exata (não são "TODO"); tasks de lógica têm código completo. T7/T8 têm passos descritivos onde o teste unitário não se aplica (Jinja/HTMX) — verificação é grep + smoke, explicitada.

**Consistência de tipos:** `_toggle_checkbox_fragment(post_url, vals, checked)` usado igual nos 2 toggles (T2); filter `meta_status_label` registrado em T15 e usado nos templates; middlewares nomeados `CSRFOriginMiddleware`/`SecurityHeadersMiddleware` consistentes T3/T4.

**Dependências entre fases:** independentes e shippáveis em qualquer ordem; recomendado Segurança primeiro. T17 (definir classes) e T19 (remover macros) tocam `_components.html`/CSS — executar T17 antes de T19 pra não definir classe de macro que será removida.

## Riscos
- **CSP (T4)** pode quebrar render (inline scripts/Tailwind). Mitigação: diretiva permissiva (`unsafe-inline`/`unsafe-eval` + host-allowlist) + smoke manual obrigatório (T20 step 3); se preferir conservador, subir CSP como `Content-Security-Policy-Report-Only` primeiro.
- **CSRF (T3)** pode bloquear um POST legítimo se faltar Origin/Referer (raro em browsers modernos same-origin). Isentar `/oauth/` e `/mcp`; validar no smoke.
- Integration tests não rodam local (sem Docker) — validam no CI.
