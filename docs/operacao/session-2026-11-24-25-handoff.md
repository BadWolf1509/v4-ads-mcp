# Sessão 24–25/11/2026 — handoff: desligamento da V4 e migração para `fluxo-certo-ads`

> Mapa da sessão. O estado vivo está no [`estado-atual.md`](estado-atual.md); a infra, no
> [`infra-setup.md`](infra-setup.md) (seção autoritativa do projeto novo).

## O que aconteceu

O Wellington saiu da V4 Lima Soares & Co e manteve o projeto para um único cliente (Mestre da Obra JP +
Cabedelo). A sessão partiu de um pedido de outra sessão ("Projetos V4 Lima Soares & Co") para revogar os
acessos `@v4company.com` e terminou com o serviço migrado para um projeto GCP do Gmail.

1. **#283 — a tabela `managers` vira a allowlist** (sem trava `@v4company.com` no login, no convite e na
   conexão do Google Ads; `is_allowed_email` → `is_valid_email_shape`). Deployado no projeto antigo.
2. **24/11, 21:30 BRT — o faturamento do projeto `v4-ads-mcp` foi desligado** pela própria conta
   `@v4company.com` (log de auditoria medido pela sessão "Projetos V4"). Serviço 503. O projeto estava
   dentro da organização `v4company.com`: transferir não é suportado, então **projeto novo**.
3. **#284 — preparo da migração:** `scripts/infra/bootstrap_projeto.py` (reproduz o inventário medido;
   dry-run por padrão, reexecutável, schedulers nascem pausados), `deploy.yml` lendo projeto/URL/BM de
   `vars`, rebrand **Fluxo Certo Ads** (globais Jinja; legais reescritas como rascunho), `Settings` com
   `str_strip_whitespace` (secret `" "` = vazio) e BM vazio aceito com aviso.
4. **Projeto `fluxo-certo-ads` (`505452482961`)** criado e faturado no Gmail; `--apply` do bootstrap com
   cada recurso conferido; 9 secrets (2 chaves novas, `database-url` conferida por conexão real, OAuth,
   login-customer-id e Meta provisórios); GitHub `GCP_*` + `vars.PUBLIC_BASE_URL`; merge do #284 →
   **primeiro deploy verde** (`v4-ads-mcp-00001-cr5`).
5. Login do Gmail (convite já existia), `bootstrap-admin`, probe da API: **Teste → Exploração → Básico**
   no mesmo dia. Leitura real pelo `/mcp` novo: `list_my_accounts`, `get_performance_breakdown` e
   `plan_keyword_ideas` da MDO, todos `success` no `audit_log`.

## Medido × não medido

**Medido:** gate + full sweep + `tests/browser` em cada PR; sabotagem de cada guard novo; `gcloud.CMD`
do Windows passa `==`, `'`, `,`, `(`, `)` e espaço intactos; recursos do projeto novo um a um;
`/health?deep=1`, `/mcp` 401; Google Ads API Básico com keyword planner real.

**Não medido:** comportamento da reconciliação Google com login-customer-id de conta (só leitura do
código: revogaria o inventário — por isso os schedulers seguem **pausados**); publicação do OAuth em
Produção; verificação de marca (falta o Search Console do `fluxocerto.dev.br` no Gmail); alertas do
projeto novo (não criados).

## Decisões que o Claude tomou (rulings)

- Script de bootstrap em Python, não `.ps1` (lista de args sem shell resolve o F66 e é testável).
- `roles/cloudbuild.builds.builder` explícito ao SA do Compute — medido depois: o SA já nasce com
  `roles/editor` num projeto sem organização (redundante, inofensivo).
- Canal de e-mail e policies fora do script (runbook REST).
- Chaves `aes-master-key`/`session-signing-key` **novas** (o refresh token é preso ao cliente OAuth;
  todo mundo reconecta de qualquer jeito).
- Rebrand mais largo que o plano (logo, descrições de 7 tools, mensagem de convite); `com.v4company/bucket`
  e classes CSS `v4-*` ficam; logo antigo não apagado.
- Login-customer-id provisório = MDO (`7862230676`), porque o Gmail tem acesso direto.

## Candidatos a finding (só o Wellington cataloga — `/findings-add`)

1. **Faturamento desligado derruba produção sem alerta.** Nenhuma policy olha o estado de billing; o
   uptime check morreu junto com o projeto. Família: governança ausente.
2. **Escape de barra invertida em `python - <<'EOF'` virou backspace** e o guard novo passou contra o
   código quebrado (`r"\bV4\b"` → `\x08V4\x08`). Só o "verde de primeira" denunciou. Família: guard que
   não cobre. (Lição já na memória `armadilhas-de-shell-e-verificacao`.)
3. **`subprocess.run(["gcloud", ...])` sem shell não acha `gcloud.cmd` no Windows** (C1 da revisão do
   #284); mock de `subprocess.run` escondia. Família: teste que não exercita o caminho real.
4. **`pause` de scheduler como comando solto** pausaria produção a cada reexecução do bootstrap (I1).
5. **Trava do `deploy.yml` mais estrita que o código** (BM vazio barrava, mas é estado legítimo) —
   achado ao preparar o corte com a Meta desligada.

## Minors adiados

Bootstrap: M1 (SA do Compute/consistência eventual), M5 (pool WIF em soft-delete), M6 (scheduler sem
`description`). #283: busca do gestor no login sem `lower()` (falha fechado); convite sem teste de dois
`@`/espaços; teste HTTP de `not_invited` para domínio externo; helper `_cookies_apagados` com nome
enganoso. Marca provisória "FC". Páginas legais do serviço são rascunho.

## Próxima sessão

Ver "Decision gates", "Próximo trabalho" e "Pendências que dependem do Wellington" no
[`estado-atual.md`](estado-atual.md). O primeiro item técnico é recriar os alertas no projeto novo.
