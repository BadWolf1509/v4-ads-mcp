"""Guard DERIVADO: o gate Google nao pode voltar a ler so a tabela de grants.

Espelha `tests/unit/test_gate_meta_exige_conta_ativa.py` — mesma logica de
deteccao (AST, ignorando docstring e comentario `--`), aplicada a
`can_manager_access` de `manager_account_access.py` / `google_ads_accounts`.
`achar_funcao`, `sql_sem_docstring`, `tem_join_puro_para`,
`tem_predicado_bem_formado` e `e_conjuncao_pura` vem de `_guard_harness` e sao
os mesmos do gemeo Meta (`_sem_comentario_sql` segue copia local): a logica de
deteccao nao muda entre os dois lados, só o arquivo/tabela alvo. Ver aquele arquivo pro histórico completo
(quatro rodadas de fix, a última fechando uma sabotagem por `OR TRUE` solto
que as três primeiras deixavam passar) que chegou nesta forma — aqui ela já
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

from tests.unit._guard_harness import (
    achar_funcao,
    e_conjuncao_pura,
    sql_sem_docstring,
    tem_join_puro_para,
    tem_predicado_bem_formado,
)

_REPO = Path(__file__).resolve().parents[2] / "src" / "db" / "repositories"
_ARQUIVO = _REPO / "manager_account_access.py"


def _sem_comentario_sql(sql: str) -> str:
    """Remove `-- até fim de linha` de dentro do literal.

    É comentário SQL de verdade (roda no banco), mas pro Python é só
    caractere dentro de uma string comum — o `ast` nunca tira isso (só tira
    `#`, que é gramática Python, não `--`, que é gramática SQL escondida
    dentro do valor da string). Sem isto, mencionar os tokens exigidos dentro
    de um `--` bastaria pra passar mesmo com o predicado de verdade apagado.
    """
    return "\n".join(re.sub(r"--.*$", "", linha) for linha in sql.splitlines())


def test_can_manager_access_google_consulta_estado_da_conta() -> None:
    fonte = _ARQUIVO.read_text(encoding="utf-8")
    arvore = ast.parse(fonte)
    funcao = achar_funcao(arvore, "can_manager_access")
    sql = _sem_comentario_sql(sql_sem_docstring(funcao))

    assert "google_ads_accounts" in sql, "o gate precisa cruzar com o inventario"
    assert tem_predicado_bem_formado(sql, "is_active", r"=\s*true"), (
        "conta fora do MCC tem que ser negada aqui tambem — como AND de topo "
        "colado na coluna, nao so a substring solta (que sobrevive intacta a "
        "`is_active = false`, a `OR is_active = true`, e a `is_active = true "
        "OR TRUE`)"
    )
    assert tem_predicado_bem_formado(sql, "revoked_at", r"IS\s*NULL"), (
        "grant revogado nao pode dar acesso — mesma forma estrita"
    )
    assert tem_join_puro_para(sql, "google_ads_accounts"), (
        "so JOIN puro (sem LEFT/RIGHT/FULL/OUTER logo antes) garante que a "
        "condicao do ON exclui a linha de verdade — qualquer sabor de outer "
        "join preserva o lado esquerdo com colunas NULL da direita, deixando "
        "conta inativa (ou revogada) passar mesmo com o predicado escrito"
    )
    assert e_conjuncao_pura(sql), (
        "um OR fora de parenteses no fim do WHERE reescreve o predicado "
        "inteiro pra `(...) OR <resto>` (AND liga mais forte que OR) — "
        "`AND revoked_at IS NULL OR TRUE` sobrevive intacta a "
        "`tem_predicado_bem_formado`, que so olha o que vem ANTES do "
        "match, nunca o que vem depois"
    )
