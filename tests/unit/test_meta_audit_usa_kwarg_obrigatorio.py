"""O audit Meta tem que gravar a conta a partir do kwarg, nao do params_summary.

`ad_account_id` e kwarg OBRIGATORIO de run_meta_graph_get desde o F72 — o gate
roda contra ele. Mas o audit lia `(params_summary or {}).get("ad_account_id")`:
um caller que esquecesse a chave gravava a linha com conta NULA, justamente na
plataforma onde o token e compartilhado e a matriz e o unico freio.

Os 3 callers de hoje passam a chave. O risco e o proximo (M.5).
"""

import ast
from pathlib import Path

import pytest

_REPORTS = Path(__file__).resolve().parents[2] / "src" / "meta_ads" / "reports.py"


def _chamadas_de_audit() -> list[ast.Call]:
    arvore = ast.parse(_REPORTS.read_text(encoding="utf-8"))
    return [
        no
        for no in ast.walk(arvore)
        if isinstance(no, ast.Call)
        and isinstance(no.func, ast.Attribute)
        and no.func.attr == "record"
    ]


def test_ha_audit_no_executor_meta() -> None:
    """Se as chamadas sumirem, o teste abaixo passaria vazio."""
    assert len(_chamadas_de_audit()) >= 3, "esperado denial + erro + sucesso"


@pytest.mark.parametrize("indice", range(3))
def test_audit_meta_grava_conta_do_kwarg(indice: int) -> None:
    """customer_id vem de `ad_account_id`, nunca de um dict opcional."""
    chamadas = _chamadas_de_audit()
    chamada = chamadas[indice]
    argumento = next(
        (kw.value for kw in chamada.keywords if kw.arg == "customer_id"),
        None,
    )
    assert argumento is not None, f"audit em reports.py:{chamada.lineno} sem customer_id"
    origem = ast.unparse(argumento)
    assert origem == "ad_account_id", (
        f"reports.py:{chamada.lineno}: customer_id vem de {origem!r}; use o kwarg "
        "obrigatorio ad_account_id — params_summary e opcional e o caller pode "
        "esquecer a chave, gravando auditoria sem conta"
    )
