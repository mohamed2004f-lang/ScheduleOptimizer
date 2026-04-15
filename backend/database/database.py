"""
إدارة قاعدة البيانات المحسّنة
يتضمن Foreign Keys و Constraints لضمان سلامة البيانات
"""
import os
import re
import sqlite3
import logging
from contextlib import contextmanager
from pathlib import Path

try:
    from sqlalchemy.engine.url import make_url
except ImportError:  # pragma: no cover - يُفضّل تثبيت SQLAlchemy (انظر requirements.txt)
    make_url = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# تحميل config أولاً لضمان قراءة .env (DATABASE_URL / DATABASE_PATH)
try:
    from config import DATABASE_PATH, DATABASE_URL, PG_POOL_MIN_SIZE, PG_POOL_MAX_SIZE
except ImportError:
    BASE_DIR = Path(__file__).parent
    DATABASE_PATH = os.environ.get("DATABASE_PATH", str(BASE_DIR / "mechanical.db"))
    DATABASE_URL = os.environ.get("DATABASE_URL") or f"sqlite:///{Path(DATABASE_PATH).resolve().as_posix()}"
    PG_POOL_MIN_SIZE = int(os.environ.get("PG_POOL_MIN_SIZE", "2"))
    PG_POOL_MAX_SIZE = int(os.environ.get("PG_POOL_MAX_SIZE", "10"))

# جذر المشروع (ScheduleOptimizer): backend/database/database.py -> .. -> ..
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _resolve_config_database_path() -> Path:
    """
    يحل DATABASE_PATH إلى مسار مطلق ثابت نسبةً لجذر المشروع.
    تجنّباً لملفات SQLite مختلفة عند تغيّر مجلد العمل (cwd) بين عمليات التشغيل.
    """
    dp = Path(DATABASE_PATH)
    if not dp.is_absolute():
        return (PROJECT_ROOT / dp).resolve()
    return dp.resolve()


def _sqlite_db_file_path() -> str:
    """مسار ملف SQLite الفعلي لاستخدامه مع sqlite3 (وليس لـ PostgreSQL)."""
    if make_url is None:
        return str(_resolve_config_database_path())
    u = make_url(DATABASE_URL)
    if u.get_backend_name() != "sqlite":
        return str(_resolve_config_database_path())
    if not u.database or u.database == ":memory:":
        return str(_resolve_config_database_path())
    p = Path(u.database)
    if not p.is_absolute():
        p = (PROJECT_ROOT / p).resolve()
    else:
        p = p.resolve()
    return str(p)


DB_FILE = _sqlite_db_file_path()


def is_postgresql() -> bool:
    """True إذا كان ``DATABASE_URL`` يشير إلى PostgreSQL (تشغيل التطبيق على Postgres)."""
    if make_url is None:
        return False
    try:
        return make_url(DATABASE_URL).get_backend_name() == "postgresql"
    except Exception:
        return False


def _pg_conninfo() -> str:
    """سلسلة اتصال libpq/psycopg من عنوان SQLAlchemy."""
    u = make_url(DATABASE_URL)
    s = u.render_as_string(hide_password=False)
    if "+psycopg" in s:
        return s.replace("postgresql+psycopg", "postgresql", 1)
    return s


def fetch_table_columns(conn, table_name: str) -> list[str]:
    """أسماء أعمدة جدول (بديل PRAGMA table_info) لـ SQLite وPostgreSQL."""
    cur = conn.cursor()
    if is_postgresql():
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


def table_exists(conn, name: str) -> bool:
    """بديل sqlite_master لمعرفة وجود جدول."""
    cur = conn.cursor()
    if is_postgresql():
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


def _adapt_pg_execute_sql(sql: str) -> str:
    from backend.database.pg_sql import adapt_sqlite_sql_to_postgres, qmarks_to_percent

    s = adapt_sqlite_sql_to_postgres(sql)
    s = s.replace("excluded.", "EXCLUDED.")
    return qmarks_to_percent(s)


class _PgRowAdapter:
    """
    يجمع بين وصول psycopg dict_row بالاسم وبين فهرسة رقمية مثل sqlite3.Row (row[0]).
    """

    __slots__ = ("_d", "_seq")

    def __init__(self, mapping: dict, column_order: tuple[str, ...]):
        self._d = mapping
        self._seq = tuple(mapping.get(c) for c in column_order)

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._seq[key]
        return self._d[key]

    def __iter__(self):
        return iter(self._seq)

    def __len__(self):
        return len(self._seq)

    def keys(self):
        return self._d.keys()

    def get(self, key, default=None):
        return self._d.get(key, default)


def _wrap_pg_row(row, description) -> object:
    """يحوّل صف dict_row إلى _PgRowAdapter عند الحاجة."""
    if row is None or description is None:
        return row
    if not isinstance(row, dict):
        return row
    colnames = tuple(d[0] for d in description)
    return _PgRowAdapter(row, colnames)


class _PgCursorWrapper:
    """محوّل ? إلى %s و lastrowid لـ psycopg."""

    def __init__(self, raw, parent: "_PgConnectionWrapper"):
        self._c = raw
        self._parent = parent
        self._lastrowid = None
        self.description = None

    @property
    def connection(self):
        """توافق مع sqlite3.Cursor.connection."""
        return self._parent

    def execute(self, sql, params=None):
        self._lastrowid = None
        s_in = sql.strip()
        # محاكاة PRAGMA / sqlite_master لعدم تعديل كل الخدمات يدوياً
        pm = re.match(
            r"^\s*PRAGMA\s+table_info\s*\(\s*['\"]?([a-zA-Z0-9_]+)['\"]?\s*\)\s*$",
            s_in,
            re.I | re.DOTALL,
        )
        if pm:
            tname = pm.group(1)
            q = (
                "SELECT ordinal_position AS cid, column_name AS name, data_type AS type, "
                "0 AS notnull, NULL AS dflt_value, 0 AS pk "
                "FROM information_schema.columns WHERE table_schema = 'public' "
                "AND lower(table_name) = lower(%s) ORDER BY ordinal_position"
            )
            self._c.execute(q, (tname,))
            self.description = self._c.description
            return self

        nrm = re.sub(r"\s+", " ", s_in)
        if re.match(
            r"^SELECT\s+name\s+FROM\s+sqlite_master\s+WHERE\s+type\s*=\s*['\"]table['\"]",
            nrm,
            re.I,
        ):
            self._c.execute(
                "SELECT tablename AS name FROM pg_catalog.pg_tables "
                "WHERE schemaname = 'public' ORDER BY tablename"
            )
            self.description = self._c.description
            return self

        sm = re.match(
            r"^\s*SELECT\s+name\s+FROM\s+sqlite_master\s+WHERE\s+type\s*=\s*['\"]table['\"]\s+AND\s+name\s*=\s*\?\s*$",
            s_in,
            re.I,
        )
        if sm and params:
            self._c.execute(
                "SELECT tablename AS name FROM pg_catalog.pg_tables "
                "WHERE schemaname = 'public' AND lower(tablename) = lower(%s)",
                (params[0],),
            )
            self.description = self._c.description
            return self

        sm1 = re.match(
            r"^\s*SELECT\s+1\s+FROM\s+sqlite_master\s+WHERE\s+type\s*=\s*['\"]table['\"]\s+AND\s+name\s*=\s*['\"]([a-zA-Z0-9_]+)['\"]\s*$",
            s_in,
            re.I,
        )
        if sm1:
            t = sm1.group(1)
            self._c.execute(
                "SELECT 1 AS x FROM pg_catalog.pg_tables "
                "WHERE schemaname = 'public' AND lower(tablename) = lower(%s)",
                (t,),
            )
            self.description = self._c.description
            return self

        q = _adapt_pg_execute_sql(sql)
        if params is None:
            self._c.execute(q)
        else:
            self._c.execute(q, params)
        self.description = self._c.description
        uq = q.lstrip().upper()
        if uq.startswith("INSERT"):
            # PostgreSQL: لا نستدعي lastval() هنا لأن جداول كثيرة لا تستخدم sequence
            # (مثل users بمفتاح نصي)، واستدعاؤه يفشل ويُفسد المعاملة الحالية.
            self._lastrowid = None
        return self

    def executemany(self, sql, seq_of_params):
        self._lastrowid = None
        q = _adapt_pg_execute_sql(sql)
        self._c.executemany(q, seq_of_params)
        self.description = self._c.description
        return self

    def fetchone(self):
        return _wrap_pg_row(self._c.fetchone(), self._c.description)

    def fetchall(self):
        desc = self._c.description
        return [_wrap_pg_row(r, desc) for r in self._c.fetchall()]

    def __iter__(self):
        """مثل sqlite3.Cursor: for row in cur.execute(...)."""
        while True:
            row = self.fetchone()
            if row is None:
                break
            yield row

    @property
    def lastrowid(self):
        return self._lastrowid

    @property
    def rowcount(self):
        """متوافق مع sqlite3: عدد الصفوف المتأثرة بآخر execute / executemany."""
        return getattr(self._c, "rowcount", -1)


class _PgConnectionWrapper:
    """
    Wrapper لاتصال PostgreSQL يوفر توافق مع واجهة sqlite3.Connection.
    يدعم العمل مع connection pool: عند الإغلاق يعيد الاتصال للـ pool بدلاً من إغلاقه فعلياً.
    """
    def __init__(self, raw_conn, pool=None):
        self._conn = raw_conn
        self._pool = pool

    def cursor(self):
        return _PgCursorWrapper(self._conn.cursor(), self)

    def commit(self):
        return self._conn.commit()

    def rollback(self):
        return self._conn.rollback()

    def close(self):
        if self._pool is not None:
            # إعادة الاتصال للـ pool بدلاً من إغلاقه
            self._pool.putconn(self._conn)
        else:
            self._conn.close()

    def execute(self, sql, params=None):
        cur = self.cursor()
        cur.execute(sql, params)
        return cur

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self._conn.commit()
        else:
            self._conn.rollback()
        self.close()
        return False


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

    db_path = db_file or DB_FILE
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


# ============================================
# تعريفات الجداول المحسّنة
# ============================================

TABLES_SCHEMA = {
    'students': """
        CREATE TABLE IF NOT EXISTS students (
            student_id TEXT PRIMARY KEY,
            student_name TEXT NOT NULL DEFAULT '',
            university_number TEXT,
            email TEXT,
            phone TEXT,
            join_year TEXT,
            enrollment_status TEXT NOT NULL DEFAULT 'active',
            status_changed_at TEXT,
            status_reason TEXT,
            status_changed_term TEXT,
            status_changed_year TEXT,
            graduation_plan TEXT DEFAULT '',
            join_term TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """,
    
    'courses': """
        CREATE TABLE IF NOT EXISTS courses (
            course_name TEXT PRIMARY KEY,
            course_code TEXT,
            units INTEGER DEFAULT 0 CHECK (units >= 0),
            grading_mode TEXT NOT NULL DEFAULT 'partial_final' CHECK (grading_mode IN ('partial_final','final_total_only')),
            category TEXT NOT NULL DEFAULT 'required',
            is_archived INTEGER NOT NULL DEFAULT 0 CHECK (is_archived IN (0, 1)),
            description TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """,
    
    'schedule': """
        CREATE TABLE IF NOT EXISTS schedule (
            rowid INTEGER PRIMARY KEY AUTOINCREMENT,
            course_name TEXT NOT NULL,
            day TEXT NOT NULL,
            time TEXT NOT NULL,
            room TEXT DEFAULT '',
            instructor TEXT DEFAULT '',
            instructor_id INTEGER,
            semester TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (course_name) REFERENCES courses(course_name) 
                ON DELETE CASCADE ON UPDATE CASCADE
        )
    """,
    
    'registrations': """
        CREATE TABLE IF NOT EXISTS registrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL,
            course_name TEXT NOT NULL,
            registered_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (student_id, course_name),
            FOREIGN KEY (student_id) REFERENCES students(student_id) 
                ON DELETE CASCADE ON UPDATE CASCADE,
            FOREIGN KEY (course_name) REFERENCES courses(course_name) 
                ON DELETE CASCADE ON UPDATE CASCADE
        )
    """,
    
    'grades': """
        CREATE TABLE IF NOT EXISTS grades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL,
            semester TEXT NOT NULL,
            course_name TEXT NOT NULL,
            course_code TEXT DEFAULT '',
            units INTEGER DEFAULT 0,
            grade REAL CHECK (grade IS NULL OR (grade >= 0 AND grade <= 100)),
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (student_id, semester, course_name),
            FOREIGN KEY (student_id) REFERENCES students(student_id) 
                ON DELETE CASCADE ON UPDATE CASCADE,
            FOREIGN KEY (course_name) REFERENCES courses(course_name) 
                ON DELETE SET NULL ON UPDATE CASCADE
        )
    """,
    
    'prereqs': """
        CREATE TABLE IF NOT EXISTS prereqs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_name TEXT NOT NULL,
            required_course_name TEXT NOT NULL,
            UNIQUE (course_name, required_course_name),
            FOREIGN KEY (course_name) REFERENCES courses(course_name) 
                ON DELETE CASCADE ON UPDATE CASCADE,
            FOREIGN KEY (required_course_name) REFERENCES courses(course_name) 
                ON DELETE CASCADE ON UPDATE CASCADE
        )
    """,
    
    'exams': """
        CREATE TABLE IF NOT EXISTS exams (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exam_type TEXT NOT NULL CHECK (exam_type IN ('midterm', 'final', 'quiz')),
            exam_id INTEGER,
            course_name TEXT NOT NULL,
            exam_date TEXT,
            exam_time TEXT,
            room TEXT DEFAULT '',
            instructor TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (course_name) REFERENCES courses(course_name) 
                ON DELETE CASCADE ON UPDATE CASCADE
        )
    """,
    
    'exam_conflicts': """
        CREATE TABLE IF NOT EXISTS exam_conflicts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exam_type TEXT NOT NULL,
            student_id TEXT NOT NULL,
            exam_date TEXT,
            conflicting_courses TEXT,
            detected_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(student_id) 
                ON DELETE CASCADE ON UPDATE CASCADE
        )
    """,
    
    'conflict_report': """
        CREATE TABLE IF NOT EXISTS conflict_report (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL,
            day TEXT,
            time TEXT,
            conflicting_sections TEXT,
            detected_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(student_id) 
                ON DELETE CASCADE ON UPDATE CASCADE
        )
    """,
    
    'ignored_conflicts': """
        CREATE TABLE IF NOT EXISTS ignored_conflicts (
            student_id TEXT NOT NULL,
            day TEXT NOT NULL,
            time TEXT NOT NULL,
            conflicting_sections TEXT NOT NULL,
            ignored_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (student_id, day, time, conflicting_sections),
            FOREIGN KEY (student_id) REFERENCES students(student_id) 
                ON DELETE CASCADE ON UPDATE CASCADE
        )
    """,
    
    'optimized_schedule': """
        CREATE TABLE IF NOT EXISTS optimized_schedule (
            section_id INTEGER PRIMARY KEY,
            course_name TEXT,
            day TEXT,
            time TEXT,
            room TEXT,
            instructor TEXT,
            semester TEXT
        )
    """,
    
    'schedule_versions': """
        CREATE TABLE IF NOT EXISTS schedule_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            semester TEXT NOT NULL,
            version_no INTEGER NOT NULL DEFAULT 1,
            snapshot_json TEXT DEFAULT '',
            generated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            generated_by TEXT DEFAULT '',
            note TEXT DEFAULT '',
            is_published INTEGER NOT NULL DEFAULT 0,
            UNIQUE (semester, version_no)
        )
    """,

    'schedule_version_events': """
        CREATE TABLE IF NOT EXISTS schedule_version_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            schedule_version_id INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            event_time TEXT DEFAULT CURRENT_TIMESTAMP,
            actor TEXT DEFAULT '',
            details TEXT DEFAULT '',
            FOREIGN KEY (schedule_version_id) REFERENCES schedule_versions(id)
                ON DELETE CASCADE ON UPDATE CASCADE
        )
    """,

    'exam_schedule_versions': """
        CREATE TABLE IF NOT EXISTS exam_schedule_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exam_type TEXT NOT NULL CHECK (exam_type IN ('midterm', 'final')),
            semester TEXT NOT NULL,
            version_no INTEGER NOT NULL DEFAULT 1,
            snapshot_json TEXT DEFAULT '',
            generated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            generated_by TEXT DEFAULT '',
            note TEXT DEFAULT '',
            is_published INTEGER NOT NULL DEFAULT 0,
            UNIQUE (exam_type, semester, version_no)
        )
    """,

    'exam_schedule_version_events': """
        CREATE TABLE IF NOT EXISTS exam_schedule_version_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exam_schedule_version_id INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            event_time TEXT DEFAULT CURRENT_TIMESTAMP,
            actor TEXT DEFAULT '',
            details TEXT DEFAULT '',
            FOREIGN KEY (exam_schedule_version_id) REFERENCES exam_schedule_versions(id)
                ON DELETE CASCADE ON UPDATE CASCADE
        )
    """,
    
    'proposed_moves': """
        CREATE TABLE IF NOT EXISTS proposed_moves (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            section_id INTEGER,
            orig_day TEXT,
            orig_time TEXT,
            new_day TEXT,
            new_time TEXT,
            move_cost REAL
        )
    """,
    
    'grade_audit': """
        CREATE TABLE IF NOT EXISTS grade_audit (
            audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL,
            semester TEXT,
            course_name TEXT,
            old_grade REAL,
            new_grade REAL,
            changed_by TEXT DEFAULT 'system',
            ts TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(student_id) 
                ON DELETE CASCADE ON UPDATE CASCADE
        )
    """,
    
    'attendance_records': """
        CREATE TABLE IF NOT EXISTS attendance_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL,
            course_name TEXT NOT NULL,
            week_number INTEGER NOT NULL,
            status TEXT CHECK (status IN ('present', 'absent', 'late', 'excused')),
            note TEXT,
            recorded_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (student_id, course_name, week_number),
            FOREIGN KEY (student_id) REFERENCES students(student_id) 
                ON DELETE CASCADE ON UPDATE CASCADE,
            FOREIGN KEY (course_name) REFERENCES courses(course_name) 
                ON DELETE CASCADE ON UPDATE CASCADE
        )
    """,
    
    'registration_changes_log': """
        CREATE TABLE IF NOT EXISTS registration_changes_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL,
            student_name TEXT DEFAULT '',
            term TEXT DEFAULT '',
            course_name TEXT NOT NULL,
            course_code TEXT DEFAULT '',
            units INTEGER DEFAULT 0,
            action TEXT NOT NULL CHECK (action IN ('add','drop','change')),
            action_phase TEXT DEFAULT '',
            action_time TEXT DEFAULT CURRENT_TIMESTAMP,
            performed_by TEXT DEFAULT '',
            reason TEXT,
            notes TEXT,
            prev_state TEXT,
            new_state TEXT,
            FOREIGN KEY (student_id) REFERENCES students(student_id)
                ON DELETE CASCADE ON UPDATE CASCADE,
            FOREIGN KEY (course_name) REFERENCES courses(course_name)
                ON DELETE SET NULL ON UPDATE CASCADE
        )
    """
    ,
    'registration_signatures': """
        CREATE TABLE IF NOT EXISTS registration_signatures (
            student_id TEXT NOT NULL,
            term TEXT NOT NULL,
            student_signed INTEGER NOT NULL DEFAULT 0,
            signed_at TEXT,
            signature_note TEXT,
            form_file_id INTEGER,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_by TEXT DEFAULT '',
            PRIMARY KEY (student_id, term),
            FOREIGN KEY (student_id) REFERENCES students(student_id)
                ON DELETE CASCADE ON UPDATE CASCADE
        )
    """,

    'registration_form_files': """
        CREATE TABLE IF NOT EXISTS registration_form_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL,
            term TEXT NOT NULL,
            original_name TEXT DEFAULT '',
            stored_path TEXT NOT NULL,
            mime_type TEXT DEFAULT '',
            file_size INTEGER DEFAULT 0,
            sha256 TEXT DEFAULT '',
            uploaded_by TEXT DEFAULT '',
            uploaded_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(student_id)
                ON DELETE CASCADE ON UPDATE CASCADE
        )
    """,

    'registration_signature_events': """
        CREATE TABLE IF NOT EXISTS registration_signature_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL,
            term TEXT NOT NULL,
            form_version_id INTEGER,
            form_version_no INTEGER DEFAULT 0,
            student_signed INTEGER NOT NULL DEFAULT 0,
            signed_at TEXT,
            signature_note TEXT,
            form_file_id INTEGER,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_by TEXT DEFAULT '',
            UNIQUE(student_id, term, form_version_id),
            FOREIGN KEY (student_id) REFERENCES students(student_id)
                ON DELETE CASCADE ON UPDATE CASCADE
        )
    """,

    'registration_form_versions': """
        CREATE TABLE IF NOT EXISTS registration_form_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL,
            semester TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'actual',
            version_no INTEGER NOT NULL DEFAULT 1,
            snapshot_json TEXT DEFAULT '',
            generated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            generated_by TEXT DEFAULT '',
            UNIQUE(student_id, semester, source, version_no),
            FOREIGN KEY (student_id) REFERENCES students(student_id)
                ON DELETE CASCADE ON UPDATE CASCADE
        )
    """,

    'activity_log': """
        CREATE TABLE IF NOT EXISTS activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            actor TEXT,
            action TEXT NOT NULL,
            details TEXT
        )
    """,

    'enrollment_plans': """
        CREATE TABLE IF NOT EXISTS enrollment_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL,
            semester TEXT NOT NULL,
            status TEXT NOT NULL,
            rejection_reason TEXT,
            created_at TEXT,
            updated_at TEXT,
            prereq_validation_json TEXT,
            prereq_ack_by_student INTEGER NOT NULL DEFAULT 0,
            prereq_ack_reason TEXT DEFAULT '',
            FOREIGN KEY (student_id) REFERENCES students(student_id) ON DELETE CASCADE
        )
    """,

    'enrollment_plan_items': """
        CREATE TABLE IF NOT EXISTS enrollment_plan_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_id INTEGER NOT NULL,
            course_name TEXT NOT NULL,
            FOREIGN KEY (plan_id) REFERENCES enrollment_plans(id) ON DELETE CASCADE
        )
    """,

    'users': """
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL,
            student_id TEXT,
            instructor_id INTEGER,
            is_supervisor INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1
        )
    """,

    'user_invites': """
        CREATE TABLE IF NOT EXISTS user_invites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            email TEXT NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            used_at TEXT
        )
    """,

    'notifications': """
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user TEXT NOT NULL,
            title TEXT NOT NULL,
            body TEXT,
            is_read INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """,

    'system_settings': """
        CREATE TABLE IF NOT EXISTS system_settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """,

    'academic_calendar': """
        CREATE TABLE IF NOT EXISTS academic_calendar (
            academic_year TEXT NOT NULL,
            term TEXT NOT NULL,
            item_no INTEGER NOT NULL,
            title TEXT NOT NULL,
            event_date TEXT,
            is_deleted INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT,
            PRIMARY KEY (academic_year, term, item_no)
        )
    """,

    'instructors': """
        CREATE TABLE IF NOT EXISTS instructors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            type TEXT NOT NULL DEFAULT 'internal',
            email TEXT,
            is_active INTEGER NOT NULL DEFAULT 1
        )
    """,

    'student_supervisor': """
        CREATE TABLE IF NOT EXISTS student_supervisor (
            student_id TEXT NOT NULL,
            instructor_id INTEGER NOT NULL,
            PRIMARY KEY (student_id, instructor_id),
            FOREIGN KEY (student_id) REFERENCES students(student_id) ON DELETE CASCADE,
            FOREIGN KEY (instructor_id) REFERENCES instructors(id) ON DELETE CASCADE
        )
    """,

    'student_exceptions': """
        CREATE TABLE IF NOT EXISTS student_exceptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL,
            type TEXT NOT NULL,
            note TEXT,
            created_by TEXT,
            created_at TEXT,
            is_active INTEGER NOT NULL DEFAULT 1
        )
    """,

    'academic_rules': """
        CREATE TABLE IF NOT EXISTS academic_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rule_key TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL,
            description TEXT,
            category TEXT,
            value_number REAL,
            value_text TEXT,
            is_active INTEGER NOT NULL DEFAULT 1
        )
    """,

    'registration_requests': """
        CREATE TABLE IF NOT EXISTS registration_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL,
            term TEXT DEFAULT '',
            course_name TEXT NOT NULL,
            action TEXT NOT NULL CHECK (action IN ('add','drop')),
            status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected','executed')),
            requested_by TEXT DEFAULT '',
            reviewed_by TEXT DEFAULT '',
            request_reason TEXT,
            review_note TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(student_id) ON DELETE CASCADE,
            FOREIGN KEY (course_name) REFERENCES courses(course_name) ON DELETE SET NULL
        )
    """,

    'app_settings': """
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value_json TEXT,
            updated_at TEXT,
            updated_by TEXT
        )
    """,

    'grade_drafts': """
        CREATE TABLE IF NOT EXISTS grade_drafts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            semester TEXT NOT NULL,
            course_name TEXT NOT NULL,
            instructor_id INTEGER NOT NULL,
            grading_mode TEXT NOT NULL DEFAULT 'partial_final' CHECK (grading_mode IN ('partial_final','final_total_only')),
            status TEXT NOT NULL DEFAULT 'Draft' CHECK (status IN ('Draft','Submitted','Approved','Rejected')),
            created_at TEXT,
            updated_at TEXT,
            submitted_at TEXT,
            approved_at TEXT,
            approved_by TEXT,
            note TEXT,
            UNIQUE (semester, course_name, instructor_id)
        )
    """,

    'grade_draft_items': """
        CREATE TABLE IF NOT EXISTS grade_draft_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            draft_id INTEGER NOT NULL,
            student_id TEXT NOT NULL,
            partial REAL CHECK (partial IS NULL OR (partial >= 0 AND partial <= 100)),
            final REAL CHECK (final IS NULL OR (final >= 0 AND final <= 100)),
            total REAL CHECK (total IS NULL OR (total >= 0 AND total <= 100)),
            computed_total REAL CHECK (computed_total IS NULL OR (computed_total >= 0 AND computed_total <= 100)),
            updated_at TEXT,
            UNIQUE (draft_id, student_id),
            FOREIGN KEY (draft_id) REFERENCES grade_drafts(id) ON DELETE CASCADE
        )
    """,

    'faculty_section_axis_status': """
        CREATE TABLE IF NOT EXISTS faculty_section_axis_status (
            section_id INTEGER NOT NULL,
            instructor_id INTEGER NOT NULL,
            axis_key TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'done', 'na')),
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (section_id, instructor_id, axis_key)
        )
    """,

    'faculty_course_plans': """
        CREATE TABLE IF NOT EXISTS faculty_course_plans (
            section_id INTEGER NOT NULL,
            instructor_id INTEGER NOT NULL,
            week_no INTEGER NOT NULL,
            week_topic TEXT DEFAULT '',
            lecture_status TEXT NOT NULL DEFAULT 'planned'
                CHECK (lecture_status IN ('planned', 'done', 'postponed', 'compensated')),
            resources_text TEXT DEFAULT '',
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_by TEXT DEFAULT '',
            PRIMARY KEY (section_id, instructor_id, week_no)
        )
    """,

    'faculty_course_announcements': """
        CREATE TABLE IF NOT EXISTS faculty_course_announcements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            section_id INTEGER NOT NULL,
            instructor_id INTEGER NOT NULL,
            title TEXT DEFAULT '',
            body TEXT NOT NULL,
            announcement_type TEXT NOT NULL DEFAULT 'general'
                CHECK (announcement_type IN ('general', 'postponement', 'makeup', 'extra_lecture')),
            lecture_date TEXT,
            published_to_students INTEGER NOT NULL DEFAULT 1
                CHECK (published_to_students IN (0, 1)),
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            created_by TEXT DEFAULT ''
        )
    """,

    'faculty_course_syllabi': """
        CREATE TABLE IF NOT EXISTS faculty_course_syllabi (
            section_id INTEGER NOT NULL,
            instructor_id INTEGER NOT NULL,
            syllabus_text TEXT DEFAULT '',
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_by TEXT DEFAULT '',
            PRIMARY KEY (section_id, instructor_id)
        )
    """,
}

# ============================================
# الفهارس لتحسين الأداء
# ============================================

INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_registrations_student ON registrations(student_id)",
    "CREATE INDEX IF NOT EXISTS idx_registrations_course ON registrations(course_name)",
    "CREATE INDEX IF NOT EXISTS idx_schedule_course ON schedule(course_name)",
    "CREATE INDEX IF NOT EXISTS idx_schedule_day_time ON schedule(day, time)",
    "CREATE INDEX IF NOT EXISTS idx_schedule_instructor_id ON schedule(instructor_id)",
    "CREATE INDEX IF NOT EXISTS idx_faculty_axis_inst ON faculty_section_axis_status(instructor_id)",
    "CREATE INDEX IF NOT EXISTS idx_faculty_plan_inst_sec ON faculty_course_plans(instructor_id, section_id)",
    "CREATE INDEX IF NOT EXISTS idx_faculty_ann_sec_pub ON faculty_course_announcements(section_id, published_to_students)",
    "CREATE INDEX IF NOT EXISTS idx_faculty_syllabus_inst_sec ON faculty_course_syllabi(instructor_id, section_id)",
    "CREATE INDEX IF NOT EXISTS idx_grades_student_semester ON grades(student_id, semester)",
    "CREATE INDEX IF NOT EXISTS idx_grades_course ON grades(course_name)",
    "CREATE INDEX IF NOT EXISTS idx_conflict_report_student ON conflict_report(student_id)",
    "CREATE INDEX IF NOT EXISTS idx_exams_course ON exams(course_name)",
    "CREATE INDEX IF NOT EXISTS idx_exams_date ON exams(exam_date)",
    "CREATE INDEX IF NOT EXISTS idx_grade_audit_student ON grade_audit(student_id)",
    "CREATE INDEX IF NOT EXISTS idx_attendance_student ON attendance_records(student_id)",
    "CREATE INDEX IF NOT EXISTS idx_attendance_course ON attendance_records(course_name)",
    "CREATE INDEX IF NOT EXISTS idx_enrollment_plans_student_sem ON enrollment_plans(student_id, semester)",
    "CREATE INDEX IF NOT EXISTS idx_enrollment_items_plan ON enrollment_plan_items(plan_id)",
    'CREATE INDEX IF NOT EXISTS idx_notifications_user_created ON notifications("user", created_at)',
    "CREATE INDEX IF NOT EXISTS idx_users_role ON users(role)",
    "CREATE INDEX IF NOT EXISTS idx_academic_calendar_year_term ON academic_calendar(academic_year, term)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_courses_code_unique ON courses(course_code) WHERE course_code IS NOT NULL AND course_code <> ''",
    "CREATE INDEX IF NOT EXISTS idx_student_supervisor_instructor ON student_supervisor(instructor_id)",
    "CREATE INDEX IF NOT EXISTS idx_reg_requests_status_created ON registration_requests(status, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_reg_requests_student ON registration_requests(student_id)",
    "CREATE INDEX IF NOT EXISTS idx_reg_changes_student_time ON registration_changes_log(student_id, action_time)",
]


def _ensure_tables_postgresql() -> None:
    """ترقيات خفيفة على PostgreSQL (إنشاء المخطط الأساسي عبر ``alembic upgrade head``)."""
    pg_alters = [
        "ALTER TABLE students ADD COLUMN IF NOT EXISTS join_year TEXT",
        "ALTER TABLE students ADD COLUMN IF NOT EXISTS university_number TEXT",
        "ALTER TABLE students ADD COLUMN IF NOT EXISTS email TEXT",
        "ALTER TABLE students ADD COLUMN IF NOT EXISTS phone TEXT",
        "ALTER TABLE students ADD COLUMN IF NOT EXISTS updated_at TEXT",
        (
            "ALTER TABLE students ADD COLUMN IF NOT EXISTS enrollment_status TEXT "
            "NOT NULL DEFAULT 'active'"
        ),
        "ALTER TABLE students ADD COLUMN IF NOT EXISTS status_changed_at TEXT",
        "ALTER TABLE students ADD COLUMN IF NOT EXISTS status_reason TEXT",
        "ALTER TABLE students ADD COLUMN IF NOT EXISTS status_changed_term TEXT",
        "ALTER TABLE students ADD COLUMN IF NOT EXISTS status_changed_year TEXT",
        "ALTER TABLE students ADD COLUMN IF NOT EXISTS graduation_plan TEXT DEFAULT ''",
        "ALTER TABLE students ADD COLUMN IF NOT EXISTS join_term TEXT DEFAULT ''",
        "ALTER TABLE courses ADD COLUMN IF NOT EXISTS is_archived INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE academic_calendar ADD COLUMN IF NOT EXISTS is_deleted INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS instructor_id INTEGER",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_supervisor INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active INTEGER NOT NULL DEFAULT 1",
        "ALTER TABLE courses ADD COLUMN IF NOT EXISTS category TEXT NOT NULL DEFAULT 'required'",
        "ALTER TABLE courses ADD COLUMN IF NOT EXISTS grading_mode TEXT NOT NULL DEFAULT 'partial_final'",
        "ALTER TABLE enrollment_plans ADD COLUMN IF NOT EXISTS prereq_validation_json TEXT",
        (
            "ALTER TABLE enrollment_plans ADD COLUMN IF NOT EXISTS prereq_ack_by_student "
            "INTEGER NOT NULL DEFAULT 0"
        ),
        "ALTER TABLE enrollment_plans ADD COLUMN IF NOT EXISTS prereq_ack_reason TEXT DEFAULT ''",
        "ALTER TABLE schedule ADD COLUMN IF NOT EXISTS instructor_id INTEGER",
        # أرقام معرفات طويلة (وطني/داخلي) تتجاوز INTEGER في PostgreSQL
        "ALTER TABLE users ALTER COLUMN instructor_id TYPE BIGINT USING instructor_id::bigint",
    ]
    pg_constraints = [
        (
            "users_student_requires_student_id_chk",
            """
            ALTER TABLE users
            ADD CONSTRAINT users_student_requires_student_id_chk
            CHECK (
                role <> 'student'
                OR (
                    student_id IS NOT NULL
                    AND btrim(student_id) <> ''
                )
            ) NOT VALID
            """,
        ),
        (
            "users_staff_requires_instructor_id_chk",
            """
            ALTER TABLE users
            ADD CONSTRAINT users_staff_requires_instructor_id_chk
            CHECK (
                role NOT IN ('instructor', 'head_of_department')
                OR instructor_id IS NOT NULL
            ) NOT VALID
            """,
        ),
    ]
    enable_lower_username_unique = (os.environ.get("ENABLE_USERS_LOWER_UNIQUE_IDX") or "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    with get_connection() as conn:
        cur = conn.cursor()
        # كل جملة في معاملة منفصلة حتى لا يُلغى تنفيذ الباقي بعد فشل واحد (PostgreSQL يرفض المتابعة في نفس المعاملة)
        for stmt in pg_alters:
            try:
                cur.execute(stmt)
                conn.commit()
            except Exception as e:
                logger.debug("postgresql alter skipped: %s", e)
                try:
                    conn.rollback()
                except Exception:
                    pass
        for idx_stmt in INDEXES:
            try:
                cur.execute(idx_stmt)
                conn.commit()
            except Exception as e:
                logger.warning("Could not create index on PostgreSQL: %s", e)
                try:
                    conn.rollback()
                except Exception:
                    pass
        for constraint_name, ddl in pg_constraints:
            try:
                exists_row = cur.execute(
                    """
                    SELECT 1
                    FROM pg_constraint
                    WHERE conname = %s
                    LIMIT 1
                    """,
                    (constraint_name,),
                ).fetchone()
                if not exists_row:
                    cur.execute(ddl)
                    conn.commit()
            except Exception as e:
                logger.warning("Could not create PostgreSQL constraint %s: %s", constraint_name, e)
                try:
                    conn.rollback()
                except Exception:
                    pass
        if enable_lower_username_unique:
            try:
                cur.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username_lower_unique ON users (lower(username))"
                )
                conn.commit()
            except Exception as e:
                logger.warning("Could not create optional unique lower(username) index: %s", e)
                try:
                    conn.rollback()
                except Exception:
                    pass
        else:
            logger.info("Skipping optional lower(username) unique index (ENABLE_USERS_LOWER_UNIQUE_IDX is off)")
        try:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS faculty_section_axis_status (
                    section_id INTEGER NOT NULL,
                    instructor_id BIGINT NOT NULL,
                    axis_key TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (section_id, instructor_id, axis_key),
                    CONSTRAINT faculty_axis_status_chk CHECK (status IN ('pending', 'done', 'na'))
                )
                """
            )
            conn.commit()
        except Exception as e:
            logger.warning("Could not ensure faculty_section_axis_status on PostgreSQL: %s", e)
            try:
                conn.rollback()
            except Exception:
                pass
        try:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS faculty_course_plans (
                    section_id INTEGER NOT NULL,
                    instructor_id BIGINT NOT NULL,
                    week_no INTEGER NOT NULL,
                    week_topic TEXT DEFAULT '',
                    lecture_status TEXT NOT NULL DEFAULT 'planned',
                    resources_text TEXT DEFAULT '',
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_by TEXT DEFAULT '',
                    PRIMARY KEY (section_id, instructor_id, week_no),
                    CONSTRAINT faculty_course_plans_status_chk
                        CHECK (lecture_status IN ('planned', 'done', 'postponed', 'compensated'))
                )
                """
            )
            conn.commit()
        except Exception as e:
            logger.warning("Could not ensure faculty_course_plans on PostgreSQL: %s", e)
            try:
                conn.rollback()
            except Exception:
                pass
        try:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS faculty_course_announcements (
                    id BIGSERIAL PRIMARY KEY,
                    section_id INTEGER NOT NULL,
                    instructor_id BIGINT NOT NULL,
                    title TEXT DEFAULT '',
                    body TEXT NOT NULL,
                    announcement_type TEXT NOT NULL DEFAULT 'general',
                    lecture_date TEXT,
                    published_to_students INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    created_by TEXT DEFAULT '',
                    CONSTRAINT faculty_course_ann_type_chk
                        CHECK (announcement_type IN ('general', 'postponement', 'makeup', 'extra_lecture')),
                    CONSTRAINT faculty_course_ann_pub_chk
                        CHECK (published_to_students IN (0, 1))
                )
                """
            )
            conn.commit()
        except Exception as e:
            logger.warning("Could not ensure faculty_course_announcements on PostgreSQL: %s", e)
            try:
                conn.rollback()
            except Exception:
                pass
        try:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS faculty_course_syllabi (
                    section_id INTEGER NOT NULL,
                    instructor_id BIGINT NOT NULL,
                    syllabus_text TEXT DEFAULT '',
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_by TEXT DEFAULT '',
                    PRIMARY KEY (section_id, instructor_id)
                )
                """
            )
            conn.commit()
        except Exception as e:
            logger.warning("Could not ensure faculty_course_syllabi on PostgreSQL: %s", e)
            try:
                conn.rollback()
            except Exception:
                pass
    logger.info("PostgreSQL compatibility migrations applied")


def ensure_tables(db_file=None):
    """إنشاء جميع الجداول والفهارس إذا لم تكن موجودة"""
    if is_postgresql():
        _ensure_tables_postgresql()
        return

    db_path = db_file or DB_FILE
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    
    with get_connection(db_path) as conn:
        cur = conn.cursor()
        
        # إنشاء الجداول
        for table_name, create_stmt in TABLES_SCHEMA.items():
            try:
                cur.execute(create_stmt)
                logger.debug(f"Table {table_name} ensured")
            except Exception as e:
                logger.warning(f"Could not create table {table_name}: {e}")

        # ترقيات أعمدة جدول الطلاب لقواعد بيانات قديمة
        try:
            cols = [r[1] for r in cur.execute("PRAGMA table_info(students)").fetchall()]
            migrations = [
                ("join_year", "ALTER TABLE students ADD COLUMN join_year TEXT"),
                ("university_number", "ALTER TABLE students ADD COLUMN university_number TEXT"),
                ("email", "ALTER TABLE students ADD COLUMN email TEXT"),
                ("phone", "ALTER TABLE students ADD COLUMN phone TEXT"),
                ("updated_at", "ALTER TABLE students ADD COLUMN updated_at TEXT"),
                (
                    "enrollment_status",
                    "ALTER TABLE students ADD COLUMN enrollment_status TEXT NOT NULL DEFAULT 'active'",
                ),
                ("status_changed_at", "ALTER TABLE students ADD COLUMN status_changed_at TEXT"),
                ("status_reason", "ALTER TABLE students ADD COLUMN status_reason TEXT"),
                ("status_changed_term", "ALTER TABLE students ADD COLUMN status_changed_term TEXT"),
                ("status_changed_year", "ALTER TABLE students ADD COLUMN status_changed_year TEXT"),
                ("graduation_plan", "ALTER TABLE students ADD COLUMN graduation_plan TEXT DEFAULT ''"),
                ("join_term", "ALTER TABLE students ADD COLUMN join_term TEXT DEFAULT ''"),
            ]
            for col, stmt in migrations:
                if col not in cols:
                    try:
                        cur.execute(stmt)
                    except Exception:
                        pass
        except Exception as e:
            logger.warning(f"Could not migrate students table columns: {e}")

        # إنشاء الفهارس
        for idx_stmt in INDEXES:
            try:
                cur.execute(idx_stmt)
            except Exception as e:
                logger.warning(f"Could not create index: {e}")

        # بقية الترقيات الخفيفة (كانت في utilities.ensure_tables)
        try:
            cols = [r[1] for r in cur.execute("PRAGMA table_info(courses)").fetchall()]
        except Exception:
            cols = []
        if "is_archived" not in cols:
            try:
                cur.execute("ALTER TABLE courses ADD COLUMN is_archived INTEGER NOT NULL DEFAULT 0")
            except Exception:
                pass

        try:
            cur.execute(
                "ALTER TABLE academic_calendar ADD COLUMN is_deleted INTEGER NOT NULL DEFAULT 0"
            )
        except Exception:
            pass

        for stmt in (
            "ALTER TABLE users ADD COLUMN instructor_id INTEGER",
            "ALTER TABLE users ADD COLUMN is_supervisor INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE users ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1",
        ):
            try:
                cur.execute(stmt)
            except Exception:
                pass

        for stmt in (
            "ALTER TABLE courses ADD COLUMN category TEXT NOT NULL DEFAULT 'required'",
            "ALTER TABLE courses ADD COLUMN grading_mode TEXT NOT NULL DEFAULT 'partial_final'",
        ):
            try:
                cur.execute(stmt)
            except Exception:
                pass

        try:
            eco = [r[1] for r in cur.execute("PRAGMA table_info(enrollment_plans)").fetchall()]
        except Exception:
            eco = []
        if "prereq_validation_json" not in eco:
            try:
                cur.execute("ALTER TABLE enrollment_plans ADD COLUMN prereq_validation_json TEXT")
            except Exception:
                pass
        if "prereq_ack_by_student" not in eco:
            try:
                cur.execute(
                    "ALTER TABLE enrollment_plans ADD COLUMN prereq_ack_by_student INTEGER NOT NULL DEFAULT 0"
                )
            except Exception:
                pass
        if "prereq_ack_reason" not in eco:
            try:
                cur.execute(
                    "ALTER TABLE enrollment_plans ADD COLUMN prereq_ack_reason TEXT DEFAULT ''"
                )
            except Exception:
                pass

        try:
            scols = [r[1] for r in cur.execute("PRAGMA table_info(schedule)").fetchall()]
        except Exception:
            scols = []
        if "instructor_id" not in scols:
            try:
                cur.execute("ALTER TABLE schedule ADD COLUMN instructor_id INTEGER")
            except Exception:
                pass

        conn.commit()
        logger.info("Database tables and indexes ensured")


def migrate_to_foreign_keys(db_file=None):
    """
    ترحيل قاعدة البيانات القديمة لدعم Foreign Keys
    هذه الدالة تنشئ جداول جديدة وتنقل البيانات
    """
    if is_postgresql():
        return

    db_path = db_file or DB_FILE
    
    with get_connection(db_path) as conn:
        cur = conn.cursor()
        
        # التحقق من وجود الجداول القديمة
        tables = cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        existing_tables = {t[0] for t in tables}
        
        # إذا كانت الجداول موجودة، نحتاج لترحيل البيانات
        if 'students' in existing_tables:
            logger.info("Existing database detected. Migration may be needed.")
            # يمكن إضافة منطق الترحيل هنا إذا لزم الأمر
        
        conn.commit()


# قائمة الجداول المسموح بها للاستعلامات الديناميكية
ALLOWED_TABLES = set(TABLES_SCHEMA.keys())


def validate_table_name(table_name: str) -> bool:
    """التحقق من صحة اسم الجدول لمنع SQL Injection"""
    return table_name in ALLOWED_TABLES


def table_to_dicts(table_name: str, db_file=None) -> list:
    """إرجاع جميع صفوف الجدول كقائمة من القواميس"""
    if not validate_table_name(table_name):
        raise ValueError(f"Invalid table name: {table_name}")
    
    with get_connection(db_file) as conn:
        cur = conn.cursor()
        rows = cur.execute(f"SELECT * FROM {table_name}").fetchall()
        return [dict(r) for r in rows]
