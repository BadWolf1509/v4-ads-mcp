"""Nenhuma regra `Don't` se perdeu ao sair do CLAUDE.md para os arquivos roteados.

A separacao de 2026-09-22 moveu 37 das 45 **bullets** do `Don't do` para
`docs/convencoes/`. O `Don't do` tem 45 bullets mas 63 **claúsulas** (regras):
13 bullets carregam 2+ claúsulas cada. Extrair uma ANCORA por BULLET deixa
17 claúsulas SEM cobertura propria.

Consequencia: na Task 7, ao APAGAR um bullet inteiro, essas 17 sub-regras
sumiram sem que nada acusasse — nao estao na lista de ancoras, entao nada
as conta.

Solucao: 62 ancoras (45 originais + 17 sub-regras que dividiam bullet).
Das 63 claúsulas, 62 tem ancora unica; 1 claúsula (Don't chamar SDK Google
fora de run_blocking, bullet 1) e coberta de graça pela ancora `run_blocking`
que aparece nos dois bullets. Por isso 62 ancoras bastam.

Cada regra e identificada por uma ANCORA (um trecho distintivo + sua CONTAGEM).
Por que contagem (nao presenca)? Porque 17 das 62 ancoras ja vivem naturalmente
em `docs/convencoes/` — aqueles arquivos falam dos mesmos identificadores por
conta propria (ex: `_CSP_POLICY` em painel.md porque fala de CSP). Para essas,
presenca nao basta: apagar do CLAUDE.md sem mover nao seria detectado, porque o
token continua no destino.

Contagem fecha o buraco: MOVER mantem o total (sai de um arquivo, entra noutro);
APAGAR sem mover derruba. O piso e medido contra o estado PRE-SEPARACAO, nunca
estimado.

Se um teste aqui ficar vermelho, uma regra foi APAGADA sem chegar ao destino.
NAO baixe o piso — ache a regra.
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
    # --- 17 sub-regras que dividiam bullet com outra e nao tinham ancora
    # propria (Ruling 2, 22/09). 45 bullets carregam 61 regras; extrair uma
    # ancora por BULLET deixava 17 sem cobertura, e a Task 7 as levaria junto
    # com o bullet sem que nada acusasse.
    "gaql_string_literal",  # do bullet 1
    "pool/cliente/logger",  # do bullet 1
    "LIMIT",  # do bullet 3
    "params=",  # do bullet 3
    "push sem `python scripts",  # do bullet 5
    "asserir o ADJACENTE",  # do bullet 2
    "coluna sem alias",  # do bullet 12
    "pin do Tailwind",  # do bullet 14
    "<link>",  # do bullet 14
    "aplicar gzip",  # do bullet 15
    "{% block head_extra %}",  # do bullet 15
    "3 Cloud Run Jobs",  # do bullet 16
    "check bloqueante",  # do bullet 17
    "dict opcional",  # do bullet 22
    "aria-label",  # do bullet 24
    "<th>",  # do bullet 27
    "<table>",  # do bullet 43
)

# Quantas vezes cada ancora aparece na uniao HOJE, antes da separacao.
# Presenca nao basta: 17 destas ancoras ja vivem em `docs/convencoes/`
# porque aqueles arquivos falam dos mesmos identificadores por conta
# propria. Para essas, "a ancora existe" fica verde mesmo que a regra
# tenha sido APAGADA do CLAUDE.md sem chegar ao destino.
#
# Contagem fecha o buraco: MOVER mantem o total (sai de um arquivo, entra
# noutro); APAGAR sem mover derruba. O piso e medido, nunca estimado.
PISO_DE_OCORRENCIAS = {
    "best_effort": 4,
    "git checkout": 2,
    "run_with_reconnect": 4,
    "validate_gaql": 5,
    "check_pre_push.py | tail && git commit": 1,
    "gh run view <id> --json conclusion": 2,
    "⬜ pending": 1,
    "classificador de auto mode": 1,
    "ci.yml": 2,
    "build_client_for_manager": 4,
    "_CSP_POLICY": 3,
    "conn.cursor(...)": 2,
    "pool.acquire()": 1,
    "python scripts/build_tailwind.py": 3,
    "--v4-gray-300": 2,
    "--universal": 3,
    "por ordem de criação": 1,
    "run_blocking": 3,
    "-03:00": 1,
    "change_event": 1,
    "datetime.now": 1,
    "mgr:<uuid>": 3,
    "blast_radius.classify": 1,
    "?v={{ asset_version }}": 2,
    "_CSRF_EXEMPT_ROUTES": 2,
    "hx-post": 3,
    'role="button"': 1,
    "onclick=": 1,
    "search_input": 1,
    "pyproject.toml": 2,
    "error_envelope": 1,
    "AttributeError": 1,
    "SQL cru sem extremo cuidado": 1,
    "superpowers:brainstorming": 2,
    "arquivos OVERLAPPING": 1,
    "per-value empirical probe": 1,
    "make_capture_client": 5,
    "oneOf/allOf/anyOf": 1,
    "facebook_business": 3,
    "is_allowed_email": 1,
    "{{ button() }}": 1,
    "sessions_revoke": 2,
    "request.query_params": 1,
    "ads_get_field_context": 5,
    "pipe PowerShell": 1,
    "gaql_string_literal": 2,
    "pool/cliente/logger": 1,
    "LIMIT": 2,
    "params=": 1,
    "push sem `python scripts": 1,
    "asserir o ADJACENTE": 1,
    "coluna sem alias": 1,
    "pin do Tailwind": 1,
    "<link>": 4,
    "aplicar gzip": 1,
    "{% block head_extra %}": 3,
    "3 Cloud Run Jobs": 1,
    "check bloqueante": 1,
    "dict opcional": 1,
    "aria-label": 6,
    "<th>": 1,
    "<table>": 1,
}


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
    assert len(ANCORAS) == 62, f"a lista tem {len(ANCORAS)} ancoras, esperava 62"
    assert len(set(ANCORAS)) == 62, "ha ancora duplicada — ela deixa de identificar UMA regra"
    assert len(_uniao()) > 40_000, "uniao pequena demais: algum arquivo nao foi lido"
    assert set(PISO_DE_OCORRENCIAS) == set(ANCORAS), (
        "piso e ancoras divergiram — toda ancora precisa de piso medido"
    )


def test_nenhuma_regra_se_perdeu() -> None:
    texto = _uniao()
    perdidas = [
        (i, a, texto.count(a), PISO_DE_OCORRENCIAS[a])
        for i, a in enumerate(ANCORAS, 1)
        if texto.count(a) < PISO_DE_OCORRENCIAS[a]
    ]
    assert not perdidas, (
        "regras que perderam ocorrencia na uniao CLAUDE.md + docs/convencoes/:\n  "
        + "\n  ".join(f"#{i}: {a!r} tem {n}, esperava >= {p}" for i, a, n, p in perdidas)
        + "\nMOVER mantem a contagem. Se caiu, a regra foi APAGADA sem chegar ao destino."
        "\nNAO baixe o piso — ache a regra."
    )
