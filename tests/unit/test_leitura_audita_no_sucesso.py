"""Toda tool grava trilha de audit no sucesso — inventário por tool (A-01, P0).

Existe porque, até 15/11, sete leituras não gravavam nenhuma linha quando davam
certo: `run_report` e `run_meta_graph_get` só auditam o sucesso com
`audit_this_call=True`, e quem esquecia o opt-in ficava invisível. A lista de
"tools sem uso em 90 dias" que ia pautar a decisão do 02/12 contava essas sete
como zero, sem ter medido nada (A-01 da varredura de 15/11).

`COMO_CADA_TOOL_AUDITA` diz, para cada tool do registry, por onde a linha de
audit sai:

- `executor`: chama `run_report`/`run_meta_graph_get` com `audit_this_call`
  que não é o literal `False`, ou `run_meta_level_performance`, que não tem
  opt-in e audita sempre (o teste `test_executor_sem_opt_in_audita_sempre`
  confere que ele passa `True` adiante).
- `registro_direto`: chama `audit_log.record` no próprio módulo.
- `mutacao`: passa por executor de mutação ou pela pendência (preview grava
  `dry_run=true`; a aplicação grava pelo executor).
- `pendencia`: `apply_change`, que consome a pendência e aplica.
- `delega:<arquivo sob src/>:<função>`: o módulo da tool não tem sinal; a
  função nomeada é quem grava, e `test_delegada_audita_de_fato` confere.

A tabela é lida pelo script de medição (`scripts/medir_uso_tools.py`, T0.4).
Se uma tool mudar de categoria num refactor (P5/P6), a tabela muda junto.
"""

from __future__ import annotations

import ast
import inspect
import shutil
import textwrap
from pathlib import Path

import pytest

from tests.unit import _guard_harness as h

COMO_CADA_TOOL_AUDITA: dict[str, str] = {
    "add_keywords": "mutacao",
    "add_negative_keywords": "mutacao",
    "add_negatives_from_search_terms": "mutacao",
    "apply_audience": "mutacao",
    "apply_change": "pendencia",
    "apply_recommendation": "mutacao",
    "audit_competitor_keywords": "executor",
    "audit_goal_attribution": "executor",
    "audit_orphan_smart_actions": "executor",
    "audit_quality_score": "executor",
    "audit_zombie_keywords": "executor",
    "bulk_pause_by_query": "mutacao",
    "create_ad_group": "mutacao",
    "create_and_link_assets": "mutacao",
    "create_campaign": "mutacao",
    "create_conversion_action": "mutacao",
    "create_conversion_value_rule_set": "mutacao",
    "create_rsa": "mutacao",
    # Grava sob `get_change_history` (A-01): o drift não é separável no audit.
    "detect_drift": "delega:google_ads/change_scan.py:consultar_change_history",
    "dismiss_recommendation": "mutacao",
    "get_account_balance": "executor",
    "get_account_overview": "executor",
    "get_ad_group_performance": "executor",
    "get_ad_performance": "executor",
    "get_ad_schedule": "executor",
    "get_assets": "executor",
    "get_audience_performance": "executor",
    "get_budget_pacing": "executor",
    "get_campaign_performance": "executor",
    "get_change_history": "delega:google_ads/change_scan.py:consultar_change_history",
    "get_conversion_actions": "executor",
    "get_device_performance": "executor",
    "get_experiments": "executor",
    "get_funnel_metrics": "executor",
    "get_geo_performance": "executor",
    "get_hourly_performance": "executor",
    "get_keyword_metrics": "delega:google_ads/keyword_planning.py:run_keyword_planning",
    "get_keyword_performance": "executor",
    "get_my_audit_log": "registro_direto",
    "get_my_rate_limit_status": "registro_direto",
    "get_negative_keywords_audit": "executor",
    "get_performance_breakdown": "executor",
    "get_recommendations": "executor",
    "get_search_terms_report": "executor",
    "get_top_keywords_creatives": "executor",
    "import_offline_conversions": "mutacao",
    "list_gaql_resources": "registro_direto",
    "list_my_accounts": "registro_direto",
    "meta_get_account_balance": "executor",
    "meta_get_account_overview": "executor",
    "meta_get_ad_performance": "executor",
    "meta_get_ad_preview": "delega:meta_ads/criativos.py:gerar_previa",
    "meta_get_ad_set_performance": "executor",
    "meta_get_budget_pacing": "executor",
    "meta_get_campaign_performance": "executor",
    "meta_get_change_history": "delega:meta_ads/historico.py:listar_atividades",
    "meta_get_creatives": "delega:meta_ads/criativos.py:listar_criativos",
    "meta_get_delivery_estimate": "delega:meta_ads/segmentacao.py:estimar_entrega",
    "meta_get_entities": "delega:meta_ads/colecao.py:ler_colecao",
    "meta_get_pages": "delega:meta_ads/colecao.py:ler_colecao",
    "meta_get_performance_breakdown": "executor",
    "meta_list_my_ad_accounts": "registro_direto",
    "meta_search_targeting": "delega:meta_ads/segmentacao.py:buscar_segmentacao",
    "plan_keyword_ideas": "delega:google_ads/keyword_planning.py:run_keyword_planning",
    "remove_ad": "mutacao",
    "remove_asset_link": "mutacao",
    "remove_audience": "mutacao",
    "remove_negative_keywords": "mutacao",
    "run_gaql": "delega:google_ads/reports.py:execute_gaql_raw",
    "update_ad_group_bid": "mutacao",
    "update_ad_group_status": "mutacao",
    "update_ad_schedule": "mutacao",
    "update_ad_status": "mutacao",
    "update_campaign_bidding": "mutacao",
    "update_campaign_budget": "mutacao",
    "update_campaign_status": "mutacao",
    "update_conversion_action": "mutacao",
    "update_keyword_bid": "mutacao",
    "update_keyword_status": "mutacao",
    "update_recommendation_subscription": "mutacao",
    "update_rsa": "mutacao",
    "upload_customer_match_list": "mutacao",
    "validate_gaql": "registro_direto",
}

_EXECUTORES_DE_MUTACAO = (
    "run_mutation",
    "run_conversion_upload",
    "run_offline_user_data_job",
    "run_recommendation_action",
    "emitir_preview",
    "create_pending",
    # Helper que escolhe entre `run_mutation` e `emitir_preview` (T5.1, 15/11):
    # as tools de status chamam so ele, e continuam `mutacao`.
    "aplicar_ou_pedir_confirmacao",
)

# Executor de leitura com opt-in de audit (`audit_this_call`, default False).
_EXECUTORES_COM_OPT_IN = ("run_report", "run_meta_graph_get")
# Executor de leitura sem opt-in: audita em toda chamada (conferido abaixo).
_EXECUTORES_SEM_OPT_IN = ("run_meta_level_performance",)


def _chamadas(arv: ast.Module, alvo: str) -> list[ast.Call]:
    """Toda chamada a `alvo` no módulo, por nome, atributo ou alias de import."""
    nomes = h.nomes_locais(arv, alvo)
    achadas: list[ast.Call] = []
    for no in ast.walk(arv):
        if not isinstance(no, ast.Call):
            continue
        f = no.func
        if (isinstance(f, ast.Name) and f.id in nomes) or (
            isinstance(f, ast.Attribute) and f.attr in nomes
        ):
            achadas.append(no)
    return achadas


def _opta_por_audit(chamada: ast.Call) -> bool:
    """`audit_this_call` presente e diferente do literal `False`.

    Ausente vale o default (`False`). Um valor não literal (variável, expressão)
    conta como opt-in: o scanner não executa código, e o caso real é a
    variável que o chamador repassa.
    """
    for kw in chamada.keywords:
        if kw.arg == "audit_this_call":
            return not (isinstance(kw.value, ast.Constant) and kw.value.value is False)
    return False


def _chama_audit_log_record(arv: ast.Module, escopo: ast.AST | None = None) -> bool:
    """`audit_log.record(...)` — o atributo `record` sobre o nome `audit_log`
    (ou alias dele). Um `.record()` qualquer, de outro objeto, não conta."""
    nomes = h.nomes_locais(arv, "audit_log")
    nos = h.nos_do_corpo_proprio(escopo) if escopo is not None else ast.walk(arv)
    for no in nos:
        if (
            isinstance(no, ast.Call)
            and isinstance(no.func, ast.Attribute)
            and no.func.attr == "record"
            and isinstance(no.func.value, ast.Name)
            and no.func.value.id in nomes
        ):
            return True
    return False


def _delega_a_encerrar_execucao(arv: ast.Module, escopo: ast.AST) -> bool:
    """`encerrar_execucao(..., montar_audit=<montador>)` no corpo próprio (P6, 15/11).

    Os executores Google passaram a gravar o audit por `encerrar_execucao`
    (`src/governance/execucao.py`), que chama `audit_log.record` com o que o
    montador devolve — `test_encerrar_execucao_grava_o_audit` confere esse elo.
    Montador ausente, `None` literal ou condicional que pode dar `None` NÃO
    conta: é o caminho que não audita (`run_report` sem opt-in).
    """
    nomes = h.nomes_locais(arv, "encerrar_execucao")
    for no in h.nos_do_corpo_proprio(escopo):
        if not isinstance(no, ast.Call):
            continue
        f = no.func
        if not (
            (isinstance(f, ast.Name) and f.id in nomes)
            or (isinstance(f, ast.Attribute) and f.attr in nomes)
        ):
            continue
        for kw in no.keywords:
            if kw.arg == "montar_audit" and not any(
                isinstance(n, ast.Constant) and n.value is None for n in ast.walk(kw.value)
            ):
                return True
    return False


def _sinais(arquivo: Path) -> set[str]:
    """Os sinais de audit do módulo do handler (AST, sem executar)."""
    arv = h.arvore(arquivo)
    sinais: set[str] = set()
    if any(h.chama(arv, m, arv=arv) for m in _EXECUTORES_DE_MUTACAO):
        sinais.add("mutacao")
    if h.chama(arv, "consume", arv=arv):
        sinais.add("pendencia")
    if _chama_audit_log_record(arv):
        sinais.add("registro_direto")
    com_opt_in = [c for e in _EXECUTORES_COM_OPT_IN for c in _chamadas(arv, e)]
    sem_opt_in = [c for e in _EXECUTORES_SEM_OPT_IN for c in _chamadas(arv, e)]
    if com_opt_in or sem_opt_in:
        if sem_opt_in or any(_opta_por_audit(c) for c in com_opt_in):
            sinais.add("executor")
        else:
            sinais.add("executor_sem_audit")
    return sinais


def _categoria(sinais: set[str]) -> str | None:
    """Precedência `mutacao > pendencia > registro_direto | executor`.

    `executor_sem_audit` só sai quando nada acima dele apareceu: numa mutação, a
    leitura de pré-voo sem opt-in não é a linha que conta. `None` = módulo sem
    sinal nenhum, que só passa com `delega:` na tabela.
    """
    for cat in ("mutacao", "pendencia", "registro_direto", "executor", "executor_sem_audit"):
        if cat in sinais:
            return cat
    return None


def _modulos_das_tools() -> dict[str, Path]:
    from src.mcp.tools._registry import all_tools, import_all_tools

    import_all_tools()
    modulos = {t.name: Path(inspect.getsourcefile(t.handler) or "") for t in all_tools()}
    if not modulos:
        raise h.EscopoVazioError("registry vazio: o guard não varreria nenhuma tool")
    return modulos


def test_tabela_cobre_o_registry_inteiro() -> None:
    registry = set(_modulos_das_tools())
    tabela = set(COMO_CADA_TOOL_AUDITA)
    assert tabela == registry, (
        f"só no código: {sorted(registry - tabela)}; só na tabela: {sorted(tabela - registry)}"
    )


def test_categoria_derivada_bate_com_a_tabela() -> None:
    divergentes: dict[str, tuple[str | None, str]] = {}
    for nome, arquivo in _modulos_das_tools().items():
        esperado = COMO_CADA_TOOL_AUDITA.get(nome)
        if esperado is None or esperado.startswith("delega:"):
            continue
        derivada = _categoria(_sinais(arquivo))
        if derivada != esperado:
            divergentes[nome] = (derivada, esperado)
    assert not divergentes, f"(derivada, tabela) por tool: {divergentes}"


def _delegadas() -> list[tuple[str, str, str]]:
    achadas = []
    for nome, cat in sorted(COMO_CADA_TOOL_AUDITA.items()):
        if cat.startswith("delega:"):
            _, arquivo, funcao = cat.split(":")
            achadas.append((nome, arquivo, funcao))
    assert achadas, "nenhuma delegada na tabela: o teste passaria por vacuidade"
    return achadas


@pytest.mark.parametrize(("tool", "arquivo", "funcao"), _delegadas())
def test_delegada_audita_de_fato(tool: str, arquivo: str, funcao: str) -> None:
    caminho = h.SRC / arquivo
    assert caminho.is_file(), f"{tool}: {arquivo} não existe sob src/"
    arv = h.arvore(caminho)
    defs = [f for f in h.funcoes(arv) if f.name == funcao]
    assert defs, f"{tool}: {funcao} não existe em src/{arquivo}"
    for fn in defs:
        if _chama_audit_log_record(arv, fn):
            return
        if h.chama_no_corpo_proprio(fn, "_gravar_audit_leitura", arv=arv):
            return
        if _delega_a_encerrar_execucao(arv, fn):
            return
        for no in h.nos_do_corpo_proprio(fn):
            if isinstance(no, ast.Call) and any(
                kw.arg == "audit_this_call"
                and isinstance(kw.value, ast.Constant)
                and kw.value.value is True
                for kw in no.keywords
            ):
                return
    pytest.fail(f"{tool}: src/{arquivo}:{funcao} não grava audit no corpo próprio")


def test_encerrar_execucao_grava_o_audit() -> None:
    """O elo que `_delega_a_encerrar_execucao` presume: a função grava de fato."""
    arv = h.arvore(h.SRC / "governance" / "execucao.py")
    fns = [f for f in h.funcoes(arv) if f.name == "encerrar_execucao"]
    assert len(fns) == 1, "encerrar_execucao não existe em src/governance/execucao.py"
    assert _chama_audit_log_record(arv, fns[0])


@pytest.mark.parametrize(
    ("montador", "audita"),
    [
        ("_montar", True),
        ("None", False),
        ("_montar if auditar else None", False),
    ],
)
def test_scanner_ve_o_montador_de_encerrar_execucao(montador: str, audita: bool) -> None:
    """Controle do scanner: só montador que não pode ser `None` conta como audit."""
    fonte = textwrap.dedent(
        f"""
        from src.governance.execucao import encerrar_execucao
        async def run_x(auditar):
            try:
                pass
            finally:
                def _montar():
                    return None
                await encerrar_execucao(None, None, montar_audit={montador})
        """
    )
    arv = ast.parse(fonte)
    fn = next(f for f in h.funcoes(arv) if f.name == "run_x")
    assert _delega_a_encerrar_execucao(arv, fn) is audita


def test_nenhuma_leitura_sem_trilha() -> None:
    sem_trilha: dict[str, str] = {}
    for nome, arquivo in _modulos_das_tools().items():
        derivada = _categoria(_sinais(arquivo))
        if derivada == "executor_sem_audit":
            sem_trilha[nome] = "chama executor sem audit_this_call"
        elif derivada is None and not COMO_CADA_TOOL_AUDITA.get(nome, "").startswith("delega:"):
            sem_trilha[nome] = "nenhum sinal de audit e sem delega: na tabela"
    assert not sem_trilha, f"leituras que não gravam no sucesso: {sem_trilha}"


def test_executor_sem_opt_in_audita_sempre() -> None:
    """`run_meta_level_performance` conta como `executor` sem olhar argumento:
    só vale enquanto ele mesmo passar `audit_this_call=True` adiante, e não
    tiver um `audit_this_call` próprio que o chamador pudesse desligar."""
    from src.mcp.tools import _meta_performance

    assert (
        "audit_this_call"
        not in inspect.signature(_meta_performance.run_meta_level_performance).parameters
    )
    arquivo = Path(inspect.getsourcefile(_meta_performance) or "")
    arv = h.arvore(arquivo)
    fn = next(f for f in h.funcoes(arv) if f.name == "run_meta_level_performance")
    chamadas = [
        no
        for no in h.nos_do_corpo_proprio(fn)
        if isinstance(no, ast.Call)
        and isinstance(no.func, ast.Name)
        and no.func.id in h.nomes_locais(arv, "run_meta_graph_get")
    ]
    assert chamadas, "run_meta_level_performance não chama run_meta_graph_get"
    assert all(_opta_por_audit(c) for c in chamadas)


def test_scanner_ve_o_opt_out(tmp_path: Path) -> None:
    """Controle do scanner: o mesmo arquivo, com o opt-in trocado por `False`,
    deriva `executor_sem_audit`. Sem isto, um scanner que sempre dissesse
    `executor` deixaria os testes acima verdes."""
    original = h.SRC / "mcp" / "tools" / "get_campaign_performance.py"
    assert _sinais(original) == {"executor"}
    copia = tmp_path / original.name
    shutil.copy(original, copia)
    texto = copia.read_text(encoding="utf-8")
    assert "audit_this_call=True" in texto
    copia.write_text(texto.replace("audit_this_call=True", "audit_this_call=False"), "utf-8")
    assert _sinais(copia) == {"executor_sem_audit"}
    # E sem o kwarg (ausente = default False), o mesmo veredito.
    copia.write_text(texto.replace("audit_this_call=True,", ""), "utf-8")
    assert _sinais(copia) == {"executor_sem_audit"}
