#!/usr/bin/env python3
"""Fast pre-push gate. Runs lint + format + mypy + unit + non-DB integration.

Sequence (fail-fast):
    1. ruff e mypy instalados = os fixados no pyproject
    2. ruff check src tests
    3. ruff format --check src tests
    4. mypy src
    5. pytest tests/unit -m "not integration" -q
    6. pytest tests/integration -m "not integration" -q
    7. tailwind css sincronizado

For full sweep including DB integration tests (requires Docker), use:
    python scripts/check_pre_push_full.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _runner import BASE_STEPS, run_steps  # noqa: E402

if __name__ == "__main__":
    sys.exit(run_steps(BASE_STEPS))
