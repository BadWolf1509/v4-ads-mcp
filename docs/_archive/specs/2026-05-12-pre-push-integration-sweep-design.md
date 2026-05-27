# Pre-push integration sweep — Design

**Date:** 2026-05-12
**Author:** Claude (Sonnet 4.7) em sessão dirigida por wellinton.ribeiro@v4company.com
**Status:** APPROVED — pronto para writing-plans
**Sprint:** P2 (process improvement, sem novo MCP tool)

## 1. Goal

Fechar gap descoberto em Sprint 3b.5: a "verification cadence" documentada em
[`CLAUDE.md`](../../../CLAUDE.md) rodava ruff + format + mypy + unit tests
manualmente antes de cada commit, mas **não incluía integration tests**. Resultado:
2 integration tests pré-existentes (`test_apply_audience` sem mock de
`run_report` + `test_update_ad_status` em REMOVED dead path) ficaram quebrados
silenciosamente até CI pegar no push, exigindo commit fix `3c23fc5`.

Sprint 3b.7 spawn-task pendente: "adicionar integration sweep ao pre-push
gates."

Esta sprint shippa **dois scripts standalone em Python** + fix de inconsistência
de marker em `test_update_ad_status.py`. Zero novos MCP tools. Tool count permanece
em 39.

## 2. Scope decisions

| # | Decisão | Resolução | Justificativa |
|---|---|---|---|
| 1 | Estratégia agressividade | **Híbrido** — pragmatic default + opt-in full sweep | Frequência empírica de bug DB-test-escape é baixa (1 em 7 sprints). Custo cumulativo de exigir Docker on per-push excederia o ganho. Hybrid preserva opção sem onerar dia-a-dia. |
| 2 | Mecanismo | **Standalone script versionado**, não git hook | Projeto já tem cultura de gate manual documentado em CLAUDE.md. Cross-platform via Python. Sem cerimônia de install-hooks em fresh clones. Solo project — automação via hook tem reputação ruim (escape via `--no-verify` em momento de irritação). |
| 3 | Escopo do default | **Comprehensive** — substitui toda a verification cadence | Single source of truth. Ergonomic (1 comando vs 4). Espelha estrutura sequencial fail-fast do CI. |
| 4 | Full sweep + Docker off | **Loud fail** — exit code 2 com hint clara | Script é opt-in; pessoa rodou de propósito pra full coverage. Skip silencioso anula propósito. Exit code distinto permite scripting downstream. |

## 3. Component specs

### 3.1 Diretório `scripts/`

Criado neste sprint (não existe hoje no repo). Conterá scripts utilitários
versionados executáveis via `python scripts/<name>.py` a partir da raiz do repo.

```
scripts/
├── __init__.py                    # empty
├── check-pre-push.py              # fast default — entry point
├── check-pre-push-full.py         # opt-in full sweep — entry point
└── _runner.py                     # shared internal helpers
```

### 3.2 `scripts/_runner.py` — shared module

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
    Step("pytest non-DB integration",
         ["pytest", "tests/integration", "-m", "not integration", "-q"]),
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
        header = _color(f"==> [{i}/{total}] {step.name}", "36")  # cyan
        print(header)
        result = subprocess.run(step.cmd)
        if result.returncode != 0:
            footer = _color(f"❌ {step.name} FAILED", "31")  # red
            print(footer)
            print(
                f"   Run individually to debug: {' '.join(step.cmd)}",
                file=sys.stderr,
            )
            elapsed = time.perf_counter() - start
            print(
                _color(
                    f"❌ Pre-push check FAILED at step {i}/{total} ({step.name}) "
                    f"after {elapsed:.1f}s.",
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
    """Probe Docker daemon. Returns (ok, hint_if_not_ok)."""
    hint = (
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
        return False, hint
    return (result.returncode == 0, "" if result.returncode == 0 else hint)
```

### 3.3 `scripts/check-pre-push.py` — fast entry

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

### 3.4 `scripts/check-pre-push-full.py` — full entry

```python
#!/usr/bin/env python3
"""Full pre-push gate. Base steps + DB integration tests (Docker required).

Sequence (fail-fast):
    pre-check: docker info (timeout 2s)
    1-5:       base steps (ruff/format/mypy/unit/non-DB integration)
    6:         pytest tests/integration -m integration -q  (testcontainers)

If Docker is off, exits with hint without running any step.
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
        return 2  # distinct exit code for Docker-off
    return run_steps([*BASE_STEPS, DB_INTEGRATION_STEP])


if __name__ == "__main__":
    sys.exit(main())
```

### 3.5 Marker fix em `tests/integration/test_update_ad_status.py`

Esse test usa `testcontainers.postgres.PostgresContainer` mas não tem
`@pytest.mark.integration` marker, então `pytest -m "not integration"` tenta
rodá-lo e trava no fixture quando Docker está off. Fix: adicionar marker no
módulo (pytestmark) ou em cada test class/function.

```python
import pytest

pytestmark = pytest.mark.integration
```

Sem esse fix, step 5 do fast script (`pytest tests/integration -m "not integration"`)
fica enroscado quando Docker está off — ou seja, o script seria inútil para
Wellington (que tem Docker tipicamente off no Windows). Esse fix é pré-requisito
crítico do gate funcionar.

### 3.6 Exit codes

| Situação | Exit code |
|---|---|
| All steps pass | 0 |
| Any step fails (fast script ou full script após Docker check) | 1 |
| Docker daemon off (full script only) | 2 |
| Internal error (subprocess can't spawn) | 3 (Python default) |

Ctrl+C mid-run usa default Python handler — exit 130. Sem custom signal handling.

### 3.7 CLAUDE.md updates

**Seção "Verification cadence (always before commit)"** — substituir os 4
comandos atuais por:

```bash
python scripts/check-pre-push.py
```

E adicionar nota sobre opt-in full sweep:

> Opt-in full sweep (requer Docker Desktop rodando):
> ```bash
> python scripts/check-pre-push-full.py
> ```

**Seção "Don't do"** — adicionar:

> Don't push to main without running `python scripts/check-pre-push.py` first.
> CI catches lint/type/test failures but it wastes a deploy cycle and may
> trigger rollback if integration tests reveal a bug.

## 4. Files affected

```
scripts/                                       # NEW directory
├── __init__.py                                # NEW: empty
├── _runner.py                                 # NEW: shared runner module
├── check-pre-push.py                          # NEW: fast entry
└── check-pre-push-full.py                     # NEW: full entry

tests/
├── unit/
│   └── test_pre_push_runner.py                # NEW: 7 unit tests for _runner.py
└── integration/
    └── test_update_ad_status.py               # MODIFY: add pytestmark = pytest.mark.integration

CLAUDE.md                                      # MODIFY: verification cadence + don't do
```

**Net delta:** ~150 LOC source (`scripts/`), ~80 LOC test, ~5 LOC docs.

## 5. Risks & mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Script trava em Windows por path/encoding | Medium | `Path` API + UTF-8 implicit. Smoke test no Wellington's box durante sprint. |
| Wellington esquece de rodar e push quebra CI | Medium | Lesson 3b.5 mostra que escape rate é baixa (1/7). Hook automático tem trade-offs piores (escolha original C). |
| Color codes vazam em logs/CI capture | Low | `_color()` checa `sys.stdout.isatty()` — se redirecionado, emite plain text. |
| `docker info` é lento mesmo com daemon off | Low-medium | Timeout 2s. Se TimeoutExpired raise, tratado como "not running." |
| Marker fix em test_update_ad_status.py quebra CI matrix | Very Low | Hoje CI roda `pytest tests/integration -m "not integration"` (que pega o test) + `pytest tests/integration -m integration` (que não pega). Após fix, primeira não pega, segunda pega. Cobertura mantida — só muda em qual job ele roda. |
| Adding subprocess timeout doesn't help on Windows where docker pipe hang differently | Low | timeout 2s aplica em qualquer SO via Python subprocess. Se quebrar, testar manualmente no Windows + ajustar. |
| Wellington roda scripts de subdir errado | Low | `_chdir_repo_root()` no topo de `run_steps()` — cwd sempre vira repo root antes de qualquer pytest. |

## 6. Out of scope (explicit)

- **Git hooks (auto-install via husky/pre-commit/lefthook)** — decisão explícita
  Pergunta 2 (mecanismo). Pode ser revisitada se padrão manual falhar empiricamente
  em sprints futuros.
- **Parallel step execution** — sequential fail-fast é mais simples + reflete CI
  workflow. Paralelizar adicionaria complexidade sem ganho material (~15s total).
- **Pretty output (rich library, spinners, etc)** — stdlib ANSI + TTY check
  é suficiente. Sem nova dep.
- **Configurable step list via TOML/YAML** — YAGNI. Steps são hardcoded em
  `_runner.py`. Mudança futura edita uma constante.
- **Integration test sweep além das testcontainers tests** — full script roda
  o que CI roda. Sem step adicional.
- **Auto-detect Docker boot + retry** — out of scope. Loud fail por design
  (Pergunta 4). Wellington decide ligar Docker.
- **Smoke test em produção** — esta sprint é internal tooling, não muda
  comportamento end-user. CI passing + manual local run = signoff suficiente.
- **Retrofit `@pytest.mark.integration` em outros tests inconsistentes** — só
  `test_update_ad_status.py` precisa (único caso identificado via grep). Se
  surgirem outros depois, fix incremental.

## 7. Open questions — resolved

| # | Question | Resolution |
|---|---|---|
| 1 | Estratégia agressividade | Híbrido (Pergunta 1 = C) |
| 2 | Mecanismo (hook vs script) | Standalone script (Pergunta 2 = B) |
| 3 | Escopo do default | Comprehensive (Pergunta 3 = B) |
| 4 | Docker off behavior (full script) | Loud fail exit 2 (Pergunta 4 = A) |
| 5 | Marker inconsistency fix scope | Incluir neste sprint (pre-req do fast script) |
| 6 | Test coverage para os scripts | Unit tests apenas em `_runner.py` (Step + run_steps + check_docker). Scripts top-level são thin entries, smoke manual no sign-off |
| 7 | Linguagem | Python (cross-platform, alinhado com stack, sem nova dep) |
| 8 | Fail-fast vs collect-all | Fail-fast (consistente com CI, evita noise de erros em cascata) |

## 8. References

- Sprint 3b.5 fix commit que motivou: [`3c23fc5`](https://github.com/BadWolf1509/v4-ads-mcp/commit/3c23fc5)
- CLAUDE.md seções afetadas: "Verification cadence", "Don't do"
- Test marker convention: `pyproject.toml` define `integration: tests that require a live DB`
- CI workflow espelhado: `.github/workflows/ci.yml` (mesma sequência de steps)
- Projeto convention: solo dev on main + admin bypass — pre-push gate é o single defense localmente
