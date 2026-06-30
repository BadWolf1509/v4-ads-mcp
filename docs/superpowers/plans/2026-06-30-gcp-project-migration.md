# Migração do projeto GCP — Plano de execução

> **Para workers:** runbook de infra (não TDD). Execute fase a fase; ao fim de cada fase há um **🔄 Checkpoint** — pare, verifique o critério, reavalie antes de seguir. `[G]` = gestor (Cloud Shell / console). `[C]` = Claude (automação/verificação no terminal local).

**Goal:** Levantar um clone do v4-ads-mcp num projeto GCP novo onde `wellington.ribeiro@` é owner, virar os 4 gestores via cutover paralelo, e decomissionar o antigo.

**Architecture:** Lift-and-shift. Mesmo código/repo/`deploy.yml`, mesmo Supabase, mesma região. Só muda o projeto GCP, billing, URL, OAuth clients e chaves de cifra. Spec: [2026-06-30-gcp-project-migration-design.md](../specs/2026-06-30-gcp-project-migration-design.md).

**Tech Stack:** GCP (Cloud Run, Cloud Build/Buildpacks, Artifact Registry, Secret Manager, Cloud Scheduler, WIF), GitHub Actions, Supabase (externo).

## Global Constants (use em todos os comandos)

```bash
# === rode no Cloud Shell (bash byte-clean — evita o CRLF do F47) ===
export NEW_PROJECT=v4-ads-mcp          # [G] confirme disponível na Task 1; senão escolha outro id
export REGION=southamerica-east1
export ORG=1098515561970               # v4company.com
export REPO=BadWolf1509/v4-ads-mcp
export MCC=6436352492                  # google-ads-login-customer-id
# Meta app de produção: V4 Ads MCP = 1522411803012799 ; system-user = v4-ads-mcp-integracao (61590110716028)
```

Os 13 secrets a recriar e suas origens estão na §4 do spec. **Nunca** colar valor de secret no chat.

---

### Task 1: Projeto + billing + APIs `[G]`

**Files:** nenhum (console/Cloud Shell).

- [ ] **1.1** Confirmar disponibilidade do ID e criar o projeto sob o org:
```bash
gcloud projects create $NEW_PROJECT --name="V4 Ads MCP" --organization=$ORG
```
Se "already exists / not available", escolha outro id e atualize `NEW_PROJECT`.

- [ ] **1.2** Criar uma billing account própria (console: **Faturamento → Criar conta**, cartão da unidade) e pegar o ID:
```bash
gcloud billing accounts list   # copie o ACCOUNT_ID da conta nova
export BILLING=XXXXXX-XXXXXX-XXXXXX
gcloud billing projects link $NEW_PROJECT --billing-account=$BILLING
```

- [ ] **1.3** Alerta de orçamento (console: **Faturamento → Orçamentos** → US$20/mês, e-mail) — evita surpresa.

- [ ] **1.4** Habilitar APIs:
```bash
gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com secretmanager.googleapis.com \
  cloudscheduler.googleapis.com iam.googleapis.com googleads.googleapis.com \
  --project=$NEW_PROJECT
```

- [ ] **1.5 Verificação:**
```bash
gcloud services list --enabled --project=$NEW_PROJECT | grep -E "run|secretmanager|artifactregistry|cloudbuild|scheduler"
gcloud billing projects describe $NEW_PROJECT   # billingEnabled: true
```

**🔄 Checkpoint 1:** projeto existe, billing vinculada (`billingEnabled: true`), 6 APIs ativas. Reavaliar: o id escolhido é o definitivo? Anote o `PROJECT_NUMBER`: `gcloud projects describe $NEW_PROJECT --format='value(projectNumber)'` → `export PROJECT_NUMBER=...`

---

### Task 2: Identidade & infra base `[G]` (comandos fornecidos por `[C]`)

**Files:** nenhum (Cloud Shell).

- [ ] **2.1** Artifact Registry (mesmo nome que o `deploy.yml` espera):
```bash
gcloud artifacts repositories create v4-ads-mcp --repository-format=docker \
  --location=$REGION --project=$NEW_PROJECT
```

- [ ] **2.2** Runtime SA + role de leitura de secret:
```bash
gcloud iam service-accounts create v4-ads-mcp-runtime --project=$NEW_PROJECT
gcloud projects add-iam-policy-binding $NEW_PROJECT \
  --member="serviceAccount:v4-ads-mcp-runtime@$NEW_PROJECT.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

- [ ] **2.3** Deploy SA + roles (espelha o que o `deploy.yml` faz):
```bash
gcloud iam service-accounts create v4-ads-mcp-deploy --project=$NEW_PROJECT
DEPLOY_SA="v4-ads-mcp-deploy@$NEW_PROJECT.iam.gserviceaccount.com"
for R in roles/run.admin roles/cloudbuild.builds.editor roles/artifactregistry.writer \
         roles/iam.serviceAccountUser roles/storage.objectViewer \
         roles/serviceusage.serviceUsageConsumer; do
  gcloud projects add-iam-policy-binding $NEW_PROJECT \
    --member="serviceAccount:$DEPLOY_SA" --role="$R" --condition=None
done
```

- [ ] **2.4** WIF pool + provider federado com o repo (cópia do binding do projeto antigo):
```bash
gcloud iam workload-identity-pools create github --location=global --project=$NEW_PROJECT
gcloud iam workload-identity-pools providers create-oidc github-provider \
  --location=global --workload-identity-pool=github \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --attribute-condition="assertion.repository=='$REPO'" --project=$NEW_PROJECT
# permitir o repo impersonar o deploy SA:
gcloud iam service-accounts add-iam-policy-binding $DEPLOY_SA --project=$NEW_PROJECT \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/github/attribute.repository/$REPO"
```

- [ ] **2.5** Guardar o provider path (vira o GitHub secret `GCP_WIF_PROVIDER` na Task 4):
```bash
echo "projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/github/providers/github-provider"
```

- [ ] **2.6 Verificação:**
```bash
gcloud artifacts repositories describe v4-ads-mcp --location=$REGION --project=$NEW_PROJECT
gcloud iam service-accounts list --project=$NEW_PROJECT   # runtime + deploy
gcloud iam workload-identity-pools providers describe github-provider --location=global --workload-identity-pool=github --project=$NEW_PROJECT
```

**🔄 Checkpoint 2:** AR repo, 2 SAs com roles, WIF provider com condição no repo certo. Reavaliar: roles do deploy SA suficientes? (Se o deploy falhar em Task 4 por permissão, voltar aqui.)

---

### Task 3: Secrets `[G]` (script binary-safe fornecido por `[C]`)

**Files:** nenhum (Cloud Shell — bash é byte-clean, não precisa do truque F47 do PowerShell).

- [ ] **3.1** Recuperáveis do **Supabase dashboard** (Settings → Database/API): copie `database-url` (connection string, modo *session pooler*), `supabase-url`, `supabase-anon-key`, `supabase-service-key`.

- [ ] **3.2** Recuperáveis (você é admin): `meta-app-id`+`meta-app-secret` (app *V4 Ads MCP* → Configurações), `google-ads-developer-token` (Bitwarden "Google ads V4" ou API Center da MCC). `google-ads-login-customer-id` = `6436352492`.

- [ ] **3.3** Regenerar:
```bash
# aes-master-key e session-signing-key:
python3 -c "import secrets;print(secrets.token_urlsafe(32))"   # rode 2x, guarde cada saída
```
`meta-system-user-token`: gerar **novo token all-targets** no app *V4 Ads MCP* → System Users → `v4-ads-mcp-integracao` → Generate token → marcar **todas as ad accounts (atuais e futuras)** + scopes `ads_read`,`ads_management`,`business_management`.

- [ ] **3.4** `google-oauth-client-id`/`secret`: deixar pra Task 5 (precisa da URL). Por ora, criar os secrets vazios depois — **ou** pular e criar na Task 5. (Mantemos aqui só os 11 que já temos.)

- [ ] **3.5** Criar os secrets (1 por valor; cole o valor no editor do Cloud Shell, NÃO no chat):
```bash
create_secret () {  # uso: create_secret NOME ; depois cole o valor e Ctrl-D
  gcloud secrets create "$1" --replication-policy=automatic --project=$NEW_PROJECT 2>/dev/null
  cat | gcloud secrets versions add "$1" --data-file=- --project=$NEW_PROJECT
}
for S in database-url supabase-url supabase-anon-key supabase-service-key \
         meta-app-id meta-app-secret google-ads-developer-token \
         google-ads-login-customer-id aes-master-key session-signing-key \
         meta-system-user-token; do
  echo ">>> cole o valor de $S e tecle Ctrl-D:"; create_secret "$S"
done
```

- [ ] **3.6 Verificação:**
```bash
gcloud secrets list --project=$NEW_PROJECT   # 11 secrets (google-oauth-* entram na Task 5)
```

**🔄 Checkpoint 3:** 11 secrets criados, runtime SA com `secretAccessor`. Reavaliar: a connection string do Supabase é a do *pooler* (porta 6543/5432 conforme o app espera)? Confirmar contra `src/config.py`.

---

### Task 4: Jobs + primeiro deploy `[C]` + `[G]`

**Files:** Modify (GitHub secrets, não arquivos).

- [ ] **4.1 `[G]`** Criar os 2 Cloud Run Jobs vazios (o `deploy.yml` faz `jobs update`, exige que existam):
```bash
IMG="$REGION-docker.pkg.dev/$NEW_PROJECT/v4-ads-mcp/app:bootstrap"
RUNTIME="v4-ads-mcp-runtime@$NEW_PROJECT.iam.gserviceaccount.com"
# imagem placeholder só pra criar o job; o deploy.yml troca pela real
gcloud run jobs create v4-ads-mcp-migrate --image=gcr.io/cloudrun/hello --region=$REGION \
  --service-account=$RUNTIME --project=$NEW_PROJECT
gcloud run jobs create v4-ads-mcp-resync  --image=gcr.io/cloudrun/hello --region=$REGION \
  --service-account=$RUNTIME --project=$NEW_PROJECT
```

- [ ] **4.2 `[C]`** Atualizar os GitHub secrets pro novo projeto (eu rodo via `gh`, com os valores que você me passar de 2.5/Task 2):
```bash
gh secret set GCP_PROJECT_ID  --body "$NEW_PROJECT"            --repo $REPO
gh secret set GCP_REGION      --body "southamerica-east1"      --repo $REPO
gh secret set GCP_DEPLOY_SA   --body "$DEPLOY_SA"              --repo $REPO
gh secret set GCP_WIF_PROVIDER --body "<provider path de 2.5>" --repo $REPO
```
> ⚠️ A partir daqui o `deploy.yml` aponta pro **novo** projeto. O antigo congela na última revisão (segue vivo, sem novos deploys) — é o que queremos no paralelo.

- [ ] **4.3 `[C]`** Disparar o deploy (re-run do workflow Deploy ou um commit no-op):
```bash
gh workflow run Deploy --repo $REPO   # ou: git commit --allow-empty -m "chore: trigger deploy no projeto novo" && push
```

- [ ] **4.4 `[C]`** Acompanhar até concluir (confirmar via `--json conclusion`, nunca pelo exit de `watch`):
```bash
gh run list --workflow=Deploy --limit 1; gh run view <id> --json status,conclusion
```
Esperado: `success`. O smoke do próprio workflow valida `/health?deep=1` db=ok + `/mcp` 401.

- [ ] **4.5 `[G]`** Cloud Scheduler pro resync diário (espelha o antigo):
```bash
gcloud scheduler jobs create http v4-ads-mcp-resync-daily --location=$REGION --project=$NEW_PROJECT \
  --schedule="0 6 * * *" --uri="https://$REGION-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/$NEW_PROJECT/jobs/v4-ads-mcp-resync:run" \
  --http-method=POST --oauth-service-account-email=$DEPLOY_SA
```

- [ ] **4.6 Verificação:**
```bash
SERVICE_URL=$(gcloud run services describe v4-ads-mcp --region=$REGION --project=$NEW_PROJECT --format='value(status.url)')
echo $SERVICE_URL; curl -fsS "$SERVICE_URL/health?deep=1"
```
Esperado: `{"status":"ok",...,"db":"ok"}`. **Guarde `SERVICE_URL`** (nova URL).

**🔄 Checkpoint 4:** serviço no ar, `db=ok`, jobs+scheduler criados. Reavaliar: o deploy passou de primeira? Se falhou por IAM → Checkpoint 2. A URL nova é esta `SERVICE_URL`.

---

### Task 5: OAuth (Google + Meta) `[G]`

**Files:** nenhum (consoles).

- [ ] **5.1 Google OAuth client** no `$NEW_PROJECT` (console → APIs & Services → Credentials → Create OAuth client ID → Web): consent screen **Internal**; Authorized redirect URI = `$SERVICE_URL` + o callback do app (confira o path em `src/auth/oauth.py`, ex.: `$SERVICE_URL/oauth/google/callback`). Copie client id/secret.

- [ ] **5.2 `[G]`** Criar os 2 secrets que faltavam:
```bash
echo ">>> google-oauth-client-id"; create_secret google-oauth-client-id
echo ">>> google-oauth-client-secret"; create_secret google-oauth-client-secret
```

- [ ] **5.3 Meta** (developers.facebook.com → app *V4 Ads MCP* → Login do Facebook → Configurações): adicionar `$SERVICE_URL` + callback (confira em `src/auth/meta_oauth.py`, ex.: `$SERVICE_URL/oauth/meta/callback`) em **Valid OAuth Redirect URIs**.

- [ ] **5.4 `[C]`** Redeploy pra montar os secrets OAuth novos:
```bash
gh workflow run Deploy --repo $REPO   # pega google-oauth-* :latest
```

- [ ] **5.5 Verificação:** abrir `$SERVICE_URL/login` no browser → fluxo Google OAuth conclui sem erro de redirect_uri.

**🔄 Checkpoint 5:** OAuth Google + Meta aceitam a URL nova; login funciona. Reavaliar: o callback path bate com o código? (se der `redirect_uri_mismatch`, ajustar a URI no console).

---

### Task 6: Validação ponta-a-ponta `[G]` + `[C]`

- [ ] **6.1 `[G]`** No painel do ambiente NOVO, 1 gestor de teste reconecta Google OAuth + (se aplicável) Meta.
- [ ] **6.2 `[G]`** Emitir 1 Bearer v4-ads via `/sessions` do ambiente novo; configurar num cliente de teste.
- [ ] **6.3 `[C]`** Rodar tools read de fumaça: `list_my_accounts` (Google) e `meta_list_my_ad_accounts`.
- [ ] **6.4 Verificação F64:** `meta_list_my_ad_accounts` **inclui `CA - MDO Goiânia`** (`act_1292624998332379`) → token all-targets confirmado.

**🔄 Checkpoint 6:** dados retornam; CA-MDO Goiânia presente; resync manual (`gcloud run jobs execute v4-ads-mcp-resync`) popula `meta_ad_accounts`. Reavaliar: algo do antigo não replicou? Comparar `get_account_overview` nos dois.

---

### Task 7: Cutover dos 4 gestores `[G]`

- [ ] **7.1** Para cada um dos 4: emitir Bearer novo (`/sessions` do novo) → atualizar `~/.claude.json` (`mcpServers.v4-ads.url` = `$SERVICE_URL/mcp` + `headers.Authorization` = Bearer novo) → restart do cliente.
- [ ] **7.2** Cada gestor reconecta Google OAuth no painel novo (Meta não precisa — system-user token).
- [ ] **7.3 Verificação:** cada gestor roda 1 tool e vê dados; `audit_log` do novo registra `manager_id` deles.

**🔄 Checkpoint 7:** 4 gestores operando no novo. Reavaliar: algum preso no antigo? Manter o antigo vivo como fallback.

---

### Task 8: Decomissão `[G]`

- [ ] **8.1** Janela de fallback ~1–2 semanas (antigo vivo, sem deploys).
- [ ] **8.2** Após estabilidade: revogar Bearers antigos; parar o serviço antigo (`gcloud run services delete v4-ads-mcp` no projeto **antigo** — se tiver acesso; senão deixar ocioso, escala a zero = custo ~0).
- [ ] **8.3 `[C]`** Atualizar CLAUDE.md (novo `PROJECT_ID`, nova URL de produção, IAM agora = owner) + handoff + fechar F64 no findings-catalog.

**🔄 Checkpoint 8 (final):** produção 100% no projeto novo; gestor é owner; F64 fechado; docs atualizadas. Migração completa.

---

## Self-review (cobertura do spec)

- D1 billing própria → Task 1.2/1.3 ✓ · D2 URL default → URL vem do deploy (4.6), OAuth depois (5) ✓ · D3 regenerar chaves → 3.3 + reconexões 7.2 ✓ · D4 mesmo Supabase → 3.1 ✓ · D5 cutover paralelo → 4.2 nota + 7 + 8 ✓
- Secrets §4 do spec: 11 em Task 3 + 2 OAuth em Task 5 = 13 ✓
- Critérios de sucesso do spec: health (4.6/6), F64/CA-MDO Goiânia (6.4), resync (6 checkpoint), owner (1) ✓
- Riscos: jobs antes do deploy (4.1) ✓; ordem OAuth↔URL (5 pós-4) ✓; orçamento (1.3) ✓; dois ambientes mesmo DB (4.2 nota) ✓
