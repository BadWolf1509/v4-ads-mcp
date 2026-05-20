# Sprint 3b.29 — `run_gaql.aggregate_by` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add optional `aggregate_by` parameter to `run_gaql` tool that performs client-side GROUP BY + COUNT, returning ordered groups instead of raw rows. Resolves B5 (token overflow em queries de alta cardinalidade).

**Architecture:** Pure aggregator module (`src/google_ads/aggregation.py`) consumed by updated `run_gaql.py`. Backward compatible — param opcional, ausente mantém shape original. Safety net hard 10k raw rows antes de aggregate.

**Tech Stack:** Python 3.12 stdlib only (sem pandas/numpy), pytest, ruff format, mypy strict. Aproveita `execute_gaql_raw` existente.

**Spec:** [`docs/superpowers/specs/2026-05-20-sprint-3b-29-run-gaql-aggregate-by-design.md`](../specs/2026-05-20-sprint-3b-29-run-gaql-aggregate-by-design.md)

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `src/google_ads/aggregation.py` | **CREATE** | Pure function `aggregate_rows(rows, group_by) -> list[dict]`. Sem imports do Google SDK — testável standalone. |
| `tests/unit/test_aggregation.py` | **CREATE** | 9 unit tests cobrindo empty/single/multi/nested/missing/sort/ties/edge cases. |
| `src/mcp/tools/run_gaql.py` | **MODIFY** | Adiciona `aggregate_by` no `_SCHEMA`, branch logic + safety net 10k raw rows. Mantém shape original quando ausente. |
| `tests/integration/test_utility_tools.py` | **MODIFY** | Adiciona 4 wire-up tests (regression shape, groups shape, truncation 1000 groups, safety 10k hard). |
| `docs/operacao/phase-3b-29-bootstrap.md` | **CREATE** | Smoke runbook 6 cases pra validação real em Nutry. |

---

## Task A1: Pure aggregation module + unit tests

**Files:**
- Create: `src/google_ads/aggregation.py`
- Create: `tests/unit/test_aggregation.py`

**Recommended model:** sonnet (módulo + 9 testes coordenados).

### A1 — Step 1: Write 3 initial failing tests (RED)

Create `tests/unit/test_aggregation.py`:

```python
"""Unit tests for src.google_ads.aggregation.aggregate_rows (Sprint 3b.29 B5).

Pure function tests — sem fixture Google SDK. COUNT only por design (V0).
"""

from src.google_ads.aggregation import aggregate_rows


def test_empty_rows_returns_empty_groups():
    assert aggregate_rows([], ["field_type"]) == []


def test_single_field_group_by():
    rows = [
        {"field_type": "SITELINK"},
        {"field_type": "STRUCTURED_SNIPPET"},
        {"field_type": "STRUCTURED_SNIPPET"},
        {"field_type": "SITELINK"},
        {"field_type": "STRUCTURED_SNIPPET"},
    ]
    result = aggregate_rows(rows, ["field_type"])
    # STRUCTURED_SNIPPET first (3 > SITELINK 2)
    assert result == [
        {"key": {"field_type": "STRUCTURED_SNIPPET"}, "count": 3},
        {"key": {"field_type": "SITELINK"}, "count": 2},
    ]


def test_multi_field_group_by():
    rows = [
        {"field_type": "SITELINK", "asset": {"type": "SITELINK"}},
        {"field_type": "STRUCTURED_SNIPPET", "asset": {"type": "STRUCTURED_SNIPPET"}},
        {"field_type": "STRUCTURED_SNIPPET", "asset": {"type": "STRUCTURED_SNIPPET"}},
    ]
    result = aggregate_rows(rows, ["field_type", "asset.type"])
    assert len(result) == 2
    top = result[0]
    assert top["count"] == 2
    assert top["key"]["field_type"] == "STRUCTURED_SNIPPET"
    assert top["key"]["asset.type"] == "STRUCTURED_SNIPPET"
```

### A1 — Step 2: Run tests to verify they fail (RED)

Run: `python -m pytest tests/unit/test_aggregation.py -v`

Expected: `ImportError: cannot import name 'aggregate_rows' from 'src.google_ads.aggregation'`

(Module doesn't exist yet.)

### A1 — Step 3: Create aggregation module (GREEN)

Create `src/google_ads/aggregation.py`:

```python
"""Pure client-side aggregation for GAQL result rows (V0: COUNT only).

GAQL nativo NAO suporta GROUP BY (verified em
src/google_ads/queries/bulk_pause.py:20 — está na blacklist _FORBIDDEN_KEYWORDS).
Aggregation precisa ser client-side post-fetch.

Used by src/mcp/tools/run_gaql.py when caller passa aggregate_by parameter.
"""

from typing import Any


def _resolve_dotted(row: dict[str, Any], path: str) -> Any:
    """Walk dotted field path in flat/nested dict from MessageToDict.

    MessageToDict with preserving_proto_field_name=True retorna nested dicts
    pra nested protos (e.g., {"campaign": {"id": "123"}}). Helper resolve
    "campaign.id" -> "123". Returns None se qualquer segmento missing.
    """
    current: Any = row
    for segment in path.split("."):
        if not isinstance(current, dict) or segment not in current:
            return None
        current = current[segment]
    return current


def aggregate_rows(
    rows: list[dict[str, Any]],
    group_by: list[str],
) -> list[dict[str, Any]]:
    """Agrupa rows por field paths (dotted), retorna [{key:{...}, count:N}] sorted desc.

    Pure function — nao importa Google SDK; testavel sem fixture pesado.

    Args:
        rows: flat dicts vindos de MessageToDict (preserving_proto_field_name=True).
        group_by: 1-5 field paths dotted. Ex: ['field_type', 'asset.type'].

    Returns:
        Lista de grupos sorted by count desc. Key e dict mapeando cada field path
        ao valor encontrado (None se field missing). Empates preservam insertion
        order (sorted() Python e stable).
    """
    if not rows:
        return []

    counts: dict[tuple[Any, ...], int] = {}
    for row in rows:
        key = tuple(_resolve_dotted(row, path) for path in group_by)
        counts[key] = counts.get(key, 0) + 1

    # sorted() Python is stable; ties preserve insertion order.
    sorted_groups = sorted(counts.items(), key=lambda kv: -kv[1])

    return [
        {
            "key": dict(zip(group_by, key_tuple, strict=True)),
            "count": count,
        }
        for key_tuple, count in sorted_groups
    ]
```

### A1 — Step 4: Run 3 tests to verify GREEN

Run: `python -m pytest tests/unit/test_aggregation.py -v`

Expected: 3 passed.

### A1 — Step 5: Add remaining 6 tests

Append to `tests/unit/test_aggregation.py`:

```python
def test_nested_field_path_dotted_lookup():
    rows = [
        {"campaign": {"id": "123"}},
        {"campaign": {"id": "456"}},
        {"campaign": {"id": "123"}},
    ]
    result = aggregate_rows(rows, ["campaign.id"])
    # campaign.id=123 has 2; 456 has 1
    assert result == [
        {"key": {"campaign.id": "123"}, "count": 2},
        {"key": {"campaign.id": "456"}, "count": 1},
    ]


def test_missing_field_yields_none_key():
    rows = [
        {"field_type": "SITELINK"},
        {"field_type": "SITELINK", "asset": {"type": "SITELINK"}},
        {"asset": {"type": "X"}},  # no field_type
    ]
    result = aggregate_rows(rows, ["field_type"])
    # 2 groups: SITELINK (2) + None (1)
    assert len(result) == 2
    assert result[0] == {"key": {"field_type": "SITELINK"}, "count": 2}
    assert result[1] == {"key": {"field_type": None}, "count": 1}


def test_sort_is_count_desc():
    rows = [{"x": "a"}] + [{"x": "b"}] * 5 + [{"x": "c"}] * 3
    result = aggregate_rows(rows, ["x"])
    counts_only = [g["count"] for g in result]
    assert counts_only == [5, 3, 1]


def test_ties_in_count_preserves_insertion_order():
    rows = [{"x": "a"}, {"x": "b"}, {"x": "a"}, {"x": "b"}]
    result = aggregate_rows(rows, ["x"])
    # both have count 2; "a" was inserted first
    assert result[0]["key"] == {"x": "a"}
    assert result[1]["key"] == {"x": "b"}


def test_single_row_returns_one_group_count_1():
    result = aggregate_rows([{"x": "a"}], ["x"])
    assert result == [{"key": {"x": "a"}, "count": 1}]


def test_group_by_field_not_in_any_row():
    rows = [{"a": 1}, {"a": 2}, {"a": 3}]
    result = aggregate_rows(rows, ["nonexistent"])
    assert result == [{"key": {"nonexistent": None}, "count": 3}]
```

### A1 — Step 6: Run all 9 tests

Run: `python -m pytest tests/unit/test_aggregation.py -v`

Expected: 9 passed.

### A1 — Step 7: Pre-commit gate

Run: `python scripts/check_pre_push.py`

Expected: `All pre-push checks passed (5 steps in ~40s)`.

### A1 — Step 8: Commit

```bash
git add src/google_ads/aggregation.py tests/unit/test_aggregation.py
git commit -m "$(cat <<'EOF'
feat(aggregation): pure aggregate_rows module (Sprint 3b.29 A1)

Adiciona helper puro src/google_ads/aggregation.py que agrupa flat dicts
de MessageToDict por field paths dotted, retornando [{key:{...}, count:N}]
ordenado por count desc.

V0 COUNT only (per spec section 4.2). Sem imports Google SDK — testavel
standalone. Suporta nested dotted paths (ex: 'campaign.id') + None pra
fields missing. Stable sort em empates.

9 unit tests cobrem: empty, single field, multi field, nested, missing
field, sort desc, ties, single row, field not in any row.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task A2: run_gaql.py schema + branch + safety net

**Files:**
- Modify: `src/mcp/tools/run_gaql.py` (full rewrite, 56 → ~95 LoC)

**Recommended model:** haiku (mecânico, código completo abaixo).

### A2 — Step 1: Replace run_gaql.py with updated version

**Out-of-scope nota:** spec section 5.3 menciona "audit_log captura aggregate_by em
params_summary". Investigação revelou que `run_gaql` atual NAO chama `audit_log.record()`
explicit (a description "Sempre auditado" e inconsistencia antiga). Esse sprint NAO
adiciona audit — fica como design choice pre-existente. Se for prioridade futura,
candidate Sprint 3b.X separado adiciona audit_log.record() pra todas as tools "Sempre
auditado" listadas (run_gaql + get_my_audit_log + get_my_rate_limit_status).

**Replace ENTIRE content** of `src/mcp/tools/run_gaql.py` with:

```python
"""Tool: run_gaql - escape hatch to execute arbitrary GAQL queries.

V0 (Sprint 3b.29): adiciona aggregate_by opcional pra client-side
GROUP BY + COUNT (resolve B5 token overflow em queries densas).
"""

from typing import Any

from src.google_ads.aggregation import aggregate_rows
from src.google_ads.reports import execute_gaql_raw
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "query": {
            "type": "string",
            "minLength": 10,
            "description": (
                "GAQL query string. Sempre auditado. Resultado truncado em 1000 "
                "linhas. Use list_gaql_resources pra ver o catalogo de campos."
            ),
        },
        "aggregate_by": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "maxItems": 5,
            "description": (
                "Opcional. Lista de field paths (dotted) pra agrupar rows e contar. "
                "Ex: ['field_type','asset.type']. Retorna groups[] ordenado por count "
                "DESC ao inves de rows[]. Limite hard: 10k raw rows antes de agregar."
            ),
        },
    },
    "required": ["customer_id", "query"],
    "additionalProperties": False,
}

_MAX_ROWS = 1000
_MAX_RAW_ROWS_FOR_AGGREGATE = 10_000


@register_tool(
    name="run_gaql",
    description=(
        "Escape hatch: executa qualquer GAQL contra a conta. Use apenas quando as "
        "tools curadas nao cobrem o caso. Sempre auditado. Limite: resultado "
        f"truncado em {_MAX_ROWS} linhas pra evitar respostas gigantes. Suporta "
        "aggregate_by (client-side GROUP BY+COUNT) pra queries com cardinalidade "
        "alta — retorna groups[] ordenado por count DESC."
    ),
    input_schema=_SCHEMA,
)
async def run_gaql(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    query = args["query"]
    aggregate_by = args.get("aggregate_by")

    rows = await execute_gaql_raw(
        manager_id=ctx.manager_id,
        customer_id=customer_id,
        query=query,
    )

    if aggregate_by:
        if len(rows) > _MAX_RAW_ROWS_FOR_AGGREGATE:
            raise ValueError(
                f"Query retornou {len(rows)} rows (>{_MAX_RAW_ROWS_FOR_AGGREGATE}). "
                "Refine WHERE clause antes de agregar (limite hard pra evitar OOM)."
            )
        groups = aggregate_rows(rows, aggregate_by)
        truncated = len(groups) > _MAX_ROWS
        return {
            "customer_id": customer_id,
            "total_rows_scanned": len(rows),
            "group_count": len(groups[:_MAX_ROWS]),
            "truncated": truncated,
            "groups": groups[:_MAX_ROWS],
        }

    truncated = len(rows) > _MAX_ROWS
    return {
        "customer_id": customer_id,
        "row_count": len(rows),
        "truncated": truncated,
        "rows": rows[:_MAX_ROWS],
    }
```

### A2 — Step 2: Run schema regression tests

Run: `python -m pytest tests/unit/test_tools_schemas.py -v`

Expected: all passing. Especificamente confirma:
- `test_every_tool_has_valid_schema` — `aggregate_by` é valid JSON Schema
- `test_no_composition_keywords_in_any_schema` — sem oneOf/allOf/anyOf
- `test_every_tool_input_schema_disallows_extra_properties` — `additionalProperties: false` mantido

### A2 — Step 3: Pre-commit gate

Run: `python scripts/check_pre_push.py`

Expected: 5/5 PASS. Tests integration `test_validate_gaql_returns_valid_when_no_error` + `test_validate_gaql_returns_invalid_with_error` + `test_run_gaql_returns_rows_and_truncation_flag` continuam green (backward compat).

### A2 — Step 4: Commit

```bash
git add src/mcp/tools/run_gaql.py
git commit -m "$(cat <<'EOF'
feat(run_gaql): aggregate_by opcional client-side (Sprint 3b.29 A2)

Adiciona param aggregate_by no _SCHEMA + branch logic em run_gaql:
- Ausente: shape original (rows[]) mantido — backward compat 100%
- Presente: agrega via aggregate_rows + retorna groups[] ordenado count DESC
- Safety net hard 10k raw rows antes de agregar (raise ValueError PT-BR)
- Metadata: total_rows_scanned + group_count + truncated

Schema validado por test_no_composition_keywords (sem oneOf/anyOf).
additionalProperties:false mantido.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task A3: Integration tests + pre-push gate

**Files:**
- Modify: `tests/integration/test_utility_tools.py` (append 4 tests after existing block)

**Recommended model:** sonnet (mock patterns + AsyncMock nuanced).

### A3 — Step 1: Append 4 integration tests

Open `tests/integration/test_utility_tools.py` and append AFTER `test_validate_gaql_appends_b3_hint_for_conversion_action_cost_micros` (which é o último teste atual):

```python
@pytest.mark.asyncio
async def test_run_gaql_without_aggregate_by_returns_rows_unchanged(bound_context):
    """Regression: shape original mantido quando aggregate_by ausente."""
    from src.mcp.tools.run_gaql import run_gaql

    fake_rows = [{"campaign": {"id": "123"}}, {"campaign": {"id": "456"}}]

    with patch(
        "src.mcp.tools.run_gaql.execute_gaql_raw",
        AsyncMock(return_value=fake_rows),
    ):
        result = await run_gaql(
            {
                "customer_id": "1234567890",
                "query": "SELECT campaign.id FROM campaign",
            }
        )

    assert result["row_count"] == 2
    assert result["truncated"] is False
    assert "rows" in result
    assert "groups" not in result


@pytest.mark.asyncio
async def test_run_gaql_with_aggregate_by_returns_groups_shape(bound_context):
    """aggregate_by ativo retorna groups[] + metadata, sem rows[]."""
    from src.mcp.tools.run_gaql import run_gaql

    fake_rows = [
        {"field_type": "SITELINK"},
        {"field_type": "STRUCTURED_SNIPPET"},
        {"field_type": "STRUCTURED_SNIPPET"},
        {"field_type": "SITELINK"},
        {"field_type": "STRUCTURED_SNIPPET"},
    ]

    with patch(
        "src.mcp.tools.run_gaql.execute_gaql_raw",
        AsyncMock(return_value=fake_rows),
    ):
        result = await run_gaql(
            {
                "customer_id": "1234567890",
                "query": "SELECT campaign_asset.field_type FROM campaign_asset",
                "aggregate_by": ["field_type"],
            }
        )

    assert "rows" not in result
    assert result["total_rows_scanned"] == 5
    assert result["group_count"] == 2
    assert result["truncated"] is False
    assert result["groups"] == [
        {"key": {"field_type": "STRUCTURED_SNIPPET"}, "count": 3},
        {"key": {"field_type": "SITELINK"}, "count": 2},
    ]


@pytest.mark.asyncio
async def test_run_gaql_aggregate_truncates_at_1000_groups(bound_context):
    """1500 grupos unicos -> truncado a 1000 com truncated:true."""
    from src.mcp.tools.run_gaql import run_gaql

    # Generate 1500 unique field values
    fake_rows = [{"x": f"val_{i}"} for i in range(1500)]

    with patch(
        "src.mcp.tools.run_gaql.execute_gaql_raw",
        AsyncMock(return_value=fake_rows),
    ):
        result = await run_gaql(
            {
                "customer_id": "1234567890",
                "query": "SELECT x FROM something",
                "aggregate_by": ["x"],
            }
        )

    assert result["total_rows_scanned"] == 1500
    assert len(result["groups"]) == 1000
    assert result["truncated"] is True


@pytest.mark.asyncio
async def test_run_gaql_rejects_more_than_10k_raw_rows(bound_context):
    """Safety net hard: >10k raw rows com aggregate_by raises ValueError."""
    from src.mcp.tools.run_gaql import run_gaql

    fake_rows = [{"x": "val"} for _ in range(10_001)]

    with patch(
        "src.mcp.tools.run_gaql.execute_gaql_raw",
        AsyncMock(return_value=fake_rows),
    ):
        with pytest.raises(ValueError, match=r"refine WHERE clause"):
            await run_gaql(
                {
                    "customer_id": "1234567890",
                    "query": "SELECT x FROM something",
                    "aggregate_by": ["x"],
                }
            )
```

### A3 — Step 2: Run 4 new tests

Run: `python -m pytest tests/integration/test_utility_tools.py -k "aggregate or 10k" -v`

Expected: 4 passed.

### A3 — Step 3: Run full pre-push gate

Run: `python scripts/check_pre_push.py`

Expected: 5/5 PASS in ~40s.

If Docker disponivel, opcional: `python scripts/check_pre_push_full.py` (6/6 including testcontainers).

### A3 — Step 4: Commit

```bash
git add tests/integration/test_utility_tools.py
git commit -m "$(cat <<'EOF'
test(run_gaql): 4 integration tests aggregate_by (Sprint 3b.29 A3)

Wire-up tests cobrem:
- Backward compat: aggregate_by ausente -> shape rows[] original
- Happy path: aggregate_by ativo -> groups[] ordered DESC + metadata
- Truncation: 1500 groups -> truncado a 1000 com truncated:true
- Safety net: >10k raw rows raises ValueError com refine hint PT-BR

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task A4: Smoke runbook + push + signoff

**Files:**
- Create: `docs/operacao/phase-3b-29-bootstrap.md`

**Recommended model:** sonnet (estrutura inspirada em runbooks recentes 3b.27/3b.28).

### A4 — Step 1: Generate smoke runbook esqueleto

**Option A (recommended):** dispatch `smoke-runbook-generator` subagent:

```
Prompt: "Generate smoke runbook esqueleto pra Sprint 3b.29 (run_gaql.aggregate_by).
Spec: docs/superpowers/specs/2026-05-20-sprint-3b-29-run-gaql-aggregate-by-design.md
Plan: docs/superpowers/plans/2026-05-20-sprint-3b-29-run-gaql-aggregate-by.md

6 smoke cases conforme spec section 7:
- T1: run_gaql sem aggregate_by -> rows[] shape original
- T2: aggregate_by:['campaign.status'] -> groups por status
- T3: campaign_asset + aggregate_by:['field_type','asset.type'] (reproduz B5)
- T4: aggregate_by:['nonexistent.field'] -> 1 grupo {key:{nonexistent:None}}
- T5: query 0 rows + aggregate_by -> {group_count:0, groups:[]}
- T6: query patológica >10k rows -> erro PT-BR claro

Conta sandbox: Nutry (customer_id 1163862076)."
```

**Option B (fallback manual):** Use template `docs/operacao/phase-3b-28-bootstrap.md` como modelo + adaptar conteúdo manualmente.

### A4 — Step 2: Verify runbook file existe

Run: `ls -la docs/operacao/phase-3b-29-bootstrap.md`

Expected: file exists.

### A4 — Step 3: Pre-push final

Run: `python scripts/check_pre_push.py`

Expected: 5/5 PASS.

### A4 — Step 4: Commit runbook

```bash
git add docs/operacao/phase-3b-29-bootstrap.md
git commit -m "$(cat <<'EOF'
docs(runbook): Sprint 3b.29 smoke runbook (T1-T6 aggregate_by)

6 smoke cases em Nutry sandbox (customer_id 1163862076):
- T1: shape original sem aggregate_by
- T2: aggregate por campaign.status
- T3: campaign_asset reproduce caso B5 dogfood
- T4: nonexistent field -> grupo None
- T5: 0 rows -> groups:[] empty
- T6: >10k raw rows -> erro safety net

Pendente: Wellington execucao manual.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### A4 — Step 5: Push para main

```bash
git push origin main
```

Expected output: `Bypassed rule violations for refs/heads/main` + commit hashes pushed.

### A4 — Step 6: Watch CI

```bash
gh run list --limit 3
```

Pick the latest workflow run id, then:

```bash
gh run watch <run_id>
```

Expected: CI + Deploy parallel both green em ~5-7min.

### A4 — Step 7: Verify production health

```bash
curl -s https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/health
```

Expected: `{"status":"ok"}` HTTP 200.

### A4 — Step 8: Wellington executes smoke runbook

**Manual step** — Wellington roda T1-T6 do runbook em Nutry sandbox via MCP client.

Esperado:
- T1-T5 PASS
- T6 PASS (erro PT-BR claro)
- Reportar qualquer divergência → ajuste sprint 3b.29.x se necessário

### A4 — Step 9: Signoff document

After smoke PASS, append nota a `docs/operacao/sprint-history.md` na entrada Sprint 3b.29:

```markdown
| 3b.29 | run_gaql.aggregate_by | ✅ 2026-05-20 | B5 fix dogfood MO-JP. Pure aggregation module + run_gaql branch. 13 testes (9 unit pure + 4 integration). Smoke 6/6 PASS em Nutry. Tool count: 51 unchanged. Backward compat: aggregate_by opcional. |
```

Update `CLAUDE.md` Sprint counter:

```diff
- | Sprint 3b.1 → 3b.28 (28 sprints) | ✅ 2026-05-04→20 | All shipped + signed-off em conta real.
+ | Sprint 3b.1 → 3b.29 (29 sprints) | ✅ 2026-05-04→20 | All shipped + signed-off em conta real.
```

```bash
git add docs/operacao/sprint-history.md CLAUDE.md
git commit -m "$(cat <<'EOF'
docs(signoff): Sprint 3b.29 shipped — run_gaql.aggregate_by

Sprint 3b.29 (B5 fix dogfood MO-JP) shipped + smoke 6/6 PASS em Nutry.

Detalhes:
- Pure aggregation module src/google_ads/aggregation.py (9 unit tests)
- run_gaql.aggregate_by opcional + safety net 10k raw rows
- 4 integration tests wire-up
- Tool count: 51 unchanged (extends existing)
- Backward compat 100%

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"

git push origin main
```

---

## Verification checklist (final)

Após todas as tasks:

- [ ] `src/google_ads/aggregation.py` existe, 9 unit tests passing
- [ ] `src/mcp/tools/run_gaql.py` aceita `aggregate_by` opcional, retorna shape correto em ambos modos
- [ ] 4 integration tests passing (regression + happy path + truncation + safety net)
- [ ] `docs/operacao/phase-3b-29-bootstrap.md` existe
- [ ] Smoke T1-T6 PASS em Nutry (Wellington manual)
- [ ] `python scripts/check_pre_push.py` 5/5 PASS local
- [ ] CI green em GitHub Actions
- [ ] Cloud Run deployment green
- [ ] `/health` retorna 200
- [ ] `docs/operacao/sprint-history.md` atualizado
- [ ] `CLAUDE.md` Sprint counter atualizado
