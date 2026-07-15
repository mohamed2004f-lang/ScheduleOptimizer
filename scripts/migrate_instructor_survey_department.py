#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from backend.services.utilities import get_connection


def _pick_department_id(cur, prefer_id: int | None, name_hints: tuple[str, ...]) -> tuple[int | None, str]:
    if prefer_id is not None:
        row = cur.execute(
            "SELECT id, COALESCE(name_ar, '') FROM departments WHERE id = ? LIMIT 1",
            (int(prefer_id),),
        ).fetchone()
        if row:
            return int(row[0] if not hasattr(row, "keys") else row["id"]), (
                row[1] if not hasattr(row, "keys") else row["name_ar"]
            ) or ""
    rows = cur.execute("SELECT id, COALESCE(name_ar, '') AS name_ar FROM departments").fetchall()
    for row in rows:
        did = int(row[0] if not hasattr(row, "keys") else row["id"])
        name = (row[1] if not hasattr(row, "keys") else row["name_ar"]) or ""
        if any(h in name for h in name_hints):
            return did, name
    return None, ""


def _counts(cur, instructor_id: str, dept_id: int, template_codes: tuple[str, ...]) -> list[tuple[str, int]]:
    placeholders = ",".join("?" for _ in template_codes)
    rows = cur.execute(
        f"""
        SELECT template_code, COUNT(*) AS cnt
        FROM survey_responses
        WHERE respondent_id = ? AND department_id = ? AND template_code IN ({placeholders})
        GROUP BY template_code
        ORDER BY template_code
        """,
        (instructor_id, int(dept_id), *template_codes),
    ).fetchall()
    out: list[tuple[str, int]] = []
    for row in rows:
        code = (row[0] if not hasattr(row, "keys") else row["template_code"]) or ""
        cnt = int(row[1] if not hasattr(row, "keys") else row["cnt"])
        out.append((str(code), cnt))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Move instructor survey responses from one department to another."
    )
    parser.add_argument("--instructor-id", required=True, help="Instructor/respondent id (e.g. 9)")
    parser.add_argument("--from-dept-id", type=int, default=None, help="Source department id")
    parser.add_argument("--to-dept-id", type=int, default=None, help="Destination department id")
    parser.add_argument(
        "--template-codes",
        default="faculty_hod,supervisor_advising,supervisor_coordination",
        help="Comma-separated template codes to move",
    )
    args = parser.parse_args()

    template_codes = tuple(c.strip() for c in (args.template_codes or "").split(",") if c.strip())
    if not template_codes:
        print("No template codes provided.")
        return 2

    with get_connection() as conn:
        cur = conn.cursor()
        from_id, from_name = _pick_department_id(
            cur,
            args.from_dept_id,
            ("الهندسة الميكانيكية", "هندسة ميكانيكية", "ميكانيكية"),
        )
        to_id, to_name = _pick_department_id(
            cur,
            args.to_dept_id,
            ("الهندسة المدنية", "هندسة مدنية", "مدنية"),
        )
        if from_id is None or to_id is None:
            print(f"Department lookup failed: from={from_id}:{from_name} to={to_id}:{to_name}")
            return 2

        print(f"From department: {from_id} - {from_name}")
        print(f"To department:   {to_id} - {to_name}")
        print(f"Templates:       {', '.join(template_codes)}")

        before = _counts(cur, str(args.instructor_id), from_id, template_codes)
        print("Before (source) counts:")
        if not before:
            print("  (none)")
        for code, cnt in before:
            print(f"  {code}: {cnt}")

        placeholders = ",".join("?" for _ in template_codes)
        updated = cur.execute(
            f"""
            UPDATE survey_responses
            SET department_id = ?
            WHERE respondent_id = ? AND department_id = ? AND template_code IN ({placeholders})
            """,
            (int(to_id), str(args.instructor_id), int(from_id), *template_codes),
        ).rowcount
        conn.commit()
        print(f"Updated rows: {int(updated or 0)}")

        after_src = _counts(cur, str(args.instructor_id), from_id, template_codes)
        after_dst = _counts(cur, str(args.instructor_id), to_id, template_codes)

        print("After (source) counts:")
        if not after_src:
            print("  (none)")
        for code, cnt in after_src:
            print(f"  {code}: {cnt}")

        print("After (destination) counts:")
        if not after_dst:
            print("  (none)")
        for code, cnt in after_dst:
            print(f"  {code}: {cnt}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
