"""تفريغ جدول الامتحانات (جزئي/نهائي) مع تأكيد الفصل ونسخة أرشيف."""
from __future__ import annotations

from backend.services.term_engine import (
    confirm_term_label_matches,
    ensure_term_engine_tables,
    parse_ops_term,
)
from backend.services.utilities import set_exam_schedule_published_at


def _login_admin(app):
    c = app.test_client()
    resp = c.post("/auth/login", json={"username": "admin-test", "password": "TestP@ssw0rd!"})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return c


def _restore_default_term(db_conn):
    db_conn.execute(
        "INSERT OR REPLACE INTO system_settings (key, value) VALUES ('current_term_name', 'خريف')"
    )
    db_conn.execute(
        "INSERT OR REPLACE INTO system_settings (key, value) VALUES ('current_term_year', '44-45')"
    )
    db_conn.commit()


def test_exam_clear_all_requires_confirm_and_clears(app, db_conn):
    ensure_term_engine_tables(db_conn)
    cur = db_conn.cursor()
    # فصل اختبار
    db_conn.execute(
        "INSERT OR REPLACE INTO system_settings (key, value) VALUES ('current_term_name', 'خريف')"
    )
    db_conn.execute(
        "INSERT OR REPLACE INTO system_settings (key, value) VALUES ('current_term_year', '97-98')"
    )
    db_conn.commit()

    # جداول امتحان إن لزم (SQLite اختبار)
    try:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS exams (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                exam_type TEXT NOT NULL,
                exam_id INTEGER,
                course_name TEXT,
                exam_date TEXT,
                exam_time TEXT,
                room TEXT,
                instructor TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS exam_conflicts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                exam_type TEXT,
                student_id TEXT,
                exam_date TEXT,
                conflicting_courses TEXT
            )
            """
        )
    except Exception:
        pass

    cur.execute("DELETE FROM exams WHERE exam_type = 'midterm'")
    cur.execute(
        """
        INSERT INTO exams (exam_type, course_name, exam_date, exam_time, room, instructor)
        VALUES ('midterm', 'امتحان تفريغ 1', '2026-01-10', '09:00-12:00', '1', 'أ')
        """
    )
    cur.execute(
        """
        INSERT INTO exams (exam_type, course_name, exam_date, exam_time, room, instructor)
        VALUES ('final', 'امتحان نهائي يبقى', '2026-06-01', '09:00-12:00', '2', 'ب')
        """
    )
    db_conn.commit()
    set_exam_schedule_published_at("midterm", conn=db_conn)

    admin = _login_admin(app)
    try:
        missing = admin.post("/exams/midterm/clear_all", json={})
        assert missing.status_code == 400
        assert (missing.get_json() or {}).get("code") == "confirm_required"
        still = cur.execute(
            "SELECT COUNT(*) FROM exams WHERE exam_type = 'midterm'"
        ).fetchone()[0]
        assert int(still) >= 1

        parsed = parse_ops_term("خريف", "97-98")
        label = (parsed or {}).get("ops_label") or "خريف 97-98"
        assert confirm_term_label_matches(label, {"ops_label": label})

        ok = admin.post("/exams/midterm/clear_all", json={"confirm_label": label})
        assert ok.status_code == 200, ok.get_data(as_text=True)
        body = ok.get_json() or {}
        assert body.get("status") == "ok"
        assert int(body.get("deleted_rows") or 0) >= 1

        gone = cur.execute(
            "SELECT COUNT(*) FROM exams WHERE exam_type = 'midterm'"
        ).fetchone()[0]
        kept = cur.execute(
            "SELECT COUNT(*) FROM exams WHERE exam_type = 'final' AND course_name = ?",
            ("امتحان نهائي يبقى",),
        ).fetchone()[0]
        assert int(gone) == 0
        assert int(kept) == 1

        pub = cur.execute(
            "SELECT value FROM system_settings WHERE key = 'exam_midterm_schedule_published_at'"
        ).fetchone()
        assert not pub or not pub[0]
    finally:
        _restore_default_term(db_conn)


def test_exam_unpublish_clears_publish_flag(app, db_conn):
    ensure_term_engine_tables(db_conn)
    set_exam_schedule_published_at("final", conn=db_conn)
    admin = _login_admin(app)
    try:
        st = admin.get("/exams/final/publish_status")
        assert st.status_code == 200
        assert (st.get_json() or {}).get("published") is True

        r = admin.post("/exams/final/unpublish", json={})
        assert r.status_code == 200, r.get_data(as_text=True)
        body = r.get_json() or {}
        assert body.get("status") == "ok"
        assert body.get("published") is False

        st2 = admin.get("/exams/final/publish_status")
        assert (st2.get_json() or {}).get("published") is False
    finally:
        _restore_default_term(db_conn)


def test_exams_midterms_page_includes_publish_controls(app):
    admin = _login_admin(app)
    r = admin.get("/exams/midterms")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert 'id="examPublishCard"' in html
    assert 'id="btnExamClear"' in html
    assert 'id="btnExamPublish"' in html
    assert 'id="btnExamUnpublish"' in html
    assert 'id="btnExamArchive"' in html
    assert "تفريغ الجدول" in html
    assert "أرشيف النسخ" in html
