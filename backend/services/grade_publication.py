"""نشر الدرجات: جزئي (أستاذ/HoD)، حزمة نهائية للقسم (HoD → عميد)."""

from __future__ import annotations

import datetime
from typing import Any

from flask import session

from backend.core.department_scope_policy import (
    assert_hod_for_course_operation,
    filter_items_for_course_hod_scope,
    hod_may_operate_on_course,
    resolve_users_list_scope,
)
from backend.database.database import fetch_table_columns, is_postgresql, table_exists
from backend.services.utilities import get_current_term

BATCH_STATUSES = frozenset(
    {
        "collecting",
        "submitted_to_dean",
        "returned_to_hod",
        "published",
    }
)

_PARTIAL_PUBLISH_ROLES = frozenset({"instructor", "head_of_department", "admin_main", "admin"})
_DEAN_PUBLISH_ROLES = frozenset({"admin_main", "admin", "system_admin", "college_dean", "academic_vice_dean"})


def _now_iso() -> str:
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _row_dict(row) -> dict:
    if row is None:
        return {}
    if hasattr(row, "keys"):
        return dict(row)
    return {}


def _actor() -> str:
    return (session.get("user") or session.get("username") or "").strip() or "system"


def _role() -> str:
    return (session.get("user_role") or "").strip().lower()


def ensure_grade_publication_schema(conn) -> None:
    """إنشاء/ترقية جداول وأعمدة نشر الدرجات."""
    cur = conn.cursor()
    gd_cols = {c.lower() for c in fetch_table_columns(conn, "grade_drafts")}
    extra_gd = [
        ("partial_published_at", "TEXT"),
        ("partial_published_by", "TEXT"),
        ("hod_final_approved_at", "TEXT"),
        ("hod_final_approved_by", "TEXT"),
        ("batch_id", "INTEGER"),
    ]
    for col, typ in extra_gd:
        if col not in gd_cols:
            try:
                if is_postgresql():
                    cur.execute(f"ALTER TABLE grade_drafts ADD COLUMN IF NOT EXISTS {col} {typ}")
                else:
                    cur.execute(f"ALTER TABLE grade_drafts ADD COLUMN {col} {typ}")
            except Exception:
                pass

    if not table_exists(conn, "department_final_grade_batches"):
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS department_final_grade_batches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                department_id INTEGER NOT NULL,
                semester TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'collecting',
                completion_percent REAL NOT NULL DEFAULT 0,
                total_courses INTEGER NOT NULL DEFAULT 0,
                ready_courses INTEGER NOT NULL DEFAULT 0,
                submitted_at TEXT,
                submitted_by TEXT,
                published_at TEXT,
                published_by TEXT,
                hod_note TEXT DEFAULT '',
                dean_note TEXT DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (department_id, semester)
            )
            """
        )
    if not table_exists(conn, "student_published_grades"):
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS student_published_grades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id TEXT NOT NULL,
                semester TEXT NOT NULL,
                course_name TEXT NOT NULL,
                section_id INTEGER,
                draft_id INTEGER,
                coursework REAL,
                midterm REAL,
                partial_total REAL,
                final_exam REAL,
                total REAL,
                visibility TEXT NOT NULL DEFAULT 'partial'
                    CHECK (visibility IN ('partial', 'final')),
                published_at TEXT,
                published_by TEXT,
                UNIQUE (student_id, semester, course_name, visibility)
            )
            """
        )
    try:
        conn.commit()
    except Exception:
        pass


def _semester_label(conn) -> str:
    tn, ty = get_current_term(conn=conn)
    return f"{(tn or '').strip()} {(ty or '').strip()}".strip()


def _draft_phase(drow: dict) -> str:
    return str(drow.get("draft_phase") or "combined").strip().lower()


def _draft_department_id(conn, drow: dict) -> int | None:
    cur = conn.cursor()
    tgid = drow.get("teaching_group_id")
    if tgid not in (None, "", 0):
        try:
            row = cur.execute(
                "SELECT department_id FROM teaching_groups WHERE id = ? LIMIT 1",
                (int(tgid),),
            ).fetchone()
            if row and row[0] not in (None, ""):
                return int(row[0])
        except Exception:
            pass
    cn = (drow.get("course_name") or "").strip()
    if cn:
        try:
            row = cur.execute(
                "SELECT owning_department_id FROM courses WHERE course_name = ? LIMIT 1",
                (cn,),
            ).fetchone()
            if row and row[0] not in (None, ""):
                return int(row[0])
        except Exception:
            pass
    iid = drow.get("instructor_id")
    if iid:
        try:
            row = cur.execute(
                "SELECT department_id FROM instructors WHERE id = ? LIMIT 1",
                (int(iid),),
            ).fetchone()
            if row and row[0] not in (None, ""):
                return int(row[0])
        except Exception:
            pass
    return None


def _instructor_owns_draft(drow: dict) -> bool:
    try:
        iid = int(session.get("instructor_id") or 0)
    except (TypeError, ValueError):
        iid = 0
    try:
        return iid > 0 and int(drow.get("instructor_id") or 0) == iid
    except (TypeError, ValueError):
        return False


def _can_publish_partial(conn, drow: dict) -> bool:
    role = _role()
    actor = _actor()
    phase = _draft_phase(drow)
    if phase not in ("partial", "combined"):
        return False
    if role in ("admin_main", "admin"):
        return True
    if role == "instructor" and _instructor_owns_draft(drow):
        return True
    if role == "head_of_department":
        try:
            if hod_may_operate_on_course(
                conn,
                actor,
                str(drow.get("course_name") or ""),
                teaching_group_id=drow.get("teaching_group_id"),
                section_id=drow.get("section_id"),
                semester=str(drow.get("semester") or ""),
            ):
                return True
        except Exception:
            pass
        dept_id = _hod_department_id(conn, actor)
        draft_dept = _draft_department_id(conn, drow)
        return dept_id is not None and draft_dept is not None and int(dept_id) == int(draft_dept)
    return False


def _compute_partial_total(coursework, midterm) -> float | None:
    parts = []
    for v in (coursework, midterm):
        if v is not None and v != "":
            try:
                parts.append(float(v))
            except (TypeError, ValueError):
                pass
    if not parts:
        return None
    return round(sum(parts), 2)


def publish_partial_draft(conn, draft_id: int, *, actor: str | None = None) -> dict[str, Any]:
    ensure_grade_publication_schema(conn)
    actor = actor or _actor()
    cur = conn.cursor()
    d = cur.execute("SELECT * FROM grade_drafts WHERE id = ?", (int(draft_id),)).fetchone()
    if not d:
        return {"ok": False, "message": "المسودة غير موجودة", "code": 404}
    drow = _row_dict(d)
    if not _can_publish_partial(conn, drow):
        return {"ok": False, "message": "غير مصرح بنشر الجزئي", "code": 403}
    status = (drow.get("status") or "").strip()
    if status not in ("Draft", "Submitted", "Approved", "Rejected"):
        return {"ok": False, "message": "حالة المسودة لا تسمح بالنشر", "code": 400}

    items = cur.execute(
        """
        SELECT student_id, coursework, midterm, computed_total
        FROM grade_draft_items WHERE draft_id = ?
        """,
        (int(draft_id),),
    ).fetchall()
    if not items:
        return {"ok": False, "message": "لا توجد درجات في المسودة", "code": 400}

    now = _now_iso()
    semester = (drow.get("semester") or "").strip()
    course_name = (drow.get("course_name") or "").strip()
    section_id = drow.get("section_id")
    published = 0
    for it in items:
        row = _row_dict(it)
        sid = str(row.get("student_id") or "").strip()
        if not sid:
            continue
        cw = row.get("coursework")
        md = row.get("midterm")
        pt = _compute_partial_total(cw, md)
        if pt is None:
            continue
        if is_postgresql():
            cur.execute(
                """
                INSERT INTO student_published_grades
                    (student_id, semester, course_name, section_id, draft_id,
                     coursework, midterm, partial_total, visibility, published_at, published_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'partial', ?, ?)
                ON CONFLICT (student_id, semester, course_name, visibility)
                DO UPDATE SET
                    section_id = EXCLUDED.section_id,
                    draft_id = EXCLUDED.draft_id,
                    coursework = EXCLUDED.coursework,
                    midterm = EXCLUDED.midterm,
                    partial_total = EXCLUDED.partial_total,
                    published_at = EXCLUDED.published_at,
                    published_by = EXCLUDED.published_by
                """,
                (sid, semester, course_name, section_id, int(draft_id), cw, md, pt, now, actor),
            )
        else:
            cur.execute(
                """
                INSERT INTO student_published_grades
                    (student_id, semester, course_name, section_id, draft_id,
                     coursework, midterm, partial_total, visibility, published_at, published_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'partial', ?, ?)
                ON CONFLICT(student_id, semester, course_name, visibility)
                DO UPDATE SET
                    section_id = excluded.section_id,
                    draft_id = excluded.draft_id,
                    coursework = excluded.coursework,
                    midterm = excluded.midterm,
                    partial_total = excluded.partial_total,
                    published_at = excluded.published_at,
                    published_by = excluded.published_by
                """,
                (sid, semester, course_name, section_id, int(draft_id), cw, md, pt, now, actor),
            )
        published += 1

    cur.execute(
        """
        UPDATE grade_drafts
        SET partial_published_at = ?, partial_published_by = ?, updated_at = ?
        WHERE id = ?
        """,
        (now, actor, now, int(draft_id)),
    )
    conn.commit()
    return {"ok": True, "published_students": published, "draft_id": int(draft_id)}


def hod_approve_final_draft(conn, draft_id: int, *, actor: str | None = None) -> dict[str, Any]:
    """اعتماد داخلي لمسودة نهائي/مجمّع — بدون نشر للطالب."""
    ensure_grade_publication_schema(conn)
    actor = actor or _actor()
    if _role() not in ("head_of_department", "admin_main", "admin"):
        return {"ok": False, "message": "غير مصرح", "code": 403}
    cur = conn.cursor()
    d = cur.execute("SELECT * FROM grade_drafts WHERE id = ?", (int(draft_id),)).fetchone()
    if not d:
        return {"ok": False, "message": "المسودة غير موجودة", "code": 404}
    drow = _row_dict(d)
    phase = _draft_phase(drow)
    if phase not in ("final", "combined"):
        return {"ok": False, "message": "الاعتماد الداخلي للنهائي فقط", "code": 400}
    if (drow.get("status") or "") not in ("Submitted",):
        return {"ok": False, "message": "يجب أن تكون المسودة مُرسلة (Submitted)", "code": 400}
    try:
        assert_hod_for_course_operation(
            conn,
            actor,
            str(drow.get("course_name") or ""),
            teaching_group_id=drow.get("teaching_group_id"),
            section_id=drow.get("section_id"),
            semester=str(drow.get("semester") or ""),
        )
    except PermissionError:
        return {"ok": False, "message": "FORBIDDEN_DEPARTMENT_SCOPE", "code": 403}

    now = _now_iso()
    cur.execute(
        """
        UPDATE grade_drafts
        SET status = 'Approved',
            hod_final_approved_at = ?,
            hod_final_approved_by = ?,
            approved_at = ?,
            approved_by = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (now, actor, now, actor, now, int(draft_id)),
    )
    conn.commit()
    return {"ok": True, "draft_id": int(draft_id)}


def publish_final_draft_to_grades(conn, draft_id: int, *, actor: str) -> int:
    """نشر مسودة نهائية في grades + student_published_grades (نهائي)."""
    cur = conn.cursor()
    d = cur.execute("SELECT * FROM grade_drafts WHERE id = ?", (int(draft_id),)).fetchone()
    if not d:
        return 0
    drow = _row_dict(d)
    semester = (drow.get("semester") or "").strip()
    course_name = (drow.get("course_name") or "").strip()
    section_id = drow.get("section_id")
    now = _now_iso()
    items = cur.execute(
        """
        SELECT student_id, coursework, midterm, final_exam, computed_total
        FROM grade_draft_items WHERE draft_id = ?
        """,
        (int(draft_id),),
    ).fetchall()
    published = 0
    for it in items or []:
        row = _row_dict(it)
        sid = str(row.get("student_id") or "").strip()
        if not sid:
            continue
        grade_val = row.get("computed_total")
        cw = row.get("coursework")
        md = row.get("midterm")
        fe = row.get("final_exam")
        old = cur.execute(
            "SELECT grade FROM grades WHERE student_id=? AND semester=? AND course_name=?",
            (sid, semester, course_name),
        ).fetchone()
        old_grade = old[0] if old else None
        if is_postgresql():
            cur.execute(
                """
                INSERT INTO grades (student_id, semester, course_name, grade, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (student_id, semester, course_name)
                DO UPDATE SET grade = EXCLUDED.grade, updated_at = EXCLUDED.updated_at
                """,
                (sid, semester, course_name, grade_val, now),
            )
        else:
            cur.execute(
                """
                INSERT INTO grades (student_id, semester, course_name, grade, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(student_id, semester, course_name)
                DO UPDATE SET grade = excluded.grade, updated_at = excluded.updated_at
                """,
                (sid, semester, course_name, grade_val, now),
            )
        try:
            cur.execute(
                """
                INSERT INTO grade_audit
                    (student_id, semester, course_name, old_grade, new_grade, changed_by, ts)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (sid, semester, course_name, old_grade, grade_val, actor, now),
            )
        except Exception:
            pass
        pt = _compute_partial_total(cw, md)
        if is_postgresql():
            cur.execute(
                """
                INSERT INTO student_published_grades
                    (student_id, semester, course_name, section_id, draft_id,
                     coursework, midterm, partial_total, final_exam, total,
                     visibility, published_at, published_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'final', ?, ?)
                ON CONFLICT (student_id, semester, course_name, visibility)
                DO UPDATE SET
                    coursework = EXCLUDED.coursework,
                    midterm = EXCLUDED.midterm,
                    partial_total = EXCLUDED.partial_total,
                    final_exam = EXCLUDED.final_exam,
                    total = EXCLUDED.total,
                    published_at = EXCLUDED.published_at,
                    published_by = EXCLUDED.published_by
                """,
                (
                    sid,
                    semester,
                    course_name,
                    section_id,
                    int(draft_id),
                    cw,
                    md,
                    pt,
                    fe,
                    grade_val,
                    now,
                    actor,
                ),
            )
        else:
            cur.execute(
                """
                INSERT INTO student_published_grades
                    (student_id, semester, course_name, section_id, draft_id,
                     coursework, midterm, partial_total, final_exam, total,
                     visibility, published_at, published_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'final', ?, ?)
                ON CONFLICT(student_id, semester, course_name, visibility)
                DO UPDATE SET
                    coursework = excluded.coursework,
                    midterm = excluded.midterm,
                    partial_total = excluded.partial_total,
                    final_exam = excluded.final_exam,
                    total = excluded.total,
                    published_at = excluded.published_at,
                    published_by = excluded.published_by
                """,
                (
                    sid,
                    semester,
                    course_name,
                    section_id,
                    int(draft_id),
                    cw,
                    md,
                    pt,
                    fe,
                    grade_val,
                    now,
                    actor,
                ),
            )
        published += 1
    return published


def _list_department_final_drafts(conn, department_id: int, semester: str, actor: str) -> list[dict]:
    ensure_grade_publication_schema(conn)
    cur = conn.cursor()
    gd_cols = {c.lower() for c in fetch_table_columns(conn, "grade_drafts")}
    dp_col = ", COALESCE(d.draft_phase, 'combined') AS draft_phase" if "draft_phase" in gd_cols else ", 'combined' AS draft_phase"
    tgid_col = ", d.teaching_group_id" if "teaching_group_id" in gd_cols else ""
    hod_col = ", d.hod_final_approved_at" if "hod_final_approved_at" in gd_cols else ", NULL AS hod_final_approved_at"
    pp_col = ", d.partial_published_at" if "partial_published_at" in gd_cols else ", NULL AS partial_published_at"
    rows = cur.execute(
        f"""
        SELECT d.id, d.semester, d.course_name, d.section_id{tgid_col}{dp_col},
               d.status, d.submitted_at, d.instructor_id,
               COALESCE(i.name, '') AS instructor_name
               {hod_col}{pp_col}
        FROM grade_drafts d
        LEFT JOIN instructors i ON i.id = d.instructor_id
        WHERE d.semester = ?
          AND COALESCE(d.draft_phase, 'combined') IN ('final', 'combined')
        ORDER BY d.course_name, d.section_id
        """,
        (semester,),
    ).fetchall()
    out: list[dict] = []
    for r in rows or []:
        item = _row_dict(r)
        dept_id = _draft_department_id(conn, item)
        if dept_id is not None and int(dept_id) != int(department_id):
            continue
        scoped = filter_items_for_course_hod_scope(conn, actor, [item])
        if not scoped and _role() == "head_of_department":
            continue
        item["department_id"] = dept_id
        item["hod_ready"] = bool(item.get("hod_final_approved_at"))
        item["readiness"] = _draft_readiness_label(item)
        out.append(item)
    return out


def _draft_readiness_label(d: dict) -> str:
    st = (d.get("status") or "").strip()
    if d.get("hod_final_approved_at"):
        return "ready"
    if st == "Submitted":
        return "submitted"
    if st in ("Draft", "Rejected"):
        return "in_progress"
    if st == "Approved" and not d.get("hod_final_approved_at"):
        return "needs_hod"
    return "other"


def _expected_department_courses(conn, department_id: int, semester: str) -> int:
    cur = conn.cursor()
    if table_exists(conn, "teaching_groups"):
        row = cur.execute(
            """
            SELECT COUNT(DISTINCT course_name || '::' || COALESCE(CAST(instructor_id AS TEXT), ''))
            FROM teaching_groups
            WHERE semester = ? AND department_id = ? AND COALESCE(is_active, 1) = 1
            """,
            (semester, int(department_id)),
        ).fetchone()
        n = int((row[0] if row else 0) or 0)
        if n > 0:
            return n
    row = cur.execute(
        """
        SELECT COUNT(DISTINCT d.id)
        FROM grade_drafts d
        WHERE d.semester = ?
          AND COALESCE(d.draft_phase, 'combined') IN ('final', 'combined')
        """,
        (semester,),
    ).fetchone()
    return max(1, int((row[0] if row else 0) or 0))


def build_hod_final_batch_summary(conn, *, department_id: int, semester: str, actor: str) -> dict[str, Any]:
    ensure_grade_publication_schema(conn)
    drafts = _list_department_final_drafts(conn, department_id, semester, actor)
    total = _expected_department_courses(conn, department_id, semester)
    ready = sum(1 for d in drafts if d.get("readiness") == "ready")
    if len(drafts) > total:
        total = len(drafts)
    pct = round((ready / total) * 100.0, 1) if total > 0 else 0.0

    cur = conn.cursor()
    batch = cur.execute(
        """
        SELECT * FROM department_final_grade_batches
        WHERE department_id = ? AND semester = ?
        LIMIT 1
        """,
        (int(department_id), semester),
    ).fetchone()
    batch_row = _row_dict(batch) if batch else {}

    return {
        "department_id": int(department_id),
        "semester": semester,
        "completion_percent": pct,
        "total_courses": total,
        "ready_courses": ready,
        "drafts": drafts,
        "batch": batch_row,
        "can_submit_to_dean": pct >= 100.0 and (batch_row.get("status") or "collecting") in (
            "collecting",
            "returned_to_hod",
        ),
    }


def _hod_department_id(conn, actor: str) -> int | None:
    mode, dep_id = resolve_users_list_scope(conn, actor)
    if dep_id is not None:
        return int(dep_id)
    try:
        row = conn.cursor().execute(
            "SELECT department_id FROM users WHERE lower(username)=lower(?) LIMIT 1",
            (actor,),
        ).fetchone()
        if row and row[0] not in (None, ""):
            return int(row[0])
    except Exception:
        pass
    return None


def submit_department_batch_to_dean(
    conn, *, department_id: int, semester: str, actor: str, hod_note: str = ""
) -> dict[str, Any]:
    summary = build_hod_final_batch_summary(conn, department_id=department_id, semester=semester, actor=actor)
    if summary["completion_percent"] < 100.0:
        return {"ok": False, "message": "يجب إكمال 100% من مقررات القسم قبل الإرسال للعميد", "code": 400}

    cur = conn.cursor()
    now = _now_iso()
    ready_ids = [int(d["id"]) for d in summary["drafts"] if d.get("readiness") == "ready"]
    if not ready_ids:
        return {"ok": False, "message": "لا توجد مسودات جاهزة", "code": 400}

    if is_postgresql():
        cur.execute(
            """
            INSERT INTO department_final_grade_batches
                (department_id, semester, status, completion_percent, total_courses,
                 ready_courses, submitted_at, submitted_by, hod_note, updated_at)
            VALUES (?, ?, 'submitted_to_dean', ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (department_id, semester)
            DO UPDATE SET
                status = 'submitted_to_dean',
                completion_percent = EXCLUDED.completion_percent,
                total_courses = EXCLUDED.total_courses,
                ready_courses = EXCLUDED.ready_courses,
                submitted_at = EXCLUDED.submitted_at,
                submitted_by = EXCLUDED.submitted_by,
                hod_note = EXCLUDED.hod_note,
                updated_at = EXCLUDED.updated_at,
                dean_note = ''
            """,
            (
                int(department_id),
                semester,
                summary["completion_percent"],
                summary["total_courses"],
                summary["ready_courses"],
                now,
                actor,
                (hod_note or "").strip(),
                now,
            ),
        )
    else:
        cur.execute(
            """
            INSERT INTO department_final_grade_batches
                (department_id, semester, status, completion_percent, total_courses,
                 ready_courses, submitted_at, submitted_by, hod_note, updated_at)
            VALUES (?, ?, 'submitted_to_dean', ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(department_id, semester)
            DO UPDATE SET
                status = 'submitted_to_dean',
                completion_percent = excluded.completion_percent,
                total_courses = excluded.total_courses,
                ready_courses = excluded.ready_courses,
                submitted_at = excluded.submitted_at,
                submitted_by = excluded.submitted_by,
                hod_note = excluded.hod_note,
                updated_at = excluded.updated_at,
                dean_note = ''
            """,
            (
                int(department_id),
                semester,
                summary["completion_percent"],
                summary["total_courses"],
                summary["ready_courses"],
                now,
                actor,
                (hod_note or "").strip(),
                now,
            ),
        )
    row = cur.execute(
        "SELECT id FROM department_final_grade_batches WHERE department_id=? AND semester=?",
        (int(department_id), semester),
    ).fetchone()
    batch_id = int(row[0])

    ph = ",".join("?" for _ in ready_ids)
    cur.execute(
        f"UPDATE grade_drafts SET batch_id = ?, updated_at = ? WHERE id IN ({ph})",
        [batch_id, now, *ready_ids],
    )
    conn.commit()
    return {"ok": True, "batch_id": batch_id, "draft_count": len(ready_ids)}


def list_dean_batches(conn, semester: str | None = None) -> list[dict]:
    ensure_grade_publication_schema(conn)
    cur = conn.cursor()
    sem = (semester or "").strip() or _semester_label(conn)
    rows = cur.execute(
        """
        SELECT b.*, COALESCE(d.name_ar, '') AS department_name
        FROM department_final_grade_batches b
        LEFT JOIN departments d ON d.id = b.department_id
        WHERE b.semester = ?
        ORDER BY
            CASE b.status
                WHEN 'submitted_to_dean' THEN 0
                WHEN 'returned_to_hod' THEN 1
                WHEN 'published' THEN 2
                ELSE 3
            END,
            b.submitted_at DESC
        """,
        (sem,),
    ).fetchall()
    return [_row_dict(r) for r in rows or []]


def get_dean_batch_detail(conn, batch_id: int) -> dict[str, Any] | None:
    ensure_grade_publication_schema(conn)
    cur = conn.cursor()
    b = cur.execute(
        """
        SELECT b.*, COALESCE(d.name_ar, '') AS department_name
        FROM department_final_grade_batches b
        LEFT JOIN departments d ON d.id = b.department_id
        WHERE b.id = ?
        """,
        (int(batch_id),),
    ).fetchone()
    if not b:
        return None
    batch = _row_dict(b)
    drafts = cur.execute(
        """
        SELECT d.id, d.course_name, d.section_id, d.status,
               COALESCE(d.draft_phase, 'combined') AS draft_phase,
               COALESCE(i.name, '') AS instructor_name,
               d.hod_final_approved_at
        FROM grade_drafts d
        LEFT JOIN instructors i ON i.id = d.instructor_id
        WHERE d.batch_id = ?
        ORDER BY d.course_name
        """,
        (int(batch_id),),
    ).fetchall()
    batch["drafts"] = [_row_dict(r) for r in drafts or []]
    return batch


def dean_publish_batch(conn, batch_id: int, *, actor: str) -> dict[str, Any]:
    if _role() not in _DEAN_PUBLISH_ROLES:
        return {"ok": False, "message": "غير مصرح — النشر النهائي للعميد ومدير النظام فقط", "code": 403}
    detail = get_dean_batch_detail(conn, batch_id)
    if not detail:
        return {"ok": False, "message": "الحزمة غير موجودة", "code": 404}
    if (detail.get("status") or "") not in ("submitted_to_dean",):
        return {"ok": False, "message": "الحزمة ليست بانتظار النشر", "code": 400}

    now = _now_iso()
    total_published = 0
    for d in detail.get("drafts") or []:
        total_published += publish_final_draft_to_grades(conn, int(d["id"]), actor=actor)

    cur = conn.cursor()
    cur.execute(
        """
        UPDATE department_final_grade_batches
        SET status = 'published', published_at = ?, published_by = ?, updated_at = ?
        WHERE id = ?
        """,
        (now, actor, now, int(batch_id)),
    )
    conn.commit()
    return {"ok": True, "batch_id": int(batch_id), "published_grades": total_published}


def dean_return_batch(conn, batch_id: int, *, actor: str, note: str = "") -> dict[str, Any]:
    if _role() not in _DEAN_PUBLISH_ROLES:
        return {"ok": False, "message": "غير مصرح", "code": 403}
    cur = conn.cursor()
    b = cur.execute(
        "SELECT status FROM department_final_grade_batches WHERE id = ?",
        (int(batch_id),),
    ).fetchone()
    if not b:
        return {"ok": False, "message": "الحزمة غير موجودة", "code": 404}
    if (b[0] or "") != "submitted_to_dean":
        return {"ok": False, "message": "لا يمكن الإرجاع في هذه الحالة", "code": 400}
    now = _now_iso()
    cur.execute(
        """
        UPDATE department_final_grade_batches
        SET status = 'returned_to_hod', dean_note = ?, updated_at = ?
        WHERE id = ?
        """,
        ((note or "").strip(), now, int(batch_id)),
    )
    conn.commit()
    return {"ok": True, "batch_id": int(batch_id)}


def student_term_grade_details(conn, student_id: str, semester: str | None = None) -> list[dict]:
    """درجات الفصل الحالي المنشورة للطالب (جزئي/نهائي)."""
    ensure_grade_publication_schema(conn)
    sem = (semester or "").strip() or _semester_label(conn)
    if not sem:
        return []
    cur = conn.cursor()
    if not table_exists(conn, "student_published_grades"):
        return []
    rows = cur.execute(
        """
        SELECT course_name, coursework, midterm, partial_total, final_exam, total,
               visibility, published_at
        FROM student_published_grades
        WHERE student_id = ? AND semester = ?
        ORDER BY course_name, visibility
        """,
        (student_id, sem),
    ).fetchall()
    by_course: dict[str, dict] = {}
    for r in rows or []:
        row = _row_dict(r)
        cn = (row.get("course_name") or "").strip()
        if not cn:
            continue
        entry = by_course.setdefault(
            cn,
            {
                "course_name": cn,
                "partial": None,
                "final": None,
            },
        )
        vis = (row.get("visibility") or "").strip().lower()
        if vis == "partial":
            entry["partial"] = {
                "coursework": row.get("coursework"),
                "midterm": row.get("midterm"),
                "partial_total": row.get("partial_total"),
                "published_at": row.get("published_at"),
            }
        elif vis == "final":
            entry["final"] = {
                "coursework": row.get("coursework"),
                "midterm": row.get("midterm"),
                "partial_total": row.get("partial_total"),
                "final_exam": row.get("final_exam"),
                "total": row.get("total"),
                "published_at": row.get("published_at"),
            }
    return list(by_course.values())


def filter_transcript_for_student_visibility(
    conn,
    student_id: str,
    transcript: dict,
    *,
    current_semester: str,
) -> dict:
    """
    يخفي درجات الفصل الحالي من grades حتى يُنشر النهائي.
    يُبقي الفصول السابقة كما هي.
    """
    if not current_semester or current_semester not in transcript:
        return transcript
    ensure_grade_publication_schema(conn)
    cur = conn.cursor()
    if not table_exists(conn, "student_published_grades"):
        return transcript
    finals = {
        r[0]
        for r in cur.execute(
            """
            SELECT course_name FROM student_published_grades
            WHERE student_id = ? AND semester = ? AND visibility = 'final'
            """,
            (student_id, current_semester),
        ).fetchall()
        or []
    }
    courses = transcript.get(current_semester) or []
    filtered = []
    for c in courses:
        cn = (c.get("course_name") or "").strip()
        if cn in finals:
            filtered.append(c)
        else:
            filtered.append(
                {
                    **c,
                    "grade": None,
                    "grade_pending_final": True,
                }
            )
    out = dict(transcript)
    out[current_semester] = filtered
    return out
