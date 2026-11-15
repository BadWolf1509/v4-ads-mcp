"""Núcleo das ESCRITAS dos repositórios de acesso gêmeos (Google x Meta).

`manager_account_access` e `manager_meta_account_access` são a mesma máquina de
estados (grant / revogação soft / cópia) sobre duas tabelas. As cinco escritas
(`grant`, `grant_all_active`, `revoke`, `bulk_grant`, `copy_access`) viviam
escritas duas vezes, e a classe de bug que isso gera é o F167: uma cláusula
`ON CONFLICT` corrigida num gêmeo e esquecida no outro. Aqui o SQL existe UMA
vez, parametrizado por um descritor da tabela; os dois módulos mantêm as
assinaturas públicas de sempre e só delegam.

Fica de FORA, por decisão do plano: `can_manager_access` (o gate é explícito por
plataforma) e `list_accounts_for_manager` (leitura, devolve o tipo de cada lado).

Identificadores no SQL: tabela e coluna não podem ir como parâmetro de bind, então
entram por interpolação. A única fonte deles são os dois descritores deste módulo
(`GOOGLE`, `META`): `TabelaDeAcesso` recusa nome que não seja identificador SQL
simples (`__post_init__`) e toda função do núcleo recusa descritor que não seja um
dos dois (`_exigir_descritor`). Valor de chamador (ids, motivo, nível) vai SEMPRE
por bind (`$n`), nunca pelo texto.
"""

import re
from dataclasses import dataclass, fields
from uuid import UUID

import asyncpg

from src.db.repositories._comum import linhas_afetadas
from src.db.repositories.motivos import BULK_COPY_REPLACED_REASON, MANAGER_DEACTIVATED_REASON

_IDENTIFICADOR = re.compile(r"[a-z_][a-z0-9_]*")


@dataclass(frozen=True, slots=True)
class TabelaDeAcesso:
    """O que muda entre os gêmeos: só NOMES. Comportamento igual nos dois lados
    (decisão de 10/11, G0) — divergência de comportamento não vira campo aqui sem
    passar pelo registro de `tests/unit/test_acesso_gemeos_conformes.py`."""

    tabela: str
    coluna_conta: str
    inventario: str

    def __post_init__(self) -> None:
        for campo in fields(self):
            valor = getattr(self, campo.name)
            if not _IDENTIFICADOR.fullmatch(valor):
                raise ValueError(f"TabelaDeAcesso.{campo.name}: identificador SQL inválido")


GOOGLE = TabelaDeAcesso(
    tabela="manager_account_access",
    coluna_conta="customer_id",
    inventario="google_ads_accounts",
)
META = TabelaDeAcesso(
    tabela="manager_meta_account_access",
    coluna_conta="ad_account_id",
    inventario="meta_ad_accounts",
)

_DESCRITORES = (GOOGLE, META)

# "Gestor desativado" em SQL, sobre o alias `m` de `managers`: a MESMA regra de
# `Manager.is_deactivated` (F84), amarrada a ela por
# `tests/integration/test_revogacao_na_desativacao.py::test_predicado_sql_igual_ao_python`.
# `invited` não conta como desativado. As duas colunas são NOT NULL, então a
# negação (`NOT ...`) não tem terceiro valor.
PREDICADO_DESATIVADO = "(m.is_active = false OR m.status = 'inactive')"


def _exigir_descritor(t: TabelaDeAcesso) -> None:
    # `if`/`raise`, não `assert`: `python -O` apagaria o assert.
    if t not in _DESCRITORES:
        raise ValueError("descritor de acesso desconhecido: use GOOGLE ou META")


def _ao_conflitar_restaura(t: TabelaDeAcesso, *, so_o_que_muda: bool = False) -> str:
    """Reconceder é a forma de restaurar: o conflito limpa a revogação, promove o
    nível (F128) e registra quem e quando (F167, decisão de 10/11) — a MESMA
    cláusula para os quatro INSERTs, que é o ponto deste módulo.

    `so_o_que_muda` (decisão de 11/11, só o `grant_all_active`): o UPDATE pula a
    linha ATIVA no mesmo nível — autor e data originais ficam, e a contagem
    devolvida passa a ser só do que mudou (nova, restaurada ou promovida). Os
    outros três concedem UMA escolha explícita do admin, e ali "atualizar sempre"
    (G0) continua valendo."""
    filtro = (
        f"""
         WHERE {t.tabela}.revoked_at IS NOT NULL
            OR {t.tabela}.access_level IS DISTINCT FROM EXCLUDED.access_level"""
        if so_o_que_muda
        else ""
    )
    return f"""
        ON CONFLICT (manager_id, {t.coluna_conta}) DO UPDATE SET
            access_level = EXCLUDED.access_level,
            granted_at = now(),
            granted_by = EXCLUDED.granted_by,
            revoked_at = NULL,
            revoked_reason = NULL{filtro}"""


async def grant(
    conn: asyncpg.Connection,
    t: TabelaDeAcesso,
    *,
    manager_id: UUID,
    conta: str,
    access_level: str,
    granted_by: UUID | None,
) -> None:
    _exigir_descritor(t)
    await conn.execute(
        f"""
        INSERT INTO {t.tabela} (manager_id, {t.coluna_conta}, access_level, granted_by)
        VALUES ($1, $2, $3, $4){_ao_conflitar_restaura(t)}
        """,
        manager_id,
        conta,
        access_level,
        granted_by,
    )


async def grant_all_active(
    conn: asyncpg.Connection,
    t: TabelaDeAcesso,
    *,
    manager_id: UUID,
    granted_by: UUID | None,
) -> int:
    _exigir_descritor(t)
    result = await conn.execute(
        f"""
        INSERT INTO {t.tabela} (manager_id, {t.coluna_conta}, access_level, granted_by)
        SELECT $1, {t.coluna_conta}, 'write', $2
        FROM {t.inventario}
        WHERE is_active = true{_ao_conflitar_restaura(t, so_o_que_muda=True)}
        """,
        manager_id,
        granted_by,
    )
    return linhas_afetadas(result)


async def revoke(
    conn: asyncpg.Connection,
    t: TabelaDeAcesso,
    *,
    manager_id: UUID,
    conta: str,
    reason: str,
) -> None:
    """Só pega linha viva: revogar de novo trocaria o motivo de churn e tiraria a
    linha do `restore_for_account` (spec 2026-09-28 §3.2.1)."""
    _exigir_descritor(t)
    await conn.execute(
        f"""
        UPDATE {t.tabela}
           SET revoked_at = now(), revoked_reason = $3
         WHERE manager_id = $1 AND {t.coluna_conta} = $2 AND revoked_at IS NULL
        """,
        manager_id,
        conta,
        reason,
    )


async def bulk_grant(
    conn: asyncpg.Connection,
    t: TabelaDeAcesso,
    *,
    manager_id: UUID,
    contas: list[str],
    granted_by: UUID,
    access_level: str,
) -> int:
    """Devolve len(contas): `executemany` com ON CONFLICT não expõe contagem."""
    _exigir_descritor(t)
    if not contas:
        return 0
    rows = [(manager_id, conta, access_level, granted_by) for conta in contas]
    await conn.executemany(
        f"""
        INSERT INTO {t.tabela} (manager_id, {t.coluna_conta}, access_level, granted_by)
        VALUES ($1, $2, $3, $4){_ao_conflitar_restaura(t)}
        """,
        rows,
    )
    return len(rows)


async def copy_access(
    conn: asyncpg.Connection,
    t: TabelaDeAcesso,
    *,
    from_manager_id: UUID,
    to_manager_id: UUID,
    granted_by: UUID,
) -> int:
    """Substitui o acesso VIVO do destino pelo acesso VIVO da origem. Atômico.

    Origem == destino aniquilaria o gestor (o UPDATE revoga tudo, o SELECT não
    acha mais nada vivo): recusa aqui, não só na rota.
    """
    _exigir_descritor(t)
    if from_manager_id == to_manager_id:
        raise ValueError("copy_access: origem e destino sao o mesmo gestor")
    async with conn.transaction():
        # "Replace" primeiro revoga (soft) o que o destino tinha de VIVO — sem
        # isso, uma conta que só o destino tinha ficaria viva pra sempre. Só pega
        # `revoked_at IS NULL`: quem já estava revogado no destino (por churn,
        # `admin_revoked` ou cópia anterior) não é tocado, e essa trilha sobrevive.
        await conn.execute(
            f"""
            UPDATE {t.tabela}
               SET revoked_at = now(), revoked_reason = $2
             WHERE manager_id = $1 AND revoked_at IS NULL
            """,
            to_manager_id,
            BULK_COPY_REPLACED_REASON,
        )
        result = await conn.execute(
            f"""
            INSERT INTO {t.tabela} (manager_id, {t.coluna_conta}, access_level, granted_by)
            SELECT $1, {t.coluna_conta}, access_level, $2
              FROM {t.tabela}
             WHERE manager_id = $3 AND revoked_at IS NULL{_ao_conflitar_restaura(t)}
            """,
            to_manager_id,
            granted_by,
            from_manager_id,
        )
    return linhas_afetadas(result)


async def revogar_de_desativados(
    conn: asyncpg.Connection,
    t: TabelaDeAcesso,
    *,
    motivo_churn: str,
    manager_id: UUID | None = None,
) -> list[tuple[UUID, str]]:
    """Revoga (soft) todo grant VIVO de gestor desativado.

    O motivo nomeia o que bloqueia agora, e com dois bloqueios vale o da conta:
    conta ativa recebe `manager_deactivated`; conta já inativa recebe
    `motivo_churn` (o de churn do lado), para que a volta da conta a trate como
    churn e não fique presa a um motivo que a reativação não alcançaria.

    Opera sobre o ESTADO, não sobre o delta (lição do
    `revoke_for_inactive_accounts`): pega também o grant concedido depois da
    desativação e a desativação feita por SQL direto. Com `manager_id`, só
    daquele gestor (a rota); sem, todos (o job). Linha já revogada não é tocada:
    revogar de novo trocaria o motivo e a tiraria da restauração que lhe cabe.
    Devolve `(manager_id, conta)` de cada grant revogado. A transação é do
    chamador.
    """
    _exigir_descritor(t)
    rows = await conn.fetch(
        f"""
        UPDATE {t.tabela} g
           SET revoked_at = now(),
               revoked_reason = CASE WHEN a.is_active THEN $1 ELSE $2 END
          FROM managers m, {t.inventario} a
         WHERE m.id = g.manager_id
           AND a.{t.coluna_conta} = g.{t.coluna_conta}
           AND {PREDICADO_DESATIVADO}
           AND g.revoked_at IS NULL
           AND ($3::uuid IS NULL OR g.manager_id = $3::uuid)
        RETURNING g.manager_id, g.{t.coluna_conta} AS conta
        """,
        MANAGER_DEACTIVATED_REASON,
        motivo_churn,
        manager_id,
    )
    return [(r["manager_id"], r["conta"]) for r in rows]


async def restaurar_de_reativados(
    conn: asyncpg.Connection,
    t: TabelaDeAcesso,
    *,
    motivo_churn: str,
    manager_id: UUID | None = None,
) -> tuple[list[tuple[UUID, str]], list[tuple[UUID, str]]]:
    """Devolve só o que a desativação tirou, a gestor que não está desativado.

    Só linhas `manager_deactivated`: revogação de admin, cópia e churn não voltam
    por aqui. Dois UPDATEs na mesma conexão, sobre conjuntos disjuntos (conta
    inativa x ativa):

    1. conta INATIVA: a linha continua revogada e o motivo vira `motivo_churn`
       (o de churn do lado: `left_mcc` / `partnership_ended`), para que a volta
       da conta a devolva — com dois bloqueios, vale o da conta;
    2. conta ATIVA: `revoked_at = NULL, revoked_reason = NULL`.

    Devolve `(restaurados, remarcados_como_churn)`, cada um com
    `(manager_id, conta)`. A transação é do chamador.
    """
    _exigir_descritor(t)
    remarcados = await conn.fetch(
        f"""
        UPDATE {t.tabela} g
           SET revoked_reason = $1
          FROM managers m, {t.inventario} a
         WHERE m.id = g.manager_id
           AND a.{t.coluna_conta} = g.{t.coluna_conta}
           AND NOT {PREDICADO_DESATIVADO}
           AND a.is_active = false
           AND g.revoked_at IS NOT NULL
           AND g.revoked_reason = $2
           AND ($3::uuid IS NULL OR g.manager_id = $3::uuid)
        RETURNING g.manager_id, g.{t.coluna_conta} AS conta
        """,
        motivo_churn,
        MANAGER_DEACTIVATED_REASON,
        manager_id,
    )
    restaurados = await conn.fetch(
        f"""
        UPDATE {t.tabela} g
           SET revoked_at = NULL, revoked_reason = NULL
          FROM managers m, {t.inventario} a
         WHERE m.id = g.manager_id
           AND a.{t.coluna_conta} = g.{t.coluna_conta}
           AND NOT {PREDICADO_DESATIVADO}
           AND a.is_active = true
           AND g.revoked_at IS NOT NULL
           AND g.revoked_reason = $1
           AND ($2::uuid IS NULL OR g.manager_id = $2::uuid)
        RETURNING g.manager_id, g.{t.coluna_conta} AS conta
        """,
        MANAGER_DEACTIVATED_REASON,
        manager_id,
    )
    return (
        [(r["manager_id"], r["conta"]) for r in restaurados],
        [(r["manager_id"], r["conta"]) for r in remarcados],
    )


async def planejar_convergencia(
    conn: asyncpg.Connection,
    t: TabelaDeAcesso,
    *,
    motivo_churn: str,
) -> dict[str, int]:
    """Quantas linhas `revogar_de_desativados` e `restaurar_de_reativados` (sem
    `manager_id`) mudariam agora, sem escrever: o dry-run do job.

    Mesmos predicados das duas funções, num `SELECT count` só. Os três conjuntos
    são disjuntos (gestor desativado x não; conta ativa x inativa), então rodar as
    duas em seguida muda exatamente essas contagens. `motivo_churn` não muda a
    contagem (remarcar troca o motivo, não a população); é recebido para que o
    chamador passe ao plano o MESMO par `(t, motivo_churn)` do apply.
    """
    _exigir_descritor(t)
    row = await conn.fetchrow(
        f"""
        SELECT
            count(*) FILTER (
                WHERE {PREDICADO_DESATIVADO} AND g.revoked_at IS NULL
            ) AS a_revogar,
            count(*) FILTER (
                WHERE NOT {PREDICADO_DESATIVADO}
                  AND g.revoked_at IS NOT NULL AND g.revoked_reason = $1
                  AND a.is_active = true
            ) AS a_restaurar,
            count(*) FILTER (
                WHERE NOT {PREDICADO_DESATIVADO}
                  AND g.revoked_at IS NOT NULL AND g.revoked_reason = $1
                  AND a.is_active = false
            ) AS a_remarcar
          FROM {t.tabela} g
          JOIN managers m ON m.id = g.manager_id
          JOIN {t.inventario} a ON a.{t.coluna_conta} = g.{t.coluna_conta}
        """,
        MANAGER_DEACTIVATED_REASON,
    )
    return {
        "a_revogar": int(row["a_revogar"]),
        "a_restaurar": int(row["a_restaurar"]),
        "a_remarcar": int(row["a_remarcar"]),
    }
