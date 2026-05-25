#!/usr/bin/env python3
"""
Mass-edit script v3: Tag 59 tool files with bucket classification.
Task C — Sprint 3b.39

SIMPLEST APPROACH:
1. Add bucket comment on line 1
2. Find @register_tool( and add bucket="X" before the closing )
   by parsing backwards from closing ) safely
3. Add [CORE]/[DEFER] prefix to description
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


def process_file(file_path: Path) -> tuple[bool, str]:
    """Edit a tool file. Returns (success, message)."""
    tool_name = file_path.stem
    bucket = get_bucket(tool_name)
    prefix = "[CORE]" if bucket == "always" else "[DEFER]"

    content = file_path.read_text(encoding="utf-8")

    # Step 1: Add bucket comment on line 1
    if content.startswith("# bucket:"):
        # Already has bucket comment
        pass
    else:
        bucket_comment = f"# bucket: {bucket}\n"
        content = bucket_comment + content

    # Step 2: Check if already fully tagged
    if f'bucket="{bucket}"' in content:
        return False, f"{tool_name}: already fully tagged"

    # Step 3: Add bucket kwarg to @register_tool(...)
    # Use regex to find @register_tool and match the closing paren
    # This time: match the whole @register_tool(...) block
    register_pattern = r"(@register_tool\([^)]*name=['\"]" + re.escape(tool_name) + r"['\"][^)]*)"
    register_match = re.search(register_pattern, content, re.DOTALL)

    if not register_match:
        # Fallback: maybe name isn't on same line, just find @register_tool and add before closing )
        # Find all @register_tool calls and add bucket before the FIRST closing )
        register_calls = list(re.finditer(r"@register_tool\(", content))
        if not register_calls:
            return False, f"{tool_name}: could not find @register_tool("

        # For safety, only process if we find the tool name relatively close
        for match_start in register_calls:
            # Find the closing paren for this call
            start_pos = match_start.end() - 1
            paren_depth = 1
            pos = start_pos + 1

            while pos < len(content) and paren_depth > 0:
                # Skip strings to avoid counting parens inside strings
                if content[pos] in ('"', "'"):
                    quote = content[pos]
                    pos += 1
                    while pos < len(content) and content[pos] != quote:
                        if content[pos] == "\\":
                            pos += 2
                        else:
                            pos += 1
                    pos += 1
                else:
                    if content[pos] == "(":
                        paren_depth += 1
                    elif content[pos] == ")":
                        paren_depth -= 1
                    pos += 1

            if paren_depth == 0:
                # Found closing paren at pos-1
                closing_paren_pos = pos - 1
                decorator_block = content[start_pos : closing_paren_pos]

                # Check if this is the right decorator (contains the tool name)
                if tool_name in decorator_block:
                    # Insert bucket kwarg before closing paren
                    insert_pos = closing_paren_pos
                    before_close = content[insert_pos - 1]

                    if before_close == "\n":
                        insertion = f'    bucket="{bucket}"\n'
                    else:
                        insertion = f',\n    bucket="{bucket}"'

                    content = content[:insert_pos] + insertion + content[insert_pos:]
                    break

    # Step 4: Add prefix to description
    # Strategy 1: Check for _DESCRIPTION variable
    var_match = re.search(r"^_DESCRIPTION\s*=\s*\(\s*['\"]", content, re.MULTILINE)

    if var_match:
        # Extract the actual description text
        # Find the opening quote
        opening_quote_pos = content.find("(", var_match.start())
        opening_quote_pos = content.find(content[opening_quote_pos + 1], opening_quote_pos)
        opening_quote = content[opening_quote_pos]

        # Find closing quote
        closing_quote_pos = opening_quote_pos + 1
        while closing_quote_pos < len(content) and content[closing_quote_pos] != opening_quote:
            if content[closing_quote_pos] == "\\":
                closing_quote_pos += 2
            else:
                closing_quote_pos += 1

        # Get the description text
        desc_start = opening_quote_pos + 1
        old_desc = content[desc_start:closing_quote_pos]

        if not old_desc.strip().startswith("[CORE]") and not old_desc.strip().startswith("[DEFER]"):
            new_desc = f"{prefix} {old_desc}"
            content = (
                content[:desc_start]
                + new_desc
                + content[closing_quote_pos:]
            )
    else:
        # Strategy 2: Find description= in @register_tool
        desc_match = re.search(
            r'description\s*=\s*["\']([^"\']*?)["\']',
            content,
            re.DOTALL,
        )

        if desc_match:
            old_desc = desc_match.group(1)
            if not old_desc.strip().startswith("[CORE]") and not old_desc.strip().startswith(
                "[DEFER]"
            ):
                new_desc = f"{prefix} {old_desc}"
                content = content[: desc_match.start(1)] + new_desc + content[desc_match.end(1) :]

    # Write back
    file_path.write_text(content, encoding="utf-8")
    return True, f"{tool_name}: {bucket} OK"


def main():
    print("Tagging 59 tools with bucket classification (v3)...")
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
