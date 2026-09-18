"""Keyset (seek) pagination do audit_log — Task 7, PR 5.

A frente 6 (ja em producao) entregou o desempate estavel `ORDER BY
occurred_at DESC, id DESC` e a migration 010 criou `idx_audit_occurred_at`
exatamente nesse par de colunas. Esta tarefa troca o `OFFSET` das duas rotas
paginadas (`/audit`, `/admin/audit`) por um cursor `(occurred_at, id)`.

Ver `src/db/repositories/audit_log.py::list_page_for_manager`/`list_page_admin`
e o brief em `.superpowers/sdd/2026-09-17-pr5-painel/task-7-brief.md`.
"""

from uuid import uuid4

import asyncpg
import pytest

from src.db.repositories import audit_log


async def _seed_tied_batch(conn: asyncpg.Connection, *, manager_id: object, n: int) -> list[int]:
    """Insere `n` linhas na MESMA transacao — um unico `now()`, F98/F88 — e
    devolve os ids em ordem de insercao (id1 < id2 < ... < idn). Occurred_at
    empatado de proposito: e o caso real de auditoria de lote, nao um cenario
    forcado."""
    async with conn.transaction():
        ids = [
            await conn.fetchval(
                "INSERT INTO audit_log (manager_id, action_type, operation, status, occurred_at) "
                "VALUES ($1, 'read', $2, 'success', now()) RETURNING id",
                manager_id,
                f"op{i}",
            )
            for i in range(n)
        ]
    return [int(i) for i in ids]


@pytest.mark.integration
async def test_keyset_nao_duplica_nem_perde_linha_com_insercao_entre_paginas(db):
    """O item 3 do brief: o caso que separa isto de "trocar uma clausula por
    outra".

    5 linhas nascem EMPATADAS em `occurred_at`. Pagina 1 (limit=3) pega as 3
    de maior id (F98/F88). ANTES de buscar a pagina 2, uma linha NOVA entra
    com `occurred_at` MAIS RECENTE que o lote — "chegou evento novo enquanto
    eu navegava".

    Com `OFFSET`, a pagina 2 (`OFFSET 3`) deslizaria: a linha nova assume o
    topo da ordenacao, empurra as outras uma posicao, e a linha que estava no
    indice 2 (dentro da pagina 1) passa a cair no indice 3 (inicio da pagina
    2) — repete. Com keyset, a pagina 2 ancora no ULTIMO `(occurred_at, id)`
    visto e ignora tudo mais novo que o cursor, esteja dentro ou fora do lote
    original.
    """
    mid = uuid4()
    pool = db
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO managers (id, email, status, role) "
            "VALUES ($1, 'keyset@v4company.com', 'active', 'gestor')",
            mid,
        )
        ids = await _seed_tied_batch(conn, manager_id=mid, n=5)

        instantes = await conn.fetch(
            "SELECT DISTINCT occurred_at FROM audit_log WHERE manager_id = $1", mid
        )
        assert len(instantes) == 1, "controle: as 5 linhas TEM que empatar em occurred_at"

        pagina1, cursor1 = await audit_log.list_page_for_manager(
            conn, manager_id=mid, days=7, limit=3
        )
        pagina1_ids = [r["id"] for r in pagina1]
        assert pagina1_ids == sorted(ids, reverse=True)[:3], (
            "com empate em occurred_at, a pagina 1 tem que ser as 3 de maior id (F98/F88)"
        )
        assert cursor1 is not None, "5 linhas semeadas > limit=3: TEM que sobrar proxima pagina"

        # Insercao ENTRE as duas paginas — o caso que so o keyset acerta.
        # occurred_at explicitamente mais novo (nao so "depois no tempo real"):
        # torna a ordenacao determinista mesmo se dois now() caissem no mesmo
        # microssegundo.
        nova_id = await conn.fetchval(
            "INSERT INTO audit_log (manager_id, action_type, operation, status, occurred_at) "
            "VALUES ($1, 'read', 'op_novo_durante_navegacao', 'success', "
            "now() + interval '1 second') RETURNING id",
            mid,
        )
        nova_id = int(nova_id)

        pagina2, cursor2 = await audit_log.list_page_for_manager(
            conn,
            manager_id=mid,
            days=7,
            limit=3,
            cursor_occurred_at=cursor1[0],
            cursor_id=cursor1[1],
        )
        pagina2_ids = [r["id"] for r in pagina2]

        # Bonus, mesma conexao: a linha nova nao sumiu do mundo, so nao faz
        # parte desta caminhada — um reload da pagina 1 (cursor=None) tem que
        # traze-la em primeiro lugar (e a mais recente de todas agora).
        pagina1_de_novo, _ = await audit_log.list_page_for_manager(
            conn, manager_id=mid, days=7, limit=3
        )

    # 1. Nenhuma linha aparece em duas paginas.
    repetidas = set(pagina1_ids) & set(pagina2_ids)
    assert repetidas == set(), f"linha repetida entre paginas: {repetidas}"

    # 2. Nenhuma linha do lote ORIGINAL some entre as paginas.
    assert set(pagina1_ids) | set(pagina2_ids) == set(ids), (
        "a uniao das duas paginas tem que cobrir as 5 linhas semeadas antes do cursor"
    )

    # 3. O caso que separa isto de uma troca de clausula: a linha na BORDA da
    #    pagina 1 (a de menor id ali, a ultima mostrada) nao pode reaparecer —
    #    e exatamente o deslize que o OFFSET erra. E a linha inserida DEPOIS
    #    do cursor (mais nova que ele) fica de fora desta caminhada: ela nao
    #    existia quando o cursor foi cortado.
    borda_pagina1 = pagina1_ids[-1]
    assert borda_pagina1 not in pagina2_ids, (
        "a linha na borda da pagina 1 reapareceu na pagina 2 — e o deslize que "
        "o OFFSET erra e o keyset existe pra evitar"
    )
    assert nova_id not in pagina2_ids, (
        "linha inserida DEPOIS do cursor vazou pra dentro da pagina 2"
    )
    assert cursor2 is None, (
        "5 semeadas, 3 na pagina 1, 2 restantes cabem inteiras na pagina 2 — acabou"
    )

    assert pagina1_de_novo[0]["id"] == nova_id, (
        "reload do zero (cursor=None) tem que trazer a linha nova primeiro"
    )


@pytest.mark.integration
async def test_keyset_admin_tambem_pagina_por_cursor_sem_sobreposicao(db):
    """`/admin/audit` usa `list_page_admin` — WHERE e SELECT diferentes (sem
    escopo por manager_id, join extra com `managers` pro e-mail), mesma
    ancora `(occurred_at, id)`. Prova mais enxuta que a de cima: sem
    sobreposicao nem perda entre 2 paginas do mesmo lote empatado — confirma
    que o SEGUNDO call-site tambem usa o cursor de verdade, nao so o
    primeiro."""
    mid = uuid4()
    pool = db
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO managers (id, email, status, role) "
            "VALUES ($1, 'keyset-admin@v4company.com', 'active', 'gestor')",
            mid,
        )
        ids = await _seed_tied_batch(conn, manager_id=mid, n=5)

        pagina1, cursor1 = await audit_log.list_page_admin(conn, days=7, limit=3)
        assert cursor1 is not None

        pagina2, cursor2 = await audit_log.list_page_admin(
            conn, days=7, limit=3, cursor_occurred_at=cursor1[0], cursor_id=cursor1[1]
        )

    pagina1_ids = {r["id"] for r in pagina1}
    pagina2_ids = {r["id"] for r in pagina2}
    assert pagina1_ids & pagina2_ids == set(), "sobreposicao entre paginas do admin"
    assert pagina1_ids | pagina2_ids == set(ids), "linha perdida entre paginas do admin"
    assert cursor2 is None


@pytest.mark.integration
async def test_keyset_query_usa_indice_nao_seq_scan(db):
    """Step 5 do brief: um keyset que nao usa indice e mais lento que o OFFSET
    que substituiu — e isso so aparece medindo. Semeia volume realista (tabela
    pequena demais faz o Postgres preferir Seq Scan mesmo com indice
    disponivel, por ser mais barato de fato nesse tamanho) e roda EXPLAIN
    ANALYZE na MESMA forma de WHERE que list_page_admin/list_page_for_manager
    emitem — cursor preenchido (pagina >= 2 de verdade, nao a primeira).
    """
    pool = db
    async with pool.acquire() as conn:
        m1, m2, m3 = uuid4(), uuid4(), uuid4()
        await conn.execute(
            "INSERT INTO managers (id, email, status, role) VALUES "
            "($1, 'q1@v4company.com', 'active', 'gestor'), "
            "($2, 'q2@v4company.com', 'active', 'gestor'), "
            "($3, 'q3@v4company.com', 'active', 'gestor')",
            m1,
            m2,
            m3,
        )
        # Bulk insert via generate_series: 20k linhas com occurred_at
        # ESPALHADO (nao empatado) pelas ultimas ~5.5h, dentro da janela
        # padrao de 7 dias — perfil mais realista que um loop de 20k INSERTs
        # avulsos, e rapido (uma unica query).
        await conn.execute(
            """
            INSERT INTO audit_log (manager_id, action_type, operation, status, occurred_at)
            SELECT
                (ARRAY[$1::uuid, $2::uuid, $3::uuid])[1 + (g % 3)],
                'read',
                'op_' || g,
                'success',
                now() - (g || ' seconds')::interval
            FROM generate_series(1, 20000) AS g
            """,
            m1,
            m2,
            m3,
        )
        await conn.execute("ANALYZE audit_log")

        # Cursor de uma linha real (por volta da metade), pra simular pagina
        # 2+ de verdade — nao a primeira pagina (cursor NULL), que e um plano
        # diferente.
        cursor_row = await conn.fetchrow(
            "SELECT occurred_at, id FROM audit_log ORDER BY occurred_at DESC, id DESC "
            "OFFSET 10000 LIMIT 1"
        )
        assert cursor_row is not None

        # list_page_admin: SEM filtro de manager_id — o caso que a migration
        # 010 nomeia explicitamente ("listagem geral do audit... sem filtrar
        # por nenhuma das tres [manager_id, customer_id, platform]").
        plano_admin = await conn.fetch(
            """EXPLAIN (ANALYZE, BUFFERS)
               SELECT al.id, al.occurred_at, al.action_type, al.operation,
                      al.customer_id, al.target_count, al.status, al.duration_ms
               FROM audit_log al
               WHERE al.occurred_at > now() - ($1 || ' days')::interval
                 AND ($2::timestamptz IS NULL OR (al.occurred_at, al.id) < ($2, $3))
               ORDER BY al.occurred_at DESC, al.id DESC
               LIMIT $4""",
            "7",
            cursor_row["occurred_at"],
            cursor_row["id"],
            51,
        )
        texto_admin = "\n".join(r["QUERY PLAN"] for r in plano_admin)

        # Mesma query, cursor NULL — a PRIMEIRA pagina (o caminho mais comum
        # na pratica: todo load de /audit ou /admin/audit sem clicar em
        # "Proxima" cai aqui). O `$2 IS NULL OR` muda o formato da expressao;
        # confirma que o ramo NULL tambem usa o indice, nao só o ramo com
        # cursor preenchido testado acima.
        plano_admin_pagina1 = await conn.fetch(
            """EXPLAIN (ANALYZE, BUFFERS)
               SELECT al.id, al.occurred_at, al.action_type, al.operation,
                      al.customer_id, al.target_count, al.status, al.duration_ms
               FROM audit_log al
               WHERE al.occurred_at > now() - ($1 || ' days')::interval
                 AND ($2::timestamptz IS NULL OR (al.occurred_at, al.id) < ($2, $3))
               ORDER BY al.occurred_at DESC, al.id DESC
               LIMIT $4""",
            "7",
            None,
            None,
            51,
        )
        texto_admin_pagina1 = "\n".join(r["QUERY PLAN"] for r in plano_admin_pagina1)

        # list_page_for_manager: filtrado por manager_id — pode legitimamente
        # preferir idx_audit_manager_time (manager_id, occurred_at DESC), que
        # JA EXISTIA antes da migration 010 (001_initial_schema.sql) e tambem
        # cobre o filtro. O que importa pra este teste e NAO cair pra Seq Scan.
        plano_manager = await conn.fetch(
            """EXPLAIN (ANALYZE, BUFFERS)
               SELECT al.id, al.occurred_at, al.action_type, al.operation,
                      al.customer_id, al.target_count, al.status, al.duration_ms
               FROM audit_log al
               WHERE al.manager_id = $1
                 AND al.occurred_at > now() - ($2 || ' days')::interval
                 AND ($3::timestamptz IS NULL OR (al.occurred_at, al.id) < ($3, $4))
               ORDER BY al.occurred_at DESC, al.id DESC
               LIMIT $5""",
            m1,
            "7",
            cursor_row["occurred_at"],
            cursor_row["id"],
            51,
        )
        texto_manager = "\n".join(r["QUERY PLAN"] for r in plano_manager)

    # Os 3 planos (mensagem de falha de cada assert abaixo carrega o texto
    # inteiro) tambem foram colados no relatorio da Task 7 — rodado uma vez,
    # manualmente, contra este mesmo teste. Nao grava em disco daqui: caminho
    # de scratchpad e por sessao, gravar um literal aqui quebraria em CI
    # (Linux) e em qualquer outra maquina/sessao.
    assert "Seq Scan" not in texto_admin, f"scan sequencial na query global:\n{texto_admin}"
    assert "idx_audit_occurred_at" in texto_admin, (
        f"a query global (sem filtro de manager) tem que usar o indice que a "
        f"migration 010 criou pra ela:\n{texto_admin}"
    )
    assert "Seq Scan" not in texto_admin_pagina1, (
        f"scan sequencial na primeira pagina (cursor NULL):\n{texto_admin_pagina1}"
    )
    assert "idx_audit_occurred_at" in texto_admin_pagina1, (
        f"a primeira pagina tambem tem que usar o indice — o ramo `IS NULL OR` "
        f"nao pode derrubar o planner pra Seq Scan:\n{texto_admin_pagina1}"
    )
    assert "Seq Scan" not in texto_manager, f"scan sequencial na query por gestor:\n{texto_manager}"
