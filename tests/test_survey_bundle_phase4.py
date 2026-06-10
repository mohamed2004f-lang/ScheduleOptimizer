"""اختبارات المرحلة 4 المتبقية: ZIP، اتجاهات، تذكير الإغلاق."""

import io
import zipfile

from backend.services.multi_surveys import (
    ensure_survey_templates_seeded,
    get_template_by_code,
    list_template_questions,
    submit_survey_response,
)
from backend.services.survey_export_bundle import build_survey_bundle_zip
from backend.services.survey_snapshots import (
    build_trends_chart_data,
    close_semester_and_snapshot,
    closure_reminder_status,
)


def _seed_faculty_dean(db_conn, sem: str, n: int = 3):
    tpl = get_template_by_code(db_conn, "faculty_dean")
    answers = {int(q["id"]): 4 for q in list_template_questions(db_conn, int(tpl["id"]))}
    for i in range(n):
        submit_survey_response(
            db_conn,
            template_code="faculty_dean",
            semester=sem,
            respondent_role="instructor",
            respondent_id=str(7000 + i),
            subject_type="dean",
            subject_id=1,
            department_id=None,
            answers=answers,
            submitted_by=f"b{i}",
        )
    db_conn.commit()


def test_bundle_zip_contains_package_and_reports(db_conn):
    ensure_survey_templates_seeded(db_conn)
    sem = "bundle-sem-1"
    _seed_faculty_dean(db_conn, sem)
    raw, filename, meta = build_survey_bundle_zip(
        db_conn,
        semester=sem,
        department_id=None,
        include_course_eval=True,
        include_pdf=False,
    )
    assert filename.endswith(".zip")
    assert "package.xlsx" in meta["files"]
    assert any(p.startswith("reports/") and p.endswith(".xlsx") for p in meta["files"])

    zf = zipfile.ZipFile(io.BytesIO(raw))
    names = zf.namelist()
    assert "package.xlsx" in names
    assert "README.txt" in names
    assert any(n.endswith("faculty_dean.xlsx") for n in names)


def test_trends_chart_data_after_closures(db_conn):
    ensure_survey_templates_seeded(db_conn)
    for sem in ("chart-a", "chart-b"):
        _seed_faculty_dean(db_conn, sem)
        close_semester_and_snapshot(db_conn, semester=sem, department_id=None, actor="t")
    data = build_trends_chart_data(db_conn, department_id=None)
    assert data["has_data"]
    assert len(data["semesters"]) >= 2
    assert len(data["overall_avg"]) == len(data["semesters"])
    assert data["surveys"]


def test_closure_reminder_when_not_closed(db_conn):
    ensure_survey_templates_seeded(db_conn)
    sem = "remind-sem"
    _seed_faculty_dean(db_conn, sem)
    r = closure_reminder_status(db_conn, sem, None)
    assert r["show"] is True
    close_semester_and_snapshot(db_conn, semester=sem, department_id=None, actor="t")
    r2 = closure_reminder_status(db_conn, sem, None)
    assert r2["show"] is False


def test_bundle_zip_route(app, db_conn):
    ensure_survey_templates_seeded(db_conn)
    sem = "bundle-api"
    _seed_faculty_dean(db_conn, sem)
    with app.test_client() as c:
        c.post("/auth/login", json={"username": "admin-test", "password": "TestP@ssw0rd!"})
        r = c.get(
            f"/academic_quality/surveys/export/bundle.zip?semester={sem}&include_pdf=0"
        )
        assert r.status_code == 200
        assert "zip" in (r.content_type or "").lower()
        zf = zipfile.ZipFile(io.BytesIO(r.data))
        assert "package.xlsx" in zf.namelist()
