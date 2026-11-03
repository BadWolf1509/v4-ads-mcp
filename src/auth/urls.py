"""URL absoluta com https forçado, para callbacks registrados em terceiros."""

from typing import Any

from fastapi import Request


def https_url_for(request: Request, name: str, **params: Any) -> str:
    """`request.url_for(name, **params)` com o esquema trocado para https.

    Cloud Run termina o TLS no GFE; o container vê HTTP, então
    `request.url.scheme` é "http" mesmo quando o cliente usou HTTPS. O OAuth
    Client no Google Cloud Console está registrado com a URL pública https://,
    e mandar http:// dá redirect_uri_mismatch.

    --proxy-headers / X-Forwarded-Proto foram tentados e não pegaram de forma
    confiável no uvicorn lançado pelo CNB no Cloud Run. Forçar https no código
    resolve, e a única URL chamável de fora é https de qualquer modo.
    """
    url = str(request.url_for(name, **params))
    if url.startswith("http://"):
        url = "https://" + url[len("http://") :]
    return url
