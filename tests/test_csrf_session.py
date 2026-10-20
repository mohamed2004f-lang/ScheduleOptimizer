"""CSRF على مسارات الجلسة — يبقى إعفاء الدعوة الخارجية والخروج."""
import re


def _enable_csrf(app):
    prev = app.config.get("WTF_CSRF_ENABLED")
    app.config["WTF_CSRF_ENABLED"] = True
    app.config["WTF_CSRF_SSL_STRICT"] = False
    return prev


def _restore_csrf(app, prev):
    app.config["WTF_CSRF_ENABLED"] = prev


def _csrf_from_html(html: bytes) -> str:
    m = re.search(rb'name="csrf-token"\s+content="([^"]+)"', html)
    assert m, html[:800]
    return m.group(1).decode()


def _login_with_csrf(client, username="admin-test", password="TestP@ssw0rd!"):
    page = client.get("/login")
    assert page.status_code == 200
    token = _csrf_from_html(page.data)
    return client.post(
        "/auth/login",
        json={"username": username, "password": password, "csrf_token": token},
        headers={"X-CSRFToken": token, "Accept": "application/json"},
    )


def test_login_requires_csrf(app):
    prev = _enable_csrf(app)
    try:
        with app.test_client() as c:
            missing = c.post(
                "/auth/login",
                json={"username": "admin-test", "password": "TestP@ssw0rd!"},
                headers={"Accept": "application/json"},
            )
            assert missing.status_code == 400
            assert (missing.get_json() or {}).get("error") == "CSRF_FAILED"

            ok = _login_with_csrf(c)
            assert ok.status_code == 200, ok.get_data(as_text=True)
            body = ok.get_json() or {}
            assert body.get("status") in ("ok", "mfa_required") or body.get("authenticated")
    finally:
        _restore_csrf(app, prev)


def test_admin_department_scope_requires_csrf(app):
    prev = _enable_csrf(app)
    try:
        with app.test_client() as c:
            login = _login_with_csrf(c)
            assert login.status_code == 200
            missing = c.post(
                "/auth/admin_department_scope",
                json={"department_id": None},
                headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"},
            )
            assert missing.status_code == 400
            assert (missing.get_json() or {}).get("error") == "CSRF_FAILED"

            page = c.get("/change_password")
            assert page.status_code == 200
            token = _csrf_from_html(page.data)
            ok = c.post(
                "/auth/admin_department_scope",
                json={"department_id": None},
                headers={
                    "Accept": "application/json",
                    "X-Requested-With": "XMLHttpRequest",
                    "X-CSRFToken": token,
                },
            )
            assert ok.status_code == 200, ok.get_data(as_text=True)
            assert (ok.get_json() or {}).get("status") == "ok"
    finally:
        _restore_csrf(app, prev)


def test_students_api_post_requires_csrf(app):
    prev = _enable_csrf(app)
    try:
        with app.test_client() as c:
            _login_with_csrf(c)
            missing = c.post(
                "/api/v1/students",
                json={"student_id": "csrf-no", "name": "تجربة"},
                headers={"Accept": "application/json"},
            )
            assert missing.status_code == 400
            assert (missing.get_json() or {}).get("error") == "CSRF_FAILED"
    finally:
        _restore_csrf(app, prev)


def test_academic_calendar_post_requires_csrf(app):
    prev = _enable_csrf(app)
    try:
        with app.test_client() as c:
            login = _login_with_csrf(c)
            assert login.status_code == 200
            payload = {
                "academic_year": "2065/2066",
                "term": "fall",
                "items": [
                    {"item_no": 1, "title": "تجديد القيد", "event_date": "2065-09-07", "is_deleted": 0}
                ],
            }
            missing = c.post(
                "/academic_calendar/items",
                json=payload,
                headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"},
            )
            assert missing.status_code == 400
            assert (missing.get_json() or {}).get("error") == "CSRF_FAILED"

            page = c.get("/academic_calendar_page")
            assert page.status_code == 200
            token = _csrf_from_html(page.data)
            ok = c.post(
                "/academic_calendar/items",
                json=payload,
                headers={
                    "Accept": "application/json",
                    "X-Requested-With": "XMLHttpRequest",
                    "X-CSRFToken": token,
                },
            )
            assert ok.status_code == 200, ok.get_data(as_text=True)
            body = ok.get_json() or {}
            assert body.get("status") == "ok"
            first = next(i for i in body["items"] if i["item_no"] == 1)
            assert first["event_date"] == "2065-09-07"
    finally:
        _restore_csrf(app, prev)


def test_term_offerings_save_requires_csrf(app):
    prev = _enable_csrf(app)
    try:
        with app.test_client() as c:
            login = _login_with_csrf(c)
            assert login.status_code == 200
            missing = c.post(
                "/term_offerings/save",
                json={"course_names": []},
                headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"},
            )
            assert missing.status_code == 400
            assert (missing.get_json() or {}).get("error") == "CSRF_FAILED"

            page = c.get("/term_offerings")
            assert page.status_code == 200
            token = _csrf_from_html(page.data)
            ok = c.post(
                "/term_offerings/save",
                json={"course_names": [], "csrf_token": token},
                headers={
                    "Accept": "application/json",
                    "X-Requested-With": "XMLHttpRequest",
                    "X-CSRFToken": token,
                },
            )
            assert ok.status_code == 200, ok.get_data(as_text=True)
            assert (ok.get_json() or {}).get("status") == "ok"

            body_only = c.post(
                "/term_offerings/save",
                json={"course_names": [], "csrf_token": token},
                headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"},
            )
            assert body_only.status_code == 200, body_only.get_data(as_text=True)
    finally:
        _restore_csrf(app, prev)
