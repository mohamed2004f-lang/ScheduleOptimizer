# -*- coding: utf-8 -*-
"""ربط حصة الجدول بمجموعة تدريس صريحة (A/B) عند الإضافة."""

from __future__ import annotations

import uuid

import pytest

from backend.services import teaching_groups as tg


def _seed_dept_course(db_conn):
    uid = uuid.uuid4().hex[:6]
    cur = db_conn.cursor()
    cur.execute(
        "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
        (f"TG{uid}".upper()[:12], f"قسم {uid}", "TG"),
    )
    dept_id = int(cur.execute("SELECT id FROM departments WHERE code=?", (f"TG{uid}".upper()[:12],)).fetchone()[0])
    course = f"مقرر تقسيم {uid}"
    sem = f"خريف 44-{uid[:2]}"
    cur.execute(
        "INSERT OR IGNORE INTO courses (course_name, course_code, units, owning_department_id) VALUES (?, ?, 3, ?)",
        (course, f"TG{uid}"[:8], dept_id),
    )
    cur.execute(
        "INSERT INTO instructors (name, type, is_active, department_id) VALUES (?, 'internal', 1, ?)",
        (f"د. {uid}", dept_id),
    )
    inst_id = int(cur.lastrowid)
    db_conn.commit()
    return {"uid": uid, "dept_id": dept_id, "course": course, "sem": sem, "inst_id": inst_id}


def _insert_slot(db_conn, *, course, sem, dept_id, inst_id, day="السبت", time="09:00-11:00"):
    cur = db_conn.cursor()
    cur.execute(
        """
        INSERT INTO schedule
            (course_name, day, time, room, instructor_id, semester, department_id)
        VALUES (?, ?, ?, 'R1', ?, ?, ?)
        """,
        (course, day, time, inst_id, sem, dept_id),
    )
    db_conn.commit()
    row = cur.execute(
        "SELECT COALESCE(id, rowid) AS sid FROM schedule WHERE course_name = ? ORDER BY rowid DESC LIMIT 1",
        (course,),
    ).fetchone()
    return int(row[0] if not hasattr(row, "keys") else row["sid"])


def test_attach_requires_choice_when_split_exists(db_conn):
    world = _seed_dept_course(db_conn)
    tg.setup_course_offering(
        db_conn,
        course_name=world["course"],
        semester=world["sem"],
        department_id=world["dept_id"],
        group_kind="split",
        groups=[
            {"group_code": "A", "instructor_id": world["inst_id"], "section_ids": []},
            {"group_code": "B", "instructor_id": world["inst_id"], "section_ids": []},
        ],
    )
    groups = tg.list_teaching_groups(
        db_conn, semester=world["sem"], department_id=world["dept_id"], course_name=world["course"]
    )
    gid_a = int(next(g for g in groups if g.get("group_code") == "A")["id"])
    sid = _insert_slot(db_conn, course=world["course"], sem=world["sem"], dept_id=world["dept_id"], inst_id=world["inst_id"])

    with pytest.raises(ValueError, match="اختر مجموعة"):
        tg.attach_schedule_slot_teaching_group(db_conn, sid)

    linked = tg.attach_schedule_slot_teaching_group(
        db_conn, sid, teaching_group_id=gid_a
    )
    db_conn.commit()
    assert linked == gid_a
    row = db_conn.cursor().execute(
        "SELECT teaching_group_id FROM schedule WHERE COALESCE(id, rowid) = ?",
        (sid,),
    ).fetchone()
    assert int(row[0] if not hasattr(row, "keys") else row["teaching_group_id"]) == gid_a


def test_attach_creates_split_group_by_code(db_conn):
    world = _seed_dept_course(db_conn)
    sid = _insert_slot(
        db_conn,
        course=world["course"],
        sem=world["sem"],
        dept_id=world["dept_id"],
        inst_id=world["inst_id"],
        day="الأحد",
    )
    gid = tg.attach_schedule_slot_teaching_group(
        db_conn, sid, group_kind="split", group_code="A"
    )
    db_conn.commit()
    assert gid and gid > 0
    g = tg.get_teaching_group(db_conn, gid)
    assert g["group_kind"] == "split"
    assert g["group_code"] == "A"


def test_attach_allow_reassign_changes_group(db_conn):
    world = _seed_dept_course(db_conn)
    tg.setup_course_offering(
        db_conn,
        course_name=world["course"],
        semester=world["sem"],
        department_id=world["dept_id"],
        group_kind="split",
        groups=[
            {"group_code": "A", "instructor_id": world["inst_id"], "section_ids": []},
            {"group_code": "B", "instructor_id": world["inst_id"], "section_ids": []},
        ],
    )
    groups = tg.list_teaching_groups(
        db_conn, semester=world["sem"], department_id=world["dept_id"], course_name=world["course"]
    )
    gid_a = int(next(g for g in groups if g.get("group_code") == "A")["id"])
    gid_b = int(next(g for g in groups if g.get("group_code") == "B")["id"])
    sid = _insert_slot(db_conn, course=world["course"], sem=world["sem"], dept_id=world["dept_id"], inst_id=world["inst_id"])
    assert tg.attach_schedule_slot_teaching_group(db_conn, sid, teaching_group_id=gid_a) == gid_a
    db_conn.commit()
    # بدون allow_reassign يبقى على A
    assert tg.attach_schedule_slot_teaching_group(db_conn, sid, teaching_group_id=gid_b) == gid_a
    # مع التعديل ينتقل إلى B
    assert (
        tg.attach_schedule_slot_teaching_group(
            db_conn, sid, teaching_group_id=gid_b, allow_reassign=True
        )
        == gid_b
    )
    db_conn.commit()
    row = db_conn.cursor().execute(
        "SELECT teaching_group_id FROM schedule WHERE COALESCE(id, rowid) = ?",
        (sid,),
    ).fetchone()
    assert int(row[0] if not hasattr(row, "keys") else row["teaching_group_id"]) == gid_b
