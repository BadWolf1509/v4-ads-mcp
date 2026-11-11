# Sessão de 10 e 11/11 — Handoff (deps e varredura de refatoração de 10/11)

> Plano: [`2026-11-10-varredura-refatoracao.md`](../superpowers/plans/2026-11-10-varredura-refatoracao.md) —
> **Partes A a I em produção; J pulada (depende do F207); K1 decidido e entregue como C2 (#239).**
> Ledger da execução (git-ignored, mantido porque o plano não fechou):
> `D:/v4-ads-mcp/.superpowers/sdd/2026-11-10-varredura-refatoracao/progress.md`.
> Anterior: [`session-2026-11-04-handoff.md`](session-2026-11-04-handoff.md).

## O que entrou em produção

| PR | o quê | revisão |
|---|---|---|
| #227 | 5 bumps do Dependabot juntos | `00188-qbr` |
| #223 | sse-starlette 3.7.0 | `00189-c2x` |
| #228 | **A** — os 6 bugs (audit por dia BRT, toggles com `?desejado=`, bootstrap-admin, `reconcile_meta` sem configuração, corpo 200 não-objeto) | `00190-2zl` |
| #229 | **B** — guards de paridade, gêmeos e ratchets (só testes) | `00191-684` |
| #230 | **C** — Google de baixo risco | `00192-glq` |
| #231 | **D** — tools MCP | `00193-9rf` |
| #232 | **E** — Meta: URL base única; página lida uma vez; **moeda lida do inventário** depois do `can_manager_access`; contador BUC conta só o lido; sonda de alcance com aviso de versão; `classify` com motivo próprio para 3 operações | `00194-bw4` |
| #233 | **F** — fuso numa fonte (`APP_TIMEZONE` saiu do deploy); tipos do gate; `linhas_afetadas`; motivos de revogação em `motivos.py` | `00195-9c5` |
| #234 | **G** — **re-concessão grava `granted_at`/`granted_by`**; **revoke Meta grava `admin_revoked`**; núcleo das escritas de acesso; leituras das rotas nos repositórios; `_Filtros` do audit; **audit mostra o nome da conta Meta**; núcleo da regra de reconciliação | `00196-6q8` |
| #235 | **H** — codec único de token assinado; callback do OAuth em passos; `handle_callback_decision` síncrona | `00197-7j9` |
| #236 | **I** — `planejar_grade` pura; varredura do drift no `change_scan`; lookups GAQL no `preflight`; `dict_to_*` não inventam zero | `00198-t94` (pelo log; `gcloud` sem credencial) |

Cada deploy: `gh run view`, revisão servindo (`gcloud`), `/health?deep=1` e leitura real pelo MCP. A linha
`SERVING_REVISION` do log do deploy é a revisão de **antes**. Medido além disso:
- **G:** painel aberto só para leitura (Chrome "Browser 2", que tem a sessão; o "Browser 1" caiu no login e
  não se fez login): matrizes Google e Meta, as duas visões por gestor (24/24), convites, `/accounts`,
  dashboard e `/audit` com nome Meta (`[Cotia] MDO`), página 2 do `/admin/audit` pelo cursor.
- **H:** o cookie de painel emitido **antes** do deploy foi aceito pelo codec novo (compatibilidade byte a
  byte provada em produção); `/login` 200; `POST /mcp` sem token 401.
- **E:** as 24 contas Meta do Wellington têm `currency` preenchida (BRL).
- **I:** `detect_drift` (bloco `cobertura` com os tetos) e `audit_zombie_keywords` (206 linhas, adaptador
  estrito) responderam em produção.

## 11/11 à tarde — sequência pós-varredura

| PR | o quê | revisão |
|---|---|---|
| #237 | docs do fecho da varredura e levantamento K1 | — (só docs) |
| #238 | `ruff==0.17.4` e `mypy==2.4.1` fixados; passo 1 do gate (`check_ferramentas_fixadas.py`) recusa `.venv` defasada | `00199-phh` |
| #239 | **C2** — enum de recomendação v24→v25 junto com as entradas: os 2 tipos de lance do v25.2 sempre confirmam (fator, alvo atual e alvo novo derivado); `CAMPAIGN_SPECIFIC_APP_GOAL` só leitura (recusado na tool **e** no `pre_check` do `apply_change`; `so_leitura` no `get_recommendations`); guard de versão do SDK em `src/` | `00200-8dj` |
| #240 | follow-ups: `grant-all` só toca o que muda e exige `--by <admin ativo>` (autor no audit); `estimated_calls` removido; guard do reexport do `token_assinado`; guard do I4 ampliado | `00201-vwn` |

Medido além do gate e do CI:
- **gcloud** logado; `00198-t94` confirmada servindo antes da sequência.
- **Resync (parte H de 03/11):** 8 execuções de 04 a 11/11 com sucesso; o log de 11/11 mostra as três
  etapas (Google 24 contas, `complete: True`; Meta +2; purge de 5 linhas) e `exit(0)`.
- **C2:** `validate_gaql` (1171969590) aceitou a consulta de detalhe com os 28 campos, os 2 novos
  inclusos; o `InternalServerError` com resource name falso se repetiu no controle sem eles. Depois do
  deploy, `get_recommendations` na mesma conta devolveu 17 linhas com `so_leitura` — **nenhuma dos 3
  tipos novos**.
- Revisões finais (opus) com sabotagem nos dois PRs de código; o Important da C2 (token emitido antes
  do deploy aplicado pelo `apply_change`) foi reproduzido com teste vermelho antes do conserto.

Decisões e rulings desta tarde:
- **Decisões do Wellington (menu de 11/11):** merges #237–#240; descartar o CSS só de fim de linha do
  checkout; C2 = lance com confirmação + app só leitura; `grant-all` = só tocar o que muda, `--by`.
- **Ruling:** mypy fixado junto com o ruff (mesma deriva medida: 2.1.0 local × 2.4.1 no CI).
- **Ruling:** descrições de `apply_recommendation`/`get_recommendations` **não** mudaram (snapshot de
  schemas não se regera): seguem dizendo "SDK v24", "e mais 13" e não citam `so_leitura`. **Decisão
  sua** se quiser regerar.
- **Ruling:** promoção read→write no `grant-all` ganha autor novo (a decisão citava "nova ou
  revogada"). **Confirme.**
- **Ruling:** `d.get(k) or []` (coleção vazia) fica fora do guard do I4 — campo repetido do proto,
  ausente == vazio.
- **Achado de revisor descartado por medição:** "`client.py:39` fixa `version='v24'`" — falso; o
  client usa a versão padrão do SDK (v25).

Minors registrados (sem PR): âncora de ROAS sem arredondamento no preview; zero inventado quando o
Google omite a âncora `optional` (padrão herdado, família F145); guard de versão não pega
`importlib`; scanner do reexport não trata import relativo (mypy cobre); guard do I4 não pega
`IfExp`, `dict(P, **d)` nem `d |= {...}`.

## Método (o que funcionou)

Implementador e revisor por task (mínimo sonnet; opus em auth, acesso, reconciliação e revisões finais),
**caracterização gravada no código antigo antes de cada refactor** (o revisor a roda num worktree temporário
no commit antigo), revisão final da branch no opus com sabotagem própria, uma onda de correção, full sweep
antes do PR, merge com `--match-head-commit`, deploy verificado antes da parte seguinte.

## Decisões tomadas na execução (rulings, com o custo se erradas)

- **E3:** a premissa do plano "a conta já passou pelo gate" era falsa (o gate Meta roda dentro de
  `run_meta_graph_get`); ler a moeda da tabela antes vazaria a moeda de conta sem acesso. O helper chama
  `can_manager_access` antes — custo: uma consulta a mais por chamada.
- **E6:** a Meta não tem reserva de cota; `estimated_calls` ficou sem uso — remoção é follow-up.
- **E8:** `create_campaign` também caía no fallback "unknown operation"; entrou pela decisão 7 (só o texto).
- **F2:** o plano pedia `pool: asyncpg.Pool` (é `Any` para o mypy); ficou `PoolValidado`, como a spec §3.1.
- **F3:** helper estrito (`ValueError`) no lugar de um ramo que devolvia 0 e estava morto nos 6 sítios.
- **G1:** valeu a "Nota de 10/11" (descritor só com nomes), não o texto anterior do Step 3.
- **G3 → G5:** a unificação do JOIN do nome da conta foi feita na G5, que tinha de mexer nele.
- **H1:** as duas implementações de token só diferiam nas mensagens; o codec recebe `MensagensDeErro`.
- **H2:** aceito um delta: com o pool não inicializado, um state sem `manager_id` nem `mode` dá 400, não 500.
- **I1:** `metricas: list[dict]` (o `MetricCell` não carrega `campaign_id`).
- Ondas finais levaram também os achados de guard mais estreito que a invariante (E8, F4, G, H, I).

## Pendências que dependem do Wellington

- **Dry-run com o gestor presente:** tools de status e as 3 do `emitir_preview` (D3); as 5 de mutate da
  Parte I (`update_ad_schedule`, `update_ad_group_bid`, `update_keyword_bid`, `update_campaign_budget`,
  `apply_audience`); e o `apply_recommendation` com um dos 2 tipos de lance do v25 quando aparecer
  pendente (a C2 muda o preview deles).
- **Clique nos toggles de gestor** (A2) num gestor de teste; **login novo pelo Google** depois da Parte H.
- **Reemitir o `SMOKE_MCP_BEARER`** (expirado; o handshake autenticado do smoke não roda — F186).
- **Parte J e F207** numa sessão com ele, começando pelos logs de produção do resync.
- Filtro de conta do `/admin/audit` só lista contas Google.

## Achados para o catálogo — catalogados em 11/11 como F208–F211

F208 (Parte A), F209 (`grant-all` e tipo de app do v25), F210 (codec de token, em parte), F211
(ruff/mypy, `SERVING_REVISION`, guards estreitos, E3); F167 atualizado. A lista de origem fica abaixo.

- Os 6 bugs da Parte A; `SERVING_REVISION` é a revisão anterior.
- Guards nascidos mais estreitos que a invariante, todos fechados antes do merge: B1–B4, E8 (substring
  em vez de entrada explícita), F4 (não pegava o ciclo de volta), G (EXPLAIN aceitava Bitmap + Sort), I3
  (teste do orçamento só ficava vermelho por `TypeError` do `FakePool`).
- **E3:** premissa de gate errada no plano — leitura do inventário antes do gate vazaria dado.
- **F167** descreve o `granted_at` antigo (mudou na G0).
- **Auth, pré-existentes e só com a chave:** `iat` futuro aceito sem limite; corpo não-UTF-8 com HMAC válido
  levanta `UnicodeDecodeError` cru; `oauth_state`/`panel_session` expõem `assinar`/`verificar` (um import
  por eles contornaria o guard novo `test_token_assinado_privado`).
- ~~**Guard do I4** só pega `.get(k, default)`~~: ampliado no #240 (`or X`, `pop`, `setdefault`, mescla de defaults).

## Follow-ups menores (no ledger, com arquivo e linha)

~~`estimated_calls` morto~~ (#240); TOCTOU inverso do `exigir_brl` (sentinela "negado"); `granted_by` obrigatório;
`janela_para_dict` OK, mas `test_update_ad_schedule` não pina `resumo`/`shared_budgets`; testes de
`dict_to_*` que não asserem todos os campos; cenário de inventário vazio já pinado; minors de docstring.

## Não medido

- Dry-run de mutação e clique que escreve em produção (acima).
- Plano de execução real do `LEFT JOIN meta_ad_accounts` com o volume de produção.
- Tokens dos buckets de tools (sem remedição desde 05/10).
