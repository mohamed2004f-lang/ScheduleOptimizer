"""كتالوج مخرجات التعلم (PLO) وربطها بالمقررات وتقييم الشعب."""

from __future__ import annotations

import datetime

from flask import Blueprint, Response, jsonify, redirect, render_template, request, session

from backend.core.auth import (
    login_required,
    role_required,
    current_supervisor_effective,
    _normalize_role,
    get_admin_department_scope_id,
)
from backend.core.department_scope_policy import head_home_department_id, resolve_users_list_scope
from backend.database.database import is_postgresql, schedule_pk_column
from backend.services.utilities import get_connection
from backend.services.quality_metrics import term_label_from_conn
from backend.services.schedule import _is_instructor_effective_session, _sync_schedule_pk_col
from backend.core.plo_benchmarks import import_template, templates_for_program
from backend.core.plo_excel import (
    export_program_outcomes_xlsx,
    import_outcomes_from_xlsx,
    template_xlsx_bytes,
)
from backend.core.plo_glo import (
    BLOOM_LABELS_AR,
    COVERAGE_LABELS_AR,
    DOMAIN_COLORS,
    DOMAIN_LABELS_AR,
    DOMAIN_ORDER,
    GOVERNANCE_LABELS_AR,
    GLO_SELECT,
    DEFAULT_OUTCOME_DOMAIN,
    VALID_GLO_DOMAINS,
    VALID_PLO_DOMAINS,
    glo_list,
    glo_referenced_by_plo,
    normalize_outcome_domain,
    outcome_domains_payload,
)
from backend.core.plo_schema import ensure_plo_enhancement_schema
from backend.core.outcome_symbol_audit import (
    audit_all_programs,
    audit_program_outcome_symbols,
    cleanup_mech_stray_outcomes,
)
from backend.core.program_goals import (
    goal_has_active_links,
    import_mech_program_profile,
    outcome_has_active_links,
    propagate_mech_profile_to_tracks,
)
from backend.core.plo_goals_excel import export_program_goals_outcomes_xlsx
from backend.services.plo_analytics import export_plo_matrix_csv, program_plo_analytics
from backend.services.plo_linking import (
    cell_is_linked,
    cycle_cell_coverage,
    linked_outcome_ids_for_pc,
    set_cell_link,
    set_master_link,
    set_pc_link,
)
from backend.core.outcome_assessment_schema import ensure_outcome_assessment_schema
from backend.services.outcome_assessment import (
    department_outcomes_dashboard,
    get_scores_matrix,
    list_assessment_items,
    list_clos_for_section,
    list_section_clo_assessments,
    recompute_clo_mastery,
    save_assessment_items,
    save_section_clo_assessments,
    save_student_scores,
    student_learning_outcomes_payload,
)

learning_outcomes_bp = Blueprint("learning_outcomes", __name__)

GOAL_SELECT = """
    id, program_id, code, title_ar, COALESCE(title_en,'') AS title_en,
    COALESCE(description,'') AS description,
    COALESCE(parent_ig_code,'') AS parent_ig_code,
    sort_order, COALESCE(governance_status,'draft') AS governance_status,
    is_active
"""

PLO_SELECT = """
    id, program_id, code, title_ar, COALESCE(title_en,'') AS title_en,
    COALESCE(description,'') AS description, COALESCE(domain,'skills') AS domain,
    COALESCE(bloom_level,'') AS bloom_level,
    COALESCE(performance_indicator,'') AS performance_indicator,
    COALESCE(accreditation_tag,'') AS accreditation_tag,
    COALESCE(version,1) AS version, COALESCE(effective_from,'') AS effective_from,
    COALESCE(governance_status,'draft') AS governance_status,
    COALESCE(approved_by,'') AS approved_by, COALESCE(approved_at,'') AS approved_at,
    COALESCE(parent_glo_code,'') AS parent_glo_code,
    sort_order, is_active
"""


def _log_plo_revision(cur, outcome_id: int, action: str, snapshot: dict, actor: str) -> None:
    import json

    try:
        cur.execute(
            """
            INSERT INTO plo_revision_log (outcome_id, action, snapshot_json, actor)
            VALUES (?, ?, ?, ?)
            """,
            (int(outcome_id), action, json.dumps(snapshot, ensure_ascii=False), actor or ""),
        )
    except Exception:
        pass


def _row_dict(row, keys=None):
    if row is None:
        return {}
    if hasattr(row, "keys"):
        return dict(row)
    if keys:
        return {keys[i]: row[i] for i in range(min(len(keys), len(row)))}
    return {"v": row[0]}


def _rows_to_dicts(cur, rows):
    desc = cur.description or ()
    keys = [d[0] for d in desc]
    out = []
    for r in rows or []:
        if hasattr(r, "keys"):
            out.append(dict(r))
        else:
            out.append({keys[i]: r[i] for i in range(min(len(keys), len(r)))})
    return out


def _scope_program_ids(conn) -> list[int] | None:
    """None = كل البرامج؛ قائمة = برامج القسم فقط."""
    uname = (session.get("user") or session.get("username") or "").strip()
    mode, dep_id = resolve_users_list_scope(conn, uname)
    if mode == "empty":
        return []
    if mode == "department" and dep_id is not None:
        cur = conn.cursor()
        rows = cur.execute(
            "SELECT id FROM programs WHERE department_id = ? AND COALESCE(is_active,1)=1",
            (int(dep_id),),
        ).fetchall()
        return [int(r[0] if not hasattr(r, "keys") else r["id"]) for r in rows]
    role = _normalize_role((session.get("user_role") or "").strip())
    if role in ("instructor", "supervisor"):
        dep_id = _resolve_instructor_department(conn)
        if dep_id is None:
            return []
        cur = conn.cursor()
        rows = cur.execute(
            "SELECT id FROM programs WHERE department_id = ? AND COALESCE(is_active,1)=1",
            (int(dep_id),),
        ).fetchall()
        return [int(r[0] if not hasattr(r, "keys") else r["id"]) for r in rows]
    return []


def _resolve_instructor_department(conn) -> int | None:
    """استنتاج قسم الأستاذ/المشرف من users.department_id أو instructors.department_id."""
    cur = conn.cursor()
    uname = (session.get("user") or session.get("username") or "").strip()
    if uname:
        try:
            row = cur.execute(
                "SELECT department_id FROM users WHERE lower(username)=lower(?) LIMIT 1",
                (uname,),
            ).fetchone()
            if row:
                dep = row[0] if not hasattr(row, "keys") else row["department_id"]
                if dep not in (None, ""):
                    return int(dep)
        except Exception:
            pass
    try:
        inst_id = int(session.get("instructor_id") or 0)
    except (TypeError, ValueError):
        inst_id = 0
    if inst_id:
        try:
            row = cur.execute(
                "SELECT department_id FROM instructors WHERE id = ? LIMIT 1",
                (inst_id,),
            ).fetchone()
            if row:
                dep = row[0] if not hasattr(row, "keys") else row["department_id"]
                if dep not in (None, ""):
                    return int(dep)
        except Exception:
            pass
    return None


def _can_edit_ilo(conn, program_id: int = 0) -> bool:
    """هل المستخدم الحالي يملك صلاحية التعديل على أهداف/مخرجات الكتالوج؟"""
    from backend.core.auth import SESSION_ACTIVE_MODE
    role = _normalize_role((session.get("user_role") or "").strip())
    active_mode = (session.get(SESSION_ACTIVE_MODE) or "").strip().lower()
    if role in ("admin", "admin_main"):
        return True
    if role == "head_of_department":
        if active_mode and active_mode not in ("head", "hod", "department_head", ""):
            return False
        if program_id:
            return _program_in_scope(conn, program_id)
        return True
    return False


def _program_in_scope(conn, program_id: int) -> bool:
    allowed = _scope_program_ids(conn)
    if allowed is None:
        return True
    return int(program_id) in allowed


def _program_department_id(conn, program_id: int) -> int | None:
    cur = conn.cursor()
    row = cur.execute(
        "SELECT department_id FROM programs WHERE id = ?",
        (int(program_id),),
    ).fetchone()
    if not row:
        return None
    dep = row[0] if not hasattr(row, "keys") else row["department_id"]
    try:
        return int(dep) if dep is not None else None
    except (TypeError, ValueError):
        return None


def _courses_table_exists(conn) -> bool:
    cur = conn.cursor()
    try:
        cur.execute("SELECT 1 FROM courses LIMIT 1")
        return True
    except Exception:
        return False


@learning_outcomes_bp.route("/catalog")
@login_required
@role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department", "instructor", "supervisor")
def ilo_catalog_page():
    role = _normalize_role((session.get("user_role") or "").strip())
    # الأستاذ/المشرف: توجيه للعرض التعريفي بدل محرر الكتالوج
    if role in ("instructor", "supervisor") and not _can_edit_ilo_quick():
        return redirect("/academic_quality/ilo/outcomes-map")
    with get_connection() as conn:
        ensure_plo_enhancement_schema(conn)
        can_edit = _can_edit_ilo(conn)
    return render_template(
        "ilo_catalog.html",
        domain_labels=DOMAIN_LABELS_AR,
        domain_order=DOMAIN_ORDER,
        domain_colors=DOMAIN_COLORS,
        bloom_labels=BLOOM_LABELS_AR,
        governance_labels=GOVERNANCE_LABELS_AR,
        coverage_labels=COVERAGE_LABELS_AR,
        can_edit=can_edit,
    )


def _can_edit_ilo_quick() -> bool:
    role = _normalize_role((session.get("user_role") or "").strip())
    return role in ("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department")


@learning_outcomes_bp.route("/outcomes-map")
@login_required
def outcomes_map_page():
    return render_template("outcomes_map.html")


@learning_outcomes_bp.route("/api/outcomes-map", methods=["GET"])
@login_required
def api_outcomes_map():
    """عرض تعريفي: أهداف/مخرجات الكلية ثم البرنامج التابع للمستخدم."""
    with get_connection() as conn:
        try:
            from backend.core.plo_schema import ensure_plo_enhancement_schema
            from backend.core.plo_glo import glo_list
            from backend.core.college_identity_schema import ensure_college_identity_schema

            ensure_plo_enhancement_schema(conn)
            try:
                ensure_college_identity_schema(conn)
            except Exception:
                pass
        except Exception:
            pass
        cur = conn.cursor()
        college_goals = []
        try:
            rows = cur.execute(
                """
                SELECT code, title_ar FROM college_strategic_goals
                WHERE COALESCE(is_active,1)=1
                ORDER BY sort_order, code
                """
            ).fetchall()
            college_goals = _rows_to_dicts(cur, rows)
        except Exception:
            college_goals = []
        try:
            college_outcomes = glo_list(conn, active_only=True) or []
        except Exception:
            college_outcomes = []
        college_name = "الكلية"
        try:
            row = cur.execute(
                "SELECT COALESCE(name_ar, name, '') FROM colleges ORDER BY id LIMIT 1"
            ).fetchone()
            if row and row[0]:
                college_name = str(row[0])
        except Exception:
            pass

        program = {"id": None, "code": "", "name_ar": "", "goals": [], "outcomes": []}
        allowed = _scope_program_ids(conn)
        program_id = None
        if allowed is None:
            row = cur.execute(
                "SELECT id, code, name_ar FROM programs WHERE COALESCE(is_active,1)=1 ORDER BY code LIMIT 1"
            ).fetchone()
            if row:
                program_id = int(row[0] if not hasattr(row, "keys") else row["id"])
                program["code"] = (row[1] if not hasattr(row, "keys") else row["code"]) or ""
                program["name_ar"] = (row[2] if not hasattr(row, "keys") else row["name_ar"]) or ""
        elif allowed:
            ph = ",".join("?" * len(allowed))
            row = cur.execute(
                f"""
                SELECT id, code, name_ar FROM programs
                WHERE id IN ({ph}) AND COALESCE(is_active,1)=1
                ORDER BY code LIMIT 1
                """,
                tuple(allowed),
            ).fetchone()
            if row:
                program_id = int(row[0] if not hasattr(row, "keys") else row["id"])
                program["code"] = (row[1] if not hasattr(row, "keys") else row["code"]) or ""
                program["name_ar"] = (row[2] if not hasattr(row, "keys") else row["name_ar"]) or ""
        program["id"] = program_id
        if program_id:
            try:
                rows = cur.execute(
                    """
                    SELECT code, title_ar FROM program_goals
                    WHERE program_id=? AND COALESCE(is_active,1)=1
                    ORDER BY sort_order, code
                    """,
                    (program_id,),
                ).fetchall()
                program["goals"] = _rows_to_dicts(cur, rows)
            except Exception:
                program["goals"] = []
            try:
                rows = cur.execute(
                    f"""
                    SELECT {PLO_SELECT} FROM program_learning_outcomes
                    WHERE program_id=? AND COALESCE(is_active,1)=1
                    ORDER BY sort_order, code
                    """,
                    (program_id,),
                ).fetchall()
                program["outcomes"] = _rows_to_dicts(cur, rows)
            except Exception:
                try:
                    rows = cur.execute(
                        """
                        SELECT id, code, title_ar FROM program_learning_outcomes
                        WHERE program_id=? AND COALESCE(is_active,1)=1
                        ORDER BY sort_order, code
                        """,
                        (program_id,),
                    ).fetchall()
                    program["outcomes"] = _rows_to_dicts(cur, rows)
                except Exception:
                    program["outcomes"] = []

        return jsonify(
            {
                "status": "ok",
                "college": {
                    "name_ar": college_name,
                    "goals": college_goals,
                    "outcomes": college_outcomes,
                },
                "program": program,
            }
        )


@learning_outcomes_bp.route("/api/outcome-domains", methods=["GET"])
@login_required
def api_outcome_domains():
    return jsonify({"status": "ok", **outcome_domains_payload()})


@learning_outcomes_bp.route("/api/programs")
@login_required
@role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department", "instructor", "supervisor")
def list_programs():
    with get_connection() as conn:
        allowed = _scope_program_ids(conn)
        can_edit = _can_edit_ilo(conn)
        cur = conn.cursor()
        if allowed is None:
            rows = cur.execute(
                """
                SELECT p.id, p.code, p.name_ar, COALESCE(d.name_ar,'') AS department_name
                FROM programs p
                LEFT JOIN departments d ON d.id = p.department_id
                WHERE COALESCE(p.is_active,1)=1
                ORDER BY d.name_ar, p.code
                """
            ).fetchall()
        elif not allowed:
            rows = []
        else:
            ph = ",".join("?" * len(allowed))
            rows = cur.execute(
                f"""
                SELECT p.id, p.code, p.name_ar, COALESCE(d.name_ar,'') AS department_name
                FROM programs p
                LEFT JOIN departments d ON d.id = p.department_id
                WHERE p.id IN ({ph}) AND COALESCE(p.is_active,1)=1
                ORDER BY p.code
                """,
                tuple(allowed),
            ).fetchall()
    return jsonify({"status": "ok", "items": _rows_to_dicts(cur, rows), "can_edit": can_edit})


@learning_outcomes_bp.route("/api/programs/<int:program_id>/outcomes", methods=["GET", "POST"])
@login_required
@role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department", "instructor", "supervisor")
def program_outcomes(program_id: int):
    with get_connection() as conn:
        if not _program_in_scope(conn, program_id):
            return jsonify({"status": "error", "message": "غير مصرح"}), 403
        cur = conn.cursor()
        ensure_plo_enhancement_schema(conn)
        if request.method == "GET":
            rows = cur.execute(
                f"""
                SELECT {PLO_SELECT}
                FROM program_learning_outcomes
                WHERE program_id = ?
                ORDER BY sort_order, code
                """,
                (program_id,),
            ).fetchall()
            audit = audit_program_outcome_symbols(cur, program_id)
            return jsonify(
                {
                    "status": "ok",
                    "items": _rows_to_dicts(cur, rows),
                    "can_edit": _can_edit_ilo(conn, program_id),
                    "symbol_audit": audit,
                }
            )

        if not _can_edit_ilo(conn, program_id):
            return jsonify({"status": "error", "message": "غير مصرح بالتعديل"}), 403
        data = request.get_json(force=True) or {}
        code = (data.get("code") or "").strip()
        title_ar = (data.get("title_ar") or "").strip()
        if not code or not title_ar:
            return jsonify({"status": "error", "message": "الرمز والعنوان مطلوبان"}), 400
        description = (data.get("description") or "").strip()
        sort_order = int(data.get("sort_order") or 0)
        cur.execute(
            """
            INSERT INTO program_learning_outcomes (
                program_id, code, title_ar, title_en, description, domain, bloom_level,
                performance_indicator, accreditation_tag, parent_glo_code, sort_order,
                governance_status, version, effective_from
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', 1, ?)
            """,
            (
                program_id,
                code,
                title_ar,
                (data.get("title_en") or "").strip(),
                description,
                normalize_outcome_domain(
                    data.get("domain"),
                    glo_code=(data.get("parent_glo_code") or ""),
                ),
                (data.get("bloom_level") or "").strip(),
                (data.get("performance_indicator") or "").strip(),
                (data.get("accreditation_tag") or "").strip(),
                (data.get("parent_glo_code") or "").strip(),
                sort_order,
                (data.get("effective_from") or "").strip(),
            ),
        )
        conn.commit()
        oid = int(cur.lastrowid or 0)
    return jsonify({"status": "ok", "id": oid})


@learning_outcomes_bp.route("/api/outcomes/<int:outcome_id>", methods=["PUT", "DELETE"])
@login_required
@role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department")
def update_outcome(outcome_id: int):
    with get_connection() as conn:
        cur = conn.cursor()
        row = cur.execute(
            "SELECT program_id FROM program_learning_outcomes WHERE id = ?",
            (outcome_id,),
        ).fetchone()
        if not row:
            return jsonify({"status": "error", "message": "غير موجود"}), 404
        pid = int(row[0] if not hasattr(row, "keys") else row["program_id"])
        if not _can_edit_ilo(conn, pid):
            return jsonify({"status": "error", "message": "غير مصرح بالتعديل"}), 403
        if request.method == "DELETE":
            force = (request.args.get("force") or "").strip().lower() in (
                "1",
                "true",
                "yes",
            )
            if outcome_has_active_links(cur, outcome_id) and not force:
                cur.execute(
                    "UPDATE program_learning_outcomes SET is_active = 0 WHERE id = ?",
                    (outcome_id,),
                )
                conn.commit()
                return jsonify(
                    {
                        "status": "ok",
                        "soft_deleted": True,
                        "message": "المخرج مرتبط بمقررات أو أهداف — تم التعطيل (حذف منطقي).",
                    }
                )
            cur.execute(
                "DELETE FROM program_goal_outcome_links WHERE outcome_id = ?",
                (outcome_id,),
            )
            cur.execute(
                "DELETE FROM program_learning_outcomes WHERE id = ?", (outcome_id,)
            )
            conn.commit()
            return jsonify({"status": "ok", "soft_deleted": False})
        ensure_plo_enhancement_schema(conn)
        data = request.get_json(force=True) or {}
        actor = (session.get("user") or "").strip()
        sets = []
        params = []
        field_map = {
            "title_ar": lambda v: (v or "").strip(),
            "title_en": lambda v: (v or "").strip(),
            "description": lambda v: (v or "").strip(),
            "domain": lambda v: normalize_outcome_domain(v),
            "bloom_level": lambda v: (v or "").strip(),
            "performance_indicator": lambda v: (v or "").strip(),
            "accreditation_tag": lambda v: (v or "").strip(),
            "parent_glo_code": lambda v: (v or "").strip(),
            "effective_from": lambda v: (v or "").strip(),
            "governance_status": lambda v: (v or "").strip(),
        }
        for key, fn in field_map.items():
            if key in data:
                val = fn(data.get(key))
                if key == "title_ar" and not val:
                    continue
                sets.append(f"{key} = ?")
                params.append(val)
        code = (data.get("code") or "").strip()
        if code:
            sets.append("code = ?")
            params.append(code)
        if data.get("sort_order") is not None:
            sets.append("sort_order = ?")
            params.append(int(data.get("sort_order")))
        if data.get("is_active") is not None:
            sets.append("is_active = ?")
            params.append(1 if data.get("is_active") else 0)
        if data.get("approve"):
            sets.append("governance_status = ?")
            params.append("approved")
            sets.append("approved_by = ?")
            params.append(actor)
            sets.append("approved_at = ?")
            params.append(datetime.datetime.utcnow().isoformat())
        if not sets:
            return jsonify({"status": "error", "message": "لا توجد حقول"}), 400
        snap_row = cur.execute(
            f"SELECT {PLO_SELECT} FROM program_learning_outcomes WHERE id = ?",
            (outcome_id,),
        ).fetchone()
        params.append(outcome_id)
        cur.execute(
            f"UPDATE program_learning_outcomes SET {', '.join(sets)} WHERE id = ?",
            tuple(params),
        )
        if snap_row:
            snap = _rows_to_dicts(cur, [snap_row])[0] if hasattr(snap_row, "keys") else {}
            if not snap and hasattr(snap_row, "__getitem__"):
                snap = {"id": outcome_id}
            _log_plo_revision(
                cur,
                outcome_id,
                "approve" if data.get("approve") else "update",
                snap,
                actor,
            )
        conn.commit()
    return jsonify({"status": "ok"})


@learning_outcomes_bp.route("/api/programs/<int:program_id>/summary")
@login_required
@role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department", "instructor", "supervisor")
def program_ilo_summary(program_id: int):
    with get_connection() as conn:
        if not _program_in_scope(conn, program_id):
            return jsonify({"status": "error", "message": "غير مصرح"}), 403
        cur = conn.cursor()
        outcomes = int(
            cur.execute(
                """
                SELECT COUNT(*) FROM program_learning_outcomes
                WHERE program_id = ? AND COALESCE(is_active, 1) = 1
                """,
                (program_id,),
            ).fetchone()[0]
        )
        courses = int(
            cur.execute(
                """
                SELECT COUNT(*) FROM program_courses
                WHERE program_id = ? AND COALESCE(is_active, 1) = 1
                """,
                (program_id,),
            ).fetchone()[0]
        )
        links_pc = int(
            cur.execute(
                """
                SELECT COUNT(*)
                FROM program_course_learning_outcomes m
                JOIN program_courses pc ON pc.id = m.program_course_id
                WHERE pc.program_id = ?
                """,
                (program_id,),
            ).fetchone()[0]
        )
        links_master = int(
            cur.execute(
                """
                SELECT COUNT(*) FROM plo_course_master_links
                WHERE program_id = ?
                """,
                (program_id,),
            ).fetchone()[0]
        )
        links = links_pc + links_master
        courses_linked = int(
            cur.execute(
                """
                SELECT COUNT(*) FROM (
                    SELECT 'pc:' || CAST(m.program_course_id AS TEXT) AS ref_key
                    FROM program_course_learning_outcomes m
                    JOIN program_courses pc ON pc.id = m.program_course_id
                    WHERE pc.program_id = ? AND COALESCE(pc.is_active, 1) = 1
                    UNION
                    SELECT 'cm:' || CAST(m.course_master_id AS TEXT)
                    FROM plo_course_master_links m
                    WHERE m.program_id = ?
                      AND NOT EXISTS (
                        SELECT 1 FROM program_courses pc2
                        WHERE pc2.program_id = ?
                          AND pc2.course_master_id = m.course_master_id
                          AND COALESCE(pc2.is_active, 1) = 1
                      )
                ) t
                """,
                (program_id, program_id, program_id),
            ).fetchone()[0]
        )
        outcomes_linked = int(
            cur.execute(
                """
                SELECT COUNT(DISTINCT m.outcome_id)
                FROM program_course_learning_outcomes m
                JOIN program_learning_outcomes o ON o.id = m.outcome_id
                WHERE o.program_id = ? AND COALESCE(o.is_active, 1) = 1
                """,
                (program_id,),
            ).fetchone()[0]
        )
    return jsonify(
        {
            "status": "ok",
            "outcomes_count": outcomes,
            "courses_count": courses,
            "links_count": links,
            "courses_linked_count": courses_linked,
            "outcomes_linked_count": outcomes_linked,
            "courses_unlinked_count": max(0, courses - courses_linked),
            "outcomes_unlinked_count": max(0, outcomes - outcomes_linked),
        }
    )


@learning_outcomes_bp.route("/api/programs/<int:program_id>/courses")
@login_required
@role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department", "instructor", "supervisor")
def program_courses_for_ilo(program_id: int):
    """
    مقررات قابلة للربط بمخرجات البرنامج المحدد:
    - خطة البرنامج الحالي (program_courses)
    - خطط البرامج الأخرى في نفس القسم
    - مقررات تشغيلية (جدول courses) غير المدرجة في خطة البرنامج الحالي
    """
    with get_connection() as conn:
        if not _program_in_scope(conn, program_id):
            return jsonify({"status": "error", "message": "غير مصرح"}), 403
        cur = conn.cursor()
        dept_id = _program_department_id(conn, program_id)

        current_rows = cur.execute(
            """
            SELECT pc.id, pc.course_code, pc.program_id, p.code AS program_code,
                   COALESCE(NULLIF(pc.course_name_override,''), cm.title_ar, pc.course_code) AS course_name,
                   'current_program' AS course_group
            FROM program_courses pc
            JOIN programs p ON p.id = pc.program_id
            LEFT JOIN course_master cm ON cm.id = pc.course_master_id
            WHERE pc.program_id = ? AND COALESCE(pc.is_active,1)=1
            ORDER BY pc.level_no, pc.course_code
            """,
            (program_id,),
        ).fetchall()
        current = _rows_to_dicts(cur, current_rows)

        department_plans: list[dict] = []
        if dept_id is not None:
            dept_rows = cur.execute(
                """
                SELECT pc.id, pc.course_code, pc.program_id, p.code AS program_code,
                       COALESCE(NULLIF(pc.course_name_override,''), cm.title_ar, pc.course_code) AS course_name,
                       'department_plan' AS course_group
                FROM program_courses pc
                JOIN programs p ON p.id = pc.program_id
                LEFT JOIN course_master cm ON cm.id = pc.course_master_id
                WHERE p.department_id = ? AND pc.program_id != ?
                  AND COALESCE(pc.is_active,1)=1 AND COALESCE(p.is_active,1)=1
                ORDER BY p.code, pc.level_no, pc.course_code
                """,
                (int(dept_id), int(program_id)),
            ).fetchall()
            department_plans = _rows_to_dicts(cur, dept_rows)

        operational: list[dict] = []
        if dept_id is not None and _courses_table_exists(conn):
            op_rows = cur.execute(
                """
                SELECT c.course_name, c.course_code, c.course_master_id,
                       COALESCE(cm.title_ar, c.course_name) AS display_name
                FROM courses c
                LEFT JOIN course_master cm ON cm.id = c.course_master_id
                WHERE COALESCE(c.is_archived, 0) = 0
                  AND COALESCE(c.owning_department_id, -1) = ?
                  AND NOT EXISTS (
                    SELECT 1 FROM program_courses pc
                    WHERE pc.program_id = ?
                      AND COALESCE(pc.is_active, 1) = 1
                      AND (
                        (c.course_master_id IS NOT NULL AND pc.course_master_id = c.course_master_id)
                        OR lower(trim(COALESCE(pc.course_code, ''))) = lower(trim(COALESCE(c.course_code, '')))
                        OR lower(trim(COALESCE(pc.course_name_override, ''))) = lower(trim(COALESCE(c.course_name, '')))
                      )
                  )
                ORDER BY c.course_name
                """,
                (int(dept_id), int(program_id)),
            ).fetchall()
            for r in op_rows or []:
                d = _row_dict(
                    r,
                    ["course_name", "course_code", "course_master_id", "display_name"],
                )
                cmid = d.get("course_master_id")
                alt_pc: list[dict] = []
                if cmid is not None:
                    alt_rows = cur.execute(
                        """
                        SELECT pc.id, pc.course_code, p.code AS program_code,
                               COALESCE(NULLIF(pc.course_name_override,''), cm.title_ar, pc.course_code) AS course_name
                        FROM program_courses pc
                        JOIN programs p ON p.id = pc.program_id
                        LEFT JOIN course_master cm ON cm.id = pc.course_master_id
                        WHERE p.department_id = ? AND pc.course_master_id = ?
                          AND COALESCE(pc.is_active,1)=1
                        ORDER BY p.code, pc.course_code
                        """,
                        (int(dept_id), int(cmid)),
                    ).fetchall()
                    alt_pc = _rows_to_dicts(cur, alt_rows)
                operational.append(
                    {
                        "course_group": "operational",
                        "course_name": d.get("course_name") or "",
                        "course_code": d.get("course_code") or "",
                        "course_master_id": cmid,
                        "display_name": d.get("display_name") or d.get("course_name") or "",
                        "program_course_options": alt_pc,
                        "id": alt_pc[0]["id"] if len(alt_pc) == 1 else None,
                    }
                )

        items = current + department_plans
        for op in operational:
            if op.get("id"):
                items.append(
                    {
                        "id": op["id"],
                        "course_code": op.get("course_code") or "",
                        "course_name": op.get("display_name") or op.get("course_name"),
                        "program_id": None,
                        "program_code": "",
                        "course_group": "operational",
                        "via_operational": True,
                    }
                )

    return jsonify(
        {
            "status": "ok",
            "items": items,
            "groups": {
                "current_program": current,
                "department_plans": department_plans,
                "operational": operational,
            },
            "department_id": dept_id,
        }
    )


@learning_outcomes_bp.route("/api/program_courses/<int:program_course_id>/outcomes", methods=["GET", "PUT"])
@login_required
@role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department", "instructor", "supervisor")
def course_outcome_links(program_course_id: int):
    with get_connection() as conn:
        cur = conn.cursor()
        prow = cur.execute(
            "SELECT program_id FROM program_courses WHERE id = ?",
            (program_course_id,),
        ).fetchone()
        if not prow:
            return jsonify({"status": "error", "message": "مقرر غير موجود"}), 404
        pc_program_id = int(prow[0] if not hasattr(prow, "keys") else prow["program_id"])
        if not _program_in_scope(conn, pc_program_id):
            return jsonify({"status": "error", "message": "غير مصرح"}), 403
        if request.method == "PUT" and not _can_edit_ilo(conn, pc_program_id):
            return jsonify({"status": "error", "message": "غير مصرح بالتعديل"}), 403
        for_program_id = request.args.get("for_program_id") if request.method == "GET" else None
        if request.method == "PUT":
            body = request.get_json(force=True) or {}
            for_program_id = body.get("for_program_id")
        try:
            outcome_program_id = int(for_program_id) if for_program_id not in (None, "") else pc_program_id
        except (TypeError, ValueError):
            outcome_program_id = pc_program_id
        if not _program_in_scope(conn, outcome_program_id):
            return jsonify({"status": "error", "message": "غير مصرح لبرنامج المخرجات"}), 403
        pid = outcome_program_id
        if request.method == "GET":
            linked_ids = linked_outcome_ids_for_pc(cur, pid, int(program_course_id))
            if linked_ids:
                ph = ",".join("?" * len(linked_ids))
                linked = cur.execute(
                    f"""
                    SELECT id, code, title_ar FROM program_learning_outcomes
                    WHERE id IN ({ph}) AND COALESCE(is_active,1)=1
                    ORDER BY sort_order, code
                    """,
                    tuple(linked_ids),
                ).fetchall()
            else:
                linked = []
            all_out = cur.execute(
                """
                SELECT id, code, title_ar FROM program_learning_outcomes
                WHERE program_id = ? AND COALESCE(is_active,1)=1
                ORDER BY sort_order, code
                """,
                (pid,),
            ).fetchall()
            return jsonify(
                {
                    "status": "ok",
                    "linked": _rows_to_dicts(cur, linked),
                    "all_outcomes": _rows_to_dicts(cur, all_out),
                }
            )
        data = request.get_json(force=True) or {}
        try:
            pid = int(data.get("for_program_id") or outcome_program_id)
        except (TypeError, ValueError):
            pid = outcome_program_id
        if not _program_in_scope(conn, pid):
            return jsonify({"status": "error", "message": "غير مصرح لبرنامج المخرجات"}), 403
        outcome_ids = [int(x) for x in (data.get("outcome_ids") or [])]
        if outcome_ids:
            ph = ",".join("?" * len(outcome_ids))
            valid = cur.execute(
                f"""
                SELECT COUNT(*) FROM program_learning_outcomes
                WHERE program_id = ? AND id IN ({ph})
                """,
                (pid, *outcome_ids),
            ).fetchone()[0]
            if int(valid or 0) != len(outcome_ids):
                return jsonify({"status": "error", "message": "مخرج غير تابع للبرنامج المحدد"}), 400
        cur.execute(
            "DELETE FROM program_course_learning_outcomes WHERE program_course_id = ?",
            (program_course_id,),
        )
        cm_row = cur.execute(
            "SELECT course_master_id FROM program_courses WHERE id = ?",
            (program_course_id,),
        ).fetchone()
        cmid = None
        if cm_row:
            raw = cm_row[0] if not hasattr(cm_row, "keys") else cm_row["course_master_id"]
            try:
                cmid = int(raw) if raw is not None else None
            except (TypeError, ValueError):
                cmid = None
        if cmid is not None:
            cur.execute(
                """
                DELETE FROM plo_course_master_links
                WHERE program_id = ? AND course_master_id = ?
                """,
                (pid, cmid),
            )
        for oid in outcome_ids:
            set_pc_link(cur, int(program_course_id), int(oid), True)
            if cmid is not None:
                set_master_link(cur, pid, int(oid), cmid, True)
        conn.commit()
    return jsonify({"status": "ok"})


@learning_outcomes_bp.route(
    "/api/programs/<int:program_id>/course_master/<int:course_master_id>/outcomes",
    methods=["GET", "PUT"],
)
@login_required
@role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department", "instructor", "supervisor")
def course_master_outcome_links(program_id: int, course_master_id: int):
    """ربط مخرجات البرنامج مباشرة على course_master دون المرور بـ program_courses."""
    with get_connection() as conn:
        if not _program_in_scope(conn, program_id):
            return jsonify({"status": "error", "message": "غير مصرح"}), 403
        if request.method == "PUT" and not _can_edit_ilo(conn, program_id):
            return jsonify({"status": "error", "message": "غير مصرح بالتعديل"}), 403
        cur = conn.cursor()
        cm = cur.execute(
            "SELECT id FROM course_master WHERE id = ?",
            (course_master_id,),
        ).fetchone()
        if not cm:
            return jsonify({"status": "error", "message": "مقرر كتالوج غير موجود"}), 404
        if request.method == "GET":
            linked = cur.execute(
                """
                SELECT o.id, o.code, o.title_ar
                FROM plo_course_master_links m
                JOIN program_learning_outcomes o ON o.id = m.outcome_id
                WHERE m.program_id = ? AND m.course_master_id = ?
                  AND COALESCE(o.is_active, 1) = 1
                ORDER BY o.sort_order, o.code
                """,
                (program_id, course_master_id),
            ).fetchall()
            all_out = cur.execute(
                """
                SELECT id, code, title_ar FROM program_learning_outcomes
                WHERE program_id = ? AND COALESCE(is_active, 1) = 1
                ORDER BY sort_order, code
                """,
                (program_id,),
            ).fetchall()
            return jsonify(
                {
                    "status": "ok",
                    "linked": _rows_to_dicts(cur, linked),
                    "all_outcomes": _rows_to_dicts(cur, all_out),
                    "course_master_id": course_master_id,
                }
            )
        data = request.get_json(force=True) or {}
        outcome_ids = [int(x) for x in (data.get("outcome_ids") or [])]
        if outcome_ids:
            ph = ",".join("?" * len(outcome_ids))
            valid = cur.execute(
                f"""
                SELECT COUNT(*) FROM program_learning_outcomes
                WHERE program_id = ? AND id IN ({ph})
                """,
                (program_id, *outcome_ids),
            ).fetchone()[0]
            if int(valid or 0) != len(outcome_ids):
                return jsonify({"status": "error", "message": "مخرج غير تابع للبرنامج"}), 400
        cur.execute(
            """
            DELETE FROM plo_course_master_links
            WHERE program_id = ? AND course_master_id = ?
            """,
            (program_id, course_master_id),
        )
        for oid in outcome_ids:
            set_master_link(cur, program_id, int(oid), course_master_id, True)
        conn.commit()
    return jsonify({"status": "ok", "course_master_id": course_master_id})


def _matrix_columns_for_program(cur, program_id: int, dept_id: int | None) -> tuple[list[dict], list[dict]]:
    """أعمدة المصفوفة + مقررات تشغيلية بلا خطة."""
    cols: list[dict] = []
    rows = cur.execute(
        """
        SELECT pc.id, pc.course_code, pc.course_master_id,
               COALESCE(NULLIF(pc.course_name_override,''), cm.title_ar, pc.course_code) AS course_name
        FROM program_courses pc
        LEFT JOIN course_master cm ON cm.id = pc.course_master_id
        WHERE pc.program_id = ? AND COALESCE(pc.is_active,1)=1
        ORDER BY pc.level_no, pc.course_code
        """,
        (int(program_id),),
    ).fetchall()
    for r in rows or []:
        d = _row_dict(r, ["id", "course_code", "course_master_id", "course_name"])
        cols.append(
            {
                "col_key": f"pc:{d['id']}",
                "col_type": "program_course",
                "program_course_id": int(d["id"]),
                "course_master_id": d.get("course_master_id"),
                "course_code": d.get("course_code") or "",
                "course_name": d.get("course_name") or "",
                "in_current_program": True,
            }
        )
    operational: list[dict] = []
    if dept_id is None:
        return cols, operational
    try:
        cur.execute("SELECT 1 FROM courses LIMIT 1")
    except Exception:
        return cols, operational
    op_rows = cur.execute(
        """
        SELECT c.course_name, c.course_code, c.course_master_id,
               COALESCE(cm.title_ar, c.course_name) AS display_name
        FROM courses c
        LEFT JOIN course_master cm ON cm.id = c.course_master_id
        WHERE COALESCE(c.is_archived, 0) = 0
          AND COALESCE(c.owning_department_id, -1) = ?
          AND NOT EXISTS (
            SELECT 1 FROM program_courses pc
            WHERE pc.program_id = ?
              AND COALESCE(pc.is_active, 1) = 1
              AND (
                (c.course_master_id IS NOT NULL AND pc.course_master_id = c.course_master_id)
                OR lower(trim(COALESCE(pc.course_code, ''))) = lower(trim(COALESCE(c.course_code, '')))
                OR lower(trim(COALESCE(pc.course_name_override, ''))) = lower(trim(COALESCE(c.course_name, '')))
              )
          )
        ORDER BY c.course_name
        """,
        (int(dept_id), int(program_id)),
    ).fetchall()
    seen_cm: set[int] = set()
    for r in op_rows or []:
        d = _row_dict(r, ["course_name", "course_code", "course_master_id", "display_name"])
        cmid = d.get("course_master_id")
        try:
            cmid_i = int(cmid) if cmid is not None else None
        except (TypeError, ValueError):
            cmid_i = None
        if cmid_i is not None and cmid_i in seen_cm:
            continue
        if cmid_i is not None:
            seen_cm.add(cmid_i)
            cols.append(
                {
                    "col_key": f"cm:{cmid_i}",
                    "col_type": "course_master",
                    "program_course_id": None,
                    "course_master_id": cmid_i,
                    "course_code": d.get("course_code") or "",
                    "course_name": d.get("display_name") or d.get("course_name") or "",
                    "in_current_program": False,
                }
            )
        operational.append(
            {
                "course_name": d.get("course_name") or "",
                "course_code": d.get("course_code") or "",
                "course_master_id": cmid_i,
                "display_name": d.get("display_name") or d.get("course_name") or "",
            }
        )
    return cols, operational


@learning_outcomes_bp.route("/api/programs/<int:program_id>/coverage_matrix")
@login_required
@role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department", "instructor", "supervisor")
def coverage_matrix(program_id: int):
    with get_connection() as conn:
        if not _program_in_scope(conn, program_id):
            return jsonify({"status": "error", "message": "غير مصرح"}), 403
        cur = conn.cursor()
        dept_id = _program_department_id(conn, program_id)
        outcomes = cur.execute(
            """
            SELECT id, code, title_ar, COALESCE(domain,'') AS domain
            FROM program_learning_outcomes
            WHERE program_id = ? AND COALESCE(is_active,1)=1
            ORDER BY sort_order, code
            """,
            (program_id,),
        ).fetchall()
        outcome_list = _rows_to_dicts(cur, outcomes)
        for o in outcome_list:
            o["domain"] = normalize_outcome_domain(o.get("domain"))
            o["domain_label"] = DOMAIN_LABELS_AR.get(o["domain"], o["domain"])
        columns, operational = _matrix_columns_for_program(cur, program_id, dept_id)
        cells: list[dict] = []
        for col in columns:
            for o in outcome_list:
                oid = int(o["id"])
                if col.get("col_type") == "program_course" and col.get("program_course_id"):
                    linked, src, cov = cell_is_linked(
                        cur,
                        program_id,
                        oid,
                        program_course_id=int(col["program_course_id"]),
                    )
                elif col.get("course_master_id") is not None:
                    linked, src, cov = cell_is_linked(
                        cur,
                        program_id,
                        oid,
                        course_master_id=int(col["course_master_id"]),
                    )
                else:
                    linked, src, cov = False, "", ""
                cells.append(
                    {
                        "outcome_id": oid,
                        "col_key": col["col_key"],
                        "linked": linked,
                        "link_source": src,
                        "coverage_level": cov if linked else "",
                    }
                )
    return jsonify(
        {
            "status": "ok",
            "outcomes": outcome_list,
            "columns": columns,
            "cells": cells,
            "operational_unplanned": operational,
        }
    )


@learning_outcomes_bp.route("/api/programs/<int:program_id>/coverage_matrix/toggle", methods=["POST"])
@login_required
@role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department")
def coverage_matrix_toggle(program_id: int):
    with get_connection() as conn:
        if not _can_edit_ilo(conn, program_id):
            return jsonify({"status": "error", "message": "غير مصرح بالتعديل"}), 403
    data = request.get_json(force=True) or {}
    try:
        outcome_id = int(data.get("outcome_id"))
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "outcome_id مطلوب"}), 400
    col_key = (data.get("col_key") or "").strip()
    cycle = data.get("cycle", True)
    linked = data.get("linked")
    coverage_level = (data.get("coverage_level") or "").strip().upper()
    sync_master = data.get("sync_master", True)
    if not col_key or ":" not in col_key:
        return jsonify({"status": "error", "message": "col_key غير صالح"}), 400
    kind, raw_id = col_key.split(":", 1)
    try:
        target_id = int(raw_id)
    except ValueError:
        return jsonify({"status": "error", "message": "col_key غير صالح"}), 400
    with get_connection() as conn:
        ensure_plo_enhancement_schema(conn)
        if not _program_in_scope(conn, program_id):
            return jsonify({"status": "error", "message": "غير مصرح"}), 403
        cur = conn.cursor()
        row = cur.execute(
            "SELECT id FROM program_learning_outcomes WHERE id = ? AND program_id = ?",
            (outcome_id, program_id),
        ).fetchone()
        if not row:
            return jsonify({"status": "error", "message": "مخرج غير تابع للبرنامج"}), 400
        if kind == "pc":
            if cycle and linked is None and not coverage_level:
                ln, src, cov = cycle_cell_coverage(
                    cur,
                    program_id,
                    outcome_id,
                    program_course_id=target_id,
                    sync_master=bool(sync_master),
                )
            else:
                want = bool(linked) if linked is not None else True
                set_cell_link(
                    cur,
                    program_id,
                    outcome_id,
                    program_course_id=target_id,
                    linked=want,
                    sync_master=bool(sync_master),
                    coverage_level=coverage_level or "I",
                )
                ln, src, cov = cell_is_linked(
                    cur, program_id, outcome_id, program_course_id=target_id
                )
        elif kind == "cm":
            if cycle and linked is None and not coverage_level:
                ln, src, cov = cycle_cell_coverage(
                    cur,
                    program_id,
                    outcome_id,
                    course_master_id=target_id,
                    sync_master=True,
                )
            else:
                want = bool(linked) if linked is not None else True
                set_cell_link(
                    cur,
                    program_id,
                    outcome_id,
                    course_master_id=target_id,
                    linked=want,
                    sync_master=True,
                    coverage_level=coverage_level or "I",
                )
                ln, src, cov = cell_is_linked(
                    cur, program_id, outcome_id, course_master_id=target_id
                )
        else:
            return jsonify({"status": "error", "message": "نوع عمود غير معروف"}), 400
        conn.commit()
    return jsonify(
        {
            "status": "ok",
            "linked": ln,
            "link_source": src,
            "coverage_level": cov if ln else "",
        }
    )


@learning_outcomes_bp.route("/api/programs/<int:program_id>/add_to_plan", methods=["POST"])
@login_required
@role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department")
def add_operational_course_to_plan(program_id: int):
    """إضافة مقرر تشغيلي إلى خطة البرنامج + ربط مخرجات (اختياري)."""
    with get_connection() as conn:
        if not _can_edit_ilo(conn, program_id):
            return jsonify({"status": "error", "message": "غير مصرح بالتعديل"}), 403
    data = request.get_json(force=True) or {}
    course_name = (data.get("course_name") or "").strip()
    course_code = (data.get("course_code") or "").strip()
    course_master_id = data.get("course_master_id")
    level_no = max(0, int(data.get("level_no") or 0))
    outcome_ids = [int(x) for x in (data.get("outcome_ids") or [])]
    if not course_name and not course_code:
        return jsonify({"status": "error", "message": "اسم المقرر أو رمزه مطلوب"}), 400
    with get_connection() as conn:
        if not _program_in_scope(conn, program_id):
            return jsonify({"status": "error", "message": "غير مصرح"}), 403
        cur = conn.cursor()
        try:
            cmid = int(course_master_id) if course_master_id not in (None, "") else None
        except (TypeError, ValueError):
            cmid = None
        if cmid is None and course_name:
            ex = cur.execute(
                """
                SELECT id FROM course_master
                WHERE lower(trim(title_ar)) = lower(trim(?))
                LIMIT 1
                """,
                (course_name,),
            ).fetchone()
            if ex:
                cmid = int(ex[0] if not hasattr(ex, "keys") else ex["id"])
            else:
                cur.execute(
                    """
                    INSERT INTO course_master (title_ar, default_units, grading_mode, assessment_type)
                    VALUES (?, 0, 'partial_final', 'theoretical')
                    """,
                    (course_name,),
                )
                cmid = int(cur.lastrowid or 0)
        if not course_code and course_name:
            course_code = course_name[:20].replace(" ", "_")
        if not course_code:
            return jsonify({"status": "error", "message": "رمز المقرر في الخطة مطلوب"}), 400
        dup = cur.execute(
            """
            SELECT id FROM program_courses
            WHERE program_id = ? AND lower(trim(course_code)) = lower(trim(?))
            """,
            (program_id, course_code),
        ).fetchone()
        if dup:
            pcid = int(dup[0] if not hasattr(dup, "keys") else dup["id"])
        else:
            cur.execute(
                """
                INSERT INTO program_courses
                (program_id, course_master_id, course_code, course_name_override,
                 plan_applicability, requirement_scope, level_no, category, is_required, is_active)
                VALUES (?, ?, ?, ?, 'both', 'dept_common', ?, 'required', 1, 1)
                """,
                (program_id, cmid, course_code, course_name or "", level_no),
            )
            pcid = int(cur.lastrowid or 0)
        for oid in outcome_ids:
            row = cur.execute(
                "SELECT id FROM program_learning_outcomes WHERE id = ? AND program_id = ?",
                (oid, program_id),
            ).fetchone()
            if not row:
                continue
            set_pc_link(cur, pcid, oid, True)
            if cmid:
                set_master_link(cur, program_id, oid, cmid, True)
        conn.commit()
    return jsonify({"status": "ok", "program_course_id": pcid, "course_master_id": cmid})


@learning_outcomes_bp.route("/api/sections/<int:section_id>/ilo", methods=["GET", "POST"])
@login_required
def section_ilo_assessments(section_id: int):
    if not _is_instructor_effective_session():
        role = _normalize_role((session.get("user_role") or "").strip())
        if role not in ("admin", "admin_main", "head_of_department"):
            return jsonify({"status": "error", "message": "غير مصرح"}), 403
    instructor_id = session.get("instructor_id")
    if not instructor_id and _normalize_role((session.get("user_role") or "").strip()) not in (
        "admin",
        "admin_main",
        "head_of_department",
    ):
        return jsonify({"status": "error", "message": "لا يوجد ربط بأستاذ"}), 400
    iid = int(instructor_id or 0)

    with get_connection() as conn:
        _sync_schedule_pk_col(conn)
        pk = schedule_pk_column(conn)
        cur = conn.cursor()
        sem = term_label_from_conn(conn)
        sch = cur.execute(
            f"""
            SELECT {pk} AS section_id, COALESCE(program_course_id,0) AS program_course_id,
                   COALESCE(course_name,'') AS course_name, COALESCE(instructor_id,0) AS instructor_id,
                   COALESCE(department_id,0) AS department_id
            FROM schedule WHERE {pk} = ? LIMIT 1
            """,
            (section_id,),
        ).fetchone()
        if not sch:
            return jsonify({"status": "error", "message": "شعبة غير موجودة"}), 404
        sch_d = _row_dict(
            sch,
            ["section_id", "program_course_id", "course_name", "instructor_id", "department_id"],
        )
        pcid = int(sch_d.get("program_course_id") or 0)
        sec_iid = int(sch_d.get("instructor_id") or 0)
        if iid and sec_iid and iid != sec_iid:
            return jsonify({"status": "error", "message": "الشعبة غير مكلّفة لحسابك"}), 403
        if not iid:
            iid = sec_iid

        if request.method == "GET":
            outcomes = []
            if pcid:
                prog_row = cur.execute(
                    "SELECT program_id FROM program_courses WHERE id = ?",
                    (pcid,),
                ).fetchone()
                if prog_row:
                    pid_pc = int(prog_row[0] if not hasattr(prog_row, "keys") else prog_row["program_id"])
                    linked_ids = linked_outcome_ids_for_pc(cur, pid_pc, pcid)
                if linked_ids:
                    ph = ",".join("?" * len(linked_ids))
                    rows = cur.execute(
                        f"""
                        SELECT o.id, o.code, o.title_ar,
                               a.achievement_percent, COALESCE(a.notes,'') AS notes
                        FROM program_learning_outcomes o
                        LEFT JOIN section_ilo_assessments a
                            ON a.outcome_id = o.id AND a.section_id = ? AND a.instructor_id = ?
                               AND a.semester = ?
                        WHERE o.id IN ({ph}) AND COALESCE(o.is_active,1)=1
                        ORDER BY o.sort_order, o.code
                        """,
                        (section_id, iid, sem, *linked_ids),
                    ).fetchall()
                    outcomes = _rows_to_dicts(cur, rows)
            else:
                cname = (sch_d.get("course_name") or "").strip()
                dept_id = int(sch_d.get("department_id") or 0)
                cmid = None
                if cname:
                    cmr = cur.execute(
                        "SELECT course_master_id FROM courses WHERE course_name = ? LIMIT 1",
                        (cname,),
                    ).fetchone()
                    if cmr:
                        raw = cmr[0] if not hasattr(cmr, "keys") else cmr["course_master_id"]
                        try:
                            cmid = int(raw) if raw is not None else None
                        except (TypeError, ValueError):
                            cmid = None
                if cmid and dept_id:
                    rows = cur.execute(
                        """
                        SELECT o.id, o.code, o.title_ar,
                               a.achievement_percent, COALESCE(a.notes,'') AS notes
                        FROM plo_course_master_links m
                        JOIN program_learning_outcomes o ON o.id = m.outcome_id
                        JOIN programs p ON p.id = m.program_id
                        LEFT JOIN section_ilo_assessments a
                            ON a.outcome_id = o.id AND a.section_id = ? AND a.instructor_id = ?
                               AND a.semester = ?
                        WHERE m.course_master_id = ? AND p.department_id = ?
                          AND COALESCE(o.is_active,1)=1
                        ORDER BY o.sort_order, o.code
                        """,
                        (section_id, iid, sem, cmid, dept_id),
                    ).fetchall()
                    outcomes = _rows_to_dicts(cur, rows)
            return jsonify(
                {
                    "status": "ok",
                    "semester": sem,
                    "course_name": sch_d.get("course_name"),
                    "program_course_id": pcid,
                    "outcomes": outcomes,
                }
            )

        data = request.get_json(force=True) or {}
        items = data.get("assessments") or []
        now = datetime.datetime.utcnow().isoformat()
        for it in items:
            try:
                oid = int(it.get("outcome_id"))
                pct = int(it.get("achievement_percent"))
            except (TypeError, ValueError):
                continue
            if pct < 0 or pct > 100:
                continue
            notes = (it.get("notes") or "").strip()
            cur.execute(
                """
                INSERT INTO section_ilo_assessments
                    (section_id, instructor_id, semester, outcome_id, achievement_percent, notes, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (section_id, instructor_id, semester, outcome_id)
                DO UPDATE SET achievement_percent = excluded.achievement_percent,
                              notes = excluded.notes,
                              updated_at = excluded.updated_at
                """,
                (section_id, iid, sem, oid, pct, notes, now),
            )
        conn.commit()
        avg_row = cur.execute(
            """
            SELECT AVG(achievement_percent) FROM section_ilo_assessments
            WHERE section_id = ? AND instructor_id = ? AND semester = ?
            """,
            (section_id, iid, sem),
        ).fetchone()
        avg_pct = avg_row[0] if avg_row else None
    return jsonify({"status": "ok", "average_achievement_percent": avg_pct})


def _resolve_section_instructor_id(section_id: int, cur, pk: str) -> tuple[int | None, tuple | None]:
    """التحقق من صلاحية الأستاذ على الشعبة — يُرجع (instructor_id, error_response)."""
    if not _is_instructor_effective_session():
        role = _normalize_role((session.get("user_role") or "").strip())
        if role not in ("admin", "admin_main", "head_of_department"):
            return None, (jsonify({"status": "error", "message": "غير مصرح"}), 403)
    instructor_id = session.get("instructor_id")
    if not instructor_id and _normalize_role((session.get("user_role") or "").strip()) not in (
        "admin",
        "admin_main",
        "head_of_department",
    ):
        return None, (jsonify({"status": "error", "message": "لا يوجد ربط بأستاذ"}), 400)
    iid = int(instructor_id or 0)
    sch = cur.execute(
        f"""
        SELECT COALESCE(instructor_id,0) AS instructor_id
        FROM schedule WHERE {pk} = ? LIMIT 1
        """,
        (section_id,),
    ).fetchone()
    if not sch:
        return None, (jsonify({"status": "error", "message": "شعبة غير موجودة"}), 404)
    sec_iid = int(sch[0] if not hasattr(sch, "keys") else sch["instructor_id"])
    if iid and sec_iid and iid != sec_iid:
        return None, (jsonify({"status": "error", "message": "الشعبة غير مكلّفة لحسابك"}), 403)
    if not iid:
        iid = sec_iid
    return iid, None


@learning_outcomes_bp.route("/api/sections/<int:section_id>/clos", methods=["GET"])
@login_required
def section_clos_list(section_id: int):
    with get_connection() as conn:
        _sync_schedule_pk_col(conn)
        pk = schedule_pk_column(conn)
        cur = conn.cursor()
        ensure_plo_enhancement_schema(conn)
        ensure_outcome_assessment_schema(conn)
        sem = term_label_from_conn(conn)
        iid, err = _resolve_section_instructor_id(section_id, cur, pk)
        if err:
            return err[0], err[1]
        clos = list_clos_for_section(cur, section_id, conn)
        items = list_assessment_items(cur, section_id, sem)
    return jsonify({"status": "ok", "semester": sem, "clos": clos, "assessment_items": items})


@learning_outcomes_bp.route("/api/sections/<int:section_id>/clo-assessments", methods=["GET", "POST"])
@login_required
def section_clo_assessments_api(section_id: int):
    with get_connection() as conn:
        _sync_schedule_pk_col(conn)
        pk = schedule_pk_column(conn)
        cur = conn.cursor()
        ensure_plo_enhancement_schema(conn)
        ensure_outcome_assessment_schema(conn)
        sem = term_label_from_conn(conn)
        iid, err = _resolve_section_instructor_id(section_id, cur, pk)
        if err:
            return err[0], err[1]
        if request.method == "GET":
            items = list_section_clo_assessments(cur, section_id, iid, sem, conn)
            return jsonify({"status": "ok", "semester": sem, "clos": items})
        data = request.get_json(force=True) or {}
        save_section_clo_assessments(cur, section_id, iid, sem, data.get("assessments") or [])
        conn.commit()
    return jsonify({"status": "ok"})


@learning_outcomes_bp.route("/api/sections/<int:section_id>/assessment-items", methods=["GET", "POST"])
@login_required
def section_assessment_items_api(section_id: int):
    """بنك بنود التقييم (أسئلة/أنشطة) المرتبطة بـ CLO للشعبة."""
    with get_connection() as conn:
        _sync_schedule_pk_col(conn)
        pk = schedule_pk_column(conn)
        cur = conn.cursor()
        ensure_plo_enhancement_schema(conn)
        ensure_outcome_assessment_schema(conn)
        sem = term_label_from_conn(conn)
        iid, err = _resolve_section_instructor_id(section_id, cur, pk)
        if err:
            return err[0], err[1]
        if request.method == "GET":
            items = list_assessment_items(cur, section_id, sem)
            matrix = get_scores_matrix(cur, section_id, sem)
            return jsonify({
                "status": "ok",
                "semester": sem,
                "items": items,
                "scores": matrix.get("scores") or [],
            })
        if (request.get_json(force=True) or {}).get("readonly"):
            return jsonify({"status": "error", "message": "للقراءة فقط"}), 400
        data = request.get_json(force=True) or {}
        save_assessment_items(cur, section_id, sem, data.get("items") or [])
        if data.get("scores"):
            save_student_scores(cur, data.get("scores") or [])
        recompute_clo_mastery(cur, section_id, sem)
        conn.commit()
        items = list_assessment_items(cur, section_id, sem)
    return jsonify({"status": "ok", "items": items})


@learning_outcomes_bp.route("/api/student/learning-outcomes", methods=["GET"])
@login_required
@role_required("student")
def api_student_learning_outcomes():
    sid = (session.get("student_id") or "").strip()
    if not sid:
        return jsonify({"status": "error", "message": "لا يوجد ربط بطالب"}), 400
    with get_connection() as conn:
        payload = student_learning_outcomes_payload(conn, sid)
    return jsonify({"status": "ok", **payload})


@learning_outcomes_bp.route("/student/learning-outcomes")
@login_required
@role_required("student")
def student_learning_outcomes_page():
    return render_template(
        "student_learning_outcomes.html",
        active_page="student_learning_outcomes",
    )


@learning_outcomes_bp.route("/department/dashboard")
@login_required
@role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department")
def department_lo_dashboard_page():
    return render_template(
        "department_lo_dashboard.html",
        active_page="department_lo_dashboard",
    )


@learning_outcomes_bp.route("/api/department/outcomes-dashboard", methods=["GET"])
@login_required
@role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department")
def api_department_outcomes_dashboard():
    with get_connection() as conn:
        dep_id = head_home_department_id(conn, _current_user_name())
        if dep_id is None:
            dep_id = get_admin_department_scope_id()
        if dep_id is None:
            return jsonify({"status": "error", "message": "لا يمكن تحديد القسم"}), 400
        if not _department_in_scope(conn, int(dep_id)):
            return jsonify({"status": "error", "message": "غير مصرح"}), 403
        payload = department_outcomes_dashboard(conn, int(dep_id))
    return jsonify({"status": "ok", **payload})


def _current_user_name() -> str:
    return (session.get("user") or session.get("username") or "").strip()


def _department_in_scope(conn, department_id: int) -> bool:
    role = _normalize_role((session.get("user_role") or "").strip())
    if role in ("admin", "admin_main"):
        scope = get_admin_department_scope_id()
        if scope is not None and int(scope) != int(department_id):
            return False
        return True
    if role == "head_of_department":
        hid = head_home_department_id(conn, _current_user_name())
        return hid is not None and int(hid) == int(department_id)
    return False


def sync_closure_ilo_from_assessments(conn, section_id: int, instructor_id: int, semester: str) -> int | None:
    """يُحدّث ilo_achievement_percent في تقرير الإقفال من متوسط تقييمات المخرجات."""
    cur = conn.cursor()
    row = cur.execute(
        """
        SELECT AVG(achievement_percent) FROM section_ilo_assessments
        WHERE section_id = ? AND instructor_id = ? AND semester = ?
        """,
        (section_id, instructor_id, semester),
    ).fetchone()
    if not row or row[0] is None:
        return None
    avg_pct = int(round(float(row[0])))
    cur.execute(
        """
        UPDATE course_closure_reports SET ilo_achievement_percent = ?
        WHERE section_id = ? AND instructor_id = ? AND semester = ?
        """,
        (avg_pct, section_id, instructor_id, semester),
    )
    return avg_pct


@learning_outcomes_bp.route("/api/programs/<int:program_id>/goals", methods=["GET", "POST"])
@login_required
@role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department", "instructor", "supervisor")
def program_goals(program_id: int):
    with get_connection() as conn:
        if not _program_in_scope(conn, program_id):
            return jsonify({"status": "error", "message": "غير مصرح"}), 403
        cur = conn.cursor()
        ensure_plo_enhancement_schema(conn)
        if request.method == "GET":
            active_only = (request.args.get("active_only") or "1").strip() not in (
                "0",
                "false",
            )
            sql = f"""
                SELECT {GOAL_SELECT}
                FROM program_goals
                WHERE program_id = ?
            """
            params: list = [program_id]
            if active_only:
                sql += " AND COALESCE(is_active, 1) = 1"
            sql += " ORDER BY sort_order, code"
            rows = cur.execute(sql, tuple(params)).fetchall()
            return jsonify({"status": "ok", "items": _rows_to_dicts(cur, rows)})

        if not _can_edit_ilo(conn, program_id):
            return jsonify({"status": "error", "message": "غير مصرح بالتعديل"}), 403
        data = request.get_json(force=True) or {}
        code = (data.get("code") or "").strip()
        title_ar = (data.get("title_ar") or "").strip()
        if not code or not title_ar:
            return jsonify({"status": "error", "message": "الرمز والعنوان مطلوبان"}), 400
        cur.execute(
            """
            INSERT INTO program_goals (
                program_id, code, title_ar, title_en, description,
                parent_ig_code, sort_order, governance_status, is_active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                program_id,
                code,
                title_ar,
                (data.get("title_en") or "").strip(),
                (data.get("description") or "").strip(),
                (data.get("parent_ig_code") or "").strip(),
                int(data.get("sort_order") or 0),
                (data.get("governance_status") or "draft").strip() or "draft",
            ),
        )
        conn.commit()
        gid = int(cur.lastrowid or 0)
        if not gid:
            row = cur.execute(
                "SELECT id FROM program_goals WHERE program_id = ? AND code = ?",
                (program_id, code),
            ).fetchone()
            gid = int(row[0] if not hasattr(row, "keys") else row["id"])
    return jsonify({"status": "ok", "id": gid})


@learning_outcomes_bp.route("/api/goals/<int:goal_id>", methods=["PUT", "DELETE"])
@login_required
@role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department")
def update_goal(goal_id: int):
    with get_connection() as conn:
        cur = conn.cursor()
        ensure_plo_enhancement_schema(conn)
        row = cur.execute(
            "SELECT program_id FROM program_goals WHERE id = ?",
            (goal_id,),
        ).fetchone()
        if not row:
            return jsonify({"status": "error", "message": "غير موجود"}), 404
        pid = int(row[0] if not hasattr(row, "keys") else row["program_id"])
        if not _can_edit_ilo(conn, pid):
            return jsonify({"status": "error", "message": "غير مصرح بالتعديل"}), 403
        if request.method == "DELETE":
            force = (request.args.get("force") or "").strip().lower() in (
                "1",
                "true",
                "yes",
            )
            if goal_has_active_links(cur, goal_id) and not force:
                cur.execute(
                    "UPDATE program_goals SET is_active = 0 WHERE id = ?",
                    (goal_id,),
                )
                conn.commit()
                return jsonify(
                    {
                        "status": "ok",
                        "soft_deleted": True,
                        "message": "الهدف مرتبط بمخرجات — تم التعطيل.",
                    }
                )
            cur.execute(
                "DELETE FROM program_goal_outcome_links WHERE goal_id = ?",
                (goal_id,),
            )
            cur.execute("DELETE FROM program_goals WHERE id = ?", (goal_id,))
            conn.commit()
            return jsonify({"status": "ok", "soft_deleted": False})

        data = request.get_json(force=True) or {}
        sets = []
        params = []
        for key in ("title_ar", "title_en", "description", "governance_status", "parent_ig_code"):
            if key in data:
                sets.append(f"{key} = ?")
                params.append((data.get(key) or "").strip())
        if data.get("sort_order") is not None:
            sets.append("sort_order = ?")
            params.append(int(data.get("sort_order")))
        if data.get("is_active") is not None:
            sets.append("is_active = ?")
            params.append(1 if data.get("is_active") else 0)
        code = (data.get("code") or "").strip()
        if code:
            sets.append("code = ?")
            params.append(code)
        if data.get("approve"):
            sets.append("governance_status = ?")
            params.append("approved")
        if not sets:
            return jsonify({"status": "error", "message": "لا توجد حقول"}), 400
        params.append(goal_id)
        cur.execute(
            f"UPDATE program_goals SET {', '.join(sets)} WHERE id = ?",
            tuple(params),
        )
        conn.commit()
    return jsonify({"status": "ok"})


@learning_outcomes_bp.route("/api/programs/<int:program_id>/goal_outcome_matrix")
@login_required
@role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department", "instructor", "supervisor")
def goal_outcome_matrix(program_id: int):
    with get_connection() as conn:
        if not _program_in_scope(conn, program_id):
            return jsonify({"status": "error", "message": "غير مصرح"}), 403
        cur = conn.cursor()
        ensure_plo_enhancement_schema(conn)
        goals = _rows_to_dicts(
            cur,
            cur.execute(
                f"""
                SELECT {GOAL_SELECT}
                FROM program_goals
                WHERE program_id = ? AND COALESCE(is_active, 1) = 1
                ORDER BY sort_order, code
                """,
                (program_id,),
            ).fetchall(),
        )
        outcomes = _rows_to_dicts(
            cur,
            cur.execute(
                f"""
                SELECT id, code, title_ar
                FROM program_learning_outcomes
                WHERE program_id = ? AND COALESCE(is_active, 1) = 1
                ORDER BY sort_order, code
                """,
                (program_id,),
            ).fetchall(),
        )
        cells = _rows_to_dicts(
            cur,
            cur.execute(
                """
                SELECT l.goal_id, l.outcome_id
                FROM program_goal_outcome_links l
                INNER JOIN program_goals g ON g.id = l.goal_id
                WHERE g.program_id = ?
                """,
                (program_id,),
            ).fetchall(),
        )
    return jsonify(
        {
            "status": "ok",
            "goals": goals,
            "outcomes": outcomes,
            "cells": cells,
        }
    )


@learning_outcomes_bp.route(
    "/api/programs/<int:program_id>/goal_outcome_links", methods=["PUT"]
)
@login_required
@role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department")
def save_goal_outcome_links(program_id: int):
    data = request.get_json(force=True) or {}
    goal_id = data.get("goal_id")
    outcome_ids = data.get("outcome_ids")
    if goal_id is None or outcome_ids is None:
        return jsonify({"status": "error", "message": "goal_id و outcome_ids مطلوبان"}), 400
    with get_connection() as conn:
        if not _can_edit_ilo(conn, program_id):
            return jsonify({"status": "error", "message": "غير مصرح بالتعديل"}), 403
        cur = conn.cursor()
        ensure_plo_enhancement_schema(conn)
        grow = cur.execute(
            "SELECT id FROM program_goals WHERE id = ? AND program_id = ?",
            (int(goal_id), program_id),
        ).fetchone()
        if not grow:
            return jsonify({"status": "error", "message": "هدف غير تابع للبرنامج"}), 400
        cur.execute(
            "DELETE FROM program_goal_outcome_links WHERE goal_id = ?",
            (int(goal_id),),
        )
        for oid in outcome_ids or []:
            try:
                oid_i = int(oid)
            except (TypeError, ValueError):
                continue
            ok = cur.execute(
                """
                SELECT id FROM program_learning_outcomes
                WHERE id = ? AND program_id = ?
                """,
                (oid_i, program_id),
            ).fetchone()
            if ok:
                cur.execute(
                    """
                    INSERT INTO program_goal_outcome_links (goal_id, outcome_id)
                    VALUES (?, ?)
                    """,
                    (int(goal_id), oid_i),
                )
        conn.commit()
    return jsonify({"status": "ok"})


@learning_outcomes_bp.route("/api/programs/<int:program_id>/fix_outcome_symbols", methods=["POST"])
@login_required
@role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department")
def fix_outcome_symbols(program_id: int):
    """إصلاح خلط PLO/SO — ميكانيك: إيقاف PLO زائدة + إعادة تطبيق قالب SO."""
    with get_connection() as conn:
        ensure_plo_enhancement_schema(conn)
        if not _program_in_scope(conn, program_id):
            return jsonify({"status": "error", "message": "غير مصرح"}), 403
        cur = conn.cursor()
        actor = (session.get("user") or "").strip()
        mech = import_mech_program_profile(
            cur, program_id, merge=True, sync_links=True, actor=actor
        )
        if mech.get("status") != "ok":
            return jsonify(mech), 400
        cleanup = cleanup_mech_stray_outcomes(cur, program_id)
        audit = audit_program_outcome_symbols(cur, program_id)
        conn.commit()
    return jsonify(
        {
            "status": "ok",
            "mech_profile": mech,
            "cleanup": cleanup,
            "symbol_audit": audit,
        }
    )


@learning_outcomes_bp.route("/api/outcome_symbols/audit", methods=["GET"])
@login_required
@role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department")
def outcome_symbols_audit_all():
    with get_connection() as conn:
        ensure_plo_enhancement_schema(conn)
        reports = audit_all_programs(conn.cursor())
    return jsonify({"status": "ok", "programs_with_issues": reports})


@learning_outcomes_bp.route(
    "/api/programs/<int:program_id>/import_mech_profile", methods=["POST"]
)
@login_required
@role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department")
def import_mech_profile(program_id: int):
    data = request.get_json(force=True) or {}
    merge = bool(data.get("merge", True))
    propagate = bool(data.get("propagate_tracks", False))
    with get_connection() as conn:
        ensure_plo_enhancement_schema(conn)
        if not _program_in_scope(conn, program_id):
            return jsonify({"status": "error", "message": "غير مصرح"}), 403
        cur = conn.cursor()
        actor = (session.get("user") or "").strip()
        result = import_mech_program_profile(
            cur, program_id, merge=merge, sync_links=True, actor=actor
        )
        if result.get("status") != "ok":
            return jsonify(result), 400
        tracks = None
        if propagate:
            tracks = propagate_mech_profile_to_tracks(
                cur, program_id, merge=merge, actor=actor
            )
        conn.commit()
    out = dict(result)
    if tracks:
        out["tracks_propagation"] = tracks
    return jsonify(out)


@learning_outcomes_bp.route("/api/programs/<int:program_id>/export_profile.xlsx")
@login_required
@role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department", "instructor", "supervisor")
def export_program_profile_xlsx(program_id: int):
    with get_connection() as conn:
        ensure_plo_enhancement_schema(conn)
        if not _program_in_scope(conn, program_id):
            return jsonify({"status": "error", "message": "غير مصرح"}), 403
        cur = conn.cursor()
        goals = _rows_to_dicts(
            cur,
            cur.execute(
                f"""
                SELECT {GOAL_SELECT}
                FROM program_goals WHERE program_id = ?
                ORDER BY sort_order, code
                """,
                (program_id,),
            ).fetchall(),
        )
        outcomes = _rows_to_dicts(
            cur,
            cur.execute(
                f"""
                SELECT {PLO_SELECT}
                FROM program_learning_outcomes
                WHERE program_id = ?
                ORDER BY sort_order, code
                """,
                (program_id,),
            ).fetchall(),
        )
        matrix_goals = _rows_to_dicts(
            cur,
            cur.execute(
                f"""
                SELECT {GOAL_SELECT}
                FROM program_goals
                WHERE program_id = ? AND COALESCE(is_active, 1) = 1
                ORDER BY sort_order, code
                """,
                (program_id,),
            ).fetchall(),
        )
        matrix_outcomes = _rows_to_dicts(
            cur,
            cur.execute(
                """
                SELECT id, code, title_ar
                FROM program_learning_outcomes
                WHERE program_id = ? AND COALESCE(is_active, 1) = 1
                ORDER BY sort_order, code
                """,
                (program_id,),
            ).fetchall(),
        )
        cells = _rows_to_dicts(
            cur,
            cur.execute(
                """
                SELECT l.goal_id, l.outcome_id
                FROM program_goal_outcome_links l
                INNER JOIN program_goals g ON g.id = l.goal_id
                WHERE g.program_id = ?
                """,
                (program_id,),
            ).fetchall(),
        )
        matrix = {
            "goals": matrix_goals,
            "outcomes": matrix_outcomes,
            "cells": cells,
        }
    data = export_program_goals_outcomes_xlsx(goals, outcomes, matrix)
    return Response(
        data,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename=program_profile_{program_id}.xlsx"
        },
    )


def _can_edit_college_glo() -> bool:
    role = _normalize_role((session.get("user_role") or "").strip())
    return role in ("admin", "admin_main")


@learning_outcomes_bp.route("/api/glo", methods=["GET", "POST"])
@login_required
@role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department", "instructor", "supervisor")
def college_glo_api():
    with get_connection() as conn:
        ensure_plo_enhancement_schema(conn)
        if request.method == "GET":
            active_only = (request.args.get("active_only") or "1").strip() not in (
                "0",
                "false",
            )
            items = glo_list(conn, active_only=active_only)
            return jsonify(
                {
                    "status": "ok",
                    "items": items,
                    "can_edit": _can_edit_college_glo(),
                }
            )

        if not _can_edit_college_glo():
            return jsonify({"status": "error", "message": "غير مصرح"}), 403
        data = request.get_json(force=True) or {}
        code = (data.get("code") or "").strip().upper()
        title_ar = (data.get("title_ar") or "").strip()
        if not code or not title_ar:
            return jsonify({"status": "error", "message": "الرمز والعنوان مطلوبان"}), 400
        domain = normalize_outcome_domain(data.get("domain"), glo_code=code)
        cur = conn.cursor()
        dup = cur.execute(
            "SELECT id FROM college_graduate_outcomes WHERE UPPER(TRIM(code)) = ?",
            (code,),
        ).fetchone()
        if dup:
            return jsonify({"status": "error", "message": "الرمز مستخدم مسبقاً"}), 400
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
                (data.get("governance_status") or "draft").strip() or "draft",
            ),
        )
        conn.commit()
        gid = int(cur.lastrowid or 0)
        if not gid:
            row = cur.execute(
                "SELECT id FROM college_graduate_outcomes WHERE code = ?",
                (code,),
            ).fetchone()
            gid = int(row[0] if not hasattr(row, "keys") else row["id"])
    return jsonify({"status": "ok", "id": gid})


@learning_outcomes_bp.route("/api/glo/<int:glo_id>", methods=["PUT", "DELETE"])
@login_required
@role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department")
def update_college_glo(glo_id: int):
    with get_connection() as conn:
        ensure_plo_enhancement_schema(conn)
        cur = conn.cursor()
        row = cur.execute(
            f"SELECT {GLO_SELECT} FROM college_graduate_outcomes WHERE id = ?",
            (glo_id,),
        ).fetchone()
        if not row:
            return jsonify({"status": "error", "message": "غير موجود"}), 404
        if hasattr(row, "keys"):
            existing = dict(row)
        else:
            existing = {
                "id": row[0],
                "code": row[1],
                "title_ar": row[2],
            }

        if request.method == "DELETE":
            if not _can_edit_college_glo():
                return jsonify({"status": "error", "message": "غير مصرح"}), 403
            code = str(existing.get("code") or "")
            refs = glo_referenced_by_plo(cur, code)
            force = (request.args.get("force") or "").strip().lower() in (
                "1",
                "true",
                "yes",
            )
            if refs > 0 and not force:
                cur.execute(
                    "UPDATE college_graduate_outcomes SET is_active = 0 WHERE id = ?",
                    (glo_id,),
                )
                conn.commit()
                return jsonify(
                    {
                        "status": "ok",
                        "soft_deleted": True,
                        "message": f"GLO مرتبط بـ {refs} مخرج برنامج — تم التعطيل.",
                    }
                )
            cur.execute(
                "DELETE FROM college_graduate_outcomes WHERE id = ?", (glo_id,)
            )
            conn.commit()
            return jsonify({"status": "ok", "soft_deleted": False})

        if not _can_edit_college_glo():
            return jsonify({"status": "error", "message": "غير مصرح"}), 403
        data = request.get_json(force=True) or {}
        sets = []
        params = []
        if "title_ar" in data:
            val = (data.get("title_ar") or "").strip()
            if val:
                sets.append("title_ar = ?")
                params.append(val)
        for key in ("title_en", "description", "governance_status"):
            if key in data:
                sets.append(f"{key} = ?")
                params.append((data.get(key) or "").strip())
        if "domain" in data:
            dom = normalize_outcome_domain(
                data.get("domain"),
                glo_code=str(existing.get("code") or data.get("code") or ""),
            )
            sets.append("domain = ?")
            params.append(dom)
        if data.get("sort_order") is not None:
            sets.append("sort_order = ?")
            params.append(int(data.get("sort_order")))
        if data.get("is_active") is not None:
            sets.append("is_active = ?")
            params.append(1 if data.get("is_active") else 0)
        new_code = (data.get("code") or "").strip().upper()
        if new_code and new_code != str(existing.get("code") or "").upper():
            dup = cur.execute(
                """
                SELECT id FROM college_graduate_outcomes
                WHERE UPPER(TRIM(code)) = ? AND id <> ?
                """,
                (new_code, glo_id),
            ).fetchone()
            if dup:
                return jsonify({"status": "error", "message": "الرمز مستخدم"}), 400
            if glo_referenced_by_plo(cur, str(existing.get("code") or "")) > 0:
                return jsonify(
                    {
                        "status": "error",
                        "message": "لا يمكن تغيير الرمز — مرتبط بمخرجات برامج. عطّل وأنشئ رمزاً جديداً.",
                    }
                ), 400
            sets.append("code = ?")
            params.append(new_code)
        if data.get("approve"):
            sets.append("governance_status = ?")
            params.append("approved")
        if not sets:
            return jsonify({"status": "error", "message": "لا توجد حقول"}), 400
        params.append(glo_id)
        cur.execute(
            f"UPDATE college_graduate_outcomes SET {', '.join(sets)} WHERE id = ?",
            tuple(params),
        )
        conn.commit()
    return jsonify({"status": "ok"})


@learning_outcomes_bp.route("/api/benchmark_templates")
@login_required
@role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department", "instructor", "supervisor")
def benchmark_templates_api():
    program_id = request.args.get("program_id")
    if not program_id:
        return jsonify({"status": "error", "message": "program_id مطلوب"}), 400
    with get_connection() as conn:
        ensure_plo_enhancement_schema(conn)
        cur = conn.cursor()
        if not _program_in_scope(conn, int(program_id)):
            return jsonify({"status": "error", "message": "غير مصرح"}), 403
        items = templates_for_program(cur, int(program_id))
    return jsonify({"status": "ok", "items": items})


@learning_outcomes_bp.route("/api/programs/<int:program_id>/import_benchmark", methods=["POST"])
@login_required
@role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department")
def import_benchmark(program_id: int):
    data = request.get_json(force=True) or {}
    template_code = (data.get("template_code") or "").strip()
    if not template_code:
        return jsonify({"status": "error", "message": "template_code مطلوب"}), 400
    with get_connection() as conn:
        ensure_plo_enhancement_schema(conn)
        if not _can_edit_ilo(conn, program_id):
            return jsonify({"status": "error", "message": "غير مصرح بالتعديل"}), 403
        cur = conn.cursor()
        result = import_template(
            cur,
            program_id,
            template_code,
            merge=bool(data.get("merge", True)),
            actor=(session.get("user") or "").strip(),
        )
        if result.get("status") != "ok":
            return jsonify(result), 400
        conn.commit()
    return jsonify(result)


@learning_outcomes_bp.route("/api/programs/<int:program_id>/outcomes/template.xlsx")
@login_required
@role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department", "instructor", "supervisor")
def plo_excel_template(program_id: int):
    with get_connection() as conn:
        if not _program_in_scope(conn, program_id):
            return jsonify({"status": "error", "message": "غير مصرح"}), 403
    data = template_xlsx_bytes()
    return Response(
        data,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=plo_template.xlsx"},
    )


@learning_outcomes_bp.route("/api/programs/<int:program_id>/outcomes/export.xlsx")
@login_required
@role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department", "instructor", "supervisor")
def plo_excel_export(program_id: int):
    with get_connection() as conn:
        ensure_plo_enhancement_schema(conn)
        if not _program_in_scope(conn, program_id):
            return jsonify({"status": "error", "message": "غير مصرح"}), 403
        cur = conn.cursor()
        rows = cur.execute(
            f"""
            SELECT {PLO_SELECT}
            FROM program_learning_outcomes
            WHERE program_id = ?
            ORDER BY sort_order, code
            """,
            (program_id,),
        ).fetchall()
        items = _rows_to_dicts(cur, rows)
    data = export_program_outcomes_xlsx(items)
    return Response(
        data,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename=plo_program_{program_id}.xlsx"
        },
    )


@learning_outcomes_bp.route("/api/programs/<int:program_id>/outcomes/import.xlsx", methods=["POST"])
@login_required
@role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department")
def plo_excel_import(program_id: int):
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"status": "error", "message": "لم يُرفع ملف"}), 400
    raw = f.read()
    if not raw:
        return jsonify({"status": "error", "message": "ملف فارغ"}), 400
    merge = (request.form.get("merge") or "1").strip().lower() not in ("0", "false", "no")
    with get_connection() as conn:
        ensure_plo_enhancement_schema(conn)
        if not _can_edit_ilo(conn, program_id):
            return jsonify({"status": "error", "message": "غير مصرح بالتعديل"}), 403
        cur = conn.cursor()
        result = import_outcomes_from_xlsx(cur, program_id, raw, merge=merge)
        if result.get("status") != "ok":
            return jsonify(result), 400
        conn.commit()
    return jsonify(result)


@learning_outcomes_bp.route("/api/programs/<int:program_id>/analytics")
@login_required
@role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department", "instructor", "supervisor")
def program_analytics(program_id: int):
    with get_connection() as conn:
        ensure_plo_enhancement_schema(conn)
        if not _program_in_scope(conn, program_id):
            return jsonify({"status": "error", "message": "غير مصرح"}), 403
        cur = conn.cursor()
        data = program_plo_analytics(cur, program_id)
    return jsonify({"status": "ok", **data})


@learning_outcomes_bp.route("/api/programs/<int:program_id>/export_matrix.csv")
@login_required
@role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department", "instructor", "supervisor")
def export_matrix_csv(program_id: int):
    with get_connection() as conn:
        if not _program_in_scope(conn, program_id):
            return jsonify({"status": "error", "message": "غير مصرح"}), 403
        cur = conn.cursor()
        dept_id = _program_department_id(conn, program_id)
        outcomes = cur.execute(
            """
            SELECT id, code, title_ar FROM program_learning_outcomes
            WHERE program_id = ? AND COALESCE(is_active,1)=1
            ORDER BY sort_order, code
            """,
            (program_id,),
        ).fetchall()
        outcome_list = _rows_to_dicts(cur, outcomes)
        columns, _op = _matrix_columns_for_program(cur, program_id, dept_id)
        cells = []
        for col in columns:
            for o in outcome_list:
                oid = int(o["id"])
                if col.get("col_type") == "program_course" and col.get("program_course_id"):
                    linked, src, cov = cell_is_linked(
                        cur,
                        program_id,
                        oid,
                        program_course_id=int(col["program_course_id"]),
                    )
                elif col.get("course_master_id") is not None:
                    linked, src, cov = cell_is_linked(
                        cur,
                        program_id,
                        oid,
                        course_master_id=int(col["course_master_id"]),
                    )
                else:
                    linked, src, cov = False, "", ""
                cells.append(
                    {
                        "outcome_id": oid,
                        "col_key": col["col_key"],
                        "linked": linked,
                        "coverage_level": cov if linked else "",
                    }
                )
    csv_text = export_plo_matrix_csv(outcome_list, columns, cells)
    return Response(
        csv_text,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=plo_matrix_{program_id}.csv"},
    )


@learning_outcomes_bp.route("/api/program_courses/<int:program_course_id>/clos", methods=["GET", "POST"])
@login_required
@role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department", "instructor", "supervisor")
def course_clos(program_course_id: int):
    with get_connection() as conn:
        ensure_plo_enhancement_schema(conn)
        cur = conn.cursor()
        prow = cur.execute(
            "SELECT program_id FROM program_courses WHERE id = ?",
            (program_course_id,),
        ).fetchone()
        if not prow:
            return jsonify({"status": "error", "message": "مقرر غير موجود"}), 404
        pid = int(prow[0] if not hasattr(prow, "keys") else prow["program_id"])
        if not _program_in_scope(conn, pid):
            return jsonify({"status": "error", "message": "غير مصرح"}), 403
        if request.method == "POST" and not _can_edit_ilo(conn, pid):
            return jsonify({"status": "error", "message": "غير مصرح بالتعديل"}), 403
        if request.method == "GET":
            rows = cur.execute(
                """
                SELECT c.id, c.program_course_id, c.code, c.title_ar, c.title_en,
                       COALESCE(c.description,'') AS description, COALESCE(c.bloom_level,'') AS bloom_level,
                       c.sort_order, c.is_active
                FROM course_learning_outcomes c
                WHERE c.program_course_id = ? AND COALESCE(c.is_active,1)=1
                ORDER BY c.sort_order, c.code
                """,
                (program_course_id,),
            ).fetchall()
            items = []
            for r in _rows_to_dicts(cur, rows):
                links = cur.execute(
                    """
                    SELECT o.code FROM clo_plo_links l
                    JOIN program_learning_outcomes o ON o.id = l.outcome_id
                    WHERE l.clo_id = ?
                    """,
                    (r["id"],),
                ).fetchall()
                r["plo_codes"] = [
                    (x[0] if not hasattr(x, "keys") else x["code"]) for x in links or []
                ]
                items.append(r)
            return jsonify({"status": "ok", "items": items})
        data = request.get_json(force=True) or {}
        code = (data.get("code") or "").strip()
        title_ar = (data.get("title_ar") or "").strip()
        if not code or not title_ar:
            return jsonify({"status": "error", "message": "الرمز والعنوان مطلوبان"}), 400
        cur.execute(
            """
            INSERT INTO course_learning_outcomes (
                program_course_id, code, title_ar, title_en, description, bloom_level, sort_order
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                program_course_id,
                code,
                title_ar,
                (data.get("title_en") or "").strip(),
                (data.get("description") or "").strip(),
                (data.get("bloom_level") or "").strip(),
                int(data.get("sort_order") or 0),
            ),
        )
        clo_id = int(cur.lastrowid or 0)
        for oid in [int(x) for x in (data.get("plo_ids") or [])]:
            if is_postgresql():
                cur.execute(
                    """
                    INSERT INTO clo_plo_links (clo_id, outcome_id) VALUES (?, ?)
                    ON CONFLICT DO NOTHING
                    """,
                    (clo_id, oid),
                )
            else:
                cur.execute(
                    "INSERT OR IGNORE INTO clo_plo_links (clo_id, outcome_id) VALUES (?, ?)",
                    (clo_id, oid),
                )
        conn.commit()
    return jsonify({"status": "ok", "id": clo_id})


@learning_outcomes_bp.route("/api/clos/<int:clo_id>", methods=["PUT", "DELETE"])
@login_required
@role_required("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean", "head_of_department")
def update_clo(clo_id: int):
    with get_connection() as conn:
        ensure_plo_enhancement_schema(conn)
        cur = conn.cursor()
        row = cur.execute(
            """
            SELECT c.id, pc.program_id FROM course_learning_outcomes c
            JOIN program_courses pc ON pc.id = c.program_course_id
            WHERE c.id = ?
            """,
            (clo_id,),
        ).fetchone()
        if not row:
            return jsonify({"status": "error", "message": "غير موجود"}), 404
        prog_id = int(row[1] if not hasattr(row, "keys") else row["program_id"])
        if not _program_in_scope(conn, prog_id):
            return jsonify({"status": "error", "message": "غير مصرح"}), 403
        if request.method == "DELETE":
            cur.execute("DELETE FROM course_learning_outcomes WHERE id = ?", (clo_id,))
            conn.commit()
            return jsonify({"status": "ok"})
        data = request.get_json(force=True) or {}
        sets, params = [], []
        for key in ("title_ar", "title_en", "description", "bloom_level", "code"):
            if key in data:
                sets.append(f"{key} = ?")
                params.append((data.get(key) or "").strip())
        if data.get("sort_order") is not None:
            sets.append("sort_order = ?")
            params.append(int(data.get("sort_order")))
        if sets:
            params.append(clo_id)
            cur.execute(
                f"UPDATE course_learning_outcomes SET {', '.join(sets)} WHERE id = ?",
                tuple(params),
            )
        if "plo_ids" in data:
            cur.execute("DELETE FROM clo_plo_links WHERE clo_id = ?", (clo_id,))
            for oid in [int(x) for x in (data.get("plo_ids") or [])]:
                if is_postgresql():
                    cur.execute(
                        """
                        INSERT INTO clo_plo_links (clo_id, outcome_id) VALUES (?, ?)
                        ON CONFLICT DO NOTHING
                        """,
                        (clo_id, oid),
                    )
                else:
                    cur.execute(
                        "INSERT OR IGNORE INTO clo_plo_links (clo_id, outcome_id) VALUES (?, ?)",
                        (clo_id, oid),
                    )
        conn.commit()
    return jsonify({"status": "ok"})
