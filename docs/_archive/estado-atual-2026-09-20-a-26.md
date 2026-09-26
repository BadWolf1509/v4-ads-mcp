# Estado atual — o que saiu em 26/09 (arquivo)

Trechos movidos **literalmente** de `docs/operacao/estado-atual.md` na reorganização de 26/09,
pela regra do cabeçalho dele: trabalho que fechou sai de lá, a narrativa vem para cá, e lá fica
uma linha. Nada foi reescrito; o estado vigente está no arquivo de origem.

## Produção — caminho de mutação verificado após os bumps de 20/09

**Caminho de mutação verificado após os bumps de 20/09** (`grpcio` 1.84, `google-auth`
2.58, `google-api-core` 2.38): duas mutações reais em `1163862076` com
`provider_request_id` e confirmação por GAQL, conta sem resíduo. O de leitura já tinha
controle positivo. Detalhe na entrada do **F182**, que o smoke verificou de quebra.

## Decision gates — a trava Google, como estava em 26/09 antes da reorganização

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
policy executadas em 05/09, ver `infra-setup.md`). **A execução de 26/09 confirmou a previsão:**
`removed=3` e `revoke_candidates=46` (34 do backlog + 12 das três contas), `applied=False`,
`complete=True` — lido no `audit_log` em transação READ ONLY. A contagem por estado segue em
34: em observação a remoção só é projetada, e as três contas continuam `is_active` com
`missed_syncs=2`. A resposta sobre elas veio no mesmo dia: **churn** — deixaram de ser
clientes da unidade, então os 12 grants delas são revogações legítimas, não algo a
revincular. **A virada está destravada e é decisão do Wellington:** trocar
`GOOGLE_RECONCILE_APPLY=false` por `true` no `JOB_ENV_VARS` do `deploy.yml` (PR com deploy).
Na primeira execução depois dela saem as três contas e são revogados os 46 grants. **Novo
em 26/09:** `bumped=1` — Alumínios Veneza (`2640486995`, 4 grants vivos) faltou no
inventário, 1ª ausência de 3.

## Smokes de leitura — todos executados

A seção nasceu e esvaziou no mesmo dia (20/09), e o ciclo vale mais que o resultado: os dois
itens estavam **invisíveis** — nenhum arquivo vivo apontava para eles, e a única lista de
pendências era a das que dependem do gestor, onde leitura pendente não cabia. Ganharam ponteiro
na revisão de contexto e foram executados em seguida, sem aval, porque nunca precisaram de um.

- **3b.43** (`particao-horaria`) — **6/6 PASS**, e achou o **F188**.
  [`phase-3b-43-particao-horaria-smoke.md`](../operacao/phase-3b-43-particao-horaria-smoke.md)
- **3b.41** (`assets`) — **9/9 PASS** com o T2 fechado.
  [`phase-3b-41-assets-smoke.md`](../operacao/phase-3b-41-assets-smoke.md)

**Smoke pendente sem ponteiro é smoke que ninguém roda** — a lição fica, os itens saem.

## Findings fechados de 20 a 21/09 — a narrativa que morava aqui

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
> [`findings-catalog.md`](../operacao/findings-catalog.md), e o smoke em
> [`phase-rsa-f180-f181-smoke.md`](../operacao/phase-rsa-f180-f181-smoke.md) — nada se perdeu, mudou
> de endereço. **Foi a primeira aplicação da regra contra o trabalho da própria sessão
> que a escreveu**, que é onde esse tipo de regra costuma morrer.
