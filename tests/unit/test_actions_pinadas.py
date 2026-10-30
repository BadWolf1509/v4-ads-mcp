"""Toda action externa dos workflows e presa por SHA de commit (40 hex).

Tag de action e mutavel: quem controla o repo da action move `v3` para outro
commit e o proximo run executa codigo novo com a identidade do deploy (WIF).
O SHA fecha isso; a tag fica em comentario para o Dependabot `github-actions`
e para quem le. `uses: ./...` (workflow reusavel local) nao conta.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"
_USES = re.compile(r"^\s*(?:-\s*)?uses:\s*(?P<ref>\S+)(?P<resto>.*)$")
_SHA = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")
_TAG_COMENTADA = re.compile(r"#\s*v\d")


def _usos_externos() -> list[tuple[str, int, str, str]]:
    achados = []
    for arq in sorted(_WORKFLOWS.glob("*.yml")):
        for n, linha in enumerate(arq.read_text(encoding="utf-8").splitlines(), 1):
            m = _USES.match(linha)
            if m and not m["ref"].startswith("./"):
                achados.append((arq.name, n, m["ref"], m["resto"]))
    return achados


def test_ha_actions_externas_para_conferir() -> None:
    assert _usos_externos(), "regex nao achou nenhuma `uses:` — o guard virou no-op"


@pytest.mark.parametrize(("arq", "n", "ref", "resto"), _usos_externos())
def test_action_externa_presa_por_sha_com_tag_em_comentario(
    arq: str, n: int, ref: str, resto: str
) -> None:
    assert _SHA.match(ref), f"{arq}:{n} `{ref}` nao esta presa por SHA de 40 hex"
    assert _TAG_COMENTADA.search(resto), f"{arq}:{n} sem a tag em comentario (# vN)"
