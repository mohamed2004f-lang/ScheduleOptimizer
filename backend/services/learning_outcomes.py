"""كتالوج مخرجات التعلم (PLO) وربطها بالمقررات وتقييم الشعب."""

from __future__ import annotations

import datetime

from flask import Blueprint, jsonify, render_template, request, session

from backend.core.auth import (
    login_required,
    role_required,
    current_supervisor_effective,
    _normalize_role,
    get_admin_department_scope_id,
)
from backend.core.department_scope_policy import head_home_department_id, resolve_users_list_scope
from backend.database.database import schedule_pk_column
from backend.services.utilities import get_connection
from backend.services.quality_metrics import term_label_from_conn
from backend.services.schedule import _is_instructor_effective_session, _sync_schedule_pk_col
from backend.services.plo_linking import (
    cell_is_linked,
    linked_outcome_ids_for_pc,
    set_cell_link,
    set_master_link,
    set_pc_link,
)

learning_outcomes_bp = Blueprint("learning_outcomes", __name__)


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
    role = _normalize_role((session.get("user_role") or "").strip())
    if role in ("admin", "admin_main"):
        dep = get_admin_department_scope_id()
        if dep is None:
            return None
        cur = conn.cursor()
        rows = cur.execute(
            "SELECT id FROM programs WHERE department_id = ? AND COALESCE(is_active,1)=1",
            (int(dep),),
        ).fetchall()
        return [int(r[0] if not hasattr(r, "keys") else r["id"]) for r in rows]
    if role == "head_of_department":
        mode, dept = resolve_users_list_scope(conn, session.get("user"))
        dep_id = dept if mode == "department" else head_home_department_id(conn, session.get("user"))
        if dep_id is None:
            return []
        cur = conn.cursor()
        rows = cur.execute(
            "SELECT id FROM programs WHERE department_id = ? AND COALESCE(is_active,1)=1",
            (int(dep_id),),
        ).fetchall()
        return [int(r[0] if not hasattr(r, "keys") else r["id"]) for r in rows]
    return []


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
@role_required("admin", "admin_main", "head_of_department")
def ilo_catalog_page():
    return render_template("ilo_catalog.html")


@learning_outcomes_bp.route("/api/programs")
@login_required
@role_required("admin", "admin_main", "head_of_department")
def list_programs():
    with get_connection() as conn:
        allowed = _scope_program_ids(conn)
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
    return jsonify({"status": "ok", "items": _rows_to_dicts(cur, rows)})


@learning_outcomes_bp.route("/api/programs/<int:program_id>/outcomes", methods=["GET", "POST"])
@login_required
@role_required("admin", "admin_main", "head_of_department")
def program_outcomes(program_id: int):
    with get_connection() as conn:
        if not _program_in_scope(conn, program_id):
            return jsonify({"status": "error", "message": "غير مصرح"}), 403
        cur = conn.cursor()
        if request.method == "GET":
            rows = cur.execute(
                """
                SELECT id, program_id, code, title_ar, COALESCE(description,'') AS description,
                       sort_order, is_active
                FROM program_learning_outcomes
                WHERE program_id = ?
                ORDER BY sort_order, code
                """,
                (program_id,),
            ).fetchall()
            return jsonify({"status": "ok", "items": _rows_to_dicts(cur, rows)})

        data = request.get_json(force=True) or {}
        code = (data.get("code") or "").strip()
        title_ar = (data.get("title_ar") or "").strip()
        if not code or not title_ar:
            return jsonify({"status": "error", "message": "الرمز والعنوان مطلوبان"}), 400
        description = (data.get("description") or "").strip()
        sort_order = int(data.get("sort_order") or 0)
        cur.execute(
            """
            INSERT INTO program_learning_outcomes (program_id, code, title_ar, description, sort_order)
            VALUES (?, ?, ?, ?, ?)
            """,
            (program_id, code, title_ar, description, sort_order),
        )
        conn.commit()
        oid = int(cur.lastrowid or 0)
    return jsonify({"status": "ok", "id": oid})


@learning_outcomes_bp.route("/api/outcomes/<int:outcome_id>", methods=["PUT", "DELETE"])
@login_required
@role_required("admin", "admin_main", "head_of_department")
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
        if not _program_in_scope(conn, pid):
            return jsonify({"status": "error", "message": "غير مصرح"}), 403
        if request.method == "DELETE":
            cur.execute("DELETE FROM program_learning_outcomes WHERE id = ?", (outcome_id,))
            conn.commit()
            return jsonify({"status": "ok"})
        data = request.get_json(force=True) or {}
        title_ar = (data.get("title_ar") or "").strip()
        description = (data.get("description") or "").strip()
        sort_order = data.get("sort_order")
        is_active = data.get("is_active")
        sets = []
        params = []
        if title_ar:
            sets.append("title_ar = ?")
            params.append(title_ar)
        code = (data.get("code") or "").strip()
        if code:
            sets.append("code = ?")
            params.append(code)
        if "description" in data:
            sets.append("description = ?")
            params.append(description)
        if sort_order is not None:
            sets.append("sort_order = ?")
            params.append(int(sort_order))
        if is_active is not None:
            sets.append("is_active = ?")
            params.append(1 if is_active else 0)
        if not sets:
            return jsonify({"status": "error", "message": "لا توجد حقول"}), 400
        params.append(outcome_id)
        cur.execute(
            f"UPDATE program_learning_outcomes SET {', '.join(sets)} WHERE id = ?",
            tuple(params),
        )
        conn.commit()
    return jsonify({"status": "ok"})


@learning_outcomes_bp.route("/api/programs/<int:program_id>/summary")
@login_required
@role_required("admin", "admin_main", "head_of_department")
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
@role_required("admin", "admin_main", "head_of_department")
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
@role_required("admin", "admin_main", "head_of_department")
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
@role_required("admin", "admin_main", "head_of_department")
def course_master_outcome_links(program_id: int, course_master_id: int):
    """ربط مخرجات البرنامج مباشرة على course_master دون المرور بـ program_courses."""
    with get_connection() as conn:
        if not _program_in_scope(conn, program_id):
            return jsonify({"status": "error", "message": "غير مصرح"}), 403
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
@role_required("admin", "admin_main", "head_of_department")
def coverage_matrix(program_id: int):
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
        columns, operational = _matrix_columns_for_program(cur, program_id, dept_id)
        cells: list[dict] = []
        for col in columns:
            for o in outcome_list:
                oid = int(o["id"])
                if col.get("col_type") == "program_course" and col.get("program_course_id"):
                    linked, src = cell_is_linked(
                        cur,
                        program_id,
                        oid,
                        program_course_id=int(col["program_course_id"]),
                    )
                elif col.get("course_master_id") is not None:
                    linked, src = cell_is_linked(
                        cur,
                        program_id,
                        oid,
                        course_master_id=int(col["course_master_id"]),
                    )
                else:
                    linked, src = False, ""
                cells.append(
                    {
                        "outcome_id": oid,
                        "col_key": col["col_key"],
                        "linked": linked,
                        "link_source": src,
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
@role_required("admin", "admin_main", "head_of_department")
def coverage_matrix_toggle(program_id: int):
    data = request.get_json(force=True) or {}
    try:
        outcome_id = int(data.get("outcome_id"))
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "outcome_id مطلوب"}), 400
    col_key = (data.get("col_key") or "").strip()
    linked = bool(data.get("linked"))
    sync_master = data.get("sync_master", True)
    if not col_key or ":" not in col_key:
        return jsonify({"status": "error", "message": "col_key غير صالح"}), 400
    kind, raw_id = col_key.split(":", 1)
    try:
        target_id = int(raw_id)
    except ValueError:
        return jsonify({"status": "error", "message": "col_key غير صالح"}), 400
    with get_connection() as conn:
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
            set_cell_link(
                cur,
                program_id,
                outcome_id,
                program_course_id=target_id,
                linked=linked,
                sync_master=bool(sync_master),
            )
        elif kind == "cm":
            set_cell_link(
                cur,
                program_id,
                outcome_id,
                course_master_id=target_id,
                linked=linked,
                sync_master=True,
            )
        else:
            return jsonify({"status": "error", "message": "نوع عمود غير معروف"}), 400
        conn.commit()
        if kind == "pc":
            ln, src = cell_is_linked(cur, program_id, outcome_id, program_course_id=target_id)
        else:
            ln, src = cell_is_linked(cur, program_id, outcome_id, course_master_id=target_id)
    return jsonify({"status": "ok", "linked": ln, "link_source": src})


@learning_outcomes_bp.route("/api/programs/<int:program_id>/add_to_plan", methods=["POST"])
@login_required
@role_required("admin", "admin_main", "head_of_department")
def add_operational_course_to_plan(program_id: int):
    """إضافة مقرر تشغيلي إلى خطة البرنامج + ربط مخرجات (اختياري)."""
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
                 plan_applicability, level_no, category, is_required, is_active)
                VALUES (?, ?, ?, ?, 'both', ?, 'required', 1, 1)
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
