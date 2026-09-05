# Phase 3b.44 — smoke runbook para `bid_modifier` por janela (`update_ad_schedule` + `apply_change`)

> 🔴🔴 **ESTE SMOKE MUTA CONTA REAL — LEIA ANTES DE EXECUTAR QUALQUER PASSO.** Diferente do
> 3b.43 (100% leitura), todo teste abaixo a partir do "Setup" cria, altera ou remove
> `campaign_criterion` de verdade. **O gestor precisa autorizar CADA rodada de mutação NA
> PRÓPRIA SESSÃO QUE EXECUTA** — aval relayado por outra sessão Claude **não passa** no
> classificador de auto mode do harness. Isso não é hipótese: foi **medido em 04/09** —
> `phase-3b-42-ad-schedule-smoke.md` registra que **T2b** (conta de cliente, `7862230676`)
> e **T3** (esta mesma conta de teste, `1163862076`, campanha PAUSED, **dry-run**) foram
> recusados **de forma idêntica** pelo classificador na primeira tentativa, e os dois só
> passaram na segunda, depois de o Wellington autorizar **com as próprias palavras**, na
> sessão que executava. **Nem dry-run, nem conta de teste, isentam** — os dois eram dry-run
> e um deles já era esta conta de teste. Repetido no `estado-atual.md`: "cada rodada precisa
> do aval do Wellington na sessão que executa: aval relayado por sessão-par não passa no
> classificador." Não agende nem tente rodar isto sem o gestor presente na sessão.

**Estado em 2026-09-04: as tools ganharam o campo desta sprint SÓ no branch
`feat/bid-modifier-por-janela` — `main` segue em `e57f513`, sem nenhum deles.** HEAD do
branch no momento desta escrita: `9a718b3` (Task 5 completa); este commit da documentação
avança mais um. Confira `git rev-parse HEAD` para o HEAD atual no momento da execução, e
`git log --oneline main..feat/bid-modifier-por-janela` para a lista completa de commits.
Nada foi mesclado, nada foi deployado, e **o smoke abaixo NÃO foi executado**. Este documento
é prospectivo: escreve o roteiro antes da execução, não um relato depois dela — todo
`Result` está `⬜ pending`.

**Por que este documento não inventa número nenhum "medido agora":** esta sessão de escrita
**não chamou nenhuma tool MCP `v4-ads` e não consultou nenhuma conta**. Todo número técnico
abaixo vem de uma de três fontes, sempre citada: (1) leitura direta do código-fonte desta
sprint (`src/google_ads/ad_schedule.py`, `src/mcp/tools/update_ad_schedule.py`,
`src/mcp/tools/apply_change.py`, `src/google_ads/mutates/ad_schedule.py`,
`src/google_ads/queries/ad_schedule.py`, `src/governance/dry_run.py`); (2) os testes que
fecham o F149 (`tests/unit/test_update_ad_schedule.py`,
`tests/unit/test_ad_schedule_domain.py`, `tests/unit/test_apply_change_ad_schedule.py`),
cujos fixtures este runbook **reaproveita literalmente** contra a conta real, em vez de
inventar valores novos; (3) o runbook irmão já executado contra esta mesma conta e mesma
tool, `phase-3b-42-ad-schedule-smoke.md`. Onde nenhuma das três se aplica, o campo diz
`<medir>` explicitamente.

---

**Purpose:** Validar a Task 6 do plano `2026-09-04-bid-modifier-por-janela` — fechar o que
o **F149** (`findings-catalog.md`) deixou aberto: `update_ad_schedule` aceitava `bid_modifier`
só como escalar por chamada, então mudar o lance de **uma** faixa horária exigia duas
chamadas, e entre elas a campanha servia ~50 de 168 horas (inundando a campanha irmã em
orçamento compartilhado). A origem do finding, para não perder o fio: a análise da MO-JP em
04/09 achou sinal **oposto** por campanha — "JPA fora de hora com CPA 18,47 contra 19,87 no
comercial; CAB fora de hora 24,46 contra 18,60 no fim de semana" (F149, findings-catalog.md)
— e a execução esbarrou exatamente nesta limitação de superfície.

**O que a sprint entregou** (Tasks 1-5, todas `complete`, ver `progress.md`):

- **`Window` ganha `bid_modifier: float | None`** como atributo — `key()` (5 posições,
  identidade = faixa horária) **deliberadamente não muda**. Se o modificador entrasse na
  chave, mudá-lo viraria `remove`+`add`: o criterion seria recriado, custando **~14 dias de
  re-learning** — o mesmo custo que o caminho `no_changes` existe para evitar (Task 1).
- **`diff_schedule` decide por janela**: o modificador da **janela** vence; o escalar da
  **chamada** é o default de quem não trouxer o seu; ambos ausentes preserva o valor atual —
  regra centralizada em `modificador_efetivo(janela, escalar)`, usada em **4 call-sites**
  (o próprio `diff_schedule` + as ops `add`/`update` + `bid_modifier_novo` do preview na
  tool) para não repetir a família do F81 (Tasks 2 e 4, com um fix round cada).
- **`schedule_fingerprint` passa a cobrir o modificador** (6ª posição, antes 5) — sem isso,
  a concorrência otimista da Ruling 10 (que recusa o apply se a agenda mudou dentro do TTL
  de 10 min) ficaria **cega** justamente para uma mudança de só bid_modifier feita por
  outra pessoa entre o preview e o apply (Task 3).
- **O preview mostra o efetivo**: `windows_added` e `bid_modifier_updated` trazem o
  `bid_modifier` que **realmente** vai ser aplicado (via `modificador_efetivo`), nunca o
  escalar cru — quem confirma o preview vê o valor real (Task 4, fix round 1).
- **Task 5 prova, por teste, que o F149 fechou**: uma faixa muda numa única chamada sem
  desligar as outras (`test_muda_uma_faixa_sem_desligar_as_outras_em_UMA_chamada`, passou de
  primeira) + o apply recusa quando só o bid_modifier mudou no baseline
  (`test_apply_recusa_quando_so_o_bid_modifier_mudou_no_baseline`, validado por sabotagem
  contra o fingerprint pré-Task-3).

**Operator:** wellington.ribeiro@v4company.com — a autorização de mutação (ver aviso no
topo) é dele, na sessão que executa. Sem substituto.

**Conta (única, todos os testes):** `1163862076` — conta de teste do Wellington. Todos os
seis testes mínimos do brief rodam aqui; não há conta de substância neste smoke (diferente
do 3b.42, que tinha `7862230676` para a métrica real) porque o ponto do F149 é mecânica de
diff/fingerprint, não CPA por bloco.

**Campanha recomendada — reuso do 3b.42, com estado conhecido:**

```
campaign_id: 23851718373
campaign_name: [3b.24.4] T5.1 - max_conv_value
Razão: mesma campanha do smoke 3b.42 (T3-T8) — PAUSED, zero atividade em 30d, sem
criterion AD_SCHEDULE preexistente, fora de orçamento compartilhado. Reusar em vez de
escolher uma nova reduz o número de fatos não medidos que este documento carrega.
```

**Estado conhecido desta campanha ANTES do Setup abaixo** (citado, não medido nesta sessão):

- **PAUSED, zero shared budget, zero atividade nos últimos 30 dias** — `phase-3b-42-ad-schedule-smoke.md`, "Dados conhecidos", tabela das 6 candidatas.
- **Devolvida a 24×7 natural (`has_schedule: false`, zero criteria `AD_SCHEDULE`) ao final do 3b.42, T8, executado 2026-09-04 08:27 UTC**, com resíduo confirmado **por dois instrumentos**: `run_gaql` em `campaign_criterion` **sem filtro de status** devolveu `row_count: 0` (ou seja, **o `remove` desta tool apaga o criterion de fato — não fica uma linha com `status: REMOVED` para trás**), e `get_ad_schedule(status="all")` mostrou as 6 campanhas candidatas com `has_schedule: false, hours_per_week: 168.0` (`phase-3b-42-ad-schedule-smoke.md`, Teste T8, "Resíduo: ZERO, verificado por dois instrumentos"). **Este fato — remoção real, não status `REMOVED` — é exatamente o que o T6 deste runbook precisa reconfirmar**, e é o motivo de a query de T6 não filtrar por status.
- **Nenhuma sessão de smoke tocou esta campanha entre o 3b.42 (04/09) e agora** — o 3b.43 (partição horária) usou a MESMA conta `1163862076` só para dois testes de leitura/recusa (`T5`/`T6`), nenhum deles passando `campaign_ids` com esta campanha específica nem mutando nada.
- **Reconfirme antes do Setup**, mesmo assim: `get_ad_schedule(customer_id="1163862076", campaign_ids=["23851718373"])` deve devolver `has_schedule: false, windows: 0, hours_per_week: 168.0`. Se vier diferente, **pare** — o baseline mudou e este roteiro não se aplica sem ajuste.

**Plan:** `docs/superpowers/plans/2026-09-04-bid-modifier-por-janela.md` (Tasks 1-6)
**Ledger:** `.superpowers/sdd/2026-09-04-bid-modifier-por-janela/progress.md` (scan de pré-voo, 2 Rulings, execução das 5 tasks)
**Task reports:** `.superpowers/sdd/2026-09-04-bid-modifier-por-janela/task-{1,2,3,4,5}-report.md`
**Finding:** F149 (`findings-catalog.md`) — este smoke fecha o que ficou aberto nele

> **Escopo confirmado:**
> - **Tool count: inalterado.** Zero tools novas — `update_ad_schedule` já existia (desde o
>   PR #31/3b.42) e ganha um campo NOVO OPCIONAL em cada item de `windows[]`. Último total
>   conhecido: 68 (CLAUDE.md, 2026-09-04); esta sprint não mexe nesse número.
> - **Breaking change: nenhum.** `_JANELA["properties"]["bid_modifier"]` é aditivo e
>   `additionalProperties: False` só rejeitaria uma chamada que TENTASSE usar o campo novo
>   contra um schema antigo (ver nota de F140 abaixo) — quem não usa o campo não é afetado.
>   Os 34 testes pré-existentes de `test_update_ad_schedule.py` (comportamento escalar)
>   seguem intocados e verdes nas 5 tasks (task-4-report.md, task-5-report.md).
> - **Zero migration.** Nenhuma das 5 tasks tocou o banco (confirmado nos task reports).
> - **F140 aplica-se como no 3b.43, não como no 3b.42.** A tool `update_ad_schedule` **já
>   existe** em produção — o que muda é só o SCHEMA (`bid_modifier` novo dentro de cada item
>   de `windows[]`). Uma sessão MCP conectada antes do deploy carrega o schema antigo (sem
>   esse campo), e `additionalProperties: False` recusaria — não com "tool não encontrada",
>   mas com um erro de validação de schema — **qualquer chamada de T1, T5 ou T7 que passe
>   `bid_modifier` dentro de um item de `windows[]`**. O Setup, T2, T3, T4 e T6 não usam o
>   campo por-janela e não seriam afetados por schema desatualizado. **Reconecte a sessão
>   MCP depois do deploy, antes de tentar T1.**
> - **Não executado** — branch nem mesclada ainda; ver cabeçalho.

---

## Pre-flight — documento APENAS, sem checks automatizados executados

- [x] **Branch local existente:** `git branch --show-current` = `feat/bid-modifier-por-janela` — confirmado nesta sessão
- [x] **HEAD do branch (nesta escrita):** `9a718b3` (Task 5 completa) — confirme o valor atual com `git rev-parse HEAD` no momento da execução; este commit de documentação avança mais um
- [x] **`main` não tem nenhum destes commits:** HEAD de `main` é `e57f513` — confirmado por `git log main --oneline -3` nesta sessão (`e57f513 docs(plans): plano do F149`, que é só o plano, não a implementação)
- [x] **Plan lido:** `docs/superpowers/plans/2026-09-04-bid-modifier-por-janela.md` — confirmado, linha a linha
- [x] **Ledger lido:** `.superpowers/sdd/2026-09-04-bid-modifier-por-janela/progress.md` — scan de pré-voo (2 Rulings) + execução das 5 tasks, todas `complete`
- [x] **Tasks 1-5 entregues**, cada uma com gate `check_pre_push.py` 6/6 (Tasks 4 e 5, que tocam mutação, também com `check_pre_push_full.py` 7/7) e review limpo (Task 2 precisou de 1 fix round por um buraco na matriz de prioridade; Task 4 precisou de 1 fix round por duplicação de regra; Task 3 e Task 1 clean de primeira; Task 5 clean, zero achados) — confirmado via os 5 `task-N-report.md` + `progress.md`
- [x] **Código-fonte lido linha a linha nesta sessão:** `src/google_ads/ad_schedule.py`, `src/mcp/tools/update_ad_schedule.py`, `src/mcp/tools/apply_change.py` (bloco `update_ad_schedule`), `src/google_ads/mutates/ad_schedule.py`, `src/google_ads/queries/ad_schedule.py`, `src/governance/dry_run.py` (`consume()`) — as mensagens de erro e formas de resposta citadas abaixo são cópia literal do código, não paráfrase
- [x] **`findings-catalog.md` lido:** F149 (aberto — este sprint fecha o restante), F150 e F151 (corrigidos — contexto de precedente sobre o corolário "não fechar sprint de tool mutante com apply ou restauração em pending")
- [x] **Nenhuma tool MCP chamada, nenhuma conta consultada nesta sessão de escrita** — todo número vem do 3b.42 (já executado) ou dos fixtures dos testes unitários (já executados no CI), ou está marcado `<medir>`
- [x] **Nenhum segredo ou credencial será digitado** durante este documento — confirmado
- [ ] **CI local (`check_pre_push.py`)** — roda antes do commit deste documento (é markdown puro; incluído por convenção do repo, não porque se espera que quebre algo)
- [ ] **Autorização do Wellington obtida NA SESSÃO QUE EXECUTA** antes do primeiro passo mutante (Setup) — ver aviso no topo

---

## Smoke results

**Legenda** (mesma do 3b.42/3b.43): ✅ executado com evidência transcrita aqui · ◐ executado
em sessão de campo, detalhe no `findings-catalog.md` · 🚫 tentado e barrado pelo
classificador de auto mode antes de chegar ao MCP · ⬜ não executado.

| # | Teste | Muta? | Result | Execution Date | Notes |
|---|---|---|---|---|---|
| Setup | `update_ad_schedule` (5 `add`, escalar 1.0) + `apply_change` | **sim** | ⬜ pending | — | Pré-requisito do T1 — NÃO é um dos 6 do brief; estabelece a grade baseline |
| T1 | `update_ad_schedule` (5 janelas, `bid_modifier` só em MONDAY) — dry-run | não (preview) | ⬜ pending | — | Crítico: 1 `update`, zero `remove`, `cobertura.reduz: false` |
| T2 | `apply_change` do token de T1 | **sim** | ⬜ pending | — | Crítico: GAQL por `criterion_id` — MONDAY novo, outras 4 intactas |
| T3 | Comparação de `criterion_id`: Setup vs. pós-T2 | não (leitura) | ⬜ pending | — | Crítico: mesmos 5 ids — update via field mask, não recriação |
| T4 | Reenviar a mesma grade de T1 | não (preview) | ⬜ pending | — | `no_changes`, sem token |
| T5 | Janela com `bid_modifier` + chamada com escalar diferente — dry-run | não (preview, descartado) | ⬜ pending | — | MONDAY ausente de `bid_modifier_updated` — a janela vence |
| T7 (opcional) | Concorrência otimista: dois tokens, o segundo aplicado primeiro | **sim** | ⬜ pending | — | `apply_change` do token A recusado citando "mudou desde o preview" |
| T6 | `clear_schedule: true` — restauração | **sim** | ⬜ pending | — | `has_schedule: false`; `run_gaql` sem filtro de status devolve 0 linhas |

**Effective result:** 0/7 obrigatórios executados (+ T7 opcional). Nenhuma tool chamada nesta
sessão de escrita — branch não mesclada, sem autorização de mutação nesta sessão.

**Ordem de execução (obrigatória, não intercambiável):** Setup → T1 → T2 → T3 → T4 → T5 →
T7 (se incluído) → T6. **T6 tem que ser o ÚLTIMO passo mutante** — ele apaga a grade
inteira, e qualquer teste depois dele voltaria a partir de 24×7 natural, não do estado que
os testes anteriores descrevem. Se T7 for pulado, vá direto de T5 para T6.

---

## Teste Setup — estabelecer a grade baseline (pré-requisito do T1, NÃO conta como um dos 6)

**Setup:** Nenhum dos 6 testes do brief funciona contra uma campanha 24×7 "limpa" — T1
precisa que a IDENTIDADE das 5 janelas (dia+hora) já exista como `campaign_criterion`, com
algum `bid_modifier` conhecido, para poder mostrar "1 `update`" (mudar só MONDAY) em vez de
"5 `add`" (criar a grade do zero). Esta chamada estabelece exatamente o fixture que o teste
que fecha o F149 usa
(`tests/unit/test_update_ad_schedule.py::test_muda_uma_faixa_sem_desligar_as_outras_em_UMA_chamada`):
5 janelas seg-sex 07h-17h, todas com `bid_modifier=1.0` — aqui aplicado pela via ESCALAR
(o jeito antigo, que afeta todas as janelas do lote, porque neste momento TODAS são novas).

**Tool call (dry-run):**

```
update_ad_schedule(
  customer_id="1163862076",
  campaign_ids=["23851718373"],
  windows=[
    {"day_of_week": "MONDAY", "start_hour": 7, "end_hour": 17},
    {"day_of_week": "TUESDAY", "start_hour": 7, "end_hour": 17},
    {"day_of_week": "WEDNESDAY", "start_hour": 7, "end_hour": 17},
    {"day_of_week": "THURSDAY", "start_hour": 7, "end_hour": 17},
    {"day_of_week": "FRIDAY", "start_hour": 7, "end_hour": 17}
  ],
  bid_modifier=1.0
)
```

**Expected response shape (estrutura + texto confirmados por leitura de código; a campanha
é a mesma do 3b.42, zero atividade em 30d — ver "Dados conhecidos"):**

```json
{
  "status": "dry_run",
  "operation": "update_ad_schedule",
  "customer_id": "1163862076",
  "blast_summary": "Redefinir a grade de 1 campanha(s): 5 janela(s) entram, 0 saem, 0 mudam bid_modifier (5 operacoes). Janelas fora da grade DEIXAM de servir. 1 reduz(em) cobertura (168.0 -> 50.0 horas/semana).",
  "confirmation_token": "<medir, 8 chars ^[A-Z0-9]{8}$>",
  "expires_in_minutes": 10,
  "confirmation_reason": "update_ad_schedule: redefine a grade de veiculacao (conjunto, nao incremento) — sempre CONFIRM",
  "target_count": 5,
  "preview": {
    "23851718373": {
      "was_24x7": true,
      "campaign_status": "PAUSED",
      "aviso_status": "campanha PAUSED: as metricas abaixo sao historicas e a grade nao afeta entrega enquanto ela estiver pausada",
      "current": {"has_schedule": false, "windows": 0, "hours_per_week": 168.0},
      "cobertura": {"horas_antes": 168.0, "horas_depois": 50.0, "reduz": true},
      "aviso_cobertura": null,
      "windows_added": [
        {"day_of_week": "MONDAY", "start_hour": 7, "start_minute": 0, "end_hour": 17, "end_minute": 0, "bid_modifier": 1.0},
        {"day_of_week": "TUESDAY", "...": "idem, bid_modifier: 1.0"},
        {"day_of_week": "WEDNESDAY", "...": "idem"},
        {"day_of_week": "THURSDAY", "...": "idem"},
        {"day_of_week": "FRIDAY", "...": "idem"}
      ],
      "windows_removed": [],
      "bid_modifier_updated": [],
      "metrics": {
        "leaving": {"cost_brl": 0.0, "conversions": 0.0, "cpa_brl": null, "cells": 0},
        "staying": {"cost_brl": 0.0, "conversions": 0.0, "cpa_brl": null, "cells": 0},
        "metrics_granularity": "hora cheia; janelas com minutos sao aproximadas a hora cheia"
      }
    }
  },
  "shared_budgets": [],
  "metrics_window": {"start": "<medir>", "end": "<medir>", "days": 30}
}
```

*(`aviso_cobertura: null` apesar de `reduz: true` — o destaque só aparece quando reduz **e**
`shared_budget`; esta campanha não tem orçamento compartilhado.)*

**Validação:**

- [ ] Response sem `"error"`; `status == "dry_run"` (`update_ad_schedule` não tem branch AUTO)
- [ ] `confirmation_token` presente, 8 chars `^[A-Z0-9]{8}$`; `expires_in_minutes == 10`
- [ ] `target_count == 5` — 5 `add`, 0 `remove`, 0 `update`
- [ ] **Crítico Setup:** `preview["23851718373"].windows_added` tem **5** entradas, cada uma
      com **6** campos (os 5 de identidade + `bid_modifier: 1.0`) — se vier com 5 campos
      (sem `bid_modifier`), a Task 4/fix-round-1 regrediu (windows_added deixou de mostrar o
      efetivo)
- [ ] `cobertura == {"horas_antes": 168.0, "horas_depois": 50.0, "reduz": true}`
- [ ] `campaign_status == "PAUSED"` e `aviso_status` não-nulo (F52/F90 — herdado, não desta sprint)
- [ ] `metrics.leaving`/`staying` ambos zerados — campanha sem atividade em 30d (citado do 3b.42)
- [ ] `shared_budgets == []`
- [ ] Uma linha nova em `pending_confirmations`

**Após `apply_change(token)`:**

- [ ] `status == "applied"`, `applied_count == 5`, `changed_count == 5`, `partial_failures == []`
- [ ] `resulting_schedule["23851718373"]` = `{"has_schedule": true, "windows": [5 linhas], "hours_per_week": 50.0, "matches_requested": true}`
- [ ] **Anote os 5 `criterion_id`** de `resulting_schedule` (um por dia) — chame este
      conjunto de **`BASELINE_IDS`**. T2 e T3 comparam contra ele.
- [ ] **Confirme por `run_gaql`** (query abaixo): 5 linhas, todas `status: ENABLED`,
      `bid_modifier: 1.0` nas 5 — os mesmos `criterion_id` de `resulting_schedule`

```sql
SELECT campaign_criterion.criterion_id, campaign_criterion.status,
       campaign_criterion.ad_schedule.day_of_week,
       campaign_criterion.ad_schedule.start_hour,
       campaign_criterion.ad_schedule.end_hour,
       campaign_criterion.bid_modifier
FROM campaign_criterion
WHERE campaign.id = 23851718373 AND campaign_criterion.type = 'AD_SCHEDULE'
ORDER BY campaign_criterion.ad_schedule.day_of_week
```

**Failure modes investigation:**

- `windows_added` sem `bid_modifier` → regressão da Task 4 (fix round 1) — o preview voltou
  a mostrar só identidade, escondendo o valor que vai ser aplicado
- Algum dos 5 `bid_modifier` sai diferente de `1.0` → o escalar não está sendo aplicado como
  default em `add` (`modificador_efetivo(w, 1.0)` deveria devolver `1.0` para toda janela
  sem override próprio)
- `was_24x7 == false` ou `preview` com `windows_removed`/`bid_modifier_updated` não-vazios →
  a campanha já tinha algum criterion — o "Dados conhecidos" mudou; **pare** e reconfirme
  por `get_ad_schedule` antes de prosseguir

**Result:** ⬜ pending

---

## Teste T1 — grade de 5 janelas, `bid_modifier` só em MONDAY — o preview que prova a mecânica

**Setup:** Esta é a chamada central do sprint: a mesma identidade de 5 janelas do Setup,
mas agora com `bid_modifier: 1.4` **só no item de MONDAY** — sem escalar top-level. Reproduz,
contra conta real, exatamente
`tests/unit/test_update_ad_schedule.py::test_muda_uma_faixa_sem_desligar_as_outras_em_UMA_chamada`
(grade com `bm=1.0` nas 5, pedido = `SEG_SEX` com `janelas[0]["bid_modifier"] = 1.4`, que é
MONDAY — `SEG_SEX[0]` é `{"day_of_week": "MONDAY", ...}`,
`tests/unit/test_update_ad_schedule.py:111-114`). Antes desta sprint, isto era inexprimível
numa chamada só — a única rota era duas chamadas com um estado degradado no meio (F149).

**Tool call (dry-run — NÃO aplicar ainda, T2 usa este token):**

```
update_ad_schedule(
  customer_id="1163862076",
  campaign_ids=["23851718373"],
  windows=[
    {"day_of_week": "MONDAY", "start_hour": 7, "end_hour": 17, "bid_modifier": 1.4},
    {"day_of_week": "TUESDAY", "start_hour": 7, "end_hour": 17},
    {"day_of_week": "WEDNESDAY", "start_hour": 7, "end_hour": 17},
    {"day_of_week": "THURSDAY", "start_hour": 7, "end_hour": 17},
    {"day_of_week": "FRIDAY", "start_hour": 7, "end_hour": 17}
  ]
)
```

**Expected response shape:**

```json
{
  "status": "dry_run",
  "blast_summary": "Redefinir a grade de 1 campanha(s): 0 janela(s) entram, 0 saem, 1 mudam bid_modifier (1 operacoes). Janelas fora da grade DEIXAM de servir.",
  "confirmation_token": "<medir>",
  "expires_in_minutes": 10,
  "target_count": 1,
  "preview": {
    "23851718373": {
      "was_24x7": false,
      "cobertura": {"horas_antes": 50.0, "horas_depois": 50.0, "reduz": false},
      "aviso_cobertura": null,
      "windows_added": [],
      "windows_removed": [],
      "bid_modifier_updated": [
        {"day_of_week": "MONDAY", "start_hour": 7, "start_minute": 0, "end_hour": 17, "end_minute": 0, "bid_modifier_antigo": 1.0, "bid_modifier_novo": 1.4}
      ]
    }
  }
}
```

**Validação:**

- [ ] `status == "dry_run"`; `confirmation_token` presente — **guarde este token para o T2**
- [ ] **Crítico T1:** `target_count == 1` — zero `add`, zero `remove`, exatamente 1 `update`
- [ ] **Crítico T1:** `preview["23851718373"].windows_added == []` **e**
      `windows_removed == []` — as 5 janelas já existiam com a mesma identidade; nenhuma
      entra, nenhuma sai
- [ ] **Crítico T1 (a asserção central do F149):** `bid_modifier_updated` tem **exatamente
      1** entrada, para `day_of_week: "MONDAY"`, com `bid_modifier_antigo: 1.0` (valor do
      Setup) e `bid_modifier_novo: 1.4` — TUESDAY a FRIDAY **não aparecem** nesta lista
- [ ] **Crítico T1:** `cobertura == {"horas_antes": 50.0, "horas_depois": 50.0, "reduz": false}`
      — a identidade das janelas não muda, só o modificador; `hours_per_week` nunca depende
      de `bid_modifier` (`hours_per_week()` soma só duração, `src/google_ads/ad_schedule.py:119-120`).
      É o dado que prova que este teste não é "mais uma redefinição de grade" — é uma
      correção cirúrgica de lance
- [ ] `was_24x7 == false` (a campanha já tem grade, do Setup)

**Failure modes investigation:**

- `target_count != 1` ou `windows_added`/`windows_removed` não-vazios → a identidade das 5
  janelas divergiu entre Setup e T1 (dia/hora diferentes por engano) — `diff_schedule` está
  comparando por `key()`, que ignora minuto default; confira `start_minute`/`end_minute`
- `bid_modifier_updated` com mais de 1 entrada (TUESDAY-FRIDAY aparecendo) → **regressão
  grave do F149**: o escalar (ausente aqui) está sendo tratado como não-`None`, ou
  `modificador_efetivo` está invertido (escalar vencendo a janela em vez do contrário) —
  ver Ruling 3 do ledger, que documenta exatamente este buraco achado por mutação na Task 2
- `bid_modifier_updated` vazio (zero entradas) → o efetivo de MONDAY (`1.4`) não está
  diferindo do atual (`1.0`) na comparação — conferir se o Setup realmente aplicou 1.0 (ver
  `BASELINE_IDS`/GAQL do Setup) antes de investigar o diff
- `cobertura.reduz == true` → bug na lógica de `hours_per_week`, ou a identidade das janelas
  mudou (5 → menos de 5) entre Setup e T1

**Result:** ⬜ pending

---

## Teste T2 — `apply_change` do token de T1 — a prova por `criterion_id`, nunca por contagem

**Setup:** Esta é a asserção que prova o F149 fechado de verdade — em conta real, não só em
unit test. **Tem que ser por `criterion_id`**, comparando contra `BASELINE_IDS` anotado no
Setup: se a prova fosse só "5 linhas, 1 com bid_modifier 1.4" isso não distinguiria "MONDAY
mudou de lance" de "MONDAY foi removido e um criterion novo foi criado com o mesmo dia/hora
e já o lance certo" — o primeiro é o que o F149 promete (update via field mask, criterion
preservado); o segundo queimaria ~14 dias de re-learning silenciosamente.

**Tool call:**

```
apply_change(confirmation_token="<token de T1>")
```

**Expected response shape:**

```json
{
  "status": "applied",
  "operation": "update_ad_schedule",
  "customer_id": "1163862076",
  "applied_count": 1,
  "changed_count": 1,
  "partial_failures": [],
  "confirmation_error": null,
  "resulting_schedule": {
    "23851718373": {
      "has_schedule": true,
      "hours_per_week": 50.0,
      "matches_requested": true,
      "windows": ["5 linhas, uma por dia util"]
    }
  }
}
```

**Validação:**

- [ ] `status == "applied"`; `applied_count == 1`; `changed_count == 1`; `partial_failures == []`
- [ ] `confirmation_error == null` (a reconsulta pós-apply funcionou)
- [ ] `resulting_schedule["23851718373"].matches_requested == true`

**Confirmação por GAQL (reexecute a query do Setup) — o crítico deste teste:**

```sql
SELECT campaign_criterion.criterion_id, campaign_criterion.status,
       campaign_criterion.ad_schedule.day_of_week,
       campaign_criterion.ad_schedule.start_hour,
       campaign_criterion.ad_schedule.end_hour,
       campaign_criterion.bid_modifier
FROM campaign_criterion
WHERE campaign.id = 23851718373 AND campaign_criterion.type = 'AD_SCHEDULE'
ORDER BY campaign_criterion.ad_schedule.day_of_week
```

- [ ] **Crítico T2:** 5 linhas, todas `status: ENABLED`
- [ ] **Crítico T2:** o `criterion_id` da linha `MONDAY` é **idêntico** ao `criterion_id` de
      MONDAY em `BASELINE_IDS` (do Setup) — **não** um id novo
- [ ] **Crítico T2 (fix C1 da revisão final — leia antes de marcar falha):**
      `bid_modifier` da linha `MONDAY` **não sai `1.4` exato** — o SDK v24 declara
      o campo como `proto.FLOAT` (32 bits), e o Google devolve algo como
      `1.399999976158142`. Valide com tolerância (`abs(valor - 1.4) < 1e-6`, a
      mesma que `bid_modifier_diverge` usa em `diff_schedule`/`matches_requested`),
      **não** por igualdade exata. Ver `bid_modifier_diverge` em
      `src/google_ads/ad_schedule.py`. Isto **não é regressão** — é o
      comportamento correto do fix; o preview (`bid_modifier_antigo`/`novo`) já
      arredonda para 2 casas na exibição, mas o GAQL cru aqui não passa por
      essa camada
- [ ] **Crítico T2 — "os outros quatro ficaram intactos":** os `criterion_id` de TUESDAY,
      WEDNESDAY, THURSDAY, FRIDAY são **idênticos**, um a um, aos de `BASELINE_IDS`, **e**
      `bid_modifier` de cada um continua `1.0` — comparação por `criterion_id`, nunca por
      "ainda são 5 linhas" (5 linhas também apareceriam se MONDAY tivesse sido removido e
      recriado com um id novo — contagem sozinha não distingue os dois cenários)

**Failure modes investigation:**

- `criterion_id` de MONDAY **diferente** de `BASELINE_IDS[MONDAY]` → **achado HIGH**: a
  tool recriou o criterion em vez de fazer update via field mask, apesar de
  `src/google_ads/mutates/ad_schedule.py:45-54` só tocar `bid_modifier` via
  `cco.update` + `FieldMask(paths=["bid_modifier"])` — pare e investigue antes de T3
- Algum `criterion_id` de TUESDAY-FRIDAY diferente de `BASELINE_IDS` → as janelas que não
  deveriam mudar foram tocadas — o F149 não fechou, a "assimetria" apontada no finding
  persiste
- `bid_modifier` de alguma janela TUESDAY-FRIDAY diferente de `1.0` → a operação vazou para
  janelas fora do alvo — mesma classe de bug do ponto acima
- `partial_failures` não-vazio → alguma operação falhou; `applied_count`/`changed_count`
  sozinhos não dizem onde — transcreva cada `{index, status, error}`

**Result:** ⬜ pending

---

## Teste T3 — os mesmos `criterion_id`: update via field mask, não recriação

**Setup:** Mesma GAQL de T2, lente diferente: aqui a comparação é contra o **conjunto
completo** de `BASELINE_IDS` do Setup (as 5, não só as 4 "que não deveriam mudar"),
confirmando que **nenhum** dos 5 criteria foi recriado — nem MONDAY (que mudou de valor),
nem os outros (que não mudaram de nada). Esta é a invariante mais cara do plano
("`key()` da `Window` NÃO pode incluir o modificador" — Global Constraints do plan) validada
contra a API real, não só contra `diff_schedule` em memória.

**Não há tool call novo** — reusa a mesma resposta de GAQL de T2.

**Validação:**

- [ ] **Crítico T3:** o conjunto `{criterion_id de MONDAY..FRIDAY pós-T2}` é **byte a byte
      idêntico** ao conjunto `BASELINE_IDS` do Setup — mesmos 5 ids, nenhum novo, nenhum
      ausente
- [ ] Recriar estes 5 criteria custaria ~14 dias de re-learning (Global Constraint do
      plan) — este teste é a prova de que isso NÃO aconteceu, com dado real
- [ ] Nenhuma linha extra em `campaign_criterion` para esta campanha além das 5 — se
      aparecesse uma 6ª linha (mesmo com `status: REMOVED`), seria sinal de um `add`+`remove`
      indevido em algum ponto do fluxo

**Failure modes investigation:**

- Conjunto de ids diverge em qualquer posição → mesma investigação de T2 (regressão na
  invariante `key()` sem modificador) — trate como o MESMO achado de T2, não um segundo
- 6ª linha aparece (qualquer status) → algum `add` ou `remove` extra foi emitido; cruze
  com `ops` do payload de T1 (deveria ter só 1 `update`, nada mais)

**Result:** ⬜ pending

---

## Teste T4 — reenviar a mesma grade de T1 — `no_changes`, sem token

**Setup:** Idempotência: mandar exatamente o que já está lá não deveria emitir operação
nenhuma, muito menos criar um token novo. Esta é a mesma chamada de T1, **byte a byte**,
agora contra um estado que já reflete o T2 aplicado (MONDAY em `1.4`).

**Tool call (idêntica à de T1):**

```
update_ad_schedule(
  customer_id="1163862076",
  campaign_ids=["23851718373"],
  windows=[
    {"day_of_week": "MONDAY", "start_hour": 7, "end_hour": 17, "bid_modifier": 1.4},
    {"day_of_week": "TUESDAY", "start_hour": 7, "end_hour": 17},
    {"day_of_week": "WEDNESDAY", "start_hour": 7, "end_hour": 17},
    {"day_of_week": "THURSDAY", "start_hour": 7, "end_hour": 17},
    {"day_of_week": "FRIDAY", "start_hour": 7, "end_hour": 17}
  ]
)
```

**Expected response (envelope próprio, montado à mão — não passa por `preview_envelope`;
`src/mcp/tools/update_ad_schedule.py:348-359`):**

```json
{
  "status": "no_changes",
  "operation": "update_ad_schedule",
  "customer_id": "1163862076",
  "no_changes": true,
  "message": "A grade desejada e identica a atual em todas as campanhas: nenhuma operacao emitida (recriar criterios identicos custaria re-learning).",
  "current_schedule": {
    "23851718373": {"has_schedule": true, "windows": 5, "hours_per_week": 50.0}
  }
}
```

**Validação:**

- [ ] **Crítico T4:** `status == "no_changes"` e `no_changes == true`
- [ ] **Crítico T4:** **nenhuma** chave `confirmation_token` na resposta — este é o único
      envelope de mutação do repo que não passa por `preview_envelope` (mesma nota já
      registrada no 3b.42 T6, spec §4.4)
- [ ] `current_schedule["23851718373"]` reflete o estado pós-T2: `windows: 5` (aqui é
      **contagem inteira**, `summarize_current()` puro — não confundir com
      `resulting_schedule[cid].windows` de `apply_change`, que é lista; mesma nota de forma
      já registrada no 3b.43)
- [ ] `hours_per_week == 50.0` (inalterado — bid_modifier não afeta isto)
- [ ] Zero linha nova em `pending_confirmations`

**Failure modes investigation:**

- 🔴 **Histórico medido (fix C1 da revisão final, já corrigido no código — cite
  isto se T4 falhar de novo):** antes do fix, este teste **falhava sempre** —
  `diff_schedule` comparava o `1.4` (float64, pedido) com o que o Google
  devolve (`1.399999976158142`, float32/`proto.FLOAT` do SDK v24) usando `==`,
  então a comparação nunca batia e `to_update` saía não-vazio com token
  mintado. O fix trocou a comparação por `bid_modifier_diverge`
  (`math.isclose(rel_tol=1e-6)`, `src/google_ads/ad_schedule.py`). Se T4
  falhar aqui, a PRIMEIRA hipótese é essa tolerância ter regredido — confira
  se `diff_schedule` voltou a comparar por `!=`/`==` direto — e só DEPOIS
  verifique se T2 realmente aplicou
- `status != "no_changes"` (alguma operação é emitida), mas a tolerância acima
  está intacta → verificar se T2 realmente aplicou antes de tratar como bug novo
- `confirmation_token` presente → a tool está tratando este caminho como `dry_run` comum;
  regressão da spec §4.4 (grade idêntica não deveria gerar token)

**Result:** ⬜ pending

---

## Teste T5 — janela com `bid_modifier` + chamada com escalar diferente — a janela vence

**Setup:** Esta é a "coluna qualquer" da tabela de compatibilidade do plano — janela **e**
escalar presentes, com valores **diferentes**. A prova mais forte não é "o preview mostra o
valor da janela" (um bug poderia mostrar o valor certo e aplicar o errado) — é a mesma
técnica do teste que blindou isto no código,
`tests/unit/test_ad_schedule_domain.py::test_modificador_da_janela_vence_mesmo_com_escalar_diferente_tambem_presente`:
construir o cenário para que as duas hipóteses (janela vence / escalar vence) produzissem
resultados **opostos em presença, não só em valor** — MONDAY pede o próprio valor atual
(`1.4`, ou seja "zero mudança" se a janela vencer) enquanto o escalar pede algo diferente
(`2.0`, ou seja "muda" se o escalar vencesse). Se a janela vence (correto), MONDAY **some**
da lista de mudanças. Se o escalar vencesse (bug), MONDAY **apareceria** com `novo: 2.0`.
A distinção vem de MONDAY estar ausente ou presente — não do valor que ele mostra, que um
bug poderia coincidentemente acertar.

Ao mesmo tempo, TUESDAY-FRIDAY (sem `bid_modifier` próprio) devem herdar o escalar `2.0`
como default — o comportamento **correto e esperado** de quem não trouxe override, provando
que a regra não ficou "escalar nunca vence nada", só "escalar não vence quando a janela
também trouxe valor".

**Tool call (dry-run — o token será DESCARTADO, `apply_change` NÃO será chamado, mesmo
padrão do 3b.42 T2b/T3 para exploração sem mutar):**

```
update_ad_schedule(
  customer_id="1163862076",
  campaign_ids=["23851718373"],
  windows=[
    {"day_of_week": "MONDAY", "start_hour": 7, "end_hour": 17, "bid_modifier": 1.4},
    {"day_of_week": "TUESDAY", "start_hour": 7, "end_hour": 17},
    {"day_of_week": "WEDNESDAY", "start_hour": 7, "end_hour": 17},
    {"day_of_week": "THURSDAY", "start_hour": 7, "end_hour": 17},
    {"day_of_week": "FRIDAY", "start_hour": 7, "end_hour": 17}
  ],
  bid_modifier=2.0
)
```

**Expected response shape:**

```json
{
  "status": "dry_run",
  "blast_summary": "Redefinir a grade de 1 campanha(s): 0 janela(s) entram, 0 saem, 4 mudam bid_modifier (4 operacoes). Janelas fora da grade DEIXAM de servir.",
  "target_count": 4,
  "preview": {
    "23851718373": {
      "cobertura": {"horas_antes": 50.0, "horas_depois": 50.0, "reduz": false},
      "windows_added": [],
      "windows_removed": [],
      "bid_modifier_updated": [
        {"day_of_week": "TUESDAY", "bid_modifier_antigo": 1.0, "bid_modifier_novo": 2.0, "...": "..."},
        {"day_of_week": "WEDNESDAY", "bid_modifier_antigo": 1.0, "bid_modifier_novo": 2.0, "...": "..."},
        {"day_of_week": "THURSDAY", "bid_modifier_antigo": 1.0, "bid_modifier_novo": 2.0, "...": "..."},
        {"day_of_week": "FRIDAY", "bid_modifier_antigo": 1.0, "bid_modifier_novo": 2.0, "...": "..."}
      ]
    }
  }
}
```

**Validação:**

- [ ] **Crítico T5 (a asserção central):** `bid_modifier_updated` tem **exatamente 4**
      entradas — TUESDAY, WEDNESDAY, THURSDAY, FRIDAY. **MONDAY não aparece** — nem com
      `novo: 1.4` (que seria inócuo mas redundante) nem, principalmente, com `novo: 2.0`
      (que provaria o escalar vencendo, o bug que este teste existe para pegar)
- [ ] Os 4 presentes mostram `bid_modifier_antigo: 1.0` e `bid_modifier_novo: 2.0` — o
      escalar age como default correto para quem não trouxe override
- [ ] `target_count == 4`; `windows_added == []`; `windows_removed == []`
- [ ] `cobertura.reduz == false` (só bid_modifier muda, hours_per_week idêntico)
- [ ] **Descarte o token** — não chame `apply_change`. Este teste prova a mecânica no
      preview; aplicar mudaria TUESDAY-FRIDAY para `2.0`, o que não serve a nenhum teste
      seguinte e aumenta o blast radius sem necessidade

**Failure modes investigation:**

- MONDAY aparece em `bid_modifier_updated` com `novo: 2.0` → **achado CRÍTICO, a regra
  central do sprint está invertida**: o escalar está vencendo a janela. É exatamente o
  buraco que a Ruling 3 do ledger descreve ter sido achado por mutação na Task 2 (antes do
  fix) — se reaparecer aqui, algo regrediu depois da Task 2/4
- MONDAY aparece com `novo: 1.4` (e `antigo` algo como `1.399999976158142`, não
  `1.4` exato) → **ESTE TAMBÉM É ACHADO CRÍTICO, não nota de forma** — é o Fix
  C1 da revisão final (float32 do Google comparado por `==` com o float64 do
  gestor nunca converge) regredindo: `diff_schedule` voltou a comparar sem a
  tolerância de `bid_modifier_diverge`. Trate com a MESMA severidade do bullet
  acima — a causa é diferente (arredondamento, não prioridade invertida), mas
  o efeito observável é o mesmo (MONDAY muda quando não deveria)
- Menos de 4 entradas para TUESDAY-FRIDAY → o escalar não está sendo aplicado como default
  em algum deles — conferir `modificador_efetivo(w, 2.0)` para o item específico que faltou

**Result:** ⬜ pending

---

## Teste T7 (opcional) — a concorrência otimista recusa quando só o bid_modifier mudou

> **Se decidir pular este teste, vá direto de T5 para T6.** T7 não é um dos 6 mínimos do
> brief — é a encenação em conta real do teste que já prova a mecânica em unit test
> (`tests/unit/test_apply_change_ad_schedule.py::test_apply_recusa_quando_so_o_bid_modifier_mudou_no_baseline`,
> validado por sabotagem na Task 5: revertendo `schedule_fingerprint` para a versão
> pré-Task-3, a mesma mutação passa **às cegas**). Incluído porque **é praticável** com as
> tools existentes, sem precisar de acesso direto ao banco — mas exige uma coreografia
> precisa dentro do TTL de 10 minutos. Se a sessão que executar preferir não arriscar o
> timing, pular é uma escolha razoável — a garantia já está provada por unit test.

**Por que é praticável, e como encenar:** a única forma de mudar `bid_modifier` é através da
própria `update_ad_schedule`, então "alguém mexeu no meio tempo" precisa ser **uma segunda
chamada real, completa (dry-run + apply), no mesmo campo que a primeira chamada ainda não
aplicou**. Mecânica exata, em 3 passos:

1. **Chamada A (dry-run, NÃO aplicar ainda):** muda só `WEDNESDAY` para `1.2`. Gera
   `token_A`, que carrega no payload o `current_keys` — o fingerprint do estado **no
   momento desta chamada** (WEDNESDAY em `1.0`, valor do Setup, ainda intocado).
2. **Chamada B (dry-run + `apply_change` IMEDIATO):** muda o **mesmo** `WEDNESDAY` para
   `1.8`. Aplicar B muda WEDNESDAY de verdade, via field mask, para `1.8` — sem tocar em
   `token_A` nem no criterion de nenhuma outra janela.
3. **Tentar aplicar `token_A`:** `apply_change` reconsulta a grade fresca do Google
   (`rows_antes`, `src/mcp/tools/apply_change.py:147-154`) e recalcula
   `schedule_fingerprint` — que agora inclui WEDNESDAY em `1.8`, **diferente** do `1.0`
   salvo em `current_keys` de `token_A`. A comparação (linha 158-161) diverge, e o apply é
   recusado **antes de qualquer mutação** — a ordem no código garante que o `run_mutation`
   nunca é chamado quando o fingerprint diverge.

**Duas restrições de mecanismo que a coreografia PRECISA respeitar** (ambas lidas em
`src/governance/dry_run.py:124-154`, função `consume()`):

- **Mesma sessão MCP para os 3 passos.** `consume()` recusa (`InvalidTokenError`) se
  `session_id` do token não bate com o da sessão que chama `apply_change` — se a Chamada A
  e a tentativa de aplicar `token_A` vierem de sessões MCP diferentes, o erro que aparece é
  de sessão, não o de fingerprint que este teste quer provar.
- **`token_A` é consumido mesmo quando a tentativa é recusada.** `consume()` marca
  `consumed_at` **antes** de `apply_change` sequer chegar na checagem de fingerprint (a
  ordem no código é: consome → só depois compara fingerprint). Ou seja: depois desta
  tentativa recusada, `token_A` está morto — não dá para "tentar de novo" com o mesmo
  token. Se quiser aplicar a mudança original de WEDNESDAY para `1.2` depois deste teste,
  precisa de uma chamada `update_ad_schedule` nova, contra o estado atual (`1.8`).

**Nota lateral, não bloqueante:** rate limit por gestor (`mgr:<uuid>` em `rate_counters`,
CLAUDE.md) existe e pode, em tese, interferir com duas mutações em sequência rápida — não é
o foco deste teste; se acontecer, é sinal de configuração de rate limit, não do F149.

**Tool call A (dry-run — NÃO aplicar):**

```
update_ad_schedule(
  customer_id="1163862076",
  campaign_ids=["23851718373"],
  windows=[
    {"day_of_week": "MONDAY", "start_hour": 7, "end_hour": 17},
    {"day_of_week": "TUESDAY", "start_hour": 7, "end_hour": 17},
    {"day_of_week": "WEDNESDAY", "start_hour": 7, "end_hour": 17, "bid_modifier": 1.2},
    {"day_of_week": "THURSDAY", "start_hour": 7, "end_hour": 17},
    {"day_of_week": "FRIDAY", "start_hour": 7, "end_hour": 17}
  ]
)
```

**Tool call B (dry-run + apply IMEDIATO):**

```
update_ad_schedule(
  customer_id="1163862076",
  campaign_ids=["23851718373"],
  windows=[
    {"day_of_week": "MONDAY", "start_hour": 7, "end_hour": 17},
    {"day_of_week": "TUESDAY", "start_hour": 7, "end_hour": 17},
    {"day_of_week": "WEDNESDAY", "start_hour": 7, "end_hour": 17, "bid_modifier": 1.8},
    {"day_of_week": "THURSDAY", "start_hour": 7, "end_hour": 17},
    {"day_of_week": "FRIDAY", "start_hour": 7, "end_hour": 17}
  ]
)
→ apply_change(confirmation_token="<token de B>")
```

**Tool call — a tentativa que deve ser recusada:**

```
apply_change(confirmation_token="<token_A>")
```

**Expected result (texto exato, copiado de `src/mcp/tools/apply_change.py:162-168`):**

```json
{
  "status": "error",
  "operation": "update_ad_schedule",
  "error_message": "A grade mudou desde o preview (alguem alterou a agenda destas campanhas nos ultimos minutos). Nenhuma operacao foi aplicada. Refaca o update_ad_schedule para gerar um token novo sobre o estado atual.",
  "customer_id": "1163862076"
}
```

**Validação:**

- [ ] Chamada A: `target_count == 1` (só WEDNESDAY), `bid_modifier_updated` com 1 entrada,
      `antigo: 1.0`, `novo: 1.2`
- [ ] Chamada B: `target_count == 1` (só WEDNESDAY), `antigo: 1.0`, `novo: 1.8`; após apply,
      `applied_count == 1`, `resulting_schedule` mostra WEDNESDAY com o criterion **mesmo
      id** de antes (field mask, mesma prova de T3, agora num terceiro cenário)
- [ ] **Crítico T7:** a tentativa de aplicar `token_A` devolve `status: "error"` com o texto
      **exato** acima, incluindo os acentos (`alguem`/`agenda` sem acento é o texto real —
      ASCII puro, diferente da mensagem de `_validate_combo` que usa acentuação normal;
      não troque um pelo outro ao transcrever)
- [ ] **Crítico T7 ("nada pode ter sido mutado"):** confirme por GAQL que WEDNESDAY
      continua com `bid_modifier: 1.8` (o valor de B) — **não** `1.2` (o valor que `token_A`
      tentava aplicar) e **não** `1.0` (o valor original). Se vier `1.2`, a recusa não
      impediu a mutação de verdade — achado CRÍTICO, o guard é decorativo
- [ ] O `criterion_id` de WEDNESDAY continua o mesmo de `BASELINE_IDS` — nem a chamada B
      nem a tentativa recusada de A recriaram o criterion

**Failure modes investigation:**

- Apply de `token_A` **sucede** (muda WEDNESDAY para `1.2`) → **achado CRÍTICO**: a
  concorrência otimista não está cobrindo o `bid_modifier` — exatamente o cenário que a
  Task 3 (fingerprint de 6 posições) existe para fechar. Reverta manualmente e trate como
  regressão do F149/Task 3, não como "resultado aceitável"
- Erro de sessão (`Token '...' belongs to a different session`) em vez do erro de
  fingerprint → a coreografia rodou em sessões MCP diferentes; refaça os 3 passos na MESMA
  sessão antes de concluir qualquer coisa sobre o fingerprint
- `token_A` expirado (mais de 10 min entre a Chamada A e esta tentativa) → refaça a
  coreografia inteira mais rápido; não é falha do F149, é o TTL normal

**Result:** ⬜ pending

---

## Teste T6 — `clear_schedule: true` — restauração, e a conta fica limpa

**Setup:** Último passo, e tem que rodar por último — apaga a grade inteira e devolve a
campanha ao 24×7 natural. Existe precedente **medido** (não só lido em código) sobre a
semântica exata de "apagar" aqui: no 3b.42 T8, depois de um `clear_schedule: true`
equivalente nesta MESMA campanha, `run_gaql` **sem filtro de status** devolveu
`row_count: 0` — ou seja, **o `remove` desta tool apaga o `campaign_criterion` de fato,
não deixa uma linha para trás com `status: REMOVED`** (diferente de campanha/grupo/keyword/
anúncio, que têm campo `status` e "removidos" continuam aparecendo como `REMOVED` — CLAUDE.md,
"Don't procurar REMOVE no change_event para entidade que tem campo status"; critérios de
campanha, como `AD_SCHEDULE`, não têm essa persistência). Este teste reconfirma o mesmo fato
contra o estado que T1-T5(-T7) deixaram.

**Tool call:**

```
update_ad_schedule(
  customer_id="1163862076",
  campaign_ids=["23851718373"],
  clear_schedule=true
)
```

**Expected response shape (preview):**

```json
{
  "status": "dry_run",
  "blast_summary": "Redefinir a grade de 1 campanha(s): 0 janela(s) entram, 5 saem, 0 mudam bid_modifier (5 operacoes). Janelas fora da grade DEIXAM de servir.",
  "target_count": 5,
  "preview": {
    "23851718373": {
      "cobertura": {"horas_antes": 50.0, "horas_depois": 168.0, "reduz": false},
      "aviso_cobertura": null,
      "windows_added": [],
      "windows_removed": ["5 entradas — MONDAY..FRIDAY, só os 5 campos de identidade"],
      "bid_modifier_updated": []
    }
  }
}
```

**Validação:**

- [ ] `target_count == 5` (5 `remove`, zero `add`, zero `update`)
- [ ] **Crítico T6 (fix do F151, herdado — reconfirme que não regrediu):**
      `cobertura == {"horas_antes": 50.0, "horas_depois": 168.0, "reduz": false}` — **não**
      `{"horas_depois": 0, "reduz": true}`. `clear_schedule` **restaura** entrega (168h),
      não a reduz; se a resposta disser o contrário, o F151 (já corrigido) regrediu
- [ ] **Nota de forma, não de bug:** `windows_removed` tem 5 entradas, cada uma só com os 5
      campos de identidade (`day_of_week`, `start_hour`, `start_minute`, `end_hour`,
      `end_minute`) — **sem** `bid_modifier`. Isto é deliberado (task-4-report.md,
      "Decisão de desenho": `_w(c.window)` nunca carrega `bid_modifier` porque
      `CurrentWindow.window` vem de `rows_to_current`, que nunca popula esse campo no
      sub-objeto — o modificador real mora em `c.bid_modifier`, campo irmão, não usado por
      `windows_removed`). Não é um achado se vier ausente; seria achado se aparecesse com
      um valor sempre `None`, o que indicaria confusão de campo
- [ ] Após apply: `applied_count == 5`, `resulting_schedule["23851718373"]` =
      `{"has_schedule": false, "windows": [], "hours_per_week": 168.0, "matches_requested": true}`
- [ ] **Crítico T6:** `get_ad_schedule(customer_id="1163862076", campaign_ids=["23851718373"])`
      mostra `has_schedule: false, windows: 0, hours_per_week: 168.0` — estado idêntico ao
      pré-Setup

**Confirmação por `run_gaql`, SEM filtro de status — o crítico deste teste:**

```sql
SELECT campaign_criterion.criterion_id, campaign_criterion.status
FROM campaign_criterion
WHERE campaign.id = 23851718373 AND campaign_criterion.type = 'AD_SCHEDULE'
```

- [ ] **Crítico T6:** `row_count == 0` — **nenhuma linha**, nem com `status: REMOVED`. Isto
      é o que "a conta fica limpa" significa aqui: o critério é apagado de fato, não
      arquivado. Precedente medido: 3b.42 T8, mesma campanha, mesmo tipo de query,
      `row_count: 0`

**Failure modes investigation:**

- `cobertura` mostra `horas_depois: 0`/`reduz: true` → regressão do F151 — o caminho
  `clear_schedule` voltou a calcular cobertura pelo tamanho da grade desejada (vazia) em vez
  do caminho explícito `limpar` (`src/mcp/tools/update_ad_schedule.py:288`,
  `horas_depois = 168.0 if limpar else hours_per_week(desired)`)
- `run_gaql` sem filtro de status devolve 5 linhas com `status: REMOVED` → o comportamento
  de remoção mudou desde o 3b.42 (Google alterou semântica, ou a suposição "critério de
  campanha não persiste como REMOVED" nunca foi universal — documente como achado e
  atualize a nota do CLAUDE.md/findings-catalog se confirmado, porque várias asserções de
  smokes anteriores dependem deste fato)
- `has_schedule` volta `true` após o apply → alguma das 5 (ou mais, se T7 rodou e deixou
  WEDNESDAY em outro estado) não foi removida — cruzar `partial_failures` com a query acima

**Result:** ⬜ pending

---

## Notas operacionais pós-execução

🔴 **Autorização é o pré-requisito de TUDO abaixo, não só do primeiro passo.** O aviso do
cabeçalho vale para Setup, T2, T7 (as duas aplicações) e T6 — qualquer um destes pode ser
recusado pelo classificador independentemente dos outros já terem passado. Não assuma que
autorizar uma vez cobre a sessão inteira; se o classificador recusar de novo no meio do
roteiro, é o mesmo mecanismo, não uma regressão.

🔴 **T6 tem que ser o último passo mutante.** Ele apaga a grade inteira — qualquer teste
depois dele partiria de 24×7 natural, não do estado que T1-T5(-T7) descrevem.

⚠️ **Se pular T7:** vá direto de T5 (descartando o token) para T6. Nenhum dos testes
restantes depende de T7 ter rodado.

⚠️ **F140 nesta sprint:** reconecte a sessão MCP depois do deploy, antes de T1 — é a
primeira chamada que usa `bid_modifier` DENTRO de um item de `windows[]`. Setup, T2, T3, T4
e T6 não usam o campo novo e não seriam afetados por um schema desatualizado.

1. **Se qualquer T falhar:** crie um finding `F###`. Severidade **HIGH** se a falha for em
   T2/T3 (criterion_id divergente = recriação silenciosa) ou em T7 (concorrência otimista
   não bloqueou) — são as duas invariantes mais caras do plano. **MEDIUM** nos demais casos
   (preview com forma errada, cobertura incorreta).
2. **Se todos passarem:** atualize `docs/operacao/findings-catalog.md` — F149 muda de
   "ABERTO" para "CORRIGIDO", com um bloco `✅ CORRIGIDO em <data> (PR #<N>)` no mesmo
   padrão usado para F150/F151 (mesma entrada, não um finding novo). Atualize também
   `docs/operacao/estado-atual.md` (mover bid_modifier por janela de "sprint em andamento"
   para "entregue, smoke ✅") e `sprint-history.md` com a entrada da sprint.
3. Depois do merge, confirme tool count em produção (deveria seguir 68 — nenhuma tool nova,
   só schema) para fechar o "Escopo confirmado" do cabeçalho.

---

## Sign-off checklist — TODO após execução

- [ ] Pre-push gate 6/6 PASS para o commit deste documento
- [ ] Autorização do Wellington obtida NA SESSÃO QUE EXECUTA, antes do Setup — aval
      relayado não vale (medido em 04/09, ver cabeçalho)
- [ ] Branch mesclado em `main`, CI verde, deploy fechado (`ci.yml` job `deploy`, gated)
- [ ] Sessão MCP reconectada pós-deploy, capaz de aceitar `bid_modifier` por item de
      `windows[]` (F140 — ver nota no cabeçalho)
- [ ] Setup PASS — 5 criteria criados com `bid_modifier: 1.0`, `BASELINE_IDS` anotado
- [ ] T1 PASS — 1 `update`, zero `add`/`remove`, `cobertura.reduz: false`,
      `bid_modifier_antigo`/`novo` corretos na entrada de MONDAY
- [ ] T2 PASS — GAQL por `criterion_id` confirma MONDAY em `~1.4` (float32 do
      Google, ex. `1.399999976158142` — tolerância, não igualdade exata; ver
      nota do fix C1 na validação detalhada de T2) e as outras 4 intactas em
      `1.0` (exato — 1.0 não sofre arredondamento de float32), todos os 5 ids
      iguais a `BASELINE_IDS`
- [ ] T3 PASS — conjunto de `criterion_id` pós-apply idêntico a `BASELINE_IDS` (nenhuma
      recriação)
- [ ] T4 PASS — `no_changes: true`, sem `confirmation_token`
- [ ] T5 PASS — MONDAY ausente de `bid_modifier_updated`; TUESDAY-FRIDAY presentes com o
      escalar `2.0`; token descartado
- [ ] T7 (se executado) PASS — apply de `token_A` recusado com o texto exato citado;
      WEDNESDAY confirmado em `1.8` (valor de B), não `1.2` (valor de A)
- [ ] T6 PASS — `has_schedule: false`, `hours_per_week: 168.0`, `run_gaql` sem filtro de
      status devolve `row_count: 0`
- [ ] Zero findings novos OU todos catalogados (série F###) com cross-reference
- [ ] `findings-catalog.md`: F149 marcado `✅ CORRIGIDO`, mesmo padrão de F150/F151
- [ ] `estado-atual.md` atualizado
- [ ] `sprint-history.md` ganha a entrada da sprint

---

## Referências

- Plan: `docs/superpowers/plans/2026-09-04-bid-modifier-por-janela.md` (Tasks 1-6)
- Ledger: `.superpowers/sdd/2026-09-04-bid-modifier-por-janela/progress.md` (2 Rulings, execução das 5 tasks)
- Task reports: `.superpowers/sdd/2026-09-04-bid-modifier-por-janela/task-{1,2,3,4,5}-report.md`
- Finding fechado por este smoke: F149 (`docs/operacao/findings-catalog.md`)
- Precedente de forma (não fechar sprint de tool mutante com apply/restauração pending): F150, F151 (mesmo arquivo)
- Runbook irmão, mesma conta e mesma campanha, fonte do precedente de auto-mode e da prova de remoção real (não `REMOVED`): `docs/operacao/phase-3b-42-ad-schedule-smoke.md`
- Molde estrutural (mais recente antes deste): `docs/operacao/phase-3b-43-particao-horaria-smoke.md`
- Estado: `docs/operacao/estado-atual.md`
