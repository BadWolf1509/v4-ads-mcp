# PR 2 — Reconciliação idempotente (C4)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fazer o contador de ausências do laço de reconciliação contar **uma ausência por dia**, e não uma por execução — para que um retry do job pare de consumir a carência que protege contas de clientes.

**Architecture:** O incremento vira condicional a uma data nova (`last_missed_on`), gravada no mesmo `UPDATE`. A data é o dia **no fuso da conta**, calculado sem I/O extra: o inventário passa a carregar o fuso que já está no banco, e `account_today` é função pura. `record_job_run` ganha `best_effort`, que é o que hoje transforma bookkeeping pós-commit em task fracassada.

**Tech Stack:** Python 3.13, asyncpg com SQL cru, Postgres. Migration aditiva. Sem dependência nova.

**Spec:** [`docs/superpowers/specs/2026-09-06-correcoes-varredura-design.md`](../specs/2026-09-06-correcoes-varredura-design.md) — PR 2 da seção 4.

## Global Constraints

- **Este PR toca produção viva.** O laço Meta revoga acesso desde 05/09; o Google está em soak com `GOOGLE_RECONCILE_APPLY=false`. Uma migration ou uma mudança de semântica errada aqui **retira acesso de gestor a conta de cliente**.
- **A migration é aditiva e idempotente.** Coluna nova com default, sem `NOT NULL` sem default, sem backfill que trave tabela. Ela roda num Cloud Run Job **antes** do deploy; se falhar no meio, o serviço antigo continua servindo — então cada statement tem que poder ser reexecutado.
- **Nenhuma mudança de comportamento além da idempotência.** O limiar continua 3; o breaker continua all-or-nothing; a trava `GOOGLE_RECONCILE_APPLY` continua governando só a parte destrutiva.
- **Simetria Google/Meta é requisito, não estética.** Os dois laços são gêmeos por desenho, e toda divergência entre eles neste projeto já virou finding (o F128 nasceu de uma cláusula que ficou de fora de um dos lados).
- **Full sweep obrigatório** (`check_pre_push_full.py`, Docker): tudo aqui é repositório e job, e o gate local não roda os testes com banco.
- PT-BR em docstring e mensagem; `mypy --strict` e `ruff` limpos.

---

## Decisão de desenho que diverge da spec, e por quê

A spec diz que o dia vem de `resolve_account_today(customer_id)`. **Não vou usar essa função aqui**, e uso `account_today` — a função pura que ela envolve.

Motivo: `resolve_account_today` (`src/google_ads/account_clock.py:27`) faz
`connection.run_with_reconnect(...)` para ler o fuso, isto é, **adquire uma
conexão do pool**. Chamá-la por conta dentro de `reconcile_google` significaria
pedir uma segunda conexão enquanto a transação da reconciliação já segura uma —
com pool de tamanho 5 e N contas, é contenção auto-infligida no caminho que menos
pode falhar.

O dado já está à mão: `list_inventory_rows` lê a tabela onde `time_zone` mora. Ele
passa a trazer o fuso junto, e `account_today(tz, now=...)` decide o dia sem I/O
nenhum. **Mesma semântica da spec, zero round-trip novo.**

---

## Estrutura de arquivos

| arquivo | mudança |
|---|---|
| `src/db/migrations/009_last_missed_on.sql` (criar) | coluna nos dois lados |
| `src/db/repositories/google_ads_accounts.py` | `InventoryRow` carrega fuso; `apply_absences` idempotente por dia |
| `src/db/repositories/meta_ad_accounts.py` | o gêmeo |
| `src/jobs/account_resync.py` | passa o `now`; `record_job_run` em `best_effort` |
| `src/jobs/meta_resync.py` | idem, mais `configure_logging()` |
| `tests/integration/test_google_reconcile_repo.py` | testes de idempotência |
| `tests/integration/test_meta_reconcile_repo.py` | idem |

---

### Task 1: Migration 009 — a coluna nos dois lados

**Files:**
- Create: `src/db/migrations/009_last_missed_on.sql`
- Test: `tests/integration/test_migrations.py` (se existir guard de migration, estenda-o)

**Interfaces:**
- Produces: coluna `last_missed_on DATE` em `google_ads_accounts` e em `meta_ad_accounts`, nullable, sem default.

**Por que nullable e sem default:** `NULL` significa "nunca teve ausência contada", que é exatamente o estado de toda linha hoje. Um default de data faria toda conta parecer já contada hoje, e a primeira execução depois do deploy **não contaria a ausência real**. Nulo é o único valor que preserva a semântica atual.

- [ ] **Step 1: Escrever a migration**

```sql
-- 009: `missed_syncs` contava uma ausência por EXECUÇÃO, não por dia.
-- Com `maxRetries: 3` no job de resync, um retry após o commit da reconciliação
-- contava a mesma ausência de novo, consumindo em 2 execuções a carência de 3
-- dias que protege a conta do cliente. `last_missed_on` torna o incremento
-- idempotente por dia.
--
-- NULL = nunca teve ausência contada. É o estado de toda linha hoje, e é o
-- único default que não faz a primeira execução pós-deploy pular a ausência
-- real do dia.
ALTER TABLE google_ads_accounts ADD COLUMN IF NOT EXISTS last_missed_on DATE;
ALTER TABLE meta_ad_accounts    ADD COLUMN IF NOT EXISTS last_missed_on DATE;
```

- [ ] **Step 2: Conferir que é reexecutável**

Rode a migration duas vezes seguidas contra um banco de teste e confirme que a
segunda é no-op sem erro. `ADD COLUMN IF NOT EXISTS` dá isso; o teste é para
provar, não para supor.

- [ ] **Step 3: Rodar o full sweep**

Run: `python scripts/check_pre_push_full.py` — leia `$?` do próprio processo, nunca de um pipe.

- [ ] **Step 4: Commit**

```bash
git add src/db/migrations/009_last_missed_on.sql
git commit -m "feat(db): last_missed_on nos dois inventarios (migration 009)"
```

---

### Task 2: Lado Google — inventário carrega o fuso, incremento vira idempotente

**Files:**
- Modify: `src/db/repositories/google_ads_accounts.py` (`InventoryRow`, `list_inventory_rows`, `apply_absences`)
- Modify: `src/jobs/account_resync.py` (passa `now` para o cálculo do dia)
- Test: `tests/integration/test_google_reconcile_repo.py`

**Interfaces:**
- Consumes: a coluna da Task 1; `account_today(time_zone, *, now)` de `src/google_ads/queries/_common.py`.
- Produces: `apply_absences(conn, *, bump: list[tuple[str, date]], reset: list[str]) -> None` — o `bump` passa a carregar o dia de cada conta.

- [ ] **Step 1: Escrever o teste que falha**

```python
async def test_duas_execucoes_no_mesmo_dia_contam_uma_ausencia(db) -> None:
    """C4: com `maxRetries: 3` no job, um retry após o commit reexecuta a
    reconciliação. Antes deste fix, a mesma ausência era contada de novo, e a
    carência de 3 dias que protege a conta do cliente caía em 2 execuções."""
    hoje = date(2026, 9, 6)
    async with db.acquire() as conn:
        await _semear_conta(conn, "1234567890", missed_syncs=0)
        await google_ads_accounts.apply_absences(conn, bump=[("1234567890", hoje)], reset=[])
        await google_ads_accounts.apply_absences(conn, bump=[("1234567890", hoje)], reset=[])
        linha = await conn.fetchrow(
            "SELECT missed_syncs, last_missed_on FROM google_ads_accounts "
            "WHERE customer_id = $1", "1234567890")
    assert linha["missed_syncs"] == 1, "retry no mesmo dia contou duas vezes"
    assert linha["last_missed_on"] == hoje


async def test_dia_novo_conta_de_novo(db) -> None:
    """A carência tem que continuar avançando: dia diferente, ausência nova."""
    async with db.acquire() as conn:
        await _semear_conta(conn, "1234567890", missed_syncs=0)
        await google_ads_accounts.apply_absences(
            conn, bump=[("1234567890", date(2026, 9, 6))], reset=[])
        await google_ads_accounts.apply_absences(
            conn, bump=[("1234567890", date(2026, 9, 7))], reset=[])
        n = await conn.fetchval(
            "SELECT missed_syncs FROM google_ads_accounts WHERE customer_id = $1",
            "1234567890")
    assert n == 2
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest tests/integration/test_google_reconcile_repo.py -m integration -q -k "mesmo_dia or dia_novo"`
Expected: FAIL — a assinatura de `apply_absences` ainda recebe `list[str]`.

- [ ] **Step 3: Implementar**

```python
async def apply_absences(
    conn: asyncpg.Connection, *, bump: list[tuple[str, date]], reset: list[str]
) -> None:
    """Aplica a carência decidida por `build_plan()`. Não decide nada — só escreve.

    C4: o incremento é condicional ao dia. `missed_syncs = missed_syncs + 1` puro
    contava uma ausência por EXECUÇÃO, e o job tem `maxRetries: 3` — um retry
    depois do commit da reconciliação contava a mesma ausência de novo. A
    carência de 3 dias caía em 2 execuções, e do lado Meta isso é revogação de
    acesso de gestor a conta de cliente.

    O dia vem do fuso da CONTA (F141), calculado por `account_today` sobre o
    fuso que `list_inventory_rows` já traz — sem I/O extra. `resolve_account_today`
    faria uma leitura por conta e adquiriria uma segunda conexão do pool dentro
    da transação aberta da reconciliação.
    """
    if bump:
        await conn.executemany(
            "UPDATE google_ads_accounts "
            "   SET missed_syncs = missed_syncs + 1, last_missed_on = $2 "
            " WHERE customer_id = $1 "
            "   AND last_missed_on IS DISTINCT FROM $2",
            bump,
        )
    if reset:
        await conn.execute(
            "UPDATE google_ads_accounts SET missed_syncs = 0, last_missed_on = NULL "
            "WHERE customer_id = ANY($1::text[]) AND missed_syncs <> 0",
            reset,
        )
```

`IS DISTINCT FROM` e não `<>` porque `last_missed_on` é `NULL` em toda linha hoje,
e `NULL <> $2` é `NULL`, que não satisfaz o `WHERE` — a primeira ausência de cada
conta nunca seria contada.

O `reset` zera `last_missed_on` junto: conta que reapareceu não pode carregar a
data velha, senão a próxima ausência dela seria pulada se caísse no mesmo dia.
E ganha `AND missed_syncs <> 0`, que o lado Meta já tem — simetria (F128).

- [ ] **Step 4: Fazer o inventário carregar o fuso**

`InventoryRow` ganha `time_zone: str | None`, e `list_inventory_rows` passa a
selecioná-lo. Em `account_resync.py`, o `to_bump` de `build_plan` (que devolve
ids) é casado com o fuso do inventário e vira `list[tuple[str, date]]` via
`account_today(tz, now=agora)`, com **um único `agora`** lido uma vez por
execução e passado adiante — nunca `datetime.now()` por conta.

- [ ] **Step 5: Rodar e ver passar**

Run: `python -m pytest tests/integration/test_google_reconcile_repo.py -m integration -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/db/repositories/google_ads_accounts.py src/jobs/account_resync.py tests/integration/test_google_reconcile_repo.py
git commit -m "fix(db): ausencia conta uma vez por dia no lado Google (C4)"
```

---

### Task 3: Lado Meta — o gêmeo

**Files:**
- Modify: `src/db/repositories/meta_ad_accounts.py`
- Modify: `src/jobs/meta_resync.py`
- Test: `tests/integration/test_meta_reconcile_repo.py`

**Interfaces:**
- Consumes: a coluna da Task 1.
- Produces: `apply_absences(conn, *, bump: list[tuple[str, date]], reset: list[str]) -> None` em `meta_ad_accounts`.

**Este lado é o urgente:** ele **revoga acesso em produção desde 05/09**. O Google está em soak e não aplica; o Meta aplica.

O fuso vem de `meta_ad_accounts.timezone_name`, que já existe (`:24`) e é populado
por `src/auth/meta_oauth.py` — não é preciso buscar nada.

- [ ] **Step 1: Escrever os mesmos dois testes** do Task 2, adaptados para `ad_account_id` e `meta_ad_accounts`. Repita o código; não escreva "igual à Task 2".

```python
async def test_duas_execucoes_no_mesmo_dia_contam_uma_ausencia_meta(db) -> None:
    """C4, lado Meta — este laço REVOGA acesso em produção desde 05/09."""
    hoje = date(2026, 9, 6)
    async with db.acquire() as conn:
        await _semear_conta_meta(conn, "act_123", missed_syncs=0)
        await meta_ad_accounts.apply_absences(conn, bump=[("act_123", hoje)], reset=[])
        await meta_ad_accounts.apply_absences(conn, bump=[("act_123", hoje)], reset=[])
        linha = await conn.fetchrow(
            "SELECT missed_syncs, last_missed_on FROM meta_ad_accounts "
            "WHERE ad_account_id = $1", "act_123")
    assert linha["missed_syncs"] == 1
    assert linha["last_missed_on"] == hoje


async def test_dia_novo_conta_de_novo_meta(db) -> None:
    async with db.acquire() as conn:
        await _semear_conta_meta(conn, "act_123", missed_syncs=0)
        await meta_ad_accounts.apply_absences(
            conn, bump=[("act_123", date(2026, 9, 6))], reset=[])
        await meta_ad_accounts.apply_absences(
            conn, bump=[("act_123", date(2026, 9, 7))], reset=[])
        n = await conn.fetchval(
            "SELECT missed_syncs FROM meta_ad_accounts WHERE ad_account_id = $1",
            "act_123")
    assert n == 2
```

- [ ] **Step 2: Rodar e ver falhar.** Expected: FAIL por assinatura.

- [ ] **Step 3: Implementar**, espelhando a Task 2 — `executemany` com `IS DISTINCT FROM`, `reset` zerando `last_missed_on` junto.

- [ ] **Step 4: Confirmar a simetria.** Compare as duas implementações lado a lado e liste qualquer diferença que não seja o nome da tabela e da coluna-chave. Diferença não explicada é achado: o F128 nasceu de uma cláusula que ficou de fora de um dos lados.

- [ ] **Step 5: Rodar** o full sweep. **Step 6: Commit.**

---

### Task 4: O bookkeeping que dispara o retry

**Files:**
- Modify: `src/jobs/account_resync.py` (`record_job_run`)
- Modify: `src/jobs/meta_resync.py` (`record_job_run` + `configure_logging`)
- Test: `tests/unit/test_job_bookkeeping.py` (ou o arquivo existente de job)

**Por que isto importa mesmo com o C4 fechado:** a idempotência impede o dano; esta
task impede o gatilho. `record_job_run` roda **fora** da transação da reconciliação
(ela fecha no `return` de `reconcile_google`) e **sem `best_effort`**, ao contrário
dos três vizinhos no mesmo arquivo. Exceção ali derruba a task **com a reconciliação
já commitada** — que é exatamente o F83: I/O de bookkeeping pós-commit transformando
operação bem-sucedida em falha.

- [ ] **Step 1: Teste que prove.** Faça `record_job_run` levantar e afirme que `run()` **não** propaga — a reconciliação já commitou, e o job tem que terminar com sucesso.

- [ ] **Step 2: Rodar e ver falhar.**

- [ ] **Step 3: Envolver em `best_effort`** nos dois jobs, com a chave de log no padrão dos vizinhos.

- [ ] **Step 4: `configure_logging()` em `meta_resync.run()`** — só o lado Google recebeu (Task 7 de um sprint anterior). Sem isso o log estruturado do job Meta não sai com `severity`, e o Cloud Logging não o classifica.

- [ ] **Step 5: Remover o `reset` redundante do lado Google.** `upsert_many` já zera `missed_syncs` para toda conta presente no MCC, e `to_reset` é subconjunto de `mcc_ids` por construção. **Antes de remover, prove a equivalência com um teste** — se não conseguir provar, não remova e registre por quê.

- [ ] **Step 6: Full sweep. Step 7: Commit.**

---

### Task 5: Medir a produção e documentar

**Files:**
- Modify: `docs/operacao/findings-catalog.md`
- Modify: `docs/operacao/estado-atual.md`

- [ ] **Step 1: Medir o estado atual dos dois inventários.**

**Este passo depende de credencial `gcloud` válida**, que estava expirada quando
este plano foi escrito. Se `gcloud secrets versions access latest
--secret=database-url --project=v4-ads-mcp` falhar por reautenticação, **pare e
peça ao Wellington** — não invente o número nem pule a medição.

Com a credencial, leia (somente leitura, nunca escreva):

```sql
SELECT 'google' AS lado, customer_id AS id, missed_syncs, is_active
  FROM google_ads_accounts WHERE missed_syncs > 0
UNION ALL
SELECT 'meta', ad_account_id, missed_syncs, is_active
  FROM meta_ad_accounts WHERE missed_syncs > 0
ORDER BY missed_syncs DESC;
```

**Se houver conta em ou acima do limiar (3)**, ela pode ter chegado lá por contagem
dupla — e do lado Meta isso significa grant já revogado. Registre a lista e
**leve ao Wellington antes de qualquer correção de dado**: reverter revogação é
decisão dele, não sua.

- [ ] **Step 2: Abrir o ID no catálogo** (sugestão **F157 — carência consumida por retry do job**), com: a cadeia medida (incremento cego + `record_job_run` fora de `best_effort` + `maxRetries: 3`, medido por `gcloud run jobs describe` como `1 3`), por que o `migrate` tem `--max-retries=1` e o `resync` nunca recebeu, a decisão de tornar idempotente **em vez de** capar o retry (retry é útil; operação não-idempotente é o defeito), e o que ficou de fora.

- [ ] **Step 3: Registrar no `estado-atual.md`** o efeito sobre a pendência 7: o contador que ela usaria estava inflado, e o soak do Google só passa a medir o que promete depois deste PR.

- [ ] **Step 4: Full sweep. Step 5: Commit.** Sem push e sem PR — a decisão de publicar é do Wellington.

---

## Auto-revisão do plano

**Cobertura da spec (PR 2 da seção 4):** migration aditiva ✅ (T1); incremento condicional a `last_missed_on` ✅ (T2, T3); dia no fuso da conta ✅ (T2 Step 4, com a divergência de mecanismo declarada e justificada acima); `record_job_run` com `best_effort` ✅ (T4); `configure_logging` no Meta ✅ (T4 Step 4); `reset` redundante removido com prova ✅ (T4 Step 5); medição da produção antes do código ✅ (T5 Step 1, com o bloqueio de credencial declarado).

**Divergência deliberada:** a spec diz `resolve_account_today`; uso `account_today` sobre o fuso que o inventário passa a carregar. Mesma semântica, sem adquirir segunda conexão do pool dentro da transação aberta. Registrado na seção própria.

**Ordem invertida em relação à spec:** a spec põe a medição "antes de escrever código". Ponho na Task 5 porque a credencial `gcloud` está expirada e bloquear as quatro tasks anteriores por isso custaria a sessão inteira — mas a medição continua **obrigatória antes do merge**, e a Task 5 para se ela não puder ser feita.

**Consistência de tipos:** `apply_absences(conn, *, bump: list[tuple[str, date]], reset: list[str]) -> None` nos dois repositórios; `InventoryRow.time_zone: str | None`; `account_today(time_zone: str | None, *, now: datetime) -> date`.
