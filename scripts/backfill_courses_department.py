#!/usr/bin/env python3
"""ربط owning_department_id للمقررات من جدول schedule (مرحلة جودة البيانات)."""
from __future__ import annotations

import argparse
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

os.environ.setdefault("ADMIN_PASSWORD", "backfill-local")
os.environ.setdefault("SECRET_KEY", "backfill-local")


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill courses.owning_department_id from schedule")
    parser.add_argument("--department-id", type=int, default=None, help="Limit to one department id")
    parser.add_argument("--dry-run", action="store_true", help="Count only, no commit")
    args = parser.parse_args()

    from backend.database.database import close_pool, get_connection
    from backend.core.department_scope_policy import backfill_courses_owning_department_from_schedule

    try:
        with get_connection() as conn:
            if args.dry_run:
                from backend.database.database import fetch_table_columns

                cols = fetch_table_columns(conn, "courses")
                if "owning_department_id" not in cols:
                    print("owning_department_id column missing")
                    return 1
                cur = conn.cursor()
                params: list = []
                dept_filter = ""
                if args.department_id is not None:
                    dept_filter = " AND COALESCE(s.department_id, -1) = ? "
                    params = [int(args.department_id)]
                row = cur.execute(
                    f"""
                    SELECT COUNT(*) FROM courses c
                    WHERE COALESCE(c.owning_department_id, 0) = 0
                      AND EXISTS (
                        SELECT 1 FROM schedule s
                        WHERE lower(trim(s.course_name)) = lower(trim(c.course_name))
                          AND COALESCE(s.department_id, -1) > 0
                          {dept_filter}
                      )
                    """,
                    tuple(params),
                ).fetchone()
                n = int(row[0] if row else 0)
                print(f"Would update {n} course(s)")
                return 0

            n = backfill_courses_owning_department_from_schedule(
                conn, department_id=args.department_id
            )
            conn.commit()
            print(f"Updated {n} course(s)")
        return 0
    finally:
        close_pool()


if __name__ == "__main__":
    raise SystemExit(main())
