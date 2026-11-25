"""Meta desligada explícita (META_HABILITADA=false): a etapa Meta do resync registra e não derruba o job.

Antes (25/11, audits 12862/12867/12872/12877): com a Meta desligada de propósito, a etapa
gravava `meta_reconcile` com erro "token do system user nao configurado" e o job saía com 1
todo dia — o retry repetia 4 vezes e o alerta de job falho viraria ruído diário.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config import Settings
from src.jobs import account_resync
from tests.unit.fixtures.fake_pool import FakePool


def _settings(monkeypatch: pytest.MonkeyPatch, **env: str) -> Settings:
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return Settings()  # type: ignore[call-arg]


@pytest.mark.asyncio
async def test_meta_desligada_grava_audit_e_nao_falha(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(monkeypatch, META_HABILITADA="false")
    reconcile = AsyncMock()
    record = AsyncMock()
    with (
        patch("src.jobs.meta_resync.reconcile_meta", reconcile),
        patch.object(account_resync, "record_job_run", record),
    ):
        falhou = await account_resync._etapa_meta(FakePool(MagicMock()), settings)

    assert falhou is False
    reconcile.assert_not_awaited()
    record.assert_awaited_once()
    kw = record.call_args.kwargs
    assert kw["operation"] == "meta_reconcile"
    assert kw["platform"] == "meta"
    assert kw["status"] == "success"
    assert kw["params_summary"] == {"desligada": True}


@pytest.mark.asyncio
async def test_meta_desligada_vence_bm_configurado(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(monkeypatch, META_HABILITADA="false", META_BUSINESS_ID="123")
    reconcile = AsyncMock()
    with (
        patch("src.jobs.meta_resync.reconcile_meta", reconcile),
        patch.object(account_resync, "record_job_run", AsyncMock()),
    ):
        assert await account_resync._etapa_meta(FakePool(MagicMock()), settings) is False
    reconcile.assert_not_awaited()


@pytest.mark.asyncio
async def test_meta_habilitada_por_padrao_chama_reconcile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("META_HABILITADA", raising=False)
    settings = _settings(monkeypatch)
    assert settings.meta_habilitada is True
    plano = MagicMock(to_add=[], to_remove=[], blocked_reason=None)
    reconcile = AsyncMock(return_value=plano)
    with patch("src.jobs.meta_resync.reconcile_meta", reconcile):
        assert await account_resync._etapa_meta(FakePool(MagicMock()), settings) is False
    reconcile.assert_awaited_once()
