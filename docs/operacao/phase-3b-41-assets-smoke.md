# Phase 3b.41 — smoke runbook para `get_assets` e `remove_asset_link`

**ATENÇÃO: Este documento é uma ESPECIFICAÇÃO APENAS, não foi executado. Dois bloqueadores impedem a execução:**

1. **As tools estão apenas neste branch local (`feat/assets-visibilidade-e-unlink`).** Produção está na revisão 2026-08-20 que não tem `get_assets` nem `remove_asset_link`. O MCP server que serve o ambiente não consegue resolver essas ferramentas — chamadas retornarão "tool not found". A execução só é possível após este branch ser mesclado em `main` e deployado em produção.

2. **O passo 4-5 aplicam uma mutação real em uma conta de cliente pagante.** A conta `7862230676` (MO João Pessoa) é uma conta ativa em produção com campanhas veiculando. Remover um vínculo de asset em nível de conta afeta o que pode aparecer nos resultados da busca — não é limpeza inerte. Essa decisão requer aprovação explícita do Wellington (repo owner) antes de qualquer execução.

---

**Purpose:** Validar Sprint 3b.41 — Fase 1 da implementação de visibilidade + unlink de assets Google Ads.

- **`get_assets`** (Task 3): Leitura dos ativos vinculados em três níveis (CUSTOMER, CAMPAIGN, AD_GROUP) com filtro opcional por tipo de asset (`field_type`) e visualização de status (ENABLED, REMOVED, etc.). Cobre o §5 da spec com enumeração de recursos órfãos.
  
- **`remove_asset_link`** (Task 5): Mutação de desvinculação de asset com dry-run (`confirmation_token`), idempotência via `partial_failure`, e validação obrigatória contra o estado de produção via query GAQL.

**Operator:** wellington.ribeiro@v4company.com  
**Account principal:** `7862230676` Mestre da Obra JP+CAB (production V4 — Cliente real com assets vinculados em múltiplos níveis)

**Spec:** `docs/superpowers/specs/2026-09-02-ad-schedule-e-assets-design.md` (§2.1 Global Constraints, §5 Get Assets, §6-§7 Remove + Validation)  
**Plan:** `docs/superpowers/plans/2026-09-02-assets-visibilidade-e-unlink.md`

> **Escopo V0 confirmado:**
> - Tool count: 64 → 66 (duas novas tools: `get_assets` + `remove_asset_link`)
> - Nenhum breaking change (leitura pura em Task 3; mutação new-only em Task 5)
> - 2 ferramentas novas registradas no bucket defer (não impacta o always-23 — verificado por grep de `bucket="always"` em `src/mcp/tools/`, consistente com `docs/operacao/estado-atual.md`: baseline de produção é 23 always + 41 defer, e neste branch 23 always + 43 defer)
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
- [x] **CI local passaria:** `python scripts/check_pre_push.py` PASS (verificado pré-commit) — 6/6 PASS (`scripts/_runner.py` `BASE_STEPS`: ruff check, ruff format, mypy, pytest unit, pytest integração não-DB, tailwind sync)
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
| T6 | Reaplica `remove_asset_link` idêntico (mesmo `links`) — mint de um novo `confirmation_token`, `status: dry_run`, sem erro | ⬜ pending | | |
| T6b | `apply_change(confirmation_token=<T6>)` — idempotência: `status: applied` sem erro terminal (`applied_count` pode ser 0 ou 1); prova real é o re-query GAQL `status: REMOVED` | ⬜ pending | | |

**Effective result:** 0/8 PASS (não executado)

### F-findings emerged

_Preencher durante execução futura. Template: `**F## (SEV)** — <symptom>. Fix: <plan>. Family: <bug class>.`_

Se zero F-findings: documentar explicitamente "Zero F-findings novos. Sprint clean."

### Sign-off checklist — TODO após execução

- [ ] Pre-push gate 6/6 PASS (commit final merge branch)
- [ ] Spec compliance + code quality reviewers APPROVED (2 commits sequenciais Task 3 + Task 5)
- [ ] Production `/health` 200 (pós-deploy)
- [ ] T1 PASS — `get_assets` retorna `links[]` com CUSTOMER + CAMPAIGN + AD_GROUP, `summary` com agregações, ≥1 REMOVED  
- [ ] T2 PASS — filtro `field_type="CALLOUT"` funciona, subset válido
- [ ] T3 PASS — asset `144113768043` aparece ELIGIBLE em ambos os níveis (CUSTOMER + CAMPAIGN)
- [ ] T4 PASS — `remove_asset_link` retorna `confirmation_token` 8-char válido, `status: dry_run`
- [ ] T4b PASS — `apply_change(confirmation_token)` aplica, `status: applied`, `applied_count >= 1`
- [ ] T5 PASS — query GAQL confirma `status: REMOVED` por resource_name específico (não por contagem)
- [ ] T6 PASS — reaplica `remove_asset_link`, mint de novo token, `status: dry_run`, sem erro
- [ ] T6b PASS — `apply_change` do token de T6 retorna `status: applied` sem erro terminal; re-query GAQL confirma `status: REMOVED` mantido
- [ ] Tool count confirmado 66 em produção (64 → +2)
- [ ] Bucket distribution: 23 always + 43 defer verificado
- [ ] Zero findings criados OU todos catalogados (F### series) com cross-reference

---

## Teste T1 — `get_assets(customer_id)` sem filtro — 3 níveis + ≥1 REMOVED

**Setup:** Validar que a leitura não-filtrada enumera assets dos três níveis (CUSTOMER, CAMPAIGN, AD_GROUP) e que pelo menos um vem com `status: REMOVED`. Account `7862230676` tem dois callouts removidos conhecidos (IDs 144113768040 e 144113768046).

🔴 **Use `limit: 1000`, não o default.** Medido em 02/09, a conta tem **735 vínculos** (26 `customer_asset` + 313 `campaign_asset` + 396 `ad_group_asset`), dos quais **598 são `AD_IMAGE`** de RSA. Com o default de 200 a resposta trunca, e a ordenação é por `asset_id` — ou seja, quais 200 sobrevivem é decidido pela ordem, não pela relevância. A asserção "aparecem os três níveis" passaria a testar a sorte da ordenação em vez do comportamento da tool. Com 1000, os 735 cabem e `truncated` deve vir `false`.

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
- [ ] Cada `resource_name` é string não-vazia, no formato de VÍNCULO (nunca o Asset genérico `customers/.../assets/...`): CUSTOMER é `customers/{cid}/customerAssets/{asset_id}~{FIELD_TYPE}`, CAMPAIGN é `customers/{cid}/campaignAssets/{campaign_id}~{asset_id}~{FIELD_TYPE}`, AD_GROUP é `customers/{cid}/adGroupAssets/{ad_group_id}~{asset_id}~{FIELD_TYPE}` (confirmado em `tests/unit/test_remove_asset_link.py`, linhas 60/70/81)
- [ ] Cada `level` está no whitelist: `"CUSTOMER" | "CAMPAIGN" | "AD_GROUP"`
- [ ] Cada `field_type` está no whitelist de tipo de ativo (CALLOUT, SITELINK, STRUCTURED_SNIPPET, CALL, PROMOTION, etc.)
- [ ] Cada `status` é `"ENABLED" | "PAUSED" | "REMOVED"` (enum `AssetLinkStatus` do SDK Google Ads instalado — `google.ads.googleads.<v>.enums.types.asset_link_status.AssetLinkStatusEnum.AssetLinkStatus`; os sentinelas de proto `UNSPECIFIED`/`UNKNOWN` ficam fora da whitelist por convenção do repo, não são valor operacional — mas o parser repassa o que o Google mandar, então um deles aparecer aqui é ele mesmo digno de virar finding, não de ser ignorado)
- [ ] `primary_status` é `"ELIGIBLE" | "PAUSED" | "REMOVED" | "PENDING" | "LIMITED" | "NOT_ELIGIBLE"` (SDK v24, spec §5.1 linha 166)
- [ ] `primary_status_reasons` é array (pode estar vazio)
- [ ] **Níveis (regra de campos):** CUSTOMER tem `campaign_id, campaign_name, ad_group_id, ad_group_name` todos `null`; CAMPAIGN tem `campaign_id` e `campaign_name` populados, `ad_group_id, ad_group_name` `null`; AD_GROUP tem todos os quatro populados
- [ ] **Exatamente UMA** entry nova em `audit_log` para esta chamada, com `operation_name: "get_assets"`. Das três consultas internas, só a de `customer_asset` passa `audit_this_call=True` (`src/mcp/tools/get_assets.py`) — uma chamada do gestor vira uma linha, não três. O `params_summary` dessa linha carrega os filtros aplicados: `field_type`, `campaign_ids` e `limit` (aqui, `null`/`null`/`200`). Confirme por `get_my_audit_log`.

**Failure modes investigation:**

- Nenhum asset REMOVED aparece → query Google não devolveu campos `status=REMOVED` (inesperado, Wellington confirmou que os 2 callouts existem); verificar se Google response foi parseada completa
- Faltam um dos níveis (ex.: só CUSTOMER + CAMPAIGN, falta AD_GROUP) → filtro foi aplicado acidentalmente ou Google não devolveu AD_GROUP (verificar GAQL query e resource_names parsing)
- `primary_status` vem como string numérica (ex.: `"4"`) em vez de nome enum → proto-plus `.name` não foi aplicado (mesmo padrão UX-2 — não F52, que é sobre `audit_zombie_keywords` não filtrar `ad_group.status`)
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
- [ ] `summary` **difere** do T1 num ponto: como esta chamada usa filtro (`field_type`), ela traz `orphan_scope: "nao_calculado_com_filtro"` e **não** traz `assets_sem_vinculo_ativo`. Detecção de órfão só é completa em chamada sem filtro — uma lista calculada sobre visão parcial marcaria como órfão um asset cujo único vínculo vivo está fora do filtro. O resto (`total_links`, `truncated`, `by_level`, `by_primary_status`) é igual.
- [ ] **Exatamente UMA** entry nova em `audit_log`, como no T1 — e desta vez o `params_summary` dela mostra `field_type: "CALLOUT"`, que é o ponto: o filtro aplicado fica rastreado. Se a entry vier com `field_type: null`, o filtro não chegou ao audit.

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
- [ ] Documentar que a spec **§5.1** ("Resultado 3 — o conceito não existe na API", linha 160) diz explicitamente que não há precedência entre níveis — `AssetLinkPrimaryStatusReason` não tem nenhum valor de precedência, e Google retorna o `primary_status` próprio de cada vínculo, independente (§2.1 é só as convenções de mutate que o repo herda — não fala de precedência)

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
  "confirmation_reason": "remove_asset_link (1 vínculo(s)) — sempre confirma (spec §7.1 remove)",
  "target_count": 1
}
```

**Validação (dry_run path):**

- [ ] `status == "dry_run"` (CONFIRM path acionado; mutação é sempre CONFIRM per spec §6 — `remove_asset_link` não tem branch AUTO, ver `src/mcp/tools/remove_asset_link.py`)
- [ ] **Crítico T4:** `confirmation_token` key presente e é string não-vazia com exatamente 8 caracteres (padrão V4 `^[A-Z0-9]{8}$`, gerado por `generate_token()` em `src/governance/dry_run.py`)
- [ ] `expires_in_minutes` presente e > 0 (10 minutos, `DEFAULT_TTL_MINUTES` em `src/governance/dry_run.py`)
- [ ] `blast_summary` descreve a desviculação esperada em português
- [ ] `to_apply` texto instruindo `apply_change(confirmation_token=...)`
- [ ] `operation` == `"remove_asset_link"`
- [ ] `target_count == 1` (tamanho do array `links` desta chamada — chega ao envelope via `**extra` de `preview_envelope`, `src/mcp/tools/_mutate_common.py`)
- [ ] Uma linha nova aparece em `pending_confirmations` (token, customer_id, operation_type, payload, blast_summary, expires_at) — **não** em `audit_log`: dry-run só grava a tabela de preview (`create_pending`, `src/governance/dry_run.py`); o audit da mutação real só existe depois de T4b

**Failure modes investigation:**

- `confirmation_token` ausente → bug envelope construction (verificar `preview_envelope` em `_mutate_common.py`)
- `confirmation_token` != 8 caracteres uppercase + digits → implementação gerou formato errado (deve ser `^[A-Z0-9]{8}$`)
- `status` != `"dry_run"` → caminho de confirmação não foi acionado (sempre CONFIRM per spec §6, verificar `classify()`)
- `blast_summary` não menciona `links` ou nível → descrição incompleta (deveria listar impacto)
- Chamada lança exceção em vez de devolver preview → falha na escrita de `pending_confirmations` (`create_pending` não usa `best_effort`/`finally` como o `audit_log.record` de `run_report`/`run_mutation` — aqui um erro de escrita interrompe a chamada inteira, não falha em silêncio)

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
- [ ] Audit_log entry criada com `operation: "remove_asset_link"`, `action_type: "mutate"`, `status: "success"` (vocabulário do `audit_log` é `success`/`error`/`denied` — não é o mesmo `status` do envelope da tool, que usa `applied`/`dry_run`/`error`; ver `status: str = "success"` em `src/db/repositories/audit_log.py` e a gravação em `run_mutation`, `src/google_ads/mutations.py`), `provider_request_id` rastreado
- [ ] Nenhum erro de token inválido / expirado (se expirou, erro aparece aqui)

**Failure modes investigation:**

- `status: "error"` com "token invalid" → token fora do padrão `^[A-Z0-9]{8}$` ou não existe
- `status: "error"` com "token expired" → mais de 10 minutos passaram entre T4 e T4b
- `applied_count == 0` → Google recusou a operação apesar da chamada não ter levantado erro (`partial_failure=True` engole falhas por-operação). Diferente de T6b, aqui o vínculo foi confirmado `ENABLED` em T1-T3 antes do teste — `applied_count == 0` não é esperado neste passo; investigue via re-query GAQL (T5) antes de seguir

**Result:** ⬜ pending

---

## Teste T5 — Query GAQL de confirmação obrigatória — `status: REMOVED` por asset_id

**Setup:** CRÍTICO — Confirmação obrigatória per spec §7. Não confirme por ausência em lista filtrada nem por `row_count`. O padrão correto é consultar o banco Google por ID asset específico e validar que `status == "REMOVED"` na linha alvo.

**Referência histórica medida 2026-09-02 na conta `7862230676` (spec §7, linhas 195-203) — de uma limpeza DIFERENTE e MAIOR (6 vínculos), não de uma execução deste runbook:**

Os números abaixo vieram do incidente de campo que motivou a spec, não de T4/T4b aqui — que desvincula **1** link só. Se você re-medir durante a execução real, espere um delta de 1 no `row_count` filtrado (ex.: `N` → `N-1`), não o 16→12 histórico. A tabela fica porque o ponto que ela prova — nenhuma forma de contar linha distingue sucesso de falha sem depender de um baseline exato — vale em qualquer escala, e um delta de 1 é **ainda mais fácil de confundir com ruído** do que o delta de 4 medido em 02/09.

| Forma de validar | Falha (estado PRÉ-aplicação) | Sucesso (estado PÓS-aplicação) | Distingue? |
|---|---|---|---|
| `row_count` não-filtrado de `campaign_asset` | 16 linhas | 16 linhas | **NUNCA** — REMOVED continua contando |
| `row_count` filtrado por `status = 'ENABLED'` | 16 linhas | 12 linhas | Sim, **OU com baseline conhecido** — sem baseline acerta por sorte |
| `status` pelo `asset.id` alvo via query | `status: ENABLED` | `status: REMOVED` | **SEMPRE** — verdade de fato inequívoca |

Conclusão: **Apenas a terceira forma é confiável, em qualquer escala de remoção.** Partial removal ilustra o mesmo problema por outro recorte (spec §7, linha 203): tirar 2 de 4 vínculos devolve 14 linhas com `status: ENABLED`, que se lê como "mudou, logo funcionou" — mas esquece os 2 que continuam lá. Neste runbook o equivalente é tirar 1 de N: olhando só a contagem, uma mudança de 1 linha é praticamente invisível.

**Query GAQL via `run_gaql` (executar APÓS `apply_change`) — escolha a query pelo `level` do link escolhido em T4, não sempre `campaign_asset`:**

CUSTOMER:
```
SELECT customer_asset.status, asset.id
FROM customer_asset
WHERE customer_asset.field_type = 'CALLOUT' AND asset.id IN (<asset_id_alvo>)
```

CAMPAIGN:
```
SELECT campaign.name, campaign_asset.status, asset.id
FROM campaign_asset
WHERE campaign_asset.field_type = 'CALLOUT' AND asset.id IN (<asset_id_alvo>)
```

AD_GROUP:
```
SELECT ad_group.name, ad_group_asset.status, asset.id
FROM ad_group_asset
WHERE ad_group_asset.field_type = 'CALLOUT' AND asset.id IN (<asset_id_alvo>)
```

*(Substituir `<asset_id_alvo>` pelo ID real aplicado em T4. A camada de conta é a que este branch inteiro existe para tornar visível — se T4 escolheu um link CUSTOMER, a query de `campaign_asset` sozinha devolve ZERO linhas, o que pareceria falha mas é só a tabela errada.)*

**Expected result (exemplo para o `level` CAMPAIGN — as outras duas trocam a coluna de nome e a tabela, mesma forma):**

```
campaign.name | campaign_asset.status | asset.id
----|---|----
"Campanha X" | "REMOVED" | "<asset_id_alvo>"
(zero ou mais linhas adicionais se o asset estava vinculado em múltiplas entidades do mesmo nível)
```

**Validação (crítica):**

- [ ] Query executa sem erro GAQL (a do `level` escolhido em T4 — CUSTOMER, CAMPAIGN ou AD_GROUP)
- [ ] **Crítico T5:** `<nível>_asset.status == "REMOVED"` (a coluna correspondente — `customer_asset.status`, `campaign_asset.status` ou `ad_group_asset.status`) para a linha com `asset.id == <asset_id_alvo>` (não null, não "PAUSED")
- [ ] Se o vínculo existia em múltiplas entidades do mesmo nível (várias campanhas para CAMPAIGN, vários ad_groups para AD_GROUP), **TODAS** têm `status: REMOVED` (confirmação completa); CUSTOMER tem no máximo uma linha por `asset.id`+`field_type`, então essa checagem não se aplica a ela
- [ ] Nenhuma linha com `status: "ENABLED"` para o asset ID alvo, na tabela do nível escolhido (não há "link fantasma" parcial)
- [ ] Documentar a medição explicitamente para prova futura

**Failure modes investigation:**

- Query não retorna linhas → tabela errada pro `level` escolhido em T4 (ex.: rodou `campaign_asset` pra um link CUSTOMER); confira contra as três queries acima antes de tratar como falha
- Aparece linha com `status: "ENABLED"` ainda → aplicação parcial falhou (finding crítica: mutation inconsistent)
- `status` é `"PAUSED"` em vez de `"REMOVED"` → bug envelope não aplicou a ação correta

**Result:** ⬜ pending

---

## Teste T6 — Reaplica `remove_asset_link` idêntico — mint de novo token

**Setup:** Validar idempotência. Chamar `remove_asset_link` de novo com o **mesmo** `links` array de T4 (o vínculo já foi removido em T4b). `remove_asset_link` não olha o estado atual do vínculo antes de gerar o preview — não há pré-flight nenhum sobre status em `src/mcp/tools/remove_asset_link.py`, então esta chamada por si só é sempre um dry-run limpo, igual T4. A idempotência de verdade só é exercida em **T6b**, quando o token é consumido contra o Google Ads.

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

*(Substituir pelos mesmos valores de T4 — mesmo `level` e `resource_name`)*

**Expected response shape:** idêntico ao de T4 (mesmo `blast_summary`, `confirmation_reason` e `target_count`, já que os `links` de entrada são os mesmos) — só `confirmation_token` muda, porque é um preview novo. `expires_in_minutes` **não varia**: é a constante `DEFAULT_TTL_MINUTES` (10, ver `src/mcp/tools/_mutate_common.py`), igual em T4 e T6 — a validação de T4 já afirma isso corretamente (linha 360 deste documento); esta linha só alinha com aquela.

**Validação:**

- [ ] `status == "dry_run"` (mesmo caminho de T4 — não existe branch que detecte "já removido" antes do preview)
- [ ] `confirmation_token` é um valor **novo**, diferente do token de T4 (aquele já foi consumido em T4b — `consume()` marca `consumed_at`; reusar o mesmo token dá `InvalidTokenError`, ver `src/governance/dry_run.py`)
- [ ] `blast_summary`, `confirmation_reason` e `target_count` idênticos aos de T4 (mesma entrada `links`, mesma lógica determinística)

**Failure modes investigation:**

- Chamada retorna erro em vez de um novo preview → regressão: `remove_asset_link` passou a inspecionar estado prévio, o que a spec §6 não pede e este teste não cobre
- `confirmation_token` igual ao de T4 → colisão do gerador aleatório (`36^8` de espaço — extremamente improvável) ou bug de cache

**Result:** ⬜ pending

---

## Teste T6b — `apply_change` do token de T6 — idempotência contra o Google Ads

**Setup:** Consumir o token de T6. Esta é a chamada que de fato re-executa a remoção do MESMO vínculo já removido em T4b — é aqui, não em T6, que a idempotência é exercida de verdade. `remove_asset_link` grava `__partial_failure__: True` no payload (igual T4/T4b), então `run_mutation` chama `GoogleAdsService.mutate` com `request.partial_failure = True`: uma operação individual que falhar (ex.: o vínculo não existe mais) não derruba a chamada inteira nem levanta exceção — ela só aparece como um item `"failed"` dentro de `partial_failure_error`, que `apply_change` **não repassa ao chamador**: `run_mutation` devolve `partial_failures` no seu próprio dict de retorno, mas o dict que `apply_change` de fato retorna ao MCP caller só usa `provider_request_id`, `applied_count` e `resource_names` daquele resultado — `partial_failures` é descartado nessa borda (ver `src/mcp/tools/apply_change.py` linhas 129-137). Por isso não dá para prever aqui se `applied_count` vem `0` (Google recusou a operação individual) ou `1` (Google tratou como no-op silencioso) — os dois são aceitáveis. O que não é aceitável é `status: "error"` no envelope.

**Tool call:**

```
apply_change(
  confirmation_token="<token de T6>"
)
```

*(Substituir `<token de T6>` pelo valor exato retornado em T6 — NÃO o token de T4, que já foi consumido)*

**Expected response shape:** igual ao de T4b em formato (mesmas 7 chaves), com `applied_count` podendo ser `0` ou `1` — não é previsível de antemão.

**Validação:**

- [ ] Response não é `{"status": "error", ...}` (essa é a única forma de erro que este domínio expõe ao chamador — não há código HTTP tipo 400/409/422 nesta camada; um erro real vem como `error_message` em português via `to_friendly`)
- [ ] **Crítico T6b:** `status == "applied"` (o `partial_failure=True` faz o Google devolver sucesso na chamada mesmo que a operação individual tenha sido recusada — ver Setup acima)
- [ ] `applied_count` é `0` ou `1` — qualquer um dos dois é PASS; não trate um valor específico como esperado
- [ ] **Crítico T6b (prova real):** re-query GAQL (repetir a query de T5) devolve `status: REMOVED` para o `asset.id` alvo — o vínculo continua removido, não voltou a `ENABLED`
- [ ] Nenhuma entry em `audit_log` documenta `already_removed` — esse rótulo só existe em `remove_audience.py` (`_classify_partial`); `remove_asset_link.py` não implementa mapeamento por-linha equivalente, então não procure por ele

**Failure modes investigation:**

- `status: "error"` com token inválido/expirado → mais de 10 minutos entre T6 e T6b, ou ordem de execução errada
- Re-query GAQL mostra `status: ENABLED` → a "idempotência" na verdade recriou o vínculo (bug grave: `remove_asset_link` deveria ser puramente destrutivo, nunca recriar)
- `status: "error"` com mensagem PT-BR do Google → `to_friendly` traduziu uma falha real da API (não confundir com sucesso parcial, que não levanta exceção)

**Result:** ⬜ pending

---

## Teste T7 — `account_frontier` é a fronteira da CONTA (F131, mesmo release)

**Por que está neste runbook:** o F131 shippou no mesmo PR das tools de asset. Não é sobre assets, mas é sobre o mesmo deploy, e a asserção precisa de conta real.

**Setup:** `get_change_history` e `detect_drift` devolvem `freshness.account_frontier`, que deve ser o evento mais recente indexado **na conta**, independente da janela consultada. A primeira versão herdava a janela do usuário: consultar 31/08–01/09 devolvia fronteira 31/08 e `status: atrasado` com a conta indexada até 02/09, e o warning disparava em toda janela terminando em dia sem write.

**Passo 1 — a fronteira não varia com a janela.** Duas chamadas, uma terminando em dia **com** atividade e outra em dia **sem**:

```
get_change_history(customer_id="7862230676", date_range="TODAY", limit=1)
get_change_history(customer_id="7862230676", start_date="2026-08-31", end_date="2026-09-01", limit=1)
```

- [ ] `account_frontier` **idêntico** nas duas. Se variar, está filtrado pela janela.
- [ ] `slice_frontier` **difere** entre elas — é o campo que deve acompanhar a janela, e é essa a diferença entre os dois.
- [ ] `status: confiavel` e `warning: null` nas duas, quando a conta está em dia.

**Passo 2 — a fronteira é o máximo real, com tolerância.** Rode o `MAX` por GAQL **primeiro**, a tool **depois**:

```
SELECT change_event.change_date_time FROM change_event
WHERE change_event.change_date_time BETWEEN '<hoje-28>' AND '<hoje+1>'
ORDER BY change_event.change_date_time DESC LIMIT 1
```

- [ ] `account_frontier` **>= (MAX − 120s)**.

🔴 **Não asserte igualdade estrita.** As duas consultas não são simultâneas: qualquer write no intervalo, ou deriva de propagação do lado do Google, faz os valores discordarem por segundos **sem que haja defeito**. Igualdade estrita transforma isso em falha de teste — e asserção flaky é reprovada, investigada, não reproduzida e no fim ignorada, perdendo-se justamente a checagem de corretude. Rodar o `MAX` antes põe a deriva na direção benigna: evento novo no intervalo só faz a tool ver **mais**, nunca menos.

O que esta asserção precisa pegar é fronteira **filtrada pela janela** (erra por dias) e fronteira **estagnada** (erra por sempre). Discordância de segundos não é o alvo.

**Failure modes:**
- `account_frontier` diferente entre as duas janelas → a sonda voltou a herdar filtro do chamador.
- `account_frontier` muito abaixo do `MAX` (minutos ou mais) → sonda estagnada, ou janela própria estreita demais.
- `status: atrasado` em janela cujo último dia simplesmente não teve write → é o bug original reincidindo; confira por GAQL se o dia teve atividade antes de reportar.

**Resultado:** ⬜ pending

---

## Resultado final (após execução futura)

```
SMOKE 3b.41 assets: 0/8 PASS (não executado — bloqueadores 1 e 2 impedem)
Data de execução: <preencher após bloqueadores removidos e aprovação Wellington>
F-findings novos: <preencher durante execução — esperado ZERO>
```

---

## Notas operacionais pós-execução

🔴 **Antes de tentar: reconecte o MCP.** O catálogo de tools é negociado no **handshake**. Sessão aberta antes do deploy segue com a lista antiga, e o sintoma é a tool **"não existir"** — busca por nome exato e por keyword não acham —, não um erro que mencione deploy ou versão. Aconteceu com duas sessões em 02/09, com o servidor já servindo 66 tools (F140).

🔴 **O passo de mutação pode barrar antes de chegar no MCP.** A primeira tentativa do `remove_asset_link` em 02/09 foi bloqueada pelo **classificador de auto mode do Claude Code**, não pelo gate do MCP nem pelo Google — e o erro não menciona nenhum dos dois. Se acontecer: pare e leve ao dono do repo em vez de contornar. Naquele caso ele confirmou que a conta era de teste dele e autorizou.

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
