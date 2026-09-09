# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
except Exception:
    pass
os.environ.setdefault("ADMIN_PASSWORD", "x")
os.environ.setdefault("SECRET_KEY", "x")


def main() -> None:
    from backend.database.database import close_pool, fetch_table_columns, get_connection
    from backend.repositories.courses_repo import (
        find_course_code_duplicate_ci,
        find_course_name_duplicate_ci,
    )

    name = "قياسات هندسية"
    with get_connection() as conn:
        cur = conn.cursor()
        cols = fetch_table_columns(conn, "courses")
        print("has is_archived", "is_archived" in cols)
        rows = cur.execute(
            """
            SELECT course_name, course_code, units, owning_department_id,
                   COALESCE(is_archived, 0) AS is_archived
            FROM courses
            WHERE course_name LIKE ?
               OR course_code LIKE ?
            """,
            ("%قياسات%", "%209%"),
        ).fetchall()
        print("like hits", len(rows))
        for r in rows:
            print(" ", dict(r) if hasattr(r, "keys") else r)

        dup = find_course_name_duplicate_ci(conn, name)
        print("name_dup", dict(dup) if dup is not None and hasattr(dup, "keys") else dup)
        code_dup = find_course_code_duplicate_ci(conn, "ME 209")
        print("code_dup", dict(code_dup) if code_dup is not None and hasattr(code_dup, "keys") else code_dup)

        # list filter: active only?
        active = cur.execute(
            """
            SELECT course_name, course_code, COALESCE(is_archived,0)
            FROM courses
            WHERE lower(trim(course_name)) = lower(trim(?))
              AND COALESCE(is_archived,0) = 0
            """,
            (name,),
        ).fetchall()
        print("active exact", active)
        archived = cur.execute(
            """
            SELECT course_name, course_code, COALESCE(is_archived,0)
            FROM courses
            WHERE lower(trim(course_name)) = lower(trim(?))
              AND COALESCE(is_archived,0) = 1
            """,
            (name,),
        ).fetchall()
        print("archived exact", archived)

        # grades/schedule usage
        for table, col in (
            ("grades", "course_name"),
            ("schedule", "course_name"),
            ("registrations", "course_name"),
            ("prereqs", "course_name"),
        ):
            try:
                n = cur.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE lower(trim({col})) = lower(trim(?))",
                    (name,),
                ).fetchone()[0]
                print(f"usage {table}.{col}", n)
            except Exception as e:
                print(f"usage {table}", e)
    close_pool()


if __name__ == "__main__":
    main()
