# Dogfood 2026-05-25 — Primeiros findings reais Meta Ads via `meta_list_my_ad_accounts`

> **Contexto:** Smoke real Sprint M.2a T2 — primeira chamada Meta MCP tool em produção. Wellington fez OAuth Meta, conectou conta Facebook pessoal `wellington.ribeiro.eng@gmail.com`, sincronizou 12 ad accounts do Business Manager **V4 Lima Soares & Co** (`act_*` IDs). Tool retornou TODOS os campos esperados com PT-BR labels. **3 real biz findings observados pra investigação Wellington fora-MCP.**

> **Sprint context:** [Sprint M.2a signoff](../superpowers/specs/2026-05-24-sprint-m2a-meta-oauth-first-tool-design.md). Esses findings NÃO são bugs do MCP — são situações biz nas contas Meta clientes que valem investigação ou ação.

---

## Inventory completo das 12 ad accounts sincronizadas

| Tipo | Total |
|---|---|
| ATIVAS | 10 |
| PAGAMENTO_PENDENTE | 1 (ML Antiguidades CA) |
| FECHADO | 1 (WJX Construções) |
| Personal (sem Business Manager) | 1 (Wellington Ribeiro) |
| Sob BM "V4 Lima Soares & Co" | 11 |

Currency: BRL (12/12). Timezone: America/Sao_Paulo (10), America/Manaus (1, SedLoc Manaus), America/Recife (1, Wellington personal).

---

## Finding D1 — ML Antiguidades CA: status PAGAMENTO_PENDENTE

| Campo | Valor |
|---|---|
| `ad_account_id` | `act_370008662` |
| `account_name` | **"CA - ML Antiguidades (Ativo)"** ⚠️ nome diz "Ativo" mas status real é diferente |
| `business_id` | `263981595372142` |
| `business_name` | "ML Antiguidades" |
| `account_status` | 3 (`PAGAMENTO_PENDENTE`) |
| Currency | BRL |
| Timezone | America/Sao_Paulo |

**Severidade:** 🟡 MED. Conta MAY estar bloqueada de exibir anúncios devido a billing issue. Nome mente sobre o status real.

**Investigação Wellington (fora-MCP):**
1. Acessar Meta Business Suite → ML Antiguidades → Billing → ver método de pagamento + invoices pendentes
2. Confirmar com cliente ML Antiguidades se billing issue intencional (pause planejado) ou esquecido
3. Renomear conta de "CA - ML Antiguidades (Ativo)" → algo coerente com status real

**Cross-reference:** ML Antiguidades também tem Sprint 3b.37 EMERGENCY documentada — 5 PURCHASE primary actions zero conv em 30d no Google Ads. Tracking pixel issue suspeito ATRAVÉS de plataformas. Investigation candidate dedicada.

---

## Finding D2 — Mestre da Obra Cotia: 2 ad accounts duplicadas

| Account #1 | Account #2 |
|---|---|
| `act_2337133646484970` | `act_24879253358328154` |
| `account_name`: "[Cotia] MDO" | `account_name`: "Mestre da Obra - Cotia" |
| `business_id`: `190122423536399` | `business_id`: `190122423536399` (mesmo BM) |
| `business_name`: "Mestre da obra - Cotia - SP" | "Mestre da obra - Cotia - SP" |
| account_status: 1 (ATIVO) | account_status: 1 (ATIVO) |

**Severidade:** 🟡 MED. Duplicação histórica — provavelmente conta legacy + conta nova coexistindo. Risk: budget fragmentado, duplicidade de campanhas, dificuldade analytics consolidada.

**Investigação Wellington (fora-MCP):**
1. Acessar Meta Business Suite → ambas contas Cotia → verificar:
   - Qual tem campanhas ativas atualmente?
   - Qual tem histórico de spend mais recente?
   - Qual é a "oficial" pro cliente?
2. Plano: migrar campanhas pra conta principal + arquivar conta secundária (ou marcar account_name=`[ARCHIVED]` no nome pra reconhecimento futuro)
3. Cross-reference Google: cliente Cotia no Google MCC é `customer_id 5894449831` — verificar consistência cross-platform

**MCP implication:** quando Meta tools de spend reporting entrarem (M.3+ `meta_get_account_overview`), espalhar duplicação visível ao gestor. M.2b decision: pode adicionar warning automático em `meta_list_my_ad_accounts` quando 2+ accounts compartilham `business_name`? Hold YAGNI por agora.

---

## Finding D3 — WJX Construções: account_status FECHADO

| Campo | Valor |
|---|---|
| `ad_account_id` | `act_773918051591274` |
| `account_name` | "WJX Construções" |
| `business_id` | `396342731231134` |
| `business_name` | "WJX Construções e Serviços de Engenharia LTDA." |
| `account_status` | **101 (`FECHADO`)** |

**Severidade:** 🟢 LOW. Conta fechada mas ainda visível no BM Wellington. Tools de spend/campaign listing vão retornar erro ou empty pra essa conta — não bloqueia outras 11.

**Investigação Wellington (fora-MCP):**
1. Confirmar com cliente WJX se intencional (encerramento contrato V4) ou erro
2. Se intencional: pode remover acesso Wellington ao ad account no BM (cleanup)
3. Se erro: re-abrir conta

**MCP implication:** quando Meta tools que aceitam `ad_account_id` input entrarem (M.3+), seria útil ter validação pre-flight bloqueando ad_account_id com status=101/201/202 (FECHADO/FECHAMENTO_PENDENTE/LIQUIDAÇÃO_PENDENTE). Sprint M.3+ candidate.

---

## Observações cross-platform Google ↔ Meta

Inspeção das 12 Meta accounts vs 25 Google accounts (Sprint M.1 `list_my_accounts`):

| Cliente | Google MCC | Meta BM | Cross-platform? |
|---|---|---|---|
| Mestre da Obra Cotia | `5894449831` | `act_2337...` + `act_24879...` (DUP) | ✅ |
| 3 Lagoas Locações | `3237459217` | `act_1470682461507188` | ✅ |
| ICSER | `4226457109` | `act_1489398022911451` | ✅ |
| Fardim Tintas | `9409785962` | `act_1742450026462797` | ✅ |
| SedLoc Manaus | `2330543488` | `act_1128439142303593` (BM "SedLoc Manaus") | ✅ |
| Imperial Alimentos | `8726746966` | `act_1648706246292124` | ✅ |
| ML Antiguidades | `7455088726` | `act_370008662` (PAGAMENTO_PENDENTE) | ✅ |
| Dr. Dérick Vinhas | `4493906974` | `act_4051924171730156` | ✅ |
| Dra. Paula Minchillo | (não consta MCC) | `act_1479232423809572` | Meta-only |
| Wellington Ribeiro (personal) | n/a | `act_383566922510173` | Personal-only |
| WJX Construções | (não consta MCC) | `act_773918051591274` (FECHADO) | Meta-only |

**Insights:**
- **9 clientes V4 têm presença cross-platform** (Google + Meta) — Sprint M.2b `meta_get_account_overview` desbloqueia análise comparativa spend/results
- **2 clientes Meta-only** (Dra. Paula Minchillo + WJX) — não estão no MCC Google. Worth verificar com cliente se interesse em Google Ads ou se Meta-exclusive intencional
- **Cliente Pedro Vytor** (Google MCC `?`) não aparece na Meta list — pode ser conta sem ads_management permission pra Wellington, ou Google-exclusive

---

## Pra fazer (Wellington manual fora-MCP)

| Action | Owner | Estimativa |
|---|---|---|
| Diagnose ML Antiguidades CA pagamento pendente | Wellington + cliente | 30 min |
| Decisão Mestre da Obra Cotia duplicação (manter qual, arquivar outra) | Wellington + cliente | 1h |
| Confirmação WJX FECHADO intencional | Wellington + cliente | 15 min |
| Validar 2 clientes Meta-only (Dra. Paula, WJX) — interesse Google Ads? | Wellington | 30 min |

---

## Pra M.2b ou M.3+ MCP candidates (derivadas do dogfood)

| Candidate | Sprint sugerido | Notes |
|---|---|---|
| Pre-flight validation: bloquear `ad_account_id` com status FECHADO/PENDENTE em tools mutates | M.3+ | Mesmo padrão validate_keyword_criterion_types (F43) |
| Warning automático em `meta_list_my_ad_accounts` quando 2+ accounts compartilham `business_name` | YAGNI — wait | Hold demand-driven |
| `meta_get_account_overview` (M.2b) — adicionar field `account_status_label` no header pra alertar status PAGAMENTO_PENDENTE/FECHADO antes do gestor pedir relatório | M.2b refinement | Low effort, alto valor UX |

---

**Última atualização:** 2026-05-25 (Sprint M.2a signoff).
