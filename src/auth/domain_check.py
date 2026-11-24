"""Formato de e-mail aceito no login, na conexão do Google Ads e no convite.

Não é gate de acesso: quem decide quem entra é a tabela `managers` (convidado ou
ativo). A trava fixa em `@v4company.com` saiu em 24/11/2026.
"""


def is_valid_email_shape(email: str | None) -> bool:
    """True se há exatamente um `@`, com parte local e domínio não vazios."""
    if not email:
        return False
    parts = email.lower().strip().split("@")
    if len(parts) != 2:
        return False
    local, domain = parts
    return bool(local) and bool(domain)
