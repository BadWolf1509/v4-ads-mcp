"""Razoes numericas neutras de plataforma: denominador ausente e indefinido (`None`), nao zero."""


def razao(numerador: float | None, denominador: float | None) -> float | None:
    """`numerador / denominador`, ou `None` quando nao ha o que dividir.

    Razao sem denominador e INDEFINIDA, nao zero: CPA R$ 0,00 com gasto e zero
    conversao se le como o melhor CPA possivel; CPC R$ 0,00 sem clique, como
    clique de graca. `None` e o terceiro estado do F191 — distinto do zero
    medido. E a UNICA regra de denominador zero das razoes, neutra de
    plataforma: usada pelas tools Google e Meta. O guard
    `test_nenhuma_razao_vira_zero_quando_o_denominador_some` acusa a expressao
    condicional nas duas orientacoes (`x / y if y else 0` e tambem
    `0 if not y else x / y`), com `0`, `0.0` ou `None` no ramo constante, em
    `src/mcp/tools/` (onde moram as tools das duas plataformas) e
    `src/google_ads/`; `src/meta_ads/` fica fora da varredura. A forma em
    instrucoes (`if ...: return None`) o guard nao ve —
    `apply_recommendation._delta_pct` foi migrada a mao (F4).
    """
    if numerador is None or not denominador:
        return None
    return numerador / denominador


def arredondado(valor: float | None, casas: int) -> float | None:
    """`round` que deixa `None` passar: a razao indefinida continua indefinida."""
    return None if valor is None else round(valor, casas)


def percentual(valor: float | None) -> float | None:
    """`valor * 100` que deixa `None` passar.

    Mantem a ordem `a / b * 100` das contas de antes: `a * 100 / b` muda o ultimo
    bit e pode virar o arredondamento na casa decimal.
    """
    return None if valor is None else valor * 100
