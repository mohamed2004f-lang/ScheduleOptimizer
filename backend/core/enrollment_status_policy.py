"""سياسة حالة قيد الطالب: التشغيل اليومي مقابل السجل الأرشيفي (خريج/إيقاف/سحب)."""
from __future__ import annotations

from typing import Any

ENROLLMENT_ACTIVE = "active"
ENROLLMENT_WITHDRAWN = "withdrawn"
ENROLLMENT_SUSPENDED = "suspended"
ENROLLMENT_GRADUATED = "graduated"

ALLOWED_ENROLLMENT_STATUSES = frozenset(
    {ENROLLMENT_ACTIVE, ENROLLMENT_WITHDRAWN, ENROLLMENT_SUSPENDED, ENROLLMENT_GRADUATED}
)
OPERATIONAL_ENROLLMENT_STATUSES = frozenset({ENROLLMENT_ACTIVE})


def normalize_enrollment_status(value: Any) -> str:
    s = str(value or ENROLLMENT_ACTIVE).strip().lower()
    return s if s in ALLOWED_ENROLLMENT_STATUSES else ENROLLMENT_ACTIVE


def is_operational_enrollment(value: Any) -> bool:
    return normalize_enrollment_status(value) in OPERATIONAL_ENROLLMENT_STATUSES


def is_alumni_enrollment(value: Any) -> bool:
    return normalize_enrollment_status(value) == ENROLLMENT_GRADUATED


def operational_status_sql(alias: str | None = None) -> str:
    col = f"{alias}.enrollment_status" if alias else "enrollment_status"
    return f"COALESCE({col}, 'active') = 'active'"


def lookup_student_enrollment_status(student_id: str | None) -> str:
    sid = str(student_id or "").strip()
    if not sid:
        return ENROLLMENT_ACTIVE
    try:
        from backend.database.database import fetch_table_columns, get_connection

        with get_connection() as conn:
            cols = fetch_table_columns(conn, "students")
            if "enrollment_status" not in cols:
                return ENROLLMENT_ACTIVE
            row = conn.cursor().execute(
                "SELECT COALESCE(enrollment_status, 'active') FROM students WHERE student_id = ? LIMIT 1",
                (sid,),
            ).fetchone()
        if not row:
            return ENROLLMENT_ACTIVE
        raw = row[0] if not hasattr(row, "keys") else row[0]
        return normalize_enrollment_status(raw)
    except Exception:
        return ENROLLMENT_ACTIVE


def apply_alumni_student_caps(caps: dict | None) -> dict:
    """بوابة خريج: كشف ووثائق وتقدّم — بدون تشغيل فصلي."""
    out = caps if isinstance(caps, dict) else {}
    out["alumni_mode"] = True
    out["enrollment_status"] = ENROLLMENT_GRADUATED
    out["nav_student_registrations"] = False
    out["nav_planning_student_view"] = False
    out["nav_student_course_evaluations"] = False
    out["nav_student_schedule"] = False
    out["nav_student_exams"] = False
    out["nav_student_requests"] = False
    out["nav_student_announcements"] = False
    out["nav_student_course_pages"] = False
    out["nav_student_portal"] = True
    out["nav_student_hub_more"] = True
    out["nav_student_academic_identity"] = True
    out["nav_student_academic_progress"] = True
    out["nav_transcript_nav"] = True
    return out
