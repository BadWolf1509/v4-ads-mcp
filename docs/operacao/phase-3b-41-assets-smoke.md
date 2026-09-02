# Phase 3b.41 — smoke runbook para `get_assets` e `remove_asset_link`

**ATENÇÃO: Este documento é uma ESPECIFICAÇÃO APENAS, não foi executado. Dois bloqueadores impedem a execução:**

1. **As tools estão apenas neste branch local (`feat/assets-visibilidade-e-unlink`).** Produção está na revisão 2026-08-20 que não tem `get_assets` nem `remove_asset_link`. O MCP server que serve o ambiente não consegue resolver essas ferramentas — chamadas retornarão "tool not found". A execução só é possível após este branch ser mesclado em `main` e deployado em produção.

2. **O passo 4-5 aplicam uma mutação real em uma conta de cliente pagante.** A conta `7862230676` (MO João Pessoa) é uma conta ativa em produção com campanhas veiculando. Remover um vínculo de asset em nível de conta afeta o que pode aparecer nos resultados da busca — não é limpeza inerte. Essa decisão requer aprovação explícita do Wellington (repo owner) antes de qualquer execução.

---

**Purpose:** Validar Sprint 3b.41 — Fase 1 da implementação de visibilidade + unlink de assets Google Ads.

- **`get_assets`** (Task 3): Leitura dos ativos vinculados em três níveis (CUSTOMER, CAMPAIGN, AD_GROUP) com filtro opcional por tipo de asset (`field_type`) e visualização de status (ENABLED, REMOVED, etc.). Cobre o §5 da spec com enumeração de recursos órfãos.
  
- **`remove_asset_link`** (Task 5): Mutação de desvinculação de asset com dry-run (confirmação_token), idempotência via `partial_failure`, e validação obrigatória contra o estado de produção via query GAQL.

**Operator:** wellington.ribeiro@v4company.com  
**Account principal:** `7862230676` Mestre da Obra JP+CAB (production V4 — Cliente real com assets vinculados em múltiplos níveis)

**Spec:** `docs/superpowers/specs/2026-09-02-ad-schedule-e-assets-design.md` (§2.1 Global Constraints, §5 Get Assets, §6-§7 Remove + Validation)  
**Plan:** `docs/superpowers/plans/2026-09-02-assets-visibilidade-e-unlink.md`

> **Escopo V0 confirmado:**
> - Tool count: 64 → 66 (duas novas tools: `get_assets` + `remove_asset_link`)
> - Nenhum breaking change (leitura pura em Task 3; mutação new-only em Task 5)
> - 2 ferramentas novas registradas no bucket defer (não impacta o always-22)
> - Zero migration no banco (ativos vinculados e status são campos Google nativos, não rastreados localmente)
> - **Não executado** — bloqueadores em 1 e 2 acima

**Dados conhecidos pré-smoke (probe spec 3b.19A.1):**

- Conta `7862230676` tem assets removidos conhecidos: callout `144113768040` ("Super Desconto") e `144113768046` ("Melhores Preços") — ambos status REMOVED.
- Asset `144113768043` ("Atendimento Eficaz") vinculado em **dois níveis** (CUSTOMER + CAMPAIGN) com `primary_status: ELIGIBLE` em ambos — demonstra que precedência **não existe** (não há razão "campaign overrides customer", Google devolve o status próprio do nível).

---

## Production URL

```
https://v4-ads-mcp-299432068772.southamerica-east1.run.app
(revisão 2026-08-20; deploy do 3b.41 ainda não aconteceu)
```

## Pre-flight — documento APENAS, sem checks automatizados executados

- [ ] **Branch local existente:** `git branch | grep feat/assets-visibilidade-e-unlink` — YES
- [ ] **Spec lida:** `docs/superpowers/specs/2026-09-02-ad-schedule-e-assets-design.md` sections 5-7 — YES
- [ ] **Plan lida:** `docs/superpowers/plans/2026-09-02-assets-visibilidade-e-unlink.md` — YES
- [ ] **Tasks 3 e 5 entregues (relatórios):**
  - Task 3 `get_assets` implementação + tests (`task-3-report.md` na SDD)
  - Task 5 `remove_asset_link` implementação + tests (`task-5-report.md` na SDD)
- [ ] **CI local passaria:** `python scripts/check_pre_push.py` PASS (não executado agora, mas será pré-merge) — 5/5 PASS esperado
- [ ] **Nenhum segredo ou credencial será digitado** durante este documento

---

## Smoke results

Preencher conforme execução **futura** (após deploy). Deixado em branco deliberadamente.

| # | Test | Result | Execution Date | Notes |
|---|---|---|---|---|
| T1 | `get_assets` sem filtro — aparecem linhas dos **3 níveis** (CUSTOMER, CAMPAIGN, AD_GROUP) + ≥1 com `status: REMOVED` | ⬜ pending | | |
| T2 | `get_assets` com `field_type="CALLOUT"` — filtro nariza corretamente a apenas callouts | ⬜ pending | | |
| T3 | Asset `144113768043` aparece com `primary_status: ELIGIBLE` **nos dois níveis** (CUSTOMER + CAMPAIGN) — prova que precedência não existe | ⬜ pending | | |
| T4 | `remove_asset_link` em vínculo de teste — retorna `confirmation_token` + `status: dry_run` + aplicável via `apply_change` | ⬜ pending | | |
| T5 | Query GAQL de confirmação **obrigatória** — SELECT campaign_asset.status por asset.id alvo retorna `status: REMOVED` no registro específico pós-aplicação | ⬜ pending | | |
| T6 | Reaplica `remove_asset_link` idêntico — retorna gracioso via `partial_failure` (não erro) | ⬜ pending | | |

**Effective result:** 0/6 PASS (não executado)

### F-findings emerged

_Preencher durante execução futura. Template: `**F## (SEV)** — <symptom>. Fix: <plan>. Family: <bug class>.`_

Se zero F-findings: documentar explicitamente "Zero F-findings novos. Sprint clean."

### Sign-off checklist — TODO após execução

- [ ] Pre-push gate 5/5 PASS (commit final merge branch)
- [ ] Spec compliance + code quality reviewers APPROVED (2 commits sequenciais Task 3 + Task 5)
- [ ] Production `/health` 200 (pós-deploy)
- [ ] T1 PASS — `get_assets` retorna linhas CUSTOMER + CAMPAIGN + AD_GROUP, ≥1 REMOVED  
- [ ] T2 PASS — filtro `field_type="CALLOUT"` funciona
- [ ] T3 PASS — asset `144113768043` aparece ELIGIBLE em ambos os níveis
- [ ] T4 PASS — `remove_asset_link` retorna `confirmation_token` válido
- [ ] T5 PASS — query GAQL confirma `status: REMOVED` por ID asset específico (não por contagem)
- [ ] T6 PASS — reaplica com graciosidade via `partial_failure`
- [ ] Tool count confirmado 66 em produção (64 → +2)
- [ ] Bucket distribution: 22 always + 44 defer verificado
- [ ] Zero findings criados OU todos catalogados (F### series) com cross-reference

---

## Teste T1 — `get_assets(customer_id)` sem filtro — 3 níveis + ≥1 REMOVED

**Setup:** Validar que a leitura não-filtrada enumera assets dos três níveis (CUSTOMER, CAMPAIGN, AD_GROUP) e que pelo menos um vem com `status: REMOVED`. Account `7862230676` tem dois callouts removidos conhecidos (IDs 144113768040 e 144113768046).

**Pré-requisito:** Branch local com Task 3 implementada. MCP server em produção ainda **não** tem a tool (bloqueador 1), então este teste NÃO pode rodar até deploy.

**Tool call:**

```
get_assets(
  customer_id="7862230676"
)
```

**Expected response shape:**

```json
{
  "customer_id": "7862230676",
  "total_assets": N,
  "assets": [
    {
      "asset_id": "144113768043",
      "level": "CUSTOMER",
      "field_type": "CALLOUT",
      "status": "ENABLED",
      "primary_status": "ELIGIBLE",
      "text": "Atendimento Eficaz"
    },
    {
      "asset_id": "144113768040",
      "level": "CUSTOMER",
      "field_type": "CALLOUT",
      "status": "REMOVED",
      "primary_status": null,
      "text": "Super Desconto"
    },
    {
      "asset_id": "XX",
      "level": "CAMPAIGN",
      "field_type": "SITELINK",
      "status": "ENABLED",
      "primary_status": "ELIGIBLE",
      "text": "..."
    },
    {
      "asset_id": "YY",
      "level": "AD_GROUP",
      "field_type": "CALLOUT",
      "status": "ENABLED",
      "primary_status": "ELIGIBLE",
      "text": "..."
    }
    // ... mais assets de cada nível
  ]
}
```

**Validação:**

- [ ] Response retorna sem error (tool retorna dict válido sem `"error"` key)
- [ ] `total_assets >= 3` (MO-JP tem assets vinculados)
- [ ] **Crítico T1:** Três níveis aparecem em `assets[]`: pelo menos 1 com `level: "CUSTOMER"`, pelo menos 1 com `level: "CAMPAIGN"`, pelo menos 1 com `level: "AD_GROUP"`
- [ ] **Crítico T1:** Pelo menos 1 asset com `status: "REMOVED"` presente (callouts `144113768040` ou `144113768046` esperados)
- [ ] Cada asset tem 6 campos obrigatórios: `asset_id`, `level`, `field_type`, `status`, `primary_status`, `text`
- [ ] Cada `asset_id` é string numérica
- [ ] Cada `level` está no whitelist: `"CUSTOMER" | "CAMPAIGN" | "AD_GROUP"`
- [ ] Cada `field_type` está no whitelist de tipo de ativo (CALLOUT, SITELINK, STRUCTURED_SNIPPET, CALL, PROMOTION, etc.)
- [ ] Cada `status` é `"ENABLED" | "REMOVED" | "UNSPECIFIED" | "UNKNOWN"`
- [ ] `primary_status` é `"ELIGIBLE" | "PAUSED" | "DISAPPROVED" | "UNDER_REVIEW" | null` (null esperado para REMOVED)
- [ ] Audit_log entry criada (operação `get_assets`, plataforma `google`, status `success`)

**Failure modes investigation:**

- Nenhum asset REMOVED aparece → query Google não devolveu campos `status=REMOVED` (inesperado, Wellington confirmou que os 2 callouts existem); verificar se Google response foi parseada completa
- Faltam um dos níveis (ex.: só CUSTOMER + CAMPAIGN, falta AD_GROUP) → filtro foi aplicado acidentalmente ou Google não devolveu AD_GROUP (verificar GAQL query e resource_names parsing)
- `primary_status` vem como string numérica (ex.: `"4"`) em vez de nome enum → proto-plus `.name` não foi aplicado (mesmo padrão F52)
- Tool não resolve (404 not found) → branch ainda não foi deployado (bloqueador 1) ou MCP registry stale

**Result:** ⬜ pending

---

## Teste T2 — `get_assets(customer_id, field_type="CALLOUT")` — filtro nariza

**Setup:** Validar que o filtro `field_type` funciona. Chamada repetida com `field_type="CALLOUT"` deve devolver subset apenas callouts (não sitelinks, não call, etc.).

**Pré-requisito:** T1 baseline (conhecer total assets não-filtrado).

**Tool call:**

```
get_assets(
  customer_id="7862230676",
  field_type="CALLOUT"
)
```

**Expected response shape:**

```json
{
  "customer_id": "7862230676",
  "total_assets": M,
  "filter_applied": {
    "field_type": "CALLOUT"
  },
  "assets": [
    {
      "asset_id": "144113768043",
      "level": "CUSTOMER",
      "field_type": "CALLOUT",
      "status": "ENABLED",
      "primary_status": "ELIGIBLE",
      "text": "Atendimento Eficaz"
    },
    // ... apenas callouts
  ]
}
```

**Validação:**

- [ ] Response retorna sem error
- [ ] `total_assets <= N` (T1 baseline N — subset ou igual)
- [ ] **Crítico T2:** TODOS os assets em `assets[]` têm `field_type: "CALLOUT"` (zero de outro tipo)
- [ ] `filter_applied` key presente indicando quais filtros ativos
- [ ] Assets `144113768040` (REMOVED) e `144113768046` (REMOVED) e `144113768043` (ENABLED) esperados se existem como callouts (subset de T1)
- [ ] Audit_log entry criada

**Failure modes investigation:**

- Aparecem assets de outro tipo (ex.: SITELINK) → filtro não foi aplicado server-side (verificar GAQL WHERE clause)
- `filter_applied` ausente → response não declara quais filtros estão ativos (UX degradada)

**Result:** ⬜ pending

---

## Teste T3 — Asset `144113768043` em dois níveis com `primary_status: ELIGIBLE`

**Setup:** Validar a especificação que diz não há precedência entre níveis. Asset `144113768043` ("Atendimento Eficaz") foi vinculado deliberadamente em CUSTOMER e CAMPAIGN para probe spec 3b.19A.1. Google devolve `primary_status: ELIGIBLE` **em ambos os níveis**, não uma hierarquia onde um "sobrescreve" o outro.

**Pré-requisito:** T1 resultado (anotar as duas linhas para `144113768043`).

**Verificação manual:**

Procurar em `assets[]` (T1 resultado) por DUAS linhas com `asset_id: "144113768043"`:

```
Linha 1: asset_id="144113768043", level="CUSTOMER", status="ENABLED", primary_status="ELIGIBLE"
Linha 2: asset_id="144113768043", level="CAMPAIGN", status="ENABLED", primary_status="ELIGIBLE"
```

**Validação:**

- [ ] Ambas as linhas presentes (grep por `144113768043` em resultado T1 retorna exatamente 2 linhas)
- [ ] **Crítico T3:** Ambas têm `primary_status: "ELIGIBLE"` (não `null`, não `"PAUSED"`)
- [ ] Não existe linha "vencedora" (ex.: nível CAMPAIGN não aparece sozinha, CUSTOMER também vem)
- [ ] Documentar que a spec §2.1 diz explicitamente que não há precedência entre níveis — cada um tem seu próprio `primary_status`

**Failure modes investigation:**

- Só uma das linhas aparece (ex.: só CAMPAIGN) → query não enumera todos os níveis (bug sério)
- Ambas aparecem mas com `primary_status` diferente (ex.: CUSTOMER=ELIGIBLE, CAMPAIGN=PAUSED) → seria inesperado (Wellington confirmou que ambas estão ativas em produção), documentar como finding

**Result:** ⬜ pending

---

## Teste T4 — `remove_asset_link` em vínculo de teste — dry-run com token

**Setup:** Validar que a mutação `remove_asset_link` funciona em dry-run. O passo aplica a remoção de um vínculo de asset em um nível específico. Wellington escolhe um vínculo "seguro" (não crítico para campanha ativa) para teste; documentar qual foi escolhido.

**ATENÇÃO — Bloqueador 2 aplica-se aqui:** Este teste requer aprovação explícita do Wellington para executar, mesmo que seja dry-run. A decisão de remover um vínculo em uma conta de cliente pagante é de negócio, não técnica.

**Pré-requisito:** T1-T3 resultado validado. Wellington identifica um vínculo seguro:

```
Vínculo escolhido para teste: <preencher com asset_id, level, account_id>
Razão: <preencher com motivo técnico/negócio seguro>
```

**Tool call (DRY_RUN — deve retornar preview, não aplicar):**

```
remove_asset_link(
  customer_id="7862230676",
  asset_id="<XXXXX>",
  level="<CUSTOMER|CAMPAIGN|AD_GROUP>"
)
```

*(Substituir `<XXXXX>` e `<LEVEL>` pelos valores reais do vínculo escolhido)*

**Expected response shape (dry_run path):**

```json
{
  "status": "dry_run",
  "operation": "remove_asset_link",
  "customer_id": "7862230676",
  "asset_id": "XXXXX",
  "level": "CUSTOMER",
  "blast_summary": "Desvincula asset XXXXX do nível CUSTOMER. Afeta X campanhas / Y anúncios que referenciam este asset.",
  "confirmation_token": "abc123def456ghi789jkl...",
  "expires_in_minutes": 10,
  "to_apply": "Chame apply_change(confirmation_token=<token>) para aplicar.",
  "confirmation_reason": "remove_asset_link is a mutating operation that unlinks a resource. Always CONFIRM."
}
```

**Validação (dry_run path):**

- [ ] `status == "dry_run"` (CONFIRM path acionado; mutação é sempre CONFIRM per spec §6)
- [ ] **Crítico T4:** `confirmation_token` key presente e é string não-vazia
- [ ] `confirmation_token` formato válido (encoding base64url ou similar, não guessável)
- [ ] `expires_in_minutes` presente e > 0 (10 minutos padrão esperado)
- [ ] `blast_summary` descreve o impacto esperado em português
- [ ] `to_apply` texto instruindo `apply_change(confirmation_token=...)`
- [ ] `operation` == `"remove_asset_link"`
- [ ] Audit_log entry criada com operation `remove_asset_link`, status `dry_run`, customer_id e asset_id rastreados
- [ ] Nenhum banco de dados foi modificado (operação foi apenas dry-run)

**Failure modes investigation:**

- `confirmation_token` ausente → bug envelope construction (check `preview_envelope` in `_mutate_common.py`)
- `status` != `"dry_run"` → caminho de confirmação não foi acionado (esperado ser CONFIRM, verificar `classify()`)
- Audit_log não foi gravado → auditoria falhou silenciosamente (F83 pattern possível se bookkeeping em finally)

**Result:** ⬜ pending

---

## Teste T5 — Query GAQL de confirmação obrigatória — `status: REMOVED` por asset_id

**Setup:** CRÍTICO — Confirmação obrigatória per spec §7. Não confirme por ausência em lista filtrada nem por `row_count`. O padrão correto é consultar o banco Google por ID asset específico e validar que `status == "REMOVED"` na linha alvo.

**Referência histórica medida 2026-09-02 na conta `7862230676`:**

| Forma de validar | Falha (estado PRÉ-aplicação) | Sucesso (estado PÓS-aplicação) | Distingue? |
|---|---|---|---|
| `row_count` não-filtrado de `campaign_asset` | 16 linhas | 16 linhas | **NUNCA** — REMOVED continua contando |
| `row_count` filtrado por `status = 'ENABLED'` | 16 linhas | 12 linhas | Sim, **OU com baseline conhecido** — sem baseline acerta por sorte |
| `status` pelo `asset.id` alvo via query | `status: ENABLED` | `status: REMOVED` | **SEMPRE** — verdade de fato inequívoca |

Conclusão: **Apenas a terceira forma é confiável.** Partial removal (remover 2 de 4 links devolve 14 ENABLED, lê-se como "mudou, logo funcionou", mas esquece os 2 que ainda estão lá).

**Query GAQL via `run_gaql` (executar APÓS `apply_change`):**

```
SELECT campaign.name, campaign_asset.status, asset.id
FROM campaign_asset
WHERE campaign_asset.field_type = 'CALLOUT' AND asset.id IN (<asset_id_alvo>)
```

*(Substituir `<asset_id_alvo>` pelo ID real aplicado em T4)*

**Expected result:**

```
campaign.name | campaign_asset.status | asset.id
----|---|----
"Campanha X" | "REMOVED" | "<asset_id_alvo>"
(zero ou mais linhas adicionais se o asset estava vinculado em múltiplas campanhas)
```

**Validação (crítica):**

- [ ] Query executa sem erro GAQL
- [ ] **Crítico T5:** `campaign_asset.status == "REMOVED"` para a linha com `asset.id == <asset_id_alvo>` (não null, não "PAUSED")
- [ ] Se havia múltiplas campanhas, **TODAS** têm `status: REMOVED` (confirmação completa)
- [ ] Nenhuma linha com `status: "ENABLED"` para o asset ID alvo (não há "link fantasma" parcial)
- [ ] Documentar a medição explicitamente para prova futura

**Failure modes investigation:**

- Query não retorna linhas → asset nunca estava vinculado em nível CAMPAIGN (possível se estava só em CUSTOMER/AD_GROUP); tentar outra tabela (`customer_asset` ou `ad_group_asset`)
- Aparece linha com `status: "ENABLED"` ainda → aplicação parcial falhou (finding crítica: mutation inconsistent)
- `status` é `"PAUSED"` em vez de `"REMOVED"` → bug envelope não aplicou a ação correta

**Result:** ⬜ pending

---

## Teste T6 — Reaplica `remove_asset_link` idêntico — gracioso via `partial_failure`

**Setup:** Validar idempotência. Chamar `remove_asset_link` novamente com os mesmos parâmetros de T4. Esperado: NOT erro `"already removed"`, mas resposta gracioso via mecanismo `partial_failure` que a spec descreve.

**Tool call (mesmo params de T4):**

```
remove_asset_link(
  customer_id="7862230676",
  asset_id="<XXXXX>",
  level="<CUSTOMER|CAMPAIGN|AD_GROUP>"
)
```

**Expected response shape (idempotência gracioso via partial_failure):**

```json
{
  "status": "dry_run",
  "operation": "remove_asset_link",
  "customer_id": "7862230676",
  "audit_log": [
    {
      "row_id": 123,
      "status": "already_removed",
      "message": "Asset XXXXX no nível CUSTOMER already_removed (operação idempotente)"
    }
  ]
}
```

*(Ou shape ligeiramente diferente conforme design executador, mas deve devolver gracioso, nunca erro)*

**Validação:**

- [ ] Response não retorna um HTTP error (não deve ser 400, 409, etc.)
- [ ] `status` pode ser `"dry_run"` novamente OU `"applied"` se foi auto-apply (gracioso é aceitável em ambos)
- [ ] **Crítico T6:** `audit_log` entry (ou equivalente) documente que foi `already_removed` ou `idempotent_success` (não erro)
- [ ] Nenhum dados foram modificados (já havia sido removido em T4-T5)
- [ ] Não criei duplicate removal ou inconsistência

**Failure modes investigation:**

- Response retorna HTTP 400 ou 409 → idempotência não foi implementada (spec §6 diz que deve ser gracioso)
- Audit_log não documenta `already_removed` → auditoria não rastreou a tentativa idempotente
- Realmente re-aplicou a ação (Google API retornou 200 como se algo mudasse) → implementação não verificou PRÉ-estado

**Result:** ⬜ pending

---

## Resultado final (após execução futura)

```
SMOKE 3b.41 assets: 0/6 PASS (não executado — bloqueadores 1 e 2 impedem)
Data de execução: <preencher após bloqueadores removidos e aprovação Wellington>
F-findings novos: <preencher durante execução — esperado ZERO>
```

---

## Notas operacionais pós-execução

1. Se qualquer T falhar: criar finding `F###` com severidade apropriada (HIGH se afeta mutação real, MED se é leitura)
2. Se todas T passarem: atualizar `estado-atual.md` com referência a este smoke + resultado
3. Documentar em `sprint-history.md` entrada Sprint 3b.41 com resumo smoke
4. Atualizar `CLAUDE.md` encontrado se mudou algo de premissa no code path de assets

---

## Referências

- Spec assets: `docs/superpowers/specs/2026-09-02-ad-schedule-e-assets-design.md` §2.1, §5, §6, §7
- Plan: `docs/superpowers/plans/2026-09-02-assets-visibilidade-e-unlink.md`
- Task 3 report: `.superpowers/sdd/2026-09-02-assets-visibilidade-e-unlink/task-3-report.md`
- Task 5 report: `.superpowers/sdd/2026-09-02-assets-visibilidade-e-unlink/task-5-report.md`
- Findings: `docs/operacao/findings-catalog.md` (F131-F138 pré-smoke histórico)
- Estado: `docs/operacao/estado-atual.md` (2026-09-02)
