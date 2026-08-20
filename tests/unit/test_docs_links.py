"""Higiene da documentacao: link que resolve, e CLAUDE.md dentro do orcamento.

A doc deste repo E a memoria dele: o CLAUDE.md aponta pro handoff, que aponta
pro catalogo, que aponta pro runbook arquivado. Sao 27 links so pro _archive.
Um link morto nao falha nada — o leitor (humano ou agente) simplesmente nao
chega no "porque", e o custo aparece semanas depois, na forma de alguem
refazendo uma decisao ja tomada.

Escopo: os .md da raiz e os de `docs/operacao`, `docs/convencoes` e `docs/superpowers`. O
`docs/_archive/` fica FORA como ORIGEM (arquivo historico pode apontar pra algo
que mudou de lugar depois; corrigir 108 arquivos parados seria trabalho morto),
mas continua valendo como DESTINO — link vivo apontando pra la tem que resolver.
"""

import re
from pathlib import Path

_RAIZ = Path(__file__).resolve().parents[2]

# `](destino)` sem protocolo e sem ancora pura
_LINK = re.compile(r"\]\((?!https?://|mailto:|#)([^)]+)\)")


def _docs_vivos() -> list[Path]:
    arquivos = sorted(_RAIZ.glob("*.md"))
    for pasta in ("docs/operacao", "docs/convencoes", "docs/superpowers"):
        arquivos.extend(sorted((_RAIZ / pasta).rglob("*.md")))
    return arquivos


def test_ha_docs_vivos_pra_verificar() -> None:
    """Se o coletor parar de casar, o teste abaixo passaria vazio."""
    assert len(_docs_vivos()) >= 20, "esperado dezenas de .md vivos"


def test_todo_link_relativo_da_doc_viva_resolve() -> None:
    quebrados: list[str] = []
    for doc in _docs_vivos():
        for numero, linha in enumerate(doc.read_text(encoding="utf-8").splitlines(), 1):
            for destino in _LINK.findall(linha):
                alvo = destino.split("#", 1)[0].strip()
                if not alvo:
                    continue  # link so de ancora dentro do proprio arquivo
                if not (doc.parent / alvo).resolve().exists():
                    rel = doc.relative_to(_RAIZ).as_posix()
                    quebrados.append(f"{rel}:{numero} -> {alvo}")
    assert not quebrados, "links relativos que nao resolvem:\n  " + "\n  ".join(quebrados)


# ------------------------------------------------- orcamento do CLAUDE.md

# 2026-08-19: o arquivo chegou a 54.852 bytes carregados em TODA sessao — 88%
# deles em `Current state` (volatil), `Conventions` (estavel, especifico de area)
# e `Don't do`. Separar por volatilidade derrubou pra ~17,7 KB. O teto existe pra
# que a separacao nao seja desfeita por acumulo: cada sessao acrescenta um pouco,
# e sem limite o arquivo volta ao que era em poucos meses (foi o que aconteceu).
_ORCAMENTO_CLAUDE_MD = 24_000


def test_claude_md_cabe_no_orcamento() -> None:
    """CLAUDE.md entra inteiro em toda sessao — cada byte e imposto de contexto."""
    tamanho = (_RAIZ / "CLAUDE.md").stat().st_size
    assert tamanho <= _ORCAMENTO_CLAUDE_MD, (
        f"CLAUDE.md tem {tamanho} bytes (teto {_ORCAMENTO_CLAUDE_MD}). O conteudo novo "
        "provavelmente pertence a docs/convencoes/<area>.md (convencao estavel) ou a "
        "docs/operacao/estado-atual.md (estado volatil). Subir o teto e a ultima opcao: "
        "ele existe porque este arquivo ja chegou a 54.852 bytes por acumulo."
    )


def test_tabela_de_roteamento_aponta_pras_convencoes() -> None:
    """Se o CLAUDE.md nao rotear, o conteudo movido fica inalcancavel."""
    texto = (_RAIZ / "CLAUDE.md").read_text(encoding="utf-8")
    for area in ("nucleo", "painel", "testes", "dados", "processo"):
        assert f"docs/convencoes/{area}.md" in texto, (
            f"CLAUDE.md nao aponta pra convencoes/{area}.md — quem precisar dela nao acha"
        )
    assert "docs/operacao/estado-atual.md" in texto


# --------------------------- os dois pontos de entrada nao podem mentir

# Reivindicacoes que o codigo parou de honrar em 2026-08-11 e que sobreviveram
# na doc: o F99 pegou no CLAUDE.md, e o README seguiu dizendo "Tailwind (CDN)"
# por mais oito dias. Doc de entrada que mente instrui a escrever codigo que o
# browser bloqueia — o texto so vale como narrativa historica (handoff), nunca
# como descricao do presente. Por isso o escopo e SO README e CLAUDE.md.
_REIVINDICACOES_MORTAS = (
    "Tailwind (CDN)",
    "Tailwind via CDN",
    "Tailwind/HTMX via CDN",
    "cdn.tailwindcss.com",
)


def test_pontos_de_entrada_nao_afirmam_tailwind_por_cdn() -> None:
    """O Play CDN foi aposentado em 2026-08-11; o CSS e gerado offline."""
    ofensores: list[str] = []
    for nome in ("README.md", "CLAUDE.md"):
        texto = (_RAIZ / nome).read_text(encoding="utf-8")
        for numero, linha in enumerate(texto.splitlines(), 1):
            for morta in _REIVINDICACOES_MORTAS:
                if morta in linha:
                    ofensores.append(f"{nome}:{numero} ({morta!r})")
    assert not ofensores, (
        "ponto de entrada afirmando que o Tailwind vem de CDN: "
        + "; ".join(ofensores)
        + " — o CSS e gerado offline por scripts/build_tailwind.py e commitado"
    )
