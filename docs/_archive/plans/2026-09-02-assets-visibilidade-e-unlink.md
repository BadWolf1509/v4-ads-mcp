# Assets: visibilidade nas 3 camadas + unlink — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dar ao gestor uma leitura única dos vínculos de asset nas três camadas (conta, campanha, grupo) com o veredito de serviço do Google, e o inverso do `create_and_link_assets` para desvincular.

**Architecture:** Duas tools. `get_assets` roda três queries GAQL em paralelo (`customer_asset`, `campaign_asset`, `ad_group_asset`), normaliza cada linha com um campo `level` e agrega num inventário que também marca assets órfãos. `remove_asset_link` segue o padrão de mutate always-CONFIRM já usado pelo `remove_audience`: preview + token + `apply_change`, com builder de proto registrado em `mutates/assets.py`.

**Tech Stack:** Python 3.13 · `google-ads>=27.0.0` (API v24) · pytest · o registry de tools do repo (`register_tool`) e o de builders de mutate (`register_builder`).

**Spec:** [`docs/superpowers/specs/2026-09-02-ad-schedule-e-assets-design.md`](../specs/2026-09-02-ad-schedule-e-assets-design.md) — leia as §2.1, §5, §6 e §7 antes de começar. Este plano cobre **só a metade de assets**; `get_ad_schedule`/`update_ad_schedule` têm plano próprio.

## Global Constraints

Copiadas da §2.1 da spec. **Valem para toda task deste plano**, mesmo quando o texto da task não repetir:

- **Envelope de mutate não se monta à mão.** Use `preview_envelope` / `applied_envelope` / `error_envelope` de `src/mcp/tools/_mutate_common.py`. Erro canônico é `error_message` + `operation`. TTL vem de `DEFAULT_TTL_MINUTES`, **nunca** literal.
- **Blast radius é computado:** `classify(operation=..., params=...)` de `src/governance/blast_radius.py`. Não escreva `if` decidindo CONFIRM à mão.
- **SDK só dentro de `run_blocking`** (F109). Nas tools deste plano isso já vem de graça: `run_report` e `run_mutation` cuidam disso — **não** construa client próprio.
- **Audit sempre em mutate.** O caminho `create_pending` → `apply_change` → `run_mutation` já grava; não desligue.
- **`bucket="defer"`** nas duas tools novas, e a description começa com `[DEFER]`.
- **`limit` + `truncated`** em toda leitura.
- **Mutate em lote usa `__partial_failure__: True`** no payload, como o `remove_audience`.
- **Não use `MagicMock` em teste de builder de proto** — use `make_capture_client()` de `tests/unit/fixtures/proto_capture.py` (F16/F42/F44).
- **Verificação antes de todo commit:** `python scripts/check_pre_push.py` rodado **mudo**, lendo o exit code:
  ```bash
  python scripts/check_pre_push.py > /dev/null 2>&1; echo $?
  ```
  **Nunca** `check_pre_push.py | tail && git commit` — o exit code de um pipeline é o do último comando, então o `&&` não é gate. Isso já causou um commit com gate vermelho em 02/09.

---

### Task 1: Queries e parsers das três camadas de vínculo

**Files:**
- Create: `src/google_ads/queries/assets.py`
- Test: `tests/unit/test_assets_queries.py`

**Interfaces:**
- Consumes: nada (primeira task).
- Produces:
  - `build_customer_asset_query(*, field_type: str | None) -> str`
  - `build_campaign_asset_query(*, field_type: str | None, campaign_ids: list[str] | None) -> str`
  - `build_ad_group_asset_query(*, field_type: str | None) -> str`
  - `parse_customer_asset_row(row: Any) -> dict[str, Any]`
  - `parse_campaign_asset_row(row: Any) -> dict[str, Any]`
  - `parse_ad_group_asset_row(row: Any) -> dict[str, Any]`
  - Todo dict de parser tem as chaves: `level`, `resource_name`, `asset_id`, `asset_name`, `field_type`, `status`, `primary_status`, `primary_status_reasons`, `campaign_id`, `campaign_name`, `ad_group_id`, `ad_group_name`.

- [ ] **Step 1: Escreva os testes que falham**

```python
# tests/unit/test_assets_queries.py
"""F134/F135: a camada `customer_asset` era invisivel. Estas queries sao a base
da leitura das TRES camadas.

`primary_status` e `primary_status_reasons` entram desde a v0: sao o veredito do
Google sobre servir, e substituem o `effective`/`shadowed_by` que a probe da
secao 5.1 da spec eliminou (o conceito nao existe na API).
"""

from __future__ import annotations

from types import SimpleNamespace

from src.google_ads.queries.assets import (
    build_ad_group_asset_query,
    build_campaign_asset_query,
    build_customer_asset_query,
    parse_campaign_asset_row,
    parse_customer_asset_row,
)


def test_query_de_conta_pede_primary_status() -> None:
    q = build_customer_asset_query(field_type=None)
    assert "FROM customer_asset" in q
    assert "customer_asset.primary_status" in q
    assert "customer_asset.primary_status_reasons" in q


def test_query_de_conta_nao_filtra_status() -> None:
    """Spec section 7: filtrar por status esconde o REMOVED, que e a prova positiva."""
    q = build_customer_asset_query(field_type=None)
    assert "status = 'ENABLED'" not in q
    assert "status='ENABLED'" not in q


def test_filtro_de_field_type_e_opcional_e_escapado() -> None:
    sem = build_customer_asset_query(field_type=None)
    com = build_customer_asset_query(field_type="CALLOUT")
    assert "field_type" not in sem.split("FROM")[1]
    assert "customer_asset.field_type = 'CALLOUT'" in com


def test_query_de_campanha_filtra_por_campaign_ids() -> None:
    q = build_campaign_asset_query(field_type=None, campaign_ids=["111", "222"])
    assert "campaign.id IN (111,222)" in q


def test_query_de_ad_group_existe_e_aponta_o_recurso_certo() -> None:
    """A terceira camada e a que ninguem lembra — por isso tem teste proprio."""
    q = build_ad_group_asset_query(field_type=None)
    assert "FROM ad_group_asset" in q
    assert "ad_group_asset.primary_status" in q


def test_parser_de_conta_marca_o_level_e_nao_inventa_campanha() -> None:
    row = SimpleNamespace(
        customer_asset=SimpleNamespace(
            resource_name="customers/1/customerAssets/9~CALLOUT",
            field_type=SimpleNamespace(name="CALLOUT"),
            status=SimpleNamespace(name="ENABLED"),
            primary_status=SimpleNamespace(name="ELIGIBLE"),
            primary_status_reasons=[],
        ),
        asset=SimpleNamespace(id=9, name="Atendimento Eficaz"),
    )
    d = parse_customer_asset_row(row)
    assert d["level"] == "CUSTOMER"
    assert d["asset_id"] == "9"
    assert d["primary_status"] == "ELIGIBLE"
    assert d["campaign_id"] is None
    assert d["ad_group_id"] is None
    assert d["resource_name"] == "customers/1/customerAssets/9~CALLOUT"


def test_parser_traduz_enum_de_reason_para_nome() -> None:
    """Licao UX-2: `.name` do enum, nunca str(enum) — proto-plus tem repr feio."""
    row = SimpleNamespace(
        customer_asset=SimpleNamespace(
            resource_name="customers/1/customerAssets/9~CALLOUT",
            field_type=SimpleNamespace(name="CALLOUT"),
            status=SimpleNamespace(name="REMOVED"),
            primary_status=SimpleNamespace(name="REMOVED"),
            primary_status_reasons=[SimpleNamespace(name="ASSET_LINK_REMOVED")],
        ),
        asset=SimpleNamespace(id=9, name=""),
    )
    assert parse_customer_asset_row(row)["primary_status_reasons"] == ["ASSET_LINK_REMOVED"]


def test_parser_de_campanha_preenche_campanha() -> None:
    row = SimpleNamespace(
        campaign_asset=SimpleNamespace(
            resource_name="customers/1/campaignAssets/7~9~CALLOUT",
            field_type=SimpleNamespace(name="CALLOUT"),
            status=SimpleNamespace(name="ENABLED"),
            primary_status=SimpleNamespace(name="ELIGIBLE"),
            primary_status_reasons=[],
        ),
        asset=SimpleNamespace(id=9, name="X"),
        campaign=SimpleNamespace(id=7, name="JPA"),
    )
    d = parse_campaign_asset_row(row)
    assert d["level"] == "CAMPAIGN"
    assert d["campaign_id"] == "7"
    assert d["campaign_name"] == "JPA"
    assert d["ad_group_id"] is None
```

- [ ] **Step 2: Rode os testes e confirme que falham**

Run: `python -m pytest tests/unit/test_assets_queries.py -q`
Expected: FAIL com `ModuleNotFoundError: No module named 'src.google_ads.queries.assets'`

- [ ] **Step 3: Implemente o módulo**

```python
# src/google_ads/queries/assets.py
"""GAQL das TRES camadas de vinculo de asset (F134/F135).

Precedencia NAO e calculada: a probe de 2026-09-02 (spec secao 5.1) mostrou que o
conceito nao existe na API — `AssetLinkPrimaryStatusReason` tem seis valores e
nenhum e de precedencia, e dois vinculos coexistentes do mesmo asset voltam ambos
`ELIGIBLE`. O que se devolve e o veredito do proprio Google: `primary_status`.

Status NAO e filtrado: linha `REMOVED` e a unica prova positiva de remocao
(spec secao 7).
"""

from typing import Any

from src.google_ads.queries._gaql import gaql_escape

_CAMPOS_COMUNS = "field_type, status, primary_status, primary_status_reasons, resource_name"


def _clausula_field_type(recurso: str, field_type: str | None) -> str:
    if field_type is None:
        return ""
    return f" WHERE {recurso}.field_type = '{gaql_escape(field_type)}'"


def build_customer_asset_query(*, field_type: str | None) -> str:
    campos = ", ".join(f"customer_asset.{c}" for c in _CAMPOS_COMUNS.split(", "))
    return f"SELECT {campos}, asset.id, asset.name FROM customer_asset" + _clausula_field_type(
        "customer_asset", field_type
    )


def build_campaign_asset_query(
    *, field_type: str | None, campaign_ids: list[str] | None
) -> str:
    campos = ", ".join(f"campaign_asset.{c}" for c in _CAMPOS_COMUNS.split(", "))
    q = (
        f"SELECT {campos}, asset.id, asset.name, campaign.id, campaign.name "
        "FROM campaign_asset"
    )
    filtros = []
    if field_type is not None:
        filtros.append(f"campaign_asset.field_type = '{gaql_escape(field_type)}'")
    if campaign_ids:
        # ids sao validados como digit-string no schema da tool
        filtros.append(f"campaign.id IN ({','.join(campaign_ids)})")
    return q + (" WHERE " + " AND ".join(filtros) if filtros else "")


def build_ad_group_asset_query(*, field_type: str | None) -> str:
    campos = ", ".join(f"ad_group_asset.{c}" for c in _CAMPOS_COMUNS.split(", "))
    return (
        f"SELECT {campos}, asset.id, asset.name, ad_group.id, ad_group.name, "
        "campaign.id, campaign.name FROM ad_group_asset"
    ) + _clausula_field_type("ad_group_asset", field_type)


def _nome(enum_ou_none: Any) -> str:
    return enum_ou_none.name if hasattr(enum_ou_none, "name") else str(enum_ou_none)


def _base(link: Any, asset: Any, level: str) -> dict[str, Any]:
    return {
        "level": level,
        "resource_name": str(link.resource_name),
        "asset_id": str(asset.id),
        "asset_name": str(asset.name),
        "field_type": _nome(link.field_type),
        "status": _nome(link.status),
        "primary_status": _nome(link.primary_status),
        "primary_status_reasons": [_nome(r) for r in link.primary_status_reasons],
        "campaign_id": None,
        "campaign_name": None,
        "ad_group_id": None,
        "ad_group_name": None,
    }


def parse_customer_asset_row(row: Any) -> dict[str, Any]:
    return _base(row.customer_asset, row.asset, "CUSTOMER")


def parse_campaign_asset_row(row: Any) -> dict[str, Any]:
    d = _base(row.campaign_asset, row.asset, "CAMPAIGN")
    d["campaign_id"] = str(row.campaign.id)
    d["campaign_name"] = str(row.campaign.name)
    return d


def parse_ad_group_asset_row(row: Any) -> dict[str, Any]:
    d = _base(row.ad_group_asset, row.asset, "AD_GROUP")
    d["campaign_id"] = str(row.campaign.id)
    d["campaign_name"] = str(row.campaign.name)
    d["ad_group_id"] = str(row.ad_group.id)
    d["ad_group_name"] = str(row.ad_group.name)
    return d
```

- [ ] **Step 4: Rode os testes e confirme que passam**

Run: `python -m pytest tests/unit/test_assets_queries.py -q`
Expected: PASS, 8 testes.

- [ ] **Step 5: Valide as três queries contra a API antes de seguir**

**Não pule.** A spec exige probe empírica em vez de analogia. Use a tool `validate_gaql` contra a conta `7862230676` com o output de cada builder. As três devem voltar `{"valid": true}`. Se alguma falhar, o campo está errado — corrija o builder, não o teste.

- [ ] **Step 6: Commit**

```bash
python scripts/check_pre_push.py > /dev/null 2>&1; echo $?
# so siga se imprimir 0
git add src/google_ads/queries/assets.py tests/unit/test_assets_queries.py
git commit -m "feat(mcp): queries e parsers das tres camadas de vinculo de asset"
```

---

### Task 2: Inventário puro — junta as camadas e marca órfãos

**Files:**
- Create: `src/google_ads/asset_inventory.py`
- Test: `tests/unit/test_asset_inventory.py`

**Interfaces:**
- Consumes: os dicts produzidos pelos parsers da Task 1 (chaves listadas lá).
- Produces:
  - `build_inventory(*, rows: list[dict[str, Any]], limit: int) -> tuple[list[dict[str, Any]], dict[str, Any]]`
  - Retorna `(links_truncados, summary)`. `summary` tem: `total_links`, `truncated`, `by_level` (dict), `by_primary_status` (dict), `assets_sem_vinculo_ativo` (list de `asset_id`).

- [ ] **Step 1: Escreva os testes que falham**

```python
# tests/unit/test_asset_inventory.py
"""Agregacao pura do inventario de assets. Sem SDK, sem I/O."""

from __future__ import annotations

from typing import Any

from src.google_ads.asset_inventory import build_inventory


def _link(**kw: Any) -> dict[str, Any]:
    base = {
        "level": "CAMPAIGN",
        "resource_name": "customers/1/campaignAssets/7~9~CALLOUT",
        "asset_id": "9",
        "asset_name": "X",
        "field_type": "CALLOUT",
        "status": "ENABLED",
        "primary_status": "ELIGIBLE",
        "primary_status_reasons": [],
        "campaign_id": "7",
        "campaign_name": "JPA",
        "ad_group_id": None,
        "ad_group_name": None,
    }
    base.update(kw)
    return base


def test_ordena_por_asset_e_depois_por_camada() -> None:
    """Agrupar visualmente por asset e o que faz a camada dormente saltar."""
    rows = [
        _link(asset_id="2", level="CAMPAIGN"),
        _link(asset_id="1", level="CAMPAIGN"),
        _link(asset_id="1", level="CUSTOMER", campaign_id=None),
    ]
    links, _ = build_inventory(rows=rows, limit=100)
    assert [(x["asset_id"], x["level"]) for x in links] == [
        ("1", "CUSTOMER"),
        ("1", "CAMPAIGN"),
        ("2", "CAMPAIGN"),
    ]


def test_summary_conta_por_camada() -> None:
    rows = [
        _link(asset_id="1", level="CUSTOMER", campaign_id=None),
        _link(asset_id="1", level="CAMPAIGN"),
        _link(asset_id="1", level="AD_GROUP", ad_group_id="5"),
    ]
    _, summary = build_inventory(rows=rows, limit=100)
    assert summary["by_level"] == {"CUSTOMER": 1, "CAMPAIGN": 1, "AD_GROUP": 1}
    assert summary["total_links"] == 3


def test_summary_conta_por_primary_status() -> None:
    rows = [
        _link(asset_id="1", primary_status="ELIGIBLE"),
        _link(asset_id="2", primary_status="REMOVED"),
        _link(asset_id="3", primary_status="REMOVED"),
    ]
    _, summary = build_inventory(rows=rows, limit=100)
    assert summary["by_primary_status"] == {"ELIGIBLE": 1, "REMOVED": 2}


def test_asset_so_com_vinculo_removido_conta_como_orfao() -> None:
    """Inventario do lixo sem precisar de tool destrutiva."""
    rows = [
        _link(asset_id="1", status="REMOVED", primary_status="REMOVED"),
        _link(asset_id="2", status="ENABLED", primary_status="ELIGIBLE"),
    ]
    _, summary = build_inventory(rows=rows, limit=100)
    assert summary["assets_sem_vinculo_ativo"] == ["1"]


def test_asset_com_um_vinculo_vivo_em_qualquer_camada_nao_e_orfao() -> None:
    """O vinculo vivo pode estar na camada que ninguem olhou — era o bug de 02/09."""
    rows = [
        _link(asset_id="1", level="CAMPAIGN", status="REMOVED", primary_status="REMOVED"),
        _link(
            asset_id="1",
            level="CUSTOMER",
            campaign_id=None,
            status="ENABLED",
            primary_status="ELIGIBLE",
        ),
    ]
    _, summary = build_inventory(rows=rows, limit=100)
    assert summary["assets_sem_vinculo_ativo"] == []


def test_limit_trunca_e_sinaliza() -> None:
    rows = [_link(asset_id=str(i)) for i in range(5)]
    links, summary = build_inventory(rows=rows, limit=2)
    assert len(links) == 2
    assert summary["truncated"] is True
    assert summary["total_links"] == 5, "o summary conta o total bruto, nao o truncado"
```

- [ ] **Step 2: Rode os testes e confirme que falham**

Run: `python -m pytest tests/unit/test_asset_inventory.py -q`
Expected: FAIL com `ModuleNotFoundError: No module named 'src.google_ads.asset_inventory'`

- [ ] **Step 3: Implemente o módulo**

```python
# src/google_ads/asset_inventory.py
"""Agregacao pura do inventario de vinculos de asset — zero SDK, zero I/O.

NAO calcula precedencia. A probe de 2026-09-02 (spec secao 5.1) mostrou que o
conceito nao existe na API. O que se reporta e o `primary_status` do Google.

"Orfao" aqui significa: nenhum vinculo com status ENABLED em NENHUMA das tres
camadas. A checagem tem de olhar as tres — foi exatamente olhar so uma que
produziu o erro de 02/09.
"""

from collections import Counter
from typing import Any

_ORDEM_CAMADA = {"CUSTOMER": 0, "CAMPAIGN": 1, "AD_GROUP": 2}


def build_inventory(
    *, rows: list[dict[str, Any]], limit: int
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Ordena, conta e marca orfaos. Devolve (links_truncados, summary)."""
    ordenados = sorted(
        rows, key=lambda r: (r["asset_id"], _ORDEM_CAMADA.get(r["level"], 9))
    )

    by_level: Counter[str] = Counter()
    by_primary: Counter[str] = Counter()
    tem_vinculo_vivo: dict[str, bool] = {}
    for r in ordenados:
        by_level[r["level"]] += 1
        by_primary[r["primary_status"]] += 1
        vivo = r["status"] == "ENABLED"
        tem_vinculo_vivo[r["asset_id"]] = tem_vinculo_vivo.get(r["asset_id"], False) or vivo

    total = len(ordenados)
    summary = {
        "total_links": total,
        "truncated": total > limit,
        "by_level": dict(by_level),
        "by_primary_status": dict(by_primary),
        "assets_sem_vinculo_ativo": sorted(a for a, vivo in tem_vinculo_vivo.items() if not vivo),
    }
    return ordenados[:limit], summary
```

- [ ] **Step 4: Rode os testes e confirme que passam**

Run: `python -m pytest tests/unit/test_asset_inventory.py -q`
Expected: PASS, 6 testes.

- [ ] **Step 5: Commit**

```bash
python scripts/check_pre_push.py > /dev/null 2>&1; echo $?
git add src/google_ads/asset_inventory.py tests/unit/test_asset_inventory.py
git commit -m "feat(mcp): inventario puro de assets com marcacao de orfaos"
```

---

### Task 3: A tool `get_assets`

**Files:**
- Create: `src/mcp/tools/get_assets.py`
- Test: `tests/unit/test_get_assets.py`

> **Não há lista de imports para atualizar.** `import_all_tools()` descobre os módulos por `pkgutil.iter_modules`, ignorando os que começam com `_`. Basta o arquivo existir no pacote com o decorator `@register_tool`. (O repo já teve o problema oposto: nos sprints 3b.12-3b.14 a lista era manual e tools shipparam mortas em produção passando nos testes unitários por efeito colateral de import.)

**Interfaces:**
- Consumes: Task 1 (`build_*_query`, `parse_*_row`) e Task 2 (`build_inventory`).
- Produces: tool MCP `get_assets`. A resposta tem `customer_id`, `links` (list dos dicts da Task 1) e `summary` (dict da Task 2).

- [ ] **Step 1: Escreva os testes que falham**

```python
# tests/unit/test_get_assets.py
"""F134: a camada `customer_asset` era invisivel por tool curada.

O teste que importa e `test_consulta_as_TRES_camadas`: uma implementacao que
consultasse so `campaign_asset` passaria em todos os outros e reproduziria
exatamente o erro de 02/09 (checklist previa 4 vinculos, eram 6).
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from src.mcp.tools._registry import get_tool
from src.mcp.tools.get_assets import get_assets


@pytest.fixture(autouse=True)
def _ctx():
    from src.mcp.context import McpRequestContext, clear_current, set_current

    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    yield
    clear_current()


def _fake_run_report(por_recurso: dict[str, list[dict[str, Any]]]):
    queries: list[str] = []

    async def _run(**kwargs: Any) -> list[dict[str, Any]]:
        q = kwargs["query"]
        queries.append(q)
        for recurso, linhas in por_recurso.items():
            if f"FROM {recurso}" in q:
                return linhas
        return []

    return _run, queries


def _link(**kw: Any) -> dict[str, Any]:
    base = {
        "level": "CAMPAIGN",
        "resource_name": "customers/1/campaignAssets/7~9~CALLOUT",
        "asset_id": "9",
        "asset_name": "X",
        "field_type": "CALLOUT",
        "status": "ENABLED",
        "primary_status": "ELIGIBLE",
        "primary_status_reasons": [],
        "campaign_id": "7",
        "campaign_name": "JPA",
        "ad_group_id": None,
        "ad_group_name": None,
    }
    base.update(kw)
    return base


@pytest.mark.asyncio
async def test_consulta_as_TRES_camadas(monkeypatch) -> None:
    """O guard da falha que esta tool existe para impedir."""
    run, queries = _fake_run_report({})
    monkeypatch.setattr("src.mcp.tools.get_assets.run_report", run)
    await get_assets({"customer_id": "1234567890"})
    recursos = {r for r in ("customer_asset", "campaign_asset", "ad_group_asset") if any(
        f"FROM {r}" in q for q in queries
    )}
    assert recursos == {"customer_asset", "campaign_asset", "ad_group_asset"}


@pytest.mark.asyncio
async def test_vinculo_de_conta_aparece_na_saida(monkeypatch) -> None:
    run, _ = _fake_run_report(
        {"customer_asset": [_link(level="CUSTOMER", campaign_id=None, campaign_name=None)]}
    )
    monkeypatch.setattr("src.mcp.tools.get_assets.run_report", run)
    r = await get_assets({"customer_id": "1234567890"})
    assert [x["level"] for x in r["links"]] == ["CUSTOMER"]


@pytest.mark.asyncio
async def test_linha_removida_aparece_sem_filtro_explicito(monkeypatch) -> None:
    """Spec secao 7: `REMOVED` e a prova positiva; escondê-la mata a confirmacao."""
    run, _ = _fake_run_report(
        {"campaign_asset": [_link(status="REMOVED", primary_status="REMOVED")]}
    )
    monkeypatch.setattr("src.mcp.tools.get_assets.run_report", run)
    r = await get_assets({"customer_id": "1234567890"})
    assert r["links"][0]["status"] == "REMOVED"


@pytest.mark.asyncio
async def test_saida_traz_resource_name(monkeypatch) -> None:
    """Acoplamento com o remove_asset_link (classe F81): sem isto o gestor nao
    consegue encadear as duas tools sem cair no run_gaql."""
    run, _ = _fake_run_report({"campaign_asset": [_link()]})
    monkeypatch.setattr("src.mcp.tools.get_assets.run_report", run)
    r = await get_assets({"customer_id": "1234567890"})
    assert r["links"][0]["resource_name"].startswith("customers/")


def test_tool_registrada_como_defer_com_prefixo() -> None:
    t = get_tool("get_assets")
    assert t is not None
    assert t.bucket == "defer"
    assert t.description.startswith("[DEFER]")


def test_schema_tem_limit_com_teto() -> None:
    """Classe F98: ausencia de teto estoura o cap de token em conta grande."""
    t = get_tool("get_assets")
    assert t is not None
    limite = t.input_schema["properties"]["limit"]
    assert limite["default"] == 200
    assert limite["maximum"] == 1000
```

- [ ] **Step 2: Rode os testes e confirme que falham**

Run: `python -m pytest tests/unit/test_get_assets.py -q`
Expected: FAIL com `ModuleNotFoundError: No module named 'src.mcp.tools.get_assets'`

- [ ] **Step 3: Implemente a tool**

```python
# src/mcp/tools/get_assets.py
# bucket: defer
"""Tool: get_assets — vinculos de asset nas TRES camadas, num lugar so.

F134: a limpeza de 02/09 previa 4 vinculos em `campaign_asset` e eram 6 — os
mesmos assets tambem existiam em `customer_asset`, e so apareceram porque o
gestor foi atras por desconfianca no `run_gaql`.

NAO calcula precedencia: a probe da spec secao 5.1 mostrou que o conceito nao
existe na API. Devolve o `primary_status` do Google, que e autoritativo e cobre
mais (reprovacao, revisao pendente, LIMITED).
"""

import asyncio
from typing import Any

from src.google_ads.asset_inventory import build_inventory
from src.google_ads.queries.assets import (
    build_ad_group_asset_query,
    build_campaign_asset_query,
    build_customer_asset_query,
    parse_ad_group_asset_row,
    parse_campaign_asset_row,
    parse_customer_asset_row,
)
from src.google_ads.reports import run_report
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "field_type": {
            "type": "string",
            "description": (
                "Opcional. Filtra por tipo (CALLOUT, SITELINK, STRUCTURED_SNIPPET, "
                "CALL, PROMOTION, BUSINESS_LOGO...). Default: TODOS os tipos."
            ),
        },
        "campaign_ids": {
            "type": "array",
            "items": {"type": "string", "pattern": "^[0-9]+$"},
            "minItems": 1,
            "maxItems": 50,
            "description": "Opcional. Restringe a camada de campanha a estes ids.",
        },
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": 1000,
            "default": 200,
            "description": "Máximo de vínculos retornados. truncated:true se exceder.",
        },
    },
    "required": ["customer_id"],
    "additionalProperties": False,
}

_DESCRIPTION = (
    "[DEFER] Lista vínculos de asset nas TRÊS camadas — customer_asset, "
    "campaign_asset e ad_group_asset — numa resposta só, cada linha com `level` e "
    "`resource_name` (o mesmo que `remove_asset_link` recebe). Traz "
    "`primary_status` + `primary_status_reasons`, que é o veredito do Google "
    "sobre servir (ELIGIBLE|PAUSED|REMOVED|PENDING|LIMITED|NOT_ELIGIBLE), e "
    "`summary.assets_sem_vinculo_ativo` com os órfãos. **NÃO filtra status por "
    "default**: linha REMOVED é a única prova positiva de que uma remoção "
    "funcionou — contagem não distingue, porque o vínculo removido continua na "
    "tabela. ATENÇÃO: não existe campo de precedência entre camadas na API do "
    "Google (o enum de razões não tem nenhum valor de ofuscamento), então esta "
    "tool não afirma qual vínculo 'vence' — ela mostra os três e o veredito de "
    "cada um. Filtros: field_type opcional (default todos), campaign_ids "
    "opcional, limit (default 200, teto 1000)."
)


@register_tool(
    name="get_assets",
    description=_DESCRIPTION,
    input_schema=_SCHEMA,
    bucket="defer",
)
async def get_assets(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    field_type = args.get("field_type")
    campaign_ids = args.get("campaign_ids")
    limit = args.get("limit", 200)

    async def _consulta(query: str, parser: Any, fase: str) -> list[dict[str, Any]]:
        return await run_report(
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=customer_id,
            query=query,
            row_formatter=parser,
            operation_name="get_assets",
            audit_this_call=False,
            params_summary={"phase": fase, "field_type": field_type},
        )

    # As TRES camadas em paralelo. Consultar so uma e o bug de 02/09.
    conta, campanha, grupo = await asyncio.gather(
        _consulta(
            build_customer_asset_query(field_type=field_type),
            parse_customer_asset_row,
            "customer_asset",
        ),
        _consulta(
            build_campaign_asset_query(field_type=field_type, campaign_ids=campaign_ids),
            parse_campaign_asset_row,
            "campaign_asset",
        ),
        _consulta(
            build_ad_group_asset_query(field_type=field_type),
            parse_ad_group_asset_row,
            "ad_group_asset",
        ),
    )

    links, summary = build_inventory(rows=[*conta, *campanha, *grupo], limit=limit)
    return {"customer_id": customer_id, "links": links, "summary": summary}
```

- [ ] **Step 4: Rode os testes e confirme que passam**

Run: `python -m pytest tests/unit/test_get_assets.py -q`
Expected: PASS, 6 testes.

- [ ] **Step 5: Sabote o guard das três camadas e confirme que ele pega**

**Obrigatório.** Comente a chamada de `customer_asset` no `asyncio.gather` (devolvendo lista vazia no lugar) e rode de novo. `test_consulta_as_TRES_camadas` **tem** de falhar. Restaure em seguida — copie o arquivo antes (`cp src/mcp/tools/get_assets.py "$TMP/get_assets.bak"`), **nunca** `git checkout`.

- [ ] **Step 6: Commit**

```bash
python scripts/check_pre_push.py > /dev/null 2>&1; echo $?
git add src/mcp/tools/get_assets.py tests/unit/test_get_assets.py
git commit -m "feat(mcp): get_assets le as tres camadas de vinculo com primary_status"
```

---

### Task 4: Builder de proto do unlink

**Files:**
- Modify: `src/google_ads/mutates/assets.py` (adicionar builder novo; não mexa no `build_create_and_link_assets` existente)
- Test: `tests/unit/test_remove_asset_link_builder.py`

**Interfaces:**
- Consumes: nada das tasks anteriores.
- Produces: `build_remove_asset_link(client, customer_id, payload) -> list[Any]`, registrado com `@register_builder("remove_asset_link")`. `payload` tem a chave `links`: lista de `{"level": "CUSTOMER"|"CAMPAIGN"|"AD_GROUP", "resource_name": str}`.

- [ ] **Step 1: Escreva os testes que falham**

```python
# tests/unit/test_remove_asset_link_builder.py
"""Unlink de asset: remove o VINCULO, nunca a entidade Asset.

Asset orfao e inerte; remover a entidade e irreversivel e ela pode estar linkada
onde a varredura nao alcancou (spec secao 2).

Use `make_capture_client`, nunca MagicMock (F16/F42/F44): o MagicMock aceita
qualquer campo e esconde erro de nome de campo do proto.
"""

from __future__ import annotations

from src.google_ads.mutates.assets import build_remove_asset_link
from tests.unit.fixtures.proto_capture import make_capture_client


def _payload(*links: tuple[str, str]) -> dict:
    return {"links": [{"level": lv, "resource_name": rn} for lv, rn in links]}


def test_uma_operacao_por_vinculo() -> None:
    ops = build_remove_asset_link(
        make_capture_client(),
        "1234567890",
        _payload(
            ("CUSTOMER", "customers/1234567890/customerAssets/9~CALLOUT"),
            ("CAMPAIGN", "customers/1234567890/campaignAssets/7~9~CALLOUT"),
        ),
    )
    assert len(ops) == 2


def test_nivel_de_conta_usa_customer_asset_operation_remove() -> None:
    ops = build_remove_asset_link(
        make_capture_client(),
        "1234567890",
        _payload(("CUSTOMER", "customers/1234567890/customerAssets/9~CALLOUT")),
    )
    assert (
        ops[0].field("customer_asset_operation.remove")
        == "customers/1234567890/customerAssets/9~CALLOUT"
    )


def test_nivel_de_campanha_usa_campaign_asset_operation_remove() -> None:
    ops = build_remove_asset_link(
        make_capture_client(),
        "1234567890",
        _payload(("CAMPAIGN", "customers/1234567890/campaignAssets/7~9~CALLOUT")),
    )
    assert (
        ops[0].field("campaign_asset_operation.remove")
        == "customers/1234567890/campaignAssets/7~9~CALLOUT"
    )


def test_nivel_de_ad_group_usa_ad_group_asset_operation_remove() -> None:
    ops = build_remove_asset_link(
        make_capture_client(),
        "1234567890",
        _payload(("AD_GROUP", "customers/1234567890/adGroupAssets/5~9~CALLOUT")),
    )
    assert (
        ops[0].field("ad_group_asset_operation.remove")
        == "customers/1234567890/adGroupAssets/5~9~CALLOUT"
    )


def test_nunca_emite_operacao_sobre_a_entidade_asset() -> None:
    """A guarda da secao 2 da spec: so o vinculo sai, a entidade fica."""
    ops = build_remove_asset_link(
        make_capture_client(),
        "1234567890",
        _payload(("CAMPAIGN", "customers/1234567890/campaignAssets/7~9~CALLOUT")),
    )
    assert ops[0].has("asset_operation") is False
```

- [ ] **Step 2: Rode os testes e confirme que falham**

Run: `python -m pytest tests/unit/test_remove_asset_link_builder.py -q`
Expected: FAIL com `ImportError: cannot import name 'build_remove_asset_link'`

- [ ] **Step 3: Implemente o builder**

Acrescente ao fim de `src/google_ads/mutates/assets.py`:

```python
@register_builder("remove_asset_link")
def build_remove_asset_link(client: Any, customer_id: str, payload: dict[str, Any]) -> list[Any]:
    """Uma MutateOperation de `remove` por vinculo, no operation do nivel certo.

    Remove o VINCULO (`*_asset`), nunca a entidade `Asset` — asset orfao e inerte,
    e remover a entidade e irreversivel numa coisa que pode estar linkada onde a
    varredura nao alcancou (spec secao 2). Por isso nao ha branch para
    `asset_operation` aqui, e ha teste exigindo a ausencia dele.
    """
    campo_por_nivel = {
        "CUSTOMER": "customer_asset_operation",
        "CAMPAIGN": "campaign_asset_operation",
        "AD_GROUP": "ad_group_asset_operation",
    }
    ops: list[Any] = []
    for link in payload["links"]:
        op = client.get_type("MutateOperation")
        alvo = getattr(op, campo_por_nivel[link["level"]])
        alvo.remove = link["resource_name"]
        ops.append(op)
    return ops
```

Se o topo do arquivo ainda não importar `register_builder` e `Any`, acrescente — siga os imports que o `build_create_and_link_assets` já usa.

- [ ] **Step 4: Rode os testes e confirme que passam**

Run: `python -m pytest tests/unit/test_remove_asset_link_builder.py -q`
Expected: PASS, 5 testes.

- [ ] **Step 5: Commit**

```bash
python scripts/check_pre_push.py > /dev/null 2>&1; echo $?
git add src/google_ads/mutates/assets.py tests/unit/test_remove_asset_link_builder.py
git commit -m "feat(mcp): builder de proto para remover vinculo de asset"
```

---

### Task 5: A tool `remove_asset_link` e o acoplamento com `get_assets`

**Files:**
- Create: `src/mcp/tools/remove_asset_link.py`
- Modify: `src/governance/blast_radius.py` (branch explícito — ver Step 3b)
- Test: `tests/unit/test_remove_asset_link.py`

> Como na Task 3: **nada a registrar à mão**, a descoberta é por `pkgutil`.

**Interfaces:**
- Consumes: Task 4 (`build_remove_asset_link` via `operation_type="remove_asset_link"`), e o `resource_name` que a Task 3 devolve.
- Produces: tool MCP `remove_asset_link`. Devolve envelope de preview com `confirmation_token`; a aplicação acontece por `apply_change(token)`.

- [ ] **Step 1: Escreva os testes que falham**

```python
# tests/unit/test_remove_asset_link.py
"""`remove_asset_link` — always-CONFIRM, e o `resource_name` vem do `get_assets`.

O teste de acoplamento (classe F81) e o que impede as duas tools de estarem
certas sozinhas e erradas juntas.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

# Import de modulo no topo: e ele que dispara o @register_tool. Sem isto,
# `get_tool("remove_asset_link")` devolve None quando este arquivo roda sozinho.
from src.mcp.tools import remove_asset_link as mod
from src.mcp.tools._registry import get_tool


@pytest.fixture(autouse=True)
def _ctx():
    from src.mcp.context import McpRequestContext, clear_current, set_current

    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    yield
    clear_current()


def test_tool_registrada_como_defer() -> None:
    t = get_tool("remove_asset_link")
    assert t is not None
    assert t.bucket == "defer"


def test_schema_aceita_o_resource_name_que_o_get_assets_devolve() -> None:
    """Acoplamento F81: o formato de um lado tem de ser aceito pelo outro."""
    t = get_tool("remove_asset_link")
    assert t is not None
    item = t.input_schema["properties"]["links"]["items"]
    assert set(item["required"]) == {"level", "resource_name"}
    assert set(item["properties"]["level"]["enum"]) == {"CUSTOMER", "CAMPAIGN", "AD_GROUP"}
    # o mesmo shape que get_assets emite em cada linha de `links`
    exemplo = {"level": "CAMPAIGN", "resource_name": "customers/1/campaignAssets/7~9~CALLOUT"}
    assert set(exemplo) >= set(item["required"])


def test_description_avisa_que_nao_remove_a_entidade() -> None:
    t = get_tool("remove_asset_link")
    assert t is not None
    assert "não remove o asset" in t.description.lower() or "nao remove o asset" in (
        t.description.lower()
    )


@pytest.mark.asyncio
async def test_devolve_preview_com_token_e_nunca_aplica_direto(monkeypatch) -> None:
    """Always-CONFIRM: nao ha caminho AUTO nesta tool."""
    async def _create_pending(conn: Any, **kwargs: Any) -> str:
        return "tok-123"

    class _FakeConn:
        async def __aenter__(self) -> Any:
            return self

        async def __aexit__(self, *a: Any) -> None:
            return None

    class _FakePool:
        def acquire(self) -> Any:
            return _FakeConn()

    monkeypatch.setattr(mod.connection, "get_pool", lambda: _FakePool())
    monkeypatch.setattr(mod, "create_pending", _create_pending)

    r = await mod.remove_asset_link(
        {
            "customer_id": "1234567890",
            "links": [
                {
                    "level": "CAMPAIGN",
                    "resource_name": "customers/1234567890/campaignAssets/7~9~CALLOUT",
                }
            ],
        }
    )
    # `preview_envelope` devolve status "dry_run" — verificado em
    # src/mcp/tools/_mutate_common.py. Se este teste falhar dizendo "preview",
    # o erro esta no teste, NAO no envelope: nao monte envelope a mao.
    assert r["status"] == "dry_run"
    assert r["confirmation_token"] == "tok-123"
    assert r["expires_in_minutes"] > 0, "TTL vem de DEFAULT_TTL_MINUTES"
    assert "applied_count" not in r
```

- [ ] **Step 2: Rode os testes e confirme que falham**

Run: `python -m pytest tests/unit/test_remove_asset_link.py -q`
Expected: FAIL com `ModuleNotFoundError: No module named 'src.mcp.tools.remove_asset_link'`

- [ ] **Step 3: Implemente a tool**

```python
# src/mcp/tools/remove_asset_link.py
# bucket: defer
"""Tool: remove_asset_link — desvincula asset, sem tocar na entidade.

Inverso do `create_and_link_assets`, que existia sem contraparte e custava idas
a UI. Formato precedente: `remove_audience.py`.

NAO remove a entidade `Asset` (spec secao 2): o que serve na SERP e o vinculo,
asset orfao e inerte, e remover a entidade e irreversivel numa coisa que pode
estar linkada onde a varredura nao alcancou.
"""

from typing import Any

from src.db import connection
from src.governance.blast_radius import classify
from src.governance.dry_run import create_pending
from src.mcp.context import get_current
from src.mcp.tools._mutate_common import preview_envelope
from src.mcp.tools._registry import register_tool

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "links": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "level": {"type": "string", "enum": ["CUSTOMER", "CAMPAIGN", "AD_GROUP"]},
                    "resource_name": {"type": "string", "minLength": 1},
                },
                "required": ["level", "resource_name"],
                "additionalProperties": False,
            },
            "minItems": 1,
            "maxItems": 100,
        },
    },
    "required": ["customer_id", "links"],
    "additionalProperties": False,
}

_DESCRIPTION = (
    "[DEFER] Desvincula assets: remove o vínculo (customer_asset / campaign_asset "
    "/ ad_group_asset) e **não remove o asset** em si — asset órfão é inerte, e a "
    "entidade pode estar linkada onde a varredura não alcançou. Recebe `level` + "
    "`resource_name` exatamente como o `get_assets` devolve em cada linha; use "
    "aquela tool para descobrir o que remover, inclusive na camada de conta, que "
    "não aparece para quem olha só campanha. Sempre CONFIRM: devolve preview com "
    "confirmation_token, aplique via apply_change. Idempotente: vínculo já "
    "removido volta graciosamente via partial_failure. **Para confirmar a "
    "remoção, cheque `status == REMOVED` no registro alvo** — contagem de linhas "
    "NÃO distingue sucesso de falha, porque o vínculo removido continua na tabela."
)


@register_tool(
    name="remove_asset_link",
    description=_DESCRIPTION,
    input_schema=_SCHEMA,
    bucket="defer",
)
async def remove_asset_link(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    links = args["links"]
    target_count = len(links)

    risk = classify(operation="remove_asset_link", params={"target_count": target_count})
    # Always-CONFIRM: nao ha branch AUTO.

    por_nivel: dict[str, int] = {}
    for link in links:
        por_nivel[link["level"]] = por_nivel.get(link["level"], 0) + 1

    payload = {
        "links": links,
        "__target_count__": target_count,
        "__partial_failure__": True,
        "__params_summary__": {"target_count": target_count, "by_level": por_nivel},
    }
    niveis = ", ".join(f"{n}×{c}" for n, c in sorted(por_nivel.items()))
    summary = f"Desvincular {target_count} asset(s) ({niveis}). A entidade Asset NÃO é removida."

    pool = connection.get_pool()
    async with pool.acquire() as conn:
        token = await create_pending(
            conn,
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=customer_id,
            operation_type="remove_asset_link",
            payload=payload,
            blast_summary=summary,
        )
    return preview_envelope(
        "remove_asset_link",
        customer_id,
        summary,
        token,
        confirmation_reason=risk.reason,
        target_count=target_count,
    )
```

- [ ] **Step 3b: Dê ao `classify` um branch explícito**

`classify` já devolve CONFIRM para operação desconhecida — o fallback é *"Unknown operation — default safe to confirm"*. Então a tool **funciona** sem isto. Mas o `confirmation_reason` que chega ao gestor sairia como *"remove_asset_link: unknown operation"*, o que é mensagem ruim para uma operação destrutiva, e nada na política registraria a intenção.

Acrescente em `src/governance/blast_radius.py`, junto do branch de `remove_audience`:

```python
    # Unlink de asset — remove, sempre confirma (spec §7.1). O vinculo sai; a
    # entidade Asset NAO. Fallback de unknown ja daria CONFIRM, mas a razao
    # ficaria ilegivel pro gestor e a intencao nao ficaria registrada.
    if operation == "remove_asset_link":
        return RiskClassification(
            RiskLevel.CONFIRM,
            f"remove_asset_link ({target_count} vínculo(s)) — sempre confirma (spec §7.1 remove)",
        )
```

E o teste, em `tests/unit/test_remove_asset_link.py`:

```python
def test_classify_tem_branch_proprio_e_nao_cai_no_fallback() -> None:
    from src.governance.blast_radius import RiskLevel, classify

    r = classify(operation="remove_asset_link", params={"target_count": 3})
    assert r.level is RiskLevel.CONFIRM
    assert "unknown" not in r.reason.lower(), "caiu no fallback — falta o branch explicito"
    assert "3" in r.reason
```

- [ ] **Step 4: Rode os testes e confirme que passam**

Run: `python -m pytest tests/unit/test_remove_asset_link.py -q`
Expected: PASS, 5 testes.

- [ ] **Step 5: Commit**

```bash
python scripts/check_pre_push.py > /dev/null 2>&1; echo $?
git add src/mcp/tools/remove_asset_link.py src/governance/blast_radius.py tests/unit/test_remove_asset_link.py
git commit -m "feat(mcp): remove_asset_link desvincula asset sem remover a entidade"
```

---

### Task 6: Smoke em conta real, com a asserção que não mente

**Files:**
- Create: `docs/operacao/phase-3b-XX-assets-smoke.md` (numere conforme o sprint corrente)

**Interfaces:**
- Consumes: as duas tools das Tasks 3 e 5.
- Produces: runbook de smoke executado, com os resultados preenchidos.

- [ ] **Step 1: Escreva o runbook**

Cubra, na conta `7862230676`:

1. `get_assets(customer_id)` sem filtro → confirme que aparecem linhas dos **três** níveis e que há pelo menos uma `REMOVED` (existem: os callouts `144113768040` e `144113768046`).
2. `get_assets(customer_id, field_type="CALLOUT")` → confirme o filtro.
3. Confirme que `144113768043` ("Atendimento Eficaz") aparece com `primary_status: ELIGIBLE` **nos dois níveis** — é o par coexistente que a probe da spec usou.
4. `remove_asset_link` num vínculo de teste → guarde o `confirmation_token`, aplique por `apply_change`.
5. **Confirmação (obrigatória, spec §7):**
   ```
   SELECT campaign.name, campaign_asset.status, asset.id
   FROM campaign_asset
   WHERE campaign_asset.field_type = 'CALLOUT' AND asset.id IN (<id alvo>)
   ```
   Asserte `status == REMOVED` **no registro alvo**. **Nunca** confirme por ausência em lista filtrada nem por `row_count`: medido em 02/09, a contagem não-filtrada dá **16 nos dois estados** (sucesso e falha), e a filtrada só distingue com baseline conhecido.
6. Reaplique o mesmo `remove_asset_link` → confirme que volta gracioso (idempotência via partial_failure), não erro.

- [ ] **Step 2: Execute o smoke e preencha os resultados**

Cada passo com o valor real observado. Passo que falhar vira finding com `/findings-add`.

- [ ] **Step 3: Commit**

```bash
python scripts/check_pre_push.py > /dev/null 2>&1; echo $?
git add docs/operacao/phase-3b-XX-assets-smoke.md
git commit -m "docs(operacao): smoke de get_assets e remove_asset_link"
```

---

## Correções da auto-revisão (aplicadas antes de entregar)

Quatro coisas que eu tinha escrito errado e que fariam o executor tropeçar. As três primeiras só apareceram porque fui **ler o codebase** em vez de reler o plano:

1. **`preview_envelope` devolve `status: "dry_run"`, não `"preview"`.** O teste da Task 5 falharia, e o caminho "natural" para consertar seria montar o envelope à mão — que é um `Don't do` nomeado.
2. **Não existe lista de imports de tool para atualizar.** `import_all_tools()` descobre por `pkgutil`; o `__init__.py` está vazio de propósito. Duas tasks mandavam editá-lo.
3. **`classify` cai num fallback genérico** para operação nova. Funciona (o default é CONFIRM), mas entregaria ao gestor a razão *"unknown operation"* numa ação destrutiva. Virou o Step 3b.
4. **O teste de registro precisava do import no topo do arquivo** — rodando isolado, `get_tool` devolveria `None`.

## Self-review deste plano

**Cobertura da spec (metade de assets):** §2.1 → Global Constraints · §5 decisões → Tasks 1-3 (todos os `field_type`, sem filtro de status, três camadas, órfãos, `resource_name`, nota de métricas) · §5.1 → ausência deliberada de `effective` em toda a Task 3 · §6 → Tasks 4-5 · §7 → Task 6 passo 5 e a description da Task 5 · §8 guards 5,6,7,8 → Tasks 3 e 5; guards 1,2,3,4,9,10 pertencem à metade de `ad_schedule` e ficam no outro plano.

**Nota de honestidade sobre o guard 10 da spec** ("envelope e blast radius vêm do compartilhado, guard derivado do source"): a Task 5 usa `preview_envelope` e `classify`, e o passo 6 manda rodar o guard existente do F112 — mas **este plano não cria** o guard derivado novo. Se ele não existir para `remove_asset_link`, criá-lo é trabalho da metade de `ad_schedule`, que introduz a segunda tool de mutate e torna o guard genérico útil de verdade.

**Consistência de tipos:** os dicts da Task 1 têm exatamente as chaves que a Task 2 lê (`asset_id`, `level`, `status`, `primary_status`) e que a Task 3 devolve; `resource_name` atravessa Task 1 → Task 3 → schema da Task 5 → payload da Task 4 com o mesmo nome.

## Por que `ad_schedule` fica em outro plano

Não é fatiamento por tamanho. São subsistemas independentes — não compartilham arquivo nem função — e cada metade entrega software funcionando sozinha. Mais dois motivos específicos:

1. **A §4.2 da spec diz que a conjunta dia × hora é levantada *na implementação*, com a janela madura.** Escrever hoje os números do preview seria congelar dado que a própria spec manda medir na hora. A conta teve copy nova em 02/09 e portfólio saindo de re-learning.
2. **Risco muito diferente.** `get_assets` é leitura pura; `update_ad_schedule` desliga veiculação e queima 14 dias de re-learning se errar. Misturar os dois num plano faz o revisor gastar atenção uniforme onde ela deveria ser desigual.
