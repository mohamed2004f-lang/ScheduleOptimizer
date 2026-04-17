#!/usr/bin/env python3
"""
Backfill blank `schedule.semester` rows to the current term label.

Modes:
- preview: show how many rows would change, and a sample
- apply: perform the UPDATE

Usage (from repo root):
  python scripts/backfill_schedule_semester.py preview
  python scripts/backfill_schedule_semester.py apply
  python scripts/backfill_schedule_semester.py apply --dry-run
  python scripts/backfill_schedule_semester.py preview --limit 50
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.database.database import get_connection, is_postgresql  # noqa: E402
from backend.services.utilities import get_current_term  # noqa: E402


def _term_label(conn) -> str:
    name, year = get_current_term(conn=conn)
    return f"{(name or '').strip()} {(year or '').strip()}".strip()


def _qmarks_or_percent(sql: str) -> str:
    return sql.replace("?", "%s") if is_postgresql() else sql


def _fetchall(conn, sql: str, params: tuple):
    cur = conn.cursor()
    cur.execute(_qmarks_or_percent(sql), params)
    return cur.fetchall()


def _execute(conn, sql: str, params: tuple):
    cur = conn.cursor()
    cur.execute(_qmarks_or_percent(sql), params)
    return cur


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["preview", "apply"])
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    with get_connection() as conn:
        term = _term_label(conn)
        if not term:
            print("ERROR: current term is not set (system_settings current_term_name/year).", file=sys.stderr)
            return 2

        rows = _fetchall(
            conn,
            """
            SELECT rowid, course_name, day, time, instructor, instructor_id, semester
            FROM schedule
            WHERE TRIM(COALESCE(semester,'')) = ''
            ORDER BY course_name, day, time
            LIMIT ?
            """,
            (int(args.limit),),
        )
        count_blank = _fetchall(
            conn, "SELECT COUNT(*) FROM schedule WHERE TRIM(COALESCE(semester,'')) = ''", ()
        )[0][0]

        print("db:", "PostgreSQL" if is_postgresql() else "SQLite")
        print("current_term_label:", repr(term))
        print("blank_semester_rows:", int(count_blank))
        if rows:
            print("\nSAMPLE (blank semester):")
            for r in rows:
                rowid, course_name, day, time, instructor, instructor_id, semester = r
                print(
                    " - rowid=%s course=%r day=%r time=%r instructor=%r instructor_id=%r semester=%r"
                    % (rowid, course_name, day, time, instructor, instructor_id, semester)
                )

        if args.mode == "preview":
            return 0

        if args.dry_run:
            print("\ndry_run: no changes applied.")
            return 0

        # Apply: update only blanks
        _execute(
            conn,
            "UPDATE schedule SET semester = ? WHERE TRIM(COALESCE(semester,'')) = ''",
            (term,),
        )
        conn.commit()
        print("\napplied: set schedule.semester for blank rows to", repr(term))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

