"""remove_ad (S3): remove anuncio com token, sempre CONFIRM, e releitura no apply.

Remocao e IRREVERSIVEL: anuncio REMOVED nao volta a ENABLED. Por isso a tool nao
auto-aplica nunca (o `update_ad_status` aceita so ENABLED/PAUSED e auto-aplica ate 5).

**Os fakes montam a row com o proto de verdade** (`AdGroupAd`, `AdGroup`, `Campaign`),
so com os campos que o SELECT pediu (padrao de `test_update_recommendation_subscription`):
proto-plus devolve o zero-value para campo fora do SELECT (F145), entao um dict pronto
passaria verde com `system_managed_resource_source` fora da query — e a recusa de
variacao (F181) morreria calada.
"""

from __future__ import annotations

import re
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import jsonschema
import pytest
from google.ads.googleads.v25.enums.types.ad_group_ad_status import AdGroupAdStatusEnum
from google.ads.googleads.v25.enums.types.ad_type import AdTypeEnum
from google.ads.googleads.v25.enums.types.system_managed_entity_source import (
    SystemManagedResourceSourceEnum,
)
from google.ads.googleads.v25.resources.types.ad_group import AdGroup
from google.ads.googleads.v25.resources.types.ad_group_ad import AdGroupAd
from google.ads.googleads.v25.resources.types.campaign import Campaign

from src.db import connection
from src.google_ads.queries.remover_anuncio import (
    anuncios_query,
    enabled_por_grupo_query,
)
from src.mcp.tools import remove_ad as mod
from tests.unit.fixtures.fake_pool import FakePool

_CID = "7862230676"


def _campos_do_select(query: str) -> set[str]:
    m = re.search(r"\bSELECT\b(.+?)\bFROM\b", query, re.S | re.I)
    assert m is not None, f"GAQL sem SELECT..FROM: {query!r}"
    return {c.strip() for c in m.group(1).split(",") if c.strip()}


def linha_de_anuncio(
    query: str,
    *,
    ad_id: str,
    ad_group_id: str,
    status: str | None,
    source: str = "UNSPECIFIED",
) -> Any:
    """Row real do proto, so com o que o SELECT pediu.

    `status=None` deixa o campo no default (UNSPECIFIED): o que chega quando o Google
    omite o campo — "nao lido", nao um status medido.
    """
    pedidos = _campos_do_select(query)
    aga = AdGroupAd()
    ag = AdGroup()
    camp = Campaign()
    if "ad_group_ad.ad.id" in pedidos:
        aga.ad.id = int(ad_id)
    if "ad_group_ad.ad.type" in pedidos:
        aga.ad.type_ = AdTypeEnum.AdType.RESPONSIVE_SEARCH_AD
    if "ad_group_ad.ad.system_managed_resource_source" in pedidos:
        aga.ad.system_managed_resource_source = (
            SystemManagedResourceSourceEnum.SystemManagedResourceSource[source]
        )
    if "ad_group_ad.status" in pedidos and status is not None:
        aga.status = AdGroupAdStatusEnum.AdGroupAdStatus[status]
    if "ad_group.id" in pedidos:
        ag.id = int(ad_group_id)
    if "ad_group.name" in pedidos:
        ag.name = f"Grupo {ad_group_id}"
    if "campaign.name" in pedidos:
        camp.name = "Campanha X"
    return SimpleNamespace(ad_group_ad=aga, ad_group=ag, campaign=camp)


@pytest.fixture(autouse=True)
def _ctx() -> Any:
    from src.mcp.context import McpRequestContext, clear_current, set_current

    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    yield
    clear_current()


def _wire(
    monkeypatch: pytest.MonkeyPatch,
    anuncios: list[dict[str, Any]],
    enabled: list[tuple[str, str]] | None = None,
    base: list[str] | None = None,
) -> dict[str, Any]:
    """`anuncios`: kwargs de `linha_de_anuncio`; `enabled`: (ad_group_id, ad_id) ENABLED."""
    cap: dict[str, Any] = {"queries": [], "pending": None, "base_chamado": []}

    async def _run(**kwargs: Any) -> list[dict[str, Any]]:
        q: str = kwargs["query"]
        cap["queries"].append(q)
        fmt = kwargs["row_formatter"]
        if "ad_group_ad.status = 'ENABLED'" in q:
            return [
                fmt(linha_de_anuncio(q, ad_id=ad, ad_group_id=ag, status="ENABLED"))
                for ag, ad in (enabled or [])
            ]
        return [fmt(linha_de_anuncio(q, **a)) for a in anuncios]

    async def _base(**kwargs: Any) -> list[str]:
        cap["base_chamado"].append(kwargs["ad_group_id"])
        return ["999"] if base is None else base

    async def _create_pending(conn: Any, **kwargs: Any) -> str:
        cap["pending"] = kwargs
        return "TOKEN123"

    monkeypatch.setattr(mod, "run_report", _run)
    monkeypatch.setattr(mod, "buscar_ads_base_do_grupo", _base)
    monkeypatch.setattr("src.mcp.tools._mutate_common.create_pending", _create_pending)
    monkeypatch.setattr(connection, "get_pool", lambda: FakePool())
    return cap


async def _chamar(*ad_ids: str) -> dict[str, Any]:
    out: dict[str, Any] = await mod.remove_ad({"customer_id": _CID, "ad_ids": list(ad_ids)})
    return out


def _item(out: dict[str, Any], ad_id: str) -> dict[str, Any]:
    return next(i for i in out["anuncios"] if i["ad_id"] == ad_id)


# --------------------------------------------------------------------------- #
# Recusas (sem token)
# --------------------------------------------------------------------------- #
async def test_ad_inexistente_recusa_sem_token(monkeypatch: pytest.MonkeyPatch) -> None:
    cap = _wire(monkeypatch, [{"ad_id": "11", "ad_group_id": "100", "status": "ENABLED"}])
    out = await _chamar("11", "22")
    assert out["status"] == "error"
    assert "22" in out["error_message"]
    assert "nao encontrado" in out["error_message"]
    assert cap["pending"] is None


async def test_variacao_recusa_apontando_o_base(monkeypatch: pytest.MonkeyPatch) -> None:
    cap = _wire(
        monkeypatch,
        [{"ad_id": "11", "ad_group_id": "100", "status": "ENABLED", "source": "AD_VARIATIONS"}],
        base=["999"],
    )
    out = await _chamar("11")
    assert out["status"] == "error"
    assert "AD_VARIATIONS" in out["error_message"]
    assert "variacao" in out["error_message"]
    assert "999" in out["error_message"]
    assert cap["base_chamado"] == ["100"]
    assert cap["pending"] is None


async def test_variacao_com_dois_bases_lista_os_dois(monkeypatch: pytest.MonkeyPatch) -> None:
    """Smoke de 15/11 na MO: o MARTELETE tem 2 bases (730606848394, 807521122523) e a
    recusa citava so o grupo. Os dois sao o fato medido; nenhum e escolhido."""
    cap = _wire(
        monkeypatch,
        [{"ad_id": "11", "ad_group_id": "100", "status": "ENABLED", "source": "AD_VARIATIONS"}],
        base=["730606848394", "807521122523"],
    )
    out = await _chamar("11")
    assert out["status"] == "error"
    msg = out["error_message"]
    assert "730606848394, 807521122523" in msg
    assert "o anuncio BASE 730606848394" not in msg
    assert "encerre o experimento na UI" in msg
    assert cap["pending"] is None


async def test_variacao_sem_base_nomeia_o_grupo(monkeypatch: pytest.MonkeyPatch) -> None:
    cap = _wire(
        monkeypatch,
        [{"ad_id": "11", "ad_group_id": "100", "status": "ENABLED", "source": "AD_VARIATIONS"}],
        base=[],
    )
    out = await _chamar("11")
    assert out["status"] == "error"
    assert "AD_VARIATIONS" in out["error_message"]
    assert "100" in out["error_message"]
    assert cap["pending"] is None


async def test_ad_em_mais_de_um_grupo_recusa(monkeypatch: pytest.MonkeyPatch) -> None:
    cap = _wire(
        monkeypatch,
        [
            {"ad_id": "11", "ad_group_id": "100", "status": "ENABLED"},
            {"ad_id": "11", "ad_group_id": "200", "status": "PAUSED"},
        ],
    )
    out = await _chamar("11")
    assert out["status"] == "error"
    assert "100" in out["error_message"] and "200" in out["error_message"]
    assert cap["pending"] is None


async def test_todos_ja_removed_sem_token(monkeypatch: pytest.MonkeyPatch) -> None:
    cap = _wire(
        monkeypatch,
        [
            {"ad_id": "11", "ad_group_id": "100", "status": "REMOVED"},
            {"ad_id": "22", "ad_group_id": "100", "status": "REMOVED"},
        ],
    )
    out = await _chamar("11", "22")
    assert out["status"] == "no_changes"
    assert "ja esta REMOVED" in out["message"]
    assert "confirmation_token" not in out
    assert cap["pending"] is None


# --------------------------------------------------------------------------- #
# Preview
# --------------------------------------------------------------------------- #
async def test_lote_misto_tira_os_removed(monkeypatch: pytest.MonkeyPatch) -> None:
    cap = _wire(
        monkeypatch,
        [
            {"ad_id": "11", "ad_group_id": "100", "status": "REMOVED"},
            {"ad_id": "22", "ad_group_id": "100", "status": "PAUSED"},
            {"ad_id": "33", "ad_group_id": "200", "status": "ENABLED"},
        ],
        enabled=[("200", "33"), ("200", "34")],
    )
    out = await _chamar("11", "22", "33")
    assert out["status"] == "dry_run"
    assert out["ja_removidos"] == ["11"]
    payload = cap["pending"]["payload"]
    assert payload["ads"] == [
        {"ad_group_id": "100", "ad_id": "22"},
        {"ad_group_id": "200", "ad_id": "33"},
    ]
    assert payload["__target_count__"] == 2
    assert payload["__partial_failure__"] is True
    assert payload["__params_summary__"] == {"count": 2, "ad_ids": ["22", "33"]}
    assert cap["pending"]["operation_type"] == "remove_ad"
    assert [i["ad_id"] for i in out["anuncios"]] == ["22", "33"]
    # a contagem de ENABLED so le os grupos que ficaram no lote
    assert cap["queries"][1] == enabled_por_grupo_query(["100", "200"])


async def test_aviso_ultimo_enabled_do_grupo(monkeypatch: pytest.MonkeyPatch) -> None:
    _wire(
        monkeypatch,
        [{"ad_id": "11", "ad_group_id": "100", "status": "ENABLED"}],
        enabled=[("100", "11")],
    )
    out = await _chamar("11")
    item = _item(out, "11")
    assert "ultimo anuncio ENABLED do grupo" in item["aviso"]
    assert item["status_atual"] == "ENABLED"
    assert item["ad_group_name"] == "Grupo 100"
    assert item["campaign_name"] == "Campanha X"
    # o aviso tambem vai no blast_summary, que o apply_change reexibe
    assert "ultimo anuncio ENABLED do grupo" in out["blast_summary"]


async def test_aviso_quando_o_lote_tira_todos_os_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _wire(
        monkeypatch,
        [
            {"ad_id": "11", "ad_group_id": "100", "status": "ENABLED"},
            {"ad_id": "12", "ad_group_id": "100", "status": "ENABLED"},
            {"ad_id": "21", "ad_group_id": "200", "status": "ENABLED"},
            {"ad_id": "22", "ad_group_id": "200", "status": "ENABLED"},
        ],
        enabled=[("100", "11"), ("100", "12"), ("200", "21"), ("200", "22"), ("200", "23")],
    )
    out = await _chamar("11", "12", "21", "22")
    assert "ultimo anuncio ENABLED do grupo" in _item(out, "11")["aviso"]
    assert "ultimo anuncio ENABLED do grupo" in _item(out, "12")["aviso"]
    assert _item(out, "21").get("aviso") is None
    assert _item(out, "22").get("aviso") is None


async def test_paused_nao_dispara_aviso(monkeypatch: pytest.MonkeyPatch) -> None:
    _wire(
        monkeypatch,
        [{"ad_id": "11", "ad_group_id": "100", "status": "PAUSED"}],
        enabled=[],
    )
    out = await _chamar("11")
    assert _item(out, "11").get("aviso") is None
    assert "ultimo anuncio ENABLED" not in out["blast_summary"]


async def test_preview_tem_aviso_de_irreversivel_e_risco_confirm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cap = _wire(
        monkeypatch,
        [{"ad_id": "11", "ad_group_id": "100", "status": "PAUSED"}],
    )
    out = await _chamar("11")
    assert out["status"] == "dry_run"
    assert out["confirmation_token"] == "TOKEN123"
    assert out["aviso_irreversivel"] == (
        "A remocao e irreversivel: anuncio REMOVED nao volta a ENABLED; para voltar, crie outro."
    )
    assert "irreversivel" in out["blast_summary"]
    assert "irreversivel" in out["confirmation_reason"]
    assert cap["pending"]["blast_summary"] == out["blast_summary"]
    # o status lido veio do proto: o SELECT tem que pedir o que a tool usa
    assert cap["queries"][0] == anuncios_query(["11"])


async def test_audit_so_contagens_e_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    cap = _wire(
        monkeypatch,
        [{"ad_id": "11", "ad_group_id": "100", "status": "PAUSED"}],
    )
    await _chamar("11")
    resumo = cap["pending"]["payload"]["__params_summary__"]
    assert resumo == {"count": 1, "ad_ids": ["11"]}
    texto = repr(resumo)
    assert "Grupo 100" not in texto and "Campanha X" not in texto
    assert "ad_group_name" not in resumo and "campaign_name" not in resumo


async def test_status_nao_lido_fica_no_lote(monkeypatch: pytest.MonkeyPatch) -> None:
    """UNSPECIFIED nao e REMOVED medido: nao se afirma no-op sem medir."""
    cap = _wire(monkeypatch, [{"ad_id": "11", "ad_group_id": "100", "status": None}])
    out = await _chamar("11")
    assert out["status"] == "dry_run"
    assert cap["pending"]["payload"]["ads"] == [{"ad_group_id": "100", "ad_id": "11"}]
    # campo nao lido e `None`, nao o nome cru do default do proto (F145)
    assert _item(out, "11")["status_atual"] is None


async def test_duplicata_depois_de_normalizar_recusa_sem_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`uniqueItems` compara a string crua: "22" e "022" passam no schema."""
    cap = _wire(monkeypatch, [{"ad_id": "22", "ad_group_id": "100", "status": "ENABLED"}])
    jsonschema.validate({"customer_id": _CID, "ad_ids": ["22", "022"]}, mod._SCHEMA)
    out = await _chamar("22", "022")
    assert out["status"] == "error"
    assert "22" in out["error_message"]
    assert "repetido" in out["error_message"]
    assert cap["queries"] == []
    assert cap["pending"] is None


# --------------------------------------------------------------------------- #
# Schema e queries
# --------------------------------------------------------------------------- #
def test_schema() -> None:
    schema = mod._SCHEMA
    ad_ids = schema["properties"]["ad_ids"]
    assert schema["required"] == ["customer_id", "ad_ids"]
    assert ad_ids["maxItems"] == 20
    assert ad_ids["minItems"] == 1
    assert ad_ids["uniqueItems"] is True
    assert ad_ids["items"]["pattern"] == "^[0-9]+$"
    from src.mcp.tools._registry import all_tools, import_all_tools

    import_all_tools()
    tool = next(t for t in all_tools() if t.name == "remove_ad")
    assert tool.description.startswith("[DEFER]")
    assert "irreversivel" in tool.description
    assert tool.bucket == "defer"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"customer_id": _CID, "ad_ids": ["1", "1"]}, schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"customer_id": _CID, "ad_ids": [str(i) for i in range(21)]}, schema)


def test_queries_do_contrato() -> None:
    assert anuncios_query(["11", "022"]) == (
        "SELECT ad_group_ad.ad.id, ad_group_ad.ad.type, "
        "ad_group_ad.ad.system_managed_resource_source, ad_group_ad.status, "
        "ad_group.id, ad_group.name, campaign.name FROM ad_group_ad "
        "WHERE ad_group_ad.ad.id IN (11, 22)"
    )
    assert enabled_por_grupo_query(["100", "200"]) == (
        "SELECT ad_group.id, ad_group_ad.ad.id FROM ad_group_ad "
        "WHERE ad_group.id IN (100, 200) AND ad_group_ad.status = 'ENABLED'"
    )
    with pytest.raises(ValueError):
        anuncios_query(["1 OR 1=1"])
    with pytest.raises(ValueError):
        anuncios_query([])
