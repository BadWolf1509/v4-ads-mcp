"""F93: job nao pode reportar `success` sobre inventario parcial, nem morrer calado.

Duas falhas somadas:

1. `_fetch_all_adaccounts` faz `break` em resposta non-200 e devolve a lista
   PARCIAL. Isso e correto pro uso original (cache de exibicao do OAuth), mas o
   `resync_meta` reusa o helper pra DELETION DETECTION — entao um 500 na pagina 2
   entrega inventario truncado que `_deactivate_churned` interpreta como churn,
   reintroduzindo o sintoma do F65 por outra porta. E uma falha na pagina 1 grava
   `record_job_run(target_count=0)` com status `success` (o default), mascarando
   a falha por completo.
2. Crash inesperado no corpo do job (build_client, upsert_many, rede) nao grava
   NENHUMA linha: o rastro fica so no Cloud Run, entao um resync quebrado por
   dias fica invisivel na trilha de auditoria.

O item (1) e o que segurou a migracao do F82 pro header Authorization: enquanto
a quebra do resync for auditada como sucesso, trocar o mecanismo de auth desse
job e apostar as cegas.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import respx
from httpx import Response

from src.jobs import _audit, meta_resync

_ADACCOUNTS = "https://graph.facebook.com/v22.0/me/adaccounts"


class _FakeAcquire:
    async def __aenter__(self) -> MagicMock:
        return MagicMock()

    async def __aexit__(self, *exc: object) -> bool:
        return False


class _FakePool:
    def acquire(self) -> _FakeAcquire:
        return _FakeAcquire()


@pytest.mark.asyncio
async def test_fetch_sinaliza_incompleto_quando_uma_pagina_falha() -> None:
    """F93(1): pagina non-200 no meio da paginacao => complete=False."""
    from src.auth.meta_oauth import _fetch_all_adaccounts

    with respx.mock:
        respx.get(url__startswith=_ADACCOUNTS).mock(
            side_effect=[
                Response(
                    200,
                    json={
                        "data": [{"id": "act_1", "name": "A"}],
                        "paging": {"next": f"{_ADACCOUNTS}?after=cursor2"},
                    },
                ),
                Response(500, json={"error": {"message": "boom"}}),
            ]
        )
        async with httpx.AsyncClient() as http:
            result = await _fetch_all_adaccounts(http, "tok")

    assert [a["id"] for a in result.accounts] == ["act_1"]
    assert result.complete is False, (
        "inventario truncado nao pode se passar por completo — e o que faz o "
        "deletion detection desativar conta viva"
    )


@pytest.mark.asyncio
async def test_fetch_completo_quando_paginacao_termina_naturalmente() -> None:
    """F93(1): sem `paging.next` e sem erro => complete=True."""
    from src.auth.meta_oauth import _fetch_all_adaccounts

    with respx.mock:
        respx.get(url__startswith=_ADACCOUNTS).mock(
            return_value=Response(200, json={"data": [{"id": "act_1", "name": "A"}]})
        )
        async with httpx.AsyncClient() as http:
            result = await _fetch_all_adaccounts(http, "tok")

    assert result.complete is True
    assert len(result.accounts) == 1


def _patch_resync(monkeypatch: pytest.MonkeyPatch, *, accounts: list, complete: bool) -> AsyncMock:
    from src.auth.meta_oauth import AdAccountsFetch

    settings = MagicMock()
    settings.meta_system_user_token = "tok"
    monkeypatch.setattr(meta_resync, "get_settings", lambda: settings)
    monkeypatch.setattr(
        meta_resync,
        "_fetch_all_adaccounts",
        AsyncMock(return_value=AdAccountsFetch(accounts=accounts, complete=complete)),
    )
    monkeypatch.setattr(
        meta_resync.meta_ad_accounts, "upsert_many", AsyncMock(return_value=len(accounts))
    )
    monkeypatch.setattr(meta_resync.connection, "get_pool", lambda: _FakePool())
    mie = AsyncMock(return_value=0)
    monkeypatch.setattr(meta_resync.meta_ad_accounts, "mark_inactive_except", mie)
    return mie


@pytest.mark.asyncio
async def test_inventario_parcial_nao_desativa_nada_e_audita_erro(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F93(1): com complete=False o upsert segue (aditivo, seguro) mas a deteccao
    de churn NAO roda, e o audit registra `error` em vez de `success`."""
    mie = _patch_resync(
        monkeypatch,
        accounts=[{"id": "act_1", "name": "A", "business": {"id": "bmX", "name": "BM X"}}],
        complete=False,
    )
    rec = AsyncMock(return_value=1)
    monkeypatch.setattr(meta_resync, "record_job_run", rec)

    await meta_resync.resync_meta()

    mie.assert_not_awaited(), "deletion detection sobre inventario truncado desativa conta viva"
    kwargs = rec.call_args.kwargs
    assert kwargs["status"] == "error"
    assert kwargs["error_message"]


@pytest.mark.asyncio
async def test_inventario_completo_audita_sucesso_e_desativa(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F93(1): o caminho feliz nao pode regredir — segue deduzindo churn e gravando success."""
    mie = _patch_resync(
        monkeypatch,
        accounts=[{"id": "act_1", "name": "A", "business": {"id": "bmX", "name": "BM X"}}],
        complete=True,
    )
    rec = AsyncMock(return_value=1)
    monkeypatch.setattr(meta_resync, "record_job_run", rec)

    await meta_resync.resync_meta()

    mie.assert_awaited_once()
    assert rec.call_args.kwargs["status"] == "success"


@pytest.mark.asyncio
async def test_crash_do_job_grava_audit_e_repropaga(monkeypatch: pytest.MonkeyPatch) -> None:
    """F93(2): crash inesperado precisa deixar linha `error` no audit — e continuar sendo crash."""
    settings = MagicMock()
    settings.database_url = "postgres://fake"
    monkeypatch.setattr(meta_resync, "get_settings", lambda: settings)
    monkeypatch.setattr(meta_resync.connection, "init_pool", AsyncMock())
    monkeypatch.setattr(meta_resync.connection, "close_pool", AsyncMock())
    monkeypatch.setattr(meta_resync.connection, "get_pool", lambda: _FakePool())
    monkeypatch.setattr(
        meta_resync, "resync_meta", AsyncMock(side_effect=RuntimeError("upsert explodiu"))
    )
    # `record_job_crash` resolve `record_job_run` no namespace de _audit, nao no
    # de meta_resync — patchar no lugar errado nao interceptaria nada (a mesma
    # armadilha de mock-target que o CLAUDE.md documenta pra pre-flight).
    rec = AsyncMock(return_value=1)
    monkeypatch.setattr(_audit, "record_job_run", rec)
    monkeypatch.setattr(_audit.connection, "get_pool", lambda: _FakePool())

    with pytest.raises(RuntimeError, match="upsert explodiu"):
        await meta_resync.run()

    kwargs = rec.call_args.kwargs
    assert kwargs["status"] == "error"
    assert "upsert explodiu" in kwargs["error_message"]
