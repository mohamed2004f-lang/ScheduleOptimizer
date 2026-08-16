"""إعداد اتصال قاعدة البيانات وكشف لهجة التشغيل."""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

try:
    from sqlalchemy.engine.url import make_url
except ImportError:  # pragma: no cover
    make_url = None  # type: ignore[assignment]

logger = logging.getLogger("backend.database")

# جذر المشروع (ScheduleOptimizer): backend/database/database.py -> .. -> ..
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# تحميل config — PostgreSQL للتشغيل؛ SQLite في الذاكرة للاختبارات فقط (conftest)
try:
    from config import DATABASE_URL, PG_POOL_MIN_SIZE, PG_POOL_MAX_SIZE
except ImportError:
    DATABASE_URL = os.environ.get("DATABASE_URL") or ""
    PG_POOL_MIN_SIZE = int(os.environ.get("PG_POOL_MIN_SIZE", "2"))
    PG_POOL_MAX_SIZE = int(os.environ.get("PG_POOL_MAX_SIZE", "10"))


def _sqlite_db_file_path() -> str:
    """مسار SQLite للاختبارات فقط (DATABASE_URL=sqlite://…)."""
    if make_url is None:
        return ":memory:"
    try:
        u = make_url(DATABASE_URL)
    except Exception:
        return ":memory:"
    if u.get_backend_name() != "sqlite":
        return ""
    db = (u.database or "").strip()
    if not db or db == ":memory:":
        return ":memory:"
    p = Path(db)
    if not p.is_absolute():
        p = (PROJECT_ROOT / p).resolve()
    return str(p)


DB_FILE = _sqlite_db_file_path()


def require_postgres_url(url: str) -> str:
    """ارفض عناوين SQLite وأي شيء غير PostgreSQL (Alembic والتشغيل)."""
    low = (url or "").strip().lower()
    if not (low.startswith("postgresql://") or low.startswith("postgresql+")):
        raise RuntimeError(
            "Alembic يتطلب DATABASE_URL لـ PostgreSQL "
            "(postgresql:// أو postgresql+psycopg://). SQLite غير مدعوم."
        )
    return url


def is_postgresql() -> bool:
    """True إذا كان ``DATABASE_URL`` يشير إلى PostgreSQL (تشغيل التطبيق على Postgres)."""
    if make_url is None:
        return False
    try:
        return make_url(DATABASE_URL).get_backend_name() == "postgresql"
    except Exception:
        return False


def _in_pytest() -> bool:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return True
    return "pytest" in sys.modules


def allow_ensure_tables() -> bool:
    v = (os.environ.get("ALLOW_ENSURE_TABLES") or "").strip().lower()
    return v in ("1", "true", "yes", "on")


def _pg_conninfo() -> str:
    """سلسلة اتصال libpq/psycopg من عنوان SQLAlchemy."""
    u = make_url(DATABASE_URL)
    s = u.render_as_string(hide_password=False)
    if "+psycopg" in s:
        return s.replace("postgresql+psycopg", "postgresql", 1)
    return s

