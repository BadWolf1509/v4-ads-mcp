"""F187: o resumo no topo é a superfície de decisão; o detalhe embaixo é a verdade.

Quando os dois divergem, a decisão sai pelo resumo — e a divergência é
**estruturalmente invisível**, porque o detalhe está certo e qualquer revisão que o
abra absolve o arquivo. Em 20/09 a frase *"o smoke 3b.42 parou em 5 de 10"* atravessou
três leituras minhas, duas delas dentro de PRs cujo propósito declarado era remover
afirmação falsa daquele arquivo, e na terceira virou um pedido de execução que só não
virou mutação em conta real porque o `audit_log` foi consultado antes.

A regra "atualize o topo junto" é processo humano no lugar de mecanismo — teste 1 da
lista de gambiarra do `CLAUDE.md`. Estes guards são o mecanismo.

**Fora de escopo, de propósito:** casar prosa do resumo contra prosa do detalhe. Seria
casador de linguagem natural, erraria pelo que não está na lista, e viraria a terceira
fonte de verdade. Os guards afirmam **números derivados**, nunca frases.

**E o denominador do `N/M` também fica de fora**, com motivo: ele não tem definição
uniforme na família — o 3b.44 conta "obrigatórios" e exclui um teste opcional, os
outros contam o total. Asserir o denominador codificaria uma convenção que não existe.
O numerador é o que responde "falta rodar?", e é ele que se assere.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.unit._guard_harness import EscopoVazioError

_RAIZ = Path(__file__).resolve().parents[2]
_OPERACAO = _RAIZ / "docs" / "operacao"
_CATALOGO = _OPERACAO / "findings-catalog.md"
_FONTES_DE_METRICA = ("findings-catalog.md", "CLAUDE.md", "estado-atual.md")

# Legenda comum à família: ✅ executado com evidência transcrita · ◐ executado em sessão
# de campo · 🚫 tentado e barrado antes de chegar ao MCP · ⬜ não executado.
#
# ⚠️ NÃO está na legenda e mesmo assim é usado (3b.42 T8: "⚠️ PASS com bug no preview").
# Entra aqui porque teste que passou com ressalva FOI executado. A lista é do lado
# EXECUTADO de propósito: enumerar o que conta como executado erra ACUSANDO — glifo novo
# vira divergência barulhenta. Enumerar o lado "não executado" erraria ABSOLVENDO, que é
# o modo calado.
_EXECUTADO = ("✅", "◐", "⚠")
_NAO_EXECUTADO = ("⬜", "\U0001f6ab")

_PISO_DE_RUNBOOKS = 3  # 4 em 2026-09-20 (3b.41, 3b.42, 3b.43, 3b.44)
_TOLERANCIA = 0.10


def _caminhos_de_metrica() -> list[Path]:
    return [_CATALOGO, _RAIZ / "CLAUDE.md", _OPERACAO / "estado-atual.md"]


def _onde_declara(p: Path) -> str:
    """O trecho onde `p` DECLARA a métrica — não onde ele a cita.

    Só o catálogo tem esse problema, e por um motivo estrutural: **ele é o único que
    contém a própria história.** A entrada do F187 transcreve
    `"~1490 linhas, 151 IDs (F1-F152)"` como evidência do defeito, e varrer o arquivo
    inteiro fazia o guard acusar a documentação do bug como se fosse o bug.

    Logo o recorte vale para o auto-referente (cabeçalho, antes do primeiro `---`) e
    não para quem apenas referencia de fora. Não é lista de alvos: é a distinção entre
    declarar sobre si e citar o passado, e ela cai naturalmente num arquivo só.

    A primeira versão recortava os TRÊS e o controle pegou na hora — a declaração do
    `estado-atual` vive numa tabela abaixo do `---` dele e sumiu da varredura.
    """
    texto = p.read_text(encoding="utf-8")
    if p != _CATALOGO:
        return texto
    linhas = texto.splitlines()
    for i, linha in enumerate(linhas):
        if linha.strip() == "---" and i > 0:
            return "\n".join(linhas[:i])
    return texto


def _runbooks_com_resumo() -> list[tuple[str, list[str]]]:
    achados = []
    for p in sorted(_OPERACAO.glob("phase-*-smoke.md")):
        texto = p.read_text(encoding="utf-8")
        if "**Effective result:**" in texto:
            achados.append((p.name, texto.splitlines()))
    if len(achados) < _PISO_DE_RUNBOOKS:
        raise EscopoVazioError(
            f"só {len(achados)} runbooks com `Effective result` (piso: "
            f"{_PISO_DE_RUNBOOKS}, observados 4 em 2026-09-20). O glob não alcançou o "
            "diretório, e o guard estaria varrendo o vazio."
        )
    return achados


def _celulas(linha: str) -> list[str]:
    return [c.strip() for c in linha.strip().strip("|").split("|")]


def _contar_executados(linhas: list[str]) -> tuple[int, int] | None:
    """`(executados, total)` da tabela de resultados, ou None se não houver uma.

    O índice da coluna é **derivado do cabeçalho**, nunca fixo: entre os 4 runbooks ele
    varia (2 em três deles, 3 no 3b.44, que tem uma coluna `Muta?` a mais). Índice
    literal passaria a ler a coluna errada no primeiro runbook de formato novo.
    """
    for i, linha in enumerate(linhas):
        if not linha.startswith("|"):
            continue
        cabecalho = _celulas(linha)
        if "Result" not in cabecalho:
            continue
        col = cabecalho.index("Result")
        executados = total = 0
        for corpo in linhas[i + 2 :]:  # +2 pula a linha separadora |---|
            if not corpo.startswith("|"):
                break
            celulas = _celulas(corpo)
            if len(celulas) <= col:
                continue
            marca = celulas[col]
            if marca.startswith(_EXECUTADO):
                executados += 1
                total += 1
            elif marca.startswith(_NAO_EXECUTADO):
                total += 1
        return executados, total
    return None


def _declarado(linhas: list[str]) -> int | None:
    for linha in linhas:
        m = re.search(r"\*\*Effective result:\*\*\s*\**\s*(\d+)\s*/\s*(\d+)", linha)
        if m:
            return int(m.group(1))
    return None


def test_a_tabela_de_resultados_e_legivel_em_todos_os_runbooks() -> None:
    """Controle positivo: sem tabela lida, o guard irmão passa por vacuidade.

    "Não achei divergência" e "não achei tabela" são indistinguíveis para quem lê um
    teste verde — que é o defeito que este finding inteiro documenta.
    """
    ilegiveis: list[str] = []
    for nome, linhas in _runbooks_com_resumo():
        tabela = _contar_executados(linhas)
        if tabela is None or tabela[1] == 0:
            ilegiveis.append(f"{nome} (tabela)")
        if _declarado(linhas) is None:
            ilegiveis.append(f"{nome} (sem N/M no resumo)")
    assert not ilegiveis, (
        "runbook cuja tabela de resultados ou cujo `Effective result` não foi lido: "
        + ", ".join(ilegiveis)
        + ". O guard irmão não compara o que não leu, e passaria verde sem medir nada."
    )


def test_o_resumo_declara_o_mesmo_que_a_tabela_conta() -> None:
    divergentes: list[str] = []
    for nome, linhas in _runbooks_com_resumo():
        tabela = _contar_executados(linhas)
        declarado = _declarado(linhas)
        if tabela is None or declarado is None:
            continue  # coberto pelo controle acima
        executados, total = tabela
        if declarado != executados:
            divergentes.append(
                f"{nome}: o resumo diz {declarado} executados, a tabela conta "
                f"{executados} de {total}"
            )
    assert not divergentes, (
        "resumo e tabela discordam sobre quantos testes rodaram:\n  "
        + "\n  ".join(divergentes)
        + "\n\nO resumo é o que alguém lê para decidir SE FALTA RODAR — e re-rodar um "
        "smoke que muta significa mutar uma conta real outra vez (F187). A tabela é a "
        "fonte: corrija o resumo, nunca a tabela."
    )


def _declaracoes_de_tamanho() -> list[tuple[str, int]]:
    """`(arquivo, linhas declaradas)` onde quer que o tamanho do catálogo apareça.

    São TRÊS cópias do mesmo fato (o próprio catálogo, o `CLAUDE.md` e o
    `estado-atual.md`) — duplicação de estado registrada como dívida no F187. Enquanto
    ela existir, este guard é o que impede as três de divergirem em silêncio.
    """
    achados: list[tuple[str, int]] = []
    for p in _caminhos_de_metrica():
        for m in re.finditer(r"~\s*([\d.]+)\s*linhas", _onde_declara(p)):
            achados.append((p.name, int(m.group(1).replace(".", ""))))
    return achados


def test_as_declaracoes_de_tamanho_do_catalogo_existem() -> None:
    """Controle positivo: se o casador não acha nenhuma, o guard irmão é vácuo."""
    achados = _declaracoes_de_tamanho()
    assert len(achados) >= len(_FONTES_DE_METRICA), (
        f"esperava ao menos {len(_FONTES_DE_METRICA)} declarações de tamanho, achei "
        f"{achados}. Ou o formato mudou, ou o casador quebrou — nos dois casos o guard "
        "irmão estaria passando sem comparar nada."
    )


def test_o_catalogo_nao_mente_sobre_o_proprio_tamanho() -> None:
    """Tolerância de ±10%, larga de propósito.

    O defeito medido foi "~1490 linhas" num arquivo de 3.993 — erro de 2,7x. ±10% pega
    isso com folga e ainda sobrevive a uns 5 findings novos antes de cobrar refresh,
    que é a cadência certa: apertar viraria ruído a cada append, afrouxar deixaria a
    deriva crescer de novo até ninguém confiar no número.
    """
    real = len(_CATALOGO.read_text(encoding="utf-8").splitlines())
    fora = [
        f"{nome} declara ~{declarado} linhas; o arquivo tem {real}"
        for nome, declarado in _declaracoes_de_tamanho()
        if abs(declarado - real) > real * _TOLERANCIA
    ]
    assert not fora, (
        "declaração de tamanho fora de ±10% do arquivo real:\n  "
        + "\n  ".join(fora)
        + f"\n\nO catálogo tem {real} linhas. Quem lê esse número decide se dá para ler "
        "o arquivo inteiro — e já houve '~1490 linhas' num arquivo de 3.993 (F187)."
    )


def test_a_faixa_de_findings_declarada_bate_com_o_maior_id() -> None:
    """Aqui a asserção é EXATA, não tolerante: a faixa é o índice do arquivo.

    Tolerar deriva na faixa deixaria o leitor procurar um finding que o índice diz não
    existir — ou parar antes do que existe. O custo de errar é uma sessão reabrindo
    trabalho já fechado.
    """
    ids = [
        int(m.group(1))
        for m in re.finditer(r"^## F(\d+)", _CATALOGO.read_text(encoding="utf-8"), re.MULTILINE)
    ]
    assert ids, "nenhum cabeçalho `## F<n>` no catálogo — o casador quebrou."
    maior = max(ids)

    # As três grafias em uso: `F1–F187`, `F1 a F187` e `até **F187**`.
    padrao = re.compile(r"F1[–-]F(\d+)|F1 a F(\d+)|at[ée] \*\*F(\d+)\*\*")
    declaradas: list[tuple[str, int]] = []
    for p in _caminhos_de_metrica():
        for m in padrao.finditer(_onde_declara(p)):
            valor = m.group(1) or m.group(2) or m.group(3)
            declaradas.append((p.name, int(valor)))

    assert declaradas, "nenhuma faixa `F1–F<n>` declarada — o casador quebrou."
    erradas = [f"{nome} declara ate F{v}" for nome, v in declaradas if v != maior]
    assert not erradas, (
        f"faixa declarada diverge do maior `## F<n>` do catálogo (F{maior}):\n  "
        + "\n  ".join(erradas)
        + "\n\nA faixa é o índice do arquivo: divergir manda o leitor procurar o que o "
        "índice diz não existir, ou parar antes do que existe."
    )
