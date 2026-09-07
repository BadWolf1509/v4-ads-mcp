"""M2: a imagem de um Cloud Run Job nao pode chegar antes da migration.

O `deploy.yml` atualiza a imagem de tres Cloud Run Jobs (`migrate`, `resync`,
`backup`) e depois EXECUTA um deles — o `migrate` — para aplicar as migrations
pendentes. Ate 2026-09-07 os tres updates vinham antes do execute, e isso tem
dois modos de falha, um transitorio e um permanente:

- **transitorio (1-3 min por deploy):** entre o update do `resync` e o fim das
  migrations, o Cloud Scheduler pode disparar o job diario, que ja roda o codigo
  do commit novo contra o schema velho. A migration 009 estreou
  `SELECT ... last_missed_on` em `list_inventory_rows` — leitura com lista
  EXPLICITA de colunas, que falha alto quando a coluna nao existe.
- **permanente:** se o step de migration FALHAR, o job fica com a imagem nova e
  o schema velho para sempre. O `Rollback on failure` do mesmo workflow reverte
  o TRAFEGO do servico e nunca a imagem de um job — nao ha caminho de volta
  automatico.

A direcao inversa (schema novo + codigo velho) e segura e foi verificada: no
codigo anterior nenhum caminho le `last_missed_on`, e os demais reads sao
`SELECT *` mapeados por NOME (`_row_to_account`), imunes a coluna nova.

**O guard afirma a PROPRIEDADE, nao a lista de steps.** Um quarto Cloud Run Job
que alguem acrescente amanha entra no escopo sozinho; enumerar `resync` e
`backup` pelo nome deixaria o proximo de fora exatamente como este ficou.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

_DEPLOY = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "deploy.yml"

_ATUALIZA = re.compile(r"gcloud run jobs update\s+(\S+)")
_EXECUTA = re.compile(r"gcloud run jobs execute\s+(\S+)")


class EscopoVazioError(AssertionError):
    """Guard que nao encontrou nenhum step de job nao esta guardando nada."""


def _steps() -> list[dict[str, Any]]:
    return yaml.safe_load(_DEPLOY.read_text(encoding="utf-8"))["jobs"]["deploy"]["steps"]


def _mapa(steps: list[dict[str, Any]]) -> tuple[dict[str, int], dict[str, int]]:
    """(job cuja IMAGEM e atualizada -> indice, job EXECUTADO -> indice).

    Le o nome do job do proprio comando `gcloud`, nao do `name:` do step: o
    rotulo humano e livre e ja divergiu do que o step faz neste repositorio.
    """
    atualiza: dict[str, int] = {}
    executa: dict[str, int] = {}
    for i, step in enumerate(steps):
        corpo = step.get("run") or ""
        for job in _ATUALIZA.findall(corpo):
            atualiza[job] = i
        for job in _EXECUTA.findall(corpo):
            executa[job] = i
    if not atualiza or not executa:
        raise EscopoVazioError(
            "nenhum `gcloud run jobs update`/`execute` encontrado no deploy — "
            "o guard varreu o nada e passaria por vacuidade"
        )
    return atualiza, executa


def _violacoes(atualiza: dict[str, int], executa: dict[str, int]) -> list[str]:
    """Cada job executado impoe DUAS ordens; devolve as que o documento quebra."""
    erros: list[str] = []
    for alvo, i_exec in executa.items():
        i_upd = atualiza.get(alvo)
        if i_upd is None:
            erros.append(f"`{alvo}` e executado mas a imagem dele nunca e atualizada")
        elif i_upd > i_exec:
            erros.append(
                f"`{alvo}` e executado (step {i_exec}) ANTES de receber a imagem do "
                f"commit (step {i_upd}) — as migrations do commit nem existem no container"
            )
        for outro, i_outro in atualiza.items():
            if outro != alvo and i_outro < i_exec:
                erros.append(
                    f"`{outro}` recebe a imagem nova (step {i_outro}) ANTES de "
                    f"`{alvo}` migrar o schema (step {i_exec}) — janela de codigo "
                    "novo com schema velho, e permanente se a migration falhar"
                )
    return erros


def test_ordem_dos_jobs_no_deploy() -> None:
    assert _violacoes(*_mapa(_steps())) == []


def test_o_guard_enxerga_a_ordem_errada() -> None:
    """Guard que nunca viu vermelho nao e guard: a ordem pre-fix tem que acusar.

    Reproduz o `deploy.yml` como estava ate 2026-09-07 — os tres updates antes
    do execute — e exige as DUAS violacoes (resync e backup), nao "alguma".
    """
    pre_fix = [
        {"run": "gcloud run jobs update v4-ads-mcp-migrate --image=x"},
        {"run": "gcloud run jobs update v4-ads-mcp-resync --image=x"},
        {"run": "gcloud run jobs update v4-ads-mcp-backup --image=x"},
        {"run": "gcloud run jobs execute v4-ads-mcp-migrate --wait"},
    ]
    erros = _violacoes(*_mapa(pre_fix))
    assert len(erros) == 2, erros
    assert any("v4-ads-mcp-resync" in e for e in erros)
    assert any("v4-ads-mcp-backup" in e for e in erros)


def test_o_guard_enxerga_o_execute_antes_do_proprio_update() -> None:
    """A outra ordem: migrar com a imagem VELHA passa verde e nao aplica nada."""
    invertido = [
        {"run": "gcloud run jobs execute v4-ads-mcp-migrate --wait"},
        {"run": "gcloud run jobs update v4-ads-mcp-migrate --image=x"},
    ]
    erros = _violacoes(*_mapa(invertido))
    assert erros and "ANTES de receber a imagem" in erros[0]


def test_o_guard_recusa_escopo_vazio() -> None:
    """Sem step de job nenhum, a ausencia de violacao seria vacuidade."""
    with pytest.raises(EscopoVazioError):
        _mapa([{"run": "echo nada a ver"}])
