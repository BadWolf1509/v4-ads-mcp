# Google MCP Per-Account Authorization Gate — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforçar a matriz `manager_account_access` na camada MCP do Google — um gestor só pode ler/mutar contas concedidas a ele.

**Architecture:** Um helper `ensure_account_access` (espelha o `MetaAccessDeniedError`/gate do Meta) chamado nos 5 choke points por onde todo `customer_id` passa: `run_report` (read), `run_mutation` + `run_conversion_upload` + `run_offline_user_data_job` (write/apply), e `create_pending` (build/preview). Sem migration. Sem bypass por role (matriz autoritativa pra todos). Spec: [`2026-05-28-google-mcp-account-gate-design.md`](../specs/2026-05-28-google-mcp-account-gate-design.md).

**Tech Stack:** Python 3.12, asyncpg, pytest. Reusa `manager_account_access.can_manager_access` (já existe, suporta level read/write).

---

## File Structure

**Create:**
- `src/google_ads/access.py` — `AccountAccessDeniedError` + `ensure_account_access(conn, *, manager_id, customer_id, session_id, operation_name, level)`
- `tests/unit/test_account_access.py` — unit do helper

**Modify (choke points):**
- `src/google_ads/reports.py::run_report` — gate read
- `src/google_ads/mutations.py::run_mutation` — gate write
- `src/google_ads/conversions.py::run_conversion_upload` — gate write
- `src/google_ads/customer_match.py::run_offline_user_data_job` — gate write
- `src/governance/dry_run.py::create_pending` — novo param `manager_id` + gate write (build/preview)
- callsites de `create_pending` (mutate tools em dry-run) — passar `ctx.manager_id`

**Modify (tests):** seeds dos testes de integração que exercitam executores reais.

> **Convenções (todas as tasks):** `python scripts/check_pre_push.py` antes de cada commit (5/5). Integration tests testcontainers NÃO rodam local (sem Docker) → validam no CI; escrevê-los mesmo assim. Commitar, NÃO push (controller decide). ruff auto-formata; mypy strict. Estamos na `main` com consentimento.

---

### Task 1: Helper `ensure_account_access` + exceção

**Files:**
- Create: `src/google_ads/access.py`
- Test: `tests/unit/test_account_access.py`

- [ ] **Step 1: Escrever o teste falhando** (`tests/unit/test_account_access.py`):

```python
import pytest
from unittest.mock import AsyncMock, patch
from uuid import uuid4
from src.google_ads import access
from src.google_ads.access import AccountAccessDeniedError


@pytest.mark.asyncio
async def test_ensure_account_access_allows_when_granted():
    conn = AsyncMock()
    with patch("src.google_ads.access.manager_account_access.can_manager_access",
               AsyncMock(return_value=True)):
        # não levanta
        await access.ensure_account_access(
            conn, manager_id=uuid4(), customer_id="123", session_id=uuid4(),
            operation_name="get_campaign_performance", level="read")


@pytest.mark.asyncio
async def test_ensure_account_access_denies_and_audits():
    conn = AsyncMock()
    mid, sid = uuid4(), uuid4()
    with (
        patch("src.google_ads.access.manager_account_access.can_manager_access",
              AsyncMock(return_value=False)),
        patch("src.google_ads.access.audit_log.record", AsyncMock()) as rec,
    ):
        with pytest.raises(AccountAccessDeniedError):
            await access.ensure_account_access(
                conn, manager_id=mid, customer_id="999", session_id=sid,
                operation_name="update_campaign_status", level="write")
        rec.assert_awaited_once()
        kwargs = rec.await_args.kwargs
        assert kwargs["status"] == "denied"
        assert kwargs["customer_id"] == "999"
        assert kwargs["platform"] == "google"
```

- [ ] **Step 2: Rodar — FAIL.** `python -m pytest tests/unit/test_account_access.py -v` → erro (módulo não existe).

- [ ] **Step 3: Implementar** `src/google_ads/access.py`:

```python
"""Per-account authorization gate for Google MCP tools.

The MCC OAuth token reaches all client accounts; this gate makes
`manager_account_access` the authoritative boundary at the MCP layer
(mirrors src/meta_ads/reports.py's can_manager_access check).
"""

from uuid import UUID

import asyncpg
import structlog

from src.db.repositories import audit_log, manager_account_access

log = structlog.get_logger(__name__)


class AccountAccessDeniedError(Exception):
    """Raised when a manager has no grant for the requested Google customer_id."""

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


async def ensure_account_access(
    conn: asyncpg.Connection,
    *,
    manager_id: UUID,
    customer_id: str,
    session_id: UUID,
    operation_name: str,
    level: str = "read",
) -> None:
    """Raise AccountAccessDeniedError (PT-BR) + audit denied if the manager lacks
    `level` access to customer_id. No-op when access is granted.
    """
    allowed = await manager_account_access.can_manager_access(
        conn, manager_id, customer_id, level=level
    )
    if allowed:
        return
    await audit_log.record(
        conn,
        manager_id=manager_id,
        session_id=session_id,
        customer_id=customer_id,
        action_type="mutate" if level == "write" else "read",
        operation=operation_name,
        status="denied",
        error_message="Gestor sem acesso à conta Google",
        platform="google",
    )
    raise AccountAccessDeniedError(
        f"Você não tem acesso à conta {customer_id}. Peça ao admin pra liberar no painel."
    )
```

- [ ] **Step 4: Rodar — PASS.** `python -m pytest tests/unit/test_account_access.py -v`
- [ ] **Step 5: `python scripts/check_pre_push.py` → 5/5.**
- [ ] **Step 6: Commit** `git add src/google_ads/access.py tests/unit/test_account_access.py && git commit -m "feat(google_ads): ensure_account_access gate helper + AccountAccessDeniedError"`

---

### Task 2: Gate em `run_report` (reads)

**Files:**
- Modify: `src/google_ads/reports.py::run_report` (após `settings = get_settings()`, antes da reserva de quota)
- Test: `tests/unit/test_run_report_gate.py` (criar)

- [ ] **Step 1: Teste falhando** (`tests/unit/test_run_report_gate.py`):

```python
import pytest
from unittest.mock import AsyncMock, patch
from uuid import uuid4
from src.google_ads import reports
from src.google_ads.access import AccountAccessDeniedError


@pytest.mark.asyncio
async def test_run_report_denies_without_grant():
    with (
        patch("src.google_ads.reports.connection.get_pool"),
        patch("src.google_ads.reports.ensure_account_access",
              AsyncMock(side_effect=AccountAccessDeniedError("sem acesso"))),
    ):
        with pytest.raises(AccountAccessDeniedError):
            await reports.run_report(
                manager_id=uuid4(), session_id=uuid4(), customer_id="999",
                query="SELECT 1", row_formatter=lambda r: {}, operation_name="x")
```

- [ ] **Step 2: Rodar — FAIL** (gate não existe; tenta seguir).

- [ ] **Step 3: Implementar.** Em `src/google_ads/reports.py`: adicionar import `from src.google_ads.access import ensure_account_access`. No corpo de `run_report`, logo após `settings = get_settings()` (linha ~59) e ANTES de qualquer reserva de quota / `build_client_for_manager`, inserir:

```python
    async with connection.get_pool().acquire() as conn:
        await ensure_account_access(
            conn, manager_id=manager_id, customer_id=customer_id,
            session_id=session_id, operation_name=operation_name, level="read",
        )
```

(O gate levanta `AccountAccessDeniedError` antes de consumir quota ou bater na API.)

- [ ] **Step 4: Rodar — PASS.** `python -m pytest tests/unit/test_run_report_gate.py -v`
- [ ] **Step 5: check_pre_push 5/5.**
- [ ] **Step 6: Commit** `git add src/google_ads/reports.py tests/unit/test_run_report_gate.py && git commit -m "feat(google_ads): hard-gate de acesso por-conta em run_report (read)"`

---

### Task 3: Gate em `run_mutation` (write/apply)

**Files:**
- Modify: `src/google_ads/mutations.py::run_mutation`
- Test: `tests/unit/test_run_mutation_gate.py` (criar)

- [ ] **Step 1: Teste falhando** (mirror da Task 2, trocando `reports`→`mutations`, `run_report`→`run_mutation`, args `operation_type="update_campaign_status", payload={}, target_count=1`, `level="write"` implícito):

```python
import pytest
from unittest.mock import AsyncMock, patch
from uuid import uuid4
from src.google_ads import mutations
from src.google_ads.access import AccountAccessDeniedError


@pytest.mark.asyncio
async def test_run_mutation_denies_without_grant():
    with (
        patch("src.google_ads.mutations.connection.get_pool"),
        patch("src.google_ads.mutations.ensure_account_access",
              AsyncMock(side_effect=AccountAccessDeniedError("sem acesso"))),
    ):
        with pytest.raises(AccountAccessDeniedError):
            await mutations.run_mutation(
                manager_id=uuid4(), session_id=uuid4(), customer_id="999",
                operation_type="update_campaign_status", payload={}, target_count=1)
```

- [ ] **Step 2: Rodar — FAIL.**
- [ ] **Step 3: Implementar.** Em `src/google_ads/mutations.py`: import `from src.google_ads.access import ensure_account_access`. No topo de `run_mutation`, após `settings = get_settings()` (~linha 63) e ANTES do `before_call`/builder, inserir o mesmo bloco da Task 2 mas com `level="write"`:

```python
    async with connection.get_pool().acquire() as conn:
        await ensure_account_access(
            conn, manager_id=manager_id, customer_id=customer_id,
            session_id=session_id, operation_name=operation_type, level="write",
        )
```

- [ ] **Step 4: Rodar — PASS.**
- [ ] **Step 5: check_pre_push 5/5.**
- [ ] **Step 6: Commit** `git add src/google_ads/mutations.py tests/unit/test_run_mutation_gate.py && git commit -m "feat(google_ads): hard-gate de acesso por-conta em run_mutation (write)"`

---

### Task 4: Gate em `run_conversion_upload` + `run_offline_user_data_job`

**Files:**
- Modify: `src/google_ads/conversions.py::run_conversion_upload`, `src/google_ads/customer_match.py::run_offline_user_data_job`
- Test: `tests/unit/test_conversion_customer_match_gate.py` (criar)

- [ ] **Step 1: Ler** ambas funções pra confirmar a assinatura (recebem `manager_id`, `session_id`, `customer_id`). Confirmar onde fica o início do corpo pra inserir o gate.

- [ ] **Step 2: Teste falhando:**

```python
import pytest
from unittest.mock import AsyncMock, patch
from uuid import uuid4
from src.google_ads import conversions, customer_match
from src.google_ads.access import AccountAccessDeniedError


@pytest.mark.asyncio
async def test_conversion_upload_denies_without_grant():
    with (
        patch("src.google_ads.conversions.connection.get_pool"),
        patch("src.google_ads.conversions.ensure_account_access",
              AsyncMock(side_effect=AccountAccessDeniedError("x"))),
    ):
        with pytest.raises(AccountAccessDeniedError):
            await conversions.run_conversion_upload(
                manager_id=uuid4(), session_id=uuid4(), customer_id="999",
                operation_type="import_offline_conversions", payload={}, target_count=1)


@pytest.mark.asyncio
async def test_offline_user_data_job_denies_without_grant():
    with (
        patch("src.google_ads.customer_match.connection.get_pool"),
        patch("src.google_ads.customer_match.ensure_account_access",
              AsyncMock(side_effect=AccountAccessDeniedError("x"))),
    ):
        with pytest.raises(AccountAccessDeniedError):
            await customer_match.run_offline_user_data_job(
                manager_id=uuid4(), session_id=uuid4(), customer_id="999",
                user_list_id="1", operation_type="add", hashed_members=[])
```
(Ajustar os kwargs aos nomes reais lidos no Step 1.)

- [ ] **Step 3: Rodar — FAIL.**
- [ ] **Step 4: Implementar.** Em cada função, import `from src.google_ads.access import ensure_account_access` e inserir no início do corpo (antes de quota/SDK):

```python
    async with connection.get_pool().acquire() as conn:
        await ensure_account_access(
            conn, manager_id=manager_id, customer_id=customer_id,
            session_id=session_id, operation_name=<operation_name_da_funcao>, level="write",
        )
```
(`operation_name`: usar `operation_type` em conversions; `"upload_customer_match_list"` em customer_match. Confirmar `connection` está importado em cada módulo; senão `from src.db import connection`.)

- [ ] **Step 5: Rodar — PASS.**
- [ ] **Step 6: check_pre_push 5/5.**
- [ ] **Step 7: Commit** `git add src/google_ads/conversions.py src/google_ads/customer_match.py tests/unit/test_conversion_customer_match_gate.py && git commit -m "feat(google_ads): hard-gate em run_conversion_upload + run_offline_user_data_job"`

---

### Task 5: Gate em `create_pending` (build/preview)

**Files:**
- Modify: `src/governance/dry_run.py::create_pending` (novo param `manager_id`)
- Modify: todos os callsites de `create_pending` (passar `manager_id`)
- Test: `tests/unit/test_create_pending_gate.py` (criar) + ajustar testes existentes de dry_run

- [ ] **Step 1: Achar callsites.** `grep -rn "create_pending(" src/ tests/` — listar cada mutate tool que cria token em dry-run. (Esperado: várias tools em `src/mcp/tools/` + `tests/`.)

- [ ] **Step 2: Teste falhando** (`tests/unit/test_create_pending_gate.py`):

```python
import pytest
from unittest.mock import AsyncMock, patch
from uuid import uuid4
from src.governance import dry_run
from src.google_ads.access import AccountAccessDeniedError


@pytest.mark.asyncio
async def test_create_pending_denies_without_grant():
    conn = AsyncMock()
    with patch("src.governance.dry_run.ensure_account_access",
               AsyncMock(side_effect=AccountAccessDeniedError("x"))):
        with pytest.raises(AccountAccessDeniedError):
            await dry_run.create_pending(
                conn, manager_id=uuid4(), session_id=uuid4(), customer_id="999",
                operation_type="update_campaign_status", payload={}, blast_summary="...")
    conn.execute.assert_not_called()  # não cria token sem acesso
```

- [ ] **Step 3: Rodar — FAIL** (assinatura ainda não tem `manager_id`).

- [ ] **Step 4: Implementar em `dry_run.py`.** Adicionar `manager_id: UUID` aos kwargs de `create_pending` (antes de `session_id`), import `from src.google_ads.access import ensure_account_access`, e checar logo no início (antes do loop de INSERT):

```python
async def create_pending(
    conn: asyncpg.Connection,
    *,
    manager_id: UUID,
    session_id: UUID,
    customer_id: str,
    operation_type: str,
    payload: dict[str, Any],
    blast_summary: str,
    ttl_minutes: int = DEFAULT_TTL_MINUTES,
) -> str:
    """Persist a pending confirmation. Returns the token.

    Gates on per-account access first: a manager cannot even PREVIEW (mint a
    token for) an account they weren't granted.
    """
    await ensure_account_access(
        conn, manager_id=manager_id, customer_id=customer_id, session_id=session_id,
        operation_name=operation_type, level="write",
    )
    # ... resto inalterado (loop de INSERT) ...
```

- [ ] **Step 5: Atualizar todos os callsites** (do Step 1) pra passar `manager_id=ctx.manager_id`. Em cada mutate tool que chama `create_pending`, adicionar o kwarg. (Mudança mecânica de 1 kwarg por callsite.)

- [ ] **Step 6: Rodar — PASS** + rodar a suíte unit completa pra pegar callsites quebrados: `python -m pytest tests/unit -q`. Corrigir qualquer `create_pending(` em teste que não passe `manager_id`.

- [ ] **Step 7: check_pre_push 5/5.**
- [ ] **Step 8: Commit** `git add -A && git commit -m "feat(governance): gate de acesso em create_pending (bloqueia preview de conta não concedida)"`

---

### Task 6: Ajustar integration tests + full sweep

**Files:**
- Modify: `tests/integration/` — seeds dos testes que exercitam executores reais

- [ ] **Step 1: Mapear impacto.** `grep -rln "run_report\|run_mutation\|run_conversion_upload\|run_offline_user_data_job\|create_pending\|apply_change" tests/integration/`. Para cada teste que chama um executor REAL (não mocka), o gate agora exige grant do (manager, customer) no seed.

- [ ] **Step 2: Padrão de fix.** Em cada teste afetado, após criar o manager + a conta no seed, conceder acesso:
```python
from src.db.repositories import manager_account_access
await manager_account_access.grant(conn, manager_id=mid, customer_id="123", access_level="write", granted_by=mid)
```
OU, se o teste mocka o executor no nível da tool, nenhuma mudança. Decidir por teste.

- [ ] **Step 3: Novo integration test** `tests/integration/test_google_account_gate.py`: gestor SEM grant → `run_report` levanta `AccountAccessDeniedError` + grava audit `status="denied"`; gestor COM grant → passa. (Mirror do `test_meta_*` com seed real.)

- [ ] **Step 4: Full sweep.** `python scripts/check_pre_push.py` (5/5) — local não roda os testcontainers. `python scripts/check_pre_push_full.py` se Docker disponível (6/6); senão CI valida.

- [ ] **Step 5: Grep de regressão.** `grep -rn "can_manager_access\|ensure_account_access" src/` — confirmar gate presente nos 5 choke points (4 executores + create_pending) + nenhum executor Google sem gate.

- [ ] **Step 6: Commit** `git add -A && git commit -m "test(google_ads): seeds de grant nos integration tests + test do account gate"`

---

## Rollout (pós-merge, antes/junto do deploy)
1. Confirmar grants do admin cobrem contas ativas: `/admin/access` (aba Google) — Wellington já tem 25.
2. Quando colaboradores entrarem: admin concede o subset de cada um.
3. Deploy. Smoke: como gestor com grant parcial, chamar tool numa conta concedida (sucesso) e numa não-concedida (erro PT-BR "sem acesso"). Verificar audit `status="denied"`.

## Self-Review (preenchido)
- **Cobertura da spec:** §3.1 helper ✓ T1; §3.2 4 executores ✓ T2+T3+T4; §3.3 create_pending ✓ T5; §3.4 tools sem customer_id inalteradas (não tocadas) ✓; §4 migração/rollout ✓ (rollout section); §5 testing ✓ T6. Decisão §1 (sem bypass) refletida (gate uniforme, sem check `is_admin`).
- **Placeholders:** Task 4 Step 2 e Task 5 Step 5 referenciam "ajustar aos nomes reais"/"callsites do Step 1" — são instruções de leitura-primeiro legítimas (os nomes exatos vêm do grep), com o padrão de código completo mostrado. Sem TODO/TBD.
- **Consistência de tipos:** `ensure_account_access(conn, *, manager_id, customer_id, session_id, operation_name, level)` idêntico em T1 e em todos os callsites (T2-T5). `AccountAccessDeniedError(message)` com `.message`. `create_pending(..., manager_id, ...)` consistente T5.

## Out-of-scope (ver spec §6)
Bypass is_admin; bind de token a manager_id (achado I1); refactor do login_customer_id; UX gestor (Plano B).
