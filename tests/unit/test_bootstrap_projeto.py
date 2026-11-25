"""Bootstrap do projeto GCP novo: a lista de comandos reproduz o inventário medido em 25/11."""

from __future__ import annotations

from types import SimpleNamespace
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
    # F66: imagem CNB com só `--args` sobe o process `web` e o job pendura; o deploy usa `--command`.
    assert _flag(job, "--command") == f"/cnb/process/{tipo}"
    assert _flag(job, "--args") is None
    assert _flag(job, "--max-retries") == retries
    assert _flag(job, "--task-timeout") == timeout
    assert _flag(job, "--memory") == "512Mi"
    assert _flag(job, "--cpu") == "1"


def test_schedulers_nascem_pausados(comandos: list[bp.Comando]) -> None:
    """O pause vem amarrado à criação: só roda quando o scheduler acabou de nascer."""
    criados = [c for c in comandos if c.criacao[1:5] == ["scheduler", "jobs", "create", "http"]]
    assert {c.criacao[5] for c in criados} == {
        "v4-ads-mcp-resync-daily",
        "v4-ads-mcp-backup-weekly",
    }
    for c in criados:
        assert c.apos_criar is not None
        assert c.apos_criar[1:4] == ["scheduler", "jobs", "pause"]
        assert c.apos_criar[4] == c.criacao[5]
    assert not any(c.criacao[1:4] == ["scheduler", "jobs", "pause"] for c in comandos)


def test_cada_criacao_tem_checagem(comandos: list[bp.Comando]) -> None:
    idempotentes = {
        ("services", "enable"),
        ("projects", "add-iam-policy-binding"),
        ("iam", "service-accounts", "add-iam-policy-binding"),
        ("storage", "buckets", "add-iam-policy-binding"),
        ("run", "jobs", "add-iam-policy-binding"),
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


class _Rodada:
    """Registra as chamadas; `existentes` = prefixos de checagem que devolvem 0 (recurso já existe)."""

    def __init__(self, existentes: tuple[str, ...] = ()) -> None:
        self.chamadas: list[list[str]] = []
        self.existentes = existentes

    def __call__(self, cmd: list[str], **_: Any) -> SimpleNamespace:
        self.chamadas.append(cmd)
        if cmd[1:3] == ["projects", "describe"]:
            return SimpleNamespace(returncode=0, stdout="123")
        texto = " ".join(cmd)
        existe = "describe" in cmd and any(e in texto for e in self.existentes)
        return SimpleNamespace(
            returncode=0 if existe else (1 if "describe" in cmd else 0), stdout=""
        )


_ARGS_APPLY = ["--project-id", "p", "--region", "r", "--alert-email", "a@b.com", "--apply"]


def test_apply_usa_o_executavel_resolvido(monkeypatch: pytest.MonkeyPatch) -> None:
    """No Windows o SDK só tem `gcloud.cmd`: `["gcloud", ...]` sem shell dá FileNotFoundError."""
    rodada = _Rodada()
    monkeypatch.setattr(
        bp.shutil, "which", lambda nome: "C:/sdk/bin/gcloud.cmd" if nome == "gcloud" else None
    )
    monkeypatch.setattr(bp.subprocess, "run", rodada)
    assert bp.main(_ARGS_APPLY) == 0
    assert rodada.chamadas
    assert {c[0] for c in rodada.chamadas} == {"C:/sdk/bin/gcloud.cmd"}


def test_apply_sem_gcloud_no_path_sai_2(monkeypatch: pytest.MonkeyPatch) -> None:
    rodada = _Rodada()
    monkeypatch.setattr(bp.shutil, "which", lambda _nome: None)
    monkeypatch.setattr(bp.subprocess, "run", rodada)
    assert bp.main(_ARGS_APPLY) == 2
    assert rodada.chamadas == []


def test_reexecucao_nao_pausa_scheduler_existente(monkeypatch: pytest.MonkeyPatch) -> None:
    """Depois do corte os schedulers estão ENABLED: reexecutar não pode pausá-los."""
    rodada = _Rodada(existentes=("scheduler jobs describe",))
    monkeypatch.setattr(bp.shutil, "which", lambda _nome: "gcloud")
    monkeypatch.setattr(bp.subprocess, "run", rodada)
    assert bp.main(_ARGS_APPLY) == 0
    assert not any(c[1:4] == ["scheduler", "jobs", "pause"] for c in rodada.chamadas)


def test_primeira_execucao_pausa_scheduler_novo(monkeypatch: pytest.MonkeyPatch) -> None:
    rodada = _Rodada()
    monkeypatch.setattr(bp.shutil, "which", lambda _nome: "gcloud")
    monkeypatch.setattr(bp.subprocess, "run", rodada)
    assert bp.main(_ARGS_APPLY) == 0
    pausados = [c[4] for c in rodada.chamadas if c[1:4] == ["scheduler", "jobs", "pause"]]
    assert pausados == ["v4-ads-mcp-resync-daily", "v4-ads-mcp-backup-weekly"]


def test_valores_para_o_github() -> None:
    """M3: o número do projeto só existe no `--apply`; o script imprime o que vai no GitHub."""
    v = bp.valores_para_o_github(project_id="p", project_number="123", region="southamerica-east1")
    assert v == {
        "GCP_PROJECT_ID": "p",
        "GCP_REGION": "southamerica-east1",
        "GCP_WIF_PROVIDER": "projects/123/locations/global/workloadIdentityPools/github/providers/github-provider",
        "GCP_DEPLOY_SA": "v4-ads-mcp-deploy@p.iam.gserviceaccount.com",
    }


def test_apply_imprime_os_valores_do_github(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(bp.shutil, "which", lambda _nome: "gcloud")
    monkeypatch.setattr(bp.subprocess, "run", _Rodada())
    assert bp.main(_ARGS_APPLY) == 0
    saida = capsys.readouterr().out
    assert (
        "GCP_WIF_PROVIDER=projects/123/locations/global/workloadIdentityPools/github/providers/github-provider"
        in saida
    )
    assert "GCP_DEPLOY_SA=v4-ads-mcp-deploy@p.iam.gserviceaccount.com" in saida


def test_gcloud_pendurado_sai_1_sem_traceback(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """M4: credencial vencida faz o gcloud tentar reautenticar e pendurar (CLAUDE.md)."""

    def _pendura(cmd: list[str], **_: Any) -> Any:
        raise bp.subprocess.TimeoutExpired(cmd, 120)

    monkeypatch.setattr(bp.shutil, "which", lambda _nome: "gcloud")
    monkeypatch.setattr(bp.subprocess, "run", _pendura)
    assert bp.main(_ARGS_APPLY) == 1
    assert "gcloud auth login" in capsys.readouterr().err
