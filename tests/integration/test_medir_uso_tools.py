"""`scripts/medir_uso_tools.py` contra Postgres real: SQL e transação só de leitura."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from uuid import uuid4

import asyncpg
import pytest

from scripts.medir_uso_tools import FUSO, coletar, coletar_aplicacoes

_INICIO = date(2026, 11, 1)
_FIM = date(2026, 11, 15)


def _em(dia: int, hora: int, minuto: int = 0) -> datetime:
    return datetime(2026, 11, dia, hora, minuto, tzinfo=FUSO)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_coleta_roda_em_transacao_so_de_leitura(db: Any) -> None:
    mid = uuid4()
    sid = uuid4()
    async with db.acquire() as conn:
        await conn.execute(
            "INSERT INTO managers (id, email, status, role) "
            "VALUES ($1, 'gestor@v4company.com', 'active', 'gestor')",
            mid,
        )
        await conn.execute(
            "INSERT INTO mcp_sessions (id, manager_id, label, token_hash) "
            "VALUES ($1, $2, 't', 'h')",
            sid,
            mid,
        )
        linhas = [
            # Leitura com sucesso: conta.
            ("read", "get_funnel_metrics", "success", None, _em(10, 9)),
            # Preview de mutação e a aplicação 3 min depois (via apply_change).
            ("mutate", "update_ad_status", "success", True, _em(12, 10)),
            ("mutate", "update_ad_status", "success", None, _em(12, 10, 3)),
            # Leitura de pré-voo sob o nome da tool de mutação: não é aplicação.
            ("read", "update_ad_status", "success", None, _em(12, 9, 59)),
            # Fora da janela (dia anterior ao início, em Brasília): não conta.
            ("read", "get_funnel_metrics", "success", None, _em(1, 0) - timedelta(minutes=1)),
        ]
        for action_type, operation, status, dry_run, quando in linhas:
            await conn.execute(
                "INSERT INTO audit_log (manager_id, session_id, customer_id, action_type, "
                "operation, status, dry_run, occurred_at) "
                "VALUES ($1, $2, '1234567890', $3, $4, $5, $6, $7)",
                mid,
                sid,
                action_type,
                operation,
                status,
                dry_run,
                quando,
            )
        await conn.execute(
            "INSERT INTO pending_confirmations (token, session_id, customer_id, "
            "operation_type, payload, blast_summary, expires_at, consumed_at) "
            "VALUES ('ABCD1234', $1, '1234567890', 'update_ad_status', '{}'::jsonb, "
            "'x', $2, $3)",
            sid,
            _em(12, 10, 10),
            _em(12, 10, 3),
        )

    async with db.acquire() as conn:
        async with conn.transaction(readonly=True):
            uso = {u.operation: u for u in await coletar(conn, inicio=_INICIO, fim=_FIM)}
            aplicacoes = await coletar_aplicacoes(conn, inicio=_INICIO, fim=_FIM)

        assert set(uso) == {"get_funnel_metrics", "update_ad_status"}
        funil = uso["get_funnel_metrics"]
        assert (funil.linhas, funil.linhas_preview, funil.sucesso, funil.gestores) == (1, 0, 1, 1)
        assert funil.primeira_sucesso == _em(10, 9)
        mutacao = uso["update_ad_status"]
        assert (mutacao.linhas, mutacao.linhas_preview) == (2, 1)
        assert (mutacao.linhas_mutacao, mutacao.sucesso_mutacao) == (1, 1)
        assert aplicacoes.via_pendencias == 1
        assert aplicacoes.gestores_pendencias == 1
        assert aplicacoes.ultima_pendencia == _em(12, 10, 3)
        assert aplicacoes.via_audit == 1

        # Controle: a transação do script é mesmo só de leitura.
        with pytest.raises(asyncpg.exceptions.ReadOnlySQLTransactionError):
            async with conn.transaction(readonly=True):
                await coletar(conn, inicio=_INICIO, fim=_FIM)
                await conn.execute(
                    "INSERT INTO audit_log (action_type, operation, status) "
                    "VALUES ('read', 'x', 'success')"
                )
