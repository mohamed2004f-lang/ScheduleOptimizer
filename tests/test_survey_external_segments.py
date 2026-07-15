"""اختبارات تفصيل الاستبيانات الخارجية حسب القسم/البرنامج."""

from backend.services.multi_surveys import (
    ensure_survey_templates_seeded,
    get_template_by_code,
    list_template_questions,
)
from backend.services.survey_external_analytics import build_external_survey_report
from backend.services.survey_invites import (
    create_survey_invite,
    ensure_survey_invite_schema,
    list_public_departments,
    submit_invite_survey,
)


def _ensure_test_department_id(db_conn) -> int:
    depts = list_public_departments(db_conn)
    if depts:
        return int(depts[0]["id"])
    cur = db_conn.cursor()
    cur.execute(
        "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES ('SEGTEST', 'قسم شرائح', 'SEG', 1)"
    )
    db_conn.commit()
    return int(cur.lastrowid)


def _seed_alumni_by_dept(db_conn, *, cycle: str, dept_id: int | None = None, track_code: str = "", n: int = 5):
    if dept_id is None:
        dept_id = _ensure_test_department_id(db_conn)
    tpl = get_template_by_code(db_conn, "alumni")
    qs = list_template_questions(db_conn, int(tpl["id"]))
    answers = {str(q["id"]): 4 for q in qs}
    profile_base = {
        "graduation_year": 2020,
        "department_id": dept_id,
        "employment_status": "in_specialty",
        "engineering_qualification": "yes",
        "job_rejection": "no",
        "recommend_enrollment": "yes",
        "program_freeze_support": "no",
    }
    if track_code:
        profile_base["track_code"] = track_code
        profile_base["track_label"] = f"مسار {track_code}"
    for i in range(n):
        inv = create_survey_invite(
            db_conn,
            template_code="alumni",
            cycle_label=cycle,
            invite_kind="personal",
            expires_days=30,
            created_by="test",
        )
        profile = {
            **profile_base,
            "full_name": f"خريج اختبار {i+1}",
            "recommend_reason_text": "سوق العمل يحتاج التخصص",
            "open_missing_skill": "برمجة التحكم",
            "current_role_text": "مهندس",
        }
        submit_invite_survey(
            db_conn,
            token=inv["token"],
            profile=profile,
            answers_payload={"answers": answers},
            comments=f"توصية توظيف رقم {i+1}",
        )
    db_conn.commit()


def test_alumni_department_and_program_segments(db_conn):
    ensure_survey_invite_schema(db_conn)
    ensure_survey_templates_seeded(db_conn)
    dept_id = _ensure_test_department_id(db_conn)
    cycle = "segment-alumni-test"
    _seed_alumni_by_dept(db_conn, cycle=cycle, dept_id=dept_id, track_code="energy", n=5)

    report = build_external_survey_report(db_conn, "alumni", cycle_label=cycle)
    assert report.get("department_comparison_rows")
    assert any(r.get("department_id") == dept_id for r in report["department_comparison_rows"])
    assert report.get("program_comparison_rows")
    dept_seg = next(
        s for s in report.get("department_segments") or [] if s.get("department_id") == dept_id
    )
    assert dept_seg["aggregated"] is True
    assert dept_seg["overall_score_percent"] is not None


def test_employer_hire_department_segments(db_conn):
    ensure_survey_invite_schema(db_conn)
    ensure_survey_templates_seeded(db_conn)
    dept_id = _ensure_test_department_id(db_conn)
    cycle = "segment-employer-test"
    tpl = get_template_by_code(db_conn, "employer_strategic")
    qs = list_template_questions(db_conn, int(tpl["id"]))
    answers = {str(q["id"]): 4 for q in qs}
    for i in range(5):
        inv = create_survey_invite(
            db_conn,
            template_code="employer_strategic",
            cycle_label=cycle,
            invite_kind="personal",
            expires_days=30,
            created_by="test",
        )
        submit_invite_survey(
            db_conn,
            token=inv["token"],
            profile={
                "org_type": "private",
                "org_name": f"شركة {i}",
                "hires_graduates": "yes",
                "hire_department_ids": [dept_id],
                "hire_department_needs": [
                    {"department_id": dept_id, "specialty_needs_text": "اتصالات وطاقة"},
                ],
            },
            answers_payload={"answers": answers},
        )
    db_conn.commit()

    report = build_external_survey_report(db_conn, "employer_strategic", cycle_label=cycle)
    assert report.get("hire_department_comparison_rows")
    assert report.get("profile_breakdown", {}).get("by_hire_department")
    assert report.get("profile_breakdown", {}).get("by_hire_department_needs")
    hire_seg = next(
        s
        for s in report.get("hire_department_segments") or []
        if s.get("department_id") == dept_id
    )
    assert hire_seg["aggregated"] is True
    assert hire_seg["overall_score_percent"] is not None


def test_alumni_segment_detail_reports_separate(db_conn):
    """كل قسم مجمّع له تقرير وتحليل مستقل — دون الاعتماد على المجموع الكلي فقط."""
    ensure_survey_invite_schema(db_conn)
    ensure_survey_templates_seeded(db_conn)
    dept_id = _ensure_test_department_id(db_conn)
    cycle = "segment-detail-test"
    _seed_alumni_by_dept(db_conn, cycle=cycle, dept_id=dept_id, n=5)

    report = build_external_survey_report(db_conn, "alumni", cycle_label=cycle)
    assert report.get("has_segment_detail") is True
    assert report.get("suppress_college_item_detail") is True

    dept_seg = next(
        s for s in report.get("department_segments") or [] if s.get("department_id") == dept_id
    )
    assert dept_seg.get("detail_report")
    assert dept_seg["detail_report"].get("overall_score_percent") is not None
    assert dept_seg.get("analysis", {}).get("narrative_paragraphs")
    assert dept_seg.get("profile_breakdown", {}).get("by_employment_status")
    assert dept_seg.get("profile_breakdown", {}).get("by_recommend_enrollment")
    assert report.get("raw_response_rows")
    assert len(report["raw_response_rows"]) >= 5
    assert "الاسم_الثلاثي" in report["raw_response_rows"][0]
    assert "ينصح_بالالتحاق" in report["raw_response_rows"][0]

    college_score = report.get("overall_score_percent")
    dept_score = dept_seg["detail_report"].get("overall_score_percent")
    assert college_score is not None and dept_score is not None


def test_alumni_excel_includes_raw_named_rows(db_conn):
    from backend.services.survey_external_analytics import external_single_survey_excel_frames

    ensure_survey_invite_schema(db_conn)
    ensure_survey_templates_seeded(db_conn)
    dept_id = _ensure_test_department_id(db_conn)
    cycle = "raw-excel-alumni"
    _seed_alumni_by_dept(db_conn, cycle=cycle, dept_id=dept_id, n=5)
    report = build_external_survey_report(db_conn, "alumni", cycle_label=cycle)
    frames = external_single_survey_excel_frames(report)
    names = [n for n, _ in frames]
    assert "بيانات_الخريجين_كاملة" in names
    raw_df = next(df for n, df in frames if n == "بيانات_الخريجين_كاملة")
    assert "الاسم_الثلاثي" in raw_df.columns
    assert "الحالة_المهنية" in raw_df.columns
    assert "ينصح_بالالتحاق" in raw_df.columns
    assert len(raw_df) >= 5
