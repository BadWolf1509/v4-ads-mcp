"""Os jobs do Cloud Run recebem secrets por `--update-secrets`, que so acrescenta.

Tirar um secret de JOB_SECRETS nao o tira do job: o developer token ficou montado
nos tres jobs depois do #208 (02/11). Todo `gcloud run jobs update` retira a lista
JOB_SECRETS_RETIRADOS, e nada nela pode continuar sendo montado ou lido.
"""

from __future__ import annotations

import re
from pathlib import Path

from src.config import Settings

_DEPLOY = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "deploy.yml"


def _texto() -> str:
    return _DEPLOY.read_text(encoding="utf-8")


def _lista(nome: str) -> set[str]:
    achado = re.search(rf'^\s*{nome}: "([^"]*)"', _texto(), re.M)
    assert achado, f"{nome} sumiu do deploy.yml"
    return {par.split("=", 1)[0].strip() for par in achado.group(1).split(",") if par.strip()}


def _comandos_de_job() -> dict[str, list[str]]:
    """Cada `gcloud run jobs update`, linha a linha, enquanto a anterior termina em barra invertida."""
    linhas = _texto().splitlines()
    comandos: dict[str, list[str]] = {}
    for i, linha in enumerate(linhas):
        if "gcloud run jobs update " not in linha:
            continue
        cmd = [linha.strip()]
        while linhas[i].rstrip().endswith("\\"):
            i += 1
            cmd.append(linhas[i].strip())
        comandos[cmd[0].split()[4]] = cmd
    return comandos


def test_todo_update_de_job_retira_os_secrets_aposentados() -> None:
    comandos = _comandos_de_job()
    assert set(comandos) == {"v4-ads-mcp-migrate", "v4-ads-mcp-resync", "v4-ads-mcp-backup"}
    flag = '--remove-secrets="${JOB_SECRETS_RETIRADOS}"'
    sem_retirada = sorted(job for job, cmd in comandos.items() if flag not in cmd)
    assert not sem_retirada, f"jobs que nao retiram os secrets aposentados: {sem_retirada}"


def test_aposentado_nao_volta_a_ser_montado_nem_lido() -> None:
    retirados = _lista("JOB_SECRETS_RETIRADOS")
    assert "GOOGLE_ADS_DEVELOPER_TOKEN" in retirados
    assert not retirados & _lista("JOB_SECRETS")
    assert not {n.lower() for n in retirados} & set(Settings.model_fields)
