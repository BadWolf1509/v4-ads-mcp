"""Guard DERIVADO: o gate Google nao pode voltar a ler so a tabela de grants.

Espelha `tests/unit/test_gate_meta_exige_conta_ativa.py` — mesma logica de
deteccao (AST, ignorando docstring e comentario `--`), aplicada a
`can_manager_access` de `manager_account_access.py` / `google_ads_accounts`.
`_achar_funcao`, `_sql_sem_docstring`, `_sem_comentario_sql` e
`_tem_join_puro_para` sao copia literal das do gemeo Meta: a logica de deteccao
nao muda entre os dois lados, só o arquivo/tabela alvo. Ver aquele arquivo pro
histórico das duas rodadas de fix que a chegaram nesta forma — aqui ela já
nasce corrigida.

Fecha o F130: o gate do Google não cruzava com `is_active` nem com
`revoked_at`, o mesmo buraco que o do Meta tinha acabado de perder (F128/F129).
Sem este guard, alguém "simplifica" o JOIN de volta pra só a tabela de grants
e o gate volta a liberar ex-cliente (ou grant revogado) sem nenhum teste
vermelho — só o gêmeo Meta ficaria protegido, e o Google reincidiria calado.
"""

import ast
import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2] / "src" / "db" / "repositories"
_ARQUIVO = _REPO / "manager_account_access.py"


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

    Bigrama exato (`LEFT JOIN`, `RIGHT JOIN`, `FULL JOIN`) não basta — `LEFT
    OUTER JOIN` e primos passariam por baixo, porque a palavra logo antes de
    "JOIN" ali é "OUTER". A forma certa é afirmativa: só um JOIN puro
    (implicitamente INNER, com ou sem a palavra escrita) garante que a
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


def test_can_manager_access_google_consulta_estado_da_conta() -> None:
    fonte = _ARQUIVO.read_text(encoding="utf-8")
    arvore = ast.parse(fonte)
    funcao = _achar_funcao(arvore, "can_manager_access")
    sql = _sem_comentario_sql(_sql_sem_docstring(funcao))

    assert "google_ads_accounts" in sql, "o gate precisa cruzar com o inventario"
    assert "is_active" in sql, "conta fora do MCC tem que ser negada aqui tambem"
    assert "revoked_at IS NULL" in sql, "grant revogado nao pode dar acesso"
    assert _tem_join_puro_para(sql, "google_ads_accounts"), (
        "so JOIN puro (sem LEFT/RIGHT/FULL/OUTER logo antes) garante que a "
        "condicao do ON exclui a linha de verdade — qualquer sabor de outer "
        "join preserva o lado esquerdo com colunas NULL da direita, deixando "
        "conta inativa (ou revogada) passar mesmo com o predicado escrito"
    )
