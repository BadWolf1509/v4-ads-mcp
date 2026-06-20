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
