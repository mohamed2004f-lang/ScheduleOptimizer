"""اختبارات حقن حصص الاتجاه العام + اختيار المجموعة ونقل التسجيلات."""

from __future__ import annotations

import uuid

import pytest

from backend.services import schedule_general_overlay as sgo
from backend.services import teaching_groups as tg
from backend.services.schedule import (
    _get_time_slots_setting,
    _setting_key_time_slots,
    _save_app_setting_json,
)


def _ensure_general(db_conn) -> int:
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
    return int(cur.execute("SELECT id FROM departments WHERE code='GENERAL' LIMIT 1").fetchone()[0])


def _seed_overlay_world(db_conn):
    uid = uuid.uuid4().hex[:6]
    cur = db_conn.cursor()
    gen_id = _ensure_general(db_conn)
    cur.execute(
        "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
        (f"ME{uid}".upper()[:12], f"ميكانيكا {uid}", "Mech"),
    )
    mech_id = int(cur.execute("SELECT id FROM departments WHERE code=?", (f"ME{uid}".upper()[:12],)).fetchone()[0])
    sem = f"خريف 14{uid[:2]}"
    course = f"رياضيات عامة {uid}"
    cur.execute(
        "INSERT OR IGNORE INTO courses (course_name, course_code, units, owning_department_id) VALUES (?, ?, 3, ?)",
        (course, f"GS{uid}"[:8], gen_id),
    )
    cur.execute(
        "INSERT INTO instructors (name, type, is_active, department_id) VALUES (?, 'internal', 1, ?)",
        (f"د. عام {uid}", gen_id),
    )
    iid = int(cur.lastrowid)
    # مجموعتان A/B مع حصص
    for code, day, time in (("A", "السبت", "09:00-11:00"), ("B", "الأحد", "11:00-13:00")):
        cur.execute(
            """
            INSERT INTO teaching_groups
                (course_name, semester, department_id, group_code, group_kind, instructor_id, capacity_max, is_active)
            VALUES (?, ?, ?, ?, 'split', ?, ?, 1)
            """,
            (course, sem, gen_id, code, iid, 2 if code == "A" else 50),
        )
        gid = int(cur.lastrowid)
        cur.execute(
            """
            INSERT INTO schedule
                (course_name, day, time, room, instructor, instructor_id, semester, department_id, teaching_group_id)
            VALUES (?, ?, ?, 'G1', ?, ?, ?, ?, ?)
            """,
            (course, day, time, f"د. عام {uid}", iid, sem, gen_id, gid),
        )
        try:
            cur.execute("UPDATE schedule SET id = rowid WHERE id IS NULL")
        except Exception:
            pass

    groups = {
        g["group_code"]: int(g["id"])
        for g in tg.list_teaching_groups(db_conn, semester=sem, department_id=gen_id, course_name=course)
    }
    # طالبان في الميكانيكا على مجموعة A
    for i in range(2):
        sid = f"S{uid}{i}"
        cur.execute(
            """
            INSERT INTO students (student_id, student_name, department_id, enrollment_status)
            VALUES (?, ?, ?, 'active')
            """,
            (sid, f"طالب {i}", mech_id),
        )
        cur.execute(
            """
            INSERT INTO registrations (student_id, course_name, semester, teaching_group_id)
            VALUES (?, ?, ?, ?)
            """,
            (sid, course, sem, groups["A"]),
        )
    db_conn.commit()
    return {
        "uid": uid,
        "gen_id": gen_id,
        "mech_id": mech_id,
        "sem": sem,
        "course": course,
        "groups": groups,
        "inst_id": iid,
    }


def test_overlay_absent_without_regs(db_conn):
    uid = uuid.uuid4().hex[:6]
    cur = db_conn.cursor()
    gen_id = _ensure_general(db_conn)
    cur.execute(
        "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
        (f"CV{uid}".upper()[:12], f"مدني {uid}", "Civil"),
    )
    civil = int(cur.execute("SELECT id FROM departments WHERE code=?", (f"CV{uid}".upper()[:12],)).fetchone()[0])
    db_conn.commit()
    items = sgo.fetch_overlay_schedule_items(db_conn, consumer_department_id=civil, semester="خريف 9999")
    assert items == []


def test_overlay_shows_bound_group_slots(db_conn):
    world = _seed_overlay_world(db_conn)
    items = sgo.fetch_overlay_schedule_items(
        db_conn, consumer_department_id=world["mech_id"], semester=world["sem"]
    )
    assert len(items) >= 1
    assert all(x.get("is_overlay_general") for x in items)
    assert all(int(x.get("teaching_group_id") or 0) == world["groups"]["A"] for x in items)
    assert items[0]["student_count"] == 2
    # عمود المرحلة الأولى
    from backend.core.schedule_stage_layout import enrich_schedule_row_stage_fields

    enrich_schedule_row_stage_fields(db_conn, items[0])
    assert items[0].get("stage_bucket") == "general_or_y1"
    assert items[0].get("stage_badge") == "عام"


def test_select_moves_only_dept_students_and_capacity(db_conn):
    world = _seed_overlay_world(db_conn)
    # طالب من قسم آخر على A — لا يُنقل
    cur = db_conn.cursor()
    cur.execute(
        "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
        (f"EL{world['uid']}".upper()[:12], "كهرباء", "Elec"),
    )
    other = int(
        cur.execute("SELECT id FROM departments WHERE code=?", (f"EL{world['uid']}".upper()[:12],)).fetchone()[0]
    )
    cur.execute(
        "INSERT INTO students (student_id, student_name, department_id, enrollment_status) VALUES (?, 'آخر', ?, 'active')",
        (f"OX{world['uid']}", other),
    )
    cur.execute(
        "INSERT INTO registrations (student_id, course_name, semester, teaching_group_id) VALUES (?, ?, ?, ?)",
        (f"OX{world['uid']}", world["course"], world["sem"], world["groups"]["A"]),
    )
    db_conn.commit()

    # السعة على A = 2 وممتلئة بطلبة الميكانيكا + الآخر؛ النقل إلى B بسعة 50
    result = sgo.select_general_group_for_department(
        db_conn,
        course_name=world["course"],
        semester=world["sem"],
        teaching_group_id=world["groups"]["B"],
        consumer_department_id=world["mech_id"],
        actor="test",
        force_admin=True,
    )
    db_conn.commit()
    assert result["moved_count"] == 2
    assert result["teaching_group_id"] == world["groups"]["B"]

    # طالب القسم الآخر بقي على A
    row = cur.execute(
        "SELECT teaching_group_id FROM registrations WHERE student_id = ?",
        (f"OX{world['uid']}",),
    ).fetchone()
    assert int(row[0]) == world["groups"]["A"]

    # الربط محفوظ
    bindings = sgo.list_bindings(
        db_conn, semester=world["sem"], consumer_department_id=world["mech_id"]
    )
    assert bindings[world["course"].lower()] == world["groups"]["B"]

    # فشل السعة: أنشئ مجموعة C بسعة 1 وانقل إليها
    cur.execute(
        """
        INSERT INTO teaching_groups
            (course_name, semester, department_id, group_code, group_kind, instructor_id, capacity_max, is_active)
        VALUES (?, ?, ?, 'C', 'split', ?, 1, 1)
        """,
        (world["course"], world["sem"], world["gen_id"], world["inst_id"]),
    )
    gid_c = int(cur.lastrowid)
    db_conn.commit()
    with pytest.raises(ValueError, match="سعة"):
        sgo.select_general_group_for_department(
            db_conn,
            course_name=world["course"],
            semester=world["sem"],
            teaching_group_id=gid_c,
            consumer_department_id=world["mech_id"],
            actor="test",
            force_admin=True,
        )


def test_registration_options_include_general(db_conn):
    world = _seed_overlay_world(db_conn)
    sid = f"S{world['uid']}0"
    opts = tg.list_registration_group_options(
        db_conn,
        course_name=world["course"],
        semester=world["sem"],
        student_id=sid,
    )
    gids = {int(o.get("teaching_group_id") or 0) for o in opts}
    assert world["groups"]["A"] in gids
    assert world["groups"]["B"] in gids


def test_time_slots_dept_key_migrates_legacy(db_conn):
    world = _seed_overlay_world(db_conn)
    # محاكاة مفتاح كلّي قديم
    legacy = _setting_key_time_slots(db_conn, None)
    _save_app_setting_json(
        db_conn, legacy, {"slots": ["08:00-10:00", "10:00-12:00"]}, "test"
    )
    db_conn.commit()
    out = _get_time_slots_setting(db_conn, department_id=world["mech_id"])
    assert "08:00-10:00" in (out.get("slots") or [])
    assert f"dept:{world['mech_id']}" in (out.get("key") or "")


def test_split_warning_when_multiple_groups(db_conn):
    world = _seed_overlay_world(db_conn)
    cur = db_conn.cursor()
    # انقل أحد الطالبين إلى B يدوياً بدون ربط
    cur.execute(
        "UPDATE registrations SET teaching_group_id = ? WHERE student_id = ?",
        (world["groups"]["B"], f"S{world['uid']}1"),
    )
    db_conn.commit()
    resolved = sgo.resolve_effective_general_groups(
        db_conn, consumer_department_id=world["mech_id"], semester=world["sem"]
    )
    assert resolved["split_warnings"]
    assert any(
        str(w.get("course_name") or "").lower() == world["course"].lower()
        for w in resolved["split_warnings"]
    )
