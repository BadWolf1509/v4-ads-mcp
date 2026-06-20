# Onda 1 — Hardening + Observabilidade + Instrumentação — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fechar o boundary de erro do dispatcher MCP, tornar greppáveis 3 eventos hoje invisíveis (negações de acesso, erros de tool, runs de resync), e destravar honestamente o gate da Fase 2B instrumentando os 8 reports.

**Architecture:** 7 tasks independentes (arquivos disjuntos — qualquer ordem). Cada uma é uma mudança pequena e cirúrgica com teste próprio. Origem: §3 da spec [`2026-06-20-improvements-roadmap-design.md`](../specs/2026-06-20-improvements-roadmap-design.md).

**Tech Stack:** Python 3.13 · FastAPI · MCP SDK · structlog · asyncpg · pytest (`asyncio_mode=auto`) · GitHub Actions (Cloud Run deploy).

## Global Constraints

- **Verificação antes de CADA commit:** `python scripts/check_pre_push.py` (~40s: ruff + format + mypy strict + unit + integração não-DB). Deve passar verde.
- **Tasks 4 e 5 tocam `audit_log`/integração-DB:** rodar também `python scripts/check_pre_push_full.py` (Docker/testcontainers) OU aceitar o CI como validador e confirmar via `gh run view <id> --json conclusion` (NUNCA pelo exit code de `gh run watch`).
- **Testes async:** `@pytest.mark.asyncio` + `async def` (modo `auto`). Logs: `from structlog.testing import capture_logs`.
- **`audit_log.record`:** `action_type ∈ {mutate, read, auth, system}`, `status ∈ {success, error, denied}`, `manager_id` é nullable. Use `action_type="system"` pra jobs.
- **Mensagens ao usuário/cliente:** PT-BR. Preservar mensagens friendly/denied (auto-corrigem clientes LLM — F62); scrubar só o inesperado.
- **Commits:** `feat(scope)` / `fix(scope)` / `ci:` / `chore:` + trailer `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`. Não pushar sem `check_pre_push` verde.

---

### Task 1: Boundary de erro no dispatcher MCP (#3)

**Files:**
- Modify: `src/mcp/server.py` (imports no topo; `_error_envelope` novo; try/except em `call_tool` na linha 102; scrub no fallback de auth nas linhas 133-138)
- Test: `tests/unit/test_mcp_error_boundary.py` (criar)

**Interfaces:**
- Produces: `_error_envelope(tool_name: str, exc: Exception) -> dict[str, Any]` — mapeia exceção → `{"status": "denied"|"error", "error_message": str}`. Chamada de dentro de um `except` (pra `log.exception` pegar o traceback vivo).

- [ ] **Step 1: Escrever os testes (falhando)**

Criar `tests/unit/test_mcp_error_boundary.py`:

```python
"""Boundary de erro do dispatcher MCP: exceções viram envelope seguro (sem vazar internals)."""

import pytest

from src.google_ads.access import AccountAccessDeniedError
from src.google_ads.errors import GoogleAdsFriendlyError
from src.governance.rate_limit import QuotaExhausted
from src.meta_ads.client import MetaAccessDeniedError
from src.mcp.server import _error_envelope


def test_generic_exception_is_scrubbed() -> None:
    env = _error_envelope("get_campaign_performance", KeyError("internal_secret_xyz"))
    assert env["status"] == "error"
    assert "internal_secret_xyz" not in env["error_message"]
    assert env["error_message"] == "Erro interno ao executar a ferramenta. O time foi notificado."


def test_account_denied_preserves_ptbr_message() -> None:
    env = _error_envelope("x", AccountAccessDeniedError("Você não tem acesso à conta 1234567890."))
    assert env["status"] == "denied"
    assert "1234567890" in env["error_message"]


def test_meta_denied_is_denied_status() -> None:
    env = _error_envelope("x", MetaAccessDeniedError("Você não tem acesso à conta act_123."))
    assert env["status"] == "denied"
    assert "act_123" in env["error_message"]


def test_google_friendly_error_preserved() -> None:
    env = _error_envelope("x", GoogleAdsFriendlyError("Quota diária esgotada, aguarde."))
    assert env["status"] == "error"
    assert env["error_message"] == "Quota diária esgotada, aguarde."


def test_quota_exhausted_preserved() -> None:
    env = _error_envelope("x", QuotaExhausted("limite diário atingido"))
    assert env["status"] == "error"
    assert "limite diário atingido" in env["error_message"]
```

- [ ] **Step 2: Rodar pra confirmar que falha**

Run: `python -m pytest tests/unit/test_mcp_error_boundary.py -v`
Expected: FAIL com `ImportError: cannot import name '_error_envelope' from 'src.mcp.server'`

- [ ] **Step 3: Adicionar os imports de exceção no topo de `src/mcp/server.py`**

Após a linha 15 (`from src.mcp.tools._registry import ...`), adicionar:

```python
from src.google_ads.access import AccountAccessDeniedError
from src.google_ads.errors import GoogleAdsFriendlyError
from src.governance.rate_limit import QuotaExhausted
from src.meta_ads.client import MetaAccessDeniedError
```

- [ ] **Step 4: Adicionar `_error_envelope` (antes de `build_server`, ~linha 54)**

```python
def _error_envelope(tool_name: str, exc: Exception) -> dict[str, Any]:
    """Mapeia uma exceção de handler pra um envelope seguro pro cliente.

    Chamada de dentro do `except` em call_tool — log.exception() captura o
    traceback vivo no branch catch-all. Erros friendly/denied mantêm a msg
    PT-BR (auto-corrigem clientes LLM, F62); o resto é scrubado pra uma msg
    genérica (sem SQL/driver/internals vazando pro cliente MCP).
    """
    if isinstance(exc, AccountAccessDeniedError | MetaAccessDeniedError):
        log.warning("tool_access_denied", tool=tool_name, error=str(exc))
        return {"status": "denied", "error_message": str(exc)}
    if isinstance(exc, GoogleAdsFriendlyError | QuotaExhausted):
        log.info("tool_friendly_error", tool=tool_name, error=str(exc))
        return {"status": "error", "error_message": str(exc)}
    log.exception("tool_handler_error", tool=tool_name)
    return {
        "status": "error",
        "error_message": "Erro interno ao executar a ferramenta. O time foi notificado.",
    }
```

- [ ] **Step 5: Envolver a chamada do handler em `call_tool`**

Em `src/mcp/server.py`, substituir a linha 102 (`result = await tool.handler(args)`) por:

```python
        try:
            result = await tool.handler(args)
        except Exception as e:  # noqa: BLE001 — boundary: toda falha vira envelope seguro
            result = _error_envelope(name, e)
```

(A linha 96-101 que faz `jsonschema.validate` e levanta `ValueError` fica como está — a mensagem de validação é útil e não vaza segredo.)

- [ ] **Step 6: Scrubar o fallback de auth do `/mcp`**

Substituir o bloco `except Exception as e:` nas linhas 133-138 por:

```python
        except Exception:
            log.exception("mcp_auth_error")
            return Response(
                content=json.dumps({"error": "internal_error", "message": "Erro interno."}),
                status_code=500,
                headers={"content-type": "application/json"},
            )
```

- [ ] **Step 7: Rodar os testes**

Run: `python -m pytest tests/unit/test_mcp_error_boundary.py -v`
Expected: PASS (5 passed)

- [ ] **Step 8: Verificação + commit**

```bash
python scripts/check_pre_push.py
git add src/mcp/server.py tests/unit/test_mcp_error_boundary.py
git commit -m "fix(mcp): boundary de erro no dispatcher — scrub de internals + envelope denied/friendly" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Log estruturado na negação de acesso Google (#4a)

**Files:**
- Modify: `src/google_ads/access.py` (adicionar `log.warning` antes do `raise` na linha 54)
- Test: `tests/unit/test_access_denial_log.py` (criar)

- [ ] **Step 1: Escrever o teste (falhando)**

Criar `tests/unit/test_access_denial_log.py`:

```python
"""A negação de acesso Google deve emitir log.warning (evento de segurança visível)."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from structlog.testing import capture_logs

from src.google_ads import access


@pytest.mark.asyncio
async def test_denial_emits_warning_log(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        access.manager_account_access, "can_manager_access", AsyncMock(return_value=False)
    )
    monkeypatch.setattr(access.audit_log, "record", AsyncMock(return_value=1))

    with capture_logs() as logs:
        with pytest.raises(access.AccountAccessDeniedError):
            await access.ensure_account_access(
                MagicMock(),
                manager_id=uuid4(),
                customer_id="1234567890",
                session_id=uuid4(),
                operation_name="get_campaign_performance",
                level="read",
            )

    events = [e for e in logs if e["event"] == "account_access_denied"]
    assert len(events) == 1
    assert events[0]["customer_id"] == "1234567890"
    assert events[0]["operation"] == "get_campaign_performance"
```

- [ ] **Step 2: Rodar pra confirmar que falha**

Run: `python -m pytest tests/unit/test_access_denial_log.py -v`
Expected: FAIL (`assert len(events) == 1` → 0 — o log ainda não é emitido)

- [ ] **Step 3: Adicionar o `log.warning` em `src/google_ads/access.py`**

Imediatamente antes do `raise AccountAccessDeniedError(` (linha 54), dentro de `ensure_account_access`:

```python
    log.warning(
        "account_access_denied",
        manager_id=str(manager_id),
        customer_id=customer_id,
        operation=operation_name,
        level=level,
        platform="google",
    )
    raise AccountAccessDeniedError(
        f"Você não tem acesso à conta {customer_id}. Peça ao admin pra liberar no painel."
    )
```

- [ ] **Step 4: Rodar o teste**

Run: `python -m pytest tests/unit/test_access_denial_log.py -v`
Expected: PASS

- [ ] **Step 5: Verificação + commit**

```bash
python scripts/check_pre_push.py
git add src/google_ads/access.py tests/unit/test_access_denial_log.py
git commit -m "feat(security): log estruturado na negacao de acesso Google" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Log estruturado na negação de acesso Meta (#4b)

**Files:**
- Modify: `src/meta_ads/reports.py` (adicionar `log.warning` antes do `raise MetaAccessDeniedError`, linha ~87)
- Test: `tests/unit/test_meta_denial_log.py` (criar)

- [ ] **Step 1: Escrever o teste (falhando)**

Criar `tests/unit/test_meta_denial_log.py`:

```python
"""A negação de acesso Meta deve emitir log.warning (espelha o gate Google)."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from structlog.testing import capture_logs

from src.meta_ads import reports as meta_reports


class _FakeAcquire:
    async def __aenter__(self) -> MagicMock:
        return MagicMock()

    async def __aexit__(self, *exc: object) -> bool:
        return False


class _FakePool:
    def acquire(self) -> _FakeAcquire:
        return _FakeAcquire()


@pytest.mark.asyncio
async def test_meta_denial_emits_warning_log(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(meta_reports.connection, "get_pool", lambda: _FakePool())
    monkeypatch.setattr(
        meta_reports.manager_meta_account_access,
        "can_manager_access",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(meta_reports.audit_log, "record", AsyncMock(return_value=1))

    with capture_logs() as logs:
        with pytest.raises(meta_reports.MetaAccessDeniedError):
            await meta_reports.run_meta_graph_get(
                manager_id=uuid4(),
                session_id=uuid4(),
                edge="/act_123/insights",
                params={"ad_account_id": "act_123"},
                operation_name="meta_get_campaign_performance",
            )

    events = [e for e in logs if e["event"] == "meta_account_access_denied"]
    assert len(events) == 1
    assert events[0]["ad_account_id"] == "act_123"
```

- [ ] **Step 2: Rodar pra confirmar que falha**

Run: `python -m pytest tests/unit/test_meta_denial_log.py -v`
Expected: FAIL (`assert len(events) == 1` → 0)

- [ ] **Step 3: Adicionar o `log.warning` em `src/meta_ads/reports.py`**

Imediatamente antes do `raise MetaAccessDeniedError(` (linha 87), dentro do bloco `if not allowed:` (depois do `await audit_log.record(...)`):

```python
                log.warning(
                    "meta_account_access_denied",
                    manager_id=str(manager_id),
                    ad_account_id=ad_account_id,
                    operation=operation_name,
                    platform="meta",
                )
                raise MetaAccessDeniedError(
                    f"Você não tem acesso à conta {ad_account_id}. "
                    f"Peça ao admin pra liberar no painel."
                )
```

- [ ] **Step 4: Rodar o teste**

Run: `python -m pytest tests/unit/test_meta_denial_log.py -v`
Expected: PASS

- [ ] **Step 5: Verificação + commit**

```bash
python scripts/check_pre_push.py
git add src/meta_ads/reports.py tests/unit/test_meta_denial_log.py
git commit -m "feat(security): log estruturado na negacao de acesso Meta" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Audit row por run de resync (#4c)

**Files:**
- Create: `src/jobs/_audit.py` (helper `record_job_run`)
- Modify: `src/jobs/account_resync.py` (chamar o helper dentro do `async with pool.acquire()` das linhas 96-103; import no topo)
- Modify: `src/jobs/meta_resync.py` (chamar o helper dentro do `async with pool.acquire()` das linhas 63-64; import no topo)
- Test: `tests/unit/test_job_audit.py` (criar) + `tests/unit/test_meta_resync_audit.py` (criar)

**Interfaces:**
- Produces: `record_job_run(conn, *, operation: str, platform: Literal["google","meta"]="google", target_count: int|None=None, status: str="success", error_message: str|None=None, params_summary: dict|None=None) -> int` — grava 1 linha `audit_log` com `action_type="system"`, `manager_id=None`, `session_id=None`, `customer_id=None`.

- [ ] **Step 1: Escrever o teste do helper (falhando)**

Criar `tests/unit/test_job_audit.py`:

```python
"""record_job_run grava um audit_log de job (action_type=system, sem manager)."""

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_record_job_run_writes_system_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.jobs import _audit

    rec = AsyncMock(return_value=42)
    monkeypatch.setattr(_audit.audit_log, "record", rec)

    rid = await _audit.record_job_run(
        MagicMock(),
        operation="account_resync",
        platform="google",
        target_count=25,
        params_summary={"deactivated": 1},
    )

    assert rid == 42
    kwargs = rec.call_args.kwargs
    assert kwargs["action_type"] == "system"
    assert kwargs["operation"] == "account_resync"
    assert kwargs["platform"] == "google"
    assert kwargs["manager_id"] is None
    assert kwargs["session_id"] is None
    assert kwargs["target_count"] == 25
    assert kwargs["params_summary"] == {"deactivated": 1}
```

- [ ] **Step 2: Rodar pra confirmar que falha**

Run: `python -m pytest tests/unit/test_job_audit.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'src.jobs._audit'`)

- [ ] **Step 3: Criar `src/jobs/_audit.py`**

```python
"""Audit row compartilhado pra jobs de background (resync, etc.).

Jobs rodam sem contexto de manager/session → manager_id/session_id None
(audit_log.manager_id é nullable, 001_initial_schema.sql:73). action_type
'system' é permitido pelo audit_action_type_check.
"""

from typing import Any, Literal

import asyncpg

from src.db.repositories import audit_log


async def record_job_run(
    conn: asyncpg.Connection,
    *,
    operation: str,
    platform: Literal["google", "meta"] = "google",
    target_count: int | None = None,
    status: str = "success",
    error_message: str | None = None,
    params_summary: dict[str, Any] | None = None,
) -> int:
    """Grava 1 linha audit_log marcando um run de job. Retorna o id da linha."""
    return await audit_log.record(
        conn,
        manager_id=None,
        session_id=None,
        customer_id=None,
        action_type="system",
        operation=operation,
        target_count=target_count,
        params_summary=params_summary,
        status=status,
        error_message=error_message,
        platform=platform,
    )
```

- [ ] **Step 4: Rodar o teste do helper**

Run: `python -m pytest tests/unit/test_job_audit.py -v`
Expected: PASS

- [ ] **Step 5: Plugar no resync Google**

Em `src/jobs/account_resync.py`, adicionar o import após a linha 29 (`from src.google_ads.client import build_client`):

```python
from src.jobs._audit import record_job_run
```

E dentro do bloco `async with pool.acquire() as conn:` (linhas 96-103), logo após o `deactivated = await google_ads_accounts.mark_inactive_except(...)`:

```python
            await record_job_run(
                conn,
                operation="account_resync",
                platform="google",
                target_count=n,
                params_summary={"deactivated": deactivated},
            )
```

- [ ] **Step 6: Escrever o teste do plug Meta (falhando)**

Criar `tests/unit/test_meta_resync_audit.py`:

```python
"""resync_meta() grava 1 audit_log de job (operation=meta_resync, platform=meta)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.jobs import meta_resync


class _FakeAcquire:
    async def __aenter__(self) -> MagicMock:
        return MagicMock()

    async def __aexit__(self, *exc: object) -> bool:
        return False


class _FakePool:
    def acquire(self) -> _FakeAcquire:
        return _FakeAcquire()


@pytest.mark.asyncio
async def test_resync_meta_records_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = MagicMock()
    settings.meta_system_user_token = "tok"
    monkeypatch.setattr(meta_resync, "get_settings", lambda: settings)
    monkeypatch.setattr(
        meta_resync, "_fetch_all_adaccounts", AsyncMock(return_value=[{"id": "act_1", "name": "X"}])
    )
    monkeypatch.setattr(meta_resync.meta_ad_accounts, "upsert_many", AsyncMock(return_value=1))
    monkeypatch.setattr(meta_resync.connection, "get_pool", lambda: _FakePool())
    rec = AsyncMock(return_value=7)
    monkeypatch.setattr(meta_resync, "record_job_run", rec)

    n = await meta_resync.resync_meta()

    assert n == 1
    kwargs = rec.call_args.kwargs
    assert kwargs["operation"] == "meta_resync"
    assert kwargs["platform"] == "meta"
    assert kwargs["target_count"] == 1
```

- [ ] **Step 7: Rodar pra confirmar que falha**

Run: `python -m pytest tests/unit/test_meta_resync_audit.py -v`
Expected: FAIL (`AttributeError: <module 'src.jobs.meta_resync'> does not have the attribute 'record_job_run'`)

- [ ] **Step 8: Plugar no resync Meta**

Em `src/jobs/meta_resync.py`, adicionar o import após a linha 21 (`from src.db.repositories import meta_ad_accounts`):

```python
from src.jobs._audit import record_job_run
```

E em `resync_meta()`, dentro do `async with pool.acquire() as conn:` (linhas 63-64), após o `n = await meta_ad_accounts.upsert_many(conn, payload)`:

```python
    async with pool.acquire() as conn:
        n = await meta_ad_accounts.upsert_many(conn, payload)
        await record_job_run(conn, operation="meta_resync", platform="meta", target_count=n)
```

- [ ] **Step 9: Rodar os testes**

Run: `python -m pytest tests/unit/test_job_audit.py tests/unit/test_meta_resync_audit.py -v`
Expected: PASS (2 passed)

- [ ] **Step 10: Verificação + commit**

```bash
python scripts/check_pre_push.py
git add src/jobs/_audit.py src/jobs/account_resync.py src/jobs/meta_resync.py tests/unit/test_job_audit.py tests/unit/test_meta_resync_audit.py
git commit -m "feat(db): audit row por run de resync (observabilidade de job zero-touch)" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: Instrumentar os 8 reports com `audit_this_call` (#1 — destrava o gate da 2B)

**Files:**
- Modify (8): `src/mcp/tools/get_campaign_performance.py:108`, `get_ad_group_performance.py:106`, `get_ad_performance.py:117`, `get_keyword_performance.py:131`, `get_audience_performance.py:110`, `get_device_performance.py:94`, `get_geo_performance.py:96`, `get_hourly_performance.py:96`
- Test: `tests/unit/test_report_audit_optin.py` (criar)

**Interfaces:**
- Consumes: `run_report(..., audit_this_call: bool = False, ...)` ([`reports.py:50`](../../../src/google_ads/reports.py)) — já existe; o `finally` grava em `audit_log` quando `True`.

- [ ] **Step 1: Escrever o teste (falhando)**

Criar `tests/unit/test_report_audit_optin.py`. Acessa o handler via o registry (não precisa do nome da função), mocka `get_current` + `run_report` no namespace do tool:

```python
"""Os 8 reports consolidados pela 2A devem passar audit_this_call=True (gate da Fase 2B)."""

from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from src.mcp.tools._registry import get_tool

# (módulo do tool, nome registrado)
_REPORTS = [
    ("src.mcp.tools.get_campaign_performance", "get_campaign_performance"),
    ("src.mcp.tools.get_ad_group_performance", "get_ad_group_performance"),
    ("src.mcp.tools.get_ad_performance", "get_ad_performance"),
    ("src.mcp.tools.get_keyword_performance", "get_keyword_performance"),
    ("src.mcp.tools.get_audience_performance", "get_audience_performance"),
    ("src.mcp.tools.get_device_performance", "get_device_performance"),
    ("src.mcp.tools.get_geo_performance", "get_geo_performance"),
    ("src.mcp.tools.get_hourly_performance", "get_hourly_performance"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("module_path, tool_name", _REPORTS)
async def test_report_opts_into_audit(
    module_path: str, tool_name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import importlib

    mod = importlib.import_module(module_path)

    ctx = MagicMock()
    ctx.manager_id = uuid4()
    ctx.session_id = uuid4()
    monkeypatch.setattr(mod, "get_current", lambda: ctx)

    captured: dict[str, Any] = {}

    async def _fake_run_report(**kwargs: Any) -> list[Any]:
        captured.update(kwargs)
        return []

    monkeypatch.setattr(mod, "run_report", _fake_run_report)

    tool = get_tool(tool_name)
    assert tool is not None
    await tool.handler({"customer_id": "1234567890", "date_range": "LAST_7_DAYS"})

    assert captured.get("audit_this_call") is True, f"{tool_name} não opta por audit_this_call"
```

- [ ] **Step 2: Rodar pra confirmar que falha**

Run: `python -m pytest tests/unit/test_report_audit_optin.py -v`
Expected: FAIL nos 8 (`{tool_name} não opta por audit_this_call` — hoje o default é `False`)

- [ ] **Step 3: Adicionar `audit_this_call=True` nos 8 reports**

Em cada arquivo, na chamada `run_report(...)`, adicionar a linha `audit_this_call=True,` logo após a linha `operation_name="...",`. Exemplo em `src/mcp/tools/get_campaign_performance.py` (linha 108):

```python
        operation_name="get_campaign_performance",
        audit_this_call=True,
    )
```

Repetir o mesmo (a linha idêntica `audit_this_call=True,` após o respectivo `operation_name=`) em:
- `get_ad_group_performance.py` (após linha 106)
- `get_ad_performance.py` (após linha 117)
- `get_keyword_performance.py` (após linha 131)
- `get_audience_performance.py` (após linha 110)
- `get_device_performance.py` (após linha 94)
- `get_geo_performance.py` (após linha 96)
- `get_hourly_performance.py` (após linha 96)

- [ ] **Step 4: Rodar o teste**

Run: `python -m pytest tests/unit/test_report_audit_optin.py -v`
Expected: PASS (8 passed)

- [ ] **Step 5: Verificação + commit**

`check_pre_push` cobre este teste (unit, sem DB). Como o comportamento real grava em `audit_log`, rodar também o full sweep se Docker disponível.

```bash
python scripts/check_pre_push.py
git add src/mcp/tools/get_campaign_performance.py src/mcp/tools/get_ad_group_performance.py src/mcp/tools/get_ad_performance.py src/mcp/tools/get_keyword_performance.py src/mcp/tools/get_audience_performance.py src/mcp/tools/get_device_performance.py src/mcp/tools/get_geo_performance.py src/mcp/tools/get_hourly_performance.py tests/unit/test_report_audit_optin.py
git commit -m "feat(mcp): instrumentar os 8 reports com audit_this_call (destrava gate Fase 2B)" -m "Os 8 reports consolidados pela 2A nao auditavam → o soak gate media zero por construcao. Com audit_this_call=True, o uso aparece no audit_log (Postgres, consultavel via Supabase MCP). REINICIA o relogio do soak a partir deste deploy." -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: Smoke do deploy usa readiness `/health?deep=1` (#5)

**Files:**
- Modify: `.github/workflows/deploy.yml` (linhas 126-130 — o probe de `/health`)

**Nota:** o endpoint `/health?deep=1` já existe ([`app.py:50`](../../../src/app.py)) e já tem teste (`tests/integration/test_health.py`). Esta task é só config de CI — a validação é o step "Smoke test" verde no próprio deploy (YAML de workflow não tem unit test).

- [ ] **Step 1: Trocar o probe shallow por deep**

Em `.github/workflows/deploy.yml`, no step "Smoke test", o bloco do `/health` (linhas 126-130). Substituir:

```yaml
          echo "Probing /health (with retry)..."
          for i in $(seq 1 18); do
            if curl -fsS "${SERVICE_URL}/health" | grep -q '"status":"ok"'; then
              echo "  ✓ /health responded after $((i * 5))s"
              break
```

por:

```yaml
          echo "Probing /health?deep=1 (readiness — verifica o DB, with retry)..."
          for i in $(seq 1 18); do
            if curl -fsS "${SERVICE_URL}/health?deep=1" | grep -q '"db":"ok"'; then
              echo "  ✓ /health?deep=1 (DB ok) responded after $((i * 5))s"
              break
```

(O resto do loop — o branch de timeout `if [ "$i" -eq 18 ]` e o `sleep 5` — fica inalterado. `curl -fsS` já falha em HTTP 503, e o `grep '"db":"ok"'` garante que o corpo confirma o DB; um deploy com DB inacessível agora reprova o smoke.)

- [ ] **Step 2: Sanity local (lint do YAML, sem rodar deploy)**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/deploy.yml')); print('YAML ok')"`
Expected: `YAML ok`

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/deploy.yml
git commit -m "ci: smoke do deploy usa /health?deep=1 (readiness real do DB)" -m "Onda 1 (2026-06-20) criou /health?deep=1 pra impedir deploy com DB inacessivel passar o smoke, mas o gate ainda batia /health raso. Fecha o loop." -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

- [ ] **Step 4: Pós-push — confirmar o smoke verde**

Após o push (no fim da onda), confirmar que o step "Smoke test" passou:

Run: `gh run list --workflow=Deploy --limit 1` → pegar o run id → `gh run view <id> --json conclusion,jobs`
Expected: `conclusion: success` e o step "Smoke test" com o probe `/health?deep=1` verde. (NÃO confiar no exit code de `gh run watch`.)

---

### Task 7: Limpezas + doc-drift (#11)

**Files:**
- Modify: `src/google_ads/queries/_common.py` (remover `METRIC_FIELDS`, linhas 185-196)
- Delete: `scripts/tag_tool_buckets.py`, `scripts/tag_tool_buckets_v2.py`, `scripts/tag_tool_buckets_v3.py`, `scripts/tag_tool_buckets_final.py`
- Modify: `CLAUDE.md` (corrigir o path de `resolve_date_window`)

- [ ] **Step 1: Confirmar que `METRIC_FIELDS` está morto (zero uso em código/testes)**

Run: `git grep -n "METRIC_FIELDS" -- src tests`
Expected: APENAS `src/google_ads/queries/_common.py:186:METRIC_FIELDS = {` (a definição). Se aparecer qualquer uso em `src/` ou `tests/`, PARAR e reavaliar.

- [ ] **Step 2: Remover o dict `METRIC_FIELDS`**

Em `src/google_ads/queries/_common.py`, deletar as linhas 185-196 (o comentário `# Common metric SELECT fragments — reuse across many tools` + o dict `METRIC_FIELDS = { ... }` inteiro). Manter `micros_to_currency` (linha 199+) intacto.

- [ ] **Step 3: Confirmar que os scripts não são importados em lugar nenhum**

Run: `git grep -n "tag_tool_buckets" -- src tests scripts`
Expected: só auto-referências dentro dos próprios 4 arquivos (nenhum import de `src/` ou `tests/`). Se houver import externo, PARAR.

- [ ] **Step 4: Deletar os 4 scripts one-off**

```bash
git rm scripts/tag_tool_buckets.py scripts/tag_tool_buckets_v2.py scripts/tag_tool_buckets_v3.py scripts/tag_tool_buckets_final.py
```

- [ ] **Step 5: Corrigir o doc-drift no `CLAUDE.md`**

Na seção "Date range conventions (post-3b.20)", a frase diz que `resolve_date_window` está em `_common.py` de forma ambígua. Ajustar pra apontar o path correto: `resolve_date_window` em `src/google_ads/queries/_common.py` (NÃO `src/mcp/tools/_common.py` — existem dois `_common.py`). Editar a menção pra:

```
Resolve via `resolve_date_window` em `src/google_ads/queries/_common.py`
```

- [ ] **Step 6: Verificação (garantir que nada quebrou)**

Run: `python scripts/check_pre_push.py`
Expected: verde (ruff/mypy/unit — confirma que remover `METRIC_FIELDS` e os scripts não quebrou nenhum import).

- [ ] **Step 7: Commit**

```bash
git add src/google_ads/queries/_common.py CLAUDE.md
git commit -m "chore: remover METRIC_FIELDS morto + scripts tag_tool_buckets + fix doc-drift resolve_date_window" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review (do autor do plano)

**Cobertura da spec §3 (Onda 1):**
- §3.1 #3 boundary de erro → Task 1 ✅ (dispatcher + fallback de auth)
- §3.2 #4 logs → Task 2 (Google denial) + Task 3 (Meta denial) + Task 4 (resync audit) ✅
- §3.3 #1 instrumentação → Task 5 ✅
- §3.4 #5 deploy deep → Task 6 ✅
- §3.5 #11 limpezas → Task 7 ✅

**Desvio consciente da spec:** o §3.2 dizia `action_type="read"` pro audit de resync; o plano usa `action_type="system"` (semanticamente correto pra job e permitido pelo `audit_action_type_check`). Sem impacto na observabilidade.

**Type consistency:** `record_job_run` (Task 4) usado com a mesma assinatura nos 2 call-sites. `_error_envelope` (Task 1) retorna sempre `{"status", "error_message"}`. `audit_this_call` é o kwarg existente de `run_report`.

**Pronto pra execução:** todas as tasks têm arquivos disjuntos → ordem livre; cada uma com test cycle + commit próprio. Tasks 4 e 5 recomendam o full sweep Docker (tocam `audit_log`).
