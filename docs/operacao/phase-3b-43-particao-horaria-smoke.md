# Phase 3b.43 — smoke runbook para partição horária (`get_ad_schedule` + `get_performance_breakdown`)

**Estado em 2026-09-04: as tools ganharam os campos desta sprint SÓ no branch `feat/particao-horaria` — `main` segue em `ede7557`, sem nenhum deles. A branch segue recebendo commits (implementação original das Tasks 1-5 + a onda de correções da revisão final) — não copie um HEAD ou uma contagem fixa daqui; confira `git rev-parse HEAD` para o HEAD atual no momento da execução, e `git log --oneline main..feat/particao-horaria` para a lista completa. Nada foi mesclado, nada foi deployado, e o smoke abaixo NÃO foi executado.** Este documento é prospectivo: escreve o roteiro antes da execução, não um relato depois dela.

> ⚠️ **Nenhum passo deste smoke muta.** As duas tools (`get_ad_schedule`, `get_performance_breakdown`) são 100% leitura — nenhuma tem `blast_radius`, nenhuma emite `confirmation_token`, nenhuma toca `campaign_criterion` nem qualquer outro recurso do Google. Diferente do 3b.42 (que tinha dois bloqueadores, um deles reservando 3 dos 10 passos para aval humano por mutação real), este runbook tem **um único bloqueador**, e é de deploy — não de autorização.

**Por que este documento não tem número nenhum "medido agora":** mesmo que o cliente MCP desta sessão exponha `get_ad_schedule`/`get_performance_breakdown`, ele fala com a produção atual (`main` `ede7557`), que **ainda não tem** `include_metrics`, `campaign_ids`+`raw_grid` em `get_performance_breakdown`, nem o combo `campaign`+`hourly` aberto. Uma chamada com esses campos contra o schema antigo seria recusada por `additionalProperties: false` antes mesmo de chegar no handler. Por isso este runbook foi escrito por leitura direta do código-fonte (`src/google_ads/ad_schedule.py`, `src/mcp/tools/get_ad_schedule.py`, `src/google_ads/performance_breakdown.py`, `src/mcp/tools/get_performance_breakdown.py`, `src/google_ads/queries/ad_schedule.py`) e por citação explícita do runbook 3b.42 (já executado, mesma conta) — nunca por chamada MCP nem por número inventado. Onde um valor é citado, a origem vem entre parênteses; onde não há origem, o campo diz explicitamente "medir na execução".

---

**Purpose:** Validar a Task 6 do plano `2026-09-04-particao-horaria` — as duas superfícies que a spec (`docs/superpowers/specs/2026-09-04-particao-horaria-design.md`) abre para responder "comercial, fora de hora ou fim de semana decide o CPA desta campanha?" sem precisar chamar a tool de mutação em dry-run só para ler um número (esse era o problema de origem: a spec nasceu porque JPA teve CPA 18,47 de madrugada contra 24,46 na CAB, mesma conta, mesma janela — número já citado no smoke 3b.42 e comentado em `src/google_ads/performance_breakdown.py:39-42`; ninguém tinha como ver isso sem mutar). As duas tools reusam o mesmo domínio puro (`partition_by_blocks`, `BLOCOS_PADRAO`, `covers` — todos em `src/google_ads/ad_schedule.py`, sem I/O), então o mesmo bug de partição apareceria nas duas se existisse.

- **`get_ad_schedule` + `include_metrics`** (Task 3, commit `43f674e`): flag opt-in que acrescenta `metrics_por_bloco` a cada entrada de `schedule_summary`, sem exigir intenção de mutar — antes, CPA por bloco só existia no preview de `update_ad_schedule`.
- **`get_performance_breakdown` com `level=campaign`+`breakdown=hourly`** (Tasks 4-5, commits `5319727`/`aa80746`/`36cb532`): único combo entity+breakdown aberto além do `level=account` original; devolve partição por default (3 blocos nomeados + `outros`, nunca as 168 células cruas) e `raw_grid: true` para a grade crua, com teto próprio `168 × len(campaign_ids)`.
- **`breakdown=geo` em `level=campaign` continua recusado**, de propósito — é regra de merge de `geoTargetConstant` duplicado, não de nível (medido na spec: `Bayeux` e `Goiana` aparecem com dois ids cada). Fora do escopo desta sprint.

**Operator:** wellington.ribeiro@v4company.com — confirme grant nas duas contas abaixo em `/admin/access` se quem executar for outra pessoa.

**Conta de substância (T1, T2, T3, T4):** `7862230676` — Mestre da Obra João Pessoa, produção V4, cliente real. Gasto real e orçamento compartilhado — é onde a soma dos baldes tem alguma coisa para errar. (T2 usa a mesma chamada de T1, só sem `include_metrics` — ficava órfão deste crosswalk.)
**Conta de forma (T5, T6):** `1163862076` — conta de teste do Wellington, campanhas pausadas, gasto zero. Usada só nos dois testes cuja asserção é sobre o CONTRATO (mensagem de erro, envelope), não sobre o número — poupa a conta de cliente de duas chamadas que não precisam dela.

**Spec:** `docs/superpowers/specs/2026-09-04-particao-horaria-design.md` ("O problema, em um número"; "A decisão de desenho"; "Escopo"; "Limitação do Google")
**Plan:** `docs/superpowers/plans/2026-09-04-particao-horaria.md` (Tasks 1-6) + `.superpowers/sdd/2026-09-04-particao-horaria/progress.md` (9 Rulings registrados durante a implementação)

> **Escopo confirmado:**
> - **Tool count: inalterado.** Zero tools novas — `get_ad_schedule` e `get_performance_breakdown` já existiam (desde o 3b.42/2A) e ganham CAMPOS novos no schema. Último total conhecido: 68 (CLAUDE.md, 2026-09-03); esta sprint não mexe nesse número.
> - **Breaking change: só um, e é expansão, não remoção.** `_validate_combo("campaign", "hourly")` antes devolvia erro PT-BR ("breakdown só é suportado em level='account'"); agora devolve `None` (aceito). Nenhum outro combo muda — `_validate_combo("campaign", "geo")` e `_validate_combo("ad_group", "hourly")` continuam recusados (`tests/unit/test_performance_breakdown.py::test_outros_breakdowns_seguem_recusados_em_entity_level`, task-4-brief). Os dois schemas ganham campos NOVOS e OPCIONAIS (`include_metrics` default `false`; `campaign_ids`/`raw_grid` em `get_performance_breakdown`) — uma chamada pré-sprint, sem esses campos, se comporta exatamente igual a antes.
> - **Zero migration.** Nenhuma task tocou o banco — confirmado nos 5 task reports ("Preocupações": "nenhuma migração, nenhuma mutação, nenhum dado de produção tocado").
> - **F140 se aplica de um jeito DIFERENTE do 3b.42 — leia antes de assumir o sintoma.** No 3b.42, a tool inteira não existia numa sessão antiga, e o sintoma era "tool não encontrada". Aqui, `get_ad_schedule` e `get_performance_breakdown` **já existem** em produção — o que muda é só o SCHEMA. Uma sessão MCP que conectou antes deste deploy carrega o schema ANTIGO (sem `include_metrics`; sem `campaign_ids`/`raw_grid` em `get_performance_breakdown`), e `additionalProperties: false` nos dois schemas faz uma chamada com os campos novos ser recusada — não com "tool não encontrada", mas com um erro de validação de schema citando o campo desconhecido (mesma família da Camada 0 que o 3b.42 T9 documentou: o cliente valida o `inputSchema` antes de qualquer coisa chegar no classificador de auto mode ou no servidor). **Reconecte a sessão MCP depois do deploy, antes de tentar T1.**
> - **Não executado** — branch nem mesclado ainda; ver "Purpose" acima para o porquê deste documento não ter chamadas reais.

### Os blocos de `BLOCOS_PADRAO` (para ler os resultados sem voltar ao código)

Definidos em `src/google_ads/ad_schedule.py`, ladrilham a semana exatamente (soma 168h, guard de célula-a-célula em `tests/unit/test_particao_por_blocos.py::test_os_blocos_padrao_cobrem_cada_celula_exatamente_uma_vez` — Task 2, Ruling 4):

| Bloco | Janela | Horas/semana |
|---|---|---|
| `comercial` | seg-sex 08:00-18:00 | 50h |
| `fora_de_hora` | seg-sex 00:00-08:00 e 18:00-24:00 | 70h |
| `fim_de_semana` | sáb-dom 00:00-24:00 | 48h |
| `outros` | qualquer célula não coberta pelos 3 acima | 0h (lixeira; deveria ficar vazia com estes 3 blocos, que já são totais) |

Cada balde é `{cost_brl, conversions, cpa_brl, cells}` — `cpa_brl` é `None` quando `conversions == 0` (nunca dividir por zero), nunca somado entre blocos (razão não se soma — CLAUDE.md, e é exatamente por isso que a spec deixou `aggregate_by` somando fora do escopo).

**Dados conhecidos pré-smoke (citados do runbook 3b.42, já executado contra esta mesma conta em 2026-09-03/04 — não medidos nesta sessão de escrita):**

- **`7862230676` tem exatamente 2 campanhas não-removidas**, `21359547724` ("[GPC][JPA][LEADS][SEG][MESTRE DA OBRA]") e `22169885957` ("[GPC][CAB][LEADS][SEG][SEX][MESTRE DA OBRA]"), ambas `ENABLED`, ambas no mesmo orçamento compartilhado `15803241252` (R$ 310,00/dia, `explicitly_shared: true`). (`phase-3b-42-ad-schedule-smoke.md`, "Dados conhecidos pré-smoke", medido por `run_gaql` em 2026-09-03/04.)
- **Nenhuma das duas tinha nenhum `campaign_criterion` do tipo `AD_SCHEDULE`, em nenhum status**, confirmado tanto por `run_gaql` quanto pela execução real de `get_ad_schedule` (T1/T2 do 3b.42): `has_schedule: false`, `hours_per_week: 168.0` nas duas. (Idem, + `phase-3b-42-ad-schedule-smoke.md` Teste T1, executado 2026-09-04 05:27 UTC.) Nenhuma mutação rodou contra esta conta desde então (o único `update_ad_schedule` que a tocou, T2b do 3b.42, foi dry-run com token descartado) — o baseline deveria seguir de pé, mas reconfirme por `run_gaql` se a execução divergir muito do que este documento descreve.
- **A conta tem gasto real de milhares de reais por mês nas duas campanhas** — evidência indireta, não uma medição direta deste sprint: o 3b.42 rodou um dry-run de `update_ad_schedule` (grade SEG-SEX 07-17, **diferente** do bloco `comercial` de BLOCOS_PADRAO que é SEG-SEX 08-18) contra as mesmas 2 campanhas, janela 2026-08-05→2026-09-03 (30 dias), e mediu:

  | campanha | "leaving" (fora de seg-sex 07-17) | "staying" (dentro) |
  |---|---|---|
  | `21359547724` JPA | R$ 1.680,76 · 88,67 conv · CPA R$ 18,96 | R$ 5.150,51 · 259,17 conv · CPA R$ 19,87 |
  | `22169885957` CAB | R$ 626,63 · 29,75 conv · CPA R$ 21,06 | R$ 2.025,17 · 106,01 conv · CPA R$ 19,10 |

  (`phase-3b-42-ad-schedule-smoke.md`, Teste T2b, executado 2026-09-04 05:39 UTC.) Somando os dois lados (aritmética minha sobre os números citados, não uma medição nova): JPA ≈ R$ 6.831,27 e CAB ≈ R$ 2.651,80 no período — confirma que a conta tem substância real, mas **não é o número esperado de T1**: aquele preview particionou por SEG-SEX 07-17 (a grade que o dry-run testava), este smoke particiona por `BLOCOS_PADRAO` (comercial SEG-SEX 08-18). São partições diferentes da mesma base de dados — não espere os mesmos R$ 1.680,76/R$ 5.150,51 aparecerem em T1; espere a MESMA ORDEM DE GRANDEZA (milhares de reais no total, não zero) e a MESMA PROPRIEDADE (a soma bate com o total, verificada abaixo por cruzamento, não por comparação com esta tabela).
- **`1163862076`:** usada só em T5/T6, que não dependem de nenhum dado específico da conta (ver setup de cada teste).

---

## Pre-flight — documento APENAS, sem checks automatizados executados

- [x] **Branch local existente:** `git branch --show-current` = `feat/particao-horaria` — confirmado nesta sessão
- [x] **HEAD do branch:** avança a cada commit novo (implementação original das Tasks 1-5 + a onda de correções da revisão final) — confirme o valor atual com `git rev-parse HEAD`, e a lista completa desde `main` com `git log --oneline main..feat/particao-horaria`; não trate um hash copiado aqui como o HEAD de agora
- [x] **`main` não tem nenhum destes commits:** HEAD de `main` é `ede7557` — confirmado por `git log main --oneline -3`
- [x] **Spec lida:** `docs/superpowers/specs/2026-09-04-particao-horaria-design.md` — confirmado
- [x] **Plan + ledger lidos:** `docs/superpowers/plans/2026-09-04-particao-horaria.md` + `.superpowers/sdd/2026-09-04-particao-horaria/progress.md` (9 Rulings) — confirmado
- [x] **Tasks 1-5 entregues**, cada uma com gate `check_pre_push.py` 6/6 e review limpo (Task 2 e Task 5 precisaram de 1 fix round cada; Task 4 não tem relatório escrito — falha de processo registrada no próprio `progress.md`, não de código: o RED foi reconstruído por git pelo revisor) — confirmado via os 5 `task-N-report.md` + `progress.md`
- [x] **Código-fonte das duas tools e do domínio lido linha a linha nesta sessão** (`src/google_ads/ad_schedule.py`, `src/mcp/tools/get_ad_schedule.py`, `src/google_ads/performance_breakdown.py`, `src/mcp/tools/get_performance_breakdown.py`, `src/google_ads/queries/ad_schedule.py`) — as mensagens de erro e formas de resposta citadas abaixo são cópia literal do código, não paráfrase
- [x] **Nenhuma tool MCP chamada, nenhuma conta consultada nesta sessão de escrita** — todo número vem do 3b.42 (já executado) ou está marcado "medir na execução"
- [x] **Nenhum segredo ou credencial será digitado** durante este documento — confirmado
- [ ] **CI local (`check_pre_push.py`)** — roda antes do commit deste documento (é markdown puro; incluído por convenção do repo, não porque se espera que quebre algo)

---

## Smoke results

**Legenda** (mesma do 3b.42, para quando este documento for editado in-place durante a execução): ✅ executado com evidência transcrita aqui · ◐ executado em sessão de campo, detalhe no `findings-catalog.md` · 🚫 tentado e barrado antes de chegar ao MCP · ⬜ não executado.

| # | Teste | Result | Execution Date | Notes |
|---|---|---|---|---|
| T1 | `get_ad_schedule(7862230676, campaign_ids=[JPA, CAB], include_metrics=true)` | ⬜ pending | — | Crítico: soma dos 4 baldes por campanha bate com `get_performance_breakdown(level=campaign)` da mesma campanha (cruzamento obrigatório, ver Teste T1) |
| T2 | a mesma chamada **sem** `include_metrics` | ⬜ pending | — | `metrics_por_bloco` ausente; resposta idêntica a T1 nos demais campos |
| T3 | `get_performance_breakdown(7862230676, level=campaign, breakdown=hourly, campaign_ids=[JPA, CAB])` | ⬜ pending | — | 8 linhas (2×4 baldes), `truncated: false`; cruza com T1 |
| T4 | o mesmo com `raw_grid: true` | ⬜ pending | — | células cruas em `cost_micros` (não `cost_brl`); `truncated` matematicamente `false` (teto 336, ver Failure modes) |
| T5 | `get_performance_breakdown(1163862076, level=campaign, breakdown=geo)` | ⬜ pending | — | continua recusado; zero I/O (recusa antes de `resolve_account_today`) |
| T6 | `get_ad_schedule(1163862076, include_metrics=true)` sem `campaign_ids` | ⬜ pending | — | caminho de erro; opcional, incluído por completude |

**Effective result:** 0/6 executados. Nenhuma tool chamada nesta sessão de escrita (branch não deployado — ver cabeçalho).

### Sign-off checklist — TODO após execução

- [ ] Pre-push gate 6/6 PASS para o commit deste documento
- [ ] Branch mesclado em `main`, CI verde, deploy fechado (`ci.yml` job `deploy`, gated)
- [ ] Sessão MCP reconectada DEPOIS do deploy (F140 — ver nuance no cabeçalho)
- [ ] Produção `/health?deep=1` 200 pós-deploy
- [ ] T1 PASS — `metrics_por_bloco` presente nas 2 campanhas, 4 baldes cada, soma bate com o cruzamento (tolerância ≤ R$0,10 por arredondamento independente)
- [ ] T2 PASS — `metrics_por_bloco` ausente, resto idêntico a T1
- [ ] T3 PASS — 8 linhas, ordem determinística (JPA×4 blocos, CAB×4 blocos), `truncated: false`
- [ ] T4 PASS — grade crua com `cost_micros`, teto 336 respeitado, soma reconcilia com T3
- [ ] T5 PASS — recusado com a mensagem exata citada abaixo, zero I/O
- [ ] T6 PASS — recusado com a mensagem exata citada abaixo, MAS com as 2 queries baratas executadas (1 audit_log entry, resultado descartado)
- [ ] Zero findings novos OU todos catalogados (F### série) com cross-reference
- [ ] `estado-atual.md` atualizado (mover partição horária de "desenhado, não iniciado" para "entregue, smoke ✅" ou o que a execução real mostrar)
- [ ] `sprint-history.md` ganha a entrada da sprint

---

## Teste T1 — `get_ad_schedule(7862230676, include_metrics=true)` — a substância

**Setup:** Esta é a chamada que a Task 3 existe para viabilizar: CPA por bloco sem precisar de intenção de mutar. `include_metrics=true` acrescenta `metrics_por_bloco` a cada entrada de `schedule_summary`, construído chamando `day_hour_metrics_query` (mesma conjunta cara que `update_ad_schedule` já usava no dry-run) e particionando o resultado com `partition_by_blocks(células, BLOCOS_PADRAO)` — a MESMA função de domínio que T3 usa por outro caminho (Task 5). A pré-condição do código é `campaign_ids` obrigatório (senão a conjunta rodaria sobre a conta inteira); por isso a chamada abaixo já inclui os 2 ids conhecidos.

**A asserção que importa (balde que some é o defeito que este repo mais pagou — não pule esta parte):** `partition_by_blocks` promete, por construção, que toda célula cai em exatamente um balde (`src/google_ads/ad_schedule.py`, docstring: "TOTAL por construção"). A forma de checar isso contra dado real, sem precisar de um número pré-conhecido, é comparar contra uma fonte INDEPENDENTE do mesmo total — uma consulta que não passa por `day_hour_metrics_query` nem por `partition_by_blocks` nenhuma vez.

**Tool call (chamada A — a que tem `include_metrics`):**

```
get_ad_schedule(
  customer_id="7862230676",
  campaign_ids=["21359547724", "22169885957"],
  include_metrics=true
)
```

**Tool call (chamada B — cruzamento, OBRIGATÓRIA para fechar o crítico deste teste):**

```
get_performance_breakdown(
  customer_id="7862230676",
  level="campaign"
)
```

*(Sem `breakdown` — cai no builder genérico pré-existente, `campaign_performance_query`, que nunca usa `segments.hour` nem `partition_by_blocks`. É uma rota de código inteiramente diferente da que T1 exercita, e é exatamente por isso que serve de fonte independente.)*

**Nota de timing (leia antes de rodar):** as duas chamadas resolvem `LAST_30_DAYS` de forma independente, cada uma via `resolve_account_today` + `resolve_date_window` (F141 — nunca lê o relógio do servidor, sempre o fuso da conta). Rodando as duas em sequência, na mesma sessão, o dia civil da conta quase certamente não muda entre elas — mas se quiser zero ambiguidade, passe os MESMOS `start_date`/`end_date` explícitos nas duas chamadas (`get_ad_schedule` aceita `date_range`/`start_date`/`end_date`; `get_performance_breakdown` também). `get_ad_schedule` **não devolve** a janela resolvida em nenhum campo do response (diferente de `update_ad_schedule`, que expõe `metrics_window`) — se a comparação abaixo divergir de um jeito que pareça janela desalinhada, essa ausência é a primeira suspeita, não `partition_by_blocks`.

**Expected response shape (chamada A — estrutura confirmada por leitura de código; números a medir):**

```json
{
  "customer_id": "7862230676",
  "windows": [],
  "schedule_summary": {
    "21359547724": {
      "campaign_name": "[GPC][JPA][LEADS][SEG][MESTRE DA OBRA]",
      "campaign_status": "ENABLED",
      "has_schedule": false,
      "windows": 0,
      "hours_per_week": 168.0,
      "budget_is_shared": true,
      "metrics_por_bloco": {
        "comercial": {"cost_brl": "<medir>", "conversions": "<medir>", "cpa_brl": "<medir ou null>", "cells": "<medir>"},
        "fora_de_hora": {"cost_brl": "<medir>", "conversions": "<medir>", "cpa_brl": "<medir ou null>", "cells": "<medir>"},
        "fim_de_semana": {"cost_brl": "<medir>", "conversions": "<medir>", "cpa_brl": "<medir ou null>", "cells": "<medir>"},
        "outros": {"cost_brl": "<medir>", "conversions": "<medir>", "cpa_brl": "<medir ou null>", "cells": "<medir>"}
      }
    },
    "22169885957": { "...": "mesma forma, campanha CAB" }
  },
  "truncated": false
}
```

**Validação:**

- [ ] Response retorna sem `"error"` nas duas chamadas
- [ ] `windows == []` — baseline conhecido (zero criteria); se vier não-vazio, reconfirme por `run_gaql` antes de tratar como bug (baseline pode ter mudado)
- [ ] **Crítico T1:** `schedule_summary` tem exatamente as chaves `"21359547724"` e `"22169885957"`
- [ ] **Crítico T1:** cada entrada de `schedule_summary` tem **7** campos (os 6 de sempre + `metrics_por_bloco`) — se vier com 6, a flag não fez nada; se vier com mais de 7, algo vazou
- [ ] **Crítico T1:** `metrics_por_bloco` tem exatamente as 4 chaves `comercial`, `fora_de_hora`, `fim_de_semana`, `outros`, nesta ordem de inserção (Python preserva ordem de dict; `BLOCOS_PADRAO` declara `comercial`→`fora_de_hora`→`fim_de_semana`, e `outros` é acrescentado por último em `partition_by_blocks`)
- [ ] Cada balde tem exatamente 4 campos: `cost_brl`, `conversions`, `cpa_brl`, `cells`
- [ ] **Nota de tipo, não de bug:** `cost_brl` vem sempre `float` (a divisão por `1_000_000` garante isso mesmo em zero). `conversions` vem `int 0` se o balde não tiver NENHUMA célula (soma de lista vazia em Python é `int`), e `float` (`0.0`, `12.5`, etc.) se tiver células — não é inconsistência, é `sum()` do Python sobre gerador vazio vs. não-vazio. Mesmo comportamento já documentado no 3b.42 T3 para `partition_metrics`, que usa a mesma `_agrega`
- [ ] **Crítico T1 — a soma bate (o cruzamento):** para cada campanha, some `cost_brl` dos 4 baldes (chamada A) e compare com `cost_brl` da MESMA campanha na chamada B. Diferença esperada ≤ R$ 0,10 (arredondamento independente: 4 baldes arredondados a 2 casas cada, vs. 1 total arredondado uma vez). Diferença maior — sobretudo se for uma fração grande do total — é o balde que some: **achado HIGH**, pare antes de prosseguir. Repita para `conversions` (mesma lógica de tolerância). **Não** compare `cpa_brl` diretamente entre os dois lados — CPA não é aditivo, e a chamada B nem devolve CPA por bloco (é grão de campanha inteira)
- [ ] `truncated == false` nas duas chamadas
- [ ] Documente os 2 valores de `cost_brl` de A (soma dos 4 baldes) e B (total direto) lado a lado, por campanha — é a evidência que fecha o crítico deste teste, não só um "PASS" sem número

**Failure modes investigation:**

- `metrics_por_bloco` ausente mesmo com `include_metrics=true` → `args.get("include_metrics", False)` não está lendo o campo (nome errado no schema, ou schema antigo — reconecte a sessão MCP, ver F140 no cabeçalho)
- Soma dos 4 baldes MENOR que o total da chamada B, por uma diferença grande → células "vazando" para fora dos 4 baldes (bug em `covers` ou em `partition_by_blocks` não cobrindo alguma faixa) — comece conferindo se `outros` está anormalmente pequeno, o que indicaria que `BLOCOS_PADRAO` está "roubando" células que deveriam cair lá
- Soma MAIOR que o total → célula contada em mais de um balde (quebra a garantia "exatamente um bloco" — mesma classe de bug que a Task 2 já blindou para o ladrilhamento teórico, mas isso não impede um bug de `covers()` na prática)
- `cpa_brl` não-null com `conversions == 0` → divisão por zero não guardada (contradiz `_agrega`: `cpa_brl = cost/conv if conv > 0 else None`)
- `windows` não-vazio → grade mudou desde o baseline do 3b.42; reconfirme por `run_gaql`, não é falha do sprint

**Result:** ⬜ pending

---

## Teste T2 — a mesma chamada, sem `include_metrics`

**Setup:** Metade do valor da flag é a AUSÊNCIA de consulta quando ela não é pedida (comentário do próprio código: "SEM a flag nenhuma consulta dia x hora sai — metade do valor da flag e essa ausencia"). Este teste prova isso pelo único jeito observável de fora: a chave não aparece. **Não é possível provar "a consulta cara não saiu" pelo `audit_log`** — mesmo COM a flag, a conjunta dia×hora nunca é auditada separadamente (`_consulta(day_hour_metrics_query(...), parse_day_hour_row)` é chamada sem `audited=True`; só a consulta de grade tem `audited=True`). Ou seja: T1 e T2 devem mostrar o MESMO número de entradas novas em `audit_log` (1, sempre) — a diferença observável está só na resposta, nunca no audit trail. Não escreva uma asserção sobre audit_log "provando" ausência de consulta; ela não prova.

**Tool call:**

```
get_ad_schedule(
  customer_id="7862230676",
  campaign_ids=["21359547724", "22169885957"]
)
```

**Expected response shape:**

```json
{
  "customer_id": "7862230676",
  "windows": [],
  "schedule_summary": {
    "21359547724": {
      "campaign_name": "[GPC][JPA][LEADS][SEG][MESTRE DA OBRA]",
      "campaign_status": "ENABLED",
      "has_schedule": false,
      "windows": 0,
      "hours_per_week": 168.0,
      "budget_is_shared": true
    },
    "22169885957": { "...": "idêntico, campanha CAB" }
  },
  "truncated": false
}
```

**Validação:**

- [ ] Response retorna sem error
- [ ] **Crítico T2:** cada entrada de `schedule_summary` tem exatamente **6** campos — sem `metrics_por_bloco`
- [ ] Todos os demais campos idênticos aos de T1 (`windows`, `has_schedule`, `hours_per_week`, `budget_is_shared`, `campaign_status`, `campaign_name`) — as duas queries baratas (`ad_schedule_query`, `campaign_budget_query`) não dependem de `include_metrics`
- [ ] Exatamente **1** entrada nova em `audit_log`, `operation: "get_ad_schedule"` — mesmo número de T1 (ver Setup: a ausência da flag não muda a contagem de audit, só a resposta)
- [ ] `truncated == false`

**Failure modes investigation:**

- `metrics_por_bloco` presente mesmo sem a flag → `args.get("include_metrics", False)` tratando `None`/ausência como truthy (bug de default)
- Resposta diverge de T1 em algum campo além de `metrics_por_bloco` → as duas queries baratas não deveriam ser afetadas pela flag; investigar se `include_metrics` está sendo lido antes de montar `summary` (não deveria — o código lê a flag DEPOIS de montar `summary`, ver Task 3 report)

**Result:** ⬜ pending

---

## Teste T3 — `get_performance_breakdown(level=campaign, breakdown=hourly)` — a partição, no outro caminho de código

**Setup:** Mesma pergunta de T1 ("CPA por bloco"), caminho de integração diferente (Task 5, não Task 3) — mas a MESMA função de domínio (`partition_by_blocks(_, BLOCOS_PADRAO)`). Se T1 e T3 divergirem para as mesmas campanhas na mesma janela, o bug está na fiação de um dos dois call-sites, não no domínio (que T1 já teria validado contra a fonte independente).

**Tool call:**

```
get_performance_breakdown(
  customer_id="7862230676",
  level="campaign",
  breakdown="hourly",
  campaign_ids=["21359547724", "22169885957"]
)
```

**Expected response shape (estrutura confirmada por leitura de código; números a medir):**

```json
{
  "customer_id": "7862230676",
  "level": "campaign",
  "breakdown": "hourly",
  "period": {"from": "<YYYY-MM-DD>", "to": "<YYYY-MM-DD>"},
  "rows": [
    {"campaign_id": "21359547724", "bloco": "comercial", "cost_brl": "<medir>", "conversions": "<medir>", "cpa_brl": "<medir ou null>", "cells": "<medir>"},
    {"campaign_id": "21359547724", "bloco": "fora_de_hora", "...": "..."},
    {"campaign_id": "21359547724", "bloco": "fim_de_semana", "...": "..."},
    {"campaign_id": "21359547724", "bloco": "outros", "...": "..."},
    {"campaign_id": "22169885957", "bloco": "comercial", "...": "..."},
    {"campaign_id": "22169885957", "bloco": "fora_de_hora", "...": "..."},
    {"campaign_id": "22169885957", "bloco": "fim_de_semana", "...": "..."},
    {"campaign_id": "22169885957", "bloco": "outros", "...": "..."}
  ],
  "truncated": false
}
```

**Validação:**

- [ ] Response retorna sem `"error"` — **nota:** este envelope de sucesso NÃO tem chave `"status"` (foi removida no fix round 1 da Task 5 para uniformizar com o caminho genérico da mesma tool — `status` só aparece na resposta de erro)
- [ ] **Crítico T3:** `len(rows) == 8` — exatamente 2 campanhas × 4 baldes
- [ ] **Crítico T3 (ordem determinística):** `rows` vem na ordem `campaign_ids` (loop externo) × ordem de `BLOCOS_PADRAO` + `outros` (loop interno) — ou seja, as 4 linhas de `21359547724` (comercial, fora_de_hora, fim_de_semana, outros) vêm antes das 4 de `22169885957`, nesta ordem de bloco em cada grupo. Se vier em outra ordem, documente — não é necessariamente bug, mas contradiz o código lido nesta sessão
- [ ] `period.from`/`period.to` presentes, formato `YYYY-MM-DD` — **note os dois valores**: são a única forma de saber a janela real usada (ao contrário de `get_ad_schedule`, que não expõe isso em T1/T2)
- [ ] `truncated == false`
- [ ] Cada linha tem exatamente 6 campos: `campaign_id`, `bloco`, `cost_brl`, `conversions`, `cpa_brl`, `cells`
- [ ] **Nota de forma (não é bug):** `status` do schema (default `"enabled"`) é **ignorado** neste combo — `day_hour_metrics_query` não filtra por status de campanha nenhum, só por `campaign_ids` e data. Não afeta este teste (as 2 campanhas já são `ENABLED`), mas se um dia alguém passar um `campaign_id` `PAUSED`/`REMOVED` aqui esperando que `status="enabled"` o exclua, vai se surpreender — ele aparece igual, com o custo real que teve no período
- [ ] Exatamente **1** entrada nova em `audit_log`, `operation: "get_performance_breakdown"` (aqui, diferente de `get_ad_schedule`, a conjunta cara É a única query do combo, e É auditada sempre — `audit_this_call=True` incondicional no bloco `campaign+hourly`)
- [ ] **Crítico T3 (cruza com T1):** para cada campanha, os 4 baldes daqui devem bater com os 4 baldes de `metrics_por_bloco` em T1 para a MESMA campanha — mesma tolerância de arredondamento (≤ R$0,05 por campo, comparação bloco a bloco desta vez, não só a soma). Se T1 já passou e este teste divergir dele, o bug está especificamente na fiação da Task 5 (este arquivo), não no domínio partilhado

**Failure modes investigation:**

- `len(rows) != 8` → `_validate_combo`/builder rejeitando o combo (schema antigo — reconecte, F140) ou algum `campaign_id` não encontrado (célula zerada silenciosamente, não erro — ver nota abaixo)
- Envelope antigo (`{"status": "ok", "rows": [...], "truncated": ...}` sem `customer_id`/`level`/`breakdown`/`period`) → branch desatualizado; o fix round 1 da Task 5 (commit `36cb532`) uniformizou isso — qualquer commit anterior a ele (ex.: `aa80746`) ainda tem o envelope antigo. Confirme que está rodando o HEAD ATUAL da branch `feat/particao-horaria` (`git rev-parse HEAD`), não um commit congelado citado num documento: `36cb532` já deixou de ser HEAD (a branch ganhou a onda de correções da revisão final depois dele) e vai continuar avançando
- `period` ausente → mesmo sintoma acima
- Alguma linha com `cost_brl: 0.0` e `cells: 0` numa campanha que sabidamente tem gasto → não é bug por si (ver nota abaixo), mas confira se É a campanha errada por engano
- **(Não-bug, mas vale saber):** se `campaign_ids` incluir um id que não existe ou é de outra conta, `day_hour_metrics_query` simplesmente não devolve linha nenhuma para ele — os 4 baldes daquele `campaign_id` vêm inteiramente zerados (`cost_brl: 0.0, conversions: 0/0.0, cpa_brl: null, cells: 0`), sem erro. Não deveria acontecer aqui (os 2 ids foram confirmados por `run_gaql` no 3b.42), mas se acontecer não é a mesma classe de bug que "balde que some" — é campanha errada no input

**Result:** ⬜ pending

---

## Teste T4 — o mesmo com `raw_grid: true` — a grade crua, e a unidade muda

**Setup:** Mesmo combo de T3, `raw_grid: true` troca a partição pelas células cruas — o caminho que a spec rejeitou como default (168 células por campanha estouram o `limit` padrão antes de terminar UMA campanha), mas que continua disponível sob flag explícita, com teto próprio. **Armadilha de forma:** as células cruas usam `cost_micros` (int, não convertido), não `cost_brl` — são literalmente o dict de `parse_day_hour_row`, sem passar por `_agrega`. Um consumidor que espere o mesmo nome de campo do caminho particionado (T3) vai procurar `cost_brl` aqui e não achar.

**Tool call:**

```
get_performance_breakdown(
  customer_id="7862230676",
  level="campaign",
  breakdown="hourly",
  campaign_ids=["21359547724", "22169885957"],
  raw_grid=true
)
```

**Expected response shape:**

```json
{
  "customer_id": "7862230676",
  "level": "campaign",
  "breakdown": "hourly",
  "period": {"from": "<YYYY-MM-DD>", "to": "<YYYY-MM-DD>"},
  "rows": [
    {"campaign_id": "21359547724", "day_of_week": "<MONDAY..SUNDAY>", "hour": "<0..23>", "cost_micros": "<medir, int>", "conversions": "<medir, float>"},
    "... uma linha por (campanha, dia, hora) com QUALQUER atividade no período — nao 168 x 2 ..."
  ],
  "truncated": false
}
```

**Validação:**

- [ ] Response retorna sem error
- [ ] **Crítico T4 (nome de campo, não confundir com T3):** cada linha tem `campaign_id`, `day_of_week`, `hour`, `cost_micros`, `conversions` — **não** tem `bloco`, `cost_brl` nem `cpa_brl`. `cost_micros` é o valor cru do Google (multiplicado por 1.000.000), não convertido
- [ ] **Crítico T4:** `truncated == false` — e isto não é uma expectativa estatística, é matemático: `day_hour_metrics_query` agrega por `(campaign.id, segments.day_of_week, segments.hour)` **sem** `segments.date`, então o teto físico é `7 dias × 24 horas = 168` linhas por campanha, sempre, para QUALQUER janela de data. Com 2 campanhas, o teto é `168 × 2 = 336`, e `len(rows)` não pode matematicamente ultrapassar isso — só dado sintético consegue (é como os testes de unidade da Task 5 provam truncamento; task-5-report, "Preocupações" item 1). Se `truncated` vier `true` aqui, é uma contradição estrutural grave, não ruído
- [ ] `len(rows)` provavelmente bem abaixo de 336 — só combinações dia×hora com QUALQUER custo ou conversão no período viram linha (célula sem nenhuma atividade não aparece; mesmo padrão já observado no 3b.42 T2b, onde uma campanha teve 49 células em vez de 50 possíveis)
- [ ] `period.from`/`period.to` idênticos aos de T3 (mesmo combo, mesma resolução de data — só o `raw_grid` muda)
- [ ] Exatamente **1** entrada nova em `audit_log`, `operation: "get_performance_breakdown"`
- [ ] **Crítico T4 (cruza com T3, mesmo tool, mesma query):** para cada campanha, converta `cost_micros` para BRL (`/1_000_000`) e some todas as linhas dessa campanha; conversions, some direto. Compare com a soma dos 4 baldes de T3 para a MESMA campanha. Aqui a tolerância pode ser mais apertada que a de T1 (≤ R$0,05): T3 e T4 usam o **mesmo** `day_hour_metrics_query`, só a apresentação difere — se divergirem por mais que arredondamento, o bug está especificamente em `partition_by_blocks` ou no loop de agrupamento por `campaign_id`, não na query

**Failure modes investigation:**

- `truncated == true` → contradição matemática (ver Crítico acima); reportar como achado HIGH, algo está gerando mais de 168 linhas por campanha, o que não deveria ser possível com esta query
- `cost_brl` aparece em vez de `cost_micros` → `raw_grid` não está de fato pulando `_agrega`/`partition_by_blocks`; branch errado
- Soma de T4 diverge muito da soma de T3 para a mesma campanha → bug no loop `for cid in campaign_ids: do_cid = [... if m["campaign_id"] == cid]` (vazamento de células entre campanhas — mesma classe de bug que o teste `test_campaign_hourly_duas_campanhas_teto_multiplica_e_celulas_nao_vazam` da Task 5 já cobre com dado sintético; aqui é a confirmação com dado real)
- `len(rows) > 336` → teto não está sendo aplicado (`celulas[:teto]` ausente ou com o `teto` errado)

**Result:** ⬜ pending

---

## Teste T5 — `breakdown=geo` em `level=campaign` continua recusado

**Setup:** Único combo que a Task 4 deixou de propósito FORA (geo é regra de merge de `geoTargetConstant`, não mudança de nível — spec, "Escopo", "Fora, declarado"). Diferente do 3b.42 T9 (validação de minuto), aqui `"geo"` é um valor **válido** no enum do schema (`breakdown: {"enum": ["device", "geo", "hourly"]}`) — a recusa não acontece na Camada 0/1 (schema), acontece dentro do handler, em `_validate_combo`. Por isso este teste não tem a ambiguidade de camadas que o 3b.42 T9 documentou: se a mensagem abaixo aparecer, ela SÓ pode ter vindo do código do repo, não de validação de schema genérica.

**Zero I/O:** `_validate_combo(level, breakdown)` roda **antes** de `resolve_account_today` — a recusa acontece sem nenhuma chamada ao Google, sem resolver fuso, sem tocar `audit_log`. Por isso a conta usada aqui é a de teste (`1163862076`): o `customer_id` passa pela validação de schema (`pattern: ^[0-9]{10}$`) mas nunca é efetivamente usado antes do erro.

**Tool call:**

```
get_performance_breakdown(
  customer_id="1163862076",
  level="campaign",
  breakdown="geo"
)
```

**Expected result (texto exato, copiado de `src/google_ads/performance_breakdown.py::_validate_combo`):**

```json
{
  "status": "error",
  "error_message": "breakdown só é suportado em level='account' no v0 (você pediu level='campaign'). Use level='account' + breakdown, ou remova o breakdown."
}
```

**Validação:**

- [ ] **Crítico T5:** `status == "error"`
- [ ] **Crítico T5:** `error_message` bate **exatamente** com o texto acima, incluindo os acentos (`só`, `é`, `você`) — esta mensagem específica, ao contrário de outras do mesmo arquivo, usa acentuação normal, não ASCII substituído; se vier sem acento, documente (pode indicar transporte/encoding alterando a string)
- [ ] Zero entradas novas em `audit_log` para este customer_id — a recusa acontece antes de qualquer I/O
- [ ] Rode também `get_performance_breakdown(customer_id="1163862076", level="ad_group", breakdown="hourly")` como checagem adjacente (não crítica): deve recusar igual — só `campaign`+`hourly` abriu, nenhum outro nível ganhou o combo (`tests/unit/test_performance_breakdown.py::test_outros_breakdowns_seguem_recusados_em_entity_level`, já cobre isso via teste de unidade; aqui é só confirmar que a regra sobreviveu contra uma chamada MCP real)

**Failure modes investigation:**

- `status` != `"error"` ou resposta com `rows` → `_validate_combo` parou de recusar `campaign`+`geo` (regressão grave: geo por cidade tem bug de merge conhecido e documentado na spec — não deveria nunca chegar a rodar)
- Mensagem com texto diferente do citado → `_validate_combo` foi editado depois da leitura desta sessão; concatene a mensagem real acima deste bullet para o próximo runbook citar
- Alguma entrada aparece em `audit_log` → a recusa deixou de ser o primeiro passo da função (regressão de ordem — reintroduziria custo de quota para uma chamada que deveria ser grátis)

**Result:** ⬜ pending

---

## Teste T6 — `get_ad_schedule(include_metrics=true)` sem `campaign_ids` — caminho de erro (opcional, incluído)

**Setup:** O pré-flight que impede a conjunta cara de rodar sobre a conta inteira. Diferente de T5, este NÃO é I/O zero: as duas queries baratas (`ad_schedule_query`, `campaign_budget_query`) já rodaram, em paralelo, ANTES do bloco `if include_metrics` sequer ser avaliado — o código monta `summary` primeiro, e só verifica `campaign_ids` depois, dentro do `if include_metrics`. O resultado dessas duas queries baratas é **descartado**: a resposta ao chamador é só `{status, error_message}`, sem `windows`/`schedule_summary`/`truncated`, mesmo esses três já tendo sido computados internamente.

**Tool call:**

```
get_ad_schedule(
  customer_id="1163862076",
  include_metrics=true
)
```

**Expected result (texto exato, copiado de `src/mcp/tools/get_ad_schedule.py`):**

```json
{
  "status": "error",
  "error_message": "include_metrics exige campaign_ids: a conjunta dia x hora e cara e nao roda sobre a conta inteira."
}
```

**Validação:**

- [ ] **Crítico T6:** `status == "error"`, `error_message` bate exatamente com o texto acima (sem acentos — esta mensagem usa "nao"/"e", ASCII puro, diferente da de T5)
- [ ] **Crítico T6:** a resposta **não** tem `windows`, `schedule_summary` nem `truncated` — só as 2 chaves acima, mesmo as queries baratas tendo rodado
- [ ] **Crítico T6:** exatamente **1** entrada nova em `audit_log`, `operation: "get_ad_schedule"` — prova de que as 2 queries baratas rodaram de verdade (a auditada é `ad_schedule_query`) mesmo com a resposta final sendo um erro
- [ ] `campaign_ids=[]` (lista vazia explícita, em vez de omitido) **não** chega neste mesmo caminho — o schema de `get_ad_schedule` tem `minItems: 1` em `campaign_ids`, então uma lista vazia é recusada na validação de schema (Camada 0/1), antes do handler. Se quiser exercitar essa variante, espere um erro de schema genérico, não o texto PT-BR acima — não é obrigatório para este smoke, mas documente se tentar

**Failure modes investigation:**

- `status` != `"error"` com `campaign_ids` de fato ausente → pré-flight não está checando `not campaign_ids` corretamente (ex.: só checa `is None`, deixando `[]` escapar — mas `[]` já é barrado por schema antes de chegar aqui, então isso só importaria se o schema mudasse)
- `windows`/`schedule_summary` aparecem na resposta de erro → o `return` do bloco de erro não está de fato substituindo o dict final; vazamento de dado que a tool não deveria expor neste caminho
- Zero entradas em `audit_log` → as duas queries baratas deixaram de rodar antes do check (mudança de ordem em relação ao código lido nesta sessão — não é bug por si, mas contradiz a Nota de forma acima e vale reconfirmar contra o código antes de aceitar)
- **Nota, não achado:** este é o análogo, em `get_ad_schedule`, do guard que `get_performance_breakdown` já tem para `campaign`+`hourly` sem `campaign_ids` (mensagem irmã: `"level='campaign' + breakdown='hourly' exige campaign_ids: ..."`, coberta por `tests/unit/test_performance_breakdown.py::test_campaign_hourly_exige_campaign_ids`). Não repetido aqui como teste separado — mesma forma de guard, já coberto por unidade, smoke não precisa duplicar

**Result:** ⬜ pending

---

## Notas operacionais pós-execução

🔴 **Antes de tentar: reconecte o MCP — mas leia a nuance do F140 no cabeçalho antes de assumir o sintoma.** Aqui não é "tool não encontrada" (a tool já existe desde o 3b.42/2A); é schema desatualizado recusando os campos novos. Se `include_metrics`/`campaign_ids`+`raw_grid` derem erro de validação em vez de rodar, é isso — reconecte, não investigue o handler.

🔴 **Não assere igualdade estrita entre leituras de métrica separadas por segundos.** Mesma nota do 3b.42 final: eventual consistency entre réplicas do backend do Google pode fazer duas leituras próximas no tempo discordarem por uma fração pequena, sem que seja bug. As tolerâncias sugeridas em cada teste (≤ R$0,05-0,10) já assumem isso — divergência DENTRO da tolerância não é motivo para investigar; divergência GRANDE (dezenas de reais, ou uma fração relevante do total) é.

🔴 **Ordem sugerida de execução: T5 → T6 → T1 → T2 → T3 → T4.** T5 e T6 não dependem de nenhum estado (rodam em qualquer ordem, contra a conta de teste). T1 deve rodar antes de T3/T4 porque T3/T4 citam "cruza com T1" nas suas próprias validações — inverter a ordem não quebra nada, mas obriga a voltar e reconferir depois.

1. Se qualquer T falhar: criar finding `F###` com severidade apropriada (HIGH se a soma dos baldes não bate com o total independente — é exatamente o cenário que motivou o aviso "balde que some é o defeito que este repo mais pagou" — MED nos demais casos de leitura)
2. Se todas as T passarem: atualizar `docs/operacao/estado-atual.md` (a entrada atual diz "Sprint desenhado, não iniciado" — linha 105 na sessão em que este documento foi escrito; precisa virar "entregue, smoke ✅" ou o que a execução mostrar) e `docs/operacao/sprint-history.md` com a entrada da sprint
3. Depois do merge, confirmar tool count em produção (deveria seguir 68 — nenhuma tool nova, só schema) e os 2 schemas nos metadados do MCP, para fechar o "Escopo confirmado" do cabeçalho

---

## Referências

- Spec: `docs/superpowers/specs/2026-09-04-particao-horaria-design.md`
- Plan: `docs/superpowers/plans/2026-09-04-particao-horaria.md` (Tasks 1-6)
- Ledger: `.superpowers/sdd/2026-09-04-particao-horaria/progress.md` (9 Rulings)
- Task reports: `.superpowers/sdd/2026-09-04-particao-horaria/task-{1,2,3,5}-report.md` (Task 4 sem relatório escrito — ver Ruling/nota no `progress.md`)
- Runbook irmão, mesma conta, fonte dos números citados na seção "Dados conhecidos": `docs/operacao/phase-3b-42-ad-schedule-smoke.md`
- Findings: `docs/operacao/findings-catalog.md`
- Estado: `docs/operacao/estado-atual.md`
