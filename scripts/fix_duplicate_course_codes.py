"""
إصلاح تكرار course_code في جدول courses (المفتاح الأساسي هو course_name).

المشكلة: فهرس فريد شرطي على course_code يفشل عند وجود نفس الرمز لمقررين مختلفين.
الحل: إبقاء أقدم/أول صف بالرمز الأصلي، وتعديل الباقي إلى رمز فريد (suffix رقمي).

الاستخدام:
  python scripts/fix_duplicate_course_codes.py           # معاينة فقط
  python scripts/fix_duplicate_course_codes.py --apply   # تطبيق التعديلات

آمن: لا يغيّر course_name (مفتاح أجنبي في بقية الجداول).
"""
from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from config import DATABASE_PATH
except ImportError:
    DATABASE_PATH = os.environ.get(
        "DATABASE_PATH", str(ROOT / "backend" / "database" / "mechanical.db")
    )


def _backup_db(db_path: Path) -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    dest = db_path.with_suffix(f".bak_{ts}.db")
    shutil.copy2(db_path, dest)
    return dest


def main() -> int:
    parser = argparse.ArgumentParser(description="Fix duplicate course_code values in SQLite.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply updates (default is dry-run only).",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Skip creating a .bak copy before --apply.",
    )
    args = parser.parse_args()

    db_path = Path(DATABASE_PATH).resolve()
    if not db_path.is_file():
        print("Database file not found:", db_path)
        return 1

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute(
        """
        SELECT course_code, COUNT(*) AS n
        FROM courses
        WHERE COALESCE(TRIM(course_code), '') <> ''
        GROUP BY course_code
        HAVING COUNT(*) > 1
        """
    )
    dup_codes = [r[0] for r in cur.fetchall()]
    if not dup_codes:
        print("No duplicate non-empty course_code values. Nothing to do.")
        conn.close()
        return 0

    print("Found duplicate course_code values:", dup_codes)

    updates: list[tuple[str, str]] = []
    for code in dup_codes:
        cur.execute(
            """
            SELECT course_name, course_code
            FROM courses
            WHERE TRIM(COALESCE(course_code,'')) = TRIM(?)
            ORDER BY course_name
            """,
            (code.strip(),),
        )
        rows = cur.fetchall()
        # الأول يبقى كما هو؛ الثاني (2)، الثالث (3)… مع تجنب التصادم مع أي course_code موجود
        for i, row in enumerate(rows):
            if i == 0:
                continue
            course_name = row["course_name"]
            n = i + 1
            new_code = f"{code.strip()} ({n})"
            attempt = n
            while True:
                cur.execute(
                    "SELECT 1 FROM courses WHERE TRIM(COALESCE(course_code,'')) = ? AND course_name <> ?",
                    (new_code, course_name),
                )
                if cur.fetchone() is None:
                    break
                attempt += 1
                new_code = f"{code.strip()} ({attempt})"
            updates.append((new_code, course_name))
            print(f"  would update: {course_name!r}: {code!r} -> {new_code!r}")

    if not args.apply:
        print("\nDry-run only. Re-run with --apply to write changes.")
        conn.close()
        return 0

    if not args.no_backup:
        bak = _backup_db(db_path)
        print("Backup written to:", bak)

    for new_code, course_name in updates:
        cur.execute(
            "UPDATE courses SET course_code = ? WHERE course_name = ?",
            (new_code, course_name),
        )
    conn.commit()
    print(f"Applied {len(updates)} update(s).")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
