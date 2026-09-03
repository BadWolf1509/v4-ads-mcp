"""F141: o caminho REAL de `resolve_account_today` — DB de verdade, fuso de verdade.

Todo teste de tool tem o relogio da conta stubado pelo conftest compartilhado
(sem pool nos unitarios). Isto e correto para os tools, mas deixaria o caminho
real — `run_with_reconnect` -> `get_by_customer_id` -> `account_today` — sem
nenhuma execucao no CI. Este arquivo chama a ORIGEM direto, contra um Postgres
de testcontainers com a conta seedada.

O instante injetado e o do bug: 00:30 UTC de 03/09, quando na conta
(`America/Fortaleza`, UTC-3) ainda sao 21:30 de 02/09.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from src.db.repositories import google_ads_accounts
from src.google_ads.account_clock import resolve_account_today

INSTANTE_DO_BUG = datetime(2026, 9, 3, 0, 30, tzinfo=UTC)


@pytest.mark.integration
async def test_le_o_fuso_do_inventario_e_devolve_o_dia_da_conta(db):
    async with db.acquire() as conn:
        await google_ads_accounts.upsert_many(
            conn,
            [
                {
                    "customer_id": "1163862076",
                    "mcc_id": "0000000000",
                    "descriptive_name": "Fortaleza",
                    "time_zone": "America/Fortaleza",
                },
                {
                    "customer_id": "3237459217",
                    "mcc_id": "0000000000",
                    "descriptive_name": "Campo Grande",
                    "time_zone": "America/Campo_Grande",
                },
            ],
        )
    assert await resolve_account_today("1163862076", now=INSTANTE_DO_BUG) == date(2026, 9, 2)
    assert await resolve_account_today("3237459217", now=INSTANTE_DO_BUG) == date(2026, 9, 2)


@pytest.mark.integration
async def test_conta_fora_do_inventario_cai_em_utc_sem_estourar(db):
    """Decisao registrada: sem fuso -> data UTC + warning, nunca excecao."""
    assert await resolve_account_today("9999999999", now=INSTANTE_DO_BUG) == date(2026, 9, 3)


@pytest.mark.integration
async def test_conta_com_fuso_nulo_cai_em_utc(db):
    async with db.acquire() as conn:
        await google_ads_accounts.upsert_many(
            conn,
            [{"customer_id": "5555555555", "mcc_id": "0000000000", "descriptive_name": "sem tz"}],
        )
    assert await resolve_account_today("5555555555", now=INSTANTE_DO_BUG) == date(2026, 9, 3)
