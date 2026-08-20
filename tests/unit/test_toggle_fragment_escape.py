from src.web.routes import _toggle_checkbox_fragment


def test_toggle_fragment_escapes_injection():
    frag = _toggle_checkbox_fragment(
        post_url="/admin/access/meta/toggle",
        manager_id="m1",
        account_id="act_1' hx-on='evil",
        account_field="ad_account_id",
        checked=True,
    )
    # O id agora alimenta DOIS atributos (hx-vals e aria-labelledby), entao a
    # aspa injetada precisa sair escapada nos dois — senao fecha o atributo.
    assert "hx-on='evil" not in frag
    assert "&#x27;" in frag or "&#39;" in frag


def test_toggle_fragment_checked_state():
    comum = {
        "post_url": "/x",
        "manager_id": "m1",
        "account_id": "a1",
        "account_field": "customer_id",
    }
    on = _toggle_checkbox_fragment(**comum, checked=True)
    off = _toggle_checkbox_fragment(**comum, checked=False)
    # Checagem posicional em vez de `"checked" in frag`. O motivo original era o
    # hx-on embutido, que continha "this.checked" nos DOIS estados; ele saiu em
    # 2026-08-11 (handler virou delegado), mas a forma posicional segue melhor:
    # nao quebra se algum atributo novo mencionar a palavra.
    assert '"checkbox" checked' in on
    assert '"checkbox" checked' not in off
