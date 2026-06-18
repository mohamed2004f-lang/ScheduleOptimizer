"""اختبارات دعوات الاستبيانات الخارجية."""

import json

from backend.core.survey_platform import EXTERNAL_SURVEY_CODES
from backend.services.multi_surveys import (
    aggregate_template,
    ensure_survey_templates_seeded,
    get_template_by_code,
    list_template_questions,
)
from backend.services.survey_identity_context import build_employer_identity_panel, sanitize_survey_display_text
from backend.services.survey_invites import (
    create_survey_invite,
    ensure_survey_invite_schema,
    invite_fill_context,
    list_external_cycles,
    submit_invite_survey,
    validate_invite,
)


def test_external_templates_seeded(db_conn):
    ensure_survey_templates_seeded(db_conn)
    for code in EXTERNAL_SURVEY_CODES:
        tpl = get_template_by_code(db_conn, code)
        assert tpl is not None
        qs = list_template_questions(db_conn, int(tpl["id"]))
        assert len(qs) == 6


def test_sanitize_removes_abbreviations():
    raw = "مخرجات ومقررات واضحة (CLO/PLO) و IG1"
    cleaned = sanitize_survey_display_text(raw)
    assert "CLO" not in cleaned
    assert "IG1" not in cleaned


def test_employer_identity_panel(db_conn):
    ensure_survey_templates_seeded(db_conn)
    panel = build_employer_identity_panel(db_conn)
    assert "vision_ar" in panel
    assert "strategic_plan_summary_ar" in panel
    assert "strategic_goals" in panel
    assert "graduate_outcomes" in panel


def test_invite_create_submit_aggregate(db_conn):
    ensure_survey_invite_schema(db_conn)
    ensure_survey_templates_seeded(db_conn)
    invite = create_survey_invite(
        db_conn,
        template_code="employer_strategic",
        cycle_label="استشارة قطاع اختبار",
        invite_kind="campaign",
        expires_days=30,
        created_by="test",
    )
    db_conn.commit()
    token = invite["token"]
    validate_invite(db_conn, token)
    ctx = invite_fill_context(db_conn, token)
    assert ctx["template_code"] == "employer_strategic"
    assert "identity_panel" in ctx
    assert ctx.get("scale_levels")
    assert ctx.get("scale_example_label")

    questions = ctx["questions"]
    answers = {str(q["id"]): 4 for q in questions}
    rid = submit_invite_survey(
        db_conn,
        token=token,
        profile={
            "org_type": "private",
            "org_name": "شركة اختبار",
            "hires_graduates": "yes",
        },
        answers_payload={"answers": answers},
        comments="توصية اختبار",
    )
    db_conn.commit()
    assert rid > 0

    for i in range(4):
        inv2 = create_survey_invite(
            db_conn,
            template_code="employer_strategic",
            cycle_label="استشارة قطاع اختبار",
            invite_kind="personal",
            expires_days=30,
            created_by="test",
        )
        qs = list_template_questions(db_conn, int(get_template_by_code(db_conn, "employer_strategic")["id"]))
        ans = {str(q["id"]): 5 for q in qs}
        submit_invite_survey(
            db_conn,
            token=inv2["token"],
            profile={
                "org_type": "government",
                "org_name": f"جهة {i}",
                "hires_graduates": "sometimes",
            },
            answers_payload={"answers": ans},
        )
    db_conn.commit()

    agg = aggregate_template(
        db_conn, "employer_strategic", semester="استشارة قطاع اختبار"
    )
    assert agg["response_count"] >= 5
    assert agg["aggregated"] is True
    cycles = list_external_cycles(db_conn)
    assert "استشارة قطاع اختبار" in cycles


def test_alumni_invite_submit(db_conn):
    ensure_survey_invite_schema(db_conn)
    ensure_survey_templates_seeded(db_conn)
    invite = create_survey_invite(
        db_conn,
        template_code="alumni",
        cycle_label="صوت الخريج 2026",
        invite_kind="campaign",
        created_by="test",
    )
    db_conn.commit()
    qs = list_template_questions(db_conn, int(get_template_by_code(db_conn, "alumni")["id"]))
    answers = {str(q["id"]): 3 for q in qs}
    rid = submit_invite_survey(
        db_conn,
        token=invite["token"],
        profile={
            "graduation_year": 2020,
            "department_id": "other",
            "department_label": "قسم قديم",
            "current_role_text": "مهندس",
        },
        answers_payload={"answers": answers},
    )
    db_conn.commit()
    assert rid > 0
    row = db_conn.cursor().execute(
        "SELECT respondent_profile_json FROM survey_responses WHERE id = ?",
        (rid,),
    ).fetchone()
    profile = json.loads(row[0])
    assert profile["graduation_year"] == 2020
