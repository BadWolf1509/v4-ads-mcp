# Meta Onda 2: auditorias Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Pausado em 02/11:** retomada depende do teste de 30 dias registrado em `docs/operacao/estado-atual.md`.

**Goal:** Entregar as 3 auditorias Meta da Onda 2, que apontam o que corrigir e dizem o que não foi possível medir.

**Architecture:** As tools leem pelas funções da Onda 1 (`listar_entidades`, `listar_atividades`, insights por `build_insights_call`). A regra de cada auditoria é pura e fica em `src/meta_ads/`, com limiares em constantes nomeadas e devolvidos na resposta. A sonda da Task 2 fixa o formato real antes das regras.

**Tech Stack:** Python 3.13, Graph API v25 por `httpx`, pytest, `AsyncMock` na fronteira do executor.

**Spec:** `docs/superpowers/specs/2026-10-31-meta-leitura-auditoria-escrita-design.md`

## Global Constraints

- Prefixo `meta_`; `ad_account_id` com pattern `^act_\d+$`.
- Toda chamada à Graph passa por `run_meta_graph_get`, com `edge` contendo `/{ad_account_id}/` (F190), e passa o `operacao` da própria auditoria, para o uso ser medido por tool.
- Métrica só por `metricas_da_linha`; insights só por `build_insights_call`; "hoje" por `resolve_meta_account_today` (F165). Dia corrente não entra em média (F199).
- Só leitura, sem migration. Bucket `defer`, description `[DEFER]`, texto em PT-BR.
- Limiares em constantes nomeadas e devolvidos em `limiares` na resposta.
- Toda auditoria distingue "sem problema" de "não foi possível medir": dado ausente é `null` com `motivo`, e o resultado traz `cobertura`.
- Medição de campo: na edge, campo inexistente não dá erro; vale o campo aparecer na resposta ou o teste no objeto.
- `effective_status` sozinho não prova entrega: o smoke achou 12 de 19 campanhas ACTIVE com data final vencida. Entidade com `stop_time` ou `end_time` vencido sai da avaliação e conta em `ignoradas`.
- Repositório público: sonda e testes registram forma, sem nome ou valor de cliente.
- Gate antes de commit: `D:/v4-ads-mcp/.venv/Scripts/python.exe scripts/check_pre_push.py > log 2>&1 && git add ... && git commit ...`.

## Review Focus

1. Conta com entidades pausadas ou sem entrega: `problemas: []` e cobertura que mostra o que foi examinado, sem parecer "conta saudável" quando nada rodou.
2. Anúncio com impressões baixas nas duas janelas: fora da fadiga, contado em `sem_medicao`, nunca como "sem fadiga".
3. Janela com mais de uma página: `truncated` em `cobertura`, e `drift: 0` com leitura truncada não vira veredito.
4. Campanha encerrada com `effective_status` ACTIVE, e conjunto ativo sob ela: fora da avaliação, contados em `ignoradas`, sem aparecer como problema nem como saudável.

---

## File Structure

| Arquivo | Responsabilidade |
|---|---|
| `scripts/probe_meta_onda2.py` | Sonda da Task 2 |
| `src/meta_ads/auditoria.py` | `montar_cobertura` e o envelope comum |
| `src/meta_ads/entrega.py` | Regras de `meta_audit_delivery_health` |
| `src/meta_ads/fadiga.py` | Regras de `meta_audit_creative_fatigue` |
| `src/meta_ads/drift.py` | Classificação de eventos de `meta_detect_drift` |
| `src/mcp/tools/meta_audit_*.py`, `meta_detect_drift.py` | Uma tool por arquivo |

### Task 1: Smoke da Onda 1 (pré-requisito, com o gestor)

A Onda 2 é construída sobre tools que nunca rodaram contra a API. O smoke vem antes.

Rodado em 02/11 em três contas. Os 4 defeitos achados foram corrigidos no #203 (`00169-h9n`) e reconferidos em produção. Resultado em `docs/operacao/estado-atual.md`.

- [x] **Step 1:** Em sessão nova, chamar as 8 tools. As 8 rodaram na conta interna; a conta de cliente com campanha ativa rodou 4 delas, mais `meta_get_campaign_performance`.
- [x] **Step 2:** Conferir `meta_get_entities` e `meta_get_budget_pacing` no Gerenciador em uma conta. Feito em 02/11: os números bateram.
- [x] **Step 3:** Conferir filtro de status em conjunto e anúncio, paginação, e se `until` inclui o último dia. Paginação de `meta_get_entities` além de uma página segue não medida: a maior lista teve 19 linhas.
- [x] **Step 4:** Registrar o resultado em `docs/operacao/estado-atual.md`. Defeito achado vira correção antes da Task 2.
- [ ] **Step 5:** Registrar o uso das 8 tools desde o deploy. Não medido, e o período é curto demais para decidir: o deploy foi em 02/11. A decisão de seguir sem essa medição é do Wellington.

Expected: linha de resultado por tool, com conta e data.

### Task 2: Sonda (precisa de aval nominal)

Usa o token de produção, só GET, nas contas autorizadas. A conta interna não serve sozinha: a única campanha dela está pausada. O aval tem de ser digitado pelo Wellington na sessão que roda a sonda: no smoke, o aval repassado por outra sessão foi recusado pelo freio do modo automático.

**Files:** Create `scripts/probe_meta_onda2.py`, `docs/operacao/sonda-meta-onda2.md`.

- [ ] **Step 1: Medir em conjunto ativo:** conteúdo de `learning_stage_info`, `issues_info`, `recommendations`, valores de `effective_status`. No smoke, `learning_stage_info` veio sem `status`, só com `attribution_windows` e, na maioria dos conjuntos, `last_sig_edit_ts`. A sonda procura `status` em conjunto em aprendizado e testa `delivery_sub_status` (`FAIL` = aprendizado limitado) e `delivery` (`completed`), que o catálogo do MCP da Meta lista, sem prova de que vêm pela Graph. Sem nenhum desses valores, a regra de aprendizado limitado sai.
- [ ] **Step 2: Medir em anúncio:** `ad_review_feedback`, `issues_info`, `effective_status` de reprovado e limitado.
- [ ] **Step 3: Medir insights:** `frequency`, `ctr`, `impressions` por anúncio em duas janelas.
- [ ] **Step 4: Medir `activities`:** `event_type` de orçamento e status, inclusive `update_campaign_budget_scheduling_state`, `actor_id` de humano e do system user, e se `application_id` de ação pela API é o `META_APP_ID`. Registrar forma, sem nome de pessoa.
- [ ] **Step 5:** Rodar `ads_get_field_context` nos campos novos das Tasks 4 a 6.
- [ ] **Step 6:** Atualizar as constantes de valor medido das Tasks 3 a 6 e commitar.

Expected: documento com uma linha por sinal, dizendo medido ou não medido. **Sinal não medido sai da regra**, e a resposta declara essa ausência em `nao_medido`.

### Task 3: Envelope comum

**Files:** Create `src/meta_ads/auditoria.py`. Test `tests/unit/test_meta_auditoria.py`.

**Interfaces:**
- Produces: `montar_cobertura(*, examinadas: int, sem_medicao: list[dict[str, Any]], truncated: bool) -> dict[str, Any]`, devolvendo `examinadas`, `medidas`, `sem_medicao`, `truncated`; `montar_resposta(*, ad_account_id: str, date_range: dict[str, str] | None, limiares: dict[str, Any], problemas: list[dict[str, Any]], cobertura: dict[str, Any], nao_medido: list[str]) -> dict[str, Any]`.

- [ ] **Step 1: Testes.**

```python
def test_medidas_desconta_o_sem_medicao():
    c = montar_cobertura(examinadas=5, sem_medicao=[{"id": "1", "motivo": "x"}], truncated=False)
    assert c["medidas"] == 4

def test_veredito_so_com_leitura_completa():
    c = montar_cobertura(examinadas=0, sem_medicao=[], truncated=False)
    assert montar_resposta(ad_account_id="act_1", date_range=None, limiares={}, problemas=[],
                           cobertura=c, nao_medido=[])["veredito"] == "nada_examinado"
    c = montar_cobertura(examinadas=3, sem_medicao=[], truncated=True)
    assert montar_resposta(ad_account_id="act_1", date_range=None, limiares={}, problemas=[],
                           cobertura=c, nao_medido=[])["veredito"] == "parcial"
```

`veredito` é `com_problemas` se houver problema, depois `nada_examinado`, `parcial` (truncado, com `sem_medicao` ou com `nao_medido`) e `sem_problemas`.

- [ ] **Step 2: Ver falhar.** Expected: falha de import.
- [ ] **Step 3: Implementar.**
- [ ] **Step 4: Passar.**
- [ ] **Step 5: Commit** `feat(meta_ads): envelope das auditorias`.

### Task 4: `meta_audit_delivery_health`

**Files:** Create `src/meta_ads/entrega.py`, a tool. Modify `src/mcp/tools/meta_get_budget_pacing.py`, `src/meta_ads/entidades.py`. Test `tests/unit/test_meta_audit_delivery.py`.

**Interfaces:** Consumes `listar_entidades(..., operacao=...)` e o envelope da Task 3. Produces `encerrada(linha: dict[str, Any], campo: str, hoje: date) -> bool` em `src/meta_ads/entidades.py`, movida de `_encerrada` em `meta_get_budget_pacing.py`, que passa a importá-la; `avaliar_conjunto(linha, frequencia)` e `avaliar_anuncio(linha)`, cada uma devolvendo `list[dict[str, Any]]` com `tipo`, `severidade`, `entidade_id`, `entidade_nome`, `detalhe`.

Limiares iniciais: `FREQUENCIA_ALTA = 3.0` em 7 dias fechados, prática comum de saturação em prospecção, ajustável após o smoke.

- [ ] **Step 1: Testes.** Aprendizado limitado com o valor medido gera problema; `learning_stage_info` sem `status` não gera problema nem exceção, e a resposta declara o aprendizado em `nao_medido`; frequência 3,0 não gera e 3,01 gera; frequência `null` entra em `sem_medicao`; anúncio reprovado e com entrega limitada geram problema; entidade fora de `ACTIVE` não é avaliada e conta em `ignoradas`; campanha ACTIVE com `stop_time` vencido, conjunto ACTIVE com `end_time` vencido e conjunto sob campanha encerrada contam em `ignoradas`; conta sem nada dá `nada_examinado`.
- [ ] **Step 2: Ver falhar.**
- [ ] **Step 3: Implementar.** Frequência por conjunto vem de insights de 7 dias fechados.
- [ ] **Step 4: Passar.**
- [ ] **Step 5: Commit** `feat(meta_ads): meta_audit_delivery_health`.

### Task 5: `meta_audit_creative_fatigue`

**Files:** Create `src/meta_ads/fadiga.py`, a tool. Test `tests/unit/test_meta_audit_fatigue.py`.

**Interfaces:** Produces `avaliar_fadiga(atual: dict[str, Any], anterior: dict[str, Any]) -> dict[str, Any]`, com `situacao` em `fadiga`, `sem_fadiga`, `sem_medicao` e `motivo`.

Limiares: `QUEDA_CTR = 0.20`, `ALTA_FREQUENCIA = 0.20`, `MIN_IMPRESSOES = 1000` em cada janela, janela de 7 dias fechados contra os 7 anteriores. O mínimo evita tratar ruído como fadiga.

- [ ] **Step 1: Testes.**

```python
def test_queda_de_ctr_com_alta_de_frequencia_e_fadiga():
    a = {"ctr": 0.008, "frequency": 3.0, "impressions": 2000}
    b = {"ctr": 0.010, "frequency": 2.5, "impressions": 2000}
    assert avaliar_fadiga(a, b)["situacao"] == "fadiga"

def test_queda_de_ctr_sem_alta_de_frequencia_nao_e_fadiga():
    a = {"ctr": 0.008, "frequency": 2.5, "impressions": 2000}
    b = {"ctr": 0.010, "frequency": 2.5, "impressions": 2000}
    assert avaliar_fadiga(a, b)["situacao"] == "sem_fadiga"

def test_poucas_impressoes_nao_mede():
    a = {"ctr": 0.008, "frequency": 3.0, "impressions": 999}
    b = {"ctr": 0.010, "frequency": 2.5, "impressions": 2000}
    assert avaliar_fadiga(a, b)["situacao"] == "sem_medicao"

def test_ctr_nulo_nao_mede():
    a = {"ctr": None, "frequency": 3.0, "impressions": 2000}
    b = {"ctr": 0.010, "frequency": 2.5, "impressions": 2000}
    assert avaliar_fadiga(a, b)["situacao"] == "sem_medicao"
```

Na tool: anúncio presente em só uma janela vai para `sem_medicao`; `limit` padrão 100, máximo 500.

- [ ] **Step 2: Ver falhar.**
- [ ] **Step 3: Implementar.**
- [ ] **Step 4: Passar.**
- [ ] **Step 5: Commit** `feat(meta_ads): meta_audit_creative_fatigue`.

### Task 6: `meta_detect_drift`

**Files:** Create `src/meta_ads/drift.py`, a tool. Modify `src/meta_ads/historico.py`. Test `tests/unit/test_meta_detect_drift.py`.

**Interfaces:**
- Consumes `listar_atividades`, com `aplicacao_id` e `aplicacao_nome` acrescentados a `parse_atividade`.
- Produces `classificar_evento(evento: dict[str, Any], *, autorizados: set[str], app_id: str) -> str`, que devolve `autorizado`, `drift` ou `sistema_sem_auditoria`.

- [ ] **Step 1: Testes.** Ator na lista por ID ou nome é autorizado, ignorando caixa; lista vazia conta tudo como drift; evento vindo do app do MCP é `sistema_sem_auditoria`, e nunca autorizado por nome; ator ausente é drift; flags `status_change_detected` e `budget_change_detected` com os `event_type` medidos; `truncated` impede `veredito: sem_problemas`; evento com `data_nao_verificada` entra na classificação, conta em `sem_medicao` da cobertura e impede `sem_problemas`; o nível do evento sai de `objeto_tipo`, e `detalhe.campaign_id` de conjunto não aparece como campanha.
- [ ] **Step 2: Ver falhar.**
- [ ] **Step 3: Implementar.** `authorized_actors` tem até 20 itens, como `responsible_user_emails`; período padrão 2 dias, máximo 30. A resposta declara em `limitacoes` que toda ação pelo MCP sai como o system user e que, antes da Onda 3, toda ação dele é drift. `detalhe.campaign_id` traz o ID do conjunto, nome antigo da Graph, então a tool não o traduz nem o usa como campanha. Conta sem fuso propaga o `ValueError` de `listar_atividades`, sem veredito.
- [ ] **Step 4: Passar.**
- [ ] **Step 5: Commit** `feat(meta_ads): meta_detect_drift`.

### Task 7: Fechamento

**Files:** Modify `README.md` se o guard pedir, `docs/operacao/estado-atual.md`.

- [ ] **Step 1:** Atualizar contagens pelo registry (83 tools esperadas).
- [ ] **Step 2:** Rodar `mcp-tool-quality-reviewer` nas 3 tools e corrigir o que proceder.
- [ ] **Step 3:** Rodar o gate. Expected: `All pre-push checks passed`.
- [ ] **Step 4:** Rodar o full sweep. Expected: exit 0.
- [ ] **Step 5: Commit** `docs(meta_ads): fecha a onda 2`.

### Depois do merge (com aval nominal de merge e deploy)

- Sessão nova, chamada real das 3 auditorias em duas contas.
- Conferir um problema apontado de cada auditoria no Gerenciador.
