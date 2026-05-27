# Sprint 3b.40 — Quick Wins Mutate Safety (A1+B9+A2)

**Status:** Spec draft
**Author:** Claude (assistant) com Wellington
**Created:** 2026-05-27
**Source:** [Dogfood MO-JP 2026-05-27](../../operacao/dogfood-2026-05-27-mestre-da-obra-jp-investigacao-senior.md) — 13 sugestões priorizadas ICE, top 3 selecionadas
**Esforço estimado:** 4-6h dev (single sequencial, 4 commits atômicos)

---

## 1. Contexto e motivação

Sessão dogfood 2026-05-27 em Mestre da Obra JP+CAB foi a mais densa do ciclo (169 mudanças aplicadas em 4h sessão). Wellington identificou 3 fricções operacionais críticas durante o workflow de cleanup massivo de keywords:

1. **A1 (ICE 800)** — `update_keyword_status` dry-run não mostra `sample_keywords`. Wellington aplicou 9 tokens PAUSE em batch sem sanity check humano. Apply token TTL 10min sem reverter — risco real de aplicar 19+ keywords erradas em batch.

2. **B9 (ICE 630 — NOVO BUG)** — `get_keyword_performance` retorna positive E negative `ad_group_criterion` sem distinção. Workflow "fresh fetch zumbis → extrair criterion_ids → PAUSE batch" produziu 147 candidatos quando o real era 108 (39 falsos positivos = negative ad_group_criterion que não podem ser pausadas via mutation). Forçou parse Python externo.

3. **A2 (ICE 600)** — `audit_quality_score` ainda não tem `ad_group_status` (gap de consistency vs `audit_zombie_keywords` cravado F52 25/05). Keywords QS≤2 em REMOVED ad_groups são órfãs cosméticas (não competem em leilão, não impactam QS/Smart Bidding) — usuário precisa filtrar manualmente.

**ICE somado:** 2030. **Custo dev:** 4-6h. **Wellington é o usuário #1 dessas tools** (MO-JP é a conta mais ativa em dogfood = 3 sessões em 8 dias). Fix amplifica produtividade imediatamente.

---

## 2. Escopo

### In scope (V0)

- **F56 catalog** em `findings-catalog.md` (B9 documentado como F-finding ANTES do sprint)
- **A2**: campo `ad_group_status` em `audit_quality_score` response (replica pattern F52)
- **B9**: campo `negative` em `get_keyword_performance` response + warning F56 na description
- **A1**: `sample_keywords` (top 5) no dry-run path de `update_keyword_status` via fetch GAQL extra
- Tests unit + integration cobrindo as 3 mudanças
- Smoke runbook `phase-3b-40-bootstrap.md` (3 testes T1-T3 em MO-JP)
- Pre-push gate + push deploy + signoff (sprint-history.md + CLAUDE.md)

### Out of scope

- **A3-A6 quick wins remanescentes** (summary_only, already_exists, limit_per_ad_group, last_conv_date) — backlog Sprint Quick Wins #2 (bundle Q3)
- **B1-B3 features médias** (batch tokens apply_change, server-side filters search_terms/keyword_performance) — backlog
- **C1-C3 tools novas** (bulk_promote_to_exact, create_ad_group_with_keywords, get_ad_group_intent_analysis) — backlog larger
- **D1-D3 docs** (cravar lições V4 em descriptions) — fazer junto com sprint adjacente que toque cada tool
- **Configurable `sample_size`** em A1 — V0 fixo top 5, expandir só se demanda real
- **`sample_keywords` no AUTO-APPLY path** (≤5 keywords) — auto-apply não tem preview pra revisar (aplica direto), YAGNI

---

## 3. Decisões de design

### 3.1 — A1 fetch strategy: Server-side fetch obrigatório

**Decidido em Pergunta 1.** Alternativas consideradas:
- ❌ Cliente passa `keyword_text` opcional na request (API mais complexa)
- ❌ Sample-only fetch top 5 (latency menor mas perde fidelidade)
- ✅ **Server-side fetch obrigatório** (zero API changes pro client, preview sempre completo)

**Trade-off aceito:** +100-200ms latency no DRY-RUN path (>5 keywords). AUTO-APPLY path inalterado.

### 3.2 — B9 negative field strategy: Opção A + C

**Decidido em Pergunta 2.** Alternativas consideradas:
- ❌ Opção A only (field, sem description warning) — não-explicativo
- ❌ Opção A + B + C (field + param `include_negative=false` default + description) — breaking change subtil
- ✅ **Opção A + C** (field `negative: bool` + description warning) — backward-compat total

**Caller filtra client-side:** `[r for r in rows if not r['negative']]`. Tools `audit_zombie_keywords` e `audit_quality_score` continuam filtrando server-side (são as recomendadas pra workflows positive-only).

### 3.3 — Sprint number: 3b.40 + catalog F56 antes

**Decidido em Pergunta 3.** Alternativas consideradas:
- ❌ Novo namespace `QW.1` Quick Wins (overhead trackear 3 namespaces)
- ❌ Catalog B9 inline durante sprint (menos atomicidade histórica)
- ✅ **Sprint 3b.40 + catalog F56 antes** (alinha Google Phase 3b series, atomic commit per F-finding)

### 3.4 — A1 sample ordering: primeiros 5 da lista caller

**Decidido sem pergunta (YAGNI).** Alternativas descartadas:
- ❌ Random 5 (não-deterministico, dificulta debug)
- ❌ Alfabético (perde semântica caller-defined)
- ✅ **Primeiros 5 da lista caller** (preserva intent — caller passa em alguma ordem, primeiros = bons candidatos pra sanity check)

### 3.5 — A1 fetch scope: TODOS criterion_ids do batch

**Decidido sem pergunta (YAGNI).** Diferença latency entre fetch 5 vs 100 IDs é mínima (~20ms). Fetch todos:
- Simplifica código (sem slicing antes do fetch)
- Future-proof (caller pode pedir sample maior depois sem refetch)
- Retorna apenas top 5 no `sample_keywords` field (resto descartado V0)

### 3.6 — Approach execução: Bundle único single PR (4 commits sequenciais)

**Decidido sem pergunta** (esforço 4-6h não justifica subagent dispatch overhead).

| # | Commit | Files | Tests |
|---|---|---|---|
| 1 | `docs(findings): catalog F56` | findings-catalog.md | — |
| 2 | `feat(mcp): A2 ad_group_status audit_quality_score` | 3 src + 3 tests | ~5 |
| 3 | `feat(mcp): B9 negative field get_keyword_performance` | 2 src + 1 test | ~2 |
| 4 | `feat(mcp): A1 sample_keywords update_keyword_status` | 2 src (1 novo) + 2 tests | ~5-7 |

---

## 4. Arquitetura

### 4.1 — F56 finding (Commit 1)

**Arquivo:** `docs/operacao/findings-catalog.md`

**Conteúdo F56:**
- Title: `F56 — get_keyword_performance retorna positive E negative ad_group_criterion sem distinção (workflow risk)`
- Severity: **MEDIUM** (workaround existe via `audit_zombie_keywords` e `audit_quality_score`, mas friction operacional documentada 27/05)
- Root cause: GAQL `keyword_view` retorna `ad_group_criterion.negative` mas tool atual omite no row_formatter
- Impact: workflow "extract criterion_ids zumbis pra PAUSE batch via fresh fetch" produz falsos positivos (147 vs 108 reais em MO-JP 27/05 = 39 negative-typed ad_group_criterion ENABLED)
- Mitigation: Sprint 3b.40 adiciona field + description warning (Opção A+C)
- Lesson: tools de listagem que feed mutate workflows MUST expor type discriminators (positive vs negative, criterion type) explícitos no output, mesmo que GAQL native exponha

**Sem mudanças de código no Commit 1.**

### 4.2 — A2: ad_group_status em audit_quality_score (Commit 2)

**Pattern reference:** F52 cravado 25/05 em `audit_zombie_keywords` (linhas 19, 44-45, 70).

**Files a modificar:**

1. **`src/google_ads/flag_keywords.py`** (KeywordRow + FlaggedKeyword dataclasses):
   - Add field `ad_group_status: str` em `KeywordRow` (linha ~24, entre `ad_group_name` e `campaign_name`)
   - Add field `ad_group_status: str` em `FlaggedKeyword` (linha ~42)
   - Forward field em construção do `FlaggedKeyword` (linha ~105)

2. **`src/google_ads/queries/audit_quality_score.py`**:
   - Query builder: adicionar `ad_group.status,` no SELECT (linha 29)
   - `parse_keyword_view_row`: adicionar `"ad_group_status": row.ad_group.status.name`
   - `dict_to_keyword_row`: forward `ad_group_status=d["ad_group_status"]`

3. **`src/mcp/tools/audit_quality_score.py`**:
   - Response `flagged_keywords[]`: adicionar `"ad_group_status": f.ad_group_status` (linha 153+)
   - Description: adicionar warning espelhando F52 — "ATENÇÃO (F52): keywords flagged podem estar em ad_groups REMOVED (órfãs cosméticas — não competem em leilão, não impactam QS/Smart Bidding). Filtre `ad_group_status='ENABLED'` no consumer pra cleanup de impacto técnico real."

**Tests:**

- `tests/unit/test_flag_keywords.py` — assertion `KeywordRow.ad_group_status` field exists + propagation pra `FlaggedKeyword` (2 tests)
- `tests/unit/test_audit_quality_score_query.py` — assertion `ad_group.status` em SELECT clause (1 test)
- `tests/integration/test_audit_quality_score.py` — assertion response contém `ad_group_status` field per row (2 tests: ENABLED + REMOVED samples)

### 4.3 — B9: negative field em get_keyword_performance (Commit 3)

**Files a modificar:**

1. **`src/google_ads/queries/tactical.py`** (`keyword_performance_query`, linha 8-30):
   - Adicionar `ad_group_criterion.negative,` no SELECT (após `ad_group_criterion.status,` linha 15)

2. **`src/mcp/tools/get_keyword_performance.py`**:
   - `_row_formatter` (linha 60-97): adicionar `"negative": bool(row.ad_group_criterion.negative)` (após `"status"`)
   - Description: substituir por versão com warning F56 (ver §3.2)

**Description nova proposta:**

```
[DEFER] Performance por palavra-chave com Quality Score completo (3 componentes:
creative, post_click, search_predicted_ctr) + estimativas de first_page_cpc
e top_of_page_cpc. Filtros: status (enabled|paused|removed|all), limit.
ATENÇÃO (F56): retorna positive E negative ad_group_criterion indistintamente.
Cada row tem field `negative: bool` — filtre `negative=false` no consumer pra
workflows de PAUSE/análise QS, OU use `audit_zombie_keywords`/`audit_quality_score`
(filtram `negative=FALSE` server-side).
```

**Tests:**

- `tests/integration/test_get_keyword_performance.py` — assertion response rows contém `negative` field (true + false samples via mocked stub). Verificar bool type (não None ou string). (1-2 tests)

### 4.4 — A1: sample_keywords no dry-run update_keyword_status (Commit 4)

**Files a criar/modificar:**

1. **NOVO MÓDULO `src/google_ads/queries/keyword_lookup.py`** (~50 LOC):

```python
"""GAQL helper pra resolver criterion_id → keyword_text + match_type.

Usado por update_keyword_status dry-run preview (Sprint 3b.40 A1).
"""

from typing import Any
from uuid import UUID

from src.google_ads.reports import run_report


def build_keyword_text_lookup_query(
    keyword_pairs: list[tuple[str, str]],
) -> str:
    """Build GAQL pra fetch keyword_text + match_type per (ad_group_id, criterion_id).

    Args:
        keyword_pairs: list de (ad_group_id, criterion_id) — duplicates OK,
            query deduplicates implicit via IN clause.

    Returns:
        GAQL string sobre ad_group_criterion resource, sem date filter
        (resource é absolute state, não time-series).

    Note: keyword_view é time-series (requires segments.date). ad_group_criterion
    é absolute state — não precisa date_range, mais barato.
    """
    if not keyword_pairs:
        raise ValueError("keyword_pairs cannot be empty")
    ad_group_ids = sorted({pair[0] for pair in keyword_pairs})
    criterion_ids = sorted({pair[1] for pair in keyword_pairs})
    ad_group_clause = ", ".join(ad_group_ids)
    criterion_clause = ", ".join(criterion_ids)
    return (
        "SELECT "
        "ad_group.id, "
        "ad_group_criterion.criterion_id, "
        "ad_group_criterion.keyword.text, "
        "ad_group_criterion.keyword.match_type "
        "FROM ad_group_criterion "
        f"WHERE ad_group.id IN ({ad_group_clause}) "
        f"AND ad_group_criterion.criterion_id IN ({criterion_clause})"
    )


def _lookup_row_formatter(row: Any) -> dict[str, Any]:
    """Parse SDK row → dict pra lookup index."""
    return {
        "ad_group_id": str(row.ad_group.id),
        "criterion_id": str(row.ad_group_criterion.criterion_id),
        "keyword_text": row.ad_group_criterion.keyword.text,
        "match_type": row.ad_group_criterion.keyword.match_type.name,
    }


async def fetch_keyword_texts(
    *,
    manager_id: UUID,
    session_id: UUID,
    customer_id: str,
    keyword_pairs: list[tuple[str, str]],
) -> dict[tuple[str, str], dict[str, str]]:
    """Resolve (ad_group_id, criterion_id) → {keyword_text, match_type}.

    Used by update_keyword_status DRY_RUN path pra preview sample.
    Graceful: returns partial dict if some pairs not found (no exception).

    Returns:
        dict keyed by (ad_group_id, criterion_id) tuple. Missing pairs
        simply absent from dict — caller iterates pairs e checks presence.
    """
    if not keyword_pairs:
        return {}
    query = build_keyword_text_lookup_query(keyword_pairs)
    rows = await run_report(
        manager_id=manager_id,
        session_id=session_id,
        customer_id=customer_id,
        query=query,
        row_formatter=_lookup_row_formatter,
        operation_name="keyword_text_lookup",
    )
    return {
        (r["ad_group_id"], r["criterion_id"]): {
            "keyword_text": r["keyword_text"],
            "match_type": r["match_type"],
        }
        for r in rows
    }
```

2. **`src/mcp/tools/update_keyword_status.py`** (DRY_RUN branch, linhas 107-126):

Top-level import (não dentro da função — convention V4):
```python
from src.google_ads.queries.keyword_lookup import fetch_keyword_texts
```

Dentro da branch DRY_RUN, antes de `create_pending`:
```python
# Fetch keyword_texts pra sample preview
text_index = await fetch_keyword_texts(
    manager_id=ctx.manager_id,
    session_id=ctx.session_id,
    customer_id=customer_id,
    keyword_pairs=keyword_pairs,  # já existe do pre-flight (linha 62)
)

# Build sample top 5 (primeiros da lista caller, preserva intent)
SAMPLE_SIZE = 5
sample_keywords = []
for ad_group_id, criterion_id in keyword_pairs[:SAMPLE_SIZE]:
    text_info = text_index.get((ad_group_id, criterion_id), {})
    sample_keywords.append({
        "ad_group_id": ad_group_id,
        "criterion_id": criterion_id,
        "keyword_text": text_info.get("keyword_text"),  # None se não resolvido
        "match_type": text_info.get("match_type"),
    })

# ... create_pending unchanged ...

return {
    "status": "dry_run",
    "operation": "update_keyword_status",
    "customer_id": customer_id,
    "blast_summary": summary,
    "sample_keywords": sample_keywords,
    "sample_truncated": target_count > SAMPLE_SIZE,
    "confirmation_token": token,
    "expires_in_minutes": 10,
    "to_apply": "Chame apply_change(confirmation_token=<token>) para aplicar.",
    "confirmation_reason": risk.reason,
}
```

**Tests:**

- `tests/unit/test_keyword_lookup.py` (3-4 tests):
  - `build_keyword_text_lookup_query` returns valid GAQL com IN clauses + dedup
  - Empty `keyword_pairs` → `ValueError`
  - `_lookup_row_formatter` extracts fields corretamente
- `tests/integration/test_update_keyword_status.py` (2 tests):
  - DRY_RUN path (>5 keywords): response contém `sample_keywords` (top 5) + `sample_truncated=true`
  - AUTO_APPLY path (≤5 keywords): response NÃO contém `sample_keywords` (unchanged)

---

## 5. Error handling

### A2 — ad_group_status edge cases

- `row.ad_group.status` é proto enum — `.name` retorna `"ENABLED"|"PAUSED"|"REMOVED"|"UNSPECIFIED"|"UNKNOWN"`. SDK garante never None (default UNSPECIFIED).
- Sem tratamento extra necessário — pattern F52 já validado.

### B9 — negative bool field

- `row.ad_group_criterion.negative` é proto bool — default `False` (SDK never None pra primitive types).
- Cast explícito `bool(...)` defensive (caso futuro proto-plus mudança).

### A1 — fetch graceful

- Se Google API rejeita query (rare — ad_group_id inválido): `run_report` raises → tool retorna error response standard (existing behavior preservado).
- Se fetch retorna partial result (alguns IDs não encontrados): `text_index.get(...)` retorna `{}` → `sample_keywords` row tem `keyword_text=None` + `match_type=None`. Caller vê que faltou resolver mas tem ad_group_id+criterion_id como fallback identifier.
- Se `keyword_pairs` for empty list: helper raises `ValueError` — mas isso NUNCA acontece em produção (tool valida `minItems: 1` no schema). Defense em depth.

---

## 6. Testing strategy

### Unit tests (5-7 novos)

- `tests/unit/test_flag_keywords.py` (+2): KeywordRow.ad_group_status field + propagation
- `tests/unit/test_audit_quality_score_query.py` (+1): SELECT contém ad_group.status
- `tests/unit/test_keyword_lookup.py` (+3-4 NOVO): query builder + parser + empty edge

### Integration tests (3-5 novos)

- `tests/integration/test_audit_quality_score.py` (+2): response field `ad_group_status` (ENABLED + REMOVED samples)
- `tests/integration/test_get_keyword_performance.py` (+1-2): response field `negative` (true + false samples)
- `tests/integration/test_update_keyword_status.py` (+2): DRY_RUN contém sample_keywords, AUTO_APPLY não contém

**Pre-push gate:** `python scripts/check_pre_push.py` (5/5 PASS) antes de commit final.

**Full sweep:** `python scripts/check_pre_push_full.py` opcional (sem Docker local, CI cobre).

### Smoke runbook (3 testes manuais)

`docs/operacao/phase-3b-40-bootstrap.md` via subagent `smoke-runbook-generator`:

- **T1 (A2)**: `audit_quality_score` em MO-JP (`7862230676`) — verify cada row em `flagged_keywords[]` contém `ad_group_status` field com valor PT-BR-mapped (ENABLED|PAUSED|REMOVED|UNKNOWN).
- **T2 (B9)**: `get_keyword_performance` em MO-JP — verify cada row contém `negative: bool` field. Mix esperado: maioria `false` + algumas `true` (Wellington documentou 39 negative ENABLED em CAB GERAL 27/05).
- **T3 (A1)**: `update_keyword_status` em MO-JP com 6+ keywords (random sample de zumbis safe-to-pause) — verify dry_run response contém `sample_keywords` top 5 + `sample_truncated=true`. Apply via `apply_change(token=...)` — verify aplica corretamente (sample não interfere com mutation).

---

## 7. Riscos e mitigações

| Risco | Probabilidade | Mitigação |
|---|---|---|
| Test fixture gap A1 fetch (proto_capture vs MagicMock) | LOW | A1 não usa builder pattern (sem proto_capture). Fetch usa `run_report` que já tem padrão de mock |
| GAQL `ad_group.status` field nome diferente em algum SDK | VERY LOW | F52 já validado em produção 25/05 (`audit_zombie_keywords.py:45`). Mesmo field |
| F56 description warning quebra Anthropic Messages API (>1024 chars) | LOW | Description nova ~370 chars (vs limit 1024). Safe |
| A1 fetch latency excessiva em batches grandes | LOW | Single GAQL com IN clause = 1 round-trip. Google Ads API típica 100-300ms. Schema sem maxItems explícito — investigar Google Ads API IN clause limit (~10k típico) durante plan |
| Caller passa criterion_id inválido → fetch retorna vazio → preview vazio | MEDIUM | Pre-flight `validate_keyword_criterion_types` já valida existence (linha 63 existing) — fetch só roda se pre-flight passa |

---

## 8. Calendário + dependencies

**Sequência (single sessão Wellington, ~4-6h):**

1. ✅ **Brainstorming** (concluído nesta sessão)
2. ✅ **Spec doc** (este arquivo)
3. **Self-review + user review** (próximo passo)
4. **Writing-plans skill** (invocar após approval)
5. **Execução** 4 commits sequenciais conforme `4.x` sections
6. **Smoke runbook gen** via subagent
7. **Smoke real** Wellington manual em MO-JP
8. **Signoff** sprint-history + CLAUDE.md

**Dependencies:** nenhuma (sprint isolado, sem blockers Meta/Google API external).

**Janela ótima:** **2026-05-27 ou 28** (esta semana). Não bloqueia Sprint M.4 que pode começar 03/06.

---

## 9. Success criteria

- [ ] F56 catalogado em findings-catalog.md (55 → 56 findings)
- [ ] A2: `audit_quality_score` response contém `ad_group_status` field em cada flagged_keyword
- [ ] B9: `get_keyword_performance` response contém `negative: bool` field em cada row
- [ ] A1: `update_keyword_status` dry-run response contém `sample_keywords` (top 5) + `sample_truncated` flag
- [ ] 5-7 unit tests novos passando
- [ ] 3-5 integration tests novos passando
- [ ] `check_pre_push.py` 5/5 PASS
- [ ] CI + Deploy green
- [ ] Smoke real 3/3 PASS em MO-JP
- [ ] sprint-history.md row 3b.40 adicionada
- [ ] CLAUDE.md Pending section refresh (remove B9+A1+A2, contagem 56 findings)

---

## 10. Pós-sprint (próximos candidatos)

Após shipping confirmado:
1. **Sprint M.4** — Meta breakdowns (geo+device+hourly) — janela 03/06-09/06
2. **Sprint Quick Wins #2** (Q3) — bundle A3-A6 + D1-D3 + B1-B3 (~6-8h)
3. **Sprint M.5** — Meta audience + top_creatives — janela 17/06-23/06

---

*Spec produzido 2026-05-27 via skill `superpowers:brainstorming`. Approval Wellington pendente antes de `writing-plans` skill.*
