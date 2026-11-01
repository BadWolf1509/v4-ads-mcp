"""meta_get_creatives e meta_get_ad_preview: criativos, posse fail-closed e iframe."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.mcp.context import McpRequestContext, clear_current, set_current
from src.mcp.tools import meta_get_ad_preview as prev
from src.mcp.tools import meta_get_creatives as crea
from src.meta_ads import criativos

_CONTA = "act_1"
_IFRAME = (
    '<iframe src="https://business.facebook.com/ads/api/preview_iframe.php?d=1&amp;t=2" '
    'width="320" height="300"></iframe>'
)


@pytest.fixture(autouse=True)
def _ctx() -> Iterator[None]:
    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    yield
    clear_current()


def _graph(side_effect: Any) -> tuple[AsyncMock, Any]:
    g = AsyncMock(side_effect=side_effect)
    return g, patch.object(criativos, "run_meta_graph_get", g)


def _edges(g: AsyncMock) -> list[str]:
    return [c.kwargs["edge"] for c in g.await_args_list]


_ADS = {
    "data": [
        {"id": "11", "creative": {"id": "900"}},
        {"id": "12", "creative": {"id": "900"}},
        {"id": "13", "creative": {"id": "901"}},
    ]
}


# ---------- meta_get_creatives ----------


@pytest.mark.asyncio
async def test_criativo_com_e_sem_imagem() -> None:
    g, p = _graph(
        [
            {
                "data": [
                    {
                        "id": "900",
                        "name": "c1",
                        "image_url": "https://x/i.jpg",
                        "title": "T",
                        "body": "B",
                        "call_to_action_type": "LEARN_MORE",
                    },
                    {"id": "901", "name": "c2"},
                ]
            }
        ]
    )
    with p:
        r = await crea.meta_get_creatives({"ad_account_id": _CONTA})
    assert r["status"] == "success" and r["truncated"] is False
    c1, c2 = r["creatives"]
    assert c1["image_url"] == "https://x/i.jpg" and c1["call_to_action_type"] == "LEARN_MORE"
    assert c2["image_url"] is None and c2["title"] is None and c2["thumbnail_url"] is None
    assert c2["ads_vinculados"] is None
    kw = g.await_args_list[0].kwargs
    assert kw["edge"] == "/act_1/adcreatives"
    assert kw["audit_this_call"] is True
    assert kw["operation_name"] == "meta_get_creatives"
    assert kw["params"]["limit"] == 100
    assert "effective_object_story_id" in kw["params"]["fields"]


@pytest.mark.asyncio
async def test_limite_marca_truncated() -> None:
    g, p = _graph([{"data": [{"id": str(i)} for i in range(4)]}])
    with p:
        r = await crea.meta_get_creatives({"ad_account_id": _CONTA, "limit": 3})
    assert r["truncated"] is True and len(r["creatives"]) == 3 and r["truncated_hint"]


@pytest.mark.asyncio
async def test_ad_id_traz_o_criativo_do_anuncio_e_ads_vinculados() -> None:
    g, p = _graph(
        [
            _ADS,
            {"data": [{"id": "901", "name": "outro"}, {"id": "900", "name": "alvo"}]},
        ]
    )
    with p:
        r = await crea.meta_get_creatives({"ad_account_id": _CONTA, "ad_id": "11"})
    assert r["status"] == "success"
    assert _edges(g) == ["/act_1/ads", "/act_1/adcreatives"]
    assert g.await_args_list[0].kwargs["params"]["fields"] == "id,creative{id}"
    assert [c["id"] for c in r["creatives"]] == ["900"]
    assert r["creatives"][0]["ads_vinculados"] == ["11", "12"]


@pytest.mark.asyncio
async def test_ad_id_ausente_da_conta_e_erro() -> None:
    g, p = _graph([_ADS])
    with p:
        r = await crea.meta_get_creatives({"ad_account_id": _CONTA, "ad_id": "999"})
    assert r["status"] == "error" and "grande" in r["error_message"]
    assert _edges(g) == ["/act_1/ads"]


@pytest.mark.asyncio
async def test_ad_id_nao_numerico_e_recusado() -> None:
    g, p = _graph([_ADS])
    with p:
        r = await crea.meta_get_creatives({"ad_account_id": _CONTA, "ad_id": "11/x"})
    assert r["status"] == "error"
    g.assert_not_awaited()


def test_creatives_registrada_como_defer() -> None:
    from src.mcp.tools._registry import get_tool

    t = get_tool("meta_get_creatives")
    assert t is not None and t.bucket == "defer" and t.description.startswith("[DEFER]")
    assert t.input_schema["properties"]["ad_account_id"]["pattern"] == r"^act_\d+$"
    assert t.input_schema["properties"]["limit"]["maximum"] == 500


# ---------- meta_get_ad_preview ----------


@pytest.mark.asyncio
async def test_preview_por_creative_id_prova_posse_e_devolve_so_o_src() -> None:
    g, p = _graph(
        [
            {"data": [{"id": "5"}, {"id": "900"}]},
            {"data": [{"body": _IFRAME}]},
        ]
    )
    with p:
        r = await prev.meta_get_ad_preview({"ad_account_id": _CONTA, "creative_id": "900"})
    assert r["status"] == "success"
    assert r["preview_url"] == "https://business.facebook.com/ads/api/preview_iframe.php?d=1&t=2"
    assert "body" not in r and "<" not in str(r)
    assert r["ad_format"] == "MOBILE_FEED_STANDARD"
    assert _edges(g) == ["/act_1/adcreatives", "/act_1/generatepreviews"]
    posse = g.await_args_list[0].kwargs
    assert posse["params"] == {"fields": "id", "limit": 200}
    assert posse["max_pages"] == 5 and posse["audit_this_call"] is True
    ger = g.await_args_list[1].kwargs
    assert ger["params"]["creative"] == '{"id": "900"}'
    assert ger["params"]["ad_format"] == "MOBILE_FEED_STANDARD"
    assert ger["audit_this_call"] is True


@pytest.mark.asyncio
async def test_preview_por_ad_id_usa_o_criativo_da_linha_achada() -> None:
    g, p = _graph([_ADS, {"data": [{"body": _IFRAME}]}])
    with p:
        r = await prev.meta_get_ad_preview(
            {"ad_account_id": _CONTA, "ad_id": "13", "ad_format": "INSTAGRAM_STORY"}
        )
    assert r["status"] == "success" and r["creative_id"] == "901"
    assert _edges(g) == ["/act_1/ads", "/act_1/generatepreviews"]
    assert g.await_args_list[0].kwargs["params"] == {"fields": "id,creative{id}", "limit": 200}
    assert g.await_args_list[1].kwargs["params"]["creative"] == '{"id": "901"}'
    assert g.await_args_list[1].kwargs["params"]["ad_format"] == "INSTAGRAM_STORY"


@pytest.mark.asyncio
async def test_creative_id_fora_da_conta_nao_chama_generatepreviews() -> None:
    g, p = _graph([{"data": [{"id": "5"}, {"id": "6"}]}, {"data": [{"body": _IFRAME}]}])
    with p:
        r = await prev.meta_get_ad_preview({"ad_account_id": _CONTA, "creative_id": "777"})
    assert r["status"] == "error" and "grande" in r["error_message"]
    assert "/act_1/generatepreviews" not in _edges(g)
    assert _edges(g) == ["/act_1/adcreatives"]


@pytest.mark.asyncio
async def test_ad_id_fora_da_conta_nao_chama_generatepreviews() -> None:
    g, p = _graph([_ADS, {"data": [{"body": _IFRAME}]}])
    with p:
        r = await prev.meta_get_ad_preview({"ad_account_id": _CONTA, "ad_id": "999"})
    assert r["status"] == "error"
    assert "/act_1/generatepreviews" not in _edges(g)


@pytest.mark.asyncio
async def test_erro_na_leitura_de_posse_recusa_sem_gerar() -> None:
    g, p = _graph([RuntimeError("boom"), {"data": [{"body": _IFRAME}]}])
    with p:
        r = await prev.meta_get_ad_preview({"ad_account_id": _CONTA, "creative_id": "900"})
    assert r["status"] == "error"
    assert _edges(g) == ["/act_1/adcreatives"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "args",
    [
        {"ad_account_id": _CONTA},
        {"ad_account_id": _CONTA, "ad_id": "11", "creative_id": "900"},
        {"ad_account_id": _CONTA, "creative_id": "9;x"},
        {"ad_account_id": _CONTA, "creative_id": "900", "ad_format": "DESKTOP_FEED_STANDARD"},
    ],
)
async def test_argumentos_invalidos_sao_recusados_sem_chamar_a_graph(
    args: dict[str, Any],
) -> None:
    g, p = _graph([])
    with p:
        r = await prev.meta_get_ad_preview(args)
    assert r["status"] == "error"
    g.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "html",
    [
        '<iframe src="https://evil.com/x"></iframe>',
        '<iframe src="https://facebook.com.evil.com/x"></iframe>',
        '<iframe src="https://evilfacebook.com/x"></iframe>',
        '<iframe src="http://business.facebook.com/x"></iframe>',
        '<iframe src="javascript:alert(1)"></iframe>',
        '<iframe src="https://user@evil.com#@business.facebook.com/x"></iframe>',
        "<iframe></iframe>",
        "<div>sem iframe</div>",
        "",
    ],
)
async def test_src_invalido_ou_ausente_e_erro_sem_html_bruto(html: str) -> None:
    g, p = _graph([{"data": [{"id": "900"}]}, {"data": [{"body": html}]}])
    with p:
        r = await prev.meta_get_ad_preview({"ad_account_id": _CONTA, "creative_id": "900"})
    assert r["status"] == "error"
    assert "<" not in str(r) and "evil" not in str(r)


@pytest.mark.asyncio
async def test_preview_sem_data_e_erro() -> None:
    g, p = _graph([{"data": [{"id": "900"}]}, {"data": []}])
    with p:
        r = await prev.meta_get_ad_preview({"ad_account_id": _CONTA, "creative_id": "900"})
    assert r["status"] == "error"


def test_subdominio_https_de_facebook_com_passa() -> None:
    assert criativos.extrair_src_iframe('<iframe src="https://facebook.com/p"></iframe>')
    assert criativos.extrair_src_iframe('<iframe src="https://a.b.facebook.com/p"></iframe>')


def test_preview_registrada_como_defer_com_enum() -> None:
    from src.mcp.tools._registry import get_tool

    t = get_tool("meta_get_ad_preview")
    assert t is not None and t.bucket == "defer" and t.description.startswith("[DEFER]")
    props = t.input_schema["properties"]
    assert props["ad_account_id"]["pattern"] == r"^act_\d+$"
    assert props["ad_format"]["enum"] == [
        "MOBILE_FEED_STANDARD",
        "INSTAGRAM_STANDARD",
        "INSTAGRAM_STORY",
        "INSTAGRAM_REELS",
        "FACEBOOK_STORY_MOBILE",
        "FACEBOOK_REELS_MOBILE",
    ]
    assert props["ad_id"]["pattern"] == r"^\d+$"
    assert props["creative_id"]["pattern"] == r"^\d+$"
