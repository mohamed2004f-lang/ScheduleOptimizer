"""
حاسبة مسار الطالب — منجز / متبقي حسب نطاق المتطلب وخطة البرامج (155 شاملة 36).
"""

from __future__ import annotations

import re
from typing import Any

from backend.core.academic_pathway import (
    REQUIREMENT_SCOPE_LABELS,
    normalize_pathway_stage,
    normalize_requirement_scope,
    regulation_value,
    resolve_college_general_program_id,
    resolve_operating_mode,
    student_uses_college_pathway,
)
from backend.core.program_tracks import resolve_base_program_id

PASSING_GRADE = 50.0

SCOPE_ORDER = (
    "college_general",
    "pre_track",
    "dept_common",
    "track",
    "elective",
)


def normalize_course_code(code: str | None) -> str:
    return re.sub(r"\s+", "", (code or "").strip().upper())


def _row_val(row: Any, idx: int = 0, key: str | None = None) -> Any:
    if row is None:
        return None
    if key and hasattr(row, "keys"):
        try:
            return row[key]
        except (KeyError, TypeError, IndexError):
            pass
    try:
        return row[idx]
    except (TypeError, IndexError):
        return None


def _load_student_row(cur, student_id: str) -> dict[str, Any] | None:
    row = cur.execute(
        """
        SELECT student_id, COALESCE(student_name, '') AS student_name,
               department_id, current_program_id, admission_program_id,
               COALESCE(track_code, '') AS track_code,
               COALESCE(pathway_stage, 'dept_admitted') AS pathway_stage,
               COALESCE(graduation_plan, '') AS graduation_plan
        FROM students WHERE student_id = ? LIMIT 1
        """,
        (student_id,),
    ).fetchone()
    if not row:
        return None
    if hasattr(row, "keys"):
        return {k: row[k] for k in row.keys()}
    return {
        "student_id": row[0],
        "student_name": row[1],
        "department_id": row[2],
        "current_program_id": row[3],
        "admission_program_id": row[4],
        "track_code": row[5],
        "pathway_stage": row[6],
        "graduation_plan": row[7],
    }


def _dept_code(cur, department_id: int | None) -> str | None:
    if department_id is None:
        return None
    row = cur.execute(
        "SELECT code FROM departments WHERE id = ? LIMIT 1",
        (int(department_id),),
    ).fetchone()
    if not row:
        return None
    return str(_row_val(row, 0, "code") or "").strip()


def _program_meta(cur, program_id: int) -> dict[str, Any] | None:
    row = cur.execute(
        """
        SELECT p.id, p.code, p.name_ar, COALESCE(p.track_group, '') AS track_group,
               p.department_id, d.code AS department_code
        FROM programs p
        LEFT JOIN departments d ON d.id = p.department_id
        WHERE p.id = ?
        """,
        (int(program_id),),
    ).fetchone()
    if not row:
        return None
    if hasattr(row, "keys"):
        return {k: row[k] for k in row.keys()}
    return {
        "id": row[0],
        "code": row[1],
        "name_ar": row[2],
        "track_group": row[3],
        "department_id": row[4],
        "department_code": row[5],
    }


def _resolve_track_program_id(cur, department_id: int, track_code: str) -> int | None:
    tc = (track_code or "").strip().upper()
    if not tc:
        return None
    row = cur.execute(
        """
        SELECT id FROM programs
        WHERE department_id = ? AND UPPER(TRIM(COALESCE(track_group, ''))) = ?
        ORDER BY COALESCE(is_active, 1) DESC, id
        LIMIT 1
        """,
        (int(department_id), tc),
    ).fetchone()
    if not row:
        return None
    return int(_row_val(row, 0, "id"))


def _programs_for_audit(cur, student: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if student_uses_college_pathway(cur, student):
        college_pid = resolve_college_general_program_id(cur)
        if college_pid:
            cmeta = _program_meta(cur, int(college_pid))
            if cmeta:
                out.append({**cmeta, "role": "college", "program_id": int(college_pid)})

    dept_id = student.get("department_id")
    if dept_id in (None, ""):
        return out
    dept_code = _dept_code(cur, int(dept_id)) or "MECH"
    if dept_code.upper() == "GENERAL":
        return out
    base_id = resolve_base_program_id(cur, dept_code)
    if not base_id:
        return out
    base_meta = _program_meta(cur, int(base_id))
    if base_meta:
        out.append({**base_meta, "role": "base", "program_id": int(base_id)})

    track_pid = None
    cur_pid = student.get("current_program_id")
    if cur_pid not in (None, ""):
        meta = _program_meta(cur, int(cur_pid))
        if meta and (meta.get("track_group") or "").strip():
            track_pid = int(cur_pid)
    if track_pid is None:
        track_pid = _resolve_track_program_id(
            cur, int(dept_id), str(student.get("track_code") or "")
        )
    if track_pid and track_pid != int(base_id):
        tmeta = _program_meta(cur, int(track_pid))
        if tmeta:
            out.append({**tmeta, "role": "track", "program_id": int(track_pid)})
    return out


def _load_plan_courses(cur, program_ids: list[int]) -> list[dict[str, Any]]:
    if not program_ids:
        return []
    placeholders = ",".join("?" for _ in program_ids)
    rows = cur.execute(
        f"""
        SELECT pc.id, pc.program_id, pc.course_code, pc.level_no,
               COALESCE(pc.requirement_scope, 'dept_common') AS requirement_scope,
               COALESCE(pc.units_override, cm.default_units, 0) AS units,
               cm.title_ar AS title_ar, p.code AS program_code
        FROM program_courses pc
        INNER JOIN course_master cm ON cm.id = pc.course_master_id
        INNER JOIN programs p ON p.id = pc.program_id
        WHERE pc.program_id IN ({placeholders})
          AND COALESCE(pc.is_active, 1) = 1
        ORDER BY pc.program_id, pc.level_no, pc.course_code
        """,
        tuple(int(x) for x in program_ids),
    ).fetchall()
    items: list[dict[str, Any]] = []
    for r in rows or []:
        if hasattr(r, "keys"):
            items.append({k: r[k] for k in r.keys()})
        else:
            items.append(
                {
                    "id": r[0],
                    "program_id": r[1],
                    "course_code": r[2],
                    "level_no": r[3],
                    "requirement_scope": r[4],
                    "units": int(r[5] or 0),
                    "title_ar": r[6],
                    "program_code": r[7],
                }
            )
    return items


def _lookup_course_code(cur, course_name: str) -> str:
    name = (course_name or "").strip()
    if not name:
        return ""
    row = cur.execute(
        "SELECT COALESCE(course_code, '') FROM courses WHERE course_name = ? LIMIT 1",
        (name,),
    ).fetchone()
    if row:
        code = str(_row_val(row, 0, "course_code") or "").strip()
        if code:
            return code
    row = cur.execute(
        """
        SELECT COALESCE(code, '') FROM course_master
        WHERE TRIM(COALESCE(title_ar, '')) = ? OR TRIM(COALESCE(code, '')) = ?
        LIMIT 1
        """,
        (name, name),
    ).fetchone()
    if row:
        return str(_row_val(row, 0, "code") or "").strip()
    return ""


def _load_passed_pool(cur, student_id: str) -> list[dict[str, Any]]:
    from backend.services.grades import _load_transcript_data

    data = _load_transcript_data(student_id)
    pool: list[dict[str, Any]] = []
    for item in data.get("completed_units_breakdown") or []:
        if not item.get("passed"):
            continue
        name = (item.get("course_name") or "").strip()
        units = int(item.get("units_used") or 0)
        code = _lookup_course_code(cur, name)
        pool.append(
            {
                "course_name": name,
                "course_code": code,
                "code_norm": normalize_course_code(code),
                "units": units,
                "used": False,
            }
        )
    return pool


def _match_plan_course(pc: dict[str, Any], pool: list[dict[str, Any]]) -> dict[str, Any] | None:
    pcode = normalize_course_code(pc.get("course_code"))
    title = (pc.get("title_ar") or "").strip().lower()
    for entry in pool:
        if entry.get("used"):
            continue
        if pcode and entry.get("code_norm") and pcode == entry["code_norm"]:
            entry["used"] = True
            return entry
        if pcode and normalize_course_code(entry.get("course_code")) == pcode:
            entry["used"] = True
            return entry
        ename = (entry.get("course_name") or "").strip().lower()
        if title and ename and (title == ename or title in ename or ename in title):
            entry["used"] = True
            return entry
    return None


def _empty_scope_bucket() -> dict[str, Any]:
    return {
        "required_units": 0,
        "completed_units": 0,
        "remaining_units": 0,
        "courses_required": 0,
        "courses_completed": 0,
        "courses_remaining": 0,
    }


def compute_pathway_progress(cur, student_id: str) -> dict[str, Any]:
    """
    يحسب منجز/متبقي للطالب مقابل خطة MECH (+ برنامج الشعبة إن وُجد).
    """
    student = _load_student_row(cur, student_id)
    if not student:
        return {"status": "error", "message": "الطالب غير موجود"}

    programs = _programs_for_audit(cur, student)
    if not programs:
        return {"status": "error", "message": "لا يوجد برنامج قسم لحساب المسار"}

    dept_id = int(student["department_id"])
    dept_code = _dept_code(cur, dept_id) or "MECH"

    grad_target = int(
        regulation_value(cur, dept_id, "dept_graduation_min_units", default=155) or 155
    )
    college_target = int(
        regulation_value(
            cur, dept_id, "college_general_total_units", default=36, college_fallback=True
        )
        or 36
    )
    transfer_min = int(
        regulation_value(
            cur, dept_id, "transfer_to_department_min_units", default=22, college_fallback=True
        )
        or 22
    )

    program_ids = [int(p["program_id"]) for p in programs]
    plan_items = _load_plan_courses(cur, program_ids)
    pool = _load_passed_pool(cur, student_id)

    by_scope: dict[str, dict[str, Any]] = {
        sc: _empty_scope_bucket() for sc in SCOPE_ORDER
    }
    course_rows: list[dict[str, Any]] = []
    plan_completed_units = 0

    for pc in plan_items:
        scope = normalize_requirement_scope(pc.get("requirement_scope"))
        units = max(0, int(pc.get("units") or 0))
        bucket = by_scope.setdefault(scope, _empty_scope_bucket())
        bucket["required_units"] += units
        bucket["courses_required"] += 1

        matched = _match_plan_course(pc, pool)
        done = matched is not None
        completed_u = units if done else 0
        if done:
            bucket["completed_units"] += completed_u
            bucket["courses_completed"] += 1
            plan_completed_units += completed_u

        course_rows.append(
            {
                "program_course_id": pc.get("id"),
                "program_code": pc.get("program_code"),
                "course_code": pc.get("course_code"),
                "title_ar": pc.get("title_ar"),
                "requirement_scope": scope,
                "requirement_scope_label": REQUIREMENT_SCOPE_LABELS.get(scope, scope),
                "units": units,
                "completed": done,
                "matched_course_name": (matched or {}).get("course_name") if matched else None,
            }
        )

    for scope, bucket in by_scope.items():
        bucket["remaining_units"] = max(
            0, int(bucket["required_units"]) - int(bucket["completed_units"])
        )
        bucket["courses_remaining"] = max(
            0, int(bucket["courses_required"]) - int(bucket["courses_completed"])
        )
        bucket["label"] = REQUIREMENT_SCOPE_LABELS.get(scope, scope)

    plan_required_total = sum(int(by_scope.get(sc, _empty_scope_bucket())["required_units"]) for sc in by_scope)
    college_completed = int(by_scope.get("college_general", _empty_scope_bucket())["completed_units"])
    college_required = int(by_scope.get("college_general", _empty_scope_bucket())["required_units"])

    unmatched_passed = [
        {
            "course_name": e.get("course_name"),
            "course_code": e.get("course_code"),
            "units": e.get("units"),
        }
        for e in pool
        if not e.get("used")
    ]

    plan_gaps = [c for c in course_rows if not c.get("completed")]

    pre_units = (
        int(by_scope.get("pre_track", _empty_scope_bucket())["completed_units"])
        + int(by_scope.get("dept_common", _empty_scope_bucket())["completed_units"])
    )
    pre_required = (
        int(by_scope.get("pre_track", _empty_scope_bucket())["required_units"])
        + int(by_scope.get("dept_common", _empty_scope_bucket())["required_units"])
    )
    track_completed = int(by_scope.get("track", _empty_scope_bucket())["completed_units"])
    track_required = int(by_scope.get("track", _empty_scope_bucket())["required_units"])

    operating_mode = resolve_operating_mode(cur, student)

    return {
        "status": "ok",
        "operating_mode": operating_mode,
        "uses_college_pathway": student_uses_college_pathway(cur, student),
        "student_id": student_id,
        "student_name": student.get("student_name") or "",
        "pathway_stage": normalize_pathway_stage(student.get("pathway_stage")),
        "track_code": (student.get("track_code") or "").strip(),
        "graduation_plan_legacy": (student.get("graduation_plan") or "").strip(),
        "department_code": dept_code,
        "programs": [
            {
                "program_id": p["program_id"],
                "code": p.get("code"),
                "name_ar": p.get("name_ar"),
                "role": p.get("role"),
                "track_group": p.get("track_group"),
            }
            for p in programs
        ],
        "targets": {
            "graduation_total": grad_target,
            "college_general": college_target,
            "transfer_to_department_min": transfer_min,
            "note_ar": "وحدات التخرج 155 شاملة اتجاه عام 36 (ليست 155+36).",
        },
        "by_scope": by_scope,
        "summary_pre_track": {
            "label": "قبل الشعبة (يشمل dept_common)",
            "required_units": pre_required,
            "completed_units": pre_units,
            "remaining_units": max(0, pre_required - pre_units),
        },
        "totals": {
            "plan_required_units": plan_required_total,
            "plan_completed_units": plan_completed_units,
            "graduation_target": grad_target,
            "graduation_remaining": max(0, grad_target - plan_completed_units),
            "college_general_required_in_plan": college_required,
            "college_general_completed": college_completed,
            "college_general_target": college_target,
            "college_general_remaining": max(0, college_target - college_completed),
            "track_required": track_required,
            "track_completed": track_completed,
            "track_remaining": max(0, track_required - track_completed),
        },
        "flags": {
            "college_general_met": college_completed >= college_target
            or (college_required > 0 and college_completed >= college_required),
            "plan_units_match_graduation": plan_required_total == grad_target,
            "transfer_gate_met": college_completed >= transfer_min,
        },
        "courses": course_rows,
        "unmatched_passed_count": len(unmatched_passed),
        "unmatched_passed": unmatched_passed[:15],
        "plan_gaps_count": len(plan_gaps),
        "plan_gaps": plan_gaps[:20],
    }
