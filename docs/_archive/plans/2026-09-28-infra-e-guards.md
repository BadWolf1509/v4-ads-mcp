# Infra e guards — conexão validada na retirada, SQL idempotente, migrations serializadas: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** fechar o resto dos sub-projetos 3 e 4 da varredura de 21/09:
- a conexão do banco passa a ser testada na retirada do pool, cobrindo leitura e escrita num ponto só;
- revogar vira idempotente e escolher uma linha vira determinístico, com guards derivados do SQL;
- os pagers passam a recusar `limit < 1`, e o token de dry-run vence pelo relógio do banco;
- reserva e acerto de quota caem no mesmo dia, e o contador Meta passa a gravar em UTC e numa transação;
- as migrations passam a rodar serializadas por lock;
- o export CSV ganha um teto de linhas.

**Architecture:**
- **O pool:** o `init_pool` liga um `setup` (`SELECT 1`) e o `get_pool()` devolve um invólucro fino, o `PoolValidado`, que repete a RETIRADA uma vez em conexão derrubada. Nenhum dos ~100 pontos de uso muda.
- **Guards:** os dois guards de SQL varrem os literais de `src/` e cobram a propriedade de todo statement da forma.
- **O resto:** são consertos locais, cada um com teste que falha contra o código de 28/09.

**Tech Stack:** Python 3.13, asyncpg 0.31, pytest + testcontainers, structlog.

**Spec:** `docs/superpowers/specs/2026-09-28-infra-e-guards-design.md` (aprovada em 28/09).

**Como este plano foi feito:**
- O código de cada task foi escrito e executado ANTES do plano, num worktree de rascunho, uma task por commit.
- Cada commit passou no **full sweep** (`check_pre_push_full.py`: 8 passos, integração com Docker inclusive).
- Os blocos de código abaixo são o conteúdo exato daqueles commits, gerado por script, não transcrito.
- Cada "ver falhar" foi **medido** aplicando os testes da task sobre o estado da task anterior.

## Global Constraints

- **Só a RETIRADA se repete (spec §3.1):**
  - o `PoolValidado` repete `acquire` uma vez quando a retirada levanta um dos `_DROPPED_CONNECTION_ERRORS`;
  - erro dentro do corpo do `with` (a query do chamador) nunca é repetido;
  - o `run_with_reconnect` continua como está.
- **Só `src/db/connection.py` abre conexão com o banco** (`asyncpg.create_pool`/`asyncpg.connect`).
- **Revogação** (`UPDATE … SET revoked_at = now()`) sempre com `revoked_at IS NULL` no `WHERE`.
- **`ORDER BY … LIMIT 1` sobre tabela do banco** sempre termina em `id`. "Tabela do banco" é tabela criada numa migration, e isso separa o SQL da GAQL.
- **Quota:**
  - `before_call` devolve o dia UTC da reserva;
  - `record_actual` recebe esse dia no argumento obrigatório `dia=`;
  - o lado Meta usa o mesmo `_today()`.
- **Migrations:** `pg_advisory_xact_lock(_CHAVE_DO_LOCK)` no bootstrap e em cada migration, com re-checagem de `_migrations` depois do lock.
- **Export CSV:** teto de `50_000` linhas, e a query pede `teto + 1`. Passando do teto, o arquivo termina em `# v4-ads-mcp: EXPORT CORTADO em …`, nunca em "export completo".
- **Gate: full sweep em TODA task** (`python scripts/check_pre_push_full.py`, com Docker), porque cada uma mexe em SQL, transação, pool ou migration. Rode-o mudo, com o commit ENCADEADO por `&&` ao gate — **nunca** `;` nem pipe entre os dois.
- **Sabotagem se restaura de CÓPIA, nunca de `git checkout`.** Cópias e arquivos auxiliares vão para `.superpowers/` (git-ignored), nunca para a raiz do repo.
- **Commits:** mensagem pelo Git Bash (o PowerShell põe BOM), com o trailer `Co-Authored-By:` do modelo que você é.

## Arquivos

| arquivo | task | responsabilidade |
|---|---|---|
| `src/db/connection.py` | 1 | `_testa_conexao`, `_RetiradaValidada`, `PoolValidado`, `get_pool()` |
| `src/jobs/purge.py` | 1 | anotação do `pool` aceita o `PoolValidado` |
| `tests/unit/test_pool_validado.py` (novo) | 1 | retirada repetida; o corpo nunca; o `setup`; guard estrutural com controle |
| `src/db/repositories/manager_meta_account_access.py`, `google_oauth_connections.py`, `meta_oauth_connections.py`, `src/jobs/account_resync.py` | 2 | `revoked_at IS NULL` nas revogações; `id DESC` nos `LIMIT 1` |
| `tests/unit/test_sql_idempotente_e_deterministico.py` (novo), `tests/integration/test_manager_meta_account_access.py` | 2 | os dois guards derivados do SQL; revogar de novo não tira a linha do restore |
| `src/db/repositories/audit_log.py`, `src/governance/dry_run.py` | 3 | `limit < 1` recusado; expiração no `now()` do banco |
| `tests/unit/test_pagers_recusam_limite_menor_que_um.py` (novo), `tests/integration/test_dry_run.py` | 3 | recusa antes do banco; token vencido com o relógio da app atrasado |
| `src/governance/rate_limit.py` + os 5 executores (`conversions.py`, `customer_match.py`, `mutations.py`, `reports.py`, `validate_gaql.py`) | 4 | o dia da reserva viaja até o acerto; o Meta em UTC e numa transação |
| `tests/integration/test_rate_limit.py`, `tests/unit/test_meta_buc_registro.py` | 4 | a virada do dia; a transação; o dia UTC; a assinatura nova nos testes antigos |
| `src/db/migrate.py`, `tests/integration/test_migrations.py` | 5 | o lock; duas execuções concorrentes num banco vazio |
| `src/db/repositories/audit_log.py`, `tests/unit/test_export_csv_tem_teto_de_linhas.py` (novo) | 6 | o teto, a sentinela e a marca de corte |
| `docs/...` (estado-atual, destino dos achados de 21/09, a spec) | 7 | por script |

**Como aplicar um bloco `diff`:** salve o bloco inteiro (sem as cercas) em `.superpowers/infra-tN-<nome>.diff` e rode `git apply --check <arquivo>` e depois `git apply <arquivo>`. Um bloco que não aplica é um desvio do estado esperado — **pare e reporte**, não edite à mão.

**Integração precisa de Docker** (testcontainers). Sem engine, os passos de integração não rodam — diga isso, não escreva "passou".

---

### Task 1: A conexão é testada na retirada do pool

**Files:**
- Create: `tests/unit/test_pool_validado.py`
- Modify: `src/db/connection.py`, `src/jobs/purge.py`

**Interfaces:**
- Produces:
  - `async def _testa_conexao(conn: asyncpg.Connection) -> None`, que roda `SELECT 1`;
  - `class PoolValidado`, com `acquire() -> _RetiradaValidada` e `async close() -> None`;
  - `get_pool() -> PoolValidado`, que embrulha o `_pool` a cada chamada, e por isso os testes que trocam `connection._pool` por um pool falso passam pelo invólucro;
  - o `init_pool` passa `setup=_testa_conexao` ao `asyncpg.create_pool`.
- Consome o protocolo de gerenciador de contexto da retirada (`__aenter__`/`__aexit__`), não `await pool.acquire()`: os ~20 pools falsos dos testes existentes devolvem um gerenciador de contexto, não um awaitable.

- [ ] **Step 1: Escrever o teste** — `tests/unit/test_pool_validado.py`, conteúdo exato:

```python
"""A conexão é testada na retirada do pool, e a retirada se repete uma vez (spec 2026-09-28 §3.1).

O pool do asyncpg não testa a conexão antes de entregá-la (F76): o Supabase fecha o
socket ocioso e a primeira query estoura. O `run_with_reconnect` só cobre leitura — o F91
proíbe repetir escrita às cegas — e cobria só quem se lembrou de usá-lo: 9 leituras no
caminho quente ficaram de fora (varredura de 21/09, 05#2, conferido em 28/09).

Agora o `init_pool` passa `setup=_testa_conexao` (um `SELECT 1` a cada retirada) e o
`get_pool()` devolve o `PoolValidado`, que repete a RETIRADA uma vez quando o teste falha
por conexão derrubada. A repetição acontece antes de o chamador receber a conexão: nenhum
comando dele rodou, então nada é repetido — leitura e escrita ficam cobertas por um lugar só.
"""

from __future__ import annotations

import ast
from typing import Any

import asyncpg
import pytest

from src.db import connection
from tests.unit import _guard_harness as h


class _Retirada:
    """O gerenciador de contexto que `pool.acquire()` devolve — o protocolo que os fakes
    dos testes existentes também usam (não é awaitable)."""

    def __init__(self, efeito: object) -> None:
        self._efeito = efeito
        self.soltou = False

    async def __aenter__(self) -> object:
        if isinstance(self._efeito, BaseException):
            raise self._efeito
        return self._efeito

    async def __aexit__(self, *exc: object) -> bool:
        self.soltou = True
        return False


class _PoolFalso:
    def __init__(self, efeitos: list[object]) -> None:
        self._efeitos = efeitos
        self.retiradas: list[_Retirada] = []

    def acquire(self) -> _Retirada:
        r = _Retirada(self._efeitos[len(self.retiradas)])
        self.retiradas.append(r)
        return r


def _derrubada() -> asyncpg.exceptions.ConnectionDoesNotExistError:
    return asyncpg.exceptions.ConnectionDoesNotExistError(
        "connection was closed in the middle of operation"
    )


async def test_retirada_repete_uma_vez_quando_o_teste_de_conexao_falha(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    viva = object()
    pool = _PoolFalso([_derrubada(), viva])
    monkeypatch.setattr(connection, "_pool", pool)
    corpo = 0

    async with connection.get_pool().acquire() as conn:
        corpo += 1
        assert conn is viva

    assert len(pool.retiradas) == 2
    assert corpo == 1
    assert pool.retiradas[1].soltou


async def test_erro_que_nao_e_de_conexao_derrubada_nao_repete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool = _PoolFalso([ValueError("outra coisa"), object()])
    monkeypatch.setattr(connection, "_pool", pool)

    with pytest.raises(ValueError, match="outra coisa"):
        async with connection.get_pool().acquire():
            pass

    assert len(pool.retiradas) == 1


async def test_duas_falhas_seguidas_repassam_o_erro(monkeypatch: pytest.MonkeyPatch) -> None:
    pool = _PoolFalso([_derrubada(), ConnectionResetError(104, "reset"), object()])
    monkeypatch.setattr(connection, "_pool", pool)

    with pytest.raises(ConnectionError):
        async with connection.get_pool().acquire():
            pass

    assert len(pool.retiradas) == 2


async def test_erro_dentro_do_corpo_nao_repete_nada(monkeypatch: pytest.MonkeyPatch) -> None:
    """A escrita que falha DEPOIS da retirada não é repetida: o invólucro só repete a retirada."""
    pool = _PoolFalso([object(), object()])
    monkeypatch.setattr(connection, "_pool", pool)
    corpo = 0

    with pytest.raises(asyncpg.exceptions.ConnectionDoesNotExistError):
        async with connection.get_pool().acquire():
            corpo += 1
            raise _derrubada()

    assert len(pool.retiradas) == 1
    assert corpo == 1
    assert pool.retiradas[0].soltou


async def test_init_pool_liga_o_teste_de_conexao(monkeypatch: pytest.MonkeyPatch) -> None:
    capturado: dict[str, Any] = {}

    async def create_pool_falso(**kwargs: Any) -> object:
        capturado.update(kwargs)
        return object()

    monkeypatch.setattr(connection.asyncpg, "create_pool", create_pool_falso)
    monkeypatch.setattr(connection, "_pool", None)

    await connection.init_pool("postgresql://ignored")

    assert capturado["setup"] is connection._testa_conexao
    executado: list[str] = []

    class _Conn:
        async def execute(self, sql: str) -> str:
            executado.append(sql)
            return "SELECT 1"

    await connection._testa_conexao(_Conn())  # type: ignore[arg-type]
    assert executado == ["SELECT 1"]


def test_get_pool_devolve_o_pool_validado(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(connection, "_pool", _PoolFalso([]))
    assert isinstance(connection.get_pool(), connection.PoolValidado)


_ABRE_CONEXAO = {"asyncpg.create_pool", "asyncpg.connect"}


def _quem_abre_conexao_fora_do_pool() -> list[str]:
    ofensores = []
    for arquivo in h.fontes_py(h.SRC):
        if h.rel(arquivo) == "src/db/connection.py":
            continue
        arv = h.arvore(arquivo)
        origens = h.origens_de_import(arv)
        for no in ast.walk(arv):
            if isinstance(no, ast.Call) and h.caminho_canonico(no.func, origens) in _ABRE_CONEXAO:
                ofensores.append(f"{h.rel(arquivo)}:{no.lineno}")
    return ofensores


def test_so_o_connection_abre_conexao_com_o_banco() -> None:
    """Quem abre conexão fora de `connection.py` escapa do teste na retirada."""
    ofensores = _quem_abre_conexao_fora_do_pool()
    assert not ofensores, (
        f"conexão aberta fora de src/db/connection.py: {ofensores}. Use connection.get_pool() — "
        "a conexão tirada dali é testada antes de ser entregue (spec 2026-09-28 §3.1)."
    )


def test_o_scan_de_conexao_ve_as_duas_formas(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Controle: o scan acha `asyncpg.connect(...)` e `from asyncpg import create_pool`."""
    pasta = tmp_path.resolve() / "src"
    pasta.mkdir()
    (pasta / "a.py").write_text("import asyncpg\nasync def f():\n    await asyncpg.connect('x')\n")
    (pasta / "b.py").write_text(
        "from asyncpg import create_pool as cp\nasync def g():\n    await cp(dsn='x')\n"
    )
    monkeypatch.setattr(h, "SRC", pasta)
    monkeypatch.setattr(h, "RAIZ", tmp_path.resolve())
    assert sorted(_quem_abre_conexao_fora_do_pool()) == ["src/a.py:3", "src/b.py:3"]
```

- [ ] **Step 2: Ver falhar**

Run: `python -m pytest tests/unit/test_pool_validado.py -p no:cacheprovider`
Expected (medido): `4 failed, 4 passed in 5.60s` — `E AttributeError: module 'src.db.connection' has no attribute 'PoolValidado'` / `E KeyError: 'setup'` / `E asyncpg.exceptions.ConnectionDoesNotExistError: connection was closed in the middle of operation`

Os 4 que passam antes do conserto são esperados:
- dois de não-regressão: o erro que não é de conexão não se repete, e o erro no corpo não se repete;
- o guard estrutural, que hoje não tem ofensor;
- o controle dele, que prova que o scan acha as duas formas.

- [ ] **Step 3: Implementar** — aplique os dois blocos:

```diff
diff --git a/src/db/connection.py b/src/db/connection.py
index f8f7988..665721f 100644
--- a/src/db/connection.py
+++ b/src/db/connection.py
@@ -1,6 +1,8 @@
 """asyncpg connection pool factory."""
 
 from collections.abc import AsyncIterator, Awaitable, Callable
+from types import TracebackType
+from typing import Any
 
 import asyncpg
 import structlog
@@ -23,6 +25,70 @@ _DROPPED_CONNECTION_ERRORS: tuple[type[BaseException], ...] = (
 )
 
 
+async def _testa_conexao(conn: asyncpg.Connection) -> None:
+    """`setup` do pool: roda a cada retirada, antes de a conexão chegar ao chamador.
+
+    O asyncpg não testa a conexão ociosa (F76), e o Supabase fecha o socket: sem isto, a
+    primeira query do chamador é quem descobre. Se o `SELECT 1` falha, o asyncpg fecha a
+    conexão e repassa o erro; o `PoolValidado` então retira de novo, e a próxima retirada
+    reconecta (spec 2026-09-28 §3.1).
+    """
+    await conn.execute("SELECT 1")
+
+
+class _RetiradaValidada:
+    """`async with pool.acquire() as conn`, com a retirada repetida uma vez.
+
+    Usa o protocolo de gerenciador de contexto da retirada do asyncpg (e dos fakes dos
+    testes), não `await pool.acquire()`. Só a RETIRADA é repetida: um erro dentro do corpo
+    do `with` — a query do chamador — sobe sem repetição, então escrita nunca roda duas vezes.
+    """
+
+    def __init__(self, pool: Any) -> None:
+        self._pool = pool
+        self._retirada: Any = None
+
+    async def __aenter__(self) -> asyncpg.Connection:
+        for tentativa in (1, 2):
+            retirada = self._pool.acquire()
+            try:
+                conn = await retirada.__aenter__()
+            except _DROPPED_CONNECTION_ERRORS as exc:
+                if tentativa == 2:
+                    raise
+                log.warning("db_conexao_testada_reconectou", error=str(exc))
+                continue
+            self._retirada = retirada
+            return conn
+        raise AssertionError("inalcançável: a 2ª tentativa devolve ou levanta")
+
+    async def __aexit__(
+        self,
+        exc_type: type[BaseException] | None,
+        exc: BaseException | None,
+        tb: TracebackType | None,
+    ) -> bool | None:
+        return await self._retirada.__aexit__(exc_type, exc, tb)  # type: ignore[no-any-return]
+
+
+class PoolValidado:
+    """O pool que `get_pool()` devolve: a conexão é testada na retirada (spec 2026-09-28 §3.1).
+
+    `src/` só usa `acquire()`; `close()` é do ciclo de vida. Nada mais é exposto, de
+    propósito: um atalho do asyncpg (`pool.fetch`, `pool.execute`) retiraria por dentro,
+    sem a repetição.
+    """
+
+    def __init__(self, pool: Any) -> None:
+        self._pool = pool
+
+    def acquire(self) -> _RetiradaValidada:
+        return _RetiradaValidada(self._pool)
+
+    async def close(self) -> None:
+        await self._pool.close()
+
+
 # F92 — defaults conservadores do pool. Ver docstring de init_pool pra conta
 # (instâncias × pool ≤ teto do banco). Settings espelha estes valores pro caminho
 # que serve tráfego; um teste garante que os dois não divergem.
@@ -58,6 +124,7 @@ async def init_pool(
         max_size=max_size,
         command_timeout=30,
         max_inactive_connection_lifetime=_MAX_INACTIVE_CONNECTION_LIFETIME,
+        setup=_testa_conexao,
     )
     log.info("db_pool_created", min_size=min_size, max_size=max_size)
     return _pool
@@ -73,11 +140,11 @@ async def close_pool() -> None:
     log.info("db_pool_closed")
 
 
-def get_pool() -> asyncpg.Pool:
-    """Get the global pool. Raises if init_pool was not called."""
+def get_pool() -> PoolValidado:
+    """O pool global, com a conexão testada na retirada. Levanta se `init_pool` não rodou."""
     if _pool is None:
         raise RuntimeError("DB pool not initialized; call init_pool() first")
-    return _pool
+    return PoolValidado(_pool)
 
 
 async def acquire() -> AsyncIterator[asyncpg.Connection]:
```

```diff
diff --git a/src/jobs/purge.py b/src/jobs/purge.py
index acdfb93..28e1db6 100644
--- a/src/jobs/purge.py
+++ b/src/jobs/purge.py
@@ -7,8 +7,10 @@ purge não deve derrubar o job de resync.
 
 import asyncpg
 
+from src.db.connection import PoolValidado
 
-async def purge_expired(pool: asyncpg.Pool) -> dict[str, int]:
+
+async def purge_expired(pool: PoolValidado | asyncpg.Pool) -> dict[str, int]:
     """Purga rows expiradas/antigas. Retorna contagem de rows deletadas por tabela.
 
     - pending_confirmations: expires_at < now() - 7 dias (consumidas ou não —
```

- [ ] **Step 4: Ver passar**

Run: `python -m pytest tests/unit/test_pool_validado.py tests/unit/test_db_connection.py tests/unit/test_health_resilience.py tests/unit/test_health_reporta_o_registry.py tests/unit/test_pool_sizing.py -p no:cacheprovider`
Expected: `22 passed in 5.08s`

- [ ] **Step 5: Gate e commit** (o commit só roda se o gate passar):

```bash
python scripts/check_pre_push_full.py > .superpowers/gate-infra-t1.log 2>&1 && git add src/db/connection.py src/jobs/purge.py tests/unit/test_pool_validado.py && git commit -F .superpowers/msg-infra-t1.txt
```

Mensagem (`.superpowers/msg-infra-t1.txt`): `fix(db): a conexao e testada na retirada do pool (infra e guards, parte 1)` + linha em branco + o trailer.

---

### Task 2: Revogar é idempotente e escolher uma linha desempata por `id`

**Files:**
- Create: `tests/unit/test_sql_idempotente_e_deterministico.py`
- Modify: `tests/integration/test_manager_meta_account_access.py`, `src/db/repositories/manager_meta_account_access.py`, `src/db/repositories/google_oauth_connections.py`, `src/db/repositories/meta_oauth_connections.py`, `src/jobs/account_resync.py`

**Interfaces:**
- Não muda assinatura nenhuma: só o SQL de três `revoke` e de três `ORDER BY … LIMIT 1`.
- O guard deriva "tabela do banco" das migrations (`CREATE TABLE`).
- Os pisos foram medidos em 28/09: 9 revogações em `src/` e 3 escolhas de uma linha.

- [ ] **Step 1: Escrever os testes** — `tests/unit/test_sql_idempotente_e_deterministico.py`, conteúdo exato:

```python
"""Revogar é idempotente e escolher uma linha é determinístico (spec 2026-09-28 §3.2, itens 1 e 2).

Os dois guards são derivados do SQL, não de uma lista de funções — a mesma técnica do
guard do escritor único (F197): varrem os literais de string de `src/` e cobram a
propriedade de todo statement da forma, inclusive do próximo que alguém escrever.

1. **Revogar só pega linha viva.** Todo `UPDATE … SET revoked_at = now()` tem
   `revoked_at IS NULL` no `WHERE`. Sem ele, revogar de novo re-carimba a linha: no
   `manager_meta_account_access`, com outro motivo, ela ficaria fora do
   `restore_for_account` (que filtra por `revoked_reason`) sem ninguém ver. Medido em
   28/09: 9 revogações em `src/`, 3 sem o predicado (a Meta manual e as duas das conexões
   OAuth). O `restore`, que grava `revoked_at = NULL`, fica fora por definição.
2. **Escolher uma linha desempata por `id`.** Todo `ORDER BY … LIMIT 1` sobre tabela do
   nosso banco tem `id` como última chave. `ORDER BY connected_at DESC LIMIT 1` com duas
   conexões vivas no mesmo instante escolhia a credencial de forma arbitrária. Tabela "do
   nosso banco" = criada numa migration: é o que separa o SQL da GAQL (`change_event`,
   `campaign`), cujo `LIMIT 1` lê um valor, não escolhe linha.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from tests.unit import _guard_harness as h

_MIGRATIONS = h.SRC / "db" / "migrations"

# Exceções à regra do desempate: {(tabela, coluna final): a constraint UNIQUE que a garante}.
_DESEMPATE_POR_CHAVE_UNICA: dict[tuple[str, str], str] = {}

_REVOGA = re.compile(r"\bUPDATE\s+(\w+)\b.*?\bSET\b.*?\brevoked_at\s*=\s*now\(\)", re.I | re.S)
_SO_LINHA_VIVA = re.compile(r"\bWHERE\b.*\b(?:\w+\.)?revoked_at\s+IS\s+NULL\b", re.I | re.S)
_ESCOLHE_UMA = re.compile(r"\bFROM\s+(\w+)\b.*?\bORDER\s+BY\s+(.+?)\s+LIMIT\s+1\b", re.I | re.S)


def _texto(no: ast.AST) -> str | None:
    if isinstance(no, ast.Constant) and isinstance(no.value, str):
        return no.value
    if isinstance(no, ast.JoinedStr):
        return "".join(v.value if isinstance(v, ast.Constant) else "{}" for v in no.values)
    return None


def _literais(raiz: Path) -> list[tuple[str, str]]:
    achados = []
    for arquivo in h.fontes_py(raiz):
        for no in ast.walk(h.arvore(arquivo)):
            texto = _texto(no)
            if texto is not None:
                achados.append((f"{h.rel(arquivo)}:{no.lineno}", texto))  # type: ignore[attr-defined]
    return achados


def _tabelas_do_banco(pasta: Path) -> set[str]:
    return {
        m.group(1).lower()
        for arq in sorted(pasta.glob("*.sql"))
        for m in re.finditer(
            r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)",
            arq.read_text(encoding="utf-8"),
            re.I,
        )
    }


def _revogacoes(literais: list[tuple[str, str]]) -> list[tuple[str, str]]:
    return [(onde, t) for onde, t in literais if _REVOGA.search(t)]


def _revogacoes_sem_predicado(literais: list[tuple[str, str]]) -> list[str]:
    return [onde for onde, t in _revogacoes(literais) if not _SO_LINHA_VIVA.search(t)]


def _ultima_chave(order_by: str) -> str:
    ultima = order_by.split(",")[-1].strip()
    ultima = re.sub(r"\s+(ASC|DESC)\b.*$|\s+NULLS\s+(FIRST|LAST)$", "", ultima, flags=re.I)
    return ultima.split(".")[-1].strip().lower()


def _escolhas_de_uma_linha(
    literais: list[tuple[str, str]], tabelas: set[str]
) -> list[tuple[str, str, str]]:
    achadas = []
    for onde, t in literais:
        m = _ESCOLHE_UMA.search(t)
        if m and m.group(1).lower() in tabelas:
            achadas.append((onde, m.group(1).lower(), _ultima_chave(m.group(2))))
    return achadas


def _escolhas_sem_desempate(literais: list[tuple[str, str]], tabelas: set[str]) -> list[str]:
    return [
        f"{onde} ({tabela}, termina em {chave!r})"
        for onde, tabela, chave in _escolhas_de_uma_linha(literais, tabelas)
        if chave != "id" and (tabela, chave) not in _DESEMPATE_POR_CHAVE_UNICA
    ]


def test_toda_revogacao_so_pega_linha_viva() -> None:
    literais = _literais(h.SRC)
    populacao = _revogacoes(literais)
    assert len(populacao) >= 9, (
        f"piso medido em 28/09: 9 revogações em src/; achou {len(populacao)} — "
        "o casador parou de casar?"
    )
    faltam = _revogacoes_sem_predicado(literais)
    assert not faltam, (
        f"revogação sem `revoked_at IS NULL` no WHERE: {faltam}. Revogar de novo re-carimba "
        "a linha (e, com outro motivo, a tira do restore) — spec 2026-09-28 §3.2.1."
    )


def test_toda_escolha_de_uma_linha_desempata_por_id() -> None:
    tabelas = _tabelas_do_banco(_MIGRATIONS)
    assert {"google_oauth_connections", "meta_oauth_connections", "audit_log"} <= tabelas
    literais = _literais(h.SRC)
    populacao = _escolhas_de_uma_linha(literais, tabelas)
    assert len(populacao) >= 3, (
        f"piso medido em 28/09: 3 `ORDER BY … LIMIT 1` sobre tabela do banco; achou "
        f"{len(populacao)}"
    )
    faltam = _escolhas_sem_desempate(literais, tabelas)
    assert not faltam, (
        f"`ORDER BY … LIMIT 1` sem `id` como última chave: {faltam}. Empate na ordenação "
        "escolhe a linha de forma arbitrária — spec 2026-09-28 §3.2.2."
    )


def test_os_casadores_veem_o_que_devem_e_so_isso() -> None:
    """Controle positivo e negativo dos dois casadores."""
    literais = [
        ("sem", "UPDATE x SET revoked_at = now() WHERE id = $1"),
        ("com", "UPDATE x SET revoked_at = now() WHERE id = $1 AND revoked_at IS NULL"),
        ("alias", "UPDATE x m SET revoked_at = now() FROM y WHERE m.revoked_at IS NULL"),
        ("restore", "UPDATE x SET revoked_at = NULL WHERE revoked_at IS NOT NULL"),
    ]
    assert [o for o, _ in _revogacoes(literais)] == ["sem", "com", "alias"]
    assert _revogacoes_sem_predicado(literais) == ["sem"]

    tabelas = {"conexoes"}
    escolhas = [
        ("empate", "SELECT * FROM conexoes WHERE a = $1 ORDER BY criado DESC LIMIT 1"),
        ("ok", "SELECT * FROM conexoes ORDER BY criado DESC, id DESC LIMIT 1"),
        ("gaql", "SELECT change_event.t FROM change_event ORDER BY change_event.t DESC LIMIT 1"),
        ("dez", "SELECT * FROM conexoes ORDER BY criado DESC LIMIT 10"),
    ]
    assert _escolhas_sem_desempate(escolhas, tabelas) == ["empate (conexoes, termina em 'criado')"]
```

E aplique o teste de integração:

```diff
diff --git a/tests/integration/test_manager_meta_account_access.py b/tests/integration/test_manager_meta_account_access.py
index ff82606..c668568 100644
--- a/tests/integration/test_manager_meta_account_access.py
+++ b/tests/integration/test_manager_meta_account_access.py
@@ -105,3 +105,44 @@ async def test_bulk_grant_continua_limpando_a_revogacao(db) -> None:
         )
         assert linha["revoked_at"] is None, "a revogacao deveria ter sido limpa"
         assert linha["access_level"] == "write"
+
+
+@pytest.mark.integration
+async def test_revogar_de_novo_nao_tira_a_linha_do_restore(db) -> None:
+    """Spec 2026-09-28 §3.2.1: o `revoke` manual só pega linha viva.
+
+    Sem `AND revoked_at IS NULL`, revogar de novo uma linha que o churn já revogou
+    re-carimba o motivo: `partnership_ended` vira `manual`, e o `restore_for_account` —
+    que filtra por esse motivo — deixa de devolver o acesso quando a parceria volta.
+    """
+    async with db.acquire() as conn:
+        manager_id = await _make_manager(conn, "mrevoga2x@v4company.com")
+        await _make_account(conn, "act_3333333333")
+        await manager_meta_account_access.grant(
+            conn,
+            manager_id=manager_id,
+            ad_account_id="act_3333333333",
+            access_level="write",
+            granted_by=manager_id,
+        )
+        await manager_meta_account_access.revoke_for_account(
+            conn,
+            ad_account_id="act_3333333333",
+            reason=manager_meta_account_access.PARTNERSHIP_ENDED_REASON,
+        )
+
+        await manager_meta_account_access.revoke(
+            conn, manager_id=manager_id, ad_account_id="act_3333333333", reason="manual"
+        )
+
+        motivo = await conn.fetchval(
+            "SELECT revoked_reason FROM manager_meta_account_access "
+            " WHERE manager_id = $1 AND ad_account_id = $2",
+            manager_id,
+            "act_3333333333",
+        )
+        assert motivo == manager_meta_account_access.PARTNERSHIP_ENDED_REASON
+        restauradas = await manager_meta_account_access.restore_for_account(
+            conn, ad_account_id="act_3333333333"
+        )
+        assert restauradas == 1
```

- [ ] **Step 2: Ver falhar**

Run: `python -m pytest tests/unit/test_sql_idempotente_e_deterministico.py tests/integration/test_manager_meta_account_access.py -p no:cacheprovider`
Expected (medido): `3 failed, 3 passed in 9.92s` — `E AssertionError: 'ORDER BY … LIMIT 1' sem 'id' como última chave: ["src/db/repositories/google_oauth_connections.py:68 (google_oauth_connections, termina em 'connected_a` / `E AssertionError: assert 'manual' == 'partnership_ended'` / `E AssertionError: revogação sem 'revoked_at IS NULL' no WHERE: ['src/db/repositories/google_oauth_connections.py:81', 'src/db/repositories/manager_meta_account_access.py:` / `E assert not ["src/db/repositories/google_oauth_connections.py:68 (google_oauth_connections, termina em 'connected_at')", "src/db/r...ns, termina em 'connected_at')", "sr`

Os dois guards listam exatamente:
- os 3 `revoke` sem o predicado: `google_oauth_connections.py`, `manager_meta_account_access.py` e `meta_oauth_connections.py`;
- os 3 `ORDER BY connected_at DESC LIMIT 1`: os dois `get_active_for_manager` e o `account_resync.py:58`.

O teste de integração cai porque o motivo vira `manual`.

- [ ] **Step 3: Implementar** — aplique os quatro blocos:

```diff
diff --git a/src/db/repositories/manager_meta_account_access.py b/src/db/repositories/manager_meta_account_access.py
index dcaf09a..3e9d28b 100644
--- a/src/db/repositories/manager_meta_account_access.py
+++ b/src/db/repositories/manager_meta_account_access.py
@@ -104,12 +104,16 @@ async def revoke(
 
     Era DELETE. Curadoria de acesso é trabalho humano — apagar a linha perderia
     quem tinha acesso quando a parceria (ou o gestor) volta.
+
+    Só pega linha viva (spec 2026-09-28 §3.2.1): revogar de novo uma linha que o churn
+    já revogou trocaria `partnership_ended` pelo motivo novo, e o `restore_for_account`
+    deixaria de devolvê-la quando a parceria voltasse.
     """
     await conn.execute(
         """
         UPDATE manager_meta_account_access
            SET revoked_at = now(), revoked_reason = $3
-         WHERE manager_id = $1 AND ad_account_id = $2
+         WHERE manager_id = $1 AND ad_account_id = $2 AND revoked_at IS NULL
         """,
         manager_id,
         ad_account_id,
```

```diff
diff --git a/src/db/repositories/google_oauth_connections.py b/src/db/repositories/google_oauth_connections.py
index d3df43c..f1c9629 100644
--- a/src/db/repositories/google_oauth_connections.py
+++ b/src/db/repositories/google_oauth_connections.py
@@ -68,7 +68,7 @@ async def get_active_for_manager(
         """
         SELECT * FROM google_oauth_connections
         WHERE manager_id = $1 AND revoked_at IS NULL
-        ORDER BY connected_at DESC
+        ORDER BY connected_at DESC, id DESC
         LIMIT 1
         """,
         manager_id,
@@ -78,6 +78,6 @@ async def get_active_for_manager(
 
 async def revoke(conn: asyncpg.Connection, connection_id: UUID) -> None:
     await conn.execute(
-        "UPDATE google_oauth_connections SET revoked_at = now() WHERE id = $1",
+        "UPDATE google_oauth_connections SET revoked_at = now() WHERE id = $1 AND revoked_at IS NULL",
         connection_id,
     )
```

```diff
diff --git a/src/db/repositories/meta_oauth_connections.py b/src/db/repositories/meta_oauth_connections.py
index ad773c3..c726ae3 100644
--- a/src/db/repositories/meta_oauth_connections.py
+++ b/src/db/repositories/meta_oauth_connections.py
@@ -83,7 +83,7 @@ async def get_active_for_manager(
         """
         SELECT * FROM meta_oauth_connections
         WHERE manager_id = $1 AND revoked_at IS NULL
-        ORDER BY connected_at DESC
+        ORDER BY connected_at DESC, id DESC
         LIMIT 1
         """,
         manager_id,
@@ -93,6 +93,6 @@ async def get_active_for_manager(
 
 async def revoke(conn: asyncpg.Connection, connection_id: UUID) -> None:
     await conn.execute(
-        "UPDATE meta_oauth_connections SET revoked_at = now() WHERE id = $1",
+        "UPDATE meta_oauth_connections SET revoked_at = now() WHERE id = $1 AND revoked_at IS NULL",
         connection_id,
     )
```

```diff
diff --git a/src/jobs/account_resync.py b/src/jobs/account_resync.py
index a995d2d..6f8d03d 100644
--- a/src/jobs/account_resync.py
+++ b/src/jobs/account_resync.py
@@ -55,7 +55,8 @@ async def _pick_oauth_connection(conn: asyncpg.Connection) -> tuple[Any, Any]:
 
     # Fallback: any active connection.
     row = await conn.fetchrow(
-        "SELECT manager_id FROM google_oauth_connections WHERE revoked_at IS NULL ORDER BY connected_at DESC LIMIT 1"
+        "SELECT manager_id FROM google_oauth_connections WHERE revoked_at IS NULL"
+        " ORDER BY connected_at DESC, id DESC LIMIT 1"
     )
     if row is None:
         return None, None
```

- [ ] **Step 4: Ver passar**

Run: `python -m pytest tests/unit/test_sql_idempotente_e_deterministico.py tests/integration/test_manager_meta_account_access.py -p no:cacheprovider`
Expected: `6 passed in 8.48s`

- [ ] **Step 5: Gate e commit**

```bash
python scripts/check_pre_push_full.py > .superpowers/gate-infra-t2.log 2>&1 && git add src/db/repositories/manager_meta_account_access.py src/db/repositories/google_oauth_connections.py src/db/repositories/meta_oauth_connections.py src/jobs/account_resync.py tests/unit/test_sql_idempotente_e_deterministico.py tests/integration/test_manager_meta_account_access.py && git commit -F .superpowers/msg-infra-t2.txt
```

Mensagem: `fix(db): revogar e idempotente e escolher uma linha desempata por id (infra e guards, parte 2)` + trailer.

---

### Task 3: Os pagers recusam `limit < 1` e o token de dry-run vence pelo relógio do banco

**Files:**
- Create: `tests/unit/test_pagers_recusam_limite_menor_que_um.py`
- Modify: `tests/integration/test_dry_run.py`, `src/db/repositories/audit_log.py`, `src/governance/dry_run.py`

**Interfaces:**
- Produces: `_recusa_limite_menor_que_um(limit: int) -> None`, em `audit_log.py`, chamado na entrada de `list_page_for_manager` e `list_page_admin`.
- O `SELECT … FOR UPDATE` do `consume` passa a trazer `expires_at < now() AS expirado`, e o `dry_run.py` deixa de importar `datetime`.

- [ ] **Step 1: Escrever os testes** — `tests/unit/test_pagers_recusam_limite_menor_que_um.py`, conteúdo exato:

```python
"""Os pagers keyset do audit recusam `limit < 1` na entrada (spec 2026-09-28 §3.2.3).

Com `limit=0` e uma linha no filtro, a consulta interna (`LIMIT limit + 1`) devolve uma
linha, a página fica vazia, `len(fetched) > limit` é verdadeiro e o `page[-1]` estoura
`IndexError`. As rotas fixam 50 hoje; a função pública não impedia o próximo chamador.
A recusa vem ANTES de tocar no banco — a conexão abaixo explode se for usada.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from src.db.repositories import audit_log


class _ConexaoIntocavel:
    def __getattr__(self, nome: str) -> Any:
        raise AssertionError(f"a recusa tinha de vir antes do banco; usou conn.{nome}")


@pytest.mark.parametrize("limit", [0, -1])
async def test_pagina_do_gestor_recusa_limite_menor_que_um(limit: int) -> None:
    with pytest.raises(ValueError, match="limit"):
        await audit_log.list_page_for_manager(
            _ConexaoIntocavel(),  # type: ignore[arg-type]
            manager_id=uuid4(),
            limit=limit,
        )


@pytest.mark.parametrize("limit", [0, -1])
async def test_pagina_do_admin_recusa_limite_menor_que_um(limit: int) -> None:
    with pytest.raises(ValueError, match="limit"):
        await audit_log.list_page_admin(_ConexaoIntocavel(), limit=limit)  # type: ignore[arg-type]
```

E aplique o teste de integração:

```diff
diff --git a/tests/integration/test_dry_run.py b/tests/integration/test_dry_run.py
index 025dbb0..1b85981 100644
--- a/tests/integration/test_dry_run.py
+++ b/tests/integration/test_dry_run.py
@@ -199,3 +199,40 @@ async def test_pendencia_e_trilha_vivem_ou_morrem_juntas(db, session_id) -> None
             "SELECT count(*) FROM pending_confirmations WHERE session_id = $1", sid
         )
     assert pendentes == 0, "token ficou de pe sem linha de auditoria — e o proprio F148"
+
+
+@pytest.mark.integration
+async def test_token_vence_pelo_relogio_do_banco(db, session_id, monkeypatch) -> None:
+    """Spec 2026-09-28 §3.2.5: o prazo é gravado com o `now()` do banco, e é com ele que
+    se decide. Com o relógio da app atrasado (Cloud Run e Supabase são hosts diferentes),
+    comparar `expires_at` com `datetime.now()` da app aceitava um token já vencido."""
+    from datetime import UTC
+    from datetime import datetime as _datetime
+
+    class _RelogioAtrasado(_datetime):
+        @classmethod
+        def now(cls, tz=None):  # type: ignore[no-untyped-def, override]
+            return _datetime(2020, 1, 1, tzinfo=UTC)
+
+    sid, mid = session_id
+    with patch("src.governance.dry_run.ensure_account_access", AsyncMock(return_value=None)):
+        async with db.acquire() as conn:
+            token = await create_pending(
+                conn,
+                manager_id=mid,
+                session_id=sid,
+                customer_id="1234567890",
+                operation_type="update_campaign_budget",
+                payload={},
+                blast_summary="...",
+            )
+            await conn.execute(
+                "UPDATE pending_confirmations SET expires_at = now() - interval '1 minute' "
+                "WHERE token = $1",
+                token,
+            )
+
+    monkeypatch.setattr("src.governance.dry_run.datetime", _RelogioAtrasado, raising=False)
+    async with db.acquire() as conn:
+        with pytest.raises(InvalidTokenError, match="expired"):
+            await consume(conn, token=token, session_id=sid)
```

- [ ] **Step 2: Ver falhar**

Run: `python -m pytest tests/unit/test_pagers_recusam_limite_menor_que_um.py tests/integration/test_dry_run.py -p no:cacheprovider`
Expected (medido): `5 failed, 7 passed in 9.87s` — `E AssertionError: a recusa tinha de vir antes do banco; usou conn.fetch` / `E Failed: DID NOT RAISE InvalidTokenError`

O `DID NOT RAISE` é o defeito real: com o relógio da app atrasado, um token já vencido pelo banco era aceito.

- [ ] **Step 3: Implementar** — aplique os dois blocos:

```diff
diff --git a/src/db/repositories/audit_log.py b/src/db/repositories/audit_log.py
index b809254..fd91ea0 100644
--- a/src/db/repositories/audit_log.py
+++ b/src/db/repositories/audit_log.py
@@ -349,6 +349,13 @@ def _build_manager_page_sql(
     return sql, params
 
 
+def _recusa_limite_menor_que_um(limit: int) -> None:
+    """Spec 2026-09-28 §3.2.3: com `limit=0`, a página fica vazia, a linha sentinela
+    diz "tem mais" e o `page[-1]` do cursor estoura `IndexError`."""
+    if limit < 1:
+        raise ValueError(f"limit tem de ser >= 1, veio {limit}")
+
+
 async def list_page_for_manager(
     conn: asyncpg.Connection,
     *,
@@ -389,6 +396,7 @@ async def list_page_for_manager(
     tools layer. The SQL itself lives in `_build_manager_page_sql` — see its
     docstring for why it isn't inlined here anymore.
     """
+    _recusa_limite_menor_que_um(limit)
     sql, params = _build_manager_page_sql(
         manager_id=manager_id,
         days=days,
@@ -484,6 +492,7 @@ async def list_page_admin(
     admin table shows (gestor e-mail, no per-row dry_run/params_summary). The
     SQL itself lives in `_build_admin_page_sql`.
     """
+    _recusa_limite_menor_que_um(limit)
     sql, params = _build_admin_page_sql(
         days=days,
         manager_id=manager_id,
```

```diff
diff --git a/src/governance/dry_run.py b/src/governance/dry_run.py
index a2c6bd6..d1d26b0 100644
--- a/src/governance/dry_run.py
+++ b/src/governance/dry_run.py
@@ -13,7 +13,6 @@ import json
 import secrets
 import string
 from dataclasses import dataclass
-from datetime import UTC, datetime
 from typing import Any
 from uuid import UUID
 
@@ -136,7 +135,7 @@ async def consume(
         row = await conn.fetchrow(
             """
             SELECT session_id, customer_id, operation_type, payload, blast_summary,
-                   expires_at, consumed_at
+                   expires_at, consumed_at, expires_at < now() AS expirado
             FROM pending_confirmations
             WHERE token = $1
             FOR UPDATE
@@ -151,7 +150,9 @@ async def consume(
             raise InvalidTokenError(
                 f"Token '{token}' belongs to a different session — refuse to apply"
             )
-        if row["expires_at"] < datetime.now(UTC):
+        # Spec 2026-09-28 §3.2.5: o prazo foi gravado com o `now()` do banco, e é com
+        # ele que se decide — o relógio da app é outro host.
+        if row["expirado"]:
             raise InvalidTokenError(f"Token '{token}' expired")
 
         await conn.execute(
```

- [ ] **Step 4: Ver passar**

Run: `python -m pytest tests/unit/test_pagers_recusam_limite_menor_que_um.py tests/integration/test_dry_run.py tests/integration/test_audit_keyset.py -p no:cacheprovider`
Expected: `15 passed in 10.14s`

- [ ] **Step 5: Gate e commit**

```bash
python scripts/check_pre_push_full.py > .superpowers/gate-infra-t3.log 2>&1 && git add src/db/repositories/audit_log.py src/governance/dry_run.py tests/unit/test_pagers_recusam_limite_menor_que_um.py tests/integration/test_dry_run.py && git commit -F .superpowers/msg-infra-t3.txt
```

Mensagem: `fix(db): pagers recusam limit < 1 e o token de dry-run vence pelo relogio do banco (infra e guards, parte 2)` + trailer.

---

### Task 4: Reserva e acerto de quota no mesmo dia; o contador Meta em UTC e numa transação

**Files:**
- Modify: `tests/integration/test_rate_limit.py`, `tests/unit/test_meta_buc_registro.py`, `src/governance/rate_limit.py`, `src/google_ads/conversions.py`, `src/google_ads/customer_match.py`, `src/google_ads/mutations.py`, `src/google_ads/reports.py`, `src/mcp/tools/validate_gaql.py`

**Interfaces:**
- **Produces:**
  - `async def before_call(...) -> date`, que devolve o dia UTC em que reservou;
  - `async def record_actual(conn, developer_token_id, *, dia: date, actual_ops: int, estimated_ops: int) -> None`: o `dia` é **obrigatório**, e o mypy acusa quem esquecer.
- **Os 6 pontos de reserva** (conversions, customer_match, reports, validate_gaql e os dois de mutations): guardam `dia = await before_call(conn, token_id, …)` e `dia_do_gestor = await before_call(conn, f"mgr:…", …)`, e passam cada um ao seu `record_actual`. Os dois dias podem diferir se a virada cair entre as duas reservas.
- **`record_actual_meta`:** usa `_today().date()` e grava sob `async with pool.acquire() as conn, conn.transaction():`. Por isso o pool falso de `test_meta_buc_registro.py` ganha um `transaction()`.

- [ ] **Step 1: Escrever os testes e converter os antigos** — aplique os dois blocos:

```diff
diff --git a/tests/integration/test_rate_limit.py b/tests/integration/test_rate_limit.py
index 576aded..b217674 100644
--- a/tests/integration/test_rate_limit.py
+++ b/tests/integration/test_rate_limit.py
@@ -30,9 +30,9 @@ async def test_first_call_starts_counter_at_estimate(db) -> None:
 async def test_record_actual_reconciles_estimate(db) -> None:
     pool = db
     async with pool.acquire() as conn:
-        await before_call(conn, _TOKEN_ID, estimated_ops=10)
+        dia = await before_call(conn, _TOKEN_ID, estimated_ops=10)
         # Google said only 7 ops actually used.
-        await record_actual(conn, _TOKEN_ID, actual_ops=7, estimated_ops=10)
+        await record_actual(conn, _TOKEN_ID, dia=dia, actual_ops=7, estimated_ops=10)
         used, _, _ = await get_today_usage(conn, _TOKEN_ID)
     assert used == 7  # reconciled down
 
@@ -143,7 +143,7 @@ async def test_manager_key_reserves_and_reconciles_independently_of_global_key(d
 
     async with pool.acquire() as conn:
         await before_call(conn, _TOKEN_ID, estimated_ops=50)
-        await before_call(conn, mgr_key, estimated_ops=30, daily_limit=5000)
+        dia_do_gestor = await before_call(conn, mgr_key, estimated_ops=30, daily_limit=5000)
 
         global_used, _, _ = await get_today_usage(conn, _TOKEN_ID)
         mgr_used, _, _ = await get_today_usage(conn, mgr_key, daily_limit=5000)
@@ -151,7 +151,7 @@ async def test_manager_key_reserves_and_reconciles_independently_of_global_key(d
         assert mgr_used == 30
 
         # Reconcilia so a chave do gestor pra baixo — a global fica intacta.
-        await record_actual(conn, mgr_key, actual_ops=20, estimated_ops=30)
+        await record_actual(conn, mgr_key, dia=dia_do_gestor, actual_ops=20, estimated_ops=30)
 
         global_used_after, _, _ = await get_today_usage(conn, _TOKEN_ID)
         mgr_used_after, _, _ = await get_today_usage(conn, mgr_key, daily_limit=5000)
@@ -174,3 +174,68 @@ async def test_manager_key_blocks_at_its_own_daily_limit(db) -> None:
 
         mgr_used, _, _ = await get_today_usage(conn, mgr_key, daily_limit=manager_daily_quota)
     assert mgr_used == 95  # bloqueio nao alterou a row
+
+
+@pytest.mark.integration
+async def test_acerto_que_atravessa_a_meia_noite_acerta_o_dia_da_reserva(db, monkeypatch) -> None:
+    """Spec 2026-09-28 §3.2.4: reserva e acerto no mesmo balde.
+
+    O `record_actual` acertava a linha de HOJE. Uma chamada reservada às 23:59 UTC e
+    acertada às 00:01 caía num dia sem linha — `UPDATE` de zero linhas, sem erro — e a
+    correção sumia; a reserva de ontem ficava com a estimativa, não com o medido.
+    """
+    import src.governance.rate_limit as rl
+
+    reserva = datetime(2026, 9, 27, 23, 59, tzinfo=UTC)
+    acerto = datetime(2026, 9, 28, 0, 1, tzinfo=UTC)
+    monkeypatch.setattr(rl, "_today", lambda: reserva)
+    async with db.acquire() as conn:
+        dia = await before_call(conn, _TOKEN_ID, estimated_ops=10)
+        monkeypatch.setattr(rl, "_today", lambda: acerto)
+        await record_actual(conn, _TOKEN_ID, dia=dia, actual_ops=7, estimated_ops=10)
+        linhas = await conn.fetch(
+            "SELECT date, operations_used FROM rate_counters "
+            "WHERE developer_token_id = $1 ORDER BY date",
+            _TOKEN_ID,
+        )
+    assert dia == reserva.date()
+    assert [(r["date"], r["operations_used"]) for r in linhas] == [(reserva.date(), 7)]
+
+
+def _buc(pct: int) -> str:
+    import json
+
+    return json.dumps({"123": [{"call_count": pct, "total_cputime": 1, "total_time": 1}]})
+
+
+@pytest.mark.integration
+async def test_contador_meta_grava_as_duas_coisas_ou_nenhuma(db, monkeypatch) -> None:
+    """Spec 2026-09-28 §3.2.4: `increment_calls` e `update_throttle` numa transação só."""
+    from src.db.repositories import meta_rate_counters
+    from src.governance.rate_limit import record_actual_meta
+
+    async def quebra(*args: object, **kwargs: object) -> None:
+        raise RuntimeError("falhou no meio")
+
+    monkeypatch.setattr(meta_rate_counters, "update_throttle", quebra)
+    with pytest.raises(RuntimeError, match="falhou no meio"):
+        await record_actual_meta(app_id="app", ad_account_id="act_123", buc_header=_buc(42))
+
+    async with db.acquire() as conn:
+        linhas = await conn.fetchval("SELECT count(*) FROM meta_rate_counters")
+    assert linhas == 0, "o increment_calls ficou gravado sem o update_throttle"
+
+
+@pytest.mark.integration
+async def test_contador_meta_conta_no_dia_utc(db, monkeypatch) -> None:
+    """Spec 2026-09-28 §3.2.4: o lado Meta usava `date.today()` — o dia do SO, sem fuso —
+    e o Google, o dia UTC. Só concordavam porque o container roda em UTC."""
+    import src.governance.rate_limit as rl
+    from src.governance.rate_limit import record_actual_meta
+
+    monkeypatch.setattr(rl, "_today", lambda: datetime(2030, 1, 1, 12, tzinfo=UTC))
+    await record_actual_meta(app_id="app", ad_account_id="act_123", buc_header=_buc(42))
+
+    async with db.acquire() as conn:
+        dias = [r["date"] for r in await conn.fetch("SELECT date FROM meta_rate_counters")]
+    assert dias == [datetime(2030, 1, 1, tzinfo=UTC).date()]
```

```diff
diff --git a/tests/unit/test_meta_buc_registro.py b/tests/unit/test_meta_buc_registro.py
index 5f166dc..9fe49ad 100644
--- a/tests/unit/test_meta_buc_registro.py
+++ b/tests/unit/test_meta_buc_registro.py
@@ -17,9 +17,22 @@ from structlog.testing import capture_logs
 from src.governance import rate_limit
 
 
+class _FakeTransacao:
+    async def __aenter__(self) -> None:
+        return None
+
+    async def __aexit__(self, *exc: object) -> None:
+        return None
+
+
+class _FakeConn:
+    def transaction(self) -> _FakeTransacao:
+        return _FakeTransacao()
+
+
 class _FakeAcquire:
     async def __aenter__(self) -> object:
-        return object()
+        return _FakeConn()
 
     async def __aexit__(self, *exc: object) -> None:
         return None
```

- [ ] **Step 2: Ver falhar**

Run: `python -m pytest tests/integration/test_rate_limit.py tests/unit/test_meta_buc_registro.py -p no:cacheprovider`
Expected (medido): `5 failed, 13 passed in 10.86s` — `E AssertionError: o increment_calls ficou gravado sem o update_throttle` / `E TypeError: record_actual() got an unexpected keyword argument 'dia'` / `E assert 1 == 0` / `E assert [datetime.date(2026, 9, 28)] == [datetime.date(2030, 1, 1)]`

- [ ] **Step 3: Implementar** — aplique os seis blocos:

```diff
diff --git a/src/governance/rate_limit.py b/src/governance/rate_limit.py
index 1372923..5564a56 100644
--- a/src/governance/rate_limit.py
+++ b/src/governance/rate_limit.py
@@ -12,7 +12,7 @@ asyncpg connection and runs in one transaction.
 """
 
 import json
-from datetime import UTC, datetime
+from datetime import UTC, date, datetime
 from typing import NamedTuple
 
 import asyncpg
@@ -46,9 +46,12 @@ async def before_call(
     *,
     estimated_ops: int,
     daily_limit: int = DAILY_QUOTA_BASIC,
-) -> None:
+) -> date:
     """Reserve estimated_ops in today's counter. Raises QuotaExhausted at 100%.
 
+    Devolve o dia (UTC) em que reservou: o `record_actual` acerta ESSE dia, não o de
+    hoje — reserva e acerto no mesmo balde (spec 2026-09-28 §3.2.4).
+
     Logs a one-time warning when crossing 80% threshold (uses
     `last_alert_pct` to dedupe within the day).
     """
@@ -109,17 +112,22 @@ async def before_call(
             new_used,
             new_alert,
         )
+    return today
 
 
 async def record_actual(
     conn: asyncpg.Connection,
     developer_token_id: str,
     *,
+    dia: date,
     actual_ops: int,
     estimated_ops: int,
 ) -> None:
-    """Reconcile counter after API responds. Adjusts by (actual - estimated)."""
-    today = _today().date()
+    """Acerta a reserva depois da resposta: soma (actual - estimated) ao dia `dia`.
+
+    `dia` é o que o `before_call` devolveu. Acertar o dia de HOJE descartava a correção
+    de chamada que atravessa a meia-noite UTC: `UPDATE` de zero linhas, sem erro.
+    """
     delta = actual_ops - estimated_ops
     if delta == 0:
         return  # estimate was right
@@ -130,7 +138,7 @@ async def record_actual(
         WHERE developer_token_id = $1 AND date = $2
         """,
         developer_token_id,
-        today,
+        dia,
         delta,
     )
 
@@ -258,7 +266,6 @@ async def record_actual_meta(
     Hashes app_id (SHA-256 truncated 32-char) before persisting for storage privacy.
     """
     import hashlib
-    from datetime import date
 
     from src.db import connection
     from src.db.repositories import meta_rate_counters
@@ -266,10 +273,12 @@ async def record_actual_meta(
     throttle_pct = _parse_buc_header_pct(buc_header, ad_account_id=ad_account_id)
     insights = _parse_insights_throttle(insights_throttle_header)
     app_id_hash = hashlib.sha256(app_id.encode()).hexdigest()[:32]
-    today = date.today()
+    # Spec 2026-09-28 §3.2.4: o mesmo dia UTC do Google (era `date.today()`, o dia do SO),
+    # e as duas gravações numa transação — a falha da segunda desfaz a primeira.
+    today = _today().date()
 
     pool = connection.get_pool()
-    async with pool.acquire() as conn:
+    async with pool.acquire() as conn, conn.transaction():
         await meta_rate_counters.increment_calls(
             conn,
             app_id=app_id_hash,
```

```diff
diff --git a/src/google_ads/conversions.py b/src/google_ads/conversions.py
index e546dba..87e4a49 100644
--- a/src/google_ads/conversions.py
+++ b/src/google_ads/conversions.py
@@ -111,8 +111,8 @@ async def run_conversion_upload(
         # EXTERNA torna as duas reservas tudo-ou-nada (before_call's internal
         # conn.transaction() vira SAVEPOINT; raise em qualquer uma desfaz ambas).
         async with pool.acquire() as conn, conn.transaction():
-            await before_call(conn, token_id, estimated_ops=max(1, target_count))
-            await before_call(
+            dia = await before_call(conn, token_id, estimated_ops=max(1, target_count))
+            dia_do_gestor = await before_call(
                 conn,
                 f"mgr:{manager_id}",
                 estimated_ops=max(1, target_count),
@@ -200,12 +200,14 @@ async def run_conversion_upload(
                 await record_actual(
                     conn,
                     token_id,
+                    dia=dia,
                     actual_ops=actual_ops,
                     estimated_ops=max(1, target_count),
                 )
                 await record_actual(
                     conn,
                     f"mgr:{manager_id}",
+                    dia=dia_do_gestor,
                     actual_ops=actual_ops,
                     estimated_ops=max(1, target_count),
                 )
```

```diff
diff --git a/src/google_ads/customer_match.py b/src/google_ads/customer_match.py
index f200c6b..591d84a 100644
--- a/src/google_ads/customer_match.py
+++ b/src/google_ads/customer_match.py
@@ -276,8 +276,8 @@ async def run_offline_user_data_job(
         # EXTERNA torna as duas reservas tudo-ou-nada (before_call's internal
         # conn.transaction() vira SAVEPOINT; raise em qualquer uma desfaz ambas).
         async with pool.acquire() as conn, conn.transaction():
-            await before_call(conn, token_id, estimated_ops=estimated_ops)
-            await before_call(
+            dia = await before_call(conn, token_id, estimated_ops=estimated_ops)
+            dia_do_gestor = await before_call(
                 conn,
                 f"mgr:{manager_id}",
                 estimated_ops=estimated_ops,
@@ -390,11 +390,12 @@ async def run_offline_user_data_job(
                 conn.transaction(),
             ):
                 await record_actual(
-                    conn, token_id, actual_ops=actual_ops, estimated_ops=estimated_ops
+                    conn, token_id, dia=dia, actual_ops=actual_ops, estimated_ops=estimated_ops
                 )
                 await record_actual(
                     conn,
                     f"mgr:{manager_id}",
+                    dia=dia_do_gestor,
                     actual_ops=actual_ops,
                     estimated_ops=estimated_ops,
                 )
```

```diff
diff --git a/src/google_ads/mutations.py b/src/google_ads/mutations.py
index 5973a61..3a043ba 100644
--- a/src/google_ads/mutations.py
+++ b/src/google_ads/mutations.py
@@ -269,8 +269,8 @@ async def run_mutation(
         # EXTERNA torna as duas reservas tudo-ou-nada (before_call's internal
         # conn.transaction() vira SAVEPOINT; raise em qualquer uma desfaz ambas).
         async with pool.acquire() as conn, conn.transaction():
-            await before_call(conn, token_id, estimated_ops=max(1, target_count))
-            await before_call(
+            dia = await before_call(conn, token_id, estimated_ops=max(1, target_count))
+            dia_do_gestor = await before_call(
                 conn,
                 f"mgr:{manager_id}",
                 estimated_ops=max(1, target_count),
@@ -413,12 +413,14 @@ async def run_mutation(
                 await record_actual(
                     conn,
                     token_id,
+                    dia=dia,
                     actual_ops=target_count,
                     estimated_ops=max(1, target_count),
                 )
                 await record_actual(
                     conn,
                     f"mgr:{manager_id}",
+                    dia=dia_do_gestor,
                     actual_ops=target_count,
                     estimated_ops=max(1, target_count),
                 )
@@ -511,8 +513,8 @@ async def run_recommendation_action(
         # outros 4 executores; sem a 2a chave o cap por gestor teria um buraco
         # por onde apply/dismiss_recommendation passariam livres).
         async with pool.acquire() as conn, conn.transaction():
-            await before_call(conn, token_id, estimated_ops=1)
-            await before_call(
+            dia = await before_call(conn, token_id, estimated_ops=1)
+            dia_do_gestor = await before_call(
                 conn,
                 f"mgr:{manager_id}",
                 estimated_ops=1,
@@ -569,8 +571,10 @@ async def run_recommendation_action(
                 pool.acquire() as conn,
                 conn.transaction(),
             ):
-                await record_actual(conn, token_id, actual_ops=1, estimated_ops=1)
-                await record_actual(conn, f"mgr:{manager_id}", actual_ops=1, estimated_ops=1)
+                await record_actual(conn, token_id, dia=dia, actual_ops=1, estimated_ops=1)
+                await record_actual(
+                    conn, f"mgr:{manager_id}", dia=dia_do_gestor, actual_ops=1, estimated_ops=1
+                )
         async with (
             best_effort(
                 "recommendation_audit_write_failed",
```

```diff
diff --git a/src/google_ads/reports.py b/src/google_ads/reports.py
index e26c91c..a17f7d4 100644
--- a/src/google_ads/reports.py
+++ b/src/google_ads/reports.py
@@ -86,8 +86,8 @@ async def run_report(
         # EXTERNA torna as duas reservas tudo-ou-nada (before_call's internal
         # conn.transaction() vira SAVEPOINT; raise em qualquer uma desfaz ambas).
         async with pool.acquire() as conn, conn.transaction():
-            await before_call(conn, token_id, estimated_ops=estimated_ops)
-            await before_call(
+            dia = await before_call(conn, token_id, estimated_ops=estimated_ops)
+            dia_do_gestor = await before_call(
                 conn,
                 f"mgr:{manager_id}",
                 estimated_ops=estimated_ops,
@@ -145,12 +145,14 @@ async def run_report(
                 await record_actual(
                     conn,
                     token_id,
+                    dia=dia,
                     actual_ops=actual_ops,
                     estimated_ops=estimated_ops,
                 )
                 await record_actual(
                     conn,
                     f"mgr:{manager_id}",
+                    dia=dia_do_gestor,
                     actual_ops=actual_ops,
                     estimated_ops=estimated_ops,
                 )
```

```diff
diff --git a/src/mcp/tools/validate_gaql.py b/src/mcp/tools/validate_gaql.py
index 67ce4f2..8e932ef 100644
--- a/src/mcp/tools/validate_gaql.py
+++ b/src/mcp/tools/validate_gaql.py
@@ -124,8 +124,8 @@ async def validate_gaql(args: dict[str, Any]) -> dict[str, Any]:
         # Transacao EXTERNA torna as duas reservas tudo-ou-nada (mesmo padrao
         # de run_report: before_call's conn.transaction() interna vira SAVEPOINT).
         async with pool.acquire() as conn, conn.transaction():
-            await before_call(conn, token_id, estimated_ops=estimated_ops)
-            await before_call(
+            dia = await before_call(conn, token_id, estimated_ops=estimated_ops)
+            dia_do_gestor = await before_call(
                 conn,
                 f"mgr:{ctx.manager_id}",
                 estimated_ops=estimated_ops,
@@ -191,11 +191,12 @@ async def validate_gaql(args: dict[str, Any]) -> dict[str, Any]:
                 conn.transaction(),
             ):
                 await record_actual(
-                    conn, token_id, actual_ops=actual_ops, estimated_ops=estimated_ops
+                    conn, token_id, dia=dia, actual_ops=actual_ops, estimated_ops=estimated_ops
                 )
                 await record_actual(
                     conn,
                     f"mgr:{ctx.manager_id}",
+                    dia=dia_do_gestor,
                     actual_ops=actual_ops,
                     estimated_ops=estimated_ops,
                 )
```

- [ ] **Step 4: Ver passar**

Run: `python -m pytest tests/integration/test_rate_limit.py tests/unit/test_meta_buc_registro.py -p no:cacheprovider`
Expected: `18 passed in 9.63s`

E `python -m mypy src` limpo: é ele que prova que nenhum `record_actual` ficou sem `dia=`.

- [ ] **Step 5: Gate e commit**

```bash
python scripts/check_pre_push_full.py > .superpowers/gate-infra-t4.log 2>&1 && git add src/governance/rate_limit.py src/google_ads/conversions.py src/google_ads/customer_match.py src/google_ads/mutations.py src/google_ads/reports.py src/mcp/tools/validate_gaql.py tests/integration/test_rate_limit.py tests/unit/test_meta_buc_registro.py && git commit -F .superpowers/msg-infra-t4.txt
```

Mensagem: `fix(governance): reserva e acerto de quota no mesmo dia, e o contador Meta em UTC e numa transacao (infra e guards, parte 2)` + trailer.

---

### Task 5: Migrations serializadas por `pg_advisory_xact_lock`

**Files:**
- Modify: `tests/integration/test_migrations.py`, `src/db/migrate.py`

**Interfaces:**
- Produces: `_CHAVE_DO_LOCK = 0x76346164732D6D67`.
- O `run_all` segue sem argumentos. Cada migration pendente faz, na mesma transação:
  1. toma o lock;
  2. confere de novo `_migrations`;
  3. aplica e registra só se ainda falta.

- [ ] **Step 1: Escrever o teste** — aplique:

```diff
diff --git a/tests/integration/test_migrations.py b/tests/integration/test_migrations.py
index eb876ec..25707ed 100644
--- a/tests/integration/test_migrations.py
+++ b/tests/integration/test_migrations.py
@@ -100,3 +100,40 @@ async def test_indices_da_010_existem_apos_migrar(db) -> None:
         f"idx_audit_occurred_at ausente. Indices vistos: {sorted(nomes)}"
     )
     assert "idx_mac_customer" in nomes, f"idx_mac_customer ausente. Indices vistos: {sorted(nomes)}"
+
+
+@pytest.mark.integration
+async def test_duas_execucoes_concorrentes_aplicam_cada_migration_uma_vez(pg_dsn: str) -> None:
+    """Spec 2026-09-28 §3.3.1: `pg_advisory_xact_lock` por migration, com re-checagem.
+
+    Sem lock, as duas execuções listam as mesmas pendentes e a perdedora aborta na PK de
+    `_migrations` (o DDL é transacional, então o schema não quebra — o job é que falha).
+    O `deploy-prod` já serializa os deploys do CI; sobra o `gcloud run jobs execute`
+    manual. Banco novo e vazio: o do container já foi migrado pelos testes acima.
+    """
+    import asyncio
+    import os
+
+    import asyncpg
+
+    nome = f"mig_concorrente_{os.getpid()}"
+    admin = await asyncpg.connect(pg_dsn)
+    try:
+        await admin.execute(f'CREATE DATABASE "{nome}"')
+    finally:
+        await admin.close()
+    await connection.init_pool(pg_dsn.rsplit("/", 1)[0] + f"/{nome}", min_size=2, max_size=2)
+    try:
+        await asyncio.gather(migrate.run_all(), migrate.run_all())
+        async with connection.get_pool().acquire() as conn:
+            aplicadas = [
+                r["name"] for r in await conn.fetch("SELECT name FROM _migrations ORDER BY name")
+            ]
+    finally:
+        await connection.close_pool()
+        admin = await asyncpg.connect(pg_dsn)
+        try:
+            await admin.execute(f'DROP DATABASE "{nome}" WITH (FORCE)')
+        finally:
+            await admin.close()
+    assert aplicadas == sorted(p.name for p in migrate.MIGRATIONS_DIR.glob("*.sql"))
```

- [ ] **Step 2: Ver falhar**

Run: `python -m pytest tests/integration/test_migrations.py -p no:cacheprovider -k concorrentes`
Expected (medido): `1 failed, 4 deselected in 7.89s` — `E asyncpg.exceptions.UniqueViolationError: duplicate key value violates unique constraint "pg_type_typname_nsp_index"`

O vermelho é o bootstrap: dois `CREATE TABLE IF NOT EXISTS _migrations` simultâneos colidem no catálogo. Com sorte diferente na corrida, sai a PK de `_migrations`. Os dois são o mesmo defeito.

- [ ] **Step 3: Implementar** — aplique:

```diff
diff --git a/src/db/migrate.py b/src/db/migrate.py
index f4ec0c5..63dd93e 100644
--- a/src/db/migrate.py
+++ b/src/db/migrate.py
@@ -25,6 +25,12 @@ CREATE TABLE IF NOT EXISTS _migrations (
 );
 """
 
+# Spec 2026-09-28 §3.3.1: uma chave só para toda execução do runner. É a de TRANSAÇÃO
+# (`pg_advisory_xact_lock`), não a de sessão: funciona nos dois modos do pooler do
+# Supavisor, e a de sessão quebraria em silêncio se o DSN fosse para a porta 6543.
+# O valor é arbitrário e fixo — 'v4ads-mg' em ASCII, cabe num bigint.
+_CHAVE_DO_LOCK = 0x76346164732D6D67
+
 
 async def _list_pending(conn: asyncpg.Connection) -> list[Path]:
     rows = await conn.fetch("SELECT name FROM _migrations")
@@ -37,7 +43,11 @@ async def run_all() -> None:
     """Apply every pending migration in order. Idempotent."""
     pool = connection.get_pool()
     async with pool.acquire() as conn:
-        await conn.execute(_BOOTSTRAP_SQL)
+        # Dois `CREATE TABLE IF NOT EXISTS` concorrentes também colidem (no catálogo):
+        # o bootstrap roda sob o mesmo lock.
+        async with conn.transaction():
+            await conn.execute("SELECT pg_advisory_xact_lock($1)", _CHAVE_DO_LOCK)
+            await conn.execute(_BOOTSTRAP_SQL)
         pending = await _list_pending(conn)
         if not pending:
             log.info("migrations_no_pending")
@@ -45,12 +55,22 @@ async def run_all() -> None:
         for path in pending:
             sql = path.read_text(encoding="utf-8")
             async with conn.transaction():
-                await conn.execute(sql)
-                await conn.execute(
-                    "INSERT INTO _migrations (name) VALUES ($1)",
-                    path.name,
+                await conn.execute("SELECT pg_advisory_xact_lock($1)", _CHAVE_DO_LOCK)
+                # Re-checa DEPOIS do lock: a lista acima pode ter sido lida enquanto
+                # outra execução aplicava esta mesma migration.
+                ja_aplicada = await conn.fetchval(
+                    "SELECT 1 FROM _migrations WHERE name = $1", path.name
                 )
-            log.info("migration_applied", name=path.name)
+                if not ja_aplicada:
+                    await conn.execute(sql)
+                    await conn.execute(
+                        "INSERT INTO _migrations (name) VALUES ($1)",
+                        path.name,
+                    )
+            if ja_aplicada:
+                log.info("migration_aplicada_por_outra_execucao", name=path.name)
+            else:
+                log.info("migration_applied", name=path.name)
 
 
 async def main() -> None:
```

- [ ] **Step 4: Ver passar**

Run: `python -m pytest tests/integration/test_migrations.py -p no:cacheprovider`
Expected: `5 passed in 7.39s`

- [ ] **Step 5: Gate e commit**

```bash
python scripts/check_pre_push_full.py > .superpowers/gate-infra-t5.log 2>&1 && git add src/db/migrate.py tests/integration/test_migrations.py && git commit -F .superpowers/msg-infra-t5.txt
```

Mensagem: `fix(db): migrations serializadas por pg_advisory_xact_lock (infra e guards, parte 3)` + trailer.

---

### Task 6: Teto de linhas no export CSV do audit

**Files:**
- Create: `tests/unit/test_export_csv_tem_teto_de_linhas.py`
- Modify: `src/db/repositories/audit_log.py`

**Interfaces:**
- Produces: `_TETO_LINHAS_EXPORT = 50_000` e o logger `log` em `audit_log.py`.
- A query de `export_csv_rows` ganha `LIMIT $n`, com o último parâmetro valendo `teto + 1`.

- [ ] **Step 1: Escrever o teste** — `tests/unit/test_export_csv_tem_teto_de_linhas.py`, conteúdo exato:

```python
"""O export CSV do audit tem teto de linhas, e o corte é dito no arquivo (spec 2026-09-28 §3.3.2).

`days` já tinha teto (365, 25/09), mas o resultado não: o cursor server-side ia até a
última linha da janela segurando 1 das 5 conexões do pool pelo download inteiro. Agora a
query pede `teto + 1` (a linha sentinela do F98) e, passando do teto, o arquivo termina
numa marca de CORTE — nunca na de "export completo", que afirmaria o que não é. Medido
em 28/09: 5.795 linhas em 365 dias, então o teto de 50.000 não muda nada hoje.
"""

from collections.abc import AsyncIterator
from typing import Any

import pytest
from structlog.testing import capture_logs

from src.db.repositories import audit_log


def _linha(i: int) -> dict[str, Any]:
    return {
        "occurred_at": None,
        "email": f"a{i}@v4company.com",
        "operation": "op",
        "customer_id": "1",
        "action_type": "read",
        "status": "success",
        "target_count": None,
        "duration_ms": None,
        "error_message": None,
        "provider_request_id": None,
    }


class _Cursor:
    def __init__(self, n: int) -> None:
        self.n = n

    def __aiter__(self) -> AsyncIterator[Any]:
        return self._gerar()

    async def _gerar(self) -> AsyncIterator[Any]:
        for i in range(self.n):
            yield _linha(i)


class _Conn:
    def __init__(self, n: int) -> None:
        self._n = n
        self.sql = ""
        self.params: tuple[Any, ...] = ()

    def cursor(self, sql: str, *params: Any) -> _Cursor:
        self.sql, self.params = sql, params
        return _Cursor(self._n)

    def transaction(self) -> Any:
        class _T:
            async def __aenter__(self) -> None:
                return None

            async def __aexit__(self, *a: Any) -> bool:
                return False

        return _T()


async def _exportar(n: int) -> tuple[str, _Conn, list[dict[str, Any]]]:
    conn = _Conn(n)
    with capture_logs() as logs:
        texto = "".join([x async for x in audit_log.export_csv_rows(conn, days=365)])  # type: ignore[arg-type]
    return texto, conn, logs


@pytest.mark.asyncio
async def test_passando_do_teto_o_arquivo_termina_no_corte(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(audit_log, "_TETO_LINHAS_EXPORT", 2, raising=False)
    texto, conn, logs = await _exportar(3)

    assert "a0@v4company.com" in texto and "a1@v4company.com" in texto
    assert "a2@v4company.com" not in texto
    assert "# v4-ads-mcp: EXPORT CORTADO em 2 linhas" in texto
    assert "export completo" not in texto
    assert conn.params[-1] == 3, "a query pede teto + 1: a linha extra é o que revela o corte"
    assert "LIMIT" in conn.sql
    assert any(e["event"] == "audit_export_cortado" for e in logs)


@pytest.mark.asyncio
async def test_no_teto_exato_o_export_e_completo(monkeypatch: pytest.MonkeyPatch) -> None:
    """Controle: exatamente o teto não é corte — a sentinela não veio."""
    monkeypatch.setattr(audit_log, "_TETO_LINHAS_EXPORT", 2, raising=False)
    texto, _, logs = await _exportar(2)

    assert "# v4-ads-mcp: export completo, 2 linhas" in texto
    assert "CORTADO" not in texto
    assert not any(e["event"] == "audit_export_cortado" for e in logs)


def test_o_teto_de_producao_e_50_mil() -> None:
    assert audit_log._TETO_LINHAS_EXPORT == 50_000
```

- [ ] **Step 2: Ver falhar**

Run: `python -m pytest tests/unit/test_export_csv_tem_teto_de_linhas.py -p no:cacheprovider`
Expected (medido): `2 failed, 1 passed in 4.08s` — `E AttributeError: module 'src.db.repositories.audit_log' has no attribute '_TETO_LINHAS_EXPORT'` / `E assert 'a2@v4company.com' not in 'occurred_at... linhas"\r\n'`

O controle (teto exato = completo) passa antes do conserto, e é para passar.

- [ ] **Step 3: Implementar** — aplique:

```diff
diff --git a/src/db/repositories/audit_log.py b/src/db/repositories/audit_log.py
index fd91ea0..4bba513 100644
--- a/src/db/repositories/audit_log.py
+++ b/src/db/repositories/audit_log.py
@@ -8,6 +8,9 @@ from typing import Any, Literal
 from uuid import UUID
 
 import asyncpg
+import structlog
+
+log = structlog.get_logger(__name__)
 
 # Excel/Sheets treat a leading =, +, -, @ (or tab) as a formula trigger — a
 # manager_email, operation, or error_message that happens to start with one of
@@ -123,6 +126,11 @@ async def get_by_id(
     return dict(row) if row else None
 
 
+# Spec 2026-09-28 §3.3.2: teto de linhas do export CSV. Medido em 28/09: 5.795 linhas
+# em 365 dias (o teto de `days`), então 50.000 dá folga de anos e não corta nada hoje.
+_TETO_LINHAS_EXPORT = 50_000
+
+
 async def export_csv_rows(
     conn: asyncpg.Connection,
     *,
@@ -155,12 +163,16 @@ async def export_csv_rows(
         where.append(f"al.status = ${idx}")
         params.append(status)
         idx += 1
+    teto = _TETO_LINHAS_EXPORT
+    # F98: pede teto + 1 — a linha extra é o que revela que havia mais.
+    params.append(teto + 1)
     sql = f"""SELECT al.occurred_at, m.email, al.operation, al.customer_id,
                      al.action_type, al.status, al.target_count, al.duration_ms,
                      al.error_message, al.provider_request_id
               FROM audit_log al LEFT JOIN managers m ON m.id = al.manager_id
               WHERE {" AND ".join(where)}
-              ORDER BY al.occurred_at DESC, al.id DESC"""
+              ORDER BY al.occurred_at DESC, al.id DESC
+              LIMIT ${idx}"""
 
     # Header
     header = [
@@ -185,12 +197,16 @@ async def export_csv_rows(
     # sentinela de sucesso so existe para que a AUSENCIA dela, sob exceçao,
     # signifique "incompleto" — fail-closed por construçao (ver brief da Task 6).
     lidas = 0
+    cortado = False
     try:
         # asyncpg server-side cursors MUST run inside an explicit transaction.
         # (Pre-existing bug surfaced by the first test to actually iterate this
         # generator: NoActiveSQLTransactionError without this wrapper.)
         async with conn.transaction():
             async for row in conn.cursor(sql, *params):
+                if lidas == teto:
+                    cortado = True
+                    break
                 buf = io.StringIO()
                 csv.writer(buf).writerow(
                     [
@@ -223,7 +239,13 @@ async def export_csv_rows(
         yield buf.getvalue()
         raise
     buf = io.StringIO()
-    csv.writer(buf).writerow([f"# v4-ads-mcp: export completo, {lidas} linhas"])
+    if cortado:
+        log.warning("audit_export_cortado", teto=teto, days=days)
+        csv.writer(buf).writerow(
+            [f"# v4-ads-mcp: EXPORT CORTADO em {teto} linhas — reduza o periodo (days={days})"]
+        )
+    else:
+        csv.writer(buf).writerow([f"# v4-ads-mcp: export completo, {lidas} linhas"])
     yield buf.getvalue()
 
 
```

- [ ] **Step 4: Ver passar**

Run: `python -m pytest tests/unit/test_export_csv_tem_teto_de_linhas.py tests/unit/test_export_csv_prova_completude.py tests/unit/test_export_csv_days_tem_teto.py tests/unit/test_audit_log_csv_safe.py -p no:cacheprovider`
Expected: `24 passed in 4.59s`

- [ ] **Step 5: Gate e commit**

```bash
python scripts/check_pre_push_full.py > .superpowers/gate-infra-t6.log 2>&1 && git add src/db/repositories/audit_log.py tests/unit/test_export_csv_tem_teto_de_linhas.py && git commit -F .superpowers/msg-infra-t6.txt
```

Mensagem: `fix(db): teto de linhas no export CSV do audit (infra e guards, parte 3)` + trailer.

---

### Task 7: estado-atual, destino dos achados de 21/09 e a spec

**Files:**
- Modify: `docs/operacao/estado-atual.md`, `docs/_archive/varredura-2026-09-21/README.md`, `docs/superpowers/specs/2026-09-28-infra-e-guards-design.md`

**Interfaces:** consome o que as tasks 1 a 6 fizeram. O ajuste na spec é a regra do guard de desempate, que passa a olhar só tabela do banco (Task 2).

- [ ] **Step 1: Salvar o script** em `.superpowers/task7_infra_docs.py`, conteúdo exato:

```python
"""Task 7 do plano infra e guards: estado-atual, destino dos achados de 21/09 e a spec.

Uso (raiz do repo): python task7_docs.py
"""

import pathlib


def editar(caminho: str, pares: list[tuple[str, str]]) -> None:
    p = pathlib.Path(caminho)
    t = p.read_text(encoding="utf-8")
    for velho, novo in pares:
        assert t.count(velho) == 1, (caminho, t.count(velho), velho[:70])
        t = t.replace(velho, novo)
    p.write_text(t, encoding="utf-8", newline="\n")


# O link e montado em partes: o `test_docs_links` le o plano inteiro, cercas de codigo
# inclusive, e resolveria um link literal daqui relativo ao arquivo do plano.
SPEC = "[spec 2026-09-28]" + "(../superpowers/specs/2026-09-28-infra-e-guards-design.md)"

editar(
    "docs/operacao/estado-atual.md",
    [
        (
            "| 3 · infra de dados (CSV do audit, guard de reconnect, lock no `migrate.py`, `revoke` Meta) "
            "| **em parte** — CSV no F191; o resto é a frente *infra e guards* |",
            "| 3 · infra de dados (CSV do audit, guard de reconnect, lock no `migrate.py`, `revoke` Meta) "
            f"| **fechado** — CSV no F191; o resto na frente *infra e guards* ({SPEC}) |",
        ),
        (
            "| 4 · guards que não cobrem (mock que bloqueava o conserto, testes que enumeram) "
            "| **em parte** — mock no F191; o resto é a frente *infra e guards* |",
            "| 4 · guards que não cobrem (mock que bloqueava o conserto, testes que enumeram) "
            "| **fechado** — mock no F191; o guard de reconexão que enumerava deu lugar ao pool "
            f"validado, um ponto só ({SPEC}) |",
        ),
        (
            "1. **Fase 2B** — em 04/10, separar o uso por gestor, junto da remedição dos buckets.\n"
            "2. **Infra e guards** (spec) — o resto dos sub-projetos 3 e 4.\n"
            "3. **`recommendation_subscription`** — tool de leitura no MCC.\n",
            "1. **Fase 2B** — em 04/10, separar o uso por gestor, junto da remedição dos buckets.\n"
            "2. **`recommendation_subscription`** — tool de leitura no MCC.\n"
            "3. **F187** — o remédio do resumo × detalhe.\n",
        ),
    ],
)

FECHADO = "fechado — *infra e guards* (spec 2026-09-28)"
editar(
    "docs/_archive/varredura-2026-09-21/README.md",
    [
        (
            "| 3 | infra de dados | CSV do audit falha aberto · escopo do guard de reconnect · lock no "
            "`migrate.py` · assimetria do `revoke` Meta | CSV fechado no F191; o resto aberto |",
            "| 3 | infra de dados | CSV do audit falha aberto · escopo do guard de reconnect · lock no "
            "`migrate.py` · assimetria do `revoke` Meta | CSV fechado no F191; o resto na *infra e "
            "guards* (spec 2026-09-28) |",
        ),
        (
            "| 4 | guards que não cobrem | o mock que bloqueava o conserto · testes que enumeram em vez "
            "de afirmar a propriedade | mock fechado no F191; o resto aberto |",
            "| 4 | guards que não cobrem | o mock que bloqueava o conserto · testes que enumeram em vez "
            "de afirmar a propriedade | mock fechado no F191; o resto na *infra e guards* (spec "
            "2026-09-28) |",
        ),
        (
            "| 2 | `pool.acquire()` cru em leituras quentes, fora do guard estrutural | aberto — *infra e guards* |",
            f"| 2 | `pool.acquire()` cru em leituras quentes, fora do guard estrutural | {FECHADO}: a "
            "conexão é testada na retirada, para toda leitura e escrita |",
        ),
        (
            "| 3 | `migrate.py` sem advisory lock | aberto — *infra e guards*. Conferido em 25/09: nenhum "
            "`pg_advisory` no arquivo |",
            f"| 3 | `migrate.py` sem advisory lock | {FECHADO}: `pg_advisory_xact_lock` por migration, "
            "com re-checagem |",
        ),
        (
            "| 4 | `days` e resultado sem teto nos exports CSV | `days`: fechado em 25/09 — teto de 365, "
            "validado na rota; resultado: aberto — *infra e guards* |",
            "| 4 | `days` e resultado sem teto nos exports CSV | `days`: fechado em 25/09 — teto de 365, "
            f"validado na rota; resultado: {FECHADO} (50.000 linhas, com marca de corte) |",
        ),
        (
            "| 5 | `revoke` Meta sem `AND revoked_at IS NULL` | aberto — *infra e guards*. Conferido em "
            "25/09: falta no `revoke` manual de `manager_meta_account_access.py`; o "
            "`revoke_for_account`, que a reconciliação usa em produção, tem. O `revoke` de "
            "`google_oauth_connections.py` também não tem |",
            f"| 5 | `revoke` Meta sem `AND revoked_at IS NULL` | {FECHADO}: os três `revoke` sem o "
            "predicado (o Meta manual e os das duas conexões OAuth), com guard derivado do SQL |",
        ),
        (
            "| 6 | `get_active_for_manager`: `LIMIT 1` sobre chave de ordenação não-única | aberto, baixo "
            "— *infra e guards* |",
            f"| 6 | `get_active_for_manager`: `LIMIT 1` sobre chave de ordenação não-única | {FECHADO}: "
            "`id` como desempate, também no `account_resync.py`, com guard derivado do SQL |",
        ),
        (
            "| 7 | `IndexError` com `limit=0` nos dois pagers keyset | aberto, inalcançável hoje — *infra "
            "e guards* |",
            f"| 7 | `IndexError` com `limit=0` nos dois pagers keyset | {FECHADO}: `limit < 1` recusado "
            "na entrada |",
        ),
        (
            "| 8 | itens menores | ver o relatório |",
            f"| 8 | itens menores | {FECHADO}: o dia do contador Meta em UTC, o acerto de quota no "
            "dia da reserva, a transação do contador Meta e a expiração do token de dry-run no "
            "relógio do banco |",
        ),
    ],
)

editar(
    "docs/superpowers/specs/2026-09-28-infra-e-guards-design.md",
    [
        (
            "| 2 | derivado do SQL: todo `ORDER BY … LIMIT 1` em `src/` tem `id` como última chave de "
            "ordenação.",
            "| 2 | derivado do SQL: todo `ORDER BY … LIMIT 1` em `src/` **sobre tabela do nosso banco** "
            "(criada numa migration — é o que separa o SQL da GAQL, cujo `LIMIT 1` em `change_event` "
            "lê um valor, não escolhe linha) tem `id` como última chave de ordenação.",
        ),
    ],
)
print("docs ok")
```

- [ ] **Step 2: Rodar** da raiz do repo:

```bash
python .superpowers/task7_infra_docs.py
```

Expected: `docs ok`. `AssertionError` é âncora que mudou — **não force**: pare e reporte.

- [ ] **Step 3: Conferir** — `git diff --stat` mostra 3 arquivos.

- [ ] **Step 4: Gate e commit**

```bash
python scripts/check_pre_push.py > .superpowers/gate-infra-t7.log 2>&1 && git add docs/operacao/estado-atual.md docs/_archive/varredura-2026-09-21/README.md docs/superpowers/specs/2026-09-28-infra-e-guards-design.md && git commit -F .superpowers/msg-infra-t7.txt
```

Mensagem: `docs(operacao): infra e guards - sub-projetos 3 e 4 da varredura de 21/09 fechados` + trailer.

---

## Depois das tasks

Passos do controlador:

1. **Revisão final da branch** (modelo mais capaz) e uma onda de correção se houver achado. As costuras entre tasks moram aqui: o F154 mostrou que a revisão por task não as vê.
2. **PR contra `main`** com vigia de CI e auto-merge (método `merge`), com a **autorização nominal** do Wellington antes do push. O merge deploya e muda o pool de todo request.
3. **Verificação em produção** (spec §6), tudo por leitura:
   - latência p50 e p95 do `/mcp` nas 24 h antes e depois;
   - contagem de `db_conexao_testada_reconectou` e de `db_dropped_connection_retry`;
   - nenhum 500 de conexão no primeiro acesso da manhã seguinte;
   - o job de migration do deploy limpo;
   - smoke de leitura em `list_my_accounts`, `get_my_rate_limit_status` e uma tool Meta.
   - Registrar no `estado-atual`.
