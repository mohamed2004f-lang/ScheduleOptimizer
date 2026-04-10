import os
import sqlite3
import io
import pandas as pd
import shutil
import tempfile
import logging
from flask import send_file, render_template, jsonify
from datetime import datetime
from backend.database.database import (
    DB_FILE,
    ALLOWED_TABLES,
    ensure_tables as ensure_schema,
    get_connection,
    is_postgresql,
    table_to_dicts,
)

logger = logging.getLogger(__name__)

# حاول استيراد pdfkit بشكل اختياري
try:
    import pdfkit
except Exception:
    pdfkit = None

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

def query_all(query, params=(), db_file=DB_FILE):
    with get_connection(db_file) as conn:
        cur = conn.cursor()
        cur.execute(query, params)
        return cur.fetchall()
def ensure_tables():
    """
    توافق خلفي: إبقاء نفس واجهة الاستدعاء القديمة مع توحيد المصدر.
    مصدر تعريف المخطط الآن هو backend.database.database فقط.
    """
    ensure_schema(DB_FILE)

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


def _exam_schedule_published_key(exam_type: str) -> str:
    return f"exam_{exam_type}_schedule_published_at"


def _exam_schedule_updated_key(exam_type: str) -> str:
    return f"exam_{exam_type}_schedule_updated_at"


def get_exam_schedule_published_at(exam_type: str, conn=None, db_file=DB_FILE):
    """وقت آخر اعتماد/نشر لجدول الامتحانات (جزئي أو نهائي)، أو None."""
    if exam_type not in ("midterm", "final"):
        return None
    key = _exam_schedule_published_key(exam_type)

    def _get(c):
        cur = c.cursor()
        cur.execute("SELECT value FROM system_settings WHERE key = ?", (key,))
        row = cur.fetchone()
        return row[0] if row and row[0] else None

    if conn is not None:
        return _get(conn)
    with get_connection(db_file) as c:
        return _get(c)


def set_exam_schedule_published_at(exam_type: str, conn=None, db_file=DB_FILE):
    """يضبط وقت نشر جدول الامتحانات إلى الآن ويعيد القيمة النصية."""
    from datetime import datetime

    if exam_type not in ("midterm", "final"):
        return None
    key = _exam_schedule_published_key(exam_type)
    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    def _set(c):
        cur = c.cursor()
        cur.execute(
            "INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?)",
            (key, now),
        )
        c.commit()
        return now

    if conn is not None:
        return _set(conn)
    with get_connection(db_file) as c:
        return _set(c)


def get_exam_schedule_updated_at(exam_type: str, conn=None, db_file=DB_FILE):
    if exam_type not in ("midterm", "final"):
        return None
    key = _exam_schedule_updated_key(exam_type)

    def _get(c):
        cur = c.cursor()
        cur.execute("SELECT value FROM system_settings WHERE key = ?", (key,))
        row = cur.fetchone()
        return row[0] if row and row[0] else None

    if conn is not None:
        return _get(conn)
    with get_connection(db_file) as c:
        return _get(c)


def touch_exam_schedule_updated_at(exam_type: str, conn=None, db_file=DB_FILE):
    """وقت آخر تعديل على جدول الامتحانات (بعد النشر يُستخدم للتنبيه)."""
    from datetime import datetime

    if exam_type not in ("midterm", "final"):
        return None
    key = _exam_schedule_updated_key(exam_type)
    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    def _set(c):
        cur = c.cursor()
        cur.execute(
            "INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?)",
            (key, now),
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
    if is_postgresql():
        from backend.database.pg_sql import adapt_sqlite_sql_to_postgres, qmarks_to_percent

        q = qmarks_to_percent(adapt_sqlite_sql_to_postgres(query))
        with get_connection(db_file) as conn:
            raw = getattr(conn, "_conn", conn)
            return pd.read_sql_query(q, raw, params=list(params))
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
