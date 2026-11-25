# Migração para projeto Gmail — Fase 2 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** deixar o repositório pronto para subir num projeto GCP novo do Wellington: script de infra reprodutível, `deploy.yml` sem valores da V4 fixos, e páginas públicas sem a V4, com o produto renomeado para "Fluxo Certo Ads".

**Architecture:** três frentes independentes. (A) um script Python que **monta** a lista de comandos `gcloud` a partir de parâmetros (função pura, testável) e só executa com `--apply`; (B) `vars.*` do GitHub no lugar dos literais do projeto atual; (C) um global Jinja `nome_produto` e textos públicos reescritos.

**Tech Stack:** Python 3.13, pytest, Jinja2, GitHub Actions, gcloud.

**Spec:** `docs/superpowers/specs/2026-11-25-migracao-projeto-gmail-design.md`

## Global Constraints

- Nenhuma escrita no GCP, no GitHub (secrets/vars) ou em produção nesta fase: o script roda só em dry-run nos testes; `--apply` é do Wellington.
- Nome do produto: **`Fluxo Certo Ads`**, definido em um único lugar.
- Inventário medido em 25/11 no projeto atual (fonte da Task 1): SAs `v4-ads-mcp-runtime`, `v4-ads-mcp-deploy` (o `infra-setup.md` diz `github-deployer` — está defasado), `v4-ads-mcp-scheduler`; papéis do deploy: `artifactregistry.writer`, `cloudbuild.builds.editor`, `iam.serviceAccountUser`, `run.admin`, `serviceusage.serviceUsageConsumer`, `storage.admin`, `storage.objectViewer`; runtime: `secretmanager.secretAccessor` no projeto + `storage.objectCreator` no bucket; scheduler: `run.invoker` nos jobs `resync` e `backup`; WIF pool `github`, provider `github-provider`, issuer `https://token.actions.githubusercontent.com`, condição `assertion.repository=='BadWolf1509/v4-ads-mcp'`, mapping `google.subject=assertion.sub,attribute.repository=assertion.repository`, `roles/iam.workloadIdentityUser` para o principalSet do repo no SA de deploy; jobs `migrate` (retries 1, 600s), `resync` (retries 3, 600s), `backup` (retries 1, 900s), todos 1 CPU/512Mi, args `/cnb/process/<tipo>`; schedulers `v4-ads-mcp-resync-daily` `0 6 * * *` e `v4-ads-mcp-backup-weekly` `0 5 * * 0`, fuso `America/Sao_Paulo`; bucket UBLA, lifecycle Delete age 90; Artifact Registry docker `v4-ads-mcp`.
- Secrets a criar (vazios): os 9 de `--set-secrets` do serviço no `deploy.yml` — `database-url`, `session-signing-key`, `aes-master-key`, `google-oauth-client-id`, `google-oauth-client-secret`, `google-ads-login-customer-id`, `meta-app-id`, `meta-app-secret`, `meta-system-user-token`. Não recriar `google-ads-developer-token` nem `supabase-*`.
- Commits `feat(ci)` / `feat(web)` / `docs(…)`, trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Gate mudo antes de cada commit.

## Review Focus

1. Script reexecutado num projeto que já tem metade dos recursos: precisa ser idempotente (comando de checagem antes de cada criação, ou `create || describe`) — dono: Task 1 (`test_cada_criacao_tem_checagem`).
2. Schedulers nascem **pausados** — um resync no projeto novo antes do corte revoga grants (spec, Fase 3 passo 2) — dono: Task 1 (`test_schedulers_nascem_pausados`).
3. Nenhum valor de secret passa por argumento de linha de comando ou pipe (F47) — dono: Task 1 (`test_nenhum_valor_de_secret_no_comando`).
4. `vars.PUBLIC_BASE_URL` vazio no GitHub faria o deploy subir com `PUBLIC_BASE_URL=` — dono: Task 2 (passo de validação no workflow + `test_deploy_exige_vars`).
5. Página pública que ainda cite `@v4company` ou "V4 Ads MCP" depois do rebrand — dono: Task 3 (`test_paginas_publicas_sem_v4`).

---

### Task 1: Script de infra reprodutível

**Files:**
- Create: `scripts/infra/__init__.py`, `scripts/infra/bootstrap_projeto.py`
- Test: `tests/unit/test_bootstrap_projeto.py`
- Modify: `docs/operacao/infra-setup.md` (seção nova "Projeto novo: bootstrap" + corrigir `github-deployer` → `v4-ads-mcp-deploy`)

**Interfaces:**
- Produces: `@dataclass(frozen=True) class Comando: checagem: list[str] | None; criacao: list[str]` e `def montar_comandos(*, project_id: str, region: str, alert_email: str, repo: str = "BadWolf1509/v4-ads-mcp") -> list[Comando]`; CLI `python -m scripts.infra.bootstrap_projeto --project-id X --region Y --alert-email Z [--apply]`. Sem `--apply`, imprime os comandos e sai 0.

- [ ] **Step 1: Testes** (todos sobre `montar_comandos(project_id="p-teste", region="southamerica-east1", alert_email="a@b.com")`):
  - `test_cria_os_tres_service_accounts`: há criação `iam service-accounts create` para `v4-ads-mcp-runtime`, `v4-ads-mcp-deploy`, `v4-ads-mcp-scheduler`.
  - `test_papeis_do_deploy_iguais_ao_medido`: o conjunto de `--role` em `projects add-iam-policy-binding` para `v4-ads-mcp-deploy@p-teste.iam.gserviceaccount.com` é exatamente os 7 papéis do Global Constraints.
  - `test_wif_restrito_ao_repo`: o provider tem `--attribute-condition=assertion.repository=='BadWolf1509/v4-ads-mcp'`.
  - `test_jobs_com_args_cnb`: os 3 `run jobs create` têm `--args=/cnb/process/<tipo>` e os retries/timeouts medidos. Os jobs usam `--image=us-docker.pkg.dev/cloudrun/container/hello` como placeholder (o primeiro deploy troca).
  - `test_schedulers_nascem_pausados`: para cada scheduler criado existe um `scheduler jobs pause` depois dele na lista.
  - `test_cada_criacao_tem_checagem`: toda `Comando.criacao` que cria recurso tem `checagem` não nula (exceção: `services enable` e `add-iam-policy-binding`, idempotentes por natureza — listar no teste).
  - `test_nenhum_valor_de_secret_no_comando`: `secrets create` usa `--replication-policy=automatic` **sem** valor; nenhum argumento de nenhum comando contém `data-file` (os valores entram depois, por arquivo, à mão — F47).
  - `test_cria_os_nove_secrets`: nomes exatos do Global Constraints, nem mais nem menos.
  - `test_dry_run_nao_executa`: com `subprocess.run` monkeypatchado para registrar, `main(["--project-id","p","--region","r","--alert-email","a@b.com"])` retorna 0 e não chama `subprocess.run`.
- [ ] **Step 2: Falhar** — `D:/v4-ads-mcp/.venv/Scripts/python.exe -m pytest tests/unit/test_bootstrap_projeto.py -q` → ImportError.
- [ ] **Step 3: Implementar.** Execução com `subprocess.run(lista, check=False)` sem shell (lista de args: o `/cnb/process/*` não passa por Git Bash, F66); `checagem` com retorno 0 → pula a criação. Bucket `gs://<project_id>-backups`. Policies de alerta: **fora** deste script (o runbook REST do `infra-setup.md` cria as 5; o script só cria o canal de e-mail e imprime o lembrete) — Ruling se mudar.
- [ ] **Step 4: Verde** + sabotagem: tirar o `pause` de um scheduler → `test_schedulers_nascem_pausados` vermelho; desfazer.
- [ ] **Step 5: Commit** `feat(ci): script reprodutível de bootstrap do projeto GCP`

### Task 2: `deploy.yml` sem literais do projeto atual

**Files:**
- Modify: `.github/workflows/deploy.yml` (linhas 68, 96/130/202/373/392, 212), `src/config.py:77`, `src/scripts/admin.py:243`
- Test: `tests/unit/test_deploy_sem_literais_do_projeto.py`

**Interfaces:**
- Consumes: nada. Produces: `vars.PUBLIC_BASE_URL`, `vars.META_BUSINESS_ID` (o Wellington cria no GitHub no corte).

- [ ] **Step 1: Testes**
  - `test_deploy_sem_project_number`: `"299432068772"` não aparece em `deploy.yml`.
  - `test_deploy_sem_bm_da_v4`: `"619664032237208"` não aparece em `deploy.yml`.
  - `test_public_base_url_vem_de_vars`: a linha `--set-env-vars` do serviço contém `PUBLIC_BASE_URL=${{ vars.PUBLIC_BASE_URL }}`; `JOB_ENV_VARS` e a linha do serviço contêm `META_BUSINESS_ID=${{ vars.META_BUSINESS_ID }}`.
  - `test_registry_deriva_da_regiao`: nenhuma ocorrência literal de `southamerica-east1-docker.pkg.dev`; usa `${REGION}-docker.pkg.dev` (ou `${{ secrets.GCP_REGION }}`).
  - `test_deploy_exige_vars`: existe um step antes do build que falha (`exit 1`) se `vars.PUBLIC_BASE_URL` ou `vars.META_BUSINESS_ID` estiverem vazios.
  - `test_defaults_nao_apontam_projeto_antigo`: `Settings.model_fields["public_base_url"].default` e o default do `--base-url` do `admin.py` não contêm `299432068772`.
- [ ] **Step 2: Falhar.**
- [ ] **Step 3: Implementar.** Default de `public_base_url` vira `"http://localhost:8000"` (produção sempre seta). Confira que `test_deploy_env_matches_settings`, `test_deploy_jobs_retiram_secrets`, `test_deploy_job_image_order` e `test_ci_deploy_gate` seguem verdes — se algum fixar o literal, atualize com Ruling.
- [ ] **Step 4: Verde** + `check_pre_push.py`.
- [ ] **Step 5: Commit** `feat(ci): deploy lê projeto, URL e BM de vars do repositório`
- **Atenção operacional (vai no PR):** antes do merge desta task, o Wellington cria `vars.PUBLIC_BASE_URL` e `vars.META_BUSINESS_ID` no GitHub com os valores **atuais** — senão o step de validação barra o próximo deploy. Ordem: vars → merge.

### Task 3: Produto "Fluxo Certo Ads" e páginas públicas sem a V4

**Files:**
- Modify: `src/web/templating.py:45` (global `nome_produto`), os 24 templates com "V4 Ads MCP", `legal/privacy.html`, `legal/terms.html`, `legal/data_deletion_status.html`, `help.html`, os 9 pontos em `src/**/*.py` que citam a V4 (levantar com `grep -rn "V4 Ads MCP\|V4 Company\|V4 Lima\|v4company" src --include=*.py`, exceto `src/scripts/admin.py` docstrings de exemplo, que viram `gestor@exemplo.com`)
- Test: `tests/unit/test_paginas_publicas_sem_v4.py`; atualizar os testes que fixarem "V4 Ads MCP"/"Entrar com Google V4"

**Interfaces:**
- Produces: `NOME_PRODUTO = "Fluxo Certo Ads"` em `src/web/templating.py`, exposto como `templates.env.globals["nome_produto"]`.

- [ ] **Step 1: Testes**
  - `test_paginas_publicas_sem_v4` (parametrize `/login`, `/help`, `/legal/privacy`, `/legal/terms`, `/data-deletion-status?id=x` — conferir a rota real em `pages.py`): resposta 200, `"Fluxo Certo Ads" in text`, e nenhum de `"V4 Ads MCP"`, `"@v4company"`, `"V4 Company"`, `"V4 Lima"`, `"Google V4"` no texto.
  - `test_nome_produto_num_lugar_so`: `grep` em `src/web/templates` não acha a string literal `"Fluxo Certo Ads"` (só o global).
- [ ] **Step 2: Falhar.**
- [ ] **Step 3: Implementar.** Contato nas legais: `wellington.ribeiro.eng@gmail.com`; operador: "Wellington Ribeiro". Botão "Entrar com Google V4" → "Entrar com Google". Textos de "admin V4 da sua unidade" → "o admin". Classes CSS `v4-*` e o nome do pacote ficam. Se o nome do servidor MCP no handshake for "V4 Ads MCP", troca também (só cosmético) — conferir se algum teste fixa. **O texto jurídico é rascunho:** marcar no PR que o Wellington revisa privacidade e termos.
- [ ] **Step 4: Verde** + `check_pre_push.py` + `tests/browser`.
- [ ] **Step 5: Commit** `feat(web): produto vira Fluxo Certo Ads; páginas públicas sem a V4`

### Fecho

- Full sweep; um PR com as 3 tasks. Merge só com aval nominal, **depois** de as 2 `vars` existirem no GitHub (Task 2).
- `estado-atual.md`: registrar a decisão Cloud Run, o inventário medido e a ordem do corte.
