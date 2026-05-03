"""
اختبارات واجهة كتالوج الأقسام والخطط (إداري).
"""


class TestCollegeCatalogApi:
    def test_departments_unauthorized(self, client):
        resp = client.get(
            "/college/catalog/departments",
            headers={"Accept": "application/json"},
        )
        assert resp.status_code == 401

    def test_departments_student_forbidden(self, student_auth_client):
        resp = student_auth_client.get(
            "/college/catalog/departments",
            headers={"Accept": "application/json"},
        )
        assert resp.status_code == 403

    def test_departments_admin_ok(self, auth_client):
        resp = auth_client.get(
            "/college/catalog/departments",
            headers={"Accept": "application/json"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data.get("status") == "ok"
        assert isinstance(data.get("items"), list)

    def test_department_save_roundtrip(self, auth_client):
        code = "TSTCAT_ROUND"
        resp = auth_client.post(
            "/college/catalog/department/save",
            json={
                "code": code,
                "name_ar": "قسم اختبار",
                "name_en": "Test dept",
                "is_active": True,
            },
        )
        assert resp.status_code == 200
        assert resp.get_json().get("status") == "ok"

        lst = auth_client.get(
            "/college/catalog/departments",
            headers={"Accept": "application/json"},
        )
        assert lst.status_code == 200
        rows = lst.get_json().get("items") or []
        assert any(r.get("code") == code for r in rows)
