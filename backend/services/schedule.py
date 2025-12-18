import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from models.models import ScheduleRow
from flask import Blueprint, request, jsonify, render_template
from collections import defaultdict
import sqlite3, pandas as pd
import logging
from .utilities import get_connection, table_to_dicts, SEMESTER_LABEL, DB_FILE, df_from_query, excel_response_from_df, pdf_response_from_html
from .students import compute_per_student_conflicts

logger = logging.getLogger(__name__)

schedule_bp = Blueprint("schedule", __name__)

# -----------------------------
# عرض/إضافة صفوف الجدول
# -----------------------------

@schedule_bp.route("/rows")
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
def list_schedule_rows_alias():
    return list_schedule_rows()

@schedule_bp.route("/check_conflicts", methods=["POST"])
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
        conn.commit()
    # تحديث الجدول النهائي وتقرير التعارضات تلقائياً (خارج with block)
    # Disabled: optimize_with_move_suggestions() is not defined
    # try:
    #     optimize_with_move_suggestions()
    # except Exception as e:
    #     logger.error(f"Error updating optimized schedule after add: {e}")
    return jsonify({"status": "ok", "message": "تم إضافة صف إلى الجدول", "rowid": last}), 200

# Alias to match frontend calls that use /add_schedule_row
@schedule_bp.route("/add_schedule_row", methods=["POST"])
def add_schedule_row_alias():
    return add_schedule_row()
