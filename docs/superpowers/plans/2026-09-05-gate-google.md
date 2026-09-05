# Gate de acesso Google — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fazer do `can_manager_access` do Google uma fronteira real — cruzando o
inventário, com revogação soft e reconciliação contra o MCC — e tornar visível a
conta que entra sem gestor delegado.

**Architecture:** Espelha o desenho Meta de 20/08. Um planejador **puro** decide
(`src/google_ads/reconcile.py`, zero I/O); o repositório aplica; o
`account_resync` orquestra dentro de uma transação, atrás de uma trava de
rollout. O gate vai primeiro e sozinho porque não depende de nada do resto.

**Tech Stack:** Python 3.13, asyncpg (SQL cru, sem ORM), FastAPI + Jinja2 + HTMX,
pytest + testcontainers, Cloud Run Job diário.

**Spec:** [`docs/superpowers/specs/2026-09-05-gate-google-design.md`](../specs/2026-09-05-gate-google-design.md)

## Global Constraints

- **Toda chamada de SDK Google sai do event loop** via `run_blocking` (F86/F109).
- **Nada de `datetime.now`/`date.today` em tool Google** — guard AST em
  `test_no_server_clock_in_google_tools.py`. Não se aplica a job, mas o job usa
  `now()` do Postgres, que é onde o resto do repo já põe carimbo.
- **Migration commitada é imutável** — há PreToolUse guard. Migration nova sempre.
- **Zero JS/CSS inline em template** (CSP sem `unsafe-*`); comportamento em
  `v4-panel.js` via `data-v4-*`.
- **Toda `<table>` num contentor com `tabindex="0" role="region" aria-label`**
  (F118/F125); `<th scope>` obrigatório (F104).
- **Gate local antes de todo commit:** `python scripts/check_pre_push.py` — rodar
  mudo e ler `$?`, **nunca** com pipe antes do `&&`.
- **Tarefas que tocam SQL/JOIN/transação exigem** `python scripts/check_pre_push_full.py`
  (Docker) ou aceitar o CI como validador.
- Commits: `feat(scope):` / `fix(scope):` / `docs(scope):`, trailer
  `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.

## Três correções da spec, achadas lendo o código antes de despachar

A spec está mesclada e estas três linhas dela estão **erradas**. O plano vale; a
spec é corrigida na Task 8.

1. **§5.4 diz "dois call-sites de `DELETE`, incluindo o do offboarding".** O
   `DELETE ... WHERE manager_id = $1` (`manager_account_access.py:147`) está
   dentro de **`copy_access`**, não de offboarding — e torná-lo soft quebraria a
   função, porque o `INSERT` seguinte não tem `ON CONFLICT` e bateria na PK.
2. **São CINCO funções a tocar, não duas.** `grant` (`DO UPDATE` sem limpar
   `revoked_at`), `grant_all_active` e `bulk_grant` (`DO NOTHING` — reconceder
   vira no-op silencioso e deixa o gestor bloqueado para sempre), `copy_access`
   e `list_accounts_for_manager` (não filtra revogado).
3. **§6.1 chaveia a fila "Saíram do MCC" em carência/`is_active`.** Errado, e é
   a lição C1 da revisão Meta, escrita no docstring de
   `meta_ad_accounts.list_queues`: quando a conta volta, `upsert_many` a reativa
   **na mesma execução**, e é aí, e só aí, que restaurar faz sentido — porque o
   gate exige conta ativa. Chavear em `is_active=false` faz a conta sumir da fila
   no instante em que se torna restaurável. **A chave é ter grant revogado por
   churn PENDENTE.**

## File Structure

| Arquivo | Responsabilidade |
|---|---|
| `src/google_ads/reconcile.py` **(criar)** | Planejador puro. Zero I/O. É a única parte capaz de revogar acesso indevidamente, então é a parte que tem de ser testável sem mock. |
| `src/db/migrations/008_google_reconciliation.sql` **(criar)** | `missed_syncs`, `revoked_at`, `revoked_reason`. Aditiva. |
| `src/db/repositories/manager_account_access.py` | Revogação soft: 5 funções. |
| `src/db/repositories/google_ads_accounts.py` | Carência (`apply_absences`), `list_inventory_rows`, `list_queues`. |
| `src/jobs/account_resync.py` | Orquestra: lê → planeja → aplica → audita. |
| `src/config.py` | `google_reconcile_apply: bool = False`. |
| `.github/workflows/deploy.yml` | A trava no `JOB_ENV_VARS`. |
| `src/web/routes.py` + `templates/admin/accounts.html` | As duas filas + restaurar. |
| `docs/operacao/infra-setup.md` | Runbook REST da métrica e da policy. |

---

## Task 0: Sonda do `customer_manager_link` — medição, não código

**Files:** nenhum. O produto é uma resposta escrita no relatório da task.

**Interfaces:**
- Consumes: nada.
- Produces: a decisão binária que a Task 4 consome — o `Plan` tem ou não campo
  `unreachable`.

Isto não é TDD porque não há código. É probe empírica, e ela existe porque
**assertar superfície de API externa por analogia já custou três findings aqui**
(F87, F89, e os mocks do F84/F89).

- [ ] **Step 1: Validar a query**

Chamar a tool MCP `validate_gaql` com `customer_id` de uma conta que o gestor
alcance (ex.: `7862230676`) e:

```sql
SELECT customer_manager_link.manager_customer,
       customer_manager_link.manager_link_id,
       customer_manager_link.status
FROM customer_manager_link
```

Esperado: `{"valid": true, "error": null}` (já confirmado em 05/09 — reconfirmar).

- [ ] **Step 2: Ler de verdade**

Chamar `run_gaql` com a mesma query. Registrar a saída **literal**.

- [ ] **Step 3: Decidir e escrever**

Duas saídas possíveis, ambas já especificadas — não há espaço para julgamento:

- **Se aparecerem links com `status` ≠ `ACTIVE`** (ex.: `PENDING`), há análogo do
  `su_reachable`: a Task 4 inclui `unreachable: list[str]` no `Plan`, a Task 6
  ganha uma terceira raia "Vínculo pendente no MCC", e essas contas **nunca** são
  desativadas nem revogadas — só sinalizadas.
- **Se todos vierem `ACTIVE`, ou o recurso não devolver linha útil**, o `Plan`
  fica sem `unreachable` e a ausência do análogo entra como comentário no topo de
  `src/google_ads/reconcile.py`, **com a data da medição e a saída observada**.

- [ ] **Step 4: Commit do registro**

```bash
git add docs/superpowers/plans/2026-09-05-gate-google.md
git commit -m "docs(plans): Task 0 — sonda do customer_manager_link, resultado registrado"
```

---

## Task 1: O gate cruza o inventário

**Files:**
- Modify: `src/db/repositories/manager_account_access.py:97-113`
- Test: `tests/integration/test_repositories.py`

**Interfaces:**
- Consumes: nada.
- Produces: `can_manager_access(conn, manager_id, customer_id, *, level="read") -> bool`
  — assinatura **inalterada**. Só o predicado muda.

Vai num PR próprio. É o item severo e não depende da migration.

- [ ] **Step 1: Varrer os call-sites antes de tocar em nada**

```bash
grep -rn "can_manager_access" src/ tests/ --include=*.py | grep -v meta
```

Esperado (medido em 05/09): **um** chamador de produção,
`src/google_ads/access.py:39`; dois testes de integração em
`tests/integration/test_repositories.py:271-272`; dois patch-targets em
`tests/unit/test_account_access.py:14,33`. Se aparecer mais alguma coisa,
**pare e reporte** — adicionar gate sem varrer é o F57.

- [ ] **Step 2: Escrever o teste que falha**

Em `tests/integration/test_repositories.py`:

```python
async def test_gate_nega_conta_inativa_com_grant_vivo(db) -> None:
    """F-gate: 34 grants vivos em 9 contas fora do MCC (medido 2026-09-05).

    O gate antigo aprovava os 34 — quem os negava era o Google, não nós.
    """
    async with db.acquire() as conn:
        mid = await _make_manager(conn, "gate@v4company.com")
        await google_ads_accounts.upsert_many(
            conn,
            [{"customer_id": "555", "mcc_id": "6436352492", "descriptive_name": "Ex-cliente"}],
        )
        await manager_account_access.grant(conn, manager_id=mid, customer_id="555")
        assert await manager_account_access.can_manager_access(conn, mid, "555") is True

        # A conta sai do MCC.
        await conn.execute(
            "UPDATE google_ads_accounts SET is_active = false WHERE customer_id = '555'"
        )
        assert await manager_account_access.can_manager_access(conn, mid, "555") is False
        assert (
            await manager_account_access.can_manager_access(conn, mid, "555", level="write")
            is False
        )
```

- [ ] **Step 3: Rodar e ver falhar**

```bash
python -m pytest tests/integration/test_repositories.py::test_gate_nega_conta_inativa_com_grant_vivo -v
```

Esperado: **FAIL** no primeiro `is False` — o gate atual devolve `True`.
Se passar de primeira, o teste não distingue código bom de quebrado: **pare**.

- [ ] **Step 4: Implementar**

Substituir o corpo de `can_manager_access`:

```python
async def can_manager_access(
    conn: asyncpg.Connection, manager_id: UUID, customer_id: str, *, level: str = "read"
) -> bool:
    """Gate por conta — e, como no Meta, é a ÚNICA fronteira que sobra.

    `build_client_for_manager` usa o token do próprio gestor, mas com
    `login_customer_id` = o MCC, e as identidades dos gestores são usuárias do
    MCC (confirmado 2026-09-05). Logo o token alcança as 26 contas de cliente e
    quem os limita às atribuídas é esta função.

    O JOIN com o inventário é o fix da pendência 10: em 2026-09-05 havia 34
    grants `write` vivos em 9 contas que saíram do MCC, e este predicado
    aprovava os 34. Quem os negava era o Google — delegar ao provedor a
    aplicação de uma regra nossa.
    """
    row = await conn.fetchrow(
        """
        SELECT m.access_level
          FROM manager_account_access m
          JOIN google_ads_accounts a ON a.customer_id = m.customer_id
         WHERE m.manager_id = $1
           AND m.customer_id = $2
           AND a.is_active = true
        """,
        manager_id,
        customer_id,
    )
    if row is None:
        return False
    if level == "read":
        return True
    return bool(row["access_level"] == "write")
```

- [ ] **Step 5: Rodar e ver passar**

```bash
python -m pytest tests/integration/test_repositories.py -v -k "gate_nega or can_manager"
```

Esperado: PASS, e os dois testes antigos (`:271-272`) continuam passando.

- [ ] **Step 6: Verificar o guard por sabotagem**

**Nunca `git checkout`** (descarta trabalho não commitado). Copiar o arquivo,
reverter o predicado na cópia, rodar o teste contra ela, confirmar FAIL,
restaurar:

```bash
cp src/db/repositories/manager_account_access.py /tmp/mac_backup.py
# reverter o SELECT para a versão de uma tabela só, rodar o teste, ver FAIL
cp /tmp/mac_backup.py src/db/repositories/manager_account_access.py
```

- [ ] **Step 7: Gate e commit**

```bash
python scripts/check_pre_push_full.py
```

```bash
git add src/db/repositories/manager_account_access.py tests/integration/test_repositories.py
git commit -m "fix(db): gate Google cruza o inventario (pendencia 10)"
```

---

## Task 2: Migration 008

**Files:**
- Create: `src/db/migrations/008_google_reconciliation.sql`
- Test: `tests/integration/test_migrations.py` (se existir asserção de colunas;
  senão a cobertura vem das Tasks 3-5)

**Interfaces:**
- Produces: colunas `google_ads_accounts.missed_syncs` (INTEGER NOT NULL
  DEFAULT 0), `manager_account_access.revoked_at` (TIMESTAMPTZ NULL),
  `manager_account_access.revoked_reason` (TEXT NULL).

- [ ] **Step 1: Escrever a migration**

```sql
-- 008_google_reconciliation.sql
-- Reconciliação do lado Google contra o MCC (spec 2026-09-05).
--
-- missed_syncs dá ao Google a carência que o Meta ganhou na 005. Sem ela,
-- `mark_inactive_except` desativa na PRIMEIRA ausência, e amarrar revogação a
-- esse sinal revoga grant real na primeira leitura parcial (F93).
--
-- revoked_at/revoked_reason tornam a revogação SOFT: a linha do grant fica, o
-- gate nega, e a conta que volta ao MCC restaura com um clique. Antes era
-- DELETE — sem trilha e sem caminho de volta.
--
-- Sem backfill de propósito: missed_syncs = 0 é o estado correto de partida, e
-- revoked_at nulo é o que as 138 linhas existentes já são (medido 2026-09-05).

ALTER TABLE google_ads_accounts
    ADD COLUMN IF NOT EXISTS missed_syncs INTEGER NOT NULL DEFAULT 0;

ALTER TABLE manager_account_access
    ADD COLUMN IF NOT EXISTS revoked_at     TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS revoked_reason TEXT;

CREATE INDEX IF NOT EXISTS idx_mac_revoked
    ON manager_account_access (customer_id)
    WHERE revoked_at IS NOT NULL;
```

- [ ] **Step 2: Aplicar e conferir**

```bash
python scripts/check_pre_push_full.py
```

Esperado: os testes de integração sobem o container, aplicam `001`…`008` e
passam. Se a migration tiver erro de sintaxe, falha aqui.

- [ ] **Step 3: Commit**

```bash
git add src/db/migrations/008_google_reconciliation.sql
git commit -m "feat(db): migration 008 — carencia e revogacao soft no lado Google"
```

---

## Task 3: Revogação soft nas cinco funções

**Files:**
- Modify: `src/db/repositories/manager_account_access.py` (`grant`,
  `grant_all_active`, `revoke`, `bulk_grant`, `copy_access`,
  `list_accounts_for_manager`, `can_manager_access`)
- Test: `tests/integration/test_repositories.py`

**Interfaces:**
- Consumes: colunas da Task 2.
- Produces:
  - `LEFT_MCC_REASON = "left_mcc"` e `ADMIN_REVOKED_REASON = "admin_revoked"`
  - `revoke(conn, *, manager_id, customer_id, reason=ADMIN_REVOKED_REASON) -> None`
  - `revoke_for_inactive_accounts(conn, *, reason=LEFT_MCC_REASON) -> dict[str, list[str]]`
    — mapa `customer_id -> [manager_id, …]` do que foi revogado
  - `restore_for_account(conn, *, customer_id) -> list[str]` — manager_ids
    restaurados; só linhas com `revoked_reason = LEFT_MCC_REASON`
  - `count_grants_on_inactive_accounts(conn) -> int` — leitura pura, o número
    que o dry-run reporta como `revoke_candidates` (implementado na Task 5)

🔴 **`revoke_for_inactive_accounts` opera sobre TODA conta inativa**, não só
sobre a que cruzou a carência nesta execução. É a invariante da §5.3 da spec —
*nenhum grant vivo em conta inativa* — e é o que cobre os 34 grants legados,
que jamais entrariam num `to_remove` calculado a partir de `ativos`.

- [ ] **Step 1: Escrever os testes que falham**

```python
async def test_revoke_e_soft_e_o_gate_nega(db) -> None:
    async with db.acquire() as conn:
        mid = await _make_manager(conn, "soft@v4company.com")
        await google_ads_accounts.upsert_many(
            conn, [{"customer_id": "601", "mcc_id": "1", "descriptive_name": "X"}]
        )
        await manager_account_access.grant(conn, manager_id=mid, customer_id="601")
        await manager_account_access.revoke(conn, manager_id=mid, customer_id="601")

        # A LINHA FICA — é o que distingue soft de DELETE.
        row = await conn.fetchrow(
            "SELECT revoked_at, revoked_reason FROM manager_account_access "
            "WHERE manager_id = $1 AND customer_id = '601'",
            mid,
        )
        assert row is not None
        assert row["revoked_at"] is not None
        assert row["revoked_reason"] == manager_account_access.ADMIN_REVOKED_REASON
        assert await manager_account_access.can_manager_access(conn, mid, "601") is False


async def test_reconceder_limpa_a_revogacao(db) -> None:
    """Sem isto, o `ON CONFLICT DO NOTHING` deixa o gestor bloqueado pra sempre."""
    async with db.acquire() as conn:
        mid = await _make_manager(conn, "regrant@v4company.com")
        await google_ads_accounts.upsert_many(
            conn, [{"customer_id": "602", "mcc_id": "1", "descriptive_name": "Y"}]
        )
        await manager_account_access.grant(conn, manager_id=mid, customer_id="602")
        await manager_account_access.revoke(conn, manager_id=mid, customer_id="602")
        assert await manager_account_access.can_manager_access(conn, mid, "602") is False

        await manager_account_access.bulk_grant(
            conn, manager_id=mid, customer_ids=["602"], granted_by=mid
        )
        assert await manager_account_access.can_manager_access(conn, mid, "602") is True


async def test_revoke_for_inactive_pega_o_legado_nao_so_o_novo(db) -> None:
    """Os 34 grants de 2026-09-05 estavam em contas JA inativas.

    Um plano que parte de `ativos` nunca os alcançaria.
    """
    async with db.acquire() as conn:
        mid = await _make_manager(conn, "legado@v4company.com")
        await google_ads_accounts.upsert_many(
            conn, [{"customer_id": "603", "mcc_id": "1", "descriptive_name": "Ex"}]
        )
        await manager_account_access.grant(conn, manager_id=mid, customer_id="603")
        await conn.execute(
            "UPDATE google_ads_accounts SET is_active = false WHERE customer_id = '603'"
        )

        atingidos = await manager_account_access.revoke_for_inactive_accounts(conn)
        assert atingidos == {"603": [str(mid)]}
        row = await conn.fetchrow(
            "SELECT revoked_reason FROM manager_account_access WHERE customer_id = '603'"
        )
        assert row["revoked_reason"] == manager_account_access.LEFT_MCC_REASON


async def test_restore_devolve_so_o_churn(db) -> None:
    async with db.acquire() as conn:
        a = await _make_manager(conn, "churn@v4company.com")
        b = await _make_manager(conn, "punido@v4company.com")
        await google_ads_accounts.upsert_many(
            conn, [{"customer_id": "604", "mcc_id": "1", "descriptive_name": "Z"}]
        )
        await manager_account_access.grant(conn, manager_id=a, customer_id="604")
        await manager_account_access.grant(conn, manager_id=b, customer_id="604")
        # b perdeu acesso de propósito; a perdeu por churn.
        await manager_account_access.revoke(conn, manager_id=b, customer_id="604")
        await conn.execute(
            "UPDATE google_ads_accounts SET is_active = false WHERE customer_id = '604'"
        )
        await manager_account_access.revoke_for_inactive_accounts(conn)
        await conn.execute(
            "UPDATE google_ads_accounts SET is_active = true WHERE customer_id = '604'"
        )

        restaurados = await manager_account_access.restore_for_account(conn, customer_id="604")
        assert restaurados == [str(a)]
        assert await manager_account_access.can_manager_access(conn, a, "604") is True
        assert await manager_account_access.can_manager_access(conn, b, "604") is False
```

- [ ] **Step 2: Rodar e ver os quatro falharem**

```bash
python -m pytest tests/integration/test_repositories.py -v -k "soft or reconceder or inactive or restore"
```

Esperado: FAIL nos quatro (`AttributeError` nos dois últimos,
`assert None is not None` nos primeiros).

- [ ] **Step 3: Implementar**

No topo de `src/db/repositories/manager_account_access.py`:

```python
LEFT_MCC_REASON = "left_mcc"
ADMIN_REVOKED_REASON = "admin_revoked"
```

`revoke` deixa de deletar:

```python
async def revoke(
    conn: asyncpg.Connection,
    *,
    manager_id: UUID,
    customer_id: str,
    reason: str = ADMIN_REVOKED_REASON,
) -> None:
    """Revogação SOFT. A linha fica; o gate nega.

    Era DELETE. Sem a linha não há trilha de quem perdeu o quê e quando, e não
    há caminho de volta — e o caminho de volta é o que distingue churn
    (restaurável) de decisão do admin (não volta).
    """
    await conn.execute(
        """
        UPDATE manager_account_access
           SET revoked_at = now(), revoked_reason = $3
         WHERE manager_id = $1 AND customer_id = $2 AND revoked_at IS NULL
        """,
        manager_id,
        customer_id,
        reason,
    )
```

As três funções de conceder passam a **limpar** a revogação. Em `grant`, o
`ON CONFLICT DO UPDATE` ganha duas linhas:

```python
        ON CONFLICT (manager_id, customer_id) DO UPDATE SET
            access_level = EXCLUDED.access_level,
            granted_at = now(),
            granted_by = EXCLUDED.granted_by,
            revoked_at = NULL,
            revoked_reason = NULL
```

Em `grant_all_active` e `bulk_grant`, o `DO NOTHING` vira `DO UPDATE` — senão
reconceder é no-op silencioso sobre linha revogada:

```python
        ON CONFLICT (manager_id, customer_id) DO UPDATE SET
            revoked_at = NULL,
            revoked_reason = NULL
```

`list_accounts_for_manager` ganha `AND m.revoked_at IS NULL` no `WHERE`.

`can_manager_access` ganha `AND m.revoked_at IS NULL` (soma ao JOIN da Task 1).

`copy_access` **não vira soft** — ele substitui o conjunto do destino, e o
`INSERT` seguinte não tem `ON CONFLICT`. Mantém o `DELETE`, com o motivo escrito:

```python
    async with conn.transaction():
        # DELETE (não soft) de propósito: `copy_access` REESCREVE o conjunto do
        # destino, e o INSERT abaixo não tem ON CONFLICT — linha soft-revogada
        # sobrevivente bateria na PK. Revogação soft existe para churn e para a
        # decisão pontual do admin, que são remoções de UMA linha; esta é uma
        # substituição de conjunto e tem semântica própria.
        await conn.execute(
            "DELETE FROM manager_account_access WHERE manager_id = $1",
            to_manager_id,
        )
```

As duas funções novas:

```python
async def revoke_for_inactive_accounts(
    conn: asyncpg.Connection, *, reason: str = LEFT_MCC_REASON
) -> dict[str, list[str]]:
    """Revoga todo grant vivo em conta inativa. Devolve customer_id -> manager_ids.

    Opera sobre o ESTADO (`is_active = false`), não sobre o delta da execução.
    Em 2026-09-05 havia 34 grants vivos em 9 contas já inativas: um plano
    calculado a partir de `ativos` nunca os alcançaria, e o sprint fecharia
    verde sem tocar no que o motivou.
    """
    rows = await conn.fetch(
        """
        UPDATE manager_account_access m
           SET revoked_at = now(), revoked_reason = $1
          FROM google_ads_accounts a
         WHERE a.customer_id = m.customer_id
           AND a.is_active = false
           AND m.revoked_at IS NULL
        RETURNING m.customer_id, m.manager_id
        """,
        reason,
    )
    atingidos: dict[str, list[str]] = {}
    for r in rows:
        atingidos.setdefault(r["customer_id"], []).append(str(r["manager_id"]))
    return atingidos


async def restore_for_account(conn: asyncpg.Connection, *, customer_id: str) -> list[str]:
    """Devolve o acesso revogado por CHURN. Revogação de admin não volta."""
    rows = await conn.fetch(
        """
        UPDATE manager_account_access
           SET revoked_at = NULL, revoked_reason = NULL
         WHERE customer_id = $1
           AND revoked_at IS NOT NULL
           AND revoked_reason = $2
        RETURNING manager_id
        """,
        customer_id,
        LEFT_MCC_REASON,
    )
    return [str(r["manager_id"]) for r in rows]
```

- [ ] **Step 4: Rodar e ver passar**

```bash
python scripts/check_pre_push_full.py
```

Esperado: os 4 novos passam e **nenhum** dos existentes quebra — atenção aos de
`tests/integration/test_managers_invite.py:164,171` (usam `bulk_grant`) e
`tests/integration/test_repositories.py` (usam `revoke`).

- [ ] **Step 5: Commit**

```bash
git add src/db/repositories/manager_account_access.py tests/integration/test_repositories.py
git commit -m "feat(db): revogacao soft no lado Google, com restauracao so do churn"
```

---

## Task 4: O planejador puro

**Files:**
- Create: `src/google_ads/reconcile.py`
- Test: `tests/unit/test_google_reconcile.py`

**Interfaces:**
- Consumes: nada (puro).
- Produces:
  - `InventoryRow(customer_id: str, is_active: bool, missed_syncs: int)`
  - `Plan(to_add: list[str], to_bump: list[str], to_remove: list[str], to_reset: list[str], blocked_reason: str | None)`
  - `build_plan(*, mcc_ids: set[str], inventory: list[InventoryRow], complete: bool, threshold: int = 3, max_removal_ratio: float = 0.2, max_removal_abs: int = 5) -> Plan`

Se a Task 0 encontrou links pendentes, `Plan` ganha `unreachable: list[str]` e
`build_plan` ganha o kwarg `linked_ids: set[str]`, com
`unreachable = sorted(mcc_ids - linked_ids)`.

- [ ] **Step 1: Escrever os testes que falham**

```python
from src.google_ads.reconcile import InventoryRow, build_plan


def _inv(cid: str, *, ativo: bool = True, miss: int = 0) -> InventoryRow:
    return InventoryRow(customer_id=cid, is_active=ativo, missed_syncs=miss)


def test_ausencia_dentro_da_carencia_nao_remove():
    p = build_plan(mcc_ids={"a"}, inventory=[_inv("a"), _inv("b", miss=0)], complete=True)
    assert p.to_remove == []
    assert p.to_bump == ["b"]


def test_ausencia_que_cruza_a_carencia_remove():
    p = build_plan(mcc_ids={"a"}, inventory=[_inv("a"), _inv("b", miss=2)], complete=True)
    assert p.to_remove == ["b"]
    assert p.to_bump == []


def test_leitura_incompleta_bloqueia_destrutivo_mas_ainda_adiciona():
    p = build_plan(mcc_ids={"a", "novo"}, inventory=[_inv("a"), _inv("b", miss=9)], complete=False)
    assert p.to_remove == []
    assert p.blocked_reason == "leitura incompleta"
    assert p.to_add == ["novo"]


def test_conta_que_voltou_zera_o_contador():
    p = build_plan(mcc_ids={"a"}, inventory=[_inv("a", miss=2)], complete=True)
    assert p.to_reset == ["a"]
    assert p.to_remove == []


def test_teto_percentual_barra_remocao_em_massa():
    inv = [_inv(str(i), miss=5) for i in range(20)]
    p = build_plan(mcc_ids=set(), inventory=inv, complete=True)
    assert p.to_remove == []
    assert p.blocked_reason is not None
    assert "remocao em massa" in p.blocked_reason


def test_piso_do_teto_deixa_passar_a_saida_de_uma_conta_so():
    """Sem `max(1, ...)`, 2 ativas -> floor(0.4) = 0 e o guard barraria ATE uma."""
    p = build_plan(mcc_ids={"a"}, inventory=[_inv("a"), _inv("b", miss=5)], complete=True)
    assert p.to_remove == ["b"]
    assert p.blocked_reason is None


def test_conta_ja_inativa_nao_entra_em_plano_nenhum():
    """Documenta o limite do planejador — os 34 grants legados NAO saem daqui.

    Quem os cobre e `revoke_for_inactive_accounts`, que opera sobre o estado.
    """
    p = build_plan(mcc_ids=set(), inventory=[_inv("velha", ativo=False, miss=9)], complete=True)
    assert p.to_remove == []
    assert p.to_bump == []
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
python -m pytest tests/unit/test_google_reconcile.py -v
```

Esperado: `ModuleNotFoundError: No module named 'src.google_ads.reconcile'`.

- [ ] **Step 3: Implementar**

```python
"""Decide o que reconciliar no lado Google. Puro de propósito: nenhuma I/O.

Separar decisão de efeito é o que torna testável a única parte que pode revogar
acesso indevidamente. O repositório aplica; este módulo escolhe.

Espelha `src/meta_ads/reconcile.py`, com uma diferença deliberada: aqui não há
`unreachable`. No Meta, `su_reachable` separa "saiu da parceria" de "SU não
atribuído" — duas ações humanas diferentes.

Substitua a linha abaixo pelo resultado literal da Task 0, com a data:

    Sondado em 2026-09-__: `customer_manager_link.status` devolveu <saída>, logo
    <não há / há> análogo do `su_reachable` no lado Google.
"""

import math
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class InventoryRow:
    customer_id: str
    is_active: bool
    missed_syncs: int


@dataclass(frozen=True, slots=True)
class Plan:
    to_add: list[str] = field(default_factory=list)
    to_bump: list[str] = field(default_factory=list)
    to_remove: list[str] = field(default_factory=list)
    to_reset: list[str] = field(default_factory=list)
    blocked_reason: str | None = None


def build_plan(
    *,
    mcc_ids: set[str],
    inventory: list[InventoryRow],
    complete: bool,
    threshold: int = 3,
    max_removal_ratio: float = 0.2,
    max_removal_abs: int = 5,
) -> Plan:
    """(MCC, inventário) → plano. Aditivo sempre; destrutivo só com leitura completa."""
    ativos = [r for r in inventory if r.is_active]
    ids_ativos = {r.customer_id for r in ativos}

    to_add = sorted(mcc_ids - ids_ativos)
    to_reset = sorted(
        r.customer_id for r in ativos if r.missed_syncs and r.customer_id in mcc_ids
    )

    if not complete:
        # Metade da lista não sustenta "esta conta saiu do MCC".
        return Plan(to_add=to_add, to_reset=to_reset, blocked_reason="leitura incompleta")

    ausentes = [r for r in ativos if r.customer_id not in mcc_ids]
    # missed_syncs conta as ausências ANTERIORES; esta execução é a próxima.
    remover = sorted(r.customer_id for r in ausentes if r.missed_syncs + 1 >= threshold)
    marcar = sorted(r.customer_id for r in ausentes if r.missed_syncs + 1 < threshold)

    # `max(1, ...)`: sem o piso, inventário pequeno zera o teto (2 ativas → 20% →
    # floor 0) e o guard barraria ATÉ a saída de uma conta só. O guard existe
    # contra remoção em massa, não contra o caso normal.
    teto = max(1, min(max_removal_abs, math.floor(len(ativos) * max_removal_ratio)))
    if remover and len(remover) > teto:
        return Plan(
            to_add=to_add,
            to_reset=to_reset,
            blocked_reason=(
                f"remocao em massa barrada: {len(remover)} contas de {len(ativos)} ativas "
                f"(teto {teto})"
            ),
        )

    return Plan(to_add=to_add, to_bump=marcar, to_remove=remover, to_reset=to_reset)
```

- [ ] **Step 4: Rodar e ver passar**

```bash
python -m pytest tests/unit/test_google_reconcile.py -v
```

Esperado: 7 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/google_ads/reconcile.py tests/unit/test_google_reconcile.py
git commit -m "feat(google_ads): planejador puro da reconciliacao contra o MCC"
```

---

## Task 5: A carência no repositório e o laço no job

**Files:**
- Modify: `src/db/repositories/google_ads_accounts.py` (adiciona
  `list_inventory_rows`, `apply_absences`, `deactivate`)
- Modify: `src/jobs/account_resync.py:113-137`
- Modify: `src/config.py:60` (área)
- Modify: `.github/workflows/deploy.yml:35`
- Test: `tests/integration/test_repositories.py`, `tests/unit/test_account_resync.py`

**Interfaces:**
- Consumes: `build_plan`, `InventoryRow`, `Plan` (Task 4);
  `revoke_for_inactive_accounts` (Task 3).
- Produces:
  - `list_inventory_rows(conn) -> list[InventoryRow]`
  - `apply_absences(conn, *, bump: list[str], reset: list[str]) -> None`
  - `deactivate(conn, *, customer_ids: list[str]) -> int`
  - `Settings.google_reconcile_apply: bool`

- [ ] **Step 1: Escrever o teste que falha (a ordem lê-antes-do-upsert)**

Em `tests/integration/test_repositories.py`. **Integração, não mock:** asserir a
*consequência* (`added` sai certo) distingue código bom de quebrado; asserir a
ordem das chamadas com monkeypatch seria verdadeiro independente de a lógica
estar certa.

```python
async def test_conta_nova_aparece_em_added(db) -> None:
    """Se o upsert rodasse ANTES da leitura, `added` sairia sempre 0.

    `upsert_many` marca is_active=true e zera missed_syncs pra toda conta do
    MCC — lido depois dele, o inventário já parece "em dia" e a auditoria nunca
    reporta conta nova. Achado da revisão do sprint Meta, round 1.
    """
    async with db.acquire() as conn:
        resumo = await account_resync.reconcile_google(
            conn,
            accounts=[{"customer_id": "801", "mcc_id": "1", "descriptive_name": "Nova"}],
            complete=True,
            apply=False,
        )
        assert resumo["added"] == 1

        # Segunda execução: a conta já está no inventário, não é mais "nova".
        resumo = await account_resync.reconcile_google(
            conn,
            accounts=[{"customer_id": "801", "mcc_id": "1", "descriptive_name": "Nova"}],
            complete=True,
            apply=False,
        )
        assert resumo["added"] == 0


async def test_trava_desligada_nao_revoga_mas_reporta(db) -> None:
    """O dry-run tem de OBSERVAR o que a virada fará, senão o soak não serve."""
    async with db.acquire() as conn:
        mid = await _make_manager(conn, "dry@v4company.com")
        await google_ads_accounts.upsert_many(
            conn, [{"customer_id": "802", "mcc_id": "1", "descriptive_name": "Sai"}]
        )
        await manager_account_access.grant(conn, manager_id=mid, customer_id="802")
        await conn.execute(
            "UPDATE google_ads_accounts SET is_active = false WHERE customer_id = '802'"
        )

        resumo = await account_resync.reconcile_google(
            conn, accounts=[], complete=True, apply=False
        )
        assert resumo["applied"] is False
        assert resumo["revoked_grants"] == 0
        # ...MAS o dry-run tem de OBSERVAR o que a virada fará. Sem este
        # contador, o soak inteiro reporta zero e não distingue "não há o que
        # revogar" de "há 34 e a trava está segurando".
        assert resumo["revoke_candidates"] == 1
        # A linha continua VIVA — a trava governa destruição, não observação.
        assert await conn.fetchval(
            "SELECT revoked_at IS NULL FROM manager_account_access WHERE customer_id = '802'"
        )
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
python -m pytest tests/integration/test_repositories.py -v -k "added or trava_desligada"
```

Esperado: FAIL — `account_resync.reconcile_google` não existe.

- [ ] **Step 3: Implementar o repositório**

```python
async def list_inventory_rows(conn: asyncpg.Connection) -> list[InventoryRow]:
    rows = await conn.fetch(
        "SELECT customer_id, is_active, missed_syncs FROM google_ads_accounts"
    )
    return [
        InventoryRow(
            customer_id=r["customer_id"],
            is_active=r["is_active"],
            missed_syncs=r["missed_syncs"],
        )
        for r in rows
    ]


async def apply_absences(
    conn: asyncpg.Connection, *, bump: list[str], reset: list[str]
) -> None:
    if bump:
        await conn.execute(
            "UPDATE google_ads_accounts SET missed_syncs = missed_syncs + 1 "
            "WHERE customer_id = ANY($1::text[])",
            bump,
        )
    if reset:
        await conn.execute(
            "UPDATE google_ads_accounts SET missed_syncs = 0 "
            "WHERE customer_id = ANY($1::text[])",
            reset,
        )


async def deactivate(conn: asyncpg.Connection, *, customer_ids: list[str]) -> int:
    if not customer_ids:
        return 0
    result = await conn.execute(
        "UPDATE google_ads_accounts SET is_active = false "
        "WHERE customer_id = ANY($1::text[]) AND is_active = true",
        customer_ids,
    )
    return int(result.split()[-1]) if result.startswith("UPDATE") else 0
```

- [ ] **Step 4: Extrair `reconcile_google`, substituindo `mark_inactive_except`**

Função própria em `src/jobs/account_resync.py`, e não código inline no job: é o
que a torna testável contra um banco real sem subir o job inteiro.

```python
async def reconcile_google(
    conn: asyncpg.Connection,
    *,
    accounts: list[dict[str, Any]],
    complete: bool,
    apply: bool,
) -> dict[str, Any]:
    """Reconcilia o inventário Google contra o MCC. Devolve o params_summary.

    Uma transação só pro bloco de escrita inteiro: metade aplicada — carência
    somada sem desativar, ou desativada com grant vivo — é exatamente a
    inconsistência que este recurso existe pra evitar.
    """
    async with conn.transaction():
        # Ler ANTES do upsert. `upsert_many` marca is_active=true e zera
        # missed_syncs pra toda conta do MCC; lido depois dele, o inventário já
        # parece "em dia" e `to_add` sai vazio SEMPRE (revisão Meta, round 1).
        inventario = await google_ads_accounts.list_inventory_rows(conn)
        plano = build_plan(
            mcc_ids={a["customer_id"] for a in accounts},
            inventory=inventario,
            complete=complete,
        )
        n = await google_ads_accounts.upsert_many(conn, accounts)
        await google_ads_accounts.apply_absences(
            conn, bump=plano.to_bump, reset=plano.to_reset
        )

        # Contado SEMPRE, inclusive no dry-run: a trava governa DESTRUIÇÃO, não
        # observação. Sem isto o soak inteiro reporta zero e não distingue "não
        # há o que revogar" de "há 34 e a trava está segurando".
        candidatos = await manager_account_access.count_grants_on_inactive_accounts(conn)

        # Destrutivo: exige leitura completa E a trava ligada.
        # `blocked_reason is None` já implica leitura completa.
        aplicado = apply and plano.blocked_reason is None
        revogados = 0
        if aplicado:
            await google_ads_accounts.deactivate(conn, customer_ids=plano.to_remove)
            # Sobre o ESTADO, não sobre o delta desta execução: é o que cobre as
            # contas que JÁ estavam inativas (34 grants em 9 contas em
            # 2026-09-05), que nenhum `to_remove` calculado a partir de `ativos`
            # alcançaria.
            atingidos = await manager_account_access.revoke_for_inactive_accounts(conn)
            revogados = sum(len(v) for v in atingidos.values())

    return {
        "added": len(plano.to_add),
        "bumped": len(plano.to_bump),
        "removed": len(plano.to_remove),
        "reset": len(plano.to_reset),
        "revoke_candidates": candidatos,
        "revoked_grants": revogados,
        "applied": aplicado,
        "complete": complete,
        "upserted": n,
        "blocked_reason": plano.blocked_reason,
    }
```

No corpo do job, o bloco `async with pool.acquire() as conn:` passa a chamar
essa função e auditar **fora** da transação — bookkeeping não pode desfazer
reconciliação já aplicada (família do F83):

```python
        async with pool.acquire() as conn:
            resumo = await reconcile_google(
                conn,
                accounts=accounts,
                complete=inventario_ok,
                apply=settings.google_reconcile_apply,
            )
            await record_job_run(
                conn,
                operation="google_reconcile",
                platform="google",
                target_count=resumo["upserted"],
                status="success" if resumo["blocked_reason"] is None else "error",
                error_message=resumo["blocked_reason"],
                params_summary={
                    k: v for k, v in resumo.items() if k not in ("upserted", "blocked_reason")
                },
            )
```

A linha `account_resync` no `audit_log` continua sendo gravada como hoje.
`mark_inactive_except` deixa de ser chamada pelo job — **não apagar a função**:
ela segue coberta por `tests/integration/test_repositories.py:201,221` e o
`allow_full_deactivation` é caminho de emergência.

O contador novo, em `manager_account_access.py`:

```python
async def count_grants_on_inactive_accounts(conn: asyncpg.Connection) -> int:
    """Quantos grants VIVOS existem em conta inativa. Leitura pura.

    É o número que o dry-run precisa reportar para o soak significar alguma
    coisa — sem ele, `revoked_grants: 0` com a trava desligada é indistinguível
    de "não há nada a revogar".
    """
    return int(
        await conn.fetchval(
            """
            SELECT count(*)
              FROM manager_account_access m
              JOIN google_ads_accounts a ON a.customer_id = m.customer_id
             WHERE a.is_active = false AND m.revoked_at IS NULL
            """
        )
    )
```

- [ ] **Step 5: A trava, nos dois lugares**

Em `src/config.py`, ao lado de `meta_reconcile_apply`:

```python
    # Trava do rollout do lado Google, espelhando `meta_reconcile_apply`. O job
    # calcula e audita o plano sempre; só o lado destrutivo depende disto.
    google_reconcile_apply: bool = False
```

Em `.github/workflows/deploy.yml:35`, acrescentar ao `JOB_ENV_VARS`
`,GOOGLE_RECONCILE_APPLY=false` — e **também** ao `--set-env-vars` do serviço,
para os dois não divergirem. Medido em 05/09: `gcloud run jobs update` é
revertido em silêncio no push seguinte, porque o workflow reescreve a chave nos
três jobs a cada deploy.

- [ ] **Step 6: Rodar tudo**

```bash
python scripts/check_pre_push_full.py
```

Esperado: verde, e o guard `test_deploy_env_matches_settings.py` passa (ele cruza
env montado ↔ campo de `Settings` nas duas direções — o campo novo **precisa**
estar nos dois lugares).

- [ ] **Step 7: Commit**

```bash
git add src/db/repositories/google_ads_accounts.py src/jobs/account_resync.py \
        src/config.py .github/workflows/deploy.yml tests/
git commit -m "feat(jobs): reconciliacao Google com carencia, atras de trava de rollout"
```

---

## Task 6: As filas no painel

**Files:**
- Modify: `src/db/repositories/google_ads_accounts.py` (`list_queues`)
- Modify: `src/web/routes.py:961-982` (rota `/admin/accounts`) e nova rota de restaurar
- Modify: `src/web/templates/admin/accounts.html`
- Test: `tests/integration/test_repositories.py`, `tests/unit/test_frontend_responsive_guards.py`

**Interfaces:**
- Consumes: `LEFT_MCC_REASON`, `restore_for_account` (Task 3).
- Produces: `ReconcileQueues(sem_delegacao: list, voltaram_ao_mcc: list)` e
  `POST /admin/accounts/{customer_id}/restore`.

🔴 **A fila 2 NÃO chaveia em `is_active`.** É a lição C1 da revisão Meta, escrita
no docstring de `meta_ad_accounts.list_queues`: quando a conta volta ao MCC,
`upsert_many` a reativa **na mesma execução**, e é aí — e só aí — que restaurar
faz sentido, porque o gate exige conta ativa. Chavear em `is_active = false` faz
a conta sumir da fila no instante em que se torna restaurável, levando junto o
único chamador de `restore_for_account`. **A chave é ter grant revogado por churn
pendente.** Por isso o nome é `voltaram_ao_mcc`, não `sairam_do_mcc`.

- [ ] **Step 1: Escrever os testes que falham**

```python
async def test_fila_delegacao_lista_conta_ativa_sem_grant(db) -> None:
    async with db.acquire() as conn:
        await google_ads_accounts.upsert_many(
            conn, [{"customer_id": "701", "mcc_id": "1", "descriptive_name": "Nova"}]
        )
        q = await google_ads_accounts.list_queues(conn)
        assert [r["customer_id"] for r in q.sem_delegacao] == ["701"]


async def test_fila_de_restauracao_aparece_QUANDO_a_conta_VOLTA(db) -> None:
    """C1 da revisão Meta: chavear em is_active=false faz a conta sumir da fila
    exatamente quando ela se torna restaurável."""
    async with db.acquire() as conn:
        mid = await _make_manager(conn, "volta@v4company.com")
        await google_ads_accounts.upsert_many(
            conn, [{"customer_id": "702", "mcc_id": "1", "descriptive_name": "Voltou"}]
        )
        await manager_account_access.grant(conn, manager_id=mid, customer_id="702")
        await conn.execute(
            "UPDATE google_ads_accounts SET is_active = false WHERE customer_id = '702'"
        )
        await manager_account_access.revoke_for_inactive_accounts(conn)

        # Enquanto FORA do MCC: não é restaurável, o gate exige conta ativa.
        q = await google_ads_accounts.list_queues(conn)
        assert [r["customer_id"] for r in q.voltaram_ao_mcc] == []

        # Voltou ao MCC — agora sim.
        await google_ads_accounts.upsert_many(
            conn, [{"customer_id": "702", "mcc_id": "1", "descriptive_name": "Voltou"}]
        )
        q = await google_ads_accounts.list_queues(conn)
        assert [r["customer_id"] for r in q.voltaram_ao_mcc] == ["702"]
        assert [r["customer_id"] for r in q.sem_delegacao] == []  # exclusiva
```

- [ ] **Step 2: Rodar e ver falhar**

```bash
python -m pytest tests/integration/test_repositories.py -v -k "fila"
```

Esperado: FAIL (`list_queues` não existe em `google_ads_accounts`).

- [ ] **Step 3: Implementar `list_queues`**

```python
@dataclass(slots=True, frozen=True)
class ReconcileQueues:
    sem_delegacao: list[asyncpg.Record]
    voltaram_ao_mcc: list[asyncpg.Record]


async def list_queues(conn: asyncpg.Connection) -> ReconcileQueues:
    """As duas filas do painel. Cada uma é uma AÇÃO diferente do admin.

    C1 (lição do sprint Meta): a fila 2 NÃO chaveia em `is_active`. Quando a
    conta volta ao MCC, `upsert_many` a reativa na MESMA execução — e é aí, e só
    aí, que restaurar faz sentido, porque `can_manager_access` exige conta ativa.
    Com o predicado `is_active = false`, a conta sumiria da fila no instante em
    que se tornasse restaurável, e sobraria redelegar tudo à mão.

    As filas são exclusivas e `voltaram_ao_mcc` tem precedência: a conta que
    voltou satisfaz as duas (está ativa e sem grant VIVO), e sem a exclusão o
    admin seria convidado a refazer à mão o que um clique devolve.
    """
    from src.db.repositories.manager_account_access import LEFT_MCC_REASON

    voltaram = await conn.fetch(
        """
        SELECT a.customer_id, a.descriptive_name,
               count(m.manager_id) AS grants_restauraveis
          FROM google_ads_accounts a
          JOIN manager_account_access m ON m.customer_id = a.customer_id
         WHERE a.is_active = true
           AND m.revoked_at IS NOT NULL
           AND m.revoked_reason = $1
         GROUP BY a.customer_id, a.descriptive_name
         ORDER BY a.descriptive_name
        """,
        LEFT_MCC_REASON,
    )
    sem_delegacao = await conn.fetch(
        """
        SELECT a.customer_id, a.descriptive_name, a.synced_at
          FROM google_ads_accounts a
         WHERE a.is_active = true
           AND NOT EXISTS (
                 SELECT 1 FROM manager_account_access m
                  WHERE m.customer_id = a.customer_id AND m.revoked_at IS NULL)
           AND NOT EXISTS (
                 SELECT 1 FROM manager_account_access m
                  WHERE m.customer_id = a.customer_id
                    AND m.revoked_reason = $1)
         ORDER BY a.descriptive_name
        """,
        LEFT_MCC_REASON,
    )
    return ReconcileQueues(sem_delegacao=list(sem_delegacao), voltaram_ao_mcc=list(voltaram))
```

- [ ] **Step 4: Rota e template**

Na rota `/admin/accounts` (`src/web/routes.py:961`), acrescentar
`queues = await google_ads_accounts.list_queues(conn)` e passar
`sem_delegacao` / `voltaram_ao_mcc` no contexto.

Rota nova, espelhando `admin_accounts_meta_restore` (`routes.py:1017`):

```python
@router.post("/admin/accounts/{customer_id}/restore", response_class=HTMLResponse)
async def admin_accounts_google_restore(
    request: Request,
    customer_id: str,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
) -> Response:
    _require_admin(user)
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        conta = await google_ads_accounts.get_by_customer_id(conn, customer_id)
        if conta is None or not conta.is_active:
            # Restaurar em conta inativa produz grant que o gate nega — trabalho
            # inútil apresentado como sucesso.
            return RedirectResponse(
                url="/admin/accounts?error=conta_inativa", status_code=303
            )
        restaurados = await manager_account_access.restore_for_account(
            conn, customer_id=customer_id
        )
    log.info("google_access_restored", customer_id=customer_id, managers=len(restaurados))
    return RedirectResponse(url="/admin/accounts?ok=restored", status_code=303)
```

**303, não 200** — POST de mutação sem HTMX devolve 303, senão o refresh
re-executa a ação (F107).

No template, as duas filas em `<table>` dentro de
`<div class="v4-table-wrap" tabindex="0" role="region" aria-label="…">`, com
`<th scope="col">`. O botão de restaurar é `<form method="post">` com
`{{ button(..., type="submit") }}` (F49). **Zero `onclick`, zero `style=`.**

- [ ] **Step 5: Rodar tudo**

```bash
python scripts/check_pre_push_full.py
```

Esperado: verde, incluindo os 11 guards de
`tests/unit/test_frontend_responsive_guards.py`.

- [ ] **Step 6: Commit**

```bash
git add src/db/repositories/google_ads_accounts.py src/web/ tests/
git commit -m "feat(web): filas de delegacao e restauracao no painel Google"
```

---

## Task 7: O sinal do alerta e o runbook

**Files:**
- Modify: `src/jobs/account_resync.py` (um `log.warning` estruturado)
- Modify: `docs/operacao/infra-setup.md`
- Test: `tests/unit/test_account_resync.py`

**Interfaces:**
- Consumes: `list_queues` (Task 6).
- Produces: evento de log `google_accounts_sem_grant` com campo numérico
  `total`, que é sobre o que a métrica log-based é definida.

- [ ] **Step 1: Escrever o teste que falha**

Em `tests/integration/test_repositories.py`, com `structlog` capturado por
`structlog.testing.capture_logs` (o repo usa structlog, não logging padrão —
`caplog` não vê estes eventos):

```python
import structlog

async def test_avisa_quando_ha_conta_sem_grant(db) -> None:
    """A Hust App ficou dias sem grant e foi achada por ACASO, no seletor de
    contas do Google. Este log é o que a policy transforma em e-mail."""
    async with db.acquire() as conn:
        await google_ads_accounts.upsert_many(
            conn,
            [
                {"customer_id": "901", "mcc_id": "1", "descriptive_name": "Sem gestor"},
                {"customer_id": "902", "mcc_id": "1", "descriptive_name": "Tambem sem"},
            ],
        )
        with structlog.testing.capture_logs() as logs:
            await account_resync.avisar_contas_sem_grant(conn)

    evento = [e for e in logs if e["event"] == "google_accounts_sem_grant"]
    assert len(evento) == 1
    assert evento[0]["total"] == 2
    assert sorted(evento[0]["customer_ids"]) == ["901", "902"]


async def test_nao_avisa_quando_todas_tem_grant(db) -> None:
    """Alarme que aparece sempre ensina a ser ignorado."""
    async with db.acquire() as conn:
        mid = await _make_manager(conn, "tem@v4company.com")
        await google_ads_accounts.upsert_many(
            conn, [{"customer_id": "903", "mcc_id": "1", "descriptive_name": "Com gestor"}]
        )
        await manager_account_access.grant(conn, manager_id=mid, customer_id="903")
        with structlog.testing.capture_logs() as logs:
            await account_resync.avisar_contas_sem_grant(conn)

    assert [e for e in logs if e["event"] == "google_accounts_sem_grant"] == []
```

- [ ] **Step 2: Rodar e ver os dois falharem**

```bash
python -m pytest tests/unit/test_account_resync.py -v -k "sem_grant"
```

- [ ] **Step 3: Implementar**

Função própria em `src/jobs/account_resync.py`, chamada ao fim do bloco do job,
depois do `record_job_run`:

```python
async def avisar_contas_sem_grant(conn: asyncpg.Connection) -> int:
    """Emite o evento que a policy de alerta observa. Devolve quantas achou.

    `warning`, não `error`: o job fez o trabalho certo — a anomalia é do
    inventário, não da execução. Marcar como erro faria a policy de "Cloud Run
    Job failed" disparar e mascararia falha real.

    Só emite quando há o que avisar: alarme que aparece sempre ensina a ser
    ignorado (mesma razão do `aviso_cobertura` do F151).
    """
    queues = await google_ads_accounts.list_queues(conn)
    if not queues.sem_delegacao:
        return 0
    log.warning(
        "google_accounts_sem_grant",
        total=len(queues.sem_delegacao),
        customer_ids=[r["customer_id"] for r in queues.sem_delegacao],
    )
    return len(queues.sem_delegacao)
```

- [ ] **Step 4: Escrever o runbook**

Em `docs/operacao/infra-setup.md`, seção nova com o `curl` **completo** da
Monitoring API (`gcloud auth print-access-token`) para (a) criar a métrica
log-based sobre `jsonPayload.event="google_accounts_sem_grant"` e (b) criar a
policy no canal de e-mail existente.

🔴 **Escrever explicitamente que sem a policy ninguém recebe nada**, e abrir a
pendência correspondente no `estado-atual.md`. O sprint não entrega o alerta;
entrega o sinal e o procedimento.

- [ ] **Step 5: Gate e commit**

```bash
python scripts/check_pre_push.py
```

```bash
git add src/jobs/account_resync.py docs/operacao/infra-setup.md tests/
git commit -m "feat(jobs): sinal de conta sem grant, com runbook da policy"
```

---

## Task 8: Corrigir a spec e o estado-atual

**Files:**
- Modify: `docs/superpowers/specs/2026-09-05-gate-google-design.md` (§5.4, §6.1)
- Modify: `docs/operacao/estado-atual.md` (pendência 10, pendência nova do alerta)

A spec está mesclada com três linhas erradas, listadas no topo deste plano.
Documento que se contradiz é pior que documento velho — as duas leituras ficam
no repo e nada diz qual vale.

- [ ] **Step 1: Corrigir a §5.4** — o `DELETE` da linha 147 é `copy_access`, não
  offboarding; são **cinco** funções, e `copy_access` **fica** como `DELETE`,
  com o motivo escrito.
- [ ] **Step 2: Corrigir a §6.1** — a fila chaveia em **grant revogado por churn
  pendente**, não em carência nem em `is_active`; o nome é `voltaram_ao_mcc`.
- [ ] **Step 3: Atualizar o `estado-atual.md`** — pendência 10 fechada, com o
  número de grants revogados **remedido no dia**, e pendência nova aberta para
  a criação da policy de alerta.
- [ ] **Step 4: Commit**

```bash
git add docs/
git commit -m "docs: corrige tres linhas da spec do gate Google achadas na implementacao"
```

---

## Ordem de PR e o soak

1. **PR 1** = Task 1. Inerte para o usuário (os 34 grants já falham no Google).
2. **PR 2** = Tasks 2-5, com `GOOGLE_RECONCILE_APPLY=false`.
3. **Soak.** Previsão a registrar **antes** da primeira execução, para que ela
   possa falhar: as 26 ativas estão todas no MCC e todas com grant, então
   `added=0`, `bumped=0`, `removed=0`, `reset=0`, `complete=true`,
   `applied=false`, `revoked_grants=0` — e **`revoke_candidates=34`**, que é o
   único campo que prova que o dry-run está enxergando o que a virada fará.
   Qualquer outro número significa que o desenho está errado **e ninguém perdeu
   acesso**: é para isso que a trava existe.
4. **PR 3** = Tasks 6-7.
5. **Virar a trava** no `deploy.yml`, com o raio **remedido no dia** — nunca
   herdado deste plano. Esperado hoje: 34 grants em 9 contas.
6. **Criar a policy** (ação do Wellington) + Task 8.
