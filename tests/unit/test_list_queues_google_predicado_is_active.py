"""Guard DERIVADO: as duas filas de `list_queues` (google_ads_accounts) não
podem trocar a polaridade de `is_active`.

I-2 da revisão final de `feat/gate-google-reconcile` (2026-09-05): o predicado
`a.is_active = true` de `sem_delegacao` não tinha NENHUM teste. Sabotando-o
para `(a.is_active = true OR a.is_active = false)`, os arquivos INTEIROS
`tests/integration/test_repositories.py` e
`tests/integration/test_web_panel_admin.py` continuavam verdes, e duas contas
INATIVAS entravam na fila. Essa fila alimenta `avisar_contas_sem_grant` — o
sinal do alerta —, então sem o predicado toda conta fora do MCC sem grant
vivo dispararia o e-mail todo dia, convidando o admin a delegar numa conta que
o próprio gate (`can_manager_access`) nega.

O teste de comportamento (contas reais, banco real) vive em
`tests/integration/test_repositories.py`
(`test_fila_delegacao_ignora_conta_inativa`), mas exige Docker. Este aqui roda
em qualquer máquina e falha vermelho se alguém enfraquecer a query.

`_achar_funcao`, `_chamada_atribuida_a` e `_sql` são cópia literal de
`tests/unit/test_fila_saiu_da_parceria_alcanca_a_volta.py` (gêmeo Meta), que já
resolve o problema de isolar UMA query dentro de uma função com mais de uma
(`list_queues` do Google tem duas: `sem_delegacao` e `voltaram`) — derivar do
ALVO (a variável), não da n-ésima query do corpo, é o que faz o guard não
confundir as duas nem quebrar quando alguém reordenar.

`_tem_predicado_bem_formado` e `_e_conjuncao_pura` são cópia (quase) literal de
`tests/unit/test_gate_google_exige_conta_ativa.py` — aquele arquivo documenta
quatro rodadas até chegar numa forma que resiste a `OR`: substring solta
("is_active" ou até a frase inteira "is_active = true") sobrevive intacta a
`(is_active = true OR is_active = false)` — a sabotagem MEDIDA neste I-2— a
`OR is_active = true`, e a `is_active = true OR TRUE`. A única mudança real é
o token âncora: lá o predicado vem depois de outro `AND` (não é o primeiro da
cláusula); aqui, em `sem_delegacao`, `a.is_active = true` é o PRIMEIRO
predicado logo após `WHERE` — mesma exigência de adjacência (nada, nem
parêntese, entre a palavra-chave e a coluna), só que a palavra-chave pode ser
`WHERE` ou `AND`.
"""

import ast
import re
from pathlib import Path

_ARQUIVO = (
    Path(__file__).resolve().parents[2] / "src" / "db" / "repositories" / "google_ads_accounts.py"
)


def _achar_funcao(arvore: ast.Module, nome: str) -> ast.AsyncFunctionDef:
    for node in ast.walk(arvore):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == nome:
            return node
    raise AssertionError(f"{nome} sumiu ou mudou de nome")


def _chamada_atribuida_a(funcao: ast.AsyncFunctionDef, alvo: str) -> ast.Call:
    """A `ast.Call` do `await conn.fetch(...)` atribuído a `alvo`.

    Derivar do ALVO (e não contar a n-ésima query do corpo) é o que faz o
    guard continuar valendo quando alguém reordenar ou acrescentar uma fila —
    `list_queues` tem duas queries no mesmo corpo, e cada assert abaixo precisa
    da SQL de uma delas, nunca das duas misturadas.
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
    raise AssertionError(f"nenhuma query atribuída a `{alvo}` em list_queues")


def _sql(chamada: ast.Call) -> str:
    """Primeiro argumento posicional, sem comentário SQL `--`."""
    primeiro = chamada.args[0]
    assert isinstance(primeiro, ast.Constant) and isinstance(primeiro.value, str), (
        "a query deixou de ser um literal — o guard não consegue mais ler o SQL"
    )
    return "\n".join(re.sub(r"--.*$", "", linha) for linha in primeiro.value.splitlines())


def _tem_predicado_bem_formado(sql: str, coluna: str, comparacao: str) -> bool:
    r"""True se existir `(WHERE|AND) [alias.]<coluna><comparacao>` como
    conjunto de topo, sem NADA (parênteses incluso) entre a palavra-chave e a
    coluna.

    Mesma lógica de `test_gate_google_exige_conta_ativa.py` (quatro rodadas
    até chegar nesta forma — ver aquele arquivo pra história completa), só que
    aqui a palavra-chave aceita `WHERE` além de `AND`: em `sem_delegacao`,
    `a.is_active = true` é o PRIMEIRO predicado da cláusula, não um que vem
    depois de outro `AND`. Sem aceitar `WHERE` aqui, o guard nunca bateria nem
    contra o código BOM — o que não é guard nenhum, é teste sempre-vermelho.
    """
    padrao = r"\b(?:WHERE|AND)\s+(?:\w+\.)?" + re.escape(coluna) + r"\s*" + comparacao + r"\b"
    return re.search(padrao, sql, re.IGNORECASE) is not None


def _e_conjuncao_pura(sql: str) -> bool:
    r"""True se o SQL NÃO tiver nenhum `OR` fora de parênteses (top-level).

    Cópia literal de `test_gate_google_exige_conta_ativa.py`: sem isto, `AND x
    OR TRUE` (ou o `OR a.is_active = false` sem parênteses) sobrevive a
    `_tem_predicado_bem_formado` — que só olha o que vem ANTES do match — e
    neutraliza o WHERE inteiro, porque `AND` liga mais forte que `OR`.
    """
    profundidade = 0
    for m in re.finditer(r"[()]|\bOR\b", sql, re.IGNORECASE):
        token = m.group()
        if token == "(":
            profundidade += 1
        elif token == ")":
            profundidade -= 1
        elif profundidade == 0:
            return False
    return True


def _sql_da_fila(nome_variavel: str) -> str:
    arvore = ast.parse(_ARQUIVO.read_text(encoding="utf-8"))
    funcao = _achar_funcao(arvore, "list_queues")
    chamada = _chamada_atribuida_a(funcao, nome_variavel)
    return _sql(chamada)


def test_sem_delegacao_exige_conta_ativa() -> None:
    """I-2: sem isto, conta fora do MCC sem grant vivo dispara o alerta todo
    dia e convida o admin a delegar numa conta que o gate nega.

    As duas asserções são necessárias: `_tem_predicado_bem_formado` sozinha
    passaria (errado) com `WHERE a.is_active = true OR a.is_active = false
    AND NOT EXISTS(...)` — sem parênteses, "WHERE a.is_active = true" casa
    intacto, e só `_e_conjuncao_pura` pega o `OR` solto que neutraliza a
    cláusula inteira (AND liga mais forte que OR).
    """
    sql = _sql_da_fila("sem_delegacao")

    assert _tem_predicado_bem_formado(sql, "is_active", r"=\s*true"), (
        "a fila de delegação parou de exigir conta ativa — como conjunto de "
        "topo colado na palavra-chave (WHERE/AND), não só a substring solta "
        "(que sobrevive intacta a `(is_active = true OR is_active = false)`, "
        "a sabotagem medida no I-2)"
    )
    assert _e_conjuncao_pura(sql), (
        "um OR fora de parênteses neutraliza o WHERE inteiro (`is_active = "
        "true OR is_active = false`, sem parênteses, ou `AND ... OR TRUE`) "
        "mesmo com a substring `is_active = true` intacta"
    )


def test_voltaram_ao_mcc_nao_key_a_em_conta_inativa() -> None:
    """C1 (gêmeo Meta, mesma lição): a conta que VOLTOU (is_active = true) tem
    de continuar na fila — o predicado antigo `is_active = false` a tirava no
    exato instante em que se tornava restaurável, levando junto o único
    chamador de `restore_for_account` em todo o `src/`.
    """
    sql = _sql_da_fila("voltaram")

    assert not re.search(r"is_active\s*=\s*false", sql, re.IGNORECASE), (
        "a fila voltou a exigir conta inativa — a conta some da fila no "
        "mesmo instante em que a parceria volta e o Restaurar passa a fazer "
        "sentido"
    )
