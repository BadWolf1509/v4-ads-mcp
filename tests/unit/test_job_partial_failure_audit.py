"""F93: job nao pode reportar `success` sobre inventario parcial, nem morrer calado.

Duas falhas somadas:

1. `_fetch_all_adaccounts` faz `break` em resposta non-200 e devolve a lista
   PARCIAL. Isso e correto pro uso original (cache de exibicao do OAuth), mas
   `reconcile_meta` tambem usa o helper pra medir o ALCANCE do system user —
   entao um 500 na pagina 2 nao pode passar por leitura completa. Desde a Task
   7 (2026-08-20) quem decide o que fazer com inventario truncado e
   `build_plan()` (via o `complete` combinado de `fetch_partnership` +
   `_fetch_all_adaccounts`), nao mais `_deactivate_churned` — mas a propriedade
   e a mesma: leitura parcial bloqueia o lado destrutivo e o audit registra
   `error`, nunca `success` por omissao.
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
from src.meta_ads.partnership import PartnershipSnapshot
from src.meta_ads.reconcile import InventoryRow

_ADACCOUNTS = "https://graph.facebook.com/v22.0/me/adaccounts"


class _FakeAcquire:
    async def __aenter__(self) -> MagicMock:
        conn = MagicMock()
        # F128: o caminho `complete=True` passou a escrever pelo conn (contador
        # de ausencias), entao a dublê precisa de um execute awaitable.
        conn.execute = AsyncMock(return_value="UPDATE 0")
        return conn

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


def _patch_resync(
    monkeypatch: pytest.MonkeyPatch, *, parceria_accounts: list, complete: bool
) -> tuple[AsyncMock, AsyncMock]:
    """Troca as duas leituras (`fetch_partnership` + `_fetch_all_adaccounts`,
    ambas com o mesmo `complete`) e o passo destrutivo do plano por dublês.

    O inventário fixo (`act_ausente`, ativo, `missed_syncs=2`) nunca está na
    parceria — cruza o limiar (`2 + 1 >= 3`) sempre que `complete=True`, o que
    faz `build_plan()` propor remoção e exercita `deactivate`/`revoke_for_account`
    de verdade no teste do caminho feliz.
    """
    from src.auth.meta_oauth import AdAccountsFetch

    settings = MagicMock()
    settings.meta_system_user_token = "tok"
    settings.meta_business_id = "bm"
    settings.meta_reconcile_apply = True
    monkeypatch.setattr(meta_resync, "get_settings", lambda: settings)
    monkeypatch.setattr(
        meta_resync,
        "fetch_partnership",
        AsyncMock(return_value=PartnershipSnapshot(parceria_accounts, complete)),
    )
    monkeypatch.setattr(
        meta_resync,
        "_fetch_all_adaccounts",
        AsyncMock(
            return_value=AdAccountsFetch(
                accounts=[{"id": a["ad_account_id"]} for a in parceria_accounts],
                complete=complete,
            )
        ),
    )
    monkeypatch.setattr(
        meta_resync.meta_ad_accounts,
        "upsert_many",
        AsyncMock(return_value=len(parceria_accounts)),
    )
    monkeypatch.setattr(
        meta_resync.meta_ad_accounts,
        "list_inventory_rows",
        AsyncMock(return_value=[InventoryRow("act_ausente", True, 2)]),
    )
    monkeypatch.setattr(meta_resync.meta_ad_accounts, "apply_absences", AsyncMock())
    monkeypatch.setattr(meta_resync.meta_ad_accounts, "set_reachable", AsyncMock())
    monkeypatch.setattr(meta_resync.connection, "get_pool", lambda: _FakePool())
    desativa = AsyncMock(return_value=1)
    monkeypatch.setattr(meta_resync.meta_ad_accounts, "deactivate", desativa)
    revoga = AsyncMock(return_value=[])
    monkeypatch.setattr(meta_resync.manager_meta_account_access, "revoke_for_account", revoga)
    monkeypatch.setattr(meta_resync, "record_access_revocation", AsyncMock())
    return desativa, revoga


@pytest.mark.asyncio
async def test_inventario_parcial_nao_desativa_nada_e_audita_erro(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F93(1)/Req.3: com complete=False o upsert segue (aditivo, seguro) mas
    build_plan() bloqueia o lado destrutivo (deactivate/revoke NAO rodam), e o
    audit registra `error` em vez de `success`."""
    desativa, revoga = _patch_resync(
        monkeypatch,
        parceria_accounts=[{"ad_account_id": "act_1", "account_name": "A"}],
        complete=False,
    )
    rec = AsyncMock(return_value=1)
    monkeypatch.setattr(meta_resync, "record_job_run", rec)

    await meta_resync.reconcile_meta()

    (
        desativa.assert_not_awaited(),
        "deletion detection sobre inventario truncado desativa conta viva",
    )
    revoga.assert_not_awaited()
    kwargs = rec.call_args.kwargs
    assert kwargs["status"] == "error"
    assert kwargs["error_message"]


@pytest.mark.asyncio
async def test_inventario_completo_audita_sucesso_e_desativa(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F93(1): o caminho feliz nao pode regredir — segue desativando quem saiu
    da parceria e gravando success."""
    desativa, revoga = _patch_resync(
        monkeypatch,
        parceria_accounts=[{"ad_account_id": "act_1", "account_name": "A"}],
        complete=True,
    )
    rec = AsyncMock(return_value=1)
    monkeypatch.setattr(meta_resync, "record_job_run", rec)

    await meta_resync.reconcile_meta()

    desativa.assert_awaited_once()
    assert desativa.await_args.kwargs["ad_account_ids"] == ["act_ausente"]
    revoga.assert_awaited_once()
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
        meta_resync, "reconcile_meta", AsyncMock(side_effect=RuntimeError("upsert explodiu"))
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
