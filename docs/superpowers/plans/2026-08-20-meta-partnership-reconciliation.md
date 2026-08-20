# Reconciliação da parceria Meta — plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** fazer o MCP reconciliar o inventário e os acessos Meta contra a lista autoritativa da parceria do BM da V4, de modo que unidade que entra apareça no painel sem acesso e unidade que sai perca inventário e grants sozinha.

**Architecture:** o job diário passa a ler `client_ad_accounts ∪ owned_ad_accounts` do BM da V4 como estado desejado, e `/me/adaccounts` apenas como sinal de "o system user consegue ler". Um `build_plan()` **puro** transforma (parceria, alcance, inventário) num plano de três listas; o job aplica o plano em transação, com carência, guard percentual e dry-run. Revogação é soft e o gate passa a exigir conta ativa.

**Tech Stack:** Python 3.13, httpx, asyncpg (SQL cru), FastAPI + Jinja2, pytest + respx + testcontainers.

**Spec:** [`docs/superpowers/specs/2026-08-20-meta-partnership-reconciliation-design.md`](../specs/2026-08-20-meta-partnership-reconciliation-design.md)

## Global Constraints

- **Token da Graph vai no header `Authorization: Bearer`, nunca em `params`** (F82). Há guard AST em `tests/unit/test_no_secrets_in_query_params.py`.
- **SDK/HTTP de ads em caminho que atende request roda dentro de `run_blocking`** (F109). Os jobs deste plano rodam fora do event loop de request, então não se aplica — mas o gate (Task 5) é caminho de request e só faz SQL.
- **Toda leitura paginada devolve `complete`** e quem faz detecção destrutiva precisa checá-lo (F93).
- **Campo novo em `Settings` entra com default** (`= ""` / `= False`), espelhando `meta_system_user_token`. Assim os 3 Cloud Run Jobs não quebram na subida (F114) — mas o `deploy.yml` declara mesmo assim, senão a feature fica desligada em produção.
- **Migration nova nunca edita arquivo commitado** — cria `006_*.sql` e acrescenta o nome à lista de `tests/integration/test_migrations.py`.
- **`python scripts/check_pre_push.py` antes de cada commit.** Docker pode não estar disponível: os testes de integração deste plano validam no CI (`gh run view <id> --json conclusion`).
- Comentário em código e docstring em **pt-BR**, nomes de símbolo em inglês, seguindo o que já existe nos módulos tocados.

---

## Estrutura de arquivos

| Arquivo | Responsabilidade |
|---|---|
| `src/meta_ads/graph.py` (novo) | paginação genérica da Graph com contrato `complete` |
| `src/meta_ads/partnership.py` (novo) | busca as duas edges do BM e normaliza para o payload do inventário |
| `src/meta_ads/reconcile.py` (novo) | `build_plan()` puro + travas de segurança como decisão, não como efeito |
| `src/auth/meta_oauth.py` | passa a delegar a paginação para `graph.py` |
| `src/db/migrations/006_meta_partnership_reconciliation.sql` (novo) | `su_reachable` + `revoked_at`/`revoked_reason` |
| `src/db/repositories/meta_ad_accounts.py` | aplica o plano no inventário (sem decidir nada) |
| `src/db/repositories/manager_meta_account_access.py` | revogação soft, restauração e o gate com JOIN |
| `src/config.py` | `meta_business_id`, `meta_reconcile_apply` |
| `.github/workflows/deploy.yml` | declara as duas env vars nos 3 jobs |
| `src/jobs/meta_resync.py` | orquestra: lê, planeja, aplica, audita |
| `src/web/routes.py` + `src/web/templates/admin/accounts_meta.html` | as três filas e o botão restaurar |

---

## Task 1: paginador compartilhado da Graph

**Files:**
- Create: `src/meta_ads/graph.py`
- Modify: `src/auth/meta_oauth.py` (`_fetch_all_adaccounts`)
- Test: `tests/unit/test_meta_graph_paginacao.py`

**Interfaces:**
- Consumes: nada.
- Produces: `PagedFetch(rows: list[dict], complete: bool)` e
  `async fetch_paginated(http: httpx.AsyncClient, url: str, *, access_token: str, params: dict[str, Any], max_pages: int = 50) -> PagedFetch`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_meta_graph_paginacao.py
"""O paginador e o unico lugar que sabe seguir paging.next — e o unico que
decide se a leitura ficou COMPLETA (F93)."""

import httpx
import pytest
import respx

from src.meta_ads.graph import fetch_paginated

URL = "https://graph.facebook.com/v22.0/x/edge"


@pytest.mark.asyncio
@respx.mock
async def test_segue_paging_next_e_marca_completo() -> None:
    respx.get(URL).mock(
        return_value=httpx.Response(
            200, json={"data": [{"id": "1"}], "paging": {"next": f"{URL}?after=abc"}}
        )
    )
    respx.get(f"{URL}?after=abc").mock(return_value=httpx.Response(200, json={"data": [{"id": "2"}]}))

    async with httpx.AsyncClient() as http:
        out = await fetch_paginated(http, URL, access_token="tok", params={"fields": "id"})

    assert [r["id"] for r in out.rows] == ["1", "2"]
    assert out.complete is True


@pytest.mark.asyncio
@respx.mock
async def test_pagina_que_falha_marca_incompleto_sem_perder_o_que_veio() -> None:
    respx.get(URL).mock(
        return_value=httpx.Response(
            200, json={"data": [{"id": "1"}], "paging": {"next": f"{URL}?after=abc"}}
        )
    )
    respx.get(f"{URL}?after=abc").mock(return_value=httpx.Response(500, json={"error": {}}))

    async with httpx.AsyncClient() as http:
        out = await fetch_paginated(http, URL, access_token="tok", params={"fields": "id"})

    assert [r["id"] for r in out.rows] == ["1"]
    assert out.complete is False


@pytest.mark.asyncio
@respx.mock
async def test_token_vai_no_header_nunca_na_query() -> None:
    """F82: token em query string vaza em log de proxy."""
    rota = respx.get(URL).mock(return_value=httpx.Response(200, json={"data": []}))

    async with httpx.AsyncClient() as http:
        await fetch_paginated(http, URL, access_token="segredo", params={"fields": "id"})

    pedido = rota.calls[0].request
    assert pedido.headers["Authorization"] == "Bearer segredo"
    assert "segredo" not in str(pedido.url)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_meta_graph_paginacao.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.meta_ads.graph'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/meta_ads/graph.py
"""Paginação da Graph API — o único lugar que sabe seguir `paging.next`.

Existe porque a lógica nasceu dentro de `src/auth/meta_oauth.py` e passou a ser
reusada por quem não tem nada a ver com OAuth (o resync). Duplicar paginação é
o tipo de cópia que apodrece: a correção entra numa das duas e a outra fica.
"""

from typing import Any, NamedTuple

import httpx
import structlog

log = structlog.get_logger(__name__)


class PagedFetch(NamedTuple):
    """`complete=False` significa leitura TRUNCADA — página falhou ou cap estourou.

    Quem faz detecção destrutiva PRECISA olhar esta flag (F93): sobre lista
    truncada, "ausente" significa "página que não veio", não churn.
    """

    rows: list[dict[str, Any]]
    complete: bool


async def fetch_paginated(
    http: httpx.AsyncClient,
    url: str,
    *,
    access_token: str,
    params: dict[str, Any],
    max_pages: int = 50,
) -> PagedFetch:
    rows: list[dict[str, Any]] = []
    # F82 — token no HEADER, nunca na query: quem lê a URL num log contorna tudo.
    headers = {"Authorization": f"Bearer {access_token}"}
    proxima: str | None = url
    primeira = True
    for _ in range(max_pages):
        resp = await http.get(proxima, params=params if primeira else None, headers=headers)
        primeira = False
        if resp.status_code != 200:
            log.warning(
                "meta_graph_page_failed",
                status=resp.status_code,
                body=resp.text[:200],
                fetched_so_far=len(rows),
            )
            return PagedFetch(rows, False)
        body = resp.json()
        rows.extend(body.get("data", []))
        proxima = (body.get("paging") or {}).get("next")
        if not proxima:
            return PagedFetch(rows, True)
    log.warning("meta_graph_page_cap", fetched=len(rows))
    return PagedFetch(rows, False)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_meta_graph_paginacao.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Fazer `_fetch_all_adaccounts` delegar**

Em `src/auth/meta_oauth.py`, substituir o corpo do laço por uma chamada ao helper, preservando o tipo de retorno `AdAccountsFetch` (há testes existentes que dependem dele):

```python
from src.meta_ads.graph import fetch_paginated

async def _fetch_all_adaccounts(http: httpx.AsyncClient, access_token: str) -> AdAccountsFetch:
    """GET /me/adaccounts seguindo paging.next até esgotar.

    A paginação em si vive em `src/meta_ads/graph.py` desde 2026-08-20 — este
    módulo é OAuth, e o resync (que não é OAuth) reusava o helper daqui.
    """
    out = await fetch_paginated(
        http,
        f"{META_GRAPH_BASE}/me/adaccounts",
        access_token=access_token,
        params={"fields": _ADACCOUNT_FIELDS, "limit": 200},
    )
    return AdAccountsFetch(accounts=out.rows, complete=out.complete)
```

- [ ] **Step 6: Rodar a suíte inteira do Meta pra provar que nada regrediu**

Run: `python -m pytest tests/unit -k "meta" -q`
Expected: PASS — em especial `test_job_partial_failure_audit.py`, que exercita o caminho de página que falha.

- [ ] **Step 7: Commit**

```bash
git add src/meta_ads/graph.py src/auth/meta_oauth.py tests/unit/test_meta_graph_paginacao.py
git commit -m "refactor(meta_ads): extrai paginacao da Graph pro proprio modulo"
```

---

## Task 2: fonte autoritativa da parceria

**Files:**
- Create: `src/meta_ads/partnership.py`
- Test: `tests/unit/test_meta_partnership_fetch.py`

**Interfaces:**
- Consumes: `fetch_paginated`, `PagedFetch` da Task 1.
- Produces: `PartnershipSnapshot(accounts: list[dict], complete: bool)`,
  `async fetch_partnership(http, *, access_token: str, business_id: str) -> PartnershipSnapshot`,
  `to_account_payload(rows: list[dict]) -> list[dict]` (mesma forma que `meta_ad_accounts.upsert_many` consome).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_meta_partnership_fetch.py
"""A lista autoritativa da parceria = client_ad_accounts UNIAO owned_ad_accounts.

Medido em 2026-08-20: 24 + 1 = 25, enquanto /me/adaccounts devolvia 23 — a edge
do BM enxerga conta que o system user ainda nao foi atribuido a ler.
"""

import httpx
import pytest
import respx

from src.meta_ads.partnership import fetch_partnership

BASE = "https://graph.facebook.com/v22.0/619664032237208"


@pytest.mark.asyncio
@respx.mock
async def test_une_as_duas_edges_e_normaliza() -> None:
    respx.get(f"{BASE}/client_ad_accounts").mock(
        return_value=httpx.Response(
            200,
            json={"data": [{"id": "act_1", "name": "Cliente", "account_status": 1,
                            "business": {"id": "bm_c", "name": "BM do cliente"}}]},
        )
    )
    respx.get(f"{BASE}/owned_ad_accounts").mock(
        return_value=httpx.Response(
            200, json={"data": [{"id": "act_2", "name": "Propria", "account_status": 1}]}
        )
    )

    async with httpx.AsyncClient() as http:
        snap = await fetch_partnership(http, access_token="tok", business_id="619664032237208")

    assert snap.complete is True
    por_id = {a["ad_account_id"]: a for a in snap.accounts}
    assert set(por_id) == {"act_1", "act_2"}
    assert por_id["act_1"]["business_id"] == "bm_c"
    assert por_id["act_1"]["account_name"] == "Cliente"
    # conta própria não tem `business` no payload da Graph
    assert por_id["act_2"]["business_id"] is None


@pytest.mark.asyncio
@respx.mock
async def test_uma_edge_incompleta_contamina_o_snapshot() -> None:
    """Meia leitura nao pode virar 'a parceria encolheu' — F93/F85."""
    respx.get(f"{BASE}/client_ad_accounts").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "act_1", "name": "C"}]})
    )
    respx.get(f"{BASE}/owned_ad_accounts").mock(return_value=httpx.Response(500, json={"error": {}}))

    async with httpx.AsyncClient() as http:
        snap = await fetch_partnership(http, access_token="tok", business_id="619664032237208")

    assert snap.complete is False
    assert len(snap.accounts) == 1  # o que veio não se perde


@pytest.mark.asyncio
@respx.mock
async def test_prefixo_act_normalizado() -> None:
    respx.get(f"{BASE}/client_ad_accounts").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "123", "name": "Sem prefixo"}]})
    )
    respx.get(f"{BASE}/owned_ad_accounts").mock(return_value=httpx.Response(200, json={"data": []}))

    async with httpx.AsyncClient() as http:
        snap = await fetch_partnership(http, access_token="tok", business_id="619664032237208")

    assert snap.accounts[0]["ad_account_id"] == "act_123"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_meta_partnership_fetch.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.meta_ads.partnership'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/meta_ads/partnership.py
"""Fonte autoritativa: quais contas a parceria do BM da V4 nos dá.

Substitui `/me/adaccounts` como definidor do inventário. A diferença medida em
2026-08-20: a edge do BM devolveu 25 contas e `/me/adaccounts` 23 — porque esta
última só enxerga conta a que o system user foi atribuído INDIVIDUALMENTE.
Confundir as duas é o que tornava "saiu da parceria" indistinguível de "ninguém
atribuiu o SU" (F128).
"""

from typing import Any, NamedTuple

import httpx

from src.meta_ads.client import META_GRAPH_API_VERSION
from src.meta_ads.graph import fetch_paginated

_GRAPH = f"https://graph.facebook.com/{META_GRAPH_API_VERSION}"
# currency e timezone_name são OBRIGATÓRIOS aqui: `upsert_many` escreve
# `currency = EXCLUDED.currency`, então pedir menos campos do que a tabela
# guarda APAGA os que faltarem nas 24 contas. Verificado por probe em
# 2026-08-20 — as duas edges devolvem os dois campos quando pedidos.
_FIELDS = "id,name,account_status,business,currency,timezone_name"
_EDGES = ("client_ad_accounts", "owned_ad_accounts")


class PartnershipSnapshot(NamedTuple):
    accounts: list[dict[str, Any]]
    complete: bool


def to_account_payload(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Graph → dicts que `meta_ad_accounts.upsert_many` consome."""
    payload: list[dict[str, Any]] = []
    for a in rows:
        ad_id = a.get("id", "")
        if not ad_id.startswith("act_"):
            ad_id = f"act_{ad_id}"
        business = a.get("business") or {}
        payload.append(
            {
                "ad_account_id": ad_id,
                "business_id": business.get("id"),
                "business_name": business.get("name"),
                "account_name": a.get("name", ad_id),
                "currency": a.get("currency"),
                "timezone_name": a.get("timezone_name"),
                "account_status": a.get("account_status"),
            }
        )
    return payload


async def fetch_partnership(
    http: httpx.AsyncClient, *, access_token: str, business_id: str
) -> PartnershipSnapshot:
    """União das duas edges. Uma edge truncada contamina o snapshot inteiro.

    Contaminar é deliberado: com metade da lista não dá pra dizer que uma conta
    saiu da parceria, e é essa afirmação que revoga acesso.
    """
    linhas: list[dict[str, Any]] = []
    completo = True
    for edge in _EDGES:
        out = await fetch_paginated(
            http,
            f"{_GRAPH}/{business_id}/{edge}",
            access_token=access_token,
            params={"fields": _FIELDS, "limit": 200},
        )
        linhas.extend(out.rows)
        completo = completo and out.complete
    return PartnershipSnapshot(to_account_payload(linhas), completo)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_meta_partnership_fetch.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/meta_ads/partnership.py tests/unit/test_meta_partnership_fetch.py
git commit -m "feat(meta_ads): le a lista autoritativa da parceria do BM"
```

---

## Task 3: o plano, como função pura

**Files:**
- Create: `src/meta_ads/reconcile.py`
- Test: `tests/unit/test_meta_reconcile_plan.py`

**Interfaces:**
- Consumes: nada (puro, sem I/O).
- Produces: `InventoryRow(ad_account_id: str, is_active: bool, missed_syncs: int)`,
  `Plan(to_add, to_bump, to_remove, to_reset, unreachable, blocked_reason)` — todas `list[str]` menos `blocked_reason: str | None` —,
  `build_plan(*, partnership_ids: set[str], reachable_ids: set[str], inventory: list[InventoryRow], complete: bool, threshold: int = 3, max_removal_ratio: float = 0.2, max_removal_abs: int = 5) -> Plan`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_meta_reconcile_plan.py
"""O plano e onde mora a decisao de revogar acesso — entao ele e PURO.

Sem I/O, sem banco, sem rede: da pra cobrir por tabela de casos, e um erro aqui
nao precisa de container pra aparecer.
"""

import pytest

from src.meta_ads.reconcile import InventoryRow, build_plan


def inv(id_: str, ativo: bool = True, faltas: int = 0) -> InventoryRow:
    return InventoryRow(ad_account_id=id_, is_active=ativo, missed_syncs=faltas)


def test_conta_nova_da_parceria_entra() -> None:
    plano = build_plan(
        partnership_ids={"act_1", "act_2"},
        reachable_ids={"act_1", "act_2"},
        inventory=[inv("act_1")],
        complete=True,
    )
    assert plano.to_add == ["act_2"]
    assert plano.to_remove == []


def test_ausencia_na_parceria_conta_carencia_antes_de_remover() -> None:
    """Primeira e segunda ausencia so marcam; a terceira remove."""
    for faltas, espera_remocao in ((0, False), (1, False), (2, True)):
        plano = build_plan(
            partnership_ids={"act_1"},
            reachable_ids={"act_1"},
            inventory=[inv("act_1"), inv("act_2", faltas=faltas)],
            complete=True,
            threshold=3,
        )
        assert (plano.to_remove == ["act_2"]) is espera_remocao, f"faltas={faltas}"
        assert (plano.to_bump == ["act_2"]) is not espera_remocao


def test_leitura_incompleta_bloqueia_o_lado_destrutivo_mas_nao_o_aditivo() -> None:
    """F93: pagina que falhou nao e churn. Adicionar segue seguro."""
    plano = build_plan(
        partnership_ids={"act_1", "act_novo"},
        reachable_ids={"act_1"},
        inventory=[inv("act_1"), inv("act_sumiu", faltas=9)],
        complete=False,
    )
    assert plano.to_add == ["act_novo"]
    assert plano.to_remove == []
    assert plano.to_bump == []
    assert plano.blocked_reason == "leitura incompleta"


def test_guard_percentual_barra_remocao_em_massa() -> None:
    """F85: uma resposta estranha nao pode revogar a conta inteira."""
    inventario = [inv(f"act_{i}", faltas=9) for i in range(10)]
    plano = build_plan(
        partnership_ids=set(),
        reachable_ids=set(),
        inventory=inventario,
        complete=True,
        max_removal_ratio=0.2,
        max_removal_abs=5,
    )
    assert plano.to_remove == []
    assert plano.blocked_reason is not None
    assert "10" in plano.blocked_reason  # diz quantas seriam


def test_conta_na_parceria_sem_su_e_sinalizada_nunca_removida() -> None:
    """A distincao que o F128 nao tinha: 'nao alcanco' != 'nao e mais nossa'."""
    plano = build_plan(
        partnership_ids={"act_1"},
        reachable_ids=set(),
        inventory=[inv("act_1")],
        complete=True,
    )
    assert plano.unreachable == ["act_1"]
    assert plano.to_remove == []
    assert plano.to_bump == []


def test_conta_que_reaparece_zera_a_carencia() -> None:
    plano = build_plan(
        partnership_ids={"act_1"},
        reachable_ids={"act_1"},
        inventory=[inv("act_1", faltas=2)],
        complete=True,
    )
    assert plano.to_reset == ["act_1"]
    assert plano.to_remove == []


def test_conta_ja_desativada_nao_reaparece_no_plano_destrutivo() -> None:
    plano = build_plan(
        partnership_ids=set(),
        reachable_ids=set(),
        inventory=[inv("act_velha", ativo=False, faltas=9)],
        complete=True,
    )
    assert plano.to_remove == []
    assert plano.to_bump == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_meta_reconcile_plan.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.meta_ads.reconcile'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/meta_ads/reconcile.py
"""Decide o que reconciliar. Puro de propósito: nenhuma I/O entra aqui.

Separar decisão de efeito é o que torna testável a única parte que pode revogar
acesso indevidamente. O repositório aplica; este módulo escolhe.
"""

import math
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class InventoryRow:
    ad_account_id: str
    is_active: bool
    missed_syncs: int


@dataclass(frozen=True, slots=True)
class Plan:
    to_add: list[str] = field(default_factory=list)
    to_bump: list[str] = field(default_factory=list)
    to_remove: list[str] = field(default_factory=list)
    to_reset: list[str] = field(default_factory=list)
    unreachable: list[str] = field(default_factory=list)
    blocked_reason: str | None = None


def build_plan(
    *,
    partnership_ids: set[str],
    reachable_ids: set[str],
    inventory: list[InventoryRow],
    complete: bool,
    threshold: int = 3,
    max_removal_ratio: float = 0.2,
    max_removal_abs: int = 5,
) -> Plan:
    """(parceria, alcance, inventário) → plano.

    Aditivo sempre; destrutivo só com leitura completa e dentro do teto.
    """
    ativos = [r for r in inventory if r.is_active]
    ids_ativos = {r.ad_account_id for r in ativos}

    to_add = sorted(partnership_ids - ids_ativos)
    unreachable = sorted((partnership_ids & ids_ativos) - reachable_ids)
    to_reset = sorted(r.ad_account_id for r in ativos if r.missed_syncs and r.ad_account_id in partnership_ids)

    if not complete:
        # Metade da lista não sustenta a afirmação "esta conta saiu da parceria".
        return Plan(to_add=to_add, to_reset=to_reset, unreachable=unreachable,
                    blocked_reason="leitura incompleta")

    ausentes = [r for r in ativos if r.ad_account_id not in partnership_ids]
    # missed_syncs conta as ausências ANTERIORES; esta execução é a próxima.
    remover = sorted(r.ad_account_id for r in ausentes if r.missed_syncs + 1 >= threshold)
    marcar = sorted(r.ad_account_id for r in ausentes if r.missed_syncs + 1 < threshold)

    # `max(1, ...)`: sem o piso, inventário pequeno zera o teto (2 ativas → 20% →
    # floor 0) e o guard barraria ATÉ a saída de uma conta só — o recurso nunca
    # dispararia. O guard existe contra remoção em massa, não contra o caso normal.
    teto = max(1, min(max_removal_abs, math.floor(len(ativos) * max_removal_ratio)))
    if remover and len(remover) > teto:
        return Plan(
            to_add=to_add,
            to_reset=to_reset,
            unreachable=unreachable,
            blocked_reason=(
                f"remocao em massa barrada: {len(remover)} contas de {len(ativos)} ativas "
                f"(teto {teto})"
            ),
        )

    return Plan(to_add=to_add, to_bump=marcar, to_remove=remover,
                to_reset=to_reset, unreachable=unreachable)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_meta_reconcile_plan.py -q`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add src/meta_ads/reconcile.py tests/unit/test_meta_reconcile_plan.py
git commit -m "feat(meta_ads): plano de reconciliacao como funcao pura"
```

---

## Task 4: migration e aplicação no inventário

**Files:**
- Create: `src/db/migrations/006_meta_partnership_reconciliation.sql`
- Modify: `src/db/repositories/meta_ad_accounts.py`
- Modify: `tests/integration/test_migrations.py` (lista de migrations)
- **NÃO remover `bump_missing` nesta task.** `src/jobs/meta_resync.py:104` ainda a chama, e quem reescreve o job é a Task 7 — apagar aqui deixaria a árvore vermelha entre as duas tasks, e cada task tem de terminar verde. Marque-a como obsoleta com um comentário apontando para `build_plan()`; a Task 7 remove a função e os dois arquivos de teste (`tests/unit/test_meta_churn_por_ausencia.py`, `tests/integration/test_meta_churn_por_ausencia.py`) junto com o call-site.
- Test: `tests/integration/test_meta_reconcile_repo.py`

**Interfaces:**
- Consumes: `Plan` da Task 3 (só as listas de ids).
- Produces: `async apply_absences(conn, *, bump: list[str], reset: list[str]) -> None`,
  `async deactivate(conn, *, ad_account_ids: list[str]) -> int`,
  `async set_reachable(conn, *, reachable_ids: list[str]) -> None`,
  `async list_inventory_rows(conn) -> list[InventoryRow]`.

- [ ] **Step 1: Escrever a migration**

```sql
-- 006_meta_partnership_reconciliation.sql
-- Reconciliação contra a lista autoritativa da parceria (spec 2026-08-20).
--
-- su_reachable separa duas condições que hoje colapsam em "sumiu": conta que
-- saiu da parceria (deve sair do MCP) e conta que está na parceria mas cujo
-- system user não foi atribuído (ação humana no Business Manager, NUNCA
-- desativar). Medido em 2026-08-20: 25 na parceria, 23 alcançáveis.
--
-- revoked_at/revoked_reason tornam a revogação SOFT: a linha do grant fica, o
-- gate nega, e a parceria que volta restaura com um clique. Antes era DELETE.

ALTER TABLE meta_ad_accounts
    ADD COLUMN IF NOT EXISTS su_reachable BOOLEAN NOT NULL DEFAULT true;

ALTER TABLE manager_meta_account_access
    ADD COLUMN IF NOT EXISTS revoked_at     TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS revoked_reason TEXT;
```

- [ ] **Step 2: Acrescentar à lista do guard de migrations**

Em `tests/integration/test_migrations.py`, dentro do `assert [r["name"] for r in applied] == [...]`, adicionar `"006_meta_partnership_reconciliation.sql",` ao final da lista.

- [ ] **Step 3: Write the failing test**

```python
# tests/integration/test_meta_reconcile_repo.py
"""O repositorio APLICA o plano; nao decide nada. Contra banco real porque o
que importa aqui e o efeito do SQL, nao a chamada (licao do F85)."""

import pytest

from src.db.repositories import meta_ad_accounts

CONTA = {
    "ad_account_id": "act_1",
    "business_id": "bm",
    "business_name": "BM",
    "account_name": "Conta 1",
    "currency": "BRL",
    "timezone_name": "America/Sao_Paulo",
    "account_status": 1,
}
OUTRA = {**CONTA, "ad_account_id": "act_2", "account_name": "Conta 2"}


@pytest.mark.integration
async def test_apply_absences_incrementa_e_zera(db) -> None:
    async with db.acquire() as conn:
        await meta_ad_accounts.upsert_many(conn, [CONTA, OUTRA])

        await meta_ad_accounts.apply_absences(conn, bump=["act_2"], reset=[])
        await meta_ad_accounts.apply_absences(conn, bump=["act_2"], reset=[])
        assert (await meta_ad_accounts.get_by_id(conn, "act_2")).missed_syncs == 2

        await meta_ad_accounts.apply_absences(conn, bump=[], reset=["act_2"])
        assert (await meta_ad_accounts.get_by_id(conn, "act_2")).missed_syncs == 0


@pytest.mark.integration
async def test_deactivate_so_mexe_no_que_foi_pedido(db) -> None:
    async with db.acquire() as conn:
        await meta_ad_accounts.upsert_many(conn, [CONTA, OUTRA])

        n = await meta_ad_accounts.deactivate(conn, ad_account_ids=["act_2"])

        assert n == 1
        assert (await meta_ad_accounts.get_by_id(conn, "act_1")).is_active is True
        assert (await meta_ad_accounts.get_by_id(conn, "act_2")).is_active is False


@pytest.mark.integration
async def test_lista_vazia_e_noop_em_todas_as_operacoes(db) -> None:
    """F85: lista vazia quase sempre e falha de leitura, nao 'todas sumiram'."""
    async with db.acquire() as conn:
        await meta_ad_accounts.upsert_many(conn, [CONTA, OUTRA])

        assert await meta_ad_accounts.deactivate(conn, ad_account_ids=[]) == 0
        await meta_ad_accounts.apply_absences(conn, bump=[], reset=[])
        await meta_ad_accounts.set_reachable(conn, reachable_ids=[])

        assert len(await meta_ad_accounts.list_all(conn)) == 2
        assert (await meta_ad_accounts.get_by_id(conn, "act_1")).su_reachable is True


@pytest.mark.integration
async def test_set_reachable_marca_quem_esta_fora_do_alcance(db) -> None:
    async with db.acquire() as conn:
        await meta_ad_accounts.upsert_many(conn, [CONTA, OUTRA])

        await meta_ad_accounts.set_reachable(conn, reachable_ids=["act_1"])

        assert (await meta_ad_accounts.get_by_id(conn, "act_1")).su_reachable is True
        assert (await meta_ad_accounts.get_by_id(conn, "act_2")).su_reachable is False


@pytest.mark.integration
async def test_list_inventory_rows_devolve_o_que_o_plano_consome(db) -> None:
    async with db.acquire() as conn:
        await meta_ad_accounts.upsert_many(conn, [CONTA, OUTRA])
        await meta_ad_accounts.deactivate(conn, ad_account_ids=["act_2"])

        linhas = {r.ad_account_id: r for r in await meta_ad_accounts.list_inventory_rows(conn)}

        assert linhas["act_1"].is_active is True
        assert linhas["act_2"].is_active is False
        assert linhas["act_1"].missed_syncs == 0
```

- [ ] **Step 4: Run test to verify it fails**

Run: `python -m pytest tests/integration/test_meta_reconcile_repo.py -q`
Expected: FAIL — `AttributeError: module ... has no attribute 'apply_absences'`. (Sem Docker, falha no fixture; nesse caso rode no CI e siga para o Step 5 com base no erro de atributo.)

- [ ] **Step 5: Write minimal implementation**

Em `src/db/repositories/meta_ad_accounts.py`: acrescentar `su_reachable: bool = True` ao dataclass e ao `_row_to_account`, **remover** `bump_missing` e `MISSED_SYNCS_THRESHOLD` (a decisão virou `build_plan`), e acrescentar:

```python
from src.meta_ads.reconcile import InventoryRow


async def apply_absences(conn: asyncpg.Connection, *, bump: list[str], reset: list[str]) -> None:
    """Aplica a carência decidida pelo plano. Não decide nada."""
    if bump:
        await conn.execute(
            "UPDATE meta_ad_accounts SET missed_syncs = missed_syncs + 1 "
            "WHERE ad_account_id = ANY($1::text[])",
            bump,
        )
    if reset:
        await conn.execute(
            "UPDATE meta_ad_accounts SET missed_syncs = 0 "
            "WHERE ad_account_id = ANY($1::text[]) AND missed_syncs <> 0",
            reset,
        )


async def deactivate(conn: asyncpg.Connection, *, ad_account_ids: list[str]) -> int:
    """Desativa exatamente a lista dada — nunca 'tudo que não está em X'.

    A forma antiga (`mark_inactive_except`) tinha o modo de falha do F85 embutido:
    lista vazia significava 'desative o resto'. Aqui, lista vazia é no-op.
    """
    if not ad_account_ids:
        return 0
    return _rows_affected(
        await conn.execute(
            "UPDATE meta_ad_accounts SET is_active = false "
            "WHERE ad_account_id = ANY($1::text[]) AND is_active = true",
            ad_account_ids,
        )
    )


async def set_reachable(conn: asyncpg.Connection, *, reachable_ids: list[str]) -> None:
    """Marca alcance do system user. NÃO desativa: alcance ≠ pertencer à parceria."""
    if not reachable_ids:
        return
    await conn.execute(
        "UPDATE meta_ad_accounts SET su_reachable = (ad_account_id = ANY($1::text[]))",
        reachable_ids,
    )


async def list_inventory_rows(conn: asyncpg.Connection) -> list[InventoryRow]:
    rows = await conn.fetch("SELECT ad_account_id, is_active, missed_syncs FROM meta_ad_accounts")
    return [
        InventoryRow(
            ad_account_id=r["ad_account_id"],
            is_active=r["is_active"],
            missed_syncs=r["missed_syncs"],
        )
        for r in rows
    ]
```

- [ ] **Step 6: Marcar `bump_missing` como obsoleta, sem remover**

Acrescentar à docstring dela: `OBSOLETA (2026-08-20): a decisão migrou para build_plan(); removida junto com o call-site na Task 7.` O call-site em `src/jobs/meta_resync.py` continua funcionando até lá — remover agora deixaria a árvore vermelha no meio do plano.

- [ ] **Step 7: Rodar o gate e o CI**

Run: `python scripts/check_pre_push.py`
Expected: OK nos 6 passos. Os testes de integração rodam no CI — confirme depois do push com `gh run view <id> --json conclusion`.

- [ ] **Step 8: Commit**

```bash
git add -A src/db tests/integration/test_migrations.py tests/integration/test_meta_reconcile_repo.py
git commit -m "feat(db): inventario Meta aplica plano de reconciliacao"
```

---

## Task 5: revogação soft e o gate

**Files:**
- Modify: `src/db/repositories/manager_meta_account_access.py`
- Test: `tests/integration/test_meta_grants_soft_revoke.py`
- Test: `tests/unit/test_gate_meta_exige_conta_ativa.py`

**Interfaces:**
- Consumes: nada das tasks anteriores.
- Produces: `async revoke_for_account(conn, *, ad_account_id: str, reason: str) -> list[UUID]`,
  `async restore_for_account(conn, *, ad_account_id: str) -> int`,
  `revoke(conn, *, manager_id, ad_account_id, reason: str = "manual") -> None` (agora soft).

- [ ] **Step 1: Write the failing tests**

```python
# tests/integration/test_meta_grants_soft_revoke.py
"""Revogar precisa ser reversivel e auditavel — o grant e curadoria humana.

E o gate precisa negar SEM depender do reconciliador ter rodado: sob token de
system user, ele e a unica fronteira que sobra (confused deputy).
"""

from uuid import uuid4

import pytest

from src.db.repositories import manager_meta_account_access, managers, meta_ad_accounts

CONTA = {
    "ad_account_id": "act_1",
    "business_id": "bm",
    "business_name": "BM",
    "account_name": "Conta 1",
    "currency": "BRL",
    "timezone_name": "America/Sao_Paulo",
    "account_status": 1,
}


async def _cenario(conn):
    mid = uuid4()
    await managers.create(conn, manager_id=mid, email="g@v4company.com", full_name=None)
    await meta_ad_accounts.upsert_many(conn, [CONTA])
    await manager_meta_account_access.bulk_grant(
        conn, manager_id=mid, ad_account_ids=["act_1"], granted_by=mid
    )
    return mid


@pytest.mark.integration
async def test_revogacao_preserva_a_linha_e_o_motivo(db) -> None:
    async with db.acquire() as conn:
        mid = await _cenario(conn)

        atingidos = await manager_meta_account_access.revoke_for_account(
            conn, ad_account_id="act_1", reason="partnership_ended"
        )

        assert atingidos == [mid]
        linha = await conn.fetchrow(
            "SELECT revoked_at, revoked_reason FROM manager_meta_account_access "
            "WHERE manager_id = $1 AND ad_account_id = 'act_1'",
            mid,
        )
        assert linha["revoked_at"] is not None
        assert linha["revoked_reason"] == "partnership_ended"


@pytest.mark.integration
async def test_grant_revogado_nao_da_acesso_nem_aparece_na_lista(db) -> None:
    async with db.acquire() as conn:
        mid = await _cenario(conn)
        await manager_meta_account_access.revoke_for_account(
            conn, ad_account_id="act_1", reason="partnership_ended"
        )

        assert await manager_meta_account_access.can_manager_access(conn, mid, "act_1") is False
        assert await manager_meta_account_access.list_accounts_for_manager(conn, mid) == []


@pytest.mark.integration
async def test_restaurar_devolve_exatamente_quem_tinha(db) -> None:
    async with db.acquire() as conn:
        mid = await _cenario(conn)
        await manager_meta_account_access.revoke_for_account(
            conn, ad_account_id="act_1", reason="partnership_ended"
        )

        n = await manager_meta_account_access.restore_for_account(conn, ad_account_id="act_1")

        assert n == 1
        assert await manager_meta_account_access.can_manager_access(conn, mid, "act_1") is True


@pytest.mark.integration
async def test_gate_nega_conta_desativada_mesmo_com_grant_vivo(db) -> None:
    """Defesa em profundidade: se o reconciliador atrasar, o gate ja nega."""
    async with db.acquire() as conn:
        mid = await _cenario(conn)
        await meta_ad_accounts.deactivate(conn, ad_account_ids=["act_1"])

        assert await manager_meta_account_access.can_manager_access(conn, mid, "act_1") is False
```

```python
# tests/unit/test_gate_meta_exige_conta_ativa.py
"""Guard DERIVADO: o gate nao pode voltar a ler so a tabela de grants.

Sem isto alguem 'simplifica' o JOIN e o gate volta a liberar ex-cliente sem
nenhum teste vermelho — foi assim que o F86 renasceu como F109.
"""

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2] / "src" / "db" / "repositories"


def test_can_manager_access_meta_consulta_estado_da_conta() -> None:
    fonte = (_REPO / "manager_meta_account_access.py").read_text(encoding="utf-8")
    corpo = re.search(r"async def can_manager_access\(.*?\n(?=async def |\Z)", fonte, re.S)
    assert corpo, "can_manager_access sumiu ou mudou de nome"
    sql = corpo.group(0)
    assert "meta_ad_accounts" in sql, "o gate precisa cruzar com o inventario"
    assert "is_active" in sql, "conta fora da parceria tem que ser negada aqui tambem"
    assert "revoked_at IS NULL" in sql, "grant revogado nao pode dar acesso"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/test_gate_meta_exige_conta_ativa.py -q`
Expected: FAIL — `AssertionError: o gate precisa cruzar com o inventario`

- [ ] **Step 3: Write minimal implementation**

Em `src/db/repositories/manager_meta_account_access.py`:

```python
async def can_manager_access(
    conn: asyncpg.Connection,
    manager_id: UUID,
    ad_account_id: str,
    *,
    level: str = "read",
) -> bool:
    """Gate do Modelo B — e a ÚNICA fronteira que sobra.

    O token de system user entrega tudo que o BM alcança, então a Meta não nega
    nada por nós (confused deputy). Por isso o gate cruza com o inventário: conta
    fora da parceria é negada aqui mesmo que o reconciliador ainda não tenha
    rodado, e grant revogado não vale.
    """
    row = await conn.fetchrow(
        """
        SELECT m.access_level
          FROM manager_meta_account_access m
          JOIN meta_ad_accounts a ON a.ad_account_id = m.ad_account_id
         WHERE m.manager_id = $1
           AND m.ad_account_id = $2
           AND m.revoked_at IS NULL
           AND a.is_active = true
        """,
        manager_id,
        ad_account_id,
    )
    if row is None:
        return False
    if level == "read":
        return True
    return bool(row["access_level"] == "write")


async def revoke_for_account(
    conn: asyncpg.Connection, *, ad_account_id: str, reason: str
) -> list[UUID]:
    """Revogação SOFT de todos os grants vivos da conta; devolve os atingidos.

    A linha fica: sem ela não há o que restaurar quando a parceria volta, só
    refazer à mão — e a curadoria de quem tinha acesso é trabalho humano.
    """
    rows = await conn.fetch(
        """
        UPDATE manager_meta_account_access
           SET revoked_at = now(), revoked_reason = $2
         WHERE ad_account_id = $1 AND revoked_at IS NULL
        RETURNING manager_id
        """,
        ad_account_id,
        reason,
    )
    return [r["manager_id"] for r in rows]


async def restore_for_account(conn: asyncpg.Connection, *, ad_account_id: str) -> int:
    rows = await conn.fetch(
        """
        UPDATE manager_meta_account_access
           SET revoked_at = NULL, revoked_reason = NULL
         WHERE ad_account_id = $1 AND revoked_at IS NOT NULL
        RETURNING manager_id
        """,
        ad_account_id,
    )
    return len(rows)
```

Ainda no mesmo arquivo: `revoke` deixa de ser `DELETE` e passa a marcar `revoked_at = now(), revoked_reason = 'manual'`; `list_accounts_for_manager` ganha `AND m.revoked_at IS NULL`; e a query que monta o `access_set` da matriz (usada por `routes.py`) idem. `bulk_grant` limpa `revoked_at`/`revoked_reason` no `ON CONFLICT`, porque reconceder é a forma de restaurar.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/test_gate_meta_exige_conta_ativa.py -q`
Expected: PASS

- [ ] **Step 5: Provar o guard contra o código PRÉ-fix**

```bash
cp src/db/repositories/manager_meta_account_access.py "$TMPDIR/gate.bak"
python - <<'PY'
import pathlib
p = pathlib.Path("src/db/repositories/manager_meta_account_access.py")
t = p.read_text(encoding="utf-8")
p.write_text(t.replace("JOIN meta_ad_accounts a ON a.ad_account_id = m.ad_account_id", ""), encoding="utf-8")
PY
python -m pytest tests/unit/test_gate_meta_exige_conta_ativa.py -q  # DEVE falhar
cp "$TMPDIR/gate.bak" src/db/repositories/manager_meta_account_access.py
python -m pytest tests/unit/test_gate_meta_exige_conta_ativa.py -q  # DEVE passar
```

Guard que nunca foi visto vermelho não é guard. Restaure da cópia, **nunca** com `git checkout` — ele levaria junto trabalho não commitado.

- [ ] **Step 6: Commit**

```bash
git add -A src/db tests
git commit -m "feat(auth): revogacao soft e gate Meta exigindo conta ativa"
```

---

## Task 6: configuração e declaração no deploy

**Files:**
- Modify: `src/config.py`
- Modify: `.github/workflows/deploy.yml`
- Test: `tests/unit/test_deploy_env_matches_settings.py` (existente, roda como guard)

**Interfaces:**
- Consumes: nada.
- Produces: `Settings.meta_business_id: str = ""`, `Settings.meta_reconcile_apply: bool = False`.

- [ ] **Step 1: Acrescentar os campos**

Em `src/config.py`, junto dos demais campos Meta:

```python
    # ID do BM da V4 Lima Soares. Não é segredo (é identificador), então env var
    # comum. Default vazio porque `/me/businesses` devolve 0 pro system user: sem
    # este valor não há como descobrir o BM, e o reconciliador vira no-op em vez
    # de derrubar o job (mesma escolha de meta_system_user_token).
    meta_business_id: str = ""
    # Trava do rollout: o job calcula e audita o plano, mas só executa o lado
    # destrutivo com isto ligado. Virar sem deploy de código.
    meta_reconcile_apply: bool = False
```

- [ ] **Step 2: Declarar nos 3 Cloud Run Jobs**

Em `.github/workflows/deploy.yml`, nos três `gcloud run jobs update`, acrescentar ao `--update-env-vars` (merge, nunca `--set-env-vars`, que é replace):

```
META_BUSINESS_ID=619664032237208,META_RECONCILE_APPLY=false
```

E no `gcloud run services update` do serviço, o mesmo par — o painel lê `meta_business_id` para a mensagem de "SU não atribuído".

- [ ] **Step 3: Rodar o guard de paridade**

Run: `python -m pytest tests/unit/test_deploy_env_matches_settings.py -q`
Expected: PASS — ele cruza as duas direções (env montado sem campo, campo obrigatório sem montagem). Como os campos têm default, a falta de declaração não derruba o job (F114), mas a declaração é o que liga a feature em produção.

- [ ] **Step 4: Commit**

```bash
git add src/config.py .github/workflows/deploy.yml
git commit -m "chore(config): meta_business_id e trava de rollout do reconciliador"
```

---

## Task 7: o job aplica o plano

**Files:**
- Modify: `src/jobs/meta_resync.py`
- Test: `tests/unit/test_meta_reconcile_job.py`

**Interfaces:**
- Consumes: `fetch_partnership`, `build_plan`, os repositórios das Tasks 4 e 5, `Settings` da Task 6.
- Produces: `async reconcile_meta() -> Plan` (substitui o miolo de `resync_meta`).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_meta_reconcile_job.py
"""O job orquestra: le, planeja, aplica, audita. As decisoes ja foram testadas
puras — aqui prova-se a FIACAO, incluindo o dry-run e a auditoria."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.meta_ads.partnership import PartnershipSnapshot
from src.meta_ads.reconcile import InventoryRow


def _pool(conn):
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=ctx)
    return pool


def _patches(job, *, apply: bool, parceria: list[str], inventario: list[InventoryRow]):
    from src.auth.meta_oauth import AdAccountsFetch

    conn = MagicMock()
    conn.execute = AsyncMock(return_value="UPDATE 0")
    return conn, [
        patch.object(job, "get_settings", MagicMock(return_value=MagicMock(
            meta_system_user_token="tok", meta_business_id="bm", meta_reconcile_apply=apply
        ))),
        patch.object(job, "fetch_partnership", AsyncMock(return_value=PartnershipSnapshot(
            [{"ad_account_id": i, "account_name": i} for i in parceria], True
        ))),
        patch.object(job, "_fetch_all_adaccounts", AsyncMock(
            return_value=AdAccountsFetch(accounts=[{"id": i} for i in parceria], complete=True)
        )),
        patch.object(job.connection, "get_pool", MagicMock(return_value=_pool(conn))),
        patch.object(job, "record_job_run", AsyncMock()),
    ]


@pytest.mark.asyncio
async def test_dry_run_calcula_e_audita_sem_aplicar() -> None:
    from src.jobs import meta_resync as job

    conn, ps = _patches(job, apply=False, parceria=["act_1"],
                        inventario=[InventoryRow("act_2", True, 9)])
    with (
        *ps,
        patch.object(job.meta_ad_accounts, "list_inventory_rows",
                     AsyncMock(return_value=[InventoryRow("act_2", True, 9)])),
        patch.object(job.meta_ad_accounts, "upsert_many", AsyncMock(return_value=1)),
        patch.object(job.meta_ad_accounts, "deactivate", AsyncMock(return_value=0)) as desativa,
        patch.object(job.manager_meta_account_access, "revoke_for_account",
                     AsyncMock(return_value=[])) as revoga,
    ):
        plano = await job.reconcile_meta()

    assert plano.to_remove == ["act_2"]
    desativa.assert_not_awaited()
    revoga.assert_not_awaited()


@pytest.mark.asyncio
async def test_com_apply_ligado_desativa_e_revoga_e_audita_a_conta() -> None:
    from src.jobs import meta_resync as job

    conn, ps = _patches(job, apply=True, parceria=["act_1"],
                        inventario=[InventoryRow("act_2", True, 9)])
    with (
        *ps,
        patch.object(job.meta_ad_accounts, "list_inventory_rows",
                     AsyncMock(return_value=[InventoryRow("act_2", True, 9)])),
        patch.object(job.meta_ad_accounts, "upsert_many", AsyncMock(return_value=1)),
        patch.object(job.meta_ad_accounts, "apply_absences", AsyncMock()),
        patch.object(job.meta_ad_accounts, "set_reachable", AsyncMock()),
        patch.object(job.meta_ad_accounts, "deactivate", AsyncMock(return_value=1)) as desativa,
        patch.object(job.manager_meta_account_access, "revoke_for_account",
                     AsyncMock(return_value=["mgr-1"])) as revoga,
        patch.object(job, "record_audit_event", AsyncMock()) as audita,
    ):
        await job.reconcile_meta()

    desativa.assert_awaited_once()
    assert desativa.await_args.kwargs["ad_account_ids"] == ["act_2"]
    assert revoga.await_args.kwargs["reason"] == "partnership_ended"
    assert audita.await_args.kwargs["operation"] == "meta_access_cleanup"


@pytest.mark.asyncio
async def test_sem_business_id_o_job_nao_reconcilia() -> None:
    """Config faltando vira no-op explicito, nao excecao no meio da noite."""
    from src.jobs import meta_resync as job

    with patch.object(job, "get_settings", MagicMock(return_value=MagicMock(
        meta_system_user_token="tok", meta_business_id="", meta_reconcile_apply=True
    ))):
        plano = await job.reconcile_meta()

    assert plano.blocked_reason == "meta_business_id nao configurado"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_meta_reconcile_job.py -q`
Expected: FAIL — `AttributeError: module 'src.jobs.meta_resync' has no attribute 'reconcile_meta'`

- [ ] **Step 3: Write minimal implementation**

Substituir o miolo de `src/jobs/meta_resync.py` (remover `_deactivate_churned` e a chamada a `bump_missing`) por:

```python
async def reconcile_meta() -> Plan:
    """Lê a parceria, planeja e aplica. Assume `connection.init_pool()` feito."""
    settings = get_settings()
    if not settings.meta_system_user_token:
        log.warning("meta_reconcile_no_token")
        return Plan(blocked_reason="token do system user nao configurado")
    if not settings.meta_business_id:
        log.warning("meta_reconcile_no_business_id")
        return Plan(blocked_reason="meta_business_id nao configurado")

    async with httpx.AsyncClient(timeout=60.0) as http:
        parceria = await fetch_partnership(
            http,
            access_token=settings.meta_system_user_token,
            business_id=settings.meta_business_id,
        )
        alcance = await _fetch_all_adaccounts(http, settings.meta_system_user_token)

    ids_parceria = {a["ad_account_id"] for a in parceria.accounts}
    ids_alcance = {
        i if i.startswith("act_") else f"act_{i}"
        for i in (a.get("id", "") for a in alcance.accounts)
    }

    pool = connection.get_pool()
    async with pool.acquire() as conn:
        # Aditivo primeiro e sempre: entrar no catálogo é seguro mesmo com
        # leitura parcial, e é o que faz a conta nova aparecer pro admin delegar.
        upserted = await meta_ad_accounts.upsert_many(conn, parceria.accounts)
        inventario = await meta_ad_accounts.list_inventory_rows(conn)
        plano = build_plan(
            partnership_ids=ids_parceria,
            reachable_ids=ids_alcance,
            inventory=inventario,
            complete=parceria.complete and alcance.complete,
        )

        aplicado = settings.meta_reconcile_apply and plano.blocked_reason is None
        revogados = 0
        if aplicado:
            await meta_ad_accounts.apply_absences(conn, bump=plano.to_bump, reset=plano.to_reset)
            await meta_ad_accounts.set_reachable(conn, reachable_ids=sorted(ids_alcance))
            await meta_ad_accounts.deactivate(conn, ad_account_ids=plano.to_remove)
            for ad_account_id in plano.to_remove:
                atingidos = await manager_meta_account_access.revoke_for_account(
                    conn, ad_account_id=ad_account_id, reason="partnership_ended"
                )
                revogados += len(atingidos)
                # Por conta, não por grant: forense suficiente, sem inundar a trilha.
                await record_audit_event(
                    conn,
                    operation="meta_access_cleanup",
                    platform="meta",
                    params_summary={
                        "ad_account_id": ad_account_id,
                        "reason": "partnership_ended",
                        "managers": [str(m) for m in atingidos],
                    },
                )

        await record_job_run(
            conn,
            operation="meta_reconcile",
            platform="meta",
            target_count=upserted,
            status="success" if plano.blocked_reason is None else "error",
            error_message=plano.blocked_reason,
            params_summary={
                "added": len(plano.to_add),
                "removed": len(plano.to_remove),
                "bumped": len(plano.to_bump),
                "unreachable": len(plano.unreachable),
                "revoked_grants": revogados,
                "applied": aplicado,
            },
        )
    log.info("meta_reconcile_complete", applied=aplicado, plan=plano)
    return plano
```

`run()` passa a chamar `reconcile_meta()`, e `meta_resync.py` passa a importar `manager_meta_account_access` e `record_access_revocation`.

**`record_access_revocation` não existe — criar** em `src/jobs/_audit.py`, ao lado de `record_job_run`. Reusar `record_job_run` seria mentira semântica: ele grava `action_type="system"` e documenta "marca um run de job"; revogar acesso é `mutate`, e é isso que a trilha precisa dizer.

```python
async def record_access_revocation(
    conn: asyncpg.Connection,
    *,
    ad_account_id: str,
    reason: str,
    manager_ids: list[str],
) -> int:
    """Grava a revogação automática de acesso de UMA conta.

    Por conta e não por grant: a lista de gestores cabe no `params_summary` e
    uma linha por grant inundaria a trilha sem acrescentar forense.

    `action_type="mutate"` porque é o que é. Sob token de system user a Meta
    registra tudo como `v4-ads-mcp-integracao`, então esta linha é o único lugar
    onde fica registrado que um acesso humano foi retirado, e por quê.
    """
    return await audit_log.record(
        conn,
        manager_id=None,
        session_id=None,
        customer_id=ad_account_id,
        action_type="mutate",
        operation="meta_access_cleanup",
        target_count=len(manager_ids),
        params_summary={"reason": reason, "managers": manager_ids},
        status="success",
        error_message=None,
        platform="meta",
    )
```

No job, a chamada correspondente troca `record_audit_event(...)` por:

```python
                await record_access_revocation(
                    conn,
                    ad_account_id=ad_account_id,
                    reason="partnership_ended",
                    manager_ids=[str(m) for m in atingidos],
                )
```

E no teste da Task 7, o patch e a asserção passam a ser sobre `record_access_revocation`, checando `await_args.kwargs["reason"] == "partnership_ended"`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_meta_reconcile_job.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Rodar a suíte de jobs inteira**

Run: `python -m pytest tests/unit -k "resync or job" -q`
Expected: PASS. `test_job_partial_failure_audit.py` e `test_meta_resync_audit.py` provavelmente precisam de ajuste de nome (`resync_meta` → `reconcile_meta`) — ajuste o alvo, **não** o contrato que eles provam.

- [ ] **Step 6: Commit**

```bash
git add src/jobs/meta_resync.py tests/unit
git commit -m "feat(jobs): resync Meta vira reconciliacao contra a parceria"
```

---

## Task 8: as três filas no painel

**Files:**
- Modify: `src/web/routes.py` (`admin_accounts_meta` + nova rota de restaurar)
- Modify: `src/web/templates/admin/accounts_meta.html`
- Test: `tests/integration/test_web_panel_admin.py` (acrescentar casos)

**Interfaces:**
- Consumes: `manager_meta_account_access.restore_for_account` (Task 5), `meta_ad_accounts.set_reachable`/`deactivate` (Task 4, usados no teste).
- Produces: `async list_queues(conn) -> ReconcileQueues` em `meta_ad_accounts`, e a rota `POST /admin/accounts/meta/{ad_account_id}/restore`.

**`list_out_of_reach` (do F128) não serve e sai nesta task.** Ela devolve `is_active = false OR missed_syncs > 0`, o que não distingue as três filas: não sabe se a conta tem gestor delegado (precisa cruzar com os grants) nem se o system user a alcança (precisa de `su_reachable`). Substituir por:

```python
@dataclass(frozen=True, slots=True)
class ReconcileQueues:
    sem_delegacao: list[MetaAdAccount]
    sem_su: list[MetaAdAccount]
    saiu_da_parceria: list[tuple[MetaAdAccount, int]]  # conta + nº de grants revogados


async def list_queues(conn: asyncpg.Connection) -> ReconcileQueues:
    """As três filas do painel. Cada uma é uma AÇÃO diferente do admin."""
    sem_delegacao = await conn.fetch(
        """
        SELECT a.* FROM meta_ad_accounts a
         WHERE a.is_active = true
           AND NOT EXISTS (
               SELECT 1 FROM manager_meta_account_access m
                WHERE m.ad_account_id = a.ad_account_id AND m.revoked_at IS NULL
           )
         ORDER BY a.account_name
        """
    )
    sem_su = await conn.fetch(
        "SELECT * FROM meta_ad_accounts "
        "WHERE is_active = true AND su_reachable = false ORDER BY account_name"
    )
    # F59: toda coluna aliasada em query com JOIN.
    saiu = await conn.fetch(
        """
        SELECT a.*, count(m.manager_id) FILTER (WHERE m.revoked_at IS NOT NULL) AS revogados
          FROM meta_ad_accounts a
          LEFT JOIN manager_meta_account_access m ON m.ad_account_id = a.ad_account_id
         WHERE a.is_active = false
         GROUP BY a.ad_account_id
         ORDER BY a.account_name
        """
    )
    return ReconcileQueues(
        sem_delegacao=[_row_to_account(r) for r in sem_delegacao],
        sem_su=[_row_to_account(r) for r in sem_su],
        saiu_da_parceria=[(_row_to_account(r), r["revogados"]) for r in saiu],
    )
```

Remover `list_out_of_reach` e a seção de template do F128 que a consumia — as três filas a substituem por completo.

- [ ] **Step 1: Write the failing test**

```python
# acrescentar a tests/integration/test_web_panel_admin.py
# (usa os helpers que já existem no topo do arquivo: _bootstrap_admin_and_gestor,
#  _admin_cookie, PANEL_SESSION_COOKIE_NAME)


def _conta_meta(ad_account_id: str, nome: str) -> dict:
    return {
        "ad_account_id": ad_account_id,
        "business_id": "bm",
        "business_name": "BM",
        "account_name": nome,
        "currency": "BRL",
        "timezone_name": "America/Sao_Paulo",
        "account_status": 1,
    }


@pytest.mark.integration
async def test_painel_meta_separa_as_tres_filas(client: AsyncClient) -> None:
    """Sem delegacao, sem SU e fora da parceria sao acoes DIFERENTES."""
    pool = connection.get_pool()
    admin_id, gestor_id = await _bootstrap_admin_and_gestor(pool)
    async with pool.acquire() as conn:
        await meta_ad_accounts.upsert_many(
            conn,
            [
                _conta_meta("act_sem_delegacao", "Nova sem gestor"),
                _conta_meta("act_sem_su", "Na parceria sem SU"),
                _conta_meta("act_saiu", "Ex-cliente"),
            ],
        )
        # fila 2: na parceria, mas o system user não foi atribuído
        await meta_ad_accounts.set_reachable(
            conn, reachable_ids=["act_sem_delegacao", "act_saiu"]
        )
        # fila 3: saiu da parceria — desativada e com o grant do gestor revogado
        await manager_meta_account_access.bulk_grant(
            conn, manager_id=gestor_id, ad_account_ids=["act_saiu"], granted_by=admin_id
        )
        await meta_ad_accounts.deactivate(conn, ad_account_ids=["act_saiu"])
        await manager_meta_account_access.revoke_for_account(
            conn, ad_account_id="act_saiu", reason="partnership_ended"
        )

    resp = await client.get(
        "/admin/accounts/meta",
        cookies={PANEL_SESSION_COOKIE_NAME: _admin_cookie(admin_id)},
    )

    assert resp.status_code == 200
    assert "Aguardando delegação" in resp.text
    assert "Sem o system user atribuído" in resp.text
    assert "Saíram da parceria" in resp.text
    # cada conta cai na SUA fila, e não em todas
    assert "Nova sem gestor" in resp.text
    assert "Ex-cliente" in resp.text


@pytest.mark.integration
async def test_restaurar_reconcede_os_grants_revogados(client: AsyncClient) -> None:
    pool = connection.get_pool()
    admin_id, gestor_id = await _bootstrap_admin_and_gestor(pool)
    async with pool.acquire() as conn:
        await meta_ad_accounts.upsert_many(conn, [_conta_meta("act_saiu", "Ex-cliente")])
        await manager_meta_account_access.bulk_grant(
            conn, manager_id=gestor_id, ad_account_ids=["act_saiu"], granted_by=admin_id
        )
        await manager_meta_account_access.revoke_for_account(
            conn, ad_account_id="act_saiu", reason="partnership_ended"
        )

    resp = await client.post(
        "/admin/accounts/meta/act_saiu/restore",
        cookies={PANEL_SESSION_COOKIE_NAME: _admin_cookie(admin_id)},
        follow_redirects=False,
    )

    assert resp.status_code == 303  # F107: POST de mutação sem HTMX é 303
    async with pool.acquire() as conn:
        assert (
            await manager_meta_account_access.can_manager_access(conn, gestor_id, "act_saiu")
        ) is True
```

O import de `manager_meta_account_access` precisa entrar na lista de `from src.db.repositories import (...)` no topo do arquivo.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/integration/test_web_panel_admin.py -k "tres_filas or restaurar" -q`
Expected: FAIL — texto ausente / 404 na rota.

- [ ] **Step 3: Implementar rota e template**

Em `routes.py`, `admin_accounts_meta` passa a montar as três listas a partir do inventário (`sem_delegacao`, `sem_su`, `fora_da_parceria`) e a rota nova chama `restore_for_account` e devolve `303` para `/admin/accounts/meta?ok=restored` (`204` + `HX-Refresh` se `HX-Request`, espelhando `sessions_revoke`).

No template, as três seções seguem as regras do painel — **cada tabela dentro de `<div class="v4-table-wrap" tabindex="0" role="region" aria-label="…">`** (F118/F125, cobrado por guard), zero JS/CSS inline (a confirmação do restaurar usa `data-v4-action="confirm"`), e o flash vem de mapa fixo código→mensagem, nunca do query param.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/integration/test_web_panel_admin.py -q` (ou no CI, se sem Docker)
Expected: PASS

- [ ] **Step 5: Regenerar o CSS se entrou classe utilitária nova**

Run: `python scripts/build_tailwind.py`
Commitar `src/web/static/v4-tailwind.css` **no mesmo commit** — o CI faz `git diff --exit-code`. Cuidado: o scanner lê o arquivo inteiro, comentário incluído; não cite nome de utilitário em comentário.

- [ ] **Step 6: Commit**

```bash
git add src/web tests/integration/test_web_panel_admin.py
git commit -m "feat(admin): tres filas da reconciliacao Meta no painel"
```

---

## Encerramento

- [ ] **Rodar o gate completo e o full sweep**

```bash
python scripts/check_pre_push.py
python scripts/check_pre_push_full.py   # exige Docker; se indisponível, o CI é o validador
```

- [ ] **Push e confirmar o CI pela conclusão, nunca pelo exit code do watch**

```bash
git push origin main
gh run view <id> --json conclusion
```

- [ ] **Observar o dry-run**

Com `META_RECONCILE_APPLY=false`, a linha `meta_reconcile` no `audit_log` deve mostrar, na primeira execução: `added=2`, `removed=1`, `unreachable=2`, `applied=false`. Se mostrar outra coisa, o desenho está errado **e ninguém perdeu acesso** — que é o ponto do dry-run.

- [ ] **Virar a chave e verificar o critério de aceite**

Após a observação, `META_RECONCILE_APPLY=true`. Critério: `Mestre da Obra Petrolina` sai sozinha — inventário desativado, 4 grants com `revoked_reason='partnership_ended'`, linha `meta_access_cleanup` no audit — sem ninguém tocar na matriz.

- [ ] **Registrar no catálogo e no estado-atual**

F128 ganha um adendo apontando para esta reconciliação (o contador mudou de fonte), e o `estado-atual.md` recebe a pendência do lado Google, que tem o mesmo buraco no gate e ficou fora de escopo.
