# Meta Access Matrix + System User Token (Modelo B) — Design Doc

**Data:** 2026-05-28
**Status:** Proposto (aguardando review do gestor antes de `writing-plans`)
**Origem:** Brainstorming sessão 2026-05-28 ("vamos trabalhar na interface e acesso dos usuários")
**Specs relacionadas:** [`2026-05-24-meta-ads-incorporation-design.md`](2026-05-24-meta-ads-incorporation-design.md) (foundation M.1 criou as tabelas), [`2026-05-25-architecture-refactor-design.md`](2026-05-25-architecture-refactor-design.md)

---

## 0. Contexto e motivador

O controle de acesso por-conta hoje é **só Google**: `/admin/accounts` e `/admin/access` gerenciam `manager_account_access` (gestor × `customer_id`). O Meta ficou de fora do painel admin, mesmo com as tabelas já existentes desde a M.1 (`meta_ad_accounts` + `manager_meta_account_access`).

Hoje o acesso Meta de um gestor é **auto-concedido ao conectar** o próprio Facebook ([`meta_oauth.py:353`](../../../src/auth/meta_oauth.py)): o callback puxa `/me/adaccounts` do token pessoal e concede tudo que o token vê. Não há UI admin pra conceder/revogar, e as tools de performance **não checam grant** — só verificam que a conta existe no inventário ([`meta_get_campaign_performance.py:98`](../../../src/mcp/tools/meta_get_campaign_performance.py)) e chamam a Graph API com o token de quem chamou ([`reports.py:59`](../../../src/meta_ads/reports.py)).

Driver: chegada de **3 colaboradores V4 LS&Co**. Sem painel de acesso Meta, cada um teria que conectar o próprio FB e reconectar a cada ~60d, sem o admin poder escopar quem vê o quê.

## 1. Decisão: Modelo B (system user compartilhado)

Avaliamos dois modelos de token:

- **A — per-manager:** cada gestor conecta o próprio FB; matriz escopa visibilidade. Menor código, mas reconnect-60d por pessoa + setup BM por pessoa.
- **B — system user compartilhado:** as tools executam via um system user do BM; a matriz vira o gate real de quem opera o quê.

**Escolhido: B.** Rationale:

1. **Referência da categoria.** Supermetrics ("shared connections": autentica 1×, time reusa) e Windsor.ai (workspace-owned connections + "restrict members from seeing other members' accounts") — os dois tools que a V4 substitui usam conexão compartilhada + scoping por-conta. Validação direta do modelo.
2. **Token system user não expira** → mata o reconnect-60d, que era o único downside recorrente.
3. **Viabilidade confirmada na prática (2026-05-28).** Criamos um system user no BM V4 Lima Soares & Co, atribuímos à conta **ICSER** (`act_1489398022911451`, client-owned) e geramos token com `ads_read`/`ads_management`/`business_management`. Teste:
   - `GET /act_.../?fields=name,account_status,currency` → `name=ICSER, account_status=1, currency=BRL` ✓
   - `GET /act_.../insights` → `data: []` (sem gasto 7d) **sem erro de permissão** ✓
   - Conclusão: system user opera conta **client-owned** no **tier atual** (Dev). Descartado o cenário Advanced-Access-blocker pra leitura.
4. **Setup mais leve** que o A: 1 system user atribuído a ~12 contas (one-time) vs ~3 pessoas × 12 contas + 3 reconnects recorrentes.

### Pré-requisitos confirmados no BM
- **Business Verification:** Verificada (17/mai/2026). ✓
- **Feature "Usuários do sistema"** disponível no BM `619664032237208`. ✓
- **Contas são client-owned** (cada uma com `business_id` próprio ≠ BM da V4). Funciona no tier atual via admin role; o tier "Marketing API Access Tier" (rejeitado, em observação Caminho B+) só eleva rate limit, não desbloqueia função.

## 2. Architecture Overview

```
MCP tool (manager_id, ad_account_id)
   └─ run_meta_graph_get(manager_id, ad_account_id, ...)
        ├─ HARD-GATE: can_manager_access(manager_id, ad_account_id)  ← D3 (novo)
        │     └─ nega → erro PT-BR + audit status="denied"
        ├─ build_meta_api()  ← usa TOKEN DO SYSTEM USER (D1), não per-manager
        ├─ api.call(...)  (Graph API)
        ├─ record_actual_meta(...)  (BUC, inalterado)
        └─ audit_log.record(manager_id, platform="meta", ...)  (inalterado)
```

Mudança central: o **token de execução deixa de ser o do gestor** e passa a ser o do system user; a **matriz `manager_meta_account_access` vira o único freio** (por isso o hard-gate é obrigatório).

## 3. Data model — sem migration nova

As tabelas da M.1 cobrem tudo:
- `meta_ad_accounts` (inventário; PK `ad_account_id`) — sincronizado via system user.
- `manager_meta_account_access` (M:N gestor × conta, `access_level` read/write) — a matriz.

Repo `manager_meta_account_access.py` já tem `grant` / `revoke` / `bulk_grant` / `grant_all_active` / `can_manager_access` / `list_accounts_for_manager`. **Nenhuma migration** — só fiação + UI + storage do token.

> Nota: `copy_access` (clonar acesso de um gestor pra outro) **não existe** no repo Meta (presente no Google). Adicionar pra paridade da view "por-gestor" (botão "Copiar de…").

## 4. Token do system user (D1 — Secret Manager)

- Secret novo: **`meta-system-user-token`** (GCP Secret Manager, já criptografado em repouso; versionável pra rotação).
- Setting novo `meta_system_user_token` em `src/config.py`, montado no Cloud Run via `--update-secrets`.
- **Upload do token segue F47**: arquivo binary intermediário, nunca pipe PowerShell. Nunca colar em chat.
- `src/meta_ads/client.py`: novo `build_meta_api()` (sem `manager_id`) que constrói `FacebookSession` + `FacebookAdsApi` com o token do system user (factory F48 — `FacebookSession` primeiro, nunca `FacebookAdsApi.init()`).
- Token system user **não expira** → o novo path NÃO valida `token_expires_at`. Tratar secret ausente com erro PT-BR ("token do system user não configurado — admin precisa subir o secret").
- UI mostra **só o status** (configurado ✓ / ausente) — o token nunca passa pelo browser.

## 5. Execução + hard-gate (D3)

- `run_meta_graph_get` ([`reports.py`](../../../src/meta_ads/reports.py)) passa a chamar `build_meta_api()` (system user) em vez de `build_meta_api_for_manager(manager_id)`.
- **Hard-gate (novo):** quando `params` tem `ad_account_id`, checar `can_manager_access(manager_id, ad_account_id, level="read")` antes do `api.call`. Sem grant → `raise` erro PT-BR ("Você não tem acesso a esta conta — peça ao admin") + `audit_log.record(..., status="denied")`. Calls account-agnostic (sem `ad_account_id`) pulam o gate.
- Mantém `manager_id` no fluxo só pra gate + audit (atribuição interna preservada mesmo com token compartilhado).

## 6. Sync de inventário

- `meta_oauth_refresh_accounts` ([`meta_oauth.py:466`](../../../src/auth/meta_oauth.py)) passa a sincronizar `/me/adaccounts` via **token do system user** (não o pessoal). Vira ação admin: re-popula `meta_ad_accounts` com as contas atribuídas ao system user.
- Remove o auto-`grant` por-gestor que existe no fim do sync (no Modelo B o grant é responsabilidade da matriz, não do sync).

## 7. Acesso = opt-in + migração

- **Opt-in por natureza:** gestor novo não vê conta nenhuma até o admin conceder via matriz.
- **Grants existentes preservados:** as linhas que o Wellington já tem (auto-concedidas pela conexão pessoal) permanecem válidas — ele não perde acesso.
- **Rollout:**
  1. Admin cria system user no BM + atribui as 12 contas + gera token.
  2. Sobe `meta-system-user-token` (Secret Manager, F47) + `update-secrets` no Cloud Run.
  3. Admin roda o refresh (via system user) → `meta_ad_accounts` populado.
  4. Admin concede acesso por gestor na nova matriz.
- **OAuth Meta por-gestor (D2):** fica **dormante**. Rotas `/oauth/meta/*` e `build_meta_api_for_manager` permanecem funcionais (não viram dead code — o fluxo ainda roda ponta a ponta pra eventual conexão pessoal de admin), mas **não são o path de execução**. Remoção é follow-up de sprint futuro se confirmado sem uso.

## 8. UI (visual aprovado no companion)

**Estrutura (Opção A — abas):** `/admin/accounts` e `/admin/access` ganham abas **Google | Meta** (mesma URL, conteúdo por aba). Espelha o paralelismo Google/Meta, sem páginas novas.

**Aba Meta de `/admin/access`:**
- **Grid (primária):** linhas = contas, colunas = gestores, checkbox HTMX na célula (espelha `admin/access.html` + endpoint `toggle`). Status inline (●ativo / ●pgto / ●fechado) reaproveitando `account_status` do `meta_ad_accounts`.
- **Por-gestor (secundária):** seleciona 1 gestor → checklist de contas + "Conceder todas" (`grant_all_active`) + "Copiar de…" (novo `copy_access`). Bom pra onboarding.
- Endpoints novos espelham os do Google: `toggle`, `bulk-grant`, `by-manager`, detail. Mutates Meta-access auto-aplicam (negativas/grants de acesso = baixo blast radius, igual Google).

**Aba Meta de `/admin/accounts`:**
- Inventário `meta_ad_accounts` (conta, cliente/`business_name`, status, currency, synced_at) + botão **Refresh** (sync via system user) + **widget de status do token** system user.

> `button()` dentro de `<form>` sempre `type="submit"` (F49). HTMX swap nos toggles (igual Google).

## 9. Security / LGPD

- Token compartilhado executa sob a identidade do **system user** (não FB pessoal de ninguém) — rotacionável/revogável sem afetar contas pessoais.
- **Atribuição interna preservada:** `audit_log` continua gravando `manager_id` real de quem chamou + `platform="meta"`, mesmo com token único.
- Hard-gate + always-CONFIRM (mutates futuros M.16+) + audit cobrem o risco de mutate que Supermetrics/Windsor (read-only) nem têm.
- Dados são de clientes (client-owned accounts); o system user opera em nome da V4 (empresa verificada), consistente com a relação de agência.

## 10. Testing strategy

- **Unit:** `build_meta_api()` factory (contrato `FacebookSession`/`FacebookAdsApi`, F48); hard-gate em `run_meta_graph_get` (mock `can_manager_access` → allowed vs denied → assert raise + audit status="denied"). `copy_access` repo (integration).
- **Integration:** matriz toggle/bulk-grant/by-manager (espelhar testes do Google access); `manager_meta_account_access` já coberto em `test_repositories.py`.
- **Sem `MetaCaptureClient` necessário** nesse sprint (sem builders de mutate proto — Meta usa dicts; reads só). Fica pra M.16+.
- `check_pre_push.py` antes de commit; **`check_pre_push_full.py`** obrigatório (toca `reports.py`/`_common` + secret/config). Sem migration nova, mas rodar full sweep mesmo assim.

## 11. Riscos & Out-of-scope

**Riscos com mitigação:**
- **Write (`ads_management`) não testado** — só leitura provada. Mitigação: não há tools Meta de mutate ainda (M.16+); validar write num teste controlado (conta própria, não cliente ao vivo) quando construir mutate. Mesmo modelo de tier pra read/write.
- **Atribuir system user a conta partner-shared** — provado pra ICSER; algumas contas de cliente podem ter sharing que não permite system user. Mitigação: refresh lista só o que o system user alcança; contas faltantes = ajustar sharing no BM cliente.
- **Rate limit Dev tier** (ads_insights 600/h + 400×ads ativos por conta) — folgado pra 4 pessoas interativas; sobe ~300× quando Caminho B+ atingir 500 calls/15d. Monitorado via `meta_rate_counters`/BUC.

**Out-of-scope (deliberado):**
- Remover OAuth Meta por-gestor (D2 dormante; follow-up).
- Unificar matriz Google+Meta (Opção C descartada).
- Papéis mais ricos (Viewer/Finance estilo Supermetrics) — `admin/gestor` atual basta.
- Mutates Meta (M.16+) e seus testes de `ads_management` write.
- Retrofit do hard-gate no Google (simetria) — opcional, sprint futuro.

## 12. Critérios de signoff
- Aba Meta em `/admin/accounts` + `/admin/access` (grid + por-gestor) funcionando.
- Hard-gate nega conta sem grant (erro PT-BR + audit "denied").
- Tools de performance Meta executam via system user token.
- Token via Secret Manager; UI só status.
- `check_pre_push_full.py` 6/6 PASS.

## 13. Pre-checklist antes de `writing-plans`
- [ ] Gestor cria system user + atribui contas + gera token (manual BM) — pode rodar em paralelo ao dev.
- [ ] Confirmar quais das 12 contas o system user alcança (refresh de teste).
- [ ] Review desta spec pelo gestor.
