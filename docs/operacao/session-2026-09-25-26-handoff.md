# Sessão 2026-09-25/26 — Handoff (medir, fechar o F193, virar a trava Google, métricas Meta)

> Dois dias, oito PRs mergeados (#108–#115; três deles com deploy), e a frente *métricas Meta*
> (F194) fechada no código na branch `spec/metricas-meta` (seção abaixo). Este é o **mapa**;
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
| [#115](https://github.com/BadWolf1509/v4-ads-mcp/pull/115) | pós-virada: a primeira execução com a trava bateu a previsão; o primeiro PR com vigia de CI e auto-merge (entrou sozinho) | docs |

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

## A frente métricas Meta — F194 (branch `spec/metricas-meta`)

[Spec](../superpowers/specs/2026-09-26-metricas-meta-dizem-o-que-mediram-design.md) (`79b82ce`) →
[plano](../superpowers/plans/2026-09-26-metricas-meta-dizem-o-que-mediram.md) (`0cd0ae4`) → execução
por subagentes: seis tasks (`b810621`, `86015c9`, `aa138c9`, `2d5eb73`, `67ca703`, `f16400f`),
uma rodada de correção da Task 5 (`910b8f8`) e uma da revisão final da branch. Todas revisadas;
o full sweep (Docker) passou nos 7 passos.

**O que falta:** o PR (vigia de CI + auto-merge; o merge deploya) e o smoke de leitura em
produção numa sessão MCP **nova** (F140) — o roteiro está no `estado-atual.md`, e a conta de
referência é a Cheiro | Conta 01 (`act_926193536103926`: `purchases` 10, onde hoje sai 0).

**O que as sondagens de 26/09 mediram** (Graph API, 24 contas, 30 dias,
`scripts/probe_meta_metricas.py`): a mesma compra sob 5 nomes e o mesmo lead sob 7; 14 de 14 contas
com gasto medem conversas iniciadas, que nenhuma tool expunha; `action_values` e `purchase_roas`
vazios em todas; `ctr` em escalas 100× diferentes entre o overview e o trio; o horário sem
`reach`/`frequency`; o BUC gravando "não sei" como 0. E duas afirmações falsas nas docs: o índice
da varredura dava o 03#10 como fechado pelo F190 (o overview seguia mandando o parâmetro), e a
contagem de cabeçalhos no topo do catálogo estava defasada em um. Na revisão final, as
combinações de parâmetros foram mandadas juntas à API, na forma exata do construtor
(`scripts/probe_meta_combinacoes.py`, 27/09): 16 de 16 com 200, e o controle inválido 400.

**Como o plano foi feito — e por que foi diferente do F193:** o código de cada task foi escrito e
executado num worktree antes do plano, uma task por commit, cada uma verde isolada; o plano foi
**gerado desses commits** (os blocos são os diffs exatos) e reaplicado bloco a bloco a partir do
próprio arquivo sobre o commit do spec — resultado idêntico. As seis tasks bateram byte a byte
com o plano, conferido por script a cada commit. As revisões por task acharam **um** Important,
e ele era do plano, não da execução: o grafo de import do guard das descriptions não via
`from pacote import módulo` (`910b8f8`). **O plano commitado difere do executado em dois
pontos**, decididos na execução: esse conserto do guard, e o par do `nucleo.md` que troca a
linha do BUC antigo pelo contrato novo (carregado pela Task 6). A revisão final achou dois
Important — estas docs se contradizendo, e as combinações de parâmetros nunca enviadas juntas
à API real (sondadas: passam) — e Minors que entraram no mesmo commit de correção.

## O que ficou pendente

- **Conferir a execução de 28/09** da reconciliação Google: `removed=1`, `revoked_grants=4` (Alumínios Veneza, 3ª ausência).
- **Plugin `v4-trafego-google-ads`:** o texto do ajuste do `null` (6 pontos) foi entregue ao Wellington; aplicar na fonte.
- **Remover do BM as contas Meta das quatro clientes que saíram** — ação do Wellington, decidida em 26/09; detalhe no `estado-atual.md`.
- **04/10:** remedição dos buckets e uso da Fase 2B por gestor.
- **Smoke de leitura do F194 em produção**, numa sessão MCP nova — roteiro no `estado-atual.md`.
- **Alerta para os WARNING do Meta** (`meta_rate_limit_warning`, `meta_buc_nao_lido`): a única
  política de alerta por log dispara em `severity>=ERROR`, então o aviso existe e ninguém é
  avisado. Métrica por log + política, como a do `google_accounts_sem_grant` (declarado no F194).
- **Nível de acesso da API Meta:** o cabeçalho de throttle diz `development_access` — o app segue no Limited Access do D1 de maio; decisão do Wellington (pedir o Full Access agora, ou esperar volume). Registrado no `estado-atual`.
- **Follow-ups do F193** (Minor): no corpo do #111.

## Operacional que custou tempo

- O `gcloud` expira no meio da sessão: teste com `gcloud auth print-access-token` sob `timeout`, com o stderr visível.
- `pytest -q` duplica o `-q` do `addopts` e esconde a linha de resumo.
- Mensagem de commit escrita pelo PowerShell ganha **BOM**; escreva pelo Git Bash e confira `head -c 4 | od -c`.
- O `test_docs_links` lê planos como doc viva: `](` dentro de código e link relativo ao arquivo de destino quebram o gate.
- A reorganização de 26/09 tirou do `estado-atual.md` a narrativa fechada, movida literalmente para [`_archive/estado-atual-2026-09-20-a-26.md`](../_archive/estado-atual-2026-09-20-a-26.md).
- O freio do auto mode recusou a edição do `deploy.yml` depois de um "pode prosseguir" genérico, e a deixou passar de primeira depois de uma pergunta que nomeava cada passo (editar, mergear, rodar o job).
- Desde 26/09 os PRs abertos pelo Claude saem com **vigia de CI e auto-merge** (método `merge`); o `allow_auto_merge` do repo foi ligado nesse dia. O verde não acorda a sessão — o merge automático é que fecha o ciclo.
- `git stash` é do **repositório**, não do worktree: um stash feito num worktree de rascunho aparece no repo principal. Para guardar o estado de um protótipo, copie os arquivos para fora do repo.
- Plano gerado de commits executados, com um conferidor (`confere_task.py` no workspace do plano) que compara cada commit de task com os blocos do plano: a checagem "o implementador transcreveu certo?" vira mecânica e sai da revisão.
- O implementador da Task 5 gravou a evidência das sabotagens na **raiz do repo** — confira `git status` depois de cada task; nada disso pode ir para um commit.
