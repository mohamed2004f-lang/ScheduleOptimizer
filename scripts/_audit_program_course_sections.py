#!/usr/bin/env python3
"""تدقيق: هل program_course_sections مستخدم فعلياً؟"""
from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("ADMIN_PASSWORD", "audit")
os.environ.setdefault("SECRET_KEY", "audit")

from backend.core.feature_flags import registration_program_course_mode
from backend.database.database import fetch_table_columns, is_postgresql, table_exists
from backend.services.utilities import get_connection


def main() -> int:
    with get_connection() as conn:
        cur = conn.cursor()
        print("=== تدقيق program_course_sections ===")
        print("المحرك:", "PostgreSQL" if is_postgresql() else "SQLite/أخرى")
        print("REG_PROGRAM_COURSE_MODE:", registration_program_course_mode())

        if not table_exists(conn, "program_course_sections"):
            print("program_course_sections: REMOVED (use teaching_groups)")
        else:
            total = cur.execute("SELECT COUNT(*) FROM program_course_sections").fetchone()[0]
            active = cur.execute(
                "SELECT COUNT(*) FROM program_course_sections WHERE COALESCE(is_active, 1) = 1"
            ).fetchone()[0]
            print(f"program_course_sections: total={total}, active={active}")
            rows = cur.execute(
                """
                SELECT id, program_course_id, section_code, capacity_max, semester, is_active, note
                FROM program_course_sections
                ORDER BY program_course_id, section_code
                """
            ).fetchall()
            print("--- الصفوف ---")
            for r in rows:
                print(" ", dict(r) if hasattr(r, "keys") else r)

        if table_exists(conn, "program_courses"):
            pc = cur.execute("SELECT COUNT(*) FROM program_courses").fetchone()[0]
            print(f"program_courses (خطة البرنامج): {pc}")

        if table_exists(conn, "teaching_groups"):
            tg = cur.execute(
                "SELECT COUNT(*) FROM teaching_groups WHERE COALESCE(is_active, 1) = 1"
            ).fetchone()[0]
            print(f"teaching_groups (تشغيل فعلي): {tg}")
            if int(tg) > 0:
                sample = cur.execute(
                    """
                    SELECT tg.id, tg.course_name, tg.group_code, tg.group_kind, tg.semester,
                           tg.capacity_max,
                           (SELECT COUNT(DISTINCT r.student_id)
                            FROM registrations r WHERE r.teaching_group_id = tg.id) AS enrolled
                    FROM teaching_groups tg
                    WHERE COALESCE(tg.is_active, 1) = 1
                    ORDER BY tg.semester DESC, tg.course_name, tg.group_code
                    LIMIT 10
                    """
                ).fetchall()
                print("--- عينة teaching_groups ---")
                for r in sample:
                    print(" ", dict(r) if hasattr(r, "keys") else r)

        if table_exists(conn, "registrations"):
            rcols = {c.lower() for c in fetch_table_columns(conn, "registrations")}
            reg_total = cur.execute("SELECT COUNT(*) FROM registrations").fetchone()[0]
            print(f"registrations: {reg_total}")
            if "program_course_id" in rcols:
                with_pc = cur.execute(
                    "SELECT COUNT(*) FROM registrations WHERE program_course_id IS NOT NULL AND program_course_id > 0"
                ).fetchone()[0]
                print(f"  linked program_course_id: {with_pc}")
            if "teaching_group_id" in rcols:
                with_tg = cur.execute(
                    "SELECT COUNT(*) FROM registrations WHERE teaching_group_id IS NOT NULL AND teaching_group_id > 0"
                ).fetchone()[0]
                print(f"  linked teaching_group_id: {with_tg}")

        split = 0
        if table_exists(conn, "teaching_groups"):
            split = cur.execute(
                "SELECT COUNT(*) FROM teaching_groups WHERE group_kind = 'split' AND COALESCE(is_active, 1) = 1"
            ).fetchone()[0]
            print(f"teaching_groups split: {split}")

        print()
        print("=== verdict ===")
        if not table_exists(conn, "program_course_sections"):
            print("OK: program_course_sections removed — teaching_groups is the source of truth.")
        elif int(total) == 0:
            print("OK: program_course_sections empty — safe to drop.")
        else:
            print("WARN: program_course_sections has rows — review before delete.")

        if table_exists(conn, "teaching_groups"):
            tg_n = cur.execute(
                "SELECT COUNT(*) FROM teaching_groups WHERE COALESCE(is_active, 1) = 1"
            ).fetchone()[0]
            if int(tg_n) > 0:
                print(f"OK: runtime uses teaching_groups ({tg_n} groups), not catalog sections.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
