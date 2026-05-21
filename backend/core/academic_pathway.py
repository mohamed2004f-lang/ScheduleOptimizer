"""مسار الطالب ومستوى المتطلبات في خطة البرنامج (بدون تأسيس 150/155)."""

from __future__ import annotations

# مراحل مسار الطالب
PATHWAY_STAGES = (
    "college_general",      # دفعة جديدة — لا يزال في الاتجاه العام (PROG_U1)
    "transfer_pending",     # أنجز عتبة الانتقال — بانتظار القسم
    "dept_admitted",        # داخل القسم — لم يتخصص بعد
    "dept_pre_track",       # أنجز جزءاً من متطلبات ما قبل الشعبة
    "specialized",          # دخل شعبة (track_code)
    "graduation_pending",
)

DEFAULT_PATHWAY_STAGE = "dept_admitted"
COLLEGE_PATHWAY_STAGES = frozenset({"college_general", "transfer_pending"})

PATHWAY_STAGE_LABELS = {
    "college_general": "الاتجاه العام (كلية)",
    "transfer_pending": "بانتظار الانتقال للقسم",
    "dept_admitted": "داخل القسم (بعد الاتجاه العام)",
    "dept_pre_track": "ما قبل التخصص (شعبة)",
    "specialized": "متخصص (شعبة)",
    "graduation_pending": "قرب التخرج",
}

COLLEGE_GENERAL_PROGRAM_CODE = "PROG_U1"
COLLEGE_GENERAL_DEPT_CODE = "GENERAL"

# نطاق المتطلب في بند الخطة
REQUIREMENT_SCOPES = (
    "college_general",  # محجوز للمستقبل — اتجاه عام الكلية
    "dept_common",      # مشترك لكل طلاب القسم
    "pre_track",        # قبل اختيار الشعبة
    "track",            # خاص بشعبة / مسار
    "elective",
)

DEFAULT_REQUIREMENT_SCOPE = "dept_common"

REQUIREMENT_SCOPE_LABELS = {
    "college_general": "اتجاه عام (كلية — ضمن التخرج)",
    "dept_common": "مشترك للقسم (قديم)",
    "pre_track": "قبل اختيار الشعبة",
    "track": "شعبة / تخصص",
    "elective": "اختياري",
}


def normalize_requirement_scope(value: str | None) -> str:
    v = (value or "").strip().lower()
    if v in REQUIREMENT_SCOPES:
        return v
    return DEFAULT_REQUIREMENT_SCOPE


def normalize_pathway_stage(value: str | None) -> str:
    v = (value or "").strip().lower()
    if v in PATHWAY_STAGES:
        return v
    return DEFAULT_PATHWAY_STAGE


def regulation_value(
    cur,
    department_id: int | None,
    rule_key: str,
    *,
    default: float | None = None,
    college_fallback: bool = True,
) -> float | None:
    """قراءة قيمة بند لائحة مسار (من pathway_regulation_items)."""
    from backend.services.pathway_regulations import get_pathway_regulation_value

    if department_id is not None:
        v = get_pathway_regulation_value(cur, int(department_id), rule_key, default=None)
        if v is not None:
            return v
    if college_fallback:
        row = cur.execute(
            "SELECT id FROM departments WHERE UPPER(TRIM(code)) = 'GENERAL' LIMIT 1"
        ).fetchone()
        if row:
            gid = int(row[0] if not hasattr(row, "keys") else row["id"])
            v = get_pathway_regulation_value(cur, gid, rule_key, default=None)
            if v is not None:
                return v
    return default


def _row_id(row) -> int | None:
    if row is None:
        return None
    try:
        return int(row[0])
    except (TypeError, IndexError, KeyError):
        pass
    if hasattr(row, "keys"):
        v = row.get("id")
        return int(v) if v is not None else None
    return None


def resolve_college_general_program_id(cur) -> int | None:
    """برنامج المرحلة التأسيسية PROG_U1."""
    row = cur.execute(
        """
        SELECT p.id FROM programs p
        INNER JOIN departments d ON d.id = p.department_id
        WHERE UPPER(TRIM(d.code)) = ?
          AND UPPER(TRIM(p.code)) = ?
        ORDER BY COALESCE(p.is_active, 1) DESC, p.id
        LIMIT 1
        """,
        (COLLEGE_GENERAL_DEPT_CODE, COLLEGE_GENERAL_PROGRAM_CODE),
    ).fetchone()
    return _row_id(row)


def resolve_college_general_department_id(cur) -> int | None:
    row = cur.execute(
        "SELECT id FROM departments WHERE UPPER(TRIM(code)) = ? LIMIT 1",
        (COLLEGE_GENERAL_DEPT_CODE,),
    ).fetchone()
    return _row_id(row)


def _parse_join_year_int(join_year: str | None) -> int | None:
    digits = "".join(c for c in (join_year or "") if c.isdigit())
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


def college_pathway_cohort_cutoff(cur, department_id: int | None = None) -> int | None:
    """سنة الالتحاق الهجرية الأدنى لتفعيل مسار الكلية (0 أو غياب = معطّل)."""
    v = regulation_value(
        cur,
        department_id,
        "college_pathway_cohort_from_join_year",
        default=None,
        college_fallback=True,
    )
    if v is None:
        return None
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def student_uses_college_pathway(cur, student: dict) -> bool:
    """هل يُراجع الطالب ضد خطة PROG_U1 بالإضافة لخطة القسم؟"""
    stage = normalize_pathway_stage(student.get("pathway_stage"))
    if stage in COLLEGE_PATHWAY_STAGES:
        return True
    adm = student.get("admission_program_id")
    if adm not in (None, ""):
        row = cur.execute(
            """
            SELECT p.code, p.phase FROM programs p WHERE p.id = ? LIMIT 1
            """,
            (int(adm),),
        ).fetchone()
        if row:
            code = str(row[0] if not hasattr(row, "keys") else row["code"] or "").strip().upper()
            phase = str(row[1] if not hasattr(row, "keys") else row.get("phase") or "").strip().lower()
            if code == COLLEGE_GENERAL_PROGRAM_CODE or phase == "general":
                return True
    jy = _parse_join_year_int(student.get("join_year"))
    cutoff = college_pathway_cohort_cutoff(cur, student.get("department_id"))
    if cutoff is not None and jy is not None and jy >= cutoff:
        return True
    return False


def resolve_operating_mode(cur, student: dict | None) -> str:
    if student and student_uses_college_pathway(cur, student):
        return "college_and_dept"
    return "dept_only"


def cohort_defaults_for_new_student(cur, join_year: str | None) -> dict[str, int | str] | None:
    """
    حقول افتراضية لدفعة الاتجاه العام (department_id، admission/current program، pathway_stage).
    يُرجع None إذا لم تُفعَّل الدفعة.
    """
    jy = _parse_join_year_int(join_year)
    cutoff = college_pathway_cohort_cutoff(cur, None)
    if cutoff is None or jy is None or jy < cutoff:
        return None
    dept_id = resolve_college_general_department_id(cur)
    prog_id = resolve_college_general_program_id(cur)
    if not dept_id or not prog_id:
        return None
    return {
        "department_id": int(dept_id),
        "admission_program_id": int(prog_id),
        "current_program_id": int(prog_id),
        "pathway_stage": "college_general",
    }


def infer_pathway_stage(
    *,
    track_code: str | None = None,
    specialized_at_term: str | None = None,
    explicit: str | None = None,
) -> str:
    if explicit:
        return normalize_pathway_stage(explicit)
    if (track_code or "").strip() or (specialized_at_term or "").strip():
        return "specialized"
    return DEFAULT_PATHWAY_STAGE
