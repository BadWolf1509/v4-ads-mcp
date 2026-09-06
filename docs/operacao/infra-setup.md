# Infra setup — one-time manual steps

This document records the cloud-console actions performed once to bootstrap the project. Re-doing them is only necessary in disaster recovery or to provision a new environment.

---

## ⚠️ ESTADO ATUAL (autoritativo) — projeto novo pós-migração, atualizado 2026-07-23

> **A seção "GCP project" mais abaixo descreve o projeto ANTIGO `v4-ads-mcp-prod` (a decomissionar) — é histórico. Num DR real, siga ESTA seção.** A migração 2026-06-30 lift-and-shift criou um projeto novo com Wellington como owner (o antigo estava sem owner humano — motivo da migração). Detalhe: [`session-2026-06-30-handoff.md`](session-2026-06-30-handoff.md).

- **Projeto GCP:** `v4-ads-mcp` (project number **`299432068772`**), **Wellington owner**, billing própria. Região `southamerica-east1`.
- **URL do serviço:** `https://v4-ads-mcp-299432068772.southamerica-east1.run.app` (`PUBLIC_BASE_URL` no `deploy.yml`; OAuth redirect_uri usa `request.url_for`, não deriva daqui — F68). Revisão corrente em 2026-07-23: `v4-ads-mcp-00028-lvc`, 100% do tráfego.
- **Secret Manager (13 secrets):** `database-url`, `aes-master-key`, `session-signing-key`, `google-oauth-client-id`, `google-oauth-client-secret`, `google-ads-developer-token`, `google-ads-login-customer-id`, `supabase-url`, `supabase-anon-key`, `supabase-service-key`, `meta-app-id`, `meta-app-secret`, `meta-system-user-token`. A `aes-master-key`/`session-signing-key` foram **regeneradas** na migração (→ gestores reconectam Google; token cifrado com chave antiga cai na mensagem amigável F70).
- **Service accounts:** `v4-ads-mcp-runtime` (identidade do Cloud Run + jobs; tem `roles/storage.objectCreator` no bucket de backup), `github-deployer` (deploy via WIF), `v4-ads-mcp-scheduler` (invoca os jobs via Scheduler, least-privilege `run.invoker`).
- **Cloud Run Jobs** (todos com process CNB `/cnb/process/<type>` — F66; criar/atualizar com arg iniciando em `/` **em PowerShell**, Git Bash mangla o path):
  - `v4-ads-mcp-migrate` (`/cnb/process/migrate`) — roda no deploy.
  - `v4-ads-mcp-resync` (`/cnb/process/resync`) — Google + Meta accounts + purge diário.
  - `v4-ads-mcp-backup` (`/cnb/process/backup`) — dump csv.gz por tabela → GCS. **Precisa do MESMO secret set do resync** (não só `DATABASE_URL`): `get_settings()` valida o Settings inteiro na subida, então o job monta `SESSION_SIGNING_KEY`/`AES_MASTER_KEY`/`GOOGLE_OAUTH_*`/`GOOGLE_ADS_*` também (as fields Meta têm default `""`). Num DR, recriar o job com `--set-secrets` completo. **F95 (2026-08-15):** `SUPABASE_URL`/`ANON_KEY`/`SERVICE_KEY` saíram do `--set-secrets` do serviço e de `Settings`. Os **jobs** foram criados à mão e ainda os montam — inofensivo (`extra="ignore"`), mas ao recriar qualquer job, não os reponha. Os 3 secrets seguem existindo no Secret Manager; apagá-los é decisão à parte.
- **Cloud Scheduler:** `v4-ads-mcp-resync-daily` (`0 6 * * *` BRT) + `v4-ads-mcp-backup-weekly` (`0 5 * * 0` BRT, domingo). Ambos via SA `v4-ads-mcp-scheduler`.
- **Backup / DR:** bucket `gs://v4-ads-mcp-backups` (southamerica-east1, UBLA, **lifecycle delete > 90d**). Runbook completo de restore: [`backup-restore-runbook.md`](backup-restore-runbook.md). **O `audit_log` NÃO é purgado** (compliance); `pending_confirmations` (>7d) e `rate_counters`/`meta_rate_counters` (>90d) são purgados no resync diário ([`src/jobs/purge.py`](../../src/jobs/purge.py)).
- **Observabilidade / alerting** (Monitoring, criado 2026-07-04; validado 2026-07-23): canal e-mail `wellington.ribeiro@v4company.com`; uptime check HTTPS `/health?deep=1` (contentMatcher `"db":"ok"`, período 300s, timeout 10s, `STATIC_IP_CHECKERS`) + policy que exige falha sustentada; policy de **Cloud Run Job failed** (resync/migrate/backup); policy log-based do serviço `severity>=ERROR` (ID `6765708543993578761`, rate-limit 1/h, auto-close 24h). “No severity” no e-mail é severidade não configurada na policy, não ausência de severity no log. O deep health usa `run_with_reconnect` + deadline interno 5s desde F77; `max_inactive_connection_lifetime=120` sozinho não é pre-ping. Recriar policies via REST Monitoring API com `gcloud auth print-access-token` (o componente `gcloud alpha monitoring` não está instalado local).
- **CI/Deploy:** deploy gated pelo CI (`ci.yml` job `test` → job `deploy` `needs: test`). **Lockfile `requirements.txt`** pinado (uv pip compile do pyproject) instalado pelo buildpack CNB e pelo CI + `pip-audit` non-blocking. Smoke sempre valida health + `/mcp` 401; o smoke MCP autenticado é fail-well e está **dormente** porque o gestor/bearer smoke foi removido (F58 operacional). Re-armar exige recriar o gestor smoke sem grants e atualizar o secret.
- **GitHub repo secrets:** `GCP_WIF_PROVIDER`, `GCP_DEPLOY_SA`, `GCP_PROJECT_ID`, `GCP_REGION`; `SMOKE_MCP_BEARER` pode existir, mas está operacionalmente dormente até recriar o gestor smoke.
- **Alerta de conta Google sem grant (Task 7, 2026-09-05):** o job `v4-ads-mcp-resync` emite `log.warning("google_accounts_sem_grant", total=N, customer_ids=[...])` quando a fila `sem_delegacao` (`google_ads_accounts.list_queues`) não está vazia — conta ativa no MCC sem NENHUM gestor com grant vivo. ✅ **Métrica e policy CRIADAS em 2026-09-05** — métrica `logging.googleapis.com/user/google_accounts_sem_grant_total`, policy `alertPolicies/13901405017880842242` (*"Google Ads: conta sem grant apos resync"*), `enabled: true`, apontando o canal de e-mail `15226380074599878362` (Wellington). O projeto passou de 3 para 4 policies. Runbook na seção *"Runbook: alerta de conta Google sem grant"* abaixo — **corrigido em 05/09 depois de a execução real recusá-lo duas vezes**; ver a nota 🔴 lá.

---

## Runbook: alerta de conta Google sem grant (Task 7)

> Contexto: conta nova que entra no MCC sem gestor delegado hoje não avisa ninguém — a `Hust App` ficou dias assim e só foi achada por acaso, olhando o seletor de contas do Google. O job diário (`src/jobs/account_resync.py`, `avisar_contas_sem_grant`) agora **detecta** isso e **loga** — `log.warning`, não `error`: o job fez o trabalho certo, a anomalia é do inventário, não da execução, e marcar como erro faria a policy de "Cloud Run Job failed" disparar e mascarar falha real. E só loga quando há o que avisar — hoje, em produção, `sem_delegacao` está **vazia** (as 26 contas ativas têm grant), então o caminho normal é silêncio; alarme que aparece sempre ensina a ser ignorado.
>
> ✅ **EXECUTADO em 2026-09-05 — a métrica e a policy existem.** O texto abaixo fica como registro do procedimento (e para recriar em outro projeto), já corrigido pelos dois erros que só a execução revelou. Aviso original: *esta task entrega o sinal e este runbook — não entrega o alerta.* Criar a métrica log-based e a policy no Cloud Monitoring é ação humana, fora do repositório, e foi decidido assim de propósito (não dá pra fazer isso passar no CI). **Enquanto os dois comandos abaixo não forem executados, o evento `google_accounts_sem_grant` só existe no log do Cloud Run — nenhum e-mail sai, pra ninguém, mesmo com uma conta sem grant há dias.** Pendência de execução: ver `docs/operacao/estado-atual.md` (Task 8 deste sprint abre o item formal).
>
> **Pré-requisito silencioso, já corrigido nesta task:** até este commit, `python -m src.jobs.account_resync` nunca chamava `configure_logging()` — só `src/app.py` (o serviço web) chamava. Sem isso o job loga em texto puro (o renderer default do structlog não-configurado — confirmado lendo logs reais de produção, ex. `2026-09-05 09:00:24 [info] resync_complete ...`), e o filtro `jsonPayload.event=...` abaixo NUNCA acharia nada — a métrica ficaria criada e sempre vazia, calada, sem ninguém notar. Se um dia este alerta parar de disparar quando deveria, o primeiro lugar a olhar é se o job voltou a logar texto puro (`gcloud logging read` sem `jsonPayload`, só `textPayload`).
>
> Comandos abaixo em **PowerShell**, com `curl.exe` **explícito** — `curl` sozinho é alias de `Invoke-WebRequest` no PowerShell 5.1 (confirmado nesta máquina: `Get-Command curl` resolve pro alias), que não entende `-H`/`-d` do jeito que estes comandos esperam. Rode como o Wellington (`gcloud auth print-access-token`, já autenticado como owner do projeto `v4-ads-mcp`).

### (a) Criar a métrica log-based

Conta a distribuição de `jsonPayload.total` toda vez que o evento aparece — não só "aconteceu", mas "quantas contas".

> ⚠️ **Não passe o JSON direto como `-d $body`.** Confirmado nesta máquina (PowerShell 5.1): ao montar a linha de comando pro processo nativo, o PowerShell **engole as aspas internas** de qualquer argumento que contenha `"` — sobra `{name: test, filter: resource.type=cloud_run_job` sem nenhuma aspa, e o `AND` vira um argv separado (quebra no espaço que a aspa deveria ter protegido). O sintoma no Google é `400 INVALID_ARGUMENT` / `Unexpected token`. O fix comprovado é gravar o JSON num arquivo e usar `curl.exe -d "@arquivo"` — variável nenhuma cruza a linha de comando. Use `-Encoding ascii` (os JSONs abaixo são texto puro, sem acento) porque `-Encoding utf8` do `Set-Content` grava BOM, e um BOM na frente de `{` é `400` de novo, agora por JSON inválido de verdade (RFC 8259 proíbe BOM).

```powershell
$body = @'
{
  "name": "google_accounts_sem_grant_total",
  "description": "Quantas contas Google Ads ativas estao sem nenhum gestor com grant vivo (evento google_accounts_sem_grant do job v4-ads-mcp-resync, src/jobs/account_resync.py:avisar_contas_sem_grant).",
  "filter": "resource.type=\"cloud_run_job\" AND resource.labels.job_name=\"v4-ads-mcp-resync\" AND jsonPayload.event=\"google_accounts_sem_grant\"",
  "metricDescriptor": {
    "metricKind": "DELTA",
    "valueType": "DISTRIBUTION",
    "unit": "1",
    "displayName": "Contas Google sem grant (resync)"
  },
  "valueExtractor": "EXTRACT(jsonPayload.total)",
  "bucketOptions": {
    "linearBuckets": { "numFiniteBuckets": 64, "width": 1, "offset": 0 }
  }
}
'@
$arquivo = "$env:TEMP\google_accounts_sem_grant_metric.json"
$body | Set-Content -Encoding ascii -Path $arquivo
$token = gcloud auth print-access-token
curl.exe -s -X POST -H "Authorization: Bearer $token" -H "Content-Type: application/json" "https://logging.googleapis.com/v2/projects/v4-ads-mcp/metrics" -d "@$arquivo"
```

Verificar que foi criada:

```powershell
$token = gcloud auth print-access-token
curl.exe -s -H "Authorization: Bearer $token" "https://logging.googleapis.com/v2/projects/v4-ads-mcp/metrics/google_accounts_sem_grant_total"
```

### (b) Criar a policy, no canal de e-mail que já existe

Canal e-mail existente (Wellington, criado 2026-07-04 — **não crie outro**): `projects/v4-ads-mcp/notificationChannels/15226380074599878362`. Confirmar antes de usar (o ID não muda, mas é barato conferir):

```powershell
$token = gcloud auth print-access-token
curl.exe -s -H "Authorization: Bearer $token" "https://monitoring.googleapis.com/v3/projects/v4-ads-mcp/notificationChannels"
```

Criar a policy (referencia a métrica do passo (a) — rode DEPOIS dela):

```powershell
$body = @'
{
  "displayName": "Google Ads: conta sem grant apos resync",
  "documentation": {
    "content": "Uma ou mais contas Google Ads ativas no MCC nao tem NENHUM gestor com grant vivo (fila sem_delegacao). Delegue em /admin/access (ou manager_account_access.grant) assim que possivel -- e o mesmo buraco que deixou a Hust App dias sem ninguem responsavel. Ver docs/operacao/infra-setup.md, secao Runbook: alerta de conta Google sem grant.",
    "mimeType": "text/markdown"
  },
  "combiner": "OR",
  "conditions": [
    {
      "displayName": "google_accounts_sem_grant_total > 0",
      "conditionThreshold": {
        "filter": "metric.type=\"logging.googleapis.com/user/google_accounts_sem_grant_total\" AND resource.type=\"cloud_run_job\"",
        "comparison": "COMPARISON_GT",
        "thresholdValue": 0,
        "duration": "0s",
        "trigger": { "count": 1 },
        "aggregations": [
          { "alignmentPeriod": "300s", "perSeriesAligner": "ALIGN_PERCENTILE_99" }
        ]
      }
    }
  ],
  "notificationChannels": [
    "projects/v4-ads-mcp/notificationChannels/15226380074599878362"
  ],
  "alertStrategy": {
    "autoClose": "86400s"
  }
}
'@
$arquivo = "$env:TEMP\google_accounts_sem_grant_policy.json"
$body | Set-Content -Encoding ascii -Path $arquivo
$token = gcloud auth print-access-token
curl.exe -s -X POST -H "Authorization: Bearer $token" -H "Content-Type: application/json" "https://monitoring.googleapis.com/v3/projects/v4-ads-mcp/alertPolicies" -d "@$arquivo"
```

Verificar que foi criada (a resposta do POST já traz o `name` gerado, mas dá pra reconferir por listagem):

```powershell
$token = gcloud auth print-access-token
(curl.exe -s -H "Authorization: Bearer $token" "https://monitoring.googleapis.com/v3/projects/v4-ads-mcp/alertPolicies" | ConvertFrom-Json).alertPolicies | Where-Object { $_.displayName -like "*sem grant*" }
```

### Testar de ponta a ponta

Hoje `sem_delegacao` está vazia (26/26 contas ativas com grant) — rodar o job agora não gera o evento, e isso é o comportamento CORRETO, não uma falha do teste. Pra validar o caminho de alerta sem esperar uma conta órfã de verdade aparecer: revogue o grant de UMA conta de teste (`/admin/access`, ou `manager_account_access.revoke` direto), rode o job sob demanda, confirme o `jsonPayload.event=google_accounts_sem_grant` no log e o e-mail chegando, e **reconceda o grant em seguida** (a revogação manual não é o estado desejado da conta).

```powershell
gcloud run jobs execute v4-ads-mcp-resync --project=v4-ads-mcp --region=southamerica-east1 --wait
```

```powershell
$body = @'
{
  "resourceNames": ["projects/v4-ads-mcp"],
  "filter": "resource.type=\"cloud_run_job\" AND resource.labels.job_name=\"v4-ads-mcp-resync\" AND jsonPayload.event=\"google_accounts_sem_grant\"",
  "orderBy": "timestamp desc",
  "pageSize": 5
}
'@

🔴 **DOIS ERROS DESTE RUNBOOK QUE SÓ A EXECUÇÃO REVELOU (corrigidos acima em 2026-09-05).**
Ele foi escrito para ser executado por um humano e nunca tinha sido rodado — as verificações
da task que o escreveu foram chamadas de leitura e POSTs com token inválido, que falham na
**autenticação antes da validação do corpo**. Os dois só aparecem com token bom:

1. **`alertStrategy.notificationRateLimit` foi REMOVIDO.** A API recusa:
   *"only log-based alert policies may specify a notification rate limit"* — ele vale para
   policy do tipo `conditionMatchedLog`, não para limiar de métrica. Custo de perdê-lo é
   baixo: o job roda **uma vez por dia**, então o teto de 1/hora era quase inócuo, e o
   `autoClose: 86400s` continua.
2. **`ALIGN_COUNT` virou `ALIGN_PERCENTILE_99`.** A API recusa:
   *"The aligner cannot be applied to metrics with kind DELTA and value type DISTRIBUTION"*.
   `ALIGN_MAX`, `ALIGN_MEAN` e `ALIGN_SUM` são recusados pelo mesmo motivo — os alinhadores
   que produzem escalar a partir de distribuição são os de percentil. Como a função só emite
   o evento com a fila **não vazia**, `total` é sempre ≥ 1 quando ele aparece, então
   `PERCENTILE_99 > 0` dispara em qualquer ocorrência. ⚠️ **A revisão final tinha marcado
   exatamente essa incerteza** (*"plausível e é padrão comum, mas não tenho como confirmar
   sem criar a policy de verdade"*) — e estava certa em não afirmar.

**Nota sobre `thresholdValue: 0`:** a resposta da API **omite** o campo, porque em proto3
zero é o default e não é serializado. Não é bug: `COMPARISON_GT` com threshold ausente é
`> 0`, que é o que se quer.

$arquivo = "$env:TEMP\google_accounts_sem_grant_query.json"
$body | Set-Content -Encoding ascii -Path $arquivo
$token = gcloud auth print-access-token
curl.exe -s -H "Authorization: Bearer $token" -H "Content-Type: application/json" "https://logging.googleapis.com/v2/entries:list" -d "@$arquivo"
```

---

## GitHub
- [x] Repo: `BadWolf1509/v4-ads-mcp` (private)
- [x] Branch protection on `main`: ha **required status check `test`** — o push de 2026-08-19 recebeu `remote: - Required status check "test" is expected.`, que o GitHub so emite quando a branch esta protegida. O fluxo e solo-dev com **admin bypass** (CLAUDE.md, "Git workflow"), entao o push passa mesmo com o check pendente; a protecao vale pra quem nao for admin. O checkbox ficou desmarcado por ~1 ano depois de a protecao existir.

## GCP project (HISTÓRICO — projeto antigo `v4-ads-mcp-prod`, a decomissionar; use a seção "ESTADO ATUAL" acima)
- [x] Project: `v4-ads-mcp-prod` (project number `518798891402`, billing `01286F-7A67A7-226F9E`)
- [x] APIs enabled: Cloud Run, Cloud Build, Artifact Registry, Secret Manager, Cloud Logging, Cloud Scheduler, IAM Credentials, STS, Google Ads
- [x] Service accounts: `v4-ads-mcp-runtime` (Cloud Run identity), `github-deployer` (CI deploys via Workload Identity Federation)
- [x] Workload Identity Federation pool `github-pool` + OIDC provider `github-provider` (restricted to repo `BadWolf1509/v4-ads-mcp`)
- [x] Secret Manager: 10 secrets created. Real values for `session-signing-key`, `aes-master-key`, `google-ads-developer-token`, `google-ads-login-customer-id`, `supabase-url`, `database-url`. Placeholders for OAuth + Supabase keys (Phase 1 fills in).
- [x] GitHub repo secrets: `GCP_WIF_PROVIDER`, `GCP_DEPLOY_SA`, `GCP_PROJECT_ID`, `GCP_REGION`
- [x] Cloud Run Job `v4-ads-mcp-resync` created (entry: `python -m src.jobs.account_resync`)
- [x] Cloud Scheduler `v4-ads-mcp-resync-daily` (cron `0 7 * * *` UTC = 04:00 BRT)

## Supabase project
- [x] Project ref: `laiqtoisehgkwfxaezjl` (region São Paulo)
- [x] DB password recorded (1Password under "v4-ads-mcp / supabase")
- [x] Connection string in Secret Manager: `database-url` (uses Shared Pooler `aws-1-sa-east-1.pooler.supabase.com:5432`, IPv4)

## Google Ads
- [x] Developer token: `<set in Secret Manager — see 1Password "v4-ads-mcp / google-ads-dev-token">` (Test Account mode at MVP; submit Standard Access during Phase 1)
- [x] V4 MCC ID: `6436352492` (was previously misidentified as `7862230676` which is actually a child account "Mestre da Obra - João Pessoa")
- [x] OAuth Client created in GCP Console with redirect URI `https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/oauth/google/callback`

## Phase sign-offs

### Phase 0 — Foundation (2026-05-03)
- Repo + tooling, Cloud Run service, /health and /mcp (no tools), CI/CD pipeline, Supabase migrations applied. All acceptance criteria met.

### Phase 1a — Auth backend + first MCP tool (2026-05-04)
- AES-GCM encryption for refresh tokens, MCP Bearer sessions, OAuth state HMAC, 6 DB repositories, Google Ads SDK client, MCP middleware, tool registry, `list_my_accounts` tool, OAuth Google flow, admin CLI, account_resync job + Cloud Scheduler.
- E2E verified: wellinton.ribeiro@v4company.com bootstrapped → OAuth flow completed → 23 V4 client accounts populated via resync → granted access → MCP session created → Codex CLI configured + connected → `list_my_accounts` returned all 23 accounts → audit_log captured 2 calls (6ms + 7ms duration each).
- Known limitations carried into Phase 1b:
  - Userinfo endpoint failed during OAuth (scope `adwords` alone doesn't include email); google_email is currently "unknown". Add `email` scope in Phase 1b.
  - Developer token still in Test mode (15k ops/day quota). Submit for Standard Access when quota becomes constraining.

### Phase 2 — Read tools (2026-05-04)
- 16 curated read tools (visao geral, performance, tactical, client report) + 3 GAQL utilities (run_gaql, validate_gaql, list_gaql_resources) shipped.
- Total tools registered: 20 (incl. list_my_accounts from Phase 1a).
- Rate limit module enforces 15k ops/day per developer token (Basic Access). Warning at 80%, block at 100%.
- Audit log captures sensitive reads only (recommendations, run_gaql, conversion_actions).
- jsonschema input validation in MCP call_tool (defense in depth).
- 114 tests passing (unit + integration with testcontainers Postgres + mocked Google Ads SDK).
- E2E verified via Codex on conta `5894449831` (Mestre da Obra - Cotia):
  - `get_account_overview`: returned 30-day KPIs + previous-period comparison (impressions 8590 vs 8086, +6.2%; conversions 237 vs 197, +20.3%; CPA dropped from R$ 10.76 to R$ 10.04).
  - `get_budget_pacing`: returned 1 active campaign with daily_budget R$ 100, MTD spend R$ 213.92, projected R$ 1657.88 (53.5% of monthly budget).
  - `get_campaign_performance` (top 5, 7-day): returned the 1 active campaign with R$ 581.75 spend, 151 clicks, CTR 7.57%.
  - `get_search_terms_report` (14-day): returned 64 search terms without conversions totaling R$ 271.81, candidates for negative keywords identified by Codex.
  - `run_gaql` with custom GAQL: returned 1 row with descriptive_name "Mestre da Obra - Cotia", currency BRL.
- Codex performed intelligent analysis on top of the raw tool outputs (% deltas, negative keyword candidates, projection vs budget) — proving the gestor workflow value end-to-end.

### Phase 3a — Core mutations (2026-05-04 — code complete, E2E deferred to operations)
- 10 mutation tools shipped: 3 campaign (status/budget/bidding), 2 ad_group (status/bid), 2 keyword (status/bid), 1 negative_keywords, 2 recommendations.
- Plus `apply_change` utility tool to consume confirmation tokens.
- Total tools registered: 31 (20 from Phase 2 + 1 apply_change + 10 mutations).
- Governance: blast_radius classifier (auto vs confirm per spec §7.1), dry_run with 8-char alphanumeric tokens + 10-min TTL + session-scoped, audit_log captures every mutation with google_request_id.
- 162 tests passing (unit + integration with testcontainers + mocked Google Ads SDK).
- E2E approach: deferred to operations (gestores) doing real work — synthetic test mutations risk altering live accounts. Validation channel = audit_log table + Google Ads UI Change History. Test prompts in `phase-1a-bootstrap.md` Phase 3a section remain available for ad-hoc validation if needed.
- First-touch monitoring plan: track audit_log for the first week of operations use; flag any failures (status='error') for investigation.

### Phase 1b — Web panel (2026-05-05)
- 5 gestor pages (login, dashboard, accounts, sessions, audit) + 4 admin pages (managers, accounts, access matrix, audit) shipped.
- Authentication: unified Google OAuth (deviation from spec §5.1 which prescribed Supabase Auth + separate Google OAuth) — single flow with scopes {openid, email, profile, adwords} restricted to @v4company.com.
- Panel session: signed cookie `v4_panel_session` (24h TTL, httpOnly, Secure, SameSite=Lax). HMAC-signed with session_signing_key.
- First-ever login auto-promoted to admin (bootstrap path).
- Templates: Jinja2 + V4 design tokens (no JS framework, no build step). HTMX via CDN for inline interactions (revoke session, toggle access).
- Brand assets: official V4 SVG logo (`logo_v4_puro_round.svg`, 667 bytes vector-pure) replacing initial placeholder. Renders in header of every page + login hero. Reserve `logo_v4_puro_round_transparente.svg` (585 bytes) kept for future dark-mode/footer use.
- 203 tests passing (unit + integration with testcontainers).
- Existing CLI admin remains available as escape hatch.
- E2E verified by user on 2026-05-05 via 5 screenshots covering all gestor + admin pages in production:
  - Login flow worked end-to-end. Re-OAuth populated google_email = wellinton.ribeiro@v4company.com, fixing the "unknown" carryover from Phase 1a (which had only `adwords` scope).
  - Dashboard `/`: greeting "Bem-vindo, Wellinton Ribeiro!", ADMIN badge, "23 contas acessíveis", "1 sessão MCP ativa", Google connection card showing wellinton.ribeiro@v4company.com (Conectado em 05/05/2026 00:51).
  - `/accounts`: 2 OAuth connections rendered (new with-email ATIVA from 05/05 + legacy "unknown" ATIVA from 04/05) + table of 23 Google Ads accounts (CIDs 3237459217 → 9985020293, including "3 Lagoas Locações", "DR DÉRICK VINHAS", "Mestre da Obra - Cotia" etc.).
  - `/sessions`: 1 active "Claude Desktop" session listed (criada 04/05/2026 04:56, último uso 04/05/2026 14:14, expira 02/08/2026). Revoke button rendered.
  - `/audit`: 2 events captured — both `list_my_accounts` READ ops, status OK, target_count 23, durations 7ms + 6ms.
  - `/admin/managers`: 1 admin row (Wellinton Ribeiro, badge ADMIN, ATIVO, criado 04/05/2026, último acesso 04/05 14:14, marcado "(você)").
- Phase 1a known-limitation #1 (google_email="unknown" because OAuth used only `adwords` scope) is now resolved: new connections via panel use `{openid, email, profile, adwords}` and the email column populates correctly. Legacy "unknown" rows from Phase 1a remain visible until those connections are revoked + reauthorized — cosmetic only.
- Logo renders correctly across all pages including the login hero.

### Phase FE Redesign v2 (2026-05-05) — code-complete in production
- 56 commits across 6 phases shipping a Hybrid Editorial+Operational identity per `docs/superpowers/specs/2026-05-05-frontend-redesign-v2-design.md` and `docs/superpowers/plans/2026-05-05-frontend-redesign-v2-plan.md`.
- Design system v2: Tailwind CDN integrated with V4 token bridge (`bg-v4-red`, `text-display`, `font-mono`, `transition-v4-out`); 22 components in `_components.html` (refined: button/card/badge/alert/inputs/form_group; new: sparkline, pagination, code_block, empty_state, toast, skeleton, confirm_dialog, modal, breadcrumb, dropdown, tooltip, expandable_row, sticky/compact tables); ~520 lines added to CSS; new `v4-motion.css`; 5 JS helpers in `_base.html` (toggleDrawer, showToast, openConfirm, v4DropdownToggle, v4ToggleRow).
- Auth/Q8: invite-only allowlist enforced. Migration `002_managers_status.sql` adds `status` (`invited`/`active`/`inactive`) + `invited_by` + `invited_at`. OAuth callback decision tree (pure `handle_callback_decision` + 8 unit tests). `BOOTSTRAP_ADMIN_EMAILS` env var (Cloud Run revision `00058+`). `/access-denied` page with 3 reason variants.
- 15 pages redesigned/created (9 redesigned + 6 new):
  - **Editorial:** `/login` (display 56 hero "V4 Ads MCP. IA + Google Ads."), `/access-denied`, `/help`.
  - **Hybrid hero:** `/` dashboard (Editorial hero + Operational stats + admin extras card), `/admin` (visão geral consolidada).
  - **Operational tables:** `/audit` (sticky filters + auto-submit + day grouping + expand row + CSV export), `/audit/{id}` detail, `/admin/audit` (+ status filter + gestor filter), `/admin/access` matrix v2 (search + bulk grant + copy access modals), `/admin/access/by-manager` + `/admin/access/{id}` (mobile per-gestor paradigm).
  - **List + form:** `/accounts`, `/sessions` (flow change: POST → 302 → `/sessions/{id}?token_flash=true`), `/sessions/{id}` permanent detail, `/admin/managers` (search + dropdown ⋯ + filters), `/admin/accounts` (search + MCC filter), `/admin/invites` (Q8 list + form).
- Sub-nav admin (Visão geral · Managers · Convites · Contas · Acessos · Audit global) with live-counter badge for pending invites.
- Mobile-aware: hamburger drawer below 768px; tables >3 cols become card list; access matrix has dedicated per-gestor route.
- Backend touchpoints: 1 migration, ~10 new repository functions (managers invite lifecycle, audit_log get_by_id/summary_stats/export_csv_rows, mcp_sessions.get_by_id, manager_account_access.bulk_grant/copy_access), 12+ new routes, allowlist OAuth flow.
- Tests: 101 unit + 8 OAuth allowlist + integration test updates (sessions flow + admin audit header). All CI green.
- E2E partially verified during deploy: smoke screenshot of `/admin/invites` showing form + sub-nav badge + Lucas Soares pending invite. Final visual regression sweep across all 15 pages deferred to operations during real onboarding (`docs/operacao/screenshots/after/` directory awaits captures).
- Out of scope (deferred to follow-up sub-projects per the spec): multi-tenancy backend (`unidades` table + 3-tier RBAC), multi-MCC OAuth, single→multi migration, dark mode opt-in.
