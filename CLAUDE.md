# V4 Ads MCP — agent context

Auto-loaded by Claude Code. Read first.

**V4 Ads MCP** é tool interna da V4 Company (marketing digital, BR) que conecta Google Ads + Meta Ads accounts a Claude/Codex/Cursor via Model Context Protocol. Gestores pedem em PT-BR — _"top 5 campanhas por gasto últimos 7 dias"_, _"pause keywords sem conversão"_ — e o assistente executa via tools curadas read/mutate com governança (audit_log, rate_limit, always-CONFIRM em mutates de blast radius alto, **hard-gate de acesso por conta**).

Interno only, não SaaS, sem terceiros. Substitui Supermetrics.

- **Production:** `https://v4-ads-mcp-299432068772.southamerica-east1.run.app` — projeto GCP **`v4-ads-mcp`** (Wellington é **owner**; migrado 2026-06-30 do antigo `v4-ads-mcp-prod`). Custom domain `mcpv4.fluxocerto.dev.br` pendente (via LB).
- **MCC Google Ads:** `6436352492` (V4 Maceió, 26 client accounts em 04/09)
- **BM Meta Ads:** V4 Lima Soares & Co (`619664032237208`; **24 ad accounts alcançáveis pelo SU** em 19 BMs, verificado 15/08 — via **system-user token all-targets**, Modelo B)
- **Unidade operacional:** V4 Lima Soares & Co (João Pessoa, PB) — Wellington dev + 3 colaboradores futuros
- **Admin:** `wellington.ribeiro@v4company.com`

## Stack

Python 3.13 (`.python-version`; `requires-python >=3.12,<3.14`) · FastAPI + Jinja2 + Tailwind (CSS gerado offline) + HTMX 2 · `mcp>=1.2.0` Streamable HTTP · `google-ads>=27.0.0` (v24) · `facebook-business>=21.0.0` · Supabase Postgres via `asyncpg` (raw SQL, no ORM) · Cloud Run (`southamerica-east1`) · GitHub Actions + WIF · pytest + testcontainers + `respx`/`freezegun` · ruff + mypy strict. Sem build step no runtime nem no deploy — o CSS do Tailwind é **gerado offline** (`python scripts/build_tailwind.py`, pin 3.4.17) e **commitado** em `src/web/static/v4-tailwind.css`, com guard de diff no CI.

## Estado atual

**2026-09-21.** Produção em `https://v4-ads-mcp-299432068772.southamerica-east1.run.app`,
**68 MCP tools** (62 Google + 6 Meta), CI gated + deploy automático. Catálogo até **F192**. **Detalhe, pendências e decision gates vivem em
[`estado-atual.md`](docs/operacao/estado-atual.md)** — atualize AQUELE no fecho, não este.

**Sabe de cara:**

- `gcloud` pode estar **sem credencial válida** — confirme antes de tarefa de infra, e
  **nunca com `2>/dev/null`**: ele tenta pedir reautenticação e pendura em silêncio.
- **A reconciliação Meta REVOGA** (`META_RECONCILE_APPLY=true` desde 09/09; já revogou em
  produção). O lado **Google** é que segue em soak (`GOOGLE_RECONCILE_APPLY=false`) —
  observa e conta, não revoga. Ver a pendência do `estado-atual.md` antes de virar.
- Fase 2B (tombstone dos 8 reports antigos) segue **travada** no soak — não tombstonar.
- **Tool nova só aparece pra sessão nova** (F140): o catálogo é negociado no handshake do
  MCP, e o sintoma é a tool "não existir", não um erro de versão. Reconecte antes do smoke.
- **Buckets** (PR #32, 04/09): 22 always + 46 defer; **próxima remedição em 04/10**, com
  o método, em [`tool-buckets-2026-09-04.md`](docs/operacao/tool-buckets-2026-09-04.md).
- **Docker parado ≠ Docker travado:** os processos do Desktop sobem e ainda assim não há
  engine se o serviço `com.docker.service` estiver `Stopped` (exige elevação).
- Varredura fechada em 18/09: **7 frentes, F155–F179**. Abertos: **F178** (callback OAuth
  sem CSS — `<style>` inline barrado pela CSP). **F179** fechou em 21/09, junto do
  **F191** (seis superfícies onde ausência de medição virava zero/sucesso).
  **F180 em parte:** o Google engole operação
  impossível em vez de errar, então `failed_count` é sempre zero — leia `efeito`.

## Context bootstrap

**Este arquivo basta pra maioria das tarefas.** Ele carrega em toda sessão, então só
tem o que serve a toda sessão: o que o projeto é, como verificar e commitar, e os
tripwires do `Don't do`. O resto é roteado — carregue sob demanda:

| Vai mexer em… | Leia |
|---|---|
| executores Google/Meta, gate de acesso, pool, observabilidade | [`convencoes/nucleo.md`](docs/convencoes/nucleo.md) — tripwires da área vivem lá |
| `src/web/` — templates, CSP, Tailwind, HTMX | [`convencoes/painel.md`](docs/convencoes/painel.md) — tripwires da área vivem lá |
| escrever teste, shippar tool nova | [`convencoes/testes.md`](docs/convencoes/testes.md) — tripwires da área vivem lá |
| query, repository, migration, janela de data | [`convencoes/dados.md`](docs/convencoes/dados.md) — tripwires da área vivem lá |
| planejar trabalho, procedimento operacional raro | [`convencoes/processo.md`](docs/convencoes/processo.md) — tripwires da área vivem lá |
| adicionar dependência, mexer em deploy ou rollback | [`convencoes/processo.md`](docs/convencoes/processo.md) |
| estado de produção, pendências, decision gates | [`operacao/estado-atual.md`](docs/operacao/estado-atual.md) |
| infra, DR, alertas | [`infra-setup.md`](docs/operacao/infra-setup.md) · [`backup-restore-runbook.md`](docs/operacao/backup-restore-runbook.md) |
| roadmap Meta / Fase 2B | [`specs/`](docs/superpowers/specs/) |

**Antes de desenhar ou corrigir código**, faça busca **dirigida** em
[`findings-catalog.md`](docs/operacao/findings-catalog.md) pela área ou sintoma — **F1–F192, ~5300 linhas, 545 KB**. Grep por palavra-chave (`GAQL`, `pool`, `Meta`, `audit`, `CSP`); ler
integral não cabe em contexto nenhum. Cada entrada corrigida traz o que foi feito **e o que ficou deliberadamente de fora**.

A última sessão de cada frente está em `docs/operacao/session-*-handoff.md`; o handoff é o
mapa da sessão, o catálogo é a enciclopédia dos bugs.

Não grep `docs/_archive/` — é histórico (runbooks de sprint, dogfoods, specs e planos
antigos). Abra um arquivo de lá só quando um link vivo apontar para ele.

## Conventions

> Convenção por área vive em [`docs/convencoes/`](docs/convencoes/) — veja a tabela de
> roteamento acima. Aqui ficam só as duas que **toda** sessão usa: como verificar e como
> entregar. A taxonomia completa dos bugs está em
> [`findings-catalog.md`](docs/operacao/findings-catalog.md).

### Verification cadence (always before commit)


```bash
python scripts/check_pre_push.py        # ~50s: ruff + format + mypy + unit + integração NÃO-DB + sync do Tailwind (pula sem Node). Sem Docker.
python scripts/check_pre_push_full.py   # opt-in: + pytest -m integration via testcontainers (~60-90s, Docker)
```

`check_pre_push.py` **NÃO roda os integration tests (testcontainers/DB)** — bugs de SQL/JOIN/cursor/transação só aparecem no CI (8min). Use o full sweep (Docker) ao mexer em queries/mutate/`_common`/migrations, OU aceite o CI como validador e corrija forward confirmando via `gh run view`.

### Git workflow + deploy


Solo dev on `main` (admin bypass). Commits: `feat(scope): …` / `fix(scope): …` / `docs(scope): …` / `chore: …`. Scopes: `web`, `admin`, `auth`, `db`, `mcp`, `meta_ads`, `ci`, `design-system`, `security`. Co-author trailer com Claude.

`git push origin main` → **CI roda; o Deploy é GATED** (desde 07-02): `ci.yml` job `test` → se verde, job `deploy` (`needs: test`, `uses: ./.github/workflows/deploy.yml` reusable) roda no MESMO commit (Buildpacks → **migrations Cloud Run Job** [F66 resolvido, `/cnb/process/migrate`] → deploy → route-to-latest → smoke `/health?deep=1`+`/mcp` 401 → rollback-on-failure com guard). NÃO há mais workflow "Deploy" standalone; o deploy aparece como job dentro do run do CI. Break-glass manual: `workflow_dispatch` no `deploy.yml`. **Confirme via `gh run view <id> --json conclusion` — NUNCA pelo exit code de `gh run watch` (engana).** Force secret novo: `gcloud run services update v4-ads-mcp --region=southamerica-east1 --update-secrets="<NAME>=<secret>:latest"` — mas adicione o secret também ao `--set-secrets` do `deploy.yml` (senão o próximo deploy o apaga).

## Tools available (this Claude session)


- **gcloud** authed `wellington.ribeiro@v4company.com`, **owner** do projeto `v4-ads-mcp` (pós-migração 2026-06-30) — lê/grava secrets, Cloud Run, jobs, rollback direto (`--project=v4-ads-mcp`). `git push` → deploy (WIF/`GCP_DEPLOY_SA`). Antigo `v4-ads-mcp-prod` ainda existe sem owner (a decomissionar).
- **gh** authed `BadWolf1509`.
- **Secret Manager:** `gcloud secrets versions access latest --secret=<NAME> --project=v4-ads-mcp` (owner — funciona). **10 secrets montados** no serviço: `database-url`, `aes-master-key`, `session-signing-key`, `google-oauth-client-id`, `google-oauth-client-secret`, `google-ads-developer-token`, `google-ads-login-customer-id`, `meta-app-id`, `meta-app-secret`, `meta-system-user-token`. Os 3 `supabase-*` **saíram em 08-15** (F95: eram required em Settings sem nenhum leitor) — seguem existindo no Secret Manager, mas não são montados nem lidos; não os reponha. Guard `test_deploy_env_matches_settings.py` cruza as duas direções: env montado sem campo, e campo obrigatório sem montagem.
- **No psql no Windows** — `python+asyncpg` pra DB direto. **Docker** pode não estar rodando — testcontainers falham local, CI roda.
- **Supabase MCP** + **Meta MCP oficial** (`ads_get_field_context` pra validar fields Meta) em config. **Claude in Chrome** disponível pra smoke visual.
- **Hooks:** PostToolUse auto-format ruff em .py + PreToolUse guard contra editar migration commitada. PowerShell pipe converte LF→CRLF mesmo binary (F47).

## Padrão de solução


**A solução entregue aqui é a prática consolidada do mercado para aquele problema — não a que fecha o ticket.** Antes de propor, **nomeie o padrão** que está usando (reconciliation loop, soft delete, idempotência, circuit breaker, JML/deprovisionamento, outbox…) e por que ele se aplica. Estar inventando um mecanismo novo é sinal de que o padrão conhecido não foi procurado.

É gambiarra — e não entra — o que resolve o sintoma e cria trabalho novo. Cinco testes que a pegam:

1. **Depende de alguém lembrar.** Processo humano no lugar de mecanismo é dívida com juros (o offboarding manual do F128 durou dois meses assim).
2. **Duplica estado.** Mesmo dado com duas fontes de verdade diverge — a pergunta certa é qual é a autoritativa e quem reconcilia.
3. **Só descreve o caminho feliz.** Sem resposta pra leitura parcial, retry, concorrência e ordem de eventos, o desenho não está pronto (F85, F93).
4. **Não é reversível nem auditável.** Ação automática que destrói estado sem trilha e sem caminho de volta é pior que ação nenhuma.
5. **Fecha sem guard.** Fix sem teste que falhe contra o código pré-fix não fica fechado (F86 → F109).

Quando o padrão de mercado custar caro demais para o momento, **apresente o trade-off e deixe a decisão com o Wellington** — o que não pode é escolher a gambiarra em silêncio.

## When in doubt


- **Feature nova?** `superpowers:brainstorming` ANTES de codar. **Spec pronta?** `writing-plans`. **Plano pronto?** `subagent-driven-development`. **Bug?** `systematic-debugging`.
- **Lib/SDK?** `plugin:context7:context7` (training data stale, esp. facebook_business + Meta Graph quirks).
- **F-finding?** `/findings-add`. **Quality audit?** `mcp-tool-quality-reviewer` subagent. **Smoke runbook?** `smoke-runbook-generator` subagent.

## Don't do


- Don't confiar em guard que passou de primeira: verifique contra o código PRÉ-fix (sabotagem ou cópia — **nunca `git checkout`**, que descarta trabalho não commitado). E don't asserir o ADJACENTE à invariante: se a asserção não distingue código bom de quebrado, ela não é guard. Os modos e os exemplos medidos estão em `docs/convencoes/testes.md`.
- Don't pôr pipe entre o gate e o `&&`: o exit code de um pipeline é o do ÚLTIMO comando, então `check_pre_push.py | tail && git commit` **não é gate** e já deixou passar commit com gate vermelho (02/09; a variante com `grep` já tinha acontecido antes). Rode mudo e leia `$?`. Don't push sem `python scripts/check_pre_push.py` antes. Full sweep MANDATORY ao mexer em pré-flight de mutate, queries com JOIN/cursor, ou migrations.
- Don't confiar no exit code de `gh run watch` — confirme via `gh run view <id> --json conclusion`.
- **Don't agendar smoke de tool que muta sem o gestor presente:** o classificador de auto mode recusa a chamada, e a alavanca e **autorizacao humana explicita na sessao dele** — aval relayado por outra sessao Claude nao passa. Nem dry-run nem conta de teste isentam: medido 3x (04/09 e 20/09), sempre passando na SEGUNDA tentativa. E o aval precisa preceder a **TENTATIVA**, nao o pedido: em 20/09 ele veio antes da chamada e o freio disparou igual. Tente, leve a recusa ao gestor, repita. A leitura "o freio reage ao nome da tool" foi **RETIRADA**: se fosse o nome, a 2a teria sido barrada igual.
- **Don't tomar "sem checks" de PR empilhado por CI verde:** o `ci.yml` só dispara em `pull_request` contra `main`, então PR cuja base é outra branch **não roda CI nenhum** — e a ausência se parece com "ainda enfileirado". Reapontar a base depois também não dispara: isso é evento `edited`, e os tipos padrão são `opened`/`synchronize`/`reopened`. O que dispara é `git merge origin/main` dentro da branch e push (conta como `synchronize`) — nunca force-push, que descarta o histórico do outro. Medido em 04/09 no #32, empilhado sobre o #31.
- Don't modificar dados de produção via SQL cru sem extremo cuidado (Python script + BEGIN/COMMIT + idempotência).
- Don't pular `superpowers:brainstorming` antes de trabalho criativo mesmo que pareça simples.
- Don't upload secret via pipe PowerShell — arquivo binary intermediário (F47); NUNCA cole secret em chat.

**Os tripwires de área saíram daqui em 22/09 e vivem com a convenção da área.**
Acima ficaram só os que disparam onde nada roteia — shell, git, CI, segredo,
autorização, processo. Se você vai mexer numa destas áreas, **as regras dela
estão no arquivo roteado**, não aqui:

| área | arquivo | o que mora lá |
|---|---|---|
| painel, CSS, template, HTMX, CSP, a11y | [`convencoes/painel.md`](docs/convencoes/painel.md) | 12 regras |
| executor, gate, pool, SDK, envelope de mutate | [`convencoes/nucleo.md`](docs/convencoes/nucleo.md) | 11 regras |
| query, transação, janela de data, fuso | [`convencoes/dados.md`](docs/convencoes/dados.md) | 4 regras |
| teste, mock, probe de API externa | [`convencoes/testes.md`](docs/convencoes/testes.md) | 5 regras |
| dependência, deploy, rollback, sprint | [`convencoes/processo.md`](docs/convencoes/processo.md) | 5 regras |
