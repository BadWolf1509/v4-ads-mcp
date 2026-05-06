"""GAQL query for the recommendations tool."""


def recommendations_query() -> str:
    """All pending recommendations for the account.

    NOTE: Impact metrics (base_metrics.*, potential_metrics.*) intentionally
    omitted — they're selectable_with-restricted in v24 and depend on the
    recommendation type. Users can query specific types via run_gaql for
    detailed impact data.
    """
    return """
        SELECT
          recommendation.resource_name,
          recommendation.type,
          recommendation.dismissed
        FROM recommendation
        WHERE recommendation.dismissed = false
    """.strip()
