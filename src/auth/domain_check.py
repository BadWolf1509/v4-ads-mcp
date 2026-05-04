"""Restrict panel access to @v4company.com emails."""

ALLOWED_DOMAIN = "v4company.com"


def is_allowed_email(email: str | None) -> bool:
    """Return True if email belongs to the allowed corporate domain."""
    if not email:
        return False
    parts = email.lower().strip().split("@")
    if len(parts) != 2:
        return False
    _, domain = parts
    return domain == ALLOWED_DOMAIN
