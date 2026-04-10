"""
نقل بيانات من SQLite (mechanical.db) إلى PostgreSQL بعد تطبيق Alembic على القاعدة الفارغة.

الاستخدام (من جذر المشروع):
  # 1) ضع في .env: DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/schedule_optimizer
  # 2) alembic upgrade head
  # 3) نسخة احتياطية من ملف SQLite
  python scripts/migrate_sqlite_to_postgres.py --dry-run
  python scripts/migrate_sqlite_to_postgres.py --truncate --yes

متغيرات اختيارية:
  SQLITE_MIGRATION_SOURCE  مسار ملف .db المصدر (الافتراضي: DATABASE_PATH من config)
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

# جذر المشروع على path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.database.database import ALLOWED_TABLES  # noqa: E402

try:
    from config import DATABASE_PATH, DATABASE_URL
except ImportError:
    DATABASE_PATH = str(ROOT / "backend" / "database" / "mechanical.db")
    DATABASE_URL = os.environ.get("DATABASE_URL", "")


# ترتيب يلتزم بالاعتماديات (آباء قبل الأبناء)
TABLE_COPY_ORDER: list[str] = [
    "students",
    "courses",
    "instructors",
    "system_settings",
    "app_settings",
    "academic_calendar",
    "academic_rules",
    "activity_log",
    "user_invites",
    "users",
    "notifications",
    "schedule",
    "prereqs",
    "registrations",
    "grades",
    "exams",
    "exam_conflicts",
    "conflict_report",
    "ignored_conflicts",
    "optimized_schedule",
    "proposed_moves",
    "grade_audit",
    "attendance_records",
    "registration_form_files",
    "registration_form_versions",
    "registration_signatures",
    "registration_signature_events",
    "registration_changes_log",
    "enrollment_plans",
    "enrollment_plan_items",
    "student_supervisor",
    "student_exceptions",
    "registration_requests",
    "schedule_versions",
    "schedule_version_events",
    "exam_schedule_versions",
    "exam_schedule_version_events",
    "grade_drafts",
    "grade_draft_items",
]

assert set(TABLE_COPY_ORDER) == ALLOWED_TABLES, (
    f"TABLE_COPY_ORDER يجب أن يطابق ALLOWED_TABLES. فرق: "
    f"{ALLOWED_TABLES.symmetric_difference(set(TABLE_COPY_ORDER))}"
)


def _pg_dsn() -> str:
    u = (DATABASE_URL or "").strip()
    if not u:
        raise SystemExit("DATABASE_URL غير معرّف. عيّنه في .env إلى postgresql+psycopg://...")
    if "postgresql+psycopg" in u:
        u = u.replace("postgresql+psycopg://", "postgresql://", 1)
    elif u.startswith("postgres://"):
        u = "postgresql://" + u[len("postgres://") :]
    if not u.startswith("postgresql://"):
        raise SystemExit("DATABASE_URL يجب أن يشير إلى PostgreSQL لتشغيل هذا السكربت.")
    return u


def _sqlite_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    cur = conn.execute(f"PRAGMA table_info({table})")
    return [str(r[1]) for r in cur.fetchall()]


def _table_exists_sqlite(conn: sqlite3.Connection, table: str) -> bool:
    r = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return r is not None


def _table_exists_pg(pg, table: str) -> bool:
    with pg.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name=%s",
            (table,),
        )
        r = cur.fetchone()
    return r is not None


def _reset_serials(conn, table: str, pk_col: str) -> None:
    """يضبط تسلسل SERIAL بعد إدراج صفوف بمفاتيح صريحة من SQLite."""
    try:
        with conn.cursor() as cur:
            cur.execute(f'SELECT COALESCE(MAX("{pk_col}"), 1) FROM "{table}"')
            mx = cur.fetchone()[0]
            cur.execute(
                "SELECT pg_get_serial_sequence(%s, %s)",
                (table, pk_col),
            )
            row = cur.fetchone()
            seq = row[0] if row else None
            if seq:
                cur.execute("SELECT setval(%s, %s, true)", (seq, int(mx)))
    except Exception:
        pass


def migrate(
    sqlite_path: Path,
    *,
    dry_run: bool,
    truncate: bool,
    skip_confirm: bool,
) -> None:
    if not sqlite_path.is_file():
        raise SystemExit(f"ملف SQLite غير موجود: {sqlite_path}")

    sl = sqlite3.connect(str(sqlite_path))
    sl.row_factory = sqlite3.Row

    if dry_run:
        try:
            dsn = _pg_dsn()
            tail = dsn.split("@", 1)[-1] if "@" in dsn else dsn
        except SystemExit:
            tail = "(لم يُضبط DATABASE_URL لـ Postgres — عرض أعداد SQLite فقط)"
        print("[dry-run] Postgres:", tail)
        print("[dry-run] SQLite:", sqlite_path)
        for t in TABLE_COPY_ORDER:
            if not _table_exists_sqlite(sl, t):
                print(f"  [skip missing] {t}")
                continue
            n = sl.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            print(f"  {t}: {n} rows")
        sl.close()
        return

    import psycopg

    dsn = _pg_dsn()

    if not truncate or not skip_confirm:
        print("للنسخ الفعلي إلى Postgres (بعد alembic upgrade head):")
        print("  python scripts/migrate_sqlite_to_postgres.py --truncate --yes")
        print("للمعاينة فقط:  python scripts/migrate_sqlite_to_postgres.py --dry-run")
        sl.close()
        return

    with psycopg.connect(dsn) as pg:
        try:
            pg.execute("SET session_replication_role = replica")
        except Exception as e:
            print("note: session_replication_role not set (قد تحتاج صلاحية سوبرمستخدم):", e)

        if truncate:
            tbls = ", ".join(f'"{t}"' for t in TABLE_COPY_ORDER)
            pg.execute(f"TRUNCATE {tbls} RESTART IDENTITY CASCADE")

        for table in TABLE_COPY_ORDER:
            if not _table_exists_sqlite(sl, table):
                print(f"skip (missing in SQLite): {table}")
                continue
            if not _table_exists_pg(pg, table):
                print(f"skip (missing in Postgres): {table}")
                continue

            cols = _sqlite_columns(sl, table)
            if not cols:
                continue
            rows = sl.execute(f'SELECT * FROM "{table}"').fetchall()
            if not rows:
                print(f"{table}: 0 rows")
                continue

            col_ident = ", ".join(f'"{c}"' for c in cols)
            placeholders = ", ".join(["%s"] * len(cols))
            sql = f'INSERT INTO "{table}" ({col_ident}) VALUES ({placeholders})'

            data = [tuple(r[c] for c in cols) for r in rows]

            with pg.cursor() as cur:
                cur.executemany(sql, data)
            print(f"{table}: inserted {len(data)} rows")

        try:
            pg.execute("SET session_replication_role = DEFAULT")
        except Exception:
            pass
        pg.commit()

    sl.close()

    with psycopg.connect(dsn) as pg:
        serial_tables = [
            ("schedule", "rowid"),
            ("registrations", "id"),
            ("grades", "id"),
            ("prereqs", "id"),
            ("exams", "id"),
            ("exam_conflicts", "id"),
            ("conflict_report", "id"),
            ("optimized_schedule", "section_id"),
            ("schedule_versions", "id"),
            ("schedule_version_events", "id"),
            ("exam_schedule_versions", "id"),
            ("exam_schedule_version_events", "id"),
            ("proposed_moves", "id"),
            ("grade_audit", "audit_id"),
            ("attendance_records", "id"),
            ("registration_changes_log", "id"),
            ("registration_form_files", "id"),
            ("registration_signature_events", "id"),
            ("registration_form_versions", "id"),
            ("activity_log", "id"),
            ("enrollment_plans", "id"),
            ("enrollment_plan_items", "id"),
            ("instructors", "id"),
            ("student_exceptions", "id"),
            ("academic_rules", "id"),
            ("registration_requests", "id"),
            ("grade_drafts", "id"),
            ("grade_draft_items", "id"),
            ("user_invites", "id"),
            ("notifications", "id"),
        ]
        for tbl, col in serial_tables:
            if not _table_exists_pg(pg, tbl):
                continue
            _reset_serials(pg, tbl, col)
        pg.commit()

    print("Done.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Migrate SQLite mechanical.db to PostgreSQL")
    ap.add_argument(
        "--sqlite",
        type=Path,
        default=Path(os.environ.get("SQLITE_MIGRATION_SOURCE", DATABASE_PATH)).resolve(),
        help="Path to source .db file",
    )
    ap.add_argument("--dry-run", action="store_true", help="Only print row counts")
    ap.add_argument(
        "--truncate",
        action="store_true",
        help="TRUNCATE all app tables on Postgres before copy (destructive)",
    )
    ap.add_argument("-y", "--yes", action="store_true", dest="yes", help="Confirm truncate")
    args = ap.parse_args()
    migrate(args.sqlite, dry_run=args.dry_run, truncate=args.truncate, skip_confirm=args.yes)


if __name__ == "__main__":
    main()
