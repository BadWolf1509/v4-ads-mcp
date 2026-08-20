"""Guard DERIVADO: a fila 3 nao pode voltar a key-ar em `is_active`.

C1 da revisao de branch. `upsert_many` poe `is_active = true` assim que a
parceria volta — e voltar e o UNICO momento em que restaurar faz sentido, porque
o gate (`can_manager_access`) exige conta ativa. Com `WHERE a.is_active = false`,
a conta saia da fila no mesmo instante em que se tornava restauravel, levando
junto o unico chamador de `restore_for_account` em todo o `src/`. O que resta ao
admin e redelegar tudo a mao, que e o trabalho manual que a revogacao soft existe
para eliminar.

O guard varre o SQL, nao os arquivos: o teste de comportamento vive no banco
(`tests/integration/test_meta_reconcile_repo.py`), mas ele precisa de Docker.
Este aqui roda em qualquer maquina e falha vermelho se alguem "simplificar" a
query de volta pro predicado antigo.

Mesma familia do `test_gate_meta_exige_conta_ativa.py`, e com as mesmas duas
protecoes que aquele guard precisou aprender: docstring fora da fatia (F87 ->
F116) e comentario SQL `--` removido de dentro do literal (o `ast` so descarta
`#`, que e gramatica Python; `--` e so caractere dentro da string).
"""

import ast
import re
from pathlib import Path

_ARQUIVO = (
    Path(__file__).resolve().parents[2] / "src" / "db" / "repositories" / "meta_ad_accounts.py"
)


def _achar_funcao(arvore: ast.Module, nome: str) -> ast.AsyncFunctionDef:
    for node in ast.walk(arvore):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == nome:
            return node
    raise AssertionError(f"{nome} sumiu ou mudou de nome")


def _chamada_atribuida_a(funcao: ast.AsyncFunctionDef, alvo: str) -> ast.Call:
    """A `ast.Call` do `await conn.fetch(...)` atribuido a `alvo`.

    Derivar do ALVO (e nao contar a n-esima query do corpo) e o que faz o guard
    continuar valendo quando alguem reordenar ou acrescentar uma fila.
    """
    for node in ast.walk(funcao):
        if not isinstance(node, ast.Assign):
            continue
        nomes = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if alvo not in nomes:
            continue
        valor = node.value
        if isinstance(valor, ast.Await):
            valor = valor.value
        if isinstance(valor, ast.Call):
            return valor
    raise AssertionError(f"nenhuma query atribuida a `{alvo}` em list_queues")


def _sql(chamada: ast.Call) -> str:
    """Primeiro argumento posicional, sem comentario SQL `--`."""
    primeiro = chamada.args[0]
    assert isinstance(primeiro, ast.Constant) and isinstance(primeiro.value, str), (
        "a query deixou de ser um literal — o guard nao consegue mais ler o SQL"
    )
    return "\n".join(re.sub(r"--.*$", "", linha) for linha in primeiro.value.splitlines())


def _tem_join_puro_para(sql: str, tabela: str) -> bool:
    """True se existir `JOIN <tabela>` sem LEFT/RIGHT/FULL/OUTER logo antes.

    Qualquer sabor de outer join preserva a linha da esquerda com colunas NULL
    da direita — a fila listaria conta sem NENHUM grant revogado por churn, com
    contagem 0 e um botao que nao tem o que restaurar.
    """
    for m in re.finditer(r"\bJOIN\s+" + re.escape(tabela) + r"\b", sql, re.IGNORECASE):
        palavra_antes = re.findall(r"\w+", sql[: m.start()])[-1:]
        if palavra_antes and palavra_antes[0].upper() in ("LEFT", "RIGHT", "FULL", "OUTER"):
            continue
        return True
    return False


def _fila_saiu() -> tuple[ast.Call, str]:
    arvore = ast.parse(_ARQUIVO.read_text(encoding="utf-8"))
    chamada = _chamada_atribuida_a(_achar_funcao(arvore, "list_queues"), "saiu")
    return chamada, _sql(chamada)


def test_fila_saiu_nao_key_a_em_conta_inativa() -> None:
    """C1: a conta que VOLTOU (is_active = true) tem de continuar na fila."""
    _, sql = _fila_saiu()

    assert not re.search(r"is_active\s*=\s*false", sql, re.IGNORECASE), (
        "a fila voltou a exigir conta inativa — a conta some da fila no mesmo "
        "instante em que a parceria volta e o Restaurar passa a fazer sentido, "
        "e com ela some o unico chamador de restore_for_account no src/"
    )


def test_fila_saiu_mostra_primeiro_quem_voltou() -> None:
    """A conta que voltou e a unica acionavel — nao pode ficar sob o historico."""
    _, sql = _fila_saiu()

    assert re.search(r"ORDER\s+BY\s+a\.is_active\s+DESC", sql, re.IGNORECASE), (
        "sem `ORDER BY a.is_active DESC` a conta restauravel afunda no meio do "
        "historico de quem saiu e nao voltou"
    )


def test_contagem_exibida_e_exatamente_o_que_o_restore_devolve() -> None:
    """I5: o denominador exibido tem de ser o mesmo conjunto que o botao mexe.

    `restore_for_account` reconcede SO o que foi revogado por churn. Contar
    revogacao de qualquer razao (manual, bulk_copy_replaced) faz o painel
    prometer 5 e o botao devolver 3.
    """
    chamada, sql = _fila_saiu()

    assert "revoked_reason" in sql, (
        "a fila conta revogacao de qualquer razao — inclui acesso que o admin "
        "tirou de proposito, que o Restaurar (corretamente) nao devolve"
    )
    nomes = [a.id for a in chamada.args[1:] if isinstance(a, ast.Name)]
    assert "PARTNERSHIP_ENDED_REASON" in nomes, (
        "a razao tem de vir da constante compartilhada com restore_for_account "
        "— string solta aqui e a forma de os dois lados divergirem em silencio"
    )
    assert _tem_join_puro_para(sql, "manager_meta_account_access"), (
        "so JOIN puro garante que a conta sem grant revogado por churn fique "
        "FORA da fila; outer join a traria com contagem 0 e botao inerte"
    )
