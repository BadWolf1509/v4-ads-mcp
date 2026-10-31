# V4 Ads MCP — agent context

Auto-loaded by Claude Code. Read first.

**V4 Ads MCP** é tool interna da V4 Company (marketing digital, BR) que conecta Google Ads + Meta Ads accounts a Claude/Codex/Cursor via Model Context Protocol. Gestores pedem em PT-BR — _"top 5 campanhas por gasto últimos 7 dias"_, _"pause keywords sem conversão"_ — e o assistente executa via tools curadas read/mutate com governança (audit_log, rate_limit, always-CONFIRM em mutates de blast radius alto, **hard-gate de acesso por conta**).

Interno only, não SaaS, sem terceiros. Substitui Supermetrics.

- **Production:** `https://v4-ads-mcp-299432068772.southamerica-east1.run.app` — projeto GCP **`v4-ads-mcp`** (Wellington é **owner**; migrado 2026-06-30 do antigo `v4-ads-mcp-prod`). Custom domain `mcpv4.fluxocerto.dev.br` pendente (via LB).
- **MCC Google Ads:** `6436352492` (V4 Maceió, 26 client accounts em 04/09)
- **BM Meta Ads:** V4 Lima Soares & Co (`619664032237208`; **24 ad accounts alcançáveis pelo SU** em 19 BMs, verificado 15/08 — via **system-user token all-targets**, Modelo B)
- **Unidade operacional:** V4 Lima Soares & Co (João Pessoa, PB) — Wellington dev + gestores da unidade
- **Admin:** `wellington.ribeiro@v4company.com`

## Stack

Python 3.13 (`.python-version`; `requires-python >=3.12,<3.14`) · FastAPI + Jinja2 + Tailwind (CSS gerado offline) + HTMX 2 · `mcp>=1.2.0` Streamable HTTP · `google-ads>=27.0.0` (API v25) · Meta Graph v25 (HTTP direto) · Supabase Postgres via `asyncpg` (raw SQL, no ORM) · Cloud Run (`southamerica-east1`) · GitHub Actions + WIF · pytest + testcontainers + `respx`/`freezegun` · ruff + mypy strict. Sem build step no runtime nem no deploy — o CSS do Tailwind é **gerado offline** (`python scripts/build_tailwind.py`, pin 3.4.17) e **commitado** em `src/web/static/v4-tailwind.css`, com guard de diff no CI.

## Estado atual

Produção, contagens, pendências, o que aguarda deploy e decision gates vivem em
[`estado-atual.md`](docs/operacao/estado-atual.md) — atualize AQUELE no fecho, não este.

**Sabe de cara:**

- `gcloud` pode estar **sem credencial válida** (perde durante a noite) — confirme antes de
  tarefa de infra, e **nunca com `2>/dev/null`**: ele tenta reautenticar e pendura em silêncio.
- **As duas reconciliações REVOGAM** acesso de conta que sai do MCC/BM; churn sozinho não revoga. Detalhe em `convencoes/processo.md`.
- Fase 2B (tombstone dos 8 reports antigos) segue **travada** no soak — não tombstonar.
- **Tool nova só aparece pra sessão nova** (F140), e parâmetro novo pede conversa nova: o catálogo vem do handshake. Reconecte antes do smoke e prove chamando, não lendo o schema. Detalhe em `convencoes/processo.md`.
- **Docker** para o full sweep: se o engine não responde, abra o Docker Desktop (o engine sobe em
  ~15 s mesmo com `com.docker.service` em `Stopped`, medido em 29/09).
- **F180 em parte:** o Google engole operação impossível em vez de errar, então `failed_count`
  é sempre zero — leia `efeito`.

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
| adicionar dependência, mexer em deploy ou rollback | [`convencoes/processo.md`](docs/convencoes/processo.md) — tripwires da área vivem lá |
| estado de produção, pendências, decision gates | [`operacao/estado-atual.md`](docs/operacao/estado-atual.md) |
| infra, DR, alertas | [`infra-setup.md`](docs/operacao/infra-setup.md) · [`backup-restore-runbook.md`](docs/operacao/backup-restore-runbook.md) |
| roadmap Meta / Fase 2B | [`specs/`](docs/superpowers/specs/) |

**Antes de desenhar ou corrigir código**, faça busca **dirigida** em
[`findings-catalog.md`](docs/operacao/findings-catalog.md) pela área ou sintoma — **F1–F203, ~6000 linhas, 601 KB**. Grep por palavra-chave (`GAQL`, `pool`, `Meta`, `audit`, `CSP`); ler
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
D:/v4-ads-mcp/.venv/Scripts/python.exe scripts/check_pre_push.py        # ~150s: ruff + format + mypy + unit + integração NÃO-DB + sync do Tailwind (pula sem Node). Sem Docker.
D:/v4-ads-mcp/.venv/Scripts/python.exe scripts/check_pre_push_full.py   # opt-in: + pytest -m integration via testcontainers (Docker)
D:/v4-ads-mcp/.venv/Scripts/python.exe -m pytest tests/browser          # cliques reais em Chromium; o gate não roda, o CI roda
```

`check_pre_push.py` **NÃO roda os integration tests (testcontainers/DB)** — bugs de SQL/JOIN/cursor/transação só aparecem no CI (8min). Use o full sweep (Docker) ao mexer em queries/mutate/`_common`/migrations, OU aceite o CI como validador e corrija forward confirmando via `gh run view`.

Use o Python do `.venv`: o Controle de Aplicativos do Windows bloqueia o `mypy` compilado do Python global.

### Definição de pronto

Gate verde prova o código, não a entrega. Só diga "pronto" com a prova da linha que se aplica:

| Mudou | Prova |
|---|---|
| painel, template, JS | `tests/browser` + clique em produção |
| query, transação, migration, `_common` | full sweep |
| tool de leitura | chamada real após o deploy; tool nova, em sessão nova |
| tool de mutação | dry-run com o gestor presente |
| deploy, dependência, secret | revisão servindo, `/health?deep=1` e leitura real |

### Relato e autorização

- **Não medido não é zero.** Separe o medido do não medido em todo relato; nunca afirme ausência, cobertura ou fechamento sem a medição.
- **"Analise" e "liste" não autorizam execução.** Perguntas com opções vão em menu (`AskUserQuestion`), uma decisão irreversível por menu.
- **Aval é nominal:** cite a ação exata. Autorizar o trabalho não autoriza merge, deploy ou escrita em produção.

### Git workflow + deploy


Solo dev on `main` (admin bypass). Commits: `feat(scope): …` / `fix(scope): …` / `docs(scope): …` / `chore: …`. Scopes: `web`, `admin`, `auth`, `db`, `mcp`, `meta_ads`, `ci`, `design-system`, `security`. Co-author trailer com Claude.

`git push origin main` → **CI roda; o Deploy é GATED** (desde 07-02): `ci.yml` job `test` → se verde, job `deploy` (`needs: test`, `uses: ./.github/workflows/deploy.yml` reusable) roda no MESMO commit (Buildpacks → **migrations Cloud Run Job** [F66 resolvido, `/cnb/process/migrate`] → deploy → route-to-latest → smoke `/health?deep=1`+`/mcp` 401 → rollback-on-failure com guard). NÃO há mais workflow "Deploy" standalone; o deploy aparece como job dentro do run do CI. Break-glass manual: `workflow_dispatch` no `deploy.yml`. **Confirme via `gh run view <id> --json conclusion` — NUNCA pelo exit code de `gh run watch` (engana).** Force secret novo: `gcloud run services update v4-ads-mcp --region=southamerica-east1 --update-secrets="<NAME>=<secret>:latest"` — mas adicione o secret também ao `--set-secrets` do `deploy.yml` (senão o próximo deploy o apaga).

## Tools available (this Claude session)


- **gcloud** authed `wellington.ribeiro@v4company.com`, **owner** do projeto `v4-ads-mcp` (pós-migração 2026-06-30) — lê/grava secrets, Cloud Run, jobs, rollback direto (`--project=v4-ads-mcp`). `git push` → deploy (WIF/`GCP_DEPLOY_SA`). Antigo `v4-ads-mcp-prod` ainda existe sem owner (a decomissionar).
- **gh** authed `BadWolf1509`.
- **Secret Manager:** `gcloud secrets versions access latest --secret=<NAME> --project=v4-ads-mcp`. Secret novo entra no serviço e no `--set-secrets` do `deploy.yml`; lista em `convencoes/processo.md`.
- **No psql no Windows** — `python+asyncpg` pra DB direto.
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


- **Funcionalidade nova ou mudança de contrato?** `superpowers:brainstorming` ANTES de codar; dispensável em bug com causa medida, bump e documentação. **Spec pronta?** `writing-plans`. **Plano pronto?** `subagent-driven-development`. **Bug?** `systematic-debugging`.
- **Lib/SDK?** `plugin:context7:context7` (training data stale, esp. Meta Graph quirks (a Meta é chamada por HTTP direto; o SDK facebook_business saiu)).
- **F-finding?** `/findings-add`. **Quality audit?** `mcp-tool-quality-reviewer` subagent. **Smoke runbook?** `smoke-runbook-generator` subagent.

## Don't do


- Don't confiar em guard que passou de primeira: verifique contra o código PRÉ-fix (sabotagem ou cópia — **nunca `git checkout`**, que descarta trabalho não commitado). E don't asserir o ADJACENTE à invariante: se a asserção não distingue código bom de quebrado, ela não é guard. Os modos e os exemplos medidos estão em `docs/convencoes/testes.md`.
- Don't pôr pipe entre o gate e o `&&`: o exit code de um pipeline é o do ÚLTIMO comando, então `check_pre_push.py | tail && git commit` **não é gate** e já deixou passar commit com gate vermelho (02/09; a variante com `grep` já tinha acontecido antes). Rode mudo e leia `$?`. Don't push sem `python scripts/check_pre_push.py` antes. Full sweep MANDATORY ao mexer em pré-flight de mutate, queries com JOIN/cursor, ou migrations.
- Don't confiar no exit code de `gh run watch` — confirme via `gh run view <id> --json conclusion`.
- **Don't agendar smoke de tool que muta sem o gestor presente:** só a autorização humana explícita, nesta sessão, destrava o freio de auto mode; aval relayado por outra sessão não passa. Pedido nominal, tentativa, recusa levada ao gestor, nova tentativa. Vale para mudança que deploya comportamento. Detalhe em `convencoes/processo.md`.
- **Don't tomar "sem checks" de PR empilhado por CI verde:** PR com base fora de `main` não roda CI, e reapontar a base não dispara. O que dispara é `git merge origin/main` na branch e push; nunca force-push. Detalhe em `convencoes/processo.md`.
- Don't modificar dados de produção via SQL cru sem extremo cuidado (Python script + BEGIN/COMMIT + idempotência).
- Don't pular `superpowers:brainstorming` em funcionalidade nova ou mudança de contrato, mesmo que pareça simples.
- Don't upload secret via pipe PowerShell — arquivo binary intermediário (F47); NUNCA cole secret em chat.

**Os tripwires de área saíram daqui em 22/09 e vivem com a convenção da área.**
Acima ficaram só os que disparam onde nada roteia — shell, git, CI, segredo,
autorização, dado de produção, verificação e brainstorming. Se você vai mexer
numa destas áreas, **as regras dela estão no arquivo roteado**, não aqui:

| área | arquivo |
|---|---|
| painel, CSS, template, HTMX, CSP, a11y | [`convencoes/painel.md`](docs/convencoes/painel.md) |
| executor, gate, pool, SDK, envelope de mutate | [`convencoes/nucleo.md`](docs/convencoes/nucleo.md) |
| query, transação, janela de data, fuso | [`convencoes/dados.md`](docs/convencoes/dados.md) |
| teste, mock, probe de API externa | [`convencoes/testes.md`](docs/convencoes/testes.md) |
| dependência, deploy, rollback, sprint | [`convencoes/processo.md`](docs/convencoes/processo.md) |
