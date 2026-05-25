#!/usr/bin/env python3
"""
Mass-edit script FINAL: Tag 59 tool files with bucket classification.
Task C — Sprint 3b.39

THREE INDEPENDENT OPERATIONS (no complex state):
1. Add # bucket: comment on line 1 (idempotent)
2. Add bucket="..." kwarg before @register_tool closing paren (idempotent)
3. Add [CORE]/[DEFER] prefix to description (idempotent)
"""

import re
from pathlib import Path

ALWAYS_TOOLS = {
    "get_change_history",
    "create_and_link_assets",
    "audit_competitor_keywords",
    "list_my_accounts",
    "add_negative_keywords",
    "get_conversion_actions",
    "audit_goal_attribution",
    "create_conversion_action",
    "update_keyword_status",
    "audit_zombie_keywords",
    "apply_audience",
    "audit_quality_score",
    "get_recommendations",
    "bulk_pause_by_query",
    "create_campaign",
    "meta_get_account_overview",
    "remove_audience",
    "update_ad_group_status",
    "update_keyword_bid",
    "detect_drift",
    "meta_list_my_ad_accounts",
}

DEFER_TOOLS = {
    "audit_orphan_smart_actions",
    "remove_negative_keywords",
    "update_ad_status",
    "add_keywords",
    "add_negatives_from_search_terms",
    "create_conversion_value_rule_set",
    "create_rsa",
    "get_my_audit_log",
    "update_conversion_action",
    "update_rsa",
    "create_ad_group",
    "update_ad_group_bid",
    "update_campaign_budget",
    "update_campaign_status",
    "get_my_rate_limit_status",
    "import_offline_conversions",
    "apply_change",
    "apply_recommendation",
    "dismiss_recommendation",
    "get_account_overview",
    "get_ad_group_performance",
    "get_ad_performance",
    "get_audience_performance",
    "get_budget_pacing",
    "get_campaign_performance",
    "get_device_performance",
    "get_funnel_metrics",
    "get_geo_performance",
    "get_hourly_performance",
    "get_keyword_performance",
    "get_negative_keywords_audit",
    "get_search_terms_report",
    "get_top_keywords_creatives",
    "list_gaql_resources",
    "run_gaql",
    "update_campaign_bidding",
    "upload_customer_match_list",
    "validate_gaql",
}

TOOLS_DIR = Path("D:/V4 ads MCP/src/mcp/tools")


def get_bucket(tool_name: str) -> str:
    if tool_name in ALWAYS_TOOLS:
        return "always"
    elif tool_name in DEFER_TOOLS:
        return "defer"
    else:
        raise ValueError(f"Tool {tool_name} not found in bucket classification")


def safe_find_closing_paren(content: str, open_pos: int) -> int:
    """Find closing paren, skipping over strings."""
    depth = 1
    pos = open_pos + 1
    while pos < len(content) and depth > 0:
        char = content[pos]
        if char in ('"', "'"):
            quote_char = char
            pos += 1
            while pos < len(content) and content[pos] != quote_char:
                if content[pos] == "\\":
                    pos += 2
                else:
                    pos += 1
            if pos < len(content):
                pos += 1  # skip closing quote
        elif char == "(":
            depth += 1
            pos += 1
        elif char == ")":
            depth -= 1
            pos += 1
        else:
            pos += 1
    return pos - 1 if depth == 0 else -1


def process_file(file_path: Path) -> tuple[bool, str]:
    """Edit a tool file. Returns (success, message)."""
    tool_name = file_path.stem
    bucket = get_bucket(tool_name)
    prefix = "[CORE]" if bucket == "always" else "[DEFER]"

    content = file_path.read_text(encoding="utf-8")

    # Operation 1: Add # bucket: comment on line 1
    if not content.startswith("# bucket:"):
        lines = content.split("\n", 1)
        if len(lines) == 2:
            content = f"# bucket: {bucket}\n{lines[1]}"
        else:
            content = f"# bucket: {bucket}\n{content}"

    # Operation 2: Add bucket="..." kwarg (if not already present)
    if f'bucket="{bucket}"' not in content:
        # Find @register_tool( and its closing paren
        register_match = re.search(r"@register_tool\(", content)
        if register_match:
            open_paren_pos = register_match.end() - 1
            close_paren_pos = safe_find_closing_paren(content, open_paren_pos)

            if close_paren_pos > 0:
                # Insert bucket kwarg before closing paren
                insert_text = f',\n    bucket="{bucket}"'
                content = (
                    content[:close_paren_pos]
                    + insert_text
                    + content[close_paren_pos:]
                )

    # Operation 3: Add [CORE]/[DEFER] prefix to description
    # Case 1: _DESCRIPTION = ( ... )
    var_def_match = re.search(
        r"^_DESCRIPTION\s*=\s*\(\s*(['\"])(.+?)\1",
        content,
        re.MULTILINE | re.DOTALL,
    )

    if var_def_match:
        old_desc = var_def_match.group(2)
        if not old_desc.strip().startswith("[CORE]") and not old_desc.strip().startswith(
            "[DEFER]"
        ):
            new_desc = f"{prefix} {old_desc}"
            # Replace only the captured group 2 (the description text, not the quotes)
            start = var_def_match.start(2)
            end = var_def_match.end(2)
            content = content[:start] + new_desc + content[end:]
    else:
        # Case 2: description="..." in @register_tool
        # Match description= followed by opening quote, then non-greedily match until closing quote
        desc_match = re.search(
            r'description\s*=\s*(["\'])(.*?)\1',
            content,
            re.DOTALL,
        )

        if desc_match:
            old_desc = desc_match.group(2)
            if not old_desc.strip().startswith("[CORE]") and not old_desc.strip().startswith(
                "[DEFER]"
            ):
                new_desc = f"{prefix} {old_desc}"
                # Replace group 2 only (the content between quotes)
                start = desc_match.start(2)
                end = desc_match.end(2)
                content = content[:start] + new_desc + content[end:]

    # Write back
    file_path.write_text(content, encoding="utf-8")
    return True, f"{tool_name}: {bucket} OK"


def main():
    print("Tagging 59 tools with bucket classification (FINAL)...")
    print()

    success_count = 0
    failures = []

    for tool_file in sorted(TOOLS_DIR.glob("*.py")):
        if tool_file.name in ("_registry.py", "_meta_common.py", "__init__.py"):
            continue

        try:
            ok, msg = process_file(tool_file)
            print(msg)

            if ok:
                success_count += 1
            else:
                failures.append((tool_file.name, msg))
        except Exception as e:
            print(f"{tool_file.name}: ERROR — {e}")
            failures.append((tool_file.name, str(e)))

    print()
    print(f"Success: {success_count}/59")
    if failures:
        print(f"Failures: {len(failures)}")
        for name, msg in failures:
            print(f"  {name}: {msg}")
    else:
        print("All 59 files tagged successfully!")


if __name__ == "__main__":
    main()
