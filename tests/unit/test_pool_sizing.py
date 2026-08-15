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
async def test_init_pool_nao_depende_de_settings() -> None:
    """F92: `init_pool` é primitivo de banco — não pode exigir a config da app.

    A 1ª versão deste fix lia `get_settings()` dentro de `init_pool` e derrubou a
    suíte INTEIRA de integração: naquele ambiente o Settings não tem as 13
    variáveis obrigatórias, e a validação estourava antes mesmo de olhar os
    argumentos — que a conftest passava explicitamente. O default agora é uma
    constante do módulo.
    """
    from src.db import connection

    criar = AsyncMock(return_value=object())
    with (
        patch.object(connection, "_pool", None),
        patch("asyncpg.create_pool", criar),
        patch("src.config.get_settings", side_effect=AssertionError("nao pode ler Settings")),
    ):
        await connection.init_pool("postgres://fake")

    kwargs = criar.await_args.kwargs
    assert kwargs["max_size"] == connection.DEFAULT_POOL_MAX_SIZE
    assert kwargs["min_size"] == connection.DEFAULT_POOL_MIN_SIZE


def test_default_do_modulo_e_de_settings_nao_divergem() -> None:
    """F92: são duas fontes (constante pro job, Settings pro serviço) — se uma
    mudar sozinha, a conta de conexões deixa de valer pra metade do sistema."""
    from src.config import get_settings
    from src.db import connection

    settings = get_settings()
    assert settings.db_pool_max_size == connection.DEFAULT_POOL_MAX_SIZE
    assert settings.db_pool_min_size == connection.DEFAULT_POOL_MIN_SIZE


@pytest.mark.asyncio
async def test_app_dimensiona_o_pool_por_settings() -> None:
    """F92: quem serve tráfego é quem precisa da conta instâncias × pool."""
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
