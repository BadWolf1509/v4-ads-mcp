# Sprint 3b.32 — Quality Wins HIGH Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fechar 3 quick wins identificados no dogfood 2026-05-21 (MO-JP+CAB D+9): G1 (ICE 720), B1 (ICE 700), UX2 (ICE 600) — total ICE 2020. Ataca gaps internos do sprint 3b.27 (`update_conversion_action`) + descrição imprecisa do `get_change_history` reforçada pelo B4 quality win anterior.

**Architecture:** Três edits cirúrgicos em tools existentes — sem novas tools, sem novos módulos. T1 adiciona 2 fields no SELECT GAQL + row_formatter (READ-only, F44-safe). T2 e T3 são edits de description string (zero comportamento). T4 fecha com pre-push gate + push + docs sync.

**Tech Stack:** Python 3.12, Google Ads v24, pytest com AsyncMock+patch, ruff+mypy strict, asyncpg para audit_log persistence.

**Reference:** [`docs/operacao/dogfood-2026-05-21-mestre-da-obra-jp-drift-detection.md`](../../operacao/dogfood-2026-05-21-mestre-da-obra-jp-drift-detection.md) seção "Gaps", "Bugs", "UX issues".

---

## File Structure

**Modify:**
- `src/google_ads/queries/tactical.py` — adicionar 2 fields no `conversion_actions_query()` SELECT (T1)
- `src/mcp/tools/get_conversion_actions.py` — `_row_formatter` retorna 2 chaves novas (T1)
- `tests/integration/test_tactical_tools.py` — fixture + assertions estendidas (T1)
- `src/mcp/tools/get_change_history.py` — module docstring + tool description (T2)
- `src/mcp/tools/update_conversion_action.py` — tool description com exemplo dry-run+confirm (T3)
- `docs/operacao/sprint-history.md` — append entry Sprint 3b.32 (T4)
- `CLAUDE.md` — bump pending/future section (T4)

**No new files. No schema changes (input). No new tests beyond fixture extension.**

---

## Task 1 — G1: Enrich `get_conversion_actions` (+2 fields)

**Files:**
- Modify: `src/google_ads/queries/tactical.py:105-118`
- Modify: `src/mcp/tools/get_conversion_actions.py:21-37`
- Modify: `tests/integration/test_tactical_tools.py:191-211`

**F44 safety note:** `include_in_conversions_metric` é IMMUTABLE em `ConversionAction.update` v24 (Sprint 3b.27.1 lesson). Mas é READABLE — esta task só faz SELECT no listing. Zero conflito com F44.

- [ ] **Step 1: Estender `conversion_actions_query()` GAQL SELECT**

Modificar `src/google_ads/queries/tactical.py` adicionando 2 fields ao SELECT do `conversion_actions_query`:

```python
def conversion_actions_query() -> str:
    return """
        SELECT
          conversion_action.id,
          conversion_action.name,
          conversion_action.status,
          conversion_action.category,
          conversion_action.type,
          conversion_action.counting_type,
          conversion_action.attribution_model_settings.attribution_model,
          conversion_action.value_settings.default_value,
          conversion_action.value_settings.always_use_default_value,
          conversion_action.primary_for_goal,
          conversion_action.include_in_conversions_metric
        FROM conversion_action
    """.strip()
```

- [ ] **Step 2: Estender `_row_formatter` em `get_conversion_actions.py`**

Modificar `src/mcp/tools/get_conversion_actions.py:21-37` para retornar 2 chaves novas:

```python
def _row_formatter(row: Any) -> dict[str, Any]:
    ca = row.conversion_action
    return {
        "id": str(ca.id),
        "name": ca.name,
        "status": ca.status.name,
        "category": ca.category.name,
        "type": ca.type.name,
        "counting_type": ca.counting_type.name,
        "attribution_model": ca.attribution_model_settings.attribution_model.name,
        "default_value_brl": (
            micros_to_currency(ca.value_settings.default_value * 1_000_000)
            if ca.value_settings.default_value
            else 0.0
        ),
        "always_use_default_value": bool(ca.value_settings.always_use_default_value),
        "primary_for_goal": bool(ca.primary_for_goal),
        "include_in_conversions_metric": bool(ca.include_in_conversions_metric),
    }
```

- [ ] **Step 3: Atualizar description da tool pra mencionar novos fields**

Modificar `src/mcp/tools/get_conversion_actions.py:42-46`:

```python
@register_tool(
    name="get_conversion_actions",
    description=(
        "Acoes de conversao configuradas na conta com status, categoria, tipo, "
        "atribuicao, valor default, primary_for_goal (Smart Bidding optimization) "
        "e include_in_conversions_metric (dashboard 'Conversions' metric). "
        "Util pra auditoria de tracking + decisao de promocao Secondary->Primary."
    ),
    input_schema=_SCHEMA,
)
```

- [ ] **Step 4: Estender integration test fixture + assertions**

Modificar `tests/integration/test_tactical_tools.py:191-211` (test `test_get_conversion_actions_*`):

```python
async def test_get_conversion_actions_returns_summary(bound_context):
    from src.mcp.tools.get_conversion_actions import get_conversion_actions

    fake_rows = [
        {
            "id": "1",
            "name": "Purchase",
            "status": "ENABLED",
            "category": "PURCHASE",
            "type": "WEBPAGE",
            "counting_type": "ONE_PER_CLICK",
            "attribution_model": "DATA_DRIVEN",
            "default_value_brl": 0.0,
            "always_use_default_value": False,
            "primary_for_goal": True,
            "include_in_conversions_metric": True,
        },
    ]
    with patch(
        "src.mcp.tools.get_conversion_actions.run_report", AsyncMock(return_value=fake_rows)
    ):
        result = await get_conversion_actions({"customer_id": "1234567890"})
    assert result["count"] == 1
    assert result["actions"][0]["name"] == "Purchase"
    assert result["actions"][0]["primary_for_goal"] is True
    assert result["actions"][0]["include_in_conversions_metric"] is True
```

Manter o nome do test atual (look exact line). Se nome diferir, manter assinatura — só atualizar fixture + adicionar assertions.

- [ ] **Step 5: Run integration test**

```bash
python -m pytest tests/integration/test_tactical_tools.py -v -k get_conversion_actions
```

Expected: PASS com 2 assertions novas.

- [ ] **Step 6: Run pre-push gate**

```bash
python scripts/check_pre_push.py
```

Expected: 5/5 PASS (não toca em mutate flows, full sweep não obrigatório).

- [ ] **Step 7: Commit**

```bash
git add src/google_ads/queries/tactical.py src/mcp/tools/get_conversion_actions.py tests/integration/test_tactical_tools.py
git commit -m "$(cat <<'EOF'
feat(mcp): enrich get_conversion_actions with primary_for_goal + include_in_conversions_metric

G1 quick win do dogfood 2026-05-21 MO-JP+CAB. Tool curada agora retorna
2 fields críticos pra audit de conversion actions + decisão Secondary->Primary:
- primary_for_goal: flag Smart Bidding optimization
- include_in_conversions_metric: flag dashboard "Conversions" metric

Antes exigia GAQL custom (~5 min extra). Fields READ-only — F44 safe (immutable
apenas em UPDATE).

ICE 720.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2 — B1: `get_change_history` lag warning HORAS

**Files:**
- Modify: `src/mcp/tools/get_change_history.py:1-25` (module docstring)
- Modify: `src/mcp/tools/get_change_history.py:243-253` (tool description)

**Context:** O docstring atual fala "MINUTES TO HOURS" mas a tool description diz só "Janela maxima 30 dias". Dogfood 21/05 confirmou: >3 horas entre mudança UI e indexação no change_event, afeta múltiplos campos (não só `campaign.status`). Sprint 3b.x B4 anterior só warneava `campaign.status` em outras tools — esta task fortalece a WARNING **na tool dona do audit log lagging**.

- [ ] **Step 1: Atualizar module docstring (linhas 12-25)**

Substituir o bloco "Caveats" em `src/mcp/tools/get_change_history.py:12-25`:

```python
Caveats (empirically verified against production change_event 2026-05-11 e
re-confirmado em dogfood 2026-05-21 MO-JP):
- Propagation lag: change_event é AUDIT LOG LAGGING, NOT real-time. Mutações
  via API ou UI tipicamente levam MINUTOS A **HORAS** (já visto >3h em
  produção) para surface em change_event. O lag afeta MÚLTIPLOS campos, não
  apenas `campaign.status` — também `ai_max_setting.enable_ai_max`,
  `asset_automation_settings`, `text_guidelines.messaging_restrictions`, etc.
- Padrão V4 pra validar estado ATUAL pós-mutação (revert/incident recovery):
  use `run_gaql FROM campaign` como LEADING indicator (real-time) e
  `get_change_history` como LAGGING (audit log). Se divergirem, confie no
  leading. Se um campo opcional não retornar no GAQL, está vazio/removido.
- 30-day window é a retenção documentada; alguns date_range presets podem
  bater limite ligeiramente menor. Nosso path usa explicit BETWEEN dates.
- Google não distingue 'user applied via Recommendations UI' de 'Google
  auto-apply' em change_event.client_type — ambos surface como
  GOOGLE_ADS_RECOMMENDATIONS. summary.auto_applied_count conta a união;
  cross-reference auto-apply settings se intent matters.
```

- [ ] **Step 2: Atualizar tool description (@register_tool, linhas 243-253)**

Substituir bloco em `src/mcp/tools/get_change_history.py:243-253`:

```python
@register_tool(
    name="get_change_history",
    description=(
        "Historico de mudancas (change_event) na conta nos ultimos 7-30 dias com "
        "filtros opcionais (resource_types, operation_types, user_emails, "
        "client_types). Util pra auditoria 'CRITICO antes de tudo': detectar "
        "auto-apply Recommendations, mudancas estruturais, e quem mexeu no que. "
        "ATENCAO: latency de indexacao pode chegar a HORAS (>3h ja visto em "
        "producao) e afeta multiplos campos. Pra validar estado atual (revert/"
        "incident), use `run_gaql FROM campaign` como leading indicator. Inclui "
        "summary com totais por usuario/resource/operation. Janela maxima 30 "
        "dias. Audited como read sensivel."
    ),
    input_schema=_SCHEMA,
)
```

- [ ] **Step 3: Sanity ruff + format**

```bash
python -m ruff check src/mcp/tools/get_change_history.py
python -m ruff format --check src/mcp/tools/get_change_history.py
```

Expected: zero issues. PostToolUse hook deveria ter formatado auto.

- [ ] **Step 4: Commit**

```bash
git add src/mcp/tools/get_change_history.py
git commit -m "$(cat <<'EOF'
docs(mcp): escalate get_change_history lag warning to HOURS + multi-field

B1 quick win do dogfood 2026-05-21 MO-JP. Description anterior subestimava
latency ("MINUTES TO HOURS" no docstring, sem warning na tool description).
Dogfood confirmou >3h de lag e afetando ai_max_setting, asset_automation_
settings, text_guidelines.messaging_restrictions (não só campaign.status).

Adicionado padrão V4 explícito: usar `run_gaql FROM campaign` como leading
indicator pra estado atual quando precisar validar revert/incident recovery.

Sem mudança de comportamento — pure documentation hardening. ICE 700.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3 — UX2: `update_conversion_action` dry-run flow doc

**Files:**
- Modify: `src/mcp/tools/update_conversion_action.py:87-97` (tool description)

**Context:** Description atual diz "qualquer batch > 1 OU primary_for_goal=False retorna preview com token" mas não documenta o fluxo. Wellington nota no dogfood: "Não fica claro: Token vai onde? Re-enviar como parâmetro? Formato? Caminho exato pra aplicar após preview".

- [ ] **Step 1: Atualizar tool description (linhas 87-97)**

Substituir em `src/mcp/tools/update_conversion_action.py:87-97`:

```python
@register_tool(
    name="update_conversion_action",
    description=(
        "Atualiza ConversionAction: name, primary_for_goal (off = action vira "
        "non-biddable em todas as campaigns). 2 fields V0 — todos opcionais por "
        "item (forneça ao menos 1). Single item rename auto-aplica. Batch > 1 "
        "OU primary_for_goal=False retorna preview dry-run com "
        "`confirmation_token` (UUID string, expires em 10 min). Fluxo: 1) chame "
        "esta tool -> recebe response com status='dry_run' + confirmation_token. "
        "2) revise `changes` (lista de fields_updated por ID). 3) chame "
        "`apply_change(confirmation_token=<token>)` pra executar. Pra desligar "
        "include_in_conversions_metric, use Google Ads UI (Google v24 marca o "
        "field como immutable — F44)."
    ),
    input_schema=_SCHEMA,
)
```

- [ ] **Step 2: Sanity ruff + format**

```bash
python -m ruff check src/mcp/tools/update_conversion_action.py
python -m ruff format --check src/mcp/tools/update_conversion_action.py
```

Expected: zero issues.

- [ ] **Step 3: Commit**

```bash
git add src/mcp/tools/update_conversion_action.py
git commit -m "$(cat <<'EOF'
docs(mcp): document dry-run+confirm token flow in update_conversion_action

UX2 quick win do dogfood 2026-05-21 MO-JP. Description anterior mencionava
"preview com token" sem documentar fluxo. Wellington apontou ambiguidades:
formato do token, onde re-enviar, caminho completo pra aplicar.

Description agora especifica:
- Token format: UUID string
- expires_in_minutes: 10
- 3-step flow: tool -> review -> apply_change(token)

Padroniza convenção V4 dry-run+confirm com create_rsa/upload_customer_match_list.
Pure docs change. ICE 600.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4 — Pre-push gate + docs sync + push

**Files:**
- Modify: `docs/operacao/sprint-history.md` (append Sprint 3b.32 entry)
- Modify: `CLAUDE.md` (bump "Last updated" + pending/future section)

- [ ] **Step 1: Append Sprint 3b.32 entry em `sprint-history.md`**

Adicionar entry no formato existente (após Sprint 3b.31):

```markdown
### Sprint 3b.32 — Quality Wins HIGH (2026-05-21)

**Goal:** 3 quick wins ICE 600+ identificados no dogfood 2026-05-21 MO-JP+CAB D+9.

**Shipped:**
- **G1 (ICE 720):** `get_conversion_actions` retorna `primary_for_goal` + `include_in_conversions_metric` (READ-only, F44-safe). Antes exigia GAQL custom pra audit de conversion actions.
- **B1 (ICE 700):** `get_change_history` description escala lag warning de "alguns minutos" para "HOURS" (>3h visto em prod) + afeta múltiplos campos (não só `campaign.status`). Recomenda `run_gaql FROM campaign` como leading indicator.
- **UX2 (ICE 600):** `update_conversion_action` description documenta fluxo dry-run+confirm token (formato UUID, expires 10 min, 3-step path).

**Validation:**
- pre-push gate 5/5 PASS
- CI + Deploy green
- /health 200 OK

**Tool count:** 53 (sem mudança — pure quality wins, sem tools novas).

**Reference:** [`dogfood-2026-05-21-mestre-da-obra-jp-drift-detection.md`](dogfood-2026-05-21-mestre-da-obra-jp-drift-detection.md) seção "Quick wins recomendados".

**Findings:** Zero F-findings novos. F44 reforçado (include_in_conversions_metric immutable em UPDATE mas readable em listing).
```

- [ ] **Step 2: Bump `CLAUDE.md` — Last updated + pending/future**

Atualizar 2 pontos em `CLAUDE.md`:

**(a)** `**Last updated:** 2026-05-20` → `**Last updated:** 2026-05-21`

**(b)** Sprint history line `Sprint 3b.1 → 3b.31 (31 sprints)` → `Sprint 3b.1 → 3b.32 (32 sprints)` + data range `2026-05-04→20` → `2026-05-04→21`

**(c)** Production revision line update: substituir "post-`a01954b` (Sprint 3b.31 — `audit_competitor_keywords` 53rd tool" para algo como "post-`<sha-task4>` (Sprint 3b.32 — quality wins G1+B1+UX2, 53 tools)".

**(d)** Em "Pending / future", remover de "Sprint 3b.32 candidate" os items já atacados (não há — todos eram candidates novas, dogfood adicionou novas). Atualizar para mencionar W1 detect_drift + W3 audit_goal_attribution como novos top candidates ICE 486 / 360.

- [ ] **Step 3: Run pre-push gate**

```bash
python scripts/check_pre_push.py
```

Expected: 5/5 PASS.

- [ ] **Step 4: Commit docs + push**

```bash
git add docs/operacao/sprint-history.md CLAUDE.md
git commit -m "$(cat <<'EOF'
docs: Sprint 3b.32 signoff — Quality Wins HIGH G1+B1+UX2

Tool count 53 unchanged (pure quality wins).
Sprint history + CLAUDE.md atualizados.
Dogfood 2026-05-21 MO-JP+CAB drift detection referenciado.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"

git push origin main
```

- [ ] **Step 5: Watch CI + Deploy**

```bash
gh run list --limit 3
gh run watch <run-id>
```

Expected: CI green + Deploy green em ~5-7 min.

- [ ] **Step 6: Verify /health post-deploy**

```bash
curl -s https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/health
```

Expected: HTTP 200.

---

## Self-Review (run after writing this plan)

**Spec coverage:**
- G1 ICE 720 → Task 1 ✅
- B1 ICE 700 → Task 2 ✅
- UX2 ICE 600 → Task 3 ✅
- Pre-push + docs sync → Task 4 ✅

**Placeholder scan:** zero TBD/TODO/"fill in details". Code blocks completos em cada step.

**Type consistency:** `bool(ca.primary_for_goal)` + `bool(ca.include_in_conversions_metric)` match teste assertion `is True`. Fixture key names match return dict.

**Out-of-scope (defer):**
- W1 `detect_drift` (ICE 486) → Sprint 3b.33 candidate
- W3 `audit_goal_attribution` (ICE 360) → Sprint 3b.33 candidate
- G2 `change_event` em `list_gaql_resources` (ICE 360) → Sprint+1
- B2 schema enum CONVERSION_ACTION (ICE 288) → batch "schema cleanup"
- B3 LIKE OR LIKE hint em validate_gaql (ICE 192) → defer
- P1 cross-check ERP (fora-MCP) → doc-only

**No new findings expected.** Se durante execução algo quebrar, registrar via `/findings-add`.

---

## Estimated time

- Task 1: ~30 min (GAQL + formatter + test + commit)
- Task 2: ~15 min (description rewrite)
- Task 3: ~10 min (description rewrite)
- Task 4: ~20 min (docs + pre-push + push + watch CI)

**Total: ~75 min (~1.5h).** Solo dev pace, sem subagent overhead.
