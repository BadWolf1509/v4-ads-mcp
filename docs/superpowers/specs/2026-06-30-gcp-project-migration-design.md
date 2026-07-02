# Design — Migração do projeto GCP (lift-and-shift autônomo)

> **Status:** ✅ **EXECUTADO 2026-06-30** — serviço no ar no projeto novo `v4-ads-mcp` (owner próprio), OAuth Google e2e OK, cutover do Wellington feito. Pendências (cutover dos outros gestores, F66 job `migrate`, F67 custom domain, ML Antiguidades/Pinda) no [handoff](../../operacao/session-2026-06-30-handoff.md). Desvios do plano: URL default mantida (custom domain virou passo à parte por F67); job `migrate` não roda (F66) mas é redundante (schema no DB compartilhado); Bearers antigos seguem válidos (cutover = só trocar URL).
> **Topo relacionado:** [session-2026-06-30-handoff.md](../../operacao/session-2026-06-30-handoff.md) · findings F64/F65 · [[meta-token-scoping-and-iam-gargalo]].

## 1. Motivação

O projeto atual `v4-ads-mcp-prod` ficou **sem owner humano**: a conta criadora (`wellinton.ribeiro@`, com typo, era owner) foi excluída e a nova (`wellington.ribeiro@`) tem **ZERO IAM** no projeto. Deploys seguem (WIF/`GCP_DEPLOY_SA`), mas toda ops manual (ler/gravar secrets, Cloud Run, rollback) está bloqueada. Confirmado nesta sessão: o `GCP_DEPLOY_SA` **não tem acesso a secrets** (probe `IAM_PERMISSION_DENIED`), então nem por CI dá pra destravar. Conceder owner exigiria um Org Admin de um org de **4000+ contas** (acionamento difícil).

Decisão: em vez de depender do org, **criar um projeto novo onde `wellington.ribeiro@` é owner desde o início** (autonomia permanente). Confirmado que a conta **consegue criar billing + projeto** sob o org `v4company.com`. Bônus: a migração **resolve o F64** — o novo `meta-system-user-token` nasce *all-targets*, então contas Meta novas entram sozinhas.

## 2. Decisões de design (com rationale)

| # | Decisão | Rationale |
|---|---|---|
| D1 | **Billing própria da unidade** (cartão Lima Soares) | Único caminho autônomo (billing corporativa V4 reintroduz a dependência do IT). Custo trivial: Cloud Run escala a zero, 4 gestores → estimado <US$10/mês. |
| D2 | **URL default `*.run.app`** (sem custom domain) | Escolha do gestor por simplicidade. Implica reconfigurar OAuth URIs + 4 clientes (aceito). |
| D3 | **Regenerar `aes-master-key` + `session-signing-key`** | Sem backup fora do GCP e irrecuperáveis (refém). Consequência: refresh tokens cifrados viram ilegíveis → **4 reconexões Google OAuth** + re-login. Meta NÃO afeta (system-user token). |
| D4 | **Mesmo Supabase** (DB não migra) | Externo ao GCP. `database-url` + supabase keys recuperáveis do dashboard (gestor tem acesso). |
| D5 | **Cutover paralelo (blue-green)** | Novo aponta pro mesmo Supabase; valida antes de virar; rollback trivial; os dois coexistem sem conflito (cada um lê os tokens cifrados com a sua chave; reconexão sobrescreve). |

## 3. Escopo

**Não muda:** código (mesmo repo + `deploy.yml`), Supabase, região `southamerica-east1`, arquitetura. É lift-and-shift, não redesenho.

**Muda:** projeto GCP, billing, URL do Cloud Run, OAuth clients (Google novo no projeto novo; Meta adiciona redirect URI), chaves de cifra (novas), Bearer tokens v4-ads (novos via `/sessions`), `~/.claude.json` dos 4 clientes.

## 4. Inventário de secrets (origem sem o GCP antigo)

| Origem | Secrets |
|---|---|
| **Supabase dashboard** | `database-url`, `supabase-url`, `supabase-anon-key`, `supabase-service-key` |
| **Regenerar** | `aes-master-key` (`secrets.token_urlsafe(32)`), `session-signing-key`, `meta-system-user-token` (gerar *all-targets* no app *V4 Ads MCP*) |
| **Recuperável (gestor é admin)** | `meta-app-id`, `meta-app-secret` (app Meta), `google-ads-developer-token` (Bitwarden "Google ads V4"/MCC), `google-ads-login-customer-id` (= MCC `6436352492`) |
| **Criar no projeto novo** | `google-oauth-client-id`, `google-oauth-client-secret` (novo OAuth 2.0 Client + consent screen *internal*) |

Criação de secret no Windows segue F47 (arquivo binary intermediário, nunca pipe PowerShell).

## 5. Fases de execução (responsabilidade marcada)

> `[G]` = gestor no console/UI · `[C]` = Claude automatiza (gcloud script / código / CI).

1. **Projeto base** `[G]` — criar projeto (sugestão `v4-ads-mcp`), vincular billing própria, habilitar APIs (Run, Cloud Build, Artifact Registry, Secret Manager, Cloud Scheduler, IAM, Google Ads).
2. **Identidade & infra** `[C]` provê comandos, `[G]` executa autenticado como owner — Artifact Registry repo, runtime SA + roles, deploy SA + roles, **WIF pool/provider** federado com `BadWolf1509/v4-ads-mcp`.
3. **Secrets** `[C]` script (binary-safe), `[G]` roda — recuperar/regenerar conforme §4.
4. **Jobs + deploy** `[C]` — criar Cloud Run Jobs `migrate`+`resync` (devem existir antes do `deploy.yml`), atualizar GitHub secrets (`GCP_PROJECT_ID`/`GCP_WIF_PROVIDER`/`GCP_DEPLOY_SA`/`GCP_REGION`) `[G]`, push → `deploy.yml` roda; criar Cloud Scheduler do resync.
5. **OAuth** `[G]` — após o 1º deploy revelar a URL: criar Google OAuth client com redirect URI = nova URL; adicionar a URL como *Valid OAuth Redirect URI* no app Meta; gravar `google-oauth-*` secrets; redeploy se necessário. (Nota de ordem: a URL só existe pós-deploy — OAuth é configurado depois e pode exigir 1 redeploy.)
6. **Validação** `[C]`+`[G]` — `/health?deep=1` (db=ok), smoke `/mcp` 401, 1 gestor reconecta Google OAuth e roda 1 tool read (`list_my_accounts`).
7. **Cutover** `[G]` — emitir Bearer novos via `/sessions` do ambiente novo; atualizar `~/.claude.json` dos 4 (URL + Bearer); 4 reconexões Google OAuth.
8. **Decomissão** — manter o antigo como fallback ~1–2 semanas; depois parar o serviço antigo (a billing antiga não é nossa, mas o serviço fica ocioso/parado).

## 6. Riscos & mitigações

- **Refresh tokens ilegíveis no novo (chave nova)** → esperado; mitigado pelo paralelo (antigo serve quem não reconectou) + só 4 gestores. Meta intacto.
- **Ordem OAuth ↔ URL circular** → deploy primeiro, configurar redirect URIs depois (1 redeploy se preciso).
- **Jobs inexistentes no 1º deploy** (`deploy.yml` faz `jobs update`) → criar `migrate`+`resync` antes (fase 4).
- **Dois ambientes no mesmo Supabase** → seguro p/ a janela (sem migrations destrutivas durante o paralelo; evitar rodar o job `migrate` novo enquanto o antigo está vivo se houver migration nova pendente).
- **Billing própria** → confirmar alerta de orçamento (ex: US$20/mês) pra não haver surpresa.

## 7. Critérios de sucesso

- `/health?deep=1` no novo retorna `db=ok`; `/mcp` gateia 401 sem Bearer.
- Os 4 gestores operam via a URL nova; `list_my_accounts` (Google) e `meta_list_my_ad_accounts` retornam dados.
- `meta_list_my_ad_accounts` no novo **inclui CA-MDO Goiânia** (prova do token all-targets — F64 fechado).
- Resync diário roda no novo (Cloud Scheduler) e o `audit_log` registra.
- Gestor tem **owner** no projeto novo (lê/grava secrets, rollback) — gargalo de origem eliminado.

## 8. Rollback

Durante o paralelo, reverter = apontar o `~/.claude.json` de volta pra URL antiga (o ambiente antigo segue vivo com a chave antiga). Sem perda de dados (mesmo Supabase). Só decomissionar o antigo após os 4 estáveis no novo.

## 9. Out of scope (YAGNI)

Custom domain (D2), IaC/Terraform, 2º owner humano (recomendado operacionalmente, mas não bloqueia), migração do DB (Supabase fica), Onda 5 (`mark_inactive_except`, F65 — sprint separado).
