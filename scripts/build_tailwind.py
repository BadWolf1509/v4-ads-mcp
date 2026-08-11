"""Gera src/web/static/v4-tailwind.css a partir das templates.

Roda o CLI oficial do Tailwind via npx. Node existe so na maquina do dev e
no runner do CI — o runtime e o buildpack nao veem node, e nada disso entra
no pyproject.toml. O CSS gerado e COMMITADO; o CI regenera e faz
`git diff --exit-code` pra impedir drift silencioso.

Contexto: ate 2026-08-11 o painel carregava o Play CDN (cdn.tailwindcss.com),
407 KB de JS render-blocking que compilava em runtime pra produzir ~7 KB de
CSS. Gerar offline derruba isso pra ~12 KB de CSS estatico e permitiu tirar
'unsafe-eval' da CSP.

Uso: python scripts/build_tailwind.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

# A versao que o Play CDN servia. Nao subir pra v4 (config CSS-first).
TAILWIND_VERSION = "3.4.17"

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "src" / "web" / "static" / "v4-tailwind.css"


def main() -> int:
    npx = shutil.which("npx")
    if npx is None:
        print(
            "npx nao encontrado. Instale Node LTS pra regenerar o CSS "
            "(so necessario ao mexer em classe utilitaria de template).",
            file=sys.stderr,
        )
        return 1

    cmd = [
        npx,
        "--yes",
        f"tailwindcss@{TAILWIND_VERSION}",
        "-c",
        str(ROOT / "tailwind.config.js"),
        "-i",
        str(ROOT / "scripts" / "tailwind-input.css"),
        "-o",
        str(OUTPUT),
        "--minify",
    ]
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if proc.returncode != 0:
        print(proc.stdout, file=sys.stderr)
        print(proc.stderr, file=sys.stderr)
        return proc.returncode

    print(f"OK: {OUTPUT.relative_to(ROOT)} ({OUTPUT.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
