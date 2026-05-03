"""MCP session resolution from Bearer tokens.

This module is a stub at Phase 0 — it only parses the Authorization
header. Full session resolution (DB lookup, manager_id binding) lands
in Phase 1.
"""


def extract_bearer_token(authorization_header: str | None) -> str | None:
    """Parse 'Bearer <token>' header, returning the token or None.

    Returns None when the header is missing, uses a non-Bearer scheme,
    or has an empty token.
    """
    if not authorization_header:
        return None
    parts = authorization_header.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    return token or None
