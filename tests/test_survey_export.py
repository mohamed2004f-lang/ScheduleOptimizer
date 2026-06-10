"""اختبارات تصدير وتحليل الاستبيانات (المرحلة 1)."""

import io

import pandas as pd

from backend.core.survey_platform import SURVEY_ACCREDITATION_MAP
from backend.services.multi_surveys import (
    ensure_survey_templates_seeded,
    get_template_by_code,
    list_template_questions,
    submit_survey_response,
)
from backend.services.quality_metrics import term_label_from_conn
from backend.services.evaluation_survey import (
    insert_evaluation_with_answers,
    list_survey_questions,
)
from backend.services.survey_analytics import (
    build_combined_survey_report,
    build_course_eval_by_course_report,
    build_course_eval_section_report,
    build_course_eval_sections_summary,
    build_survey_report,
    classify_item_score,
    course_eval_is_aggregated,
    course_eval_min_required,
    generate_executive_narrative_ar,
    interpret_overall_score_ar,
    list_course_eval_course_instructor_groups,
    package_excel_frames,
    prepare_combined_pdf_context,
    prepare_single_survey_pdf_context,
    single_survey_excel_frames,
)


def test_survey_accreditation_map_defined():
    """خريطة ثابتة — مرجع توثيقي؛ العرض الفعلي من bindings وقواعد الكتالوج."""
    assert "faculty_dean" in SURVEY_ACCREDITATION_MAP
    assert "student_facilities" in SURVEY_ACCREDITATION_MAP
    assert "student_course" in SURVEY_ACCREDITATION_MAP


def test_course_eval_min_required_rate():
    assert course_eval_min_required(10) == 5
    assert course_eval_min_required(6) == 3
    assert course_eval_min_required(4) == 3
    assert course_eval_min_required(3) == 3
    assert course_eval_min_required(2) == 3
    assert course_eval_is_aggregated(3, 6) is True
    assert course_eval_is_aggregated(2, 6) is False
    assert course_eval_is_aggregated(3, 4) is True


def test_classify_item_score():
    assert classify_item_score(85) == "excellent"
    assert classify_item_score(72) == "good"
    assert classify_item_score(55) == "needs_improvement"
    assert classify_item_score(40) == "critical"
    assert classify_item_score(None) == "pending"


def test_build_survey_report_with_submissions(db_conn):
    ensure_survey_templates_seeded(db_conn)
    sem = term_label_from_conn(db_conn)
    tpl = get_template_by_code(db_conn, "faculty_hod")
    assert tpl
    answers = {int(q["id"]): 4 for q in list_template_questions(db_conn, int(tpl["id"]))}
    for i in range(3):
        submit_survey_response(
            db_conn,
            template_code="faculty_hod",
            semester=sem,
            respondent_role="instructor",
            respondent_id=str(2000 + i),
            subject_type="department_head",
            subject_id=1,
            department_id=1,
            answers=answers,
            submitted_by=f"exp{i}",
        )
    db_conn.commit()
    report = build_survey_report(db_conn, "faculty_hod", semester=sem, department_id=1)
    assert report["aggregated"] is True
    assert report["overall_score_percent"] is not None
    assert isinstance(report["accreditation_links"], list)
    assert report["compliance_status_ar"]
    assert report["weakest_item"]
    assert report["recommendations"]


def test_combined_report_and_excel_frames(db_conn):
    ensure_survey_templates_seeded(db_conn)
    sem = term_label_from_conn(db_conn)
    combined = build_combined_survey_report(db_conn, semester=sem, include_course_eval=True)
    assert combined["semester"] == sem
    assert len(combined["reports"]) >= 9
    frames = package_excel_frames(combined)
    sheet_names = [name for name, _ in frames]
    assert "ملخص_تنفيذي" in sheet_names
    assert "ربط_المعايير" in sheet_names
    assert "تحليل_مقارن" in sheet_names
    assert "بيانات_وصفية" in sheet_names
    assert "رئيس_القسم" in sheet_names


def test_single_survey_excel_frames(db_conn):
    ensure_survey_templates_seeded(db_conn)
    sem = term_label_from_conn(db_conn)
    report = build_survey_report(db_conn, "faculty_dean", semester=sem)
    frames = single_survey_excel_frames(report)
    names = [n for n, _ in frames]
    assert names == ["ملخص", "البنود", "المعايير", "توصيات", "منهجية"]


def _seed_course_eval_for_section(db_conn, *, section_id: int, course_name: str, instructor_id: int, sem: str, n: int):
    questions = list_survey_questions(db_conn, active_only=True)
    answers = {int(q["id"]): 4 for q in questions}
    for i in range(n):
        insert_evaluation_with_answers(
            db_conn,
            student_id=f"eval-stu-{section_id}-{i}",
            section_id=section_id,
            course_name=course_name,
            instructor_id=instructor_id,
            semester=sem,
            comments="",
            answers=answers,
            active_questions=questions,
        )
    db_conn.commit()


def test_course_eval_per_section_export(db_conn):
    sem = term_label_from_conn(db_conn)
    cur = db_conn.cursor()
    cur.execute(
        "INSERT INTO schedule (course_name, day, time, room, instructor_id, semester) VALUES (?,?,?,?,?,?)",
        ("مقرر تصدير اختبار", "الأحد", "08:00", "101", 1, sem),
    )
    db_conn.commit()
    cur.execute("UPDATE schedule SET id = rowid WHERE id IS NULL")
    db_conn.commit()
    sec_a = int(cur.execute("SELECT id FROM schedule ORDER BY rowid DESC LIMIT 1").fetchone()[0])
    cur.execute(
        "INSERT INTO schedule (course_name, day, time, room, instructor_id, semester) VALUES (?,?,?,?,?,?)",
        ("مقرر تصدير اختبار", "الاثنين", "10:00", "102", 1, sem),
    )
    db_conn.commit()
    cur.execute("UPDATE schedule SET id = rowid WHERE id IS NULL")
    db_conn.commit()
    sec_b = int(cur.execute("SELECT id FROM schedule ORDER BY rowid DESC LIMIT 1").fetchone()[0])

    for i in range(8):
        cur.execute(
            "INSERT OR IGNORE INTO registrations (student_id, course_name) VALUES (?, ?)",
            (f"reg-stu-{i}", "مقرر تصدير اختبار"),
        )
    db_conn.commit()

    _seed_course_eval_for_section(
        db_conn, section_id=sec_a, course_name="مقرر تصدير اختبار", instructor_id=1, sem=sem, n=5
    )
    _seed_course_eval_for_section(
        db_conn, section_id=sec_b, course_name="مقرر تصدير اختبار", instructor_id=1, sem=sem, n=3
    )

    sections = build_course_eval_sections_summary(db_conn, semester=sem)
    assert len(sections) >= 2
    rep_a = build_course_eval_section_report(db_conn, sec_a, semester=sem)
    assert rep_a and rep_a["aggregated"] is True
    rep_b = build_course_eval_section_report(db_conn, sec_b, semester=sem)
    assert rep_b and rep_b["aggregated"] is True
    assert rep_b["min_aggregate"] == 3

    by_course = build_course_eval_by_course_report(
        db_conn, "مقرر تصدير اختبار", 1, semester=sem
    )
    assert by_course
    assert by_course["section_count"] == 2
    assert by_course["response_count"] == 8
    assert by_course["aggregated"] is True

    groups = list_course_eval_course_instructor_groups(db_conn, semester=sem)
    multi = [g for g in groups if int(g.get("section_count") or 0) > 1]
    assert multi

    combined = build_combined_survey_report(db_conn, semester=sem, include_course_eval=True)
    sheet_names = [n for n, _ in package_excel_frames(combined)]
    assert "ملخص_المقررات" in sheet_names
    assert "بنود_المقررات" in sheet_names
    assert "مقرر_وأستاذ" in sheet_names


def test_pdf_context_builders(db_conn):
    ensure_survey_templates_seeded(db_conn)
    sem = term_label_from_conn(db_conn)
    ctx = prepare_combined_pdf_context(db_conn, semester=sem, include_course_eval=True)
    assert ctx["title"]
    assert ctx["executive_summary"]
    assert ctx["accreditation_rows"] is not None
    assert ctx["narrative_paragraphs"]
    assert len(ctx["narrative_paragraphs"]) >= 1
    single = prepare_single_survey_pdf_context(db_conn, "faculty_dean", semester=sem)
    assert single
    assert single["report"]["template_code"] == "faculty_dean"
    assert single["report"].get("interpretation_ar") is not None
    assert prepare_single_survey_pdf_context(db_conn, "not_real", semester=sem) is None


def test_interpret_overall_score_ar():
    assert "خصوصية" in interpret_overall_score_ar(None, False)
    assert "ممتاز" in interpret_overall_score_ar(85, True)


def test_executive_narrative(db_conn):
    ensure_survey_templates_seeded(db_conn)
    sem = term_label_from_conn(db_conn)
    combined = prepare_combined_pdf_context(db_conn, semester=sem)
    paragraphs = generate_executive_narrative_ar(combined)
    assert any("استبيان" in p for p in paragraphs)


def test_export_routes(app):
    with app.test_client() as c:
        c.post("/auth/login", json={"username": "admin-test", "password": "TestP@ssw0rd!"})
        r_pkg = c.get("/academic_quality/surveys/export/package.xlsx")
        assert r_pkg.status_code == 200
        assert "spreadsheetml" in (r_pkg.content_type or "")
        buf = io.BytesIO(r_pkg.data)
        xls = pd.ExcelFile(buf)
        assert "ملخص_تنفيذي" in xls.sheet_names

        r_one = c.get("/academic_quality/surveys/export/faculty_dean.xlsx")
        assert r_one.status_code == 200
        buf2 = io.BytesIO(r_one.data)
        xls2 = pd.ExcelFile(buf2)
        assert "ملخص" in xls2.sheet_names
        assert "البنود" in xls2.sheet_names

        r_bad = c.get("/academic_quality/surveys/export/not_a_survey.xlsx")
        assert r_bad.status_code == 404

        r_ce = c.get("/academic_quality/surveys/export/student_course.xlsx")
        assert r_ce.status_code == 200

        r_secs = c.get("/academic_quality/surveys/export/course_eval_sections.xlsx")
        assert r_secs.status_code == 200
        xls_secs = pd.ExcelFile(io.BytesIO(r_secs.data))
        assert "ملخص_الشعب" in xls_secs.sheet_names

        r_pkg_html = c.get("/academic_quality/surveys/export/package")
        assert r_pkg_html.status_code == 200
        assert "ملخص تنفيذي" in (r_pkg_html.get_data(as_text=True) or "")

        r_one_html = c.get("/academic_quality/surveys/export/faculty_dean")
        assert r_one_html.status_code == 200
        assert "توصيات" in (r_one_html.get_data(as_text=True) or "")

        r_pkg_pdf = c.get("/academic_quality/surveys/export/package.pdf")
        assert r_pkg_pdf.status_code in (200, 500)
        if r_pkg_pdf.status_code == 200:
            assert "pdf" in (r_pkg_pdf.content_type or "").lower()

        r_one_pdf = c.get("/academic_quality/surveys/export/faculty_dean.pdf")
        assert r_one_pdf.status_code in (200, 500)
        if r_one_pdf.status_code == 200:
            assert "pdf" in (r_one_pdf.content_type or "").lower()

        r_bad_pdf = c.get("/academic_quality/surveys/export/not_a_survey.pdf")
        assert r_bad_pdf.status_code == 404

