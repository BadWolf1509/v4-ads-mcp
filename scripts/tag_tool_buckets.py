#!/usr/bin/env python3
"""
Mass-edit script: Tag 59 tool files with bucket classification.
Task C — Sprint 3b.39

Adds:
1. # bucket: always|defer comment on line 1
2. bucket="always"|"defer" kwarg in @register_tool(...)
3. [CORE]|[DEFER] prefix in description string (or _DESCRIPTION variable for Meta tools)
"""

import re
from pathlib import Path

# Always-loaded tools (22)
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

# Defer-loading tools (37)
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


def process_file(file_path: Path) -> tuple[bool, str]:
    """
    Edit a tool file. Returns (success, message).
    """
    tool_name = file_path.stem
    bucket = get_bucket(tool_name)
    prefix = "[CORE]" if bucket == "always" else "[DEFER]"

    content = file_path.read_text(encoding="utf-8")

    # Step 1: Add bucket comment on line 1
    if content.startswith("# bucket:"):
        # Already has bucket comment, try to just add kwarg + description prefix
        # Check if bucket kwarg already exists
        if "bucket=" in content:
            return False, f"{tool_name}: already fully tagged (comment + kwarg + prefix)"
        # Fall through to add kwarg + prefix
    else:
        bucket_comment = f"# bucket: {bucket}\n"
        content = bucket_comment + content

    # Step 2: Add bucket kwarg to @register_tool(...)
    # Find @register_tool line and the matching closing paren
    register_match = re.search(r"@register_tool\(", content)
    if not register_match:
        return False, f"{tool_name}: could not find @register_tool("

    # Find matching closing paren (account for nesting)
    start = register_match.end() - 1  # position of '('
    paren_count = 1
    pos = start + 1
    while pos < len(content) and paren_count > 0:
        if content[pos] == "(":
            paren_count += 1
        elif content[pos] == ")":
            paren_count -= 1
        pos += 1

    if paren_count != 0:
        return False, f"{tool_name}: mismatched parens in @register_tool"

    closing_paren_pos = pos - 1
    register_block = content[start : closing_paren_pos]

    # Check if bucket kwarg already exists
    if "bucket=" in register_block:
        bucket_added = True
    else:
        bucket_added = False
        # Insert bucket kwarg before closing paren
        # Back up to find trailing content before )
        back = closing_paren_pos - 1
        while back > start and content[back] in (" ", "\t", "\n"):
            back -= 1

        # Insert after the last non-whitespace
        insertion_point = back + 1
        if insertion_point < len(content) and content[insertion_point] == "\n":
            new_content = content[:insertion_point] + f",\n    bucket=\"{bucket}\"" + content[insertion_point:]
        else:
            new_content = content[:insertion_point] + f",\n    bucket=\"{bucket}\"" + content[insertion_point:]

        content = new_content

    # Step 3: Add prefix to description string
    # Check if description=_DESCRIPTION (variable reference)
    var_match = re.search(r"description\s*=\s*_DESCRIPTION", content)
    if var_match:
        # Handle variable reference case (Meta tools)
        # Look for _DESCRIPTION = ( ... )
        var_def_match = re.search(r"^_DESCRIPTION\s*=\s*\(\s*['\"](.+?)['\"]", content, re.MULTILINE | re.DOTALL)
        if not var_def_match:
            # Multi-line parenthetical
            var_def_match = re.search(r"^_DESCRIPTION\s*=\s*\(\s*(['\"])(.+?)\1\s*\)", content, re.MULTILINE | re.DOTALL)

        if var_def_match:
            old_desc = var_def_match.group(1) if var_def_match.lastindex == 1 else var_def_match.group(2)
            if old_desc.strip().startswith("[CORE]") or old_desc.strip().startswith("[DEFER]"):
                return False, f"{tool_name}: _DESCRIPTION already has prefix"

            new_desc = f"{prefix} {old_desc}"
            old_text = var_def_match.group(0)
            new_text = old_text.replace(f'"{old_desc}"', f'"{new_desc}"', 1)
            if new_text == old_text:
                new_text = old_text.replace(f"'{old_desc}'", f"'{new_desc}'", 1)
            content = content.replace(old_text, new_text, 1)
        else:
            return False, f"{tool_name}: could not find _DESCRIPTION variable definition"
    else:
        # Handle inline description in @register_tool
        # Match description=( ... ) or description="..." or description='...'
        desc_pattern = r'description\s*=\s*\(\s*"(.*?)"(?:\s*\)|,)'
        desc_match = re.search(desc_pattern, content, re.DOTALL)

        if not desc_match:
            # Try single-line quoted version
            desc_pattern = r'description\s*=\s*(["\'])(.*?)\1'
            desc_match = re.search(desc_pattern, content)

        if not desc_match:
            return False, f"{tool_name}: could not find description=... in @register_tool"

        old_desc = desc_match.group(1) if desc_pattern.count("(") > 1 else desc_match.group(2)

        # Check if prefix already exists
        if old_desc.strip().startswith("[CORE]") or old_desc.strip().startswith("[DEFER]"):
            return False, f"{tool_name}: description already has prefix"

        new_desc = f"{prefix} {old_desc}"

        # Replace in content
        old_match_text = desc_match.group(0)
        new_match_text = old_match_text.replace(f'"{old_desc}"', f'"{new_desc}"')

        content = content.replace(old_match_text, new_match_text, 1)

    # Write back
    file_path.write_text(content, encoding="utf-8")
    return True, f"{tool_name}: {bucket} OK"


def main():
    print("Tagging 59 tools with bucket classification...")
    print()

    success_count = 0
    failures = []

    for tool_file in sorted(TOOLS_DIR.glob("*.py")):
        if tool_file.name in ("_registry.py", "_meta_common.py", "__init__.py"):
            continue

        ok, msg = process_file(tool_file)
        print(msg)

        if ok:
            success_count += 1
        else:
            failures.append((tool_file.name, msg))

    print()
    print(f"Success: {success_count}/59")
    if failures:
        print(f"Failures: {len(failures)}")
        for name, msg in failures:
            print(f"  {msg}")
    else:
        print("All 59 files tagged successfully!")


if __name__ == "__main__":
    main()
