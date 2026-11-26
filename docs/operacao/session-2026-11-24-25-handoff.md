# Sessão 24–25/11/2026 — handoff: desligamento da V4, migração para `fluxo-certo-ads` e escopo de um cliente

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

**Não medido (na parte 1):** a reconciliação Google com login-customer-id de conta, por isso os
schedulers ficaram pausados (a parte 2 mediu e fechou); a publicação do OAuth em Produção; a
verificação de marca (falta o Search Console do `fluxocerto.dev.br` no Gmail).

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

## Parte 2 — 25/11, tarde: backup, alertas e resync com um cliente

1. **#286 — o backup do projeto novo gravaria no bucket da V4.**
   - **Causa:** default `backup_bucket = "v4-ads-mcp-backups"` em código, sem override no job nem no deploy.
   - **Correção:** `BACKUP_BUCKET=<GCP_PROJECT_ID>-backups` pelo `deploy.yml`, e o job falha fechado sem ele.
   - **Prova em produção:** a falha forçada sem bucket saiu antes do banco. O backup manual gravou 13 tabelas (audit 12853). O agendamento semanal foi ligado.
2. **Alertas recriados** a partir do export REST do projeto antigo: canal, uptime, 2 métricas e 5 policies. O Wellington confirmou o e-mail do job falho forçado.
   - **#288** versiona os alertas em `scripts/infra/monitoramento_defs/`. O aplicador só cria o que falta e marca `diferente`, `duplicado` ou `bloqueado` sem tocar em nada.
   - Aceite: 9 recursos `igual`. No controle com host errado, o uptime saiu `diferente`.
3. **Rodada do resync sem aplicar** (audits 12861–12880). Saiu com 1, por três causas:
   - Meta desligada → erro "token do system user nao configurado". A afirmação "BM vazio = no-op" estava errada: o código aborta antes.
   - Google: `bumped=23`. Pela leitura do código, o teto de 20% ou 5 bloquearia a remoção em 3 dias.
   - 5 conexões OAuth vivas de gestores já desativados. O fallback de credencial do job pegaria qualquer uma delas.
4. **#289 — três correções:**
   - `META_HABILITADA` (var, padrão `true`).
   - JML de credencial: o toggle e a convergência diária revogam conexões, e o fallback ignora gestor desativado.
   - `admin descomissionar` auditado: soft, motivos de churn e trilha por conta.
   - O guard F197 ganhou uma exceção estreita: só `deactivate`.
5. **Aplicado em produção**, com aval por ação:
   - a var mais o env do job;
   - 5 conexões revogadas;
   - 23 contas Google e 25 Meta descomissionadas, com 48 linhas `*_access_cleanup`.
   - Uma rodada sem aplicar saiu com **0** (audits 12931–12935), e o resync diário foi ligado.

### Rulings da parte 2

- **Bucket:** derivado do `GCP_PROJECT_ID` no deploy, mesma convenção do bootstrap. Alternativa recusada: uma var nova.
- **Bootstrap** imprime o comando de monitoramento, não o executa: o uptime check alarmaria antes do primeiro deploy.
- **Descomissionamento reusa os motivos de churn** (`left_mcc`/`partnership_ended`) em vez de criar um novo. Assim a restauração existente devolve os acessos.
- **Exceção no guard F197** em vez de mover o código para `src/jobs`. Mover só para passar seria fraudar o guard.

### Candidatos a finding da parte 2 (só o Wellington cataloga)

6. **Default de recurso de ambiente em código** (`backup_bucket`) sobreviveu à migração, e o teste de "sem literais do projeto" só olhava o `deploy.yml`. Família: guard mais estreito que a invariante.
7. **"BM vazio = no-op" afirmado sem probe.** A reconciliação Meta aborta antes, na checagem do token, e o job sairia com 1 todo dia. Família: afirmação sem probe.
8. **Desligamento revogava grants, mas não a credencial.**
   - O fallback `pick_latest_active` escolhia conexão de gestor desativado.
   - O painel só permite que o dono revogue a própria conexão.
   - Família: JML incompleto.
9. **Teto de segurança da reconciliação × login-customer-id de conta.** Reduzir o alcance da credencial faz o plano pedir remoção em massa, que o teto bloqueia, e o job falha todo dia.
10. **Reincidência do falso gate:** `ruff check | tail && git commit` deixou entrar um commit com lint e mypy vermelhos (corrigido em `cedce32`). Família: regra sem mecanismo.

### Minors adiados da parte 2

**Monitoramento:**
- `contem` não conhece os defaults proto3 (`false` e `0` omitidos).
- O dry-run não explica o sentinela `<a criar>`.
- `_MARCADOR` só casa `[A-Z_]`.
- `displayName` fixo no modelo do canal.
- `_ = alert_email` sobrando no bootstrap.
- A paginação não tem teto.
- Falta teste de `diferente` em lista aninhada.

**#289:**
- O toast do toggle não cita as conexões revogadas.
- A contagem do backfill pode divergir sob concorrência.
- `_ativos` monta SQL com f-string; trocar por `Literal`.
- Não há backlog Meta simétrico (documentado como deliberado).

## Próxima sessão

Primeiro: conferir o resync agendado de 26/11, 06:00 BRT. O esperado:
- exit 0;
- `google_reconcile` sem `bumped`;
- `meta_reconcile` `{desligada: true}`;
- `manager_offboarding_reconcile` com `conexoes_a_revogar=0`.

Depois, o "Próximo trabalho" e as pendências do Wellington no [`estado-atual.md`](estado-atual.md):
- Meta própria;
- MCC próprio;
- domínio e marca do OAuth.
