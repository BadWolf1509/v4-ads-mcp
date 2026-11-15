"""Gerar signed_request HMAC-valid pra testar /oauth/meta/data-deletion-callback.

Usage:
    python scripts/gerar_signed_request_meta.py [META_APP_SECRET]
    # Se não passar arg, lê via getpass interativo (evita exposição em shell history).

Output:
    O signed_request no formato `<sig_b64>.<payload_b64>` (valor do form param
    `signed_request`) e, em seguida, os comandos de POST (PowerShell e curl) já
    com o host atual (`PUBLIC_BASE_URL` ou o default das settings), sem host fixo neste texto.
"""

import base64
import getpass
import hashlib
import hmac
import json
import os
import sys
import time
from pathlib import Path

_RAIZ = Path(__file__).resolve().parents[1]
if str(_RAIZ) not in sys.path:  # `python scripts/gerar_signed_request_meta.py` da raiz
    sys.path.insert(0, str(_RAIZ))

from src.config import Settings  # noqa: E402


def _base_url() -> str:
    """`PUBLIC_BASE_URL` do ambiente, senão o default das settings.

    Não instancia `get_settings()`: ele exige os segredos obrigatórios, e este
    script só precisa do host.
    """
    return os.environ.get("PUBLIC_BASE_URL") or str(
        Settings.model_fields["public_base_url"].default
    )


def main() -> None:
    app_secret = sys.argv[1] if len(sys.argv) > 1 else getpass.getpass("META_APP_SECRET: ")

    if not app_secret:
        print("ERROR: META_APP_SECRET vazio. Aborting.", file=sys.stderr)
        sys.exit(1)

    now = int(time.time())
    payload = {
        "algorithm": "HMAC-SHA256",
        "user_id": "9999999999",
        "expires": now + 3600,
        "issued_at": now,
    }
    payload_json = json.dumps(payload, separators=(",", ":"))
    payload_b64 = base64.urlsafe_b64encode(payload_json.encode()).decode().rstrip("=")
    sig = hmac.new(app_secret.encode(), payload_b64.encode(), hashlib.sha256).digest()
    sig_b64 = base64.urlsafe_b64encode(sig).decode().rstrip("=")
    signed_request = f"{sig_b64}.{payload_b64}"
    url = f"{_base_url().rstrip('/')}/oauth/meta/data-deletion-callback"

    print(signed_request)
    print()
    print("Exemplo POST (PowerShell):")
    print(
        f'    Invoke-WebRequest -Uri "{url}" -Method POST '
        f'-Body "signed_request={signed_request}" '
        '-ContentType "application/x-www-form-urlencoded"'
    )
    print()
    print("Exemplo POST (curl):")
    print(f'    curl -X POST "{url}" -d "signed_request={signed_request}"')


if __name__ == "__main__":
    main()
