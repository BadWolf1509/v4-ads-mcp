"""F86: chamada bloqueante do SDK Google nao pode rodar no event loop.

`search_stream`, `mutate`, `search` e `upload_click_conversions` sao chamadas
gRPC SINCRONAS, invocadas de dentro de `async def`. Enquanto uma delas roda, o
event loop da instancia inteira fica parado — e com `--concurrency=80` isso
serializa TODOS os requests daquela instancia.

O caso mais afiado e o `/health?deep=1`: o `asyncio.timeout(5)` que a F77
introduziu nem comeca a contar, porque o timer so dispara quando o loop volta a
girar. Ou seja, era um caminho pra 503 no uptime check SEM nenhum problema de
banco — algo que a investigacao da F77 nao tinha como distinguir do stale
connection que ela estava perseguindo.

## Por que o teste e assim

A forma obvia — medir o tempo e assertar que nenhuma pausa passou de X ms — e
instavel em CI ruidoso. Aqui a prova e DETERMINISTICA e nao depende de limiar:

o SDK falso bloqueia num `threading.Event` que so o lado ASYNC consegue liberar.
Se a chamada rodar no event loop, a corrotina que libera nunca executa e o
`wait` estoura por timeout. Se rodar numa thread, o loop segue girando, a
corrotina libera, e o `wait` retorna True. O booleano que o SDK falso registra E
a resposta: "o loop continuou vivo enquanto eu bloqueava?".
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


def _pool() -> MagicMock:
    conn = AsyncMock()
    txn = MagicMock()
    txn.__aenter__ = AsyncMock(return_value=None)
    txn.__aexit__ = AsyncMock(return_value=None)
    conn.transaction = MagicMock(return_value=txn)
    pool = MagicMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=conn)
    cm.__aexit__ = AsyncMock(return_value=None)
    pool.acquire.return_value = cm
    return pool


class _Sonda:
    """Bloqueia o chamador ate o lado async liberar — ou desistir por timeout."""

    def __init__(self) -> None:
        self.liberado = threading.Event()
        self.loop_seguiu_girando: bool | None = None

    def bloquear(self) -> None:
        # 2s e folga suficiente: no caminho bom o release vem em ~50ms.
        self.loop_seguiu_girando = self.liberado.wait(timeout=2.0)

    async def liberar(self) -> None:
        await asyncio.sleep(0.05)
        self.liberado.set()


@pytest.mark.asyncio
async def test_read_nao_congela_o_event_loop() -> None:
    """F86: `search_stream` + consumo do stream rodam fora do loop."""
    from src.google_ads.reports import run_report

    sonda = _Sonda()

    def fake_search_stream(request: Any) -> list[Any]:
        sonda.bloquear()
        batch = MagicMock()
        batch.results = [MagicMock()]
        return [batch]

    ga_service = MagicMock()
    ga_service.search_stream = fake_search_stream
    client = MagicMock()
    client.get_service = MagicMock(return_value=ga_service)
    client.get_type = MagicMock(return_value=MagicMock())

    with (
        patch("src.google_ads.reports.ensure_account_access", AsyncMock(return_value=None)),
        patch("src.google_ads.reports.before_call", AsyncMock()),
        patch("src.google_ads.reports.record_actual", AsyncMock()),
        patch("src.google_ads.reports.audit_log.record", AsyncMock(return_value=1)),
        patch("src.google_ads.reports.connection.get_pool", return_value=_pool()),
        patch("src.google_ads.reports.build_client_for_manager", AsyncMock(return_value=client)),
    ):
        await asyncio.gather(
            run_report(
                manager_id=uuid4(),
                session_id=uuid4(),
                customer_id="1234567890",
                query="SELECT campaign.id FROM campaign",
                row_formatter=lambda _row: {"ok": True},
                operation_name="get_campaign_performance",
            ),
            sonda.liberar(),
        )

    assert sonda.loop_seguiu_girando is True, (
        "o event loop ficou parado durante a chamada do SDK — com --concurrency=80 "
        "isso serializa a instancia inteira e trava ate o /health"
    )


@pytest.mark.asyncio
async def test_provider_request_id_sobrevive_ao_salto_de_thread() -> None:
    """F86 — armadilha da propria correcao: `_last_request_id` e um ContextVar.

    O interceptor grava o request-id DURANTE a chamada gRPC. `to_thread` COPIA o
    contexto pra worker thread, e mutacoes la dentro nao voltam: um
    `get_request_id()` do lado do loop leria None e o `provider_request_id`
    sumiria de todo audit — em silencio, porque o campo e opcional.

    Por isso o id e lido DENTRO da funcao offloaded e devolvido junto com a
    resposta. Este teste exercita o ContextVar de verdade, e nao o mock de
    `get_request_id` que os outros testes usam — e o unico jeito de pegar isso.
    """
    from src.google_ads import mutations
    from src.google_ads.mutations import run_mutation
    from src.google_ads.request_id import _last_request_id

    def fake_mutate(request: Any) -> MagicMock:
        # Simula o interceptor: grava o id no ContextVar dentro da chamada.
        _last_request_id.set("req-vindo-da-thread")
        resp = MagicMock()
        resp.mutate_operation_responses = []
        resp.partial_failure_error = MagicMock(code=0, details=[])
        return resp

    ga_service = MagicMock()
    ga_service.mutate = fake_mutate
    client = MagicMock()
    client.get_service = MagicMock(return_value=ga_service)
    client.get_type = MagicMock(return_value=MagicMock(mutate_operations=[]))

    audit = AsyncMock(return_value=1)
    with (
        patch.object(mutations, "ensure_account_access", AsyncMock()),
        patch.object(mutations, "before_call", AsyncMock()),
        patch.object(mutations, "record_actual", AsyncMock()),
        patch.object(mutations.audit_log, "record", audit),
        patch.object(mutations.connection, "get_pool", return_value=_pool()),
        patch.object(mutations, "build_client_for_manager", AsyncMock(return_value=client)),
        patch.object(mutations, "get_builder", lambda _op: lambda c, cid, p: [MagicMock()]),
    ):
        resultado = await run_mutation(
            manager_id=uuid4(),
            session_id=uuid4(),
            customer_id="1234567890",
            operation_type="update_keyword_status",
            payload={"keywords": [{}]},
            target_count=1,
        )

    assert resultado["provider_request_id"] == "req-vindo-da-thread"
    assert audit.call_args.kwargs["provider_request_id"] == "req-vindo-da-thread"


@pytest.mark.asyncio
async def test_mutate_nao_congela_o_event_loop() -> None:
    """F86: o caminho de escrita tem o mesmo problema e a mesma correcao."""
    from src.google_ads import mutations
    from src.google_ads.mutations import run_mutation

    sonda = _Sonda()

    def fake_mutate(request: Any) -> MagicMock:
        sonda.bloquear()
        resp = MagicMock()
        resp.mutate_operation_responses = []
        resp.partial_failure_error = MagicMock(code=0, details=[])
        return resp

    ga_service = MagicMock()
    ga_service.mutate = fake_mutate
    client = MagicMock()
    client.get_service = MagicMock(return_value=ga_service)
    client.get_type = MagicMock(return_value=MagicMock(mutate_operations=[]))

    with (
        patch.object(mutations, "ensure_account_access", AsyncMock()),
        patch.object(mutations, "before_call", AsyncMock()),
        patch.object(mutations, "record_actual", AsyncMock()),
        patch.object(mutations.audit_log, "record", AsyncMock(return_value=1)),
        patch.object(mutations.connection, "get_pool", return_value=_pool()),
        patch.object(mutations, "build_client_for_manager", AsyncMock(return_value=client)),
        patch.object(mutations, "get_builder", lambda _op: lambda c, cid, p: [MagicMock()]),
        patch.object(mutations, "get_request_id", lambda: "req-1"),
        patch.object(mutations, "reset_request_id", lambda: None),
    ):
        await asyncio.gather(
            run_mutation(
                manager_id=uuid4(),
                session_id=uuid4(),
                customer_id="1234567890",
                operation_type="update_keyword_status",
                payload={"keywords": [{}]},
                target_count=1,
            ),
            sonda.liberar(),
        )

    assert sonda.loop_seguiu_girando is True
