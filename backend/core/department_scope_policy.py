"""سياسة موحّدة لنطاق القسم في القوائم والعمليات الحساسة."""

from __future__ import annotations

from typing import Literal

from backend.core.auth import _normalize_role, get_admin_department_scope_id

UsersListScopeMode = Literal["none", "department", "empty"]

_SCOPE_SESSION_ROLES = frozenset(
    {
        "admin",
        "admin_main",
        "system_admin",
        "college_dean",
        "academic_vice_dean",
        "staff",
    }
)


def session_role_profile_scope_mode() -> str:
    """نطاق ملف الدور في الجلسة: college | department | none."""
    try:
        from flask import session
    except Exception:
        return "none"
    code = (session.get("role_profile_code") or "").strip()
    if code:
        try:
            from backend.core.permissions import get_profile_by_code

            prof = get_profile_by_code(code)
            return str((prof or {}).get("scope_mode") or "none").strip().lower()
        except Exception:
            return "none"
    rp_id = session.get("role_profile_id")
    if rp_id not in (None, ""):
        try:
            from backend.database.database import get_connection
            from backend.core.permissions import get_profile_by_id

            with get_connection() as conn:
                prof = get_profile_by_id(conn, int(rp_id))
            if prof:
                return str(prof.get("scope_mode") or "none").strip().lower()
        except Exception:
            pass
    return "none"


def resolve_users_list_scope(conn, actor_username: str | None) -> tuple[UsersListScopeMode, int | None]:
    try:
        from flask import has_request_context, session
    except Exception:
        has_request_context = lambda: False  # type: ignore[assignment,misc]
        session = None  # type: ignore[assignment]

    if not has_request_context():
        un = (actor_username or "").strip()
        if un:
            cur = conn.cursor()
            row = cur.execute(
                "SELECT role FROM users WHERE lower(username) = lower(?) LIMIT 1",
                (un,),
            ).fetchone()
            role = ""
            if row:
                raw_role = row["role"] if hasattr(row, "keys") else row[0]
                role = _normalize_role(str(raw_role or "").strip())
            if role == "head_of_department":
                hid = head_home_department_id(conn, un)
                if hid is None:
                    return ("empty", None)
                return ("department", int(hid))
        return ("none", None)

    role = _normalize_role((session.get("user_role") or "").strip())
    # جلسة بلا دور مع اسم مستخدم صريح: الرجوع لجدول users (اختبارات/سكربتات)
    if not role:
        un = (actor_username or "").strip()
        if un:
            cur = conn.cursor()
            row = cur.execute(
                "SELECT role FROM users WHERE lower(username) = lower(?) LIMIT 1",
                (un,),
            ).fetchone()
            if row:
                raw_role = row["role"] if hasattr(row, "keys") else row[0]
                role = _normalize_role(str(raw_role or "").strip())
    if role in _SCOPE_SESSION_ROLES:
        if role == "staff" and session_role_profile_scope_mode() == "department":
            hid = head_home_department_id(conn, actor_username)
            if hid is None:
                return ("empty", None)
            return ("department", int(hid))
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


def resolve_effective_department_scope_id(
    conn,
    actor_username: str | None = None,
) -> int | None:
    """معرّف القسم الفعّال للفلترة والربط عند الاستيراد."""
    mode, dept_id = resolve_users_list_scope(conn, actor_username)
    if mode == "department" and dept_id is not None:
        return int(dept_id)
    return None


def student_ids_for_department(conn, dept_id: int) -> set[str]:
    """أرقام الطلاب المطابقين لسياسة نطاق القسم."""
    cur = conn.cursor()
    p_rows = cur.execute(
        "SELECT id FROM programs WHERE department_id = ?",
        (int(dept_id),),
    ).fetchall()
    program_ids: set[int] = set()
    for pr in p_rows or []:
        try:
            v = pr[0] if not hasattr(pr, "keys") else pr["id"]
            if v not in (None, ""):
                program_ids.add(int(v))
        except (TypeError, ValueError, KeyError, IndexError):
            continue
    if program_ids:
        ph = ",".join("?" for _ in program_ids)
        rows = cur.execute(
            f"""
            SELECT student_id
            FROM students
            WHERE department_id = ?
               OR current_program_id IN ({ph})
               OR admission_program_id IN ({ph})
            """,
            (int(dept_id), *tuple(program_ids), *tuple(program_ids)),
        ).fetchall()
    else:
        rows = cur.execute(
            "SELECT student_id FROM students WHERE department_id = ?",
            (int(dept_id),),
        ).fetchall()
    out: set[str] = set()
    for r in rows or []:
        if not r:
            continue
        sid = r[0] if not hasattr(r, "keys") else r["student_id"]
        if sid:
            out.add(str(sid).strip())
    return out


def major_program_id_for_department(conn, dept_id: int) -> int | None:
    """برنامج PROG_MAJOR لقسم محدد."""
    cur = conn.cursor()
    row = cur.execute(
        """
        SELECT p.id FROM programs p
        WHERE p.department_id = ? AND UPPER(TRIM(COALESCE(p.code, ''))) = 'PROG_MAJOR'
        LIMIT 1
        """,
        (int(dept_id),),
    ).fetchone()
    if not row:
        return None
    try:
        raw = row["id"] if hasattr(row, "keys") else row[0]
        if raw in (None, ""):
            return None
        return int(raw)
    except (TypeError, ValueError, KeyError, IndexError):
        return None


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


def department_exists(conn, department_id: int) -> bool:
    cur = conn.cursor()
    row = cur.execute(
        "SELECT id FROM departments WHERE id = ? LIMIT 1",
        (int(department_id),),
    ).fetchone()
    return bool(row)


def resolve_hod_managed_department_id(
    conn,
    *,
    role: str,
    instructor_id: int | None,
    explicit_department_id: int | None,
    actor_username: str | None,
    actor_is_privileged: bool,
) -> tuple[int | None, str | None]:
    """قسم الحوكمة لدور رئيس القسم (users.department_id) منفصل عن قسم الأستاذ الوظيفي.

    - المسؤولون/العمادة: يمكنهم اختيار أي قسم (مثل GENERAL لاتجاه عام).
    - رئيس قسم: يقتصر على قسمه فقط.
    - إن لم يُمرَّر قسم صراحة: يُشتق من قسم الأستاذ (توافق خلفي).
    """
    role_n = _normalize_role((role or "").strip())
    if role_n != "head_of_department":
        return (
            derive_users_department_id_for_storage(
                conn, role=role, student_id=None, instructor_id=instructor_id
            ),
            None,
        )

    explicit: int | None = None
    if explicit_department_id not in (None, ""):
        try:
            explicit = int(explicit_department_id)
        except (TypeError, ValueError):
            return (None, "department_id غير صالح")
        if not department_exists(conn, explicit):
            return (None, f"القسم غير موجود: {explicit}")

    actor_home = head_home_department_id(conn, actor_username)

    if not actor_is_privileged:
        # رئيس قسم يعدّل ضمن نطاقه فقط
        forced = actor_home
        if forced is None:
            forced = derive_users_department_id_for_storage(
                conn, role=role_n, student_id=None, instructor_id=instructor_id
            )
        if explicit is not None and forced is not None and int(explicit) != int(forced):
            return (None, "لا يمكن لرئيس القسم تعيين رئاسة قسم خارج نطاقه.")
        return (forced if forced is not None else explicit, None)

    if explicit is not None:
        return (explicit, None)

    # توافق خلفي: بدون اختيار صريح ← قسم الأستاذ الوظيفي
    return (
        derive_users_department_id_for_storage(
            conn, role=role_n, student_id=None, instructor_id=instructor_id
        ),
        None,
    )


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


# ---------------------------------------------------------------------------
# مقررات: تصدير / تحقق نطاق / ربط استيراد
# ---------------------------------------------------------------------------

def resolve_college_general_department_id(conn) -> int | None:
    """معرّف قسم GENERAL (اتجاه عام الكلية)."""
    from backend.core.academic_pathway import resolve_college_general_department_id as _resolve

    return _resolve(conn.cursor())


def course_is_college_general(
    conn,
    course_name: str,
    *,
    course_code: str | None = None,
) -> bool:
    """هل المقرر ضمن اتجاه عام الكلية (خطة PROG_U1 أو ملكية قسم GENERAL)؟"""
    cname = (course_name or "").strip()
    if not cname:
        return False
    cur = conn.cursor()
    from backend.database.database import fetch_table_columns

    gen_id = resolve_college_general_department_id(conn)
    cols = fetch_table_columns(conn, "courses")
    if "owning_department_id" in cols and gen_id is not None:
        row = cur.execute(
            """
            SELECT owning_department_id FROM courses
            WHERE lower(trim(course_name)) = lower(trim(?))
            LIMIT 1
            """,
            (cname,),
        ).fetchone()
        if row:
            raw = row["owning_department_id"] if hasattr(row, "keys") else row[0]
            if raw not in (None, ""):
                try:
                    if int(raw) == int(gen_id):
                        return True
                except (TypeError, ValueError):
                    pass

    pc_cols = fetch_table_columns(conn, "program_courses")
    if "requirement_scope" not in pc_cols:
        return False
    code = (course_code or "").strip()
    row = cur.execute(
        """
        SELECT 1 FROM program_courses pc
        WHERE COALESCE(pc.requirement_scope, 'dept_common') = 'college_general'
          AND COALESCE(pc.is_active, 1) = 1
          AND (
            EXISTS (
              SELECT 1 FROM courses c
              LEFT JOIN course_master cm ON cm.id = c.course_master_id
              WHERE lower(trim(c.course_name)) = lower(trim(?))
                AND (
                  (c.course_master_id IS NOT NULL AND c.course_master_id = pc.course_master_id)
                  OR lower(trim(COALESCE(pc.course_code, ''))) = lower(trim(COALESCE(c.course_code, '')))
                  OR lower(trim(COALESCE(cm.title_ar, ''))) = lower(trim(?))
                )
            )
            OR (
              ? <> ''
              AND lower(trim(COALESCE(pc.course_code, ''))) = lower(trim(?))
            )
          )
        LIMIT 1
        """,
        (cname, cname, code, code),
    ).fetchone()
    return bool(row)


def _ensure_shared_catalog_tables(conn) -> None:
    try:
        from backend.core.college_shared_catalog import ensure_college_shared_catalog_schema

        ensure_college_shared_catalog_schema(conn)
    except Exception:
        pass


def course_is_college_shared_catalog(
    conn,
    course_name: str,
    *,
    department_id: int | None = None,
) -> bool:
    """هل المقرر في سجل المقررات المشتركة (مع اختيار تحقق قسم للنوع subset)؟"""
    cname = (course_name or "").strip()
    if not cname:
        return False
    _ensure_shared_catalog_tables(conn)
    cur = conn.cursor()
    row = cur.execute(
        """
        SELECT id, share_type FROM college_shared_catalog
        WHERE lower(trim(canonical_course_name)) = lower(trim(?))
          AND COALESCE(is_active, 1) = 1
        LIMIT 1
        """,
        (cname,),
    ).fetchone()
    if not row:
        return False
    cid = int(row[0] if not hasattr(row, "keys") else row["id"])
    st = str(row[1] if not hasattr(row, "keys") else row["share_type"] or "")
    if st != "subset" or department_id is None:
        return True
    hit = cur.execute(
        """
        SELECT 1 FROM college_shared_catalog_depts
        WHERE catalog_id = ? AND department_id = ? AND COALESCE(is_active, 1) = 1
        LIMIT 1
        """,
        (cid, int(department_id)),
    ).fetchone()
    return bool(hit)


def _general_owned_visibility_sql(
    conn,
    dep: int,
    *,
    owning_col: str = "owning_department_id",
    course_name_col: str = "course_name",
    table_alias: str = "",
) -> tuple[str, tuple]:
    """
    مقررات GENERAL الظاهرة لقسم: اتجاه عام + مشترك unified/multi_code + subset للمشاركين.
    """
    _ensure_shared_catalog_tables(conn)
    gen_id = resolve_college_general_department_id(conn)
    if gen_id is None:
        return " AND 1=0 ", ()
    prefix = f"{table_alias}." if table_alias else ""
    own_expr = f"{prefix}{owning_col.split('.')[-1]}" if table_alias else owning_col
    cname_expr = f"{prefix}{course_name_col.split('.')[-1]}" if table_alias else course_name_col
    return (
        f"""
         AND (
           COALESCE({own_expr}, -1) = ?
           OR {own_expr} IS NULL
           OR (
             COALESCE({own_expr}, -1) = ?
             AND (
               EXISTS (
                 SELECT 1 FROM program_courses pc
                 INNER JOIN courses __cg_c
                   ON lower(trim(__cg_c.course_name)) = lower(trim({cname_expr}))
                 WHERE COALESCE(pc.requirement_scope, 'dept_common') = 'college_general'
                   AND COALESCE(pc.is_active, 1) = 1
                   AND (
                     (__cg_c.course_master_id IS NOT NULL AND __cg_c.course_master_id = pc.course_master_id)
                     OR lower(trim(COALESCE(pc.course_code, ''))) = lower(trim(COALESCE(__cg_c.course_code, '')))
                   )
               )
               OR EXISTS (
                 SELECT 1 FROM college_shared_catalog csc
                 WHERE lower(trim(csc.canonical_course_name)) = lower(trim({cname_expr}))
                   AND COALESCE(csc.is_active, 1) = 1
                   AND csc.share_type IN ('unified', 'multi_code')
               )
               OR EXISTS (
                 SELECT 1 FROM college_shared_catalog csc
                 INNER JOIN college_shared_catalog_depts csd ON csd.catalog_id = csc.id
                 WHERE lower(trim(csc.canonical_course_name)) = lower(trim({cname_expr}))
                   AND COALESCE(csc.is_active, 1) = 1
                   AND csc.share_type = 'subset'
                   AND COALESCE(csd.is_active, 1) = 1
                   AND csd.department_id = ?
               )
             )
           )
         )
        """,
        (dep, int(gen_id), dep),
    )


def resolve_course_responsible_department_id(
    conn,
    course_name: str,
    *,
    teaching_group_id: int | None = None,
    section_id: int | None = None,
    semester: str | None = None,
) -> int | None:
    """
    القسم المختص بالمقرر للإشعارات والتقارير والاستبيانات.
    يعتمد سياق التدريس (مجموعة تدريس / شعبة / جدول) — وليس قسم المنزل للأستاذ.
    لا يُستخدم GENERAL كقسم تشغيلي للتوجيه.
    """
    cname = (course_name or "").strip()
    if not cname:
        return None
    cur = conn.cursor()
    gen_id = resolve_college_general_department_id(conn)

    def _valid_dept(raw) -> int | None:
        if raw in (None, ""):
            return None
        try:
            did = int(raw)
        except (TypeError, ValueError):
            return None
        if did <= 0:
            return None
        if gen_id is not None and did == int(gen_id):
            return None
        return did

    if teaching_group_id not in (None, ""):
        try:
            row = cur.execute(
                "SELECT department_id FROM teaching_groups WHERE id = ? LIMIT 1",
                (int(teaching_group_id),),
            ).fetchone()
            if row:
                did = _valid_dept(row["department_id"] if hasattr(row, "keys") else row[0])
                if did is not None:
                    return did
        except (TypeError, ValueError):
            pass

    if section_id not in (None, ""):
        try:
            from backend.database.database import schedule_pk_column

            pk = schedule_pk_column(conn)
            row = cur.execute(
                f"SELECT department_id FROM schedule WHERE {pk} = ? LIMIT 1",
                (int(section_id),),
            ).fetchone()
            if row:
                did = _valid_dept(row["department_id"] if hasattr(row, "keys") else row[0])
                if did is not None:
                    return did
        except (TypeError, ValueError):
            pass

    sem = (semester or "").strip()
    if sem:
        row = cur.execute(
            """
            SELECT department_id FROM schedule
            WHERE lower(trim(course_name)) = lower(trim(?))
              AND department_id IS NOT NULL
              AND COALESCE(semester, '') LIKE ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (cname, f"%{sem}%"),
        ).fetchone()
        if row:
            did = _valid_dept(row[0] if not hasattr(row, "keys") else row["department_id"])
            if did is not None:
                return did

    row = cur.execute(
        """
        SELECT department_id FROM schedule
        WHERE lower(trim(course_name)) = lower(trim(?))
          AND department_id IS NOT NULL
        ORDER BY id DESC
        LIMIT 1
        """,
        (cname,),
    ).fetchone()
    if row:
        did = _valid_dept(row[0] if not hasattr(row, "keys") else row["department_id"])
        if did is not None:
            return did

    row = cur.execute(
        """
        SELECT department_id FROM teaching_groups
        WHERE lower(trim(course_name)) = lower(trim(?))
          AND department_id IS NOT NULL
        ORDER BY id DESC
        LIMIT 1
        """,
        (cname,),
    ).fetchone()
    if row:
        did = _valid_dept(row[0] if not hasattr(row, "keys") else row["department_id"])
        if did is not None:
            return did

    from backend.database.database import fetch_table_columns

    cols = fetch_table_columns(conn, "courses")
    if "owning_department_id" in cols:
        row = cur.execute(
            """
            SELECT owning_department_id FROM courses
            WHERE lower(trim(course_name)) = lower(trim(?))
            LIMIT 1
            """,
            (cname,),
        ).fetchone()
        if row:
            did = _valid_dept(row[0] if not hasattr(row, "keys") else row["owning_department_id"])
            if did is not None:
                return did

    return None


_COLLEGE_WIDE_COURSE_OPS_ROLES = frozenset(
    {
        "admin",
        "admin_main",
        "system_admin",
        "college_dean",
        "academic_vice_dean",
    }
)


def actor_role_for_username(conn, actor_username: str | None) -> str:
    """دور المستخدم من قاعدة البيانات (بدون الاعتماد على الجلسة فقط)."""
    un = _actor_username(actor_username)
    if not un:
        return ""
    row = conn.cursor().execute(
        "SELECT role FROM users WHERE lower(username) = lower(?) LIMIT 1",
        (un,),
    ).fetchone()
    if not row:
        return ""
    raw = row["role"] if hasattr(row, "keys") else row[0]
    return _normalize_role(str(raw or "").strip())


def actor_bypasses_course_department_guard(conn, actor_username: str | None) -> bool:
    """أدوار الكلية/الإدارة التي لا تُقيَّد بقسم عرض المقرر."""
    return actor_role_for_username(conn, actor_username) in _COLLEGE_WIDE_COURSE_OPS_ROLES


def hod_may_operate_on_course(
    conn,
    actor_username: str | None,
    course_name: str,
    *,
    teaching_group_id: int | None = None,
    section_id: int | None = None,
    semester: str | None = None,
) -> bool:
    """
    هل يجوز لرئيس القسم (أو الإدارة العليا) اعتماد/مراجعة عمليات هذا المقرر؟
    يعتمد على قسم العرض (مجموعة تدريس / جدول) وليس قسم منزل الأستاذ.
    """
    if actor_bypasses_course_department_guard(conn, actor_username):
        return True
    role = actor_role_for_username(conn, actor_username)
    if role != "head_of_department":
        return False
    scope_dep = resolve_effective_department_scope_id(conn, actor_username)
    if scope_dep is None:
        return False
    responsible = resolve_course_responsible_department_id(
        conn,
        course_name,
        teaching_group_id=teaching_group_id,
        section_id=section_id,
        semester=semester,
    )
    if responsible is None:
        return False
    return int(responsible) == int(scope_dep)


def assert_hod_for_course_operation(
    conn,
    actor_username: str | None,
    course_name: str,
    *,
    teaching_group_id: int | None = None,
    section_id: int | None = None,
    semester: str | None = None,
) -> None:
    """يرفض العملية إذا كان رئيس القسم خارج نطاق قسم عرض المقرر."""
    if hod_may_operate_on_course(
        conn,
        actor_username,
        course_name,
        teaching_group_id=teaching_group_id,
        section_id=section_id,
        semester=semester,
    ):
        return
    raise PermissionError("FORBIDDEN_DEPARTMENT_SCOPE")


def filter_items_for_course_hod_scope(
    conn,
    actor_username: str | None,
    items: list[dict],
    *,
    course_name_key: str = "course_name",
    teaching_group_id_key: str = "teaching_group_id",
    section_id_key: str = "section_id",
    semester_key: str = "semester",
) -> list[dict]:
    """يُبقي عناصر القائمة التي يجوز لرئيس القسم رؤيتها/اعتمادها."""
    if actor_bypasses_course_department_guard(conn, actor_username):
        return items
    if actor_role_for_username(conn, actor_username) != "head_of_department":
        return items
    out: list[dict] = []
    for item in items:
        if hod_may_operate_on_course(
            conn,
            actor_username,
            str(item.get(course_name_key) or ""),
            teaching_group_id=item.get(teaching_group_id_key),
            section_id=item.get(section_id_key),
            semester=item.get(semester_key),
        ):
            out.append(item)
    return out


def courses_department_scope_filter(
    conn,
    scope_dep: int | None,
    *,
    owning_col: str = "owning_department_id",
    course_name_col: str = "course_name",
) -> tuple[str, tuple]:
    """
    شرط SQL لعرض مقررات القسم + الاتجاه العام + المشترك حسب النوع.
    """
    if scope_dep is None:
        return "", ()
    dep = int(scope_dep)
    table_alias = ""
    own_col = owning_col
    cname_col = course_name_col
    if "." in own_col:
        parts = own_col.split(".", 1)
        table_alias, own_col = parts[0], parts[1]
    if "." in cname_col:
        cname_col = cname_col.split(".", 1)[1]
    return _general_owned_visibility_sql(
        conn,
        dep,
        owning_col=own_col,
        course_name_col=cname_col,
        table_alias=table_alias,
    )


def resolve_import_owning_department_id(
    conn,
    course_name: str,
    importer_dept_id: int | None,
    *,
    course_code: str | None = None,
) -> int | None:
    """قسم المالك عند الاستيراد: GENERAL للاتجاه العام، وإلا قسم المنفّذ."""
    if importer_dept_id is None:
        return None
    if course_is_college_general(conn, course_name, course_code=course_code):
        return resolve_college_general_department_id(conn)
    if course_is_college_shared_catalog(conn, course_name):
        return resolve_college_general_department_id(conn)
    return int(importer_dept_id)


def _actor_username(actor_username: str | None) -> str:
    if actor_username is not None:
        return (actor_username or "").strip()
    try:
        from flask import session

        return (session.get("user") or session.get("username") or "").strip()
    except Exception:
        return ""


def courses_export_sql_and_params(
    conn,
    actor_username: str | None = None,
) -> tuple[str, tuple]:
    """استعلام تصدير المقررات مع احترام نطاق قسم المنفّذ."""
    from backend.database.database import fetch_table_columns

    scope_dep = resolve_effective_department_scope_id(conn, _actor_username(actor_username))
    try:
        cols = fetch_table_columns(conn, "courses")
    except Exception:
        cols = []
    has_owning = "owning_department_id" in cols

    if scope_dep is not None and has_owning:
        scope_sql, scope_params = courses_department_scope_filter(conn, int(scope_dep))
        return (
            "SELECT course_name, course_code, units FROM courses "
            f"WHERE COALESCE(course_name, '') <> ''{scope_sql}"
            "ORDER BY course_name",
            scope_params,
        )
    if scope_dep is not None:
        try:
            sch_cols = fetch_table_columns(conn, "schedule")
        except Exception:
            sch_cols = []
        if "department_id" in sch_cols:
            return (
                """
                SELECT DISTINCT COALESCE(s.course_name, '') AS course_name,
                       COALESCE(c.course_code, '') AS course_code,
                       COALESCE(c.units, 0) AS units
                FROM schedule s
                LEFT JOIN courses c
                  ON LOWER(TRIM(COALESCE(c.course_name, ''))) = LOWER(TRIM(COALESCE(s.course_name, '')))
                WHERE COALESCE(s.course_name, '') <> ''
                  AND COALESCE(s.department_id, -1) = ?
                ORDER BY course_name
                """,
                (int(scope_dep),),
            )
        return (
            "SELECT course_name, course_code, units FROM courses WHERE 1 = 0",
            (),
        )
    return (
        "SELECT course_name, course_code, units FROM courses "
        "WHERE COALESCE(course_name, '') <> '' ORDER BY course_name",
        (),
    )


def course_in_actor_scope(
    conn,
    course_name: str,
    actor_username: str | None = None,
) -> bool:
    """هل المقرر ضمن نطاق قسم المنفّذ؟"""
    dep = resolve_effective_department_scope_id(conn, _actor_username(actor_username))
    if dep is None:
        return True
    cname = (course_name or "").strip()
    if not cname:
        return False
    cur = conn.cursor()
    from backend.database.database import fetch_table_columns

    cols = fetch_table_columns(conn, "courses")
    if course_is_college_general(conn, cname):
        return True
    if course_is_college_shared_catalog(conn, cname, department_id=int(dep)):
        return True
    if "owning_department_id" in cols:
        gen_id = resolve_college_general_department_id(conn)
        row = cur.execute(
            """
            SELECT owning_department_id FROM courses
            WHERE lower(trim(course_name)) = lower(trim(?))
            LIMIT 1
            """,
            (cname,),
        ).fetchone()
        if row:
            raw = row["owning_department_id"] if hasattr(row, "keys") else row[0]
            if raw in (None, ""):
                return True
            try:
                oid = int(raw)
                if oid == int(dep):
                    return True
                if gen_id is not None and oid == int(gen_id):
                    return course_is_college_general(conn, cname) or course_is_college_shared_catalog(
                        conn, cname, department_id=int(dep)
                    )
                return False
            except (TypeError, ValueError):
                return False
    sch_cols = fetch_table_columns(conn, "schedule")
    if "department_id" in sch_cols:
        row = cur.execute(
            """
            SELECT 1 FROM schedule
            WHERE lower(trim(course_name)) = lower(trim(?))
              AND COALESCE(department_id, -1) = ?
            LIMIT 1
            """,
            (cname, int(dep)),
        ).fetchone()
        return bool(row)
    return False


def assert_course_in_actor_scope(
    conn,
    course_name: str,
    actor_username: str | None = None,
) -> None:
    if not course_in_actor_scope(conn, course_name, actor_username):
        label = (course_name or "").strip() or "—"
        raise ValueError(f"المقرر «{label}» خارج نطاق قسمك.")


def actor_manages_college_general_scope(
    conn,
    actor_username: str | None = None,
) -> bool:
    """هل نطاق الفاعل هو قسم الاتجاه العام (GENERAL)؟"""
    dep = resolve_effective_department_scope_id(conn, _actor_username(actor_username))
    gen_id = resolve_college_general_department_id(conn)
    if dep is None or gen_id is None:
        return False
    try:
        return int(dep) == int(gen_id)
    except (TypeError, ValueError):
        return False


def _course_owning_department_id(conn, course_name: str) -> int | None:
    cname = (course_name or "").strip()
    if not cname:
        return None
    from backend.database.database import fetch_table_columns

    cols = fetch_table_columns(conn, "courses")
    if "owning_department_id" not in cols:
        return None
    cur = conn.cursor()
    row = cur.execute(
        """
        SELECT owning_department_id FROM courses
        WHERE lower(trim(course_name)) = lower(trim(?))
        LIMIT 1
        """,
        (cname,),
    ).fetchone()
    if not row:
        return None
    raw = row["owning_department_id"] if hasattr(row, "keys") else row[0]
    if raw in (None, ""):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def course_writable_by_actor(
    conn,
    course_name: str,
    actor_username: str | None = None,
) -> bool:
    """
    صلاحية *تعديل/حذف* المقرر (أضيق من العرض).

    - أدمن / عميد / وكيلة: الكل (بما فيها المشتركة).
    - نطاق كلية بلا قسم: الكل.
    - رئيس الاتجاه العام (GENERAL): مقررات الاتجاه العام المملوكة لـ GENERAL فقط —
      بدون مقررات السجل المشترك.
    - رئيس تخصص: مقررات قسمه فقط — دون العامة/المشتركة (عرض فقط).
    """
    actor = _actor_username(actor_username)
    try:
        from flask import session
        from backend.core.auth import _normalize_role

        role = _normalize_role((session.get("user_role") or "").strip())
        if role in ("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean"):
            return True
    except Exception:
        pass

    dep = resolve_effective_department_scope_id(conn, actor)
    if dep is None:
        return True
    cname = (course_name or "").strip()
    if not cname:
        return False
    gen_id = resolve_college_general_department_id(conn)
    owning = _course_owning_department_id(conn, cname)
    is_general_course = course_is_college_general(conn, cname)
    is_shared = course_is_college_shared_catalog(conn, cname)

    if actor_manages_college_general_scope(conn, actor):
        # المقررات المشتركة: للكلية فقط (عميد/وكيلة/أدمن)
        if is_shared:
            return False
        if is_general_course:
            return True
        if owning is None:
            return True
        if gen_id is not None and owning == int(gen_id):
            return True
        return False

    # رئيس تخصص / نطاق قسم آخر: لا تعديل للعامة/المشتركة
    if is_general_course or is_shared:
        return False
    if gen_id is not None and owning is not None and owning == int(gen_id):
        return False
    if owning is not None:
        return owning == int(dep)
    # بلا مالك: السماح فقط إن كان ظاهراً في نطاق القسم عبر الجدول
    return course_in_actor_scope(conn, cname, actor)


def assert_course_writable_by_actor(
    conn,
    course_name: str,
    actor_username: str | None = None,
) -> None:
    if not course_writable_by_actor(conn, course_name, actor_username):
        label = (course_name or "").strip() or "—"
        raise ValueError(
            f"لا يمكن تعديل المقرر «{label}» من نطاق قسمك "
            "(مقرر مشترك يُدار من العميد/الوكيلة/الإدارة، أو خارج قسمك)."
        )


def can_manage_college_shared_catalog(
    conn,
    actor_username: str | None = None,
    *,
    user_role: str | None = None,
) -> bool:
    """كتابة سجل المقررات المشتركة: أدمن رئيسي / عميد / وكيلة فقط."""
    role = (user_role or "").strip()
    if not role:
        try:
            from flask import session

            role = (session.get("user_role") or "").strip()
        except Exception:
            role = ""
    return role in (
        "admin",
        "admin_main",
        "system_admin",
        "college_dean",
        "academic_vice_dean",
    )


def student_in_actor_scope(
    conn,
    student_id: str,
    actor_username: str | None = None,
) -> bool:
    mode, dep_id = resolve_users_list_scope(conn, _actor_username(actor_username))
    if mode == "none":
        return True
    if mode == "empty" or dep_id is None:
        return False
    return student_matches_department(conn, student_id, int(dep_id))


def assert_student_in_actor_scope(
    conn,
    student_id: str,
    actor_username: str | None = None,
) -> None:
    if not student_in_actor_scope(conn, student_id, actor_username):
        sid = (student_id or "").strip() or "—"
        raise ValueError(f"الطالب {sid} خارج نطاق قسمك.")


def resolve_import_department_binding(
    conn,
    actor_username: str | None = None,
) -> tuple[int | None, int | None]:
    """قسم/برنامج الربط التلقائي عند الاستيراد حسب نطاق المنفّذ."""
    dept_id = resolve_effective_department_scope_id(conn, _actor_username(actor_username))
    if dept_id is None:
        return None, None
    prog_id = major_program_id_for_department(conn, int(dept_id))
    return int(dept_id), prog_id


def resolve_registration_course_scope_sql(
    conn,
    actor_username: str | None,
    *,
    registration_course_col: str = "r.course_name",
) -> tuple[str, tuple]:
    """جزء AND لفلترة أسماء المقررات في تقارير التسجيل حسب القسم."""
    scope_dep = resolve_effective_department_scope_id(conn, _actor_username(actor_username))
    if scope_dep is None:
        return "", ()
    dep = int(scope_dep)
    from backend.database.database import fetch_table_columns

    cols = fetch_table_columns(conn, "courses")
    if "owning_department_id" in cols:
        scope_sql, scope_params = courses_department_scope_filter(
            conn, dep, owning_col="__c_reg_scope.owning_department_id"
        )
        return (
            f"""
            AND EXISTS (
                SELECT 1 FROM courses __c_reg_scope
                WHERE lower(trim(__c_reg_scope.course_name)) = lower(trim({registration_course_col}))
                {scope_sql}
            )
            """,
            scope_params,
        )
    sch_cols = fetch_table_columns(conn, "schedule")
    if "department_id" in sch_cols:
        return (
            f"""
            AND EXISTS (
                SELECT 1 FROM schedule __sch_reg_scope
                WHERE lower(trim(__sch_reg_scope.course_name)) = lower(trim({registration_course_col}))
                  AND COALESCE(__sch_reg_scope.department_id, -1) = ?
            )
            """,
            (dep,),
        )
    return " AND 1=0 ", ()


def backfill_courses_owning_department_from_schedule(
    conn,
    *,
    department_id: int | None = None,
) -> int:
    """
    ربط owning_department_id من جدول schedule للمقررات التي تفتقد مالكاً.
    يُرجع عدد الصفوف المُحدَّثة.
    """
    from backend.database.database import fetch_table_columns

    cols = fetch_table_columns(conn, "courses")
    sch_cols = fetch_table_columns(conn, "schedule")
    if "owning_department_id" not in cols or "department_id" not in sch_cols:
        return 0
    cur = conn.cursor()
    pc_cols = fetch_table_columns(conn, "program_courses")
    college_general_guard = ""
    if "requirement_scope" in pc_cols:
        college_general_guard = """
          AND NOT EXISTS (
            SELECT 1 FROM program_courses pc
            INNER JOIN courses c2 ON (
              (c2.course_master_id IS NOT NULL AND c2.course_master_id = pc.course_master_id)
              OR lower(trim(COALESCE(pc.course_code, ''))) = lower(trim(COALESCE(c2.course_code, '')))
            )
            WHERE lower(trim(c2.course_name)) = lower(trim(courses.course_name))
              AND COALESCE(pc.requirement_scope, 'dept_common') = 'college_general'
              AND COALESCE(pc.is_active, 1) = 1
          )
        """
    params: list = []
    dept_filter = ""
    if department_id is not None:
        dep = int(department_id)
        dept_filter = " AND COALESCE(s.department_id, -1) = ? "
        params = [dep, dep]
    cur.execute(
        f"""
        UPDATE courses
        SET owning_department_id = (
            SELECT s.department_id FROM schedule s
            WHERE lower(trim(s.course_name)) = lower(trim(courses.course_name))
              AND COALESCE(s.department_id, -1) > 0
              {dept_filter}
            LIMIT 1
        )
        WHERE COALESCE(owning_department_id, 0) = 0
          {college_general_guard}
          AND EXISTS (
            SELECT 1 FROM schedule s
            WHERE lower(trim(s.course_name)) = lower(trim(courses.course_name))
              AND COALESCE(s.department_id, -1) > 0
              {dept_filter}
          )
        """,
        tuple(params),
    )
    return int(cur.rowcount or 0)


def invalidate_department_scope_list_caches() -> None:
    """إبطال قوائم القراءة عند تغيير نطاق القسم في الجلسة."""
    try:
        from backend.core.cache_setup import invalidate_list_prefix

        for prefix in ("courses", "students", "schedule", "instructors"):
            invalidate_list_prefix(prefix)
    except Exception:
        pass

