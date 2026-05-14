"""
دمج صفوف courses المكررة (نفس الاسم بعد trim) مع الإبقاء على الصف الأكثر استخداماً في كشف الدرجات.

قاعدة اختيار الصف الفائز (winner):
  1) الأعلى عدداً في grades.course_name
  2) عند التعادل: الأعلى في registrations.course_name
  3) عند التعادل: يُفضَّل الاسم المطابق لـ trim() إن وُجد كصف في المجموعة

ثم نقل المراجع من الصفوف الخاسرة إلى الفائز، ثم حذف الصفوف الخاسرة من courses.

الاستخدام:
  python scripts/merge_duplicate_courses_by_grades.py           # معاينة
  python scripts/merge_duplicate_courses_by_grades.py --apply # تنفيذ

PostgreSQL فقط. قبل --apply: نسخة احتياطية.
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.database.database import get_connection, is_postgresql  # noqa: E402


def _cnt(cur, sql: str, params: tuple) -> int:
    r = cur.execute(sql, params).fetchone()
    if not r:
        return 0
    if isinstance(r, (list, tuple)):
        v = r[0]
    else:
        try:
            v = r[0]
        except Exception:
            v = list(r)[0] if len(r) else 0
    return int(v or 0)


def _pick_winner(cur, variants: list[str], trim_key: str) -> str:
    scores: list[tuple[int, int, str]] = []
    for v in variants:
        g = _cnt(cur, "SELECT COUNT(*) FROM grades WHERE course_name = ?", (v,))
        r = _cnt(cur, "SELECT COUNT(*) FROM registrations WHERE course_name = ?", (v,))
        scores.append((g, r, v))
    scores.sort(key=lambda x: (x[0], x[1]), reverse=True)
    best_g, best_r, _ = scores[0]
    top = [s for s in scores if s[0] == best_g and s[1] == best_r]
    if len(top) == 1:
        return top[0][2]
    for _g, _r, v in top:
        if v == trim_key:
            return v
    return top[0][2]


def _dedupe_grades(cur, winner: str, loser: str) -> None:
    cur.execute(
        """
        DELETE FROM grades g1
        WHERE g1.course_name = ?
          AND EXISTS (
            SELECT 1 FROM grades g2
            WHERE g2.student_id = g1.student_id
              AND g2.semester = g1.semester
              AND g2.course_name = ?
          )
        """,
        (loser, winner),
    )
    cur.execute(
        "UPDATE grades SET course_name = ? WHERE course_name = ?",
        (winner, loser),
    )


def _dedupe_registrations(cur, winner: str, loser: str) -> None:
    cur.execute(
        """
        DELETE FROM registrations r1
        WHERE r1.course_name = ?
          AND EXISTS (
            SELECT 1 FROM registrations r2
            WHERE r2.student_id = r1.student_id
              AND r2.course_name = ?
          )
        """,
        (loser, winner),
    )
    cur.execute(
        "UPDATE registrations SET course_name = ? WHERE course_name = ?",
        (winner, loser),
    )


def _dedupe_attendance(cur, winner: str, loser: str) -> None:
    cur.execute(
        """
        DELETE FROM attendance_records a1
        WHERE a1.course_name = ?
          AND EXISTS (
            SELECT 1 FROM attendance_records a2
            WHERE a2.student_id = a1.student_id
              AND a2.week_number = a1.week_number
              AND a2.course_name = ?
          )
        """,
        (loser, winner),
    )
    cur.execute(
        "UPDATE attendance_records SET course_name = ? WHERE course_name = ?",
        (winner, loser),
    )


def _merge_one(cur, winner: str, loser: str) -> None:
    _dedupe_grades(cur, winner, loser)
    _dedupe_registrations(cur, winner, loser)
    _dedupe_attendance(cur, winner, loser)

    cur.execute("UPDATE schedule SET course_name = ? WHERE course_name = ?", (winner, loser))
    cur.execute("UPDATE exams SET course_name = ? WHERE course_name = ?", (winner, loser))
    cur.execute(
        "UPDATE registration_changes_log SET course_name = ? WHERE course_name = ?",
        (winner, loser),
    )
    cur.execute(
        "UPDATE registration_requests SET course_name = ? WHERE course_name = ?",
        (winner, loser),
    )
    cur.execute("UPDATE grade_audit SET course_name = ? WHERE course_name = ?", (winner, loser))

    for tbl in ("grade_drafts", "grade_special_cases"):
        try:
            cur.execute(
                f"UPDATE {tbl} SET course_name = ? WHERE course_name = ?",
                (winner, loser),
            )
        except Exception:
            pass

    cur.execute(
        "UPDATE prereqs SET course_name = ? WHERE course_name = ?",
        (winner, loser),
    )
    cur.execute(
        "UPDATE prereqs SET required_course_name = ? WHERE required_course_name = ?",
        (winner, loser),
    )

    cur.execute(
        "UPDATE course_equivalence_items SET course_name = ? WHERE course_name = ?",
        (winner, loser),
    )

    cur.execute("DELETE FROM courses WHERE course_name = ?", (loser,))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Execute merges (default: dry-run).")
    args = parser.parse_args()

    if not is_postgresql():
        print("PostgreSQL فقط.")
        return 1

    dry_run = not args.apply

    with get_connection() as conn:
        cur = conn.cursor()
        rows = cur.execute("SELECT course_name FROM courses").fetchall()
        names = [_r[0] if isinstance(_r, (list, tuple)) else _r["course_name"] for _r in rows]

    by_trim: dict[str, list[str]] = defaultdict(list)
    for n in names:
        by_trim[n.strip()].append(n)

    plans: list[tuple[str, str, str, int, int]] = []

    with get_connection() as conn:
        cur = conn.cursor()
        for t, variants in by_trim.items():
            uniq = list(dict.fromkeys(variants))
            if len(uniq) < 2:
                continue
            winner = _pick_winner(cur, uniq, t)
            for v in uniq:
                if v == winner:
                    continue
                g = _cnt(cur, "SELECT COUNT(*) FROM grades WHERE course_name = ?", (v,))
                r = _cnt(cur, "SELECT COUNT(*) FROM registrations WHERE course_name = ?", (v,))
                plans.append((t, winner, v, g, r))

    if not plans:
        print("لا توجد مجموعات مكررة (نفس الاسم بعد trim) تحتاج دمجاً.")
        return 0

    print("=== خطة الدمج (الفائز = الأقوى في grades ثم registrations) ===")
    for t, winner, loser, g, r in plans:
        print(f"  trim=«{t}» | يبقى: «{winner}» | يُدمج/يُحذف: «{loser}» (grades={g}, registrations={r})")

    if dry_run:
        print("\nمعاينة فقط. للتنفيذ: python scripts/merge_duplicate_courses_by_grades.py --apply")
        return 0

    with get_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute("BEGIN")
            for t, winner, loser, _g, _r in plans:
                _merge_one(cur, winner, loser)
            cur.execute(
                """
                DELETE FROM prereqs p1
                WHERE EXISTS (
                    SELECT 1 FROM prereqs p2
                    WHERE p2.course_name = p1.course_name
                      AND p2.required_course_name = p1.required_course_name
                      AND p2.id < p1.id
                )
                """
            )
            cur.execute("COMMIT")
        except Exception as e:
            try:
                cur.execute("ROLLBACK")
            except Exception:
                pass
            print("فشل التنفيذ:", e)
            return 1

    print("\nتم الدمج بنجاح.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
