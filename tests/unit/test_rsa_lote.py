"""M2: teto de lote de RSA 5 -> 50, preview compacto, releitura unica."""

from __future__ import annotations

import json
import re

import jsonschema
import pytest

from src.mcp.tools import apply_change as mod
from src.mcp.tools import create_rsa, update_rsa
from src.mcp.tools._registry import get_tool, import_all_tools
from src.mcp.tools._rsa_textos import TETO_LOTE_RSA, preview_compacto
from tests.unit.test_apply_change_rsa_estado import (  # noqa: F401
    _ctx,  # noqa: F401  (autouse fixture)
    _estado,
    _mutacao,
    _saved,
    _wire,
)

_RSA_OK = {
    "ad_group_id": "55",
    "headlines": ["a", "b", "c"],
    "descriptions": ["d1", "d2"],
    "final_urls": ["https://x.com"],
}


def _schema(nome: str) -> dict:
    import_all_tools()
    tool = get_tool(nome)
    assert tool is not None
    return tool.input_schema


def _updates(n: int) -> list[dict]:
    return [{"ad_id": str(i + 1), "final_urls": ["https://x.com"]} for i in range(n)]


def test_51_recusa_50_passa() -> None:
    s = _schema("update_rsa")
    jsonschema.validate({"customer_id": "1234567890", "updates": _updates(50)}, s)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"customer_id": "1234567890", "updates": _updates(51)}, s)
    c = _schema("create_rsa")
    jsonschema.validate({"customer_id": "1234567890", "rsas": [_RSA_OK] * 50}, c)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"customer_id": "1234567890", "rsas": [_RSA_OK] * 51}, c)


def test_constante_unica() -> None:
    assert TETO_LOTE_RSA == 50
    assert create_rsa._SCHEMA["properties"]["rsas"]["maxItems"] is TETO_LOTE_RSA
    assert update_rsa._SCHEMA["properties"]["updates"]["maxItems"] is TETO_LOTE_RSA


def test_preview_50_abaixo_do_teto() -> None:
    p = preview_compacto(_updates(50))
    assert len(p) == 50
    assert len(json.dumps(p)) < 60_000
    assert set(p[0]) == {"ad_id", "fields_updated", "contagens", "final_urls", "path1", "path2"}
    assert set(p[0]["contagens"]) == {"headlines", "descriptions", "pinos"}


def test_compacto_texto_so_quando_muda() -> None:
    ups = _updates(6)
    ups[0]["headlines"] = ["a", {"text": "b", "pinned_field": "HEADLINE_1"}, "c"]
    p = preview_compacto(ups)
    assert p[0]["headlines"] == ["a", {"text": "b", "pinned_field": "HEADLINE_1"}, "c"]
    assert p[0]["contagens"] == {"headlines": 3, "descriptions": 0, "pinos": 1}
    assert "headlines" not in p[1] and "descriptions" not in p[1]


def test_compacto_nao_e_aplicado_ate_5() -> None:
    from src.mcp.tools._rsa_textos import preview_do_lote

    ups = _updates(5)
    assert preview_do_lote(ups, lambda u: {"x": u["ad_id"]}) == [{"x": u["ad_id"]} for u in ups]
    # acima de 5 o detalhado nao roda: a forma e exatamente a do compacto de hoje
    seis = preview_do_lote(_updates(6), lambda u: {"x": 1})
    assert seis == preview_compacto(_updates(6))
    assert seis[0] == {
        "ad_id": "1",
        "fields_updated": ["final_urls"],
        "contagens": {"headlines": 0, "descriptions": 0, "pinos": 0},
        "final_urls": ["https://x.com"],
        "path1": None,
        "path2": None,
    }


def _rsas_com_pino(n: int) -> list[dict]:
    pinado = {
        **_RSA_OK,
        "headlines": [
            {"text": "PinoSecretoA", "pinned_field": "HEADLINE_1"},
            {"text": "PinoSecretoB", "pinned_field": "HEADLINE_1"},
            "c",
        ],
        "descriptions": [{"text": "PinoSecretoD", "pinned_field": "DESCRIPTION_2"}, "d2"],
    }
    return [pinado] + [dict(_RSA_OK) for _ in range(n - 1)]


async def _preview_create(rsas: list[dict]) -> dict:
    from unittest.mock import AsyncMock, patch

    with (
        patch(
            "src.mcp.tools.create_rsa.validate_parent_ad_groups_for_rsa_create",
            AsyncMock(return_value=None),
        ),
        patch("src.mcp.tools._mutate_common.create_pending", AsyncMock(return_value="T")),
        patch("src.mcp.tools._mutate_common.connection.get_pool") as pool,
    ):
        pool.return_value.acquire.return_value.__aenter__ = AsyncMock(return_value=None)
        pool.return_value.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
        return await create_rsa.create_rsa({"customer_id": "1234567890", "rsas": rsas})


@pytest.mark.asyncio
async def test_create_acima_de_5_pinos_viram_contagem_por_posicao() -> None:
    out = await _preview_create(_rsas_com_pino(6))
    assert out["status"] == "dry_run"
    prev = out["rsas_preview"]
    assert prev[0]["pinos"] == {"HEADLINE_1": 2, "DESCRIPTION_2": 1}
    assert all(p["pinos"] == {} for p in prev[1:])
    assert "PinoSecreto" not in json.dumps(prev)


@pytest.mark.asyncio
async def test_create_ate_5_pinos_seguem_com_texto() -> None:
    """Controle: no detalhado (ate 5) o preview mostra o texto pinado."""
    out = await _preview_create(_rsas_com_pino(5))
    assert out["rsas_preview"][0]["pinos"] == {
        "HEADLINE_1": ["PinoSecretoA", "PinoSecretoB"],
        "DESCRIPTION_2": ["PinoSecretoD"],
    }


def test_update_description_nao_se_contradiz_sobre_o_preview() -> None:
    import_all_tools()
    desc = get_tool("update_rsa").description
    # um so trecho fala do preview de pinos, e ele diz o limite dos dois lados
    assert desc.count("antes->depois") == 1
    assert "ate 5 updates o preview mostra pinos antes->depois" in desc
    assert "acima de 5" in desc


@pytest.mark.asyncio
async def test_update_recusa_ad_id_repetido_antes_do_preflight() -> None:
    from unittest.mock import AsyncMock, patch

    preflight = AsyncMock(return_value=None)
    pending = AsyncMock(return_value="T")
    with (
        patch("src.mcp.tools.update_rsa.validate_existing_rsas_for_update", preflight),
        patch("src.mcp.tools._mutate_common.create_pending", pending),
    ):
        out = await update_rsa.update_rsa(
            {
                "customer_id": "1234567890",
                "updates": [
                    {"ad_id": "11", "path1": "a"},
                    {"ad_id": "22", "path1": "b"},
                    {"ad_id": "11", "path2": "c"},
                ],
            }
        )
    assert out["status"] == "error"
    assert "ad_id 11" in out["error_message"] and "repetido" in out["error_message"]
    assert "22" not in out["error_message"]
    preflight.assert_not_awaited()
    pending.assert_not_awaited()


@pytest.mark.asyncio
async def test_releitura_do_lote_e_uma_gaql(monkeypatch) -> None:
    nomes = [f"customers/1234567890/ads/{i}" for i in range(1, 51)]
    queries = _wire(
        monkeypatch,
        saved=_saved(),
        mutacao=_mutacao(nomes),
        rows=[_estado(str(i)) for i in range(1, 51)],
    )
    out = await mod.apply_change({"confirmation_token": "ABCDEFGH"})
    assert len(queries) == 1
    assert len(out["estado_revisao"]) == 50


@pytest.mark.asyncio
async def test_lote_misto_so_rele_quem_mudou(monkeypatch) -> None:
    nomes = [f"customers/1234567890/ads/{i}" for i in range(1, 51)]
    efeitos = ["mudou" if i % 2 == 0 else "sem_efeito" for i in range(50)]
    mudou = [str(i + 1) for i in range(50) if i % 2 == 0]
    queries = _wire(
        monkeypatch,
        saved=_saved(),
        mutacao=_mutacao(nomes, efeitos),
        rows=[_estado(a) for a in mudou],
    )
    out = await mod.apply_change({"confirmation_token": "ABCDEFGH"})
    assert len(queries) == 1
    assert [e["ad_id"] for e in out["estado_revisao"]] == mudou
    lidos = re.search(r"IN \(([^)]*)\)", queries[0]).group(1).replace(" ", "").split(",")
    assert lidos == mudou
