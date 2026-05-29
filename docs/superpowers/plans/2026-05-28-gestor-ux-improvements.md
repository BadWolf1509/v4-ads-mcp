# Gestor UX Improvements — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Corrigir os atritos de UX/onboarding do gestor (não-admin) identificados na análise — sem mudar arquitetura.

**Architecture:** Mudanças de template Jinja + pequenas queries em `routes.py`. Sem migration. Agrupado em 3 tasks por afinidade de arquivo (evita conflito de writer). Spec: [`2026-05-28-gestor-ux-improvements-design.md`](../specs/2026-05-28-gestor-ux-improvements-design.md).

**Tech Stack:** FastAPI + Jinja2 + Tailwind(CDN) + HTMX, asyncpg. Reusa repos existentes.

---

## File Structure

- `src/web/routes.py` — queries: `accounts_page` (+Meta), `sessions_list` (+revoked param/contador), `sessions_revoke` (+HX-Trigger), `dashboard` (unidade)
- `src/web/templates/`: `accounts.html`, `sessions/list.html`, `sessions/detail.html`, `sessions/_table.html`, `access_denied.html`, `help.html`, `audit.html`, `audit_detail.html`, `dashboard.html`
- Tests: `tests/integration/test_web_panel_*.py`

> **Convenções:** `check_pre_push.py` antes de cada commit (5/5). Macro/signature em template falha só no render → confirmar call sites via grep + os integration tests cobrem no CI (lição da auditoria). `button()` em `<form>` precisa `type="submit"` (F49). Integration tests = testcontainers (CI, sem Docker local). On `main` com consentimento — commit, NÃO push.

---

### Task 1: `/accounts` — card de contas Meta (B1) + jargão (B7 parcial)

**Files:**
- Modify: `src/web/routes.py::accounts_page`, `src/web/templates/accounts.html`
- Test: `tests/integration/test_web_panel_accounts.py`

- [ ] **Step 1: Ler** `accounts_page` (~routes.py:380) + `accounts.html` + a macro `alert()`/`empty_state` em `_components.html`. Confirmar `manager_meta_account_access.list_accounts_for_manager(conn, user.id)` (existe) e os campos de `MetaAdAccount` (`ad_account_id`, `account_name`, `business_name`, `account_status`, `currency`).

- [ ] **Step 2: Teste falhando** em `test_web_panel_accounts.py`: gestor com 1 grant Meta (seed `meta_ad_accounts` + `manager_meta_account_access.grant`) → GET `/accounts` → 200 + nome da conta Meta presente + texto "Contas Meta". Gestor sem grant Meta → seção mostra empty state.

- [ ] **Step 3: Rodar — FAIL** (rota não busca Meta ainda).

- [ ] **Step 4: Implementar query.** Em `accounts_page`, adicionar:
```python
from src.db.repositories import manager_meta_account_access
meta_accounts = await manager_meta_account_access.list_accounts_for_manager(conn, user.id)
```
e passar `meta_accounts=meta_accounts` (lista de `MetaAdAccount`) no contexto do template.

- [ ] **Step 5: Implementar template.** Em `accounts.html`, após a seção Google, adicionar card "Contas Meta Ads acessíveis":
```html
<div class="v4-card mt-6">
  <h2 class="text-xl font-bold mb-3">Contas Meta Ads acessíveis ({{ meta_accounts|length }})</h2>
  {% if not meta_accounts %}
    {{ alert("Nenhuma conta Meta liberada ainda. Peça ao admin da sua unidade.", "info") }}
  {% else %}
  <table class="v4-table v4-table--compact">
    <thead><tr><th scope="col">Conta</th><th scope="col">Cliente</th><th scope="col">Status</th><th scope="col">Moeda</th></tr></thead>
    <tbody>
      {% for a in meta_accounts %}
      <tr>
        <td><strong>{{ a.account_name }}</strong><div class="text-xs font-mono text-v4-gray-300">{{ a.ad_account_id }}</div></td>
        <td>{{ a.business_name or "—" }}</td>
        <td>{% if a.account_status == 1 %}<span class="text-v4-green">● {{ a.account_status | meta_status_label }}</span>{% else %}<span class="text-v4-red-medium">● {{ a.account_status | meta_status_label }}</span>{% endif %}</td>
        <td>{{ a.currency or "—" }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  {% endif %}
</div>
```
(O filtro `meta_status_label` já está registrado — Sprint Meta F4.T15.)

- [ ] **Step 6: Jargão (B7) na mesma página.** Em `accounts.html`: search placeholder "Buscar nome ou customer_id..." → "Buscar por nome ou ID da conta..."; coluna `<th>Customer ID</th>` → `<th scope="col">ID da conta</th>`.

- [ ] **Step 7: Rodar — PASS** + check_pre_push 5/5.
- [ ] **Step 8: Commit** `git add src/web/routes.py src/web/templates/accounts.html tests/integration/test_web_panel_accounts.py && git commit -m "feat(web): card de contas Meta no /accounts do gestor + tirar jargão customer_id"`

---

### Task 2: Sessões — aviso token (B2), interpolação (B6), toast revoke (B4), histórico (B5), duplo-submit (B12), label ativas (B13)

**Files:**
- Modify: `src/web/routes.py` (`sessions_list`, `sessions_revoke`), `sessions/list.html`, `sessions/detail.html`, `sessions/_table.html`
- Test: `tests/integration/test_web_panel_sessions.py`

- [ ] **Step 1: Ler** `sessions_list` (~routes.py:245), `sessions_revoke` (~364), os 3 templates + `mcp_sessions.list_for_manager` (ver se filtra `expires_at`).

- [ ] **Step 2: Testes falhando** em `test_web_panel_sessions.py`:
  - `GET /sessions?include_revoked=1` → inclui sessão revogada na resposta.
  - revoke de sessão → resposta tem header `HX-Trigger` contendo `toast`.

- [ ] **Step 3: Rodar — FAIL.**

- [ ] **Step 4: B5 histórico.** Em `sessions_list`, aceitar query param `include_revoked: bool = False` e passar pro `list_for_manager(conn, user.id, include_revoked=include_revoked)`. Em `sessions/list.html`, adicionar link condicional: se não incluindo, `<a href="/sessions?include_revoked=1">ver revogadas</a>`; se incluindo, `<a href="/sessions">ver só ativas</a>`. Mostrar coluna de status (ativa/revogada) quando incluindo.

- [ ] **Step 5: B4 toast no revoke.** Em `sessions_revoke`, no retorno 204 com `HX-Redirect` (detail) e/ou no fragmento (list), adicionar header `HX-Trigger`:
```python
return Response(status_code=204, headers={
    "HX-Redirect": "/sessions",
    "HX-Trigger": '{"toast": {"message": "Sessão revogada.", "kind": "success"}}',
})
```
(Para o swap da lista, adicionar `HX-Trigger` no `TemplateResponse` via `.headers["HX-Trigger"] = ...`.)

- [ ] **Step 6: B2 aviso da janela do token.** Em `sessions/list.html`, perto do form "Criar nova sessão", adicionar:
```html
<p class="text-sm text-v4-gray-700 mt-2">⚠ O token aparece <strong>uma única vez</strong> na próxima tela, por ~60 segundos. Tenha o arquivo de config do seu cliente MCP aberto antes de criar.</p>
```

- [ ] **Step 7: B12 duplo-submit.** No botão "Criar" (`sessions/list.html`), adicionar `onclick="this.disabled=true; this.form.submit()"` OU usar o `loading` do macro `button()`. Confirmar que o form ainda submete (não quebrar com disable prematuro — preferir `this.form.requestSubmit()` antes do disable, ou `hx-disabled-elt` se o form for HTMX). Padrão seguro sem HTMX: `<button type="submit" onclick="setTimeout(()=>this.disabled=true,0)">Criar</button>`.

- [ ] **Step 8: B6 token interpolado.** Em `sessions/detail.html`, onde os code blocks mostram `mcp_xxx...`: quando `flash_token` presente, OU interpolar `{{ flash_token }}` nos snippets, OU adicionar nota destacada acima dos blocks: `{% if flash_token %}<p class="text-sm text-v4-gold">↓ Substitua <code>mcp_xxx...</code> pelo token em amarelo acima.</p>{% endif %}`.

- [ ] **Step 9: B13 label "ativas".** Se `list_for_manager` não filtra `expires_at > now()` (confirmado no Step 1), ou ajustar o header `_table.html` de "Sessões ativas" para "Sessões (não revogadas)", OU adicionar coluna que destaque expiradas. Mínimo: rótulo honesto. (Decidir pelo menor toque que não engana.)

- [ ] **Step 10: Rodar — PASS** + check_pre_push 5/5.
- [ ] **Step 11: Commit** `git add src/web/routes.py src/web/templates/sessions/ tests/integration/test_web_panel_sessions.py && git commit -m "feat(web): sessões do gestor — aviso/interpolação token, toast+histórico revoke, anti duplo-submit"`

---

### Task 3: Páginas de borda + dashboard — access_denied (B3,B10), help (B9), audit (B7,B11), dashboard unidade (B8)

**Files:**
- Modify: `access_denied.html`, `help.html`, `audit.html`, `audit_detail.html`, `dashboard.html`, `src/web/routes.py` (dashboard unidade)
- Test: `tests/integration/test_web_panel_*.py` (access_denied render)

- [ ] **Step 1: B3 — mensagem amigável no access_denied.** Em `access_denied.html`, a branch `meta_oauth_incomplete/meta_state_invalid/meta_userinfo_*` (~linha 51-56) que mostra `Reason: <code>{{ reason }}</code>`: trocar o `<p>` por mensagem PT-BR amigável ("Ocorreu um erro inesperado durante a autenticação. Tente novamente — se persistir, avise o admin da sua unidade.") + manter o reason em `<!-- {{ reason }} -->` (comentário) pra debug.

- [ ] **Step 2: B10 — link help no access_denied.** Na branch genérica "não convidado", adicionar `<p class="mt-4"><a href="/help" class="text-v4-red hover:underline">Veja o guia de onboarding</a></p>`.

- [ ] **Step 3: B9 — limpar paths admin do help.** Em `help.html`, linhas que citam `/admin/invites` e `/admin/access`: remover o path ("Login só funciona se um admin V4 tiver te convidado previamente." / "peça acesso ao admin da sua unidade").

- [ ] **Step 4: B7 — jargão no audit.** Em `audit.html`: filtro "Reads sensíveis" → adicionar `title="Leituras de dados sensíveis (ex: relatórios de termos de busca)"` no option/label OU renomear pra "Consultas sensíveis". Em `audit_detail.html`: label "Google Request ID" → "ID de rastreamento" (corrige o mislabel — guarda trace Meta também).

- [ ] **Step 5: B11 — tooltip "Alvos".** Em `audit.html`, o `<th>Alvos</th>` → `<th scope="col" title="Número de entidades afetadas pela operação">Alvos</th>`.

- [ ] **Step 6: B8 — placeholder unidade.** Em `dashboard.html`, o segmento `V4 unidade · {{ unidade_label or "—" }}`: remover o `· {{ unidade_label or "—" }}` (ou a linha toda do unidade) até o sub-projeto 2. Em `routes.py::dashboard`, pode remover o `unidade_label` do contexto se não usado em outro lugar.

- [ ] **Step 7: Teste.** Em `test_web_panel_login.py` (ou onde access_denied é testado): GET `/access-denied?reason=meta_state_invalid` → 200 + NÃO contém "Reason:" cru + contém a mensagem amigável. (Integration, CI.)

- [ ] **Step 8: Rodar — PASS** + check_pre_push 5/5.
- [ ] **Step 9: Commit** `git add -A && git commit -m "fix(web): access_denied amigável + help sem paths admin + audit labels/tooltip + unidade placeholder"`

---

### Task 4: Verificação final

- [ ] **Step 1:** `python scripts/check_pre_push.py` → 5/5.
- [ ] **Step 2: Grep de regressão:** confirmar zero "customer_id" no placeholder de busca do `/accounts`, zero "Reason:" cru no access_denied, zero `/admin/` em `help.html`.
- [ ] **Step 3: Smoke pós-deploy:** `/accounts` (card Meta como gestor), criar+revogar sessão (aviso + toast + ver revogadas), `/help` sem paths admin, `/access-denied?reason=meta_state_invalid` amigável.

---

## Self-Review (preenchido)
- **Cobertura da spec:** B1 ✓T1, B2/B4/B5/B6/B12/B13 ✓T2, B3/B7/B8/B9/B10/B11 ✓T3. B5 = `?include_revoked=1` (default escolhido). Verificação ✓T4.
- **Placeholders:** B12 (Step 7) e B13 (Step 9) dão o padrão exato + a decisão "menor toque"; não são TODO. Os snippets de template são completos.
- **Consistência:** `meta_status_label` reusado (registrado em F4.T15); `meta_accounts` nome consistente entre query (T1.S4) e template (T1.S5); `HX-Trigger` toast shape igual ao que `_base.html` escuta.

## Out-of-scope (ver spec §4)
Hard-gate Google (Plano A); mudar TTL 60s; self-service Meta pelo gestor; conceito de unidade (sub-projeto 2).
