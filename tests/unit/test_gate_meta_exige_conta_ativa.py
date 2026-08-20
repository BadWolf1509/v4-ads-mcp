"""Guard DERIVADO: o gate nao pode voltar a ler so a tabela de grants.

Sem isto alguem 'simplifica' o JOIN e o gate volta a liberar ex-cliente sem
nenhum teste vermelho — foi assim que o F86 renasceu como F109.

Fix round 1 (revisao independente achou dois furos no regex original):

1. A fatia `re.search(...)` incluia a docstring inteira, entao um comentario
   OU a propria docstring mencionando os tokens exigidos bastava pra passar,
   independente do SQL de verdade — o padrao F87 -> F116, ja repetido 5x
   nesta base. Agora extrai só os literais de string do CORPO da função via
   AST, pulando a docstring explicitamente; comentário `#` o `ast` já
   descarta sozinho, nunca chega a virar valor de nenhum node.
2. Era checagem por SUBSTRING pura, entao `LEFT JOIN meta_ad_accounts a ON
   a.ad_account_id = m.ad_account_id AND a.is_active = true` mantém toda
   substring exigida (`meta_ad_accounts`, `is_active`, `revoked_at IS NULL`)
   e MESMO ASSIM devolve uma linha pra conta INATIVA: LEFT JOIN preserva o
   lado esquerdo com colunas da direita NULL quando a condição do ON falha,
   em vez de excluir a linha — exatamente a regressão que este guard existe
   pra travar. Por isso agora proíbe JOIN externo (LEFT/RIGHT/FULL)
   explicitamente; só JOIN puro (INNER, implícito ou explícito) garante que
   a condição vira filtro de verdade.
"""

import ast
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2] / "src" / "db" / "repositories"
_ARQUIVO = _REPO / "manager_meta_account_access.py"


def _achar_funcao(arvore: ast.Module, nome: str) -> ast.AsyncFunctionDef:
    for node in ast.walk(arvore):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == nome:
            return node
    raise AssertionError(f"{nome} sumiu ou mudou de nome")


def _sql_sem_docstring(funcao: ast.AsyncFunctionDef) -> str:
    """Concatena os literais de string do corpo da função, IGNORANDO a
    docstring — comentário `#` nunca aparece aqui pra começo de conversa (o
    `ast` descarta na tokenização, não é gramática), então só a docstring
    precisa de exclusão explícita: é o único literal de string que pode ficar
    solto como `Expr` isolado no topo do corpo.
    """
    corpo = funcao.body
    docstring_node = None
    if (
        corpo
        and isinstance(corpo[0], ast.Expr)
        and isinstance(corpo[0].value, ast.Constant)
        and isinstance(corpo[0].value.value, str)
    ):
        docstring_node = corpo[0].value

    literais = [
        node.value
        for node in ast.walk(funcao)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node is not docstring_node
    ]
    return "\n".join(literais)


def test_can_manager_access_meta_consulta_estado_da_conta() -> None:
    fonte = _ARQUIVO.read_text(encoding="utf-8")
    arvore = ast.parse(fonte)
    funcao = _achar_funcao(arvore, "can_manager_access")
    sql = _sql_sem_docstring(funcao)

    assert "meta_ad_accounts" in sql, "o gate precisa cruzar com o inventario"
    assert "is_active" in sql, "conta fora da parceria tem que ser negada aqui tambem"
    assert "revoked_at IS NULL" in sql, "grant revogado nao pode dar acesso"

    sql_upper = sql.upper()
    assert not any(kw in sql_upper for kw in ("LEFT JOIN", "RIGHT JOIN", "FULL JOIN")), (
        "JOIN externo (LEFT/RIGHT/FULL) preserva a linha de "
        "manager_meta_account_access mesmo quando a condicao de is_active falha "
        "na clausula ON — devolve colunas NULL da tabela da direita em vez de "
        "excluir a linha, entao conta inativa continua liberando acesso. So JOIN "
        "puro (INNER) garante que is_active vira filtro de verdade."
    )
