# Roadmap de Melhorias — 5 ondas (hardening → consolidação)

> **Status:** design aprovado (brainstorming 2026-06-20). Próximo: `superpowers:writing-plans` **por onda, on-demand** (não tudo de uma vez).
> **Escopo:** roadmap guarda-chuva das **11 melhorias** da investigação 2026-06-20, agrupadas em **5 ondas independentes**. Profundidade graduada: **Onda 1 em nível de implementação** (executa já); **Ondas 2-5 em nível de design** (cada uma vira plano próprio quando for executada).
> **Origem:** investigação multi-agente 2026-06-20 (code quality · testes · arquitetura · segurança · ops). **Não confundir** com [`2026-06-20-google-performance-breakdown-design.md`](2026-06-20-google-performance-breakdown-design.md) (mesma data, tool única da Fase 2A).

## 0. Rastreabilidade (11 itens → 5 ondas)

| # | Item da investigação | Onda |
|---|---|---|
| 1 | Instrumentar sinal de uso (destrava gate da Fase 2B) | **1** |
| 3 | Boundary de erro no dispatcher MCP (vaza internals) | **1** |
| 4 | Logs estruturados (denials/erros/resync silenciosos) | **1** |
| 5 | Smoke do deploy usa `/health` raso, não `?deep=1` | **1** |
| 11 | Limpezas (constante morta, scripts dup, doc-drift) | **1** |
| 2 | Cobertura de testes dos builders de mutate (classe F50/F51) | **2** |
| 6 | Filtros server-side + payload budget (dor #1 do dogfood) | **3** |
| 7 | Consolidação Meta 3→1 (`meta_get_performance_breakdown`) | **4** |
| 8 | Refatorar `run_mutation` (função de 100 linhas) | **4** |
| 9 | Dedup `_classify_partial` (copiado em 4 tools) | **4** |
| 10 | Resync Meta nunca desativa contas churned | **5** |

## 1. Objetivo

Endereçar, de forma faseada e rastreável, as 11 oportunidades levantadas na investigação. A **Onda 1** é a de maior ROI e a única com pré-requisito de roadmap: ela **destrava honestamente o gate da Fase 2B** — a investigação descobriu que os 8 reports consolidados pela 2A **não escrevem no `audit_log`** (`run_report(..., audit_this_call=False)` por default, [`reports.py:50`](../../../src/google_ads/reports.py)), então o soak gate *"zero-uso por N dias no `audit_log`"* mede zero por construção, vacuamente.

## 2. Decisões do brainstorming

| Decisão | Escolha | Motivo |
|---|---|---|
| **Empacotamento** | 1 roadmap-spec, profundidade graduada | Atende o pedido ("todas num spec") + YAGNI (não especular 5 specs detalhadas de trabalho que pode mudar de escopo). Ondas 2-5 viram plano on-demand. |
| **#1 — sinal de uso** | `audit_this_call=True` nos 8 reports | Sem IAM no GCP → métrica de Cloud Logging **inviável de operar**. O `audit_log` mora no Postgres → consultável via **Supabase MCP** (sem grant GCP). |
| **Onda 3 — escopo dos filtros** | Só `get_keyword_performance` + `get_search_terms_report` | YAGNI — são as 2 tools citadas no dogfood; os demais reads não pediram. |
| **Onda 4 — consolidação** | **Aditiva** (não remove nada) | Espelha a 2A. Tombstone de tools = decisão pós-uso, não acoplada à entrega. |
| **Fase 2B** | **Fora** — Onda 1 só destrava o gate | Tombstone dos 8 reports é sprint pós-soak próprio (3 skills V4 dependentes). |
| **Ordem de execução** | 1→2→3→4→5 recomendada, **não amarrada** | Onda 1 destrava roadmap + maior ROI; gestor reordena na execução. |

---

## 3. Onda 1 — Hardening + Observabilidade + Instrumentação · *S–M, 1 PR* · **detalhada**

Fecha o boundary de erro, torna eventos invisíveis em greppáveis, e destrava o gate da 2B. Tudo em um PR coeso (completa a "Onda 0/1" da sessão 2026-06-20).

### 3.1 · #3 Boundary de erro no dispatcher

`src/mcp/server.py` — `call_tool` invoca `await tool.handler(args)` em [`server.py:102`](../../../src/mcp/server.py) **sem try/except**. Exceção inesperada (KeyError num row_formatter, erro asyncpg em `before_call`/`record_actual`, `MessageToDict` em `run_gaql`) propaga crua pro SDK MCP → `str(exc)` pode conter SQL/driver/internals. Negação de acesso e erros friendly também escapam como exceção, não como result limpo.

- Envolver **apenas** a chamada do handler (linha 102) em try/except. **Manter** o tratamento de `jsonschema.ValidationError` como está (mensagem útil, não vaza).
- Mapeamento → retorno `[TextContent(json(envelope))]`:
  - `AccountAccessDeniedError` / `MetaAccessDeniedError` → `{"status":"denied","error_message": e.message}` (preserva a msg PT-BR acionável "peça ao admin").
  - `GoogleAdsFriendlyError` / `QuotaExhausted` → `{"status":"error","error_message": <msg PT-BR>}` (**preservar** — auto-corrige clientes LLM, F62).
  - catch-all `Exception` → `log.exception("tool_handler_error", tool=name)` server-side + `{"status":"error","error_message":"Erro interno ao executar a ferramenta."}` genérico (sem internals).
- Mesmo scrub no fallback de auth `mcp_endpoint` ([`server.py:133-138`](../../../src/mcp/server.py)): logar `str(e)` server-side, retornar `"Erro interno"` genérico ao cliente (hoje devolve `str(e)` cru a um caller não-autenticado).

### 3.2 · #4 Logs estruturados nos pontos cegos

`merge_contextvars` já anexa `manager_id`/`session_id` (Onda 1 da sessão 2026-06-20) — basta emitir.

- **Negação Google** ([`access.py`](../../../src/google_ads/access.py)): `log` está importado (linha 15) e **nunca chamado**. Adicionar `log.warning("account_access_denied", manager_id=…, customer_id=…, operation=operation_name, level=level)` antes do `raise` (linha 54). A negação já é auditada; falta o log.
- **Negação Meta** (`src/meta_ads/reports.py`, no `can_manager_access` de `run_meta_graph_get`): `log.warning` simétrico (o plano confirma o file:line exato). Já auditada desde 2026-06-20; falta o log.
- **Tool errors:** coberto pelo `log.exception` do §3.1.
- **Resync** (`src/jobs/account_resync.py` + `src/jobs/meta_resync.py`): hoje só `log.info("resync_complete")` (structlog). Adicionar **1 linha `audit_log.record(operation="account_resync"/"meta_resync", action_type="read", status=…, target_count=n, manager_id=None)`** por run — o `audit_log` aceita `manager_id=None` (precedente: callback de data-deletion Meta). Torna "rodou ontem?" respondível via Supabase MCP.

### 3.3 · #1 Instrumentar uso (destrava o gate da 2B)

`audit_this_call=True` nos **8 reports consolidados pela 2A**:
`get_campaign_performance`, `get_ad_group_performance`, `get_ad_performance`, `get_keyword_performance`, `get_audience_performance`, `get_device_performance`, `get_geo_performance`, `get_hourly_performance` (todos em `src/mcp/tools/`).

- 1 linha por tool no call de `run_report` (parâmetro já existe, [`reports.py:50`](../../../src/google_ads/reports.py); o `finally` já grava quando `True`, linhas 112-126).
- **Reinicia o relógio do soak da Fase 2B** a partir do deploy desta onda (a data ~07-11 do CLAUDE.md deixa de valer — passa a `deploy_onda_1 + janela`).
- Custo: +1 insert por chamada nesses 8 reads de alto volume. Aceitável (`audit_log.id` é BIGSERIAL barato) e dá observabilidade de uso contínua — sinergia com §3.2.

### 3.4 · #5 Smoke do deploy usa readiness real

`.github/workflows/deploy.yml` (linha ~128) faz `curl /health` raso (`{"status":"ok"}` estático). A Onda 1 da sessão 2026-06-20 criou `/health?deep=1` (faz `SELECT 1` no pool) **exatamente** pra impedir "deploy com DB inacessível passa o smoke" — mas o gate não usa.

- Trocar o smoke pra `/health?deep=1` + assert `"db":"ok"` no corpo. Migrations já rodam com `--wait` antes (linha ~85) — esse branch fica intacto.

### 3.5 · #11 Limpezas (hygiene + doc-drift)

- Remover `METRIC_FIELDS` (dict morto, [`queries/_common.py:185-196`](../../../src/google_ads/queries/_common.py); grep retorna só a definição) — escapou do `69a7f2d "drop dead constants"`.
- Remover os 4 scripts one-off duplicados `scripts/tag_tool_buckets{,_v2,_v3,_final}.py` (tags de bucket já estão inline em cada tool).
- Corrigir doc-drift no `CLAUDE.md`: `resolve_date_window` está em `src/google_ads/queries/_common.py`, não em `src/mcp/tools/_common.py` (existem dois `_common.py`).

### 3.6 · Testes & critério de pronto

- **Boundary (§3.1):** teste no dispatcher (`build_server().call_tool`) — handler que levanta `Exception` inesperada → envelope genérico (sem o texto da exceção original); que levanta `AccountAccessDeniedError` → `{"status":"denied"}`; que levanta `GoogleAdsFriendlyError` → msg PT-BR preservada.
- **Logs (§3.2):** asserção via `structlog` capture que a negação emite `account_access_denied`; que o resync grava 1 linha em `audit_log` (integração, consome o resultado).
- **Instrumentação (§3.3):** integração — chamar 1 dos 8 reports com `audit_this_call` agora `True` grava linha no `audit_log` (seed com grant, senão hard-gate levanta).
- **Deploy (§3.4):** smoke `?deep=1` verde no run de deploy (validação no CI, não local).
- **Pronto:** `check_pre_push.py` verde + (por mexer em audit/integração) **full sweep Docker** + deploy smoke `?deep=1` verde + linha de audit visível por report no Supabase MCP.

### 3.7 · Riscos

- **Mudança de shape de erro** pode afetar clientes que hoje esperam o `raise` cru — mitigado preservando as msgs friendly/denied (só as inesperadas viram genérico).
- **Auditar 8 reads** infla o `audit_log` — aceitável (barato; é a observabilidade do §3.2 de quebra). Se virar problema pós-soak, reverter `audit_this_call` nos que forem tombstonados na 2B.

---

## 4. Onda 2 — Cobertura de testes de mutate · *M* · design

**Objetivo:** fechar a classe **F50/F51** — um builder com nome de campo / `FieldMask` / enum errado passa a suíte inteira e só falha quando um gestor confirma uma mudança real em produção. Os testes dry-run só asseguram `status=="dry_run"`; o builder só roda no apply, e o único teste de apply ([`test_apply_change.py`](../../../tests/integration/test_apply_change.py)) faz stub de `get_builder` → o builder real é bypassado.

**Abordagem:**
- Capture-client builder tests (`make_capture_client`, **nunca** MagicMock) pros **10 builders sem execução** em `src/google_ads/mutates/`: `build_update_campaign_{bidding,budget,status}` (`campaigns.py`), `build_update_ad_group_{bid,status}` (`ad_groups.py`), `build_update_ad_status` (`ads.py`), `build_update_keyword_{bid,status}` (`keywords.py`), `build_add/remove_negative_keywords` (`negatives.py`).
- Asserção **presença E ausência** (guard F51) por branch oneof/`FieldMask` — prioridade pro `build_update_campaign_bidding` (3 branches TARGET_CPA/TARGET_ROAS/MAXIMIZE_CONVERSIONS × {valor, mask path}).
- **Guard estrutural:** teste em `tests/unit/test_tools_schemas.py` que enumera todo `register_builder` e exige um `test_*_builder.py` referenciando-o (espelha `test_registered_tool_count_matches_files_on_disk`). Torna o gap estruturalmente impossível — o guard atual ([`test_tools_schemas.py:59`](../../../tests/unit/test_tools_schemas.py)) só pega MagicMock, não a ausência total de teste.

**Pronto:** cada builder executado por ≥1 teste capture-client; guard novo verde.
**Risco:** baixo (só testes); pode revelar um bug real num builder — desfecho desejável.

## 5. Onda 3 — Dogfood: filtros server-side & payload budget · *M* · design

**Objetivo:** a **dor #1 do dogfood** (citada em 4 sessões, ainda WATCH em `sprint-history.md`): output estoura o cap do MCP (`get_keyword_performance` ~295k chars, `get_negative_keywords_audit` ~705k) → o gestor cai pra Bash+Python. O workflow canônico "top desperdício" (`cost>=3, conv=0`) não é expressável server-side (grep `min_cost_brl|min_clicks` → 0 matches).

**Abordagem:**
- Params `min_cost_brl` / `min_clicks` / `min_conversions` (GAQL `HAVING`) em `get_keyword_performance` + `get_search_terms_report`. Validar a semântica de `HAVING` por métrica no smoke (lição F-findings — descriptor ≠ runtime).
- Helper de **budget de tamanho compartilhado** (cap de char/row com `truncated` honesto) reutilizável pelos reads de alto volume; defaults menores onde aplicável.

**Pronto:** "cost>=3 conv=0" expressável server-side; smoke mostra corte de ~90% no payload das 2 tools.
**Risco:** `HAVING` semantics por métrica — smoke per-combo antes de declarar pronto.

## 6. Onda 4 — Consolidação & dívida estrutural · *M–L* · design

**Objetivo:** matar a duplicação confirmada na investigação. **Aditiva** — nada é removido nesta onda.

- **#7 Meta 3→1:** `meta_get_performance_breakdown(level, breakdown=None)` (`src/mcp/tools/meta_get_performance_breakdown.py`) já retornaria o output das 3 tools de entidade (`meta_get_{campaign,ad_set,ad}_performance`) — o builder (`build_insights_call`) e o parser (`parse_insights_row`, `src/meta_ads/insights.py`) **já são compartilhados e optional-aware**. Manter a consolidada `bucket="always"`. Tombstone das 3 = decisão pós-uso (como a 2B).
- **#8 Refatorar `run_mutation`:** extrair `_parse_partial_failures(response, client)` + `_extract_resource_names(response)` de [`mutations.py`](../../../src/google_ads/mutations.py) (função de ~100 linhas com 5 responsabilidades + oneof-walk duplicado em :178-197 e :224-232). **Comportamento idêntico**; ganho = lógica de classificação testável isolada.
- **#9 Dedup `_classify_partial`:** helper compartilhado `classify_partial(error, *, ok_label, dup_label, patterns)` (hoje copiado em `add_keywords.py`, `add_negatives_from_search_terms.py`, `apply_audience.py`, `remove_audience.py`). Precedente: `_meta_common.py` já hospeda helpers de tool.

**Pronto:** teste de paridade (output Meta consolidado == 3 tools, bit-a-bit no smoke); `run_mutation` refatorado passa **todos** os testes de partial-failure existentes; 1 definição de `classify_partial` no lugar de 4.
**Risco:** refactor em caminho crítico de mutate → **full sweep Docker obrigatório** + paridade bit-a-bit. Fazer os 3 sub-itens em commits separados (não-overlapping).

## 7. Onda 5 — Resync Meta: desativação de contas · *M* · design

**Objetivo:** parar dados stale — uma conta Meta fechada/removida fica `is_active=true` pra sempre (Google já faz deletion-detection em [`account_resync.py`](../../../src/jobs/account_resync.py); Meta só faz `upsert_many`, `is_active` só flipa pra `true`).

**Abordagem:**
- `mark_inactive_except` (já existe em `src/db/repositories/meta_ad_accounts.py`) no `resync_meta` (`src/jobs/meta_resync.py`), **agrupado por `business_id`** — o system user enxerga múltiplos BMs via `/me/adaccounts`; desativar por-BM evita derrubar contas de outro BM que não vieram naquela página.

**Pronto:** teste de integração — conta sumida do `/me/adaccounts` vira `is_active=false`; conta de **outro** BM intacta.
**Risco:** o agrupamento por BM é o ponto fiddly — sem ele, desativa contas erradas. O teste de cross-BM cobre.

---

## 8. Fora de escopo (explícito)

- **Execução da Fase 2B** (tombstone dos 8 reports + atualizar as 3 skills V4) — a Onda 1 só destrava o gate; o tombstone é sprint pós-soak próprio.
- **Tombstone das 3 tools Meta** (pós Onda 4) e **dos reports antigos** — decisão pós-uso, não acoplada.
- **Fases 3 e 4 do refactor** ([`2026-05-25-architecture-refactor-design.md`](2026-05-25-architecture-refactor-design.md)) — viram edição de doc (re-scope), não código. Fase 3 (zombie detection) só é data-driven **depois** do sinal de uso da Onda 1.
- **Backlog não-priorizado:** `verify_campaign_state`, enriquecimento do `get_my_audit_log` (JOIN que `get_by_id` já tem) — ficam no backlog do CLAUDE.md, não entram neste roadmap.

## 9. Sequência & gates

1. **Onda 1** primeiro (destrava roadmap + maior ROI). Deploy → **inicia o soak da 2B** (relógio reinicia aqui).
2. **Onda 2** (risco de correção F50/F51) **ou** **Onda 3** (valor de produto) — gestor escolhe. Recomendação: 2 antes de 3 (a classe de bug já vazou pra prod).
3. **Onda 4** (consolidação) — quando houver folga; full sweep obrigatório.
4. **Onda 5** (resync Meta) — independente, encaixa quando convier.
5. Cada onda: `writing-plans` → `subagent-driven-development`. **Não** gerar os 5 planos de antemão (escopo das Ondas 4-5 pode refinar).

**Decision gate movido:** o checkpoint "soak Fase 2A→2B ~2026-07-11" do CLAUDE.md passa a depender do deploy da Onda 1 (`deploy + janela de soak`), não da data fixa.
