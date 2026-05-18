"""Proto field capture fixture for mutate builder tests.

Replaces MagicMock pattern that masks proto field assignment bugs (Sprint
3b.4 finding A4 — Google override of negative=True passed undetected because
MagicMock accepts any attribute set silently).

Usage:
    client = make_capture_client()
    ops = build_apply_audience(client, "1234567890", payload)
    assert ops[0].field("ad_group_criterion_operation.create.negative") is True

Repeated fields (Sprint 3b.16, simplified em 3b.17 post-F16):
    # proto-plus repeated message field — use .append() with typed instance
    h = client.get_type("AdTextAsset")
    h.text = "H1"
    rsa.headlines.append(h)
    op.field_count("...responsive_search_ad.headlines")  # → 1

    # proto-plus repeated scalar field — use .append() with raw value
    ad.final_urls.append("https://example.com/")
    op.field_count("...ad.final_urls")  # → 1

NOTE (Sprint 3b.17 / F16 lesson): we previously had .add() support here
(mocking raw protobuf API), but proto-plus repeated message fields don't
expose .add() — only .append(). Tests passed but builder broke in
production (Sprint 3b.16 smoke T1 caught it). Mock surface now mirrors
proto-plus reality. Don't add .add() back — let it AttributeError loudly
if any builder regresses.
"""

from typing import Any
from unittest.mock import MagicMock


class _RepeatedCapture:
    """Captures proto-plus repeated field usage via .append().

    When builder code does ``rsa.headlines.append(item)`` or
    ``ad.final_urls.append(url)``, the relevant _SubCapture detects the
    first .append() call and promotes itself to a _RepeatedCapture stored
    in the parent dict under the same key.
    """

    def __init__(self) -> None:
        self._items: list[Any] = []

    def append(self, value: Any) -> None:
        """Append a value (proto-plus typed instance, dict, or scalar)."""
        self._items.append(value)

    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self) -> Any:
        return iter(self._items)


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

    def append(self, value: Any) -> None:
        """Promote this sub-capture to a _RepeatedCapture in parent, then append.

        proto-plus repeated message fields use .append(typed_instance) —
        raw .add() (raw protobuf descriptor pool API) is NOT supported by
        proto-plus and would AttributeError in production. Sprint 3b.16 F16
        lesson: this mock used to support .add(), tests passed but real SDK
        rejected — fixture now mirrors proto-plus reality.
        """
        repeated = _RepeatedCapture()
        self._parent[self._name] = repeated
        repeated.append(value)


class CapturedOp:
    """Wraps a proto-like op + records every assignment in a nested dict.

    Drop-in replacement for client.get_type('MutateOperation') in builder
    tests. Builder code does e.g. `op.ad_group_criterion_operation.create.negative = True`
    — capture stores it so tests can assert via
    `op.field("ad_group_criterion_operation.create.negative")`.

    NOTE (Sprint 3b.24.4 F33 reversal): ``__call__`` has been removed. The real
    google-ads-python SDK's ``client.get_type("X")`` returns an INSTANCE directly —
    calling it with ``()`` raises TypeError in production. Sprint 3b.24.3 added
    ``__call__`` here so tests would pass with ``client.get_type("X")()``, but that
    masked the production TypeError. Mock surface now mirrors SDK reality: no parens.
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
            elif isinstance(cur, CapturedOp):
                # CapturedOp stored via explicit assignment (canonical proto-plus
                # oneof pattern: campaign.X = client.get_type("X")).
                # Sprint 3b.24.1 F30: explicit oneof assignment stores a CapturedOp
                # as a value; traversal must descend into its _captured dict.
                cur = cur._captured
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                return None
        if isinstance(cur, (_SubCapture, CapturedOp)):
            return None  # Sub-message, not a leaf value
        return cur

    def has(self, path: str) -> bool:
        """True if path was explicitly assigned (vs never set)."""
        raw = self._raw(path)
        return raw is not None and not isinstance(raw, (_SubCapture, CapturedOp))

    def _raw(self, path: str) -> Any:
        """Internal: resolve path without the _SubCapture→None coercion."""
        cur: Any = self._captured
        for part in path.split("."):
            if isinstance(cur, _SubCapture):
                cur = cur._captured
            elif isinstance(cur, CapturedOp):
                # See field() note above — descend into explicitly-assigned sub-ops.
                cur = cur._captured
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                return None
        return cur

    def field_count(self, path: str) -> int:
        """Return the number of items in a repeated field at dotted path.

        Works for both _RepeatedCapture (from .add()/.append()) and plain lists.
        Returns 0 if the path was never set.
        """
        raw = self._raw(path)
        if raw is None:
            return 0
        if isinstance(raw, _RepeatedCapture):
            return len(raw)
        if isinstance(raw, list):
            return len(raw)
        return 0


def make_capture_client() -> MagicMock:
    """Mock SDK client whose get_type() returns CapturedOp instances.

    Path helpers + enums return predictable strings so tests can assert on the
    path values written to the op. Helpers mirror the actual SDK signatures:
    - AdGroupService.ad_group_path(cid, ag_id) → parent ad_group path
    - CampaignService.campaign_path(cid, c_id) → parent campaign path
    - AdGroupCriterionService.ad_group_criterion_path(cid, ag_id, crit_id)
      → compound ~-separated criterion path
    - CampaignCriterionService.campaign_criterion_path(cid, c_id, crit_id)
      → compound ~-separated criterion path (Sprint 3b.6 A5 fix)
    - AdService.ad_path(cid, ad_id) → top-level ad path (Sprint 3b.18)
    - ConversionActionService.conversion_action_path(cid, ca_id) → conversion
      action path (Sprint 3b.19A)
    - ConversionValueRuleService.conversion_value_rule_path(cid, rule_id) →
      conversion value rule path (Sprint 3b.19B)
    - ConversionValueRuleSetService.conversion_value_rule_set_path(cid, set_id)
      → conversion value rule set path (Sprint 3b.19B)
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
    ad_service = MagicMock()
    ad_service.ad_path = lambda cid, ad_id: f"customers/{cid}/ads/{ad_id}"
    conv_action_service = MagicMock()
    conv_action_service.conversion_action_path = lambda cid, ca_id: (
        f"customers/{cid}/conversionActions/{ca_id}"
    )
    conv_value_rule_service = MagicMock()
    conv_value_rule_service.conversion_value_rule_path = lambda cid, rule_id: (
        f"customers/{cid}/conversionValueRules/{rule_id}"
    )
    conv_value_rule_set_service = MagicMock()
    conv_value_rule_set_service.conversion_value_rule_set_path = lambda cid, set_id: (
        f"customers/{cid}/conversionValueRuleSets/{set_id}"
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
        if name == "AdService":
            return ad_service
        if name == "ConversionActionService":
            return conv_action_service
        if name == "ConversionValueRuleService":
            return conv_value_rule_service
        if name == "ConversionValueRuleSetService":
            return conv_value_rule_set_service
        return MagicMock()

    client.get_service = get_service
    client.get_type = lambda _name: CapturedOp()
    client.enums.AdGroupCriterionStatusEnum.ENABLED = "AG_ENABLED"
    client.enums.CampaignCriterionStatusEnum.ENABLED = "CAMP_ENABLED"

    # ConversionAction enums (Sprint 3b.19A). Return enum name as scalar string
    # so test assertions can check value passed correctly.
    class _EnumDict:
        def __init__(self, prefix: str) -> None:
            self._prefix = prefix

        def __getitem__(self, key: str) -> str:
            return f"{self._prefix}_{key}"

        def __getattr__(self, key: str) -> str:
            return f"{self._prefix}_{key}"

    client.enums.ConversionActionCategoryEnum = _EnumDict("CAT")
    client.enums.ConversionActionTypeEnum = _EnumDict("TYPE")
    client.enums.ConversionActionStatusEnum = _EnumDict("STATUS")
    client.enums.ConversionActionCountingTypeEnum = _EnumDict("COUNTING")

    # ConversionValueRule + RuleSet enums (Sprint 3b.19B). Use _EnumDict helper.
    client.enums.ValueRuleOperationEnum = _EnumDict("OP")
    client.enums.ValueRuleDeviceTypeEnum = _EnumDict("DEVICE")
    client.enums.ValueRuleGeoLocationMatchTypeEnum = _EnumDict("MATCH")
    client.enums.ValueRuleSetAttachmentTypeEnum = _EnumDict("ATTACH")
    client.enums.ValueRuleSetDimensionEnum = _EnumDict("DIM")
    client.enums.ConversionValueRuleStatusEnum = _EnumDict("RULE_STATUS")
    client.enums.ConversionValueRuleSetStatusEnum = _EnumDict("SET_STATUS")

    # Campaign create enums (Sprint 3b.24). Return the raw member name as a
    # plain string so builder tests can assert e.g. status == "PAUSED",
    # advertising_channel_type == "SEARCH", delivery_method == "STANDARD".
    # _EnumDict prefix set to "" so __getattr__("PAUSED") → "PAUSED" (no prefix).
    class _BareEnumDict:
        """Like _EnumDict but returns the key itself (no prefix)."""

        def __getitem__(self, key: str) -> str:
            return key

        def __getattr__(self, key: str) -> str:
            return key

    client.enums.BudgetDeliveryMethodEnum = _BareEnumDict()
    client.enums.AdvertisingChannelTypeEnum = _BareEnumDict()
    client.enums.CampaignStatusEnum = _BareEnumDict()
    # F34 (Sprint 3b.24.4): EU political advertising compliance — V4 always
    # DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING (Brazilian advertiser).
    client.enums.EuPoliticalAdvertisingStatusEnum = _BareEnumDict()

    return client
