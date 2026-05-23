"""بنود لائحة المسار الأكاديمي (وحدات الاتجاه العام، عتبات الانتقال، التخرج…) — قابلة للتعديل."""

from __future__ import annotations

import re

from flask import jsonify, request, session

from backend.core.auth import get_admin_department_scope_id, role_required
from backend.core.department_scope_policy import head_home_department_id
from backend.database.database import is_postgresql
from backend.services.utilities import get_connection

_PLAN_EDITOR = ("admin", "admin_main", "head_of_department")
_ADMIN_FULL = ("admin", "admin_main")


def _body() -> dict:
    return request.get_json(force=True, silent=True) or {}


def _i(v, default=None):
    if v in (None, ""):
        return default
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _rows(cur, sql: str, params=()):
    cur.execute(sql, params)
    rows = cur.fetchall() or []
    desc = cur.description or ()
    keys = [d[0] for d in desc]
    out = []
    for r in rows:
        if hasattr(r, "keys"):
            try:
                out.append({k: r[k] for k in r.keys()})
                continue
            except Exception:
                pass
        out.append({keys[i]: r[i] for i in range(min(len(keys), len(r)))})
    return out

_RULE_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{2,63}$")

# (rule_key, title_ar, description_ar, category, value_number, department_code)
DEFAULT_PATHWAY_REGULATIONS: list[tuple] = [
    (
        "college_general_total_units",
        "إجمالي وحدات الاتجاه العام",
        "إجمالي الوحدات المطلوبة في مرحلة الاتجاه العام بالكلية (قابل للتعديل حسب اللائحة).",
        "college_general",
        36.0,
        "GENERAL",
    ),
    (
        "college_general_university_units",
        "وحدات متطلبات الجامعة في الاتجاه العام",
        "الجزء المطلوب من وحدات الاتجاه العام لمتطلبات الجامعة.",
        "college_general",
        4.0,
        "GENERAL",
    ),
    (
        "college_general_college_units",
        "وحدات متطلبات الكلية في الاتجاه العام",
        "الجزء المطلوب من وحدات الاتجاه العام لمتطلبات الكلية.",
        "college_general",
        32.0,
        "GENERAL",
    ),
    (
        "transfer_to_department_min_units",
        "أدنى وحدات للانتقال إلى القسم",
        "الحد الأدنى من الوحدات المنجزة في الاتجاه العام للتقديم على القسم (مثال: 22 وحدة).",
        "college_general",
        22.0,
        "GENERAL",
    ),
    (
        "dept_graduation_min_units",
        "وحدات التخرج من القسم",
        "الحد الأدنى للوحدات لإتمام التخرج من برنامج القسم (يُكمّل أو يُستبدل بـ min_total_units للبرنامج).",
        "graduation",
        155.0,
        "MECH",
    ),
    (
        "dept_pre_track_min_units",
        "وحدات ما قبل التخصص (شعبة)",
        "وحدات يجب إنجازها في القسم قبل اختيار الشعبة/التخصص.",
        "dept_track",
        0.0,
        "MECH",
    ),
    (
        "dept_specialization_min_units",
        "وحدات التخصص (الشعبة)",
        "وحدات مقررات الشعبة المختارة بعد التخصص.",
        "dept_track",
        0.0,
        "MECH",
    ),
    (
        "college_pathway_cohort_from_join_year",
        "دفعات مسار الكلية (من سنة الالتحاق)",
        "0 = معطّل. عند تعيين سنة هجرية (مثل 1447) يُعيَّن الطلاب الجدد تلقائياً على PROG_U1 ومرحلة college_general.",
        "college_general",
        0.0,
        "GENERAL",
    ),
]

CATEGORY_LABELS = {
    "college_general": "الاتجاه العام والانتقال",
    "dept_track": "القسم — قبل وبعد الشعبة",
    "graduation": "التخرج",
    "other": "أخرى",
}


def _dept_id_by_code(cur, code: str) -> int | None:
    row = cur.execute(
        "SELECT id FROM departments WHERE UPPER(TRIM(code)) = UPPER(TRIM(?)) LIMIT 1",
        (code,),
    ).fetchone()
    if not row:
        return None
    return int(row[0] if not hasattr(row, "keys") else row["id"])


def _can_edit_department(conn, department_id: int) -> bool:
    role = (session.get("user_role") or "").strip().lower()
    if role in ("admin", "admin_main"):
        return True
    if role == "head_of_department":
        scope = head_home_department_id(conn, (session.get("user") or session.get("username") or "").strip())
        return scope is not None and int(scope) == int(department_id)
    return False


def ensure_pathway_regulation_defaults(conn) -> None:
    cur = conn.cursor()
    for rule_key, title, desc, cat, val, dept_code in DEFAULT_PATHWAY_REGULATIONS:
        dept_id = _dept_id_by_code(cur, dept_code)
        if dept_id is None:
            continue
        if is_postgresql():
            cur.execute(
                """
                INSERT INTO pathway_regulation_items
                (department_id, rule_key, title, description, category, value_number, sort_order, is_active)
                VALUES (?, ?, ?, ?, ?, ?, 0, 1)
                ON CONFLICT (department_id, rule_key) DO NOTHING
                """,
                (dept_id, rule_key, title, desc, cat, val),
            )
        else:
            cur.execute(
                """
                INSERT OR IGNORE INTO pathway_regulation_items
                (department_id, rule_key, title, description, category, value_number, sort_order, is_active)
                VALUES (?, ?, ?, ?, ?, ?, 0, 1)
                """,
                (dept_id, rule_key, title, desc, cat, val),
            )
    conn.commit()


def get_pathway_regulation_value(
    cur, department_id: int, rule_key: str, default: float | None = None
) -> float | None:
    """قيمة بند لائحة لقسم معيّن (أو None)."""
    row = cur.execute(
        """
        SELECT value_number FROM pathway_regulation_items
        WHERE department_id = ? AND rule_key = ? AND COALESCE(is_active, 1) = 1
        LIMIT 1
        """,
        (int(department_id), rule_key),
    ).fetchone()
    if not row:
        return default
    raw = row[0] if not hasattr(row, "keys") else row["value_number"]
    try:
        return float(raw) if raw is not None else default
    except (TypeError, ValueError):
        return default


def register_pathway_regulation_routes(bp) -> None:
    """تسجيل المسارات على blueprint كتالوج الكلية."""

    @bp.route("/pathway_regulations", methods=["GET"])
    @role_required(*_PLAN_EDITOR)
    def list_pathway_regulations():
        dept_id = _i(request.args.get("department_id"))
        with get_connection() as conn:
            ensure_pathway_regulation_defaults(conn)
            cur = conn.cursor()
            scope = get_admin_department_scope_id()
            if scope is not None:
                dept_id = int(scope)
            elif dept_id is None:
                dept_id = _dept_id_by_code(cur, "MECH")
            if dept_id is None:
                return jsonify({"status": "ok", "items": [], "department_id": None}), 200
            rows = _rows(
                cur,
                """
                SELECT r.id, r.department_id, d.code AS department_code, d.name_ar AS department_name,
                       r.rule_key, r.title, r.description, r.category,
                       r.value_number, r.value_text, r.sort_order, r.is_active
                FROM pathway_regulation_items r
                JOIN departments d ON d.id = r.department_id
                WHERE r.department_id = ?
                ORDER BY r.category, r.sort_order, r.rule_key
                """,
                (int(dept_id),),
            )
            college_rows = []
            gen_id = _dept_id_by_code(cur, "GENERAL")
            if gen_id is not None:
                college_rows = _rows(
                    cur,
                    """
                    SELECT r.id, r.department_id, d.code AS department_code, d.name_ar AS department_name,
                           r.rule_key, r.title, r.description, r.category,
                           r.value_number, r.value_text, r.sort_order, r.is_active
                    FROM pathway_regulation_items r
                    JOIN departments d ON d.id = r.department_id
                    WHERE r.department_id = ?
                    ORDER BY r.category, r.sort_order, r.rule_key
                    """,
                    (int(gen_id),),
                )
        for r in rows + college_rows:
            r["category_label"] = CATEGORY_LABELS.get(r.get("category") or "", r.get("category") or "")
        role = (session.get("user_role") or "").strip().lower()
        is_full_admin = role in ("admin", "admin_main")
        return jsonify(
            {
                "status": "ok",
                "department_id": dept_id,
                "items": rows,
                "college_items": college_rows,
                "category_labels": CATEGORY_LABELS,
                "can_edit_college_items": is_full_admin,
            }
        ), 200

    @bp.route("/pathway_regulation/save", methods=["POST"])
    @role_required(*_PLAN_EDITOR)
    def save_pathway_regulation():
        b = _body()
        item_id = _i(b.get("id"))
        department_id = _i(b.get("department_id"))
        rule_key = (b.get("rule_key") or "").strip().lower()
        title = (b.get("title") or "").strip()
        description = (b.get("description") or "").strip()
        category = (b.get("category") or "other").strip() or "other"
        sort_order = _i(b.get("sort_order"), 0) or 0
        is_active = 1 if b.get("is_active", True) else 0
        value_number = b.get("value_number")
        if value_number in (None, ""):
            value_number = None
        else:
            try:
                value_number = float(value_number)
            except (TypeError, ValueError):
                return jsonify({"status": "error", "message": "القيمة الرقمية غير صالحة"}), 400
        value_text = (b.get("value_text") or "").strip() or None

        if not department_id:
            return jsonify({"status": "error", "message": "department_id مطلوب"}), 400
        if not title:
            return jsonify({"status": "error", "message": "العنوان مطلوب"}), 400

        with get_connection() as conn:
            if not _can_edit_department(conn, int(department_id)):
                return jsonify({"status": "error", "message": "غير مصرح لتعديل لائحة هذا القسم"}), 403
            cur = conn.cursor()
            if item_id:
                cur.execute(
                    """
                    UPDATE pathway_regulation_items SET
                      title = ?, description = ?, category = ?,
                      value_number = ?, value_text = ?, sort_order = ?, is_active = ?
                    WHERE id = ? AND department_id = ?
                    """,
                    (
                        title,
                        description,
                        category,
                        value_number,
                        value_text,
                        sort_order,
                        is_active,
                        item_id,
                        department_id,
                    ),
                )
            else:
                if not rule_key or not _RULE_KEY_RE.match(rule_key):
                    return jsonify(
                        {
                            "status": "error",
                            "message": "rule_key مطلوب (حروف إنجليزية صغيرة وأرقام و _ فقط)",
                        }
                    ), 400
                if is_postgresql():
                    cur.execute(
                        """
                        INSERT INTO pathway_regulation_items
                        (department_id, rule_key, title, description, category,
                         value_number, value_text, sort_order, is_active)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT (department_id, rule_key) DO UPDATE SET
                          title = EXCLUDED.title,
                          description = EXCLUDED.description,
                          category = EXCLUDED.category,
                          value_number = EXCLUDED.value_number,
                          value_text = EXCLUDED.value_text,
                          sort_order = EXCLUDED.sort_order,
                          is_active = EXCLUDED.is_active
                        RETURNING id
                        """,
                        (
                            department_id,
                            rule_key,
                            title,
                            description,
                            category,
                            value_number,
                            value_text,
                            sort_order,
                            is_active,
                        ),
                    )
                    row = cur.fetchone()
                    item_id = int(row[0] if not hasattr(row, "keys") else row["id"])
                else:
                    cur.execute(
                        """
                        INSERT INTO pathway_regulation_items
                        (department_id, rule_key, title, description, category,
                         value_number, value_text, sort_order, is_active)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT (department_id, rule_key) DO UPDATE SET
                          title = excluded.title,
                          description = excluded.description,
                          category = excluded.category,
                          value_number = excluded.value_number,
                          value_text = excluded.value_text,
                          sort_order = excluded.sort_order,
                          is_active = excluded.is_active
                        """,
                        (
                            department_id,
                            rule_key,
                            title,
                            description,
                            category,
                            value_number,
                            value_text,
                            sort_order,
                            is_active,
                        ),
                    )
                    item_id = int(cur.lastrowid or 0)
            conn.commit()
        return jsonify({"status": "ok", "id": item_id}), 200

    @bp.route("/pathway_regulation/delete", methods=["POST"])
    @role_required(*_ADMIN_FULL)
    def delete_pathway_regulation():
        b = _body()
        item_id = _i(b.get("id"))
        if not item_id:
            return jsonify({"status": "error", "message": "id مطلوب"}), 400
        with get_connection() as conn:
            cur = conn.cursor()
            row = cur.execute(
                "SELECT department_id FROM pathway_regulation_items WHERE id = ?",
                (item_id,),
            ).fetchone()
            if not row:
                return jsonify({"status": "error", "message": "البند غير موجود"}), 404
            dept_id = int(row[0] if not hasattr(row, "keys") else row["department_id"])
            if not _can_edit_department(conn, dept_id):
                return jsonify({"status": "error", "message": "غير مصرح"}), 403
            cur.execute("DELETE FROM pathway_regulation_items WHERE id = ?", (item_id,))
            conn.commit()
        return jsonify({"status": "ok"}), 200
