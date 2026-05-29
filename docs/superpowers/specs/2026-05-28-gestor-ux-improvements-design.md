# Gestor (Non-Admin) UX Improvements — Design Doc

**Data:** 2026-05-28
**Status:** Proposto (aguardando review do gestor antes de `writing-plans`)
**Origem:** Análise criteriosa das telas do gestor (não-admin), 2026-05-28 — achados High/Medium/Low.
**Relacionada:** [`2026-05-28-google-mcp-account-gate-design.md`](2026-05-28-google-mcp-account-gate-design.md) (Sub-projeto A, segurança — independente desta).

---

## 0. Contexto e motivador

A análise da experiência do gestor (role não-admin) confirmou que o **isolamento de dados na UI web é sólido** (zero IDOR, scoping correto, admin routes gateados). Os achados são de **UX/onboarding**: atritos que travam ou confundem um gestor, especialmente relevantes com os **3 colaboradores V4 LS&Co** entrando. Esta spec agrupa os fixes de template/UX (baixo risco, sem mudança de arquitetura).

Escopo estritamente o que o **gestor** vê (blocos `{% if current_user.is_admin %}` fora de escopo).

## 1. Itens (priorizados por impacto no trabalho do gestor)

### Alta — dead-ends / footguns

**B1 — Card de contas Meta no `/accounts`.** Hoje `/accounts` só mostra Google. Um gestor com acesso Meta concedido não tem como ver quais `act_…` pode operar via MCP. Adicionar card "Contas Meta Ads acessíveis" abaixo do Google, listando `manager_meta_account_access JOIN meta_ad_accounts` para o gestor. Empty state com `alert()` ("peça acesso ao admin"). Arquivo: `src/web/routes.py::accounts_page` (query) + `src/web/templates/accounts.html`.

**B2 — Aviso da janela de 60s do token antes de criar.** O token aparece 1× por 60s (`routes.py:368` cookie max_age). Em mobile/lento dá pra perder sem recuperação. Adicionar aviso em `sessions/list.html` perto do form ("o token aparece só uma vez, por ~60s — tenha o config do MCP à mão antes de criar"). Não mexer no TTL (decisão de segurança mantida).

**B3 — Mensagem amigável no `access_denied` para códigos crus.** A branch `meta_oauth_incomplete/meta_state_invalid/meta_userinfo_*` (`access_denied.html:51-56`) mostra `Reason: <code>{{ reason }}</code>` cru. Trocar por mensagem PT-BR ("Erro inesperado na autenticação. Tente de novo; se persistir, avise o admin.") + manter o reason em comentário HTML pra debug.

### Média — guidance / fricção / labels

**B4 — Toast de confirmação no revoke de sessão.** O revoke no detalhe retorna 204 + `HX-Redirect` sem feedback (`routes.py:401`). Adicionar header `HX-Trigger: {"toast": {"message": "Sessão revogada.", "kind": "success"}}` ao 204 (o `_base.html` já escuta `HX-Trigger` toast).

**B5 — Histórico de sessões revogadas.** `/sessions` só mostra ativas (`include_revoked=False`). Gestor não confirma que o revoke funcionou. Adicionar visão de revogadas via query param `?include_revoked=1` (link "ver revogadas") OU contador "X revogadas". Mínimo: o contador. Arquivos: `routes.py::sessions_list` + `sessions/list.html`.

**B6 — Token interpolado nos snippets de config quando flash presente.** `sessions/detail.html:47-78` sempre mostra `mcp_xxx...` placeholder, mesmo com `flash_token` disponível. Quando `flash_token` presente, interpolar o token real nos code blocks OU nota destacada ("substitua `mcp_xxx` pelo token em amarelo acima").

**B7 — Jargão exposto ao gestor.** Renomear: search placeholder "Buscar nome ou customer_id..." → "Buscar por nome ou ID da conta..."; coluna "Customer ID" → "ID da conta" (`accounts.html`); filtro audit "Reads sensíveis" → label mais claro OU tooltip explicando (`audit.html:28`); "Request ID" no `audit_detail.html` → "ID de rastreamento" + corrigir o label hardcoded "Google Request ID" (agora guarda trace Meta também) ou esconder na view do gestor.

**B8 — `unidade_label` placeholder.** Dashboard mostra `V4 unidade · —` sempre (`routes.py:262` placeholder). Remover o segmento `· —` até o sub-projeto 2 shipar (não mostrar dado fantasma).

### Baixa — clareza / polish

**B9 — Limpar caminhos admin do `/help`.** `help.html:115,121` mandam o gestor "ver em `/admin/invites`/`/admin/access`" (403 pra ele). Remover as referências de path ("peça ao admin da sua unidade" basta).

**B10 — Link pra `/help` no `access_denied`.** A branch "não convidado" não tem próximo passo navegável. Adicionar `<a href="/help">guia de onboarding</a>`.

**B11 — Tooltip na coluna "Alvos" do audit.** `audit.html:76` mostra número sem explicação. Adicionar `title="Número de entidades afetadas pela operação"` no `<th>`.

**B12 — Proteção de duplo-submit no "Criar" sessão.** `sessions/list.html:33` sem loading state. Adicionar `hx-disabled-elt` ou `onclick="this.disabled=true"` (evita 2 sessões por duplo-clique). Confirmar antes que o form não-HTMX ainda submete (F49).

**B13 — "Sessões ativas" inclui expiradas?** `_table.html:5` diz "ativas" mas `list_for_manager` pode não filtrar `expires_at > now()`. Verificar no repo; se só filtra `revoked_at IS NULL`, ajustar o label OU a query pra não chamar expirada de "ativa".

## 2. Architecture / arquivos

Template-only + pequenas queries em `routes.py`. Sem migration, sem mudança de arquitetura. Arquivos tocados:
- `src/web/routes.py` (queries: `accounts_page` +Meta, `sessions_list` +revoked/contador, `sessions_revoke` +HX-Trigger, dashboard unidade)
- `src/web/templates/`: `accounts.html`, `sessions/list.html`, `sessions/detail.html`, `sessions/_table.html`, `access_denied.html`, `help.html`, `audit.html`, `audit_detail.html`, `dashboard.html`
- Reusar repos existentes (`manager_meta_account_access.list_accounts_for_manager`, `mcp_sessions.list_for_manager`).

## 3. Testing strategy

- **Integration:** `/accounts` renderiza card Meta com contas concedidas (seed grant) + empty state; `/sessions?include_revoked=1` mostra revogadas; revoke retorna `HX-Trigger` header; `access_denied` não mostra `Reason:` cru. Mirror dos testes web panel existentes (auth fixture).
- **Sem unit nova relevante** (mudanças são template + query). `check_pre_push.py` 5/5 (compila templates + queries).
- Smoke visual pós-deploy: `/accounts` (card Meta), criar+revogar sessão (toast + histórico), `/help` sem paths admin.

## 4. Riscos & Out-of-scope

**Riscos:** baixos (template-only). Maior risco é macro/signature de template (validar via `check_pre_push` + grep dos call sites, lição da auditoria). A query Meta nova em `accounts_page` deve escopar por `user.id` (não vazar contas não concedidas).

**Out-of-scope:**
- Hard-gate Google (Sub-projeto A, spec própria).
- Mudar o TTL de 60s do token (decisão de segurança mantida; só avisamos melhor).
- Self-service de conexão Meta pelo gestor (arquitetura Modelo B é system-user; gestor não conecta Meta — só vê o que foi concedido).
- Sub-projeto 2 (conceito de "unidade") — B8 só remove o placeholder até lá.

## 5. Critérios de signoff
- `/accounts` mostra contas Meta concedidas (ou empty state) pro gestor.
- Token: aviso antes de criar + token interpolado/destacado no flash.
- Revoke: toast + histórico/contador de revogadas.
- `access_denied`/`help` sem códigos crus nem paths admin.
- Jargão substituído; placeholder `unidade` removido.
- `check_pre_push.py` 5/5.

## 6. Pre-checklist antes de `writing-plans`
- [ ] Review desta spec pelo gestor.
- [ ] Decidir B5 (histórico completo via `?include_revoked=1` vs só contador) — default: link `?include_revoked=1` (mais útil, custo baixo).
