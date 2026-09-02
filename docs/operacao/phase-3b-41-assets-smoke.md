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

**Dados conhecidos pré-smoke (observados em produção 2026-09-02):**

- Conta `7862230676` tem assets removidos conhecidos: callout `144113768040` ("Super Desconto") e `144113768046` ("Melhores Preços") — ambos status REMOVED. Observados via GAQL direto em `asset.callout_asset.callout_text`, produção Google Ads (não inventados para este documento).
- Asset `144113768043` ("Atendimento Eficaz") vinculado em **dois níveis** (CUSTOMER + CAMPAIGN) com `primary_status: ELIGIBLE` em ambos — demonstra que precedência **não existe** (não há razão "campaign overrides customer", Google devolve o status próprio do nível).

---

## Production URL

```
https://v4-ads-mcp-299432068772.southamerica-east1.run.app
(revisão 2026-08-20; deploy do 3b.41 ainda não aconteceu)
```

## Pre-flight — documento APENAS, sem checks automatizados executados

- [x] **Branch local existente:** `git branch | grep feat/assets-visibilidade-e-unlink` — confirmado
- [x] **Spec lida:** `docs/superpowers/specs/2026-09-02-ad-schedule-e-assets-design.md` sections 5-7 — confirmado
- [x] **Plan lida:** `docs/superpowers/plans/2026-09-02-assets-visibilidade-e-unlink.md` — confirmado
- [x] **Tasks 3 e 5 entregues (relatórios):**
  - Task 3 `get_assets` implementação + tests (`task-3-report.md` na SDD)
  - Task 5 `remove_asset_link` implementação + tests (`task-5-report.md` na SDD)
- [x] **CI local passaria:** `python scripts/check_pre_push.py` PASS (verificado pré-commit) — 5/5 PASS
- [x] **Nenhum segredo ou credencial será digitado** durante este documento — confirmado

---

## Smoke results

Preencher conforme execução **futura** (após deploy). Deixado em branco deliberadamente.

| # | Test | Result | Execution Date | Notes |
|---|---|---|---|---|
| T1 | `get_assets` sem filtro — aparecem linhas dos **3 níveis** em `links[]`, ≥1 com `status: REMOVED`, `summary` com agregações | ⬜ pending | | |
| T2 | `get_assets` com `field_type="CALLOUT"` — filtro se aplica, apenas callouts retornados, `links[]` é subset de T1 | ⬜ pending | | |
| T3 | Asset `144113768043` aparece com `primary_status: ELIGIBLE` **nos dois níveis** (CUSTOMER + CAMPAIGN) em `links[]` — prova que precedência não existe | ⬜ pending | | |
| T4 | `remove_asset_link` com `links=[{level, resource_name}]` — retorna `confirmation_token` 8 chars + `status: dry_run` | ⬜ pending | | |
| T4b | `apply_change(confirmation_token=<T4>)` — aplica a mutação, retorna `status: applied` + `applied_count >= 1` | ⬜ pending | | |
| T5 | Query GAQL de confirmação **obrigatória** — SELECT campaign_asset.status por resource_name alvo retorna `status: REMOVED` no registro específico | ⬜ pending | | |
| T6 | Reaplica `remove_asset_link` idêntico — retorna gracioso (novo token ou `applied_count: 0`), não erro | ⬜ pending | | |

**Effective result:** 0/7 PASS (não executado)

### F-findings emerged

_Preencher durante execução futura. Template: `**F## (SEV)** — <symptom>. Fix: <plan>. Family: <bug class>.`_

Se zero F-findings: documentar explicitamente "Zero F-findings novos. Sprint clean."

### Sign-off checklist — TODO após execução

- [ ] Pre-push gate 5/5 PASS (commit final merge branch)
- [ ] Spec compliance + code quality reviewers APPROVED (2 commits sequenciais Task 3 + Task 5)
- [ ] Production `/health` 200 (pós-deploy)
- [ ] T1 PASS — `get_assets` retorna `links[]` com CUSTOMER + CAMPAIGN + AD_GROUP, `summary` com agregações, ≥1 REMOVED  
- [ ] T2 PASS — filtro `field_type="CALLOUT"` funciona, subset válido
- [ ] T3 PASS — asset `144113768043` aparece ELIGIBLE em ambos os níveis (CUSTOMER + CAMPAIGN)
- [ ] T4 PASS — `remove_asset_link` retorna `confirmation_token` 8-char válido, `status: dry_run`
- [ ] T4b PASS — `apply_change(confirmation_token)` aplica, `status: applied`, `applied_count >= 1`
- [ ] T5 PASS — query GAQL confirma `status: REMOVED` por resource_name específico (não por contagem)
- [ ] T6 PASS — reaplica com graciosidade (novo token ou `applied_count: 0`), não erro
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
  "links": [
    {
      "level": "CUSTOMER",
      "resource_name": "customers/7862230676/customerAssets/144113768043~CALLOUT",
      "asset_id": "144113768043",
      "asset_name": "Atendimento Eficaz",
      "field_type": "CALLOUT",
      "status": "ENABLED",
      "primary_status": "ELIGIBLE",
      "primary_status_reasons": [],
      "campaign_id": null,
      "campaign_name": null,
      "ad_group_id": null,
      "ad_group_name": null
    },
    {
      "level": "CUSTOMER",
      "resource_name": "customers/7862230676/customerAssets/144113768040~CALLOUT",
      "asset_id": "144113768040",
      "asset_name": "Super Desconto",
      "field_type": "CALLOUT",
      "status": "REMOVED",
      "primary_status": "REMOVED",
      "primary_status_reasons": [],
      "campaign_id": null,
      "campaign_name": null,
      "ad_group_id": null,
      "ad_group_name": null
    },
    {
      "level": "CAMPAIGN",
      "resource_name": "customers/7862230676/campaignAssets/21359547724~144113768043~CALLOUT",
      "asset_id": "144113768043",
      "asset_name": "Atendimento Eficaz",
      "field_type": "CALLOUT",
      "status": "ENABLED",
      "primary_status": "ELIGIBLE",
      "primary_status_reasons": [],
      "campaign_id": "21359547724",
      "campaign_name": "[GPC][JPA][LEADS][SEG][MESTRE DA OBRA]",
      "ad_group_id": null,
      "ad_group_name": null
    }
    // ... mais links de cada nível
  ],
  "summary": {
    "total_links": N,
    "truncated": false,
    "by_level": {
      "CUSTOMER": M1,
      "CAMPAIGN": M2,
      "AD_GROUP": M3
    },
    "by_primary_status": {
      "ELIGIBLE": K1,
      "REMOVED": K2,
      "...": "..."
    },
    "assets_sem_vinculo_ativo": ["ID1", "ID2"]
  }
}
```

**Validação:**

- [ ] Response retorna sem error (tool retorna dict válido sem `"error"` key)
- [ ] `links[]` tem ≥ 3 elementos (MO-JP tem assets vinculados)
- [ ] **Crítico T1:** Três níveis aparecem em `links[]`: pelo menos 1 com `level: "CUSTOMER"`, pelo menos 1 com `level: "CAMPAIGN"`, pelo menos 1 com `level: "AD_GROUP"`
- [ ] **Crítico T1:** Pelo menos 1 link com `status: "REMOVED"` presente em `links[]` (callouts `144113768040` ou `144113768046` esperados)
- [ ] `summary` key presente com subcampos: `total_links`, `truncated`, `by_level`, `by_primary_status`, `assets_sem_vinculo_ativo`
- [ ] `summary.total_links == len(links)` (sanidade)
- [ ] Cada link em `links[]` tem 12 campos: `level`, `resource_name`, `asset_id`, `asset_name`, `field_type`, `status`, `primary_status`, `primary_status_reasons`, `campaign_id`, `campaign_name`, `ad_group_id`, `ad_group_name`
- [ ] Cada `asset_id` é string numérica
- [ ] Cada `resource_name` é string não-vazia (GCP resource naming `customers/.../assets/...`)
- [ ] Cada `level` está no whitelist: `"CUSTOMER" | "CAMPAIGN" | "AD_GROUP"`
- [ ] Cada `field_type` está no whitelist de tipo de ativo (CALLOUT, SITELINK, STRUCTURED_SNIPPET, CALL, PROMOTION, etc.)
- [ ] Cada `status` é `"ENABLED" | "REMOVED" | "UNSPECIFIED" | "UNKNOWN"`
- [ ] `primary_status` é `"ELIGIBLE" | "PAUSED" | "REMOVED" | "PENDING" | "LIMITED" | "NOT_ELIGIBLE"`
- [ ] `primary_status_reasons` é array (pode estar vazio)
- [ ] **Níveis (regra de campos):** CUSTOMER tem `campaign_id, campaign_name, ad_group_id, ad_group_name` todos `null`; CAMPAIGN tem `campaign_id` e `campaign_name` populados, `ad_group_id, ad_group_name` `null`; AD_GROUP tem todos os quatro populados
- [ ] Audit_log entry criada (operação `get_assets`, plataforma `google`, status `success`)

**Failure modes investigation:**

- Nenhum asset REMOVED aparece → query Google não devolveu campos `status=REMOVED` (inesperado, Wellington confirmou que os 2 callouts existem); verificar se Google response foi parseada completa
- Faltam um dos níveis (ex.: só CUSTOMER + CAMPAIGN, falta AD_GROUP) → filtro foi aplicado acidentalmente ou Google não devolveu AD_GROUP (verificar GAQL query e resource_names parsing)
- `primary_status` vem como string numérica (ex.: `"4"`) em vez de nome enum → proto-plus `.name` não foi aplicado (mesmo padrão F52)
- Tool não resolve (404 not found) → branch ainda não foi deployado (bloqueador 1) ou MCP registry stale

**Result:** ⬜ pending

---

## Teste T2 — `get_assets(customer_id, field_type="CALLOUT")` — filtro se aplica

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
  "links": [
    {
      "level": "CUSTOMER",
      "resource_name": "customers/7862230676/customerAssets/144113768043~CALLOUT",
      "asset_id": "144113768043",
      "asset_name": "Atendimento Eficaz",
      "field_type": "CALLOUT",
      "status": "ENABLED",
      "primary_status": "ELIGIBLE",
      "primary_status_reasons": [],
      "campaign_id": null,
      "campaign_name": null,
      "ad_group_id": null,
      "ad_group_name": null
    },
    // ... apenas links com field_type=CALLOUT
  ],
  "summary": {
    "total_links": M,
    "truncated": false,
    "by_level": {"CUSTOMER": A, "CAMPAIGN": B, "AD_GROUP": C},
    "by_primary_status": {"ELIGIBLE": X, "REMOVED": Y},
    "assets_sem_vinculo_ativo": [...]
  }
}
```

**Validação:**

- [ ] Response retorna sem error
- [ ] `summary.total_links <= N` (T1 baseline N — subset esperado pois filtrado)
- [ ] **Crítico T2:** TODOS os links em `links[]` têm `field_type: "CALLOUT"` (zero de outro tipo)
- [ ] Links com IDs `144113768040`, `144113768046` e `144113768043` aparecem se existem (subset de T1)
- [ ] Assets REMOVED e ENABLED ambos aparecem (filtro não filtra por status, só por field_type — spec §5 obrigatório)
- [ ] `summary` tem a mesma estrutura que T1
- [ ] Audit_log entry criada (mesma operação que T1 mas com parâmetro `field_type: "CALLOUT"` registrado)

**Failure modes investigation:**

- Aparecem assets de outro tipo (ex.: SITELINK) → filtro não foi aplicado server-side (verificar GAQL WHERE clause)

**Result:** ⬜ pending

---

## Teste T3 — Asset `144113768043` em dois níveis com `primary_status: ELIGIBLE`

**Setup:** Validar a especificação que diz não há precedência entre níveis. Asset `144113768043` ("Atendimento Eficaz") foi vinculado deliberadamente em CUSTOMER e CAMPAIGN em produção. Google devolve `primary_status: ELIGIBLE` **em ambos os níveis**, não uma hierarquia onde um "sobrescreve" o outro.

**Pré-requisito:** T1 resultado (anotar as duas linhas para `144113768043`).

**Verificação manual:**

Procurar em `links[]` (T1 resultado) por DUAS linhas com `asset_id: "144113768043"`:

```
Linha 1: asset_id="144113768043", level="CUSTOMER", status="ENABLED", primary_status="ELIGIBLE", resource_name="customers/7862230676/customerAssets/144113768043~CALLOUT"
Linha 2: asset_id="144113768043", level="CAMPAIGN", status="ENABLED", primary_status="ELIGIBLE", resource_name="customers/7862230676/campaignAssets/21359547724~144113768043~CALLOUT"
```

**Validação:**

- [ ] Ambas as linhas presentes em `links[]` (grep por `"asset_id": "144113768043"` retorna exatamente 2 linhas)
- [ ] **Crítico T3:** Ambas têm `primary_status: "ELIGIBLE"` (não `null`, não `"PAUSED"`)
- [ ] `resource_name` valores diferem por nível: o de conta é `customers/.../customerAssets/{asset_id}~{FIELD_TYPE}`, o de campanha é `customers/.../campaignAssets/{campaign_id}~{asset_id}~{FIELD_TYPE}` — confirmando vínculos distintos
- [ ] Não existe linha "vencedora" (ambas aparecem, ambas têm o mesmo `primary_status`)
- [ ] Documentar que a spec §2.1 diz explicitamente que não há precedência entre níveis — Google retorna o status próprio de cada vínculo, independente

**Failure modes investigation:**

- Só uma das linhas aparece (ex.: só CAMPAIGN) → query não enumera todos os níveis (bug sério)
- Ambas aparecem mas com `primary_status` diferente (ex.: CUSTOMER=ELIGIBLE, CAMPAIGN=PAUSED) → seria inesperado (Wellington confirmou que ambas estão ativas em produção), documentar como finding

**Result:** ⬜ pending

---

## Teste T4 — `remove_asset_link` em vínculo de teste — dry-run com token

**Setup:** Validar que a mutação `remove_asset_link` funciona em dry-run. O passo desvincula um link identificado em T1. Wellington escolhe um vínculo "seguro" (não crítico para campanha ativa) para teste; documentar qual foi escolhido. O vínculo é identificado pelo `resource_name` que `get_assets` devolveu.

**ATENÇÃO — Bloqueador 2 aplica-se aqui:** Este teste requer aprovação explícita do Wellington para executar, mesmo que seja dry-run. A decisão de remover um vínculo em uma conta de cliente pagante é de negócio, não técnica.

**Pré-requisito:** T1-T3 resultado validado. Wellington identifica um link seguro de `links[]`:

```
Link escolhido para teste: 
  asset_id: <ID>
  level: <CUSTOMER|CAMPAIGN|AD_GROUP>
  resource_name: <resource_name de T1>
Razão: <preencher com motivo técnico/negócio seguro>
```

**Tool call (DRY_RUN — deve retornar preview, não aplicar):**

```
remove_asset_link(
  customer_id="7862230676",
  links=[
    {
      "level": "<CUSTOMER|CAMPAIGN|AD_GROUP>",
      "resource_name": "<resource_name do T1>"
    }
  ]
)
```

*(Substituir `<level>` e `<resource_name>` pelos valores reais do link escolhido em T1)*

**Expected response shape (dry_run path):**

```json
{
  "status": "dry_run",
  "operation": "remove_asset_link",
  "customer_id": "7862230676",
  "blast_summary": "Desvincular 1 asset(s) (CUSTOMER×1). A entidade Asset NÃO é removida.",
  "confirmation_token": "ABC12XY9",
  "expires_in_minutes": 10,
  "to_apply": "Chame apply_change(confirmation_token=<token>) para aplicar.",
  "confirmation_reason": "remove_asset_link (1 vínculo(s)) — sempre confirma (spec §7.1 remove)"
}
```

**Validação (dry_run path):**

- [ ] `status == "dry_run"` (CONFIRM path acionado; mutação é sempre CONFIRM per spec §6)
- [ ] **Crítico T4:** `confirmation_token` key presente e é string não-vazia com exatamente 8 caracteres (padrão V4 `^[A-Z0-9]{8}$`)
- [ ] `expires_in_minutes` presente e > 0 (10 minutos padrão esperado)
- [ ] `blast_summary` descreve a desviculação esperada em português
- [ ] `to_apply` texto instruindo `apply_change(confirmation_token=...)`
- [ ] `operation` == `"remove_asset_link"`
- [ ] Audit_log entry criada com operation `remove_asset_link`, status `dry_run`, customer_id e target_count rastreados
- [ ] Nenhum banco de dados foi modificado (operação foi apenas dry-run)

**Failure modes investigation:**

- `confirmation_token` ausente → bug envelope construction (verificar `preview_envelope` em `_mutate_common.py`)
- `confirmation_token` != 8 caracteres uppercase + digits → implementação gerou formato errado (deve ser `^[A-Z0-9]{8}$`)
- `status` != `"dry_run"` → caminho de confirmação não foi acionado (sempre CONFIRM per spec §6, verificar `classify()`)
- `blast_summary` não menciona `links` ou nível → descrição incompleta (deveria listar impacto)
- Audit_log não foi gravado → auditoria falhou silenciosamente (F83 pattern possível se bookkeeping em finally)

**Result:** ⬜ pending

---

## Teste T4b — `apply_change` com confirmation_token de T4 — aplica a mutação

**Setup:** Validar que a mutação é aplicada de verdade. Usar o `confirmation_token` retornado em T4 e passar a `apply_change`.

**Pré-requisito:** T4 resultado válido com `confirmation_token` obtido.

**Tool call:**

```
apply_change(
  confirmation_token="<token de T4>"
)
```

*(Substituir `<token de T4>` pelo valor exato retornado em T4)*

**Expected response shape (applied path):**

```json
{
  "status": "applied",
  "operation": "remove_asset_link",
  "customer_id": "7862230676",
  "blast_summary": "Desvincular 1 asset(s) (CUSTOMER×1). A entidade Asset NÃO é removida.",
  "provider_request_id": "goog_request_id_xyz",
  "applied_count": 1,
  "resource_names": [...]
}
```

**Validação:**

- [ ] Response retorna sem error (não é `{"status": "error", ...}`)
- [ ] **Crítico T4b:** `status == "applied"` (mutação foi de fato executada)
- [ ] `operation == "remove_asset_link"`
- [ ] `applied_count >= 1` (pelo menos um vínculo foi removido)
- [ ] `provider_request_id` presente (Google Ads API internal tracking)
- [ ] `resource_names` pode estar vazio ou ter valores — tanto faz, o importante é o `applied_count`
- [ ] Audit_log entry criada com operation `remove_asset_link`, status `applied`, provider_request_id rastreado
- [ ] Nenhum erro de token inválido / expirado (se expirou, erro aparece aqui)

**Failure modes investigation:**

- `status: "error"` com "token invalid" → token fora do padrão `^[A-Z0-9]{8}$` ou não existe
- `status: "error"` com "token expired" → mais de 10 minutos passaram entre T4 e T4b
- `applied_count == 0` → token consumido mas Google rejeitou (possivelmente link já removido — normal, via partial_failure)

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

**Setup:** Validar idempotência. Chamar `remove_asset_link` novamente com os mesmos parâmetros de T4. Esperado: NOT erro, mas resposta gracioso via mecanismo `partial_failure` que a spec descreve — o link já foi removido, Google retorna parcialmente bem-sucedido. Não asserte contagens: `apply_change` não devolve `partial_failures` ao chamador, então nenhum campo da resposta as confirma. O que se verifica é a ausência de erro e, por re-query GAQL em `asset.id`, que o `status` do vínculo alvo continua `REMOVED`.

**Tool call (mesmo `links` array de T4):**

```
remove_asset_link(
  customer_id="7862230676",
  links=[
    {
      "level": "<CUSTOMER|CAMPAIGN|AD_GROUP>",
      "resource_name": "<resource_name de T4>"
    }
  ]
)
```

*(Substituir pelos mesmos valores de T4)*

**Expected response shape (idempotência gracioso):**

Não há contrato específico: `apply_change` não devolve breakdown de `partial_failures` ao caller. A validação é feita por re-query GAQL, não pela response.

**Validação:**

- [ ] Response não retorna um HTTP error (não deve ser 400, 409, 422, etc.)
- [ ] `status` é `"applied"` (se roteia pra `apply_change`) ou `"dry_run"` (se retorna preview novamente)
- [ ] **Crítico T6:** Nenhuma mensagem de erro terminal tipo `"invalid token"` ou `"authorization failed"` 
- [ ] Confirmação pós-aplicação: re-query GAQL (T5 query repetida) deve devolver `status: REMOVED` para o target link — prova que a idempotência funcionou (vínculo continua removido, não voltou)

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
