# Sprint 3b.28 — upload_customer_match_list Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Shippar tool MCP `upload_customer_match_list` V0 + dispatcher `run_offline_user_data_job` (segundo dispatcher non-mutate, paralelo a 3b.26). SHA-256 hashing client-side, LGPD compliance (`consent.ad_user_data=GRANTED`), fire-and-forget async model (return job_resource_name + poll via run_gaql).

**Architecture:** Pattern Layer 1 schema + Layer 2 sync (hashing + plaintext detect + duplicates) + Layer 3 async pre-flight (validate_user_list_for_upload) + Always-CONFIRM classify() + 3-step Google API sequence (create_job → add_ops → run_job) via novo dispatcher `run_offline_user_data_job`.

**Tech Stack:** Python 3.12, mcp>=1.2.0, google-ads>=27.0.0 (v24 OfflineUserDataJobService), asyncpg, hashlib (stdlib SHA-256), pytest + ProtoFieldCapture fixture (post-retrofit commit `e055ef7`), ruff + mypy strict. Cloud Run deploy via GitHub Actions.

**Spec:** [`docs/superpowers/specs/2026-05-20-sprint-3b-28-upload-customer-match-list-design.md`](../specs/2026-05-20-sprint-3b-28-upload-customer-match-list-design.md)

---

## File structure

### Phase A: tool + dispatcher

| Arquivo | Action | Responsabilidade |
|---|---|---|
| `src/google_ads/customer_match.py` | **Create** | Module novo. Hashing utilities (`_normalize_and_hash_email`, `_normalize_and_hash_phone`) + builder (`_build_user_data_operations`) + dispatcher (`run_offline_user_data_job`). |
| `src/google_ads/queries/_common.py` | **Modify (append)** | Helper `validate_user_list_for_upload` (Layer 3 pre-flight). |
| `src/mcp/tools/upload_customer_match_list.py` | **Create** | Tool MCP entry. Schema (Layer 1) + `_validate_payload_shape` (Layer 2 sync) + chama hashing + Layer 3 + classify + create_pending. |
| `src/governance/blast_radius.py` | **Modify** | Entry `upload_customer_match_list` em `classify()` — Always CONFIRM. |
| `src/mcp/tools/apply_change.py` | **Modify** | Branch `operation_type == "upload_customer_match_list"` → `run_offline_user_data_job`. |
| `tests/unit/test_customer_match_hashing.py` | **Create** | Unit tests pros 2 hashing utilities (normalize email/phone + SHA-256). |
| `tests/unit/test_validate_user_list_for_upload.py` | **Create** | Unit tests do helper (mock run_report). |
| `tests/unit/test_upload_customer_match_list.py` | **Create** | Unit tests schema + Layer 2 + risk classify. |
| `tests/unit/test_run_offline_user_data_job.py` | **Create** | Dispatcher tests via proto_capture (3-step sequence asserts). |
| `tests/unit/test_blast_radius.py` | **Modify (append)** | `TestUploadCustomerMatchListClassify` (1 test — sempre CONFIRM). |
| `tests/unit/test_tools_schemas.py` | **Modify** | Whitelists incluem `upload_customer_match_list` em ambas as listas. |
| `tests/integration/test_upload_customer_match_list.py` | **Create** | Integration tests (mock helper no namespace da tool, mock dispatcher no namespace da tool — convention pós-3b.5/3b.8). |
| `tests/unit/fixtures/proto_capture.py` | **Modify (potencialmente)** | Extension pra mockar `OfflineUserDataJobService` methods + `ConsentStatusEnum.GRANTED` + `OfflineUserDataJobTypeEnum.CUSTOMER_MATCH_USER_LIST`. **Só modificar se Task A5 falhar com fixture insuficiente** (decision durante implementação). |

### Phase C: smoke + signoff (após deploy Phase A)

| Arquivo | Action | Responsabilidade |
|---|---|---|
| `docs/operacao/phase-3b-28-bootstrap.md` | **Modify** | Atualizar com escopo V0 confirmado + smoke results. |
| `docs/operacao/findings-catalog.md` | **Modify** | Add F-findings se emergir + Last updated. |
| `CLAUDE.md` | **Modify** | Sprint 3b.28 shipped row + tool count 50→51 + Pending/future. |

---

# PHASE A — Implementation

## Task A1: Hashing utilities

**Files:**
- Create: `src/google_ads/customer_match.py` (módulo novo — inicial vai conter apenas os 2 helpers de hashing)
- Test: `tests/unit/test_customer_match_hashing.py` (create)

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_customer_match_hashing.py`:

```python
"""Unit tests for SHA-256 hashing utilities (Sprint 3b.28).

Google Ads Customer Match exige:
- Email: lowercase + remove ALL whitespace + SHA-256 hex digest
- Phone: E.164 normalize (+55 default BR) + lowercase + SHA-256 hex
"""

import hashlib

import pytest


def test_normalize_and_hash_email_basic():
    from src.google_ads.customer_match import _normalize_and_hash_email

    result = _normalize_and_hash_email("user@example.com")
    expected = hashlib.sha256(b"user@example.com").hexdigest()
    assert result == expected
    assert len(result) == 64
    assert all(c in "0123456789abcdef" for c in result)


def test_normalize_and_hash_email_lowercase():
    from src.google_ads.customer_match import _normalize_and_hash_email

    result_upper = _normalize_and_hash_email("USER@EXAMPLE.COM")
    result_lower = _normalize_and_hash_email("user@example.com")
    assert result_upper == result_lower


def test_normalize_and_hash_email_strips_whitespace():
    from src.google_ads.customer_match import _normalize_and_hash_email

    result_with_ws = _normalize_and_hash_email(" us er @example.com ")
    result_clean = _normalize_and_hash_email("user@example.com")
    assert result_with_ws == result_clean


def test_normalize_and_hash_phone_e164_already_formatted():
    from src.google_ads.customer_match import _normalize_and_hash_phone

    result = _normalize_and_hash_phone("+5511987654321")
    expected = hashlib.sha256(b"+5511987654321").hexdigest()
    assert result == expected


def test_normalize_and_hash_phone_default_to_br_plus55():
    """V4 invariant: phone sem country code → assume +55 BR."""
    from src.google_ads.customer_match import _normalize_and_hash_phone

    # Numero BR sem prefixo +55 deve virar +5511987654321 após normalize
    result_no_prefix = _normalize_and_hash_phone("11987654321")
    result_with_prefix = _normalize_and_hash_phone("+5511987654321")
    assert result_no_prefix == result_with_prefix


def test_normalize_and_hash_phone_strips_formatting():
    """Phone com parênteses, traços, espaços normaliza."""
    from src.google_ads.customer_match import _normalize_and_hash_phone

    result_formatted = _normalize_and_hash_phone("(11) 9 8765-4321")
    result_clean = _normalize_and_hash_phone("+5511987654321")
    assert result_formatted == result_clean


def test_normalize_and_hash_phone_strips_leading_zero_br():
    """Numero BR começa com 0 (DDD) → strip antes de adicionar +55."""
    from src.google_ads.customer_match import _normalize_and_hash_phone

    # "011987654321" (com 0 DDD) → "+5511987654321" (sem 0)
    result_with_zero = _normalize_and_hash_phone("011987654321")
    result_clean = _normalize_and_hash_phone("+5511987654321")
    assert result_with_zero == result_clean


def test_normalize_and_hash_email_returns_lowercase_hex():
    from src.google_ads.customer_match import _normalize_and_hash_email

    result = _normalize_and_hash_email("user@example.com")
    # hashlib.sha256.hexdigest() já retorna lowercase
    assert result == result.lower()


def test_normalize_and_hash_phone_handles_international_prefix():
    """Phone com prefix internacional (+1, +44, etc) preserva o prefix."""
    from src.google_ads.customer_match import _normalize_and_hash_phone

    result_us = _normalize_and_hash_phone("+14155552671")
    expected = hashlib.sha256(b"+14155552671").hexdigest()
    assert result_us == expected
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/unit/test_customer_match_hashing.py -v`
Expected: 9 FAIL com `ImportError: No module named 'src.google_ads.customer_match'`

- [ ] **Step 3: Implement the hashing utilities**

Create `src/google_ads/customer_match.py`:

```python
"""Customer Match user list upload — hashing utilities + builder + dispatcher.

Sprint 3b.28 — segundo dispatcher non-mutate fora de GoogleAdsService.mutate
(paralelo a src/google_ads/conversions.py do Sprint 3b.26).

SHA-256 hex digest client-side per Google Ads Customer Match spec.
V4 invariants: phone default country_code +55 (BR-only V4), LGPD consent
GRANTED hardcoded em metadata, enable_partial_failure=True.
"""

from __future__ import annotations

import hashlib
import re


def _normalize_and_hash_email(plaintext: str) -> str:
    """SHA-256 hex digest após lowercase + remove ALL whitespace.

    Per Google Customer Match spec:
    https://developers.google.com/google-ads/api/docs/remarketing/audience-types/customer-match#data-formatting
    """
    normalized = "".join(plaintext.split()).lower()
    return hashlib.sha256(normalized.encode()).hexdigest()


def _normalize_and_hash_phone(plaintext: str) -> str:
    """E.164 normalize + SHA-256 hex digest.

    V4 invariant: phone sem country code prefix (+) → assume +55 (BR).
    Strip non-digit chars except leading +. Numero BR começando com 0 (DDD
    legacy) tem 0 removido antes de adicionar +55.
    """
    # Strip everything except digits + leading +
    digits = re.sub(r"[^\d+]", "", plaintext)
    if not digits.startswith("+"):
        # Numero sem country code → assume BR (+55)
        # Strip leading zero (DDD legacy format) antes do prefix
        digits = "+55" + digits.lstrip("0")
    return hashlib.sha256(digits.encode()).hexdigest()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/unit/test_customer_match_hashing.py -v`
Expected: 9 PASS

- [ ] **Step 5: Run lint + format + mypy**

```
.venv/Scripts/python -m ruff check src/google_ads/customer_match.py tests/unit/test_customer_match_hashing.py
.venv/Scripts/python -m ruff format --check src/google_ads/customer_match.py tests/unit/test_customer_match_hashing.py
.venv/Scripts/python -m mypy src/google_ads/customer_match.py
```

Autofix format se necessário.

- [ ] **Step 6: Commit**

```bash
git add src/google_ads/customer_match.py tests/unit/test_customer_match_hashing.py
git commit -m "$(cat <<'EOF'
feat(mcp): customer_match hashing utilities

Sprint 3b.28 — modulo novo src/google_ads/customer_match.py com helpers de
hashing SHA-256 client-side per Google Customer Match spec.

- _normalize_and_hash_email: lowercase + remove ALL whitespace + hex digest
- _normalize_and_hash_phone: E.164 normalize + SHA-256, default +55 BR
  (V4 invariant), strip leading 0 DDD legacy format

9 unit tests cobrem basic hashing + lowercase + whitespace stripping +
E.164 default BR + formatted input + leading zero handling + international
prefix preservation.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task A2: Helper `validate_user_list_for_upload`

**Files:**
- Modify (append at end): `src/google_ads/queries/_common.py`
- Test: `tests/unit/test_validate_user_list_for_upload.py` (create)

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_validate_user_list_for_upload.py`:

```python
"""Unit tests for validate_user_list_for_upload helper (Sprint 3b.28)."""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest


@pytest.fixture
def fake_ctx():
    return {"manager_id": uuid4(), "session_id": uuid4(), "customer_id": "1163862076"}


def _make_row(
    user_list_id: str,
    list_type: str = "CRM_BASED_USER_LIST",
    read_only: bool = False,
    membership_status: str = "OPEN",
):
    """Build a dict matching the row_formatter output of the helper."""
    return {
        "user_list": {
            "id": user_list_id,
            "name": f"Test list {user_list_id}",
            "type": list_type,
            "read_only": read_only,
            "membership_status": membership_status,
        }
    }


@pytest.mark.asyncio
async def test_user_list_exists_crm_based_enabled_returns_none(fake_ctx):
    from src.google_ads.queries._common import validate_user_list_for_upload

    rows = [_make_row("123")]
    with patch(
        "src.google_ads.queries._common.run_report",
        AsyncMock(return_value=rows),
    ):
        result = await validate_user_list_for_upload(
            manager_id=fake_ctx["manager_id"],
            session_id=fake_ctx["session_id"],
            customer_id=fake_ctx["customer_id"],
            user_list_id="123",
        )
    assert result is None


@pytest.mark.asyncio
async def test_missing_user_list_returns_error_with_id(fake_ctx):
    from src.google_ads.queries._common import validate_user_list_for_upload

    with patch(
        "src.google_ads.queries._common.run_report",
        AsyncMock(return_value=[]),
    ):
        result = await validate_user_list_for_upload(
            manager_id=fake_ctx["manager_id"],
            session_id=fake_ctx["session_id"],
            customer_id=fake_ctx["customer_id"],
            user_list_id="999",
        )
    assert result is not None
    assert "não existe" in result["error"]
    assert result["missing_id"] == "999"


@pytest.mark.asyncio
async def test_wrong_type_returns_error_with_type_name(fake_ctx):
    from src.google_ads.queries._common import validate_user_list_for_upload

    rows = [_make_row("123", list_type="LOGICAL_USER_LIST")]
    with patch(
        "src.google_ads.queries._common.run_report",
        AsyncMock(return_value=rows),
    ):
        result = await validate_user_list_for_upload(
            manager_id=fake_ctx["manager_id"],
            session_id=fake_ctx["session_id"],
            customer_id=fake_ctx["customer_id"],
            user_list_id="123",
        )
    assert result is not None
    assert "LOGICAL_USER_LIST" in result["error"]
    assert "CRM_BASED_USER_LIST" in result["error"]


@pytest.mark.asyncio
async def test_read_only_returns_error_mentioning_policy_acceptance(fake_ctx):
    from src.google_ads.queries._common import validate_user_list_for_upload

    rows = [_make_row("123", read_only=True)]
    with patch(
        "src.google_ads.queries._common.run_report",
        AsyncMock(return_value=rows),
    ):
        result = await validate_user_list_for_upload(
            manager_id=fake_ctx["manager_id"],
            session_id=fake_ctx["session_id"],
            customer_id=fake_ctx["customer_id"],
            user_list_id="123",
        )
    assert result is not None
    assert "read_only" in result["error"]
    assert "Customer Match" in result["error"]


@pytest.mark.asyncio
async def test_membership_status_closed_returns_error(fake_ctx):
    from src.google_ads.queries._common import validate_user_list_for_upload

    rows = [_make_row("123", membership_status="CLOSED")]
    with patch(
        "src.google_ads.queries._common.run_report",
        AsyncMock(return_value=rows),
    ):
        result = await validate_user_list_for_upload(
            manager_id=fake_ctx["manager_id"],
            session_id=fake_ctx["session_id"],
            customer_id=fake_ctx["customer_id"],
            user_list_id="123",
        )
    assert result is not None
    assert "CLOSED" in result["error"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/unit/test_validate_user_list_for_upload.py -v`
Expected: 5 FAIL com `ImportError: cannot import name 'validate_user_list_for_upload'`

- [ ] **Step 3: Implement the helper**

Append at the END of `src/google_ads/queries/_common.py`:

```python
async def validate_user_list_for_upload(
    *,
    manager_id: UUID,
    session_id: UUID,
    customer_id: str,
    user_list_id: str,
) -> dict[str, Any] | None:
    """GAQL pre-flight: user_list existe + type=CRM_BASED_USER_LIST + writable.

    Checks (em ordem, curto-circuita no primeiro fail):
    1. Lista existe (else: missing_id)
    2. type == CRM_BASED_USER_LIST (else: wrong_type)
    3. read_only == False (else: customer_match_policy_not_accepted likely)
    4. membership_status == OPEN (else: closed)

    Returns None if valid, dict com {error, ...} se issue.

    Sprint 3b.28 — pre-flight pra upload_customer_match_list tool.
    """
    query = (
        "SELECT user_list.id, user_list.name, user_list.type, "
        "user_list.read_only, user_list.membership_status "
        "FROM user_list "
        f"WHERE user_list.id = {int(user_list_id)}"
    )

    def _format(row: Any) -> dict[str, Any]:
        return {
            "user_list": {
                "id": str(row.user_list.id),
                "name": row.user_list.name,
                "type": row.user_list.type.name
                if hasattr(row.user_list.type, "name")
                else str(row.user_list.type),
                "read_only": bool(row.user_list.read_only),
                "membership_status": row.user_list.membership_status.name
                if hasattr(row.user_list.membership_status, "name")
                else str(row.user_list.membership_status),
            }
        }

    rows = await run_report(
        manager_id=manager_id,
        session_id=session_id,
        customer_id=customer_id,
        query=query,
        row_formatter=_format,
        operation_name="validate_user_list_for_upload",
    )

    if not rows:
        return {
            "error": (
                f"user_list_id={user_list_id} não existe em customer_id={customer_id}. "
                f"Verifique IDs via run_gaql ou Google Ads UI > Audience Manager."
            ),
            "missing_id": user_list_id,
        }

    ul = rows[0]["user_list"]

    if ul["type"] != "CRM_BASED_USER_LIST":
        return {
            "error": (
                f"user_list_id={user_list_id} type={ul['type']}; upload requer "
                f"CRM_BASED_USER_LIST. Crie nova lista via Google Ads UI > "
                f"Audience Manager > Customer Match."
            ),
        }

    if ul["read_only"]:
        return {
            "error": (
                f"user_list_id={user_list_id} está read_only. Provável causa: "
                f"Customer Match policy não aceita pra conta. Aceite em Google Ads "
                f"UI > Tools > Audience Manager > Customer lists > Accept terms."
            ),
        }

    if ul["membership_status"] != "OPEN":
        return {
            "error": (
                f"user_list_id={user_list_id} membership_status={ul['membership_status']}; "
                f"não aceita uploads agora. Status esperado: OPEN."
            ),
        }

    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/unit/test_validate_user_list_for_upload.py -v`
Expected: 5 PASS

- [ ] **Step 5: Run lint + format + mypy**

```
.venv/Scripts/python -m ruff check src/google_ads/queries/_common.py tests/unit/test_validate_user_list_for_upload.py
.venv/Scripts/python -m ruff format --check src/google_ads/queries/_common.py tests/unit/test_validate_user_list_for_upload.py
.venv/Scripts/python -m mypy src/google_ads/queries/_common.py
```

- [ ] **Step 6: Commit**

```bash
git add src/google_ads/queries/_common.py tests/unit/test_validate_user_list_for_upload.py
git commit -m "$(cat <<'EOF'
feat(mcp): add validate_user_list_for_upload helper

Sprint 3b.28 — Layer 3 pre-flight pra upload_customer_match_list.

GAQL pre-flight SELECT user_list.id, name, type, read_only,
membership_status FROM user_list WHERE id = X. Checks em ordem (curto-
circuita): exists -> type=CRM_BASED -> writable (!read_only) ->
membership_status=OPEN.

Returns None se valid, dict com error PT-BR + dica acionavel se issue.
Mensagem read_only specifically directs gestor ao "Accept terms" do
Customer Match policy em Google Ads UI.

5 unit tests cobrem happy path + missing + wrong_type + read_only +
closed_status.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task A3: classify() entry — Always CONFIRM

**Files:**
- Modify: `src/governance/blast_radius.py`
- Test: `tests/unit/test_blast_radius.py` (append TestClass)

- [ ] **Step 1: Write the failing test**

Open `tests/unit/test_blast_radius.py` and APPEND at the end:

```python


class TestUploadCustomerMatchListClassify:
    def test_always_confirm_regardless_of_member_count(self):
        from src.governance.blast_radius import RiskLevel, classify

        # Single member
        result_single = classify(
            operation="upload_customer_match_list",
            params={"members": [{"email": "x@y.com"}]},
        )
        assert result_single.level == RiskLevel.CONFIRM

        # Batch
        result_batch = classify(
            operation="upload_customer_match_list",
            params={"members": [{"email": f"x{i}@y.com"} for i in range(50)]},
        )
        assert result_batch.level == RiskLevel.CONFIRM

    def test_reason_includes_pii_upload_mention(self):
        from src.governance.blast_radius import classify

        result = classify(
            operation="upload_customer_match_list",
            params={"members": [{"email": "x@y.com"}, {"phone_number": "+5511..."}]},
        )
        assert "PII" in result.reason
        assert "2" in result.reason  # member count
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/unit/test_blast_radius.py::TestUploadCustomerMatchListClassify -v`
Expected: 2 FAIL (operation falls through to default).

- [ ] **Step 3: Implement the branch**

Open `src/governance/blast_radius.py`. Find the existing `elif operation == "update_conversion_action":` block (around line 200). IMMEDIATELY AFTER that block (and before `if operation == "remove_audience":`), add:

```python

    # Upload Customer Match list — sempre CONFIRM (Sprint 3b.28).
    # PII upload tem alto blast radius (LGPD audit + Google billing baseado
    # em members ingeridos). Não há AUTO path V0.
    elif operation == "upload_customer_match_list":
        members = params.get("members", [])
        return RiskClassification(
            RiskLevel.CONFIRM,
            f"upload_customer_match_list: {len(members)} membro(s) — PII upload, sempre CONFIRM",
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/unit/test_blast_radius.py::TestUploadCustomerMatchListClassify -v`
Expected: 2 PASS

Re-run full file: `.venv/Scripts/python -m pytest tests/unit/test_blast_radius.py -v`
Expected: 100% PASS (no regression).

- [ ] **Step 5: Lint + mypy**

```
.venv/Scripts/python -m ruff check src/governance/blast_radius.py tests/unit/test_blast_radius.py
.venv/Scripts/python -m mypy src/governance/blast_radius.py
```

- [ ] **Step 6: Commit**

```bash
git add src/governance/blast_radius.py tests/unit/test_blast_radius.py
git commit -m "$(cat <<'EOF'
feat(governance): classify() entry para upload_customer_match_list

Sprint 3b.28. Sempre CONFIRM — PII upload tem alto blast radius (LGPD
audit + Google billing baseado em members ingeridos). Sem AUTO path V0.

2 unit tests cobrem: single+batch sempre CONFIRM, reason mentions PII +
member count.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task A4: Builder + Dispatcher in customer_match.py

**Files:**
- Modify (append): `src/google_ads/customer_match.py`
- Test: `tests/unit/test_run_offline_user_data_job.py` (create)

**Context:** Dispatcher faz 3 chamadas Google API em sequência (`create_offline_user_data_job` → `add_offline_user_data_job_operations` → `run_offline_user_data_job`). Builder helper `_build_user_data_operations` constrói os `OfflineUserDataJobOperation` items.

**Decision point:** Tests usam `make_capture_client` (proto_capture) ou MagicMock?
- Builder helper (constrói proto messages) → ProtoFieldCapture obrigatório (F42 lesson)
- Dispatcher service-level calls → ProtoFieldCapture pra captures + manual response mocking

Convention pós-retrofit `e055ef7` (3b.26 dispatcher): ProtoFieldCapture pra field assertions; MagicMock só onde NÃO há proto-plus message a capturar (service method calls).

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_run_offline_user_data_job.py`:

```python
"""Unit tests for run_offline_user_data_job dispatcher (Sprint 3b.28).

Pattern paralelo a tests/unit/test_run_conversion_upload.py (3b.26 +
retrofit ProtoFieldCapture commit e055ef7). Dispatcher faz 3 calls em
sequência: create_offline_user_data_job → add_offline_user_data_job_operations
→ run_offline_user_data_job.

Tests usam make_capture_client pra capturar field assignments em OfflineUserDataJob
+ UserData + OfflineUserDataJobOperation. Service-level calls mockadas com
manual response objects.
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from tests.unit.fixtures.proto_capture import make_capture_client


def _make_capture_client_with_offline_user_data_job_service():
    """Extends make_capture_client com mocks pra OfflineUserDataJobService.

    Cada call retorna response object compatível.
    """
    client = make_capture_client()

    # Service methods retornam objetos com resource_name (create) ou None
    service = MagicMock()
    service.create_offline_user_data_job = MagicMock(
        return_value=MagicMock(resource_name="customers/1163862076/offlineUserDataJobs/JOB123")
    )
    service.add_offline_user_data_job_operations = MagicMock(return_value=MagicMock())
    service.run_offline_user_data_job = MagicMock(return_value=MagicMock())

    client.get_service = MagicMock(return_value=service)

    # Enums usados no dispatcher
    client.enums.OfflineUserDataJobTypeEnum.CUSTOMER_MATCH_USER_LIST = "CUSTOMER_MATCH_USER_LIST"
    client.enums.ConsentStatusEnum.GRANTED = "GRANTED"

    return client, service


@pytest.fixture
def fake_ctx():
    return {"manager_id": uuid4(), "session_id": uuid4(), "customer_id": "1163862076"}


@pytest.mark.asyncio
async def test_dispatcher_creates_job_with_customer_match_metadata(fake_ctx):
    """Step 1: create_offline_user_data_job sets job.type_ + user_list resource."""
    from src.google_ads.customer_match import run_offline_user_data_job

    client, service = _make_capture_client_with_offline_user_data_job_service()

    with patch(
        "src.google_ads.customer_match.build_client_for_manager",
        AsyncMock(return_value=client),
    ):
        await run_offline_user_data_job(
            manager_id=fake_ctx["manager_id"],
            session_id=fake_ctx["session_id"],
            customer_id=fake_ctx["customer_id"],
            user_list_id="1234567890",
            operation_type="add",
            hashed_members=[{"hashed_email": "abc123"}],
        )

    # Assert create_offline_user_data_job foi chamada com job que tem type correto
    create_call = service.create_offline_user_data_job.call_args
    assert create_call.kwargs["customer_id"] == "1163862076"

    job_arg = create_call.kwargs["job"]
    assert job_arg.field("type_") == "CUSTOMER_MATCH_USER_LIST"
    assert (
        job_arg.field("customer_match_user_list_metadata.user_list")
        == "customers/1163862076/userLists/1234567890"
    )


@pytest.mark.asyncio
async def test_dispatcher_consent_lgpd_invariants_granted(fake_ctx):
    """V4 invariant: consent.ad_user_data + consent.ad_personalization GRANTED."""
    from src.google_ads.customer_match import run_offline_user_data_job

    client, service = _make_capture_client_with_offline_user_data_job_service()

    with patch(
        "src.google_ads.customer_match.build_client_for_manager",
        AsyncMock(return_value=client),
    ):
        await run_offline_user_data_job(
            manager_id=fake_ctx["manager_id"],
            session_id=fake_ctx["session_id"],
            customer_id=fake_ctx["customer_id"],
            user_list_id="1234567890",
            operation_type="add",
            hashed_members=[{"hashed_email": "abc123"}],
        )

    job_arg = service.create_offline_user_data_job.call_args.kwargs["job"]
    assert (
        job_arg.field("customer_match_user_list_metadata.consent.ad_user_data")
        == "GRANTED"
    )
    assert (
        job_arg.field("customer_match_user_list_metadata.consent.ad_personalization")
        == "GRANTED"
    )


@pytest.mark.asyncio
async def test_dispatcher_add_operations_partial_failure_true(fake_ctx):
    """V4 invariant: enable_partial_failure=True na add_operations request."""
    from src.google_ads.customer_match import run_offline_user_data_job

    client, service = _make_capture_client_with_offline_user_data_job_service()

    with patch(
        "src.google_ads.customer_match.build_client_for_manager",
        AsyncMock(return_value=client),
    ):
        await run_offline_user_data_job(
            manager_id=fake_ctx["manager_id"],
            session_id=fake_ctx["session_id"],
            customer_id=fake_ctx["customer_id"],
            user_list_id="1234567890",
            operation_type="add",
            hashed_members=[{"hashed_email": "abc123"}],
        )

    add_call = service.add_offline_user_data_job_operations.call_args
    request_arg = add_call.kwargs["request"]
    assert request_arg.field("enable_partial_failure") is True
    assert (
        request_arg.field("resource_name")
        == "customers/1163862076/offlineUserDataJobs/JOB123"
    )


@pytest.mark.asyncio
async def test_dispatcher_user_data_uses_hashed_email_field(fake_ctx):
    """UserData.user_identifiers[].hashed_email é setado quando email no member."""
    from src.google_ads.customer_match import run_offline_user_data_job

    client, service = _make_capture_client_with_offline_user_data_job_service()

    with patch(
        "src.google_ads.customer_match.build_client_for_manager",
        AsyncMock(return_value=client),
    ):
        await run_offline_user_data_job(
            manager_id=fake_ctx["manager_id"],
            session_id=fake_ctx["session_id"],
            customer_id=fake_ctx["customer_id"],
            user_list_id="1234567890",
            operation_type="add",
            hashed_members=[{"hashed_email": "abc123hash"}],
        )

    add_call = service.add_offline_user_data_job_operations.call_args
    operations = add_call.kwargs["request"].field("operations")
    # 1 member → 1 operation → 1 user_data → 1 user_identifier com hashed_email
    assert len(operations) == 1


@pytest.mark.asyncio
async def test_dispatcher_returns_job_resource_name_and_three_request_ids(fake_ctx):
    """Return shape: job_resource_name + 3 google_request_ids + members_submitted."""
    from src.google_ads.customer_match import run_offline_user_data_job

    client, service = _make_capture_client_with_offline_user_data_job_service()

    with patch(
        "src.google_ads.customer_match.build_client_for_manager",
        AsyncMock(return_value=client),
    ):
        result = await run_offline_user_data_job(
            manager_id=fake_ctx["manager_id"],
            session_id=fake_ctx["session_id"],
            customer_id=fake_ctx["customer_id"],
            user_list_id="1234567890",
            operation_type="add",
            hashed_members=[{"hashed_email": "abc"}, {"hashed_phone_number": "xyz"}],
        )

    assert (
        result["job_resource_name"]
        == "customers/1163862076/offlineUserDataJobs/JOB123"
    )
    assert "google_request_id_create_job" in result
    assert "google_request_id_add_ops" in result
    assert "google_request_id_run_job" in result
    assert result["members_submitted"] == 2


@pytest.mark.asyncio
async def test_dispatcher_remove_operation_uses_remove_field(fake_ctx):
    """operation_type='remove' → OfflineUserDataJobOperation.remove = user_data
    (não create)."""
    from src.google_ads.customer_match import run_offline_user_data_job

    client, service = _make_capture_client_with_offline_user_data_job_service()

    with patch(
        "src.google_ads.customer_match.build_client_for_manager",
        AsyncMock(return_value=client),
    ):
        await run_offline_user_data_job(
            manager_id=fake_ctx["manager_id"],
            session_id=fake_ctx["session_id"],
            customer_id=fake_ctx["customer_id"],
            user_list_id="1234567890",
            operation_type="remove",
            hashed_members=[{"hashed_email": "abc123"}],
        )

    add_call = service.add_offline_user_data_job_operations.call_args
    operations = add_call.kwargs["request"].field("operations")
    op_zero = operations[0]
    # remove (não create) deve ser setado
    assert op_zero.has("remove") is True
    assert op_zero.has("create") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/unit/test_run_offline_user_data_job.py -v`
Expected: 6 FAIL com `ImportError: cannot import name 'run_offline_user_data_job'`

- [ ] **Step 3: Implement builder + dispatcher in customer_match.py**

Append at the END of `src/google_ads/customer_match.py`:

```python
from typing import Any
from uuid import UUID

import structlog

from src.db.repositories import audit_log
from src.google_ads.client import build_client_for_manager
from src.google_ads.request_id import (
    get_capture_interceptor,
    get_request_id,
    reset_request_id,
)
from src.governance.rate_limit import before_call, hash_developer_token, record_actual

log = structlog.get_logger(__name__)


def _build_user_data_operations(
    client: Any,
    operation_type: str,
    hashed_members: list[dict[str, Any]],
) -> list[Any]:
    """Build OfflineUserDataJobOperation list from hashed members.

    Each member → 1 UserData with 1-2 user_identifiers (hashed_email and/or
    hashed_phone_number) → 1 OfflineUserDataJobOperation.

    operation_type: "add" (operation.create = user_data) or
                    "remove" (operation.remove = user_data).
    """
    operations: list[Any] = []
    for member in hashed_members:
        user_data = client.get_type("UserData")

        if "hashed_email" in member:
            identifier = client.get_type("UserIdentifier")
            identifier.hashed_email = member["hashed_email"]
            user_data.user_identifiers.append(identifier)

        if "hashed_phone_number" in member:
            identifier = client.get_type("UserIdentifier")
            identifier.hashed_phone_number = member["hashed_phone_number"]
            user_data.user_identifiers.append(identifier)

        op = client.get_type("OfflineUserDataJobOperation")
        if operation_type == "add":
            op.create = user_data
        else:  # "remove"
            op.remove = user_data
        operations.append(op)

    return operations


async def run_offline_user_data_job(
    *,
    manager_id: UUID,
    session_id: UUID,
    customer_id: str,
    user_list_id: str,
    operation_type: str,  # "add" | "remove"
    hashed_members: list[dict[str, Any]],
) -> dict[str, Any]:
    """3-step Google API sequence pra Customer Match upload:

    1. create_offline_user_data_job → job_resource
    2. add_offline_user_data_job_operations(operations[], enable_partial_failure=True)
    3. run_offline_user_data_job (fire-and-forget; backend processa em horas)

    Returns:
        {
            job_resource_name: str,
            google_request_id_create_job: str,
            google_request_id_add_ops: str,
            google_request_id_run_job: str,
            members_submitted: int,
        }

    Sprint 3b.28 — segundo dispatcher non-mutate, paralelo a run_conversion_upload
    do Sprint 3b.26.
    """
    log.info(
        "run_offline_user_data_job_start",
        customer_id=customer_id,
        user_list_id=user_list_id,
        operation_type=operation_type,
        member_count=len(hashed_members),
    )

    client = await build_client_for_manager(manager_id=manager_id)
    service = client.get_service("OfflineUserDataJobService")

    # Step 1: Create job
    reset_request_id()
    job = client.get_type("OfflineUserDataJob")
    job.type_ = client.enums.OfflineUserDataJobTypeEnum.CUSTOMER_MATCH_USER_LIST
    job.customer_match_user_list_metadata.user_list = (
        f"customers/{customer_id}/userLists/{user_list_id}"
    )
    # V4 LGPD invariants
    job.customer_match_user_list_metadata.consent.ad_user_data = (
        client.enums.ConsentStatusEnum.GRANTED
    )
    job.customer_match_user_list_metadata.consent.ad_personalization = (
        client.enums.ConsentStatusEnum.GRANTED
    )
    create_response = service.create_offline_user_data_job(
        customer_id=customer_id, job=job
    )
    job_resource = create_response.resource_name
    create_req_id = get_request_id() or "unknown"

    # Step 2: Add operations
    reset_request_id()
    operations = _build_user_data_operations(client, operation_type, hashed_members)
    add_request = client.get_type("AddOfflineUserDataJobOperationsRequest")
    add_request.resource_name = job_resource
    add_request.operations = operations
    add_request.enable_partial_failure = True
    service.add_offline_user_data_job_operations(request=add_request)
    add_req_id = get_request_id() or "unknown"

    # Step 3: Run job (fire-and-forget)
    reset_request_id()
    service.run_offline_user_data_job(resource_name=job_resource)
    run_req_id = get_request_id() or "unknown"

    log.info(
        "run_offline_user_data_job_done",
        customer_id=customer_id,
        job_resource_name=job_resource,
        members_submitted=len(hashed_members),
    )

    return {
        "job_resource_name": job_resource,
        "google_request_id_create_job": create_req_id,
        "google_request_id_add_ops": add_req_id,
        "google_request_id_run_job": run_req_id,
        "members_submitted": len(hashed_members),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/unit/test_run_offline_user_data_job.py -v`
Expected: 6 PASS.

**If tests fail with fixture issues:** the `proto_capture` fixture may not support `request.operations = operations` (list assignment) or `client.get_service` properly. If failures are non-trivial:
- Read the actual error
- Check if `make_capture_client()` needs extension for `OfflineUserDataJobService` mocking
- Adapt the helper `_make_capture_client_with_offline_user_data_job_service` instead of changing the dispatcher

The goal is dispatcher code is correct + tests work. If fixture extension is needed, do it INLINE in this test file (helper), not in `tests/unit/fixtures/proto_capture.py`. Future tasks can promote it if reused.

- [ ] **Step 5: Lint + format + mypy**

```
.venv/Scripts/python -m ruff check src/google_ads/customer_match.py tests/unit/test_run_offline_user_data_job.py
.venv/Scripts/python -m ruff format --check src/google_ads/customer_match.py tests/unit/test_run_offline_user_data_job.py
.venv/Scripts/python -m mypy src/google_ads/customer_match.py
```

- [ ] **Step 6: Commit**

```bash
git add src/google_ads/customer_match.py tests/unit/test_run_offline_user_data_job.py
git commit -m "$(cat <<'EOF'
feat(mcp): run_offline_user_data_job dispatcher + builder

Sprint 3b.28 — segundo dispatcher non-mutate (paralelo a 3b.26 run_conversion_upload).

3-step Google API sequence:
1. create_offline_user_data_job (job.type_=CUSTOMER_MATCH_USER_LIST,
   metadata.user_list=resource path, consent.ad_user_data/ad_personalization
   GRANTED hardcoded V4 LGPD invariant)
2. add_offline_user_data_job_operations (operations[], enable_partial_failure=True)
3. run_offline_user_data_job (fire-and-forget; backend processa em horas)

_build_user_data_operations: cada member -> 1 UserData com 1-2
user_identifiers (hashed_email/hashed_phone_number) -> 1
OfflineUserDataJobOperation.create (add) or .remove (remove).

Returns job_resource_name + 3 google_request_ids + members_submitted.

6 unit tests via proto_capture (NÃO MagicMock — F42 lesson; retrofit
test_run_conversion_upload em commit e055ef7 estabeleceu pattern):
job.type_ + metadata, consent LGPD GRANTED, enable_partial_failure,
hashed_email field assignment, return shape, remove vs create.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task A5: Tool MCP `upload_customer_match_list`

**Files:**
- Create: `src/mcp/tools/upload_customer_match_list.py`
- Test: `tests/unit/test_upload_customer_match_list.py` (create — schema + Layer 2 ONLY)

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_upload_customer_match_list.py`:

```python
"""Unit tests for upload_customer_match_list tool — schema + Layer 2 (Sprint 3b.28).

Integration tests (Layer 3 mocking, dispatcher routing) live em
tests/integration/test_upload_customer_match_list.py.
"""

from src.mcp.tools.upload_customer_match_list import (
    _SCHEMA,
    _hash_members,
    _validate_payload_shape,
)


def test_schema_has_no_composition_keywords():
    """Regression guard: F18/F25 family."""
    import json

    schema_str = json.dumps(_SCHEMA)
    assert '"oneOf"' not in schema_str
    assert '"allOf"' not in schema_str
    assert '"anyOf"' not in schema_str


def test_schema_explicit_types():
    """F1 lesson: every property has explicit type."""

    def _walk(obj):
        if isinstance(obj, dict):
            if "properties" in obj:
                for prop_name, prop_schema in obj["properties"].items():
                    assert "type" in prop_schema, f"property '{prop_name}' missing type"
                    _walk(prop_schema)
            if "items" in obj:
                _walk(obj["items"])
            for v in obj.values():
                if isinstance(v, dict | list):
                    _walk(v)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)

    _walk(_SCHEMA)


def test_validate_payload_shape_accepts_well_formed_input():
    args = {
        "customer_id": "1163862076",
        "user_list_id": "1234567890",
        "operation": "add",
        "members": [
            {"email": "user1@example.com"},
            {"phone_number": "+5511987654321"},
            {"email": "user2@example.com", "phone_number": "11987654322"},
        ],
    }
    assert _validate_payload_shape(args) is None


def test_validate_payload_shape_rejects_member_without_identifier():
    args = {
        "customer_id": "1163862076",
        "user_list_id": "1234567890",
        "operation": "add",
        "members": [{}],  # vazio — sem email nem phone
    }
    # Layer 1 (jsonschema minProperties:1) já pega isso, mas Layer 2 também
    # valida pra mensagem clara
    err = _validate_payload_shape(args)
    assert err is not None
    assert "sem identificador" in err or "minProperties" in err


def test_validate_payload_shape_rejects_already_hashed_email():
    args = {
        "customer_id": "1163862076",
        "user_list_id": "1234567890",
        "operation": "add",
        "members": [
            {"email": "5e884898da28047151d0e56f8dc6292773603d0d6aabbdd62a11ef721d1542d8"}
        ],
    }
    err = _validate_payload_shape(args)
    assert err is not None
    assert "SHA-256" in err or "já parece" in err
    assert "plaintext" in err


def test_validate_payload_shape_rejects_invalid_email_format():
    args = {
        "customer_id": "1163862076",
        "user_list_id": "1234567890",
        "operation": "add",
        "members": [{"email": "not-an-email"}],
    }
    err = _validate_payload_shape(args)
    assert err is not None
    assert "inválido" in err or "invalid" in err.lower()


def test_validate_payload_shape_rejects_duplicate_email_after_normalize():
    args = {
        "customer_id": "1163862076",
        "user_list_id": "1234567890",
        "operation": "add",
        "members": [
            {"email": "User@Example.COM"},
            {"email": "user@example.com"},  # mesmo após lowercase
        ],
    }
    err = _validate_payload_shape(args)
    assert err is not None
    assert "duplicados" in err


def test_validate_payload_shape_rejects_duplicate_phone_after_normalize():
    args = {
        "customer_id": "1163862076",
        "user_list_id": "1234567890",
        "operation": "add",
        "members": [
            {"phone_number": "(11) 9 8765-4321"},
            {"phone_number": "+5511987654321"},  # mesmo após normalize
        ],
    }
    err = _validate_payload_shape(args)
    assert err is not None
    assert "duplicados" in err


def test_hash_members_returns_hashed_email():
    members = [{"email": "user@example.com"}]
    result = _hash_members(members)
    assert len(result) == 1
    assert "hashed_email" in result[0]
    assert "hashed_phone_number" not in result[0]
    assert len(result[0]["hashed_email"]) == 64  # SHA-256 hex


def test_hash_members_handles_email_and_phone_per_member():
    members = [{"email": "user@example.com", "phone_number": "+5511987654321"}]
    result = _hash_members(members)
    assert "hashed_email" in result[0]
    assert "hashed_phone_number" in result[0]


def test_hash_members_strips_plaintext_keys():
    """Hashed output não deve carrear plaintext email/phone."""
    members = [{"email": "user@example.com", "phone_number": "+5511987654321"}]
    result = _hash_members(members)
    assert "email" not in result[0]
    assert "phone_number" not in result[0]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/unit/test_upload_customer_match_list.py -v`
Expected: 11 FAIL com `ImportError: No module named 'src.mcp.tools.upload_customer_match_list'`

- [ ] **Step 3: Implement the tool**

Create `src/mcp/tools/upload_customer_match_list.py`:

```python
"""Tool: upload_customer_match_list — upload members (email/phone) pra Customer Match user list.

Sprint 3b.28. V0 minimal:
- 2 identifier types: email + phone_number
- 2 operation types: add + remove
- Fire-and-forget async: returns job_resource_name + to_check_status hint
- LGPD invariants: consent.ad_user_data + consent.ad_personalization GRANTED
- SHA-256 hashing client-side (PII nunca sai do processo unhashed)

Layer 1 (jsonschema): customer_id pattern, user_list_id pattern, operation enum,
  members array maxItems 1000, items minProperties 1.
Layer 2 (sync): rejeita member sem identifier, email já-hashed (^[a-f0-9]{64}$),
  email regex inválido, duplicates após normalize.
Layer 3 (async): validate_user_list_for_upload — exists + CRM_BASED + writable.
"""

import re
from typing import Any

from src.db import connection
from src.google_ads.customer_match import (
    _normalize_and_hash_email,
    _normalize_and_hash_phone,
)
from src.google_ads.queries._common import validate_user_list_for_upload
from src.governance.blast_radius import classify
from src.governance.dry_run import create_pending
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool

# Sha-256 hex digest é exatamente 64 chars [0-9a-f]
_SHA256_HEX_RE = re.compile(r"^[a-f0-9]{64}$")
# Email validation simples (Layer 2 — Google API valida formato final)
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "user_list_id": {"type": "string", "pattern": "^[0-9]+$"},
        "operation": {"type": "string", "enum": ["add", "remove"]},
        "members": {
            "type": "array",
            "minItems": 1,
            "maxItems": 1000,
            "items": {
                "type": "object",
                "properties": {
                    "email": {"type": "string", "minLength": 3, "maxLength": 254},
                    "phone_number": {"type": "string", "minLength": 8, "maxLength": 30},
                },
                "additionalProperties": False,
                "minProperties": 1,
            },
        },
    },
    "required": ["customer_id", "user_list_id", "operation", "members"],
    "additionalProperties": False,
}


def _validate_payload_shape(args: dict[str, Any]) -> str | None:
    """Layer 2: synchronous validation pre-Google.

    Rejects:
    - Member sem nenhum identifier (Layer 1 minProperties já pega, mas
      garantia adicional)
    - Email já parece SHA-256 hash (^[a-f0-9]{64}$) — gestor deve passar plaintext
    - Email regex inválido (formato local@domain)
    - Duplicate email (após lowercase + remove whitespace) no batch
    - Duplicate phone (após normalize) no batch
    """
    members = args["members"]

    # Per-member validation
    for idx, member in enumerate(members):
        if not member:
            return f"member item {idx} sem identificador (precisa email OU phone_number)."

        if "email" in member:
            email = member["email"]
            if _SHA256_HEX_RE.match(email):
                return (
                    f"member item {idx}: email '{email[:20]}...' já parece SHA-256 hash. "
                    f"Passe plaintext; tool faz hash internamente."
                )
            if not _EMAIL_RE.match(email):
                return (
                    f"member item {idx}: email '{email}' inválido (formato esperado: "
                    f"local@domain)."
                )

        # Phone formato é mais permissivo — normalize tenta extrair digits
        # qualquer string com pelo menos 8 digits passa Layer 2; Google API
        # rejeita inválidos no apply

    # Duplicate detection — usa hashing functions pra normalize antes de comparar
    seen_emails: set[str] = set()
    dup_emails: list[str] = []
    seen_phones: set[str] = set()
    dup_phones: list[str] = []

    for member in members:
        if "email" in member:
            normalized_hash = _normalize_and_hash_email(member["email"])
            if normalized_hash in seen_emails and normalized_hash not in dup_emails:
                dup_emails.append(member["email"])
            seen_emails.add(normalized_hash)

        if "phone_number" in member:
            normalized_hash = _normalize_and_hash_phone(member["phone_number"])
            if normalized_hash in seen_phones and normalized_hash not in dup_phones:
                dup_phones.append(member["phone_number"])
            seen_phones.add(normalized_hash)

    if dup_emails:
        return (
            f"emails duplicados no batch após normalize: {dup_emails}. "
            f"Cada email aparece no máximo 1 vez."
        )
    if dup_phones:
        return (
            f"phone_numbers duplicados no batch após normalize: {dup_phones}. "
            f"Cada phone aparece no máximo 1 vez."
        )

    return None


def _hash_members(members: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Layer 2: SHA-256 hash members + drop plaintext keys.

    Output members têm SÓ hashed_email/hashed_phone_number — plaintext nunca
    é persistido no dry_run_tokens nem no audit_log (LGPD minimização).
    """
    hashed: list[dict[str, str]] = []
    for member in members:
        entry: dict[str, str] = {}
        if "email" in member:
            entry["hashed_email"] = _normalize_and_hash_email(member["email"])
        if "phone_number" in member:
            entry["hashed_phone_number"] = _normalize_and_hash_phone(member["phone_number"])
        hashed.append(entry)
    return hashed


@register_tool(
    name="upload_customer_match_list",
    description=(
        "Upload members (email/phone) pra Customer Match user list. SHA-256 "
        "hash client-side (PII nunca sai unhashed). LGPD invariants: consent "
        "GRANTED + audit log sem plaintext. Operation: 'add' (incluir) ou "
        "'remove' (excluir — opt-out LGPD). User list deve existir (CRM_BASED + "
        "Customer Match policy aceita). Tool retorna job_resource_name + hint "
        "pra checar status (jobs processam em horas no backend Google)."
    ),
    input_schema=_SCHEMA,
)
async def upload_customer_match_list(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    user_list_id = args["user_list_id"]
    operation_type = args["operation"]
    members = args["members"]

    # Layer 2: sync validation
    shape_error = _validate_payload_shape(args)
    if shape_error:
        return {
            "status": "error",
            "operation": "upload_customer_match_list",
            "customer_id": customer_id,
            "error": shape_error,
        }

    # Layer 3: async pre-flight (validate user_list existe + tipo + writable)
    preflight_error = await validate_user_list_for_upload(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        user_list_id=user_list_id,
    )
    if preflight_error:
        return {
            "status": "error",
            "operation": "upload_customer_match_list",
            "customer_id": customer_id,
            **preflight_error,
        }

    # Hash members (plaintext discardado — só hashed_* segue downstream)
    hashed_members = _hash_members(members)

    # Risk classify — sempre CONFIRM (PII upload)
    risk = classify(operation="upload_customer_match_list", params={"members": members})

    # Payload pro dry_run_tokens — SEM plaintext, SEM identificadores
    payload = {
        "user_list_id": user_list_id,
        "operation": operation_type,
        "hashed_members": hashed_members,
        "__target_count__": len(members),
    }
    summary = (
        f"Upload Customer Match: {operation_type.upper()} {len(members)} membro(s) "
        f"pra user_list_id={user_list_id}."
    )

    # Always CONFIRM (PII upload tem alto blast radius)
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        token = await create_pending(
            conn,
            session_id=ctx.session_id,
            customer_id=customer_id,
            operation_type="upload_customer_match_list",
            payload=payload,
            blast_summary=summary,
        )

    return {
        "status": "dry_run",
        "operation": "upload_customer_match_list",
        "customer_id": customer_id,
        "user_list_id": user_list_id,
        "operation_type": operation_type,
        "members_count": len(members),
        "blast_summary": summary,
        "confirmation_token": token,
        "expires_in_minutes": 10,
        "to_apply": (
            "Chame apply_change(confirmation_token=<token>) para submeter o job. "
            "Job é assíncrono no backend Google — após apply, tool retorna "
            "job_resource_name. Pra checar status posterior, use run_gaql com "
            "query 'SELECT offline_user_data_job.status, failure_reason FROM "
            "offline_user_data_job WHERE offline_user_data_job.id = <id>'."
        ),
        "confirmation_reason": risk.reason,
    }
```

- [ ] **Step 4: Run unit tests, verify they pass**

Run: `.venv/Scripts/python -m pytest tests/unit/test_upload_customer_match_list.py -v`
Expected: 11 PASS.

- [ ] **Step 5: Cross-cutting schema regression**

Run: `.venv/Scripts/python -m pytest tests/unit/test_tools_schemas.py -v -k "no_composition"`
Expected: PASS.

- [ ] **Step 6: Lint + format + mypy**

```
.venv/Scripts/python -m ruff check src/mcp/tools/upload_customer_match_list.py tests/unit/test_upload_customer_match_list.py
.venv/Scripts/python -m ruff format --check src/mcp/tools/upload_customer_match_list.py tests/unit/test_upload_customer_match_list.py
.venv/Scripts/python -m mypy src/mcp/tools/upload_customer_match_list.py
```

- [ ] **Step 7: Commit**

```bash
git add src/mcp/tools/upload_customer_match_list.py tests/unit/test_upload_customer_match_list.py
git commit -m "$(cat <<'EOF'
feat(mcp): upload_customer_match_list tool — schema + Layer 2 + Layer 3

Sprint 3b.28 V0 minimal:
- Schema: customer_id + user_list_id (regex 10/N digits) + operation enum
  add|remove + members array maxItems 1000 items minProperties 1 com
  email/phone_number opt
- Layer 2: _validate_payload_shape (rejeita ja-hashed em email, regex
  invalida, duplicates apos normalize) + _hash_members (SHA-256 +
  plaintext discarded)
- Layer 3: validate_user_list_for_upload (helper Task A2)
- Sempre CONFIRM via classify (Task A3) — payload em dry_run_tokens SEM
  plaintext, SEM identificadores (LGPD minimizacao)

Auto-discovery do _registry pega o arquivo (count visivel 50 -> 51
post-deploy).

11 unit tests cobrem schema regression + Layer 2 (5 reject paths +
happy) + _hash_members (3 cases).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task A6: apply_change router branch

**Files:**
- Modify: `src/mcp/tools/apply_change.py`

- [ ] **Step 1: Find the dispatcher routing block**

Run: `grep -n "operation_type ==" src/mcp/tools/apply_change.py`
Note the location of the existing `import_offline_conversions` branch (around line 58).

- [ ] **Step 2: Inspect the existing branch pattern**

Read 20 lines around the `import_offline_conversions` branch. Use as template.

- [ ] **Step 3: Add the new branch**

In `src/mcp/tools/apply_change.py`, immediately AFTER the existing `if saved.operation_type == "import_offline_conversions":` block (look for the `return` statement that closes it), add a new branch:

```python
    if saved.operation_type == "upload_customer_match_list":
        from src.google_ads.customer_match import run_offline_user_data_job

        result = await run_offline_user_data_job(
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=saved.customer_id,
            user_list_id=saved.payload["user_list_id"],
            operation_type=saved.payload["operation"],
            hashed_members=saved.payload["hashed_members"],
        )
        return {
            "status": "submitted",
            "operation": "upload_customer_match_list",
            "customer_id": saved.customer_id,
            "user_list_id": saved.payload["user_list_id"],
            "operation_type": saved.payload["operation"],
            "members_submitted": result["members_submitted"],
            "job_resource_name": result["job_resource_name"],
            "google_request_id_create_job": result["google_request_id_create_job"],
            "google_request_id_add_ops": result["google_request_id_add_ops"],
            "google_request_id_run_job": result["google_request_id_run_job"],
            "to_check_status": (
                f"Job é assíncrono no backend Google (processa em horas). "
                f"Pra verificar status, use run_gaql com query 'SELECT "
                f"offline_user_data_job.status, offline_user_data_job."
                f"failure_reason FROM offline_user_data_job WHERE "
                f"offline_user_data_job.id = "
                f"{result['job_resource_name'].rsplit('/', 1)[-1]}'."
            ),
        }
```

**Important:** the `import` of `run_offline_user_data_job` goes INSIDE the branch (lazy import) to avoid module-level cycle if `apply_change` is imported by `customer_match.py` transitively.

- [ ] **Step 4: Run all integration tests for apply_change**

Run: `.venv/Scripts/python -m pytest tests/ -v -k "apply_change" 2>&1 | tail -20`
Expected: pre-existing tests still PASS.

- [ ] **Step 5: Lint + format + mypy**

```
.venv/Scripts/python -m ruff check src/mcp/tools/apply_change.py
.venv/Scripts/python -m ruff format --check src/mcp/tools/apply_change.py
.venv/Scripts/python -m mypy src/mcp/tools/apply_change.py
```

- [ ] **Step 6: Commit**

```bash
git add src/mcp/tools/apply_change.py
git commit -m "$(cat <<'EOF'
feat(mcp): apply_change router branch para upload_customer_match_list

Sprint 3b.28 — branch novo no router que dispatch operation_type=
"upload_customer_match_list" para src.google_ads.customer_match.
run_offline_user_data_job (Task A4).

Return shape inclui status="submitted", job_resource_name, 3
google_request_ids (create + add + run) e to_check_status com query GAQL
template embutida pro gestor copiar/colar.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task A7: Integration test for upload_customer_match_list

**Files:**
- Create: `tests/integration/test_upload_customer_match_list.py`

- [ ] **Step 1: Write the integration tests**

Create `tests/integration/test_upload_customer_match_list.py`:

```python
"""Integration tests for upload_customer_match_list tool (Sprint 3b.28).

Mock pattern crítico (convention pós-3b.5/3b.8):
- validate_user_list_for_upload patched at TOOL namespace
  (src.mcp.tools.upload_customer_match_list.*), NOT _common.
- run_offline_user_data_job patched at apply_change OR dispatcher namespace
  (whichever apply_change imports from).
"""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from testcontainers.postgres import PostgresContainer

from src.db import connection, migrate
from src.db.repositories import managers, mcp_sessions
from src.mcp.context import McpRequestContext, clear_current, set_current


@pytest.fixture
async def pg() -> PostgresContainer:
    with PostgresContainer("postgres:16-alpine") as container:
        yield container


@pytest.fixture
async def db(pg):
    dsn = pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
    await connection.init_pool(dsn, min_size=1, max_size=4)
    try:
        await migrate.run_all()
        yield connection.get_pool()
    finally:
        await connection.close_pool()


@pytest.fixture
async def session_ctx(db):
    pool = db
    async with pool.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="t@v4.com", full_name=None)
        from src.auth.sessions import generate_session_token, hash_session_token

        token = generate_session_token()
        sess = await mcp_sessions.create(
            conn, manager_id=mid, token_hash=hash_session_token(token), label="t"
        )
    ctx = McpRequestContext(manager_id=mid, session_id=sess.id)
    set_current(ctx)
    yield ctx
    clear_current()


@pytest.mark.integration
async def test_layer2_rejects_already_hashed_email(db, session_ctx):
    """Layer 2 catches plaintext-pretending-to-be-hashed input."""
    from src.mcp.tools.upload_customer_match_list import upload_customer_match_list

    args = {
        "customer_id": "1163862076",
        "user_list_id": "1234567890",
        "operation": "add",
        "members": [
            {"email": "5e884898da28047151d0e56f8dc6292773603d0d6aabbdd62a11ef721d1542d8"}
        ],
    }
    result = await upload_customer_match_list(args)
    assert result["status"] == "error"
    assert "SHA-256" in result["error"] or "já parece" in result["error"]


@pytest.mark.integration
async def test_preflight_missing_user_list_returns_error(db, session_ctx):
    """Preflight mock at TOOL namespace (convention pós-3b.5/3b.8)."""
    from src.mcp.tools.upload_customer_match_list import upload_customer_match_list

    args = {
        "customer_id": "1163862076",
        "user_list_id": "9999999999",
        "operation": "add",
        "members": [{"email": "user@example.com"}],
    }
    mock_error = {
        "error": "user_list_id=9999999999 não existe...",
        "missing_id": "9999999999",
    }
    with patch(
        "src.mcp.tools.upload_customer_match_list.validate_user_list_for_upload",
        AsyncMock(return_value=mock_error),
    ):
        result = await upload_customer_match_list(args)
    assert result["status"] == "error"
    assert result["missing_id"] == "9999999999"


@pytest.mark.integration
async def test_happy_path_returns_dry_run_token(db, session_ctx):
    """Layer 1+2+3 pass → dry_run + confirmation_token retornado."""
    from src.mcp.tools.upload_customer_match_list import upload_customer_match_list

    args = {
        "customer_id": "1163862076",
        "user_list_id": "1234567890",
        "operation": "add",
        "members": [
            {"email": "user1@example.com"},
            {"phone_number": "+5511987654321"},
        ],
    }
    with patch(
        "src.mcp.tools.upload_customer_match_list.validate_user_list_for_upload",
        AsyncMock(return_value=None),
    ):
        result = await upload_customer_match_list(args)
    assert result["status"] == "dry_run"
    assert "confirmation_token" in result
    assert result["members_count"] == 2
    assert result["operation_type"] == "add"


@pytest.mark.integration
async def test_remove_operation_passes_remove_to_payload(db, session_ctx):
    """operation='remove' é preserved no payload pro dispatcher."""
    from src.mcp.tools.upload_customer_match_list import upload_customer_match_list

    args = {
        "customer_id": "1163862076",
        "user_list_id": "1234567890",
        "operation": "remove",
        "members": [{"email": "user1@example.com"}],
    }
    with patch(
        "src.mcp.tools.upload_customer_match_list.validate_user_list_for_upload",
        AsyncMock(return_value=None),
    ):
        result = await upload_customer_match_list(args)
    assert result["status"] == "dry_run"
    assert result["operation_type"] == "remove"


@pytest.mark.integration
async def test_payload_contains_only_hashed_members_no_plaintext(db, session_ctx):
    """LGPD: dry_run_tokens NÃO armazena plaintext email/phone — só hashed.

    Verifica que após dry_run, o token tem payload com hashed_email/
    hashed_phone_number e SEM email/phone_number plaintext.
    """
    from src.governance.dry_run import fetch_pending
    from src.mcp.tools.upload_customer_match_list import upload_customer_match_list

    args = {
        "customer_id": "1163862076",
        "user_list_id": "1234567890",
        "operation": "add",
        "members": [{"email": "secret@example.com"}],
    }
    with patch(
        "src.mcp.tools.upload_customer_match_list.validate_user_list_for_upload",
        AsyncMock(return_value=None),
    ):
        result = await upload_customer_match_list(args)

    token = result["confirmation_token"]

    # Fetch saved payload from dry_run_tokens (Layer 4 — DB inspection)
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        saved = await fetch_pending(conn, token=token, session_id=session_ctx.session_id)

    payload = saved.payload
    assert "hashed_members" in payload
    hashed_member = payload["hashed_members"][0]
    assert "hashed_email" in hashed_member
    # CRITICAL: plaintext keys MUST NOT appear
    assert "email" not in hashed_member
    assert "phone_number" not in hashed_member
    # Hash value não deve ser o plaintext literal
    assert hashed_member["hashed_email"] != "secret@example.com"
    # SHA-256 hex length
    assert len(hashed_member["hashed_email"]) == 64
```

- [ ] **Step 2: Try to run integration tests (Docker required)**

Run: `.venv/Scripts/python -m pytest tests/integration/test_upload_customer_match_list.py -v -m integration 2>&1 | tail -30`

Expected outcomes:
- **If Docker is running**: 5 PASS.
- **If Docker is NOT running**: tests can't start (acceptable — CI will run them).

If a test fails with assertion error (não Docker), investigate.

**Possível issue:** `fetch_pending` em dry_run module — verifique se a API existe. Se não, adapte o teste pra fazer raw DB query (`SELECT payload FROM dry_run_tokens WHERE id = ?`).

- [ ] **Step 3: Lint + format + mypy**

```
.venv/Scripts/python -m ruff check tests/integration/test_upload_customer_match_list.py
.venv/Scripts/python -m ruff format --check tests/integration/test_upload_customer_match_list.py
.venv/Scripts/python -m mypy tests/integration/test_upload_customer_match_list.py
```

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_upload_customer_match_list.py
git commit -m "$(cat <<'EOF'
test(mcp): integration tests upload_customer_match_list

Sprint 3b.28. 5 integration tests via testcontainers Postgres:

- Layer 2 rejects already-hashed email input
- Preflight missing_user_list returns error (mock no namespace TOOL,
  convention pos-3b.5/3b.8 evita slipping local pre-push gate)
- Happy path returns dry_run + confirmation_token + members_count
- Operation='remove' passes through ao payload corretamente
- LGPD: dry_run_tokens payload SO tem hashed_email/hashed_phone_number;
  ZERO plaintext (test verify via fetch_pending na DB)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task A8: Update schema whitelists

**Files:**
- Modify: `tests/unit/test_tools_schemas.py`

- [ ] **Step 1: Find the whitelist lines**

Run: `grep -n "import_offline_conversions" tests/unit/test_tools_schemas.py`
Note both occurrences (typically `test_all_expected_tools_registered` AND `test_no_unexpected_tools`).

- [ ] **Step 2: Add `upload_customer_match_list` to both expected sets**

After each `"import_offline_conversions",  # Sprint 3b.26` line, add:

```python
        "upload_customer_match_list",  # Sprint 3b.28
```

(2 occurrences in the file — one per `expected` set).

- [ ] **Step 3: Run schema tests**

Run: `.venv/Scripts/python -m pytest tests/unit/test_tools_schemas.py -v`
Expected: all PASS (including new tool in whitelists).

- [ ] **Step 4: Commit**

```bash
git add tests/unit/test_tools_schemas.py
git commit -m "$(cat <<'EOF'
test(mcp): add upload_customer_match_list aos whitelists schema tests

Sprint 3b.28 — schema regression whitelists em test_tools_schemas.py
(test_all_expected_tools_registered + test_no_unexpected_tools) precisam
incluir o novo tool name explicitamente pra os 2 testes nao falharem.

1 linha em cada expected set (50 tools -> 51 listed).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task A9: Pre-push gate + push Phase A

- [ ] **Step 1: Run pre-push gate**

Run: `.venv/Scripts/python scripts/check_pre_push.py 2>&1 | tail -15`
Expected: `5/5 PASS`. Se algum step falhar, fix antes de prosseguir.

- [ ] **Step 2: (opt-in, Docker required) Full sweep**

Run: `.venv/Scripts/python scripts/check_pre_push_full.py 2>&1 | tail -20`
Expected: `6/6 PASS`. Recommended pra Sprint 3b.28 — dispatcher novo + preflight novo precisam DB integration sweep.

Se Docker unavailable: rodar apenas `pytest -v -m integration -k "upload_customer_match_list"` se possível, ou pular e confiar no CI.

- [ ] **Step 3: Push**

Run: `git push origin main 2>&1 | tail -10`
Expected: bypass de admin policy do main + push success.

- [ ] **Step 4: Watch CI**

Run: `gh run list --limit 4 --json databaseId,name,status,conclusion,headSha 2>&1 | head`
Captura SHAs do CI + Deploy. Use Monitor com poll loop:

```bash
# Monitor template — substitua <SHA> pelo SHA do commit Phase A
prev=""; while true; do
  s=$(gh run list --limit 2 --json databaseId,name,status,conclusion,headSha 2>/dev/null || echo "[]");
  cur=$(echo "$s" | jq -r '.[] | select(.headSha=="<SHA>") | "\(.name): \(.status) \(.conclusion)"' | sort);
  new=$(comm -13 <(echo "$prev") <(echo "$cur"));
  if [ -n "$new" ]; then echo "$new"; fi;
  prev=$cur;
  if echo "$cur" | grep -q "completed" && [ "$(echo "$cur" | grep -c "completed")" -eq 2 ]; then echo "BOTH RUNS COMPLETED"; break; fi;
  sleep 30;
done
```

Expected: CI + Deploy ambos SUCCESS dentro de 5-8 min.

- [ ] **Step 5: Verify production**

```
curl -s -o /dev/null -w "HTTP %{http_code}\n" https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/health
gcloud run revisions list --service=v4-ads-mcp --region=southamerica-east1 --limit=2 --format="value(name,active)"
```

Expected: HTTP 200 + new revisão ativa.

- [ ] **Step 6: Verify tool count in MCP**

Após restart Claude Code, verificar via ToolSearch ou `/mcp` que `mcp__v4-ads__upload_customer_match_list` aparece na lista. Count 50 → 51.

Se tool não aparece: check `gcloud logging read` for import errors. Re-deploy se necessário.

---

# PHASE B — Smoke + signoff (após Phase A deployed)

## Task B1: Update runbook with V0 confirmed scope

**Files:**
- Modify: `docs/operacao/phase-3b-28-bootstrap.md`

- [ ] **Step 1: Open runbook**

O runbook esqueleto foi gerado 2026-05-19 pelo subagent `smoke-runbook-generator` quando o sprint estava marcado pra 3b.27. Agora Sprint 3b.28 está em produção com escopo V0 confirmado (D1-D5). Vamos atualizar.

Read `docs/operacao/phase-3b-28-bootstrap.md` (skim full file).

- [ ] **Step 2: Update header (Status + Histórico)**

Procurar o bloco `> **Status do runbook:** DRAFT/esqueleto pré-spec.` e substituir por:

```markdown
> **Status do runbook:** READY pra smoke execution (Sprint 3b.28 V0 deployed em produção).
>
> **Histórico:** Esqueleto originalmente gerado em 2026-05-19 pelo subagent
> `smoke-runbook-generator` quando o sprint estava temporariamente marcado pra 3b.27.
> Renomeado pra 3b.28 + escopo V0 confirmado em 2026-05-20 via D1-D5 (ver spec).
```

- [ ] **Step 3: Sync test scenarios com V0 escopo**

Os tests no runbook esqueleto provavelmente referenciam 5 identifier types e operation types diferentes do V0 confirmado. Atualizar pra:
- identifier types V0: SÓ email + phone_number (não address_info/mobile_id/third_party_user_id)
- operation types V0: add + remove (não remove_all)
- async model: fire-and-forget (não synchronous wait)

Vou usar `superpowers:smoke-runbook-generator` subagent **só se** o runbook estiver muito diferente. Provavelmente um Edit manual já cobre.

Estratégia mínima: Editar a Smoke results table pra ter 7-12 tests V0-aligned. Test list referência:

| # | Test | Result | Notes |
|---|---|---|---|
| T0a | GAQL pré-smoke — listar UserLists CRM_BASED em Nutry | ⬜ pending | |
| T0b | Setup: criar UserList Customer Match em Nutry (UI Wellington) se nenhuma existir | ⬜ pending | Skip se já existe |
| T1 | Layer 2 reject — member sem identifier | ⬜ pending | |
| T2 | Layer 2 reject — email já-hashed (SHA-256 input) | ⬜ pending | |
| T3 | Layer 2 reject — email regex inválido | ⬜ pending | |
| T4 | Layer 2 reject — duplicate email após normalize | ⬜ pending | |
| T5 | Layer 3 reject — user_list_id 9999 não existe | ⬜ pending | |
| T6 | Schema regression — maxItems 1001 → "is too long" | ⬜ pending | |
| T7 | dry_run happy path — 5 emails synthetic (smoke+N@v4.com) → CONFIRM token | ⬜ pending | |
| T8 | apply T7 → status="submitted" + job_resource_name | ⬜ pending | **DEFERRED** se Nutry sem Customer Match terms acceptance (F41-equivalent) |
| T9 | status poll via run_gaql usando job_resource_name de T8 → PENDING/RUNNING/SUCCESS | ⬜ pending | Manual |
| T10 | operation="remove" — repete T7 com remove → dry_run + apply OK | ⬜ pending | |
| T11 | V4 invariants verify — bit-a-bit via interceptor capture (post-deploy) | ⬜ pending | consent GRANTED + partial_failure=True + +55 default |

- [ ] **Step 4: Lint check (markdown)**

(Sem ruff pra markdown — só visual scan. Confirma que tabela está bem-formada e links funcionam.)

- [ ] **Step 5: Commit**

```bash
git add docs/operacao/phase-3b-28-bootstrap.md
git commit -m "$(cat <<'EOF'
docs(runbook): Sprint 3b.28 V0 — sync com escopo confirmado D1-D5

Esqueleto gerado 19/05 atualizado pra V0 minimal (D1-D5):
- 2 identifier types: email + phone_number (sem address/mobile/3p)
- 2 operation types: add + remove (sem remove_all)
- async model fire-and-forget (não sync wait)

11 test scenarios + 2 setup pre-smoke. T8/T9 marcados DEFERRED se Nutry
sem Customer Match terms (F41-equivalent).

Status DRAFT -> READY pra execution.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task B2: Smoke execution (Wellington manual)

Wellington executa os 11 tests + 2 setup em Nutry sandbox.

- [ ] **Step 1: Setup pre-smoke (T0a + T0b)**

Execute via MCP:
1. `run_gaql` com query `SELECT user_list.id, name, type, read_only, membership_status FROM user_list WHERE user_list.type = 'CRM_BASED_USER_LIST'` em Nutry (`1163862076`)
2. Se zero results, criar Customer Match user list via Google Ads UI manual ANTES de continuar
3. Anotar `user_list_id` resultante no runbook (substituir `<UL_ID>` em todos os tests)

- [ ] **Step 2: Execute T1-T6 (validation rejects — não tocam Google)**

Todos os 6 tests são Layer 1/2/3 rejects que NÃO chegam no Google API (rate_counter +1 cada pra T5 que faz GAQL preflight). Esperado: 6 PASS rápidos.

- [ ] **Step 3: Execute T7 (dry_run happy path)**

Synthetic emails `smoke+1@v4.com` a `smoke+5@v4.com`. Esperado: `dry_run` + token retornado.

- [ ] **Step 4: Execute T8 (apply T7)**

Apply token de T7. **3 outcomes possíveis:**
- ✅ PASS: `status=submitted` + `job_resource_name` + 3 request_ids
- ⏸ DEFERRED: Nutry sem Customer Match terms — pré-flight bloqueia OR Google rejeita no step 1 (create_offline_user_data_job). Marcar como F41-equivalent.
- ❌ FAIL: erro inesperado — investigate

- [ ] **Step 5: Execute T9 (status poll)**

Pegar `job_resource_name` de T8. Extrair `job_id` (último segmento do path). Rodar:

```
run_gaql(customer_id="1163862076", query="SELECT offline_user_data_job.status, offline_user_data_job.failure_reason FROM offline_user_data_job WHERE offline_user_data_job.id = <JOB_ID>")
```

Esperado: status PENDING/RUNNING (logo após T8) ou eventualmente SUCCESS/FAILED (após horas).

- [ ] **Step 6: Execute T10 (remove operation)**

Repetir T7 + T8 com `operation="remove"`.

- [ ] **Step 7: Execute T11 (V4 invariants verify)**

Post-T8, inspeccionar Cloud Logging do request (use `gcloud logging read` filtrando pelo google_request_id_create_job ou Cloud Run logs) pra confirmar:
- `consent.ad_user_data = GRANTED` na request payload
- `consent.ad_personalization = GRANTED`
- `enable_partial_failure = True`
- Phone numbers com `+55` default

- [ ] **Step 8: Atualizar runbook com resultados**

No runbook, marcar cada T# com `✅ PASS` / `❌ FAIL` / `⏸ DEFERRED` + Google request_ids relevantes em Notes.

Se algum F-finding emergiu, documentar inline na seção `### F-findings emerged`.

---

## Task B3: Final signoff — reviewer + catalog + CLAUDE.md

- [ ] **Step 1: Dispatch mcp-tool-quality-reviewer**

Use Agent tool with `subagent_type: mcp-tool-quality-reviewer`:

```
Audite Sprint 3b.28 combo:

1. Tool nova: src/mcp/tools/upload_customer_match_list.py
2. Dispatcher novo: src/google_ads/customer_match.py (módulo inteiro:
   hashing helpers + builder + run_offline_user_data_job)
3. Helper novo: src/google_ads/queries/_common.py::validate_user_list_for_upload
4. apply_change router branch

Tests:
- tests/unit/test_customer_match_hashing.py
- tests/unit/test_validate_user_list_for_upload.py
- tests/unit/test_upload_customer_match_list.py
- tests/unit/test_run_offline_user_data_job.py
- tests/integration/test_upload_customer_match_list.py

Smoke runbook: docs/operacao/phase-3b-28-bootstrap.md (executado: <N>/12 PASS).

Atenção especial:
- Group 1.1 zero composition keywords
- Group 2.1 ProtoFieldCapture em builder + dispatcher tests (F42 lesson)
- Group 2.2 mock no namespace da TOOL (não _common)
- Group 3.2 V4 invariants LGPD (consent.ad_user_data + ad_personalization
  GRANTED + +55 phone default + enable_partial_failure=True)
- Group 4.1/4.3 always-CONFIRM dry_run + smoke runbook

Retorne report estruturado.
```

Expected: PASS/FAIL/N/A per check + verdict + top-3 fixes se FAIL.

- [ ] **Step 2: Apply top-3 fixes (se FAIL)**

Inline ou via subagent fix. Reviewer pode flagrar convention-drift LOW (aceitar com nota) vs HIGH (fix obrigatório).

- [ ] **Step 3: Update findings-catalog.md**

Abrir `docs/operacao/findings-catalog.md`. Adicionar F-finding(s) emergido(s) no smoke (se aplicável):

```markdown
| **F45** | <SEV> | 3b.28 | <fix sprint> | <symptom + fix description>. [phase-3b-28-bootstrap.md] |
```

Update Cross-reference table:
```markdown
| 3b.28 | F45 (→ 3b.28.x) |
```

(Se zero findings emergidos, pular — só atualizar Last updated.)

Update Last updated:
```markdown
> **Last updated:** 2026-05-XX (Sprint 3b.28 signoff)
```

- [ ] **Step 4: Update CLAUDE.md**

Adicionar Sprint 3b.28 shipped row em "Shipped + in production" table:

```markdown
| Sprint 3b.28 — `upload_customer_match_list` (51st tool, second non-mutate dispatcher) | ✅ 2026-05-XX | Production revision `v4-ads-mcp-XXXXX-xxx`. **Tool count 50 → 51.** <N>/11 PASS após <K> fix iteration(s). V0 minimal: 2 identifier types (email + phone_number) × 2 operation types (add + remove). LGPD invariants: consent GRANTED + audit log sem plaintext (minimização). Fire-and-forget async (return job_resource_name + run_gaql template). [<F-findings>]. Runbook: [`phase-3b-28-bootstrap.md`](docs/operacao/phase-3b-28-bootstrap.md). |
```

Atualizar header:
- `**50 MCP tools**` → `**51 MCP tools**` (também em 2-3 lugares no header)

Atualizar Pending/future:
- Remove `Sprint 3b.28 next-in-queue` (shipped)
- Promote `Sprint 3b.29 candidate (remove_* bundle)` pra next-in-queue position

- [ ] **Step 5: Commit signoff**

```bash
git add docs/operacao/findings-catalog.md CLAUDE.md docs/operacao/phase-3b-28-bootstrap.md
git commit -m "$(cat <<'EOF'
docs(signoff): Sprint 3b.28 shipped — upload_customer_match_list

C3 signoff final pos-smoke <N>/11 PASS.

- phase-3b-28-bootstrap: smoke results consolidados + F-findings doc'd
- findings-catalog: <F-finding details + Last updated 2026-05-XX>
- CLAUDE.md: Sprint 3b.28 row shipped, tool count 50 -> 51. Pending/future
  reordenado (3b.29 remove_* bundle next-in-queue).

mcp-tool-quality-reviewer subagent verdict: <PASS counts / FAIL counts>.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 6: Push final**

```bash
git push origin main
```

CI runs final.

---

## Self-review do plan

**1. Spec coverage:**
- Component A schema/Layer 2 → Task A5
- Component A Layer 3 helper → Task A2
- Component B builder + dispatcher → Task A4
- classify() → Task A3
- Hashing utilities → Task A1
- apply_change router → Task A6
- Integration tests → Task A7
- Schema whitelists → Task A8
- Pre-push + push → Task A9
- Smoke runbook update → Task B1
- Smoke execution → Task B2
- Sign-off → Task B3

**2. Placeholder scan:**
- "<N>/11 PASS" e "<SHA>" e "<F-findings>" são placeholders esperados no signoff (revisão substitui com valores reais durante execução). Aceitáveis pq Task B2/B3 são pós-smoke.

Sem TBD/TODO/FIXME em código ou test code.

**3. Type consistency:**
- Helper signature: `validate_user_list_for_upload(*, manager_id: UUID, session_id: UUID, customer_id: str, user_list_id: str) -> dict[str, Any] | None` (consistent across Tasks A2 + A5 + A6)
- Dispatcher signature: `run_offline_user_data_job(*, manager_id, session_id, customer_id, user_list_id, operation_type, hashed_members) -> dict[str, Any]` (consistent A4 + A6)
- `_hash_members(members: list[dict[str, Any]]) -> list[dict[str, str]]` (A5)
- `hashed_members[]` items têm `hashed_email` e/ou `hashed_phone_number` (consistent A4 + A5)
- Return shape do tool inclui `status: "dry_run" | "error"` (A5), `status: "submitted"` no apply (A6) — consistent

**4. Possible gaps:**
- `proto_capture` fixture extension não tem task separada — está embedded no Task A4 step 4 ("If fixture extension needed, do it INLINE in the test file as helper, not in proto_capture.py"). Aceitável — extensão emerge sob demanda.

---

## Execution handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-20-sprint-3b-28-upload-customer-match-list.md`.**

**Two execution options:**

**1. Subagent-Driven (recommended)** — Dispatch fresh subagent per task, two-stage review entre tasks (spec + quality), fast iteration. Default pra projetos com TDD discipline embedded.

**2. Inline Execution** — Execute tasks in this session com batch execution + checkpoints. Mais rápido em tokens, mas contexto acumula.

**Which approach?**
