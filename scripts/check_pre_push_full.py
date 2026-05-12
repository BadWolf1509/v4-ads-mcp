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
from _runner import (  # noqa: E402, type: ignore
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
