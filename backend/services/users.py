from flask import Blueprint, request, jsonify

from backend.core.auth import role_required, hash_password
from .utilities import get_connection

users_bp = Blueprint("users", __name__)

def _normalize_role(role: str) -> str:
    r = (role or "").strip()
    # legacy compatibility
    if r == "admin":
        return "admin_main"
    if r == "supervisor":
        return "instructor"
    return r


def _current_role() -> str:
    # Prefer Flask-Login user, fall back to session role
    try:
        from flask_login import current_user
        if getattr(current_user, "is_authenticated", False):
            return getattr(current_user, "role", "") or ""
    except Exception:
        pass
    try:
        from flask import session
        return (session.get("user_role") or "").strip()
    except Exception:
        return ""


@users_bp.route("/list")
@role_required("admin_main", "head_of_department")
def list_users():
    """
    إرجاع قائمة المستخدمين (بدون كلمات المرور الصريحة).
    """
    with get_connection() as conn:
        cur = conn.cursor()
        rows = cur.execute(
            "SELECT username, role, student_id, instructor_id, "
            "COALESCE(is_supervisor,0) AS is_supervisor, "
            "COALESCE(is_active,1) AS is_active "
            "FROM users ORDER BY username"
        ).fetchall()
        items = []
        for r in rows:
            items.append(
                {
                    "username": r[0],
                    "role": r[1],
                    "student_id": r[2],
                    "instructor_id": r[3],
                    "is_supervisor": int(r[4] or 0),
                    "is_active": int(r[5] or 1),
                }
            )
    return jsonify({"users": items})


@users_bp.route("/add", methods=["POST"])
@role_required("admin_main", "head_of_department")
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
    role = _normalize_role((data.get("role") or "").strip() or "student")
    student_id = (data.get("student_id") or "").strip() or None
    instructor_id_raw = data.get("instructor_id")
    is_supervisor = int(bool(data.get("is_supervisor", False)))
    is_active = int(bool(data.get("is_active", True)))
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
    if role not in ("admin_main", "head_of_department", "instructor", "student"):
        return (
            jsonify({"status": "error", "message": "role غير صحيح"}),
            400,
        )

    actor_role = _normalize_role(_current_role())
    if actor_role != "admin_main":
        # رئيس القسم: لا يعيّن admin_main ولا يغيّر تفعيل الحساب ولا يغيّر كلمات المرور ولا ينشئ مستخدمين جدد
        if role == "admin_main":
            return jsonify({"status": "error", "message": "غير مسموح تعيين دور admin_main"}), 403
        if not is_active:
            return jsonify({"status": "error", "message": "غير مسموح تعطيل/تفعيل الحساب لرئيس القسم"}), 403
        if password:
            return jsonify({"status": "error", "message": "غير مسموح تغيير كلمة المرور لرئيس القسم"}), 403

    with get_connection() as conn:
        cur = conn.cursor()
        existing = cur.execute(
            "SELECT username FROM users WHERE username = ?", (username,)
        ).fetchone()
        if existing:
            old_role_row = cur.execute("SELECT role FROM users WHERE username = ?", (username,)).fetchone()
            old_role = _normalize_role(old_role_row[0] if old_role_row else "")
            if old_role == "admin_main" and actor_role != "admin_main":
                return jsonify({"status": "error", "message": "لا يمكن تعديل مستخدم admin_main إلا بواسطة admin_main"}), 403
            if actor_role != "admin_main":
                # رئيس القسم يسمح فقط بتعديل الأساتذة: is_supervisor و instructor_id و role= instructor/ head_of_department
                if old_role not in ("instructor", "head_of_department"):
                    return jsonify({"status": "error", "message": "رئيس القسم يمكنه تعديل الأساتذة فقط"}), 403
                if role not in ("instructor", "head_of_department"):
                    return jsonify({"status": "error", "message": "لا يمكن تغيير دور الأستاذ إلى هذا الدور من قبل رئيس القسم"}), 403
        if existing:
            # تحديث مستخدم موجود
            if actor_role == "admin_main":
                if password:
                    pw_hash = hash_password(password)
                    cur.execute(
                        """
                        UPDATE users
                        SET password_hash = ?, role = ?, student_id = ?, instructor_id = ?, is_supervisor = ?, is_active = ?
                        WHERE username = ?
                        """,
                        (pw_hash, role, student_id, instructor_id, is_supervisor, is_active, username),
                    )
                else:
                    cur.execute(
                        """
                        UPDATE users
                        SET role = ?, student_id = ?, instructor_id = ?, is_supervisor = ?, is_active = ?
                        WHERE username = ?
                        """,
                        (role, student_id, instructor_id, is_supervisor, is_active, username),
                    )
            else:
                # رئيس القسم: تحديث محدود للأساتذة فقط
                cur.execute(
                    """
                    UPDATE users
                    SET role = ?, instructor_id = ?, is_supervisor = ?
                    WHERE username = ?
                    """,
                    (role, instructor_id, is_supervisor, username),
                )
        else:
            if actor_role != "admin_main":
                return jsonify({"status": "error", "message": "رئيس القسم لا يمكنه إنشاء مستخدم جديد"}), 403
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
                INSERT INTO users (username, password_hash, role, student_id, instructor_id, is_supervisor, is_active)
                VALUES (?,?,?,?,?,?,?)
                """,
                (username, pw_hash, role, student_id, instructor_id, is_supervisor, is_active),
            )
        conn.commit()

    return jsonify({"status": "ok"})


@users_bp.route("/delete", methods=["POST"])
@role_required("admin_main")
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


@users_bp.route("/toggle_active", methods=["POST"])
@role_required("admin_main")
def toggle_active():
    data = request.get_json(force=True) or {}
    username = (data.get("username") or "").strip()
    active = int(bool(data.get("active", True)))
    if not username:
        return jsonify({"status": "error", "message": "username مطلوب"}), 400

    actor_role = _normalize_role(_current_role())
    with get_connection() as conn:
        cur = conn.cursor()
        row = cur.execute("SELECT role FROM users WHERE username = ?", (username,)).fetchone()
        if not row:
            return jsonify({"status": "error", "message": "المستخدم غير موجود"}), 404
        target_role = _normalize_role(row[0])
        if target_role == "admin_main" and actor_role != "admin_main":
            return jsonify({"status": "error", "message": "لا يمكن تعطيل admin_main إلا بواسطة admin_main"}), 403
        if target_role == "admin_main" and active == 0:
            cnt = cur.execute("SELECT COUNT(*) FROM users WHERE role = 'admin_main' AND COALESCE(is_active,1)=1").fetchone()[0]
            if cnt <= 1:
                return jsonify({"status": "error", "message": "لا يمكن تعطيل آخر مستخدم admin_main"}), 400
        cur.execute("UPDATE users SET is_active = ? WHERE username = ?", (active, username))
        conn.commit()
    return jsonify({"status": "ok", "message": "تم تحديث الحالة"}), 200


@users_bp.route("/set_supervisor", methods=["POST"])
@role_required("admin_main", "head_of_department")
def set_supervisor():
    data = request.get_json(force=True) or {}
    username = (data.get("username") or "").strip()
    is_sup = int(bool(data.get("is_supervisor", True)))
    if not username:
        return jsonify({"status": "error", "message": "username مطلوب"}), 400
    with get_connection() as conn:
        cur = conn.cursor()
        row = cur.execute("SELECT role FROM users WHERE username = ?", (username,)).fetchone()
        if not row:
            return jsonify({"status": "error", "message": "المستخدم غير موجود"}), 404
        role = _normalize_role(row[0])
        if role not in ("instructor", "head_of_department"):
            return jsonify({"status": "error", "message": "يمكن تعيين الإشراف للأستاذ/رئيس القسم فقط"}), 400
        cur.execute("UPDATE users SET is_supervisor = ? WHERE username = ?", (is_sup, username))
        conn.commit()
    return jsonify({"status": "ok", "message": "تم تحديث الإشراف الأكاديمي"}), 200

