"""Bootstrap do projeto GCP novo: a lista de comandos reproduz o inventário medido em 25/11."""

from __future__ import annotations

from typing import Any

import pytest

from scripts.infra import bootstrap_projeto as bp

PAPEIS_DEPLOY = {
    "roles/artifactregistry.writer",
    "roles/cloudbuild.builds.editor",
    "roles/iam.serviceAccountUser",
    "roles/run.admin",
    "roles/serviceusage.serviceUsageConsumer",
    "roles/storage.admin",
    "roles/storage.objectViewer",
}
SECRETS = {
    "database-url",
    "session-signing-key",
    "aes-master-key",
    "google-oauth-client-id",
    "google-oauth-client-secret",
    "google-ads-login-customer-id",
    "meta-app-id",
    "meta-app-secret",
    "meta-system-user-token",
}


@pytest.fixture
def comandos() -> list[bp.Comando]:
    return bp.montar_comandos(
        project_id="p-teste", region="southamerica-east1", alert_email="a@b.com"
    )


def _criacoes(comandos: list[bp.Comando], *prefixo: str) -> list[list[str]]:
    n = len(prefixo)
    return [c.criacao for c in comandos if c.criacao[1 : 1 + n] == list(prefixo)]


def _flag(cmd: list[str], nome: str) -> str | None:
    for arg in cmd:
        if arg.startswith(f"{nome}="):
            return arg.split("=", 1)[1]
    return None


def test_cria_os_tres_service_accounts(comandos: list[bp.Comando]) -> None:
    nomes = {c[4] for c in _criacoes(comandos, "iam", "service-accounts", "create")}
    assert nomes == {"v4-ads-mcp-runtime", "v4-ads-mcp-deploy", "v4-ads-mcp-scheduler"}


def test_papeis_do_deploy_iguais_ao_medido(comandos: list[bp.Comando]) -> None:
    sa = "serviceAccount:v4-ads-mcp-deploy@p-teste.iam.gserviceaccount.com"
    papeis = {
        _flag(c, "--role")
        for c in _criacoes(comandos, "projects", "add-iam-policy-binding")
        if _flag(c, "--member") == sa
    }
    assert papeis == PAPEIS_DEPLOY


def test_wif_restrito_ao_repo(comandos: list[bp.Comando]) -> None:
    [provider] = _criacoes(comandos, "iam", "workload-identity-pools", "providers", "create-oidc")
    assert (
        _flag(provider, "--attribute-condition") == "assertion.repository=='BadWolf1509/v4-ads-mcp'"
    )
    assert _flag(provider, "--issuer-uri") == "https://token.actions.githubusercontent.com"


@pytest.mark.parametrize(
    ("tipo", "retries", "timeout"),
    [("migrate", "1", "600s"), ("resync", "3", "600s"), ("backup", "1", "900s")],
)
def test_jobs_com_args_cnb(
    comandos: list[bp.Comando], tipo: str, retries: str, timeout: str
) -> None:
    [job] = [
        c for c in _criacoes(comandos, "run", "jobs", "create") if c[4] == f"v4-ads-mcp-{tipo}"
    ]
    assert _flag(job, "--args") == f"/cnb/process/{tipo}"
    assert _flag(job, "--max-retries") == retries
    assert _flag(job, "--task-timeout") == timeout
    assert _flag(job, "--memory") == "512Mi"
    assert _flag(job, "--cpu") == "1"


def test_schedulers_nascem_pausados(comandos: list[bp.Comando]) -> None:
    criados = [
        (i, c.criacao[5])
        for i, c in enumerate(comandos)
        if c.criacao[1:5] == ["scheduler", "jobs", "create", "http"]
    ]
    assert {n for _, n in criados} == {"v4-ads-mcp-resync-daily", "v4-ads-mcp-backup-weekly"}
    for i, nome in criados:
        depois = [c.criacao for c in comandos[i + 1 :]]
        assert any(c[1:4] == ["scheduler", "jobs", "pause"] and c[4] == nome for c in depois), nome


def test_cada_criacao_tem_checagem(comandos: list[bp.Comando]) -> None:
    idempotentes = {
        ("services", "enable"),
        ("projects", "add-iam-policy-binding"),
        ("iam", "service-accounts", "add-iam-policy-binding"),
        ("storage", "buckets", "add-iam-policy-binding"),
        ("run", "jobs", "add-iam-policy-binding"),
        ("scheduler", "jobs", "pause"),
        ("storage", "buckets", "update"),
    }
    for c in comandos:
        if any(tuple(c.criacao[1 : 1 + len(p)]) == p for p in idempotentes):
            continue
        assert c.checagem is not None, c.criacao


def test_nenhum_valor_de_secret_no_comando(comandos: list[bp.Comando]) -> None:
    for c in comandos:
        for arg in [*c.criacao, *(c.checagem or [])]:
            assert "data-file" not in arg, c.criacao


def test_cria_os_nove_secrets(comandos: list[bp.Comando]) -> None:
    nomes = {c[3] for c in _criacoes(comandos, "secrets", "create")}
    assert nomes == SECRETS


def test_dry_run_nao_executa(monkeypatch: pytest.MonkeyPatch) -> None:
    chamadas: list[Any] = []
    monkeypatch.setattr(bp.subprocess, "run", lambda *a, **k: chamadas.append(a))
    rc = bp.main(["--project-id", "p", "--region", "r", "--alert-email", "a@b.com"])
    assert rc == 0
    assert chamadas == []
