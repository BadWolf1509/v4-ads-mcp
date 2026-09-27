"""`record_actual_meta` registra so o MEDIDO (spec 2026-09-26, §5).

Antes: BUC nao entendido virava `throttle_pct=0`, gravado por cima do ultimo valor
medido — e o aviso de 75% nunca disparava sobre o que nao se leu. A quota do app, que
em chamada /insights vem no `x-fb-ads-insights-throttle`, nao era lida.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from structlog.testing import capture_logs

from src.governance import rate_limit


class _FakeAcquire:
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, *exc: object) -> None:
        return None


class _FakePool:
    def acquire(self) -> _FakeAcquire:
        return _FakeAcquire()


async def _registrar(**kwargs: Any) -> tuple[AsyncMock, AsyncMock, list[dict[str, Any]]]:
    incrementa, atualiza = AsyncMock(), AsyncMock()
    with (
        patch("src.db.connection.get_pool", return_value=_FakePool()),
        patch("src.db.repositories.meta_rate_counters.increment_calls", incrementa),
        patch("src.db.repositories.meta_rate_counters.update_throttle", atualiza),
        capture_logs() as logs,
    ):
        await rate_limit.record_actual_meta(app_id="app", ad_account_id="act_123", **kwargs)
    return incrementa, atualiza, logs


def _buc(pct: int) -> str:
    return json.dumps({"123": [{"call_count": pct, "total_cputime": 1, "total_time": 1}]})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("header", "motivo"),
    [(None, "ausente"), ("nao json", "nao_entendido"), ("{}", "nao_entendido")],
)
async def test_buc_nao_lido_nao_grava_throttle(header: str | None, motivo: str) -> None:
    """O ultimo valor medido fica; o que nao se leu vira evento, nao 0."""
    incrementa, atualiza, logs = await _registrar(buc_header=header)
    incrementa.assert_awaited_once()  # a chamada aconteceu e conta
    atualiza.assert_not_awaited()
    evento = next(e for e in logs if e["event"] == "meta_buc_nao_lido")
    assert evento["motivo"] == motivo


@pytest.mark.asyncio
async def test_buc_lido_grava_o_medido() -> None:
    _, atualiza, logs = await _registrar(buc_header=_buc(42))
    assert atualiza.await_args.kwargs["throttle_pct"] == 42
    assert not [e for e in logs if e["event"] == "meta_rate_limit_warning"]


@pytest.mark.asyncio
async def test_quota_do_app_acima_de_75_avisa_e_diz_qual() -> None:
    """F110: a quota que barra e a que tem menos folga — o aviso nomeia qual."""
    throttle = '{"app_id_util_pct": 80, "acc_id_util_pct": 3}'
    _, _, logs = await _registrar(buc_header=_buc(10), insights_throttle_header=throttle)
    aviso = next(e for e in logs if e["event"] == "meta_rate_limit_warning")
    assert aviso["acima_de_75"] == {"app_id_util_pct": 80.0}


@pytest.mark.asyncio
async def test_buc_da_conta_acima_de_75_segue_avisando() -> None:
    _, _, logs = await _registrar(buc_header=_buc(90))
    aviso = next(e for e in logs if e["event"] == "meta_rate_limit_warning")
    assert aviso["acima_de_75"] == {"buc_conta_pct": 90.0}
