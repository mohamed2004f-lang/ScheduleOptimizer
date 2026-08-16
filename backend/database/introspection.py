"""استعلام هيكل الجداول (أعمدة، وجود جدول، مفتاح schedule)."""
from __future__ import annotations

from backend.database.db_config import is_postgresql

def sql_notifications_user_col() -> str:
    """اسم عمود المستخدم في جدول notifications (محجوز في PostgreSQL)."""
    return '"user"' if is_postgresql() else "user"


def conn_is_postgresql(conn) -> bool:
    """True إذا كان الاتصال فعلياً PostgreSQL (وليس SQLite في اختبارات الذاكرة)."""
    if not is_postgresql():
        return False
    try:
        import sqlite3

        raw = getattr(conn, "_conn", conn)
        if isinstance(raw, sqlite3.Connection):
            return False
    except Exception:
        pass
    return True


def fetch_table_columns(conn, table_name: str) -> list[str]:
    """أسماء أعمدة جدول (بديل PRAGMA table_info) لـ SQLite وPostgreSQL."""
    cur = conn.cursor()
    if conn_is_postgresql(conn):
        cur.execute(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'public' AND lower(table_name) = lower(%s)
            ORDER BY ordinal_position
            """,
            (table_name,),
        )
        rows = cur.fetchall()
        out = []
        for r in rows:
            if isinstance(r, dict):
                out.append(r.get("column_name") or list(r.values())[0])
            else:
                out.append(r[0])
        return out
    cur.execute(f"PRAGMA table_info({table_name})")
    return [r[1] for r in cur.fetchall()]


def schedule_pk_column(conn) -> str:
    """
    عمود المفتاح الأساسي المفضل لجدول schedule.
    في PostgreSQL يجب أن يكون id موجوداً بشكل صريح.
    """
    try:
        cols = {str(c).strip().lower() for c in fetch_table_columns(conn, "schedule")}
        if "id" in cols:
            return "id"
        if is_postgresql():
            raise RuntimeError(
                "PostgreSQL schema is invalid: schedule.id is missing. "
                "Run: alembic upgrade head"
            )
    except Exception:
        if is_postgresql():
            raise
    return "rowid" if not is_postgresql() else "id"


def table_exists(conn, name: str) -> bool:
    """بديل sqlite_master لمعرفة وجود جدول — يُحكم بالاتصال الفعلي لا بعنوان DATABASE_URL."""
    cur = conn.cursor()
    if conn_is_postgresql(conn):
        cur.execute(
            """
            SELECT 1 FROM pg_catalog.pg_tables
            WHERE schemaname = 'public' AND lower(tablename) = lower(%s)
            """,
            (name,),
        )
        return cur.fetchone() is not None
    cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?", (name,))
    return cur.fetchone() is not None
