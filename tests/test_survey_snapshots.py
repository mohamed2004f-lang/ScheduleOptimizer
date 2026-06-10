"""اختبارات لقطات إغلاق الفصل ومقارنة الاستبيانات."""

from backend.services.multi_surveys import (
    ensure_survey_templates_seeded,
    get_template_by_code,
    list_template_questions,
    submit_survey_response,
)
from backend.services.quality_metrics import term_label_from_conn
from backend.services.survey_snapshots import (
    close_semester_and_snapshot,
    compare_semester_snapshots,
    get_semester_closure,
    is_semester_closed,
    list_semester_snapshots,
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
            respondent_id=str(8000 + i),
            subject_type="dean",
            subject_id=1,
            department_id=1,
            answers=answers,
            submitted_by=f"snap{i}",
        )
    db_conn.commit()


def test_close_semester_creates_snapshots(db_conn):
    ensure_survey_templates_seeded(db_conn)
    sem = "snap-sem-a"
    _seed_faculty_dean(db_conn, sem)
    assert not is_semester_closed(db_conn, sem, department_id=1)

    result = close_semester_and_snapshot(
        db_conn,
        semester=sem,
        department_id=1,
        actor="pytest",
    )
    assert result["status"] == "ok"
    assert result["snapshot_count"] >= 1
    assert result.get("archive_url")

    closure = get_semester_closure(db_conn, sem, department_id=1)
    assert closure
    assert closure["is_closed"]

    snaps = list_semester_snapshots(db_conn, sem, department_id=1)
    assert any(s["template_code"] == "faculty_dean" for s in snaps)
    dean = next(s for s in snaps if s["template_code"] == "faculty_dean")
    assert dean.get("aggregated")
    assert dean.get("overall_score_percent") is not None


def test_close_semester_twice_requires_force(db_conn):
    ensure_survey_templates_seeded(db_conn)
    sem = "snap-sem-b"
    _seed_faculty_dean(db_conn, sem)
    close_semester_and_snapshot(db_conn, semester=sem, department_id=None, actor="pytest")
    try:
        close_semester_and_snapshot(db_conn, semester=sem, department_id=None, actor="pytest")
        assert False, "expected ValueError"
    except ValueError as e:
        assert "مُغلق" in str(e)
    close_semester_and_snapshot(
        db_conn, semester=sem, department_id=None, actor="pytest", force=True
    )
    assert is_semester_closed(db_conn, sem, None)


def test_compare_semester_snapshots(db_conn):
    ensure_survey_templates_seeded(db_conn)
    sem_a = "snap-cmp-a"
    sem_b = "snap-cmp-b"
    _seed_faculty_dean(db_conn, sem_a)
    _seed_faculty_dean(db_conn, sem_b)
    close_semester_and_snapshot(db_conn, semester=sem_a, department_id=None, actor="t")
    close_semester_and_snapshot(db_conn, semester=sem_b, department_id=None, actor="t")
    cmp = compare_semester_snapshots(db_conn, sem_a, sem_b, department_id=None)
    assert cmp["has_closure_a"] and cmp["has_closure_b"]
    row = next((r for r in cmp["rows"] if r["template_code"] == "faculty_dean"), None)
    assert row
    assert row["score_a"] is not None
    assert row["score_b"] is not None


def test_close_semester_api(app, db_conn):
    ensure_survey_templates_seeded(db_conn)
    sem = term_label_from_conn(db_conn)
    _seed_faculty_dean(db_conn, sem + "-api")
    with app.test_client() as c:
        c.post("/auth/login", json={"username": "admin-test", "password": "TestP@ssw0rd!"})
        r = c.post(
            "/academic_quality/surveys/api/close_semester",
            json={"semester": sem + "-api", "force": False},
        )
        assert r.status_code == 200
        body = r.get_json() or {}
        assert body.get("status") == "ok"
        assert body.get("snapshot_count", 0) >= 1

        r2 = c.get(f"/academic_quality/surveys/api/closure?semester={sem + '-api'}")
        assert r2.status_code == 200
        assert (r2.get_json() or {}).get("is_closed") is True

        r3 = c.get("/academic_quality/surveys/trends")
        assert r3.status_code == 200
        assert "مقارنة" in (r3.get_data(as_text=True) or "")
