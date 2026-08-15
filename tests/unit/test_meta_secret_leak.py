"""F82: segredo do Meta nao pode chegar ao Cloud Logging pela URL do request.

O httpx loga `request.url` INTEIRA — com query string — em `logger.info`
(`httpx/_client.py`, "HTTP Request: %s %s ..."). `configure_logging` chama
`basicConfig(level=info)` e nada silenciava o logger `httpx`, entao a URL caia
no stdout, que no Cloud Run e o Cloud Logging. O codigo Meta passava segredo em
`params=` (query string): `client_secret`, o app access token `app_id|app_secret`
e o token system-user all-targets.

Gravidade especifica deste projeto: o token system-user NAO expira e da acesso as
~19 contas do BM. No Modelo B a matriz de acesso e o unico freio e ela vive na
camada MCP — quem le o Cloud Logging contorna a matriz inteira sem passar por
gate nenhum.

Duas camadas cobertas aqui:
1. o logger do httpx nao emite INFO (mata a classe, inclusive pra call-sites
   que ainda carregam segredo na URL);
2. a troca short->long-lived manda o `client_secret` no CORPO, nao na URL.

O lado Google ja era correto e serve de referencia: `data=` no POST do token e
header `Authorization: Bearer` no userinfo — nada na URL.
"""

from __future__ import annotations

import logging

import httpx
import pytest
import respx

_FAKE_APP_SECRET = "s3cr3t-do-app-que-nao-pode-vazar"  # noqa: S105 — valor de teste
_FAKE_SHORT_TOKEN = "short-token-de-teste"  # noqa: S105 — valor de teste


def test_configure_logging_silencia_o_logger_do_httpx() -> None:
    """F82 camada 1: httpx nao pode emitir INFO — e nesse nivel que ele loga a URL."""
    from src.logging import configure_logging

    logging.getLogger("httpx").setLevel(logging.NOTSET)  # estado limpo
    configure_logging(level="info", json_output=True)

    # Nivel PROPRIO, nao o efetivo: o efetivo herda do root e passaria vazio
    # (basicConfig e no-op quando o root ja tem handler, como sob pytest). So um
    # setLevel explicito no logger `httpx` satisfaz este assert.
    assert logging.getLogger("httpx").level >= logging.WARNING, (
        "httpx loga a URL completa (com query string) em INFO — manter INFO ligado "
        "publica qualquer segredo que esteja em params= no Cloud Logging."
    )
    # httpcore so loga em DEBUG, mas LOG_LEVEL=debug e opcao real em config.py.
    assert logging.getLogger("httpcore").level >= logging.WARNING


def test_httpx_realmente_logaria_a_query_string_sem_o_silenciamento(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Prova que a ameaca e real: com INFO ligado, o segredo aparece no log record.

    Sem esta prova, o teste acima vira ritual — ninguem sabe se `httpx` de fato
    emite a URL. Aqui forcamos INFO e verificamos o vazamento.
    """
    logging.getLogger("httpx").setLevel(logging.INFO)
    try:
        with respx.mock:
            respx.get("https://graph.facebook.com/v22.0/oauth/access_token").mock(
                return_value=httpx.Response(200, json={"access_token": "x"})
            )
            with caplog.at_level(logging.INFO, logger="httpx"), httpx.Client() as client:
                client.get(
                    "https://graph.facebook.com/v22.0/oauth/access_token",
                    params={"client_secret": _FAKE_APP_SECRET},
                )
    finally:
        logging.getLogger("httpx").setLevel(logging.NOTSET)

    vazou = any(_FAKE_APP_SECRET in record.getMessage() for record in caplog.records)
    assert vazou, "premissa do F82 invalida: httpx nao esta logando a query string"


@pytest.mark.asyncio
async def test_troca_long_lived_nao_poe_client_secret_na_url() -> None:
    """F82 camada 2: o `client_secret` vai no corpo, nunca na query string.

    A troca code->short (mesmo endpoint, ja em producao) sempre usou POST com
    `data=`; a short->long-lived era o GET destoante.
    """
    from src.auth.meta_oauth import _exchange_for_long_lived_token

    with respx.mock:
        route = respx.post("https://graph.facebook.com/v22.0/oauth/access_token").mock(
            return_value=httpx.Response(200, json={"access_token": "long", "expires_in": 5184000})
        )
        async with httpx.AsyncClient() as http:
            resp = await _exchange_for_long_lived_token(
                http,
                app_id="123",
                app_secret=_FAKE_APP_SECRET,
                short_token=_FAKE_SHORT_TOKEN,
            )

    assert resp.status_code == 200
    request = route.calls[0].request
    url = str(request.url)
    assert _FAKE_APP_SECRET not in url, f"client_secret vazou na URL: {url}"
    assert _FAKE_SHORT_TOKEN not in url, f"fb_exchange_token vazou na URL: {url}"

    body = request.content.decode()
    assert _FAKE_APP_SECRET in body, "o secret precisa seguir no corpo — so mudou de lugar"
    assert "grant_type=fb_exchange_token" in body


# ---------------------------------------------------------------------------
# Camada 3 (2026-08-15): o token sai da URL e vai pro header `Authorization`.
#
# Probe empirica contra o Graph real ANTES de escrever isto (scripts/
# probe_meta_auth_header.py) — a licao F53/F54/F55 e nao mexer em superficie da
# API Meta por analogia. O que ela estabeleceu:
#
#   (B) `Authorization: Bearer <token>` devolve EXATAMENTE os mesmos dados que
#       `?access_token=` — migracao segura.
#   (D) autenticando por header, o Graph NAO embute mais o token no
#       `paging.next`. Otimo pro vazamento, mas vira requisito: o header tem
#       que ir em TODA pagina, senao a 2a volta 401.
#   (G) `/debug_token` NAO aceita POST (400, code 100 subcode 33), entao o
#       `input_token` continua na query — ele nao e credencial do chamador e
#       nao cabe no header. O que sai de la e o `app_id|app_secret`, que e o
#       segredo permanente.
# ---------------------------------------------------------------------------

_FAKE_SU_TOKEN = "system-user-token-que-nao-expira"  # noqa: S105 — valor de teste


@pytest.mark.asyncio
@respx.mock
async def test_adaccounts_manda_o_token_no_header_e_nao_na_url() -> None:
    """F82: o token system-user da acesso as ~19 contas do BM e NAO expira."""
    from src.auth.meta_oauth import META_GRAPH_BASE, _fetch_all_adaccounts

    rota = respx.get(f"{META_GRAPH_BASE}/me/adaccounts").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "act_1"}], "paging": {}})
    )

    async with httpx.AsyncClient() as http:
        resultado = await _fetch_all_adaccounts(http, _FAKE_SU_TOKEN)

    assert resultado.complete is True
    pedido = rota.calls[0].request
    assert pedido.headers.get("Authorization") == f"Bearer {_FAKE_SU_TOKEN}"
    assert _FAKE_SU_TOKEN not in str(pedido.url), "o token continua na query string"
    assert "access_token" not in str(pedido.url)


@pytest.mark.asyncio
@respx.mock
async def test_header_acompanha_a_paginacao_ate_o_fim() -> None:
    """F82 + (D): o `next` vem SEM token; sem o header a 2a pagina daria 401.

    Este e o teste que o probe tornou obrigatorio — antes dele eu ia reescrever
    a URL do `next` pra tirar o token, que e o oposto do que o Graph faz.
    """
    from src.auth.meta_oauth import META_GRAPH_BASE, _fetch_all_adaccounts

    proxima = f"{META_GRAPH_BASE}/me/adaccounts?after=cursor2&fields=id"
    respx.get(f"{META_GRAPH_BASE}/me/adaccounts").mock(
        side_effect=[
            httpx.Response(200, json={"data": [{"id": "act_1"}], "paging": {"next": proxima}}),
            httpx.Response(200, json={"data": [{"id": "act_2"}], "paging": {}}),
        ]
    )

    async with httpx.AsyncClient() as http:
        resultado = await _fetch_all_adaccounts(http, _FAKE_SU_TOKEN)

    assert [c["id"] for c in resultado.accounts] == ["act_1", "act_2"]
    assert resultado.complete is True
    assert len(respx.calls) == 2
    for chamada in respx.calls:
        assert chamada.request.headers.get("Authorization") == f"Bearer {_FAKE_SU_TOKEN}", (
            "alguma pagina foi pedida sem o header — o `next` do Graph nao "
            "carrega mais o token quando a autenticacao vem por header"
        )
        assert _FAKE_SU_TOKEN not in str(chamada.request.url)
