"""F92: o tamanho do pool era literal no código e não cabia no orçamento real.

`init_pool` tinha `max_size=10` hardcoded como default, e TODOS os call-sites
usavam o default. Contra `--max-instances=10` do Cloud Run, isso dá **até 100
conexões** — mais os pools próprios dos Cloud Run Jobs (resync, backup, migrate)
e o overlap de revisões durante um deploy. Tiers pequenos do Supabase têm
`max_connections=60`: estourar vira `too many connections`, que derruba o deep
health e as tools em cascata.

Nada no código documentava ou coordenava essa conta. Aqui o número sai pra
Settings — dá pra ajustar por env var sem tocar em código, e a aritmética
(instâncias × pool) fica escrita onde alguém vai procurar.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_init_pool_usa_os_valores_de_settings() -> None:
    """F92: o tamanho vem de Settings, não de um literal enterrado na função."""
    from src.db import connection

    criar = AsyncMock(return_value=object())
    with (
        patch.object(connection, "_pool", None),
        patch("asyncpg.create_pool", criar),
    ):
        await connection.init_pool("postgres://fake")

    kwargs = criar.await_args.kwargs
    from src.config import get_settings

    settings = get_settings()
    assert kwargs["max_size"] == settings.db_pool_max_size
    assert kwargs["min_size"] == settings.db_pool_min_size


@pytest.mark.asyncio
async def test_chamador_ainda_pode_forcar_um_tamanho() -> None:
    """Jobs/scripts podem querer um pool minúsculo — o override continua valendo."""
    from src.db import connection

    criar = AsyncMock(return_value=object())
    with (
        patch.object(connection, "_pool", None),
        patch("asyncpg.create_pool", criar),
    ):
        await connection.init_pool("postgres://fake", min_size=1, max_size=2)

    assert criar.await_args.kwargs["max_size"] == 2


def test_default_cabe_no_orcamento_de_conexoes_do_supabase() -> None:
    """F92: instâncias × pool tem que caber no teto do banco, com folga pros jobs.

    `--max-instances=10` no deploy.yml; tier pequeno do Supabase = 60 conexões.
    Este teste é a conta escrita — se alguém subir o pool sem subir o tier (ou
    sem baixar max-instances), quebra aqui e não em produção às 3 da manhã.
    """
    from src.config import get_settings

    max_instancias_cloud_run = 10  # deploy.yml --max-instances
    teto_supabase = 60
    folga_pra_jobs = 10  # resync/backup/migrate abrem pools próprios

    teto_do_servico = get_settings().db_pool_max_size * max_instancias_cloud_run
    assert teto_do_servico + folga_pra_jobs <= teto_supabase, (
        f"{teto_do_servico} conexões possíveis do serviço + {folga_pra_jobs} dos jobs "
        f"estouram o teto de {teto_supabase}. Suba o tier do Supabase, baixe "
        "DB_POOL_MAX_SIZE ou reduza --max-instances — mas escolha conscientemente."
    )
