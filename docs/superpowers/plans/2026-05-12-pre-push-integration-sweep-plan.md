# Pre-push integration sweep — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship 2 Python scripts (`scripts/check-pre-push.py` fast default + `scripts/check-pre-push-full.py` opt-in Docker-required) to close Sprint 3b.5 gate gap, plus marker fix em `test_update_ad_status.py` que é pré-requisito do fast script funcionar localmente.

**Architecture:** Standalone script versionado approach (não git hook). `_runner.py` é o motor compartilhado (Step dataclass + run_steps fail-fast + check_docker probe). Two thin entries top-level. Fail-fast sequential. ANSI colors com TTY detection. Sem novas deps.

**Tech Stack:** Python 3.13 stdlib only (subprocess, dataclasses, pathlib, sys, os, time). Existing pytest infra. No new requirements.

**Reference spec:** `docs/superpowers/specs/2026-05-12-pre-push-integration-sweep-design.md` (commit `88912ab`)

---

## Task 1: Marker fix em test_update_ad_status.py (pré-requisito)

**Why first:** Step 5 do fast script roda `pytest tests/integration -m "not integration"`. Hoje `test_update_ad_status.py` usa `testcontainers.PostgresContainer` mas não tem o marker `integration`, então é coletado por esse step. Sem Docker, o fixture testcontainers trava. Esta task corrige o marker antes de criar o script, evitando smoke confuso na Task 3.

**Files:**
- Modify: `tests/integration/test_update_ad_status.py:1-15` (add `pytestmark` after imports)

**Model:** haiku (mechanical one-line edit)

- [ ] **Step 1: Read current file head to find insertion point**

Run: `python -c "print(open('tests/integration/test_update_ad_status.py').read()[:500])"`
Expected: see imports block, no existing `pytestmark`.

- [ ] **Step 2: Add `pytestmark = pytest.mark.integration` after imports**

Edit `tests/integration/test_update_ad_status.py` — add this line at module top-level immediately after the `import pytest` line (or add the import if missing):

```python
pytestmark = pytest.mark.integration
```

- [ ] **Step 3: Verify marker excludes the file from non-DB collection**

Run: `pytest tests/integration/test_update_ad_status.py -m "not integration" --collect-only -q`
Expected: `no tests ran in 0.XXs` ou `5 deselected` (a file não aparece como coletado).

- [ ] **Step 4: Verify marker includes the file in DB-integration collection**

Run: `pytest tests/integration/test_update_ad_status.py -m integration --collect-only -q`
Expected: tests listed (≥1 test collected with marker).

- [ ] **Step 5: Run ruff + mypy (no actual test execution — Docker off)**

Run: `python -m ruff check tests/integration/test_update_ad_status.py && python -m ruff format --check tests/integration/test_update_ad_status.py`
Expected: zero issues.

- [ ] **Step 6: Commit**

```bash
git add tests/integration/test_update_ad_status.py
git commit -m "$(cat <<'EOF'
fix(tests): add missing pytest.mark.integration marker

test_update_ad_status.py uses testcontainers.PostgresContainer but lacked
the @pytest.mark.integration marker, so 'pytest -m "not integration"'
would collect it and hang waiting for Docker. Required for P2 pre-push
fast script (which runs that exact filter and must work without Docker).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `scripts/_runner.py` + unit tests (TDD core)

**Why TDD:** `_runner.py` is the only piece com lógica não-trivial (fail-fast sequence, Docker probe with timeout/FileNotFoundError handling, color toggling). Tests verify behavior independent of real subprocess execution.

**Files:**
- Create: `scripts/__init__.py` (empty — makes scripts/ importable)
- Create: `scripts/_runner.py`
- Create: `tests/unit/test_pre_push_runner.py`

**Model:** sonnet (TDD with mock subprocess, monkeypatch, multiple assertions per test)

- [ ] **Step 1: Create empty `scripts/__init__.py`**

```bash
mkdir -p scripts
touch scripts/__init__.py
```

Verify: `ls scripts/` shows `__init__.py`.

- [ ] **Step 2: Write all 7 failing unit tests**

Create `tests/unit/test_pre_push_runner.py`:

```python
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

from _runner import Step, check_docker, run_steps  # noqa: E402


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
    """docker info timeout (>2s) → (False, hint)."""

    def hang(*a: object, **kw: object) -> SimpleNamespace:
        raise subprocess.TimeoutExpired(cmd="docker", timeout=2)

    monkeypatch.setattr("subprocess.run", hang)
    ok, hint = check_docker()
    assert ok is False
```

- [ ] **Step 3: Run tests, verify ImportError (no module yet)**

Run: `python -m pytest tests/unit/test_pre_push_runner.py -v`
Expected: collection or import errors — module `_runner` doesn't exist yet.

- [ ] **Step 4: Implement `scripts/_runner.py`**

Create `scripts/_runner.py`:

```python
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
    Step("ruff check", ["ruff", "check", "src", "tests"]),
    Step("ruff format check", ["ruff", "format", "--check", "src", "tests"]),
    Step("mypy", ["mypy", "src"]),
    Step("pytest unit", ["pytest", "tests/unit", "-q"]),
    Step(
        "pytest non-DB integration",
        ["pytest", "tests/integration", "-m", "not integration", "-q"],
    ),
]

DB_INTEGRATION_STEP = Step(
    "pytest DB integration",
    ["pytest", "tests/integration", "-m", "integration", "-q"],
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
            print(_color(f"❌ {step.name} FAILED", "31"), file=sys.stderr)  # red
            print(
                f"   Run individually to debug: {' '.join(step.cmd)}",
                file=sys.stderr,
            )
            elapsed = time.perf_counter() - start
            print(
                _color(
                    f"❌ Pre-push check FAILED at step {i}/{total} "
                    f"({step.name}) after {elapsed:.1f}s.",
                    "31",
                ),
                file=sys.stderr,
            )
            return 1
        print(_color(f"✅ {step.name} OK", "32"))  # green
    elapsed = time.perf_counter() - start
    print(
        _color(
            f"✅ All pre-push checks passed ({total} steps in {elapsed:.1f}s).",
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
        "Docker Desktop não está rodando. Start Docker e re-rode "
        "'python scripts/check-pre-push-full.py'."
    )
    try:
        result = subprocess.run(
            ["docker", "info"],
            timeout=2,
            capture_output=True,
        )
    except FileNotFoundError:
        return False, "Docker CLI não encontrado no PATH. Instale Docker Desktop."
    except subprocess.TimeoutExpired:
        return False, hint_off
    if result.returncode == 0:
        return True, ""
    return False, hint_off
```

- [ ] **Step 5: Run tests, verify all pass**

Run: `python -m pytest tests/unit/test_pre_push_runner.py -v`
Expected: 7 passed.

- [ ] **Step 6: Run lint + format + mypy on new files**

Run: `python -m ruff check scripts tests/unit/test_pre_push_runner.py && python -m ruff format --check scripts tests/unit/test_pre_push_runner.py && python -m mypy scripts`
Expected: zero issues. If ruff format complains, auto-fix with `python -m ruff format scripts tests/unit/test_pre_push_runner.py` and retry.

- [ ] **Step 7: Commit**

```bash
git add scripts/__init__.py scripts/_runner.py tests/unit/test_pre_push_runner.py
git commit -m "$(cat <<'EOF'
feat(scripts): _runner.py — shared engine for pre-push gate scripts

Step dataclass (frozen) + run_steps() fail-fast sequencer + check_docker()
probe with 2s timeout. Used by check-pre-push.py (fast default) and
check-pre-push-full.py (opt-in Docker-required full sweep).

7 unit tests cover: Step immutability, run_steps pass + fail-fast paths,
check_docker daemon-on/off/timeout/CLI-missing.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Entry scripts (fast + full)

**Why no tests:** entry scripts são thin wrappers (1-3 LOC of logic each — just call `run_steps()` with pre-built step lists, or check Docker then run_steps). Smoke validation manual no Step 4 do plan é suficiente. Adding unit tests for entries would duplicate `_runner.py` coverage.

**Files:**
- Create: `scripts/check-pre-push.py`
- Create: `scripts/check-pre-push-full.py`

**Model:** haiku (mechanical thin entries with hardcoded behavior)

- [ ] **Step 1: Create `scripts/check-pre-push.py`**

```python
#!/usr/bin/env python3
"""Fast pre-push gate. Runs lint + format + mypy + unit + non-DB integration.

Sequence (fail-fast):
    1. ruff check src tests
    2. ruff format --check src tests
    3. mypy src
    4. pytest tests/unit -q
    5. pytest tests/integration -m "not integration" -q

For full sweep including DB integration tests (requires Docker), use:
    python scripts/check-pre-push-full.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _runner import BASE_STEPS, run_steps  # noqa: E402


if __name__ == "__main__":
    sys.exit(run_steps(BASE_STEPS))
```

- [ ] **Step 2: Create `scripts/check-pre-push-full.py`**

```python
#!/usr/bin/env python3
"""Full pre-push gate. Base steps + DB integration tests (Docker required).

Sequence (fail-fast):
    pre-check: docker info (timeout 2s)
    1-5:       base steps (ruff/format/mypy/unit/non-DB integration)
    6:         pytest tests/integration -m integration -q  (testcontainers)

Exit codes:
    0  all checks passed
    1  any step failed
    2  Docker Desktop not running (pre-check)

If Docker is off, exits with hint without running any step (Pergunta 4 = A).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _runner import (  # noqa: E402
    BASE_STEPS,
    DB_INTEGRATION_STEP,
    check_docker,
    run_steps,
)


def main() -> int:
    ok, hint = check_docker()
    if not ok:
        print(f"❌ {hint}", file=sys.stderr)
        return 2
    return run_steps([*BASE_STEPS, DB_INTEGRATION_STEP])


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Manual smoke — fast script**

Run: `python scripts/check-pre-push.py`
Expected output:
```
==> [1/5] ruff check
✅ ruff check OK
==> [2/5] ruff format check
✅ ruff format check OK
==> [3/5] mypy
✅ mypy OK
==> [4/5] pytest unit
... (many tests) ...
✅ pytest unit OK
==> [5/5] pytest non-DB integration
... (tests) ...
✅ pytest non-DB integration OK
✅ All pre-push checks passed (5 steps in ~15s).
```
Exit code: 0. If any step fails, fix the issue before proceeding (real bugs caught are real bugs to fix).

- [ ] **Step 4: Manual smoke — full script with Docker off**

Verify Docker is off: `docker version 2>&1 | grep -i "cannot find"` (expect text indicating daemon not running).
Run: `python scripts/check-pre-push-full.py`
Expected output:
```
❌ Docker Desktop não está rodando. Start Docker e re-rode 'python scripts/check-pre-push-full.py'.
```
Exit code: 2 (`echo $?` or `$LASTEXITCODE` em PowerShell).

If Docker happens to be on locally, run anyway — expect full 6-step sequence including the DB integration step (which may take 30-60s). Verify exit code 0 on success.

- [ ] **Step 5: Lint + format + mypy on new files**

Run: `python -m ruff check scripts && python -m ruff format --check scripts && python -m mypy scripts`
Expected: zero issues.

- [ ] **Step 6: Commit**

```bash
git add scripts/check-pre-push.py scripts/check-pre-push-full.py
git commit -m "$(cat <<'EOF'
feat(scripts): check-pre-push.py + check-pre-push-full.py entry scripts

Two thin entries calling into _runner.py:

- check-pre-push.py: fast default (5 steps, no Docker, ~15s)
- check-pre-push-full.py: full sweep (6 steps, Docker required, ~60-90s).
  Pre-checks Docker via 'docker info' with 2s timeout. Exit 2 if Docker
  Desktop off, with hint string in PT-BR.

Smoke validated locally: fast script passes 5/5 on current main; full
script exits 2 with hint when Docker daemon down.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: CLAUDE.md update + sign-off

**Files:**
- Modify: `CLAUDE.md` (Verification cadence section ~line 95-105 + Don't do section)

**Model:** sonnet (judgment about exact phrasing, scan whole doc for consistency)

- [ ] **Step 1: Update "Verification cadence" section**

Find the section starting `### Verification cadence (always before commit)` and replace its body with:

```markdown
### Verification cadence (always before commit)

```bash
python scripts/check-pre-push.py
```

Roda em sequência (fail-fast): ruff check → ruff format check → mypy → pytest
unit → pytest non-DB integration. ~15s. Sem Docker.

Opt-in full sweep (requer Docker Desktop rodando):

```bash
python scripts/check-pre-push-full.py
```

Adiciona um 6º step (`pytest tests/integration -m integration`) com
testcontainers. ~60-90s. Use antes de push quando mudou mutate flow ou
qualquer caminho exercitado por DB integration tests. Sem Docker, exit 2
com hint clara — não silenciosamente skipa.

Se algum step do fast script falhar, corrija e re-rode. Comandos individuais
listados em `scripts/_runner.py` para debug isolado.
```

- [ ] **Step 2: Update "Don't do" section**

Find `## Don't do` and add this bullet (preserve existing bullets):

```markdown
- Don't push to main without running `python scripts/check-pre-push.py` first. CI catches lint/type/test failures but wastes a deploy cycle and may trigger rollback if integration tests reveal a bug. Lesson Sprint 3b.5: gate gap (apenas unit pre-push) deixou 2 integration tests quebrados escaparem para CI.
```

Place it between the existing first bullet (about ruff format) and the dependencies bullet — order não é crítico, mas perto da verification guidance.

- [ ] **Step 3: Update "Last updated" date if older than today**

Find `**Last updated:** 2026-05-12` — confirm it's today's date. If not, update.

- [ ] **Step 4: Final fast script run before push**

Run: `python scripts/check-pre-push.py`
Expected: all 5 steps pass, exit 0. This is also the dogfood validation — first real use of the new gate is gating its own merge.

- [ ] **Step 5: Commit + push**

```bash
git add CLAUDE.md
git commit -m "$(cat <<'EOF'
docs(claude): P2 — update Verification cadence to use scripts/check-pre-push.py

Substitui os 4 comandos manuais (ruff/format/mypy/unit) por single entry
'python scripts/check-pre-push.py' que adicionalmente roda non-DB integration
sweep — fechando o gap descoberto em Sprint 3b.5.

Opt-in full sweep documentado: 'python scripts/check-pre-push-full.py'
(requer Docker Desktop, +pytest -m integration step).

"Don't do" section atualizada com bullet sobre não pushar sem rodar o gate.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
git push origin main
```

- [ ] **Step 6: Watch CI**

Run: `gh run watch $(gh run list --limit 1 --json databaseId --jq '.[0].databaseId')`
Expected: CI test job passes (same suite the local script ran). Deploy is a no-op since no MCP src changes.

- [ ] **Step 7: Update todo + summary back to user**

Sprint P2 complete:
- 3 commits on main (marker fix + `_runner.py` + entries) + 1 sign-off commit (CLAUDE.md)
- 7 unit tests added + 1 marker fix
- Zero new MCP tools (tool count stays at 39)
- New "fast" gate runs in ~15s, opt-in "full" gate in ~60-90s with Docker

---

## Self-review checklist

After all tasks complete, verify:

- [ ] `python scripts/check-pre-push.py` runs clean from a fresh terminal
- [ ] `python scripts/check-pre-push-full.py` (Docker off) returns exit 2 with hint
- [ ] All 7 `_runner.py` unit tests pass
- [ ] CI green on the push containing CLAUDE.md update
- [ ] No regressions: existing CI test split still works (`pytest -m "not integration"` no longer collects `test_update_ad_status.py`; `pytest -m integration` does)
- [ ] CLAUDE.md "Verification cadence" no longer lists the 4 individual commands

## Files affected (recap)

```
scripts/                                       # NEW directory
├── __init__.py                                # Task 2: empty
├── _runner.py                                 # Task 2: shared engine
├── check-pre-push.py                          # Task 3: fast entry
└── check-pre-push-full.py                     # Task 3: full entry

tests/
├── unit/
│   └── test_pre_push_runner.py                # Task 2: 7 unit tests
└── integration/
    └── test_update_ad_status.py               # Task 1: add pytestmark

CLAUDE.md                                      # Task 4: cadence + don't do
```

**Net delta:** ~150 LOC source + ~80 LOC test + ~10 LOC docs. 4 commits.

## Out of scope (recap from spec)

- Git hooks auto-install — manual run, no install script
- Parallel step execution — sequential fail-fast
- Pretty output libs (rich, etc) — stdlib ANSI
- Configurable step list via TOML/YAML — hardcoded in `_runner.py`
- Auto-detect Docker boot + retry — loud fail by design
- Smoke runbook em conta real — this is internal tooling, no MCP behavior change

## Risks & rollback

| Risk | Mitigation |
|---|---|
| Marker fix breaks CI matrix | CI split unchanged — test just moves from job 1 to job 2. Verified by `--collect-only` checks in Task 1 Steps 3-4. |
| Script fails on Windows path | Smoke in Task 3 Steps 3-4 done on Wellington's Windows box. If breaks, fix inline before Task 4. |
| CLAUDE.md formatting breaks | Markdown is human-rendered, no parser dependency. Visual review post-edit. |

**Rollback:** if any task lands broken in main, revert the relevant commit. No DB migrations, no production state changes — full rollback is `git revert <sha> && git push`.
