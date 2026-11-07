"""طلبات إنشاء حساب طالب — تسجيل ذاتي بموافقة رئيس القسم."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from flask import Blueprint, jsonify, render_template, request, session

from backend.core.auth import role_required
from backend.core.auth_password import hash_password
from backend.core.department_scope_policy import head_home_department_id
from backend.core.instructor_contact_policy import normalize_whatsapp_phone
from backend.database.database import is_postgresql
from backend.services.utilities import get_connection, log_activity

student_account_bp = Blueprint("student_account", __name__)
logger = logging.getLogger(__name__)

_STATUS_PENDING = "pending"
_STATUS_APPROVED = "approved"
_STATUS_REJECTED = "rejected"
_MIN_PASSWORD_LEN = 8
_NOTE_MAX = 500


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _ensure_table(conn) -> None:
    cur = conn.cursor()
    if is_postgresql():
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS student_account_requests (
                id BIGSERIAL PRIMARY KEY,
                student_id TEXT NOT NULL,
                student_name TEXT NOT NULL DEFAULT '',
                department_id BIGINT,
                email TEXT,
                stored_phone TEXT,
                whatsapp_phone TEXT NOT NULL,
                whatsapp_correction INTEGER NOT NULL DEFAULT 0,
                alternate_whatsapp TEXT,
                note TEXT,
                password_hash TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                requested_at TEXT NOT NULL,
                reviewed_at TEXT,
                reviewed_by TEXT,
                review_note TEXT,
                created_username TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_sar_student_status
            ON student_account_requests (student_id, status)
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_sar_dept_status
            ON student_account_requests (department_id, status)
            """
        )
    else:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS student_account_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id TEXT NOT NULL,
                student_name TEXT NOT NULL DEFAULT '',
                department_id INTEGER,
                email TEXT,
                stored_phone TEXT,
                whatsapp_phone TEXT NOT NULL,
                whatsapp_correction INTEGER NOT NULL DEFAULT 0,
                alternate_whatsapp TEXT,
                note TEXT,
                password_hash TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                requested_at TEXT NOT NULL,
                reviewed_at TEXT,
                reviewed_by TEXT,
                review_note TEXT,
                created_username TEXT
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_sar_student_status ON student_account_requests (student_id, status)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_sar_dept_status ON student_account_requests (department_id, status)"
        )
    conn.commit()


def _fetch_student(conn, student_id: str):
    cur = conn.cursor()
    row = cur.execute(
        """
        SELECT s.student_id,
               COALESCE(s.student_name, '') AS student_name,
               s.department_id,
               COALESCE(s.email, '') AS email,
               COALESCE(s.phone, '') AS phone,
               COALESCE(d.name_ar, '') AS department_name_ar,
               COALESCE(d.code, '') AS department_code
        FROM students s
        LEFT JOIN departments d ON d.id = s.department_id
        WHERE s.student_id = ?
        LIMIT 1
        """,
        (student_id,),
    ).fetchone()
    if not row:
        return None
    if hasattr(row, "keys"):
        return dict(row)
    return {
        "student_id": row[0],
        "student_name": row[1],
        "department_id": row[2],
        "email": row[3],
        "phone": row[4],
        "department_name_ar": row[5],
        "department_code": row[6],
    }


def _active_user_for_student(conn, student_id: str) -> dict | None:
    cur = conn.cursor()
    row = cur.execute(
        """
        SELECT username, role, COALESCE(is_active, 1) AS is_active
        FROM users
        WHERE student_id = ? AND lower(COALESCE(role,'')) = 'student'
        ORDER BY COALESCE(is_active, 1) DESC
        LIMIT 1
        """,
        (student_id,),
    ).fetchone()
    if not row:
        return None
    if hasattr(row, "keys"):
        return {
            "username": row["username"],
            "role": row["role"],
            "is_active": int(row["is_active"] or 0),
        }
    return {"username": row[0], "role": row[1], "is_active": int(row[2] or 0)}


def _pending_request(conn, student_id: str):
    cur = conn.cursor()
    return cur.execute(
        """
        SELECT id, requested_at FROM student_account_requests
        WHERE student_id = ? AND status = ?
        ORDER BY id DESC LIMIT 1
        """,
        (student_id, _STATUS_PENDING),
    ).fetchone()


def _stored_whatsapp_digits(phone_raw: str | None) -> str | None:
    return normalize_whatsapp_phone(phone_raw or "")


@student_account_bp.route("/register", methods=["GET"])
def register_page():
    return render_template("student_account_register.html")


@student_account_bp.route("/approvals", methods=["GET"])
@role_required("head_of_department", "admin_main", "system_admin", "college_dean")
def approvals_page():
    return render_template("student_account_approvals.html")


@student_account_bp.route("/lookup", methods=["GET"])
def lookup_student():
    student_id = (request.args.get("student_id") or "").strip()
    if not student_id:
        return jsonify({"status": "error", "message": "الرقم الدراسي مطلوب"}), 400
    with get_connection() as conn:
        _ensure_table(conn)
        st = _fetch_student(conn, student_id)
        if not st:
            return jsonify({
                "status": "error",
                "code": "NOT_FOUND",
                "message": "الرقم الدراسي غير مسجّل في الكلية",
            }), 404
        existing = _active_user_for_student(conn, student_id)
        if existing and int(existing.get("is_active") or 0) == 1:
            return jsonify({
                "status": "error",
                "code": "HAS_ACCOUNT",
                "message": "لديك حساب مسبقاً — استخدم تسجيل الدخول أو استعادة كلمة المرور",
                "username": existing.get("username"),
            }), 409
        if existing and int(existing.get("is_active") or 0) == 0:
            return jsonify({
                "status": "error",
                "code": "ACCOUNT_DISABLED",
                "message": "حسابك موجود لكنه معطّل — راجع رئيس القسم أو إدارة المستخدمين لإعادة التفعيل",
            }), 409
        pending = _pending_request(conn, student_id)
        if pending:
            return jsonify({
                "status": "error",
                "code": "PENDING",
                "message": "طلبك قيد المراجعة لدى رئيس القسم",
            }), 409
        stored_wa = _stored_whatsapp_digits(st.get("phone"))
        return jsonify({
            "status": "ok",
            "student_id": st["student_id"],
            "student_name": st.get("student_name") or "",
            "department_id": st.get("department_id"),
            "department_name_ar": st.get("department_name_ar") or "",
            "department_code": st.get("department_code") or "",
            "email_stored": (st.get("email") or "").strip(),
            "whatsapp_stored": stored_wa,
            "whatsapp_required": stored_wa is None,
        })


@student_account_bp.route("/request", methods=["POST"])
def submit_request():
    data = request.get_json(force=True) or {}
    student_id = (data.get("student_id") or "").strip()
    password = data.get("password") or ""
    password2 = data.get("password_confirm") or data.get("password2") or ""
    email = (data.get("email") or "").strip() or None
    note = (data.get("note") or "").strip() or None
    whatsapp_correction = data.get("whatsapp_correction") in (True, 1, "1", "true", "True", "yes")
    whatsapp_in = data.get("whatsapp_phone")
    alternate_in = data.get("alternate_whatsapp")

    if not student_id:
        return jsonify({"status": "error", "message": "الرقم الدراسي مطلوب"}), 400
    if not isinstance(password, str) or len(password) < _MIN_PASSWORD_LEN:
        return jsonify({
            "status": "error",
            "message": f"كلمة المرور يجب أن تكون {_MIN_PASSWORD_LEN} أحرف على الأقل",
        }), 400
    if password != password2:
        return jsonify({"status": "error", "message": "تأكيد كلمة المرور غير مطابق"}), 400
    if note and len(note) > _NOTE_MAX:
        return jsonify({"status": "error", "message": "الملاحظة طويلة جداً"}), 400
    if email and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return jsonify({"status": "error", "message": "البريد الإلكتروني غير صالح"}), 400

    with get_connection() as conn:
        _ensure_table(conn)
        st = _fetch_student(conn, student_id)
        if not st:
            return jsonify({"status": "error", "message": "الرقم الدراسي غير مسجّل في الكلية"}), 404
        if not st.get("department_id"):
            return jsonify({
                "status": "error",
                "message": "لا يمكن إرسال الطلب: الطالب غير مربوط بقسم — راجع شؤون الطلبة",
            }), 400
        existing = _active_user_for_student(conn, student_id)
        if existing and int(existing.get("is_active") or 0) == 1:
            return jsonify({
                "status": "error",
                "code": "HAS_ACCOUNT",
                "message": "لديك حساب مسبقاً — استخدم تسجيل الدخول",
            }), 409
        if existing and int(existing.get("is_active") or 0) == 0:
            return jsonify({
                "status": "error",
                "code": "ACCOUNT_DISABLED",
                "message": "حسابك موجود لكنه معطّل — راجع رئيس القسم",
            }), 409
        if _pending_request(conn, student_id):
            return jsonify({
                "status": "error",
                "code": "PENDING",
                "message": "طلبك قيد المراجعة لدى رئيس القسم",
            }), 409

        stored_wa = _stored_whatsapp_digits(st.get("phone"))
        alternate_wa = None
        if stored_wa is None:
            wa = normalize_whatsapp_phone(whatsapp_in)
            if not wa:
                return jsonify({
                    "status": "error",
                    "message": "رقم الواتساب إلزامي للتسجيل (مثال: 0912345678 أو 2189…)",
                }), 400
            final_wa = wa
            whatsapp_correction = False
        else:
            final_wa = stored_wa
            if whatsapp_correction:
                alternate_wa = normalize_whatsapp_phone(alternate_in)
                if not alternate_wa:
                    return jsonify({
                        "status": "error",
                        "message": "أدخل رقم واتساب بديل صالح عند تصحيح الرقم",
                    }), 400
                if not note:
                    return jsonify({
                        "status": "error",
                        "message": "أضف ملاحظة قصيرة توضح أن الرقم المخزّن غير صحيح",
                    }), 400
                final_wa = alternate_wa
            else:
                whatsapp_correction = False

        if not email:
            email = (st.get("email") or "").strip() or None

        pw_hash = hash_password(password)
        cur = conn.cursor()
        params = (
            student_id,
            st.get("student_name") or "",
            st.get("department_id"),
            email,
            stored_wa,
            final_wa,
            1 if whatsapp_correction else 0,
            alternate_wa,
            note,
            pw_hash,
            _STATUS_PENDING,
            _now_iso(),
        )
        if is_postgresql():
            row = cur.execute(
                """
                INSERT INTO student_account_requests (
                    student_id, student_name, department_id, email, stored_phone,
                    whatsapp_phone, whatsapp_correction, alternate_whatsapp, note,
                    password_hash, status, requested_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                RETURNING id
                """,
                params,
            ).fetchone()
            req_id = int(row[0] if row else 0)
        else:
            cur.execute(
                """
                INSERT INTO student_account_requests (
                    student_id, student_name, department_id, email, stored_phone,
                    whatsapp_phone, whatsapp_correction, alternate_whatsapp, note,
                    password_hash, status, requested_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                params,
            )
            req_id = int(cur.lastrowid or 0)
        conn.commit()
        log_activity(
            action="student_account.request_created",
            details=f"id={req_id}; student_id={student_id}; dept={st.get('department_id')}",
            actor=student_id,
        )

    return jsonify({
        "status": "ok",
        "id": req_id,
        "message": "تم إرسال طلبك إلى رئيس القسم للمراجعة",
    }), 200


_REQ_SELECT = """
    id, student_id, student_name, department_id, email, stored_phone,
    whatsapp_phone, whatsapp_correction, alternate_whatsapp, note,
    status, requested_at, reviewed_at, reviewed_by, review_note, created_username
"""


def _row_to_request(r) -> dict:
    if hasattr(r, "keys"):
        d = dict(r)
        return {
            "id": d.get("id"),
            "student_id": d.get("student_id"),
            "student_name": d.get("student_name"),
            "department_id": d.get("department_id"),
            "email": d.get("email"),
            "stored_phone": d.get("stored_phone"),
            "whatsapp_phone": d.get("whatsapp_phone"),
            "whatsapp_correction": int(d.get("whatsapp_correction") or 0),
            "alternate_whatsapp": d.get("alternate_whatsapp"),
            "note": d.get("note"),
            "status": d.get("status"),
            "requested_at": d.get("requested_at"),
            "reviewed_at": d.get("reviewed_at"),
            "reviewed_by": d.get("reviewed_by"),
            "review_note": d.get("review_note"),
            "created_username": d.get("created_username"),
        }
    return {
        "id": r[0],
        "student_id": r[1],
        "student_name": r[2],
        "department_id": r[3],
        "email": r[4],
        "stored_phone": r[5],
        "whatsapp_phone": r[6],
        "whatsapp_correction": int(r[7] or 0),
        "alternate_whatsapp": r[8],
        "note": r[9],
        "status": r[10],
        "requested_at": r[11],
        "reviewed_at": r[12],
        "reviewed_by": r[13],
        "review_note": r[14],
        "created_username": r[15],
    }


@student_account_bp.route("/requests", methods=["GET"])
@role_required("head_of_department", "admin_main", "system_admin", "college_dean")
def list_requests():
    status = (request.args.get("status") or _STATUS_PENDING).strip().lower()
    if status not in (_STATUS_PENDING, _STATUS_APPROVED, _STATUS_REJECTED, "all"):
        status = _STATUS_PENDING
    actor = (session.get("user") or "").strip()
    role = (session.get("user_role") or "").strip().lower()
    with get_connection() as conn:
        _ensure_table(conn)
        cur = conn.cursor()
        params: list = []
        where = ["1=1"]
        if status != "all":
            where.append("status = ?")
            params.append(status)
        if role == "head_of_department":
            dep_id = head_home_department_id(conn, actor)
            if dep_id is None:
                return jsonify({"status": "ok", "items": [], "message": "لا يوجد قسم مرتبط بحسابك"}), 200
            where.append("department_id = ?")
            params.append(int(dep_id))
        sql = f"""
            SELECT {_REQ_SELECT}
            FROM student_account_requests
            WHERE {' AND '.join(where)}
            ORDER BY id DESC
            LIMIT 200
        """
        rows = cur.execute(sql, tuple(params)).fetchall()
        items = [_row_to_request(r) for r in rows]
    return jsonify({"status": "ok", "items": items})


@student_account_bp.route("/requests/<int:req_id>/decide", methods=["POST"])
@role_required("head_of_department", "admin_main", "system_admin", "college_dean")
def decide_request(req_id: int):
    data = request.get_json(force=True) or {}
    decision = (data.get("decision") or data.get("status") or "").strip().lower()
    review_note = (data.get("review_note") or data.get("note") or "").strip() or None
    if decision not in ("approve", "reject", _STATUS_APPROVED, _STATUS_REJECTED):
        return jsonify({"status": "error", "message": "decision يجب أن يكون approve أو reject"}), 400
    approve = decision in ("approve", _STATUS_APPROVED)
    actor = (session.get("user") or "").strip() or "system"
    role = (session.get("user_role") or "").strip().lower()

    with get_connection() as conn:
        _ensure_table(conn)
        cur = conn.cursor()
        row = cur.execute(
            f"""
            SELECT {_REQ_SELECT}, password_hash
            FROM student_account_requests WHERE id = ? LIMIT 1
            """,
            (req_id,),
        ).fetchone()
        if not row:
            return jsonify({"status": "error", "message": "الطلب غير موجود"}), 404
        item = _row_to_request(row)
        if hasattr(row, "keys"):
            pw_hash = row["password_hash"]
        else:
            pw_hash = row[16]
        if item.get("status") != _STATUS_PENDING:
            return jsonify({"status": "error", "message": "تمت معالجة هذا الطلب مسبقاً"}), 409

        if role == "head_of_department":
            dep_id = head_home_department_id(conn, actor)
            if dep_id is None or int(item.get("department_id") or 0) != int(dep_id):
                return jsonify({"status": "error", "message": "الطلب خارج نطاق قسمك"}), 403

        if not approve:
            cur.execute(
                """
                UPDATE student_account_requests
                SET status = ?, reviewed_at = ?, reviewed_by = ?, review_note = ?, password_hash = ''
                WHERE id = ?
                """,
                (_STATUS_REJECTED, _now_iso(), actor, review_note, req_id),
            )
            conn.commit()
            log_activity(
                action="student_account.request_rejected",
                details=f"id={req_id}; student_id={item.get('student_id')}",
                actor=actor,
            )
            return jsonify({"status": "ok", "message": "تم رفض الطلب"}), 200

        student_id = (item.get("student_id") or "").strip()
        existing = _active_user_for_student(conn, student_id)
        if existing and int(existing.get("is_active") or 0) == 1:
            cur.execute(
                """
                UPDATE student_account_requests
                SET status = ?, reviewed_at = ?, reviewed_by = ?, review_note = ?, password_hash = ''
                WHERE id = ?
                """,
                (_STATUS_REJECTED, _now_iso(), actor, "يوجد حساب نشط مسبقاً", req_id),
            )
            conn.commit()
            return jsonify({
                "status": "error",
                "message": "يوجد حساب نشط لهذا الرقم — رُفض الطلب تلقائياً",
            }), 409

        username = student_id
        clash = cur.execute(
            "SELECT 1 FROM users WHERE lower(username) = lower(?) LIMIT 1",
            (username,),
        ).fetchone()
        if clash:
            username = f"s{student_id}"
            clash2 = cur.execute(
                "SELECT 1 FROM users WHERE lower(username) = lower(?) LIMIT 1",
                (username,),
            ).fetchone()
            if clash2:
                return jsonify({
                    "status": "error",
                    "message": "تعذر اختيار اسم مستخدم فريد — راجع إدارة المستخدمين",
                }), 409

        dept_id = item.get("department_id")
        email = item.get("email")
        wa = item.get("whatsapp_phone")
        try:
            cur.execute(
                """
                INSERT INTO users (
                    username, password_hash, role, student_id, instructor_id,
                    is_supervisor, is_active, department_id
                ) VALUES (?, ?, 'student', ?, NULL, 0, 1, ?)
                """,
                (username, pw_hash, student_id, dept_id),
            )
        except Exception as exc:
            logger.exception("approve student account insert failed")
            return jsonify({"status": "error", "message": f"فشل إنشاء الحساب: {exc}"}), 500

        # تحديث تواصل الطالب إن لزم
        try:
            if email:
                cur.execute(
                    """
                    UPDATE students SET email = COALESCE(NULLIF(email,''), ?)
                    WHERE student_id = ?
                    """,
                    (email, student_id),
                )
            if wa:
                # عند التصحيح أو رقم جديد: اعتمد الرقم النهائي
                if int(item.get("whatsapp_correction") or 0) == 1 or not (item.get("stored_phone") or "").strip():
                    cur.execute(
                        "UPDATE students SET phone = ? WHERE student_id = ?",
                        (wa, student_id),
                    )
                else:
                    cur.execute(
                        """
                        UPDATE students SET phone = COALESCE(NULLIF(phone,''), ?)
                        WHERE student_id = ?
                        """,
                        (wa, student_id),
                    )
        except Exception:
            logger.exception("student contact update after approve failed student_id=%s", student_id)

        cur.execute(
            """
            UPDATE student_account_requests
            SET status = ?, reviewed_at = ?, reviewed_by = ?, review_note = ?,
                created_username = ?, password_hash = ''
            WHERE id = ?
            """,
            (_STATUS_APPROVED, _now_iso(), actor, review_note, username, req_id),
        )
        conn.commit()
        log_activity(
            action="student_account.request_approved",
            details=f"id={req_id}; student_id={student_id}; username={username}",
            actor=actor,
        )

    return jsonify({
        "status": "ok",
        "message": "تمت الموافقة وإنشاء الحساب",
        "username": username,
    }), 200
