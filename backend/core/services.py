"""
Service Layer - فصل منطق العمل عن Routes
يوفر واجهة موحدة للتعامل مع البيانات
"""
import logging
from typing import List, Dict, Optional, Any, Tuple
from datetime import datetime
from contextlib import contextmanager

logger = logging.getLogger(__name__)

# استيراد الأدوات المساعدة
try:
    from ..services.utilities import get_connection, DB_FILE, SEMESTER_LABEL
except ImportError:
    from backend.services.utilities import get_connection, DB_FILE, SEMESTER_LABEL

# استيراد الاستثناءات
try:
    from .exceptions import ValidationError, NotFoundError, DatabaseError
except ImportError:
    from backend.core.exceptions import ValidationError, NotFoundError, DatabaseError

# استيراد أدوات التحقق
try:
    from .validators import normalize_student_id, normalize_grade, normalize_units, sanitize_input
except ImportError:
    # fallback functions
    def normalize_student_id(sid):
        if sid is None:
            return ""
        sid_str = str(sid).strip()
        if sid_str.endswith('.0'):
            sid_str = sid_str[:-2]
        return sid_str
    
    def normalize_grade(grade):
        if grade is None or grade == '':
            return None
        try:
            return float(grade)
        except:
            return None
    
    def normalize_units(units):
        if units is None or units == '':
            return 0
        try:
            return max(0, int(units))
        except:
            return 0
    
    def sanitize_input(value, max_length=500):
        if value is None:
            return ""
        return str(value).strip()[:max_length]


# ============================================
# Context Manager للتعاملات
# ============================================

@contextmanager
def db_transaction():
    """Context manager للتعاملات مع قاعدة البيانات"""
    conn = get_connection()
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
# خدمة الطلاب
# ============================================

class StudentService:
    """خدمة إدارة الطلاب"""
    
    @staticmethod
    def _students_columns(cur) -> List[str]:
        """قائمة أعمدة جدول students (للتوافق مع قواعد قديمة بدون أعمدة حالة القيد)."""
        cols = [row[1] for row in cur.execute("PRAGMA table_info(students)").fetchall()]
        return cols

    @staticmethod
    def get_all_students(active_only: bool = False) -> List[Dict]:
        """جلب جميع الطلاب. إذا active_only=True يُرجَع فقط من حالتهم «مسجّل» (لا سحب ملف ولا إيقاف قيد ولا خريج)."""
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                cols = StudentService._students_columns(cur)
                has_status = "enrollment_status" in cols
                has_plan = "graduation_plan" in cols
                if has_status:
                    if active_only:
                        rows = cur.execute("""
                            SELECT 
                                student_id, student_name,
                                COALESCE(enrollment_status, 'active') AS enrollment_status,
                                status_changed_at, status_reason
                            """ + (", COALESCE(graduation_plan, '') AS graduation_plan" if has_plan else "") + """
                            FROM students 
                            WHERE COALESCE(enrollment_status, 'active') = 'active'
                            ORDER BY student_name, student_id
                        """).fetchall()
                    else:
                        rows = cur.execute("""
                            SELECT 
                                student_id, 
                                student_name,
                                COALESCE(enrollment_status, 'active') AS enrollment_status,
                                status_changed_at,
                                status_reason
                            """ + (", COALESCE(graduation_plan, '') AS graduation_plan" if has_plan else "") + """
                            FROM students 
                            ORDER BY student_name, student_id
                        """).fetchall()
                    result: List[Dict[str, Any]] = []
                    for r in rows:
                        row_dict = {
                            "student_id": r["student_id"],
                            "student_name": r["student_name"] or "",
                            "enrollment_status": r["enrollment_status"] or "active",
                            "status_changed_at": r["status_changed_at"],
                            "status_reason": r["status_reason"] or "",
                        }
                        if has_plan:
                            row_dict["graduation_plan"] = (r["graduation_plan"] or "").strip()
                        else:
                            row_dict["graduation_plan"] = ""
                        result.append(row_dict)
                    return result
                # قواعد قديمة بدون أعمدة حالة القيد
                rows = cur.execute("""
                    SELECT student_id, student_name FROM students ORDER BY student_name, student_id
                """).fetchall()
                return [
                    {
                        "student_id": r["student_id"],
                        "student_name": r["student_name"] or "",
                        "enrollment_status": "active",
                        "status_changed_at": None,
                        "status_reason": "",
                        "graduation_plan": "",
                    }
                    for r in rows
                ]
        except Exception as e:
            logger.error(f"Error getting students: {e}")
            raise DatabaseError(f"فشل جلب قائمة الطلاب: {str(e)}")
    
    @staticmethod
    def get_student(student_id: str) -> Optional[Dict]:
        """جلب طالب بالمعرف"""
        sid = normalize_student_id(student_id)
        if not sid:
            raise ValidationError("معرّف الطالب مطلوب")
        
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                cols = StudentService._students_columns(cur)
                has_status = "enrollment_status" in cols
                has_plan = "graduation_plan" in cols
                if has_status:
                    row = cur.execute(
                        """
                        SELECT student_id, student_name,
                               COALESCE(enrollment_status, 'active') AS enrollment_status,
                               status_changed_at, status_reason
                        """ + (", COALESCE(graduation_plan, '') AS graduation_plan" if has_plan else "") + """
                        FROM students WHERE student_id = ?
                        """,
                        (sid,),
                    ).fetchone()
                else:
                    row = cur.execute(
                        "SELECT student_id, student_name FROM students WHERE student_id = ?",
                        (sid,),
                    ).fetchone()
                if row:
                    out = {
                        "student_id": row["student_id"],
                        "student_name": row["student_name"] or "",
                        "enrollment_status": row["enrollment_status"] if has_status else "active",
                        "status_changed_at": row["status_changed_at"] if has_status else None,
                        "status_reason": row["status_reason"] if has_status else "",
                    }
                    if has_plan:
                        out["graduation_plan"] = (row["graduation_plan"] or "").strip()
                    else:
                        out["graduation_plan"] = ""
                    return out
                return None
        except Exception as e:
            logger.error(f"Error getting student {sid}: {e}")
            raise DatabaseError(f"فشل جلب بيانات الطالب: {str(e)}")
    
    @staticmethod
    def add_student(student_id: str, student_name: str = "", graduation_plan: str = "") -> Dict:
        """إضافة طالب جديد أو تحديث بياناته (upsert). خطة التخرج اختيارية: 150، 155، أو فارغ."""
        sid = normalize_student_id(student_id)
        if not sid:
            raise ValidationError("معرّف الطالب مطلوب")
        
        name = sanitize_input(student_name, 200)
        plan = (graduation_plan or "").strip()[:50]
        
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                cols = StudentService._students_columns(cur)
                has_status = "enrollment_status" in cols
                has_plan = "graduation_plan" in cols
                if has_status and has_plan:
                    cur.execute(
                        """
                        INSERT OR REPLACE INTO students (
                            student_id, student_name,
                            enrollment_status, status_changed_at, graduation_plan
                        ) VALUES (
                            ?, ?,
                            COALESCE((SELECT enrollment_status FROM students WHERE student_id = ?), 'active'),
                            COALESCE((SELECT status_changed_at FROM students WHERE student_id = ?), CURRENT_TIMESTAMP),
                            ?
                        )
                        """,
                        (sid, name, sid, sid, plan),
                    )
                elif has_status:
                    cur.execute(
                        """
                        INSERT OR REPLACE INTO students (
                            student_id, student_name,
                            enrollment_status, status_changed_at
                        ) VALUES (
                            ?, ?,
                            COALESCE((SELECT enrollment_status FROM students WHERE student_id = ?), 'active'),
                            COALESCE((SELECT status_changed_at FROM students WHERE student_id = ?), CURRENT_TIMESTAMP)
                        )
                        """,
                        (sid, name, sid, sid),
                    )
                else:
                    cur.execute(
                        "INSERT OR REPLACE INTO students (student_id, student_name) VALUES (?, ?)",
                        (sid, name),
                    )
                conn.commit()
                logger.info(f"Student added/updated: {sid}")
                return {'status': 'ok', 'message': 'تم إضافة الطالب', 'student_id': sid}
        except Exception as e:
            logger.error(f"Error adding student: {e}")
            raise DatabaseError(f"فشل إضافة الطالب: {str(e)}")
    
    @staticmethod
    def update_student(student_id: str, student_name: str, graduation_plan: Optional[str] = None) -> Dict:
        """تحديث بيانات طالب (الاسم و/أو خطة التخرج)."""
        sid = normalize_student_id(student_id)
        if not sid:
            raise ValidationError("معرّف الطالب مطلوب")
        
        name = sanitize_input(student_name, 200)
        
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                cols = StudentService._students_columns(cur)
                has_plan = "graduation_plan" in cols
                if has_plan and graduation_plan is not None:
                    plan = (graduation_plan or "").strip()[:50]
                    cur.execute(
                        "UPDATE students SET student_name = ?, graduation_plan = ?, updated_at = CURRENT_TIMESTAMP WHERE student_id = ?",
                        (name, plan, sid)
                    )
                else:
                    cur.execute(
                        "UPDATE students SET student_name = ?, updated_at = CURRENT_TIMESTAMP WHERE student_id = ?",
                        (name, sid)
                    )
                if cur.rowcount == 0:
                    raise NotFoundError("الطالب غير موجود")
                conn.commit()
                return {'status': 'ok', 'message': 'تم تحديث بيانات الطالب'}
        except NotFoundError:
            raise
        except Exception as e:
            logger.error(f"Error updating student: {e}")
            raise DatabaseError(f"فشل تحديث بيانات الطالب: {str(e)}")

    @staticmethod
    def update_enrollment_status(
        student_id: str,
        status: str,
        changed_at: Optional[str] = None,
        reason: str = "",
        **kwargs,
    ) -> Dict:
        """
        تحديث حالة قيد الطالب (مسجَّل، سحب الملف، موقوف قيده، خريج)
        """
        sid = normalize_student_id(student_id)
        if not sid:
            raise ValidationError("معرّف الطالب مطلوب")

        allowed_statuses = {
            "active": "مسجَّل",
            "withdrawn": "سحب الملف",
            "suspended": "موقوف قيده",
            "graduated": "خريج",
        }
        if status not in allowed_statuses:
            raise ValidationError("حالة القيد غير صحيحة")

        note = sanitize_input(reason, 500)
        ts = changed_at or datetime.utcnow().isoformat()
        phone = (kwargs.get("phone") or "").strip() if kwargs else ""

        try:
            with get_connection() as conn:
                cur = conn.cursor()
                cols = [row[1] for row in cur.execute("PRAGMA table_info(students)").fetchall()]
                # تحديث الهاتف فقط عند التحويل إلى خريج (لظهوره في قائمة الخريجين)
                if "phone" in cols and status == "graduated":
                    cur.execute(
                        """
                        UPDATE students
                        SET enrollment_status = ?,
                            status_changed_at = ?,
                            status_reason = ?,
                            phone = ?,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE student_id = ?
                        """,
                        (status, ts, note, phone, sid),
                    )
                else:
                    cur.execute(
                        """
                        UPDATE students
                        SET enrollment_status = ?,
                            status_changed_at = ?,
                            status_reason = ?,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE student_id = ?
                        """,
                        (status, ts, note, sid),
                    )
                if cur.rowcount == 0:
                    raise NotFoundError("الطالب غير موجود")
                return {
                    "status": "ok",
                    "message": f"تم تحديث حالة القيد إلى «{allowed_statuses[status]}»",
                    "student_id": sid,
                    "enrollment_status": status,
                }
        except NotFoundError:
            raise
        except Exception as e:
            logger.error(f"Error updating enrollment status for {sid}: {e}")
            raise DatabaseError(f"فشل تحديث حالة القيد للطالب: {str(e)}")
    
    @staticmethod
    def delete_student(student_id: str, cascade: bool = True) -> Dict:
        """حذف طالب"""
        sid = normalize_student_id(student_id)
        if not sid:
            raise ValidationError("معرّف الطالب مطلوب")
        
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                
                # حذف البيانات المرتبطة إذا طُلب ذلك
                if cascade:
                    cur.execute("DELETE FROM registrations WHERE student_id = ?", (sid,))
                    cur.execute("DELETE FROM grades WHERE student_id = ?", (sid,))
                    cur.execute("DELETE FROM grade_audit WHERE student_id = ?", (sid,))
                    cur.execute("DELETE FROM conflict_report WHERE student_id = ?", (sid,))
                
                cur.execute("DELETE FROM students WHERE student_id = ?", (sid,))
                if cur.rowcount == 0:
                    raise NotFoundError("الطالب غير موجود")
                
                conn.commit()
                logger.info(f"Student deleted: {sid}")
                return {'status': 'ok', 'message': 'تم حذف الطالب'}
        except NotFoundError:
            raise
        except Exception as e:
            logger.error(f"Error deleting student: {e}")
            raise DatabaseError(f"فشل حذف الطالب: {str(e)}")
    
    @staticmethod
    def get_student_count() -> int:
        """الحصول على عدد الطلاب"""
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                row = cur.execute("SELECT COUNT(*) FROM students").fetchone()
                return row[0] if row else 0
        except Exception as e:
            logger.error(f"Error counting students: {e}")
            return 0


# ============================================
# خدمة المقررات
# ============================================

class CourseService:
    """خدمة إدارة المقررات"""
    
    @staticmethod
    def get_all_courses() -> List[Dict]:
        """جلب جميع المقررات"""
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                rows = cur.execute("""
                    SELECT course_name, course_code, units 
                    FROM courses 
                    WHERE COALESCE(course_name, '') <> ''
                    ORDER BY course_name
                """).fetchall()
                return [
                    {
                        'course_name': r[0],
                        'course_code': r[1] or '',
                        'units': r[2] or 0
                    }
                    for r in rows
                ]
        except Exception as e:
            logger.error(f"Error getting courses: {e}")
            raise DatabaseError(f"فشل جلب قائمة المقررات: {str(e)}")
    
    @staticmethod
    def get_course(course_name: str) -> Optional[Dict]:
        """جلب مقرر بالاسم"""
        name = sanitize_input(course_name, 200)
        if not name:
            raise ValidationError("اسم المقرر مطلوب")
        
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                row = cur.execute(
                    "SELECT course_name, course_code, units FROM courses WHERE course_name = ?",
                    (name,)
                ).fetchone()
                
                if row:
                    return {
                        'course_name': row[0],
                        'course_code': row[1] or '',
                        'units': row[2] or 0
                    }
                return None
        except Exception as e:
            logger.error(f"Error getting course {name}: {e}")
            raise DatabaseError(f"فشل جلب بيانات المقرر: {str(e)}")
    
    @staticmethod
    def add_course(course_name: str, course_code: str = "", units: int = 0) -> Dict:
        """إضافة مقرر جديد"""
        name = sanitize_input(course_name, 200)
        if not name:
            raise ValidationError("اسم المقرر مطلوب")
        
        code = sanitize_input(course_code, 50)
        units_val = normalize_units(units)
        
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                cur.execute(
                    "INSERT OR REPLACE INTO courses (course_name, course_code, units) VALUES (?, ?, ?)",
                    (name, code, units_val)
                )
                conn.commit()
                logger.info(f"Course added/updated: {name}")
                return {'status': 'ok', 'message': 'تم إضافة المقرر', 'course_name': name}
        except Exception as e:
            logger.error(f"Error adding course: {e}")
            raise DatabaseError(f"فشل إضافة المقرر: {str(e)}")
    
    @staticmethod
    def update_course(old_name: str, new_name: str, course_code: str = None, units: int = None) -> Dict:
        """تحديث بيانات مقرر"""
        old = sanitize_input(old_name, 200)
        new = sanitize_input(new_name, 200)
        
        if not old or not new:
            raise ValidationError("اسم المقرر القديم والجديد مطلوبان")
        
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                
                # تحديث المقرر
                if course_code is not None and units is not None:
                    cur.execute(
                        "UPDATE courses SET course_name=?, course_code=?, units=? WHERE course_name=?",
                        (new, sanitize_input(course_code, 50), normalize_units(units), old)
                    )
                elif course_code is not None:
                    cur.execute(
                        "UPDATE courses SET course_name=?, course_code=? WHERE course_name=?",
                        (new, sanitize_input(course_code, 50), old)
                    )
                elif units is not None:
                    cur.execute(
                        "UPDATE courses SET course_name=?, units=? WHERE course_name=?",
                        (new, normalize_units(units), old)
                    )
                else:
                    cur.execute(
                        "UPDATE courses SET course_name=? WHERE course_name=?",
                        (new, old)
                    )
                
                if cur.rowcount == 0:
                    raise NotFoundError("المقرر غير موجود")
                
                # تحديث الجداول المرتبطة
                for table in ('grades', 'schedule', 'registrations', 'prereqs'):
                    try:
                        cur.execute(f"UPDATE {table} SET course_name=? WHERE course_name=?", (new, old))
                    except Exception:
                        pass
                
                # تحديث المتطلبات
                cur.execute(
                    "UPDATE prereqs SET required_course_name=? WHERE required_course_name=?",
                    (new, old)
                )
                
                # أي تعديل في بيانات المقرر (الاسم/الرمز/الوحدات) يمكن أن يؤثر على الجدول النهائي والتعارضات
                # لذا نفرّغ الجداول المشتقة ليُعاد حسابها عند تشغيل التحسين.
                try:
                    cur.execute("DELETE FROM optimized_schedule")
                except Exception:
                    pass
                try:
                    cur.execute("DELETE FROM conflict_report")
                except Exception:
                    pass

                conn.commit()
                return {'status': 'ok', 'message': 'تم تحديث بيانات المقرر'}
        except NotFoundError:
            raise
        except Exception as e:
            logger.error(f"Error updating course: {e}")
            raise DatabaseError(f"فشل تحديث بيانات المقرر: {str(e)}")
    
    @staticmethod
    def delete_course(course_name: str, cascade: bool = True) -> Dict:
        """حذف مقرر"""
        name = sanitize_input(course_name, 200)
        if not name:
            raise ValidationError("اسم المقرر مطلوب")
        
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                
                if cascade:
                    for table in ('schedule', 'registrations', 'grades'):
                        try:
                            cur.execute(f"DELETE FROM {table} WHERE course_name = ?", (name,))
                        except Exception:
                            pass
                    cur.execute(
                        "DELETE FROM prereqs WHERE course_name = ? OR required_course_name = ?",
                        (name, name)
                    )
                
                cur.execute("DELETE FROM courses WHERE course_name = ?", (name,))
                if cur.rowcount == 0:
                    raise NotFoundError("المقرر غير موجود")

                # حذف مقرر مرتبط بالجدول/التسجيلات يعني أن نتائج التحسين الحالية لم تعد صالحة.
                try:
                    cur.execute("DELETE FROM optimized_schedule")
                except Exception:
                    pass
                try:
                    cur.execute("DELETE FROM conflict_report")
                except Exception:
                    pass
                
                conn.commit()
                logger.info(f"Course deleted: {name}")
                return {'status': 'ok', 'message': 'تم حذف المقرر'}
        except NotFoundError:
            raise
        except Exception as e:
            logger.error(f"Error deleting course: {e}")
            raise DatabaseError(f"فشل حذف المقرر: {str(e)}")


# ============================================
# خدمة الجدول الدراسي
# ============================================

class ScheduleService:
    """خدمة إدارة الجدول الدراسي"""
    
    @staticmethod
    def get_all_schedule_rows() -> List[Dict]:
        """جلب جميع صفوف الجدول الدراسي مع عدد الطلاب"""
        try:
            with get_connection() as conn:
                cur = conn.cursor()
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
                return [
                    {
                        'section_id': r[0],
                        'course_name': r[1],
                        'day': r[2],
                        'time': r[3],
                        'room': r[4] or '',
                        'instructor': r[5] or '',
                        'semester': r[6] or '',
                        'student_count': r[7] or 0
                    }
                    for r in rows
                ]
        except Exception as e:
            logger.error(f"Error getting schedule rows: {e}")
            raise DatabaseError(f"فشل جلب الجدول الدراسي: {str(e)}")
    
    @staticmethod
    def add_schedule_row(course_name: str, day: str, time: str, 
                        room: str = "", instructor: str = "", semester: str = "") -> Dict:
        """إضافة صف جديد للجدول الدراسي"""
        name = sanitize_input(course_name, 200)
        day_val = sanitize_input(day, 20)
        time_val = sanitize_input(time, 20)
        
        if not name:
            raise ValidationError("اسم المقرر مطلوب")
        if not day_val:
            raise ValidationError("اليوم مطلوب")
        if not time_val:
            raise ValidationError("الوقت مطلوب")
        
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                cur.execute(
                    """INSERT INTO schedule (course_name, day, time, room, instructor, semester) 
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (name, day_val, time_val, 
                     sanitize_input(room, 50), 
                     sanitize_input(instructor, 100), 
                     sanitize_input(semester, 50) or SEMESTER_LABEL)
                )
                rowid = cur.lastrowid

                # أي تغيير في الجدول الدراسي يجعل الجدول النهائي/تقرير التعارضات قديمة،
                # لذا نفرّغ الجداول المشتقة لتُعاد حساباتها عند الضغط على زر التحسين.
                try:
                    cur.execute("DELETE FROM optimized_schedule")
                except Exception:
                    pass
                try:
                    cur.execute("DELETE FROM conflict_report")
                except Exception:
                    pass

                conn.commit()
                logger.info(f"Schedule row added: {name} on {day_val}")
                return {'status': 'ok', 'message': 'تم إضافة الصف للجدول الدراسي', 'rowid': rowid}
        except Exception as e:
            logger.error(f"Error adding schedule row: {e}")
            raise DatabaseError(f"فشل إضافة الصف: {str(e)}")
    
    @staticmethod
    def update_schedule_row(section_id: int, **kwargs) -> Dict:
        """تحديث صف في الجدول الدراسي"""
        if not section_id:
            raise ValidationError("معرّف الصف مطلوب")
        
        allowed_fields = {'course_name', 'day', 'time', 'room', 'instructor', 'semester'}
        updates = {k: v for k, v in kwargs.items() if k in allowed_fields and v is not None}
        
        if not updates:
            raise ValidationError("لا توجد بيانات للتحديث")
        
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                
                set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
                values = list(updates.values()) + [section_id]
                
                cur.execute(
                    f"UPDATE schedule SET {set_clause} WHERE rowid = ?",
                    values
                )
                
                if cur.rowcount == 0:
                    raise NotFoundError("الصف غير موجود")

                # أي تعديل في الجدول الدراسي يفسد الجدول النهائي/تقرير التعارضات الحالية
                try:
                    cur.execute("DELETE FROM optimized_schedule")
                except Exception:
                    pass
                try:
                    cur.execute("DELETE FROM conflict_report")
                except Exception:
                    pass

                conn.commit()
                return {'status': 'ok', 'message': 'تم تحديث الصف'}
        except NotFoundError:
            raise
        except Exception as e:
            logger.error(f"Error updating schedule row: {e}")
            raise DatabaseError(f"فشل تحديث الصف: {str(e)}")
    
    @staticmethod
    def delete_schedule_row(section_id: int) -> Dict:
        """حذف صف من الجدول الدراسي"""
        if not section_id:
            raise ValidationError("معرّف الصف مطلوب")
        
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                cur.execute("DELETE FROM schedule WHERE rowid = ?", (section_id,))
                if cur.rowcount == 0:
                    raise NotFoundError("الصف غير موجود")

                # تفريغ الجداول المشتقة حتى لا تبقى نتائج قديمة
                try:
                    cur.execute("DELETE FROM optimized_schedule")
                except Exception:
                    pass
                try:
                    cur.execute("DELETE FROM conflict_report")
                except Exception:
                    pass

                conn.commit()
                logger.info(f"Schedule row deleted: {section_id}")
                return {'status': 'ok', 'message': 'تم حذف الصف'}
        except NotFoundError:
            raise
        except Exception as e:
            logger.error(f"Error deleting schedule row: {e}")
            raise DatabaseError(f"فشل حذف الصف: {str(e)}")


# ============================================
# خدمة التسجيلات
# ============================================

class RegistrationService:
    """خدمة إدارة التسجيلات"""
    
    @staticmethod
    def get_student_registrations(student_id: str) -> List[str]:
        """جلب تسجيلات طالب"""
        sid = normalize_student_id(student_id)
        if not sid:
            raise ValidationError("معرّف الطالب مطلوب")
        
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                rows = cur.execute(
                    "SELECT course_name FROM registrations WHERE student_id = ?",
                    (sid,)
                ).fetchall()
                return [r[0] for r in rows]
        except Exception as e:
            logger.error(f"Error getting registrations for {sid}: {e}")
            raise DatabaseError(f"فشل جلب التسجيلات: {str(e)}")
    
    @staticmethod
    def save_registrations(student_id: str, courses: List[str]) -> Dict:
        """حفظ تسجيلات طالب"""
        sid = normalize_student_id(student_id)
        if not sid:
            raise ValidationError("معرّف الطالب مطلوب")
        
        # إزالة التكرارات
        unique_courses = list(dict.fromkeys(courses))
        
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                
                # حذف التسجيلات القديمة
                cur.execute("DELETE FROM registrations WHERE student_id = ?", (sid,))
                
                # إضافة التسجيلات الجديدة
                if unique_courses:
                    cur.executemany(
                        "INSERT INTO registrations (student_id, course_name) VALUES (?, ?)",
                        [(sid, c) for c in unique_courses]
                    )
                
                conn.commit()
                logger.info(f"Registrations saved for {sid}: {len(unique_courses)} courses")
                return {
                    'status': 'ok', 
                    'message': 'تم حفظ التسجيلات',
                    'count': len(unique_courses)
                }
        except Exception as e:
            logger.error(f"Error saving registrations: {e}")
            raise DatabaseError(f"فشل حفظ التسجيلات: {str(e)}")
    
    @staticmethod
    def delete_registrations(student_id: str) -> Dict:
        """حذف جميع تسجيلات طالب"""
        sid = normalize_student_id(student_id)
        if not sid:
            raise ValidationError("معرّف الطالب مطلوب")
        
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                cur.execute("DELETE FROM registrations WHERE student_id = ?", (sid,))
                deleted = cur.rowcount
                conn.commit()
                return {'status': 'ok', 'message': f'تم حذف {deleted} تسجيل'}
        except Exception as e:
            logger.error(f"Error deleting registrations: {e}")
            raise DatabaseError(f"فشل حذف التسجيلات: {str(e)}")


# ============================================
# خدمة الدرجات
# ============================================

class GradeService:
    """خدمة إدارة الدرجات"""
    
    @staticmethod
    def get_student_grades(student_id: str, semester: str = None) -> List[Dict]:
        """جلب درجات طالب"""
        sid = normalize_student_id(student_id)
        if not sid:
            raise ValidationError("معرّف الطالب مطلوب")
        
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                
                if semester:
                    rows = cur.execute("""
                        SELECT semester, course_name, course_code, units, grade
                        FROM grades
                        WHERE student_id = ? AND semester = ?
                        ORDER BY course_name
                    """, (sid, semester)).fetchall()
                else:
                    rows = cur.execute("""
                        SELECT semester, course_name, course_code, units, grade
                        FROM grades
                        WHERE student_id = ?
                        ORDER BY semester, course_name
                    """, (sid,)).fetchall()
                
                return [
                    {
                        'semester': r[0],
                        'course_name': r[1],
                        'course_code': r[2] or '',
                        'units': r[3] or 0,
                        'grade': r[4]
                    }
                    for r in rows
                ]
        except Exception as e:
            logger.error(f"Error getting grades for {sid}: {e}")
            raise DatabaseError(f"فشل جلب الدرجات: {str(e)}")
    
    @staticmethod
    def save_grade(student_id: str, semester: str, course_name: str, 
                   grade: float = None, course_code: str = "", units: int = 0,
                   changed_by: str = "system") -> Dict:
        """حفظ درجة"""
        sid = normalize_student_id(student_id)
        if not sid:
            raise ValidationError("معرّف الطالب مطلوب")
        if not semester:
            raise ValidationError("الفصل الدراسي مطلوب")
        if not course_name:
            raise ValidationError("اسم المقرر مطلوب")
        
        grade_val = normalize_grade(grade)
        if grade_val is not None and (grade_val < 0 or grade_val > 100):
            raise ValidationError("الدرجة يجب أن تكون بين 0 و 100")
        
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                
                # جلب الدرجة القديمة للتدقيق
                old = cur.execute(
                    "SELECT grade FROM grades WHERE student_id = ? AND semester = ? AND course_name = ?",
                    (sid, semester, course_name)
                ).fetchone()
                old_grade = old[0] if old else None
                
                # تسجيل التعديل
                cur.execute("""
                    INSERT INTO grade_audit 
                    (student_id, semester, course_name, old_grade, new_grade, changed_by, ts)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (sid, semester, course_name, old_grade, grade_val, 
                      changed_by, datetime.utcnow().isoformat()))
                
                # حفظ الدرجة
                cur.execute("""
                    INSERT OR REPLACE INTO grades 
                    (student_id, semester, course_name, course_code, units, grade)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (sid, semester, course_name, course_code, normalize_units(units), grade_val))
                
                conn.commit()
                logger.info(f"Grade saved for {sid} in {course_name}: {grade_val}")
                return {'status': 'ok', 'message': 'تم حفظ الدرجة'}
        except Exception as e:
            logger.error(f"Error saving grade: {e}")
            raise DatabaseError(f"فشل حفظ الدرجة: {str(e)}")
    
    @staticmethod
    def calculate_gpa(student_id: str, semester: str = None) -> Dict:
        """حساب المعدل التراكمي"""
        sid = normalize_student_id(student_id)
        if not sid:
            raise ValidationError("معرّف الطالب مطلوب")
        
        try:
            grades = GradeService.get_student_grades(sid, semester)
            
            total_points = 0.0
            total_units = 0
            
            for g in grades:
                if g['grade'] is not None and g['units'] > 0:
                    total_points += g['grade'] * g['units']
                    total_units += g['units']
            
            gpa = round(total_points / total_units, 2) if total_units > 0 else 0.0
            
            return {
                'student_id': sid,
                'semester': semester,
                'gpa': gpa,
                'total_units': total_units,
                'courses_count': len([g for g in grades if g['grade'] is not None])
            }
        except Exception as e:
            logger.error(f"Error calculating GPA for {sid}: {e}")
            raise DatabaseError(f"فشل حساب المعدل: {str(e)}")
