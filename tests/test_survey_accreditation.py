"""اختبارات ربط الاستبيانات بالاعتماد (المرحلة 3)."""

from backend.core.accreditation_catalog import ensure_accreditation_catalog
from backend.services.accreditation_metrics import compute_indicator_auto
from backend.services.multi_surveys import (
    ensure_survey_templates_seeded,
    get_template_by_code,
    list_template_questions,
    submit_survey_response,
)
from backend.services.quality_metrics import term_label_from_conn
from backend.services.survey_accreditation import (
    build_program_survey_summary,
    hybrid_ff01_score,
    primary_evidence_indicator_code,
    register_survey_as_evidence,
)


def test_primary_evidence_indicator_code_without_conn():
    """بدون اتصال DB — لا خرائط ثابتة؛ الربط من bindings/قواعد الكتالوج فقط."""
    assert primary_evidence_indicator_code("student_facilities") is None
    assert primary_evidence_indicator_code("student_course") is None
    assert primary_evidence_indicator_code("faculty_hod") is None


def test_hybrid_ff01_score_manual_only():
    score, detail = hybrid_ff01_score(80.0, {"aggregated": False})
    assert score == 80.0
    assert "يدوي" in detail


def test_hybrid_ff01_score_blended():
    score, detail = hybrid_ff01_score(
        80.0,
        {"aggregated": True, "overall_score_percent": 60.0},
    )
    assert score == 68.0  # 0.4*80 + 0.6*60
    assert "هجين" in detail
    assert "60" in detail


def test_compute_ff01_uses_hybrid(db_conn):
    ensure_accreditation_catalog(db_conn)
    out = compute_indicator_auto(db_conn, "FF-01-1", semester="phase3-sem", department_id=None)
    assert out["indicator_code"] == "FF-01-1"
    assert out.get("score_percent") is not None
    assert "FF-01-1" in out.get("detail_ar", "") or "البنية" in out.get("detail_ar", "")


def test_register_survey_evidence(db_conn):
    ensure_accreditation_catalog(db_conn)
    ensure_survey_templates_seeded(db_conn)
    sem = term_label_from_conn(db_conn)
    tpl = get_template_by_code(db_conn, "faculty_dean")
    assert tpl
    answers = {int(q["id"]): 4 for q in list_template_questions(db_conn, int(tpl["id"]))}
    for i in range(3):
        submit_survey_response(
            db_conn,
            template_code="faculty_dean",
            semester=sem,
            respondent_role="instructor",
            respondent_id=str(9000 + i),
            subject_type="dean",
            subject_id=1,
            department_id=1,
            answers=answers,
            submitted_by=f"ev{i}",
        )
    db_conn.commit()

    result = register_survey_as_evidence(
        db_conn,
        template_code="faculty_dean",
        semester=sem,
        department_id=1,
        indicator_code="GV-01-1",
        uploaded_by="pytest",
    )
    assert result["id"] > 0
    assert result["indicator_code"] == "GV-01-1"
    assert "compliance_map_url" in result


def test_program_survey_summary(db_conn):
    ensure_survey_templates_seeded(db_conn)
    sem = term_label_from_conn(db_conn)
    summary = build_program_survey_summary(db_conn, semester=sem, department_id=None)
    assert summary["semester"] == sem
    assert summary["rows"]
    assert summary["total_count"] >= 9


def test_register_evidence_api(app, db_conn):
    ensure_accreditation_catalog(db_conn)
    ensure_survey_templates_seeded(db_conn)
    sem = term_label_from_conn(db_conn)
    with app.test_client() as c:
        c.post("/auth/login", json={"username": "admin-test", "password": "TestP@ssw0rd!"})
        r = c.post(
            "/academic_quality/surveys/api/register_evidence",
            json={
                "template_code": "faculty_dean",
                "indicator_code": "GV-01-1",
                "semester": sem,
            },
        )
        assert r.status_code == 200
        body = r.get_json() or {}
        assert body.get("status") == "ok"
        assert body.get("id", 0) > 0


def test_program_export_includes_survey_summary(app, db_conn):
    ensure_survey_templates_seeded(db_conn)
    with app.test_client() as c:
        c.post("/auth/login", json={"username": "admin-test", "password": "TestP@ssw0rd!"})
        r = c.get("/academic_quality/export/program")
        assert r.status_code == 200
        html = r.get_data(as_text=True) or ""
        assert "ملخص الاستبيانات" in html
