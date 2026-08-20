"""إقفال إداري لفصل سابق: ملاحظة إلزامية، دون احتسابه دليلاً للجودة."""
from backend.services.course_closure_admin import DEFAULT_ADMIN_CLOSE_NOTE
from backend.services.quality_metrics import _avg_ilo, _reports_completion


def test_admin_close_previous_term_with_note(auth_client, db_conn):
    cur = db_conn.cursor()
    cur.execute(
        """
        INSERT INTO schedule (course_name, day, time, room, instructor_id, semester)
        VALUES ('كيمياء تجريبي إقفال', 'الأحد', '08:00-09:30', 'قاعة ت', 1, 'ربيع 43-44')
        """
    )
    cur.execute("UPDATE schedule SET id = rowid WHERE id IS NULL")
    sid = int(
        cur.execute(
            "SELECT COALESCE(id, rowid) FROM schedule WHERE course_name = ? LIMIT 1",
            ("كيمياء تجريبي إقفال",),
        ).fetchone()[0]
    )
    db_conn.commit()
    try:
        q = auth_client.get("/schedule/course_closure_admin_queue?semester=ربيع 43-44")
        assert q.status_code == 200
        payload_q = q.get_json() or {}
        assert "ربيع 43-44" in (payload_q.get("previous_semesters") or [])
        items = payload_q.get("items") or []
        assert any(int(x.get("section_id") or 0) == sid for x in items)

        blocked = auth_client.post(
            "/schedule/course_closure_admin_close",
            json={"semester": "خريف 44-45", "note": DEFAULT_ADMIN_CLOSE_NOTE},
        )
        assert blocked.status_code == 400

        short = auth_client.post(
            "/schedule/course_closure_admin_close",
            json={"semester": "ربيع 43-44", "note": "قصير", "section_ids": [sid]},
        )
        assert short.status_code == 400

        close = auth_client.post(
            "/schedule/course_closure_admin_close",
            json={
                "semester": "ربيع 43-44",
                "note": DEFAULT_ADMIN_CLOSE_NOTE,
                "section_ids": [sid],
            },
        )
        assert close.status_code == 200
        payload = close.get_json() or {}
        assert int(payload.get("closed") or 0) >= 1

        listed = auth_client.get("/schedule/course_closure_reports?status=admin_closed")
        assert listed.status_code == 200
        admin_items = (listed.get_json() or {}).get("items") or []
        row = next((x for x in admin_items if int(x.get("section_id") or 0) == sid), None)
        assert row is not None
        assert row.get("status") == "admin_closed"
        assert (row.get("review_note") or "").strip()
        assert (row.get("approved_by") or "").strip()

        st = cur.execute(
            "SELECT status FROM course_closure_reports WHERE section_id = ? ORDER BY id DESC LIMIT 1",
            (sid,),
        ).fetchone()
        assert st and st[0] == "admin_closed"

        pct = _reports_completion(db_conn, cur, "ربيع 43-44")
        assert pct == 0.0
        assert _avg_ilo(db_conn, cur, "ربيع 43-44") == 0.0
    finally:
        cur.execute("DELETE FROM course_closure_reports WHERE section_id = ?", (sid,))
        cur.execute("DELETE FROM schedule WHERE COALESCE(id, rowid) = ?", (sid,))
        db_conn.commit()


def test_my_assigned_sections_hides_previous_term(app, db_conn):
    cur = db_conn.cursor()
    rows = cur.execute("SELECT COALESCE(id, rowid), semester FROM schedule").fetchall()
    try:
        cur.execute("UPDATE schedule SET semester = 'ربيع 43-44'")
        db_conn.commit()
        with app.test_client() as c:
            login = c.post(
                "/auth/login",
                json={"username": "inst-test", "password": "TestP@ssw0rd!"},
            )
            assert login.status_code == 200
            listed = c.get("/schedule/my_assigned_sections")
            assert listed.status_code == 200
            data = listed.get_json() or {}
            assert (data.get("rows") or []) == []
    finally:
        for r in rows:
            cur.execute(
                "UPDATE schedule SET semester = ? WHERE COALESCE(id, rowid) = ?",
                (r[1], r[0]),
            )
        db_conn.commit()
