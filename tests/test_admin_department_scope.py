"""سياق قسم المسؤول: الجلسة وواجهة التصفية."""
import uuid


class TestAdminDepartmentScope:
    def test_auth_check_includes_scope_null_for_admin(self, app):
        with app.test_client() as c:
            c.post(
                "/auth/login",
                json={"username": "admin-test", "password": "TestP@ssw0rd!"},
            )
            r = c.get("/auth/check")
            assert r.status_code == 200
            data = r.get_json()
            assert data.get("admin_department_scope") is None
            assert data.get("capabilities", {}).get("can_switch_department_scope") is True

    def test_set_scope_requires_department_row(self, app, db_conn):
        code = "TSC" + uuid.uuid4().hex[:8].upper()
        cur = db_conn.cursor()
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (code, "قسم تجربة", "Scope Dept"),
        )
        db_conn.commit()
        did = cur.execute("SELECT id FROM departments WHERE code = ?", (code,)).fetchone()[0]

        with app.test_client() as c:
            c.post(
                "/auth/login",
                json={"username": "admin-test", "password": "TestP@ssw0rd!"},
            )
            pr = c.post(
                "/auth/admin_department_scope",
                json={"department_id": did},
                headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"},
            )
            assert pr.status_code == 200
            pj = pr.get_json()
            assert pj.get("status") == "ok"
            assert pj.get("admin_department_scope", {}).get("id") == did

            chk = c.get("/auth/check")
            assert chk.get_json().get("admin_department_scope", {}).get("code") == code

            clr = c.post(
                "/auth/admin_department_scope",
                json={"department_id": None},
                headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"},
            )
            assert clr.status_code == 200
            assert clr.get_json().get("admin_department_scope") is None

    def test_set_scope_forbidden_for_student(self, app, student_auth_client):
        resp = student_auth_client.post(
            "/auth/admin_department_scope",
            json={"department_id": 1},
            headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"},
        )
        assert resp.status_code == 403
