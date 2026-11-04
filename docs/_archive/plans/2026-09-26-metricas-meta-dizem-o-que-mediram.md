# As métricas Meta dizem o que mediram — plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** As 5 tools de métrica Meta passam a reportar o que a Meta mediu — um contrato único de leitura (ausente é `null`, um nome canônico por evento, `ctr` em fração, conversas iniciadas), atribuição fixada e dita na resposta, e um sinal BUC que não grava "não sei" como 0.

**Architecture:** `src/meta_ads/metricas.py` (puro) é a única leitura de métrica de uma linha `/insights`. `insights.py` (trio e breakdown) e `account_overview.py` (overview) delegam a ele, e `insights.build_insights_call` é o construtor único de toda chamada `/insights`, com a atribuição unificada. Três guards AST fecham o contrato; o BUC ganha o terceiro estado (`None`) e passa a ler o cabeçalho de throttle de insights.

**Tech Stack:** Python 3.13, httpx, structlog, pytest (+ testcontainers na integração), ruff, mypy strict.

**Spec:** [`2026-09-26-metricas-meta-dizem-o-que-mediram-design.md`](../specs/2026-09-26-metricas-meta-dizem-o-que-mediram-design.md)

## Global Constraints

- **A regra (spec §1):** uma métrica Meta diz o que a Meta mediu. Campo que a Meta não mandou é `null`, não zero; o mesmo campo sai pela mesma regra em todas as tools; e a resposta diz a atribuição e a unidade que usou.
- **Mapa canônico (spec §3.1):** `purchases` ← `actions[omni_purchase]`; `purchases_value_brl` ← `action_values[omni_purchase]`; `purchase_roas` ← `purchase_roas[omni_purchase]`; `leads` ← `actions[lead]`; `messaging_conversations_started` ← `actions[onsite_conversion.messaging_conversation_started_7d]`. **Um nome por campo, nunca soma de nomes.**
- **Ausente → `null`**; zero só quando a Meta manda zero; valor que não converte → `null`; contagens arredondam (`round`), não truncam.
- **`ctr` em fração** em todas as tools (a Meta manda porcentagem).
- **Toda chamada `/insights` sai de `build_insights_call`**, com `use_unified_attribution_setting: "true"`; as 5 respostas trazem `atribuicao: "unificada"`.
- **Chaves `_brl` ficam** (fora de escopo, spec §7).
- **BUC (spec §5):** "não lido" é `None`, não chama `update_throttle`, emite `meta_buc_nao_lido`; o aviso de 75% vale para qualquer sinal medido e diz qual. **Sem migration.**
- **Gate:** `python scripts/check_pre_push.py` rodado mudo, lendo `$?` — **nunca** pipe entre o gate e o `&&`.
- **Sabotagem se restaura de CÓPIA, nunca de `git checkout`** (descarta trabalho não commitado). Cópias vão para `.superpowers/` (git-ignored).
- **Commits:** `feat(scope)`/`fix(scope)`/`docs(scope)`, com o trailer `Co-Authored-By` do Claude; mensagem escrita pelo Git Bash (o PowerShell põe BOM).

---

## Como este plano foi validado (26/09)

O código de cada task **rodou** antes de o plano ser escrito — os blocos abaixo foram gerados dos commits de um worktree de validação, não transcritos à mão:

- **Uma task por commit, em sequência sobre `79b82ce`**, cada uma verde isolada: ruff, format, `mypy src` e a suíte unitária inteira (2402, 2400, 2395, 2407, 2410 e — com os docs — os mesmos 2410 testes). Estado final: `check_pre_push_full.py` **7/7**, com a integração com banco (Docker); os 19 testes de integração das 5 tools Meta verdes.
- **Contra a Graph API real** (leitura, token no header): os params do `build_insights_call` novo voltam 200 nos níveis `account` (com `sort` e `limit=1`), `campaign`, `adset`, `ad` e no breakdown horário. Na Cheiro | Conta 01 (`act_926193536103926`, 30 dias): `purchases: 10` (o código anterior dá 0), `leads: 13`, `messaging_conversations_started: 3531`, `purchase_roas: null`; **a soma de `purchases` por campanha dá 10, igual ao total da conta**; `reach: null` em 50 de 50 linhas do horário.
- **Os testes novos foram vistos vermelhos contra o código anterior** — cada Step 2 abaixo diz o que falha e por quê, medido.
- **Os guards** (Task 2, Step 6 e Task 5): vermelhos por sabotagem em cópia, cada sabotagem derrubando só o seu guard, com a mensagem certa; e os dois estruturais vermelhos contra o código anterior.

## Mapa dos arquivos

| arquivo | task | responsabilidade |
|---|---|---|
| `src/meta_ads/metricas.py` (novo) | 1 | o contrato: mapa canônico, `null`, unidade, frases das descriptions |
| `tests/unit/_meta_formas_medidas.py` (novo) | 1 | as formas de linha medidas na Graph API em 26/09 |
| `tests/unit/test_meta_metricas_contrato.py` (novo) | 1 | o contrato sobre as formas medidas |
| `src/meta_ads/insights.py` | 2 | `parse_insights_row` delega; `build_insights_call` ganha `account` e a atribuição |
| `src/mcp/tools/_meta_performance.py` | 2 | ordenação que aceita `null`; `atribuicao` no envelope |
| `src/mcp/tools/meta_get_performance_breakdown.py` | 2 | idem + description |
| `src/mcp/tools/meta_get_{campaign,ad_set,ad}_performance.py` | 2 | descriptions |
| `tests/unit/test_meta_insights.py`, `test_insights_no_phantom_fields.py`, `test_meta_performance_core.py`, `tests/integration/test_meta_get_campaign_performance.py` | 2 | testes do trio; o guard do F89 estendido |
| `src/meta_ads/account_overview.py` | 3 | `parse_insights_response` e `compute_deltas` pelo contrato |
| `src/mcp/tools/meta_get_account_overview.py` | 3 | chamadas pelo construtor; `atribuicao`; description |
| `tests/unit/test_meta_account_overview.py`, `tests/integration/test_meta_get_account_overview.py` | 3 | testes do overview |
| `src/governance/rate_limit.py`, `src/meta_ads/reports.py` | 4 | o sinal BUC |
| `tests/unit/test_buc_header_parsing.py`, `tests/unit/test_meta_buc_registro.py` (novo), `tests/unit/test_meta_reports_executor.py` | 4 | testes do BUC |
| `tests/unit/test_meta_metricas_guards.py` (novo) | 5 | os três guards |
| catálogo, índice da varredura, `estado-atual`, `nucleo.md`, `CLAUDE.md` | 6 | F194 e o estado |

**Como ler os blocos `diff`:** são o diff exato contra o estado da task anterior. Aplique pelo conteúdo (ferramenta de edição) ou salve o bloco num arquivo em `.superpowers/` e rode `git apply --ignore-whitespace <arquivo>`; o resultado tem de ser o do bloco. Os blocos `python` completos são arquivos novos, a escrever inteiros.

---

### Task 1: O contrato das métricas (`metricas.py`)

**Files:**
- Create: `src/meta_ads/metricas.py`
- Create: `tests/unit/_meta_formas_medidas.py`
- Test: `tests/unit/test_meta_metricas_contrato.py`

**Interfaces:**
- Consumes: nada.
- Produces (as tasks 2 a 5 usam estes nomes exatos): `ACAO_COMPRA`, `ACAO_LEAD`, `ACAO_CONVERSA`, `ATRIBUICAO = "unificada"`, `FRASE_DO_NULL`, `FRASE_DO_CTR`, `FRASE_DA_ATRIBUICAO`, `CONTRATO_NA_DESCRIPTION` (as três frases juntas), `MetricaMeta = float | int | None`, `metricas_da_linha(linha: dict[str, Any]) -> dict[str, MetricaMeta]` (12 chaves: `spend_brl`, `impressions`, `clicks`, `ctr`, `cpc_brl`, `reach`, `frequency`, `purchases`, `purchases_value_brl`, `purchase_roas`, `leads`, `messaging_conversations_started`) e `metricas_sem_linha() -> dict[str, MetricaMeta]` (as mesmas chaves; entrega em 0, o resto `None`). Fixtures: `LINHA_COMPRA_E_LEAD`, `LINHA_SO_CONVERSAS`, `LINHA_HORARIA`.

- [ ] **Step 1: Escrever as formas medidas** — `tests/unit/_meta_formas_medidas.py`:

```python
"""Formas de linha /insights MEDIDAS na Graph API em 26/09 (`scripts/probe_meta_metricas.py`).

Os testes do contrato das métricas Meta (spec 2026-09-26) usam estas formas, e não as
que o código antigo supunha: nenhuma das 24 contas medidas devolveu o nome nu
`purchase`, e as fixtures que o usavam modelavam uma convenção, não a Graph API.

A FORMA é medida: os nomes de ação, quais campos vêm e quais faltam. Os VALORES de
compra (10) e lead (13) também são medidos (Cheiro | Conta 01, 30 dias); o resto é
ilustrativo e diz quando é.
"""

from __future__ import annotations

from typing import Any

# A mesma compra sob 5 nomes e o mesmo lead sob 7 (M2), mais as conversas iniciadas
# (M3) e ações de engajamento que o contrato ignora. `action_values` e
# `purchase_roas` NÃO vêm (M4) — ausentes em 14 de 14 contas.
LINHA_COMPRA_E_LEAD: dict[str, Any] = {
    "spend": "22662.53",
    "impressions": "1000000",  # ilustrativo, coerente com o ctr
    "clicks": "17775",  # ilustrativo
    "ctr": "1.777474",
    "cpc": "1.275",  # ilustrativo
    "reach": "412000",  # ilustrativo
    "frequency": "2.43",  # ilustrativo
    "actions": [
        {"action_type": "link_click", "value": "17775"},
        {"action_type": "omni_purchase", "value": "10"},
        {"action_type": "onsite_app_purchase", "value": "10"},
        {"action_type": "onsite_web_app_purchase", "value": "10"},
        {"action_type": "onsite_conversion.purchase", "value": "10"},
        {"action_type": "onsite_web_purchase", "value": "10"},
        {"action_type": "onsite_conversion.lead", "value": "13"},
        {"action_type": "offsite_complete_registration_add_meta_leads", "value": "13"},
        {"action_type": "offsite_search_add_meta_leads", "value": "13"},
        {"action_type": "onsite_web_lead", "value": "13"},
        {"action_type": "lead", "value": "13"},
        {"action_type": "offsite_content_view_add_meta_leads", "value": "13"},
        {"action_type": "onsite_conversion.lead_grouped", "value": "13"},
        {"action_type": "onsite_conversion.messaging_conversation_started_7d", "value": "3531"},
    ],
}

# A conta típica (13 das 14 com gasto): só conversas iniciadas e engajamento, sem
# nenhum tipo de compra ou lead. Valores ilustrativos.
LINHA_SO_CONVERSAS: dict[str, Any] = {
    "spend": "839.79",
    "impressions": "91000",
    "clicks": "839",
    "ctr": "0.922477",
    "cpc": "1.0009",
    "reach": "40210",
    "frequency": "2.26",
    "actions": [
        {"action_type": "link_click", "value": "610"},
        {"action_type": "post_engagement", "value": "1204"},
        {"action_type": "onsite_conversion.messaging_conversation_started_7d", "value": "37"},
    ],
}

# Linha do breakdown horário (M5): `reach` e `frequency` ausentes em 50 de 50 linhas.
LINHA_HORARIA: dict[str, Any] = {
    "campaign_id": "120210000000000001",
    "campaign_name": "Conversas | JP",
    "hourly_stats_aggregated_by_advertiser_time_zone": "09:00:00 - 09:59:59",
    "spend": "12.3",
    "impressions": "1400",
    "clicks": "21",
    "ctr": "1.5",
    "cpc": "0.5857",
}
```

- [ ] **Step 2: Escrever o teste do contrato** — `tests/unit/test_meta_metricas_contrato.py`:

```python
"""O contrato das métricas Meta (spec 2026-09-26, §3) — sobre as formas MEDIDAS.

Cada teste aqui é uma medição de 26/09 que o código anterior errava: `purchases: 0`
sobre 10 compras, lead somado 7 vezes, conversa iniciada invisível, `reach` e ROAS
inventados como zero, `ctr` em duas escalas.
"""

from __future__ import annotations

from src.meta_ads.metricas import (
    ACAO_COMPRA,
    ACAO_CONVERSA,
    ACAO_LEAD,
    metricas_da_linha,
    metricas_sem_linha,
)
from tests.unit._meta_formas_medidas import LINHA_COMPRA_E_LEAD, LINHA_HORARIA, LINHA_SO_CONVERSAS

_CHAVES = {
    "spend_brl",
    "impressions",
    "clicks",
    "ctr",
    "cpc_brl",
    "reach",
    "frequency",
    "purchases",
    "purchases_value_brl",
    "purchase_roas",
    "leads",
    "messaging_conversations_started",
}


def test_compra_sob_cinco_nomes_conta_uma_vez() -> None:
    """M2: o total canônico é `omni_purchase`; os outros 4 nomes são recortes dele."""
    m = metricas_da_linha(LINHA_COMPRA_E_LEAD)
    assert m["purchases"] == 10


def test_lead_sob_sete_nomes_conta_uma_vez() -> None:
    """M2: somar os 7 nomes daria 91 — o mesmo lead contado sete vezes."""
    m = metricas_da_linha(LINHA_COMPRA_E_LEAD)
    assert m["leads"] == 13


def test_conversa_iniciada_e_campo_proprio() -> None:
    """M3: 14 de 14 contas com gasto medem conversa iniciada."""
    assert metricas_da_linha(LINHA_COMPRA_E_LEAD)["messaging_conversations_started"] == 3531
    assert metricas_da_linha(LINHA_SO_CONVERSAS)["messaging_conversations_started"] == 37


def test_evento_que_a_conta_nao_reporta_e_null_nao_zero() -> None:
    """A Meta omite o tipo com zero ocorrência: null = zero OU não rastreado."""
    m = metricas_da_linha(LINHA_SO_CONVERSAS)
    assert m["purchases"] is None
    assert m["leads"] is None


def test_valor_e_roas_ausentes_sao_null() -> None:
    """M4: `action_values` e `purchase_roas` vazios em 14 de 14 contas."""
    m = metricas_da_linha(LINHA_COMPRA_E_LEAD)
    assert m["purchases_value_brl"] is None
    assert m["purchase_roas"] is None


def test_roas_le_a_entrada_do_total_canonico_nao_a_primeira() -> None:
    """Antes o trio pegava `purchase_roas[0]` sem olhar o tipo."""
    linha = {
        "purchase_roas": [
            {"action_type": "offsite_conversion.fb_pixel_purchase", "value": "9.9"},
            {"action_type": ACAO_COMPRA, "value": "4.45"},
        ]
    }
    assert metricas_da_linha(linha)["purchase_roas"] == 4.45


def test_reach_e_frequency_ausentes_no_horario_sao_null() -> None:
    """M5: ausentes em 50 de 50 linhas do breakdown horário."""
    m = metricas_da_linha(LINHA_HORARIA)
    assert m["reach"] is None
    assert m["frequency"] is None
    assert m["spend_brl"] == 12.3


def test_ctr_sai_em_fracao() -> None:
    """M1: a Meta manda porcentagem (1.777474 = 1,78%)."""
    assert metricas_da_linha(LINHA_COMPRA_E_LEAD)["ctr"] == 0.0178
    assert metricas_da_linha({})["ctr"] is None


def test_contagem_arredonda_nao_trunca() -> None:
    linha = {"actions": [{"action_type": ACAO_LEAD, "value": "2.9"}], "impressions": "99.6"}
    m = metricas_da_linha(linha)
    assert m["leads"] == 3
    assert m["impressions"] == 100


def test_valor_que_nao_converte_e_null() -> None:
    linha = {"spend": "n/a", "actions": [{"action_type": ACAO_CONVERSA, "value": "x"}]}
    m = metricas_da_linha(linha)
    assert m["spend_brl"] is None
    assert m["messaging_conversations_started"] is None


def test_zero_que_a_meta_manda_segue_zero() -> None:
    """Null é só para o que não veio: o zero medido continua zero."""
    linha = {"spend": "0", "actions": [{"action_type": ACAO_COMPRA, "value": "0"}]}
    m = metricas_da_linha(linha)
    assert m["spend_brl"] == 0.0
    assert m["purchases"] == 0


def test_linha_vazia_da_todas_as_chaves_em_null() -> None:
    m = metricas_da_linha({})
    assert set(m) == _CHAVES
    assert all(v is None for v in m.values())


def test_sem_linha_entrega_zero_e_eventos_null() -> None:
    """M7: sem entrega, a Meta não manda linha. Entrega 0 é verdade; o resto é null."""
    m = metricas_sem_linha()
    assert set(m) == _CHAVES
    assert (m["spend_brl"], m["impressions"], m["clicks"], m["reach"]) == (0.0, 0, 0, 0)
    for chave in ("purchases", "leads", "messaging_conversations_started", "ctr", "frequency"):
        assert m[chave] is None, chave
```

- [ ] **Step 3: Ver falhar**

Run: `python -m pytest tests/unit/test_meta_metricas_contrato.py -p no:cacheprovider`
Expected: erro de coleta, `ModuleNotFoundError: No module named 'src.meta_ads.metricas'`.

- [ ] **Step 4: Implementar o contrato** — `src/meta_ads/metricas.py`:

```python
"""O contrato das métricas Meta — a ÚNICA leitura de métrica de uma linha da Graph API.

Spec 2026-09-26 (métricas Meta dizem o que mediram). Antes deste módulo, os mesmos
campos saíam por duas regras: `insights.py` (trio e breakdown) buscava o nome exato
`purchase`, que nenhuma das 24 contas medidas devolve, e reportava `purchases: 0`
sobre 10 compras reais; `account_overview.py` somava seis nomes, o que conta o mesmo
evento várias vezes quando a conta devolve recortes sobrepostos. O `ctr` saía em
fração num e em porcentagem no outro. É o F189/F190 de novo — a regra consertada num
gêmeo e não no outro —, e por isso o guard estrutural (`test_meta_metricas_guards.py`)
proíbe qualquer outro arquivo Meta de ler chave de métrica da linha.

Três regras, uma fonte:

1. **Um nome por campo, nunca soma de nomes.** Medido em 26/09: a mesma compra sai
   sob 5 nomes e o mesmo lead sob 7; somar recortes multiplica o evento.
2. **Ausente é `None`.** A Meta OMITE o tipo de ação com zero ocorrência, então
   `None` quer dizer "não reportado: zero ou não rastreado — a API não distingue".
   Valor que não converte para número também é `None`. Zero só quando a Meta manda
   zero.
3. **`ctr` em fração**, como o `ctr` do Google: a Meta manda porcentagem.

Puro: sem IO, sem SDK.
"""

from typing import Any

# O mapa canônico (spec §3.1). Os totais que o Gerenciador de Anúncios chama de
# "Compras" e "Leads"; os outros nomes medidos são recortes do mesmo número.
ACAO_COMPRA = "omni_purchase"
ACAO_LEAD = "lead"
ACAO_CONVERSA = "onsite_conversion.messaging_conversation_started_7d"

# Toda chamada /insights sai com `use_unified_attribution_setting=true`
# (`insights.build_insights_call`), e a resposta diz qual atribuição usou.
ATRIBUICAO = "unificada"

# Frases que as descriptions das tools Meta de métrica carregam — uma fonte só, e o
# teste de description confere a presença por varredura do registry.
FRASE_DO_NULL = "Metrica null = a Meta nao reportou: zero ou nao rastreado (a API nao distingue)."
FRASE_DO_CTR = "ctr em fracao (0.0283 = 2,83%), como no Google."
FRASE_DA_ATRIBUICAO = "Atribuicao unificada: a do conjunto de anuncios, como no Gerenciador."
CONTRATO_NA_DESCRIPTION = f"{FRASE_DO_NULL} {FRASE_DO_CTR} {FRASE_DA_ATRIBUICAO}"

MetricaMeta = float | int | None


def _numero(valor: Any) -> float | None:
    if valor is None:
        return None
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def _contagem(valor: float | None) -> int | None:
    """Arredonda, não trunca: `int(2.9)` dava 2."""
    return None if valor is None else round(valor)


def _casas(valor: float | None, casas: int) -> float | None:
    return None if valor is None else round(valor, casas)


def _da_acao(lista: Any, tipo: str) -> float | None:
    """Valor do tipo `tipo` numa lista de ações Graph. Tipo ausente -> `None`."""
    if not isinstance(lista, list):
        return None
    for item in lista:
        if isinstance(item, dict) and item.get("action_type") == tipo:
            return _numero(item.get("value"))
    return None


def metricas_da_linha(linha: dict[str, Any]) -> dict[str, MetricaMeta]:
    """As métricas de UMA linha /insights, pelo contrato. Os nomes são os da resposta."""
    ctr = _numero(linha.get("ctr"))
    return {
        "spend_brl": _casas(_numero(linha.get("spend")), 2),
        "impressions": _contagem(_numero(linha.get("impressions"))),
        "clicks": _contagem(_numero(linha.get("clicks"))),
        "ctr": None if ctr is None else round(ctr / 100, 4),
        "cpc_brl": _casas(_numero(linha.get("cpc")), 4),
        "reach": _contagem(_numero(linha.get("reach"))),
        "frequency": _casas(_numero(linha.get("frequency")), 2),
        "purchases": _contagem(_da_acao(linha.get("actions"), ACAO_COMPRA)),
        "purchases_value_brl": _casas(_da_acao(linha.get("action_values"), ACAO_COMPRA), 2),
        "purchase_roas": _casas(_da_acao(linha.get("purchase_roas"), ACAO_COMPRA), 2),
        "leads": _contagem(_da_acao(linha.get("actions"), ACAO_LEAD)),
        "messaging_conversations_started": _contagem(_da_acao(linha.get("actions"), ACAO_CONVERSA)),
    }


def metricas_sem_linha() -> dict[str, MetricaMeta]:
    """Período em que a Meta não devolveu linha nenhuma (spec §3.4).

    A Meta não manda linha zerada — sem entrega, não vem linha. Entrega em 0 é
    verdade (não houve impressão, clique, gasto nem alcance); eventos, valores e
    razões ficam `None`, pela regra 2: a Meta não diz se a conta rastreia o evento.
    Derivado de `metricas_da_linha({})`, então as chaves não divergem.
    """
    return {
        **metricas_da_linha({}),
        "spend_brl": 0.0,
        "impressions": 0,
        "clicks": 0,
        "reach": 0,
    }
```

- [ ] **Step 5: Ver passar**

Run: `python -m pytest tests/unit/test_meta_metricas_contrato.py -p no:cacheprovider`
Expected: `13 passed`.

- [ ] **Step 6: Gate** — `python scripts/check_pre_push.py`, mudo; `echo $?` → `0`.

- [ ] **Step 7: Commit**

```bash
git add src/meta_ads/metricas.py tests/unit/_meta_formas_medidas.py tests/unit/test_meta_metricas_contrato.py
git commit -m "feat(meta_ads): contrato unico das metricas Meta (metricas.py)"
```

---

### Task 2: Trio e breakdown pelo contrato; o construtor único com a atribuição

**Files:**
- Modify: `src/meta_ads/insights.py`, `src/mcp/tools/_meta_performance.py`, `src/mcp/tools/meta_get_performance_breakdown.py`, `src/mcp/tools/meta_get_campaign_performance.py`, `src/mcp/tools/meta_get_ad_set_performance.py`, `src/mcp/tools/meta_get_ad_performance.py`
- Test: `tests/unit/test_meta_insights.py`, `tests/unit/test_insights_no_phantom_fields.py`, `tests/unit/test_meta_performance_core.py`, `tests/integration/test_meta_get_campaign_performance.py`

**Interfaces:**
- Consumes (Task 1): `metricas_da_linha`, `ATRIBUICAO`, `CONTRATO_NA_DESCRIPTION`; fixtures `LINHA_COMPRA_E_LEAD`, `LINHA_HORARIA`.
- Produces: `insights.NivelDaChamada = Literal["account", "campaign", "adset", "ad"]`; `build_insights_call(*, level: NivelDaChamada, ...)` — `level="account"` pede só `_COMMON_INSIGHTS_FIELDS`, e todo `params` traz `"use_unified_attribution_setting": "true"`; `_meta_performance._gasto_para_ordenar(linha) -> float` (o breakdown importa); `"atribuicao"` no envelope do trio e do breakdown. **Saem** `insights._extract_action_value` e `insights._extract_purchase_roas` (só testes os importavam — o Step 1 remove esses imports).

**Por que o guard do F89 muda aqui:** ele lia `row.get(...)` só dentro de `parse_insights_row`. Com as métricas movidas para `metricas_da_linha`, ele ficaria **verde sobre um campo fantasma plantado no contrato** — medido na validação: o guard antigo, com `linha.get("unique_clicks")` no contrato, lê só `ad_id`, `campaign_id`… e passa. O Step 1 o faz varrer os dois leitores; o Step 6 prova a mordida.

**Por que `test_meta_performance_core.py` muda:** ele afirma o conjunto EXATO de chaves do envelope, e `atribuicao` é campo novo e honesto — a mesma atualização que o F88 fez ao acrescentar `truncated`.

- [ ] **Step 1: Escrever os testes**

`tests/unit/test_meta_insights.py` — a fixture completa passa à forma medida (`omni_purchase`), o "sem actions" afirma `null` (afirmava a regra revogada: `== 0`), saem os testes dos dois extratores removidos, entram os das formas medidas e do construtor:

```diff
diff --git a/tests/unit/test_meta_insights.py b/tests/unit/test_meta_insights.py
index 9c85a65..3582efe 100644
--- a/tests/unit/test_meta_insights.py
+++ b/tests/unit/test_meta_insights.py
@@ -6,11 +6,10 @@ Pure module — zero IO, zero SDK. ~50ms total.
 from datetime import date
 
 from src.meta_ads.insights import (
-    _extract_action_value,
-    _extract_purchase_roas,
     build_insights_call,
     parse_insights_row,
 )  # noqa: F401
+from tests.unit._meta_formas_medidas import LINHA_COMPRA_E_LEAD, LINHA_HORARIA
 
 # ============================================================================
 # build_insights_call
@@ -118,11 +117,13 @@ def test_parse_insights_row_campaign_full() -> None:
         "cpc": "1.54",
         "reach": "12345",
         "frequency": "4.05",
+        # Spec 2026-09-26: a forma MEDIDA — o total de compras e `omni_purchase`;
+        # o nome nu `purchase` nao apareceu em nenhuma das 24 contas.
         "actions": [
-            {"action_type": "purchase", "value": "12"},
+            {"action_type": "omni_purchase", "value": "12"},
             {"action_type": "lead", "value": "3"},
         ],
-        "action_values": [{"action_type": "purchase", "value": "5500.00"}],
+        "action_values": [{"action_type": "omni_purchase", "value": "5500.00"}],
         "purchase_roas": [{"action_type": "omni_purchase", "value": "4.45"}],
     }
     out = parse_insights_row(row, "campaign")
@@ -142,6 +143,7 @@ def test_parse_insights_row_campaign_full() -> None:
     assert out["purchases_value_brl"] == 5500.00
     assert out["purchase_roas"] == 4.45
     assert out["leads"] == 3
+    assert out["messaging_conversations_started"] is None
 
 
 # ============================================================================
@@ -211,8 +213,12 @@ def test_parse_insights_row_ad_sem_metadata_de_criativo() -> None:
 # ============================================================================
 
 
-def test_parse_insights_row_no_actions() -> None:
-    """Row sem actions → purchases=0, leads=0, purchases_value_brl=0."""
+def test_parse_insights_row_sem_actions_da_null_nao_zero() -> None:
+    """Spec 2026-09-26: evento que a Meta nao reportou e null (zero OU nao rastreado).
+
+    Este teste afirmava `purchases == 0` sobre uma linha sem `actions` — a regra que o
+    spec revoga: o 0 era indistinguivel de "a Meta mediu e deu zero".
+    """
     row = {
         "campaign_id": "1",
         "campaign_name": "Test",
@@ -220,10 +226,11 @@ def test_parse_insights_row_no_actions() -> None:
         "spend": "100",
     }
     out = parse_insights_row(row, "campaign")
-    assert out["purchases"] == 0
-    assert out["purchases_value_brl"] == 0.0
-    assert out["leads"] == 0
-    assert out["purchase_roas"] == 0.0
+    assert out["purchases"] is None
+    assert out["purchases_value_brl"] is None
+    assert out["leads"] is None
+    assert out["purchase_roas"] is None
+    assert out["messaging_conversations_started"] is None
 
 
 def test_parse_insights_row_ctr_normalization() -> None:
@@ -263,52 +270,27 @@ def test_parse_insights_row_ignora_metadata_que_a_query_nao_pede() -> None:
 
 
 # ============================================================================
-# _extract_action_value helper
-# ============================================================================
-
-
-def test_extract_action_value_missing_action_type() -> None:
-    actions = [{"action_type": "link_click", "value": "100"}]
-    assert _extract_action_value(actions, "purchase") == 0.0
-
-
-def test_extract_action_value_first_match_only() -> None:
-    """Se houver múltiplos action_type='purchase', retorna primeiro encontrado."""
-    actions = [
-        {"action_type": "purchase", "value": "10"},
-        {"action_type": "purchase", "value": "20"},
-    ]
-    assert _extract_action_value(actions, "purchase") == 10.0
-
-
-def test_extract_action_value_malformed_value() -> None:
-    """Value não-numérico → 0 (defensive)."""
-    actions = [{"action_type": "purchase", "value": "not_a_number"}]
-    assert _extract_action_value(actions, "purchase") == 0.0
-
-
-def test_extract_action_value_none_or_empty() -> None:
-    assert _extract_action_value(None, "purchase") == 0.0
-    assert _extract_action_value([], "purchase") == 0.0
-
-
-# ============================================================================
-# _extract_purchase_roas helper
+# As formas medidas em 26/09 (spec 2026-09-26) — o que o parser anterior errava
 # ============================================================================
 
 
-def test_extract_purchase_roas_first_only() -> None:
-    """purchase_roas é lista; retorna [0].value."""
-    roas = [
-        {"action_type": "omni_purchase", "value": "4.45"},
-        {"action_type": "purchase", "value": "5.00"},  # ignored
-    ]
-    assert _extract_purchase_roas(roas) == 4.45
+def test_compra_e_lead_sob_varios_nomes_saem_pelo_total_canonico() -> None:
+    """M2: 10 compras sob 5 nomes, 13 leads sob 7. O parser anterior buscava o nome
+    exato `purchase` e devolvia `purchases: 0` sobre as 10 compras."""
+    row = {"campaign_id": "1", "campaign_name": "C", **LINHA_COMPRA_E_LEAD}
+    out = parse_insights_row(row, "campaign")
+    assert out["purchases"] == 10
+    assert out["leads"] == 13
+    assert out["messaging_conversations_started"] == 3531
 
 
-def test_extract_purchase_roas_empty_list() -> None:
-    assert _extract_purchase_roas([]) == 0.0
-    assert _extract_purchase_roas(None) == 0.0
+def test_linha_horaria_sem_reach_da_null() -> None:
+    """M5: o breakdown horario nao traz reach/frequency — antes saiam 0."""
+    chave = "hourly_stats_aggregated_by_advertiser_time_zone"
+    out = parse_insights_row(dict(LINHA_HORARIA), "campaign", breakdown_keys=[chave])
+    assert out["reach"] is None
+    assert out["frequency"] is None
+    assert out["breakdown"] == {chave: "09:00:00 - 09:59:59"}
 
 
 # ============================================================================
@@ -397,3 +379,49 @@ def test_parse_insights_row_breakdown_missing_value_is_none() -> None:
     row = {"campaign_id": "1", "campaign_name": "T", "effective_status": "ACTIVE", "spend": "10"}
     out = parse_insights_row(row, "campaign", breakdown_keys=["publisher_platform"])
     assert out["breakdown"] == {"publisher_platform": None}
+
+
+# ============================================================================
+# build_insights_call — nivel `account` e atribuicao (spec 2026-09-26, §4.2)
+# ============================================================================
+
+
+def test_build_insights_call_nivel_account_pede_so_as_metricas() -> None:
+    """O overview passa a sair do construtor unico, no nivel `account`."""
+    edge, params = build_insights_call(
+        level="account",
+        ad_account_id="act_123",
+        start=date(2026, 9, 1),
+        end=date(2026, 9, 7),
+        limit=1,
+    )
+    assert edge == "/act_123/insights"
+    assert params["level"] == "account"
+    assert params["fields"].split(",") == [
+        "spend",
+        "impressions",
+        "clicks",
+        "ctr",
+        "cpc",
+        "reach",
+        "frequency",
+        "actions",
+        "action_values",
+        "purchase_roas",
+    ]
+    assert "ad_account_id" not in params
+
+
+def test_toda_chamada_leva_a_atribuicao_unificada() -> None:
+    """Sondado com controle: valor invalido volta 400, entao a API le o parametro."""
+    for level in ("account", "campaign", "adset", "ad"):
+        for breakdowns in (None, ["publisher_platform"]):
+            _, params = build_insights_call(
+                level=level,  # type: ignore[arg-type]
+                ad_account_id="act_1",
+                start=date(2026, 9, 1),
+                end=date(2026, 9, 1),
+                limit=10,
+                breakdowns=breakdowns,
+            )
+            assert params["use_unified_attribution_setting"] == "true", (level, breakdowns)
```

`tests/unit/test_insights_no_phantom_fields.py` — o guard do F89 passa a varrer os dois leitores de linha:

```diff
diff --git a/tests/unit/test_insights_no_phantom_fields.py b/tests/unit/test_insights_no_phantom_fields.py
index 84d8a52..9422c3f 100644
--- a/tests/unit/test_insights_no_phantom_fields.py
+++ b/tests/unit/test_insights_no_phantom_fields.py
@@ -87,25 +87,22 @@ def test_breakdown_continua_exposto() -> None:
     assert out["breakdown"] == {"publisher_platform": "instagram"}
 
 
-def test_parser_nao_le_campo_que_a_query_nao_pede() -> None:
-    """Guard da classe F89: `row.get("x")` exige que "x" esteja em INSIGHTS_FIELDS_*.
-
-    E o que faltava pra fechar F53/F54 — aqueles fixes corrigiram a QUERY e
-    deixaram o parser pedindo campo inexistente. Le o AST de `parse_insights_row`
-    e cruza cada literal lido com a uniao das listas que a query realmente manda.
-    Chaves de breakdown sao dinamicas (`row.get(key)`), entao nao aparecem como
-    constante e ficam naturalmente fora do check.
-    """
-    pedidos = set(INSIGHTS_FIELDS_CAMPAIGN) | set(INSIGHTS_FIELDS_ADSET) | set(INSIGHTS_FIELDS_AD)
+# Toda funcao que le campo de uma linha /insights, e o arquivo onde mora. Spec
+# 2026-09-26: as metricas sairam de `parse_insights_row` para o contrato
+# (`metricas.py`) — com o guard olhando so o parser, a leitura de metrica ficava fora
+# da varredura e ele seguia verde sobre um campo fantasma (medido: `linha.get(...)`
+# plantado no contrato passava). O `.get` e casado no NOME DO PRIMEIRO PARAMETRO de
+# cada funcao, nao num nome fixo: `row` aqui, `linha` la.
+_LEITORES_DE_LINHA = (
+    ("insights.py", "parse_insights_row"),
+    ("metricas.py", "metricas_da_linha"),
+)
 
-    fonte = (h.SRC / "meta_ads" / "insights.py").read_text(encoding="utf-8")
-    tree = ast.parse(fonte)
-    alvo = next(
-        n
-        for n in ast.walk(tree)
-        if isinstance(n, ast.FunctionDef) and n.name == "parse_insights_row"
-    )
 
+def _campos_lidos(arquivo: str, funcao: str) -> set[str]:
+    tree = h.arvore(h.SRC / "meta_ads" / arquivo)
+    alvo = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == funcao)
+    param = alvo.args.args[0].arg
     lidos: set[str] = set()
     for node in ast.walk(alvo):
         if (
@@ -113,16 +110,33 @@ def test_parser_nao_le_campo_que_a_query_nao_pede() -> None:
             and isinstance(node.func, ast.Attribute)
             and node.func.attr == "get"
             and isinstance(node.func.value, ast.Name)
-            and node.func.value.id == "row"
+            and node.func.value.id == param
             and node.args
             and isinstance(node.args[0], ast.Constant)
             and isinstance(node.args[0].value, str)
         ):
             lidos.add(node.args[0].value)
+    return lidos
 
-    fantasmas = sorted(lidos - pedidos)
+
+def test_parser_nao_le_campo_que_a_query_nao_pede() -> None:
+    """Guard da classe F89: toda leitura de campo da linha exige o campo na query.
+
+    E o que faltava pra fechar F53/F54 — aqueles fixes corrigiram a QUERY e
+    deixaram o parser pedindo campo inexistente. Le o AST de cada leitor de linha
+    (`_LEITORES_DE_LINHA`) e cruza cada literal lido com a uniao das listas que a
+    query realmente manda. Chaves de breakdown sao dinamicas (`row.get(key)`), entao
+    nao aparecem como constante e ficam naturalmente fora do check.
+    """
+    pedidos = set(INSIGHTS_FIELDS_CAMPAIGN) | set(INSIGHTS_FIELDS_ADSET) | set(INSIGHTS_FIELDS_AD)
+    fantasmas = {}
+    for arquivo, funcao in _LEITORES_DE_LINHA:
+        lidos = _campos_lidos(arquivo, funcao)
+        assert lidos, f"{arquivo}::{funcao} nao le campo nenhum — o guard perdeu o alvo"
+        if lidos - pedidos:
+            fantasmas[f"{arquivo}::{funcao}"] = sorted(lidos - pedidos)
     assert not fantasmas, (
-        f"F89 — parse_insights_row le campo que a query nao pede: {fantasmas}. "
+        f"F89 — leitor de linha le campo que a query nao pede: {fantasmas}. "
         "Campo ausente do row vira valor constante (None/'UNKNOWN') em 100% das "
         "linhas e o consumidor LLM reporta como se fosse dado. Ou inclua o campo "
         "em INSIGHTS_FIELDS_* (se a Meta Insights aceitar — ver F53/F54), ou pare "
```

`tests/unit/test_meta_performance_core.py`:

```diff
diff --git a/tests/unit/test_meta_performance_core.py b/tests/unit/test_meta_performance_core.py
index d61c438..fcdd83e 100644
--- a/tests/unit/test_meta_performance_core.py
+++ b/tests/unit/test_meta_performance_core.py
@@ -161,13 +161,15 @@ async def test_run_meta_level_performance_success_shape_parity(level: str) -> No
     # F88: `truncated` entrou no envelope de propósito. A parity desta suíte é
     # com o shape pré-dedup M.3, e a adição é aditiva — nenhum campo saiu. Sem
     # ela, o consumidor não tem como saber que o "top por gasto" pode estar
-    # incompleto porque o teto de paginação cortou.
+    # incompleto porque o teto de paginação cortou. `atribuicao` entrou pelo mesmo
+    # motivo (spec 2026-09-26, §4.2): a resposta diz a atribuição que usou.
     assert set(result) == {
         "status",
         "ad_account_id",
         "ad_account_name",
         "currency",
         "date_range",
+        "atribuicao",
         "rows",
         "total_rows",
         "truncated",
```

`tests/integration/test_meta_get_campaign_performance.py` — fixture na forma medida:

```diff
diff --git a/tests/integration/test_meta_get_campaign_performance.py b/tests/integration/test_meta_get_campaign_performance.py
index b73bc84..02cf71e 100644
--- a/tests/integration/test_meta_get_campaign_performance.py
+++ b/tests/integration/test_meta_get_campaign_performance.py
@@ -73,8 +73,8 @@ async def test_happy_path_returns_sorted_rows(db):
                 "clicks": "50",
                 "ctr": "5.0",
                 "cpc": "2.0",
-                "actions": [{"action_type": "purchase", "value": "1"}],
-                "action_values": [{"action_type": "purchase", "value": "50"}],
+                "actions": [{"action_type": "omni_purchase", "value": "1"}],
+                "action_values": [{"action_type": "omni_purchase", "value": "50"}],
                 "purchase_roas": [{"action_type": "omni_purchase", "value": "0.5"}],
             },
             {
@@ -86,8 +86,8 @@ async def test_happy_path_returns_sorted_rows(db):
                 "clicks": "300",
                 "ctr": "3.0",
                 "cpc": "3.33",
-                "actions": [{"action_type": "purchase", "value": "20"}],
-                "action_values": [{"action_type": "purchase", "value": "4000"}],
+                "actions": [{"action_type": "omni_purchase", "value": "20"}],
+                "action_values": [{"action_type": "omni_purchase", "value": "4000"}],
                 "purchase_roas": [{"action_type": "omni_purchase", "value": "4.0"}],
             },
             {
@@ -128,6 +128,11 @@ async def test_happy_path_returns_sorted_rows(db):
     assert top["purchases"] == 20
     assert top["purchases_value_brl"] == 4000.0
     assert top["purchase_roas"] == 4.0
+    # Spec 2026-09-26: evento nao reportado e null; a campanha de leads tem leads.
+    assert top["leads"] is None
+    assert result["rows"][1]["leads"] == 10
+    assert result["rows"][1]["purchases"] is None
+    assert result["atribuicao"] == "unificada"
     # F89: metadata de entidade nao sai na resposta (era 'DESCONHECIDO' sempre).
     assert "effective_status" not in top
     assert "effective_status_label" not in top
```

- [ ] **Step 2: Ver falhar**

Run: `python -m pytest tests/unit/test_meta_insights.py tests/unit/test_insights_no_phantom_fields.py tests/unit/test_meta_performance_core.py -p no:cacheprovider`
Expected (medido contra o código anterior):
- `test_compra_e_lead_sob_varios_nomes_saem_pelo_total_canonico`: `assert 0 == 10` — o parser anterior busca o nome nu `purchase`;
- `test_linha_horaria_sem_reach_da_null`: `assert 0 is None`;
- `test_parse_insights_row_sem_actions_da_null_nao_zero`: `assert 0 is None`;
- `test_parse_insights_row_campaign_full`: `assert 0 == 12` — `purchases` sobre `omni_purchase`;
- `test_build_insights_call_nivel_account_pede_so_as_metricas`: `KeyError: 'account'`;
- `test_toda_chamada_leva_a_atribuicao_unificada`: `KeyError: 'account'` (o nível ainda não existe);
- os 3 `test_run_meta_level_performance_success_shape_parity[...]`: conjunto sem `atribuicao`;
- `test_parser_nao_le_campo_que_a_query_nao_pede` **passa** — por construção: o contrato só lê campos pedidos; a mordida é provada no Step 6.

Total medido: `9 failed, 28 passed`.

- [ ] **Step 3: Implementar**

`src/meta_ads/insights.py`:

```diff
diff --git a/src/meta_ads/insights.py b/src/meta_ads/insights.py
index 22d8504..eb2ecba 100644
--- a/src/meta_ads/insights.py
+++ b/src/meta_ads/insights.py
@@ -18,7 +18,13 @@ resposta, com valor de verdade.
 from datetime import date
 from typing import Any, Literal
 
+from src.meta_ads.metricas import metricas_da_linha
+
+# Nivel de LINHA (o que `parse_insights_row` sabe desenhar) x nivel de CHAMADA
+# (o que `build_insights_call` monta): o overview pede `account`, uma linha so, e a
+# le por `account_overview.parse_insights_response` — nao por `parse_insights_row`.
 Level = Literal["campaign", "adset", "ad"]
+NivelDaChamada = Literal["account", "campaign", "adset", "ad"]
 
 Breakdown = Literal["platform", "device", "geo", "hourly"]
 
@@ -78,7 +84,7 @@ INSIGHTS_FIELDS_AD = [
 
 def build_insights_call(
     *,
-    level: Level,
+    level: NivelDaChamada,
     ad_account_id: str,
     start: date,
     end: date,
@@ -103,6 +109,7 @@ def build_insights_call(
     resolver a conta, e não muda.
     """
     fields_by_level = {
+        "account": _COMMON_INSIGHTS_FIELDS,
         "campaign": INSIGHTS_FIELDS_CAMPAIGN,
         "adset": INSIGHTS_FIELDS_ADSET,
         "ad": INSIGHTS_FIELDS_AD,
@@ -125,35 +132,18 @@ def build_insights_call(
         # nada (foi assim que F53/F54/F55 nasceram). A combinacao com
         # `breakdowns` foi sondada a parte, inclusive a hourly.
         "sort": "spend_descending",
+        # Spec 2026-09-26 §4.2: a atribuicao configurada no conjunto de anuncios,
+        # que e o que o Gerenciador mostra. Sondado com controle: valor invalido
+        # volta HTTP 400 ("must be a boolean"), entao a API le o parametro
+        # (`scripts/probe_meta_metricas.py`). A resposta diz qual usou
+        # (`metricas.ATRIBUICAO`).
+        "use_unified_attribution_setting": "true",
     }
     if breakdowns:
         params["breakdowns"] = ",".join(breakdowns)
     return edge, params
 
 
-def _extract_action_value(actions: list[dict[str, Any]] | None, action_type: str) -> float:
-    """Extract value of FIRST action matching action_type. 0 if absent."""
-    if not actions:
-        return 0.0
-    for a in actions:
-        if a.get("action_type") == action_type:
-            try:
-                return float(a.get("value", 0))
-            except (TypeError, ValueError):
-                return 0.0
-    return 0.0
-
-
-def _extract_purchase_roas(roas_list: list[dict[str, Any]] | None) -> float:
-    """purchase_roas é lista: [{'action_type':'omni_purchase','value':'4.45'}]."""
-    if not roas_list:
-        return 0.0
-    try:
-        return float(roas_list[0].get("value", 0))
-    except (TypeError, ValueError, IndexError):
-        return 0.0
-
-
 def parse_insights_row(
     row: dict[str, Any], level: Level, breakdown_keys: list[str] | None = None
 ) -> dict[str, Any]:
@@ -163,29 +153,16 @@ def parse_insights_row(
     M.4: se `breakdown_keys` for dado, os valores da dimensão do row são
     expostos em result["breakdown"] (ex: {"publisher_platform": "instagram"}).
     """
-    spend = float(row.get("spend") or 0)
-    clicks = int(row.get("clicks") or 0)
-    actions = row.get("actions")
-    action_values = row.get("action_values")
-
+    # As metricas saem do contrato (`metricas.py`), a unica leitura de metrica de
+    # linha Graph — ausente vira None, um nome por campo, ctr em fracao. Aqui so
+    # mora o desenho por nivel.
+    #
     # F89: `effective_status` NÃO é devolvido. Os F53/F54 o tiraram da query
     # (a Meta Insights o rejeita — é metadata de entidade, vive em /campaigns),
     # mas o parser seguia lendo, então saía "UNKNOWN"/"DESCONHECIDO" em 100% das
     # linhas. Campo constante é pior que campo ausente pra consumidor LLM: ele
     # relata como se fosse dado. Volta junto com o enriquecimento em 2 passos.
-    common: dict[str, Any] = {
-        "spend_brl": round(spend, 2),
-        "impressions": int(row.get("impressions") or 0),
-        "clicks": clicks,
-        "ctr": round(float(row.get("ctr") or 0) / 100, 4),  # Meta % → decimal
-        "cpc_brl": round(float(row.get("cpc") or 0), 4),
-        "reach": int(row.get("reach") or 0),
-        "frequency": round(float(row.get("frequency") or 0), 2),
-        "purchases": int(_extract_action_value(actions, "purchase")),
-        "purchases_value_brl": round(_extract_action_value(action_values, "purchase"), 2),
-        "purchase_roas": _extract_purchase_roas(row.get("purchase_roas")),
-        "leads": int(_extract_action_value(actions, "lead")),
-    }
+    common = metricas_da_linha(row)
 
     if level == "campaign":
         result: dict[str, Any] = {
```

`src/mcp/tools/_meta_performance.py`:

```diff
diff --git a/src/mcp/tools/_meta_performance.py b/src/mcp/tools/_meta_performance.py
index 3765cbf..add5974 100644
--- a/src/mcp/tools/_meta_performance.py
+++ b/src/mcp/tools/_meta_performance.py
@@ -26,6 +26,7 @@ from src.mcp.tools._meta_common import meta_error_message
 from src.meta_ads.account_clock import resolve_meta_account_today
 from src.meta_ads.account_overview import resolve_meta_date_window
 from src.meta_ads.insights import Level, build_insights_call, parse_insights_row
+from src.meta_ads.metricas import ATRIBUICAO
 from src.meta_ads.reports import run_meta_graph_get
 
 # F189: UMA página. O F88 lia 5 e cortava em `limit` depois — mas o mesmo F88
@@ -41,6 +42,17 @@ from src.meta_ads.reports import run_meta_graph_get
 _MAX_PAGES = 1
 
 
+def _gasto_para_ordenar(linha: dict[str, Any]) -> float:
+    """Chave do sort de seguranca: `spend_brl` pode vir None pelo contrato.
+
+    Nao acontece em linha com entrega (a Meta manda `spend` sempre que ha linha),
+    mas `None > float` estoura TypeError — e o sort e rede de seguranca, nao pode
+    ser ele a derrubar a resposta. None vai para o fim.
+    """
+    gasto = linha["spend_brl"]
+    return -1.0 if gasto is None else float(gasto)
+
+
 def meta_account_not_found_error(ad_account_id: str) -> dict[str, Any]:
     """Envelope de erro padrão quando `ad_account_id` não está em meta_ad_accounts.
 
@@ -133,7 +145,7 @@ async def run_meta_level_performance(
     # a 1ª página JÁ é o topo. O sort abaixo é rede de segurança idempotente
     # sobre dado já ordenado — o corte (`[:limit]`) é que precisa da garantia.
     rows = [parse_insights_row(r, level) for r in resp.get("data", [])]
-    rows.sort(key=lambda r: r["spend_brl"], reverse=True)
+    rows.sort(key=_gasto_para_ordenar, reverse=True)
     rows = rows[:limit]
 
     # Sobrou `paging.next` = há mais linhas ABAIXO do topo. Com o sort
@@ -147,6 +159,7 @@ async def run_meta_level_performance(
         "ad_account_name": account.account_name,
         "currency": account.currency,
         "date_range": {"start": start.isoformat(), "end": end.isoformat()},
+        "atribuicao": ATRIBUICAO,
         "rows": rows,
         "total_rows": len(rows),
         "truncated": truncated,
```

`src/mcp/tools/meta_get_performance_breakdown.py`:

```diff
diff --git a/src/mcp/tools/meta_get_performance_breakdown.py b/src/mcp/tools/meta_get_performance_breakdown.py
index c7a7d70..743f97f 100644
--- a/src/mcp/tools/meta_get_performance_breakdown.py
+++ b/src/mcp/tools/meta_get_performance_breakdown.py
@@ -14,7 +14,7 @@ from src.db import connection
 from src.db.repositories import meta_ad_accounts
 from src.mcp.context import get_current
 from src.mcp.tools._meta_common import meta_error_message
-from src.mcp.tools._meta_performance import _MAX_PAGES
+from src.mcp.tools._meta_performance import _MAX_PAGES, _gasto_para_ordenar
 from src.mcp.tools._registry import register_tool
 from src.meta_ads.account_clock import resolve_meta_account_today
 from src.meta_ads.account_overview import resolve_meta_date_window
@@ -24,6 +24,7 @@ from src.meta_ads.insights import (
     build_insights_call,
     parse_insights_row,
 )
+from src.meta_ads.metricas import ATRIBUICAO, CONTRATO_NA_DESCRIPTION
 from src.meta_ads.reports import run_meta_graph_get
 
 _DESCRIPTION = (
@@ -31,7 +32,9 @@ _DESCRIPTION = (
     "(Facebook/Instagram/Audience Network), device (iOS/Android/desktop), geo (país) "
     "ou hourly (hora do dia). level = campaign|adset|ad (default campaign). Métricas: "
     "spend, impressões, clicks, CTR, CPC, reach, frequency, purchases, purchase_roas, "
-    "leads. Cada row traz o valor da dimensão em `breakdown`. Ordenado por spend desc **no servidor**, entao o topo devolvido E o topo real da conta; `truncated:true` significa que ficou cauda de MENOR gasto de fora, nao que o ranking esteja incompleto. "
+    "leads, messaging_conversations_started (conversas iniciadas). "
+    "O breakdown hourly nao traz reach nem frequency: vem null. " + CONTRATO_NA_DESCRIPTION + " "
+    "Cada row traz o valor da dimensão em `breakdown`. Ordenado por spend desc **no servidor**, entao o topo devolvido E o topo real da conta; `truncated:true` significa que ficou cauda de MENOR gasto de fora, nao que o ranking esteja incompleto. "
     "1 breakdown por chamada. Use meta_list_my_ad_accounts pros IDs."
 )
 
@@ -172,7 +175,7 @@ async def meta_get_performance_breakdown(
     ]
     # F88: ordenação SERVER-SIDE (`sort=spend_descending`); este sort é rede de
     # segurança idempotente sobre dado já ordenado, e garante o corte abaixo.
-    rows.sort(key=lambda r: r["spend_brl"], reverse=True)
+    rows.sort(key=_gasto_para_ordenar, reverse=True)
     rows = rows[:limit]
     truncated = bool((resp.get("paging") or {}).get("next"))
 
@@ -184,6 +187,7 @@ async def meta_get_performance_breakdown(
         "level": level,
         "breakdown": breakdown,
         "date_range": {"start": start.isoformat(), "end": end.isoformat()},
+        "atribuicao": ATRIBUICAO,
         "rows": rows,
         "total_rows": len(rows),
         "truncated": truncated,
```

`src/mcp/tools/meta_get_campaign_performance.py`:

```diff
diff --git a/src/mcp/tools/meta_get_campaign_performance.py b/src/mcp/tools/meta_get_campaign_performance.py
index 61a0ca1..a7f4f90 100644
--- a/src/mcp/tools/meta_get_campaign_performance.py
+++ b/src/mcp/tools/meta_get_campaign_performance.py
@@ -11,10 +11,13 @@ from uuid import UUID
 from src.mcp.context import get_current
 from src.mcp.tools._meta_performance import run_meta_level_performance
 from src.mcp.tools._registry import register_tool
+from src.meta_ads.metricas import CONTRATO_NA_DESCRIPTION
 
 _DESCRIPTION = (
     "[CORE] Performance por campanha Meta Ads: spend, impressões, clicks, CTR, "
-    "CPC, reach, frequency, purchases, purchases_value_brl, purchase_roas, leads. "
+    "CPC, reach, frequency, purchases, purchases_value_brl, purchase_roas, leads, messaging_conversations_started (conversas iniciadas). "
+    + CONTRATO_NA_DESCRIPTION
+    + " "
     "Ordenado por spend desc **no servidor**, entao o topo devolvido E o topo real da conta; `truncated:true` significa que ficou cauda de MENOR gasto de fora, nao que o ranking esteja incompleto. Filtros: limit (max 500). "
     "Use meta_list_my_ad_accounts pra listar ad_account_ids disponíveis. "
     "[Limitação] Retorna campanhas de QUALQUER status (ACTIVE/PAUSED/ARCHIVED) e "
```

`src/mcp/tools/meta_get_ad_set_performance.py`:

```diff
diff --git a/src/mcp/tools/meta_get_ad_set_performance.py b/src/mcp/tools/meta_get_ad_set_performance.py
index 73cbe8c..3900d03 100644
--- a/src/mcp/tools/meta_get_ad_set_performance.py
+++ b/src/mcp/tools/meta_get_ad_set_performance.py
@@ -11,10 +11,13 @@ from uuid import UUID
 from src.mcp.context import get_current
 from src.mcp.tools._meta_performance import run_meta_level_performance
 from src.mcp.tools._registry import register_tool
+from src.meta_ads.metricas import CONTRATO_NA_DESCRIPTION
 
 _DESCRIPTION = (
     "[CORE] Performance por ad set Meta Ads: spend, impressões, clicks, CTR, "
-    "CPC, reach, frequency, purchases, purchases_value_brl, purchase_roas, leads. "
+    "CPC, reach, frequency, purchases, purchases_value_brl, purchase_roas, leads, messaging_conversations_started (conversas iniciadas). "
+    + CONTRATO_NA_DESCRIPTION
+    + " "
     "Inclui campaign_id/name parent + optimization_goal. Ordenado por spend desc **no servidor**, entao o topo devolvido E o topo real da conta; `truncated:true` significa que ficou cauda de MENOR gasto de fora, nao que o ranking esteja incompleto. "
     "Filtros: limit (max 500). "
     "[Limitação] Metadata de entidade (effective_status, billing_event, "
```

`src/mcp/tools/meta_get_ad_performance.py`:

```diff
diff --git a/src/mcp/tools/meta_get_ad_performance.py b/src/mcp/tools/meta_get_ad_performance.py
index 3286706..cb4eb47 100644
--- a/src/mcp/tools/meta_get_ad_performance.py
+++ b/src/mcp/tools/meta_get_ad_performance.py
@@ -11,11 +11,14 @@ from uuid import UUID
 from src.mcp.context import get_current
 from src.mcp.tools._meta_performance import run_meta_level_performance
 from src.mcp.tools._registry import register_tool
+from src.meta_ads.metricas import CONTRATO_NA_DESCRIPTION
 
 _DESCRIPTION = (
     "[CORE] Performance por anúncio (ad) Meta Ads: spend, impressões, clicks, "
-    "CTR, CPC, reach, frequency, purchases, purchases_value_brl, purchase_roas, "
-    "leads. Inclui ad_set_id/name + campaign_id/name parents. "
+    "CTR, CPC, reach, frequency, purchases, purchases_value_brl, purchase_roas, leads, messaging_conversations_started (conversas iniciadas). "
+    + CONTRATO_NA_DESCRIPTION
+    + " "
+    "Inclui ad_set_id/name + campaign_id/name parents. "
     "Ordenado por spend desc **no servidor**, entao o topo devolvido E o topo real da conta; `truncated:true` significa que ficou cauda de MENOR gasto de fora, nao que o ranking esteja incompleto. Filtros: limit (max 500). "
     "[Limitação] Metadata de entidade (effective_status, creative_id) NÃO vem: a "
     "Meta Insights API só serve métricas — esses campos vivem em /ads. Retorna "
```

- [ ] **Step 4: Ver passar**

Run: `python -m pytest tests/unit/test_meta_insights.py tests/unit/test_insights_no_phantom_fields.py tests/unit/test_meta_performance_core.py -p no:cacheprovider`
Expected: `37 passed` (22 + 7 + 8).

Com Docker de pé: `python -m pytest -m integration tests/integration/test_meta_get_campaign_performance.py -p no:cacheprovider` → verde. Sem Docker, o CI valida (anote no relatório).

- [ ] **Step 5: Gate** — `python scripts/check_pre_push.py`, mudo; `echo $?` → `0`.

- [ ] **Step 6: Provar a mordida do guard do F89 estendido (sabotagem por cópia)**

```bash
cp src/meta_ads/metricas.py .superpowers/metricas.py.bak
sed -i 's/linha.get("spend")/linha.get("unique_clicks")/' src/meta_ads/metricas.py
python -m pytest tests/unit/test_insights_no_phantom_fields.py -p no:cacheprovider
cp .superpowers/metricas.py.bak src/meta_ads/metricas.py
python -m pytest tests/unit/test_insights_no_phantom_fields.py -p no:cacheprovider
```

Expected: a 1ª rodada falha em `test_parser_nao_le_campo_que_a_query_nao_pede` com `F89 — leitor de linha le campo que a query nao pede: {'metricas.py::metricas_da_linha': ['unique_clicks']}` (e `test_metricas_reais_seguem_intactas` cai junto — `spend_brl` deixa de ser lido); a 2ª, `7 passed`. Confira `git diff --stat src/meta_ads/metricas.py` vazio depois da restauração.

- [ ] **Step 7: Commit**

```bash
git add src/meta_ads/insights.py src/mcp/tools/_meta_performance.py src/mcp/tools/meta_get_performance_breakdown.py src/mcp/tools/meta_get_campaign_performance.py src/mcp/tools/meta_get_ad_set_performance.py src/mcp/tools/meta_get_ad_performance.py tests/unit/test_meta_insights.py tests/unit/test_insights_no_phantom_fields.py tests/unit/test_meta_performance_core.py tests/integration/test_meta_get_campaign_performance.py
git commit -m "fix(meta_ads): trio e breakdown pelo contrato; atribuicao unificada no construtor unico"
```

---

### Task 3: O overview pelo contrato e pelo construtor

**Files:**
- Modify: `src/meta_ads/account_overview.py`, `src/mcp/tools/meta_get_account_overview.py`
- Test: `tests/unit/test_meta_account_overview.py`, `tests/integration/test_meta_get_account_overview.py`

**Interfaces:**
- Consumes: `metricas_da_linha`, `metricas_sem_linha`, `ATRIBUICAO`, `CONTRATO_NA_DESCRIPTION` (Task 1); `build_insights_call(level="account", ...)` (Task 2).
- Produces: `account_overview.DELTA_CAMPOS` (tupla de 8 campos); `parse_insights_response(data) -> dict[str, Any]` — as 12 chaves do contrato + `sem_dados_no_periodo`; `compute_deltas(current, previous) -> dict[str, float | None]`, chaves `f"{campo}_pct"`, `None` quando um lado é `None` ou o anterior é 0. **Saem** `CONVERSION_ACTION_TYPES`, `_sum_actions`, `_extract_purchase_roas`, `_to_float`, `_to_int`, `_empty_metrics` (sem consumidor fora do módulo — conferido por grep em `src/` e `tests/`).

**O que muda na resposta do overview** (a tool Meta mais usada, 161 chamadas em 30 dias; consumidor: só o LLM): as chaves passam às do trio (`spend_brl`, `cpc_brl`…); saem `conversions`/`conversion_value` (somavam recortes do mesmo evento); `ctr` passa a fração; cada período ganha `sem_dados_no_periodo`; a resposta ganha `atribuicao`; e as duas chamadas deixam de mandar `ad_account_id` à Graph API (o 03#10 que o índice dava por fechado).

- [ ] **Step 1: Escrever os testes**

`tests/unit/test_meta_account_overview.py` — as classes de `parse_insights_response` e `compute_deltas` afirmavam a regra que o spec revoga (zero para ausente, `ctr` em porcentagem, soma de seis nomes):

```diff
diff --git a/tests/unit/test_meta_account_overview.py b/tests/unit/test_meta_account_overview.py
index dc20345..ba0bb90 100644
--- a/tests/unit/test_meta_account_overview.py
+++ b/tests/unit/test_meta_account_overview.py
@@ -11,6 +11,7 @@ from src.meta_ads.account_overview import (
     resolve_meta_date_window,
     shift_to_previous_period,
 )
+from tests.unit._meta_formas_medidas import LINHA_COMPRA_E_LEAD, LINHA_SO_CONVERSAS
 
 TODAY = date(2026, 5, 25)
 
@@ -71,180 +72,80 @@ class TestShiftPreviousPeriod:
 
 
 class TestParseInsightsResponse:
-    """parse_insights_response tests."""
-
-    def test_parse_insights_empty_data(self):
-        result = parse_insights_response({"data": []})
-        assert result["spend"] == 0.0
-        assert result["impressions"] == 0
-        assert result["conversions"] == 0
-
-    def test_parse_insights_no_data_key(self):
-        result = parse_insights_response({})
-        assert result["spend"] == 0.0
-
-    def test_parse_insights_full_row(self):
-        data = {
-            "data": [
-                {
-                    "spend": "1234.56",
-                    "impressions": "45000",
-                    "clicks": "1200",
-                    "ctr": "2.67",
-                    "cpc": "1.03",
-                    "reach": "23000",
-                    "frequency": "1.95",
-                    "actions": [
-                        {"action_type": "purchase", "value": "35"},
-                        {"action_type": "link_click", "value": "1200"},  # NOT counted
-                        {"action_type": "lead", "value": "5"},
-                    ],
-                    "action_values": [
-                        {"action_type": "purchase", "value": "8400.0"},
-                        {"action_type": "link_click", "value": "0"},  # NOT counted
-                    ],
-                    "purchase_roas": [{"action_type": "omni_purchase", "value": "6.8"}],
-                }
-            ]
-        }
-        result = parse_insights_response(data)
-        assert result["spend"] == 1234.56
-        assert result["impressions"] == 45000
-        assert result["clicks"] == 1200
-        assert result["ctr"] == 2.67
-        assert result["cpc"] == 1.03
-        assert result["reach"] == 23000
-        assert result["frequency"] == 1.95
-        assert result["conversions"] == 40  # 35 purchase + 5 lead
-        assert result["conversion_value"] == 8400.0
-        assert result["purchase_roas"] == 6.8
-
-    def test_parse_insights_fb_pixel_action_types_counted(self):
-        """offsite_conversion.fb_pixel_* MUST be counted (Meta tracking)."""
-        data = {
-            "data": [
-                {
-                    "spend": "100",
-                    "actions": [
-                        {"action_type": "offsite_conversion.fb_pixel_purchase", "value": "10"},
-                        {"action_type": "offsite_conversion.fb_pixel_lead", "value": "3"},
-                    ],
-                }
-            ]
-        }
-        result = parse_insights_response(data)
-        assert result["conversions"] == 13
-
-    def test_parse_insights_missing_purchase_roas_returns_zero(self):
-        data = {"data": [{"spend": "100"}]}
-        result = parse_insights_response(data)
-        assert result["purchase_roas"] == 0.0
-
-    def test_parse_insights_null_values_handled(self):
-        """Meta às vezes retorna null pra fields ausentes."""
-        data = {"data": [{"spend": None, "impressions": None, "actions": None}]}
-        result = parse_insights_response(data)
-        assert result["spend"] == 0.0
-        assert result["impressions"] == 0
-        assert result["conversions"] == 0
-
-    def test_parse_insights_complete_register_action_type(self):
-        """complete_registration também é action_type countable."""
-        data = {
-            "data": [
-                {
-                    "spend": "100",
-                    "actions": [
-                        {"action_type": "complete_registration", "value": "8"},
-                    ],
-                }
-            ]
-        }
-        result = parse_insights_response(data)
-        assert result["conversions"] == 8
-
-    def test_parse_insights_multiple_roas_entries_first_purchase_wins(self):
-        """purchase_roas array pode ter múltiplas entradas, retorna primeira purchase/omni_purchase."""
-        data = {
-            "data": [
-                {
-                    "purchase_roas": [
-                        {"action_type": "link_click", "value": "1.5"},
-                        {"action_type": "purchase", "value": "4.2"},
-                        {"action_type": "omni_purchase", "value": "5.0"},
-                    ]
-                }
-            ]
-        }
-        result = parse_insights_response(data)
-        assert result["purchase_roas"] == 4.2  # purchase encontrado primeiro
+    """parse_insights_response — as metricas do periodo pelo contrato (spec 2026-09-26).
+
+    Os testes anteriores afirmavam a regra que o spec revoga: zero para campo ausente
+    (`conversions == 0`, `purchase_roas == 0.0`), `ctr` em porcentagem, e a SOMA de
+    seis nomes de conversao — que conta o mesmo evento varias vezes quando a Meta
+    devolve os recortes (medido: a mesma compra sob 5 nomes, o mesmo lead sob 7).
+    """
+
+    def test_sem_linha_entrega_zero_eventos_null_e_marcador(self):
+        """M7: sem entrega, a Meta nao manda linha — nao manda linha zerada."""
+        for data in ({"data": []}, {}):
+            result = parse_insights_response(data)
+            assert result["sem_dados_no_periodo"] is True
+            assert result["spend_brl"] == 0.0
+            assert result["impressions"] == 0
+            assert result["purchases"] is None
+            assert result["leads"] is None
+            assert result["ctr"] is None
+
+    def test_linha_medida_sai_pelo_contrato(self):
+        result = parse_insights_response({"data": [LINHA_COMPRA_E_LEAD]})
+        assert result["sem_dados_no_periodo"] is False
+        assert result["spend_brl"] == 22662.53
+        assert result["purchases"] == 10
+        assert result["leads"] == 13
+        assert result["messaging_conversations_started"] == 3531
+        assert result["ctr"] == 0.0178  # fracao, como o trio e o Google
+        assert result["purchase_roas"] is None  # M4: nao veio
+
+    def test_nao_ha_mais_soma_de_conversoes(self):
+        """`conversions`/`conversion_value` saem: somavam recortes do mesmo evento."""
+        result = parse_insights_response({"data": [LINHA_COMPRA_E_LEAD]})
+        assert "conversions" not in result
+        assert "conversion_value" not in result
+
+    def test_mesmas_chaves_do_trio(self):
+        """Um contrato so: o overview e o trio falam os mesmos nomes."""
+        from src.meta_ads.metricas import metricas_da_linha
+
+        result = parse_insights_response({"data": [LINHA_SO_CONVERSAS]})
+        assert set(result) == set(metricas_da_linha({})) | {"sem_dados_no_periodo"}
 
 
 class TestComputeDeltas:
-    """compute_deltas tests."""
+    """compute_deltas — por campo de DELTA_CAMPOS; null quando nao ha base ou medida."""
 
-    def test_compute_deltas_growth(self):
-        current = {"spend": 1200.0, "conversions": 40}
-        previous = {"spend": 1000.0, "conversions": 30}
+    def test_variacao_por_campo(self):
+        current = {"spend_brl": 1200.0, "purchases": 40}
+        previous = {"spend_brl": 1000.0, "purchases": 30}
         deltas = compute_deltas(current, previous)
-        assert deltas["spend_pct"] == 20.0
-        assert round(deltas["conversions_pct"], 2) == 33.33
-
-    def test_compute_deltas_decline(self):
-        current = {"spend": 800.0, "conversions": 25}
-        previous = {"spend": 1000.0, "conversions": 30}
-        deltas = compute_deltas(current, previous)
-        assert deltas["spend_pct"] == -20.0
-        assert round(deltas["conversions_pct"], 2) == -16.67
-
-    def test_compute_deltas_previous_zero_returns_none(self):
-        current = {"spend": 100.0, "conversions": 5}
-        previous = {"spend": 0.0, "conversions": 0}
-        deltas = compute_deltas(current, previous)
-        assert deltas["spend_pct"] is None
-        assert deltas["conversions_pct"] is None
-
-    def test_compute_deltas_missing_keys_zero(self):
-        current = {"spend": 100.0}
-        previous = {"spend": 50.0, "conversions": 10}
-        deltas = compute_deltas(current, previous)
-        assert deltas["spend_pct"] == 100.0
-        assert deltas["conversions_pct"] == -100.0
-
-    def test_compute_deltas_returns_all_expected_keys(self):
-        current = {
-            "spend": 100,
-            "impressions": 1000,
-            "clicks": 50,
-            "conversions": 5,
-            "conversion_value": 500,
-            "purchase_roas": 5.0,
-        }
-        previous = {
-            "spend": 100,
-            "impressions": 1000,
-            "clicks": 50,
-            "conversions": 5,
-            "conversion_value": 500,
-            "purchase_roas": 5.0,
-        }
-        deltas = compute_deltas(current, previous)
-        expected_keys = {
-            "spend_pct",
-            "impressions_pct",
-            "clicks_pct",
-            "conversions_pct",
-            "conversion_value_pct",
-            "purchase_roas_pct",
-        }
-        assert set(deltas.keys()) == expected_keys
-
-    def test_compute_deltas_zero_percent_change(self):
-        """Dados iguais → 0.0 não None."""
-        current = {"spend": 500.0}
-        previous = {"spend": 500.0}
-        deltas = compute_deltas(current, previous)
-        assert deltas["spend_pct"] == 0.0
+        assert deltas["spend_brl_pct"] == 20.0
+        assert deltas["purchases_pct"] == 33.33
+
+    def test_anterior_zero_da_null(self):
+        deltas = compute_deltas({"spend_brl": 100.0}, {"spend_brl": 0.0})
+        assert deltas["spend_brl_pct"] is None
+
+    def test_lado_nao_medido_da_null_nao_menos_cem(self):
+        """Antes, campo ausente contava como 0 e a variacao saia -100%."""
+        deltas = compute_deltas({"purchases": None}, {"purchases": 10})
+        assert deltas["purchases_pct"] is None
+        deltas = compute_deltas({}, {"leads": 10})
+        assert deltas["leads_pct"] is None
+
+    def test_iguais_dao_zero_nao_null(self):
+        deltas = compute_deltas({"spend_brl": 500.0}, {"spend_brl": 500.0})
+        assert deltas["spend_brl_pct"] == 0.0
+
+    def test_chaves_sao_as_de_delta_campos(self):
+        from src.meta_ads.account_overview import DELTA_CAMPOS
+
+        deltas = compute_deltas({}, {})
+        assert set(deltas) == {f"{c}_pct" for c in DELTA_CAMPOS}
+        assert "messaging_conversations_started_pct" in deltas
 
 
 class TestBuildWarnings:
```

`tests/integration/test_meta_get_account_overview.py` — fixture na forma medida, e os params que a tool manda à Graph API:

```diff
diff --git a/tests/integration/test_meta_get_account_overview.py b/tests/integration/test_meta_get_account_overview.py
index 5b50458..892b410 100644
--- a/tests/integration/test_meta_get_account_overview.py
+++ b/tests/integration/test_meta_get_account_overview.py
@@ -72,8 +72,8 @@ async def test_meta_get_account_overview_happy_path(db):
                 "cpc": "4.0",
                 "reach": "8000",
                 "frequency": "1.25",
-                "actions": [{"action_type": "purchase", "value": "40"}],
-                "action_values": [{"action_type": "purchase", "value": "8000"}],
+                "actions": [{"action_type": "omni_purchase", "value": "40"}],
+                "action_values": [{"action_type": "omni_purchase", "value": "8000"}],
                 "purchase_roas": [{"action_type": "omni_purchase", "value": "6.67"}],
             }
         ]
@@ -88,17 +88,15 @@ async def test_meta_get_account_overview_happy_path(db):
                 "cpc": "4.17",
                 "reach": "6500",
                 "frequency": "1.23",
-                "actions": [{"action_type": "purchase", "value": "30"}],
-                "action_values": [{"action_type": "purchase", "value": "6000"}],
+                "actions": [{"action_type": "omni_purchase", "value": "30"}],
+                "action_values": [{"action_type": "omni_purchase", "value": "6000"}],
                 "purchase_roas": [{"action_type": "omni_purchase", "value": "6.0"}],
             }
         ]
     }
 
-    with patch(
-        "src.mcp.tools.meta_get_account_overview.run_meta_graph_get",
-        new=AsyncMock(side_effect=[current_body, previous_body]),
-    ):
+    graph = AsyncMock(side_effect=[current_body, previous_body])
+    with patch("src.mcp.tools.meta_get_account_overview.run_meta_graph_get", new=graph):
         result = await meta_get_account_overview(
             manager_id=mid,
             session_id=uuid4(),
@@ -111,12 +109,25 @@ async def test_meta_get_account_overview_happy_path(db):
     assert result["account_name"] == "Test Account"
     assert result["account_status_label"] == "ATIVO"
     assert result["currency"] == "BRL"
-    assert result["current"]["spend"] == 1200.0
-    assert result["current"]["conversions"] == 40
+    # Spec 2026-09-26: os nomes do contrato (os do trio), conversao por evento.
+    assert result["current"]["spend_brl"] == 1200.0
+    assert result["current"]["purchases"] == 40
+    assert result["current"]["purchases_value_brl"] == 8000.0
     assert result["current"]["purchase_roas"] == 6.67
-    assert result["previous"]["spend"] == 1000.0
-    assert result["deltas"]["spend_pct"] == 20.0
-    assert result["deltas"]["conversions_pct"] == round((40 - 30) / 30 * 100, 2)
+    assert result["current"]["ctr"] == 0.03
+    assert result["current"]["leads"] is None
+    assert result["current"]["sem_dados_no_periodo"] is False
+    assert result["previous"]["spend_brl"] == 1000.0
+    assert result["deltas"]["spend_brl_pct"] == 20.0
+    assert result["deltas"]["purchases_pct"] == round((40 - 30) / 30 * 100, 2)
+    assert result["atribuicao"] == "unificada"
+    # As duas chamadas saem do construtor unico: atribuicao unificada, e sem o
+    # `ad_account_id` espurio que os params montados a mao mandavam (03#10).
+    for chamada in graph.await_args_list:
+        params = chamada.kwargs["params"]
+        assert params["use_unified_attribution_setting"] == "true"
+        assert params["level"] == "account"
+        assert "ad_account_id" not in params
     assert result["_warnings"] == []
     assert "date_range" in result
     assert result["date_range"]["start"] is not None
```

- [ ] **Step 2: Ver falhar**

Run: `python -m pytest tests/unit/test_meta_account_overview.py -p no:cacheprovider`
Expected (medido contra o código anterior): `9 failed, 19 passed` — `KeyError: 'sem_dados_no_periodo'` e as asserções de `conversions`/chaves nos 4 de `parse_insights_response`; `KeyError: 'spend_brl_pct'`/`'purchases_pct'` nos de variação; `ImportError: cannot import name 'DELTA_CAMPOS'` em `test_chaves_sao_as_de_delta_campos`. Os de `resolve_meta_date_window`, `shift_to_previous_period` e `build_warnings` seguem verdes.

- [ ] **Step 3: Implementar**

`src/meta_ads/account_overview.py`:

```diff
diff --git a/src/meta_ads/account_overview.py b/src/meta_ads/account_overview.py
index 8a98253..a65332c 100644
--- a/src/meta_ads/account_overview.py
+++ b/src/meta_ads/account_overview.py
@@ -6,16 +6,19 @@ Zero IO. Date math + Graph response parsing + deltas + warnings.
 from datetime import date, datetime, timedelta
 from typing import Any
 
-# Conversion actions a totalizar (cross-platform pattern com Google)
-CONVERSION_ACTION_TYPES = frozenset(
-    {
-        "purchase",
-        "lead",
-        "complete_registration",
-        "offsite_conversion.fb_pixel_purchase",
-        "offsite_conversion.fb_pixel_lead",
-        "offsite_conversion.fb_pixel_complete_registration",
-    }
+from src.meta_ads.metricas import metricas_da_linha, metricas_sem_linha
+
+# Os campos com variacao no comparativo (sufixo `_pct`). Os nomes sao os do
+# contrato (`metricas.py`), os mesmos do trio.
+DELTA_CAMPOS = (
+    "spend_brl",
+    "impressions",
+    "clicks",
+    "purchases",
+    "purchases_value_brl",
+    "leads",
+    "messaging_conversations_started",
+    "purchase_roas",
 )
 
 _PRESET_DAYS: dict[str, int] = {
@@ -59,51 +62,37 @@ def shift_to_previous_period(start: date, end: date) -> tuple[date, date]:
     return (prev_start, prev_end)
 
 
-def parse_insights_response(data: dict[str, Any]) -> dict[str, float | int]:
-    """Parse Graph /insights response → normalized metrics dict.
+def parse_insights_response(data: dict[str, Any]) -> dict[str, Any]:
+    """Resposta /insights de nivel `account` -> metricas do periodo, pelo contrato.
 
-    Empty/missing/null fields → 0.
+    Sem linha nenhuma (a Meta nao manda linha zerada: sem entrega, nao vem linha),
+    as metricas saem de `metricas_sem_linha` e `sem_dados_no_periodo` e True — o
+    que distingue "nao houve entrega" de uma linha medida com zero. E o contrato do
+    overview Google (F193), com uma diferenca deliberada: la as conversoes sem linha
+    sao 0; aqui os eventos sao None, porque a Meta nao diz se a conta os rastreia
+    (spec 2026-09-26, §3.4).
+    """
+    linhas = data.get("data") or []
+    if not linhas:
+        return {**metricas_sem_linha(), "sem_dados_no_periodo": True}
+    return {**metricas_da_linha(linhas[0]), "sem_dados_no_periodo": False}
+
+
+def compute_deltas(current: dict[str, Any], previous: dict[str, Any]) -> dict[str, float | None]:
+    """Variacao percentual por campo de `DELTA_CAMPOS`, com sufixo `_pct`.
+
+    None quando um dos lados e None (nao medido) ou o anterior e 0 (sem base).
+    Campo ausente do dict conta como nao medido — antes contava como 0 e virava
+    -100%.
     """
-    rows = data.get("data") or []
-    if not rows:
-        return _empty_metrics()
-    row = rows[0]
-    actions = _sum_actions(row.get("actions") or [], CONVERSION_ACTION_TYPES)
-    action_values = _sum_actions(row.get("action_values") or [], CONVERSION_ACTION_TYPES)
-    return {
-        "spend": _to_float(row.get("spend")),
-        "impressions": _to_int(row.get("impressions")),
-        "clicks": _to_int(row.get("clicks")),
-        "ctr": _to_float(row.get("ctr")),
-        "cpc": _to_float(row.get("cpc")),
-        "reach": _to_int(row.get("reach")),
-        "frequency": _to_float(row.get("frequency")),
-        "conversions": int(actions),
-        "conversion_value": float(action_values),
-        "purchase_roas": _extract_purchase_roas(row.get("purchase_roas") or []),
-    }
-
-
-def compute_deltas(
-    current: dict[str, float | int], previous: dict[str, float | int]
-) -> dict[str, float | None]:
-    """Returns dict with `_pct` suffix per metric. None if previous=0."""
     out: dict[str, float | None] = {}
-    for key in (
-        "spend",
-        "impressions",
-        "clicks",
-        "conversions",
-        "conversion_value",
-        "purchase_roas",
-    ):
-        prev_val = previous.get(key, 0)
-        curr_val = current.get(key, 0)
-        if prev_val == 0:
+    for key in DELTA_CAMPOS:
+        prev_val = previous.get(key)
+        curr_val = current.get(key)
+        if prev_val is None or curr_val is None or prev_val == 0:
             out[f"{key}_pct"] = None
         else:
-            pct = round((curr_val - prev_val) / prev_val * 100, 2)
-            out[f"{key}_pct"] = pct
+            out[f"{key}_pct"] = round((curr_val - prev_val) / prev_val * 100, 2)
     return out
 
 
@@ -129,52 +118,3 @@ def build_warnings(
                 f"Reconectar via /admin → 'Conectar Meta' pra evitar interrupção das tools."
             )
     return out
-
-
-# ============================================================================
-# Helpers (module-private)
-# ============================================================================
-
-
-def _sum_actions(actions: list[dict[str, Any]], filter_types: frozenset[str]) -> float:
-    return sum(_to_float(a.get("value")) for a in actions if a.get("action_type") in filter_types)
-
-
-def _extract_purchase_roas(roas_arr: list[dict[str, Any]]) -> float:
-    for entry in roas_arr:
-        if entry.get("action_type") in ("purchase", "omni_purchase"):
-            return _to_float(entry.get("value"))
-    return 0.0
-
-
-def _to_float(v: Any) -> float:
-    if v is None:
-        return 0.0
-    try:
-        return float(v)
-    except (TypeError, ValueError):
-        return 0.0
-
-
-def _to_int(v: Any) -> int:
-    if v is None:
-        return 0
-    try:
-        return int(float(v))
-    except (TypeError, ValueError):
-        return 0
-
-
-def _empty_metrics() -> dict[str, float | int]:
-    return {
-        "spend": 0.0,
-        "impressions": 0,
-        "clicks": 0,
-        "ctr": 0.0,
-        "cpc": 0.0,
-        "reach": 0,
-        "frequency": 0.0,
-        "conversions": 0,
-        "conversion_value": 0.0,
-        "purchase_roas": 0.0,
-    }
```

`src/mcp/tools/meta_get_account_overview.py`:

```diff
diff --git a/src/mcp/tools/meta_get_account_overview.py b/src/mcp/tools/meta_get_account_overview.py
index 2b4e289..0c0111f 100644
--- a/src/mcp/tools/meta_get_account_overview.py
+++ b/src/mcp/tools/meta_get_account_overview.py
@@ -24,15 +24,21 @@ from src.meta_ads.account_overview import (
     resolve_meta_date_window,
     shift_to_previous_period,
 )
+from src.meta_ads.insights import build_insights_call
 from src.meta_ads.labels import META_ACCOUNT_STATUS_LABELS
+from src.meta_ads.metricas import ATRIBUICAO, CONTRATO_NA_DESCRIPTION
 from src.meta_ads.reports import run_meta_graph_get
 
 log = structlog.get_logger(__name__)
 
 _DESCRIPTION = (
-    "[CORE] Overview de uma conta Meta Ads: métricas essenciais (spend, impressões, clicks, "
-    "CTR, CPC, reach, frequency, conversões, conversion_value, purchase_roas) "
-    "para o período selecionado com comparativo do período anterior de mesma duração. "
+    "[CORE] Overview de uma conta Meta Ads: métricas essenciais (spend_brl, impressões, "
+    "clicks, CTR, cpc_brl, reach, frequency, purchases, purchases_value_brl, purchase_roas, "
+    "leads, messaging_conversations_started) para o período selecionado com comparativo "
+    "do período anterior de mesma duração. Conversoes saem por evento (compras, leads, "
+    "conversas iniciadas), nunca somadas: a mesma compra vem sob varios nomes na Meta. "
+    "Cada periodo traz sem_dados_no_periodo: true quando a Meta nao devolveu linha "
+    "(sem entrega). " + CONTRATO_NA_DESCRIPTION + " "
     "Inclui warnings PT-BR pra account_status problemático. "
     "Requer conexão Meta ativa (gestor deve ter conectado via /oauth/meta/start). "
     "Use meta_list_my_ad_accounts pra listar IDs disponíveis."
@@ -125,7 +131,24 @@ async def meta_get_account_overview(
         account.account_status or 0, "DESCONHECIDO"
     )
 
-    fields = "spend,impressions,clicks,ctr,cpc,reach,frequency,actions,action_values,purchase_roas"
+    # Spec 2026-09-26 §4.2: as duas chamadas saem do construtor unico — os mesmos
+    # campos do trio, a atribuicao unificada, e sem o `ad_account_id` espurio que os
+    # params montados a mao mandavam para a Graph API (o indice da varredura dava o
+    # 03#10 como fechado pelo F190; nao estava).
+    edge, params_atual = build_insights_call(
+        level="account",
+        ad_account_id=ad_account_id,
+        start=current_start,
+        end=current_end,
+        limit=1,
+    )
+    _, params_anterior = build_insights_call(
+        level="account",
+        ad_account_id=ad_account_id,
+        start=prev_start,
+        end=prev_end,
+        limit=1,
+    )
 
     # 3. Two Graph API calls: current period + previous period
     try:
@@ -133,15 +156,8 @@ async def meta_get_account_overview(
             manager_id=manager_id,
             session_id=session_id,
             ad_account_id=ad_account_id,
-            edge=f"/{ad_account_id}/insights",
-            params={
-                "fields": fields,
-                "time_range": (
-                    f'{{"since":"{current_start.isoformat()}","until":"{current_end.isoformat()}"}}'
-                ),
-                "level": "account",
-                "ad_account_id": ad_account_id,
-            },
+            edge=edge,
+            params=params_atual,
             operation_name="meta_get_account_overview",
             estimated_calls=1,
             audit_this_call=True,
@@ -157,15 +173,8 @@ async def meta_get_account_overview(
             manager_id=manager_id,
             session_id=session_id,
             ad_account_id=ad_account_id,
-            edge=f"/{ad_account_id}/insights",
-            params={
-                "fields": fields,
-                "time_range": (
-                    f'{{"since":"{prev_start.isoformat()}","until":"{prev_end.isoformat()}"}}'
-                ),
-                "level": "account",
-                "ad_account_id": ad_account_id,
-            },
+            edge=edge,
+            params=params_anterior,
             operation_name="meta_get_account_overview",
             estimated_calls=1,
             audit_this_call=False,
@@ -195,6 +204,7 @@ async def meta_get_account_overview(
             "start": current_start.isoformat(),
             "end": current_end.isoformat(),
         },
+        "atribuicao": ATRIBUICAO,
         "current": current_metrics,
         "previous": previous_metrics,
         "deltas": deltas,
```

- [ ] **Step 4: Ver passar**

Run: `python -m pytest tests/unit/test_meta_account_overview.py -p no:cacheprovider`
Expected: `28 passed`.

Com Docker: `python -m pytest -m integration tests/integration/test_meta_get_account_overview.py -p no:cacheprovider` → verde.

- [ ] **Step 5: Gate** — `python scripts/check_pre_push.py`, mudo; `echo $?` → `0`.

- [ ] **Step 6: Commit**

```bash
git add src/meta_ads/account_overview.py src/mcp/tools/meta_get_account_overview.py tests/unit/test_meta_account_overview.py tests/integration/test_meta_get_account_overview.py
git commit -m "fix(meta_ads): overview pelo contrato e pelo construtor unico"
```

---

### Task 4: O sinal BUC

**Files:**
- Modify: `src/governance/rate_limit.py`, `src/meta_ads/reports.py`
- Create: `tests/unit/test_meta_buc_registro.py`
- Test: `tests/unit/test_buc_header_parsing.py`, `tests/unit/test_meta_reports_executor.py`

**Interfaces:**
- Consumes: nada das tasks anteriores (independente).
- Produces: `_parse_buc_header_pct(buc_header: str | None, *, ad_account_id: str) -> int | None`; `_parse_insights_throttle(header: str | None) -> dict[str, float] | None`; `record_actual_meta(*, app_id: str, ad_account_id: str, buc_header: str | None, insights_throttle_header: str | None = None, calls: int = 1) -> None`. Eventos: `meta_buc_nao_lido` (WARNING, `motivo` = `ausente` | `nao_entendido`) e `meta_rate_limit_warning` (WARNING, `acima_de_75` = dict dos sinais medidos acima de 75).

**Por que `meta_buc_nao_lido` é WARNING, não info:** é o único sinal que avisa que o token COMPARTILHADO vai ser limitado, e em 26/09 ele veio em toda chamada `/insights` medida — ausente ou ilegível é anomalia. (Medido também: um teste da suíte deixa o structlog global acima de `info`; um evento `info` sumiria da captura na suíte inteira e passaria isolado. A decisão de nível é pela semântica — o efeito no teste é consequência, não motivo.)

- [ ] **Step 1: Escrever os testes**

`tests/unit/test_buc_header_parsing.py` — os quatro `== 0` afirmavam a regra revogada:

```diff
diff --git a/tests/unit/test_buc_header_parsing.py b/tests/unit/test_buc_header_parsing.py
index 3808706..7aef3ad 100644
--- a/tests/unit/test_buc_header_parsing.py
+++ b/tests/unit/test_buc_header_parsing.py
@@ -1,8 +1,13 @@
-"""Unit tests for BUC (X-Business-Use-Case-Usage) header parsing (Sprint M.2a Task 7)."""
+"""Unit tests for BUC (X-Business-Use-Case-Usage) header parsing (Sprint M.2a Task 7).
+
+Spec 2026-09-26 §5: "nao sei" e `None`, nunca `0`. Os quatro testes de vazio/
+malformado/sem a conta afirmavam `== 0` — a regra que o spec revoga: o 0 era
+indistinguivel de conta ociosa e sobrescrevia o ultimo valor medido.
+"""
 
 import json
 
-from src.governance.rate_limit import _parse_buc_header_pct
+from src.governance.rate_limit import _parse_buc_header_pct, _parse_insights_throttle
 
 
 def test_parse_buc_extracts_max_pct():
@@ -24,27 +29,27 @@ def test_parse_buc_extracts_max_pct():
     assert pct == 42  # max(42, 12, 35)
 
 
-def test_parse_buc_returns_zero_when_account_not_in_header():
+def test_parse_buc_returns_none_when_account_not_in_header():
     header = json.dumps(
         {"999": [{"type": "ads_read", "call_count": 50, "total_cputime": 0, "total_time": 0}]}
     )
     pct = _parse_buc_header_pct(header, ad_account_id="act_111")
-    assert pct == 0
+    assert pct is None
 
 
 def test_parse_buc_handles_empty_header():
     pct = _parse_buc_header_pct("", ad_account_id="act_123")
-    assert pct == 0
+    assert pct is None
 
 
 def test_parse_buc_handles_empty_json():
     pct = _parse_buc_header_pct("{}", ad_account_id="act_123")
-    assert pct == 0
+    assert pct is None
 
 
 def test_parse_buc_handles_malformed_json():
     pct = _parse_buc_header_pct("not valid json", ad_account_id="act_123")
-    assert pct == 0
+    assert pct is None
 
 
 def test_parse_buc_strips_act_prefix():
@@ -66,3 +71,38 @@ def test_parse_buc_multiple_usage_entries():
     )
     pct = _parse_buc_header_pct(header, ad_account_id="act_123")
     assert pct == 90
+
+
+def test_parse_buc_handles_none_header():
+    assert _parse_buc_header_pct(None, ad_account_id="act_123") is None
+
+
+def test_parse_buc_zero_medido_segue_zero():
+    """Null e so para o que nao veio: 0% medido continua 0."""
+    header = json.dumps({"123": [{"call_count": 0, "total_cputime": 0, "total_time": 0}]})
+    assert _parse_buc_header_pct(header, ad_account_id="act_123") == 0
+
+
+# ============================================================================
+# x-fb-ads-insights-throttle — onde vem a quota do APP em chamada /insights
+# ============================================================================
+
+
+def test_insights_throttle_forma_medida():
+    """Forma medida em 26/09 (`scripts/probe_meta_metricas.py`)."""
+    header = (
+        '{"app_id_util_pct":0.02,"acc_id_util_pct":0,"ads_api_access_tier":"development_access"}'
+    )
+    assert _parse_insights_throttle(header) == {"app_id_util_pct": 0.02, "acc_id_util_pct": 0.0}
+
+
+def test_insights_throttle_ausente_ou_malformado_e_none():
+    assert _parse_insights_throttle(None) is None
+    assert _parse_insights_throttle("") is None
+    assert _parse_insights_throttle("nao json") is None
+    assert _parse_insights_throttle("[1, 2]") is None
+    assert _parse_insights_throttle('{"ads_api_access_tier": "x"}') is None
+
+
+def test_insights_throttle_so_devolve_o_que_veio():
+    assert _parse_insights_throttle('{"app_id_util_pct": 81}') == {"app_id_util_pct": 81.0}
```

`tests/unit/test_meta_buc_registro.py` (novo):

```python
"""`record_actual_meta` registra so o MEDIDO (spec 2026-09-26, §5).

Antes: BUC nao entendido virava `throttle_pct=0`, gravado por cima do ultimo valor
medido — e o aviso de 75% nunca disparava sobre o que nao se leu. A quota do app, que
em chamada /insights vem no `x-fb-ads-insights-throttle`, nao era lida.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from structlog.testing import capture_logs

from src.governance import rate_limit


class _FakeAcquire:
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, *exc: object) -> None:
        return None


class _FakePool:
    def acquire(self) -> _FakeAcquire:
        return _FakeAcquire()


async def _registrar(**kwargs: Any) -> tuple[AsyncMock, AsyncMock, list[dict[str, Any]]]:
    incrementa, atualiza = AsyncMock(), AsyncMock()
    with (
        patch("src.db.connection.get_pool", return_value=_FakePool()),
        patch("src.db.repositories.meta_rate_counters.increment_calls", incrementa),
        patch("src.db.repositories.meta_rate_counters.update_throttle", atualiza),
        capture_logs() as logs,
    ):
        await rate_limit.record_actual_meta(app_id="app", ad_account_id="act_123", **kwargs)
    return incrementa, atualiza, logs


def _buc(pct: int) -> str:
    return json.dumps({"123": [{"call_count": pct, "total_cputime": 1, "total_time": 1}]})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("header", "motivo"),
    [(None, "ausente"), ("nao json", "nao_entendido"), ("{}", "nao_entendido")],
)
async def test_buc_nao_lido_nao_grava_throttle(header: str | None, motivo: str) -> None:
    """O ultimo valor medido fica; o que nao se leu vira evento, nao 0."""
    incrementa, atualiza, logs = await _registrar(buc_header=header)
    incrementa.assert_awaited_once()  # a chamada aconteceu e conta
    atualiza.assert_not_awaited()
    evento = next(e for e in logs if e["event"] == "meta_buc_nao_lido")
    assert evento["motivo"] == motivo


@pytest.mark.asyncio
async def test_buc_lido_grava_o_medido() -> None:
    _, atualiza, logs = await _registrar(buc_header=_buc(42))
    assert atualiza.await_args.kwargs["throttle_pct"] == 42
    assert not [e for e in logs if e["event"] == "meta_rate_limit_warning"]


@pytest.mark.asyncio
async def test_quota_do_app_acima_de_75_avisa_e_diz_qual() -> None:
    """F110: a quota que barra e a que tem menos folga — o aviso nomeia qual."""
    throttle = '{"app_id_util_pct": 80, "acc_id_util_pct": 3}'
    _, _, logs = await _registrar(buc_header=_buc(10), insights_throttle_header=throttle)
    aviso = next(e for e in logs if e["event"] == "meta_rate_limit_warning")
    assert aviso["acima_de_75"] == {"app_id_util_pct": 80.0}


@pytest.mark.asyncio
async def test_buc_da_conta_acima_de_75_segue_avisando() -> None:
    _, _, logs = await _registrar(buc_header=_buc(90))
    aviso = next(e for e in logs if e["event"] == "meta_rate_limit_warning")
    assert aviso["acima_de_75"] == {"buc_conta_pct": 90.0}
```

`tests/unit/test_meta_reports_executor.py`:

```diff
diff --git a/tests/unit/test_meta_reports_executor.py b/tests/unit/test_meta_reports_executor.py
index 912780e..eb1dad5 100644
--- a/tests/unit/test_meta_reports_executor.py
+++ b/tests/unit/test_meta_reports_executor.py
@@ -137,6 +137,8 @@ async def test_run_meta_graph_get_happy_path_parses_and_audits() -> None:
     rate_kwargs = mock_record_actual_meta.call_args.kwargs
     assert rate_kwargs["ad_account_id"] == "act_999"
     assert rate_kwargs["buc_header"] == '{"999": [{"call_count": 5}]}'
+    # spec 2026-09-26 §5: o cabecalho da quota do app vai junto; aqui nao veio.
+    assert rate_kwargs["insights_throttle_header"] is None
     assert rate_kwargs["calls"] == 1
 
 
@@ -184,7 +186,7 @@ async def test_run_meta_graph_get_records_buc_even_without_ad_account_id_in_para
 
 @pytest.mark.asyncio
 async def test_run_meta_graph_get_skips_rate_counter_when_buc_header_absent() -> None:
-    """Resposta sem o header BUC (edge fora de /insights, por ex.) → record_actual_meta NÃO chamado."""
+    """Resposta sem NENHUM dos dois cabecalhos de uso → record_actual_meta NÃO chamado."""
     mid, sid = uuid4(), uuid4()
     fake_pool = _patch_allowed_pool()
 
@@ -339,3 +341,46 @@ async def test_run_meta_graph_get_raises_when_system_user_token_missing() -> Non
             params={"level": "campaign"},
             operation_name="meta_get_campaign_performance",
         )
+
+
+@pytest.mark.asyncio
+async def test_run_meta_graph_get_registra_quando_so_a_quota_do_app_vem() -> None:
+    """Spec 2026-09-26 §5: a quota do APP vem no `x-fb-ads-insights-throttle`.
+
+    Antes, sem o BUC o registro nem era chamado — e a unica leitura da quota do app
+    ficava de fora. O BUC ausente segue "nao sei" (quem decide e o registro).
+    """
+    mid, sid = uuid4(), uuid4()
+    fake_pool = _patch_allowed_pool()
+    throttle = '{"app_id_util_pct":0.02,"acc_id_util_pct":0}'
+
+    def handler(_request: httpx.Request) -> httpx.Response:
+        return httpx.Response(
+            200, json={"data": []}, headers={"x-fb-ads-insights-throttle": throttle}
+        )
+
+    mock_record_actual_meta = AsyncMock()
+
+    with (
+        patch.object(reports.connection, "get_pool", return_value=fake_pool),
+        patch.object(
+            reports.manager_meta_account_access,
+            "can_manager_access",
+            AsyncMock(return_value=True),
+        ),
+        patch.object(reports.httpx, "AsyncClient", MagicMock(return_value=_cliente_httpx(handler))),
+        patch.object(reports, "record_actual_meta", mock_record_actual_meta),
+    ):
+        await reports.run_meta_graph_get(
+            manager_id=mid,
+            session_id=sid,
+            ad_account_id="act_111",
+            edge="/act_111/insights",
+            params={},
+            operation_name="meta_get_campaign_performance",
+        )
+
+    mock_record_actual_meta.assert_awaited_once()
+    kwargs = mock_record_actual_meta.call_args.kwargs
+    assert kwargs["insights_throttle_header"] == throttle
+    assert kwargs["buc_header"] is None
```

- [ ] **Step 2: Ver falhar**

Run: `python -m pytest tests/unit/test_buc_header_parsing.py tests/unit/test_meta_buc_registro.py tests/unit/test_meta_reports_executor.py -p no:cacheprovider`
Expected (medido contra o código anterior): coleta de `test_buc_header_parsing.py` quebra em `ImportError: cannot import name '_parse_insights_throttle'`; em `test_meta_buc_registro.py`, os três `test_buc_nao_lido_nao_grava_throttle[...]` falham com `Expected mock to not have been awaited. Awaited 1 times.` — o código anterior grava 0 —, `test_buc_lido_grava_o_medido` **passa** (controle: o caminho medido não muda), o de quota do app falha com `TypeError` (o parâmetro não existe) e o do BUC acima de 75 com `KeyError: 'acima_de_75'`; no executor, `KeyError: 'insights_throttle_header'` e o teste novo com `Expected mock to have been awaited once. Awaited 0 times.`

- [ ] **Step 3: Implementar**

`src/governance/rate_limit.py`:

```diff
diff --git a/src/governance/rate_limit.py b/src/governance/rate_limit.py
index 06942cd..308d3cc 100644
--- a/src/governance/rate_limit.py
+++ b/src/governance/rate_limit.py
@@ -11,6 +11,7 @@ parallel callers don't double-count. Each function takes a single
 asyncpg connection and runs in one transaction.
 """
 
+import json
 from datetime import UTC, datetime
 from typing import NamedTuple
 
@@ -170,27 +171,29 @@ def hash_developer_token(token: str) -> str:
 # ============================================================================
 
 
-def _parse_buc_header_pct(buc_header: str, *, ad_account_id: str) -> int:
+def _parse_buc_header_pct(buc_header: str | None, *, ad_account_id: str) -> int | None:
     """Parse X-Business-Use-Case-Usage header + return max usage pct for ad_account.
 
-    BUC format: {"<numeric_ad_account_id>": [{"type":"ads_management",
+    BUC format: {"<numeric_ad_account_id>": [{"type":"ads_insights",
                   "call_count": 42, "total_cputime": 12, "total_time": 35,
                   "estimated_time_to_regain_access": 0}]}
 
     Strategy: max(call_count, total_cputime, total_time) across all entries
-    for the matching ad_account. Returns 0 if header empty/malformed/no-match.
+    for the matching ad_account.
+
+    Spec 2026-09-26 §5: cabecalho vazio, JSON malformado, nao-dict ou sem a chave da
+    conta devolve **None** — "nao sei", nunca `0`. O `0` antigo era indistinguivel de
+    uma conta ociosa e sobrescrevia o ultimo valor medido.
     """
     if not buc_header:
-        return 0
+        return None
     try:
-        import json
-
         parsed = json.loads(buc_header)
     except (ValueError, TypeError):
-        return 0
+        return None
 
     if not isinstance(parsed, dict):
-        return 0
+        return None
 
     numeric_id = ad_account_id.replace("act_", "")
     pcts: list[int] = []
@@ -209,20 +212,49 @@ def _parse_buc_header_pct(buc_header: str, *, ad_account_id: str) -> int:
                     int(u.get("total_time", 0)),
                 ]
             )
-    return max(pcts) if pcts else 0
+    return max(pcts) if pcts else None
+
+
+def _parse_insights_throttle(header: str | None) -> dict[str, float] | None:
+    """Parse X-FB-Ads-Insights-Throttle -> {"app_id_util_pct": x, "acc_id_util_pct": y}.
+
+    Medido em 26/09 (`scripts/probe_meta_metricas.py`): em chamada /insights o
+    `x-app-usage` NAO vem; a quota do APP vem aqui, junto da da conta. Devolve so os
+    dois campos numericos que vierem; nenhum, ou cabecalho ausente/malformado -> None.
+    """
+    if not header:
+        return None
+    try:
+        parsed = json.loads(header)
+    except (ValueError, TypeError):
+        return None
+    if not isinstance(parsed, dict):
+        return None
+    sinais: dict[str, float] = {}
+    for chave in ("app_id_util_pct", "acc_id_util_pct"):
+        valor = parsed.get(chave)
+        if isinstance(valor, int | float) and not isinstance(valor, bool):
+            sinais[chave] = float(valor)
+    return sinais or None
 
 
 async def record_actual_meta(
     *,
     app_id: str,
     ad_account_id: str,
-    buc_header: str,
+    buc_header: str | None,
+    insights_throttle_header: str | None = None,
     calls: int = 1,
 ) -> None:
-    """Parse BUC header + persist counter increments + throttle pct.
+    """Conta as chamadas e registra o uso medido — so o MEDIDO.
+
+    Spec 2026-09-26 §5: BUC nao lido nao grava nada no `last_throttle_pct` (o ultimo
+    valor medido fica) e vira o evento `meta_buc_nao_lido`. O aviso
+    `meta_rate_limit_warning` dispara quando QUALQUER sinal medido passa de 75% — o
+    BUC da conta, ou a quota do app/conta do `x-fb-ads-insights-throttle` — e diz
+    quais: a quota que barra e a que tem menos folga (F110).
 
     Hashes app_id (SHA-256 truncated 32-char) before persisting for storage privacy.
-    Structlog warning if throttle_pct > 75%.
     """
     import hashlib
     from datetime import date
@@ -231,6 +263,7 @@ async def record_actual_meta(
     from src.db.repositories import meta_rate_counters
 
     throttle_pct = _parse_buc_header_pct(buc_header, ad_account_id=ad_account_id)
+    insights = _parse_insights_throttle(insights_throttle_header)
     app_id_hash = hashlib.sha256(app_id.encode()).hexdigest()[:32]
     today = date.today()
 
@@ -243,17 +276,32 @@ async def record_actual_meta(
             date=today,
             by=calls,
         )
-        await meta_rate_counters.update_throttle(
-            conn,
-            app_id=app_id_hash,
+        if throttle_pct is not None:
+            await meta_rate_counters.update_throttle(
+                conn,
+                app_id=app_id_hash,
+                ad_account_id=ad_account_id,
+                date=today,
+                throttle_pct=throttle_pct,
+            )
+
+    if throttle_pct is None:
+        # WARNING, nao info: e o unico sinal que avisa que o token COMPARTILHADO vai
+        # ser limitado, e em 26/09 ele veio em toda chamada /insights medida — ausente
+        # ou ilegivel e anomalia (formato mudou), nao rotina.
+        log.warning(
+            "meta_buc_nao_lido",
             ad_account_id=ad_account_id,
-            date=today,
-            throttle_pct=throttle_pct,
+            motivo="ausente" if not buc_header else "nao_entendido",
         )
 
-    if throttle_pct > 75:
+    medidos: dict[str, float] = dict(insights or {})
+    if throttle_pct is not None:
+        medidos["buc_conta_pct"] = float(throttle_pct)
+    acima = {nome: valor for nome, valor in medidos.items() if valor > 75}
+    if acima:
         log.warning(
             "meta_rate_limit_warning",
             ad_account_id=ad_account_id,
-            throttle_pct=throttle_pct,
+            acima_de_75=acima,
         )
```

`src/meta_ads/reports.py`:

```diff
diff --git a/src/meta_ads/reports.py b/src/meta_ads/reports.py
index 8864a7c..a17e1eb 100644
--- a/src/meta_ads/reports.py
+++ b/src/meta_ads/reports.py
@@ -306,13 +306,20 @@ async def run_meta_graph_get(
     # params.get("ad_account_id"), que era um passthrough espúrio só existindo
     # pra alimentar este contador (Task 3.4: desacopla o BUC do dict de params
     # do Graph, que agora pode perder essa chave sem quebrar o rate counter).
+    #
+    # Spec 2026-09-26 §5: le tambem o `x-fb-ads-insights-throttle`, onde vem a quota
+    # do APP em chamada /insights (o `x-app-usage` nao vem ali — medido). Registra se
+    # QUALQUER dos dois vier: a chamada aconteceu e conta, e o que nao veio e "nao
+    # sei", nunca 0.
     buc_header = headers_ultima.get("x-business-use-case-usage")
-    if buc_header:
+    throttle_insights = headers_ultima.get("x-fb-ads-insights-throttle")
+    if buc_header or throttle_insights:
         try:
             await record_actual_meta(
                 app_id=settings.meta_app_id,
                 ad_account_id=ad_account_id,
                 buc_header=buc_header,
+                insights_throttle_header=throttle_insights,
                 # F88: contabiliza as chamadas REALMENTE feitas, não a estimativa.
                 calls=max(estimated_calls, paginas_lidas),
             )
```

- [ ] **Step 4: Ver passar**

Run: `python -m pytest tests/unit/test_buc_header_parsing.py tests/unit/test_meta_buc_registro.py tests/unit/test_meta_reports_executor.py -p no:cacheprovider`
Expected: `25 passed` (12 + 6 + 7).

- [ ] **Step 5: Gate** — `python scripts/check_pre_push.py`, mudo; `echo $?` → `0`. **Aqui a suíte inteira importa**, não só os três arquivos: foi nela que o nível do log apareceu.

- [ ] **Step 6: Commit**

```bash
git add src/governance/rate_limit.py src/meta_ads/reports.py tests/unit/test_buc_header_parsing.py tests/unit/test_meta_buc_registro.py tests/unit/test_meta_reports_executor.py
git commit -m "fix(governance): BUC nao lido nao vira 0; le a quota do app do x-fb-ads-insights-throttle"
```

---

### Task 5: Os guards do contrato

**Files:**
- Create: `tests/unit/test_meta_metricas_guards.py`

**Interfaces:**
- Consumes: `FRASE_DO_NULL`, `FRASE_DO_CTR`, `FRASE_DA_ATRIBUICAO` (Task 1); o estado das tasks 2 e 3 (é ele que os guards protegem); o harness `tests/unit/_guard_harness.py` (`fontes_py`, `arvore`, `rel`, `_nos_de_docstring`, `_literais_de_string`, `_texto_logico`, `SRC`, `RAIZ`).
- Produces: três guards — (1) só `metricas.py` lê chave de métrica de linha Graph; (2) só `build_insights_call` monta o literal `/insights` fora de docstring; (3) toda tool que chega ao contrato pelo grafo de import (as 5, medido) carrega as três frases na description.

**Estes guards nascem verdes** — as tasks 2 e 3 já fizeram o trabalho. Guard que passa ao nascer prova-se por sabotagem em cópia (Step 3). Contra o código ANTERIOR às tasks 2 e 3 os dois estruturais foram vistos vermelhos na validação: o (1) acusou `src/meta_ads/account_overview.py:71 le 'actions'` (e as demais leituras do overview), o (2) acusou `src/mcp/tools/meta_get_account_overview.py:136` e `:160`.

- [ ] **Step 1: Escrever os guards** — `tests/unit/test_meta_metricas_guards.py`:

```python
"""Os guards do contrato das métricas Meta (spec 2026-09-26, §6).

O defeito que o spec fecha é o F189/F190 de novo: a mesma regra consertada num gêmeo
e não no outro (`insights.py` e `account_overview.py` liam os mesmos campos por regras
diferentes). O contrato único só fica único se nada mais puder ler métrica da linha
Graph, e se toda chamada /insights sair do construtor que põe a atribuição. E como o
contrato mudou de número para null, quem lê a tool (o LLM) tem de ser avisado.
"""

from __future__ import annotations

import ast
from pathlib import Path

from src.meta_ads.metricas import FRASE_DA_ATRIBUICAO, FRASE_DO_CTR, FRASE_DO_NULL
from tests.unit import _guard_harness as h

# Os campos de métrica que a linha /insights traz (`insights._COMMON_INSIGHTS_FIELDS`).
_CHAVES_DE_METRICA = frozenset(
    {
        "spend",
        "impressions",
        "clicks",
        "ctr",
        "cpc",
        "reach",
        "frequency",
        "actions",
        "action_values",
        "purchase_roas",
    }
)
_CONTRATO = h.SRC / "meta_ads" / "metricas.py"
_CONSTRUTOR = (h.SRC / "meta_ads" / "insights.py", "build_insights_call")


def _arquivos_meta() -> list[Path]:
    """`src/meta_ads/` inteiro + as tools e helpers Meta de `src/mcp/tools/`.

    O CONJUNTO de raizes e afirmado, nao um piso numerico: uma pasta sumindo da
    varredura enquanto a outra cresce passaria por qualquer piso.
    """
    ferramentas = h.SRC / "mcp" / "tools"
    arquivos = h.fontes_py(h.SRC / "meta_ads") + [
        p for p in h.fontes_py(ferramentas) if p.stem.startswith(("meta_", "_meta_"))
    ]
    raizes = {p.parent.name for p in arquivos}
    assert raizes == {"meta_ads", "tools"}, raizes
    assert any(p.stem == "meta_get_account_overview" for p in arquivos)
    return arquivos


def _leituras_de_metrica(arv: ast.Module) -> list[tuple[int, str]]:
    """`x.get("<metrica>")` e `x["<metrica>"]`, com a linha."""
    achados = []
    for no in ast.walk(arv):
        chave = None
        if (
            isinstance(no, ast.Call)
            and isinstance(no.func, ast.Attribute)
            and no.func.attr == "get"
            and no.args
            and isinstance(no.args[0], ast.Constant)
        ):
            chave = no.args[0].value
        elif isinstance(no, ast.Subscript) and isinstance(no.slice, ast.Constant):
            chave = no.slice.value
        if isinstance(chave, str) and chave in _CHAVES_DE_METRICA:
            achados.append((no.lineno, chave))
    return achados


def test_so_o_contrato_le_metrica_da_linha_graph() -> None:
    """Um segundo leitor de `actions`/`reach`/... e um segundo contrato — o F190."""
    ofensores = []
    lidas_no_contrato = 0
    for arquivo in _arquivos_meta():
        leituras = _leituras_de_metrica(h.arvore(arquivo))
        if arquivo == _CONTRATO:
            lidas_no_contrato = len(leituras)
            continue
        ofensores += [f"{h.rel(arquivo)}:{linha} le {chave!r}" for linha, chave in leituras]
    assert not ofensores, (
        "metrica da linha Graph lida fora de `src/meta_ads/metricas.py`: "
        f"{ofensores}. Use `metricas_da_linha` — a regra do null, do nome canonico e "
        "da unidade mora so la (spec 2026-09-26)."
    )
    assert lidas_no_contrato >= 10, "o contrato parou de ler as metricas — o guard perdeu o alvo"


def _ids_dentro(arv: ast.Module, funcao: str) -> set[int]:
    alvo = next(n for n in ast.walk(arv) if isinstance(n, ast.FunctionDef) and n.name == funcao)
    return {id(n) for n in ast.walk(alvo)}


def test_toda_chamada_insights_sai_do_construtor_unico() -> None:
    """O construtor põe a atribuição unificada; params montados a mão não põem.

    Medido: o overview montava os params à mão e mandava `ad_account_id` espúrio à
    Graph API — o índice da varredura o dava como fechado pelo F190.
    """
    arquivo_construtor, funcao = _CONSTRUTOR
    ofensores = []
    dentro_do_construtor = 0
    for arquivo in _arquivos_meta():
        arv = h.arvore(arquivo)
        docstrings = h._nos_de_docstring(arv)
        permitidos = _ids_dentro(arv, funcao) if arquivo == arquivo_construtor else set()
        for lit in h._literais_de_string(arv):
            if id(lit) in docstrings or "/insights" not in h._texto_logico(lit):
                continue
            if id(lit) in permitidos:
                dentro_do_construtor += 1
                continue
            ofensores.append(f"{h.rel(arquivo)}:{lit.lineno}")
    assert dentro_do_construtor == 1, "o construtor parou de montar o edge — guard sem alvo"
    assert not ofensores, (
        f"edge /insights montado fora de `build_insights_call`: {ofensores}. "
        "Chame o construtor: ele poe a atribuicao unificada (spec 2026-09-26, §4.2)."
    )


def _modulo(caminho: Path) -> str:
    return ".".join(caminho.relative_to(h.RAIZ).with_suffix("").parts)


def _tools_que_chegam_ao_contrato() -> set[str]:
    """Tool cujo modulo importa o contrato, direto ou por modulo de `src/` no meio.

    A populacao sai do grafo de import, nao de lista: tool Meta nova que devolva
    metrica cai aqui sozinha.
    """
    importa: dict[str, set[str]] = {}
    for p in h.fontes_py():
        alvos = set()
        for no in ast.walk(h.arvore(p)):
            if isinstance(no, ast.ImportFrom) and no.module:
                alvos.add(no.module)
            elif isinstance(no, ast.Import):
                alvos.update(a.name for a in no.names)
        importa[_modulo(p)] = alvos
    alcanca = {"src.meta_ads.metricas"}
    mudou = True
    while mudou:
        novos = {m for m, alvos in importa.items() if alvos & alcanca} - alcanca
        alcanca |= novos
        mudou = bool(novos)
    ferramentas = h.SRC / "mcp" / "tools"
    return {
        p.stem
        for p in h.fontes_py(ferramentas)
        if not p.stem.startswith("_") and _modulo(p) in alcanca
    }


def test_toda_tool_com_metrica_meta_avisa_o_contrato_na_description() -> None:
    """O contrato mudou de numero para null e de porcentagem para fracao."""
    from src.mcp.tools._registry import get_tool, import_all_tools

    import_all_tools()
    nomes = _tools_que_chegam_ao_contrato()
    assert len(nomes) >= 5, f"piso medido em 26/09: 5 tools; a varredura achou {sorted(nomes)}"
    faltando = {}
    for nome in sorted(nomes):
        tool = get_tool(nome)
        assert tool is not None, f"`{nome}` nao esta no registry com o nome do modulo"
        ausentes = [
            f
            for f in (FRASE_DO_NULL, FRASE_DO_CTR, FRASE_DA_ATRIBUICAO)
            if f not in tool.description
        ]
        if ausentes:
            faltando[nome] = ausentes
    assert not faltando, f"description sem a frase do contrato: {faltando}"
```

- [ ] **Step 2: Ver passar**

Run: `python -m pytest tests/unit/test_meta_metricas_guards.py -p no:cacheprovider`
Expected: `3 passed`.

- [ ] **Step 3: Provar a mordida — uma sabotagem por guard, cada uma restaurada de cópia**

```bash
G=tests/unit/test_meta_metricas_guards.py
# (a) um segundo leitor de metrica no trio
cp src/meta_ads/insights.py .superpowers/insights.py.bak
sed -i 's/    common = metricas_da_linha(row)/    common = metricas_da_linha(row)\n    _ = row.get("actions")/' src/meta_ads/insights.py
python -m pytest $G -p no:cacheprovider
cp .superpowers/insights.py.bak src/meta_ads/insights.py
# (b) um edge /insights montado a mao numa tool
cp src/mcp/tools/meta_get_performance_breakdown.py .superpowers/breakdown.py.bak
sed -i 's/    level_typed = cast(Level, level)/    _edge_manual = f"\/{ad_account_id}\/insights"\n    level_typed = cast(Level, level)/' src/mcp/tools/meta_get_performance_breakdown.py
python -m pytest $G -p no:cacheprovider
cp .superpowers/breakdown.py.bak src/mcp/tools/meta_get_performance_breakdown.py
# (c) uma description sem as frases do contrato
cp src/mcp/tools/meta_get_ad_performance.py .superpowers/ad.py.bak
python -c "import pathlib; p = pathlib.Path('src/mcp/tools/meta_get_ad_performance.py'); t = p.read_text(encoding='utf-8'); p.write_text(t.replace('    + CONTRATO_NA_DESCRIPTION\n', '', 1), encoding='utf-8')"
python -m pytest $G -p no:cacheprovider
cp .superpowers/ad.py.bak src/mcp/tools/meta_get_ad_performance.py
python -m pytest $G -p no:cacheprovider
git diff --stat src/
```

Expected: cada sabotagem dá `1 failed, 2 passed`, e só o guard dela cai — (a) `metrica da linha Graph lida fora de src/meta_ads/metricas.py: ["src/meta_ads/insights.py:<linha> le 'actions'"]`; (b) `edge /insights montado fora de build_insights_call: ['src/mcp/tools/meta_get_performance_breakdown.py:<linha>']`; (c) `description sem a frase do contrato: {'meta_get_ad_performance': [...]}`. A última rodada: `3 passed`; e o `git diff --stat src/` vazio (as restaurações voltaram ao commit da Task 3).

- [ ] **Step 4: Gate** — `python scripts/check_pre_push.py`, mudo; `echo $?` → `0`.

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_meta_metricas_guards.py
git commit -m "test(meta_ads): guards do contrato unico, do construtor e das descriptions"
```

---

### Task 6: Catálogo, índice e estado (F194)

**Files:**
- Modify: `docs/operacao/findings-catalog.md`, `docs/_archive/varredura-2026-09-21/README.md`, `docs/operacao/estado-atual.md`, `docs/convencoes/nucleo.md`, `CLAUDE.md`

**Interfaces:** consome o que as tasks 1 a 5 fizeram (o texto do F194 descreve exatamente isso).

**O script, e não edições à mão:** ele exige cada âncora exatamente uma vez e **mede** o que declara — a faixa do catálogo (que o guard `test_resumo_bate_com_o_detalhe.py` confere exata), o tamanho (±10%) e a contagem de cabeçalhos `## F<n>` do topo do catálogo, que **não tem guard e já estava defasada em um** antes desta frente (dizia 53 linhas; eram 54 — o F193 não a atualizou).

- [ ] **Step 1: Salvar o script** em `.superpowers/task6_docs.py` (git-ignored):

```python
"""Task 6 do plano das metricas Meta: catalogo, indice da varredura, estado-atual, nucleo, CLAUDE.md.

Rode da raiz do repo: `python <este arquivo> AAAA-MM-DD` (a data do dia da execucao).
Cada ancora e exigida exatamente uma vez.
"""

import pathlib
import re
import sys

DATA = sys.argv[1]
DIA = f"{DATA[8:10]}/{DATA[5:7]}"


def editar(caminho: str, pares: list[tuple[str, str]]) -> None:
    p = pathlib.Path(caminho)
    t = p.read_text(encoding="utf-8")
    for velho, novo in pares:
        assert t.count(velho) == 1, (caminho, t.count(velho), velho[:90])
        t = t.replace(velho, novo)
    p.write_text(t, encoding="utf-8", newline="\n")


# 1. catalogo: a entrada F194, no fim
# Os links sao montados em duas metades: este script vive dentro de um plano, e o
# `test_docs_links` le o plano inteiro (blocos de codigo inclusive) procurando colchete
# fechado colado em parentese aberto —
# um link relativo ao CATALOGO, lido a partir da pasta do plano, quebraria o gate.
L_INDICE = "[índice]" + "(../_archive/varredura-2026-09-21/README.md)"
L_SPEC = (
    "[`2026-09-26-metricas-meta-dizem-o-que-mediram-design.md`]"
    + "(../superpowers/specs/2026-09-26-metricas-meta-dizem-o-que-mediram-design.md)"
)
L_PLANO = (
    "[`2026-09-26-metricas-meta-dizem-o-que-mediram.md`]"
    + "(../superpowers/plans/2026-09-26-metricas-meta-dizem-o-que-mediram.md)"
)
CAT = pathlib.Path("docs/operacao/findings-catalog.md")
ENTRADA = f"""

## F194 (HIGH, ✅ CORRIGIDO {DATA}) — métricas Meta que afirmavam mais do que a Meta mediu

**Origem:** varredura de 21/09, relatórios 01 (item 4) e 03 (itens 4 a 7, 9 e 10) — {L_INDICE}; o F190 deixou estes itens explicitamente para cá.
Spec: {L_SPEC}; plano: {L_PLANO}.

**A classe.** A do F191 e do F193 — uma resposta que afirma mais do que mediu —, agora no
lado Meta, e com a forma do F189/F190: os mesmos campos saíam por **duas regras**, uma em
`insights.py` (trio e breakdown) e outra em `account_overview.py` (overview).

**Medido em 26/09** (Graph API, 24 contas, 30 dias, `scripts/probe_meta_metricas.py`, com
controle de valor inválido nos parâmetros de atribuição):

- a mesma compra sai sob **5 nomes** e o mesmo lead sob **7**. O trio buscava o nome exato
  `purchase`, que nenhuma conta devolve, e reportava **`purchases: 0` sobre 10 compras
  reais**; o overview somava uma lista fixa de nomes, que conta o mesmo evento várias vezes
  quando os recortes vêm juntos;
- **14 de 14** contas com gasto medem conversas iniciadas, e nenhuma tool as expunha: para 13
  delas a resposta dizia `purchases: 0, leads: 0`;
- `action_values` e `purchase_roas` vazios em todas as contas: `0` e `0.0` eram "não
  medido" em 100% das linhas;
- `ctr` em porcentagem no overview e em fração no trio — 100× entre as duas tools mais
  usadas;
- `reach`/`frequency` ausentes em 50 de 50 linhas do breakdown horário, e saindo `0`;
- 10 das 24 contas sem linha nenhuma no período (a Meta não manda linha zerada): o overview
  devolvia zeros sem marcador;
- o BUC gravava "não entendi" como `0`, por cima do último valor medido; a quota do app vem no
  `x-fb-ads-insights-throttle` (o `x-app-usage` não vem em chamada de insights), que nada lia.

E uma afirmação falsa no índice da varredura: o 03#10 constava **fechado pelo F190** ("o
transporte novo não o envia"), e o overview seguia mandando `ad_account_id` como parâmetro da
Graph API — o transporte repassa `params` como recebe. Ninguém tinha conferido.

**✅ O que foi feito:**

- **`src/meta_ads/metricas.py`, o contrato:** a única leitura de métrica de uma linha Graph.
  Um nome canônico por campo (`omni_purchase`, `lead`,
  `onsite_conversion.messaging_conversation_started_7d`), nunca soma de nomes; ausente é
  `null`; `ctr` em fração; contagem arredonda. Campo novo:
  `messaging_conversations_started`.
- **Trio, breakdown e overview passam pelo contrato.** O overview troca
  `conversions`/`conversion_value` pelos campos do trio, traz `sem_dados_no_periodo` e dá
  variação `null` quando um lado não foi medido — antes, campo ausente contava 0 e virava
  -100%.
- **Construtor único:** `build_insights_call` monta toda chamada `/insights`, agora também no
  nível `account`, e fixa `use_unified_attribution_setting=true` (sondado: valor inválido
  volta 400; na conta com conversões, os números não mudaram). As respostas dizem
  `atribuicao: "unificada"`.
- **BUC:** "não lido" é `None`, não grava e emite `meta_buc_nao_lido` em WARNING; o aviso de
  75% passa a considerar também a quota do app e da conta do `x-fb-ads-insights-throttle`, e
  diz qual passou.
- **Descriptions** das 5 tools dizem o que é o `null`, a unidade do `ctr` e a atribuição.

**Os guards** (`tests/unit/test_meta_metricas_guards.py`), vermelhos contra o código
anterior e por sabotagem em cópia:

- só `metricas.py` lê chave de métrica de linha Graph — contra o código anterior acusou as
  leituras do overview;
- só `build_insights_call` monta `/insights` — acusou as duas chamadas montadas à mão do
  overview;
- as tools que chegam ao contrato (população pelo grafo de import: as 5) carregam as três
  frases.

**O guard do F89 tinha um ponto cego que esta mudança criaria:** ele lia só o corpo de
`parse_insights_row`, e com as métricas movidas para o contrato ficava **verde sobre um campo
fantasma plantado em `metricas.py`** (medido). Passou a varrer os dois leitores de linha.

**Fixtures que modelavam uma convenção:** as de quatro arquivos de teste usavam o nome nu
`purchase`, que nenhuma das 24 contas devolve. Reescritas com as formas medidas
(`tests/unit/_meta_formas_medidas.py`).

**Fora, com o motivo:** chaves `_brl` (30 de 30 contas em BRL); as duas paginações
(débito do F190); o nível de acesso `development_access`, que o mesmo cabeçalho revelou
(pendência no `estado-atual`); métricas derivadas de custo por resultado; o dia do contador
BUC no fuso da conta (o contador não tem leitor); status de entidade; freshness de métricas.
"""
CAT.write_text(
    CAT.read_text(encoding="utf-8").rstrip("\n") + ENTRADA, encoding="utf-8", newline="\n"
)

# 2. indice da varredura: os destinos
editar(
    "docs/_archive/varredura-2026-09-21/README.md",
    [
        (
            "| 4 | Meta: `purchases`/`leads`/`purchase_roas` viram `0` quando o campo não vem | aberto — *métricas Meta* |",
            "| 4 | Meta: `purchases`/`leads`/`purchase_roas` viram `0` quando o campo não vem | fechado — F194 (ausente é `null`; o total canônico é `omni_purchase`) |",
        ),
        (
            "| 4 | três regras diferentes para os mesmos campos | aberto — *métricas Meta* |",
            "| 4 | três regras diferentes para os mesmos campos | fechado — F194 (um contrato só, `metricas.py`, com guard) |",
        ),
        (
            "| 5 | contrato de atribuição implícito | aberto — *métricas Meta* |",
            "| 5 | contrato de atribuição implícito | fechado — F194 (atribuição unificada fixada e ecoada; medido: sem efeito na conta com conversões) |",
        ),
        (
            "| 6 | `reach`/`frequency` sob breakdown: ausência vira `0` | aberto — *métricas Meta* |",
            "| 6 | `reach`/`frequency` sob breakdown: ausência vira `0` | fechado — F194 (medido: ausentes em 50 de 50 linhas do horário; vêm `null`) |",
        ),
        (
            '| 7 | BUC: "desconhecido" gravado como `0`; quota de app nunca lida | aberto — *métricas Meta*. Conferido em 25/09: `src/governance/rate_limit.py` devolve `0` em três caminhos |',
            '| 7 | BUC: "desconhecido" gravado como `0`; quota de app nunca lida | fechado — F194 ("não sei" é `None` e não grava; a quota do app vem no `x-fb-ads-insights-throttle`, medido). O dia do contador no fuso da conta ficou fora: o contador não tem leitor |',
        ),
        (
            "| 9 | `_brl` fixo num inventário multi-moeda | aberto — *métricas Meta* |",
            "| 9 | `_brl` fixo num inventário multi-moeda | fora — F194 declarou: 30 de 30 contas em BRL (medido em 26/09) |",
        ),
        (
            "| 10 | `ad_account_id` sobrando na query | fechado — F190 (o transporte novo não o envia) |",
            '| 10 | `ad_account_id` sobrando na query | fechado — F194. Esta linha dizia "fechado — F190 (o transporte novo não o envia)", e não era: o overview montava os params à mão e seguia mandando o parâmetro (conferido em 26/09) |',
        ),
    ],
)

# 3. estado-atual
EA = "docs/operacao/estado-atual.md"
editar(
    EA,
    [
        (
            "sub-projeto nenhum** — viraram a frente *métricas Meta*.",
            f"sub-projeto nenhum** — viraram a frente *métricas Meta*, fechada no **F194** ({DIA}).",
        ),
        (
            '3. **Métricas Meta** (spec) — zero no lugar de "não veio", e o limitador que lê "não sei" como 0%.\n'
            "4. **F154** (spec).\n"
            "5. **Infra e guards** (spec) — o resto dos sub-projetos 3 e 4.\n"
            "6. **`recommendation_subscription`** — tool de leitura no MCC.",
            "3. **F154** (spec).\n"
            "4. **Infra e guards** (spec) — o resto dos sub-projetos 3 e 4.\n"
            "5. **`recommendation_subscription`** — tool de leitura no MCC.",
        ),
        ("**F190**, **F191** e **F193**.", "**F190**, **F191**, **F193** e **F194**."),
        (
            "- **F129** — governança do system user Meta: ação humana, fora do código.\n",
            "- **Nível de acesso da API Meta.** O cabeçalho `x-fb-ads-insights-throttle` diz "
            "`ads_api_access_tier: development_access` (medido em 26/09): o app segue no Limited "
            "Access do **D1** de maio. A regra do D1 para pedir o Full Access é 500 chamadas em 15 "
            "dias; o uso medido em 26/09 é de ~200 por quinzena (395 chamadas Meta em 30 dias). "
            "Decisão sua: pedir agora com o volume atual, ou esperar.\n"
            "- **F129** — governança do system user Meta: ação humana, fora do código.\n",
        ),
    ],
)

# 4. nucleo.md: onde mora a regra das metricas Meta
editar(
    "docs/convencoes/nucleo.md",
    [
        (
            "- **Long-lived token (OAuth pessoal, dormante):**",
            "- **Métrica Meta só pelo contrato (F194):** `src/meta_ads/metricas.py::metricas_da_linha` "
            "é a única leitura de métrica de uma linha `/insights` — um nome canônico por campo "
            "(`omni_purchase`, `lead`, conversa iniciada), nunca soma de nomes; ausente é `null`; "
            "`ctr` em fração. Toda chamada `/insights` sai de `insights.build_insights_call`, que fixa "
            "a atribuição unificada. Os guards estão em `tests/unit/test_meta_metricas_guards.py`.\n"
            "- **Long-lived token (OAuth pessoal, dormante):**",
        ),
    ],
)

# 5. o catalogo vai ate F194: o cabecalho dele, o CLAUDE.md e o estado-atual declaram a
# faixa, o tamanho e (so o cabecalho) quantos `## F<n>` existem — tudo MEDIDO depois da
# entrada nova. O guard `test_resumo_bate_com_o_detalhe.py` confere a faixa (exata) e o
# tamanho (±10%); a contagem de cabecalhos nao tem guard e ficaria falsa em silencio.
texto = CAT.read_text(encoding="utf-8")
cabecalhos = re.findall(r"^## F(\d+)", texto, re.MULTILINE)
distintos = len(set(cabecalhos))
editar(
    str(CAT),
    [
        (
            "(só 52 têm; 53 linhas, F182 aparece 2×)",
            f"(só {distintos} têm; {len(cabecalhos)} linhas, F182 aparece 2×)",
        )
    ],
)
linhas = len(CAT.read_text(encoding="utf-8").splitlines())
kb = round(CAT.stat().st_size / 1024)
aprox = round(linhas, -2)
editar(
    str(CAT),
    [
        (
            "~5400 linhas, 563 KB, IDs de **F1 a F193**",
            f"~{aprox} linhas, {kb} KB, IDs de **F1 a F194**",
        )
    ],
)
editar(
    "CLAUDE.md",
    [
        ("Catálogo até **F193**.", "Catálogo até **F194**."),
        ("**F1–F193, ~5400 linhas, 563 KB**", f"**F1–F194, ~{aprox} linhas, {kb} KB**"),
    ],
)
editar(
    EA,
    [
        (
            "| Catálogo | até **F193** (~5.400 linhas, 563 KB) |",
            f"| Catálogo | até **F194** (~{aprox:,} linhas, {kb} KB) |".replace(",", "."),
        )
    ],
)
print("ok; catalogo:", linhas, "linhas,", kb, "KB")
```

- [ ] **Step 2: Rodar** da raiz do repo, com a data do dia da execução:

```bash
python .superpowers/task6_docs.py AAAA-MM-DD
```

Expected: `ok; catalogo: <n> linhas, <k> KB` (na validação: 5530 linhas, 564 KB). Qualquer `AssertionError` é âncora que mudou desde 26/09 — **não** force: leia o trecho, ajuste a âncora do script ao texto atual, rode de novo.

- [ ] **Step 3: Conferir**

```bash
git diff --stat
grep -n "^## F194" docs/operacao/findings-catalog.md
grep -n "F1–F194" CLAUDE.md
```

Expected: 5 arquivos; um cabeçalho F194; a faixa nova no `CLAUDE.md`.

- [ ] **Step 4: Gate** — `python scripts/check_pre_push.py`, mudo; `echo $?` → `0` (inclui `test_docs_links`, o orçamento do `CLAUDE.md` e a faixa/tamanho do catálogo).

- [ ] **Step 5: Commit**

```bash
git add docs/operacao/findings-catalog.md docs/_archive/varredura-2026-09-21/README.md docs/operacao/estado-atual.md docs/convencoes/nucleo.md CLAUDE.md
git commit -m "docs(operacao): F194 - metricas Meta dizem o que mediram"
```

---

## Depois das tasks: fechar a frente

Passos do controlador, não de um implementador:

1. **Full sweep** — `python scripts/check_pre_push_full.py` (Docker) → 7/7. Mexe em executor, parser e testes de integração: é o caso em que o `CLAUDE.md` torna o sweep obrigatório.
2. **Revisão final da branch** (modelo mais capaz), e uma onda de correção se houver achado.
3. **PR contra `main`** com vigia de CI e auto-merge (método `merge`), pela regra de 26/09. O merge deploya.
4. **Smoke de leitura em produção** (spec §9.6), numa sessão MCP **nova** (F140 — as descriptions novas só aparecem no handshake):
   - `meta_get_account_overview` e `meta_get_campaign_performance` na Cheiro | Conta 01 (`act_926193536103926`, LAST_30_DAYS): `purchases` 10 (não 0), `leads` 13, `messaging_conversations_started` presente, `ctr` em fração, `atribuicao: "unificada"`;
   - numa conta com gasto e sem compra (13 das 14 medidas): `purchases: null`, conversas presentes;
   - `meta_get_performance_breakdown` com `breakdown=hourly`: `reach: null`.
5. **Registrar o smoke** no `estado-atual` (PR de docs pós-deploy).
