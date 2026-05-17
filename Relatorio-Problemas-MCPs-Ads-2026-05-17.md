# Relatório de Problemas — MCPs de Ads

> **Data de levantamento**: 17/05/2026
> **Origem dos achados**: sessão de execução do relatório semanal Mestre da Obra JP+CAB em 15/05/2026 (geração via MCPs `v4-ads`, Meta MCP oficial e `empsis`).
> **Gestor**: Wellington Ribeiro · wellinton.ribeiro@v4company.com
> **Escopo deste documento**: problemas, friccões e gaps identificados nos MCPs durante coleta de dados real para entregável V4. Não inclui skills ou plugins (documentados separadamente).

---

## Sumário executivo

| MCP | Bloqueios | Fricções | Gaps | Status geral |
|---|---|---|---|---|
| `v4-ads` (Google Ads V4) | 1 | 2 | 0 | Funcional com workaround |
| Meta MCP oficial (`9a70c712-...`) | 2 | 1 | 0 | Funcional com perdas significativas |
| `empsis` (ERP) | 0 | 0 | 0 | Padrão de referência |

**Prioridade de fix (consolidada)**:
1. **v4-ads** — `date_range` object format quebrado (impede períodos custom)
2. **Meta** — Campos "Not available" silenciosos por objective × optimization_goal (impede análise criativa)
3. **Meta** — Campo `actions` solo rejeitado sem hint claro
4. **v4-ads** — `get_search_terms_report` token cap muito agressivo (default 500 estoura limite)
5. **v4-ads** — `get_negative_keywords_audit` sem `created_date`
6. **Meta** — `ads_get_dataset_quality` saída pobre (sem EMQ scores)

---

## 1. MCP `v4-ads` (Google Ads V4 — `https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/mcp`)

### 1.1 [CRÍTICO] `date_range` object `{from, to}` rejeitado

**Tools afetadas**: `get_account_overview`, `get_funnel_metrics`, `get_campaign_performance`, `get_top_keywords_creatives`, `get_device_performance`, `get_search_terms_report` (e provavelmente todas que aceitam `date_range`).

**Comportamento observado**:
Schema declara que aceita `{from: 'YYYY-MM-DD', to: 'YYYY-MM-DD'}` como object OU preset string. Em todas as 6 chamadas iniciais o object foi rejeitado com:

```
Unknown date_range preset '{"FROM":"2026-05-08","TO":"2026-05-14"}'.
Valid presets: LAST_14_DAYS, LAST_30_DAYS, LAST_7_DAYS, LAST_90_DAYS,
LAST_MONTH, LAST_WEEK, THIS_MONTH, THIS_WEEK, TODAY, YESTERDAY
```

**Diagnóstico**: middleware está fazendo upper-case nas keys do object (`from` → `FROM`, `to` → `TO`) e tratando o object inteiro como string de preset. Provavelmente um normalizer genérico de params está sendo aplicado antes do roteamento.

**Input enviado**:
```json
{"customer_id": "7862230676", "date_range": {"from": "2026-05-08", "to": "2026-05-14"}}
```

**Impacto**:
- **Bloqueio real** para qualquer período custom (comparar mesma semana mês passado, janela 14-30/04, etc.).
- Presets cobrem só janelas relativas a "hoje". Pra report semanal Wellington precisava 08-14/05 — caiu por sorte em `LAST_7_DAYS` (today = 15/05).
- Comparativo período anterior fica preso ao que `get_account_overview` entrega automaticamente.

**Workaround usado**: usar preset `LAST_7_DAYS`.

**Fix sugerido**:
- Middleware deve preservar casing das keys quando o param é object.
- OU se object não é suportado, schema deve declarar `type: string` only com lista de presets.
- OU adicionar `from_date`/`to_date` como params separados (escapando o roteamento por type).

**Severidade**: Alta. Limita análise V4 a janelas pré-definidas.

---

### 1.2 [MÉDIO] `get_search_terms_report` — token cap muito agressivo (default 500)

**Comportamento observado**:
Chamada com `limit=500` retornou **193.987 caracteres** e excedeu o cap de tokens. Output foi salvo em arquivo temp e exigiu read sequencial:

```
Error: result (193.987 characters) exceeds maximum allowed tokens.
Output has been saved to <tool-results path>.
REQUIREMENTS FOR SUMMARIZATION/ANALYSIS/REVIEW:
- You MUST read the content from the file in sequential chunks until 100% of the content has been read.
```

**Impacto**:
- Esta sessão **abandonou a leitura do arquivo** por economia de tempo — usei apenas a contagem agregada de negativas do `get_negative_keywords_audit`. Gap de dado real no relatório.
- Pra audit completa de search terms (skill `auditoria-google-ads`), o overhead de ler arquivo paginado é significativo.

**Workaround usado**: pular leitura, usar audit de negativas para inferir cobertura.

**Fix sugerido**:
- Reduzir default de `limit=500` para `limit=50`.
- Adicionar parâmetro `summarize=true` que retorna agregação (top N gasto + top N conv 0 + total stats) em formato compacto.
- OU adicionar `min_cost` / `min_clicks` filters pra reduzir cardinalidade no servidor.

**Severidade**: Média. Recorrente em qualquer audit de search terms.

---

### 1.3 [MÉDIO] `get_negative_keywords_audit` — sem `created_date` por critério

**Comportamento observado**:
Tool retorna a lista completa atual (467 negativas no caso MO-JP+CAB) com `criterion_id`, `keyword_text`, `match_type`. **Não retorna data de adição**.

**Impacto**:
- Pra falar "X negativas adicionadas no período do relatório" precisei cruzar manualmente com `get_change_history`. Inviável pra relatório semanal.
- No Word entregue acabei falando do volume total (467) sem distinguir adições recentes.

**Workaround usado**: mencionar volume total + lista qualitativa de geo-negativas estratégicas.

**Fix sugerido**: incluir `created_date` (e idealmente `added_by_email`) por critério.

**Severidade**: Média. Não bloqueia, mas degrada qualidade narrativa.

---

### 1.4 Limitação documentada — `get_geo_performance` country-level only

Já conhecida e listada em [`mcp-v4-ads-reference.md`](D:/Gestor%20de%20Tráfego%20de%20Ads/mcp-v4-ads-reference.md). Pra cidade-level usar `run_gaql` com `geographic_view` + validate prévio. Não é bug — só limitação a contornar em sessões que precisam de cidade.

---

### 1.5 Observação positiva — `get_account_overview` entrega comparativo automático

Diferencial valioso da tool: ela já calcula período anterior de mesma duração e retorna ambos no mesmo payload. Economiza 1 call.

**Caveat**: o `tracking_warning` que vem no payload (ex: `"conversions_value == conversions (1:1 ratio). Tracking provavelmente sem revenue real — ROAS pode ser misleading."`) é útil, mas **não flag específico** quando o período anterior tem perfil de conversão diferente do atual (ex: pré vs pós-correção de geoTargetType). Pra cliente lead-gen, sugiro adicionar warning quando há mistura de categorias de conversão (CONTACT vs GET_DIRECTIONS vs ENGAGEMENT) na janela.

---

## 2. MCP Meta oficial (`9a70c712-f16f-4456-81f8-505c0897f04e`)

### 2.1 [CRÍTICO] `ads_get_ad_entities` — campo `actions` solo rejeitado sem hint claro

**Comportamento observado**:
Passei `"actions"` como field e foi rejeitado com lista de campos válidos:

```json
{
  "error_category": "VALIDATION",
  "error_message": "Unsupported field(s): actions. Supported fields are:
    3_second_video_plays, actions:comment, actions:like, actions:link_click,
    actions:omni_purchase, actions:page_engagement, actions:post_reaction,
    actions:post_save, ad_creation_package_config, adset_id, amount_spent, ...",
  "error_code": "100"
}
```

**Diagnóstico**: schema description lista "actions" entre os fields ("**This is a partial list**...") e dá exemplo `"actions:like"` mas não explicita que `actions` solo é inválido. Documentação engana.

**Impacto**:
- Quem vem de Marketing API Graph (onde `actions` retorna array com todos os action_types) atinge esse erro na primeira tentativa.
- Custou 1 retry completo (3 calls Meta repetidas: campaign + adset + ad).

**Workaround usado**: substituí `actions` por `actions:link_click + actions:page_engagement`. Funcionou parcialmente (ver 2.2).

**Fix sugerido**:
- Pre-validation no schema — rejeitar `actions` no client side com mensagem clara.
- Adicionar à description: "Note: `actions` must always be specified as `actions:<type>` — bare `actions` is not supported."
- Lista de exemplos típicos por objective:
  - `OUTCOME_LEADS` → `lead, actions:link_click`
  - `OUTCOME_ENGAGEMENT` (REPLIES) → `cost_per_result, results`
  - `OUTCOME_AWARENESS` → `reach, frequency`

**Severidade**: Alta. Falha previsível na primeira chamada.

---

### 2.2 [CRÍTICO] `ads_get_ad_entities` — 80% dos fields voltam `"Not available"` silenciosamente

**O problema mais grave da sessão.** Para a campanha A CTW da MO (objetivo `OUTCOME_ENGAGEMENT`, optimization `REPLIES`), passei 24 fields válidos. **17 deles voltaram com string literal `"Not available"`**:

```json
{
  "id": "120242168745300258",
  "name": "[CP] [V4] [A] [CTW] [PROSPECTING+RETARGETING] 2026-05",
  "objective": "OUTCOME_ENGAGEMENT",
  "daily_budget": "R$58,00 BRL",
  "bid_strategy": "Highest volume",
  "impressions": "6.478",
  "amount_spent": "R$71,83 BRL",
  "reach": "3.784",
  "frequency": "1,71",
  "result_values": [{"indicator": "R$0,00 BRL"}],
  "clicks": "Not available",
  "ctr": "Not available",
  "cpc": "Not available",
  "results": "Not available",
  "cost_per_result": "Not available",
  "cost_per_link_click": "Not available",
  "lead": "Not available",
  "actions:link_click": "Not available",
  "actions:page_engagement": "Not available",
  "delivery_sub_status": "Not available"
}
```

**Impacto direto no relatório**:
- **Sem CTR/CPC**: não consegui falar de eficiência de clique no Word entregue. Tive que descrever campanhas Meta D+1 só por impressions + reach + frequency.
- **Sem `results`**: pra REPLIES (conversas iniciadas via WhatsApp) o número de conversas — métrica primária da campanha — voltou indisponível. Caí em `result_values: [{"indicator": "R$0,00 BRL"}]` que não é valor útil.
- **Sem `actions:link_click`**: não consegui validar engajamento dos vídeos da campanha C Awareness.

**Suspeita técnica**: campos disponíveis dependem de `objective × optimization_goal × buying_type`. Mas **a tool retorna `"Not available"` em string, não erro estruturado** — silencioso, dificulta debug. Não há documentação de matriz `objective → fields disponíveis`.

**Comparativo entre objetivos** (mesma chamada, 3 campanhas):
- Campanha A (`OUTCOME_ENGAGEMENT/REPLIES`): só impressions, amount_spent, reach, frequency, daily_budget, bid_strategy populam
- Campanha C (`OUTCOME_AWARENESS/REACH`): impressions, amount_spent, reach, frequency + `results` populado como `[{"indicator": "reach", "values": [{"value": 20875}]}]`
- Campanha B (`OUTCOME_LEADS/Unknown Optimization Goal`): impressions, amount_spent, reach, frequency, `result_values: [{"indicator": "action_values:lead"}]` mas SEM número real

**Fix sugerido**:
- Retornar erro estruturado: `{"field": "clicks", "error": "not_available_for_objective", "objective": "OUTCOME_ENGAGEMENT", "optimization_goal": "REPLIES"}` em vez de string `"Not available"`.
- Publicar matriz `objective × optimization_goal × buying_type → available_fields` na documentação da tool.
- OU adicionar tool `ads_describe_fields(objective, optimization_goal)` que retorna lista de fields disponíveis antes da chamada principal.
- Idealmente: retornar dado em formato consistente (todos como object com `value`/`unit` ao invés de mistura de string formatada "R$58,00 BRL" + objeto + "Not available").

**Severidade**: Alta. Compromete análise criativa para qualquer campanha que não seja conversão padrão.

---

### 2.3 [MÉDIO] `ads_get_dataset_quality` — saída pobre vs schema promete

**Comportamento observado**:
Schema description promete: "EMQ scores, per-match-key coverage, and data upload freshness... grouped by channel (web, offline, crm, custom_attribution)".

Output real para Pixel `1383778336264832`:

```json
{"web":[{"event_name":"PageView"}]}
```

Sem EMQ score, sem match-key coverage, sem freshness. Só lista 1 event_name.

**Diagnóstico provável**: dataset jovem (operação Meta lançada 13/05, 2 dias antes da call), só PageView populando, Lead via Lead Form interno não passa pelo Pixel. Pode ser que EMQ só calcule após N eventos / N dias.

**Impacto**:
- Não consegui validar baseline EMQ pré-launch (2,5/10 documentado em audits anteriores) vs estado D+2.
- Sem visibilidade de match-key coverage, gate de CAPI (27/05 D+15) fica sem termômetro.

**Workaround usado**: nenhum — registrei no chat exec como "Pixel EMQ ainda baixo, gate CAPI vira mais urgente".

**Fix sugerido**:
- Schema deve declarar pré-requisitos: "Requires N events in last 7 days to compute EMQ. Returns event_name list only if threshold not met."
- OU retornar campo `eligibility: {emq_computable: false, reason: "insufficient_events_last_7d"}` explicando porquê EMQ não veio.

**Severidade**: Média. Não bloqueia mas degrada monitoria de qualidade de sinal.

---

### 2.4 Observação — `ads_get_ad_entities` formato `time_range` ambíguo

Schema declara `"time_range": {"type": "string", "description": "Date range with since and until properties in YYYY-MM-DD format."}`.

Passei como object JSON serializado `{"since":"2026-05-13","until":"2026-05-14"}` (com aspas no Claude Code) e funcionou. Mas a combinação `type: string` + "with properties" é confusa. Documentar exemplo literal evitaria tentativa-e-erro:

```json
"time_range": "{\"since\":\"2026-05-13\",\"until\":\"2026-05-14\"}"
```

OU mudar `type` para `object` no schema (provavelmente possível dado que MCPs aceitam objects nativos).

**Severidade**: Baixa. Funcionou na primeira tentativa.

---

### 2.5 Observação positiva — `ads_get_dataset_stats`

Funcionou bem. Retornou volume horário de eventos PageView/Lead nos últimos 7 dias com aggregation `event`, suficiente pra montar narrativa de tracking pré/pós-launch Meta. Único caveat: timestamps em PST (`-0700`) em vez de timezone do cliente — exige conversão manual pra horário Brasil (UTC-3).

---

### 2.6 Gaps documentados (`MCP-Meta-Oficial-Reference.md`)

Lembrar que o doc V4 [`MCP-Meta-Oficial-Reference.md`](D:/Gestor%20de%20Tráfego%20de%20Ads/MCP-Meta-Oficial-Reference.md) já cataloga gaps conhecidos do MCP Meta oficial:

- **Listing de Custom Audiences** — não há tool, usar UI Wellington
- **Listing de Lead Forms** — não há tool, usar UI Wellington
- **Account info financial** — não há tool
- **Activities log** — não há tool

Nada novo descoberto nesta sessão, mas vale rastrear no mesmo lugar.

---

## 3. MCP `empsis` (ERP Mestre da Obra)

### 3.1 Funcionamento padrão de referência

4 chamadas paralelas (`faturamento_periodo`, `ranking_vendedores`, `equipamentos_mais_locados`, `clientes_inativos`). **Todas retornaram dados estruturados sem erro, sem fricção, sem campos vazios**.

Pontos fortes do design:
- **Schema enxuto** — 3-5 params por tool, defaults sensatos
- **Output JSON limpo** — sem strings formatadas tipo "R$ 116,17 BRL", retorna `faturamento: 116173.69` como número
- **Nomes em português** — alinhado com domínio do cliente (`faturamento`, `ranking`, `vendedor`)
- **Bloco de concentração de receita em `clientes_inativos`** — entrega análise pronta (top 10/20 %) além dos dados brutos, **economiza pós-processamento no client**

**Nenhuma issue identificada nesta sessão.**

Se houver expansão futura do MCP `empsis`, vale considerar:
- Tool `lojas_split(periodo)` retornando split JP vs CAB (hoje precisa inferir via cidade do cliente)
- Tool `atribuicao_canal(periodo, source)` se cliente trouxer UTM/canal nos contratos
- Hoje cumpre o escopo declarado com qualidade alta

---

## 4. Cross-MCP — friccões transversais

### 4.1 Timezones inconsistentes

- `v4-ads`: retorna datas no fuso da conta (Brasil/PB, UTC-3)
- Meta `ads_get_dataset_stats`: retorna timestamps em PST (`-0700`)
- `empsis`: datas em formato `YYYY-MM-DD` sem timezone (assume local server)

**Impacto**: quando cruza-se dados (ex: "PageView Meta às 04:00 PST = 08:00 BRT vs faturamento ERP dia 13/05"), há risco de off-by-day. Pra relatório multi-canal V4, vale normalizar tudo pra BRT no client.

**Sugestão**: cada MCP declarar timezone do output explicitamente em cada resposta (`"timezone": "America/Sao_Paulo"`).

### 4.2 Formatos de moeda inconsistentes

- `v4-ads`: `cost_brl: 3036.62` (número, brl)
- Meta: `"amount_spent": "R$71,83 BRL"` (string formatada PT-BR)
- `empsis`: `faturamento: 238204.69` (número, brl)

**Impacto**: client precisa parser pra Meta (substituir `,` por `.`, remover " BRL", parsear). Quebra agregação trivial.

**Sugestão**: Meta retornar `amount_spent: 71.83, currency: "BRL"` como number + currency code, não string formatada.

### 4.3 Cardinalidade de output — falta `summary` mode

Tanto `v4-ads get_search_terms_report` (193k chars) quanto Meta `ads_get_ad_entities level=ad` (24 entities × 16 fields) entregam dados brutos sem opção de resumo.

Pra workflows V4 de relatório, 80% das chamadas precisam só de top 10 + agregação total. **Adicionar `summary=true` em todas as tools de listing reduziria token usage 70-90%** e aceleraria sessions Plan→Exec.

---

## 5. Quadro priorizado — pra time MCP V4

| # | MCP | Problema | Severidade | Esforço estimado fix | ROI |
|---|---|---|---|---|---|
| 1 | v4-ads | `date_range` object format quebrado | CRÍTICO | Baixo (middleware fix) | Alto — destrava custom periods |
| 2 | Meta | Campos `"Not available"` silenciosos por objective | CRÍTICO | Médio (matriz docs + error format) | Alto — destrava análise criativa |
| 3 | Meta | `actions` solo rejeitado sem hint | ALTO | Baixo (schema description + exemplos) | Médio — evita 1 retry/sessão |
| 4 | v4-ads | `get_search_terms_report` token cap | MÉDIO | Médio (default limit + `summarize=true`) | Alto — recorrente em audits |
| 5 | v4-ads | `get_negative_keywords_audit` sem `created_date` | MÉDIO | Baixo (campo extra na query GAQL) | Médio — degrada narrativa |
| 6 | Meta | `ads_get_dataset_quality` saída pobre vs schema | MÉDIO | Baixo (eligibility flag) | Baixo — só relevante pré-CAPI maturado |
| 7 | Cross | Formatos moeda inconsistentes | BAIXO | Baixo (Meta retornar number) | Médio — limpa client side |
| 8 | Cross | Timezones inconsistentes | BAIXO | Baixo (campo `timezone` em cada response) | Médio — evita off-by-day |

---

## 6. Próximos passos sugeridos

### Pro time MCP V4 (`v4-ads`)
1. **Fix #1 prioritário**: middleware de params — preservar casing de keys quando param é object
2. Adicionar `summarize=true` em `get_search_terms_report` + `get_top_keywords_creatives`
3. Adicionar `created_date` em `get_negative_keywords_audit`

### Pro time Meta MCP (Anthropic / Meta partnership)
1. **Fix #2 prioritário**: publicar matriz `objective × optimization_goal → available_fields` (mesmo que README)
2. Substituir string `"Not available"` por struct estruturado com motivo
3. Padronizar formato de moeda (number + currency code)
4. Documentar pré-requisitos de `ads_get_dataset_quality` (eligibility)

### Pra documentação interna V4
1. Atualizar [`MCP-Meta-Oficial-Reference.md`](D:/Gestor%20de%20Tráfego%20de%20Ads/MCP-Meta-Oficial-Reference.md) com:
   - Tabela "fields que populam por objective" (à medida que descobrimos)
   - Lista de erros conhecidos + workarounds
2. Adicionar seção em [`mcp-v4-ads-reference.md`](D:/Gestor%20de%20Tráfego%20de%20Ads/mcp-v4-ads-reference.md):
   - Workaround `date_range` object → preset
   - Padrão de paginação `get_search_terms_report`

### Pra próximas sessões V4
- **Antes de qualquer call Meta com `ads_get_ad_entities`**: rodar 1 call exploratória com 2-3 fields essenciais + checar quais voltam `"Not available"`, depois ampliar com os que populam
- **Antes de qualquer `date_range` custom no v4-ads**: confirmar que o preset cobre o período desejado, senão considerar split em 2 calls de presets adjacentes

---

## Anexo A — Comandos exatos que falharam (reprodução)

### v4-ads — `date_range` object rejeitado
```
mcp__v4-ads__get_account_overview(
  customer_id="7862230676",
  date_range={"from":"2026-05-08","to":"2026-05-14"}
)
→ Error: Unknown date_range preset '{"FROM":"2026-05-08","TO":"2026-05-14"}'
```

### Meta — `actions` solo rejeitado
```
mcp__9a70c712-f16f-4456-81f8-505c0897f04e__ads_get_ad_entities(
  ad_account_id="1145068113357031",
  level="campaign",
  time_range="{\"since\":\"2026-05-13\",\"until\":\"2026-05-14\"}",
  fields=["id","name","actions",...]
)
→ Error: Unsupported field(s): actions
```

### Meta — `"Not available"` silencioso (sem erro, dado inacessível)
```
fields=["id","name","clicks","ctr","cpc","results","cost_per_result",
        "actions:link_click","actions:page_engagement","lead",...]

Resposta campanha REPLIES:
{
  "clicks": "Not available",
  "ctr": "Not available",
  "cpc": "Not available",
  "results": "Not available",
  ...
}
```

### v4-ads — `get_search_terms_report` token cap
```
mcp__v4-ads__get_search_terms_report(
  customer_id="7862230676",
  date_range="LAST_7_DAYS",
  limit=500
)
→ Error: result (193.987 characters) exceeds maximum allowed tokens.
```

---

## Anexo B — Tools chamadas com sucesso (referência positiva)

Pra preservar contexto do que funcionou bem nesta mesma sessão:

| MCP | Tool | Observação |
|---|---|---|
| v4-ads | `get_account_overview` | OK com preset. Comparativo automático embutido. |
| v4-ads | `get_funnel_metrics` | OK com preset. |
| v4-ads | `get_campaign_performance` | OK. Retornou 2 active + 3 PAUSED/REMOVED limpamente. |
| v4-ads | `get_top_keywords_creatives` | Excelente — top keywords + top RSAs com ad_strength em 1 call. |
| v4-ads | `get_device_performance` | OK. |
| v4-ads | `get_negative_keywords_audit` | OK (apesar do gap de `created_date`). |
| Meta | `ads_get_ad_accounts` | OK. Confirmou OAuth + ad_account_id queryable. |
| Meta | `ads_get_dataset_stats` | OK. Volume horário 7 dias por evento. |
| empsis | `faturamento_periodo` | OK. |
| empsis | `ranking_vendedores` | OK. |
| empsis | `equipamentos_mais_locados` | OK. |
| empsis | `clientes_inativos` | OK. Bloco de concentração de receita = bônus valioso. |

---

*Documento gerado em 17/05/2026 a partir de logs reais de execução do relatório semanal MO-JP+CAB de 15/05/2026.*
*Atualizar este documento sempre que novos problemas/melhorias forem identificados em sessões V4 reais.*
