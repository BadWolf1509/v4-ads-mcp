"""Gerar signed_request HMAC-valid pra testar /oauth/meta/data-deletion-callback localmente.

Usage:
    python scripts/test_meta_deletion_callback.py [META_APP_SECRET]
    # Se não passar arg, lê via getpass interativo (evita exposição em shell history).

Output:
    String no formato `<sig_b64>.<payload_b64>` — usar como valor do form param `signed_request`
    em POST pra https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/oauth/meta/data-deletion-callback

Exemplo POST (PowerShell):
    $signedRequest = "<output>"
    Invoke-WebRequest -Uri "https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/oauth/meta/data-deletion-callback" `
      -Method POST `
      -Body "signed_request=$signedRequest" `
      -ContentType "application/x-www-form-urlencoded"

Exemplo POST (curl):
    curl -X POST "https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/oauth/meta/data-deletion-callback" \
      -d "signed_request=<output>"
"""

import base64
import getpass
import hashlib
import hmac
import json
import sys
import time


def main() -> None:
    if len(sys.argv) > 1:
        app_secret = sys.argv[1]
    else:
        app_secret = getpass.getpass("META_APP_SECRET: ")

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
    print(f"{sig_b64}.{payload_b64}")


if __name__ == "__main__":
    main()
