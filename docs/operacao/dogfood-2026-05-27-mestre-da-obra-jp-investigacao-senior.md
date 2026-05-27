# Dogfood 2026-05-27 — Mestre da Obra JP (`7862230676`) — sessão investigação senior 8 segmentos + apply B1.6 (169 mudanças)

**Operator:** Claude Code (Sonnet 4.7) em sessão dirigida por wellinton.ribeiro@v4company.com
**Account:** `7862230676` — Mestre da Obra JP+CAB
**Window:** Manhã exploração 11:17-13:00 + tarde investigação 8 segmentos 13:00-14:18 + APPLY B1.6 14:18-14:25 + docs update 14:25-15:00
**Goal:** Sessão D+17 launch / D+8 cleanup B1. Aplicar B1.6 REVISADO pós investigação senior pré-flight. Cravou 2 lições V4 novas (50 v4 + 51) + 169 mudanças aplicadas sem erros + 6 docs atualizados.

**Referência:** complementa dogfoods anteriores [21/05](./dogfood-2026-05-21-mestre-da-obra-jp-drift-detection.md) + [25/05](./dogfood-2026-05-25-mestre-da-obra-jp-zombies-audit.md). Esta sessão é a **mais densa** do ciclo MO-JP: 15+ tool calls + 169 writes + 2 lições V4 novas cravadas.

---

## ✅ Tools sugeridas anteriores que foram entregues

Confirmação contínua do ciclo dogfood → ship:

| Tool | Sugerida em | Status validation hoje |
|---|---|---|
| `detect_drift` | Dogfood 21/05 W1 (ICE 486) | ✅ Funcionou perfeitamente (usado pra audit 22-26/05) |
| `audit_goal_attribution` | Dogfood 21/05 W3 (ICE 360) | ✅ Disponível (não usado hoje, escopo focado em keywords) |
| `audit_orphan_smart_actions` | Dogfood 19/05 | ✅ Disponível |
| `audit_zombie_keywords` | Dogfood 19/05 | ✅ Usado massivamente — F52 (ad_group_status) confirmado working |
| F52 shipped 25/05 (B6 audit_zombie ad_group_status) | Dogfood 25/05 | ✅ Validado — filtro REMOVED ad_groups funcionou; ENABLED cravados |
| F23 fix (LAST_30_DAYS clamp) | Dogfood 25/05 B7 | ✅ Não invocado diretamente — `detect_drift` usado em 7d window |
| B1 refino "lag DIAS" descrição `get_change_history` | Dogfood 25/05 B1 | ✅ Description reflete realidade |

---

## 🚨 Bug NOVA descoberta hoje — B9 (HIGH severity)

### B9: `get_keyword_performance` NÃO distingue positive vs negative criteria

**Sintoma operacional**:
Fresh fetch `get_keyword_performance(status=enabled, limit=500)` retornou:
- 500 keywords ENABLED
- 317 com 0 impressions + 0 clicks LAST_30_DAYS (candidatos a "zumbi")

Cross-check com `audit_zombie_keywords` (que filtra `negative=FALSE` server-side):
- 280 zumbis totais → 108 em ENABLED ad_groups
- Diferença com fresh fetch: **39 keywords = negative ad_group_criterion com status ENABLED**

Essas 39 são keywords negativas a nível ad_group (não campaign-level), que aparecem em `get_keyword_performance` mas:
- Não podem ser pausadas via `update_keyword_status` (lição V4 43 — read-only)
- Não são candidatas a NEG novo (já são negative)
- Inflam baseline de "zumbis" sem ser actionable

**Lista exemplos negative ad_group_criterion ENABLED zumbis detectados** (CAB GERAL — 10 amostras):
- "Areia", "Brita", "Cano de PVC", "Telha", "Tijolo" (materiais)
- "bob cat", "bobcat", "carregadeira", "escavadeira", "fresadora" (equipamentos pesados — protegido)
- "macaco hidraulico", "mini carregadeira" (3 variantes), "minicarregadeira", "retro", "retroescavadeira", "valetadeira"
- "carroça de areia", "nível para pedreiro" (peças/serviços)

**Impacto operacional**:
Workflow "extract criterion_ids zumbis pra PAUSE batch via fresh fetch" produz:
- 147 candidatos PAUSE (incorretos)
- vs 108 verdadeiros (positive ENABLED)
- 39 falsos positivos que rodariam `update_keyword_status` e seriam rejeitados (lição 43)

**Fix sugerido** (ordem preferência):

**Opção A — Field `negative: bool` na response** (mínimo viável):
```json
{
  "criterion_id": "12345",
  "keyword_text": "rolo compactador",
  "match_type": "PHRASE",
  "negative": true,  // NOVO
  "status": "ENABLED",
  ...
}
```
Pro: dado disponível, consumer filtra. Zero breaking change.
Contra: usuário precisa lembrar de filtrar.

**Opção B — Param server-side `negative: false`** (preferido V4):
```python
get_keyword_performance(
    customer_id="...",
    status="enabled",
    negative=False  # NOVO - default null = retorna ambos
)
```
Pro: default safe pra workflows positive (90% dos casos)
Contra: breaking change subtil (mudar default pra `false` filtraria silentemente)

**Opção C — Warning na description** (paliativo):
> "Inclui keywords positive E negative ad_group_criterion. Pra workflows de PAUSE/análise QS, filtre `negative=false` no consumer ou use `audit_zombie_keywords` (negative=FALSE server-side)."

**Recomendação V4: Opção A (mínimo) + Opção C (description)** — backward-compat + clareza.

**Severity**: MEDIUM — workaround existe via `audit_zombie_keywords` mas gera fricção operacional. Eu mesmo errei conta inicial (147 vs 108).

**ICE**: I=7 × C=10 × E=9 (Opção A 1-2h dev) = **630**

---

## 🎯 Quick wins CATEGORIA A (6 itens · 1-2h cada)

### A1: `update_keyword_status` dry-run incluir top 5 sample keywords (HIGH)

**Atual**:
```json
{
  "status": "dry_run",
  "blast_summary": "Mudar status de 19 palavra(s)-chave para PAUSED.",
  "confirmation_token": "5S49572I"
}
```

**Sugerido**: adicionar `sample_keywords` na response:
```json
{
  "status": "dry_run",
  "blast_summary": "Mudar status de 19 palavra(s)-chave para PAUSED.",
  "sample_keywords": [
    {"ad_group_id": "...", "criterion_id": "...", "keyword_text": "aluguel de airless"},
    {"ad_group_id": "...", "criterion_id": "...", "keyword_text": "aluguel de balancim"},
    ...
  ],
  "confirmation_token": "5S49572I"
}
```

**Por quê**: Apply token TTL 10min sem reverter. Top 5 amostras = sanity check humano em 5 segundos. Hoje aplicaria 9 tokens em batch — risco humano alto sem preview.

**Severity**: HIGH (prevenção bug humano em mutation)
**ICE**: I=8 × C=10 × E=10 (~1h dev) = **800**

### A2: `audit_quality_score` adicionar `ad_group_status` field (espelhar F52)

**Atual**: F52 shipped em `audit_zombie_keywords` (campo `ad_group_status` cravado 25/05). `audit_quality_score` ainda não tem.

**Sugerido**: espelhar mesma lógica — field `ad_group_status` na response

**Por quê**: keywords QS≤2 em REMOVED ad_groups são órfãs cosméticas (não precisam fix). Consistency com lição V4 48.

**Severity**: MEDIUM (consistency)
**ICE**: I=6 × C=10 × E=10 (~1h, mesma query JOIN F52) = **600**

### A3: `get_negative_keywords_audit` adicionar `summary_only: bool` (MEDIUM)

**Atual**: 705k chars output (493 negativas conta inteira — excede max tokens)

**Sugerido**: param `summary_only=true` retorna apenas:
- `total_negatives`
- `additions_summary` (last_7_days, last_30_days, pre_30)
- `sample_recent` (top 20 mais recentes)
- `unique_keyword_texts_count`

Sem listar todos os 493 por campaign.

**Por quê**: chamada inicial pra checar idempotência ou contagem não precisa output massivo. Hoje truncou e tive que usar Python pra parsear.

**Severity**: MEDIUM (perf + tokens)
**ICE**: I=6 × C=10 × E=8 (~2h, simples filter na response) = **480**

### A4: `add_negative_keywords` retornar `already_exists` array (MEDIUM)

**Atual**: response não distingue `applied_count` que veio de "criação nova" vs "já existia (skip silencioso)"

**Sugerido**:
```json
{
  "status": "applied",
  "applied_count": 42,
  "already_exists_count": 2,
  "already_exists": ["bobcat", "casa do construtor"]
}
```

**Por quê**: clareza pra batch idempotente. Hoje skipei `bobcat` manualmente (sabia que existia via cross-check). Sem essa info, gestor não sabe se algumas foram skipped.

**Severity**: LOW-MEDIUM (DX)
**ICE**: I=5 × C=9 × E=8 (~2h, response field) = **360**

### A5: `audit_zombie_keywords` adicionar `limit_per_ad_group` (LOW)

**Atual**: 96k chars output 278 zumbis em 1 linha JSON (read.tool não chunca)

**Sugerido**: param `limit_per_ad_group=20` retorna top N zumbis por ad_group (mais antigos primeiro, ou ordenados por algo relevante)

**Por quê**: análise por SEGMENTO precisa ver categoria, não 100 zumbis dum ad_group só. Quem investiga GERAL JPA quer 20-30 amostras, não todos.

**Severity**: LOW (workaround via Python parse)
**ICE**: I=4 × C=9 × E=8 (~2h) = **288**

### A6: `audit_zombie_keywords` adicionar `last_conv_date` (LOW)

**Atual**: zumbi binário (0 imp+cl LAST_30_DAYS)

**Sugerido**: campo `last_conversion_date` (LAST_90_DAYS lookback) — distingue zumbi recente (atividade 31-90d) vs histórico (>90d)

**Por quê**: zumbi recente pode reviver com promoção (PROMOTE EXACT em B3). Zumbi >90d = candidato PAUSE/DELETE seguro.

**Severity**: LOW (insight refinamento)
**ICE**: I=5 × C=8 × E=6 (~4h query LAST_90_DAYS adicional) = **240**

---

## 🛠️ Features médias CATEGORIA B (4-8h cada)

### B1: `apply_change` aceitar lista de tokens (batch apply)

**Atual**: 1 token por call
**Sugerido**: `apply_change(tokens=[t1, t2, ..., t6])` aplica todos em paralelo
**Use case hoje**: 6 dry-run tokens PAUSE → 6 calls separadas. Com batch = 1 call.
**Severity**: MEDIUM (DX)
**ICE**: I=6 × C=9 × E=6 (~4h, mantém compat single token) = **324**

### B2: `get_search_terms_report` filtros server-side granulares

**Atual**: limit 10000 + sem filtros performance
**Sugerido** parâmetros adicionais:
- `min_clicks`: int (default 0)
- `min_conversions`: float (default 0)
- `min_cost_brl`: float (default 0)
- `status_in`: list[str] (default null)
- `exclude_status`: list[str] (default null)

**Use case hoje**: 90d 2000 rows = 700k chars. Pra workflow "top WASTE" (cost>=3, conv=0, status=NONE) filtraria 95% server-side. Pra "GOLD" (conv>=2, status=NONE) idem.

**Severity**: MEDIUM (perf 90%+ reduction)
**ICE**: I=8 × C=10 × E=6 (~6h, query GAQL conditions) = **480**

### B3: `get_keyword_performance` filtros `min_impressions` / `has_clicks`

**Atual**: 500 keywords output 295k chars
**Sugerido**: filtros `min_impressions=1` ou `has_clicks=true` reduz zumbis automaticamente

**Use case**: análise top performers (não zumbis) → 50-100 keywords vs 500.

**Severity**: MEDIUM (perf)
**ICE**: I=7 × C=10 × E=7 (~4h, where clause GAQL) = **490**

---

## 🚀 Features NOVAS CATEGORIA C (1-2 dias cada)

### C1: Tool nova `bulk_promote_to_exact`

**Use case revelado hoje**: 75 PROMOTE B3 candidates → hoje workflow é manual `add_keywords` por keyword + cravar ad_group_id mapping

**Sugerido**:
```python
bulk_promote_to_exact(
    customer_id="...",
    promotions=[
        {
            "search_term": "aluguel de andaimes em joao pessoa",
            "target_ad_group_id": "175472286913",  # ANDAIME JPA
            "target_match_type": "EXACT"
        },
        ...
    ]
)
```

Tool faz: cria keyword EXACT/PHRASE pra cada search_term em ad_group_id específico, com confirmation_token preview pra ≥5.

**Severity**: MEDIUM (alto valor pra workflows B3-tipo)
**ICE**: I=8 × C=8 × E=4 (~1-2 dias) = **256**

### C2: Tool nova `create_ad_group_with_keywords`

**Use case revelado hoje**: B3 16/06 vai criar 8 ad_groups novos. Cada um requer hoje:
1. `create_ad_group` (separado)
2. `add_keywords` (separado, após ter ad_group_id)
3. `create_rsa` (separado, com ad_group_id)
4. apply audience (se aplicável)
= 4 tools sequenciais por ad_group × 8 = 32 calls

**Sugerido**: tool composta atómica que cria tudo em 1 chained mutation (similar a `create_and_link_assets` existing):
```python
create_ad_group_with_keywords(
    customer_id="...",
    campaign_id="...",
    ad_group={
        "name": "[GPA][07][LIXADEIRA]",
        "bid_modifier": ...
    },
    keywords=[
        {"text": "[aluguel de lixadeira]", "match_type": "EXACT"},
        {"text": "[lixadeira de parede]", "match_type": "EXACT"},
        ...
    ],
    rsa={
        "headlines": [...],
        "descriptions": [...],
        "final_urls": [...]
    }
)
```

**Severity**: MEDIUM (alto valor pra B3 expandido)
**ICE**: I=8 × C=7 × E=3 (~2 dias, chained mutation similar `create_and_link_assets`) = **168**

### C3: Tool nova `get_ad_group_intent_analysis`

**Use case**: workflow SEGMENT-INVESTIGATION (5 reads paralelos por segmento = 40 calls em 8 segmentos)

**Sugerido**: tool composta retornando matriz already-classified por ad_group:
- ERP cross-check (se MCP empsis disponível)
- Search_terms 90d top + waste + gold
- Keywords ENABLED top performers + zumbis
- Sinônimos regionais sugeridos

**Severity**: LOW (workflow atual 5 reads paralelos funciona bem)
**ICE**: I=6 × C=6 × E=2 (~2-3 dias) = **72**

---

## 📝 Documentação MCP CATEGORIA D (cravar lições V4 nas descriptions)

### D1: `add_negative_keywords` description — adicionar caveat Cat A/B/C

**Add**:
> ANTES de propor NEG: aplicar teste 3 perguntas operacionais V4 — (1) cliente TEM equipamento equivalente no ERP/inventário? (2) cliente típico ACEITARIA o substituto ao ligar/conversar? (3) Se NÃO aceitar → lead Google é FAKE (mensagem gerada, venda não fecha). Cat A (substituto funcional aceito) + B (mesmo equipamento nome diferente/sinônimo regional) → NÃO NEG, usar PROMOTE. Cat C (produto único cliente recusa) → NEG mesmo com conv aparente. Ver `padroes-investigacao-senior.md` V4 ou docs/lessons cliente.

### D2: `create_ad_group` description — adicionar caveat Gateway vs Recurring

**Add** (especificamente pra B2C/B2B locação recorrente):
> Em LOCAÇÃO RECORRENTE com alta retenção pós-1ª compra (cliente busca via WhatsApp pós-aquisição): equipamento ERP alto faturamento + ZERO Google search 90d = RECURRING product (NÃO criar ad_group — base já compra via canal direto, ad seria desperdício). Cravar ad_group SE search 90d ≥ 5 = GATEWAY product. Ver Lição V4 51 em `padroes-investigacao-senior.md`.

### D3: `audit_zombie_keywords` description — pré-cleanup checklist V4

**Add** (expandindo nota F52 atual):
> Pré-cleanup checklist V4 obrigatório pra keywords ≥30: (1) audit_zombie identifica pool · (2) cross-check ad_group.status (F52 cravado) · (3) cross-check ERP/inventário cliente · (4) cross-check search_terms 90d (lição 50) — search_term que CONVERTE via substituto NÃO é NEG · (5) cross-check sinônimos regionais (lição 50 v4 — tabela NE em padroes-investigacao-senior.md). Separa NEG/PAUSE/PROMOTE corretamente.

---

## ✅ Tools usadas hoje (15+ calls)

### Read tools
1. `audit_zombie_keywords` ✅ (1 call — F52 funcionou perfeito)
2. `audit_quality_score` ✅ (1 call — 17 keywords flagged)
3. `get_negative_keywords_audit` ✅ (1 call — 493 negativas, output 700k truncado)
4. `get_search_terms_report` ✅ (2 calls — 7d e 90d, output truncado em 90d)
5. `get_keyword_performance` ✅ (2 calls — manhã + fresh tarde, 500 kws output truncado)
6. `get_ad_group_performance` ✅ (1 call — 13 ad_groups ENABLED)
7. `validate_gaql` ✅ (1 call — query ad_group JOIN)
8. `run_gaql` ✅ (1 call — listar ad_groups + status)
9. `detect_drift` ✅ (1 call — 7d, 5 changes Pedro já conhecidos)
10. `list_my_accounts` ✅ (1 call — startup)

### Write tools (B1.6 APPLY)
1. `add_negative_keywords` ✅ (2 calls em paralelo — 44 JPA + 44 CAB = 88 NEG auto-aplicadas)
2. `update_keyword_status` ✅ (9 calls — 3 auto-aplica + 6 dry-run)
3. `apply_change` ✅ (6 calls em paralelo — 6 tokens PAUSE consumidos)

### ERP empsis MCP (cross-validation)
- `equipamentos_mais_locados` ✅ (1 call — top 100 fat 180d)
- `estoque_produto` ✅ (~15 buscas paralelas — ROÇADEIRA, CORTADOR, PALETEIRA, TRANSPALLET, ACABADORA, POLITRIZ, ALISADORA, PLAINA, TUPIA, ROSQUEADEIRA, PLATAFORMA, MARTELETE BATERIA, LAVADORA, BOMBA SUBMERSIVEL, COMPACTADOR, FURADEIRA, DEWALT, GERADOR, EXTRATORA, EXTRATOR, MISTURADOR, ARGAMASSADEIRA)

### WebSearch
- 6 queries (best practices 2026 Google Ads) — sessão manhã (cravar padroes-investigacao-senior.md)
- 1 query `martelete EOS marca` (verificar Cat A)

**Total**: ~15 tool calls MCP v4-ads + ~17 ERP + 7 web = **~40 calls em ~4h sessão**

---

## 📊 Padrões V4 novos descobertos (cravar findings-catalog)

### P5 — Cat A/B/C substituto operacional (Lição V4 50 v4)

Teste 3 perguntas ANTES de NEG:
1. Cliente TEM equipamento equivalente no ERP? (data)
2. Cliente típico ACEITARIA o substituto? (gestor)
3. Se NÃO aceitar → lead Google é FAKE (venda não fecha)

3 categorias substituto:
- **A — FUNCIONAL ACEITO**: cortador grama→roçadeira, britadeira→martelete rompedor, acabadora→alisadora, dewalt→qualquer marca, diesel→gasolina, martelete EOS→MAKITA SDS Plus. **PROMOTE B3**.
- **B — MESMO EQUIPAMENTO NOME DIFERENTE**: paleteira manual=transpallet, sapinho=compactador solo, desempenadeira=alisadora, lavadora semi-pro=J7 PRO.S SEMI. **PROMOTE B3 EXACT**.
- **C — PRODUTO ESPECÍFICO ÚNICO**: rolo compactador, plataforma elevatória pessoa, bobcat, perfuratriz industrial, 50/100/1000 kva, betoneira 600L+, gerador residencial silencioso, trator. **NEG mesmo com conv aparente Google**.

**Validação MO 27/05**: 9 NEG planejadas invalidadas via Cat A/B (pipeline ~129 conv/90d preservadas) + Intent COMPRA/USADO/OLX descoberto Cat A (CVR 62-88%).

### P6 — Google = AQUISIÇÃO em LOCAÇÃO RECORRENTE (Lição V4 51)

Em B2B/B2C com alta retenção pós-1ª compra:
- Cliente NOVO entra via Google
- Cliente RECORRENTE busca via WhatsApp pós-1ª locação
- Métricas search_term 90d MEDEM SOMENTE aquisição

**Filtro pra criação ad_group**:
- ERP alto fat + search 90d ≥ 5 = **GATEWAY** (criar ad_group dedicado)
- ERP alto fat + ZERO search 90d = **RECURRING** (NÃO criar — desperdício)

**Validação MO 27/05**: 8 gateways pra criar B3 (LIXADEIRA 21,5c top + 7 outros) · 12 recurring NÃO criar (lavadora R$11k fat, vibrador concreto R$33k, cortadora piso R$17k — todos ZERO Google demand = recorrência WhatsApp).

### P7 — Sinônimos regionais NE Locação leves (validados Wellington 27/05)

Tabela cravada em `padroes-investigacao-senior.md` — usar antes de classificar NEG quando cliente busca termo não-literal ao ERP:

| Termo cliente | Equipamento MO equivalente | Cat | Validação |
|---|---|---|---|
| paleteira manual | TRANSPALLET MTP 3T | B | Wellington 27/05 |
| sapinho / sapo compactador / pula pula / socador de terra | COMPACTADOR DE SOLO | B | Termos regionais NE |
| britadeira / rompedor | MARTELETE ROMPEDOR | A | Substituto funcional |
| acabadora / desempenadeira | ALISADORA + POLITRIZ | A | Substituto funcional |
| elevador para obra | GUINCHO ELEVAÇÃO 500KG | A | Mesmo uso obra |
| cortador grama / cortar grama | ROÇADEIRA A GASOLINA | A | Parcial — atende |
| lavadora semi-pro | LAVADORA J7 PRO.S SEMI | B | MO tem categoria |
| perfurador solo (NÃO perfuratriz industrial) | PERFURADOR SOLO BFG | B | CUIDADO Cat C grande |
| bomba submersa | BOMBA SUBMERSÍVEL MAKITA/BUFFALO | B | Mesmo equipamento |
| escora de laje | ESCORA METÁLICA | B | Mesmo equipamento |

---

## 🎯 Priorização ICE consolidada

| # | Item | I | C | E | **ICE** | Categoria |
|---|---|---|---|---|---|---|
| A1 | `update_keyword_status` dry-run sample keywords | 8 | 10 | 10 | **800** | Quick win (bug prev) |
| B9 | `get_keyword_performance` negative field | 7 | 10 | 9 | **630** | NOVA pegadinha |
| A2 | `audit_quality_score` ad_group_status | 6 | 10 | 10 | **600** | Quick win (consistency F52) |
| B3 | `get_keyword_performance` filtros min_impressions | 7 | 10 | 7 | **490** | Médio (perf) |
| B2 | `get_search_terms_report` filtros server-side | 8 | 10 | 6 | **480** | Médio (perf 90% reduction) |
| A3 | `get_negative_keywords_audit` summary_only | 6 | 10 | 8 | **480** | Quick win (perf) |
| A4 | `add_negative_keywords` already_exists | 5 | 9 | 8 | **360** | Quick win (DX) |
| B1 | `apply_change` batch tokens | 6 | 9 | 6 | **324** | Médio (DX) |
| A5 | `audit_zombie_keywords` limit_per_ad_group | 4 | 9 | 8 | **288** | LOW |
| C1 | `bulk_promote_to_exact` (tool nova) | 8 | 8 | 4 | **256** | Feature nova (workflow B3) |
| A6 | `audit_zombie_keywords` last_conv_date | 5 | 8 | 6 | **240** | LOW |
| C2 | `create_ad_group_with_keywords` (tool nova) | 8 | 7 | 3 | **168** | Feature nova (workflow B3) |
| C3 | `get_ad_group_intent_analysis` (tool nova) | 6 | 6 | 2 | **72** | LOW (workflow atual ok) |

**Top 3 sprint atual**:
1. **A1 (ICE 800)** — sample keywords no dry-run = prevenção bug humano CRÍTICO
2. **B9 (ICE 630)** — fix `get_keyword_performance` negative field/filter
3. **A2 (ICE 600)** — `audit_quality_score` ad_group_status (consistency F52)

---

## 📦 Anexo — IDs e descobertas relevantes 27/05

### Apply B1.6 — provider_request_ids cravados
**88 NEG aplicadas**:
- JPA `21359547724`: `824z9G8Rq2CvmG52dXbfxQ` (44 negatives)
- CAB `22169885957`: `82SDPkJB-U758nRGX2ufSQ` (44 negatives)

**81 PAUSE aplicadas em 9 batches**:
| Ad_group | Count | Provider Request ID | Token (se dry-run) |
|---|---:|---|---|
| `[GPA][01][BETONEIRA][CABEDELO]` | 1 | wP93KL8-1FNOirPlpfr2Bg | auto |
| `[GPA][04][MARTELETE]` JPA | 2 | R09QDmDGtkzDr1vsje-AQw | auto |
| `[GPA][02][BETONEIRA]` JPA | 5 | IXFtyQiYq2-2zV90_SBwxQ | auto |
| `[GPA][05][MARTELETE][CABEDELO]` | 6 | -9zSauoaaZjOUGkKS4vGVA | 39P5QR1P |
| `[GPA][05][COMPACTADOR]` JPA | 7 | RI3iL8PlUL88PKH9xU-_qg | QI1K6K34 |
| `[GPA][04][GERADORES][CABEDELO]` | 8 | 7l8Tsct_mKxRhSulZoOPyQ | U2FPK4KQ |
| `[GPA][03][COMPACTADOR][CABEDELO]` | 9 | iXKpkwcCi8FE9NHD_tmVNw | P3BIXS4N |
| `[GPA][00][GERAL]` CAB | 19 | T_lVsTy0e5YFQCn8DsF90A | 5S49572I |
| `[GPA][01][GERAL]` JPA | 24 | --rbPRno3A3MdjGGjQIsrQ | KK5WTOFZ |

### Investigação Senior 8 Segmentos
- Segmento 1 GERAL JPA+CAB (63 zumbis) → 12 NEG + 20 PROMOTE B3 + 28 PAUSE + 3 DECISÃO
- Segmento 2 ANDAIME → 6 NEG + 10 PROMOTE B3 + 1 PAUSE + 3 QS fixes
- Segmento 3 MARTELETE → 4 NEG + 10 PROMOTE B3 + 8 PAUSE + 6 QS fixes
- Segmento 4 GERADOR (CVR JPA 16% problema) → 8 NEG + 6 PROMOTE B3 + 12 PAUSE + AUDIT B4 RSA/LP
- Segmento 5 COMPACTADOR → 0 NEG (3 reversões V4 50) + 9 PROMOTE B3 + 23 PAUSE
- Segmento 6 BETONEIRA (descoberta 150L PRIME) → 4 NEG + 12 PROMOTE B3 + 6 PAUSE
- Segmento 7 NEG plan 25/05 restantes → 9 invalidações Cat A + 8 confirmações Cat C
- Segmento 8 Gap analysis → 8 GATEWAY products + 12 RECURRING (Lição V4 51 nascimento)

### 12 decisões Wellington Cat A/B/C
Q1-Q12: britadeira A · gerador a diesel A · cortador de grama A · acabadora A · dewalt compactador A · compactador elétrico A · martelete EOS A · gerador 1000 kva C · paleteira manual B · sapinho compactador B · betoneiras 200/250L A + 600L C · perfuratriz C (Wellington corrigiu — pesada industrial)

### Cumulativo investigação ↔ apply
- ~3h40min sessão total
- 15+ tool calls MCP v4-ads
- 17 ERP queries cross-validation
- 7 web searches (best practices + EOS validation)
- 169 mudanças aplicadas SEM ERROS
- 2 lições V4 cravadas (50 v4 + 51)
- 6 docs atualizados
- 8 ad_groups novos cravados B3
- 5 AUDIT B4 cravados

---

*Produzido por Claude Code 2026-05-27 em sessão D+17 MO-JP+CAB tarde. Lições V4 50 v4 + 51 + sinônimos regionais NE registrados em `02-ROADMAP.md` MO-JP + `padroes-investigacao-senior.md` (raiz V4). Reconhecimento contínuo ao time V4-ads MCP — ciclo dogfood funcionou (F52 + F23 fix usados validam shipped 25/05). Sessão mais densa do ciclo MO-JP até hoje.*

---

**Update 2026-05-27 pós-publicação**: Documento cravado em `D:/V4 ads MCP/docs/operacao/`. Próximas sessões MO-JP/Camaçari aplicar lições V4 50 v4 + 51 via SOP atualizado. Aguardando shipping de B9 (HIGH severity) + A1/A2 (quick wins ICE 800/600). Smoke real de B9 fix pendente sessão futura (próximo cleanup keywords em conta nova).
