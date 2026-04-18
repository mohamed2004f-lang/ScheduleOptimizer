#!/usr/bin/env python3
"""
Audit `schedule.semester` quality vs current term settings.

Outputs counts and a small sample of:
- blank semester rows
- rows with semester != current term
- rows with semester == current term

Usage (from repo root):
  python scripts/audit_schedule_semester.py
  python scripts/audit_schedule_semester.py --limit 50
  python scripts/audit_schedule_semester.py --csv out.csv
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.database.database import get_connection, is_postgresql, schedule_pk_column  # noqa: E402
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--csv", type=str, default="")
    args = ap.parse_args()

    with get_connection() as conn:
        sched_pk = schedule_pk_column(conn)
        term = _term_label(conn)
        if not term:
            print("ERROR: current term is not set in system_settings.", file=sys.stderr)
            return 2

        total = _fetchall(conn, "SELECT COUNT(*) FROM schedule", ())[0][0]
        blank = _fetchall(
            conn,
            "SELECT COUNT(*) FROM schedule WHERE TRIM(COALESCE(semester,'')) = ''",
            (),
        )[0][0]
        match = _fetchall(
            conn,
            "SELECT COUNT(*) FROM schedule WHERE TRIM(COALESCE(semester,'')) = ?",
            (term,),
        )[0][0]
        mismatch = _fetchall(
            conn,
            "SELECT COUNT(*) FROM schedule WHERE TRIM(COALESCE(semester,'')) <> '' AND TRIM(COALESCE(semester,'')) <> ?",
            (term,),
        )[0][0]

        print("db:", "PostgreSQL" if is_postgresql() else "SQLite")
        print("current_term_label:", repr(term))
        print("schedule_total_rows:", int(total))
        print("schedule_blank_semester_rows:", int(blank))
        print("schedule_current_term_rows:", int(match))
        print("schedule_mismatched_term_rows:", int(mismatch))

        sample = _fetchall(
            conn,
            f"""
            SELECT {sched_pk}, course_name, day, time, room, instructor, instructor_id, semester
            FROM schedule
            WHERE TRIM(COALESCE(semester,'')) = '' OR TRIM(COALESCE(semester,'')) <> ?
            ORDER BY semester, course_name, day, time
            LIMIT ?
            """,
            (term, int(args.limit)),
        )

        if args.csv:
            with open(args.csv, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["section_id", "course_name", "day", "time", "room", "instructor", "instructor_id", "semester"])
                for r in sample:
                    w.writerow(list(r))
            print("wrote_csv:", args.csv)
        else:
            if sample:
                print("\nSAMPLE (blank or mismatched semester):")
                for r in sample:
                    section_id, course_name, day, time, room, instructor, instructor_id, semester = r
                    print(
                        " - section_id=%s course=%r day=%r time=%r room=%r instructor=%r instructor_id=%r semester=%r"
                        % (section_id, course_name, day, time, room, instructor, instructor_id, semester)
                    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

