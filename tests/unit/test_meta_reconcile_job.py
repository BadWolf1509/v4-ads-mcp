# tests/unit/test_meta_reconcile_job.py
"""O job orquestra: le, planeja, aplica, audita. As decisoes ja foram testadas
puras — aqui prova-se a FIACAO, incluindo o dry-run, a transacao atomica do
bloco destrutivo e a auditoria.

Nota: `ps` (a lista comum de patches de `_patches()`) é combinada com patches
específicos de cada teste via `ExitStack`, não via `with (*ps, ...)`. Esse
`with` parentizado com um item `*desempacotado` faz o Python interpretar o
grupo inteiro como UMA tupla (o mesmo literal `(*ps, a, b)`), não como vários
context managers — `TypeError: 'tuple' object does not support the context
manager protocol` em runtime, mesmo com a sintaxe válida. Os mocks que
precisam de asserção depois são pré-criados como AsyncMock e passados como
`new=` explícito pro `patch.object` (assim a variável local já É o mock,
sem depender de `as` nem do atributo interno `_patch.new`).
"""

from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.db.repositories.manager_meta_account_access import PARTNERSHIP_ENDED_REASON
from src.meta_ads.partnership import PartnershipSnapshot
from src.meta_ads.reconcile import InventoryRow


def _pool(conn: MagicMock) -> MagicMock:
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=ctx)
    return pool


def _patches(job, *, apply: bool, parceria: list[str]):
    """Setup comum: settings + as duas leituras (parceria completa, alcance
    completo) + pool/conn. `record_job_run` vem à parte (`gravar_run`) porque
    alguns testes precisam inspecionar a chamada depois do `with`."""
    from src.auth.meta_oauth import AdAccountsFetch

    conn = MagicMock()
    conn.execute = AsyncMock(return_value="UPDATE 0")
    gravar_run = AsyncMock()
    ps = [
        patch.object(
            job,
            "get_settings",
            MagicMock(
                return_value=MagicMock(
                    meta_system_user_token="tok", meta_business_id="bm", meta_reconcile_apply=apply
                )
            ),
        ),
        patch.object(
            job,
            "fetch_partnership",
            AsyncMock(
                return_value=PartnershipSnapshot(
                    [{"ad_account_id": i, "account_name": i} for i in parceria], True
                )
            ),
        ),
        patch.object(
            job,
            "_fetch_all_adaccounts",
            AsyncMock(
                return_value=AdAccountsFetch(accounts=[{"id": i} for i in parceria], complete=True)
            ),
        ),
        patch.object(job.connection, "get_pool", MagicMock(return_value=_pool(conn))),
        patch.object(job, "record_job_run", gravar_run),
    ]
    return conn, gravar_run, ps


@pytest.mark.asyncio
async def test_dry_run_calcula_e_audita_sem_aplicar() -> None:
    from src.jobs import meta_resync as job

    conn, _gravar_run, ps = _patches(job, apply=False, parceria=["act_1"])
    listar = AsyncMock(return_value=[InventoryRow("act_2", True, 9)])
    upsert = AsyncMock(return_value=1)
    desativa = AsyncMock(return_value=0)
    revoga = AsyncMock(return_value=[])
    with ExitStack() as stack:
        for p in [
            *ps,
            patch.object(job.meta_ad_accounts, "list_inventory_rows", listar),
            patch.object(job.meta_ad_accounts, "upsert_many", upsert),
            patch.object(job.meta_ad_accounts, "deactivate", desativa),
            patch.object(job.manager_meta_account_access, "revoke_for_account", revoga),
        ]:
            stack.enter_context(p)
        plano = await job.reconcile_meta()

    assert plano.to_remove == ["act_2"]
    desativa.assert_not_awaited()
    revoga.assert_not_awaited()
    # Req. 1: sem apply, o bloco destrutivo inteiro (a transação) nem começa.
    conn.transaction.assert_not_called()


@pytest.mark.asyncio
async def test_com_apply_ligado_desativa_e_revoga_e_audita_a_conta() -> None:
    from src.jobs import meta_resync as job

    conn, gravar_run, ps = _patches(job, apply=True, parceria=["act_1"])
    listar = AsyncMock(return_value=[InventoryRow("act_2", True, 9)])
    upsert = AsyncMock(return_value=1)
    absencias = AsyncMock()
    marca_alcance = AsyncMock()
    desativa = AsyncMock(return_value=1)
    revoga = AsyncMock(return_value=["mgr-1"])
    audita = AsyncMock()
    with ExitStack() as stack:
        for p in [
            *ps,
            patch.object(job.meta_ad_accounts, "list_inventory_rows", listar),
            patch.object(job.meta_ad_accounts, "upsert_many", upsert),
            patch.object(job.meta_ad_accounts, "apply_absences", absencias),
            patch.object(job.meta_ad_accounts, "set_reachable", marca_alcance),
            patch.object(job.meta_ad_accounts, "deactivate", desativa),
            patch.object(job.manager_meta_account_access, "revoke_for_account", revoga),
            patch.object(job, "record_access_revocation", audita),
        ]:
            stack.enter_context(p)
        plano = await job.reconcile_meta()

    desativa.assert_awaited_once()
    assert desativa.await_args.kwargs["ad_account_ids"] == ["act_2"]
    # Req. 2: a razão vem da CONSTANTE compartilhada com restore_for_account,
    # não de uma string livre reescrita no job.
    assert revoga.await_args.kwargs["reason"] == PARTNERSHIP_ENDED_REASON
    assert audita.await_args.kwargs["reason"] == PARTNERSHIP_ENDED_REASON
    assert audita.await_args.kwargs["ad_account_id"] == "act_2"
    assert audita.await_args.kwargs["manager_ids"] == ["mgr-1"]
    # Req. 3: alcance só é marcado com a leitura completa (aqui, complete=True
    # nos dois lados) — reachable_ids reflete exatamente o que foi lido.
    assert marca_alcance.await_args.kwargs["reachable_ids"] == ["act_1"]
    # Req. 1: absences + alcance + desativação + revogação + a auditoria da
    # revogação inteiras dentro de UMA transação — tudo ou nada.
    conn.transaction.assert_called_once()
    # Auditoria do RUN acontece de qualquer forma (dry-run ou não).
    assert gravar_run.await_args.kwargs["operation"] == "meta_reconcile"
    assert gravar_run.await_args.kwargs["platform"] == "meta"
    assert gravar_run.await_args.kwargs["params_summary"]["revoked_grants"] == 1
    assert gravar_run.await_args.kwargs["params_summary"]["applied"] is True
    assert plano.to_remove == ["act_2"]


@pytest.mark.asyncio
async def test_sem_business_id_o_job_nao_reconcilia() -> None:
    """Config faltando vira no-op explícito, não exceção no meio da noite."""
    from src.jobs import meta_resync as job

    with patch.object(
        job,
        "get_settings",
        MagicMock(
            return_value=MagicMock(
                meta_system_user_token="tok", meta_business_id="", meta_reconcile_apply=True
            )
        ),
    ):
        plano = await job.reconcile_meta()

    assert plano.blocked_reason == "meta_business_id nao configurado"


@pytest.mark.asyncio
async def test_leitura_parcial_bloqueia_aplicacao_mesmo_com_apply_ligado() -> None:
    """Req. 3: com meta_reconcile_apply=True mas leitura incompleta (aqui, a
    parceria vem truncada), build_plan() bloqueia primeiro — set_reachable,
    deactivate e revoke_for_account nunca rodam sobre uma leitura parcial."""
    from src.auth.meta_oauth import AdAccountsFetch
    from src.jobs import meta_resync as job

    conn = MagicMock()
    conn.execute = AsyncMock(return_value="UPDATE 0")
    settings = MagicMock(
        meta_system_user_token="tok", meta_business_id="bm", meta_reconcile_apply=True
    )
    marca_alcance = AsyncMock()
    desativa = AsyncMock(return_value=0)
    revoga = AsyncMock(return_value=[])
    with (
        patch.object(job, "get_settings", MagicMock(return_value=settings)),
        patch.object(
            job,
            "fetch_partnership",
            AsyncMock(
                return_value=PartnershipSnapshot(
                    [{"ad_account_id": "act_1", "account_name": "act_1"}],
                    False,  # leitura parcial
                )
            ),
        ),
        patch.object(
            job,
            "_fetch_all_adaccounts",
            AsyncMock(return_value=AdAccountsFetch(accounts=[{"id": "act_1"}], complete=True)),
        ),
        patch.object(job.connection, "get_pool", MagicMock(return_value=_pool(conn))),
        patch.object(
            job.meta_ad_accounts,
            "list_inventory_rows",
            AsyncMock(return_value=[InventoryRow("act_2", True, 9)]),
        ),
        patch.object(job.meta_ad_accounts, "upsert_many", AsyncMock(return_value=1)),
        patch.object(job.meta_ad_accounts, "set_reachable", marca_alcance),
        patch.object(job.meta_ad_accounts, "deactivate", desativa),
        patch.object(job.manager_meta_account_access, "revoke_for_account", revoga),
        patch.object(job, "record_job_run", AsyncMock()),
    ):
        plano = await job.reconcile_meta()

    assert plano.blocked_reason == "leitura incompleta"
    marca_alcance.assert_not_awaited()
    desativa.assert_not_awaited()
    revoga.assert_not_awaited()
    conn.transaction.assert_not_called()
