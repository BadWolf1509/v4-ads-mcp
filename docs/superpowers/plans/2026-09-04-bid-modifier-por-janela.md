# F149 — `bid_modifier` por janela — plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: use `superpowers:subagent-driven-development` (recomendado) ou `superpowers:executing-plans`. Os passos usam checkbox (`- [ ]`).

**Goal:** permitir mudar o `bid_modifier` de **uma** faixa horária sem achatar as outras — hoje a única rota disponível exige duas chamadas e passa por um estado em que a campanha para de servir.

**Architecture:** o modificador deixa de ser escalar por chamada e passa a ser atributo de cada item de `windows[]`. O escalar **continua existindo** como default para as janelas que não trouxerem o seu — compatível com todos os chamadores de hoje. O builder **não muda**: ele já lê `item.get("bid_modifier")` por operação; o que muda é de onde o valor vem.

**Tech Stack:** Python 3.13, `google-ads` v24, pytest. Sem dependência nova.

**Spec:** não há spec separada. A análise que fundamenta este plano é a entrada **F149** em [`findings-catalog.md`](../../operacao/findings-catalog.md), com a sequência de duas chamadas medida e a prova de que não há ordenação segura.

## O problema, em uma frase

`get_ad_schedule` **lê** modificador por janela; `update_ad_schedule` só aceita um **por chamada**. A tool lê um estado que não consegue reproduzir.

Os dois caminhos de hoje, medidos em `diff_schedule` (`ad_schedule.py:142-145`):

| Caminho | Efeito |
|---|---|
| `bid_modifier` omitido | preserva **todos**, muda **nenhum** |
| `bid_modifier` informado | muda **todos** do conjunto |

Não há meio-termo. A rota que existe — mandar só a faixa alvo, depois a grade cheia — passa por um estado em que a campanha serve ~50 de 168 horas, com token de 10 min e aval humano entre as duas chamadas. Em orçamento compartilhado isso **inunda a campanha irmã**.

## Global Constraints

- **`key()` da `Window` NÃO pode incluir o modificador.** Identidade é a faixa horária; o modificador é atributo. Se entrar na chave, mudar um modificador vira `remove` + `add`, o critério é **recriado**, e isso custa **~14 dias de re-learning** — exatamente o que o caminho `no_changes` existe para evitar. Esta é a invariante mais cara do plano.
- **`hoje` é da conta** (`resolve_account_today`), nunca do servidor (F141; guard AST).
- **SDK do Google só dentro de `run_blocking`**; leituras via `run_report` (F86/F109).
- **Sem `oneOf`/`allOf`/`anyOf`** em `input_schema` (3b.19B.1) — regra cross-field vive em pré-flight Python.
- **Envelope de mutate vem de `_mutate_common`** (`preview_envelope`/`error_envelope`), nunca montado à mão.
- **Full sweep obrigatório** (`check_pre_push_full.py`, Docker): o plano toca caminho de mutação.
- **Não fechar o sprint com o APPLY ou a RESTAURAÇÃO em `⬜ pending`** (F150/F151).

## Compatibilidade — a regra em uma tabela

Para cada janela do conjunto desejado, o **modificador efetivo** é:

| janela traz `bid_modifier`? | chamada traz o escalar? | efetivo | comportamento |
|---|---|---|---|
| sim | qualquer | o da janela | **novo** |
| não | sim | o escalar | **igual ao de hoje** |
| não | não | `None` = preserva | **igual ao de hoje** |

Chamador que não usar o campo novo vê exatamente o comportamento atual. Isso não é gentileza: a tool está em produção e o `update_ad_schedule` é `always`-loaded.

## File Structure

| Arquivo | Responsabilidade |
|---|---|
| `src/google_ads/ad_schedule.py` (modificar) | `Window.bid_modifier`; `key()` intacta; `diff_schedule` por janela; `schedule_fingerprint` cobre o modificador |
| `src/mcp/tools/update_ad_schedule.py` (modificar) | `_JANELA` ganha o campo; ops carregam o efetivo; preview por janela |
| `src/mcp/tools/apply_change.py` (verificar) | nada a mudar, mas a concorrência otimista passa a cobrir modificador — precisa de teste |
| `src/google_ads/mutates/ad_schedule.py` | **NÃO MUDA** — já lê `item.get("bid_modifier")` por op |
| `tests/unit/test_ad_schedule_domain.py`, `test_update_ad_schedule.py`, `test_apply_change_ad_schedule.py` | testes |
| `docs/operacao/phase-3b-44-bid-modifier-smoke.md` (criar) | smoke |

**Harness real dos testes, para o plano não inventar nome** (os dois sprints anteriores perderam rodadas nisso): `tests/unit/test_update_ad_schedule.py` tem `_wire(monkeypatch, *, grade, orcamentos, metricas, irmas=None)` que devolve o dict capturado do `create_pending`, mais os helpers `_janela_row(cid, day, sh, eh, crit, bm)`, `_orc(cid, shared, rn, status)`, `_cell(...)` e a constante `SEG_SEX`. Use-os.

---

### Task 1: `Window` carrega o modificador, e a chave não

**Files:**
- Modify: `src/google_ads/ad_schedule.py`
- Test: `tests/unit/test_ad_schedule_domain.py`

**Interfaces:**
- Produces: `Window` com sexto campo `bid_modifier: float | None = None`; `Window.key()` **inalterada**, devolvendo as mesmas 5 posições; `window_from_input` lê `bid_modifier` do dict quando presente.

- [ ] **Step 1: escrever os testes que falham**

```python
def test_a_chave_da_janela_ignora_o_bid_modifier():
    """Identidade e a FAIXA HORARIA. Se o modificador entrasse na chave, muda-lo
    viraria remove+add: o criterion seria RECRIADO, e recriar custa ~14 dias de
    re-learning — o mesmo custo que o caminho `no_changes` existe para evitar."""
    a = Window("MONDAY", 7, 0, 17, 0, None)
    b = Window("MONDAY", 7, 0, 17, 0, 1.3)
    assert a.key() == b.key()
    assert len(a.key()) == 5


def test_window_from_input_le_o_modificador_quando_vem():
    assert window_from_input(
        {"day_of_week": "MONDAY", "start_hour": 7, "end_hour": 17, "bid_modifier": 1.3}
    ).bid_modifier == 1.3
    assert window_from_input(
        {"day_of_week": "MONDAY", "start_hour": 7, "end_hour": 17}
    ).bid_modifier is None
```

- [ ] **Step 2: rodar e ver falhar**

Run: `python -m pytest tests/unit/test_ad_schedule_domain.py -k "chave_da_janela or window_from_input_le" -v`
Expected: FAIL — `Window.__init__` não aceita o sexto argumento.

- [ ] **Step 3: implementar**

```python
@dataclass(frozen=True, slots=True)
class Window:
    day_of_week: str
    start_hour: int
    start_minute: int
    end_hour: int
    end_minute: int
    # F149: ATRIBUTO, nao identidade. `key()` deliberadamente nao o inclui —
    # ver o teste que cobra isso e o custo de recriar criterion.
    bid_modifier: float | None = None
```

e em `window_from_input`, acrescente ao construtor:

```python
        bid_modifier=(
            float(d["bid_modifier"]) if d.get("bid_modifier") is not None else None
        ),
```

- [ ] **Step 4: rodar e ver passar**

Run: `python -m pytest tests/unit/test_ad_schedule_domain.py -v`
Expected: PASS. **Rode o arquivo inteiro**: `Window` é construída em vários testes com 5 posicionais, e o default `None` tem que manter todos verdes.

- [ ] **Step 5: commit**

```bash
git add src/google_ads/ad_schedule.py tests/unit/test_ad_schedule_domain.py
git commit -m "feat(ad_schedule): Window carrega bid_modifier como atributo, nao identidade"
```

---

### Task 2: `diff_schedule` decide por janela

**Files:**
- Modify: `src/google_ads/ad_schedule.py`
- Test: `tests/unit/test_ad_schedule_domain.py`

**Interfaces:**
- Consumes: `Window.bid_modifier` (Task 1).
- Produces: `diff_schedule(current, desired, bid_modifier)` mantém a assinatura — o terceiro parâmetro vira o **default** para janelas sem modificador próprio. `to_update` passa a conter apenas as janelas cujo efetivo difere do atual.

- [ ] **Step 1: escrever os testes que falham**

```python
def test_modificador_por_janela_atualiza_so_a_faixa_alvo():
    """O ponto do F149: mudar UMA faixa sem achatar as outras, numa chamada."""
    atual = [
        CurrentWindow(Window("MONDAY", 7, 0, 17, 0), "rn/1", "1", 1.3),
        CurrentWindow(Window("TUESDAY", 7, 0, 17, 0), "rn/2", "2", 0.8),
    ]
    desejada = [
        Window("MONDAY", 7, 0, 17, 0, 1.5),
        Window("TUESDAY", 7, 0, 17, 0),  # sem modificador proprio
    ]
    d = diff_schedule(atual, desejada, None)
    assert d.to_add == () and d.to_remove == ()
    assert [c.criterion_id for c in d.to_update] == ["1"], "so a alvo muda"


def test_escalar_continua_valendo_como_default_das_janelas_sem_modificador():
    """Compatibilidade: quem so passa o escalar ve o comportamento de hoje."""
    atual = [CurrentWindow(Window("MONDAY", 7, 0, 17, 0), "rn/1", "1", 1.0)]
    d = diff_schedule(atual, [Window("MONDAY", 7, 0, 17, 0)], 1.1)
    assert [c.criterion_id for c in d.to_update] == ["1"]


def test_janela_com_modificador_igual_ao_atual_nao_vira_update():
    """Idempotencia: mandar o valor que ja esta la nao emite operacao."""
    atual = [CurrentWindow(Window("MONDAY", 7, 0, 17, 0), "rn/1", "1", 1.3)]
    d = diff_schedule(atual, [Window("MONDAY", 7, 0, 17, 0, 1.3)], None)
    assert d.to_update == ()
```

- [ ] **Step 2: rodar e ver falhar**

Run: `python -m pytest tests/unit/test_ad_schedule_domain.py -k "por_janela or escalar_continua or igual_ao_atual" -v`
Expected: FAIL — o primeiro teste devolve `to_update` vazio, porque hoje o escalar `None` desliga o cálculo inteiro.

- [ ] **Step 3: implementar**

Substitua o bloco `to_update` de `diff_schedule`:

```python
    to_update: list[CurrentWindow] = []
    for k, c in atual_por_chave.items():
        desejada = desejada_por_chave.get(k)
        if desejada is None:
            continue
        # F149: o modificador da JANELA vence; o escalar da chamada e o default
        # de quem nao trouxe o seu. Ambos ausentes = preserva (comportamento de hoje).
        efetivo = desejada.bid_modifier if desejada.bid_modifier is not None else bid_modifier
        if efetivo is not None and c.bid_modifier != efetivo:
            to_update.append(c)
```

- [ ] **Step 4: rodar e ver passar**

Run: `python -m pytest tests/unit/test_ad_schedule_domain.py tests/unit/test_update_ad_schedule.py -v`
Expected: PASS nos dois — os testes existentes de `update_ad_schedule` cobrem o comportamento escalar e **não podem** regredir.

- [ ] **Step 5: commit**

```bash
git add src/google_ads/ad_schedule.py tests/unit/test_ad_schedule_domain.py
git commit -m "feat(ad_schedule): diff por janela com o escalar como default"
```

---

### Task 3: o fingerprint passa a cobrir o modificador

**Files:**
- Modify: `src/google_ads/ad_schedule.py:211-225`
- Test: `tests/unit/test_ad_schedule_domain.py`

**Interfaces:**
- Produces: `schedule_fingerprint` devolve, por campanha, lista ordenada de `[dia, sh, sm, eh, em, bid_modifier]` — **seis** posições, a última podendo ser `None`.

> **Por que isto entra no sprint e não fica para depois.** A concorrência otimista (Ruling 10 do sprint `ad_schedule`) existe para recusar o apply quando alguém mexeu na agenda dentro do TTL de 10 min. Hoje ela compara **só as faixas** — então uma mudança de modificador feita por outra pessoa entre o preview e o apply **passa despercebida**, e o delta é aplicado contra um baseline que já não vale. Enquanto o modificador era escalar isso era pequeno; ao promovê-lo a cidadão de primeira classe, deixar o fingerprint cego seria criar a corrida que a Ruling 10 fechou.

- [ ] **Step 1: escrever o teste que falha**

```python
def test_fingerprint_detecta_mudanca_so_de_bid_modifier():
    """Sem isto, alguem muda o modificador dentro do TTL e o apply nao percebe —
    a concorrencia otimista da Ruling 10 ficaria cega justamente no campo que
    este sprint promove a primeira classe."""
    antes = {"1": [CurrentWindow(Window("MONDAY", 7, 0, 17, 0), "rn/1", "1", 1.0)]}
    depois = {"1": [CurrentWindow(Window("MONDAY", 7, 0, 17, 0), "rn/1", "1", 1.3)]}
    assert schedule_fingerprint(antes, ["1"]) != schedule_fingerprint(depois, ["1"])


def test_fingerprint_continua_sobrevivendo_ao_json():
    """Ruling 10: listas, nunca tuplas — o payload atravessa JSONB e tupla volta lista."""
    import json

    fp = schedule_fingerprint(
        {"1": [CurrentWindow(Window("MONDAY", 7, 0, 17, 0), "rn/1", "1", 1.3)]}, ["1"]
    )
    assert json.loads(json.dumps(fp)) == fp
```

- [ ] **Step 2: rodar e ver falhar**

Run: `python -m pytest tests/unit/test_ad_schedule_domain.py -k fingerprint -v`
Expected: FAIL no primeiro — os dois fingerprints saem iguais, porque a chave ignora o modificador.

- [ ] **Step 3: implementar**

```python
    return {
        cid: sorted(
            ([*c.window.key(), c.bid_modifier] for c in atual.get(cid, [])),
            # Ruling 1 do scan: NUNCA comparar a 6a posicao diretamente — ela pode
            # ser None num registro e float noutro, e `sorted` estouraria com
            # TypeError no caminho de APPLY. Defesa contra estado NAO PROVADO
            # alcancavel (duas criterias com a MESMA faixa e modificadores
            # diferentes) — o SDK v24 recusa faixas sobrepostas
            # (CriterionError.AD_SCHEDULE_TIME_INTERVALS_OVERLAP, revisao final
            # da branch, Fix M5), mas o `key=` fica: e barato e o fingerprint le
            # o ATUAL do Google, nao a entrada validada.
            key=lambda linha: (linha[:5], linha[5] is None, linha[5] or 0.0),
        )
        for cid in campaign_ids
    }
```

> ⚠️ **Ruling 1 do scan de pré-voo — o `sorted` ingênuo estouraria.** Eu havia argumentado que as 5 primeiras posições são sempre distintas porque `validate_windows` recusa sobreposição. **O argumento não vale aqui:** o fingerprint é construído do **atual lido do Google**, não da entrada validada. Duas criterias com a mesma faixa e modificadores diferentes **poderiam** existir se alguém as criasse pela UI ou por outra API — e aí `sorted` levantaria `TypeError: '<' not supported between NoneType and float`, **no caminho de apply**. Daí a `key=` acima. **Escreva o teste do caso degenerado**: duas `CurrentWindow` com faixa idêntica, uma com modificador e outra sem, e assere que o fingerprint sai sem exceção e é determinístico entre duas chamadas.
>
> **Correção (revisão final da branch, Fix M5):** a frase acima afirmava que esse estado **existe** sem probe — e o SDK v24 contradiz: `CriterionError.AD_SCHEDULE_TIME_INTERVALS_OVERLAP` (=56) mostra que o Google **recusa** janelas sobrepostas, então duas criterias com a mesma faixa não foram provadas alcançáveis por nenhuma via. O `key=` continua — é defesa barata contra um estado não provado inalcançável, não prova de que ele exista —, mas a afirmação correta é essa, não a de cima. Afirmar superfície de API externa por analogia, sem probe, é o tripwire escrito do repo (CLAUDE.md).

- [ ] **Step 4: rodar e ver passar**

Run: `python -m pytest tests/unit/test_ad_schedule_domain.py tests/unit/test_apply_change_ad_schedule.py -v`
Expected: PASS. O segundo arquivo cobre a pré-checagem de concorrência e **não pode** regredir.

- [ ] **Step 5: commit**

```bash
git add src/google_ads/ad_schedule.py tests/unit/test_ad_schedule_domain.py
git commit -m "feat(ad_schedule): fingerprint cobre o bid_modifier, nao so a faixa"
```

---

### Task 4: o schema aceita o campo, e as ops carregam o efetivo

**Files:**
- Modify: `src/mcp/tools/update_ad_schedule.py`
- Test: `tests/unit/test_update_ad_schedule.py`

**Interfaces:**
- Consumes: `Window.bid_modifier`, `diff_schedule` (Tasks 1-2).
- Produces: `_JANELA` com `bid_modifier` opcional (`number`, 0.1–10.0); cada op `add` e `update` carrega o **efetivo** daquela janela; `preview[cid].bid_modifier_updated` traz `bid_modifier_antigo`/`bid_modifier_novo` por janela, com o **novo** sendo o efetivo dela.

- [ ] **Step 1: escrever os testes que falham**

```python
@pytest.mark.asyncio
async def test_modificador_por_janela_chega_nas_ops(monkeypatch) -> None:
    grade = [
        _janela_row(day="MONDAY", sh=7, eh=17, crit="1", bm=1.3),
        _janela_row(day="TUESDAY", sh=7, eh=17, crit="2", bm=0.8),
    ]
    cap = _wire(monkeypatch, grade=grade, orcamentos=[_orc()], metricas=[])
    await mod.update_ad_schedule({
        "customer_id": "1234567890", "campaign_ids": ["1"],
        "windows": [
            {"day_of_week": "MONDAY", "start_hour": 7, "end_hour": 17, "bid_modifier": 1.5},
            {"day_of_week": "TUESDAY", "start_hour": 7, "end_hour": 17},
        ],
    })
    ops = cap["payload"]["ops"]
    updates = [o for o in ops if o["kind"] == "update"]
    assert len(updates) == 1, "so a faixa alvo muda; a outra e preservada"
    assert updates[0]["bid_modifier"] == 1.5


@pytest.mark.asyncio
async def test_preview_mostra_o_novo_por_janela_e_nao_o_escalar(monkeypatch) -> None:
    grade = [_janela_row(day="MONDAY", sh=7, eh=17, crit="1", bm=1.3)]
    _wire(monkeypatch, grade=grade, orcamentos=[_orc()], metricas=[])
    out = await mod.update_ad_schedule({
        "customer_id": "1234567890", "campaign_ids": ["1"],
        "windows": [
            {"day_of_week": "MONDAY", "start_hour": 7, "end_hour": 17, "bid_modifier": 1.5}
        ],
    })
    linha = out["preview"]["1"]["bid_modifier_updated"][0]
    assert linha["bid_modifier_antigo"] == 1.3
    assert linha["bid_modifier_novo"] == 1.5
```

- [ ] **Step 2: rodar e ver falhar**

Run: `python -m pytest tests/unit/test_update_ad_schedule.py -k "por_janela or novo_por_janela" -v`
Expected: FAIL — `additionalProperties: False` no `_JANELA` rejeita o campo, ou o preview traz o escalar (`None`).

- [ ] **Step 3: implementar**

Em `_JANELA["properties"]`, acrescente:

```python
        "bid_modifier": {
            "type": "number",
            "minimum": 0.1,
            "maximum": 10.0,
            "description": "Opcional, POR JANELA. Vence o bid_modifier da chamada, que vale como default das janelas sem o seu. Ausente nos dois = preserva o valor atual.",
        },
```

Na construção das ops, troque o escalar pelo efetivo. Para o `add`:

```python
        ops += [
            {
                "kind": "add",
                "campaign_id": cid,
                "window": _w(w),
                "bid_modifier": w.bid_modifier if w.bid_modifier is not None else bid_modifier,
            }
            for w in diff.to_add
        ]
```

**Ruling 2 do scan de pré-voo: a regra do efetivo vira helper, não expressão inline.**
A versão que eu havia escrito usava walrus dentro de uma comprehension — válida, mas ilegível,
e quem editasse depois quebraria sem perceber. Pior: a mesma regra aparece em **três**
call-sites (op de `add`, op de `update`, e `bid_modifier_novo` do preview), e é exatamente o
caso em que ela tem que morar num lugar só — a alternativa é a família do F81, cada lado certo
sozinho e o trio errado junto.

Em `src/google_ads/ad_schedule.py`, junto do domínio:

```python
def modificador_efetivo(janela: Window, escalar: float | None) -> float | None:
    """F149: o modificador da JANELA vence; o escalar da chamada e o default de
    quem nao trouxe o seu; ambos ausentes preserva o valor atual (None)."""
    return janela.bid_modifier if janela.bid_modifier is not None else escalar
```

E na tool, os três call-sites passam a chamá-lo. Para o `update`, a janela desejada vem por
chave:

```python
        desejada_por_chave = {w.key(): w for w in desired}
        ops += [
            {
                "kind": "update",
                "resource_name": c.resource_name,
                "bid_modifier": modificador_efetivo(
                    desejada_por_chave[c.window.key()], bid_modifier
                ),
            }
            for c in diff.to_update
        ]
```

E no preview, `bid_modifier_novo` sai do **mesmo helper**, nunca do escalar direto.

- [ ] **Step 4: rodar e ver passar**

Run: `python -m pytest tests/unit/test_update_ad_schedule.py -v`
Expected: PASS, **incluindo os testes existentes do comportamento escalar** — eles são a prova de compatibilidade.

- [ ] **Step 5: full sweep e commit**

```bash
python scripts/check_pre_push_full.py
git add src/mcp/tools/update_ad_schedule.py tests/unit/test_update_ad_schedule.py
git commit -m "feat(mcp): update_ad_schedule aceita bid_modifier por janela"
```

---

### Task 5: a rota perigosa deixa de ser a única, e o apply cobre a corrida

**Files:**
- Test: `tests/unit/test_update_ad_schedule.py`, `tests/unit/test_apply_change_ad_schedule.py`
- Modify: `src/mcp/tools/update_ad_schedule.py` (só a `_DESCRIPTION`)

**Interfaces:** nenhuma nova. Esta task prova, por teste, que o F149 fechou.

- [ ] **Step 1: escrever os testes que falham**

```python
@pytest.mark.asyncio
async def test_muda_uma_faixa_sem_desligar_as_outras_em_UMA_chamada(monkeypatch) -> None:
    """A regressao que o F149 descreve: antes, a unica rota exigia duas chamadas
    e passava por um estado com a campanha servindo ~50 de 168 horas."""
    grade = [
        _janela_row(day=d, sh=7, eh=17, crit=str(i), bm=1.0)
        for i, d in enumerate(("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY"))
    ]
    cap = _wire(monkeypatch, grade=grade, orcamentos=[_orc()], metricas=[])
    janelas = [dict(w) for w in SEG_SEX]
    janelas[0]["bid_modifier"] = 1.4
    out = await mod.update_ad_schedule(
        {"customer_id": "1234567890", "campaign_ids": ["1"], "windows": janelas}
    )
    ops = cap["payload"]["ops"]
    assert not [o for o in ops if o["kind"] == "remove"], "nenhuma faixa sai de servico"
    assert len(ops) == 1 and ops[0]["kind"] == "update"
    assert out["preview"]["1"]["cobertura"]["reduz"] is False
```

E em `test_apply_change_ad_schedule.py`, a corrida:

```python
@pytest.mark.asyncio
async def test_apply_recusa_quando_so_o_bid_modifier_mudou_no_baseline(monkeypatch):
    """A pre-checagem da Ruling 10 passa a cobrir o modificador. Sem isto, alguem
    muda o lance dentro dos 10 min do TTL e o delta e aplicado as cegas."""
    # baseline do token: modificador 1.0; a reconsulta devolve 1.3
    ...  # siga o padrao do teste de divergencia que ja existe neste arquivo
    assert out["status"] == "error"
    assert "mudou desde o preview" in out["error_message"]
```

- [ ] **Step 2: rodar e ver falhar**

Run: `python -m pytest tests/unit/test_update_ad_schedule.py tests/unit/test_apply_change_ad_schedule.py -k "sem_desligar or so_o_bid_modifier" -v`
Expected: FAIL no segundo se a Task 3 não tiver landado; o primeiro deve passar se as Tasks 1-4 estiverem certas — **se ele falhar, algo nelas está errado**, e é para isso que ele existe.

- [ ] **Step 3: atualizar a descrição da tool**

A `_DESCRIPTION` hoje diz *"Mudar so bid_modifier faz UPDATE do criterion, nao recria"*. Acrescente, na mesma frase, que o modificador pode vir **por janela** dentro de `windows[]`, que ele vence o da chamada, e que o da chamada é o default de quem não trouxer o seu. Sem isso a capacidade existe e ninguém a encontra.

- [ ] **Step 4: rodar e ver passar**

Run: `python scripts/check_pre_push_full.py`
Expected: 7/7.

- [ ] **Step 5: commit**

```bash
git add -A
git commit -m "test(mcp): F149 fechado — uma faixa muda sem desligar as outras"
```

---

### Task 6: smoke runbook

**Files:**
- Create: `docs/operacao/phase-3b-44-bid-modifier-smoke.md`

- [ ] **Step 1: escrever o runbook**

Molde: `docs/operacao/phase-3b-43-particao-horaria-smoke.md`, que é o mais recente. **Não invente números** — cite medição já documentada, ou marque `<medir>`.

⚠️ **Este smoke MUTA.** Diferente do 3b.43, ele exige o gestor autorizando **na sessão que executa** — aval relayado por sessão-par não passa no classificador, medido em 04/09. Diga isso no cabeçalho.

Testes mínimos, na conta de teste `1163862076`:

- **T1** — grade de 5 janelas com `bid_modifier` só na de segunda. Preview: 1 `update`, **zero** `remove`, `cobertura.reduz: false`.
- **T2** — `apply_change`. Confirmar por GAQL que o critério de segunda tem o valor novo e os **outros quatro ficaram intactos** — é a asserção que prova o F149 fechado, e tem que ser por `criterion_id`, nunca por contagem.
- **T3** — os mesmos `criterion_id` de antes: **update via field mask, não recriação**. Recriar custaria ~14 dias de re-learning.
- **T4** — reenviar a mesma grade: `no_changes`, sem token.
- **T5** — janela com `bid_modifier` e chamada com o escalar: a janela vence.
- **T6** — restauração: `clear_schedule: true` devolve `has_schedule: false`, e a conta fica limpa (confirmar por `run_gaql` sem filtro de status).

- [ ] **Step 2: commit**

```bash
git add docs/operacao/phase-3b-44-bid-modifier-smoke.md
git commit -m "docs(operacao): smoke 3b.44 do bid_modifier por janela"
```

---

## Self-review

**Cobertura do F149.** A entrada do catálogo tem três partes: a assimetria read/write (Tasks 1-4), a sequência perigosa de duas chamadas (Task 5 prova que deixou de ser necessária), e o preview honesto — **este já está fechado** pelo PR #34, não entra aqui.

**O que este plano acrescenta ao F149 e não estava no catálogo:** o fingerprint cego a modificador (Task 3). Só apareceu lendo `schedule_fingerprint`, e é o tipo de coisa que promover o campo a primeira classe transforma de detalhe em corrida real.

**Consistência de tipos.** `Window.bid_modifier` é `float | None` em todo lugar. `key()` continua com 5 posições e o fingerprint com 6 — a diferença é deliberada e está coberta por teste nos dois lados.

**Risco maior do plano, dito em voz alta:** `Window` é `frozen`/`slots` e construída posicionalmente em vários testes existentes. O default `None` deveria manter tudo verde, mas a Task 1 manda rodar o arquivo inteiro justamente porque essa suposição é minha, não medida.

**O que fica de fora:** `bid_modifier` por janela no `get_ad_schedule` — ele **já** devolve o modificador por linha; era o write que não acompanhava.
