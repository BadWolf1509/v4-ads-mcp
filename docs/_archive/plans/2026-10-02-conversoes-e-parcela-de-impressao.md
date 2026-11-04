# Conversões por ação e parcela de impressão — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cobrir com tools curadas as duas lacunas que o uso real mede — conversões por ação de conversão e parcela de impressão — sem tool nova.

**Architecture:** A parcela de impressão entra nas linhas de `level='campaign'` do `get_performance_breakdown` (mesma query) e no `get_account_overview` (os três campos que `customer` aceita), lida pela presença do campo no proto (`metrica_opcional`): ausente vira `null`, nunca o `0.0` da leitura direta. O recorte por ação é `breakdown='conversion_action'` nos níveis conta e campanha, com construtores novos em `queries/performance.py` e uma segunda consulta ao `conversion_action` para as flags de cada ação — ação fora do cadastro fica com flag `null` e motivo.

**Tech Stack:** Python 3.13, google-ads v24 (proto-plus), GAQL, pytest.

**Spec:** `docs/superpowers/specs/2026-10-02-conversoes-e-parcela-de-impressao-design.md`

**Como este plano foi feito (método de 26/09):** o código de cada task foi escrito e executado ANTES, uma task por commit no worktree `D:/v4-ads-mcp-wt/conversoes` (branch `spec/conversoes-e-parcela`), cada commit com o gate rápido verde e as sabotagens medidas; os blocos abaixo são o `git show`/`git diff` exato desses commits, e o "Expected" de cada ver-falhar foi medido reaplicando este arquivo. As cinco consultas foram validadas contra a API na Mestre da Obra – João Pessoa (`7862230676`) em 02/10.

## Global Constraints

- Nenhuma tool nova: o catálogo segue com 68 tools e os buckets não mudam.
- Campo `optional` do proto lido por presença (`campo in m`); ausente vira `None`, nunca `0` (spec §3.2).
- Recorte por ação sem custo nem CPA: a API recusa custo nesse recorte (spec §2, fato 1).
- Flag de ação que o `conversion_action` não devolve: `null` com `flags_motivo`, nunca `false` (F191; spec §3.1).
- Id em `IN` sempre por `int()` (F163); lista com teto estrutural e `ValueError` fora dele.
- Toda query com corte devolve `(gaql, filtros)`, e o eco vem do WHERE (o guard `test_filters_applied_e_derivado.py` enxerga toda função pública de `queries/performance.py`).
- Gate de cada task: `D:/v4-ads-mcp/.venv/Scripts/python.exe scripts/check_pre_push.py` — o Python global teve o `mypy` compilado bloqueado pelo Controle de Aplicativos do Windows em 30/09; o do `.venv` roda os mesmos passos. Commit encadeado ao gate por `&&`, nunca `;`.

## Mapa de arquivos

| arquivo | task | responsabilidade |
|---|---|---|
| `src/google_ads/queries/_common.py` | 1 | `metrica_opcional(m, campo)` — presença no proto, ou atributo em objeto falso |
| `src/google_ads/queries/performance.py` | 1, 3 | a parcela na query de campanha; `conversion_action_breakdown_query`, `conversion_action_flags_query` |
| `src/google_ads/performance_breakdown.py` | 1, 3 | parse da parcela na campanha; combinação, despacho e parse do recorte por ação |
| `src/google_ads/queries/overview.py` | 2 | os três campos de parcela da conta |
| `src/mcp/tools/get_account_overview.py` | 2 | a parcela no formatador e no agregado (linha única) e na description |
| `src/mcp/tools/get_performance_breakdown.py` | 4 | schema, a consulta das flags depois do corte, a junção e a description |

---

### Task 1: parcela de impressão nas linhas de `level='campaign'`

**Files:**
- Create: `tests/unit/test_parcela_de_impressao.py`
- Modify: `src/google_ads/queries/_common.py`, `src/google_ads/queries/performance.py`, `src/google_ads/performance_breakdown.py`

**Interfaces:**
- Produces: `metrica_opcional(m: Any, campo: str) -> float | None` em `src/google_ads/queries/_common.py` (usada nas tasks 2 e 3); as linhas de campanha ganham `parcela_impressao`, `perdida_orcamento`, `perdida_classificacao`, `parcela_topo`, `parcela_topo_absoluto`.

- [ ] **Step 1: Write the failing test**

Crie `tests/unit/test_parcela_de_impressao.py`, conteúdo exato:

```python
"""Parcela de impressão nas linhas de `level='campaign'` (spec 2026-10-02, §3.2).

Os cinco campos `search_*impression_share` são `optional` no proto (v24). Medido em 02/10
na Hosp Ocular: campanha SMART/LOCAL/VIDEO e campanha de pesquisa sem impressão vêm SEM o
campo (o `impressions` delas vem presente, `0`); a de pesquisa com impressão vem com ele —
inclusive `0.0999`, o "< 10%" do Google. Ler o atributo direto devolve `0.0` para o campo
ausente: o zero falso que a spec proíbe. A regra é presença no proto.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from google.ads.googleads.v24.common.types.metrics import Metrics

from src.google_ads.performance_breakdown import parse_performance_row
from src.google_ads.queries._common import metrica_opcional
from src.google_ads.queries.performance import campaign_performance_query

_CAMPOS = (
    "search_impression_share",
    "search_budget_lost_impression_share",
    "search_rank_lost_impression_share",
    "search_top_impression_share",
    "search_absolute_top_impression_share",
)


def _linha(metrics: Metrics) -> SimpleNamespace:
    return SimpleNamespace(
        campaign=SimpleNamespace(
            id=1,
            name="c",
            status=SimpleNamespace(name="ENABLED"),
            advertising_channel_type=SimpleNamespace(name="SEARCH"),
        ),
        metrics=metrics,
    )


def test_campo_ausente_no_proto_vira_none_e_nao_zero() -> None:
    vazio = Metrics(impressions=0)
    assert vazio.search_impression_share == 0.0  # o zero falso que a leitura direta daria
    assert metrica_opcional(vazio, "search_impression_share") is None


def test_campo_presente_devolve_o_valor_inclusive_zero_e_o_menor_que_10() -> None:
    assert (
        metrica_opcional(Metrics(search_impression_share=0.42), "search_impression_share") == 0.42
    )
    assert metrica_opcional(Metrics(search_impression_share=0.0), "search_impression_share") == 0.0
    assert (
        metrica_opcional(Metrics(search_top_impression_share=0.0999), "search_top_impression_share")
        == 0.0999
    )


def test_objeto_falso_sem_o_atributo_vira_none() -> None:
    """Os testes do modulo usam SimpleNamespace, onde `in` nao funciona."""
    assert metrica_opcional(SimpleNamespace(), "search_impression_share") is None
    assert (
        metrica_opcional(SimpleNamespace(search_impression_share=0.3), "search_impression_share")
        == 0.3
    )


def test_linha_de_campanha_traz_a_parcela_de_impressao() -> None:
    cheia = Metrics(
        impressions=100,
        search_impression_share=0.5517,
        search_budget_lost_impression_share=0.229,
        search_rank_lost_impression_share=0.2193,
        search_top_impression_share=0.4402,
        search_absolute_top_impression_share=0.3193,
    )
    r = parse_performance_row(_linha(cheia), "campaign", None)
    assert r["parcela_impressao"] == 0.5517
    assert r["perdida_orcamento"] == 0.229
    assert r["perdida_classificacao"] == 0.2193
    assert r["parcela_topo"] == 0.4402
    assert r["parcela_topo_absoluto"] == 0.3193


def test_campanha_sem_o_campo_traz_none_nos_cinco() -> None:
    r = parse_performance_row(_linha(Metrics(impressions=0)), "campaign", None)
    for chave in (
        "parcela_impressao",
        "perdida_orcamento",
        "perdida_classificacao",
        "parcela_topo",
        "parcela_topo_absoluto",
    ):
        assert r[chave] is None, chave


def test_query_de_campanha_pede_os_cinco_campos() -> None:
    gaql, _ = campaign_performance_query(date(2026, 9, 1), date(2026, 9, 30), "enabled", 10)
    for campo in _CAMPOS:
        assert f"metrics.{campo}" in gaql, campo
```

- [ ] **Step 2: Run test to verify it fails**

Run: `D:/v4-ads-mcp/.venv/Scripts/python.exe -m pytest tests/unit/test_parcela_de_impressao.py -p no:cacheprovider -q`
Expected (medido): !!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!! | E ImportError: cannot import name 'metrica_opcional' from 'src.google_ads.queries._common' (D:\v4-ads-mcp-wt\conv-reaplica\src\google_ads\queries\_common.py)

- [ ] **Step 3: Write minimal implementation**

`src/google_ads/queries/_common.py`:

```diff
diff --git a/src/google_ads/queries/_common.py b/src/google_ads/queries/_common.py
index 6689302..24efa7f 100644
--- a/src/google_ads/queries/_common.py
+++ b/src/google_ads/queries/_common.py
@@ -207,6 +207,21 @@ def arredondado(valor: float | None, casas: int) -> float | None:
     return None if valor is None else round(valor, casas)
 
 
+def metrica_opcional(m: Any, campo: str) -> float | None:
+    """Metrica `optional` do proto: o valor quando o Google a mandou, `None` quando nao.
+
+    Os `search_*impression_share` sao `optional` (v24): campanha que nao e de pesquisa, ou
+    de pesquisa sem impressao, vem SEM o campo — e ler o atributo direto devolve `0.0`, o
+    zero falso (medido em 02/10, spec 2026-10-02 §3.2). Presenca no proto-plus e `campo in
+    m`; os testes do modulo usam `SimpleNamespace`, onde `in` nao funciona e vale o atributo.
+    """
+    try:
+        presente = campo in m
+    except TypeError:
+        presente = hasattr(m, campo)
+    return float(getattr(m, campo)) if presente else None
+
+
 def em_moeda(valor_micros: float | None) -> float | None:
     """`micros_to_currency` que deixa `None` passar."""
     return None if valor_micros is None else micros_to_currency(valor_micros)
```

`src/google_ads/queries/performance.py`:

```diff
diff --git a/src/google_ads/queries/performance.py b/src/google_ads/queries/performance.py
index fadf16c..db44ec5 100644
--- a/src/google_ads/queries/performance.py
+++ b/src/google_ads/queries/performance.py
@@ -24,7 +24,12 @@ def campaign_performance_query(
           campaign.id, campaign.name, campaign.status,
           campaign.advertising_channel_type,
           metrics.impressions, metrics.clicks, metrics.cost_micros,
-          metrics.conversions, metrics.conversions_value
+          metrics.conversions, metrics.conversions_value,
+          metrics.search_impression_share,
+          metrics.search_budget_lost_impression_share,
+          metrics.search_rank_lost_impression_share,
+          metrics.search_top_impression_share,
+          metrics.search_absolute_top_impression_share
         FROM campaign
         WHERE {gaql_date_clause(start, end)} {status_clause}
         ORDER BY metrics.cost_micros DESC
```

`src/google_ads/performance_breakdown.py`:

```diff
diff --git a/src/google_ads/performance_breakdown.py b/src/google_ads/performance_breakdown.py
index b4c82e0..19a0630 100644
--- a/src/google_ads/performance_breakdown.py
+++ b/src/google_ads/performance_breakdown.py
@@ -8,7 +8,13 @@ SimpleNamespace). Espelha src/meta_ads/insights.py (M.4).
 from datetime import date
 from typing import Any
 
-from src.google_ads.queries._common import arredondado, em_moeda, micros_to_currency, razao
+from src.google_ads.queries._common import (
+    arredondado,
+    em_moeda,
+    metrica_opcional,
+    micros_to_currency,
+    razao,
+)
 from src.google_ads.queries.performance import (
     ad_group_performance_query,
     campaign_performance_query,
@@ -68,6 +74,21 @@ def _common_metrics(m: Any) -> dict[str, Any]:
     }
 
 
+def _parcela_de_impressao(m: Any) -> dict[str, float | None]:
+    """Os cinco campos de parcela de impressao da campanha (spec 2026-10-02, §3.2).
+
+    Campo ausente no proto (campanha que nao e de pesquisa, ou sem impressao) vira `None`,
+    nunca `0`. O Google informa "< 10%" como 0,0999, e o valor vai como veio.
+    """
+    return {
+        "parcela_impressao": metrica_opcional(m, "search_impression_share"),
+        "perdida_orcamento": metrica_opcional(m, "search_budget_lost_impression_share"),
+        "perdida_classificacao": metrica_opcional(m, "search_rank_lost_impression_share"),
+        "parcela_topo": metrica_opcional(m, "search_top_impression_share"),
+        "parcela_topo_absoluto": metrica_opcional(m, "search_absolute_top_impression_share"),
+    }
+
+
 def build_performance_breakdown_query(
     level: str, breakdown: str | None, status: str, start: date, end: date, limit: int
 ) -> tuple[str, dict[str, Any]]:
@@ -139,6 +160,7 @@ def parse_performance_row(row: Any, level: str, breakdown: str | None) -> dict[s
             "status": row.campaign.status.name,
             "type": row.campaign.advertising_channel_type.name,
             **base,
+            **_parcela_de_impressao(row.metrics),
         }
     if level == "ad_group":
         return {
```

- [ ] **Step 4: Run the gate**

Run: `D:/v4-ads-mcp/.venv/Scripts/python.exe scripts/check_pre_push.py`
Expected: `All pre-push checks passed (6 steps ...)`. Sabotagem medida: trocar o corpo de `metrica_opcional` por `return float(getattr(m, campo, 0.0))` derruba 3 dos 6 testes (o campo ausente, o objeto falso sem atributo, a campanha sem o campo).

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(mcp): parcela de impressao nas linhas de level=campaign do breakdown"
```

---

### Task 2: parcela de impressão da conta no `get_account_overview`

**Files:**
- Create: `tests/unit/test_overview_parcela_de_impressao.py`
- Modify: `src/google_ads/queries/overview.py`, `src/mcp/tools/get_account_overview.py`, `tests/unit/test_account_overview.py`, `tests/unit/test_razao_indefinida.py`, `tests/integration/test_overview_tools.py`

**Interfaces:**
- Consumes: `metrica_opcional` (Task 1).
- Produces: `current` e `previous` do overview com `parcela_impressao`, `perdida_orcamento`, `perdida_classificacao`.

- [ ] **Step 1: Write the failing test**

Crie `tests/unit/test_overview_parcela_de_impressao.py`, conteúdo exato:

```python
"""Parcela de impressão no `get_account_overview` (spec 2026-10-02, §3.2).

Em `FROM customer` só três campos existem (medido em 02/10: topo e topo absoluto são
recusados pela API nesse recurso). A parcela não soma: ela vem de uma linha só (`customer`
sem segmento devolve uma), e com mais de uma linha — ou nenhuma — o valor é `None`.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from google.ads.googleads.v24.common.types.metrics import Metrics

from src.google_ads.queries.overview import overview_query
from src.mcp.tools.get_account_overview import _aggregate, _row_formatter


def _row(**metricas: float) -> SimpleNamespace:
    return SimpleNamespace(
        metrics=Metrics(impressions=10, clicks=1, cost_micros=1_000_000, **metricas)
    )


def test_query_pede_os_tres_campos_da_conta_e_nao_os_de_topo() -> None:
    gaql, _ = overview_query(date(2026, 9, 1), date(2026, 9, 30))
    assert "metrics.search_impression_share" in gaql
    assert "metrics.search_budget_lost_impression_share" in gaql
    assert "metrics.search_rank_lost_impression_share" in gaql
    assert "search_top_impression_share" not in gaql
    assert "search_absolute_top_impression_share" not in gaql


def test_linha_com_os_campos_chega_ao_agregado() -> None:
    linha = _row(
        search_impression_share=0.5468,
        search_budget_lost_impression_share=0.2339,
        search_rank_lost_impression_share=0.2194,
    )
    agg = _aggregate([_row_formatter(linha)])
    assert agg["parcela_impressao"] == 0.5468
    assert agg["perdida_orcamento"] == 0.2339
    assert agg["perdida_classificacao"] == 0.2194


def test_campo_ausente_vira_none() -> None:
    agg = _aggregate([_row_formatter(_row())])
    assert agg["parcela_impressao"] is None
    assert agg["perdida_orcamento"] is None
    assert agg["perdida_classificacao"] is None


def test_periodo_sem_linha_traz_none() -> None:
    agg = _aggregate([])
    assert agg["parcela_impressao"] is None


def test_mais_de_uma_linha_nao_soma_parcela() -> None:
    a = _row_formatter(_row(search_impression_share=0.5))
    b = _row_formatter(_row(search_impression_share=0.3))
    agg = _aggregate([a, b])
    assert agg["parcela_impressao"] is None
    assert agg["impressions"] == 20  # as contagens seguem somando
```

As fixtures que montam linhas já formatadas do overview ganham as três chaves que o formatador passa a produzir sempre:

```diff
diff --git a/tests/unit/test_account_overview.py b/tests/unit/test_account_overview.py
index 14a4104..92484a1 100644
--- a/tests/unit/test_account_overview.py
+++ b/tests/unit/test_account_overview.py
@@ -35,6 +35,9 @@ async def test_overview_includes_tracking_warning_on_1_to_1():
             "cost_micros": 1_935_680_000,
             "conversions": 93.0,
             "conversions_value": 93.0,  # 1:1 placeholder
+            "parcela_impressao": None,
+            "perdida_orcamento": None,
+            "perdida_classificacao": None,
         }
     ]
     fake_rows_prev = [
@@ -44,6 +47,9 @@ async def test_overview_includes_tracking_warning_on_1_to_1():
             "cost_micros": 1_435_570_000,
             "conversions": 727.49,
             "conversions_value": 727.49,  # also 1:1
+            "parcela_impressao": None,
+            "perdida_orcamento": None,
+            "perdida_classificacao": None,
         }
     ]
 
@@ -75,6 +81,9 @@ async def test_overview_omits_tracking_warning_on_real_tracking():
             "cost_micros": 500_000_000,
             "conversions": 10.0,
             "conversions_value": 2500.0,  # real revenue tracking
+            "parcela_impressao": None,
+            "perdida_orcamento": None,
+            "perdida_classificacao": None,
         }
     ]
     fake_rows_prev = [
@@ -84,6 +93,9 @@ async def test_overview_omits_tracking_warning_on_real_tracking():
             "cost_micros": 400_000_000,
             "conversions": 8.0,
             "conversions_value": 2000.0,
+            "parcela_impressao": None,
+            "perdida_orcamento": None,
+            "perdida_classificacao": None,
         }
     ]
 
```

```diff
diff --git a/tests/unit/test_razao_indefinida.py b/tests/unit/test_razao_indefinida.py
index bec3e7e..43d9416 100644
--- a/tests/unit/test_razao_indefinida.py
+++ b/tests/unit/test_razao_indefinida.py
@@ -146,6 +146,9 @@ def test_overview_com_gasto_e_zero_conversao_nao_tem_cpa() -> None:
                 "cost_micros": 5_000_000,
                 "conversions": 0.0,
                 "conversions_value": 0.0,
+                "parcela_impressao": None,
+                "perdida_orcamento": None,
+                "perdida_classificacao": None,
             }
         ]
     )
@@ -173,6 +176,9 @@ def test_overview_com_custo_abaixo_de_meio_centavo_nao_quebra_o_roas() -> None:
                 "cost_micros": 3_000,
                 "conversions": 1.0,
                 "conversions_value": 50.0,
+                "parcela_impressao": None,
+                "perdida_orcamento": None,
+                "perdida_classificacao": None,
             }
         ]
     )
```

```diff
diff --git a/tests/integration/test_overview_tools.py b/tests/integration/test_overview_tools.py
index f7d583a..ae8fc39 100644
--- a/tests/integration/test_overview_tools.py
+++ b/tests/integration/test_overview_tools.py
@@ -35,6 +35,9 @@ async def test_account_overview_aggregates_and_compares(bound_context):
                 "cost_micros": 100_000_000,
                 "conversions": 5.0,
                 "conversions_value": 500.0,
+                "parcela_impressao": None,
+                "perdida_orcamento": None,
+                "perdida_classificacao": None,
             },
             {
                 "impressions": 2000,
@@ -42,6 +45,9 @@ async def test_account_overview_aggregates_and_compares(bound_context):
                 "cost_micros": 200_000_000,
                 "conversions": 10.0,
                 "conversions_value": 1000.0,
+                "parcela_impressao": None,
+                "perdida_orcamento": None,
+                "perdida_classificacao": None,
             },
         ],
         # previous period rows
@@ -52,6 +58,9 @@ async def test_account_overview_aggregates_and_compares(bound_context):
                 "cost_micros": 150_000_000,
                 "conversions": 7.0,
                 "conversions_value": 700.0,
+                "parcela_impressao": None,
+                "perdida_orcamento": None,
+                "perdida_classificacao": None,
             },
         ],
     ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `D:/v4-ads-mcp/.venv/Scripts/python.exe -m pytest tests/unit/test_overview_parcela_de_impressao.py -p no:cacheprovider -q`
Expected (medido): (sem linha de resumo) | E KeyError: 'parcela_impressao'

- [ ] **Step 3: Write minimal implementation**

`src/google_ads/queries/overview.py`:

```diff
diff --git a/src/google_ads/queries/overview.py b/src/google_ads/queries/overview.py
index 028678f..c63c263 100644
--- a/src/google_ads/queries/overview.py
+++ b/src/google_ads/queries/overview.py
@@ -11,6 +11,9 @@ def overview_query(date_start: date, date_end: date) -> tuple[str, dict[str, Any
 
     Nao filtra status: a docstring antiga dizia "across all enabled campaigns",
     e a query nunca teve esse corte.
+
+    Parcela de impressao: so os tres campos que `customer` aceita — topo e topo absoluto
+    sao recusados pela API neste recurso (medido em 02/10, spec 2026-10-02 §2).
     """
     gaql = f"""
         SELECT
@@ -21,7 +24,10 @@ def overview_query(date_start: date, date_end: date) -> tuple[str, dict[str, Any
           metrics.conversions_value,
           metrics.ctr,
           metrics.average_cpc,
-          metrics.cost_per_conversion
+          metrics.cost_per_conversion,
+          metrics.search_impression_share,
+          metrics.search_budget_lost_impression_share,
+          metrics.search_rank_lost_impression_share
         FROM customer
         WHERE {gaql_date_clause(date_start, date_end)}
     """.strip()
```

`src/mcp/tools/get_account_overview.py`:

```diff
diff --git a/src/mcp/tools/get_account_overview.py b/src/mcp/tools/get_account_overview.py
index ba1c247..c76c2da 100644
--- a/src/mcp/tools/get_account_overview.py
+++ b/src/mcp/tools/get_account_overview.py
@@ -8,6 +8,7 @@ from src.google_ads.queries._common import (
     arredondado,
     em_moeda,
     get_comparison_range,
+    metrica_opcional,
     micros_to_currency,
     razao,
     resolve_date_window,
@@ -66,6 +67,20 @@ _SCHEMA: dict[str, Any] = {
 }
 
 
+# Parcela de impressao na conta: os tres campos que `customer` aceita (spec 2026-10-02 §3.2).
+_PARCELA = ("parcela_impressao", "perdida_orcamento", "perdida_classificacao")
+
+
+def _parcela(rows: list[dict[str, Any]]) -> dict[str, float | None]:
+    """Parcela nao soma: vale a linha unica que `customer` sem segmento devolve.
+
+    Sem linha, ou com mais de uma, nao ha um valor a afirmar — `None`.
+    """
+    if len(rows) != 1:
+        return dict.fromkeys(_PARCELA)
+    return {k: rows[0][k] for k in _PARCELA}
+
+
 def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
     """Sum the per-day rows into single totals + computed ratios.
 
@@ -85,6 +100,7 @@ def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
             "average_cpc_brl": None,
             "cost_per_conversion_brl": None,
             "roas": None,
+            **_parcela(rows),
             "sem_dados_no_periodo": True,
         }
     impr = sum(r["impressions"] for r in rows)
@@ -104,6 +120,7 @@ def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
         # O guarda antigo era `if cost` (micros) e dividia por `micros_to_currency(cost)`:
         # custo abaixo de meio centavo arredonda para 0.0 e dava ZeroDivisionError.
         "roas": arredondado(razao(conv_val, micros_to_currency(cost)), 2),
+        **_parcela(rows),
         "sem_dados_no_periodo": False,
     }
     # UX-1: detect tracking placeholder (conversions_value == conversions exact 1:1)
@@ -121,6 +138,9 @@ def _row_formatter(row: Any) -> dict[str, Any]:
         "cost_micros": int(m.cost_micros),
         "conversions": float(m.conversions),
         "conversions_value": float(m.conversions_value),
+        "parcela_impressao": metrica_opcional(m, "search_impression_share"),
+        "perdida_orcamento": metrica_opcional(m, "search_budget_lost_impression_share"),
+        "perdida_classificacao": metrica_opcional(m, "search_rank_lost_impression_share"),
     }
 
 
@@ -129,7 +149,12 @@ def _row_formatter(row: Any) -> dict[str, Any]:
     description=(
         "[DEFER] KPIs consolidados de uma conta Google Ads (impressoes, clicks, custo, "
         "conversoes, valor, CTR, CPC, CPA, ROAS) para um periodo, com comparativo "
-        "do periodo imediatamente anterior de mesma duracao."
+        "do periodo imediatamente anterior de mesma duracao. Parcela de impressao de "
+        "pesquisa da conta (fracao 0-1): `parcela_impressao`, `perdida_orcamento`, "
+        "`perdida_classificacao` — null quando o Google nao a mede (conta sem pesquisa, "
+        "periodo sem impressao); 0.0999 e o '< 10%' do Google. Topo e topo absoluto nao "
+        "existem no nivel da conta: estao nas linhas de get_performance_breakdown("
+        "level='campaign')."
         " Razao com denominador zero vem null (indefinida), nao 0."
         " filters_applied diz o recorte que a query aplicou."
     ),
```

- [ ] **Step 4: Run the gate**

Run: `D:/v4-ads-mcp/.venv/Scripts/python.exe scripts/check_pre_push.py`
Expected: `All pre-push checks passed (6 steps ...)`.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(mcp): parcela de impressao da conta no get_account_overview"
```

---

### Task 3: consultas e parse do recorte por ação de conversão

**Files:**
- Create: `tests/unit/test_conversao_por_acao.py`
- Modify: `src/google_ads/queries/performance.py`, `src/google_ads/performance_breakdown.py`, `tests/unit/test_filters_applied_e_derivado.py`

**Interfaces:**
- Produces: `conversion_action_breakdown_query(level, start, end, status, limit) -> tuple[str, dict]` e `conversion_action_flags_query(ids: list[str]) -> tuple[str, dict]` em `src/google_ads/queries/performance.py`; `parse_performance_row(row, level, "conversion_action")` devolve `conversion_action_id`, `conversion_action_name`, `categoria`, `conversions`, `all_conversions`, `conversions_value_brl`, `all_conversions_value_brl` (+ `campaign_id`, `campaign_name` em `campaign`). A Task 4 consome os dois construtores e o formato da linha.

- [ ] **Step 1: Write the failing test**

Crie `tests/unit/test_conversao_por_acao.py`, conteúdo exato:

```python
"""Recorte por ação de conversão — consultas, parse e combinações (spec 2026-10-02, §3.1).

Fatos medidos em 02/10 (Mestre da Obra – João Pessoa): recortar por ação recusa métrica de
custo (sem CPA por ação); `conversions` por ação segue `include_in_conversions_metric`.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from src.google_ads.performance_breakdown import (
    _validate_combo,
    build_performance_breakdown_query,
    parse_performance_row,
)
from src.google_ads.queries.performance import (
    conversion_action_breakdown_query,
    conversion_action_flags_query,
)

_S, _E = date(2026, 9, 1), date(2026, 9, 30)


def test_conta_por_acao_sem_custo_ordenada_e_com_sentinela() -> None:
    gaql, filtros = conversion_action_breakdown_query("account", _S, _E, "enabled", 50)
    assert "FROM customer" in gaql
    for campo in (
        "segments.conversion_action",
        "segments.conversion_action_name",
        "segments.conversion_action_category",
        "metrics.conversions",
        "metrics.all_conversions",
        "metrics.conversions_value",
        "metrics.all_conversions_value",
    ):
        assert campo in gaql, campo
    assert "cost_micros" not in gaql  # a API recusa custo neste recorte
    assert "ORDER BY metrics.all_conversions DESC" in gaql
    assert "LIMIT 51" in gaql
    assert "campaign.status" not in gaql  # conta nao tem status de campanha
    assert filtros == {"date_range": {"start": "2026-09-01", "end": "2026-09-30"}}


def test_campanha_por_acao_traz_a_campanha_e_o_filtro_de_status() -> None:
    gaql, filtros = conversion_action_breakdown_query("campaign", _S, _E, "enabled", 10)
    assert "FROM campaign" in gaql
    assert "campaign.id" in gaql and "campaign.name" in gaql
    assert "campaign.status = 'ENABLED'" in gaql
    assert filtros["campaign_status"] == "ENABLED"
    gaql_all, filtros_all = conversion_action_breakdown_query("campaign", _S, _E, "all", 10)
    assert "campaign.status" not in gaql_all.split("WHERE")[1]
    assert "campaign_status" not in filtros_all


def test_recorte_por_acao_so_em_conta_e_campanha() -> None:
    with pytest.raises(ValueError):
        gaql, _ = conversion_action_breakdown_query("ad_group", _S, _E, "enabled", 10)


def test_flags_por_id_inteiro_com_teto_estrutural() -> None:
    gaql, filtros = conversion_action_flags_query(["6827189000", "6826176642"])
    assert "FROM conversion_action" in gaql
    assert "conversion_action.id IN (6827189000, 6826176642)" in gaql
    for campo in ("include_in_conversions_metric", "primary_for_goal", "status", "type"):
        assert f"conversion_action.{campo}" in gaql
    assert "LIMIT 1000" in gaql
    assert filtros == {"conversion_action_ids": ["6827189000", "6826176642"]}


@pytest.mark.parametrize("ids", [[], ["12", "3 OR 1=1"], [str(i) for i in range(1001)]])
def test_flags_recusa_lista_vazia_id_nao_numerico_ou_acima_do_teto(ids: list[str]) -> None:
    with pytest.raises(ValueError):
        gaql, _ = conversion_action_flags_query(ids)


def _linha(campanha: bool = False) -> SimpleNamespace:
    base = SimpleNamespace(
        segments=SimpleNamespace(
            conversion_action="customers/7862230676/conversionActions/6827189000",
            conversion_action_name="Whatsapp - JPA",
            conversion_action_category=SimpleNamespace(name="CONTACT"),
        ),
        metrics=SimpleNamespace(
            conversions=204.0,
            all_conversions=204.0,
            conversions_value=204.0,
            all_conversions_value=204.0,
        ),
    )
    if campanha:
        base.campaign = SimpleNamespace(id=21359547724, name="[GPC][JPA]")
    return base


def test_linha_por_acao_tem_formato_proprio_sem_custo() -> None:
    r = parse_performance_row(_linha(), "account", "conversion_action")
    assert r == {
        "conversion_action_id": "6827189000",
        "conversion_action_name": "Whatsapp - JPA",
        "categoria": "CONTACT",
        "conversions": 204.0,
        "all_conversions": 204.0,
        "conversions_value_brl": 204.0,
        "all_conversions_value_brl": 204.0,
    }


def test_linha_por_acao_na_campanha_traz_a_campanha() -> None:
    r = parse_performance_row(_linha(campanha=True), "campaign", "conversion_action")
    assert r["campaign_id"] == "21359547724"
    assert r["campaign_name"] == "[GPC][JPA]"
    assert "impressions" not in r and "cost_brl" not in r


def test_combinacoes_validas_e_invalidas() -> None:
    assert _validate_combo("account", "conversion_action") is None
    assert _validate_combo("campaign", "conversion_action") is None
    msg = _validate_combo("ad_group", "conversion_action")
    assert msg is not None and "conversion_action" in msg


def test_o_despachante_leva_o_recorte_ao_construtor_novo() -> None:
    gaql, _ = build_performance_breakdown_query(
        "campaign", "conversion_action", "enabled", _S, _E, 10
    )
    assert "segments.conversion_action" in gaql and "FROM campaign" in gaql
```

O guard do `filters_applied` ganha o exemplo das duas funções novas e a chave de `conversion_action.id`:

```diff
diff --git a/tests/unit/test_filters_applied_e_derivado.py b/tests/unit/test_filters_applied_e_derivado.py
index b1e24c6..b4ebf77 100644
--- a/tests/unit/test_filters_applied_e_derivado.py
+++ b/tests/unit/test_filters_applied_e_derivado.py
@@ -61,6 +61,8 @@ CAMPO_PARA_CHAVE = {
     "campaign.id": "campaign_ids",
     # o gasto dos orcamentos compartilhados, lido do proprio orcamento
     "campaign_budget.id": "budget_ids",
+    # spec 2026-10-02: as flags so das acoes que o recorte por acao trouxe
+    "conversion_action.id": "conversion_action_ids",
 }
 
 
@@ -150,6 +152,10 @@ def _chamadas() -> dict[str, Callable[[], tuple[str, dict[str, Any]]]]:
 
     return {
         "campaign_performance_query": lambda: p.campaign_performance_query(_S, _E, "enabled", 10),
+        "conversion_action_breakdown_query": lambda: p.conversion_action_breakdown_query(
+            "campaign", _S, _E, "enabled", 10
+        ),
+        "conversion_action_flags_query": lambda: p.conversion_action_flags_query(["1", "2"]),
         "ad_group_performance_query": lambda: p.ad_group_performance_query(_S, _E, "enabled", 10),
         "device_performance_query": lambda: p.device_performance_query(_S, _E),
         "geo_performance_query": lambda: p.geo_performance_query(_S, _E, 10),
@@ -196,6 +202,10 @@ def _chamadas_sem_corte() -> list[tuple[str, Callable[[], tuple[str, dict[str, A
 
     return [
         ("campaign_performance_query", lambda: p.campaign_performance_query(_S, _E, "all", 10)),
+        (
+            "conversion_action_breakdown_query",
+            lambda: p.conversion_action_breakdown_query("account", _S, _E, "enabled", 10),
+        ),
         ("ad_group_performance_query", lambda: p.ad_group_performance_query(_S, _E, "all", 10)),
         ("ad_performance_query", lambda: t.ad_performance_query(_S, _E, "all", 10)),
         ("keyword_performance_query", lambda: t.keyword_performance_query(_S, _E, "all", 10)),
@@ -326,6 +336,12 @@ def test_o_breakdown_repassa_o_recorte_da_funcao_que_despacha() -> None:
         ("account", "device"): lambda: p.device_performance_query(_S, _E),
         ("account", "geo"): lambda: p.geo_performance_query(_S, _E, 10),
         ("account", "hourly"): lambda: p.hourly_performance_query(_S, _E),
+        ("account", "conversion_action"): lambda: p.conversion_action_breakdown_query(
+            "account", _S, _E, "enabled", 10
+        ),
+        ("campaign", "conversion_action"): lambda: p.conversion_action_breakdown_query(
+            "campaign", _S, _E, "enabled", 10
+        ),
     }
     for (level, breakdown), direto in esperados.items():
         assert (
```

- [ ] **Step 2: Run test to verify it fails**

Run: `D:/v4-ads-mcp/.venv/Scripts/python.exe -m pytest tests/unit/test_conversao_por_acao.py -p no:cacheprovider -q`
Expected (medido): !!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!! | E ImportError: cannot import name 'conversion_action_breakdown_query' from 'src.google_ads.queries.performance' (D:\v4-ads-mcp-wt\conv-reaplica\src\google_ads\q

- [ ] **Step 3: Write minimal implementation**

`src/google_ads/queries/performance.py`:

```diff
diff --git a/src/google_ads/queries/performance.py b/src/google_ads/queries/performance.py
index db44ec5..02c4dba 100644
--- a/src/google_ads/queries/performance.py
+++ b/src/google_ads/queries/performance.py
@@ -97,3 +97,63 @@ def hourly_performance_query(start: date, end: date) -> tuple[str, dict[str, Any
         WHERE {gaql_date_clause(start, end)}
     """.strip()
     return gaql, {"date_range": janela_aplicada(start, end)}
+
+
+def conversion_action_breakdown_query(
+    level: str, start: date, end: date, status: str, limit: int
+) -> tuple[str, dict[str, Any]]:
+    """Conversoes por acao de conversao, na conta ou por campanha (spec 2026-10-02 §3.1).
+
+    So metricas de conversao: recortar por `segments.conversion_action` recusa custo
+    (medido em 02/10) — nao existe CPA por acao. `ORDER BY` + `LIMIT limit+1` (F98: a
+    linha a mais revela o corte). `conversions` segue o `include_in_conversions_metric`
+    da acao; `all_conversions` soma todas.
+    """
+    filtros: dict[str, Any] = {"date_range": janela_aplicada(start, end)}
+    if level == "account":
+        recurso, campanha, status_clause = "customer", "", ""
+    elif level == "campaign":
+        recurso, campanha, status_clause = "campaign", "campaign.id, campaign.name,", ""
+        if status != "all":
+            status_clause = f"AND campaign.status = '{status.upper()}'"
+            filtros["campaign_status"] = status.upper()
+    else:
+        raise ValueError(f"recorte por acao so em account ou campaign, veio {level!r}")
+    gaql = f"""
+        SELECT
+          {campanha}
+          segments.conversion_action,
+          segments.conversion_action_name,
+          segments.conversion_action_category,
+          metrics.conversions, metrics.all_conversions,
+          metrics.conversions_value, metrics.all_conversions_value
+        FROM {recurso}
+        WHERE {gaql_date_clause(start, end)} {status_clause}
+        ORDER BY metrics.all_conversions DESC
+        LIMIT {limit + 1}
+    """.strip()
+    return gaql, filtros
+
+
+def conversion_action_flags_query(ids: list[str]) -> tuple[str, dict[str, Any]]:
+    """As flags de cada acao do recorte: conta em `conversions`? e meta de lance?
+
+    Acao que este recurso nao devolve (medido: "Conversation started", gerenciada pelo
+    Google ou de outra conta) fica sem flag — quem chama marca `null` com motivo, nunca
+    `false`. `int()` em cada id (F163); `LIMIT 1000` e teto estrutural, uma linha por id.
+    """
+    if not 1 <= len(ids) <= 1000:
+        raise ValueError(f"conversion_action_flags_query: 1 a 1000 acoes, veio {len(ids)}")
+    lista = ", ".join(str(int(x)) for x in ids)
+    gaql = f"""
+        SELECT
+          conversion_action.id,
+          conversion_action.include_in_conversions_metric,
+          conversion_action.primary_for_goal,
+          conversion_action.status,
+          conversion_action.type
+        FROM conversion_action
+        WHERE conversion_action.id IN ({lista})
+        LIMIT 1000
+    """.strip()
+    return gaql, {"conversion_action_ids": list(ids)}
```

`src/google_ads/performance_breakdown.py`:

```diff
diff --git a/src/google_ads/performance_breakdown.py b/src/google_ads/performance_breakdown.py
index 19a0630..7ee998a 100644
--- a/src/google_ads/performance_breakdown.py
+++ b/src/google_ads/performance_breakdown.py
@@ -18,6 +18,7 @@ from src.google_ads.queries._common import (
 from src.google_ads.queries.performance import (
     ad_group_performance_query,
     campaign_performance_query,
+    conversion_action_breakdown_query,
     device_performance_query,
     geo_performance_query,
     hourly_performance_query,
@@ -48,11 +49,15 @@ def _validate_combo(level: str, breakdown: str | None) -> str | None:
     # merge (geoTargetConstant duplicado), nao nivel.
     if level == "campaign" and breakdown == "hourly":
         return None
-    # entity level (exceto campaign+hourly, tratado acima)
+    # Conversao por acao (spec 2026-10-02 §3.1): conta e campanha.
+    if level == "campaign" and breakdown == "conversion_action":
+        return None
+    # entity level (exceto campaign+hourly e campaign+conversion_action, tratados acima)
     if breakdown is not None:
         return (
-            f"breakdown só é suportado em level='account' (device/geo/hourly) ou em "
-            f"level='campaign' com breakdown='hourly' (exige campaign_ids) — você pediu "
+            f"breakdown só é suportado em level='account' (device/geo/hourly/"
+            f"conversion_action) ou em level='campaign' com breakdown='hourly' (exige "
+            f"campaign_ids) ou 'conversion_action' — você pediu "
             f"level='{level}'+breakdown='{breakdown}'. Use uma dessas combinações, ou "
             "remova o breakdown."
         )
@@ -106,12 +111,16 @@ def build_performance_breakdown_query(
             return geo_performance_query(start, end, limit)
         if breakdown == "hourly":
             return hourly_performance_query(start, end)
+        if breakdown == "conversion_action":
+            return conversion_action_breakdown_query("account", start, end, status, limit)
         raise ValueError(f"breakdown invalido pra account: {breakdown!r}")
     if level == "campaign" and breakdown == "hourly":
         raise ValueError(
             "campaign+hourly nao passa por este builder: a tool monta a conjunta "
             "com day_hour_metrics_query, que exige campaign_ids explicitos."
         )
+    if level == "campaign" and breakdown == "conversion_action":
+        return conversion_action_breakdown_query("campaign", start, end, status, limit)
     if level == "campaign":
         return campaign_performance_query(start, end, status, limit)
     if level == "ad_group":
@@ -125,12 +134,40 @@ def build_performance_breakdown_query(
     raise ValueError(f"level invalido: {level!r}")
 
 
+def _parse_conversion_action_row(row: Any, level: str) -> dict[str, Any]:
+    """Linha do recorte por acao: so metricas de conversao (o recorte recusa custo).
+
+    As flags (`conta_em_conversoes`, `primary_for_goal`) nao vem daqui: a tool as le do
+    recurso `conversion_action` e as junta pela id.
+    """
+    s, m = row.segments, row.metrics
+    out: dict[str, Any] = {}
+    if level == "campaign":
+        out["campaign_id"] = str(row.campaign.id)
+        out["campaign_name"] = row.campaign.name
+    out.update(
+        {
+            "conversion_action_id": str(s.conversion_action).rsplit("/", 1)[-1],
+            "conversion_action_name": s.conversion_action_name,
+            "categoria": s.conversion_action_category.name,
+            "conversions": round(float(m.conversions), 2),
+            "all_conversions": round(float(m.all_conversions), 2),
+            "conversions_value_brl": round(float(m.conversions_value), 2),
+            "all_conversions_value_brl": round(float(m.all_conversions_value), 2),
+        }
+    )
+    return out
+
+
 def parse_performance_row(row: Any, level: str, breakdown: str | None) -> dict[str, Any]:
     """Transforma uma linha GAQL (proto) em dict com unit conversions.
 
     Cobre os 5 entity levels (campaign/ad_group/ad/keyword/audience).
     Task 4 cobre account+breakdown.
     """
+    if breakdown == "conversion_action":
+        return _parse_conversion_action_row(row, level)
+
     base = _common_metrics(row.metrics)
 
     if level == "account":
```

- [ ] **Step 4: Run the gate**

Run: `D:/v4-ads-mcp/.venv/Scripts/python.exe scripts/check_pre_push.py`
Expected: `All pre-push checks passed (6 steps ...)`.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(mcp): consultas e parse do recorte por acao de conversao"
```

---

### Task 4: `breakdown='conversion_action'` na tool, com as flags do cadastro da ação

**Files:**
- Create: `tests/unit/test_breakdown_conversao_por_acao_tool.py`
- Modify: `src/mcp/tools/get_performance_breakdown.py`

**Interfaces:**
- Consumes: `conversion_action_flags_query` e o formato de linha da Task 3.
- Produces: linhas do recorte com `conta_em_conversoes`, `primary_for_goal` e `flags_motivo`; schema com `conversion_action` no enum de `breakdown`.

- [ ] **Step 1: Write the failing test**

Crie `tests/unit/test_breakdown_conversao_por_acao_tool.py`, conteúdo exato:

```python
"""A tool `get_performance_breakdown` com `breakdown='conversion_action'` (spec 2026-10-02, §3.1).

As flags de cada ação vêm do recurso `conversion_action`, numa segunda consulta só com as
ações das linhas devolvidas. A que esse recurso não devolve — medido em 02/10: "Conversation
started" (`7028680990`), 173 conversões em setembro e zero linhas em `conversion_action` —
fica com flag `null` e motivo: ausência de medição não é `false` (F191).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.mcp.context import McpRequestContext, clear_current, set_current

_CONTA = "7862230676"


@pytest.fixture(autouse=True)
def _ctx() -> Iterator[None]:
    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    yield
    clear_current()


def _acao(aid: str, nome: str, conv: float, todas: float) -> dict[str, Any]:
    return {
        "conversion_action_id": aid,
        "conversion_action_name": nome,
        "categoria": "CONTACT",
        "conversions": conv,
        "all_conversions": todas,
        "conversions_value_brl": conv,
        "all_conversions_value_brl": todas,
    }


def _flag(aid: str, conta: bool, primaria: bool) -> dict[str, Any]:
    return {
        "conversion_action_id": aid,
        "include_in_conversions_metric": conta,
        "primary_for_goal": primaria,
        "status": "ENABLED",
        "type": "WEBPAGE",
    }


async def _chamar(respostas: list[list[dict[str, Any]]], **args: Any) -> tuple[Any, AsyncMock]:
    from src.mcp.tools.get_performance_breakdown import get_performance_breakdown

    with (
        patch("src.mcp.tools.get_performance_breakdown.run_report", new_callable=AsyncMock) as rr,
        patch(
            "src.mcp.tools.get_performance_breakdown.resolve_account_today",
            new_callable=AsyncMock,
        ) as hoje,
    ):
        from datetime import date

        hoje.return_value = date(2026, 10, 2)
        rr.side_effect = respostas
        out = await get_performance_breakdown(
            {"customer_id": _CONTA, "level": "account", "breakdown": "conversion_action", **args}
        )
    return out, rr


_LINHAS = [
    _acao("6827189000", "Whatsapp - JPA", 204.0, 204.0),
    _acao("7028680990", "Conversation started", 173.0, 173.0),
    _acao("6826176642", "Clicks to call", 0.0, 11.0),
]


async def test_flags_vem_do_recurso_e_a_acao_ausente_fica_null_com_motivo() -> None:
    out, rr = await _chamar(
        [_LINHAS, [_flag("6827189000", True, True), _flag("6826176642", False, True)]]
    )
    por_id = {r["conversion_action_id"]: r for r in out["rows"]}
    assert por_id["6827189000"]["conta_em_conversoes"] is True
    assert por_id["6827189000"]["primary_for_goal"] is True
    assert por_id["6827189000"]["flags_motivo"] is None
    assert por_id["6826176642"]["conta_em_conversoes"] is False
    assert por_id["6826176642"]["primary_for_goal"] is True
    ausente = por_id["7028680990"]
    assert ausente["conta_em_conversoes"] is None
    assert ausente["primary_for_goal"] is None
    assert "conversion_action" in ausente["flags_motivo"]
    flags = rr.await_args_list[1].kwargs["query"]
    assert "conversion_action.id IN (6827189000, 7028680990, 6826176642)" in flags


async def test_corte_antes_das_flags_e_truncated() -> None:
    out, rr = await _chamar([_LINHAS, [_flag("6827189000", True, True)]], limit=2)
    assert out["truncated"] is True
    assert [r["conversion_action_id"] for r in out["rows"]] == ["6827189000", "7028680990"]
    # a sentinela (a 3a linha) nao entra na consulta das flags
    assert "6826176642" not in rr.await_args_list[1].kwargs["query"]


async def test_sem_linha_nao_roda_a_consulta_das_flags() -> None:
    out, rr = await _chamar([[]])
    assert out["rows"] == []
    assert rr.await_count == 1


async def test_filters_applied_e_period_do_recorte() -> None:
    out, rr = await _chamar([_LINHAS[:1], [_flag("6827189000", True, True)]])
    assert out["filters_applied"]["date_range"] == {"start": "2026-09-02", "end": "2026-10-01"}
    assert "FROM customer" in rr.await_args_list[0].kwargs["query"]


def test_description_diz_os_dois_contratos() -> None:
    from src.mcp.tools._registry import get_tool, import_all_tools

    import_all_tools()
    tool = get_tool("get_performance_breakdown")
    assert tool is not None
    d = tool.description
    assert "conversion_action" in d
    assert "conta_em_conversoes" in d and "all_conversions" in d
    assert "flags_motivo" in d
    assert "sem custo" in d.lower() or "nao ha custo" in d.lower()
    assert "parcela_impressao" in d
```

- [ ] **Step 2: Run test to verify it fails**

Run: `D:/v4-ads-mcp/.venv/Scripts/python.exe -m pytest tests/unit/test_breakdown_conversao_por_acao_tool.py -p no:cacheprovider -q`
Expected (medido): (sem linha de resumo) | E AssertionError: assert 'conversion_action' in '[CORE] Performance Google quebrada por nivel + dimensao opcional. level: campaign|ad_group|ad|keyword|audience  / E IndexError: list index out of range / E KeyError: 'conta_em_conversoes'

- [ ] **Step 3: Write minimal implementation**

`src/mcp/tools/get_performance_breakdown.py`:

```diff
diff --git a/src/mcp/tools/get_performance_breakdown.py b/src/mcp/tools/get_performance_breakdown.py
index abfcde1..61e6fae 100644
--- a/src/mcp/tools/get_performance_breakdown.py
+++ b/src/mcp/tools/get_performance_breakdown.py
@@ -16,6 +16,7 @@ from src.google_ads.performance_breakdown import (
 )
 from src.google_ads.queries._common import resolve_date_window
 from src.google_ads.queries.ad_schedule import day_hour_metrics_query, parse_day_hour_row
+from src.google_ads.queries.performance import conversion_action_flags_query
 from src.google_ads.reports import lookup_country_names, run_report
 from src.mcp.context import get_current
 from src.mcp.tools._common import aplicar_limite
@@ -45,8 +46,8 @@ _SCHEMA: dict[str, Any] = {
         },
         "breakdown": {
             "type": "string",
-            "enum": ["device", "geo", "hourly"],
-            "description": "Dimensao secundaria. So em level=account no v0, e (Task 5) tambem em level=campaign.",
+            "enum": ["device", "geo", "hourly", "conversion_action"],
+            "description": "Dimensao secundaria. device/geo/hourly em level=account; hourly (com campaign_ids) e conversion_action tambem em level=campaign.",
         },
         "campaign_ids": {
             "type": "array",
@@ -99,6 +100,35 @@ _ORDEM_DO_DIA: dict[str, int] = {dia: i for i, dia in enumerate(DIAS)}
 # `teto = 168 * len(campaign_ids)`, teto da grade, nao do gestor.
 _CELULAS_DA_GRADE = 7 * 24
 
+# Acao que o recurso `conversion_action` nao devolve (medido em 02/10: "Conversation
+# started", gerenciada pelo Google ou de outra conta). Flag `null` com este motivo — nunca
+# `false`: ausencia de medicao nao e resposta (F191). Spec 2026-10-02 §3.1.
+_MOTIVO_SEM_FLAG = (
+    "acao nao listada em conversion_action (gerenciada pelo Google ou de outra conta)"
+)
+
+
+def _flag_da_acao(row: Any) -> dict[str, Any]:
+    ca = row.conversion_action
+    return {
+        "conversion_action_id": str(ca.id),
+        "include_in_conversions_metric": bool(ca.include_in_conversions_metric),
+        "primary_for_goal": bool(ca.primary_for_goal),
+    }
+
+
+def _junta_flags(rows: list[dict[str, Any]], flags: dict[str, dict[str, Any]]) -> None:
+    for r in rows:
+        f = flags.get(r["conversion_action_id"])
+        if f is None:
+            r["conta_em_conversoes"] = None
+            r["primary_for_goal"] = None
+            r["flags_motivo"] = _MOTIVO_SEM_FLAG
+        else:
+            r["conta_em_conversoes"] = f["include_in_conversions_metric"]
+            r["primary_for_goal"] = f["primary_for_goal"]
+            r["flags_motivo"] = None
+
 
 @register_tool(
     name="get_performance_breakdown",
@@ -128,6 +158,17 @@ _CELULAS_DA_GRADE = 7 * 24
         "devolve negativa, mas por outro motivo: ele exige `quality_score IS NOT "
         "NULL`, e criterio negativo nao tem indice de qualidade). Para visao geral da "
         "conta com comparativo use get_account_overview."
+        " As linhas de level='campaign' trazem a parcela de impressao de pesquisa (fracao"
+        " 0-1): parcela_impressao, perdida_orcamento, perdida_classificacao, parcela_topo,"
+        " parcela_topo_absoluto — null quando o Google nao a mede (campanha que nao e de"
+        " pesquisa, ou sem impressao); 0.0999 e o '< 10%' do Google."
+        " breakdown='conversion_action' (level account ou campaign): uma linha por acao de"
+        " conversao (por campanha x acao em campaign), com conversions, all_conversions e os"
+        " dois valores — sem custo: a API nao cruza custo com acao, entao nao ha CPA por"
+        " acao. `conversions` so soma as acoes com conta_em_conversoes=true; all_conversions"
+        " soma todas. conta_em_conversoes e primary_for_goal vem do cadastro da acao; acao"
+        " fora do cadastro traz os dois null e flags_motivo explica. Ordenado por"
+        " all_conversions desc."
         " Razao com denominador zero vem null (indefinida), nao 0."
         " Com level=campaign e breakdown=hourly a resposta nao traz filters_applied"
         " (grade dia x hora)."
@@ -246,6 +287,20 @@ async def get_performance_breakdown(args: dict[str, Any]) -> dict[str, Any]:
     teto = _CELULAS_DA_GRADE if breakdown == "hourly" else limit
     rows, truncado = aplicar_limite(rows, teto)
 
+    # Depois do corte: a sentinela nao entra na consulta das flags.
+    if breakdown == "conversion_action" and rows:
+        ids = list(dict.fromkeys(r["conversion_action_id"] for r in rows))
+        gaql_flags, _ = conversion_action_flags_query(ids)
+        flags = await run_report(
+            manager_id=ctx.manager_id,
+            session_id=ctx.session_id,
+            customer_id=customer_id,
+            query=gaql_flags,
+            row_formatter=_flag_da_acao,
+            operation_name="get_performance_breakdown",
+        )
+        _junta_flags(rows, {f["conversion_action_id"]: f for f in flags})
+
     if breakdown == "geo":
         country_ids = {r["breakdown"]["country_criterion_id"] for r in rows}
         country_map = await lookup_country_names(
```

- [ ] **Step 4: Run the gate**

Run: `D:/v4-ads-mcp/.venv/Scripts/python.exe scripts/check_pre_push.py`
Expected: `All pre-push checks passed (6 steps ...)`. Sabotagens medidas: a ação ausente gravada como `False` derruba `test_flags_vem_do_recurso_e_a_acao_ausente_fica_null_com_motivo`; as flags consultadas antes do corte derrubam `test_corte_antes_das_flags_e_truncated`.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(mcp): breakdown=conversion_action na tool, com as flags do cadastro da acao"
```

---

## Depois das tasks

- Revisão da branch inteira (o que mora **entre** as tasks: o despachante × o parse × a tool; a description × o contrato real).
- Deploy com autorização nominal; smoke de leitura na Mestre da Obra (spec §7): "Whatsapp - JPA" `conta_em_conversoes: true`, "Clicks to call" `false`, "Conversation started" `null` com motivo; a parcela das duas campanhas igual à do `run_gaql` na mesma janela.
- Texto do plugin para o Wellington (spec §5).
