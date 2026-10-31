"""O hook executa de verdade: regex lida nao prova o que o PowerShell casa."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

_HOOK = Path(__file__).resolve().parents[2] / ".claude" / "hooks" / "guard-bash.ps1"
_SHELL = shutil.which("pwsh") or shutil.which("powershell")

if _SHELL is None and os.environ.get("CI"):
    pytest.fail("CI sem PowerShell: o guard nao seria exercitado", pytrace=False)
pytestmark = pytest.mark.skipif(_SHELL is None, reason="sem PowerShell")


def _negado(comando: str) -> bool:
    assert _SHELL is not None
    r = subprocess.run(
        [_SHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(_HOOK)],
        input=json.dumps({"tool_input": {"command": comando}}),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert r.returncode == 0, r.stderr
    return '"deny"' in r.stdout.replace(" ", "")


@pytest.mark.parametrize(
    "comando",
    [
        "python scripts/check_pre_push.py | tail && git commit -m x",
        "python scripts/check_pre_push.py > log; tail log; git add -A && git commit -m x",
        "python scripts/check_pre_push_full.py > log\ngit commit -m x",
        "gcloud run services list 2>/dev/null",
        "gcloud secrets list --project=x 2>$null",
        "git checkout -- src/a.py",
        "git checkout HEAD -- src/a.py",
        "git checkout src/web/v4-panel.js",
        "git checkout .",
        "until grep -q ok log 2>/dev/null; do sleep 4; done",
        "cd x && until test -f y; do sleep 1; done",
        "while true; do sleep 5; done",
    ],
)
def test_comando_perigoso_e_negado(comando: str) -> None:
    assert _negado(comando)


@pytest.mark.parametrize(
    "comando",
    [
        "python scripts/check_pre_push.py > log 2>&1 && git add a.py && git commit -m x",
        "python scripts/check_pre_push.py > log 2>&1 | tail -3",
        "git commit -q -F - <<'MSG'\ngate | tail; git checkout -- a.py\nMSG",
        "gcloud run services list",
        "curl x 2>/dev/null; gcloud run services list",
        "git checkout main",
        "git checkout -b fix/confirm-sem-alvo",
        "git checkout feat/htmx-local",
        "ls | grep x && echo ok",
        "timeout 590 bash -c 'until gh pr view 1; do sleep 20; done'",
        "for i in 1 2 3; do sleep 1; done",
        "while read l; do echo $l; done < arquivo",
        "echo until amanha",
    ],
)
def test_comando_legitimo_passa(comando: str) -> None:
    assert not _negado(comando)
