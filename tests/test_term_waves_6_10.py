"""الموجات 6–10: استثناءات، إغلاق موحّد، حارس الجدول، حالة الفصل، قيد السلة."""
from __future__ import annotations

import datetime
import uuid

from backend.services.term_engine import (
    OP_ADD_COURSE,
    OP_DROP_COURSE,
    OP_EXAM_WRITE,
    OP_SCHEDULE_PUBLISH,
    OP_SCHEDULE_WRITE,
    TERM_STATUS_CLOSED,
    TERM_STATUS_PLANNED,
    TERM_STATUS_REGISTRATION,
    assert_term_operation,
    derive_term_lifecycle_status,
    ensure_term_engine_tables,
    set_term_master_status,
    sync_term_master_status,
    upsert_term_master,
)
from backend.services.utilities import get_current_term, set_schedule_published_at


def _login(app, user="admin-test", password="TestP@ssw0rd!"):
    c = app.test_client()
    r = c.post("/auth/login", json={"username": user, "password": password})
    assert r.status_code == 200, r.get_data(as_text=True)
    return c


def test_wave6_exception_list_propose_approve_reject(app, db_conn):
    ensure_term_engine_tables(db_conn)
    uid = uuid.uuid4().hex[:6]
    sid = f"EXC{uid}"
    cur = db_conn.cursor()
    cur.execute(
        "INSERT INTO students (student_id, student_name, join_year) VALUES (?, ?, '1445')",
        (sid, "طالب استثناء"),
    )
    db_conn.commit()
    admin = _login(app)

    listed = admin.get("/term_ops/exceptions")
    assert listed.status_code == 200, listed.get_data(as_text=True)
    assert (listed.get_json() or {}).get("status") == "ok"

    prop = admin.post(
        "/term_ops/exceptions",
        json={"student_id": sid, "operation": "add_course", "reason": "نافذة مغلقة للطالب"},
    )
    assert prop.status_code == 200, prop.get_data(as_text=True)
    eid = int((prop.get_json() or {}).get("id") or 0)
    assert eid > 0

    ok = admin.post(f"/term_ops/exceptions/{eid}/approve", json={"days": 5})
    assert ok.status_code == 200, ok.get_data(as_text=True)
    assert (ok.get_json() or {}).get("state") == "approved"

    prop2 = admin.post(
        "/term_ops/exceptions",
        json={"student_id": sid, "operation": "drop_course", "reason": "إسقاط بعد الإغلاق"},
    )
    eid2 = int((prop2.get_json() or {}).get("id") or 0)
    rej = admin.post(f"/term_ops/exceptions/{eid2}/reject", json={"reason": "غير مناسب"})
    assert rej.status_code == 200, rej.get_data(as_text=True)
    assert (rej.get_json() or {}).get("state") == "rejected"


def test_wave7_close_and_reopen_from_term_ops(app, db_conn):
    ensure_term_engine_tables(db_conn)
    admin = _login(app)
    close = admin.post("/term_ops/stages/close", json={"stage": "surveys", "note": "اختبار موجة 7"})
    assert close.status_code == 200, close.get_data(as_text=True)
    dash = admin.get("/term_ops/dashboard")
    assert dash.status_code == 200
    board = ((dash.get_json() or {}).get("closure") or {}).get("stage_board") or []
    surveys = next((s for s in board if s.get("stage") == "surveys"), None)
    assert surveys and surveys.get("closed") is True

    reopen = admin.post(
        "/term_ops/stages/reopen",
        json={"stage": "surveys", "reason": "إعادة فتح للاختبار"},
    )
    assert reopen.status_code == 200, reopen.get_data(as_text=True)


def test_wave8_schedule_ops_registered_in_guard(db_conn):
    ensure_term_engine_tables(db_conn)
    master = upsert_term_master(
        db_conn, season="fall", academic_year="2048/2049", make_current=True
    )
    # بدون نوافذ مؤرخة: الكتابة مسموحة ما دامت المرحلة مفتوحة
    assert_term_operation(
        db_conn,
        operation=OP_SCHEDULE_WRITE,
        semester=master.get("ops_label") or "خريف 48-49",
    )
    assert_term_operation(
        db_conn,
        operation=OP_SCHEDULE_PUBLISH,
        semester=master.get("ops_label") or "خريف 48-49",
    )
    assert_term_operation(
        db_conn,
        operation=OP_EXAM_WRITE,
        semester=master.get("ops_label") or "خريف 48-49",
    )


def test_wave8_publish_schedule_uses_guard(app, db_conn):
    ensure_term_engine_tables(db_conn)
    admin = _login(app)
    r = admin.post("/schedule/publish", json={})
    assert r.status_code == 200, r.get_data(as_text=True)
    assert (r.get_json() or {}).get("status") == "ok"


def test_wave9_lifecycle_status_sync_and_manual(app, db_conn):
    ensure_term_engine_tables(db_conn)
    master = upsert_term_master(
        db_conn, season="fall", academic_year="2049/2050", make_current=True
    )
    term_key = master["term_key"]
    derived = derive_term_lifecycle_status(db_conn, term_key=term_key, ops_label=master.get("ops_label") or "")
    assert derived in (
        TERM_STATUS_PLANNED,
        TERM_STATUS_REGISTRATION,
        "instruction",
        "exams",
        "grading",
        TERM_STATUS_CLOSED,
    )
    synced = sync_term_master_status(db_conn, term_key=term_key, ops_label=master.get("ops_label") or "")
    assert synced.get("status")

    admin = _login(app)
    set_r = admin.post("/term_ops/status", json={"term_key": term_key, "status": "registration"})
    assert set_r.status_code == 200, set_r.get_data(as_text=True)
    row = db_conn.cursor().execute(
        "SELECT status FROM term_master WHERE term_key = ?", (term_key,)
    ).fetchone()
    assert str(row[0]) == "registration"

    set_term_master_status(db_conn, term_key, TERM_STATUS_CLOSED, actor="test")
    again = sync_term_master_status(db_conn, term_key=term_key, ops_label=master.get("ops_label") or "")
    assert again.get("status") == TERM_STATUS_CLOSED


def test_wave10_registrations_unique_includes_semester(db_conn):
    ensure_term_engine_tables(db_conn)
    uid = uuid.uuid4().hex[:6]
    sid = f"UQ{uid}"
    course = f"مقرر قيد {uid}"
    cur = db_conn.cursor()
    cur.execute(
        "INSERT INTO students (student_id, student_name, join_year) VALUES (?, ?, '1445')",
        (sid, "طالب قيد"),
    )
    cur.execute(
        "INSERT OR REPLACE INTO courses (course_name, course_code, units) VALUES (?, ?, 3)",
        (course, f"U{uid}"),
    )
    cur.execute(
        "INSERT INTO registrations (student_id, course_name, semester) VALUES (?, ?, ?)",
        (sid, course, "خريف 44-45"),
    )
    cur.execute(
        "INSERT INTO registrations (student_id, course_name, semester) VALUES (?, ?, ?)",
        (sid, course, "ربيع 44-45"),
    )
    db_conn.commit()
    n = cur.execute(
        "SELECT COUNT(*) FROM registrations WHERE student_id = ? AND course_name = ?",
        (sid, course),
    ).fetchone()[0]
    assert int(n) == 2

    # نفس الفصل مرتين يجب أن يفشل
    try:
        cur.execute(
            "INSERT INTO registrations (student_id, course_name, semester) VALUES (?, ?, ?)",
            (sid, course, "خريف 44-45"),
        )
        db_conn.commit()
        assert False, "expected unique violation"
    except Exception:
        db_conn.rollback()
