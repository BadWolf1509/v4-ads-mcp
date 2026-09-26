# Estado atual — V4 Ads MCP

> **Volátil por natureza.** Esta é a seção que muda a cada sessão; ela vivia no
> `CLAUDE.md` e era o motivo de ele reinchar — estado e convenção no mesmo arquivo
> significa que todo trabalho novo empurra bytes para dentro do que é carregado sempre.
> O `CLAUDE.md` mantém um resumo de poucas linhas e aponta para cá.

> **Ao terminar uma sessão, atualize ESTE arquivo**, não o `CLAUDE.md`.

> 🔑 **E mantenha-o curto.** Em 20/09 ele estava com **91 KB**, dos quais 83 eram a
> narrativa de uma frente **já concluída** — narrando como *"falta só o merge"* sete PRs
> mesclados, e contradizendo a própria tabela duas telas abaixo. Arquivo de estado que
> narra o passado deixa de ser confiável sobre o presente, que é a única coisa que ele
> faz. A narrativa foi para
> [`_archive/varredura-2026-09-06-frentes.md`](../_archive/varredura-2026-09-06-frentes.md).
> **Trabalho que fechou sai daqui:** o defeito vai para o catálogo, a narrativa para o
> arquivo, e aqui fica uma linha.

---

## Produção — medido em 2026-09-25

| | |
|---|---|
| Revisão servindo | **`v4-ads-mcp-00125-hct`**, 100% do tráfego — `/health?deep=1` devolveu `db: ok` e `tools: 68`. ⚠️ O handshake MCP **autenticado NÃO foi conferido**: segue desarmado (F186), então "registry montado" aqui é o que o health afirma, não o que um `tools/list` provou |
| Tools | **68** (62 Google + 6 Meta) |
| Buckets | 22 always + 46 defer — **próxima remedição 04/10** ([método](tool-buckets-2026-09-04.md)) |
| Catálogo | até **F192** (~5.300 linhas, 545 KB) |

**Caminho de mutação verificado após os bumps de 20/09** (`grpcio` 1.84, `google-auth`
2.58, `google-api-core` 2.38): duas mutações reais em `1163862076` com
`provider_request_id` e confirmação por GAQL, conta sem resíduo. O de leitura já tinha
controle positivo. Detalhe na entrada do **F182**, que o smoke verificou de quebra.

⚠️ **`deploy: skipped` NAO significa "PR de documentação".** O gate do F138 pula o
deploy só quando o push mexeu **exclusivamente** em `docs/` e markdown — um arquivo em
`tests/` conta como código e publica revisão. Em 20/09 o merge do #97 (guard novo +
docs) deployou, e eu só percebi remedindo: **cheque a revisão servindo, não o rótulo
do PR.**

Contagens de tool e bucket vêm do registry (`import_all_tools()`), não de `grep` —
**`grep` e `ast.literal_eval` já erraram esta medição**, o segundo devolvendo zero (F183).

## Decision gates abertos

**`GOOGLE_RECONCILE_APPLY=false`** — verificado em produção em 20/09. O laço de
reconciliação Google roda em **observação**: compara, conta, e **não revoga**. Virar a
trava depende do soak. O lado **Meta já revoga** (`META_RECONCILE_APPLY=true` desde
09/09, verificado no mesmo dia).

**Soak medido em 25/09:** 21 execuções diárias (05/09 a 25/09), todas `success`,
`complete=True`, `applied=False`, `revoked_grants=0` e `revoke_candidates=34` — o backlog,
conferido por query independente: 34 grants vivos em 9 contas inativas, o mesmo de 05/09.
Os desvios da previsão têm causa: `added` em 09/09 e 18/09 (contas novas no MCC) e
`bumped=3` em 24 e 25/09 — **três contas sumiram do MCC** e estão a uma ausência do limiar
de 3. Se seguirem fora, a execução de **26/09** reporta `removed=3` e `revoke_candidates=46`
(+12 grants): o primeiro exercício real do caminho de remoção em dry-run. O PR 3 do
[spec do gate](../superpowers/specs/2026-09-05-gate-google-design.md) — filas no painel,
sinal do alerta, runbook — **já está feito** (Tasks 6 e 7 do plano de 05/09; métrica e
policy executadas em 05/09, ver `infra-setup.md`). **O que falta para a virada:** a
execução de 26/09 confirmar a previsão, e a resposta sobre as três contas.

**Fase 2B travada no soak** — o tombstone dos 8 reports antigos não acontece enquanto os
gestores não migrarem para `get_performance_breakdown`. Re-checar por `audit_log`.
⚠️ O plugin `v4-trafego-google-ads` **0.4.0 empurrava ativamente na direção errada**, com
duas afirmações falsas sobre o breakdown; o **0.4.1 corrigiu e está instalado** (20/09).
**Medido em 25/09:** o antigo segue mais usado que o novo — em 30 dias,
`get_campaign_performance` teve 148 chamadas de 3 gestores contra 33 do
`get_performance_breakdown` (1 gestor); desde 20/09, 20 contra 14. O 0.4.1 **já** manda
usar o breakdown em todos os skills, então o motor está em outro lugar: versão do plugin
na máquina dos outros gestores, ou o LLM escolhendo a tool pelo nome. Separar por gestor
é a medida de 04/10.

## Pendências que dependem do Wellington

- **Três contas Google saíram do MCC em 24/09** — `4493906974`, `8726746966` e `9450567241`, 4 grants vivos cada. Churn ou desvinculação por engano? A resposta muda a virada da trava Google: se foi engano, revincular antes.
- **F129** — governança do system user Meta: ação humana, fora do código.
- **F67** — custom domain `mcpv4.fluxocerto.dev.br`, pendente via LB.
- **Pedir ao TI da V4 uma identidade `@v4company.com` sem caixa postal** (alias ou conta de serviço) — é o que **desbloqueia o F186 por inteiro**: manager com grant zero, pior caso de vazamento `tools/list`, e a reconciliação não a toca. Sem ela não há token de CI possível: `sessions_create` só emite para o próprio manager logado, e login exige identidade Google do domínio. **Emitir sob um manager existente está recusado** — poria no GitHub Actions um token com alcance de ~38 contas Google e 26 Meta.
- **Varredura de `recommendation_subscription` sobre o MCC** — pedida pela sessão de tráfego a partir do F185. **Recomendado:** a tool de LEITURA, desenhada para varrer **só o que o gestor já alcança** (varredura que vê além do hard-gate de acesso vira caminho lateral para o gate) e para **contar os opacos em vez de descartá-los**. **Não recomendada:** a tool de escrita — o F185 mostra que 4 de 11 não têm chave, então ela alcançaria 7 de 11 e seria obrigada a dizer isso.

## Smokes de leitura — todos executados

A seção nasceu e esvaziou no mesmo dia (20/09), e o ciclo vale mais que o resultado: os dois
itens estavam **invisíveis** — nenhum arquivo vivo apontava para eles, e a única lista de
pendências era a das que dependem do gestor, onde leitura pendente não cabia. Ganharam ponteiro
na revisão de contexto e foram executados em seguida, sem aval, porque nunca precisaram de um.

- **3b.43** (`particao-horaria`) — **6/6 PASS**, e achou o **F188**.
  [`phase-3b-43-particao-horaria-smoke.md`](phase-3b-43-particao-horaria-smoke.md)
- **3b.41** (`assets`) — **9/9 PASS** com o T2 fechado.
  [`phase-3b-41-assets-smoke.md`](phase-3b-41-assets-smoke.md)

**Smoke pendente sem ponteiro é smoke que ninguém roda** — a lição fica, os itens saem.

## Findings abertos

### Varredura de 21/09 (5 agentes paralelos, 4 sub-projetos)

Os 5 relatórios, recuperados do transcript em 25/09 (a extração de 21/09 tinha falhado),
estão em [`_archive/varredura-2026-09-21/`](../_archive/varredura-2026-09-21/README.md) —
com o destino de cada achado. **Os status lá são dos agentes**: achado que ninguém remediu
no código não vira trabalho até ser verificado.

| sub-projeto (decomposição de 21/09) | status |
|---|---|
| 1 · credencial + contratos do SDK Meta | fechado — **F190** |
| 2 · respostas que afirmam mais do que mediram | **em parte** — núcleo no **F191**; o resto é a frente *respostas Google* |
| 3 · infra de dados (CSV do audit, guard de reconnect, lock no `migrate.py`, `revoke` Meta) | **em parte** — CSV no F191; o resto é a frente *infra e guards* |
| 4 · guards que não cobrem (mock que bloqueava o conserto, testes que enumeram) | **em parte** — mock no F191; o resto é a frente *infra e guards* |

As **métricas Meta** que a nota do F190 chama de "sub-projeto 2" (`_parse_buc_header_pct`,
zero no lugar de campo ausente, `_brl` fixo, atribuição implícita) **nunca estiveram em
sub-projeto nenhum** — viraram a frente *métricas Meta*.

### Ordem de ataque (25/09)

Medir a exposição, dar dado às decisões, consertos pequenos, e só então specs — um por vez.

1. **Rollout Google** — soak medido e PR 3 já feito (acima): observar a execução de 26/09 → virada da trava, do Wellington.
2. **Fase 2B** — medida em 25/09 (acima); em 04/10, separar o uso por gestor, junto da remedição dos buckets.
3. **Respostas Google** (spec) — o que as respostas escondem do recorte, e o remédio do F187.
4. **Métricas Meta** (spec) — zero no lugar de "não veio", e o limitador que lê "não sei" como 0%.
5. **F154** (spec).
6. **Infra e guards** (spec) — o resto dos sub-projetos 3 e 4.
7. **`recommendation_subscription`** — tool de leitura no MCC.

### Os abertos, um por linha

| ID | o que é |
|---|---|
| **F180** | **em parte, provavelmente para sempre** — a flag `partial_failure` está ligada, mas a falha por-linha **nunca foi exercitada**: o Google aceita operação impossível em vez de errar (campanha `REMOVED`, `final_urls` inválida, anúncio apagado entre preview e apply). O único gatilho conhecido é a variação de experimento, que o **F181 agora bloqueia no pre-flight**. Consequência: `failed_count` é constante zero — leia `efeito` e `changed_count` |
| **F154** | `/me/adaccounts` não é prova de alcance |
| **F185** | `recommendation_subscription`: 4 de 11 opacos e **sem chave nenhuma** — limitação da API, sem correção possível deste lado |
| **F187** | o **resumo no topo** de um artefato é a superfície de decisão e o **detalhe embaixo** é a verdade — 4 instâncias medidas, uma quase custou mutação em conta real. Remédio proposto: derivar o resumo, ou guard que cobre a igualdade |
| **F186** | 🔴 smoke autenticado do `/mcp` **desarmado** — e o manager dele **não existe**: criar exige identidade de serviço no Workspace, acesso que o gestor **não tem**. **ABERTO como risco ACEITO.** No lugar entrou `tools` no `/health?deep=1` (sem credencial), e o desarme aparece como `::warning::` em todo deploy — **observado disparando** nos dois deploys de 21/09, que é o que separa "o aviso existe" de "o aviso avisa" |

Fechados em 20/09: **F181, F182, F183, F184** — mais a **2ª instância do F182**, que
fechou a *classe*: só o `apply_change` descreve a contagem do lote, agora com guard. O
F182 consertara a instância e deixara a classe.

Fechado em 21/09: **F188** — fix verificado em produção (`00121-hlq`) com o mesmo
instrumento que achou o defeito. Só que as duas chamadas voltaram **idênticas**, e
perguntar por quê revelou que a entrada afirmava um **segundo custo nunca alcançável**:
no `raw_grid` o teto é `168 × len(campaign_ids)` e a conjunta produz no máximo 168 células
por campanha, então `truncated: true` é falso por construção. Três textos corrigidos
(description, catálogo, docstring) com o motivo escrito em vez de apagado, e a folga que
restava ganhou guard — `test_raw_grid_ignora_o_limit_do_gestor`, validado por sabotagem.
**Afirmar dois custos onde há um é a mesma família que o F188 cataloga, do lado de quem
escreve.**

Fechados no mesmo dia: **F189** e **F190** — os dois verificados em produção, e os três
achados pelo mesmo método: **variar uma coisa só e perguntar por que o resultado mudou.**

- **F189** — `limit: 17` passava, `limit: 16` errava. A paginação Meta embrulhava a URL do
  `paging.next` numa **lista**, e o SDK só trata string como URL completa: **qualquer
  resultado com mais de uma página virava erro**, desde que o F88 introduziu a paginação.
  Foi regressão, não lacuna — antes a 1ª página voltava com sucesso.
- **F190** — o token de system user (não expira, ~24 contas) vazava para `audit_log`,
  Cloud Logging e contexto do LLM em qualquer falha de transporte. Fechado em duas
  camadas: redação em `to_friendly_meta_error` (estanca) e transporte httpx com auth por
  header (remove a causa). 19 commits, 7 tasks, verificado em produção.
  **Débito medido em 25/09: nenhuma ocorrência** no `audit_log` (história inteira) nem no
  Cloud Logging (30 dias), com controle positivo — ver a entrada no catálogo.

🔑 **Os três estavam escondidos pela mesma causa: existia a regra e não existia o
mecanismo.** A invariante do F190 estava escrita no repo desde o F82 (*"token no HEADER,
nunca na query"*) e o guard que deveria aplicá-la **enumerava dois arquivos** — o do bug
não estava na lista. O F189 tinha a implementação certa ao lado da errada. Metade das 7
tasks do F190 não consertou código: consertou **o que deveria ter pegado o código**.

Fechados em 21/09 também: **F179** e **F191** — seis superfícies (núcleo do
partial-failure/`Unpack`, Customer Match, `admin_invites_cancel`, CSV do audit,
`filters_applied`, `get_ad_schedule`) onde uma ausência de medição era lida como zero ou
sucesso. Inclui um Critical que a própria branch quase introduziu — `classify_partial`
lendo `error=None` como sucesso em 3 tools do ramo AUTO — achado só na revisão e fechado
no fix round. Detalhe completo no catálogo.

> A narrativa do sprint de RSA **saiu daqui**, pela regra do cabeçalho: ela ocupava 42
> das 111 linhas descrevendo trabalho já fechado. O detalhe de cada finding vive no
> [`findings-catalog.md`](findings-catalog.md), e o smoke em
> [`phase-rsa-f180-f181-smoke.md`](phase-rsa-f180-f181-smoke.md) — nada se perdeu, mudou
> de endereço. **Foi a primeira aplicação da regra contra o trabalho da própria sessão
> que a escreveu**, que é onde esse tipo de regra costuma morrer.
