"""Guards estruturais: varrem o source pra impedir reincidência de classes de bug.

Cada guard aqui existe porque a classe já mordeu em produção e a proteção era
"lembrar de fazer grep manual" (documentada no CLAUDE.md). Um guard automatizado
transforma a convenção num teste que falha no commit em vez de num incidente.

- F57 (Google): call-site de build_client_for_manager sem ensure_account_access
  → vazou existência/schema de qualquer conta da MCC (o validate_gaql ficou
  desguarnecido até a auditoria de 2026-06-20).
- F57-Meta: chamada à Graph API fora de run_meta_graph_get → pula o hard-gate
  (o freio do Modelo B é a matriz de acesso; o token é compartilhado).
- F58: conn.cursor() sem async with conn.transaction() → asyncpg exige transação
  pra server-side cursor (o CSV export quebrou em prod porque nenhum teste iterou).
"""

from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"


def _py_files() -> list[Path]:
    return [p for p in SRC.rglob("*.py") if "__pycache__" not in p.parts]


def test_build_client_for_manager_callsites_have_gate() -> None:
    """F57: todo arquivo que CHAMA build_client_for_manager também chama
    ensure_account_access. client.py o DEFINE (allowlist)."""
    definer = SRC / "google_ads" / "client.py"
    offenders = []
    for p in _py_files():
        if p == definer:
            continue
        text = p.read_text(encoding="utf-8")
        if "build_client_for_manager(" in text and "ensure_account_access(" not in text:
            offenders.append(str(p.relative_to(SRC)))
    assert not offenders, (
        "F57 — call-site de build_client_for_manager SEM ensure_account_access: "
        f"{offenders}. Todo caminho que builda o client Google precisa do hard-gate "
        "no mesmo fluxo (grep TODA função que chama build_client_for_manager)."
    )


def test_meta_graph_execution_is_contained() -> None:
    """F57-Meta: build_meta_api (o factory de execução com o system-user token) só
    pode ser chamado dentro de run_meta_graph_get (reports.py), que aplica o gate.
    client.py o DEFINE. Um tool que chame direto pularia o hard-gate incondicional."""
    allowed = {
        SRC / "meta_ads" / "client.py",  # define build_meta_api
        SRC / "meta_ads" / "reports.py",  # run_meta_graph_get — único executor
    }
    offenders = []
    for p in _py_files():
        if p in allowed:
            continue
        if "build_meta_api(" in p.read_text(encoding="utf-8"):
            offenders.append(str(p.relative_to(SRC)))
    assert not offenders, (
        "F57-Meta — build_meta_api chamado fora de reports.py: "
        f"{offenders}. Toda leitura Meta deve passar por run_meta_graph_get "
        "(gate can_manager_access + audit + BUC)."
    )


def test_cursor_usage_is_wrapped_in_transaction() -> None:
    """F58: arquivo que usa conn.cursor() (server-side cursor) precisa também
    de conn.transaction() — asyncpg exige transação explícita, senão o generator
    quebra no primeiro fetch (o CSV export foi pra prod quebrado assim)."""
    offenders = []
    for p in _py_files():
        text = p.read_text(encoding="utf-8")
        if ".cursor(" in text and "conn.transaction()" not in text:
            offenders.append(str(p.relative_to(SRC)))
    assert not offenders, (
        "F58 — .cursor() sem conn.transaction() no mesmo arquivo: "
        f"{offenders}. async for row in conn.cursor(...) PRECISA de "
        "async with conn.transaction()."
    )
