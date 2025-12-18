import os
import sqlite3
import io
import pandas as pd
import shutil
import tempfile
from flask import send_file, render_template, jsonify
from datetime import datetime

# حاول استيراد pdfkit بشكل اختياري
try:
    import pdfkit
except Exception:
    pdfkit = None

# خزن ملف قاعدة البيانات في مجلد مركزي داخل backend/database
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'database'))
DB_FILE = os.path.join(BASE_DIR, "mechanical.db")
SEMESTER_LABEL = "خريف 25-26"

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
    'grade_audit', 'attendance_records'
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
                            student_name TEXT
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
                ]
                for idx in indexes:
                    try:
                        cur.execute(idx)
                    except Exception:
                        # تجاهل الأخطاء إذا كان الفهرس موجوداً بالفعل
                        pass
                
                conn.commit()

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
