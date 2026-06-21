"""
تقرير تنفيذ المقرر (baseline مفردات + تقارير جزئي/نهائي) وبوابة مسودات الدرجات.
"""
from __future__ import annotations

import datetime
from typing import Any

from flask import Blueprint, jsonify, request, session

from backend.core.auth import login_required, role_required, get_admin_department_scope_id
from backend.database.database import fetch_table_columns, is_postgresql
from backend.services.utilities import get_connection, get_current_term

course_delivery_bp = Blueprint("course_delivery", __name__)

PHASE_PARTIAL = "partial"
PHASE_FINAL = "final"
BASELINE_DRAFT = "draft"
BASELINE_PENDING = "pending_hod"
BASELINE_APPROVED = "approved"
BASELINE_SUPERSEDED = "superseded"


def _now_iso() -> str:
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _current_semester_label(conn) -> str:
    tname, tyear = get_current_term(conn=conn)
    return f"{(tname or '').strip()} {(tyear or '').strip()}".strip()


def _row_dict(row) -> dict:
    if row is None:
        return {}
    if isinstance(row, dict):
        return row
    return dict(row)


def _is_hod_or_admin() -> bool:
    role = (session.get("user_role") or "").strip()
    return role in ("head_of_department", "admin_main", "admin")


def ensure_course_delivery_schema(conn) -> None:
    """إنشاء جداول تقرير التنفيذ (PostgreSQL / SQLite)."""
    cur = conn.cursor()
    stmts = [
        """
        CREATE TABLE IF NOT EXISTS course_syllabus_baselines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_name TEXT NOT NULL,
            version INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'draft',
            semester_label TEXT DEFAULT '',
            created_by_instructor_id INTEGER,
            created_by TEXT DEFAULT '',
            approved_by TEXT,
            approved_at TEXT,
            hod_note TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS course_syllabus_topics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            baseline_id INTEGER NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 0,
            topic_title TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY (baseline_id) REFERENCES course_syllabus_baselines(id) ON DELETE CASCADE
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS grade_gate_policies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            department_id INTEGER,
            semester_label TEXT DEFAULT '',
            partial_min_pct REAL NOT NULL DEFAULT 50,
            final_min_pct REAL NOT NULL DEFAULT 80,
            updated_by TEXT DEFAULT '',
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (department_id, semester_label)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS course_delivery_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            teaching_group_id INTEGER NOT NULL,
            semester TEXT NOT NULL,
            course_name TEXT NOT NULL,
            instructor_id INTEGER NOT NULL,
            baseline_id INTEGER NOT NULL,
            phase TEXT NOT NULL,
            overall_pct REAL,
            below_threshold_reason TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'draft',
            submitted_at TEXT,
            reviewed_by TEXT,
            reviewed_at TEXT,
            review_note TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (teaching_group_id, semester, phase)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS course_delivery_report_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_id INTEGER NOT NULL,
            topic_id INTEGER NOT NULL,
            completion_pct REAL,
            incomplete_reason TEXT DEFAULT '',
            UNIQUE (report_id, topic_id),
            FOREIGN KEY (report_id) REFERENCES course_delivery_reports(id) ON DELETE CASCADE
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS course_delivery_extra_topics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            reason TEXT NOT NULL DEFAULT '',
            FOREIGN KEY (report_id) REFERENCES course_delivery_reports(id) ON DELETE CASCADE
        )
        """,
    ]
    if is_postgresql():
        stmts = [
            s.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY")
            .replace("INTEGER NOT NULL", "BIGINT NOT NULL")
            .replace("INTEGER,", "BIGINT,")
            .replace("INTEGER ", "BIGINT ")
            for s in stmts
        ]
        stmts[0] = stmts[0].replace("BIGINT PRIMARY KEY", "BIGSERIAL PRIMARY KEY", 1)
        stmts[1] = stmts[1].replace("BIGINT PRIMARY KEY", "BIGSERIAL PRIMARY KEY", 1)
        stmts[2] = stmts[2].replace("BIGINT PRIMARY KEY", "BIGSERIAL PRIMARY KEY", 1)
        stmts[3] = stmts[3].replace("BIGINT PRIMARY KEY", "BIGSERIAL PRIMARY KEY", 1)
        stmts[4] = stmts[4].replace("BIGINT PRIMARY KEY", "BIGSERIAL PRIMARY KEY", 1)
        stmts[5] = stmts[5].replace("BIGINT PRIMARY KEY", "BIGSERIAL PRIMARY KEY", 1)
    for stmt in stmts:
        try:
            cur.execute(stmt)
        except Exception:
            pass
    gd_cols = {c.lower() for c in fetch_table_columns(conn, "grade_drafts")}
    if "draft_phase" not in gd_cols:
        try:
            cur.execute(
                "ALTER TABLE grade_drafts ADD COLUMN draft_phase TEXT NOT NULL DEFAULT 'combined'"
            )
        except Exception:
            pass
    _ensure_grade_drafts_phase_unique(conn)
    conn.commit()


def _ensure_grade_drafts_phase_unique(conn) -> None:
    """يسمح بمسودتي جزئي/نهائي لنفس المقرر (PostgreSQL)."""
    if not is_postgresql():
        return
    cur = conn.cursor()
    try:
        cur.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_grade_drafts_phase
            ON grade_drafts (
                semester, course_name, instructor_id,
                COALESCE(section_id, -1),
                COALESCE(teaching_group_id, -1),
                COALESCE(draft_phase, 'combined')
            )
            """
        )
    except Exception:
        pass
    for cname in (
        "grade_drafts_semester_course_name_instructor_id_section_id_key",
        "grade_drafts_semester_course_name_instructor_id_key",
    ):
        try:
            cur.execute(f"ALTER TABLE grade_drafts DROP CONSTRAINT IF EXISTS {cname}")
        except Exception:
            pass
    conn.commit()


def get_gate_policy(conn, department_id: int | None, semester: str) -> dict:
    ensure_course_delivery_schema(conn)
    cur = conn.cursor()
    row = None
    if department_id:
        row = cur.execute(
            """
            SELECT partial_min_pct, final_min_pct FROM grade_gate_policies
            WHERE department_id = ? AND semester_label = ?
            LIMIT 1
            """,
            (int(department_id), semester),
        ).fetchone()
    if not row:
        row = cur.execute(
            """
            SELECT partial_min_pct, final_min_pct FROM grade_gate_policies
            WHERE department_id IS NULL AND semester_label = ?
            LIMIT 1
            """,
            (semester,),
        ).fetchone()
    if not row:
        return {"partial_min_pct": 50.0, "final_min_pct": 80.0}
    d = _row_dict(row)
    return {
        "partial_min_pct": float(d.get("partial_min_pct") or 50),
        "final_min_pct": float(d.get("final_min_pct") or 80),
    }


def get_active_baseline(conn, course_name: str) -> dict | None:
    ensure_course_delivery_schema(conn)
    cur = conn.cursor()
    row = cur.execute(
        """
        SELECT * FROM course_syllabus_baselines
        WHERE course_name = ? AND status = ?
        ORDER BY version DESC, id DESC
        LIMIT 1
        """,
        (course_name.strip(), BASELINE_APPROVED),
    ).fetchone()
    if not row:
        return None
    bl = _row_dict(row)
    topics = cur.execute(
        """
        SELECT id, sort_order, topic_title, is_active
        FROM course_syllabus_topics
        WHERE baseline_id = ? AND is_active = 1
        ORDER BY sort_order, id
        """,
        (int(bl["id"]),),
    ).fetchall()
    bl["topics"] = [_row_dict(t) for t in topics or []]
    return bl


def get_baseline_with_topics(conn, baseline_id: int) -> dict | None:
    cur = conn.cursor()
    row = cur.execute(
        "SELECT * FROM course_syllabus_baselines WHERE id = ?",
        (int(baseline_id),),
    ).fetchone()
    if not row:
        return None
    bl = _row_dict(row)
    topics = cur.execute(
        """
        SELECT id, sort_order, topic_title, is_active
        FROM course_syllabus_topics
        WHERE baseline_id = ?
        ORDER BY sort_order, id
        """,
        (int(baseline_id),),
    ).fetchall()
    bl["topics"] = [_row_dict(t) for t in topics or []]
    return bl


def _compute_overall_pct(items: list[dict]) -> float:
    pcts = [float(x.get("completion_pct") or 0) for x in items if x.get("completion_pct") is not None]
    if not pcts:
        return 0.0
    return round(sum(pcts) / len(pcts), 1)


def get_delivery_report(conn, teaching_group_id: int, semester: str, phase: str) -> dict | None:
    ensure_course_delivery_schema(conn)
    cur = conn.cursor()
    row = cur.execute(
        """
        SELECT * FROM course_delivery_reports
        WHERE teaching_group_id = ? AND semester = ? AND phase = ?
        LIMIT 1
        """,
        (int(teaching_group_id), semester, phase),
    ).fetchone()
    if not row:
        return None
    rep = _row_dict(row)
    items = cur.execute(
        """
        SELECT i.*, t.topic_title, t.sort_order
        FROM course_delivery_report_items i
        JOIN course_syllabus_topics t ON t.id = i.topic_id
        WHERE i.report_id = ?
        ORDER BY t.sort_order, t.id
        """,
        (int(rep["id"]),),
    ).fetchall()
    rep["items"] = [_row_dict(i) for i in items or []]
    extras = cur.execute(
        "SELECT id, title, reason FROM course_delivery_extra_topics WHERE report_id = ?",
        (int(rep["id"]),),
    ).fetchall()
    rep["extra_topics"] = [_row_dict(e) for e in extras or []]
    return rep


def _report_unlocks_draft(rep: dict | None, min_pct: float) -> bool:
    if not rep:
        return False
    st = str(rep.get("status") or "")
    if st in ("auto_approved", "gate_approved", "submitted"):
        ov = float(rep.get("overall_pct") or 0)
        if ov >= min_pct:
            return True
    if st == "gate_approved":
        return True
    return False


def _report_submitted(rep: dict | None) -> bool:
    """هل أُرسل التقرير (بما في ذلك بانتظار موافقة رئيس القسم)؟"""
    if not rep:
        return False
    return str(rep.get("status") or "") in (
        "submitted",
        "auto_approved",
        "gate_pending",
        "gate_approved",
        "gate_rejected",
    )


def _phase_summary(rep: dict | None) -> dict:
    if not rep:
        return {"overall_pct": None, "status": None, "submitted": False}
    return {
        "overall_pct": rep.get("overall_pct"),
        "status": rep.get("status"),
        "submitted": _report_submitted(rep),
    }


def _grade_draft_phase_status(
    conn,
    *,
    teaching_group_id: int,
    semester: str,
    course_name: str,
    instructor_id: int,
    phase: str,
) -> str | None:
    """آخر حالة لمسودة درجات (جزئي/نهائي) لمجموعة تدريس."""
    ensure_course_delivery_schema(conn)
    cur = conn.cursor()
    gd_cols = {c.lower() for c in fetch_table_columns(conn, "grade_drafts")}
    if "draft_phase" not in gd_cols or "teaching_group_id" not in gd_cols:
        return None
    row = cur.execute(
        """
        SELECT status FROM grade_drafts
        WHERE teaching_group_id = ? AND semester = ? AND course_name = ?
          AND instructor_id = ? AND COALESCE(draft_phase, 'combined') = ?
        ORDER BY id DESC LIMIT 1
        """,
        (int(teaching_group_id), (semester or "").strip(), (course_name or "").strip(), int(instructor_id), phase),
    ).fetchone()
    if not row:
        return None
    return str(row["status"] if hasattr(row, "keys") else row[0] or "").strip() or None


def _section_ids_from_row(row: dict) -> list[int]:
    ids: list[int] = []
    for raw in row.get("section_ids") or []:
        try:
            sid = int(raw)
        except (TypeError, ValueError):
            continue
        if sid > 0 and sid not in ids:
            ids.append(sid)
    if not ids and row.get("section_id"):
        try:
            sid = int(row["section_id"])
            if sid > 0:
                ids.append(sid)
        except (TypeError, ValueError):
            pass
    return ids


def _has_weekly_plan(conn, *, instructor_id: int, section_ids: list[int]) -> bool:
    if not section_ids:
        return False
    cur = conn.cursor()
    ph = ",".join(["?"] * len(section_ids))
    row = cur.execute(
        f"""
        SELECT COUNT(*) FROM faculty_course_plans
        WHERE instructor_id = ? AND section_id IN ({ph})
        """,
        (int(instructor_id), *section_ids),
    ).fetchone()
    if not row:
        return False
    return int(row[0] if not hasattr(row, "keys") else list(row)[0]) > 0


def derive_course_mgmt_axis(
    conn,
    *,
    course_name: str,
    instructor_id: int,
    section_ids: list[int],
) -> dict[str, Any]:
    """8.7.3 — إعداد المقرر: مفردات معتمدة + خطة أسبوعية."""
    cn = (course_name or "").strip()
    if not cn:
        return {"status": None, "auto": False, "detail_ar": ""}
    ensure_course_delivery_schema(conn)
    baseline = get_active_baseline(conn, cn)
    baseline_ok = bool(baseline and baseline.get("topics"))
    plan_ok = _has_weekly_plan(conn, instructor_id=int(instructor_id), section_ids=section_ids)
    if baseline_ok and plan_ok:
        return {
            "status": "done",
            "auto": True,
            "detail_ar": "قائمة المفردات معتمدة والخطة الأسبوعية مُدخلة",
            "milestones": {"baseline_ok": True, "weekly_plan": True},
        }
    if not baseline_ok:
        detail = "أكمل واعتمد قائمة المفردات من تقرير المقرر"
    elif not plan_ok:
        detail = "قائمة المفردات معتمدة — أضف خطة أسبوعية في مقرراتي"
    else:
        detail = "أكمل إعداد المقرر"
    return {
        "status": "pending",
        "auto": True,
        "detail_ar": detail,
        "milestones": {"baseline_ok": baseline_ok, "weekly_plan": plan_ok},
    }


def derive_teaching_content_axis(
    conn,
    *,
    teaching_group_id: int | None,
    course_name: str,
    semester: str,
) -> dict[str, Any]:
    """8.7.3 — تنفيذ المحتوى: تقرير جزئي ثم نهائي."""
    if not teaching_group_id:
        return {"status": None, "auto": False, "detail_ar": ""}
    ensure_course_delivery_schema(conn)
    tgid = int(teaching_group_id)
    sem = (semester or "").strip()
    partial_rep = get_delivery_report(conn, tgid, sem, PHASE_PARTIAL)
    final_rep = get_delivery_report(conn, tgid, sem, PHASE_FINAL)
    partial_ok = _report_submitted(partial_rep)
    final_ok = _report_submitted(final_rep)
    milestones = {"partial_report": partial_ok, "final_report": final_ok}
    if final_ok:
        return {
            "status": "done",
            "auto": True,
            "detail_ar": "تقريرا الجزئي والنهائي مُرسلان",
            "milestones": milestones,
        }
    if partial_ok:
        return {
            "status": "pending",
            "auto": True,
            "detail_ar": "التقرير الجزئي مُرسل — أكمل تقرير النهائي",
            "milestones": milestones,
        }
    return {
        "status": "pending",
        "auto": True,
        "detail_ar": "بانتظار إرسال تقرير الجزئي من صفحة تقرير المقرر",
        "milestones": milestones,
    }


def derive_documentation_axis(
    conn,
    *,
    teaching_group_id: int | None,
    course_name: str,
    semester: str,
) -> dict[str, Any]:
    """8.8 — التوثيق والجودة: تقدم تقرير تنفيذ المقرر (3 نقاط تحقق)."""
    if not teaching_group_id:
        return {"status": None, "auto": False, "detail_ar": ""}
    ds = delivery_summary_for_ui(
        conn,
        teaching_group_id=int(teaching_group_id),
        course_name=(course_name or "").strip(),
        semester=(semester or "").strip(),
    )
    if not ds.get("available"):
        return {"status": "pending", "auto": True, "detail_ar": "تقرير التنفيذ غير مرتبط بمجموعة تدريس"}
    done = int(ds.get("checkpoints_done") or 0)
    total = int(ds.get("checkpoints_total") or 3)
    milestones = {
        "baseline_ok": bool(ds.get("baseline_ok")),
        "partial_report": bool((ds.get("partial") or {}).get("submitted")),
        "final_report": bool((ds.get("final") or {}).get("submitted")),
    }
    if done >= total and total > 0:
        return {
            "status": "done",
            "auto": True,
            "detail_ar": "دورة التوثيق مكتملة (مفردات + جزئي + نهائي)",
            "milestones": milestones,
        }
    if done > 0:
        return {
            "status": "pending",
            "auto": True,
            "detail_ar": f"تقدم التوثيق {done}/{total} — أكمل تقرير تنفيذ المقرر",
            "milestones": milestones,
        }
    return {
        "status": "pending",
        "auto": True,
        "detail_ar": "ابدأ من قائمة المفردات في تقرير المقرر",
        "milestones": milestones,
    }


def _merge_auto_axis(row: dict, axis_key: str, derived: dict[str, Any]) -> None:
    if not derived.get("auto") or derived.get("status") is None:
        return
    row.setdefault("axes", {})[axis_key] = derived["status"]
    row.setdefault("axes_meta", {})[axis_key] = {
        "auto": True,
        "detail_ar": derived.get("detail_ar") or "",
        "milestones": derived.get("milestones") or {},
    }


def derive_assessment_axis(
    conn,
    *,
    teaching_group_id: int | None,
    course_name: str,
    semester: str,
    instructor_id: int,
) -> dict[str, Any]:
    """
    8.7.2 — حالة محور «الدرجات والاختبارات» من تقرير التنفيذ ومسودات الدرجات.
    يُرجع status=None عندما لا تتوفر مجموعة تدريس (يبقى التحديث اليدوي).
    """
    if not teaching_group_id:
        return {"status": None, "auto": False, "detail_ar": ""}
    ensure_course_delivery_schema(conn)
    tgid = int(teaching_group_id)
    sem = (semester or "").strip()
    cn = (course_name or "").strip()
    iid = int(instructor_id)

    partial_rep = get_delivery_report(conn, tgid, sem, PHASE_PARTIAL)
    final_rep = get_delivery_report(conn, tgid, sem, PHASE_FINAL)
    partial_draft_st = _grade_draft_phase_status(
        conn, teaching_group_id=tgid, semester=sem, course_name=cn, instructor_id=iid, phase=PHASE_PARTIAL
    )
    final_draft_st = _grade_draft_phase_status(
        conn, teaching_group_id=tgid, semester=sem, course_name=cn, instructor_id=iid, phase=PHASE_FINAL
    )

    partial_report_ok = _report_submitted(partial_rep)
    final_report_ok = _report_submitted(final_rep)
    milestones = {
        "partial_report": partial_report_ok,
        "partial_draft_approved": partial_draft_st == "Approved",
        "partial_draft_submitted": partial_draft_st in ("Submitted", "Approved"),
        "final_report": final_report_ok,
        "final_draft_approved": final_draft_st == "Approved",
        "final_draft_submitted": final_draft_st in ("Submitted", "Approved"),
    }

    if final_draft_st == "Approved":
        status = "done"
        detail = "مسودة النهائي معتمدة — دورة الدرجات مكتملة"
    elif partial_draft_st == "Approved":
        status = "done"
        detail = "مسودة الجزئي معتمدة — أكمل تقرير ومسودة النهائي لاحقاً"
    else:
        status = "pending"
        if partial_draft_st == "Submitted":
            detail = "مسودة الجزئي مرسلة — بانتظار اعتماد رئيس القسم"
        elif partial_draft_st in ("Draft", "Rejected"):
            detail = "أكمل وأرسل مسودة الجزئي"
        elif partial_report_ok:
            detail = "التقرير الجزئي مُرسل — ابدأ مسودة الجزئي"
        elif partial_rep:
            detail = "أكمل وأرسل تقرير الجزئي ثم مسودة الدرجات"
        else:
            detail = "بانتظار تقرير الجزئي ومسودات الدرجات"

    return {
        "status": status,
        "auto": True,
        "detail_ar": detail,
        "milestones": milestones,
    }


def apply_auto_axes_to_portal_row(
    conn,
    row: dict,
    *,
    semester: str,
    instructor_id: int,
) -> None:
    """دمج المحاور المشتقة تلقائياً في صف مقرراتي (8.7.2–8.7.3)."""
    tgid = int(row.get("teaching_group_id") or 0) or None
    cn = (row.get("course_name") or "").strip()
    sem = (semester or "").strip()
    iid = int(instructor_id)
    section_ids = _section_ids_from_row(row)

    _merge_auto_axis(
        row,
        "course_mgmt",
        derive_course_mgmt_axis(conn, course_name=cn, instructor_id=iid, section_ids=section_ids),
    )
    _merge_auto_axis(
        row,
        "teaching_content",
        derive_teaching_content_axis(conn, teaching_group_id=tgid, course_name=cn, semester=sem),
    )
    _merge_auto_axis(
        row,
        "assessment",
        derive_assessment_axis(
            conn,
            teaching_group_id=tgid,
            course_name=cn,
            semester=sem,
            instructor_id=iid,
        ),
    )
    _merge_auto_axis(
        row,
        "documentation_quality",
        derive_documentation_axis(conn, teaching_group_id=tgid, course_name=cn, semester=sem),
    )


def delivery_summary_for_ui(
    conn,
    *,
    teaching_group_id: int | None,
    course_name: str,
    semester: str,
) -> dict[str, Any]:
    """ملخص تقرير التنفيذ لعرضه في مقرراتي (8.7)."""
    if not teaching_group_id:
        return {
            "available": False,
            "message": "تقرير التنفيذ متاح لمجموعات التدريس — راجع المسؤول للربط",
            "checkpoints_done": 0,
            "checkpoints_total": 0,
        }
    ensure_course_delivery_schema(conn)
    baseline = get_active_baseline(conn, (course_name or "").strip())
    baseline_ok = bool(baseline and baseline.get("topics"))
    partial_rep = get_delivery_report(conn, int(teaching_group_id), semester, PHASE_PARTIAL)
    final_rep = get_delivery_report(conn, int(teaching_group_id), semester, PHASE_FINAL)
    checkpoints_done = 0
    if baseline_ok:
        checkpoints_done += 1
    if _report_submitted(partial_rep):
        checkpoints_done += 1
    if _report_submitted(final_rep):
        checkpoints_done += 1
    return {
        "available": True,
        "teaching_group_id": int(teaching_group_id),
        "baseline_ok": baseline_ok,
        "baseline_status": "approved" if baseline_ok else "missing",
        "partial": _phase_summary(partial_rep),
        "final": _phase_summary(final_rep),
        "checkpoints_done": checkpoints_done,
        "checkpoints_total": 3,
        "survey_url": f"/course_delivery_page?teaching_group_id={int(teaching_group_id)}",
    }


def grade_draft_gate_status(
    conn,
    *,
    teaching_group_id: int,
    semester: str,
    course_name: str,
    department_id: int | None,
    phase: str,
) -> dict[str, Any]:
    """حالة بوابة فتح مسودة جزئي/نهائي."""
    policy = get_gate_policy(conn, department_id, semester)
    min_pct = policy["partial_min_pct"] if phase == PHASE_PARTIAL else policy["final_min_pct"]
    baseline = get_active_baseline(conn, course_name)
    if not baseline or not baseline.get("topics"):
        return {
            "unlocked": False,
            "reason": "لا توجد قائمة مفردات معتمدة — أكمل اعتماد رئيس القسم أولاً",
            "baseline_status": baseline.get("status") if baseline else "missing",
            "partial_min_pct": policy["partial_min_pct"],
            "final_min_pct": policy["final_min_pct"],
        }
    rep = get_delivery_report(conn, teaching_group_id, semester, phase)
    if phase == PHASE_FINAL:
        cur = conn.cursor()
        partial_draft = cur.execute(
            """
            SELECT status FROM grade_drafts
            WHERE teaching_group_id = ? AND semester = ? AND draft_phase = ?
            LIMIT 1
            """,
            (int(teaching_group_id), semester, PHASE_PARTIAL),
        ).fetchone()
        pst = str(_row_dict(partial_draft).get("status") or "")
        if pst != "Approved":
            return {
                "unlocked": False,
                "reason": "يجب اعتماد مسودة الجزئي قبل فتح مسودة النهائي",
                "partial_min_pct": policy["partial_min_pct"],
                "final_min_pct": policy["final_min_pct"],
            }
    unlocked = _report_unlocks_draft(rep, min_pct)
    reason = ""
    if not rep:
        reason = f"أكمل تقرير {'الجزئي' if phase == PHASE_PARTIAL else 'النهائي'} أولاً"
    elif not unlocked:
        if str(rep.get("status") or "") == "gate_pending":
            reason = "بانتظار موافقة رئيس القسم على التبرير (النسبة دون الحد)"
        else:
            reason = f"نسبة الإنجاز {rep.get('overall_pct')}% — أرسل التقرير أو اطلب موافقة رئيس القسم"
    return {
        "unlocked": unlocked,
        "reason": reason,
        "report": rep,
        "baseline_id": int(baseline["id"]),
        "overall_pct": rep.get("overall_pct") if rep else None,
        "report_status": rep.get("status") if rep else None,
        "partial_min_pct": policy["partial_min_pct"],
        "final_min_pct": policy["final_min_pct"],
    }


def sync_partial_grades_to_final(conn, *, partial_draft_id: int) -> int | None:
    """بعد اعتماد مسودة الجزئي: إنشاء/تحديث مسودة النهائي بنفس بنود coursework/midterm."""
    cur = conn.cursor()
    pd = _row_dict(cur.execute("SELECT * FROM grade_drafts WHERE id = ?", (partial_draft_id,)).fetchone())
    if not pd:
        return None
    tgid = int(pd.get("teaching_group_id") or 0)
    semester = pd.get("semester") or ""
    course_name = pd.get("course_name") or ""
    instructor_id = int(pd.get("instructor_id") or 0)
    section_id = pd.get("section_id")
    now = _now_iso()
    existing = cur.execute(
        """
        SELECT id FROM grade_drafts
        WHERE semester = ? AND course_name = ? AND instructor_id = ?
          AND COALESCE(teaching_group_id, 0) = ?
          AND draft_phase = ?
        LIMIT 1
        """,
        (semester, course_name, instructor_id, tgid, PHASE_FINAL),
    ).fetchone()
    if existing:
        final_id = int(_row_dict(existing)["id"])
    else:
        cols = fetch_table_columns(conn, "grade_drafts")
        has_tg = "teaching_group_id" in {c.lower() for c in cols}
        has_dp = "draft_phase" in {c.lower() for c in cols}
        if has_tg and has_dp:
            cur.execute(
                """
                INSERT INTO grade_drafts (
                    semester, course_name, section_id, teaching_group_id, instructor_id,
                    grading_mode, draft_phase, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'Draft', ?, ?)
                """,
                (
                    semester,
                    course_name,
                    section_id,
                    tgid or None,
                    instructor_id,
                    pd.get("grading_mode") or "partial_final",
                    PHASE_FINAL,
                    now,
                    now,
                ),
            )
        else:
            cur.execute(
                """
                INSERT INTO grade_drafts (
                    semester, course_name, section_id, instructor_id,
                    grading_mode, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'Draft', ?, ?)
                """,
                (semester, course_name, section_id, instructor_id, pd.get("grading_mode"), now, now),
            )
        final_id = int(cur.lastrowid or 0)
        if is_postgresql():
            row = cur.execute(
                "SELECT id FROM grade_drafts WHERE semester=? AND course_name=? AND instructor_id=? AND draft_phase=? ORDER BY id DESC LIMIT 1",
                (semester, course_name, instructor_id, PHASE_FINAL),
            ).fetchone()
            final_id = int(_row_dict(row)["id"]) if row else final_id
    partial_items = cur.execute(
        "SELECT * FROM grade_draft_items WHERE draft_id = ?",
        (partial_draft_id,),
    ).fetchall()
    for it in partial_items or []:
        row = _row_dict(it)
        sid = row.get("student_id")
        cur.execute(
            """
            INSERT INTO grade_draft_items (
                draft_id, student_id, coursework, midterm, final_exam,
                absent_midterm, absent_final_exam, partial, final, total, computed_total, updated_at
            ) VALUES (?, ?, ?, ?, NULL, ?, 0, NULL, NULL, NULL, NULL, ?)
            ON CONFLICT(draft_id, student_id) DO UPDATE SET
                coursework = excluded.coursework,
                midterm = excluded.midterm,
                absent_midterm = excluded.absent_midterm,
                updated_at = excluded.updated_at
            """,
            (
                final_id,
                sid,
                row.get("coursework"),
                row.get("midterm"),
                row.get("absent_midterm") or 0,
                now,
            ),
        )
    conn.commit()
    return final_id


# --- API routes ---

@course_delivery_bp.route("/baseline", methods=["GET"])
@login_required
def api_baseline_get():
    course_name = (request.args.get("course_name") or "").strip()
    baseline_id = request.args.get("baseline_id", type=int)
    with get_connection() as conn:
        ensure_course_delivery_schema(conn)
        if baseline_id:
            bl = get_baseline_with_topics(conn, baseline_id)
        elif course_name:
            bl = get_active_baseline(conn, course_name)
            if not bl:
                cur = conn.cursor()
                draft = cur.execute(
                    """
                    SELECT * FROM course_syllabus_baselines
                    WHERE course_name = ? AND status IN (?, ?)
                    ORDER BY id DESC LIMIT 1
                    """,
                    (course_name, BASELINE_DRAFT, BASELINE_PENDING),
                ).fetchone()
                if draft:
                    bl = get_baseline_with_topics(conn, int(_row_dict(draft)["id"]))
        else:
            return jsonify({"status": "error", "message": "course_name or baseline_id required"}), 400
    return jsonify({"status": "ok", "baseline": bl}), 200


@course_delivery_bp.route("/baseline", methods=["POST"])
@role_required("instructor", "head_of_department", "admin_main", "admin", "system_admin", "college_dean", "academic_vice_dean")
def api_baseline_create():
    data = request.get_json(force=True) or {}
    course_name = (data.get("course_name") or "").strip()
    topics = data.get("topics") or []
    revise = bool(data.get("revise"))
    if not course_name:
        return jsonify({"status": "error", "message": "course_name مطلوب"}), 400
    instructor_id = session.get("instructor_id")
    actor = (session.get("user") or "").strip()
    with get_connection() as conn:
        ensure_course_delivery_schema(conn)
        cur = conn.cursor()
        sem = _current_semester_label(conn)
        active = get_active_baseline(conn, course_name)
        if active and not revise and not _is_hod_or_admin():
            return jsonify({
                "status": "error",
                "message": "توجد قائمة مفردات معتمدة — استخدم revise=true لاقتراح تعديل",
                "baseline": active,
            }), 400
        version = 1
        if active:
            version = int(active.get("version") or 1) + 1
        if _is_hod_or_admin() and data.get("direct_approve"):
            status = BASELINE_APPROVED
        else:
            status = BASELINE_DRAFT
        now = _now_iso()
        cur.execute(
            """
            INSERT INTO course_syllabus_baselines (
                course_name, version, status, semester_label,
                created_by_instructor_id, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (course_name, version, status, sem, instructor_id, actor, now, now),
        )
        if is_postgresql():
            bid = int(_row_dict(cur.execute(
                "SELECT id FROM course_syllabus_baselines WHERE course_name=? ORDER BY id DESC LIMIT 1",
                (course_name,),
            ).fetchone())["id"])
        else:
            bid = int(cur.lastrowid or 0)
        if status == BASELINE_APPROVED and active:
            cur.execute(
                "UPDATE course_syllabus_baselines SET status=? WHERE id=? AND status=?",
                (BASELINE_SUPERSEDED, int(active["id"]), BASELINE_APPROVED),
            )
        for i, t in enumerate(topics):
            title = (t.get("topic_title") or t.get("title") or "").strip()
            if not title:
                continue
            cur.execute(
                """
                INSERT INTO course_syllabus_topics (baseline_id, sort_order, topic_title, is_active)
                VALUES (?, ?, ?, 1)
                """,
                (bid, int(t.get("sort_order") or i), title),
            )
        conn.commit()
        bl = get_baseline_with_topics(conn, bid)
    return jsonify({"status": "ok", "baseline": bl}), 200


@course_delivery_bp.route("/baseline/<int:baseline_id>/topics", methods=["PUT"])
@role_required("instructor", "head_of_department", "admin_main", "admin", "system_admin", "college_dean", "academic_vice_dean")
def api_baseline_save_topics(baseline_id: int):
    data = request.get_json(force=True) or {}
    topics = data.get("topics") or []
    with get_connection() as conn:
        ensure_course_delivery_schema(conn)
        bl = get_baseline_with_topics(conn, baseline_id)
        if not bl:
            return jsonify({"status": "error", "message": "baseline not found"}), 404
        st = str(bl.get("status") or "")
        if st == BASELINE_APPROVED and not _is_hod_or_admin():
            return jsonify({"status": "error", "message": "قائمة المفردات معتمدة — اقترح نسخة تعديل جديدة"}), 403
        if st == BASELINE_PENDING and not _is_hod_or_admin():
            return jsonify({"status": "error", "message": "قائمة المفردات بانتظار اعتماد رئيس القسم"}), 400
        cur = conn.cursor()
        cur.execute("DELETE FROM course_syllabus_topics WHERE baseline_id = ?", (baseline_id,))
        for i, t in enumerate(topics):
            title = (t.get("topic_title") or t.get("title") or "").strip()
            if not title:
                continue
            cur.execute(
                """
                INSERT INTO course_syllabus_topics (baseline_id, sort_order, topic_title, is_active)
                VALUES (?, ?, ?, ?)
                """,
                (baseline_id, int(t.get("sort_order") or i), title, 1 if t.get("is_active", True) else 0),
            )
        cur.execute(
            "UPDATE course_syllabus_baselines SET updated_at=? WHERE id=?",
            (_now_iso(), baseline_id),
        )
        conn.commit()
        bl = get_baseline_with_topics(conn, baseline_id)
    return jsonify({"status": "ok", "baseline": bl}), 200


@course_delivery_bp.route("/baseline/<int:baseline_id>/submit", methods=["POST"])
@role_required("instructor", "head_of_department")
def api_baseline_submit(baseline_id: int):
    with get_connection() as conn:
        ensure_course_delivery_schema(conn)
        bl = get_baseline_with_topics(conn, baseline_id)
        if not bl:
            return jsonify({"status": "error", "message": "not found"}), 404
        if not bl.get("topics"):
            return jsonify({"status": "error", "message": "أضف مفردات أولاً"}), 400
        if str(bl.get("status")) not in (BASELINE_DRAFT,):
            return jsonify({"status": "error", "message": "لا يمكن الإرسال من هذه الحالة"}), 400
        conn.cursor().execute(
            "UPDATE course_syllabus_baselines SET status=?, updated_at=? WHERE id=?",
            (BASELINE_PENDING, _now_iso(), baseline_id),
        )
        conn.commit()
        from backend.services.course_workflow import notify_baseline_submitted

        notify_baseline_submitted(conn, course_name=str(bl.get("course_name") or ""), baseline_id=baseline_id)
    return jsonify({"status": "ok"}), 200


@course_delivery_bp.route("/baseline/<int:baseline_id>/review", methods=["POST"])
@role_required("head_of_department", "admin_main", "admin", "system_admin", "college_dean", "academic_vice_dean")
def api_baseline_review(baseline_id: int):
    data = request.get_json(force=True) or {}
    action = (data.get("action") or "").strip().lower()
    note = (data.get("note") or "").strip()
    actor = (session.get("user") or "").strip()
    now = _now_iso()
    with get_connection() as conn:
        ensure_course_delivery_schema(conn)
        bl = get_baseline_with_topics(conn, baseline_id)
        if not bl:
            return jsonify({"status": "error", "message": "not found"}), 404
        cur = conn.cursor()
        if action == "approve":
            cur.execute(
                """
                UPDATE course_syllabus_baselines SET status=?
                WHERE course_name=? AND status=? AND id<>?
                """,
                (BASELINE_SUPERSEDED, bl["course_name"], BASELINE_APPROVED, baseline_id),
            )
            cur.execute(
                """
                UPDATE course_syllabus_baselines
                SET status=?, approved_by=?, approved_at=?, hod_note=?, updated_at=?
                WHERE id=?
                """,
                (BASELINE_APPROVED, actor, now, note, now, baseline_id),
            )
        elif action == "reject":
            cur.execute(
                """
                UPDATE course_syllabus_baselines
                SET status=?, hod_note=?, updated_at=?
                WHERE id=?
                """,
                (BASELINE_DRAFT, note, now, baseline_id),
            )
        else:
            return jsonify({"status": "error", "message": "action يجب approve أو reject"}), 400
        conn.commit()
        bl = get_baseline_with_topics(conn, baseline_id)
        from backend.services.course_workflow import notify_baseline_reviewed

        notify_baseline_reviewed(
            conn,
            course_name=str(bl.get("course_name") or ""),
            action=action,
            created_by=str(bl.get("created_by") or "").strip() or None,
            instructor_id=int(bl.get("created_by_instructor_id") or 0) or None,
        )
    return jsonify({"status": "ok", "baseline": bl}), 200


@course_delivery_bp.route("/report", methods=["GET"])
@login_required
def api_report_get():
    tgid = request.args.get("teaching_group_id", type=int)
    phase = (request.args.get("phase") or PHASE_PARTIAL).strip()
    if not tgid:
        return jsonify({"status": "error", "message": "teaching_group_id مطلوب"}), 400
    with get_connection() as conn:
        sem = _current_semester_label(conn)
        rep = get_delivery_report(conn, tgid, sem, phase)
        baseline = None
        if rep:
            baseline = get_baseline_with_topics(conn, int(rep["baseline_id"]))
        else:
            from backend.services import teaching_groups as tg

            g = tg.get_teaching_group(conn, tgid)
            if g:
                baseline = get_active_baseline(conn, g.get("course_name") or "")
    return jsonify({"status": "ok", "report": rep, "baseline": baseline, "semester": sem}), 200


@course_delivery_bp.route("/report", methods=["POST"])
@role_required("instructor", "head_of_department")
def api_report_save():
    data = request.get_json(force=True) or {}
    tgid = int(data.get("teaching_group_id") or 0)
    phase = (data.get("phase") or PHASE_PARTIAL).strip()
    items = data.get("items") or []
    extra_topics = data.get("extra_topics") or []
    if not tgid:
        return jsonify({"status": "error", "message": "teaching_group_id مطلوب"}), 400
    instructor_id = session.get("instructor_id")
    with get_connection() as conn:
        from backend.services import teaching_groups as tg

        g = tg.get_teaching_group(conn, tgid)
        if not g:
            return jsonify({"status": "error", "message": "مجموعة تدريس غير موجودة"}), 404
        if int(g.get("instructor_id") or 0) != int(instructor_id or 0) and not _is_hod_or_admin():
            return jsonify({"status": "error", "message": "FORBIDDEN"}), 403
        baseline = get_active_baseline(conn, g.get("course_name") or "")
        if not baseline:
            return jsonify({"status": "error", "message": "لا توجد قائمة مفردات معتمدة للمقرر"}), 400
        sem = _current_semester_label(conn)
        dept_id = int(g.get("department_id") or 0) or None
        policy = get_gate_policy(conn, dept_id, sem)
        cur = conn.cursor()
        rep = get_delivery_report(conn, tgid, sem, phase)
        now = _now_iso()
        if rep:
            rid = int(rep["id"])
        else:
            cur.execute(
                """
                INSERT INTO course_delivery_reports (
                    teaching_group_id, semester, course_name, instructor_id,
                    baseline_id, phase, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'draft', ?, ?)
                """,
                (
                    tgid,
                    sem,
                    g.get("course_name"),
                    instructor_id,
                    int(baseline["id"]),
                    phase,
                    now,
                    now,
                ),
            )
            if is_postgresql():
                rid = int(_row_dict(cur.execute(
                    "SELECT id FROM course_delivery_reports WHERE teaching_group_id=? AND semester=? AND phase=?",
                    (tgid, sem, phase),
                ).fetchone())["id"])
            else:
                rid = int(cur.lastrowid or 0)
        overall = _compute_overall_pct(items)
        cur.execute(
            "UPDATE course_delivery_reports SET overall_pct=?, updated_at=? WHERE id=?",
            (overall, now, rid),
        )
        cur.execute("DELETE FROM course_delivery_report_items WHERE report_id=?", (rid,))
        for it in items:
            tid = int(it.get("topic_id") or 0)
            if not tid:
                continue
            pct = it.get("completion_pct")
            cur.execute(
                """
                INSERT INTO course_delivery_report_items (report_id, topic_id, completion_pct, incomplete_reason)
                VALUES (?, ?, ?, ?)
                """,
                (rid, tid, pct, (it.get("incomplete_reason") or "").strip()),
            )
        if phase == PHASE_FINAL:
            cur.execute("DELETE FROM course_delivery_extra_topics WHERE report_id=?", (rid,))
            for ex in extra_topics:
                title = (ex.get("title") or "").strip()
                if not title:
                    continue
                cur.execute(
                    "INSERT INTO course_delivery_extra_topics (report_id, title, reason) VALUES (?, ?, ?)",
                    (rid, title, (ex.get("reason") or "").strip()),
                )
        conn.commit()
        rep = get_delivery_report(conn, tgid, sem, phase)
    return jsonify({
        "status": "ok",
        "report": rep,
        "overall_pct": overall,
        "partial_min_pct": policy["partial_min_pct"],
        "final_min_pct": policy["final_min_pct"],
    }), 200


@course_delivery_bp.route("/report/<int:report_id>/submit", methods=["POST"])
@role_required("instructor", "head_of_department")
def api_report_submit(report_id: int):
    data = request.get_json(force=True) or {}
    reason = (data.get("below_threshold_reason") or "").strip()
    with get_connection() as conn:
        cur = conn.cursor()
        rep = _row_dict(cur.execute("SELECT * FROM course_delivery_reports WHERE id=?", (report_id,)).fetchone())
        if not rep:
            return jsonify({"status": "error", "message": "not found"}), 404
        phase = rep.get("phase")
        from backend.services import teaching_groups as tg

        g = tg.get_teaching_group(conn, int(rep["teaching_group_id"]))
        dept_id = int(g.get("department_id") or 0) if g else None
        policy = get_gate_policy(conn, dept_id, rep.get("semester") or "")
        min_pct = policy["partial_min_pct"] if phase == PHASE_PARTIAL else policy["final_min_pct"]
        overall = float(rep.get("overall_pct") or 0)
        now = _now_iso()
        if overall >= min_pct:
            st = "auto_approved"
        else:
            if not reason:
                return jsonify({
                    "status": "error",
                    "message": f"النسبة {overall}% أقل من {min_pct}% — التبرير مطلوب",
                }), 400
            st = "gate_pending"
        cur.execute(
            """
            UPDATE course_delivery_reports
            SET status=?, below_threshold_reason=?, submitted_at=?, updated_at=?
            WHERE id=?
            """,
            (st, reason, now, now, report_id),
        )
        conn.commit()
        from backend.services.course_workflow import notify_report_submitted

        notify_report_submitted(
            conn,
            course_name=str(rep.get("course_name") or ""),
            phase=str(phase or ""),
            report_status=st,
            department_id=dept_id,
            teaching_group_id=int(rep.get("teaching_group_id") or 0),
        )
    return jsonify({"status": "ok", "report_status": st, "overall_pct": overall}), 200


@course_delivery_bp.route("/report/<int:report_id>/gate_review", methods=["POST"])
@role_required("head_of_department", "admin_main", "admin", "system_admin", "college_dean", "academic_vice_dean")
def api_report_gate_review(report_id: int):
    data = request.get_json(force=True) or {}
    action = (data.get("action") or "").strip().lower()
    note = (data.get("note") or "").strip()
    actor = (session.get("user") or "").strip()
    now = _now_iso()
    with get_connection() as conn:
        cur = conn.cursor()
        if action == "approve":
            st = "gate_approved"
        elif action == "reject":
            st = "gate_rejected"
        else:
            return jsonify({"status": "error", "message": "action invalid"}), 400
        cur.execute(
            """
            UPDATE course_delivery_reports
            SET status=?, reviewed_by=?, reviewed_at=?, review_note=?, updated_at=?
            WHERE id=? AND status=?
            """,
            (st, actor, now, note, now, report_id, "gate_pending"),
        )
        rep = _row_dict(cur.execute("SELECT * FROM course_delivery_reports WHERE id=?", (report_id,)).fetchone())
        conn.commit()
        from backend.services.course_workflow import notify_report_gate_reviewed

        notify_report_gate_reviewed(
            conn,
            course_name=str(rep.get("course_name") or ""),
            phase=str(rep.get("phase") or ""),
            action=action,
            instructor_id=int(rep.get("instructor_id") or 0),
        )
    return jsonify({"status": "ok", "report_status": st}), 200


@course_delivery_bp.route("/gate_status", methods=["GET"])
@login_required
def api_gate_status():
    tgid = request.args.get("teaching_group_id", type=int)
    phase = (request.args.get("phase") or PHASE_PARTIAL).strip()
    if not tgid:
        return jsonify({"status": "error", "message": "teaching_group_id مطلوب"}), 400
    with get_connection() as conn:
        from backend.services import teaching_groups as tg

        g = tg.get_teaching_group(conn, tgid)
        if not g:
            return jsonify({"status": "error", "message": "not found"}), 404
        sem = _current_semester_label(conn)
        st = grade_draft_gate_status(
            conn,
            teaching_group_id=tgid,
            semester=sem,
            course_name=g.get("course_name") or "",
            department_id=int(g.get("department_id") or 0) or None,
            phase=phase,
        )
    return jsonify({"status": "ok", **st}), 200


@course_delivery_bp.route("/hod/pending", methods=["GET"])
@role_required("head_of_department")
def api_hod_pending():
    dept_id = get_admin_department_scope_id()
    with get_connection() as conn:
        ensure_course_delivery_schema(conn)
        cur = conn.cursor()
        sem = _current_semester_label(conn)
        dept_courses: list[str] = []
        if dept_id is not None:
            from backend.services import teaching_groups as tg

            for g in tg.list_teaching_groups(conn, semester=sem, department_id=dept_id, active_only=True):
                cn = (g.get("course_name") or "").strip()
                if cn and cn not in dept_courses:
                    dept_courses.append(cn)
        baselines = cur.execute(
            """
            SELECT * FROM course_syllabus_baselines
            WHERE status = ?
            ORDER BY updated_at DESC
            """,
            (BASELINE_PENDING,),
        ).fetchall()
        bl_out = []
        for b in baselines or []:
            item = _row_dict(b)
            cn = (item.get("course_name") or "").strip()
            if dept_id is not None and dept_courses and cn not in dept_courses:
                continue
            item["topics"] = [
                _row_dict(t)
                for t in cur.execute(
                    "SELECT * FROM course_syllabus_topics WHERE baseline_id=? ORDER BY sort_order",
                    (int(item["id"]),),
                ).fetchall()
                or []
            ]
            bl_out.append(item)

        gate_sql = """
            SELECT r.*, tg.group_code, tg.department_id
            FROM course_delivery_reports r
            LEFT JOIN teaching_groups tg ON tg.id = r.teaching_group_id
            WHERE r.status = ?
        """
        gate_params: list[Any] = ["gate_pending"]
        if dept_id is not None:
            gate_sql += " AND tg.department_id = ?"
            gate_params.append(int(dept_id))
        gate_sql += " ORDER BY r.submitted_at DESC"
        gates = cur.execute(gate_sql, tuple(gate_params)).fetchall()

        gd_out: list[dict] = []
        if sem:
            from backend.services.grades import _enrich_drafts_with_group_labels

            gd_cols = {c.lower() for c in fetch_table_columns(conn, "grade_drafts")}
            dp_col = ", d.draft_phase" if "draft_phase" in gd_cols else ""
            tgid_col = ", d.teaching_group_id" if "teaching_group_id" in gd_cols else ""
            gd_sql = f"""
                SELECT d.id, d.semester, d.course_name, d.section_id{tgid_col}{dp_col},
                       d.grading_mode, d.status, d.submitted_at,
                       d.instructor_id, COALESCE(i.name, '') AS instructor_name
                FROM grade_drafts d
                LEFT JOIN instructors i ON i.id = d.instructor_id
                LEFT JOIN teaching_groups tg ON tg.id = d.teaching_group_id
                WHERE d.semester = ? AND d.status = 'Submitted'
            """
            gd_params: list[Any] = [sem]
            if dept_id is not None:
                gd_sql += " AND (tg.department_id = ? OR d.course_name IN (SELECT course_name FROM teaching_groups WHERE department_id = ? AND semester = ?))"
                gd_params.extend([int(dept_id), int(dept_id), sem])
            gd_sql += " ORDER BY d.submitted_at DESC, d.course_name"
            rows = cur.execute(gd_sql, tuple(gd_params)).fetchall()
            gd_out = [_row_dict(r) for r in rows or []]
            _enrich_drafts_with_group_labels(conn, gd_out)

        summary = {
            "pending_baselines": len(bl_out),
            "pending_gate_reports": len(gates or []),
            "pending_grade_drafts": len(gd_out),
            "total_pending": len(bl_out) + len(gates or []) + len(gd_out),
            "semester": sem,
            "department_id": dept_id,
        }
    return jsonify({
        "status": "ok",
        "pending_baselines": bl_out,
        "pending_gate_reports": [_row_dict(g) for g in gates or []],
        "pending_grade_drafts": gd_out,
        "summary": summary,
    }), 200


@course_delivery_bp.route("/hod/department_summary", methods=["GET"])
@role_required("head_of_department")
def api_hod_department_summary():
    """8.8 — ملخص متابعة القسم: تقدم تقرير التنفيذ لكل مجموعة تدريس."""
    dept_id = get_admin_department_scope_id()
    with get_connection() as conn:
        ensure_course_delivery_schema(conn)
        from backend.services import teaching_groups as tg

        sem = (request.args.get("semester") or "").strip() or _current_semester_label(conn)
        groups = tg.list_teaching_groups(conn, semester=sem, department_id=dept_id, active_only=True)
        rows_out: list[dict] = []
        for g in groups or []:
            tgid = int(g.get("id") or 0)
            cn = (g.get("course_name") or "").strip()
            iid = int(g.get("instructor_id") or 0)
            sids = tg.list_linked_section_ids(conn, tgid)
            row = {
                "teaching_group_id": tgid,
                "group_code": g.get("group_code"),
                "course_name": cn,
                "instructor_id": iid,
                "instructor_name": g.get("instructor_name") or "",
                "section_ids": sids,
                "section_id": sids[0] if sids else None,
                "axes": {},
            }
            apply_auto_axes_to_portal_row(conn, row, semester=sem, instructor_id=iid)
            ds = delivery_summary_for_ui(conn, teaching_group_id=tgid, course_name=cn, semester=sem)
            row["delivery_summary"] = ds
            from backend.services.course_workflow import faculty_progress_counts

            prog = faculty_progress_counts(row)
            rows_out.append({
                "teaching_group_id": tgid,
                "group_code": g.get("group_code"),
                "course_name": cn,
                "instructor_name": g.get("instructor_name") or "",
                "axes": row.get("axes") or {},
                "delivery": {
                    "baseline_ok": bool(ds.get("baseline_ok")),
                    "partial_submitted": bool((ds.get("partial") or {}).get("submitted")),
                    "final_submitted": bool((ds.get("final") or {}).get("submitted")),
                    "checkpoints_done": int(ds.get("checkpoints_done") or 0),
                    "checkpoints_total": int(ds.get("checkpoints_total") or 3),
                },
                "progress_done": prog["done"],
                "progress_total": prog["total"],
                "survey_url": ds.get("survey_url") or f"/course_delivery_page?teaching_group_id={tgid}",
            })
        complete = sum(1 for r in rows_out if r["delivery"]["checkpoints_done"] >= r["delivery"]["checkpoints_total"])
    return jsonify({
        "status": "ok",
        "semester": sem,
        "department_id": dept_id,
        "summary": {
            "groups_total": len(rows_out),
            "groups_documentation_complete": complete,
            "groups_in_progress": len(rows_out) - complete,
        },
        "rows": rows_out,
    }), 200


@course_delivery_bp.route("/gate_policy", methods=["GET", "PUT"])
@role_required("head_of_department", "admin_main", "admin", "system_admin", "college_dean", "academic_vice_dean")
def api_gate_policy():
    dept_id = get_admin_department_scope_id()
    with get_connection() as conn:
        ensure_course_delivery_schema(conn)
        sem = _current_semester_label(conn)
        if request.method == "GET":
            pol = get_gate_policy(conn, dept_id, sem)
            return jsonify({"status": "ok", "semester": sem, "department_id": dept_id, **pol}), 200
        data = request.get_json(force=True) or {}
        partial_min = float(data.get("partial_min_pct") or 50)
        final_min = float(data.get("final_min_pct") or 80)
        actor = (session.get("user") or "").strip()
        now = _now_iso()
        cur = conn.cursor()
        existing = cur.execute(
            "SELECT id FROM grade_gate_policies WHERE department_id IS ? AND semester_label = ?",
            (dept_id, sem),
        ).fetchone()
        if existing:
            cur.execute(
                """
                UPDATE grade_gate_policies
                SET partial_min_pct=?, final_min_pct=?, updated_by=?, updated_at=?
                WHERE id=?
                """,
                (partial_min, final_min, actor, now, int(_row_dict(existing)["id"])),
            )
        else:
            cur.execute(
                """
                INSERT INTO grade_gate_policies (department_id, semester_label, partial_min_pct, final_min_pct, updated_by, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (dept_id, sem, partial_min, final_min, actor, now),
            )
        conn.commit()
    return jsonify({"status": "ok", "partial_min_pct": partial_min, "final_min_pct": final_min}), 200
