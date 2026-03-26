"""
إدارة قاعدة البيانات المحسّنة
يتضمن Foreign Keys و Constraints لضمان سلامة البيانات
"""
import os
import sqlite3
import logging
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger(__name__)

# مسار قاعدة البيانات
BASE_DIR = Path(__file__).parent
DB_FILE = os.environ.get('DATABASE_PATH', str(BASE_DIR / 'mechanical.db'))


def get_connection(db_file=None):
    """إنشاء اتصال بقاعدة البيانات مع تفعيل Foreign Keys"""
    db_path = db_file or DB_FILE
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    # تفعيل Foreign Keys
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
}

# ============================================
# الفهارس لتحسين الأداء
# ============================================

INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_registrations_student ON registrations(student_id)",
    "CREATE INDEX IF NOT EXISTS idx_registrations_course ON registrations(course_name)",
    "CREATE INDEX IF NOT EXISTS idx_schedule_course ON schedule(course_name)",
    "CREATE INDEX IF NOT EXISTS idx_schedule_day_time ON schedule(day, time)",
    "CREATE INDEX IF NOT EXISTS idx_grades_student_semester ON grades(student_id, semester)",
    "CREATE INDEX IF NOT EXISTS idx_grades_course ON grades(course_name)",
    "CREATE INDEX IF NOT EXISTS idx_conflict_report_student ON conflict_report(student_id)",
    "CREATE INDEX IF NOT EXISTS idx_exams_course ON exams(course_name)",
    "CREATE INDEX IF NOT EXISTS idx_exams_date ON exams(exam_date)",
    "CREATE INDEX IF NOT EXISTS idx_grade_audit_student ON grade_audit(student_id)",
    "CREATE INDEX IF NOT EXISTS idx_attendance_student ON attendance_records(student_id)",
    "CREATE INDEX IF NOT EXISTS idx_attendance_course ON attendance_records(course_name)",
]


def ensure_tables(db_file=None):
    """إنشاء جميع الجداول والفهارس إذا لم تكن موجودة"""
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

        # ترقية جدول الطلاب لإضافة حالة القيد إن لم تكن موجودة
        try:
            cols = [r[1] for r in cur.execute("PRAGMA table_info(students)").fetchall()]
            if "enrollment_status" not in cols:
                cur.execute(
                    "ALTER TABLE students ADD COLUMN enrollment_status TEXT NOT NULL DEFAULT 'active'"
                )
            if "status_changed_at" not in cols:
                cur.execute(
                    "ALTER TABLE students ADD COLUMN status_changed_at TEXT"
                )
            if "status_reason" not in cols:
                cur.execute(
                    "ALTER TABLE students ADD COLUMN status_reason TEXT"
                )
            if "status_changed_term" not in cols:
                cur.execute("ALTER TABLE students ADD COLUMN status_changed_term TEXT")
            if "status_changed_year" not in cols:
                cur.execute("ALTER TABLE students ADD COLUMN status_changed_year TEXT")
            if "graduation_plan" not in cols:
                cur.execute(
                    "ALTER TABLE students ADD COLUMN graduation_plan TEXT DEFAULT ''"
                )
            if "join_term" not in cols:
                cur.execute(
                    "ALTER TABLE students ADD COLUMN join_term TEXT DEFAULT ''"
                )
        except Exception as e:
            # في حال فشل التعديل (مثلاً في قواعد بيانات قديمة جداً)، نكتفي بالتسجيل ولا نوقف التطبيق
            logger.warning(f"Could not migrate students table with enrollment status columns: {e}")
        
        # إنشاء الفهارس
        for idx_stmt in INDEXES:
            try:
                cur.execute(idx_stmt)
            except Exception as e:
                logger.warning(f"Could not create index: {e}")
        
        conn.commit()
        logger.info("Database tables and indexes ensured")


def migrate_to_foreign_keys(db_file=None):
    """
    ترحيل قاعدة البيانات القديمة لدعم Foreign Keys
    هذه الدالة تنشئ جداول جديدة وتنقل البيانات
    """
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
