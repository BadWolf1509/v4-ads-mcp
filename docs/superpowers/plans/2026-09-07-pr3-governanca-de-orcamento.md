# PR 3 — Governança de orçamento

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fechar as duas portas pelas quais o orçamento de uma conta de cliente muda sem que o gestor confirme — e apertar o guard que deveria ter impedido a segunda.

**Architecture:** `update_campaign_budget` passa a ler `campaign_budget.explicitly_shared` e a declarar no preview as campanhas irmãs que a mudança atinge, espelhando o que `update_ad_schedule` já faz. `apply_recommendation` passa a ler `recommendation.type` e a exigir confirmação para os tipos que mexem em orçamento ou lance, mostrando o valor novo. Os guards do F57 e do F112 passam de "por arquivo" e "qualquer `.level`" para a propriedade que de fato protege.

**Tech Stack:** Python 3.13, google-ads v24, asyncpg, pytest, mypy strict, ruff. Sem dependência nova.

**Spec:** [`docs/superpowers/specs/2026-09-06-correcoes-varredura-design.md`](../specs/2026-09-06-correcoes-varredura-design.md) — seção 4, "PR 3".

## Global Constraints

- **Whitelist de enum sai de probe empírica, nunca de analogia.** É a regra do `CLAUDE.md` e a razão de F87, F89 e dos mocks do F84. A probe já foi feita (seção "Probe" abaixo) — use os valores medidos.
- **`classify()` computado tem que ter `.level` LIDO.** Computar e descartar é o F112, e é o defeito que abriu a porta do C2.
- **Preview de mutação de orçamento mostra o valor novo.** Confirmar sem ver o número não é confirmar.
- **Simetria com `update_ad_schedule`:** o C1 espelha o bloco `shared_budgets` que já existe (`src/mcp/tools/update_ad_schedule.py:494-535`). Consistência entre as duas tools vale mais que uma regra nova.
- **Se um hook ou classificador bloquear, PARE e reporte.** Nunca contorne com outra ferramenta.
- `mypy --strict` e `ruff` limpos. **Full sweep obrigatório** (`check_pre_push_full.py`) — este PR toca `_mutate_common`, pré-flight de mutate e queries.
- Para cada guard novo ou apertado, **nomeie a mutação de produção que o derruba** e prove rodando, em cópia fora do repositório. Nunca `git checkout`.

---

## Probe — já feita em 2026-09-07, contra contas reais. Não refaça; use.

**Superfície GAQL de `recommendation`:**

| campo | válido? |
|---|---|
| `recommendation.type` | ✅ |
| `recommendation.campaign` | ✅ |
| `recommendation.campaign_budget_recommendation` (a **mensagem** inteira) | ✅ |
| `recommendation.campaign_budget_recommendation.current_budget_amount_micros` (a **folha**) | ❌ `Unrecognized fields` |
| `recommendation.impact.potential_metrics.cost_micros` | ❌ `Unrecognized fields` |

**A armadilha, e é a classe F87/F89:** o proto do SDK **tem** as folhas
(`.venv/.../v24/resources/types/recommendation.py:575,580`), mas o GAQL **não as
expõe individualmente**. Seleciona-se a mensagem; o SDK a popula; o Python lê as
folhas do objeto. Quem escrever a query pelo proto erra.

**Os dois tipos de orçamento existem vivos e o campo popula inteiro:**

```
1171969590 (Montes Claros), type=CAMPAIGN_BUDGET, campanha 22883395595
  current_budget_amount_micros     =  50000000   (R$  50,00/dia)
  recommended_budget_amount_micros = 140000000   (R$ 140,00/dia)   2,8x

1171969590, campanha 22922100363
  current      =  50000000  (R$  50,00)
  recommended  = 180000000  (R$ 180,00)   3,6x

7621086021 (Goiânia), type=MARGINAL_ROI_CAMPAIGN_BUDGET, campanha 23646410138
  campo: recommendation.marginal_roi_campaign_budget_recommendation
  current      = 40300000  (R$ 40,30)
  recommended  = 78000000  (R$ 78,00)   1,9x
```

**O que isso significa hoje, antes deste PR:** `apply_recommendation` aplica um
aumento de **3,6×** no orçamento diário com uma chamada só, sem token, sem preview,
e **sem nunca mostrar o número**. Não é hipótese — está disponível agora.

**Distribuição de tipos medida (`aggregate_by`):**

```
7621086021: KEYWORD 55 · SEARCH_PARTNERS_OPT_IN 2 · DISPLAY_EXPANSION_OPT_IN 2 ·
            MARGINAL_ROI_CAMPAIGN_BUDGET 2 · SET_TARGET_CPA 1 ·
            DYNAMIC_IMAGE_EXTENSION_OPT_IN 1 · PERFORMANCE_MAX_OPT_IN 1
1171969590: KEYWORD 8 · CAMPAIGN_BUDGET 2 · DYNAMIC_IMAGE_EXTENSION_OPT_IN 1
7862230676: KEYWORD 6 · SEARCH_PARTNERS_OPT_IN 2 · DISPLAY_EXPANSION_OPT_IN 2 ·
            USE_BROAD_MATCH_KEYWORD 2   (nenhum de orçamento)
```

**O enum tem 55 tipos** (`.venv/.../v24/enums/types/recommendation_type.py`). Os
**17** que tocam orçamento ou lance, extraídos do enum e não de memória:

```
CAMPAIGN_BUDGET · FORECASTING_CAMPAIGN_BUDGET · MARGINAL_ROI_CAMPAIGN_BUDGET ·
MOVE_UNUSED_BUDGET · ENHANCED_CPC_OPT_IN · MAXIMIZE_CLICKS_OPT_IN ·
MAXIMIZE_CONVERSIONS_OPT_IN · MAXIMIZE_CONVERSION_VALUE_OPT_IN ·
TARGET_CPA_OPT_IN · TARGET_ROAS_OPT_IN · SET_TARGET_CPA · SET_TARGET_ROAS ·
RAISE_TARGET_CPA · RAISE_TARGET_CPA_BID_TOO_LOW · LOWER_TARGET_ROAS ·
FORECASTING_SET_TARGET_CPA · FORECASTING_SET_TARGET_ROAS
```

---

## Estrutura de arquivos

| arquivo | responsabilidade |
|---|---|
| `src/mcp/tools/update_campaign_budget.py` | C1 — ler `explicitly_shared`, declarar as irmãs |
| `src/google_ads/queries/ad_schedule.py` | reusar `campaigns_on_budgets_query` (já existe) |
| `src/mcp/tools/apply_recommendation.py` | C2 — ler o tipo, gate por família, ler `.level` |
| `src/google_ads/queries/recommendations.py` (criar ou estender) | a query de tipo + detalhe |
| `src/governance/blast_radius.py` | classificação por tipo de recomendação |
| `tests/unit/test_structural_guards.py` | guard do F57 por função |
| `tests/unit/test_blast_radius_bate_com_as_tools.py` | guard do F112 sem "qualquer `.level`" |
| `tests/unit/test_call_tool_valida_schema.py` (criar) | R7-C2, o órfão |
| `src/mcp/tools/apply_change.py`, `_mutate_common.py`, `mutations.py` | os Importantes do R1 |

---

### Task 1: C1 — `update_campaign_budget` enxerga orçamento compartilhado

**Files:**
- Modify: `src/mcp/tools/update_campaign_budget.py:56-66` (a GAQL) e `:100-118` (o preview)
- Test: `tests/unit/test_update_campaign_budget.py`

**Interfaces:**
- Consumes: `campaigns_on_budgets_query` e `parse_campaign_on_budget_row` de `src/google_ads/queries/ad_schedule.py` — já existem, usados por `update_ad_schedule`.
- Produces: o preview ganha `shared_budget` (dict ou `None`).

**O defeito, medido:** a query em `:56-66` seleciona `campaign.id`, `campaign.name`, `campaign_budget.resource_name` e `campaign_budget.amount_micros` — **não** `explicitly_shared`. O builder (`src/google_ads/mutates/campaigns.py:48-56`) escreve no **recurso orçamento**, então quando ele é do portfólio a mudança atinge todas as campanhas. O summary (`:100-104`) nomeia **uma**.

Na conta `7862230676`, medido em 02-04/09: as duas campanhas não-removidas dividem o orçamento `15803241252`, `explicitly_shared: true`, R$ 310,00/dia.

- [ ] **Step 1: Escrever o teste que falha**

```python
def test_preview_declara_as_irmas_quando_o_orcamento_e_compartilhado() -> None:
    """C1: o preview nomeia UMA campanha e a mutação atinge o portfólio.

    Sem isto, baixar o orçamento "da JPA" de R$ 310 para R$ 100 corta também a
    CAB, que não aparece em lugar nenhum do preview.
    """
    envelope = _preview_com(
        explicitly_shared=True,
        irmas=[{"campaign_id": "22169885957", "campaign_name": "[GPC][CAB]", "status": "ENABLED"}],
    )
    sb = envelope["shared_budget"]
    assert sb is not None, "orçamento compartilhado não declarado no preview"
    assert sb["campaigns_outside_batch"] == [
        {"campaign_id": "22169885957", "campaign_name": "[GPC][CAB]", "status": "ENABLED"}
    ]
    assert "atinge" in sb["warning_pt"].lower()


def test_orcamento_exclusivo_nao_gera_bloco() -> None:
    """Contraprova: sem ela, um `shared_budget` sempre-presente passaria."""
    assert _preview_com(explicitly_shared=False, irmas=[])["shared_budget"] is None
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest tests/unit/test_update_campaign_budget.py -q`
Expected: FAIL — `KeyError: 'shared_budget'`.

- [ ] **Step 3: Acrescentar `explicitly_shared` à GAQL e o bloco ao preview**

Na query, somar `campaign_budget.explicitly_shared`. No `_row_formatter`, somar
`"explicitly_shared": bool(row.campaign_budget.explicitly_shared)`. Quando `true`,
consultar as irmãs com `campaigns_on_budgets_query` e montar o bloco **no mesmo
formato** que `update_ad_schedule.py:520-535` produz — mesmas chaves, mesma
semântica de `campaigns_outside_batch`.

**Avisa, não recusa** — é a decisão já tomada para o `update_ad_schedule`, e
consistência entre as duas vale mais que uma regra nova.

- [ ] **Step 4: Rodar e ver passar**

- [ ] **Step 5: Provar a mordida**

Em cópia fora do repositório, remova `explicitly_shared` da GAQL: o primeiro teste
tem que ficar vermelho. Restaure. Depois faça o bloco ser sempre emitido: o segundo
tem que ficar vermelho. **Sabotagem sozinha não prova guard** — as duas direções.

- [ ] **Step 6: Commit**

```bash
git add src/mcp/tools/update_campaign_budget.py tests/unit/test_update_campaign_budget.py
git commit -m "fix(mcp): update_campaign_budget declara as campanhas irmas do portfolio (C1)"
```

---

### Task 2: C2 — gate por tipo no `apply_recommendation`

**Files:**
- Modify: `src/mcp/tools/apply_recommendation.py` (inteiro — hoje tem 70 linhas)
- Modify: `src/governance/blast_radius.py:247-252`
- Create: query do tipo em `src/google_ads/queries/recommendations.py`
- Test: `tests/unit/test_apply_recommendation.py`

**Interfaces:**
- Produces: `_TIPOS_QUE_CONFIRMAM: frozenset[str]` — os 17 da probe.

**O defeito:** `blast_radius.py:247-252` classifica `apply_recommendation` como
`AUTO`; `apply_recommendation.py:45` computa `risk` e chama
`run_recommendation_action` direto — **nunca cria pending, nunca devolve preview**.
`risk.level` não é lido em lugar nenhum; `risk.reason` vira o campo cosmético
`auto_applied_reason`. É o F112 no pior caso.

O schema (`:11-27`) aceita **qualquer** `recommendation_resource_name`, sem
whitelist de tipo — enquanto `get_recommendations.py:48-49` traduz para o gestor
exatamente `CAMPAIGN_BUDGET` → *"Ajustar orcamento da campanha"*.

- [ ] **Step 1: Escrever os testes que falham**

```python
def test_recomendacao_de_orcamento_exige_confirmacao() -> None:
    """C2: hoje aplica direto um aumento de 3,6x sem mostrar o número.

    Medido em 07/09 na conta 1171969590: CAMPAIGN_BUDGET vivo com
    current=R$ 50,00 e recommended=R$ 180,00.
    """
    env = _aplicar(tipo="CAMPAIGN_BUDGET", current_micros=50_000_000,
                   recommended_micros=180_000_000)
    assert env["status"] == "preview", "orçamento aplicado sem confirmação"
    assert env["confirmation_token"]
    assert env["current_amount_brl"] == 50.0
    assert env["recommended_amount_brl"] == 180.0, "o preview não mostra o valor novo"


def test_recomendacao_de_keyword_segue_auto() -> None:
    """Contraprova: sem ela, 'tudo confirma' passaria e o gate seria inútil."""
    assert _aplicar(tipo="KEYWORD")["status"] == "applied"


@pytest.mark.parametrize("tipo", sorted(_TIPOS_QUE_CONFIRMAM))
def test_todo_tipo_da_familia_confirma(tipo: str) -> None:
    """Os 17 vêm da probe do enum, não de memória."""
    assert _aplicar(tipo=tipo)["status"] == "preview"
```

- [ ] **Step 2: Rodar e ver falhar**

Expected: FAIL — `status` vem `applied` nos três.

- [ ] **Step 3: Implementar**

A tool lê `recommendation.type` **e** a mensagem de detalhe por GAQL antes de
decidir. **Use os nomes que a probe validou:** seleciona-se
`recommendation.campaign_budget_recommendation` (a mensagem), nunca as folhas — o
GAQL as recusa mesmo estando no proto.

`classify` recebe o tipo e devolve o nível; **a tool lê `risk.level`** e ramifica.
Tipo na família → `create_pending` + `preview_envelope`, com `current` e
`recommended` em BRL. Fora dela → o caminho de hoje.

- [ ] **Step 4: Rodar e ver passar**

- [ ] **Step 5: Provar a mordida**

Em cópia fora do repositório: (a) tire um tipo da whitelist e veja o teste
parametrizado daquele tipo ficar vermelho; (b) faça a tool ignorar `risk.level` e
aplicar sempre — o primeiro teste fica vermelho; (c) faça a tool confirmar tudo — a
**contraprova** fica vermelha. As três.

- [ ] **Step 6: Commit**

---

### Task 3: Os guards que deveriam ter impedido

**Files:**
- Modify: `tests/unit/test_structural_guards.py:29-40` (F57)
- Modify: `tests/unit/test_blast_radius_bate_com_as_tools.py:70-80,96-104` (F112)
- Modify: `CLAUDE.md` **só se couber** (13 bytes de folga) e `docs/operacao/findings-catalog.md`

**O F57 hoje é por ARQUIVO:** `test_build_client_for_manager_callsites_have_gate`
pergunta se o arquivo que chama `build_client_for_manager` também chama
`ensure_account_access` — então um executor novo, num arquivo que já gateia noutra
função, passa verde. A mensagem do próprio guard diz *"grep TODA função"*: ele
enuncia a propriedade que não verifica.

**Correção:** usar `h.funcoes()` e perguntar **por função**.

**⚠️ Este é o ponto do PR que pode crescer sozinho.** Apertar o guard pode revelar
executor sem gate que ninguém vê hoje. **Se revelar, PARE e relate** — é Crítico, e
a decisão de como fechá-lo não é do implementador.

**O F112 hoje casa qualquer `.level`:** `le_level = any(isinstance(no, ast.Attribute)
and no.attr == "level" ...)` aceita `qualquer_coisa.level`. E o piso `>= 15` é
frouxo para uma derivação que deveria ser exata.

- [ ] **Step 1: Provar a ausência antes de apertar (F57)**

Rode o guard novo contra a árvore atual **antes** de commitá-lo. Se acusar, pare.

- [ ] **Step 2: Reescrever o F57 por função, com sabotagem**

Sabotagem: função nova em arquivo que **já gateia noutra função**, chamando
`build_client_for_manager` sem `ensure_account_access`. Tem que ficar vermelha — é
o caso que o guard por arquivo deixava passar.

- [ ] **Step 3: Reescrever o F112**

`.level` só conta quando o objeto é o resultado de `classify` — não qualquer
atributo. Sabotagem: uma variável qualquer chamada `x.level` num arquivo que ignora
`risk.level`; hoje passa, depois tem que ficar vermelha.

- [ ] **Step 4: Trocar o piso `>= 15` por derivação exata**

- [ ] **Step 5: Corrigir a contagem "17 das 26"** no `CLAUDE.md` e no catálogo para
a medida real. **Confira o orçamento do `CLAUDE.md` antes de escrever** — 13 bytes.

- [ ] **Step 6: Commit**

---

### Task 4: R7-C2 — o órfão que eu deixei fora da spec

**Files:**
- Create: `tests/unit/test_call_tool_valida_schema.py`

`src/mcp/server.py:121` é a **única** linha que aplica `pattern`, `enum` e
`required` de todas as 74 tools. Dela dependem a whitelist do F17-F19 e a
não-interpolação GAQL do F87. **Nenhum teste exercita `call_tool`.**

Isto não estava em frente nenhuma da spec — é buraco meu, e o PR 3 é o lugar
natural porque é o mesmo caminho de mutate.

- [ ] **Step 1: Teste que chama `call_tool` com argumento que viola o schema** e
afirma a recusa. Cubra `pattern` (um `customer_id` de 9 dígitos), `enum` (um valor
fora da whitelist) e `required` (campo ausente).

- [ ] **Step 2: Provar a mordida** — remova a validação em cópia; os três ficam
vermelhos. É o único guard dessa linha.

- [ ] **Step 3: Commit**

---

### Task 5: Os Importantes do R1 (lote)

Cinco correções na mesma família, no mesmo caminho. Vão num despacho só.

- **R1-I1** `apply_change.py:298-309` descarta `partial_failures` no caminho default: 5 tools em lote perdem o motivo de cada falha.
- **R1-I2** `mutations.py:347-362` — o audit grava o **tentado**, nunca o **aplicado**.
- **R1-I3/I4** `customer_match.py:209-210,307` descarta a resposta de partial-failure e reporta o lote inteiro; `:153-155,198-222` tem 3 passos não-atômicos e audit de erro com `provider_request_id=""` contradizendo o próprio comentário.
- **R1-I5** `remove_audience.py:72-79,88-90` — `_classify_partial` é código morto e a description promete `already_removed` per-row que nunca acontece.
- **R1-I6** `import_offline_conversions.py:266-268` — o preview calcula `utc_offset` em `datetime.now`, o upload calcula por timestamp.

Cada um com teste que falha antes.

---

### Task 6: Os pequenos

- `level="write"` asserido por teste (R7-I3): trocar por `"read"` hoje deixa a suíte verde.
- As 5 tools que montam envelope à mão passam a usar `applied_envelope`.
- Literais de TTL fora das descrições (`apply_change.py:89`) — usar `DEFAULT_TTL_MINUTES`.

---

### Task 7: Documentação

Abrir **F158 — o orçamento mudava por duas portas com governança oposta**, com: a
probe (incluindo o 3,6× vivo), a assimetria `blast_radius.py:90` × `:247`, o F112
como causa (classificar e descartar), e o que ficou de fora. Atualizar
`estado-atual.md`. **Não escrever no `CLAUDE.md`** sem conferir os 13 bytes.

---

## Auto-revisão do plano

**Cobertura da spec (PR 3 da seção 4):** C1 (Task 1) ✓; C2 com gate por tipo e probe
empírica (Task 2) ✓; guards F57 e F112 mais a contagem (Task 3) ✓; os seis
Importantes do R1 (Task 5, que junta I3 e I4 por serem o mesmo arquivo) ✓;
`level="write"`, envelopes e TTL (Task 6) ✓.

**Acréscimo à spec, declarado:** a Task 4 (R7-C2) não estava em frente nenhuma —
buraco meu ao escrever a spec, corrigido aqui.

**Risco que pode mudar o tamanho do PR:** o Step 1 da Task 3. Se o guard do F57
por função acusar executor vivo, o PR cresce e a decisão é do Wellington.

**Consistência de tipos:** `_TIPOS_QUE_CONFIRMAM` é `frozenset[str]` com os 17 da
probe; `classify` devolve `RiskClassification` com `.level: RiskLevel`; o bloco
`shared_budget` da Task 1 usa as mesmas chaves que `update_ad_schedule` já emite.
