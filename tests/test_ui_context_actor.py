"""Regression: inject_ui_context must not crash before active_mode is set."""

from __future__ import annotations


def test_inject_ui_context_sets_actor_display_for_dean(app):
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["authenticated"] = True
            sess["user"] = "dean-test"
            sess["username"] = "dean-test"
            sess["user_role"] = "college_dean"
            sess["active_mode"] = "dean"
        resp = client.get("/exams/finals")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert "actor_display_ar" not in html  # rendered value, not key name
        assert "عميد" in html or "dean-test" in html or "إدارة النظام" in html
