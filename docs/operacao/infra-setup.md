# Infra setup — one-time manual steps

This document records the cloud-console actions performed once to bootstrap the project. Re-doing them is only necessary in disaster recovery or to provision a new environment.

---

## ⚠️ ESTADO ATUAL (autoritativo) — projeto `fluxo-certo-ads`, desde 25/11/2026

> Migração do projeto `v4-ads-mcp` (dentro da organização `v4company.com`, faturamento desligado em
> 24/11) para um projeto do Gmail. Spec: [`2026-11-25-migracao-projeto-gmail-design.md`](../superpowers/specs/2026-11-25-migracao-projeto-gmail-design.md).
> Recriado pelo script da seção seguinte; **num DR, rode o script** e siga esta seção.

- **Projeto GCP:** `fluxo-certo-ads` (número **`505452482961`**), sem organização. Owner, faturamento
  (conta de faturamento do próprio Gmail) e conta ativa do `gcloud`: `wellington.ribeiro.eng@gmail.com`.
- **URL do serviço:** `https://v4-ads-mcp-505452482961.southamerica-east1.run.app` = `vars.PUBLIC_BASE_URL`
  do GitHub e redirect do cliente OAuth (`/oauth/google/callback`). O endereço alternativo
  `v4-ads-mcp-nbuw3bjhpq-rj.a.run.app` responde, mas o login por ele falha (redirect não cadastrado).
- **Secret Manager (9):** `database-url` (Supabase, Session Pooler `:5432`), `session-signing-key` e
  `aes-master-key` (**novas** em 25/11 — tokens cifrados com a chave antiga caem no F70),
  `google-oauth-client-id`/`-secret` (cliente web do projeto novo), `google-ads-login-customer-id`
  (**provisório `7862230676`**, a MDO, acesso direto), `meta-app-id`/`-secret`/`meta-system-user-token`
  (**`" "`** = Meta indisponível; o `Settings` tira espaço das pontas). Valores entram por arquivo (F47).
- **Service accounts, WIF, jobs, bucket:** iguais ao inventário do projeto antigo, conferidos recurso a
  recurso depois do `--apply`: `v4-ads-mcp-runtime`, `v4-ads-mcp-deploy`, `v4-ads-mcp-scheduler`; pool
  `github`/provider `github-provider` restrito a `BadWolf1509/v4-ads-mcp`; jobs `migrate`/`resync`/`backup`
  com `--command=/cnb/process/<tipo>`; bucket `gs://fluxo-certo-ads-backups` (UBLA, lifecycle 90d).
- **Cloud Scheduler:** `v4-ads-mcp-resync-daily` e `v4-ads-mcp-backup-weekly` **PAUSADOS** (gate da
  reconciliação no [`estado-atual.md`](estado-atual.md)). Despausar: `gcloud scheduler jobs resume <nome>
  --location=southamerica-east1 --project=fluxo-certo-ads`.
- **Google Ads API:** nível **Básico** do projeto (Cloud Console → Google Ads API → Níveis de acesso,
  `console.cloud.google.com/google/ads-apis/overview?project=fluxo-certo-ads`). Teste → Exploração →
  Básico em 25/11; o Básico foi negado uma vez por falta de verificação de marca e aprovado depois.
- **OAuth / marca:** tela de consentimento Externa; marca **não verificada** (Search Console do
  `fluxocerto.dev.br` ainda sem o Gmail). Em Teste, refresh token expira em 7 dias.
- **Observabilidade (criada em 25/11, cópia exata do projeto antigo exportada pela REST API):** canal
  e-mail `notificationChannels/10110565655084152842` (Gmail); uptime check
  `v4-ads-mcp-health-deep-9XtDnsW6NAc` (`/health?deep=1`, `"db":"ok"`, 300 s); métricas log-based
  `google_accounts_sem_grant_total` e `meta_avisos_de_quota`; 5 policies ligadas — job falhou
  (`6773825326335248563`), conta sem grant (`16467679565630814675`), avisos Meta de quota
  (`12935802224862145880`), `severity>=ERROR` do serviço (`15445270631082308889`) e uptime
  (`12935802224862142879`). O job falhou foi exercitado em 25/11 com uma execução forçada do backup
  sem bucket; a chegada do e-mail é conferência do Wellington.
- **Backup:** bucket `gs://fluxo-certo-ads-backups`, passado ao job por `BACKUP_BUCKET` (#286; sem ele o
  job falha fechado). Primeiro backup em 25/11 (13 tabelas, audit 12853); `v4-ads-mcp-backup-weekly`
  **ligado** desde 25/11.
- **GitHub:** secrets `GCP_PROJECT_ID=fluxo-certo-ads`, `GCP_REGION`, `GCP_WIF_PROVIDER`
  (`projects/505452482961/.../providers/github-provider`), `GCP_DEPLOY_SA`
  (`v4-ads-mcp-deploy@fluxo-certo-ads.iam.gserviceaccount.com`); vars `PUBLIC_BASE_URL` (obrigatória,
  barra o deploy se vazia) e `META_BUSINESS_ID` (ausente → aviso, reconciliação Meta no-op).

## Projeto anterior `v4-ads-mcp` (desligado em 24/11/2026) — referência

> Faturamento desligado em 24/11, 21:30 BRT; serviço 503; bucket e Secret Manager inacessíveis. Fica
> como inventário (foi a fonte do script) e pelos runbooks de alerta abaixo, que valem no projeto novo
> trocando `--project` e o e-mail do canal.

> **O projeto GCP ANTIGO (a decomissionar) é histórico e está em [`infra-setup-historico.md`](../_archive/setup/infra-setup-historico.md). Num DR real, siga ESTA seção.** A migração 2026-06-30 lift-and-shift criou um projeto novo com Wellington como owner (o antigo estava sem owner humano — motivo da migração). Detalhe: [`session-2026-06-30-handoff.md`](../_archive/handoffs/session-2026-06-30-handoff.md).

- **Projeto GCP:** `v4-ads-mcp` (project number **`299432068772`**), **Wellington owner**, billing própria. Região `southamerica-east1`.
- **URL do serviço:** `https://v4-ads-mcp-299432068772.southamerica-east1.run.app` (`PUBLIC_BASE_URL` no `deploy.yml`; OAuth redirect_uri usa `request.url_for`, não deriva daqui — F68). Revisão corrente em 2026-07-23: `v4-ads-mcp-00028-lvc`, 100% do tráfego.
- **Secret Manager (13 secrets):** `database-url`, `aes-master-key`, `session-signing-key`, `google-oauth-client-id`, `google-oauth-client-secret`, `google-ads-developer-token` (não montado desde 11/2026), `google-ads-login-customer-id`, `supabase-url`, `supabase-anon-key`, `supabase-service-key`, `meta-app-id`, `meta-app-secret`, `meta-system-user-token`. A `aes-master-key`/`session-signing-key` foram **regeneradas** na migração (→ gestores reconectam Google; token cifrado com chave antiga cai na mensagem amigável F70).
- **Service accounts:** `v4-ads-mcp-runtime` (identidade do Cloud Run + jobs; tem `roles/storage.objectCreator` no bucket de backup), `v4-ads-mcp-deploy` (deploy via WIF; o nome `github-deployer` que constava aqui estava errado — medido em 25/11), `v4-ads-mcp-scheduler` (invoca os jobs via Scheduler, least-privilege `run.invoker`).
- **Cloud Run Jobs** (todos com process CNB `/cnb/process/<type>` — F66; criar/atualizar com arg iniciando em `/` **em PowerShell**, Git Bash mangla o path):
  - `v4-ads-mcp-migrate` (`/cnb/process/migrate`) — roda no deploy.
  - `v4-ads-mcp-resync` (`/cnb/process/resync`) — Google + Meta accounts + purge diário.
  - `v4-ads-mcp-backup` (`/cnb/process/backup`) — dump csv.gz por tabela → GCS. **Precisa do MESMO secret set do resync** (não só `DATABASE_URL`): `get_settings()` valida o Settings inteiro na subida, então o job monta `SESSION_SIGNING_KEY`/`AES_MASTER_KEY`/`GOOGLE_OAUTH_*`/`GOOGLE_ADS_*` também (as fields Meta têm default `""`). Num DR, recriar o job com `--set-secrets` completo. **F95 (2026-08-15):** `SUPABASE_URL`/`ANON_KEY`/`SERVICE_KEY` saíram do `--set-secrets` do serviço e de `Settings`. Os **jobs** foram criados à mão e ainda os montam — inofensivo (`extra="ignore"`), mas ao recriar qualquer job, não os reponha. Os 3 secrets seguem existindo no Secret Manager; apagá-los é decisão à parte.
- **Cloud Scheduler:** `v4-ads-mcp-resync-daily` (`0 6 * * *` BRT) + `v4-ads-mcp-backup-weekly` (`0 5 * * 0` BRT, domingo). Ambos via SA `v4-ads-mcp-scheduler`.
- **Backup / DR:** bucket `gs://fluxo-certo-ads-backups` (`BACKUP_BUCKET` no `deploy.yml`; southamerica-east1, UBLA, **lifecycle delete > 90d**). Runbook completo de restore: [`backup-restore-runbook.md`](backup-restore-runbook.md). **O `audit_log` NÃO é purgado** (compliance); `pending_confirmations` (>7d) e `rate_counters`/`meta_rate_counters` (>90d) são purgados no resync diário ([`src/jobs/purge.py`](../../src/jobs/purge.py)).
- **Observabilidade / alerting** (Monitoring, criado 2026-07-04; validado 2026-07-23): canal e-mail `wellington.ribeiro@v4company.com`; uptime check HTTPS `/health?deep=1` (contentMatcher `"db":"ok"`, período 300s, timeout 10s, `STATIC_IP_CHECKERS`) + policy que exige falha sustentada; policy de **Cloud Run Job failed** (resync/migrate/backup); policy log-based do serviço `severity>=ERROR` (ID `6765708543993578761`, rate-limit 1/h, auto-close 24h). “No severity” no e-mail é severidade não configurada na policy, não ausência de severity no log. O deep health usa `run_with_reconnect` + deadline interno 5s desde F77; `max_inactive_connection_lifetime=120` sozinho não é pre-ping. Recriar policies via REST Monitoring API com `gcloud auth print-access-token` (o componente `gcloud alpha monitoring` não está instalado local).
- **CI/Deploy:** deploy gated pelo CI (`ci.yml` job `test` → job `deploy` `needs: test`). **Lockfile `requirements.txt`** pinado (uv pip compile do pyproject) instalado pelo buildpack CNB e pelo CI + `pip-audit` non-blocking. Smoke sempre valida health + `/mcp` 401; o smoke MCP autenticado é fail-well e está **dormente** porque o gestor/bearer smoke foi removido (F58 operacional). Re-armar exige recriar o gestor smoke sem grants e atualizar o secret.
- **GitHub repo secrets:** `GCP_WIF_PROVIDER`, `GCP_DEPLOY_SA`, `GCP_PROJECT_ID`, `GCP_REGION`; `SMOKE_MCP_BEARER` pode existir, mas está operacionalmente dormente até recriar o gestor smoke.
- **Alerta de conta Google sem grant (Task 7, 2026-09-05):** o job `v4-ads-mcp-resync` emite `log.warning("google_accounts_sem_grant", total=N, customer_ids=[...])` quando a fila `sem_delegacao` (`google_ads_accounts.list_queues`) não está vazia — conta ativa no MCC sem NENHUM gestor com grant vivo. ✅ **Métrica e policy CRIADAS em 2026-09-05** — métrica `logging.googleapis.com/user/google_accounts_sem_grant_total`, policy `alertPolicies/13901405017880842242` (*"Google Ads: conta sem grant apos resync"*), `enabled: true`, apontando o canal de e-mail `15226380074599878362` (Wellington). O projeto passou de 3 para 4 policies. Runbook na seção *"Runbook: alerta de conta Google sem grant"* abaixo — **corrigido em 05/09 depois de a execução real recusá-lo duas vezes**; ver a nota 🔴 lá.
- **Job bloqueado alerta (Task 5, 2026-10-30):** `src/jobs/account_resync.py` (Google + piggyback Meta) e `src/jobs/meta_resync.py` saem com **exit 1** quando uma reconciliação tem `blocked_reason` ou quando o piggyback Meta quebra — antes devolviam 0 e a policy *Cloud Run Job: execucao FALHOU* (a única que vê o job, keyed em `completed_execution_count{result=failed}`) nunca disparava. O exit 1 vem **depois** de upsert, audit e purge. O job de resync tem `maxRetries: 3`: o bloqueio é determinístico, então o retry o repete até 4 execuções no dia (4 linhas `status=error` no `audit_log`, um único e-mail), e a reconciliação é idempotente por dia (F157), então repetir não consome carência nem revoga duas vezes. Desde 11/11 (F207) a falha do purge também sai com exit 1, com linha `db_purge`/`error` no `audit_log`; e `init_pool` que falha emite `jsonPayload.event="job_init_pool_failed"` (ERROR, com `operation`/`platform`) antes de a execução falhar — o alerta log-based sobre esse evento **não foi criado** (decisão do Wellington, 11/11: fica com ele).
- **Alerta dos avisos Meta de quota (F194, 2026-09-27):** o serviço emite `meta_rate_limit_warning` (algum sinal de quota medido acima de 75%, com `acima_de_75`) e `meta_buc_nao_lido` (cabeçalho BUC ausente ou ilegível) em **WARNING** — a policy `severity>=ERROR` não os pega. ✅ **Criados em 2026-09-27**, com autorização nominal do Wellington: métrica `logging.googleapis.com/user/meta_avisos_de_quota` (contador `DELTA`/`INT64`, label `evento` = `EXTRACT(jsonPayload.event)`; filtro `resource.type="cloud_run_revision" AND resource.labels.service_name="v4-ads-mcp" AND (jsonPayload.event="meta_rate_limit_warning" OR jsonPayload.event="meta_buc_nao_lido")`) e policy `alertPolicies/3565996587605688856` (*"Meta Ads: quota acima de 75% ou BUC nao lido"*: soma em 5 min por `evento` > 0, auto-close 24h, canal de e-mail `15226380074599878362`). Criadas pela REST API como no runbook abaixo, mas do **Git Bash** (`curl -d @arquivo`, o `curl` real — as armadilhas de aspas e BOM do runbook são do PowerShell). O projeto passou de 4 para **5 policies**. Em 25–27/09 houve **zero** desses eventos em 34 chamadas Graph medidas: o normal é silêncio. **Não exercitado ponta a ponta** — nenhum evento real disparou a policy ainda.

## Projeto novo: bootstrap reprodutível (25/11/2026)

Para subir o serviço num projeto GCP novo (migração para o projeto do Gmail, spec
[`2026-11-25-migracao-projeto-gmail-design.md`](../superpowers/specs/2026-11-25-migracao-projeto-gmail-design.md)):

```powershell
D:/v4-ads-mcp/.venv/Scripts/python.exe -m scripts.infra.bootstrap_projeto --project-id <ID> --region southamerica-east1 --alert-email <EMAIL>
```

Sem `--apply` só imprime; com `--apply` executa e é reexecutável (pula o que já existe). Reproduz o
inventário medido em 25/11 (APIs, Artifact Registry, 3 SAs e papéis, WIF restrito ao repo, bucket com
lifecycle 90d, 9 secrets **vazios**, 3 jobs, 2 schedulers **pausados**). **Fica à mão:** os valores
dos secrets (por arquivo, F47), o canal de e-mail e as 5 policies (runbooks REST abaixo), os secrets
`GCP_*` e as vars `PUBLIC_BASE_URL`/`META_BUSINESS_ID` do GitHub. **Medido no `--apply` de 25/11 em
`fluxo-certo-ads` (projeto sem organização, número `505452482961`):** os 46 comandos rodaram com exit 0
e cada recurso foi conferido; o SA padrão do Compute já nasce com `roles/editor` (o
`cloudbuild.builds.builder` explícito do script é redundante ali, inofensivo).

**Ordem do corte (as vars e os secrets do GitHub mudam JUNTOS):** o `deploy.yml` barra o deploy se
`vars.PUBLIC_BASE_URL` ou `vars.META_BUSINESS_ID` estiverem vazias, e usa os secrets `GCP_*` para saber
em qual projeto subir. Troque os quatro `GCP_*` e as duas vars no mesmo momento, com os valores do
projeto de destino. Var nova com secret antigo sobe o serviço antigo com a URL errada nos snippets do
`/help`, do `/sessions` e na mensagem de convite. O script é reexecutável: o `pause` dos schedulers só
roda na criação, então reexecutá-lo depois do corte **não** pausa o resync de produção.

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

$arquivo = "$env:TEMP\google_accounts_sem_grant_query.json"
$body | Set-Content -Encoding ascii -Path $arquivo
$token = gcloud auth print-access-token
curl.exe -s -H "Authorization: Bearer $token" -H "Content-Type: application/json" "https://logging.googleapis.com/v2/entries:list" -d "@$arquivo"
```

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

---

## GitHub
- [x] Repo: `BadWolf1509/v4-ads-mcp` (private)
- [x] Branch protection on `main`: ha **required status check `test`** — o push de 2026-08-19 recebeu `remote: - Required status check "test" is expected.`, que o GitHub so emite quando a branch esta protegida. O fluxo e solo-dev com **admin bypass** (CLAUDE.md, "Git workflow"), entao o push passa mesmo com o check pendente; a protecao vale pra quem nao for admin. O checkbox ficou desmarcado por ~1 ano depois de a protecao existir.

## Supabase project
- [x] Project ref: `laiqtoisehgkwfxaezjl` (region São Paulo)
- [x] DB password recorded (1Password under "v4-ads-mcp / supabase")
- [x] Connection string in Secret Manager: `database-url` (uses Shared Pooler `aws-1-sa-east-1.pooler.supabase.com:5432`, IPv4)

## Google Ads
- [x] Developer token: aposentado pelo Google em 09/09/2026 e não usado desde 11/2026. O nível de acesso é do projeto dono do cliente OAuth (`v4-ads-mcp`); veja em Console > Google Ads API > Níveis de acesso.
- [x] V4 MCC ID: `6436352492` (was previously misidentified as `7862230676` which is actually a child account "Mestre da Obra - João Pessoa")

Histórico (projeto GCP antigo, sign-offs de fase e redesign): [`infra-setup-historico.md`](../_archive/setup/infra-setup-historico.md). Num DR real, siga a seção "ESTADO ATUAL" acima.
