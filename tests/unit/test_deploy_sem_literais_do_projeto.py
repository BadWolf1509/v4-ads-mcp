"""O `deploy.yml` não fixa valores do projeto da V4: projeto novo muda só secrets e vars do repo."""

from __future__ import annotations

import re
from pathlib import Path

from src.config import Settings

RAIZ = Path(__file__).resolve().parents[2]
DEPLOY = (RAIZ / ".github/workflows/deploy.yml").read_text(encoding="utf-8")


def test_deploy_sem_project_number() -> None:
    assert "299432068772" not in DEPLOY


def test_deploy_sem_bm_da_v4() -> None:
    assert "619664032237208" not in DEPLOY


def test_public_base_url_vem_de_vars() -> None:
    [servico] = re.findall(r'--set-env-vars="([^"]*)"', DEPLOY)
    assert "PUBLIC_BASE_URL=${{ vars.PUBLIC_BASE_URL }}" in servico.split(",")
    assert "META_BUSINESS_ID=${{ vars.META_BUSINESS_ID }}" in servico.split(",")
    [job_env] = re.findall(r'^      JOB_ENV_VARS: "([^"]*)"$', DEPLOY, re.M)
    assert "META_BUSINESS_ID=${{ vars.META_BUSINESS_ID }}" in job_env.split(",")


def test_registry_deriva_da_regiao() -> None:
    assert "southamerica-east1-docker.pkg.dev" not in DEPLOY
    assert DEPLOY.count("${{ secrets.GCP_REGION }}-docker.pkg.dev/") == 5


def test_deploy_exige_vars() -> None:
    """Um step antes do build barra o deploy com var vazia (o serviço subiria com `PUBLIC_BASE_URL=`)."""
    i_valida = DEPLOY.index("name: Validar vars do repositorio")
    i_build = DEPLOY.index("name: Submit build via Buildpacks")
    assert i_valida < i_build
    bloco = DEPLOY[i_valida:i_build]
    for var in ("PUBLIC_BASE_URL", "META_BUSINESS_ID"):
        assert f"${{{{ vars.{var} }}}}" in bloco
        assert re.search(rf'-z "\$\{{?{var}\}}?"', bloco), var
    assert "exit 1" in bloco


def test_defaults_nao_apontam_projeto_antigo() -> None:
    assert "299432068772" not in str(Settings.model_fields["public_base_url"].default)
    admin = (RAIZ / "src/scripts/admin.py").read_text(encoding="utf-8")
    assert "299432068772" not in admin
