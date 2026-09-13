"""سياسة ظهور/إدارة الأستاذ متعدد الأقسام."""
from __future__ import annotations

import uuid

from backend.core.department_scope_policy import (
    actor_can_link_instructor_to_scoped_department,
    actor_can_manage_existing_instructor,
    actor_can_manage_instructor_identity,
    actor_can_unlink_instructor_from_scoped_department,
    instructor_has_active_assignment_in_department,
    instructor_is_home_in_department,
    instructor_matches_department,
    instructor_relation_to_department,
    instructor_visible_in_department_scope,
)
from backend.database.database import HOME_ASSIGNMENT_SECTION_ID
from backend.repositories.instructor_assignments_repo import upsert_user_assignment
from backend.repositories.instructor_students_repo import instructor_linked_to_department


def _two_depts_and_instructor(db_conn, *, home_on_first: bool = True):
    uid = uuid.uuid4().hex[:8]
    cur = db_conn.cursor()
    cur.execute(
        "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
        (f"HA{uid}".upper()[:12], "منزل", "Home"),
    )
    cur.execute(
        "INSERT INTO departments (code, name_ar, name_en, is_active) VALUES (?, ?, ?, 1)",
        (f"HB{uid}".upper()[:12], "مضيف", "Host"),
    )
    d1 = cur.execute("SELECT id FROM departments WHERE code = ?", (f"HA{uid}".upper()[:12],)).fetchone()[0]
    d2 = cur.execute("SELECT id FROM departments WHERE code = ?", (f"HB{uid}".upper()[:12],)).fetchone()[0]
    home = d1 if home_on_first else d2
    cur.execute(
        "INSERT INTO instructors (name, type, email, is_active, department_id) VALUES (?, 'internal', NULL, 1, ?)",
        (f"Inst {uid}", home),
    )
    iid = int(cur.lastrowid)
    db_conn.commit()
    return int(d1), int(d2), iid


class TestInstructorScopePolicy:
    def test_home_relation_and_manage(self, db_conn):
        d1, d2, iid = _two_depts_and_instructor(db_conn)
        assert instructor_is_home_in_department(db_conn, iid, d1) is True
        assert instructor_matches_department(db_conn, iid, d1) is True
        assert instructor_visible_in_department_scope(db_conn, iid, d1) is True
        assert instructor_relation_to_department(db_conn, iid, d1) == "home"
        assert instructor_visible_in_department_scope(db_conn, iid, d2) is False
        assert instructor_relation_to_department(db_conn, iid, d2) == "none"

    def test_assignment_makes_collaborator_visible_not_manageable(self, app, db_conn):
        d1, d2, iid = _two_depts_and_instructor(db_conn)
        upsert_user_assignment(db_conn, instructor_id=iid, department_id=d2, source="user_ui")
        db_conn.commit()

        assert instructor_has_active_assignment_in_department(db_conn, iid, d2) is True
        assert instructor_visible_in_department_scope(db_conn, iid, d2) is True
        assert instructor_relation_to_department(db_conn, iid, d2) == "collaborator"
        assert instructor_is_home_in_department(db_conn, iid, d2) is False
        assert instructor_matches_department(db_conn, iid, d2) is False

        uid = uuid.uuid4().hex[:8]
        pw = db_conn.execute(
            "SELECT password_hash FROM users WHERE username = 'admin-test' LIMIT 1"
        ).fetchone()[0]
        host_user = f"hod_host_{uid}"
        db_conn.execute(
            "INSERT INTO users (username, password_hash, role, department_id) VALUES (?, ?, 'head_of_department', ?)",
            (host_user, pw, d2),
        )
        db_conn.commit()

        assert actor_can_manage_instructor_identity(db_conn, host_user, iid) is False
        assert actor_can_manage_existing_instructor(db_conn, host_user, iid) is False
        ok_link, _ = actor_can_link_instructor_to_scoped_department(db_conn, host_user, iid, d2)
        # already linked; still allowed to re-link/activate
        assert ok_link is True
        ok_unlink, _ = actor_can_unlink_instructor_from_scoped_department(db_conn, host_user, iid, d2)
        assert ok_unlink is True

    def test_schedule_row_alone_not_visible_in_policy(self, db_conn):
        d1, d2, iid = _two_depts_and_instructor(db_conn)
        db_conn.execute(
            """
            INSERT INTO schedule (course_name, day, time, room, instructor, instructor_id, semester, department_id)
            VALUES (?, 'الأحد', '08:00-09:00', 'R1', 'x', ?, 'خريف 44-45', ?)
            """,
            (f"C-{uuid.uuid4().hex[:6]}", iid, d2),
        )
        db_conn.commit()
        assert instructor_visible_in_department_scope(db_conn, iid, d2) is False
        assert instructor_linked_to_department(db_conn, iid, d2, include_schedule=True) is True
        assert instructor_linked_to_department(db_conn, iid, d2, include_schedule=False) is False

    def test_unlink_rejects_home_department(self, db_conn):
        d1, d2, iid = _two_depts_and_instructor(db_conn)
        uid = uuid.uuid4().hex[:8]
        pw = db_conn.execute(
            "SELECT password_hash FROM users WHERE username = 'admin-test' LIMIT 1"
        ).fetchone()[0]
        home_user = f"hod_home_{uid}"
        db_conn.execute(
            "INSERT INTO users (username, password_hash, role, department_id) VALUES (?, ?, 'head_of_department', ?)",
            (home_user, pw, d1),
        )
        db_conn.commit()
        ok, msg = actor_can_unlink_instructor_from_scoped_department(db_conn, home_user, iid, d1)
        assert ok is False
        assert msg

    def test_home_assignment_key_constant(self):
        assert HOME_ASSIGNMENT_SECTION_ID == -1
