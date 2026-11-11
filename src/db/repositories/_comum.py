"""Utilidades compartilhadas pelos repositórios."""


def linhas_afetadas(status: str) -> int:
    """Contagem de linhas do command tag que o `execute` do asyncpg devolve.

    'UPDATE 3' -> 3, 'INSERT 0 2' -> 2, 'DELETE 0' -> 0: a contagem é sempre o
    último token. Tag malformada (vazia ou sem número no fim) levanta
    `ValueError` em vez de virar 0 — "0 linhas" afirmaria uma medição que não
    houve.
    """
    return int(status.rsplit(" ", 1)[-1])
