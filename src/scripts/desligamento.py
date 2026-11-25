"""Desligamento auditado: credenciais de gestor desativado e descomissionamento de contas.

Núcleo dos subcomandos `admin revogar-conexoes-de-inativos` e `admin descomissionar`
(`src/scripts/admin.py`), separado para ser testável com uma conexão real. Os dois só
escrevem com `apply=True`, numa transação, e gravam audit com `had_effect` (F179) — inclusive
quando não havia nada a fazer. Nenhuma linha é apagada: revogação e desativação são soft.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

import asyncpg

from src.db.repositories import (
    audit_log,
    google_ads_accounts,
    google_oauth_connections,
    manager_account_access,
    manager_meta_account_access,
    meta_ad_accounts,
)
from src.db.repositories.motivos import LEFT_MCC_REASON, PARTNERSHIP_ENDED_REASON
from src.jobs._audit import record_access_revocation


async def revogar_conexoes_de_inativos(
    conn: asyncpg.Connection, *, apply: bool, por: UUID
) -> list[asyncpg.Record]:
    """Conexões OAuth vivas de gestor desativado; com `apply`, revoga todas e audita.

    Backfill do que o toggle passou a fazer na desativação (desenho de 25/11): os gestores
    desativados antes disso ficaram com a conexão viva."""
    if not apply:
        return await google_oauth_connections.list_live_of_inactive_managers(conn)
    async with conn.transaction():
        alvo = await google_oauth_connections.list_live_of_inactive_managers(conn)
        for linha in alvo:
            await google_oauth_connections.revoke(conn, linha["id"])
        await audit_log.record(
            conn,
            manager_id=por,
            session_id=None,
            customer_id=None,
            action_type="system",
            operation="cli_revoke_inactive_connections",
            target_count=len(alvo),
            params_summary={
                "conexoes": [
                    {"manager_email": r["manager_email"], "google_email": r["google_email"]}
                    for r in alvo
                ]
            },
            had_effect=bool(alvo),
        )
    return alvo


@dataclass(frozen=True, slots=True)
class Descomissionamento:
    invalidos: list[str] = field(default_factory=list)
    google: list[str] = field(default_factory=list)
    meta: list[str] = field(default_factory=list)
    # Contas Google JÁ inativas com grant vivo: o apply as revoga também
    # (`revoke_for_inactive_accounts` age sobre o estado), então o operador precisa vê-las.
    google_backlog: list[str] = field(default_factory=list)
    grants_google: int = 0
    grants_meta: int = 0


async def _ativos(conn: asyncpg.Connection, tabela: str, coluna: str) -> list[str]:
    linhas = await conn.fetch(
        f"SELECT {coluna} FROM {tabela} WHERE is_active = true ORDER BY {coluna}"  # noqa: S608
    )
    return [str(r[0]) for r in linhas]


async def _grants_meta_vivos(conn: asyncpg.Connection, contas: list[str]) -> int:
    n = await conn.fetchval(
        "SELECT count(*) FROM manager_meta_account_access "
        "WHERE ad_account_id = ANY($1::text[]) AND revoked_at IS NULL",
        contas,
    )
    return int(n or 0)


async def _backlog_google(conn: asyncpg.Connection) -> list[str]:
    linhas = await conn.fetch(
        "SELECT DISTINCT a.customer_id FROM google_ads_accounts a"
        " JOIN manager_account_access m ON m.customer_id = a.customer_id"
        " WHERE a.is_active = false AND m.revoked_at IS NULL ORDER BY 1"
    )
    return [str(r[0]) for r in linhas]


async def descomissionar(
    conn: asyncpg.Connection,
    *,
    manter_google: list[str],
    manter_meta: list[str],
    apply: bool,
    por: UUID,
) -> Descomissionamento:
    """Desativa no inventário toda conta ATIVA fora das listas e revoga os grants nelas.

    Trava: cada id a manter tem de ser conta ativa do inventário, e nenhuma lista pode vir
    vazia — um erro de digitação não pode descomissionar tudo. Os grants saem com os motivos
    de churn (`left_mcc` / `partnership_ended`): conta que reaparecer é reativada pelo resync
    e os grants voltam pela restauração de churn. Leitura, decisão e escrita na MESMA
    transação; audit `cli_decommission` com `had_effect` também quando nada mudou.

    Assimetria deliberada: no Google, grants vivos em conta JÁ inativa (backlog) também são
    revogados e aparecem em `google_backlog`; no Meta, só as contas descomissionadas agora —
    o gate do Meta já filtra conta inativa (`can_manager_access`)."""
    async with conn.transaction():
        ativas_g = await _ativos(conn, "google_ads_accounts", "customer_id")
        ativas_m = await _ativos(conn, "meta_ad_accounts", "ad_account_id")
        invalidos = [c for c in manter_google if c not in ativas_g] + [
            a for a in manter_meta if a not in ativas_m
        ]
        if not manter_google:
            invalidos.append("(google vazio)")
        if not manter_meta:
            invalidos.append("(meta vazio)")
        if invalidos:
            return Descomissionamento(invalidos=invalidos)

        fora_g = [c for c in ativas_g if c not in manter_google]
        fora_m = [a for a in ativas_m if a not in manter_meta]
        backlog = await _backlog_google(conn)
        if not apply:
            grants_g = await manager_account_access.count_grants_on_accounts(
                conn, customer_ids=fora_g
            ) + await manager_account_access.count_grants_on_inactive_accounts(conn)
            return Descomissionamento(
                google=fora_g,
                meta=fora_m,
                google_backlog=backlog,
                grants_google=grants_g,
                grants_meta=await _grants_meta_vivos(conn, fora_m),
            )

        await google_ads_accounts.deactivate(conn, customer_ids=fora_g)
        atingidos = await manager_account_access.revoke_for_inactive_accounts(
            conn, reason=LEFT_MCC_REASON
        )
        grants_g = sum(len(v) for v in atingidos.values())
        # Trilha por conta, como o resync (C2): reconceder zera o motivo, e sem esta linha
        # não sobra registro de quais gestores perderam quais contas.
        for customer_id, manager_ids in sorted(atingidos.items()):
            await record_access_revocation(
                conn,
                platform="google",
                ad_account_id=customer_id,
                reason=LEFT_MCC_REASON,
                manager_ids=manager_ids,
            )
        await meta_ad_accounts.deactivate(conn, ad_account_ids=fora_m)
        grants_m = 0
        for conta in fora_m:
            atingidos_m = await manager_meta_account_access.revoke_for_account(
                conn, ad_account_id=conta, reason=PARTNERSHIP_ENDED_REASON
            )
            grants_m += len(atingidos_m)
            if atingidos_m:
                await record_access_revocation(
                    conn,
                    platform="meta",
                    ad_account_id=conta,
                    reason=PARTNERSHIP_ENDED_REASON,
                    manager_ids=[str(m) for m in atingidos_m],
                )
        resultado = Descomissionamento(
            google=fora_g,
            meta=fora_m,
            google_backlog=backlog,
            grants_google=grants_g,
            grants_meta=grants_m,
        )
        await audit_log.record(
            conn,
            manager_id=por,
            session_id=None,
            customer_id=None,
            action_type="system",
            operation="cli_decommission",
            target_count=len(fora_g) + len(fora_m),
            params_summary={
                "manter_google": manter_google,
                "manter_meta": manter_meta,
                "contas_google": fora_g,
                "contas_meta": fora_m,
                "contas_google_backlog": backlog,
                "grants_google": grants_g,
                "grants_meta": grants_m,
            },
            had_effect=bool(fora_g or fora_m or grants_g or grants_m),
        )
    return resultado
