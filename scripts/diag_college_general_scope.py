#!/usr/bin/env python3
"""تشخيص ظهور مقررات الاتجاه العام لرؤساء الأقسام."""
from __future__ import annotations

import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

os.environ.setdefault("ADMIN_PASSWORD", "diag-local")
os.environ.setdefault("SECRET_KEY", "diag-local")


def main() -> int:
    from backend.database.database import close_pool, get_connection
    from backend.core.department_scope_policy import (
        courses_department_scope_filter,
        resolve_college_general_department_id,
    )

    try:
        with get_connection() as conn:
            cur = conn.cursor()
            gen_id = resolve_college_general_department_id(conn)
            print("GENERAL department id:", gen_id)
            rows = cur.execute(
                """
                SELECT id, code, name_ar FROM departments
                WHERE COALESCE(is_active, 1) = 1
                ORDER BY id
                """
            ).fetchall()
            print("\nDepartments:")
            for r in rows:
                rid = r[0] if not hasattr(r, "keys") else r["id"]
                code = r[1] if not hasattr(r, "keys") else r["code"]
                name = r[2] if not hasattr(r, "keys") else r["name_ar"]
                print(f"  {rid}: {code} — {name}")

            gen_courses = cur.execute(
                """
                SELECT course_name, owning_department_id FROM courses
                WHERE COALESCE(owning_department_id, -1) = ?
                ORDER BY course_name
                LIMIT 20
                """,
                (int(gen_id) if gen_id is not None else -999,),
            ).fetchall()
            print(f"\nCourses owned by GENERAL (sample {len(gen_courses)}):")
            for r in gen_courses:
                print(f"  - {r[0]} (dept={r[1]})")

            print("\nVisible course counts per department (scope filter):")
            for r in rows:
                dep = int(r[0] if not hasattr(r, "keys") else r["id"])
                code = r[1] if not hasattr(r, "keys") else r["code"]
                if str(code).strip().upper() == "GENERAL":
                    continue
                scope_sql, scope_params = courses_department_scope_filter(conn, dep)
                q = (
                    "SELECT COUNT(*) FROM courses WHERE COALESCE(course_name, '') <> ''"
                    + scope_sql
                )
                n = cur.execute(q, scope_params).fetchone()[0]
                print(f"  dept {dep} ({code}): {n} courses")
        return 0
    finally:
        close_pool()


if __name__ == "__main__":
    raise SystemExit(main())
