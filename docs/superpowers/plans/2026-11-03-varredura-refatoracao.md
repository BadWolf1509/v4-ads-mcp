# Varredura de refatoração de 03/11 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Corrigir os 3 bugs e executar as refatorações e limpezas apontadas pela varredura de 03/11, mais as duas decisões do Wellington, sem mudar comportamento além do que cada task declara.

**Architecture:** Oito partes independentes, **uma por PR**, nesta ordem: A (bugs) → B (cota Google) → C (limpezas Google) → D (Meta) → E (OAuth pessoal Meta) → F (painel) → G (tools MCP) → H (jobs e testes). Cada parte sai de `main` atualizado, passa pelo gate (e pelo full sweep quando indicado) e só é mesclada com o aval nominal do Wellington. Refatoração é estrutural: o teste existente é a rede, e onde não houver rede a task escreve teste de caracterização **antes** de mexer.

**Tech Stack:** Python 3.13, asyncpg, FastAPI + Jinja2 + HTMX, `google-ads` 33.0.0 (API v25), Meta Graph v25 via httpx, pytest + testcontainers.

**Spec:** não há documento de spec. A origem são os achados da varredura de 03/11 (quatro varreduras só de leitura, com os 3 bugs reconferidos no código) e as decisões do Wellington em 03/11: **remover** o OAuth pessoal da Meta, mantendo o `data-deletion-callback`; **manter** `mark_inactive_except`, marcada como uso de emergência. As rulings sem spec são provisórias e vão no ledger.

## Global Constraints

- Gate antes de todo commit, sem pipe: `D:/v4-ads-mcp/.venv/Scripts/python.exe scripts/check_pre_push.py > log 2>&1 && git add ... && git commit ...`.
- Full sweep (`scripts/check_pre_push_full.py`, Docker) obrigatório nas partes B, C, E, G e H (executor, query, `_common`, transação, repositório).
- Guard novo só vale com sabotagem conferida contra o código pré-fix; **nunca `git checkout`** para isso (cópia ou edição reversa).
- Gate `ensure_account_access` continua **no topo de cada executor**, fora de `try` e fora de helper (guard `test_structural_guards.py`).
- `run_with_reconnect` só envolve leitura; quota e audit são blocos `best_effort` **independentes**; reservas de cota numa transação **externa** (F73, F83, F91).
- `run_meta_graph_get` segue o único construtor de cliente HTTP da Graph (`test_meta_graph_execution_is_contained`).
- Migration commitada não se edita. A coluna `rate_counters.developer_token_id` mantém o nome.
- Mensagens ao gestor em PT-BR. Nenhum dado de cliente em arquivo (repo público).
- Template com classe utilitária nova: `python scripts/build_tailwind.py` no mesmo commit.
- Rotas: ordem e nomes preservados (`tests/unit/fixtures/tabela_de_rotas.json`); mudança deliberada atualiza o fixture no mesmo commit, com o motivo.
- Fora deste plano, por decisão registrada: os 8 reports antigos da **Fase 2B** (travada no soak); a divisão de `recommendations.py`; `accounts.html` × `accounts_meta.html` (filas divergem de verdade); os checks de `limit` repetidos nas tools Meta (defensivos, como o `run_gaql` documenta).
- Escrever sem ler: o shell do Windows altera barra invertida em heredoc. Edição de arquivo com `\` usa o editor, não heredoc.

## Review Focus

1. Negação de acesso em qualquer executor Google: exatamente **uma** linha de audit (`denied`), nenhuma reserva de cota tocada.
2. Erro de entrada do gestor (janela fora da retenção, agregação grande demais) chega com o texto dele, e erro interno (asyncpg, KeyError) continua escondido — nas tools Google **e** Meta.
3. Negação Meta devolve `status: "denied"`, como a Google.
4. Contrato público intacto: schemas das tools, nomes e ordem das rotas, shape dos envelopes de mutate — conferido por snapshot, não por leitura.
5. Corrida no reconcile de cota: falha no `record_actual` não derruba resposta já obtida, e reserva negada no limite do gestor desfaz a do projeto.

Cada linha tem teste na task dona (A1, A2/A3, A3, G1/F5, B1).

---

## Parte A — Bugs (PR `fix/bugs-varredura`)

### Task A1: negação em `run_recommendation_action` grava um audit só

**Files:** Modify `src/google_ads/mutations.py` (bloco de `run_recommendation_action`, ~L495-511). Test: `tests/unit/test_recommendation_gate.py`.

- [ ] **Step 1: teste que falha.** `test_negacao_nao_grava_audit_do_executor`: com `ensure_account_access` trocado por um que levanta `AccountAccessDeniedError` e `audit_log.record` trocado por um contador, chamar `run_recommendation_action(...)`; assert `pytest.raises(AccountAccessDeniedError)` e `contador.chamadas == 0` (o audit `denied` é gravado pelo próprio gate real, que aqui está trocado), e `before_call` nunca chamado.
- [ ] **Step 2:** rodar `pytest tests/unit/test_recommendation_gate.py -q`. Expected: FAIL, contador = 1 (o `finally` grava `error`).
- [ ] **Step 3:** mover a chamada `run_with_reconnect(... ensure_account_access ...)` para antes do `try:`, como em `run_mutation`.
- [ ] **Step 4:** rodar o mesmo teste e `tests/unit/test_executor_gates.py`. Expected: PASS.
- [ ] **Step 5:** commit `fix(mcp): negação em run_recommendation_action grava um audit só`.

### Task A2: erro de entrada chega ao gestor

**Files:** Modify `src/google_ads/queries/_common.py` (ao lado de `InvalidDateRangeError`, L20), `src/mcp/server.py:60-81`, `src/mcp/tools/get_change_history.py:437`, `src/mcp/tools/run_gaql.py:109`. Test: `tests/unit/test_error_envelope.py` (criar se não existir; senão o arquivo que testa `_error_envelope`).

**Interfaces — Produces:** `class EntradaInvalidaError(ValueError)` em `src/google_ads/queries/_common.py`.

- [ ] **Step 1: testes que falham.** `test_entrada_invalida_repassa_mensagem`: `_error_envelope("x", EntradaInvalidaError("janela fora"))` == `{"status": "error", "error_message": "janela fora"}`. `test_value_error_cru_segue_escondido`: `ValueError("SELECT ... internals")` devolve a mensagem genérica. `test_change_history_janela_inteira_fora_da_retencao`: `consultar_change_history({"start_date": <today-60>, "end_date": <today-40>, ...}, today=date(2026,11,3))` levanta `EntradaInvalidaError` (não `ValueError` simples: `type(exc) is EntradaInvalidaError`).
- [ ] **Step 2:** rodar. Expected: FAIL (`EntradaInvalidaError` não existe).
- [ ] **Step 3:** criar a classe, incluí-la no `isinstance` de friendly do `_error_envelope`, trocar os dois `raise ValueError` por `raise EntradaInvalidaError`.
- [ ] **Step 4:** rodar os testes e `tests/unit/test_detect_drift.py`. Expected: PASS.
- [ ] **Step 5:** commit `fix(mcp): erro de entrada chega ao gestor com o texto dele`.

### Task A3: tools Meta devolvem `denied` e não vazam erro interno

**Files:** Modify `src/mcp/tools/_meta_common.py` e as 12 tools que chamam `meta_error_message` (lista: `meta_get_account_balance`, `meta_get_account_overview`, `meta_get_ad_preview`, `meta_get_budget_pacing`, `meta_get_change_history`, `meta_get_creatives`, `meta_get_delivery_estimate`, `meta_get_entities`, `meta_get_pages`, `meta_get_performance_breakdown`, `meta_search_targeting`, `_meta_performance`). Test: `tests/unit/test_meta_erro.py` (novo) + ajustes nos testes por tool que assertem o shape antigo.

**Interfaces — Produces:** `def meta_erro(exc: Exception) -> dict[str, Any]` em `_meta_common.py`: `MetaAccessDeniedError` → `{"status": "denied", "error_message": exc.message}`; `MetaAdsFriendlyError` → `{"status": "error", "error_message": exc.message}`; qualquer outra → `raise exc` (o `_error_envelope` central esconde). `meta_error_message` e o re-export `META_ACCOUNT_STATUS_LABELS` saem.

- [ ] **Step 1: testes que falham.** Em `test_meta_erro.py`: `test_negacao_vira_denied`, `test_friendly_mantem_mensagem`, `test_erro_interno_sobe` (`RuntimeError("asyncpg: senha")` re-levantado, mesma instância). `test_tool_meta_negada_devolve_denied`: `meta_get_entities` com `listar_entidades` trocado por um que levanta `MetaAccessDeniedError("sem grant")` → `status == "denied"`. Guard `test_nenhuma_tool_meta_usa_meta_error_message`: grep em `src/mcp/tools/*.py` por `meta_error_message` dá zero.
- [ ] **Step 2:** rodar. Expected: FAIL.
- [ ] **Step 3:** criar `meta_erro`; em cada tool, `except (MetaAccessDeniedError, MetaAdsFriendlyError) as e: return meta_erro(e)` no lugar do `except Exception` (`# noqa: BLE001` sai junto); remover `meta_error_message` e o re-export.
- [ ] **Step 4:** rodar `pytest tests/unit -q -k meta`. Expected: PASS; ajustar só testes que assertavam `status: "error"` em negação ou `str(exc)` de erro interno (o novo comportamento é o certo).
- [ ] **Step 5:** sabotagem do guard: recolocar um `meta_error_message` numa tool → guard falha; desfazer. Commit `fix(meta_ads): negação Meta devolve denied e erro interno não vaza`.

---

## Parte B — Cota e audit dos executores Google (PR `refactor/reserva-de-cota`, full sweep)

### Task B1: helper de reserva e reconcile

**Files:** Create `src/governance/reserva.py`. Test: `tests/integration/test_reserva_de_cota.py`.

**Interfaces — Produces:**
- `@dataclass(frozen=True) class Reserva: dia_projeto: <tipo que before_call devolve>; dia_gestor: <idem>; estimated_ops: int`
- `async def reservar_cota(pool: Any, *, manager_id: UUID, estimated_ops: int) -> Reserva` — numa transação externa, `before_call(conn, CHAVE_COTA_PROJETO, ...)` e `before_call(conn, f"mgr:{manager_id}", ..., daily_limit=get_settings().manager_daily_quota)`; `QuotaExhausted` sobe intacto.
- `async def reconciliar_cota(pool: Any, reserva: Reserva, *, manager_id: UUID, actual_ops: int, evento: str, **contexto: Any) -> None` — `best_effort(evento, **contexto)` + transação + os dois `record_actual`.

- [ ] **Step 1: testes que falham (DB real).** `test_reserva_e_reconcile_movem_as_duas_chaves`: reservar 5, reconciliar com 2 → `operations_used` = 2 nas duas linhas do dia. `test_limite_do_gestor_desfaz_reserva_do_projeto`: gestor no limite → `QuotaExhausted` e a linha `google-cloud-project` inalterada. `test_reconcile_engole_falha`: pool cujo `acquire` levanta → `reconciliar_cota` não levanta.
- [ ] **Step 2:** `pytest tests/integration/test_reserva_de_cota.py -q`. Expected: FAIL (módulo não existe).
- [ ] **Step 3:** implementar.
- [ ] **Step 4:** rodar. Expected: PASS. Commit `refactor(mcp): helper de reserva e reconcile de cota`.

### Task B2: `run_keyword_planning` e `run_report` usam o helper

**Files:** Modify `src/google_ads/keyword_planning.py`, `src/google_ads/reports.py`. Test: `tests/unit/test_run_report_quota_reserve.py`, `tests/unit/test_run_keyword_planning.py`.

- [ ] **Step 1:** trocar os blocos de reserva e reconcile por `reservar_cota`/`reconciliar_cota` (eventos `report_quota_reconcile_failed` e o de keyword planning, iguais aos atuais). `reserved` passa a ser `reserva is not None`. Audit continua no executor.
- [ ] **Step 2:** `run_report` passa a capturar o request-id: `client.get_service("GoogleAdsService", interceptors=[get_capture_interceptor()])`, `reset_request_id()` e `get_request_id()` **dentro** de `_consumir_stream` (F86), gravado como `provider_request_id` no audit. Teste novo `test_run_report_audita_request_id` com interceptor falso.
- [ ] **Step 3:** comentários "developer token" e a variável `token_id` saem dos dois arquivos; docstring de `reports.py` descreve as duas chaves e o gate.
- [ ] **Step 4:** rodar os testes citados e `tests/unit/test_executor_bookkeeping_never_masks.py`. Expected: PASS. Commit.

### Task B3: `run_mutation` e `run_recommendation_action`

**Files:** Modify `src/google_ads/mutations.py`. Test: `tests/unit/test_run_mutation_quota_reserve.py`; criar `test_recommendation_quota_reserve` no mesmo arquivo ou em `test_recommendation_gate.py`.

- [ ] **Step 1:** teste de caracterização para `run_recommendation_action` (reserva 1, reconcile 1, falha da API ainda reconcilia), rodar e ver PASS no código atual.
- [ ] **Step 2:** trocar os blocos pelos helpers; comentários e `token_id` como em B2.
- [ ] **Step 3:** rodar. Expected: PASS. Commit.

### Task B4: `run_conversion_upload` e `run_offline_user_data_job`

**Files:** Modify `src/google_ads/conversions.py`, `src/google_ads/customer_match.py`. Test: os `test_run_*_quota_reserve.py` dos dois.

- [ ] **Step 1:** trocar os blocos pelos helpers; comentários e `token_id` como em B2.
- [ ] **Step 2:** `provider_request_id` **no audit** passa a `None` quando não capturado (regra de `keyword_planning.py`: não medido é `None`, nunca `""`). O retorno ao cliente mantém o valor atual. Teste `test_audit_sem_request_id_grava_none` em cada um.
- [ ] **Step 3:** rodar os testes e o full sweep. Expected: verde. Commit.

---

## Parte C — Limpezas Google (PR `refactor/limpezas-google`, full sweep)

### Task C1: código morto e uniformidade em queries

**Files:** `src/google_ads/queries/change_history.py` (`_quote_literal` sai; `_format_in_clause` vira `gaql_in_list` direto), `src/google_ads/queries/assets.py:22,37` (`gaql_string_literal`), `src/google_ads/queries/_common.py:31` (`_PRESETS` sai, usa `PRESETS`), `src/db/repositories/google_ads_accounts.py:204` (docstring de `mark_inactive_except`: uso manual de emergência, sem chamador por design, ver F85).

- [ ] **Step 1:** grep de cada nome removido em `src/` e `tests/` dá zero antes da remoção. Fazer as mudanças.
- [ ] **Step 2:** `pytest tests/unit -q -k "change_history or assets or gaql"`. Expected: PASS. Commit.

### Task C2: versão da API num lugar só

**Files:** Create a constante `GOOGLE_ADS_API_VERSION = "v25"` em `src/google_ads/versao.py`. Modify `src/google_ads/queries/recommendations.py:151` (import do enum pela versão da constante), as mensagens ao usuário que dizem "v24" (`src/mcp/tools/apply_recommendation.py` L249/L294, `src/mcp/tools/update_conversion_action.py` L101) passam a interpolar a constante; os testes que importam `v24` (`test_recommendations_mutations.py`, `test_add_negative_keywords_cobertura.py`) usam a constante.

- [ ] **Step 1: guard que falha.** `test_versao_da_api_e_a_padrao_da_lib`: a constante é igual à versão padrão do `GoogleAdsClient` instalado; e grep `google\.ads\.googleads\.v[0-9]+` em `src/` só acha `versao.py`. Rodar: FAIL (há import v24).
- [ ] **Step 2:** fazer as trocas. Rodar o guard do proto de recomendações (o que reconfere `CAMPOS_DE_DETALHE`). Se ele falhar na v25, **parar**: a tabela precisa ser relida campo a campo, e isso vira ruling no ledger, não ajuste no teste.
- [ ] **Step 3:** rodar `pytest tests/unit -q -k "recommend or conversion_action"`. Expected: PASS. Commit.

### Task C3: pré-flights saem de `queries/_common.py`

**Files:** Create `src/google_ads/preflight.py` com os `validate_*` async (L316-1190) e o `run_report` que eles usam. `queries/_common.py` fica com datas, micros, métricas, filtros e os erros (`InvalidDateRangeError`, `EntradaInvalidaError`), **sem** importar `reports`. Modify os importadores (grep `from src.google_ads.queries._common import` com nome `validate_`) e os patch-sites de teste (grep `_common.validate_` e `_common.run_report` em `tests/` **antes** de mover; testes.md: patch no namespace de quem chama).

- [ ] **Step 1:** guard `test_queries_nao_importa_executor`: nenhum arquivo em `src/google_ads/queries/` importa `src.google_ads.reports`. Rodar: FAIL.
- [ ] **Step 2:** mover, sem reexport. Atualizar `docs/convencoes/dados.md` se citar o caminho.
- [ ] **Step 3:** gate + full sweep. Expected: verde. Commit.

---

## Parte D — Meta (PR `refactor/meta-colecao`)

### Task D1: caracterização das leituras de coleção

**Files:** Create `tests/unit/test_meta_colecao_caracterizacao.py`.

- [ ] **Step 1:** para `listar_paginas`, `buscar_segmentacao`, `listar_atividades` e `listar_criativos` (o que usa `_percorrer`), com `run_meta_graph_get` trocado por um falso que grava os kwargs: assertar `estimated_calls`, `max_pages`, `audit_this_call is True`, `params_summary` e o `truncated` em três casos (menos que `limit`, `limit+1` linhas, `paging.next` presente). Rodar no código atual: PASS. Commit.

### Task D2: `ler_colecao`

**Files:** Create `src/meta_ads/colecao.py`. Modify `entidades.py`, `paginas.py`, `segmentacao.py`, `historico.py`, `criativos.py`.

**Interfaces — Produces:**
- `class ContextoMeta(Protocol): manager_id: UUID; session_id: UUID`
- `async def ler_colecao(ctx: ContextoMeta, *, ad_account_id: str, edge: str, params: dict[str, Any], operacao: str, limit: int, params_summary: dict[str, Any]) -> tuple[list[dict[str, Any]], bool]` — devolve `(linhas_cruas, sobrou_next)`; calcula `max_pages = -(-(limit + 1) // int(params["limit"]))` e passa `estimated_calls=max_pages`. Cada módulo mantém o seu `parse_*` e a sua regra de `truncated` (`segmentacao` usa `None`; `historico` filtra antes de cortar).

- [ ] **Step 1:** implementar e trocar os 5 módulos; `ctx: Any` vira `ContextoMeta`.
- [ ] **Step 2:** rodar D1 e `pytest tests/unit -q -k meta`. Expected: PASS sem mudar D1. Commit.

### Task D3: janela Meta num lugar

**Files:** Modify `src/mcp/tools/_meta_performance.py`, `meta_get_account_overview.py`, `meta_get_performance_breakdown.py`.

**Interfaces — Produces:** `async def resolver_janela_meta(args: dict[str, Any], conta: <tipo do inventário>) -> tuple[<datas>]` em `_meta_performance.py`, com a mensagem única `"Datas inválidas: <detalhe>"`.

- [ ] **Step 1:** teste de caracterização das três tools com datas inválidas (mensagem atual de cada uma), PASS; depois trocar a expectativa para a mensagem única e implementar.
- [ ] **Step 2:** rodar `pytest tests/unit -q -k "meta and (overview or breakdown or performance)"`. Expected: PASS. Commit.

### Task D4: paginação da Graph com um laço só

**Files:** Modify `src/meta_ads/graph.py` (`fetch_paginated`), `src/meta_ads/reports.py` (`_paginar_graph`).

**Interfaces — Produces:** `async def paginas_graph(http: httpx.AsyncClient, url: str, params: dict[str, Any], headers: dict[str, str], max_pages: int) -> AsyncIterator[httpx.Response]` em `graph.py`; recebe o cliente, nunca o constrói. As duas funções viram adaptadores (uma devolve `complete=False`, a outra levanta `MetaGraphHTTPError`).

- [ ] **Step 1:** conferir que existem testes de `_paginar_graph` com 429 e de `fetch_paginated` com erro; se faltar, escrever a caracterização primeiro.
- [ ] **Step 2:** implementar; `test_meta_graph_execution_is_contained` e os testes F61/F189 verdes. Commit.

### Task D5: audit único em `run_meta_graph_get`

**Files:** Modify `src/meta_ads/reports.py` (os dois blocos `best_effort + audit_log.record`, ramos de erro e sucesso).

- [ ] **Step 1:** extrair `async def _gravar_audit_leitura(*, manager_id, session_id, ad_account_id, operation_name, status, error_message, target_count, provider_request_id, params_summary, duration_ms) -> None`; não constrói cliente. Testes de audit e `denied` de `reports` verdes. Commit.

---

## Parte E — Remover o OAuth pessoal da Meta (PR `refactor/sem-oauth-meta-pessoal`, full sweep)

### Task E1: callback de exclusão de dados em módulo próprio

**Files:** Create `src/auth/meta_data_deletion.py` com `router = APIRouter(prefix="/oauth/meta")`, a rota `POST /data-deletion-callback` e `_verify_meta_signed_request`, movidos sem mudança. Modify `src/app.py:127` (inclui este router no lugar do antigo). Tests: `test_meta_data_deletion_callback.py`, `test_meta_signed_request.py`, `test_csrf_por_rota.py`, `test_csrf_middleware.py` (import novo).

- [ ] **Step 1:** mover; o path literal `/oauth/meta/data-deletion-callback` continua em `_CSRF_EXEMPT_ROUTES`. Rodar esses testes e o snapshot de rotas. Expected: PASS. Commit.

### Task E2: retirar start, callback e revoke

**Files:** Delete `src/auth/meta_oauth.py` e `src/db/repositories/meta_oauth_connections.py`. Modify `src/web/routes/admin_overview.py` (card), `src/web/routes/_shared.py` (`meta_expiry_signals` sai), `src/web/templates/admin/index.html` (card Meta), `src/web/templates/access_denied.html` (ramos `meta_*` saem), `src/auth/oauth_state.py` (`"meta_oauth"` sai do `StateAudience`), `src/meta_ads/account_overview.py` (`build_warnings` perde `token_expires_at` e o ramo de expiração), `src/mcp/tools/meta_get_account_overview.py:191`, `tests/unit/fixtures/tabela_de_rotas.json` (3 rotas saem, motivo no commit), `docs/convencoes/nucleo.md` (o OAuth pessoal deixa de existir; a tabela `meta_oauth_connections` fica, e `src/jobs/restore.py:48` continua listando-a).
Tests: apagar `test_meta_oauth.py`, `test_meta_oauth_flow.py`, `test_meta_expiry_signals.py`; ajustar `test_meta_secret_leak.py` (o escopo passa a `meta_data_deletion.py`), `test_confusao_de_token.py`, `test_oauth_state.py`, `test_no_secrets_in_query_params.py`, `test_rotas_de_mutacao_tem_guard.py`, `test_structural_guards.py`, `test_meta_account_overview.py` e os seeds de integração que chamavam `meta_oauth_connections.upsert` (passam a não semear a conexão; se algum teste dependia dela, registrar no ledger).

- [ ] **Step 1: guard que falha.** `test_oauth_meta_pessoal_nao_existe`: a tabela de rotas da app não tem `/oauth/meta/start`, `/oauth/meta/callback` nem `/oauth/meta/revoke`, e tem `/oauth/meta/data-deletion-callback`. Rodar: FAIL.
- [ ] **Step 2:** fazer as remoções; `python scripts/build_tailwind.py` se o template mudar classe.
- [ ] **Step 3:** gate + full sweep + `pytest tests/browser`. Expected: verde.
- [ ] **Step 4:** grep `oauth/meta/start\|meta_oauth\b\|meta_expiry` em `src/` só acha o que o Step 1 permite. Commit `refactor(auth): remove o OAuth pessoal da Meta`.
- **Fora desta task:** as linhas já gravadas em `meta_oauth_connections` em produção ficam. Apagar dado de produção é decisão e aval à parte.

---

## Parte F — Painel (PR `refactor/painel`, `tests/browser` + clique em produção)

### Task F1: helpers HTMX e toast

**Files:** Modify `src/web/routes/_shared.py`; os 9 pontos: `accounts.py:77`, `admin_accounts.py:153-198`, `admin_invites.py:157,163`, `admin_overview.py:188,194,229,235`, `sessions.py:352,357`.

**Interfaces — Produces:** `def eh_htmx(request: Request) -> bool` (header `HX-Request` == `"true"`); `def toast_trigger(mensagem: str, kind: str = "success") -> str` (`json.dumps`, mesmo formato de `_shared.py:191`); `def resposta_hx(request: Request, *, destino: str, hx: Literal["redirect", "refresh"] = "refresh", toast: str | None = None) -> Response` (HTMX: 204 + `HX-Redirect`/`HX-Refresh` [+ `HX-Trigger`]; senão 303 para `destino`).

- [ ] **Step 1:** testes unitários dos três helpers (header `"true"`, ausente e `"false"`; toast com aspas e acento). FAIL, implementar, PASS.
- [ ] **Step 2:** trocar os 9 pontos; o restore Google ganha o ramo HTMX igual ao Meta. Rodar `test_web_panel_admin.py`, `test_admin_meta_access.py`. Commit.

### Task F2: validação e links nas rotas admin

**Files:** `src/web/routes/admin_access.py` (`manager_id: UUID = Form(...)` nos POSTs), `src/web/routes/audit.py:76-84` e `admin_audit.py:73-83` (`urllib.parse.urlencode`), imports locais redundantes (`audit.py:123,153`, `admin_audit.py:129`), `detail` dos 404 em PT-BR.

- [ ] **Step 1:** em `test_uuid_guards.py`, `test_post_com_manager_id_malformado_da_422` para cada POST de `admin_access` (hoje 500). Em teste de audit, `customer_id="1&status=x"` gera link com `%26`. FAIL.
- [ ] **Step 2:** implementar. PASS. Commit.

### Task F3: SQL do painel em repositórios

**Files:** Modify `src/db/repositories/managers.py`, `src/web/routes/admin_access.py:43,84,304,470`, `admin_audit.py:64`, `accounts.py:69-72`, `admin_overview.py:52-68`.

**Interfaces — Produces:** `managers.list_active(conn) -> list[asyncpg.Record]` (`id, email, full_name, role`, `ORDER BY email`); `managers.get_summary(conn, manager_id: UUID) -> asyncpg.Record | None` (`id, email, full_name`).

- [ ] **Step 1:** testes de integração dos dois. FAIL, implementar, trocar as rotas, PASS (full sweep). Commit.

### Task F4: rotas gêmeas Google e Meta

**Files:** Create `src/web/routes/_acesso.py`. Modify `src/web/routes/admin_access.py` (toggle 110-169/504-563, bulk-grant 172-198/334-359, bulk-copy 201-230/362-390).

**Interfaces — Produces:** `@dataclass(frozen=True) class PlataformaAcesso` com o repositório de grant, o nome da coluna da conta, a plataforma do audit e o prefixo de URL; `PLATAFORMAS: dict[Literal["google", "meta"], PlataformaAcesso]`; `async def aplicar_toggle(conn, plataforma: PlataformaAcesso, *, admin: CurrentUser, manager_id: UUID, conta: str, desejado: bool) -> bool` (devolve `mudou`); `async def conceder_em_massa(...)` e `async def copiar_acessos(...)` com a mesma forma. As rotas continuam com path, nome e ordem atuais e só delegam.

- [ ] **Step 1:** rodar os testes de acesso (`test_admin_access_idempotente.py`, `test_admin_meta_access.py`, `test_toggle_fragment_escape.py`) e o snapshot de rotas: verdes antes.
- [ ] **Step 2:** implementar e delegar. Os mesmos testes, sem alteração, verdes. Commit.

### Task F5: templates de acesso unificados

**Files:** `src/web/templates/admin/access.html` + `access_meta.html`, `access_by_manager*.html`, `access_manager_detail*.html` → um template por par, parametrizado pela plataforma (coluna da conta, cabeçalho, badge de status só no Meta, sufixo de id `-meta`).

- [ ] **Step 1:** snapshot do HTML renderizado das 6 páginas com dados fixos (teste novo, PASS no código atual).
- [ ] **Step 2:** unificar; o snapshot só pode mudar em espaço em branco. Preservar `aria-labelledby`, ids `v4-mgr-*`/`v4-acc-*`, `data-v4-access-toggle` e ids únicos por página (F81, F101). `build_tailwind.py`, `test_frontend_a11y_guards.py`, `test_frontend_responsive_guards.py`, `tests/browser`. Commit.

### Task F6: `sessions.py` só com sessão

**Files:** Create `src/web/routes/pages.py` (help, legal, access-denied, data-deletion-status) e `dashboard.py`. Modify `sessions.py`, `src/web/routes/__init__.py`.

- [ ] **Step 1:** mover mantendo nomes (`data_deletion_status` continua) e a ordem de registro; `test_tabela_de_rotas_e_estavel.py` verde sem mexer no fixture. Commit.

### Task F7: `auth` deixa de importar `web`

**Files:** Create `src/web/templating.py` (`templates`), `src/auth/urls.py` (`def https_url_for(request: Request, name: str, **params: Any) -> str`). Modify `src/auth/oauth.py:29,70,134-149`, `src/web/routes/_shared.py:208` (importa de `templating`).

- [ ] **Step 1:** guard `test_auth_nao_importa_web_routes`: nenhum arquivo em `src/auth/` importa `src.web.routes`. Teste de `handle_callback_decision` com `"a@sub.v4company.com"` e `"a@V4Company.com"`: registrar o comportamento atual e passar a usar `is_allowed_email` só se os dois casos derem o mesmo resultado; senão ruling no ledger. FAIL no guard.
- [ ] **Step 2:** implementar. PASS. Commit.

---

## Parte G — Tools MCP (PR `refactor/tools-mcp`, full sweep; tool nova ou schema mudado pede sessão nova no smoke)

### Task G1: snapshot dos schemas

**Files:** Create `tests/unit/test_schemas_snapshot.py` + `tests/unit/fixtures/schemas_das_tools.json`.

- [ ] **Step 1:** gerar o JSON de `name`, `description` e `input_schema` das 80 tools a partir do registry; o teste compara. PASS. Commit. Todas as tasks G seguintes rodam este teste sem atualizar o fixture.

### Task G2: schema e janela de datas

**Files:** Modify `src/mcp/tools/_common.py`; aplicar em `get_performance_breakdown`, `get_change_history`, `detect_drift`, `bulk_pause_by_query`, `get_account_overview`, `get_funnel_metrics`, `get_search_terms_report`, `get_top_keywords_creatives` e nos `audit_*` que tenham o trio. **Não** nos 8 reports da Fase 2B.

**Interfaces — Produces:** `def propriedades_de_data(default: str = "LAST_30_DAYS", presets: Sequence[str] = <PRESETS de src.janelas>) -> dict[str, Any]`; `async def janela_da_conta(ctx: Any, args: dict[str, Any], customer_id: str, *, default: str = "LAST_30_DAYS") -> tuple[date, date, date]` (início, fim, hoje da conta), chamando `resolve_account_today` (guard `test_no_server_clock_in_google_tools`).

- [ ] **Step 1:** testes dos dois helpers; implementar; trocar; G1 verde sem mudar o fixture. Commit.

### Task G3: domínio sai das tools

**Files:** Create `src/google_ads/change_scan.py` (`consultar_change_history`, `CAP_CHANGE_EVENT`). Modify `src/google_ads/ad_schedule.py` (`rows_to_current`, `campanhas_com_grade_incerta`). Modify `get_change_history.py`, `detect_drift.py`, `get_ad_schedule.py`, `update_ad_schedule.py`, `apply_change.py` e todos os patch-sites em `tests/` (grep antes).

- [ ] **Step 1:** mover; `today` continua injetado (F141). Testes das 5 tools verdes. Commit.

### Task G4: preview de mutate num helper

**Files:** Modify `src/mcp/tools/_mutate_common.py` e as tools com `create_pending` (grep; 25).

**Interfaces — Produces:** `async def emitir_preview(ctx: Any, *, operation: str, customer_id: str, payload: dict[str, Any], summary: str, risk: RiskAssessment, **extra: Any) -> dict[str, Any]` — usa `risk.level` (F112) e devolve `preview_envelope(...)`; `def no_changes_envelope(operation: str, motivo: str, **extra: Any) -> dict[str, Any]`, no shape atual de `update_ad_schedule.py:359` e `add_negative_keywords.py:200` (conferir que os dois são iguais antes; se não forem, ruling).

- [ ] **Step 1:** testes dos helpers; trocar em lotes de 5 tools por commit; `test_envelope_applied_e_unico.py` e o guard F112 verdes. G1 verde.

### Task G5: `apply_change` vira despachante

**Files:** Modify `src/mcp/tools/apply_change.py`; os confirmadores vão para perto do domínio (`src/google_ads/confirmadores.py`).

**Interfaces — Produces:** `class Confirmador(Protocol): async def pre_check(...) -> dict[str, Any] | None; async def executar(...) -> dict[str, Any]; async def pos_check(...) -> dict[str, Any]`; `CONFIRMADORES: dict[str, Confirmador]` com `import_offline_conversions`, `apply_recommendation`, `upload_customer_match_list`, `update_ad_schedule` e o padrão.

- [ ] **Step 1:** ler os testes de `apply_change` e escrever caracterização do que faltar (ordem pre-check antes da escrita; I/O pós-escrita nunca vira erro, F83/F91). PASS no código atual.
- [ ] **Step 2:** implementar o despachante; caracterização verde sem mudança; full sweep. Commit.

---

## Parte H — Jobs e testes (PR `refactor/jobs-e-testes`, full sweep)

### Task H1: esqueleto comum dos jobs

**Files:** Create `src/jobs/_runner.py`. Modify `src/jobs/account_resync.py:235-442`, `src/jobs/meta_resync.py:232-265`.

**Interfaces — Produces:** `async def executar_job(*, operation: str, platform: str, corpo: Callable[[], Awaitable[int]]) -> int` (logging, `init_pool`, `record_job_crash` em exceção, `close_pool` no `finally`); em `account_resync`, `_etapa_google() -> bool`, `_etapa_meta() -> bool`, `_etapa_purge() -> bool` (True = falhou), na ordem atual e com os comentários de F83/F85/F93 movidos para as docstrings.

- [ ] **Step 1:** `test_account_resync.py` e `test_job_partial_failure_audit.py` verdes antes e depois, sem alteração. Commit.

### Task H2: nomes da cota e SQL dos jobs

**Files:** `src/governance/rate_limit.py` (parâmetro `developer_token_id` → `chave` nas funções Python; coluna intacta), `src/db/repositories/google_oauth_connections.py` (`pick_admin_active(conn) -> <conexão> | None`, com o `ORDER BY` determinístico atual de `_pick_oauth_connection`), `src/jobs/account_resync.py:50,60`.

- [ ] **Step 1:** teste de integração de `pick_admin_active` (dois admins ativos: mesmo escolhido sempre). FAIL, implementar, PASS. Commit.

### Task H3: seeds de integração

**Files:** Create `tests/integration/_seed.py`. Modify em lotes os arquivos com `managers.create` + `mcp_sessions.create` (29) e os helpers locais (`_make_manager` ×4, `_seed_manager_with_access`, `_seed_manager_and_session`, `_seed_manager_with_meta_conn` ×3).

**Interfaces — Produces:** `async def seed_manager(conn, *, email: str | None = None, role: str = "manager") -> UUID` (e-mail único por padrão: `f"t-{uuid4().hex[:8]}@v4company.com"`); `async def seed_manager_with_session(conn, **kw) -> tuple[UUID, str]` (manager, token); `async def grant_google(conn, manager_id: UUID, customer_id: str) -> None`; `async def seed_meta_account(conn, manager_id: UUID, *, ad_account_id: str = "act_123456", account_status: int = 1) -> None`.

- [ ] **Step 1:** um lote por commit (no máximo ~10 arquivos), full sweep a cada lote; nenhum assert muda.

### Task H4: fake pool compartilhado

**Files:** Create `tests/unit/fixtures/fake_pool.py`. Modify os 19 arquivos com `_FakePool`/`_fake_pool` idênticos (manter local o de `test_hot_reads_reconnect.py`, que testa reconexão).

**Interfaces — Produces:** `class FakePool` (`acquire()` devolve a conexão dada; conta `acquires`); `def patch_pool(monkeypatch, pool, *alvos: str) -> None`.

- [ ] **Step 1:** trocar; `pytest tests/unit -q` verde. Commit.

### Task H5: trio Meta de performance parametrizado

**Files:** `tests/integration/test_meta_get_{ad,ad_set,campaign}_performance.py` → um arquivo com `pytest.mark.parametrize` sobre a tool, mantendo os asserts específicos de cada uma (F54, F89).

- [ ] **Step 1:** número de casos coletados igual ou maior que a soma dos três arquivos atuais; full sweep. Commit.

---

## Fecho

- [ ] `docs/operacao/estado-atual.md`: uma linha por parte entregue; o que ficou fora, com o motivo.
- [ ] Os 3 bugs vão para o `/findings-add` (o Wellington roda).
