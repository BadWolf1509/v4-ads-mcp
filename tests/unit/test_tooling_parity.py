"""Paridade entre o tooling do Claude Code (.claude/) e o do Codex (.codex/, .agents/).

Os dois clientes compartilham os mesmos guard-rails do repo — em particular o
hook que impede editar migration já commitada. Onde dá, o Codex referencia o
arquivo do .claude; onde não dá (o Codex lê skills de um caminho fixo), a cópia
é inevitável e estes testes impedem que ela divirja em silêncio.
"""

import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_CLAUDE = _ROOT / ".claude"
_CODEX = _ROOT / ".codex"
_AGENTS = _ROOT / ".agents"


def test_codex_nao_duplica_os_hooks():
    """Havia copias byte-identicas em .codex/hooks/; corrigir um lado deixava o
    outro para tras, e um deles e o guard de migration."""
    assert not (_CODEX / "hooks").exists(), (
        ".codex/hooks/ voltou a existir — o hooks.json deve apontar pros .ps1 "
        "de .claude/hooks/, nao manter copia"
    )


def test_codex_hooks_apontam_pro_claude_sem_caminho_absoluto():
    """O valor anterior era D:\\v4-ads-mcp\\... — so funcionava numa maquina."""
    if not (_CODEX / "hooks.json").exists():
        return
    bruto = (_CODEX / "hooks.json").read_text(encoding="utf-8")
    config = json.loads(bruto)
    comandos = [
        h["command"]
        for grupo in config["hooks"].values()
        for entrada in grupo
        for h in entrada["hooks"]
    ]
    assert comandos, "hooks.json sem comando nenhum"
    for cmd in comandos:
        assert ".claude/hooks/" in cmd, f"deveria reusar o hook do .claude: {cmd}"
        assert "rev-parse --show-toplevel" in cmd, f"resolva a raiz via git: {cmd}"
        assert ":\\" not in cmd and ":/" not in cmd, f"caminho absoluto: {cmd}"


def test_hooks_compartilhados_nao_dependem_de_variavel_do_claude():
    """CLAUDE_PROJECT_DIR nao existe sob o Codex.

    Sem fallback, o guard de migration rodava `git log -- <path>` a partir do
    cwd errado; o pathspec e relativo ao cwd, entao ele nao achava commit algum
    e LIBERAVA a edicao. Verificado empiricamente em 2026-08-11.
    """
    for nome in ["guard-migrations.ps1", "format-python.ps1"]:
        script = (_CLAUDE / "hooks" / nome).read_text(encoding="utf-8")
        if "CLAUDE_PROJECT_DIR" not in script:
            continue
        assert "rev-parse --show-toplevel" in script, (
            f"{nome} usa CLAUDE_PROJECT_DIR sem fallback — quebra sob o Codex"
        )


def test_skills_do_codex_espelham_as_do_claude():
    """O Codex le skills de .agents/skills/, entao a copia e inevitavel."""
    origem = _CLAUDE / "skills"
    espelho = _AGENTS / "skills"
    if not espelho.exists():
        return
    for arquivo in espelho.rglob("*.md"):
        equivalente = origem / arquivo.relative_to(espelho)
        assert equivalente.exists(), f"{arquivo} nao tem par em .claude/skills/"
        assert arquivo.read_bytes() == equivalente.read_bytes(), (
            f"{arquivo.relative_to(_ROOT)} divergiu de {equivalente.relative_to(_ROOT)}"
        )


def test_agents_md_aponta_pro_claude_md_em_vez_de_forkar():
    """AGENTS.md era um fork do CLAUDE.md por find-replace.

    Ficou 26 commits atrasado e passou a ensinar o oposto do repo (dizia
    "Tailwind CDN" depois do CDN sair; nao conhecia a CSP sem unsafe-*), o que
    levaria um agente a escrever onclick inline — hoje bloqueado pelo browser.
    Um ponteiro nao tem como ficar velho.
    """
    agents = _ROOT / "AGENTS.md"
    if not agents.exists():
        return
    conteudo = agents.read_text(encoding="utf-8")
    assert "CLAUDE.md" in conteudo, "AGENTS.md precisa apontar pro contexto canonico"
    linhas = len(conteudo.splitlines())
    assert linhas < 60, (
        f"AGENTS.md com {linhas} linhas — voltou a duplicar o CLAUDE.md? "
        "Aponte pra ele em vez de copiar."
    )


def test_agentes_existem_nos_dois_clientes():
    """Um subagente definido so num cliente e uma capacidade que some quando o
    gestor troca de ferramenta."""
    claude = {p.stem for p in (_CLAUDE / "agents").glob("*.md")}
    codex_dir = _CODEX / "agents"
    if not codex_dir.exists():
        return
    codex = {p.stem for p in codex_dir.glob("*.toml")}
    assert claude == codex, (
        f"agentes divergentes — só no Claude: {claude - codex} · só no Codex: {codex - claude}"
    )
