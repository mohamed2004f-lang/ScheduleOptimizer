import os
import sys
import sqlite3
import io
import pandas as pd
import shutil
import tempfile
import logging
from flask import send_file, render_template, jsonify
from datetime import datetime
from contextlib import contextmanager

logger = logging.getLogger(__name__)

# حاول استيراد pdfkit بشكل اختياري
try:
    import pdfkit
except Exception:
    pdfkit = None

# استيراد الإعدادات من config.py
try:
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    if root_dir not in sys.path:
        sys.path.insert(0, root_dir)
    from config import DATABASE_PATH
    DB_FILE = DATABASE_PATH
except ImportError:
    # fallback للمسار الافتراضي
    BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'database'))
    DB_FILE = os.path.join(BASE_DIR, "mechanical.db")

# الفصل الدراسي الحالي - يمكن نقله إلى config.py لاحقاً
SEMESTER_LABEL = os.environ.get('CURRENT_SEMESTER', 'خريف 25-26')

# ------------------------------------------------------------------
# تهيئة PDFKIT مركزية (الخيار A)
# عدّل المسار هنا إن كان مختلفاً عن المسار الموجود على جهازك
# ------------------------------------------------------------------
_DEFAULT_WKHTMLTOPDF_PATHS = [
    r"C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe",
    r"C:\Program Files (x86)\wkhtmltopdf\bin\wkhtmltopdf.exe",
    r"C:\Users\BARCODE\Downloads\Programs\wkhtmltox-0.12.6-1.mxe-cross-win64\wkhtmltox\bin\wkhtmltopdf.exe",
    r"C:\Users\BARCODE\Downloads\wkhtmltox-0.12.6-1.mxe-cross-win64\wkhtmltox\bin\wkhtmltopdf.exe",
]

PDFKIT_CONFIG = None
if pdfkit is not None:
    # أفضلية: استخدم wkhtmltopdf الموجود في PATH أولاً
    wk = shutil.which("wkhtmltopdf")
    if wk:
        try:
            PDFKIT_CONFIG = pdfkit.configuration(wkhtmltopdf=wk)
        except Exception:
            PDFKIT_CONFIG = None
    # إذا لم يكن في PATH، جرّب قائمة المسارات الافتراضية
    if PDFKIT_CONFIG is None:
        for p in _DEFAULT_WKHTMLTOPDF_PATHS:
            if os.path.isfile(p):
                try:
                    PDFKIT_CONFIG = pdfkit.configuration(wkhtmltopdf=p)
                    break
                except Exception:
                    PDFKIT_CONFIG = None

def get_connection(db_file=DB_FILE):
    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
    except Exception:
        pass
    return conn

def query_all(query, params=(), db_file=DB_FILE):
    with get_connection(db_file) as conn:
        cur = conn.cursor()
        cur.execute(query, params)
        return cur.fetchall()

# قائمة الجداول المسموح بها لمنع SQL Injection
ALLOWED_TABLES = {
    'students', 'courses', 'schedule', 'registrations', 'grades',
    'optimized_schedule', 'conflict_report', 'ignored_conflicts',
    'proposed_moves', 'exams', 'exam_conflicts', 'prereqs',
    'grade_audit', 'attendance_records', 'activity_log',
    'enrollment_plans', 'enrollment_plan_items',
    'registration_requests', 'registration_changes_log',
    'users', 'notifications', 'system_settings',
    'academic_calendar', 'instructors', 'student_supervisor',
    'student_exceptions', 'academic_rules'
}

def table_to_dicts(table_name, db_file=DB_FILE):
    """إرجاع جميع صفوف الجدول كقائمة من القواميس"""
    # التحقق من اسم الجدول لمنع SQL Injection
    if table_name not in ALLOWED_TABLES:
        raise ValueError(f"Invalid table name: {table_name}. Allowed tables: {', '.join(sorted(ALLOWED_TABLES))}")
    
    with get_connection(db_file) as conn:
        cur = conn.cursor()
        rows = cur.execute(f"SELECT * FROM {table_name}").fetchall()
        return [dict(r) for r in rows]

def ensure_tables():
        os.makedirs(os.path.dirname(DB_FILE) or ".", exist_ok=True)
        with get_connection(DB_FILE) as conn:
                cur = conn.cursor()
                create_stmts = [
                        """
                        CREATE TABLE IF NOT EXISTS students (
                            student_id TEXT PRIMARY KEY,
                            student_name TEXT,
                            join_year TEXT
                        )""",
                        """
                        CREATE TABLE IF NOT EXISTS courses (
                            course_name TEXT PRIMARY KEY,
                            course_code TEXT,
                            units INTEGER
                        )""",
                        """
                        CREATE TABLE IF NOT EXISTS schedule (
                            course_name TEXT,
                            day TEXT,
                            time TEXT,
                            room TEXT,
                            instructor TEXT,
                            semester TEXT
                        )""",
                        """
                        CREATE TABLE IF NOT EXISTS registrations (
                            student_id TEXT,
                            course_name TEXT
                        )""",
                        """
                        CREATE TABLE IF NOT EXISTS optimized_schedule (
                            section_id INTEGER, course_name TEXT, day TEXT, time TEXT, room TEXT, instructor TEXT, semester TEXT
                        )""",
                        """
                        CREATE TABLE IF NOT EXISTS conflict_report (
                            student_id TEXT, day TEXT, time TEXT, conflicting_sections TEXT
                        )""",
                        """
                        CREATE TABLE IF NOT EXISTS ignored_conflicts (
                            student_id TEXT, day TEXT, time TEXT, conflicting_sections TEXT,
                            PRIMARY KEY (student_id, day, time, conflicting_sections)
                        )""",
                        """
                        CREATE TABLE IF NOT EXISTS proposed_moves (
                            section_id INTEGER, orig_day TEXT, orig_time TEXT, new_day TEXT, new_time TEXT, move_cost REAL
                        )""",
                        """
                        CREATE TABLE IF NOT EXISTS exams (
                            exam_type TEXT,
                            exam_id INTEGER,
                            course_name TEXT,
                            exam_date TEXT,
                            exam_time TEXT,
                            room TEXT,
                            instructor TEXT
                        )""",
                        """
                        CREATE TABLE IF NOT EXISTS exam_conflicts (
                            exam_type TEXT,
                            student_id TEXT,
                            exam_date TEXT,
                            conflicting_courses TEXT
                        )""",
                        """
                        CREATE TABLE IF NOT EXISTS grades (
                            student_id TEXT,
                            semester TEXT,
                            course_name TEXT,
                            course_code TEXT,
                            units INTEGER,
                            grade REAL,
                            PRIMARY KEY (student_id, semester, course_name)
                        )""",
                        """
                        CREATE TABLE IF NOT EXISTS prereqs (
                            course_name TEXT,
                            required_course_name TEXT,
                            PRIMARY KEY (course_name, required_course_name)
                        )""",
                        """
                        CREATE TABLE IF NOT EXISTS grade_audit (
                            audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                            student_id TEXT,
                            semester TEXT,
                            course_name TEXT,
                            old_grade REAL,
                            new_grade REAL,
                            changed_by TEXT,
                            ts TEXT
                        )""",
                        """
                        CREATE TABLE IF NOT EXISTS attendance_records (
                            student_id TEXT NOT NULL,
                            course_name TEXT NOT NULL,
                            week_number INTEGER NOT NULL,
                            status TEXT,
                            note TEXT,
                            recorded_at TEXT,
                            PRIMARY KEY (student_id, course_name, week_number)
                        )""",
                        """
                        CREATE TABLE IF NOT EXISTS activity_log (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            ts TEXT NOT NULL,
                            actor TEXT,
                            action TEXT NOT NULL,
                            details TEXT
                        )""",
                        """
                        CREATE TABLE IF NOT EXISTS enrollment_plans (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            student_id TEXT NOT NULL,
                            semester TEXT NOT NULL,
                            status TEXT NOT NULL,
                            rejection_reason TEXT,
                            created_at TEXT,
                            updated_at TEXT
                        )""",
                        """
                        CREATE TABLE IF NOT EXISTS enrollment_plan_items (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            plan_id INTEGER NOT NULL,
                            course_name TEXT NOT NULL,
                            FOREIGN KEY (plan_id) REFERENCES enrollment_plans(id) ON DELETE CASCADE
                        )""",
                        """
                        CREATE TABLE IF NOT EXISTS users (
                            username TEXT PRIMARY KEY,
                            password_hash TEXT NOT NULL,
                            role TEXT NOT NULL,
                            student_id TEXT,
                            instructor_id INTEGER,
                            is_supervisor INTEGER NOT NULL DEFAULT 0,
                            is_active INTEGER NOT NULL DEFAULT 1
                        )""",
                        """
                        CREATE TABLE IF NOT EXISTS notifications (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            user TEXT NOT NULL,
                            title TEXT NOT NULL,
                            body TEXT,
                            is_read INTEGER NOT NULL DEFAULT 0,
                            created_at TEXT NOT NULL
                        )""",
                        """
                        CREATE TABLE IF NOT EXISTS system_settings (
                            key TEXT PRIMARY KEY,
                            value TEXT
                        )""",
                        """
                        CREATE TABLE IF NOT EXISTS academic_calendar (
                            academic_year TEXT NOT NULL,
                            term TEXT NOT NULL,
                            item_no INTEGER NOT NULL,
                            title TEXT NOT NULL,
                            event_date TEXT,
                            is_deleted INTEGER NOT NULL DEFAULT 0,
                            updated_at TEXT,
                            PRIMARY KEY (academic_year, term, item_no)
                        )""",
                        """
                        CREATE TABLE IF NOT EXISTS instructors (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            name TEXT NOT NULL,
                            type TEXT NOT NULL DEFAULT 'internal', -- internal | external
                            email TEXT,
                            is_active INTEGER NOT NULL DEFAULT 1
                        )""",
                        """
                        CREATE TABLE IF NOT EXISTS student_supervisor (
                            student_id TEXT NOT NULL,
                            instructor_id INTEGER NOT NULL,
                            PRIMARY KEY (student_id, instructor_id),
                            FOREIGN KEY (student_id) REFERENCES students(student_id) ON DELETE CASCADE,
                            FOREIGN KEY (instructor_id) REFERENCES instructors(id) ON DELETE CASCADE
                        )""",
                        """
                        CREATE TABLE IF NOT EXISTS student_exceptions (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            student_id TEXT NOT NULL,
                            type TEXT NOT NULL, -- extra_chance, etc.
                            note TEXT,
                            created_by TEXT,
                            created_at TEXT,
                            is_active INTEGER NOT NULL DEFAULT 1
                        )""",
                        """
                        CREATE TABLE IF NOT EXISTS academic_rules (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            rule_key TEXT NOT NULL UNIQUE,
                            title TEXT NOT NULL,
                            description TEXT,
                            category TEXT,
                            value_number REAL,
                            value_text TEXT,
                            is_active INTEGER NOT NULL DEFAULT 1
                        )""",
                        """
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
                        )""",
                        """
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
                            FOREIGN KEY (student_id) REFERENCES students(student_id) ON DELETE CASCADE,
                            FOREIGN KEY (course_name) REFERENCES courses(course_name) ON DELETE SET NULL
                        )""",
                ]
                for s in create_stmts:
                        cur.execute(s)
                
                # إضافة فهارس لتحسين الأداء
                indexes = [
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
                    "CREATE INDEX IF NOT EXISTS idx_enrollment_plans_student_sem ON enrollment_plans(student_id, semester)",
                    "CREATE INDEX IF NOT EXISTS idx_enrollment_items_plan ON enrollment_plan_items(plan_id)",
                    "CREATE INDEX IF NOT EXISTS idx_notifications_user_created ON notifications(user, created_at)",
                    "CREATE INDEX IF NOT EXISTS idx_users_role ON users(role)",
                    "CREATE INDEX IF NOT EXISTS idx_academic_calendar_year_term ON academic_calendar(academic_year, term)",
                    "CREATE UNIQUE INDEX IF NOT EXISTS idx_courses_code_unique ON courses(course_code) WHERE COALESCE(course_code,'') <> ''",
                    "CREATE INDEX IF NOT EXISTS idx_student_supervisor_instructor ON student_supervisor(instructor_id)",
                    "CREATE INDEX IF NOT EXISTS idx_reg_requests_status_created ON registration_requests(status, created_at)",
                    "CREATE INDEX IF NOT EXISTS idx_reg_requests_student ON registration_requests(student_id)",
                    "CREATE INDEX IF NOT EXISTS idx_reg_changes_student_time ON registration_changes_log(student_id, action_time)",
                ]
                for idx in indexes:
                    try:
                        cur.execute(idx)
                    except Exception:
                        # تجاهل الأخطاء إذا كان الفهرس موجوداً بالفعل
                        pass

                # ترقيات خفيفة للـ schema (بدون كسر قواعد بيانات قديمة)
                try:
                    cur.execute("ALTER TABLE academic_calendar ADD COLUMN is_deleted INTEGER NOT NULL DEFAULT 0")
                except Exception:
                    pass
                # إضافة أعمدة جديدة إلى الجداول القديمة إن لم تكن موجودة
                try:
                    cur.execute("ALTER TABLE users ADD COLUMN instructor_id INTEGER")
                except Exception:
                    pass
                try:
                    cur.execute("ALTER TABLE users ADD COLUMN is_supervisor INTEGER NOT NULL DEFAULT 0")
                except Exception:
                    pass
                try:
                    cur.execute("ALTER TABLE users ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")
                except Exception:
                    pass
                try:
                    cur.execute("ALTER TABLE students ADD COLUMN join_year TEXT")
                except Exception:
                    pass
                # أعمدة حالة القيد (متوافقة مع النسخة المحسّنة في backend/database/database.py)
                try:
                    cur.execute("ALTER TABLE students ADD COLUMN enrollment_status TEXT DEFAULT 'active'")
                except Exception:
                    pass
                try:
                    cur.execute("ALTER TABLE students ADD COLUMN status_changed_at TEXT")
                except Exception:
                    pass
                try:
                    cur.execute("ALTER TABLE students ADD COLUMN status_reason TEXT")
                except Exception:
                    pass
                try:
                    cur.execute("ALTER TABLE students ADD COLUMN status_changed_term TEXT")
                except Exception:
                    pass
                try:
                    cur.execute("ALTER TABLE students ADD COLUMN status_changed_year TEXT")
                except Exception:
                    pass
                # عمود updated_at قد يُستخدم في بعض التحديثات (مثل تحديث حالة القيد)
                try:
                    cur.execute("ALTER TABLE students ADD COLUMN updated_at TEXT")
                except Exception:
                    pass
                try:
                    cur.execute("ALTER TABLE students ADD COLUMN phone TEXT")
                except Exception:
                    pass
                # نوع المقرر (إجباري/اختياري...) - عمود category في جدول courses
                try:
                    cur.execute("ALTER TABLE courses ADD COLUMN category TEXT NOT NULL DEFAULT 'required'")
                except Exception:
                    pass
                try:
                    cur.execute("ALTER TABLE students ADD COLUMN graduation_plan TEXT DEFAULT ''")
                except Exception:
                    pass
                try:
                    cur.execute("ALTER TABLE students ADD COLUMN join_term TEXT DEFAULT ''")
                except Exception:
                    pass

                conn.commit()

# -----------------------------
# حالة نشر الجدول الدراسي (اعتماد الأدمن)
# -----------------------------
SCHEDULE_PUBLISHED_KEY = "schedule_published_at"
SCHEDULE_UPDATED_KEY = "schedule_updated_at"

def get_schedule_published_at(conn=None, db_file=DB_FILE):
    """يرجع وقت آخر نشر للجدول (ISO نص) أو None إذا لم يُنشر بعد."""
    def _get(c):
        cur = c.cursor()
        cur.execute("SELECT value FROM system_settings WHERE key = ?", (SCHEDULE_PUBLISHED_KEY,))
        row = cur.fetchone()
        return row[0] if row and row[0] else None
    if conn is not None:
        return _get(conn)
    with get_connection(db_file) as c:
        return _get(c)

def set_schedule_published_at(conn=None, db_file=DB_FILE):
    """يضبط وقت نشر الجدول إلى الآن. يرجع الوقت المضبوط (ISO)."""
    from datetime import datetime
    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    def _set(c):
        cur = c.cursor()
        cur.execute(
            "INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?)",
            (SCHEDULE_PUBLISHED_KEY, now)
        )
        c.commit()
        return now
    if conn is not None:
        return _set(conn)
    with get_connection(db_file) as c:
        return _set(c)


def get_schedule_updated_at(conn=None, db_file=DB_FILE):
    """يرجع وقت آخر تعديل للجدول (ISO نص) أو None إذا لم يُسجل تعديل بعد."""
    def _get(c):
        cur = c.cursor()
        cur.execute("SELECT value FROM system_settings WHERE key = ?", (SCHEDULE_UPDATED_KEY,))
        row = cur.fetchone()
        return row[0] if row and row[0] else None
    if conn is not None:
        return _get(conn)
    with get_connection(db_file) as c:
        return _get(c)


def touch_schedule_updated_at(conn=None, db_file=DB_FILE):
    """يضبط وقت آخر تعديل للجدول إلى الآن. يرجع الوقت المضبوط (ISO)."""
    from datetime import datetime
    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    def _set(c):
        cur = c.cursor()
        cur.execute(
            "INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?)",
            (SCHEDULE_UPDATED_KEY, now),
        )
        c.commit()
        return now
    if conn is not None:
        return _set(conn)
    with get_connection(db_file) as c:
        return _set(c)


def get_current_term(conn=None, db_file=DB_FILE):
    """يرجع (term_name, term_year) من system_settings للفصل الحالي. للاستخدام عند الترحيل أو العرض."""
    def _get(c):
        cur = c.cursor()
        name, year = "", ""
        try:
            row = cur.execute("SELECT value FROM system_settings WHERE key = 'current_term_name'").fetchone()
            if row and row[0]:
                name = (row[0] or "").strip()
        except Exception:
            pass
        try:
            row = cur.execute("SELECT value FROM system_settings WHERE key = 'current_term_year'").fetchone()
            if row and row[0]:
                year = (row[0] or "").strip()
        except Exception:
            pass
        return name, year
    if conn is not None:
        return _get(conn)
    with get_connection(db_file) as c:
        return _get(c)


# -----------------------------
# دوال مساعدة للاستيراد/التصدير
# -----------------------------

def df_from_query(query, params=(), db_file=DB_FILE):
    """إرجاع DataFrame من استعلام SQL"""
    with sqlite3.connect(db_file) as conn:
        return pd.read_sql_query(query, conn, params=params)

def excel_response_from_df(df, filename_prefix="export"):
    """إرجاع ملف Excel للتحميل"""
    buf = io.BytesIO()
    now = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    fname = f"{filename_prefix}_{now}.xlsx"
    with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="Sheet1")
    buf.seek(0)
    return send_file(buf,
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                     as_attachment=True,
                     download_name=fname)


def excel_response_from_frames(frames, filename_prefix="export"):
    """
    توليد ملف Excel يحتوي على عدة أوراق.

    frames: Iterable من أزواج (sheet_name, DataFrame).
    """
    if not frames:
        frames = [("Sheet1", pd.DataFrame())]

    buf = io.BytesIO()
    now = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    fname = f"{filename_prefix}_{now}.xlsx"

    def _sanitize_sheet_name(name, used):
        invalid_chars = set('[]:*?/\\')
        cleaned = "".join(("-" if ch in invalid_chars else ch) for ch in (name or "Sheet")).strip()
        if not cleaned:
            cleaned = "Sheet"
        base = cleaned[:31]
        candidate = base
        counter = 1
        while candidate in used:
            suffix = f"_{counter}"
            candidate = (base[:31 - len(suffix)] + suffix) if len(base) + len(suffix) > 31 else base + suffix
            counter += 1
        used.add(candidate)
        return candidate

    with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
        used_names = set()
        for sheet_name, df in frames:
            safe_name = _sanitize_sheet_name(sheet_name, used_names)
            (df if isinstance(df, pd.DataFrame) else pd.DataFrame(df)).to_excel(writer, index=False, sheet_name=safe_name)

    buf.seek(0)
    return send_file(
        buf,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=fname,
    )


def log_activity(action: str, details: str = "", actor: str | None = None):
    """
    تسجيل حدث مبسط في جدول activity_log.
    يستخدم أساساً لتغذية لوحة معلومات 'آخر التعديلات'.
    """
    try:
        ts = datetime.utcnow().isoformat()
        with get_connection(DB_FILE) as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO activity_log (ts, actor, action, details) VALUES (?,?,?,?)",
                (ts, actor or "", action, details or ""),
            )
            conn.commit()
    except Exception:
        # لا نسمح لسقوط التسجيل بكسر بقية العملية
        logger.exception("failed to log activity")


def create_notification(user: str, title: str, body: str = "", created_at: str | None = None):
    """
    إنشاء إشعار بسيط لمستخدم معيّن.
    """
    if not user or not title:
        return
    try:
        ts = created_at or datetime.utcnow().isoformat()
        with get_connection(DB_FILE) as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO notifications (user, title, body, is_read, created_at) VALUES (?,?,?,?,?)",
                (user, title, body or "", 0, ts),
            )
            conn.commit()
    except Exception:
        logger.exception("failed to create notification")

# فحص قابلية إنشاء PDF (pdfkit + wkhtmltopdf)
def _pdf_available():
    if pdfkit is None:
        return False, "pdfkit مكتبة غير مثبتة. ثبّت الحزمة 'pdfkit' باستخدام pip."
    # إذا تم تهيئة PDFKIT_CONFIG نعتبره متاحًا؛ استخدم الخاصية الآمنة
    if PDFKIT_CONFIG is not None:
        wkpath = getattr(PDFKIT_CONFIG, "wkhtmltopdf", None)
        if wkpath:
            return True, {"wkhtmltopdf": wkpath}
    # حاول إيجاد برنامج wkhtmltopdf في PATH
    wkpath = shutil.which("wkhtmltopdf")
    if wkpath:
        return True, {"wkhtmltopdf": wkpath}
    # رسالة واضحة إن لم يوجد
    return False, "البرنامج wkhtmltopdf غير مثبت أو غير موجود في PATH. نزّله وثبتّه من https://wkhtmltopdf.org/ ثم أعد التشغيل."

def pdf_response_from_html(html, filename_prefix="export"):
    """
    إرجاع ملف PDF للتحميل من HTML.
    يولد ملفًا مؤقتًا لأن بعض بيئات Windows لا تدعم كتابة البايت-ستريم مباشرة عبر pdfkit.
    """
    ok, info = _pdf_available()
    if not ok:
        return jsonify({"status": "error", "message": str(info)}), 500

    try:
        # بناء config إن لزم
        config = PDFKIT_CONFIG if PDFKIT_CONFIG is not None else None
        if config is None:
            wkpath = info.get("wkhtmltopdf") if isinstance(info, dict) else shutil.which("wkhtmltopdf")
            if wkpath:
                config = pdfkit.configuration(wkhtmltopdf=wkpath)

        options = {'enable-local-file-access': None, 'encoding': "UTF-8"}

        # أنشئ ملفًا مؤقتًا للـ PDF
        tmpf = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
        tmp_path = tmpf.name
        tmpf.close()

        try:
            # اطلب من pdfkit توليد الملف فعليًا إلى المسار المؤقت
            pdfkit.from_string(html, tmp_path, options=options, configuration=config)
            now = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            fname = f"{filename_prefix}_{now}.pdf"
            return send_file(tmp_path,
                             mimetype="application/pdf",
                             as_attachment=True,
                             download_name=fname)
        finally:
            # نترك الملف كما هو أثناء الإرسال؛ إن رغبت بتنظيف لاحق يمكنك حذف الملفات المؤقتة عبر مهمة خلفية أو cron
            pass

    except Exception as e:
        return jsonify({"status": "error", "message": f"فشل توليد PDF: {str(e)}"}), 500
