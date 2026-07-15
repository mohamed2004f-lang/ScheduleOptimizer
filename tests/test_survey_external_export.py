"""اختبارات المرحلة 9 — تصدير وإغلاق دورات الاستبيانات الخارجية."""

import io
import zipfile

from backend.core.survey_platform import EXTERNAL_SURVEY_CODES
from backend.services.multi_surveys import (
    aggregate_template,
    ensure_survey_templates_seeded,
    get_template_by_code,
    list_template_questions,
)
from backend.services.survey_export_bundle import build_external_survey_bundle_zip
from backend.services.survey_external_analytics import (
    build_combined_external_report,
    build_external_export_bytes,
    external_package_excel_frames,
    survey_external_metrics_summary,
    _alumni_profile_open_texts,
    _dedupe_open_text_entries,
)
from backend.services.survey_invites import (
    create_survey_invite,
    ensure_survey_invite_schema,
    list_external_cycles,
    list_public_departments,
    submit_invite_survey,
)
from backend.services.survey_snapshots import (
    build_external_trends_chart_data,
    close_cycle_and_snapshot,
    get_cycle_closure,
    is_cycle_closed,
)
from backend.services.survey_accreditation import (
    build_program_survey_summary,
    build_survey_export_bytes,
    survey_supplementary_notes,
)


CYCLE = "دورة تصدير خارجي 9"


def _ensure_test_department_id(db_conn) -> int:
    depts = list_public_departments(db_conn)
    if depts:
        return int(depts[0]["id"])
    cur = db_conn.cursor()
    cur.execute(
        "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES ('TSTEXT', 'قسم اختبار خارجي', 'EXT', 1)"
    )
    db_conn.commit()
    return int(cur.lastrowid)


def _seed_employer_cycle(db_conn, cycle: str = CYCLE, n: int = 5):
    tpl = get_template_by_code(db_conn, "employer_strategic")
    qs = list_template_questions(db_conn, int(tpl["id"]))
    answers = {str(q["id"]): 4 for q in qs}
    dept_id = _ensure_test_department_id(db_conn)
    for i in range(n):
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
                "org_name": f"جهة {i}",
                "hires_graduates": "yes",
                "hire_department_ids": [dept_id],
                "hire_department_needs": [
                    {"department_id": dept_id, "specialty_needs_text": "هندسة مدنية"},
                ],
            },
            answers_payload={"answers": answers},
        )
    db_conn.commit()


def test_external_combined_report_and_excel_frames(db_conn):
    ensure_survey_invite_schema(db_conn)
    ensure_survey_templates_seeded(db_conn)
    _seed_employer_cycle(db_conn)
    combined = build_combined_external_report(db_conn, cycle_label=CYCLE)
    assert combined["report_kind"] == "external"
    assert combined["cycle_label"] == CYCLE
    frames = external_package_excel_frames(combined)
    assert any(name == "ملخص_تنفيذي" or "ملخص" in name for name, _ in frames)

    raw, filename, report = build_external_export_bytes(
        db_conn, "employer_strategic", cycle_label=CYCLE
    )
    assert filename.endswith(".xlsx")
    assert report["response_count"] >= 5
    assert report["aggregated"] is True


def test_external_bundle_zip(db_conn):
    ensure_survey_invite_schema(db_conn)
    ensure_survey_templates_seeded(db_conn)
    _seed_employer_cycle(db_conn, cycle="zip-cycle-9")
    raw, filename, meta = build_external_survey_bundle_zip(
        db_conn,
        cycle_label="zip-cycle-9",
        include_pdf=False,
    )
    assert filename.endswith(".zip")
    assert meta["report_kind"] == "external"
    assert "package.xlsx" in meta["files"]
    zf = zipfile.ZipFile(io.BytesIO(raw))
    names = zf.namelist()
    assert "package.xlsx" in names
    assert any(n.endswith("employer_strategic.xlsx") for n in names)


def test_close_cycle_and_trends(db_conn):
    ensure_survey_invite_schema(db_conn)
    ensure_survey_templates_seeded(db_conn)
    cycle = "close-cycle-9"
    _seed_employer_cycle(db_conn, cycle=cycle)
    assert not is_cycle_closed(db_conn, cycle)
    result = close_cycle_and_snapshot(db_conn, cycle_label=cycle, actor="tester")
    db_conn.commit()
    assert result["status"] == "ok"
    assert result["snapshot_count"] >= 1
    closure = get_cycle_closure(db_conn, cycle)
    assert closure is not None
    assert closure.get("archive_url")

    cycle2 = "close-cycle-9b"
    _seed_employer_cycle(db_conn, cycle=cycle2)
    close_cycle_and_snapshot(db_conn, cycle_label=cycle2, actor="tester")
    db_conn.commit()
    chart = build_external_trends_chart_data(db_conn)
    assert chart["has_data"]
    assert len(chart["cycles"]) >= 2


def test_accreditation_and_quality_hooks(db_conn):
    ensure_survey_invite_schema(db_conn)
    ensure_survey_templates_seeded(db_conn)
    _seed_employer_cycle(db_conn)
    metrics = survey_external_metrics_summary(db_conn)
    assert "employer_strategic" in metrics.get("templates", {})
    assert CYCLE in list_external_cycles(db_conn)

    raw, _fn, _rep = build_survey_export_bytes(
        db_conn, "employer_strategic", semester=CYCLE
    )
    assert len(raw) > 100

    notes = survey_supplementary_notes(
        db_conn, semester="any-sem", department_id=None, indicator_code="GV-01-1"
    )
    assert notes  # employer_strategic links to GV

    summary = build_program_survey_summary(db_conn, semester="any-sem", department_id=None)
    assert summary.get("external_rows")


def test_external_export_routes(app, db_conn):
    ensure_survey_invite_schema(db_conn)
    ensure_survey_templates_seeded(db_conn)
    _seed_employer_cycle(db_conn, cycle="route-cycle-9")
    with app.test_client() as c:
        c.post("/auth/login", json={"username": "admin-test", "password": "TestP@ssw0rd!"})
        cycle_q = "route-cycle-9"
        r = c.get(
            f"/academic_quality/surveys/export/external/package.xlsx?cycle={cycle_q}"
        )
        assert r.status_code == 200
        assert "spreadsheet" in (r.content_type or "").lower() or r.data[:2] == b"PK"

        r2 = c.get(
            f"/academic_quality/surveys/export/external/bundle.zip?cycle={cycle_q}&include_pdf=0"
        )
        assert r2.status_code == 200
        zf = zipfile.ZipFile(io.BytesIO(r2.data))
        assert "package.xlsx" in zf.namelist()

        for code in EXTERNAL_SURVEY_CODES:
            r3 = c.get(
                f"/academic_quality/surveys/export/external/{code}.xlsx?cycle={cycle_q}"
            )
            assert r3.status_code == 200

        r_html = c.get(
            f"/academic_quality/surveys/export/external/package?cycle={cycle_q}"
        )
        assert r_html.status_code == 200
        assert "text/html" in (r_html.content_type or "")

        r_pdf = c.get(
            f"/academic_quality/surveys/export/external/package.pdf?cycle={cycle_q}"
        )
        assert r_pdf.status_code == 200

        for code in EXTERNAL_SURVEY_CODES:
            r_prev = c.get(
                f"/academic_quality/surveys/export/external/{code}?cycle={cycle_q}"
            )
            assert r_prev.status_code == 200
            r_spdf = c.get(
                f"/academic_quality/surveys/export/external/{code}.pdf?cycle={cycle_q}"
            )
            assert r_spdf.status_code == 200

        r4 = c.post(
            "/academic_quality/surveys/api/close_cycle",
            json={"cycle_label": cycle_q, "force": True},
        )
        assert r4.status_code == 200
        assert r4.get_json().get("status") == "ok"


def test_alumni_open_texts_dedupe_identical():
    rows = [
        {
            "comments": "توصية عامة",
            "profile": {
                "full_name": "أ",
                "department_label": "مدني",
                "recommend_reason_text": "هو مجال التكنولوجيا الحديث",
                "open_adaptation_difficulty": "عدم الخبره",
            },
        },
        {
            "comments": "",
            "profile": {
                "full_name": "ب",
                "department_label": "مدني",
                "recommend_reason_text": "  هو مجال التكنولوجيا الحديث  ",
                "open_adaptation_difficulty": "عدم الخبره",
            },
        },
        {
            "comments": "توصية عامة",
            "profile": {
                "full_name": "",
                "recommend_reason_text": "لا توجد فرص",
            },
        },
    ]
    ot = _alumni_profile_open_texts(rows)
    reasons = ot["recommend_reasons"]
    assert len(reasons) == 2
    assert reasons[0]["العدد"] == 2
    assert "×2" in reasons[0]["النص_المعروض"]
    assert reasons[1]["النص"] == "لا توجد فرص"
    diffs = ot["adaptation_difficulties"]
    assert len(diffs) == 1
    assert diffs[0]["العدد"] == 2
    comments = ot["open_comments"]
    assert len(comments) == 1
    assert comments[0]["العدد"] == 2


def test_dedupe_open_text_entries_preserves_first_wording():
    out = _dedupe_open_text_entries(
        [
            {"الاسم": "أ", "النص": "عدم الخبرة"},
            {"الاسم": "ب", "النص": "عدم   الخبرة"},
        ]
    )
    assert len(out) == 1
    assert out[0]["النص"] == "عدم الخبرة"
    assert out[0]["العدد"] == 2

