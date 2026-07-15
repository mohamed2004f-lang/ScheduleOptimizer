"""
إشعارات وتنسيق سير عمل تقرير تنفيذ المقرر (8.8).
"""
from __future__ import annotations

import logging
from typing import Any

from backend.core.faculty_axes import (
    AUTO_DERIVED_AXIS_KEYS,
    FACULTY_AXIS_LABELS_AR,
    is_editable_axis_key,
    visible_axis_keys,
)
from backend.services.utilities import create_notification, get_connection

logger = logging.getLogger(__name__)


def username_for_instructor(conn, instructor_id: int | None) -> str | None:
    if not instructor_id:
        return None
    row = conn.cursor().execute(
        "SELECT username FROM users WHERE instructor_id = ? AND COALESCE(is_active, 1) = 1 LIMIT 1",
        (int(instructor_id),),
    ).fetchone()
    if not row:
        return None
    return str(row[0] if not hasattr(row, "keys") else row["username"] or row[0] or "").strip() or None


def usernames_for_department_hods(conn, department_id: int | None) -> list[str]:
    cur = conn.cursor()
    if department_id is not None:
        rows = cur.execute(
            """
            SELECT username FROM users
            WHERE role = 'head_of_department' AND department_id = ?
              AND COALESCE(is_active, 1) = 1
            """,
            (int(department_id),),
        ).fetchall()
    else:
        rows = cur.execute(
            """
            SELECT username FROM users
            WHERE role IN ('head_of_department', 'admin_main', 'admin')
              AND COALESCE(is_active, 1) = 1
            """
        ).fetchall()
    out: list[str] = []
    for r in rows or []:
        u = str(r[0] if not hasattr(r, "keys") else r["username"] or r[0] or "").strip()
        if u and u not in out:
            out.append(u)
    return out


def department_id_for_course(
    conn,
    course_name: str,
    *,
    teaching_group_id: int | None = None,
    section_id: int | None = None,
    semester: str | None = None,
) -> int | None:
    """القسم المختص بالمقرر — سياق التدريس وليس قسم منزل الأستاذ."""
    from backend.core.department_scope_policy import resolve_course_responsible_department_id

    return resolve_course_responsible_department_id(
        conn,
        course_name,
        teaching_group_id=teaching_group_id,
        section_id=section_id,
        semester=semester,
    )


def notify_users(usernames: list[str], *, title: str, body: str = "") -> None:
    for u in usernames:
        try:
            create_notification(u, title, body or "")
        except Exception as exc:
            logger.warning("notify %s failed: %s", u, exc)


def notify_department_hods(conn, department_id: int | None, *, title: str, body: str = "") -> None:
    notify_users(usernames_for_department_hods(conn, department_id), title=title, body=body)


def notify_instructor(conn, instructor_id: int | None, *, title: str, body: str = "") -> None:
    u = username_for_instructor(conn, instructor_id)
    if u:
        notify_users([u], title=title, body=body)


def notify_baseline_submitted(
    conn,
    *,
    course_name: str,
    baseline_id: int,
    teaching_group_id: int | None = None,
    section_id: int | None = None,
    semester: str | None = None,
) -> None:
    dept_id = department_id_for_course(
        conn,
        course_name,
        teaching_group_id=teaching_group_id,
        section_id=section_id,
        semester=semester,
    )
    notify_department_hods(
        conn,
        dept_id,
        title=f"قائمة مفردات بانتظار الاعتماد: {course_name}",
        body=f"راجع قائمة المفردات (#{baseline_id}) من لوحة اعتماد رئيس القسم.",
    )


def notify_baseline_reviewed(
    conn, *, course_name: str, action: str, created_by: str | None = None, instructor_id: int | None = None
) -> None:
    if action == "approve":
        title = f"اعتُمدت قائمة مفردات {course_name}"
        body = "يمكنك متابعة تقرير الجزئي من صفحة تقرير المقرر."
    else:
        title = f"أُرجعت قائمة مفردات {course_name}"
        body = "راجع ملاحظات رئيس القسم وأعد الإرسال."
    if created_by:
        notify_users([created_by.strip()], title=title, body=body)
    notify_instructor(conn, instructor_id, title=title, body=body)


def notify_report_submitted(
    conn,
    *,
    course_name: str,
    phase: str,
    report_status: str,
    department_id: int | None,
    teaching_group_id: int,
) -> None:
    ph = "الجزئي" if phase == "partial" else "النهائي"
    if report_status == "gate_pending":
        notify_department_hods(
            conn,
            department_id,
            title=f"تقرير {ph} دون الحد: {course_name}",
            body=f"راجع التبرير واعتمد من لوحة اعتماد رئيس القسم (مجموعة #{teaching_group_id}).",
        )


def notify_report_gate_reviewed(conn, *, course_name: str, phase: str, action: str, instructor_id: int) -> None:
    ph = "الجزئي" if phase == "partial" else "النهائي"
    if action == "approve":
        title = f"وُوفق على تقرير {ph}: {course_name}"
        body = "يمكنك متابعة الخطوة التالية في تقرير تنفيذ المقرر."
    else:
        title = f"رُفض تقرير {ph}: {course_name}"
        body = "راجع ملاحظات رئيس القسم وأعد التقرير."
    notify_instructor(conn, instructor_id, title=title, body=body)


def notify_grade_draft_submitted(
    conn, *, course_name: str, draft_phase: str, department_id: int | None, draft_id: int
) -> None:
    ph = {"partial": "جزئي", "final": "نهائي"}.get(str(draft_phase or "").lower(), "درجات")
    notify_department_hods(
        conn,
        department_id,
        title=f"مسودة {ph} بانتظار الاعتماد: {course_name}",
        body=f"راجع مسودة الدرجات #{draft_id} من لوحة اعتماد رئيس القسم.",
    )


def notify_grade_draft_reviewed(
    conn, *, course_name: str, draft_phase: str, approved: bool, instructor_id: int
) -> None:
    ph = {"partial": "جزئي", "final": "نهائي"}.get(str(draft_phase or "").lower(), "درجات")
    if approved:
        title = f"اعتُمدت مسودة {ph}: {course_name}"
        body = "تم اعتماد مسودة الدرجات من رئيس القسم."
    else:
        title = f"أُرجعت مسودة {ph}: {course_name}"
        body = "راجع الملاحظات وأعد الإرسال من صفحة مسودات الدرجات."
    notify_instructor(conn, instructor_id, title=title, body=body)


def faculty_progress_counts(row: dict) -> dict[str, int]:
    """عداد موحّد للمحاور الظاهرة (بدون إضافة نقاط التحقق مرتين)."""
    axes = row.get("axes") or {}
    keys = visible_axis_keys()
    done = sum(1 for k in keys if axes.get(k) in ("done", "na"))
    return {"done": done, "total": len(keys), "pct": round(100 * done / len(keys)) if keys else 0}


def enriched_axis_progress(conn, *, section_id: int, instructor_id: int, section_ids: list[int] | None = None) -> dict[str, Any]:
    """محاور مدمجة + تقدم لشعبة واحدة (للملخصات والمؤشرات)."""
    from backend.services.course_delivery import apply_auto_axes_to_portal_row, delivery_summary_for_ui
    from backend.services.utilities import get_current_term

    sids = section_ids or [section_id]
    tname, tyear = get_current_term(conn=conn)
    sem = f"{(tname or '').strip()} {(tyear or '').strip()}".strip()
    cur = conn.cursor()
    from backend.database.database import schedule_pk_column

    pk = schedule_pk_column(conn)
    sched = cur.execute(
        f"SELECT course_name, COALESCE(teaching_group_id, 0) AS tgid, semester FROM schedule WHERE {pk} = ? LIMIT 1",
        (int(section_id),),
    ).fetchone()
    cn = ""
    tgid = None
    if sched:
        cn = str(sched[0] if not hasattr(sched, "keys") else sched["course_name"] or "").strip()
        try:
            tgid = int(sched[1] if not hasattr(sched, "keys") else sched["tgid"] or 0) or None
        except (TypeError, ValueError):
            tgid = None
    row = {
        "section_id": int(section_id),
        "section_ids": sids,
        "teaching_group_id": tgid,
        "course_name": cn,
        "axes": {k: "pending" for k in visible_axis_keys()},
    }
    row["delivery_summary"] = delivery_summary_for_ui(
        conn, teaching_group_id=tgid, course_name=cn, semester=sem
    )
    apply_auto_axes_to_portal_row(conn, row, semester=sem, instructor_id=int(instructor_id))
    prog = faculty_progress_counts(row)
    ds = row.get("delivery_summary") or {}
    delivery_pct = 0
    if ds.get("available") and ds.get("checkpoints_total"):
        delivery_pct = round(100 * int(ds.get("checkpoints_done") or 0) / int(ds["checkpoints_total"]))
    editable_done = sum(
        1 for k in visible_axis_keys() if is_editable_axis_key(k) and row["axes"].get(k) in ("done", "na")
    )
    editable_total = sum(1 for k in visible_axis_keys() if is_editable_axis_key(k))
    return {
        "axes": row.get("axes") or {},
        "axes_meta": row.get("axes_meta") or {},
        "delivery_summary": ds,
        "progress": prog,
        "delivery_pct": delivery_pct,
        "editable_axes_done": editable_done,
        "editable_axes_total": editable_total,
        "documentation_pct": delivery_pct,
    }


def delivery_action_items_for_row(row: dict) -> list[dict]:
    """مهام مقترحة من تقرير التنفيذ لعرضها في مقرراتي."""
    items: list[dict] = []
    cn = (row.get("course_name") or "").strip()
    sid = row.get("section_id")
    ds = row.get("delivery_summary") or {}
    axes = row.get("axes") or {}
    if not ds.get("available"):
        return items
    if not ds.get("baseline_ok"):
        items.append({
            "type": "delivery_baseline",
            "section_id": sid,
            "course": cn,
            "tab": "sections",
            "focus": "delivery",
            "message": f"{cn}: أكمل واعتمد قائمة المفردات",
        })
    partial = ds.get("partial") or {}
    if not partial.get("submitted"):
        items.append({
            "type": "delivery_partial",
            "section_id": sid,
            "course": cn,
            "tab": "sections",
            "focus": "delivery",
            "message": f"{cn}: أرسل تقرير الجزئي",
        })
    final = ds.get("final") or {}
    if partial.get("submitted") and not final.get("submitted"):
        items.append({
            "type": "delivery_final",
            "section_id": sid,
            "course": cn,
            "tab": "sections",
            "focus": "delivery",
            "message": f"{cn}: أرسل تقرير النهائي",
        })
    for k in visible_axis_keys():
        if is_editable_axis_key(k) and axes.get(k) == "pending":
            label = FACULTY_AXIS_LABELS_AR.get(k, k)
            items.append({
                "type": "axis_pending",
                "section_id": sid,
                "course": cn,
                "tab": "sections",
                "focus": "axes",
                "message": f"{cn}: {label} — قيد العمل",
            })
    return items


def pending_axis_labels(axes: dict) -> list[str]:
    return [FACULTY_AXIS_LABELS_AR.get(k, k) for k in visible_axis_keys() if axes.get(k, "pending") == "pending"]
