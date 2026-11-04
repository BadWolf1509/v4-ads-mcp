# Saldo da conta (Google e Meta) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Duas tools de leitura — `get_account_balance` (Google) e `meta_get_account_balance` (Meta) — que dizem quanto falta até os anúncios de UMA conta pararem, em quantos dias, e o que trava primeiro.

**Architecture:** A regra de situação (`sem_teto`/`esgotada`/`acabando`/`com_saldo`/`sem_gasto`/`indeterminada`) e o cálculo de dias vivem num módulo puro neutro `src/saldo.py`. Cada plataforma tem um módulo puro que traduz a resposta crua (`src/google_ads/saldo.py`, `src/meta_ads/saldo.py`) e uma tool fina que só faz I/O pelos executores de sempre (`run_report`, `run_meta_graph_get`). Sem tabela, sem migration, sem dependência nova.

**Tech Stack:** Python 3.13, `google-ads` v24 (GAQL), Graph API v22.0 via `httpx` (executor existente), pytest.

**Spec:** `docs/superpowers/specs/2026-10-28-saldo-da-conta-design.md` — leia inteiro antes da Task 1. Os números dos fixtures vêm da §1 dele.

## Global Constraints

- Restante Google = `adjusted_spending_limit_micros − amount_served_micros` — **nunca** `approved_spending_limit_micros` (spec §1.1).
- `spend_cap: "0"` = sem limite; valores Meta de conta em **centavos** (string) (spec §1.9).
- No pós-pago Meta, `balance` sai como `a_faturar_brl`, nunca com a palavra "saldo" na chave (spec §1.10).
- Saldo pré-pago ilegível → `None` + texto cru + aviso `saldo_prepago_ilegivel`; **nunca** número parcial nem exceção (spec §3.3).
- Pré-pago Meta com saldo ilegível é sempre `indeterminada`, mesmo com `spend_cap` (spec §3.3).
- Dias restantes = restante ÷ média dos **últimos 7 dias completos** no fuso da conta, sem hoje; "esgotada" compara com a média dos **dias com gasto nos últimos 30 dias** (spec §3.1).
- `acabando` = `dias_restantes ≤ 7`.
- **Dia ausente na resposta = gasto zero.** Medido em 29/10: a Graph omite dias sem entrega (Cantina 7 linhas, Dr. Dérick 12, de 30) e devolve ordenado por gasto, não por data; o Google também não traz dia sem impressão (Cantina Google: 20 linhas em 30 dias).
- Toda chamada das duas tools com `audit_this_call=True`.
- Todo payload: `aproximado: true`.
- Gate: `D:/v4-ads-mcp/.venv/Scripts/python.exe scripts/check_pre_push.py` (rodar mudo, ler `$?`, nunca com pipe antes do `&&`). Uma task por commit.
- Mensagens de commit: `feat(mcp): …` / `feat(meta_ads): …` / `docs(operacao): …`, terminando com `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Conta Google sem nenhuma linha em `account_budget`** (conta nova, faturamento não configurado) → `indeterminada` com motivo, não exceção nem `sem_teto`. Teste na Task 3.
2. **Mais de um orçamento `APPROVED` na mesma conta** (um encerrado e um vigente; dois vigentes) → usa o de início mais recente e avisa quando há dois vigentes. Teste na Task 3.
3. **`display_string` em outro idioma ou formato** (`"Available balance (R$633.45 BRL)"`, `"Saldo disponível (R$1.234,56 BRL)"`, string vazia, `None`) → só o formato pt-BR medido vira número; o resto é `None`. Teste na Task 5.
4. **Gestor sem permissão de faturamento** → `AUTHORIZATION_ERROR` só na consulta de `account_budget` vira `indeterminada`; qualquer outro erro sobe como hoje. Teste na Task 4.
5. **Média de 7 dias zero com restante positivo e data de fim próxima** → `sem_gasto`, com `dias_ate_fim` preenchido e `dias_restantes: null`. Teste na Task 2.

---

### Task 1: `/insights` diário — parâmetro `time_increment` no construtor + sonda versionada

**Files:**
- Modify: `src/meta_ads/insights.py` (`build_insights_call`, linhas ~85-139)
- Create: `scripts/probe_meta_time_increment.py`
- Test: `tests/unit/test_insights_time_increment.py`

**Interfaces:**
- Produces: `build_insights_call(*, level, ad_account_id, start, end, limit, breakdowns=None, time_increment: int | None = None) -> tuple[str, dict[str, Any]]`. Com `time_increment` não-`None`, `params["time_increment"] = str(time_increment)`; com `None`, o dict é **idêntico** ao de antes.

- [ ] **Step 1: Write the failing tests**

```python
def test_sem_time_increment_a_chamada_e_a_de_antes():
    edge, p = build_insights_call(level="account", ad_account_id="act_1",
                                  start=date(2026, 9, 1), end=date(2026, 9, 30), limit=100)
    assert "time_increment" not in p
    assert p["sort"] == "spend_descending"
    assert p["use_unified_attribution_setting"] == "true"

def test_time_increment_vira_string():
    _, p = build_insights_call(level="account", ad_account_id="act_1",
                               start=date(2026, 9, 1), end=date(2026, 9, 30), limit=100,
                               time_increment=1)
    assert p["time_increment"] == "1"
```

- [ ] **Step 2: Run** `.venv/Scripts/python.exe -m pytest tests/unit/test_insights_time_increment.py -v` — Expected: FAIL (`unexpected keyword argument 'time_increment'`).
- [ ] **Step 3: Implement** o kwarg. No comentário do param, registre a sonda: controle `time_increment=abc` volta **HTTP 400** `(#100) … must be one of the following values: monthly, all_days`, `time_increment=1` volta 200 com uma linha por dia **com entrega** (dias sem entrega omitidos), ordenadas por gasto.
- [ ] **Step 4: Create `scripts/probe_meta_time_increment.py`** no formato de `scripts/probe_meta_combinacoes.py` (reusa `BASE` e `secret` de lá; token no header; imprime só status, contagem de linhas, as 4 primeiras datas e a mensagem de erro). Três casos: `time_increment=1`, controle `abc`, sem o param. Docstring com o resultado de 29/10 acima. Rode: `.venv/Scripts/python.exe -m scripts.probe_meta_time_increment act_3709029949237406` — Expected: `200`, `400`, `200`.
- [ ] **Step 5: Run** o teste — PASS; e `tests/unit/test_meta_metricas_guards.py` — PASS.
- [ ] **Step 6: Commit** `feat(meta_ads): time_increment opcional no build_insights_call, sondado com controle`.

### Task 2: Regra comum `src/saldo.py`

**Files:**
- Create: `src/saldo.py`
- Test: `tests/unit/test_saldo_regra.py`

**Interfaces:**
- Produces:
  - `Situacao = Literal["sem_teto", "esgotada", "acabando", "com_saldo", "sem_gasto", "indeterminada"]`
  - `def serie_diaria(gastos: Mapping[date, float], *, ontem: date, dias: int) -> list[float]` — os `dias` dias que terminam em `ontem`, dia ausente = `0.0`.
  - `def media_7d(gastos: Mapping[date, float], *, ontem: date) -> float`
  - `def media_dias_com_gasto(gastos: Mapping[date, float], *, ontem: date) -> float | None` — janela de 30 dias; `None` se nenhum dia > 0.
  - `@dataclass(frozen=True) class Classificacao: situacao: Situacao; dias_restantes: float | None; dias_pelo_dinheiro: float | None; trava_por_data: bool; motivo: str | None`
  - `def classificar(*, restante: float, media7: float, media_com_gasto: float | None, dias_ate_fim: int | None = None) -> Classificacao` — só para conta COM teto e legível (`sem_teto`/`indeterminada` são decididos pelo módulo da plataforma antes).

Ordem de avaliação dentro de `classificar` (spec §3.1):
1. `dias_ate_fim is not None and dias_ate_fim < 0` → `esgotada`, motivo `"orçamento da conta encerrado"`.
2. `restante <= 0` → `esgotada`; `media_com_gasto is not None and restante < media_com_gasto` → `esgotada`, motivo `"restante menor que um dia de gasto"`.
3. `media7 == 0` → `sem_gasto`, `dias_restantes=None`, motivo `"sem gasto nos últimos 7 dias"`.
4. `dias_pelo_dinheiro = restante / media7`; `dias_restantes = min(dias_pelo_dinheiro, dias_ate_fim)` quando há data; `trava_por_data = dias_ate_fim is not None and dias_ate_fim < dias_pelo_dinheiro`.
5. `dias_restantes <= 7` → `acabando`, senão `com_saldo`. Dias arredondados a 1 casa.

- [ ] **Step 1: Write the failing tests** (um por linha, valores da spec):

```python
def test_serie_preenche_dia_ausente_com_zero():
    s = serie_diaria({date(2026, 10, 27): 10.0}, ontem=date(2026, 10, 28), dias=3)
    assert s == [0.0, 10.0, 0.0]

def test_esgotada_com_media_7d_zero():  # Cantina Google, spec §1.4
    c = classificar(restante=0.85, media7=0.0, media_com_gasto=55.0)
    assert c.situacao == "esgotada"

def test_sem_gasto_com_dinheiro():
    c = classificar(restante=500.0, media7=0.0, media_com_gasto=55.0, dias_ate_fim=3)
    assert (c.situacao, c.dias_restantes) == ("sem_gasto", None)

def test_sem_gasto_sem_historico_e_restante_positivo():
    assert classificar(restante=10.0, media7=0.0, media_com_gasto=None).situacao == "sem_gasto"

def test_restante_zero_sem_historico_e_esgotada():
    assert classificar(restante=0.0, media7=0.0, media_com_gasto=None).situacao == "esgotada"

def test_hosp_ocular_acabando():  # R$ 313,22 a ~R$ 49/dia
    c = classificar(restante=313.22, media7=49.23, media_com_gasto=49.23)
    assert c.situacao == "acabando" and c.dias_restantes == 6.4

def test_data_de_fim_trava_antes():
    c = classificar(restante=1000.0, media7=50.0, media_com_gasto=50.0, dias_ate_fim=5)
    assert (c.dias_restantes, c.trava_por_data, c.situacao) == (5, True, "acabando")

def test_data_de_fim_passada_e_esgotada():
    assert classificar(restante=1000.0, media7=50.0, media_com_gasto=50.0,
                       dias_ate_fim=-1).situacao == "esgotada"

def test_com_saldo():
    assert classificar(restante=1000.0, media7=50.0, media_com_gasto=50.0).situacao == "com_saldo"
```

- [ ] **Step 2: Run** `pytest tests/unit/test_saldo_regra.py -v` — FAIL (módulo inexistente).
- [ ] **Step 3: Implement** `src/saldo.py` (sem I/O, sem import de `google_ads`/`meta_ads`).
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `feat(mcp): regra comum de saldo e dias restantes`.

### Task 3: Google — queries e módulo puro

**Files:**
- Modify: `src/google_ads/queries/overview.py` (duas funções novas no fim)
- Create: `src/google_ads/saldo.py`
- Test: `tests/unit/test_saldo_google.py`

**Interfaces:**
- Consumes: `src.saldo.classificar`, `media_7d`, `media_dias_com_gasto` (Task 2).
- Produces:
  - `def saldo_orcamento_conta_query() -> tuple[str, dict[str, Any]]` — `FROM account_budget WHERE account_budget.status = 'APPROVED' ORDER BY account_budget.approved_start_date_time DESC LIMIT 50`, campos: `id`, `approved_spending_limit_type`, `adjusted_spending_limit_micros`, `amount_served_micros`, `total_adjustments_micros`, `approved_start_date_time`, `approved_end_date_time`, `approved_end_time_type`, `pending_proposal.account_budget_proposal` (`pendente = bool(...)`). As duas queries, na forma exata, foram validadas com `validate_gaql` na `2935187268` em 29/10 (`valid: true`). `filtros = {"status": "APPROVED"}`.
  - `def gasto_diario_conta_query(inicio: date, fim: date) -> tuple[str, dict[str, Any]]` — `SELECT segments.date, metrics.cost_micros FROM customer WHERE <gaql_date_clause(inicio, fim)> ORDER BY segments.date LIMIT 40`; `filtros` com a janela.
  - `def montar_saldo_google(orcamentos: list[dict[str, Any]], gastos: Mapping[date, float], *, hoje: date) -> dict[str, Any]` — `orcamentos` são as linhas já formatadas pelo row formatter da Task 4 (chaves: `tipo_limite: str`, `limite_ajustado_micros: int | None`, `gasto_micros: int`, `ajustes_micros: int`, `inicio: str`, `fim: str | None`, `tipo_fim: str`, `pendente: bool`).

`montar_saldo_google`:
- Lista vazia → `situacao: "indeterminada"`, motivo `"conta sem orçamento de conta"`.
- Escolhe a linha de `inicio` mais recente; se houver **duas ou mais** com `inicio <= agora` e (`fim` ausente ou `fim >= hoje`), aviso `"mais de um orçamento de conta vigente; usado o de início mais recente (não medido, spec §1.5)"`.
- `tipo_limite == "INFINITE"` → `situacao: "sem_teto"`, `tipo_de_teto: "sem_teto"`, `restante_brl: None`, `dias_restantes: None`.
- Senão: `restante = (limite_ajustado − gasto)/1e6`; `dias_ate_fim = (date(fim) − hoje).days` quando `fim`; chama `classificar`; `trava_primeiro = "data_fim" if trava_por_data else "saldo"`.
- Payload: `situacao, motivo, tipo_de_teto, restante_brl, limite_ajustado_brl, gasto_acumulado_brl, ajustes_brl, dias_restantes, dias_ate_fim, data_fim, trava_primeiro, media_diaria_7d_brl, orcamento_pendente, aproximado: True, avisos`.

- [ ] **Step 1: Write the failing tests**

```python
HOSP = {"tipo_limite": "UNSPECIFIED", "limite_ajustado_micros": 34_782_190_000,
        "gasto_micros": 34_468_970_000, "ajustes_micros": 161_190_000,
        "inicio": "2021-02-26 15:37:54", "fim": None, "tipo_fim": "FOREVER", "pendente": False}

def test_hosp_ocular_bate_com_fundos_disponiveis():
    r = montar_saldo_google([HOSP], {}, hoje=date(2026, 10, 28))
    assert r["restante_brl"] == 313.22   # aprovado daria 152.03: o teste falha se trocar

def test_infinite_e_sem_teto():
    r = montar_saldo_google([{**HOSP, "tipo_limite": "INFINITE", "limite_ajustado_micros": None}],
                            {}, hoje=date(2026, 10, 28))
    assert (r["situacao"], r["restante_brl"]) == ("sem_teto", None)

def test_sem_linha_e_indeterminada():
    assert montar_saldo_google([], {}, hoje=date(2026, 10, 28))["situacao"] == "indeterminada"

def test_dois_vigentes_avisa_e_usa_o_mais_recente(): ...  # assere o aviso e o limite do mais recente

def test_data_de_fim_trava_primeiro(): ...  # fim em 3 dias, saldo para 20 → trava_primeiro == "data_fim"

def test_queries_sao_validas_e_declaram_filtros():
    gaql, filtros = saldo_orcamento_conta_query()
    assert "adjusted_spending_limit_micros" in gaql and "ORDER BY" in gaql
    assert filtros == {"status": "APPROVED"}
```

- [ ] **Step 2: Run** `pytest tests/unit/test_saldo_google.py -v` — FAIL.
- [ ] **Step 3: Implement** as duas queries e `montar_saldo_google`. Use `micros_to_currency`/`arredondado` de `src/google_ads/queries/_common.py`.
- [ ] **Step 4: Run** o teste + `tests/unit/test_filters_applied_e_derivado.py` — PASS.
- [ ] **Step 5: Commit** `feat(mcp): leitura do orcamento da conta Google para o saldo`.

### Task 4: Tool `get_account_balance`

**Files:**
- Create: `src/mcp/tools/get_account_balance.py` (`# bucket: always`, padrão de `get_budget_pacing.py`)
- Modify: `tests/unit/test_tools_schemas.py` (nome nas duas listas: esperado e não-inesperado)
- Test: `tests/unit/test_get_account_balance_tool.py`

**Interfaces:**
- Consumes: as duas queries e `montar_saldo_google` (Task 3); `resolve_account_today`; `run_report`.
- Produces: tool `get_account_balance`, schema `{"customer_id": {"type": "string", "pattern": "^[0-9]{10}$"}}`, required `customer_id`, `additionalProperties: false`.

Fluxo: `hoje = await resolve_account_today(customer_id)`; `ontem = hoje − 1`; consulta 1 (`account_budget`) com `audit_this_call=True`, capturando `GoogleAdsFriendlyError` **só** com `code == "AUTHORIZATION_ERROR"` → resposta `situacao: "indeterminada"`, motivo `"sem permissão de faturamento nesta conta"`, sem a consulta 2; consulta 2 (gasto `ontem−29 … ontem`) com `audit_this_call=True`; `montar_saldo_google`; resposta = payload + `customer_id` + `filters_applied` (os dois `filtros`, chaveados `orcamento` e `gasto`). Ambas com `operation_name="get_account_balance"`.

Description (PT-BR, sem markdown): diz que é uma conta só; que o restante é o "Fundos disponíveis" do Faturamento (ajustado − gasto); o vocabulário das 6 situações em uma linha cada; que `sem_teto` não tem número e não diz forma de pagamento; que dias = restante ÷ média dos 7 dias fechados e que a data de fim conta como freio (`trava_primeiro`); que o valor é aproximado (gasto atrasa horas); e termina com `" filters_applied diz o recorte que a query aplicou."`.

- [ ] **Step 1: Write the failing tests** (com `run_report` e `resolve_account_today` patchados, contexto via `set_current`, como em `test_filters_applied_chega_na_resposta.py`):
  - `test_authorization_error_vira_indeterminada` — 1ª chamada levanta `GoogleAdsFriendlyError("x", code="AUTHORIZATION_ERROR")`; assere `situacao == "indeterminada"` e que `run_report` foi chamado **uma** vez.
  - `test_outro_erro_sobe` — `code="QUOTA_ERROR"` → `pytest.raises(GoogleAdsFriendlyError)`.
  - `test_as_duas_consultas_auditam` — todas as chamadas a `run_report` com `audit_this_call=True`.
  - `test_janela_de_gasto_termina_ontem_no_fuso_da_conta` — `hoje=2026-10-28` → a 2ª query cobre `2026-09-28..2026-10-27`.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement** a tool e adicione o nome às duas listas de `test_tools_schemas.py`.
- [ ] **Step 4: Run** o gate inteiro (guards de registry, `filters_applied`, razão, F57, `run_blocking`) — Expected: `All pre-push checks passed`.
- [ ] **Step 5: Commit** `feat(mcp): get_account_balance (saldo da conta Google)`.

### Task 5: Meta — módulo puro

**Files:**
- Create: `src/meta_ads/saldo.py`
- Test: `tests/unit/test_saldo_meta.py`

**Interfaces:**
- Consumes: `src.saldo` (Task 2); `META_ACCOUNT_STATUS_LABELS` de `src/meta_ads/labels.py`.
- Produces:
  - `def saldo_do_texto(display_string: str | None) -> Decimal | None` — só casa `^Saldo disponível \(R\$\s?(\d{1,3}(?:\.\d{3})*,\d{2}) BRL\)$`; qualquer outra coisa → `None`.
  - `def montar_saldo_meta(conta: dict[str, Any], gastos: Mapping[date, float], *, hoje: date) -> dict[str, Any]` — `conta` é o JSON cru de `GET /act_<id>` (spec §1.6).

`montar_saldo_meta`:
- `prepago = conta["is_prepay_account"]`; `cap = int(conta["spend_cap"])`, `gasto = int(conta["amount_spent"])`; `freio_limite = (cap − gasto)/100 if cap > 0 else None`.
- Pré-pago: `saldo = saldo_do_texto(fsd.display_string)`. `saldo is None` → `indeterminada`, motivo `"saldo pré-pago ilegível"`, `saldo_prepago_texto` cru, `teto_pelo_limite_brl = freio_limite`, `restante_brl`/`dias_restantes` `None`, aviso `saldo_prepago_ilegivel`.
- Freios presentes → `restante = min`, `trava_primeiro` = `"saldo_prepago"` ou `"limite_de_gastos"` (empate: `"saldo_prepago"`); chama `classificar` (sem `dias_ate_fim`).
- Pós-pago sem limite → `sem_teto`; com limite → `classificar` sobre `freio_limite`.
- Sempre: `status_conta`, `status_conta_label`, `disable_reason`, `forma_de_pagamento` (`"pre_pago"`/`"pos_pago"`), `forma_de_pagamento_texto` (o `display_string`), `a_faturar_brl` (só pós-pago, `balance/100`), `cupons` (lista crua informativa, fora do restante), `freio_saldo_brl`, `freio_limite_brl`, `media_diaria_7d_brl`, `aproximado: True`, `avisos`. `account_status != 1` → aviso `"conta com status <label>: os anúncios podem estar parados independente do saldo"`.
- Moeda ≠ `"BRL"` → `ValueError` com mensagem clara (a tool converte em erro; spec §3.3, escolha registrada).

- [ ] **Step 1: Write the failing tests** com os JSON crus de 28/10 (spec §1, copiados da sondagem):
  - `test_texto_medido` → `Decimal("633.45")`; `test_milhar` `"Saldo disponível (R$1.234,56 BRL)"` → `Decimal("1234.56")`; `test_zero` → `Decimal("0.00")`; `test_ingles_e_none` `"Available balance (R$633.45 BRL)"` → `None`; `test_vazio_e_none` (`""`, `None`) → `None`.
  - `test_cantina_limite_trava_antes` → `freio_saldo_brl == 633.45`, `freio_limite_brl == 556.49`, `trava_primeiro == "limite_de_gastos"`, `restante_brl == 556.49`.
  - `test_3_lagoas_esgotada` (`spend_cap == amount_spent == "15000"`) → `esgotada`.
  - `test_mdo_jp_prepago_sem_saldo_sem_limite` → `esgotada`.
  - `test_mi_importss_pendente` → `sem_teto`, `a_faturar_brl == 1218.58`, aviso de status `PAGAMENTO_PENDENTE`.
  - `test_ilegivel_com_limite_e_indeterminada` → `indeterminada`, `teto_pelo_limite_brl == 556.49`, `restante_brl is None`.
  - `test_cupom_nao_entra_no_restante` (Dr. Dérick) → `sem_teto`, `cupons` com 1 item.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `feat(meta_ads): leitura do saldo e dos freios da conta Meta`.

### Task 6: Tool `meta_get_account_balance`

**Files:**
- Create: `src/mcp/tools/meta_get_account_balance.py` (`# bucket: always`, padrão de `meta_get_account_overview.py`)
- Modify: `tests/unit/test_tools_schemas.py` (nome nas duas listas)
- Test: `tests/unit/test_meta_get_account_balance_tool.py`

**Interfaces:**
- Consumes: `montar_saldo_meta` (Task 5); `build_insights_call(..., time_increment=1)` (Task 1); `metricas_da_linha`; `resolve_meta_account_today`; `run_meta_graph_get`.
- Produces: tool `meta_get_account_balance`, schema `{"ad_account_id": {"type": "string", "pattern": "^act_\\d+$"}}`, required.

Fluxo: `hoje = await resolve_meta_account_today(id)`; chamada 1 `edge=f"/{id}"`, `params={"fields": "name,account_status,disable_reason,is_prepay_account,spend_cap,amount_spent,balance,currency,funding_source_details"}`; chamada 2 `build_insights_call(level="account", start=ontem−29, end=ontem, limit=40, time_increment=1)`; gasto de cada linha por `metricas_da_linha(linha)["spend_brl"]`, data por `linha["date_start"]`; `montar_saldo_meta`. As duas com `audit_this_call=True`, `operation_name="meta_get_account_balance"`. Erro de executor → `{"status": "error", "error_message": meta_error_message(e)}` como no overview.

Description: uma conta; os dois freios e `trava_primeiro`; que o saldo pré-pago é lido do texto da Meta e vem `null` + texto se o formato mudar; que `a_faturar_brl` no pós-pago não é saldo; cupons fora do restante; status de conta; dias pela média de 7 dias fechados; aproximado. **Como a tool alcança `metricas_da_linha`, os guards de `tests/unit/test_meta_metricas_guards.py` exigem na description as quatro frases do contrato (`FRASE_DO_NULL`, `FRASE_DO_CTR`, `FRASE_DA_ATRIBUICAO`, `FRASE_DA_JANELA`) e todas as chaves de `metricas_da_linha({})` — inclua-as numa frase final dizendo que só `spend_brl` é usado.**

- [ ] **Step 0: `ads_get_field_context`** (Meta MCP oficial) nos 9 fields da chamada 1 — regra F53/F54/F55. Se o MCP não estiver disponível na sessão, **pare e reporte**; não pule.
- [ ] **Step 1: Write the failing tests** (`run_meta_graph_get` e o relógio patchados):
  - `test_dias_sem_entrega_contam_como_zero` — insights com 2 linhas fora de ordem de data → `media_diaria_7d_brl` = soma/7.
  - `test_insights_pede_time_increment` — a 2ª chamada leva `params["time_increment"] == "1"` e `sort`/atribuição de sempre.
  - `test_edge_da_conta_e_a_conta_gateada` — 1ª chamada `edge == "/act_1"` e `ad_account_id == "act_1"`.
  - `test_as_duas_chamadas_auditam`.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement** + listas do `test_tools_schemas.py`.
- [ ] **Step 4: Run** o gate inteiro — `All pre-push checks passed`.
- [ ] **Step 5: Commit** `feat(meta_ads): meta_get_account_balance (saldo da conta Meta)`.

### Task 7: Fecho de docs e smoke

**Files:**
- Modify: `CLAUDE.md` (68 → 70 tools; 62 Google + 6 Meta → 63 + 7), `docs/operacao/estado-atual.md` (tools novas no ar, aguardando smoke)
- Create: `docs/operacao/smoke-saldo-da-conta.md` (tabela do spec §5 com colunas "esperado" e "medido")

- [ ] **Step 1:** Atualize os números e o estado; o smoke vai como checklist com as 6 contas do spec §5 + "gestor comum, se houver".
- [ ] **Step 2:** Gate + full sweep (`scripts/check_pre_push_full.py`, Docker) — o diff toca executores só por consumo, mas é a regra para tool nova.
- [ ] **Step 3: Commit** `docs(operacao): saldo da conta no catalogo e roteiro de smoke`.
- [ ] **Step 4 (depois do merge e do deploy, sessão NOVA — F140):** rode o smoke chamando as tools; preencha "medido"; Hosp Ocular comparada com a tela de Faturamento do dia.
