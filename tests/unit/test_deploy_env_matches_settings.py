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
