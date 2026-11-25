"""M8: `admin invite` sem `--base-url` gerava link para localhost (o default antigo era produção)."""

from __future__ import annotations

import pytest

from src.scripts import admin


def test_invite_exige_base_url(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as saida:
        admin.main(["invite", "--email", "gestor@exemplo.com"])
    assert saida.value.code == 2
    assert "--base-url" in capsys.readouterr().err
