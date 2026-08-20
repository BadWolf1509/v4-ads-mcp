#!/usr/bin/env python3
"""Verifica se v4-tailwind.css esta em sync com as classes das templates.

Espelha o step homonimo do ci.yml. Existia so la, entao mexer numa classe
utilitaria e dar push virava CI vermelho DEPOIS da espera do runner — e a
unica protecao era a regra do CLAUDE.md ("rode o build e commite no mesmo
commit"), que depende de lembrar.

Node e opcional na maquina do dev (o runtime e o buildpack nao o veem), entao
sem `npx` este check PULA com dica em vez de bloquear o gate — mesmo padrao do
`check_docker()` no full sweep. Quem nao tem Node tambem nao consegue mexer no
CSS gerado, entao pular ali nao abre buraco: o CI segue sendo a rede.

Exit codes:
    0  em sync (ou pulado por falta de Node)
    1  o CSS estava defasado — foi REGENERADO, falta commitar
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
CSS = RAIZ / "src" / "web" / "static" / "v4-tailwind.css"


def main() -> int:
    if shutil.which("npx") is None:
        print(
            "[skip] npx nao encontrado — pulando o check do Tailwind. "
            "O CI regenera e falha se estiver defasado.",
        )
        return 0

    build = subprocess.run(
        [sys.executable, str(RAIZ / "scripts" / "build_tailwind.py")],
        cwd=RAIZ,
        capture_output=True,
        text=True,
    )
    if build.returncode != 0:
        print(build.stdout, file=sys.stderr)
        print(build.stderr, file=sys.stderr)
        return 1

    diff = subprocess.run(
        ["git", "diff", "--exit-code", "--", str(CSS.relative_to(RAIZ))],
        cwd=RAIZ,
        capture_output=True,
        text=True,
    )
    if diff.returncode != 0:
        print(
            f"v4-tailwind.css estava defasado e foi REGENERADO ({CSS.stat().st_size} bytes).\n"
            "Commite o arquivo junto da mudanca de template — o CI faz o mesmo "
            "diff e falha sem ele.",
            file=sys.stderr,
        )
        return 1

    print(f"OK: {CSS.relative_to(RAIZ)} em sync com as templates.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
