import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from models.models import ScheduleRow
from flask import Blueprint, request, jsonify, render_template, session
from backend.core.auth import login_required, role_required
from collections import defaultdict
import sqlite3, pandas as pd
import logging
from .utilities import (
    get_connection,
    table_to_dicts,
    SEMESTER_LABEL,
    DB_FILE,
    df_from_query,
    excel_response_from_df,
    pdf_response_from_html,
    log_activity,
    get_schedule_published_at,
    set_schedule_published_at,
    get_schedule_updated_at,
    touch_schedule_updated_at,
)
from .students import compute_per_student_conflicts

logger = logging.getLogger(__name__)

schedule_bp = Blueprint("schedule", __name__)

# -----------------------------
# عرض/إضافة صفوف الجدول
# -----------------------------

@schedule_bp.route("/rows")
@login_required
def list_schedule_rows():
    with get_connection() as conn:
        cur = conn.cursor()
        try:
            # استخدام JOIN لتحسين الأداء بدلاً من استعلامات منفصلة في loop
            rows = cur.execute("""
                SELECT 
                    s.rowid AS section_id, 
                    s.course_name, 
                    s.day, 
                    s.time, 
                    s.room, 
                    s.instructor, 
                    s.semester,
                    COUNT(DISTINCT r.student_id) AS student_count
                FROM schedule s
                LEFT JOIN registrations r ON s.course_name = r.course_name
                GROUP BY s.rowid, s.course_name, s.day, s.time, s.room, s.instructor, s.semester
                ORDER BY s.rowid
            """).fetchall()
            result = []
            for r in rows:
                result.append({
                    'section_id': r[0],
                    'course_name': r[1],
                    'day': r[2],
                    'time': r[3],
                    'room': r[4],
                    'instructor': r[5],
                    'semester': r[6],
                    'student_count': r[7] or 0
                })
            return jsonify(result)
        except Exception as e:
            logger.error(f"Error in list_schedule_rows: {e}")
            return jsonify([])

# Alias to match frontend calls that use /list_schedule_rows
@schedule_bp.route("/list_schedule_rows")
@login_required
def list_schedule_rows_alias():
    return list_schedule_rows()

@schedule_bp.route("/check_conflicts", methods=["POST"])
@role_required("admin")
def check_conflicts():
    """
    التحقق من التعارضات قبل إضافة مقرر جديد
    Returns: قائمة بالتعارضات المحتملة
    """
    try:
        data = request.get_json(force=True) or {}
        course_name = data.get("course_name", "").strip()
        day = data.get("day", "").strip()
        time = data.get("time", "").strip()
        
        if not course_name or not day or not time:
            return jsonify({
                "status": "error",
                "message": "بيانات غير كاملة"
            }), 400
        
        # محاكاة إضافة المقرر مؤقتاً للتحقق من التعارضات
        with get_connection() as conn:
            # حفظ حالة الجدول الحالي
            cur = conn.cursor()
            
            # إضافة مؤقتة للجدول
            cur.execute("""
                INSERT INTO schedule (course_name, day, time, room, instructor, semester)
                VALUES (?,?,?,?,?,?)
            """, (
                course_name,
                day,
                time,
                data.get("room", ""),
                data.get("instructor", ""),
                data.get("semester", SEMESTER_LABEL)
            ))
            temp_rowid = cur.lastrowid
            
            # حساب التعارضات
            conflicts = compute_per_student_conflicts(conn)
            
            # حذف الإضافة المؤقتة
            cur.execute("DELETE FROM schedule WHERE rowid = ?", (temp_rowid,))
            conn.commit()
            
            # تصفية التعارضات المتعلقة بالمقرر الجديد
            relevant_conflicts = []
            for conflict in conflicts:
                # التحقق إذا كان التعارض يتضمن المقرر الجديد
                conflicting_sections = conflict.get('conflicting_sections', '')
                if course_name in conflicting_sections and day == conflict.get('day') and time == conflict.get('time'):
                    relevant_conflicts.append({
                        'student_id': conflict.get('student_id', ''),
                        'day': conflict.get('day', ''),
                        'time': conflict.get('time', ''),
                        'conflicting_sections': conflicting_sections
                    })
            
            return jsonify({
                "status": "ok",
                "has_conflicts": len(relevant_conflicts) > 0,
                "conflicts": relevant_conflicts,
                "conflict_count": len(relevant_conflicts)
            }), 200
            
    except Exception as e:
        logger.error(f"Error checking conflicts: {e}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": f"خطأ في التحقق من التعارضات: {str(e)}"
        }), 500

# Original add_row (kept)
@schedule_bp.route("/add_row", methods=["POST"])
@role_required("admin")
def add_schedule_row():
    data = request.get_json(force=True)
    required = ["course_name", "day", "time"]
    for k in required:
        if not data.get(k):
            return jsonify({"status": "error", "message": f"{k} مطلوب"}), 400
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO schedule (course_name, day, time, room, instructor, semester)
            VALUES (?,?,?,?,?,?)
        """, (data.get("course_name"), data.get("day"), data.get("time"),
              data.get("room", ""), data.get("instructor", ""), data.get("semester", SEMESTER_LABEL)))
        last = cur.lastrowid
        try:
            touch_schedule_updated_at(conn)
        except Exception:
            pass
        conn.commit()

    try:
        log_activity(
            action="add_schedule_row",
            details=f"section_id={last}, course_name={data.get('course_name')}, day={data.get('day')}, time={data.get('time')}",
        )
    except Exception:
        pass
    # تحديث الجدول النهائي وتقرير التعارضات تلقائياً (خارج with block)
    # Disabled: optimize_with_move_suggestions() is not defined
    # try:
    #     optimize_with_move_suggestions()
    # except Exception as e:
    #     logger.error(f"Error updating optimized schedule after add: {e}")
    return jsonify({"status": "ok", "message": "تم إضافة صف إلى الجدول", "rowid": last}), 200

# Alias to match frontend calls that use /add_schedule_row
@schedule_bp.route("/add_schedule_row", methods=["POST"])
@role_required("admin")
def add_schedule_row_alias():
    return add_schedule_row()


@schedule_bp.route("/delete_schedule_row", methods=["POST"])
@role_required("admin")
def delete_schedule_row():
    """حذف صف من الجدول الدراسي (للأدمن فقط)."""
    data = request.get_json(force=True) or {}
    section_id = data.get("section_id")
    try:
        from backend.core.services import ScheduleService
        res = ScheduleService.delete_schedule_row(int(section_id))
        try:
            with get_connection() as conn:
                touch_schedule_updated_at(conn)
        except Exception:
            pass
        try:
            log_activity(action="delete_schedule_row", details=f"section_id={section_id}")
        except Exception:
            pass
        return jsonify(res), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400


@schedule_bp.route("/update_schedule_row", methods=["POST"])
@role_required("admin")
def update_schedule_row():
    """تحديث صف في الجدول الدراسي (للأدمن فقط)."""
    data = request.get_json(force=True) or {}
    section_id = data.get("section_id")
    if not section_id:
        return jsonify({"status": "error", "message": "section_id مطلوب"}), 400
    fields = {}
    for k in ("course_name", "day", "time", "room", "instructor", "semester"):
        if k in data:
            fields[k] = data.get(k)
    try:
        from backend.core.services import ScheduleService
        res = ScheduleService.update_schedule_row(int(section_id), **fields)
        try:
            with get_connection() as conn:
                touch_schedule_updated_at(conn)
        except Exception:
            pass
        try:
            log_activity(action="update_schedule_row", details=f"section_id={section_id}")
        except Exception:
            pass
        return jsonify(res), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400


@schedule_bp.route("/publish_status")
@login_required
def publish_status():
    """حالة نشر الجدول: هل اعتمد الأدمن الجدول ليظهر للطالب والمشرف."""
    with get_connection() as conn:
        published_at = get_schedule_published_at(conn)
    return jsonify({
        "published": published_at is not None,
        "published_at": published_at,
    })


@schedule_bp.route("/publish", methods=["POST"])
@login_required
@role_required("admin")
def publish_schedule():
    """اعتماد/نشر الجدول من الأدمن الرئيسي. بعدها يراه الطالب والمشرف وتُستمد منه المقررات المتاحة في خطط التسجيل."""
    try:
        with get_connection() as conn:
            published_at = set_schedule_published_at(conn)
            # عند النشر، نضبط أيضاً updated_at حتى لا يظهر تحذير فوراً
            try:
                touch_schedule_updated_at(conn)
            except Exception:
                pass
        log_activity(action="schedule_publish", details=f"published_at={published_at}")
        return jsonify({"status": "ok", "message": "تم اعتماد ونشر الجدول الدراسي", "published_at": published_at}), 200
    except Exception as e:
        logger.error(f"Error publishing schedule: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@schedule_bp.route("/meta")
@login_required
def schedule_meta():
    """معلومات الجدول المعتمد + آخر تعديل، لعرض تنبيه تغيّر الجدول لجميع الأدوار."""
    with get_connection() as conn:
        published_at = get_schedule_published_at(conn)
        updated_at = get_schedule_updated_at(conn)
    changed_since_publish = False
    if published_at and updated_at:
        # مقارنة نصية ISO بصيغة Z تعمل ترتيبياً
        changed_since_publish = updated_at > published_at
    return jsonify({
        "published": published_at is not None,
        "published_at": published_at,
        "updated_at": updated_at,
        "changed_since_publish": changed_since_publish,
    })


@schedule_bp.route("/student_timetable")
@login_required
def student_timetable():
    """
    جدول الطالب الشخصي: يعرض فقط الصفوف المرتبطة بالمقررات المسجل بها.
    الطالب والمشرف يرون الجدول فقط عندما يكون الجدول معتمداً/منشوراً من الأدمن.
    """
    with get_connection() as conn:
        published_at = get_schedule_published_at(conn)
    if published_at is None:
        return jsonify({"rows": [], "published": False})

    user_role = session.get("user_role")
    if user_role == "student":
        sid = session.get("student_id") or session.get("user") or ""
    elif user_role == "supervisor":
        # المشرف يمكنه عرض جدول طلبته المسندين إليه فقط
        sid = (request.args.get("student_id") or "").strip()
        instructor_id = session.get("instructor_id")
        if not instructor_id or not sid:
            return jsonify({"rows": [], "published": True})
        from backend.services.utilities import get_connection
        with get_connection() as conn:
            cur = conn.cursor()
            row = cur.execute(
                "SELECT 1 FROM student_supervisor WHERE student_id = ? AND instructor_id = ? LIMIT 1",
                (sid, instructor_id),
            ).fetchone()
            if not row:
                return jsonify({"rows": [], "published": True})
    else:
        sid = (request.args.get("student_id") or "").strip()
    if not sid:
        return jsonify({"rows": [], "published": True})

    with get_connection() as conn:
        cur = conn.cursor()
        q = """
        SELECT s.rowid AS section_id,
               s.course_name,
               s.day,
               s.time,
               s.room,
               s.instructor,
               s.semester
        FROM schedule s
        JOIN registrations r ON r.course_name = s.course_name
        WHERE r.student_id = ?
        ORDER BY s.day, s.time, s.course_name
        """
        rows = cur.execute(q, (sid,)).fetchall()
        out = []
        for r in rows:
            out.append(
                {
                    "section_id": r[0],
                    "course_name": r[1],
                    "day": r[2],
                    "time": r[3],
                    "room": r[4],
                    "instructor": r[5],
                    "semester": r[6],
                }
            )
    return jsonify({"rows": out, "published": True})
