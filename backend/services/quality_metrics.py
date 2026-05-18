"""حساب مؤشرات ضمان الجودة والاعتماد من بيانات النظام."""

from __future__ import annotations

import json
from typing import Any

from backend.database.database import fetch_table_columns, schedule_pk_column, table_exists
from backend.services.utilities import get_current_term, SEMESTER_LABEL


def term_label_from_conn(conn) -> str:
    try:
        tname, tyear = get_current_term(conn=conn)
        label = f"{(tname or '').strip()} {(tyear or '').strip()}".strip()
        return label or SEMESTER_LABEL
    except Exception:
        return SEMESTER_LABEL


def _row_val(row, idx: int = 0, key: str | None = None):
    if row is None:
        return None
    if key and hasattr(row, "keys"):
        try:
            return row[key]
        except (KeyError, TypeError):
            pass
    try:
        return row[idx]
    except (IndexError, TypeError):
        return None


def _legacy_eval_avg_sql() -> str:
    return """(
        COALESCE(e.instructor_punctuality, 0) +
        COALESCE(e.course_clarity, 0) +
        COALESCE(e.assessment_fairness, 0) +
        COALESCE(e.material_relevance, 0) +
        COALESCE(e.communication_quality, 0)
    ) / 5.0"""


def _avg_eval_score(conn, cur, semester: str, department_id: int | None = None) -> float:
    dept_sql = ""
    params: list[Any] = [semester]
    if department_id is not None:
        dept_sql = """
            AND EXISTS (
                SELECT 1 FROM schedule sch
                WHERE sch.id = e.section_id AND sch.department_id = ?
            )
        """
        params.append(int(department_id))
    use_dynamic = table_exists(conn, "evaluation_survey_answers")
    if use_dynamic:
        row = cur.execute(
            f"""
            SELECT AVG(
                COALESCE(
                    (
                        SELECT AVG(a.rating * 1.0)
                        FROM evaluation_survey_answers a
                        WHERE a.evaluation_id = e.id
                    ),
                    {_legacy_eval_avg_sql()}
                )
            )
            FROM course_evaluations e
            WHERE e.semester = ? {dept_sql}
            """,
            tuple(params),
        ).fetchone()
    else:
        row = cur.execute(
            f"""
            SELECT AVG({_legacy_eval_avg_sql()})
            FROM course_evaluations e
            WHERE e.semester = ? {dept_sql}
            """,
            tuple(params),
        ).fetchone()
    avg5 = float(_row_val(row, 0) or 0)
    return (avg5 / 5.0) * 100.0 if avg5 else 0.0


def _reports_completion(conn, cur, semester: str, department_id: int | None = None) -> float:
    pk = schedule_pk_column(conn)
    dept_sql = ""
    params: list[Any] = [semester]
    if department_id is not None:
        dept_sql = " AND sch.department_id = ?"
        params.append(int(department_id))
    total_row = cur.execute(
        f"""
        SELECT COUNT(DISTINCT sch.{pk})
        FROM schedule sch
        WHERE COALESCE(sch.semester,'') = ? AND COALESCE(sch.instructor_id, 0) > 0 {dept_sql}
        """,
        tuple(params),
    ).fetchone()
    total = int(_row_val(total_row, 0) or 0)
    if total <= 0:
        return 0.0
    sub_row = cur.execute(
        f"""
        SELECT COUNT(DISTINCT c.section_id)
        FROM course_closure_reports c
        JOIN schedule sch ON sch.{pk} = c.section_id
        WHERE c.semester = ? AND c.status IN ('submitted', 'approved') {dept_sql}
        """,
        tuple(params),
    ).fetchone()
    submitted = int(_row_val(sub_row, 0) or 0)
    return min(100.0, (submitted / total) * 100.0)


def _avg_ilo(conn, cur, semester: str, department_id: int | None = None) -> float:
    cols = {c.lower() for c in fetch_table_columns(conn, "course_closure_reports")}
    if "ilo_achievement_percent" not in cols:
        return 0.0
    dept_sql = ""
    params: list[Any] = [semester]
    if department_id is not None:
        dept_sql = """
            AND EXISTS (
                SELECT 1 FROM schedule sch
                WHERE sch.id = c.section_id AND sch.department_id = ?
            )
        """
        params.append(int(department_id))
    row = cur.execute(
        f"""
        SELECT AVG(c.ilo_achievement_percent)
        FROM course_closure_reports c
        WHERE c.semester = ? AND c.ilo_achievement_percent IS NOT NULL {dept_sql}
        """,
        tuple(params),
    ).fetchone()
    return float(_row_val(row, 0) or 0)


def _graduation_proxy(cur, department_id: int | None = None) -> float:
    """تقريب معدل التخرج: نسبة الطلاب النشطين بمعدل تراكمي ≥ 50%."""
    dept_sql = ""
    params: list[Any] = []
    if department_id is not None:
        dept_sql = " AND s.department_id = ?"
        params.append(int(department_id))
    rows = cur.execute(
        f"""
        SELECT s.student_id
        FROM students s
        WHERE COALESCE(s.enrollment_status, 'active') = 'active' {dept_sql}
        """,
        tuple(params),
    ).fetchall()
    if not rows:
        return 0.0
    ok = 0
    total = 0
    for r in rows:
        sid = str(_row_val(r, 0, "student_id") or "").strip()
        if not sid:
            continue
        total += 1
        g_rows = cur.execute(
            "SELECT grade FROM grades WHERE student_id = ?",
            (sid,),
        ).fetchall()
        if not g_rows:
            continue
        vals = []
        for gr in g_rows:
            try:
                vals.append(float(_row_val(gr, 0, "grade") or 0))
            except (TypeError, ValueError):
                pass
        if vals and (sum(vals) / len(vals)) >= 50.0:
            ok += 1
    return (ok / total) * 100.0 if total else 0.0


def _faculty_qualifications(cur, department_id: int | None, semester: str) -> float:
    inp = _institutional_inputs(cur, semester, department_id)
    if inp.get("faculty_qualifications_percent") is not None:
        return float(inp["faculty_qualifications_percent"])
    dept_sql = ""
    params: list[Any] = []
    if department_id is not None:
        dept_sql = " WHERE department_id = ?"
        params.append(int(department_id))
    row = cur.execute(
        f"""
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN COALESCE(type,'') IN ('internal','external_phd','external_master') THEN 1 ELSE 0 END) AS qualified
        FROM instructors
        {dept_sql}
        """,
        tuple(params),
    ).fetchone()
    total = int(_row_val(row, 0) or 0)
    qualified = int(_row_val(row, 1) or 0)
    if total <= 0:
        return 0.0
    return min(100.0, (qualified / total) * 100.0)


def _student_faculty_ratio(cur, department_id: int | None) -> float | None:
    dept_sql_st = dept_sql_ins = ""
    params_st: list[Any] = []
    params_ins: list[Any] = []
    if department_id is not None:
        dept_sql_st = " AND department_id = ?"
        dept_sql_ins = " AND department_id = ?"
        params_st = [int(department_id)]
        params_ins = [int(department_id)]
    st_row = cur.execute(
        f"SELECT COUNT(*) FROM students WHERE COALESCE(enrollment_status,'active')='active' {dept_sql_st}",
        tuple(params_st),
    ).fetchone()
    ins_row = cur.execute(
        f"SELECT COUNT(*) FROM instructors WHERE COALESCE(is_active,1)=1 {dept_sql_ins}",
        tuple(params_ins),
    ).fetchone()
    students = int(_row_val(st_row, 0) or 0)
    faculty = int(_row_val(ins_row, 0) or 0)
    if faculty <= 0:
        return None
    return round(students / faculty, 2)


def _institutional_inputs(cur, semester: str, department_id: int | None) -> dict:
    row = cur.execute(
        """
        SELECT faculty_qualifications_percent, infrastructure_rating, notes
        FROM quality_institutional_inputs
        WHERE semester = ? AND (
            (? IS NULL AND department_id IS NULL) OR department_id = ?
        )
        LIMIT 1
        """,
        (semester, department_id, department_id),
    ).fetchone()
    if not row:
        return {}
    return {
        "faculty_qualifications_percent": _row_val(row, 0),
        "infrastructure_rating": _row_val(row, 1),
        "notes": _row_val(row, 2) or "",
    }


def _accreditation_status(score: float) -> str:
    if score >= 80:
        return "Excellent"
    if score >= 70:
        return "Good"
    return "Needs Improvement"


def _status_label_ar(code: str) -> str:
    return {
        "Excellent": "ممتاز",
        "Good": "جيد جداً",
        "Needs Improvement": "يحتاج تحسين",
    }.get(code, code)


def compute_quality_metrics(
    conn,
    *,
    semester: str | None = None,
    department_id: int | None = None,
) -> dict[str, Any]:
    cur = conn.cursor()
    sem = (semester or term_label_from_conn(conn)).strip()
    satisfaction = _avg_eval_score(conn, cur, sem, department_id)
    reports_pct = _reports_completion(conn, cur, sem, department_id)
    ilo_pct = _avg_ilo(conn, cur, sem, department_id)
    graduation = _graduation_proxy(cur, department_id)
    faculty_qual = _faculty_qualifications(cur, department_id, sem)
    ratio = _student_faculty_ratio(cur, department_id)
    inst = _institutional_inputs(cur, sem, department_id)
    infra = float(inst.get("infrastructure_rating") or 75.0)

    program_score = (
        satisfaction * 0.25
        + reports_pct * 0.25
        + ilo_pct * 0.25
        + graduation * 0.25
    )
    inst_score = faculty_qual * 0.4 + infra * 0.35 + reports_pct * 0.25
    overall = program_score * 0.6 + inst_score * 0.4
    status = _accreditation_status(overall)

    eval_count_row = cur.execute(
        "SELECT COUNT(*) FROM course_evaluations WHERE semester = ?",
        (sem,),
    ).fetchone()
    eval_count = int(_row_val(eval_count_row, 0) or 0)

    return {
        "semester": sem,
        "department_id": department_id,
        "program_student_satisfaction": round(satisfaction, 1),
        "program_course_reports_completion": round(reports_pct, 1),
        "program_ilo_achievement": round(ilo_pct, 1),
        "program_graduation_rate": round(graduation, 1),
        "institutional_faculty_qualifications": round(faculty_qual, 1),
        "institutional_student_to_faculty_ratio": ratio,
        "institutional_infrastructure_rating": round(infra, 1),
        "overall_accreditation_score": round(overall, 1),
        "accreditation_status": status,
        "accreditation_status_ar": _status_label_ar(status),
        "evaluation_count": eval_count,
        "institutional_inputs": inst,
    }


def list_critical_courses(conn, semester: str, department_id: int | None = None, min_failure: float = 25.0) -> list[dict]:
    cur = conn.cursor()
    pk = schedule_pk_column(conn)
    cols = {c.lower() for c in fetch_table_columns(conn, "course_closure_reports")}
    if "student_failure_rate" not in cols:
        return []
    dept_sql = ""
    params: list[Any] = [semester, min_failure]
    if department_id is not None:
        dept_sql = " AND sch.department_id = ?"
        params.append(int(department_id))
    rows = cur.execute(
        f"""
        SELECT sch.{pk} AS section_id,
               COALESCE(sch.course_name,'') AS course_name,
               COALESCE(i.name,'') AS instructor_name,
               c.student_failure_rate,
               COALESCE(c.action_plan,'') AS action_plan,
               COALESCE(c.status,'draft') AS status
        FROM course_closure_reports c
        JOIN schedule sch ON sch.{pk} = c.section_id
        LEFT JOIN instructors i ON i.id = c.instructor_id
        WHERE c.semester = ? AND COALESCE(c.student_failure_rate, 0) >= ? {dept_sql}
        ORDER BY c.student_failure_rate DESC
        LIMIT 50
        """,
        tuple(params),
    ).fetchall()
    out = []
    for r in rows:
        if hasattr(r, "keys"):
            out.append(dict(r))
        else:
            out.append(
                {
                    "section_id": r[0],
                    "course_name": r[1],
                    "instructor_name": r[2],
                    "student_failure_rate": r[3],
                    "action_plan": r[4],
                    "status": r[5],
                }
            )
    return out


def save_metrics_snapshot(conn, metrics: dict, actor: str = "") -> int | None:
    cur = conn.cursor()
    now = __import__("datetime").datetime.utcnow().isoformat()
    extra = {
        k: metrics.get(k)
        for k in ("evaluation_count", "accreditation_status_ar", "institutional_inputs")
    }
    cur.execute(
        """
        INSERT INTO quality_metrics_snapshots (
            semester, department_id,
            program_student_satisfaction, program_course_reports_completion,
            program_ilo_achievement, program_graduation_rate,
            institutional_faculty_qualifications, institutional_student_to_faculty_ratio,
            institutional_infrastructure_rating,
            overall_accreditation_score, accreditation_status,
            metrics_json, created_at, created_by
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            metrics.get("semester"),
            metrics.get("department_id"),
            metrics.get("program_student_satisfaction"),
            metrics.get("program_course_reports_completion"),
            metrics.get("program_ilo_achievement"),
            metrics.get("program_graduation_rate"),
            metrics.get("institutional_faculty_qualifications"),
            metrics.get("institutional_student_to_faculty_ratio"),
            metrics.get("institutional_infrastructure_rating"),
            metrics.get("overall_accreditation_score"),
            metrics.get("accreditation_status"),
            json.dumps(extra, ensure_ascii=False),
            now,
            actor,
        ),
    )
    try:
        return int(cur.lastrowid)
    except (TypeError, ValueError):
        row = cur.execute("SELECT last_insert_rowid()").fetchone()
        return int(_row_val(row, 0) or 0)
