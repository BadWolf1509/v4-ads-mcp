# Migração para um projeto GCP no Gmail — design (25/11/2026)

## Intenção

Wellington sai da V4 Lima Soares & Co e segue com o MCP atendendo um único cliente, a Mestre da Obra
JP + Cabedelo (Google `7862230676`, Meta `act_27798855556414269`, BM `3771852976434166`). Tudo o que
hoje pertence à V4 precisa de um equivalente dele, **antes** de o Workspace da V4 ser desligado.
Hospedagem decidida em 25/11: **Cloud Run no projeto novo**, não VPS.

## Medido (24–25/11)

- Projeto `v4-ads-mcp` (`299432068772`) está **dentro da organização `v4company.com`**
  (`1098515561970`); owner único `wellington.ribeiro@v4company.com`; faturamento só da V4. Tirar
  projeto de organização não é suportado → é **projeto novo**, não transferência.
- **Não há developer token** desde 09/09: o acesso à Google Ads API (nível Básico, 15.000 ops/dia) é
  do **projeto**. O projeto novo pede acesso de novo.
- MCC `6436352492` e BM `619664032237208` são da V4. O app Meta `1522411803012799` ("V4 Ads MCP")
  está em `619664032237208/owned_apps` → **o app Meta também é da V4**. O mesmo BM é dono do app
  "V4 MDO Stories" (`4419481288293195`) — fora deste escopo, mas é ativo da MDO preso à V4.
- Banco é Supabase, **fora** do projeto GCP: não migra.
- Login sem trava de domínio em produção desde 25/11 (#283).

## Não medido

Prazo real das aprovações (acesso à API; verificação do escopo `adwords`); se o Supabase restringe
IP; custo do projeto novo; conteúdo que a verificação OAuth exigirá das páginas legais.

## Objetivos / não-objetivos / anti-objetivos

- **Objetivo:** serviço no projeto novo do Gmail, operando a MDO com credenciais só dele, com os mesmos
  guards de hoje (gate de acesso, audit, reconciliações, alertas, backup).
- **Não-objetivo:** mudar arquitetura, banco, ou tirar a governança; atender novos clientes.
- **Anti-objetivos:** perder o grant da MDO na troca; apagar `audit_log`; dois resyncs reconciliando o
  mesmo banco contra MCCs diferentes; deixar o serviço sem alerta.

## Abordagens consideradas

| Abordagem | Troca | Escolha |
|---|---|---|
| **Cloud Run no projeto novo (lift-and-shift, como 30/06)** | reaproveita `deploy.yml`, jobs e alertas; exige projeto GCP de qualquer forma (API) | **escolhida** |
| VPS | custo fixo, mas ~6 peças a refazer (deploy com rollback, alertas, backup S3, TLS, cron, patches) e o projeto GCP continua necessário | descartada (25/11) |
| Mover o projeto atual para fora da org | não suportado pelo GCP | inviável |

## Desenho

### Fase 1 — Wellington, logado no Gmail (caminho crítico; começar já)

1. Criar projeto GCP (sem organização) e faturamento — dados de pagamento só ele.
2. Criar MCC próprio; pedir à MDO o vínculo da `7862230676` **sem** a V4 desvincular (sobreposição).
3. Pedir acesso à Google Ads API para o projeto novo.
4. Tela de consentimento **Externo** + cliente OAuth web; pedir verificação do escopo `adwords`
   (precisa das páginas legais da Fase 2). Em modo Teste o refresh token expira em 7 dias.
5. Meta: BM próprio, app próprio, system user com token all-targets (lição F64), parceria com o BM
   `3771852976434166` da MDO.

### Fase 2 — Claude prepara (não depende do Gmail)

- **A. Script de infra** `scripts/infra/bootstrap_projeto.ps1` (PowerShell — o Git Bash mangla o
  `/cnb/process/*`, F66): idempotente, parametrizado por `-ProjectId -Region -AlertEmail`; cria
  APIs, Artifact Registry, SAs (`v4-ads-mcp-runtime`, `github-deployer`, `v4-ads-mcp-scheduler`) com
  os papéis de hoje, WIF para o repo, bucket de backup (UBLA, lifecycle 90d), secrets **vazios** (os
  valores entram por arquivo, nunca por pipe — F47), os 3 jobs, os 2 schedulers **pausados**, canal de
  e-mail e as 5 policies. Roda com `-DryRun` imprimindo os comandos.
- **B. `deploy.yml`:** `PUBLIC_BASE_URL` e `META_BUSINESS_ID` saem do texto fixo para `vars.*` do
  repositório (nas linhas do serviço **e** no `JOB_ENV_VARS`); o host do Artifact Registry deriva de
  `GCP_REGION`. Defaults de `public_base_url` (`config.py:77`, `admin.py:243`) deixam de apontar o
  projeto antigo.
- **C. Páginas legais e ajuda:** privacidade, termos, status de exclusão e `help.html` sem a V4 e sem
  `@v4company`; contato do operador novo. **Texto jurídico final é do Wellington.**

### Fase 3 — corte (na janela de sobreposição do MCC)

1. Valores dos secrets no projeto novo; troca dos 4 secrets `GCP_*` + 2 `vars` no GitHub; deploy.
2. **Pausar o Scheduler do projeto antigo ANTES** de despausar o do novo — o mesmo banco com dois
   resyncs contra MCCs diferentes faz um revogar o que o outro concede.
3. Gmail entra, conecta Google Ads (todos reconectam: o refresh token é preso ao cliente OAuth) e
   recebe os grants da MDO; o resync novo roda com `GOOGLE_ADS_LOGIN_CUSTOMER_ID` = MCC novo e o BM
   novo; conferir que a MDO segue com grant vivo.
4. Desativar no painel os 4 `@v4company` (F213, soft); revogar a conexão OAuth órfã do lucassoares.
5. Só então a V4 desvincula a MDO do MCC/BM dela. Projeto antigo fica parado (não apagado) até o corte
   do Workspace.

Chaves `aes-master-key`/`session-signing-key` **novas** no projeto novo (decisão do Claude): como todo
mundo reconecta de qualquer jeito, copiar a chave antiga só levaria segredo de um projeto da V4.

## Para o plano

Ordem das tasks da Fase 2 (A, B e C são independentes), forma dos testes do script (dry-run comparado
a snapshot) e a lista exata de papéis IAM, lida do projeto atual antes de escrever o script.
