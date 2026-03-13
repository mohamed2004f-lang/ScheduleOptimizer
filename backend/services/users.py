from flask import Blueprint, request, jsonify

from backend.core.auth import admin_required, hash_password
from .utilities import get_connection

users_bp = Blueprint("users", __name__)


@users_bp.route("/list")
@admin_required
def list_users():
    """
    إرجاع قائمة المستخدمين (بدون كلمات المرور الصريحة).
    """
    with get_connection() as conn:
        cur = conn.cursor()
        rows = cur.execute(
            "SELECT username, role, student_id, instructor_id FROM users ORDER BY username"
        ).fetchall()
        items = []
        for r in rows:
            items.append(
                {
                    "username": r[0],
                    "role": r[1],
                    "student_id": r[2],
                    "instructor_id": r[3],
                }
            )
    return jsonify({"users": items})


@users_bp.route("/add", methods=["POST"])
@admin_required
def add_user():
    """
    إضافة/تحديث مستخدم.
    body:
      - username (إجباري)
      - password (إجباري عند الإنشاء؛ اختياري عند التحديث)
      - role: admin | supervisor | student
      - student_id (اختياري؛ مهم لدور student)
      - instructor_id (اختياري؛ مهم لدور supervisor)
    """
    data = request.get_json(force=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password")
    role = (data.get("role") or "").strip() or "student"
    student_id = (data.get("student_id") or "").strip() or None
    instructor_id_raw = data.get("instructor_id")
    instructor_id = None
    if instructor_id_raw not in (None, ""):
        try:
            instructor_id = int(instructor_id_raw)
        except (TypeError, ValueError):
            instructor_id = None

    if not username:
        return (
            jsonify({"status": "error", "message": "username مطلوب"}),
            400,
        )
    if role not in ("admin", "supervisor", "student"):
        return (
            jsonify({"status": "error", "message": "role غير صحيح"}),
            400,
        )

    with get_connection() as conn:
        cur = conn.cursor()
        existing = cur.execute(
            "SELECT username FROM users WHERE username = ?", (username,)
        ).fetchone()
        if existing:
            # تحديث مستخدم موجود
            if password:
                pw_hash = hash_password(password)
                cur.execute(
                    """
                    UPDATE users
                    SET password_hash = ?, role = ?, student_id = ?, instructor_id = ?
                    WHERE username = ?
                    """,
                    (pw_hash, role, student_id, instructor_id, username),
                )
            else:
                cur.execute(
                    """
                    UPDATE users
                    SET role = ?, student_id = ?, instructor_id = ?
                    WHERE username = ?
                    """,
                    (role, student_id, instructor_id, username),
                )
        else:
            if not password:
                return (
                    jsonify(
                        {
                            "status": "error",
                            "message": "password مطلوب عند إنشاء مستخدم جديد",
                        }
                    ),
                    400,
                )
            pw_hash = hash_password(password)
            cur.execute(
                """
                INSERT INTO users (username, password_hash, role, student_id, instructor_id)
                VALUES (?,?,?,?,?)
                """,
                (username, pw_hash, role, student_id, instructor_id),
            )
        conn.commit()

    return jsonify({"status": "ok"})


@users_bp.route("/delete", methods=["POST"])
@admin_required
def delete_user():
    """
    حذف مستخدم.
    body:
      - username
    """
    data = request.get_json(force=True) or {}
    username = (data.get("username") or "").strip()
    if not username:
        return (
            jsonify({"status": "error", "message": "username مطلوب"}),
            400,
        )
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM users WHERE username = ?", (username,))
        conn.commit()
    return jsonify({"status": "ok"})

