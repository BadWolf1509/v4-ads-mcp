"""Pre-push gate runner. Shared between check-pre-push.py and
check-pre-push-full.py."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Step:
    """One step in a pre-push gate sequence."""

    name: str
    cmd: list[str]


# Pre-defined step lists
BASE_STEPS: list[Step] = [
    Step("ruff check", [sys.executable, "-m", "ruff", "check", "src", "tests"]),
    Step("ruff format check", [sys.executable, "-m", "ruff", "format", "--check", "src", "tests"]),
    Step("mypy", [sys.executable, "-m", "mypy", "src"]),
    # 'not integration' filter mirrors CI behavior (CI runs unit + non-DB
    # integration in one step). Filter exclui any test marked
    # @pytest.mark.integration even if accidentally placed in tests/unit/ —
    # defensive: convention is to live in tests/integration/ but marker is
    # the authoritative signal.
    Step(
        "pytest unit", [sys.executable, "-m", "pytest", "tests/unit", "-m", "not integration", "-q"]
    ),
    Step(
        "pytest non-DB integration",
        [sys.executable, "-m", "pytest", "tests/integration", "-m", "not integration", "-q"],
    ),
]

DB_INTEGRATION_STEP = Step(
    "pytest DB integration",
    [sys.executable, "-m", "pytest", "tests/integration", "-m", "integration", "-q"],
)


def _color(text: str, code: str) -> str:
    """Wrap text in ANSI color code if stdout is a TTY, else return plain."""
    if sys.stdout.isatty():
        return f"\033[{code}m{text}\033[0m"
    return text


def _chdir_repo_root() -> None:
    """Ensure cwd is repo root, regardless of where script was invoked from."""
    repo_root = Path(__file__).resolve().parent.parent
    os.chdir(repo_root)


def run_steps(steps: list[Step]) -> int:
    """Run steps sequentially, fail-fast. Returns 0 if all pass, 1 if any fails."""
    _chdir_repo_root()
    total = len(steps)
    start = time.perf_counter()
    for i, step in enumerate(steps, start=1):
        print(_color(f"==> [{i}/{total}] {step.name}", "36"))  # cyan
        result = subprocess.run(step.cmd)
        if result.returncode != 0:
            print(_color(f"FAILED: {step.name}", "31"), file=sys.stderr)  # red
            print(
                f"   Run individually to debug: {' '.join(step.cmd)}",
                file=sys.stderr,
            )
            elapsed = time.perf_counter() - start
            print(
                _color(
                    f"FAILED at step {i}/{total} ({step.name}) after {elapsed:.1f}s.",
                    "31",
                ),
                file=sys.stderr,
            )
            return 1
        print(_color(f"OK: {step.name}", "32"))  # green
    elapsed = time.perf_counter() - start
    print(
        _color(
            f"All pre-push checks passed ({total} steps in {elapsed:.1f}s).",
            "32",
        )
    )
    return 0


def check_docker() -> tuple[bool, str]:
    """Probe Docker daemon. Returns (ok, hint_if_not_ok).

    Returns (True, "") if daemon responds to 'docker info' within 2s.
    Returns (False, hint) for FileNotFoundError (CLI missing),
    TimeoutExpired (daemon hung), or non-zero exit (daemon off).
    """
    hint_off = (
        "Docker Desktop nao esta rodando. Start Docker e re-rode "
        "'python scripts/check_pre_push_full.py'."
    )
    try:
        result = subprocess.run(
            ["docker", "info"],
            timeout=2,
            capture_output=True,
        )
    except FileNotFoundError:
        return False, "Docker CLI nao encontrado no PATH. Instale Docker Desktop."
    except subprocess.TimeoutExpired:
        return False, hint_off
    if result.returncode == 0:
        return True, ""
    return False, hint_off
