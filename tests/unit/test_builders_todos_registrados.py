"""F150 — a lista de imports do `import_all_builders` divergiu do pacote.

`update_ad_schedule` foi para producao com o `@register_builder` correto no
modulo, mas o modulo nunca era importado: a funcao tinha uma lista escrita A MAO
com 11 entradas, e `mutates/ad_schedule.py` nao estava nela. O decorator nunca
rodava, a chave nunca entrava no `_BUILDERS`, e `apply_change` respondia
"No mutate builder registered for 'update_ad_schedule'".

Efeito em producao: a tool PREVIA e nao APLICAVA. Todo o caminho de leitura e de
dry-run passava; so o apply quebrava, e o gestor via "Erro interno ao executar a
ferramenta" sem diagnostico possivel do lado dele.
"""

import ast
import pathlib

from src.google_ads.mutates._common import _BUILDERS, import_all_builders

_MUTATES = pathlib.Path(__file__).resolve().parents[2] / "src" / "google_ads" / "mutates"


def _chaves_declaradas() -> dict[str, str]:
    """Le o pacote e devolve {chave: arquivo} de todo @register_builder("x").

    Le do FONTE, nao do registry: a pergunta e justamente se o que o codigo
    declara chega no registry. Comparar o registry consigo mesmo nao provaria nada.
    """
    declaradas: dict[str, str] = {}
    for p in sorted(_MUTATES.glob("*.py")):
        arvore = ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
        for no in ast.walk(arvore):
            if not isinstance(no, ast.Call):
                continue
            alvo = no.func
            nome = alvo.attr if isinstance(alvo, ast.Attribute) else getattr(alvo, "id", None)
            if nome != "register_builder" or not no.args:
                continue
            arg = no.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                declaradas[arg.value] = p.name
    return declaradas


def test_todo_register_builder_do_pacote_chega_no_registry() -> None:
    """Propriedade, nao lista: builder novo nasce coberto sem ninguem inscrever.

    Este guard existe porque a alternativa — manter uma lista de imports a mao —
    ja divergiu em producao. Uma lista paralela mantida por memoria humana e o
    proprio defeito, entao o guard tem que ler o PACOTE.
    """
    import_all_builders()
    declaradas = _chaves_declaradas()
    assert declaradas, "nenhum @register_builder encontrado — o parser quebrou, nao o codigo"

    faltando = {c: arq for c, arq in declaradas.items() if c not in _BUILDERS}
    assert not faltando, (
        "builders declarados no pacote que NAO chegaram ao registry (o modulo nao e "
        "importado por import_all_builders): "
        + "; ".join(f"{c} ({arq})" for c, arq in sorted(faltando.items()))
    )


def test_update_ad_schedule_tem_builder() -> None:
    """O caso concreto que foi para producao quebrado, fixado como regressao."""
    import_all_builders()
    assert "update_ad_schedule" in _BUILDERS, (
        "sem esta chave o apply_change do ad_schedule devolve 'No mutate builder "
        "registered' e a tool preve sem conseguir aplicar"
    )
