"""F138: commit que toca so `docs/` publicava revisao nova do servidor MCP.

Este e o servidor por onde o gestor escreve nas contas dos clientes. Um deploy no
meio de uma sequencia de `update_rsa` + `apply_change` tiraria a ferramenta com
writes parciais aplicados. Em 02/09 aconteceu: 4 commits que mexiam SO no
`findings-catalog.md` rodaram `Route 100% traffic to latest revision` + smoke.

**A correcao obvia (`paths-ignore` no `on:`) seria pior, e isso foi verificado
contra a API de protecao da branch, nao suposto:** `test` e required status check
e `pr_required` esta ligado, entao um PR so de documentacao nao dispararia o
workflow, o check nunca reportaria, e o PR travaria em "Expected — waiting for
status" sem caminho de merge que nao fosse bypass de admin.

A correcao aplicada condiciona o JOB `deploy`, que ja era gated por `if:`. O
`test` continua rodando sempre.

## O que estes guards protegem

O primeiro grupo cuida da fiacao. O segundo cuida da LOGICA — que e onde mora o
risco real, porque um `grep` editado sem cuidado nao quebra nada visivelmente: ele
so passa a deployar (ou a nao deployar) calado.

O guard mais sutil e o do `fetch-depth: 0`. Sem ele o clone e raso, o
`git cat-file -e` da base falha, o script cai no fail-open e passa a devolver
`true` **sempre** — o gate vira no-op com cara de funcionando. Degradacao
silenciosa, que e a familia que este repo cataloga.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
import yaml

_CI = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"


def _workflow() -> dict:
    return yaml.safe_load(_CI.read_text(encoding="utf-8"))


def _passo_de_deteccao() -> dict:
    steps = _workflow()["jobs"]["test"]["steps"]
    achados = [s for s in steps if s.get("id") == "detectar_mudanca"]
    assert len(achados) == 1, "o passo de deteccao do F138 sumiu do job `test`"
    return achados[0]


# --- Fiacao -------------------------------------------------------------------


def test_job_test_exporta_code_changed() -> None:
    outputs = _workflow()["jobs"]["test"].get("outputs") or {}
    assert "code_changed" in outputs


def test_deploy_exige_code_changed() -> None:
    """Sem esta condicao, commit de docs volta a publicar revisao nova."""
    condicao = _workflow()["jobs"]["deploy"]["if"]
    assert "needs.test.outputs.code_changed == 'true'" in condicao


def test_test_continua_rodando_em_pull_request() -> None:
    """A inversao do `paths-ignore`: o required check tem que reportar sempre.

    Se alguem "otimizar" pondo filtro de caminho no `on:`, PR de docs trava sem
    caminho de merge — pior que o problema original.
    """
    gatilhos = _workflow()[True]  # o YAML transforma a chave `on:` em True
    assert "pull_request" in gatilhos
    assert "paths-ignore" not in str(gatilhos)
    assert "paths" not in str(gatilhos)


def test_checkout_traz_historico_completo() -> None:
    """Sem `fetch-depth: 0` o gate vira no-op silencioso (fail-open sempre)."""
    checkout = _workflow()["jobs"]["test"]["steps"][0]
    assert "checkout" in checkout["uses"]
    assert (checkout.get("with") or {}).get("fetch-depth") == 0


# --- Logica -------------------------------------------------------------------


def _bash_que_funciona() -> str | None:
    """Acha um bash que REALMENTE roda.

    `shutil.which("bash")` no Windows devolve o `bash.exe` do WSL, que existe no
    PATH e falha com "execvpe(/bin/bash) failed" quando o WSL nao esta
    configurado — foi o que aconteceu ao escrever este arquivo. Presenca no PATH
    nao e prova de que executa; por isso cada candidato e exercitado.
    """
    candidatos = [
        shutil.which("bash"),
        os.path.join(os.environ.get("PROGRAMFILES", r"C:\Program Files"), "Git", "bin", "bash.exe"),
        "/bin/bash",
    ]
    for c in candidatos:
        if not c or not Path(c).exists():
            continue
        try:
            if subprocess.run([c, "-c", "true"], capture_output=True, timeout=15).returncode == 0:
                return c
        except OSError:
            continue
    return None


_BASH = _bash_que_funciona()


def _rodar(arquivos: list[str] | None, *, base: str = "abc123") -> str:
    """Executa o script do passo com a lista de arquivos injetada.

    Substitui as duas chamadas de git para o teste nao depender de SHA real nem
    do estado do repo — o que importa aqui e a CLASSIFICACAO da lista.
    """
    script = _passo_de_deteccao()["run"]
    script = script.replace("${{ github.event.before }}", base)
    script = script.replace("${{ github.sha }}", "def456")
    script = script.replace('git cat-file -e "${BASE}^{commit}" 2>/dev/null', "true")
    listagem = (
        "printf '%s\\n' " + " ".join(f"'{a}'" for a in (arquivos or [])) if arquivos else "true"
    )
    script = script.replace('git diff --name-only "$BASE" "$HEAD_SHA"', listagem)

    with tempfile.TemporaryDirectory() as d:
        sh = Path(d) / "step.sh"
        sh.write_text(script, encoding="utf-8")
        saida = Path(d) / "out"
        saida.touch()
        env = {
            **os.environ,
            "GITHUB_OUTPUT": saida.as_posix(),
            "GITHUB_STEP_SUMMARY": (Path(d) / "sum").as_posix(),
        }
        assert _BASH is not None
        r = subprocess.run(
            [_BASH, "-e", sh.as_posix()], env=env, check=False, capture_output=True, text=True
        )
        assert r.returncode == 0, f"o script do passo falhou: {r.stderr}"
        for linha in saida.read_text(encoding="utf-8").splitlines():
            if linha.startswith("code_changed="):
                return linha.split("=", 1)[1]
    raise AssertionError("o script nao escreveu code_changed no GITHUB_OUTPUT")


pytestmark_bash = pytest.mark.skipif(
    _BASH is None, reason="nenhum bash executavel encontrado (o do WSL nao conta)"
)


@pytestmark_bash
def test_push_so_de_docs_nao_deploya() -> None:
    """O caso de 02/09, que era exatamente esta lista."""
    assert _rodar(["docs/operacao/findings-catalog.md"]) == "false"


@pytestmark_bash
def test_markdown_fora_de_docs_tambem_nao_deploya() -> None:
    assert _rodar(["README.md", "docs/operacao/estado-atual.md"]) == "false"


@pytestmark_bash
def test_mudanca_em_src_deploya() -> None:
    assert _rodar(["src/mcp/tools/detect_drift.py"]) == "true"


@pytestmark_bash
def test_mudanca_misturada_deploya() -> None:
    """Um arquivo de codigo no meio de muitos de docs ainda tem que deployar."""
    assert _rodar(["docs/a.md", "docs/b.md", "src/x.py", "docs/c.md"]) == "true"


@pytestmark_bash
def test_workflow_e_lockfile_contam_como_codigo() -> None:
    assert _rodar([".github/workflows/ci.yml"]) == "true"
    assert _rodar(["requirements.txt"]) == "true"


@pytestmark_bash
def test_sem_base_confiavel_deploya_fail_open() -> None:
    """Deploy a mais e melhor que deploy que devia acontecer e nao aconteceu."""
    assert _rodar(["docs/x.md"], base="") == "true"
    assert _rodar(["docs/x.md"], base="0" * 40) == "true"


@pytestmark_bash
def test_diff_vazio_deploya_fail_open() -> None:
    assert _rodar(None) == "true"
