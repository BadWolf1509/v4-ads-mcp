# V4 Ads MCP

Ferramenta **interna da V4 Company** que conecta as contas **Google Ads** e **Meta Ads** que a unidade gerencia ao Claude (e outros clientes MCP — Claude Code, Codex CLI, Cursor). O gestor pede em linguagem natural — _"performance da conta X últimos 30 dias"_, _"pause keywords sem conversão"_, _"top campanhas Meta por gasto"_ — e o assistente executa via ferramentas curadas, com governança e auditoria. Substitui o Supermetrics; uso interno, sem terceiros.

- **Produção:** `https://v4-ads-mcp-299432068772.southamerica-east1.run.app`
- **Onboarding (como conectar seu cliente de IA):** [`/help`](https://v4-ads-mcp-299432068772.southamerica-east1.run.app/help)
- **MCC Google Ads:** `6436352492` (V4 Maceió) · **BM Meta:** V4 Lima Soares & Co

## O que faz

- **~64 ferramentas MCP** (Google Ads + Meta Ads) — leitura (performance, search terms, funil, geo/device/hora, auditorias) e mutação (status, lances, orçamento, keywords, RSAs, conversões, audiências…).
- **Governança em toda chamada:** registro no `audit_log` (quem, quando, qual conta, operação, status), rate-limit por token, e **dry-run + confirmação** (`apply_change`) para mutações de blast radius alto.
- **Autorização por conta:** a matriz `manager_account_access` / `manager_meta_account_access` é **enforçada na camada MCP** — um gestor só lê/altera contas que o admin liberou (Google e Meta).
- **Painel web** (FastAPI + HTMX): login Google OAuth (allowlist `@v4company.com`, invite-only), gestão de sessões/tokens MCP, visão das contas acessíveis, audit log com filtros/CSV, e área admin (convites, matriz de acesso, métricas).
- **Segurança:** Bearer por sessão, CSRF (Origin check), CSP enforcing + SRI, security headers, escaping XSS, cookies `httponly/secure/samesite`.

## Stack

Python 3.13 (`.python-version`; `requires-python >=3.12,<3.14`) · FastAPI + Jinja2 + Tailwind (CSS gerado offline e commitado) + HTMX 2 · `mcp` Streamable HTTP · `google-ads` (v24) · `facebook-business` · Supabase Postgres via `asyncpg` (SQL cru, sem ORM) · Cloud Run (`southamerica-east1`) · GitHub Actions + Workload Identity Federation · pytest + testcontainers · ruff + mypy strict.

Sem build step no runtime nem no deploy: o CSS do Tailwind e **gerado offline** (`python scripts/build_tailwind.py`, pin 3.4.17) e **commitado**, com guard de diff no CI. HTMX vem de CDN com SRI. A CSP roda **sem nenhuma diretiva `unsafe-*`**.

## Dev setup

1. Python 3.13 (`pyenv install 3.13` ou via sistema; mínimo 3.12).
2. Venv: `uv venv` (ou `python -m venv .venv`); ative: `source .venv/bin/activate` (Linux/macOS) ou `.venv\Scripts\activate` (Windows).
3. Deps: `uv pip install -e ".[dev]"` (ou `pip install -e ".[dev]"`).
4. Copie `.env.example` → `.env` e preencha os valores (segredos vêm do GCP Secret Manager em produção).
5. App local: `uvicorn src.app:app --reload --port 8080`.

## Verificação (antes de todo push)

```bash
python scripts/check_pre_push.py        # ~50s: ruff + format + mypy + unit + integração não-DB + sync do Tailwind (sem Docker)
python scripts/check_pre_push_full.py   # opcional: + integration via testcontainers (~60-90s, requer Docker)
```

O sweep completo é **obrigatório** ao mexer em fluxos de mutate, helpers de `_common`, ou migrations — `check_pre_push.py` não roda os testes de integração com banco (testcontainers); esses só validam no CI.

## Deploy

`git push origin main` dispara o **CI** (ruff + format + mypy + pytest unit + integration); somente depois do job `test` verde, o job **Deploy** executa build Buildpacks → migrations via Cloud Run Job → deploy do serviço → smoke `/health` + `/mcp` 401. O deploy é gated por `needs: test`. Confirme a conclusão real via `gh run view <id> --json conclusion` (o exit code de `gh run watch` pode enganar).

## Estrutura

```
src/
  app.py                 # factory FastAPI + middlewares (CSRF, security headers) + exception handler
  mcp/                   # servidor MCP (Streamable HTTP), registro de tools, resolução de sessão
  google_ads/            # client + executores (run_report, run_mutation, …) + gate de acesso
  meta_ads/              # client (system user) + executor Graph API + gate de acesso
  governance/            # rate limit + dry-run/confirmação
  auth/                  # OAuth Google + Meta, sessões do painel, allowlist
  db/                    # migrations (append-only) + repositories (asyncpg)
  web/                   # rotas + templates Jinja + design system (static/*.css)
docs/
  convencoes/            # convenção por área de trabalho (carregada sob demanda)
  operacao/              # estado-atual, findings-catalog, sprint-history, runbooks de DR
  superpowers/specs+plans # design docs + planos de implementação
  _archive/              # histórico: runbooks de sprint, dogfoods, specs e planos antigos
```

## Documentação

- **Contexto do agente:** [`CLAUDE.md`](CLAUDE.md) — leia primeiro ao continuar o trabalho. Ele carrega em toda sessão e roteia o resto.
- **Estado de produção, pendências e decision gates:** [`docs/operacao/estado-atual.md`](docs/operacao/estado-atual.md) — é o que se atualiza ao fim de cada sessão.
- **Convenções por área:** [`docs/convencoes/`](docs/convencoes/) — núcleo, painel, testes, dados, processo.
- **Taxonomia de bugs e lições:** [`docs/operacao/findings-catalog.md`](docs/operacao/findings-catalog.md) — 116 IDs; busca dirigida, nunca leitura integral.
- **Cronologia de entregas e sessões:** [`docs/operacao/sprint-history.md`](docs/operacao/sprint-history.md)
- **Infra / DR:** [`docs/operacao/infra-setup.md`](docs/operacao/infra-setup.md) · [`docs/operacao/backup-restore-runbook.md`](docs/operacao/backup-restore-runbook.md)
- **Specs e planos:** [`docs/superpowers/`](docs/superpowers/) · histórico arquivado em `docs/_archive/`

## Repositório

`https://github.com/BadWolf1509/v4-ads-mcp` — solo dev em `main` (admin bypass); CI obrigatório.
