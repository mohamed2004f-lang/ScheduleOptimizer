"""شبكة مستويات خطة البرنامج + روابط المتطلبات السابقة."""

from __future__ import annotations

from typing import Any

from backend.core.academic_pathway import REQUIREMENT_SCOPE_LABELS, normalize_requirement_scope


def _row_dict(row: Any, keys: list[str] | None = None) -> dict[str, Any]:
    if row is None:
        return {}
    if hasattr(row, "keys"):
        return {k: row[k] for k in row.keys()}
    if keys:
        return {keys[i]: row[i] for i in range(min(len(keys), len(row)))}
    return {}


def _rows_as_dicts(cur, sql: str, params=()) -> list[dict[str, Any]]:
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


def load_program_courses_for_grid(cur, program_id: int) -> list[dict[str, Any]]:
    return _rows_as_dicts(
        cur,
        """
        SELECT pc.id, pc.program_id, pc.course_code, pc.level_no,
               COALESCE(pc.requirement_scope, 'dept_common') AS requirement_scope,
               COALESCE(pc.units_override, cm.default_units, 0) AS units,
               COALESCE(pc.course_name_override, '') AS course_name_override,
               cm.title_ar AS title_ar, cm.id AS course_master_id
        FROM program_courses pc
        INNER JOIN course_master cm ON cm.id = pc.course_master_id
        WHERE pc.program_id = ? AND COALESCE(pc.is_active, 1) = 1
        ORDER BY pc.level_no, pc.course_code
        """,
        (int(program_id),),
    )


def load_prereq_edges(cur, program_id: int) -> list[dict[str, Any]]:
    rows = _rows_as_dicts(
        cur,
        """
        SELECT pr.id, pr.program_course_id, pr.required_program_course_id,
               pr.required_course_master_id, pr.note,
               pc.course_code AS course_code,
               pc.level_no AS level_no,
               rpc.course_code AS required_course_code,
               rpc.level_no AS required_level_no
        FROM program_course_prereqs pr
        INNER JOIN program_courses pc ON pc.id = pr.program_course_id
        LEFT JOIN program_courses rpc ON rpc.id = pr.required_program_course_id
        WHERE pc.program_id = ?
        ORDER BY pr.id
        """,
        (int(program_id),),
    )
    return rows


def build_program_plan_grid(cur, program_id: int) -> dict[str, Any]:
    """مجموعات المستوى + حواف المتطلبات السابقة."""
    courses = load_program_courses_for_grid(cur, program_id)
    by_level: dict[int, list[dict[str, Any]]] = {}
    max_level = 0
    for c in courses:
        lv = int(c.get("level_no") or 0)
        max_level = max(max_level, lv)
        scope = normalize_requirement_scope(c.get("requirement_scope"))
        by_level.setdefault(lv, []).append(
            {
                "id": c.get("id"),
                "course_code": c.get("course_code"),
                "title_ar": (c.get("course_name_override") or c.get("title_ar") or "").strip(),
                "units": int(c.get("units") or 0),
                "requirement_scope": scope,
                "requirement_scope_label": REQUIREMENT_SCOPE_LABELS.get(scope, scope),
                "level_no": lv,
                "course_master_id": c.get("course_master_id"),
            }
        )
    levels = [
        {
            "level_no": lv,
            "courses": by_level[lv],
            "course_count": len(by_level[lv]),
            "units_sum": sum(int(x.get("units") or 0) for x in by_level[lv]),
        }
        for lv in sorted(by_level.keys())
    ]
    edges = []
    for e in load_prereq_edges(cur, program_id):
        edges.append(
            {
                "id": e.get("id"),
                "from_program_course_id": e.get("required_program_course_id"),
                "to_program_course_id": e.get("program_course_id"),
                "from_code": e.get("required_course_code"),
                "to_code": e.get("course_code"),
                "note": (e.get("note") or "").strip(),
            }
        )
    return {
        "program_id": int(program_id),
        "max_level": max_level,
        "level_count": len(levels),
        "course_count": len(courses),
        "levels": levels,
        "edges": edges,
    }
