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

## Produção — medido em 2026-09-21

| | |
|---|---|
| Revisão servindo | **`v4-ads-mcp-00123-tz8`** — `/health?deep=1` devolveu `db: ok` e `tools: 68`. ⚠️ O handshake MCP **autenticado NÃO foi conferido**: segue desarmado (F186), então "registry montado" aqui é o que o health afirma, não o que um `tools/list` provou |
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

**Fase 2B travada no soak** — o tombstone dos 8 reports antigos não acontece enquanto os
gestores não migrarem para `get_performance_breakdown`. Re-checar por `audit_log`.
⚠️ O plugin `v4-trafego-google-ads` **0.4.0 empurrava ativamente na direção errada**, com
duas afirmações falsas sobre o breakdown; o **0.4.1 corrigiu e está instalado** (20/09).

## Pendências que dependem do Wellington

- **F190 — não foi medido se o token Meta já vazou.** Decisão de 21/09: consertar para frente, sem rotação nem expurgo de log. A conta que responderia é um `COUNT(*)` em `audit_log` por `error_message` com nome de parâmetro de token, e **ela não foi executada** — "ninguém mediu" não é "nunca aconteceu".
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

| sub-projeto | conteúdo | status |
|---|---|---|
| 1 | transporte Meta / token em query string | fechado — **F190** |
| 2 | terceiro estado não medido (`Unpack`/partial-failure, F179, CSV do audit, `filters_applied`, `get_ad_schedule`) | fechado — **F191**. F154, que fazia parte do recorte original, **saiu para spec próprio** |
| 3 | não descrito nesta tabela — sem spec ainda | pendente |
| 4 | não descrito nesta tabela — sem spec ainda | pendente |

**2 de 4 sub-projetos fechados** (era 1 antes desta sessão). ⚠️ A nota "fora de escopo" do F190 usa "sub-projeto 2" para um recorte DIFERENTE (métricas Meta: `_parse_buc_header_pct`, `spend_brl`/`cpc_brl`, `ctr`, taxonomia de `actions`, janelas de atribuição) — escrita **antes** da reclassificação que a abertura do spec do F191 documenta. Os dois "sub-projeto 2" não são o mesmo recorte; qual dos dois está vivo não foi conferido aqui.

| ID | o que é |
|---|---|
| **F178** | callback OAuth renderiza sem CSS — `<style>` inline barrado pela CSP |
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
  ⚠️ **Débito declarado: NÃO foi medido se o token já vazou** — ver a entrada no catálogo.

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
