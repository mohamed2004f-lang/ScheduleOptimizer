from __future__ import annotations

from datetime import datetime

from flask import Blueprint, jsonify, request, session

from backend.core.auth import role_required
from backend.core.department_scope_policy import head_home_department_id
from backend.database.database import table_exists
from .utilities import get_connection, get_current_term, log_activity


department_policies_bp = Blueprint("department_policies", __name__)

_ALLOWED_PLAN_CODES = {"150", "155"}
_ALLOWED_STATUS = {"draft", "pending_approval", "approved", "rejected"}


def _now_iso() -> str:
    return datetime.utcnow().isoformat()


def _actor() -> str:
    return (session.get("user") or session.get("username") or "").strip()


def _role() -> str:
    return (session.get("user_role") or "").strip()


def _ensure_table(conn) -> None:
    if table_exists(conn, "department_graduation_policies"):
        return
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS department_graduation_policies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            department_id INTEGER NOT NULL,
            plan_code TEXT NOT NULL,
            min_total_units INTEGER NOT NULL DEFAULT 0,
            effective_from_term TEXT DEFAULT '',
            effective_from_year TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'draft',
            submitted_at TEXT,
            approved_at TEXT,
            rejected_at TEXT,
            rejection_reason TEXT DEFAULT '',
            created_by TEXT DEFAULT '',
            approved_by TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            CHECK (plan_code IN ('150','155')),
            CHECK (status IN ('draft','pending_approval','approved','rejected'))
        )
        """
    )
    conn.commit()


def _term_order(term_name: str) -> int:
    t = (term_name or "").strip()
    if t == "ربيع":
        return 1
    if t == "صيف":
        return 2
    if t == "خريف":
        return 3
    return 0


def _parse_year_token(y: str) -> int:
    s = (y or "").strip()
    if not s:
        return -1
    try:
        return int(s)
    except Exception:
        pass
    for sep in ("/", "-", " "):
        if sep in s:
            parts = [p for p in s.split(sep) if p.strip()]
            for p in parts:
                try:
                    return int(p.strip())
                except Exception:
                    continue
    return -1


def _is_effective_now(row: dict, current_term: str, current_year: str) -> bool:
    eff_term = (row.get("effective_from_term") or "").strip()
    eff_year = (row.get("effective_from_year") or "").strip()
    if not eff_term and not eff_year:
        return True
    cy = _parse_year_token(current_year)
    ey = _parse_year_token(eff_year)
    if ey >= 0 and cy < 0:
        return False
    if ey >= 0 and cy >= 0:
        if ey < cy:
            return True
        if ey > cy:
            return False
    # same year (or unknown year) => compare term order if both available
    if eff_term and current_term:
        return _term_order(eff_term) <= _term_order(current_term)
    if eff_term and not current_term:
        return False
    return True


def _head_department_id_or_403(conn) -> int | None:
    dep_id = head_home_department_id(conn, _actor())
    if dep_id is None:
        return None
    return int(dep_id)


@department_policies_bp.route("/department_policies/head/list", methods=["GET"])
@role_required("head_of_department")
def head_list_policies():
    with get_connection() as conn:
        _ensure_table(conn)
        dep_id = _head_department_id_or_403(conn)
        if dep_id is None:
            return jsonify({"status": "error", "message": "لا يوجد قسم مرتبط بحساب رئيس القسم"}), 403
        cur = conn.cursor()
        rows = cur.execute(
            """
            SELECT *
            FROM department_graduation_policies
            WHERE department_id = ?
            ORDER BY id DESC
            """,
            (dep_id,),
        ).fetchall()
        items = [dict(r) for r in rows]
    return jsonify({"status": "ok", "department_id": dep_id, "items": items}), 200


@department_policies_bp.route("/department_policies/head/propose", methods=["POST"])
@role_required("head_of_department")
def head_propose_policy():
    body = request.get_json(force=True) or {}
    plan_code = (body.get("plan_code") or "").strip()
    if plan_code not in _ALLOWED_PLAN_CODES:
        return jsonify({"status": "error", "message": "plan_code يجب أن يكون 150 أو 155"}), 400
    try:
        min_total_units = int(body.get("min_total_units") or 0)
    except (TypeError, ValueError):
        min_total_units = 0
    min_total_units = max(0, min_total_units)
    effective_from_term = (body.get("effective_from_term") or "").strip()
    effective_from_year = (body.get("effective_from_year") or "").strip()
    notes = (body.get("notes") or "").strip()

    with get_connection() as conn:
        _ensure_table(conn)
        dep_id = _head_department_id_or_403(conn)
        if dep_id is None:
            return jsonify({"status": "error", "message": "لا يوجد قسم مرتبط بحساب رئيس القسم"}), 403
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO department_graduation_policies
            (department_id, plan_code, min_total_units, effective_from_term, effective_from_year, notes, status, created_by, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 'draft', ?, ?, ?)
            """,
            (
                dep_id,
                plan_code,
                min_total_units,
                effective_from_term,
                effective_from_year,
                notes,
                _actor(),
                _now_iso(),
                _now_iso(),
            ),
        )
        policy_id = int(cur.lastrowid or 0)
        conn.commit()
        log_activity(
            action="dept_policy_proposed",
            details=(
                f"policy_id={policy_id}; department_id={dep_id}; plan_code={plan_code}; "
                f"min_total_units={min_total_units}; effective_from={effective_from_term} {effective_from_year}"
            ),
            actor=_actor(),
        )
    return jsonify({"status": "ok", "id": policy_id, "department_id": dep_id}), 200


@department_policies_bp.route("/department_policies/head/submit/<int:policy_id>", methods=["POST"])
@role_required("head_of_department")
def head_submit_policy(policy_id: int):
    with get_connection() as conn:
        _ensure_table(conn)
        dep_id = _head_department_id_or_403(conn)
        if dep_id is None:
            return jsonify({"status": "error", "message": "لا يوجد قسم مرتبط بحساب رئيس القسم"}), 403
        cur = conn.cursor()
        row = cur.execute(
            """
            SELECT id, status
            FROM department_graduation_policies
            WHERE id = ? AND department_id = ?
            LIMIT 1
            """,
            (policy_id, dep_id),
        ).fetchone()
        if not row:
            return jsonify({"status": "error", "message": "السياسة غير موجودة ضمن قسمك"}), 404
        st = (row["status"] if hasattr(row, "keys") else row[1]) or ""
        if st not in ("draft", "rejected"):
            return jsonify({"status": "error", "message": "يمكن إرسال مسودة أو سياسة مرفوضة فقط"}), 400
        cur.execute(
            """
            UPDATE department_graduation_policies
            SET status = 'pending_approval', submitted_at = ?, updated_at = ?, rejection_reason = ''
            WHERE id = ?
            """,
            (_now_iso(), _now_iso(), policy_id),
        )
        conn.commit()
        log_activity(
            action="dept_policy_submitted",
            details=f"policy_id={policy_id}; department_id={dep_id}",
            actor=_actor(),
        )
    return jsonify({"status": "ok", "id": policy_id}), 200


@department_policies_bp.route("/department_policies/admin/pending", methods=["GET"])
@role_required("admin_main", "system_admin", "college_dean")
def admin_list_pending():
    with get_connection() as conn:
        _ensure_table(conn)
        cur = conn.cursor()
        rows = cur.execute(
            """
            SELECT p.*, d.code AS department_code, COALESCE(d.name_ar,'') AS department_name_ar
            FROM department_graduation_policies p
            LEFT JOIN departments d ON d.id = p.department_id
            WHERE p.status = 'pending_approval'
            ORDER BY p.id DESC
            """
        ).fetchall()
        items = [dict(r) for r in rows]
    return jsonify({"status": "ok", "items": items}), 200


@department_policies_bp.route("/department_policies/admin/approve/<int:policy_id>", methods=["POST"])
@role_required("admin_main", "system_admin", "college_dean")
def admin_approve(policy_id: int):
    body = request.get_json(force=True) or {}
    activate_now = bool(body.get("activate_now"))
    with get_connection() as conn:
        _ensure_table(conn)
        cur = conn.cursor()
        row = cur.execute(
            """
            SELECT id, department_id, plan_code, min_total_units, status
            FROM department_graduation_policies
            WHERE id = ?
            LIMIT 1
            """,
            (policy_id,),
        ).fetchone()
        if not row:
            return jsonify({"status": "error", "message": "السياسة غير موجودة"}), 404
        st = (row["status"] if hasattr(row, "keys") else row[4]) or ""
        if st != "pending_approval":
            return jsonify({"status": "error", "message": "لا يمكن اعتماد سياسة ليست قيد المراجعة"}), 400
        dep_id = int((row["department_id"] if hasattr(row, "keys") else row[1]) or 0)
        plan_code = (row["plan_code"] if hasattr(row, "keys") else row[2]) or ""
        min_units = int((row["min_total_units"] if hasattr(row, "keys") else row[3]) or 0)
        now = _now_iso()
        eff_term = None
        eff_year = None
        if activate_now:
            term_name, term_year = get_current_term(conn=conn)
            eff_term = (term_name or "").strip()
            eff_year = str(term_year or "").strip()
        cur.execute(
            """
            UPDATE department_graduation_policies
            SET status = 'approved',
                approved_at = ?,
                approved_by = ?,
                updated_at = ?,
                rejection_reason = '',
                effective_from_term = COALESCE(?, effective_from_term),
                effective_from_year = COALESCE(?, effective_from_year)
            WHERE id = ?
            """,
            (now, _actor(), now, eff_term, eff_year, policy_id),
        )
        # نجعل الاعتماد الأخير لهذا القسم هو المرجع ونؤرشف بقية المعتمدة السابقة.
        cur.execute(
            """
            UPDATE department_graduation_policies
            SET status = 'rejected', rejected_at = ?, rejection_reason = 'Superseded by newer approved policy', updated_at = ?
            WHERE department_id = ?
              AND id <> ?
              AND status = 'approved'
            """,
            (now, now, dep_id, policy_id),
        )
        conn.commit()
        log_activity(
            action="dept_policy_approved",
            details=(
                f"policy_id={policy_id}; department_id={dep_id}; plan_code={plan_code}; "
                f"min_total_units={min_units}; activate_now={1 if activate_now else 0}; "
                f"effective_from={eff_term or ''} {eff_year or ''}"
            ),
            actor=_actor(),
        )
    return jsonify({"status": "ok", "id": policy_id}), 200


@department_policies_bp.route("/department_policies/admin/reject/<int:policy_id>", methods=["POST"])
@role_required("admin_main", "system_admin", "college_dean")
def admin_reject(policy_id: int):
    body = request.get_json(force=True) or {}
    reason = (body.get("reason") or "").strip()
    with get_connection() as conn:
        _ensure_table(conn)
        cur = conn.cursor()
        row = cur.execute(
            """
            SELECT id, department_id, status
            FROM department_graduation_policies
            WHERE id = ?
            LIMIT 1
            """,
            (policy_id,),
        ).fetchone()
        if not row:
            return jsonify({"status": "error", "message": "السياسة غير موجودة"}), 404
        st = (row["status"] if hasattr(row, "keys") else row[2]) or ""
        if st != "pending_approval":
            return jsonify({"status": "error", "message": "لا يمكن رفض سياسة ليست قيد المراجعة"}), 400
        dep_id = int((row["department_id"] if hasattr(row, "keys") else row[1]) or 0)
        now = _now_iso()
        cur.execute(
            """
            UPDATE department_graduation_policies
            SET status = 'rejected', rejected_at = ?, rejection_reason = ?, approved_by = ?, updated_at = ?
            WHERE id = ?
            """,
            (now, reason, _actor(), now, policy_id),
        )
        conn.commit()
        log_activity(
            action="dept_policy_rejected",
            details=f"policy_id={policy_id}; department_id={dep_id}; reason={reason}",
            actor=_actor(),
        )
    return jsonify({"status": "ok", "id": policy_id}), 200


@department_policies_bp.route("/department_policies/active/<int:department_id>", methods=["GET"])
@role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department")
def get_active_policy(department_id: int):
    with get_connection() as conn:
        _ensure_table(conn)
        role = _role()
        actor = _actor()
        if role == "head_of_department":
            own_dep = _head_department_id_or_403(conn)
            if own_dep is None or int(own_dep) != int(department_id):
                return jsonify({"status": "error", "message": "غير مسموح بالوصول لسياسات قسم آخر"}), 403

        cur = conn.cursor()
        rows = cur.execute(
            """
            SELECT *
            FROM department_graduation_policies
            WHERE department_id = ? AND status = 'approved'
            ORDER BY COALESCE(approved_at, created_at) DESC, id DESC
            """,
            (int(department_id),),
        ).fetchall()
        items = [dict(r) for r in rows]
        term_name, term_year = get_current_term(conn=conn)
        effective_items = [x for x in items if _is_effective_now(x, term_name, str(term_year or ""))]
        if effective_items:
            out = effective_items[0]
        else:
            no_effective = [x for x in items if not (x.get("effective_from_term") or "").strip() and not (x.get("effective_from_year") or "").strip()]
            out = (no_effective[0] if no_effective else (items[-1] if items else None))
        return jsonify({"status": "ok", "item": out}), 200
