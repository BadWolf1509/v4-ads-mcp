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


def _chamada_ao_classify(no: ast.AST, nomes: set[str]) -> ast.Call | None:
    """A `ast.Call` a `classify` que `no` representa — `None` se não for uma.

    Desembrulha o walrus ANTES de olhar: em `(r := classify(...)).level` o dono
    do atributo é o `ast.NamedExpr`, não o `ast.Call` — sem isso a forma passava
    como "não lê `.level`". Achado pela própria tabela sintética deste módulo.

    **Devolve o nó DESEMBRULHADO, não um booleano.** A primeira versão do
    desembrulho devolvia `True` e deixava o chamador com o nó original: quem
    precisava de `.keywords` (`_operacao_classificada`) o pedia a um
    `ast.NamedExpr`, que não tem esse atributo. Uma tool com walrus que NÃO
    lesse `.level` derrubava `_particionar()` — e como `_PARTICAO` é montada no
    import, o módulo inteiro morria na COLEÇÃO, com `AttributeError` e rc=2, em
    vez de dar um teste vermelho legível (revisão de 2026-09-07). O tipo de
    retorno é o que impede a reincidência: não há mais nó original para o
    chamador usar por engano, e o `mypy` cobra o `is None`.
    """
    if isinstance(no, ast.NamedExpr):
        no = no.value
    if not isinstance(no, ast.Call):
        return None
    f = no.func
    if isinstance(f, ast.Name):
        return no if f.id in nomes else None
    if isinstance(f, ast.Attribute):
        return no if f.attr in nomes else None
    return None


def _ligados_por_escopo(arvore: ast.Module) -> dict[ast.AST, tuple[set[str], set[str]]]:
    """Por escopo: (nomes ligados a `classify`, todos os nomes ligados ali).

    O segundo conjunto existe para modelar SOMBREAMENTO. `x` lido num escopo
    resolve no escopo mais interno que liga `x` — se esse escopo liga `x` a
    outra coisa, a ligação de fora não vale mais. Sem isso, `risk = janela`
    dentro de um closure herdaria o `risk = classify(...)` do pai.

    Entram como ligação: `=`, `:=`, atribuição anotada, `for` alvo, `with ...
    as`, `except ... as` e os PARÂMETROS da função. Não tenta desempacotar
    tupla (`a, b = ...`) nem seguir reatribuição encadeada — quem escrever
    isso cai em `caminho_ambiguo` e é cobrado lá, em vez de sumir calado.

    `lambda` é transparente aqui pela mesma razão de `h.nos_do_corpo_proprio`:
    é expressão escrita inline no corpo que a contém.
    """
    nomes = h.nomes_locais(arvore, "classify")
    tabela: dict[ast.AST, tuple[set[str], set[str]]] = {}
    for escopo in (arvore, *h.funcoes(arvore)):
        do_classify: set[str] = set()
        todos: set[str] = set()
        args = getattr(escopo, "args", None)
        if args is not None:  # parâmetro é ligação, e sombreia
            todos.update(
                a.arg
                for a in (*args.posonlyargs, *args.args, *args.kwonlyargs)
                if isinstance(a, ast.arg)
            )
            todos.update(a.arg for a in (args.vararg, args.kwarg) if a is not None)
        for no in h.nos_do_corpo_proprio(escopo):
            valor: ast.expr | None
            alvos: list[ast.expr]
            if isinstance(no, ast.Assign):
                valor, alvos = no.value, list(no.targets)
            elif isinstance(no, ast.AnnAssign | ast.NamedExpr):
                valor, alvos = no.value, [no.target]
            elif isinstance(no, ast.For | ast.AsyncFor):
                valor, alvos = None, [no.target]
            elif isinstance(no, ast.withitem):
                valor = None
                alvos = [no.optional_vars] if no.optional_vars is not None else []
            elif isinstance(no, ast.ExceptHandler):
                valor, alvos = None, []
                if no.name is not None:
                    todos.add(no.name)
            else:
                continue
            ligados_aqui = {a.id for a in alvos if isinstance(a, ast.Name)}
            todos |= ligados_aqui
            if valor is not None and _chamada_ao_classify(valor, nomes) is not None:
                do_classify |= ligados_aqui
        tabela[escopo] = (do_classify, todos)
    return tabela


def _escopo_de_cada_no(arvore: ast.Module) -> dict[ast.AST, ast.AST]:
    """O escopo (módulo ou função) a que cada nó pertence, sem contar `lambda`."""
    dono: dict[ast.AST, ast.AST] = {}
    for escopo in (arvore, *h.funcoes(arvore)):
        for no in h.nos_do_corpo_proprio(escopo):
            dono[no] = escopo
    return dono


def _le_level_do_classify(arvore: ast.Module) -> bool:
    """True se a tool lê `.level` DO RESULTADO de `classify` — nao de outra coisa.

    Ate 2026-09-07 a pergunta era `any(no.attr == "level" for no in walk)`, que
    casa QUALQUER atributo chamado `level`: um `log.bind(level=...)`, um
    `janela.level`, um kwarg de qualquer biblioteca. Uma tool que computasse
    `classify` e ignorasse o veredito, mas tivesse um `x.level` qualquer no
    corpo, saia da cobranca inteira — e sairia calada, porque a lista de casos e
    derivada e ninguem conta quantos deveriam estar nela. Era o guard eximindo
    justamente quem ele existe pra cobrar.

    **A ligação do nome tem ESCOPO.** O primeiro aperto ligou os nomes no
    módulo inteiro, e isso reabria o buraco por outra porta: bastava OUTRA
    função do mesmo arquivo ter uma variável de mesmo nome lendo `.level`
    (`def _formata(janela): risk = janela; return risk.level`) para a tool que
    ignora o veredito e auto-aplica uma operação CONFIRM sair da cobrança
    inteira. Medido em 2026-09-07: guard VERDE sob essa sabotagem. A leitura
    agora resolve como o Python resolve — no escopo do próprio nó, subindo a
    cadeia léxica e PARANDO no primeiro escopo que sombreia o nome.
    """
    nomes = h.nomes_locais(arvore, "classify")
    ligados = _ligados_por_escopo(arvore)
    dono = _escopo_de_cada_no(arvore)
    pai = h.escopos_pais(arvore)

    for no in ast.walk(arvore):
        if not (isinstance(no, ast.Attribute) and no.attr == "level"):
            continue
        if _chamada_ao_classify(no.value, nomes) is not None:  # `classify(...).level` direto
            return True
        if not isinstance(no.value, ast.Name):
            continue
        escopo: ast.AST | None = dono.get(no)
        while escopo is not None:
            do_classify, todos = ligados.get(escopo, (set(), set()))
            if no.value.id in do_classify:
                return True
            if no.value.id in todos:
                break  # sombreado por outra ligação: a de fora nao vale mais
            escopo = pai.get(escopo)
    return False


def _operacao_classificada(arvore: ast.Module) -> str | None:
    """String literal passada como `operation=` pro classify (None se nao houver).

    Alias-aware pela mesma razao que `_le_level_do_classify`: o casamento
    estreito daqui e o que sustenta a derivacao EXATA — quem entra no universo
    por `h.chama` e nao sai por aqui vira ofensor declarado, nao um `continue`.
    """
    nomes = h.nomes_locais(arvore, "classify")
    for no in ast.walk(arvore):
        chamada = _chamada_ao_classify(no, nomes)
        if chamada is None:
            continue
        for kw in chamada.keywords:
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
    (
        "nome_igual_noutra_funcao_nao_conta",
        # A SABOTAGEM DO I2: verde ate 2026-09-07 porque a ligacao do nome nao
        # tinha escopo. A tool ignora o veredito e auto-aplica uma operacao que
        # o modulo classifica como CONFIRM; quem le `risk.level` e OUTRA funcao,
        # sobre OUTRO objeto. Com a ligacao no modulo inteiro, o arquivo saia da
        # cobranca por colisao de nome — o mesmo buraco que a task fechou, um
        # nivel abaixo.
        "def _formata(janela):\n"
        "    risk = janela\n"
        "    return risk.level\n"
        "async def zz(args):\n"
        "    risk = classify(operation='update_campaign_budget', params={})\n"
        "    await run_mutation(args)\n"
        "    return risk.reason\n",
        False,
    ),
    (
        "parametro_de_outra_funcao_nao_conta",
        # Variante da mesma familia: o nome colide com um PARAMETRO alheio.
        "def _formata(risk):\n"
        "    return risk.level\n"
        "async def zz(args):\n"
        "    risk = classify(operation='x', params={})\n"
        "    return risk.reason\n",
        False,
    ),
    (
        "sombreado_no_closure_nao_conta",
        # Sombreamento: o closure religa `risk` a outra coisa antes de ler
        # `.level`, entao a ligacao do pai nao alcanca essa leitura.
        "async def zz(args, janela):\n"
        "    risk = classify(operation='x', params={})\n"
        "    def _f():\n"
        "        risk = janela\n"
        "        return risk.level\n"
        "    return _f()\n",
        False,
    ),
    (
        "closure_le_o_nome_do_pai_conta",
        # A outra metade: closure que CAPTURA o nome do pai le, sim, o veredito.
        # Sem esta linha, o aperto de escopo viraria falso negativo ao contrario.
        "async def zz(args):\n"
        "    risk = classify(operation='x', params={})\n"
        "    def _f():\n"
        "        return risk.level is RiskLevel.AUTO\n"
        "    return _f()\n",
        True,
    ),
    (
        "walrus_sem_level",
        # A forma que derrubava a COLECAO do modulo (I1): walrus no classify sem
        # ler `.level`. Aqui a tabela so cobra o veredito; que ela nao ESTOURE
        # mais e o que `test_walrus_sem_level_da_teste_vermelho...` prova.
        "motivo = (r := classify(operation='x', params={})).reason\n",
        False,
    ),
]


# Tool sintetica com a forma do I1: walrus no `classify`, sem ler `.level`, e
# com caminho fixo AUTO contra uma operacao que a politica diz ser CONFIRM.
_TOOL_WALRUS_SEM_LEVEL = (
    "from src.governance.blast_radius import classify\n"
    "async def zz_walrus(args):\n"
    "    motivo = (r := classify(operation='update_campaign_budget', params={})).reason\n"
    "    await run_mutation(args)\n"
    "    return {'reason': motivo}\n"
)


def test_walrus_sem_level_da_teste_vermelho_e_nao_erro_de_colecao(tmp_path: Path) -> None:
    """Tool com walrus que NAO le `.level` tem que ser COBRADA, nao estourar.

    Ate a revisao de 2026-09-07, `_operacao_classificada` pedia `.keywords` ao
    no que `_e_chamada_ao_classify` recebia — um `ast.NamedExpr` nessa forma.
    Como `_PARTICAO` e montada no import, o efeito nao era um teste vermelho: o
    modulo inteiro morria na COLECAO (`AttributeError`, rc=2), que e exatamente
    o modo de falha que a Task 3 declarou ter removido. Um guard que nao coleta
    nao cobra ninguem — inclusive as outras 27 tools.

    O teste roda a MESMA `_particionar` do scanner sobre uma raiz sintetica.
    Contra o codigo pre-fix ele fica VERMELHO no `_particionar`; contra o codigo
    corrigido ele mostra a tool caindo em `caminho_fixo` com AUTO, divergindo da
    politica — que e a cobranca certa, legivel e localizada.
    """
    (tmp_path / "zz_walrus.py").write_text(_TOOL_WALRUS_SEM_LEVEL, encoding="utf-8")

    particao = _particionar(tmp_path)  # pre-fix: AttributeError aqui

    assert particao.leem_level == [], "a tool usa so `.reason` — nao pode contar como leitora"
    assert particao.caminho_fixo == [("zz_walrus.py", "update_campaign_budget", RiskLevel.AUTO)], (
        f"a tool tinha que entrar na cobranca de caminho fixo: {particao}"
    )

    _, operacao, esperado = particao.caminho_fixo[0]
    assert classify(operation=operacao, params={"target_count": 1}).level is not esperado, (
        "esta forma so prova o que precisa provar se a politica DISCORDAR do "
        "caminho fixo: e a discordancia que vira teste vermelho parametrizado. "
        "Se `update_campaign_budget` passar a classificar AUTO, troque a "
        "operacao da fonte sintetica por outra que o modulo mande confirmar."
    )


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
