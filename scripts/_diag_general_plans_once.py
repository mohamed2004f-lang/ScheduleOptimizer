#!/usr/bin/env python3
from __future__ import annotations

import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

os.environ.setdefault("ADMIN_PASSWORD", "diag-local")
os.environ.setdefault("SECRET_KEY", "diag-local")

from backend.database.database import close_pool, get_connection
from backend.services.college_catalog import ensure_college_general_plan_items
from backend.core.department_scope_policy import (
    courses_department_scope_filter,
    resolve_college_general_department_id,
)


def main() -> int:
    with get_connection() as conn:
        cur = conn.cursor()
        gen = resolve_college_general_department_id(conn)
        gen_n = cur.execute(
            "SELECT COUNT(*) FROM courses WHERE owning_department_id = ?",
            (int(gen),),
        ).fetchone()[0]
        print("GENERAL-owned courses:", gen_n)
        for dep_id, code in ((2, "MECH"), (3, "CIVIL"), (4, "ELEC"), (5, "RENEW")):
            sql, params = courses_department_scope_filter(conn, dep_id)
            n = cur.execute(
                "SELECT COUNT(*) FROM courses WHERE COALESCE(course_name,'') <> ''" + sql,
                params,
            ).fetchone()[0]
            gen_vis = cur.execute(
                "SELECT COUNT(*) FROM courses WHERE owning_department_id = ?" + sql,
                (int(gen), *params),
            ).fetchone()[0]
            print(f"  {code}: visible={n}, general_in_view={gen_vis}")

        rows = cur.execute(
            """
            SELECT p.id, p.code, d.code
            FROM programs p
            JOIN departments d ON d.id = p.department_id
            WHERE d.code IN ('CIVIL', 'ELEC', 'RENEW', 'MECH')
            ORDER BY d.code, p.code
            """
        ).fetchall()
        print("\nSync college_general onto specialty programs:")
        for r in rows:
            pid, pcode, dcode = int(r[0]), r[1], r[2]
            before = cur.execute(
                """
                SELECT COUNT(*) FROM program_courses
                WHERE program_id = ?
                  AND requirement_scope = 'college_general'
                  AND COALESCE(is_active, 1) = 1
                """,
                (pid,),
            ).fetchone()[0]
            added = ensure_college_general_plan_items(conn, pid)
            after = cur.execute(
                """
                SELECT COUNT(*) FROM program_courses
                WHERE program_id = ?
                  AND requirement_scope = 'college_general'
                  AND COALESCE(is_active, 1) = 1
                """,
                (pid,),
            ).fetchone()[0]
            print(f"  {dcode}/{pcode}: before={before} added={added} after={after}")
    close_pool()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
