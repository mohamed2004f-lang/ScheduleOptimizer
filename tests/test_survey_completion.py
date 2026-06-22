"""اختبارات تقرير تغطية تعبئة الاستبيانات."""

import json

from backend.services.multi_surveys import (
    ensure_survey_templates_seeded,
    get_template_by_code,
    list_template_questions,
    submit_survey_response,
)
from backend.services.quality_metrics import term_label_from_conn
from backend.services.survey_completion import (
    build_survey_completion_report,
    export_pending_completion_xlsx,
    resolve_completion_department_id,
)


def _seed_instructor_and_staff(db_conn):
    cur = db_conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO departments (id, code, name_ar) VALUES (1, 'ME', 'ميكانيك')"
    )
    cur.execute(
        """
        INSERT OR IGNORE INTO instructors (id, name, department_id, is_active)
        VALUES (9101, 'أستاذ مكتمل', 1, 1), (9102, 'أستاذ متأخر', 1, 1)
        """
    )
    cur.execute(
        """
        INSERT OR IGNORE INTO users (username, password_hash, role, instructor_id, department_id, is_active)
        VALUES
          ('inst-done', 'x', 'instructor', 9101, 1, 1),
          ('inst-late', 'x', 'instructor', 9102, 1, 1),
          ('staff-late', 'x', 'staff', NULL, 1, 1)
        """
    )
    cur.execute(
        """
        INSERT OR IGNORE INTO students (student_id, student_name, department_id, enrollment_status)
        VALUES ('ST-C1', 'طالب متأخر', 1, 'active')
        """
    )
    cur.execute(
        "INSERT OR IGNORE INTO registrations (student_id, course_name) VALUES ('ST-C1', 'رياضيات 1')"
    )
    db_conn.commit()


def _submit_all_instructor_surveys_except(conn, instructor_id: int, semester: str, skip_code: str | None = None):
    ensure_survey_templates_seeded(conn)
    tpls = [
        t
        for t in __import__(
            "backend.services.multi_surveys", fromlist=["list_templates"]
        ).list_templates(conn)
        if t.get("respondent_role") == "instructor" and not int(t.get("legacy_course_eval") or 0)
    ]
    for t in tpls:
        if skip_code and t["code"] == skip_code:
            continue
        qs = list_template_questions(conn, int(t["id"]))
        answers = {int(q["id"]): 4 for q in qs}
        st = (t.get("subject_type") or "").strip()
        if st in ("department_head", "educational_process", "supervision", "supervision_coordination"):
            subj_id = 1
        else:
            subj_id = 0
        submit_survey_response(
            conn,
            template_code=t["code"],
            semester=semester,
            respondent_role="instructor",
            respondent_id=str(instructor_id),
            subject_type=st,
            subject_id=subj_id,
            department_id=1,
            answers=answers,
        )


def test_build_completion_report_instructor_pending_only(db_conn):
    _seed_instructor_and_staff(db_conn)
    ensure_survey_templates_seeded(db_conn)
    sem = term_label_from_conn(db_conn)
    _submit_all_instructor_surveys_except(db_conn, 9101, sem)

    report = build_survey_completion_report(db_conn, semester=sem, department_id=1)
    inst = next(b for b in report["roles"] if b["role"] == "instructor")
    assert inst["total"] >= 2
    assert inst["completed"] >= 1
    assert inst["pending"] >= 1
    pending_ids = {p["respondent_id"] for p in inst["pending_people"]}
    assert "9102" in pending_ids
    assert "9101" not in pending_ids
    for p in inst["pending_people"]:
        assert p.get("name")
        assert p.get("missing_items")


def test_export_pending_xlsx(db_conn):
    report = build_survey_completion_report(db_conn, semester=term_label_from_conn(db_conn))
    data = export_pending_completion_xlsx(report)
    assert isinstance(data, bytes)
    assert len(data) > 100


def test_resolve_completion_scope_head_department(db_conn):
    dept_id, can_pick = resolve_completion_department_id(
        db_conn, role="head_of_department", username="hod-user", requested_department_id=99
    )
    assert can_pick is False
    assert dept_id is None or isinstance(dept_id, int)


def test_surveys_completion_routes(app):
    with app.test_client() as c:
        c.post("/auth/login", json={"username": "admin-test", "password": "TestP@ssw0rd!"})
        page = c.get("/academic_quality/surveys/completion")
        assert page.status_code == 200
        assert "تغطية تعبئة".encode("utf-8") in page.data
        api = c.get("/academic_quality/surveys/api/completion")
        assert api.status_code == 200
        payload = json.loads(api.data)
        assert payload["status"] == "ok"
        assert "roles" in payload["data"]
