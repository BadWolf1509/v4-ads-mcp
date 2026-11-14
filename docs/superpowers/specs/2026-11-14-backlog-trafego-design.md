# Backlog de tráfego (sessão Gestor de Tráfego JP) — desenho

**Data:** 2026-11-14 · **Origem:** `D:\Gestor de Tráfego de Ads\mcp-v4-ads-backlog-melhorias.md`
(tabela "ESTADO — revisto em 14/11") · **Aprovação:** Wellington, item a item nesta sessão.

Oito entregas independentes, um PR por item, na ordem combinada com a sessão de tráfego:
M1 → N1+N2 → N3 → G1 → G2 → M2 → end_experiment → M3. F154/F178/F179 saíram do backlog
(fechados no catálogo em 21–27/09).

Regras que valem para todos: tool nova ou parâmetro novo só aparece em sessão nova (F140);
smoke de mutate só com o gestor presente; I/O pós-escrita nunca vira erro (F83/F91);
proto-plus omite default — "não lido" é `null`, nunca o default (F145); guard que falha contra
o código pré-fix.

---

## M1 — estado de aprovação do RSA depois do write ✅ aprovado

**Por quê.** O `apply_change` de `update_rsa`/`create_rsa` devolve só `efeito`/`changed_count`;
anúncio reprovado passa sem ninguém ver. Nenhuma tool curada expõe `approval_status` hoje
(0 ocorrências de `approval_status`/`policy_summary` em `src/`, medido 14/11).

**Restrição medida.** Logo após o write o Google responde quase sempre "em revisão" — o campo é
foto do instante, não veredito.

**Abordagens.**
- A (escolhida) — foto no pós-write + GAQL de releitura pronta na resposta. Sem superfície nova.
- B — campos de política no `get_performance_breakdown(level=ad)`: descartada; anúncio novo não
  tem impressão e some de relatório por data (mesma armadilha do N1), e é contrato novo em
  relatório de métrica.
- C — tool `check_ad_approval`: descartada pelo Wellington (catálogo já tem 80 tools).

**Desenho.**
- Confirmador `_RSA` em `src/google_ads/confirmadores.py`, registrado para `update_rsa` e
  `create_rsa`; `executar` igual ao `_Padrao`.
- `pos_check`: uma GAQL sobre os `resource_names` gravados lendo
  `ad_group_ad.policy_summary.approval_status`, `review_status` e tópicos de política. Devolve
  `estado_revisao` por anúncio + `lido_em` + aviso "em revisão não é veredito".
- `releitura`: a GAQL pronta (FROM `ad_group_ad`, sem `segments.date`) para rodar depois no
  `run_gaql`.
- Falha da releitura → escrita segue sucesso, com `confirmation_error` (molde do `_AdSchedule`).
- **Guard:** teste exige `estado_revisao` (falha no código de hoje); teste com a releitura
  quebrando exige sucesso preservado.
- **Prova:** dry-run + apply com o gestor presente, sessão nova.

---

## N1 + N2 — avisos do `validate_gaql`/`run_gaql` ✅ aprovado (um PR)

### N1 — `segments.date` no SELECT esconde entidade sem tráfego

**Premissa corrigida por medição (MO-JP, 14/11, 4 campanhas REMOVED com 0 impressão):**

| consulta | linhas |
|---|---|
| sem data | 4 |
| `segments.date` só no WHERE | 4 |
| idem + `metrics.impressions` | 4 |
| `segments.date` no SELECT (com ou sem métrica) | 0 |

O que esconde é a data **no SELECT**, não no WHERE. `segments.week/month/quarter/year` e outros
segmentos: **não medidos** — a regra cobre só `segments.date`.

**Desenho.** Lint estático compartilhado (sem chamada à API) usado por `validate_gaql` e
`run_gaql`: `segments.date` no SELECT → campo novo `avisos[]` com "linhas só existem para dias
com dado; entidade sem tráfego no período não aparece. Para inventário, tire `segments.date` do
SELECT (no WHERE ele não esconde nada — medido 14/11)". Dispara **sempre** (decisão do
Wellington), com ou sem métrica. Não altera `valid` nem `rows`.

**Guard:** data no SELECT → aviso presente; data só no WHERE → ausente. Ambos falham hoje
(o campo não existe).

### N2 — "must be present in SELECT"

**Premissa não procede:** o `validate_gaql` já devolve `valid:false` com a mensagem do Google,
que nomeia o campo (medido 14/11, `geographic_view` filtrada por `campaign.id`). O defeito real:
todo erro de GAQL recebe o sufixo genérico ("métricas existem só em certos recursos… auction
insights…"), irrelevante aqui.

**Desenho.** Em `_augment_error_hint`, mensagem "must be present in SELECT" → hint específico
"adicione ao SELECT o campo citado", no lugar do sufixo genérico. **Guard** com a mensagem real.

---

## N3 — `update_recommendation_subscription` ✅ aprovado

**Por quê.** Na MO-JP a assinatura `RESPONSIVE_SEARCH_AD` está ENABLED desde 06/06/2024 e a UI
não a lista (F185); só a API pausa. Remedido em 14/11: 11 tipos, só esse ENABLED, 4 `UNKNOWN`
com `resource_name` degenerado (F185 inalterado na v25).

**Medição de urgência (sessão de tráfego, 14/11, change_event 16/10–14/11):** 0 eventos de
recomendação; o controle sem filtro devolveu 73, todos `GOOGLE_ADS_API`. Ressalva: o filtro usado
(`GOOGLE_ADS_RECOMMENDATIONS`) não captura auto-apply de assinatura, que chega como
`GOOGLE_ADS_RECOMMENDATIONS_SUBSCRIPTION` (F142) — a conclusão vale pelo controle sem filtro,
não pelo filtro. Janela máxima do change_event: 30 dias; antes disso, não medido.

**Abordagens.** Pausa e reativa (escolhida — reversível pelo mesmo mecanismo) vs só pausa
(desfazer só pela UI, que nem lista o tipo).

**Desenho.** Tool `update_recommendation_subscription(customer_id, type, status: PAUSED|ENABLED)`.
- `type` = enum `RecommendationType` do SDK menos `UNKNOWN`/`UNSPECIFIED`; guard cruza com o enum
  (lição F142).
- Dry-run lê o estado atual por GAQL. Recusa: tipo sem assinatura (criar está fora do escopo —
  seria ligar auto-apply novo), `UNKNOWN`/ambíguo (cita F185). Já no status pedido → "já está X",
  sem token.
- Preview antes→depois; `ENABLED` com aviso "o Google passa a aplicar recomendações deste tipo
  sozinho" e risco alto. Sempre token.
- Executa via `GoogleAdsService.mutate` (`recommendation_subscription_operation`,
  `update_mask=status`). `pos_check` relê → `status_resultante`; divergência → `efeito: sem_efeito`;
  falha da releitura → `confirmation_error`.
- **Guards:** recusa UNKNOWN, "já está", enum, divergência pós-write.
- **Prova:** pausar `RESPONSIVE_SEARCH_AD` na MO, sessão nova, gestor presente.

---

## G1 — `get_experiments` (leitura) ✅ aprovado

**Por quê.** Teste de URL `10061805617` (AD_VARIATION, ENABLED até 2027-01-07) pode pedir 2ª
variação em 08/01; decidir exige comparar base × variação, não só listar.

**Medido na MO-JP, 14/11 (v25):** `FROM experiment` completo (2 experimentos). `experiment_arm`
segue vazio além de `resource_name`/`experiment` (F181) — **a API não liga braço a anúncio**.
13 anúncios `AD_VARIATIONS`: 10 ENABLED em 5 grupos (2 por grupo), 3 REMOVED.

**Abordagens.** Com comparativo (escolhida) vs só inventário (comparativo a cargo do gestor).

**Desenho.** Tool de leitura `get_experiments(customer_id, experiment_id?)`.
- `FROM experiment`: id, nome, tipo, status, início, fim.
- AD_VARIATION, por grupo: base = RSAs sem `system_managed_resource_source`; variação = RSAs
  `AD_VARIATIONS` ENABLED.
- Atribuição por eliminação: 1 experimento AD_VARIATION ENABLED → variações ENABLED dele,
  `atribuicao: "inferida_por_eliminacao"`; 2+ → `null` + motivo (F181); REMOVED não se atribui.
- Comparativo por grupo (base somada × variação somada: impressões, cliques, custo, conversões,
  CPA) na janela `start_date` → min(ontem, `end_date`), declarada na resposta. Data só no WHERE
  (N1). Denominador zero → `null`. Aviso: não é o teste de significância da UI.
- Experimento de campanha: só na lista, sem comparativo (formato não medido — nenhum na MO).
- **Guards:** 2 ENABLED → `null`; anúncio sem tráfego aparece com zero; braço vazio não quebra.
- **Prova:** chamada real no `10061805617`, sessão nova.

**Adendo ao M1 (medido 14/11 no G2):** cada headline/description traz `policy_summary_info`
próprio (approval/review por asset) — o `estado_revisao` do M1 pode apontar QUAL texto foi
reprovado, não só o anúncio.

---

## G2 — `pinned_field` em `create_rsa`/`update_rsa` ✅ aprovado

**Medido 14/11:** amostra de 8 dos 40 RSAs ENABLED da MO sem nenhum `pinned_field` (32 não medidos).

**Abordagens.** Item string-ou-objeto (escolhida, retrocompatível) vs listas paralelas de índices
(frágil, desalinha).

**Desenho.**
- `headlines`/`descriptions` aceitam string ou `{text, pinned_field}` (`HEADLINE_1..3`,
  `DESCRIPTION_1..2`). String = sem pino. Builder seta `AdTextAsset.pinned_field`.
- `update_rsa`: pré-flight lê os pinos atuais; lista nova que perde pino → **recusa** listando-os;
  só segue com `remover_pinos: true` (decisão do Wellington). Default omitido = sem pino (F145).
  **"Perder pino" é por POSIÇÃO** (decisão do Wellington após a revisão): recusa só quando uma
  posição que hoje tem pino fica sem nenhum; reescrever o texto mantendo a posição segue, com
  antes→depois no preview. `remover_pinos` vale **por update**, não pelo lote.
- Preview com pinos por posição + aviso de força do anúncio. **Sem `validate_only`** (decisão do
  Wellington após a revisão): como todo mutate do projeto, o dry-run não chama o Google; pino
  inválido erra no `apply_change`, com motivo por linha (`partial_failure`).
- Audit: contagem de pinos por posição, sem texto.
- **Guards:** update sem pino sobre pinado → recusa (falha hoje); com flag → segue; item string →
  payload idêntico ao atual.
- **Prova:** dry-run + apply com gestor, sessão nova, RSA de teste pausado.

---

## M2 — teto de lote de RSA: 5 → 50 ✅ aprovado

**Por quê.** Trocar `final_url` dos 33 RSAs ativos da MO = 7 chamadas com dry-run+token. O 5 não
tem racional registrado (sprint 3b.18); pré-requisitos fechados (`partial_failure` B1, `efeito` F184).

**Abordagens.** 50 (escolhida; = `update_ad_group_bid`) vs 15 (preview com texto inteiro) vs manter 5.

**Desenho.**
- `maxItems` 5 → 50 em `create_rsa.rsas` e `update_rsa.updates`, numa constante única usada pelas
  duas tools e pelo guard.
- Preview compacto acima de 5 itens: por anúncio, campos que mudam + contagens; texto inteiro só
  quando o texto muda; URL/path sempre.
- Releituras do M1 (aprovação) e G2 (pinos) em UMA GAQL para o lote.
- Mantidos: always-CONFIRM, `partial_failure`, `efeito`.
- **Guards:** 51 recusa / 50 passa (validação real do schema); tamanho do preview de 50 abaixo de
  teto medido; guard F183 segue cobrindo os dois arrays.
- **Prova:** lote real de troca de `final_url` na MO com o gestor presente.

**Adendo ao G1 (decisão de 14/11, no item end_experiment):** a resposta da `get_experiments`
diz como aplicar o resultado — `update_rsa` no anúncio base, cujo `ad_id` vem por grupo; a
variação herda em minutos (F181) — sem tool nova.

---

## end_experiment — ❌ fora do escopo (decisão do Wellington, 14/11)

O `10061805617` termina sozinho em 2027-01-07 (`end_date` medido 14/11); o uso pedido é
**aplicar o resultado**, que já tem caminho (`update_rsa` no base; ver adendo do G1).
`end_experiment` (parar antes), `promote_experiment` (semântica em AD_VARIATION não medida),
`graduate_experiment` e criar experimento novo ficam de fora.

---

## M3 — compatibilidade no `list_gaql_resources` ✅ aprovado

**Abordagens.** Fonte do Google (escolhida: `GoogleAdsFieldService.selectable_with`, não
apodrece) vs lista curada datada (envelhece; o backlog já alertava) vs não fazer.

**Desenho.**
- Parâmetro opcional `resource`. Sem ele: resposta atual. Com ele: `compativel: {segments[],
  metrics[], resources_atribuidos[]}` do `selectable_with` + `fonte: "GoogleAdsFieldService v25"`.
- Cache em memória por (versão da API, recurso); sem tabela/migration.
- Metadado, não dado de conta: sem gate por conta, mas com reserva de rate-limit e audit (molde
  `validate_gaql`).
- Falha → catálogo estático + `compativel: null` + motivo; nunca `[]`.
- Null silencioso (`quality_info` + `segments.date`, medido 19/09 pela sessão de tráfego) entra
  como aviso no lint do N1, após remedição.
- **Guards:** com `resource` → `compativel` preenchido (mock no formato real do serviço); falha →
  `null` com motivo; sem `resource` → resposta idêntica à atual.
- **Prova:** chamada real `resource="ad_group_ad"` sem `segments.hour` (medido 19/09), sessão nova.

---

## Revisão do builder (14/11) — decisões que saíram dela

Do Wellington: critério de pino por posição e sem `validate_only` (no G2, acima).

Minhas, para conferir:
- **G1 — pareamento.** Medido 14/11: os 5 grupos em teste têm 2 bases ENABLED + 2 variações
  cada (bases em `/unidades/joaopessoa/…`, variações em `lp.…#…`). Comparativo somado por grupo;
  a resposta lista **todos** os `ad_id` base do grupo, sem parear base↔variação. Base = só ENABLED;
  só entram grupos com variação ENABLED.
- **N2 — escopo.** O sufixo genérico mora em `src/google_ads/errors.py` (ramo `QUERY_ERROR`), não
  em `_augment_error_hint`. A troca é lá: `run_gaql` e `validate_gaql` recebem o hint específico.
- **M1 — por asset no mesmo PR.** `estado_revisao` já sai com os textos reprovados
  (`policy_summary_info` por asset); mudar o shape depois seria contrato novo (F140).
- **G2 × M1 — releitura de pinos.** O `_RSA` do M1 também relê os pinos pós-write; pino pedido que
  não pegou → `efeito: sem_efeito`. É isto que o M2 unifica numa GAQL.
