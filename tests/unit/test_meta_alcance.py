"""A sonda de alcance do system user e os três estados (F154, spec 2026-09-27 §3.1).

As assinaturas vêm da medição de 27/09 contra a Graph API real: CHUTE 07 lida (200) apesar de
ausente de `/me/adaccounts`; conta sem acesso e id inexistente → 403 `code 200`; token
inválido → 401 `code 190`.
"""

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
import respx

from src.meta_ads.alcance import Alcance, classificar_sonda, sondar_alcance

_BASE = "https://graph.facebook.com/v22.0"
_RECUSA = {
    "error": {
        "message": "(#200) Ad account owner has NOT grant ads_management or ads_read permission",
        "code": 200,
    }
}


@pytest.mark.parametrize(
    ("status", "corpo", "esperado"),
    [
        (200, {"data": [{"spend": "3.37"}]}, "le"),
        (200, {"data": []}, "le"),
        (403, _RECUSA, "recusa"),
        (401, {"error": {"code": 190, "message": "Invalid OAuth access token"}}, "nao_medido"),
        (400, {"error": {"code": 17, "message": "User request limit reached"}}, "nao_medido"),
        (429, None, "nao_medido"),
        (500, {"error": {"code": 1, "message": "An unknown error occurred"}}, "nao_medido"),
        (403, {"error": {"code": 10, "message": "Permission denied"}}, "nao_medido"),
        (403, "nao e json de erro", "nao_medido"),
    ],
)
def test_classificar_sonda(status: int, corpo: Any, esperado: str) -> None:
    assert classificar_sonda(status, corpo) == esperado


@pytest.mark.asyncio
@respx.mock
async def test_sondar_alcance_separa_os_tres_estados() -> None:
    lida = respx.get(f"{_BASE}/act_1/insights").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    respx.get(f"{_BASE}/act_2/insights").mock(return_value=httpx.Response(403, json=_RECUSA))
    respx.get(f"{_BASE}/act_3/insights").mock(
        return_value=httpx.Response(401, json={"error": {"code": 190}})
    )
    respx.get(f"{_BASE}/act_4/insights").mock(side_effect=httpx.ReadTimeout("pendurou"))

    async with httpx.AsyncClient() as http:
        alcance = await sondar_alcance(
            http,
            access_token="tok_su",
            contas=[
                ("act_1", "America/Sao_Paulo"),
                ("act_2", "America/Sao_Paulo"),
                ("act_3", None),
                ("act_4", "America/Sao_Paulo"),
            ],
            # 02h UTC de 27/09 = 23h de 26/09 em Sao Paulo: "ontem" da conta e 25/09.
            agora=datetime(2026, 9, 27, 2, 0, tzinfo=UTC),
        )

    assert alcance == Alcance(
        le=frozenset({"act_1"}),
        recusa=frozenset({"act_2"}),
        nao_medido=frozenset({"act_3", "act_4"}),
    )
    pedido = lida.calls.last.request
    assert pedido.headers["Authorization"] == "Bearer tok_su"
    assert "access_token" not in str(pedido.url)  # F82: token no header, nunca na URL
    assert '"since":"2026-09-25"' in pedido.url.params["time_range"]
    assert pedido.url.params["level"] == "account"
