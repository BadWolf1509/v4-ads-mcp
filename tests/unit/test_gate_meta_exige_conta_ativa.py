"""Guard DERIVADO: o gate nao pode voltar a ler so a tabela de grants.

Sem isto alguem 'simplifica' o JOIN e o gate volta a liberar ex-cliente sem
nenhum teste vermelho — foi assim que o F86 renasceu como F109.
"""

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2] / "src" / "db" / "repositories"


def test_can_manager_access_meta_consulta_estado_da_conta() -> None:
    fonte = (_REPO / "manager_meta_account_access.py").read_text(encoding="utf-8")
    corpo = re.search(r"async def can_manager_access\(.*?\n(?=async def |\Z)", fonte, re.S)
    assert corpo, "can_manager_access sumiu ou mudou de nome"
    sql = corpo.group(0)
    assert "meta_ad_accounts" in sql, "o gate precisa cruzar com o inventario"
    assert "is_active" in sql, "conta fora da parceria tem que ser negada aqui tambem"
    assert "revoked_at IS NULL" in sql, "grant revogado nao pode dar acesso"
