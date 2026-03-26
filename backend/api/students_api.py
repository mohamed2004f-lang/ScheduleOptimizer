"""
Students API Endpoints
RESTful API for managing students (read-only for v1 rollout)
Version: 1.0.0
"""

from __future__ import annotations

import logging
from functools import wraps

from flask import Blueprint, jsonify, request, session

from backend.core.auth import login_required, role_required
from backend.services.utilities import get_connection

logger = logging.getLogger(__name__)

students_api_bp = Blueprint("students_api", __name__, url_prefix="/api/v1/students")


# -----------------------------
# Errors + handler decorator
# -----------------------------
class APIError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class ValidationError(APIError):
    def __init__(self, message: str):
        super().__init__(message, 400)


class NotFoundError(APIError):
    def __init__(self, message: str):
        super().__init__(message, 404)


def handle_errors(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except APIError as e:
            return jsonify({"success": False, "error": e.message}), e.status_code
        except Exception as e:
            logger.exception("Unexpected error in students API")
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Internal server error",
                        "details": str(e),
                    }
                ),
                500,
            )

    return decorated


# -----------------------------
# Authorization helpers
# -----------------------------
def _can_view_student(conn, student_id: str) -> bool:
    """
    - admin/supervisor: allowed (supervisor only for assigned students)
    - student: allowed only for own record
    """
    role = session.get("user_role") or ""
    if role == "admin":
        return True
    if role == "student":
        sid_session = session.get("student_id") or session.get("user")
        return bool(sid_session and str(sid_session) == str(student_id))
    is_supervisor = (role == "supervisor") or (role == "instructor" and int(session.get("is_supervisor") or 0) == 1)
    if is_supervisor:
        instructor_id = session.get("instructor_id")
        if not instructor_id:
            return False
        cur = conn.cursor()
        row = cur.execute(
            "SELECT 1 FROM student_supervisor WHERE student_id = ? AND instructor_id = ? LIMIT 1",
            (student_id, instructor_id),
        ).fetchone()
        return bool(row)
    # any other authenticated role: read-only allowed? keep strict
    return False


# -----------------------------
# Routes (GET/Statistics only)
# -----------------------------
@students_api_bp.route("", methods=["GET"])
@login_required
@handle_errors
def get_students():
    """Get students with pagination + search. Admin/Supervisor only."""
    role = session.get("user_role") or ""
    is_supervisor = (role == "supervisor") or (role == "instructor" and int(session.get("is_supervisor") or 0) == 1)
    if role != "admin" and not is_supervisor:
        raise APIError("ليس لديك صلاحية لعرض قائمة الطلبة", 403)

    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    search = (request.args.get("search", "", type=str) or "").strip()

    if page < 1 or per_page < 1 or per_page > 100:
        raise ValidationError("Invalid pagination parameters")

    with get_connection() as conn:
        cur = conn.cursor()

        query = "SELECT student_id, student_name, university_number, email, phone, created_at, updated_at FROM students"
        count_query = "SELECT COUNT(*) FROM students"
        params = []

        if search:
            query += " WHERE student_name LIKE ? OR student_id LIKE ? OR university_number LIKE ?"
            count_query += " WHERE student_name LIKE ? OR student_id LIKE ? OR university_number LIKE ?"
            s = f"%{search}%"
            params.extend([s, s, s])

        total = cur.execute(count_query, params).fetchone()[0]

        query += " ORDER BY student_name ASC LIMIT ? OFFSET ?"
        params2 = list(params) + [per_page, (page - 1) * per_page]
        rows = cur.execute(query, params2).fetchall()
        students = [dict(r) for r in rows]

    pages = (total + per_page - 1) // per_page
    return (
        jsonify(
            {
                "success": True,
                "data": students,
                "pagination": {
                    "page": page,
                    "per_page": per_page,
                    "total": total,
                    "pages": pages,
                },
            }
        ),
        200,
    )


@students_api_bp.route("/<string:student_id>", methods=["GET"])
@login_required
@handle_errors
def get_student(student_id: str):
    """Get a single student, plus current registrations and grades summary."""
    sid = (student_id or "").strip()
    if not sid:
        raise ValidationError("student_id مطلوب")

    with get_connection() as conn:
        if not _can_view_student(conn, sid):
            raise APIError("ليس لديك صلاحية لعرض بيانات هذا الطالب", 403)

        cur = conn.cursor()
        student = cur.execute(
            "SELECT student_id, student_name, university_number, email, phone, created_at, updated_at FROM students WHERE student_id = ?",
            (sid,),
        ).fetchone()
        if not student:
            raise NotFoundError(f"Student with ID {sid} not found")

        # Current registrations (includes registered_at in schema)
        regs = cur.execute(
            """
            SELECT c.course_name, c.course_code, c.units, r.registered_at
            FROM registrations r
            JOIN courses c ON r.course_name = c.course_name
            WHERE r.student_id = ?
            ORDER BY r.registered_at DESC
            """,
            (sid,),
        ).fetchall()
        courses = [dict(r) for r in regs]

        # Grades (do not include all columns to keep response small)
        grades = cur.execute(
            """
            SELECT semester, course_name, course_code, units, grade
            FROM grades
            WHERE student_id = ?
            ORDER BY semester DESC
            """,
            (sid,),
        ).fetchall()
        grades_rows = [dict(r) for r in grades]

    payload = dict(student)
    payload["courses"] = courses
    payload["grades"] = grades_rows
    return jsonify({"success": True, "data": payload}), 200


@students_api_bp.route("/statistics", methods=["GET"])
@role_required("admin", "supervisor")
@handle_errors
def get_students_statistics():
    """Simple statistics for dashboards."""
    with get_connection() as conn:
        cur = conn.cursor()
        total_students = cur.execute("SELECT COUNT(*) FROM students").fetchone()[0]
        students_with_grades = cur.execute(
            "SELECT COUNT(DISTINCT student_id) FROM grades"
        ).fetchone()[0]
        registered_students = cur.execute(
            "SELECT COUNT(DISTINCT student_id) FROM registrations"
        ).fetchone()[0]

    return (
        jsonify(
            {
                "success": True,
                "data": {
                    "total_students": total_students,
                    "students_with_grades": students_with_grades,
                    "registered_students": registered_students,
                },
            }
        ),
        200,
    )


# -----------------------------
# CRUD (Admin only)
# -----------------------------
@students_api_bp.route("", methods=["POST"])
@role_required("admin")
@handle_errors
def create_student():
    """
    Create a new student (Admin only).
    Required: student_id, student_name
    Optional: university_number, email, phone
    """
    data = request.get_json(force=True) or {}
    student_id = (data.get("student_id") or "").strip()
    student_name = (data.get("student_name") or "").strip()
    university_number = (data.get("university_number") or "").strip()
    email = (data.get("email") or "").strip()
    phone = (data.get("phone") or "").strip()

    if not student_id:
        raise ValidationError("student_id مطلوب")
    if not student_name:
        raise ValidationError("student_name مطلوب")

    with get_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                INSERT INTO students (student_id, student_name, university_number, email, phone)
                VALUES (?, ?, ?, ?, ?)
                """,
                (student_id, student_name, university_number, email, phone),
            )
            conn.commit()
        except Exception as e:
            conn.rollback()
            # Duplicate PK or other constraint
            raise ValidationError(f"تعذر إنشاء الطالب: {str(e)}")

        row = cur.execute(
            "SELECT student_id, student_name, university_number, email, phone, created_at, updated_at FROM students WHERE student_id = ?",
            (student_id,),
        ).fetchone()

    return (
        jsonify(
            {
                "success": True,
                "message": "تم إنشاء الطالب بنجاح",
                "data": dict(row) if row else None,
            }
        ),
        201,
    )


@students_api_bp.route("/<string:student_id>", methods=["PUT"])
@role_required("admin")
@handle_errors
def update_student(student_id: str):
    """
    Update a student (Admin only).
    Note: cannot change student_id to avoid breaking relationships.
    Allowed fields: student_name, university_number, email, phone
    """
    sid = (student_id or "").strip()
    if not sid:
        raise ValidationError("student_id مطلوب")

    data = request.get_json(force=True) or {}
    if "student_id" in data and (data.get("student_id") or "").strip() != sid:
        raise ValidationError("لا يمكن تعديل student_id. أنشئ طالباً جديداً إن لزم.")

    allowed_fields = ("student_name", "university_number", "email", "phone")
    updates = []
    params = []
    for f in allowed_fields:
        if f in data:
            updates.append(f"{f} = ?")
            params.append((data.get(f) or "").strip())

    if not updates:
        raise ValidationError("لا توجد حقول صالحة للتحديث")

    # keep updated_at in sync (exists in schema)
    updates.append("updated_at = CURRENT_TIMESTAMP")

    with get_connection() as conn:
        cur = conn.cursor()
        exists = cur.execute(
            "SELECT 1 FROM students WHERE student_id = ? LIMIT 1", (sid,)
        ).fetchone()
        if not exists:
            raise NotFoundError(f"Student with ID {sid} not found")

        cur.execute(
            f"UPDATE students SET {', '.join(updates)} WHERE student_id = ?",
            params + [sid],
        )
        conn.commit()

        row = cur.execute(
            "SELECT student_id, student_name, university_number, email, phone, created_at, updated_at FROM students WHERE student_id = ?",
            (sid,),
        ).fetchone()

    return (
        jsonify(
            {
                "success": True,
                "message": "تم تحديث بيانات الطالب",
                "data": dict(row) if row else None,
            }
        ),
        200,
    )


@students_api_bp.route("/<string:student_id>", methods=["DELETE"])
@role_required("admin")
@handle_errors
def delete_student(student_id: str):
    """
    Delete a student (Admin only).
    Safety: prevent delete if student has grades or current registrations.
    """
    sid = (student_id or "").strip()
    if not sid:
        raise ValidationError("student_id مطلوب")

    with get_connection() as conn:
        cur = conn.cursor()
        exists = cur.execute(
            "SELECT 1 FROM students WHERE student_id = ? LIMIT 1", (sid,)
        ).fetchone()
        if not exists:
            raise NotFoundError(f"Student with ID {sid} not found")

        grades_count = cur.execute(
            "SELECT COUNT(*) FROM grades WHERE student_id = ?", (sid,)
        ).fetchone()[0]
        reg_count = cur.execute(
            "SELECT COUNT(*) FROM registrations WHERE student_id = ?", (sid,)
        ).fetchone()[0]

        if grades_count > 0 or reg_count > 0:
            raise ValidationError(
                f"لا يمكن حذف الطالب لأن لديه درجات ({grades_count}) أو تسجيلات حالية ({reg_count})."
            )

        cur.execute("DELETE FROM students WHERE student_id = ?", (sid,))
        conn.commit()

    return jsonify({"success": True, "message": "تم حذف الطالب"}), 200

