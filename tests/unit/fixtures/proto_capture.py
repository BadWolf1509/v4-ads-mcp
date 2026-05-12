"""Proto field capture fixture for mutate builder tests.

Replaces MagicMock pattern that masks proto field assignment bugs (Sprint
3b.4 finding A4 — Google override of negative=True passed undetected because
MagicMock accepts any attribute set silently).

Usage:
    client = make_capture_client()
    ops = build_apply_audience(client, "1234567890", payload)
    assert ops[0].field("ad_group_criterion_operation.create.negative") is True
"""

from typing import Any
from unittest.mock import MagicMock


class _SubCapture:
    """Nested capture for `op.foo.bar.baz = X` style assignments."""

    def __init__(self, name: str, parent_dict: dict[str, Any]) -> None:
        self._name = name
        self._parent = parent_dict
        self._captured: dict[str, Any] = {}

    def __setattr__(self, key: str, value: Any) -> None:
        if key.startswith("_"):
            object.__setattr__(self, key, value)
        else:
            self._captured[key] = value

    def __getattr__(self, key: str) -> Any:
        if key.startswith("_"):
            return object.__getattribute__(self, key)
        if key not in self._captured:
            self._captured[key] = _SubCapture(key, self._captured)
        return self._captured[key]


class CapturedOp:
    """Wraps a proto-like op + records every assignment in a nested dict.

    Drop-in replacement for client.get_type('MutateOperation') in builder
    tests. Builder code does e.g. `op.ad_group_criterion_operation.create.negative = True`
    — capture stores it so tests can assert via
    `op.field("ad_group_criterion_operation.create.negative")`.
    """

    def __init__(self) -> None:
        self._captured: dict[str, Any] = {}

    def __setattr__(self, key: str, value: Any) -> None:
        if key.startswith("_"):
            object.__setattr__(self, key, value)
        else:
            self._captured[key] = value

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            return object.__getattribute__(self, name)
        if name not in self._captured:
            self._captured[name] = _SubCapture(name, self._captured)
        return self._captured[name]

    def field(self, path: str) -> Any:
        """Get captured value at dotted path. Returns None if not set."""
        cur: Any = self._captured
        for part in path.split("."):
            if isinstance(cur, _SubCapture):
                cur = cur._captured
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                return None
        if isinstance(cur, _SubCapture):
            return None  # Sub-message, not a leaf value
        return cur

    def has(self, path: str) -> bool:
        """True if path was explicitly assigned (vs never set)."""
        return self.field(path) is not None


def make_capture_client() -> MagicMock:
    """Mock SDK client whose get_type() returns CapturedOp instances.

    Path helpers + enums return predictable strings so tests can assert on the
    path values written to the op. Helpers mirror the actual SDK signatures:
    - AdGroupService.ad_group_path(cid, ag_id) → parent ad_group path
    - CampaignService.campaign_path(cid, c_id) → parent campaign path
    - AdGroupCriterionService.ad_group_criterion_path(cid, ag_id, crit_id)
      → compound ~-separated criterion path
    - CampaignCriterionService.campaign_criterion_path(cid, c_id, crit_id)
      → compound ~-separated criterion path (Sprint 3b.6 A5 fix — used to be
      flat in old code, corrected to compound matching SDK).
    """
    client = MagicMock()

    ag_service = MagicMock()
    ag_service.ad_group_path = lambda cid, ag_id: f"customers/{cid}/adGroups/{ag_id}"
    camp_service = MagicMock()
    camp_service.campaign_path = lambda cid, c_id: f"customers/{cid}/campaigns/{c_id}"
    ag_crit_service = MagicMock()
    ag_crit_service.ad_group_criterion_path = lambda cid, ag_id, crit_id: (
        f"customers/{cid}/adGroupCriteria/{ag_id}~{crit_id}"
    )
    camp_crit_service = MagicMock()
    camp_crit_service.campaign_criterion_path = lambda cid, c_id, crit_id: (
        f"customers/{cid}/campaignCriteria/{c_id}~{crit_id}"
    )

    def get_service(name: str) -> Any:
        if name == "AdGroupService":
            return ag_service
        if name == "CampaignService":
            return camp_service
        if name == "AdGroupCriterionService":
            return ag_crit_service
        if name == "CampaignCriterionService":
            return camp_crit_service
        return MagicMock()

    client.get_service = get_service
    client.get_type = lambda _name: CapturedOp()
    client.enums.AdGroupCriterionStatusEnum.ENABLED = "AG_ENABLED"
    client.enums.CampaignCriterionStatusEnum.ENABLED = "CAMP_ENABLED"
    return client
