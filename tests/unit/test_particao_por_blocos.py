from src.google_ads.ad_schedule import (
    BLOCOS_PADRAO,
    MetricCell,
    Window,
    hours_per_week,
    partition_by_blocks,
)


def _cel(dia: str, hora: int, custo_brl: float, conv: float) -> MetricCell:
    return MetricCell(dia, hora, int(custo_brl * 1_000_000), conv)


def test_celula_fora_de_todo_bloco_cai_em_outros_e_nao_some():
    """Soma dos blocos tem que bater com o total. Celula descartada em silencio
    e a familia de defeito que este repo mais vem pagando: numero que parece
    certo porque a parte que faltava nao aparece."""
    blocos = {"comercial": [Window("MONDAY", 8, 0, 18, 0)]}
    cells = [_cel("MONDAY", 9, 100.0, 5.0), _cel("SUNDAY", 3, 40.0, 1.0)]

    resultado = partition_by_blocks(cells, blocos)

    assert resultado["comercial"]["cost_brl"] == 100.0
    assert resultado["outros"]["cost_brl"] == 40.0
    assert sum(b["cost_brl"] for b in resultado.values()) == 140.0
    assert sum(b["cells"] for b in resultado.values()) == 2


def test_os_blocos_padrao_ladrilham_a_semana_exatamente():
    """168h, sem sobra e sem sobreposicao. Se os blocos nao ladrilham, `outros`
    vira lixeira silenciosa e a comparacao entre blocos perde sentido."""
    total = sum(hours_per_week(janelas) for janelas in BLOCOS_PADRAO.values())
    assert total == 168.0
    assert set(BLOCOS_PADRAO) == {"comercial", "fora_de_hora", "fim_de_semana"}
