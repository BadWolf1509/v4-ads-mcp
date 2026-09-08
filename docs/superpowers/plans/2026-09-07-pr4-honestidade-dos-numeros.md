# PR 4 — Honestidade dos números: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Toda tool que corta resultado passa a dizer que cortou, e o corte volta a ser feito pela coluna que o gestor pediu.

**Architecture:** Um primitivo em `src/mcp/tools/_common.py` decide o corte num
lugar só; as 11 tools passam a consumi-lo; um guard construído sobre o harness do
PR 0 afirma a propriedade *"declara `limit` → devolve `truncated`"* em vez de
enumerar nomes. O C5 (ordenação) some do cliente e volta para o servidor, onde o
`LIMIT` acontece. Cinco sítios de interpolação crua em GAQL passam por `int()` ou
`gaql_string_literal`, e o guard do F141 passa a ver as formas que hoje escapam.

**Tech Stack:** Python 3.13, `google-ads>=27` (v24), pytest, AST puro nos guards.

**Spec:** [`docs/superpowers/specs/2026-09-06-correcoes-varredura-design.md`](../specs/2026-09-06-correcoes-varredura-design.md) — frente "PR 4", primitivo §3.2, critérios §6.

## Global Constraints

- **Todo achado corrigido tem um teste que falha contra o código pré-fix**,
  verificado por sabotagem ou por cópia — **nunca por `git checkout`**, que
  descarta trabalho não commitado.
- **Nenhum guard novo ou reescrito fecha sem que se nomeie a mudança concreta de
  produção que o deixaria vermelho** — e, para guard *apertado*, sem a prova de
  que o **antigo passava verde** onde o novo acusa. Sem essa segunda prova não se
  demonstrou aperto, só reescrita.
- **Sabotagem sozinha não prova guard.** Um `assert False` também ficaria
  vermelho. Toda sabotagem exige o controle positivo: baseline verde antes,
  verde de novo depois de desfazer.
- **Mutação que quebra pelo motivo errado não prova nada.** Se a sabotagem
  derruba o teste com `TypeError`/`IndexError`/erro de protocolo em vez da
  asserção do guard, ela não exercitou a invariante — refaça.
- Guard novo usa `tests/unit/_guard_harness.py` (primitivo do PR 0). **Nunca**
  `Path` relativo nem glob não-recursivo: os dois já produziram guard de escopo
  vazio neste repo.
- `python scripts/check_pre_push.py` verde antes de cada commit. **`python
  scripts/check_pre_push_full.py` (Docker) é obrigatório neste PR** — ele toca
  `queries/` e `_common`.
- Rode o gate **mudo** e leia `$?`. Pipe antes do `&&` não é gate: o exit code do
  pipeline é o do último comando.
- **`ORDER BY` exige o campo no `SELECT`.** Sondado em 2026-09-07 contra a conta
  `7862230676` via `validate_gaql`: `ORDER BY metrics.conversions` sem
  `metrics.conversions` no `SELECT` devolve `QUERY_ERROR`. Não "otimize" o
  `SELECT` das queries do C5.
- **Nada de relógio do servidor em caminho de conta** (F141): `hoje` vem de
  `resolve_account_today`.
- **Nada de SDK do Google fora de `run_blocking`** (F109).
- Acrescentar campo à resposta é **aditivo** e não exige sessão MCP nova (F140);
  tool nova é que exigiria. Nenhuma tool nova entra neste PR.
- Ao fechar o PR: `findings-catalog.md` e `estado-atual.md` atualizados.

## File Structure

| Arquivo | Responsabilidade neste PR |
|---|---|
| `src/mcp/tools/_common.py` | Ganha `aplicar_limite` — o único lugar que decide o corte. |
| `src/google_ads/queries/performance.py` | 3 builders passam a pedir `limit + 1`. |
| `src/google_ads/queries/tactical.py` | 4 builders passam a pedir `limit + 1`. |
| `src/google_ads/queries/change_history.py` | 1 builder passa a pedir `limit + 1`. |
| `src/google_ads/queries/client_report.py` | C5: as duas queries de topo recebem a métrica e emitem o `ORDER BY` dela. |
| `src/google_ads/queries/_common.py` | 4 helpers de validação param de interpolar id cru. |
| `src/google_ads/queries/audit_quality_score.py` | 1 interpolação crua. |
| `src/google_ads/queries/audit_zombie_keywords.py` | 1 interpolação crua + `int()` que trunca `conversions`. |
| 9 tools de relatório | Passam a devolver `truncated`. |
| `src/mcp/tools/get_top_keywords_creatives.py` | Perde o re-sort client-side. |
| `src/mcp/tools/get_ad_schedule.py` | `has_schedule` deixa de mentir sob truncamento. |
| `src/mcp/tools/get_performance_breakdown.py` | `truncated` nos caminhos que não têm + aviso do F56. |
| `src/mcp/tools/detect_drift.py` | Pagina em vez de esconder o teto interno de 500. |
| `tests/unit/test_declaracao_de_truncamento.py` | **Novo.** O guard da propriedade §3.2. |
| `tests/unit/test_no_server_clock_in_google_tools.py` | Guard do F141 apertado. |

---

### Task 1: O primitivo do corte e o guard que o cobra

O defeito não é "faltou um campo em 11 tools" — é que **cada tool decide o corte
sozinha**, e quem decide sozinho decide errado em silêncio. O primitivo dá um
lugar só; o guard impede a próxima tool de nascer sem ele.

**Files:**
- Modify: `src/mcp/tools/_common.py`
- Create: `tests/unit/test_declaracao_de_truncamento.py`
- Create: `tests/unit/test_aplicar_limite.py`

**Interfaces:**
- Produces: `aplicar_limite(linhas: list[T], limite: int) -> tuple[list[T], bool]`
  em `src/mcp/tools/_common.py`. Todas as Tasks 2-5 consomem esta assinatura
  exata.

- [ ] **Step 1: Escreva o teste que falha**

Crie `tests/unit/test_aplicar_limite.py`:

```python
"""O primitivo do corte: um lugar só decide, e o contrato do `+1` fica escrito."""

from src.mcp.tools._common import aplicar_limite


def test_corta_e_declara_quando_veio_sobra() -> None:
    linhas, truncado = aplicar_limite([1, 2, 3, 4], 3)
    assert linhas == [1, 2, 3]
    assert truncado is True


def test_nao_declara_quando_coube_exato() -> None:
    linhas, truncado = aplicar_limite([1, 2, 3], 3)
    assert linhas == [1, 2, 3]
    assert truncado is False


def test_nao_declara_quando_veio_menos() -> None:
    assert aplicar_limite([1], 3) == ([1], False)


def test_lista_vazia() -> None:
    assert aplicar_limite([], 10) == ([], False)


def test_o_truncado_e_bool_de_verdade() -> None:
    """`len(x) > n` já devolve bool; a asserção prende contra um refactor que
    devolva o inteiro da diferença e passe por verdade acidental no consumidor."""
    _, truncado = aplicar_limite([1, 2], 1)
    assert truncado is True
    assert isinstance(truncado, bool)
```

- [ ] **Step 2: Rode e veja falhar**

Run: `python -m pytest tests/unit/test_aplicar_limite.py -q`
Expected: FAIL — `ImportError: cannot import name 'aplicar_limite'`

- [ ] **Step 3: Implemente o primitivo**

Acrescente ao fim de `src/mcp/tools/_common.py`:

```python
from typing import TypeVar

T = TypeVar("T")


def aplicar_limite(linhas: list[T], limite: int) -> tuple[list[T], bool]:
    """Devolve (linhas cortadas, truncated). Único lugar que decide o corte.

    **Contrato:** `linhas` tem que vir de uma consulta pedida com `limite + 1`.
    É a única forma de distinguir "vieram exatamente `limite`" de "havia mais".
    Pedir `LIMIT {limite}` e comparar `len(linhas) > limite` aqui devolve
    `False` SEMPRE, e o detector morre calado — que é o defeito que este
    primitivo existe para fechar, não uma sutileza de estilo.

    O `+1` já é o idioma do repo: `ad_schedule`, `overview` e `recommendations`
    o usam desde que ganharam `truncated`. As 9 tools desta frente usavam
    `LIMIT {limit}` — daí a mentira.
    """
    return linhas[:limite], len(linhas) > limite
```

- [ ] **Step 4: Rode e veja passar**

Run: `python -m pytest tests/unit/test_aplicar_limite.py -q`
Expected: 5 passed

- [ ] **Step 5: Escreva o guard da propriedade**

Crie `tests/unit/test_declaracao_de_truncamento.py`. O guard afirma a
**propriedade**, não uma lista: *toda tool cujo `input_schema` declara `limit`
devolve `truncated`*. Enumerar nomes é o modo de falha nº 1 deste repo — o que
ficar fora da lista passa.

```python
"""§3.2 da spec: tool que corta tem que dizer que cortou.

Por que propriedade e nao lista: a versao "lista de tools que precisam de
`truncated`" passa verde para a tool NOVA que ninguem lembrou de listar, que e
exatamente como as 9 desta frente chegaram a producao. O escopo aqui e derivado
do registry — tool nova com `limit` entra sozinha.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from src.mcp.tools._registry import all_tools, import_all_tools
from tests.unit import _guard_harness as h

import_all_tools()


def _tools_com_limite() -> list[tuple[str, Path]]:
    achados = []
    for t in all_tools():
        props = (t.input_schema or {}).get("properties", {})
        if "limit" not in props:
            continue
        arquivo = Path(sys.modules[t.handler.__module__].__file__ or "")
        achados.append((t.name, arquivo))
    if not achados:
        raise h.EscopoVazioError(
            "nenhuma tool declara `limit` — o registry nao carregou, e o guard "
            "estaria passando sem olhar nada"
        )
    return sorted(achados)


def _chaves_de_retorno(arquivo: Path) -> set[str]:
    """Chaves string de TODO dict literal do modulo.

    Deliberadamente largo: o retorno de varias tools e montado em variavel e so
    depois devolvido, entao olhar so o `ast.Return` veria dict vazio. Largo aqui
    erra para o lado de ABSOLVER, e quem fecha essa folga e o teste de mordida
    do Step 7.
    """
    arvore = ast.parse(arquivo.read_text(encoding="utf-8"))
    chaves: set[str] = set()
    for node in ast.walk(arvore):
        if isinstance(node, ast.Dict):
            for k in node.keys:
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    chaves.add(k.value)
    return chaves


def test_toda_tool_com_limite_declara_truncated() -> None:
    sem = [nome for nome, arq in _tools_com_limite() if "truncated" not in _chaves_de_retorno(arq)]
    assert sem == [], (
        "estas tools cortam resultado e nao dizem que cortaram (spec 3.2): "
        f"{sem}"
    )


def test_nenhuma_tool_devolve_truncated_constante() -> None:
    """`"truncated": False` fixo satisfaz o teste de cima e mente igual.

    Esta e a assercao que distingue "o campo existe" de "o campo e computado" —
    sem ela o guard de cima e satisfeito por um literal, que e a familia
    "asserir o adjacente a invariante".
    """
    ofensores: list[str] = []
    for nome, arq in _tools_com_limite():
        arvore = ast.parse(arq.read_text(encoding="utf-8"))
        for node in ast.walk(arvore):
            if not isinstance(node, ast.Dict):
                continue
            for k, v in zip(node.keys, node.values, strict=True):
                if (
                    isinstance(k, ast.Constant)
                    and k.value == "truncated"
                    and isinstance(v, ast.Constant)
                ):
                    ofensores.append(f"{nome}:{k.lineno}")
    assert ofensores == [], (
        "`truncated` como literal nao e deteccao, e decoracao: " f"{ofensores}"
    )


def test_o_guard_enxerga_as_duas_formas_erradas() -> None:
    """Mordida: prova que as assercoes acima distinguem codigo bom de quebrado."""
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        bom = Path(d) / "bom.py"
        bom.write_text('def f():\n    return {"rows": [], "truncated": t}\n', encoding="utf-8")
        assert "truncated" in _chaves_de_retorno(bom)

        mudo = Path(d) / "mudo.py"
        mudo.write_text('def f():\n    return {"rows": []}\n', encoding="utf-8")
        assert "truncated" not in _chaves_de_retorno(mudo)
```

- [ ] **Step 6: Rode o guard e veja falhar contra o código de hoje**

Run: `python -m pytest tests/unit/test_declaracao_de_truncamento.py -q`
Expected: FAIL — `test_toda_tool_com_limite_declara_truncated` lista as **9**:
`get_ad_group_performance`, `get_ad_performance`, `get_audience_performance`,
`get_campaign_performance`, `get_change_history`, `get_geo_performance`,
`get_keyword_performance`, `get_my_audit_log`, `get_search_terms_report`.

Se a lista vier vazia, o guard não está olhando nada — investigue antes de seguir.

- [ ] **Step 7: Marque as 9 como xfail temporário e commit**

O guard tem que entrar **vermelho pelas 9 certas** e verde só quando a Task 2
fechar. Para não deixar a branch vermelha entre commits, marque o teste com
`@pytest.mark.xfail(strict=True, reason="as 9 fecham na Task 2 deste PR")` e
**remova a marca na Task 2** — `strict=True` faz o xfail que passa virar
falha, então a marca não pode ser esquecida.

```bash
git add src/mcp/tools/_common.py tests/unit/test_aplicar_limite.py tests/unit/test_declaracao_de_truncamento.py
git commit -m "feat(mcp): aplicar_limite e o guard da declaracao de truncamento (3.2)"
```

---

### Task 2: As 9 tools que cortavam calado

**Files:**
- Modify: `src/google_ads/queries/performance.py:19,34,59`
- Modify: `src/google_ads/queries/tactical.py:40,65,103,121`
- Modify: `src/google_ads/queries/change_history.py:163`
- Modify: `src/mcp/tools/get_campaign_performance.py`, `get_ad_group_performance.py`,
  `get_keyword_performance.py`, `get_ad_performance.py`, `get_geo_performance.py`,
  `get_audience_performance.py`, `get_search_terms_report.py`,
  `get_change_history.py`, `get_my_audit_log.py`
- Modify: `tests/unit/test_declaracao_de_truncamento.py` (tira o xfail)
- Test: `tests/unit/test_query_builders_gaql.py` (os builders) + um teste por tool

**Interfaces:**
- Consumes: `aplicar_limite` da Task 1.

- [ ] **Step 1: Escreva os testes de builder que falham**

Em `tests/unit/test_query_builders_gaql.py`, acrescente **um teste por builder**
(8 no total). O modelo, para `campaign_performance_query`:

```python
def test_campaign_performance_query_pede_uma_linha_a_mais() -> None:
    """Sem o `+1`, `len(linhas) > limite` e falso por construcao e o
    `truncated` da tool mente `false` para sempre."""
    assert "LIMIT 101" in campaign_performance_query(_S, _E, "ENABLED", 100)
    assert "LIMIT 100" not in campaign_performance_query(_S, _E, "ENABLED", 100)
```

Repita, com o mesmo corpo e os argumentos de cada assinatura, para:
`ad_group_performance_query`, `geo_performance_query`,
`keyword_performance_query`, `search_terms_query`, `ad_performance_query`,
`audience_performance_query`, `change_history_query`.

- [ ] **Step 2: Rode e veja os 8 falharem**

Run: `python -m pytest tests/unit/test_query_builders_gaql.py -q`
Expected: 8 failed — `assert 'LIMIT 101' in ...`

- [ ] **Step 3: Troque `LIMIT {limit}` por `LIMIT {limit + 1}` nos 8 builders**

Uma edição por sítio. Confira depois que **nenhum** `LIMIT {limit}` sem `+ 1`
sobrou nos builders que servem tool com `limit` no schema:

```bash
grep -rn "LIMIT {limit}" src/google_ads/queries/
```

Expected: nenhuma linha.

- [ ] **Step 4: Rode e veja passar**

Run: `python -m pytest tests/unit/test_query_builders_gaql.py -q`
Expected: all passed

- [ ] **Step 5: Escreva o teste de tool que falha (as 9)**

Crie `tests/unit/test_tools_declaram_truncamento.py`. Cada teste monta
`limite + 1` linhas falsas, chama o handler com o `run_report`/repositório
mockado, e afirma **as duas metades**: `truncated is True` **e**
`len(rows) == limite`. Afirmar só o campo deixaria passar uma tool que declara e
não corta.

```python
"""As 9 tools da frente PR 4: cortam e DIZEM que cortaram.

Uma metade so nao basta: `truncated: true` com a lista inteira devolvida engana
igual, so na direcao oposta.
"""
```

Siga o padrão de mock já usado em `tests/unit/` para tools de relatório — não
invente um novo. Para `get_my_audit_log`, o alvo é
`audit_log.list_for_manager`, não `run_report`.

- [ ] **Step 6: Rode e veja as 9 falharem**

Run: `python -m pytest tests/unit/test_tools_declaram_truncamento.py -q`
Expected: 9 failed — `KeyError: 'truncated'`

- [ ] **Step 7: Faça as 9 tools consumirem `aplicar_limite`**

Em cada tool, depois do `run_report` (ou do `list_for_manager`):

```python
from src.mcp.tools._common import aplicar_limite

rows, truncado = aplicar_limite(rows, limit)
```

e acrescente `"truncated": truncado` ao dict de retorno. Em
`get_my_audit_log`, passe `limit=limit + 1` ao repositório.

Atualize a `description` de cada tool para dizer que `truncated: true` avisa o
corte — a descrição é o contrato que o gestor lê.

- [ ] **Step 8: Tire o xfail do guard e rode tudo**

Remova a marca `xfail` de `test_toda_tool_com_limite_declara_truncated`.

Run: `python -m pytest tests/unit/test_declaracao_de_truncamento.py tests/unit/test_tools_declaram_truncamento.py -q`
Expected: all passed

- [ ] **Step 9: Prove o guard por sabotagem**

Tire o `"truncated": truncado` de **uma** tool (`get_geo_performance`), rode o
guard, confirme que ele acusa **aquela** tool pelo nome, desfaça, confirme verde
de novo. Sem o verde final, a sabotagem não prova nada.

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "fix(mcp): as 9 tools que cortavam calado passam a declarar truncated"
```

---

### Task 3: `get_performance_breakdown` e o aviso do F56

`truncated` existe no arquivo, mas só no caminho `raw_grid` da partição horária.
Os demais níveis (`campaign`, `ad_group`, `ad`, `keyword`, `audience`,
`account`) cortam calado — e o guard da Task 1 passa verde porque olha o
arquivo, não o caminho. É a mesma família de "o campo existe".

**Files:**
- Modify: `src/mcp/tools/get_performance_breakdown.py`
- Test: `tests/unit/test_get_performance_breakdown.py` (ou o arquivo existente)

- [ ] **Step 1: Teste que falha, um por caminho de retorno**

Um teste por `return` do handler que hoje não carrega `truncated`. Cada um monta
`limit + 1` linhas e afirma `truncated is True` **e** `len(rows) == limit`.

- [ ] **Step 2: Rode e veja falhar** — `KeyError: 'truncated'`

- [ ] **Step 3: Aplique `aplicar_limite` em cada caminho**

O builder do nível correspondente já foi para `limit + 1` na Task 2 quando
compartilhado; se este tool tiver builder próprio, aplique o `+1` aqui também.

- [ ] **Step 4: Herde o aviso do F56**

`get_keyword_performance` já avisa que a resposta mistura keywords **negativas**
(`ad_group_criterion.negative`). `get_performance_breakdown(level="keyword")` lê
a mesma tabela e **não avisa**. Copie o aviso para a `description` e, se a tool
devolver o campo `negative` por linha, diga isso na descrição também. Se ela
**não** devolver, acrescente o campo: aviso sem o campo obriga o gestor a
adivinhar qual linha é qual.

- [ ] **Step 5: Rode, sabote, desfaça, commit**

```bash
git commit -am "fix(mcp): get_performance_breakdown declara corte em todo nivel e herda o aviso do F56"
```

---

### Task 4: `has_schedule` deixa de mentir sob truncamento

`get_ad_schedule` detecta o corte certo (`LIMIT {limit + 1}`, já era assim). O
defeito é o **resumo**: `schedule_summary` é montado a partir de `orcamentos`
(todas as campanhas), e `atual.get(cid, [])` devolve vazio para a campanha cujas
janelas ficaram além do corte. O resumo então diz `has_schedule: false` e
`hours_per_week: 168` — ou seja, **"serve 24x7"**, que é o oposto da verdade,
para uma campanha que tem grade e foi truncada.

Ler "sem grade" de uma campanha que tem grade restrita é o erro que faz o gestor
achar que precisa criar agenda onde já existe.

**Files:**
- Modify: `src/mcp/tools/get_ad_schedule.py`
- Test: `tests/unit/test_get_ad_schedule.py` (arquivo existente)

- [ ] **Step 1: Teste que falha**

```python
def test_campanha_cortada_nao_e_reportada_como_24x7() -> None:
    """Duas campanhas, `limit=1`: a segunda perde as janelas para o corte.

    Antes do fix o resumo dela dizia has_schedule=false / hours_per_week=168 —
    "serve o tempo todo" — que e o oposto do que a grade dela diz.
    """
    # ... monta 2 campanhas com grade, chama com limit=1 ...
    assert resultado["truncated"] is True
    cortada = resultado["schedule_summary"]["<id da segunda>"]
    assert cortada["has_schedule"] is None
    assert cortada["hours_per_week"] is None
    assert cortada["schedule_desconhecida_por_truncamento"] is True
```

- [ ] **Step 2: Rode e veja falhar**

Expected: FAIL — `assert False is None` (hoje devolve `False`).

- [ ] **Step 3: Implemente**

Quando `truncated` for verdadeiro, toda campanha **sem nenhuma linha** em
`atual` tem resumo desconhecido, não resumo vazio:

```python
tem_janela_lida = set(atual)
for cid, resumo in summary.items():
    if truncated and cid not in tem_janela_lida:
        # Nao sabemos se a campanha nao tem grade ou se a grade dela ficou
        # alem do corte. `false` aqui afirma "serve 24x7", que e uma frase
        # sobre ENTREGA — nao se chuta isso a partir de uma leitura parcial.
        resumo["has_schedule"] = None
        resumo["hours_per_week"] = None
        resumo["schedule_desconhecida_por_truncamento"] = True
```

Atualize a `description` da tool: hoje ela ensina explicitamente a ler
`has_schedule: false` como 24x7, e passa a precisar dizer que `null` significa
"não sei, aumente o `limit`".

- [ ] **Step 4: Rode, sabote (volte o `None` para `False`), desfaça, commit**

```bash
git commit -am "fix(mcp): has_schedule nao afirma 24x7 a partir de leitura parcial"
```

---

### Task 5: `detect_drift` pagina em vez de esconder o teto de 500

A tool devolve `truncated`, mas ele reflete **o `limit` do gestor**, não o teto
interno de 500 (`src/mcp/tools/detect_drift.py:176`). Numa conta com mais de 500
eventos na janela, evento se perde antes de qualquer classificação — e o
trabalho inteiro desta tool é responder *"mudou algo que não devia?"*.

Declarar sem paginar seria o mínimo honesto; aqui não basta.

**Files:**
- Modify: `src/mcp/tools/detect_drift.py`
- Modify: `src/google_ads/queries/change_history.py` (se a paginação exigir cursor)
- Test: `tests/unit/test_detect_drift.py`

- [ ] **Step 1: Teste que falha — mais de 500 eventos**

```python
async def test_pagina_alem_do_teto_de_500() -> None:
    """1200 eventos na janela: antes do fix, 700 sumiam sem `truncated`.

    O que o gestor via: "zero drift", com 700 mudancas nao examinadas.
    """
```

Monte o mock devolvendo 1200 eventos e afirme que **todos os 1200** foram
classificados, e que `truncated` reflete o teto **paginado**, não o de 500.

- [ ] **Step 2: Rode e veja falhar** — a contagem para em 500.

- [ ] **Step 3: Implemente a paginação**

O `change_event` do Google é ordenado e aceita `LIMIT`; pagine por
`change_event.change_date_time` com desempate estável, buscando páginas de 500
até esgotar ou até um teto declarado (`_TETO_PAGINADO`, constante nomeada no
módulo, não literal solto). Ao atingir o teto paginado, `truncated: true`
**e** um campo dizendo quantos eventos foram examinados.

Se a API não sustentar cursor estável para este recurso, **pare e registre a
descoberta** em vez de inventar um: a alternativa honesta é declarar o teto
interno explicitamente (`teto_interno_atingido: true`) e dizer o número. Não
invente cursor por analogia — probe primeiro com `validate_gaql`.

- [ ] **Step 4: Rode, sabote, desfaça, commit**

```bash
git commit -am "fix(mcp): detect_drift pagina em vez de perder evento no teto interno"
```

---

### Task 6: C5 — o corte volta para a coluna certa

`top_keywords_query` ordena por `metrics.cost_micros DESC LIMIT top_n` **sempre**.
Quando o gestor pede `metric="conversions"`, a tool re-ordena **as N linhas que
já vieram cortadas por custo**. O top-10 por conversões que não estiver no
top-10 por custo **não existe na resposta** — e a docstring de
`client_report.py:23` promete *"caller decides via ORDER BY"*, o que é falso.

Uma keyword barata que converte muito é exatamente o que a tool deveria achar, e
é exatamente o que ela esconde.

**Files:**
- Modify: `src/google_ads/queries/client_report.py`
- Modify: `src/mcp/tools/get_top_keywords_creatives.py`
- Test: `tests/unit/test_query_builders_gaql.py`, `tests/unit/test_get_top_keywords_creatives.py`

**Interfaces:**
- Produces: `top_keywords_query(start, end, top_n, *, metric: str) -> str` e
  `top_creatives_query(start, end, top_n, *, metric: str) -> str`. `metric` é uma
  das quatro do schema: `cost`, `conversions`, `clicks`, `impressions`.

- [ ] **Step 1: Teste que falha — o `ORDER BY` segue a métrica**

```python
_ORDEM = {
    "cost": "metrics.cost_micros",
    "conversions": "metrics.conversions",
    "clicks": "metrics.clicks",
    "impressions": "metrics.impressions",
}


def test_top_keywords_ordena_pela_metrica_pedida() -> None:
    for metric, campo in _ORDEM.items():
        q = top_keywords_query(_S, _E, 10, metric=metric)
        assert f"ORDER BY {campo} DESC" in q, metric


def test_o_campo_do_order_by_esta_no_select() -> None:
    """Sondado em 07/09 via validate_gaql: o Google recusa `ORDER BY` de campo
    fora do SELECT com "The following field must be present in SELECT clause".
    Esta assercao e o que impede alguem de "enxugar" o SELECT depois."""
    for metric, campo in _ORDEM.items():
        for q in (
            top_keywords_query(_S, _E, 10, metric=metric),
            top_creatives_query(_S, _E, 10, metric=metric),
        ):
            select = q.split("FROM")[0]
            assert campo in select, f"{metric}: {campo} fora do SELECT"
```

- [ ] **Step 2: Rode e veja falhar** — `TypeError: unexpected keyword 'metric'`

- [ ] **Step 3: Implemente nos dois builders**

Mapa único no módulo (não duplicado nas duas funções), `metric` obrigatório
como keyword-only, e `KeyError` explícito para valor fora do mapa — a validação
do schema é a montante, mas o builder não depende dela (F87).

- [ ] **Step 4: Teste de tool que falha — o top certo aparece**

```python
async def test_top_por_conversoes_encontra_a_barata_que_converte() -> None:
    """A keyword de menor custo e maior conversao: antes do fix ela ficava
    FORA, porque o corte era por custo e o re-sort so reordenava o que sobrou.

    Este e o teste que falha contra o codigo pre-fix por MOTIVO CERTO: nao e
    ordem trocada, e linha ausente.
    """
```

O mock do `run_report` deve devolver **exatamente o que a query pede** — se a
query ordena por conversões, o mock devolve ordenado por conversões. Um mock que
devolve sempre a mesma lista não consegue expressar este bug (modo de falha
conhecido: o mock incapaz de expressar o defeito).

- [ ] **Step 5: Rode, veja falhar, implemente**

Passe `metric=metric` às duas chamadas e **apague** o bloco `if metric !=
"cost":` com o re-sort e o `[:top_n]`. Apague também `_METRIC_KEY`, que só
existia para ele — deixar constante órfã é o rastro que faz o próximo leitor
achar que ainda há re-sort.

- [ ] **Step 6: Corrija a docstring que prometia**

`"""Top N keywords ordered by metric (caller decides via ORDER BY at fetch)."""`
deixa de ser promessa e passa a descrever o que a função faz.

- [ ] **Step 7: Sabote, desfaça, commit**

```bash
git commit -am "fix(google_ads): o top-N volta a ser cortado pela metrica pedida (C5)"
```

---

### Task 7: Cinco interpolações cruas e um `int()` que apaga conversão

**Files:**
- Modify: `src/google_ads/queries/_common.py:261,321,408,482`
- Modify: `src/google_ads/queries/audit_quality_score.py:43`
- Modify: `src/google_ads/queries/audit_zombie_keywords.py:34,78,96`
- Test: `tests/unit/test_query_builders_gaql.py` ou arquivo próprio

- [ ] **Step 1: Teste que falha, um por sítio**

Cada teste passa um id que **não é numérico** e afirma que o builder recusa
(`ValueError`) em vez de interpolar. Não afirme "o texto foi escapado" — afirme
que a função **não aceita** o que não é id.

```python
def test_valida_manual_cpc_recusa_id_nao_numerico() -> None:
    """`", ".join(ad_group_ids)` interpolava texto livre direto no GAQL.

    O `pattern` do schema a montante nao e defesa: helper e chamado de mais de
    um lugar, e o proximo chamador pode nao ter schema nenhum (F87).
    """
```

Para `audit_zombie_keywords`, o teste do `int()`:

```python
def test_conversoes_fracionadas_nao_viram_zero() -> None:
    """`int(0.9)` = 0. Numa tool que define zumbi como "zero atividade",
    truncar conversao fracionada INVENTA zumbi: a keyword converteu, e o
    relatorio diz que nao. Atribuicao fracionada e o caso normal, nao a borda."""
    linha = parse_zombie_row(_row(conversions=0.9))
    assert linha["conversions"] == 0.9
```

- [ ] **Step 2: Rode e veja falhar**

- [ ] **Step 3: Implemente**

Nos 4 helpers de `_common.py` e no `audit_zombie_keywords.py:34`: os valores são
**ids numéricos** — `", ".join(str(int(x)) for x in ids)`, o mesmo idioma já
usado nas linhas 791 e 869 do próprio arquivo. Em `audit_quality_score.py:43` o
valor vai entre aspas no GAQL; use `int()` igual (id numérico não precisa de
aspas) ou `gaql_string_literal` se a coluna exigir string — **decida olhando a
query, não por analogia**.

`conversions` passa a `float(...)` nos três sítios
(`audit_zombie_keywords.py:78,96` e o campo do dataclass, se for `int`).

- [ ] **Step 4: Rode, sabote um sítio, desfaça, commit**

```bash
git commit -am "fix(google_ads): id nao entra cru em GAQL, e conversao fracionada nao vira zero"
```

---

### Task 8: O guard do F141 vê as formas que hoje escapam

O guard casa `datetime.now`, `date.today` e `datetime.today` **e só quando o
objeto é um `ast.Name` com esse nome literal**. Escapam hoje:

| Forma | Por que escapa |
|---|---|
| `datetime.utcnow()` | `utcnow` não está em `_RELOGIO` |
| `time.time()` | idem |
| `from time import time` → `time()` | é `ast.Name`, não `ast.Attribute` |
| `from datetime import datetime as dt` → `dt.now()` | `f.value.id == "dt"` |
| `import datetime as dt` → `dt.datetime.now()` | `f.value` é `Attribute`, não `Name` |

Nenhuma delas é hipotética: `utcnow()` é o que a maior parte do código Python
antigo escreve, e alias de import é o que um formatador ou um autocomplete
produz sozinho.

**Files:**
- Modify: `tests/unit/test_no_server_clock_in_google_tools.py`
- Modify: qualquer arquivo de produção que o guard apertado revelar

- [ ] **Step 1: Escreva os casos de mordida que falham**

```python
def test_o_guard_ve_utcnow_time_e_alias_de_import() -> None:
    """As cinco formas que o guard antigo deixava passar.

    Cada uma e um `hoje` do SERVIDOR entrando em caminho de conta pela porta
    que ninguem fechou — e o sintoma e o mesmo do F141: erra so das 21h a
    meia-noite locais.
    """
    assert _chamadas_de_relogio("x = datetime.utcnow()") == [1]
    assert _chamadas_de_relogio("import time\nx = time.time()") == [2]
    assert _chamadas_de_relogio("from time import time\nx = time()") == [2]
    assert _chamadas_de_relogio(
        "from datetime import datetime as dt\nx = dt.now(UTC)"
    ) == [2]
    assert _chamadas_de_relogio("import datetime as dt\nx = dt.datetime.now()") == [2]


def test_o_guard_apertado_nao_passa_a_acusar_o_inocente() -> None:
    """Controle: um nome local `time` que nao e o modulo nao pode virar ofensor."""
    assert _chamadas_de_relogio("def f(time):\n    return time.strftime('%Y')") == []
```

- [ ] **Step 2: Rode e veja falhar** — as 5 primeiras asserções devolvem `[]`.

- [ ] **Step 3: Implemente a resolução de alias**

Percorra `ast.Import` e `ast.ImportFrom` do módulo montando um mapa
`nome_local -> origem canônica`, e resolva o `func` contra ele. Acrescente
`utcnow` e `time.time` ao conjunto proibido. Mantenha o AST — não caia para
grep, pelo motivo que a docstring do arquivo já dá (os comentários **citam** o
padrão proibido).

O harness do PR 0 já tem `nomes_locais` para isto — **use-o em vez de escrever
outro**; se não servir, diga por quê no comentário e estenda o harness, não o
guard.

- [ ] **Step 4: Rode o guard inteiro contra a produção**

Run: `python -m pytest tests/unit/test_no_server_clock_in_google_tools.py -q`

Se ele acusar arquivo de produção, **isso é uma violação viva que o guard nunca
viu** — corrija no mesmo commit (é a regra da spec §4: guard apertado e violação
exposta são a mesma unidade de trabalho). Se acusar `LEITORES_LEGITIMOS` por
uma forma nova, avalie se é o idioma injetável ou relógio disfarçado.

- [ ] **Step 5: Prove que o guard ANTIGO passava verde aqui**

Copie o `_nos_de_relogio` antigo para um teste temporário, rode-o contra as 5
formas, confirme que devolve `[]` nas cinco, e **apague o teste temporário**.
Sem isso não se demonstrou aperto — só reescrita. Registre o resultado no
relatório da task.

- [ ] **Step 6: Commit**

```bash
git commit -am "test(guard): o F141 passa a ver utcnow, time.time e alias de import"
```

---

### Task 9: Fecho — catálogo, estado e o full sweep

**Files:**
- Modify: `docs/operacao/findings-catalog.md`
- Modify: `docs/operacao/estado-atual.md`

- [ ] **Step 1: Abra os findings desta frente**

Um por família, com o que foi feito **e o que ficou deliberadamente de fora** —
é o formato do catálogo. No mínimo: a família do truncamento (11 tools), o C5, o
`has_schedule` sob leitura parcial, a paginação do `detect_drift`, as
interpolações, o `int()` das conversões, e o aperto do F141.

- [ ] **Step 2: Atualize `estado-atual.md`** com a frente fechada e o que resta.

- [ ] **Step 3: Full sweep, mudo, lendo `$?`**

```bash
python scripts/check_pre_push_full.py
```

Expected: exit 0. **Obrigatório** — este PR toca `queries/` e `_common`.

- [ ] **Step 4: Commit**

```bash
git commit -am "docs(operacao): findings e estado da frente de honestidade dos numeros"
```
