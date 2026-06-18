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


def test_build_survey_hub_status_student_no_regs(db_conn):
    from backend.services.survey_platform_routes import build_survey_hub_status

    ensure_survey_templates_seeded(db_conn)
    sem = term_label_from_conn(db_conn)
    status = build_survey_hub_status(
        db_conn,
        role="student",
        session_data={"user": "ghost-student", "student_id": "GHOST999"},
        semester=sem,
        department_id=None,
        active_mode="",
        pending=[],
        supervisor_effective=False,
        supervisor_template_count=0,
        dept_missing=False,
    )
    assert status["show"] is True
    assert status["details"]["registration_count"] == 0
    assert any("تسجيلات" in m for m in status["messages"])


def test_surveys_hub_student_shows_diag(app, student_auth_client):
    r = student_auth_client.get("/academic_quality/surveys")
    assert r.status_code == 200
    assert "ملخص الاستبيانات".encode("utf-8") in r.data


def test_surveys_results_route(app):
    with app.test_client() as c:
        c.post("/auth/login", json={"username": "admin-test", "password": "TestP@ssw0rd!"})
        r = c.get("/academic_quality/surveys/results")
        assert r.status_code == 200


def test_likert_scale_context_shared():
    from backend.services.evaluation_survey import likert_scale_context, likert_scale_guide_ar

    ctx = likert_scale_context([{"label_ar": "بند تجريبي للاختبار"}])
    assert ctx["scale_example_label"] == "بند تجريبي للاختبار"
    assert len(ctx["scale_levels"]) == 5
    mid = next(lv for lv in likert_scale_guide_ar() if lv["value"] == 3)
    assert "جيد" in mid["label"]
    assert mid.get("hint")


def test_survey_question_labels_sync_from_seed(db_conn):
    from backend.services.evaluation_survey import (
        DEFAULT_SURVEY_SEED,
        ensure_survey_questions_seeded,
        list_survey_questions,
    )
    from backend.services.multi_surveys import ensure_survey_templates_seeded, get_template_by_code, list_template_questions

    ensure_survey_questions_seeded(db_conn)
    ce = {q["legacy_key"]: q["label_ar"] for q in list_survey_questions(db_conn, active_only=True)}
    for lk, label, _ in DEFAULT_SURVEY_SEED:
        assert ce.get(lk) == label

    ensure_survey_templates_seeded(db_conn)
    tpl = get_template_by_code(db_conn, "student_services")
    assert tpl
    labels = [q["label_ar"] for q in list_template_questions(db_conn, int(tpl["id"]))]
    assert "بشكل عام، أنا راضٍ عن خدمات الشؤون والتسجيل" in labels
