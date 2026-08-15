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
