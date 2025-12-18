"""
Service Layer - فصل منطق العمل عن Routes
"""
import logging
from typing import List, Dict, Optional, Any
from ..services.utilities import get_connection
from ..core.exceptions import ValidationError, NotFoundError, DatabaseError

logger = logging.getLogger(__name__)


class StudentService:
    """خدمة إدارة الطلاب"""
    
    @staticmethod
    def normalize_sid(sid):
        """تطبيع معرّف الطالب"""
        if sid is None:
            return ""
        return str(sid).strip()
    
    @staticmethod
    def get_all_students() -> List[Dict]:
        """جلب جميع الطلاب"""
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                rows = cur.execute("SELECT student_id, student_name FROM students").fetchall()
                return [{'student_id': r[0], 'student_name': r[1]} for r in rows]
        except Exception as e:
            logger.error(f"Error getting students: {e}")
            raise DatabaseError(f"فشل جلب قائمة الطلاب: {str(e)}")
    
    @staticmethod
    def add_student(student_id: str, student_name: str) -> Dict:
        """إضافة طالب جديد"""
        sid = StudentService.normalize_sid(student_id)
        if not sid:
            raise ValidationError("معرّف الطالب مطلوب")
        
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                cur.execute(
                    "INSERT OR REPLACE INTO students (student_id, student_name) VALUES (?,?)",
                    (sid, student_name)
                )
                conn.commit()
                return {'status': 'ok', 'message': 'تم إضافة الطالب'}
        except Exception as e:
            logger.error(f"Error adding student: {e}")
            raise DatabaseError(f"فشل إضافة الطالب: {str(e)}")
    
    @staticmethod
    def delete_student(student_id: str) -> Dict:
        """حذف طالب"""
        sid = StudentService.normalize_sid(student_id)
        if not sid:
            raise ValidationError("معرّف الطالب مطلوب")
        
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                cur.execute("DELETE FROM students WHERE student_id = ?", (sid,))
                if cur.rowcount == 0:
                    raise NotFoundError("الطالب غير موجود")
                conn.commit()
                return {'status': 'ok', 'message': 'تم حذف الطالب'}
        except NotFoundError:
            raise
        except Exception as e:
            logger.error(f"Error deleting student: {e}")
            raise DatabaseError(f"فشل حذف الطالب: {str(e)}")


class CourseService:
    """خدمة إدارة المقررات"""
    
    @staticmethod
    def get_all_courses() -> List[Dict]:
        """جلب جميع المقررات"""
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                rows = cur.execute(
                    "SELECT course_name, course_code, units FROM courses"
                ).fetchall()
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
    def add_course(course_name: str, course_code: str = "", units: int = 0) -> Dict:
        """إضافة مقرر جديد"""
        if not course_name or not course_name.strip():
            raise ValidationError("اسم المقرر مطلوب")
        
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                cur.execute(
                    "INSERT OR REPLACE INTO courses (course_name, course_code, units) VALUES (?, ?, ?)",
                    (course_name.strip(), course_code or "", int(units) if units else 0)
                )
                conn.commit()
                return {'status': 'ok', 'message': 'تم إضافة المقرر'}
        except Exception as e:
            logger.error(f"Error adding course: {e}")
            raise DatabaseError(f"فشل إضافة المقرر: {str(e)}")
    
    @staticmethod
    def delete_course(course_name: str) -> Dict:
        """حذف مقرر"""
        if not course_name or not course_name.strip():
            raise ValidationError("اسم المقرر مطلوب")
        
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                cur.execute("DELETE FROM courses WHERE course_name = ?", (course_name.strip(),))
                if cur.rowcount == 0:
                    raise NotFoundError("المقرر غير موجود")
                conn.commit()
                return {'status': 'ok', 'message': 'تم حذف المقرر'}
        except NotFoundError:
            raise
        except Exception as e:
            logger.error(f"Error deleting course: {e}")
            raise DatabaseError(f"فشل حذف المقرر: {str(e)}")


class ScheduleService:
    """خدمة إدارة الجدول الدراسي"""
    
    @staticmethod
    def get_all_schedule_rows() -> List[Dict]:
        """جلب جميع صفوف الجدول الدراسي"""
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
                        'room': r[4],
                        'instructor': r[5],
                        'semester': r[6],
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
        if not course_name or not course_name.strip():
            raise ValidationError("اسم المقرر مطلوب")
        if not day or not day.strip():
            raise ValidationError("اليوم مطلوب")
        if not time or not time.strip():
            raise ValidationError("الوقت مطلوب")
        
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                cur.execute(
                    """INSERT INTO schedule (course_name, day, time, room, instructor, semester) 
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (course_name.strip(), day.strip(), time.strip(), 
                     room or "", instructor or "", semester or "")
                )
                conn.commit()
                return {'status': 'ok', 'message': 'تم إضافة الصف للجدول الدراسي'}
        except Exception as e:
            logger.error(f"Error adding schedule row: {e}")
            raise DatabaseError(f"فشل إضافة الصف: {str(e)}")
    
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
                conn.commit()
                return {'status': 'ok', 'message': 'تم حذف الصف'}
        except NotFoundError:
            raise
        except Exception as e:
            logger.error(f"Error deleting schedule row: {e}")
            raise DatabaseError(f"فشل حذف الصف: {str(e)}")

