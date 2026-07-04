# Sessão 2026-07-04 — Handoff (investigação 2026-07-03 → 3 ondas shipadas)

> Investigação multi-agente (5 dimensões) + probes do `audit_log`/infra de produção → **3 ondas executadas e mergeadas na main** (`03c78bb..ebd48ce`, ~40 commits, todas CI+Deploy verdes). Governança (incl. 1 bug real F73) + resiliência operacional (a operação passou a *falhar bem*, não só *executar bem*) + dívida técnica. Subagent-driven: cada task teve implementer + review (spec+qualidade); 2 fix-forwards no CI.

## TL;DR

| Onda | Entrega | Commits |
|---|---|---|
| **1 — Governança** | F73 quota leak fix + cap diário por gestor · audit das ações admin do painel · run_gaql `limit`+query no audit · validate_gaql sob rate-limit+audit · purge job diário · resync audita falha | `8ea91f4`, `6bcd145`, `510cd9d`, `22c5311`, `d2c56d3` |
| **2 — Falhar bem** | Alerting GCP (uptime+job-failed+logs) · lockfile `requirements.txt` universal + pip-audit · smoke MCP autenticado no deploy · backup semanal→GCS + runbook · infra-setup pro projeto novo | `40c53f6`, `42c8055`, `613f2d1`, `b2a2ed8`, `2dc3e0d`, `cd8de03`, `97833a1`, `afdf30f` + gcloud one-time |
| **3 — Velocidade & dívida** | test-infra template DB (CI 8min→~1.5min) · `_mutate_common` (dedup 22 mutates + error_message) · dedup trio Meta + BUC via kwarg · dead code/micros/labels/CSV-injection/apply_change · test gaps | `0188b5f`..`ebd48ce` (12 commits) |

Produção verde ao fim de cada onda; `/health?deep=1` db=ok. Backup validado (13 tabelas→GCS). Smoke MCP autenticado validado contra prod (registry 71 tools).

## Onda 1 — Governança & o bug

- **F73 (quota leak) — bug real confirmado + corrigido** (`510cd9d`, catalogado): nos executores Google (`run_report`/`run_conversion_upload`/`run_offline_user_data_job`), `before_call` ficava DENTRO do `try` e levantava `QuotaExhausted` ANTES de persistir a reserva; o `finally` reconciliava `record_actual(actual_ops=0, estimated_ops=N)` → delta `-N` incondicional → **cada chamada bloqueada no teto liberava quota pra próxima** (cap diário virava soft cap). `run_mutation` era imune por acidente. Fix: flag `reserved` (before_call em transação EXTERNA, `record_actual` gated por `reserved`, audit SEMPRE). Mesmo diff adicionou **cap diário por gestor** (2ª chave `mgr:<uuid>` em `rate_counters`, `daily_limit=settings.manager_daily_quota` default 5000) — antes o rate-limit era só global no dev-token. **Nota operacional:** `MANAGER_DAILY_QUOTA` não está setado no Cloud Run (usa 5000) — monitorar `rate_counters WHERE developer_token_id LIKE 'mgr:%'` na 1ª semana.
- **Audit das ações admin do painel** (`6bcd145`): os 10 handlers de mutação de `routes.py` (toggle role/active, grant/revoke/bulk Google+Meta, invites) não gravavam `audit_log` — a matriz de acesso (o ÚNICO freio no Meta) mudava sem rastro. Helper `_audit_admin`, `action_type="mutate"`, `operation="admin_*"`.
- **run_gaql `limit` + query no audit** (`22c5311`): o tool nº 1 (220 calls/14d) não tinha `limit` (truncava em 1000 hardcoded — classe F2/F22) e auditava com `params_summary=None`. Agora `limit` (default 100, max 1000) + `truncated:true`/hint + a query (800 chars) no audit. **validate_gaql** passou pra sob o padrão `reserved` (validate_only consome quota Google) + audita sempre.
- **Purge diário** (`8ea91f4`): `src/jobs/purge.py` deleta `pending_confirmations` (>7d) e `rate_counters`/`meta_rate_counters` (>90d), acoplado ao resync, best-effort + auditado. **`audit_log` NUNCA é purgado** (decisão de compliance). Resync agora audita falha (`status="error"` antes do exit 1).

## Onda 2 — Falhar bem (a operação só sabia *executar*, não *detectar/recuperar*)

- **Alerting** (gcloud one-time, REST Monitoring API — o componente `gcloud alpha monitoring` não instala local): canal e-mail Wellington + uptime check `/health?deep=1` (contentMatcher `"db":"ok"`) + policy de **Cloud Run Job failed** (cobre resync/migrate/backup) + policy log-based `severity>=ERROR`. Antes: **ZERO** alerting no projeto novo. IDs no `infra-setup.md`.
- **Lockfile** (`613f2d1`, `97833a1`): `requirements.txt` pinado (`uv pip compile`) instalado pelo buildpack CNB + CI (fecha a janela "CI testou vX, deploy rodou vY" — classe F51) + `pip-audit` non-blocking. **LIÇÃO (fix-forward):** a 1ª versão quebrou o CI no Linux (`pywin32` win-only sem marker) — **gerar SEMPRE com `--universal`** (markers de plataforma). O gate barrou o deploy corretamente.
- **Smoke MCP autenticado** (`2dc3e0d`): o smoke do deploy só via `/health` e `/mcp` 401. Agora um POST `/mcp` autenticado (`tools/list`, Bearer de manager smoke SEM grants em `SMOKE_MCP_BEARER`) exige o registry montado — prova o stack MCP ponta a ponta (classe F58). Comando `create-manager` novo no `admin.py` (restrito a gestor após review — `--role admin` era footgun).
- **Backup** (`40c53f6` + gcloud): `src/jobs/backup.py` dumpa cada tabela → csv.gz → `gs://v4-ads-mcp-backups` (lifecycle 90d); Cloud Run Job `v4-ads-mcp-backup` + scheduler semanal (dom 05:00 BRT). Runbook: [`backup-restore-runbook.md`](backup-restore-runbook.md). **LIÇÃO (fix-forward):** o job precisa do secret set COMPLETO (não só `DATABASE_URL`) — `get_settings()` valida o Settings inteiro na subida. Validado: 13 tabelas→GCS, CSV bem-formado.

## Onda 3 — Velocidade & dívida

- **Test-infra template DB** (`0188b5f`+`51c84b5`): container Postgres session-scoped + `CREATE DATABASE ... TEMPLATE tpl_app` por teste (migrations rodam 1× no template). **CI DB step: ~8min → ~45-90s.** 44 arquivos perderam a fixture local redundante; convenção nova no CLAUDE.md ("consuma `pg`/`db`/`client` do conftest; NÃO redeclare"). 2 arquivos especiais legítimos (admin_script DSN cru, meta_list registry).
- **`_mutate_common`** (`8fa0ead`+`4e84fab`): 3 helpers (`error_envelope`/`applied_envelope`/`preview_envelope`) deduplicam o bloco dry-run/apply copiado em 22 tools (~900 linhas), com `DEFAULT_TTL_MINUTES` centralizado. **Envelope de erro canônico `error_message`** (+ `operation`) nos ~18 tools Google que usavam `"error"` + no `apply_change` (a última divergência). Paridade de contrato verificada tool a tool (opus).
- **Dedup trio Meta + BUC** (`4969fca`+`52d0ca5`): `meta_get_campaign/ad_set/ad_performance` (90-92% idênticos) → núcleo `_meta_performance.run_meta_level_performance`. **3.4:** o BUC gravava só se `"ad_account_id" in params` — funcionava por um param espúrio injetado em `insights.py`; agora usa o kwarg obrigatório (pós-F72), param removido. +12 testes do executor Meta (antes zero). **LIÇÃO (fix-forward `dedd82a`):** a dedup moveu `run_meta_graph_get` pro núcleo, mas os 10 patch-sites dos integration tests existentes apontavam pro namespace antigo → `AttributeError` no CI (só com Docker). **Refactor que move função → grep TODOS os patch-sites, não só os testes novos** (classe pre-flight mock-target).
- **3.5 miúdos (SUBSET)** — o agente foi cortado por limite de sessão; **feitos e verificados um a um pelo controller** (`e8b8ffe`/`e8aee43`/`7e9888b`/`ebd48ce`): dead code (managers/meta_rate_counters/audit_log.summary_stats/parse_meta_ad_account_id), `micros_to_currency` (3 audits sem round + bulk_pause), labels→`src/meta_ads/labels.py`, add_negative ecoa `resource_names` (F13), CSV formula-injection (`_csv_safe`), apply_change `error_message`.
- **3.6 test gaps** (`afcc7c7`+`4b51aea`): handler 3xx/JSON/HTML de `app.py`, `test_google_errors`, `test_logging_context` (bind contextvars), run_recommendation_action happy path, `current_manager` (deps), `test_admin_script`, GAQL builders de performance/tactical. Zero bug encontrado.

## Pendências / follow-ups (deferidos da 3.5 — não feitos)

Follow-up limpo (baixo valor/risco, cortados por limite de sessão):
1. **Sync Meta pro domínio + token no header** — mover `_fetch_all_adaccounts`/`_to_payload` de `auth/meta_oauth.py` pra `src/meta_ads/sync.py` + `access_token` de query param pra header `Authorization`. Risco: toca o job de resync de prod (validar rodando 1×).
2. **GAQL escaping** `''`→`\'` em `_common.py` (nomes de ConversionAction/geo). Contido à conta autorizada.
3. **OAuth logs sem body** (`oauth.py`/`meta_oauth.py` — não logar `resp.text` na falha de token).
4. **Guard de migrations DB-less** (mover a lista esperada pra constante + unit test comparando com o glob).
5. **Pool config** (`db_pool_min/max` em Settings) + `--concurrency=80→40` no deploy.yml.
6. **Doc-drift** `pt`→`pt-BR` em `create_and_link_assets` + NOTE→`TODO(standard-access)` em `get_my_rate_limit_status`.

Follow-ups do review (fora de escopo das tasks): `meta_get_account_overview`/`breakdown` têm o mesmo param espúrio + msg "não encontrada" inline (não migrados pro núcleo); `parse_insights_row` lê campos F54-removidos (sempre None, pré-existente).

**Ações humanas pré-existentes (não tocadas nesta sessão):** cutover lucas+anderson, decomissionar `v4-ads-mcp-prod` (exige Org Admin V4 — Wellington sem acesso), F67 custom domain, atualizar as 4 skills claude.ai pra `get_performance_breakdown`, checkpoint Meta, contas Meta faltantes no BM.

## Verificação
Todas as ondas: `check_pre_push` verde local + CI test+deploy verde no MESMO commit (`gh run view --json conclusion`). Prod `/health?deep=1` db=ok ao fim de cada onda. Backup executado 1× (bucket OK). Smoke MCP autenticado validado. Findings: **F73** catalogado.
