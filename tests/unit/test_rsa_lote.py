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


def test_compacto_nao_e_aplicado_ate_5(monkeypatch) -> None:
    from src.mcp.tools._rsa_textos import preview_do_lote

    ups = _updates(5)
    assert preview_do_lote(ups, lambda u: {"x": u["ad_id"]}) == [{"x": u["ad_id"]} for u in ups]
    assert preview_do_lote(_updates(6), lambda u: {"x": 1})[0]["contagens"]


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
