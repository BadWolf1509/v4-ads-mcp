# Partição horária por campanha — plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: use `superpowers:subagent-driven-development` (recomendado) ou `superpowers:executing-plans` para executar tarefa a tarefa. Os passos usam checkbox (`- [ ]`).

**Goal:** dar ao gestor o CPA por bloco horário **por campanha**, numa tool de leitura, para que decidir grade deixe de exigir autorização de mutação.

**Architecture:** um domínio puro novo (`partition_by_blocks`) que particiona células dia × hora em blocos nomeados, reusando `Window`, `covers` e a agregação que já existem em `src/google_ads/ad_schedule.py`. Duas tools consomem esse domínio: `get_ad_schedule` (opt-in por flag) e `get_performance_breakdown` (`level=campaign` + `breakdown=hourly`). A partição é o **default**; a grade crua de 168 células fica atrás de flag explícita, com teto próprio.

**Tech Stack:** Python 3.13, `google-ads` v24 (GAQL), pytest. Sem dependência nova.

**Spec:** [`docs/superpowers/specs/2026-09-04-particao-horaria-design.md`](../specs/2026-09-04-particao-horaria-design.md)

## Global Constraints

- **`hoje` é da conta, nunca do servidor** — `await resolve_account_today(customer_id)`, uma vez por request (F141). Guard AST em `test_no_server_clock_in_google_tools.py`.
- **SDK do Google só dentro de `run_blocking`** (F86/F109); leituras via `run_report`.
- **Teto e sentinela de truncamento obrigatórios** em toda resposta de lista (F98); `LIMIT` sem `ORDER BY` é proibido (F88).
- **Sem `oneOf`/`allOf`/`anyOf`** no `input_schema` (3b.19B.1) — regra cross-field vive em pré-flight Python.
- **Tool nova ou schema novo só aparece para sessão MCP nova** (F140).
- **Verificação antes de commit:** `python scripts/check_pre_push.py`. **Full sweep obrigatório** (`check_pre_push_full.py`, Docker) porque este plano toca query e tool de leitura com JOIN de métricas.
- **Não fechar o sprint com passo de smoke em `⬜ pending`** — F150/F151.

## Escopo

**Dentro:** partição por blocos em `get_ad_schedule` e em `get_performance_breakdown`.

**Fora, declarado:** `bid_modifier` por janela (F149) — é caminho de **escrita**, toca `windows[]`, `diff_schedule`, builder, payload e `apply_change`, e **não compartilha nada** com o domínio de partição. Vai em plano próprio. Também fora: geo por cidade (regra de merge; o `canonical_name` não colapsa os duplicados medidos) e `aggregate_by` somando (regra de razão).

## File Structure

| Arquivo | Responsabilidade |
|---|---|
| `src/google_ads/ad_schedule.py` (modificar) | ganha `Bloco`, `BLOCOS_PADRAO` e `partition_by_blocks` — domínio puro, sem I/O |
| `src/mcp/tools/get_ad_schedule.py` (modificar) | flag `include_metrics`, monta blocos e chama o domínio |
| `src/google_ads/performance_breakdown.py` (modificar) | `_validate_combo` aceita `campaign`+`hourly`; builder roteia para `day_hour_metrics_query` |
| `src/mcp/tools/get_performance_breakdown.py` (modificar) | flag `raw_grid`, teto próprio, sentinela |
| `tests/unit/test_particao_por_blocos.py` (criar) | domínio puro |
| `docs/operacao/phase-3b-43-particao-horaria-smoke.md` (criar) | smoke, com passo de leitura em conta real |

---

### Task 1: domínio — `partition_by_blocks`

**Files:**
- Modify: `src/google_ads/ad_schedule.py`
- Test: `tests/unit/test_particao_por_blocos.py` (criar)

**Interfaces:**
- Consumes: `Window`, `MetricCell`, `covers` — já existem neste módulo.
- Produces: `partition_by_blocks(cells: list[MetricCell], blocos: dict[str, list[Window]]) -> dict[str, dict[str, Any]]`. Cada valor tem as chaves `cost_brl: float`, `conversions: float`, `cpa_brl: float | None`, `cells: int`. **Ruling 3 do scan de pre-voo: a chave `horas` foi REMOVIDA** — `float(len(cs))` contava celulas COM DADO, nao a extensao do bloco, entao um bloco de 50h sem gasto apareceria com `horas: 0`. Era duplicata de `cells` com nome que prometia outra coisa. Toda célula não coberta por bloco nenhum cai em `"outros"`.

- [ ] **Step 1: escrever o teste que falha — a partição tem que ser TOTAL**

```python
from src.google_ads.ad_schedule import MetricCell, Window, partition_by_blocks


def _cel(dia: str, hora: int, custo_brl: float, conv: float) -> MetricCell:
    return MetricCell(dia, hora, int(custo_brl * 1_000_000), conv)


def test_celula_fora_de_todo_bloco_cai_em_outros_e_nao_some():
    """Soma dos blocos tem que bater com o total. Celula descartada em silencio
    e a familia de defeito que este repo mais vem pagando: numero que parece
    certo porque a parte que faltava nao aparece."""
    blocos = {"comercial": [Window("MONDAY", 8, 0, 18, 0)]}
    cells = [_cel("MONDAY", 9, 100.0, 5.0), _cel("SUNDAY", 3, 40.0, 1.0)]

    resultado = partition_by_blocks(cells, blocos)

    assert resultado["comercial"]["cost_brl"] == 100.0
    assert resultado["outros"]["cost_brl"] == 40.0
    assert sum(b["cost_brl"] for b in resultado.values()) == 140.0
    assert sum(b["cells"] for b in resultado.values()) == 2
```

- [ ] **Step 2: rodar e ver falhar**

Run: `python -m pytest tests/unit/test_particao_por_blocos.py -v`
Expected: FAIL com `ImportError: cannot import name 'partition_by_blocks'`.

- [ ] **Step 3: implementar o mínimo**

Em `src/google_ads/ad_schedule.py`, depois de `partition_metrics`:

```python
def partition_by_blocks(
    cells: list[MetricCell], blocos: dict[str, list[Window]]
) -> dict[str, dict[str, Any]]:
    """Particiona celulas dia x hora em blocos nomeados. TOTAL por construcao.

    Toda celula cai em exatamente um balde: o primeiro bloco que a cobre, ou
    `outros`. Sem isso a soma dos blocos nao bate com o total da conta, e o
    gestor compara CPA de blocos que juntos nao explicam o gasto.
    """
    baldes: dict[str, list[MetricCell]] = {nome: [] for nome in blocos}
    baldes["outros"] = []
    for c in cells:
        destino = next(
            (nome for nome, janelas in blocos.items() if covers(janelas, c.day_of_week, c.hour)),
            "outros",
        )
        baldes[destino].append(c)
    return {nome: _agrega(cs) for nome, cs in baldes.items()}
```

- [ ] **Step 4: rodar e ver passar**

Run: `python -m pytest tests/unit/test_particao_por_blocos.py -v`
Expected: PASS.

- [ ] **Step 5: commit**

```bash
git add src/google_ads/ad_schedule.py tests/unit/test_particao_por_blocos.py
git commit -m "feat(ad_schedule): particao por blocos nomeados, total por construcao"
```

---

### Task 2: os três blocos padrão, e a prova de que ladrilham a semana

**Files:**
- Modify: `src/google_ads/ad_schedule.py`
- Test: `tests/unit/test_particao_por_blocos.py`

**Interfaces:**
- Produces: `BLOCOS_PADRAO: dict[str, list[Window]]` com as chaves `"comercial"`, `"fora_de_hora"`, `"fim_de_semana"`.

- [ ] **Step 1: escrever o teste que falha**

```python
from src.google_ads.ad_schedule import BLOCOS_PADRAO, hours_per_week


def test_os_blocos_padrao_ladrilham_a_semana_exatamente():
    """168h, sem sobra e sem sobreposicao. Se os blocos nao ladrilham, `outros`
    vira lixeira silenciosa e a comparacao entre blocos perde sentido."""
    total = sum(hours_per_week(janelas) for janelas in BLOCOS_PADRAO.values())
    assert total == 168.0
    assert set(BLOCOS_PADRAO) == {"comercial", "fora_de_hora", "fim_de_semana"}
```

- [ ] **Step 2: rodar e ver falhar**

Run: `python -m pytest tests/unit/test_particao_por_blocos.py::test_os_blocos_padrao_ladrilham_a_semana_exatamente -v`
Expected: FAIL com `ImportError: cannot import name 'BLOCOS_PADRAO'`.

- [ ] **Step 3: implementar**

```python
_UTEIS = ("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY")

# 50h + 70h + 48h = 168h. O teste cobra essa soma: bloco que nao ladrilha
# transforma `outros` em lixeira e a comparacao entre blocos vira ruido.
BLOCOS_PADRAO: dict[str, list[Window]] = {
    "comercial": [Window(d, 8, 0, 18, 0) for d in _UTEIS],
    "fora_de_hora": [Window(d, 0, 0, 8, 0) for d in _UTEIS]
    + [Window(d, 18, 0, 24, 0) for d in _UTEIS],
    "fim_de_semana": [Window("SATURDAY", 0, 0, 24, 0), Window("SUNDAY", 0, 0, 24, 0)],
}
```

- [ ] **Step 4: rodar e ver passar**

Run: `python -m pytest tests/unit/test_particao_por_blocos.py -v`
Expected: PASS (2 testes).

- [ ] **Step 5: commit**

```bash
git add src/google_ads/ad_schedule.py tests/unit/test_particao_por_blocos.py
git commit -m "feat(ad_schedule): blocos padrao com guard de ladrilhamento das 168h"
```

---

### Task 3: `get_ad_schedule` ganha a partição opt-in

**Files:**
- Modify: `src/mcp/tools/get_ad_schedule.py`
- Test: `tests/unit/test_get_ad_schedule.py`

**Interfaces:**
- Consumes: `partition_by_blocks`, `BLOCOS_PADRAO` (Tasks 1-2); `day_hour_metrics_query(*, campaign_ids, start, end)` e `parse_day_hour_row` de `src/google_ads/queries/ad_schedule.py`.
- Produces: quando `include_metrics: true`, cada entrada de `schedule_summary` ganha a chave `metrics_por_bloco` com a saída de `partition_by_blocks`.

- [ ] **Step 1: escrever o teste que falha**

```python
@pytest.mark.asyncio
async def test_include_metrics_traz_cpa_por_bloco_sem_exigir_mutacao(monkeypatch) -> None:
    """O ponto do sprint: decidir grade deixa de passar pela tool de escrita."""
    _wire_get(monkeypatch, grade=[], metricas=[
        {"campaign_id": "1", "day_of_week": "MONDAY", "hour": 9,
         "cost_micros": 100_000_000, "conversions": 5.0},
    ])
    out = await mod.get_ad_schedule(
        {"customer_id": "1234567890", "campaign_ids": ["1"], "include_metrics": True}
    )
    blocos = out["schedule_summary"]["1"]["metrics_por_bloco"]
    assert blocos["comercial"]["cost_brl"] == 100.0
    assert blocos["comercial"]["cpa_brl"] == 20.0
    assert blocos["fim_de_semana"]["cells"] == 0


@pytest.mark.asyncio
async def test_sem_a_flag_nao_ha_consulta_de_metricas(monkeypatch) -> None:
    """A conjunta dia x hora e cara; a tool de leitura tem que continuar barata."""
    queries: list[str] = []
    _wire_get(monkeypatch, grade=[], metricas=[], espia=queries)
    out = await mod.get_ad_schedule({"customer_id": "1234567890", "campaign_ids": ["1"]})
    assert not any("segments.hour" in q for q in queries)
    assert "metrics_por_bloco" not in out["schedule_summary"]["1"]
```

- [ ] **Step 2: rodar e ver falhar**

Run: `python -m pytest tests/unit/test_get_ad_schedule.py -k include_metrics -v`
Expected: FAIL — `KeyError: 'metrics_por_bloco'`.

- [ ] **Step 3: implementar**

No `_SCHEMA`, acrescentar:

```python
        "include_metrics": {
            "type": "boolean",
            "default": False,
            "description": "Traz CPA por bloco horario (comercial / fora de hora / fim de semana) por campanha. Custa uma consulta conjunta dia x hora a mais.",
        },
```

No corpo, depois de montar `schedule_summary`, e **só** se a flag vier:

```python
    if args.get("include_metrics", False):
        # `campaign_ids` e obrigatorio aqui: day_hour_metrics_query recusa lista
        # vazia, e varrer a conta inteira nesta conjunta e caro sem necessidade.
        if not campaign_ids:
            return {
                "status": "error",
                "error_message": "include_metrics exige campaign_ids: a conjunta dia x hora "
                "e cara e nao roda sobre a conta inteira.",
            }
        celulas = await _consulta(
            day_hour_metrics_query(campaign_ids=campaign_ids, start=start, end=end),
            parse_day_hour_row,
        )
        for cid, resumo in schedule_summary.items():
            do_cid = [
                MetricCell(m["day_of_week"], m["hour"], m["cost_micros"], m["conversions"])
                for m in celulas
                if m["campaign_id"] == cid
            ]
            resumo["metrics_por_bloco"] = partition_by_blocks(do_cid, BLOCOS_PADRAO)
```

- [ ] **Step 4: rodar e ver passar**

Run: `python -m pytest tests/unit/test_get_ad_schedule.py -v`
Expected: PASS.

- [ ] **Step 5: commit**

```bash
git add src/mcp/tools/get_ad_schedule.py tests/unit/test_get_ad_schedule.py
git commit -m "feat(mcp): get_ad_schedule traz CPA por bloco sob include_metrics"
```

---

### Task 4: `get_performance_breakdown` aceita `campaign` + `hourly`

**Files:**
- Modify: `src/google_ads/performance_breakdown.py:26-44` (`_validate_combo`) e `:62-83` (builder)
- Modify: `src/mcp/tools/get_performance_breakdown.py`
- Test: `tests/unit/test_performance_breakdown.py`

**Interfaces:**
- Consumes: `partition_by_blocks`, `BLOCOS_PADRAO`; `day_hour_metrics_query`.
- Produces: com `level="campaign"` e `breakdown="hourly"`, `rows` passa a ser uma linha **por campanha e por bloco**, com `campaign_id`, `bloco`, `cost_brl`, `conversions`, `cpa_brl`, `cells`.

- [ ] **Step 1: escrever o teste que falha**

```python
def test_campaign_mais_hourly_deixa_de_ser_recusado():
    from src.google_ads.performance_breakdown import _validate_combo

    assert _validate_combo("campaign", "hourly") is None


def test_outros_breakdowns_seguem_recusados_em_entity_level():
    """Só `hourly` abriu. `geo` continua fora: é regra de merge, não nível."""
    from src.google_ads.performance_breakdown import _validate_combo

    assert _validate_combo("campaign", "geo") is not None
    assert _validate_combo("ad_group", "hourly") is not None
```

- [ ] **Step 2: rodar e ver falhar**

Run: `python -m pytest tests/unit/test_performance_breakdown.py -k combo -v`
Expected: FAIL — `_validate_combo("campaign", "hourly")` devolve a mensagem do v0.

- [ ] **Step 3: implementar**

Em `_validate_combo`, antes do bloco `# entity level`:

```python
    # campaign + hourly e o unico combo entity+breakdown aberto: o agregado de
    # conta esconde o que decide (medido na MO-JP: 18,47 numa campanha contra
    # 24,46 na outra, mesma faixa). `geo` segue fora — la o problema e regra de
    # merge (geoTargetConstant duplicado), nao nivel.
    if level == "campaign" and breakdown == "hourly":
        return None
```

No builder, antes do `if level == "campaign":`:

```python
    if level == "campaign" and breakdown == "hourly":
        raise ValueError(
            "campaign+hourly nao passa por este builder: a tool monta a conjunta "
            "com day_hour_metrics_query, que exige campaign_ids explicitos."
        )
```

- [ ] **Step 4: rodar e ver passar**

Run: `python -m pytest tests/unit/test_performance_breakdown.py -v`
Expected: PASS.

- [ ] **Step 5: commit**

```bash
git add src/google_ads/performance_breakdown.py tests/unit/test_performance_breakdown.py
git commit -m "feat(google_ads): campaign+hourly deixa de ser combo recusado"
```

---

### Task 5: o caminho `campaign`+`hourly` na tool, com teto próprio

> ⚠️ **Ordem obrigatoria (Ruling 1 do scan):** esta task vem DEPOIS da Task 4. Invertida, a validacao recusa o combo antes de a tool interceptar. E a Task 4 sozinha deixa um commit em que o combo e aceito na validacao e levanta `ValueError` no builder — aceito dentro da branch porque nao ha deploy entre tasks, e esta task fecha antes do merge.

**Files:**
- Modify: `src/mcp/tools/get_performance_breakdown.py`
- Test: `tests/unit/test_performance_breakdown.py`

**Interfaces:**
- Produces: `raw_grid: bool` no schema; sem ela, partição (3 linhas por campanha); com ela, grade crua com teto `168 × len(campaign_ids)` e `truncated` na resposta.

- [ ] **Step 1: escrever o teste que falha**

```python
@pytest.mark.asyncio
async def test_campaign_hourly_devolve_particao_e_nao_168_celulas(monkeypatch):
    """3 linhas por campanha, nao 168. O default de limit=100 truncaria antes
    de terminar UMA campanha, e tool que trunca em uso normal nasce quebrada."""
    _wire_bd(monkeypatch, celulas=[
        {"campaign_id": "1", "day_of_week": "MONDAY", "hour": 9,
         "cost_micros": 100_000_000, "conversions": 5.0},
        {"campaign_id": "1", "day_of_week": "SUNDAY", "hour": 3,
         "cost_micros": 40_000_000, "conversions": 1.0},
    ])
    out = await mod.get_performance_breakdown({
        "customer_id": "1234567890", "level": "campaign",
        "breakdown": "hourly", "campaign_ids": ["1"],
    })
    blocos = {r["bloco"] for r in out["rows"]}
    assert blocos == {"comercial", "fora_de_hora", "fim_de_semana", "outros"}
    assert len(out["rows"]) == 4
    assert out["truncated"] is False


@pytest.mark.asyncio
async def test_campaign_hourly_exige_campaign_ids(monkeypatch):
    out = await mod.get_performance_breakdown({
        "customer_id": "1234567890", "level": "campaign", "breakdown": "hourly",
    })
    assert out["status"] == "error"
    assert "campaign_ids" in out["error_message"]
```

- [ ] **Step 2: rodar e ver falhar**

Run: `python -m pytest tests/unit/test_performance_breakdown.py -k campaign_hourly -v`
Expected: FAIL — a tool ainda roteia pelo builder antigo.

- [ ] **Step 3: implementar**

No `_SCHEMA`, acrescentar `campaign_ids` (array, `maxItems: 20`) e:

```python
        "raw_grid": {
            "type": "boolean",
            "default": False,
            "description": "So com level=campaign+breakdown=hourly: devolve as 168 celulas dia x hora por campanha em vez da particao de 3 blocos. Caro; exige campaign_ids curto.",
        },
```

No corpo, antes do `run_report` genérico:

```python
    if level == "campaign" and breakdown == "hourly":
        campaign_ids = args.get("campaign_ids") or []
        if not campaign_ids:
            return {
                "status": "error",
                "error_message": "level='campaign' + breakdown='hourly' exige campaign_ids: "
                "a conjunta dia x hora e cara e nao roda sobre a conta inteira.",
            }
        teto = 168 * len(campaign_ids)
        celulas = await run_report(
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=customer_id,
            query=day_hour_metrics_query(campaign_ids=campaign_ids, start=start, end=end),
            row_formatter=parse_day_hour_row,
            operation_name="get_performance_breakdown",
            audit_this_call=True,
            params_summary={"level": level, "breakdown": breakdown},
        )
        truncado = len(celulas) > teto
        if args.get("raw_grid", False):
            return {"status": "ok", "rows": celulas[:teto], "truncated": truncado}
        linhas = []
        for cid in campaign_ids:
            do_cid = [
                MetricCell(m["day_of_week"], m["hour"], m["cost_micros"], m["conversions"])
                for m in celulas
                if m["campaign_id"] == cid
            ]
            for nome, agg in partition_by_blocks(do_cid, BLOCOS_PADRAO).items():
                linhas.append({"campaign_id": cid, "bloco": nome, **agg})
        return {"status": "ok", "rows": linhas, "truncated": truncado}
```

- [ ] **Step 4: rodar e ver passar**

Run: `python -m pytest tests/unit/test_performance_breakdown.py -v`
Expected: PASS.

- [ ] **Step 5: rodar o full sweep e commitar**

```bash
python scripts/check_pre_push_full.py
git add src/mcp/tools/get_performance_breakdown.py tests/unit/test_performance_breakdown.py
git commit -m "feat(mcp): breakdown campaign x hourly com particao default e teto proprio"
```

---

### Task 6: smoke runbook, com o passo de leitura em conta real

**Files:**
- Create: `docs/operacao/phase-3b-43-particao-horaria-smoke.md`

- [ ] **Step 1: escrever o runbook**

Estrutura igual ao `phase-3b-42`: cabeçalho com bloqueadores, "Dados conhecidos pré-smoke" medidos por `run_gaql`, e um teste por comportamento. Mínimo:

- **T1** — `get_ad_schedule(7862230676, campaign_ids=[as 2], include_metrics=true)`. Esperado: `metrics_por_bloco` nas duas campanhas, com a soma dos blocos batendo o custo total do período. **Esta conta tem gasto real**, então é aqui que a substância aparece.
- **T2** — a mesma chamada **sem** a flag: nenhuma consulta com `segments.hour` no audit log, e sem `metrics_por_bloco`.
- **T3** — `get_performance_breakdown(level=campaign, breakdown=hourly, campaign_ids=[as 2])`. Esperado: 8 linhas (2 campanhas × 4 baldes), `truncated: false`.
- **T4** — o mesmo com `raw_grid: true`. Esperado: células cruas, `truncated` coerente com `168 × 2`.
- **T5** — `breakdown=geo` em `level=campaign` continua recusado, com mensagem.

> ⚠️ **Nenhum passo deste smoke muta.** As duas tools são de leitura. Ainda assim exige **sessão MCP nova** (F140) porque os schemas mudaram.

- [ ] **Step 2: commit**

```bash
git add docs/operacao/phase-3b-43-particao-horaria-smoke.md
git commit -m "docs(operacao): smoke 3b.43 da particao horaria"
```

---

## Self-review

**Cobertura do spec.** Item 1 do spec → Tasks 4-5. Item 2 → Task 3. Cardinalidade e teto → Task 5. Blocos parametrizáveis: **reduzido por decisão do Wellington (04/09)** — `BLOCOS_PADRAO` fica **constante** nesta versão, e a parametrização por chamada sai do escopo. Não reabrir: a pergunta foi feita e respondida antes da execução. Se um caso real pedir blocos diferentes, é sprint próprio com o caso em mãos.

**Limitação do Google** (`segments.hour` incompatível com `geographic_view`): já está documentada no spec e não vira código aqui, porque geo saiu do escopo.

**Consistência de tipos.** `partition_by_blocks` devolve `dict[str, dict]`, consumido igual nas Tasks 3 e 5. `MetricCell` é construído do mesmo jeito nos dois lugares — candidato a helper se um terceiro consumidor aparecer, não antes.

**Correção ao spec.** O spec diz que a partição "reusa `partition_metrics`". **Não reusa:** aquela função particiona em `leaving`/`staying` a partir de duas grades, que é outra pergunta. O que se reusa de verdade é `Window`, `covers` e `_agrega`. A Task 1 cria função nova.
