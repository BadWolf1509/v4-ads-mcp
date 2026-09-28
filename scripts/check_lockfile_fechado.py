#!/usr/bin/env python3
"""Lockfile fechado (F198): toda dependência de toda linha do requirements.txt tem linha própria.

O `requirements.txt` é o lockfile que o CI e o buildpack instalam. Instalado com resolução
(`pip install -r`), uma dependência sem linha própria entra do mesmo jeito — por RESOLUÇÃO,
na versão mais nova que couber, sem pin — e nada fica vermelho. Foi o que aconteceu em 20/09:
o `google-api-core` 2.36 -> 2.38 entrou aplicando só a linha dele (sem regerar o lock) e trouxe
o `opentelemetry-api`, que passou a ser instalado flutuando.

Aqui o lock é instalado num venv limpo com `--no-deps`, e o `pip check` acusa qualquer
requisito sem linha. Medido em 27/09: com o lock antigo, exit 1 citando o `opentelemetry-api`;
com o regerado, exit 0. Precisa de rede (baixa os pacotes), por isso roda no CI e no full
sweep, não no gate rápido.

Conserto quando falhar: regerar o lock —
    uv pip compile pyproject.toml -o requirements.txt --universal
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import venv
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="lock-fechado-", ignore_cleanup_errors=True) as tmp:
        venv.create(tmp, with_pip=True)
        python = Path(tmp) / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        instalacao = subprocess.run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--quiet",
                "--disable-pip-version-check",
                "--no-deps",
                "-r",
                str(RAIZ / "requirements.txt"),
            ]
        )
        if instalacao.returncode != 0:
            print("FAIL: o lockfile nao instala com --no-deps", file=sys.stderr)
            return 1
        checagem = subprocess.run(
            [str(python), "-m", "pip", "check", "--disable-pip-version-check"],
            capture_output=True,
            text=True,
        )
        print(checagem.stdout.strip())
        if checagem.returncode != 0:
            print(
                "O requirements.txt nao e fechado. Regere com:\n"
                "  uv pip compile pyproject.toml -o requirements.txt --universal",
                file=sys.stderr,
            )
        return checagem.returncode


if __name__ == "__main__":
    sys.exit(main())
