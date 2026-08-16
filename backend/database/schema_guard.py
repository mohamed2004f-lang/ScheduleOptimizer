"""حراسة إقلاع التطبيق: Alembic مطلوب؛ ensure_tables للطوارئ/الاختبار."""
from __future__ import annotations

import logging

from backend.database.connection import get_connection
from backend.database.db_config import _in_pytest, allow_ensure_tables, is_postgresql

logger = logging.getLogger("backend.database")

def alembic_revision_present() -> bool:
    """هل طُبِّق Alembic على قاعدة التشغيل (جدول alembic_version)؟"""
    if not is_postgresql():
        return False
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT version_num FROM alembic_version LIMIT 1")
            row = cur.fetchone()
        return row is not None
    except Exception:
        return False


def assert_schema_ready() -> None:
    """
    التشغيل لا يغيّر المخطط. يجب ``alembic upgrade head`` قبل الإقلاع.
    الاختبارات تُتخطى. الطوارئ: ALLOW_ENSURE_TABLES=1.
    """
    if _in_pytest():
        return
    if not is_postgresql():
        raise RuntimeError(
            "التشغيل يتطلب PostgreSQL. عيّن DATABASE_URL ثم نفّذ: alembic upgrade head"
        )
    if alembic_revision_present():
        return
    if allow_ensure_tables():
        logger.warning(
            "alembic_version missing; ALLOW_ENSURE_TABLES=1 applying ensure_tables (emergency)"
        )
        from backend.database.migrations_postgresql import _ensure_tables_postgresql

        _ensure_tables_postgresql()
        return
    raise RuntimeError(
        "لم يُطبَّق مخطط Alembic. نفّذ من مجلد المشروع:\n"
        "  alembic upgrade head\n"
        "أو ALLOW_ENSURE_TABLES=1 للطوارئ فقط (ليس للإنتاج المستمر)."
    )


def ensure_tables(db_file=None):
    """صيانة واختبارات فقط. إقلاع التطبيق يستخدم Alembic وليس هذه الدالة."""
    if is_postgresql():
        from backend.database.migrations_postgresql import _ensure_tables_postgresql

        _ensure_tables_postgresql()
        return
    from backend.database.migrations_sqlite import ensure_sqlite_tables

    ensure_sqlite_tables(db_file)
