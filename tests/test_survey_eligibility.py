"""اختبارات أهلية تعبئة استبيانات أعضاء هيئة التدريس."""

from backend.services.multi_surveys import (
    ensure_survey_templates_seeded,
    list_pending_for_respondent_role,
    submit_survey_response,
)
from backend.services.quality_metrics import term_label_from_conn
from backend.services.survey_completion import build_survey_completion_report
from backend.services.survey_eligibility import is_instructor_template_required


def _seed_department(db_conn, dept_id: int = 1, code: str = "CIV", name: str = "مدني"):
    cur = db_conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO departments (id, code, name_ar) VALUES (?, ?, ?)",
        (dept_id, code, name),
    )
    db_conn.commit()


def test_department_head_excluded_from_faculty_hod(db_conn):
    _seed_department(db_conn)
    cur = db_conn.cursor()
    cur.execute(
        """
        INSERT OR IGNORE INTO instructors (id, name, type, department_id, external_scope, is_active)
        VALUES (9201, 'رئيس قسم', 'internal', 1, 'within_college', 1)
        """
    )
    cur.execute(
        """
        INSERT OR IGNORE INTO users (username, password_hash, role, instructor_id, department_id, is_active)
        VALUES ('hod9201', 'x', 'head_of_department', 9201, 1, 1)
        """
    )
    db_conn.commit()

    assert is_instructor_template_required(
        db_conn, template_code="faculty_hod", instructor_id=9201, department_id=1
    ) is False
    assert is_instructor_template_required(
        db_conn, template_code="faculty_educational_process", instructor_id=9201, department_id=1
    ) is True

    ensure_survey_templates_seeded(db_conn)
    sem = term_label_from_conn(db_conn)
    pending = list_pending_for_respondent_role(
        db_conn,
        respondent_role="instructor",
        session_data={"instructor_id": 9201, "user": "hod9201"},
        semester=sem,
        department_id=1,
    )
    codes = {p["code"] for p in pending}
    assert "faculty_hod" not in codes
    assert "faculty_educational_process" in codes


def test_external_collaborator_only_gets_dedicated_survey(db_conn):
    _seed_department(db_conn)
    cur = db_conn.cursor()
    cur.execute(
        """
        INSERT OR IGNORE INTO instructors (id, name, type, department_id, external_scope, is_active)
        VALUES (9202, 'متعاون خارجي', 'external', 1, 'outside_university', 1)
        """
    )
    db_conn.commit()

    assert is_instructor_template_required(
        db_conn, template_code="faculty_hod", instructor_id=9202, department_id=1
    ) is False
    assert is_instructor_template_required(
        db_conn,
        template_code="faculty_educational_process", instructor_id=9202, department_id=1
    ) is False
    assert is_instructor_template_required(
        db_conn, template_code="faculty_dean", instructor_id=9202, department_id=1
    ) is False
    assert is_instructor_template_required(
        db_conn, template_code="faculty_external_collaborator", instructor_id=9202, department_id=1
    ) is True

    ensure_survey_templates_seeded(db_conn)
    sem = term_label_from_conn(db_conn)
    pending = list_pending_for_respondent_role(
        db_conn,
        respondent_role="instructor",
        session_data={"instructor_id": 9202, "user": "ext9202"},
        semester=sem,
        department_id=1,
    )
    codes = {p["code"] for p in pending}
    assert codes == {"faculty_external_collaborator"}


def test_completion_report_marks_head_complete_without_hod(db_conn):
    _seed_department(db_conn)
    ensure_survey_templates_seeded(db_conn)
    sem = term_label_from_conn(db_conn)
    cur = db_conn.cursor()
    cur.execute(
        """
        INSERT OR IGNORE INTO instructors (id, name, type, department_id, external_scope, is_active)
        VALUES (9203, 'رئيس مكتمل', 'internal', 1, 'within_college', 1)
        """
    )
    cur.execute(
        """
        INSERT OR IGNORE INTO users (username, password_hash, role, instructor_id, department_id, is_active)
        VALUES ('hod9203', 'x', 'head_of_department', 9203, 1, 1)
        """
    )
    db_conn.commit()

    from backend.services.multi_surveys import get_template_by_code, list_template_questions

    for code in ("faculty_dean", "faculty_educational_process"):
        tpl = get_template_by_code(db_conn, code)
        qs = list_template_questions(db_conn, int(tpl["id"]))
        answers = {int(q["id"]): 4 for q in qs}
        st = (tpl.get("subject_type") or "").strip()
        subj_id = 1 if st in ("department_head", "educational_process") else 0
        submit_survey_response(
            db_conn,
            template_code=code,
            semester=sem,
            respondent_role="instructor",
            respondent_id="9203",
            subject_type=st,
            subject_id=subj_id,
            department_id=1,
            answers=answers,
        )

    report = build_survey_completion_report(db_conn, semester=sem, department_id=1)
    inst = next(b for b in report["roles"] if b["role"] == "instructor")
    pending_ids = {p["respondent_id"] for p in inst["pending_people"]}
    assert "9203" not in pending_ids
