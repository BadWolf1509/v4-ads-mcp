"""classify_partial: status MEDIDO decide primeiro, error so refina.

CRITICAL achado na revisao pos-Task 4 (fix round 1/5): antes desta mudanca,
`error is None` sozinho decidia "a linha aplicou". Isso ficou errado quando
`erros_por_indice` (Task 2) passou a devolver `error=None` tambem para uma
linha que o WhichOneof MEDIU como falha, mas cujo motivo nao foi lido
(leitura.medido=False). Uma falha real virava "ok_status" so porque o motivo
nao pode ser desempacotado -- o status mentia, na direcao mais perigosa.

O guard central deste arquivo e o combo que nenhum teste da suite cobria:
status="failed" + error=None tem que continuar "failed".
"""

from src.mcp.tools._common import classify_partial

_EXISTS_PATTERNS = ("CRITERION_EXISTS", "DUPLICATE_KEYWORD")


def test_status_failed_com_error_none_nao_vira_ok_status() -> None:
    """O guard critico: linha MEDIDA como falha, motivo nao lido, continua failed."""
    resultado = classify_partial(
        None,
        status="failed",
        ok_status="added",
        exists_status="already_exists",
        exists_patterns=_EXISTS_PATTERNS,
    )
    assert resultado == "failed", (
        "error=None por leitura nao-confiavel nao pode virar ok_status -- "
        "o WhichOneof ja mediu que esta linha falhou"
    )


def test_status_success_e_ok_status_mesmo_com_error_setado() -> None:
    """status="success" manda, mesmo que error venha preenchido (nao deveria, mas
    se vier, quem decide e o veredito medido, nao o texto)."""
    resultado = classify_partial(
        "algum residuo de erro",
        status="success",
        ok_status="added",
        exists_status="already_exists",
        exists_patterns=_EXISTS_PATTERNS,
    )
    assert resultado == "added"


def test_status_failed_com_error_que_casa_exists_pattern() -> None:
    resultado = classify_partial(
        "CRITERION_EXISTS: ja estava la",
        status="failed",
        ok_status="added",
        exists_status="already_exists",
        exists_patterns=_EXISTS_PATTERNS,
    )
    assert resultado == "already_exists"


def test_status_failed_com_error_lido_que_nao_casa_pattern() -> None:
    """Comportamento pre-existente preservado: erro lido, sem match -> failed."""
    resultado = classify_partial(
        "INVALID_ARGUMENT: campo invalido",
        status="failed",
        ok_status="added",
        exists_status="already_exists",
        exists_patterns=_EXISTS_PATTERNS,
    )
    assert resultado == "failed"
