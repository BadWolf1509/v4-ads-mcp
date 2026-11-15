"""apply_change de remove_ad (S3): o pos-check rele o status de cada anuncio.

O Google aceita operacao e pode nao executa-la (F184): a releitura diz se o anuncio
ficou REMOVED. O veredito vai em `conferencia` na linha; `efeito` e `changed_count`
seguem o ACK do Google (decisao "Campo proprio"). Releitura quebrada nao transforma
sucesso de escrita em erro (F83/F91).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from src.google_ads.queries.remover_anuncio import anuncios_query, parse_anuncio_row
from src.governance.blast_radius import RiskLevel, classify
from src.mcp.tools import apply_change as mod
from tests.unit.fixtures.fake_pool import FakePool
from tests.unit.test_remove_ad import linha_de_anuncio

pytestmark = pytest.mark.usefixtures("ctx_mcp")


_CID = "7862230676"
_DIVERGE = (
    "releitura diverge do pedido: possivel operacao aceita sem executar (F184), leitura "
    "defasada ou mudanca concorrente"
)


class _Log:
    def __init__(self) -> None:
        self.eventos: list[tuple[str, dict[str, Any]]] = []

    def warning(self, evento: str, **kw: Any) -> None:
        self.eventos.append((evento, kw))


def _saved() -> SimpleNamespace:
    return SimpleNamespace(
        operation_type="remove_ad",
        customer_id=_CID,
        blast_summary="x",
        payload={
            "ads": [{"ad_group_id": "100", "ad_id": "11"}],
            "__target_count__": 1,
            "__partial_failure__": True,
            "__params_summary__": {"count": 1, "ad_ids": ["11"]},
        },
    )


def _mutacao() -> dict[str, Any]:
    return {
        "provider_request_id": "req-1",
        "applied_count": 1,
        "changed_count": 1,
        "resource_names": [f"customers/{_CID}/adGroupAds/100~11"],
        "partial_failures": [{"index": 0, "status": "success", "error": None, "efeito": "mudou"}],
        "motivos_medidos": True,
    }


def _wire(
    monkeypatch,
    *,
    saved,
    releitura: list[str | None] | None = None,
    explode: bool = False,
) -> dict[str, Any]:
    cap: dict[str, Any] = {"queries": [], "mutou": False}

    async def _consume(conn, *, token, session_id):
        return saved

    async def _run_mutation(**kwargs: Any):
        cap["mutou"] = True
        cap["mutation_kwargs"] = kwargs
        return _mutacao()

    async def _run_report(**kwargs: Any):
        cap["queries"].append(kwargs["query"])
        assert kwargs["row_formatter"] is parse_anuncio_row
        if explode:
            raise RuntimeError("boom")
        fmt = kwargs["row_formatter"]
        return [
            fmt(linha_de_anuncio(kwargs["query"], ad_id="11", ad_group_id="100", status=s))
            for s in (releitura or [])
        ]

    monkeypatch.setattr(mod, "consume", _consume)
    monkeypatch.setattr(mod, "run_mutation", _run_mutation)
    monkeypatch.setattr(mod, "run_report", _run_report)
    monkeypatch.setattr(mod.connection, "get_pool", lambda: FakePool())
    return cap


@pytest.mark.asyncio
async def test_releitura_removed_confere(monkeypatch) -> None:
    cap = _wire(monkeypatch, saved=_saved(), releitura=["REMOVED"])
    out = await mod.apply_change({"confirmation_token": "ABCDEFGH"})
    assert out["status"] == "applied" and out["applied_count"] == 1
    linha = out["partial_failures"][0]
    assert linha["efeito"] == "mudou"
    assert linha["conferencia"] == {
        "campo": "status",
        "pedido": "REMOVED",
        "relido": "REMOVED",
        "motivo": "confere",
    }
    assert out["confirmation_error"] is None
    assert cap["queries"] == [anuncios_query(["11"])]
    assert cap["mutation_kwargs"]["partial_failure"] is True
    assert cap["mutation_kwargs"]["params_summary"] == {"count": 1, "ad_ids": ["11"]}


@pytest.mark.asyncio
async def test_releitura_enabled_diverge_sem_rebaixar_o_ack(monkeypatch) -> None:
    log = _Log()
    monkeypatch.setattr(mod, "log", log)
    _wire(monkeypatch, saved=_saved(), releitura=["ENABLED"])
    out = await mod.apply_change({"confirmation_token": "ABCDEFGH"})
    assert out["status"] == "applied"
    linha = out["partial_failures"][0]
    # efeito e changed_count sao o ACK do Google e batem com o audit
    assert linha["efeito"] == "mudou"
    assert out["changed_count"] == 1
    assert linha["status"] == "success"
    assert linha["conferencia"] == {
        "campo": "status",
        "pedido": "REMOVED",
        "relido": "ENABLED",
        "motivo": _DIVERGE,
    }
    assert log.eventos == [
        (
            "conferencia_pos_write_divergiu",
            {"operation_type": "remove_ad", "customer_id": _CID, "campo": "status"},
        )
    ]


@pytest.mark.asyncio
async def test_releitura_sem_a_linha_nao_confere(monkeypatch) -> None:
    _wire(monkeypatch, saved=_saved(), releitura=[])
    out = await mod.apply_change({"confirmation_token": "ABCDEFGH"})
    assert out["status"] == "applied"
    assert out["partial_failures"][0]["efeito"] == "mudou"
    assert out["partial_failures"][0]["conferencia"] is None
    assert out["confirmation_error"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("relido", [None, "UNKNOWN"])
async def test_status_nao_lido_nao_confere(monkeypatch, relido) -> None:
    _wire(monkeypatch, saved=_saved(), releitura=[relido])
    out = await mod.apply_change({"confirmation_token": "ABCDEFGH"})
    assert out["status"] == "applied"
    assert out["partial_failures"][0]["conferencia"] is None
    assert out["changed_count"] == 1


@pytest.mark.asyncio
async def test_releitura_que_levanta_preserva_sucesso(monkeypatch) -> None:
    _wire(monkeypatch, saved=_saved(), explode=True)
    out = await mod.apply_change({"confirmation_token": "ABCDEFGH"})
    assert out["status"] == "applied" and out["provider_request_id"] == "req-1"
    assert "RuntimeError" in out["confirmation_error"]
    assert out["partial_failures"][0]["efeito"] == "mudou"
    assert out["partial_failures"][0]["conferencia"] is None


@pytest.mark.asyncio
async def test_payload_ruim_levanta_antes_da_escrita(monkeypatch) -> None:
    saved = _saved()
    saved.payload["ads"] = [{"ad_group_id": "100", "ad_id": "11 OR 1=1"}]
    cap = _wire(monkeypatch, saved=saved, releitura=["REMOVED"])
    with pytest.raises(ValueError):
        await mod.apply_change({"confirmation_token": "ABCDEFGH"})
    assert cap["mutou"] is False


def test_classify_confirm_fixo() -> None:
    assert classify(operation="remove_ad", params={"target_count": 1}).level == RiskLevel.CONFIRM
    for n in (0, 1, 5, 20, 100):
        r = classify(operation="remove_ad", params={"target_count": n})
        assert r.level is RiskLevel.CONFIRM
        assert "irreversivel" in r.reason
        assert "unknown operation" not in r.reason


# --------------------------------------------------------------------------- #
# Lote: cada linha recebe a conferencia do SEU anuncio (revisao I1)
# --------------------------------------------------------------------------- #
_ADS_DO_LOTE = [
    {"ad_group_id": "100", "ad_id": "11"},
    {"ad_group_id": "200", "ad_id": "22"},
    {"ad_group_id": "300", "ad_id": "33"},
]


def _wire_lote(
    monkeypatch,
    *,
    ads: list[dict[str, str]],
    linhas: list[dict[str, Any]],
    releitura: list[tuple[str, str, str]],
) -> dict[str, Any]:
    """`releitura`: (ad_id, ad_group_id, status), na ordem em que o Google devolve."""
    saved = SimpleNamespace(
        operation_type="remove_ad",
        customer_id=_CID,
        blast_summary="x",
        payload={
            "ads": ads,
            "__target_count__": len(ads),
            "__partial_failure__": True,
            "__params_summary__": {"count": len(ads), "ad_ids": [a["ad_id"] for a in ads]},
        },
    )
    cap: dict[str, Any] = {"queries": []}

    async def _consume(conn, *, token, session_id):
        return saved

    async def _run_mutation(**kwargs: Any):
        ok = [pf for pf in linhas if pf["status"] == "success"]
        return {
            "provider_request_id": "req-1",
            "applied_count": len(ok),
            "changed_count": len(ok),
            "resource_names": [],
            "partial_failures": linhas,
            "motivos_medidos": True,
        }

    async def _run_report(**kwargs: Any):
        cap["queries"].append(kwargs["query"])
        fmt = kwargs["row_formatter"]
        return [
            fmt(linha_de_anuncio(kwargs["query"], ad_id=ad, ad_group_id=ag, status=s))
            for ad, ag, s in releitura
        ]

    monkeypatch.setattr(mod, "consume", _consume)
    monkeypatch.setattr(mod, "run_mutation", _run_mutation)
    monkeypatch.setattr(mod, "run_report", _run_report)
    monkeypatch.setattr(mod.connection, "get_pool", lambda: FakePool())
    return cap


@pytest.mark.asyncio
async def test_lote_cada_linha_confere_o_seu_anuncio(monkeypatch) -> None:
    """Tres anuncios, releitura FORA de ordem e com status distintos, falha no meio.

    Pega: conferencia gravada sempre no indice 0; a mesma conferencia em todas as
    linhas (a forma do molde `_AssinaturaRecomendacao`, que tem um item so); e a
    releitura casada por posicao em vez de `(ad_group_id, ad_id)`.
    """
    log = _Log()
    monkeypatch.setattr(mod, "log", log)
    _wire_lote(
        monkeypatch,
        ads=_ADS_DO_LOTE,
        linhas=[
            {"index": 0, "status": "success", "error": None, "efeito": "mudou"},
            {"index": 1, "status": "failed", "error": "recusada", "efeito": None},
            {"index": 2, "status": "success", "error": None, "efeito": "mudou"},
        ],
        releitura=[("33", "300", "REMOVED"), ("11", "100", "ENABLED"), ("22", "200", "REMOVED")],
    )
    out = await mod.apply_change({"confirmation_token": "ABCDEFGH"})
    assert out["status"] == "applied"
    por_indice = {pf["index"]: pf for pf in out["partial_failures"]}
    # 11 ficou ENABLED: a linha dele diverge, e o ACK segue intocado
    assert por_indice[0]["conferencia"] == {
        "campo": "status",
        "pedido": "REMOVED",
        "relido": "ENABLED",
        "motivo": _DIVERGE,
    }
    assert por_indice[0]["efeito"] == "mudou"
    # a linha que falhou nao traz conferencia
    assert por_indice[1]["conferencia"] is None
    assert por_indice[1]["status"] == "failed"
    # 33 saiu: a linha dele confere
    assert por_indice[2]["conferencia"] == {
        "campo": "status",
        "pedido": "REMOVED",
        "relido": "REMOVED",
        "motivo": "confere",
    }
    assert {s["ad_id"]: s["status"] for s in out["status_resultante"]} == {
        "11": "ENABLED",
        "22": "REMOVED",
        "33": "REMOVED",
    }
    assert [e for e, _ in log.eventos] == ["conferencia_pos_write_divergiu"]


@pytest.mark.asyncio
async def test_linha_que_falhou_nao_loga_divergencia(monkeypatch) -> None:
    """Op recusada e anuncio ainda ENABLED e falha parcial, nao F184: sem evento."""
    log = _Log()
    monkeypatch.setattr(mod, "log", log)
    _wire_lote(
        monkeypatch,
        ads=_ADS_DO_LOTE[:2],
        linhas=[
            {"index": 0, "status": "success", "error": None, "efeito": "mudou"},
            {"index": 1, "status": "failed", "error": "recusada", "efeito": None},
        ],
        releitura=[("11", "100", "REMOVED"), ("22", "200", "ENABLED")],
    )
    out = await mod.apply_change({"confirmation_token": "ABCDEFGH"})
    assert out["status"] == "applied"
    assert out["partial_failures"][1]["conferencia"] is None
    assert log.eventos == []
