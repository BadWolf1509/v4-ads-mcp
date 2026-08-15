"""GAQL query for the recommendations tool."""


def recommendations_query(limit: int = 100) -> str:
    """All pending recommendations for the account.

    NOTE: Impact metrics (base_metrics.*, potential_metrics.*) intentionally
    omitted — they're selectable_with-restricted in v24 and depend on the
    recommendation type. Users can query specific types via run_gaql for
    detailed impact data.

    F98 — pede `limit + 1`: a linha extra é a sentinela que revela o corte. As
    recomendações escalam com o nº de ad_groups (`RESPONSIVE_SEARCH_AD_ASSET` e
    `KEYWORD` são por ad_group), então sem teto uma conta grande estoura o cap
    de token do MCP e a resposta inteira se perde.
    """
    return f"""
        SELECT
          recommendation.resource_name,
          recommendation.type,
          recommendation.dismissed
        FROM recommendation
        WHERE recommendation.dismissed = false
        LIMIT {limit + 1}
    """.strip()
