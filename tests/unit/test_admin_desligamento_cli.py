"""Subcomandos de desligamento do `admin`: dry-run por padrão, `--apply` só quando pedido."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.scripts import admin


@pytest.fixture
def sem_banco(monkeypatch: pytest.MonkeyPatch) -> None:
    @asynccontextmanager
    async def _falsa() -> AsyncIterator[Any]:
        yield MagicMock()

    monkeypatch.setattr(admin, "_conexao", _falsa)


@pytest.mark.parametrize(("argv", "apply"), [([], False), (["--apply"], True)])
def test_revogar_conexoes_dry_run_por_padrao(
    sem_banco: None, monkeypatch: pytest.MonkeyPatch, argv: list[str], apply: bool
) -> None:
    nucleo = AsyncMock(return_value=[])
    monkeypatch.setattr(admin.desligamento, "revogar_conexoes_de_inativos", nucleo)
    assert admin.main(["revogar-conexoes-de-inativos", *argv]) == 0
    assert nucleo.call_args.kwargs == {"apply": apply}
