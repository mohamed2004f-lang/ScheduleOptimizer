"""
تنظيف مسافات طرفية في course_name و course_code لجدول courses على PostgreSQL.

- course_name هو المفتاح الأساسي؛ تحديثه يجب أن ينتقل للجداول المرجعة عند وجود ON UPDATE CASCADE.
- يُرفض التنفيذ إن كان تقليم الاسم يُنتج تعارضاً (صفّان يصبحان بنفس الاسم، أو الاسم المقلّم موجوداً لمقرر آخر).

الاستخدام:
  python scripts/cleanup_courses_trim.py                    # معاينة فقط (افتراضي)
  python scripts/cleanup_courses_trim.py --apply           # تنفيذ الكل (يرفض إن وُجدت تعارضات)
  python scripts/cleanup_courses_trim.py --apply-safe      # تنفيذ التصحيحات الآمنة فقط (يتجاهل صفوف التعارض)

قبل --apply أو --apply-safe: pg_dump أو نسخة احتياطية، وراجع مخرجات المعاينة.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.database.database import get_connection, is_postgresql  # noqa: E402


def _name(row) -> str:
    return (row[0] if isinstance(row, (list, tuple)) else row["course_name"]) or ""


def _code(row) -> str:
    v = row[1] if isinstance(row, (list, tuple)) else row["course_code"]
    if v is None:
        return ""
    return str(v)


def _plan_name_updates(names: list[str]) -> tuple[list[tuple[str, str]], list[tuple[str, str, str]]]:
    """(قائمة (قديم، جديد))، تعارضات (قديم، جديد_مقترح، سبب)."""
    name_set = set(names)
    trim_groups: dict[str, list[str]] = {}
    for old in names:
        t = old.strip()
        if not t:
            continue
        if old == t:
            continue
        trim_groups.setdefault(t, []).append(old)

    planned: list[tuple[str, str]] = []
    conflicts: list[tuple[str, str, str]] = []

    for t, olds in trim_groups.items():
        if len(olds) > 1:
            for o in olds:
                conflicts.append((o, t, f"عدة صفوف تتطابق بعد التقليم إلى «{t}»: {olds}"))
            continue
        o = olds[0]
        if t in name_set and t != o:
            conflicts.append((o, t, "يوجد بالفعل مقرر باسم مطابق للاسم بعد التقليم"))
            continue
        planned.append((o, t))
    return planned, conflicts


def _plan_code_updates(cur, names_codes: list[tuple[str, str]]) -> tuple[list[tuple[str, str, str]], list[tuple[str, str, str, str]]]:
    """تحديث الرمز لنفس الصف فقط عند عدم تعارض مع مقرر آخر بعد trim."""
    planned: list[tuple[str, str, str]] = []
    conflicts: list[tuple[str, str, str, str]] = []

    for old_name, code in names_codes:
        if not code or code.strip() == code:
            continue
        nc = code.strip()
        if not nc:
            conflicts.append((old_name, code, nc, "رمز فارغ بعد التقليم"))
            continue
        row = cur.execute(
            """
            SELECT course_name FROM courses
            WHERE lower(trim(course_code)) = lower(trim(?))
              AND course_name IS DISTINCT FROM ?
            LIMIT 1
            """,
            (nc, old_name),
        ).fetchone()
        if row:
            other = _name(row)
            conflicts.append((old_name, code, nc, f"الرمز بعد التقليم مستخدم عند «{other}»"))
            continue
        planned.append((old_name, code, nc))
    return planned, conflicts


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Trim leading/trailing whitespace on courses.course_name and course_code (PostgreSQL)."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Run all planned updates in one transaction (aborts if name conflicts exist).",
    )
    parser.add_argument(
        "--apply-safe",
        dest="apply_safe",
        action="store_true",
        help="Run only non-conflicting name/code trims (safe when duplicate spaced/unspaced rows exist).",
    )
    args = parser.parse_args()

    if args.apply and args.apply_safe:
        print("لا تجمع بين --apply و --apply-safe.")
        return 1

    if not is_postgresql():
        print("هذا السكربت مخصص لـ PostgreSQL فقط (DATABASE_URL).")
        return 1

    with get_connection() as conn:
        cur = conn.cursor()
        rows = cur.execute(
            "SELECT course_name, course_code FROM courses ORDER BY course_name"
        ).fetchall()

    names = [_name(r) for r in rows]
    names_codes = [(_name(r), _code(r)) for r in rows]

    planned_name, name_conflicts = _plan_name_updates(names)

    with get_connection() as conn:
        cur = conn.cursor()
        planned_code, code_conflicts = _plan_code_updates(cur, names_codes)

    print("=== معاينة: تعديلات course_name (مفتاح أساسي) ===")
    if not planned_name:
        print("(لا توجد أسماء تحتاج تقليم طرفي)")
    else:
        for old, new in planned_name:
            print(f"  «{old}»  ->  «{new}»")

    if name_conflicts:
        print("\n*** تعارضات أسماء ***")
        for old, new, reason in name_conflicts:
            print(f"  «{old}» -> «{new}»: {reason}")

    print("\n=== معاينة: تعديلات course_code ===")
    if not planned_code:
        print("(لا توجد رموز تحتاج تقليم طرفي ضمن الشروط)")
    else:
        for old_name, oc, nc in planned_code:
            print(f"  «{old_name}»: «{oc}» -> «{nc}»")

    if code_conflicts:
        print("\n*** تعارضات / رفض تعديل رمز ***")
        for old_name, oc, nc, reason in code_conflicts:
            print(f"  «{old_name}» «{oc}» -> «{nc}»: {reason}")

    with get_connection() as conn:
        cur = conn.cursor()
        dup_after_trim = cur.execute(
            """
            SELECT lower(trim(course_code)) AS k, count(*)::int AS n
            FROM courses
            WHERE course_code IS NOT NULL AND trim(course_code) <> ''
            GROUP BY lower(trim(course_code))
            HAVING count(*) > 1
            """
        ).fetchall()
    if dup_after_trim:
        print("\n*** تحذير: في الجدول الحالي أكثر من صف يشتركان بالرمز نفسه بعد trim ***")
        for r in dup_after_trim:
            k = r[0] if isinstance(r, (list, tuple)) else r["k"]
            n = r[1] if isinstance(r, (list, tuple)) else r["n"]
            print(f"  {k!r}: {n} صفوف")

    if name_conflicts and not args.apply_safe:
        print(
            "\nتوجد تعارضات أسماء (غالباً صف مكرّر: بمسافات طرفية + صف «نظيف» بنفس الاسم). "
            "لن يُنفَّذ --apply الكامل حتى تدمج/تحذف المكررات يدوياً."
        )

    if not args.apply and not args.apply_safe:
        print("\nمعاينة فقط. للتنفيذ الكامل: --apply   |   للآمن فقط: --apply-safe")
        return 0

    if args.apply and name_conflicts:
        print("\nرفض --apply بسبب التعارضات. استخدم --apply-safe أو أصلح البيانات.")
        return 1

    if args.apply_safe and not planned_name and not planned_code:
        print("\nلا توجد تحديثات آمنة لتطبيقها.")
        return 0

    with get_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute("BEGIN")
            # أولاً الرموز (لا تغيّر المفتاح)، ثم الأسماء
            for old_name, oc, nc in planned_code:
                cur.execute(
                    """
                    UPDATE courses SET course_code = ?
                    WHERE course_name = ?
                      AND course_code IS NOT DISTINCT FROM ?
                      AND NOT EXISTS (
                        SELECT 1 FROM courses c2
                        WHERE lower(trim(c2.course_code)) = lower(trim(?))
                          AND c2.course_name IS DISTINCT FROM courses.course_name
                      )
                    """,
                    (nc, old_name, oc, nc),
                )
            for old, new in planned_name:
                cur.execute(
                    "UPDATE courses SET course_name = ? WHERE course_name = ?",
                    (new, old),
                )
            cur.execute("COMMIT")
        except Exception as e:
            try:
                cur.execute("ROLLBACK")
            except Exception:
                pass
            print("فشل التنفيذ:", e)
            return 1

    mode = "آمن (--apply-safe)" if args.apply_safe else "كامل (--apply)"
    print(f"\nتم التطبيق بنجاح ({mode}).")
    if name_conflicts and args.apply_safe:
        print("لم تُلمَس صفوف التعارض — راجعها وادمج المكررات يدوياً عند الحاجة.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
