"""CLI do restore: sem host confirmado nao conecta (a trava contra o banco errado)."""

from types import SimpleNamespace

import pytest

from src.jobs import restore

DSN = "postgresql://postgres.abc:S3nh4Secreta@db.prod.supabase.co:5432/postgres"


@pytest.fixture
def sem_conexao(monkeypatch):
    chamadas: list[object] = []
    monkeypatch.setattr(restore, "get_settings", lambda: SimpleNamespace(database_url=DSN))

    async def _run(pasta, *a, **kw):
        chamadas.append(pasta)
        return 0

    monkeypatch.setattr(restore, "run", _run)
    return chamadas


def test_sem_confirmar_host_sai_2_mostra_host_sem_senha(sem_conexao, capsys) -> None:
    assert restore.main(["pasta"]) == 2
    saida = capsys.readouterr()
    texto = saida.out + saida.err
    assert "db.prod.supabase.co" in texto
    assert "S3nh4Secreta" not in texto
    assert "postgres.abc" not in texto
    assert sem_conexao == []


def test_host_divergente_sai_2_sem_conectar(sem_conexao, capsys) -> None:
    assert restore.main(["pasta", "--confirmar-host", "localhost"]) == 2
    saida = capsys.readouterr()
    texto = saida.out + saida.err
    assert "db.prod.supabase.co" in texto
    assert "S3nh4Secreta" not in texto
    assert sem_conexao == []


def test_host_confirmado_segue(sem_conexao) -> None:
    assert restore.main(["pasta", "--confirmar-host", "db.prod.supabase.co"]) == 0
    assert len(sem_conexao) == 1
