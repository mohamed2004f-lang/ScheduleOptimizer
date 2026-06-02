"""اختبارات منصة الاستبيانات (و-0 → و-5)."""

from backend.services.multi_surveys import (
    aggregate_template,
    ensure_survey_templates_seeded,
    list_pending_for_user,
    list_templates,
    submit_survey_response,
    survey_metrics_for_quality,
)
from backend.services.quality_metrics import compute_quality_metrics, term_label_from_conn


def test_survey_templates_seeded(db_conn):
    ensure_survey_templates_seeded(db_conn)
    templates = list_templates(db_conn)
    codes = {t["code"] for t in templates}
    assert "faculty_hod" in codes
    assert "staff_workplace" in codes
    assert "student_services" in codes


def test_faculty_hod_submit_and_aggregate(db_conn):
    ensure_survey_templates_seeded(db_conn)
    sem = term_label_from_conn(db_conn)
    answers = {}
    from backend.services.multi_surveys import get_template_by_code, list_template_questions

    tpl = get_template_by_code(db_conn, "faculty_hod")
    assert tpl
    for q in list_template_questions(db_conn, int(tpl["id"])):
        answers[int(q["id"])] = 4
    for i in range(3):
        submit_survey_response(
            db_conn,
            template_code="faculty_hod",
            semester=sem,
            respondent_role="instructor",
            respondent_id=str(1000 + i),
            subject_type="department_head",
            subject_id=1,
            department_id=1,
            answers=answers,
            submitted_by=f"inst{i}",
        )
    db_conn.commit()
    agg = aggregate_template(db_conn, "faculty_hod", semester=sem, department_id=1)
    assert agg["response_count"] >= 3
    assert agg["aggregated"] is True
    assert agg["overall_score_percent"] is not None


def test_staff_pending_and_quality_metrics(db_conn):
    ensure_survey_templates_seeded(db_conn)
    sem = term_label_from_conn(db_conn)
    pending = list_pending_for_user(
        db_conn,
        user_role="staff",
        session_data={"user": "staff1"},
        semester=sem,
    )
    codes = {p["code"] for p in pending}
    assert "staff_workplace" in codes
    metrics = compute_quality_metrics(db_conn, semester=sem)
    assert "survey_metrics" in metrics
    sm = survey_metrics_for_quality(db_conn, sem)
    assert "staff_workplace" in sm


def test_supervisor_templates_upgraded(db_conn):
    from backend.services.multi_surveys import _ensure_missing_templates_from_seed

    ensure_survey_templates_seeded(db_conn)
    _ensure_missing_templates_from_seed(db_conn)
    codes = {t["code"] for t in list_templates(db_conn)}
    assert "supervisor_advising" in codes
    assert "supervisor_coordination" in codes


def test_supervisor_pending_uses_active_mode(db_conn):
    ensure_survey_templates_seeded(db_conn)
    sem = term_label_from_conn(db_conn)
    pending = list_pending_for_user(
        db_conn,
        user_role="instructor",
        session_data={"user": "sup1", "instructor_id": 9001},
        semester=sem,
        department_id=1,
        active_mode="supervisor",
    )
    codes = {p["code"] for p in pending}
    assert "supervisor_advising" in codes
    assert "faculty_hod" not in codes


def test_instructor_pending_separate_from_supervisor(db_conn):
    ensure_survey_templates_seeded(db_conn)
    sem = term_label_from_conn(db_conn)
    inst = list_pending_for_user(
        db_conn,
        user_role="head_of_department",
        session_data={"user": "hod1", "instructor_id": 9002},
        semester=sem,
        department_id=1,
        active_mode="instructor",
    )
    inst_codes = {p["code"] for p in inst}
    assert "faculty_hod" in inst_codes
    assert "supervisor_advising" not in inst_codes


def test_surveys_hub_route(app):
    with app.test_client() as c:
        c.post("/auth/login", json={"username": "admin-test", "password": "TestP@ssw0rd!"})
        r = c.get("/academic_quality/surveys")
        assert r.status_code == 200


def test_surveys_results_route(app):
    with app.test_client() as c:
        c.post("/auth/login", json={"username": "admin-test", "password": "TestP@ssw0rd!"})
        r = c.get("/academic_quality/surveys/results")
        assert r.status_code == 200
