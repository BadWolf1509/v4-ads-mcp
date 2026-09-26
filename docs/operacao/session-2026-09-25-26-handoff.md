# Sessão 2026-09-25/26 — Handoff (medir, fechar o F193, virar a trava Google)

> Dois dias, sete PRs mergeados (#108–#114; três deles com deploy). Este é o **mapa**;
> a enciclopédia é o [`findings-catalog.md`](findings-catalog.md), e o estado vivo é o
> [`estado-atual.md`](estado-atual.md). A sessão seguiu a ordem de ataque de 25/09: medir a
> exposição, dar dado às decisões, consertos pequenos, e só então spec — um por vez.

## TL;DR

| PR | O quê | Em produção |
|---|---|---|
| [#108](https://github.com/BadWolf1509/v4-ads-mcp/pull/108) | orçamento do `CLAUDE.md` (F192): tripwires roteados por área, três formas de registro de finding no catálogo | docs |
| [#109](https://github.com/BadWolf1509/v4-ads-mcp/pull/109) | os 5 relatórios da varredura de 21/09 recuperados e arquivados, com o destino de cada achado ([índice](../_archive/varredura-2026-09-21/README.md)); débito do F190 medido | docs |
| [#110](https://github.com/BadWolf1509/v4-ads-mcp/pull/110) | **F178** (callback OAuth vira template; guard do `<style>`) e três "não sei vira número" (mensagem do Customer Match, `try` do partial-failure, teto de `days` no CSV) | `v4-ads-mcp-00126-n8r` |
| [#111](https://github.com/BadWolf1509/v4-ads-mcp/pull/111) | **F193** — respostas Google dizem o recorte que mediram: razão sem denominador vira `null`, `filters_applied` em 16 tools, `bulk_pause_by_query` mede no período, resumo do `add_negatives` conta como o envelope | `v4-ads-mcp-00127-9x6` |
| [#112](https://github.com/BadWolf1509/v4-ads-mcp/pull/112) | pós-deploy do F193 (smoke em produção, limite do `sem_dados_no_periodo`) e a execução de 26/09 da reconciliação Google | docs |
| [#113](https://github.com/BadWolf1509/v4-ads-mcp/pull/113) | organização da documentação e da memória para o compact: este handoff, e o `estado-atual.md` de 16 para 12 KB, com a narrativa fechada arquivada | docs |
| [#114](https://github.com/BadWolf1509/v4-ads-mcp/pull/114) | **virada da trava Google** (`GOOGLE_RECONCILE_APPLY=true`), com autorização nominal; conferida na execução sob demanda — 3 contas desativadas, 46 grants revogados | `v4-ads-mcp-00128-j2h` |

## O que foi medido

- **F190:** nenhuma ocorrência do token no `audit_log` (história inteira) nem no Cloud Logging (30 dias), com controle positivo.
- **Soak Google:** 22 execuções (05/09 a 26/09), todas `success` e `complete`; a de 26/09 bateu a previsão exata — `removed=3`, `revoke_candidates=46`. As três contas que sumiram do MCC em 24/09 são **churn** (resposta do Wellington, 26/09).
- **Fase 2B:** o report antigo segue mais usado que o breakdown (148 contra 33 chamadas em 30 dias). Separar por gestor em 04/10.
- **Em produção, depois do F193:** o Google devolve linha **zerada** para período sem atividade, então o `sem_dados_no_periodo` quase nunca dispara no recurso `customer`; as razões `null` é que protegem a leitura.
- **Virada Google (26/09, 23:21 UTC):** a primeira execução com a trava bateu a previsão — `applied=true`, `removed=3`, `revoked_grants=46`, 12 linhas `google_access_cleanup`, zero grant vivo em conta inativa. O raio foi medido duas vezes no dia (18:13 e 23:14 UTC), igual nas duas.
- **Churn não é saída da plataforma:** a Alumínios Veneza também saiu (a quarta), e as contas **Meta** das quatro seguem alcançáveis pelo system user, com 4 grants cada. A reconciliação só revoga quando o alcance some.

## Como o F193 foi feito

[Spec](../superpowers/specs/2026-09-25-respostas-google-dizem-o-recorte-design.md) (25/09) →
[plano](../superpowers/plans/2026-09-26-respostas-google-dizem-o-recorte.md), cujo código **rodou
contra o repo antes do commit** (GAQL idêntico nas 16 funções; contagens 26/7/17/6 e 33 razões
bateram) → 7 tasks por subagente com revisão por task → revisão final da branch → full sweep 7/7 →
deploy → smoke de leitura em produção.

As decisões que mudaram o plano no caminho, todas registradas no F193:

- o guard de completude passou a conferir **nos dois sentidos e o valor**, depois que a revisão mostrou que ele ficava verde com chave sem corte;
- cláusula e eco de métrica saem de **uma fonte só** (`_clausula_e_eco_de_metrica`);
- `razao()` virou a regra única **com mecanismo**: `ad_schedule` e `apply_recommendation` migraram, e o detector AST pega as duas orientações e o ramo `None`;
- as duas frases de description são conferidas por testes que acham a população por varredura.

Defeitos do **plano** achados na execução: um teste que afirmava a regra que o spec revoga, e
seis consumidores do plugin em **prosa**, que o grep por nome de campo não via.

## O que ficou pendente

- **Conferir a execução de 28/09** da reconciliação Google: `removed=1`, `revoked_grants=4` (Alumínios Veneza, 3ª ausência).
- **Plugin `v4-trafego-google-ads`:** o texto do ajuste do `null` (6 pontos) foi entregue ao Wellington; aplicar na fonte.
- **Remover do BM as contas Meta das quatro clientes que saíram** — ação do Wellington, decidida em 26/09; detalhe no `estado-atual.md`.
- **04/10:** remedição dos buckets e uso da Fase 2B por gestor.
- **Próxima frente:** *métricas Meta* (spec) — zero no lugar de "não veio".
- **Follow-ups do F193** (Minor): no corpo do #111.

## Operacional que custou tempo

- O `gcloud` expira no meio da sessão: teste com `gcloud auth print-access-token` sob `timeout`, com o stderr visível.
- `pytest -q` duplica o `-q` do `addopts` e esconde a linha de resumo.
- Mensagem de commit escrita pelo PowerShell ganha **BOM**; escreva pelo Git Bash e confira `head -c 4 | od -c`.
- O `test_docs_links` lê planos como doc viva: `](` dentro de código e link relativo ao arquivo de destino quebram o gate.
- A reorganização de 26/09 tirou do `estado-atual.md` a narrativa fechada, movida literalmente para [`_archive/estado-atual-2026-09-20-a-26.md`](../_archive/estado-atual-2026-09-20-a-26.md).
- O freio do auto mode recusou a edição do `deploy.yml` depois de um "pode prosseguir" genérico, e a deixou passar de primeira depois de uma pergunta que nomeava cada passo (editar, mergear, rodar o job).
- Desde 26/09 os PRs abertos pelo Claude saem com **vigia de CI e auto-merge** (método `merge`); o `allow_auto_merge` do repo foi ligado nesse dia. O verde não acorda a sessão — o merge automático é que fecha o ciclo.
