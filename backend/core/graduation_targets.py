"""هدف تخرج القسم مقابل نظام الوحدات التراثي (150/155).

تمييز المصطلحات (لا تُخلط في الواجهة):
- هدف تخرج القسم: وحدات رسمية من DEPT_GRADUATION_TARGETS / لائحة
  dept_graduation_min_units (مثال CIVIL=161).
- نظام الوحدات التراثي: students.graduation_plan ∈ {150, 155}
  لطلاب الميكانيكا فقط (انتقالي قديم/جديد) — ليس «خطة منهج القسم».
- خطط التسجيل الفصلي: enrollment_plans — مفهوم تشغيلي منفصل تماماً.
"""

from __future__ import annotations

from typing import Any

from backend.core.academic_pathway import regulation_value
from backend.core.department_scope_policy import resolve_effective_department_scope_id

# استيراد متأخر لـ DEPT_GRADUATION_TARGETS لتفادي دورة استيراد عبر services/__init__
LEGACY_UNIT_SYSTEM_CODES = ("150", "155")
LEGACY_UNIT_SYSTEM_DEPT_CODE = "MECH"


def _dept_graduation_targets() -> dict[str, int]:
    from backend.services.pathway_regulations import DEPT_GRADUATION_TARGETS

    return DEPT_GRADUATION_TARGETS


def is_legacy_unit_system_code(code: str | None) -> bool:
    return (code or "").strip() in LEGACY_UNIT_SYSTEM_CODES


def department_code_for_id(cur, department_id: int | None) -> str | None:
    if department_id is None:
        return None
    row = cur.execute(
        "SELECT UPPER(TRIM(COALESCE(code, ''))) FROM departments WHERE id = ? LIMIT 1",
        (int(department_id),),
    ).fetchone()
    if not row:
        return None
    code = (row[0] if not hasattr(row, "keys") else row[0]) or ""
    code = str(code).strip().upper()
    return code or None


def department_name_for_id(cur, department_id: int | None) -> str:
    if department_id is None:
        return ""
    row = cur.execute(
        "SELECT COALESCE(name_ar, name_en, code, '') FROM departments WHERE id = ? LIMIT 1",
        (int(department_id),),
    ).fetchone()
    if not row:
        return ""
    return str((row[0] if not hasattr(row, "keys") else row[0]) or "").strip()


def graduation_target_units_for_department(
    cur,
    department_id: int | None,
    department_code: str | None = None,
) -> int | None:
    """وحدات التخرج الرسمية للقسم (شاملة الاتجاه العام)."""
    code = (department_code or department_code_for_id(cur, department_id) or "").strip().upper()
    targets = _dept_graduation_targets()
    default = None
    if code and code in targets:
        default = float(targets[code])
    if department_id is not None:
        v = regulation_value(
            cur,
            int(department_id),
            "dept_graduation_min_units",
            default=default,
            college_fallback=False,
        )
        if v is not None:
            try:
                return int(float(v))
            except (TypeError, ValueError):
                pass
    if default is not None:
        return int(default)
    return None


def resolve_student_department_id(cur, student_id: str | None) -> int | None:
    sid = (student_id or "").strip()
    if not sid:
        return None
    row = cur.execute(
        "SELECT department_id FROM students WHERE student_id = ? LIMIT 1",
        (sid,),
    ).fetchone()
    if not row:
        return None
    raw = row[0] if not hasattr(row, "keys") else row["department_id"]
    if raw in (None, ""):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def build_graduation_plan_options(
    conn,
    *,
    student_id: str | None = None,
    department_id: int | None = None,
    actor_username: str | None = None,
    current_legacy_plan: str | None = None,
) -> dict[str, Any]:
    """خيارات واجهة «خطة التخرج» حسب قسم الطالب أو نطاق الفاعل."""
    cur = conn.cursor()
    dep_id = department_id
    if dep_id is None and student_id:
        dep_id = resolve_student_department_id(cur, student_id)
    if dep_id is None and actor_username:
        dep_id = resolve_effective_department_scope_id(conn, actor_username)

    code = department_code_for_id(cur, dep_id) if dep_id is not None else None
    name = department_name_for_id(cur, dep_id) if dep_id is not None else ""
    target = graduation_target_units_for_department(cur, dep_id, code)

    legacy_current = (current_legacy_plan or "").strip()
    if student_id and not legacy_current:
        row = cur.execute(
            "SELECT COALESCE(graduation_plan, '') FROM students WHERE student_id = ? LIMIT 1",
            ((student_id or "").strip(),),
        ).fetchone()
        if row:
            legacy_current = str((row[0] if not hasattr(row, "keys") else row[0]) or "").strip()
    if not is_legacy_unit_system_code(legacy_current):
        legacy_current = ""

    legacy_applicable = code == LEGACY_UNIT_SYSTEM_DEPT_CODE
    if target is not None:
        label_ar = f"{target} وحدة — خطة القسم"
    elif dep_id is None:
        label_ar = "حدّد القسم أولاً لعرض خطة التخرج"
    else:
        label_ar = "هدف تخرج القسم غير معرّف"

    return {
        "department_id": int(dep_id) if dep_id is not None else None,
        "department_code": code or "",
        "department_name": name,
        "graduation_target_units": target,
        "legacy_unit_system": {
            "applicable": legacy_applicable,
            "allowed_codes": list(LEGACY_UNIT_SYSTEM_CODES) if legacy_applicable else [],
            "current": legacy_current if legacy_applicable else "",
        },
        "label_ar": label_ar,
        "needs_department": dep_id is None,
    }


def sync_program_major_min_units(conn) -> list[dict[str, Any]]:
    """مزامنة programs.min_total_units لـ PROG_MAJOR مع DEPT_GRADUATION_TARGETS."""
    cur = conn.cursor()
    cols = {
        r[1] if not hasattr(r, "keys") else r["name"]
        for r in cur.execute("PRAGMA table_info(programs)").fetchall()
    }
    if "min_total_units" not in cols:
        return []
    changed: list[dict[str, Any]] = []
    for code, units in _dept_graduation_targets().items():
        row = cur.execute(
            """
            SELECT p.id, p.min_total_units
            FROM programs p
            JOIN departments d ON d.id = p.department_id
            WHERE UPPER(TRIM(COALESCE(d.code, ''))) = ?
              AND UPPER(TRIM(COALESCE(p.code, ''))) = 'PROG_MAJOR'
            LIMIT 1
            """,
            (code.upper(),),
        ).fetchone()
        if not row:
            continue
        pid = int(row[0] if not hasattr(row, "keys") else row["id"])
        old = row[1] if not hasattr(row, "keys") else row["min_total_units"]
        try:
            old_i = int(old) if old is not None else None
        except (TypeError, ValueError):
            old_i = None
        if old_i == int(units):
            continue
        cur.execute(
            "UPDATE programs SET min_total_units = ? WHERE id = ?",
            (int(units), pid),
        )
        changed.append(
            {
                "department_code": code,
                "program_id": pid,
                "old_min_total_units": old_i,
                "new_min_total_units": int(units),
            }
        )
    return changed
