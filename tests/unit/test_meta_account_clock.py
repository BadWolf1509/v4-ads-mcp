"""F141, gêmeo Meta: `hoje` é da CONTA, não do servidor.

O instante escolhido é o que separa os dois: 2026-03-10T02:30Z é dia 10 em UTC
e ainda dia 9 em `America/Sao_Paulo` (UTC-3). Um teste que use meio-dia UTC
passa com a implementação errada — é a armadilha do "teste que não distingue
código bom de quebrado".
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from src.meta_ads.account_clock import resolve_meta_account_today

# 02:30Z de 10/03 = 23:30 de 09/03 em Sao_Paulo. UTC e conta discordam.
INSTANTE = datetime(2026, 3, 10, 2, 30, tzinfo=UTC)


@pytest.mark.asyncio
async def test_usa_o_fuso_da_conta_e_nao_o_do_servidor() -> None:
    conta = SimpleNamespace(timezone_name="America/Sao_Paulo")
    with patch(
        "src.meta_ads.account_clock.connection.run_with_reconnect",
        AsyncMock(return_value=conta),
    ):
        assert await resolve_meta_account_today("act_1", now=INSTANTE) == date(2026, 3, 9)


@pytest.mark.asyncio
async def test_conta_ausente_cai_em_utc_sem_estourar() -> None:
    with patch(
        "src.meta_ads.account_clock.connection.run_with_reconnect",
        AsyncMock(return_value=None),
    ):
        assert await resolve_meta_account_today("act_x", now=INSTANTE) == date(2026, 3, 10)


@pytest.mark.asyncio
async def test_fuso_invalido_cai_em_utc_sem_estourar() -> None:
    conta = SimpleNamespace(timezone_name="Nao/Existe")
    with patch(
        "src.meta_ads.account_clock.connection.run_with_reconnect",
        AsyncMock(return_value=conta),
    ):
        assert await resolve_meta_account_today("act_2", now=INSTANTE) == date(2026, 3, 10)


@pytest.mark.asyncio
async def test_le_o_campo_timezone_name_e_nao_time_zone() -> None:
    """A coluna Meta chama-se `timezone_name`; a Google, `time_zone`.

    Sem esta asserção, um resolvedor copiado do gêmeo Google leria `time_zone`,
    receberia `None` em toda conta, e cairia em UTC SEMPRE — verde nos outros
    testes que usam `SimpleNamespace`, porque um objeto sem o atributo levanta
    `AttributeError`, mas um com AMBOS não distingue. Aqui só existe o certo.
    """
    conta = SimpleNamespace(timezone_name="America/Manaus")  # UTC-4
    with patch(
        "src.meta_ads.account_clock.connection.run_with_reconnect",
        AsyncMock(return_value=conta),
    ):
        assert await resolve_meta_account_today("act_3", now=INSTANTE) == date(2026, 3, 9)
