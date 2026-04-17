#!/usr/bin/env python3
"""
Diagnose instructor vs schedule vs current term (grade drafts).
Run from repo root: python scripts/diagnose_instructor_grades.py [name_substring]
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.core.faculty_axes import normalize_instructor_name
from backend.database.database import get_connection, is_postgresql
from backend.services.utilities import get_current_term, schedule_semester_matches_current_term


def _fetchall(cur):
    return cur.fetchall()


def main() -> int:
    needle = (sys.argv[1] if len(sys.argv) > 1 else "الحاسي").strip()
    print("needle:", repr(needle))
    print("backend:", "PostgreSQL" if is_postgresql() else "SQLite")
    with get_connection() as conn:
        cur = conn.cursor()
        term_name, term_year = get_current_term(conn=conn)
        term_label = f"{(term_name or '').strip()} {(term_year or '').strip()}".strip()
        print("current_term_label:", repr(term_label))

        if is_postgresql():
            cur.execute(
                "SELECT id, name FROM instructors WHERE name ILIKE %s ORDER BY id",
                (f"%{needle}%",),
            )
        else:
            cur.execute(
                "SELECT id, name FROM instructors WHERE name LIKE ? ORDER BY id",
                (f"%{needle}%",),
            )
        inst_rows = _fetchall(cur)
        if not inst_rows:
            print("NO instructors matching needle.")
            return 1
        for ir in inst_rows:
            if isinstance(ir, dict):
                iid, iname = ir["id"], ir["name"]
            else:
                iid, iname = ir[0], ir[1]
            print("\n--- instructor id=%s name=%r ---" % (iid, iname))
            canon = normalize_instructor_name(iname)
            print("normalized(db name):", repr(canon))

            if is_postgresql():
                cur.execute(
                    "SELECT username, role, instructor_id FROM users WHERE instructor_id = %s",
                    (int(iid),),
                )
            else:
                cur.execute(
                    "SELECT username, role, instructor_id FROM users WHERE instructor_id = ?",
                    (int(iid),),
                )
            users = _fetchall(cur)
            print("users linked:", len(users))
            for u in users:
                if isinstance(u, dict):
                    print(" ", u.get("username"), u.get("role"), "instructor_id=", u.get("instructor_id"))
                else:
                    print(" ", u[0], u[1], "instructor_id=", u[2])

            if is_postgresql():
                cur.execute(
                    """
                    SELECT rowid, course_name, semester, instructor, instructor_id, day, time
                    FROM schedule
                    WHERE instructor_id = %s
                       OR (
 (instructor_id IS NULL OR instructor_id = 0)
                         AND TRIM(COALESCE(instructor, '')) <> ''
                       )
                    ORDER BY semester, day, course_name
                    """,
                    (int(iid),),
                )
            else:
                cur.execute(
                    """
                    SELECT rowid, course_name, semester, instructor, instructor_id, day, time
                    FROM schedule
                    WHERE instructor_id = ?
                       OR (
                         (instructor_id IS NULL OR instructor_id = 0)
                         AND TRIM(COALESCE(instructor, '')) <> ''
                       )
                    ORDER BY semester, day, course_name
                    """,
                    (int(iid),),
                )
            sched = _fetchall(cur)
            matched = []
            for r in sched:
                if isinstance(r, dict):
                    sid = r["rowid"]
                    cn = r["course_name"]
                    sem = r["semester"]
                    inst_txt = r["instructor"] or ""
                    iid_col = r["instructor_id"]
                else:
                    sid, cn, sem, inst_txt, iid_col = r[0], r[1], r[2], r[3], r[4]
                try:
                    iid_int = int(iid_col) if iid_col is not None else None
                except (TypeError, ValueError):
                    iid_int = None
                if iid_int == int(iid):
                    matched.append((sid, cn, sem, inst_txt, "by_id"))
                    continue
                if (iid_int is None or iid_int == 0) and normalize_instructor_name(inst_txt) == canon:
                    matched.append((sid, cn, sem, inst_txt, "by_name"))
            print("schedule rows for this faculty (id or normalized name):", len(matched))
            for sid, cn, sem, inst_txt, how in matched[:40]:
                if not term_label:
                    flag = "NO_TERM_SETTING"
                elif schedule_semester_matches_current_term(sem, term_label):
                    flag = "OK_TERM"
                else:
                    flag = "SEM_MISMATCH"
                print(" ", flag, "section_id(rowid)=", sid, "course=", repr(cn), "semester=", repr(sem), "instructor_col=", repr(inst_txt), how)
            if len(matched) > 40:
                print("  ...", len(matched) - 40, "more")

            if term_label:
                ok = [m for m in matched if schedule_semester_matches_current_term(m[2], term_label)]
                print("rows matching current_term_label (incl. blank semester):", len(ok))
                if matched and not ok:
                    print("HINT: set schedule.semester to current term label or leave blank for legacy.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
