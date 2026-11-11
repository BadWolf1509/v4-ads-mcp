"""`estimated_calls` saiu de `run_meta_graph_get` (follow-up da Parte E, 11/11).

A Meta nao tem reserva de cota: o contador BUC grava so as paginas lidas desde
10/11. O parametro sobrou como "previsao" que nada lia — e um caller que o
ajustasse acharia que mexia no consumo. Parametro morto num executor que toda
tool Meta chama e convite a esse engano.
"""

from __future__ import annotations

import inspect

from src.meta_ads.reports import run_meta_graph_get


def test_o_executor_meta_nao_aceita_estimated_calls() -> None:
    assert "estimated_calls" not in inspect.signature(run_meta_graph_get).parameters
