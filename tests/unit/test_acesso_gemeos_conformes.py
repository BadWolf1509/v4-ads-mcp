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
entrada tem que sair (`test_registro_descreve_a_realidade`).

Duas metades desde a G1 (10/11), quando as cinco escritas foram para o núcleo
`_acesso_comum.py` e os módulos ficaram com funções finas sem SQL:

- **AST**: as assinaturas das sete funções gêmeas (nome, ordem e default de
  cada parâmetro) e o SQL dos dois pares que ficaram FORA do núcleo
  (`list_accounts_for_manager`, `can_manager_access`).
- **Runtime**: o SQL das cinco escritas é CAPTURADO chamando a função fina de
  cada módulo com uma conexão falsa — o que o banco receberia, depois do
  descritor (`GOOGLE`/`META`) interpolado —, com a mesma normalização e o mesmo
  `_DIFERENCAS_ESPERADAS`. Chamar a função FINA (não o núcleo direto) cobre
  também a fiação: o módulo Meta passando o descritor Google, ou um argumento
  trocado, aparece na captura. Cada escrita tem que emitir ao menos um
  statement; entrada vazia não conta (a função pode voltar antes do banco).
"""

from __future__ import annotations

import ast
import asyncio
import dataclasses
import re
from collections import Counter
from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import asynccontextmanager
from pathlib import Path
from types import ModuleType
from typing import Any
from uuid import UUID

import pytest

from src.db.repositories import _acesso_comum
from src.db.repositories import manager_account_access as _mod_google
from src.db.repositories import manager_meta_account_access as _mod_meta
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

# As escritas que delegam ao núcleo (SQL comparado em runtime) e os pares que
# ficaram fora dele por decisão do plano (SQL comparado por AST).
_NO_NUCLEO = ("grant", "grant_all_active", "revoke", "bulk_grant", "copy_access")
_FORA_DO_NUCLEO = ("list_accounts_for_manager", "can_manager_access")

# função -> motivo. Só encolhe: entrada nova exige decisão consciente.
_DIVERGENCIAS_REGISTRADAS: dict[str, str] = {
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


def _constantes_do_modulo(
    arv: ast.Module, *, raiz: Path = h.RAIZ, _visitados: frozenset[Path] = frozenset()
) -> dict[str, object]:
    """Nome de topo -> valor literal, seguindo `from src.x import NOME [as alias]`.

    O default `reason=ADMIN_REVOKED_REASON` tem que virar o VALOR gravado no
    banco (`'admin_revoked'`) também quando a constante mora em outro módulo:
    a task F4 a muda para `src/db/repositories/motivos.py` e a reexporta, e sem
    seguir o import o B2 passaria a comparar o NOME da constante, não o valor.
    A resolução é recursiva (reexportação de reexportação) e só de topo de
    módulo, como o Python avalia um default; ciclo de import para no visitado.
    """
    constantes: dict[str, object] = {}
    for no in arv.body:
        if (
            isinstance(no, ast.ImportFrom)
            and no.level == 0
            and (no.module or "").startswith("src.")
        ):
            arquivo = h._arquivo_do_modulo(no.module or "", raiz)
            if arquivo is None or arquivo.resolve() in _visitados:
                continue
            origem = _constantes_do_modulo(
                h.arvore(arquivo), raiz=raiz, _visitados=_visitados | {arquivo.resolve()}
            )
            for a in no.names:
                if a.name in origem:
                    constantes[a.asname or a.name] = origem[a.name]
        elif (
            isinstance(no, ast.Assign)
            and len(no.targets) == 1
            and isinstance(no.targets[0], ast.Name)
            and isinstance(no.value, ast.Constant)
        ):
            constantes[no.targets[0].id] = no.value.value
        elif (
            isinstance(no, ast.AnnAssign)
            and isinstance(no.target, ast.Name)
            and isinstance(no.value, ast.Constant)
        ):
            constantes[no.target.id] = no.value.value
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


_SEPARADOR = re.compile(
    r",\s+|\s+AND\s+|\s+(?=(?:SELECT|FROM|WHERE|VALUES|ON CONFLICT|SET|JOIN|INNER JOIN|ORDER BY)\b)"
)


def _fragmentos(texto: str) -> list[str]:
    """Quebra o texto normalizado em cláusulas (vírgula e AND fora de parênteses,
    mais as palavras-chave de cláusula). Dá a granularidade que a diferença
    esperada precisa: uma linha de `SET` ou um predicado de `WHERE` por item."""
    mascarado: list[str] = []
    profundidade = 0
    for c in texto:
        if c == "(":
            profundidade += 1
        elif c == ")":
            profundidade -= 1
        mascarado.append("\x01" if c == "," and profundidade > 0 else c)
    partes = _SEPARADOR.split("".join(mascarado))
    return [p.replace("\x01", ",").strip() for p in partes if p.strip()]


def _comparar(g: list[str], m: list[str], rotulo: str) -> set[str]:
    """Diferença entre duas listas de itens: o que só um lado tem (multiconjunto,
    então reordenar não conta) e, quando os itens são os mesmos em outra ordem,
    um marcador de reordenação — assim troca de coluna do INSERT não passa."""
    cg, cm = Counter(g), Counter(m)
    diffs = {f"{rotulo} só google: {x}" for x in (cg - cm)}
    diffs |= {f"{rotulo} só meta: {x}" for x in (cm - cg)}
    if not diffs and g != m:
        diffs.add(f"{rotulo}: mesmos fragmentos em ordem diferente")
    return diffs


@dataclasses.dataclass(frozen=True)
class _Evento:
    metodo: str  # execute / executemany / fetch / fetchrow / fetchval / BEGIN / COMMIT
    sql: str
    args: tuple[Any, ...]


_MARCADORES = frozenset({"BEGIN", "COMMIT"})


class _ConexaoFalsa:
    """Grava o que o banco receberia. Devolve tags e linhas neutras — o bastante
    para a função terminar; o valor devolvido não é o que se compara aqui."""

    def __init__(self) -> None:
        self.eventos: list[_Evento] = []

    async def execute(self, sql: str, *args: Any) -> str:
        self.eventos.append(_Evento("execute", sql, args))
        return "INSERT 0 1"

    async def executemany(self, sql: str, rows: Any) -> None:
        self.eventos.append(_Evento("executemany", sql, (list(rows),)))

    async def fetch(self, sql: str, *args: Any) -> list[Any]:
        self.eventos.append(_Evento("fetch", sql, args))
        return []

    async def fetchrow(self, sql: str, *args: Any) -> None:
        self.eventos.append(_Evento("fetchrow", sql, args))

    async def fetchval(self, sql: str, *args: Any) -> int:
        self.eventos.append(_Evento("fetchval", sql, args))
        return 0

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        self.eventos.append(_Evento("BEGIN", "", ()))
        yield
        self.eventos.append(_Evento("COMMIT", "", ()))


_ID_GESTOR, _ID_ADMIN, _ID_DESTINO = UUID(int=1), UUID(int=2), UUID(int=3)

# Entrada de cada escrita, nos nomes do Google; o Meta recebe os mesmos VALORES
# com os nomes do seu lado (`_KWARG_META`). Não vazia: `bulk_grant([])` volta
# antes de falar com o banco e não provaria nada.
_ENTRADAS: dict[str, dict[str, Any]] = {
    "grant": {"manager_id": _ID_GESTOR, "customer_id": "1111111111", "granted_by": _ID_ADMIN},
    "grant_all_active": {"manager_id": _ID_GESTOR, "granted_by": _ID_ADMIN},
    "revoke": {"manager_id": _ID_GESTOR, "customer_id": "1111111111"},
    "bulk_grant": {
        "manager_id": _ID_GESTOR,
        "customer_ids": ["1111111111", "2222222222"],
        "granted_by": _ID_ADMIN,
    },
    "copy_access": {
        "from_manager_id": _ID_GESTOR,
        "to_manager_id": _ID_DESTINO,
        "granted_by": _ID_ADMIN,
    },
}
_KWARG_META = {"customer_id": "ad_account_id", "customer_ids": "ad_account_ids"}


def _capturar(nome: str, *, meta: bool) -> list[_Evento]:
    modulo: ModuleType = _mod_meta if meta else _mod_google
    fn: Callable[..., Coroutine[Any, Any, Any]] = getattr(modulo, nome)
    kwargs = {(_KWARG_META.get(k, k) if meta else k): v for k, v in _ENTRADAS[nome].items()}
    conn = _ConexaoFalsa()
    asyncio.run(fn(conn, **kwargs))
    if not [e for e in conn.eventos if e.metodo not in _MARCADORES]:
        raise h.EscopoVazioError(
            f"`{nome}` ({'Meta' if meta else 'Google'}) não emitiu statement nenhum com "
            "entrada não vazia — comparar vazio com vazio passa por vacuidade."
        )
    return conn.eventos


def _diferencas_em_runtime(nome: str) -> set[str]:
    cap_g, cap_m = _capturar(nome, meta=False), _capturar(nome, meta=True)
    diffs = _comparar([e.metodo for e in cap_g], [e.metodo for e in cap_m], "métodos")
    if len(cap_g) != len(cap_m):
        diffs.add(f"nº de eventos: google={len(cap_g)} meta={len(cap_m)}")
    for i, (g, m) in enumerate(zip(cap_g, cap_m, strict=False)):
        diffs |= _comparar(
            _fragmentos(_normalizar(g.sql, meta=False)),
            _fragmentos(_normalizar(m.sql, meta=True)),
            f"statement #{i}",
        )
        if g.args != m.args:
            diffs.add(f"statement #{i}: bind args google={g.args!r} meta={m.args!r}")
    return diffs


def _diferencas(nome: str) -> frozenset[str]:
    arv_g, arv_m = h.arvore(_GOOGLE), h.arvore(_META)
    fn_g, fn_m = _funcao(arv_g, nome, _GOOGLE), _funcao(arv_m, nome, _META)

    ass_g = _assinatura(fn_g, _constantes_do_modulo(arv_g), meta=False)
    ass_m = _assinatura(fn_m, _constantes_do_modulo(arv_m), meta=True)
    diffs = _comparar(ass_g, ass_m, "assinatura")

    if nome in _NO_NUCLEO:
        return frozenset(diffs | _diferencas_em_runtime(nome))

    sql_g = [_normalizar(s, meta=False) for s in _strings_da_funcao(fn_g, _GOOGLE)]
    sql_m = [_normalizar(s, meta=True) for s in _strings_da_funcao(fn_m, _META)]
    if len(sql_g) != len(sql_m):
        diffs.add(f"nº de literais: google={len(sql_g)} meta={len(sql_m)}")
    for i, (g, m) in enumerate(zip(sql_g, sql_m, strict=False)):
        diffs |= _comparar(_fragmentos(g), _fragmentos(m), f"literal #{i}")
    return frozenset(diffs)


def _sql_cru(nome: str, caminho: Path) -> list[str]:
    """O SQL de um lado sem normalizar: capturado (núcleo) ou literal (AST)."""
    if nome in _NO_NUCLEO:
        return [e.sql for e in _capturar(nome, meta=caminho == _META) if e.sql]
    return _strings_da_funcao(_funcao(h.arvore(caminho), nome, caminho), caminho)


# Diferença EXATA esperada por função registrada (o que `_diferencas` mede hoje).
# Mudar o conjunto — para mais OU para menos — falha: um segundo defeito dentro
# de uma função registrada não se esconde atrás do registro.
_DIFERENCAS_ESPERADAS: dict[str, frozenset[str]] = {
    "can_manager_access": frozenset({"literal #0: mesmos fragmentos em ordem diferente"}),
}

_NOMES_GOOGLE = re.compile(
    r"\b(?:customer_ids?|google_ads_accounts|descriptive_name|manager_account_access)\b"
)
_NOMES_META = re.compile(
    r"\b(?:ad_account_ids?|meta_ad_accounts|account_name|manager_meta_account_access)\b"
)


def _publicas_de_topo(caminho: Path) -> set[str]:
    return {
        no.name
        for no in h.arvore(caminho).body
        if isinstance(no, ast.FunctionDef | ast.AsyncFunctionDef) and not no.name.startswith("_")
    }


# Funções públicas com o MESMO nome nos dois módulos que ficam fora da comparação,
# com o motivo. Medido em 10/11: a interseção é `_GEMEOS` mais estas.
_GEMEOS_EXCLUIDOS: dict[str, str] = {
    "restore_for_account": (
        "retorno difere por design: Google devolve `list[str]` (gestores restaurados), "
        "Meta devolve `int` (contagem); cada chamador usa o seu"
    ),
}


def test_todo_par_publico_e_gemeo_ou_excluido() -> None:
    """Função pública nova com o mesmo nome nos dois lados entra em `_GEMEOS` (e é
    comparada) ou em `_GEMEOS_EXCLUIDOS` (com motivo) — não fica de fora calada."""
    em_ambos = _publicas_de_topo(_GOOGLE) & _publicas_de_topo(_META)
    assert not set(_GEMEOS) & set(_GEMEOS_EXCLUIDOS), "função gêmea e excluída ao mesmo tempo"
    assert em_ambos == set(_GEMEOS) | set(_GEMEOS_EXCLUIDOS), (
        f"sem classificação: {sorted(em_ambos - set(_GEMEOS) - set(_GEMEOS_EXCLUIDOS))}; "
        f"listadas sem existir nos dois: {sorted((set(_GEMEOS) | set(_GEMEOS_EXCLUIDOS)) - em_ambos)}"
    )


def test_constante_importada_resolve_ate_o_valor(tmp_path: Path) -> None:
    """Default vindo de `from src... import NOME` (e de reexportação) vira o valor."""
    pacote = tmp_path / "src" / "pkg"
    pacote.mkdir(parents=True)
    (pacote / "motivos.py").write_text('ADMIN_REVOKED_REASON = "admin_revoked"\n', "utf-8")
    (pacote / "reexporta.py").write_text(
        "from src.pkg.motivos import ADMIN_REVOKED_REASON\n", "utf-8"
    )
    arv = ast.parse(
        "from src.pkg.reexporta import ADMIN_REVOKED_REASON\n"
        "from src.pkg.motivos import ADMIN_REVOKED_REASON as MOTIVO\n"
        "LOCAL = 'left_mcc'\n"
        "async def revoke(conn, *, reason: str = ADMIN_REVOKED_REASON, r2: str = MOTIVO): ...\n"
    )
    constantes = _constantes_do_modulo(arv, raiz=tmp_path)
    assert constantes == {
        "ADMIN_REVOKED_REASON": "admin_revoked",
        "MOTIVO": "admin_revoked",
        "LOCAL": "left_mcc",
    }
    fn = arv.body[-1]
    assert isinstance(fn, ast.AsyncFunctionDef)
    assert _assinatura(fn, constantes, meta=False) == [
        "conn",
        "*",
        "reason='admin_revoked'",
        "r2='admin_revoked'",
    ]


def test_escopo_dos_gemeos_nao_vazio() -> None:
    """Os dois arquivos existem e cada um dos gêmeos tem SQL (não vacuidade): os
    de fora do núcleo como literal, os do núcleo como statement capturado."""
    assert set(_NO_NUCLEO) | set(_FORA_DO_NUCLEO) == set(_GEMEOS)
    assert not set(_NO_NUCLEO) & set(_FORA_DO_NUCLEO)
    assert set(_ENTRADAS) == set(_NO_NUCLEO)
    for caminho in (_GOOGLE, _META):
        assert caminho.is_file(), h.rel(caminho)
    for nome in _FORA_DO_NUCLEO:
        for caminho in (_GOOGLE, _META):
            assert _strings_da_funcao(_funcao(h.arvore(caminho), nome, caminho), caminho)
    for nome in _NO_NUCLEO:
        for meta in (False, True):
            assert _capturar(nome, meta=meta)


def test_captura_sem_statement_levanta() -> None:
    """Controle da metade runtime: escrita que volta antes do banco (entrada vazia)
    levanta em vez de passar comparando vazio com vazio."""
    original = _ENTRADAS["bulk_grant"]
    _ENTRADAS["bulk_grant"] = {**original, "customer_ids": []}
    try:
        with pytest.raises(h.EscopoVazioError):
            _capturar("bulk_grant", meta=False)
    finally:
        _ENTRADAS["bulk_grant"] = original


def test_descritores_diferem_so_nos_nomes() -> None:
    """Desde a G0 os dois lados escrevem igual: o descritor só tem nomes, e é nos
    nomes — e só neles — que GOOGLE e META diferem. Divergência de comportamento
    não entra como campo calado: passa pelo registro acima."""
    nomes = {"tabela", "coluna_conta", "inventario"}
    campos = {c.name for c in dataclasses.fields(_acesso_comum.TabelaDeAcesso)}
    assert campos == nomes
    g, m = _acesso_comum.GOOGLE, _acesso_comum.META
    divergentes = {
        c: (getattr(g, c), getattr(m, c)) for c in campos if getattr(g, c) != getattr(m, c)
    }
    assert set(divergentes) == nomes, divergentes


def test_revoke_grava_admin_revoked_nos_dois_lados() -> None:
    """Bind args capturados: o `reason` default que `revoke` grava (decisão de
    10/11, G0: Meta deixou de gravar `manual`)."""
    for meta in (False, True):
        (evento,) = _capturar("revoke", meta=meta)
        assert evento.args == (_ID_GESTOR, "1111111111", "admin_revoked"), (meta, evento.args)


def test_nucleo_so_aceita_os_descritores_do_modulo() -> None:
    """Identificador no SQL só vem dos descritores do núcleo: nome que não é
    identificador simples é recusado na construção, e descritor fora de
    GOOGLE/META é recusado antes de qualquer statement."""
    with pytest.raises(ValueError, match="identificador SQL"):
        _acesso_comum.TabelaDeAcesso(
            tabela="x; DROP TABLE y", coluna_conta="customer_id", inventario="z"
        )
    alheio = _acesso_comum.TabelaDeAcesso(tabela="outra", coluna_conta="c", inventario="i")
    conn = _ConexaoFalsa()
    with pytest.raises(ValueError, match="descritor de acesso desconhecido"):
        asyncio.run(
            _acesso_comum.revoke(
                conn,
                alheio,
                manager_id=_ID_GESTOR,
                conta="1",
                reason="admin_revoked",
            )
        )
    assert conn.eventos == []


@pytest.mark.parametrize("nome", _NO_NUCLEO)
def test_sql_capturado_nao_tem_interpolacao_pendente(nome: str) -> None:
    """O SQL do núcleo é montado só com os campos do descritor: chave solta no
    texto final seria interpolação que não aconteceu (ou que veio de fora)."""
    for meta in (False, True):
        for evento in _capturar(nome, meta=meta):
            assert "{" not in evento.sql and "}" not in evento.sql, (nome, meta, evento.sql)


def test_scanner_de_sql_nao_passa_por_vacuidade() -> None:
    """Função sem literal levanta `EscopoVazioError` em vez de devolver []."""
    arv = ast.parse("async def f():\n    '''doc'''\n    return 1\n")
    fn = arv.body[0]
    assert isinstance(fn, ast.AsyncFunctionDef)
    with pytest.raises(h.EscopoVazioError):
        _strings_da_funcao(fn, _GOOGLE)


@pytest.mark.parametrize("nome", _GEMEOS)
def test_texto_cru_so_tem_os_nomes_do_proprio_lado(nome: str) -> None:
    """A normalização só renomeia o Meta; sem esta checagem, SQL Meta que citasse
    por engano `customer_id`/`google_ads_accounts` passaria como igual."""
    for caminho, proibido, lado in (
        (_GOOGLE, _NOMES_META, "Google"),
        (_META, _NOMES_GOOGLE, "Meta"),
    ):
        for texto in _sql_cru(nome, caminho):
            achados = proibido.findall(texto)
            assert not achados, (
                f"{nome} ({lado}): o SQL cita nome do outro lado {achados}; a normalização "
                "esconderia a troca"
            )


@pytest.mark.parametrize("nome", _GEMEOS)
def test_gemeos_conformes_ao_snapshot(nome: str) -> None:
    esperado = _DIFERENCAS_ESPERADAS.get(nome, frozenset())
    medido = _diferencas(nome)
    assert medido == esperado, (
        f"`{nome}`: diferença entre manager_account_access e manager_meta_account_access "
        "mudou (classe F167: cláusula corrigida num gêmeo e não no outro). Alinhe o gêmeo ou, "
        "se for deliberada, atualize _DIVERGENCIAS_REGISTRADAS e _DIFERENCAS_ESPERADAS.\n"
        f"  novas: {sorted(medido - esperado)}\n  sumiram:{sorted(esperado - medido)}"
    )


def test_registro_descreve_a_realidade() -> None:
    assert set(_DIVERGENCIAS_REGISTRADAS) == set(_DIFERENCAS_ESPERADAS), (
        "_DIVERGENCIAS_REGISTRADAS e _DIFERENCAS_ESPERADAS têm que ter as mesmas chaves"
    )
    desconhecidas = set(_DIVERGENCIAS_REGISTRADAS) - set(_GEMEOS)
    assert not desconhecidas, f"registro cita função que não é gêmea: {sorted(desconhecidas)}"
    obsoletas = [n for n in _DIVERGENCIAS_REGISTRADAS if not _diferencas(n)]
    assert not obsoletas, (
        f"entradas registradas que já não divergem (remova do registro): {obsoletas}"
    )
