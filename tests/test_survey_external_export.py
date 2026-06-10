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
)
from backend.services.survey_invites import (
    create_survey_invite,
    ensure_survey_invite_schema,
    list_external_cycles,
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


def _seed_employer_cycle(db_conn, cycle: str = CYCLE, n: int = 5):
    tpl = get_template_by_code(db_conn, "employer_strategic")
    qs = list_template_questions(db_conn, int(tpl["id"]))
    answers = {str(q["id"]): 4 for q in qs}
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

        r4 = c.post(
            "/academic_quality/surveys/api/close_cycle",
            json={"cycle_label": cycle_q, "force": True},
        )
        assert r4.status_code == 200
        assert r4.get_json().get("status") == "ok"
