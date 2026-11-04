# Correções da varredura de 2026-09-05 — design

**Data:** 2026-09-06
**Origem:** varredura de 8 revisores paralelos sobre todo o repositório
(`.superpowers/sweep-2026-09-05/`, ignorado pelo git). 86 achados brutos:
9 Críticos, 33 Importantes, 44 Menores.
**Decisões do Wellington (2026-09-06):** escopo = os 86; C2 = gate por tipo;
sequência de 7 PRs aprovada.

---

## 1. O que a varredura ensinou sobre a causa

Os achados **não são independentes**. Três famílias explicam a maioria, e cada
uma tem a mesma forma: *existe uma regra escrita, e não existe o mecanismo que
a aplica*.

**Família 1 — guards sem primitivo comum (17 instâncias, enumeradas em 3.1.1).** Cada guard
estrutural reimplementa a própria varredura: um faz substring no texto do
arquivo (F57, F58), outro lê linha a linha (nome acessível), outro usa `glob`
não-recursivo (F113, DSN, `test_tools_schemas`), outro compara nome de classe
em vez de subclasse (F91), outro afirma tautologia
(`test_change_freshness.py:235` — `f(x) == f(x)`), outro casa qualquer atributo
`.level` em vez de `risk.level`. Não há travessia compartilhada, então **cada
autor de guard reinventa o scanner e reinventa o bug junto**. Corrigir os 17
individualmente resolve o sintoma e garante o 18º.

**Família 2 — regra de governança sem ponto único de aplicação (C1, C2, F112
vivo).** A regra "orçamento sempre confirma" existe em `blast_radius.py:90`, e
há duas portas que a contornam: uma tool que não lê `explicitly_shared`
(`update_campaign_budget`) e uma que computa `classify()` e nunca lê `.level`
(`apply_recommendation`). A classificação é calculada e **descartada**.

**Família 3 — corte sem declaração de corte (R4-C2, R4-C3, R4-I1).** Onze tools
aplicam `LIMIT` e devolvem a página sem dizer que cortaram. Não existe primitivo
de "aplica limite e reporta truncamento", então cada tool decide sozinha — e a
maioria decide não dizer.

**Consequência para o desenho:** cada frente entrega a correção das instâncias
**e** o mecanismo que impede a recidiva. Pelo teste 1 de gambiarra do
`CLAUDE.md` (*"depende de alguém lembrar"*), corrigir só as instâncias seria
dívida com juros.

---

## 2. Escopo

**Entra:** os 86 achados, distribuídos nos 7 PRs da seção 4.

**Não entra**, e por quê:

- **F129** — governança do system user: exige ação humana no BM, não código.
- **A4** — override silencioso do Google em `user_list` de campanha:
  comportamento do lado deles, já mitigado por pré-flight.
- **F67** — custom domain: infra, sem relação com a varredura.
- **F154** — o sinal `su_reachable`: muda o contrato do painel e precisa de
  decisão própria, não de correção.
- **Instrumento de cobertura de teste.** O R7 registrou que o projeto não tem
  nenhum. Instalar um é decisão separada; esta rodada corrige guards que
  existem, não persegue percentual.

**Regra que atravessa todo o escopo:** *nenhum achado é corrigido sem antes ser
reproduzido.* Dos 86, 9 foram verificados por mim (5 por execução); os demais
vêm de relatório de agente — que esta mesma varredura provou falível: o R5
afirmou que a trava do soak não deixa escapar escrita, e a leitura do
`account_resync.py:91` mostrou que deixa. **Todo achado ganha um teste que falha
contra o código pré-fix antes de qualquer correção.** Achado que não se
reproduzir é registrado como refutado, com a prova, e não vira código.

---

## 3. Os dois primitivos

### 3.1 Harness de guards estruturais

**Problema:** 17 guards, 17 travessias artesanais, 17 oportunidades de errar o
escopo ou o casamento.

**Desenho.** Um módulo `tests/unit/_guard_harness.py`, dono das três coisas que
hoje cada guard refaz:

1. **Escopo de arquivos** — `fontes_py()`, `templates_html()`, `markdown()`,
   `workflows()`. Todos recursivos por padrão, com as exclusões declaradas num
   lugar só. Mata de uma vez a classe `glob` não-recursivo.
2. **Casamento por AST, nunca por texto** — `chamadas(arvore, nome)` resolvendo
   `Name`, `Attribute` **e alias de import**; `excecoes_capturadas(handler)`
   devolvendo as classes de verdade, para o guard perguntar `issubclass` em vez
   de comparar nome. Mata a classe "casa a própria docstring" (F58) e a classe
   "erra a subclasse" (F91).
3. **Afirmação da propriedade** — `exigir_vazio(ofensores, mensagem)`, com
   formato único `arquivo:linha`.

**O harness precisa dos próprios testes, e este requisito é o que o impede de
virar o defeito nº 18.** Para cada scanner, dois fixtures sintéticos: um que
**contém** a violação e um que não contém. O teste afirma que o scanner enxerga
o primeiro e não acusa o segundo. Sem isso o harness é só um lugar novo para o
mesmo erro morar.

**Migração:** o PR 0 instala o harness e converte os guards **preservando a
semântica atual** — nenhum guard fica mais estrito no PR 0, para que nada fique
vermelho e as outras frentes não travem. O aperto de cada guard viaja com a
frente que ele protege.

### 3.1.1 Os guards, um a um

Enumerados para o plano ter alvo. São **17** — eu disse 16 na conversa; a
enumeração achou mais um (`test_blast_radius_bate_com_as_tools.py:100`).

| # | guard | defeito | aperta em |
|---|---|---|---|
| 1 | `test_structural_guards.py:51` (F57) | substring no arquivo inteiro, não por função | PR 3 |
| 2 | `test_structural_guards.py:88` (F58) | por arquivo **e** casa `conn.transaction()` dentro de comentário | PR 0 |
| 3 | `test_structural_guards.py:111` (F92) | não enxerga mais `pending_invites_count`, a função que o motivou | PR 5 |
| 4 | `test_structural_guards.py:226` (F83) | só statement de topo; todo `finally` do projeto aninha o acquire num `if` | PR 2 |
| 5 | `test_structural_guards.py:254` (DSN) | `glob` não-recursivo em `tests/integration/` | PR 6 |
| 6 | `test_structural_guards.py:398` (F91) | igualdade de **nome**; erra toda subclasse e todo alias | PR 0 |
| 7 | `test_no_server_clock_in_google_tools.py` (F141) | não pega `utcnow()`, `time.time()` nem alias de import | PR 4 |
| 8 | `test_ci_local_parity.py:88` (F113) | `glob("*.md")` só na raiz; `docs/` inteiro fora, com violação viva | PR 6 |
| 9 | `test_ci_local_parity.py:56` | afirma que o **nome da ferramenta** aparece, não que os steps existem | PR 6 |
| 10 | `test_blast_radius_bate_com_as_tools.py:75` (F112) | casa **qualquer** atributo `.level`, não só `risk.level` | PR 3 |
| 11 | `test_blast_radius_bate_com_as_tools.py:100` | piso `>= 15` para uma derivação que deveria ser exata | PR 3 |
| 12 | `test_change_freshness.py:235` | tautologia: `f(x) == f(x)`, com docstring prometendo janelas **diferentes** | PR 6 |
| 13 | `test_tools_schemas.py:76,422` | `make_capture_client` varrido só em `test_*_builder.py` | PR 6 |
| 14 | `test_frontend_a11y_guards.py:83,148` | só `.html`; o fragmento montado em `routes.py` escapa | PR 5 |
| 15 | `test_todo_controle_de_formulario_tem_nome_acessivel` | linha a linha; `<input>` multi-linha invisível | PR 5 |
| 16 | `test_todo_th_declara_scope` | mesma técnica linha a linha do #15 | PR 5 |
| 17 | `test_frontend_responsive_guards.py:181-190` | lista fixa de 5 templates onde os vizinhos derivam do source | PR 5 |

Cinco deles (1, 3, 4, 14, 2) foram provados por **sabotagem executada** contra
baseline verde, em cópia fora do repositório; o 6 e o 8, por mim. Os demais vêm
de leitura e entram no plano com a exigência do critério 2 da seção 6 — provar
antes de corrigir.

### 3.2 Declaração de truncamento

**Problema:** onze tools aplicam limite e não dizem que cortaram.

**Desenho.** Em `src/mcp/tools/_common.py`:

```python
def aplicar_limite(linhas: list[T], limite: int) -> tuple[list[T], bool]:
    """Devolve (linhas cortadas, truncated). Único lugar que decide o corte."""
```

Toda tool com `limit` no schema passa a devolver `truncated: bool`. Um guard
construído sobre 3.1 afirma a propriedade: *toda tool cujo `input_schema`
declara `limit` devolve `truncated` em algum caminho de retorno*.

**Nota de contrato:** acrescentar campo à resposta é aditivo e não quebra
cliente MCP, nem exige sessão nova — pelo F140, campo novo de tool existente
passa; tool nova é que exige.

---

## 4. As sete frentes

Cada frente é um PR: CI próprio, merge próprio, revisão própria. Cada uma
carrega **a reescrita do guard que a protege** e as violações vivas que essa
reescrita revelar — guard apertado e violação exposta são a mesma unidade de
trabalho.

### PR 0 — Harness de guards

Instala 3.1 e converte os 17 guards preservando semântica. Zero mudança de
comportamento de produção.

**Pronto quando:** suíte verde e os testes do próprio harness passam contra os
fixtures sintéticos.

### PR 1 — C3: audiência de token

**Mecanismo:** claim de audiência — o padrão que este repo já aplica em
`meta_oauth.py:190` e verifica em `:247`.

- `sign_state(payload, key, *, aud: str)` — `aud` vira keyword **obrigatória**.
- `verify_state(state, key, *, aud: str)` — obrigatória, comparada antes de
  devolver o payload.
- `sign_panel_session` / `verify_panel_session` — mesmo tratamento, `aud="panel"`.
- Audiências: `"google_oauth"`, `"cli_invite"`, `"meta_oauth"`, `"panel"`.

**Consequência operacional aceita explicitamente:** todo cookie de painel
emitido antes deste PR deixa de valer — os gestores logados caem para a tela de
login e refazem OAuth. Com 4 pessoas na unidade o custo é de minutos, e a
alternativa (janela de dupla aceitação) mantém o furo aberto durante a
transição. **Escolha: quebrar as sessões vivas.** Fluxos de OAuth em voo também
quebram, dentro da janela de 10 minutos do state.

**Testes que precisam existir e falhar ANTES do fix:** um que prove a confusão
hoje (state de convite aceito por `verify_panel_session`) e um que prove a
inversão de TTL (token de 1 h recusado por `verify_state` e aceito por
`verify_panel_session`).

**Também nesta frente:** `panel_session.py:85` passa a recusar payload sem
`manager_id`, em vez de devolver `""`; a docstring de `oauth_state.py:10-11`
passa a dizer que o TTL **limita** replay, não o elimina.

### PR 2 — C4: reconciliação idempotente

Toca o laço Meta que **revoga em produção hoje**. Prioridade máxima depois do
PR 1.

**Mecanismo:** tornar a operação idempotente — não desligar o retry. Retry é
útil; operação não-idempotente é que é o defeito. (Descartada a alternativa
`--max-retries=1`: transforma falha transitória em dia sem sincronismo e deixa o
defeito de pé para qualquer outra reexecução, inclusive a manual do runbook.)

- Migration aditiva: `last_missed_on DATE` em `google_ads_accounts` e
  `meta_ad_accounts`.
- `apply_absences` incrementa **apenas** quando `last_missed_on IS DISTINCT FROM
  <hoje_da_conta>`, gravando a data no mesmo `UPDATE`. Duas execuções no mesmo
  dia contam uma ausência.
- `hoje_da_conta` vem de `resolve_account_today`, não do relógio do servidor
  (F141).
- `record_job_run` (`account_resync.py:252`) ganha `best_effort` (F83).
- `meta_resync.run()` ganha `configure_logging()`, que só o lado Google recebeu.
- `apply_absences.reset` é redundante com o que `upsert_many` já zera — remover,
  com teste que prove a equivalência.

**Antes de escrever código nesta frente:** medir quantas contas têm
`missed_syncs` inflado por contagem dupla, nos dois lados, e registrar o número.
Se houver conta em ou acima do limiar por duplicata, o dado é corrigido na mesma
migration.

### PR 3 — C1 + C2: governança de orçamento

**C1 — `update_campaign_budget` passa a enxergar orçamento compartilhado.**
Espelha o que `update_ad_schedule.py:498-525` já faz: lê
`campaign_budget.explicitly_shared` e, quando `true`, inclui no preview a lista
das campanhas irmãs com o aviso de que a mudança atinge todas. **Não recusa,
avisa** — mesma decisão já tomada para o `update_ad_schedule`, e consistência
entre as duas vale mais que uma regra nova.

**C2 — gate por tipo em `apply_recommendation`:**

- A tool lê `recommendation.type` por GAQL antes de decidir.
- `_TIPOS_QUE_CONFIRMAM` = os que mexem em orçamento ou bidding. **A lista sai
  de probe empírica contra a API, nunca por analogia** — é a regra do
  `CLAUDE.md` para whitelist de enum, e o custo de errar aqui é uma porta
  aberta.
- Tipo na lista → preview + token, com o valor novo visível. Fora da lista →
  AUTO como hoje.
- `blast_radius.classify` recebe o tipo e devolve o nível; **a tool lê
  `.level`** em vez de descartá-lo.

**Guards que viajam junto:** o do F57 passa a ser **por função** (hoje é
substring no arquivo, `test_structural_guards.py:51`); o do F112 deixa de aceitar
qualquer atributo `.level` (`test_blast_radius_bate_com_as_tools.py:75`); o piso
`>= 15` vira derivação exata; a contagem "17 das 26" no `CLAUDE.md` e no
catálogo é corrigida para a medida real.

**Risco declarado:** a reescrita do guard do F57 pode revelar executor sem gate
que hoje ninguém vê. Se revelar, é Crítico e entra neste PR.

**Também nesta frente**, por serem os mesmos arquivos e a mesma família:
`apply_change` devolvendo `partial_failures` (R1-I1); audit gravando o
**aplicado** e não o tentado (R1-I2); Customer Match reportando o parcial de
verdade e com `provider_request_id` real (R1-I3, R1-I4); `remove_audience` sem
código morto (R1-I5); `import_offline_conversions` com o mesmo `utc_offset` no
preview e no upload (R1-I6); `level="write"` asserido por teste (R7-I3); as 5
tools que montam envelope à mão passando a usar `applied_envelope`; literais de
TTL fora das descrições.

### PR 4 — C5 + honestidade dos números

- **C5:** `top_keywords_query` / `top_creatives_query` passam a receber a
  métrica e emitir o `ORDER BY` correspondente. O corte volta a ser feito **uma
  vez, no servidor, pela coluna certa**, e o re-sort client-side desaparece. A
  docstring de `client_report.py:23`, que hoje promete *"caller decides via
  ORDER BY"*, passa a ser verdade.
- **Truncamento (3.2)** aplicado às 11 tools: `get_performance_breakdown`,
  `get_change_history`, `detect_drift`, `get_search_terms_report`,
  `get_my_audit_log` e as 6 legadas.
- `detect_drift` **pagina** em vez de esconder o teto interno de 500 eventos, e
  declara `truncated` se o teto paginado também for atingido. Declarar sem
  paginar seria o mínimo honesto, mas esta é a tool cujo trabalho inteiro é
  responder *"mudou algo que não devia?"* — perder evento em silêncio derrota o
  propósito, não só a precisão.
- `get_performance_breakdown` herda o aviso do F56 (keywords negativas
  misturadas) que `get_keyword_performance` já carrega.
- `get_ad_schedule.schedule_summary.has_schedule` deixa de dizer `false` quando
  a causa foi truncamento e não ausência de grade.
- Os 4 helpers de `_common.py` que montam `IN (...)` passam por `int()` ou
  `gaql_string_literal`, sem depender do `pattern` do schema a montante (F87).
- `audit_quality_score.py:43` (interpolação) e `audit_zombie_keywords.py:78`
  (`int()` truncando `conversions`).
- **Guard que viaja junto:** o do F141 passa a pegar `utcnow()`, `time.time()` e
  alias de import.

### PR 5 — Painel

O maior diff, isolado por isso.

- **Split do `routes.py`** (1839 linhas) em 10 módulos por responsabilidade:
  `sessions`, `accounts`, `audit`, `admin_overview`, `admin_accounts`,
  `admin_access`, `admin_invites`, `admin_audit`, `oauth_panel`, `_shared`.
  Split é **movimentação sem mudança de comportamento**; qualquer correção de
  lógica vai em commit separado dentro do mesmo PR, para o diff do split
  permanecer legível.
- As ~35 queries do corpo das rotas passam a usar `run_with_reconnect`
  (F76/F91), como o gate de auth já faz.
- Isenção de CSRF passa a ser **por rota**, não por prefixo — F106 aplicado ao
  mecanismo, não só à lista.
- `POST /oauth/meta/refresh-accounts` ganha `_require_admin` (R2-I3).
- Mudança de acesso/role e sua linha de auditoria passam a compartilhar
  transação nas 12 rotas admin (R3-I3).
- Guards de a11y/CSP passam a varrer o fragmento montado em Python, não só
  `.html` (R7-I4); o de nome acessível deixa de ser linha-a-linha (R6-I3); o de
  `th scope` e o de quebra de e-mail deixam de usar lista fixa.
- Menores do R6: mini-tabelas do `admin/index.html`, `tojson` no `audit.html`.

### PR 6 — Cauda

- **Gêmeo Meta do F141** (4 sítios) usando `meta_ad_accounts.timezone_name`, que
  já está no banco e não é lido. Abrir o finding que o guard prometeu
  (`test_no_server_clock_in_google_tools.py:16-17`) e nunca foi escrito.
- Rate-limit do Graph (17, 613, 80004) reconhecido por `to_friendly_meta_error`,
  com `retryable=True` e mensagem em PT-BR.
- `bulk_grant` deixa de ignorar `access_level` no `ON CONFLICT` (R2-I2).
- Guard do F113 varre `docs/` recursivo, e a violação viva em
  `session-2026-08-19-infra-ci-handoff.md:28` é resolvida.
- `test_ci_local_parity.py:56` passa a afirmar que os **steps** existem, não que
  o nome da ferramenta aparece.
- `test_change_freshness.py:235` deixa de ser tautologia.
- `test_tools_schemas.py` deixa de varrer só `test_*_builder.py`.
- **Dependabot passa a ignorar bump major em `mcp`**, como já faz para
  `google-ads` e `facebook-business`. O `ignore_errors` de `mcp.*` no mypy
  **fica onde está nesta rodada** e vira finding próprio: removê-lo pode
  cascatear em erro de tipo por todo o servidor, e isso é trabalho de escopo
  desconhecido dentro de um PR de cauda. Os dois juntos é que deixavam o SDK de
  transporte sem freio; fechar o freio de processo já tira o pior.
- Índices ausentes: `audit_log(occurred_at)` e
  `manager_account_access(customer_id)`.
- `ORDER BY occurred_at DESC` ganha desempate estável, e a paginação do audit
  troca OFFSET por keyset (R3-I6).
- Migrations `002` e `004` idempotentes.
- Diretório `D:v4-ads-mcp.superpowerssdd/` removido e `.gitignore` fechado.
- Menores restantes de R1, R2, R3, R8.

---

## 5. Riscos

**O escopo pode crescer sozinho, em dois pontos.** Apertar o guard do F57
(PR 3) e o do F83 (PR 0 → 3) pode revelar violações vivas que hoje ninguém vê.
Não dá para saber o que vai aparecer — é a natureza de um guard que nunca
olhou. Se aparecer Crítico, entra no PR da frente correspondente e o PR cresce.

**O PR 1 desloga todo mundo.** Aceito e declarado na seção 4.

**O PR 2 mexe em produção viva.** O laço Meta revoga hoje. A migration é
aditiva, mas a mudança de semântica do contador exige medir o estado atual
**antes** de aplicar.

**O PR 5 é grande demais para revisão de uma passada.** Mitigado pela separação
entre o commit de movimentação e os de lógica.

---

## 6. Critérios de aceitação

1. `python scripts/check_pre_push.py` verde em cada PR, e o full sweep com
   Docker nos PRs que tocam queries, mutate, `_common` ou migrations.
2. **Todo achado corrigido tem um teste que falha contra o código pré-fix**,
   verificado por sabotagem ou por cópia — nunca por `git checkout`.
3. Nenhum guard novo ou reescrito passa sem que se nomeie a mudança concreta de
   produção que o deixaria vermelho.
4. Achado que não se reproduzir é registrado como **refutado, com a prova**, e
   não vira código.
5. Ao fim, os 86 têm destino explícito: corrigido, refutado, ou fora de escopo
   com motivo.
6. `findings-catalog.md` e `estado-atual.md` atualizados no fecho de cada PR.
