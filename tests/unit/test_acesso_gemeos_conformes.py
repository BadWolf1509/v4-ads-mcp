"""Conformidade dos repositórios de acesso gêmeos (Google x Meta).

`manager_account_access.py` e `manager_meta_account_access.py` são a mesma
máquina de estados (grant / revogação soft / gate) escrita duas vezes. A classe
de bug que isso gera é o F167: uma cláusula `ON CONFLICT` corrigida num gêmeo e
esquecida no outro (F128 corrigiu `access_level` nos dois por rodadas
diferentes). Este teste compara, função a função, o SQL e os defaults dos dois
lados depois de normalizar o que muda POR DESIGN (nome de tabela, de coluna, de
parâmetro e espaço em branco).

Regra de uso: diferença nova entre os gêmeos FALHA. Diferença deliberada entra
em `_DIVERGENCIAS_REGISTRADAS` com o motivo; quando o gêmeo é alinhado, a
entrada tem que sair (`test_registro_descreve_a_realidade`). O registro é lido
pela task que unificar o núcleo de escrita dos dois (G1).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from tests.unit import _guard_harness as h

_REPOS = h.SRC / "db" / "repositories"
_GOOGLE = _REPOS / "manager_account_access.py"
_META = _REPOS / "manager_meta_account_access.py"

_GEMEOS = (
    "grant",
    "grant_all_active",
    "revoke",
    "list_accounts_for_manager",
    "can_manager_access",
    "bulk_grant",
    "copy_access",
)

# função -> motivo. Só encolhe: entrada nova exige decisão consciente.
_DIVERGENCIAS_REGISTRADAS: dict[str, str] = {
    "grant_all_active": (
        "decisão pendente do Wellington (re-concessão atualiza quem e quando concedeu?): "
        "o ON CONFLICT do Meta também seta `granted_at = now()` e "
        "`granted_by = EXCLUDED.granted_by`, o do Google só `access_level`, "
        "`revoked_at` e `revoked_reason` (F167)"
    ),
    "revoke": (
        "valor gravado no banco e lido pelas filas; unificar é decisão pendente: "
        "motivo padrão `admin_revoked` (Google, ADMIN_REVOKED_REASON) × `manual` (Meta)"
    ),
    "can_manager_access": (
        "ordem equivalente dos predicados do WHERE: Google "
        "`a.is_active = true AND m.revoked_at IS NULL`, Meta "
        "`m.revoked_at IS NULL AND a.is_active = true` (mesmo conjunto, AND comutativo)"
    ),
}

# Meta -> Google. A ordem importa: nomes mais longos antes dos que os contêm.
_RENOMEAR_META_PARA_GOOGLE: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(rf"\b{antigo}\b"), novo)
    for antigo, novo in (
        ("manager_meta_account_access", "manager_account_access"),
        ("meta_ad_accounts", "google_ads_accounts"),
        ("ad_account_ids", "customer_ids"),
        ("ad_account_id", "customer_id"),
        ("account_name", "descriptive_name"),
    )
)


def _normalizar(texto: str, *, meta: bool) -> str:
    if meta:
        for padrao, novo in _RENOMEAR_META_PARA_GOOGLE:
            texto = padrao.sub(novo, texto)
    return re.sub(r"\s+", " ", texto).strip()


def _funcao(arv: ast.Module, nome: str, origem: Path) -> ast.FunctionDef | ast.AsyncFunctionDef:
    achadas = [f for f in h.funcoes(arv) if f.name == nome]
    if len(achadas) != 1:
        raise AssertionError(f"{h.rel(origem)}: esperava 1 `{nome}`, achei {len(achadas)}")
    return achadas[0]


def _strings_da_funcao(fn: ast.FunctionDef | ast.AsyncFunctionDef, origem: Path) -> list[str]:
    """Textos lógicos de todo literal string do corpo (SQL, f-string, literais
    concatenados), na ordem do código, SEM o docstring. Zero literais levanta:
    um scanner que não achou SQL não comparou nada."""
    corpo = list(fn.body)
    if (
        corpo
        and isinstance(corpo[0], ast.Expr)
        and isinstance(corpo[0].value, ast.Constant)
        and isinstance(corpo[0].value.value, str)
    ):
        corpo = corpo[1:]
    achados: list[str] = []
    for stmt in corpo:
        achados.extend(h._texto_logico(no) for no in h._literais_de_string(stmt))
    if not achados:
        raise h.EscopoVazioError(
            f"{h.rel(origem)}: `{fn.name}` sem nenhum literal string no corpo — "
            "o scanner não achou o SQL, e comparar vazio com vazio passa por vacuidade."
        )
    return achados


def _constantes_do_modulo(arv: ast.Module) -> dict[str, object]:
    constantes: dict[str, object] = {}
    for no in arv.body:
        if (
            isinstance(no, ast.Assign)
            and len(no.targets) == 1
            and isinstance(no.targets[0], ast.Name)
            and isinstance(no.value, ast.Constant)
        ):
            constantes[no.targets[0].id] = no.value.value
    return constantes


def _assinatura(
    fn: ast.FunctionDef | ast.AsyncFunctionDef, constantes: dict[str, object], *, meta: bool
) -> list[str]:
    """`nome[=default]` por parâmetro, na ordem, com nome normalizado e default
    resolvido contra as constantes do módulo (`ADMIN_REVOKED_REASON` -> valor)."""
    a = fn.args

    def default(no: ast.expr | None) -> str:
        if no is None:
            return ""
        if isinstance(no, ast.Constant):
            valor: object = no.value
        elif isinstance(no, ast.Name) and no.id in constantes:
            valor = constantes[no.id]
        else:
            return "=" + ast.unparse(no)
        return "=" + repr(valor)

    posicionais = [*a.posonlyargs, *a.args]
    defaults_pos: list[ast.expr | None] = [None] * (len(posicionais) - len(a.defaults))
    defaults_pos += list(a.defaults)
    itens: list[str] = []
    for arg, d in zip(posicionais, defaults_pos, strict=True):
        itens.append(_normalizar(arg.arg, meta=meta) + default(d))
    itens.append("*")
    for arg, d in zip(a.kwonlyargs, a.kw_defaults, strict=True):
        itens.append(_normalizar(arg.arg, meta=meta) + default(d))
    return itens


def _diferencas(nome: str) -> list[str]:
    arv_g, arv_m = h.arvore(_GOOGLE), h.arvore(_META)
    fn_g, fn_m = _funcao(arv_g, nome, _GOOGLE), _funcao(arv_m, nome, _META)
    diffs: list[str] = []

    ass_g = _assinatura(fn_g, _constantes_do_modulo(arv_g), meta=False)
    ass_m = _assinatura(fn_m, _constantes_do_modulo(arv_m), meta=True)
    if ass_g != ass_m:
        diffs.append(f"assinatura/defaults: google={ass_g} meta={ass_m}")

    sql_g = [_normalizar(s, meta=False) for s in _strings_da_funcao(fn_g, _GOOGLE)]
    sql_m = [_normalizar(s, meta=True) for s in _strings_da_funcao(fn_m, _META)]
    if len(sql_g) != len(sql_m):
        diffs.append(f"nº de literais: google={len(sql_g)} meta={len(sql_m)}")
    for i, (g, m) in enumerate(zip(sql_g, sql_m, strict=False)):
        if g != m:
            diffs.append(f"literal #{i}: google={g!r} meta(normalizado)={m!r}")
    return diffs


def test_escopo_dos_gemeos_nao_vazio() -> None:
    """Os dois arquivos existem e cada um dos 7 gêmeos tem SQL (não vacuidade)."""
    for caminho in (_GOOGLE, _META):
        assert caminho.is_file(), h.rel(caminho)
    assert len(_GEMEOS) == 7
    for nome in _GEMEOS:
        for caminho in (_GOOGLE, _META):
            assert _strings_da_funcao(_funcao(h.arvore(caminho), nome, caminho), caminho)


def test_scanner_de_sql_nao_passa_por_vacuidade() -> None:
    """Função sem literal levanta `EscopoVazioError` em vez de devolver []."""
    arv = ast.parse('async def f():\n    """doc"""\n    return 1\n')
    fn = arv.body[0]
    assert isinstance(fn, ast.AsyncFunctionDef)
    with pytest.raises(h.EscopoVazioError):
        _strings_da_funcao(fn, _GOOGLE)


@pytest.mark.parametrize("nome", [n for n in _GEMEOS if n not in _DIVERGENCIAS_REGISTRADAS])
def test_gemeos_iguais_fora_do_registrado(nome: str) -> None:
    diffs = _diferencas(nome)
    assert not diffs, (
        f"`{nome}` divergiu entre manager_account_access e manager_meta_account_access "
        "(classe F167: cláusula corrigida num gêmeo e não no outro). Alinhe o gêmeo ou, se a "
        "diferença for deliberada, registre em _DIVERGENCIAS_REGISTRADAS com o motivo:\n  "
        + "\n  ".join(diffs)
    )


def test_registro_descreve_a_realidade() -> None:
    desconhecidas = set(_DIVERGENCIAS_REGISTRADAS) - set(_GEMEOS)
    assert not desconhecidas, f"registro cita função que não é gêmea: {sorted(desconhecidas)}"
    obsoletas = [n for n in _DIVERGENCIAS_REGISTRADAS if not _diferencas(n)]
    assert not obsoletas, (
        f"entradas registradas que já não divergem (remova do registro): {obsoletas}"
    )
