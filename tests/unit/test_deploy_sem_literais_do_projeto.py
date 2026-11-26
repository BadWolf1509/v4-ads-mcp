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


def test_deploy_exige_public_base_url() -> None:
    """Um step antes do build barra o deploy sem `PUBLIC_BASE_URL` (links do painel quebrados)."""
    i_valida = DEPLOY.index("name: Validar vars do repositorio")
    i_build = DEPLOY.index("name: Submit build via Buildpacks")
    assert i_valida < i_build
    bloco = DEPLOY[i_valida:i_build]
    assert "PUBLIC_BASE_URL: ${{ vars.PUBLIC_BASE_URL }}" in bloco
    assert 'if [ -z "${PUBLIC_BASE_URL}" ]; then' in bloco
    assert "exit 1" in bloco


def test_deploy_aceita_meta_business_id_vazio_com_aviso() -> None:
    """Sem BM a reconciliação Meta é no-op (config.py): vazio é estado legítimo, não erro.

    Mas não pode passar calado — o step avisa no log do run.
    """
    i_valida = DEPLOY.index("name: Validar vars do repositorio")
    i_build = DEPLOY.index("name: Submit build via Buildpacks")
    bloco = DEPLOY[i_valida:i_build]
    assert "META_BUSINESS_ID: ${{ vars.META_BUSINESS_ID }}" in bloco
    assert 'if [ -z "${META_BUSINESS_ID}" ]; then' in bloco
    trecho = bloco[bloco.index('if [ -z "${META_BUSINESS_ID}" ]; then') :]
    trecho = trecho[: trecho.index("fi")]
    assert "::warning::" in trecho
    assert "exit 1" not in trecho


def test_defaults_nao_apontam_projeto_antigo() -> None:
    assert "299432068772" not in str(Settings.model_fields["public_base_url"].default)
    admin = (RAIZ / "src/scripts/admin.py").read_text(encoding="utf-8")
    assert "299432068772" not in admin


def test_jobs_recebem_o_bucket_de_backup_do_proprio_projeto() -> None:
    """Mesma convenção do bootstrap (`gs://<projeto>-backups`), derivada do secret do projeto."""
    [job_env] = re.findall(r'^      JOB_ENV_VARS: "([^"]*)"$', DEPLOY, re.M)
    assert "BACKUP_BUCKET=${{ secrets.GCP_PROJECT_ID }}-backups" in job_env.split(",")
    bootstrap = (RAIZ / "scripts/infra/bootstrap_projeto.py").read_text(encoding="utf-8")
    assert 'bucket = f"gs://{project_id}-backups"' in bootstrap


def test_default_do_bucket_de_backup_e_vazio() -> None:
    assert Settings.model_fields["backup_bucket"].default == ""


def test_deploy_passa_meta_habilitada_ao_servico_e_aos_jobs() -> None:
    """Desligar a Meta é uma var do repo, sem código: o default (`true`) mantém o erro alto."""
    esperado = "META_HABILITADA=${{ vars.META_HABILITADA || 'true' }}"
    [servico] = re.findall(r'--set-env-vars="([^"]*)"', DEPLOY)
    assert esperado in servico.split(",")
    [job_env] = re.findall(r'^      JOB_ENV_VARS: "([^"]*)"$', DEPLOY, re.M)
    assert esperado in job_env.split(",")
