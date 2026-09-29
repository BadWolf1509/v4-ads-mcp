# Infra e guards — conexão validada na retirada, SQL idempotente, migrations serializadas

**Data:** 2026-09-28 · **Origem:** o resto dos sub-projetos 3 e 4 da varredura de 21/09
([`_archive/varredura-2026-09-21/`](../../_archive/varredura-2026-09-21/README.md), relatórios `04` e
`05`) · **Decisões:** Wellington, 28/09. Ele escolheu uma spec em 3 partes em vez de só a parte 1 ou
de uma triagem que cortasse o inalcançável, e escolheu validar a conexão na retirada em vez de dar
retry só às leituras.

## 1. O problema

Os achados de 21/09 foram **conferidos no código de 28/09**, linha a linha, por um agente só de
leitura. Todos seguem presentes, e nenhum finding de F190 a F198 os toca. Os status do relatório
original eram do agente que o escreveu; os abaixo foram medidos.

| # | achado | onde (28/09) | impacto |
|---|---|---|---|
| 05#2 | 9 leituras no caminho quente sem o retry de reconexão (F76/F77) | `src/auth/oauth.py:184` e `:286` (login e convite pela CLI); `list_my_accounts.py:39`, `get_my_audit_log.py:80`, `get_my_rate_limit_status.py:60`, `meta_list_my_ad_accounts.py:38`, `meta_get_account_overview.py:120`, `meta_get_performance_breakdown.py:131`, `_meta_performance.py:114` | o 500 do "primeiro acesso da manhã" que o `deps.py` descreve, no login e em 7 tools |
| 04 / sub-projeto 4 | o guard de reconexão enumera 6 funções pelo nome (`test_hot_reads_reconnect.py`); o estrutural (`test_rotas_usam_run_with_reconnect.py`) só varre `src/web/routes/` | — | é por isso que os 9 pontos passaram; o F191 o listou como "resto da Classe B" |
| 05#3 | `migrate.py` sem lock | `src/db/migrate.py:29-53`; nenhum `pg_advisory` em `src/` | o `deploy-prod` já serializa os deploys do CI; sobra o `gcloud run jobs execute` manual, e o perdedor aborta na PK de `_migrations` |
| 05#4b | export CSV do audit sem teto de linhas | `audit_log.py:126-163` (`export_csv_rows`, cursor sem `LIMIT`) | segura 1 das 5 conexões do pool durante o download |
| 05#5a | `revoke` Meta manual sem `AND revoked_at IS NULL` | `manager_meta_account_access.py:108-117` (o `revoke_for_account` e o `revoke` Google têm) | latente: o `restore_for_account` filtra por `revoked_reason`, e re-revogar com outro motivo deixaria a linha irrestaurável sem ninguém ver |
| 05#5c | `revoke` das conexões OAuth sem o mesmo predicado | `google_oauth_connections.py:79-83`, `meta_oauth_connections.py:94-98` | cosmético (timestamp movido) |
| 05#6 | `ORDER BY connected_at DESC LIMIT 1` sem desempate | `google_oauth_connections.py:63-76`, `meta_oauth_connections.py:78-91`, e `src/jobs/account_resync.py:58` (achado nesta spec) | duas conexões vivas com o mesmo `connected_at` escolhem a credencial de forma arbitrária |
| 05#7 | `limit=0` estoura `page[-1]` nos pagers keyset | `audit_log.py:403-404`, `:498-499` | inalcançável hoje (as rotas fixam 50); mina em função pública |
| 05#8a | expiração do token de dry-run conferida com o relógio da app | `dry_run.py:154`, e o prazo é gravado com o `now()` do banco (`:96`) | dois relógios; a diferença entre eles desloca o TTL |
| 05#8b | contador Meta com `date.today()` sem fuso | `rate_limit.py:269`; o Google usa `_today()` (UTC) | só dá certo porque o container roda em UTC |
| 05#8c | `record_actual` faz `UPDATE` no dia de HOJE | `rate_limit.py:114-135` | acerto que atravessa a meia-noite UTC cai num dia sem linha e é descartado sem erro |
| 05#8d | `increment_calls` e `update_throttle` sem transação | `rate_limit.py:262-290` | falha entre os dois deixa o contador pela metade |

**Medido em 28/09 para decidir o desenho** (só leitura, transação READ ONLY):

- **O DSN aponta para o Supavisor na porta 5432, que é o modo sessão** (`application_name` =
  `Supavisor`). O advisory lock de sessão funcionaria hoje, mas nada no repo fixa o modo.
- **`audit_log`:** 5.795 linhas em 365 dias (desde 04/05), 3,2 MB, e o maior gestor tem 3.117.
- **asyncpg 0.31.0:** o `setup` de `create_pool` roda a cada `acquire`. Se ele levanta, o
  holder fecha a conexão, volta à fila e repassa o erro; a próxima retirada reconecta
  (`PoolConnectionHolder.acquire`, lido na fonte instalada).
- **Como `src/` e os testes chegam ao pool:** `src/` usa `connection.get_pool()` (77 ocorrências;
  104 `acquire()`), e os testes trocam `connection.get_pool` no próprio módulo (22 fakes de
  `acquire`). Uma mudança **dentro** de `get_pool()` alcança todos os pontos sem tocar em nenhum.

## 2. Decisões

1. **Escopo:** as três partes numa spec, e um plano.
2. **Conexão: validar na retirada**, o padrão de validação ao emprestar (o `pool_pre_ping` do
   SQLAlchemy e a validação do HikariCP). O F76 recusou o SQLAlchemy por ser ORM, não o padrão.
   O retry só nas leituras foi recusado: custo zero por request, mas deixa a primeira escrita da
   manhã sujeita a 500 (o retry de escrita é proibido pelo F91), e o guard herdaria os falsos
   negativos catalogados da heurística leitura/escrita.

## 3. Desenho

### 3.1 Parte 1 — a conexão é validada na retirada

- `init_pool` passa `setup=_testa_conexao` ao `asyncpg.create_pool`, e o `_testa_conexao` roda
  `SELECT 1`.
- `get_pool()` devolve o pool asyncpg dentro de um invólucro, `PoolValidado`:
  - o `acquire()` dele devolve um gerenciador de contexto que retira a conexão e, se a retirada
    levantar um dos `_DROPPED_CONNECTION_ERRORS` (o `SELECT 1` do `setup` falhou), retira **uma**
    vez de novo, com o log `db_conexao_testada_reconectou`;
  - nada além do `acquire()` é exposto, de propósito: um atalho do asyncpg (`pool.fetch`,
    `pool.execute`) retiraria a conexão por dentro, sem a repetição. Nenhum ponto de `src/`
    usa outro método do pool (conferido em 28/09). O ciclo de vida é do `close_pool()`, e o
    `init_pool` não devolve o pool cru (revisão final da branch): `get_pool()` é a única porta.
- **Por que repetir é seguro para escrita:** a repetição acontece antes de o chamador receber a
  conexão. Nenhum comando do chamador rodou, então nada é repetido.
- O `run_with_reconnect` fica como está: é a segunda rede das leituras, para a conexão que morre
  entre o teste e a query. Os 9 pontos do 05#2 passam a ser cobertos pelo pool, sem serem
  embrulhados um a um.
- Os jobs e o `migrate` chamam o mesmo `init_pool` e ganham a mesma validação.
- **Custo:** uma ida e volta ao banco por retirada. O Cloud Run e o Supabase estão ambos em São
  Paulo; o custo real é medido depois do deploy (§6).

### 3.2 Parte 2 — SQL idempotente e determinístico

1. **Revogar é idempotente** (update condicional). Os três `revoke` ganham `AND revoked_at IS NULL`.
2. **Escolher uma linha é determinístico.** `ORDER BY connected_at DESC, id DESC` nos dois
   `get_active_for_manager` e em `account_resync.py:58`.
3. **Pagers keyset:** `limit < 1` levanta `ValueError` na entrada de `list_page_for_manager` e
   `list_page_admin`.
4. **Contador de quota: reserva e acerto no mesmo balde.**
   - `before_call` devolve o dia em que reservou, e `record_actual` recebe esse dia e acerta a linha
     dele, que existe por construção.
   - O upsert foi descartado: ele jogaria o acerto de ontem no balde de hoje.
   - O lado Meta passa a usar o mesmo `_today()` UTC do Google.
   - `increment_calls` e `update_throttle` rodam numa transação.
5. **Expiração do token de dry-run no relógio do banco.** O `SELECT … FOR UPDATE` do `consume`
   passa a trazer `expires_at < now() AS expirado`, e a checagem usa esse campo. Fica um relógio só,
   o mesmo que gravou o prazo.

### 3.3 Parte 3 — operação

1. **Migrations serializadas por `pg_advisory_xact_lock`**, o padrão de serializar migration por
   advisory lock do Flyway e do golang-migrate.
   - A variante é a de transação, e não a de sessão, porque funciona nos dois modos do pooler; a
     de sessão quebraria em silêncio se o DSN fosse para a porta 6543.
   - Cada migration roda assim:
     1. abre a transação;
     2. toma o lock (chave constante);
     3. **confere de novo** se aquela migration já está em `_migrations`, e pula se estiver;
     4. aplica e registra;
     5. faz commit.
   - O bootstrap da `_migrations` também roda sob o lock, porque dois
     `CREATE TABLE IF NOT EXISTS` concorrentes também colidem.
2. **Teto de linhas no export CSV.**
   - `export_csv_rows` pede `LIMIT 50001`, com a linha sentinela (F98).
   - Passando de 50.000 linhas, o arquivo termina com uma linha de aviso visível ("exportação
     cortada em 50.000 linhas — reduza o período"), e o log registra `audit_export_cortado`.
   - Com o volume medido, isso não muda nada hoje.

## 4. Testes e guards

Cada guard é visto falhar contra o código de 28/09, por sabotagem ou cópia, nunca `git checkout`.

| parte | guard |
|---|---|
| 1 | unit: `PoolValidado` com um pool falso cuja 1ª retirada levanta `ConnectionDoesNotExistError` — a 2ª passa e a operação roda **uma** vez; erro que não é de conexão derrubada não é repetido; duas falhas seguidas repassam o erro |
| 1 | unit: `init_pool` passa `setup` ao `create_pool` e `get_pool()` devolve o invólucro |
| 1 | estrutural: nenhum `asyncpg.create_pool(`/`asyncpg.connect(` em `src/` fora de `connection.py` |
| 2 | derivado do SQL: todo literal SQL em `src/` que **revoga** (`UPDATE … SET revoked_at = now()`) tem `revoked_at IS NULL` no `WHERE`. O `restore`, que grava `revoked_at = NULL`, fica fora por definição. Sabotagem: tirar o predicado do `revoke` Google |
| 2 | derivado do SQL: todo `ORDER BY … LIMIT 1` em `src/` **sobre tabela do nosso banco** (criada numa migration — é o que separa o SQL da GAQL, cujo `LIMIT 1` em `change_event` lê um valor, não escolhe linha) tem `id` como última chave de ordenação. Exceção só por lista no próprio guard, com a coluna e a constraint `UNIQUE` que a garante. Sabotagem: tirar o `id DESC` de um dos três |
| 2 | unit: `limit=0` levanta `ValueError` nos dois pagers |
| 2 | integração: acerto de quota com o dia virando entre `before_call` e `record_actual` acerta a linha da reserva |
| 2 | integração: falha no `update_throttle` desfaz o `increment_calls` |
| 2 | integração: token com `expires_at` no passado **do banco**, com o relógio da app congelado antes dele, é recusado como vencido |
| 3 | integração: dois `run_all` concorrentes aplicam cada migration uma vez e terminam sem erro (contra o código de hoje, o perdedor aborta na PK) |
| 3 | unit: com o teto injetado pequeno, o CSV termina na linha de aviso |

Mexe em SQL, transação e migrations: o **full sweep** (`check_pre_push_full.py`) é obrigatório em
toda task.

## 5. Fora do escopo

- **Freshness das métricas** (01#12 da varredura): é desenho próprio, e o relatório de 21/09 traz
  o probe que decide.
- **A segunda paginação Meta** (débito declarado no F190).
- **Trocar o `run_with_reconnect` pelo pool validado:** ele segue como segunda rede. Removê-lo
  seria uma decisão à parte, depois de medir o pool validado em produção.
- **O `SELECT … FOR UPDATE` que o guard estrutural de rotas não vê** (falso negativo catalogado
  em `test_rotas_usam_run_with_reconnect.py`): com o pool validado, deixa de importar para
  conexão derrubada.

## 6. Verificação em produção

Tudo por leitura:

- **latência do `/mcp`** (Cloud Run, p50 e p95): as 24 h antes e as 24 h depois do deploy, para medir
  o custo real do `SELECT 1`;
- **log:** contagem de `db_conexao_testada_reconectou` e de `db_dropped_connection_retry`, e nenhum
  500 de conexão no primeiro acesso da manhã seguinte. Leitura: o `db_dropped_connection_retry`
  conta a conexão que morreu entre o teste e a query **e** a retirada que falhou duas vezes dentro
  de um `run_with_reconnect` — não é só o primeiro caso;
- **deploy:** o job de migration termina limpo com o lock;
- **smoke de leitura:** `list_my_accounts`, `get_my_rate_limit_status` e uma tool Meta.
