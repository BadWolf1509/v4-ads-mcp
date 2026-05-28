from src.web.routes import _toggle_checkbox_fragment


def test_toggle_fragment_escapes_injection():
    frag = _toggle_checkbox_fragment(
        post_url="/admin/access/meta/toggle",
        vals={"manager_id": "m1", "ad_account_id": "act_1' hx-on='evil"},
        checked=True,
    )
    # the injected single-quote must be HTML-escaped so it can't break the attribute
    assert "hx-on='evil" not in frag
    assert "&#x27;" in frag or "&#39;" in frag


def test_toggle_fragment_checked_state():
    on = _toggle_checkbox_fragment(post_url="/x", vals={"a": "b"}, checked=True)
    off = _toggle_checkbox_fragment(post_url="/x", vals={"a": "b"}, checked=False)
    assert "checked" in on and "checked" not in off
