# Meta Onda 1: leitura Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Entregar as 10 tools de leitura da Onda 1, começando por `meta_get_entities`, que dá status e orçamento.

**Architecture:** Cada tool segue `src/mcp/tools/meta_get_account_balance.py`: schema, description, `run_meta_graph_get`, envelope `status`. A lógica pura fica em `src/meta_ads/`, testável sem rede. A sonda da Task 1 decide o contrato real antes de qualquer tool.

**Tech Stack:** Python 3.13, Graph API v25 por `httpx`, pytest, `AsyncMock` na fronteira do executor.

**Spec:** `docs/superpowers/specs/2026-10-31-meta-leitura-auditoria-escrita-design.md`

## Global Constraints

- Prefixo `meta_`; `ad_account_id` com pattern `^act_\d+$`.
- Toda chamada à Graph passa por `run_meta_graph_get`, com `edge` contendo `/{ad_account_id}/` (F190). Sem chamada direta.
- Métrica só por `metricas_da_linha`; insights só por `build_insights_call`.
- `null` para o não reportado, nunca `0`. Razão com denominador zero é `null`.
- Janelas por `resolve_meta_date_window`; "hoje" por `resolve_meta_account_today` (F165).
- Campo novo só depois de validado na Task 1. Campo recusado sai da tool.
- `truncated: true` quando houver mais dado que o limite.
- Só conta em BRL onde há dinheiro; outra moeda devolve erro, sem converter.
- Texto de usuário em PT-BR. Sem migration nesta onda. Nenhuma tool escreve.
- Bucket `defer`, exceto `meta_get_entities` em `always`. Primeira linha do arquivo: `# bucket: <valor>`.
- Gate antes de commit: `D:/v4-ads-mcp/.venv/Scripts/python.exe scripts/check_pre_push.py > log 2>&1 && git add ... && git commit ...`.

## Review Focus

1. Conta sem nada da entidade pedida: resposta `success` com lista vazia, nunca erro.
2. Orçamento na campanha (CBO) e não no conjunto: o conjunto traz `null` e a origem do orçamento, sem somar duas vezes no pacing.
3. Status efetivo diferente do configurado (campanha ativa em conjunto pausado): as duas colunas aparecem.
4. Resposta maior que uma página: `max_pages` seguido e `truncated` correto.
5. Campo ausente na linha da Meta: `null`, sem `KeyError`.

---

## File Structure

| Arquivo | Responsabilidade |
|---|---|
| `scripts/sonda_meta_onda1.py` | Sonda de campos da Task 1 |
| `src/meta_ads/entidades.py` | Campos, filtros e parser de campanha, conjunto e anúncio |
| `src/meta_ads/historico.py` | Parser de `activities` |
| `src/meta_ads/criativos.py` | Parser de criativo e prévia |
| `src/meta_ads/pacing.py` | Cálculo de ritmo |
| `src/meta_ads/publicos.py` | Parser de públicos |
| `src/meta_ads/segmentacao.py` | Busca e estimativa |
| `src/mcp/tools/meta_get_*.py`, `meta_search_targeting.py` | Uma tool por arquivo |

### Task 1: Sonda da API real (bloqueia as demais)

**Precisa de aval nominal do Wellington:** usa o token de produção, só com GET, em uma conta interna.

**Files:**
- Create: `scripts/sonda_meta_onda1.py`
- Create: `docs/operacao/sonda-meta-onda1-2026-10-31.md`

- [ ] **Step 1: Escrever a sonda.** Para uma conta, fazer GET com `fields` e registrar status e chaves devolvidas, sem valores de cliente, nas edges: `/{act}/campaigns`, `/adsets`, `/ads`, `/activities`, `/adcreatives`, `/generatepreviews`, `/customaudiences`, `/delivery_estimate`, `/reachestimate`, `/targetingsearch`, `/promote_pages`, `/adspixels`, e o campo `instagram_accounts`.
- [ ] **Step 2: Incluir controle.** Um campo sabidamente inválido em cada edge precisa dar erro; sem isso a sonda não prova nada.
- [ ] **Step 3: Sondar a combinação real.** Rodar cada `fields` completo que a tool vai mandar, não campo a campo.
- [ ] **Step 4: Rodar `ads_get_field_context`** nos mesmos campos, se o MCP oficial estiver disponível; se não, registrar como não rodado.
- [ ] **Step 5: Registrar no documento** campos aceitos, formato do ator em `activities`, unidade do orçamento, e edge de páginas e de pixel.

Expected: documento com uma linha por edge. **Se páginas ou sinais não tiverem edge sob `/{act}/`, a tool correspondente sai da onda**, conforme a spec, e o F190 não é afrouxado.

- [ ] **Step 6: Atualizar as listas de campos das Tasks 2 a 9** com o medido e commitar.

### Task 2: `meta_get_entities`

**Files:**
- Create: `src/meta_ads/entidades.py`, `src/mcp/tools/meta_get_entities.py`
- Test: `tests/unit/test_meta_entidades.py`, `tests/unit/test_meta_get_entities_tool.py`

**Interfaces:**
- Produces: `build_entities_call(level: Literal["campaign","adset","ad"], ad_account_id: str, *, status: str | None, limit: int) -> tuple[str, dict[str, Any]]`; `parse_entity(level: str, linha: dict[str, Any]) -> dict[str, Any]`; `listar_entidades(ctx, ad_account_id, level, status, limit) -> tuple[list[dict[str, Any]], bool]`.

- [ ] **Step 1: Escrever os testes**

```python
def test_status_configurado_e_efetivo_vem_separados():
    linha = {"id": "1", "name": "C", "status": "ACTIVE", "effective_status": "ADSET_PAUSED"}
    r = parse_entity("campaign", linha)
    assert r["status"] == "ACTIVE" and r["effective_status"] == "ADSET_PAUSED"

def test_orcamento_em_centavos_vira_brl():
    assert parse_entity("campaign", {"id": "1", "daily_budget": "15050"})["daily_budget_brl"] == 150.5

def test_conjunto_sem_orcamento_proprio_diz_a_origem():
    r = parse_entity("adset", {"id": "1", "campaign_id": "9"})
    assert r["daily_budget_brl"] is None and r["orcamento_em"] == "campanha"

def test_campo_ausente_e_null():
    assert parse_entity("ad", {"id": "1"})["effective_status"] is None
```

Na tool: conta sem entidade dá `success` com `entities: []`; `limit` menor que o total dá `truncated: true`; conta fora de BRL devolve erro; erro do executor vira `meta_error_message`.

- [ ] **Step 2: Rodar e ver falhar.** Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_meta_entidades.py tests/unit/test_meta_get_entities_tool.py`. Expected: falha de import.
- [ ] **Step 3: Implementar.** Edge `/{act}/campaigns|adsets|ads`; filtro por `filtering` em `effective_status`; `max_pages` calculado de `limit`; `limit` padrão 100, máximo 500; bucket `always`.
- [ ] **Step 4: Rodar os testes.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(meta_ads): meta_get_entities com status e orcamento`.

### Task 3: `meta_get_change_history`

**Files:** Create `src/meta_ads/historico.py`, `src/mcp/tools/meta_get_change_history.py`. Test `tests/unit/test_meta_get_change_history.py`.

**Interfaces:** Produces `parse_atividade(linha: dict[str, Any]) -> dict[str, Any]`, com `ocorrido_em`, `ator_id`, `ator_nome`, `tipo`, `objeto_id`, `objeto_tipo`, `detalhe`. A Onda 2 consome esse formato no drift.

- [ ] **Step 1: Testes.** Mapeamento com a forma medida na Task 1; ator ausente é `null`; período padrão 7 dias, máximo 30; `truncated`; a resposta declara a janela efetiva.
- [ ] **Step 2: Ver falhar.**
- [ ] **Step 3: Implementar** com `since`/`until` no fuso da conta.
- [ ] **Step 4: Passar.**
- [ ] **Step 5: Commit** `feat(meta_ads): meta_get_change_history`.

### Task 4: `meta_get_creatives` e `meta_get_ad_preview`

**Files:** Create `src/meta_ads/criativos.py`, as duas tools. Test `tests/unit/test_meta_criativos.py`.

- [ ] **Step 1: Testes.** Criativo com e sem imagem; `ads_vinculados` por `ad_id` opcional; prévia exige `ad_id` ou `creative_id`, nunca os dois; formato em enum (`MOBILE_FEED_STANDARD`, `INSTAGRAM_STANDARD`, `INSTAGRAM_STORY`, `INSTAGRAM_REELS`, valores da Task 1); `creative_id` de outra conta é recusado porque a edge é `/{act}/generatepreviews`.
- [ ] **Step 2: Ver falhar.**
- [ ] **Step 3: Implementar.** A prévia devolve o `src` do iframe, sem o HTML bruto.
- [ ] **Step 4: Passar.**
- [ ] **Step 5: Commit** `feat(meta_ads): criativos e previa`.

### Task 5: `meta_get_budget_pacing`

**Interfaces:** Consumes `listar_entidades` da Task 2.

**Files:** Create `src/meta_ads/pacing.py`, `src/mcp/tools/meta_get_budget_pacing.py`. Test `tests/unit/test_meta_pacing.py`.

- [ ] **Step 1: Testes.**

```python
def test_dia_corrente_nao_conta_como_dia_inteiro():
    # dia 11 com 1000 gastos em 10 dias fechados: media 100, nao 90,9 (F199)
    assert projetar(gasto_fechado=1000.0, dias_fechados=10, dias_no_mes=30)["media_diaria"] == 100.0

def test_orcamento_de_campanha_nao_soma_com_conjunto():
    assert orcamento_total(campanha=500.0, conjuntos=[None, None]) == 500.0

def test_conjunto_sem_orcamento_legivel_e_null():
    assert orcamento_total(campanha=None, conjuntos=[100.0, None]) is None

def test_orcamento_vitalicio_nao_entra_em_projecao_mensal():
    assert ritmo_de(lifetime_budget=1000.0, daily_budget=None)["projecao"] is None
```

- [ ] **Step 2: Ver falhar.**
- [ ] **Step 3: Implementar.** Mesmo calendário de `get_budget_pacing` (`_calendario`); extrair para função compartilhada se o reuso for direto, sem mudar o comportamento Google.
- [ ] **Step 4: Passar.**
- [ ] **Step 5: Commit** `feat(meta_ads): meta_get_budget_pacing`.

### Task 6: `meta_get_custom_audiences`

**Files:** Create `src/meta_ads/publicos.py`, a tool. Test `tests/unit/test_meta_publicos.py`.

- [ ] **Step 1: Testes.** Faixa de tamanho vira `tamanho_min`/`tamanho_max`; tamanho indisponível é `null`; filtro por subtipo; lista vazia é `success`; nenhum dado de pessoa aparece na resposta.
- [ ] **Step 2: Ver falhar.**
- [ ] **Step 3: Implementar.**
- [ ] **Step 4: Passar.**
- [ ] **Step 5: Commit** `feat(meta_ads): meta_get_custom_audiences`.

### Task 7: `meta_search_targeting` e `meta_get_delivery_estimate`

**Files:** Create `src/meta_ads/segmentacao.py`, as duas tools. Test `tests/unit/test_meta_segmentacao.py`.

- [ ] **Step 1: Testes.** Busca exige `q` com ao menos 2 caracteres; `targeting_spec` inválido devolve erro claro; faixa de alcance com limites separados; estimativa declara `aproximado: true`.
- [ ] **Step 2: Ver falhar.**
- [ ] **Step 3: Implementar** com as edges medidas.
- [ ] **Step 4: Passar.**
- [ ] **Step 5: Commit** `feat(meta_ads): segmentacao e estimativa de entrega`.

### Task 8: `meta_get_pages` (condicional à Task 1)

**Files:** Create a tool. Test `tests/unit/test_meta_get_pages.py`.

- [ ] **Step 1: Testes.** Página sem Instagram traz `instagram_id: null`; lista vazia é `success`.
- [ ] **Step 2: Ver falhar.**
- [ ] **Step 3: Implementar.**
- [ ] **Step 4: Passar.**
- [ ] **Step 5: Commit** `feat(meta_ads): meta_get_pages`.

### Task 9: `meta_get_signal_health` (condicional à Task 1)

**Files:** Create a tool. Test `tests/unit/test_meta_get_signal_health.py`.

- [ ] **Step 1: Testes.** Conta sem pixel devolve `pixels: []` e aviso; evento sem dado de qualidade é `null` com motivo; `ultimo_disparo` no fuso da conta.
- [ ] **Step 2: Ver falhar.**
- [ ] **Step 3: Implementar.**
- [ ] **Step 4: Passar.**
- [ ] **Step 5: Commit** `feat(meta_ads): meta_get_signal_health`.

### Task 10: Fechamento

**Files:** Modify descriptions de `src/mcp/tools/meta_get_campaign_performance.py`, `meta_get_ad_set_performance.py`, `meta_get_ad_performance.py`, `README.md`, `docs/operacao/estado-atual.md`; Create `docs/operacao/tool-buckets-2026-11-01.md` se o guard pedir remedição.

- [ ] **Step 1:** Trocar nas descriptions o aviso de "status não vem" por apontar para `meta_get_entities`.
- [ ] **Step 2:** Atualizar contagens a partir do registry (`import_all_tools()`), nunca por `grep`.
- [ ] **Step 3:** Rodar `mcp-tool-quality-reviewer` nas tools novas e corrigir o que proceder.
- [ ] **Step 4:** Rodar o gate. Expected: `All pre-push checks passed`.
- [ ] **Step 5:** Rodar o full sweep. Expected: `full_exit=0`.
- [ ] **Step 6: Commit** `docs(meta_ads): fecha a onda 1`.

### Depois do merge (com aval nominal de merge e deploy)

- Sessão nova, chamada real de cada tool em duas contas.
- Comparar `meta_get_entities` e `meta_get_budget_pacing` com o Gerenciador em uma conta.
