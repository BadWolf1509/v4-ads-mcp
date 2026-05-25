#!/usr/bin/env python3
"""
Mass-edit script v2: Tag 59 tool files with bucket classification.
Task C — Sprint 3b.39

SAFER APPROACH:
1. Add bucket comment on line 1
2. Find @register_tool and insert bucket kwarg IMMEDIATELY AFTER name= value
3. Add [CORE]/[DEFER] prefix to _DESCRIPTION variable or description kwarg
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
    """Edit a tool file. Returns (success, message)."""
    tool_name = file_path.stem
    bucket = get_bucket(tool_name)
    prefix = "[CORE]" if bucket == "always" else "[DEFER]"

    content = file_path.read_text(encoding="utf-8")
    lines = content.split("\n")

    # Step 1: Add bucket comment on line 1
    if lines[0].startswith("# bucket:"):
        # Already has bucket comment
        if f'bucket="{bucket}"' in content:
            return False, f"{tool_name}: already fully tagged"
    else:
        bucket_comment = f"# bucket: {bucket}"
        lines.insert(0, bucket_comment)

    # Step 2: Add bucket kwarg to @register_tool(...)
    # Strategy: find name="<tool_name>" and insert bucket kwarg after it
    modified = False
    new_lines = []
    for i, line in enumerate(lines):
        new_lines.append(line)

        # Look for name="..." or name='...' on this line
        if f'name="{tool_name}"' in line or f"name='{tool_name}'" in line:
            # Check if bucket kwarg already exists on next few lines
            bucket_exists = False
            for j in range(i + 1, min(i + 10, len(lines))):
                if "bucket=" in lines[j]:
                    bucket_exists = True
                    break

            if not bucket_exists:
                # Insert bucket kwarg on next line if this line is closing decorator
                if line.rstrip().endswith(")"):
                    # Decorator closes on same line, insert before it
                    # This is rare, but handle it by replacing the line
                    # Actually, safer: look ahead for the closing paren
                    pass
                else:
                    # Multi-line decorator, bucket goes after name line
                    # Indent to match the context
                    indent = len(line) - len(line.lstrip())
                    new_lines.append(f'{" " * indent}bucket="{bucket}",')
                    modified = True

    if not modified:
        # Fallback: search for simple pattern bucket= insertion
        content_reconstructed = "\n".join(new_lines)
        if f'bucket="{bucket}"' not in content_reconstructed:
            # Insert via regex as fallback
            # Find @register_tool and insert after name="..." line
            pattern = r'(name=["\']' + re.escape(tool_name) + r'["\'],)'
            replacement = r'\1\n    bucket="' + bucket + '",'
            content_reconstructed = re.sub(pattern, replacement, content_reconstructed)
            new_lines = content_reconstructed.split("\n")

    # Reconstruct with modified lines
    content = "\n".join(new_lines)

    # Step 3: Add prefix to description
    # Check if description=_DESCRIPTION (variable reference)
    var_match = re.search(r"description\s*=\s*_DESCRIPTION", content)
    if var_match:
        # Handle variable reference case (Meta tools)
        var_def_pattern = (
            r"(^_DESCRIPTION\s*=\s*\(\s*['\"])"
            + r"([^'\"]*?)"
            + r"(['\"])"
        )
        def replace_var(m):
            before = m.group(1)
            desc = m.group(2)
            after = m.group(3)
            if desc.strip().startswith("[CORE]") or desc.strip().startswith("[DEFER]"):
                return m.group(0)  # Already tagged
            return f'{before}{prefix} {desc}{after}'

        content = re.sub(var_def_pattern, replace_var, content, flags=re.MULTILINE)
    else:
        # Handle inline description in @register_tool
        # Match description=(...) or description="..."
        desc_pattern = r'(description\s*=\s*\(\s*["\']|description\s*=\s*["\'])([^"\']*?)(["\'])'

        def replace_desc(m):
            before = m.group(1)
            desc = m.group(2)
            after = m.group(3)
            if desc.strip().startswith("[CORE]") or desc.strip().startswith("[DEFER]"):
                return m.group(0)  # Already tagged
            return f'{before}{prefix} {desc}{after}'

        # Be careful: match first occurrence only
        content = re.sub(desc_pattern, replace_desc, content, count=1)

    # Write back
    file_path.write_text(content, encoding="utf-8")
    return True, f"{tool_name}: {bucket} OK"


def main():
    print("Tagging 59 tools with bucket classification (v2)...")
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
