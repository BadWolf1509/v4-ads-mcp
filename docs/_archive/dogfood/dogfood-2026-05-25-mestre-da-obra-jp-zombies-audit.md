# Dogfood 2026-05-25 — Mestre da Obra JP (`7862230676`) — sessão D+14 gate cleanup + zombies audit + descoberta órfãs ad_groups REMOVED

**Operator:** Claude Code (Sonnet 4.7) em sessão dirigida por wellinton.ribeiro@v4company.com
**Account:** `7862230676` — Mestre da Obra JP+CAB
**Window:** Mix baseline 12-18/05 (7d pré-cleanup) vs preview 19-25/05 (7d pós-cleanup) + change_history LAST_30_DAYS
**Goal:** Sessão D+14 do launch (D+7 pós-cleanup 19/05). 3 frentes: (1) gate validação cleanup com leitura completa CPC+conv+drift, (2) audit keywords zumbis com tool nova `audit_zombie_keywords`, (3) preparação B1.6 cleanup zumbis com investigação prévia que REVELOU 60% das zumbis identificadas eram órfãs cosméticas em ad_groups REMOVED. 9+ tools v4-ads exercitadas em fluxo READ-ONLY.

**Referência:** complementa [`dogfood-2026-05-19-mestre-da-obra-jp-cleanup-massivo.md`](./dogfood-2026-05-19-mestre-da-obra-jp-cleanup-massivo.md) e [`dogfood-2026-05-21-mestre-da-obra-jp-drift-detection.md`](./dogfood-2026-05-21-mestre-da-obra-jp-drift-detection.md). Esta sessão **confirma 4 tools sugeridas no dogfood 21/05 que foram implementadas** + descobre **pegadinha NOVA** que merece atenção.

## ✅ Tools sugeridas em dogfoods anteriores que foram IMPLEMENTADAS

Reconhecimento ao time V4-ads MCP — entre 21/05 e 25/05 foram adicionadas as 4 tools que estavam no roadmap dos dogfoods anteriores:

| Tool | Sugerida em | Status | Validada nesta sessão |
|---|---|---|---|
| `mcp__v4-ads__detect_drift` | Dogfood 21/05 W1 (ICE 486) | ✅ Implementada | ✅ Usada 22/05 + 25/05 — funcionou perfeitamente. Descrição já incorpora pegadinha latency |
| `mcp__v4-ads__audit_goal_attribution` | Dogfood 21/05 W3 (ICE 360) | ✅ Implementada | ✅ Usada 22/05 — confirmou lição 47 + lista 13 equipamentos B2 |
| `mcp__v4-ads__audit_orphan_smart_actions` | Dogfood 19/05 | ✅ Implementada | ✅ Disponível (não usada nesta sessão por escopo) |
| `mcp__v4-ads__audit_zombie_keywords` | Dogfood 19/05 | ✅ Implementada | ✅ Usada 25/05 — **descobriu pegadinha nova B6 abaixo** |

## ⚠️ Itens dogfood anterior ainda PENDENTES (não vistos como implementados)

| Item | Origem | Status hoje |
|---|---|---|
| **G1** — `get_conversion_actions` retornar `primary_for_goal` + `include_in_conversions_metric` | Dogfood 21/05 (ICE 720, quick win sprint atual) | ✅ **Já shipped Sprint 3b.32 task T1** (commit pré-25/05). Field presente em `get_conversion_actions` (linhas 37-38) E em `audit_goal_attribution.origin_summary[*].primary_actions[*].include_in_conversions_metric`. Observação imprecisa do dogfood — não chamei `get_conversion_actions` direto, vi via `audit_goal_attribution` context que expõe os mesmos fields. **Atualização confirmada lendo código.** |
| **B1** description update — `get_change_history` latency horas | Dogfood 21/05 (ICE 700, quick win) | ✅ Aplicado (description nova reflete) → **refinado Sprint 3b.38** pra "DIAS" (>4 dias) baseado em medição empírica 25/05 |
| **UX2** — exemplo dry-run+confirm em `update_conversion_action` description | Dogfood 21/05 (ICE 600, quick win) | ❓ Não validado (não usei tool nesta sessão) — task #77 marca como shipped Sprint 3b.32 T3 |

## ✅ Sprint 3b.38 shipped same-day (25/05) baseado neste dogfood

| Item | Severity | Ship status |
|---|---|---|
| **B6 → F52** — `audit_zombie_keywords` adiciona `ad_group_status` field + description warning (Opção C) | HIGH | ✅ Shipped 3b.38: `flag_zombie_keywords.py` (KeywordRow + ZombieKeyword) + `audit_zombie_keywords` query/parser + tool response + 3 regression tests (DELL/GPA cenário) |
| **B7 → F23 promoted** — `get_change_history` LAST_30_DAYS clamp pra today-28 + warning na response | MEDIUM | ✅ Shipped 3b.38: `get_change_history.py` post-resolve clamp (apenas quando preset usado — custom dates honram intent) + `date_range_warning` field + 2 regression tests (clamp + no-warning negative). F23 promoted "known limitation" → "fixed" no findings-catalog |
| **B1 refino** — description `get_change_history` "HORAS" → "DIAS" | MEDIUM | ✅ Shipped 3b.38: docstring caveat + description string editados pra "DIAS (>4 dias já visto em produção — dogfood 25/05 MO-JP)" |
| **Lição V4 48 (P4) catalogada** | — | ✅ Adicionada como Lessons reinforced #7 em findings-catalog.md ("Audit tools devem expor status do parent resource") |

## Read tools exercitadas

1. `get_campaign_performance` ✅ (1 call — janela 19-25/05)
2. `validate_gaql` ✅ (~3 calls)
3. `run_gaql` ✅ (~6 calls — campaign, ad_group, conversion_action)
4. `get_change_history` ✅ (1 call — falhou com erro "start date too old" 30d)
5. **`audit_zombie_keywords`** ✅ (1 call — 280 zombies retornadas, descobriu pegadinha B6)
6. **`detect_drift`** ✅ (1 call — 0 drift novo, 64 changes totais autorizados)
7. (anteriores) `mcp__v4-ads__get_conversion_actions` ✅ (visto em audit_goal_attribution context)

## Write tools exercitadas

**Zero writes nesta sessão** (sessão de gate + investigação). Próximo write planejado: B1.6 27/05 (PAUSE batch 110 keywords via `update_keyword_status`).

## Bugs / pegadinhas encontradas

### B6 (NOVA): `audit_zombie_keywords` NÃO filtra `ad_group.status` — 60% dos zumbis podem ser órfãos cosméticos (HIGH)

**Sintoma:** `audit_zombie_keywords(LAST_30_DAYS, limit=1000)` retornou 280 keywords zumbis. Investigação cross-check via `SELECT ad_group.id, ad_group.status FROM ad_group WHERE campaign.id IN (...)` revelou que **2 dos 11 ad_groups com zumbis estavam REMOVED**:

- `DELL` (JPA): 93 zumbis ENABLED em ad_group REMOVED
- `[GPA][02][ANDAIME]` (CAB): 77 zumbis ENABLED em ad_group REMOVED
- **Total**: 170 das 280 zumbis (60,7%) eram órfãs cosméticas — keywords ENABLED dentro de ad_group REMOVED não competem em leilão, não impactam Quality Score nem Smart Bidding

**Impacto na sessão:** se eu tivesse aplicado PAUSE batch das 280 sem investigar, teria executado 170 operações no-op (sem impacto técnico). Pior — narrativa pro cliente teria sido "pausei 280 keywords" quando na verdade só 110 importavam. Hipótese inicial "DELL contamina QS JPA = causa raiz regressão conv" também caiu (DELL REMOVED não pode contaminar).

**Server-side filters atuais da tool** (corretos):
- `keyword.status = ENABLED` ✅
- `keyword.negative = FALSE` ✅ (lição V4 43 coberta — bom!)

**Filter ausente**:
- `ad_group.status = ENABLED` ❌

**Sugestão de fix opções**:

**Opção A — Filtrar server-side adicionar `ad_group.status = ENABLED`** (mais agressivo):
```python
# JOIN com ad_group.status na query GAQL underlying
WHERE ad_group_criterion.status = ENABLED
  AND ad_group_criterion.negative = FALSE
  AND ad_group.status = 'ENABLED'  # NOVO
```
Pro: limpo, default V4 ideal.
Contra: usuário pode legitimamente querer ver órfãs pra inventário.

**Opção B — Adicionar flag `include_orphans_in_removed_ad_groups=False` default** (mais flexível):
```python
audit_zombie_keywords(
    customer_id="...",
    include_orphans_in_removed_ad_groups=False  # NOVO, default False
)
```
Pro: backward-compat + opção pra inventário cosmético.
Contra: mais complexo.

**Opção C — Adicionar `ad_group.status` na response** (mínimo invasivo):
```json
{
  "ad_group_id": "...",
  "ad_group_name": "DELL",
  "ad_group_status": "REMOVED",  # NOVO
  ...
}
```
Pro: dado disponível, consumer filtra. Zero breaking change.
Contra: usuário precisa lembrar de filtrar.

**Recomendação V4: Opção C como mínimo + atualizar description avisando** ("zumbis incluem keywords em ad_groups REMOVED — filtre pelo campo `ad_group_status='ENABLED'` pra cleanup de impacto técnico real, ou mantenha tudo pra inventário cosmético").

**Severity:** HIGH — sem isso, gestor pode aplicar batch errado e pensar que limpou problema que não existia. Risco de overcommit em narrativa cliente.

### B1 (RECONFIRMADA): `get_change_history` continua com latência **horas** vs estado API real

Sessão 25/05 reconfirmou pegadinha do dogfood 21/05 B1. Mais 4 dias após reverts Pedro (21/05 → 25/05): `get_change_history` 21/05 hoje continua mostrando apenas 1 dos 4 reverts originais (os outros 3 ainda em latency >4 dias!).

**Atualização para 21/05 dogfood B1**: latência confirmada não é "horas" — pode chegar a **dias** em mudanças via UI. Description atual menciona "lag até HORAS" mas medição real é >4 dias em alguns casos.

**Sugestão refinada**: atualizar description pra "lag até DIAS em alguns casos — sempre cruzar com `run_gaql FROM campaign` pra estado atual".

### B7 (NOVA): `get_change_history` falha silenciosa em janelas > 30d (MEDIUM)

**Sintoma:** Tentei `get_change_history(date_range=LAST_30_DAYS, resource_types=["AD_GROUP"])` pra investigar origem do DELL ad_group (legacy, criado provavelmente >30d atrás):

```
Error: Google Ads retornou: The requested start date is too old. It cannot be older than 30 days.
```

Erro genérico Google API — mas tool aceita `LAST_30_DAYS` no preset. O limite Google é 30 dias **exclusivos** (não-inclusivos). Se hoje é 25/05 e janela LAST_30_DAYS calcula 25/04, a Google API rejeita.

**Workaround:** usar `start_date='2026-04-26'` + `end_date='2026-05-25'` explícito (29 dias).

**Sugestão de fix:** tool poderia detectar erro Google + sugerir ajuste automático pra `LAST_29_DAYS` ou similar. Alternativa: documentar limite "27-28 dias seguros" no description (evitar borda).

**Severity:** MEDIUM — UX confusa (preset oferecido mas API rejeita).

## Padrões V4 novos descobertos

### P4 (NOVA): Pre-batch sempre validar status do parent resource

**Lição V4 48** (documentada em [`02-ROADMAP.md`](D:/Gestor de Tráfego de Ads/clientes/Mestre da Obra/João Pessoa/02-ROADMAP.md) MO):

> Antes de criar batch grande baseado em `audit_*` tool, validar status do **parent resource** (ad_group pra keywords, campaign pra ad_groups). Audit tools focam no resource específico mas podem retornar items "órfãos" tecnicamente — operação batch neles é no-op + infla narrativa pro cliente.

**Aplicação concreta**:
- `audit_zombie_keywords` → validar `ad_group.status = ENABLED`
- `audit_orphan_smart_actions` → validar nada (conversion_action é top-level)
- `audit_zombie_ad_groups` (se existir) → validar `campaign.status = ENABLED`

**Generalização cross-cliente**: aplicar pra qualquer audit V4 que tenha hierarquia parent-child.

### P5 (REFORÇADA): Regressão em ad_group após cleanup pode ser COMPORTAMENTO ESPERADO, não bug

Drill-down JPA por ad_group revelou:
- `[GPA][01][GERAL]` (catch-all): −42% clicks / −46% conv ❌
- `[GPA][03][ANDAIME]`: +93% clicks / +85% conv ⭐
- `[GPA][06][GERADORES]`: CVR de 5,9% pra 25,0% ⭐ (cirurgia funcionou)
- `[GPA][02][BETONEIRA]`: saiu de 0 conv → 3 conv ⭐
- `[GPA][04][MARTELETE]`: saiu de 0 conv → 2 conv ⭐

**Padrão**: Smart Bidding redistribuiu budget de catch-all (que pegava traffic baixa qualidade) pros ad_groups segmentados que melhoraram. CVR total se manteve.

**Lição operacional**: ao detectar regressão num ad_group "geral" pós-cleanup, drill-down comparar TODOS ad_groups da campaign antes de assumir bug — pode ser comportamento esperado de melhoria estrutural.

## Priorização ICE — itens 25/05 + status anteriores

| # | Item | I | C | E | ICE | Status |
|---|---|---|---|---|---|---|
| **B6** | `audit_zombie_keywords` adicionar `ad_group_status` na response (Opção C) | 8 | 10 | 9 | **720** | NOVO — Quick win sprint atual |
| **G1** | `get_conversion_actions` retornar `primary_for_goal` + `include_in_conversions_metric` | 8 | 10 | 9 | **720** | Pendente desde 21/05 |
| **B1 refino** | description `get_change_history` "lag até DIAS" (não horas) | 6 | 10 | 10 | **600** | Refino quick |
| **B7** | `get_change_history` LAST_30_DAYS borda 30d exclusiva | 5 | 9 | 9 | **405** | NOVO — Quick win |
| **W3 ext.** | `audit_goal_attribution` retornar `campaign_attribution` (X de Y campanhas) | 7 | 8 | 5 | **280** | Extensão da já-entregue |

**Quick wins recomendados sprint atual**:
1. **B6 Opção C** — adicionar 1 field na response (~1h dev + test) — ICE 720
2. **G1** — adicionar 2 fields na response `get_conversion_actions` (~1h) — ICE 720
3. **B1 refino** — update string description (~10 min) — ICE 600

## Anexo — IDs e descobertas relevantes 25/05

- Account: `7862230676`
- **Ad_groups REMOVED descobertos** (parent de órfãos cosméticos):
  - `174842025340` DELL (JPA) — 93 órfãs
  - `176527557000` `[GPA][02][ANDAIME]` (CAB) — 77 órfãs
  - `179099118445` `Grupo de anúncios 5` (CAB) — 0 órfãs no audit (já vazio)
- **Zumbis reais B1.6** (em ad_groups ENABLED): 110 keywords em 9 ad_groups
- Gate D+14 leitura: CPC JPA −26% / CPC CAB −13% / WA-CAB curva positiva confirmada / 0 drift novo
- Próximo: B1.6 27/05 (PAUSE 110 keywords) → B2 02/06 (Opção C + 13 equipamentos Primary)

---

*Produzido por Claude Code 2026-05-25 em sessão D+14 MO-JP+CAB. Lição V4 48 nova originada desta sessão registrada em [`02-ROADMAP.md`](D:/Gestor de Tráfego de Ads/clientes/Mestre da Obra/João Pessoa/02-ROADMAP.md) do cliente. Reconhecimento ao time V4-ads MCP pela entrega das 4 tools sugeridas em dogfoods anteriores entre 21/05 e 25/05 — ciclo de feedback funcionou.*

---

**Update 2026-05-25 pós-publicação:** Sprint 3b.38 shipped same-day — F52 (B6) + F23 fix (B7) + B1 refino + Lição V4 48 catalogada. Ciclo dogfood → ship em ~2h. Ver tabela "Sprint 3b.38 shipped same-day" acima. Smoke real de F52 + F23 fix pendente próxima sessão dogfood — natural validation quando Wellington próximo cleanup ou check de change_history.
