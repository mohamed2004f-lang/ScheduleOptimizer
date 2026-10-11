"""أعمدة عرض جدول الاتجاه العام."""

from __future__ import annotations

import uuid

from backend.services import schedule_display_tracks as sdt
from backend.services import teaching_groups as tg


def _ensure_general_dept(db_conn) -> int:
    cur = db_conn.cursor()
    row = cur.execute(
        "SELECT id FROM departments WHERE UPPER(COALESCE(code,'')) IN ('GENERAL','GEN','GS') LIMIT 1"
    ).fetchone()
    if row:
        return int(row[0])
    cur.execute(
        "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES ('GENERAL', 'اتجاه عام', 'General', 1)"
    )
    db_conn.commit()
    row = cur.execute("SELECT id FROM departments WHERE code = 'GENERAL' LIMIT 1").fetchone()
    return int(row[0])


def test_default_tracks_and_save(db_conn):
    dept = _ensure_general_dept(db_conn)
    sem = "خريف 1447"
    defaults = sdt.list_display_tracks(db_conn, semester=sem, department_id=dept)
    assert len(defaults) == 2
    assert defaults[0]["label"] == "المجموعة A"
    assert defaults[1]["label"] == "المجموعة B"

    saved = sdt.save_display_tracks(
        db_conn,
        semester=sem,
        department_id=dept,
        tracks=[
            {"index": 1, "label": "مسار مخصّص 1"},
            {"index": 2, "label": "مسار مخصّص 2"},
            {"index": 3, "label": "مجموعة 3"},
        ],
    )
    assert len(saved) == 3
    assert saved[0]["label"] == "مسار مخصّص 1"
    assert saved[2]["label"] == "المجموعة C"
    listed = sdt.list_display_tracks(db_conn, semester=sem, department_id=dept)
    assert len(listed) == 3
    assert listed[2]["label"] == "المجموعة C"


def test_auto_display_column_letter_prefix():
    assert sdt.auto_display_column_for_group_code("A", sibling_codes=["A", "B"], tracks_n=2) == 1
    assert sdt.auto_display_column_for_group_code("B", sibling_codes=["A", "B"], tracks_n=2) == 2
    assert sdt.auto_display_column_for_group_code("A1", sibling_codes=["A1", "A2", "B1", "B2"], tracks_n=2) == 1
    assert sdt.auto_display_column_for_group_code("A2", sibling_codes=["A1", "A2", "B1", "B2"], tracks_n=2) == 1
    assert sdt.auto_display_column_for_group_code("B1", sibling_codes=["A1", "A2", "B1", "B2"], tracks_n=2) == 2
    assert sdt.auto_display_column_for_group_code("B2", sibling_codes=["A1", "A2", "B1", "B2"], tracks_n=2) == 2
    assert sdt.auto_display_column_for_group_code("C", sibling_codes=["A", "B", "C"], tracks_n=2) == 2


def test_enrich_rows_letter_overrides_explicit_and_balances_untagged(db_conn):
    rows = [
        {
            "course_name": "ميكانيكا",
            "group_code": "A2",
            "display_column": 2,
            "day": "السبت",
            "time": "12:00-14:00",
            "section_id": 1,
        },
        {
            "course_name": "ميكانيكا",
            "group_code": "B1",
            "day": "السبت",
            "time": "12:00-14:00",
            "section_id": 2,
        },
        {
            "course_name": "حاسوب",
            "group_code": "—",
            "day": "السبت",
            "time": "09:00-12:00",
            "section_id": 3,
        },
        {
            "course_name": "رياضيات I",
            "group_code": "",
            "day": "السبت",
            "time": "09:00-12:00",
            "section_id": 4,
        },
    ]
    sdt.enrich_schedule_rows_display_columns(db_conn, rows, tracks_n=2)
    assert rows[0]["display_column"] == 1  # A2 → المجموعة A
    assert rows[1]["display_column"] == 2  # B1 → المجموعة B
    # بلا رمز: يوزَّعان على العمودين لتقليل الازدحام
    assert {rows[2]["display_column"], rows[3]["display_column"]} == {1, 2}


def test_setup_saves_display_column(db_conn):
    uid = uuid.uuid4().hex[:6]
    dept = _ensure_general_dept(db_conn)
    sem = "خريف 1447"
    course = f"مقرر أعمدة {uid}"
    cur = db_conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO courses (course_name, course_code, units, owning_department_id) VALUES (?, ?, 3, ?)",
        (course, f"GS{uid}"[:8], dept),
    )
    cur.execute(
        "INSERT INTO instructors (name, type, is_active, department_id) VALUES (?, 'internal', 1, ?)",
        (f"د. {uid}", dept),
    )
    iid = int(cur.lastrowid)
    cur.execute(
        """
        INSERT INTO schedule (course_name, day, time, room, instructor, instructor_id, semester, department_id)
        VALUES (?, 'السبت', '09:00-11:00', '1', ?, ?, ?, ?)
        """,
        (course, f"د. {uid}", iid, sem, dept),
    )
    section_id = int(cur.lastrowid)
    try:
        cur.execute("UPDATE schedule SET id = rowid WHERE id IS NULL")
    except Exception:
        pass
    db_conn.commit()

    saved = tg.setup_course_offering(
        db_conn,
        course_name=course,
        semester=sem,
        department_id=dept,
        group_kind=tg.GROUP_KIND_SPLIT,
        groups=[
            {
                "group_code": "A",
                "instructor_id": iid,
                "section_ids": [section_id],
                "display_column": 1,
            },
            {
                "group_code": "B",
                "instructor_id": iid,
                "section_ids": [],
                "display_column": 2,
            },
        ],
    )
    assert len(saved) >= 2
    by_code = {g.get("group_code"): g for g in saved}
    assert by_code["A"].get("display_column") == 1
    assert by_code["B"].get("display_column") == 2


def test_display_layout_includes_tracks_for_general(auth_client, db_conn):
    dept = _ensure_general_dept(db_conn)
    sdt.save_display_tracks(
        db_conn,
        semester="خريف 1447",
        department_id=dept,
        tracks=[{"index": 1, "label": "مسار 1"}, {"index": 2, "label": "مسار 2"}],
    )
    r = auth_client.get(f"/schedule/display_layout?department_id={dept}")
    assert r.status_code == 200
    j = r.get_json()
    assert j.get("status") == "ok"
    if not j.get("use_stage_matrix"):
        assert j.get("use_display_tracks") is True
        assert len(j.get("display_tracks") or []) >= 2
