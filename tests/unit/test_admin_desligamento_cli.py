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
    monkeypatch.setattr(admin, "_autor_admin", AsyncMock(return_value="ADMIN_ID"))
    assert admin.main(["revogar-conexoes-de-inativos", "--by", "a@x.com", *argv]) == 0
    assert nucleo.call_args.kwargs == {"apply": apply, "por": "ADMIN_ID"}


@pytest.mark.parametrize(("argv", "apply"), [([], False), (["--apply"], True)])
def test_descomissionar_dry_run_por_padrao(
    sem_banco: None, monkeypatch: pytest.MonkeyPatch, argv: list[str], apply: bool
) -> None:
    nucleo = AsyncMock(return_value=admin.desligamento.Descomissionamento())
    monkeypatch.setattr(admin.desligamento, "descomissionar", nucleo)
    monkeypatch.setattr(admin, "_autor_admin", AsyncMock(return_value="ADMIN_ID"))
    rc = admin.main(
        [
            "descomissionar",
            "--by",
            "a@x.com",
            "--manter-google",
            "1",
            "2",
            "--manter-meta",
            "act_3",
            *argv,
        ]
    )
    assert rc == 0
    assert nucleo.call_args.kwargs == {
        "manter_google": ["1", "2"],
        "manter_meta": ["act_3"],
        "apply": apply,
        "por": "ADMIN_ID",
    }


def test_descomissionar_com_id_invalido_sai_2(
    sem_banco: None, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    nucleo = AsyncMock(return_value=admin.desligamento.Descomissionamento(invalidos=["9"]))
    monkeypatch.setattr(admin.desligamento, "descomissionar", nucleo)
    monkeypatch.setattr(admin, "_autor_admin", AsyncMock(return_value="ADMIN_ID"))
    rc = admin.main(
        ["descomissionar", "--by", "a@x.com", "--manter-google", "9", "--manter-meta", "act_3"]
    )
    assert rc == 2
    assert "9" in capsys.readouterr().err


@pytest.mark.parametrize(
    "argv",
    [
        ["revogar-conexoes-de-inativos", "--by", "nao-admin@x.com", "--apply"],
        ["descomissionar", "--by", "nao-admin@x.com", "--manter-google", "1", "--manter-meta", "a"],
    ],
)
def test_by_que_nao_e_admin_ativo_sai_1_sem_chamar_o_nucleo(
    sem_banco: None, monkeypatch: pytest.MonkeyPatch, argv: list[str]
) -> None:
    monkeypatch.setattr(admin, "_autor_admin", AsyncMock(return_value=None))
    nucleos = AsyncMock()
    monkeypatch.setattr(admin.desligamento, "revogar_conexoes_de_inativos", nucleos)
    monkeypatch.setattr(admin.desligamento, "descomissionar", nucleos)
    assert admin.main(argv) == 1
    nucleos.assert_not_awaited()
