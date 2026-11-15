# Sprint 3b.39 — Tool Bucket Classification + Wellington Config Procedure

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Classificar as 59 tools V4 Ads MCP em 3 buckets (always/defer/archive) via tags server-side + doc procedure pra Wellington configurar `defer_loading` no Claude Code client. Fase 1 do refactor arquitetural V4 Ads MCP.

**Architecture:**
1. **Server-side metadata-only:** OQ1 resolvido — `defer_loading` é client-side parameter da Anthropic Messages API, NÃO MCP server metadata. Logo, server adiciona tags discoveráveis (`# bucket:` Python comment + `[CORE]`/`[DEFER]` description prefix) sem mudar comportamento `list_tools()`.
2. **Client-side config (Wellington manual):** Wellington atualiza `~/.claude/settings.json` (ou config equivalente Claude Code) com `defer_loading: true` per-tool baseado nos tags V4. Runbook documenta procedure.
3. **Data-driven classification:** audit_log query (uses_30d) → 8 core + 10 warm = 18 always; 18 cold + 22 zombies + 3 exceções semânticas = 41 defer initially. Sem tombstone F1 (defer-only, archive vem F3).

**Tech Stack:** Python 3.12, MCP Python SDK 1.2.0+, asyncpg (audit_log query), pytest + ruff + mypy, V4 conventions (PT-BR errors, smoke runbook 3b.19A.1 per-value probe pattern).

**Spec source:** [`docs/superpowers/specs/2026-05-25-architecture-refactor-design.md`](../specs/2026-05-25-architecture-refactor-design.md) §5 (Fase 1)

**Decision gate F1 → F2 (outcome-based, timeout 14d):**
- ✅ Smoke 6/6 PASS + /health 200 + CI verde (auto)
- ✅ Wellington feedback 7d positivo (responsiveness ≥4/5, tools encontradas yes)
- 🚨 Abort triggers: >2 tools "não encontrei" OR smoke regression OR CI vermelho 2× consecutivos

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `docs/operacao/tool-buckets-2026-05-25.md` | CREATE | Tool classification doc (18 always + 41 defer com justificativa per-tool) |
| `src/mcp/tools/_registry.py` | MODIFY | Add optional `bucket` kwarg em `@register_tool` (default: "defer") pra grepability + introspection |
| `src/mcp/tools/<59 files>.py` | MODIFY | Add `# bucket: always|defer` Python comment line 1 + description prefix `[CORE]` or `[DEFER]` |
| `docs/operacao/phase-3b-39-bootstrap.md` | CREATE | Smoke runbook 6/6 testes T1-T6 + Wellington config procedure step-by-step |
| `docs/operacao/findings-catalog.md` | MODIFY | Add D2 finding (MCP defer_loading is client-side, not server-side — lesson) |
| `docs/operacao/sprint-history.md` | MODIFY | Add Sprint 3b.39 row |
| `CLAUDE.md` | MODIFY | §Pending refresh (F1 shipped, F2 next) |

---

## Task A — Audit_log query + bucket classification doc

**Files:**
- Create: `docs/operacao/tool-buckets-2026-05-25.md`

**Goal:** Doc data-driven com lista exata das 59 tools classificadas em 2 buckets (always/defer) + justificativa per-tool.

- [ ] **Step 1: Run audit_log query via Supabase MCP**

```sql
SELECT operation, COUNT(*) AS uses_30d
FROM audit_log
WHERE created_at > NOW() - INTERVAL '30 days'
  AND status NOT IN ('error', 'cancelled')
GROUP BY operation
ORDER BY uses_30d DESC;
```

Via `mcp__supabase__execute_sql` OR `python -c` + asyncpg. Save raw output em scratch.

Expected: ~59 rows (some tools 0 uses não aparecem — count manually a partir de file list em `src/mcp/tools/*.py`).

- [ ] **Step 2: List all 59 tools via glob + cross-reference**

Run: `ls src/mcp/tools/*.py | grep -v _registry | grep -v _meta_common | wc -l`
Expected: 59 (sanity check tool file count matches CLAUDE.md current state).

- [ ] **Step 3: Write classification doc**

Create `docs/operacao/tool-buckets-2026-05-25.md` with:

````markdown
# Tool Bucket Classification — 2026-05-25 (Sprint 3b.39)

**Source:** `audit_log` query `uses_30d` window 2026-04-25→2026-05-25 + semantic overrides.

**Total tools:** 59 (57 Google + 2 Meta)
**Always-loaded (~18):** uses ≥5/30d OR exceções semânticas
**Defer-loading (~41):** uses 1-4/30d + zombies (0 uses) + recém-shipped (exceto exceptions)

## Always-loaded bucket (18 tools)

### Core (≥10 uses/30d — 8 tools)

| Tool | Uses | Justificativa |
|---|---|---|
| `create_and_link_assets` | 33 | Top 1 Pareto |
| `get_change_history` | 29 | Top 2 |
| `create_campaign` | 22 | Top 3 |
| `add_negative_keywords` | 17 | Top 4 |
| `audit_competitor_keywords` | 16 | Top 5 |
| `create_conversion_action` | 16 | Top 6 |
| `list_my_accounts` | 14 | Top 7 — entry point |
| `update_keyword_status` | 10 | Top 8 |

### Warm (5-9 uses/30d — fill from query result, ~7 tools)

[FILL FROM AUDIT_LOG QUERY OUTPUT — paste tools with uses 5-9 here]

### Exceções semânticas (3 tools)

| Tool | Uses | Justificativa override |
|---|---|---|
| `detect_drift` | 1-4 | Recém-shipped Sprint 3b.33, 60d grace period (até 2026-07-21) |
| `meta_list_my_ad_accounts` | 1-4 | Cache esporádico esperado, entry point OAuth Meta discovery |
| `meta_get_account_overview` | 1-4 | Entry point Meta, must be discoverable pelo gestor |

## Defer-loading bucket (~41 tools)

### Cold (1-4 uses/30d — fill from query, ~15 tools)

[FILL]

### Zombies (0 uses/30d — 22 tools)

[FILL — list all tools NOT appearing in audit_log query result]

## Re-classification

Re-run query mensal. Tools moving up (≥5 uses) → promote to always. Tools moving down → demote to defer. Tools 0 uses 60d → candidato tombstone Fase 3.
````

- [ ] **Step 4: Verify doc**

Run: `wc -l docs/operacao/tool-buckets-2026-05-25.md`
Expected: ~80-120 lines.

- [ ] **Step 5: Commit**

```bash
git add docs/operacao/tool-buckets-2026-05-25.md
git commit -m "docs(buckets): tool classification 2026-05-25 — 18 always + 41 defer (data-driven audit_log)

Sprint 3b.39 Task A. Data-driven via audit_log uses_30d query.
- 8 core (≥10 uses Pareto top)
- 7-10 warm (5-9 uses)
- 3 exceções semânticas (detect_drift recém-shipped, meta entry points)
- 41 defer-loading (cold + zombies)

Re-classify mensal. Zombies 60d → tombstone candidato F3."
```

---

## Task B — Add `bucket` kwarg em `@register_tool` decorator

**Files:**
- Modify: `src/mcp/tools/_registry.py:26-42` (`@register_tool` decorator definition)

**Goal:** Adicionar optional `bucket: Literal["always", "defer"]` kwarg pro decorator (default "defer") pra introspection futura + grepability.

- [ ] **Step 1: Read current registry implementation**

Run: `cat src/mcp/tools/_registry.py | head -70`
Identify: `register_tool` function signature (estimated lines 26-42).

- [ ] **Step 2: Write failing test**

Create test em `tests/unit/test_registry_bucket.py`:

```python
"""Unit tests for @register_tool bucket parameter (Sprint 3b.39)."""

import pytest
from typing import Any

from src.mcp.tools._registry import (
    ToolEntry,
    register_tool,
    get_tool,
    _registry,
)


def test_register_tool_default_bucket_is_defer():
    """Default bucket = 'defer' (conservative — explicitly opt-in to always-loaded)."""

    @register_tool(name="test_default", description="test", input_schema={"type": "object", "additionalProperties": False})
    async def handler(args: dict) -> dict:
        return {}

    entry = get_tool("test_default")
    assert entry.bucket == "defer"
    # Cleanup
    _registry.pop("test_default", None)


def test_register_tool_bucket_always():
    """bucket='always' marks tool as always-loaded (core/warm)."""

    @register_tool(
        name="test_always",
        description="test",
        input_schema={"type": "object", "additionalProperties": False},
        bucket="always",
    )
    async def handler(args: dict) -> dict:
        return {}

    entry = get_tool("test_always")
    assert entry.bucket == "always"
    _registry.pop("test_always", None)


def test_register_tool_bucket_invalid_raises():
    """Only 'always' OR 'defer' accepted."""
    with pytest.raises(ValueError, match="bucket"):
        @register_tool(
            name="test_invalid",
            description="test",
            input_schema={"type": "object", "additionalProperties": False},
            bucket="other",  # type: ignore[arg-type]
        )
        async def handler(args: dict) -> dict:
            return {}
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_registry_bucket.py -v`
Expected: FAIL with "bucket parameter not recognized" OR "ToolEntry has no attribute 'bucket'".

- [ ] **Step 4: Implement bucket support in _registry.py**

Modify `src/mcp/tools/_registry.py`:

```python
# At top of file (imports)
from typing import Any, Awaitable, Callable, Literal

# In ToolEntry dataclass (add field):
@dataclass(frozen=True, slots=True)
class ToolEntry:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
    bucket: Literal["always", "defer"] = "defer"  # NEW Sprint 3b.39


# In register_tool function (add kwarg):
def register_tool(
    *,
    name: str,
    description: str,
    input_schema: dict[str, Any],
    bucket: Literal["always", "defer"] = "defer",  # NEW Sprint 3b.39
) -> Callable[[ToolHandler], ToolHandler]:
    """Decorator to register an MCP tool.

    Args:
        name: Tool name (snake_case).
        description: PT-BR or English description shown to Claude.
        input_schema: JSON Schema for input validation (no oneOf/allOf/anyOf — see CLAUDE.md).
        bucket: 'always' = always-loaded em context Claude. 'defer' = sob demanda (default,
            conservative). Sprint 3b.39 classification — re-evaluate monthly via audit_log
            query. See docs/operacao/tool-buckets-YYYY-MM-DD.md.
    """
    if bucket not in ("always", "defer"):
        raise ValueError(f"bucket must be 'always' or 'defer', got {bucket!r}")

    def decorator(handler: ToolHandler) -> ToolHandler:
        if name in _registry:
            raise RuntimeError(f"Tool {name!r} already registered")
        _registry[name] = ToolEntry(
            name=name,
            description=description,
            input_schema=input_schema,
            handler=handler,
            bucket=bucket,
        )
        return handler

    return decorator
```

- [ ] **Step 5: Run test to verify pass**

Run: `python -m pytest tests/unit/test_registry_bucket.py -v`
Expected: PASS (3/3).

- [ ] **Step 6: Run full unit suite to check no regressions**

Run: `python -m pytest tests/unit/ -v --tb=short 2>&1 | tail -15`
Expected: All previous tests still pass + 3 new ones.

- [ ] **Step 7: Commit**

```bash
git add src/mcp/tools/_registry.py tests/unit/test_registry_bucket.py
git commit -m "feat(registry): add bucket kwarg em @register_tool (always|defer)

Sprint 3b.39 Task B. Default 'defer' (conservative).
Tools opt-in to 'always' explicitly. Used pra grepability +
introspection (list_archived endpoint future + Wellington
Claude Code config generation).

Decoupled de defer_loading client-side parameter — server-side
metadata-only. See spec §5 + D2 finding pra context."
```

---

## Task C — Mass-edit 59 tool files: add `# bucket:` comment + description prefix

**Files:**
- Modify: `src/mcp/tools/*.py` (59 files)

**Goal:** Cada tool file recebe (1) `# bucket: always|defer` comment línea 1, (2) `bucket="always"|"defer"` em `@register_tool`, (3) prefix `[CORE]` or `[DEFER]` em description.

- [ ] **Step 1: Generate edit list from bucket doc**

From `docs/operacao/tool-buckets-2026-05-25.md` (Task A output), extract:
- 18 always-loaded tool names
- 41 defer-loading tool names

Save as 2 lists in scratch.

- [ ] **Step 2: For each always-loaded tool, apply 3 changes**

Pattern (example for `create_campaign.py`):

```python
# bucket: always   # ← NEW line 1 (above existing docstring)
"""Tool: create_campaign — ..."""

# ... existing imports ...

@register_tool(
    name="create_campaign",
    description="[CORE] Criar campaign Google Ads com ...",  # ← prefix [CORE]
    input_schema=_SCHEMA,
    bucket="always",  # ← NEW kwarg
)
async def create_campaign(args: dict[str, Any]) -> dict[str, Any]:
    ...
```

Use Edit tool for each file with old_string = entire `@register_tool(...)` block + new_string = same block + bucket="always" + description prefix `[CORE] `.

- [ ] **Step 3: For each defer-loading tool, apply 3 changes**

Pattern (example for `apply_recommendation.py`):

```python
# bucket: defer   # ← NEW line 1
"""Tool: apply_recommendation — ..."""

@register_tool(
    name="apply_recommendation",
    description="[DEFER] Aplica uma recomendação ...",  # ← prefix [DEFER]
    input_schema=_SCHEMA,
    bucket="defer",  # ← NEW kwarg (optional pra defer, mas explicit pra grepability)
)
async def apply_recommendation(args: dict[str, Any]) -> dict[str, Any]:
    ...
```

- [ ] **Step 4: Sanity check via grep**

```bash
# Should show 18 always + 41 defer + 0 unclassified
grep -c "^# bucket: always" src/mcp/tools/*.py | grep -v ":0" | wc -l
# Expected: 18

grep -c "^# bucket: defer" src/mcp/tools/*.py | grep -v ":0" | wc -l
# Expected: 41

# Total tools with bucket tag (should equal 59)
grep -l "^# bucket:" src/mcp/tools/*.py | wc -l
# Expected: 59
```

- [ ] **Step 5: Verify description prefix consistency**

```bash
# CORE prefix count should equal always count (18)
grep -c 'description="\[CORE\]' src/mcp/tools/*.py | grep -v ":0" | wc -l
# Expected: 18

# DEFER prefix count should equal defer count (41)
grep -c 'description="\[DEFER\]' src/mcp/tools/*.py | grep -v ":0" | wc -l
# Expected: 41
```

- [ ] **Step 6: Run unit suite — no regressions**

Run: `python -m pytest tests/unit/ -v --tb=short 2>&1 | tail -10`
Expected: All pass (descriptions changed but functionality intact).

- [ ] **Step 7: Verify integration tests still work**

Run: `python -m pytest tests/integration/test_audit_zombie_keywords.py -v`
Expected: 4/4 PASS (regression check).

- [ ] **Step 8: Commit**

```bash
git add src/mcp/tools/*.py
git commit -m "feat(tools): tag 59 tools com bucket classification (always|defer)

Sprint 3b.39 Task C. Mass-edit per docs/operacao/tool-buckets-2026-05-25.md:
- 18 tools always-loaded (8 core ≥10 uses + 7-10 warm 5-9 uses + 3 exceções
  semânticas: detect_drift recém-shipped, meta_list_my_ad_accounts cache,
  meta_get_account_overview entry point)
- 41 tools defer-loading (cold 1-4 uses + zombies 0 uses)

Changes per tool file:
- '# bucket: always|defer' comment line 1 (grepability)
- bucket='always'|'defer' kwarg em @register_tool
- '[CORE]' or '[DEFER]' prefix em description (Wellington Claude Code config hint)

Server-side metadata-only. Cliente (Wellington) configura defer_loading no
Claude Code ~/.claude/settings.json baseado em prefix tag. Doc procedure
em runbook 3b.39."
```

---

## Task D — MCP SDK metadata support research + extension (optional)

**Files:**
- Research only: investigate `mcp>=1.2.0` Python SDK suporta arbitrary metadata field em tool
- Conditional modify: `src/mcp/server.py` if SDK supports `_meta` field em ListToolsResult

**Goal:** Se MCP SDK suporta, expor `bucket` como structured metadata (não só prefix description). Caso contrário, prefix tag suffice.

- [ ] **Step 1: Read MCP Python SDK Tool type definition**

Run: `python -c "from mcp.types import Tool; import inspect; print(inspect.getsource(Tool))"`
Expected: see Tool pydantic model fields.

- [ ] **Step 2: Check if Tool has `_meta` or `metadata` field**

If Tool model has `_meta: dict | None` (MCP standard):
- Proceed to Step 3 (implement)

If not:
- Skip to Task E (prefix tag suffice)
- Document in commit message: "MCP SDK 1.2.0 Tool type sem metadata field — prefix tag em description usado em vez disso. Future: re-check em MCP SDK ≥1.5."

- [ ] **Step 3 (conditional): Modify list_tools to expose bucket as metadata**

In `src/mcp/server.py` `list_tools` handler:

```python
@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name=entry.name,
            description=entry.description,
            inputSchema=entry.input_schema,
            _meta={"v4_bucket": entry.bucket},  # NEW Sprint 3b.39 if SDK supports
        )
        for entry in _registry.values()
    ]
```

- [ ] **Step 4: Verify via MCP inspector or curl**

If implemented, smoke test via MCP inspector tool OR raw HTTP request to MCP server, confirm `_meta.v4_bucket` field in response.

- [ ] **Step 5: Commit**

```bash
git add src/mcp/server.py
git commit -m "feat(mcp): expose bucket as _meta.v4_bucket em list_tools (if SDK supports)

Sprint 3b.39 Task D. Server expose bucket classification como structured
metadata pra clients that respect _meta field. Backward-compat: clients
sem _meta support seguem usando prefix [CORE]/[DEFER] em description.

NB: MCP Python SDK 1.2.0 metadata support verified — see commit context."
```

If Task D not applicable (SDK sem metadata): skip commit, document in Task E runbook.

---

## Task E — Smoke runbook + Wellington Claude Code config procedure

**Files:**
- Create: `docs/operacao/phase-3b-39-bootstrap.md`

**Goal:** Runbook 6/6 smoke tests + step-by-step Wellington manual config procedure pra `~/.claude/settings.json`.

- [ ] **Step 1: Generate runbook skeleton via smoke-runbook-generator subagent**

Run subagent `smoke-runbook-generator` with sprint context:
- Sprint number: 3b.39
- Goal: Tool bucket classification + Wellington Claude Code config
- 6 tests T1-T6
- Wellington manual config section

OR manual create following 3b.38 pattern.

- [ ] **Step 2: Write runbook content**

Create `docs/operacao/phase-3b-39-bootstrap.md`:

````markdown
# Sprint 3b.39 Smoke Runbook — Tool Bucket Classification

**Goal:** Validar server-side bucket tags + Wellington manual Claude Code config + Tool Search defer_loading funcional.

**Pre-requisites:**
- Deploy verde, /health 200
- CI green
- Wellington tem Claude Code instalado + Anthropic API key configured
- audit_log query baseline already taken (Task A output)

## T1 — Baseline measurement (server-side)

**Pre-flight:**
```bash
# Tool count total (sanity)
ls src/mcp/tools/*.py | grep -v _registry | grep -v _meta_common | wc -l
# Expected: 59

# Bucket distribution
grep -c "^# bucket: always" src/mcp/tools/*.py | grep -v ":0" | wc -l
# Expected: 18

grep -c "^# bucket: defer" src/mcp/tools/*.py | grep -v ":0" | wc -l
# Expected: 41

# Description prefix count
grep -c 'description="\[CORE\]' src/mcp/tools/*.py | grep -v ":0" | wc -l
# Expected: 18

grep -c 'description="\[DEFER\]' src/mcp/tools/*.py | grep -v ":0" | wc -l
# Expected: 41
```

✅ PASS criterion: 18 + 41 = 59, todas counts match.

## T2 — Server registry introspection

Via Python REPL OR script:

```python
from src.mcp.tools._registry import _registry, import_all_tools

import_all_tools()
always = [e for e in _registry.values() if e.bucket == "always"]
defer = [e for e in _registry.values() if e.bucket == "defer"]

print(f"Always: {len(always)} tools")
print(f"Defer: {len(defer)} tools")
print(f"Total: {len(_registry)}")
print()
print("Always-loaded:")
for e in sorted(always, key=lambda x: x.name):
    print(f"  {e.name}: {e.description[:60]}...")
```

Expected output:
```
Always: 18 tools
Defer: 41 tools
Total: 59
Always-loaded:
  audit_competitor_keywords: [CORE] Tier 1 Pareto audit ...
  create_and_link_assets: [CORE] Top 1 Pareto mutate ...
  create_campaign: [CORE] Pareto top 3 ...
  ...
```

✅ PASS criterion: counts correct + all always tools have [CORE] prefix.

## T3 — Wellington Claude Code config procedure

**Step 3.1 — Locate Claude Code settings file**

On Windows:
```powershell
$env:APPDATA + "\Claude\settings.json"
# OR
Get-ChildItem -Path $env:USERPROFILE\.claude -Recurse | Select FullName
```

On Mac/Linux:
```bash
~/.claude/settings.json
```

**Step 3.2 — Add advanced-tool-use beta header (if applicable)**

Edit settings.json adding:

```json
{
  "mcp": {
    "servers": {
      "v4-ads": {
        "type": "streamable-http",
        "url": "https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/mcp",
        "headers": {
          "anthropic-beta": "advanced-tool-use-2025-11-20"
        }
      }
    }
  }
}
```

**Step 3.3 — Configure defer_loading per tool**

This is the manual config step. Generate config block from bucket classification:

```bash
# Generate config block from tool descriptions
grep "description=" src/mcp/tools/*.py | grep "\[DEFER\]" | \
    sed 's/.*name="\([^"]*\)".*/\1/' | sort > /tmp/defer_tools.txt
wc -l /tmp/defer_tools.txt
# Expected: 41 lines
```

Add to Claude settings.json (snippet shown for 3 tools, repeat for all 41):

```json
{
  "mcp": {
    "servers": {
      "v4-ads": {
        ...
      }
    },
    "tool_loading": {
      "defer": [
        "v4-ads.apply_recommendation",
        "v4-ads.dismiss_recommendation",
        "v4-ads.audit_zombie_keywords",
        ...
      ]
    }
  }
}
```

**NB:** Exact JSON schema for Claude Code `tool_loading` config TBD pendendo Claude Code release notes — see OQ resolution in commit.

**Step 3.4 — Restart Claude Code**

Quit fully + restart. Open MCP inspector to verify defer tools registered but marked deferred.

✅ PASS criterion: Wellington completes 3.1-3.4 sem erro.

## T4 — Regression: always-loaded tools work identical

In Claude Code session, invoke a core tool:

> "Lista as minhas contas"

Expected: `list_my_accounts` invoked + returns 25 contas (V4 MCC).

✅ PASS criterion: always-loaded tool funciona idêntico pre-refactor (no behavior change).

## T5 — Defer tool invocação por nome funciona

In Claude Code session, explicitly name a defer tool:

> "Use `audit_zombie_keywords` na conta 7862230676 com LAST_30_DAYS"

Expected: tool invoked + returns 280 zombies (match dogfood 25/05).

✅ PASS criterion: defer tool ainda callable quando explicitly named (defer != disabled).

## T6 — Wellington feedback collection (7d post-deploy)

7 dias após ship, Wellington responde GitHub issue (criar com title "Sprint 3b.39 Wellington 7d feedback"):

```markdown
### Wellington 7-day feedback Sprint 3b.39

1. **Responsiveness Claude:** 1/2/3/4/5 (1=much slower, 5=much faster)
2. **Tool discovery:** sentiu falta de alguma tool nas 7 dias? Quais?
3. **Defer tools encontradas:** invocou alguma defer tool? Foi fácil?
4. **Funcionalidade perdida:** algo que sentiu falta totalmente?
5. **Continue F2 OR pause/revert?** Decision.
```

✅ PASS criterion: Wellington responde com responsiveness ≥4/5 + tools ok + decision "continue F2".
🚨 ABORT criterion: >2 tools "não consegui encontrar" OR Wellington reports degradação UX significativa.

## Decision gate F1 → F2

Aplicar 14 dias post-deploy:

**Auto:**
- Smoke 6/6 PASS este runbook
- /health 200 last 7d
- CI green last 7d

**Wellington feedback (Step T6):**
- Responsiveness ≥4/5
- Zero "tool desaparecida" reports
- Decision "continue"

**Se ALL ✅:** proceed to Fase 2 (Sprint 3b.40 — Caminho C consolidação)
**Se ANY 🚨:** revert via mass-set `bucket="always"` em todos tools + 1 commit + Wellington re-evaluate
````

- [ ] **Step 3: Verify runbook**

Run: `wc -l docs/operacao/phase-3b-39-bootstrap.md`
Expected: ~150-250 linhas.

- [ ] **Step 4: Commit**

```bash
git add docs/operacao/phase-3b-39-bootstrap.md
git commit -m "docs(smoke): Sprint 3b.39 runbook — 6 tests T1-T6 + Wellington config procedure

Tests:
- T1: baseline server-side (counts + prefix)
- T2: registry introspection
- T3: Wellington manual config Claude Code settings.json
- T4: regression always-loaded tools
- T5: defer tool by-name invocation
- T6: Wellington 7d feedback collection

Decision gate F1 → F2 criteria documented inline (auto + Wellington
feedback)."
```

---

## Task F — Findings catalog + sprint-history + CLAUDE.md + pre-push + push

**Files:**
- Modify: `docs/operacao/findings-catalog.md` (add D2)
- Modify: `docs/operacao/sprint-history.md` (add Sprint 3b.39 row)
- Modify: `CLAUDE.md` (§Pending refresh + tool count update)

**Goal:** Documentation sync + ship.

- [ ] **Step 1: Add D2 finding to findings-catalog.md**

In `## Bug class 7: Strategic decisions (ecosystem constraint, not-a-bug, decision documented)` section, add:

```markdown
| **D2** | INFO | OQ1 research Sprint 3b.39 | Caminho server-metadata + client-config | **MCP defer_loading é parâmetro CLIENT-SIDE da Anthropic Messages API, NÃO server metadata.** Research OQ1 do refactor arquitetural confirmou via [Anthropic advanced-tool-use docs](https://www.anthropic.com/engineering/advanced-tool-use): `defer_loading: true` é configurado em `client.beta.messages.create(tools=[...])` com beta header `advanced-tool-use-2025-11-20`. Tool Search Tool é Anthropic-provided special tool, NÃO pattern MCP server. **Implicação V4 Ads MCP:** server-side mudou de "modificar list_tools()" pra "expor bucket metadata via description prefix `[CORE]`/`[DEFER]` + opcional `_meta.v4_bucket`". Wellington manual configura `~/.claude/settings.json` com defer per-tool baseado em prefix. **Lição reinforced:** sempre research API features cross-layer (client vs server) ANTES de design — Fase 1 inicial spec assumiu server-side incorrectly, descoberto via writing-plans skill research pré-implementation (~30 min saved days de wasted work). [phase-3b-39-bootstrap.md + spec refactor §5 + commits 3b.39] |
```

- [ ] **Step 2: Update findings-catalog.md status table + total count**

```markdown
| **Strategic decision** (ecosystem constraint, not code) | 2 (D1 Meta App Review + D2 MCP defer_loading client-side) |
```

```markdown
**Total findings tracked:** 51 (was 50 + D2 — MCP defer_loading client-side discovery).
```

- [ ] **Step 3: Update sprint-history.md**

Add new row pra Sprint 3b.39 (after 3b.38 row):

```markdown
| Sprint 3b.39 — Tool bucket classification + Wellington Claude Code config | ✅ 2026-MM-DD (code + smoke 6/6 + Wellington config doc + D2 finding) | N commits ([hash..hash]). **Tool count stays at 59** (metadata-only, no archive em F1). Sprint 3b.39 é Fase 1 do refactor arquitetural V4 Ads MCP (spec: `2026-05-25-architecture-refactor-design.md`). **Discovery crítica OQ1 (D2 finding):** MCP `defer_loading` é CLIENT-SIDE parameter Anthropic API, NÃO server metadata. F1 reformulada pra server-metadata-only + Wellington manual config. **Server-side changes (mecânicas):** `@register_tool` decorator add `bucket: Literal["always", "defer"]` kwarg (default "defer", conservative). Mass-edit 59 tool files: `# bucket: always|defer` comment line 1 (grepability) + `bucket="..."` kwarg + description prefix `[CORE]`/`[DEFER]`. 18 always (8 core ≥10 uses + 7-10 warm 5-9 uses + 3 exceções semânticas) + 41 defer (15 cold + 22 zombies + 4 misc) = 59. **Client-side (Wellington manual procedure documented):** runbook `phase-3b-39-bootstrap.md` step-by-step `~/.claude/settings.json` config com `tool_loading.defer[]` list + `anthropic-beta: advanced-tool-use-2025-11-20` header. **Bucket classification doc:** `docs/operacao/tool-buckets-2026-05-25.md` lista per-tool com justificativa, re-classify mensal via audit_log query. **Pre-push 5/5 PASS + CI verde + /health 200.** **Decision gate F1 → F2 (outcome-based timeout 14d):** smoke 6/6 PASS (auto) + Wellington feedback 7d positivo (responsiveness ≥4/5, tools encontradas yes, decision continue). Abort triggers: >2 tools "não encontrei" OR smoke regression. Revert path: mass-set `bucket="always"` (1-line PR). **Próximo F2:** Sprint 3b.40 Caminho C consolidação 9 reports → 1 `get_performance_breakdown`. |
```

- [ ] **Step 4: Update CLAUDE.md §Pending**

Modify CLAUDE.md `### Pending / future`:

```markdown
- **Refactor arquitetural Sprint 3b.39 ✅ shipped** (Fase 1 — tool bucket classification + Wellington config doc). Discovery D2: MCP defer_loading client-side, F1 reformulada server-metadata-only. **Próximo F2 Sprint 3b.40:** Caminho C consolidação `get_performance_breakdown(level, dimension)` substitui 9 reports = -9 tools permanente. Spec: [`2026-05-25-architecture-refactor-design.md`](../specs/2026-05-25-architecture-refactor-design.md). Gate F1→F2: outcome-based timeout 14d.
```

Update tool count line:

```markdown
**/health 200, CI green.** **16 web pages** em prod. **Q8 invite-only allowlist** ativo. **51 findings catalogados** (F1-F52 + A1-A6 + D1-D2, alguns IDs skipped): [...]
```

- [ ] **Step 5: Pre-push gate**

```bash
python scripts/check_pre_push.py
```

Expected: All checks passed (5 steps).

- [ ] **Step 6: Commit + push**

```bash
git add docs/operacao/findings-catalog.md docs/operacao/sprint-history.md CLAUDE.md
git commit -m "docs(arch): Sprint 3b.39 shipped — F1 tool bucket classification + D2 finding

Sprint 3b.39 (Fase 1 do refactor arquitetural V4 Ads MCP) completo:
- 59 tools classificadas em 18 always + 41 defer
- @register_tool decorator extended com bucket kwarg
- Mass-edit 59 tool files (tag + description prefix)
- Runbook phase-3b-39-bootstrap.md com 6 tests + Wellington config procedure
- D1+D2 strategic decisions catalogadas (Meta App Review + MCP defer_loading client-side)

Discovery crítica (D2): MCP defer_loading é client-side Anthropic API
parameter, NÃO server metadata. F1 pivoted pra server-metadata-only
+ Wellington manual config Claude Code settings.json.

Server side complete. Wellington manual config + 7d feedback pending.
Decision gate F1 → F2 outcome-based timeout 14d.

Próximo: Sprint 3b.40 Caminho C consolidação (Fase 2 refactor).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"

git push origin main
```

- [ ] **Step 7: Watch CI + verify /health**

```bash
gh run watch <run-id> --exit-status
curl -s https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/health
```

Expected: CI ✓ + /health 200.

- [ ] **Step 8: Mark sprint signoff**

Update sprint-history row with actual commit SHA range + actual smoke result + final timestamp.

---

## Self-Review Checklist (post-plan-write)

✅ **Spec coverage:**
- §5.1 objective (85% token reduction sem cortar tools) — Task C tags enable client config that achieves this
- §5.2 duration (~3-5 dias) — 6 tasks A-F totaling ~5-8h dev
- §5.3 scope original 5 deliverables — all covered (registry kwarg, tag classification, runbook, findings catalog, smoke 6/6)
- §5.4 deliverables (5 items) — all covered Task E + F
- §5.5 gate (smoke + Wellington feedback) — Task E runbook documents both

✅ **Placeholder scan:**
- Task A Step 3 has `[FILL FROM AUDIT_LOG QUERY OUTPUT]` placeholders — INTENTIONAL (data-driven content engineer fills in at runtime)
- Task D conditional ("if SDK supports") — INTENTIONAL (research-dependent)
- Task E Step 3.3 `tool_loading` JSON schema noted as TBD pending Claude Code release notes — DOCUMENTED as known constraint
- No "TODO" / "TBD" / "fill in later" without justification

✅ **Type consistency:**
- `ToolEntry.bucket: Literal["always", "defer"]` consistent across Task B test + impl + Task C usage
- `register_tool` kwarg same naming consistent
- `# bucket:` comment format consistent (no `# Bucket:` mixed case)

✅ **Gap fixes:**
- Original prompt mentioned `tools/list_archived` endpoint — REMOVED (não aplicável pós-OQ1, archived = tombstones = F3 not F1)
- Original prompt mentioned `src/mcp/_tool_search_adapter.py` — REMOVED (não aplicável pós-OQ1)
- Original prompt mentioned `src/mcp/server.py list_tools()` modification — REMOVED (não aplicável pós-OQ1)

**Tasks: 6 (A-F). Estimated effort: ~5-8h Wellington single-handed OR ~3-5h via subagent-driven.**

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-25-sprint-3b-39-tool-bucket-classification.md`.

Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task A-F (haiku pra mecânicos A/B/C/F, sonnet pra D/E research+ambiguous), 2-stage review (spec + quality) per task. Fast iteration.

2. **Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints for Wellington review between Task C and Task D (mid-point).

Which approach?
