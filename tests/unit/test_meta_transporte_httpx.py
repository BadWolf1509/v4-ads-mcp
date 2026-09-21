"""F190/varredura 21-09: o transporte Meta fala por header, com timeout e status real.

Tres achados da mesma varredura fecham aqui:

1. **Token na URL** — o SDK assa `access_token` na query de toda requisicao, sem
   opt-out. Com header auth ele nunca entra numa URL, e o vazamento fica
   impossivel POR CONSTRUCAO em vez de por vigilancia.
2. **Sem timeout** — `FacebookSession` guarda `timeout=None` e repassa a
   `requests`, que bloqueia indefinidamente. Como a chamada era offloadada com
   `run_blocking`, uma conexao pendurada prendia um slot do pool de threads do
   anyio — COMPARTILHADO com os cinco executores Google. Com httpx async nao ha
   thread para prender, e o timeout e explicito.
3. **`cast(dict)` que mente** — `FacebookResponse.json()` devolve o corpo CRU
   quando ele nao e JSON, e `is_success()` cai num teste de substring, entao uma
   pagina de erro HTML de intermediario passava como sucesso e virava
   `'str' object has no attribute 'get'` — apresentado ao gestor como falha
   PERMANENTE. Agora a forma e validada na borda, com o status no texto.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
import pytest


def _pool() -> MagicMock:
    conn = AsyncMock()
    pool = MagicMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=conn)
    cm.__aexit__ = AsyncMock(return_value=False)
    pool.acquire = MagicMock(return_value=cm)
    return pool


async def _rodar(handler: Any, **kwargs: Any) -> Any:
    """Roda o executor contra um transporte httpx falso (MockTransport)."""
    from src.meta_ads import reports

    transporte = httpx.MockTransport(handler)
    cliente_real = httpx.AsyncClient(transport=transporte, timeout=reports._TIMEOUT_GRAPH)

    with (
        patch.object(reports.httpx, "AsyncClient", MagicMock(return_value=cliente_real)),
        patch.object(
            reports.manager_meta_account_access,
            "can_manager_access",
            AsyncMock(return_value=True),
        ),
        patch.object(reports.connection, "get_pool", return_value=_pool()),
        patch.object(reports.audit_log, "record", AsyncMock(return_value=1)),
    ):
        return await reports.run_meta_graph_get(
            manager_id=uuid4(),
            session_id=uuid4(),
            ad_account_id="act_1",
            edge="/act_1/insights",
            params={"level": "campaign"},
            operation_name="meta_get_campaign_performance",
            **kwargs,
        )


@pytest.mark.asyncio
async def test_o_token_vai_no_header_e_nunca_na_url() -> None:
    """A invariante do F82, agora tambem no caminho que as 5 tools usam."""
    vistos: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        vistos.append(request)
        return httpx.Response(200, json={"data": [], "paging": {}})

    await _rodar(handler)

    assert len(vistos) == 1, "piso: sem requisicao nao ha o que afirmar"
    req = vistos[0]
    assert "access_token" not in str(req.url), (
        f"o token foi para a URL: {req.url}. A invariante do F82 diz header, "
        "nunca query — quem le a URL num log contorna o gate de acesso."
    )
    assert req.headers.get("authorization", "").startswith("Bearer "), (
        "a autenticacao tem de ir no header Authorization"
    )


@pytest.mark.asyncio
async def test_o_cliente_e_construido_com_timeout() -> None:
    """Falha contra `timeout=None`, que e o default do SDK que saiu daqui.

    Fix round 1 (achado A da revisao): a versao anterior so lia a constante
    `reports._TIMEOUT_GRAPH` — isso passa verde mesmo se a producao PARAR de
    repassar o timeout pro `httpx.AsyncClient(...)` de verdade, porque nos
    testes o `AsyncClient` e um `MagicMock` que ignora kwargs (a constante
    existir nao prova que ela chega na construcao). Agora captura a FABRICA
    e afirma o kwarg que `run_meta_graph_get` de fato passou.
    """
    from src.meta_ads import reports

    assert reports._TIMEOUT_GRAPH is not None
    assert reports._TIMEOUT_GRAPH > 0, (
        "sem timeout, uma conexao pendurada fica pendurada para sempre"
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [], "paging": {}})

    transporte = httpx.MockTransport(handler)
    cliente_real = httpx.AsyncClient(transport=transporte, timeout=reports._TIMEOUT_GRAPH)
    fabrica = MagicMock(return_value=cliente_real)

    with (
        patch.object(reports.httpx, "AsyncClient", fabrica),
        patch.object(
            reports.manager_meta_account_access,
            "can_manager_access",
            AsyncMock(return_value=True),
        ),
        patch.object(reports.connection, "get_pool", return_value=_pool()),
        patch.object(reports.audit_log, "record", AsyncMock(return_value=1)),
    ):
        await reports.run_meta_graph_get(
            manager_id=uuid4(),
            session_id=uuid4(),
            ad_account_id="act_1",
            edge="/act_1/insights",
            params={"level": "campaign"},
            operation_name="meta_get_campaign_performance",
        )

    assert fabrica.call_args.kwargs.get("timeout"), (
        "o AsyncClient foi construido SEM timeout — a constante existir nao "
        "prova que ela chega na construcao"
    )


@pytest.mark.asyncio
async def test_corpo_nao_json_levanta_erro_nomeado_com_o_status() -> None:
    """Pagina HTML de intermediario nao pode virar AttributeError.

    Antes: `cast(dict, resposta.json())` — o cast e no-op em runtime, o corpo cru
    (str) seguia, e `corpo.get("data")` estourava com
    `'str' object has no attribute 'get'`, marcado como retryable=False.
    """

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="<html><body>Bad Gateway</body></html>")

    with pytest.raises(Exception) as capturado:
        await _rodar(handler)

    texto = getattr(capturado.value, "message", str(capturado.value))
    assert "502" in texto, f"o status HTTP tem de aparecer na mensagem; veio: {texto!r}"
    assert "attribute" not in texto.lower(), (
        f"vazou erro de atributo em vez de erro nomeado: {texto!r}"
    )


@pytest.mark.asyncio
async def test_erro_5xx_e_marcado_retryable() -> None:
    """Falha transitoria de upstream nao pode ser apresentada como permanente."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="Service Unavailable")

    with pytest.raises(Exception) as capturado:
        await _rodar(handler)

    assert getattr(capturado.value, "retryable", False) is True, (
        "5xx e transitorio; marca-lo permanente faz o gestor desistir de uma "
        "chamada que funcionaria em 30 segundos"
    )


@pytest.mark.asyncio
async def test_erro_4xx_nao_e_retryable() -> None:
    """Controle do teste irmao: se tudo fosse retryable, a assercao dele nao valeria."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "bad", "code": 100}})

    with pytest.raises(Exception) as capturado:
        await _rodar(handler)

    assert getattr(capturado.value, "retryable", True) is False
