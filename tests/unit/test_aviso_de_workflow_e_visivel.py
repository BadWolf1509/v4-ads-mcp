"""F186, passo 1: aviso em workflow tem de ser anotação, não `echo` enterrado no log.

O smoke autenticado do `/mcp` pode se desarmar sozinho — token vencido, ou secret
ausente — e nos dois casos ele imprimia `echo "  ⚠ ..."` e deixava o deploy seguir.
A decisão de não travar a entrega por credencial de CI vencida é **correta e fica**.
O que faltava era a contraparte: **nada percebia que o check estava desligado.**

Medido em 2026-09-20: **8 de 8 deploys bem-sucedidos, o mais antigo em 18/09, com o
smoke desarmado.** Ninguém soube, porque o aviso era uma linha dentro de um run verde —
exatamente o lugar onde ninguém olha.

A invariante é sobre VISIBILIDADE, não sobre o texto do aviso: quando um passo sinaliza
uma condição de atenção com ⚠ e **não** derruba o run, o único mecanismo que o GitHub
Actions oferece para essa condição chegar a alguém é a anotação (`::warning::`), que
sobe ao resumo do run. `echo` simples num run verde é indistinguível de silêncio.

Não vale para ✗: aquelas linhas vêm acompanhadas de `exit 1`, o run fica vermelho, e
vermelho já é visível por si.

**Fora de escopo, de propósito:** fazer o desarme derrubar o deploy. Trocaria um ponto
cego por uma trava — token vencido passaria a bloquear entrega legítima, que é o que o
desenho atual evita de propósito e com razão. Este guard cobra que o desarme seja
VISTO, não que ele seja fatal.

O passo 3 do F186 é quem **cobra** (workflow de liveness que falha alto quando o token
não vale). Este aqui só garante que o estado deixe de ser invisível — os dois juntos
fecham o laço, e nenhum dos dois sozinho fecha.
"""

from __future__ import annotations

from tests.unit import _guard_harness as h
from tests.unit._guard_harness import EscopoVazioError

_GLIFO = "⚠"  # ⚠
_ANOTACOES = ("::warning", "::error", "GITHUB_STEP_SUMMARY")

# 3 workflows em 2026-09-20 (ci, deploy, liveness do smoke). O piso protege contra o
# coletor devolver lista vazia e o guard passar por vacuidade — o modo de falha mais
# caro deste repo, porque zero se parece com "está tudo certo" (F183).
_PISO_DE_WORKFLOWS = 2


def _workflows() -> list[tuple[str, list[str]]]:
    arquivos = h.workflows()
    if len(arquivos) < _PISO_DE_WORKFLOWS:
        raise EscopoVazioError(
            f"só {len(arquivos)} workflows encontrados (piso: {_PISO_DE_WORKFLOWS}). "
            "O coletor não achou o diretório, e o guard estaria varrendo o vazio."
        )
    return [(h.rel(p), p.read_text(encoding="utf-8").splitlines()) for p in arquivos]


def test_o_casador_enxerga_as_anotacoes_que_existem() -> None:
    """Controle positivo: o repo JÁ usa anotação em `ci.yml`.

    Sem esta metade, o guard irmão passaria verde por não achar nada — e "não achei"
    seria lido como "não há", que é o erro que este finding inteiro documenta.
    """
    com_anotacao = [
        nome for nome, linhas in _workflows() if any(a in ln for ln in linhas for a in _ANOTACOES)
    ]
    assert com_anotacao, (
        "nenhum workflow usa `::warning::`, `::error::` ou `$GITHUB_STEP_SUMMARY`. "
        "O repo usava pelo menos um em 2026-09-20 — ou o casador quebrou, ou o "
        "coletor leu os arquivos errados. Nos dois casos o guard irmão está passando "
        "por vacuidade."
    )


def test_aviso_que_nao_derruba_o_run_sai_como_anotacao() -> None:
    invisiveis = [
        f"{nome}:{n}"
        for nome, linhas in _workflows()
        for n, ln in enumerate(linhas, 1)
        if _GLIFO in ln and not any(a in ln for a in _ANOTACOES)
    ]
    assert not invisiveis, (
        "aviso com ⚠ saindo por `echo` simples, sem anotação: "
        + ", ".join(invisiveis)
        + ". Num run que fica VERDE, isso é indistinguível de silêncio — foi assim "
        "que o smoke autenticado do /mcp passou 8 de 8 deploys desarmado sem ninguém "
        'saber (F186). Use `echo "::warning title=...::..."`, que sobe ao resumo do '
        "run. Se a condição for fatal, use ✗ com `exit 1` — vermelho já é visível."
    )
