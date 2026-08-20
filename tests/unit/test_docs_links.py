"""Link relativo quebrado na documentacao viva.

A doc deste repo E a memoria dele: o CLAUDE.md aponta pro handoff, que aponta
pro catalogo, que aponta pro runbook arquivado. Sao 27 links so pro _archive.
Um link morto nao falha nada — o leitor (humano ou agente) simplesmente nao
chega no "porque", e o custo aparece semanas depois, na forma de alguem
refazendo uma decisao ja tomada.

Escopo: os .md da raiz e os de `docs/operacao` e `docs/superpowers`. O
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
    for pasta in ("docs/operacao", "docs/superpowers"):
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
