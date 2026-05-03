"""
المرحلة 0 — تثبيت كتالوج الأقسام والبرامج الأساسي + ترحيل طلاب بلا تعيين.

السياسة للطلاب المحدَّثين تلقائياً:
- يُملأ department_id و current_program_id إلى قسم تشغيلي افتراضي (افتراضي: MECH + PROG_MAJOR).
- لا يُغيّر admission_program_id ولا specialized_at_term (البقاء NULL يعني منطقياً:
  لم يمرّ بتعريف «اتجاه عام» داخل هذا النموذج — مناسب للقدامى داخل التخصصات).

الجدول المرجعي هنا متزامن مع scripts/seed_departments_programs_demo.py (نفس أكواد الأقسام/البرامج).

ترحيل «نطاق التشغيل» للقدامى (مقررات courses، instructors، مستخدمي التدريس):
- يُنفَّذ عبر backfill_legacy_operational_data (أو سكربت phase0_apply --attach-operational).
- يقتصر على الصفوف ذات department_id / owning_department_id الفارغ حتى لا يُعاد كتابة تعيينات لاحقة.
"""

from __future__ import annotations

from typing import Any

from backend.database.database import fetch_table_columns, is_postgresql


def _scalar_int(row: Any) -> int:
    if row is None:
        return 0
    try:
        return int(row[0])
    except Exception:
        pass
    if isinstance(row, dict):
        v = row.get("count")
        if v is not None:
            return int(v)
    return int(list(row)[0])


# (code, name_ar, name_en)
PHASE0_DEPARTMENTS = [
    ("GENERAL", "القسم العام (كلية الهندسة)", "General Year"),
    ("MECH", "الهندسة الميكانيكية", "Mechanical Engineering"),
    ("CIVIL", "الهندسة المدنية", "Civil Engineering"),
    ("ELEC", "الهندسة الكهربائية", "Electrical Engineering"),
    ("RENEW", "هندسة الطاقات المتجددة", "Renewable Energy Engineering"),
]

# (dept_code, program_code, name_ar, phase, min_total_units, rules_json)
PHASE0_PROGRAMS = [
    (
        "GENERAL",
        "PROG_U1",
        "المرحلة التأسيسية / القسم العام",
        "general",
        0,
        '{"note_ar":"تهيئة مرحلة 0: قبل التنسيب من الاتجاه العام إلى الأقسام العلمية."}',
    ),
    ("MECH", "PROG_MAJOR", "بكالوريوس الهندسة الميكانيكية", "major", 160, ""),
    ("CIVIL", "PROG_MAJOR", "بكالوريوس الهندسة المدنية", "major", 160, ""),
    ("ELEC", "PROG_MAJOR", "بكالوريوس الهندسة الكهربائية", "major", 160, ""),
    ("RENEW", "PROG_MAJOR", "بكالوريوس هندسة الطاقات المتجددة", "major", 160, ""),
]


def _row_id(row: Any) -> int:
    if row is None:
        raise RuntimeError("row is None")
    if isinstance(row, (list, tuple)):
        return int(row[0])
    return int(row["id"])


def _ensure_department(cur, code: str, name_ar: str, name_en: str, pg: bool) -> int:
    if pg:
        cur.execute(
            """
            INSERT INTO departments (code, name_ar, name_en)
            VALUES (?, ?, ?)
            ON CONFLICT (code) DO UPDATE
            SET name_ar = EXCLUDED.name_ar, name_en = EXCLUDED.name_en
            RETURNING id
            """,
            (code, name_ar, name_en),
        )
        r = cur.fetchone()
        return _row_id(r)
    cur.execute(
        "INSERT OR IGNORE INTO departments (code, name_ar, name_en) VALUES (?, ?, ?)",
        (code, name_ar, name_en),
    )
    cur.execute("SELECT id FROM departments WHERE code = ?", (code,))
    return _row_id(cur.fetchone())


def _ensure_program(
    cur,
    department_id: int,
    code: str,
    name_ar: str,
    phase: str,
    min_total_units: int,
    rules_json: str,
    pg: bool,
) -> int:
    if pg:
        cur.execute(
            """
            INSERT INTO programs (department_id, code, name_ar, phase, min_total_units, rules_json)
            VALUES (?, ?, ?, ?, ?, NULLIF(?, ''))
            ON CONFLICT (department_id, code) DO UPDATE
            SET name_ar = EXCLUDED.name_ar,
                phase = EXCLUDED.phase,
                min_total_units = EXCLUDED.min_total_units,
                rules_json = EXCLUDED.rules_json
            RETURNING id
            """,
            (department_id, code, name_ar, phase, min_total_units, rules_json or ""),
        )
        return _row_id(cur.fetchone())
    cur.execute(
        """
        INSERT OR IGNORE INTO programs
        (department_id, code, name_ar, phase, min_total_units, rules_json)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (department_id, code, name_ar, phase, min_total_units, rules_json or None),
    )
    cur.execute(
        "SELECT id FROM programs WHERE department_id = ? AND code = ?",
        (department_id, code),
    )
    return _row_id(cur.fetchone())


def ensure_phase0_catalog(conn) -> dict[str, dict[str, Any]]:
    """
    ينشئ/يحدّث الأقسام والبرامج المرجعية للمرحلة 0 بدون مقررات تجريبية.
    يعيد dept_ids keyed by code و program_ids keyed by \"dept_code/program_code\".
    """
    pg = is_postgresql()
    cur = conn.cursor()
    dept_ids: dict[str, int] = {}
    for code, name_ar, name_en in PHASE0_DEPARTMENTS:
        dept_ids[code] = _ensure_department(cur, code, name_ar, name_en, pg)

    program_ids: dict[str, int] = {}
    for dept_code, pcode, name_ar, phase, min_u, rules in PHASE0_PROGRAMS:
        d_id = dept_ids[dept_code]
        pid = _ensure_program(cur, d_id, pcode, name_ar, phase, min_u, rules, pg)
        program_ids[f"{dept_code}/{pcode}"] = pid

    return {"department_ids_by_code": dept_ids, "program_ids": program_ids}


def count_legacy_students(conn) -> int:
    """عدد الطلاب الذين لم يُعيَّنوا بعد ضمن قسم أو برنامج حالي."""
    cur = conn.cursor()
    row = cur.execute(
        """
        SELECT COUNT(*) FROM students
        WHERE department_id IS NULL OR current_program_id IS NULL
        """
    ).fetchone()
    return _scalar_int(row)


def backfill_legacy_students(
    conn,
    *,
    legacy_dept_code: str = "MECH",
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    يعبّئ department_id و current_program_id للطلاب بلا تعيين.
    لا يغيّر admission_program_id (تبقى NULL للقدامى).
    """
    cur = conn.cursor()
    cur.execute(
        """
        SELECT COUNT(*) FROM students
        WHERE department_id IS NULL OR current_program_id IS NULL
        """
    )
    pending_row = cur.fetchone()
    pending = _scalar_int(pending_row)

    if dry_run:
        return {
            "dry_run": True,
            "legacy_dept_code": legacy_dept_code,
            "pending_student_rows": pending,
            "updated_rows": 0,
        }

    cur.execute(
        """
        UPDATE students SET
          department_id = COALESCE(
            department_id,
            (SELECT id FROM departments WHERE code = ? LIMIT 1)
          ),
          current_program_id = COALESCE(
            current_program_id,
            (
              SELECT p.id FROM programs p
              INNER JOIN departments d ON d.id = p.department_id
              WHERE d.code = ? AND p.code = 'PROG_MAJOR'
              LIMIT 1
            )
          ),
          updated_at = CURRENT_TIMESTAMP
        WHERE department_id IS NULL OR current_program_id IS NULL
        """,
        (legacy_dept_code, legacy_dept_code),
    )
    updated = getattr(cur, "rowcount", -1)

    remaining_row = cur.execute(
        """
        SELECT COUNT(*) FROM students
        WHERE department_id IS NULL OR current_program_id IS NULL
        """
    ).fetchone()
    remaining = _scalar_int(remaining_row)

    return {
        "dry_run": False,
        "legacy_dept_code": legacy_dept_code,
        "pending_student_rows_before": pending,
        "updated_rows": int(updated),
        "remaining_unassigned": remaining,
    }


_STAFF_ROLES_FOR_DEPT = frozenset(
    {
        "admin",
        "admin_main",
        "instructor",
        "head_of_department",
        "supervisor",
    }
)


def _resolve_major_program_id(cur, legacy_dept_code: str) -> int:
    cur.execute(
        """
        SELECT p.id FROM programs p
        INNER JOIN departments d ON d.id = p.department_id
        WHERE UPPER(TRIM(d.code)) = UPPER(TRIM(?)) AND TRIM(p.code) = 'PROG_MAJOR'
        LIMIT 1
        """,
        (legacy_dept_code,),
    )
    row = cur.fetchone()
    if not row:
        raise ValueError(
            f"برنامج PROG_MAJOR غير موجود للقسم {legacy_dept_code!r} — شغّل ensure_phase0_catalog أولاً"
        )
    return _row_id(row)


def _monolith_bind_all(
    cur,
    conn,
    *,
    dept_id: int,
    legacy_dept_code: str,
    dry_run: bool,
    include_students: bool,
    include_courses: bool,
    include_instructors: bool,
    include_staff_users: bool,
    out: dict[str, Any],
) -> dict[str, Any]:
    """يربط كل الصفوف التشغيلية الحالية بقسم واحد (سياسة كتلة واحدة قبل تعدد الأقسام)."""

    def _count(sql: str, params: tuple = ()) -> int:
        cur.execute(sql, params)
        return _scalar_int(cur.fetchone())

    major_pid = _resolve_major_program_id(cur, legacy_dept_code)
    out["monolith_exclusive"] = True
    out["major_program_id"] = major_pid

    if dry_run:
        out["dry_run"] = True
        if include_students:
            out["would_update_students"] = _count(
                "SELECT COUNT(*) FROM students WHERE COALESCE(TRIM(student_id), '') <> ''"
            )
        cols_c = fetch_table_columns(conn, "courses")
        if include_courses and "owning_department_id" in cols_c:
            out["would_update_courses"] = _count(
                "SELECT COUNT(*) FROM courses WHERE COALESCE(TRIM(course_name), '') <> ''"
            )
        cols_i = fetch_table_columns(conn, "instructors")
        if include_instructors and "department_id" in cols_i:
            out["would_update_instructors"] = _count(
                "SELECT COUNT(*) FROM instructors WHERE COALESCE(TRIM(name), '') <> ''"
            )
        cols_u = fetch_table_columns(conn, "users")
        if include_staff_users and "department_id" in cols_u and "role" in cols_u:
            placeholders = ",".join("?" * len(_STAFF_ROLES_FOR_DEPT))
            roles = tuple(sorted(_STAFF_ROLES_FOR_DEPT))
            out["would_update_staff_users"] = _count(
                f"""
                SELECT COUNT(*) FROM users
                WHERE LOWER(TRIM(COALESCE(role, ''))) IN ({placeholders})
                """,
                roles,
            )
        cols_s = fetch_table_columns(conn, "schedule")
        if "department_id" in cols_s:
            out["would_update_schedule_rows"] = _count(
                "SELECT COUNT(*) FROM schedule WHERE COALESCE(TRIM(course_name), '') <> ''"
            )
        out["remaining_unassigned"] = _count(
            """
            SELECT COUNT(*) FROM students
            WHERE department_id IS NULL OR current_program_id IS NULL
            """
        )
        return out

    if include_students:
        cur.execute(
            """
            UPDATE students SET
                department_id = ?,
                current_program_id = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE COALESCE(TRIM(student_id), '') <> ''
            """,
            (dept_id, major_pid),
        )
        out["students_all_rows_updated"] = int(getattr(cur, "rowcount", 0) or 0)

    cols_c = fetch_table_columns(conn, "courses")
    if include_courses and "owning_department_id" in cols_c:
        cur.execute(
            """
            UPDATE courses SET owning_department_id = ?
            WHERE COALESCE(TRIM(course_name), '') <> ''
            """,
            (dept_id,),
        )
        out["courses_all_rows_updated"] = int(getattr(cur, "rowcount", 0) or 0)

    cols_i = fetch_table_columns(conn, "instructors")
    if include_instructors and "department_id" in cols_i:
        cur.execute(
            """
            UPDATE instructors SET department_id = ?
            WHERE COALESCE(TRIM(name), '') <> ''
            """,
            (dept_id,),
        )
        out["instructors_all_rows_updated"] = int(getattr(cur, "rowcount", 0) or 0)

    cols_u = fetch_table_columns(conn, "users")
    if include_staff_users and "department_id" in cols_u and "role" in cols_u:
        placeholders = ",".join("?" * len(_STAFF_ROLES_FOR_DEPT))
        roles = tuple(sorted(_STAFF_ROLES_FOR_DEPT))
        cur.execute(
            f"""
            UPDATE users SET department_id = ?
            WHERE LOWER(TRIM(COALESCE(role, ''))) IN ({placeholders})
            """,
            (dept_id,) + roles,
        )
        out["staff_users_all_rows_updated"] = int(getattr(cur, "rowcount", 0) or 0)

    cols_s = fetch_table_columns(conn, "schedule")
    if "department_id" in cols_s:
        cur.execute(
            """
            UPDATE schedule SET department_id = ?
            WHERE COALESCE(TRIM(course_name), '') <> ''
            """,
            (dept_id,),
        )
        out["schedule_all_rows_updated"] = int(getattr(cur, "rowcount", 0) or 0)

    rem = _count(
        """
        SELECT COUNT(*) FROM students
        WHERE department_id IS NULL OR current_program_id IS NULL
        """
    )
    out["remaining_unassigned"] = rem
    return out


def backfill_legacy_operational_data(
    conn,
    *,
    legacy_dept_code: str = "MECH",
    dry_run: bool = False,
    include_students: bool = True,
    include_courses: bool = True,
    include_instructors: bool = True,
    include_staff_users: bool = True,
    monolith_exclusive: bool = False,
) -> dict[str, Any]:
    """
    يربط البيانات التشغيلية المخزّنة سابقاً بقسم مرجعي — افتراضياً الميكانيك.

    **الوضع الافتراضي (monolith_exclusive=False):**
    - الطلاب: backfill_legacy_students (صفوف بلا قسم أو بلا برنامج حالي فقط).
    - المقررات / الهيئة / المستخدمون: تعبئة department_id / owning_department_id عند NULL فقط.

    **monolith_exclusive=True (كتلة تشغيل واحدة):**
    - يفرض ربط **كل** الطلاب والمقررات وهيئة التدريس وجدول schedule (عند وجود العمود) بذلك القسم.
    - يُستخدم عندما كانت كل البيانات الحالية لميكانيكياً فقط وتريد بقاء أقسام أخرى فارغة في واجهة النطاق.
    """
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id FROM departments
        WHERE UPPER(TRIM(code)) = UPPER(TRIM(?))
        LIMIT 1
        """,
        (legacy_dept_code,),
    )
    row = cur.fetchone()
    if not row:
        raise ValueError(f"قسم غير موجود في departments: {legacy_dept_code!r}")
    dept_id = _row_id(row)

    out: dict[str, Any] = {
        "legacy_dept_code": str(legacy_dept_code).strip().upper(),
        "department_id": dept_id,
        "dry_run": dry_run,
    }

    if monolith_exclusive:
        return _monolith_bind_all(
            cur,
            conn,
            dept_id=dept_id,
            legacy_dept_code=legacy_dept_code,
            dry_run=dry_run,
            include_students=include_students,
            include_courses=include_courses,
            include_instructors=include_instructors,
            include_staff_users=include_staff_users,
            out=out,
        )

    if include_students:
        st = backfill_legacy_students(
            conn, legacy_dept_code=legacy_dept_code, dry_run=dry_run
        )
        out["students"] = st

    def _count(sql: str, params: tuple = ()) -> int:
        cur.execute(sql, params)
        return _scalar_int(cur.fetchone())

    if include_courses:
        cols = fetch_table_columns(conn, "courses")
        if "owning_department_id" in cols:
            pending = _count(
                """
                SELECT COUNT(*) FROM courses
                WHERE COALESCE(TRIM(course_name), '') <> ''
                  AND owning_department_id IS NULL
                """
            )
            out["courses_pending_null_owner"] = pending
            if not dry_run and pending:
                cur.execute(
                    """
                    UPDATE courses SET owning_department_id = ?
                    WHERE COALESCE(TRIM(course_name), '') <> ''
                      AND owning_department_id IS NULL
                    """,
                    (dept_id,),
                )
                out["courses_updated"] = int(getattr(cur, "rowcount", 0) or 0)
            else:
                out["courses_updated"] = 0

    if include_instructors:
        cols_i = fetch_table_columns(conn, "instructors")
        if "department_id" in cols_i:
            pending = _count(
                "SELECT COUNT(*) FROM instructors WHERE department_id IS NULL"
            )
            out["instructors_pending_null_dept"] = pending
            if not dry_run and pending:
                cur.execute(
                    """
                    UPDATE instructors SET department_id = ?
                    WHERE department_id IS NULL
                    """,
                    (dept_id,),
                )
                out["instructors_updated"] = int(getattr(cur, "rowcount", 0) or 0)
            else:
                out["instructors_updated"] = 0

    if include_staff_users:
        cols_u = fetch_table_columns(conn, "users")
        if "department_id" in cols_u and "role" in cols_u:
            placeholders = ",".join("?" * len(_STAFF_ROLES_FOR_DEPT))
            roles = tuple(sorted(_STAFF_ROLES_FOR_DEPT))
            pending = _count(
                f"""
                SELECT COUNT(*) FROM users
                WHERE department_id IS NULL
                  AND LOWER(TRIM(COALESCE(role, ''))) IN ({placeholders})
                """,
                roles,
            )
            out["staff_users_pending_null_dept"] = pending
            if not dry_run and pending:
                cur.execute(
                    f"""
                    UPDATE users SET department_id = ?
                    WHERE department_id IS NULL
                      AND LOWER(TRIM(COALESCE(role, ''))) IN ({placeholders})
                    """,
                    (dept_id,) + roles,
                )
                out["staff_users_updated"] = int(getattr(cur, "rowcount", 0) or 0)
            else:
                out["staff_users_updated"] = 0

    return out
