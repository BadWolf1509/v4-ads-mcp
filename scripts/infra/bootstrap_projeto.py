"""Bootstrap reprodutível de um projeto GCP para o serviço (migração para o projeto do Gmail, 25/11/2026).

Monta a lista de comandos `gcloud` que reproduz o inventário medido em 25/11 no projeto
`v4-ads-mcp` (spec `docs/superpowers/specs/2026-11-25-migracao-projeto-gmail-design.md`).

Sem `--apply`, só imprime. Com `--apply`, executa um a um, sem shell (lista de argumentos:
o `/cnb/process/*` não passa por Git Bash, F66); quando um comando tem `checagem` e ela
retorna 0, o recurso já existe e a criação é pulada — reexecutar é seguro.

Fica de FORA de propósito:
- valores de secret: os secrets nascem vazios; o valor entra depois, por arquivo (F47);
- canal de e-mail e as 5 policies de alerta: o runbook REST do `infra-setup.md` cria
  (o componente `gcloud alpha monitoring` não está instalado); o script só lembra;
- os schedulers nascem PAUSADOS: um resync no projeto novo antes do corte revogaria
  grants do mesmo banco (spec, Fase 3 passo 2).

Uso:
    python -m scripts.infra.bootstrap_projeto --project-id X --region Y --alert-email Z [--apply]
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_PADRAO = "BadWolf1509/v4-ads-mcp"
LIFECYCLE = Path(__file__).with_name("lifecycle-backup.json")

SERVICOS = (
    "run.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "secretmanager.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "sts.googleapis.com",
    "cloudscheduler.googleapis.com",
    "storage.googleapis.com",
    "monitoring.googleapis.com",
    "logging.googleapis.com",
    "googleads.googleapis.com",
)
PAPEIS_DEPLOY = (
    "roles/artifactregistry.writer",
    "roles/cloudbuild.builds.editor",
    "roles/iam.serviceAccountUser",
    "roles/run.admin",
    "roles/serviceusage.serviceUsageConsumer",
    "roles/storage.admin",
    "roles/storage.objectViewer",
)
SECRETS = (
    "database-url",
    "session-signing-key",
    "aes-master-key",
    "google-oauth-client-id",
    "google-oauth-client-secret",
    "google-ads-login-customer-id",
    "meta-app-id",
    "meta-app-secret",
    "meta-system-user-token",
)
# (tipo, max_retries, task_timeout) — medidos em 25/11.
JOBS = (("migrate", "1", "600s"), ("resync", "3", "600s"), ("backup", "1", "900s"))
# (nome, cron, job) — fuso America/Sao_Paulo.
SCHEDULERS = (
    ("v4-ads-mcp-resync-daily", "0 6 * * *", "v4-ads-mcp-resync"),
    ("v4-ads-mcp-backup-weekly", "0 5 * * 0", "v4-ads-mcp-backup"),
)
# O primeiro deploy troca a imagem dos jobs (`gcloud run jobs update --image`).
IMAGEM_PLACEHOLDER = "us-docker.pkg.dev/cloudrun/container/hello"


@dataclass(frozen=True)
class Comando:
    """`checagem` retorna 0 quando o recurso já existe; `None` = comando idempotente."""

    checagem: list[str] | None
    criacao: list[str]
    # Roda só quando `criacao` acabou de rodar: pausar um scheduler que já existe (ENABLED
    # depois do corte) pararia o resync e o backup de produção.
    apos_criar: list[str] | None = None


def montar_comandos(
    *,
    project_id: str,
    region: str,
    alert_email: str,
    repo: str = REPO_PADRAO,
    project_number: str = "<PROJECT_NUMBER>",
) -> list[Comando]:
    p = f"--project={project_id}"
    r = f"--region={region}"
    sa = {
        n: f"{n}@{project_id}.iam.gserviceaccount.com"
        for n in ("v4-ads-mcp-runtime", "v4-ads-mcp-deploy", "v4-ads-mcp-scheduler")
    }
    bucket = f"gs://{project_id}-backups"
    cmds: list[Comando] = []

    def binding_projeto(membro: str, papel: str) -> None:
        cmds.append(
            Comando(
                None,
                [
                    "gcloud",
                    "projects",
                    "add-iam-policy-binding",
                    project_id,
                    f"--member={membro}",
                    f"--role={papel}",
                    "--condition=None",
                ],
            )
        )

    cmds.append(Comando(None, ["gcloud", "services", "enable", *SERVICOS, p]))
    cmds.append(
        Comando(
            [
                "gcloud",
                "artifacts",
                "repositories",
                "describe",
                "v4-ads-mcp",
                f"--location={region}",
                p,
            ],
            [
                "gcloud",
                "artifacts",
                "repositories",
                "create",
                "v4-ads-mcp",
                "--repository-format=docker",
                f"--location={region}",
                p,
            ],
        )
    )
    for nome, email in sa.items():
        cmds.append(
            Comando(
                ["gcloud", "iam", "service-accounts", "describe", email, p],
                ["gcloud", "iam", "service-accounts", "create", nome, f"--display-name={nome}", p],
            )
        )
    for papel in PAPEIS_DEPLOY:
        binding_projeto(f"serviceAccount:{sa['v4-ads-mcp-deploy']}", papel)
    binding_projeto(
        f"serviceAccount:{sa['v4-ads-mcp-runtime']}", "roles/secretmanager.secretAccessor"
    )
    # O build `--pack` roda como o SA padrão do Compute; em projeto novo ele pode não ter
    # papel nenhum (grant automático desligado) — não medido, então concede explícito.
    binding_projeto(
        f"serviceAccount:{project_number}-compute@developer.gserviceaccount.com",
        "roles/cloudbuild.builds.builder",
    )

    cmds.append(
        Comando(
            [
                "gcloud",
                "iam",
                "workload-identity-pools",
                "describe",
                "github",
                "--location=global",
                p,
            ],
            [
                "gcloud",
                "iam",
                "workload-identity-pools",
                "create",
                "github",
                "--location=global",
                "--display-name=github",
                p,
            ],
        )
    )
    cmds.append(
        Comando(
            [
                "gcloud",
                "iam",
                "workload-identity-pools",
                "providers",
                "describe",
                "github-provider",
                "--workload-identity-pool=github",
                "--location=global",
                p,
            ],
            [
                "gcloud",
                "iam",
                "workload-identity-pools",
                "providers",
                "create-oidc",
                "github-provider",
                "--workload-identity-pool=github",
                "--location=global",
                "--issuer-uri=https://token.actions.githubusercontent.com",
                "--attribute-mapping=google.subject=assertion.sub,attribute.repository=assertion.repository",
                f"--attribute-condition=assertion.repository=='{repo}'",
                p,
            ],
        )
    )
    cmds.append(
        Comando(
            None,
            [
                "gcloud",
                "iam",
                "service-accounts",
                "add-iam-policy-binding",
                sa["v4-ads-mcp-deploy"],
                "--role=roles/iam.workloadIdentityUser",
                f"--member=principalSet://iam.googleapis.com/projects/{project_number}/locations/global/workloadIdentityPools/github/attribute.repository/{repo}",
                p,
            ],
        )
    )

    cmds.append(
        Comando(
            ["gcloud", "storage", "buckets", "describe", bucket, p],
            [
                "gcloud",
                "storage",
                "buckets",
                "create",
                bucket,
                f"--location={region}",
                "--uniform-bucket-level-access",
                p,
            ],
        )
    )
    cmds.append(
        Comando(
            None,
            ["gcloud", "storage", "buckets", "update", bucket, f"--lifecycle-file={LIFECYCLE}", p],
        )
    )
    cmds.append(
        Comando(
            None,
            [
                "gcloud",
                "storage",
                "buckets",
                "add-iam-policy-binding",
                bucket,
                f"--member=serviceAccount:{sa['v4-ads-mcp-runtime']}",
                "--role=roles/storage.objectCreator",
                p,
            ],
        )
    )

    for nome in SECRETS:
        cmds.append(
            Comando(
                ["gcloud", "secrets", "describe", nome, p],
                ["gcloud", "secrets", "create", nome, "--replication-policy=automatic", p],
            )
        )

    for tipo, retries, timeout in JOBS:
        job = f"v4-ads-mcp-{tipo}"
        cmds.append(
            Comando(
                ["gcloud", "run", "jobs", "describe", job, r, p],
                [
                    "gcloud",
                    "run",
                    "jobs",
                    "create",
                    job,
                    f"--image={IMAGEM_PLACEHOLDER}",
                    f"--command=/cnb/process/{tipo}",
                    f"--max-retries={retries}",
                    f"--task-timeout={timeout}",
                    "--memory=512Mi",
                    "--cpu=1",
                    f"--service-account={sa['v4-ads-mcp-runtime']}",
                    r,
                    p,
                ],
            )
        )
    for _nome, _cron, job in SCHEDULERS:
        cmds.append(
            Comando(
                None,
                [
                    "gcloud",
                    "run",
                    "jobs",
                    "add-iam-policy-binding",
                    job,
                    f"--member=serviceAccount:{sa['v4-ads-mcp-scheduler']}",
                    "--role=roles/run.invoker",
                    r,
                    p,
                ],
            )
        )

    for nome, cron, job in SCHEDULERS:
        cmds.append(
            Comando(
                ["gcloud", "scheduler", "jobs", "describe", nome, f"--location={region}", p],
                [
                    "gcloud",
                    "scheduler",
                    "jobs",
                    "create",
                    "http",
                    nome,
                    f"--location={region}",
                    f"--schedule={cron}",
                    "--time-zone=America/Sao_Paulo",
                    f"--uri=https://{region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/{project_id}/jobs/{job}:run",
                    "--http-method=POST",
                    f"--oauth-service-account-email={sa['v4-ads-mcp-scheduler']}",
                    p,
                ],
                apos_criar=[
                    "gcloud",
                    "scheduler",
                    "jobs",
                    "pause",
                    nome,
                    f"--location={region}",
                    p,
                ],
            )
        )

    _ = alert_email  # usado só no lembrete impresso por `main` (canal e policies fora do script).
    return cmds


def _numero_do_projeto(gcloud: str, project_id: str) -> str:
    saida = subprocess.run(
        [gcloud, "projects", "describe", project_id, "--format=value(projectNumber)"],
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    )
    return saida.stdout.strip()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--project-id", required=True)
    ap.add_argument("--region", required=True)
    ap.add_argument("--alert-email", required=True)
    ap.add_argument("--repo", default=REPO_PADRAO)
    ap.add_argument("--apply", action="store_true", help="executa (sem isto, só imprime)")
    a = ap.parse_args(argv)

    # No Windows o SDK só tem `gcloud.cmd`: `["gcloud", ...]` sem shell dá FileNotFoundError
    # (o CreateProcess só completa `.exe`). `shutil.which` resolve o caminho com a extensão.
    gcloud = shutil.which("gcloud") if a.apply else "gcloud"
    if gcloud is None:
        print("gcloud não encontrado no PATH", file=sys.stderr)
        return 2
    numero = _numero_do_projeto(gcloud, a.project_id) if a.apply else "<PROJECT_NUMBER>"
    comandos = montar_comandos(
        project_id=a.project_id,
        region=a.region,
        alert_email=a.alert_email,
        repo=a.repo,
        project_number=numero,
    )

    def _exe(cmd: list[str]) -> list[str]:
        return [gcloud, *cmd[1:]]

    for c in comandos:
        print(("$ " if a.apply else "") + " ".join(c.criacao))
        if c.apos_criar is not None and not a.apply:
            print("  (só se acabou de criar) " + " ".join(c.apos_criar))
        if not a.apply:
            continue
        if (
            c.checagem is not None
            and subprocess.run(_exe(c.checagem), capture_output=True, timeout=120).returncode == 0
        ):
            print("  = já existe, pulado")
            continue
        for passo in (c.criacao, c.apos_criar):
            if passo is not None and subprocess.run(_exe(passo), timeout=600).returncode != 0:
                print(
                    "  ! falhou — corrija e rode de novo (o script é reexecutável)", file=sys.stderr
                )
                return 1

    print(
        f"\nFaltam à mão: valores dos {len(SECRETS)} secrets (por arquivo, nunca por pipe — F47);"
        f" canal de e-mail {a.alert_email} e as 5 policies (runbook REST do infra-setup.md);"
        " GitHub secrets GCP_* e vars PUBLIC_BASE_URL/META_BUSINESS_ID. Schedulers ficam PAUSADOS até o corte."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
