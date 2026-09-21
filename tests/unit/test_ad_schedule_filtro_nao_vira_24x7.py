"""Filtro de status nao pode virar afirmacao sobre entrega."""

from src.mcp.tools.get_ad_schedule import campanhas_com_grade_incerta


def test_filtro_paused_torna_toda_campanha_incerta() -> None:
    """Campanha com janelas ENABLED volta VAZIA sob `status='paused'`, e
    `summarize_current([])` a chamaria de 24x7 — o oposto da verdade."""
    incertas = campanhas_com_grade_incerta(
        [], truncated=False, campanhas=["111", "222"], status="paused"
    )
    assert incertas == {"111", "222"}


def test_filtro_all_tambem_e_incerto() -> None:
    """Sob `all` as linhas incluem criterios pausados e removidos, que NAO
    restringem entrega — contar todos como janela infla `hours_per_week`."""
    incertas = campanhas_com_grade_incerta([], truncated=False, campanhas=["111"], status="all")
    assert incertas == {"111"}


def test_enabled_sem_truncamento_nao_torna_nada_incerto() -> None:
    """CONTROLE POSITIVO: sem ele, uma implementacao que marca TUDO como
    incerto passaria nos dois testes de cima, e a tool nao responderia mais
    nada. `enabled` e o default — o caminho comum nao pode mudar."""
    incertas = campanhas_com_grade_incerta(
        [], truncated=False, campanhas=["111", "222"], status="enabled"
    )
    assert incertas == set()


def test_o_resumo_da_tool_nao_diz_24x7_sob_filtro() -> None:
    """O helper certo nao prova a RESPOSTA certa: o laco que anula os tres
    campos e outro codigo. Sem este teste, `campanhas_com_grade_incerta`
    poderia devolver o conjunto certo e o resumo sair com `false`/`168` assim
    mesmo — o defeito de origem, intacto."""
    from src.mcp.tools.get_ad_schedule import anular_resumos_incertos

    summary = {
        "111": {
            "campaign_name": "A",
            "has_schedule": False,
            "windows": 0,
            "hours_per_week": 168.0,
        }
    }
    anular_resumos_incertos(summary, grade_rows=[], truncated=False, status="paused")

    assert summary["111"]["has_schedule"] is None
    assert summary["111"]["hours_per_week"] is None
    assert summary["111"]["windows"] is None
    assert summary["111"]["schedule_desconhecida_por_filtro"] is True
