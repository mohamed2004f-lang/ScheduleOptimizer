"""
تقرير تنفيذ المقرر (baseline مفردات + تقارير جزئي/نهائي) وبوابة مسودات الدرجات.
"""
from __future__ import annotations

import datetime
from typing import Any
from urllib.parse import urlencode

from flask import Blueprint, jsonify, request, session

from backend.core.auth import login_required, role_required
from backend.core.department_scope_policy import (
    assert_hod_for_course_operation,
    filter_items_for_course_hod_scope,
    hod_may_operate_on_course,
    resolve_effective_department_scope_id,
)
from backend.database.database import fetch_table_columns, is_postgresql
from backend.services.utilities import get_connection, get_current_term

course_delivery_bp = Blueprint("course_delivery", __name__)

PHASE_PARTIAL = "partial"
PHASE_FINAL = "final"
BASELINE_DRAFT = "draft"
BASELINE_PENDING = "pending_hod"
BASELINE_APPROVED = "approved"
BASELINE_SUPERSEDED = "superseded"
INCOMPLETE_PCT_THRESHOLD = 50.0  # ما لم يُنجز = نسبة أقل من 50%
MIN_BOOK_REFERENCES = 2
REF_TYPE_BOOK = "book"


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
    return role in (
        "head_of_department",
        "admin_main",
        "admin",
        "system_admin",
        "college_dean",
        "academic_vice_dean",
    )


def _is_college_leadership_or_admin() -> bool:
    role = (session.get("user_role") or "").strip()
    return role in (
        "admin_main",
        "admin",
        "system_admin",
        "college_dean",
        "academic_vice_dean",
    )


def _delivery_department_scope_id(conn) -> int | None:
    uname = (session.get("user") or session.get("username") or "").strip()
    return resolve_effective_department_scope_id(conn, uname)


def _resolve_baseline_teaching_context(conn, bl: dict) -> dict[str, Any]:
    """يستنتج سياق التدريس لقائمة المفردات من مجموعة التدريس أو الفصل."""
    cn = str(bl.get("course_name") or "").strip()
    sem = str(bl.get("semester_label") or "").strip() or _current_semester_label(conn)
    tgid = None
    iid = bl.get("created_by_instructor_id")
    if iid and cn:
        row = conn.cursor().execute(
            """
            SELECT id FROM teaching_groups
            WHERE lower(trim(course_name)) = lower(trim(?))
              AND instructor_id = ?
              AND (semester = ? OR COALESCE(?, '') = '')
            ORDER BY id DESC
            LIMIT 1
            """,
            (cn, int(iid), sem, sem),
        ).fetchone()
        if row:
            tgid = int(row["id"] if hasattr(row, "keys") else row[0])
    return {"teaching_group_id": tgid, "section_id": None, "semester": sem}


def _guard_hod_course(conn, course_name: str, *, teaching_group_id=None, section_id=None, semester=None):
    actor = (session.get("user") or session.get("username") or "").strip()
    try:
        assert_hod_for_course_operation(
            conn,
            actor,
            str(course_name or ""),
            teaching_group_id=teaching_group_id,
            section_id=section_id,
            semester=semester,
        )
    except PermissionError as exc:
        return jsonify({"status": "error", "message": str(exc) or "FORBIDDEN_DEPARTMENT_SCOPE"}), 403
    return None


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
            instructor_comments TEXT DEFAULT '',
            instructor_recommendations TEXT DEFAULT '',
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
        """
        CREATE TABLE IF NOT EXISTS course_delivery_references (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_id INTEGER NOT NULL,
            ref_type TEXT NOT NULL DEFAULT 'book',
            title TEXT NOT NULL,
            publication_date TEXT DEFAULT '',
            url_or_isbn TEXT DEFAULT '',
            sort_order INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (report_id) REFERENCES course_delivery_reports(id) ON DELETE CASCADE
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS course_delivery_assessment_methods (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_id INTEGER NOT NULL,
            method_label TEXT NOT NULL,
            weight_pct REAL,
            notes TEXT DEFAULT '',
            sort_order INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (report_id) REFERENCES course_delivery_reports(id) ON DELETE CASCADE
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS grade_entry_locks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            teaching_group_id INTEGER NOT NULL,
            semester TEXT NOT NULL,
            phase TEXT NOT NULL,
            is_open INTEGER NOT NULL DEFAULT 0,
            set_by TEXT DEFAULT '',
            set_at TEXT,
            note TEXT DEFAULT '',
            UNIQUE (teaching_group_id, semester, phase)
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
        stmts[6] = stmts[6].replace("BIGINT PRIMARY KEY", "BIGSERIAL PRIMARY KEY", 1)
        stmts[7] = stmts[7].replace("BIGINT PRIMARY KEY", "BIGSERIAL PRIMARY KEY", 1)
        stmts[8] = stmts[8].replace("BIGINT PRIMARY KEY", "BIGSERIAL PRIMARY KEY", 1)
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
    try:
        rep_cols = {c.lower() for c in fetch_table_columns(conn, "course_delivery_reports")}
        if "instructor_comments" not in rep_cols:
            cur.execute(
                "ALTER TABLE course_delivery_reports ADD COLUMN instructor_comments TEXT DEFAULT ''"
            )
        if "instructor_recommendations" not in rep_cols:
            cur.execute(
                "ALTER TABLE course_delivery_reports ADD COLUMN instructor_recommendations TEXT DEFAULT ''"
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
    """المفردات المعتمدة النشطة للمقرر — مشتركة بين كل الأساتذة."""
    ensure_course_delivery_schema(conn)
    cur = conn.cursor()
    cn = (course_name or "").strip()
    if not cn:
        return None
    row = cur.execute(
        """
        SELECT * FROM course_syllabus_baselines
        WHERE lower(trim(course_name)) = lower(trim(?)) AND status = ?
        ORDER BY version DESC, id DESC
        LIMIT 1
        """,
        (cn, BASELINE_APPROVED),
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
    bl["reusable"] = True
    return bl


def list_incomplete_topics(items: list[dict], topics_by_id: dict[int, dict] | None = None) -> list[dict]:
    """مفردات نسبة إنجازها أقل من 50%."""
    out = []
    for it in items or []:
        pct = it.get("completion_pct")
        if pct is None:
            continue
        try:
            pct_f = float(pct)
        except (TypeError, ValueError):
            continue
        if pct_f >= INCOMPLETE_PCT_THRESHOLD:
            continue
        tid = int(it.get("topic_id") or 0)
        title = (it.get("topic_title") or "").strip()
        if not title and topics_by_id and tid in topics_by_id:
            title = topics_by_id[tid].get("topic_title") or ""
        out.append(
            {
                "topic_id": tid,
                "topic_title": title,
                "completion_pct": pct_f,
                "incomplete_reason": (it.get("incomplete_reason") or "").strip(),
            }
        )
    return out


def _is_book_ref(ref: dict) -> bool:
    t = (ref.get("ref_type") or "").strip().lower()
    return t in (REF_TYPE_BOOK, "كتاب", "كتب")


def _replace_report_references(conn, report_id: int, references: list[dict]) -> None:
    cur = conn.cursor()
    cur.execute("DELETE FROM course_delivery_references WHERE report_id=?", (int(report_id),))
    for i, ref in enumerate(references or []):
        title = (ref.get("title") or "").strip()
        if not title:
            continue
        cur.execute(
            """
            INSERT INTO course_delivery_references
                (report_id, ref_type, title, publication_date, url_or_isbn, sort_order)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                int(report_id),
                (ref.get("ref_type") or REF_TYPE_BOOK).strip() or REF_TYPE_BOOK,
                title,
                (ref.get("publication_date") or "").strip(),
                (ref.get("url_or_isbn") or "").strip(),
                int(ref.get("sort_order") if ref.get("sort_order") is not None else i),
            ),
        )


def _replace_assessment_methods(conn, report_id: int, methods: list[dict]) -> None:
    cur = conn.cursor()
    cur.execute("DELETE FROM course_delivery_assessment_methods WHERE report_id=?", (int(report_id),))
    for i, m in enumerate(methods or []):
        label = (m.get("method_label") or m.get("label") or "").strip()
        if not label:
            continue
        w = m.get("weight_pct")
        try:
            w_f = float(w) if w is not None and w != "" else None
        except (TypeError, ValueError):
            w_f = None
        cur.execute(
            """
            INSERT INTO course_delivery_assessment_methods
                (report_id, method_label, weight_pct, notes, sort_order)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                int(report_id),
                label,
                w_f,
                (m.get("notes") or "").strip(),
                int(m.get("sort_order") if m.get("sort_order") is not None else i),
            ),
        )


def validate_quality_report_for_submit(rep: dict, *, require_books: bool = True, require_assessments: bool = True) -> str | None:
    """يعيد رسالة خطأ عربية أو None إن جاز الإرسال."""
    items = rep.get("items") or []
    incomplete = list_incomplete_topics(items)
    for it in incomplete:
        if not (it.get("incomplete_reason") or "").strip():
            title = it.get("topic_title") or f"#{it.get('topic_id')}"
            return f"أدخل سبب عدم الإنجاز للمفردة «{title}» (نسبة أقل من {int(INCOMPLETE_PCT_THRESHOLD)}%)"
    for ex in rep.get("extra_topics") or []:
        if (ex.get("title") or "").strip() and not (ex.get("reason") or "").strip():
            return f"برّر أهمية المفردة خارج المقرر: «{(ex.get('title') or '').strip()}»"
    if require_books:
        books = [r for r in (rep.get("references") or []) if _is_book_ref(r)]
        if len(books) < MIN_BOOK_REFERENCES:
            return f"يُفضَّل توثيق كتابين رسميّين على الأقل (الموجود: {len(books)})"
        for b in books:
            if not (b.get("publication_date") or "").strip():
                return f"أضف تاريخ الإصدار للكتاب: «{(b.get('title') or '').strip()}»"
    if require_assessments:
        methods = rep.get("assessment_methods") or []
        if not methods:
            return "اختر طريقة تقييم واحدة على الأقل لهذا المقرر"
    return None


def list_pending_quality_reports(
    conn,
    *,
    instructor_id: int,
    semester: str | None = None,
) -> list[dict]:
    """تقارير جودة المقرر المعلّقة للأستاذ — تظهر في مركز الاستبيانات."""
    ensure_course_delivery_schema(conn)
    from backend.services import teaching_groups as tg

    sem = (semester or "").strip() or _current_semester_label(conn)
    groups = tg.list_teaching_groups(conn, semester=sem, active_only=True)
    out: list[dict] = []
    for g in groups or []:
        if int(g.get("instructor_id") or 0) != int(instructor_id):
            continue
        tgid = int(g.get("id") or 0)
        cn = (g.get("course_name") or "").strip()
        baseline = get_active_baseline(conn, cn)
        for phase, label in ((PHASE_PARTIAL, "جزئي"), (PHASE_FINAL, "نهائي")):
            rep = get_delivery_report(conn, tgid, sem, phase)
            submitted = _report_submitted(rep)
            if submitted:
                continue
            out.append(
                {
                    "pending_kind": "course_quality_report",
                    "code": f"quality_{phase}_{tgid}",
                    "title_ar": f"تقرير مقرر دراسي ({label}): {cn}",
                    "fill_url": f"/course_delivery_page?teaching_group_id={tgid}&phase={phase}",
                    "teaching_group_id": tgid,
                    "course_name": cn,
                    "phase": phase,
                    "baseline_ok": bool(baseline and baseline.get("topics")),
                    "group_code": g.get("group_code") or "",
                }
            )
    return out


def build_progress_board_rows(
    conn,
    *,
    semester: str | None = None,
    department_id: int | None = None,
) -> list[dict]:
    """صفوف لوحة المتابعة: نسب، فجوات، أقفال درجات، مراجع."""
    from backend.services import teaching_groups as tg

    sem = (semester or "").strip() or _current_semester_label(conn)
    groups = tg.list_teaching_groups(
        conn, semester=sem, department_id=department_id, active_only=True
    )
    rows: list[dict] = []
    for g in groups or []:
        tgid = int(g.get("id") or 0)
        cn = (g.get("course_name") or "").strip()
        partial = get_delivery_report(conn, tgid, sem, PHASE_PARTIAL)
        final = get_delivery_report(conn, tgid, sem, PHASE_FINAL)
        primary = final or partial
        incomplete = (primary or {}).get("incomplete_topics") or []
        lock_p = get_grade_entry_lock(conn, tgid, sem, PHASE_PARTIAL)
        lock_f = get_grade_entry_lock(conn, tgid, sem, PHASE_FINAL)
        books = int((primary or {}).get("book_reference_count") or 0)
        rows.append(
            {
                "teaching_group_id": tgid,
                "group_code": g.get("group_code"),
                "course_name": cn,
                "instructor_id": int(g.get("instructor_id") or 0),
                "instructor_name": g.get("instructor_name") or "",
                "department_id": g.get("department_id"),
                "overall_pct": (primary or {}).get("overall_pct"),
                "partial_pct": (partial or {}).get("overall_pct"),
                "final_pct": (final or {}).get("overall_pct"),
                "partial_status": (partial or {}).get("status") or "missing",
                "final_status": (final or {}).get("status") or "missing",
                "incomplete_count": len(incomplete),
                "incomplete_topics": incomplete[:8],
                "book_reference_count": books,
                "books_ok": books >= MIN_BOOK_REFERENCES,
                "partial_lock_open": bool(lock_p.get("is_open")),
                "final_lock_open": bool(lock_f.get("is_open")),
                "survey_url": f"/course_delivery_page?teaching_group_id={tgid}",
                "preview_url": f"/academic_quality/course_reports/{tgid}",
                "pdf_url": f"/academic_quality/course_reports/{tgid}.pdf",
                "warn_url": f"/course_delivery/hod/warn_instructor",
            }
        )
    return rows


_REPORT_STATUS_AR = {
    "missing": "غير موجود",
    "draft": "مسودة",
    "auto_approved": "مُرسل",
    "gate_pending": "مُرسل — متابعة القسم",
    "gate_approved": "مُرسل — موافق عليه",
    "gate_rejected": "مرفوض",
    "submitted": "مُرسل",
}

_REF_TYPE_AR = {
    "book": "كتاب",
    "paper": "ورقة علمية",
    "website": "موقع",
    "video": "فيديو",
    "other": "أخرى",
    "كتاب": "كتاب",
}


def report_status_label_ar(status: str | None) -> str:
    st = (status or "missing").strip()
    return _REPORT_STATUS_AR.get(st, st or "—")


def _phase_analysis_bits(rep: dict | None, *, phase_label: str, follow_min: float) -> list[str]:
    bits: list[str] = []
    if not rep:
        bits.append(f"تقرير {phase_label}: لم يُنشأ بعد.")
        return bits
    st = report_status_label_ar(rep.get("status"))
    ov = rep.get("overall_pct")
    bits.append(f"تقرير {phase_label}: {st}" + (f" — نسبة {ov}%" if ov is not None else ""))
    incomplete = rep.get("incomplete_topics") or []
    if incomplete:
        bits.append(f"فجوات إنجاز (أقل من {int(INCOMPLETE_PCT_THRESHOLD)}٪) في {phase_label}: {len(incomplete)} مفردة.")
    if ov is not None and float(ov) < float(follow_min):
        bits.append(f"النسبة دون حد متابعة {phase_label} ({follow_min}٪) — للمتابعة الإدارية فقط.")
    books = int(rep.get("book_reference_count") or 0)
    if books < MIN_BOOK_REFERENCES:
        bits.append(f"المراجع المصنّفة ككتب: {books} من {MIN_BOOK_REFERENCES} المفضّلة.")
    return bits


def _dedupe_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for it in items:
        t = (it or "").strip()
        if not t or t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out


def build_executive_summary_lines(
    *,
    primary: dict | None,
    primary_phase: str | None,
    partial: dict | None,
    final: dict | None,
    policy: dict,
    baseline_ok: bool,
) -> list[str]:
    """سطور ملخص تنفيذي قصيرة لغلاف التقرير."""
    lines: list[str] = []
    if not baseline_ok:
        lines.append("لا توجد قائمة مفردات معتمدة بعد.")
    phase_ar = "النهائي" if primary_phase == PHASE_FINAL else ("الجزئي" if primary_phase == PHASE_PARTIAL else None)
    if primary and phase_ar:
        st = report_status_label_ar(primary.get("status"))
        ov = primary.get("overall_pct")
        bit = f"التقرير المعروض ({phase_ar}): {st}"
        if ov is not None:
            bit += f" — نسبة الإنجاز {ov}%"
        lines.append(bit)
        gaps = len(primary.get("incomplete_topics") or [])
        lines.append(f"فجوات أقل من {int(INCOMPLETE_PCT_THRESHOLD)}٪: {gaps} مفردة.")
        books = int(primary.get("book_reference_count") or 0)
        lines.append(f"كتب مرجعية: {books}/{MIN_BOOK_REFERENCES}.")
        follow = (
            policy.get("final_min_pct")
            if primary_phase == PHASE_FINAL
            else policy.get("partial_min_pct")
        )
        if ov is not None and follow is not None and float(ov) < float(follow):
            lines.append(f"دون حد المتابعة ({follow}٪).")
        else:
            lines.append(f"ضمن/فوق حد المتابعة ({follow}٪)." if follow is not None else "")
    else:
        lines.append("لم يُنشأ تقرير جزئي أو نهائي بعد.")
    p_st = report_status_label_ar(partial.get("status")) if partial else "غير موجود"
    f_st = report_status_label_ar(final.get("status")) if final else "غير موجود"
    lines.append(f"حالة الإرسال — جزئي: {p_st} · نهائي: {f_st}.")
    return [x for x in lines if x]


def build_operational_recommendations(
    *,
    partial: dict | None,
    final: dict | None,
    policy: dict,
    baseline_ok: bool,
) -> list[str]:
    """توصيات تشغيلية مبنية على قواعد (قابلة للطباعة كشاهد)."""
    recs: list[str] = []
    if not baseline_ok:
        recs.append("اعتماد قائمة مفردات المقرر قبل استكمال نسب الإنجاز والإرسال.")

    phases = (
        ("الجزئي", partial, float(policy.get("partial_min_pct") or 0)),
        ("النهائي", final, float(policy.get("final_min_pct") or 0)),
    )
    for phase_label, rep, follow_min in phases:
        if not rep:
            recs.append(f"إنشاء تقرير {phase_label} وإكماله وفق جدول القسم.")
            continue
        if not _report_submitted(rep):
            recs.append(f"إرسال تقرير {phase_label} بعد استيفاء البنود الإلزامية.")
        incomplete = rep.get("incomplete_topics") or []
        if incomplete:
            titles = [str(x.get("topic_title") or "").strip() for x in incomplete[:3] if x.get("topic_title")]
            hint = (" — منها: " + "؛ ".join(titles)) if titles else ""
            recs.append(
                f"معالجة فجوات إنجاز تقرير {phase_label} "
                f"({len(incomplete)} مفردة دون {int(INCOMPLETE_PCT_THRESHOLD)}٪){hint} "
                "بإعادة جدولة أو جلسة تعويضية مع توثيق السبب."
            )
        ov = rep.get("overall_pct")
        if ov is not None and float(ov) < follow_min:
            recs.append(
                f"رفع نسبة إنجاز {phase_label} فوق حد المتابعة ({follow_min}٪) "
                "أو توثيق تبرير واضح لرئيس القسم."
            )
        books = int(rep.get("book_reference_count") or 0)
        if books < MIN_BOOK_REFERENCES:
            recs.append(
                f"استكمال المراجع في تقرير {phase_label}: "
                f"يُفضَّل {MIN_BOOK_REFERENCES} كتاباً رسمياً على الأقل (حالياً {books})."
            )
        if not (rep.get("assessment_methods") or []):
            recs.append(f"تسجيل طرق التقييم وأوزانها في تقرير {phase_label}.")
        if not (rep.get("instructor_recommendations") or "").strip() and _report_submitted(rep):
            recs.append(
                f"إضافة توصيات تحسين واضحة من الأستاذ في تقرير {phase_label} قبل الطباعة للاعتماد."
            )

    if not partial and not final:
        recs.append("بدء تعبئة التقرير من صفحة مقرراتي / تعبئة تنفيذ المقرر.")
    return _dedupe_keep_order(recs)[:8]


def build_course_report_view(
    conn,
    *,
    teaching_group_id: int,
    semester: str | None = None,
    phase: str | None = None,
) -> dict[str, Any] | None:
    """سياق معاينة/طباعة تقرير مقرر واحد."""
    ensure_course_delivery_schema(conn)
    from backend.services import teaching_groups as tg

    tgid = int(teaching_group_id)
    g = tg.get_teaching_group(conn, tgid)
    if not g:
        return None
    sem = (semester or "").strip() or _current_semester_label(conn)
    cn = (g.get("course_name") or "").strip()
    dept_id = int(g.get("department_id") or 0) or None
    policy = get_gate_policy(conn, dept_id, sem)
    baseline = get_active_baseline(conn, cn)
    partial = get_delivery_report(conn, tgid, sem, PHASE_PARTIAL)
    final = get_delivery_report(conn, tgid, sem, PHASE_FINAL)
    show_phase = (phase or "").strip().lower()
    if show_phase == PHASE_PARTIAL:
        primary = partial
        primary_phase = PHASE_PARTIAL
    elif show_phase == PHASE_FINAL:
        primary = final
        primary_phase = PHASE_FINAL
    else:
        primary = final or partial
        primary_phase = PHASE_FINAL if final else (PHASE_PARTIAL if partial else None)

    lock_p = get_grade_entry_lock(conn, tgid, sem, PHASE_PARTIAL)
    lock_f = get_grade_entry_lock(conn, tgid, sem, PHASE_FINAL)
    baseline_ok = bool(baseline and baseline.get("topics"))
    analysis_bits: list[str] = []
    analysis_bits.extend(
        _phase_analysis_bits(partial, phase_label="الجزئي", follow_min=policy["partial_min_pct"])
    )
    analysis_bits.extend(
        _phase_analysis_bits(final, phase_label="النهائي", follow_min=policy["final_min_pct"])
    )
    if not baseline_ok:
        analysis_bits.insert(0, "لا توجد قائمة مفردات معتمدة لهذا المقرر بعد.")

    executive_summary = build_executive_summary_lines(
        primary=primary,
        primary_phase=primary_phase,
        partial=partial,
        final=final,
        policy=policy,
        baseline_ok=baseline_ok,
    )
    operational_recommendations = build_operational_recommendations(
        partial=partial,
        final=final,
        policy=policy,
        baseline_ok=baseline_ok,
    )

    def _decorate_report(rep: dict | None) -> dict | None:
        if not rep:
            return None
        out = dict(rep)
        out["status_ar"] = report_status_label_ar(out.get("status"))
        refs = []
        for r in out.get("references") or []:
            rr = dict(r)
            rt = (rr.get("ref_type") or "").strip().lower()
            rr["ref_type_ar"] = _REF_TYPE_AR.get(rt, rr.get("ref_type") or "—")
            refs.append(rr)
        out["references"] = refs
        return out

    try:
        from backend.services.survey_analytics import COLLEGE_NAME_AR, pdf_arabic_extra_css
    except Exception:
        COLLEGE_NAME_AR = "كلية الهندسة"
        def pdf_arabic_extra_css(*, for_pdf: bool = False) -> str:
            return ""

    return {
        "title": f"تقرير مقرر دراسي: {cn}",
        "college_name_ar": COLLEGE_NAME_AR,
        "semester": sem,
        "teaching_group_id": tgid,
        "group_code": g.get("group_code") or "",
        "course_name": cn,
        "instructor_id": int(g.get("instructor_id") or 0),
        "instructor_name": g.get("instructor_name") or "",
        "department_id": dept_id,
        "baseline": baseline,
        "baseline_ok": baseline_ok,
        "partial": _decorate_report(partial),
        "final": _decorate_report(final),
        "primary": _decorate_report(primary),
        "primary_phase": primary_phase,
        "policy": policy,
        "incomplete_threshold": INCOMPLETE_PCT_THRESHOLD,
        "min_book_references": MIN_BOOK_REFERENCES,
        "partial_lock_open": bool(lock_p.get("is_open")),
        "final_lock_open": bool(lock_f.get("is_open")),
        "executive_summary": executive_summary,
        "analysis_bits": analysis_bits,
        "operational_recommendations": operational_recommendations,
        "fill_url": f"/course_delivery_page?teaching_group_id={tgid}",
        "preview_url": f"/academic_quality/course_reports/{tgid}",
        "pdf_url": f"/academic_quality/course_reports/{tgid}.pdf",
        "assistant_url": (
            "/academic_quality/assistant?"
            + urlencode(
                {
                    "hint": "course_report",
                    "teaching_group_id": str(tgid),
                    "course": cn,
                }
            )
        ),
        "pdf_arabic_css": pdf_arabic_extra_css(for_pdf=False),
        "pdf_arabic_css_print": pdf_arabic_extra_css(for_pdf=True),
        "export_date": datetime.datetime.now().strftime("%Y-%m-%d"),
        "evidence_type_code": "course_delivery_quality_report",
        "evidence_hint_ar": (
            "يُقترح كشاهد تشغيل/تدريس في خريطة الاعتماد بعد المراجعة البشرية "
            "وربطه يدوياً بنوع «تقرير مقرر دراسي (تنفيذ المفردات)»."
        ),
    }


def build_course_reports_index(
    conn,
    *,
    semester: str | None = None,
    department_id: int | None = None,
    instructor_id: int | None = None,
    status_filter: str | None = None,
) -> dict[str, Any]:
    """فهرس تقارير جودة المقررات للواجهة."""
    sem = (semester or "").strip() or _current_semester_label(conn)
    rows = build_progress_board_rows(conn, semester=sem, department_id=department_id)
    if instructor_id is not None:
        rows = [r for r in rows if int(r.get("instructor_id") or 0) == int(instructor_id)]
    sf = (status_filter or "").strip().lower()
    if sf == "low":
        rows = [
            r
            for r in rows
            if r.get("overall_pct") is not None and float(r["overall_pct"]) < INCOMPLETE_PCT_THRESHOLD
        ]
    elif sf == "missing_books":
        rows = [r for r in rows if not r.get("books_ok")]
    elif sf == "unsubmitted":
        rows = [
            r
            for r in rows
            if (r.get("final_status") in ("missing", "draft"))
            and (r.get("partial_status") in ("missing", "draft"))
        ]
    elif sf == "submitted":
        rows = [
            r
            for r in rows
            if r.get("final_status") not in ("missing", "draft")
            or r.get("partial_status") not in ("missing", "draft")
        ]

    for r in rows:
        r["partial_status_ar"] = report_status_label_ar(r.get("partial_status"))
        r["final_status_ar"] = report_status_label_ar(r.get("final_status"))

    low = sum(
        1
        for r in rows
        if r.get("overall_pct") is not None and float(r["overall_pct"]) < INCOMPLETE_PCT_THRESHOLD
    )
    missing_books = sum(1 for r in rows if not r.get("books_ok"))
    submitted = sum(
        1
        for r in rows
        if r.get("final_status") not in ("missing", "draft")
        or r.get("partial_status") not in ("missing", "draft")
    )
    return {
        "semester": sem,
        "department_id": department_id,
        "rows": rows,
        "summary": {
            "groups_total": len(rows),
            "low_completion": low,
            "missing_books": missing_books,
            "submitted": submitted,
            "unsubmitted": len(rows) - submitted,
        },
        "incomplete_threshold": INCOMPLETE_PCT_THRESHOLD,
        "min_book_references": MIN_BOOK_REFERENCES,
        "package_preview_url": "/academic_quality/course_reports/package",
        "package_pdf_url": "/academic_quality/course_reports/package.pdf",
    }


def build_course_reports_package_context(
    conn,
    *,
    semester: str | None = None,
    department_id: int | None = None,
    college_wide: bool = False,
    max_detail: int = 40,
) -> dict[str, Any]:
    """سياق الحزمة الإجمالية للمعاينة/PDF."""
    try:
        from backend.services.survey_analytics import COLLEGE_NAME_AR, pdf_arabic_extra_css
    except Exception:
        COLLEGE_NAME_AR = "كلية الهندسة"
        def pdf_arabic_extra_css(*, for_pdf: bool = False) -> str:
            return ""

    sem = (semester or "").strip() or _current_semester_label(conn)
    dept = None if college_wide else department_id
    index = build_course_reports_index(conn, semester=sem, department_id=dept)
    details: list[dict] = []
    for row in (index.get("rows") or [])[: int(max_detail)]:
        view = build_course_report_view(
            conn,
            teaching_group_id=int(row["teaching_group_id"]),
            semester=sem,
        )
        if view:
            details.append(view)

    by_dept: dict[str, dict] = {}
    for r in index.get("rows") or []:
        did = str(r.get("department_id") if r.get("department_id") is not None else "بدون")
        slot = by_dept.setdefault(
            did,
            {
                "department_id": r.get("department_id"),
                "groups": 0,
                "low_completion": 0,
                "missing_books": 0,
                "pct_sum": 0.0,
                "pct_n": 0,
            },
        )
        slot["groups"] += 1
        if r.get("overall_pct") is not None:
            slot["pct_sum"] += float(r["overall_pct"])
            slot["pct_n"] += 1
        if r.get("overall_pct") is not None and float(r["overall_pct"]) < INCOMPLETE_PCT_THRESHOLD:
            slot["low_completion"] += 1
        if not r.get("books_ok"):
            slot["missing_books"] += 1
    dept_summary = []
    for slot in by_dept.values():
        n = slot.pop("pct_n")
        s = slot.pop("pct_sum")
        slot["avg_overall_pct"] = round(s / n, 1) if n else None
        dept_summary.append(slot)

    return {
        "title": "حزمة تقارير جودة المقررات",
        "college_name_ar": COLLEGE_NAME_AR,
        "semester": sem,
        "college_wide": bool(college_wide),
        "department_id": dept,
        "summary": index.get("summary") or {},
        "by_department": dept_summary,
        "rows": index.get("rows") or [],
        "details": details,
        "incomplete_threshold": INCOMPLETE_PCT_THRESHOLD,
        "min_book_references": MIN_BOOK_REFERENCES,
        "pdf_arabic_css": pdf_arabic_extra_css(for_pdf=False),
        "pdf_arabic_css_print": pdf_arabic_extra_css(for_pdf=True),
        "export_date": datetime.datetime.now().strftime("%Y-%m-%d"),
        "evidence_type_code": "course_delivery_quality_report",
        "evidence_hint_ar": (
            "الحزمة تدعم شواهد البرامج/القسم؛ الربط النهائي يدوي في خريطة الاعتماد."
        ),
        "preview_url": "/academic_quality/course_reports/package",
        "pdf_url": "/academic_quality/course_reports/package.pdf",
        "index_url": "/academic_quality/course_reports",
    }


def user_may_view_course_report(
    conn,
    *,
    teaching_group_id: int,
    user_role: str,
    instructor_id: int | None,
    username: str | None,
) -> bool:
    """صلاحية معاينة تقرير مقرر."""
    role = (user_role or "").strip()
    if role in ("admin", "admin_main", "system_admin", "college_dean", "academic_vice_dean"):
        return True
    from backend.services import teaching_groups as tg

    g = tg.get_teaching_group(conn, int(teaching_group_id))
    if not g:
        return False
    if instructor_id and int(g.get("instructor_id") or 0) == int(instructor_id):
        return True
    if role == "head_of_department":
        try:
            assert_hod_for_course_operation(
                conn,
                (username or "").strip(),
                str(g.get("course_name") or ""),
                teaching_group_id=int(teaching_group_id),
                semester=str(g.get("semester") or ""),
            )
            return True
        except PermissionError:
            return False
    return False


def get_grade_entry_lock(conn, teaching_group_id: int, semester: str, phase: str) -> dict:
    ensure_course_delivery_schema(conn)
    cur = conn.cursor()
    row = cur.execute(
        """
        SELECT * FROM grade_entry_locks
        WHERE teaching_group_id = ? AND semester = ? AND phase = ?
        LIMIT 1
        """,
        (int(teaching_group_id), (semester or "").strip(), (phase or "").strip()),
    ).fetchone()
    if not row:
        return {
            "teaching_group_id": int(teaching_group_id),
            "semester": semester,
            "phase": phase,
            "is_open": False,
            "set_by": None,
            "set_at": None,
            "note": "",
        }
    d = _row_dict(row)
    d["is_open"] = bool(int(d.get("is_open") or 0))
    return d


def set_grade_entry_lock(
    conn,
    *,
    teaching_group_id: int,
    semester: str,
    phase: str,
    is_open: bool,
    set_by: str,
    note: str = "",
) -> dict:
    ensure_course_delivery_schema(conn)
    cur = conn.cursor()
    now = _now_iso()
    existing = cur.execute(
        """
        SELECT id FROM grade_entry_locks
        WHERE teaching_group_id = ? AND semester = ? AND phase = ?
        LIMIT 1
        """,
        (int(teaching_group_id), semester, phase),
    ).fetchone()
    if existing:
        eid = int(_row_dict(existing)["id"])
        cur.execute(
            """
            UPDATE grade_entry_locks
            SET is_open=?, set_by=?, set_at=?, note=?
            WHERE id=?
            """,
            (1 if is_open else 0, set_by, now, note or "", eid),
        )
    else:
        cur.execute(
            """
            INSERT INTO grade_entry_locks
                (teaching_group_id, semester, phase, is_open, set_by, set_at, note)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (int(teaching_group_id), semester, phase, 1 if is_open else 0, set_by, now, note or ""),
        )
    conn.commit()
    return get_grade_entry_lock(conn, teaching_group_id, semester, phase)


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
    rep["instructor_comments"] = (rep.get("instructor_comments") or "").strip()
    rep["instructor_recommendations"] = (rep.get("instructor_recommendations") or "").strip()
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
    try:
        refs = cur.execute(
            """
            SELECT id, ref_type, title, publication_date, url_or_isbn, sort_order
            FROM course_delivery_references
            WHERE report_id = ?
            ORDER BY sort_order, id
            """,
            (int(rep["id"]),),
        ).fetchall()
        rep["references"] = [_row_dict(r) for r in refs or []]
    except Exception:
        rep["references"] = []
    try:
        methods = cur.execute(
            """
            SELECT id, method_label, weight_pct, notes, sort_order
            FROM course_delivery_assessment_methods
            WHERE report_id = ?
            ORDER BY sort_order, id
            """,
            (int(rep["id"]),),
        ).fetchall()
        rep["assessment_methods"] = [_row_dict(m) for m in methods or []]
    except Exception:
        rep["assessment_methods"] = []
    topics_by_id = {
        int(it.get("topic_id") or 0): {"topic_title": it.get("topic_title")}
        for it in rep["items"]
    }
    rep["incomplete_topics"] = list_incomplete_topics(rep["items"], topics_by_id)
    rep["incomplete_threshold"] = INCOMPLETE_PCT_THRESHOLD
    book_count = sum(
        1
        for r in rep["references"]
        if (r.get("ref_type") or "").strip().lower() in (REF_TYPE_BOOK, "كتاب")
    )
    rep["book_reference_count"] = book_count
    rep["min_book_references"] = MIN_BOOK_REFERENCES
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
    """
    بوابة فتح مسودة الدرجات:
    - فتح/إقفال يدوي من رئيس القسم لكل مقرر ومرحلة
    - لا يعتمد على نسبة إنجاز المفردات
    - مسودة النهائي تتطلب اعتماد مسودة الجزئي (مسار النشر كما هو)
    """
    policy = get_gate_policy(conn, department_id, semester)
    baseline = get_active_baseline(conn, course_name)
    lock = get_grade_entry_lock(conn, teaching_group_id, semester, phase)
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
                "lock": lock,
                "report": rep,
                "baseline_status": baseline.get("status") if baseline else "missing",
                "partial_min_pct": policy["partial_min_pct"],
                "final_min_pct": policy["final_min_pct"],
                "overall_pct": rep.get("overall_pct") if rep else None,
            }

    if not lock.get("is_open"):
        return {
            "unlocked": False,
            "reason": "إدخال الدرجات مغلق لهذا المقرر — بانتظار فتح رئيس القسم",
            "lock": lock,
            "report": rep,
            "baseline_status": baseline.get("status") if baseline else "missing",
            "baseline_id": int(baseline["id"]) if baseline else None,
            "overall_pct": rep.get("overall_pct") if rep else None,
            "report_status": rep.get("status") if rep else None,
            "partial_min_pct": policy["partial_min_pct"],
            "final_min_pct": policy["final_min_pct"],
        }

    return {
        "unlocked": True,
        "reason": "",
        "lock": lock,
        "report": rep,
        "baseline_id": int(baseline["id"]) if baseline else None,
        "baseline_status": baseline.get("status") if baseline else "missing",
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
    reuse_active = bool(data.get("reuse_active", True))
    if not course_name:
        return jsonify({"status": "error", "message": "course_name مطلوب"}), 400
    instructor_id = session.get("instructor_id")
    actor = (session.get("user") or "").strip()
    with get_connection() as conn:
        ensure_course_delivery_schema(conn)
        cur = conn.cursor()
        sem = _current_semester_label(conn)
        active = get_active_baseline(conn, course_name)
        # إعادة استخدام المفردات المعتمدة للمقرر إن لم تُرسل قائمة جديدة
        if (not topics) and reuse_active and active and active.get("topics"):
            topics = [
                {"sort_order": t.get("sort_order"), "topic_title": t.get("topic_title")}
                for t in active["topics"]
            ]
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
    return jsonify({"status": "ok", "baseline": bl, "reused_from_active": bool(active and reuse_active)}), 200


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

        ctx = _resolve_baseline_teaching_context(conn, bl)
        notify_baseline_submitted(
            conn,
            course_name=str(bl.get("course_name") or ""),
            baseline_id=baseline_id,
            teaching_group_id=ctx.get("teaching_group_id"),
            section_id=ctx.get("section_id"),
            semester=str(ctx.get("semester") or ""),
        )
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
        ctx = _resolve_baseline_teaching_context(conn, bl)
        denied = _guard_hod_course(
            conn,
            str(bl.get("course_name") or ""),
            teaching_group_id=ctx.get("teaching_group_id"),
            section_id=ctx.get("section_id"),
            semester=str(ctx.get("semester") or ""),
        )
        if denied:
            return denied
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
    return jsonify({"status": "ok", "report": rep, "baseline": baseline, "semester": sem,
                    "incomplete_threshold": INCOMPLETE_PCT_THRESHOLD,
                    "min_book_references": MIN_BOOK_REFERENCES}), 200


@course_delivery_bp.route("/report", methods=["POST"])
@role_required("instructor", "head_of_department")
def api_report_save():
    data = request.get_json(force=True) or {}
    tgid = int(data.get("teaching_group_id") or 0)
    phase = (data.get("phase") or PHASE_PARTIAL).strip()
    items = data.get("items") or []
    extra_topics = data.get("extra_topics") or []
    references = data.get("references") or []
    assessment_methods = data.get("assessment_methods") or []
    instructor_comments = (data.get("instructor_comments") or "").strip()
    instructor_recommendations = (data.get("instructor_recommendations") or "").strip()
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
            """
            UPDATE course_delivery_reports
            SET overall_pct=?, instructor_comments=?, instructor_recommendations=?, updated_at=?
            WHERE id=?
            """,
            (overall, instructor_comments, instructor_recommendations, now, rid),
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
        # مفردات خارج المقرر: مسموح في الجزئي والنهائي
        cur.execute("DELETE FROM course_delivery_extra_topics WHERE report_id=?", (rid,))
        for ex in extra_topics:
            title = (ex.get("title") or "").strip()
            if not title:
                continue
            cur.execute(
                "INSERT INTO course_delivery_extra_topics (report_id, title, reason) VALUES (?, ?, ?)",
                (rid, title, (ex.get("reason") or "").strip()),
            )
        _replace_report_references(conn, rid, references)
        _replace_assessment_methods(conn, rid, assessment_methods)
        conn.commit()
        rep = get_delivery_report(conn, tgid, sem, phase)
    return jsonify({
        "status": "ok",
        "report": rep,
        "overall_pct": overall,
        "incomplete_threshold": INCOMPLETE_PCT_THRESHOLD,
        "min_book_references": MIN_BOOK_REFERENCES,
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
        row = cur.execute("SELECT * FROM course_delivery_reports WHERE id=?", (report_id,)).fetchone()
        if not row:
            return jsonify({"status": "error", "message": "not found"}), 404
        base = _row_dict(row)
        phase = base.get("phase")
        tgid = int(base["teaching_group_id"])
        sem = str(base.get("semester") or "")
        rep = get_delivery_report(conn, tgid, sem, str(phase or PHASE_PARTIAL))
        if not rep:
            return jsonify({"status": "error", "message": "not found"}), 404
        from backend.services import teaching_groups as tg

        g = tg.get_teaching_group(conn, tgid)
        dept_id = int(g.get("department_id") or 0) if g else None
        policy = get_gate_policy(conn, dept_id, sem)
        min_pct = policy["partial_min_pct"] if phase == PHASE_PARTIAL else policy["final_min_pct"]
        overall = float(rep.get("overall_pct") or 0)
        require_books = phase == PHASE_FINAL
        err = validate_quality_report_for_submit(
            rep,
            require_books=require_books,
            require_assessments=require_books,
        )
        if err:
            return jsonify({"status": "error", "message": err}), 400
        now = _now_iso()
        # حالات المتابعة لرئيس القسم فقط — لا تفتح الدرجات
        if overall >= min_pct:
            st = "auto_approved"
        else:
            if not reason:
                return jsonify({
                    "status": "error",
                    "message": f"النسبة {overall}% أقل من حد المتابعة {min_pct}% — التبرير مطلوب لعلم رئيس القسم",
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
            teaching_group_id=tgid,
        )
    return jsonify({
        "status": "ok",
        "report_status": st,
        "overall_pct": overall,
        "note": "إرسال التقرير للمتابعة — فتح الدرجات قرار منفصل لرئيس القسم",
    }), 200


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
        rep_row = cur.execute(
            "SELECT * FROM course_delivery_reports WHERE id=? AND status=?",
            (report_id, "gate_pending"),
        ).fetchone()
        if not rep_row:
            return jsonify({"status": "error", "message": "not found"}), 404
        rep = _row_dict(rep_row)
        denied = _guard_hod_course(
            conn,
            str(rep.get("course_name") or ""),
            teaching_group_id=rep.get("teaching_group_id"),
            semester=str(rep.get("semester") or ""),
        )
        if denied:
            return denied
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
    with get_connection() as conn:
        dept_id = _delivery_department_scope_id(conn)
        ensure_course_delivery_schema(conn)
        cur = conn.cursor()
        sem = _current_semester_label(conn)
        actor = (session.get("user") or session.get("username") or "").strip()
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
            ctx = _resolve_baseline_teaching_context(conn, item)
            if not hod_may_operate_on_course(
                conn,
                actor,
                str(item.get("course_name") or ""),
                teaching_group_id=ctx.get("teaching_group_id"),
                section_id=ctx.get("section_id"),
                semester=str(ctx.get("semester") or sem),
            ):
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
                WHERE d.semester = ? AND d.status = 'Submitted'
                ORDER BY d.submitted_at DESC, d.course_name
            """
            rows = cur.execute(gd_sql, (sem,)).fetchall()
            gd_out = [_row_dict(r) for r in rows or []]
            _enrich_drafts_with_group_labels(conn, gd_out)
            gd_out = filter_items_for_course_hod_scope(conn, actor, gd_out)

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
    with get_connection() as conn:
        dept_id = _delivery_department_scope_id(conn)
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
    with get_connection() as conn:
        dept_id = _delivery_department_scope_id(conn)
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


@course_delivery_bp.route("/hod/progress_board", methods=["GET"])
@role_required("head_of_department", "admin_main", "admin", "system_admin", "college_dean", "academic_vice_dean")
def api_hod_progress_board():
    """لوحة نسب الإنجاز / الفجوات / أقفال إدخال الدرجات."""
    with get_connection() as conn:
        ensure_course_delivery_schema(conn)
        sem = (request.args.get("semester") or "").strip() or _current_semester_label(conn)
        college_wide = _is_college_leadership_or_admin() and request.args.get("all_departments") in (
            "1", "true", "yes",
        )
        dept_id = None if college_wide else _delivery_department_scope_id(conn)
        rows = build_progress_board_rows(conn, semester=sem, department_id=dept_id)
        low = sum(1 for r in rows if (r.get("overall_pct") is not None and float(r["overall_pct"]) < 50))
        unlocked_partial = sum(1 for r in rows if r.get("partial_lock_open"))
        unlocked_final = sum(1 for r in rows if r.get("final_lock_open"))
    return jsonify({
        "status": "ok",
        "semester": sem,
        "department_id": dept_id,
        "college_wide": bool(college_wide),
        "summary": {
            "groups_total": len(rows),
            "low_completion": low,
            "partial_open": unlocked_partial,
            "final_open": unlocked_final,
        },
        "rows": rows,
        "incomplete_threshold": INCOMPLETE_PCT_THRESHOLD,
        "min_book_references": MIN_BOOK_REFERENCES,
    }), 200


@course_delivery_bp.route("/hod/grade_locks", methods=["GET", "POST"])
@role_required("head_of_department", "admin_main", "admin", "system_admin")
def api_hod_grade_locks():
    """فتح/إقفال إدخال الدرجات لكل مقرر ومرحلة — يدوياً من رئيس القسم."""
    with get_connection() as conn:
        ensure_course_delivery_schema(conn)
        sem = (request.args.get("semester") or "").strip() or _current_semester_label(conn)
        if request.method == "GET":
            dept_id = _delivery_department_scope_id(conn)
            rows = build_progress_board_rows(conn, semester=sem, department_id=dept_id)
            return jsonify({"status": "ok", "semester": sem, "rows": rows}), 200

        data = request.get_json(force=True) or {}
        items = data.get("locks") or []
        if not items and data.get("teaching_group_id"):
            items = [data]
        actor = (session.get("user") or "").strip()
        results = []
        for it in items:
            tgid = int(it.get("teaching_group_id") or 0)
            phase = (it.get("phase") or PHASE_PARTIAL).strip()
            if phase not in (PHASE_PARTIAL, PHASE_FINAL) or not tgid:
                continue
            is_open = bool(it.get("is_open"))
            note = (it.get("note") or "").strip()
            from backend.services import teaching_groups as tg

            g = tg.get_teaching_group(conn, tgid)
            if not g:
                continue
            denied = _guard_hod_course(
                conn,
                str(g.get("course_name") or ""),
                teaching_group_id=tgid,
                semester=sem,
            )
            if denied and (session.get("user_role") or "").strip() == "head_of_department":
                return denied
            lock = set_grade_entry_lock(
                conn,
                teaching_group_id=tgid,
                semester=sem,
                phase=phase,
                is_open=is_open,
                set_by=actor,
                note=note,
            )
            results.append(lock)
            if is_open:
                from backend.services.course_workflow import notify_instructor

                ph = "الجزئي" if phase == PHASE_PARTIAL else "النهائي"
                notify_instructor(
                    conn,
                    int(g.get("instructor_id") or 0),
                    title=f"فُتح إدخال درجات {ph}: {g.get('course_name')}",
                    body="يمكنك إنشاء/تعبئة مسودة الدرجات من مقرراتي.",
                )
        return jsonify({"status": "ok", "locks": results, "count": len(results)}), 200


@course_delivery_bp.route("/hod/warn_instructor", methods=["POST"])
@role_required("head_of_department", "admin_main", "admin", "system_admin", "college_dean", "academic_vice_dean")
def api_hod_warn_instructor():
    """تنبيه يدوي للأستاذ بخصوص تقرير المقرر / الإنجاز."""
    data = request.get_json(force=True) or {}
    tgid = int(data.get("teaching_group_id") or 0)
    message = (data.get("message") or "").strip()
    if not tgid:
        return jsonify({"status": "error", "message": "teaching_group_id مطلوب"}), 400
    with get_connection() as conn:
        from backend.services import teaching_groups as tg
        from backend.services.course_workflow import notify_instructor

        g = tg.get_teaching_group(conn, tgid)
        if not g:
            return jsonify({"status": "error", "message": "مجموعة تدريس غير موجودة"}), 404
        if session.get("user_role") == "head_of_department":
            denied = _guard_hod_course(
                conn,
                str(g.get("course_name") or ""),
                teaching_group_id=tgid,
                semester=str(g.get("semester") or ""),
            )
            if denied:
                return denied
        default_msg = (
            f"يُرجى استكمال تقرير المقرر الدراسي وبيان نسب الإنجاز لمقرر «{g.get('course_name')}» "
            f"قبل موعد الامتحانات. راجع: /course_delivery_page?teaching_group_id={tgid}"
        )
        body = message or default_msg
        notify_instructor(
            conn,
            int(g.get("instructor_id") or 0),
            title=f"تنبيه رئيس القسم — تقرير المقرر: {g.get('course_name')}",
            body=body,
        )
    return jsonify({"status": "ok"}), 200


@course_delivery_bp.route("/college/reports_overview", methods=["GET"])
@role_required("college_dean", "academic_vice_dean", "admin_main", "admin", "system_admin")
def api_college_reports_overview():
    """اطلاع الوكيل/العميد على تقارير جودة المقررات لكل الأقسام."""
    with get_connection() as conn:
        ensure_course_delivery_schema(conn)
        sem = (request.args.get("semester") or "").strip() or _current_semester_label(conn)
        rows = build_progress_board_rows(conn, semester=sem, department_id=None)
        by_dept: dict[str, dict] = {}
        for r in rows:
            did = str(r.get("department_id") or "بدون قسم")
            slot = by_dept.setdefault(
                did,
                {
                    "department_id": r.get("department_id"),
                    "groups": 0,
                    "avg_pct_sum": 0.0,
                    "avg_pct_n": 0,
                    "low_completion": 0,
                    "missing_books": 0,
                    "partial_submitted": 0,
                    "final_submitted": 0,
                },
            )
            slot["groups"] += 1
            if r.get("overall_pct") is not None:
                slot["avg_pct_sum"] += float(r["overall_pct"])
                slot["avg_pct_n"] += 1
            if r.get("overall_pct") is not None and float(r["overall_pct"]) < INCOMPLETE_PCT_THRESHOLD:
                slot["low_completion"] += 1
            if not r.get("books_ok"):
                slot["missing_books"] += 1
            if r.get("partial_status") not in ("missing", "draft"):
                slot["partial_submitted"] += 1
            if r.get("final_status") not in ("missing", "draft"):
                slot["final_submitted"] += 1
        dept_summary = []
        for slot in by_dept.values():
            n = slot.pop("avg_pct_n")
            s = slot.pop("avg_pct_sum")
            slot["avg_overall_pct"] = round(s / n, 1) if n else None
            dept_summary.append(slot)
    return jsonify({
        "status": "ok",
        "semester": sem,
        "summary": {
            "groups_total": len(rows),
            "departments": len(dept_summary),
            "low_completion": sum(1 for r in rows if r.get("overall_pct") is not None and float(r["overall_pct"]) < 50),
            "missing_books": sum(1 for r in rows if not r.get("books_ok")),
        },
        "by_department": dept_summary,
        "rows": rows,
    }), 200
