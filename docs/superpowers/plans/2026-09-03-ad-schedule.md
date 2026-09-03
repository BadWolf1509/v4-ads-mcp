# `get_ad_schedule` + `update_ad_schedule` — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Duas tools MCP: ler a grade de veiculação (dia × hora) de campanhas Google Ads, e definir a grade completa com dry-run que mostra o CPA do que sai contra o que fica — sem recriar critérios idênticos e com confirmação de estado por GAQL.

**Architecture:** Módulo de domínio puro (`src/google_ads/ad_schedule.py`: janelas, validação, diff por conteúdo, partição de métricas), módulo de queries GAQL, um builder registrado em `update_ad_schedule`, duas tools no padrão `get_assets`/`remove_asset_link` (mesma spec, já mesclados), uma entrada no `classify`, e um branch pós-apply no `apply_change` que reconsulta a grade. O diff é calculado **no dry-run** e viaja no payload pendente; o builder é burro — o que o gestor confirma é exatamente o que se aplica.

**Tech Stack:** Python 3.13, `google-ads` v24 (`AdScheduleInfo`, `CampaignCriterionOperation.create|update|remove`), GAQL `campaign_criterion` / `campaign` com `segments.day_of_week` + `segments.hour`, MCP registry (`@register_tool`), `run_report`/`run_mutation`, pytest + `make_capture_client`.

**Spec:** [`docs/superpowers/specs/2026-09-02-ad-schedule-e-assets-design.md`](../specs/2026-09-02-ad-schedule-e-assets-design.md) — seções **3, 4, 8 (itens 1–5, 9, 10) e 9**. Seções 5–7 (assets) já estão implementadas e servem de padrão.

**Decisões do Wellington (03/09) que fecham a §10:** janela default do preview = **30 dias, com override** (`date_range`/`start_date`+`end_date`); lote sobre orçamento compartilhado = **avisar no preview, agrupado por orçamento — não recusar**.

**Probes já rodadas (não repita; cite):**
- 02/09 (`validate_gaql`): `campaign_criterion.ad_schedule.{day_of_week,start_hour,start_minute,end_hour,end_minute}`, `campaign_criterion.bid_modifier`, `campaign_criterion.status` com `WHERE campaign_criterion.type = 'AD_SCHEDULE'` — válido. `campaign_budget.explicitly_shared` — válido (`true` nos dois orçamentos ENABLED da 786-223-0676).
- 03/09 (`run_gaql`, conta 786-223-0676): **conjunta dia × hora sobre `campaign`** — `SELECT campaign.id, segments.day_of_week, segments.hour, metrics.cost_micros, metrics.conversions FROM campaign WHERE segments.date BETWEEN ... AND campaign.status = 'ENABLED'` devolve linhas como `{"campaign": {"id": "21359547724"}, "segments": {"day_of_week": "MONDAY", "hour": 8}, "metrics": {"cost_micros": "314676351", "conversions": 13.998888}}`. `segments.hour` é **int 0–23**; `cost_micros` chega como **string**.
- 03/09 (SDK v24, por import): `MinuteOfHour = {ZERO, FIFTEEN, THIRTY, FORTY_FIVE}` (+ sentinelas); `DayOfWeek = MONDAY…SUNDAY`; `AdScheduleInfo` tem **exatamente** `start_minute, end_minute, start_hour, end_hour, day_of_week`; `MutateOperation.campaign_criterion_operation` existe com `update_mask | create | update | remove`; `CampaignCriterion` tem `campaign, criterion_id, bid_modifier, status, ad_schedule`.

## Global Constraints

- `input_schema` **sem** `oneOf/allOf/anyOf` (Anthropic rejeita); regra condicional vai em pré-flight Python, como `remove_asset_link._preflight_validate`.
- **`hoje` é da conta**: `today = await resolve_account_today(customer_id)` uma vez, passado a `resolve_date_window(..., today=today)`. Nunca `datetime.now`/`date.today` em tool Google (guard AST `test_no_server_clock_in_google_tools.py` falha).
- Literal de usuário em GAQL só via `gaql_escape`/`gaql_string_literal`/`gaql_in_list` (`src/google_ads/queries/_gaql.py`). Ids validados como `^[0-9]+$` no schema podem ir em `IN (...)` direto, como `queries/assets.py` faz.
- **`LIMIT` sempre com `ORDER BY`** (F98/F88); `limit` default 200, teto 1000, `truncated` na resposta (spec §3).
- Envelopes só de `src/mcp/tools/_mutate_common.py`: `error_envelope(op, msg, *, customer_id=..., **extra)`, `preview_envelope(op, customer_id, blast_summary, token, *, confirmation_reason=..., **extra)`. TTL via `DEFAULT_TTL_MINUTES` (nunca literal 10).
- Mutate: `classify(operation=..., params=...)` → `create_pending(conn, manager_id=, session_id=, customer_id=, operation_type=, payload=, blast_summary=)` → `preview_envelope`; payload leva `__target_count__`, `__partial_failure__: True`, `__params_summary__`. Apply via `apply_change` (genérico chama `run_mutation`, que despacha ao builder registrado por `@register_builder("update_ad_schedule")` em `src/google_ads/mutates/_common.py`).
- Builder: assinatura `(client, customer_id: str, payload: dict) -> list[MutateOperation]`; testes **só** com `make_capture_client()` (`tests/unit/fixtures/proto_capture.py`), nunca `MagicMock` (F16/F42/F44). Enums via `client.enums.XEnum[nome]`; `update_mask` via `client.copy_from(op.update_mask, FieldMask(paths=[...]))` com `from google.protobuf.field_mask_pb2 import FieldMask` (idioma de `mutates/ad_groups.py`).
- Tool nova: `bucket="defer"`, description PT-BR começando com `[DEFER]`; tests de tool importam o módulo no topo (dispara o `@register_tool`) e usam o fixture `_ctx` de `test_remove_asset_link.py`. O conftest compartilhado já stuba `resolve_account_today` em todo módulo de tool que o importa.
- Gate antes de todo commit: `python scripts/check_pre_push.py > /dev/null 2>&1; echo $?` — **mudo**, lendo `$?`; nunca pipe entre o gate e `&&`. Commits `feat(mcp): …` com trailer `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- **Tool nova só aparece para sessão MCP nova** (F140): o smoke exige reconectar.
- Não existe `today` default em lugar nenhum; não existe fallback silencioso para janela inválida (recusa com mensagem citando os 4 minutos válidos — spec §8.1).

---

## File Structure

| Arquivo | Responsabilidade |
|---|---|
| **Create** `src/google_ads/ad_schedule.py` | Domínio puro: `Window`, `CurrentWindow`, `MetricCell`, `ScheduleDiff`; `window_from_input`, `validate_windows`, `diff_schedule`, `hours_per_week`, `covers`, `partition_metrics`, `summarize_current`. Zero I/O. |
| **Create** `src/google_ads/queries/ad_schedule.py` | Quatro builders GAQL + quatro parsers de linha (`SimpleNamespace`-friendly, como `queries/assets.py`). |
| **Create** `src/google_ads/mutates/ad_schedule.py` | `@register_builder("update_ad_schedule") build_update_ad_schedule` — traduz `payload["ops"]` (pré-calculado) em `MutateOperation`s. |
| **Create** `src/mcp/tools/get_ad_schedule.py` | Tool read: grade + `schedule_summary` por campanha (`has_schedule`, `hours_per_week`, `budget_is_shared`). |
| **Create** `src/mcp/tools/update_ad_schedule.py` | Tool mutate always-CONFIRM: validação → estado atual + orçamentos + métricas → diff → `no_changes` ou preview com CPA e aviso por orçamento → `create_pending`. |
| **Modify** `src/governance/blast_radius.py` (antes do default `unknown operation`, ~linha 250) | Entrada explícita `update_ad_schedule` → CONFIRM. |
| **Modify** `src/mcp/tools/apply_change.py:118-140` (caminho genérico) | Branch `update_ad_schedule`: roda `run_mutation` e reconsulta a grade (§4.6), devolvendo `resulting_schedule`. |
| **Create** `tests/unit/test_ad_schedule_domain.py`, `test_ad_schedule_queries.py`, `test_update_ad_schedule_builder.py`, `test_get_ad_schedule.py`, `test_update_ad_schedule.py`, `test_apply_change_ad_schedule.py` | Um arquivo por unidade. |
| **Create** `docs/operacao/phase-3b-42-ad-schedule-smoke.md` | Runbook do smoke (§7 para confirmação por status; §4.2 para a asserção de CPA). |
| **Modify** `docs/operacao/estado-atual.md` | Contagem de tools 66 → **68**; registrar o sprint. |

**Convenção de horas (fixa neste plano, documentada na description):** uma janela `{start_hour, start_minute, end_hour, end_minute}` cobre os instantes `[start, end)`. Métricas são por **hora cheia** (`segments.hour`); a célula `(dia, h)` conta como coberta se o instante `h:00` está em `[start, end)`. Janelas com minutos 15/30/45 são aproximadas à hora cheia no preview, e o preview diz isso (`"metrics_granularity": "hora cheia; janelas com minutos são aproximadas"`). Campanha **sem** critério de `AD_SCHEDULE` serve **24×7**: no domínio, `before=None` significa "cobre tudo".

---

### Task 1: Domínio — `Window`, `validate_windows`, `hours_per_week`

**Files:**
- Create: `src/google_ads/ad_schedule.py`
- Test: `tests/unit/test_ad_schedule_domain.py`

**Interfaces:**
- Produces:
  - `DIAS: tuple[str, ...]` = `("MONDAY","TUESDAY","WEDNESDAY","THURSDAY","FRIDAY","SATURDAY","SUNDAY")`
  - `MINUTO_ENUM: dict[int, str]` = `{0: "ZERO", 15: "FIFTEEN", 30: "THIRTY", 45: "FORTY_FIVE"}` e `ENUM_MINUTO` (inverso, com `"UNSPECIFIED": 0`)
  - `@dataclass(frozen=True, slots=True) class Window: day_of_week: str; start_hour: int; start_minute: int; end_hour: int; end_minute: int` com `def key(self) -> tuple[str, int, int, int, int]` e `def start_min(self) -> int` (minutos desde 00:00) / `def end_min(self) -> int`
  - `def window_from_input(d: dict[str, Any]) -> Window` — minutos default 0
  - `def validate_windows(windows: list[dict[str, Any]]) -> str | None` — mensagem PT-BR ou `None`
  - `def hours_per_week(windows: Iterable[Window]) -> float`

- [ ] **Step 1: Escrever os testes que falham**

```python
"""Dominio puro do ad_schedule (spec §4.1, §8.1): janela, validacao, cobertura.

Restricoes lidas do SDK v24 por import, nao por analogia: `MinuteOfHour` so
aceita ZERO|FIFTEEN|THIRTY|FORTY_FIVE; `DayOfWeek` e MONDAY..SUNDAY.
"""

from __future__ import annotations

import pytest

from src.google_ads.ad_schedule import (
    DIAS,
    MINUTO_ENUM,
    Window,
    hours_per_week,
    validate_windows,
    window_from_input,
)


def _w(day="MONDAY", sh=7, sm=0, eh=17, em=0) -> dict:
    return {"day_of_week": day, "start_hour": sh, "start_minute": sm, "end_hour": eh, "end_minute": em}


def test_dias_e_minutos_espelham_o_sdk() -> None:
    assert DIAS == ("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY")
    assert MINUTO_ENUM == {0: "ZERO", 15: "FIFTEEN", 30: "THIRTY", 45: "FORTY_FIVE"}


def test_window_from_input_default_de_minuto_e_zero() -> None:
    w = window_from_input({"day_of_week": "MONDAY", "start_hour": 7, "end_hour": 17})
    assert w == Window("MONDAY", 7, 0, 17, 0)
    assert w.key() == ("MONDAY", 7, 0, 17, 0)


def test_minuto_fora_do_quarto_de_hora_e_recusado_citando_os_quatro_validos() -> None:
    """Spec §8.1: 07:10 nao existe na API; recusar na entrada, nao deixar o Google recusar."""
    err = validate_windows([_w(sm=10)])
    assert err is not None
    for v in ("0", "15", "30", "45"):
        assert v in err


@pytest.mark.parametrize("bad", [_w(sh=-1), _w(eh=25), _w(sh=17, eh=7), _w(sh=7, eh=7), _w(day="MONDAI")])
def test_hora_invertida_fora_de_faixa_ou_dia_invalido_e_recusado(bad: dict) -> None:
    assert validate_windows([bad]) is not None


def test_fim_as_24_00_e_valido() -> None:
    """24:00 e o unico jeito de dizer 'ate o fim do dia' — o Google aceita end_hour=24."""
    assert validate_windows([_w(sh=18, eh=24)]) is None


def test_janelas_sobrepostas_no_mesmo_dia_sao_recusadas() -> None:
    assert validate_windows([_w(sh=7, eh=12), _w(sh=11, eh=17)]) is not None


def test_janelas_adjacentes_no_mesmo_dia_sao_aceitas() -> None:
    assert validate_windows([_w(sh=7, eh=12), _w(sh=12, eh=17)]) is None


def test_mesma_faixa_em_dias_diferentes_nao_e_sobreposicao() -> None:
    assert validate_windows([_w(day="MONDAY"), _w(day="TUESDAY")]) is None


def test_hours_per_week_soma_as_janelas() -> None:
    ws = [window_from_input(_w(day=d, sh=7, eh=17)) for d in ("MONDAY", "TUESDAY")]
    assert hours_per_week(ws) == 20.0
    assert hours_per_week([window_from_input(_w(sh=7, sm=30, eh=8))]) == 0.5
```

- [ ] **Step 2: Rodar para ver falhar**

Run: `python -m pytest tests/unit/test_ad_schedule_domain.py -q`
Expected: `ImportError: cannot import name ... from 'src.google_ads.ad_schedule'` (módulo não existe) — erro de coleta. Crie o arquivo vazio com só as constantes `DIAS`/`MINUTO_ENUM` e rode de novo: agora `ImportError` de `Window` etc. — é o RED honesto de "função não existe".

- [ ] **Step 3: Implementar o mínimo**

```python
"""Dominio puro do ad_schedule (spec §4): janela, validacao, diff por conteudo, metricas.

Zero I/O. Tudo que sabe de fuso, GAQL ou SDK fica fora daqui.

Semantica de janela: cobre [start, end). `end_hour=24` com `end_minute=0`
significa "ate o fim do dia". Restricoes lidas do SDK v24 (`AdScheduleInfo`):
minutos so 0/15/30/45; dias MONDAY..SUNDAY.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

DIAS: tuple[str, ...] = ("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY")
MINUTO_ENUM: dict[int, str] = {0: "ZERO", 15: "FIFTEEN", 30: "THIRTY", 45: "FORTY_FIVE"}
ENUM_MINUTO: dict[str, int] = {v: k for k, v in MINUTO_ENUM.items()} | {"UNSPECIFIED": 0, "UNKNOWN": 0}


@dataclass(frozen=True, slots=True)
class Window:
    day_of_week: str
    start_hour: int
    start_minute: int
    end_hour: int
    end_minute: int

    def key(self) -> tuple[str, int, int, int, int]:
        return (self.day_of_week, self.start_hour, self.start_minute, self.end_hour, self.end_minute)

    def start_min(self) -> int:
        return self.start_hour * 60 + self.start_minute

    def end_min(self) -> int:
        return self.end_hour * 60 + self.end_minute


def window_from_input(d: dict[str, Any]) -> Window:
    return Window(
        day_of_week=str(d["day_of_week"]),
        start_hour=int(d["start_hour"]),
        start_minute=int(d.get("start_minute", 0)),
        end_hour=int(d["end_hour"]),
        end_minute=int(d.get("end_minute", 0)),
    )


def validate_windows(windows: list[dict[str, Any]]) -> str | None:
    """Mensagem PT-BR se algo for invalido; None se OK. Recusa ANTES do Google."""
    validos = ", ".join(str(m) for m in MINUTO_ENUM)
    parsed: list[Window] = []
    for i, d in enumerate(windows):
        w = window_from_input(d)
        if w.day_of_week not in DIAS:
            return f"windows[{i}]: day_of_week '{w.day_of_week}' invalido; use um de {', '.join(DIAS)}"
        for nome, m in (("start_minute", w.start_minute), ("end_minute", w.end_minute)):
            if m not in MINUTO_ENUM:
                return (
                    f"windows[{i}]: {nome}={m} nao existe na API do Google Ads — "
                    f"minutos validos: {validos} (nao e possivel agendar 07:10)"
                )
        if not (0 <= w.start_hour <= 23):
            return f"windows[{i}]: start_hour={w.start_hour} fora de 0..23"
        if not (0 <= w.end_hour <= 24) or (w.end_hour == 24 and w.end_minute != 0):
            return f"windows[{i}]: end_hour deve estar em 0..24 (24 so com end_minute=0)"
        if w.end_min() <= w.start_min():
            return f"windows[{i}]: fim ({w.end_hour:02d}:{w.end_minute:02d}) tem que ser depois do inicio"
        parsed.append(w)
    por_dia: dict[str, list[Window]] = {}
    for w in parsed:
        por_dia.setdefault(w.day_of_week, []).append(w)
    for dia, ws in por_dia.items():
        ws_sorted = sorted(ws, key=lambda x: x.start_min())
        for a, b in zip(ws_sorted, ws_sorted[1:], strict=False):
            if b.start_min() < a.end_min():
                return f"janelas sobrepostas em {dia}: {a.start_hour:02d}:{a.start_minute:02d}-{a.end_hour:02d}:{a.end_minute:02d} e {b.start_hour:02d}:{b.start_minute:02d}-{b.end_hour:02d}:{b.end_minute:02d}"
    return None


def hours_per_week(windows: Iterable[Window]) -> float:
    return round(sum((w.end_min() - w.start_min()) / 60 for w in windows), 2)
```

- [ ] **Step 4: Rodar para ver passar**

Run: `python -m pytest tests/unit/test_ad_schedule_domain.py -q`
Expected: todos PASS.

- [ ] **Step 5: Commit**

```bash
git add src/google_ads/ad_schedule.py tests/unit/test_ad_schedule_domain.py
git commit -F <arquivo> # "feat(mcp): ad_schedule — dominio: janela, validacao no quarto de hora, horas/semana"
```

---

### Task 2: Domínio — `diff_schedule` por conteúdo (conjunto, não incremento; idempotente)

**Files:**
- Modify: `src/google_ads/ad_schedule.py`
- Test: `tests/unit/test_ad_schedule_domain.py` (append)

**Interfaces:**
- Consumes: `Window` (Task 1)
- Produces:
  - `@dataclass(frozen=True, slots=True) class CurrentWindow: window: Window; resource_name: str; criterion_id: str; bid_modifier: float | None`
  - `@dataclass(frozen=True, slots=True) class ScheduleDiff: to_add: tuple[Window, ...]; to_remove: tuple[CurrentWindow, ...]; to_update: tuple[CurrentWindow, ...]` com `def is_empty(self) -> bool` e `def op_count(self) -> int`
  - `def diff_schedule(current: list[CurrentWindow], desired: list[Window], bid_modifier: float | None) -> ScheduleDiff`

- [ ] **Step 1: Testes que falham**

```python
from src.google_ads.ad_schedule import CurrentWindow, ScheduleDiff, diff_schedule


def _cur(day="MONDAY", sh=7, eh=17, bm=None, rn=None) -> CurrentWindow:
    w = Window(day, sh, 0, eh, 0)
    return CurrentWindow(window=w, resource_name=rn or f"customers/1/campaignCriteria/9~{day}{sh}", criterion_id="1", bid_modifier=bm)


def test_grade_completa_e_conjunto_uma_janela_remove_as_outras_quatro() -> None:
    """Spec §8.2 — a guarda do erro conjunto-vs-incremento. Falha contra qualquer
    implementacao que trate a entrada como delta."""
    current = [_cur(day=d) for d in ("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY")]
    diff = diff_schedule(current, [Window("MONDAY", 7, 0, 17, 0)], None)
    assert diff.to_add == ()
    assert {c.window.day_of_week for c in diff.to_remove} == {"TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY"}


def test_grade_identica_nao_emite_operacao_nenhuma() -> None:
    """Spec §8.9 — reenviar a grade atual e no-op; recriar identicos queima re-learning."""
    current = [_cur(day="MONDAY"), _cur(day="TUESDAY")]
    diff = diff_schedule(current, [c.window for c in current], None)
    assert diff.is_empty() and diff.op_count() == 0


def test_diff_e_por_conteudo_nao_por_criterion_id() -> None:
    """O id muda quando o Google recria; a chave e (dia, horas, minutos)."""
    current = [_cur(day="MONDAY", rn="customers/1/campaignCriteria/9~111")]
    diff = diff_schedule(current, [Window("MONDAY", 7, 0, 17, 0)], None)
    assert diff.is_empty()


def test_janela_nova_entra_e_janela_ausente_sai() -> None:
    current = [_cur(day="MONDAY")]
    diff = diff_schedule(current, [Window("TUESDAY", 8, 0, 12, 0)], None)
    assert diff.to_add == (Window("TUESDAY", 8, 0, 12, 0),)
    assert [c.window.day_of_week for c in diff.to_remove] == ["MONDAY"]


def test_bid_modifier_diferente_vira_update_nao_recria() -> None:
    """Mudar so o bid_modifier de uma janela existente e `update` com mask — nao remove+create."""
    current = [_cur(day="MONDAY", bm=1.0)]
    diff = diff_schedule(current, [Window("MONDAY", 7, 0, 17, 0)], 1.2)
    assert diff.to_add == () and diff.to_remove == ()
    assert [c.window.day_of_week for c in diff.to_update] == ["MONDAY"]


def test_bid_modifier_igual_ou_nao_informado_nao_gera_update() -> None:
    current = [_cur(day="MONDAY", bm=1.2)]
    assert diff_schedule(current, [Window("MONDAY", 7, 0, 17, 0)], 1.2).is_empty()
    assert diff_schedule(current, [Window("MONDAY", 7, 0, 17, 0)], None).is_empty()
```

- [ ] **Step 2: Rodar para ver falhar**

Run: `python -m pytest tests/unit/test_ad_schedule_domain.py -q -k "diff or grade or bid_modifier"`
Expected: `ImportError` de `CurrentWindow`/`diff_schedule`.

- [ ] **Step 3: Implementar**

```python
@dataclass(frozen=True, slots=True)
class CurrentWindow:
    window: Window
    resource_name: str
    criterion_id: str
    bid_modifier: float | None


@dataclass(frozen=True, slots=True)
class ScheduleDiff:
    to_add: tuple[Window, ...]
    to_remove: tuple[CurrentWindow, ...]
    to_update: tuple[CurrentWindow, ...]

    def is_empty(self) -> bool:
        return not (self.to_add or self.to_remove or self.to_update)

    def op_count(self) -> int:
        return len(self.to_add) + len(self.to_remove) + len(self.to_update)


def diff_schedule(
    current: list[CurrentWindow], desired: list[Window], bid_modifier: float | None
) -> ScheduleDiff:
    """Grade desejada e CONJUNTO (spec §4.1); diff por CONTEUDO (§4.4).

    - janela desejada ausente do atual -> add
    - janela atual ausente da desejada -> remove
    - janela em ambos com bid_modifier informado e diferente -> update (mask), nunca recria
    """
    atual_por_chave = {c.window.key(): c for c in current}
    desejada_por_chave = {w.key(): w for w in desired}
    to_add = tuple(w for k, w in desejada_por_chave.items() if k not in atual_por_chave)
    to_remove = tuple(c for k, c in atual_por_chave.items() if k not in desejada_por_chave)
    to_update: list[CurrentWindow] = []
    if bid_modifier is not None:
        for k, c in atual_por_chave.items():
            if k in desejada_por_chave and c.bid_modifier != bid_modifier:
                to_update.append(c)
    return ScheduleDiff(to_add=to_add, to_remove=to_remove, to_update=tuple(to_update))
```

- [ ] **Step 4: Rodar para ver passar** — `python -m pytest tests/unit/test_ad_schedule_domain.py -q` → todos PASS.

- [ ] **Step 5: Sabotagem (obrigatória — spec §8, último parágrafo)** — em cópia do arquivo, troque o corpo de `diff_schedule` por `to_add=tuple(desired), to_remove=(), to_update=()` (implementação "delta"). Rode o arquivo: `test_grade_completa_e_conjunto...` e `test_grade_identica...` **têm** que falhar. Restaure da cópia (nunca `git checkout`).

- [ ] **Step 6: Commit** — `feat(mcp): ad_schedule — diff por conteudo: conjunto, idempotente, bid_modifier via update`

---

### Task 3: Domínio — cobertura e partição de métricas (o dry-run da §4.2)

**Files:**
- Modify: `src/google_ads/ad_schedule.py`
- Test: `tests/unit/test_ad_schedule_domain.py` (append)

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True, slots=True) class MetricCell: day_of_week: str; hour: int; cost_micros: int; conversions: float`
  - `def covers(windows: list[Window] | None, day_of_week: str, hour: int) -> bool` — `None` = 24×7
  - `def partition_metrics(cells: list[MetricCell], before: list[Window] | None, after: list[Window]) -> dict[str, Any]` → `{"leaving": {"cost_brl", "conversions", "cpa_brl", "cells"}, "staying": {...}, "metrics_granularity": "hora cheia; janelas com minutos sao aproximadas a hora cheia"}`. `cpa_brl` é `None` quando `conversions == 0`. `cost_brl = round(cost_micros / 1_000_000, 2)`.
  - `def summarize_current(current: list[CurrentWindow]) -> dict[str, Any]` → `{"has_schedule": bool, "windows": int, "hours_per_week": float}` (`has_schedule=False` ⇒ `hours_per_week=168.0`)

- [ ] **Step 1: Testes que falham**

```python
from src.google_ads.ad_schedule import MetricCell, covers, partition_metrics, summarize_current


def test_sem_criterio_cobre_24x7() -> None:
    """Spec §3: campanha sem AD_SCHEDULE serve sempre — vazio quer dizer 'tudo', nao 'nada'."""
    assert covers(None, "SUNDAY", 3) is True
    assert covers([], "SUNDAY", 3) is False


def test_cobertura_e_meio_aberta_e_por_hora_cheia() -> None:
    w = [Window("MONDAY", 7, 0, 17, 0)]
    assert covers(w, "MONDAY", 7) and covers(w, "MONDAY", 16)
    assert not covers(w, "MONDAY", 17) and not covers(w, "TUESDAY", 8)
    # 07:30-08:00: a celula 07:00 NAO esta em [07:30, 08:00) -> aproximacao documentada
    assert not covers([Window("MONDAY", 7, 30, 8, 0)], "MONDAY", 7)


def _cell(day: str, hour: int, cost: float, conv: float) -> MetricCell:
    return MetricCell(day, hour, int(cost * 1_000_000), conv)


def test_preview_separa_o_que_sai_do_que_fica_com_cpa_dos_dois_lados() -> None:
    """Spec §4.2/§8.3: custo sozinho nao responde; CPA de quem sai vs quem fica."""
    cells = [
        _cell("SATURDAY", 10, 100.0, 5.0),   # sai (fim de semana) — CPA 20
        _cell("SUNDAY", 11, 50.0, 5.0),      # sai — CPA 10
        _cell("MONDAY", 9, 300.0, 10.0),     # fica — CPA 30
    ]
    depois = [Window(d, 0, 0, 24, 0) for d in ("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY")]
    r = partition_metrics(cells, None, depois)
    assert r["leaving"]["cost_brl"] == 150.0 and r["leaving"]["conversions"] == 10.0
    assert r["leaving"]["cpa_brl"] == 15.0
    assert r["staying"]["cost_brl"] == 300.0 and r["staying"]["cpa_brl"] == 30.0
    assert "conversions" in r["leaving"] and "conversions" in r["staying"]


def test_cpa_e_none_sem_conversao_nunca_divisao_por_zero() -> None:
    r = partition_metrics([_cell("SUNDAY", 3, 10.0, 0.0)], None, [Window("MONDAY", 0, 0, 24, 0)])
    assert r["leaving"]["cpa_brl"] is None and r["leaving"]["cost_brl"] == 10.0


def test_celula_que_ja_nao_era_servida_nao_entra_em_nenhum_lado() -> None:
    antes = [Window("MONDAY", 7, 0, 17, 0)]
    r = partition_metrics([_cell("SUNDAY", 3, 10.0, 1.0)], antes, antes)
    assert r["leaving"]["cost_brl"] == 0.0 and r["staying"]["cost_brl"] == 0.0


def test_summarize_current_sem_grade_e_24x7() -> None:
    assert summarize_current([]) == {"has_schedule": False, "windows": 0, "hours_per_week": 168.0}
    s = summarize_current([_cur(day="MONDAY"), _cur(day="TUESDAY")])
    assert s == {"has_schedule": True, "windows": 2, "hours_per_week": 20.0}
```

- [ ] **Step 2: Rodar para ver falhar** — `ImportError` de `MetricCell`/`covers`/`partition_metrics`/`summarize_current`.

- [ ] **Step 3: Implementar**

```python
@dataclass(frozen=True, slots=True)
class MetricCell:
    day_of_week: str
    hour: int
    cost_micros: int
    conversions: float


METRICS_GRANULARITY = "hora cheia; janelas com minutos sao aproximadas a hora cheia"


def covers(windows: list[Window] | None, day_of_week: str, hour: int) -> bool:
    """`None` = campanha sem AD_SCHEDULE = serve 24x7. Celula (dia, h) coberta se h:00 esta em [start, end)."""
    if windows is None:
        return True
    instante = hour * 60
    return any(
        w.day_of_week == day_of_week and w.start_min() <= instante < w.end_min() for w in windows
    )


def _agrega(cells: list[MetricCell]) -> dict[str, Any]:
    cost = sum(c.cost_micros for c in cells)
    conv = sum(c.conversions for c in cells)
    cost_brl = round(cost / 1_000_000, 2)
    return {
        "cost_brl": cost_brl,
        "conversions": round(conv, 2),
        "cpa_brl": round(cost_brl / conv, 2) if conv > 0 else None,
        "cells": len(cells),
    }


def partition_metrics(
    cells: list[MetricCell], before: list[Window] | None, after: list[Window]
) -> dict[str, Any]:
    """Spec §4.2: o preview responde 'o que estou desligando e melhor ou pior do que fica?'."""
    leaving = [c for c in cells if covers(before, c.day_of_week, c.hour) and not covers(after, c.day_of_week, c.hour)]
    staying = [c for c in cells if covers(after, c.day_of_week, c.hour)]
    return {"leaving": _agrega(leaving), "staying": _agrega(staying), "metrics_granularity": METRICS_GRANULARITY}


def summarize_current(current: list[CurrentWindow]) -> dict[str, Any]:
    if not current:
        return {"has_schedule": False, "windows": 0, "hours_per_week": 168.0}
    return {
        "has_schedule": True,
        "windows": len(current),
        "hours_per_week": hours_per_week(c.window for c in current),
    }
```

- [ ] **Step 4: Rodar para ver passar** — todos PASS. **Step 5: Commit** — `feat(mcp): ad_schedule — cobertura 24x7 e particao de metricas com CPA dos dois lados`

---

### Task 4: Queries GAQL + parsers

**Files:**
- Create: `src/google_ads/queries/ad_schedule.py`
- Test: `tests/unit/test_ad_schedule_queries.py`

**Interfaces:**
- Consumes: `ENUM_MINUTO` (Task 1); `gaql_date_clause` de `src/google_ads/queries/_common.py`; `gaql_in_list` de `src/google_ads/queries/_gaql.py`.
- Produces:
  - `def ad_schedule_query(*, campaign_ids: list[str] | None, status: str, limit: int) -> str` — `status` ∈ `enabled|paused|removed|all` (mesmo contrato de `get_performance_breakdown`); `all` omite o filtro.
  - `def parse_ad_schedule_row(row: Any) -> dict[str, Any]` → `{campaign_id, campaign_name, criterion_id, resource_name, day_of_week, start_hour, start_minute, end_hour, end_minute, bid_modifier, status}` (minutos como **int**)
  - `def campaign_budget_query(*, campaign_ids: list[str]) -> str` e `def parse_campaign_budget_row(row) -> dict` → `{campaign_id, campaign_name, budget_resource_name, budget_id, explicitly_shared: bool, amount_brl}`
  - `def campaigns_on_budgets_query(*, budget_resource_names: list[str]) -> str` e `def parse_campaign_on_budget_row(row) -> dict` → `{campaign_id, campaign_name, budget_resource_name, status}`
  - `def day_hour_metrics_query(*, campaign_ids: list[str], start: date, end: date) -> str` e `def parse_day_hour_row(row) -> dict` → `{campaign_id, day_of_week, hour: int, cost_micros: int, conversions: float}`

- [ ] **Step 1: Testes que falham**

```python
"""GAQL do ad_schedule. Superficie probada em 02/09 (validate_gaql) e 03/09 (run_gaql)."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from src.google_ads.queries.ad_schedule import (
    ad_schedule_query,
    campaign_budget_query,
    campaigns_on_budgets_query,
    day_hour_metrics_query,
    parse_ad_schedule_row,
    parse_campaign_budget_row,
    parse_day_hour_row,
)


def test_ad_schedule_query_filtra_tipo_e_ordena_com_limit() -> None:
    q = ad_schedule_query(campaign_ids=["22169885957"], status="enabled", limit=200)
    assert "FROM campaign_criterion" in q
    assert "campaign_criterion.type = 'AD_SCHEDULE'" in q
    assert "campaign.id IN (22169885957)" in q
    assert "campaign_criterion.status = 'ENABLED'" in q
    assert "ORDER BY" in q and q.rstrip().endswith("LIMIT 201"), "LIMIT = limit+1 (sentinela de truncamento, F98)"
    for campo in ("day_of_week", "start_hour", "start_minute", "end_hour", "end_minute"):
        assert f"campaign_criterion.ad_schedule.{campo}" in q
    assert "campaign_criterion.bid_modifier" in q and "campaign_criterion.resource_name" in q


def test_ad_schedule_query_status_all_nao_filtra_status() -> None:
    q = ad_schedule_query(campaign_ids=None, status="all", limit=10)
    assert "campaign_criterion.status" not in q.split("WHERE", 1)[1]
    assert "campaign.id IN" not in q


def test_parse_ad_schedule_row_converte_minuto_enum_em_int() -> None:
    row = SimpleNamespace(
        campaign=SimpleNamespace(id=22169885957, name="CAB"),
        campaign_criterion=SimpleNamespace(
            criterion_id=348624223154,
            resource_name="customers/1/campaignCriteria/22169885957~348624223154",
            ad_schedule=SimpleNamespace(
                day_of_week=SimpleNamespace(name="MONDAY"),
                start_hour=7, end_hour=17,
                start_minute=SimpleNamespace(name="THIRTY"),
                end_minute=SimpleNamespace(name="UNSPECIFIED"),
            ),
            bid_modifier=1.2,
            status=SimpleNamespace(name="ENABLED"),
        ),
    )
    d = parse_ad_schedule_row(row)
    assert d["campaign_id"] == "22169885957" and d["criterion_id"] == "348624223154"
    assert (d["day_of_week"], d["start_hour"], d["start_minute"], d["end_hour"], d["end_minute"]) == ("MONDAY", 7, 30, 17, 0)
    assert d["bid_modifier"] == 1.2 and d["status"] == "ENABLED"
    assert d["resource_name"].endswith("~348624223154")


def test_campaign_budget_query_traz_explicitly_shared() -> None:
    q = campaign_budget_query(campaign_ids=["1", "2"])
    assert "campaign_budget.explicitly_shared" in q and "campaign.campaign_budget" in q
    assert "campaign.id IN (1,2)" in q


def test_parse_campaign_budget_row() -> None:
    row = SimpleNamespace(
        campaign=SimpleNamespace(id=1, name="A", campaign_budget="customers/1/campaignBudgets/77"),
        campaign_budget=SimpleNamespace(id=77, explicitly_shared=True, amount_micros=310000000),
    )
    d = parse_campaign_budget_row(row)
    assert d == {"campaign_id": "1", "campaign_name": "A", "budget_resource_name": "customers/1/campaignBudgets/77", "budget_id": "77", "explicitly_shared": True, "amount_brl": 310.0}


def test_campaigns_on_budgets_query_exclui_removidas_e_usa_literal_escapado() -> None:
    q = campaigns_on_budgets_query(budget_resource_names=["customers/1/campaignBudgets/77"])
    assert "campaign.campaign_budget IN ('customers/1/campaignBudgets/77')" in q
    assert "campaign.status != 'REMOVED'" in q


def test_day_hour_metrics_query_e_a_conjunta_probada_em_03_09() -> None:
    q = day_hour_metrics_query(campaign_ids=["21359547724"], start=date(2026, 8, 4), end=date(2026, 9, 2))
    assert "FROM campaign" in q
    assert "segments.day_of_week" in q and "segments.hour" in q
    assert "metrics.cost_micros" in q and "metrics.conversions" in q
    assert "segments.date BETWEEN '2026-08-04' AND '2026-09-02'" in q
    assert "campaign.id IN (21359547724)" in q


def test_parse_day_hour_row_tipa_hora_e_custo() -> None:
    row = SimpleNamespace(
        campaign=SimpleNamespace(id=21359547724),
        segments=SimpleNamespace(day_of_week=SimpleNamespace(name="MONDAY"), hour=8),
        metrics=SimpleNamespace(cost_micros="314676351", conversions=13.998888),
    )
    d = parse_day_hour_row(row)
    assert d == {"campaign_id": "21359547724", "day_of_week": "MONDAY", "hour": 8, "cost_micros": 314676351, "conversions": 13.998888}
```

- [ ] **Step 2: Rodar para ver falhar** — `ImportError` do módulo.

- [ ] **Step 3: Implementar**

```python
"""GAQL do ad_schedule (spec §3, §4.2, §4.3).

Superficie verificada: 02/09 por `validate_gaql` (campaign_criterion.ad_schedule.*,
bid_modifier, status; campaign_budget.explicitly_shared) e 03/09 por `run_gaql`
(conjunta segments.day_of_week x segments.hour sobre `campaign`, com metricas).
`segments.hour` chega como int 0..23; `metrics.cost_micros` chega como string.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from src.google_ads.ad_schedule import ENUM_MINUTO
from src.google_ads.queries._common import gaql_date_clause
from src.google_ads.queries._gaql import gaql_in_list

_STATUS_FILTER = {"enabled": "ENABLED", "paused": "PAUSED", "removed": "REMOVED"}


def _nome(x: Any) -> str:
    return x.name if hasattr(x, "name") else str(x)


def ad_schedule_query(*, campaign_ids: list[str] | None, status: str, limit: int) -> str:
    filtros = ["campaign_criterion.type = 'AD_SCHEDULE'"]
    if campaign_ids:
        filtros.append(f"campaign.id IN ({','.join(campaign_ids)})")  # ids validados ^[0-9]+$ no schema
    if status in _STATUS_FILTER:
        filtros.append(f"campaign_criterion.status = '{_STATUS_FILTER[status]}'")
    return f"""
        SELECT campaign.id, campaign.name, campaign_criterion.criterion_id,
               campaign_criterion.resource_name,
               campaign_criterion.ad_schedule.day_of_week,
               campaign_criterion.ad_schedule.start_hour,
               campaign_criterion.ad_schedule.start_minute,
               campaign_criterion.ad_schedule.end_hour,
               campaign_criterion.ad_schedule.end_minute,
               campaign_criterion.bid_modifier, campaign_criterion.status
        FROM campaign_criterion
        WHERE {" AND ".join(filtros)}
        ORDER BY campaign.id, campaign_criterion.ad_schedule.day_of_week, campaign_criterion.ad_schedule.start_hour
        LIMIT {limit + 1}
    """.strip()


def parse_ad_schedule_row(row: Any) -> dict[str, Any]:
    cc = row.campaign_criterion
    s = cc.ad_schedule
    return {
        "campaign_id": str(row.campaign.id),
        "campaign_name": str(row.campaign.name),
        "criterion_id": str(cc.criterion_id),
        "resource_name": str(cc.resource_name),
        "day_of_week": _nome(s.day_of_week),
        "start_hour": int(s.start_hour),
        "start_minute": ENUM_MINUTO.get(_nome(s.start_minute), 0),
        "end_hour": int(s.end_hour),
        "end_minute": ENUM_MINUTO.get(_nome(s.end_minute), 0),
        "bid_modifier": float(cc.bid_modifier) if cc.bid_modifier else None,
        "status": _nome(cc.status),
    }


def campaign_budget_query(*, campaign_ids: list[str]) -> str:
    return f"""
        SELECT campaign.id, campaign.name, campaign.campaign_budget,
               campaign_budget.id, campaign_budget.explicitly_shared, campaign_budget.amount_micros
        FROM campaign
        WHERE campaign.id IN ({','.join(campaign_ids)})
    """.strip()


def parse_campaign_budget_row(row: Any) -> dict[str, Any]:
    return {
        "campaign_id": str(row.campaign.id),
        "campaign_name": str(row.campaign.name),
        "budget_resource_name": str(row.campaign.campaign_budget),
        "budget_id": str(row.campaign_budget.id),
        "explicitly_shared": bool(row.campaign_budget.explicitly_shared),
        "amount_brl": round(int(row.campaign_budget.amount_micros) / 1_000_000, 2),
    }


def campaigns_on_budgets_query(*, budget_resource_names: list[str]) -> str:
    return f"""
        SELECT campaign.id, campaign.name, campaign.campaign_budget, campaign.status
        FROM campaign
        WHERE campaign.campaign_budget IN {gaql_in_list(budget_resource_names)}
          AND campaign.status != 'REMOVED'
    """.strip()


def parse_campaign_on_budget_row(row: Any) -> dict[str, Any]:
    return {
        "campaign_id": str(row.campaign.id),
        "campaign_name": str(row.campaign.name),
        "budget_resource_name": str(row.campaign.campaign_budget),
        "status": _nome(row.campaign.status),
    }


def day_hour_metrics_query(*, campaign_ids: list[str], start: date, end: date) -> str:
    """Conjunta dia x hora sobre `campaign` — probada valida em 03/09 (spec §4.2)."""
    return f"""
        SELECT campaign.id, segments.day_of_week, segments.hour,
               metrics.cost_micros, metrics.conversions
        FROM campaign
        WHERE {gaql_date_clause(start, end)}
          AND campaign.id IN ({','.join(campaign_ids)})
    """.strip()


def parse_day_hour_row(row: Any) -> dict[str, Any]:
    return {
        "campaign_id": str(row.campaign.id),
        "day_of_week": _nome(row.segments.day_of_week),
        "hour": int(row.segments.hour),
        "cost_micros": int(row.metrics.cost_micros),
        "conversions": float(row.metrics.conversions),
    }
```

> Fato conferido (03/09): `gaql_in_list(values: list[str]) -> str` devolve `('a', 'b')` — vírgula **e espaço** entre itens, cada um por `gaql_string_literal` (escape de `\` e `'`). Com um item só, `('x')`. O teste acima está de acordo.

- [ ] **Step 4: Rodar para ver passar**. **Step 5: Commit** — `feat(mcp): ad_schedule — queries GAQL da grade, dos orcamentos e da conjunta dia x hora`

---

### Task 5: `get_ad_schedule` (tool read)

**Files:**
- Create: `src/mcp/tools/get_ad_schedule.py`
- Test: `tests/unit/test_get_ad_schedule.py`

**Interfaces:**
- Consumes: Task 4 queries/parsers; `summarize_current`, `CurrentWindow`, `Window` (Tasks 1–3); `run_report`, `get_current`, `register_tool`.
- Produces: tool `get_ad_schedule(args) -> {customer_id, windows: [...], schedule_summary: {campaign_id: {...}}, truncated: bool}`; helper exportado `def rows_to_current(rows: list[dict]) -> dict[str, list[CurrentWindow]]` (reusado pelo `update_ad_schedule`).

- [ ] **Step 1: Testes que falham**

```python
"""get_ad_schedule (spec §3): grade + resumo por campanha; vazio quer dizer 24x7."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from src.mcp.tools import get_ad_schedule as mod
from src.mcp.tools._registry import get_tool


@pytest.fixture(autouse=True)
def _ctx():
    from src.mcp.context import McpRequestContext, clear_current, set_current

    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    yield
    clear_current()


def _fake_run_report(por_recurso: dict[str, list[dict[str, Any]]]):
    """Despacha por `FROM <recurso>` — mesmo padrao de test_get_assets.py."""
    chamadas: list[str] = []

    async def _run(**kwargs: Any) -> list[dict[str, Any]]:
        q = kwargs["query"]
        chamadas.append(q)
        for recurso, linhas in por_recurso.items():
            if f"FROM {recurso}" in q:
                return linhas
        return []

    return _run, chamadas


def _janela(cid="1", nome="A", day="MONDAY", sh=7, eh=17, bm=None, crit="9") -> dict[str, Any]:
    return {
        "campaign_id": cid, "campaign_name": nome, "criterion_id": crit,
        "resource_name": f"customers/1/campaignCriteria/{cid}~{crit}",
        "day_of_week": day, "start_hour": sh, "start_minute": 0, "end_hour": eh, "end_minute": 0,
        "bid_modifier": bm, "status": "ENABLED",
    }


def _orcamento(cid="1", nome="A", shared=False) -> dict[str, Any]:
    return {"campaign_id": cid, "campaign_name": nome, "budget_resource_name": "customers/1/campaignBudgets/77",
            "budget_id": "77", "explicitly_shared": shared, "amount_brl": 310.0}


def test_tool_registrada_como_defer() -> None:
    t = get_tool("get_ad_schedule")
    assert t is not None and t.bucket == "defer"


def test_schema_sem_composicao() -> None:
    import json
    s = json.dumps(get_tool("get_ad_schedule").input_schema)
    assert not any(k in s for k in ("oneOf", "allOf", "anyOf"))


@pytest.mark.asyncio
async def test_campanha_sem_criterio_aparece_no_resumo_como_24x7(monkeypatch) -> None:
    """A distincao central da §3: lista vazia NAO pode ficar implicita."""
    run, _ = _fake_run_report({"campaign_criterion": [], "campaign": [_orcamento(cid="1")]})
    monkeypatch.setattr("src.mcp.tools.get_ad_schedule.run_report", run)
    out = await mod.get_ad_schedule({"customer_id": "1234567890", "campaign_ids": ["1"]})
    assert out["windows"] == []
    assert out["schedule_summary"]["1"]["has_schedule"] is False
    assert out["schedule_summary"]["1"]["hours_per_week"] == 168.0
    assert out["schedule_summary"]["1"]["budget_is_shared"] is False


@pytest.mark.asyncio
async def test_resumo_por_campanha_com_horas_e_orcamento_compartilhado(monkeypatch) -> None:
    run, _ = _fake_run_report({
        "campaign_criterion": [_janela(day="MONDAY"), _janela(day="TUESDAY", crit="10")],
        "campaign": [_orcamento(shared=True)],
    })
    monkeypatch.setattr("src.mcp.tools.get_ad_schedule.run_report", run)
    out = await mod.get_ad_schedule({"customer_id": "1234567890"})
    s = out["schedule_summary"]["1"]
    assert s == {"campaign_name": "A", "has_schedule": True, "windows": 2, "hours_per_week": 20.0, "budget_is_shared": True}
    assert len(out["windows"]) == 2 and out["truncated"] is False


@pytest.mark.asyncio
async def test_limit_trunca_e_avisa(monkeypatch) -> None:
    run, chamadas = _fake_run_report({"campaign_criterion": [_janela(crit=str(i)) for i in range(3)], "campaign": [_orcamento()]})
    monkeypatch.setattr("src.mcp.tools.get_ad_schedule.run_report", run)
    out = await mod.get_ad_schedule({"customer_id": "1234567890", "limit": 2})
    assert len(out["windows"]) == 2 and out["truncated"] is True
    assert any("LIMIT 3" in q for q in chamadas), "a query pede limit+1 como sentinela"


@pytest.mark.asyncio
async def test_a_consulta_da_grade_e_auditada_e_a_de_orcamento_nao(monkeypatch) -> None:
    """Padrao de get_assets/get_change_history: UMA linha de audit por chamada do gestor."""
    vistos: list[bool] = []

    async def _run(**kwargs: Any):
        vistos.append(bool(kwargs.get("audit_this_call", False)))
        return []

    monkeypatch.setattr("src.mcp.tools.get_ad_schedule.run_report", _run)
    await mod.get_ad_schedule({"customer_id": "1234567890"})
    assert vistos.count(True) == 1
```

- [ ] **Step 2: Rodar para ver falhar** — `ImportError` do módulo `get_ad_schedule`.

- [ ] **Step 3: Implementar**

```python
# bucket: defer
"""Tool: get_ad_schedule — grade de veiculacao (dia x hora) por campanha (spec §3).

Campanha SEM criterio de AD_SCHEDULE serve 24x7. Essa distincao nao pode
ficar implicita numa lista vazia — mesma classe do F131 (vazio que quer dizer
duas coisas). Por isso `schedule_summary` existe por campanha, mesmo sem janela.
"""

import asyncio
from typing import Any

from src.google_ads.ad_schedule import CurrentWindow, Window, summarize_current
from src.google_ads.queries.ad_schedule import (
    ad_schedule_query,
    campaign_budget_query,
    parse_ad_schedule_row,
    parse_campaign_budget_row,
)
from src.google_ads.reports import run_report
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "campaign_ids": {
            "type": "array",
            "items": {"type": "string", "pattern": "^[0-9]+$"},
            "minItems": 1,
            "maxItems": 50,
            "description": "Opcional. Default: conta inteira.",
        },
        "status": {
            "type": "string",
            "enum": ["enabled", "paused", "removed", "all"],
            "default": "enabled",
            "description": "Status dos CRITERIOS de agenda (nao da campanha).",
        },
        "limit": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 200},
    },
    "required": ["customer_id"],
    "additionalProperties": False,
}

_DESCRIPTION = (
    "[DEFER] Grade de veiculacao (ad schedule) por campanha: uma linha por janela "
    "(day_of_week, start_hour/minute, end_hour/minute, bid_modifier, status, "
    "criterion_id, resource_name) e um `schedule_summary` por campanha com "
    "`has_schedule`, `hours_per_week` e `budget_is_shared`. ATENCAO: campanha "
    "SEM nenhuma janela serve 24x7 — `has_schedule: false` e `hours_per_week: 168` "
    "dizem isso explicitamente; nao leia lista vazia como 'nao serve'. Janela cobre "
    "[inicio, fim); `end_hour: 24` = ate o fim do dia; minutos so 0/15/30/45 (API). "
    "Uma campanha pode ter ate 7x24 janelas: `limit` (default 200, teto 1000) corta e "
    "`truncated: true` avisa. `budget_is_shared` vem de campaign_budget.explicitly_shared "
    "— importa porque desligar faixa em orcamento compartilhado REALOCA gasto, nao "
    "economiza (ver update_ad_schedule)."
)


def rows_to_current(rows: list[dict[str, Any]]) -> dict[str, list[CurrentWindow]]:
    """Linhas do parser -> CurrentWindow por campanha (reusado pelo update_ad_schedule)."""
    por_campanha: dict[str, list[CurrentWindow]] = {}
    for r in rows:
        w = Window(r["day_of_week"], r["start_hour"], r["start_minute"], r["end_hour"], r["end_minute"])
        por_campanha.setdefault(r["campaign_id"], []).append(
            CurrentWindow(window=w, resource_name=r["resource_name"], criterion_id=r["criterion_id"], bid_modifier=r["bid_modifier"])
        )
    return por_campanha


@register_tool(name="get_ad_schedule", description=_DESCRIPTION, input_schema=_SCHEMA, bucket="defer")
async def get_ad_schedule(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    campaign_ids = args.get("campaign_ids")
    status = args.get("status", "enabled")
    limit = args.get("limit", 200)

    async def _consulta(query: str, parser: Any, *, audited: bool = False) -> list[dict[str, Any]]:
        return await run_report(
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=customer_id,
            query=query,
            row_formatter=parser,
            operation_name="get_ad_schedule",
            audit_this_call=audited,
            params_summary=({"campaign_ids": campaign_ids, "status": status, "limit": limit} if audited else None),
        )

    grade_rows, orcamentos = await asyncio.gather(
        _consulta(ad_schedule_query(campaign_ids=campaign_ids, status=status, limit=limit), parse_ad_schedule_row, audited=True),
        _consulta(campaign_budget_query(campaign_ids=campaign_ids) if campaign_ids else _todas_as_campanhas_query(), parse_campaign_budget_row),
    )
    truncated = len(grade_rows) > limit
    grade_rows = grade_rows[:limit]

    atual = rows_to_current(grade_rows)
    summary: dict[str, dict[str, Any]] = {}
    for o in orcamentos:
        cid = o["campaign_id"]
        summary[cid] = {"campaign_name": o["campaign_name"], **summarize_current(atual.get(cid, [])), "budget_is_shared": o["explicitly_shared"]}
    return {"customer_id": customer_id, "windows": grade_rows, "schedule_summary": summary, "truncated": truncated}


def _todas_as_campanhas_query() -> str:
    """Sem campaign_ids: orcamento de todas as campanhas nao removidas (um SELECT so)."""
    return """
        SELECT campaign.id, campaign.name, campaign.campaign_budget,
               campaign_budget.id, campaign_budget.explicitly_shared, campaign_budget.amount_micros
        FROM campaign
        WHERE campaign.status != 'REMOVED'
    """.strip()
```

- [ ] **Step 4: Rodar para ver passar** — `python -m pytest tests/unit/test_get_ad_schedule.py tests/unit/test_tools_schemas.py -q` (o segundo é o guard existente de schemas; a tool nova entra nele automaticamente). Rode também `python -m pytest tests/unit/test_no_server_clock_in_google_tools.py -q`.

- [ ] **Step 5: Commit** — `feat(mcp): get_ad_schedule — grade por campanha, vazio e 24x7, orcamento compartilhado no resumo`

---

### Task 6: Builder `build_update_ad_schedule`

**Files:**
- Create: `src/google_ads/mutates/ad_schedule.py`
- Test: `tests/unit/test_update_ad_schedule_builder.py`

**Interfaces:**
- Consumes: `register_builder` de `src/google_ads/mutates/_common.py`; `MINUTO_ENUM` (Task 1); `FieldMask`.
- Produces: `build_update_ad_schedule(client, customer_id, payload) -> list[MutateOperation]` lendo `payload["ops"]`, lista de dicts:
  - `{"kind": "add", "campaign_id": "…", "window": {day_of_week, start_hour, start_minute, end_hour, end_minute}, "bid_modifier": float | None}`
  - `{"kind": "remove", "resource_name": "customers/…/campaignCriteria/…"}`
  - `{"kind": "update", "resource_name": "…", "bid_modifier": float}`

- [ ] **Step 1: Testes que falham**

```python
"""Builder do update_ad_schedule. `make_capture_client`, nunca MagicMock (F16/F42/F44).

Campos do proto lidos do SDK v24 por import (nao por analogia): AdScheduleInfo =
{day_of_week, start_hour, start_minute, end_hour, end_minute};
CampaignCriterionOperation = {update_mask, create, update, remove}.
"""

from __future__ import annotations

import pytest

from src.google_ads.mutates.ad_schedule import build_update_ad_schedule
from tests.unit.fixtures.proto_capture import make_capture_client

CID = "1234567890"


def _add(day="MONDAY", sh=7, sm=0, eh=17, em=30, bm=None) -> dict:
    return {"kind": "add", "campaign_id": "22169885957",
            "window": {"day_of_week": day, "start_hour": sh, "start_minute": sm, "end_hour": eh, "end_minute": em},
            "bid_modifier": bm}


def test_add_cria_campaign_criterion_com_ad_schedule_completo() -> None:
    ops = build_update_ad_schedule(make_capture_client(), CID, {"ops": [_add()]})
    assert len(ops) == 1
    op = ops[0]
    assert op.field("campaign_criterion_operation.create.campaign").endswith("/campaigns/22169885957")
    assert op.field("campaign_criterion_operation.create.ad_schedule.day_of_week") == "MONDAY"
    assert op.field("campaign_criterion_operation.create.ad_schedule.start_hour") == 7
    assert op.field("campaign_criterion_operation.create.ad_schedule.start_minute") == "ZERO"
    assert op.field("campaign_criterion_operation.create.ad_schedule.end_hour") == 17
    assert op.field("campaign_criterion_operation.create.ad_schedule.end_minute") == "THIRTY"


def test_add_com_bid_modifier_seta_o_campo_e_sem_ele_nao_toca() -> None:
    com = build_update_ad_schedule(make_capture_client(), CID, {"ops": [_add(bm=1.2)]})[0]
    assert com.field("campaign_criterion_operation.create.bid_modifier") == 1.2
    sem = build_update_ad_schedule(make_capture_client(), CID, {"ops": [_add()]})[0]
    assert not sem.has("campaign_criterion_operation.create.bid_modifier")


def test_remove_usa_o_resource_name_verbatim() -> None:
    rn = f"customers/{CID}/campaignCriteria/22169885957~348624223154"
    op = build_update_ad_schedule(make_capture_client(), CID, {"ops": [{"kind": "remove", "resource_name": rn}]})[0]
    assert op.field("campaign_criterion_operation.remove") == rn


def test_update_de_bid_modifier_usa_update_com_mask_e_nao_recria() -> None:
    rn = f"customers/{CID}/campaignCriteria/22169885957~348624223154"
    op = build_update_ad_schedule(make_capture_client(), CID, {"ops": [{"kind": "update", "resource_name": rn, "bid_modifier": 0.8}]})[0]
    assert op.field("campaign_criterion_operation.update.resource_name") == rn
    assert op.field("campaign_criterion_operation.update.bid_modifier") == 0.8
    assert not op.has("campaign_criterion_operation.create") and not op.has("campaign_criterion_operation.remove")


def test_minuto_invalido_no_payload_estoura_antes_do_google() -> None:
    """Defesa em profundidade: o schema recusa antes; se um payload velho passar, aqui estoura."""
    with pytest.raises(ValueError):
        build_update_ad_schedule(make_capture_client(), CID, {"ops": [_add(sm=10)]})


def test_kind_desconhecido_estoura() -> None:
    with pytest.raises(ValueError):
        build_update_ad_schedule(make_capture_client(), CID, {"ops": [{"kind": "replace"}]})
```

> Sobre `update_mask` no capture client: `client.copy_from(...)` é `MagicMock` no `make_capture_client`, então o mask **não** é capturável por `field()`. O guard do mask é o teste de sabotagem do Step 5, não uma asserção aqui.

- [ ] **Step 2: Rodar para ver falhar** — `ImportError` do módulo.

- [ ] **Step 3: Implementar**

```python
"""Builder do update_ad_schedule (spec §4). Burro de proposito: o diff foi calculado
no dry-run e viaja no payload — o que o gestor confirmou e exatamente o que se aplica.
"""

from __future__ import annotations

from typing import Any

from google.protobuf.field_mask_pb2 import FieldMask

from src.google_ads.ad_schedule import MINUTO_ENUM
from src.google_ads.mutates._common import register_builder


@register_builder("update_ad_schedule")
def build_update_ad_schedule(client: Any, customer_id: str, payload: dict[str, Any]) -> list[Any]:
    campaign_service = client.get_service("CampaignService")
    dias = client.enums.DayOfWeekEnum
    minutos = client.enums.MinuteOfHourEnum
    ops: list[Any] = []
    for item in payload["ops"]:
        kind = item.get("kind")
        op = client.get_type("MutateOperation")
        cco = op.campaign_criterion_operation
        if kind == "add":
            w = item["window"]
            for campo in ("start_minute", "end_minute"):
                if int(w[campo]) not in MINUTO_ENUM:
                    raise ValueError(f"{campo}={w[campo]} fora de {sorted(MINUTO_ENUM)}")
            crit = cco.create
            crit.campaign = campaign_service.campaign_path(customer_id, item["campaign_id"])
            crit.ad_schedule.day_of_week = dias[w["day_of_week"]]
            crit.ad_schedule.start_hour = int(w["start_hour"])
            crit.ad_schedule.start_minute = minutos[MINUTO_ENUM[int(w["start_minute"])]]
            crit.ad_schedule.end_hour = int(w["end_hour"])
            crit.ad_schedule.end_minute = minutos[MINUTO_ENUM[int(w["end_minute"])]]
            if item.get("bid_modifier") is not None:
                crit.bid_modifier = float(item["bid_modifier"])
        elif kind == "remove":
            cco.remove = item["resource_name"]
        elif kind == "update":
            crit = cco.update
            crit.resource_name = item["resource_name"]
            crit.bid_modifier = float(item["bid_modifier"])
            client.copy_from(cco.update_mask, FieldMask(paths=["bid_modifier"]))
        else:
            raise ValueError(f"kind desconhecido em ops: {kind!r}")
        ops.append(op)
    return ops
```

> Fato conferido (03/09): `make_capture_client()` expõe `CampaignService.campaign_path(cid, c_id)` devolvendo `customers/{cid}/campaigns/{c_id}` (`proto_capture.py:204`). O `endswith("/campaigns/22169885957")` do teste bate.

- [ ] **Step 4: Rodar para ver passar**.

- [ ] **Step 5: Sabotagem** — em cópia: (a) troque o ramo `update` por `remove`+`create` (recriação): `test_update_de_bid_modifier...` tem que falhar; (b) apague a linha `client.copy_from(...)`: **nenhum** teste falha — anote isso no commit como limite conhecido do capture client (o mask é verificado no smoke pela resposta do Google, que rejeita `update` sem mask). Restaure.

- [ ] **Step 6: Commit** — `feat(mcp): build_update_ad_schedule — create/remove/update(mask) sobre campaign_criterion`

---

### Task 7: `classify` + `update_ad_schedule` (tool mutate, always-CONFIRM)

**Files:**
- Modify: `src/governance/blast_radius.py` — antes do `return RiskClassification(RiskLevel.CONFIRM, f"{operation}: unknown operation — default seguro: confirmar")` (~linha 255)
- Create: `src/mcp/tools/update_ad_schedule.py`
- Test: `tests/unit/test_update_ad_schedule.py`

**Interfaces:**
- Consumes: Tasks 1–5 (`validate_windows`, `window_from_input`, `diff_schedule`, `partition_metrics`, `MetricCell`, `Window`, queries, `rows_to_current`); `resolve_account_today`, `resolve_date_window`; `classify`, `create_pending`, `preview_envelope`, `error_envelope`; `connection.get_pool`.
- Produces: tool `update_ad_schedule(args)`. Payload pendente: `{"ops": [...] (formato da Task 6), "__target_count__": op_count, "__partial_failure__": True, "__params_summary__": {...}, "campaign_ids": [...]}`. Resposta `no_changes`: `{"status": "no_changes", "operation": "update_ad_schedule", "customer_id", "no_changes": True, "message": "...", "current_schedule": {...}}` — **sem token**.

- [ ] **Step 1: `classify` — teste e entrada**

Append em `tests/unit/test_update_ad_schedule.py` (crie o arquivo com este primeiro teste):

```python
"""update_ad_schedule (spec §4): grade completa, dry-run com CPA, orcamento compartilhado, no-op."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from src.governance.blast_radius import RiskLevel, classify
from src.mcp.tools import update_ad_schedule as mod
from src.mcp.tools._registry import get_tool


def test_classify_conhece_a_operacao_e_confirma() -> None:
    """Sem entrada propria a tool cai no 'unknown operation — default seguro' (nota do estado-atual)."""
    r = classify(operation="update_ad_schedule", params={"target_count": 3})
    assert r.level is RiskLevel.CONFIRM
    assert "unknown" not in r.reason
```

Run → FAIL (`"unknown" in reason`). Então em `blast_radius.py`, logo antes do default final:

```python
    # update_ad_schedule — always CONFIRM (spec ad_schedule §4: define as janelas
    # em que a campanha serve; o que fica de fora PARA de servir)
    elif operation == "update_ad_schedule":
        return RiskClassification(
            RiskLevel.CONFIRM,
            "update_ad_schedule: redefine a grade de veiculacao (conjunto, nao incremento) — sempre CONFIRM",
        )
```

Run → PASS. Commit: `feat(governance): classify conhece update_ad_schedule`

- [ ] **Step 2: Testes da tool que falham**

```python
@pytest.fixture(autouse=True)
def _ctx():
    from src.mcp.context import McpRequestContext, clear_current, set_current

    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    yield
    clear_current()


class _FakeConn:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _FakePool:
    def acquire(self):
        return _FakeConn()


def _janela_row(cid="1", day="MONDAY", sh=7, eh=17, crit="9", bm=None) -> dict[str, Any]:
    return {"campaign_id": cid, "campaign_name": "A", "criterion_id": crit,
            "resource_name": f"customers/1234567890/campaignCriteria/{cid}~{crit}",
            "day_of_week": day, "start_hour": sh, "start_minute": 0, "end_hour": eh, "end_minute": 0,
            "bid_modifier": bm, "status": "ENABLED"}


def _orc(cid="1", shared=False, rn="customers/1234567890/campaignBudgets/77") -> dict[str, Any]:
    return {"campaign_id": cid, "campaign_name": "A", "budget_resource_name": rn, "budget_id": "77",
            "explicitly_shared": shared, "amount_brl": 310.0}


def _cell(cid="1", day="SATURDAY", hour=10, cost=100.0, conv=5.0) -> dict[str, Any]:
    return {"campaign_id": cid, "day_of_week": day, "hour": hour, "cost_micros": int(cost * 1_000_000), "conversions": conv}


def _wire(monkeypatch, *, grade, orcamentos, metricas, irmas=None):
    """run_report falso despachado por FROM/segments; create_pending capturado; pool falso."""
    captured: dict[str, Any] = {}

    async def _run(**kwargs: Any):
        q = kwargs["query"]
        if "FROM campaign_criterion" in q:
            return grade
        if "segments.hour" in q:
            return metricas
        if "campaign.campaign_budget IN" in q:
            return irmas or []
        if "FROM campaign" in q:
            return orcamentos
        return []

    async def _create_pending(conn, **kwargs):
        captured.update(kwargs)
        return "TOKEN123"

    monkeypatch.setattr("src.mcp.tools.update_ad_schedule.run_report", _run)
    monkeypatch.setattr("src.mcp.tools.update_ad_schedule.create_pending", _create_pending)
    monkeypatch.setattr("src.mcp.tools.update_ad_schedule.connection.get_pool", lambda: _FakePool())
    return captured


SEG_SEX = [{"day_of_week": d, "start_hour": 7, "end_hour": 17} for d in ("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY")]


def test_tool_registrada_como_defer_e_schema_sem_composicao() -> None:
    import json
    t = get_tool("update_ad_schedule")
    assert t is not None and t.bucket == "defer"
    assert not any(k in json.dumps(t.input_schema) for k in ("oneOf", "allOf", "anyOf"))


@pytest.mark.asyncio
async def test_minuto_invalido_e_recusado_antes_de_qualquer_query(monkeypatch) -> None:
    """Spec §8.1."""
    chamou = []

    async def _run(**kwargs):
        chamou.append(1)
        return []

    monkeypatch.setattr("src.mcp.tools.update_ad_schedule.run_report", _run)
    out = await mod.update_ad_schedule({"customer_id": "1234567890", "campaign_ids": ["1"],
                                        "windows": [{"day_of_week": "MONDAY", "start_hour": 7, "start_minute": 10, "end_hour": 17}]})
    assert out["status"] == "error" and "15" in out["error_message"] and "45" in out["error_message"]
    assert chamou == []


@pytest.mark.asyncio
async def test_grade_completa_uma_janela_numa_campanha_com_cinco_remove_quatro(monkeypatch) -> None:
    """Spec §8.2 — a guarda do conjunto-vs-incremento, agora pela TOOL."""
    grade = [_janela_row(day=d, crit=str(i)) for i, d in enumerate(("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY"))]
    captured = _wire(monkeypatch, grade=grade, orcamentos=[_orc()], metricas=[])
    out = await mod.update_ad_schedule({"customer_id": "1234567890", "campaign_ids": ["1"],
                                        "windows": [{"day_of_week": "MONDAY", "start_hour": 7, "end_hour": 17}]})
    assert out["status"] == "dry_run"
    p = out["preview"]["1"]
    assert len(p["windows_removed"]) == 4 and p["windows_added"] == []
    ops = captured["payload"]["ops"]
    assert sum(1 for o in ops if o["kind"] == "remove") == 4 and not any(o["kind"] == "add" for o in ops)


@pytest.mark.asyncio
async def test_grade_identica_devolve_no_changes_sem_token(monkeypatch) -> None:
    """Spec §8.9 — zero operacoes, nenhum token."""
    grade = [_janela_row(day=d, crit=str(i)) for i, d in enumerate(("MONDAY", "TUESDAY"))]
    captured = _wire(monkeypatch, grade=grade, orcamentos=[_orc()], metricas=[])
    out = await mod.update_ad_schedule({"customer_id": "1234567890", "campaign_ids": ["1"],
                                        "windows": [{"day_of_week": "MONDAY", "start_hour": 7, "end_hour": 17},
                                                    {"day_of_week": "TUESDAY", "start_hour": 7, "end_hour": 17}]})
    assert out["status"] == "no_changes" and out["no_changes"] is True
    assert "confirmation_token" not in out
    assert captured == {}, "create_pending nao pode ter sido chamado"


@pytest.mark.asyncio
async def test_preview_traz_cpa_do_que_sai_e_do_que_fica(monkeypatch) -> None:
    """Spec §8.3 — dry-run sem `conversions` nao passa. Campanha 24x7 vira seg-sex."""
    metricas = [_cell(day="SATURDAY", cost=100.0, conv=5.0), _cell(day="SUNDAY", cost=50.0, conv=5.0), _cell(day="MONDAY", hour=9, cost=300.0, conv=10.0)]
    _wire(monkeypatch, grade=[], orcamentos=[_orc()], metricas=metricas)
    out = await mod.update_ad_schedule({"customer_id": "1234567890", "campaign_ids": ["1"], "windows": SEG_SEX})
    m = out["preview"]["1"]["metrics"]
    assert m["leaving"] == {"cost_brl": 150.0, "conversions": 10.0, "cpa_brl": 15.0, "cells": 2}
    assert m["staying"]["cpa_brl"] == 30.0
    assert out["preview"]["1"]["was_24x7"] is True
    assert out["metrics_window"]["days"] == 30


@pytest.mark.asyncio
async def test_orcamento_compartilhado_chega_ao_preview_com_as_irmas_fora_do_lote(monkeypatch) -> None:
    """Spec §8.4 + decisao 03/09: avisar agrupado por orcamento, nao recusar."""
    irmas = [{"campaign_id": "1", "campaign_name": "A", "budget_resource_name": "customers/1234567890/campaignBudgets/77", "status": "ENABLED"},
             {"campaign_id": "2", "campaign_name": "B", "budget_resource_name": "customers/1234567890/campaignBudgets/77", "status": "ENABLED"}]
    _wire(monkeypatch, grade=[], orcamentos=[_orc(shared=True)], metricas=[], irmas=irmas)
    out = await mod.update_ad_schedule({"customer_id": "1234567890", "campaign_ids": ["1"], "windows": SEG_SEX})
    sb = out["shared_budgets"]
    assert len(sb) == 1 and sb[0]["budget_id"] == "77" and sb[0]["explicitly_shared"] is True
    assert sb[0]["campaigns_in_batch"] == ["1"] and sb[0]["campaigns_outside_batch"] == [{"campaign_id": "2", "campaign_name": "B"}]
    assert "realoca" in sb[0]["warning_pt"].lower()
    assert out["status"] == "dry_run"


@pytest.mark.asyncio
async def test_orcamento_nao_compartilhado_nao_gera_bloco(monkeypatch) -> None:
    _wire(monkeypatch, grade=[], orcamentos=[_orc(shared=False)], metricas=[])
    out = await mod.update_ad_schedule({"customer_id": "1234567890", "campaign_ids": ["1"], "windows": SEG_SEX})
    assert out["shared_budgets"] == []


@pytest.mark.asyncio
async def test_payload_pendente_leva_partial_failure_e_target_count_igual_ao_numero_de_ops(monkeypatch) -> None:
    captured = _wire(monkeypatch, grade=[], orcamentos=[_orc()], metricas=[])
    await mod.update_ad_schedule({"customer_id": "1234567890", "campaign_ids": ["1"], "windows": SEG_SEX})
    p = captured["payload"]
    assert p["__partial_failure__"] is True and p["__target_count__"] == 5 == len(p["ops"])
    assert captured["operation_type"] == "update_ad_schedule"
```

- [ ] **Step 3: Rodar para ver falhar** — `ImportError` do módulo (`update_ad_schedule`).

- [ ] **Step 4: Implementar**

```python
# bucket: defer
"""Tool: update_ad_schedule — define a GRADE COMPLETA de veiculacao (spec §4).

Conjunto, nao incremento: o que fica de fora para de servir (§4.1). O diff e
calculado AQUI, no dry-run, por conteudo (§4.4), e viaja no payload pendente —
o builder e burro, e o que o gestor confirma e exatamente o que se aplica.
Dry-run normativo (§4.2): CPA do que sai lado a lado com o que fica.
"""

from typing import Any

from src.db import connection
from src.google_ads.account_clock import resolve_account_today
from src.google_ads.ad_schedule import (
    MetricCell,
    Window,
    diff_schedule,
    partition_metrics,
    summarize_current,
    validate_windows,
    window_from_input,
)
from src.google_ads.queries._common import resolve_date_window
from src.google_ads.queries.ad_schedule import (
    ad_schedule_query,
    campaign_budget_query,
    campaigns_on_budgets_query,
    day_hour_metrics_query,
    parse_ad_schedule_row,
    parse_campaign_budget_row,
    parse_campaign_on_budget_row,
    parse_day_hour_row,
)
from src.google_ads.reports import run_report
from src.governance.blast_radius import classify
from src.governance.dry_run import create_pending
from src.mcp.context import get_current
from src.mcp.tools._mutate_common import error_envelope, preview_envelope
from src.mcp.tools._registry import register_tool
from src.mcp.tools.get_ad_schedule import rows_to_current

_JANELA = {
    "type": "object",
    "properties": {
        "day_of_week": {"type": "string", "enum": ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"]},
        "start_hour": {"type": "integer", "minimum": 0, "maximum": 23},
        "start_minute": {"type": "integer", "enum": [0, 15, 30, 45], "default": 0},
        "end_hour": {"type": "integer", "minimum": 0, "maximum": 24},
        "end_minute": {"type": "integer", "enum": [0, 15, 30, 45], "default": 0},
    },
    "required": ["day_of_week", "start_hour", "end_hour"],
    "additionalProperties": False,
}

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "campaign_ids": {"type": "array", "items": {"type": "string", "pattern": "^[0-9]+$"}, "minItems": 1, "maxItems": 20},
        "windows": {
            "type": "array",
            "items": _JANELA,
            "minItems": 1,
            "maxItems": 168,
            "description": "A GRADE COMPLETA desejada. O que nao estiver aqui deixa de servir.",
        },
        "bid_modifier": {"type": "number", "minimum": 0.1, "maximum": 10.0, "description": "Opcional; aplica as janelas novas e ATUALIZA (sem recriar) as existentes que tenham valor diferente."},
        "date_range": {"type": "string", "enum": ["LAST_7_DAYS", "LAST_14_DAYS", "LAST_30_DAYS", "LAST_90_DAYS"], "default": "LAST_30_DAYS", "description": "Janela das metricas do preview (decisao 03/09: 30 dias com override)."},
        "start_date": {"type": "string", "pattern": "^\\d{4}-\\d{2}-\\d{2}$"},
        "end_date": {"type": "string", "pattern": "^\\d{4}-\\d{2}-\\d{2}$"},
    },
    "required": ["customer_id", "campaign_ids", "windows"],
    "additionalProperties": False,
}

_DESCRIPTION = (
    "[DEFER] Define a GRADE COMPLETA de veiculacao (ad schedule) de 1-20 campanhas. "
    "CONJUNTO, nao incremento: `windows[]` e a grade inteira desejada; o que nao "
    "estiver nela DEIXA DE SERVIR (mandar so 'seg-sex 07-17' numa campanha que servia "
    "24x7 desliga o fim de semana). Always-CONFIRM: devolve preview + confirmation_token; "
    "aplique via apply_change. O preview mostra, por campanha, as janelas que entram e "
    "que saem e — regra normativa — cost_brl, conversions e CPA do que SAI lado a lado "
    "com o CPA do que FICA (custo sozinho nao responde 'o que estou desligando e melhor "
    "ou pior do que fica?'; na MO-JP o fim de semana tinha CPA R$18,59 contra R$23,59). "
    "Metricas por hora cheia (janelas com minutos sao aproximadas), janela default de 30 "
    "dias com override por date_range/start_date+end_date. Grade identica a atual = "
    "`status: no_changes`, ZERO operacoes, sem token (recriar criterios identicos custa "
    "~14 dias de re-learning). Mudar so bid_modifier faz UPDATE do criterio, nao recria. "
    "Orcamento compartilhado: desligar faixa NAO economiza, REALOCA gasto para as faixas "
    "e campanhas irmas do mesmo orcamento (inclusive as fora do lote) — o preview lista "
    "`shared_budgets` com as irmas; nao recusa. Minutos so 0/15/30/45 (API); `end_hour: 24` "
    "= ate o fim do dia. Lote com partial_failure: cada campanha reportada; sem rollback. "
    "Pos-apply, apply_change reconsulta a grade por GAQL e devolve `resulting_schedule`."
)


@register_tool(name="update_ad_schedule", description=_DESCRIPTION, input_schema=_SCHEMA, bucket="defer")
async def update_ad_schedule(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    campaign_ids: list[str] = args["campaign_ids"]
    bid_modifier = args.get("bid_modifier")

    erro = validate_windows(args["windows"])
    if erro:
        return error_envelope("update_ad_schedule", erro, customer_id=customer_id)
    desired = [window_from_input(w) for w in args["windows"]]

    today = await resolve_account_today(customer_id)
    start, end = resolve_date_window(
        date_range=args.get("date_range", "LAST_30_DAYS"),
        start_date=args.get("start_date"),
        end_date=args.get("end_date"),
        today=today,
    )

    async def _consulta(query: str, parser: Any, *, audited: bool = False) -> list[dict[str, Any]]:
        return await run_report(
            manager_id=ctx.manager_id, session_id=ctx.session_id, customer_id=customer_id,
            query=query, row_formatter=parser, operation_name="update_ad_schedule",
            audit_this_call=audited,
            params_summary=({"campaign_ids": campaign_ids, "windows": len(desired)} if audited else None),
        )

    grade_rows = await _consulta(
        ad_schedule_query(campaign_ids=campaign_ids, status="enabled", limit=1000), parse_ad_schedule_row, audited=True
    )
    orcamentos = await _consulta(campaign_budget_query(campaign_ids=campaign_ids), parse_campaign_budget_row)
    metricas = await _consulta(day_hour_metrics_query(campaign_ids=campaign_ids, start=start, end=end), parse_day_hour_row)

    atual = rows_to_current(grade_rows)
    ops: list[dict[str, Any]] = []
    preview: dict[str, Any] = {}
    for cid in campaign_ids:
        current = atual.get(cid, [])
        diff = diff_schedule(current, desired, bid_modifier)
        before = [c.window for c in current] if current else None  # None = 24x7
        cells = [MetricCell(m["day_of_week"], m["hour"], m["cost_micros"], m["conversions"]) for m in metricas if m["campaign_id"] == cid]
        preview[cid] = {
            "was_24x7": not current,
            "current": summarize_current(current),
            "windows_added": [_w(w) for w in diff.to_add],
            "windows_removed": [_w(c.window) for c in diff.to_remove],
            "bid_modifier_updated": [_w(c.window) for c in diff.to_update],
            "metrics": partition_metrics(cells, before, desired),
        }
        ops += [{"kind": "add", "campaign_id": cid, "window": _w(w), "bid_modifier": bid_modifier} for w in diff.to_add]
        ops += [{"kind": "remove", "resource_name": c.resource_name} for c in diff.to_remove]
        ops += [{"kind": "update", "resource_name": c.resource_name, "bid_modifier": bid_modifier} for c in diff.to_update]

    if not ops:
        return {
            "status": "no_changes",
            "operation": "update_ad_schedule",
            "customer_id": customer_id,
            "no_changes": True,
            "message": "A grade desejada e identica a atual em todas as campanhas: nenhuma operacao emitida (recriar criterios identicos custaria re-learning).",
            "current_schedule": {cid: preview[cid]["current"] for cid in campaign_ids},
        }

    shared_budgets = await _blocos_de_orcamento_compartilhado(_consulta, orcamentos, campaign_ids)

    target_count = len(ops)
    risk = classify(operation="update_ad_schedule", params={"target_count": target_count})
    resumo = (
        f"Redefinir a grade de {len(campaign_ids)} campanha(s): {sum(len(p['windows_added']) for p in preview.values())} janela(s) entram, "
        f"{sum(len(p['windows_removed']) for p in preview.values())} saem, {sum(len(p['bid_modifier_updated']) for p in preview.values())} mudam bid_modifier "
        f"({target_count} operacoes). Janelas fora da grade DEIXAM de servir."
    )
    payload = {
        "campaign_ids": campaign_ids,
        "ops": ops,
        "__target_count__": target_count,
        "__partial_failure__": True,
        "__params_summary__": {"target_count": target_count, "campaigns": len(campaign_ids), "window_days": (end - start).days + 1},
    }
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        token = await create_pending(
            conn, manager_id=ctx.manager_id, session_id=ctx.session_id, customer_id=customer_id,
            operation_type="update_ad_schedule", payload=payload, blast_summary=resumo,
        )
    return preview_envelope(
        "update_ad_schedule", customer_id, resumo, token,
        confirmation_reason=risk.reason,
        target_count=target_count,
        preview=preview,
        shared_budgets=shared_budgets,
        metrics_window={"start": start.isoformat(), "end": end.isoformat(), "days": (end - start).days + 1},
    )


def _w(w: Window) -> dict[str, Any]:
    return {"day_of_week": w.day_of_week, "start_hour": w.start_hour, "start_minute": w.start_minute, "end_hour": w.end_hour, "end_minute": w.end_minute}


async def _blocos_de_orcamento_compartilhado(consulta: Any, orcamentos: list[dict[str, Any]], campaign_ids: list[str]) -> list[dict[str, Any]]:
    """Spec §4.3 + decisao 03/09: um bloco por orcamento compartilhado, com as irmas fora do lote. Avisa; nao recusa."""
    compartilhados = {o["budget_resource_name"]: o for o in orcamentos if o["explicitly_shared"]}
    if not compartilhados:
        return []
    irmas = await consulta(campaigns_on_budgets_query(budget_resource_names=list(compartilhados)), parse_campaign_on_budget_row)
    no_lote = set(campaign_ids)
    blocos: list[dict[str, Any]] = []
    for rn, o in compartilhados.items():
        todas = [i for i in irmas if i["budget_resource_name"] == rn]
        dentro = sorted(i["campaign_id"] for i in todas if i["campaign_id"] in no_lote)
        fora = [{"campaign_id": i["campaign_id"], "campaign_name": i["campaign_name"]} for i in todas if i["campaign_id"] not in no_lote]
        blocos.append({
            "budget_id": o["budget_id"],
            "budget_resource_name": rn,
            "explicitly_shared": True,
            "amount_brl": o["amount_brl"],
            "campaigns_in_batch": dentro,
            "campaigns_outside_batch": fora,
            "warning_pt": (
                f"Orcamento compartilhado {o['budget_id']} (R$ {o['amount_brl']:.2f}/dia) e de {len(todas)} campanha(s); "
                f"{len(dentro)} no lote, {len(fora)} fora. Desligar faixas aqui NAO devolve dinheiro: realoca a pressao "
                "para as faixas e campanhas irmas que sobram, inclusive as fora do lote. Em quanto tempo e com que "
                "completude a verba se redistribui e pacing do Google — nao ha como medir por API."
            ),
        })
    return blocos
```

- [ ] **Step 5: Rodar para ver passar** — `python -m pytest tests/unit/test_update_ad_schedule.py tests/unit/test_tools_schemas.py tests/unit/test_no_server_clock_in_google_tools.py -q`. Confira também o guard derivado do F112 (grep `classify` em `tests/unit/` por "F112"/"blast_radius" e rode-o): a tool nova usa `classify` e `preview_envelope` do compartilhado (spec §8.10) — se o guard enumerar tools, adicione `update_ad_schedule` onde ele espera.

- [ ] **Step 6: Sabotagem** — em cópia de `update_ad_schedule.py`: (a) `desired` tratado como delta (`diff_schedule(current, [*[c.window for c in current], *desired], ...)`): `test_grade_completa_...` tem que falhar; (b) remover `"conversions"` do `_agrega` em `ad_schedule.py`: `test_preview_traz_cpa...` tem que falhar; (c) `if not ops:` → `if False:`: `test_grade_identica_...` tem que falhar; (d) `_blocos_...` devolvendo `[]` sempre: `test_orcamento_compartilhado_...` tem que falhar. Restaure.

- [ ] **Step 7: Commit** — `feat(mcp): update_ad_schedule — grade completa, dry-run com CPA dos dois lados, no-op idempotente, aviso por orcamento`

---

### Task 8: `apply_change` — confirmação de estado pós-apply (§4.6)

**Files:**
- Modify: `src/mcp/tools/apply_change.py` — inserir um branch **antes** do `# Default path` (~linha 118)
- Test: `tests/unit/test_apply_change_ad_schedule.py`

**Interfaces:**
- Consumes: `run_mutation` (resposta com `applied_count`, `changed_count`, `resource_names`, `provider_request_id`); `ad_schedule_query`/`parse_ad_schedule_row`; `run_report`; `rows_to_current` + `summarize_current`.
- Produces: resposta do `apply_change` para `update_ad_schedule` = envelope genérico **+** `"resulting_schedule": {campaign_id: {"windows": [...], **summarize_current(...)}}`.

- [ ] **Step 1: Teste que falha**

```python
"""apply_change de update_ad_schedule reconsulta a grade (spec §4.6): o ACK da mutacao
nao basta — a UI falhou em silencio duas vezes nessa conta."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from src.mcp.tools import apply_change as mod


@pytest.fixture(autouse=True)
def _ctx():
    from src.mcp.context import McpRequestContext, clear_current, set_current

    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    yield
    clear_current()


class _FakeConn:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _FakePool:
    def acquire(self):
        return _FakeConn()


@pytest.mark.asyncio
async def test_apply_reconsulta_a_grade_e_devolve_resulting_schedule(monkeypatch) -> None:
    saved = SimpleNamespace(
        operation_type="update_ad_schedule",
        customer_id="1234567890",
        blast_summary="x",
        payload={"campaign_ids": ["1"], "ops": [{"kind": "remove", "resource_name": "customers/1234567890/campaignCriteria/1~9"}],
                 "__target_count__": 1, "__partial_failure__": True},
    )

    async def _consume(conn, *, token, session_id):
        return saved

    async def _run_mutation(**kwargs):
        assert kwargs["partial_failure"] is True
        return {"provider_request_id": "req-1", "applied_count": 1, "changed_count": 1, "resource_names": ["customers/1234567890/campaignCriteria/1~9"]}

    async def _run_report(**kwargs):
        assert "FROM campaign_criterion" in kwargs["query"]
        return [{"campaign_id": "1", "campaign_name": "A", "criterion_id": "10",
                 "resource_name": "customers/1234567890/campaignCriteria/1~10",
                 "day_of_week": "MONDAY", "start_hour": 7, "start_minute": 0, "end_hour": 17, "end_minute": 0,
                 "bid_modifier": None, "status": "ENABLED"}]

    monkeypatch.setattr(mod, "consume", _consume)
    monkeypatch.setattr(mod, "run_mutation", _run_mutation)
    monkeypatch.setattr(mod, "run_report", _run_report)
    monkeypatch.setattr(mod.connection, "get_pool", lambda: _FakePool())

    out = await mod.apply_change({"confirmation_token": "ABCDEFGH"})
    assert out["status"] == "applied" and out["applied_count"] == 1 and out["changed_count"] == 1
    rs = out["resulting_schedule"]["1"]
    assert rs["has_schedule"] is True and rs["hours_per_week"] == 10.0
    assert rs["windows"][0]["day_of_week"] == "MONDAY"
```

> Fato conferido (03/09): `apply_change.py` importa hoje `connection` (de `src.db`), `run_conversion_upload`, `run_mutation`, `InvalidTokenError`/`consume` (de `src.governance.dry_run`), `get_current`, `error_envelope`, `register_tool`. **Não** importa `run_report` — o Step 3 desta task adiciona esse import (e os de `ad_schedule_query`, `parse_ad_schedule_row`, `rows_to_current`, `summarize_current`); só depois disso `monkeypatch.setattr(mod, "run_report", ...)` resolve. É por isso que o RED do Step 2 pode ser `AttributeError` em vez de `KeyError`.

- [ ] **Step 2: Rodar para ver falhar** — `KeyError: 'resulting_schedule'` (ou `AttributeError` em `mod.run_report` se ainda não importado).

- [ ] **Step 3: Implementar** — em `apply_change.py`, importar `run_report` de `src.google_ads.reports`, `ad_schedule_query`/`parse_ad_schedule_row` de `src.google_ads.queries.ad_schedule`, `rows_to_current` de `src.mcp.tools.get_ad_schedule`, `summarize_current` de `src.google_ads.ad_schedule`; e antes do `# Default path`:

```python
    # ad_schedule §4.6: confirmacao de estado por GAQL. A UI falhou em silencio duas
    # vezes nessa conta; confiar no ACK da mutacao repetiria o problema num canal novo.
    if saved.operation_type == "update_ad_schedule":
        result = await run_mutation(
            manager_id=ctx.manager_id, session_id=ctx.session_id, customer_id=saved.customer_id,
            operation_type=saved.operation_type, payload=saved.payload, target_count=target_count,
            partial_failure=True, params_summary=params_summary,
        )
        campaign_ids = list(saved.payload.get("campaign_ids", []))
        rows = await run_report(
            manager_id=ctx.manager_id, session_id=ctx.session_id, customer_id=saved.customer_id,
            query=ad_schedule_query(campaign_ids=campaign_ids, status="enabled", limit=1000),
            row_formatter=parse_ad_schedule_row, operation_name="update_ad_schedule_confirm",
        )
        atual = rows_to_current(rows)
        resulting = {
            cid: {"windows": [r for r in rows if r["campaign_id"] == cid], **summarize_current(atual.get(cid, []))}
            for cid in campaign_ids
        }
        return {
            "status": "applied",
            "operation": saved.operation_type,
            "customer_id": saved.customer_id,
            "blast_summary": saved.blast_summary,
            "provider_request_id": result["provider_request_id"],
            "applied_count": result["applied_count"],
            "changed_count": result.get("changed_count"),
            "resource_names": result.get("resource_names", []),
            "resulting_schedule": resulting,
        }
```

- [ ] **Step 4: Rodar para ver passar**; rodar também `tests/unit/test_apply_change*.py` existentes (nada deles pode mudar). **Step 5: Commit** — `feat(mcp): apply_change reconsulta a grade apos update_ad_schedule (spec §4.6)`

---

### Task 9: Guards derivados e gate completo

**Files:**
- Test: `tests/unit/test_ad_schedule_guards.py`

- [ ] **Step 1: Guard de assinatura + guard de envelope**

```python
"""Guards do ad_schedule que nao cabem nos testes de comportamento.

Regra do repo: guard que assere o ADJACENTE nao e guard. Aqui se assere
propriedade (assinatura, conjunto), nao presenca de string.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from src.google_ads.ad_schedule import diff_schedule, partition_metrics, validate_windows


def test_diff_recebe_grade_completa_e_bid_modifier_explicito() -> None:
    p = inspect.signature(diff_schedule).parameters
    assert list(p) == ["current", "desired", "bid_modifier"]
    assert p["bid_modifier"].default is inspect.Parameter.empty, "sem default: o chamador decide"


def test_partition_metrics_exige_before_e_after() -> None:
    p = inspect.signature(partition_metrics).parameters
    assert list(p) == ["cells", "before", "after"] and all(x.default is inspect.Parameter.empty for x in p.values())


def test_validate_windows_menciona_os_quatro_minutos_validos() -> None:
    err = validate_windows([{"day_of_week": "MONDAY", "start_hour": 7, "start_minute": 10, "end_hour": 17}])
    assert err is not None and all(m in err for m in ("0", "15", "30", "45"))


def _chamadas(src: str, nome: str) -> int:
    return sum(
        1 for n in ast.walk(ast.parse(src))
        if isinstance(n, ast.Call) and getattr(n.func, "id", None) == nome
    )


def test_update_ad_schedule_usa_envelope_e_classify_do_compartilhado() -> None:
    """Spec §8.10 (espirito do F112): nem envelope a mao, nem nivel fixado sem classify."""
    src = Path("src/mcp/tools/update_ad_schedule.py").read_text(encoding="utf-8")
    assert _chamadas(src, "classify") >= 1
    assert _chamadas(src, "preview_envelope") >= 1 and _chamadas(src, "error_envelope") >= 1
    assert "DEFAULT_TTL_MINUTES" not in src and "expires_in_minutes" not in src, "TTL vem do envelope, nao da tool"
```

- [ ] **Step 2: Rodar** — PASS de primeira é esperado aqui (são guards sobre código já escrito). **Verifique-os por sabotagem**: troque `preview_envelope(` por um dict literal em cópia → o último teste falha; dê default `None` a `bid_modifier` em `diff_schedule` → o primeiro falha. Restaure.

- [ ] **Step 3: Gate completo** — `python scripts/check_pre_push.py > /dev/null 2>&1; echo $?` → `0`. Se Docker estiver de pé, rode também `python -m pytest -m integration tests/integration -q -k "apply_change or dry_run"` (o `create_pending` real com DB).

- [ ] **Step 4: Commit** — `test(mcp): guards do ad_schedule — assinaturas e envelope do compartilhado`

---

### Task 10: Docs, runbook de smoke e estado

**Files:**
- Create: `docs/operacao/phase-3b-42-ad-schedule-smoke.md`
- Modify: `docs/operacao/estado-atual.md` (contagem de tools 66 → **68**; bucket defer 43 → 45; registrar o sprint e o F140 para o smoke)

- [ ] **Step 1: Runbook** — mesma estrutura de `phase-3b-41-assets-smoke.md` (legenda ✅/◐/⬜, tabela, um bloco por teste com setup/asserções/failure modes). Conta: **`1163862076`** (teste do Wellington) para T3–T6; **`7862230676`** só leitura. Testes:

| # | Teste | Asserção incondicional |
|---|---|---|
| T1 | `get_ad_schedule(7862230676)` sem filtro | cada campanha em `schedule_summary`; as sem janela com `has_schedule: false` e `hours_per_week: 168`; `budget_is_shared: true` nas duas do portfólio |
| T2 | `get_ad_schedule` com `status="all"` | aparece ao menos uma janela `REMOVED` se existir; contagem ≥ T1 |
| T3 | `update_ad_schedule(1163862076, [campanha PAUSED de teste], windows=SEG-SEX 07–17)` | `status: dry_run`; `preview[cid].was_24x7` correto; `metrics.leaving` e `metrics.staying` com `conversions` e `cpa_brl` (pode ser `null`); `metrics_window.days == 30` |
| T4 | `apply_change` do T3 | `applied_count == 5`, `changed_count == 5`, `resulting_schedule[cid].hours_per_week == 50.0` |
| T5 | **Confirmação por GAQL** (§7): `SELECT campaign_criterion.criterion_id, campaign_criterion.status, campaign_criterion.ad_schedule.day_of_week FROM campaign_criterion WHERE campaign.id = <cid> AND campaign_criterion.type = 'AD_SCHEDULE'` | 5 linhas `ENABLED` seg–sex; **nunca** por `row_count` sem filtro |
| T6 | Reenviar a MESMA grade do T3 | `status: no_changes`, sem token — e GAQL mostra os **mesmos `criterion_id`** do T5 (prova de que não recriou) |
| T7 | `update_ad_schedule` com `bid_modifier: 1.1` e a mesma grade | preview com 5 em `bid_modifier_updated`, 0 add/remove; apply; GAQL mostra `bid_modifier = 1.1` nos mesmos `criterion_id` |
| T8 | Restaurar: `windows` = grade 24×7 explícita (7 dias 0–24) **ou** remoção manual — registre qual | GAQL confirma |
| T9 | `update_ad_schedule` com `start_minute: 10` | `status: error` citando 0/15/30/45; **nenhum** token |

Notas obrigatórias: reconectar o MCP antes (F140); o passo de mutação pode barrar no classificador do harness (nota do runbook 3b.41); tolerância em asserções de métrica (não asserir igualdade de `cost_brl` entre duas leituras — deriva entre réplicas, F131-bis).

- [ ] **Step 2: `estado-atual.md`** — atualizar contagem de tools (`grep -c 'bucket="' src/mcp/tools/*.py` para confirmar 68/45), acrescentar uma linha no bloco de sessão com o sprint e o link do runbook, e mover `ad_schedule` de "próximo candidato" para "entregue, smoke pendente".

- [ ] **Step 3: Gate + commit** — `docs(operacao): runbook 3b.42 do ad_schedule e estado-atual` — depois **branch → PR** (`fix/`→ aqui `feat/ad-schedule`), CI verde, merge pelo Wellington, e o smoke **só em sessão MCP nova**.

---

## Self-review (feito ao escrever; releia antes de despachar)

- **Cobertura da spec:** §3 → Task 5 (schema, `has_schedule`, `hours_per_week`, `budget_is_shared`, `limit`/`truncated`); §4.1 → Tasks 2 e 7 (conjunto; `diff`; teste da 1-janela-remove-4); §4.2 → Tasks 3 e 7 (CPA dos dois lados; janela 30 dias com override; `metrics_granularity`); §4.3 → Task 7 (`shared_budgets`, aviso agrupado, irmãs fora do lote — decisão 03/09); §4.4 → Tasks 2 e 7 (`no_changes` sem token; diff por conteúdo; `update` de `bid_modifier` sem recriar); §4.5 → Task 7 (`__partial_failure__`, sem rollback); §4.6 → Task 8 (`resulting_schedule`); §8.1 → Tasks 1, 7, 9; §8.2 → Tasks 2, 7; §8.3 → Tasks 3, 7; §8.4 → Task 7; §8.5 → runbook T5/T6 (Task 10); §8.9 → Tasks 2, 7; §8.10 → Task 9; §9 → ordem 5 antes de 7.
- **Fora da spec, decidido aqui e visível na description:** convenção de hora cheia para métricas; `end_hour: 24`; `update` de `bid_modifier` via mask (a spec não previa `bid_modifier` em janela existente; recriar seria a §4.4 quebrada pela porta dos fundos).
- **Consistência de nomes entre tasks:** `Window`, `CurrentWindow`, `ScheduleDiff`, `MetricCell`, `window_from_input`, `validate_windows`, `diff_schedule`, `partition_metrics`, `summarize_current`, `covers`, `hours_per_week`, `rows_to_current`, `ad_schedule_query`, `parse_ad_schedule_row`, `campaign_budget_query`, `parse_campaign_budget_row`, `campaigns_on_budgets_query`, `parse_campaign_on_budget_row`, `day_hour_metrics_query`, `parse_day_hour_row`, `build_update_ad_schedule`, payload `ops[].kind ∈ {add, remove, update}` — os mesmos em todas as tasks.
- **Fatos de código conferidos em 03/09 e gravados no lugar:** assinatura/saída de `gaql_in_list` (Task 4), `campaign_path` do capture client (Task 6), imports atuais de `apply_change.py` (Task 8). Nada ficou para "conferir depois".
