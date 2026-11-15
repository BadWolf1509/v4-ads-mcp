"""Guard: as filas do painel contam só o churn que `restore_for_account` devolve.

Revisão final da revogação na desativação (I1, medido): depois da T2,
`restore_for_account` não devolve a linha de churn de gestor desativado (remarca
`manager_deactivated`), mas `voltaram_ao_mcc` (Google) e `saiu_da_parceria`
(Meta) contavam toda linha de churn da conta. A fila exibia 2 e o botão
devolvia 1 — a invariante I5 ("a contagem exibida é exatamente o que o botão
devolve") regrediu nos dois gêmeos.

As filas filtram pelo gestor com `PREDICADO_NAO_DESATIVADO`, mas não pela
constante: os guards existentes das filas
(`test_list_queues_google_predicado_is_active.py`,
`test_fila_saiu_da_parceria_alcanca_a_volta.py`) leem o SQL como LITERAL e
proíbem `is_active = false` no texto. A fila carrega então uma CÓPIA literal da
constante, e este guard é o que amarra a cópia à fonte: mudar a constante sem a
cópia (ou apagar o filtro de uma fila) fica vermelho aqui. O comportamento (fila
igual ao retorno do botão) é testado no banco em
`tests/integration/test_revogacao_na_desativacao.py::test_fila_conta_so_o_que_o_botao_devolve`.

As duas filas de delegação entram também: a conta cujo único churn é de gestor
desativado sai da fila de restauração, e a exclusão de `sem_delegacao` tem de
usar o MESMO critério — senão a conta some das duas filas.
"""

import ast
import re
from pathlib import Path

import pytest

from src.db.repositories._acesso_comum import PREDICADO_DESATIVADO, PREDICADO_NAO_DESATIVADO
from tests.unit._guard_harness import achar_funcao

_REPOS = Path(__file__).resolve().parents[2] / "src" / "db" / "repositories"

# (arquivo, variável que recebe a query em `list_queues`)
_FILAS = (
    ("google_ads_accounts.py", "voltaram"),
    ("google_ads_accounts.py", "sem_delegacao"),
    ("meta_ad_accounts.py", "saiu"),
    ("meta_ad_accounts.py", "sem_delegacao"),
)


def _sql_atribuido_a(arquivo: str, alvo: str) -> str:
    funcao = achar_funcao(ast.parse((_REPOS / arquivo).read_text(encoding="utf-8")), "list_queues")
    for node in ast.walk(funcao):
        if not isinstance(node, ast.Assign):
            continue
        if alvo not in [t.id for t in node.targets if isinstance(t, ast.Name)]:
            continue
        valor = node.value.value if isinstance(node.value, ast.Await) else node.value
        assert isinstance(valor, ast.Call)
        primeiro = valor.args[0]
        assert isinstance(primeiro, ast.Constant) and isinstance(primeiro.value, str)
        # Sem comentário SQL `--`: o predicado comentado não conta.
        return "\n".join(re.sub(r"--.*$", "", linha) for linha in primeiro.value.splitlines())
    raise AssertionError(f"nenhuma query atribuída a `{alvo}` em {arquivo}::list_queues")


@pytest.mark.parametrize(("arquivo", "alvo"), _FILAS)
def test_fila_filtra_gestor_desativado_com_a_copia_da_constante(arquivo: str, alvo: str) -> None:
    sql = _sql_atribuido_a(arquivo, alvo)
    assert re.search(r"\bAND\s+" + re.escape(PREDICADO_NAO_DESATIVADO), sql), (
        f"{arquivo}::{alvo} deixou de filtrar o gestor desativado com a cópia literal de "
        f"PREDICADO_NAO_DESATIVADO ({PREDICADO_NAO_DESATIVADO}) — a fila volta a contar "
        "churn que o Restaurar não devolve"
    )
    assert re.search(r"\bJOIN\s+managers\s+m\s+ON\s+m\.id\s*=\s*\w+\.manager_id\b", sql), (
        f"{arquivo}::{alvo}: o predicado lê o alias `m` de `managers`, que tem de vir do JOIN"
    )


def test_constante_e_a_negacao_escrita_sem_is_active_igual() -> None:
    """Os guards das filas proíbem `is_active = false` no literal (e o de
    `sem_delegacao` do Google lê `is_active = true` como o predicado da CONTA):
    a forma da constante não pode reintroduzir nenhum dos dois."""
    assert not re.search(r"is_active\s*=", PREDICADO_NAO_DESATIVADO)
    # Mesmas colunas da regra de origem (o valor da negação é provado no banco).
    assert {"m.is_active", "m.status"} <= set(re.findall(r"m\.\w+", PREDICADO_DESATIVADO))
    assert set(re.findall(r"m\.\w+", PREDICADO_NAO_DESATIVADO)) == set(
        re.findall(r"m\.\w+", PREDICADO_DESATIVADO)
    )
