"""حفظ الجدول ينشئ تعيين متعاون على مستوى القسم."""
from __future__ import annotations

import uuid

from backend.core.services import ScheduleService
from backend.database.database import HOME_ASSIGNMENT_SECTION_ID
from backend.repositories.instructor_assignments_repo import (
    upsert_schedule_derived_assignment,
    upsert_user_assignment,
)


class TestScheduleInstructorAssignment:
    def test_add_schedule_row_upserts_collaborator_assignment(self, db_conn):
        uid = uuid.uuid4().hex[:8]
        cur = db_conn.cursor()
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (f"SA{uid}".upper()[:12], "أ", "A"),
        )
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (f"SB{uid}".upper()[:12], "ب", "B"),
        )
        d1 = cur.execute("SELECT id FROM departments WHERE code = ?", (f"SA{uid}".upper()[:12],)).fetchone()[0]
        d2 = cur.execute("SELECT id FROM departments WHERE code = ?", (f"SB{uid}".upper()[:12],)).fetchone()[0]
        cur.execute(
            "INSERT INTO instructors (name, type, is_active, department_id) VALUES (?, 'internal', 1, ?)",
            (f"SchedInst {uid}", d1),
        )
        iid = int(cur.lastrowid)
        db_conn.commit()

        res = ScheduleService.add_schedule_row(
            course_name=f"Course-{uid}",
            day="الأحد",
            time="08:00-09:00",
            room="R9",
            instructor="",
            semester="خريف 44-45",
            instructor_id=iid,
            department_id=int(d2),
        )
        assert res.get("status") == "ok"

        row = db_conn.execute(
            """
            SELECT migration_source, is_active, schedule_section_id, semester
            FROM instructor_department_assignments
            WHERE instructor_id = ? AND department_id = ?
              AND schedule_section_id = ? AND semester = ''
            """,
            (iid, int(d2), HOME_ASSIGNMENT_SECTION_ID),
        ).fetchone()
        assert row is not None
        assert int(row[1]) == 1
        assert (row[0] or "") == "schedule_save"

    def test_home_department_does_not_create_assignment(self, db_conn):
        uid = uuid.uuid4().hex[:8]
        cur = db_conn.cursor()
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (f"SC{uid}".upper()[:12], "ج", "C"),
        )
        did = cur.execute("SELECT id FROM departments WHERE code = ?", (f"SC{uid}".upper()[:12],)).fetchone()[0]
        cur.execute(
            "INSERT INTO instructors (name, type, is_active, department_id) VALUES (?, 'internal', 1, ?)",
            (f"HomeOnly {uid}", did),
        )
        iid = int(cur.lastrowid)
        db_conn.commit()

        ScheduleService.add_schedule_row(
            course_name=f"HomeCourse-{uid}",
            day="الإثنين",
            time="09:00-10:00",
            room="R2",
            semester="خريف 44-45",
            instructor_id=iid,
            department_id=int(did),
        )
        n = db_conn.execute(
            """
            SELECT COUNT(*) FROM instructor_department_assignments
            WHERE instructor_id = ? AND department_id = ?
              AND schedule_section_id = ? AND semester = ''
              AND migration_source = 'schedule_save'
            """,
            (iid, int(did), HOME_ASSIGNMENT_SECTION_ID),
        ).fetchone()[0]
        assert int(n) == 0

    def test_user_ui_source_preserved_on_schedule_upsert(self, db_conn):
        uid = uuid.uuid4().hex[:8]
        cur = db_conn.cursor()
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (f"SD{uid}".upper()[:12], "د1", "D1"),
        )
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (f"SE{uid}".upper()[:12], "د2", "D2"),
        )
        d1 = cur.execute("SELECT id FROM departments WHERE code = ?", (f"SD{uid}".upper()[:12],)).fetchone()[0]
        d2 = cur.execute("SELECT id FROM departments WHERE code = ?", (f"SE{uid}".upper()[:12],)).fetchone()[0]
        cur.execute(
            "INSERT INTO instructors (name, type, is_active, department_id) VALUES (?, 'internal', 1, ?)",
            (f"Preserve {uid}", d1),
        )
        iid = int(cur.lastrowid)
        upsert_user_assignment(db_conn, instructor_id=iid, department_id=int(d2), source="user_ui")
        db_conn.commit()

        upsert_schedule_derived_assignment(
            db_conn, instructor_id=iid, department_id=int(d2), source="schedule_save"
        )
        db_conn.commit()
        src = db_conn.execute(
            """
            SELECT migration_source FROM instructor_department_assignments
            WHERE instructor_id = ? AND department_id = ?
              AND schedule_section_id = ? AND semester = ''
            """,
            (iid, int(d2), HOME_ASSIGNMENT_SECTION_ID),
        ).fetchone()[0]
        assert src == "user_ui"

    def test_no_instructor_id_skips_assignment(self, db_conn):
        uid = uuid.uuid4().hex[:8]
        cur = db_conn.cursor()
        cur.execute(
            "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
            (f"SF{uid}".upper()[:12], "ف", "F"),
        )
        did = cur.execute("SELECT id FROM departments WHERE code = ?", (f"SF{uid}".upper()[:12],)).fetchone()[0]
        db_conn.commit()
        before = db_conn.execute("SELECT COUNT(*) FROM instructor_department_assignments").fetchone()[0]
        ScheduleService.add_schedule_row(
            course_name=f"FreeText-{uid}",
            day="الثلاثاء",
            time="10:00-11:00",
            room="R3",
            instructor="اسم حر",
            semester="خريف 44-45",
            instructor_id=None,
            department_id=int(did),
        )
        after = db_conn.execute("SELECT COUNT(*) FROM instructor_department_assignments").fetchone()[0]
        assert int(after) == int(before)
