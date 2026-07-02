"""اختبارات ضمان الجودة والتقييمات."""


def test_quality_dashboard_requires_head_or_admin(app):
    with app.test_client() as c:
        login = c.post(
            "/auth/login",
            json={"username": "admin-test", "password": "TestP@ssw0rd!"},
        )
        assert login.status_code == 200
        r = c.get("/academic_quality/dashboard")
        assert r.status_code == 200
        assert "نظام ضمان الجودة".encode("utf-8") in r.data or b"quality" in r.data.lower()


def test_student_evaluable_sections_query_no_crash(app):
    """استعلام المقررات القابل للتقييم لا يسبب خطأ ORDER BY مع DISTINCT (PostgreSQL)."""
    from backend.services.course_evaluations import _student_evaluable_sections
    from backend.services.quality_metrics import term_label_from_conn
    from backend.services.utilities import get_connection

    with app.app_context():
        with get_connection() as conn:
            sem = term_label_from_conn(conn)
            _student_evaluable_sections(conn, "S001", sem)


def test_student_evaluations_list_student_only(app):
    with app.test_client() as c:
        login = c.post(
            "/auth/login",
            json={"username": "student-test", "password": "TestP@ssw0rd!"},
        )
        if login.status_code != 200:
            return  # بيئة اختبار بدون حساب طالب
        r = c.get("/students/evaluations/")
        assert r.status_code in (200, 302)


def test_ilo_catalog_page(app):
    with app.test_client() as c:
        c.post("/auth/login", json={"username": "admin-test", "password": "TestP@ssw0rd!"})
        r = c.get("/academic_quality/ilo/catalog")
        assert r.status_code == 200


def test_ilo_coverage_matrix_and_add_to_plan(app):
    with app.test_client() as c:
        c.post("/auth/login", json={"username": "admin-test", "password": "TestP@ssw0rd!"})
        progs = c.get("/academic_quality/ilo/api/programs")
        items = (progs.get_json() or {}).get("items") or []
        if not items:
            return
        pid = items[0]["id"]
        mat = c.get(f"/academic_quality/ilo/api/programs/{pid}/coverage_matrix")
        assert mat.status_code == 200
        body = mat.get_json() or {}
        assert body.get("status") == "ok"
        assert "outcomes" in body and "columns" in body and "cells" in body
        outcomes = body.get("outcomes") or []
        columns = body.get("columns") or []
        if outcomes and columns:
            oid = outcomes[0]["id"]
            col_key = columns[0]["col_key"]
            toggled = c.post(
                f"/academic_quality/ilo/api/programs/{pid}/coverage_matrix/toggle",
                json={"outcome_id": oid, "col_key": col_key, "linked": True},
            )
            assert toggled.status_code == 200
            assert (toggled.get_json() or {}).get("linked") is True
        add = c.post(
            f"/academic_quality/ilo/api/programs/{pid}/add_to_plan",
            json={
                "course_name": "مقرر اختبار PLO آلي",
                "course_code": "PLO_TEST_AUTO",
                "level_no": 1,
            },
        )
        assert add.status_code == 200
        assert (add.get_json() or {}).get("program_course_id")


def test_ilo_summary_api(app):
    with app.test_client() as c:
        c.post("/auth/login", json={"username": "admin-test", "password": "TestP@ssw0rd!"})
        progs = c.get("/academic_quality/ilo/api/programs")
        assert progs.status_code == 200
        items = (progs.get_json() or {}).get("items") or []
        if not items:
            return
        pid = items[0]["id"]
        r = c.get(f"/academic_quality/ilo/api/programs/{pid}/summary")
        assert r.status_code == 200
        body = r.get_json() or {}
        assert body.get("status") == "ok"
        assert "outcomes_count" in body


def test_supervisor_quality_report_page(app):
    with app.test_client() as c:
        login_inst = c.post(
            "/auth/login",
            json={"username": "inst-test", "password": "TestP@ssw0rd!"},
        )
        assert login_inst.status_code == 200
        r = c.get("/academic_quality/supervisor_report_page")
        assert r.status_code in (200, 403)


def test_survey_admin_page_and_crud(app):
    with app.test_client() as c:
        login = c.post(
            "/auth/login",
            json={"username": "admin-test", "password": "TestP@ssw0rd!"},
        )
        assert login.status_code == 200
        page = c.get("/academic_quality/survey_admin")
        assert page.status_code == 200
        r = c.get("/academic_quality/api/survey_questions")
        assert r.status_code == 200
        data = r.get_json() or {}
        assert data.get("status") == "ok"
        qs = data.get("questions") or []
        assert len(qs) >= 10
        r2 = c.post(
            "/academic_quality/api/survey_questions",
            json={"label_ar": "بند اختبار آلي"},
        )
        assert r2.status_code == 200
        qid = (r2.get_json() or {}).get("question", {}).get("id")
        assert qid
        r3 = c.put(
            f"/academic_quality/api/survey_questions/{qid}",
            json={"is_active": 0},
        )
        assert r3.status_code == 200
        order = [q["id"] for q in qs]
        r4 = c.post(
            "/academic_quality/api/survey_questions/reorder",
            json={"order": list(reversed(order))},
        )
        assert r4.status_code == 200
        c.delete(f"/academic_quality/api/survey_questions/{qid}?template=student_course")


def test_survey_admin_platform_template(app):
    with app.test_client() as c:
        c.post("/auth/login", json={"username": "admin-test", "password": "TestP@ssw0rd!"})
        page = c.get("/academic_quality/survey_admin?template=faculty_hod")
        assert page.status_code == 200
        r = c.get("/academic_quality/api/survey_questions?template=faculty_hod")
        assert r.status_code == 200
        qs = (r.get_json() or {}).get("questions") or []
        assert len(qs) >= 10
        r2 = c.post(
            "/academic_quality/api/survey_questions",
            json={"label_ar": "بند اختبار رئيس قسم", "template_code": "faculty_hod"},
        )
        assert r2.status_code == 200
        qid = (r2.get_json() or {}).get("question", {}).get("id")
        assert qid
        c.delete(f"/academic_quality/api/survey_questions/{qid}?template=faculty_hod")


def test_survey_admin_edit_persists_after_seed_sync(app, db_conn):
    """تعديل نص بند يدوياً لا يُستبدل عند إعادة مزامنة البذرة."""
    from backend.services.multi_surveys import ensure_survey_templates_seeded, list_admin_questions

    ensure_survey_templates_seeded(db_conn)
    with app.test_client() as c:
        c.post("/auth/login", json={"username": "admin-test", "password": "TestP@ssw0rd!"})
        r = c.get("/academic_quality/api/survey_questions?template=faculty_hod")
        qs = (r.get_json() or {}).get("questions") or []
        assert qs
        qid = qs[0]["id"]
        edited = "بند معدّل يدوياً — يجب أن يبقى بعد التحديث"
        r2 = c.put(
            f"/academic_quality/api/survey_questions/{qid}",
            json={"label_ar": edited, "template_code": "faculty_hod"},
        )
        assert r2.status_code == 200
        ensure_survey_templates_seeded(db_conn)
        ensure_survey_templates_seeded(db_conn)
        after = list_admin_questions(db_conn, "faculty_hod")
        found = next((q for q in after if int(q["id"]) == int(qid)), None)
        assert found is not None
        assert found["label_ar"] == edited


def test_quality_metrics_api(app):
    with app.test_client() as c:
        c.post("/auth/login", json={"username": "admin-test", "password": "TestP@ssw0rd!"})
        r = c.get("/academic_quality/api/metrics")
        assert r.status_code == 200
        data = r.get_json() or {}
        assert data.get("status") == "ok"
        assert "metrics" in data
