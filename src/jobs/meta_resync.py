"""Cloud Run Job tail: refresh meta_ad_accounts via the shared system-user token.

Roda piggyback no fim do job diário account_resync (mesmo Cloud Run Job +
Cloud Scheduler) pra que conta de cliente nova entre no inventário zero-touch.
Reusa o helper paginado _fetch_all_adaccounts. Grants seguem MANUAIS (Modelo B):
isto só atualiza o inventário (`meta_ad_accounts`), não concede acesso a gestor.

Standalone: `python -m src.jobs.meta_resync`
"""

import asyncio
import sys
from typing import Any

import httpx
import structlog

from src.auth.meta_oauth import _fetch_all_adaccounts
from src.config import get_settings
from src.db import connection
from src.db.repositories import meta_ad_accounts
from src.jobs._audit import record_job_run

log = structlog.get_logger(__name__)


def _to_payload(data: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map Graph /me/adaccounts rows → meta_ad_accounts upsert dicts."""
    payload: list[dict[str, Any]] = []
    for a in data:
        ad_id = a.get("id", "")
        if not ad_id.startswith("act_"):
            ad_id = f"act_{ad_id}"
        business = a.get("business") or {}
        payload.append(
            {
                "ad_account_id": ad_id,
                "business_id": business.get("id"),
                "business_name": business.get("name"),
                "account_name": a.get("name", ad_id),
                "currency": a.get("currency"),
                "timezone_name": a.get("timezone_name"),
                "account_status": a.get("account_status"),
            }
        )
    return payload


async def _deactivate_churned(conn: Any, payload: list[dict[str, Any]]) -> int:
    """Deletion detection (F65): conta que sumiu de um BM ainda visível vira is_active=false.

    Agrupa por business_id — o system user enxerga MÚLTIPLOS BMs via /me/adaccounts;
    sem agrupar, o keep-list de um BM marcaria as contas de OUTRO BM como churned.
    Contas sem business_id (pessoais) são puladas: não dá pra escopar a detecção sem BM,
    então preferimos deixá-las ativas a desativá-las por engano. Um BM que sumiu inteiro
    (SU perdeu acesso) não aparece no payload → suas contas ficam intactas (limitação
    conhecida: a detecção só cobre conta ausente de BM ainda visível).
    """
    by_business: dict[str, list[str]] = {}
    for a in payload:
        bid = a.get("business_id")
        if bid:
            by_business.setdefault(bid, []).append(a["ad_account_id"])
    total = 0
    for business_id, keep in by_business.items():
        total += await meta_ad_accounts.mark_inactive_except(
            conn, business_id=business_id, keep_ad_account_ids=keep
        )
    return total


async def resync_meta() -> int:
    """Sync meta_ad_accounts from /me/adaccounts (system user). Returns count upserted.

    Assume que connection.init_pool() já foi chamado. No-op (retorna 0) se o token
    do system user não estiver configurado — o caller trata Meta como best-effort.
    """
    settings = get_settings()
    token = settings.meta_system_user_token
    if not token:
        log.warning("meta_resync_no_token")
        return 0
    async with httpx.AsyncClient(timeout=60.0) as http:
        data = await _fetch_all_adaccounts(http, token)
    payload = _to_payload(data)
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        n = await meta_ad_accounts.upsert_many(conn, payload)
        deactivated = await _deactivate_churned(conn, payload)
        await record_job_run(
            conn,
            operation="meta_resync",
            platform="meta",
            target_count=n,
            params_summary={"deactivated": deactivated} if deactivated else None,
        )
    log.info("meta_resync_complete", upserted=n, deactivated=deactivated)
    return n


async def run() -> int:
    settings = get_settings()
    await connection.init_pool(settings.database_url)
    try:
        n = await resync_meta()
        print(f"OK: upserted {n} Meta ad accounts")
        return 0
    finally:
        await connection.close_pool()


def main() -> int:
    return asyncio.run(run())


if __name__ == "__main__":
    sys.exit(main())
