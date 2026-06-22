"""تقييم الطالب للمقرر والأستاذ — الاعتماد البرامجي."""

from __future__ import annotations

import datetime
import logging

from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for

from backend.core.auth import login_required, role_required, _normalize_role
from backend.core.faculty_axes import normalize_instructor_name
from backend.database.database import fetch_table_columns, is_postgresql, schedule_pk_column, table_exists
from backend.services import teaching_groups as tg_svc
from backend.services.evaluation_survey import (
    insert_evaluation_with_answers,
    likert_labels_ar,
    likert_scale_context,
    list_survey_questions,
    parse_answers_payload,
)
from backend.services.utilities import get_connection, schedule_semester_matches_current_term
from backend.services.quality_metrics import term_label_from_conn

logger = logging.getLogger(__name__)

course_evaluations_bp = Blueprint("course_evaluations", __name__)


def _student_id_from_session() -> str | None:
    role = _normalize_role((session.get("user_role") or "").strip())
    if role != "student":
        return None
    sid = (session.get("student_id") or session.get("user") or "").strip()
    return sid or None


def _safe_int(val, default: int | None = None) -> int | None:
    try:
        v = int(val)
        return v if v > 0 else default
    except (TypeError, ValueError):
        return default


def _schedule_section_id_expr(conn) -> str:
    """تعبير SQL لمعرّف الشعبة (يدعم id الفارغ في SQLite عبر rowid)."""
    pk = schedule_pk_column(conn)
    if not is_postgresql() and pk == "id":
        cols = {c.lower() for c in fetch_table_columns(conn, "schedule")}
        if "id" in cols:
            return "COALESCE(sch.id, sch.rowid)"
    return f"sch.{pk}"


def _instructor_id_by_name_map(cur) -> dict[str, int]:
    """خريطة اسم أستاذ مُطبَّع → معرّف instructors (للجدول القديم بلا instructor_id)."""
    out: dict[str, int] = {}
    if not table_exists(cur.connection, "instructors"):
        return out
    for row in cur.execute("SELECT id, COALESCE(name,'') FROM instructors").fetchall():
        iid = _safe_int(row[0] if not hasattr(row, "keys") else row["id"])
        name = (row[1] if not hasattr(row, "keys") else row[1]) or ""
        norm = normalize_instructor_name(name)
        if iid and norm and norm not in out:
            out[norm] = iid
    return out


def _resolve_schedule_instructor_id(
    instructor_id: int,
    instructor_name: str,
    name_map: dict[str, int],
) -> int:
    if instructor_id > 0:
        return instructor_id
    norm = normalize_instructor_name(instructor_name)
    return int(name_map.get(norm) or 0)


def _row_to_section_dict(r) -> dict | None:
    if hasattr(r, "keys"):
        d = dict(r)
    else:
        d = {
            "section_id": r[0],
            "course_name": r[1],
            "instructor_name": r[2],
            "instructor_id": r[3],
            "semester": r[4],
        }
    sid = _safe_int(d.get("section_id"))
    if not sid:
        return None
    d["section_id"] = sid
    d["instructor_id"] = int(d.get("instructor_id") or 0)
    return d


def _student_evaluable_sections_legacy(conn, student_id: str, semester: str) -> list[dict]:
    if not table_exists(conn, "course_evaluations"):
        logger.warning("course_evaluations table missing — run ensure_tables / restart app")
    sid_expr = _schedule_section_id_expr(conn)
    cur = conn.cursor()
    name_map = _instructor_id_by_name_map(cur)
    rows = cur.execute(
        f"""
        SELECT DISTINCT {sid_expr} AS section_id,
               COALESCE(sch.course_name,'') AS course_name,
               COALESCE(sch.instructor,'') AS instructor_name,
               COALESCE(sch.instructor_id, 0) AS instructor_id,
               COALESCE(sch.semester,'') AS semester
        FROM registrations r
        JOIN schedule sch ON lower(trim(sch.course_name)) = lower(trim(r.course_name))
        WHERE r.student_id = ?
          AND (
                COALESCE(sch.instructor_id, 0) > 0
                OR TRIM(COALESCE(sch.instructor, '')) <> ''
              )
        ORDER BY course_name
        """,
        (student_id,),
    ).fetchall()

    term = (semester or "").strip()
    seen_sections: set[int] = set()
    seen_course_inst: set[tuple[str, int]] = set()
    out: list[dict] = []
    for r in rows:
        item = _row_to_section_dict(r)
        if not item:
            continue
        iid = _resolve_schedule_instructor_id(
            int(item.get("instructor_id") or 0),
            str(item.get("instructor_name") or ""),
            name_map,
        )
        if not iid:
            continue
        item["instructor_id"] = iid
        sch_sem = (item.get("semester") or "").strip()
        if sch_sem and term and not schedule_semester_matches_current_term(sch_sem, term):
            continue
        sec_id = int(item["section_id"])
        if sec_id in seen_sections:
            continue
        course_key = (str(item.get("course_name") or "").strip().lower(), iid)
        if course_key in seen_course_inst:
            continue
        seen_sections.add(sec_id)
        seen_course_inst.add(course_key)
        item["semester"] = term or sch_sem
        item["teaching_group_id"] = None
        out.append(item)
    return out


def _student_evaluable_sections(conn, student_id: str, semester: str) -> list[dict]:
    """
    مقررات قابلة للتقييم.
    يفضّل مجموعات التدريس عند توفرها؛ وإلا المسار القديم (section_id).
    """
    sem = (semester or "").strip()
    if tg_svc.semester_has_teaching_groups(conn, sem):
        groups = tg_svc.list_student_evaluable_groups(conn, student_id, sem)
        if groups:
            return groups
    return _student_evaluable_sections_legacy(conn, student_id, sem)


def _find_evaluable_item(
    sections: list[dict],
    *,
    section_id: int | None = None,
    teaching_group_id: int | None = None,
) -> dict | None:
    if teaching_group_id and int(teaching_group_id) > 0:
        return next(
            (s for s in sections if int(s.get("teaching_group_id") or 0) == int(teaching_group_id)),
            None,
        )
    if section_id and int(section_id) > 0:
        return next(
            (s for s in sections if int(s.get("section_id") or 0) == int(section_id)),
            None,
        )
    return None


def list_pending_course_evaluations(
    conn,
    student_id: str,
    *,
    semester: str | None = None,
) -> list[dict]:
    """مقررات الطالب التي لم يُقيّمها بعد — للعرض في hub الاستبيانات."""
    sid = (student_id or "").strip()
    if not sid:
        return []
    sem = (semester or "").strip() or term_label_from_conn(conn)
    sections = _student_evaluable_sections(conn, sid, sem)
    cur = conn.cursor()
    pending: list[dict] = []
    for s in sections:
        tgid = int(s.get("teaching_group_id") or 0)
        sec_id = int(s.get("section_id") or 0)
        if _already_evaluated(
            conn,
            cur,
            sid,
            sem,
            section_id=sec_id or None,
            teaching_group_id=tgid or None,
        ):
            continue
        cname = (s.get("course_name") or "").strip() or "—"
        iname = (s.get("instructor_name") or "").strip()
        label = (s.get("display_label") or "").strip()
        title = f"تقييم مقرر: {label or cname}"
        if iname and iname not in title:
            title += f" — {iname}"
        fill_url = (
            f"/students/evaluations/form/tg/{tgid}"
            if tgid > 0
            else f"/students/evaluations/form/{sec_id}"
        )
        pending.append(
            {
                "code": "student_course",
                "title_ar": title,
                "semester": sem,
                "fill_url": fill_url,
                "pending_kind": "course_eval",
                "section_id": sec_id or None,
                "teaching_group_id": tgid or None,
                "course_name": cname,
                "instructor_name": iname,
                "display_label": label or None,
            }
        )
    return pending


def _already_evaluated(
    conn,
    cur,
    student_id: str,
    semester: str,
    *,
    section_id: int | None = None,
    teaching_group_id: int | None = None,
) -> bool:
    if not table_exists(conn, "course_evaluations"):
        return False
    sem = " ".join((semester or "").split()).strip()
    ce_cols = {c.lower() for c in fetch_table_columns(conn, "course_evaluations")}
    tgid = int(teaching_group_id or 0)

    def _sem_match(row_sem: str) -> bool:
        rs = " ".join((row_sem or "").split()).strip()
        if not sem or not rs:
            return False
        if rs == sem:
            return True
        return schedule_semester_matches_current_term(rs, sem)

    if tgid > 0 and "teaching_group_id" in ce_cols:
        rows = cur.execute(
            """
            SELECT semester FROM course_evaluations
            WHERE student_id = ? AND teaching_group_id = ?
            """,
            (student_id, tgid),
        ).fetchall()
        for row in rows:
            row_sem = row[0] if not hasattr(row, "keys") else row.get("semester")
            if _sem_match(str(row_sem or "")):
                return True
    sid = int(section_id or 0)
    if sid > 0:
        rows = cur.execute(
            """
            SELECT semester FROM course_evaluations
            WHERE student_id = ? AND section_id = ?
            """,
            (student_id, sid),
        ).fetchall()
        for row in rows:
            row_sem = row[0] if not hasattr(row, "keys") else row.get("semester")
            if _sem_match(str(row_sem or "")):
                return True
    return False


def _render_evaluation_form(conn, sid: str, match: dict, *, section_id: int, teaching_group_id: int | None):
    sem = term_label_from_conn(conn)
    cur = conn.cursor()
    tgid = int(teaching_group_id or match.get("teaching_group_id") or 0)
    if _already_evaluated(
        conn,
        cur,
        sid,
        sem,
        section_id=section_id,
        teaching_group_id=tgid or None,
    ):
        return render_template(
            "student_course_evaluation.html",
            error="تم إرسال تقييمك لهذا المقرر مسبقاً.",
            course=match,
            already_done=True,
        )
    questions = list_survey_questions(conn, active_only=True)
    if not questions:
        return render_template(
            "student_course_evaluation.html",
            error="لم يُضبط استبيان التقييم بعد. تواصل مع الإدارة.",
            course=match,
        )
    return render_template(
        "student_course_evaluation.html",
        course=match,
        section_id=section_id,
        teaching_group_id=tgid or None,
        semester=sem,
        questions=questions,
        likert_options=likert_labels_ar(),
        likert_labels=likert_labels_ar(),
        scale_guide_note="اختر الرقم الذي يعبّر عن تجربتك مع المقرر والأستاذ.",
        **likert_scale_context(questions),
    )


@course_evaluations_bp.route("/")
@login_required
@role_required("student")
def evaluations_home():
    """إعادة توجيه — قائمة التقييمات مدمجة في hub الاستبيانات."""
    return redirect(url_for("academic_quality.surveys_hub"))


@course_evaluations_bp.route("/form/<int:section_id>")
@login_required
@role_required("student")
def evaluation_form(section_id: int):
    sid = _student_id_from_session()
    if not sid:
        return redirect(url_for("login_page"))
    try:
        with get_connection() as conn:
            sem = term_label_from_conn(conn)
            sections = _student_evaluable_sections(conn, sid, sem)
            match = _find_evaluable_item(sections, section_id=section_id)
            if not match:
                return render_template(
                    "student_course_evaluation.html",
                    error="هذا المقرر غير مسجّل لديك في الفصل الحالي.",
                    course=None,
                )
            return _render_evaluation_form(
                conn,
                sid,
                match,
                section_id=section_id,
                teaching_group_id=int(match.get("teaching_group_id") or 0) or None,
            )
    except Exception:
        logger.exception("evaluation_form failed")
        return render_template(
            "student_course_evaluation.html",
            error="حدث خطأ أثناء تحميل الاستبيان.",
            course=None,
        )


@course_evaluations_bp.route("/form/tg/<int:teaching_group_id>")
@login_required
@role_required("student")
def evaluation_form_teaching_group(teaching_group_id: int):
    sid = _student_id_from_session()
    if not sid:
        return redirect(url_for("login_page"))
    try:
        with get_connection() as conn:
            sem = term_label_from_conn(conn)
            sections = _student_evaluable_sections(conn, sid, sem)
            match = _find_evaluable_item(sections, teaching_group_id=teaching_group_id)
            if not match:
                return render_template(
                    "student_course_evaluation.html",
                    error="هذه المجموعة غير مسجّلة لديك في الفصل الحالي.",
                    course=None,
                )
            sec_id = int(match.get("section_id") or 0) or teaching_group_id
            return _render_evaluation_form(
                conn,
                sid,
                match,
                section_id=sec_id,
                teaching_group_id=teaching_group_id,
            )
    except Exception:
        logger.exception("evaluation_form_teaching_group failed")
        return render_template(
            "student_course_evaluation.html",
            error="حدث خطأ أثناء تحميل الاستبيان.",
            course=None,
        )


@course_evaluations_bp.route("/submit", methods=["POST"])
@login_required
@role_required("student")
def submit_evaluation():
    sid = _student_id_from_session()
    if not sid:
        return jsonify({"status": "error", "message": "غير مصرح"}), 403
    data = request.get_json(force=True) if request.is_json else request.form
    data = data or {}
    section_id = _safe_int(data.get("section_id"))
    teaching_group_id = _safe_int(data.get("teaching_group_id"))
    instructor_id = _safe_int(data.get("instructor_id"))
    if not section_id and not teaching_group_id:
        return jsonify({"status": "error", "message": "معرّف المقرر غير صالح"}), 400
    if not instructor_id:
        return jsonify({"status": "error", "message": "instructor_id غير صالح"}), 400

    comments = (data.get("comments") or "").strip()
    try:
        with get_connection() as conn:
            if not table_exists(conn, "course_evaluations"):
                return jsonify(
                    {
                        "status": "error",
                        "message": "جدول التقييمات غير موجود — أعد تشغيل الخادم لإنشاء الجداول",
                        "code": "SCHEMA_MISSING",
                    }
                ), 503
            active_questions = list_survey_questions(conn, active_only=True)
            if not active_questions:
                return jsonify(
                    {"status": "error", "message": "لا توجد بنود نشطة في الاستبيان"},
                    503,
                )
            try:
                answers = parse_answers_payload(data, active_questions)
            except ValueError as ve:
                return jsonify({"status": "error", "message": str(ve)}), 400
            sem = (data.get("semester") or "").strip() or term_label_from_conn(conn)
            sections = _student_evaluable_sections(conn, sid, sem)
            match = _find_evaluable_item(
                sections,
                section_id=section_id,
                teaching_group_id=teaching_group_id,
            )
            if not match:
                return jsonify({"status": "error", "message": "المقرر غير مسجّل لديك"}), 403
            if int(match.get("instructor_id") or 0) != instructor_id:
                return jsonify({"status": "error", "message": "بيانات الأستاذ غير متطابقة"}), 400
            sec_id = int(match.get("section_id") or section_id or 0)
            tgid = int(match.get("teaching_group_id") or teaching_group_id or 0) or None
            cur = conn.cursor()
            if _already_evaluated(
                conn,
                cur,
                sid,
                sem,
                section_id=sec_id or None,
                teaching_group_id=tgid,
            ):
                return jsonify({"status": "error", "message": "تم التقييم مسبقاً"}), 409
            course_name = (match.get("course_name") or "").strip()
            insert_evaluation_with_answers(
                conn,
                student_id=sid,
                section_id=sec_id,
                teaching_group_id=tgid,
                course_name=course_name,
                instructor_id=instructor_id,
                semester=sem,
                comments=comments,
                answers=answers,
                active_questions=active_questions,
            )
            conn.commit()
    except Exception as exc:
        logger.exception("submit_evaluation failed")
        return jsonify({"status": "error", "message": str(exc), "code": "SAVE_FAILED"}), 500

    if request.is_json:
        return jsonify({"status": "ok"})
    return redirect(url_for("academic_quality.surveys_hub"))


@course_evaluations_bp.route("/api/pending")
@login_required
@role_required("student")
def pending_api():
    sid = _student_id_from_session()
    if not sid:
        return jsonify({"status": "error"}), 403
    with get_connection() as conn:
        sem = term_label_from_conn(conn)
        pending = list_pending_course_evaluations(conn, sid, semester=sem)
    return jsonify({"status": "ok", "semester": sem, "pending": pending, "count": len(pending)})
