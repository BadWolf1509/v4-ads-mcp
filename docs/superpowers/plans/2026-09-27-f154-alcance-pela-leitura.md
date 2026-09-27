# F154 — o alcance do system user medido pela leitura: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** o sinal `su_reachable` (e o `unreachable` do relatório da reconciliação Meta) passa a vir de uma leitura mínima de cada conta da parceria, em três estados, em vez do índice `/me/adaccounts`; e o desligamento de contas passa a depender só da leitura da parceria (fecha o M10).

**Architecture:** um módulo novo e puro na decisão (`src/meta_ads/alcance.py`: `classificar_sonda` + `sondar_alcance`) mede o alcance. O planejador (`build_plan`) recebe as recusas medidas; o repositório (`set_reachable`) grava só o que foi medido; o job (`reconcile_meta`) troca o índice pela sonda e tira o alcance da completude.

**Tech Stack:** Python 3.13, httpx (`AsyncClient`), asyncpg, pytest + respx + testcontainers.

**Spec:** `docs/superpowers/specs/2026-09-27-f154-alcance-pela-leitura-design.md` (aprovada em 27/09).

**Como este plano foi feito:** o código de cada task foi escrito e executado ANTES do plano, num worktree de rascunho, uma task por commit, cada uma verde isolada (gate `check_pre_push.py` exit 0 em cada commit; full sweep com Docker no último). Os blocos de código abaixo são o conteúdo exato daqueles commits, gerado por script — não transcrito. Cada "ver falhar" foi medido aplicando os testes da task sobre o estado da task anterior.

## Global Constraints

- **Três estados (spec §3.1):** `200` → lê; `4xx` com `error.code == 200` → recusa (a única recusa medida em 27/09); qualquer outra resposta, exceção de rede ou timeout → **não medido**, que **não grava**.
- **A sonda é a chamada das tools:** `build_insights_call(level="account", start=ontem, end=ontem, limit=1)`, "ontem" no fuso da conta (`account_today`, sobre o instante `agora` que o job lê uma vez — F141), timeout de **15 s** por sonda.
- **Token no header `Authorization`, nunca na URL (F82).**
- **`/me/adaccounts` sai do job; `_fetch_all_adaccounts` fica** (o OAuth pessoal o usa).
- **Completude = só a parceria** (`leitura_completa = parceria.complete`). O alcance não bloqueia o desligamento.
- **`set_reachable` escopado à parceria (M4)**, `true` em `le`, `false` em `recusa`, conta não medida intocada; nada medido é no-op.
- **Relatório `meta_reconcile`:** `unreachable` = recusas medidas na parceria; novo `alcance_nao_medido`.
- **Gate:** `python scripts/check_pre_push.py` rodado mudo, com o commit ENCADEADO por `&&` ao gate — **nunca** `;` nem pipe entre os dois.
- **Sabotagem se restaura de CÓPIA, nunca de `git checkout`.** Cópias e arquivos auxiliares vão para `.superpowers/` (git-ignored), nunca para a raiz do repo.
- **Commits:** mensagem pelo Git Bash (o PowerShell põe BOM), com o trailer `Co-Authored-By:` do modelo que você é.

## Arquivos

| arquivo | task | responsabilidade |
|---|---|---|
| `src/meta_ads/alcance.py` (novo) | 1 | classificar a resposta da sonda; sondar as contas |
| `tests/unit/test_meta_alcance.py` (novo) | 1 | tabela de classificação; os três estados pela rede (`respx`) |
| `src/meta_ads/reconcile.py` | 2 | `build_plan(refused_ids=...)`; `unreachable = parceria ∩ recusas` |
| `tests/unit/test_meta_reconcile_plan.py` | 2 | chamadas convertidas; conta não medida fora do `unreachable` |
| `src/db/repositories/meta_ad_accounts.py` | 3 | `set_reachable(le=, recusa=, scope_ids=)` |
| `tests/integration/test_meta_reconcile_repo.py`, `tests/integration/test_web_panel_admin.py` | 3, 4 | chamadores e dublês convertidos; conta não medida mantém o valor |
| `src/jobs/meta_resync.py` | 2, 3, 4 | o job: transição nas tasks 2 e 3, a sonda na 4 |
| `tests/unit/test_meta_reconcile_job.py`, `test_meta_resync_audit.py`, `test_job_partial_failure_audit.py` | 3, 4 | dublês da sonda; `respx` estrito; o M10 |
| `docs/...` (catálogo, estado-atual, nucleo.md, CLAUDE.md) | 5 | F154 corrigido, por script |

**Como aplicar um bloco `diff`:** salve o bloco inteiro (sem as cercas) em `.superpowers/f154-tN-<nome>.diff` e rode `git apply --check <arquivo>` e depois `git apply <arquivo>`. Um bloco que não aplica é um desvio do estado esperado — **pare e reporte**, não edite à mão.

---

### Task 1: A sonda de alcance e os três estados

**Files:**
- Create: `src/meta_ads/alcance.py`
- Create: `tests/unit/test_meta_alcance.py`

**Interfaces:**
- Produces: `classificar_sonda(status_code: int, corpo: Any) -> Estado` (`Estado = Literal["le", "recusa", "nao_medido"]`); `@dataclass(frozen=True, slots=True) class Alcance(le: frozenset[str], recusa: frozenset[str], nao_medido: frozenset[str])` (todos com default `frozenset()`); `async def sondar_alcance(http: httpx.AsyncClient, *, access_token: str, contas: list[tuple[str, str | None]], agora: datetime) -> Alcance`; `TIMEOUT_DA_SONDA = 15.0`.

- [ ] **Step 1: Escrever o teste** — `tests/unit/test_meta_alcance.py`, conteúdo exato:

```python
"""A sonda de alcance do system user e os três estados (F154, spec 2026-09-27 §3.1).

As assinaturas vêm da medição de 27/09 contra a Graph API real: CHUTE 07 lida (200) apesar de
ausente de `/me/adaccounts`; conta sem acesso e id inexistente → 403 `code 200`; token
inválido → 401 `code 190`.
"""

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
import respx

from src.meta_ads.alcance import Alcance, classificar_sonda, sondar_alcance

_BASE = "https://graph.facebook.com/v22.0"
_RECUSA = {
    "error": {
        "message": "(#200) Ad account owner has NOT grant ads_management or ads_read permission",
        "code": 200,
    }
}


@pytest.mark.parametrize(
    ("status", "corpo", "esperado"),
    [
        (200, {"data": [{"spend": "3.37"}]}, "le"),
        (200, {"data": []}, "le"),
        (403, _RECUSA, "recusa"),
        (401, {"error": {"code": 190, "message": "Invalid OAuth access token"}}, "nao_medido"),
        (400, {"error": {"code": 17, "message": "User request limit reached"}}, "nao_medido"),
        (429, None, "nao_medido"),
        (500, {"error": {"code": 1, "message": "An unknown error occurred"}}, "nao_medido"),
        (403, {"error": {"code": 10, "message": "Permission denied"}}, "nao_medido"),
        (403, "nao e json de erro", "nao_medido"),
    ],
)
def test_classificar_sonda(status: int, corpo: Any, esperado: str) -> None:
    assert classificar_sonda(status, corpo) == esperado


@pytest.mark.asyncio
@respx.mock
async def test_sondar_alcance_separa_os_tres_estados() -> None:
    lida = respx.get(f"{_BASE}/act_1/insights").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    respx.get(f"{_BASE}/act_2/insights").mock(return_value=httpx.Response(403, json=_RECUSA))
    respx.get(f"{_BASE}/act_3/insights").mock(
        return_value=httpx.Response(401, json={"error": {"code": 190}})
    )
    respx.get(f"{_BASE}/act_4/insights").mock(side_effect=httpx.ReadTimeout("pendurou"))

    async with httpx.AsyncClient() as http:
        alcance = await sondar_alcance(
            http,
            access_token="tok_su",
            contas=[
                ("act_1", "America/Sao_Paulo"),
                ("act_2", "America/Sao_Paulo"),
                ("act_3", None),
                ("act_4", "America/Sao_Paulo"),
            ],
            # 02h UTC de 27/09 = 23h de 26/09 em Sao Paulo: "ontem" da conta e 25/09.
            agora=datetime(2026, 9, 27, 2, 0, tzinfo=UTC),
        )

    assert alcance == Alcance(
        le=frozenset({"act_1"}),
        recusa=frozenset({"act_2"}),
        nao_medido=frozenset({"act_3", "act_4"}),
    )
    pedido = lida.calls.last.request
    assert pedido.headers["Authorization"] == "Bearer tok_su"
    assert "access_token" not in str(pedido.url)  # F82: token no header, nunca na URL
    assert '"since":"2026-09-25"' in pedido.url.params["time_range"]
    assert pedido.url.params["level"] == "account"
```

- [ ] **Step 2: Ver falhar**

Run: `python -m pytest tests/unit/test_meta_alcance.py -p no:cacheprovider`
Expected: `1 error` na coleta — `ModuleNotFoundError: No module named 'src.meta_ads.alcance'` (o módulo ainda não existe).

- [ ] **Step 3: Implementar** — `src/meta_ads/alcance.py`, conteúdo exato:

```python
"""O alcance do system user, medido pela leitura — não pelo índice (F154).

`/me/adaccounts` lista o inventário PRÓPRIO do system user, e em 27/09 omitia a CHUTE 07,
que o SU lê (`/insights` 200). O sinal `su_reachable` passou a vir de uma leitura mínima de
cada conta da parceria, na forma exata das tools (`build_insights_call`): a capacidade que
o painel promete, não um índice que a aproxima (spec 2026-09-27).

Três estados. Assinaturas medidas em 27/09 contra a Graph API: conta lida → 200; conta sem
acesso ou id inexistente → 403 com `error.code == 200`; token inválido → 401 com
`code == 190`. Só a recusa medida vira "recusa"; todo o resto é "não medido", que não grava:
ausência de medição não é resposta (F191/F194).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

import httpx
import structlog

from src.clock import account_today
from src.meta_ads.client import META_GRAPH_API_VERSION
from src.meta_ads.insights import build_insights_call

log = structlog.get_logger(__name__)

_GRAPH = f"https://graph.facebook.com/{META_GRAPH_API_VERSION}"

# O cliente do job usa 60 s; 25 contas penduradas seriam 25 minutos de job.
TIMEOUT_DA_SONDA = 15.0

# A única recusa medida (27/09): "(#200) Ad account owner has NOT grant ads_management or
# ads_read permission". Um código de recusa que ainda não vimos sai como não medido — não
# marca conta como inalcançável sem prova.
_CODIGO_DA_RECUSA = 200

Estado = Literal["le", "recusa", "nao_medido"]


def classificar_sonda(status_code: int, corpo: Any) -> Estado:
    """Resposta da sonda → lê | recusa | não medido."""
    if status_code == 200:
        return "le"
    erro = corpo.get("error") if isinstance(corpo, dict) else None
    if (
        400 <= status_code < 500
        and isinstance(erro, dict)
        and erro.get("code") == _CODIGO_DA_RECUSA
    ):
        return "recusa"
    return "nao_medido"


@dataclass(frozen=True, slots=True)
class Alcance:
    le: frozenset[str] = frozenset()
    recusa: frozenset[str] = frozenset()
    nao_medido: frozenset[str] = frozenset()


async def sondar_alcance(
    http: httpx.AsyncClient,
    *,
    access_token: str,
    contas: list[tuple[str, str | None]],
    agora: datetime,
) -> Alcance:
    """Uma leitura mínima por conta — `(ad_account_id, fuso)` → o estado de cada uma.

    "Ontem" é no fuso da conta, sobre o instante que o job lê uma vez (F141). Conta sem
    entrega ontem devolve 200 com `data` vazia: continua sendo "lê" — a pergunta é o
    acesso, não o gasto.
    """
    cabecalho = {"Authorization": f"Bearer {access_token}"}
    por_estado: dict[Estado, set[str]] = {"le": set(), "recusa": set(), "nao_medido": set()}
    for ad_account_id, fuso in contas:
        ontem = account_today(fuso, now=agora) - timedelta(days=1)
        edge, params = build_insights_call(
            level="account", ad_account_id=ad_account_id, start=ontem, end=ontem, limit=1
        )
        try:
            resposta = await http.get(
                _GRAPH + edge, params=params, headers=cabecalho, timeout=TIMEOUT_DA_SONDA
            )
            try:
                corpo = resposta.json()
            except ValueError:
                corpo = None
            estado = classificar_sonda(resposta.status_code, corpo)
        except httpx.HTTPError:
            estado = "nao_medido"
        por_estado[estado].add(ad_account_id)
    if por_estado["nao_medido"]:
        log.warning(
            "meta_alcance_nao_medido",
            total=len(por_estado["nao_medido"]),
            ad_account_ids=sorted(por_estado["nao_medido"]),
        )
    return Alcance(
        le=frozenset(por_estado["le"]),
        recusa=frozenset(por_estado["recusa"]),
        nao_medido=frozenset(por_estado["nao_medido"]),
    )
```

- [ ] **Step 4: Ver passar**

Run: `python -m pytest tests/unit/test_meta_alcance.py -p no:cacheprovider`
Expected: `10 passed`.

- [ ] **Step 5: Gate e commit** (o commit só roda se o gate passar):

```bash
python scripts/check_pre_push.py > .superpowers/gate-f154-t1.log 2>&1 && git add src/meta_ads/alcance.py tests/unit/test_meta_alcance.py && git commit -F .superpowers/msg-f154-t1.txt
```

Mensagem (`.superpowers/msg-f154-t1.txt`): `feat(meta_ads): sonda de alcance do system user, em tres estados (F154)` + linha em branco + o trailer.

---

### Task 2: O planejador recebe as recusas medidas

**Files:**
- Modify: `tests/unit/test_meta_reconcile_plan.py`
- Modify: `src/meta_ads/reconcile.py`
- Modify: `src/jobs/meta_resync.py` (transição: passa `ids_parceria - ids_alcance` até a Task 4)

**Interfaces:**
- Consumes: nada da Task 1.
- Produces: `build_plan(*, partnership_ids: set[str], refused_ids: set[str], inventory, complete, now, ...)` — o kwarg `reachable_ids` deixa de existir; `Plan.unreachable == sorted(partnership_ids & refused_ids)`.

- [ ] **Step 1: Converter os testes e escrever o do contrato novo** — aplique:

```diff
diff --git a/tests/unit/test_meta_reconcile_plan.py b/tests/unit/test_meta_reconcile_plan.py
index 26e5754..0469378 100644
--- a/tests/unit/test_meta_reconcile_plan.py
+++ b/tests/unit/test_meta_reconcile_plan.py
@@ -25,7 +25,7 @@ def inv(id_: str, ativo: bool = True, faltas: int = 0) -> InventoryRow:
 def test_conta_nova_da_parceria_entra() -> None:
     plano = build_plan(
         partnership_ids={"act_1", "act_2"},
-        reachable_ids={"act_1", "act_2"},
+        refused_ids=set(),
         inventory=[inv("act_1")],
         complete=True,
         now=AGORA,
@@ -39,7 +39,7 @@ def test_ausencia_na_parceria_conta_carencia_antes_de_remover() -> None:
     for faltas, espera_remocao in ((0, False), (1, False), (2, True)):
         plano = build_plan(
             partnership_ids={"act_1"},
-            reachable_ids={"act_1"},
+            refused_ids=set(),
             inventory=[inv("act_1"), inv("act_2", faltas=faltas)],
             complete=True,
             now=AGORA,
@@ -53,7 +53,7 @@ def test_leitura_incompleta_bloqueia_o_lado_destrutivo_mas_nao_o_aditivo() -> No
     """F93: pagina que falhou nao e churn. Adicionar segue seguro."""
     plano = build_plan(
         partnership_ids={"act_1", "act_novo"},
-        reachable_ids={"act_1"},
+        refused_ids={"act_novo"},
         inventory=[inv("act_1"), inv("act_sumiu", faltas=9)],
         complete=False,
         now=AGORA,
@@ -69,7 +69,7 @@ def test_guard_percentual_barra_remocao_em_massa() -> None:
     inventario = [inv(f"act_{i}", faltas=9) for i in range(10)]
     plano = build_plan(
         partnership_ids=set(),
-        reachable_ids=set(),
+        refused_ids=set(),
         inventory=inventario,
         complete=True,
         now=AGORA,
@@ -85,7 +85,7 @@ def test_conta_na_parceria_sem_su_e_sinalizada_nunca_removida() -> None:
     """A distincao que o F128 nao tinha: 'nao alcanco' != 'nao e mais nossa'."""
     plano = build_plan(
         partnership_ids={"act_1"},
-        reachable_ids=set(),
+        refused_ids={"act_1"},
         inventory=[inv("act_1")],
         complete=True,
         now=AGORA,
@@ -98,7 +98,7 @@ def test_conta_na_parceria_sem_su_e_sinalizada_nunca_removida() -> None:
 def test_conta_que_reaparece_zera_a_carencia() -> None:
     plano = build_plan(
         partnership_ids={"act_1"},
-        reachable_ids={"act_1"},
+        refused_ids=set(),
         inventory=[inv("act_1", faltas=2)],
         complete=True,
         now=AGORA,
@@ -110,7 +110,7 @@ def test_conta_que_reaparece_zera_a_carencia() -> None:
 def test_conta_ja_desativada_nao_reaparece_no_plano_destrutivo() -> None:
     plano = build_plan(
         partnership_ids=set(),
-        reachable_ids=set(),
+        refused_ids=set(),
         inventory=[inv("act_velha", ativo=False, faltas=9)],
         complete=True,
         now=AGORA,
@@ -133,7 +133,7 @@ def test_guard_mede_o_inventario_ativo_e_nao_so_os_ausentes() -> None:
 
     plano = build_plan(
         partnership_ids=partnership,
-        reachable_ids=partnership,
+        refused_ids=set(),
         inventory=inventario,
         complete=True,
         now=AGORA,
@@ -159,7 +159,7 @@ def test_teto_absoluto_e_o_vinculante_quando_a_conta_cresce() -> None:
 
     plano = build_plan(
         partnership_ids=parceria,
-        reachable_ids=parceria,
+        refused_ids=set(),
         inventory=inventario,
         complete=True,
         now=AGORA,
@@ -179,7 +179,7 @@ def test_teto_absoluto_e_o_vinculante_quando_a_conta_cresce() -> None:
     # simplesmente barrando tudo.
     plano_ok = build_plan(
         partnership_ids=parceria,
-        reachable_ids=parceria,
+        refused_ids=set(),
         inventory=[inv(f"act_p_{i}") for i in range(44)] + ausentes[:5],
         complete=True,
         now=AGORA,
@@ -203,7 +203,7 @@ def test_conta_nova_e_inalcancavel_sinaliza_no_mesmo_ciclo() -> None:
     """
     plano = build_plan(
         partnership_ids={"act_nova_sem_su", "act_ja_dentro"},
-        reachable_ids={"act_ja_dentro"},
+        refused_ids={"act_nova_sem_su"},
         inventory=[inv("act_ja_dentro")],
         complete=True,
         now=AGORA,
@@ -240,7 +240,7 @@ def test_retry_no_mesmo_dia_nao_soma_a_ausencia_ja_contada() -> None:
     )
     plano = build_plan(
         partnership_ids={"act_1"},
-        reachable_ids={"act_1"},
+        refused_ids=set(),
         inventory=[inv("act_1"), ja_contada],
         complete=True,
         now=AGORA,
@@ -267,7 +267,7 @@ def test_ausencia_carimbada_em_outro_dia_continua_somando() -> None:
     )
     plano = build_plan(
         partnership_ids={"act_1"},
-        reachable_ids={"act_1"},
+        refused_ids=set(),
         inventory=[inv("act_1"), de_ontem],
         complete=True,
         now=AGORA,
@@ -275,3 +275,20 @@ def test_ausencia_carimbada_em_outro_dia_continua_somando() -> None:
     )
     assert plano.to_remove == ["act_2"], "carencia parou de avancar em dia novo"
     assert plano.to_bump == []
+
+
+def test_conta_nao_medida_nao_e_sinalizada_como_inalcancavel() -> None:
+    """F154: `unreachable` sao as RECUSAS medidas, nao "tudo que nao foi lido".
+
+    Antes o alcance era `parceria - indice`, e a CHUTE 07 — lida pelo system user, mas
+    ausente de `/me/adaccounts` — saia como inalcancavel todo dia. Conta que a sonda nao
+    conseguiu medir (token, limite, timeout) tambem nao entra: nao medido nao e resposta.
+    """
+    plano = build_plan(
+        partnership_ids={"act_lida", "act_nao_medida", "act_recusada"},
+        refused_ids={"act_recusada"},
+        inventory=[inv("act_lida"), inv("act_nao_medida"), inv("act_recusada")],
+        complete=True,
+        now=AGORA,
+    )
+    assert plano.unreachable == ["act_recusada"]
```

- [ ] **Step 2: Ver falhar**

Run: `python -m pytest tests/unit/test_meta_reconcile_plan.py -p no:cacheprovider`
Expected: `13 failed` — todos com `TypeError: build_plan() got an unexpected keyword argument 'refused_ids'`.

- [ ] **Step 3: Implementar** — aplique os dois blocos:

```diff
diff --git a/src/meta_ads/reconcile.py b/src/meta_ads/reconcile.py
index 564537f..505b6c0 100644
--- a/src/meta_ads/reconcile.py
+++ b/src/meta_ads/reconcile.py
@@ -80,7 +80,7 @@ def _faltas_com_esta_execucao(r: InventoryRow, *, now: datetime) -> int:
 def build_plan(
     *,
     partnership_ids: set[str],
-    reachable_ids: set[str],
+    refused_ids: set[str],
     inventory: list[InventoryRow],
     complete: bool,
     now: datetime,
@@ -88,7 +88,7 @@ def build_plan(
     max_removal_ratio: float = 0.2,
     max_removal_abs: int = 5,
 ) -> Plan:
-    """(parceria, alcance, inventário, instante) → plano.
+    """(parceria, recusas medidas, inventário, instante) → plano.
 
     Aditivo sempre; destrutivo só com leitura completa e dentro do teto.
 
@@ -110,7 +110,12 @@ def build_plan(
     # do upsert) apagava justamente a conta nova-e-inalcançável, que é o caso
     # real em produção (`CA - V4 Lima Soares`, `CHUTE 07`): ela entra por
     # `to_add` no mesmo ciclo, e o audit reportaria `unreachable: 0` no dia 1.
-    unreachable = sorted(partnership_ids - reachable_ids)
+    #
+    # F154: `refused_ids` sao as RECUSAS medidas pela sonda (`meta_ads.alcance`), nao o
+    # complemento de um indice. `parceria - alcancadas` punha no sinal tambem o que nao foi
+    # lido — a CHUTE 07, lida pelo system user e ausente de `/me/adaccounts`, saia como
+    # inalcancavel todo dia. Conta nao medida fica fora: nao medido nao e resposta.
+    unreachable = sorted(partnership_ids & refused_ids)
     to_reset = sorted(
         r.ad_account_id for r in ativos if r.missed_syncs and r.ad_account_id in partnership_ids
     )
```

```diff
diff --git a/src/jobs/meta_resync.py b/src/jobs/meta_resync.py
index bbcf404..054b4d5 100644
--- a/src/jobs/meta_resync.py
+++ b/src/jobs/meta_resync.py
@@ -106,7 +106,8 @@ async def reconcile_meta(conn: asyncpg.Connection, *, now: datetime | None = Non
         inventario = await meta_ad_accounts.list_inventory_rows(conn)
         plano = build_plan(
             partnership_ids=ids_parceria,
-            reachable_ids=ids_alcance,
+            # O complemento do indice, por enquanto: a sonda da Task 4 substitui a fonte.
+            refused_ids=ids_parceria - ids_alcance,
             inventory=inventario,
             complete=leitura_completa,
             # O MESMO instante que carimba as ausências abaixo.
```

- [ ] **Step 4: Ver passar**

Run: `python -m pytest tests/unit/test_meta_reconcile_plan.py tests/unit/test_meta_reconcile_job.py tests/unit/test_meta_resync_audit.py tests/unit/test_job_partial_failure_audit.py -p no:cacheprovider`
Expected: `27 passed`.

- [ ] **Step 5: Gate e commit**

```bash
python scripts/check_pre_push.py > .superpowers/gate-f154-t2.log 2>&1 && git add tests/unit/test_meta_reconcile_plan.py src/meta_ads/reconcile.py src/jobs/meta_resync.py && git commit -F .superpowers/msg-f154-t2.txt
```

Mensagem: `fix(meta_ads): o plano recebe as recusas medidas, nao o complemento do indice (F154)` + trailer.

---

### Task 3: `set_reachable` grava só o alcance medido

**Files:**
- Modify: `tests/integration/test_meta_reconcile_repo.py`, `tests/integration/test_web_panel_admin.py`, `tests/unit/test_meta_reconcile_job.py`
- Modify: `src/db/repositories/meta_ad_accounts.py`
- Modify: `src/jobs/meta_resync.py` (transição: `le`/`recusa` derivados do índice, com o no-op do F85 para índice vazio)

**Interfaces:**
- Consumes: nada das tasks anteriores.
- Produces: `async def set_reachable(conn, *, le: list[str], recusa: list[str], scope_ids: list[str]) -> None` — o kwarg `reachable_ids` deixa de existir.

- [ ] **Step 1: Converter os chamadores e escrever o teste de conta não medida** — aplique os três blocos:

```diff
diff --git a/tests/integration/test_meta_reconcile_repo.py b/tests/integration/test_meta_reconcile_repo.py
index 5715885..4c478eb 100644
--- a/tests/integration/test_meta_reconcile_repo.py
+++ b/tests/integration/test_meta_reconcile_repo.py
@@ -301,7 +301,7 @@ async def test_lista_vazia_e_noop_em_todas_as_operacoes(db) -> None:
 
         assert await meta_ad_accounts.deactivate(conn, ad_account_ids=[]) == 0
         await meta_ad_accounts.apply_absences(conn, bump=[], reset=[])
-        await meta_ad_accounts.set_reachable(conn, reachable_ids=[], scope_ids=["act_1"])
+        await meta_ad_accounts.set_reachable(conn, le=[], recusa=[], scope_ids=["act_1"])
 
         assert len(await meta_ad_accounts.list_all(conn)) == 2
         assert (await meta_ad_accounts.get_by_id(conn, "act_1")).su_reachable is True
@@ -313,13 +313,40 @@ async def test_set_reachable_marca_quem_esta_fora_do_alcance(db) -> None:
         await meta_ad_accounts.upsert_many(conn, [CONTA, OUTRA])
 
         await meta_ad_accounts.set_reachable(
-            conn, reachable_ids=["act_1"], scope_ids=["act_1", "act_2"]
+            conn, le=["act_1"], recusa=["act_2"], scope_ids=["act_1", "act_2"]
         )
 
         assert (await meta_ad_accounts.get_by_id(conn, "act_1")).su_reachable is True
         assert (await meta_ad_accounts.get_by_id(conn, "act_2")).su_reachable is False
 
 
+@pytest.mark.integration
+async def test_set_reachable_nao_toca_em_conta_nao_medida(db) -> None:
+    """F154: conta que a sonda nao conseguiu medir fica com o ULTIMO valor medido.
+
+    Com o indice, "nao veio" virava `false`: um timeout ou um token recusado apagaria o
+    alcance de quem o SU le. Agora so grava o que tem resposta — nos dois sentidos.
+    """
+    async with db.acquire() as conn:
+        await meta_ad_accounts.upsert_many(conn, [CONTA, OUTRA])
+
+        # act_2 nao medida: segue true (o DEFAULT), nao vira false por nao ter vindo.
+        await meta_ad_accounts.set_reachable(
+            conn, le=["act_1"], recusa=[], scope_ids=["act_1", "act_2"]
+        )
+        assert (await meta_ad_accounts.get_by_id(conn, "act_2")).su_reachable is True
+
+        # act_2 recusada e depois nao medida: segue false, nao volta a true sozinha.
+        await meta_ad_accounts.set_reachable(
+            conn, le=[], recusa=["act_2"], scope_ids=["act_1", "act_2"]
+        )
+        await meta_ad_accounts.set_reachable(
+            conn, le=["act_1"], recusa=[], scope_ids=["act_1", "act_2"]
+        )
+        assert (await meta_ad_accounts.get_by_id(conn, "act_2")).su_reachable is False
+        assert (await meta_ad_accounts.get_by_id(conn, "act_1")).su_reachable is True
+
+
 @pytest.mark.integration
 async def test_set_reachable_nao_toca_em_conta_fora_do_escopo(db) -> None:
     """M4: o UPDATE e escopado a parceria.
@@ -334,7 +361,10 @@ async def test_set_reachable_nao_toca_em_conta_fora_do_escopo(db) -> None:
         # act_2 sai da parceria: fora do escopo do proximo set_reachable.
         await meta_ad_accounts.deactivate(conn, ad_account_ids=["act_2"])
 
-        await meta_ad_accounts.set_reachable(conn, reachable_ids=["act_1"], scope_ids=["act_1"])
+        # A recusa de act_2 vem medida, mas act_2 esta fora do escopo: nao grava.
+        await meta_ad_accounts.set_reachable(
+            conn, le=["act_1"], recusa=["act_2"], scope_ids=["act_1"]
+        )
 
         assert (await meta_ad_accounts.get_by_id(conn, "act_1")).su_reachable is True
         assert (await meta_ad_accounts.get_by_id(conn, "act_2")).su_reachable is True, (
@@ -626,7 +656,7 @@ async def test_list_queues_sem_su_tem_precedencia_sobre_sem_delegacao(db) -> Non
         # act_1 fica alcancavel (cai em sem_delegacao, o caso normal); act_2
         # fica de fora (sem SU E sem gestor — o caso que se sobrepunha).
         await meta_ad_accounts.set_reachable(
-            conn, reachable_ids=["act_1"], scope_ids=["act_1", "act_2"]
+            conn, le=["act_1"], recusa=["act_2"], scope_ids=["act_1", "act_2"]
         )
 
         queues = await meta_ad_accounts.list_queues(conn)
```

```diff
diff --git a/tests/integration/test_web_panel_admin.py b/tests/integration/test_web_panel_admin.py
index 12664e5..5e6f74b 100644
--- a/tests/integration/test_web_panel_admin.py
+++ b/tests/integration/test_web_panel_admin.py
@@ -946,7 +946,8 @@ async def test_painel_meta_separa_as_tres_filas(client: AsyncClient) -> None:
         # fila 2: na parceria, mas o system user não foi atribuído
         await meta_ad_accounts.set_reachable(
             conn,
-            reachable_ids=["act_sem_delegacao", "act_saiu"],
+            le=["act_sem_delegacao", "act_saiu"],
+            recusa=["act_sem_su"],
             scope_ids=["act_sem_delegacao", "act_sem_su", "act_saiu"],
         )
         # fila 3: saiu da parceria — desativada e com o grant do gestor revogado
```

```diff
diff --git a/tests/unit/test_meta_reconcile_job.py b/tests/unit/test_meta_reconcile_job.py
index 824845a..a7290a9 100644
--- a/tests/unit/test_meta_reconcile_job.py
+++ b/tests/unit/test_meta_reconcile_job.py
@@ -157,7 +157,8 @@ async def test_dry_run_observa_tudo_e_so_deixa_de_destruir() -> None:
     )
     assert all(isinstance(dia, date) for _aid, dia in absencias.await_args.kwargs["bump"])
     marca_alcance.assert_awaited_once()
-    assert marca_alcance.await_args.kwargs["reachable_ids"] == ["act_1"]
+    assert marca_alcance.await_args.kwargs["le"] == ["act_1"]
+    assert marca_alcance.await_args.kwargs["recusa"] == []
     # M4: o UPDATE é escopado à parceria — sem WHERE ele marcava su_reachable
     # também em conta inativa/fora da parceria, ruído num sinal que só faz
     # sentido para quem ESTÁ na parceria (spec §3).
@@ -209,8 +210,8 @@ async def test_com_apply_ligado_desativa_e_revoga_e_audita_a_conta() -> None:
     # Gate: a plataforma é obrigatória e FIXADA no call-site (sabotagem 2).
     assert audita.await_args.kwargs["platform"] == "meta"
     # Req. 3: alcance só é marcado com a leitura completa (aqui, complete=True
-    # nos dois lados) — reachable_ids reflete exatamente o que foi lido.
-    assert marca_alcance.await_args.kwargs["reachable_ids"] == ["act_1"]
+    # nos dois lados) — `le` reflete exatamente o que foi lido.
+    assert marca_alcance.await_args.kwargs["le"] == ["act_1"]
     # Req. 1: absences + alcance + desativação + revogação + a auditoria da
     # revogação inteiras dentro de UMA transação — tudo ou nada.
     conn.transaction.assert_called_once()
```

- [ ] **Step 2: Ver falhar** (precisa de Docker — testcontainers):

Run: `python -m pytest -m integration tests/integration/test_meta_reconcile_repo.py -p no:cacheprovider -k "set_reachable or lista_vazia or sem_su_tem_precedencia"`
Expected: `5 failed, 21 deselected` — todos com `TypeError: set_reachable() got an unexpected keyword argument 'le'`.

- [ ] **Step 3: Implementar** — aplique os dois blocos:

```diff
diff --git a/src/db/repositories/meta_ad_accounts.py b/src/db/repositories/meta_ad_accounts.py
index e95c3c4..8b2a049 100644
--- a/src/db/repositories/meta_ad_accounts.py
+++ b/src/db/repositories/meta_ad_accounts.py
@@ -196,9 +196,14 @@ async def deactivate(conn: asyncpg.Connection, *, ad_account_ids: list[str]) ->
 
 
 async def set_reachable(
-    conn: asyncpg.Connection, *, reachable_ids: list[str], scope_ids: list[str]
+    conn: asyncpg.Connection, *, le: list[str], recusa: list[str], scope_ids: list[str]
 ) -> None:
-    """Marca alcance do system user. NÃO desativa: alcance ≠ pertencer à parceria.
+    """Grava o alcance MEDIDO do system user. NÃO desativa: alcance ≠ pertencer à parceria.
+
+    F154: `le` e `recusa` vêm da sonda (`meta_ads.alcance`) — `true` para quem ela leu,
+    `false` para quem recusou com `#200`. Conta que a sonda não conseguiu medir não é
+    tocada: fica o último valor medido. Antes o sinal era `id ∈ /me/adaccounts`, e "não
+    veio" virava `false` — um índice que omitia a CHUTE 07, lida pelo system user.
 
     `scope_ids` é obrigatório de propósito (M4 da revisão de branch): sem o
     `WHERE`, o UPDATE marcava `su_reachable = false` também em conta inativa ou
@@ -207,16 +212,17 @@ async def set_reachable(
     Kwarg obrigatório em vez de default: quem chama tem de dizer sobre qual
     conjunto está afirmando alcance (lição F57).
 
-    Lista de alcance vazia continua sendo no-op (F85): "o SU não lê NADA" quase
-    sempre é falha de leitura, não estado real — e apagaria o sinal da conta
-    inteira do BM de uma vez.
+    Nada medido é no-op. Recusa em todas as contas, ao contrário do índice vazio do F85,
+    é estado real: cada `false` tem uma resposta `#200` por trás.
     """
-    if not reachable_ids or not scope_ids:
+    if not scope_ids or not (le or recusa):
         return
     await conn.execute(
         "UPDATE meta_ad_accounts SET su_reachable = (ad_account_id = ANY($1::text[])) "
-        "WHERE ad_account_id = ANY($2::text[])",
-        reachable_ids,
+        "WHERE ad_account_id = ANY($3::text[]) "
+        "AND (ad_account_id = ANY($1::text[]) OR ad_account_id = ANY($2::text[]))",
+        le,
+        recusa,
         scope_ids,
     )
 
```

```diff
diff --git a/src/jobs/meta_resync.py b/src/jobs/meta_resync.py
index 054b4d5..ace42b8 100644
--- a/src/jobs/meta_resync.py
+++ b/src/jobs/meta_resync.py
@@ -145,16 +145,17 @@ async def reconcile_meta(conn: asyncpg.Connection, *, now: datetime | None = Non
         fusos = {r.ad_account_id: r.timezone_name for r in inventario}
         bump = [(aid, account_today(fusos[aid], now=agora)) for aid in plano.to_bump]
         await meta_ad_accounts.apply_absences(conn, bump=bump, reset=plano.to_reset)
-        if leitura_completa:
-            # `leitura_completa`, NÃO `aplicado`: confundir os dois foi o
-            # C2. O que o alcance exige é a leitura inteira de
-            # /me/adaccounts — sobre página truncada, "não veio" significa
-            # "não li", e marcar su_reachable=false inventaria um sinal
-            # falso. Que a trava de rollout esteja ligada ou não é outra
-            # pergunta, e não é esta.
+        # `leitura_completa`, NÃO `aplicado`: confundir os dois foi o C2. O que o
+        # alcance exige é a leitura inteira de /me/adaccounts — sobre página
+        # truncada, "não veio" significa "não li", e marcar su_reachable=false
+        # inventaria um sinal falso. Que a trava de rollout esteja ligada ou não é
+        # outra pergunta, e não é esta. Índice vazio segue no-op (F85) até a sonda
+        # da Task 4 substituir a fonte.
+        if leitura_completa and ids_alcance:
             await meta_ad_accounts.set_reachable(
                 conn,
-                reachable_ids=sorted(ids_alcance),
+                le=sorted(ids_parceria & ids_alcance),
+                recusa=sorted(ids_parceria - ids_alcance),
                 scope_ids=sorted(ids_parceria),
             )
 
```

- [ ] **Step 4: Ver passar**

Run: `python -m pytest -m integration tests/integration/test_meta_reconcile_repo.py tests/integration/test_web_panel_admin.py -p no:cacheprovider` → `61 passed` (os warnings de cookie por request do httpx são do `test_web_panel_admin.py` e anteriores a esta mudança). E `python -m pytest tests/unit/test_meta_reconcile_job.py -p no:cacheprovider` → verde.

- [ ] **Step 5: Provar a mordida** — o teste de conta não medida tem de cair com a lógica antiga sob a assinatura nova. Copie o repositório para `.superpowers/meta_ad_accounts.py.bak`, troque no UPDATE de `set_reachable` a condição `"WHERE ad_account_id = ANY($3::text[]) " "AND (ad_account_id = ANY($1::text[]) OR ad_account_id = ANY($2::text[]))"` por `"WHERE ad_account_id = ANY($3::text[]) AND cardinality($2::text[]) >= 0"`, rode `python -m pytest -m integration tests/integration/test_meta_reconcile_repo.py -p no:cacheprovider -k nao_medida` → **1 failed**; restaure da cópia e confira `1 passed`.

- [ ] **Step 6: Gate e commit**

```bash
python scripts/check_pre_push.py > .superpowers/gate-f154-t3.log 2>&1 && git add tests/integration/test_meta_reconcile_repo.py tests/integration/test_web_panel_admin.py tests/unit/test_meta_reconcile_job.py src/db/repositories/meta_ad_accounts.py src/jobs/meta_resync.py && git commit -F .superpowers/msg-f154-t3.txt
```

Mensagem: `fix(db): set_reachable grava so o alcance medido; conta nao medida fica (F154)` + trailer.

---

### Task 4: O job mede o alcance pela sonda; o desligamento depende só da parceria

**Files:**
- Modify: `tests/unit/test_meta_reconcile_job.py`, `tests/unit/test_meta_resync_audit.py`, `tests/unit/test_job_partial_failure_audit.py`, `tests/integration/test_meta_reconcile_repo.py`
- Modify: `src/jobs/meta_resync.py`

**Interfaces:**
- Consumes: `sondar_alcance`, `Alcance` (Task 1); `build_plan(refused_ids=)` (Task 2); `set_reachable(le=, recusa=, scope_ids=)` (Task 3).
- Produces: `reconcile_meta` sem `/me/adaccounts`; `params_summary` do `meta_reconcile` com `alcance_nao_medido`; `complete` = só a parceria.

- [ ] **Step 1: Trocar os dublês do índice pela sonda e escrever os dois testes novos** — aplique os quatro blocos:

```diff
diff --git a/tests/unit/test_meta_reconcile_job.py b/tests/unit/test_meta_reconcile_job.py
index a7290a9..082b2fb 100644
--- a/tests/unit/test_meta_reconcile_job.py
+++ b/tests/unit/test_meta_reconcile_job.py
@@ -22,13 +22,14 @@ from unittest.mock import AsyncMock, MagicMock, patch
 import pytest
 
 from src.db.repositories.manager_meta_account_access import PARTNERSHIP_ENDED_REASON
+from src.meta_ads.alcance import Alcance
 from src.meta_ads.partnership import PartnershipSnapshot
 from src.meta_ads.reconcile import InventoryRow
 
 
 def _patches(job, *, apply: bool, parceria: list[str]):
-    """Setup comum: settings + as duas leituras (parceria completa, alcance
-    completo) + o `conn` que os testes passam a `reconcile_meta`.
+    """Setup comum: settings + a parceria completa + a sonda de alcance (todas as
+    contas lidas) + o `conn` que os testes passam a `reconcile_meta`.
     `record_job_run` vem à parte (`gravar_run`) porque alguns testes precisam
     inspecionar a chamada depois do `with`.
 
@@ -37,8 +38,6 @@ def _patches(job, *, apply: bool, parceria: list[str]):
     `patch` sobrando em `connection.get_pool` desarmaria justamente essa
     invariante — se alguém reintroduzisse o `pool.acquire()` interno, o mock o
     faria passar verde."""
-    from src.auth.meta_oauth import AdAccountsFetch
-
     conn = MagicMock()
     conn.execute = AsyncMock(return_value="UPDATE 0")
     gravar_run = AsyncMock()
@@ -62,11 +61,7 @@ def _patches(job, *, apply: bool, parceria: list[str]):
             ),
         ),
         patch.object(
-            job,
-            "_fetch_all_adaccounts",
-            AsyncMock(
-                return_value=AdAccountsFetch(accounts=[{"id": i} for i in parceria], complete=True)
-            ),
+            job, "sondar_alcance", AsyncMock(return_value=Alcance(le=frozenset(parceria)))
         ),
         patch.object(job, "record_job_run", gravar_run),
     ]
@@ -254,7 +249,6 @@ async def test_leitura_parcial_bloqueia_aplicacao_mesmo_com_apply_ligado() -> No
     Este é o outro lado do C2: a observação sai da trava do flag, mas NÃO sai da
     exigência de leitura completa. `set_reachable` sobre página truncada
     marcaria "sem SU" em conta que simplesmente não veio na página."""
-    from src.auth.meta_oauth import AdAccountsFetch
     from src.jobs import meta_resync as job
 
     conn = MagicMock()
@@ -278,9 +272,7 @@ async def test_leitura_parcial_bloqueia_aplicacao_mesmo_com_apply_ligado() -> No
             ),
         ),
         patch.object(
-            job,
-            "_fetch_all_adaccounts",
-            AsyncMock(return_value=AdAccountsFetch(accounts=[{"id": "act_1"}], complete=True)),
+            job, "sondar_alcance", AsyncMock(return_value=Alcance(le=frozenset({"act_1"})))
         ),
         patch.object(
             job.meta_ad_accounts,
@@ -381,3 +373,106 @@ async def test_reconcile_dos_dois_lados_exige_a_conexao_de_quem_chama() -> None:
             f"{fn.__qualname__}: `conn` voltou a ter default — quem chama pode "
             "omitir a conexão e abrir uma segunda transação por baixo da dele"
         )
+
+
+@pytest.mark.asyncio
+async def test_alcance_vem_da_sonda_e_o_indice_nao_e_chamado() -> None:
+    """F154: o alcance e medido por conta, e `/me/adaccounts` saiu do job.
+
+    Rede por `respx` em modo estrito: qualquer chamada nao mockada levanta. A parceria vem
+    das duas edges do BM; `act_1` le (200) e `act_2` recusa com `#200` — a forma medida em
+    27/09. Se o job voltasse a ler o indice, o `/me/adaccounts` nao teria rota.
+    """
+    import httpx
+    import respx
+
+    from src.jobs import meta_resync as job
+
+    grafo = "https://graph.facebook.com/v22.0"
+    contas = {
+        "data": [
+            {"id": "act_1", "name": "Lida", "timezone_name": "America/Sao_Paulo"},
+            {"id": "act_2", "name": "Recusa", "timezone_name": "America/Sao_Paulo"},
+        ]
+    }
+    recusa = {"error": {"code": 200, "message": "(#200) Ad account owner has NOT grant"}}
+    settings = MagicMock(
+        meta_system_user_token="tok", meta_business_id="bm", meta_reconcile_apply=False
+    )
+    conn = MagicMock()
+    conn.execute = AsyncMock(return_value="UPDATE 0")
+    marca_alcance = AsyncMock()
+    gravar_run = AsyncMock()
+    with respx.mock(assert_all_called=True) as rede, ExitStack() as stack:
+        rede.get(f"{grafo}/bm/client_ad_accounts").mock(
+            return_value=httpx.Response(200, json=contas)
+        )
+        rede.get(f"{grafo}/bm/owned_ad_accounts").mock(
+            return_value=httpx.Response(200, json={"data": []})
+        )
+        rede.get(f"{grafo}/act_1/insights").mock(
+            return_value=httpx.Response(200, json={"data": []})
+        )
+        rede.get(f"{grafo}/act_2/insights").mock(return_value=httpx.Response(403, json=recusa))
+        for p in [
+            patch.object(job, "get_settings", MagicMock(return_value=settings)),
+            patch.object(job.meta_ad_accounts, "list_inventory_rows", AsyncMock(return_value=[])),
+            patch.object(job.meta_ad_accounts, "upsert_many", AsyncMock(return_value=2)),
+            patch.object(job.meta_ad_accounts, "apply_absences", AsyncMock()),
+            patch.object(job.meta_ad_accounts, "set_reachable", marca_alcance),
+            patch.object(job, "record_job_run", gravar_run),
+        ]:
+            stack.enter_context(p)
+        plano = await job.reconcile_meta(conn)
+
+    assert marca_alcance.await_args.kwargs["le"] == ["act_1"]
+    assert marca_alcance.await_args.kwargs["recusa"] == ["act_2"]
+    assert plano.unreachable == ["act_2"]
+    resumo = gravar_run.await_args.kwargs["params_summary"]
+    assert resumo["unreachable"] == 1
+    assert resumo["alcance_nao_medido"] == 0
+
+
+@pytest.mark.asyncio
+async def test_desligamento_nao_depende_do_alcance() -> None:
+    """F154 fecha o M10: com a parceria inteira lida, o desligamento roda mesmo que a
+    sonda nao tenha medido conta nenhuma (token recusado, limite, rede).
+
+    Antes a completude era `parceria AND /me/adaccounts`: uma indisponibilidade do indice —
+    que desde a spec 2026-08-20 §3 nao define o inventario — congelava o offboarding e
+    gravava `status=error` todo dia.
+    """
+    from src.jobs import meta_resync as job
+
+    conn, gravar_run, ps = _patches(job, apply=True, parceria=["act_1"])
+    desativa = AsyncMock(return_value=1)
+    with ExitStack() as stack:
+        for p in [
+            *ps,
+            patch.object(
+                job,
+                "sondar_alcance",
+                AsyncMock(return_value=Alcance(nao_medido=frozenset({"act_1"}))),
+            ),
+            patch.object(
+                job.meta_ad_accounts,
+                "list_inventory_rows",
+                AsyncMock(return_value=[InventoryRow("act_2", True, 9)]),
+            ),
+            patch.object(job.meta_ad_accounts, "upsert_many", AsyncMock(return_value=1)),
+            patch.object(job.meta_ad_accounts, "apply_absences", AsyncMock()),
+            patch.object(job.meta_ad_accounts, "set_reachable", AsyncMock()),
+            patch.object(job.meta_ad_accounts, "deactivate", desativa),
+            patch.object(
+                job.manager_meta_account_access, "revoke_for_account", AsyncMock(return_value=[])
+            ),
+            patch.object(job, "record_access_revocation", AsyncMock()),
+        ]:
+            stack.enter_context(p)
+        plano = await job.reconcile_meta(conn)
+
+    assert plano.blocked_reason is None
+    assert desativa.await_args.kwargs["ad_account_ids"] == ["act_2"]
+    resumo = gravar_run.await_args.kwargs["params_summary"]
+    assert resumo["complete"] is True
+    assert resumo["alcance_nao_medido"] == 1
```

```diff
diff --git a/tests/unit/test_meta_resync_audit.py b/tests/unit/test_meta_resync_audit.py
index 99d26b3..3311505 100644
--- a/tests/unit/test_meta_resync_audit.py
+++ b/tests/unit/test_meta_resync_audit.py
@@ -13,8 +13,8 @@ from unittest.mock import AsyncMock, MagicMock
 
 import pytest
 
-from src.auth.meta_oauth import AdAccountsFetch
 from src.jobs import meta_resync
+from src.meta_ads.alcance import Alcance
 from src.meta_ads.partnership import PartnershipSnapshot
 
 
@@ -53,9 +53,7 @@ async def test_reconcile_meta_records_audit(monkeypatch: pytest.MonkeyPatch) ->
         ),
     )
     monkeypatch.setattr(
-        meta_resync,
-        "_fetch_all_adaccounts",
-        AsyncMock(return_value=AdAccountsFetch(accounts=[{"id": "act_1"}], complete=True)),
+        meta_resync, "sondar_alcance", AsyncMock(return_value=Alcance(le=frozenset({"act_1"})))
     )
     monkeypatch.setattr(meta_resync.meta_ad_accounts, "upsert_many", AsyncMock(return_value=1))
     monkeypatch.setattr(
@@ -112,9 +110,7 @@ async def test_reconcile_meta_record_job_run_failure_is_non_fatal(
         ),
     )
     monkeypatch.setattr(
-        meta_resync,
-        "_fetch_all_adaccounts",
-        AsyncMock(return_value=AdAccountsFetch(accounts=[{"id": "act_1"}], complete=True)),
+        meta_resync, "sondar_alcance", AsyncMock(return_value=Alcance(le=frozenset({"act_1"})))
     )
     monkeypatch.setattr(meta_resync.meta_ad_accounts, "upsert_many", AsyncMock(return_value=1))
     monkeypatch.setattr(
```

```diff
diff --git a/tests/unit/test_job_partial_failure_audit.py b/tests/unit/test_job_partial_failure_audit.py
index 6f5fd1e..f5dbd56 100644
--- a/tests/unit/test_job_partial_failure_audit.py
+++ b/tests/unit/test_job_partial_failure_audit.py
@@ -100,15 +100,15 @@ async def test_fetch_completo_quando_paginacao_termina_naturalmente() -> None:
 def _patch_resync(
     monkeypatch: pytest.MonkeyPatch, *, parceria_accounts: list, complete: bool
 ) -> tuple[AsyncMock, AsyncMock, MagicMock]:
-    """Troca as duas leituras (`fetch_partnership` + `_fetch_all_adaccounts`,
-    ambas com o mesmo `complete`) e o passo destrutivo do plano por dublês.
+    """Troca a parceria (`fetch_partnership`, com o `complete` pedido), a sonda de
+    alcance (todas as contas lidas) e o passo destrutivo do plano por dublês.
 
     O inventário fixo (`act_ausente`, ativo, `missed_syncs=2`) nunca está na
     parceria — cruza o limiar (`2 + 1 >= 3`) sempre que `complete=True`, o que
     faz `build_plan()` propor remoção e exercita `deactivate`/`revoke_for_account`
     de verdade no teste do caminho feliz.
     """
-    from src.auth.meta_oauth import AdAccountsFetch
+    from src.meta_ads.alcance import Alcance
 
     settings = MagicMock()
     settings.meta_system_user_token = "tok"
@@ -122,12 +122,9 @@ def _patch_resync(
     )
     monkeypatch.setattr(
         meta_resync,
-        "_fetch_all_adaccounts",
+        "sondar_alcance",
         AsyncMock(
-            return_value=AdAccountsFetch(
-                accounts=[{"id": a["ad_account_id"]} for a in parceria_accounts],
-                complete=complete,
-            )
+            return_value=Alcance(le=frozenset(a["ad_account_id"] for a in parceria_accounts))
         ),
     )
     monkeypatch.setattr(
```

```diff
diff --git a/tests/integration/test_meta_reconcile_repo.py b/tests/integration/test_meta_reconcile_repo.py
index 4c478eb..249c01d 100644
--- a/tests/integration/test_meta_reconcile_repo.py
+++ b/tests/integration/test_meta_reconcile_repo.py
@@ -433,13 +433,13 @@ async def test_list_inventory_rows_traz_a_data_da_ultima_ausencia_meta(db) -> No
 
 
 def _patches_do_job(*, apply: bool):
-    """Settings + as duas leituras da rede (parceria vazia, alcance vazio).
+    """Settings + a rede (parceria vazia; a sonda de alcance sem conta a medir).
 
     Parceria vazia e completa e o cenario de churn: a conta semeada esta ATIVA
     no inventario e nao esta na parceria, entao `build_plan` a manda pro
     `to_bump` (carencia 0 + 1 = 1 < limiar 3). O banco e real; so a rede sai.
     """
-    from src.auth.meta_oauth import AdAccountsFetch
+    from src.meta_ads.alcance import Alcance
     from src.meta_ads.partnership import PartnershipSnapshot
 
     return [
@@ -459,11 +459,7 @@ def _patches_do_job(*, apply: bool):
             "fetch_partnership",
             AsyncMock(return_value=PartnershipSnapshot([], True)),
         ),
-        patch.object(
-            meta_resync,
-            "_fetch_all_adaccounts",
-            AsyncMock(return_value=AdAccountsFetch(accounts=[], complete=True)),
-        ),
+        patch.object(meta_resync, "sondar_alcance", AsyncMock(return_value=Alcance())),
     ]
 
 
```

- [ ] **Step 2: Ver falhar**

Run: `python -m pytest tests/unit/test_meta_reconcile_job.py tests/unit/test_meta_resync_audit.py tests/unit/test_job_partial_failure_audit.py -p no:cacheprovider`
Expected: `11 failed, 5 passed` — dez com `AttributeError: <module 'src.jobs.meta_resync' ...> does not have the attribute 'sondar_alcance'` (os dublês novos), e `test_alcance_vem_da_sonda_e_o_indice_nao_e_chamado` com `respx.models.AllMockedAssertionError: ... /me/adaccounts ... not mocked!` — o vermelho que importa: o job ainda lê o índice.

- [ ] **Step 3: Implementar** — aplique:

```diff
diff --git a/src/jobs/meta_resync.py b/src/jobs/meta_resync.py
index ace42b8..fdfdf32 100644
--- a/src/jobs/meta_resync.py
+++ b/src/jobs/meta_resync.py
@@ -3,10 +3,10 @@
 Roda piggyback no fim do job diário account_resync (mesmo Cloud Run Job +
 Cloud Scheduler) pra que conta de cliente nova entre no inventário zero-touch.
 
-Le duas fontes: `fetch_partnership` (autoritativa — a edge do BM, spec
-2026-08-20) e `_fetch_all_adaccounts` (o alcance do system user via
-/me/adaccounts). `build_plan` decide o que fazer com as duas; este módulo só
-aplica. Grants seguem MANUAIS (Modelo B): reconciliar nunca CONCEDE acesso —
+Le a parceria (`fetch_partnership`, autoritativa — a edge do BM, spec
+2026-08-20) e MEDE o alcance do system user com uma leitura mínima por conta da
+parceria (`meta_ads.alcance`, F154) — não mais pelo índice `/me/adaccounts`, que
+omitia conta que o SU lê. `build_plan` decide; este módulo só aplica. Grants seguem MANUAIS (Modelo B): reconciliar nunca CONCEDE acesso —
 só ajusta o inventário e, quando uma conta sai da parceria, revoga o que os
 gestores tinham.
 
@@ -21,7 +21,6 @@ import asyncpg
 import httpx
 import structlog
 
-from src.auth.meta_oauth import _fetch_all_adaccounts
 from src.clock import account_today
 from src.config import get_settings
 from src.db import connection
@@ -29,6 +28,7 @@ from src.db.repositories import manager_meta_account_access, meta_ad_accounts
 from src.governance.bookkeeping import best_effort
 from src.jobs._audit import record_access_revocation, record_job_crash, record_job_run
 from src.logging import configure_logging
+from src.meta_ads.alcance import sondar_alcance
 from src.meta_ads.partnership import fetch_partnership
 from src.meta_ads.reconcile import Plan, build_plan
 
@@ -71,28 +71,34 @@ async def reconcile_meta(conn: asyncpg.Connection, *, now: datetime | None = Non
         log.warning("meta_reconcile_no_business_id")
         return Plan(blocked_reason="meta_business_id nao configurado")
 
+    # Lido antes da rede: a sonda resolve "ontem" no fuso de cada conta sobre este
+    # mesmo instante, e o carimbo das ausências abaixo também (C4/F141).
+    agora = now if now is not None else datetime.now(UTC)
     async with httpx.AsyncClient(timeout=60.0) as http:
         parceria = await fetch_partnership(
             http,
             access_token=settings.meta_system_user_token,
             business_id=settings.meta_business_id,
         )
-        alcance = await _fetch_all_adaccounts(http, settings.meta_system_user_token)
+        # F154: o alcance é MEDIDO — uma leitura mínima por conta da parceria, na
+        # forma das tools. O índice `/me/adaccounts` omitia conta que o SU lê (a
+        # CHUTE 07, em 27/09), e a fila do painel mandava atribuir um SU que já lia.
+        alcance = await sondar_alcance(
+            http,
+            access_token=settings.meta_system_user_token,
+            contas=[(a["ad_account_id"], a.get("timezone_name")) for a in parceria.accounts],
+            agora=agora,
+        )
 
     ids_parceria = {a["ad_account_id"] for a in parceria.accounts}
-    ids_alcance = {
-        i if i.startswith("act_") else f"act_{i}"
-        for i in (a.get("id", "") for a in alcance.accounts)
-    }
 
-    # M10 (registrado, não corrigido): o AND acopla as duas fontes que a §3
-    # desacopla de propósito. Falha para o lado seguro — sem as duas leituras
-    # inteiras nada é desativado —, mas o preço é real: indisponibilidade
-    # prolongada de `/me/adaccounts` (que não define mais o inventário) congela
-    # o offboarding e grava `status=error` todo dia, indefinidamente.
-    leitura_completa = parceria.complete and alcance.complete
+    # F154 fecha o M10: a completude é só a da parceria, a fonte autoritativa
+    # (spec 2026-08-20 §3). Antes era `parceria AND /me/adaccounts`, e uma
+    # indisponibilidade do índice — que não define o inventário — congelava o
+    # offboarding e gravava `status=error` todo dia. A sonda não entra aqui: conta
+    # não medida só deixa de ter o alcance atualizado, não bloqueia nada.
+    leitura_completa = parceria.complete
 
-    agora = now if now is not None else datetime.now(UTC)
     # Uma transação só pro bloco de escrita inteiro: metade aplicada
     # (carência somada sem desativar, ou desativada com grant ainda vivo) é
     # exatamente a inconsistência que este recurso existe pra evitar.
@@ -106,8 +112,8 @@ async def reconcile_meta(conn: asyncpg.Connection, *, now: datetime | None = Non
         inventario = await meta_ad_accounts.list_inventory_rows(conn)
         plano = build_plan(
             partnership_ids=ids_parceria,
-            # O complemento do indice, por enquanto: a sonda da Task 4 substitui a fonte.
-            refused_ids=ids_parceria - ids_alcance,
+            # F154: as recusas MEDIDAS (`#200`), não o complemento de um índice.
+            refused_ids=set(alcance.recusa),
             inventory=inventario,
             complete=leitura_completa,
             # O MESMO instante que carimba as ausências abaixo.
@@ -145,17 +151,15 @@ async def reconcile_meta(conn: asyncpg.Connection, *, now: datetime | None = Non
         fusos = {r.ad_account_id: r.timezone_name for r in inventario}
         bump = [(aid, account_today(fusos[aid], now=agora)) for aid in plano.to_bump]
         await meta_ad_accounts.apply_absences(conn, bump=bump, reset=plano.to_reset)
-        # `leitura_completa`, NÃO `aplicado`: confundir os dois foi o C2. O que o
-        # alcance exige é a leitura inteira de /me/adaccounts — sobre página
-        # truncada, "não veio" significa "não li", e marcar su_reachable=false
-        # inventaria um sinal falso. Que a trava de rollout esteja ligada ou não é
-        # outra pergunta, e não é esta. Índice vazio segue no-op (F85) até a sonda
-        # da Task 4 substituir a fonte.
-        if leitura_completa and ids_alcance:
+        # `leitura_completa`, NÃO `aplicado`: confundir os dois foi o C2 — a trava
+        # de rollout é outra pergunta. Com a parceria truncada o escopo também vem
+        # truncado, e o alcance espera a leitura inteira. Conta que a sonda não mediu
+        # não é tocada (`set_reachable` só grava `le`/`recusa`).
+        if leitura_completa:
             await meta_ad_accounts.set_reachable(
                 conn,
-                le=sorted(ids_parceria & ids_alcance),
-                recusa=sorted(ids_parceria - ids_alcance),
+                le=sorted(alcance.le),
+                recusa=sorted(alcance.recusa),
                 scope_ids=sorted(ids_parceria),
             )
 
@@ -209,13 +213,13 @@ async def reconcile_meta(conn: asyncpg.Connection, *, now: datetime | None = Non
                 "added": len(plano.to_add),
                 "removed": len(plano.to_remove),
                 "bumped": len(plano.to_bump),
+                # F154: só as recusas medidas; o que a sonda não mediu sai
+                # separado, para "não sei" não se passar por "não alcança".
                 "unreachable": len(plano.unreachable),
+                "alcance_nao_medido": len(alcance.nao_medido),
                 "revoked_grants": revogados,
-                # M3: a §9 nomeia `complete` explicitamente. Dá pra inferir de
-                # error_message == "leitura incompleta", mas essa string
-                # colapsa duas leituras diferentes (parceria vs
-                # /me/adaccounts) num motivo só — na triagem você não saberia
-                # qual falhou.
+                # M3: a §9 nomeia `complete` explicitamente. Desde o F154 ele é
+                # só a leitura da parceria — o alcance não bloqueia mais nada.
                 "complete": leitura_completa,
                 "applied": aplicado,
             },
```

- [ ] **Step 4: Ver passar**

Run: `python -m pytest tests/unit/test_meta_reconcile_job.py tests/unit/test_meta_resync_audit.py tests/unit/test_job_partial_failure_audit.py tests/unit/test_meta_reconcile_plan.py tests/unit/test_meta_alcance.py -p no:cacheprovider` → `39 passed`. E a integração: `python -m pytest -m integration tests/integration/test_meta_reconcile_repo.py tests/integration/test_web_panel_admin.py -p no:cacheprovider` → `61 passed`.

- [ ] **Step 5: Provar a mordida do M10** — copie `src/jobs/meta_resync.py` para `.superpowers/meta_resync.py.bak`, troque a linha `    leitura_completa = parceria.complete` por `    leitura_completa = parceria.complete and not alcance.nao_medido`, rode `python -m pytest tests/unit/test_meta_reconcile_job.py -p no:cacheprovider -k desligamento` → **1 failed** (`test_desligamento_nao_depende_do_alcance`); restaure da cópia e confira `1 passed`.

- [ ] **Step 6: Gate e commit**

```bash
python scripts/check_pre_push.py > .superpowers/gate-f154-t4.log 2>&1 && git add tests/unit/test_meta_reconcile_job.py tests/unit/test_meta_resync_audit.py tests/unit/test_job_partial_failure_audit.py tests/integration/test_meta_reconcile_repo.py src/jobs/meta_resync.py && git commit -F .superpowers/msg-f154-t4.txt
```

Mensagem: `fix(meta_ads): o job mede o alcance pela sonda; o desligamento depende so da parceria (F154)` + trailer.

---

### Task 5: Catálogo, estado-atual e nucleo.md

**Files:**
- Modify: `docs/operacao/findings-catalog.md`, `docs/operacao/estado-atual.md`, `docs/convencoes/nucleo.md`, `CLAUDE.md`

**Interfaces:** consome o que as tasks 1 a 4 fizeram (o texto do F154 descreve exatamente isso).

**O script, e não edições à mão:** ele exige cada âncora exatamente uma vez e **mede** o tamanho declarado do catálogo depois da edição (o guard `test_resumo_bate_com_o_detalhe.py` confere faixa e tamanho).

- [ ] **Step 1: Salvar o script** em `.superpowers/task5_f154_docs.py`, conteúdo exato:

```python
"""Task 5 do plano do F154: catalogo, estado-atual e nucleo.md.

Rode da raiz do repo: `python <este arquivo> AAAA-MM-DD` (a data do dia da execucao).
Cada ancora e exigida exatamente uma vez. O tamanho declarado do catalogo e MEDIDO depois
da edicao (o guard `test_resumo_bate_com_o_detalhe.py` confere faixa e tamanho).
"""

import pathlib
import re
import sys

DATA = sys.argv[1]
DIA = f"{DATA[8:10]}/{DATA[5:7]}"


def editar(caminho: str, pares: list[tuple[str, str]]) -> None:
    p = pathlib.Path(caminho)
    t = p.read_text(encoding="utf-8")
    for velho, novo in pares:
        assert t.count(velho) == 1, (caminho, t.count(velho), velho[:90])
        t = t.replace(velho, novo)
    p.write_text(t, encoding="utf-8", newline="\n")


# 1. catalogo: o F154 passa a CORRIGIDO
CAT = pathlib.Path("docs/operacao/findings-catalog.md")
texto = CAT.read_text(encoding="utf-8")
inicio = "**Fix candidato, nao decidido:** trocar a fonte do sinal"
fim = "**A escolha muda o contrato do painel e e do Wellington.**"
assert texto.count(inicio) == 1 and texto.count(fim) == 1
i = texto.index(inicio)
j = texto.index(fim, i) + len(fim)
DECISAO = f"""**Decisão (Wellington, 27/09): leitura mínima por conta** — spec
`2026-09-27-f154-alcance-pela-leitura-design.md`. **Medido em 27/09, e o confundidor caiu:** 25
contas ativas, `/me/adaccounts` com 24; a CHUTE 07 com `su_reachable = false` pelo menos desde
24/09, e o SU a lê (nó e `/insights` com `200`); conta sem acesso → `403` com `code 200`; token
inválido → `401` com `code 190`. A CA - V4 Lima Soares, a outra de 05/09, hoje aparece no índice:
ele é intermitente para uma e persistente para a outra.

**✅ CORRIGIDO {DATA} — o que foi feito:**

- **A sonda** (`src/meta_ads/alcance.py`): uma chamada `/insights` por conta da parceria, na forma
  das tools (`build_insights_call`, "ontem" no fuso da conta, timeout de 15 s), em três estados —
  lê (`200`), recusa (`4xx` com `code 200`, a única medida) e **não medido** (todo o resto, que
  não grava).
- **`set_reachable`** grava `true`/`false` só no que foi medido; conta não medida fica com o
  último valor.
- **`build_plan`** recebe as recusas medidas: `unreachable = parceria ∩ recusas`, não mais
  `parceria − índice`.
- **O job não chama mais `/me/adaccounts`, e a completude é só a da parceria — fecha o M10:** uma
  falha do alcance não congela mais o desligamento. O relatório ganhou `alcance_nao_medido`.
- **Guards, cada um medido vermelho:** o teste do job com `respx` estrito (o índice não tem rota;
  contra o código anterior caiu com `/me/adaccounts not mocked!`); conta não medida mantém o
  valor (a sabotagem com a lógica antiga o derruba); desligamento com todo o alcance não medido
  (a sabotagem que religa a completude ao alcance o derruba).

**Fora, com o motivo:** o gêmeo Google do `unreachable`; o `/me/adaccounts` do OAuth pessoal
(dormente desde o Modelo B); fila de "não medido" no painel (entra se o relatório mostrar a sonda
falhando com frequência); o motivo de o índice omitir a CHUTE 07 (a sonda o torna irrelevante
para o sinal)."""
texto = texto[:i] + DECISAO + texto[j:]
velho = "## F154 (MEDIUM, ABERTO) — `/me/adaccounts` nao e prova de alcance"
assert texto.count(velho) == 1
texto = texto.replace(
    velho, f"## F154 (MEDIUM, ✅ CORRIGIDO {DATA}) — `/me/adaccounts` nao e prova de alcance"
)
CAT.write_text(texto, encoding="utf-8", newline="\n")

# 2. estado-atual
EA = "docs/operacao/estado-atual.md"
editar(
    EA,
    [
        (
            "o `unreachable=1` é a CHUTE 07, igual desde\n  24/09 pelo menos.",
            "o `unreachable=1` é a CHUTE 07, igual desde\n  24/09 pelo menos — artefato do "
            f"índice `/me/adaccounts`, que o F154 tirou do job em {DIA} (a CHUTE 07 é lida).",
        ),
        (
            "3. **F154** (spec).\n4. **Infra e guards** (spec) — o resto dos sub-projetos 3 e 4.\n"
            "5. **`recommendation_subscription`** — tool de leitura no MCC.",
            "3. **Infra e guards** (spec) — o resto dos sub-projetos 3 e 4.\n"
            "4. **`recommendation_subscription`** — tool de leitura no MCC.",
        ),
        ("| **F154** | `/me/adaccounts` não é prova de alcance |\n", ""),
        ("**F193**, **F194** e **F195**.", "**F193**, **F194**, **F195** e **F154**."),
    ],
)
t = pathlib.Path(EA).read_text(encoding="utf-8")
ancora = "**Smoke de leitura do F195 em produção"
assert t.count(ancora) == 1
k = t.index("\n", t.index(ancora))
t = (
    t[:k]
    + "\n\n**Verificação do F154 — pendente**, na execução do `v4-ads-mcp-resync` seguinte ao "
    "deploy (a diária ou uma sob demanda): a CHUTE 07 com `su_reachable = true`, o `meta_reconcile` "
    'com `unreachable: 0` e `alcance_nao_medido: 0`, e no painel a fila "Sem o system user '
    'atribuído" vazia.' + t[k:]
)
pathlib.Path(EA).write_text(t, encoding="utf-8", newline="\n")

# 3. nucleo.md: de onde vem o sinal
editar(
    "docs/convencoes/nucleo.md",
    [
        (
            "`/me/adaccounts` NÃO define mais o inventário: alimenta só o sinal `su_reachable`.",
            "`/me/adaccounts` saiu do job (F154): o `su_reachable` vem de uma leitura mínima por "
            "conta da parceria (`src/meta_ads/alcance.py` — lê `200` / recusa `#200` / não medido, "
            "que não grava), e o desligamento depende só da leitura da parceria.",
        )
    ],
)

# 4. o tamanho declarado do catalogo, medido
linhas = len(CAT.read_text(encoding="utf-8").splitlines())
kb = round(CAT.stat().st_size / 1024)
aprox = round(linhas, -2)
for caminho, padrao, modelo in [
    (str(CAT), r"~\d+ linhas, \d+ KB, IDs de", f"~{aprox} linhas, {kb} KB, IDs de"),
    (
        "CLAUDE.md",
        r"\*\*F1–F195, ~\d+ linhas, \d+ KB\*\*",
        f"**F1–F195, ~{aprox} linhas, {kb} KB**",
    ),
    (EA, r"\(~[\d.]+ linhas, \d+ KB\)", f"(~{aprox:,} linhas, {kb} KB)".replace(",", ".", 1)),
]:
    p = pathlib.Path(caminho)
    t = p.read_text(encoding="utf-8")
    assert len(re.findall(padrao, t)) == 1, (caminho, padrao)
    p.write_text(re.sub(padrao, lambda _m, m=modelo: m, t), encoding="utf-8", newline="\n")
print("ok; catalogo:", linhas, "linhas,", kb, "KB")
```

- [ ] **Step 2: Rodar** da raiz do repo, com a data do dia:

```bash
python .superpowers/task5_f154_docs.py AAAA-MM-DD
```

Expected: `ok; catalogo: <n> linhas, <k> KB` (na validação: 5653 linhas, 572 KB). `AssertionError` é âncora que mudou — **não force**: pare e reporte.

- [ ] **Step 3: Conferir** — `git diff --stat` mostra 4 arquivos; `grep -n "^## F154" docs/operacao/findings-catalog.md` traz `✅ CORRIGIDO`.

- [ ] **Step 4: Gate e commit**

```bash
python scripts/check_pre_push.py > .superpowers/gate-f154-t5.log 2>&1 && git add docs/operacao/findings-catalog.md docs/operacao/estado-atual.md docs/convencoes/nucleo.md CLAUDE.md && git commit -F .superpowers/msg-f154-t5.txt
```

Mensagem: `docs(operacao): F154 - o alcance do system user medido pela leitura` + trailer.

---

## Depois das tasks

Passos do controlador:

1. **Full sweep** — `python scripts/check_pre_push_full.py` (Docker): mexe em repositório, job e integração.
2. **Revisão final da branch** e uma onda de correção se houver achado.
3. **PR contra `main`** com vigia de CI e auto-merge (método `merge`), com a **autorização nominal** do Wellington antes do push — o merge deploya e muda o que o job grava em produção.
4. **Verificação em produção** (spec §6): na execução do `v4-ads-mcp-resync` seguinte ao deploy (a diária ou uma sob demanda), a CHUTE 07 com `su_reachable = true`, o `meta_reconcile` com `unreachable: 0` e `alcance_nao_medido: 0`, e a fila "Sem o system user atribuído" vazia. Registrar no `estado-atual`.
