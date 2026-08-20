# Dogfood 2026-05-21 — Mestre da Obra JP (`7862230676`) — sessão D+9 drift detection + Frente 3 reavaliada

**Operator:** Claude Code (Sonnet 4.7) em sessão dirigida por wellinton.ribeiro@v4company.com
**Account:** `7862230676` — Mestre da Obra JP+CAB
**Window:** Janelas customizadas 12-18/05 (baseline pré-cleanup) vs 19-21/05 (preview pós-cleanup) + change_history 20-21/05
**Goal:** Sessão D+9 do launch. Investigação drop conv CAB −79% que descobriu: (1) auto-deleção conversion action ghost pós-REMOVE Smart Campaign, (2) mudanças não-coordenadas de outro gestor V4 interno (Pedro Vytor) 20/05 → revert total 21/05, (3) reavaliação Frente 3 (Secondary→Primary) revelou premissa "cosmético KPI" era falsa. 8+ tools v4-ads exercitadas em fluxo READ-ONLY (zero writes Google, apenas investigação + GAQL pra confirmação de revert).

**Referência:** complementa [`dogfood-2026-05-19-mestre-da-obra-jp-cleanup-massivo.md`](./dogfood-2026-05-19-mestre-da-obra-jp-cleanup-massivo.md). Vários achados convergem com aquele report — destaque pra B1 (latency `get_change_history`) que confirma sintomas mencionados no B2 anterior.

## Read tools exercitadas

1. `get_campaign_performance` ✅ (2 calls — janelas custom 12-18/05 + 19-21/05, status='all')
2. `validate_gaql` ✅ (~8 calls — alta cadência)
3. `run_gaql` ✅ (~14 calls — múltiplos resources: campaign, ad_group, conversion_action, customer_conversion_goal, change_event)
4. `get_change_history` ✅ (4 calls — 19-21/05, 20-21/05, 21/05, com/sem filtros)
5. `get_conversion_actions` ✅ (1 call — 43 actions retornadas)
6. `list_gaql_resources` ✅ (1 call)
7. (ERP fora-MCP) `mcp__empsis__consulta_livre_select` ✅ (2 calls — cross-check leads reais CAB+JP)
8. (ERP fora-MCP) `mcp__empsis__listar_tabelas` ✅ (3 calls — schema discovery)

## Write tools exercitadas

**Zero writes nesta sessão** (apenas read+investigação). Mudanças Google foram feitas via UI por Wellington/Pedro (revert AI Max + TEXT_ASSET_AUTOMATION + messaging_restriction). MCP write tools NÃO cobrem campos `ai_max_setting`/`asset_automation_settings`/`text_guidelines.messaging_restrictions`.

## Bugs / pegadinhas encontradas

### B1: `get_change_history` tem latência **horas** vs estado API real (MEDIUM)

**Sintoma:** Wellington + Pedro fizeram 3-4 mudanças via UI hoje 21/05 (~13h-15h): AI Max OFF em ambas campanhas, TEXT_ASSET_AUTOMATION OPTED_OUT em ambas, messaging_restriction "não adicionar nomes de concorrentes" REMOVIDA em ambas.

Chamadas:
```
get_change_history(start_date=2026-05-21, end_date=2026-05-21) → 0 rows
get_change_history(start_date=2026-05-20, end_date=2026-05-21) → 4 rows (só do dia 20 Pedro Vytor)
```

Estado real via GAQL leading indicator:
```
run_gaql("SELECT campaign.ai_max_setting.enable_ai_max FROM campaign WHERE campaign.id IN ...")
→ enable_ai_max: false (revertido)

run_gaql("SELECT campaign.asset_automation_settings FROM campaign WHERE campaign.id IN ...")
→ TEXT_ASSET_AUTOMATION: OPTED_OUT (revertido)

run_gaql("SELECT campaign.text_guidelines.messaging_restrictions FROM campaign WHERE campaign.id IN ...")
→ campo não retornado (vazio = removido)
```

**Latência confirmada**: >3 horas entre mudança UI e indexação no `change_event` audit log. Description atual da tool menciona "campaign.status pode lagar alguns minutos" — mas neste caso são **horas**, não minutos, e afeta MÚLTIPLOS campos (não apenas status).

**Impacto na sessão:** confusão inicial sobre se mudanças tinham sido aplicadas. Forçou cross-check via GAQL FROM campaign pra validar estado real. Em workflow audit pós-batch, gestor pode achar que revert não aconteceu e re-aplicar mudanças → race condition.

**Sugestão de fix:**

a) **Atualizar description** da tool `get_change_history` pra mencionar latência real (horas, não minutos):

```python
# Adicionar na description:
"""
NOTA UX CRÍTICA: change_event tem latência de indexação que pode chegar a HORAS
após mudança ser aplicada via UI ou API. Pra validar estado atual de campaign
(incluindo confirmar revert), use `run_gaql FROM campaign` como leading indicator —
esta tool é audit log lagging. Padrão V4: cross-check ambos quando timing é crítico.
"""
```

b) **Tool nova `verify_campaign_state(campaign_id, expected_fields)`** que cruza ambos automaticamente — leading (GAQL FROM campaign) + lagging (change_event) e retorna diff + warning de latência.

**Severity:** MEDIUM. Não bloqueia mas pode levar a conclusões erradas em workflows audit pós-batch crítico (incidentes, reverts, drift detection).

### B2: `get_change_history` rejeita `resource_types: ["CONVERSION_ACTION"]` (LOW)

**Sintoma:**
```
get_change_history(customer_id=..., resource_types=["CONVERSION_ACTION"])
→ "Google Ads retornou: Invalid enum value cannot be included in WHERE clause: 'CONVERSION_ACTION'."
```

Tool schema mostra `CONVERSION_ACTION` como valor aceito no enum `resource_types`, mas Google Ads API recusa essa filtragem específica em `change_event.change_resource_type`. Enum oficial Google é mais limitado que o exposto pela tool.

**Workaround:** chamar sem `resource_types` (retorna tudo) e filtrar client-side.

**Sugestão de fix:** ou (a) remover CONVERSION_ACTION do enum se realmente não é aceito pela API change_event, ou (b) detectar e fazer client-side filter no MCP server.

**Severity:** LOW — workaround simples mas confunde quem lê o schema.

### B3: GAQL `LIKE 'X' OR LIKE 'Y'` rejeitado (LOW)

**Sintoma:**
```sql
SELECT ... FROM conversion_action 
WHERE conversion_action.name LIKE '%onversa%' OR conversion_action.name LIKE '%hatsapp%'
→ "Google Ads retornou: Error in query: unexpected input OR."
```

GAQL não suporta operador OR em LIKE. Tive que rodar 2 queries separadas pra buscar "Conversation started" + "Whatsapp".

**Workaround:** queries separadas ou usar IN com nomes exatos.

**Sugestão de fix:** `validate_gaql` poderia detectar `LIKE ... OR LIKE` antes do API call e sugerir IN ou queries separadas.

**Severity:** LOW — GAQL limitation conhecida do Google.

## Gaps de tool curada

### G1: `get_conversion_actions` omite `primary_for_goal` + `include_in_conversions_metric` (HIGH)

**Sintoma:** A tool retorna 43 conversion actions com fields: `id, name, status, category, type, counting_type, attribution_model, default_value_brl, always_use_default_value`. **NÃO retorna**:
- `primary_for_goal` — flag crítica pra Smart Bidding optimization
- `include_in_conversions_metric` — flag crítica pra dashboard "Conversions" metric

Pra fazer audit de conversion actions (incluindo Frente 3 desta sessão Secondary→Primary), tive que fazer GAQL custom:

```sql
SELECT conversion_action.id, conversion_action.name, conversion_action.type, 
       conversion_action.category, conversion_action.status, 
       conversion_action.primary_for_goal, conversion_action.include_in_conversions_metric
FROM conversion_action WHERE conversion_action.status = 'ENABLED'
```

**Impacto na sessão:** ~5 min extra rodando GAQL pra obter campos que deveriam estar na tool curada. Não-trivial pra usuário menos técnico que não saberia GAQL.

**Sugestão de fix:** adicionar `primary_for_goal` + `include_in_conversions_metric` à response da tool curada. São fields críticos pra qualquer audit + decisão de mudança.

**Severity:** HIGH — bloqueia uso ergonômico da tool curada pra audit de conversion actions, força fallback pra GAQL.

### G2: `list_gaql_resources` não inclui `change_event` no catálogo (LOW)

**Sintoma:** Pra fazer query `change_event` com `old_resource` + `new_resource` pra ver detalhe das mudanças Pedro Vytor 20/05, tive que adivinhar nomes de fields (`change_event.change_resource_type`, `change_event.change_date_time`, etc) — não estão listados em `list_gaql_resources`.

**Impacto:** descoberta por tentativa+erro. Funcionou mas perdi tempo de validação.

**Sugestão de fix:** adicionar `change_event` ao catálogo `list_gaql_resources` retornado, talvez com nota "Prefira `get_change_history` pra casos simples. Use direto em GAQL pra acessar old_resource/new_resource com detalhe field-level."

**Severity:** LOW — descoberta possível mas frictional.

## Tools curadas sugeridas (workflows V4 descobertos)

### W1: `detect_drift(customer_id, since_timestamp, exclude_user_emails=[])` — drift detection pós-batch (HIGH valor)

**Padrão V4 identificado (lição 46 do MO)**: Após batch estrutural V4, auditar change_event 24-48h pra detectar mudanças não-coordenadas de **outros gestores V4** ou usuários externos com acesso.

Workflow manual atual:
1. `get_change_history` últimas 24-48h
2. Filtrar `user_email ≠ gestor_responsável`
3. Inspecionar manualmente cada change → reverter se inadequado

Tool sugerida:
```python
detect_drift(
    customer_id="...",
    since_timestamp="2026-05-19 18:00:00",   # após batch V4
    exclude_user_emails=["wellinton.ribeiro@v4company.com"]
) → {
    "total_drift_changes": 4,
    "by_user": {"pedro.vytor@v4company.com": 4},
    "by_resource_type": {"CAMPAIGN": 4},
    "changes": [...],
    "alert": "4 changes by non-responsible users detected.",
    "suggested_actions": ["Contact user / Validate authorization / Revert if needed"]
}
```

**Casos de uso V4:**
- Pós-batch (D+1 a D+2) — coordenação V4 interna (lição 46)
- Pós-incidente (account takeover) — auditoria de drift externo
- Auto-Apply Recommendations check — `client_type='GOOGLE_ADS_RECOMMENDATIONS_SUBSCRIPTION'`

**Severity:** HIGH valor — padrão V4 recorrente. Hoje exigiu workflow manual de ~10 min com várias queries.

### W2: `verify_campaign_state(campaign_id, expected_fields={})` — leading + lagging cross-check (MEDIUM valor)

**Padrão V4 identificado (pegadinha B1 desta sessão)**: pra validar revert/estado atual, sempre cruzar GAQL FROM campaign (leading) + get_change_history (lagging).

Tool sugerida:
```python
verify_campaign_state(
    campaign_id="22169885957",
    expected_fields={
        "ai_max_setting.enable_ai_max": False,
        "asset_automation_settings[TEXT_ASSET_AUTOMATION]": "OPTED_OUT"
    }
) → {
    "leading_state_via_gaql": {...},      # Real-time
    "lagging_state_via_change_event": {...}, # Audit log (pode lagar)
    "matches_expected": True,
    "drift_warning": null,
    "latency_warning": "change_event 0 rows for today — likely indexing lag. Trust leading state."
}
```

**Severity:** MEDIUM valor — pattern útil em revert/incident recovery.

### W3: `audit_goal_attribution(customer_id, category=None)` — pre-flight check antes de mexer em primary_for_goal (HIGH valor)

**Padrão V4 identificado (lição 47 desta sessão)**: `primary_for_goal=true` em action de categoria com `customer_conversion_goal.biddable=true` AFETA Smart Bidding, não é cosmético. Antes de propor mudança, cross-check é obrigatório.

Tool sugerida:
```python
audit_goal_attribution(
    customer_id="7862230676",
    category="CONTACT"   # opcional, padrão = all
) → {
    "category": "CONTACT",
    "origin_summary": {
        "WEBSITE": {
            "customer_conversion_goal_biddable": true,
            "primary_actions": [
                {"id": "...", "name": "Whatsapp - JPA", "include_in_conversions_metric": true},
                ...7 total
            ],
            "secondary_actions": [
                {"id": "...", "name": "Alisadora - JPA", "include_in_conversions_metric": false},
                ...13 total
            ],
            "warning": "biddable=true: promovendo Secondary→Primary AFETA Smart Bidding (não cosmético)"
        },
        ...
    },
    "campaign_attribution": {
        # Pra cada campaign: quais customer_conversion_goals estão atribuídos
        # via UI "X de Y campanhas" — cross-check da lição 41
    }
}
```

**Severity:** HIGH valor — evita decisão baseada em falsa premissa "cosmético KPI" (exatamente o caso de hoje).

## UX issues menores

### UX1: GAQL não retorna campos opcionais quando vazios

`messaging_restrictions` foi removido via UI. Query subsequente `SELECT campaign.text_guidelines.messaging_restrictions FROM campaign WHERE ...` retorna campanha **sem o campo** `text_guidelines` (não retorna `text_guidelines: {messaging_restrictions: []}`).

Comportamento padrão GAQL — campo opcional vazio sem default não vai na response. Pode confundir "removido" vs "não-existe ainda".

**Sugestão:** documentar como nota de UX em queries que envolvem fields opcionais (text_guidelines, asset_automation_settings, ai_max_setting). "Se campo não retornar, estado é vazio/null/default."

### UX2: `update_conversion_action` description menciona "preview com token" mas não documenta fluxo

```
"...batch > 1 OU primary_for_goal=False retorna preview com token..."
```

Não fica claro:
- Token vai onde? Re-enviar como parâmetro?
- Formato do `confirm_token`?
- Caminho exato pra applicar após preview

**Sugestão:** adicionar exemplo no description ou link pra padrão V4 de dry-run+confirm (`apply_change(token)` similar ao `create_rsa`/`update_keyword_status` batch).

## Padrões V4 reforçados nesta sessão

### P1: Cross-check ERP/CRM quando conv API despenca >50% (lição V4 45 nova)

Hoje, conv CAB despencou −79% no Google API. Hipótese natural: "tracking quebrado / marketing parou".

Cross-check ERP Empsis (mestrejoaopessoa, MCP `mcp__empsis__*`) revelou em 1 query SQL:
- JP: +35% volume de locações
- CAB: −20% volume mas +53% valor por locação

→ **Marketing NÃO parou, leads continuaram chegando** → drop conv é Google-side (atribuição/algoritmo), não comercial.

**Padrão V4 cravado**: drop conv API > 50% em conta com ERP/CRM acessível → cross-check antes de assumir tracking quebrado. Distingue 3 cenários:
- Leads OK = só Google (atribuição)
- Leads também caíram = problema comercial real
- Leads UP mas conv DOWN = só tracking (mais grave — algoritmo cego pra conversões reais)

### P2: REMOVE Smart Campaign cascateia auto-delete de conversion actions atreladas (lição V4 44 confirmada)

Smart Campaign `21362837957` foi REMOVED 19/05. Hoje 21/05 GAQL `WHERE conversion_action.name LIKE '%onversa%'` retornou ZERO rows — "Conversation started" action (que tinha 25 conv no baseline) **foi auto-deletada pelo Google** junto com a Smart Campaign owner.

Confirmação adicional: action sumiu do `get_conversion_actions` também. Nem como REMOVED — sumiu totalmente.

**Lição reforçada**: ao REMOVE Smart Campaign, esperar drop de conv attribution daquelas actions específicas (Click-to-Message/Local actions). Sinalizar como esperado, não como bug.

### P3: Coordenação V4 interna pós-batch (lição V4 46 nova)

Após batch V4 19/05, Pedro Vytor (V4 interno, não gestor anterior externo) ativou AI Max + TEXT_ASSET_AUTOMATION em 20/05 sem combinar com Wellington (gestor responsável).

**Sinais de mudanças não-coordenadas em change_event:**
- `user_email` diferente do gestor responsável
- Timestamp clusterizado em poucos segundos (compulsivo, tentativa de "compensar")
- `changed_fields` em features avançadas (AI Max, asset automation, messaging restrictions)

**Workflow V4 D+1 pós-batch**:
1. `get_change_history` últimas 24-48h
2. Filtrar `user_email ≠ gestor responsável`
3. Contactar autor V4 (se interno) pra alinhar + reverter se afeta o batch
4. Documentar processo combinado

## Priorização ICE — top achados 21/05

ICE Score = Impacto (1-10) × Confiança (1-10) × Esforço (1-10 invertido, 10 = muito fácil)

| # | Item | I | C | E | ICE | Prazo sugerido |
|---|---|---|---|---|---|---|
| **G1** | `get_conversion_actions` retornar `primary_for_goal` + `include_in_conversions_metric` | 8 | 10 | 9 | **720** | Quick win sprint atual |
| **W1** | `detect_drift` tool nova | 9 | 9 | 6 | **486** | Sprint próxima — alto valor |
| **W3** | `audit_goal_attribution` tool nova | 9 | 8 | 5 | **360** | Sprint próxima — pre-flight crítico |
| **B1** | Atualizar description `get_change_history` com nota de latência horas | 7 | 10 | 10 | **700** | Quick win sprint atual |
| **W2** | `verify_campaign_state` tool nova | 7 | 8 | 5 | **280** | Sprint+1 |
| **UX2** | Exemplo de fluxo dry-run+confirm em `update_conversion_action` description | 6 | 10 | 10 | **600** | Quick win sprint atual |
| **B2** | Schema enum `resource_types` em `get_change_history` validar CONVERSION_ACTION | 4 | 8 | 9 | **288** | Sprint+1 |
| **G2** | `change_event` em `list_gaql_resources` | 5 | 8 | 9 | **360** | Sprint+1 |
| **UX1** | Doc nota GAQL fields opcionais vazios | 4 | 9 | 10 | **360** | Quick win |
| **B3** | `validate_gaql` detectar LIKE OR LIKE | 3 | 8 | 8 | **192** | Sprint+2 |

**Quick wins recomendados** (ICE ≥ 600, esforço ≤ 1 dia cada):
1. **G1** — adicionar 2 fields na response do `get_conversion_actions` (ICE 720)
2. **B1** — update description `get_change_history` (ICE 700)
3. **UX2** — exemplo dry-run+confirm em description `update_conversion_action` (ICE 600)

**Investimento sprint+1** (ICE 300-500, esforço médio):
4. **W1** — `detect_drift` (ICE 486)
5. **W3** — `audit_goal_attribution` (ICE 360)
6. **G2 + UX1** — doc + catálogo updates (ICE 360 cada)

## Anexo — IDs e timestamps relevantes

- Account: `7862230676`
- Campanhas: JPA `21359547724` + CAB `22169885957` (ambas ENABLED)
- Pedro Vytor changes: 20/05 10:12:06 → 10:13:00 (4 mudanças em 54s, todas via GOOGLE_ADS_WEB_CLIENT)
- Revert: 21/05 ~13:xx-15:xx (não capturado por get_change_history até momento da auditoria)
- Conversion actions Secondary equipamentos identificadas (13): listadas em [`01-HISTORICO.md`](D:/Gestor de Tráfego de Ads/clientes/Mestre da Obra/João Pessoa/01-HISTORICO.md) entrada 21/05/2026 ACHADO 5

---

*Produzido por Claude Code 2026-05-21 em sessão D+9 MO-JP+CAB. Lições V4 45-47 originadas desta sessão registradas em [`02-ROADMAP.md`](D:/Gestor de Tráfego de Ads/clientes/Mestre da Obra/João Pessoa/02-ROADMAP.md) do cliente.*
