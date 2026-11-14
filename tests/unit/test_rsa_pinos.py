"""G2: `pinned_field` em create_rsa/update_rsa, com recusa de perda de pino.

Criterio de "perder pino" e por POSICAO (decisao do Wellington, 14/11): recusa so
quando uma posicao que hoje tem pino fica sem nenhum na lista nova. Reescrever o texto
mantendo a posicao segue. `remover_pinos` vale por update.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import jsonschema
import pytest
from google.ads.googleads.client import GoogleAdsClient
from google.oauth2.credentials import Credentials

from src.google_ads.mutates.ads import build_create_rsa, build_update_rsa
from src.google_ads.preflight import _format_rsa_preflight_row, validate_existing_rsas_for_update
from src.google_ads.queries.rsa_estado import parse_rsa_estado_row
from src.mcp.tools._rsa_textos import (
    ITEM_TEXTO,
    POSICOES_DESCRIPTION,
    POSICOES_HEADLINE,
    normalizar_textos,
    pinos_por_posicao,
    posicoes_perdidas,
    validar_textos,
)

# --- builder: proto real do SDK (offline; nenhuma chamada de rede) ----------------------

# Capturado em 14/11 no codigo PRE-G2 (base cf3c973), com o mesmo payload de
# `_PAYLOAD_*` abaixo: `type(op).serialize(op).hex()`. Item string tem que continuar
# produzindo EXATAMENTE estes bytes — e o contrato de retrocompatibilidade.
_GOLDEN_CREATE = (
    "0a6b0a6918022a43ca01260a04220248310a04220248320a04220248331204220244311204220244322a02"
    "703132027032ca021768747470733a2f2f6578656d706c6f2e636f6d2e62722f4a20637573746f6d6572"
    "732f313233343536373839302f616447726f7570732f3535"
)
_GOLDEN_UPDATE = (
    "8a03cd010a5eca01220a04220248310a04220248320a04220248331204220244311204220244322a0270"
    "31aa021c637573746f6d6572732f313233343536373839302f6164732f313030ca021768747470733a2f"
    "2f6578656d706c6f2e636f6d2e62722f126b0a1e726573706f6e736976655f7365617263685f61642e68"
    "6561646c696e65730a21726573706f6e736976655f7365617263685f61642e6465736372697074696f6e"
    "730a0a66696e616c5f75726c730a1a726573706f6e736976655f7365617263685f61642e7061746831"
)
_PAYLOAD_CREATE = {
    "rsas": [
        {
            "ad_group_id": "55",
            "headlines": ["H1", "H2", "H3"],
            "descriptions": ["D1", "D2"],
            "final_urls": ["https://exemplo.com.br/"],
            "path1": "p1",
            "path2": "p2",
            "status": "ENABLED",
        }
    ]
}
_PAYLOAD_UPDATE = {
    "updates": [
        {
            "ad_id": "100",
            "headlines": ["H1", "H2", "H3"],
            "descriptions": ["D1", "D2"],
            "final_urls": ["https://exemplo.com.br/"],
            "path1": "p1",
        }
    ]
}


@pytest.fixture(scope="module")
def sdk() -> GoogleAdsClient:
    # Cliente real so pelos tipos/enums/paths: sem chamada nenhuma, token falso.
    return GoogleAdsClient(
        credentials=Credentials(token="x"),
        developer_token="x",
        version="v25",
        use_proto_plus=True,
    )


def _hex(op: Any) -> str:
    return str(type(op).serialize(op).hex())


def test_item_string_payload_identico(sdk: GoogleAdsClient) -> None:
    [criar] = build_create_rsa(sdk, "1234567890", _PAYLOAD_CREATE)
    [atualizar] = build_update_rsa(sdk, "1234567890", _PAYLOAD_UPDATE)
    assert _hex(criar) == _GOLDEN_CREATE
    assert _hex(atualizar) == _GOLDEN_UPDATE


def test_item_objeto_seta_pinned_field(sdk: GoogleAdsClient) -> None:
    rsa = {
        **_PAYLOAD_CREATE["rsas"][0],
        "headlines": [{"text": "H1", "pinned_field": "HEADLINE_1"}, "H2", {"text": "H3"}],
        "descriptions": ["D1", {"text": "D2", "pinned_field": "DESCRIPTION_2"}],
    }
    [op] = build_create_rsa(sdk, "1234567890", {"rsas": [rsa]})
    ad = op.ad_group_ad_operation.create.ad.responsive_search_ad
    assert [h.pinned_field.name for h in ad.headlines] == [
        "HEADLINE_1",
        "UNSPECIFIED",
        "UNSPECIFIED",
    ]
    assert [h.text for h in ad.headlines] == ["H1", "H2", "H3"]
    assert [d.pinned_field.name for d in ad.descriptions] == ["UNSPECIFIED", "DESCRIPTION_2"]

    upd = {"ad_id": "100", "headlines": [{"text": "H1", "pinned_field": "HEADLINE_2"}, "H2", "H3"]}
    [op2] = build_update_rsa(sdk, "1234567890", {"updates": [upd]})
    assert op2.ad_operation.update.responsive_search_ad.headlines[0].pinned_field.name == (
        "HEADLINE_2"
    )


def test_objeto_sem_pino_e_identico_a_string(sdk: GoogleAdsClient) -> None:
    """`{text}` sem `pinned_field` = string: nao seta o campo (default UNSPECIFIED)."""
    rsa = {
        **_PAYLOAD_CREATE["rsas"][0],
        "headlines": [{"text": "H1"}, {"text": "H2", "pinned_field": None}, "H3"],
    }
    [op] = build_create_rsa(sdk, "1234567890", {"rsas": [rsa]})
    assert _hex(op) == _GOLDEN_CREATE


def test_builder_recusa_pino_de_outro_campo(sdk: GoogleAdsClient) -> None:
    """Headline pinada em DESCRIPTION_1: o schema barra, o builder publico tambem (F87)."""
    rsa = {
        **_PAYLOAD_CREATE["rsas"][0],
        "headlines": [{"text": "H1", "pinned_field": "DESCRIPTION_1"}, "H2", "H3"],
    }
    with pytest.raises(ValueError, match="DESCRIPTION_1"):
        build_create_rsa(sdk, "1234567890", {"rsas": [rsa]})


# --- normalizacao e criterio por posicao -----------------------------------------------


def test_normalizar_textos() -> None:
    assert normalizar_textos(["a", {"text": "b"}, {"text": "c", "pinned_field": "HEADLINE_1"}]) == [
        {"text": "a", "pinned_field": None},
        {"text": "b", "pinned_field": None},
        {"text": "c", "pinned_field": "HEADLINE_1"},
    ]


def test_pinos_por_posicao_mesmo_shape_da_releitura() -> None:
    itens = normalizar_textos(
        [
            {"text": "a", "pinned_field": "HEADLINE_1"},
            "b",
            {"text": "c", "pinned_field": "HEADLINE_1"},
        ]
    )
    assert pinos_por_posicao(itens) == {"HEADLINE_1": ["a", "c"]}
    assert pinos_por_posicao(normalizar_textos(["x", "y"])) == {}


def test_posicoes_perdidas_por_posicao_nao_por_texto() -> None:
    atuais = {"HEADLINE_1": ["A"], "HEADLINE_2": ["B"]}
    # Texto reescrito na mesma posicao nao e perda; posicao sem pino nenhum e.
    assert posicoes_perdidas(atuais, {"HEADLINE_1": ["Z"]}) == ["HEADLINE_2"]
    assert posicoes_perdidas(atuais, {"HEADLINE_1": ["A"], "HEADLINE_2": ["C"]}) == []
    assert posicoes_perdidas(atuais, {}) == ["HEADLINE_1", "HEADLINE_2"]
    assert posicoes_perdidas({}, {"HEADLINE_3": ["x"]}) == []


def test_item_do_schema_sem_type_e_com_descricao() -> None:
    """Sem `type` em array nem composicao: a regra mora no corpo da tool (3b.19B.1)."""
    for max_len, posicoes in ((30, POSICOES_HEADLINE), (90, POSICOES_DESCRIPTION)):
        item = ITEM_TEXTO(max_len, posicoes)
        assert "type" not in item
        assert not {"oneOf", "anyOf", "allOf"} & set(item)
        assert str(max_len) in item["description"]
        assert all(p in item["description"] for p in posicoes)
        # O schema deixa passar tudo; quem recusa e `validar_textos`.
        jsonschema.validate([7, {"x": 1}], {"type": "array", "items": item})


def test_validar_textos_aceita_as_duas_formas() -> None:
    spec = {
        "headlines": ["a", {"text": "b"}, {"text": "c", "pinned_field": "HEADLINE_3"}],
        "descriptions": ["d" * 90, {"text": "e", "pinned_field": "DESCRIPTION_2"}],
    }
    assert validar_textos(spec, "RSA 0") is None
    assert validar_textos({"final_urls": ["https://x"]}, "update 0") is None


@pytest.mark.parametrize(
    ("campo", "item", "trecho"),
    [
        ("headlines", "x" * 31, "30"),
        ("headlines", "", "1"),
        ("descriptions", "x" * 91, "90"),
        ("headlines", {"text": "x" * 31}, "30"),
        ("headlines", {"text": ""}, "1"),
        ("headlines", {"text": "c", "pino": "HEADLINE_1"}, "pino"),
        ("headlines", {"pinned_field": "HEADLINE_1"}, "text"),
        ("headlines", {"text": 5}, "text"),
        ("headlines", {"text": "c", "pinned_field": "DESCRIPTION_1"}, "DESCRIPTION_1"),
        ("descriptions", {"text": "c", "pinned_field": "HEADLINE_1"}, "HEADLINE_1"),
        ("headlines", {"text": "c", "pinned_field": None}, "pinned_field"),
        ("headlines", 7, "string"),
        ("headlines", None, "string"),
        ("headlines", ["a"], "string"),
    ],
)
def test_validar_textos_recusa(campo: str, item: Any, trecho: str) -> None:
    base = {"headlines": ["a", "b", "c"], "descriptions": ["d", "e"]}
    spec = {**base, campo: [*base[campo][:-1], item]}
    erro = validar_textos(spec, "RSA 3")
    assert erro is not None
    assert "RSA 3" in erro and campo in erro and trecho in erro
    # Posicao do item (indice 0-based) na mensagem, para o gestor achar o culpado.
    assert f"[{len(base[campo]) - 1}]" in erro


def test_schemas_registrados_usam_o_item() -> None:
    from src.mcp.tools.create_rsa import _SCHEMA as CREATE
    from src.mcp.tools.update_rsa import _SCHEMA as UPDATE

    c = CREATE["properties"]["rsas"]["items"]["properties"]
    u = UPDATE["properties"]["updates"]["items"]["properties"]
    for props in (c, u):
        assert props["headlines"]["items"] == ITEM_TEXTO(30, POSICOES_HEADLINE)
        assert props["descriptions"]["items"] == ITEM_TEXTO(90, POSICOES_DESCRIPTION)
    assert u["remover_pinos"] == {"type": "boolean", "default": False}
    assert "remover_pinos" not in c


# --- pre-flight do update_rsa -----------------------------------------------------------


def _linha(pinos: dict[str, list[str]] | None, ad_id: str = "100") -> dict[str, Any]:
    return {
        "ad_id": ad_id,
        "ad_type": "RESPONSIVE_SEARCH_AD",
        "system_managed_source": "UNSPECIFIED",
        "ad_group_id": "1",
        "ad_group_name": "AG1",
        "ad_group_status": "ENABLED",
        "campaign_id": "10",
        "campaign_name": "C1",
        "channel_type": "SEARCH",
        "pinos": pinos,
    }


async def _preflight(monkeypatch, linhas: list[dict[str, Any]], updates, **kw) -> str | None:
    capturado: dict[str, str] = {}

    async def fake_run_report(**kwargs: Any) -> list[dict[str, Any]]:
        capturado["query"] = kwargs["query"]
        return linhas

    monkeypatch.setattr("src.google_ads.preflight.run_report", fake_run_report)
    out = await validate_existing_rsas_for_update(
        manager_id=uuid4(),
        session_id=uuid4(),
        customer_id="1234567890",
        updates=updates,
        **kw,
    )
    _preflight.query = capturado.get("query")  # type: ignore[attr-defined]
    return out


@pytest.mark.asyncio
async def test_update_sem_pino_sobre_pinado_recusa(monkeypatch) -> None:
    out = await _preflight(
        monkeypatch,
        [_linha({"HEADLINE_1": ["A"]})],
        [{"ad_id": "100", "headlines": ["A", "B", "C"]}],
    )
    assert out is not None
    assert "HEADLINE_1" in out
    assert "remover_pinos" in out
    assert "100" in out
    # Erro pode ir para o audit: lista posicao, nao texto do anuncio.
    assert "'A'" not in out


@pytest.mark.asyncio
async def test_recusa_lista_todos_os_ads_que_perdem_pino(monkeypatch) -> None:
    out = await _preflight(
        monkeypatch,
        [_linha({"HEADLINE_1": ["A"]}, "100"), _linha({"DESCRIPTION_2": ["d"]}, "200")],
        [
            {"ad_id": "100", "headlines": ["A", "B", "C"]},
            {"ad_id": "200", "descriptions": ["d", "e"]},
        ],
    )
    assert out is not None
    assert "100" in out and "HEADLINE_1" in out
    assert "200" in out and "DESCRIPTION_2" in out


@pytest.mark.asyncio
async def test_reescrita_na_mesma_posicao_segue(monkeypatch) -> None:
    out = await _preflight(
        monkeypatch,
        [_linha({"HEADLINE_1": ["A"]})],
        [{"ad_id": "100", "headlines": [{"text": "Z", "pinned_field": "HEADLINE_1"}, "B", "C"]}],
    )
    assert out is None


@pytest.mark.asyncio
async def test_remover_pinos_true_segue(monkeypatch) -> None:
    out = await _preflight(
        monkeypatch,
        [_linha({"HEADLINE_1": ["A"]})],
        [{"ad_id": "100", "headlines": ["A", "B", "C"], "remover_pinos": True}],
    )
    assert out is None


@pytest.mark.asyncio
async def test_remover_pinos_vale_por_update(monkeypatch) -> None:
    out = await _preflight(
        monkeypatch,
        [_linha({"HEADLINE_1": ["A"]}, "100"), _linha({"HEADLINE_1": ["A"]}, "200")],
        [
            {"ad_id": "100", "headlines": ["A", "B", "C"], "remover_pinos": True},
            {"ad_id": "200", "headlines": ["A", "B", "C"]},
        ],
    )
    assert out is not None and "200" in out
    assert "Ad 100" not in out


@pytest.mark.asyncio
async def test_update_so_final_urls_nao_checa_pinos(monkeypatch) -> None:
    out = await _preflight(
        monkeypatch,
        [_linha({"HEADLINE_1": ["A"], "DESCRIPTION_1": ["d"]})],
        [{"ad_id": "100", "final_urls": ["https://exemplo.com.br/"]}],
    )
    assert out is None


@pytest.mark.asyncio
async def test_update_so_descriptions_nao_perde_pino_de_headline(monkeypatch) -> None:
    linhas = [_linha({"HEADLINE_1": ["A"], "DESCRIPTION_1": ["d"]})]
    ok = await _preflight(
        monkeypatch,
        linhas,
        [{"ad_id": "100", "descriptions": [{"text": "x", "pinned_field": "DESCRIPTION_1"}, "y"]}],
    )
    assert ok is None
    ruim = await _preflight(monkeypatch, linhas, [{"ad_id": "100", "descriptions": ["x", "y"]}])
    assert ruim is not None and "DESCRIPTION_1" in ruim and "HEADLINE_1" not in ruim


@pytest.mark.asyncio
async def test_pinos_nao_lidos_recusa_em_vez_de_assumir_zero(monkeypatch) -> None:
    """Sem a leitura dos pinos atuais nao da para garantir que nada se perde."""
    out = await _preflight(
        monkeypatch, [_linha(None)], [{"ad_id": "100", "headlines": ["A", "B", "C"]}]
    )
    assert out is not None and "remover_pinos" in out
    segue = await _preflight(
        monkeypatch,
        [_linha(None)],
        [{"ad_id": "100", "headlines": ["A", "B", "C"], "remover_pinos": True}],
    )
    assert segue is None


@pytest.mark.asyncio
async def test_query_do_preflight_pede_headlines_e_descriptions(monkeypatch) -> None:
    await _preflight(monkeypatch, [], [{"ad_id": "100", "path1": "x"}])
    q = _preflight.query  # type: ignore[attr-defined]
    assert "ad_group_ad.ad.responsive_search_ad.headlines" in q
    assert "ad_group_ad.ad.responsive_search_ad.descriptions" in q


@pytest.mark.asyncio
async def test_preflight_devolve_pinos_atuais_para_o_preview(monkeypatch) -> None:
    atuais: dict[str, Any] = {}
    await _preflight(
        monkeypatch,
        [_linha({"HEADLINE_1": ["A"]})],
        [{"ad_id": "100", "path1": "x"}],
        pinos_atuais=atuais,
    )
    assert atuais == {"100": {"HEADLINE_1": ["A"]}}


def _enum(nome: str) -> SimpleNamespace:
    return SimpleNamespace(name=nome)


def _row_proto(headlines: list[SimpleNamespace]) -> SimpleNamespace:
    return SimpleNamespace(
        ad_group_ad=SimpleNamespace(
            ad=SimpleNamespace(
                id=100,
                type=_enum("RESPONSIVE_SEARCH_AD"),
                system_managed_resource_source=_enum("UNSPECIFIED"),
                responsive_search_ad=SimpleNamespace(headlines=headlines, descriptions=[]),
            )
        ),
        ad_group=SimpleNamespace(id=1, name="AG1", status=_enum("ENABLED")),
        campaign=SimpleNamespace(id=10, name="C1", advertising_channel_type=_enum("SEARCH")),
    )


def test_formatter_do_preflight_le_pinos_e_unspecified_e_sem_pino() -> None:
    row = _row_proto(
        [
            SimpleNamespace(text="A", pinned_field=_enum("HEADLINE_1")),
            SimpleNamespace(text="B", pinned_field=_enum("UNSPECIFIED")),
        ]
    )
    assert _format_rsa_preflight_row(row)["pinos"] == {"HEADLINE_1": ["A"]}


def test_formatter_sem_headlines_e_nao_lido_nao_zero() -> None:
    """RSA tem >=3 headlines: lista vazia e campo nao lido, nunca 'sem pino' (F145)."""
    assert _format_rsa_preflight_row(_row_proto([]))["pinos"] is None


# --- tool: preview e audit -------------------------------------------------------------


@pytest.fixture
def _ctx():
    from src.mcp.context import McpRequestContext, clear_current, set_current

    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    yield
    clear_current()


def _pool_patch():
    p = patch("src.mcp.tools._mutate_common.connection.get_pool")
    return p


@pytest.mark.asyncio
async def test_preview_update_mostra_pinos_antes_depois_e_aviso(_ctx) -> None:
    from src.mcp.tools.update_rsa import update_rsa

    async def fake_preflight(**kwargs: Any) -> None:
        kwargs["pinos_atuais"]["100"] = {"HEADLINE_1": ["A"]}

    with (
        patch("src.mcp.tools.update_rsa.validate_existing_rsas_for_update", fake_preflight),
        patch("src.mcp.tools._mutate_common.create_pending", AsyncMock(return_value="T")),
        _pool_patch() as mock_pool,
    ):
        mock_pool.return_value.acquire.return_value.__aenter__ = AsyncMock(return_value=None)
        mock_pool.return_value.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
        out = await update_rsa(
            {
                "customer_id": "1234567890",
                "updates": [
                    {
                        "ad_id": "100",
                        "headlines": [{"text": "Z", "pinned_field": "HEADLINE_1"}, "B", "C"],
                    },
                    {"ad_id": "200", "path1": "x"},
                ],
            }
        )
    assert out["status"] == "dry_run"
    p0, p1 = out["updates_preview"]
    assert p0["pinos"] == {"antes": {"HEADLINE_1": ["A"]}, "depois": {"HEADLINE_1": ["Z"]}}
    assert "pinos" not in p1
    assert out["aviso_pinos"] == (
        "Pinar reduz a forca do anuncio: o Google tem menos combinacoes para testar."
    )


@pytest.mark.asyncio
async def test_preview_update_antes_nao_lido_e_none(_ctx) -> None:
    """Pre-flight mockado/sem leitura: `antes` e None (nao medido), nunca {}."""
    from src.mcp.tools.update_rsa import update_rsa

    with (
        patch(
            "src.mcp.tools.update_rsa.validate_existing_rsas_for_update",
            AsyncMock(return_value=None),
        ),
        patch("src.mcp.tools._mutate_common.create_pending", AsyncMock(return_value="T")),
        _pool_patch() as mock_pool,
    ):
        mock_pool.return_value.acquire.return_value.__aenter__ = AsyncMock(return_value=None)
        mock_pool.return_value.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
        out = await update_rsa(
            {"customer_id": "1234567890", "updates": [{"ad_id": "1", "headlines": ["a", "b", "c"]}]}
        )
    assert out["updates_preview"][0]["pinos"] == {"antes": None, "depois": {}}
    assert "aviso_pinos" not in out


@pytest.mark.asyncio
async def test_preview_create_mostra_pinos_e_aviso(_ctx) -> None:
    from src.mcp.tools.create_rsa import create_rsa

    with (
        patch(
            "src.mcp.tools.create_rsa.validate_parent_ad_groups_for_rsa_create",
            AsyncMock(return_value=None),
        ),
        patch("src.mcp.tools._mutate_common.create_pending", AsyncMock(return_value="T")),
        _pool_patch() as mock_pool,
    ):
        mock_pool.return_value.acquire.return_value.__aenter__ = AsyncMock(return_value=None)
        mock_pool.return_value.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
        out = await create_rsa(
            {
                "customer_id": "1234567890",
                "rsas": [
                    {
                        "ad_group_id": "5",
                        "headlines": [{"text": "A", "pinned_field": "HEADLINE_1"}, "B", "C"],
                        "descriptions": ["d", "e"],
                        "final_urls": ["https://exemplo.com.br/"],
                    }
                ],
            }
        )
    assert out["rsas_preview"][0]["pinos"] == {"HEADLINE_1": ["A"]}
    assert "Pinar reduz a forca" in out["aviso_pinos"]


def test_audit_sem_texto() -> None:
    from src.mcp.tools.create_rsa import _build_params_summary as resumo_create
    from src.mcp.tools.update_rsa import _build_params_summary as resumo_update

    rsas = [
        {
            "ad_group_id": "5",
            "headlines": [
                {"text": "TextoSecretoH1", "pinned_field": "HEADLINE_1"},
                "TextoSecretoH2",
                {"text": "TextoSecretoH3", "pinned_field": "HEADLINE_1"},
            ],
            "descriptions": [{"text": "TextoSecretoD1", "pinned_field": "DESCRIPTION_2"}, "x"],
            "final_urls": ["https://exemplo.com.br/"],
        }
    ]
    s = resumo_create(rsas)
    assert s["pinos_por_posicao_total"] == {"HEADLINE_1": 2, "DESCRIPTION_2": 1}
    assert "TextoSecreto" not in json.dumps(s)

    u = resumo_update(
        [
            {"ad_id": "1", "headlines": rsas[0]["headlines"], "remover_pinos": True},
            {"ad_id": "2", "path1": "x"},
        ]
    )
    assert u["pinos_por_posicao_total"] == {"HEADLINE_1": 2}
    assert "TextoSecreto" not in json.dumps(u)
    assert resumo_update([{"ad_id": "2", "path1": "x"}])["pinos_por_posicao_total"] == {}


# --- pos_check: pino pedido que nao pegou -----------------------------------------------


def _estado(ad_id: str, pinos: dict[str, list[str]], lidos: bool = True) -> dict[str, Any]:
    return {
        "ad_id": ad_id,
        "approval_status": None,
        "review_status": "REVIEW_IN_PROGRESS",
        "topicos": [],
        "assets_reprovados": [],
        "pinos": pinos,
        "pinos_lidos": lidos,
    }


def _wire(monkeypatch, *, op: str, payload: dict[str, Any], nomes: list[str], rows) -> None:
    from src.mcp.tools import apply_change as mod
    from tests.unit.fixtures.fake_pool import FakePool

    saved = SimpleNamespace(
        operation_type=op,
        customer_id="1234567890",
        blast_summary="x",
        payload={"__target_count__": len(nomes), "__partial_failure__": True, **payload},
    )

    async def _consume(conn, *, token, session_id):
        return saved

    async def _run_mutation(**kwargs: Any):
        return {
            "provider_request_id": "req-1",
            "applied_count": len(nomes),
            "changed_count": len(nomes),
            "resource_names": nomes,
            "partial_failures": [
                {"index": i, "status": "success", "efeito": "mudou"} for i in range(len(nomes))
            ],
        }

    async def _run_report(**kwargs: Any):
        assert kwargs["row_formatter"] is parse_rsa_estado_row
        return rows

    monkeypatch.setattr(mod, "consume", _consume)
    monkeypatch.setattr(mod, "run_mutation", _run_mutation)
    monkeypatch.setattr(mod, "run_report", _run_report)
    monkeypatch.setattr(mod.connection, "get_pool", lambda: FakePool())


async def _apply() -> dict[str, Any]:
    from src.mcp.tools import apply_change as mod

    return await mod.apply_change({"confirmation_token": "ABCDEFGH"})


_UPD_PINADO = {"ad_id": "1", "headlines": [{"text": "A", "pinned_field": "HEADLINE_1"}, "B", "C"]}

# Decisao do Wellington (revisao final, "Campo proprio"): o veredito da releitura vive em
# `conferencia`; `efeito`/`changed_count` sao o ACK do Google e batem com o audit.
_DIVERGE = (
    "releitura diverge do pedido: possivel operacao aceita sem executar (F184), leitura "
    "defasada ou mudanca concorrente"
)


class _Log:
    def __init__(self) -> None:
        self.eventos: list[tuple[str, dict[str, Any]]] = []

    def warning(self, evento: str, **kw: Any) -> None:
        self.eventos.append((evento, kw))


def _grava_log(monkeypatch) -> _Log:
    from src.mcp.tools import apply_change as mod

    log = _Log()
    monkeypatch.setattr(mod, "log", log)
    return log


@pytest.mark.asyncio
async def test_pino_nao_pegou_vai_em_conferencia(_ctx, monkeypatch) -> None:
    log = _grava_log(monkeypatch)
    _wire(
        monkeypatch,
        op="update_rsa",
        payload={"updates": [_UPD_PINADO, {"ad_id": "2", "path1": "x"}]},
        nomes=["customers/1234567890/ads/1", "customers/1234567890/ads/2"],
        rows=[_estado("1", {}), _estado("2", {})],
    )
    out = await _apply()
    l0, l1 = out["partial_failures"]
    # efeito e o ACK do Google: a releitura nao o rebaixa
    assert l0["efeito"] == "mudou" and l1["efeito"] == "mudou"
    assert out["changed_count"] == 2
    assert l0["conferencia"] == {
        "campo": "pinos",
        "pedido": {"HEADLINE_1": 1},
        "relido": {},
        "motivo": _DIVERGE,
    }
    assert l0["pinos_resultantes"] == {}
    # sem pino pedido, nada se comparou
    assert l1["conferencia"] is None and "pinos_resultantes" not in l1
    assert out["status"] == "applied"
    assert out["confirmation_error"] is None
    assert log.eventos == [
        (
            "conferencia_pos_write_divergiu",
            {"operation_type": "update_rsa", "customer_id": "1234567890", "campo": "pinos"},
        )
    ]


@pytest.mark.asyncio
async def test_pino_que_pegou_segue_mudou(_ctx, monkeypatch) -> None:
    log = _grava_log(monkeypatch)
    _wire(
        monkeypatch,
        op="update_rsa",
        payload={"updates": [_UPD_PINADO]},
        nomes=["customers/1234567890/ads/1"],
        # Pino de DESCRIPTION fora dos campos do update nao conta: o update nao mexeu nelas.
        rows=[_estado("1", {"HEADLINE_1": ["A"], "DESCRIPTION_1": ["d"]})],
    )
    out = await _apply()
    assert out["partial_failures"][0]["efeito"] == "mudou"
    assert out["partial_failures"][0]["conferencia"] == {
        "campo": "pinos",
        "pedido": {"HEADLINE_1": 1},
        "relido": {"HEADLINE_1": 1},
        "motivo": "confere",
    }
    assert "pinos_resultantes" not in out["partial_failures"][0]
    assert out["changed_count"] == 1
    assert log.eventos == []


@pytest.mark.asyncio
async def test_create_pino_nao_pegou_vai_em_conferencia(_ctx, monkeypatch) -> None:
    rsa = {
        "ad_group_id": "5",
        "headlines": ["A", "B", "C"],
        "descriptions": [{"text": "d", "pinned_field": "DESCRIPTION_2"}, "e"],
        "final_urls": ["https://exemplo.com.br/"],
    }
    _wire(
        monkeypatch,
        op="create_rsa",
        payload={"rsas": [rsa]},
        nomes=["customers/1234567890/adGroupAds/5~77"],
        rows=[_estado("77", {"DESCRIPTION_1": ["d"]})],
    )
    out = await _apply()
    linha = out["partial_failures"][0]
    assert linha["efeito"] == "mudou"
    assert out["changed_count"] == 1
    assert linha["conferencia"] == {
        "campo": "pinos",
        "pedido": {"DESCRIPTION_2": 1},
        "relido": {"DESCRIPTION_1": 1},
        "motivo": _DIVERGE,
    }
    assert linha["pinos_resultantes"] == {"DESCRIPTION_1": ["d"]}


@pytest.mark.asyncio
async def test_ad_ausente_ou_pinos_nao_lidos_nao_confere(_ctx, monkeypatch) -> None:
    """So a comparacao FEITA vira conferencia: ausencia e leitura vazia sao 'nao sei'."""
    _wire(
        monkeypatch,
        op="update_rsa",
        payload={"updates": [_UPD_PINADO, {**_UPD_PINADO, "ad_id": "2"}]},
        nomes=["customers/1234567890/ads/1", "customers/1234567890/ads/2"],
        rows=[_estado("2", {}, lidos=False)],
    )
    out = await _apply()
    assert [pf["efeito"] for pf in out["partial_failures"]] == ["mudou", "mudou"]
    assert [pf["conferencia"] for pf in out["partial_failures"]] == [None, None]
    assert out["changed_count"] == 2


@pytest.mark.asyncio
async def test_sem_pino_pedido_nao_compara(_ctx, monkeypatch) -> None:
    _wire(
        monkeypatch,
        op="update_rsa",
        payload={"updates": [{"ad_id": "1", "headlines": ["A", "B", "C"], "remover_pinos": True}]},
        nomes=["customers/1234567890/ads/1"],
        rows=[_estado("1", {"HEADLINE_1": ["A"]})],
    )
    out = await _apply()
    assert out["partial_failures"][0]["efeito"] == "mudou"
    assert out["partial_failures"][0]["conferencia"] is None


@pytest.mark.asyncio
async def test_comparacao_que_levanta_diz_que_pinos_nao_foram_conferidos(_ctx, monkeypatch) -> None:
    """Excecao DENTRO da comparacao: o sucesso fica de pe, nenhuma linha diz
    'confere', e `confirmation_error` diz que os pinos nao foram conferidos."""
    from src.google_ads import confirmadores

    def _explode(*a: Any, **k: Any) -> Any:
        raise RuntimeError("boom")

    monkeypatch.setattr(confirmadores, "_conferir_pinos", _explode)
    _wire(
        monkeypatch,
        op="update_rsa",
        payload={"updates": [_UPD_PINADO]},
        nomes=["customers/1234567890/ads/1"],
        rows=[_estado("1", {"HEADLINE_1": ["A"]})],
    )
    out = await _apply()
    assert out["status"] == "applied"
    assert out["partial_failures"][0]["efeito"] == "mudou"
    assert out["partial_failures"][0]["conferencia"] is None
    assert "pinos nao foram conferidos" in out["confirmation_error"]
    assert "RuntimeError" in out["confirmation_error"]
    # o estado de revisao, lido antes da comparacao, continua na resposta
    assert out["estado_revisao"][0]["ad_id"] == "1"


def test_parse_da_releitura_diz_se_leu_os_pinos() -> None:
    def row(headlines: list[Any]) -> SimpleNamespace:
        rsa = SimpleNamespace(headlines=headlines, descriptions=[])
        return SimpleNamespace(
            ad_group_ad=SimpleNamespace(
                ad=SimpleNamespace(id=9, responsive_search_ad=rsa), policy_summary=None
            )
        )

    h = SimpleNamespace(text="a", pinned_field=_enum("UNSPECIFIED"), policy_summary_info=None)
    assert parse_rsa_estado_row(row([h]))["pinos_lidos"] is True
    assert parse_rsa_estado_row(row([]))["pinos_lidos"] is False


# --- validacao no corpo da tool, ANTES do token ----------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "ruim",
    [
        "x" * 31,
        {"text": "c", "extra": 1},
        {"text": "c", "pinned_field": "DESCRIPTION_1"},
        7,
    ],
)
async def test_create_recusa_item_invalido_antes_do_token(_ctx, ruim: Any) -> None:
    from src.mcp.tools.create_rsa import create_rsa

    preflight = AsyncMock(return_value=None)
    pending = AsyncMock(return_value="T")
    with (
        patch("src.mcp.tools.create_rsa.validate_parent_ad_groups_for_rsa_create", preflight),
        patch("src.mcp.tools._mutate_common.create_pending", pending),
    ):
        out = await create_rsa(
            {
                "customer_id": "1234567890",
                "rsas": [
                    {
                        "ad_group_id": "5",
                        "headlines": ["A", "B", "C"],
                        "descriptions": ["d", "e"],
                        "final_urls": ["https://exemplo.com.br/"],
                    },
                    {
                        "ad_group_id": "6",
                        "headlines": ["A", "B", ruim],
                        "descriptions": ["d", "e"],
                        "final_urls": ["https://exemplo.com.br/"],
                    },
                ],
            }
        )
    assert out["status"] == "error"
    assert "ad_group 6" in out["error_message"] and "headlines[2]" in out["error_message"]
    pending.assert_not_awaited()
    preflight.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("campo", "ruim"),
    [
        ("descriptions", "x" * 91),
        ("headlines", {"text": "c", "extra": 1}),
        ("headlines", {"text": "c", "pinned_field": "DESCRIPTION_1"}),
        ("descriptions", 7),
    ],
)
async def test_update_recusa_item_invalido_antes_do_token(_ctx, campo: str, ruim: Any) -> None:
    from src.mcp.tools.update_rsa import update_rsa

    base = {"headlines": ["A", "B", "C"], "descriptions": ["d", "e"]}
    preflight = AsyncMock(return_value=None)
    pending = AsyncMock(return_value="T")
    with (
        patch("src.mcp.tools.update_rsa.validate_existing_rsas_for_update", preflight),
        patch("src.mcp.tools._mutate_common.create_pending", pending),
    ):
        out = await update_rsa(
            {
                "customer_id": "1234567890",
                "updates": [{"ad_id": "777", campo: [*base[campo][:-1], ruim]}],
            }
        )
    assert out["status"] == "error"
    assert "ad_id 777" in out["error_message"] and campo in out["error_message"]
    pending.assert_not_awaited()
    preflight.assert_not_awaited()
