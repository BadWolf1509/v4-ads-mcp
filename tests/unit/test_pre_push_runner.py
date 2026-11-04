"""Unit tests for scripts/_runner.py."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace

import pytest

# Make scripts/ importable for tests
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))

from _runner import DOCKER_INFO_TIMEOUT_S, Step, check_docker, run_steps  # noqa: E402


def test_step_is_frozen() -> None:
    """Step dataclass is immutable (frozen=True)."""
    s = Step("ruff", ["ruff", "check"])
    with pytest.raises(FrozenInstanceError):
        s.name = "different"  # type: ignore[misc]


def test_run_steps_returns_0_when_all_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    """All subprocess calls return 0 → run_steps returns 0."""
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **kw: SimpleNamespace(returncode=0),
    )
    steps = [Step("a", ["echo", "a"]), Step("b", ["echo", "b"])]
    assert run_steps(steps) == 0


def test_run_steps_fail_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    """First failing step stops execution; subsequent steps don't run."""
    calls: list[str] = []

    def fake_run(args: list[str], **kw: object) -> SimpleNamespace:
        calls.append(args[0])
        # 'first' passes, 'second' fails, 'third' should never run
        return SimpleNamespace(returncode=0 if args[0] == "first" else 1)

    monkeypatch.setattr("subprocess.run", fake_run)
    steps = [
        Step("a", ["first"]),
        Step("b", ["second"]),
        Step("c", ["third"]),
    ]
    rc = run_steps(steps)
    assert rc == 1
    assert calls == ["first", "second"]  # third never invoked


def test_check_docker_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    """docker info returncode 0 → (True, '')."""
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **kw: SimpleNamespace(returncode=0),
    )
    ok, hint = check_docker()
    assert ok is True
    assert hint == ""


def test_check_docker_daemon_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """docker info returncode != 0 → (False, hint about Docker Desktop)."""
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **kw: SimpleNamespace(returncode=1),
    )
    ok, hint = check_docker()
    assert ok is False
    assert "Docker Desktop" in hint


def test_check_docker_not_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    """docker CLI missing (FileNotFoundError) → (False, hint about install)."""

    def boom(*a: object, **kw: object) -> SimpleNamespace:
        raise FileNotFoundError("docker not found")

    monkeypatch.setattr("subprocess.run", boom)
    ok, hint = check_docker()
    assert ok is False
    assert "Docker CLI" in hint or "instale" in hint.lower()


def test_check_docker_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """docker info timeout → (False, hint que diz que o daemon nao respondeu)."""

    def hang(*a: object, **kw: object) -> SimpleNamespace:
        raise subprocess.TimeoutExpired(cmd="docker", timeout=DOCKER_INFO_TIMEOUT_S)

    monkeypatch.setattr("subprocess.run", hang)
    ok, hint = check_docker()
    assert ok is False
    assert f"{DOCKER_INFO_TIMEOUT_S}s" in hint


def test_check_docker_espera_o_daemon_lento(monkeypatch: pytest.MonkeyPatch) -> None:
    """O timeout passado ao docker info cobre o engine de pe medido em 03/11.

    Com o engine respondendo, `docker info` levou 2,5-3,4 s nesta maquina; o
    teto antigo de 2 s abortava o full sweep com o Docker funcionando.
    """
    vistos: list[object] = []

    def fake_run(*a: object, **kw: object) -> SimpleNamespace:
        vistos.append(kw.get("timeout"))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("subprocess.run", fake_run)
    assert check_docker() == (True, "")
    assert vistos == [DOCKER_INFO_TIMEOUT_S]
    assert DOCKER_INFO_TIMEOUT_S >= 10
