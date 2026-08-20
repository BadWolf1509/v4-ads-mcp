# Núcleo, execução e provedores

> Executores Google/Meta, gate de acesso, observabilidade, pool. Leia ao mexer em `src/google_ads/`, `src/meta_ads/`, `src/mcp/` ou `src/db/connection.py`.
>
> Extraído do `CLAUDE.md` em 2026-08-19: convenção é estável e específica de
> área, então carregá-la em toda sessão era imposto de contexto. As regras
> curtas (o que faz parar) seguem no `Don't do` do `CLAUDE.md`; aqui fica o
> **porquê**.
>
> Taxonomia completa dos bugs: [`findings-catalog.md`](../operacao/findings-catalog.md).

---

### Autorização por conta (hard-gate) — post sessão 2026-05-29


A matriz `manager_account_access` (Google) / `manager_meta_account_access` (Meta) é **autoritativa na camada MCP**: um gestor só lê/altera contas concedidas (sem bypass por role — admin idem).

- **Google:** `ensure_account_access(conn, *, manager_id, customer_id, session_id, operation_name, level)` em `src/google_ads/access.py` (raise `AccountAccessDeniedError` + audit `status="denied"`) é chamado no TOPO de TODO executor que builda o client: `run_report` (read), `run_mutation`, `run_conversion_upload`, `run_offline_user_data_job`, `run_recommendation_action` (write), e `create_pending` (build/preview), mais **`validate_gaql`** (gated no nível do TOOL — chama `build_client_for_manager` direto, FORA dos executores; era o site esquecido, classe F57). **Guard automatizado desde 07-02** (`tests/unit/test_structural_guards.py`): todo arquivo com `build_client_for_manager(` precisa ter `ensure_account_access(` (allowlist: `client.py`). Ao adicionar call-site, o guard falha se esquecer o gate.
- **Meta:** `run_meta_graph_get(..., ad_account_id, ...)` — `ad_account_id` é kwarg **OBRIGATÓRIO** (desde 07-02/F72) e o gate `can_manager_access` roda **incondicional** (antes era `params.get("ad_account_id")` + `if` = fail-open). Token de execução = system user compartilhado, então a matriz é o ÚNICO freio; guard `test_meta_graph_execution_is_contained` garante que `build_meta_api` só é chamado em `reports.py`. **Negação é SEMPRE auditada** (`status="denied"` fora do `if audit_this_call` — evento de segurança, espelha o Google).

### Meta SDK conventions (post-M.2a/M.2b + Modelo B)


- **Execução = system-user token** (Modelo B, sessão 2026-05-29): `run_meta_graph_get` usa `build_meta_api(system_user_token=settings.meta_system_user_token, …)` em `src/meta_ads/client.py`. `build_meta_api_for_manager` (token pessoal) foi **removido** — o OAuth pessoal é dormante.
- **NUNCA `FacebookAdsApi.init()`** (global state, perigoso em async). Factory `build_facebook_ads_api()` constrói `FacebookSession` primeiro (F48 — `__init__` aceita só `session, api_version, enable_debug_logger`):
  ```python
  session = FacebookSession(app_id=..., app_secret=..., access_token=...)
  api = FacebookAdsApi(session=session, api_version="v22.0")
  ```
- **Audit Meta:** `audit_log.record(... platform="meta", provider_request_id=resp.headers().get("x-fb-trace-id"))`.
- **BUC post-call:** `record_actual_meta()` parseia `X-Business-Use-Case-Usage` → `meta_rate_counters` + throttle warning >75%.
- **2 endpoints, whitelists diferentes (F53/F54/F55):** `/insights` = SÓ metrics (spend, impressions, ctr, cpc, reach, frequency, actions, action_values, purchase_roas); `/campaigns`,`/adsets`,`/ads` = metadata (effective_status, daily_budget, creative_id, …). **Antes de shippar tool Meta com fields novos: use `ads_get_field_context([fields])` do Meta MCP oficial** (configurado em `~/.claude.json`) pra confirmar endpoint + existência — teria evitado F53+F54.
- **Long-lived token (OAuth pessoal, dormante):** Meta pode invalidar server-side antes do expiry natural; handle `to_friendly_meta_error` subcodes 458/467/460/463.

### Pós sessão 2026-06-19 (paginação Meta + GAQL error UX + resync)


- **Paginação da Graph (F61):** todo consumo de edge Meta DEVE seguir `paging.next`. O paginador vive em **`src/meta_ads/graph.py`** (`fetch_paginated`) desde a spec 2026-08-20 — saiu de `src/auth/meta_oauth.py`, que continua expondo `_fetch_all_adaccounts` como wrapper de `/me/adaccounts` por cima dele. Conhecimento que não está em mais lugar nenhum: a Graph pagina em **25/página por default** (o BM da V4 tem 50+ contas, então single-page truncava — o MCP via 12 das 22); pedimos `limit=200` pra caber tudo em uma página no caso normal e ainda assim seguir o cursor quando não couber; o header `Authorization` é reenviado **a cada página** porque a URL de `paging.next` já vem com os params embutidos e o token nunca vai na query (F82); `max_pages` é cerca de segurança, e estourá-lo devolve `complete=False`. NÃO reverter pra single-page, e NÃO duplicar paginação em módulo novo.
- **GAQL error UX (F62):** `to_friendly` em `src/google_ads/errors.py` trata o oneof `query_error` — mantém o campo cru E anexa dica (`list_gaql_resources`/`validate_gaql` + nota que auction insights não existem na GAQL). Clientes LLM (Codex) chutam campos via `run_gaql`; a mensagem enriquecida auto-corrige no próximo turno.
- **`get_change_history` clamp (F63):** `start_date` (preset OU custom) é clampado pro teto de 30 dias com warning em vez de deixar o Google rejeitar; janela inteira fora da retenção → `ValueError` claro.
- **Resync Meta piggyback:** `src/jobs/account_resync.py` chama **`reconcile_meta()`** (`src/jobs/meta_resync.py`) no fim — o job diário (Cloud Run Job `v4-ads-mcp-resync` + Cloud Scheduler) reconcilia `meta_ad_accounts` contra a parceria autoritativa do BM (`client_ad_accounts ∪ owned_ad_accounts`), zero-touch. `/me/adaccounts` NÃO define mais o inventário: alimenta só o sinal `su_reachable`. Secret `META_SYSTEM_USER_TOKEN` e as env `META_BUSINESS_ID`/`META_RECONCILE_APPLY` montados no job via `deploy.yml`. Concessão de grant segue **manual** (Modelo B) — o job só entra/sai do catálogo e revoga (soft) quando a conta sai da parceria. A trava `META_RECONCILE_APPLY` governa **só a destruição**: upsert, carência e alcance escrevem mesmo com ela desligada, senão o dry-run não observa nada (C2). Detalhe: [spec 2026-08-20](../superpowers/specs/2026-08-20-meta-partnership-reconciliation-design.md).
- **Migração de conta + IAM:** a conta admin antiga (owner do GCP) foi excluída → recuperação exigiu re-sync de OAuth/managers/grants. **Lição:** projeto prod sem owner humano = single point of failure (peça 2 owners). A deploy SA é least-privilege (não concede IAM — bom, mas significa sem auto-recuperação). Detalhe: handoff 2026-06-19.

### Pós sessão 2026-06-20 (observabilidade + performance breakdown pattern)


- **Observabilidade + health (Onda 1, F76/F77):** `bind_request_context`/`clear_request_context` estão plugados em `resolve_session_to_context`; `merge_contextvars` propaga `manager_id`/`session_id`; `add_cloud_logging_severity` converte `level`→`severity` no pipeline JSON. `/health?deep=1` executa `SELECT 1` via `connection.run_with_reconnect` com deadline global de 5s (readiness: 200 db=ok / 503 degraded); shallow `/health` segue inalterado. `max_inactive_connection_lifetime=120` é mitigação, não pre-ping.
- **Performance breakdown pattern (M.4 + Fase 2A):** dois tools-**irmãos** de mesma forma `(level, breakdown)` — `get_performance_breakdown` (Google) e `meta_get_performance_breakdown` (Meta). **Google:** módulo puro `src/google_ads/performance_breakdown.py` (`_validate_combo`+`_common_metrics`+`build_performance_breakdown_query`+`parse_performance_row`) ENVOLVE os builders `*_query` de `performance.py`/`tactical.py` (não reescreve). Matriz: `{campaign,ad_group,ad,keyword,audience}`+sem-breakdown OU `account`+`{device,geo,hourly}`; `account`+null → erro apontando `get_account_overview`. bucket=always, `audit_this_call=True`. **Meta:** `src/meta_ads/insights.py` (`build_insights_call(breakdowns=)`); breakdown→param Meta confirmado no smoke (platform→`publisher_platform`, device→`impression_device`, geo→`country`, hourly→`hourly_stats_aggregated_by_advertiser_time_zone`). **Aditivo** — os 8 reports Google antigos seguem vivos até a **Fase 2B** (tombstone pós-soak). Ao consolidar, **paridade bit-a-bit** com o report antigo é requisito (cross-check no smoke). `ads_get_field_context` NÃO cobre breakdowns → validação é smoke-probe per-combo (lição F53/F54/F55).
- **Builder test guard (Onda 0):** `test_builder_tests_use_capture_client_not_magicmock` (`tests/unit/test_tools_schemas.py`) — qualquer `test_*_builder.py` que referencie `MagicMock` SEM importar `make_capture_client` falha (anti-reincidência F16/F42/F44).
- **Guards estruturais (07-02):** `tests/unit/test_structural_guards.py` varre o source pra impedir reincidência: **F57** (`build_client_for_manager(` sem `ensure_account_access(`), **F57-Meta** (`build_meta_api(` fora de `reports.py`), **F58** (`.cursor(` sem `conn.transaction()`). Verificado que F57 dispara quando sabotado. Ao adicionar uma classe de bug recorrente, prefira um guard grep-based aqui em vez de "lembrar de fazer grep manual".

### Núcleo pós 2026-08-15 (invariantes novos — violar quebra guard)


Cinco mecanismos nasceram da investigação de 08-14/15. Cada um tem guard estrutural; o detalhe do porquê está no [handoff](../operacao/session-2026-08-14-15-handoff.md).

- **`best_effort` ([`governance/bookkeeping.py`](../../src/governance/bookkeeping.py)) — todo I/O de bookkeeping em `finally`.** Exceção num `finally` DESCARTA o `return` pendente: sem isso, falha ao gravar audit transformava mutação já aplicada no Google em erro pro gestor (F83). Quota e audit são blocos **independentes** — a falha de um não pode pular o outro.
- **`run_blocking` ([`src/blocking.py`](../../src/blocking.py)) — toda chamada de SDK em caminho que atende request.** Vale pros DOIS provedores: o `facebook_business` usa `requests` por baixo (`FacebookAdsApi.call` não é coroutine — verificado na fonte instalada), e o executor Meta pagina, então são round-trips sequenciais. O guard `test_chamada_bloqueante_sai_do_event_loop` mantém a lista honesta; sem ele, 3 sites ficaram para trás por 5 dias (F109). É gRPC síncrono; no event loop congela a instância inteira, inclusive o `/health` (F86). **Streaming:** offloadar só a chamada não basta — o `for batch in stream` também faz I/O e precisa entrar na função offloaded. **ContextVar não volta da thread:** o `request-id` do interceptor tem que ser lido DENTRO do offload, senão some do audit em silêncio.
- **`gaql_string_literal` ([`queries/_gaql.py`](../../src/google_ads/queries/_gaql.py)) — todo texto livre em GAQL.** GAQL escapa com **barra invertida**, não com doubling de SQL (`''` é rejeitado — verificado contra a API real). A barra é escapada ANTES da aspa; inverter a ordem corrompe o resultado.
- **`Manager.is_deactivated` — todo gate de sessão.** `status` e `is_active` divergem e nada as sincroniza; ler só uma deixava Bearer MCP vivo após offboarding (F84).
- **`record_job_crash` + completude explícita nos jobs.** `record_job_run.status` é **obrigatório** (era o default `success` que mascarava falha). Inventário parcial NÃO alimenta deletion detection — nem no Meta (F93) nem no Google (F85).
- **`run_with_reconnect` em TODO read pré-operação** — os 9 sites quentes (deps do painel, os 5 gates Google, OAuth do client, gate Meta) já estão cobertos (F91). O gate **não** é read puro: a negação escreve audit, e essa escrita fica fora do retry (separada de fato no Meta; via `best_effort` no Google).
- **Backup = 1 snapshot.** `backup.py` roda descoberta + todos os COPYs numa conexão em `REPEATABLE READ`, em stream pro GCS (F94). Tabela por tabela em conexões distintas gera FK órfã e quebra o restore.
- **Teto em read novo:** `limit` no schema + `LIMIT limit+1` no builder (a sentinela alimenta `truncated`), e **`ORDER BY` sempre que o tool ordenar depois** — cortar antes de ordenar é a classe F88 (F98).

**Pool:** `connection.py` NÃO lê `Settings` — primitivo de infra não depende da config da app (isso derrubou a suíte de integração inteira uma vez). Quem serve tráfego (`app.py`) injeta `settings.db_pool_*`; job e script usam o default. O orçamento é **instâncias × pool ≤ teto do banco**, e há teste que verifica a conta.
