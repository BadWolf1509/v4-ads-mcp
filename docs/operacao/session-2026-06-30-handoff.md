# Sessão 2026-06-30 — Handoff (MIGRAÇÃO GCP executada)

> Investigação Meta (F64/F65) → **migração lift-and-shift** do projeto GCP pra um onde o Wellington é **owner** (o antigo ficou sem owner humano e o IAM era inacessível). Serviço novo **no ar e funcional**. Restam cutover dos outros 3 gestores + polimento.

## TL;DR

- **Novo projeto:** `v4-ads-mcp` (number `299432068772`), org v4company.com, **billing própria da unidade**, Wellington **owner**. IAM destravado.
- **URL produção:** `https://v4-ads-mcp-299432068772.southamerica-east1.run.app` (`/health?deep=1` db=ok, `/mcp` 401).
- **F64 resolvido:** token Meta **all-targets** → 19 contas + 25 páginas (a `CA - MDO Goiânia` voltou).
- **Bearers antigos seguem válidos** (hash no DB compartilhado) → cutover = só trocar a URL no `~/.claude.json`.
- **Chaves `aes-master-key`/`session-signing-key` regeneradas** → gestores **reconectam Google OAuth** uma vez (Meta não afeta — system-user token).

## Por que migrou

O projeto antigo `v4-ads-mcp-prod` foi criado pela conta `wellinton.ribeiro@` (typo), que foi **excluída** → projeto **sem owner humano**, IAM inacessível pra `wellington.ribeiro@`. Confirmado nesta sessão: o `GCP_DEPLOY_SA` não tem acesso a Secret Manager (não dá pra destravar por CI); Org Admin V4 (4000+ contas) é difícil de acionar. `wellington.ribeiro@` **consegue criar projeto + billing própria** → migração autônoma (owner desde o início).

## Inventário do ambiente novo (IDs pra não re-descobrir)

| Recurso | Valor |
|---|---|
| Projeto / number | `v4-ads-mcp` / `299432068772` |
| Região | `southamerica-east1` |
| Runtime SA | `v4-ads-mcp-runtime@v4-ads-mcp.iam.gserviceaccount.com` (roles/secretmanager.secretAccessor) |
| Deploy SA | `v4-ads-mcp-deploy@v4-ads-mcp.iam.gserviceaccount.com` (run.admin, cloudbuild.builds.editor, artifactregistry.writer, iam.serviceAccountUser, storage.admin, serviceusage.serviceUsageConsumer) |
| WIF provider | `projects/299432068772/locations/global/workloadIdentityPools/github/providers/github-provider` (condição repo == `BadWolf1509/v4-ads-mcp`) |
| Artifact Registry | `southamerica-east1-docker.pkg.dev/v4-ads-mcp/v4-ads-mcp/app` |
| Cloud Run service | `v4-ads-mcp` (allow-unauth, min0/max10, 512Mi, entrypoint buildpack = `web`) |
| Cloud Run Jobs | `v4-ads-mcp-migrate`, `v4-ads-mcp-resync` (**F66: quebrados** — buildpack não roda o process do Procfile) |
| Scheduler | `v4-ads-mcp-resync-daily` (0 6 * * *) |
| DB | mesmo Supabase (ref `laiqtoisehgkwfxaezjl`, session pooler `aws-1-sa-east-1.pooler.supabase.com:5432`, **senha resetada** — está no BTW "Password") |
| GitHub secrets (repo) | `GCP_PROJECT_ID=v4-ads-mcp`, `GCP_REGION=southamerica-east1`, `GCP_DEPLOY_SA=…deploy@…`, `GCP_WIF_PROVIDER=…` |

**13 secrets** no Secret Manager (owner lê): database-url, aes-master-key, session-signing-key, google-oauth-client-id, google-oauth-client-secret, google-ads-developer-token, google-ads-login-customer-id, supabase-url/anon-key/service-key, meta-app-id, meta-app-secret, meta-system-user-token.

**Meta:** SU único `v4-ads-mcp-integracao` (`61590110716028`), app **V4 Ads MCP** (`1522411803012799`), BM V4 Lima Soares (`619664032237208`). Token all-targets = secret "Meta" `7ffe144d` no BTW (⚠️ `/me` retorna **ASIDs** diferentes por app — não confundir com SUs distintos).

## Runbook de cutover (pros outros 3 gestores)

Nas máquinas deles, `~/.claude.json` → `mcpServers.v4-ads`:
1. `url`: `…jf26mmrgqa-rj.a.run.app/mcp` → `https://v4-ads-mcp-299432068772.southamerica-east1.run.app/mcp` (o **Bearer não muda**).
2. Abrir `…/admin` no navegador → **login Google** (reconecta o OAuth — chaves regeneradas).
3. Reiniciar Claude Code/Cursor.

## Pendências (ver CLAUDE.md §Pendente operacional)

1. Cutover dos outros 3 gestores (runbook acima).
2. **F66 — job `migrate`/`resync`**: o buildpack image roda `web` mesmo com `--command`/`--args`; o `deploy.yml` step "Run database migrations" **falha no próximo push**. Investigar o launcher CNB certo (`/cnb/process/<type>`?) ou remover o step (schema já existe no DB compartilhado).
3. **F67 — custom domain** `mcpv4.fluxocerto.dev.br` via Load Balancer (região não permite domain mapping; domínio já verificado no Search Console).
4. **ML Antiguidades + Mestre da Obra - Pinda** somem no token all-targets — re-atribuir o SU no BM se ainda forem clientes.
5. Onda 5 (F65) · decomissionar `v4-ads-mcp-prod` · Anderson 1 login · **revogar token BTW** do Wellington.

## Findings desta sessão

- **F64** — Meta `/me/adaccounts` é token+app-scoped; token de produção com **granular targets fixos** perdia contas novas. Fix: token all-targets (feito na migração).
- **F65** — `resync_meta` nunca chama `mark_inactive_except` → cache Meta acumula órfãs (Onda 5).
- **F66** — Cloud Run Job com buildpack image ignora `--command`/`--args` e roda o process `web` do Procfile; process não-web (`migrate`/`resync`) não é invocável trivialmente.
- **F67** — `southamerica-east1` retorna `501 UNIMPLEMENTED` em `run domain-mappings create` (custom domain exige Load Balancer).

Diagnóstico F64/F65 detalhado + o spec/plano da migração: [`specs/2026-06-30-gcp-project-migration-design.md`](../superpowers/specs/2026-06-30-gcp-project-migration-design.md) · [`plans/2026-06-30-gcp-project-migration.md`](../superpowers/plans/2026-06-30-gcp-project-migration.md).
