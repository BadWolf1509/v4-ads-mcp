# Respostas Google dizem o recorte — Plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Toda resposta das tools de leitura Google — e o preview do `bulk_pause_by_query` — diz o recorte que a query aplicou, e nenhuma razão sem denominador vira número.

**Architecture:** As funções de query passam a devolver `(gaql, filtros)`, o padrão que o F191 deixou nos três builders de auditoria, e cada tool ecoa `filtros` em `filters_applied`. Uma regra só, `razao()`, decide o denominador zero. Cinco guards travam a classe: completude derivada do `WHERE`, eco comportamental por tool, desempacotamento nas chamadas de teste, razão indefinida (AST) e igualdade no resumo do `add_negatives_from_search_terms`.

**Tech Stack:** Python 3.13, tools MCP em `src/mcp/tools/`, GAQL como texto, pytest + o harness de guards (`tests/unit/_guard_harness.py`).

**Spec:** `docs/superpowers/specs/2026-09-25-respostas-google-dizem-o-recorte-design.md` — com a correção de 25/09 dentro da §4.2 (33 ocorrências em 14 arquivos; `date_range` na forma `{"start", "end"}`).

## Global Constraints

- Python 3.13; nenhuma dependência nova.
- Antes de cada commit: `python scripts/check_pre_push.py > "$SCRATCH/gate.log" 2>&1; echo "EXIT=$?"` — 6/6, EXIT=0. **Nunca** pipe entre o gate e o `&&`. `$SCRATCH` é o diretório de rascunho da sessão, fora do repo: defina-o antes do primeiro comando.
- Todo teste ou guard que trava um conserto tem de ser visto **VERMELHO contra o código anterior** — é o passo "rode e veja falhar" de cada task. Onde não houver vermelho natural, sabotagem por **cópia** do arquivo (nunca `git checkout`).
- Chave de eco: `filters_applied`. O `filtros` é montado **na mesma função e junto da cláusula do `WHERE`** que ele descreve. Ausência de chave = sem aquele corte.
- `date_range` = `{"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}` (forma do F191), sempre via `janela_aplicada(start, end)`; janela `DURING` = `{"during": "<LITERAL>"}`.
- Chaves de status: `campaign_status`, `ad_group_status`, `ad_status`, `criterion_status`, com o valor em maiúsculas, como no GAQL.
- `razao(numerador, denominador) -> float | None` é a **única** regra de denominador zero e mora em `src/google_ads/queries/_common.py`. `arredondado`, `em_moeda` e `percentual` só repassam `None`.
- Texto de resposta e de description em ASCII sem acento (padrão dos módulos tocados: "periodo", "nao").
- Duas frases de `description`, exatas e conferidas por teste — regra sem mecanismo não fica: toda tool que ecoa ganha, como último fragmento, `" filters_applied diz o recorte que a query aplicou."` (spec §3.2); toda tool com razão na resposta ganha `" Razao com denominador zero vem null (indefinida), nao 0."` (spec §4.2).
- O `mypy` só cobre `src/`. Consumidor em `tests/` se acha pelos guards e pelo `pytest`, não pelo tipo.
- Commits `fix(google_ads)` / `fix(mcp)` / `docs(...)`, terminando com `Co-Authored-By: <modelo que escreveu> <noreply@anthropic.com>`.

## Inventário medido em 25/09 (não recontar à mão: os guards recontam)

| o quê | medido |
|---|---|
| funções de query no escopo | 17 + `build_performance_breakdown_query` (controle: 18/18 definições achadas) |
| chamadas em `src/` | 27 — o `mypy` pega todas |
| chamadas reais em `tests/` (AST) | **56**: Task 2 = 26, Task 3 = 7, Task 4 = 17 (as 8 irregulares moram aqui: 2 em comparação, 6 em tupla), Task 5 = 6 |
| `assert ... not in` nos arquivos consumidores | 31 — com tupla, viram verde vazio (daí o guard de desempacotamento) |
| chamada dinâmica que nenhum guard vê | `test_unbounded_reads_have_limit.py` (parametrize misto) — edição explícita nas Tasks 3 e 4 |
| razão que vira 0 (guard AST) | **33** em 14 arquivos |
| consumidores do contrato número → `null` | `tests/unit/test_performance_breakdown.py:91-92`, `tests/integration/test_overview_tools.py:94-95`, `tests/integration/test_client_report_tools.py:53` |
| **não** é consumidor | `tests/integration/test_get_keyword_performance.py` — mocka `run_report` com a linha já formatada, o formatador nem roda |
| tools que montam query dos cinco módulos | **17**: as 16 de leitura (contando o `get_performance_breakdown`) e o `bulk_pause_by_query` — a população do guard de eco sai daqui, pelo import |
| outra tool de mutação que afirma período (spec §7) | nenhuma — grep de 26/09: só o `bulk_pause_by_query`, e o `update_ad_schedule`, que já mede com janela |
| description que descreve a regra antiga | `bulk_pause_by_query`: *"auto-injeta segments.date BETWEEN quando filter usa metrics.\*"* — troca na Task 5, com teste |
| plugin `v4-trafego-google-ads` (26/09) | 1 linha com nome exato de campo, e ela só lista campos; 1 skill que depende do número em prosa: `relatorio-cliente-google-ads/SKILL.md:33` ordena anúncios por CTR |

## Decisões tomadas no levantamento

1. **`date_range` segue o F191** (`{"start", "end"}`). O spec dizia `{"from", "to"}`; vale o precedente real.
2. **33 ocorrências, não 29.** O `grep` do spec perdeu `get_budget_pacing` (3) e `update_campaign_budget` (1); o guard AST é que mede.
3. **A Task 2 é "os 8 reports da Fase 2B + o breakdown".** O `build_performance_breakdown_query` despacha para `performance.py` **e** para três funções de `tactical.py` (anúncio, keyword, público). Converter só um lado deixaria o breakdown devolvendo tupla num nível e texto no outro — o `mypy` recusa e o `run_report` quebra.
4. **Guard de desempacotamento estrito:** só `a, b = f(...)` e `f(...)[i]` passam; o escopo são as funções já convertidas (cresce por task); o próprio `test_filters_applied_e_derivado.py` fica isento, porque as lambdas de lá devolvem a tupla por desenho.
5. **Parser novo do `WHERE`:** toda condição tem de ser reconhecida. O do F191 não via `>=` nem `DURING` (controle medido).
6. **O ramo `campaign`+`hourly` do breakdown fica fora:** usa `day_hour_metrics_query` (`ad_schedule.py`), fora dos cinco módulos (spec §7). O docstring do builder declara isso.
7. **`add_keywords` e `add_negative_keywords` ficam fora:** o resumo delas só declara a intenção ("Adicionar N ..."), sem segunda contagem.
8. **`update_campaign_budget.delta_pct` não é furo de freio:** o `classify` de orçamento é sempre CONFIRM e não lê o número. Ele só aparece no texto e no preview, onde `None` precisa sair legível.
9. **Tools com duas queries ecoam aninhado:** `get_account_overview` → `{"current": …, "previous": …}`; `get_top_keywords_creatives` → `{"top_keywords": …, "top_creatives": …}`.
10. **`conversion_actions_query` não corta nada:** o eco é `{}`. Vazio explícito é a resposta honesta, não uma ausência.
11. **`build_metric_filter_clause` mantém a assinatura** (há teste da string exata). O eco dos mínimos entra num helper vizinho, `filtros_de_metrica`, e o guard derivado acusa qualquer descolamento entre os dois.
12. **`period` e `filters_applied.date_range` convivem.** As tools já devolviam `period` (`{"from", "to"}`); o eco repete a janela na forma do F191 (`{"start", "end"}`), como o próprio F191 já faz ao lado de `date_range_resolved`. Dois lugares para o mesmo dado só não divergem se algo confere: o guard de eco exige que as janelas de `period`/`previous_period` sejam exatamente as ecoadas.
13. **Resumo das negativas: "aceita(s) pelo Google", não "adicionada(s)".** O spec (§5) escreve *"X adicionada(s), Y já existia(m), Z falhou/falharam"*. `applied_count` mede aceitação, não execução (F184: o Google aceita operação que não executa), então o texto diz o que o número mede; "recusada(s)" pelo mesmo motivo.
14. **As populações dos guards são por varredura, não por lista nem por sufixo.** Funções: toda função pública dos módulos convertidos que devolve algo (anotação diferente de `-> None`) tem de ter chamada de exemplo — função nova que devolva GAQL sem se chamar `*_query` também cai (spec §3.3); hoje são 17, e `validate_filter` (`-> None`) fica de fora. Tools: toda tool que importa dos cinco módulos (ou do `performance_breakdown`) tem de estar no eco; toda tool que importa `razao` tem de avisar na description.
15. **O `no_op` do `bulk_pause_by_query` também ecoa.** "Nenhuma entidade no filtro" depende da janela que a query aplicou; a resposta de zero linhas diz qual. O erro de estouro (>100) não muda: ele pede refino do filtro.
16. **Consumidor externo, medido em 26/09:** no plugin `v4-trafego-google-ads`, uma referência exata aos campos (`analise-performance-google-ads/references/queries-v4-ads.md:63`, que só os lista) e um consumidor que depende do número sem citar o campo: `relatorio-cliente-google-ads/SKILL.md:33` ordena anúncios por CTR — com `ctr: null` (zero impressão), a linha tem de sair do ranking em vez de virar 0. O plugin é outro repositório: o achado vai para o corpo do PR e para o F193, não para uma task daqui.

## Ordem e acoplamento entre tasks

| arquivo | tasks | o que cada uma faz ali |
|---|---|---|
| `src/google_ads/queries/_common.py` | 1, 2 | 1: `razao` e repassadores; 2: `janela_aplicada` e `filtros_de_metrica` |
| os 9 `_row_formatter` e `performance_breakdown.py` | 1, 2 | 1: as linhas de razão; 2: a chamada da query e o retorno |
| `get_account_overview.py`, `get_budget_pacing.py`, `get_funnel_metrics.py` | 1, 4 | 1: razão e `sem_dados_no_periodo`; 4: eco |
| `tactical.py` | 2, 3 | 2: anúncio, keyword, público; 3: termos, negativas, conversões |
| `tests/unit/test_filters_applied_e_derivado.py` | 2, 3, 4, 5 | 2 cria a infraestrutura; 3–5 acrescentam módulos e chamadas; 5 põe o piso final |
| `tests/unit/test_filters_applied_chega_na_resposta.py` | 2, 3, 4 | 2 cria; 3 e 4 acrescentam casos |
| `tests/unit/test_unbounded_reads_have_limit.py` | 3, 4 | 3 reestrutura o parametrize e troca `conversion_actions`; 4 troca `budget_pacing` |

As tasks rodam **em ordem**. Cada uma termina com o gate verde.

---

### Task 1: Razão indefinida vira `null` — a classe inteira, e o `sem_dados_no_periodo`

**Files:**
- Modify: `src/google_ads/queries/_common.py` (helpers, logo depois de `micros_to_currency`)
- Modify (as 33 ocorrências): `src/mcp/tools/get_account_overview.py`, `get_funnel_metrics.py`, `get_budget_pacing.py`, `update_campaign_budget.py`, `get_ad_group_performance.py`, `get_ad_performance.py`, `get_audience_performance.py`, `get_campaign_performance.py`, `get_device_performance.py`, `get_geo_performance.py`, `get_hourly_performance.py`, `get_keyword_performance.py`, `get_search_terms_report.py`, `src/google_ads/performance_breakdown.py`
- Create: `tests/unit/test_razao_indefinida.py`
- Modify (consumidores do contrato): `tests/unit/test_performance_breakdown.py`, `tests/integration/test_overview_tools.py`, `tests/integration/test_client_report_tools.py`
- Modify (caso novo): `tests/unit/test_update_campaign_budget.py`

**Interfaces:**
- Produces (em `src/google_ads/queries/_common.py`):
  - `razao(numerador: float | None, denominador: float | None) -> float | None`
  - `arredondado(valor: float | None, casas: int) -> float | None`
  - `em_moeda(valor_micros: float | None) -> float | None`
  - `percentual(valor: float | None) -> float | None`
- `get_account_overview._aggregate(rows)` passa a devolver `sem_dados_no_periodo: bool` sempre.

- [ ] **Step 1: Escreva o teste novo**

Crie `tests/unit/test_razao_indefinida.py`:

```python
"""Razao sem denominador e indefinida, nao zero (spec 2026-09-25, §4.2).

CPA R$ 0,00 com gasto e zero conversao se le como o melhor CPA possivel; CPC
R$ 0,00 sem clique, como clique de graca. A regra e uma so (`razao()`), e o guard
AST abaixo impede a forma `x / y if y else 0` de voltar em qualquer tool Google.
"""

from __future__ import annotations

import ast
import importlib
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.google_ads.queries._common import arredondado, em_moeda, percentual, razao
from tests.unit import _guard_harness as h


def test_razao_sem_denominador_e_none() -> None:
    assert razao(5, 0) is None
    assert razao(5, 0.0) is None
    assert razao(None, 3) is None


def test_os_repassadores_deixam_none_passar() -> None:
    assert arredondado(None, 2) is None
    assert em_moeda(None) is None
    assert percentual(None) is None


@pytest.mark.parametrize("a,b", [(3, 7), (1, 3), (5_000_000, 3), (2, 9.5)])
def test_fora_do_zero_o_valor_e_o_de_antes(a: float, b: float) -> None:
    """Controle: a troca nao pode mudar numero que ja existia."""
    assert arredondado(razao(a, b), 4) == round(a / b, 4)
    assert em_moeda(razao(a, b)) == round((a / b) / 1_000_000.0, 2)
    assert arredondado(percentual(razao(a, b)), 2) == round(a / b * 100, 2)


def _divisoes_que_viram_zero(arv: ast.AST) -> list[int]:
    """`<algo que divide> if <cond> else 0` — a forma que a regra proibe."""
    achados = []
    for no in ast.walk(arv):
        if (
            isinstance(no, ast.IfExp)
            and isinstance(no.orelse, ast.Constant)
            and not isinstance(no.orelse.value, bool)
            and no.orelse.value in (0, 0.0)
            and any(
                isinstance(s, ast.BinOp) and isinstance(s.op, ast.Div) for s in ast.walk(no.body)
            )
        ):
            achados.append(no.lineno)
    return achados


def test_o_detector_enxerga_a_forma_proibida() -> None:
    """Controle positivo: sem ele, o guard abaixo passaria verde por nao casar nada."""
    arv = ast.parse("x = {'ctr': round(c / i, 4) if i else 0.0, 'n': 0}")
    assert _divisoes_que_viram_zero(arv) == [1]


def test_nenhuma_razao_vira_zero_quando_o_denominador_some() -> None:
    ofensores = [
        f"{h.rel(p)}:{linha}"
        for raiz in (h.SRC / "mcp" / "tools", h.SRC / "google_ads")
        for p in h.fontes_py(raiz)
        for linha in _divisoes_que_viram_zero(h.arvore(p))
    ]
    assert not ofensores, (
        "razao que vira 0 quando o denominador some — CPA R$ 0,00 le como o melhor "
        f"CPA possivel. Use `razao()` de src/google_ads/queries/_common.py: {ofensores}"
    )


_FORMATADORES_POR_LINHA = [
    "get_ad_group_performance",
    "get_ad_performance",
    "get_audience_performance",
    "get_campaign_performance",
    "get_device_performance",
    "get_geo_performance",
    "get_hourly_performance",
    "get_keyword_performance",
    "get_search_terms_report",
]


@pytest.mark.parametrize("modulo", _FORMATADORES_POR_LINHA)
def test_linha_sem_impressao_nem_clique_tem_razoes_indefinidas(modulo: str) -> None:
    """O guard prova que a forma sumiu; este prova que a linha zerada NAO derruba a
    tool (um `clicks / impr` cru passaria no guard e daria ZeroDivisionError)."""
    mod = importlib.import_module(f"src.mcp.tools.{modulo}")
    row = MagicMock()
    row.metrics.impressions = 0
    row.metrics.clicks = 0
    row.metrics.cost_micros = 5_000_000
    row.metrics.conversions = 0.0
    row.metrics.conversions_value = 0.0
    out = mod._row_formatter(row)
    assert out["ctr"] is None
    assert out["cpc_brl"] is None


def test_breakdown_com_metrica_zerada_tem_razoes_indefinidas() -> None:
    from src.google_ads.performance_breakdown import _common_metrics

    m = SimpleNamespace(
        impressions=0, clicks=0, cost_micros=0, conversions=0.0, conversions_value=0.0
    )
    out = _common_metrics(m)
    assert out["ctr"] is None
    assert out["cpc_brl"] is None


def test_overview_sem_linha_nenhuma_diz_que_nao_ha_dado() -> None:
    from src.mcp.tools.get_account_overview import _aggregate

    out = _aggregate([])
    assert out["sem_dados_no_periodo"] is True
    assert out["impressions"] == 0
    for chave in ("ctr", "average_cpc_brl", "cost_per_conversion_brl", "roas"):
        assert out[chave] is None


def test_overview_com_gasto_e_zero_conversao_nao_tem_cpa() -> None:
    from src.mcp.tools.get_account_overview import _aggregate

    out = _aggregate(
        [
            {
                "impressions": 100,
                "clicks": 10,
                "cost_micros": 5_000_000,
                "conversions": 0.0,
                "conversions_value": 0.0,
            }
        ]
    )
    assert out["sem_dados_no_periodo"] is False
    assert out["cost_per_conversion_brl"] is None  # era 0.0: "o melhor CPA possivel"
    assert out["ctr"] == 0.1
    assert out["average_cpc_brl"] == 0.5


def test_funil_distingue_zero_medido_de_indefinido() -> None:
    from src.mcp.tools.get_funnel_metrics import _build_funnel

    out = _build_funnel(
        [
            {
                "impressions": 100,
                "clicks": 0,
                "cost_micros": 0,
                "conversions": 0.0,
                "conversions_value": 0.0,
            }
        ]
    )
    assert out["stages"][1]["rate_from_prev_pct"] == 0.0  # 0 cliques / 100 impr: zero MEDIDO
    assert out["stages"][2]["rate_from_prev_pct"] is None  # 0 conv / 0 cliques: indefinido
    assert out["totals"]["roas"] is None
    assert out["totals"]["cost_per_conversion_brl"] is None
    assert out["totals"]["average_order_value_brl"] is None


def test_pacing_sem_orcamento_nao_vira_zero_porcento() -> None:
    from src.mcp.tools.get_budget_pacing import _project

    (c,) = _project(
        [
            {
                "campaign_id": "1",
                "campaign_name": "c",
                "daily_budget_brl": 0.0,
                "delivery_method": "STANDARD",
                "cost_micros_today": 3_100_000_000,
            }
        ],
        today=date(2026, 8, 31),
    )
    assert c["spent_pct_of_monthly_budget"] is None
    assert c["projection_vs_budget_pct"] is None
    # a projecao do GASTO existe: nao depende do orcamento
    assert c["projected_monthly_brl"] == 3100.0


_FRASE_DA_RAZAO = "Razao com denominador zero vem null (indefinida), nao 0."
# O `delta_pct` do preview de orcamento tambem pode vir null; quem explica e o
# `blast_summary` ("variacao indefinida"), nao a description da tool de mutacao.
_MUTACAO_COM_RAZAO = {"update_campaign_budget"}


def _tools_com_razao() -> set[str]:
    """Tool cuja resposta carrega razao: o modulo importa `razao`, ou monta a linha
    pelo `performance_breakdown`, que calcula a razao la dentro."""
    achadas = set()
    for p in h.fontes_py(h.SRC / "mcp" / "tools"):
        for no in ast.walk(h.arvore(p)):
            if isinstance(no, ast.ImportFrom) and (
                no.module == "src.google_ads.performance_breakdown"
                or (
                    no.module == "src.google_ads.queries._common"
                    and any(a.name == "razao" for a in no.names)
                )
            ):
                achadas.add(p.stem)
    return achadas - _MUTACAO_COM_RAZAO


def test_toda_tool_com_razao_avisa_na_description() -> None:
    """O contrato mudou de numero para null: quem le a tool (o LLM) tem de saber.

    A lista sai da varredura, nao da memoria: tool nova que use `razao` cai aqui.
    """
    from src.mcp.tools._registry import get_tool, import_all_tools

    import_all_tools()
    nomes = _tools_com_razao()
    assert len(nomes) >= 13, f"piso medido em 26/09: 13 tools; a varredura achou {sorted(nomes)}"
    sem_aviso = []
    for nome in sorted(nomes):
        tool = get_tool(nome)
        assert tool is not None, f"`{nome}` nao esta no registry com o nome do modulo"
        if _FRASE_DA_RAZAO not in tool.description:
            sem_aviso.append(nome)
    assert not sem_aviso, f"tool com razao cuja description nao avisa do null: {sem_aviso}"
```

- [ ] **Step 2: Rode e veja falhar**

Run: `python -m pytest tests/unit/test_razao_indefinida.py -q`
Expected: FAIL já na coleta, com `ImportError: cannot import name 'arredondado'`. **Previsão registrada:** depois do Step 3 (só os helpers), o guard AST acusa **33** ofensores e os testes de comportamento falham com `0.0 is None`, e o de description falha no piso — a varredura acha 1 tool (o `get_performance_breakdown`, pelo import do `performance_breakdown`), não 13.

- [ ] **Step 3: Escreva os helpers**

Em `src/google_ads/queries/_common.py`, logo depois de `micros_to_currency`:

```python
def razao(numerador: float | None, denominador: float | None) -> float | None:
    """`numerador / denominador`, ou `None` quando nao ha o que dividir.

    Razao sem denominador e INDEFINIDA, nao zero: CPA R$ 0,00 com gasto e zero
    conversao se le como o melhor CPA possivel; CPC R$ 0,00 sem clique, como
    clique de graca. `None` e o terceiro estado do F191 — distinto do zero
    medido. E a UNICA regra de denominador zero das tools Google: o guard
    `test_nenhuma_razao_vira_zero_quando_o_denominador_some` acusa a forma
    `x / y if y else 0` em `src/mcp/tools/` e `src/google_ads/`.
    """
    if numerador is None or not denominador:
        return None
    return numerador / denominador


def arredondado(valor: float | None, casas: int) -> float | None:
    """`round` que deixa `None` passar: a razao indefinida continua indefinida."""
    return None if valor is None else round(valor, casas)


def em_moeda(valor_micros: float | None) -> float | None:
    """`micros_to_currency` que deixa `None` passar."""
    return None if valor_micros is None else micros_to_currency(valor_micros)


def percentual(valor: float | None) -> float | None:
    """`valor * 100` que deixa `None` passar.

    Mantem a ordem `a / b * 100` das contas de antes: `a * 100 / b` muda o ultimo
    bit e pode virar o arredondamento na casa decimal.
    """
    return None if valor is None else valor * 100
```

Rode `python -m pytest tests/unit/test_razao_indefinida.py -q -k "detector or razao_sem or repassadores or fora_do_zero or nenhuma_razao"` e confira: os de helper passam, e o `test_nenhuma_razao_vira_zero_quando_o_denominador_some` falha listando **33** `arquivo:linha`. Se não forem 33, pare e reconte: o número é a previsão desta task.

- [ ] **Step 4: Converta as 33 ocorrências**

**(a) Os 9 `_row_formatter`** (`get_ad_group_performance`, `get_ad_performance`, `get_audience_performance`, `get_campaign_performance`, `get_device_performance`, `get_geo_performance`, `get_hourly_performance`, `get_keyword_performance`, `get_search_terms_report`). Em cada um, troque

```python
        "ctr": round(clicks / impr, 4) if impr else 0.0,
        "cpc_brl": micros_to_currency(cost_micros / clicks) if clicks else 0.0,
```

por

```python
        "ctr": arredondado(razao(clicks, impr), 4),
        "cpc_brl": em_moeda(razao(cost_micros, clicks)),
```

e troque o import `from src.google_ads.queries._common import micros_to_currency, resolve_date_window` por

```python
from src.google_ads.queries._common import (
    arredondado,
    em_moeda,
    micros_to_currency,
    razao,
    resolve_date_window,
)
```

**(b) `src/google_ads/performance_breakdown.py`, em `_common_metrics`:** as mesmas duas linhas do item (a). O import vira `from src.google_ads.queries._common import arredondado, em_moeda, micros_to_currency, razao`.

**(c) `get_account_overview.py`:** substitua o `_aggregate` inteiro por

```python
def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Sum the per-day rows into single totals + computed ratios.

    Razao sem denominador vem `None` (indefinida), nao 0.0 (spec 2026-09-25,
    §4.2). Periodo sem nenhuma linha traz as contagens em 0 — verdade: nao houve
    impressao, clique nem gasto — e `sem_dados_no_periodo: True`, que distingue
    "nao ha dado" de uma linha medida com zero.
    """
    if not rows:
        return {
            "impressions": 0,
            "clicks": 0,
            "cost_brl": 0.0,
            "conversions": 0.0,
            "conversions_value_brl": 0.0,
            "ctr": None,
            "average_cpc_brl": None,
            "cost_per_conversion_brl": None,
            "roas": None,
            "sem_dados_no_periodo": True,
        }
    impr = sum(r["impressions"] for r in rows)
    clicks = sum(r["clicks"] for r in rows)
    cost = sum(r["cost_micros"] for r in rows)
    conv = sum(r["conversions"] for r in rows)
    conv_val = sum(r["conversions_value"] for r in rows)
    aggregate = {
        "impressions": impr,
        "clicks": clicks,
        "cost_brl": micros_to_currency(cost),
        "conversions": round(conv, 2),
        "conversions_value_brl": round(conv_val, 2),
        "ctr": arredondado(razao(clicks, impr), 4),
        "average_cpc_brl": em_moeda(razao(cost, clicks)),
        "cost_per_conversion_brl": em_moeda(razao(cost, conv)),
        # O guarda antigo era `if cost` (micros) e dividia por `micros_to_currency(cost)`:
        # custo abaixo de meio centavo arredonda para 0.0 e dava ZeroDivisionError.
        "roas": arredondado(razao(conv_val, micros_to_currency(cost)), 2),
        "sem_dados_no_periodo": False,
    }
    # UX-1: detect tracking placeholder (conversions_value == conversions exact 1:1)
    warning = value_proxy_warning(aggregate["conversions"], aggregate["conversions_value_brl"])
    if warning:
        aggregate["tracking_warning"] = warning
    return aggregate
```

e acrescente `arredondado`, `em_moeda` e `razao` ao import de `_common` já existente.

**(d) `get_funnel_metrics.py`, em `_build_funnel`:** o bloco `totals` vira

```python
    totals: dict[str, Any] = {
        "cost_brl": cost_brl,
        "conversions_value_brl": round(conv_val, 2),
        "roas": arredondado(razao(conv_val, cost_brl), 2),
        "average_order_value_brl": arredondado(razao(conv_val, conv), 2),
        "cost_per_conversion_brl": arredondado(razao(cost_brl, conv), 2),
    }
```

e as duas taxas das etapas viram

```python
                "rate_from_prev_pct": arredondado(percentual(razao(clicks, impr)), 2),
```

(etapa `clicks`) e

```python
                "rate_from_prev_pct": arredondado(percentual(razao(conv, clicks)), 2),
```

(etapa `conversions`). Acrescente `arredondado`, `percentual` e `razao` ao import de `_common`.

**(e) `get_budget_pacing.py`, em `_project`:** as linhas de `daily_avg` e `projected` viram

```python
        daily_avg = razao(mtd, days_elapsed)
        projected = arredondado(None if daily_avg is None else daily_avg * days_in_month, 2)
```

e as duas porcentagens do dicionário viram

```python
                "spent_pct_of_monthly_budget": arredondado(
                    percentual(razao(mtd, budget_monthly)), 1
                ),
```

e

```python
                "projection_vs_budget_pct": arredondado(
                    percentual(razao(projected, budget_monthly)), 1
                ),
```

O import `from src.google_ads.queries._common import micros_to_currency` vira `from src.google_ads.queries._common import arredondado, micros_to_currency, percentual, razao`. (`days_elapsed = today.day` nunca é zero; a troca é pela regra, não por um caso vivo.)

**(f) `update_campaign_budget.py`:** o cálculo vira

```python
    delta_pct = percentual(razao(new_amount_micros - current_micros, current_micros))
```

o resumo vira

```python
    delta_txt = (
        f"delta {delta_pct:+.1f}%"
        if delta_pct is not None
        else "variacao indefinida: o orcamento atual e zero"
    )
    summary = (
        f"Orcamento de '{info['campaign_name']}' (id {campaign_id}): "
        f"R$ {current_brl} -> R$ {new_amount_brl:.2f} "
        f"({delta_txt})."
    )
```

e, no `preview_envelope`, `delta_pct=round(delta_pct, 2),` vira `delta_pct=arredondado(delta_pct, 2),`. O import de `_common` vira `from src.google_ads.queries._common import arredondado, micros_to_currency, percentual, razao`. O `classify` continua recebendo `delta_pct`: a regra de orçamento é sempre CONFIRM e não o lê.

- [ ] **Step 5: Atualize os três consumidores do contrato e acrescente os dois casos novos**

`tests/unit/test_performance_breakdown.py`, em `test_common_metrics_zero_division`:

```python
    assert out["ctr"] is None
    assert out["cpc_brl"] is None
```

`tests/integration/test_overview_tools.py`, em `test_account_overview_handles_zero_division`:

```python
    cur = result["current"]
    assert cur["impressions"] == 0
    assert cur["ctr"] is None
    assert cur["roas"] is None
    assert cur["sem_dados_no_periodo"] is True
    assert result["previous"]["sem_dados_no_periodo"] is True  # nos dois periodos (spec §4.2)
```

`tests/integration/test_client_report_tools.py`, em `test_funnel_handles_empty_data`, a última linha vira:

```python
    assert result["funnel"]["totals"]["roas"] is None
```

Em `tests/unit/test_update_campaign_budget.py`, acrescente:

```python
async def test_orcamento_atual_zero_nao_vira_variacao_de_zero_porcento(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """De R$ 0 para R$ 100 nao e "delta +0.0%": a razao nao existe (spec 2026-09-25,
    §4.2). O `classify` de orcamento e sempre CONFIRM e nao le o numero — o erro
    ficava so no texto que o gestor confirma e no preview."""
    captured = _wire(monkeypatch, explicitly_shared=False, irmas=[])
    zerado = {**_valores_alvo(explicitly_shared=False), "campaign_budget.amount_micros": 0}

    async def _run(**kwargs: Any) -> list[dict[str, Any]]:
        formatar = kwargs["row_formatter"]
        return [formatar(_linha(kwargs["query"], zerado))]

    monkeypatch.setattr(mod, "run_report", _run)
    envelope: dict[str, Any] = await mod.update_campaign_budget(
        {"customer_id": _CUSTOMER, "campaign_id": _ALVO_ID, "new_daily_budget_brl": 100.0}
    )
    assert envelope["delta_pct"] is None
    assert "variacao indefinida" in envelope["blast_summary"]
    assert "variacao indefinida" in captured["blast_summary"]
```

(Sem `@pytest.mark.asyncio`: o `pyproject.toml` tem `asyncio_mode = "auto"`, e os testes async deste arquivo não levam o decorador. `_wire`, `_valores_alvo`, `_linha`, `_CUSTOMER`, `_ALVO_ID`, `mod` e o `_ctx` autouse já existem no arquivo.)

- [ ] **Step 6: Declare o contrato novo nas descriptions**

Acrescente, como **último fragmento** da `description` de cada tool abaixo, exatamente:

```python
        " Razao com denominador zero vem null (indefinida), nao 0."
```

Tools: `get_account_overview`, `get_funnel_metrics`, `get_campaign_performance`, `get_ad_group_performance`, `get_keyword_performance`, `get_ad_performance`, `get_audience_performance`, `get_device_performance`, `get_geo_performance`, `get_hourly_performance`, `get_search_terms_report`, `get_performance_breakdown`, `get_budget_pacing`.

O `test_toda_tool_com_razao_avisa_na_description` confere: a varredura acha as 13 pelo import de `razao` (ou do `performance_breakdown`), e uma tool nova com razão cai nela sem ninguém lembrar.

- [ ] **Step 7: Rode e veja passar**

```bash
python -m pytest tests/unit/test_razao_indefinida.py tests/unit/test_performance_breakdown.py tests/unit/test_update_campaign_budget.py tests/unit/test_budget_pacing_today.py tests/integration/test_overview_tools.py tests/integration/test_client_report_tools.py -q
python -m ruff check --fix src/ tests/
python scripts/check_pre_push.py > "$SCRATCH/gate.log" 2>&1; echo "EXIT=$?"
```

Expected: tudo verde; gate 6/6, EXIT=0. O guard AST acusava 33 no Step 3 e acusa 0 agora — essa é a mordida provada.

- [ ] **Step 8: Reconfira o consumidor externo (plugin)**

O contrato mudou de número para `null` em 13 tools, e os skills do plugin `v4-trafego-google-ads` montam relatório de cliente com esses campos. O plugin é outro repositório: aqui só se mede e se registra (decisão 16).

```bash
grep -rn -E "\b(ctr|cpc_brl|average_cpc_brl|cost_per_conversion_brl|roas|rate_from_prev_pct|average_order_value_brl|spent_pct_of_monthly_budget|projection_vs_budget_pct|delta_pct)\b" "C:/Users/welli/.claude/plugins/marketplaces/local-desktop-app-uploads/v4-trafego-google-ads"
```

Expected: uma linha só, `skills/analise-performance-google-ads/references/queries-v4-ads.md:63`, que lista campos. Outro resultado: leia cada linha nova e registre no relatório da task as que fazem conta, ordenação ou formatação com o campo. O consumidor que depende do número não cita o campo — `skills/relatorio-cliente-google-ads/SKILL.md:33` ("ordenar por CTR depois") — e vai para o corpo do PR e para o F193 (Task 7).

- [ ] **Step 9: Commit**

```bash
git add src/ tests/
git commit -m "fix(mcp): razao sem denominador vem null, nao 0 — a classe inteira"
```

---

### Task 2: Os 8 reports da Fase 2B e o breakdown ecoam o recorte; os três guards nascem

**Files:**
- Modify: `src/google_ads/queries/_common.py` (`janela_aplicada` ao lado de `gaql_date_clause`; `filtros_de_metrica` ao lado de `build_metric_filter_clause`)
- Modify: `src/google_ads/queries/performance.py` (as 5 funções)
- Modify: `src/google_ads/queries/tactical.py` (`keyword_performance_query`, `ad_performance_query`, `audience_performance_query`)
- Modify: `src/google_ads/performance_breakdown.py` (`build_performance_breakdown_query`)
- Modify: `src/mcp/tools/get_campaign_performance.py`, `get_ad_group_performance.py`, `get_device_performance.py`, `get_geo_performance.py`, `get_hourly_performance.py`, `get_ad_performance.py`, `get_keyword_performance.py`, `get_audience_performance.py`, `get_performance_breakdown.py`
- Modify: `tests/unit/test_filters_applied_e_derivado.py`
- Create: `tests/unit/test_filters_applied_chega_na_resposta.py`
- Modify (conversão mecânica, 26 chamadas): `tests/unit/test_query_builders_gaql.py`, `tests/unit/test_performance_breakdown.py`, `tests/unit/test_keyword_performance_filters.py`

**Interfaces:**
- Consumes: nada da Task 1 além do código já mesclado.
- Produces:
  - `janela_aplicada(start: date, end: date) -> dict[str, str]`
  - `filtros_de_metrica(min_cost_brl: float | None = None, min_clicks: int | None = None, min_conversions: float | None = None) -> dict[str, float | int]`
  - As 8 funções de query e `build_performance_breakdown_query` passam a devolver `tuple[str, dict[str, Any]]`.
  - Em `test_filters_applied_e_derivado.py`: `_MODULOS_CONVERTIDOS`, `_funcoes_publicas`, `_chamadas()`, `CAMPO_PARA_CHAVE` completo, `_campos_do_where`, `_chamadas_sem_desempacotar`.
  - Em `test_filters_applied_chega_na_resposta.py`: `Caso`, `_unico`, `CASOS`, `_janelas`, `_FRASE_DO_ECO`.

- [ ] **Step 1: Escreva os guards novos em `tests/unit/test_filters_applied_e_derivado.py`**

(a) Troque a função `_campos_do_where` existente por:

```python
_CAMPO = re.compile(
    r"^([a-z_]+(?:\.[a-z_]+)+)\s*"
    r"(?:>=|<=|!=|=|>|<|\bNOT IN\b|\bIN\b|\bBETWEEN\b|\bIS\b|\bDURING\b|\bLIKE\b)"
)


def _condicoes_do_where(gaql: str) -> list[str]:
    """Condicoes do WHERE, uma por item. `BETWEEN 'a' AND 'b'` conta como uma so."""
    m = re.search(r"\bWHERE\b(.*?)(?:\bORDER BY\b|\bLIMIT\b|$)", gaql, re.S)
    if not m:
        return []
    where = re.sub(r"\bBETWEEN\s+'[^']*'\s+AND\s+'[^']*'", "BETWEEN _", m.group(1))
    return [c.strip() for c in re.split(r"\bAND\b", where) if c.strip()]


def _campos_do_where(gaql: str) -> set[str]:
    """O campo de CADA condicao. Condicao que o parser nao entende FALHA.

    O parser anterior lia so `=`, `!=`, `IN`, `BETWEEN` e `IS`: a metrica minima
    (`metrics.cost_micros >= X`) e a janela `DURING` passavam invisiveis, e a
    completude ficava verde sem elas (medido em 2026-09-25).
    """
    campos = set()
    for cond in _condicoes_do_where(gaql):
        m = _CAMPO.match(cond)
        assert m, f"condicao do WHERE que o parser nao entende: {cond!r}"
        campos.add(m.group(1))
    return campos
```

(O `import re` que ficava dentro da função antiga sobe para o topo do arquivo.)

(b) O `CAMPO_PARA_CHAVE` ganha as entradas novas (as do F191 ficam):

```python
    # plano 2026-09-26 (respostas Google)
    "campaign.status": "campaign_status",
    "ad_group.status": "ad_group_status",
    "ad_group_ad.status": "ad_status",
    "metrics.cost_micros": "min_cost_brl",
    "metrics.clicks": "min_clicks",
    "metrics.conversions": "min_conversions",
    "campaign_criterion.negative": "negative",
    "campaign_criterion.type": "criterion_type",
```

(c) Acrescente ao fim do arquivo (com os imports `ast`, `Path`, `Callable`, `date`, `Any` e `from tests.unit import _guard_harness as h` no topo):

```python
_S, _E = date(2026, 9, 1), date(2026, 9, 30)
_ESTE_ARQUIVO = Path(__file__).resolve()

# Modulos em que TODA funcao `*_query` publica devolve (gaql, filtros). Cresce a
# cada task do plano 2026-09-26; a Task 5 fecha em 5 modulos e poe o piso de 17.
_MODULOS_CONVERTIDOS: tuple[Path, ...] = (h.SRC / "google_ads" / "queries" / "performance.py",)


def _chamadas() -> dict[str, Callable[[], tuple[str, dict[str, Any]]]]:
    """Uma chamada de exemplo por funcao convertida, com args que exercitam TODO
    ramo do WHERE (status != 'all', minimos de metrica preenchidos)."""
    from src.google_ads.queries import performance as p
    from src.google_ads.queries import tactical as t

    return {
        "campaign_performance_query": lambda: p.campaign_performance_query(_S, _E, "enabled", 10),
        "ad_group_performance_query": lambda: p.ad_group_performance_query(_S, _E, "enabled", 10),
        "device_performance_query": lambda: p.device_performance_query(_S, _E),
        "geo_performance_query": lambda: p.geo_performance_query(_S, _E, 10),
        "hourly_performance_query": lambda: p.hourly_performance_query(_S, _E),
        "ad_performance_query": lambda: t.ad_performance_query(_S, _E, "enabled", 10),
        "keyword_performance_query": lambda: t.keyword_performance_query(
            _S, _E, "enabled", 10, min_cost_brl=10.0, min_clicks=5, min_conversions=1.0
        ),
        "audience_performance_query": lambda: t.audience_performance_query(_S, _E, 10),
    }


def _funcoes_publicas(mod: Path) -> set[str]:
    """Toda funcao publica do modulo que devolve algo (anotacao diferente de `-> None`).

    O nome nao entra no criterio: funcao nova que devolva GAQL sem se chamar
    `*_query` tambem cai aqui (spec 2026-09-25, §3.3 — populacao por varredura).
    """
    return {
        fn.name
        for fn in h.funcoes(h.arvore(mod))
        if not fn.name.startswith("_")
        and not (isinstance(fn.returns, ast.Constant) and fn.returns.value is None)
    }


def test_toda_funcao_publica_dos_modulos_convertidos_tem_chamada_de_exemplo() -> None:
    nos_modulos = {nome for mod in _MODULOS_CONVERTIDOS for nome in _funcoes_publicas(mod)}
    assert nos_modulos, "controle: nenhuma funcao achada — o escopo quebrou"
    faltam = sorted(nos_modulos - set(_chamadas()))
    assert not faltam, (
        f"funcao publica sem chamada de exemplo aqui: {faltam}. Acrescente em "
        "`_chamadas()` com args que exercitem todo ramo do WHERE."
    )


def test_o_parser_novo_ve_o_que_o_antigo_nao_via() -> None:
    """Controle: metrica minima e janela DURING sao cortes."""
    assert _campos_do_where("SELECT a FROM b WHERE metrics.cost_micros >= 10 LIMIT 5") == {
        "metrics.cost_micros"
    }
    assert _campos_do_where("SELECT a FROM b WHERE segments.date DURING THIS_MONTH") == {
        "segments.date"
    }


def test_toda_funcao_convertida_ecoa_cada_corte_do_where() -> None:
    for nome, chamar in _chamadas().items():
        gaql, filtros = chamar()
        for campo in _campos_do_where(gaql):
            chave = CAMPO_PARA_CHAVE.get(campo)
            assert chave is not None, (
                f"{nome}: `{campo}` corta no WHERE e este teste nao o conhece. Decida a "
                "chave em `filters_applied`, declare-a na funcao e mapeie aqui."
            )
            assert chave in filtros, f"{nome}: `{campo}` corta e nao aparece em filtros"


def test_o_breakdown_repassa_o_recorte_da_funcao_que_despacha() -> None:
    from src.google_ads.performance_breakdown import build_performance_breakdown_query
    from src.google_ads.queries import performance as p
    from src.google_ads.queries import tactical as t

    esperados = {
        ("campaign", None): lambda: p.campaign_performance_query(_S, _E, "enabled", 10),
        ("ad_group", None): lambda: p.ad_group_performance_query(_S, _E, "enabled", 10),
        ("ad", None): lambda: t.ad_performance_query(_S, _E, "enabled", 10),
        ("keyword", None): lambda: t.keyword_performance_query(_S, _E, "enabled", 10),
        ("audience", None): lambda: t.audience_performance_query(_S, _E, 10),
        ("account", "device"): lambda: p.device_performance_query(_S, _E),
        ("account", "geo"): lambda: p.geo_performance_query(_S, _E, 10),
        ("account", "hourly"): lambda: p.hourly_performance_query(_S, _E),
    }
    for (level, breakdown), direto in esperados.items():
        assert (
            build_performance_breakdown_query(level, breakdown, "enabled", _S, _E, 10) == direto()
        ), f"{level}/{breakdown}"


def _nomes_em_escopo() -> set[str]:
    return set(_chamadas()) | {"build_performance_breakdown_query"}


def _chamadas_sem_desempacotar(arv: ast.Module, nomes: set[str]) -> list[int]:
    """Chamada de funcao de query que NAO desempacota a tupla na hora.

    So duas formas passam: `a, b = f(...)` e `f(...)[i]`. Qualquer outra entrega a
    TUPLA a quem espera texto — e `assert "x" not in q` contra uma tupla fica verde
    sem afirmar nada (31 asserts `not in` nos arquivos consumidores, medido em 25/09).
    Limite: chamada por nome local (`builder(...)` num parametrize) nao e vista.
    """
    pais = {filho: no for no in ast.walk(arv) for filho in ast.iter_child_nodes(no)}
    ruins = []
    for no in ast.walk(arv):
        if not isinstance(no, ast.Call):
            continue
        nome = no.func.id if isinstance(no.func, ast.Name) else getattr(no.func, "attr", None)
        if nome not in nomes:
            continue
        pai = pais.get(no)
        desempacota = (
            isinstance(pai, ast.Assign)
            and len(pai.targets) == 1
            and isinstance(pai.targets[0], ast.Tuple)
            and len(pai.targets[0].elts) == 2
        )
        indexa = isinstance(pai, ast.Subscript) and pai.value is no
        if not (desempacota or indexa):
            ruins.append(no.lineno)
    return sorted(ruins)


def test_o_detector_de_desempacotamento_enxerga_as_formas_proibidas() -> None:
    """Controle positivo, com a fronteira exata do que passa."""
    fonte = (
        "q = f(1)\n"
        "assert 'x' in f(1)\n"
        "for q in (f(1),):\n"
        "    pass\n"
        "g, h = f(1)\n"
        "g = f(1)[0]\n"
    )
    assert _chamadas_sem_desempacotar(ast.parse(fonte), {"f"}) == [1, 2, 3]


def test_chamada_de_funcao_de_query_em_teste_desempacota_a_tupla() -> None:
    nomes = _nomes_em_escopo()
    ofensores = [
        f"{h.rel(p)}:{linha}"
        for p in h.testes_py()
        if p.resolve() != _ESTE_ARQUIVO
        for linha in _chamadas_sem_desempacotar(h.arvore(p), nomes)
    ]
    assert not ofensores, (
        f"chamada de funcao de query sem desempacotar `(gaql, filtros)`: {ofensores}. "
        "Use `gaql, _ = f(...)` ou `f(...)[0]`."
    )
```

- [ ] **Step 2: Escreva o guard de eco, `tests/unit/test_filters_applied_chega_na_resposta.py`**

```python
"""A resposta de cada tool traz em `filters_applied` o `filtros` EXATO da query que rodou.

A completude derivada (test_filters_applied_e_derivado.py) prova que a FUNCAO de
query sabe o recorte; esta prova que a TOOL o entrega, e que a query cujo recorte
ela declara e a mesma que ela mandou ao Google (spec 2026-09-25, §3.3).
"""

from __future__ import annotations

import importlib
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.mcp.context import McpRequestContext, clear_current, set_current

_CONTA = "1234567890"

Registro = dict[str, list[tuple[str, dict[str, Any]]]]

_FRASE_DO_ECO = "filters_applied diz o recorte que a query aplicou."


@pytest.fixture(autouse=True)
def _ctx() -> Iterator[None]:
    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    yield
    clear_current()


@dataclass(frozen=True)
class Caso:
    tool: str
    funcoes: tuple[str, ...]  # nomes NO MODULO DA TOOL, espionados
    esperado: Callable[[Registro], Any]  # o filters_applied que a resposta tem de trazer
    args: dict[str, Any] = field(default_factory=dict)


def _unico(funcao: str) -> Callable[[Registro], Any]:
    return lambda r: r[funcao][0][1]


CASOS: list[Caso] = [
    Caso("get_campaign_performance", ("campaign_performance_query",), _unico("campaign_performance_query")),
    Caso("get_ad_group_performance", ("ad_group_performance_query",), _unico("ad_group_performance_query")),
    Caso("get_keyword_performance", ("keyword_performance_query",), _unico("keyword_performance_query")),
    Caso("get_ad_performance", ("ad_performance_query",), _unico("ad_performance_query")),
    Caso("get_audience_performance", ("audience_performance_query",), _unico("audience_performance_query")),
    Caso("get_device_performance", ("device_performance_query",), _unico("device_performance_query")),
    Caso("get_geo_performance", ("geo_performance_query",), _unico("geo_performance_query")),
    Caso("get_hourly_performance", ("hourly_performance_query",), _unico("hourly_performance_query")),
    Caso(
        "get_performance_breakdown",
        ("build_performance_breakdown_query",),
        _unico("build_performance_breakdown_query"),
        {"level": "campaign"},
    ),
]


def _janelas(resposta: dict[str, Any]) -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
    """(o que `period`/`previous_period` dizem, o que os `date_range` ecoados dizem).

    A resposta ja trazia `period` (`{from, to}`); o eco repete a janela na forma
    do F191 (`{start, end}`). Dois lugares para o mesmo dado so nao divergem se
    algo confere — e e aqui.
    """
    ditas = {
        (resposta[k]["from"], resposta[k]["to"])
        for k in ("period", "previous_period")
        if k in resposta
    }
    fa = resposta["filters_applied"]
    blocos = [fa, *(v for v in fa.values() if isinstance(v, dict))]
    ecoadas = {
        (b["date_range"]["start"], b["date_range"]["end"])
        for b in blocos
        if isinstance(b.get("date_range"), dict) and "start" in b["date_range"]
    }
    return ditas, ecoadas


@pytest.mark.asyncio
@pytest.mark.parametrize("caso", CASOS, ids=[c.tool for c in CASOS])
async def test_a_resposta_ecoa_o_recorte_da_query_que_rodou(caso: Caso) -> None:
    from src.mcp.tools._registry import get_tool, import_all_tools

    import_all_tools()
    tool = get_tool(caso.tool)
    assert tool is not None, f"tool `{caso.tool}` nao esta no registry"
    modulo = importlib.import_module(f"src.mcp.tools.{caso.tool}")

    registro: Registro = {f: [] for f in caso.funcoes}
    espioes = []
    for nome in caso.funcoes:
        original = getattr(modulo, nome)

        def espiao(*a: Any, _o: Any = original, _n: str = nome, **k: Any) -> Any:
            resultado = _o(*a, **k)
            registro[_n].append(resultado)
            return resultado

        espioes.append(patch.object(modulo, nome, side_effect=espiao))

    with patch.object(modulo, "run_report", new_callable=AsyncMock) as rr:
        rr.return_value = []
        for e in espioes:
            e.start()
        try:
            resposta = await tool.handler({"customer_id": _CONTA, **caso.args})
        finally:
            for e in espioes:
                e.stop()

    executadas = [c.kwargs["query"] for c in rr.await_args_list]
    for nome, chamadas in registro.items():
        assert chamadas, f"`{nome}` nao foi chamada — a tool nao usa a funcao que o caso diz"
        for gaql, _filtros in chamadas:
            assert gaql in executadas, f"a tool rodou outra query que a de `{nome}`"
    assert resposta["filters_applied"] == caso.esperado(registro)
    ditas, ecoadas = _janelas(resposta)
    assert ditas == ecoadas, f"`period` diz {ditas} e o eco diz {ecoadas}"
    assert _FRASE_DO_ECO in tool.description, (
        f"`{caso.tool}` ecoa filters_applied e a description nao diz (spec §3.2)"
    )
```

- [ ] **Step 3: Rode e veja falhar**

```bash
python -m pytest tests/unit/test_filters_applied_e_derivado.py tests/unit/test_filters_applied_chega_na_resposta.py -q
```

Expected: FAIL. Previsões registradas: `test_toda_funcao_convertida_ecoa_cada_corte_do_where` falha no desempacotamento (as funções ainda devolvem `str`); `test_chamada_de_funcao_de_query_em_teste_desempacota_a_tupla` acusa **26** `arquivo:linha`; os 9 casos de eco falham. Os dois controles (`o_parser_novo_ve`, `o_detector_de_desempacotamento`) e o teste do F191 já passam.

- [ ] **Step 4: Acrescente os dois helpers em `_common.py`**

Logo depois de `gaql_date_clause`:

```python
def janela_aplicada(start: date, end: date) -> dict[str, str]:
    """O `date_range` que `filters_applied` ecoa para a janela de `gaql_date_clause`.

    Mesma forma do F191 (`{"start", "end"}`). Mora ao lado da clausula para que
    quem monta uma monte a outra: o eco derivado da mesma fonte (spec 2026-09-25).
    """
    return {"start": start.isoformat(), "end": end.isoformat()}
```

Logo depois de `build_metric_filter_clause`:

```python
def filtros_de_metrica(
    min_cost_brl: float | None = None,
    min_clicks: int | None = None,
    min_conversions: float | None = None,
) -> dict[str, float | int]:
    """O eco de `build_metric_filter_clause`: so os minimos que viraram clausula.

    Funcao irma, e nao retorno duplo, porque `build_metric_filter_clause` tem teste
    da string exata. O guard derivado (`test_toda_funcao_convertida_ecoa_cada_corte_
    do_where`) acusa se as duas descolarem.
    """
    ecos: dict[str, float | int] = {}
    if min_cost_brl is not None:
        ecos["min_cost_brl"] = min_cost_brl
    if min_clicks is not None:
        ecos["min_clicks"] = min_clicks
    if min_conversions is not None:
        ecos["min_conversions"] = min_conversions
    return ecos
```

- [ ] **Step 5: Converta `performance.py` inteiro**

```python
"""GAQL queries for performance analysis tools.

Cada funcao devolve `(gaql, filtros)`: `filtros` e o recorte que a query aplica,
montado junto da clausula do WHERE que o aplica. As tools o ecoam em
`filters_applied` (spec 2026-09-25, padrao do F191).
"""

from datetime import date
from typing import Any

from src.google_ads.queries._common import gaql_date_clause, janela_aplicada


def campaign_performance_query(
    start: date, end: date, status: str, limit: int
) -> tuple[str, dict[str, Any]]:
    filtros: dict[str, Any] = {"date_range": janela_aplicada(start, end)}
    status_clause = ""
    if status != "all":
        status_clause = f"AND campaign.status = '{status.upper()}'"
        filtros["campaign_status"] = status.upper()
    gaql = f"""
        SELECT
          campaign.id, campaign.name, campaign.status,
          campaign.advertising_channel_type,
          metrics.impressions, metrics.clicks, metrics.cost_micros,
          metrics.conversions, metrics.conversions_value
        FROM campaign
        WHERE {gaql_date_clause(start, end)} {status_clause}
        ORDER BY metrics.cost_micros DESC
        LIMIT {limit + 1}
    """.strip()
    return gaql, filtros


def ad_group_performance_query(
    start: date, end: date, status: str, limit: int
) -> tuple[str, dict[str, Any]]:
    filtros: dict[str, Any] = {"date_range": janela_aplicada(start, end)}
    status_clause = ""
    if status != "all":
        status_clause = f"AND ad_group.status = '{status.upper()}'"
        filtros["ad_group_status"] = status.upper()
    gaql = f"""
        SELECT
          ad_group.id, ad_group.name, ad_group.status,
          campaign.id, campaign.name,
          metrics.impressions, metrics.clicks, metrics.cost_micros,
          metrics.conversions, metrics.conversions_value
        FROM ad_group
        WHERE {gaql_date_clause(start, end)} {status_clause}
        ORDER BY metrics.cost_micros DESC
        LIMIT {limit + 1}
    """.strip()
    return gaql, filtros


def device_performance_query(start: date, end: date) -> tuple[str, dict[str, Any]]:
    gaql = f"""
        SELECT
          segments.device,
          metrics.impressions, metrics.clicks, metrics.cost_micros,
          metrics.conversions, metrics.conversions_value
        FROM customer
        WHERE {gaql_date_clause(start, end)}
    """.strip()
    return gaql, {"date_range": janela_aplicada(start, end)}


def geo_performance_query(start: date, end: date, limit: int) -> tuple[str, dict[str, Any]]:
    """Geographic performance from geographic_view (country-level criterion)."""
    gaql = f"""
        SELECT
          geographic_view.country_criterion_id,
          metrics.impressions, metrics.clicks, metrics.cost_micros,
          metrics.conversions, metrics.conversions_value
        FROM geographic_view
        WHERE {gaql_date_clause(start, end)}
        ORDER BY metrics.cost_micros DESC
        LIMIT {limit + 1}
    """.strip()
    return gaql, {"date_range": janela_aplicada(start, end)}


def hourly_performance_query(start: date, end: date) -> tuple[str, dict[str, Any]]:
    gaql = f"""
        SELECT
          segments.hour, segments.day_of_week,
          metrics.impressions, metrics.clicks, metrics.cost_micros,
          metrics.conversions, metrics.conversions_value
        FROM customer
        WHERE {gaql_date_clause(start, end)}
    """.strip()
    return gaql, {"date_range": janela_aplicada(start, end)}
```

- [ ] **Step 6: Converta as três funções de `tactical.py` que o breakdown despacha**

Import: `from src.google_ads.queries._common import build_metric_filter_clause, filtros_de_metrica, gaql_date_clause, janela_aplicada`, mais `from typing import Any`.

```python
def keyword_performance_query(
    start: date,
    end: date,
    status: str,
    limit: int,
    *,
    min_cost_brl: float | None = None,
    min_clicks: int | None = None,
    min_conversions: float | None = None,
) -> tuple[str, dict[str, Any]]:
    filtros: dict[str, Any] = {"date_range": janela_aplicada(start, end)}
    status_clause = ""
    if status != "all":
        status_clause = f"AND ad_group_criterion.status = '{status.upper()}'"
        filtros["criterion_status"] = status.upper()
    metric_clause = build_metric_filter_clause(min_cost_brl, min_clicks, min_conversions)
    filtros.update(filtros_de_metrica(min_cost_brl, min_clicks, min_conversions))
    gaql = f"""
        SELECT
          ad_group_criterion.criterion_id,
          ad_group_criterion.keyword.text,
          ad_group_criterion.keyword.match_type,
          ad_group_criterion.status,
          ad_group_criterion.negative,
          ad_group_criterion.quality_info.quality_score,
          ad_group_criterion.quality_info.creative_quality_score,
          ad_group_criterion.quality_info.post_click_quality_score,
          ad_group_criterion.quality_info.search_predicted_ctr,
          ad_group_criterion.position_estimates.first_page_cpc_micros,
          ad_group_criterion.position_estimates.top_of_page_cpc_micros,
          ad_group.id, ad_group.name,
          campaign.id, campaign.name,
          metrics.impressions, metrics.clicks, metrics.cost_micros,
          metrics.conversions, metrics.conversions_value
        FROM keyword_view
        WHERE {gaql_date_clause(start, end)} {status_clause} {metric_clause}
        ORDER BY metrics.cost_micros DESC
        LIMIT {limit + 1}
    """.strip()
    return gaql, filtros


def ad_performance_query(
    start: date, end: date, status: str, limit: int
) -> tuple[str, dict[str, Any]]:
    filtros: dict[str, Any] = {"date_range": janela_aplicada(start, end)}
    status_clause = ""
    if status != "all":
        status_clause = f"AND ad_group_ad.status = '{status.upper()}'"
        filtros["ad_status"] = status.upper()
    gaql = f"""
        SELECT
          ad_group_ad.ad.id,
          ad_group_ad.status,
          ad_group_ad.ad.type,
          ad_group_ad.ad.responsive_search_ad.headlines,
          ad_group_ad.ad.responsive_search_ad.descriptions,
          ad_group_ad.ad.final_urls,
          ad_group_ad.ad_strength,
          ad_group.id, ad_group.name,
          campaign.id, campaign.name,
          metrics.impressions, metrics.clicks, metrics.cost_micros,
          metrics.conversions, metrics.conversions_value
        FROM ad_group_ad
        WHERE {gaql_date_clause(start, end)} {status_clause}
        ORDER BY metrics.cost_micros DESC
        LIMIT {limit + 1}
    """.strip()
    return gaql, filtros


def audience_performance_query(start: date, end: date, limit: int) -> tuple[str, dict[str, Any]]:
    gaql = f"""
        SELECT
          ad_group_audience_view.resource_name,
          ad_group_criterion.criterion_id,
          ad_group_criterion.user_list.user_list,
          ad_group_criterion.user_interest.user_interest_category,
          ad_group.id, ad_group.name,
          campaign.id, campaign.name,
          metrics.impressions, metrics.clicks, metrics.cost_micros,
          metrics.conversions, metrics.conversions_value
        FROM ad_group_audience_view
        WHERE {gaql_date_clause(start, end)}
        ORDER BY metrics.cost_micros DESC
        LIMIT {limit + 1}
    """.strip()
    return gaql, {"date_range": janela_aplicada(start, end)}
```

`search_terms_query`, `negative_keywords_audit_query` e `conversion_actions_query` **não mudam nesta task** (Task 3).

- [ ] **Step 7: O builder do breakdown**

Em `src/google_ads/performance_breakdown.py`, a assinatura vira `-> tuple[str, dict[str, Any]]` (o corpo já devolve o que a função despachada devolve) e a docstring ganha:

```python
    """Despacha por `level`/`breakdown` e devolve o `(gaql, filtros)` da funcao
    despachada — o recorte que a tool ecoa em `filters_applied`.

    O ramo `campaign`+`hourly` nao passa por aqui: a tool monta a conjunta com
    `day_hour_metrics_query` (ad_schedule.py), fora do escopo do eco (spec
    2026-09-25, §7) — aquela resposta nao traz `filters_applied`.
    """
```

- [ ] **Step 8: As 9 tools desempacotam e ecoam**

Padrão (exemplo completo em `get_campaign_performance.py`). Antes de `rows = await run_report(`:

```python
    gaql, filtros = campaign_performance_query(start, end, status, limit)
```

Dentro do `run_report(...)`, a linha `query=campaign_performance_query(start, end, status, limit),` vira `query=gaql,`. No `return`, logo depois da linha `"period": ...`:

```python
        "filters_applied": filtros,
```

A linha `query=...` de cada uma das outras oito, e o que ela vira:

| tool | linha `query=` de hoje | desempacotar antes do `run_report` |
|---|---|---|
| `get_ad_group_performance` | `query=ad_group_performance_query(start, end, status, limit),` | `gaql, filtros = ad_group_performance_query(start, end, status, limit)` |
| `get_ad_performance` | `query=ad_performance_query(start, end, status, limit),` | `gaql, filtros = ad_performance_query(start, end, status, limit)` |
| `get_audience_performance` | `query=audience_performance_query(start, end, limit),` | `gaql, filtros = audience_performance_query(start, end, limit)` |
| `get_device_performance` | `query=device_performance_query(start, end),` | `gaql, filtros = device_performance_query(start, end)` |
| `get_geo_performance` | `query=geo_performance_query(start, end, limit),` | `gaql, filtros = geo_performance_query(start, end, limit)` |
| `get_hourly_performance` | `query=hourly_performance_query(start, end),` | `gaql, filtros = hourly_performance_query(start, end)` |
| `get_keyword_performance` | o bloco de 9 linhas `query=keyword_performance_query(` … `),` | `gaql, filtros = keyword_performance_query(start, end, status, limit, min_cost_brl=args.get("min_cost_brl"), min_clicks=args.get("min_clicks"), min_conversions=args.get("min_conversions"))` |
| `get_performance_breakdown` | `query=build_performance_breakdown_query(level, breakdown, status, start, end, limit),` | `gaql, filtros = build_performance_breakdown_query(level, breakdown, status, start, end, limit)` |

Em todas, `query=gaql,` no `run_report` e `"filters_applied": filtros,` logo depois de `"period"` no `return`. No `get_performance_breakdown`, o `return` certo é o **último** da função (o que vem depois do `run_report` principal); o `return` do ramo `campaign`+`hourly` não muda.

E na `description` de cada uma das 9, como último fragmento: `" filters_applied diz o recorte que a query aplicou."` — o guard de eco confere.

- [ ] **Step 9: Converta as 26 chamadas de teste**

Rode, da raiz do repo, preservando o fim de linha de cada arquivo:

```bash
python - <<'EOF'
import pathlib, re
NOMES = ["campaign_performance_query", "ad_group_performance_query", "device_performance_query",
         "geo_performance_query", "hourly_performance_query", "ad_performance_query",
         "keyword_performance_query", "audience_performance_query", "build_performance_breakdown_query"]
padrao = re.compile(r"^(\s*)([A-Za-z_]\w*) = (" + "|".join(NOMES) + r")\(", re.M)
total = 0
for p in sorted(pathlib.Path("tests").rglob("*.py")):
    if p.name == "test_filters_applied_e_derivado.py":
        continue
    raw = p.read_bytes().decode("utf-8")
    nl = "\r\n" if "\r\n" in raw else "\n"
    novo, n = padrao.subn(r"\1\2, _ = \3(", raw.replace("\r\n", "\n"))
    if n:
        p.write_bytes(novo.replace("\n", nl).encode("utf-8"))
        total += n
        print(p, n)
print("TOTAL:", total, "(previsto: 26)")
EOF
```

Expected: `TOTAL: 26`. Se der outro número, pare: o guard de desempacotamento é quem decide o que ainda falta.

- [ ] **Step 10: Rode e veja passar**

```bash
python -m pytest tests/unit/test_filters_applied_e_derivado.py tests/unit/test_filters_applied_chega_na_resposta.py tests/unit/test_query_builders_gaql.py tests/unit/test_performance_breakdown.py tests/unit/test_keyword_performance_filters.py tests/unit/test_builders_pedem_a_linha_sentinela.py tests/unit/test_tools_declaram_truncamento.py -q
python scripts/check_pre_push.py > "$SCRATCH/gate.log" 2>&1; echo "EXIT=$?"
```

Expected: tudo verde; o guard de desempacotamento acusava 26 no Step 3 e acusa 0; gate 6/6, EXIT=0.

- [ ] **Step 11: Commit**

```bash
git add src/ tests/
git commit -m "fix(google_ads): os 8 reports da Fase 2B e o breakdown ecoam o recorte que a query aplicou"
```

---

### Task 3: Termos de busca, negativas e conversões ecoam; a auditoria de negativas declara o escopo

**Files:**
- Modify: `src/google_ads/queries/tactical.py` (`search_terms_query`, `negative_keywords_audit_query`, `conversion_actions_query`)
- Modify: `src/mcp/tools/get_search_terms_report.py`, `get_negative_keywords_audit.py`, `get_conversion_actions.py`
- Modify: `tests/unit/test_filters_applied_e_derivado.py` (`tactical.py` entra em `_MODULOS_CONVERTIDOS`; 3 chamadas novas)
- Modify: `tests/unit/test_filters_applied_chega_na_resposta.py` (3 casos)
- Modify: `tests/unit/test_unbounded_reads_have_limit.py` (parametrize com extrator)
- Modify (conversão mecânica, 7 chamadas): `tests/unit/test_query_builders_gaql.py`, `tests/unit/test_search_terms_filters.py`
- Test novo: em `tests/unit/test_query_builders_gaql.py`

**Interfaces:**
- Consumes: `janela_aplicada`, `filtros_de_metrica` (Task 2).
- Produces: as três funções devolvem `tuple[str, dict[str, Any]]`; `negative_keywords_audit_query()` devolve `filtros == {"nivel": "campanha", "negative": True, "criterion_type": "KEYWORD"}`; `conversion_actions_query()` devolve `filtros == {}`.

- [ ] **Step 1: Estenda os guards e escreva o teste do escopo**

Em `test_filters_applied_e_derivado.py`: `_MODULOS_CONVERTIDOS` ganha `h.SRC / "google_ads" / "queries" / "tactical.py"`; `_chamadas()` ganha

```python
        "search_terms_query": lambda: t.search_terms_query(
            _S, _E, 10, min_cost_brl=10.0, min_clicks=5, min_conversions=1.0
        ),
        "negative_keywords_audit_query": lambda: t.negative_keywords_audit_query(),
        "conversion_actions_query": lambda: t.conversion_actions_query(limit=10),
```

Em `test_filters_applied_chega_na_resposta.py`, `CASOS` ganha

```python
    Caso("get_search_terms_report", ("search_terms_query",), _unico("search_terms_query")),
    Caso(
        "get_negative_keywords_audit",
        ("negative_keywords_audit_query",),
        _unico("negative_keywords_audit_query"),
    ),
    Caso("get_conversion_actions", ("conversion_actions_query",), _unico("conversion_actions_query")),
```

Em `test_query_builders_gaql.py`, acrescente:

```python
def test_auditoria_de_negativas_declara_que_so_le_campanha() -> None:
    """A description dizia "conta inteira"; a query le so `campaign_criterion`.
    Negativas de grupo e listas compartilhadas NAO entram (spec 2026-09-25, §4.3)."""
    gaql, filtros = negative_keywords_audit_query()
    assert "FROM campaign_criterion" in gaql
    assert filtros["nivel"] == "campanha"


def test_conversoes_nao_cortam_nada_e_dizem_isso() -> None:
    _gaql, filtros = conversion_actions_query(limit=10)
    assert filtros == {}
```

- [ ] **Step 2: Rode e veja falhar**

```bash
python -m pytest tests/unit/test_filters_applied_e_derivado.py tests/unit/test_filters_applied_chega_na_resposta.py tests/unit/test_query_builders_gaql.py -q
```

Expected: FAIL. Previsão: o guard de desempacotamento acusa **7**; os 3 casos de eco e os 2 testes novos falham.

- [ ] **Step 3: As três funções**

```python
def search_terms_query(
    start: date,
    end: date,
    limit: int,
    *,
    min_cost_brl: float | None = None,
    min_clicks: int | None = None,
    min_conversions: float | None = None,
) -> tuple[str, dict[str, Any]]:
    filtros: dict[str, Any] = {"date_range": janela_aplicada(start, end)}
    metric_clause = build_metric_filter_clause(min_cost_brl, min_clicks, min_conversions)
    filtros.update(filtros_de_metrica(min_cost_brl, min_clicks, min_conversions))
    gaql = f"""
        SELECT
          search_term_view.search_term,
          search_term_view.status,
          ad_group.id, ad_group.name,
          campaign.id, campaign.name,
          metrics.impressions, metrics.clicks, metrics.cost_micros,
          metrics.conversions, metrics.conversions_value
        FROM search_term_view
        WHERE {gaql_date_clause(start, end)} {metric_clause}
        ORDER BY metrics.cost_micros DESC
        LIMIT {limit + 1}
    """.strip()
    return gaql, filtros


def negative_keywords_audit_query() -> tuple[str, dict[str, Any]]:
    """Negativas de keyword no NIVEL DE CAMPANHA — so elas.

    Negativas de grupo (`ad_group_criterion`) e listas compartilhadas
    (`shared_criterion`) nao entram: o `nivel` no `filtros` diz isso na resposta
    (spec 2026-09-25, §4.3). Cobrir a conta inteira e frente propria.
    """
    gaql = """
        SELECT
          campaign_criterion.criterion_id,
          campaign_criterion.negative,
          campaign_criterion.keyword.text,
          campaign_criterion.keyword.match_type,
          campaign.id,
          campaign.name
        FROM campaign_criterion
        WHERE campaign_criterion.negative = true
          AND campaign_criterion.type = 'KEYWORD'
    """.strip()
    filtros: dict[str, Any] = {"nivel": "campanha", "negative": True, "criterion_type": "KEYWORD"}
    return gaql, filtros


def conversion_actions_query(limit: int = 100) -> tuple[str, dict[str, Any]]:
    """F98 — `limit + 1`: a linha extra é a sentinela que revela o corte.

    Nao corta nada: o `filtros` vazio e o eco honesto, nao uma ausencia.
    """
    gaql = f"""
        SELECT
          conversion_action.id,
          conversion_action.name,
          conversion_action.status,
          conversion_action.category,
          conversion_action.type,
          conversion_action.counting_type,
          conversion_action.attribution_model_settings.attribution_model,
          conversion_action.value_settings.default_value,
          conversion_action.value_settings.always_use_default_value,
          conversion_action.primary_for_goal,
          conversion_action.include_in_conversions_metric
        FROM conversion_action
        LIMIT {limit + 1}
    """.strip()
    return gaql, {}
```

- [ ] **Step 4: As três tools**

- `get_search_terms_report`: `gaql, filtros = search_terms_query(start, end, limit, min_cost_brl=args.get("min_cost_brl"), min_clicks=args.get("min_clicks"), min_conversions=args.get("min_conversions"))` antes do `run_report`; o bloco `query=search_terms_query(` … `),` vira `query=gaql,`; `"filters_applied": filtros,` depois de `"period"`.
- `get_conversion_actions`: `gaql, filtros = conversion_actions_query(limit=limit)` antes do `run_report`; `query=gaql,`; no `return`, `"filters_applied": filtros,` depois de `"customer_id"`.
- `get_negative_keywords_audit`: `gaql, filtros = negative_keywords_audit_query()` antes de `negatives_task = run_report(`; `query=negative_keywords_audit_query(),` vira `query=gaql,`; no `return` final, `"filters_applied": filtros,` depois de `"customer_id"`.

**E o texto, nos dois lugares.** Na description do parâmetro `limit`, a linha

```python
                "total_negatives + additions_summary refletem conta inteira (nao truncados). "
```

vira

```python
                "total_negatives + additions_summary contam todas as negativas DE CAMPANHA "
                "da conta, nao so as da pagina. "
```

Na description da tool, o par de linhas

```python
        "counts por janela (7d / 30d / pre-30d-ou-desconhecido) — sobre a conta "
        "INTEIRA, nao truncado. by_campaign retorna max `limit` negativas "
```

vira

```python
        "counts por janela (7d / 30d / pre-30d-ou-desconhecido) — sobre todas as "
        "negativas DE CAMPANHA, nao so a pagina. by_campaign retorna max `limit` negativas "
```

e o par final

```python
        "Quando truncado, response inclui `truncated: true` + `total_negatives` "
        "reflete o universo completo da conta."
```

vira

```python
        "Quando truncado, response inclui `truncated: true`; `total_negatives` conta "
        "todas as negativas de campanha. Negativas de grupo e listas compartilhadas "
        "NAO entram (`filters_applied.nivel`)."
        " filters_applied diz o recorte que a query aplicou."
```

(A query de criações, `negative_criterion_creations_query`, também filtra `CAMPAIGN_CRITERION`: o texto novo é verdade para as duas contagens.) Em `get_search_terms_report` e `get_conversion_actions`, o mesmo `" filters_applied diz o recorte que a query aplicou."` entra como último fragmento da `description`.

- [ ] **Step 5: `test_unbounded_reads_have_limit.py` — o parametrize misto**

O parametrize de `test_builder_emite_limit_com_a_linha_sentinela` vira:

```python
@pytest.mark.parametrize(
    "builder,gaql_de",
    [
        (recommendations_query, lambda q: q),  # segue devolvendo so o texto
        (conversion_actions_query, lambda q: q[0]),  # (gaql, filtros) desde 2026-09-26
        (budget_pacing_query, lambda q: q),  # vira q[0] na Task 4
    ],
    ids=["recommendations", "conversion_actions", "budget_pacing"],
)
def test_builder_emite_limit_com_a_linha_sentinela(builder: Any, gaql_de: Any) -> None:
```

e as duas asserções do corpo viram `assert "LIMIT 101" in gaql_de(builder(limit=100))` e `assert "LIMIT 26" in gaql_de(builder(limit=25))`. (Chamada por nome local, `builder(...)`: o guard de desempacotamento não a vê — por isso a edição é explícita.)

- [ ] **Step 6: Converta as 7 chamadas de teste**

O script do Step 9 da Task 2 com `NOMES = ["search_terms_query", "negative_keywords_audit_query", "conversion_actions_query"]`. Expected: `TOTAL: 7`.

- [ ] **Step 7: Rode, gate, commit**

```bash
python -m pytest tests/unit/test_filters_applied_e_derivado.py tests/unit/test_filters_applied_chega_na_resposta.py tests/unit/test_query_builders_gaql.py tests/unit/test_search_terms_filters.py tests/unit/test_unbounded_reads_have_limit.py -q
python scripts/check_pre_push.py > "$SCRATCH/gate.log" 2>&1; echo "EXIT=$?"
git add src/ tests/
git commit -m "fix(google_ads): termos, negativas e conversoes ecoam o recorte; negativas declaram o nivel"
```

---

### Task 4: Funil, top keywords/criativos, overview e pacing ecoam o recorte

**Files:**
- Modify: `src/google_ads/queries/client_report.py` (`funnel_query`, `top_keywords_query`, `top_creatives_query`)
- Modify: `src/google_ads/queries/overview.py` (`overview_query`, `budget_pacing_query`)
- Modify: `src/mcp/tools/get_funnel_metrics.py`, `get_top_keywords_creatives.py`, `get_account_overview.py`, `get_budget_pacing.py`
- Modify: `tests/unit/test_filters_applied_e_derivado.py`, `tests/unit/test_filters_applied_chega_na_resposta.py`, `tests/unit/test_unbounded_reads_have_limit.py`
- Modify (17 chamadas: 9 mecânicas + 8 irregulares): `tests/unit/test_query_builders_gaql.py`, `tests/unit/test_unbounded_reads_have_limit.py`

**Interfaces:**
- Consumes: `janela_aplicada` (Task 2).
- Produces: as cinco funções devolvem `tuple[str, dict[str, Any]]`. `budget_pacing_query()` devolve `filtros == {"campaign_status": "ENABLED", "date_range": {"during": "THIS_MONTH"}}`.

- [ ] **Step 1: Estenda os guards**

`_MODULOS_CONVERTIDOS` ganha `client_report.py` e `overview.py`; `_chamadas()` ganha (com `from src.google_ads.queries import client_report as c, overview as o`):

```python
        "funnel_query": lambda: c.funnel_query(_S, _E),
        "top_keywords_query": lambda: c.top_keywords_query(_S, _E, 10, metric="cost"),
        "top_creatives_query": lambda: c.top_creatives_query(_S, _E, 10, metric="cost"),
        "overview_query": lambda: o.overview_query(_S, _E),
        "budget_pacing_query": lambda: o.budget_pacing_query(limit=10),
```

`CASOS` ganha:

```python
    Caso("get_funnel_metrics", ("funnel_query",), _unico("funnel_query")),
    Caso("get_budget_pacing", ("budget_pacing_query",), _unico("budget_pacing_query")),
    Caso(
        "get_top_keywords_creatives",
        ("top_keywords_query", "top_creatives_query"),
        lambda r: {
            "top_keywords": r["top_keywords_query"][0][1],
            "top_creatives": r["top_creatives_query"][0][1],
        },
    ),
    Caso(
        "get_account_overview",
        ("overview_query",),
        lambda r: {"current": r["overview_query"][0][1], "previous": r["overview_query"][1][1]},
    ),
```

E, no fim do mesmo arquivo — agora que `CASOS` cobre as 16 —, a população derivada. Ela precisa de `import ast` e `from tests.unit import _guard_harness as h` no topo:

```python
# Modulos cujas funcoes montam o GAQL que as tools rodam. Tool que importa deles
# tem de estar em `CASOS`: a lista acima e conferida por varredura, nao lembrada.
_MODULOS_DE_QUERY = {
    "src.google_ads.queries.performance",
    "src.google_ads.queries.tactical",
    "src.google_ads.queries.client_report",
    "src.google_ads.queries.overview",
    "src.google_ads.queries.bulk_pause",
    "src.google_ads.performance_breakdown",
}
# O preview do bulk_pause_by_query e um dry-run de mutacao (grava token no banco):
# o eco dele e conferido em tests/unit/test_bulk_pause_tool.py.
_FORA_DO_ECO_DE_LEITURA = {"bulk_pause_by_query"}


def _tools_que_usam_as_funcoes_de_query() -> set[str]:
    return {
        p.stem
        for p in h.fontes_py(h.SRC / "mcp" / "tools")
        if any(
            isinstance(no, ast.ImportFrom) and no.module in _MODULOS_DE_QUERY
            for no in ast.walk(h.arvore(p))
        )
    }


def test_toda_tool_que_monta_query_dos_cinco_modulos_esta_no_eco() -> None:
    usam = _tools_que_usam_as_funcoes_de_query()
    assert len(usam) >= 17, f"piso medido em 26/09 (16 de leitura + bulk_pause): {sorted(usam)}"
    faltam = sorted(usam - _FORA_DO_ECO_DE_LEITURA - {c.tool for c in CASOS})
    assert not faltam, (
        f"tool que roda query dos cinco modulos e nao esta em CASOS: {faltam}. "
        "Acrescente o Caso: a resposta dela tem de ecoar filters_applied."
    )
```

- [ ] **Step 2: Rode e veja falhar**

Expected: FAIL. Previsão: o guard de desempacotamento acusa **17**; os 4 casos de eco falham. O `test_toda_tool_que_monta_query_dos_cinco_modulos_esta_no_eco` já passa — ele confere a lista, não a tool —, então a mordida dele se prova à parte: comente um `Caso`, veja `faltam` acusar a tool, e restaure.

- [ ] **Step 3: `client_report.py`**

Import: `from src.google_ads.queries._common import gaql_date_clause, janela_aplicada` e `from typing import Any`.

```python
def funnel_query(start: date, end: date) -> tuple[str, dict[str, Any]]:
    """Aggregate funnel metrics from customer-level for the period."""
    gaql = f"""
        SELECT
          metrics.impressions,
          metrics.clicks,
          metrics.cost_micros,
          metrics.conversions,
          metrics.conversions_value
        FROM customer
        WHERE {gaql_date_clause(start, end)}
    """.strip()
    return gaql, {"date_range": janela_aplicada(start, end)}
```

`top_keywords_query` e `top_creatives_query` inteiras (o SELECT, o `ORDER BY` e o `LIMIT` são os de hoje; `_ORDER_FIELD`, `_DESEMPATE` e `_order_by` não mudam):

```python
def top_keywords_query(
    start: date, end: date, top_n: int, *, metric: str
) -> tuple[str, dict[str, Any]]:
    """Top N keywords by `metric`: o Google ordena e corta, nesta ordem.

    `metric` entra no `ORDER BY` porque o `LIMIT` e do lado do Google — se a
    ordenacao nao for a pedida, o top-N devolvido e o top-N de OUTRA coluna, e
    nenhum re-sort no cliente traz de volta a linha que nao veio (C5).
    """
    gaql = f"""
        SELECT
          ad_group_criterion.criterion_id,
          ad_group_criterion.keyword.text,
          ad_group_criterion.keyword.match_type,
          ad_group.id, ad_group.name,
          campaign.id, campaign.name,
          metrics.impressions, metrics.clicks, metrics.cost_micros,
          metrics.conversions, metrics.conversions_value
        FROM keyword_view
        WHERE {gaql_date_clause(start, end)}
          AND ad_group_criterion.status = 'ENABLED'
        ORDER BY {_order_by(metric)}
        LIMIT {top_n}
    """.strip()
    return gaql, {"date_range": janela_aplicada(start, end), "criterion_status": "ENABLED"}


def top_creatives_query(
    start: date, end: date, top_n: int, *, metric: str
) -> tuple[str, dict[str, Any]]:
    """Top N RSAs by `metric`: o Google ordena e corta, nesta ordem (ver C5)."""
    gaql = f"""
        SELECT
          ad_group_ad.ad.id,
          ad_group_ad.ad.responsive_search_ad.headlines,
          ad_group_ad.ad.responsive_search_ad.descriptions,
          ad_group_ad.ad_strength,
          ad_group.id, ad_group.name,
          campaign.id, campaign.name,
          metrics.impressions, metrics.clicks, metrics.cost_micros,
          metrics.conversions, metrics.conversions_value
        FROM ad_group_ad
        WHERE {gaql_date_clause(start, end)}
          AND ad_group_ad.status = 'ENABLED'
        ORDER BY {_order_by(metric)}
        LIMIT {top_n}
    """.strip()
    return gaql, {"date_range": janela_aplicada(start, end), "ad_status": "ENABLED"}
```

- [ ] **Step 4: `overview.py`**

```python
def overview_query(date_start: date, date_end: date) -> tuple[str, dict[str, Any]]:
    """Metricas agregadas da conta (recurso `customer`) no periodo.

    Nao filtra status: a docstring antiga dizia "across all enabled campaigns",
    e a query nunca teve esse corte.
    """
    gaql = f"""
        SELECT
          metrics.impressions,
          metrics.clicks,
          metrics.cost_micros,
          metrics.conversions,
          metrics.conversions_value,
          metrics.ctr,
          metrics.average_cpc,
          metrics.cost_per_conversion
        FROM customer
        WHERE {gaql_date_clause(date_start, date_end)}
    """.strip()
    return gaql, {"date_range": janela_aplicada(date_start, date_end)}
```

`budget_pacing_query` inteira (o GAQL é o de hoje):

```python
def budget_pacing_query(limit: int = 100) -> tuple[str, dict[str, Any]]:
    """Per-campaign current budget + MTD spend.

    Returns one row per enabled campaign with budget amount + month-to-date metrics.

    F98 — `limit + 1` (a linha extra revela o corte) **e** `ORDER BY` explícito:
    o tool ordena por gasto DESC no fim, então cortar um conjunto não-ordenado
    entregaria N campanhas arbitrárias reordenadas entre si, parecendo o topo de
    gasto da conta sem ser — a classe F88 ("truncar e depois ordenar").

    A janela e `DURING THIS_MONTH`, resolvida pelo Google no fuso da conta; o eco a
    declara assim, `{"during": "THIS_MONTH"}`, e nao com datas que esta funcao nao
    calculou.
    """
    gaql = f"""
        SELECT
          campaign.id,
          campaign.name,
          campaign.status,
          campaign_budget.amount_micros,
          campaign_budget.delivery_method,
          metrics.cost_micros
        FROM campaign
        WHERE campaign.status = 'ENABLED'
          AND segments.date DURING THIS_MONTH
        ORDER BY metrics.cost_micros DESC
        LIMIT {limit + 1}
    """.strip()
    filtros: dict[str, Any] = {
        "campaign_status": "ENABLED",
        "date_range": {"during": "THIS_MONTH"},
    }
    return gaql, filtros
```

Imports de `overview.py`: `from typing import Any`, e `janela_aplicada` ao lado de `gaql_date_clause`.

- [ ] **Step 5: As quatro tools**

- `get_funnel_metrics`: `gaql, filtros = funnel_query(start, end)`; `query=gaql,`; `"filters_applied": filtros,` depois de `"period"`.
- `get_budget_pacing`: `gaql, filtros = budget_pacing_query(limit=limit)`; `query=gaql,`; `"filters_applied": filtros,` depois de `"as_of"`.
- `get_top_keywords_creatives`: `gaql_kw, filtros_kw = top_keywords_query(start, end, top_n, metric=metric)` e `gaql_cr, filtros_cr = top_creatives_query(start, end, top_n, metric=metric)` antes dos dois `run_report`; as linhas `query=` viram `query=gaql_kw,` e `query=gaql_cr,`; no `return`, depois de `"period"`:

```python
        "filters_applied": {"top_keywords": filtros_kw, "top_creatives": filtros_cr},
```

- `get_account_overview`: `gaql_atual, filtros_atual = overview_query(start, end)` e `gaql_anterior, filtros_anterior = overview_query(prev_start, prev_end)`; as duas linhas `query=` viram `query=gaql_atual,` e `query=gaql_anterior,`; no `return`, depois de `"previous_period"`:

```python
        "filters_applied": {"current": filtros_atual, "previous": filtros_anterior},
```

Nas quatro, como último fragmento da `description`: `" filters_applied diz o recorte que a query aplicou."`.

- [ ] **Step 6: As 17 chamadas de teste**

(a) O script da Task 2, Step 9, com `NOMES = ["funnel_query", "top_keywords_query", "top_creatives_query", "overview_query", "budget_pacing_query"]`. Expected: `TOTAL: 9`.

(b) As 8 irregulares, em `tests/unit/test_query_builders_gaql.py`, por conteúdo (as linhas se deslocam):

- em `test_top_keywords_query_limit_is_parameterized`, as duas chamadas diretas ganham `[0]`: `top_keywords_query(_S, _E, 25, metric="cost")[0]`;
- no laço `for nome, q in (("top_keywords_query", top_keywords_query(...)), ("top_creatives_query", top_creatives_query(...)))`, cada chamada ganha `[0]`;
- nos dois laços `for q in (top_keywords_query(...), top_creatives_query(...))` (desempate e custo repetido), cada chamada ganha `[0]`.

(c) Em `test_unbounded_reads_have_limit.py`, a entrada `(budget_pacing_query, lambda q: q),  # vira q[0] na Task 4` vira `(budget_pacing_query, lambda q: q[0]),  # (gaql, filtros) desde 2026-09-26`.

- [ ] **Step 7: Rode, gate, commit**

```bash
python -m pytest tests/unit/test_filters_applied_e_derivado.py tests/unit/test_filters_applied_chega_na_resposta.py tests/unit/test_query_builders_gaql.py tests/unit/test_unbounded_reads_have_limit.py tests/unit/test_get_top_keywords_creatives.py tests/unit/test_razao_indefinida.py tests/integration/test_overview_tools.py tests/integration/test_client_report_tools.py -q
python scripts/check_pre_push.py > "$SCRATCH/gate.log" 2>&1; echo "EXIT=$?"
git add src/ tests/
git commit -m "fix(google_ads): funil, top keywords, overview e pacing ecoam o recorte"
```

Expected: o guard de desempacotamento acusava 17 no Step 2 e acusa 0.

---

### Task 5: `bulk_pause_by_query` mede sempre no período, e o rótulo sai do `filtros`

**Files:**
- Modify: `src/google_ads/queries/bulk_pause.py` (`bulk_pause_query`)
- Modify: `src/mcp/tools/bulk_pause_by_query.py`
- Modify: `tests/unit/test_bulk_pause_query.py`, `tests/unit/test_bulk_pause_tool.py`, `tests/unit/test_filters_applied_e_derivado.py`

**Interfaces:**
- Consumes: `janela_aplicada`.
- Produces: `bulk_pause_query(*, target_type, filter_clause, start, end) -> tuple[str, dict[str, Any]]`, com `filtros["filtro_do_gestor"] == filter_clause` sempre, e `filtros["date_range"]` sempre que o filtro não traz `segments.date`.

- [ ] **Step 1: Testes**

Em `tests/unit/test_bulk_pause_query.py`:

```python
def test_filtro_so_de_entidade_ganha_a_janela() -> None:
    """Antes: sem `metrics.` no filtro, a janela nao entrava e o custo do preview
    era o de TODA A VIDA da entidade (medido em 25/09: R$ 3.013,88 contra
    R$ 638,05 nos 30 dias)."""
    gaql, filtros = bulk_pause_query(
        target_type="keyword",
        filter_clause="ad_group_criterion.status = 'ENABLED'",
        start=date(2026, 9, 1),
        end=date(2026, 9, 30),
    )
    assert "segments.date BETWEEN '2026-09-01' AND '2026-09-30'" in gaql
    assert filtros["date_range"] == {"start": "2026-09-01", "end": "2026-09-30"}
    assert filtros["filtro_do_gestor"] == "ad_group_criterion.status = 'ENABLED'"


def test_filtro_com_janela_propria_nao_ganha_outra() -> None:
    gaql, filtros = bulk_pause_query(
        target_type="campaign",
        filter_clause="segments.date DURING LAST_7_DAYS AND metrics.cost_micros > 0",
        start=date(2026, 9, 1),
        end=date(2026, 9, 30),
    )
    assert gaql.count("segments.date") == 1
    assert "date_range" not in filtros
```

(Confira os imports do arquivo; `date` e `bulk_pause_query` já são usados lá.)

Em `tests/unit/test_bulk_pause_tool.py`, acrescente um irmão de `test_valid_count_creates_token_with_capture`, com o mesmo aparato de `run_report`, `create_pending` e `connection`, mas com filtro só de entidade e capturando a query:

```python
@pytest.mark.asyncio
async def test_preview_com_filtro_so_de_entidade_diz_o_periodo_e_o_ecoa(monkeypatch):
    """O rotulo "no periodo" sai do `filtros`, e o custo e o do periodo (spec 2026-09-25, §4.1)."""
    from src.mcp.tools import bulk_pause_by_query as mod

    queries: list[str] = []

    async def fake_run_report(**kwargs):
        queries.append(kwargs["query"])
        return [
            {
                "ad_group_id": "111",
                "criterion_id": "200",
                "keyword_text": "test 1",
                "campaign_name": "Camp A",
                "ad_group_name": "AG 1",
                "cost_brl": 12.5,
            }
        ]

    async def fake_create_pending(conn, **kwargs):
        return "TOK01234"

    monkeypatch.setattr(mod, "run_report", fake_run_report)
    monkeypatch.setattr(mod, "create_pending", fake_create_pending)
    with patch("src.mcp.tools.bulk_pause_by_query.connection") as conn_module:
        conn_module.get_pool.return_value.acquire.return_value.__aenter__ = AsyncMock(
            return_value=AsyncMock()
        )
        conn_module.get_pool.return_value.acquire.return_value.__aexit__ = AsyncMock(
            return_value=None
        )
        result = await mod.bulk_pause_by_query(
            {
                "customer_id": "1234567890",
                "target_type": "keyword",
                "filter": "ad_group_criterion.status = 'ENABLED'",
            }
        )

    assert "segments.date BETWEEN" in queries[0]
    janela = result["preview"]["filters_applied"]["date_range"]
    assert f"no periodo {janela['start']} a {janela['end']}" in result["blast_summary"]

    from src.mcp.tools._registry import get_tool, import_all_tools

    import_all_tools()
    tool = get_tool("bulk_pause_by_query")
    assert tool is not None
    assert "filters_applied diz o recorte que a query aplicou." in tool.description
    # a description dizia "auto-injeta ... quando filter usa metrics.*": a regra antiga
    assert "exceto quando o filter ja traz segments.date" in tool.description


@pytest.mark.asyncio
async def test_sem_match_tambem_diz_a_janela(monkeypatch):
    """Zero linhas depende da janela que a query aplicou: o `no_op` diz qual."""
    from src.mcp.tools import bulk_pause_by_query as mod

    async def fake_run_report(**_kwargs):
        return []

    monkeypatch.setattr(mod, "run_report", fake_run_report)
    result = await mod.bulk_pause_by_query(
        {
            "customer_id": "1234567890",
            "target_type": "campaign",
            "filter": "campaign.status = 'ENABLED'",
        }
    )
    assert result["status"] == "no_op"
    assert "date_range" in result["filters_applied"]
```

Em `test_filters_applied_e_derivado.py`: `_MODULOS_CONVERTIDOS` ganha `bulk_pause.py`; `_chamadas()` ganha

```python
        "bulk_pause_query": lambda: bulk_pause_query(
            target_type="keyword",
            filter_clause="ad_group_criterion.status = 'ENABLED'",
            start=_S,
            end=_E,
        ),
```

(`from src.google_ads.queries.bulk_pause import bulk_pause_query`); em `test_toda_funcao_convertida_ecoa_cada_corte_do_where`, logo depois de `gaql, filtros = chamar()`:

```python
        if "filtro_do_gestor" in filtros:
            # texto livre do gestor: ecoado INTEIRO, e fora da analise campo a campo
            assert filtros["filtro_do_gestor"] in gaql
            gaql = gaql.replace(filtros["filtro_do_gestor"], "")
```

e o piso final:

```python
def test_o_escopo_final_tem_as_17_funcoes_nos_5_modulos() -> None:
    """Piso: sem ele, um modulo que saisse da tupla deixaria os guards menores e verdes."""
    assert len(_MODULOS_CONVERTIDOS) == 5
    assert len(_chamadas()) == 17
    assert {n for m in _MODULOS_CONVERTIDOS for n in _funcoes_publicas(m)} == set(_chamadas())
```

- [ ] **Step 2: Rode e veja falhar**

Expected: FAIL — os dois testes do builder (hoje devolve `str`, sem janela para filtro de entidade), os dois da tool (sem `filters_applied` nem janela — no preview e no `no_op`), e o guard de desempacotamento acusando **6**.

- [ ] **Step 3: O builder**

```python
def bulk_pause_query(
    *,
    target_type: str,
    filter_clause: str,
    start: date,
    end: date,
) -> tuple[str, dict[str, Any]]:
    """Compose the GAQL for the bulk_pause_by_query dry-run.

    target_type must be one of {keyword, ad, campaign, ad_group}.
    filter_clause must already have passed validate_filter().

    A janela entra SEMPRE, exceto quando o filtro do gestor ja traz
    `segments.date`: sem ela, `metrics.cost_micros` no SELECT vem com o custo de
    TODA A VIDA da entidade, e o preview dizia "no periodo" sobre ele (spec
    2026-09-25, §4.1 — medido: R$ 3.013,88 na vida contra R$ 638,05 em 30 dias).
    Probe em duas contas: a janela nao muda QUAIS entidades o filtro seleciona,
    nos quatro alvos. Refazer o probe se o Google mudar esse comportamento.
    """
    if target_type not in _TARGET_TO_QUERY:
        raise ValueError(
            f"target_type='{target_type}' invalido. Aceitos: {sorted(_TARGET_TO_QUERY)}."
        )

    resource, select_fields = _TARGET_TO_QUERY[target_type]
    select_clause = ", ".join(select_fields)

    filtros: dict[str, Any] = {"filtro_do_gestor": filter_clause}
    where_parts = []
    if "segments.date" not in filter_clause:
        where_parts.append(gaql_date_clause(start, end))
        filtros["date_range"] = janela_aplicada(start, end)
    # Note: do NOT wrap filter_clause in parentheses — GAQL does not support
    # parenthesized grouping in WHERE clauses (Google rejects with "invalid
    # field name '('"). validate_filter() already restricts to AND-chained
    # conditions; user-supplied OR conditions are technically supported but
    # will follow standard left-to-right precedence with AND binding tighter.
    where_parts.append(filter_clause)
    where_clause = " AND ".join(where_parts)

    gaql = f"""
        SELECT {select_clause}
        FROM {resource}
        WHERE {where_clause}
        LIMIT 101
    """.strip()
    return gaql, filtros
```

(Imports: `janela_aplicada` junto de `gaql_date_clause`; `from typing import Any`.)

- [ ] **Step 4: A tool**

`query = bulk_pause_query(` vira `query, filtros = bulk_pause_query(`. O resumo:

```python
    janela = filtros.get("date_range")
    periodo_txt = (
        f"no periodo {janela['start']} a {janela['end']}"
        if janela is not None
        else "no periodo definido no proprio filtro"
    )
    summary = (
        f"Pausar {count} {target_type}(s). Custo total R$ {total_cost:.2f} {periodo_txt}. "
        f"Amostra: " + ", ".join(f"'{s['label']}' ({s['context']})" for s in sample[:3])
    )
```

e o `preview={...}` do `preview_envelope` ganha `"filters_applied": filtros,`. O `no_op` (zero linhas) ganha a mesma chave, `"filters_applied": filtros,`, logo depois de `"matched_count": 0,` (decisão 15). E a `description` da tool ganha, como último fragmento, `" filters_applied diz o recorte que a query aplicou."`.

A mesma `description` descreve a regra antiga da janela, e passaria a mentir. O par

```python
        "SELECT/FROM/LIMIT). date_range default LAST_30_DAYS auto-injeta segments.date "
        "BETWEEN quando filter usa metrics.*. RECOMENDACAO: pra evitar incluir "
```

vira

```python
        "SELECT/FROM/LIMIT). date_range (default LAST_30_DAYS) entra SEMPRE como "
        "segments.date BETWEEN, exceto quando o filter ja traz segments.date: o custo "
        "do preview e o do periodo, nao o da vida da entidade. RECOMENDACAO: pra "
        "evitar incluir "
```

(o fragmento seguinte, `"entidades ja pausadas, adicione ..."`, continua a frase).

- [ ] **Step 5: As 6 chamadas de teste**

O script da Task 2, Step 9, com `NOMES = ["bulk_pause_query"]`. Expected: `TOTAL: 6`.

- [ ] **Step 6: Rode, gate, commit**

```bash
python -m pytest tests/unit/test_bulk_pause_query.py tests/unit/test_bulk_pause_tool.py tests/unit/test_bulk_pause_builder.py tests/unit/test_filters_applied_e_derivado.py -q
python scripts/check_pre_push.py > "$SCRATCH/gate.log" 2>&1; echo "EXIT=$?"
git add src/ tests/
git commit -m "fix(mcp): bulk_pause_by_query mede sempre no periodo e o preview diz qual"
```

---

### Task 6: O resumo do `add_negatives_from_search_terms` sai das mesmas contagens do envelope

**Files:**
- Modify: `src/mcp/tools/add_negatives_from_search_terms.py`
- Test: `tests/unit/test_add_negatives_from_search_terms.py`

**Interfaces:** nenhuma nova.

- [ ] **Step 1: O teste de igualdade**

Em `tests/unit/test_add_negatives_from_search_terms.py`, acrescente, reusando o cenário de `test_tool_zips_partial_failures_back_to_input` (3 linhas; a do meio `CRITERION_EXISTS`; `applied_count=2`):

```python
@pytest.mark.asyncio
async def test_o_resumo_conta_como_o_envelope():
    """F187 dentro da resposta: o texto dizia "(3 aceita(s) pelo Google)" contando a
    duplicata que o Google RECUSOU, enquanto `applied_count` dizia 2. O numero do
    texto e o do campo tem de ser o mesmo, e as tres parcelas somam o tentado."""
    from src.mcp.tools.add_negatives_from_search_terms import add_negatives_from_search_terms

    fake_partials = [
        {"index": 0, "status": "success", "error": None},
        {"index": 1, "status": "failed", "error": "CRITERION_EXISTS"},
        {"index": 2, "status": "success", "error": None},
    ]
    with patch(
        "src.mcp.tools.add_negatives_from_search_terms.run_mutation",
        AsyncMock(
            return_value={
                "provider_request_id": "req-123",
                "applied_count": 2,
                "partial_failures": fake_partials,
            }
        ),
    ):
        result = await add_negatives_from_search_terms(
            {
                "customer_id": "1234567890",
                "negatives": [
                    {"search_term": "a", "match_type": "EXACT", "scope": "campaign", "scope_id": "111"},
                    {"search_term": "b", "match_type": "EXACT", "scope": "campaign", "scope_id": "111"},
                    {"search_term": "c", "match_type": "EXACT", "scope": "ad_group", "scope_id": "222"},
                ],
            }
        )

    resumo = result["blast_summary"]
    m = re.search(
        r"(\d+) aceita\(s\) pelo Google, (\d+) ja existia\(m\), (\d+) recusada\(s\)", resumo
    )
    assert m, resumo
    aceitas, ja_existiam, recusadas = map(int, m.groups())
    assert aceitas == result["applied_count"]  # o numero do texto E o do campo
    assert (ja_existiam, recusadas) == (1, 0)
    assert aceitas + ja_existiam + recusadas == 3  # as tres parcelas somam o tentado
```

(`import re` no topo do arquivo: ele ainda não importa.)

- [ ] **Step 2: Rode e veja falhar**

Run: `python -m pytest tests/unit/test_add_negatives_from_search_terms.py -q -k conta_como_o_envelope`
Expected: FAIL — o resumo de hoje diz `(3 aceita(s) pelo Google)`.

- [ ] **Step 3: O resumo**

Troque

```python
    aplicadas = sum(1 for a in added if a["status"] != "failed")
    return applied_envelope(
        "add_negatives_from_search_terms",
        customer_id,
        f"Adicionar {target_count} negativa(s) derivada(s) do search_terms_report "
        f"({aplicadas} aceita(s) pelo Google).",
```

por

```python
    # O numero de aceitas e o proprio `applied_count` do envelope, ao lado: fonte
    # unica (F187). Antes, a conta `status != "failed"` incluia `already_exists`,
    # a duplicata que o Google RECUSOU, e o texto discordava do campo.
    ja_existiam = sum(1 for a in added if a["status"] == "already_exists")
    recusadas = sum(1 for a in added if a["status"] == "failed")
    return applied_envelope(
        "add_negatives_from_search_terms",
        customer_id,
        f"Adicionar {target_count} negativa(s) derivada(s) do search_terms_report: "
        f"{result['applied_count']} aceita(s) pelo Google, {ja_existiam} ja existia(m), "
        f"{recusadas} recusada(s).",
```

(O resto da chamada fica igual.) `add_keywords` e `add_negative_keywords` não mudam: o resumo delas só declara a intenção.

- [ ] **Step 4: Rode, gate, commit**

```bash
python -m pytest tests/unit/test_add_negatives_from_search_terms.py tests/unit/test_classify_partial_status_autoritativo.py tests/unit/test_envelope_applied_e_unico.py tests/unit/test_so_o_produtor_descreve_a_contagem_do_lote.py -q
python scripts/check_pre_push.py > "$SCRATCH/gate.log" 2>&1; echo "EXIT=$?"
git add src/ tests/
git commit -m "fix(mcp): resumo do add_negatives_from_search_terms conta como o envelope"
```

---

### Task 7: Registro — F193, índice da varredura, estado-atual

**Files:**
- Modify: `docs/operacao/findings-catalog.md` (entrada F193 no fim; no "Como ler" do topo, `IDs de **F1 a F192**` vira `**F1 a F193**`, e as linhas/KB de lá são remedidos)
- Modify: `docs/_archive/varredura-2026-09-21/README.md` (destinos)
- Modify: `docs/operacao/estado-atual.md`
- Modify: `CLAUDE.md` (dois lugares: `Catálogo até **F192**` e `**F1–F192, ~5300 linhas, 545 KB**`)

- [ ] **Step 1: A entrada F193**

Acrescente ao fim do catálogo:

```markdown
## F193 (HIGH, ✅ CORRIGIDO 2026-09-26) — respostas Google que afirmavam mais do que o recorte que mediram

**Origem:** varredura de 21/09, relatórios 01 e 02 (índice: LINK-INDICE).
Spec: LINK-SPEC; plano: LINK-PLANO.

**A classe.** A do F187 — resumo como superfície de decisão, detalhe como verdade —,
dentro da resposta das tools: filtro aplicado que a resposta não dizia; razão sem
denominador virando número; e um preview de mutação que dizia "no periodo" sobre um custo
de toda a vida. Achada pela varredura de 21/09 (relatórios 01 e 02, arquivados) e
conferida no código e por probe em 25/09.

**✅ O que foi feito:**

- As 17 funções de query dos cinco módulos (`performance`, `tactical`, `client_report`,
  `overview`, `bulk_pause`) devolvem `(gaql, filtros)` — o padrão do F191 —, e as 16 tools
  de leitura (contando o `get_performance_breakdown`) e o preview do `bulk_pause_by_query`
  ecoam `filters_applied`, com a frase na description conferida por teste.
- `razao()` é a única regra de denominador zero: 33 ocorrências em 14 arquivos viraram
  `null`; o overview ganhou `sem_dados_no_periodo`.
- O `bulk_pause_by_query` mede sempre no período (probe em duas contas: o conjunto a
  pausar não muda).
- A auditoria de negativas declara o nível (`campanha`) em vez de "conta inteira".
- O resumo do `add_negatives_from_search_terms` conta como o envelope.

**Guards:** completude derivada do `WHERE` (parser que exige reconhecer toda condição — o
do F191 não via `>=` nem `DURING`), eco comportamental por tool, desempacotamento nas
chamadas de teste (31 asserts `not in` teriam virado verde vazio), razão indefinida (AST) e
igualdade no resumo — com as populações por varredura (funções pela anotação de retorno,
tools pelo import), não por lista. Cada um visto vermelho contra o código anterior.

**Deliberadamente fora:** negativas de grupo e listas compartilhadas (frente própria); o
ramo `campaign`+`hourly` do breakdown (`day_hour_metrics_query`, em `ad_schedule.py`);
`get_assets`, `run_gaql` e `audit_competitor_keywords` (já declaram o corte por
`truncated`); `country_name: null` (já é o terceiro estado); modelo de freshness para
métricas; as métricas Meta (próxima frente).

**Contrato que mudou:** 13 tools de leitura passaram de número para `null` nas razões sem
denominador (e o `delta_pct` do preview do `update_campaign_budget`, explicado no texto).
Consumidor externo, medido em 26/09 no plugin `v4-trafego-google-ads`: uma referência exata
aos campos, que só os lista; e `relatorio-cliente-google-ads/SKILL.md:33`, que ordena anúncios
por CTR — com `ctr: null`, a linha sai do ranking em vez de virar 0. O plugin é outro
repositório: o ajuste é de lá.
```

Os três `LINK-*` viram links markdown relativos a `docs/operacao/`, onde a entrada mora — aqui no plano eles quebrariam o `test_docs_links.py`, que resolve a partir do arquivo que os contém:

| marcador | texto do link | destino |
|---|---|---|
| `LINK-INDICE` | `índice` | `../_archive/varredura-2026-09-21/README.md` |
| `LINK-SPEC` | `` `2026-09-25-respostas-google-dizem-o-recorte-design.md` `` | `../superpowers/specs/2026-09-25-respostas-google-dizem-o-recorte-design.md` |
| `LINK-PLANO` | `` `2026-09-26-respostas-google-dizem-o-recorte.md` `` | `../superpowers/plans/2026-09-26-respostas-google-dizem-o-recorte.md` |

O mesmo guard confere os três no catálogo, no gate da Task 7.

(Se o Step 8 da Task 1 medir outra coisa, o parágrafo acima segue o medido. A data do cabeçalho é a do commit: se a execução cair noutro dia, use a do dia.)

No "Como ler" do topo do catálogo, `IDs de **F1 a F192**` vira `**F1 a F193**`; remeça linhas e KB (`wc -l`, `wc -c`) e atualize os dois números lá e no `CLAUDE.md`.

- [ ] **Step 2: Índice da varredura — cada item com o desfecho real**

Em `docs/_archive/varredura-2026-09-21/README.md`, os destinos *respostas Google* ganham o desfecho que de fato houve: **fechado** só onde o F193 mudou código; **descartado** onde o spec (§7) julgou que a resposta já declara o corte. Marcar "fechado" num item que nenhum código tocou seria afirmar um conserto que não houve — o defeito que esta frente fecha.

| relatório · item | destino novo |
|---|---|
| 01 · 2, 3, 5, 6, 9 | `fechado — F193` |
| 01 · 7 (`get_budget_pacing`) | `fechado — F193 (eco; parâmetro de status não entrou)` |
| 01 · 11 (`country_name: null`) | `descartado no F193 — null já é o terceiro estado honesto` |
| 02 · 2, 4 | `fechado — F193` |
| 02 · 3, 6, 7 (`get_assets`, `run_gaql`, `audit_competitor_keywords`) | `descartado no F193 — já declarado por truncated/returned/orphan_scope` |

Na tabela da decomposição, a linha 2 (*respostas que afirmam mais do que mediram*) passa a dizer: `núcleo fechado no F191; eco de status fechado no F193; get_assets descartado no F193 (já declarado)`. Não mudam: 01 · 4 (*métricas Meta*) e 01 · 12 (freshness, fora da fila).

- [ ] **Step 3: `estado-atual.md` e `CLAUDE.md`**

Em `docs/operacao/estado-atual.md`:

- tabela de produção: `| Catálogo | até **F192** (~5.300 linhas, 545 KB) |` vira `até **F193**`, com linhas e KB remedidos;
- tabela dos sub-projetos: `| 2 · respostas que afirmam mais do que mediram | **em parte** — núcleo no **F191**; o resto é a frente *respostas Google* |` vira `| 2 · respostas que afirmam mais do que mediram | **fechado** — núcleo no **F191**, o resto no **F193** |`;
- "Ordem de ataque (25/09)": sai o item `3. **Respostas Google** (spec) — …`, e a numeração se refaz;
- em "Os abertos, um por linha", duas linhas novas: *negativas de grupo e listas compartilhadas na auditoria de negativas* (spec §7: frente própria) e, fora deste repo, *o skill `relatorio-cliente-google-ads` do plugin ordena anúncios por CTR (`SKILL.md:33`): com `ctr: null`, a linha tem de sair do ranking*.

No `CLAUDE.md`, os dois lugares: `Catálogo até **F192**` vira `**F193**`, e `**F1–F192, ~5300 linhas, 545 KB**` vira `**F1–F193, …**` com os números remedidos do catálogo. O teto de 24 KB do `CLAUDE.md` tem guard no gate.

- [ ] **Step 4: Gate e commit**

```bash
python scripts/check_pre_push.py > "$SCRATCH/gate.log" 2>&1; echo "EXIT=$?"
git add docs/ CLAUDE.md
git commit -m "docs(operacao): F193 — respostas Google dizem o recorte que mediram"
```

---

## Autorrevisão contra a lição "planos precisam rodar"

| a forma do defeito de plano | onde este plano responde |
|---|---|
| contagem escrita à mão | toda contagem do inventário veio de scan com controle; cada task confere a sua previsão (26, 7, 17, 6, e os 33) antes de seguir |
| enumerar chamadores numa mudança de dado | consumidores do contrato número → `null` achados por varredura dos nomes de campo, não dos nomes de função |
| código de plano que não roda | em 26/09 o código **deste** plano rodou contra o repo, sem tocá-lo (`plano_roda.py`, no scratchpad): 44 dos 60 blocos fazem parse sozinhos, e os 16 restantes são trechos de troca de linha; as 16 funções de query do plano geram GAQL **idêntico** ao de hoje, e o `bulk_pause` só ganha a janela no filtro de entidade; cada corte do `WHERE` está no `filtros` pelo parser e pelo mapa do plano; o breakdown repassa a tupla; as populações dão 17 funções e 17 tools; o detector de razão mede 33 em 14; o controle do desempacotamento deu `[1, 2, 3]`, e as contagens 26/7/17/6 bateram |
| afirmação falsa no texto do plano | o "PR 3 não feito" desta sessão ensinou: toda ausência afirmada aqui foi medida (ex.: "não é consumidor" do `test_get_keyword_performance.py`, conferido pelo mock) |
| ordem e acoplamento entre tasks | tabela acima; o acoplamento de tipo do breakdown mudou o recorte da Task 2 |
| regra sem mecanismo | as duas frases de description, as funções do guard derivado e as tools do eco têm teste que as acha por varredura; nada depende de alguém lembrar |
| regra uniforme sobre conjunto com teto próprio | `conversion_actions` ecoa `{}`; o `bulk_pause` não injeta janela quando o filtro já tem uma |
