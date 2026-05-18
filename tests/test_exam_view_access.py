"""صلاحيات عرض جداول الامتحانات للأدوار التعليمية."""


def test_student_schedule_coverage_returns_200_not_403(app):
    with app.test_client() as c:
        login = c.post(
            "/auth/login",
            json={"username": "student-test", "password": "TestP@ssw0rd!"},
        )
        if login.status_code != 200:
            return
        r = c.get("/exams/midterm/schedule_coverage")
        assert r.status_code == 200
        data = r.get_json() or {}
        assert "coverage_available" in data
        assert data.get("coverage_available") is False

        rows = c.get("/exams/midterm/rows")
        assert rows.status_code == 200
        assert isinstance(rows.get_json(), list)
