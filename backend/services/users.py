import hashlib
import json
import logging
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from flask import Blueprint, request, jsonify, session

from backend.core.auth import role_required, hash_password
from backend.database.database import DB_FILE, is_postgresql
from backend.repositories import instructors_repo, students_repo, users_repo
from .utilities import get_connection
from .mailer import send_email

users_bp = Blueprint("users", __name__)
logger = logging.getLogger(__name__)

# أحرف عرض غير مرئية شائعة تُفسّر أسماء مستخدمين «فارغة» أو غير متطابقة في الواجهة
_ZERO_WIDTH = re.compile(r"[\u200b\u200c\u200d\u200e\u200f\ufeff\u202a-\u202e]+")


def _clean_username(s: str) -> str:
    return _ZERO_WIDTH.sub("", (s or "").strip())


_STORAGE_BRIEF_PG_AR = (
    "البيانات الحية على PostgreSQL فقط؛ تجاهل ملف mechanical.db المحلي إن وُجد "
    "(لا يعكس بيانات الخادم)."
)


def _admin_storage_meta(*, verbose_storage_hint: bool = False) -> dict:
    """معلومات تشخيصية لمسؤول النظام: أين تُخزَّن بيانات المستخدمين.

    عند ``verbose_storage_hint=False`` (الوضع الافتراضي لغير المطوّرين): نص موجز فقط.
    عند ``True`` (تعريف صريح عبر ``SHOW_USER_LIST_STORAGE_DIAGNOSTICS=1`` ودور admin_main): مسارات وتفاصيل للتشخيص.
    """
    if is_postgresql():
        sqlite_path = str(Path(DB_FILE).resolve())
        note_long = (
            "التطبيق يعمل على PostgreSQL: قائمة المستخدمين والحفظ من الخادم أعلاه. "
            "ملف mechanical.db في المشروع (إن وُجد) قديم/احتياطي ولا يعكس البيانات الحية طالما DATABASE_URL مفعّل."
        )
        try:
            from config import DATABASE_URL
            from sqlalchemy.engine.url import make_url

            u = make_url(DATABASE_URL)
            host = u.host or "localhost"
            dbn = (u.database or "").strip()
            storage_display = f"{host}/{dbn}" if dbn else host
        except Exception:
            storage_display = "PostgreSQL"

        base = {
            "backend": "postgresql",
            "storage_brief_ar": _STORAGE_BRIEF_PG_AR,
            "storage_verbose": bool(verbose_storage_hint),
        }
        if verbose_storage_hint:
            base["storage_display"] = storage_display
            base["sqlite_legacy_path"] = sqlite_path
            base["note_ar"] = note_long
        return base
    return {"backend": "sqlite", "storage_display": str(Path(DB_FILE).resolve())}


def _user_dict_from_row(row) -> Optional[dict]:
    if not row:
        return None
    return {
        "username": row[0],
        "role": row[1],
        "student_id": row[2],
        "instructor_id": row[3],
        "is_supervisor": int(row[4] or 0),
        "is_active": int(row[5] or 1),
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


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
    exists = cur.execute(
        "SELECT 1 FROM users WHERE lower(username) = lower(?) LIMIT 1",
        (base,),
    ).fetchone()
    if not exists:
        return base
    for i in range(2, 10000):
        cand = f"{base}{i}"
        exists = cur.execute(
            "SELECT 1 FROM users WHERE lower(username) = lower(?) LIMIT 1",
            (cand,),
        ).fetchone()
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
        try:
            conn.rollback()
        except Exception:
            pass
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
    invite_sent = False

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

        # بريد اختياري: إن وُجد يُنشأ token ويُرسل؛ وإلا يُنشأ الحساب فقط (كلمة عشوائية) ويُكمّل المسؤول يدوياً من «إضافة مباشرة»

        if username_in:
            username = _unique_username(conn, username_in)
        else:
            first = display_name.split()[0] if display_name.split() else display_name
            base = _arabic_to_ascii_slug(first) or ("student" + student_id if student_id else f"instructor{instructor_id}")
            username = _unique_username(conn, base)

        # أنشئ/حدّث المستخدم بكلمة مرور عشوائية غير معروفة (سيتم تعيينها عبر الدعوة)
        pw_hash = hash_password(secrets.token_urlsafe(24))
        try:
            existing = cur.execute(
                "SELECT username FROM users WHERE lower(username) = lower(?) LIMIT 1",
                (username,),
            ).fetchone()
            existing_username = (existing[0] if existing else None)
            if existing:
                cur.execute(
                    """
                    UPDATE users
                    SET password_hash = ?, role = ?, student_id = ?, instructor_id = ?, is_supervisor = COALESCE(is_supervisor,0), is_active = 1
                    WHERE username = ?
                    """,
                    (pw_hash, role, student_id, instructor_id, existing_username),
                )
                username = existing_username
            else:
                cur.execute(
                    """
                    INSERT INTO users (username, password_hash, role, student_id, instructor_id, is_supervisor, is_active)
                    VALUES (?,?,?,?,?,0,1)
                    """,
                    (username, pw_hash, role, student_id, instructor_id),
                )
        except Exception as write_err:
            conn.rollback()
            msg = str(write_err)
            if "idx_users_username_lower_unique" in msg or "duplicate key value violates unique constraint" in msg:
                return jsonify({"status": "error", "message": "اسم المستخدم مستخدم مسبقاً (مع تجاهل حالة الأحرف)."}), 409
            if "users_staff_requires_instructor_id_chk" in msg:
                return jsonify({"status": "error", "message": "instructor_id مطلوب لدور عضو هيئة التدريس/رئيس القسم"}), 400
            if "users_student_requires_student_id_chk" in msg:
                return jsonify({"status": "error", "message": "student_id مطلوب لدور الطالب"}), 400
            raise

        token = None
        if email:
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
            invite_sent = True
        conn.commit()

    if email and token:
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
        try:
            send_email(email, subject, body_text=body)
        except Exception:
            logger.exception("users/invite: فشل إرسال البريد (الحساب مُنشأ)")
            invite_sent = False

    notice = None
    if not email:
        notice = (
            "تم إنشاء الحساب بدون بريد في السجل؛ لم يُرسل رابط تلقائياً. "
            "عيّن كلمة المرور من قسم «إضافة / تعديل مستخدم» أو أضف البريد للسجل ثم استخدم «إعادة إرسال الدعوة»."
        )
    return jsonify(
        {
            "status": "ok",
            "username": username,
            "email": email or "",
            "invite_sent": bool(invite_sent),
            "notice": notice,
        }
    ), 200


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


def _current_actor() -> str:
    """اسم المستخدم الحالي (لـ audit)."""
    try:
        return (session.get("user") or session.get("username") or "").strip() or "system"
    except Exception:
        return "system"


def _is_pg_connection(conn) -> bool:
    """تحقق فعلي من نوع الاتصال الحالي (وليس فقط إعدادات البيئة)."""
    raw = getattr(conn, "_conn", conn)
    mod = (getattr(raw.__class__, "__module__", "") or "").lower()
    return "psycopg" in mod


def _normalize_user_links_for_role(
    role: str, student_id: Optional[str], instructor_id: Optional[int], is_supervisor: int
) -> tuple[Optional[str], Optional[int], int, Optional[str]]:
    """تطبيع وربط الحقول التابعة للدور قبل التخزين."""
    role_n = _normalize_role(role)
    sid = (student_id or "").strip() or None
    iid = instructor_id
    sup = int(bool(is_supervisor))

    if role_n == "student":
        if not sid:
            return sid, iid, sup, "student_id مطلوب لدور الطالب"
        return sid, None, 0, None

    if role_n in ("instructor", "head_of_department"):
        if iid is None:
            return sid, iid, sup, "instructor_id مطلوب لدور عضو هيئة التدريس/رئيس القسم"
        return None, iid, sup, None

    if role_n == "admin_main":
        return None, None, 0, None

    return sid, iid, sup, None


def _log_user_audit(conn, *, action: str, actor: str, username: str, before: Optional[dict], after: Optional[dict]) -> None:
    """تسجيل تغييرات المستخدمين في activity_log (best-effort)."""
    try:
        details = {
            "username": username,
            "before": before,
            "after": after,
        }
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO activity_log (ts, actor, action, details)
            VALUES (?, ?, ?, ?)
            """,
            (_now_iso(), actor, action, json.dumps(details, ensure_ascii=False)),
        )
    except Exception:
        logger.exception("users audit log write failed action=%s username=%s", action, username)


@users_bp.route("/list")
@role_required("admin_main", "head_of_department")
def list_users():
    """
    إرجاع قائمة المستخدمين (بدون كلمات المرور الصريحة).
    """
    with get_connection() as conn:
        items = users_repo.fetch_all_users_ordered(conn)
    role_norm = _normalize_role(_current_role())
    _diag_env = (os.environ.get("SHOW_USER_LIST_STORAGE_DIAGNOSTICS") or "").strip().lower()
    verbose_meta = _diag_env in ("1", "true", "yes") and role_norm == "admin_main"
    meta = _admin_storage_meta(verbose_storage_hint=verbose_meta)
    logger.info(
        "users/list count=%s backend=%s storage=%s verbose_meta=%s",
        len(items),
        meta.get("backend"),
        meta.get("storage_display") or meta.get("storage_brief_ar", "")[:80],
        verbose_meta,
    )
    resp = jsonify({"users": items, "total": len(items), "meta": meta})
    # يمنع عرض قائمة قديمة من ذاكرة التخزين المؤقت للمتصفح بعد إضافة مستخدم
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    return resp


@users_bp.route("/validation_report", methods=["GET"])
@role_required("admin_main", "head_of_department")
def users_validation_report():
    """تقرير فحص سلامة ربط المستخدمين حسب الدور (للتحقق اليدوي)."""
    with get_connection() as conn:
        rows = users_repo.fetch_all_users_ordered(conn)

    issues = []
    for u in rows:
        username = u["username"]
        role = _normalize_role(u["role"] or "")
        student_id = (u["student_id"] or "").strip()
        instructor_id = u["instructor_id"]
        is_supervisor = int(u["is_supervisor"] or 0)
        is_active = int(u["is_active"] or 1)

        row_issues = []
        if role == "student":
            if not student_id:
                row_issues.append("MISSING_STUDENT_ID_FOR_STUDENT")
            if instructor_id is not None:
                row_issues.append("UNEXPECTED_INSTRUCTOR_ID_FOR_STUDENT")
            if is_supervisor:
                row_issues.append("UNEXPECTED_SUPERVISOR_FLAG_FOR_STUDENT")
        elif role in ("instructor", "head_of_department"):
            if instructor_id is None:
                row_issues.append("MISSING_INSTRUCTOR_ID_FOR_STAFF")
            if student_id:
                row_issues.append("UNEXPECTED_STUDENT_ID_FOR_STAFF")
        elif role == "admin_main":
            if student_id:
                row_issues.append("UNEXPECTED_STUDENT_ID_FOR_ADMIN_MAIN")
            if instructor_id is not None:
                row_issues.append("UNEXPECTED_INSTRUCTOR_ID_FOR_ADMIN_MAIN")
            if is_supervisor:
                row_issues.append("UNEXPECTED_SUPERVISOR_FLAG_FOR_ADMIN_MAIN")
        else:
            row_issues.append("UNKNOWN_ROLE")

        if row_issues:
            issues.append(
                {
                    "username": username,
                    "role": role,
                    "student_id": student_id or None,
                    "instructor_id": instructor_id,
                    "is_supervisor": is_supervisor,
                    "is_active": is_active,
                    "issues": row_issues,
                }
            )

    return jsonify(
        {
            "status": "ok",
            "total_users": len(rows),
            "invalid_count": len(issues),
            "invalid_users": issues,
        }
    ), 200


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
    username = _clean_username(data.get("username") or "")
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
    student_id, instructor_id, is_supervisor, links_err = _normalize_user_links_for_role(
        role, student_id, instructor_id, is_supervisor
    )
    if links_err:
        return jsonify({"status": "error", "message": links_err}), 400

    actor_role = _normalize_role(_current_role())
    if actor_role != "admin_main":
        # رئيس القسم: لا يعيّن admin_main ولا يغيّر تفعيل الحساب ولا يغيّر كلمات المرور ولا ينشئ مستخدمين جدد
        if role == "admin_main":
            return jsonify({"status": "error", "message": "غير مسموح تعيين دور admin_main"}), 403
        if not is_active:
            return jsonify({"status": "error", "message": "غير مسموح تعطيل/تفعيل الحساب لرئيس القسم"}), 403
        if password:
            return jsonify({"status": "error", "message": "غير مسموح تغيير كلمة المرور لرئيس القسم"}), 403

    was_created = False
    user_out: Optional[dict] = None
    actor = _current_actor()
    affected_rows = 0
    try:
        with get_connection() as conn:
            # PostgreSQL pooled connections may occasionally return with a failed transaction state.
            # Clearing it defensively avoids "InFailedSqlTransaction" on the first write.
            try:
                conn.rollback()
            except Exception:
                pass
            cur = conn.cursor()
            if _is_pg_connection(conn):
                if role == "student" and student_id:
                    if not students_repo.exists_student_id(conn, student_id):
                        return jsonify({"status": "error", "message": f"الرقم الدراسي غير موجود: {student_id}"}), 400
                if role in ("instructor", "head_of_department") and instructor_id is not None:
                    if not instructors_repo.exists_instructor_id(conn, instructor_id):
                        return jsonify({"status": "error", "message": f"رقم عضو هيئة التدريس غير موجود: {instructor_id}"}), 400
            existing = users_repo.fetch_user_row_by_username_ci(conn, username)
            before_user = _user_dict_from_row(existing) if existing else None
            if existing:
                old_role = _normalize_role(existing[1] if existing else "")
                if old_role == "admin_main" and actor_role != "admin_main":
                    return jsonify({"status": "error", "message": "لا يمكن تعديل مستخدم admin_main إلا بواسطة admin_main"}), 403
                if actor_role != "admin_main":
                    # رئيس القسم يسمح فقط بتعديل الأساتذة: is_supervisor و instructor_id و role= instructor/ head_of_department
                    if old_role not in ("instructor", "head_of_department"):
                        return jsonify({"status": "error", "message": "رئيس القسم يمكنه تعديل الأساتذة فقط"}), 403
                    if role not in ("instructor", "head_of_department"):
                        return jsonify({"status": "error", "message": "لا يمكن تغيير دور الأستاذ إلى هذا الدور من قبل رئيس القسم"}), 403
            try:
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
                            affected_rows = cur.rowcount if cur.rowcount is not None else affected_rows
                        else:
                            cur.execute(
                                """
                                UPDATE users
                                SET role = ?, student_id = ?, instructor_id = ?, is_supervisor = ?, is_active = ?
                                WHERE username = ?
                                """,
                                (role, student_id, instructor_id, is_supervisor, is_active, username),
                            )
                            affected_rows = cur.rowcount if cur.rowcount is not None else affected_rows
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
                        affected_rows = cur.rowcount if cur.rowcount is not None else affected_rows
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
                    was_created = True
                    pw_hash = hash_password(password)
                    cur.execute(
                        """
                        INSERT INTO users (username, password_hash, role, student_id, instructor_id, is_supervisor, is_active)
                        VALUES (?,?,?,?,?,?,?)
                        """,
                        (username, pw_hash, role, student_id, instructor_id, is_supervisor, is_active),
                    )
                    affected_rows = cur.rowcount if cur.rowcount is not None else affected_rows
            except Exception as write_err:
                try:
                    conn.rollback()
                except Exception:
                    pass
                msg = str(write_err)
                if "idx_users_username_lower_unique" in msg or "duplicate key value violates unique constraint" in msg:
                    return jsonify({"status": "error", "message": "اسم المستخدم مستخدم مسبقاً (مع تجاهل حالة الأحرف)."}), 409
                if "users_staff_requires_instructor_id_chk" in msg:
                    return jsonify({"status": "error", "message": "instructor_id مطلوب لدور عضو هيئة التدريس/رئيس القسم"}), 400
                if "users_student_requires_student_id_chk" in msg:
                    return jsonify({"status": "error", "message": "student_id مطلوب لدور الطالب"}), 400
                if "violates foreign key constraint" in msg and "users_instructor_id_fkey" in msg:
                    return jsonify({"status": "error", "message": f"رقم عضو هيئة التدريس غير موجود: {instructor_id}"}), 400
                if "violates foreign key constraint" in msg and "users_student_id_fkey" in msg:
                    return jsonify({"status": "error", "message": f"الرقم الدراسي غير موجود: {student_id}"}), 400
                if "infailedsqltransaction" in msg.lower():
                    return jsonify({"status": "error", "message": "تعذر الحفظ بسبب معاملة قاعدة بيانات سابقة غير مكتملة. أعد المحاولة الآن."}), 409
                raise
            row = users_repo.fetch_user_row_after_write_ci(conn, username)
            user_out = _user_dict_from_row(row)
            if user_out is None:
                # تشخيص خاص: قد يوجد تعارض case-insensitive عند تفعيل فهرس lower(username)
                maybe_same_lower = users_repo.fetch_username_row_ci(conn, username)
                try:
                    conn.rollback()
                except Exception:
                    pass
                logger.error(
                    "users/add post-check failed: username=%s role=%s was_created=%s affected_rows=%s",
                    username,
                    role,
                    was_created,
                    affected_rows,
                )
                if maybe_same_lower:
                    return (
                        jsonify(
                            {
                                "status": "error",
                                "message": f"اسم المستخدم موجود بالفعل بحالة أحرف مختلفة: {maybe_same_lower[0]}",
                            }
                        ),
                        409,
                    )
                return jsonify({"status": "error", "message": "تعذر التحقق من حفظ المستخدم؛ لم يتم إيجاد السجل بعد العملية."}), 500
            _log_user_audit(
                conn,
                action="users.created" if was_created else "users.updated",
                actor=actor,
                username=username,
                before=before_user,
                after=user_out,
            )
            conn.commit()
    except Exception:
        logger.exception("users/add failed username=%s role=%s", username, role)
        return jsonify({"status": "error", "message": "فشل حفظ المستخدم في قاعدة البيانات"}), 500

    logger.info(
        "users/add action=%s username=%s",
        "created" if was_created else "updated",
        username,
    )
    return jsonify(
        {
            "status": "ok",
            "action": "created" if was_created else "updated",
            "user": user_out,
        }
    )


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
    actor = _current_actor()
    with get_connection() as conn:
        cur = conn.cursor()
        before = cur.execute(
            "SELECT username, role, student_id, instructor_id, "
            "COALESCE(is_supervisor,0) AS is_supervisor, COALESCE(is_active,1) AS is_active "
            "FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        before_user = _user_dict_from_row(before) if before else None
        cur.execute("DELETE FROM users WHERE username = ?", (username,))
        deleted = cur.rowcount if cur.rowcount is not None else 0
        if deleted:
            _log_user_audit(
                conn,
                action="users.deleted",
                actor=actor,
                username=username,
                before=before_user,
                after=None,
            )
        conn.commit()
    if not deleted:
        return jsonify({"status": "error", "message": "المستخدم غير موجود"}), 404
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
    actor = _current_actor()
    with get_connection() as conn:
        cur = conn.cursor()
        row = cur.execute(
            "SELECT username, role, student_id, instructor_id, COALESCE(is_supervisor,0), COALESCE(is_active,1) "
            "FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        if not row:
            return jsonify({"status": "error", "message": "المستخدم غير موجود"}), 404
        before_user = _user_dict_from_row(row)
        target_role = _normalize_role(row[1])
        if target_role == "admin_main" and actor_role != "admin_main":
            return jsonify({"status": "error", "message": "لا يمكن تعطيل admin_main إلا بواسطة admin_main"}), 403
        if target_role == "admin_main" and active == 0:
            cnt = cur.execute("SELECT COUNT(*) FROM users WHERE role = 'admin_main' AND COALESCE(is_active,1)=1").fetchone()[0]
            if cnt <= 1:
                return jsonify({"status": "error", "message": "لا يمكن تعطيل آخر مستخدم admin_main"}), 400
        cur.execute("UPDATE users SET is_active = ? WHERE username = ?", (active, username))
        after = cur.execute(
            "SELECT username, role, student_id, instructor_id, COALESCE(is_supervisor,0), COALESCE(is_active,1) "
            "FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        _log_user_audit(
            conn,
            action="users.toggle_active",
            actor=actor,
            username=username,
            before=before_user,
            after=_user_dict_from_row(after),
        )
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
    actor = _current_actor()
    with get_connection() as conn:
        cur = conn.cursor()
        row = cur.execute(
            "SELECT username, role, student_id, instructor_id, COALESCE(is_supervisor,0), COALESCE(is_active,1) "
            "FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        if not row:
            return jsonify({"status": "error", "message": "المستخدم غير موجود"}), 404
        before_user = _user_dict_from_row(row)
        role = _normalize_role(row[1])
        if role not in ("instructor", "head_of_department"):
            return jsonify({"status": "error", "message": "يمكن تعيين الإشراف للأستاذ/رئيس القسم فقط"}), 400
        cur.execute("UPDATE users SET is_supervisor = ? WHERE username = ?", (is_sup, username))
        after = cur.execute(
            "SELECT username, role, student_id, instructor_id, COALESCE(is_supervisor,0), COALESCE(is_active,1) "
            "FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        _log_user_audit(
            conn,
            action="users.set_supervisor",
            actor=actor,
            username=username,
            before=before_user,
            after=_user_dict_from_row(after),
        )
        conn.commit()
    return jsonify({"status": "ok", "message": "تم تحديث الإشراف الأكاديمي"}), 200


@users_bp.route("/audit_log", methods=["GET"])
@role_required("admin_main", "head_of_department")
def users_audit_log():
    """آخر سجلات تدقيق عمليات المستخدمين مع فلاتر بسيطة."""
    actor = (request.args.get("actor") or "").strip()
    username = (request.args.get("username") or "").strip()
    action = (request.args.get("action") or "").strip()
    try:
        limit = int(request.args.get("limit", 50))
    except (TypeError, ValueError):
        limit = 50
    limit = max(1, min(limit, 200))

    q = """
        SELECT id, ts, actor, action, details
        FROM activity_log
        WHERE action LIKE 'users.%%'
    """
    params = []
    if actor:
        q += " AND actor = ?"
        params.append(actor)
    if username:
        q += " AND details LIKE ?"
        params.append(f'%"{username}"%')
    if action:
        q += " AND action = ?"
        params.append(action)
    q += " ORDER BY id DESC LIMIT ?"
    params.append(limit)

    with get_connection() as conn:
        cur = conn.cursor()
        rows = cur.execute(q, params).fetchall()

    out = []
    for r in rows:
        details_raw = r[4] or ""
        details = None
        if details_raw:
            try:
                details = json.loads(details_raw)
            except Exception:
                details = {"raw": str(details_raw)}
        out.append(
            {
                "id": r[0],
                "ts": r[1],
                "actor": r[2],
                "action": r[3],
                "details": details,
            }
        )
    return jsonify({"status": "ok", "count": len(out), "items": out}), 200
