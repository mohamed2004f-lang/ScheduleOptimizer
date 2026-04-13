"""
Shared pytest fixtures for ScheduleOptimizer tests.

Provides:
- ``app``: Flask application configured for testing with an in-memory SQLite DB.
- ``client``: Flask test client (no CSRF, TESTING=True).
- ``auth_client``: Pre-authenticated admin test client.
- ``db_conn``: Raw SQLite connection to the in-memory test database.
"""
import os
import sys
import sqlite3
import pytest

# Ensure project root is on sys.path so imports work regardless of cwd.
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# ---------------------------------------------------------------------------
# Set required environment variables *before* importing anything from the app,
# because config.py raises RuntimeError if ADMIN_PASSWORD is missing.
# ---------------------------------------------------------------------------
os.environ.setdefault("ADMIN_PASSWORD", "TestP@ssw0rd!")
os.environ.setdefault("ADMIN_USERNAME", "admin-test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-pytest")
os.environ.setdefault("FLASK_ENV", "testing")
# Force SQLite (no PostgreSQL) for tests.
os.environ["DATABASE_URL"] = "sqlite://"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MINIMAL_TABLES = """
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
);

CREATE TABLE IF NOT EXISTS courses (
    course_name TEXT PRIMARY KEY,
    course_code TEXT,
    units INTEGER DEFAULT 0 CHECK (units >= 0),
    grading_mode TEXT NOT NULL DEFAULT 'partial_final',
    category TEXT NOT NULL DEFAULT 'required',
    is_archived INTEGER NOT NULL DEFAULT 0,
    description TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

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
    UNIQUE (student_id, semester, course_name)
);

CREATE TABLE IF NOT EXISTS users (
    username TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL,
    student_id TEXT,
    instructor_id INTEGER,
    is_supervisor INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS student_exceptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id TEXT NOT NULL,
    type TEXT NOT NULL,
    note TEXT,
    created_by TEXT,
    created_at TEXT,
    is_active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS registrations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id TEXT NOT NULL,
    course_name TEXT NOT NULL,
    registered_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (student_id, course_name)
);

CREATE TABLE IF NOT EXISTS schedule (
    rowid INTEGER PRIMARY KEY AUTOINCREMENT,
    course_name TEXT NOT NULL,
    day TEXT NOT NULL,
    time TEXT NOT NULL,
    room TEXT DEFAULT '',
    instructor TEXT DEFAULT '',
    semester TEXT DEFAULT '',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS system_settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT,
    is_read INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS student_supervisor (
    student_id TEXT NOT NULL,
    instructor_id INTEGER NOT NULL,
    PRIMARY KEY (student_id, instructor_id)
);

CREATE TABLE IF NOT EXISTS instructors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT 'internal',
    email TEXT,
    is_active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS prereqs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_name TEXT NOT NULL,
    required_course_name TEXT NOT NULL,
    UNIQUE (course_name, required_course_name)
);

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
    FOREIGN KEY (student_id) REFERENCES students(student_id),
    FOREIGN KEY (course_name) REFERENCES courses(course_name)
);

CREATE TABLE IF NOT EXISTS registration_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id TEXT NOT NULL,
    term TEXT DEFAULT '',
    course_name TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('add','drop')),
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending','approved','rejected','executed')),
    requested_by TEXT DEFAULT '',
    reviewed_by TEXT DEFAULT '',
    request_reason TEXT,
    review_note TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (student_id) REFERENCES students(student_id),
    FOREIGN KEY (course_name) REFERENCES courses(course_name)
);

CREATE TABLE IF NOT EXISTS activity_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    actor TEXT,
    action TEXT NOT NULL,
    details TEXT
);
"""


def _seed_admin(conn):
    """Insert a test admin user into the users table."""
    # Use werkzeug directly if available, otherwise fallback to the project's hash_password.
    try:
        from werkzeug.security import generate_password_hash
        pw_hash = generate_password_hash("TestP@ssw0rd!")
    except ImportError:
        from backend.core.auth import hash_password
        pw_hash = hash_password("TestP@ssw0rd!")
    conn.execute(
        "INSERT OR IGNORE INTO users (username, password_hash, role) VALUES (?, ?, ?)",
        ("admin-test", pw_hash, "admin"),
    )
    conn.commit()


def _seed_sample_data(conn):
    """Insert minimal sample data for integration tests."""
    cur = conn.cursor()

    # Students
    cur.execute("INSERT OR IGNORE INTO students (student_id, student_name, join_year) VALUES ('S001', 'طالب أول', '1445')")
    cur.execute("INSERT OR IGNORE INTO students (student_id, student_name, join_year) VALUES ('S002', 'طالب ثاني', '1445')")

    # Courses
    cur.execute("INSERT OR IGNORE INTO courses (course_name, course_code, units) VALUES ('رياضيات 1', 'MATH101', 3)")
    cur.execute("INSERT OR IGNORE INTO courses (course_name, course_code, units) VALUES ('فيزياء 1', 'PHYS101', 3)")
    cur.execute("INSERT OR IGNORE INTO courses (course_name, course_code, units) VALUES ('كيمياء 1', 'CHEM101', 2)")

    # Grades
    cur.execute("INSERT OR IGNORE INTO grades (student_id, semester, course_name, course_code, units, grade) VALUES ('S001', 'خريف 44-45', 'رياضيات 1', 'MATH101', 3, 85)")
    cur.execute("INSERT OR IGNORE INTO grades (student_id, semester, course_name, course_code, units, grade) VALUES ('S001', 'خريف 44-45', 'فيزياء 1', 'PHYS101', 3, 70)")
    cur.execute("INSERT OR IGNORE INTO grades (student_id, semester, course_name, course_code, units, grade) VALUES ('S002', 'خريف 44-45', 'رياضيات 1', 'MATH101', 3, 40)")
    cur.execute("INSERT OR IGNORE INTO grades (student_id, semester, course_name, course_code, units, grade) VALUES ('S002', 'ربيع 44-45', 'كيمياء 1', 'CHEM101', 2, 90)")

    conn.commit()


def _seed_student_user(conn):
    """حساب طالب للاختبارات (طلبات التسجيل وغيرها)."""
    try:
        from werkzeug.security import generate_password_hash
        pw_hash = generate_password_hash("TestP@ssw0rd!")
    except ImportError:
        from backend.core.auth import hash_password
        pw_hash = hash_password("TestP@ssw0rd!")
    conn.execute(
        "INSERT OR IGNORE INTO users (username, password_hash, role, student_id) VALUES (?, ?, ?, ?)",
        ("student-s001", pw_hash, "student", "S001"),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Shared in-memory SQLite connection used by the whole test session.
# We monkey-patch ``backend.database.database.get_connection`` so that
# every call returns a wrapper around this shared connection (without
# actually closing it between uses).
# ---------------------------------------------------------------------------

_shared_conn: sqlite3.Connection | None = None


class _TestConnectionWrapper:
    """
    Thin wrapper that behaves like the real SQLite connection context manager
    but does NOT close the underlying shared connection on __exit__.
    Also provides .row_factory passthrough for compatibility.
    """

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    @property
    def row_factory(self):
        return self._conn.row_factory

    @row_factory.setter
    def row_factory(self, val):
        self._conn.row_factory = val

    def cursor(self):
        return self._conn.cursor()

    def execute(self, *a, **kw):
        return self._conn.execute(*a, **kw)

    def executescript(self, *a, **kw):
        return self._conn.executescript(*a, **kw)

    def commit(self):
        return self._conn.commit()

    def rollback(self):
        return self._conn.rollback()

    def close(self):
        # intentionally no-op: keep the shared connection alive
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        # commit on success, rollback on error — but never close
        if args[0] is None:
            self._conn.commit()
        else:
            self._conn.rollback()
        return False


def _patched_get_connection(db_file=None):
    """Return a non-closing wrapper around the shared in-memory connection."""
    return _TestConnectionWrapper(_shared_conn)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session", autouse=True)
def _setup_shared_db():
    """Create the shared in-memory SQLite DB once per test session."""
    global _shared_conn
    _shared_conn = sqlite3.connect(":memory:")
    _shared_conn.row_factory = sqlite3.Row
    _shared_conn.execute("PRAGMA foreign_keys = ON")
    _shared_conn.executescript(_MINIMAL_TABLES)
    _seed_admin(_shared_conn)
    _seed_sample_data(_shared_conn)
    _seed_student_user(_shared_conn)

    # Monkey-patch get_connection everywhere it is imported.
    import backend.database.database as db_mod
    db_mod.get_connection = _patched_get_connection

    # Also patch db_transaction to use our patched get_connection.
    from contextlib import contextmanager as _cm
    @_cm
    def _patched_db_transaction(db_file=None):
        conn = _patched_get_connection(db_file)
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise
    db_mod.db_transaction = _patched_db_transaction

    # Patch in every service module that re-imports get_connection at module level.
    _modules_to_patch = [
        "backend.services.utilities",
        "backend.services.grades",
        "backend.services.performance",
        "backend.services.students",
        "backend.services.courses",
        "backend.services.schedule",
        "backend.services.exams",
        "backend.services.admin",
        "backend.services.enrollment",
        "backend.services.registration_requests",
        "backend.services.notifications",
        "backend.services.users",
        "backend.services.academic_calendar",
        "backend.services.academic_rules",
        "backend.services.instructors",
        "backend.core.monitoring",
        "backend.core.auth",
    ]
    import importlib
    for mod_name in _modules_to_patch:
        try:
            mod = importlib.import_module(mod_name)
            if hasattr(mod, "get_connection"):
                mod.get_connection = _patched_get_connection
        except Exception:
            pass

    yield

    _shared_conn.close()
    _shared_conn = None


@pytest.fixture(scope="session")
def app(_setup_shared_db):
    """Create and configure the Flask application for testing."""
    # Patch *before* importing app module so that ensure_tables() uses our DB.
    import backend.database.database as db_mod
    _orig_ensure = db_mod.ensure_tables
    db_mod.ensure_tables = lambda *a, **kw: None  # no-op; tables already created

    _orig_is_pg = db_mod.is_postgresql
    db_mod.is_postgresql = lambda: False

    from app import app as flask_app

    flask_app.config["TESTING"] = True
    flask_app.config["WTF_CSRF_ENABLED"] = False
    flask_app.config["SERVER_NAME"] = None

    yield flask_app

    # Restore originals (good hygiene).
    db_mod.ensure_tables = _orig_ensure
    db_mod.is_postgresql = _orig_is_pg


@pytest.fixture(scope="session")
def client(app):
    """Flask test client."""
    return app.test_client()


@pytest.fixture(scope="session")
def auth_client(client):
    """
    Flask test client that is already logged in as admin.
    Uses the ``/auth/login`` endpoint.
    """
    resp = client.post(
        "/auth/login",
        json={"username": "admin-test", "password": "TestP@ssw0rd!"},
    )
    assert resp.status_code == 200, f"Login failed: {resp.get_data(as_text=True)}"
    return client


@pytest.fixture
def student_auth_client(app):
    """
    عميل مسجّل كطالب (S001). منفصل عن ``auth_client`` حتى لا تُستبدل جلسة الأدمن المشتركة.
    """
    with app.test_client() as c:
        resp = c.post(
            "/auth/login",
            json={"username": "student-s001", "password": "TestP@ssw0rd!"},
        )
        assert resp.status_code == 200, f"Student login failed: {resp.get_data(as_text=True)}"
        yield c


@pytest.fixture()
def db_conn():
    """Direct access to the shared in-memory SQLite connection for unit tests."""
    return _shared_conn
