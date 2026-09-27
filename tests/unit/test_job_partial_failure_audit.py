"""F93: job nao pode reportar `success` sobre inventario parcial, nem morrer calado.

Duas falhas somadas:

1. Leitura parcial nao pode passar por completa: um 500 na pagina 2 devolve a
   lista truncada. Desde a Task 7 (2026-08-20) quem decide o que fazer com
   inventario truncado e `build_plan()`, pelo `complete` de `fetch_partnership`
   (a paginacao marca `complete=False` quando uma pagina falha — guard em
   `test_meta_graph_paginacao.py`); leitura parcial bloqueia o lado destrutivo e
   o audit registra `error`, nunca `success` por omissao. Os dois testes do
   wrapper de `/me/adaccounts` sairam com ele no F197.
2. Crash inesperado no corpo do job (build_client, upsert_many, rede) nao grava
   NENHUMA linha: o rastro fica so no Cloud Run, entao um resync quebrado por
   dias fica invisivel na trilha de auditoria.

O item (1) e o que segurou a migracao do F82 pro header Authorization: enquanto
a quebra do resync for auditada como sucesso, trocar o mecanismo de auth desse
job e apostar as cegas.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.jobs import _audit, meta_resync
from src.meta_ads.partnership import PartnershipSnapshot
from src.meta_ads.reconcile import InventoryRow


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


def _patch_resync(
    monkeypatch: pytest.MonkeyPatch, *, parceria_accounts: list, complete: bool
) -> tuple[AsyncMock, AsyncMock, MagicMock]:
    """Troca a parceria (`fetch_partnership`, com o `complete` pedido), a sonda de
    alcance (todas as contas lidas) e o passo destrutivo do plano por dublês.

    O inventário fixo (`act_ausente`, ativo, `missed_syncs=2`) nunca está na
    parceria — cruza o limiar (`2 + 1 >= 3`) sempre que `complete=True`, o que
    faz `build_plan()` propor remoção e exercita `deactivate`/`revoke_for_account`
    de verdade no teste do caminho feliz.
    """
    from src.meta_ads.alcance import Alcance

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
        "sondar_alcance",
        AsyncMock(
            return_value=Alcance(le=frozenset(a["ad_account_id"] for a in parceria_accounts))
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
    desativa = AsyncMock(return_value=1)
    monkeypatch.setattr(meta_resync.meta_ad_accounts, "deactivate", desativa)
    revoga = AsyncMock(return_value=[])
    monkeypatch.setattr(meta_resync.manager_meta_account_access, "revoke_for_account", revoga)
    monkeypatch.setattr(meta_resync, "record_access_revocation", AsyncMock())
    # `conn` virou parametro obrigatorio de `reconcile_meta` (revisao da Task
    # 3): o job nao adquire mais conexao do pool, entao a dube vem daqui e o
    # pool NAO e mockado — mock sobrando desarmaria essa invariante.
    conn = MagicMock()
    conn.execute = AsyncMock(return_value="UPDATE 0")
    return desativa, revoga, conn


@pytest.mark.asyncio
async def test_inventario_parcial_nao_desativa_nada_e_audita_erro(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F93(1)/Req.3: com complete=False o upsert segue (aditivo, seguro) mas
    build_plan() bloqueia o lado destrutivo (deactivate/revoke NAO rodam), e o
    audit registra `error` em vez de `success`."""
    desativa, revoga, conn = _patch_resync(
        monkeypatch,
        parceria_accounts=[{"ad_account_id": "act_1", "account_name": "A"}],
        complete=False,
    )
    rec = AsyncMock(return_value=1)
    monkeypatch.setattr(meta_resync, "record_job_run", rec)

    await meta_resync.reconcile_meta(conn)

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
    desativa, revoga, conn = _patch_resync(
        monkeypatch,
        parceria_accounts=[{"ad_account_id": "act_1", "account_name": "A"}],
        complete=True,
    )
    rec = AsyncMock(return_value=1)
    monkeypatch.setattr(meta_resync, "record_job_run", rec)

    await meta_resync.reconcile_meta(conn)

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
    # Task 4: `run()` passou a chamar `configure_logging(...)` antes do
    # `init_pool` (espelha o gêmeo Google). Mockado aqui como todo o resto
    # desta função — `structlog.configure(...)` é estado GLOBAL do processo
    # pytest inteiro, não por-teste: rodá-lo de verdade aqui vazava pra
    # OUTROS arquivos de teste (`test_meta_denial_log.py`, que usa
    # `capture_logs()` pra afirmar o log de negação de acesso Meta),
    # dependendo da ordem alfabética de coleta — achado por bisseção, não
    # deduzido. Este teste prova a orquestração de `run()`, não o
    # `configure_logging` em si (isso já tem cobertura própria em
    # test_logging_context.py/test_logging_severity.py).
    monkeypatch.setattr(meta_resync, "configure_logging", MagicMock())
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
