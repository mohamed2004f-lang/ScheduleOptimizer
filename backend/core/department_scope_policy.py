"""سياسة موحّدة لنطاق القسم في القوائم والعمليات الحساسة."""

from __future__ import annotations

from typing import Literal

from backend.core.auth import _normalize_role, get_admin_department_scope_id

UsersListScopeMode = Literal["none", "department", "empty"]


def resolve_users_list_scope(conn, actor_username: str | None) -> tuple[UsersListScopeMode, int | None]:
    try:
        from flask import has_request_context, session
    except Exception:
        return ("none", None)

    if not has_request_context():
        return ("none", None)

    role = _normalize_role((session.get("user_role") or "").strip())
    if role in ("admin_main", "admin", "system_admin", "college_dean", "academic_vice_dean"):
        sid = get_admin_department_scope_id()
        if sid is None:
            return ("none", None)
        return ("department", int(sid))

    if role == "head_of_department":
        hid = head_home_department_id(conn, actor_username)
        if hid is None:
            return ("empty", None)
        return ("department", int(hid))

    return ("none", None)


def head_home_department_id(conn, username: str | None) -> int | None:
    un = (username or "").strip()
    if not un:
        return None
    cur = conn.cursor()
    row = cur.execute(
        """
        SELECT COALESCE(u.department_id, ins.department_id) AS home_dept
        FROM users u
        LEFT JOIN instructors ins ON ins.id = u.instructor_id
        WHERE lower(u.username) = lower(?)
        LIMIT 1
        """,
        (un,),
    ).fetchone()
    if not row:
        return None
    try:
        raw = row["home_dept"] if hasattr(row, "keys") else row[0]
    except (KeyError, IndexError, TypeError):
        raw = row[0]
    if raw in (None, ""):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def student_matches_department(conn, student_id: str | None, dept_id: int) -> bool:
    sid = (student_id or "").strip()
    if not sid:
        return False
    cur = conn.cursor()
    row = cur.execute(
        """
        SELECT department_id, current_program_id, admission_program_id
        FROM students
        WHERE student_id = ?
        LIMIT 1
        """,
        (sid,),
    ).fetchone()
    if not row:
        return False

    def _col(name: str, idx: int):
        try:
            if hasattr(row, "keys") and name in row.keys():
                return row[name]
        except Exception:
            pass
        return row[idx]

    d_raw = _col("department_id", 0)
    if d_raw not in (None, ""):
        try:
            if int(d_raw) == int(dept_id):
                return True
        except (TypeError, ValueError):
            pass

    for key, idx in (("current_program_id", 1), ("admission_program_id", 2)):
        p_raw = _col(key, idx)
        if p_raw in (None, ""):
            continue
        try:
            pid = int(p_raw)
        except (TypeError, ValueError):
            continue
        pr = cur.execute(
            "SELECT department_id FROM programs WHERE id = ? LIMIT 1",
            (pid,),
        ).fetchone()
        if not pr:
            continue
        pd = pr["department_id"] if hasattr(pr, "keys") else pr[0]
        if pd not in (None, ""):
            try:
                if int(pd) == int(dept_id):
                    return True
            except (TypeError, ValueError):
                pass
    return False


def resolve_student_department_id(conn, student_id: str | None) -> int | None:
    """قسم الطالب: من students.department_id أو من برنامجه الحالي/الالتحاق."""
    sid = (student_id or "").strip()
    if not sid:
        return None
    cur = conn.cursor()
    row = cur.execute(
        """
        SELECT department_id, current_program_id, admission_program_id
        FROM students
        WHERE student_id = ?
        LIMIT 1
        """,
        (sid,),
    ).fetchone()
    if not row:
        return None

    def _col(name: str, idx: int):
        try:
            if hasattr(row, "keys") and name in row.keys():
                return row[name]
        except Exception:
            pass
        return row[idx]

    d_raw = _col("department_id", 0)
    if d_raw not in (None, ""):
        try:
            return int(d_raw)
        except (TypeError, ValueError):
            pass

    for key, idx in (("current_program_id", 1), ("admission_program_id", 2)):
        p_raw = _col(key, idx)
        if p_raw in (None, ""):
            continue
        try:
            pid = int(p_raw)
        except (TypeError, ValueError):
            continue
        pr = cur.execute(
            "SELECT department_id FROM programs WHERE id = ? LIMIT 1",
            (pid,),
        ).fetchone()
        if not pr:
            continue
        pd = pr["department_id"] if hasattr(pr, "keys") else pr[0]
        if pd not in (None, ""):
            try:
                return int(pd)
            except (TypeError, ValueError):
                pass
    return None


def sql_student_row_belongs_to_department(dept_id: int) -> tuple[str, tuple[int, int, int]]:
    """
    Predicate matching student_matches_department for one row of students (no table alias).
    """
    frag = (
        "(department_id = ? OR current_program_id IN (SELECT id FROM programs WHERE department_id = ?) "
        "OR admission_program_id IN (SELECT id FROM programs WHERE department_id = ?))"
    )
    return frag, (int(dept_id), int(dept_id), int(dept_id))


def sql_aliased_student_belongs_to_department(alias: str, dept_id: int) -> tuple[str, tuple[int, int, int]]:
    frag = (
        f"({alias}.department_id = ? OR {alias}.current_program_id IN (SELECT id FROM programs WHERE department_id = ?) "
        f"OR {alias}.admission_program_id IN (SELECT id FROM programs WHERE department_id = ?))"
    )
    return frag, (int(dept_id), int(dept_id), int(dept_id))


def resolve_scope_sql_for_students_table(conn, actor_username: str | None) -> tuple[str, tuple]:
    """WHERE fragment for bare students table rows; '' if unscoped."""
    mode, dept_id = resolve_users_list_scope(conn, actor_username)
    if mode == "none":
        return "", ()
    if mode == "empty" or dept_id is None:
        return "1=0", ()
    return sql_student_row_belongs_to_department(int(dept_id))


def resolve_scope_sql_for_aliased_student(conn, actor_username: str | None, alias: str) -> tuple[str, tuple]:
    """WHERE fragment referencing students joined as alias (e.g. registrations JOIN students st)."""
    mode, dept_id = resolve_users_list_scope(conn, actor_username)
    if mode == "none":
        return "", ()
    if mode == "empty" or dept_id is None:
        return "1=0", ()
    return sql_aliased_student_belongs_to_department(alias, int(dept_id))


def instructor_matches_department(conn, instructor_id: int | None, dept_id: int) -> bool:
    if instructor_id is None:
        return False
    cur = conn.cursor()
    row = cur.execute(
        "SELECT department_id FROM instructors WHERE id = ? LIMIT 1",
        (int(instructor_id),),
    ).fetchone()
    if not row:
        return False
    d_raw = row["department_id"] if hasattr(row, "keys") else row[0]
    if d_raw in (None, ""):
        return False
    try:
        return int(d_raw) == int(dept_id)
    except (TypeError, ValueError):
        return False


def user_row_matches_department(
    conn,
    dept_id: int,
    *,
    role: str,
    student_id: str | None,
    instructor_id: int | None,
    users_department_id: int | None = None,
) -> bool:
    role_n = _normalize_role((role or "").strip())
    if users_department_id not in (None, ""):
        try:
            if int(users_department_id) == int(dept_id):
                return True
        except (TypeError, ValueError):
            pass

    if role_n == "student":
        return student_matches_department(conn, student_id, dept_id)

    if role_n in ("instructor", "head_of_department"):
        return instructor_matches_department(conn, instructor_id, dept_id)

    if role_n == "admin_main":
        return False

    return False


def assert_actor_may_manage_user_links(
    conn,
    *,
    actor_username: str | None,
    target_role: str,
    student_id: str | None,
    instructor_id: int | None,
    users_department_id: int | None = None,
) -> tuple[bool, str | None]:
    mode, dept_id = resolve_users_list_scope(conn, actor_username)
    if mode != "department" or dept_id is None:
        return (True, None)

    tr = _normalize_role((target_role or "").strip())
    if tr == "admin_main":
        return (False, "غير مسموح بإدارة حساب مسؤول رئيسي أثناء تفعيل نطاق قسم.")

    if user_row_matches_department(
        conn,
        int(dept_id),
        role=target_role,
        student_id=student_id,
        instructor_id=instructor_id,
        users_department_id=users_department_id,
    ):
        return (True, None)

    return (False, "المستخدم أو الربط المطلوب خارج نطاق القسم الحالي.")


def derive_users_department_id_for_storage(
    conn,
    *,
    role: str,
    student_id: str | None,
    instructor_id: int | None,
) -> int | None:
    role_n = _normalize_role((role or "").strip())
    cur = conn.cursor()
    if role_n == "student" and (student_id or "").strip():
        row = cur.execute(
            "SELECT department_id FROM students WHERE student_id = ? LIMIT 1",
            ((student_id or "").strip(),),
        ).fetchone()
        if row:
            raw = row["department_id"] if hasattr(row, "keys") else row[0]
            if raw not in (None, ""):
                try:
                    return int(raw)
                except (TypeError, ValueError):
                    pass
        return None

    if role_n in ("instructor", "head_of_department") and instructor_id is not None:
        row = cur.execute(
            "SELECT department_id FROM instructors WHERE id = ? LIMIT 1",
            (int(instructor_id),),
        ).fetchone()
        if row:
            raw = row["department_id"] if hasattr(row, "keys") else row[0]
            if raw not in (None, ""):
                try:
                    return int(raw)
                except (TypeError, ValueError):
                    pass
        return None

    return None


def target_username_allowed_for_actor(conn, actor_username: str | None, target_username: str) -> bool:
    mode, dept_id = resolve_users_list_scope(conn, actor_username)
    if mode == "empty":
        return False
    if mode != "department" or dept_id is None:
        return True
    cur = conn.cursor()
    row = cur.execute(
        """
        SELECT role, student_id, instructor_id, department_id
        FROM users
        WHERE lower(username) = lower(?)
        LIMIT 1
        """,
        ((target_username or "").strip(),),
    ).fetchone()
    if not row:
        return False
    r = row["role"] if hasattr(row, "keys") else row[0]
    sid = row["student_id"] if hasattr(row, "keys") else row[1]
    iid = row["instructor_id"] if hasattr(row, "keys") else row[2]
    ud = row["department_id"] if hasattr(row, "keys") else row[3]
    try:
        iid_i = int(iid) if iid not in (None, "") else None
    except (TypeError, ValueError):
        iid_i = None
    try:
        ud_i = int(ud) if ud not in (None, "") else None
    except (TypeError, ValueError):
        ud_i = None

    return user_row_matches_department(
        conn,
        int(dept_id),
        role=str(r or ""),
        student_id=sid,
        instructor_id=iid_i,
        users_department_id=ud_i,
    )

def actor_can_manage_existing_instructor(conn, actor_username: str | None, instructor_id: int) -> bool:
    """هل يجوز تعديل/حذف سجل محاضر موجود ضمن نطاق المنفّذ؟"""
    mode, dept_id = resolve_users_list_scope(conn, actor_username)
    if mode == "empty":
        return False
    if mode != "department" or dept_id is None:
        return True
    return instructor_matches_department(conn, instructor_id, int(dept_id))


def finalize_instructor_department_id_for_write(
    conn,
    *,
    actor_username: str | None,
    body_department_id: object | None,
) -> tuple[int | None, tuple[bool, str | None]]:
    """
    يحدد department_id النهائي لسجل محاضر عند الحفظ.

    يُرجع (المعرّف أو None، (مسموح، رسالة خطأ)).
    """
    try:
        from flask import session

        role = _normalize_role((session.get("user_role") or "").strip())
    except Exception:
        role = ""

    mode, scope_dep = resolve_users_list_scope(conn, actor_username)

    if role == "head_of_department":
        hid = head_home_department_id(conn, actor_username)
        if hid is None:
            return None, (False, "لا يوجد قسم مرتبط بحساب رئيس القسم.")
        return int(hid), (True, None)

    if role in ("admin_main", "admin", "system_admin", "college_dean", "academic_vice_dean"):
        if mode == "department" and scope_dep is not None:
            return int(scope_dep), (True, None)
        raw = body_department_id
        if raw in (None, ""):
            return None, (True, None)
        try:
            return int(raw), (True, None)
        except (TypeError, ValueError):
            return None, (False, "department_id غير صالح.")

    if mode == "department" and scope_dep is not None:
        try:
            return int(scope_dep), (True, None)
        except (TypeError, ValueError):
            pass

    raw = body_department_id
    if raw in (None, ""):
        return None, (True, None)
    try:
        return int(raw), (True, None)
    except (TypeError, ValueError):
        return None, (False, "department_id غير صالح.")


def count_students_for_department(conn, dept_id: int) -> int:
    """عدد الطلاب المطابقين لسياسة نطاق القسم (قسم مباشر أو عبر البرنامج)."""
    frag, params = sql_student_row_belongs_to_department(int(dept_id))
    cur = conn.cursor()
    row = cur.execute(f"SELECT COUNT(*) FROM students WHERE {frag}", params).fetchone()
    if not row:
        return 0
    try:
        return int(row[0] if not hasattr(row, "keys") else row["COUNT(*)"])
    except (TypeError, ValueError, KeyError):
        return int(row[0])


def count_courses_for_department(conn, dept_id: int) -> int:
    """عدد المقررات المرتبطة بالقسم (owning_department_id)."""
    try:
        from backend.services.utilities import fetch_table_columns

        cols = fetch_table_columns(conn, "courses")
    except Exception:
        cols = []
    if "owning_department_id" not in cols:
        return 0
    cur = conn.cursor()
    row = cur.execute(
        "SELECT COUNT(*) FROM courses WHERE owning_department_id = ?",
        (int(dept_id),),
    ).fetchone()
    if not row:
        return 0
    try:
        return int(row[0] if not hasattr(row, "keys") else row["COUNT(*)"])
    except (TypeError, ValueError, KeyError):
        return int(row[0])


def department_scope_data_summary(conn, dept_id: int) -> dict:
    """ملخص سريع لمحتوى نطاق قسم (لتنبيه الواجهة عند الفراغ)."""
    sc = count_students_for_department(conn, int(dept_id))
    cc = count_courses_for_department(conn, int(dept_id))
    return {
        "department_id": int(dept_id),
        "student_count": sc,
        "course_count": cc,
        "is_empty": sc == 0 and cc == 0,
    }


def proposed_department_allowed_for_scope(
    conn,
    actor_username: str | None,
    proposed_department_id: int | None,
) -> tuple[bool, str | None]:
    """تحقق من أن القسم المقترح يطابق نطاق الجلسة عند التقييد."""
    mode, dep_id = resolve_users_list_scope(conn, actor_username)
    if mode == "empty":
        return False, "لا يوجد نطاق قسم صالح للمنفّذ."
    if mode != "department" or dep_id is None:
        return True, None
    if proposed_department_id is None:
        return False, "يجب تحديد القسم ضمن نطاق عملك."
    try:
        if int(proposed_department_id) != int(dep_id):
            return False, "القسم خارج نطاق الصلاحية الحالية."
    except (TypeError, ValueError):
        return False, "معرّف القسم غير صالح."
    return True, None

