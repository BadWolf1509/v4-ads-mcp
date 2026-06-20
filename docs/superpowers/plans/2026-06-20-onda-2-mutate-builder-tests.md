# Onda 2 — Cobertura de testes dos builders de mutate — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fechar a classe F50/F51 dando cobertura de teste de execução (capture-client) aos **10 builders de mutate** que shiparam sem teste, e adicionar um guard estrutural que torna esse gap impossível de reincidir.

**Architecture:** 5 arquivos de teste novos (1 por módulo de mutate, nomeados `test_*_builder.py` pra casar os guards existentes), cada um usando `make_capture_client` (NUNCA MagicMock cru) com asserções de presença/ausência/FieldMask. + 1 guard novo em `test_tools_schemas.py` que enumera `_BUILDERS` e exige um teste por builder. Isto testa código **já existente** (não é TDD red→green): os testes devem PASSAR ao escrever; se um falhar, achou um bug real no builder (reportar, não "ajustar o teste").

**Tech Stack:** Python 3.13 · pytest (`asyncio_mode=auto`) · `tests/unit/fixtures/proto_capture.py::make_capture_client` · `google.protobuf.field_mask_pb2.FieldMask`.

## Global Constraints

- **`make_capture_client` SEMPRE, MagicMock NUNCA.** O guard `test_builder_tests_use_capture_client_not_magicmock` falha qualquer `test_*_builder.py` que referencie `MagicMock` sem importar `make_capture_client`. **Não importe `MagicMock`** nos testes — pro override de enum use um `dict` puro.
- **Nome dos arquivos termina em `_builder.py`** (casa o glob `test_*_builder.py` dos dois guards).
- **Asserção presença E ausência (F51):** onde houver branch/oneof, assertar o campo correto setado E `op.has("<campo_errado>") is False`.
- **FieldMask:** `client.copy_from` é um `MagicMock` (o mask NÃO entra no `CapturedOp`). Verifique via `client.copy_from.call_args_list[N].args[1].paths` → comparar com `list(...) == [...]`.
- **Status enums via subscript:** `AdGroupStatusEnum`, `AdGroupAdStatusEnum`, `AdGroupCriterionStatusEnum` são MagicMock na fixture → `enum[new_status]` devolve um MagicMock, não a key. **Override local com dict** no teste: `client.enums.<Enum> = {"ENABLED": "ENABLED", "PAUSED": "PAUSED", "REMOVED": "REMOVED"}`. `CampaignStatusEnum` já é `_BareEnumDict` (subscript devolve a key) → não precisa override. `KeywordMatchTypeEnum` já é `_BareEnumDict`.
- **Estes testes devem PASSAR ao escrever** (validam builder existente). Se algum FALHAR, é um bug real no builder — reporte como DONE_WITH_CONCERNS com o diagnóstico; NÃO relaxe o teste pra passar.
- **Verificação antes de cada commit:** `python scripts/check_pre_push.py` verde (estes são unit tests, sem DB — `check_pre_push` cobre 100%).
- **Commits:** `test(mcp): ...` + trailer `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

---

### Task 1: Testes dos builders de `campaigns.py`

**Files:**
- Test: `tests/unit/test_campaign_mutate_builder.py` (criar)
- Under test (não modificar): `src/google_ads/mutates/campaigns.py` (`build_update_campaign_status:16`, `build_update_campaign_budget:40`, `build_update_campaign_bidding:61`)

- [ ] **Step 1: Escrever o arquivo de teste**

```python
"""Builder tests for campaigns.py update_* mutates (Onda 2 — fecha F50/F51).

Estes builders shiparam sem teste de execução. Capture-client asserta os
campos proto, o FieldMask e (no bidding) o oneof correto + ausência dos outros.
"""

from src.google_ads.mutates.campaigns import (
    build_update_campaign_bidding,
    build_update_campaign_budget,
    build_update_campaign_status,
)
from tests.unit.fixtures.proto_capture import make_capture_client


def test_update_campaign_status_sets_status_and_mask() -> None:
    client = make_capture_client()
    ops = build_update_campaign_status(
        client, "1234567890", {"campaign_ids": ["111", "222"], "new_status": "PAUSED"}
    )
    assert len(ops) == 2
    base = "campaign_operation.update"
    assert ops[0].field(f"{base}.resource_name") == "customers/1234567890/campaigns/111"
    # CampaignStatusEnum é _BareEnumDict → subscript devolve a key
    assert ops[0].field(f"{base}.status") == "PAUSED"
    assert ops[1].field(f"{base}.resource_name") == "customers/1234567890/campaigns/222"
    assert list(client.copy_from.call_args_list[0].args[1].paths) == ["status"]
    # F51: não tocou outros campos
    assert ops[0].has(f"{base}.name") is False


def test_update_campaign_budget_sets_amount_and_mask() -> None:
    client = make_capture_client()
    ops = build_update_campaign_budget(
        client,
        "1234567890",
        {
            "campaign_budget_resource_name": "customers/1234567890/campaignBudgets/55",
            "new_amount_micros": 5_000_000,
        },
    )
    assert len(ops) == 1
    base = "campaign_budget_operation.update"
    assert ops[0].field(f"{base}.resource_name") == "customers/1234567890/campaignBudgets/55"
    assert ops[0].field(f"{base}.amount_micros") == 5_000_000
    assert list(client.copy_from.call_args_list[0].args[1].paths) == ["amount_micros"]


def test_bidding_target_cpa_sets_oneof_and_mask() -> None:
    client = make_capture_client()
    ops = build_update_campaign_bidding(
        client,
        "1234567890",
        {"campaign_id": "111", "strategy": "TARGET_CPA", "target_value_micros": 3_000_000},
    )
    base = "campaign_operation.update"
    assert ops[0].field(f"{base}.resource_name") == "customers/1234567890/campaigns/111"
    assert ops[0].field(f"{base}.target_cpa.target_cpa_micros") == 3_000_000
    assert list(client.copy_from.call_args_list[0].args[1].paths) == ["target_cpa.target_cpa_micros"]
    # oneof guard: os outros branches NÃO foram setados
    assert ops[0].has(f"{base}.target_roas.target_roas") is False
    assert ops[0].has(f"{base}.maximize_conversions.target_cpa_micros") is False


def test_bidding_target_roas_sets_oneof_and_mask() -> None:
    client = make_capture_client()
    ops = build_update_campaign_bidding(
        client, "1234567890", {"campaign_id": "111", "strategy": "TARGET_ROAS", "target_roas": 4.0}
    )
    base = "campaign_operation.update"
    assert ops[0].field(f"{base}.target_roas.target_roas") == 4.0
    assert list(client.copy_from.call_args_list[0].args[1].paths) == ["target_roas.target_roas"]
    assert ops[0].has(f"{base}.target_cpa.target_cpa_micros") is False


def test_bidding_maximize_conversions_sets_oneof_and_mask() -> None:
    client = make_capture_client()
    ops = build_update_campaign_bidding(
        client,
        "1234567890",
        {"campaign_id": "111", "strategy": "MAXIMIZE_CONVERSIONS", "target_value_micros": 2_000_000},
    )
    base = "campaign_operation.update"
    assert ops[0].field(f"{base}.maximize_conversions.target_cpa_micros") == 2_000_000
    assert list(client.copy_from.call_args_list[0].args[1].paths) == [
        "maximize_conversions.target_cpa_micros"
    ]
    assert ops[0].has(f"{base}.target_cpa.target_cpa_micros") is False


def test_bidding_unsupported_strategy_raises() -> None:
    client = make_capture_client()
    import pytest

    with pytest.raises(ValueError, match="Unsupported bidding strategy"):
        build_update_campaign_bidding(
            client, "1234567890", {"campaign_id": "111", "strategy": "FOO"}
        )
```

- [ ] **Step 2: Rodar — devem PASSAR (builder existe e correto)**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_campaign_mutate_builder.py -v`
Expected: PASS (6 passed). Se algum FALHAR, é bug real em `campaigns.py` — reporte DONE_WITH_CONCERNS com o diagnóstico, não relaxe o teste.

- [ ] **Step 3: Verificação + commit**

```bash
.venv/Scripts/python.exe scripts/check_pre_push.py
git add tests/unit/test_campaign_mutate_builder.py
git commit -m "test(mcp): cobertura capture-client dos builders update_campaign_* (F50/F51)" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Testes dos builders de `ad_groups.py`

**Files:**
- Test: `tests/unit/test_ad_group_mutate_builder.py` (criar)
- Under test: `src/google_ads/mutates/ad_groups.py` (`build_update_ad_group_status:11`, `build_update_ad_group_bid:34`)

**Interfaces:**
- `build_update_ad_group_bid` payload: `{bids: [{ad_group_id, new_cpc_bid_micros}]}`. **`new_cpc_bid_micros == 0` → NÃO seta `cpc_bid_micros`** (clear override), mas o mask `["cpc_bid_micros"]` é sempre setado.

- [ ] **Step 1: Escrever o arquivo de teste**

```python
"""Builder tests for ad_groups.py update_* mutates (Onda 2 — fecha F50/F51).

O ponto sutil: update_ad_group_bid com new_cpc_bid_micros==0 NÃO seta o campo
(clear override) mas mantém o FieldMask — testar a AUSÊNCIA é o que pega a regressão.
"""

from src.google_ads.mutates.ad_groups import (
    build_update_ad_group_bid,
    build_update_ad_group_status,
)
from tests.unit.fixtures.proto_capture import make_capture_client

_STATUS_ENUM = {"ENABLED": "ENABLED", "PAUSED": "PAUSED", "REMOVED": "REMOVED"}


def test_update_ad_group_status_sets_status_and_mask() -> None:
    client = make_capture_client()
    client.enums.AdGroupStatusEnum = _STATUS_ENUM  # subscript → key (fixture é MagicMock)
    ops = build_update_ad_group_status(
        client, "1234567890", {"ad_group_ids": ["111"], "new_status": "PAUSED"}
    )
    assert len(ops) == 1
    base = "ad_group_operation.update"
    assert ops[0].field(f"{base}.resource_name") == "customers/1234567890/adGroups/111"
    assert ops[0].field(f"{base}.status") == "PAUSED"
    assert list(client.copy_from.call_args_list[0].args[1].paths) == ["status"]


def test_update_ad_group_bid_sets_value_and_mask() -> None:
    client = make_capture_client()
    ops = build_update_ad_group_bid(
        client, "1234567890", {"bids": [{"ad_group_id": "111", "new_cpc_bid_micros": 1_500_000}]}
    )
    base = "ad_group_operation.update"
    assert ops[0].field(f"{base}.resource_name") == "customers/1234567890/adGroups/111"
    assert ops[0].field(f"{base}.cpc_bid_micros") == 1_500_000
    assert list(client.copy_from.call_args_list[0].args[1].paths) == ["cpc_bid_micros"]


def test_update_ad_group_bid_clear_override_omits_value_keeps_mask() -> None:
    client = make_capture_client()
    ops = build_update_ad_group_bid(
        client, "1234567890", {"bids": [{"ad_group_id": "111", "new_cpc_bid_micros": 0}]}
    )
    base = "ad_group_operation.update"
    # CRÍTICO: cpc_bid_micros NÃO setado (clear), mas o mask sinaliza o clear
    assert ops[0].has(f"{base}.cpc_bid_micros") is False
    assert list(client.copy_from.call_args_list[0].args[1].paths) == ["cpc_bid_micros"]
```

- [ ] **Step 2: Rodar — devem PASSAR**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_ad_group_mutate_builder.py -v`
Expected: PASS (3 passed). Falha → bug real, reporte DONE_WITH_CONCERNS.

- [ ] **Step 3: Verificação + commit**

```bash
.venv/Scripts/python.exe scripts/check_pre_push.py
git add tests/unit/test_ad_group_mutate_builder.py
git commit -m "test(mcp): cobertura capture-client dos builders update_ad_group_* (clear-override)" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Teste do builder de `ads.py` (`update_ad_status`)

**Files:**
- Test: `tests/unit/test_ad_status_mutate_builder.py` (criar)
- Under test: `src/google_ads/mutates/ads.py` (`build_update_ad_status:11`)

- [ ] **Step 1: Escrever o arquivo de teste**

```python
"""Builder test for ads.py build_update_ad_status (Onda 2 — fecha F50/F51)."""

from src.google_ads.mutates.ads import build_update_ad_status
from tests.unit.fixtures.proto_capture import make_capture_client


def test_update_ad_status_sets_status_and_mask() -> None:
    client = make_capture_client()
    client.enums.AdGroupAdStatusEnum = {"ENABLED": "ENABLED", "PAUSED": "PAUSED", "REMOVED": "REMOVED"}
    ops = build_update_ad_status(
        client,
        "1234567890",
        {"ads": [{"ad_group_id": "111", "ad_id": "222"}], "new_status": "PAUSED"},
    )
    assert len(ops) == 1
    base = "ad_group_ad_operation.update"
    assert ops[0].field(f"{base}.resource_name") == "customers/1234567890/adGroupAds/111~222"
    assert ops[0].field(f"{base}.status") == "PAUSED"
    assert list(client.copy_from.call_args_list[0].args[1].paths) == ["status"]
```

- [ ] **Step 2: Rodar — deve PASSAR**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_ad_status_mutate_builder.py -v`
Expected: PASS (1 passed).

- [ ] **Step 3: Verificação + commit**

```bash
.venv/Scripts/python.exe scripts/check_pre_push.py
git add tests/unit/test_ad_status_mutate_builder.py
git commit -m "test(mcp): cobertura capture-client do builder update_ad_status" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Testes dos builders de `keywords.py` (`update_keyword_status`, `update_keyword_bid`)

**Files:**
- Test: `tests/unit/test_keyword_mutate_builder.py` (criar)
- Under test: `src/google_ads/mutates/keywords.py` (`build_update_keyword_status:11`, `build_update_keyword_bid:36`)

**Nota:** `add_keywords` (mesmo módulo) já tem `test_add_keywords_builder.py` — não duplicar.

- [ ] **Step 1: Escrever o arquivo de teste**

```python
"""Builder tests for keywords.py update_keyword_* mutates (Onda 2 — fecha F50/F51).

resource_name é o path composto adGroupCriteria/{ag}~{crit}. update_keyword_bid
tem o mesmo clear-override (==0 omite cpc_bid_micros, mantém o mask).
"""

from src.google_ads.mutates.keywords import (
    build_update_keyword_bid,
    build_update_keyword_status,
)
from tests.unit.fixtures.proto_capture import make_capture_client


def test_update_keyword_status_sets_status_and_mask() -> None:
    client = make_capture_client()
    client.enums.AdGroupCriterionStatusEnum = {
        "ENABLED": "ENABLED",
        "PAUSED": "PAUSED",
        "REMOVED": "REMOVED",
    }
    ops = build_update_keyword_status(
        client,
        "1234567890",
        {"keywords": [{"ad_group_id": "111", "criterion_id": "222"}], "new_status": "PAUSED"},
    )
    assert len(ops) == 1
    base = "ad_group_criterion_operation.update"
    assert ops[0].field(f"{base}.resource_name") == "customers/1234567890/adGroupCriteria/111~222"
    assert ops[0].field(f"{base}.status") == "PAUSED"
    assert list(client.copy_from.call_args_list[0].args[1].paths) == ["status"]


def test_update_keyword_bid_sets_value_and_mask() -> None:
    client = make_capture_client()
    ops = build_update_keyword_bid(
        client,
        "1234567890",
        {"bids": [{"ad_group_id": "111", "criterion_id": "222", "new_cpc_bid_micros": 900_000}]},
    )
    base = "ad_group_criterion_operation.update"
    assert ops[0].field(f"{base}.resource_name") == "customers/1234567890/adGroupCriteria/111~222"
    assert ops[0].field(f"{base}.cpc_bid_micros") == 900_000
    assert list(client.copy_from.call_args_list[0].args[1].paths) == ["cpc_bid_micros"]


def test_update_keyword_bid_clear_override_omits_value_keeps_mask() -> None:
    client = make_capture_client()
    ops = build_update_keyword_bid(
        client,
        "1234567890",
        {"bids": [{"ad_group_id": "111", "criterion_id": "222", "new_cpc_bid_micros": 0}]},
    )
    base = "ad_group_criterion_operation.update"
    assert ops[0].has(f"{base}.cpc_bid_micros") is False
    assert list(client.copy_from.call_args_list[0].args[1].paths) == ["cpc_bid_micros"]
```

- [ ] **Step 2: Rodar — devem PASSAR**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_keyword_mutate_builder.py -v`
Expected: PASS (3 passed).

- [ ] **Step 3: Verificação + commit**

```bash
.venv/Scripts/python.exe scripts/check_pre_push.py
git add tests/unit/test_keyword_mutate_builder.py
git commit -m "test(mcp): cobertura capture-client dos builders update_keyword_*" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: Testes dos builders de `negatives.py` (`add_negative_keywords`, `remove_negative_keywords`)

**Files:**
- Test: `tests/unit/test_negative_keyword_mutate_builder.py` (criar)
- Under test: `src/google_ads/mutates/negatives.py` (`build_add_negative_keywords:15`, `build_remove_negative_keywords:43`)

**Nota:** `add_negatives_from_search_terms` (mesmo módulo) já tem `test_add_negatives_builder.py` — não duplicar.

**Interfaces:**
- `add_negative_keywords`: cria `campaign_criterion_operation.create` com **`negative = True`** (classe A4 — o ponto crítico) + `keyword.text` + `keyword.match_type`.
- `remove_negative_keywords`: seta **`campaign_criterion_operation.remove`** = string path composto (classe A5).

- [ ] **Step 1: Escrever o arquivo de teste**

```python
"""Builder tests for negatives.py add/remove (Onda 2 — fecha F50/F51 + A4/A5).

A4: add_negative_keywords DEVE setar negative=True (um False silencioso
adicionaria keywords POSITIVAS — gasto invertido). A5: remove usa o campo
`remove` = resource path string (não um sub-message create).
"""

from src.google_ads.mutates.negatives import (
    build_add_negative_keywords,
    build_remove_negative_keywords,
)
from tests.unit.fixtures.proto_capture import make_capture_client


def test_add_negative_keywords_sets_negative_true_and_keyword() -> None:
    client = make_capture_client()
    ops = build_add_negative_keywords(
        client,
        "1234567890",
        {"campaign_id": "111", "keywords": [{"text": "comprar barato", "match_type": "PHRASE"}]},
    )
    assert len(ops) == 1
    base = "campaign_criterion_operation.create"
    assert ops[0].field(f"{base}.campaign") == "customers/1234567890/campaigns/111"
    # A4: negative DEVE ser True
    assert ops[0].field(f"{base}.negative") is True
    assert ops[0].field(f"{base}.keyword.text") == "comprar barato"
    # KeywordMatchTypeEnum é _BareEnumDict → key
    assert ops[0].field(f"{base}.keyword.match_type") == "PHRASE"


def test_remove_negative_keywords_sets_remove_path() -> None:
    client = make_capture_client()
    ops = build_remove_negative_keywords(
        client, "1234567890", {"campaign_id": "111", "criterion_ids": ["222", "333"]}
    )
    assert len(ops) == 2
    # A5: remove = string path composto (campanha~criterion)
    assert (
        ops[0].field("campaign_criterion_operation.remove")
        == "customers/1234567890/campaignCriteria/111~222"
    )
    assert (
        ops[1].field("campaign_criterion_operation.remove")
        == "customers/1234567890/campaignCriteria/111~333"
    )
```

- [ ] **Step 2: Rodar — devem PASSAR**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_negative_keyword_mutate_builder.py -v`
Expected: PASS (2 passed).

- [ ] **Step 3: Verificação + commit**

```bash
.venv/Scripts/python.exe scripts/check_pre_push.py
git add tests/unit/test_negative_keyword_mutate_builder.py
git commit -m "test(mcp): cobertura capture-client dos builders add/remove_negative_keywords (A4/A5)" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: Guard estrutural — todo `register_builder` precisa de um `test_*_builder.py`

**Files:**
- Modify: `tests/unit/test_tools_schemas.py` (adicionar 1 função de teste no fim do arquivo)

**Interfaces:**
- Consome: `src.google_ads.mutates._common._BUILDERS` (dict `{operation_type: fn}`) e `import_all_builders`. O guard procura `fn.__name__` (ex `build_update_campaign_status`) OU o `operation_type` no conteúdo concatenado dos `test_*_builder.py`. Após Tasks 1-5, os 23 builders têm cobertura → passa.

- [ ] **Step 1: Adicionar o guard ao fim de `tests/unit/test_tools_schemas.py`**

```python
def test_every_mutate_builder_has_a_builder_test():
    """Todo @register_builder DEVE ter um test_*_builder.py que importa/referencia
    sua função. Anti-reincidência F50/F51 (Onda 2): os 10 builders update_*/negative
    shiparam sem teste de execução — um campo proto / FieldMask / oneof errado passava
    a suíte e só falhava quando um gestor confirmava a mutação em produção.

    Complementa test_builder_tests_use_capture_client_not_magicmock (que garante a
    QUALIDADE do teste) com a EXISTÊNCIA do teste.
    """
    import pathlib

    from src.google_ads.mutates._common import _BUILDERS, import_all_builders

    import_all_builders()

    unit_dir = pathlib.Path(__file__).resolve().parent
    all_content = "\n".join(
        p.read_text(encoding="utf-8") for p in unit_dir.glob("test_*_builder.py")
    )

    missing = sorted(
        op
        for op, fn in _BUILDERS.items()
        if fn.__name__ not in all_content and op not in all_content
    )

    assert not missing, (
        "Builders de mutate sem test_*_builder.py (classe F50/F51 — código de mutação "
        "sem teste de execução):\n" + "\n".join(f"  {op}" for op in missing)
    )
```

- [ ] **Step 2: Rodar o guard — deve PASSAR (os 23 builders agora cobertos)**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_tools_schemas.py::test_every_mutate_builder_has_a_builder_test -v`
Expected: PASS. Se listar builders faltando, é porque (a) uma das Tasks 1-5 não rodou, ou (b) um teste existente não referencia `fn.__name__` nem o `operation_type` — nesse caso adicione o `import`/referência no teste existente correspondente (NÃO relaxe o guard).

- [ ] **Step 3: Rodar a suíte de guards de schema inteira (garantir que nada regrediu)**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_tools_schemas.py -v`
Expected: PASS (todos, incluindo o guard novo + `test_builder_tests_use_capture_client_not_magicmock`).

- [ ] **Step 4: Verificação + commit**

```bash
.venv/Scripts/python.exe scripts/check_pre_push.py
git add tests/unit/test_tools_schemas.py
git commit -m "test(mcp): guard estrutural — todo register_builder exige um builder test (F50/F51)" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review (do autor do plano)

**Cobertura da spec §4 (Onda 2):**
- 10 builders sem teste → Tasks 1-5 (campaigns 3, ad_groups 2, ads 1, keywords 2, negatives 2 = 10) ✅
- Guard estrutural (1 teste por register_builder) → Task 6 ✅
- Asserção presença + ausência (F51) → bidding oneof (Task 1), clear-override (Tasks 2/4), negative=True (Task 5) ✅

**Escopo confirmado:** os 13 outros builders já têm `test_*_builder.py` (grep verificado) → o guard da Task 6 passa sem trabalho extra, sem escopo-surpresa.

**Type/naming consistency:** todos os arquivos terminam em `_builder.py` (casam os 2 guards). Nenhum importa `MagicMock` (usam `dict` pro override de enum) → passam `test_builder_tests_use_capture_client_not_magicmock`. FieldMask via `copy_from.call_args_list[N].args[1].paths` consistente em todas as tasks.

**Risco residual:** se um teste falhar ao escrever, achou um bug real num builder de mutate que está VIVO em produção — esse é o valor da onda. O implementer reporta DONE_WITH_CONCERNS; o controller decide se vira um fix antes do merge.
