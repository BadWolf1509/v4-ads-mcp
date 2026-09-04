"""apply_change de update_ad_schedule: pre-flight de concorrencia otimista (Ruling 10),
mutacao com falha parcial reportada (§4.5) e reconsulta que assere por PRESENCA, nunca
por ausencia (§7/§4.6) — o ACK da mutacao nao basta, a UI falhou em silencio duas vezes
nessa conta."""

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


def _janela(day: str = "MONDAY", sh: int = 7, eh: int = 17) -> dict[str, Any]:
    return {
        "day_of_week": day,
        "start_hour": sh,
        "start_minute": 0,
        "end_hour": eh,
        "end_minute": 0,
    }


def _row(
    cid: str = "1",
    day: str = "MONDAY",
    sh: int = 7,
    eh: int = 17,
    crit: str = "9",
    status: str = "ENABLED",
    bm: float | None = None,
) -> dict[str, Any]:
    return {
        "campaign_id": cid,
        "campaign_name": "A",
        "criterion_id": crit,
        "resource_name": f"customers/1234567890/campaignCriteria/{cid}~{crit}",
        "day_of_week": day,
        "start_hour": sh,
        "start_minute": 0,
        "end_hour": eh,
        "end_minute": 0,
        "bid_modifier": bm,
        "status": status,
    }


def _saved(
    *,
    campaign_ids: tuple[str, ...] = ("1",),
    windows: list[dict[str, Any]] | None = None,
    current_keys: dict[str, list[list[Any]]] | None = None,
) -> SimpleNamespace:
    """Payload como ele volta do banco: JSON, entao tupla nenhuma — so listas."""
    return SimpleNamespace(
        operation_type="update_ad_schedule",
        customer_id="1234567890",
        blast_summary="x",
        payload={
            "campaign_ids": list(campaign_ids),
            "windows": [_janela()] if windows is None else windows,
            "current_keys": {"1": []} if current_keys is None else current_keys,
            "ops": [
                {
                    "kind": "add",
                    "campaign_id": "1",
                    "window": _janela(),
                    "bid_modifier": None,
                }
            ],
            "__target_count__": 1,
            "__partial_failure__": True,
        },
    )


_MUTACAO_OK: dict[str, Any] = {
    "provider_request_id": "req-1",
    "applied_count": 1,
    "changed_count": 1,
    "partial_failures": [],
    "resource_names": ["customers/1234567890/campaignCriteria/1~10"],
}


def _wire(
    monkeypatch,
    *,
    saved: SimpleNamespace,
    antes: list[dict[str, Any]],
    depois: list[dict[str, Any]] | None = None,
    mutacao: dict[str, Any] | None = None,
    depois_explode: bool = False,
) -> dict[str, list[Any]]:
    """Duas reconsultas, ambas FROM campaign_criterion: a de pre-flight (Ruling 10)
    filtra ENABLED, a de pos-apply nao filtra (status='all', §7). Despacha por isso."""
    visto: dict[str, list[Any]] = {"mutacoes": [], "queries": []}

    async def _consume(conn, *, token, session_id):
        return saved

    async def _run_mutation(**kwargs: Any):
        visto["mutacoes"].append(kwargs)
        return mutacao if mutacao is not None else _MUTACAO_OK

    async def _run_report(**kwargs: Any):
        q = kwargs["query"]
        visto["queries"].append(q)
        assert "FROM campaign_criterion" in q
        if "campaign_criterion.status = 'ENABLED'" in q:
            return antes
        if depois_explode:
            raise RuntimeError("boom")
        return depois if depois is not None else []

    monkeypatch.setattr(mod, "consume", _consume)
    monkeypatch.setattr(mod, "run_mutation", _run_mutation)
    monkeypatch.setattr(mod, "run_report", _run_report)
    monkeypatch.setattr(mod.connection, "get_pool", lambda: _FakePool())
    return visto


@pytest.mark.asyncio
async def test_apply_reconsulta_a_grade_e_devolve_resulting_schedule(monkeypatch) -> None:
    saved = _saved()
    _wire(monkeypatch, saved=saved, antes=[], depois=[_row(crit="10")])
    out = await mod.apply_change({"confirmation_token": "ABCDEFGH"})
    assert out["status"] == "applied" and out["applied_count"] == 1 and out["changed_count"] == 1
    rs = out["resulting_schedule"]["1"]
    assert rs["has_schedule"] is True and rs["hours_per_week"] == 10.0
    assert rs["windows"][0]["day_of_week"] == "MONDAY"
    assert out["confirmation_error"] is None


@pytest.mark.asyncio
async def test_reconsulta_que_falha_nao_apaga_o_resultado_da_mutacao(monkeypatch) -> None:
    """F83/F91: I/O depois de escrita ja aplicada nao pode virar erro."""
    saved = _saved()
    _wire(monkeypatch, saved=saved, antes=[], depois_explode=True)
    out = await mod.apply_change({"confirmation_token": "ABCDEFGH"})
    assert (
        out["status"] == "applied"
        and out["applied_count"] == 1
        and out["provider_request_id"] == "req-1"
    )
    assert out["resulting_schedule"] is None
    assert "reconsulta" in out["confirmation_error"].lower()


@pytest.mark.asyncio
async def test_falha_por_operacao_chega_na_resposta_com_o_motivo(monkeypatch) -> None:
    """Important 1 / spec §4.5: 'a resposta separa aplicadas de falhas, com o motivo de
    cada falha'. Falha por-op e provavel aqui: remove de criterio que alguem ja removeu
    dentro do TTL, add que bate no teto de schedules/dia do Google."""
    saved = _saved()
    falhas = [{"index": 0, "status": "failed", "error": "criterio ja removido"}]
    _wire(
        monkeypatch,
        saved=saved,
        antes=[],
        depois=[],
        mutacao={**_MUTACAO_OK, "applied_count": 0, "partial_failures": falhas},
    )
    out = await mod.apply_change({"confirmation_token": "ABCDEFGH"})
    assert out["partial_failures"] == falhas


@pytest.mark.asyncio
async def test_confirmacao_ve_a_linha_removed_e_bate_a_grade_pedida(monkeypatch) -> None:
    """Important 2 / spec §7: a reconsulta NAO pode filtrar ENABLED — janela removida
    tem que ser confirmada por PRESENCA de status REMOVED, nunca por nao aparecer."""
    saved = _saved(windows=[_janela("MONDAY")], current_keys={"1": [["SATURDAY", 7, 0, 17, 0]]})
    _wire(
        monkeypatch,
        saved=saved,
        antes=[_row(day="SATURDAY", crit="8")],
        depois=[_row(day="MONDAY", crit="10"), _row(day="SATURDAY", crit="8", status="REMOVED")],
    )
    out = await mod.apply_change({"confirmation_token": "ABCDEFGH"})
    rs = out["resulting_schedule"]["1"]
    assert rs["matches_requested"] is True
    assert [(w["day_of_week"], w["status"]) for w in rs["windows"]] == [
        ("MONDAY", "ENABLED"),
        ("SATURDAY", "REMOVED"),
    ], "a linha REMOVED tem que ser positivamente visivel"
    assert rs["hours_per_week"] == 10.0, "REMOVED nao conta horas servidas"


@pytest.mark.asyncio
async def test_grade_resultante_diferente_da_pedida_e_reportada(monkeypatch) -> None:
    """Uma janela a menos do que se pediu -> matches_requested False."""
    saved = _saved(windows=[_janela("MONDAY"), _janela("TUESDAY")])
    _wire(monkeypatch, saved=saved, antes=[], depois=[_row(day="MONDAY", crit="10")])
    out = await mod.apply_change({"confirmation_token": "ABCDEFGH"})
    assert out["resulting_schedule"]["1"]["matches_requested"] is False


@pytest.mark.asyncio
async def test_baseline_intacto_deixa_aplicar(monkeypatch) -> None:
    """Ruling 10: mesma grade do preview -> a mutacao sai normalmente."""
    saved = _saved(current_keys={"1": [["SATURDAY", 7, 0, 17, 0]]})
    visto = _wire(
        monkeypatch,
        saved=saved,
        antes=[_row(day="SATURDAY", crit="8")],
        depois=[_row(crit="10")],
    )
    out = await mod.apply_change({"confirmation_token": "ABCDEFGH"})
    assert out["status"] == "applied"
    assert len(visto["mutacoes"]) == 1


@pytest.mark.asyncio
async def test_grade_mudada_desde_o_preview_nao_muta(monkeypatch) -> None:
    """Ruling 10 (concorrencia otimista): o delta guardado carrega resource_names de ate
    10 min atras. Baseline mudado + partial_failure produz uma grade que nao e nem a
    antiga nem a pedida, em silencio. Asserto por CAPTURA da mutacao, nao por status."""
    saved = _saved(current_keys={"1": [["SATURDAY", 7, 0, 17, 0]]})
    visto = _wire(
        monkeypatch,
        saved=saved,
        antes=[_row(day="SUNDAY", crit="12")],
        depois=[_row(crit="10")],
    )
    out = await mod.apply_change({"confirmation_token": "ABCDEFGH"})
    assert visto["mutacoes"] == [], "nada pode ter sido mutado"
    assert out["status"] == "error" and "grade mudou" in out["error_message"].lower()
    assert "update_ad_schedule" in out["error_message"] or out["operation"] == "update_ad_schedule"
