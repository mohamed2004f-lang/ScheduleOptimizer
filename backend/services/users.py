import hashlib
import secrets
from datetime import datetime, timedelta

from flask import Blueprint, request, jsonify

from backend.core.auth import role_required, hash_password
from .utilities import get_connection
from .mailer import send_email

users_bp = Blueprint("users", __name__)


def _now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _arabic_to_ascii_slug(name: str) -> str:
    """
    تحويل بسيط للاسم العربي إلى حروف لاتينية (تقريبي) لإنتاج username مقروء.
    ليس ترجمة لغوية، لكنه يعطي نتيجة عملية بدون اعتماد مكتبات خارجية.
    """
    s = (name or "").strip().lower()
    # إزالة علامات شائعة
    for ch in ("ـ", "’", "'", "“", "”", '"'):
        s = s.replace(ch, "")
    m = {
        "ا": "a", "أ": "a", "إ": "i", "آ": "a",
        "ب": "b", "ت": "t", "ث": "th",
        "ج": "j", "ح": "h", "خ": "kh",
        "د": "d", "ذ": "dh", "ر": "r", "ز": "z",
        "س": "s", "ش": "sh", "ص": "s", "ض": "d",
        "ط": "t", "ظ": "z", "ع": "a", "غ": "gh",
        "ف": "f", "ق": "q", "ك": "k", "ل": "l",
        "م": "m", "ن": "n", "ه": "h", "و": "w", "ي": "y", "ى": "a",
        "ة": "h", "ء": "",
        " ": ".", "  ": ".", "\t": ".",
    }
    out = []
    for ch in s:
        if "a" <= ch <= "z" or "0" <= ch <= "9":
            out.append(ch)
            continue
        out.append(m.get(ch, ".") if ch in m else ".")
    slug = "".join(out)
    while ".." in slug:
        slug = slug.replace("..", ".")
    slug = slug.strip(".")
    return slug


def _unique_username(conn, base: str) -> str:
    base = (base or "").strip().lower()
    base = base.replace(" ", ".")
    base = "".join(ch for ch in base if (ch.isalnum() or ch in (".", "_", "-")))
    base = base.strip("._-")
    if not base:
        base = "user"

    cur = conn.cursor()
    exists = cur.execute("SELECT 1 FROM users WHERE username = ? LIMIT 1", (base,)).fetchone()
    if not exists:
        return base
    for i in range(2, 10000):
        cand = f"{base}{i}"
        exists = cur.execute("SELECT 1 FROM users WHERE username = ? LIMIT 1", (cand,)).fetchone()
        if not exists:
            return cand
    return f"{base}{secrets.randbelow(99999)}"


@users_bp.route("/suggest_linked", methods=["GET"])
@role_required("admin_main", "head_of_department")
def suggest_linked():
    entity_type = (request.args.get("type") or "").strip().lower()
    entity_id = (request.args.get("id") or "").strip()
    if entity_type not in ("student", "instructor"):
        return jsonify({"status": "error", "message": "type must be student|instructor"}), 400
    if not entity_id:
        return jsonify({"status": "error", "message": "id مطلوب"}), 400

    with get_connection() as conn:
        cur = conn.cursor()
        if entity_type == "student":
            row = cur.execute(
                "SELECT student_id, COALESCE(student_name,''), COALESCE(email,'') FROM students WHERE student_id = ? LIMIT 1",
                (entity_id,),
            ).fetchone()
            if not row:
                return jsonify({"status": "error", "message": "student not found"}), 404
            sid = row[0]
            name = row[1] or ""
            email = (row[2] or "").strip()
            base = _arabic_to_ascii_slug(name.split()[0] if name.split() else name) or f"student{sid}"
            username = _unique_username(conn, base)
            return jsonify({"status": "ok", "username": username, "student_id": sid, "email": email})

        row = cur.execute(
            "SELECT id, COALESCE(name,''), COALESCE(email,'') FROM instructors WHERE id = ? LIMIT 1",
            (entity_id,),
        ).fetchone()
        if not row:
            return jsonify({"status": "error", "message": "instructor not found"}), 404
        iid = int(row[0])
        name = row[1] or ""
        email = (row[2] or "").strip()
        parts = name.split()
        first = parts[0] if parts else name
        base = _arabic_to_ascii_slug(first) or f"instructor{iid}"
        username = _unique_username(conn, base)
        return jsonify({"status": "ok", "username": username, "instructor_id": iid, "email": email})


@users_bp.route("/invite", methods=["POST"])
@role_required("admin_main")
def invite_user():
    """
    إنشاء/تحديث مستخدم مرتبط وإرسال رابط تعيين كلمة المرور بالبريد.
    body:
      - role: student|instructor|head_of_department
      - type: student|instructor
      - id: student_id أو instructor_id
      - username (اختياري)
    """
    data = request.get_json(force=True) or {}
    role = _normalize_role((data.get("role") or "").strip() or "student")
    entity_type = (data.get("type") or "").strip().lower()
    entity_id = (data.get("id") or "").strip()
    username_in = (data.get("username") or "").strip().lower() or None

    if role not in ("student", "instructor", "head_of_department"):
        return jsonify({"status": "error", "message": "role غير صحيح"}), 400
    if entity_type not in ("student", "instructor"):
        return jsonify({"status": "error", "message": "type must be student|instructor"}), 400
    if not entity_id:
        return jsonify({"status": "error", "message": "id مطلوب"}), 400

    with get_connection() as conn:
        cur = conn.cursor()
        student_id = None
        instructor_id = None
        email = ""
        display_name = ""

        if entity_type == "student":
            row = cur.execute(
                "SELECT student_id, COALESCE(student_name,''), COALESCE(email,'') FROM students WHERE student_id = ? LIMIT 1",
                (entity_id,),
            ).fetchone()
            if not row:
                return jsonify({"status": "error", "message": "student not found"}), 404
            student_id = (row[0] or "").strip()
            display_name = (row[1] or "").strip()
            email = (row[2] or "").strip()
            if role != "student":
                return jsonify({"status": "error", "message": "لا يمكن ربط type=student بدور غير student"}), 400
        else:
            row = cur.execute(
                "SELECT id, COALESCE(name,''), COALESCE(email,'') FROM instructors WHERE id = ? LIMIT 1",
                (entity_id,),
            ).fetchone()
            if not row:
                return jsonify({"status": "error", "message": "instructor not found"}), 404
            instructor_id = int(row[0])
            display_name = (row[1] or "").strip()
            email = (row[2] or "").strip()
            if role not in ("instructor", "head_of_department"):
                return jsonify({"status": "error", "message": "لا يمكن ربط type=instructor بدور غير instructor/head_of_department"}), 400

        if not email:
            return jsonify({"status": "error", "message": "يجب إدخال email في سجل الطالب/الأستاذ قبل إرسال الدعوة"}), 400

        if username_in:
            username = _unique_username(conn, username_in)
        else:
            first = display_name.split()[0] if display_name.split() else display_name
            base = _arabic_to_ascii_slug(first) or ("student" + student_id if student_id else f"instructor{instructor_id}")
            username = _unique_username(conn, base)

        # أنشئ/حدّث المستخدم بكلمة مرور عشوائية غير معروفة (سيتم تعيينها عبر الدعوة)
        pw_hash = hash_password(secrets.token_urlsafe(24))
        existing = cur.execute("SELECT username FROM users WHERE username = ? LIMIT 1", (username,)).fetchone()
        if existing:
            cur.execute(
                """
                UPDATE users
                SET password_hash = ?, role = ?, student_id = ?, instructor_id = ?, is_supervisor = COALESCE(is_supervisor,0), is_active = 1
                WHERE username = ?
                """,
                (pw_hash, role, student_id, instructor_id, username),
            )
        else:
            cur.execute(
                """
                INSERT INTO users (username, password_hash, role, student_id, instructor_id, is_supervisor, is_active)
                VALUES (?,?,?,?,?,0,1)
                """,
                (username, pw_hash, role, student_id, instructor_id),
            )

        token = secrets.token_urlsafe(32)
        token_hash = _hash_token(token)
        created_at = _now_iso()
        expires_at = (datetime.utcnow() + timedelta(hours=48)).replace(microsecond=0).isoformat() + "Z"
        cur.execute(
            """
            INSERT INTO user_invites (username, email, token_hash, created_at, expires_at, used_at)
            VALUES (?,?,?,?,?,NULL)
            """,
            (username, email, token_hash, created_at, expires_at),
        )
        conn.commit()

    # إرسال البريد (الرابط يعتمد على نفس الدومين)
    base_url = request.host_url.rstrip("/")
    invite_url = f"{base_url}/auth/invite/{token}"
    subject = "تفعيل حسابك في النظام"
    body = (
        f"مرحباً {display_name or username}\n\n"
        f"تم إنشاء حساب لك في النظام.\n"
        f"اسم المستخدم: {username}\n\n"
        f"لتعيين كلمة المرور لأول مرة، افتح الرابط التالي خلال 48 ساعة:\n{invite_url}\n\n"
        f"إذا لم تطلب هذا، تجاهل الرسالة.\n"
    )
    send_email(email, subject, body_text=body)

    return jsonify({"status": "ok", "username": username, "email": email}), 200


@users_bp.route("/invite/resend", methods=["POST"])
@role_required("admin_main")
def resend_invite():
    """
    إعادة إرسال دعوة تعيين كلمة المرور لمستخدم موجود.
    body:
      - username
    """
    data = request.get_json(force=True) or {}
    username = (data.get("username") or "").strip()
    if not username:
        return jsonify({"status": "error", "message": "username مطلوب"}), 400

    with get_connection() as conn:
        cur = conn.cursor()
        row = cur.execute(
            "SELECT username, role, student_id, instructor_id FROM users WHERE username = ? LIMIT 1",
            (username,),
        ).fetchone()
        if not row:
            return jsonify({"status": "error", "message": "المستخدم غير موجود"}), 404

        role = (row["role"] if hasattr(row, "keys") and "role" in row.keys() else row[1]) or ""
        student_id = (row["student_id"] if hasattr(row, "keys") and "student_id" in row.keys() else row[2]) or None
        instructor_id = (row["instructor_id"] if hasattr(row, "keys") and "instructor_id" in row.keys() else row[3]) or None

        email = ""
        display_name = ""
        try:
            if student_id:
                r2 = cur.execute(
                    "SELECT COALESCE(student_name,''), COALESCE(email,'') FROM students WHERE student_id = ? LIMIT 1",
                    (str(student_id).strip(),),
                ).fetchone()
                if r2:
                    display_name = (r2[0] if isinstance(r2, (list, tuple)) else r2[0]) or ""
                    email = (r2[1] if isinstance(r2, (list, tuple)) else r2[1]) or ""
            elif instructor_id not in (None, ""):
                r2 = cur.execute(
                    "SELECT COALESCE(name,''), COALESCE(email,'') FROM instructors WHERE id = ? LIMIT 1",
                    (int(instructor_id),),
                ).fetchone()
                if r2:
                    display_name = (r2[0] if isinstance(r2, (list, tuple)) else r2[0]) or ""
                    email = (r2[1] if isinstance(r2, (list, tuple)) else r2[1]) or ""
        except Exception:
            email = email or ""

        email = (email or "").strip()
        if not email:
            return jsonify({"status": "error", "message": "لا يوجد email مرتبط بهذا المستخدم"}), 400

        token = secrets.token_urlsafe(32)
        token_hash = _hash_token(token)
        created_at = _now_iso()
        expires_at = (datetime.utcnow() + timedelta(hours=48)).replace(microsecond=0).isoformat() + "Z"
        cur.execute(
            """
            INSERT INTO user_invites (username, email, token_hash, created_at, expires_at, used_at)
            VALUES (?,?,?,?,?,NULL)
            """,
            (username, email, token_hash, created_at, expires_at),
        )
        conn.commit()

    base_url = request.host_url.rstrip("/")
    invite_url = f"{base_url}/auth/invite/{token}"
    subject = "إعادة إرسال رابط تفعيل حسابك"
    body = (
        f"مرحباً {display_name or username}\n\n"
        f"اسم المستخدم: {username}\n"
        f"لتعيين/تغيير كلمة المرور عبر رابط التفعيل خلال 48 ساعة:\n{invite_url}\n\n"
        f"إذا لم تطلب هذا، تجاهل الرسالة.\n"
    )
    send_email(email, subject, body_text=body)

    return jsonify({"status": "ok", "username": username, "email": email, "role": role}), 200


@users_bp.route("/invite/status", methods=["GET"])
@role_required("admin_main", "head_of_department")
def invite_status():
    """
    عرض حالة الدعوات لمستخدم:
      - آخر الدعوات (الأحدث أولاً)
    query:
      - username
    """
    username = (request.args.get("username") or "").strip()
    if not username:
        return jsonify({"status": "error", "message": "username مطلوب"}), 400

    with get_connection() as conn:
        cur = conn.cursor()
        user_row = cur.execute(
            "SELECT username, role, student_id, instructor_id, COALESCE(is_active,1) AS is_active "
            "FROM users WHERE username = ? LIMIT 1",
            (username,),
        ).fetchone()
        if not user_row:
            return jsonify({"status": "error", "message": "المستخدم غير موجود"}), 404

        inv_rows = cur.execute(
            """
            SELECT id, email, created_at, expires_at, used_at
            FROM user_invites
            WHERE username = ?
            ORDER BY id DESC
            LIMIT 10
            """,
            (username,),
        ).fetchall()
        invites = []
        for r in inv_rows or []:
            invites.append(
                {
                    "id": r["id"] if hasattr(r, "keys") else r[0],
                    "email": r["email"] if hasattr(r, "keys") else r[1],
                    "created_at": r["created_at"] if hasattr(r, "keys") else r[2],
                    "expires_at": r["expires_at"] if hasattr(r, "keys") else r[3],
                    "used_at": r["used_at"] if hasattr(r, "keys") else r[4],
                }
            )

        return jsonify(
            {
                "status": "ok",
                "user": {
                    "username": user_row["username"] if hasattr(user_row, "keys") else user_row[0],
                    "role": user_row["role"] if hasattr(user_row, "keys") else user_row[1],
                    "student_id": user_row["student_id"] if hasattr(user_row, "keys") else user_row[2],
                    "instructor_id": user_row["instructor_id"] if hasattr(user_row, "keys") else user_row[3],
                    "is_active": int(user_row["is_active"] if hasattr(user_row, "keys") else user_row[4]),
                },
                "invites": invites,
            }
        )


@users_bp.route("/invite/revoke", methods=["POST"])
@role_required("admin_main")
def invite_revoke():
    """
    إلغاء جميع الدعوات غير المستخدمة لمستخدم (وضع used_at=now).
    body:
      - username
    """
    data = request.get_json(force=True) or {}
    username = (data.get("username") or "").strip()
    if not username:
        return jsonify({"status": "error", "message": "username مطلوب"}), 400

    now = _now_iso()
    with get_connection() as conn:
        cur = conn.cursor()
        exists = cur.execute(
            "SELECT 1 FROM users WHERE username = ? LIMIT 1",
            (username,),
        ).fetchone()
        if not exists:
            return jsonify({"status": "error", "message": "المستخدم غير موجود"}), 404

        cur.execute(
            "UPDATE user_invites SET used_at = ? WHERE username = ? AND (used_at IS NULL OR used_at = '')",
            (now, username),
        )
        revoked = cur.rowcount if cur.rowcount is not None else 0
        conn.commit()

    return jsonify({"status": "ok", "revoked": int(revoked)}), 200


@users_bp.route("/invite/cleanup", methods=["POST"])
@role_required("admin_main")
def invite_cleanup():
    """
    تنظيف الدعوات القديمة لتقليل تراكم البيانات.
    يحذف:
      - الدعوات المستخدمة/الملغاة (used_at موجود) أو المنتهية (expires_at < الآن)
    بشرط أن created_at أقدم من cutoff_days (افتراضي 30 يوم).
    body:
      - cutoff_days (اختياري)
    """
    data = request.get_json(force=True) or {}
    cutoff_days_raw = data.get("cutoff_days", 30)
    try:
        cutoff_days = int(cutoff_days_raw)
    except Exception:
        cutoff_days = 30
    if cutoff_days < 1:
        cutoff_days = 1
    if cutoff_days > 3650:
        cutoff_days = 3650

    now_iso = _now_iso()
    cutoff_iso = (datetime.utcnow() - timedelta(days=cutoff_days)).replace(microsecond=0).isoformat() + "Z"

    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            DELETE FROM user_invites
            WHERE COALESCE(created_at,'') <> ''
              AND created_at < ?
              AND (
                    (COALESCE(used_at,'') <> '')
                 OR (COALESCE(expires_at,'') <> '' AND expires_at < ?)
              )
            """,
            (cutoff_iso, now_iso),
        )
        deleted = cur.rowcount if cur.rowcount is not None else 0
        conn.commit()

    return jsonify({"status": "ok", "deleted": int(deleted), "cutoff_days": int(cutoff_days)}), 200

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

