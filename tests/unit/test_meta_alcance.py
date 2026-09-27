"""A sonda de alcance do system user e os três estados (F154, spec 2026-09-27 §3.1).

As assinaturas vêm da medição de 27/09 contra a Graph API real: CHUTE 07 lida (200) apesar de
ausente de `/me/adaccounts`; conta sem acesso e id inexistente → 403 `code 200`; token
inválido → 401 `code 190`.
"""

import asyncio
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
import respx

from src.meta_ads.alcance import (
    TIMEOUT_DA_SONDA,
    Alcance,
    classificar_sonda,
    sondar_alcance,
)

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
    # Revisao final da branch: o timeout da sonda chega ao pedido. Sem o `timeout=`, valeria
    # o do cliente (60 s no job) e 25 contas penduradas seriam 25 minutos.
    assert pedido.extensions["timeout"] == dict.fromkeys(
        ("connect", "read", "write", "pool"), TIMEOUT_DA_SONDA
    )


_AGORA = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_prazo_esgotado_deixa_a_conta_lenta_nao_medida() -> None:
    """Revisao final da branch: o laco tem prazo TOTAL.

    Ele roda com a conexao do job ja adquirida e ociosa, num job de 600 s. Sem prazo, uma
    conta pendurada segurava os dois pelo timeout inteiro de cada sonda, e o pior caso
    crescia com a parceria. A conta que nao coube no prazo sai como nao medida.
    """

    async def responder(pedido: httpx.Request) -> httpx.Response:
        if "act_lenta" in pedido.url.path:
            await asyncio.sleep(5)
        return httpx.Response(200, json={"data": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(responder)) as http:
        alcance = await sondar_alcance(
            http,
            access_token="tok_su",
            contas=[("act_rapida", "America/Sao_Paulo"), ("act_lenta", "America/Sao_Paulo")],
            agora=_AGORA,
            prazo=0.2,
        )

    assert alcance == Alcance(le=frozenset({"act_rapida"}), nao_medido=frozenset({"act_lenta"}))


@pytest.mark.asyncio
async def test_no_maximo_cinco_sondas_ao_mesmo_tempo() -> None:
    """Em paralelo, com teto. Em serie o pior caso e contas x 15 s; sem teto, a parceria
    inteira bate na Graph API de uma vez."""
    em_voo = 0
    pico = 0

    async def responder(_pedido: httpx.Request) -> httpx.Response:
        nonlocal em_voo, pico
        em_voo += 1
        pico = max(pico, em_voo)
        await asyncio.sleep(0.02)
        em_voo -= 1
        return httpx.Response(200, json={"data": []})

    contas: list[tuple[str, str | None]] = [(f"act_{n}", "America/Sao_Paulo") for n in range(12)]
    async with httpx.AsyncClient(transport=httpx.MockTransport(responder)) as http:
        alcance = await sondar_alcance(http, access_token="tok_su", contas=contas, agora=_AGORA)

    assert pico == 5
    assert alcance.le == frozenset(conta for conta, _ in contas)


@pytest.mark.asyncio
async def test_id_repetido_e_sondado_uma_vez() -> None:
    """Cada conta cai em exatamente um estado, que e o que `set_reachable` presume: duas
    sondas do mesmo id podiam responder diferente e por a conta em `le` e em `recusa`."""
    pedidos: list[str] = []

    async def responder(pedido: httpx.Request) -> httpx.Response:
        pedidos.append(pedido.url.path)
        return httpx.Response(200, json={"data": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(responder)) as http:
        alcance = await sondar_alcance(
            http,
            access_token="tok_su",
            contas=[("act_1", "America/Sao_Paulo"), ("act_1", "America/Sao_Paulo")],
            agora=_AGORA,
        )

    assert len(pedidos) == 1
    assert alcance == Alcance(le=frozenset({"act_1"}))
