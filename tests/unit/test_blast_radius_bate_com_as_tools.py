"""A politica de blast radius tem que bater com o caminho que cada tool toma.

`blast_radius.classify` se descreve como quem "decide auto-apply vs
require-confirmation". Na pratica so parte das tools de mutacao LE o `.level`
que ele devolve; as outras computam o veredito e usam apenas `.reason` como
texto, com o caminho (auto-aplicar ou emitir token) fixo no codigo. Medido em
2026-09-07: **28 tools chamam `classify`, 10 leem `.level`, 18 tem caminho
fixo** (o CLAUDE.md e o findings-catalog diziam "17 das 26" — contagem de duas
tools atras).

Nao ha divergencia hoje — este teste existe pra que continue assim. Apertar a
politica no modulo (por exemplo passar `remove_negative_keywords` a CONFIRM,
defensavel ja que remover negativa ALARGA o targeting) nao mudaria nada nas 18,
e o desalinhamento seria silencioso: a tool seguiria auto-aplicando enquanto o
modulo diria o contrario.

Reescrever as 18 pra consultarem `.level` seria a outra saida. Nao vale o
tamanho: o risco nao e a tool errar, e a politica e a tool DIVERGIREM — e isso
um teste pega. A lista de tools e DERIVADA do source, entao uma tool nova entra
sozinha.

**Tool que RAMIFICA em `.level` sai da cobranca — e essa e a decisao, nao um
descuido.** O guard afirma que `classify(operation, params)` concorda com um
caminho FIXO; quem le o veredito em runtime nao tem caminho fixo com que
divergir, e apertar a politica no modulo muda o comportamento da tool no mesmo
commit. Foi o que aconteceu com o `apply_recommendation` em 07/09 (C2): antes
ele computava e ignorava o `.level`, com o caminho preso em auto-aplicar;
agora ramifica por TIPO de recomendacao, e `classify` recebe o
`recommendation_type`. Forcar essa tool no molde antigo afirmaria a coisa
errada — a parametrizacao varre `target_count`, e sem tipo o veredito e CONFIRM
por seguranca, o que "provaria" um caminho fixo CONFIRM que a tool nao tem.

O que ficou de fora deliberadamente: o guard NAO afirma que a tool que ramifica
ramifica CERTO. Isso e trabalho dos testes de comportamento da propria tool
(`tests/unit/test_apply_recommendation.py`), que exercitam tipo por tipo. Aqui
so se afirma a particao — e que ninguem escapa dela por uma terceira porta.
"""

import ast
from dataclasses import dataclass
from pathlib import Path

import pytest

from src.governance.blast_radius import RiskLevel, classify
from tests.unit import _guard_harness as h

_TOOLS = Path(__file__).resolve().parents[2] / "src" / "mcp" / "tools"

_EXECUTORES = {
    "run_mutation",
    "run_conversion_upload",
    "run_recommendation_action",
    "run_offline_user_data_job",
}

# Varia o bastante pra atravessar todos os limiares do modulo (1, 5, 20).
_CONTAGENS = (0, 1, 5, 20, 100, 500)


def _e_chamada_ao_classify(no: ast.expr, nomes: set[str]) -> bool:
    """True se `no` e uma chamada a `classify` (nome local, alias ou `mod.classify`).

    Desembrulha o walrus antes de olhar: em `(r := classify(...)).level` o dono
    do atributo e o `ast.NamedExpr`, nao o `ast.Call` — sem isso a forma passava
    como "nao le `.level`". Achado pela propria tabela sintetica deste modulo.
    """
    if isinstance(no, ast.NamedExpr):
        no = no.value
    if not isinstance(no, ast.Call):
        return False
    f = no.func
    if isinstance(f, ast.Name):
        return f.id in nomes
    return isinstance(f, ast.Attribute) and f.attr in nomes


def _nomes_ligados_ao_classify(arvore: ast.Module, nomes: set[str]) -> set[str]:
    """Nomes que RECEBEM o resultado de `classify(...)` no modulo.

    Cobre `risk = classify(...)`, `risk: RiskClassification = classify(...)` e o
    walrus. Nao tenta desempacotar tupla nem seguir reatribuicao: quem escrever
    uma forma dessas cai no balde `caminho_ambiguo` e o teste da particao cobra
    explicitamente, em vez de sumir calado.
    """
    ligados: set[str] = set()
    for no in ast.walk(arvore):
        valor: ast.expr
        alvos: list[ast.expr]
        if isinstance(no, ast.Assign):
            valor, alvos = no.value, list(no.targets)
        elif isinstance(no, ast.AnnAssign | ast.NamedExpr):
            if no.value is None:  # `r: RiskClassification` sem valor
                continue
            valor, alvos = no.value, [no.target]
        else:
            continue
        if not _e_chamada_ao_classify(valor, nomes):
            continue
        ligados.update(a.id for a in alvos if isinstance(a, ast.Name))
    return ligados


def _le_level_do_classify(arvore: ast.Module) -> bool:
    """True se a tool le `.level` DO RESULTADO de `classify` — nao de outra coisa.

    Ate 2026-09-07 a pergunta era `any(no.attr == "level" for no in walk)`, que
    casa QUALQUER atributo chamado `level`: um `log.bind(level=...)`, um
    `janela.level`, um kwarg de qualquer biblioteca. Uma tool que computasse
    `classify` e ignorasse o veredito, mas tivesse um `x.level` qualquer no
    corpo, saia da cobranca inteira — e sairia calada, porque a lista de casos e
    derivada e ninguem conta quantos deveriam estar nela. Era o guard eximindo
    justamente quem ele existe pra cobrar.
    """
    nomes = h.nomes_locais(arvore, "classify")
    ligados = _nomes_ligados_ao_classify(arvore, nomes)
    for no in ast.walk(arvore):
        if not (isinstance(no, ast.Attribute) and no.attr == "level"):
            continue
        if isinstance(no.value, ast.Name) and no.value.id in ligados:
            return True
        if _e_chamada_ao_classify(no.value, nomes):  # `classify(...).level` direto
            return True
    return False


def _operacao_classificada(arvore: ast.Module) -> str | None:
    """String literal passada como `operation=` pro classify (None se nao houver).

    Alias-aware pela mesma razao que `_le_level_do_classify`: o casamento
    estreito daqui e o que sustenta a derivacao EXATA — quem entra no universo
    por `h.chama` e nao sai por aqui vira ofensor declarado, nao um `continue`.
    """
    nomes = h.nomes_locais(arvore, "classify")
    for no in ast.walk(arvore):
        if not _e_chamada_ao_classify(no, nomes):
            continue
        for kw in no.keywords:
            if kw.arg == "operation" and isinstance(kw.value, ast.Constant):
                return str(kw.value.value)
    return None


@dataclass(frozen=True, slots=True)
class _Particao:
    """As tools que chamam `classify`, separadas pelo que fazem com o veredito."""

    universo: list[str]
    leem_level: list[str]
    caminho_fixo: list[tuple[str, str, RiskLevel]]
    sem_operacao_literal: list[str]
    caminho_ambiguo: list[str]


def _particionar(raiz: Path | None = None) -> _Particao:
    """Parte as tools em quem le `.level` e quem tem caminho fixo.

    O universo sai de `h.chama(..., "classify")` — casamento LARGO, alias e
    atributo inclusive. A particao sai dos casadores ESTREITOS
    (`_le_level_do_classify`, `_operacao_classificada`). Os dois serem
    diferentes e o que torna a derivacao exata do teste abaixo nao-tautologica:
    arquivo que entra pelo largo e nao sai por nenhum dos estreitos fica num
    balde de ofensor, em vez de evaporar num `continue`.
    """
    universo: list[str] = []
    leem_level: list[str] = []
    caminho_fixo: list[tuple[str, str, RiskLevel]] = []
    sem_operacao_literal: list[str] = []
    caminho_ambiguo: list[str] = []

    for p in h.fontes_py(raiz if raiz is not None else _TOOLS):
        if p.name.startswith("_"):
            continue
        arvore = ast.parse(p.read_text(encoding="utf-8"))
        if not h.chama(arvore, "classify", arv=arvore):
            continue
        universo.append(p.name)

        if _le_level_do_classify(arvore):
            leem_level.append(p.name)  # honra a politica em runtime
            continue

        operacao = _operacao_classificada(arvore)
        if operacao is None:
            sem_operacao_literal.append(p.name)
            continue

        emite_token = h.chama(arvore, "create_pending", arv=arvore)
        aplica_direto = any(h.chama(arvore, e, arv=arvore) for e in _EXECUTORES)
        if emite_token and not aplica_direto:
            caminho_fixo.append((p.name, operacao, RiskLevel.CONFIRM))
        elif aplica_direto and not emite_token:
            caminho_fixo.append((p.name, operacao, RiskLevel.AUTO))
        else:
            caminho_ambiguo.append(
                f"{p.name} (create_pending={emite_token}, executor={aplica_direto})"
            )

    return _Particao(
        universo=universo,
        leem_level=leem_level,
        caminho_fixo=caminho_fixo,
        sem_operacao_literal=sem_operacao_literal,
        caminho_ambiguo=caminho_ambiguo,
    )


_PARTICAO = _particionar()
_CASOS = _PARTICAO.caminho_fixo


def test_particao_das_tools_e_exata() -> None:
    """Toda tool que chama `classify` cai em EXATAMENTE um dos dois lados.

    Ate 2026-09-07 este teste era um piso — `len(_CASOS) >= 15` com um "esperado
    ~17" na mensagem. Piso nao e derivacao: se o casamento estreito perdesse
    tres tools (alias no import, `operation=` vindo de constante, `classify`
    chamado como atributo de modulo), 15 continuava passando e as tres ficavam
    sem cobranca nenhuma. Agora a conta e exata contra um universo derivado por
    OUTRO casador, e as duas saidas do meio sao ofensoras declaradas.
    """
    assert _PARTICAO.universo, (
        "nenhuma tool em src/mcp/tools/ chama `classify` — o casamento quebrou "
        "ou a governanca sumiu. Guard que varre zero tools passa por vacuidade."
    )
    assert _PARTICAO.leem_level, (
        "nenhuma tool le `.level` do resultado do classify. Isso ja foi verdade "
        "em nenhum momento do projeto: se ficou verdade agora, o casador de "
        "`.level` quebrou e as tools que ramificam viraram 'caminho fixo'."
    )
    assert not _PARTICAO.sem_operacao_literal, (
        f"tool que chama `classify` sem `operation=` literal: "
        f"{_PARTICAO.sem_operacao_literal}. Sem o literal nao da pra reexecutar a "
        "politica aqui, e antes dessa checagem a tool sumia da cobranca calada. "
        "Escreva a operacao como string no call-site, ou faca a tool ler `.level`."
    )
    assert not _PARTICAO.caminho_ambiguo, (
        f"tool que nao le `.level` e cujo caminho nao e obvio no source: "
        f"{_PARTICAO.caminho_ambiguo}. Ou faca a tool consultar `risk.level`, ou "
        "deixe um caminho unico (so create_pending, ou so executor)."
    )
    assert len(_CASOS) == len(_PARTICAO.universo) - len(_PARTICAO.leem_level), (
        f"derivacao inexata: {len(_PARTICAO.universo)} tools chamam classify, "
        f"{len(_PARTICAO.leem_level)} leem `.level`, mas so {len(_CASOS)} entraram "
        "na cobranca de caminho fixo. Alguma tool escapou do casamento estreito."
    )


@pytest.mark.parametrize(("arquivo", "operacao", "esperado"), _CASOS)
def test_politica_bate_com_o_caminho_fixo_da_tool(
    arquivo: str, operacao: str, esperado: RiskLevel
) -> None:
    """Pra toda contagem plausivel, a politica concorda com o que a tool faz."""
    for n in _CONTAGENS:
        veredito = classify(operation=operacao, params={"target_count": n})
        assert veredito.level is esperado, (
            f"{arquivo} sempre {esperado.value}, mas classify({operacao!r}, "
            f"target_count={n}) diz {veredito.level.value} — a tool nao le "
            "`.level`, entao essa divergencia seria silenciosa em producao"
        )


# (id, fonte, le_level?) — o contrato do casador de `.level`, forma a forma. A
# primeira linha e a sabotagem que o casador frouxo nao pegava.
_FORMAS_LEVEL = [
    (
        "level_de_outro_objeto_nao_conta",
        # O BURACO: a tool computa o veredito e ignora, mas tem um `.level`
        # qualquer no corpo. O casador frouxo (`no.attr == 'level'`) a tirava da
        # cobranca inteira, e a divergencia que ela escondesse ficava invisivel.
        "risk = classify(operation='x', params={})\n"
        "log.info('ok', extra=janela.level)\n"
        "run_mutation(reason=risk.reason)\n",
        False,
    ),
    (
        "atribuicao_simples",
        "risk = classify(operation='x', params={})\nif risk.level == RiskLevel.AUTO:\n    pass\n",
        True,
    ),
    (
        "chamada_direta",
        "if classify(operation='x', params={}).level is RiskLevel.AUTO:\n    pass\n",
        True,
    ),
    (
        "walrus",
        "if (r := classify(operation='x', params={})).level is RiskLevel.AUTO:\n    pass\n",
        True,
    ),
    (
        "anotada",
        "r: RiskClassification = classify(operation='x', params={})\nx = r.level\n",
        True,
    ),
    (
        "alias_de_import",
        "from src.governance.blast_radius import classify as _cls\n"
        "r = _cls(operation='x', params={})\n"
        "y = r.level\n",
        True,
    ),
    (
        "atributo_de_modulo",
        "import src.governance.blast_radius as br\nr = br.classify(operation='x', params={})\ny = r.level\n",
        True,
    ),
    (
        "level_sem_classify_nenhum",
        "y = janela.level\n",
        False,
    ),
]


@pytest.mark.parametrize(
    ("fonte", "le_level"),
    [(fonte, le) for _, fonte, le in _FORMAS_LEVEL],
    ids=[ident for ident, _, _ in _FORMAS_LEVEL],
)
def test_casador_de_level_so_conta_o_resultado_do_classify(fonte: str, le_level: bool) -> None:
    """Contrato do casador contra fonte sintetica, pela MESMA funcao do scanner.

    Sem esta tabela, o aperto dependeria de existir uma tool viva com `.level`
    de outro objeto — e nao existe nenhuma hoje (frouxo e apertado dao a MESMA
    resposta nas 28 tools, medido em 07/09). O aperto e contra a tool que ainda
    vai ser escrita, entao a prova tem que ser sintetica.
    """
    assert _le_level_do_classify(ast.parse(fonte)) is le_level, (
        f"veredito errado: esperado {le_level} para:\n{fonte}"
    )
