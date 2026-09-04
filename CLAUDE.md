# V4 Ads MCP — agent context

Auto-loaded by Claude Code. Read first.

**V4 Ads MCP** é tool interna da V4 Company (marketing digital, BR) que conecta Google Ads + Meta Ads accounts a Claude/Codex/Cursor via Model Context Protocol. Gestores pedem em PT-BR — _"top 5 campanhas por gasto últimos 7 dias"_, _"pause keywords sem conversão"_ — e o assistente executa via tools curadas read/mutate com governança (audit_log, rate_limit, always-CONFIRM em mutates de blast radius alto, **hard-gate de acesso por conta**).

Interno only, não SaaS, sem terceiros. Substitui Supermetrics.

- **Production:** `https://v4-ads-mcp-299432068772.southamerica-east1.run.app` — projeto GCP **`v4-ads-mcp`** (Wellington é **owner**; migrado 2026-06-30 do antigo `v4-ads-mcp-prod`). Custom domain `mcpv4.fluxocerto.dev.br` pendente (via LB).
- **MCC Google Ads:** `6436352492` (V4 Maceió, 25 client accounts)
- **BM Meta Ads:** V4 Lima Soares & Co (`619664032237208`; **24 ad accounts alcançáveis pelo SU** em 19 BMs, verificado 15/08 — via **system-user token all-targets**, Modelo B)
- **Unidade operacional:** V4 Lima Soares & Co (João Pessoa, PB) — Wellington dev + 3 colaboradores futuros
- **Admin:** `wellington.ribeiro@v4company.com`

## Stack

Python 3.13 (`.python-version`; `requires-python >=3.12,<3.14`) · FastAPI + Jinja2 + Tailwind (CSS gerado offline) + HTMX 2 · `mcp>=1.2.0` Streamable HTTP · `google-ads>=27.0.0` (v24) · `facebook-business>=21.0.0` · Supabase Postgres via `asyncpg` (raw SQL, no ORM) · Cloud Run (`southamerica-east1`) · GitHub Actions + WIF · pytest + testcontainers + `respx`/`freezegun` · ruff + mypy strict. Sem build step no runtime nem no deploy — o CSS do Tailwind é **gerado offline** (`python scripts/build_tailwind.py`, pin 3.4.17) e **commitado** em `src/web/static/v4-tailwind.css`, com guard de diff no CI.

## Estado atual

**2026-09-03.** Produção em `https://v4-ads-mcp-299432068772.southamerica-east1.run.app`,
**66 MCP tools** (60 Google + 6 Meta), CI gated + deploy automático. Catálogo em **145 IDs**.

**Quantos findings fecharam em qual sprint NÃO vive aqui** — essa narrativa churna toda
sessão e duplica o `estado-atual.md`. Este bloco tem só o que orienta qualquer sessão;
número de tool e contagem de ID se atualizam junto com o `estado-atual.md` no fecho.

**O detalhe vive em [`docs/operacao/estado-atual.md`](docs/operacao/estado-atual.md)** —
estado de produção, pendências abertas, decision gates, quem usa o quê, tokens, IAM.
Volátil por natureza: **atualize aquele arquivo ao terminar a sessão**, não este.

**Sabe de cara:**

- `gcloud` pode estar **sem credencial válida** — confirme antes de qualquer tarefa de infra.
- **A reconciliação Meta sobe DESLIGADA** (`META_RECONCILE_APPLY=false`): observa e conta,
  não revoga. Ver a pendência 1c do `estado-atual.md` antes de virar a chave.
- Fase 2B (tombstone dos 8 reports antigos) segue **travada** no soak — não tombstonar.
- **Tool nova só aparece pra sessão nova** (F140): o catálogo é negociado no handshake do
  MCP, e o sintoma é a tool "não existir", não um erro de versão. Reconecte antes do smoke.
- `ad_schedule` está **entregue** (branch `feat/ad-schedule`: `get_ad_schedule` +
  `update_ad_schedule`), smoke **pendente** — ver
  [`phase-3b-42-ad-schedule-smoke.md`](docs/operacao/phase-3b-42-ad-schedule-smoke.md).
- Próximo sprint candidato: **M.5** (`meta_get_audience_performance` +
  `meta_get_top_creatives`).

## Context bootstrap

**Este arquivo basta pra maioria das tarefas.** Ele carrega em toda sessão, então só
tem o que serve a toda sessão: o que o projeto é, como verificar e commitar, e os
tripwires do `Don't do`. O resto é roteado — carregue sob demanda:

| Vai mexer em… | Leia |
|---|---|
| executores Google/Meta, gate de acesso, pool, observabilidade | [`convencoes/nucleo.md`](docs/convencoes/nucleo.md) |
| `src/web/` — templates, CSP, Tailwind, HTMX | [`convencoes/painel.md`](docs/convencoes/painel.md) |
| escrever teste, shippar tool nova | [`convencoes/testes.md`](docs/convencoes/testes.md) |
| query, repository, migration, janela de data | [`convencoes/dados.md`](docs/convencoes/dados.md) |
| planejar trabalho, procedimento operacional raro | [`convencoes/processo.md`](docs/convencoes/processo.md) |
| estado de produção, pendências, decision gates | [`operacao/estado-atual.md`](docs/operacao/estado-atual.md) |
| infra, DR, alertas | [`infra-setup.md`](docs/operacao/infra-setup.md) · [`backup-restore-runbook.md`](docs/operacao/backup-restore-runbook.md) |
| roadmap Meta / Fase 2B | [`specs/`](docs/superpowers/specs/) |

**Antes de desenhar ou corrigir código**, faça busca **dirigida** em
[`findings-catalog.md`](docs/operacao/findings-catalog.md) pela área ou sintoma — 116 IDs,
~460 linhas. Grep por palavra-chave (`GAQL`, `pool`, `Meta`, `audit`, `CSP`), nunca leitura
integral. Cada entrada corrigida traz o que foi feito **e o que ficou deliberadamente de fora**.

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


- Don't fazer I/O de bookkeeping em `finally` sem `best_effort` — exceção ali descarta o `return` e transforma operação já aplicada em erro (F83). Don't chamar SDK Google fora de `run_blocking` (F86). Don't interpolar texto livre em GAQL sem `gaql_string_literal` (F87). Don't ler `Settings` dentro de primitivo de infra (pool/cliente/logger) — quem serve tráfego injeta (F92).
- Don't confiar em guard que passou de primeira: verifique contra o código PRÉ-fix (sabotagem ou cópia — **nunca `git checkout`**, que descarta trabalho não commitado). E don't asserir o ADJACENTE à invariante: em 02/09 três guards meus passaram verdes porque **enumeravam** filtros em vez de afirmar a propriedade (o que ficou fora da lista passou), asseriam **concordância** em vez de corretude (duas respostas erradas e iguais passam), ou eram verdadeiros **independente da implementação**. Se a asserção não distingue código bom de quebrado, ela não é guard. Aconteceu 3× nesta sessão — grep casando a própria docstring, AST exigindo forma que o codebase não usa, e AST vendo só dict literal quando o call-site monta o dict numa variável.
- Don't envolver em `run_with_reconnect` um bloco que ESCREVE — o retry re-executa a escrita. Separe o read, ou proteja a escrita com `best_effort` (F91). Don't pôr `LIMIT` sem `ORDER BY` num tool que ordena depois (F98/F88). Don't pôr segredo em `params=` de GET (guard AST em `test_no_secrets_in_query_params.py`; use header ou `data=` no POST).
- Don't assertar superfície de API externa por analogia. Teste que codifica a convenção errada é PIOR que teste ausente (aconteceu 3×: F87, F89, e os mocks do F84/F89 que nem conseguiam expressar o bug). Probe empírica primeiro — `validate_gaql` pro Google, `ads_get_field_context` pro Meta.
- Don't pôr pipe entre o gate e o `&&`: o exit code de um pipeline é o do ÚLTIMO comando, então `check_pre_push.py | tail && git commit` **não é gate** e já deixou passar commit com gate vermelho (02/09; a variante com `grep` já tinha acontecido antes). Rode mudo e leia `$?`. Don't push sem `python scripts/check_pre_push.py` antes. Full sweep MANDATORY ao mexer em pré-flight de mutate, queries com JOIN/cursor, ou migrations.
- Don't confiar no exit code de `gh run watch` — confirme via `gh run view <id> --json conclusion`.
- Don't adicionar gate/pré-flight "a todos os executores" sem `grep` TODA função que chama `build_client_for_manager` (F57).
- Don't adicionar recurso externo (CDN/font) sem atualizar `_CSP_POLICY` no mesmo commit (CSP enforcing bloqueia).
- Don't usar `conn.cursor(...)` sem `async with conn.transaction()` (F58); don't deixar coluna sem alias em query com JOIN (F59).
- Don't fazer read idempotente de disponibilidade/hot-path (ex.: resolução de sessão ou deep health) com `pool.acquire()` cru — use `connection.run_with_reconnect(op)` (asyncpg NÃO faz pre-ping; F76/F77). Probe externo deve ter deadline interno menor (`health`: 5s interno < 10s externo). Retry só em read idempotente; mutação NÃO leva retry cego (pode ter commitado). Log Cloud Logging usa `severity` (não `level`) — `add_cloud_logging_severity` já cobre no pipeline JSON.
- Don't mexer em classe utilitária de template sem rodar `python scripts/build_tailwind.py` e commitar o CSS no MESMO commit (o CI faz `git diff --exit-code`). Don't reordenar os `<link>` do `<head>` — `v4-tailwind.css` por último, senão o Preflight perde e todo heading estoura. Don't subir o pin do Tailwind pra v4 (config CSS-first).
- Don't usar `--v4-gray-300` como cor de texto sobre fundo claro (2,1:1) — use `--v4-gray-500`; sobre fundo escuro, marque a linha com `/* on-dark */`. Don't aplicar gzip a `/mcp` (SSE). Don't pôr `{% block head_extra %}` dentro de `{% block content %}`.
- Don't escrever `uv pip compile` sem `--universal` em lugar nenhum (doc, workflow, commit): sem a flag o `pywin32` sai sem marker e o buildpack CNB quebra no Linux (F113). Don't adicionar campo obrigatório em `Settings` sem declará-lo TAMBÉM nos 3 Cloud Run Jobs do `deploy.yml` — eles chamam `get_settings()` e validam tudo na subida (F114); use `--update-*` (merge), nunca `--set-*` (replace), em job cujo estado você não consegue enumerar.
- Don't deduzir a revisão de rollback por ordem de criação — capture a que está servindo ANTES do deploy (F116). Don't deixar check bloqueante só no CI: o gate local tem que cobrir (F115).
- Don't chamar SDK de ads (Google **ou** Meta) fora de um closure passado a `run_blocking` em caminho que atende request — inclui tool que constrói o client sozinho, como `validate_gaql` (F109). Ao offloadar, leia o `request-id` **dentro** do closure: `to_thread` copia o contexto e não devolve.
- **Don't hardcodar fuso ou offset em mutate que grava timestamp no Google** (`-03:00`, `_BRT`): o fuso é `await resolve_account_zone(customer_id)` no dry-run, guardado no payload pendente e mostrado no preview; **sem fuso, recuse** — em escrita, offset chutado é corrupção de dado, não ruído (F146; contraste com o fallback UTC do F141, que é leitura).
- **Don't procurar `REMOVE` no `change_event` para entidade que tem campo `status`** (campanha, grupo, keyword, anúncio): no Google, remover essas entidades é **`UPDATE` de `status → REMOVED`**; `REMOVE` só aparece em vínculos/critérios/orçamentos, que não têm status. Medido por `aggregate_by` em 141 eventos (F145). Predicado de flag olha `new_resource.<entidade>.status`, keyed pelo `resource_type` — não pela presença do atributo, que em proto-plus existe sempre.
- **Don't ler o relógio do servidor em tool Google** (`datetime.now`/`date.today`): `hoje` é `await resolve_account_today(customer_id)`, no fuso da conta, UMA vez por request e passado a tudo (janela, clamp, sonda, freshness). As 25 contas são UTC−3/−4; em UTC todo preset deslizava um dia das 21h à meia-noite (F141). Guard AST em `test_no_server_clock_in_google_tools.py`; exceção só com motivo escrito.
- Don't reportar quota sem dizer QUAL quota: desde o F73 há duas chaves (`mgr:<uuid>` e o dev token), e a menor é a que barra (F110). Don't derivar identificador de auditoria de um dict opcional quando existe kwarg obrigatório com o mesmo dado (F111).
- Don't computar `blast_radius.classify` e ignorar `.level` sem que o caminho fixo esteja amarrado por teste — hoje 17 das 26 tools fazem isso e o guard derivado é o que impede a divergência silenciosa (F112).
- Don't pôr nome acessível (`aria-label`) num elemento que um swap HTMX substitui — o fragmento servido pela rota não tem o texto e o rótulo degrada calado. Aponte pra fora do nó trocado com `aria-labelledby`, derivando os ids do que a rota já recebe (F101, mesma família do F74). Don't referenciar `/static` sem `?v={{ asset_version }}`: o `Cache-Control` é `immutable` por um ano (F102).
- Don't isentar prefixo no `_CSRF_EXEMPT_PREFIXES` — isente **rota**. Prefixo herda tudo que um `APIRouter(prefix=…)` pendurar ali depois, sem revisão (F106).
- Don't devolver 200 de um POST de mutação sem HTMX — 303, senão o refresh re-executa a ação (F107; espelho do F96, que era 303 cru num `hx-post`).
- Don't pôr `role="button"` num `<tr>`: pela ARIA os filhos viram presentacionais e a linha perde o vínculo com os `<th scope="col">`. `tabindex="0"` + `aria-expanded` (suportado em `role=row`) dá o teclado sem isso (F105). Don't deixar `<th>` sem `scope` (F104).
- **Don't escrever JS nem CSS inline em template** (`onclick=`, `hx-on`, `<script>`, `style=`): a CSP não tem `unsafe-*`, então o browser bloqueia — e handler inline morre calado. Use `data-v4-*` + listener em `v4-panel.js`, e classe pro estilo. Vale também pra HTML montado dentro de string Jinja passada a macro (aspas escapadas escondem o atributo de grep).
- Don't fazer macro emitir markup que o consumidor não pode alcançar — `search_input` emitia `name=` enquanto o JS procurava `id=`, e os 4 filtros do painel ficaram mortos sem ninguém notar (F81). Handler inline falha em silêncio.
- Don't adicionar dependência sem checar "no build step" (HTMX via CDN; Tailwind gerado offline — sem node/Vite/React no runtime). Ao adicionar uma dep de PROD: editar `pyproject.toml` E **regenerar `requirements.txt` no MESMO commit** com `uv pip compile pyproject.toml -o requirements.txt --universal` (o `--universal` é obrigatório — sem markers de plataforma o `pywin32` win-only quebra o build Linux/CNB; o buildpack e o CI instalam desse lockfile).
- Don't montar envelope de mutate à mão — use `error_envelope`/`applied_envelope`/`preview_envelope` de `src/mcp/tools/_mutate_common.py` (erro canônico = `error_message`+`operation`; TTL via `DEFAULT_TTL_MINUTES`, nunca literal 10). Novo executor Google → padrão `reserved` (before_call global + `mgr:<uuid>` em transação externa, `record_actual` gated por `reserved`, audit SEMPRE; F73). Rate-limit tem cap por gestor via chave `mgr:<uuid>` em `rate_counters`.
- Don't mover uma função sem `grep` TODOS os patch-sites dela em `tests/` (não só os testes novos) — mock target no namespace antigo dá `AttributeError` só no CI com Docker (classe pre-flight mock-target, fix `dedd82a` 2026-07-04).
- Don't modificar dados de produção via SQL cru sem extremo cuidado (Python script + BEGIN/COMMIT + idempotência).
- Don't pular `superpowers:brainstorming` antes de trabalho criativo mesmo que pareça simples.
- Don't dispatch implementers em paralelo em arquivos OVERLAPPING (reviewers paralelos OK).
- Don't shippar tool sem per-value empirical probe em smoke pra enum whitelist (3b.19A.1 — pegou 10+ design-gaps).
- Don't usar MagicMock em builder tests de proto (use `make_capture_client` — F16/F42/F44).
- Don't incluir `oneOf/allOf/anyOf` em `input_schema` (Anthropic rejeita — 3b.19B.1).
- Don't chamar `FacebookAdsApi.init()`; don't passar `access_token`/`app_id`/`app_secret` direto pro `__init__` — use `FacebookSession` bridge / `build_facebook_ads_api()` (F48).
- Don't aplicar `is_allowed_email` (V4 domain) no callback Meta OAuth — `fb_email` é conta FB pessoal (A6); auth é o manager_id no state HMAC.
- Don't usar `{{ button() }}` em `<form>` sem `type="submit"` (F49).
- Don't retornar `303` cru de um handler chamado por `hx-post` — torne HX-aware (`204`+`HX-Redirect`/`HX-Refresh`, espelha `sessions_revoke`), senão o HTMX injeta a página no `hx-target` (dropdown Managers, 2ª sessão 07-04).
- Don't ecoar `request.query_params` no contexto da macro `alert` (`{{ message|safe }}` = XSS) — mapa fixo código→mensagem. Don't deixar `<table>` fora de contentor de scroll: sem ele a PÁGINA rola na horizontal (F118, +751px em 375). As duas exceções antigas caíram em 08-20 — sticky-head usa `.v4-table-wrap--wide` (scroller só abaixo de 1200px) e o dropdown se desancora sozinho. Contentor novo exige `tabindex="0" role="region" aria-label` (F125); o guard derivado cobra os dois.
- Don't shippar tool Meta com fields novos sem validar via `ads_get_field_context` (F53/F54/F55 — `/insights` vs `/entities`).
- Don't upload secret via pipe PowerShell — arquivo binary intermediário (F47); NUNCA cole secret em chat.
