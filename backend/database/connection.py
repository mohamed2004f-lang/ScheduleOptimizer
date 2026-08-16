"""تجمع الاتصالات وواجهة get_connection / db_transaction."""
from __future__ import annotations

import logging
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from backend.database.db_config import (
    DB_FILE,
    PG_POOL_MAX_SIZE,
    PG_POOL_MIN_SIZE,
    _pg_conninfo,
    is_postgresql,
)
from backend.database.pg_compat import _PgConnectionWrapper

logger = logging.getLogger("backend.database")

# ============================================
# Connection Pool لـ PostgreSQL
# ============================================
_pg_pool = None  # متغير عام يحمل الـ pool


def _get_or_create_pool():
    """
    إنشاء أو إرجاع connection pool لـ PostgreSQL.
    يستخدم psycopg_pool.ConnectionPool مع إعدادات min_size و max_size من config.
    """
    global _pg_pool
    if _pg_pool is not None:
        return _pg_pool

    try:
        from psycopg_pool import ConnectionPool
    except ImportError:
        logger.warning(
            "مكتبة psycopg_pool غير مثبتة. سيتم إنشاء اتصال جديد لكل طلب. "
            "ثبّتها عبر: pip install psycopg_pool"
        )
        return None

    conninfo = _pg_conninfo()
    logger.info(
        "Initializing PostgreSQL connection pool (min=%d, max=%d)",
        PG_POOL_MIN_SIZE,
        PG_POOL_MAX_SIZE,
    )
    _pg_pool = ConnectionPool(
        conninfo=conninfo,
        min_size=PG_POOL_MIN_SIZE,
        max_size=PG_POOL_MAX_SIZE,
        # الاتصالات تستخدم dict_row للتوافق مع بقية الكود
        kwargs={"row_factory": __import__("psycopg.rows", fromlist=["dict_row"]).dict_row},
    )
    return _pg_pool


def close_pool():
    """
    إغلاق connection pool عند إيقاف التطبيق.
    يجب استدعاؤها في teardown أو atexit.
    """
    global _pg_pool
    if _pg_pool is not None:
        logger.info("Closing PostgreSQL connection pool.")
        try:
            _pg_pool.close()
        except Exception as e:
            logger.warning("Error closing pool: %s", e)
        finally:
            _pg_pool = None


def get_connection(db_file=None):
    """
    اتصال قاعدة البيانات: PostgreSQL عبر psycopg (مع pool) أو SQLite كما سابقاً.

    لـ PostgreSQL:
    - يحاول أخذ اتصال من الـ pool أولاً.
    - إذا لم يكن الـ pool متاحاً (مكتبة psycopg_pool غير مثبتة)، ينشئ اتصال جديد مباشرة.
    - _PgConnectionWrapper.__exit__ يعيد الاتصال للـ pool بدلاً من إغلاقه.

    لـ SQLite:
    - يبقى السلوك كما هو (اتصال مباشر بدون pool).
    """
    if is_postgresql():
        import psycopg
        from psycopg.rows import dict_row

        if db_file and Path(db_file).resolve() != Path(DB_FILE).resolve():
            logger.warning("تجاهل db_file مع PostgreSQL: %s", db_file)

        pool = _get_or_create_pool()
        if pool is not None:
            conn = pool.getconn()
            return _PgConnectionWrapper(conn, pool=pool)
        else:
            # Fallback: إنشاء اتصال مباشر بدون pool
            conn = psycopg.connect(_pg_conninfo(), row_factory=dict_row)
            return _PgConnectionWrapper(conn, pool=None)

    if not os.environ.get("PYTEST_CURRENT_TEST"):
        raise RuntimeError(
            "SQLite runtime is disabled. Set DATABASE_URL to PostgreSQL."
        )

    db_path = db_file or DB_FILE or ":memory:"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def db_transaction(db_file=None):
    """
    Context Manager للتعاملات مع قاعدة البيانات
    يضمن commit عند النجاح و rollback عند الفشل
    """
    conn = get_connection(db_file)
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"Database transaction failed: {e}")
        raise
    finally:
        conn.close()
