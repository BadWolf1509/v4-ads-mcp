"""F95: 3 secrets Supabase eram obrigatorios em Settings sem NENHUM consumidor.

`supabase_url`, `supabase_anon_key` e `supabase_service_key` eram campos
required e 3 dos 13 secrets montados no deploy, mas o grep confirma zero
leituras em `src/` — o banco e acessado so por `DATABASE_URL` (asyncpg cru, sem
lib supabase no pyproject). Todo ambiente (CI, testes, `.env`, Cloud Run, e os
dois Cloud Run Jobs) carregava 3 valores que nada le, e os testes mantinham
fixtures so pra satisfazer o `required`.

O guard abaixo vale mais que a remocao: ele cruza os dois lados do contrato.
A direcao que sobra (**campo required sem montagem**) e o footgun ja documentado
no CLAUDE.md — "adicione o secret tambem ao `--set-secrets` do deploy.yml, senao
o proximo deploy o apaga". Ate agora isso dependia de lembrar.
"""

from __future__ import annotations

import re
from pathlib import Path

from pydantic_settings import BaseSettings

from src.config import Settings

_DEPLOY = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "deploy.yml"


def _nomes_montados_no_deploy() -> set[str]:
    """Env vars que o Cloud Run recebe: `--set-env-vars` + `--set-secrets`."""
    texto = _DEPLOY.read_text(encoding="utf-8")
    nomes: set[str] = set()
    for flag in ("--set-env-vars", "--set-secrets"):
        for bloco in re.findall(re.escape(flag) + r'="([^"]*)"', texto):
            for par in bloco.split(","):
                if "=" in par:
                    nomes.add(par.split("=", 1)[0].strip().lower())
    return nomes


def _campos_obrigatorios(modelo: type[BaseSettings]) -> set[str]:
    return {nome for nome, campo in modelo.model_fields.items() if campo.is_required()}


def test_deploy_nao_monta_env_que_ninguem_le() -> None:
    """F95: env montado sem campo correspondente e custo e superficie a toa."""
    orfaos = _nomes_montados_no_deploy() - set(Settings.model_fields)
    assert not orfaos, (
        f"o deploy monta env vars que Settings nao declara (logo, ninguem le): {sorted(orfaos)}"
    )


def test_todo_campo_obrigatorio_chega_pelo_deploy() -> None:
    """A direcao inversa: campo required sem montagem = container que nao sobe.

    O erro so apareceria no boot da revisao nova, depois do build.
    """
    faltando = _campos_obrigatorios(Settings) - _nomes_montados_no_deploy()
    assert not faltando, (
        "campos obrigatorios de Settings que o deploy nao fornece — a revisao "
        f"nova nao sobe: {sorted(faltando)}"
    )


def test_settings_sobe_sem_as_variaveis_supabase() -> None:
    """F95: o `required` era o unico motivo de esses 3 valores existirem."""
    for morto in ("supabase_url", "supabase_anon_key", "supabase_service_key"):
        assert morto not in Settings.model_fields, (
            f"`{morto}` continua declarado em Settings e nada o le"
        )


# --------------------------------------------------------- os Cloud Run Jobs

# Os 3 processos do Procfile que rodam como Cloud Run Job. Todos chamam
# `get_settings()`, que valida o Settings INTEIRO na subida — entao cada um
# precisa dos mesmos campos obrigatorios do servico, mesmo o `migrate` e o
# `backup`, que funcionalmente so usam o banco.
_JOBS = ("v4-ads-mcp-migrate", "v4-ads-mcp-resync", "v4-ads-mcp-backup")


def _expandir_env_do_workflow(valor: str) -> str:
    """Resolve `${VAR}` usando o bloco `env:` do proprio workflow.

    A lista de secrets dos jobs vive num `env:` do job pra nao ser triplicada —
    triplicar seria criar a fonte de divergencia que este guard existe pra
    impedir. Sem expandir, o parser leria `${JOB_SECRETS}` e nao os nomes.
    """
    texto = _DEPLOY.read_text(encoding="utf-8")
    for nome, conteudo in re.findall(r'^      (\w+): "([^"]*)"$', texto, re.M):
        valor = valor.replace("${" + nome + "}", conteudo)
    return valor


def _nomes_montados_no_job(job: str) -> set[str]:
    """Env vars que o deploy declara pro job, via `--update-*` (merge)."""
    texto = _DEPLOY.read_text(encoding="utf-8")
    # o bloco do job vai do `gcloud run jobs update <job>` ate o proximo step
    inicio = texto.index(f"gcloud run jobs update {job}")
    resto = texto[inicio:]
    fim = resto.find(chr(10) + "      - name:")
    bloco = resto if fim == -1 else resto[:fim]
    nomes: set[str] = set()
    for flag in ("--update-env-vars", "--update-secrets", "--set-env-vars", "--set-secrets"):
        for bruto in re.findall(re.escape(flag) + r'="([^"]*)"', bloco):
            trecho = _expandir_env_do_workflow(bruto)
            for par in trecho.split(","):
                if "=" in par:
                    nomes.add(par.split("=", 1)[0].strip().lower())
    return nomes


def test_todo_job_recebe_os_campos_obrigatorios() -> None:
    """Job sem os 8 campos obrigatorios nao sobe — e falha CALADO.

    O deploy ja re-aponta imagem e `--command` dos 3 a cada push (self-healing
    contra drift manual), mas o env ficava so na criacao a mao: nao havia fonte
    de verdade nem guard. Evidencia de que a config manual deriva: o F95
    registrou que os jobs seguem montando os 3 secrets Supabase removidos.

    `migrate` roda em todo deploy, entao falharia alto. `resync` (diario) e
    `backup` (semanal, o artefato de compliance) falhariam quietos — foi
    exatamente essa cegueira que o F93 atacou ao auditar crash de job.
    """
    obrigatorios = _campos_obrigatorios(Settings)
    problemas: list[str] = []
    for job in _JOBS:
        faltando = obrigatorios - _nomes_montados_no_job(job)
        if faltando:
            problemas.append(f"{job}: {sorted(faltando)}")
    assert not problemas, (
        "Cloud Run Jobs sem campo obrigatorio de Settings no deploy.yml — "
        "`get_settings()` valida tudo na subida: " + "; ".join(problemas)
    )
