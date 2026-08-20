"""Guard DERIVADO: o gate nao pode voltar a ler so a tabela de grants.

Sem isto alguem 'simplifica' o JOIN e o gate volta a liberar ex-cliente sem
nenhum teste vermelho — foi assim que o F86 renasceu como F109.

Fix round 1 (revisao independente achou dois furos no regex original):

1. A fatia `re.search(...)` incluia a docstring inteira, entao um comentario
   OU a propria docstring mencionando os tokens exigidos bastava pra passar,
   independente do SQL de verdade — o padrao F87 -> F116, ja repetido 5x
   nesta base. Fix: extrai só os literais de string do CORPO da função via
   AST, pulando a docstring explicitamente; comentário `#` o `ast` já
   descarta sozinho, nunca chega a virar valor de nenhum node.
2. Era checagem por SUBSTRING pura contra uma lista negra de bigramas
   (`LEFT JOIN`, `RIGHT JOIN`, `FULL JOIN`).

Fix round 2 (segunda revisao EXECUTOU o guard contra variantes em vez de so
ler — achou dois furos novos na propria correcao do round 1):

1. A lista negra so batia o bigrama EXATO. `LEFT OUTER JOIN`, `RIGHT OUTER
   JOIN` etc. passavam inteiros por baixo dela (a palavra logo antes de
   "JOIN" era "OUTER", que nao estava na lista). Fix: parar de enumerar
   grafias e checar a FORMA — "JOIN meta_ad_accounts" com a palavra
   IMEDIATAMENTE anterior fora de {LEFT, RIGHT, FULL, OUTER}. Cobre todo
   sabor de outer join (a palavra logo antes de "JOIN" e sempre uma dessas
   quatro: "LEFT JOIN" -> LEFT, "LEFT OUTER JOIN" -> OUTER, "RIGHT JOIN" ->
   RIGHT, "RIGHT OUTER JOIN" -> OUTER, "FULL JOIN" -> FULL, "FULL OUTER
   JOIN" -> OUTER).
2. `--` dentro de um literal Python e SQL de verdade (roda no banco), mas pro
   Python e só caractere de string comum — o `ast` não desmonta isso (só
   `#`, que é gramática Python). Um `-- revoked_at IS NULL / is_active`
   dentro da query, com os predicados de verdade apagados, ainda batia a
   substring. Fix: remove `-- até fim de linha` de dentro de cada literal
   antes de procurar os predicados — mesma logica do `#`, aplicada ao
   comentario que o `ast` NAO enxerga.
"""

import ast
import re
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


def _sem_comentario_sql(sql: str) -> str:
    """Remove `-- até fim de linha` de dentro do literal.

    É comentário SQL de verdade (roda no banco), mas pro Python é só
    caractere dentro de uma string comum — o `ast` nunca tira isso (só tira
    `#`, que é gramática Python, não `--`, que é gramática SQL escondida
    dentro do valor da string). Sem isto, mencionar os tokens exigidos dentro
    de um `--` bastaria pra passar mesmo com o predicado de verdade apagado.
    """
    return "\n".join(re.sub(r"--.*$", "", linha) for linha in sql.splitlines())


def _tem_join_puro_para(sql: str, tabela: str) -> bool:
    """True se existir `JOIN <tabela>` sem LEFT/RIGHT/FULL/OUTER logo antes.

    Round 1 proibia bigramas exatos (`LEFT JOIN`, `RIGHT JOIN`, `FULL JOIN`)
    — `LEFT OUTER JOIN` e primos passavam, porque a palavra logo antes de
    "JOIN" ali é "OUTER", não "LEFT". A forma certa é afirmativa: só um JOIN
    puro (implicitamente INNER, com ou sem a palavra escrita) garante que a
    condição do ON vira filtro de verdade — QUALQUER sabor de outer join
    preserva a linha do lado esquerdo com colunas NULL da direita quando o ON
    falha, em vez de excluir a linha.
    """
    for m in re.finditer(r"\bJOIN\s+" + re.escape(tabela) + r"\b", sql, re.IGNORECASE):
        palavra_antes = re.findall(r"\w+", sql[: m.start()])[-1:]
        if palavra_antes and palavra_antes[0].upper() in ("LEFT", "RIGHT", "FULL", "OUTER"):
            continue
        return True
    return False


def test_can_manager_access_meta_consulta_estado_da_conta() -> None:
    fonte = _ARQUIVO.read_text(encoding="utf-8")
    arvore = ast.parse(fonte)
    funcao = _achar_funcao(arvore, "can_manager_access")
    sql = _sem_comentario_sql(_sql_sem_docstring(funcao))

    assert "meta_ad_accounts" in sql, "o gate precisa cruzar com o inventario"
    assert "is_active" in sql, "conta fora da parceria tem que ser negada aqui tambem"
    assert "revoked_at IS NULL" in sql, "grant revogado nao pode dar acesso"
    assert _tem_join_puro_para(sql, "meta_ad_accounts"), (
        "so JOIN puro (sem LEFT/RIGHT/FULL/OUTER logo antes) garante que a "
        "condicao do ON exclui a linha de verdade — qualquer sabor de outer "
        "join preserva o lado esquerdo com colunas NULL da direita, deixando "
        "conta inativa (ou revogada) passar mesmo com o predicado escrito"
    )
