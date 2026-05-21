# Sprint 3b.33 — `detect_drift` Design Doc

**Date:** 2026-05-21
**Sprint:** 3b.33 (54th MCP tool)
**ICE:** 486 (top candidate ranqueado em [`dogfood-2026-05-21-mestre-da-obra-jp-drift-detection.md`](../../operacao/dogfood-2026-05-21-mestre-da-obra-jp-drift-detection.md))
**Author:** Wellington Ribeiro + Claude (brainstorming-driven)

---

## Context

Dogfood 2026-05-21 (MO-JP+CAB D+9) revelou padrão V4 recorrente: após batch estrutural, gestor responsável precisa auditar mudanças de **outros gestores V4 internos** ou auto-apply Recommendations Google em window 24-48h. Workflow manual atual: chamar `get_change_history`, filtrar mentalmente por `user_email ≠ wellinton`, inspecionar cada change.

Caso concreto: 20/05 Pedro Vytor (V4 interno) ativou AI Max + TEXT_ASSET_AUTOMATION em 2 campaigns sem combinar com Wellington (gestor responsável). 4 changes clusterizados em 54s. Wellington só detectou D+1 via inspeção manual change_event — perdeu ~10 min com workflow ad-hoc.

`detect_drift` consolida esse workflow em **1 tool call** com flags acionáveis.

## Use case primário V0 (cravado em brainstorming)

**Co-management:** Auditar mudanças de OUTROS gestores V4 após batch seu. Filtro principal: `responsible_user_emails[]` — todos os changes com `user_email NOT IN` essa lista contam como drift. Auto-apply (`client_type=GOOGLE_ADS_RECOMMENDATIONS`) sempre conta como drift (sem `user_email`).

V0 cuts (não-suportados — fora scope): incident response (covered indirectly por lista vazia = "all changes are drift"), auto-apply audit dedicado (covered via flag), revert suggestions, multi-account, notification.

## Design decisions cravadas (brainstorming 7 perguntas)

| Decisão | Escolha |
|---|---|
| **Use case primário V0** | Co-management (lição 46 dogfood) |
| **User filter shape** | `responsible_user_emails[]` (array de emails AUTORIZADOS) |
| **Time window** | V4 pattern: `date_range` preset + `start_date`/`end_date` custom. Novo preset `LAST_2_DAYS` default |
| **Output opinionated level** | Structured + 3 flags simples (NÃO alert textual / suggested_actions hardcoded) |
| **Architecture** | Pure aggregator + wrapper sobre `get_change_history` (DRY máximo) |
| **Flags V0** | 3 simples: `auto_apply_detected`, `multiple_users_detected`, `structural_change` |
| **Changes detail** | Full row + cap+limit (default 100, max 500, truncated bool) |

---

## Section 1 — Architecture overview

**Pattern:** Pure aggregator + wrapper sobre `get_change_history` — idêntico ao Sprint 3b.30 (`audit_quality_score`) e 3b.31 (`audit_competitor_keywords`).

**Layer stack:**

1. **`src/google_ads/drift_detection.py` — pure module** (testable standalone, zero Google SDK imports). 5 dataclasses frozen+slots: `ChangeEventRow`, `DriftChange`, `DriftFlag`, `DriftSummary`, `DriftResult`. Função `detect_drift(rows, *, responsible_user_emails, limit) → DriftResult`.
2. **`src/mcp/tools/detect_drift.py` — tool wrapper** com schema + chamada `get_change_history` internamente + boundary dict→dataclass + retorna result dict.
3. `audit_this_call=True` (sensitive read, igual `get_change_history`).

**Data flow:**

```
detect_drift({customer_id, responsible_user_emails, date_range/start_date/end_date, limit})
  └─> get_change_history({customer_id, date_range/start/end, limit=500})   # internal call
        └─> Google Ads API change_event GAQL
  └─> dict_to_change_event_row[]                                # boundary conversion
  └─> drift_detection.detect_drift(rows, responsible_user_emails, limit=100)
        └─> filter out responsible_user_emails (case-insensitive)
        └─> compute 3 flags (auto_apply / multiple_users / structural_change)
        └─> aggregate by_user / by_resource_type / by_operation
        └─> truncate to limit (default 100)
  └─> return DriftResult.to_dict()
```

**Reuse benefits:**

- `get_change_history._resolve_names` enriche `resource_name` (campaign+ad_group lookup) → drift output gets named entities free
- `get_change_history._build_summary` semantics (auto-apply collapsed em `by_user` sintético "auto-apply") já validated em produção
- Zero novos GAQL queries — empirical-validation safety
- 1 API call ao Google (não 2) — perf trivial
- `change_history_query` constraint 30-day window herdada automaticamente

---

## Section 2 — Schema (input)

```python
_DATE_PRESETS = [
    "LAST_2_DAYS",   # NEW — sane default for D+1/D+2 post-batch audit
    "TODAY",
    "YESTERDAY",
    "LAST_7_DAYS",
    "LAST_14_DAYS",
    "LAST_30_DAYS",
]

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "responsible_user_emails": {
            "type": "array",
            "items": {"type": "string", "format": "email"},
            "maxItems": 20,
            "description": (
                "Emails AUTORIZADOS pra mexer na conta (gestor responsável + co-gestores V4). "
                "Changes com user_email NESSA lista NÃO contam como drift. "
                "Lista vazia = incident mode (todos os changes contam como drift). "
                "Auto-apply (client_type=GOOGLE_ADS_RECOMMENDATIONS) sempre conta como drift "
                "(não tem user_email)."
            ),
        },
        "date_range": {
            "type": "string",
            "enum": _DATE_PRESETS,
            "default": "LAST_2_DAYS",
            "description": "Periodo via preset. Para periodo custom, use start_date+end_date.",
        },
        "start_date": {
            "type": "string",
            "pattern": "^\\d{4}-\\d{2}-\\d{2}$",
            "description": (
                "Data inicial YYYY-MM-DD inclusive. Quando informado junto com end_date, "
                "sobrepoe date_range preset. Obriga end_date."
            ),
        },
        "end_date": {
            "type": "string",
            "pattern": "^\\d{4}-\\d{2}-\\d{2}$",
            "description": "Data final YYYY-MM-DD inclusive. Obrigatorio se start_date informado.",
        },
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": 500,
            "default": 100,
            "description": "Cap em changes[] na response. Summary + flags refletem total bruto.",
        },
    },
    "required": ["customer_id"],
    "additionalProperties": False,
}
```

**Notas:**

- `responsible_user_emails` é **optional** (default `[]` = "incident mode")
- `LAST_2_DAYS` é preset NOVO — atende V4 D+1/D+2 padrão pós-batch (lição 46). Adicionado em `_DATE_PRESETS` local da tool detect_drift (não no `get_change_history` — quando passar `LAST_2_DAYS` via wrapper internal call, resolve antes de chamar)
- `limit` default 100 (cap 500) — mesmo padrão `get_negative_keywords_audit` (Sprint 3b.23 F22 fix)
- Sem `resource_types`/`operation_types` filter V0 — gestor filtra client-side ou usa `get_change_history` direto
- Sem `auto_apply_only` filter V0 — flag `auto_apply_detected` cobre

**No composition keywords:** zero `oneOf/allOf/anyOf` (3b.19B.1 convention preservada).

---

## Section 3 — Output shape (response)

```python
{
    "customer_id": "7862230676",
    "period": {"from": "2026-05-19", "to": "2026-05-21"},
    "responsible_user_emails": ["wellinton.ribeiro@v4company.com"],
    "summary": {
        "total_drift_changes": 4,        # changes que NÃO são de responsible_user_emails
        "total_changes_in_window": 5,    # raw total (incluindo authorized)
        "by_user": {
            "pedro.vytor@v4company.com": 4,
            # "auto-apply" como key sintético se houver auto-apply changes
        },
        "by_resource_type": {"CAMPAIGN": 4},
        "by_operation": {"UPDATE": 4},
    },
    "flags": [
        {
            "code": "multiple_users_detected",
            "severity": "medium",
            "message_pt": "1 usuário não-autorizado (pedro.vytor@v4company.com) realizou 4 changes.",
            "evidence": {"unauthorized_users": ["pedro.vytor@v4company.com"]},
        },
        # Possíveis outros codes V0:
        # "auto_apply_detected" (severity low) — qualquer client_type=GOOGLE_ADS_RECOMMENDATIONS
        # "structural_change" (severity high) — qualquer REMOVE em CAMPAIGN/AD_GROUP/CONVERSION_ACTION
    ],
    "changes": [
        # Cada change é DriftChange row, ordered DESC por change_date_time:
        {
            "change_date_time": "2026-05-20 10:13:00.123456",
            "user_email": "pedro.vytor@v4company.com",
            "client_type": "GOOGLE_ADS_WEB_CLIENT",
            "resource_type": "CAMPAIGN",
            "resource_id": "22169885957",
            "resource_name": "CAB - Geral",   # via _resolve_names herdado
            "operation": "UPDATE",
            "changed_fields": ["campaign.ai_max_setting.enable_ai_max"],
            "campaign_id": "22169885957",
            "ad_group_id": None,
        },
        # ... (até `limit` rows)
    ],
    "truncated": false,  # true se total_drift_changes > limit
    "returned_count": 4,
}
```

**Decisões cravadas:**

- `summary.total_drift_changes` = count POST-filter (apenas mudanças NÃO-autorizadas)
- `summary.total_changes_in_window` = count PRE-filter (sanity check pro gestor saber tamanho da janela)
- `flags[]` empty se nada detectado (V0 max 3 flags simultâneas possíveis)
- `changes[]` ordered DESC by `change_date_time` (mesmo que `get_change_history`)
- `truncated` + `returned_count` echoam padrão Sprint 3b.23 (F22 fix)
- `responsible_user_emails` ecoa input pra debug/audit clarity

---

## Section 4 — Algorithm (pure module logic)

```python
# src/google_ads/drift_detection.py

from dataclasses import dataclass
from typing import Literal

Severity = Literal["low", "medium", "high"]

# Structural-change family: REMOVE em qualquer destes resource types é high-impact
_STRUCTURAL_RESOURCE_TYPES = frozenset({"CAMPAIGN", "AD_GROUP", "CONVERSION_ACTION"})

# Auto-apply detection: client_type sentinel (already used em get_change_history)
_AUTO_APPLY_CLIENT_TYPE = "GOOGLE_ADS_RECOMMENDATIONS"
_AUTO_APPLY_USER_BUCKET = "auto-apply"


@dataclass(frozen=True, slots=True)
class ChangeEventRow:
    """Boundary input — dict de get_change_history converte pra cá."""
    change_date_time: str
    user_email: str          # "" se auto-apply
    client_type: str
    resource_type: str
    resource_id: str
    resource_name: str
    operation: str           # "CREATE" | "UPDATE" | "REMOVE"
    changed_fields: tuple[str, ...]
    campaign_id: str | None
    ad_group_id: str | None


@dataclass(frozen=True, slots=True)
class DriftChange:
    """Output row — mesma shape de ChangeEventRow."""
    change_date_time: str
    user_email: str
    client_type: str
    resource_type: str
    resource_id: str
    resource_name: str
    operation: str
    changed_fields: tuple[str, ...]
    campaign_id: str | None
    ad_group_id: str | None


@dataclass(frozen=True, slots=True)
class DriftFlag:
    code: str
    severity: Severity
    message_pt: str
    evidence: dict   # specific data triggering the flag


@dataclass(frozen=True, slots=True)
class DriftSummary:
    total_drift_changes: int
    total_changes_in_window: int
    by_user: dict[str, int]
    by_resource_type: dict[str, int]
    by_operation: dict[str, int]


@dataclass(frozen=True, slots=True)
class DriftResult:
    summary: DriftSummary
    flags: tuple[DriftFlag, ...]
    drift_changes: tuple[DriftChange, ...]
    truncated: bool


def detect_drift(
    rows: list[ChangeEventRow],
    *,
    responsible_user_emails: list[str],
    limit: int,
) -> DriftResult:
    """Detect drift changes given a list of change_event rows.

    Algorithm:
    1. Normalize responsible_user_emails (lowercase + strip).
    2. Partition rows into authorized (user_email in normalized list) vs drift.
       Auto-apply (client_type=GOOGLE_ADS_RECOMMENDATIONS) ALWAYS goes to drift,
       independent of email match (auto-apply has empty user_email).
    3. Aggregate drift rows: by_user (auto-apply collapsed as sintético key
       "auto-apply"), by_resource_type, by_operation.
    4. Detect 3 flags em order:
       - auto_apply_detected (severity low): any drift row com client_type sentinel
       - multiple_users_detected (severity medium): >1 distinct non-auto-apply user
       - structural_change (severity high): any REMOVE em _STRUCTURAL_RESOURCE_TYPES
    5. Sort drift rows DESC by change_date_time (stable; input deveria já vir DESC
       de get_change_history mas defensivo).
    6. Truncate to limit. truncated = True se len(drift_rows) > limit.
    7. Return DriftResult.

    Pure function — zero IO, zero Google SDK, fully testable.
    """
```

**Edge cases tratados:**

- Empty `responsible_user_emails` → todos os rows são drift (incident mode)
- Auto-apply rows com `user_email=""` → vão pra drift (não match qualquer email autorizado)
- Case sensitivity: normalize lowercase ambos lados (`row.user_email.lower() in {e.lower() for e in responsible_user_emails}`)
- Empty rows input → DriftResult com summary zerado + 0 flags + 0 drift_changes
- `limit=0` ou negativo → rejected schema-side, não chega aqui
- `multiple_users_detected` ignora bucket "auto-apply" — só conta humans distintos

**Boundary parser** (em `src/mcp/tools/detect_drift.py`):

```python
def dict_to_change_event_row(d: dict) -> ChangeEventRow:
    """Convert get_change_history row dict to ChangeEventRow dataclass.
    
    Defensive: missing fields default to "" or None; changed_fields list → tuple.
    """
    return ChangeEventRow(
        change_date_time=str(d.get("change_date_time", "")),
        user_email=str(d.get("user_email", "")),
        client_type=str(d.get("client_type", "")),
        resource_type=str(d.get("resource_type", "")),
        resource_id=str(d.get("resource_id", "")),
        resource_name=str(d.get("resource_name", "")),
        operation=str(d.get("operation", "")),
        changed_fields=tuple(d.get("changed_fields", [])),
        campaign_id=d.get("campaign_id"),
        ad_group_id=d.get("ad_group_id"),
    )
```

---

## Section 5 — V0 cuts (out of scope)

| Item | Por que cortar V0 | V1+ candidato |
|---|---|---|
| **Revert suggestions / auto-revert tool** | Tool passive detect only. Reverter = mutate complexo (depende do field, irreversible em alguns casos). Risk too high V0. | V2+ dedicated `revert_change(change_event_id)` tool com always-CONFIRM |
| **Multi-account aggregation** | Single `customer_id` mantém escopo simples. MCC iteration adiciona perf complexity + permission edge cases. | V2+ wrapper `detect_drift_across_accounts(account_ids[])` |
| **Email/Slack notification** | Read-only tool. Notification = side effect fora scope MCP. | V2+ separate notification service (cron + push) |
| **`sensitive_field_modified` flag (whitelist)** | Whitelist hardcoded de ~10 field paths (ai_max, asset_automation, bidding_strategy_type, primary_for_goal, etc) requer maintenance. YAGNI até descobrir field reincidente em drift real. | V1 candidato ICE alto se Wellington pegar 2-3 drifts no padrão |
| **`rapid_cluster` flag (N changes <60s)** | Heuristic time-window (Pedro Vytor 4 changes em 54s). Útil mas not minimum-V0. | V1 quick win |
| **`resource_types`/`operation_types` filter** | Gestor filtra client-side reading response, OU usa `get_change_history` direto pra deep-dive. | V1 se demanda real surge |
| **`responsible_user_emails` auto-default via manager_id → DB lookup** | Requer query a `managers` table pra mapear UUID→email. Cleaner UX mas DB coupling. | V1 default opcional se hardcoded explicit no schema fica chato |
| **change_event 30-day window override** | Limite da API Google (não nosso). `LAST_30_DAYS` max preset, custom `start_date/end_date` capped 30d. | Fora scope (API limit) |
| **WebSocket / streaming for real-time drift** | Tool é pull-based MCP read. Real-time requer architecture change. | V3+ |
| **Confidence score per change** | "Is this drift CERTAIN?" requires user authorization model + role-based ACLs. | V2+ depois RBAC |

---

## Section 6 — Testing strategy + V0 surface metrics

### Test pyramid

| Tipo | Count | Foco |
|---|---|---|
| Unit (pure module) | ~16 | Algorithm correctness — partition, flags, aggregation, truncation, edge cases |
| Unit (boundary) | ~3 | `dict_to_change_event_row` parser robustness (missing fields, None vs "" sentinel) |
| Integration (tool wrapper) | ~3 | Wire-up: get_change_history mock → detect_drift call → response shape. Schema validation. responsible_user_emails passing through. |
| Smoke (production) | T1-T6 | Real account Mestre da Obra JP (caso Pedro Vytor 20/05 ainda dentro de window 30d) |

### Unit tests detail (pure module, ~16)

- `test_empty_responsible_list_all_drift` — incident mode default
- `test_single_email_match_no_drift` — happy path co-management
- `test_multi_email_match_partial_drift` — V4 multi-gestor coordenado
- `test_auto_apply_always_drift_even_with_full_authorization` — auto-apply imune ao filter
- `test_case_insensitive_email_matching` — `Pedro@v4` vs `pedro@v4`
- `test_flag_auto_apply_detected_positive` — flag emitida quando há GOOGLE_ADS_RECOMMENDATIONS
- `test_flag_auto_apply_detected_negative` — sem GOOGLE_ADS_RECOMMENDATIONS, flag ausente
- `test_flag_multiple_users_detected_positive` — 2+ users não-autorizados
- `test_flag_multiple_users_detected_negative` — apenas 1 user não-autorizado
- `test_flag_multiple_users_ignores_auto_apply_bucket` — auto-apply não conta como "user adicional"
- `test_flag_structural_change_positive` — REMOVE em CAMPAIGN
- `test_flag_structural_change_negative` — UPDATE em CAMPAIGN (não trigger)
- `test_aggregation_by_user_with_auto_apply_collapse` — sintético "auto-apply" bucket
- `test_aggregation_by_resource_type_counter` — Counter behavior
- `test_truncation_limit_exceeded` — 50 rows + limit=10 → truncated=true, 10 returned
- `test_total_drift_vs_total_in_window_invariant` — total_in_window >= total_drift sempre

### Smoke runbook V0 (6 tests)

| # | Cenário | Conta | Expected |
|---|---|---|---|
| T1 | Schema default — sem responsible_user_emails | MO-JP `7862230676` | Incident mode, todos changes drift, flags pode emitir multiple_users + auto_apply |
| T2 | Co-management — `responsible_user_emails=[wellinton]` LAST_2_DAYS | MO-JP | Pedro Vytor 4 changes 20/05 detectados como drift (within 30d window) |
| T3 | Custom date range — `start_date=2026-05-20, end_date=2026-05-20` | MO-JP | Reproduz Pedro Vytor cluster exato |
| T4 | Limit truncation — `limit=2` em conta com 5+ drift | MO-JP | truncated=true, returned_count=2, summary refletindo total real |
| T5 | Flags structural_change — conta com REMOVE em CAMPAIGN/AD_GROUP/CONVERSION_ACTION nos últimos 7d | Best-effort | flag emitida com evidence |
| T6 | Empty drift — conta clean dentro de window | ML Antiguidades | total_drift_changes=0, flags=[] |

**Defer condicionais:** T5 DEFERRED se nenhum REMOVE recente; T6 skip se ML sem mudanças mensuráveis. Pattern F41/F45 (env limitation = doc only, não bug).

### V0 surface metrics

```
- 1 new MCP tool: detect_drift (tool count 53 → 54)
- 1 new pure module: src/google_ads/drift_detection.py (~150 LOC)
- 1 new tool wrapper: src/mcp/tools/detect_drift.py (~100 LOC)
- ~22 testes (16 unit pure + 3 unit boundary + 3 integration)
- 1 smoke runbook (phase-3b-33-bootstrap.md, 6 tests)
```

### Estimated effort

- A1 (haiku — pure module + 16 unit tests): ~25 min
- A2 (haiku — boundary parser + 3 tests): ~10 min
- A3 (sonnet — tool wrapper + 3 integration + schema): ~25 min
- A4 (smoke-runbook-generator): ~5 min
- A5 (smoke execution Wellington manual): ~30 min
- A6 (signoff + push): ~15 min

**TOTAL:** ~110 min (~1.8h) via subagent-driven (paralelo onde possível).

**Workflow:** A1 + A2 paralelo (arquivos diferentes), A3 depende de A1+A2 (importa dataclasses). A4 paralelo a A3 (geração runbook não precisa código pronto). A5+A6 serial.

---

## Riscos + mitigações

| Risco | Mitigação |
|---|---|
| **B1 lag (3b.32)** — change_event até 3h pra surface | Document na tool description: "drift detection é lagging indicator. Use `run_gaql FROM campaign` pra current state se timing crítico." Auto-herdada de `get_change_history` description recentemente fortalecida. |
| **`get_change_history` internal call retorna >500 rows truncados** | V0 hardcode `limit=500` no internal call (max preset Sprint 3b.23). Se gestor precisa mais, escolhe smaller date_range. Document trade-off na description. |
| **`responsible_user_emails` typo "wellington" vs "wellinton"** | Format `email` validation cobre forma. Lowercase normalize cobre case. Typo de letra: gestor recebe ALL changes como drift — visível na response, gestor corrige e re-roda. Fail-loud. |
| **Auto-apply changes empty `user_email`** | Handled explicitly em algorithm — bucket sintético "auto-apply" + sempre drift. Aligned com `get_change_history._build_summary` existente. |
| **30-day window enforcement** | Herda de `change_history_query` RangeTooWideError. Mensagem PT-BR já existe. |

---

## References

- Dogfood source: [`docs/operacao/dogfood-2026-05-21-mestre-da-obra-jp-drift-detection.md`](../../operacao/dogfood-2026-05-21-mestre-da-obra-jp-drift-detection.md) seção "Tools curadas sugeridas — W1"
- Architecture precedent: Sprint 3b.30 ([`audit_quality_score`](../../operacao/phase-3b-30-bootstrap.md)) e 3b.31 ([`audit_competitor_keywords`](../../operacao/phase-3b-31-bootstrap.md))
- `get_change_history` description hardening: Sprint 3b.32 commit `102b58a`
- F22 limit + truncated pattern: Sprint 3b.23 ([`phase-3b-23-bootstrap.md`](../../operacao/phase-3b-23-bootstrap.md))
- No-composition-keywords convention: Sprint 3b.19B.1 ([CLAUDE.md](../../../CLAUDE.md) "No JSON Schema composition keywords")
