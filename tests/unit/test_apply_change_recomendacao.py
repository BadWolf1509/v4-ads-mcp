"""apply_change de apply_recommendation: recheck do valor antes de aplicar (I3).

**O defeito.** A operacao do `RecommendationService` viaja SO com o
`resource_name` — nenhum parametro. Quem resolve o valor da recomendacao e o
Google, no instante do apply. Entre o preview e a confirmacao passam ate 10
minutos (o TTL do token), e nesse intervalo o Google pode revisar a
recomendacao: o `blast_summary` reexibido aqui diria "R$ 50,00 -> R$ 180,00"
enquanto outro numero aterrissa — o que anula o motivo de mostrar o numero.

**RECUSA, nao "aplica avisando".** Este e o caminho que o gestor percorre DEPOIS
de ter lido e aceito um numero: consentimento dado a R$ 180 nao cobre R$ 300, e
aviso emitido junto da resposta chega com a escrita ja feita — nao e decisao, e
notificacao. O caminho de volta custa uma chamada, e a recomendacao continua
pendente.

Espelha o `update_ad_schedule` (Ruling 10, concorrencia otimista) 40 linhas
abaixo no mesmo arquivo.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from src.mcp.tools import apply_change as mod

_CUSTOMER = "1234567890"
_REC_RN = f"customers/{_CUSTOMER}/recommendations/abc"


@pytest.fixture(autouse=True)
def _ctx() -> Any:
    from src.mcp.context import McpRequestContext, clear_current, set_current

    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    yield
    clear_current()


class _FakeConn:
    async def __aenter__(self) -> _FakeConn:
        return self

    async def __aexit__(self, *a: Any) -> bool:
        return False


class _FakePool:
    def acquire(self) -> _FakeConn:
        return _FakeConn()


def _impressao(**over: Any) -> dict[str, Any]:
    """O que o preview gravou no token — ja no formato que atravessa o JSONB."""
    base: dict[str, Any] = {
        "type": "CAMPAIGN_BUDGET",
        "current_amount_brl": 50.0,
        "recommended_amount_brl": 180.0,
        "valores": {},
    }
    base.update(over)
    return base


def _saved(payload: dict[str, Any] | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        operation_type="apply_recommendation",
        customer_id=_CUSTOMER,
        blast_summary="Aplicar recomendacao CAMPAIGN_BUDGET: R$ 50.00 -> R$ 180.00.",
        payload=(
            {
                "recommendation_resource_name": _REC_RN,
                "__target_count__": 1,
                "valores_do_preview": _impressao(),
            }
            if payload is None
            else payload
        ),
    )


def _wire(
    monkeypatch: pytest.MonkeyPatch,
    *,
    saved: SimpleNamespace,
    agora: dict[str, Any] | None = None,
    sem_linhas: bool = False,
) -> dict[str, Any]:
    """`agora` e o que a reconsulta ve no Google; `None` reusa a impressao do token."""
    visto: dict[str, Any] = {"aplicou": False, "queries": []}

    async def _consume(conn: Any, *, token: str, session_id: Any) -> SimpleNamespace:
        return saved

    async def _run_report(**kwargs: Any) -> list[dict[str, Any]]:
        visto["queries"].append(kwargs["query"])
        if sem_linhas:
            return []
        impressao = agora if agora is not None else saved.payload["valores_do_preview"]
        # `parse_recommendation_detail_row` devolve mais chaves do que o
        # fingerprint le. O fake devolve o formato COMPLETO do parser de
        # proposito: se o fingerprint passar a olhar outra chave, este fake
        # continua realista em vez de esconder a mudanca.
        return [
            {
                "resource_name": _REC_RN,
                "type": impressao["type"],
                "type_pt": None,
                "campaign_resource_name": "",
                "campaign_id": None,
                "current_amount_brl": impressao["current_amount_brl"],
                "recommended_amount_brl": impressao["recommended_amount_brl"],
                "valores": impressao["valores"],
            }
        ]

    async def _executar(**kwargs: Any) -> dict[str, Any]:
        visto["aplicou"] = True
        return {"applied_count": 1, "provider_request_id": "req-confirmado"}

    monkeypatch.setattr(mod, "consume", _consume)
    monkeypatch.setattr(mod, "run_report", _run_report)
    monkeypatch.setattr(mod, "run_recommendation_action", _executar)
    monkeypatch.setattr(mod.connection, "get_pool", lambda: _FakePool())
    return visto


@pytest.mark.asyncio
async def test_valor_igual_ao_do_preview_aplica(monkeypatch: pytest.MonkeyPatch) -> None:
    """Controle positivo: sem ele, um recheck que recusasse SEMPRE passaria verde."""
    visto = _wire(monkeypatch, saved=_saved())
    out = await mod.apply_change({"confirmation_token": "ABCDEFGH"})
    assert out["status"] == "applied"
    assert out["provider_request_id"] == "req-confirmado"
    assert visto["aplicou"] is True
    assert "FROM recommendation" in visto["queries"][0]


@pytest.mark.asyncio
async def test_valor_revisado_pelo_google_recusa_sem_aplicar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """O caso do enunciado: o preview prometeu R$ 180 e o Google agora quer R$ 300."""
    visto = _wire(monkeypatch, saved=_saved(), agora=_impressao(recommended_amount_brl=300.0))
    out = await mod.apply_change({"confirmation_token": "ABCDEFGH"})
    assert out["status"] == "error", "aplicou um valor que o gestor nunca leu"
    assert visto["aplicou"] is False, "recusou na resposta e mutou assim mesmo"
    # A mensagem tem que dizer O QUE mudou: "a recomendacao mudou" obriga o
    # gestor a refazer o preview so pra descobrir se a mudanca importa.
    assert "180.0 -> 300.0" in out["error_message"]
    assert "Nada foi aplicado" in out["error_message"]


@pytest.mark.asyncio
async def test_tipo_trocado_recusa(monkeypatch: pytest.MonkeyPatch) -> None:
    """O token autoriza UM tipo. Outro tipo no mesmo resource_name nao esta coberto."""
    visto = _wire(
        monkeypatch,
        saved=_saved(),
        agora=_impressao(type="FORECASTING_CAMPAIGN_BUDGET"),
    )
    out = await mod.apply_change({"confirmation_token": "ABCDEFGH"})
    assert out["status"] == "error"
    assert visto["aplicou"] is False
    assert "type: CAMPAIGN_BUDGET -> FORECASTING_CAMPAIGN_BUDGET" in out["error_message"]


@pytest.mark.asyncio
async def test_valor_secundario_revisado_tambem_recusa(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nem todo tipo tem `recommended_amount_brl`: ROAS e contagem vivem em `valores`.

    Um recheck que olhasse so os dois campos monetarios deixaria passar a revisao
    de um alvo de ROAS ou do orcamento exigido por USE_BROAD_MATCH_KEYWORD.
    """
    token = _saved()
    token.payload["valores_do_preview"] = _impressao(
        type="LOWER_TARGET_ROAS",
        current_amount_brl=None,
        recommended_amount_brl=None,
        valores={"target_roas_atual": 4.5, "multiplicador_recomendado": 1.35},
    )
    visto = _wire(
        monkeypatch,
        saved=token,
        agora=_impressao(
            type="LOWER_TARGET_ROAS",
            current_amount_brl=None,
            recommended_amount_brl=None,
            valores={"target_roas_atual": 4.5, "multiplicador_recomendado": 0.8},
        ),
    )
    out = await mod.apply_change({"confirmation_token": "ABCDEFGH"})
    assert out["status"] == "error"
    assert visto["aplicou"] is False
    assert "multiplicador_recomendado: 1.35 -> 0.8" in out["error_message"]


@pytest.mark.asyncio
async def test_recomendacao_que_sumiu_recusa_com_motivo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Aplicada ou dispensada por outra pessoa nos 10 minutos do TTL.

    Antes, isto ia ao Google e voltava com o erro opaco dele. Recusar aqui diz o
    que aconteceu e o que fazer.
    """
    visto = _wire(monkeypatch, saved=_saved(), sem_linhas=True)
    out = await mod.apply_change({"confirmation_token": "ABCDEFGH"})
    assert out["status"] == "error"
    assert visto["aplicou"] is False
    assert "nao esta mais pendente" in out["error_message"]


@pytest.mark.asyncio
async def test_token_sem_a_impressao_recusa(monkeypatch: pytest.MonkeyPatch) -> None:
    """Token emitido por uma revisao anterior ao recheck (deploy no meio do TTL).

    Nao e fallback calado: sem a impressao guardada nao ha o que comparar, e
    aplicar assim mesmo seria exatamente o buraco que este ramo fecha.
    """
    visto = _wire(
        monkeypatch,
        saved=_saved({"recommendation_resource_name": _REC_RN, "__target_count__": 1}),
    )
    out = await mod.apply_change({"confirmation_token": "ABCDEFGH"})
    assert out["status"] == "error"
    assert visto["aplicou"] is False
    assert visto["queries"] == [], "foi ao Google sem ter contra o que comparar"
    assert "versao anterior da tool" in out["error_message"]


@pytest.mark.asyncio
async def test_a_impressao_sobrevive_a_ida_e_volta_por_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """O payload atravessa JSONB, e tupla volta lista — a armadilha que o
    `schedule_fingerprint` ja documenta daria divergencia em TODO apply. Aqui o
    token passa por `json.dumps`/`json.loads` de verdade antes da comparacao."""
    import json

    token = _saved()
    token.payload = json.loads(json.dumps(token.payload))
    visto = _wire(monkeypatch, saved=token)
    out = await mod.apply_change({"confirmation_token": "ABCDEFGH"})
    assert out["status"] == "applied", f"divergencia falsa apos JSON: {out}"
    assert visto["aplicou"] is True
