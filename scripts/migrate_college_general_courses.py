#!/usr/bin/env python3
"""ترحيل ملكية مقررات الاتجاه العام إلى قسم GENERAL."""
from __future__ import annotations

import argparse
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

os.environ.setdefault("ADMIN_PASSWORD", "migrate-local")
os.environ.setdefault("SECRET_KEY", "migrate-local")


def _college_general_course_names(conn) -> list[str]:
    from backend.database.database import fetch_table_columns

    pc_cols = fetch_table_columns(conn, "program_courses")
    if "requirement_scope" not in pc_cols:
        return []
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT DISTINCT COALESCE(NULLIF(TRIM(c.course_name), ''), NULLIF(TRIM(pc.course_name_override), '')) AS cname
        FROM program_courses pc
        LEFT JOIN course_master cm ON cm.id = pc.course_master_id
        LEFT JOIN courses c ON (
          (c.course_master_id IS NOT NULL AND c.course_master_id = pc.course_master_id)
          OR lower(trim(COALESCE(c.course_code, ''))) = lower(trim(COALESCE(pc.course_code, '')))
          OR lower(trim(COALESCE(c.course_name, ''))) = lower(trim(COALESCE(cm.title_ar, '')))
        )
        WHERE COALESCE(pc.requirement_scope, 'dept_common') = 'college_general'
          AND COALESCE(pc.is_active, 1) = 1
          AND COALESCE(NULLIF(TRIM(c.course_name), ''), NULLIF(TRIM(pc.course_name_override), '')) IS NOT NULL
        """
    ).fetchall()
    out: list[str] = []
    for r in rows:
        name = r[0] if not hasattr(r, "keys") else r["cname"]
        if name and str(name).strip():
            out.append(str(name).strip())
    return sorted(set(out))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Assign college_general courses to GENERAL department ownership"
    )
    parser.add_argument("--dry-run", action="store_true", help="Report only, no commit")
    args = parser.parse_args()

    from backend.database.database import close_pool, get_connection, fetch_table_columns
    from backend.core.department_scope_policy import resolve_college_general_department_id

    try:
        with get_connection() as conn:
            try:
                from config import DATABASE_URL
            except Exception:
                DATABASE_URL = os.environ.get("DATABASE_URL") or ""
            db_hint = (DATABASE_URL or "").split("@")[-1] if "@" in (DATABASE_URL or "") else (DATABASE_URL or "unknown")
            print(f"Database target: {db_hint}")
            cols = fetch_table_columns(conn, "courses")
            if "owning_department_id" not in cols:
                print("owning_department_id column missing")
                return 1
            gen_id = resolve_college_general_department_id(conn)
            if gen_id is None:
                print("GENERAL department not found — create it first (code=GENERAL)")
                return 1
            names = _college_general_course_names(conn)
            if not names:
                print("No college_general courses found in program_courses")
                return 0
            cur = conn.cursor()
            placeholders = ",".join("?" for _ in names)
            wrong = cur.execute(
                f"""
                SELECT course_name, owning_department_id FROM courses
                WHERE course_name IN ({placeholders})
                  AND COALESCE(owning_department_id, -1) <> ?
                """,
                (*names, int(gen_id)),
            ).fetchall()
            print(f"College general courses in catalog: {len(names)}")
            print(f"Rows needing migration: {len(wrong)}")
            if not wrong:
                print("Nothing to do — all college_general courses already owned by GENERAL.")
                return 0
            for r in wrong[:20]:
                cname = r[0] if not hasattr(r, "keys") else r["course_name"]
                oid = r[1] if not hasattr(r, "keys") else r["owning_department_id"]
                print(f"  - {cname} (owning_department_id={oid}) -> {gen_id}")
            if len(wrong) > 20:
                print(f"  ... and {len(wrong) - 20} more")
            if args.dry_run:
                return 0
            cur.execute(
                f"""
                UPDATE courses
                SET owning_department_id = ?
                WHERE course_name IN ({placeholders})
                  AND COALESCE(owning_department_id, -1) <> ?
                """,
                (int(gen_id), *names, int(gen_id)),
            )
            conn.commit()
            print(f"Updated {int(cur.rowcount or 0)} course(s)")
        return 0
    finally:
        close_pool()


if __name__ == "__main__":
    raise SystemExit(main())
