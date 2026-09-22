"""Nenhuma regra `Don't` se perdeu ao sair do CLAUDE.md para os arquivos roteados.

A separacao de 2026-09-22 moveu 37 das 45 regras do `Don't do` para
`docs/convencoes/`. Mover texto entre arquivos e uma operacao sem rede: se um
bullet cair no caminho, nada acusa — o CLAUDE.md so fica menor, que e o que se
queria.

Cada regra e identificada por uma ANCORA (um trecho distintivo), nao pelo
texto: o texto e reescrito para caber na voz do arquivo de destino, e comparar
texto daria falso positivo a cada adaptacao legitima. As 45 ancoras foram
extraidas ANTES da separacao e verificadas como unicas.

Se um teste aqui ficar vermelho, uma regra sumiu. NAO ajuste a lista para
passar — ache a regra.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _guard_harness as h  # noqa: E402

# Os seis arquivos onde uma regra pode viver depois da separacao.
_FONTES = ["CLAUDE.md"] + [
    f"docs/convencoes/{n}.md" for n in ("nucleo", "painel", "testes", "dados", "processo")
]

# Uma ancora por regra, na ordem em que apareciam no `Don't do` original.
ANCORAS = (
    "best_effort",  # 1
    "git checkout",  # 2
    "run_with_reconnect",  # 3
    "validate_gaql",  # 4
    "check_pre_push.py | tail && git commit",  # 5
    "gh run view <id> --json conclusion",  # 6
    "⬜ pending",  # 7
    "classificador de auto mode",  # 8
    "ci.yml",  # 9
    "build_client_for_manager",  # 10
    "_CSP_POLICY",  # 11
    "conn.cursor(...)",  # 12
    "pool.acquire()",  # 13
    "python scripts/build_tailwind.py",  # 14
    "--v4-gray-300",  # 15
    "--universal",  # 16
    "por ordem de criação",  # 17
    "run_blocking",  # 18
    "-03:00",  # 19
    "change_event",  # 20
    "datetime.now",  # 21
    "mgr:<uuid>",  # 22
    "blast_radius.classify",  # 23
    "?v={{ asset_version }}",  # 24
    "_CSRF_EXEMPT_ROUTES",  # 25
    "hx-post",  # 26
    'role="button"',  # 27
    "onclick=",  # 28
    "search_input",  # 29
    "pyproject.toml",  # 30
    "error_envelope",  # 31
    "AttributeError",  # 32
    "SQL cru sem extremo cuidado",  # 33
    "superpowers:brainstorming",  # 34
    "arquivos OVERLAPPING",  # 35
    "per-value empirical probe",  # 36
    "make_capture_client",  # 37
    "oneOf/allOf/anyOf",  # 38
    "facebook_business",  # 39
    "is_allowed_email",  # 40
    "{{ button() }}",  # 41
    "sessions_revoke",  # 42
    "request.query_params",  # 43
    "ads_get_field_context",  # 44
    "pipe PowerShell",  # 45
)


def _uniao() -> str:
    """O texto dos seis arquivos, concatenado."""
    return "\n".join((h.RAIZ / nome).read_text(encoding="utf-8") for nome in _FONTES)


def test_o_scan_tem_escopo() -> None:
    """CONTROLE ANTI-VACUIDADE. Um scan que le zero arquivos passa por vacuidade.

    Sem isto, renomear `docs/convencoes/` deixaria a uniao quase vazia e o teste
    de baixo acusaria 45 regras sumidas — ou, se a lista tambem esvaziasse,
    passaria verde varrendo nada.
    """
    faltando = [n for n in _FONTES if not (h.RAIZ / n).exists()]
    assert not faltando, f"arquivo de destino nao existe: {faltando}"
    assert len(ANCORAS) == 45, f"a lista tem {len(ANCORAS)} ancoras, esperava 45"
    assert len(set(ANCORAS)) == 45, "ha ancora duplicada — ela deixa de identificar UMA regra"
    assert len(_uniao()) > 40_000, "uniao pequena demais: algum arquivo nao foi lido"


def test_nenhuma_regra_se_perdeu() -> None:
    texto = _uniao()
    sumidas = [(i, a) for i, a in enumerate(ANCORAS, 1) if a not in texto]
    assert not sumidas, (
        "regras que sumiram da uniao CLAUDE.md + docs/convencoes/:\n  "
        + "\n  ".join(f"#{i}: {a!r}" for i, a in sumidas)
        + "\nNAO remova a ancora da lista — ache a regra."
    )
