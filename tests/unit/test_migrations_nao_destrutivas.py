"""Migration nova nao derruba nem renomeia nada sem aprovacao escrita.

O deploy aplica a migration ANTES de a revisao nova subir, e o rollback so
reverte trafego: durante a janela (e para sempre, se o smoke falhar) o codigo
VELHO roda contra o schema NOVO. `DROP` e `RENAME` quebram esse codigo velho;
`ADD COLUMN`/`CREATE INDEX` nao. Por isso a regra e expand/contract: migration
destrutiva so entra com a linha `-- destrutiva-aprovada: <motivo>` no arquivo.

Vale so acima da 011: as anteriores ja estao em producao (a 004 renomeou uma
coluna) e nao mudam.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_DIR = Path(__file__).resolve().parents[2] / "src" / "db" / "migrations"
_PRIMEIRA_GUARDADA = 12  # acima da 011
_PERIGOSO = re.compile(r"\b(DROP|RENAME)\b", re.IGNORECASE)
_APROVACAO = re.compile(r"^\s*--\s*destrutiva-aprovada:[ \t]*\S", re.MULTILINE)


def _sem_comentarios(sql: str) -> str:
    sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
    return "\n".join(linha.split("--", 1)[0] for linha in sql.splitlines())


def violacao(sql: str) -> str | None:
    """Devolve o termo perigoso sem aprovacao, ou None."""
    achado = _PERIGOSO.search(_sem_comentarios(sql))
    if achado and not _APROVACAO.search(sql):
        return achado.group(1).upper()
    return None


def _migrations_guardadas() -> list[Path]:
    return [
        p for p in sorted(_DIR.glob("*.sql")) if int(p.name.split("_", 1)[0]) >= _PRIMEIRA_GUARDADA
    ]


def test_o_diretorio_de_migrations_existe() -> None:
    assert len(list(_DIR.glob("0*.sql"))) >= 11, "o guard apontou para o diretorio errado"


@pytest.mark.parametrize("sql", ["DROP TABLE x;", "alter table t rename column a to b;"])
def test_o_guard_acusa_drop_e_rename(sql: str) -> None:
    assert violacao(sql) is not None


def test_o_guard_aceita_a_aprovacao_com_motivo() -> None:
    assert violacao("-- destrutiva-aprovada: coluna sem leitor desde o F190\nDROP TABLE x;") is None


def test_aprovacao_sem_motivo_nao_vale() -> None:
    assert violacao("-- destrutiva-aprovada:\nDROP TABLE x;") is not None


def test_o_guard_ignora_a_palavra_em_comentario() -> None:
    assert violacao("-- nao faz DROP nem RENAME\nALTER TABLE t ADD COLUMN a int;") is None


def test_o_guard_ve_a_migration_001_a_011_como_fora_do_escopo() -> None:
    nomes = {p.name.split("_", 1)[0] for p in _migrations_guardadas()}
    assert "004" not in nomes


@pytest.mark.parametrize("arq", _migrations_guardadas(), ids=lambda p: p.name)
def test_migration_nao_destrutiva(arq: Path) -> None:
    termo = violacao(arq.read_text(encoding="utf-8"))
    assert termo is None, f"{arq.name} usa {termo} sem `-- destrutiva-aprovada: <motivo>`"
