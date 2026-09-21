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

## Produção — medido em 2026-09-20

| | |
|---|---|
| Revisão servindo | **`v4-ads-mcp-00119-7f8`** — saúde conferida por `/health?deep=1` (`tools: 68`) e handshake MCP real |
| Tools | **68** (62 Google + 6 Meta) |
| Buckets | 22 always + 46 defer — **próxima remedição 04/10** ([método](tool-buckets-2026-09-04.md)) |
| Catálogo | até **F187** (~4.430 linhas) |

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

- **F129** — governança do system user Meta: ação humana, fora do código.
- **F67** — custom domain `mcpv4.fluxocerto.dev.br`, pendente via LB.
- **Pedir ao TI da V4 uma identidade `@v4company.com` sem caixa postal** (alias ou conta de serviço) — é o que **desbloqueia o F186 por inteiro**: manager com grant zero, pior caso de vazamento `tools/list`, e a reconciliação não a toca. Sem ela não há token de CI possível: `sessions_create` só emite para o próprio manager logado, e login exige identidade Google do domínio. **Emitir sob um manager existente está recusado** — poria no GitHub Actions um token com alcance de ~38 contas Google e 26 Meta.
- **Varredura de `recommendation_subscription` sobre o MCC** — pedida pela sessão de tráfego a partir do F185. **Recomendado:** a tool de LEITURA, desenhada para varrer **só o que o gestor já alcança** (varredura que vê além do hard-gate de acesso vira caminho lateral para o gate) e para **contar os opacos em vez de descartá-los**. **Não recomendada:** a tool de escrita — o F185 mostra que 4 de 11 não têm chave, então ela alcançaria 7 de 11 e seria obrigada a dizer isso.

## Pendências que NÃO dependem de aval — são leitura pura

Estavam invisíveis até a revisão de 20/09: **nenhum arquivo vivo apontava para elas**, e
a lista acima só cobre o que depende do gestor. **Smoke pendente sem ponteiro é smoke que
ninguém roda** — e foi assim que dois sumiram de vista.

- **Smoke 3b.43 (`particao-horaria`) — `0/6 executados`.** Os seis são LEITURA
  (`get_ad_schedule(include_metrics)` e `get_performance_breakdown` com `hourly`, `geo` e
  `raw_grid`), então **não precisam de aval**: rodam em qualquer sessão.
  [`phase-3b-43-particao-horaria-smoke.md`](phase-3b-43-particao-horaria-smoke.md).
- **Smoke 3b.41 (`assets`) — `8/9`, o T2 pendente.** Também leitura: `get_assets` com
  `field_type="CALLOUT"`, conferindo que o filtro se aplica e que `links[]` é subconjunto
  do T1. [`phase-3b-41-assets-smoke.md`](phase-3b-41-assets-smoke.md).

## Findings abertos

| ID | o que é |
|---|---|
| **F178** | callback OAuth renderiza sem CSS — `<style>` inline barrado pela CSP |
| **F179** | `admin_invites_cancel` audita cancelamento que pode não ter ocorrido |
| **F180** | **em parte, provavelmente para sempre** — a flag `partial_failure` está ligada, mas a falha por-linha **nunca foi exercitada**: o Google aceita operação impossível em vez de errar (campanha `REMOVED`, `final_urls` inválida, anúncio apagado entre preview e apply). O único gatilho conhecido é a variação de experimento, que o **F181 agora bloqueia no pre-flight**. Consequência: `failed_count` é constante zero — leia `efeito` e `changed_count` |
| **F154** | `/me/adaccounts` não é prova de alcance |
| **F185** | `recommendation_subscription`: 4 de 11 opacos e **sem chave nenhuma** — limitação da API, sem correção possível deste lado |
| **F187** | o **resumo no topo** de um artefato é a superfície de decisão e o **detalhe embaixo** é a verdade — 4 instâncias medidas, uma quase custou mutação em conta real. Remédio proposto: derivar o resumo, ou guard que cobre a igualdade |
| **F186** | 🔴 smoke autenticado do `/mcp` **desarmado** — e o manager dele **não existe**: criar exige identidade de serviço no Workspace, acesso que o gestor **não tem**. **ABERTO como risco ACEITO.** No lugar entrou `tools` no `/health?deep=1` (sem credencial), e o desarme aparece como `::warning::` em todo deploy |

Fechados em 20/09: **F181, F182, F183, F184** — mais a **2ª instância do F182**, que
fechou a *classe*: só o `apply_change` descreve a contagem do lote, agora com guard. O
F182 consertara a instância e deixara a classe.

> A narrativa do sprint de RSA **saiu daqui**, pela regra do cabeçalho: ela ocupava 42
> das 111 linhas descrevendo trabalho já fechado. O detalhe de cada finding vive no
> [`findings-catalog.md`](findings-catalog.md), e o smoke em
> [`phase-rsa-f180-f181-smoke.md`](phase-rsa-f180-f181-smoke.md) — nada se perdeu, mudou
> de endereço. **Foi a primeira aplicação da regra contra o trabalho da própria sessão
> que a escreveu**, que é onde esse tipo de regra costuma morrer.
