"""S2: update_rsa igual ao anuncio atual sai do token."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.google_ads.preflight import _format_rsa_preflight_row
from src.google_ads.rsa_textos import campos_sem_mudanca
from src.mcp.context import McpRequestContext, clear_current, set_current


@pytest.fixture
def _ctx():
    ctx = McpRequestContext(manager_id=uuid4(), session_id=uuid4())
    set_current(ctx)
    yield ctx
    clear_current()


def _atual(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "headlines": None,
        "descriptions": None,
        "final_urls": None,
        "path1": "",
        "path2": "",
    }
    base.update(kw)
    return base


def _preflight(atuais_por_ad: dict[str, dict[str, Any]]) -> AsyncMock:
    async def _fake(**kwargs: Any) -> None:
        kwargs["atuais"].update(atuais_por_ad)
        return None

    return AsyncMock(side_effect=_fake)


async def _rodar(updates: list[dict[str, Any]], atuais_por_ad: dict[str, dict[str, Any]]):
    from src.mcp.tools.update_rsa import update_rsa

    criar = AsyncMock(return_value="TOKEN1")
    with (
        patch(
            "src.mcp.tools.update_rsa.validate_existing_rsas_for_update",
            _preflight(atuais_por_ad),
        ),
        patch("src.mcp.tools._mutate_common.create_pending", criar),
        patch("src.mcp.tools._mutate_common.connection.get_pool") as mock_pool,
    ):
        mock_pool.return_value.acquire.return_value.__aenter__ = AsyncMock(return_value=None)
        mock_pool.return_value.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
        out = await update_rsa({"customer_id": "1234567890", "updates": updates})
    return out, criar


@pytest.mark.asyncio
async def test_lote_todo_igual_nao_emite_token(_ctx) -> None:
    ids = [str(100 + i) for i in range(27)]
    updates = [{"ad_id": a, "final_urls": ["https://x/a"]} for a in ids]
    atuais = {a: _atual(final_urls=["https://x/a"]) for a in ids}

    out, criar = await _rodar(updates, atuais)

    assert out["status"] == "no_changes"
    assert "confirmation_token" not in out
    criar.assert_not_called()
    assert len(out["sem_mudanca"]) == 27
    assert out["sem_mudanca"] == [{"ad_id": a, "campos": ["final_urls"]} for a in ids]


@pytest.mark.asyncio
async def test_lote_misto_token_so_com_os_diferentes(_ctx) -> None:
    updates = [{"ad_id": a, "final_urls": ["https://x/a"]} for a in ("1", "2", "3")]
    updates[1]["final_urls"] = ["https://x/NOVA"]
    atuais = {a: _atual(final_urls=["https://x/a"]) for a in ("1", "2", "3")}

    out, criar = await _rodar(updates, atuais)

    assert out["status"] == "dry_run"
    assert out["confirmation_token"] == "TOKEN1"
    payload = criar.call_args.kwargs["payload"]
    assert [u["ad_id"] for u in payload["updates"]] == ["2"]
    assert payload["__target_count__"] == 1
    assert {i["ad_id"] for i in out["sem_mudanca"]} == {"1", "3"}
    assert "2 de 3 sem mudanca" in out["blast_summary"]
    assert [i["ad_id"] for i in out["updates_preview"]] == ["2"]
    assert payload["__params_summary__"]["count"] == 1
    assert payload["__params_summary__"]["unique_ads"] == 1
    assert "2 de 3 sem mudanca" in criar.call_args.kwargs["blast_summary"]


@pytest.mark.asyncio
async def test_atual_nao_lido_fica_no_token(_ctx) -> None:
    out, criar = await _rodar(
        [{"ad_id": "1", "final_urls": ["https://x/a"]}],
        {"1": _atual(final_urls=None)},
    )

    assert out["status"] == "dry_run"
    assert [u["ad_id"] for u in criar.call_args.kwargs["payload"]["updates"]] == ["1"]
    assert "sem_mudanca" not in out


def test_string_igual_a_objeto_sem_pino() -> None:
    atuais = _atual(headlines=[("A", None), ("B", None), ("C", None)])
    assert campos_sem_mudanca({"headlines": ["A", {"text": "B"}, "C"]}, atuais) == ["headlines"]


def test_pino_diferente_mesmo_texto_e_mudanca() -> None:
    atuais = _atual(headlines=[("A", "HEADLINE_1")])
    assert campos_sem_mudanca({"headlines": ["A"], "remover_pinos": True}, atuais) is None


def test_ordem_diferente_de_url_e_mudanca() -> None:
    atuais = _atual(final_urls=["https://x/a", "https://x/b"])
    assert campos_sem_mudanca({"final_urls": ["https://x/b", "https://x/a"]}, atuais) is None
    assert (
        campos_sem_mudanca({"final_urls": ["https://x/a/"]}, _atual(final_urls=["https://x/a"]))
        is None
    )


def test_remover_pinos_nao_e_campo() -> None:
    atuais = _atual(headlines=[("A", None), ("B", None), ("C", None)])
    spec = {"headlines": ["A", "B", "C"], "remover_pinos": True}
    assert campos_sem_mudanca(spec, atuais) == ["headlines"]


def test_path_none_igual_vazio() -> None:
    assert campos_sem_mudanca({"path1": ""}, _atual(path1="")) == ["path1"]
    assert campos_sem_mudanca({"path1": None}, _atual(path1="")) == ["path1"]
    assert campos_sem_mudanca({"path1": "abc"}, _atual(path1="")) is None


def test_atuais_none_nao_e_igual() -> None:
    assert campos_sem_mudanca({"path1": ""}, None) is None


def _asset(text: str, pino: str = "UNSPECIFIED") -> SimpleNamespace:
    return SimpleNamespace(text=text, pinned_field=SimpleNamespace(name=pino))


def _row(headlines: list[Any], final_urls: list[str]) -> SimpleNamespace:
    rsa = SimpleNamespace(headlines=headlines, descriptions=[], path1="", path2="p2")
    ad = SimpleNamespace(
        id=7,
        type=SimpleNamespace(name="RESPONSIVE_SEARCH_AD"),
        system_managed_resource_source=SimpleNamespace(name="UNSPECIFIED"),
        responsive_search_ad=rsa,
        final_urls=final_urls,
    )
    return SimpleNamespace(
        ad_group_ad=SimpleNamespace(ad=ad),
        ad_group=SimpleNamespace(id=1, name="g", status=SimpleNamespace(name="ENABLED")),
        campaign=SimpleNamespace(
            id=2,
            name="c",
            advertising_channel_type=SimpleNamespace(name="SEARCH"),
        ),
    )


def test_formatter_lista_vazia_e_nao_lido() -> None:
    atuais = _format_rsa_preflight_row(_row([], []))["atuais"]
    assert atuais["final_urls"] is None
    assert atuais["headlines"] is None
    assert atuais["descriptions"] is None
    assert atuais["path2"] == "p2"


def test_formatter_le_texto_pino_e_urls() -> None:
    atuais = _format_rsa_preflight_row(
        _row([_asset("A", "HEADLINE_1"), _asset("B")], ["https://x/a"])
    )["atuais"]
    assert atuais["headlines"] == [("A", "HEADLINE_1"), ("B", None)]
    assert atuais["final_urls"] == ["https://x/a"]


def test_chave_desconhecida_no_update_e_mudanca() -> None:
    atuais = _atual(final_urls=["https://x/a"])
    assert campos_sem_mudanca({"final_urls": ["https://x/a"]}, atuais) == ["final_urls"]
    assert campos_sem_mudanca({"final_urls": ["https://x/a"], "campo_novo": "x"}, atuais) is None


def test_campos_mutaveis_batem_com_o_schema_do_update_rsa() -> None:
    from src.google_ads.rsa_textos import _CAMPOS_MUTAVEIS
    from src.mcp.tools.update_rsa import _MUTABLE_FIELDS, _SCHEMA

    props = set(_SCHEMA["properties"]["updates"]["items"]["properties"])
    assert set(_CAMPOS_MUTAVEIS) == props - {"ad_id", "remover_pinos"}
    assert set(_CAMPOS_MUTAVEIS) == set(_MUTABLE_FIELDS)


def test_nao_lido_falha_pela_assercao_nao_por_excecao() -> None:
    # `atuais` sem a chave: tem que ser "diferente", nao TypeError nem igual por acaso.
    assert campos_sem_mudanca({"final_urls": ["https://x/a"]}, _atual()) is None
    assert campos_sem_mudanca({"path1": ""}, {"final_urls": None}) is None


def test_descriptions_iguais_sao_sem_mudanca() -> None:
    atuais = _atual(descriptions=[("D1", "DESCRIPTION_1"), ("D2", None)])
    spec = {"descriptions": [{"text": "D1", "pinned_field": "DESCRIPTION_1"}, "D2"]}
    assert campos_sem_mudanca(spec, atuais) == ["descriptions"]


def test_formatter_le_pino_de_description() -> None:
    row = _row([_asset("A")], ["https://x/a"])
    row.ad_group_ad.ad.responsive_search_ad.descriptions = [
        _asset("D1", "DESCRIPTION_1"),
        _asset("D2"),
    ]
    atuais = _format_rsa_preflight_row(row)["atuais"]
    assert atuais["descriptions"] == [("D1", "DESCRIPTION_1"), ("D2", None)]


def test_pino_unknown_e_nao_lido() -> None:
    row = _row([_asset("A", "UNKNOWN"), _asset("B")], ["https://x/a"])
    atuais = _format_rsa_preflight_row(row)["atuais"]
    assert atuais["headlines"] is None
    assert campos_sem_mudanca({"headlines": ["A", "B", "C"]}, atuais) is None
