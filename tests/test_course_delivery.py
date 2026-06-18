"""Tests for course delivery baseline and grade gate."""
from backend.database.database import get_connection
from backend.services import course_delivery as cd
from backend.services.course_delivery import (
    BASELINE_APPROVED,
    BASELINE_PENDING,
    ensure_course_delivery_schema,
)


def test_baseline_approve_and_gate(app):
    with app.app_context():
        from backend.services.utilities import get_connection

        with get_connection() as conn:
            ensure_course_delivery_schema(conn)
            cur = conn.cursor()
            course = "مقرر استبيان اختبار"
            now = cd._now_iso()
            cur.execute(
                """
                INSERT INTO course_syllabus_baselines (course_name, version, status, created_by, created_at, updated_at)
                VALUES (?, 1, ?, 'inst-test', ?, ?)
                """,
                (course, BASELINE_PENDING, now, now),
            )
            conn.commit()
            bid = int(
                cur.execute(
                    "SELECT id FROM course_syllabus_baselines WHERE course_name=?",
                    (course,),
                ).fetchone()[0]
            )
            cur.execute(
                "INSERT INTO course_syllabus_topics (baseline_id, sort_order, topic_title) VALUES (?, 0, ?)",
                (bid, "مفرد 1"),
            )
            cur.execute(
                "INSERT INTO course_syllabus_topics (baseline_id, sort_order, topic_title) VALUES (?, 1, ?)",
                (bid, "مفرد 2"),
            )
            conn.commit()

            cur.execute(
                """
                UPDATE course_syllabus_baselines
                SET status=?, approved_by=?, approved_at=?, updated_at=?
                WHERE id=?
                """,
                (BASELINE_APPROVED, "admin-test", now, now, bid),
            )
            conn.commit()

            bl = cd.get_active_baseline(conn, course)
            assert bl is not None
            assert bl["status"] == "approved"
            assert len(bl["topics"]) == 2


def test_overall_pct_average():
    items = [{"completion_pct": 50}, {"completion_pct": 100}]
    assert cd._compute_overall_pct(items) == 75.0


def test_gate_unlock_auto_approved():
    rep = {"status": "auto_approved", "overall_pct": 55.0}
    assert cd._report_unlocks_draft(rep, 50.0) is True
    assert cd._report_unlocks_draft(rep, 60.0) is False


def test_gate_unlock_gate_approved_below_threshold():
    rep = {"status": "gate_approved", "overall_pct": 40.0}
    assert cd._report_unlocks_draft(rep, 50.0) is True


def test_derive_assessment_axis_no_teaching_group():
    with get_connection() as conn:
        out = cd.derive_assessment_axis(
            conn,
            teaching_group_id=None,
            course_name="X",
            semester="ربيع 25-26",
            instructor_id=1,
        )
    assert out["auto"] is False
    assert out["status"] is None


def test_derive_assessment_axis_pending_without_drafts(app):
    with app.app_context():
        with get_connection() as conn:
            ensure_course_delivery_schema(conn)
            out = cd.derive_assessment_axis(
                conn,
                teaching_group_id=99999,
                course_name="مقرر اختبار محور",
                semester="ربيع 25-26",
                instructor_id=1,
            )
    assert out["auto"] is True
    assert out["status"] == "pending"
    assert "detail_ar" in out


def _seed_approved_baseline(conn, course: str) -> int:
    cur = conn.cursor()
    now = cd._now_iso()
    cur.execute(
        """
        INSERT INTO course_syllabus_baselines (course_name, version, status, created_by, created_at, updated_at)
        VALUES (?, 1, ?, 'inst-test', ?, ?)
        """,
        (course, BASELINE_APPROVED, now, now),
    )
    conn.commit()
    bid = int(
        cur.execute(
            "SELECT id FROM course_syllabus_baselines WHERE course_name=?",
            (course,),
        ).fetchone()[0]
    )
    cur.execute(
        "INSERT INTO course_syllabus_topics (baseline_id, sort_order, topic_title, is_active) VALUES (?, 0, ?, 1)",
        (bid, "مفرد 1"),
    )
    conn.commit()
    return bid


def _ensure_faculty_plans_table(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS faculty_course_plans (
            section_id INTEGER NOT NULL,
            instructor_id INTEGER NOT NULL,
            week_no INTEGER NOT NULL,
            week_topic TEXT DEFAULT '',
            lecture_status TEXT NOT NULL DEFAULT 'planned',
            resources_text TEXT DEFAULT '',
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_by TEXT DEFAULT '',
            PRIMARY KEY (section_id, instructor_id, week_no)
        )
        """
    )
    conn.commit()


def test_derive_course_mgmt_axis_pending_without_baseline(app):
    with app.app_context():
        with get_connection() as conn:
            ensure_course_delivery_schema(conn)
            _ensure_faculty_plans_table(conn)
            out = cd.derive_course_mgmt_axis(
                conn,
                course_name="مقرر بدون مفردات",
                instructor_id=1,
                section_ids=[101],
            )
    assert out["auto"] is True
    assert out["status"] == "pending"
    assert out["milestones"]["baseline_ok"] is False


def test_derive_course_mgmt_axis_done_with_baseline_and_plan(app):
    with app.app_context():
        with get_connection() as conn:
            ensure_course_delivery_schema(conn)
            _ensure_faculty_plans_table(conn)
            course = "مقرر إعداد مكتمل"
            _seed_approved_baseline(conn, course)
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO faculty_course_plans (section_id, instructor_id, week_no, week_topic)
                VALUES (?, ?, 1, 'أسبوع 1')
                """,
                (55, 7),
            )
            conn.commit()
            out = cd.derive_course_mgmt_axis(
                conn,
                course_name=course,
                instructor_id=7,
                section_ids=[55],
            )
    assert out["status"] == "done"
    assert out["milestones"]["baseline_ok"] is True
    assert out["milestones"]["weekly_plan"] is True


def test_derive_teaching_content_axis_done_when_both_reports_submitted(app):
    with app.app_context():
        with get_connection() as conn:
            ensure_course_delivery_schema(conn)
            course = "مقرر تنفيذ محتوى"
            bid = _seed_approved_baseline(conn, course)
            sem = "ربيع 25-26"
            tgid = 42
            now = cd._now_iso()
            cur = conn.cursor()
            for phase in (cd.PHASE_PARTIAL, cd.PHASE_FINAL):
                cur.execute(
                    """
                    INSERT INTO course_delivery_reports (
                        teaching_group_id, semester, course_name, instructor_id, baseline_id,
                        phase, overall_pct, status, submitted_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 80, 'submitted', ?, ?)
                    """,
                    (tgid, sem, course, 3, bid, phase, now, now),
                )
            conn.commit()
            out = cd.derive_teaching_content_axis(
                conn,
                teaching_group_id=tgid,
                course_name=course,
                semester=sem,
            )
    assert out["status"] == "done"
    assert out["milestones"]["partial_report"] is True
    assert out["milestones"]["final_report"] is True


def test_derive_teaching_content_axis_pending_partial_only(app):
    with app.app_context():
        with get_connection() as conn:
            ensure_course_delivery_schema(conn)
            course = "مقرر جزئي فقط"
            bid = _seed_approved_baseline(conn, course)
            sem = "ربيع 25-26"
            tgid = 43
            now = cd._now_iso()
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO course_delivery_reports (
                    teaching_group_id, semester, course_name, instructor_id, baseline_id,
                    phase, overall_pct, status, submitted_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 70, 'gate_pending', ?, ?)
                """,
                (tgid, sem, course, 3, bid, cd.PHASE_PARTIAL, now, now),
            )
            conn.commit()
            out = cd.derive_teaching_content_axis(
                conn,
                teaching_group_id=tgid,
                course_name=course,
                semester=sem,
            )
    assert out["status"] == "pending"
    assert out["milestones"]["partial_report"] is True
    assert out["milestones"]["final_report"] is False
    assert "النهائي" in out["detail_ar"]


def test_derive_documentation_axis_pending(app):
    with app.app_context():
        with get_connection() as conn:
            ensure_course_delivery_schema(conn)
            out = cd.derive_documentation_axis(
                conn,
                teaching_group_id=43,
                course_name="مقرر جزئي فقط",
                semester="ربيع 25-26",
            )
    assert out["auto"] is True
    assert out["status"] == "pending"
