"""Paridade entre o gate local e o CI, e o comando do lockfile.

Duas classes de atrito que nao aparecem em teste nenhum hoje:

1. Check que so existe no CI = feedback depois do push, com a espera do runner.
   A protecao era a regra do CLAUDE.md ("lembre de rodar o build_tailwind"), e
   regra que depende de memoria e o que este repo converte em guard.
2. Instrucao de regenerar o lockfile SEM `--universal` produz um requirements.txt
   com `pywin32` incondicional — e o buildpack CNB tenta instala-lo no Linux.
   Doc que instrui a quebrar producao e pior que doc desatualizada (F99).
"""

import re
from pathlib import Path

_RAIZ = Path(__file__).resolve().parents[2]
_CI = _RAIZ / ".github" / "workflows" / "ci.yml"
_RUNNER = _RAIZ / "scripts" / "_runner.py"

# Ferramentas que caracterizam um CHECK (o resto dos steps e setup/instalacao).
_FERRAMENTAS = ("ruff check", "ruff format", "mypy", "pytest", "build_tailwind.py")


def _steps_de_check_do_ci() -> set[str]:
    """Ferramentas invocadas por steps BLOQUEANTES do job `test`.

    `continue-on-error: true` (o pip-audit) nao conta: nao segura merge nenhum,
    entao exigi-lo no gate local so tornaria o gate mais lento.
    """
    texto = _CI.read_text(encoding="utf-8")
    # o job `deploy` nao tem `run:`, entao varrer o arquivo inteiro e seguro
    blocos = re.split(r"^      - (?:name|uses):", texto, flags=re.M)
    achadas: set[str] = set()
    for bloco in blocos:
        if "continue-on-error: true" in bloco:
            continue
        for ferramenta in _FERRAMENTAS:
            if ferramenta in bloco:
                achadas.add(ferramenta)
    return achadas


def _ferramentas_do_gate_local() -> set[str]:
    """Ferramentas que o gate local roda, DIRETA ou indiretamente.

    O fecho de um nivel importa: o step do Tailwind chama
    `check_tailwind_sync.py`, que por sua vez chama `build_tailwind.py`. Um
    scanner que olhasse so o _runner.py acusaria uma lacuna que nao existe —
    a mesma armadilha do guard transitivo do F109.
    """
    texto = _RUNNER.read_text(encoding="utf-8")
    for script in (_RAIZ / "scripts").glob("*.py"):
        if script.name in texto:
            texto += script.read_text(encoding="utf-8")
    achadas: set[str] = set()
    for ferramenta in _FERRAMENTAS:
        # no runner os comandos sao listas: ["-m", "ruff", "check", ...]
        alvo = ferramenta.replace(" ", '", "')
        if alvo in texto or ferramenta in texto:
            achadas.add(ferramenta)
    return achadas


def test_ci_realmente_tem_checks() -> None:
    """Se o parser parar de casar, o teste abaixo passaria vazio."""
    assert len(_steps_de_check_do_ci()) >= 4, "esperado ruff/mypy/pytest/tailwind no CI"


def test_gate_local_cobre_todo_check_bloqueante_do_ci() -> None:
    """Check que so roda no CI vira vermelho DEPOIS do push."""
    faltando = sorted(_steps_de_check_do_ci() - _ferramentas_do_gate_local())
    assert not faltando, (
        "checks bloqueantes do CI ausentes do gate local: "
        + ", ".join(faltando)
        + " — adicione em scripts/_runner.py (pule com dica se a ferramenta "
        "nao existir na maquina, como check_docker faz)"
    )


def test_toda_instrucao_de_regerar_o_lock_usa_universal() -> None:
    """Sem `--universal` o lockfile sai com `pywin32` incondicional.

    A maquina do dev e Windows, entao o comando sem a flag resolve pra aquela
    plataforma e o buildpack CNB quebra ao instalar no Linux. Verificado
    rodando os dois: com a flag sai `pywin32==312 ; sys_platform == 'win32'`.
    """
    ofensores: list[str] = []
    for caminho in (*_RAIZ.glob("*.md"), *(_RAIZ / ".github" / "workflows").glob("*.yml")):
        for numero, linha in enumerate(caminho.read_text(encoding="utf-8").splitlines(), 1):
            # exige `pyproject.toml` pra casar COMANDO copiavel, nao mencao
            # em prosa ("o lockfile sai de um uv pip compile do pyproject").
            comando = "uv pip compile" in linha and "pyproject.toml" in linha
            if comando and "--universal" not in linha:
                ofensores.append(f"{caminho.name}:{numero}")
    assert not ofensores, (
        "instrucao de regerar o lockfile sem --universal (quebra o build Linux): "
        + "; ".join(ofensores)
    )


def test_lockfile_carrega_markers_de_plataforma() -> None:
    """Prova que o requirements.txt commitado saiu de um compile universal.

    Sem markers, `pywin32` viajaria pro Linux — o sintoma que a flag evita.
    """
    lock = (_RAIZ / "requirements.txt").read_text(encoding="utf-8")
    assert "pywin32" in lock, "dependencia win-only sumiu; reavalie este guard"
    linha_pywin32 = next(linha for linha in lock.splitlines() if linha.startswith("pywin32"))
    assert "sys_platform == 'win32'" in linha_pywin32, (
        f"pywin32 sem marker de plataforma ({linha_pywin32!r}) — o lockfile foi "
        "gerado sem --universal e o buildpack CNB vai tentar instala-lo no Linux"
    )
