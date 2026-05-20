"""Pure client-side aggregation for GAQL result rows (V0: COUNT only).

GAQL nativo NAO suporta GROUP BY (verified em
src/google_ads/queries/bulk_pause.py:20 — está na blacklist _FORBIDDEN_KEYWORDS).
Aggregation precisa ser client-side post-fetch.

Used by src/mcp/tools/run_gaql.py when caller passa aggregate_by parameter.
"""

from typing import Any


def _resolve_dotted(row: dict[str, Any], path: str) -> Any:
    """Walk dotted field path in flat/nested dict from MessageToDict.

    MessageToDict with preserving_proto_field_name=True retorna nested dicts
    pra nested protos (e.g., {"campaign": {"id": "123"}}). Helper resolve
    "campaign.id" -> "123". Returns None se qualquer segmento missing.
    """
    current: Any = row
    for segment in path.split("."):
        if not isinstance(current, dict) or segment not in current:
            return None
        current = current[segment]
    return current


def aggregate_rows(
    rows: list[dict[str, Any]],
    group_by: list[str],
) -> list[dict[str, Any]]:
    """Agrupa rows por field paths (dotted), retorna [{key:{...}, count:N}] sorted desc.

    Pure function — nao importa Google SDK; testavel sem fixture pesado.

    Args:
        rows: flat dicts vindos de MessageToDict (preserving_proto_field_name=True).
        group_by: 1-5 field paths dotted. Ex: ['field_type', 'asset.type'].

    Returns:
        Lista de grupos sorted by count desc. Key e dict mapeando cada field path
        ao valor encontrado (None se field missing). Empates preservam insertion
        order (sorted() Python e stable).
    """
    if not rows:
        return []

    counts: dict[tuple[Any, ...], int] = {}
    for row in rows:
        key = tuple(_resolve_dotted(row, path) for path in group_by)
        counts[key] = counts.get(key, 0) + 1

    # sorted() Python is stable; ties preserve insertion order.
    sorted_groups = sorted(counts.items(), key=lambda kv: -kv[1])

    return [
        {
            "key": dict(zip(group_by, key_tuple, strict=True)),
            "count": count,
        }
        for key_tuple, count in sorted_groups
    ]
