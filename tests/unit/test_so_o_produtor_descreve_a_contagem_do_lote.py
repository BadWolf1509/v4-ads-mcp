"""F182, 2ª instância: a contagem do lote só é descrita por quem a produz.

O F182 consertou a description do `apply_change` e deixou a MESMA afirmação viva em
`remove_audience`, que enumerava `applied_count` e `failed_count` como campos a ler.
Instância corrigida, classe aberta — e foi uma sessão-par lendo a tool em uso real que
levantou a suspeita, não este repo.

A invariante não é "não mentir sobre `failed_count`": isso é prosa, e prosa não se
assere sem escrever um casador que erra pelo que não está na lista. Ela é **estrutural**,
e sai da arquitetura que o próprio `remove_audience` documenta no docstring: quem
responde ao gestor é o `apply_change`, e ele é GENÉRICO — nenhuma outra tool sabe sob
qual regime o lote rodou. Logo só ele pode descrever `failed_count`/`applied_count`.
Qualquer outra description que os cite reafirma, sem o contexto que os qualifica, uma
contagem que o próprio produtor manda não ler (F182 para o regime, F184 para o efeito).

**Fora do escopo, de propósito:**

- `partial_failure` / `partial_failures`. Uma tool dizer "rodo em partial_failure mode"
  descreve o que ELA faz — manda `__partial_failure__` no payload — e é verdade.
- `changed_count`. É justamente o campo que se deve ler.
- A prosa do `apply_change`. Asserir as frases dele aqui travaria qualquer reescrita
  legítima da explicação; o que garante o conteúdo são os testes de comportamento do
  envelope em `test_apply_change.py`, não uma asserção de texto.
- A promessa de caminho feliz do F180 em `create_rsa`/`update_rsa` ("se o Google recusar
  um, os demais são aplicados"). É condicional: verdadeira no texto, enganosa na prática,
  porque o antecedente quase não dispara — o Google aceita e não executa. Corrigi as duas
  à mão e **não sei** escrever uma asserção que separe essa redação de uma honesta. Dizer
  isso aqui vale mais do que um guard que finge cobri-la.
"""

from __future__ import annotations

from tests.unit._guard_harness import EscopoVazioError

_TOKENS = ("failed_count", "applied_count")
_PRODUTOR = "apply_change"

# 68 tools registradas em 2026-09-20. O piso protege contra o registry carregar pela
# metade: um guard que varre 5 descriptions passa por vacuidade e não diz nada — foi
# exatamente assim que o scan do F183 devolveu ZERO e quase virou "nada a fazer".
_PISO_DE_DESCRIPTIONS = 60


def _descriptions_registradas() -> dict[str, str]:
    """`{tool: description}` do que o cliente MCP recebe no handshake.

    Lê o REGISTRY, não o source: `grep` e `ast.literal_eval` já erraram esta mesma
    medição no F183, o segundo devolvendo zero porque nenhum `_SCHEMA` é literal puro.
    """
    from src.mcp.tools._registry import all_tools, import_all_tools

    import_all_tools()
    registradas = {t.name: (t.description or "") for t in all_tools()}
    if len(registradas) < _PISO_DE_DESCRIPTIONS:
        raise EscopoVazioError(
            f"só {len(registradas)} descriptions encontradas (piso: "
            f"{_PISO_DE_DESCRIPTIONS}, observadas 68 em 2026-09-20). O registry não "
            "carregou por inteiro, e o guard estaria passando sobre uma fração da "
            "superfície."
        )
    return registradas


def _tools_que_citam_a_contagem() -> set[str]:
    return {
        nome
        for nome, descr in _descriptions_registradas().items()
        if any(token in descr for token in _TOKENS)
    }


def test_o_produtor_de_fato_descreve_a_contagem() -> None:
    """Controle positivo: se nem o `apply_change` cita os campos, o casador quebrou.

    Sem esta metade, o guard irmão passaria verde por não achar nada — que é o modo de
    falha mais caro deste repo, porque zero se parece com "está tudo certo".
    """
    assert _PRODUTOR in _tools_que_citam_a_contagem(), (
        f"nenhum dos tokens {_TOKENS} aparece na description do `{_PRODUTOR}`, que é "
        "quem produz esses campos. Ou a description foi esvaziada, ou o casador deste "
        "guard parou de casar — nos dois casos o guard irmão está passando por vacuidade."
    )


def test_so_o_produtor_descreve_a_contagem_do_lote() -> None:
    citam = _tools_que_citam_a_contagem()
    intrusas = sorted(citam - {_PRODUTOR})
    assert not intrusas, (
        "description de tool que não produz a contagem citando "
        f"{_TOKENS}: {', '.join(intrusas)}. Só o `{_PRODUTOR}` responde ao gestor e só "
        "ele sabe sob qual regime o lote rodou; citar a contagem em outra tool a "
        "reafirma SEM a qualificação que o F182 e o F184 exigem — `failed_count` mede "
        "aceitação e não execução, e zero ali costuma significar 'o Google não "
        "reportou'. Descreva o que a SUA tool faz (que ela roda em partial_failure "
        "mode) e aponte pro `efeito` por linha, que é o que se lê."
    )
