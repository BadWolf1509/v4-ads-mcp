# Planejador de palavras-chave Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Duas tools de leitura — `plan_keyword_ideas` e `get_keyword_metrics` — que trazem ideias de palavras-chave e métricas do Planejador do Google (volume em degraus, concorrência, faixa de CPC de topo, sazonalidade), recortadas por cidade, para o gestor e para a skill de estrutura.

**Architecture:** Dois módulos puros — `src/google_ads/planejador.py` (leitura das métricas com presença, sazonalidade, união por origem, ordem e corte) e `src/google_ads/cidades.py` (resolução de cidade por nome com UF) — e um executor novo `src/google_ads/keyword_planning.py` (`run_keyword_planning`), no padrão dos executores Google (gate, reserva única com `reserved`, `run_blocking`, audit sempre). As tools são finas: montam as requisições num closure que o executor roda.

**Tech Stack:** Python 3.13, `google-ads` 31.4.0 (`KeywordPlanIdeaService`, `GeoTargetConstantService`, versão default do SDK), pytest.

**Spec:** `docs/superpowers/specs/2026-10-29-planejador-de-palavras-design.md` — leia inteiro antes da Task 1; os números dos testes vêm da §1.

## Global Constraints

- Volume vem em **degraus do Google**, não exato; a resposta diz isso (`volume_em_degraus: true`) e a description também.
- "Sem dado" = `null`, **nunca 0**: ler com presença (`"keyword_idea_metrics" in r`, `"keyword_metrics" in r`, `"avg_monthly_searches" in m`); sem presença → `None` (fato 6).
- CPC = `low_top_of_page_bid_micros` / `high_top_of_page_bid_micros`, rotulado como estimativa de topo de página do Google; campos `_brl` assumem conta em BRL (dito na description).
- `customer_id` **obrigatório**, passa por `ensure_account_access` (nível `read`), sem default e sem exceção no gate. A description diz que o resultado não depende da conta (fato 9).
- Idioma `languageConstants/1014`; rede `GOOGLE_SEARCH`; sem cidade → `geoTargetConstants/2076` (Brasil), dito na resposta.
- **Uma chamada por (origem × cidade)**; sementes em `keyword_seed`, cada URL em `url_seed` — **nunca** `keyword_and_url_seed` (fato 3: derruba para 40).
- Várias cidades → métricas **por cidade**, sem soma (fato 10). Teto: **5 cidades**.
- `limit` default **200**, teto **1000**; ordem por maior volume entre as cidades, `None` por último; `truncated` + `total_ideias`.
- `get_keyword_metrics`: teto de **1000** termos.
- Falha de uma **URL** não derruba as outras (`origens_com_falha`); erro com `code` em `{"QUOTA_ERROR", "AUTHORIZATION_ERROR", "AUTHENTICATION_ERROR"}` ou falha das **sementes** derruba a requisição.
- Reserva de quota **única por requisição** com `estimated_ops` = total previsto (padrão `run_offline_user_data_job`); audit sempre, `action_type="read"`, sem PII.
- Fixtures de API **copiadas do `repr` da resposta crua**, nunca da saída impressa (lição do U+00A0).
- Gate: `D:/v4-ads-mcp/.venv/Scripts/python.exe scripts/check_pre_push.py`, mudo, ler `$?`. Uma task por commit. Commits terminam com `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- As duas tools com `bucket="defer"` e description começando por `"[DEFER] "`.

## Review Focus

1. **Nome de cidade ambíguo sem UF** ("Campina Grande" → também "Campina Grande do Sul"/PR e "Campinas"/SP): escolhe o **primeiro City** da sugestão e ecoa qual escolheu; com UF, só City daquele estado. Teste na Task 3.
2. **Mesma ideia vinda de duas origens** (semente e site) com métricas iguais: aparece **uma vez**, com as duas origens. Teste na Task 2.
3. **Termo com capitalização/acentos diferentes entre origens** ("Locação" vs "locação"): une por texto normalizado, mantém o primeiro texto visto. Teste na Task 2.
4. **URL do concorrente inválida** (Google recusa só ela): as outras origens voltam e a falha aparece em `origens_com_falha`. Teste na Task 5.
5. **Mês com volume zero na série de 12 meses**: `variacao_12m_pct` com primeiro mês 0 é `None` (razão indefinida, `razao()` do `_common`). Teste na Task 2.

---

### Task 1: Sondagem versionada

**Files:**
- Create: `scripts/probe_keyword_planner.py`

**Interfaces:**
- Produces: nada importado; registra os fatos 2–6, 9 e 10 da spec.

- [ ] **Step 1:** Escreva a sonda no formato das `scripts/probe_*` (docstring com propósito, uso `python -m scripts.probe_keyword_planner <customer_id>`, segredos via `gcloud` com `shell=(sys.platform == "win32")`, nunca imprimir segredo, nunca `2>/dev/null`). Ela monta o cliente como o `build_client_for_manager` (refresh token do gestor lido do banco em transação `readonly`, decifrado com `decrypt_refresh_token`; `MANAGER` por argumento ou env) e roda, imprimindo só forma e números:
  1. ideias com sementes `["aluguel de andaime", "locação de equipamentos"]` no Brasil e em `1001622` (João Pessoa): contagem e volume de "aluguel de andaime";
  2. a mesma com `url_seed` `https://www.mestredaobra.com.br`: contagem;
  3. JP, Campina Grande (`1001621`) e as duas numa chamada: o volume de "aluguel de andaime" em cada;
  4. `generate_keyword_historical_metrics` com `["aluguel de andaime", "xyzzy termo inexistente"]`: presença de `keyword_metrics`;
  5. `suggest_geo_target_constants` para "João Pessoa" e "Campina Grande": o **`repr`** de cada sugestão (`resource_name`, `name`, `target_type`, `canonical_name`).
  Docstring com o resultado de 29/10: 1.923 ideias (BR e JP), 40 com URL, JP 40 / CG 20 / juntas 50, inexistente sem `keyword_metrics`, `1001622` City "Joao Pessoa,State of Paraiba,Brazil".
- [ ] **Step 2: Run** `D:/v4-ads-mcp/.venv/Scripts/python.exe -m scripts.probe_keyword_planner 6728568947` — Expected: os números acima (o volume pode variar mês a mês; a forma não). Salve a saída do item 5 no relatório: é a fixture da Task 3.
- [ ] **Step 3: Gate e commit** `chore(scripts): sonda do planejador de palavras-chave`.

### Task 2: Módulo puro `src/google_ads/planejador.py`

**Files:**
- Create: `src/google_ads/planejador.py`
- Test: `tests/unit/test_planejador.py`

**Interfaces:**
- Consumes: `razao`, `micros_to_currency` de `src/google_ads/queries/_common.py`.
- Produces:
  - `Metricas = TypedDict("Metricas", {"volume_mensal": int | None, "concorrencia": str | None, "indice_concorrencia": int | None, "cpc_topo_min_brl": float | None, "cpc_topo_max_brl": float | None, "sazonalidade": dict[str, Any] | None})`
  - `def metricas_do_proto(m: Any | None) -> Metricas` — `m` é `KeywordPlanHistoricalMetrics` (ou `None` quando o bloco não veio). Sem bloco → todos `None`. `volume_mensal` só com `"avg_monthly_searches" in m`; `concorrencia` = `m.competition.name` exceto `UNSPECIFIED`/`UNKNOWN` → `None`; CPC só com presença do campo.
  - `def sazonalidade(meses: Sequence[Any]) -> dict[str, Any] | None` — `meses` são `MonthlySearchVolume` (`year`, `month` enum, `monthly_searches`). Menos de 12 → `None`. Saída `{"mes_pico": "AAAA-MM", "mes_vale": "AAAA-MM", "variacao_12m_pct": float | None}`; variação = (último − primeiro) / primeiro × 100 pela `razao()` (primeiro 0 → `None`), 1 casa. Empate de pico/vale: o mês mais recente.
  - `def normalizar_termo(t: str) -> str` — minúsculas, sem acento (NFKD), espaços colapsados.
  - `@dataclass class Ideia: termo: str; origens: list[str]; por_cidade: dict[str, Metricas]`
  - `def unir(lotes: Iterable[tuple[str, str, Iterable[tuple[str, Metricas]]]]) -> list[Ideia]` — cada lote é `(origem, cidade, [(termo, metricas), ...])`. Une por `normalizar_termo`; o primeiro texto visto fica; origens sem repetição, na ordem em que aparecem; `por_cidade[cidade]` = a primeira métrica vista para aquela cidade.
  - `def volume_maximo(i: Ideia) -> int | None` — maior `volume_mensal` não-`None` entre as cidades.
  - `def ordenar_e_cortar(ideias: list[Ideia], limit: int) -> tuple[list[Ideia], bool]` — por `volume_maximo` desc, `None` por último, desempate por `termo`; devolve `(cortada, truncated)`.

- [ ] **Step 1: Write the failing tests** com **mensagens reais do SDK**, importadas da versão default do `google-ads` 31.4.0 (`v25`, conferido em 29/10): `from google.ads.googleads.v25.common.types.keyword_plan_common import KeywordPlanHistoricalMetrics, MonthlySearchVolume`; resultados em `google.ads.googleads.v25.services.types.keyword_plan_idea_service` (`GenerateKeywordIdeaResult`, `GenerateKeywordHistoricalMetricsResult`); sugestão de cidade em `...services.types.geo_target_constant_service` (`GeoTargetConstantSuggestion`). Conferido: `"avg_monthly_searches" in KeywordPlanHistoricalMetrics()` é `False`, e `"keyword_metrics" in GenerateKeywordHistoricalMetricsResult(text="x")` é `False`.
  - `test_bloco_ausente_e_tudo_none` — `metricas_do_proto(None)` → todos `None`.
  - `test_volume_presente_e_lido` — `avg_monthly_searches=8100`, `competition=HIGH`, `competition_index=76`, `low=3_000_000`, `high=12_500_000` → `8100, "HIGH", 76, 3.0, 12.5`.
  - `test_volume_ausente_nao_vira_zero` — proto `KeywordPlanHistoricalMetrics()` vazio → `volume_mensal is None` e `concorrencia is None` (falha se ler `.avg_monthly_searches` sem presença).
  - `test_sazonalidade_pico_vale_variacao` — 12 meses nov/2025..out/2026 com valores 100..210 (passo 10), pico em out/2026 → `mes_pico == "2026-10"`, `mes_vale == "2025-11"`, `variacao_12m_pct == 110.0`.
  - `test_sazonalidade_primeiro_zero_e_none` (Review Focus 5).
  - `test_sazonalidade_menos_de_12_meses_e_none`.
  - `test_unir_mesma_ideia_duas_origens` (Review Focus 2) — `("semente","JP",[("aluguel de andaime", m)])` + `("site","JP",[("aluguel de andaime", m)])` → 1 ideia, `origens == ["semente","site"]`.
  - `test_unir_normaliza_acento_e_caixa` (Review Focus 3) — "Locação de andaimes" e "locacao de andaimes" → 1 ideia, termo "Locação de andaimes".
  - `test_unir_duas_cidades` — mesma ideia em "João Pessoa (PB)" com 40 e "Campina Grande (PB)" com 20 → `por_cidade` com as duas, `volume_maximo == 40`, **sem chave de soma**.
  - `test_ordem_none_por_ultimo_e_corte` — volumes `[None, 10, 8100, 40]`, `limit=2` → `[8100, 40]`, `truncated is True`.
- [ ] **Step 2: Run** `pytest tests/unit/test_planejador.py -v` — FAIL (módulo inexistente).
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** — PASS. Sabote `metricas_do_proto` para ler o valor sem presença e confirme que `test_volume_ausente_nao_vira_zero` falha; desfaça.
- [ ] **Step 5: Gate e commit** `feat(mcp): leitura das metricas do planejador com presenca e uniao por origem`.

### Task 3: Resolução de cidade `src/google_ads/cidades.py`

**Files:**
- Create: `src/google_ads/cidades.py`
- Test: `tests/unit/test_cidades.py`

**Interfaces:**
- Produces:
  - `UF_PARA_ESTADO: dict[str, str]` — as 27 siglas → nome como o Google escreve no `canonical_name` (`"PB": "State of Paraiba"`, `"SP": "State of Sao Paulo"`, `"DF": "Federal District"`… confira os que não seguem "State of X" no `repr` do Step 1 da Task 1 ou com uma chamada da sonda).
  - `def separar_uf(entrada: str) -> tuple[str, str | None]` — `"João Pessoa, PB"` → `("João Pessoa", "PB")`; aceita nome por extenso (`"Paraíba"`) normalizado para a sigla; sem estado → `None`.
  - `@dataclass(frozen=True) class Cidade: pedido: str; resource_name: str; nome: str; canonical_name: str`
  - `class CidadeNaoResolvida(ValueError)` com `pedido` e `candidatos: list[str]`.
  - `def escolher_cidade(pedido: str, uf: str | None, sugestoes: Sequence[Any]) -> Cidade` — `sugestoes` são `GeoTargetConstantSuggestion`. Primeiro com `geo_target_constant.target_type == "City"`; com `uf`, o primeiro City cujo `canonical_name` termina em `f"{UF_PARA_ESTADO[uf]},Brazil"`. Nenhum → `CidadeNaoResolvida` com os `canonical_name` dos candidatos.
  - `def rotulo(c: Cidade) -> str` — `"João Pessoa (PB)"` (nome + sigla derivada do `canonical_name`), chave de `por_cidade`.

- [ ] **Step 1: Write the failing tests** com `GeoTargetConstantSuggestion` reais montadas **a partir do `repr` do relatório da Task 1** (Global Constraints):
  - `test_joao_pessoa_escolhe_city_pb` — sugestões na ordem medida (1001622 City PB, 9248071 Neighborhood SC, 20098 State, CEPs) → `resource_name == "geoTargetConstants/1001622"`.
  - `test_campina_grande_sem_uf_pega_primeiro_city` (Review Focus 1) → `1001621`.
  - `test_campina_grande_com_uf_pr_pega_do_sul` — `uf="PR"` → `1031525` (Campina Grande do Sul), provando que a UF filtra.
  - `test_bairro_e_cep_nunca_vencem` — só Neighborhood/Postal Code → `CidadeNaoResolvida` com os candidatos.
  - `test_separar_uf` — `"João Pessoa, PB"`, `"João Pessoa - pb"`, `"Campina Grande, Paraíba"`, `"Recife"`.
  - `test_rotulo` — `"João Pessoa (PB)"`.
- [ ] **Step 2–4:** RED, implementar, GREEN.
- [ ] **Step 5: Gate e commit** `feat(mcp): resolucao de cidade por nome para o planejador`.

### Task 4: Executor `run_keyword_planning`

**Files:**
- Create: `src/google_ads/keyword_planning.py`
- Modify: `tests/unit/test_executor_gates.py` (o executor entra nas listas parametrizadas, nível `read`)
- Test: `tests/unit/test_run_keyword_planning.py`

**Interfaces:**
- Produces:
  ```python
  async def run_keyword_planning(
      *, manager_id: UUID, session_id: UUID, customer_id: str, operation_name: str,
      estimated_ops: int, params_summary: dict[str, Any],
      chamadas: Callable[[Any], T],   # recebe o GoogleAdsClient, roda DENTRO do run_blocking
  ) -> T
  ```
  Ordem, copiada de `customer_match.run_offline_user_data_job`: `ensure_account_access(..., level="read")` via `run_with_reconnect` → reserva `before_call` global + `mgr:<uuid>` na transação externa → `reserved=True` → `build_client_for_manager` → `run_blocking(lambda: chamadas(client))` com `reset_request_id`/`get_request_id` lido dentro → `except`: `to_friendly(e)` → `finally`: `record_actual` gated por `reserved` (`actual_ops = estimated_ops` em sucesso, 0 em erro) e `audit_log.record(action_type="read", operation=operation_name, target_count=<len do resultado se for sized, senão None>, params_summary=params_summary, status=...)`, ambos em `best_effort`. Erro sobe como `GoogleAdsFriendlyError`.

- [ ] **Step 1: Write the failing tests** no estilo de `tests/unit/test_run_offline_user_data_job.py` (mesmos patches de `connection`, `before_call`, `record_actual`, `audit_log.record`, `build_client_for_manager`):
  - `test_nega_sem_acesso` (também via parametrização do `test_executor_gates.py`).
  - `test_reserva_unica_com_estimated_ops` — `before_call` chamado 2× (global e `mgr:`) com `estimated_ops=7`.
  - `test_quota_esgotada_nao_reconcilia_e_audita` (F73).
  - `test_chamadas_roda_no_run_blocking` — o closure recebe o client e roda fora do event loop (patch de `run_blocking` registra a chamada).
  - `test_erro_vira_friendly_e_audit_error`.
- [ ] **Step 2–4:** RED, implementar, GREEN. Rode `tests/unit/test_structural_guards.py` (F57 e `run_blocking`) — PASS sem allowlist nova.
- [ ] **Step 5: Gate e commit** `feat(mcp): executor do planejador de palavras-chave`.

### Task 5: Tool `plan_keyword_ideas`

**Files:**
- Create: `src/mcp/tools/plan_keyword_ideas.py` (`# bucket: defer`)
- Modify: `tests/unit/test_tools_schemas.py` (nome nas duas listas)
- Test: `tests/unit/test_plan_keyword_ideas_tool.py`

**Interfaces:**
- Consumes: `run_keyword_planning` (Task 4); `escolher_cidade`, `separar_uf`, `rotulo`, `CidadeNaoResolvida` (Task 3); `metricas_do_proto`, `sazonalidade`, `unir`, `ordenar_e_cortar`, `volume_maximo` (Task 2).
- Produces: schema `{customer_id (^[0-9]{10}$, obrigatório), sementes: string[] (maxItems 20), site: string (uri), concorrentes: string[] (maxItems 5), cidades: string[] (maxItems 5), limit: int 1..1000 default 200}`, pelo menos um de `sementes`/`site`/`concorrentes` (validar na tool com mensagem PT).

Closure `chamadas(client)` (roda no executor): resolve cidades (um `suggest_geo_target_constants` com todos os nomes; `escolher_cidade` por pedido; `CidadeNaoResolvida` sobe e vira erro claro na resposta) → para cada origem (`"semente"` com `keyword_seed`; `"site"` e `f"concorrente:{dominio}"` com `url_seed`) × cada cidade (ou Brasil) → `generate_keyword_ideas` (`page_size=1000`, idioma e rede fixos) → lote para `unir`. Erro numa origem URL: `to_friendly(e)`; `code` em `{"QUOTA_ERROR","AUTHORIZATION_ERROR","AUTHENTICATION_ERROR"}` relança, senão registra em `origens_com_falha` e segue; erro na origem `semente` relança. `estimated_ops = (1 if cidades else 0) + n_origens * max(1, n_cidades)`.

Resposta: `customer_id`, `recorte` (`cidades`: lista de `{pedido, resource_name, canonical_name, rotulo}` ou `"Brasil (geoTargetConstants/2076)"`, idioma, rede), `volume_em_degraus: True`, `ideias` (cada: `termo`, `origens`, `volume_maximo`, `por_cidade`), `total_ideias`, `truncated`, `origens_com_falha`, `avisos`.

Description (sem markdown, PT, começa com "[DEFER] "): volume em degraus do Google, `null` = sem dado (não zero); CPC é estimativa de topo de página, faixa, não o que a conta paga, `_brl` assume conta BRL; resultado não depende da conta (use qualquer conta sua, ex. a interna `6728568947`); site e concorrentes ampliam por origem; cidades por nome (com UF para desambiguar), métricas por cidade sem soma, até 5; ordem por maior volume, `limit` e `truncated`.

- [ ] **Step 1: Write the failing tests** (executor patchado para rodar o closure com um client falso cujos serviços devolvem **mensagens reais do SDK**):
  - `test_sementes_e_site_em_chamadas_separadas` — o falso registra os requests: um com `keyword_seed`, outro com `url_seed`; **nenhum** com `keyword_and_url_seed`.
  - `test_uma_chamada_por_cidade` — 2 cidades × 2 origens → 4 `generate_keyword_ideas`.
  - `test_url_concorrente_falha_e_resto_volta` (Review Focus 4) — o falso levanta `GoogleAdsException` só para a URL do concorrente → `origens_com_falha` com ela, ideias das outras presentes.
  - `test_quota_na_url_derruba_tudo` — `code="QUOTA_ERROR"` na URL → erro.
  - `test_cidade_nao_resolvida_vira_erro_claro` — mensagem com os candidatos.
  - `test_sem_entrada_recusa`.
  - `test_estimated_ops` — 1 cidade, sementes + site + 2 concorrentes → `1 + 4*1 = 5`.
  - `test_description_diz_degraus_null_e_estimativa` — as frases-chave presentes.
- [ ] **Step 2–4:** RED, implementar, GREEN; adicione o nome às duas listas do `test_tools_schemas.py`.
- [ ] **Step 5: Gate e commit** `feat(mcp): plan_keyword_ideas (ideias do planejador por cidade e origem)`.

### Task 6: Tool `get_keyword_metrics`

**Files:**
- Create: `src/mcp/tools/get_keyword_metrics.py` (`# bucket: defer`)
- Modify: `tests/unit/test_tools_schemas.py`
- Test: `tests/unit/test_get_keyword_metrics_tool.py`

**Interfaces:**
- Consumes: Tasks 2–4 (mesmos nomes).
- Produces: schema `{customer_id (obrigatório), termos: string[] (minItems 1, maxItems 1000), cidades: string[] (maxItems 5)}`. Uma `generate_keyword_historical_metrics` por cidade (ou Brasil); `estimated_ops = (1 if cidades else 0) + max(1, n_cidades)`. Resposta: `customer_id`, `recorte`, `volume_em_degraus: True`, `termos` (cada: `termo`, `variantes` = `close_variants`, `por_cidade`), `sem_dado` (termos sem `keyword_metrics` em **todas** as cidades), `avisos`. Ordem: a dos termos pedidos.

- [ ] **Step 1: Write the failing tests:**
  - `test_termo_inexistente_vai_para_sem_dado_com_metricas_none` — resultado sem `keyword_metrics` → `por_cidade[...]["volume_mensal"] is None` e o termo em `sem_dado`.
  - `test_variantes_ecoadas`.
  - `test_ordem_dos_termos_pedidos`.
  - `test_uma_chamada_por_cidade`.
- [ ] **Step 2–4:** RED, implementar, GREEN; nome nas duas listas.
- [ ] **Step 5: Gate e commit** `feat(mcp): get_keyword_metrics (metricas do planejador para lista pronta)`.

### Task 7: Docs, full sweep e roteiro de smoke

**Files:**
- Modify: `CLAUDE.md` (70 → **72** tools; 63 → **65** Google), `docs/operacao/estado-atual.md` (frente construída, aguardando deploy/smoke; buckets +2 defer na linha só depois do deploy)
- Create: `docs/operacao/smoke-planejador-de-palavras.md` (tabela do spec §7, colunas esperado/medido, em sessão NOVA — F140)

- [ ] **Step 1:** Atualize; mantenha a tabela de produção do `estado-atual.md` em 70 até o deploy (nota "em curso").
- [ ] **Step 2:** Gate + full sweep (`scripts/check_pre_push_full.py`; Docker: abra o Docker Desktop se o engine não responder).
- [ ] **Step 3: Commit** `docs(operacao): planejador de palavras-chave no catalogo e roteiro de smoke`.
