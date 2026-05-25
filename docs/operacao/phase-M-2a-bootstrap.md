# Phase M.2a — manual smoke runbook (Meta OAuth + first tool)

**Purpose:** Validar Sprint M.2a — primeira ponta-a-ponta Meta Ads na plataforma. Cobre (1) refactor foundation (audit_log.record() platform kwarg + migration 004 rename `google_request_id` → `provider_request_id` big-bang em 50 caller files + `meta_rate_counters` CRUD + conftest `_TEST_ENV`), (2) `facebook-business` SDK install + `src/meta_ads/` package (client.py + reports.py + errors.py), (3) OAuth flow Meta completo (`/oauth/meta/start` + `/callback` + `/revoke` + granular permission enforcement), (4) 1ª MCP tool Meta `meta_list_my_ad_accounts` (read cache local Postgres, sem Graph API call) e (5) webapp admin card "Suas conexões OAuth" Google + Meta paralelos. Foundation pra todas as ~45 tools Meta seguintes (M.2b → M.25).

**Operator:** wellinton.ribeiro@v4company.com
**Business Manager Meta:** V4 Lima Soares & Co (João Pessoa, PB)
**Account Google regression:** `7862230676` Mestre da Obra JP (validar tools Google intactas pós-rename)

**Spec:** `docs/superpowers/specs/2026-05-24-sprint-m2a-meta-oauth-first-tool-design.md`
**Plan:** `docs/superpowers/plans/2026-05-24-sprint-m2a-meta-oauth-first-tool.md`
**Sprint family parent:** `docs/superpowers/specs/2026-05-24-meta-ads-incorporation-design.md` (M.1 → M.25, ~3-6 meses até paridade)

> **Escopo M.2a confirmado:**
> - Tool count: 57 → **58** (1ª MCP tool Meta, sem mexer 57 tools Google existentes)
> - Foundation refactor: `audit_log.record(platform=...)` + migration 004 rename column + `meta_rate_counters` repository CRUD (tabela criada em M.1, agora com Python access)
> - OAuth Meta: 5 scopes (`ads_read`, `ads_management`, `business_management`, `email`, `public_profile`) + granular permission enforcement (rejeita se user desmarcar `ads_read`)
> - Tool `meta_list_my_ad_accounts`: read cache local em `meta_ad_accounts` (M.1 schema), sem Graph API call neste sprint — exercita SDK install + import path apenas
> - Webapp admin: card "Suas conexões OAuth" em `/admin` mostra Google + Meta status paralelos, com botões "Conectar/Desconectar" cada
> - Regression CRITICAL: 57 tools Google intactas pós-rename `google_request_id` → `provider_request_id` (big-bang em 50 callers)
> - Sprint family parte 1 de 2 (M.2b adiciona 1ª Graph API tool real → exercita token check + refresh logic)

## Production URL

`https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app`

## Pre-flight

- [ ] Deploy lands successfully (CI + Deploy green em commit final M.2a Task 12)
- [ ] Service `/health` returns 200 (`{"status":"ok","version":"0.1.0"}`)
- [ ] Migration `004_audit_log_provider_id.sql` aplicada em produção (Cloud Run Job `migrate` exitcode 0)
- [ ] Tool `meta_list_my_ad_accounts` registered (`test_registered_tool_count_matches_files_on_disk` 58==58 PASS)
- [ ] Pre-push gate `python scripts/check_pre_push.py` 5/5 PASS
- [ ] Pre-push gate FULL `python scripts/check_pre_push_full.py` 6/6 PASS (Docker required — MANDATORY pois big-bang refactor audit_log.record() em 50 caller files)
- [ ] Schema regression `test_no_composition_keywords_in_any_schema` passa
- [ ] Unit tests `tests/unit/test_meta_oauth_flow.py` PASS (OAuth state cookies + token exchange mock)
- [ ] Unit tests `tests/unit/test_meta_rate_counters_repo.py` PASS (4 ops: increment, get_today, get_window, reset)
- [ ] Integration tests `tests/integration/test_meta_oauth_callback.py` PASS (testcontainers Postgres)
- [ ] Integration tests `tests/integration/test_audit_log_platform_kwarg.py` PASS (platform="google" default + platform="meta" insert)
- [ ] Cloud Run env vars `META_APP_ID` + `META_APP_SECRET` bindados (Secret Manager refs, M.1 Task 8 wellington-manual done)
- [ ] Meta App em Dev Mode com OAuth Redirect URI configurado (`https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/oauth/meta/callback`)
- [ ] Meta App Use Cases habilitados: `ads_read`, `ads_management`, `business_management` (M.1 Task 8)
- [ ] MCP Inspector / Claude client conectado à URL de produção e enxerga `meta_list_my_ad_accounts` na tool list
- [ ] V4 Lima Soares & Co Business Manager Meta tem ≥1 ad account real visível ao Wellington (pré-requisito T2)

Production revisions: `v4-ads-mcp-XXXXX-xxx` (preencher após deploy final).

## Smoke results

Preencher conforme execução. Marcar resultado final no fim do arquivo.

| # | Test | Result | Notes |
|---|---|---|---|
| T1 | OAuth happy path Meta (5 scopes aceitos) | ⬜ pending | |
| T2 | Tool `meta_list_my_ad_accounts` via Claude Desktop | ⬜ pending | |
| T3 | Granular permission rejection (`ads_read` desmarcado) | ⬜ pending | |
| T4 | Audit_log entry com `platform="meta"` (T1+T2 lookback) | ⬜ pending | |
| T5 | Token expiry simulation (DB update + tool re-run) | ⬜ pending | |
| T6 | Revoke flow `/oauth/meta/revoke` | ⬜ pending | |
| T7 | Regression CRITICAL — Google Ads tools intactas pós-rename | ⬜ pending | |

**Effective result:** N/7 PASS + Y DEFERRED

### F-findings emerged

_Preencher durante smoke. Template: `**F## (SEV)** — <symptom>. Fix: <plan>. Family: <bug class>.`_

Se zero F-findings: documentar explicitly "Zero F-findings novos. Sprint clean."

### Sign-off

- [ ] Pre-push gate 5/5 PASS
- [ ] Pre-push gate FULL 6/6 PASS (Docker — MANDATORY pra big-bang refactor)
- [ ] Spec compliance + code quality reviewers APPROVED
- [ ] Production `/health` 200 (revisão final)
- [ ] T1 PASS (OAuth happy path — bloqueador hard pra todo o restante)
- [ ] T2 PASS (tool ponta-a-ponta via Claude — proof of life MCP Meta)
- [ ] T3 PASS (granular permission rejection — segurança LGPD/scope)
- [ ] T4 PASS (audit_log `platform="meta"` populado corretamente)
- [ ] T5 PASS ou DOCUMENTED (M.2a tool é DB-cache only — token check exercitado em M.2b primeira Graph API tool)
- [ ] T6 PASS (revoke flow + state cleanup)
- [ ] T7 PASS (CRITICAL — Google Ads tools intactas, big-bang rename sem regression)
- [ ] CLAUDE.md "Shipped — Meta Ads" tabela updated (M.1 ✅ → M.2a ✅) + tool count 57 → 58
- [ ] CLAUDE.md "Pending / future" Meta entry trimmed (M.2a items movidos pra shipped)
- [ ] sprint-history.md entry Sprint M.2a (se aplicável — confirmar se Meta sprints entram lá ou em arquivo separado)
- [ ] findings-catalog.md atualizado se F-findings emergiram (`/findings-add` skill)
- [ ] Tool count 58 confirmado em produção (`test_registered_tool_count_matches_files_on_disk` 58==58)

---

## Pre-smoke setup

### Step 1: Sanity check no MCP client + webapp admin

Conectar Claude/Inspector à URL de produção (`https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app`) e verificar que `meta_list_my_ad_accounts` aparece na lista de tools com parâmetros corretos:

```
# Introspect — esperar ver meta_list_my_ad_accounts com:
# - sem inputs obrigatórios (read all ad_accounts cached pra manager logado)
# - response shape: array de {account_id, account_name, currency, timezone, account_status_label, ...}
# - additionalProperties: false
```

Se `meta_list_my_ad_accounts` não aparece ou tool count ainda 57, deploy não landed — abortar smoke.

Webapp sanity:

```
# Browser → https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/admin (logged in como wellinton.ribeiro@v4company.com)
# Esperar ver:
# - Card "Suas conexões OAuth" com 2 sub-cards paralelos: Google + Meta
# - Sub-card Meta status: "Desconectado" + botão "Conectar Meta" (antes de T1)
# - Sub-card Google status: "Conectado" + email Wellington + expira em N dias (assumindo Google connection já existente)
```

Se card "Suas conexões OAuth" não aparece ou layout quebrado, deploy não landed corretamente — abortar smoke.

### Step 2: Wellington UUID + baseline DB state

Capturar `manager_id` UUID do Wellington pra rollback queries em T5/T6:

```sql
-- Via Supabase SQL Editor (mcp__supabase__execute_sql ou dashboard)
SELECT id, email FROM managers WHERE email = 'wellinton.ribeiro@v4company.com';
-- Anotar id retornado (UUID) — usar em T5/T6 rollback queries
```

Anotar `<wellington_uuid>` pra todas as queries SQL deste smoke.

Baseline pre-smoke audit_log Meta state:

```sql
-- Esperar 0 entries antes de T1 (primeira execução Meta)
SELECT COUNT(*) FROM audit_log WHERE platform = 'meta';
-- Se >0: documentar entries pre-existentes; smoke contará apenas DELTAS pós-T1
```

Baseline pre-smoke meta_oauth_connections state:

```sql
-- Esperar 0 rows ou 1 row revoked (sem connection ativa antes de T1)
SELECT manager_id, fb_email, scopes, token_expires_at, revoked_at
FROM meta_oauth_connections
WHERE manager_id = '<wellington_uuid>';
```

Se já existe connection ativa (`revoked_at IS NULL`), Wellington fez OAuth Meta em sprint M.1 testing → revoke manual antes de T1:

```sql
UPDATE meta_oauth_connections
SET revoked_at = now()
WHERE manager_id = '<wellington_uuid>' AND revoked_at IS NULL;
```

### Step 3: Cloud Run logs streaming setup

Em terminal separado, manter logs streaming pra captar errors durante OAuth callback:

```
gcloud run services logs read v4-ads-mcp \
  --region=southamerica-east1 \
  --project=v4-ads-mcp-prod \
  --limit=50
```

Pra streaming contínuo, usar `--follow` (ou re-rodar manualmente entre tests).

### Step 4: Captura screenshot consent screen pra docs (opcional)

Antes de aceitar consent em T1, screenshot dos 5 scopes mostrados ao usuário pelo Facebook — útil pra documentação user-facing futura ("o que você está autorizando V4 Ads MCP a fazer"). Salvar em `docs/operacao/screenshots/m2a-consent-screen.png` (criar diretório se não existir).

---

## Test T1 — OAuth happy path Meta (5 scopes aceitos)

**Setup:** Primeiro OAuth Meta ponta-a-ponta. Wellington autoriza V4 Ads MCP em V4 Lima Soares & Co BM, aceita TODOS os 5 scopes pedidos, validamos que callback persiste connection corretamente em `meta_oauth_connections` + UI reflete status "Conectado".

**Steps:**

1. Browser → `https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/admin` (logged in wellinton.ribeiro@v4company.com)
2. Localizar sub-card "Meta" no card "Suas conexões OAuth"
3. Click no botão "Conectar Meta"
4. Browser redireciona pra `https://www.facebook.com/<version>/dialog/oauth?...` (consent screen Facebook)
5. Verificar consent screen lista exatamente 5 scopes:
   - `ads_read` (Ler campanhas, anúncios e relatórios)
   - `ads_management` (Gerenciar campanhas e anúncios)
   - `business_management` (Acesso a Business Managers)
   - `email` (Endereço de e-mail)
   - `public_profile` (Perfil público — name, profile_pic)
6. Click "Continuar como Wellington" (ou equivalente)
7. Confirma "Permitir" sem desmarcar nada
8. Browser redireciona pra `https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/oauth/meta/callback?code=...&state=...`
9. Servidor processa callback → final redirect pra `https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/admin?meta_connected=1`
10. Card Meta agora mostra status "Conectado" + fb_email Wellington + "Expira em ~60 dias"

**Expected DB state (validar via SQL Editor pós-redirect):**

```sql
SELECT manager_id, fb_user_id, fb_email, scopes, token_expires_at, revoked_at, created_at
FROM meta_oauth_connections
WHERE manager_id = '<wellington_uuid>';
```

Esperar 1 row:
- `fb_user_id`: numeric string Facebook user ID (não null)
- `fb_email`: `'wellinton.ribeiro@v4company.com'` (ou outro email pessoal Facebook se diferente)
- `scopes`: array string contendo os 5 scopes: `{ads_read,ads_management,business_management,email,public_profile}`
- `token_expires_at`: timestamp aproximadamente `now() + interval '60 days'` (Facebook long-lived token)
- `revoked_at`: NULL
- `created_at`: timestamp ≈ now() ± 1 minuto

**Validação:**

- [ ] Redirect Facebook → consent screen exibe 5 scopes corretos (screenshot Step 4 opcional)
- [ ] Click "Permitir" → redirect callback success (HTTP 302 → /admin?meta_connected=1)
- [ ] Cloud Run logs sem ERROR/CRITICAL durante callback (apenas INFO `meta.oauth.callback.success`)
- [ ] Card admin atualiza pra "Conectado" sem necessidade de hard refresh (HTMX swap OK)
- [ ] DB `meta_oauth_connections` tem 1 row pra Wellington com 5 scopes
- [ ] `token_expires_at` ~60 dias no futuro (Facebook long-lived padrão)
- [ ] `revoked_at IS NULL` (active connection)
- [ ] Audit_log +1 entry: `platform='meta'`, `action_type='auth'`, `operation='meta_oauth_connect'`, `status='success'`, `target_count` = número de Ad Accounts cached (validar em T4)

**Result:** ⬜ pending

---

## Test T2 — Tool `meta_list_my_ad_accounts` via Claude Desktop

**Setup:** Primeira MCP tool Meta ponta-a-ponta via Claude Desktop (Bearer MCP token + Streamable HTTP). Tool é DB-cache only (não chama Graph API neste sprint), mas valida (1) tool registration MCP no manifest, (2) SDK `facebook-business` import path funcionando em runtime sem ImportError, (3) repository `meta_ad_accounts` query OK, (4) JSON serialization correto pra response shape Meta-specific (currency BRL, timezone America/Sao_Paulo, account_status_label PT-BR).

**Pré-requisito:** Após T1 success, Wellington precisa fazer Claude Desktop **disconnect + reconnect** do v4-ads MCP server pra refresh tool cache (Claude Desktop cache tool list at session start):

1. Claude Desktop → Settings → MCP Servers → v4-ads → Disconnect
2. Reconnect (Bearer MCP token Wellington já populado)
3. Verify "57 tools" → "58 tools" no Claude UI tool indicator (ou similar — depende UX Claude Desktop)

**Steps:**

1. Em Claude Desktop, prompt PT-BR: **"Liste minhas contas Meta"**
2. Claude resolve intent → invoca `meta_list_my_ad_accounts` (sem args)
3. Tool retorna response shape

**Expected response shape:**

```json
{
  "manager_id": "<wellington_uuid>",
  "fb_email": "wellinton.ribeiro@v4company.com",
  "ad_accounts": [
    {
      "account_id": "act_NNNNNNNNNN",
      "account_name": "V4 Lima Soares - <cliente X>",
      "currency": "BRL",
      "timezone": "America/Sao_Paulo",
      "account_status_label": "ATIVO",
      "business_manager_id": "<bm_id>",
      "business_manager_name": "V4 Lima Soares & Co"
    },
    /* ... mais accounts visíveis ao Wellington em V4 Lima Soares & Co BM ... */
  ],
  "total_accounts": N
}
```

**Validação:**

- [ ] Claude Desktop tool count atualizou 57 → 58 após reconnect (visível na UI MCP servers)
- [ ] Prompt "Liste minhas contas Meta" → Claude invoca `meta_list_my_ad_accounts` (não outra tool, não ambiguidade)
- [ ] Response NO error (sem ImportError facebook-business, sem `MetaTokenExpiredError` falsa)
- [ ] `ad_accounts[]` non-empty (≥1 entry — V4 Lima Soares & Co tem ad accounts reais)
- [ ] Cada entry tem todas as fields: `account_id` (prefixo `act_`), `account_name`, `currency`, `timezone`, `account_status_label`, `business_manager_id`, `business_manager_name`
- [ ] **Crítico V4 invariant:** Cada entry tem `currency: "BRL"` (V4 unidade BR-only)
- [ ] **Crítico V4 invariant:** Cada entry tem `timezone: "America/Sao_Paulo"`
- [ ] `account_status_label` em PT-BR enum: `"ATIVO"` (ativo) | `"DESABILITADO"` (disabled) | `"NAO_RECONCILIADO"` (unsettled) | `"PENDENTE_RISCO"` (pending risk review) | `"PENDENTE_FECHAMENTO"` (pending closure) | `"FECHADO"` (closed) | `"OUTRO"` (any unknown) — NÃO retornar Meta raw int code
- [ ] `total_accounts == len(ad_accounts)` (consistência)
- [ ] Resposta volta em <2s (cache local, sem Graph API call)
- [ ] Audit_log +1 entry (se tool tem `audit_this_call=True`; M.2a spec confirma audit_this_call=False pra read-only inocuous — verificar)

**Fallback se Wellington não vê ad accounts visíveis em V4 Lima Soares & Co BM:**
- Provavelmente role/permission Meta BM insuficiente — Wellington precisa ser pelo menos "Admin" ou "Funcionário" com acesso a ad accounts
- T2 BLOCKED — pre-requisite Meta BM access falha
- Resolver: BM owner adiciona Wellington como "Funcionário com acesso completo" antes de re-rodar

**Result:** ⬜ pending

---

## Test T3 — Granular permission rejection (`ads_read` desmarcado)

**Setup:** Validar enforcement granular permission Facebook. Wellington reinicia OAuth flow MAS no consent screen desmarca `ads_read` (intencionalmente removendo scope crítico). Servidor callback deve detectar scope ausente, REJEITAR a connection, e redirecionar pra `/access-denied?reason=meta_scopes_missing&missing=ads_read` com mensagem PT-BR.

**Pré-requisito:** T1 já completou (Wellington tem connection ativa). Em T3 vai re-OAuth — Facebook permite re-autorizar com scope subset.

**Steps:**

1. Browser → `https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/admin`
2. Sub-card Meta mostra "Conectado" (de T1)
3. Click "Reconectar" (ou "Desconectar" → "Conectar Meta" se UX exigir clean restart)
4. Browser redireciona pra Facebook consent screen
5. **Crítico:** No consent screen Facebook, click "Editar acesso" (ou link similar — Facebook permite desmarcar scopes opcionais)
6. **Desmarcar `ads_read`** (manter os outros 4 marcados)
7. Click "Continuar" / "Permitir"
8. Browser redireciona pra callback URL com `granted_scopes` subset (sem `ads_read`)
9. Servidor processa callback → detecta missing scope → REJEITA connection (NÃO persiste em DB)
10. Final redirect pra `https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/access-denied?reason=meta_scopes_missing&missing=ads_read`
11. Página `/access-denied` exibe mensagem PT-BR + link "Conecte novamente"

**Expected página `/access-denied`:**

```
[V4 logo]

Acesso negado

A integração com Meta Ads precisa do permissionamento "ads_read" pra funcionar.
Você desmarcou esse acesso no consent do Facebook — sem ele não conseguimos ler suas campanhas.

[Botão: "Conecte novamente"] → re-inicia /oauth/meta/start
[Link secundário: "Voltar ao admin"] → /admin
```

**Expected DB state (validar via SQL Editor pós-redirect):**

```sql
-- Connection T1 deve estar INTACTA (não foi revogada nem sobrescrita)
SELECT manager_id, scopes, revoked_at
FROM meta_oauth_connections
WHERE manager_id = '<wellington_uuid>';
-- Esperar: 1 row com 5 scopes (de T1), revoked_at NULL
-- NÃO esperar: 2ª row com 4 scopes, ou row substituída

-- Nenhuma nova row criada pra T3 (callback rejeitou ANTES de UPSERT)
```

**Validação:**

- [ ] Consent screen Facebook permite desmarcar `ads_read` (UI Facebook flexível — confirma feature exists)
- [ ] Callback detecta missing scope (Cloud Run logs: WARN `meta.oauth.callback.missing_scopes` + `missing=['ads_read']`)
- [ ] Final redirect = `/access-denied?reason=meta_scopes_missing&missing=ads_read` (URL exata)
- [ ] Página `/access-denied` mostra mensagem PT-BR mencionando "ads_read" pelo nome
- [ ] Página tem botão/link "Conecte novamente" funcional (re-inicia OAuth)
- [ ] DB: connection original T1 INTACTA (scopes 5 + revoked_at NULL) — callback rejeitou antes de UPSERT
- [ ] DB: nenhuma nova row meta_oauth_connections (callback aborta limpo)
- [ ] Audit_log +1 entry: `platform='meta'`, `action_type='auth'`, `operation='meta_oauth_connect'`, `status='rejected'`, `params_summary` contém `missing_scopes`

**Fallback se Facebook não permitir desmarcar `ads_read` (algumas BMs forçam todos scopes):**
- T3 **DEFERRED** — env limitation, Facebook UI dependente de BM configuration
- Alternativa: simular via unit test `test_callback_rejects_missing_required_scope` (mock granted_scopes sem `ads_read`)
- Documentar: "T3 DEFERRED — Facebook UI V4 Lima Soares & Co BM não permite scope subset (BM enforcement). Coverage via unit test."

**Cleanup T3 → preparar T4/T5/T6:**

Se T3 PASS, connection original T1 ainda ativa (confirmado em validation acima). Continuar pra T4 sem ação.

**Result:** ⬜ pending

---

## Test T4 — Audit_log entry com `platform="meta"` (T1+T2 lookback)

**Setup:** Validar refactor foundation Task `audit_log.record(platform=...)` kwarg + migration 004 rename `google_request_id` → `provider_request_id`. Após T1 (OAuth connect) + T2 (tool invoke), audit_log deve conter entries com `platform='meta'` populado corretamente. Verificação dupla: (a) via tool `get_my_audit_log` filtrando últimos 7 dias, (b) via Supabase SQL Editor query raw pra confirmar coluna `provider_request_id` existe e não há regressão em entries Google paralelas.

**Steps Wellington:**

1. Em Claude Desktop, prompt: **"Mostre meu audit log dos últimos 7 dias filtrando platform=meta"** (ou similar)
2. Claude invoca `get_my_audit_log(days=7)` (filtro platform pode não estar exposto V0 — verificar)
3. Manualmente filtra entries `platform='meta'` no output

**Expected entries Meta no audit_log (>=2):**

| occurred_at | platform | action_type | operation | status | provider_request_id | params_summary |
|---|---|---|---|---|---|---|
| T1 timestamp | meta | auth | meta_oauth_connect | success | (Facebook tracking id se SDK retorna, OR NULL) | `{"scopes_granted": 5, "fb_user_id": "..."}` |
| T2 timestamp | meta | read | meta_list_my_ad_accounts | success (se tool tem audit_this_call=True) | NULL (DB-cache only) | `{"total_accounts": N}` |

> **Nota M.2a tool audit:** spec confirma `meta_list_my_ad_accounts` com `audit_this_call=False` (read-only DB cache, inocuous). Se for o caso, T4 valida apenas 1 entry Meta (do T1 OAuth). Documentar abordagem escolhida e atualizar validação abaixo.

**Verificação manual via Supabase SQL Editor (mcp__supabase__execute_sql ou dashboard):**

```sql
-- Validar entries Meta pós-smoke
SELECT
  occurred_at,
  manager_id,
  platform,
  action_type,
  operation,
  status,
  provider_request_id,
  params_summary
FROM audit_log
WHERE platform = 'meta'
  AND occurred_at >= now() - interval '1 hour'
ORDER BY occurred_at DESC
LIMIT 10;
```

**Validação:**

- [ ] Esperar >=1 entry Meta (de T1 OAuth) — se tool T2 também audita, esperar >=2
- [ ] Entry T1: `platform='meta'`, `action_type='auth'`, `operation='meta_oauth_connect'`, `status='success'`
- [ ] Entry T1 params_summary: `scopes_granted` numeric (esperado 5) + `fb_user_id` populated (não null)
- [ ] (Se T2 audita) Entry T2: `platform='meta'`, `action_type='read'`, `operation='meta_list_my_ad_accounts'`, `status='success'`, `params_summary.total_accounts` numeric
- [ ] **Crítico migration 004:** Coluna `provider_request_id` EXISTE no schema (não `google_request_id`)
- [ ] **Crítico migration 004:** Entries Google paralelas (de T7 lookback) têm `provider_request_id` populated (não null pra Google Ads operations que retornam tracking ID)
- [ ] Nenhuma entry com `platform = NULL` (default 'google' deve estar aplicado em todas as 50 callers Google)

**Verificação adicional Google regression (cross-check T7):**

```sql
SELECT
  occurred_at,
  platform,
  operation,
  provider_request_id
FROM audit_log
WHERE platform = 'google'
  AND occurred_at >= now() - interval '1 hour'
ORDER BY occurred_at DESC
LIMIT 5;
```

Esperar entries Google recentes (de smokes/usage normal V4) com `platform='google'` (default kwarg) + `provider_request_id` populated.

**Fallback se T2 tool tem `audit_this_call=False`:**
- T4 valida apenas T1 OAuth entry — ajustar expectativa
- Documentar: "T4 PASS com 1 entry Meta (T1 OAuth). Tool `meta_list_my_ad_accounts` é DB-cache read inocuous, `audit_this_call=False` por design. M.2b primeira Graph API tool deverá audit (cost real Meta API + sensitive data)."

**Result:** ⬜ pending

---

## Test T5 — Token expiry simulation (DB update + tool re-run)

**Setup:** Validar handling de token expirado. Como M.2a `meta_list_my_ad_accounts` é **DB-cache only** (não chama Graph API), o token check NÃO é exercitado neste sprint — tool retorna cache local mesmo com token expirado. T5 documenta esse comportamento esperado + valida que UI admin reflete status "Token expirado" corretamente. Smoke completo de token check + refresh logic acontece em **M.2b** quando primeira Graph API tool entrar.

**Steps:**

1. Via Supabase SQL Editor, forçar token_expires_at no passado:

```sql
UPDATE meta_oauth_connections
SET token_expires_at = now() - interval '1 day'
WHERE manager_id = '<wellington_uuid>' AND revoked_at IS NULL;
-- Anotar token_expires_at original ANTES do UPDATE pra rollback
```

2. Browser → `/admin` (hard refresh)
3. Esperar sub-card Meta mostrar status "Token expirado" + botão "Reconectar Meta" (vermelho/warning color)

4. Claude Desktop → prompt "Liste minhas contas Meta" (re-invoca `meta_list_my_ad_accounts`)
5. Esperar response shape **vazio OR populated dependendo design**:
   - **Opção A (recommended):** Tool retorna `ad_accounts: []` + `total_accounts: 0` + warning field `connection_expired: true`
   - **Opção B:** Tool retorna cache local sem warning (read-only DB query não bloqueia em token expirado)

6. Rollback: restaurar `token_expires_at` original

```sql
UPDATE meta_oauth_connections
SET token_expires_at = '<original_value>'
WHERE manager_id = '<wellington_uuid>';
-- OR re-conectar via UI: re-OAuth refresh token_expires_at pra now()+60d
```

7. Re-rodar tool → confirmar response normal (igual T2)

**Validação:**

- [ ] DB update token_expires_at pra passado executa sem erro
- [ ] UI admin sub-card Meta reflete status "Token expirado" (cor warning/vermelho)
- [ ] Botão "Reconectar Meta" visível (não "Conectar" green nem "Conectado")
- [ ] Tool `meta_list_my_ad_accounts` retorna shape consistente (não ERROR HTTP 500):
  - Opção A: `ad_accounts: []` + `connection_expired: true` (graceful)
  - Opção B: cache retornado, comportamento documentado claramente
- [ ] **M.2a-specific assertion:** Nenhuma `MetaTokenExpiredError` raised (tool não exercita Graph API neste sprint)
- [ ] Rollback restore token_expires_at funciona — tool re-run retorna response normal T2
- [ ] Audit_log: T5 tool calls capturadas (igual T2 entries, sem `status='error'`)

**Notas operacionais pra M.2b:**

Em M.2b primeira Graph API tool real (ex.: `meta_get_campaign_performance`), o fluxo completo será:
1. Tool entry → `meta_ads.client.get_access_token(manager_id)` → check `token_expires_at < now() + 5min buffer`
2. Se expired: raise `MetaTokenExpiredError` PT-BR ("Seu acesso ao Meta expirou. Reconecte em /admin.")
3. Claude propaga error message ao usuário em PT-BR
4. Wellington reconecta via UI → token refreshed → re-run tool OK

T5 em M.2b passará a ser o "real test" de expiry — em M.2a é DRY-RUN / behavior documentation.

**Result:** ⬜ pending (PASS expected — comportamento documentado, smoke real M.2b)

---

## Test T6 — Revoke flow `/oauth/meta/revoke`

**Setup:** Validar que revoke endpoint marca connection como revoked + UI admin reflete + tool subsequente retorna empty. Revoke NÃO deleta row (audit trail mantido), apenas seta `revoked_at = now()`.

**Steps:**

1. Confirmar connection ativa (T1 + cleanups T3/T5 OK):

```sql
SELECT manager_id, fb_email, revoked_at
FROM meta_oauth_connections
WHERE manager_id = '<wellington_uuid>'
ORDER BY created_at DESC LIMIT 1;
-- Esperar revoked_at IS NULL
```

2. Browser DevTools console (logged in `/admin`):

```javascript
// Captura CSRF/session cookie ativo, POST direto
fetch('/oauth/meta/revoke', { method: 'POST', credentials: 'include' })
  .then(r => console.log('status:', r.status, 'redirect:', r.url))
  .then(() => location.reload());
```

OR via curl com session cookie (se cookie copyable):

```bash
curl -X POST https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/oauth/meta/revoke \
  -H "Cookie: <session_cookie>" \
  -i
```

3. Esperar HTTP 302 redirect → `/admin?meta_disconnected=1`
4. UI admin sub-card Meta mostra "Desconectado" + botão "Conectar Meta" (restore initial state)

5. Claude Desktop → "Liste minhas contas Meta"
6. Esperar response empty:

```json
{
  "manager_id": "<wellington_uuid>",
  "fb_email": null,
  "ad_accounts": [],
  "total_accounts": 0
}
```

OR error PT-BR "Você não tem uma conexão Meta ativa. Conecte em /admin."

**Expected DB state:**

```sql
SELECT manager_id, fb_email, revoked_at, scopes
FROM meta_oauth_connections
WHERE manager_id = '<wellington_uuid>'
ORDER BY created_at DESC LIMIT 1;
```

Esperar:
- Row T1 ainda EXISTE (não deletada)
- `revoked_at`: timestamp ≈ now() ± 1 minuto (revoke success)
- `fb_email`, `scopes`: mantidos (audit trail histórico)

**Validação:**

- [ ] POST /oauth/meta/revoke retorna HTTP 302 (ou 200 com JSON success)
- [ ] UI admin atualiza pra "Desconectado" + botão "Conectar Meta"
- [ ] DB row T1 mantida, `revoked_at` populado com timestamp recent
- [ ] **Crítico:** Row NÃO deletada (audit trail preserved)
- [ ] Tool `meta_list_my_ad_accounts` pós-revoke retorna empty ou error PT-BR consistente (documentar approach)
- [ ] Cached `meta_ad_accounts` rows: documentar se são deletadas no revoke OR mantidas (decisão M.2a spec — se mantidas, próximo OAuth pode reaproveitar; se deletadas, requer fresh sync em M.2b)
- [ ] Audit_log +1 entry: `platform='meta'`, `action_type='auth'`, `operation='meta_oauth_revoke'`, `status='success'`

**Re-connect pós-revoke (preparar T7 + uso normal):**

Recomendado re-OAuth (igual T1) pra deixar connection ativa pra uso normal Wellington pós-smoke:

1. `/admin` → "Conectar Meta" → consent screen → "Permitir" todos 5 scopes
2. DB: nova row OR row T1 UPSERT (depende design — verificar) com novos `token_expires_at` ~60d
3. Tool T2 funciona normal novamente

**Result:** ⬜ pending

---

## Test T7 — Regression CRITICAL — Google Ads tools intactas pós-rename column

**Setup:** Validar que migration 004 + big-bang refactor `audit_log.record(platform=...)` em 50 caller files NÃO quebrou nenhuma das 57 tools Google existentes. Sample test: 2 tools read Google (`list_my_accounts` + `get_account_overview`) + verificação SQL Editor que `provider_request_id` populated em entries Google novas + `platform='google'` default aplicado.

**Pré-requisito:** T1-T6 já rodaram (audit_log tem entries Meta pra contraste). Wellington tem Google connection ativa (Google OAuth já feito em sprint anterior, não revogar).

**Steps:**

1. Claude Desktop → prompt **"Quais contas Google eu tenho acesso?"**
2. Claude invoca `list_my_accounts` (tool Google existente, NÃO Meta)
3. Esperar response shape igual antes da migration: array de Google accounts (Mestre da Obra JP, ML Antiguidades, etc.)

4. Claude Desktop → prompt **"Me dá um overview da conta 7862230676"** (Mestre da Obra JP)
5. Claude invoca `get_account_overview(customer_id="7862230676")`
6. Esperar response shape normal: campaigns count, total_spend BRL, conversions, etc.

**Validação shape Google tools intactas:**

- [ ] `list_my_accounts` retorna array Google accounts non-empty (Wellington tem acesso a ~23 MCC clientes)
- [ ] Cada entry Google account tem fields esperadas (`customer_id`, `descriptive_name`, `currency`, `time_zone`, etc.)
- [ ] `get_account_overview(7862230676)` retorna shape normal sem ERROR
- [ ] Response Mestre da Obra JP tem dados realistas (não placeholder, não vazio)
- [ ] Tempo resposta normal (<3s pra read tools Google)

**Validação SQL Editor — coluna rename + platform default:**

```sql
-- Validar coluna provider_request_id existe (não google_request_id)
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'audit_log' AND column_name LIKE '%request_id%';
-- Esperar: 1 row, column_name='provider_request_id', data_type='text' (ou similar)
-- NÃO esperar: 'google_request_id' (deve ter sido renomeada)

-- Validar entries Google T7 (recentes) têm provider_request_id + platform='google'
SELECT
  occurred_at,
  platform,
  operation,
  provider_request_id,
  status
FROM audit_log
WHERE platform = 'google'
  AND occurred_at >= now() - interval '10 minutes'
ORDER BY occurred_at DESC
LIMIT 10;
```

Esperar:
- Entries de T7 tool calls (`list_my_accounts`, `get_account_overview`)
- `platform='google'` (default kwarg aplicado em todas as 50 callers)
- `provider_request_id` populated (Google Ads SDK retorna `request_id` em RPC metadata — não null pra tools que fazem RPC; pode ser null pra tools puramente DB-only)
- `status='success'`

**Validação:**

- [ ] Tool `list_my_accounts` retorna shape normal (não quebrou)
- [ ] Tool `get_account_overview(7862230676)` retorna shape normal
- [ ] DB coluna `audit_log.provider_request_id` existe (não `google_request_id`)
- [ ] DB coluna `audit_log.platform` populated com `'google'` em entries T7
- [ ] **Crítico:** Nenhum entry com `platform=NULL` (default deve estar aplicado em todas as callers — 50 files refactor)
- [ ] **Crítico:** Nenhum entry com `google_request_id` field (coluna renamed, queries que referem o nome antigo quebraria — sanity check via SQL `column does not exist` error em SELECT explicit)
- [ ] Audit_log +N entries Google (uma por tool call T7) com fields corretos
- [ ] Pre-push gate FULL passou antes do deploy (Docker — MANDATORY pra big-bang refactor)

**Fallback se Google tool retorna ERROR HTTP 500 ou shape inválido:**
- T7 FAIL **CRITICAL BLOCKER** — não shippa M.2a, rollback deploy IMEDIATAMENTE
- Investigar: stack trace Cloud Run logs → identificar arquivo caller com refactor incorreto
- Fix forward: corrigir caller(s) + re-run pre-push FULL + re-deploy
- Re-rodar T7 até PASS antes de signoff

**Fallback se entries Google têm `platform=NULL`:**
- T7 FAIL — refactor incompleto, callers Google faltaram receber kwarg default
- Investigar: `grep -rn "audit_log.record(" src/` → identificar callers sem `platform=` ou `platform='google'`
- Fix forward: completar refactor + integration test cobrindo todas as callers

**Result:** ⬜ pending **(CRITICAL — bloqueador hard pra sprint signoff)**

---

## Per-value empirical probe (Sprint 3b.19A.1 convention)

**Nota M.2a:** Tool `meta_list_my_ad_accounts` é input-less (nenhum enum whitelist no schema). Probe **não-aplicável** neste sprint.

**Probe equivalente — granted_scopes whitelist (Meta OAuth callback):**

A única "whitelist" relevante em M.2a é o conjunto de 5 scopes Meta required. Probe = T1 (todos aceitos) + T3 (faltando `ads_read` rejeitado). Coverage adequado.

V0+ candidates (probe expandido conforme tools Meta crescem em M.2b → M.25):
- `meta_get_campaign_performance` provavelmente terá enum `date_preset` (Meta-specific, diferente do Google: `last_7d`, `last_14d`, etc.) — probe per value em M.2b
- `meta_create_campaign` em sprint futuro terá enum `objective` whitelist V4 (`OUTCOME_LEADS`, `OUTCOME_SALES`, etc. — diferente do Google `goal_type`)

**Per-scope OAuth probe (T1+T3 cobre):**

| # | Scope value | Required? | T1 expected | T3 expected (sem ads_read) |
|---|---|---|---|---|
| S1 | `ads_read` | YES (required) | ✅ granted | ❌ REJECTED (T3 trigger) |
| S2 | `ads_management` | YES (required) | ✅ granted | ✅ granted (se Wellington só desmarcou ads_read) |
| S3 | `business_management` | YES (required) | ✅ granted | ✅ granted |
| S4 | `email` | YES (required pra display name) | ✅ granted | ✅ granted |
| S5 | `public_profile` | YES (Facebook default) | ✅ granted | ✅ granted |

Critério: T1 PASS (5 scopes granted) + T3 PASS (rejection em missing required scope) = scope whitelist validado empiricamente.

---

## V4 invariants validation

| Invariant | Aplicável | Enforcement | How smoke verifies |
|---|---|---|---|
| country_code = BR | N/A | N/A — Meta ad accounts BR-only via BM V4 Lima Soares & Co; tool não filtra country | — |
| language_code = pt-BR | ✅ User-facing | Mensagens UI admin + `/access-denied` PT-BR; tool description PT-BR; `account_status_label` enum PT-BR | T2 valida labels PT-BR; T3 valida mensagem `/access-denied` PT-BR |
| currency_code = BRL | ✅ Output | `meta_ad_accounts.currency` filtered to `BRL` no sync (cached only BRL accounts) OR returned as-is (M.2a spec — verificar) | T2 valida cada entry tem `currency: "BRL"` |
| timezone = America/Sao_Paulo | ✅ Output | `meta_ad_accounts.timezone` filtered/validated; tool returns `timezone: "America/Sao_Paulo"` (Meta API formato IANA) | T2 valida cada entry tem `timezone: "America/Sao_Paulo"` |
| LGPD consent | ✅ Critical | OAuth flow consent screen Facebook + scope `email` + `public_profile` explicit; user must check + accept; audit_log captures consent timestamp via `meta_oauth_connect` entry | T1 consent screen mostra scopes; audit_log T1 entry captura grant |
| Schema whitelist (3b.19A) | N/A | Tool M.2a sem enum input — válido pra V0 input-less | Cobertura em M.2b+ conforme tools enum-bearing entram |
| OAuth scope granular enforcement | ✅ Security | Callback handler valida `granted_scopes ⊇ required_scopes`; faltando = redirect access-denied; nunca persist partial connection | T3 valida rejection + UI access-denied |
| No composition keywords (3b.19B.1) | ✅ Schema | Tool input schema sem `oneOf/allOf/anyOf` (input-less = trivialmente válido) | Regression `test_no_composition_keywords_in_any_schema` (pre-push) |
| Audit log platform multi-tenancy | ✅ Foundation | `audit_log.platform: text NOT NULL DEFAULT 'google'`; entries Meta = `'meta'`; entries Google = `'google'` (default kwarg) | T4 valida Meta entries; T7 valida Google entries; nenhuma com NULL |
| Migration 004 rename | ✅ Foundation | Coluna `audit_log.provider_request_id` (renomeada de `google_request_id`); 50 caller files refactored | T4 + T7 SQL Editor confirma coluna existe + populated |
| Token expiry handling (M.2a vs M.2b) | ✅ Architecture | M.2a tool DB-cache only — NÃO exercita token check; M.2b primeira Graph API tool exercitará `MetaTokenExpiredError` PT-BR | T5 documenta behavior atual (DB cache OK em token expirado); M.2b smoke validará real expiry |
| Revoke audit trail preserved | ✅ Foundation | `meta_oauth_connections.revoked_at` set instead of DELETE; row mantida pra audit/re-OAuth UPSERT | T6 valida row mantida + `revoked_at` populated |
| Big-bang refactor regression-free | ✅ Critical | 57 Google tools intactas; `audit_log.record(platform='google')` default em 50 callers; coluna rename sem breaking change | T7 sample 2 Google tools + DB SQL Editor confirma |

---

## Cleanup post-smoke

Não há cleanup destrutivo necessário. State pós-smoke esperado:

- `meta_oauth_connections`: 1 row ativa pra Wellington (re-connected em T6 cleanup) com `revoked_at IS NULL`
- `meta_ad_accounts`: rows cached refletem ad accounts visíveis ao Wellington em V4 Lima Soares & Co BM
- `audit_log`: novas entries persistentes pra rastreio histórico — 1 entry T1 (auth.connect) + 1 entry T3 (auth.rejected) + 1 entry T6 (auth.revoke) + 1 entry T6 (auth.connect re-OAuth) + N entries Google T7 + (opcional) entries T2/T5 se tool audit ativo
- `audit_log.platform`: distribution mista `'google'` (predominante, uso normal V4) + `'meta'` (entries smoke)
- Sprint M.2a status: shipped ✅, foundation pra M.2b → M.25

**Rollback se smoke falhou (T1 ou T7 FAIL CRITICAL):**

```sql
-- 1. Marcar connection Meta revogada (limpar state)
UPDATE meta_oauth_connections
SET revoked_at = now()
WHERE manager_id = '<wellington_uuid>' AND revoked_at IS NULL;

-- 2. (Opcional) Limpar cached ad_accounts se causando confusão
DELETE FROM meta_ad_accounts WHERE manager_id = '<wellington_uuid>';
```

Investigar logs:

```
gcloud run services logs read v4-ads-mcp \
  --region=southamerica-east1 \
  --project=v4-ads-mcp-prod \
  --limit=200
```

Para rollback deploy completo (T7 CRITICAL FAIL):

```bash
# Listar revisions
gcloud run revisions list --service=v4-ads-mcp --region=southamerica-east1 --limit=5

# Roteirizar 100% pra revision anterior
gcloud run services update-traffic v4-ads-mcp \
  --region=southamerica-east1 \
  --to-revisions=<previous_revision>=100
```

Fix forward é preferível a rollback — investigate + corrige + re-deploy. Rollback usar apenas se Wellington/usuários reais impactados.

---

## Notas pra Wellington pós-smoke

1. **Sprint M.2a é sprint family parte 1 de 2.** M.2a entrega foundation OAuth + 1ª tool (DB cache). **M.2b entrega 1ª Graph API tool real** (provavelmente `meta_get_campaign_performance`) que exercita rate limit Meta + token check + refresh logic + audit_this_call=True. Smoke M.2b será mais elaborado (incluir rate counter probe, MetaTokenExpiredError PT-BR end-to-end, primeira validação real de cost/conversion data Meta).
2. **Decisão crítica M.2a→M.2b descobrir no spec M.2b:** primeira Graph API tool — opções priorizadas:
   - `meta_get_campaign_performance(account_id, date_preset)` — paralelo a `get_account_overview` Google
   - `meta_list_campaigns(account_id)` — paralelo a `list_campaigns` Google
   - `meta_get_audience_performance(account_id)` — sem paralelo Google direto, valor único Meta
   Brainstorm M.2b spec com `superpowers:brainstorming` antes de escolher.
3. **Roadmap M family update:** após M.2a ship, atualizar CLAUDE.md "Shipped — Meta Ads" tabela:
   ```
   | Sprint M.1 — Foundation | ✅ 2026-05-24 | DB schema 003... |
   | Sprint M.2a — OAuth + first tool | ✅ <data> | Foundation refactor + OAuth flow + meta_list_my_ad_accounts. Tool count 57→58. |
   ```
4. **Webapp UX learning:** card "Suas conexões OAuth" pattern Google + Meta paralelos provavelmente reutilizado em M-? se adicionarmos Bing Ads / TikTok Ads. Validar UX em T1 com olho crítico (Wellington como early user).
5. **Audit_log dataops impact:** após M.2a ship, queries dataops futuras precisam considerar `platform` field. Ex.: cost tracking, usage analytics, rate limit dashboards — todos devem `WHERE platform=?` ou GROUP BY platform. Documentar em `docs/operacao/data-model-conventions.md` (criar se não existir).
6. **Granular permission learning (T3):** Facebook OAuth allows scope subset acceptance — V4 enforcement no callback é correto e LGPD-compliant. Pattern reutilizável pra OAuth flows futuros com providers similares.
7. **Pending items M.2a → M.2b plan (Task 1-N candidatos):**
   - Decisão primeira Graph API tool (brainstorm spec)
   - `meta_rate_counters` repository CRUD já existe pós-M.2a, mas integração com rate limit middleware Meta ainda não — M.2b Task
   - `MetaTokenExpiredError` PT-BR message + propagation pra Claude pendente
   - Webhook subscription pra access_token revocation (Meta envia webhook quando user revoga via Facebook UI fora do V4 admin) — V1+ feature, low priority
8. **Sprint M family timeline check:** ~25 sprints M.1-M.25 (3-6 meses até paridade ~45 tools Meta). M.1+M.2a = 2 sprints, ~23 restantes. Cadência sugerida: 1 sprint M-? por semana se Wellington solo dev, 2-3/semana se 3 colaboradores V4 Lima Soares & Co entrarem pós-M.2b.
9. **Tool count tracking:** atualizar CLAUDE.md sprint counter + sprint-history.md após signoff. **Tool count 57 → 58** (primeira Meta tool).
10. **F-finding catalog update:** se T1-T7 emergirem F-findings (provável em primeira ponta-a-ponta tão grande), usar `/findings-add` skill — comum em sprints foundation: schema gotcha PostgreSQL, OAuth state mismatch, scope enforcement edge case, refactor leftover (callers Google esquecidos), etc.
