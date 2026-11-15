# Varredura de faxina de 15/11: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Executar os achados da varredura de 15/11 escolhidos pelo Wellington: medir de verdade o uso das tools (P0), tirar peso da doc, do gate, do código morto, dos testes duplicados e da duplicação em `src`, sem mudar o que o gestor vê.

**Architecture:** Sete partes, **um PR por parte**, nesta ordem: P0 (audit no sucesso + script de medição) → P1 (docs) → P2 (gate mais rápido) → P3 (código morto pontual) → P4 (testes duplicados) → P5 (duplicação em `src`) → P6 (esqueleto dos executores). Cada parte sai de `main` atualizado (P1 sai da branch `docs/varredura-faxina`, que já existe), passa pelo gate e, quando indicado, pelo full sweep, e só é mesclada e deployada com aval nominal do Wellington. P0 é a única parte que muda comportamento, e o que muda é só a trilha do audit. Nas demais, refatoração é estrutural: o teste existente é a rede, e onde não houver, a task escreve caracterização **antes** e a vê passar no código atual.

**Tech Stack:** Python 3.13, asyncpg, FastAPI + Jinja2 + HTMX, `google-ads` 33.0.0 (API v25), Meta Graph v25 via httpx, pytest + testcontainers + freezegun.

**Spec:** `docs/superpowers/specs/2026-11-15-varredura-faxina-design.md`. Achados, com onde/evidência/sugestão: `docs/operacao/varredura-faxina-2026-11-15.md` (relatórios A/B/C/D). Os locais citados abaixo foram reconferidos no código em 15/11.

## Global Constraints

- Gate antes de todo commit, sem pipe: `D:/v4-ads-mcp/.venv/Scripts/python.exe scripts/check_pre_push.py > /dev/null 2>&1; echo $?` tem de imprimir `0`. Nunca `| tail`, `| grep` ou `;` antes do `git commit`.
- Full sweep (`D:/v4-ads-mcp/.venv/Scripts/python.exe scripts/check_pre_push_full.py`, Docker) obrigatório em **P0, P5 e P6**, e em qualquer task que toque query, transação, executor ou arquivo de `tests/integration/`. Se o engine não responde, abrir o Docker Desktop.
- Guard novo só vale com sabotagem conferida contra o código pré-fix, cada sabotagem com controle positivo; **nunca `git checkout`** para desfazer (edição reversa ou cópia).
- Refatoração não muda comportamento: o teste existente é a rede; onde não houver rede, caracterização antes, vista em PASS no código atual.
- Contagem de tools sempre pelo registry (`import_all_tools()` + `all_tools()`), nunca por `ls`.
- Migration commitada não se edita (hook `guard-migrations`). Comentário de migration que aponte para doc movido fica como histórico.
- Snapshot de schema (`tests/unit/fixtures/schemas_das_tools.json`) só se regrava com `V4_REGRAVAR_SCHEMAS=1` **com motivo escrito no PR e diff restrito às tools da task**. Nenhuma task deste plano tem motivo para regravar: se o snapshot ficar vermelho, a task mudou contrato e para.
- Tabela de rotas (`tests/unit/fixtures/tabela_de_rotas.json`): nomes, paths e ordem preservados.
- Gate `ensure_account_access` continua no topo de cada executor, fora de `try` e de helper; `CALL_SITES_DO_GATE` (`tests/unit/test_executor_gates.py:177`) não muda em nenhuma task.
- Cota e audit continuam blocos `best_effort` **independentes** (F73/F83/F91): a falha de um não pula o outro, e nenhum transforma resultado bom em erro.
- Guard de varredura usa `tests/unit/_guard_harness.py`; escopo vazio levanta `EscopoVazioError`. Allowlist que só encolhe tem o par "barra entrada nova" + "allowlist descreve a realidade".
- Doc viva não ganha link markdown para arquivo que uma task vai mover (o `tests/unit/test_docs_links.py` varre `docs/superpowers` também).
- Template com classe nova ou removida: `python scripts/build_tailwind.py` e o CSS no mesmo commit.
- Ferramentas de apoio (script de reescrita de links, perfil) ficam no scratchpad, fora do repo.
- Fora deste plano, por decisão registrada: B-04 (`mark_inactive_except` fica), D-07, D-08, D-10, B-01, Fase 2B, `recommendations.py`, `accounts.html` × `accounts_meta.html`, remoção de qualquer tool.
- Commits `tipo(escopo): …` em PT-BR, terminando com `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Mensagem ao gestor em PT-BR.

## Review Focus

1. **Audit que falha não derruba leitura (P0).** `meta_list_my_ad_accounts` com `audit_log.record` levantando devolve as contas, e o log `meta_list_audit_write_failed` sai. Teste em T0.3.
2. **Negação não vira duas linhas (P0).** Leitura negada pelo gate grava exatamente a linha `denied` do gate, nenhuma de sucesso nem de erro do executor. Teste em T0.2.
3. **Memoização que responde por outra árvore (P2).** Duas árvores com o mesmo texto, ou um alias novo num arquivo editado entre duas leituras, dão a resposta da própria árvore. Teste de equivalência em T2.1.
4. **Fixture compartilhada muda quem tem contexto (P4).** Teste que depende da AUSÊNCIA de `McpRequestContext` continua vendo `get_current()` levantar; conjunto de nodeids coletados e de PASS idêntico ao baseline, salvo os deltas declarados. Prova em T4.2.
5. **Montar o audit levanta depois de a mutação já ter sido aplicada (P6).** O `return` do executor sobrevive e o erro vira log ERROR: o montador roda dentro do `best_effort`. Teste em T6.2.

---

## P0 — Audit no sucesso + medição (PR `feat/audit-leituras-sem-trilha`, full sweep)

A-01. Hoje sete leituras não gravam linha no sucesso: as 5 do achado, `get_account_overview` (mesma classe, medido por grep em 15/11: chama `run_report` sem `audit_this_call` e tem só 6 linhas em 90 dias) e `meta_list_my_ad_accounts`. Depois do P0, toda tool de leitura grava **uma** linha por chamada, como as demais.

### Task T0.1: inventário de como cada tool audita (guard, vermelho)

**Files:** Create `tests/unit/test_leitura_audita_no_sucesso.py`.

**Interfaces — Produces:** `COMO_CADA_TOOL_AUDITA: dict[str, str]`, uma entrada por tool do registry, valor em `{"executor", "registro_direto", "mutacao", "pendencia", "delega:<arquivo sob src/>:<função>"}`. Lido por T0.4 (lista de tools) e revisto em P5/P6 se uma tool mudar de categoria.

- [ ] **Step 1:** escrever `_sinais(arquivo: Path) -> set[str]` via harness (`h.arvore`, `h.chama`, `h.nomes_locais`), sobre o módulo do handler (`inspect.getsourcefile(tool.handler)`): `mutacao` se chama `run_mutation`, `run_conversion_upload`, `run_offline_user_data_job`, `run_recommendation_action`, `emitir_preview` ou `create_pending`; `executor` se alguma chamada a `run_report`/`run_meta_graph_get`/`run_meta_level_performance` passa `audit_this_call` diferente do literal `False` e não ausente; `executor_sem_audit` se chama executor e nenhuma chamada audita; `registro_direto` se chama `audit_log.record`; `pendencia` só para `apply_change` (chama `consume`). Categoria derivada por precedência `mutacao > pendencia > registro_direto | executor > delega`; módulo sem sinal nenhum precisa de `delega:` na tabela.
- [ ] **Step 2:** `test_tabela_cobre_o_registry_inteiro`: `set(COMO_CADA_TOOL_AUDITA) == {t.name for t in all_tools()}` (depois de `import_all_tools()`), com mensagem "só no código / só na tabela". `test_categoria_derivada_bate_com_a_tabela`: para toda tool sem `delega:`, derivada == tabela. `test_delegada_audita_de_fato`: para cada `delega:<arq>:<fn>`, a função `fn` em `src/<arq>` chama `audit_log.record`, `_gravar_audit_leitura`, ou passa `audit_this_call=True` a um executor (corpo próprio, `h.chama_no_corpo_proprio`). `test_nenhuma_leitura_sem_trilha`: nenhum módulo deriva `executor_sem_audit` nem fica sem sinal e sem `delega:`.
- [ ] **Step 3:** preencher a tabela rodando a derivação uma vez e decidindo cada linha. As 7 tools do P0 entram com a categoria **de depois** (`executor` para as 6 Google, `registro_direto` para `meta_list_my_ad_accounts`). Para cada `delega:`, abrir a função e confirmar que audita.
- [ ] **Step 4:** rodar `D:/v4-ads-mcp/.venv/Scripts/python.exe -m pytest tests/unit/test_leitura_audita_no_sucesso.py -q`. Expected: FAIL em `test_categoria_derivada_bate_com_a_tabela` e `test_nenhuma_leitura_sem_trilha` **exatamente** com `get_account_overview`, `get_budget_pacing`, `get_funnel_metrics`, `get_negative_keywords_audit`, `get_search_terms_report`, `get_top_keywords_creatives`, `meta_list_my_ad_accounts`. Conjunto diferente (outra tool sem trilha, ou uma das 7 já auditando): **pare** e leve ao Wellington — é dado novo do A-01.
- [ ] **Step 5:** controle do scanner: numa cópia em `tmp_path` de `get_campaign_performance.py` com `audit_this_call=True` trocado por `False`, `_sinais` devolve `executor_sem_audit` (`test_scanner_ve_o_opt_out`). Sem commit ainda: o guard fica vermelho até T0.2/T0.3.

### Task T0.2: as 6 leituras Google gravam no sucesso

**Files:** Modify `src/mcp/tools/get_account_overview.py:141`, `get_budget_pacing.py:116`, `get_funnel_metrics.py:98`, `get_negative_keywords_audit.py:140`, `get_search_terms_report.py:106`, `get_top_keywords_creatives.py:96`. Test: `tests/unit/test_report_audit_optin.py`.

**Interfaces — Consumes:** `run_report(..., audit_this_call: bool = False)` (`src/google_ads/reports.py:40`), sem mudança.

- [ ] **Step 1: testes que falham.** Em `test_report_audit_optin.py`, `test_leitura_grava_uma_linha_por_chamada`, parametrizado nas 6 tools: `run_report` trocado por um fake que guarda os kwargs de **cada** chamada; `get_current`, `janela_da_conta` e `resolve_account_today` trocados onde o módulo os importa (`date(2026, 11, 15)`). Assert: exatamente uma chamada com `audit_this_call is True`, e o `operation_name` dela é o nome da tool; todas as outras com `audit_this_call` ausente ou `False`. Args por tool: `{"customer_id": "1234567890"}` mais `"date_range": "LAST_7_DAYS"` nas que têm janela. Para `get_budget_pacing`, o fake devolve uma linha não compartilhada para exercitar a leitura de hoje (`_gasto_por`). `test_negacao_grava_so_a_linha_do_gate`: `run_report` real, `ensure_account_access` levantando `AccountAccessDeniedError` depois de gravar via fake de `audit_log.record`; assert uma chamada a `record`, com `status="denied"`.
- [ ] **Step 2:** rodar o arquivo. Expected: FAIL nas 6 (nenhuma chamada com `True`).
- [ ] **Step 3:** passar `audit_this_call=True` **só na leitura principal** de cada tool: a do período atual em `get_account_overview`, a de `budget_pacing_query` em `get_budget_pacing` (a de hoje e a de orçamento compartilhado, em `_gasto_por`, ficam sem), `negatives_task` em `get_negative_keywords_audit` (a `_creations` fica sem), `keywords` em `get_top_keywords_creatives`. Sem `params_summary` (como os reports da 2A).
- [ ] **Step 4:** rodar `test_report_audit_optin.py`, `test_get_negative_keywords_audit.py`, `test_leitura_audita_no_sucesso.py` (agora só falta `meta_list_my_ad_accounts`) e `test_schemas_snapshot.py`. Expected: PASS, salvo a linha Meta no guard. Commit (junto com T0.3, para o guard entrar verde).

### Task T0.3: `meta_list_my_ad_accounts` grava no sucesso

**Files:** Modify `src/mcp/tools/meta_list_my_ad_accounts.py:35-57`. Test: `tests/unit/test_meta_list_my_ad_accounts.py` (novo; não existe teste unit da tool hoje).

- [ ] **Step 1: testes que falham.** `test_lista_grava_uma_linha_de_audit`: pool fake (`tests/unit/fixtures/fake_pool.py`), `list_accounts_for_manager` devolvendo 2 contas, `audit_log.record` como `AsyncMock`; assert uma chamada com `action_type="read"`, `operation="meta_list_my_ad_accounts"`, `platform="meta"`, `customer_id=None`, `target_count=2`, `status="success"` e `duration_ms` inteiro ≥ 0. `test_audit_que_falha_nao_derruba_a_lista`: `record` levantando `ConnectionError` → a tool devolve `total == 2` e o `structlog` captura `meta_list_audit_write_failed`.
- [ ] **Step 2:** rodar. Expected: FAIL (zero chamadas).
- [ ] **Step 3:** depois da leitura, numa conexão nova: `async with best_effort("meta_list_audit_write_failed", operation="meta_list_my_ad_accounts"), pool.acquire() as conn:` → `audit_log.record(...)` com os campos acima. Medir `duration_ms` desde o início do handler, como `list_my_accounts.py`.
- [ ] **Step 4:** rodar o arquivo, `test_leitura_audita_no_sucesso.py` e `test_structural_guards.py`. Expected: PASS. Sabotagem: tirar o `audit_this_call=True` de `get_funnel_metrics.py` → `test_nenhuma_leitura_sem_trilha` e `test_leitura_grava_uma_linha_por_chamada[get_funnel_metrics]` vermelhos; desfazer por edição. Gate = 0. Commit `feat(mcp): as 7 leituras sem trilha gravam audit no sucesso` com os arquivos de T0.1–T0.3.

### Task T0.4: script de medição de uso por tool

**Files:** Create `scripts/medir_uso_tools.py`. Test: `tests/unit/test_medir_uso_tools.py`, `tests/integration/test_medir_uso_tools.py`.

**Interfaces — Produces:**
- `OPERACAO_QUE_CONTA: dict[str, str]` — tool → operation que representa a chamada (padrão: o próprio nome). Diferentes do padrão (Anexo 1 do relatório): `audit_goal_attribution` → `audit_goal_attribution_actions`; `detect_drift` → `get_change_history` (compartilhada; ver abaixo).
- `OPERACOES_AUXILIARES: dict[str, tuple[str, ...]]` — gravadas junto e **não** contadas como chamada: `get_negative_keywords_audit_creations`, `audit_goal_attribution_goals`, `bulk_pause_by_query_dry_run`, `<nome>_lookup` de `apply_recommendation`/`update_campaign_budget`/`remove_ad`/`update_recommendation_subscription`, `remove_ad_enabled_por_grupo`.
- `VARIAS_LINHAS_POR_CHAMADA: frozenset[str]` — tools que gravam mais de uma linha sob o mesmo nome numa chamada (medido em 15/11: `get_account_balance`, `meta_get_account_balance`, `audit_competitor_keywords`); o relatório marca `linhas != chamadas`.
- `async def coletar(conn: asyncpg.Connection, *, inicio: date, fim: date) -> list[LinhaDeUso]` e `async def coletar_aplicacoes(conn, *, inicio: date, fim: date) -> ContagemApplyChange` — SQL só `SELECT`.
- `def montar_relatorio(linhas: list[LinhaDeUso], aplicacoes: ContagemApplyChange, *, tools: list[str], inicio: date, fim: date) -> dict[str, Any]`.
- CLI: `python scripts/medir_uso_tools.py --dias 90 [--ate YYYY-MM-DD]`, lê `DATABASE_URL` do ambiente (como `src/scripts/admin.py`), abre **uma** conexão e roda tudo dentro de `conn.transaction(readonly=True)`, imprime JSON no stdout.

- [ ] **Step 1: testes unit que falham.** `test_toda_tool_do_registry_tem_linha`: chaves de `montar_relatorio(...)["tools"]` == nomes do registry. `test_mapa_so_tem_tool_que_existe`: chaves de `OPERACAO_QUE_CONTA`, `OPERACOES_AUXILIARES` e `VARIAS_LINHAS_POR_CHAMADA` ⊆ registry. `test_preview_e_aplicacao_separados`: linha de mutação com `dry_run=True` soma em `linhas_preview`, não em `linhas`. `test_auxiliar_nao_conta_chamada`: 3 linhas `get_negative_keywords_audit` + 3 `_creations` → `linhas == 3`. `test_operation_sem_dono_sai_em_fora_do_registry`. `test_tool_que_passou_a_auditar_traz_janela_efetiva`: para as 7 do P0, `janela_efetiva_desde` = data da primeira linha `status='success'` da operation (ou `None` com nota "sem linha de sucesso na janela"). `test_relatorio_nao_tem_email`: `"@" not in json.dumps(relatorio)` (gestores só contados).
- [ ] **Step 2:** rodar. Expected: FAIL (módulo não existe).
- [ ] **Step 3:** implementar. Cada tool sai com `{linhas, linhas_preview, gestores, ultima, operation, medivel, nota}`. `detect_drift` sai `medivel: false` com nota "grava como get_change_history; não separável no audit". `apply_change` sai de `coletar_aplicacoes` com dois números: `via_pendencias` = tokens com `consumed_at` na janela (`pending_confirmations` JOIN `mcp_sessions` para o gestor), com nota "o purge apaga pendência 7 dias depois de expirar (`src/jobs/purge.py:23`): cobre só o fim da janela"; e `via_audit` = linhas de mutação `dry_run IS NOT TRUE` precedidas, na mesma `session_id`, `operation` e `customer_id`, por uma linha `dry_run = true` até `DEFAULT_TTL_MINUTES` antes, com nota "estimado". O topo do JSON traz `janela`, `nao_medido` (lista textual) e `operations_fora_do_registry`.
- [ ] **Step 4: teste de integração.** `test_coleta_roda_em_transacao_so_de_leitura`: com o `pg` do conftest de integração, semear 4 linhas de `audit_log` e 1 `pending_confirmations` consumida; `coletar` e `coletar_aplicacoes` dentro de `transaction(readonly=True)` devolvem os números esperados; um `INSERT INTO audit_log` na mesma transação levanta `asyncpg.exceptions.ReadOnlySQLTransactionError` (controle de que a transação é mesmo só leitura).
- [ ] **Step 5:** rodar os dois arquivos; `ruff check scripts/medir_uso_tools.py` e `mypy scripts/medir_uso_tools.py` limpos (o gate não varre `scripts/`). Expected: PASS. Gate = 0; full sweep = 0. Commit `feat(admin): script de medição de uso por tool`.

**Pronto do P0:** depois do deploy (aval nominal), em sessão MCP nova, chamar cada uma das 7 tools uma vez numa conta liberada e rodar `scripts/medir_uso_tools.py --dias 1`: as 7 com `linhas ≥ 1` e `status` de sucesso. Registrar no handoff a data do deploy como início da medição dessas 7 para o 02/12.

---

## P1 — Docs (branch `docs/varredura-faxina`, gate)

D-01, D-02, D-03, D-04, D-05, D-06, D-09, D-11. Nenhuma task toca `src/`.

### Task T1.1: desenho, relatório e plano commitados; arquivo morto sai da doc viva

**Files:** Add `docs/superpowers/specs/2026-11-15-varredura-faxina-design.md`, `docs/operacao/varredura-faxina-2026-11-15.md`, este plano. Move (`git mv`): `docs/operacao/sprint-history.md` → `docs/_archive/sprint-history.md`; `docs/superpowers/plans/2026-10-30-varredura-correcoes.md`, `2026-10-31-meta-onda-1-leitura.md`, `2026-11-03-varredura-refatoracao.md`, `2026-11-10-varredura-refatoracao.md` → `docs/_archive/plans/`; `docs/superpowers/specs/2026-05-24-meta-ads-incorporation-design.md`, `2026-05-25-architecture-refactor-design.md` → `docs/_archive/specs/`; `docs/operacao/smoke-saldo-da-conta.md`, `smoke-planejador-de-palavras.md` → `docs/_archive/runbooks/`. Modify: os citantes (README, `findings-catalog.md`, `phase-3b-4x-*-smoke.md`, handoff de 10/11, `levantamento-recomendacoes-v25-2026-11-11.md`, specs que citam as de maio, `docs/_archive/README.md`), `docs/operacao/estado-atual.md` (link para `guia-alerta-de-saldo.md`).

- [ ] **Step 1:** commit só dos 3 arquivos novos: `docs(operacao): desenho, relatório e plano da varredura de faxina`.
- [ ] **Step 2:** `git mv` dos 9 arquivos. Script descartável no scratchpad reescreve os links relativos em toda doc viva (raiz, `docs/operacao`, `docs/convencoes`, `docs/superpowers`, `.claude/`, `.codex/`) que apontem para os caminhos antigos, recalculando o relativo a partir do arquivo citante. Citação por texto em código (`src/db/migrations/003_meta_schema.sql`) fica como está.
- [ ] **Step 3:** `docs/_archive/README.md`: "Quando usar" deixa de mandar para o `sprint-history` como doc diária. `estado-atual.md`: uma linha em "Pendências do Wellington" (ou equivalente) com link para `guia-alerta-de-saldo.md`, mantendo o arquivo dentro do teto de tamanho.
- [ ] **Step 4:** `D:/v4-ads-mcp/.venv/Scripts/python.exe -m pytest tests/unit/test_docs_links.py tests/unit/test_resumo_bate_com_o_detalhe.py tests/unit/test_tooling_parity.py -q`. Expected: PASS. `git grep -n "operacao/sprint-history\|plans/2026-10-30\|plans/2026-10-31\|plans/2026-11-03\|plans/2026-11-10\|specs/2026-05-2[45]\|smoke-saldo-da-conta\|smoke-planejador" -- ':!docs/_archive'` lista só a migration 003 e o catálogo onde a citação é por texto histórico. Gate = 0. Commit `docs: arquiva sprint-history, planos e specs entregues e smokes executados`.

### Task T1.2: cauda histórica do `infra-setup.md`

**Files:** Modify `docs/operacao/infra-setup.md:182-274`; Create `docs/_archive/setup/infra-setup-historico.md`.

- [ ] **Step 1:** mover para o arquivo novo as seções "GCP project (HISTÓRICO…)", "Phase sign-offs" e "Phase FE Redesign v2". "GitHub", "Supabase" e "Google Ads": ficam na parte viva só se cada linha confere com o estado atual (projeto `v4-ads-mcp`, host `v4-ads-mcp-299432068772…`, CSS offline); linha com fato aposentado vai para o histórico. No lugar, uma linha de ponteiro com link para o histórico.
- [ ] **Step 2:** `git grep -n "jf26mmrgqa\|v4-ads-mcp-prod\|Tailwind CDN" docs/operacao/infra-setup.md` → vazio. `test_docs_links.py` PASS. Gate = 0. Commit `docs(operacao): infra-setup só com o estado atual`.

### Task T1.3: fatos desatualizados no README, `CLAUDE.md` e `nucleo.md`

**Files:** Modify `README.md:19-21,34-35,53,68` e seção Deploy; `CLAUDE.md:17`; `docs/convencoes/nucleo.md:76`.

- [ ] **Step 1:** `CLAUDE.md:17`: `google-ads>=33.0.0`. `nucleo.md:76`: troca "Hoje 18 das 28 tools computam e ignoram" por "quantas computam e ignoram é derivado pelo guard `test_blast_radius_bate_com_as_tools.py`". README: o parágrafo Stack e os tempos do gate viram ponteiro para a seção do `CLAUDE.md` (sem número sem guard); linha `auth/` sem "Meta" no OAuth; "116 IDs" sai (fica "busca dirigida"); Deploy ganha uma linha: push só de `docs/` não deploya (F138), com ponteiro para o `CLAUDE.md`.
- [ ] **Step 2:** `grep -n "27.0.0\|~50s\|60-90s\|116 IDs\|Hoje 18 das 28" README.md CLAUDE.md docs/convencoes/nucleo.md` → vazio. `test_docs_links.py` (inclui o orçamento do `CLAUDE.md`) PASS. Gate = 0. Commit `docs: README, CLAUDE.md e nucleo sem fato velho`.

### Task T1.4: subagente de smoke aponta para runbooks que existem

**Files:** Modify `.claude/agents/smoke-runbook-generator.md:3,34-36` e `.codex/agents/smoke-runbook-generator.toml:2,31-33` (o `.toml` tem CRLF: preservar).

- [ ] **Step 1:** nos dois, trocar os 3 caminhos por `docs/operacao/phase-3b-42-ad-schedule-smoke.md`, `phase-3b-43-particao-horaria-smoke.md`, `phase-3b-44-bid-modifier-smoke.md` (conferir o nome exato com `ls docs/operacao/phase-3b-4*`), cada um com uma linha do que ele ensina, e o `description` passa a "latest 3 existing runbooks (3b.42/3b.43/3b.44)" e o nome do arquivo gerado segue o padrão `phase-3b-XX-<tema>-smoke.md`.
- [ ] **Step 2:** `test_tooling_parity.py` PASS (os dois iguais); cada caminho citado existe (`ls`). Gate = 0. Commit `docs: smoke-runbook-generator aponta para os runbooks vivos`.

### Task T1.5: script do callback Meta e comentários velhos dos workflows

**Files:** `git mv scripts/test_meta_deletion_callback.py scripts/gerar_signed_request_meta.py`; Modify `.github/workflows/deploy.yml:44,375`, `.github/workflows/ci.yml:33-35`.

- [ ] **Step 1:** no script, a URL dos exemplos da docstring vem de `get_settings().public_base_url` impressa pelo próprio script (nenhum host fixo no texto); o SIM108 da linha 33 vira expressão condicional. `ruff check scripts/gerar_signed_request_meta.py` limpo; `python scripts/gerar_signed_request_meta.py <segredo-de-teste-qualquer>` imprime o `signed_request` e os comandos com o host atual.
- [ ] **Step 2:** apagar o trecho "que e a pendencia 1b do estado-atual" (`deploy.yml:44`, reescrevendo a frase sem a referência), a frase "O comentario anterior dizia o contrario." (`deploy.yml:375`) e o comentário do `services: postgres` removido (`ci.yml:33-35`). `JOB_SECRETS_RETIRADOS` não muda.
- [ ] **Step 3:** `pytest tests/unit/test_ci_deploy_gate.py tests/unit/test_deploy_job_image_order.py tests/unit/test_deploy_jobs_retiram_secrets.py tests/unit/test_ci_local_parity.py -q` PASS. Gate = 0. Commit `chore: script do callback Meta sem host velho e workflows sem comentário de histórico`.

---

## P2 — Gate mais rápido (PR `test/guards-mais-rapidos`, gate)

C-01, C-09. Memoizar sem mudar resposta; os guards seguem mordendo.

### Task T2.1: harness memoiza aliases e mapa de pais

**Files:** Modify `tests/unit/_guard_harness.py:342-358`; Test: `tests/unit/test_guard_harness.py`.

**Interfaces — Produces:**
- `nomes_locais(arv: ast.Module, alvo: str) -> set[str]` — mesma assinatura e semântica; devolve conjunto **novo** a cada chamada. Por baixo, `_aliases(arv) -> Mapping[str, frozenset[str]]` (alvo → asnames, chave `a.name` para `ImportFrom` e `a.name.rpartition(".")[2]` para `Import`) calculado num walk e guardado **no próprio nó** (`setattr(arv, "_h_aliases", ...)`): morre com a árvore, sem cache global, sem reuso de `id`.
- `nomes_chamados(arv: ast.Module) -> frozenset[str]` — todo nome que alguma `ast.Call` do módulo chama (`Name.id`, `Attribute.attr`), mais o nome original de cada alias chamado. `alvo in nomes_chamados(arv)` ⇔ `chama(arv, alvo, arv=arv)`. Memoizado no nó.
- `pais(arv: ast.Module) -> Mapping[ast.AST, ast.AST]` — filho → pai de **todo** nó, memoizado no nó.

- [ ] **Step 1: testes de equivalência (antes de mexer).** Copiar o corpo atual de `nomes_locais` para o teste como `_nomes_locais_referencia`. `test_nomes_locais_equivale_a_referencia`: para toda árvore de `h.fontes_py() + h.testes_py()`, para todo nome importado nela mais `"ensure_account_access"`, `"classify"`, `"cursor"`, os dois dão o mesmo conjunto. `test_nomes_chamados_equivale_a_chama`: todas as árvores de `h.testes_py()` × 5 alvos (`run_mutation`, `create_pending`, `build_campaign_status`, o primeiro e o último builder de `get_builder` em ordem alfabética). `test_pais_equivale_a_construcao_por_walk`: em 20 árvores, `pais(arv)` == `{f: n for n in ast.walk(arv) for f in ast.iter_child_nodes(n)}`. `test_memo_e_por_arvore`: duas árvores do mesmo texto com alias diferente injetado numa delas (`ast.parse` de dois textos) dão respostas diferentes; `nomes_locais(arv, x).add("y")` não contamina a chamada seguinte. Rodar no código atual (com `nomes_chamados` e `pais` ainda inexistentes: só o primeiro roda). Expected: PASS no primeiro.
- [ ] **Step 2:** implementar as três funções. Sabotagem: memo com chave só por `alvo` (ignorando a árvore) → `test_memo_e_por_arvore` e `test_nomes_locais_equivale_a_referencia` vermelhos; desfazer.
- [ ] **Step 3:** rodar `tests/unit/test_guard_harness.py`. Expected: PASS. Commit `test: harness memoiza aliases e mapa de pais por árvore`.

### Task T2.2: os call-sites lentos usam a memoização, medido antes e depois

**Files:** Modify `tests/unit/test_executor_gates.py:217-241`, `tests/unit/test_tools_schemas.py:499` (`test_every_mutate_builder_has_a_builder_test`), `tests/unit/test_filters_applied_e_derivado.py:373,423`, e as construções de mapa filho→pai em `test_declaracao_de_truncamento.py:175`, `test_ratchet_camadas.py:104,145`, `test_structural_guards.py:830,1255`.

- [ ] **Step 1: medir antes.** `D:/v4-ads-mcp/.venv/Scripts/python.exe -m pytest tests/unit/test_filters_applied_e_derivado.py tests/unit/test_tools_schemas.py tests/unit/test_executor_gates.py tests/unit/test_structural_guards.py -p no:cacheprovider --durations=15 -q > <scratchpad>/durations-antes.txt 2>&1`. Esperado de referência (15/11): 55 s, 34 s e 33 s nos três alvos. Guardar o arquivo.
- [ ] **Step 2:** `_call_sites_do_gate`: `nomes = h.nomes_locais(arv, "ensure_account_access")` uma vez por arquivo, fora do laço de nós. `test_every_mutate_builder_has_a_builder_test`: `chamados = h.nomes_chamados(arv)` uma vez por árvore e `fn.__name__ in chamados`. `test_filters_applied...:423`: o conjunto de aliases montado uma vez por árvore; `:373` passa a `h.pais(arv)`. Nos demais sítios, trocar por `h.pais(arv)` **só** onde a construção é exatamente filho→pai de todo nó; `_funcao_dona` (`test_executor_gates.py:191`) e mapas que guardam outra coisa (função dona, só escopos) ficam — anotar quais ficaram no PR.
- [ ] **Step 3: sabotagem dos guards.** Em cópia de trabalho: tirar `level="read"` de `ensure_account_access` em `src/google_ads/reports.py` → `test_todo_call_site_do_gate_declara_o_nivel` vermelho; renomear o teste de um builder em `tests/unit/test_campaign_mutate_builder.py` (nome que não chame o builder) → `test_every_mutate_builder_has_a_builder_test` vermelho; desfazer os dois por edição.
- [ ] **Step 4: medir depois.** Mesmo comando, para `durations-depois.txt`. Expected: a soma dos três alvos cai abaixo de 15 s. Se não cair abaixo de 30 s, perfilar (`cProfile` no scratchpad) antes de seguir. Os números antes/depois vão no corpo do PR. Gate = 0. Commit `test: guards AST lentos reusam aliases e pais da árvore`.

---

## P3 — Código morto pontual (PR `refactor/codigo-morto-15-11`, gate e `tests/browser`)

A-06, A-07, B-02, B-03, B-05, B-06, B-07, D-12 a–d. **D-12 e (`to_friendly` em `list_gaql_resources`) fica de fora:** muda texto que o gestor vê, contra o não-objetivo do desenho.

### Task T3.1: Google e MCP

**Files:** Modify `src/google_ads/ad_schedule.py:140-144`, `tests/unit/test_ad_schedule_domain.py:129,136,156-157`; `src/mcp/server.py:51-54`; `src/google_ads/queries/experiments.py:24-31,38`, `src/mcp/tools/get_experiments.py:145`, `tests/unit/test_get_experiments.py:307-311`; `tests/unit/test_account_resync.py:60`.

- [ ] **Step 1:** tirar `ScheduleDiff.is_empty`/`op_count`; os 4 asserts viram `diff == ScheduleDiff((), (), ())` onde a comparação é com vazio, e `not (diff.to_add or diff.to_remove or diff.to_update)` onde o assert é só de vazio. Tirar `_Scope`, `_ASGIReceive`, `_ASGISend` e o comentário "ASGI callable types"; os imports de `typing`/`collections.abc` que sobrarem sem uso saem (ruff diz). `DAILY_QUOTA_STANDARD` fica.
- [ ] **Step 2:** `experimentos_query() -> str` sem parâmetro (só a `base`); o call-site passa a `experimentos_query()`; `test_experimentos_query_filtra_id_com_f87` sai (a validação `_id` segue coberta pelos testes de `anuncios`/`metricas`). Em `anuncios_query`, tirar `ad_group_ad.ad.final_urls` do SELECT; ajustar o teste de string da query, se houver.
- [ ] **Step 3:** `_base_patches` sem o parâmetro `manager` e sem o comentário que o justificava.
- [ ] **Step 4:** `pytest tests/unit/test_ad_schedule_domain.py tests/unit/test_get_experiments.py tests/unit/test_account_resync.py tests/unit/test_schemas_snapshot.py -q` PASS; `vulture src --min-confidence 60` (venv descartável) não lista mais os itens. Gate = 0. Commit `refactor(mcp): tira código sem uso de ad_schedule, server e experimentos`.

### Task T3.2: Meta e db

**Files:** Modify `src/db/repositories/meta_rate_counters.py:1-21`, `src/meta_ads/labels.py:45-56`, `src/meta_ads/insights.py:29`, `src/meta_ads/moeda.py:22-37`, `src/mcp/tools/meta_get_budget_pacing.py:263`, `src/mcp/tools/meta_get_entities.py:91`.

- [ ] **Step 1:** tirar `MetaRateCounter` e os imports que só ela usava (`dataclass`, `date`). Tirar `META_EFFECTIVE_STATUS_LABELS` (contraria a nota do F54 "o mapa segue para enriquecimento futuro"; a decisão de 15/11 é mais nova e remove). Tirar o alias `Breakdown` e o import de `Literal` se sobrar sem uso. `exigir_brl` perde `session_id` (assinatura e frase da docstring "session_id fica na assinatura do contrato"); os 2 call-sites deixam de passá-lo.
- [ ] **Step 2:** `git grep -n "MetaRateCounter\|META_EFFECTIVE_STATUS_LABELS\|\bBreakdown\b" -- src tests` → vazio. `pytest tests/unit/test_meta_erro.py tests/unit/test_meta_pacing.py tests/unit/test_meta_get_entities_tool.py tests/unit/test_meta_insights.py -q` PASS. Gate = 0. Commit `refactor(meta_ads): tira dataclass, mapa, alias e parâmetro sem uso`.

### Task T3.3: painel

**Files:** Modify `src/web/templates/_components.html:55-61`; Delete `src/web/static/logo/logo_v4_puro_round_transparente.svg`.

- [ ] **Step 1:** tirar a macro `radio`; tirar o SVG. `python scripts/build_tailwind.py`; se `src/web/static/v4-tailwind.css` mudar, entra no mesmo commit.
- [ ] **Step 2:** `git grep -n "import radio\|radio(\|logo_v4_puro_round_transparente" -- src tests` → vazio. `D:/v4-ads-mcp/.venv/Scripts/python.exe -m pytest tests/browser -q` PASS. Gate = 0. Commit `refactor(web): tira macro radio e logo sem referência`.

**Pronto do P3:** depois do deploy, `get_experiments` numa conta real em sessão nova (a GAQL de `anuncios_query` mudou) devolve sem erro, e uma página do painel com `_components.html` abre.

---

## P4 — Testes duplicados (PR `test/faxina-de-testes`, gate; full sweep se tocar `tests/integration/`)

C-02, C-03, C-04, C-05, C-07, C-08. Nenhum arquivo de `src/` muda.

### Task T4.1: baseline de coleta e os testes de schema subsumidos

**Files:** Modify `tests/unit/test_tools_schemas.py:185,277`, `tests/unit/test_create_and_link_assets.py:196`, `tests/unit/test_import_offline_conversions.py:173`, `tests/unit/test_update_conversion_action.py:10,18`, `tests/unit/test_upload_customer_match_list.py:14,23`, `tests/unit/test_meta_errors.py:236`.

**Interfaces — Produces:** `<scratchpad>/coleta-antes.txt` (nodeids ordenados) e `<scratchpad>/pass-antes.txt` (linha final do pytest), usados por T4.2–T4.4.

- [ ] **Step 1: baseline.** `D:/v4-ads-mcp/.venv/Scripts/python.exe -m pytest tests/unit tests/integration --collect-only -q -p no:cacheprovider > <scratchpad>/coleta-bruta.txt 2>&1`; `grep "::" <scratchpad>/coleta-bruta.txt | sort > <scratchpad>/coleta-antes.txt`; `wc -l` dá N. `pytest tests/unit -q -p no:cacheprovider > <scratchpad>/pass-antes.txt 2>&1` — guardar "X passed".
- [ ] **Step 2:** em `test_tools_schemas.py`, criar `test_every_tool_has_explicit_property_types` sobre o registry inteiro (mesma travessia do `_walk` dos testes por tool, com mensagem `tool.name` + caminho da propriedade). Sabotagem: tirar o `"type"` de uma propriedade de `update_conversion_action` em cópia → vermelho com o caminho; desfazer.
- [ ] **Step 3:** remover os 4 `test_schema_has_no_composition_keywords` por tool (subsumidos por `test_no_composition_keywords_in_any_schema`) e os 2 `test_schema_explicit_types` por tool. Fundir `test_all_phase_2_tools_registered` e `test_no_unexpected_tools` num só, `test_registry_e_a_lista_escrita`, com **igualdade** (`actual == expected`, mensagem com `faltando` e `inesperadas`). Em `test_meta_errors.py:236`, o teste vira `test_5xx_sem_envelope_e_retryable`: mesmos 3 corpos e mesmos asserts, sem a história do SDK na docstring e sem `patch.dict` de `sys.modules`; `test_errors_py_nao_depende_mais_do_sdk_facebook_business` fica.
- [ ] **Step 4:** nova coleta; `diff coleta-antes.txt coleta-depois.txt` mostra **exatamente**: −4 composition, −2 explicit_types por tool, −2 (`test_all_phase_2_tools_registered`, `test_no_unexpected_tools`), +1 `test_registry_e_a_lista_escrita`, +1 `test_every_tool_has_explicit_property_types`, ±1 renomeado em `test_meta_errors.py`. Qualquer outra linha: pare. Gate = 0. Commit `test: schema guard global no lugar das cópias por tool`.

### Task T4.2: uma fixture de contexto MCP

**Files:** Create `tests/unit/conftest.py`; Modify os arquivos com `_ctx`, `bound_context` e `session_ctx` copiados (≈100; listar com o hash AST do relatório C, script no scratchpad).

**Interfaces — Produces:** fixture **não-autouse** `ctx_mcp() -> Iterator[McpRequestContext]` em `tests/unit/conftest.py`: `set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))`, `yield ctx`, `clear_current()`.

- [ ] **Step 1:** agrupar as cópias por hash AST (ignorando nome e docstring). Só migra cópia **idêntica** a uma das formas: autouse sem retorno → o arquivo ganha `pytestmark = pytest.mark.usefixtures("ctx_mcp")` (ou acrescenta à lista existente) e perde a fixture; não-autouse usada por parâmetro → o parâmetro passa a `ctx_mcp`; a que faz `yield ctx` → `ctx_mcp` direto. Variantes com stub de `_hoje` ou campos extras **não migram** (listar no PR).
- [ ] **Step 2:** migrar um grupo por commit. Depois de cada grupo: coleta nova == `coleta-antes.txt` (menos os deltas de T4.1) e `pytest tests/unit -q -p no:cacheprovider` com o mesmo número de PASS. Expected: diff vazio. Se um arquivo de `tests/integration/` entrar, full sweep.
- [ ] **Step 3:** `git grep -n "def bound_context\|def session_ctx\|^def _ctx" tests` só lista as variantes não migradas. Gate = 0. Commits `test: <grupo> usa a fixture ctx_mcp`.

### Task T4.3: fakes de pool e de client num lugar só

**Files:** Modify `tests/unit/fixtures/fake_pool.py`; Create `tests/unit/fixtures/fake_google_client.py`; Modify os arquivos com `_pool_with_transactable_conn` (×9), `_FakePool`/`_FakeAcquire` (`test_db_connection.py:29`, `test_health_resilience.py:22`, `test_hot_reads_reconnect.py:45`), `_client_with_responses` (`test_add_keywords.py`, `test_apply_audience.py`, `test_remove_audience.py`), `_fake_success_client` (×2).

**Interfaces — Produces:** em `fake_pool.py`, `pool_com_transacao(conn: Any | None = None) -> MagicMock` (conn com `transaction()` que é context manager async de verdade) e `class PoolSequencial` (entrega conexões em sequência, expõe `acquires: int`); em `fake_google_client.py`, `client_com_respostas(...)` e `client_de_sucesso(...)` com a assinatura da cópia que migra.

- [ ] **Step 1:** pelo hash AST, só as cópias idênticas migram; a cópia divergente fica local e vai listada no PR com a diferença.
- [ ] **Step 2:** trocar a definição local por import. Depois: coleta == baseline e mesmo número de PASS em `tests/unit`. Gate = 0. Commit `test: fakes de pool e de client do Google compartilhados`.

### Task T4.4: helpers dos guards de "conta ativa" no harness

**Files:** Modify `tests/unit/_guard_harness.py`, `tests/unit/test_gate_google_exige_conta_ativa.py`, `test_gate_meta_exige_conta_ativa.py`, `test_list_queues_google_predicado_is_active.py`, `test_fila_saiu_da_parceria_alcanca_a_volta.py`; Test: `tests/unit/test_guard_harness.py`.

**Interfaces — Produces:** no harness, `e_conjuncao_pura`, `tem_join_puro_para`, `achar_funcao`, `sql_sem_docstring`, `tem_predicado_bem_formado`, com a assinatura da cópia que migra.

- [ ] **Step 1:** hash AST das cópias. Idênticas migram; divergentes ficam e vão no PR (unificar divergência muda guard: fora desta task).
- [ ] **Step 2:** em `test_guard_harness.py`, para cada helper movido, um caso que casa e um que não casa (tirados de fixtures que os 4 guards já usam).
- [ ] **Step 3:** os 4 arquivos importam do harness. Sabotagem: no harness, `tem_predicado_bem_formado` devolvendo sempre `True` → o caso sintético de "acusa" de cada guard que o usa fica vermelho (prova que o guard passa pelo helper movido); desfazer por edição. Coleta == baseline. Gate = 0. Commit `test: helpers de SQL dos guards de conta ativa no harness`.

---

## P5 — Duplicação em `src` (PR `refactor/duplicacao-src-15-11`, full sweep, `tests/browser`)

A-03, A-05, A-08, B-08, B-09.

### Task T5.1: bifurcação AUTO/CONFIRM num helper

**Files:** Modify `src/mcp/tools/_mutate_common.py`; as tools que passam no critério do Step 1 entre `update_campaign_status.py`, `update_ad_group_status.py`, `update_ad_status.py`, `update_keyword_status.py`, `update_keyword_bid.py`, `update_ad_group_bid.py`, `update_conversion_action.py`, `add_keywords.py`, `apply_audience.py`; `tests/unit/test_blast_radius_bate_com_as_tools.py:57-62`. Test: `tests/unit/test_bifurcacao_auto_confirm.py` (novo).

**Interfaces — Produces:** `async def aplicar_ou_pedir_confirmacao(ctx: Any, *, operation: str, customer_id: str, payload: dict[str, Any], target_count: int, resumo: str, risk: RiskClassification, params_summary: dict[str, Any] | None = None) -> dict[str, Any]` em `_mutate_common.py`: `risk.level == RiskLevel.AUTO` → `run_mutation(...)` + `applied_envelope(operation, customer_id, resumo, applied_count=..., provider_request_id=..., auto_applied_reason=risk.reason)`; senão `emitir_preview(ctx, operation=..., customer_id=..., payload=..., resumo=..., risk=...)`.

- [ ] **Step 1: critério.** Migra a tool cujo ramo AUTO é exatamente `run_mutation` (com ou sem `params_summary`) seguido de `applied_envelope` sem kwargs além dos acima, e cujo ramo CONFIRM é `emitir_preview` sem `**extra`. Medido em 15/11: `update_keyword_status` usa `create_pending` direto (allowlist de `test_ratchet_camadas.py:56`) e **não** migra. Listar no PR as que migram e as que ficam, com o motivo.
- [ ] **Step 2: caracterização antes.** `test_bifurcacao_auto_confirm.py`, parametrizado nas tools que migram × {AUTO, CONFIRM}: `classify` trocado para devolver o nível; `run_mutation`, `emitir_preview` e `get_current` trocados por fakes que gravam kwargs; o envelope devolvido e os kwargs gravados comparados com um dict escrito no teste a partir do código atual. Rodar. Expected: PASS.
- [ ] **Step 3: o guard do F112 aprende o helper.** Hoje a tool que lê `.level` sai da cobrança e a que não lê precisa de caminho fixo visível; depois da troca, nenhuma das duas coisas aparece no source da tool, e ela cai em `caminho_ambiguo`. Acrescentar ao guard `_RAMIFICADORES = ("aplicar_ou_pedir_confirmacao",)`: passar o nome ligado a `classify` como `risk=` a um ramificador conta como ler `.level`. Teste sintético novo na tabela de `test_casador_de_level_so_conta_o_resultado_do_classify`: `risk=classify(...)` passado ao helper → `le_level=True`; `risk=RiskClassification(...)` literal → `le_level=False`. É edição de guard: sabotagem obrigatória (passar `risk=outra_coisa` numa tool migrada → `test_particao_das_tools_e_exata` vermelho; desfazer).
- [ ] **Step 4:** implementar o helper e trocar o corpo das tools que migram por uma chamada a ele. Rodar a caracterização, `test_blast_radius_bate_com_as_tools.py`, `test_schemas_snapshot.py` (sem regravar) e os testes de cada tool. Expected: PASS. Gate = 0. Commit `refactor(mcp): bifurcação AUTO/CONFIRM num helper`.

### Task T5.2: fragmentos de schema repetidos

**Files:** Modify `src/mcp/tools/_common.py:15-54`, `audit_quality_score.py:47-98`, `audit_zombie_keywords.py:38-86`, `audit_orphan_smart_actions.py:48-93`, `detect_drift.py` (bloco start/end); `src/mcp/tools/_meta_common.py`, `_meta_performance.py:64-83`, `meta_get_performance_breakdown.py:76-95`.

**Interfaces — Produces:** `def propriedades_start_end() -> dict[str, Any]` em `_common.py` (cópia profunda de `_START_E_END`); `def propriedades_de_janela_meta() -> dict[str, Any]` em `_meta_common.py` com `date_range` (enum e description atuais), `start_date`, `end_date` e `limit` do bloco idêntico.

- [ ] **Step 1:** só troca o bloco que for **igual** ao fragmento (comparar `json.dumps(..., sort_keys=True)` num teste descartável). `date_range` das 3 de auditoria continua próprio (descrição e enum diferentes). Pares do A-08 fora do Meta (`get_budget_pacing` × `get_recommendations`, `create_rsa` × `update_rsa`, `get_search_terms_report` × `get_ad_performance`) ficam, como o relatório sugere.
- [ ] **Step 2:** `test_schemas_snapshot.py` PASS **sem** `V4_REGRAVAR_SCHEMAS`; `test_tools_schemas.py` PASS. Gate = 0. Commit `refactor(mcp): start/end e janela Meta como fragmento comum`.

### Task T5.3: leituras das rotas gêmeas de acesso por plataforma

**Files:** Modify `src/web/routes/_acesso.py:27-57` (`PlataformaAcesso`), `src/web/routes/admin_access.py:30-100,172-248,288-364`. Test: `tests/integration/test_web_panel_accounts.py`, `test_admin_meta_access.py`, `test_admin_access_idempotente.py`, `tests/unit/test_acesso_templates_snapshot.py`, `tests/browser`.

**Interfaces — Produces:** `PlataformaAcesso.inventario: ModuleType` (`google_ads_accounts` / `meta_ad_accounts`); em `admin_access.py`, `async def _pagina_matriz(request, user, plataforma) -> HTMLResponse`, `_pagina_por_gestor(request, user, plataforma) -> HTMLResponse`, `_pagina_detalhe(request, user, plataforma, manager_id: UUID) -> HTMLResponse`. As 6 rotas continuam com o mesmo nome, path e ordem, e cada uma vira `_require_admin(user)` + chamada ao helper com `PLATAFORMAS[...]`.

- [ ] **Step 1:** os testes de integração das 6 páginas e `tests/unit/test_acesso_templates_snapshot.py` rodam verdes antes (rede). Se alguma das 6 não tiver teste que confira o HTML, escrever um que compare com o snapshot existente antes de mexer.
- [ ] **Step 2:** mover o `_load` e o `TemplateResponse` para os helpers; a chave do `access_set` usa `plataforma.coluna_conta`; `pending_invites_count()` continua fora do bloco de conexão (F92); leitura continua via repositório (o ratchet `_SQL_EM_ROTA_CONHECIDO` segue vazio).
- [ ] **Step 3:** `test_tabela_de_rotas_e_estavel.py` (fixture `tabela_de_rotas.json` sem mudança), `test_acesso_templates_snapshot.py`, `test_ratchet_camadas.py`, `tests/browser` PASS; full sweep. Gate = 0. Commit `refactor(web): páginas de acesso Google e Meta num helper por tipo`.

### Task T5.4: cópia de campos do plano de reconciliação

**Files:** Modify `src/reconciliacao.py`, `src/google_ads/reconcile.py:100-106`, `src/meta_ads/reconcile.py:110-120`. Test: `tests/unit/test_reconcile_paridade.py`.

**Interfaces — Produces:** `def campos_do_plano(p: PlanoNeutro) -> dict[str, Any]` em `reconciliacao.py` (`{f.name: getattr(p, f.name) for f in fields(p)}`); Google `Plan(**campos_do_plano(p))`; Meta `Plan(**campos_do_plano(p), unreachable=unreachable)`. Os dois `Plan` continuam classes próprias (identidade de tipo e `repr` em log não mudam).

- [ ] **Step 1: teste que falha.** `test_campos_do_plano_cobre_os_dois_planos`: `{f.name for f in fields(PlanoNeutro)}` ⊆ campos do `Plan` Google e do Meta, e `campos_do_plano` devolve exatamente os de `PlanoNeutro`. Rodar: FAIL (função não existe).
- [ ] **Step 2:** implementar e trocar os dois `return Plan(...)`; o comentário do Meta sobre `unreachable` fica no Meta.
- [ ] **Step 3:** `test_reconcile_paridade.py`, `test_google_reconcile.py`, `test_meta_reconcile_plan.py`, `test_meta_reconcile_job.py` PASS. Sabotagem: Meta passa `to_bump=p.to_remove` → paridade vermelha; desfazer. Full sweep = 0. Commit `refactor: plano de reconciliação copiado por uma função do núcleo`.

**Pronto do P5:** depois do deploy, clique em produção nas 6 páginas de acesso (Google e Meta) e um dry-run de uma tool migrada em T5.1 **com o Wellington presente**; aplicar só com aval nominal na sessão.

---

## P6 — Esqueleto dos executores (PR `refactor/esqueleto-executores`, full sweep)

A-02. Desenho: **o gate e a reserva ficam em cada executor** (o gate, no topo, fora de `try`; `CALL_SITES_DO_GATE` não muda), e o `try/except` de cada um também fica, porque a tradução de erro difere de verdade (`run_report` levanta `to_friendly` dentro; `run_keyword_planning` deixa `QuotaExhausted` intacto e traduz o resto depois do `finally`; `run_conversion_upload` recalcula `status_audit`). O que vira helper é o `finally`, onde moraram F73, F83 e F91: reconciliar se reservou, e gravar o audit num bloco `best_effort` independente.

### Task T6.1: caracterização dos 6 executores

**Files:** Create `tests/unit/test_executores_caracterizacao.py`.

**Interfaces — Produces:** fixture `gravador` (fakes de `ensure_account_access`, `reservar_cota`, `build_client_for_manager`, `reconciliar_cota`, `audit_log.record` e da chamada ao SDK, todos anotando num `list[str]` de eventos e guardando kwargs), reusada por T6.3–T6.5.

- [ ] **Step 1:** montar a matriz executor × cenário a partir dos testes que já existem (`test_executor_bookkeeping_never_masks.py`, `test_run_*_quota_reserve.py`, `test_run_conversion_upload_audit.py`, `test_report_audit_optin.py`) e escrever só as células que faltam. Executores: `run_report`, `run_keyword_planning`, `run_offline_user_data_job`, `run_conversion_upload`, `run_mutation`, `run_recommendation_action`. Cenários: (a) sucesso — ordem `gate → reserva → client → sdk → reconcile → audit`, e os kwargs do `audit_log.record` iguais a um dict escrito no teste; (b) erro do SDK — tipo da exceção que sobe, `actual_ops` do reconcile e `status`/`error_message` do audit; (c) `QuotaExhausted` na reserva — nenhum reconcile, audit gravado (nos que auditam sempre) e a exceção sobe intacta; (d) `audit_log.record` levantando — o retorno de (a) e a exceção de (b) não mudam; (e) `record_actual` levantando dentro do reconcile — o audit é gravado mesmo assim; (f) só `run_report`: `audit_this_call=False` → nenhum `acquire` para audit.
- [ ] **Step 2:** rodar no código atual. Expected: PASS em tudo. Célula vermelha aqui é bug medido: pare e leve ao Wellington antes de refatorar.
- [ ] **Step 3:** commit `test: caracterização do bookkeeping dos executores Google`.

### Task T6.2: `encerrar_execucao` e os guards que o vigiam

**Files:** Create `src/governance/execucao.py`; Modify `tests/unit/test_structural_guards.py:1263-1330` (`test_reconciliar_cota_faz_todo_io_sob_best_effort`, parte 2). Test: `tests/unit/test_execucao.py` (novo).

**Interfaces — Produces:**
- `@dataclass(frozen=True, slots=True) class RegistroDeAudit` com os kwargs de `audit_log.record` que os executores passam: `manager_id: UUID`, `session_id: UUID`, `customer_id: str`, `action_type: Literal["read", "mutate"]`, `operation: str`, `status: str`, `target_count: int | None = None`, `params_summary: dict[str, Any] | None = None`, `provider_request_id: str | None = None`, `error_message: str | None = None`, `duration_ms: int | None = None`, `platform: Literal["google", "meta"] = "google"`, `had_effect: bool | None = None`.
- `async def encerrar_execucao(pool: PoolValidado, reserva: Reserva | None, *, manager_id: UUID, actual_ops: int, operation: str, customer_id: str, status: str, evento_cota: str, evento_audit: str, montar_audit: Callable[[], RegistroDeAudit] | None) -> None`. Dois statements irmãos: `if reserva is not None: await reconciliar_cota(...)`; depois, se `montar_audit is not None`, `async with best_effort(evento_audit, operation=..., customer_id=..., status=...), pool.acquire() as conn:` → `audit_log.record(conn, **asdict(montar_audit()))`. `montar_audit` é chamado **dentro** do `best_effort`: hoje `run_conversion_upload` calcula `status_audit` e o resumo lá dentro, e tirá-los de baixo do `best_effort` deixaria uma exceção nesse cálculo descartar o `return` de upload já feito.

- [ ] **Step 1: testes que falham.** `test_sem_reserva_nao_reconcilia_e_audita`; `test_reconcile_que_falha_nao_pula_o_audit` (`record_actual` levantando); `test_audit_que_falha_nao_levanta`; `test_montador_que_levanta_nao_levanta` (Review Focus 5); `test_sem_montador_nao_pega_conexao` (pool fake conta `acquires == 1` só do reconcile). Rodar: FAIL (módulo não existe).
- [ ] **Step 2:** implementar. Sabotagens, cada uma desfeita por edição: (1) audit dentro do `if reserva is not None` → `test_sem_reserva_nao_reconcilia_e_audita` vermelho; (2) `montar_audit()` chamado antes do `async with` → `test_montador_que_levanta_nao_levanta` vermelho; (3) `pool.acquire()` antes do `best_effort` na lista do `async with` → guard do Step 3 vermelho.
- [ ] **Step 3: guards.** Em `test_structural_guards.py`, a parte 2 de `test_reconciliar_cota_faz_todo_io_sob_best_effort` passa a exigir: cada um dos 5 arquivos de executor chama `encerrar_execucao` num `finally`; `reconciliar_cota` é chamado só em `src/governance/execucao.py`; nenhum `audit_log.record` dentro de `finally` em `src/google_ads/`. E `test_encerrar_execucao_faz_o_audit_sob_best_effort`: em `encerrar_execucao`, todo `acquire` está sob `best_effort` aberto antes dele (reusar `_io_de_cota_fora_do_best_effort`). É edição de guard: rodar contra o código de agora — a parte nova fica vermelha listando os 5 executores (ainda não migrados), e é isso que T6.3–T6.5 fecham. Para não deixar o gate vermelho entre tasks, a lista de executores migrados é uma constante `_EXECUTORES_NO_ESQUELETO` que cresce a cada task, com o par "barra regressão" + "descreve a realidade".
- [ ] **Step 4:** `pytest tests/unit/test_execucao.py tests/unit/test_structural_guards.py -q` PASS (com `_EXECUTORES_NO_ESQUELETO` vazio). Gate = 0. Commit `refactor(governance): encerrar_execucao concentra reconcile e audit do finally`.

### Task T6.3: `run_report` e `run_keyword_planning`

**Files:** Modify `src/google_ads/reports.py:117-160`, `src/google_ads/keyword_planning.py:125-170`, `tests/unit/test_structural_guards.py` (`_EXECUTORES_NO_ESQUELETO`).

- [ ] **Step 1:** o `finally` de cada um vira uma chamada a `encerrar_execucao`, com `montar_audit` = closure que monta o `RegistroDeAudit` com os mesmos campos de hoje (`run_report`: `None` quando `audit_this_call` é falso). Gate, reserva e `try/except` não mudam.
- [ ] **Step 2:** `test_executores_caracterizacao.py -k "run_report or run_keyword_planning"`, `test_run_report_quota_reserve.py`, `test_run_keyword_planning.py`, `test_report_audit_optin.py`, `test_executor_gates.py` (tabela **sem** edição), `test_structural_guards.py` PASS. Gate = 0. Commit `refactor(mcp): run_report e run_keyword_planning no esqueleto comum`.

### Task T6.4: `run_conversion_upload` e `run_offline_user_data_job`

**Files:** Modify `src/google_ads/conversions.py:180-230`, `src/google_ads/customer_match.py:378-430`, `tests/unit/test_structural_guards.py`.

- [ ] **Step 1:** idem T6.3. Em `conversions.py`, o cálculo de `status_audit`, `medido` e `resumo` vai inteiro para dentro do `montar_audit` (continua sob `best_effort`); `status` do envelope não muda. Em `customer_match.py`, o resumo de "onde parou" (R1-I3/I4) vai para o `montar_audit` do mesmo jeito.
- [ ] **Step 2:** caracterização `-k "conversion or offline"`, `test_run_conversion_upload_audit.py`, `test_run_conversion_upload_quota_reserve.py`, os testes de customer match e `test_structural_guards.py` PASS. Gate = 0. Commit `refactor(mcp): uploads no esqueleto comum`.

### Task T6.5: `run_mutation` e `run_recommendation_action`

**Files:** Modify `src/google_ads/mutations.py:383-440,520-560`, `tests/unit/test_structural_guards.py`.

- [ ] **Step 1:** idem. Em `run_mutation`, `base_summary`, a chave `resultado` (R1-I2) e `had_effect` vêm do `montar_audit`; o `log.info("mutation_executed", ...)` fica no executor, depois de `encerrar_execucao`.
- [ ] **Step 2:** com `_EXECUTORES_NO_ESQUELETO` completo, o guard da parte 2 cobra os 5 arquivos. Caracterização completa, `test_executor_bookkeeping_never_masks.py`, `test_mutations_partial_failure.py`, `test_run_mutation_quota_reserve.py`, `test_structural_guards.py`, `test_executor_gates.py` PASS. `git grep -n "reconciliar_cota(" -- src` → só `governance/execucao.py` e a definição. Sabotagem final: no `run_mutation`, voltar a chamar `reconciliar_cota` direto no `finally` → guard vermelho; desfazer. Gate = 0; full sweep = 0. Commit `refactor(mcp): mutações no esqueleto comum`.

**Pronto do P6:** depois do deploy (aval nominal), uma leitura real (`get_campaign_performance`) e um `plan_keyword_ideas` em sessão nova, com a linha de audit conferida pelo `scripts/medir_uso_tools.py --dias 1`; um dry-run de mutação **com o Wellington presente**; aplicar só com aval nominal na sessão.
