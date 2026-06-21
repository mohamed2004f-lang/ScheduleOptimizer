"""بوابة هوية الكلية والبرامج — مراحل أ–ه."""

from __future__ import annotations

import datetime
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

from flask import Blueprint, jsonify, render_template, request, session

from backend.core.auth import (
    SESSION_ACTIVE_MODE,
    get_admin_department_scope_id,
    login_required,
    role_required,
    _normalize_role,
)
from backend.core.college_identity_schema import ensure_college_identity_schema
from backend.core.plo_schema import ensure_plo_enhancement_schema
from backend.database.database import fetch_table_columns, table_exists
from backend.core.department_scope_policy import head_home_department_id, resolve_users_list_scope
from backend.core.plo_glo import (
    DOMAIN_COLORS,
    DOMAIN_LABELS_AR,
    DOMAIN_ORDER,
    glo_list_from_db,
    glo_referenced_by_plo,
    normalize_outcome_domain,
    outcome_domains_payload,
)
from backend.services.outcome_assessment import department_outcomes_dashboard
from backend.services.plo_analytics import program_plo_analytics
from backend.services.utilities import get_connection, pdf_response_from_html

college_portal_bp = Blueprint("college_portal", __name__)


def _row_dict(row) -> dict:
    if row is None:
        return {}
    if hasattr(row, "keys"):
        return dict(row)
    return {}


def _session_role() -> str:
    """اقرأ الدور: current_user أولاً ← session ← قاعدة البيانات."""
    from backend.core.auth import current_user as _cu
    if _cu is not None:
        try:
            if _cu.is_authenticated:
                r = getattr(_cu, "role", None) or ""
                if r:
                    return _normalize_role(r)
        except Exception:
            pass
    role = session.get("user_role") or ""
    if role:
        return _normalize_role(role)
    from backend.core.auth import get_connection as _gc
    username = session.get("user") or ""
    if username and _gc:
        try:
            with _gc() as conn:
                row = conn.cursor().execute(
                    "SELECT role FROM users WHERE lower(username)=lower(?) LIMIT 1",
                    (username,),
                ).fetchone()
                if row and row[0]:
                    role = row[0]
                    session["user_role"] = role
                    session.modified = True
        except Exception:
            pass
    return _normalize_role(role)


def _can_edit_college() -> bool:
    r = _session_role()
    return r in ("admin_main", "college_dean", "academic_vice_dean", "system_admin")


def _can_edit_program_goals() -> bool:
    r = _session_role()
    return r in ("admin", "admin_main", "head_of_department")


def _program_in_scope(conn, program_id: int) -> bool:
    role = _session_role()
    if role in ("admin", "admin_main"):
        dep = get_admin_department_scope_id()
        if dep is None:
            return True
        row = conn.cursor().execute(
            "SELECT department_id FROM programs WHERE id = ?",
            (int(program_id),),
        ).fetchone()
        if not row:
            return False
        pd = row[0] if not hasattr(row, "keys") else row["department_id"]
        return pd is None or int(pd) == int(dep)
    if role == "head_of_department":
        hid = head_home_department_id(conn, session.get("username") or "")
        if hid is None:
            return False
        row = conn.cursor().execute(
            "SELECT department_id FROM programs WHERE id = ?",
            (int(program_id),),
        ).fetchone()
        if not row:
            return False
        pd = row[0] if not hasattr(row, "keys") else row["department_id"]
        return pd is not None and int(pd) == int(hid)
    if role == "student":
        sid = (session.get("student_id") or "").strip()
        if not sid:
            return False
        row = conn.cursor().execute(
            """
            SELECT 1 FROM students
            WHERE student_id = ? AND (
                current_program_id = ? OR admission_program_id = ?
            )
            """,
            (sid, int(program_id), int(program_id)),
        ).fetchone()
        return row is not None
    if role in ("instructor", "staff", "supervisor"):
        return True
    return False


def _active_identity(cur) -> dict:
    row = cur.execute(
        """
        SELECT id, intro_ar, mission_ar, vision_ar,
               COALESCE(strategic_plan_summary_ar, '') AS strategic_plan_summary_ar,
               values_json, effective_from, governance_status, approved_by, approved_at
        FROM college_identity
        WHERE COALESCE(is_active, 1) = 1
        ORDER BY id DESC LIMIT 1
        """
    ).fetchone()
    if not row:
        return {}
    d = _row_dict(row)
    try:
        d["values"] = json.loads(d.get("values_json") or "[]")
    except Exception:
        d["values"] = []
    return d


def _ig_roots(cur) -> list[dict]:
    rows = cur.execute(
        """
        SELECT code, title_ar FROM college_strategic_goals
        WHERE COALESCE(is_active,1)=1 AND COALESCE(parent_code,'')=''
        ORDER BY sort_order, code
        """
    ).fetchall()
    return [_row_dict(r) for r in rows or []]


def _strategic_goals_tree(cur) -> list[dict]:
    rows = cur.execute(
        """
        SELECT code, parent_code, title_ar, title_en, description,
               pillar, sort_order, governance_status, is_active
        FROM college_strategic_goals
        WHERE COALESCE(is_active, 1) = 1
        ORDER BY sort_order, code
        """
    ).fetchall()
    items = [_row_dict(r) for r in rows or []]
    by_parent: dict[str, list] = {}
    roots: list[dict] = []
    for it in items:
        pc = (it.get("parent_code") or "").strip()
        if not pc:
            it["children"] = []
            roots.append(it)
        else:
            by_parent.setdefault(pc, []).append(it)
    for r in roots:
        r["children"] = by_parent.get(r["code"], [])
    return roots


def _ig_glo_matrix(cur) -> dict[str, Any]:
    goals = cur.execute(
        """
        SELECT code, title_ar FROM college_strategic_goals
        WHERE COALESCE(is_active,1)=1 AND COALESCE(parent_code,'')=''
        ORDER BY sort_order
        """
    ).fetchall()
    glos = cur.execute(
        """
        SELECT code, title_ar FROM college_graduate_outcomes
        WHERE COALESCE(is_active,1)=1 ORDER BY sort_order, code
        """
    ).fetchall()
    links = cur.execute(
        "SELECT goal_code, glo_code, alignment FROM college_goal_glo_links"
    ).fetchall()
    link_set = {
        (str(l["goal_code"] if hasattr(l, "keys") else l[0]).upper(),
         str(l["glo_code"] if hasattr(l, "keys") else l[1]).upper())
        for l in links or []
    }
    ig_rows = [_row_dict(g) for g in goals or []]
    glo_rows = [_row_dict(g) for g in glos or []]
    cells = []
    for ig in ig_rows:
        gc = (ig.get("code") or "").upper()
        for glo in glo_rows:
            gcode = (glo.get("code") or "").upper()
            cells.append({
                "goal_code": gc,
                "glo_code": gcode,
                "linked": (gc, gcode) in link_set,
            })
    return {"goals": ig_rows, "glos": glo_rows, "cells": cells}


def _kpis_for_goal(cur, goal_code: str) -> list[dict]:
    rows = cur.execute(
        """
        SELECT id, goal_code, name_ar, target_value, actual_value, unit,
               frequency, data_source, period_label, notes, sort_order
        FROM goal_kpi
        WHERE goal_code = ? OR goal_code LIKE ?
        ORDER BY sort_order, id
        """,
        (goal_code, goal_code + ".%"),
    ).fetchall()
    return [_row_dict(r) for r in rows or []]


def _compute_system_kpi(conn, kpi: dict) -> float | None:
    """حساب مؤشرات data_source=system من بيانات المخرجات."""
    name = (kpi.get("name_ar") or "").strip()
    if "مخرجاتها" in name and "80" in name:
        try:
            cur = conn.cursor()
            row = cur.execute(
                """
                SELECT AVG(COALESCE(a.achievement_percent, m.mastery_percent)) AS avg_pct
                FROM section_clo_assessments a
                LEFT JOIN student_clo_mastery m ON m.clo_id = a.clo_id AND m.section_id = a.section_id
                """
            ).fetchone()
            if row and (row[0] if not hasattr(row, "keys") else row.get("avg_pct")) is not None:
                return round(float(row[0] if not hasattr(row, "keys") else row["avg_pct"]), 1)
        except Exception:
            pass
    if "مخرجات البرنامج" in name or "PLO" in (kpi.get("goal_code") or ""):
        pass
    if "تغطية M" in name or "I/R/M" in name:
        pass
    return None


def college_profile_payload(conn, *, department_id: int | None = None) -> dict[str, Any]:
    ensure_plo_enhancement_schema(conn)
    ensure_college_identity_schema(conn)
    cur = conn.cursor()
    identity = _active_identity(cur)
    goals_tree = _strategic_goals_tree(cur)
    matrix = _ig_glo_matrix(cur)
    glos = glo_list_from_db(conn, active_only=True)
    kpis_all = cur.execute(
        "SELECT * FROM goal_kpi ORDER BY goal_code, sort_order"
    ).fetchall()
    kpis = [_row_dict(r) for r in kpis_all or []]
    for k in kpis:
        if (k.get("data_source") or "") == "system" and k.get("actual_value") is None:
            computed = _compute_system_kpi(conn, k)
            if computed is not None:
                k["computed_value"] = computed
    stats = {}
    try:
        prog_n = cur.execute(
            "SELECT COUNT(*) FROM programs WHERE COALESCE(is_active,1)=1"
        ).fetchone()
        stats["programs_count"] = int(prog_n[0] if not hasattr(prog_n, "keys") else list(prog_n.values())[0])
        dep_n = cur.execute(
            "SELECT COUNT(*) FROM departments WHERE COALESCE(is_active,1)=1"
        ).fetchone()
        stats["departments_count"] = int(dep_n[0] if not hasattr(dep_n, "keys") else list(dep_n.values())[0])
    except Exception:
        pass
    heatmap = None
    if department_id is not None:
        try:
            heatmap = department_outcomes_dashboard(conn, department_id)
        except Exception:
            heatmap = None
    return {
        "identity": identity,
        "goals_tree": goals_tree,
        "ig_roots": _ig_roots(cur),
        "ig_glo_matrix": matrix,
        "glos": glos,
        "kpis": kpis,
        "stats": stats,
        "domain_labels": dict(DOMAIN_LABELS_AR),
        "domain_order": list(DOMAIN_ORDER),
        "domain_colors": dict(DOMAIN_COLORS),
        "department_heatmap": heatmap,
        **outcome_domains_payload(),
    }


def program_profile_payload(conn, program_id: int) -> dict[str, Any]:
    ensure_plo_enhancement_schema(conn)
    ensure_college_identity_schema(conn)
    cur = conn.cursor()
    row = cur.execute(
        """
        SELECT p.id, p.code, COALESCE(p.name_ar,'') AS name_ar, COALESCE(p.name_en,'') AS name_en,
               p.department_id, COALESCE(p.intro_ar,'') AS intro_ar,
               COALESCE(p.mission_ar,'') AS mission_ar, COALESCE(p.vision_ar,'') AS vision_ar,
               COALESCE(d.name_ar, d.name_en, '') AS department_name
        FROM programs p
        LEFT JOIN departments d ON d.id = p.department_id
        WHERE p.id = ?
        """,
        (int(program_id),),
    ).fetchone()
    if not row:
        return {}
    prog = _row_dict(row)
    goals = cur.execute(
        """
        SELECT id, code, title_ar, COALESCE(title_en,'') AS title_en,
               COALESCE(description,'') AS description,
               COALESCE(parent_ig_code,'') AS parent_ig_code,
               sort_order, governance_status, is_active
        FROM program_goals
        WHERE program_id = ? AND COALESCE(is_active,1)=1
        ORDER BY sort_order, code
        """,
        (int(program_id),),
    ).fetchall()
    outcomes = cur.execute(
        """
        SELECT id, code, title_ar, COALESCE(domain,'') AS domain,
               COALESCE(parent_glo_code,'') AS parent_glo_code, sort_order
        FROM program_learning_outcomes
        WHERE program_id = ? AND COALESCE(is_active,1)=1
        ORDER BY sort_order, code
        """,
        (int(program_id),),
    ).fetchall()
    links = cur.execute(
        """
        SELECT l.goal_id, l.outcome_id, g.code AS goal_code, o.code AS outcome_code
        FROM program_goal_outcome_links l
        JOIN program_goals g ON g.id = l.goal_id
        JOIN program_learning_outcomes o ON o.id = l.outcome_id
        WHERE g.program_id = ?
        """,
        (int(program_id),),
    ).fetchall()
    analytics = program_plo_analytics(cur, int(program_id))
    college_identity = _active_identity(cur)
    try:
        ig_alignment_rows = cur.execute(
            "SELECT ig_code FROM program_ig_alignment WHERE program_id = ?",
            (int(program_id),),
        ).fetchall()
        ig_alignment = [r[0] for r in ig_alignment_rows or []]
    except Exception:
        ig_alignment = []
        try:
            conn.rollback()
        except Exception:
            pass
        try:
            ensure_college_identity_schema(conn)
            conn.commit()
        except Exception:
            pass
    college_goals = cur.execute(
        """
        SELECT code, title_ar, COALESCE(title_en,'') AS title_en, sort_order
        FROM college_strategic_goals
        WHERE COALESCE(is_active,1)=1 AND COALESCE(parent_code,'')=''
        ORDER BY sort_order, code
        """,
    ).fetchall()
    college_glos = cur.execute(
        """
        SELECT id, code, title_ar, COALESCE(domain,'') AS domain
        FROM college_graduate_outcomes
        WHERE COALESCE(is_active,1)=1
        ORDER BY sort_order, code
        """,
    ).fetchall()
    return {
        "program": prog,
        "goals": [_row_dict(g) for g in goals or []],
        "outcomes": [_row_dict(o) for o in outcomes or []],
        "goal_outcome_links": [_row_dict(l) for l in links or []],
        "analytics": analytics,
        "college_mission": college_identity.get("mission_ar"),
        "college_vision": college_identity.get("vision_ar"),
        "ig_alignment": ig_alignment,
        "college_goals": [_row_dict(g) for g in college_goals or []],
        "college_glos": [_row_dict(g) for g in college_glos or []],
        "domain_labels": dict(DOMAIN_LABELS_AR),
        "domain_colors": dict(DOMAIN_COLORS),
    }


@college_portal_bp.route("/college")
@login_required
def college_profile_page():
    role = _session_role()
    return render_template(
        "college_profile.html",
        active_page="college_profile",
        can_edit=_can_edit_college(),
        can_edit_kpi=_can_edit_college() or role == "staff",
        is_student=role == "student",
        domain_labels=DOMAIN_LABELS_AR,
        domain_order=list(DOMAIN_ORDER),
    )


@college_portal_bp.route("/programs")
@login_required
def programs_list_page():
    return render_template(
        "programs_portal_list.html",
        active_page="programs_portal",
    )


@college_portal_bp.route("/programs/<int:program_id>/profile")
@login_required
def program_profile_page(program_id: int):
    norm = _session_role()
    can_edit = _can_edit_college() or _can_edit_program_goals()
    return render_template(
        "program_profile.html",
        active_page="program_profile",
        program_id=program_id,
        can_edit_goals=_can_edit_program_goals(),
        can_edit_profile=can_edit,
        is_student=norm == "student",
    )


@college_portal_bp.route("/api/college/profile", methods=["GET"])
@login_required
def api_college_profile():
    with get_connection() as conn:
        ensure_plo_enhancement_schema(conn)
        ensure_college_identity_schema(conn)
        dep_id = None
        role = _session_role()
        if role == "head_of_department":
            dep_id = head_home_department_id(conn, session.get("username") or "")
        elif role in ("admin", "admin_main"):
            dep_id = get_admin_department_scope_id()
        data = college_profile_payload(conn, department_id=dep_id)
    can_edit = _can_edit_college()
    return jsonify({
        "status": "ok",
        "can_edit": can_edit,
        "can_edit_kpi": can_edit or role == "staff",
        **data,
    })


def _save_identity_version(
    cur,
    *,
    intro_ar: str,
    mission_ar: str,
    vision_ar: str,
    strategic_plan_summary_ar: str = "",
    values: list,
    effective_from: str,
    actor: str,
) -> None:
    now = datetime.datetime.now(datetime.UTC).isoformat()
    cur.execute("UPDATE college_identity SET is_active = 0 WHERE COALESCE(is_active,1)=1")
    cur.execute(
        """
        INSERT INTO college_identity (
            intro_ar, mission_ar, vision_ar, strategic_plan_summary_ar, values_json,
            effective_from, governance_status, approved_by, approved_at, is_active
        ) VALUES (?, ?, ?, ?, ?, ?, 'approved', ?, ?, 1)
        """,
        (
            intro_ar,
            mission_ar,
            vision_ar,
            strategic_plan_summary_ar,
            json.dumps(values, ensure_ascii=False),
            effective_from,
            actor,
            now,
        ),
    )


@college_portal_bp.route("/api/college/values", methods=["PUT"])
@login_required
def api_update_college_values():
    data = request.get_json(force=True) or {}
    values = data.get("values")
    if not isinstance(values, list):
        return jsonify({"status": "error", "message": "values يجب أن تكون مصفوفة"}), 400
    cleaned: list[dict] = []
    seen: set[str] = set()
    for v in values:
        if not isinstance(v, dict):
            continue
        code = (v.get("code") or "").strip()
        title = (v.get("title_ar") or "").strip()
        if not code or not title:
            continue
        if code in seen:
            return jsonify({"status": "error", "message": f"رمز مكرر: {code}"}), 400
        seen.add(code)
        cleaned.append({
            "code": code,
            "title_ar": title,
            "description": (v.get("description") or "").strip(),
        })
    with get_connection() as conn:
        ensure_plo_enhancement_schema(conn)
        cur = conn.cursor()
        active = _active_identity(cur)
        if not active.get("id"):
            actor = (session.get("username") or "").strip()
            _save_identity_version(
                cur,
                intro_ar="",
                mission_ar="",
                vision_ar="",
                strategic_plan_summary_ar="",
                values=cleaned,
                effective_from="",
                actor=actor,
            )
        else:
            cur.execute(
                "UPDATE college_identity SET values_json = ? WHERE id = ?",
                (json.dumps(cleaned, ensure_ascii=False), int(active["id"])),
            )
        conn.commit()
    return jsonify({"status": "ok", "count": len(cleaned)})


@college_portal_bp.route("/api/college/strategic-goals", methods=["POST"])
@login_required
def api_create_strategic_goal():
    if not _can_edit_college():
        return jsonify({"status": "error", "message": "غير مصرح — صلاحية العميد فقط"}), 403
    data = request.get_json(force=True) or {}
    code = (data.get("code") or "").strip().upper()
    title_ar = (data.get("title_ar") or "").strip()
    parent = (data.get("parent_code") or "").strip().upper()
    if not code or not title_ar:
        return jsonify({"status": "error", "message": "الرمز والعنوان مطلوبان"}), 400
    with get_connection() as conn:
        ensure_plo_enhancement_schema(conn)
        cur = conn.cursor()
        dup = cur.execute(
            "SELECT 1 FROM college_strategic_goals WHERE UPPER(TRIM(code)) = ?",
            (code,),
        ).fetchone()
        if dup:
            return jsonify({"status": "error", "message": "الرمز مستخدم"}), 400
        if parent:
            prow = cur.execute(
                "SELECT 1 FROM college_strategic_goals WHERE UPPER(TRIM(code)) = ? AND COALESCE(is_active,1)=1",
                (parent,),
            ).fetchone()
            if not prow:
                return jsonify({"status": "error", "message": "الهدف الأب غير موجود"}), 400
        cur.execute(
            """
            INSERT INTO college_strategic_goals (
                code, parent_code, title_ar, title_en, description,
                pillar, sort_order, governance_status, is_active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                code,
                parent,
                title_ar,
                (data.get("title_en") or "").strip(),
                (data.get("description") or "").strip(),
                (data.get("pillar") or "").strip(),
                int(data.get("sort_order") or 0),
                (data.get("governance_status") or "approved").strip() or "approved",
            ),
        )
        conn.commit()
    return jsonify({"status": "ok", "code": code})


@college_portal_bp.route("/api/college/strategic-goals/<path:goal_code>", methods=["PUT", "DELETE"])
@login_required
def api_strategic_goal_by_code(goal_code: str):
    if not _can_edit_college():
        return jsonify({"status": "error", "message": "غير مصرح — صلاحية العميد فقط"}), 403
    code = (goal_code or "").strip().upper()
    with get_connection() as conn:
        ensure_plo_enhancement_schema(conn)
        cur = conn.cursor()
        row = cur.execute(
            """
            SELECT code, parent_code FROM college_strategic_goals
            WHERE UPPER(TRIM(code)) = ?
            """,
            (code,),
        ).fetchone()
        if not row:
            return jsonify({"status": "error", "message": "غير موجود"}), 404
        if request.method == "DELETE":
            kids = cur.execute(
                """
                SELECT COUNT(*) FROM college_strategic_goals
                WHERE UPPER(TRIM(parent_code)) = ? AND COALESCE(is_active,1)=1
                """,
                (code,),
            ).fetchone()
            n_kids = int(kids[0] if not hasattr(kids, "keys") else kids[0])
            if n_kids > 0:
                return jsonify({
                    "status": "error",
                    "message": "احذف الأهداف الفرعية أولاً أو عطّلها.",
                }), 400
            cur.execute(
                "DELETE FROM college_goal_glo_links WHERE UPPER(TRIM(goal_code)) = ?",
                (code,),
            )
            cur.execute(
                "DELETE FROM goal_kpi WHERE goal_code = ? OR goal_code LIKE ?",
                (code, code + ".%"),
            )
            cur.execute(
                "UPDATE college_strategic_goals SET is_active = 0 WHERE UPPER(TRIM(code)) = ?",
                (code,),
            )
            conn.commit()
            return jsonify({"status": "ok", "soft_deleted": True})
        data = request.get_json(force=True) or {}
        sets = []
        params = []
        for key in ("title_ar", "title_en", "description", "pillar", "governance_status"):
            if key in data:
                sets.append(f"{key} = ?")
                params.append((data.get(key) or "").strip())
        if "parent_code" in data:
            parent = (data.get("parent_code") or "").strip().upper()
            if parent:
                prow = cur.execute(
                    "SELECT 1 FROM college_strategic_goals WHERE UPPER(TRIM(code)) = ?",
                    (parent,),
                ).fetchone()
                if not prow:
                    return jsonify({"status": "error", "message": "الهدف الأب غير موجود"}), 400
            sets.append("parent_code = ?")
            params.append(parent)
        if data.get("sort_order") is not None:
            sets.append("sort_order = ?")
            params.append(int(data.get("sort_order")))
        if data.get("is_active") is not None:
            sets.append("is_active = ?")
            params.append(1 if data.get("is_active") else 0)
        if sets:
            params.append(code)
            cur.execute(
                f"UPDATE college_strategic_goals SET {', '.join(sets)} WHERE UPPER(TRIM(code)) = ?",
                tuple(params),
            )
            conn.commit()
    return jsonify({"status": "ok"})


@college_portal_bp.route("/api/college/glo", methods=["GET", "POST"])
@login_required
def api_college_glo_crud():
    """GLO CRUD لصفحة الكلية — admin_main فقط للتعديل."""
    if request.method == "POST" and not _can_edit_college():
        return jsonify({"status": "error", "message": "غير مصرح — صلاحية العميد فقط"}), 403
    with get_connection() as conn:
        ensure_plo_enhancement_schema(conn)
        cur = conn.cursor()
        if request.method == "GET":
            return jsonify({
                "status": "ok",
                "items": glo_list_from_db(conn, active_only=False),
            })
        data = request.get_json(force=True) or {}
        code = (data.get("code") or "").strip().upper()
        title_ar = (data.get("title_ar") or "").strip()
        if not code or not title_ar:
            return jsonify({"status": "error", "message": "الرمز والعنوان مطلوبان"}), 400
        domain = normalize_outcome_domain(data.get("domain"), glo_code=code)
        dup = cur.execute(
            "SELECT id FROM college_graduate_outcomes WHERE UPPER(TRIM(code)) = ?",
            (code,),
        ).fetchone()
        if dup:
            return jsonify({"status": "error", "message": "الرمز مستخدم"}), 400
        cur.execute(
            """
            INSERT INTO college_graduate_outcomes (
                code, title_ar, title_en, description, domain,
                sort_order, governance_status, is_active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                code,
                title_ar,
                (data.get("title_en") or "").strip(),
                (data.get("description") or "").strip(),
                domain,
                int(data.get("sort_order") or 0),
                (data.get("governance_status") or "approved").strip() or "approved",
            ),
        )
        conn.commit()
        gid = int(cur.lastrowid or 0)
    return jsonify({"status": "ok", "id": gid})


@college_portal_bp.route("/api/college/glo/<int:glo_id>", methods=["PUT", "DELETE"])
@login_required
def api_college_glo_by_id(glo_id: int):
    if not _can_edit_college():
        return jsonify({"status": "error", "message": "غير مصرح — صلاحية العميد فقط"}), 403
    with get_connection() as conn:
        ensure_plo_enhancement_schema(conn)
        cur = conn.cursor()
        row = cur.execute(
            "SELECT id, code FROM college_graduate_outcomes WHERE id = ?",
            (glo_id,),
        ).fetchone()
        if not row:
            return jsonify({"status": "error", "message": "غير موجود"}), 404
        existing = _row_dict(row)
        if request.method == "DELETE":
            refs = glo_referenced_by_plo(cur, str(existing.get("code") or ""))
            if refs > 0:
                cur.execute(
                    "UPDATE college_graduate_outcomes SET is_active = 0 WHERE id = ?",
                    (glo_id,),
                )
                conn.commit()
                return jsonify({
                    "status": "ok",
                    "soft_deleted": True,
                    "message": f"مرتبط بـ {refs} PLO — تم التعطيل.",
                })
            cur.execute(
                "DELETE FROM college_goal_glo_links WHERE UPPER(TRIM(glo_code)) = ?",
                (str(existing.get("code") or "").upper(),),
            )
            cur.execute("DELETE FROM college_graduate_outcomes WHERE id = ?", (glo_id,))
            conn.commit()
            return jsonify({"status": "ok", "soft_deleted": False})
        data = request.get_json(force=True) or {}
        sets = []
        params = []
        if "title_ar" in data and (data.get("title_ar") or "").strip():
            sets.append("title_ar = ?")
            params.append((data.get("title_ar") or "").strip())
        for key in ("title_en", "description", "governance_status"):
            if key in data:
                sets.append(f"{key} = ?")
                params.append((data.get(key) or "").strip())
        if "domain" in data:
            dom = normalize_outcome_domain(
                data.get("domain"),
                glo_code=str(existing.get("code") or ""),
            )
            sets.append("domain = ?")
            params.append(dom)
        if data.get("sort_order") is not None:
            sets.append("sort_order = ?")
            params.append(int(data.get("sort_order")))
        if data.get("is_active") is not None:
            sets.append("is_active = ?")
            params.append(1 if data.get("is_active") else 0)
        if sets:
            params.append(glo_id)
            cur.execute(
                f"UPDATE college_graduate_outcomes SET {', '.join(sets)} WHERE id = ?",
                tuple(params),
            )
            conn.commit()
    return jsonify({"status": "ok"})


@college_portal_bp.route("/api/college/identity", methods=["PUT"])
@login_required
def api_update_college_identity():
    if not _can_edit_college():
        return jsonify({"status": "error", "message": "غير مصرح بالتعديل — صلاحية العميد فقط"}), 403
    data = request.get_json(force=True) or {}
    with get_connection() as conn:
        ensure_plo_enhancement_schema(conn)
        cur = conn.cursor()
        actor = (session.get("username") or "").strip()
        active = _active_identity(cur)
        values = data.get("values")
        if values is None:
            values = active.get("values") or []
        _save_identity_version(
            cur,
            intro_ar=(data.get("intro_ar") or "").strip(),
            mission_ar=(data.get("mission_ar") or "").strip(),
            vision_ar=(data.get("vision_ar") or "").strip(),
            strategic_plan_summary_ar=(
                (data.get("strategic_plan_summary_ar") or active.get("strategic_plan_summary_ar") or "")
                .strip()
            ),
            values=values if isinstance(values, list) else [],
            effective_from=(data.get("effective_from") or active.get("effective_from") or "").strip(),
            actor=actor,
        )
        conn.commit()
    return jsonify({"status": "ok"})


@college_portal_bp.route("/api/college/ig-glo/toggle", methods=["POST"])
@login_required
def api_toggle_ig_glo():
    if not _can_edit_college():
        return jsonify({"status": "error", "message": "غير مصرح — صلاحية العميد فقط"}), 403
    data = request.get_json(force=True) or {}
    gc = (data.get("goal_code") or "").strip().upper()
    glo = (data.get("glo_code") or "").strip().upper()
    if not gc or not glo:
        return jsonify({"status": "error", "message": "goal_code و glo_code مطلوبان"}), 400
    with get_connection() as conn:
        cur = conn.cursor()
        exists = cur.execute(
            "SELECT 1 FROM college_goal_glo_links WHERE goal_code = ? AND glo_code = ?",
            (gc, glo),
        ).fetchone()
        if exists:
            cur.execute(
                "DELETE FROM college_goal_glo_links WHERE goal_code = ? AND glo_code = ?",
                (gc, glo),
            )
            linked = False
        else:
            cur.execute(
                """
                INSERT INTO college_goal_glo_links (goal_code, glo_code, alignment)
                VALUES (?, ?, 'primary')
                """,
                (gc, glo),
            )
            linked = True
        conn.commit()
    return jsonify({"status": "ok", "linked": linked})


@college_portal_bp.route("/api/college/kpis", methods=["GET", "POST"])
@login_required
def api_college_kpis():
    if request.method == "POST" and not _can_edit_college():
        return jsonify({"status": "error", "message": "غير مصرح — صلاحية العميد فقط"}), 403
    with get_connection() as conn:
        ensure_plo_enhancement_schema(conn)
        cur = conn.cursor()
        if request.method == "GET":
            goal = (request.args.get("goal_code") or "").strip()
            if goal:
                return jsonify({"status": "ok", "items": _kpis_for_goal(cur, goal)})
            rows = cur.execute("SELECT * FROM goal_kpi ORDER BY goal_code, sort_order").fetchall()
            return jsonify({"status": "ok", "items": [_row_dict(r) for r in rows or []]})
        data = request.get_json(force=True) or {}
        cur.execute(
            """
            INSERT INTO goal_kpi (
                goal_code, name_ar, target_value, actual_value, unit,
                frequency, data_source, period_label, notes, sort_order, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                (data.get("goal_code") or "").strip(),
                (data.get("name_ar") or "").strip(),
                data.get("target_value"),
                data.get("actual_value"),
                (data.get("unit") or "").strip(),
                (data.get("frequency") or "annual").strip(),
                (data.get("data_source") or "manual").strip(),
                (data.get("period_label") or "").strip(),
                (data.get("notes") or "").strip(),
                int(data.get("sort_order") or 0),
                datetime.datetime.now(datetime.UTC).isoformat(),
            ),
        )
        conn.commit()
        kid = int(cur.lastrowid or 0)
    return jsonify({"status": "ok", "id": kid})


@college_portal_bp.route("/api/college/kpis/<int:kpi_id>", methods=["PUT", "DELETE"])
@login_required
def api_update_kpi(kpi_id: int):
    if not _can_edit_college():
        return jsonify({"status": "error", "message": "غير مصرح — صلاحية العميد فقط"}), 403
    data = request.get_json(force=True) or {}
    if request.method == "DELETE":
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM goal_kpi WHERE id = ?", (kpi_id,))
            conn.commit()
        return jsonify({"status": "ok"})
    with get_connection() as conn:
        cur = conn.cursor()
        sets = []
        params = []
        for key in ("name_ar", "unit", "frequency", "data_source", "period_label", "notes", "goal_code"):
            if key in data:
                sets.append(f"{key} = ?")
                params.append((data.get(key) or "").strip())
        for key in ("target_value", "actual_value"):
            if key in data:
                sets.append(f"{key} = ?")
                params.append(data.get(key))
        if data.get("sort_order") is not None:
            sets.append("sort_order = ?")
            params.append(int(data.get("sort_order")))
        sets.append("updated_at = ?")
        params.append(datetime.datetime.now(datetime.UTC).isoformat())
        params.append(kpi_id)
        if sets:
            cur.execute(f"UPDATE goal_kpi SET {', '.join(sets)} WHERE id = ?", tuple(params))
            conn.commit()
    return jsonify({"status": "ok"})


@college_portal_bp.route("/api/programs/list", methods=["GET"])
@login_required
def api_programs_list_portal():
    """قائمة برامج الكلية — تعريفية لجميع الأدوار (بدون تقييد نطاق)."""
    with get_connection() as conn:
        ensure_plo_enhancement_schema(conn)
        cur = conn.cursor()
        sql = """
            SELECT p.id, p.code, COALESCE(p.name_ar, p.name_en, p.code) AS name,
                   COALESCE(d.name_ar, '') AS department_name
            FROM programs p
            LEFT JOIN departments d ON d.id = p.department_id
            WHERE COALESCE(p.is_active, 1) = 1
        """
        params: list = []
        role = _session_role()
        if role == "student":
            sid = (session.get("student_id") or "").strip()
            sql += " AND p.id IN (SELECT COALESCE(current_program_id, admission_program_id) FROM students WHERE student_id = ?)"
            params.append(sid)
        sql += " ORDER BY d.name_ar, p.name_ar, p.code"
        rows = cur.execute(sql, tuple(params)).fetchall()
    return jsonify({"status": "ok", "items": [_row_dict(r) for r in rows or []]})


@college_portal_bp.route("/api/programs/<int:program_id>/profile", methods=["GET", "PUT"])
@login_required
def api_program_profile(program_id: int):
    """GET: قراءة تعريفية لجميع الأدوار. PUT: تعديل نصوص البرنامج + ربط IG."""

    def _can_edit_this_program(conn) -> bool:
        role = _session_role()
        import logging
        active_mode = (session.get("active_mode") or "").strip().lower()
        logging.getLogger("app").info(
            f"[EDIT CHECK] role={role!r}, active_mode={active_mode!r}, program_id={program_id}"
        )
        if role == "head_of_department":
            if active_mode and active_mode not in ("head", "hod", "department_head"):
                return False
            return _program_in_scope(conn, program_id)
        return False

    if request.method == "PUT":
        with get_connection() as conn:
            if not _can_edit_this_program(conn):
                return jsonify({"status": "error", "message": "غير مصرح بالتعديل"}), 403
            data = request.get_json(force=True) or {}
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE programs SET intro_ar = ?, mission_ar = ?, vision_ar = ?
                WHERE id = ?
                """,
                (
                    (data.get("intro_ar") or "").strip(),
                    (data.get("mission_ar") or "").strip(),
                    (data.get("vision_ar") or "").strip(),
                    int(program_id),
                ),
            )
            ig_codes = data.get("ig_alignment")
            if ig_codes is not None:
                cur.execute("DELETE FROM program_ig_alignment WHERE program_id = ?", (int(program_id),))
                for code in ig_codes:
                    code = (code or "").strip().upper()
                    if code:
                        cur.execute(
                            "INSERT INTO program_ig_alignment (program_id, ig_code) VALUES (?, ?)",
                            (int(program_id), code),
                        )
            conn.commit()
        return jsonify({"status": "ok"})
    with get_connection() as conn:
        ensure_plo_enhancement_schema(conn)
        ensure_college_identity_schema(conn)
        payload = program_profile_payload(conn, program_id)
        if not payload:
            return jsonify({"status": "error", "message": "البرنامج غير موجود"}), 404
        can_edit = _can_edit_this_program(conn)
    resp = jsonify({
        "status": "ok",
        "can_edit_profile": can_edit,
        **payload,
    })
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    return resp


def _department_in_scope(conn, department_id: int) -> bool:
    role = _session_role()
    if role in ("admin", "admin_main"):
        dep = get_admin_department_scope_id()
        if dep is None:
            return True
        return int(dep) == int(department_id)
    if role == "head_of_department":
        active_mode = (session.get("active_mode") or session.get(SESSION_ACTIVE_MODE) or "head").strip().lower()
        if active_mode not in ("", "head", "hod", "department_head"):
            return False
        hid = head_home_department_id(conn, session.get("username") or "")
        return hid is not None and int(hid) == int(department_id)
    if role == "student":
        from backend.core.department_scope_policy import resolve_student_department_id
        sid = (session.get("student_id") or "").strip()
        sd = resolve_student_department_id(conn, sid)
        return sd is not None and int(sd) == int(department_id)
    return role in ("instructor", "staff", "supervisor")


def department_profile_payload(conn, department_id: int) -> dict[str, Any] | None:
    ensure_college_identity_schema(conn)
    cur = conn.cursor()
    cols = {c.lower() for c in fetch_table_columns(conn, "departments")}
    if not cols:
        return None
    extra = ""
    if "intro_ar" in cols:
        extra = ", COALESCE(intro_ar,'') AS intro_ar, COALESCE(mission_ar,'') AS mission_ar, COALESCE(vision_ar,'') AS vision_ar"
    row = cur.execute(
        f"SELECT id, code, COALESCE(name_ar,'') AS name_ar{extra} FROM departments WHERE id = ? LIMIT 1",
        (int(department_id),),
    ).fetchone()
    if not row:
        return None
    dept = _row_dict(row)
    goals: list[dict] = []
    if table_exists(conn, "department_goals"):
        gr = cur.execute(
            """
            SELECT id, code, title_ar, COALESCE(description,'') AS description, sort_order, is_active
            FROM department_goals WHERE department_id = ? AND COALESCE(is_active,1)=1
            ORDER BY sort_order, code
            """,
            (int(department_id),),
        ).fetchall()
        goals = [_row_dict(g) for g in gr or []]
    return {"department": dept, "goals": goals}


@college_portal_bp.route("/department/profile")
@login_required
def department_profile_redirect():
    """توجيه رئيس القسم إلى صفحة قسمه."""
    role = _session_role()
    with get_connection() as conn:
        dep_id = None
        if role == "head_of_department":
            dep_id = head_home_department_id(conn, session.get("username") or "")
        elif role in ("admin", "admin_main"):
            dep_id = get_admin_department_scope_id()
        if dep_id is None:
            return jsonify({"status": "error", "message": "لم يُحدد قسم"}), 404
    from flask import redirect, url_for
    return redirect(url_for("college_portal.department_profile_page", department_id=int(dep_id)))


@college_portal_bp.route("/departments/<int:department_id>/profile")
@login_required
def department_profile_page(department_id: int):
    role = _session_role()
    with get_connection() as conn:
        if not _department_in_scope(conn, department_id) and role not in ("admin", "admin_main", "head_of_department", "instructor", "staff", "supervisor"):
            from flask import abort
            abort(403)
        can_edit = False
        if role == "head_of_department":
            active_mode = (session.get("active_mode") or session.get(SESSION_ACTIVE_MODE) or "head").strip().lower()
            if active_mode in ("", "head", "hod", "department_head"):
                can_edit = _department_in_scope(conn, department_id)
        elif role == "admin_main":
            can_edit = True
    return render_template(
        "department_profile.html",
        active_page="department_profile",
        department_id=department_id,
        can_edit=can_edit,
    )


@college_portal_bp.route("/api/departments/<int:department_id>/profile", methods=["GET", "PUT"])
@login_required
def api_department_profile(department_id: int):
    def _can_edit_dept(conn) -> bool:
        role = _session_role()
        if role == "admin_main":
            return True
        if role == "head_of_department":
            active_mode = (session.get("active_mode") or session.get(SESSION_ACTIVE_MODE) or "head").strip().lower()
            if active_mode not in ("", "head", "hod", "department_head"):
                return False
            return _department_in_scope(conn, department_id)
        return False

    if request.method == "PUT":
        with get_connection() as conn:
            if not _can_edit_dept(conn):
                return jsonify({"status": "error", "message": "غير مصرح بالتعديل"}), 403
            ensure_college_identity_schema(conn)
            data = request.get_json(force=True) or {}
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE departments SET intro_ar = ?, mission_ar = ?, vision_ar = ?
                WHERE id = ?
                """,
                (
                    (data.get("intro_ar") or "").strip(),
                    (data.get("mission_ar") or "").strip(),
                    (data.get("vision_ar") or "").strip(),
                    int(department_id),
                ),
            )
            goals = data.get("goals")
            if goals is not None and isinstance(goals, list) and table_exists(conn, "department_goals"):
                cur.execute("DELETE FROM department_goals WHERE department_id = ?", (int(department_id),))
                for i, g in enumerate(goals):
                    if not isinstance(g, dict):
                        continue
                    code = (g.get("code") or f"DG{i+1}").strip()
                    title = (g.get("title_ar") or "").strip()
                    if not title:
                        continue
                    cur.execute(
                        """
                        INSERT INTO department_goals (department_id, code, title_ar, description, sort_order, is_active)
                        VALUES (?, ?, ?, ?, ?, 1)
                        """,
                        (
                            int(department_id),
                            code,
                            title,
                            (g.get("description") or "").strip(),
                            int(g.get("sort_order") or i),
                        ),
                    )
            conn.commit()
        return jsonify({"status": "ok"})

    with get_connection() as conn:
        ensure_college_identity_schema(conn)
        if not _department_in_scope(conn, department_id) and _session_role() not in ("admin", "admin_main", "head_of_department", "instructor", "staff", "supervisor"):
            return jsonify({"status": "error", "message": "غير مصرح"}), 403
        payload = department_profile_payload(conn, department_id)
        if not payload:
            return jsonify({"status": "error", "message": "القسم غير موجود"}), 404
        can_edit = _can_edit_dept(conn)
    return jsonify({"status": "ok", "can_edit": can_edit, **payload})


@college_portal_bp.route("/export/college-strategic")
@login_required
def export_college_strategic_html():
    with get_connection() as conn:
        data = college_profile_payload(conn)
    return render_template(
        "college_strategic_export.html",
        data=data,
        title="تقرير الأهداف الاستراتيجية والمخرجات — الكلية",
        generated_at=datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
    )


@college_portal_bp.route("/export/college-strategic.pdf")
@login_required
def export_college_strategic_pdf():
    with get_connection() as conn:
        data = college_profile_payload(conn)
    html = render_template(
        "college_strategic_export.html",
        data=data,
        title="تقرير الأهداف الاستراتيجية والمخرجات — الكلية",
        generated_at=datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        for_pdf=True,
    )
    return pdf_response_from_html(html, filename_prefix="college_strategic_report")
