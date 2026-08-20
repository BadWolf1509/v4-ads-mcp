"""O paginador e o unico lugar que sabe seguir paging.next — e o unico que
decide se a leitura ficou COMPLETA (F93)."""

import httpx
import pytest
import respx

from src.meta_ads.graph import fetch_paginated

URL = "https://graph.facebook.com/v22.0/x/edge"


@pytest.mark.asyncio
@respx.mock
async def test_segue_paging_next_e_marca_completo() -> None:
    # A rota com query no pattern precisa ser registrada ANTES da rota bare:
    # respx resolve rota ambigua por ordem de registro, nao por especificidade,
    # e um pattern sem query (`URL`) casa com QUALQUER querystring naquele path
    # — inclusive `?after=abc` (probado contra respx 0.23.1 instalado aqui).
    respx.get(f"{URL}?after=abc").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "2"}]})
    )
    respx.get(URL).mock(
        return_value=httpx.Response(
            200, json={"data": [{"id": "1"}], "paging": {"next": f"{URL}?after=abc"}}
        )
    )

    async with httpx.AsyncClient() as http:
        out = await fetch_paginated(http, URL, access_token="tok", params={"fields": "id"})

    assert [r["id"] for r in out.rows] == ["1", "2"]
    assert out.complete is True


@pytest.mark.asyncio
@respx.mock
async def test_pagina_que_falha_marca_incompleto_sem_perder_o_que_veio() -> None:
    # Mesmo motivo do teste acima: rota com query registrada primeiro.
    respx.get(f"{URL}?after=abc").mock(return_value=httpx.Response(500, json={"error": {}}))
    respx.get(URL).mock(
        return_value=httpx.Response(
            200, json={"data": [{"id": "1"}], "paging": {"next": f"{URL}?after=abc"}}
        )
    )

    async with httpx.AsyncClient() as http:
        out = await fetch_paginated(http, URL, access_token="tok", params={"fields": "id"})

    assert [r["id"] for r in out.rows] == ["1"]
    assert out.complete is False


@pytest.mark.asyncio
@respx.mock
async def test_token_vai_no_header_nunca_na_query() -> None:
    """F82: token em query string vaza em log de proxy."""
    rota = respx.get(URL).mock(return_value=httpx.Response(200, json={"data": []}))

    async with httpx.AsyncClient() as http:
        await fetch_paginated(http, URL, access_token="segredo", params={"fields": "id"})

    pedido = rota.calls[0].request
    assert pedido.headers["Authorization"] == "Bearer segredo"
    assert "segredo" not in str(pedido.url)
