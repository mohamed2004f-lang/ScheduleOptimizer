"""استعلامات طلاب الأستاذ حسب القسم (مع توسعة تكافؤ المقررات)."""
from __future__ import annotations

from backend.database.database import fetch_table_columns, is_postgresql, table_exists

from backend.repositories.course_equivalence_repo import expand_course_names_for_department


def instructor_linked_to_department(conn, instructor_id: int, department_id: int) -> bool:
    """هل يُعتبر الأستاذ مرتبطاً بهذا القسم (قسم رئيسي، إسناد، أو صف جدول)؟"""
    did = int(department_id)
    iid = int(instructor_id)
    cur = conn.cursor()
    ph = "%s" if is_postgresql() else "?"
    row = cur.execute(
        f"SELECT department_id FROM instructors WHERE id = {ph} LIMIT 1",
        (iid,),
    ).fetchone()
    if row and row[0] is not None:
        try:
            if int(row[0]) == did:
                return True
        except (TypeError, ValueError):
            pass
    if table_exists(conn, "instructor_department_assignments"):
        r2 = cur.execute(
            f"""
            SELECT 1 FROM instructor_department_assignments
            WHERE instructor_id = {ph} AND department_id = {ph} AND is_active = 1 LIMIT 1
            """,
            (iid, did),
        ).fetchone()
        if r2:
            return True
    scols = fetch_table_columns(conn, "schedule")
    if "instructor_id" in scols and "department_id" in scols:
        r3 = cur.execute(
            f"""
            SELECT 1 FROM schedule
            WHERE instructor_id = {ph} AND department_id = {ph} LIMIT 1
            """,
            (iid, did),
        ).fetchone()
        if r3:
            return True
    return False


def course_names_for_instructor_department(
    conn, instructor_id: int, department_id: int, semester: str | None
) -> list[str]:
    """أسماء المقررات من جدول schedule للأستاذ ضمن القسم (مع تصفية الفصل اختياري)."""
    scols = fetch_table_columns(conn, "schedule")
    if "instructor_id" not in scols or "department_id" not in scols or "course_name" not in scols:
        return []
    cur = conn.cursor()
    iid = int(instructor_id)
    did = int(department_id)
    ph = "%s" if is_postgresql() else "?"
    params: list = [iid, did]
    sem_sql = ""
    if semester and str(semester).strip():
        sem_sql = f" AND COALESCE(TRIM(semester), '') = {ph}"
        params.append(str(semester).strip())
    rows = cur.execute(
        f"""
        SELECT DISTINCT TRIM(course_name) FROM schedule
        WHERE instructor_id = {ph} AND department_id = {ph}
        {sem_sql}
        """,
        params,
    ).fetchall()
    out = []
    for r in rows:
        cn = (r[0] or "").strip()
        if cn:
            out.append(cn)
    return out


def students_registered_in_department_for_courses(
    conn, department_id: int, course_names: set[str]
) -> list[dict]:
    """الطلاب التابعون لقسم معيّن المسجّلون في أحد المقررات."""
    if not course_names:
        return []
    cur = conn.cursor()
    did = int(department_id)
    ph = "%s" if is_postgresql() else "?"
    placeholders = ",".join([ph] * len(course_names))
    names = list(course_names)
    params = [did, *names]
    rows = cur.execute(
        f"""
        SELECT DISTINCT s.student_id, COALESCE(s.student_name, '') AS student_name
        FROM registrations r
        INNER JOIN students s ON s.student_id = r.student_id
        WHERE s.department_id = {ph}
          AND r.course_name IN ({placeholders})
        ORDER BY s.student_id
        """,
        tuple(params),
    ).fetchall()
    return [{"student_id": r[0], "student_name": r[1] or ""} for r in rows]


def students_for_instructor_department(
    conn,
    instructor_id: int,
    department_id: int,
    semester: str | None = None,
) -> tuple[list[dict], list[str]]:
    """
    طلاب القسم المسجّلون في مقررات يدرّسها الأستاذ في ذلك القسم،
    مع توسيع أسماء المقررات عبر تكافؤ الأقسام.
    """
    raw_courses = course_names_for_instructor_department(conn, instructor_id, department_id, semester)
    base = set(raw_courses)
    expanded = expand_course_names_for_department(conn, department_id, base)
    students = students_registered_in_department_for_courses(conn, department_id, expanded)
    return students, sorted(expanded)
