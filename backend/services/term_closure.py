"""إغلاق موحّد للفصل (تسجيلات / جدول / امتحانات / استبيانات) + أرشيف ZIP.

الدرجات مستثناة من الموجة الأولى (مرحلة اختيارية متأخرة).
تصحيح السجل بعد النشر لرئيس القسم/الأدمن يبقى مسموحاً ولا يُقفل بهذه الخدمة.
"""

from __future__ import annotations

import datetime
import io
import json
import os
import re
import zipfile
from typing import Any

from backend.database.database import fetch_table_columns, is_postgresql, table_exists
from backend.services.quality_metrics import term_label_from_conn
from backend.services.survey_snapshots import (
    close_semester_and_snapshot,
    get_semester_closure,
    scope_key as survey_scope_key,
    survey_archive_dir,
)
from backend.services.utilities import (
    get_current_term,
    get_exam_schedule_published_at,
    get_schedule_published_at,
)

ARCHIVE_SUBDIR = ("uploads", "term_archives")

# مراحل التشغيل (الدرجات اختيارية ومتأخرة — ليست ضمن متطلبات الأرشيف)
OPERATIONAL_STAGES: tuple[str, ...] = (
    "registrations",
    "schedule",
    "exams",
    "surveys",
)
OPTIONAL_STAGES: tuple[str, ...] = ("grades",)
ALL_STAGES: tuple[str, ...] = OPERATIONAL_STAGES + OPTIONAL_STAGES

STAGE_LABELS_AR: dict[str, str] = {
    "registrations": "إغلاق التسجيلات",
    "schedule": "تجميد الجدول الدراسي",
    "exams": "تجميد الجداول الامتحانية",
    "surveys": "إغلاق الاستبيانات + لقطة",
    "grades": "إغلاق الدرجات (اختياري لاحقاً)",
}

REQUIRED_FOR_ARCHIVE: tuple[str, ...] = OPERATIONAL_STAGES


class TermClosedError(PermissionError):
    """محاولة تعديل مرحلة مغلقة."""

    def __init__(self, message: str, *, stage: str = "", semester: str = ""):
        super().__init__(message)
        self.stage = stage
        self.semester = semester


def term_scope_key(department_id: int | None) -> str:
    return survey_scope_key(department_id)


def term_archive_dir() -> str:
    base = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", *ARCHIVE_SUBDIR)
    )
    os.makedirs(base, exist_ok=True)
    return base


def _now_iso() -> str:
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _empty_stages() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for s in ALL_STAGES:
        out[s] = {
            "closed": False,
            "closed_at": "",
            "closed_by": "",
            "note": "",
            "optional": s in OPTIONAL_STAGES,
        }
    return out


def _parse_stages(raw: Any) -> dict[str, dict[str, Any]]:
    base = _empty_stages()
    data: dict = {}
    if isinstance(raw, dict):
        data = raw
    elif isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                data = parsed
        except Exception:
            data = {}
    for k, v in data.items():
        if k not in base or not isinstance(v, dict):
            continue
        base[k] = {
            "closed": bool(v.get("closed")),
            "closed_at": str(v.get("closed_at") or ""),
            "closed_by": str(v.get("closed_by") or ""),
            "note": str(v.get("note") or ""),
            "optional": k in OPTIONAL_STAGES,
            **{
                extra: v[extra]
                for extra in ("survey_archive", "survey_snapshot_count")
                if extra in v
            },
        }
    return base


def ensure_term_closure_tables(conn) -> None:
    if table_exists(conn, "term_closures"):
        return
    cur = conn.cursor()
    if is_postgresql():
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS term_closures (
                id BIGSERIAL PRIMARY KEY,
                semester TEXT NOT NULL,
                scope_key TEXT NOT NULL,
                department_id BIGINT,
                department_label TEXT DEFAULT '',
                stages_json TEXT DEFAULT '{}',
                archive_filename TEXT DEFAULT '',
                archive_built_at TEXT DEFAULT '',
                closed_at TEXT DEFAULT '',
                closed_by TEXT DEFAULT '',
                summary_json TEXT DEFAULT '',
                updated_at TEXT DEFAULT '',
                UNIQUE (semester, scope_key)
            )
            """
        )
    else:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS term_closures (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                semester TEXT NOT NULL,
                scope_key TEXT NOT NULL,
                department_id INTEGER,
                department_label TEXT DEFAULT '',
                stages_json TEXT DEFAULT '{}',
                archive_filename TEXT DEFAULT '',
                archive_built_at TEXT DEFAULT '',
                closed_at TEXT DEFAULT '',
                closed_by TEXT DEFAULT '',
                summary_json TEXT DEFAULT '',
                updated_at TEXT DEFAULT '',
                UNIQUE (semester, scope_key)
            )
            """
        )
    try:
        conn.commit()
    except Exception:
        pass


def _department_label(conn, department_id: int | None) -> str:
    if department_id is None:
        return "الكلية"
    cur = conn.cursor()
    row = cur.execute(
        "SELECT name_ar FROM departments WHERE id = ? LIMIT 1",
        (int(department_id),),
    ).fetchone()
    if not row:
        return f"قسم {department_id}"
    return str(row[0] if not hasattr(row, "keys") else row["name_ar"] or f"قسم {department_id}")


def _row_to_dict(row) -> dict[str, Any]:
    if row is None:
        return {}
    if hasattr(row, "keys"):
        return {k: row[k] for k in row.keys()}
    return {}


def get_term_closure_row(
    conn,
    semester: str,
    department_id: int | None = None,
) -> dict[str, Any] | None:
    ensure_term_closure_tables(conn)
    sk = term_scope_key(department_id)
    cur = conn.cursor()
    row = cur.execute(
        """
        SELECT id, semester, scope_key, department_id, department_label,
               stages_json, archive_filename, archive_built_at,
               closed_at, closed_by, summary_json, updated_at
        FROM term_closures
        WHERE semester = ? AND scope_key = ?
        LIMIT 1
        """,
        (semester, sk),
    ).fetchone()
    if not row:
        return None
    d = _row_to_dict(row)
    d["stages"] = _parse_stages(d.get("stages_json"))
    d["is_stage_closed"] = {
        s: bool((d["stages"].get(s) or {}).get("closed")) for s in ALL_STAGES
    }
    d["operational_complete"] = all(
        d["is_stage_closed"].get(s) for s in REQUIRED_FOR_ARCHIVE
    )
    return d


def _upsert_term_closure(
    conn,
    *,
    semester: str,
    department_id: int | None,
    stages: dict[str, dict[str, Any]],
    actor: str = "",
    archive_filename: str = "",
    archive_built_at: str = "",
    closed_at: str = "",
    closed_by: str = "",
    summary: dict | None = None,
) -> dict[str, Any]:
    ensure_term_closure_tables(conn)
    sk = term_scope_key(department_id)
    label = _department_label(conn, department_id)
    now = _now_iso()
    stages_json = json.dumps(stages, ensure_ascii=False)
    summary_json = json.dumps(summary or {}, ensure_ascii=False)
    cur = conn.cursor()
    existing = cur.execute(
        "SELECT id, archive_filename, archive_built_at, closed_at, closed_by FROM term_closures WHERE semester=? AND scope_key=? LIMIT 1",
        (semester, sk),
    ).fetchone()
    if existing:
        eid = int(existing[0] if not hasattr(existing, "keys") else existing["id"])
        prev_arch = (
            existing[1] if not hasattr(existing, "keys") else existing["archive_filename"]
        ) or ""
        prev_arch_at = (
            existing[2] if not hasattr(existing, "keys") else existing["archive_built_at"]
        ) or ""
        prev_closed = (
            existing[3] if not hasattr(existing, "keys") else existing["closed_at"]
        ) or ""
        prev_by = (
            existing[4] if not hasattr(existing, "keys") else existing["closed_by"]
        ) or ""
        arch = archive_filename or prev_arch
        arch_at = archive_built_at or prev_arch_at
        cl_at = closed_at or prev_closed
        cl_by = closed_by or prev_by
        cur.execute(
            """
            UPDATE term_closures
               SET department_id = ?, department_label = ?, stages_json = ?,
                   archive_filename = ?, archive_built_at = ?,
                   closed_at = ?, closed_by = ?, summary_json = ?, updated_at = ?
             WHERE id = ?
            """,
            (
                department_id,
                label,
                stages_json,
                arch,
                arch_at,
                cl_at,
                cl_by,
                summary_json,
                now,
                eid,
            ),
        )
    else:
        cur.execute(
            """
            INSERT INTO term_closures
            (semester, scope_key, department_id, department_label, stages_json,
             archive_filename, archive_built_at, closed_at, closed_by, summary_json, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                semester,
                sk,
                department_id,
                label,
                stages_json,
                archive_filename or "",
                archive_built_at or "",
                closed_at or "",
                closed_by or "",
                summary_json,
                now,
            ),
        )
    try:
        conn.commit()
    except Exception:
        pass
    return get_term_closure_row(conn, semester, department_id) or {}


def is_stage_closed(
    conn,
    semester: str,
    stage: str,
    department_id: int | None = None,
    *,
    include_college: bool = True,
) -> bool:
    """
    هل المرحلة مغلقة لهذا النطاق؟
    include_college=True: إغلاق الكلية يقفل أيضاً عمليات القسم.
    """
    if stage not in ALL_STAGES:
        return False
    row = get_term_closure_row(conn, semester, department_id)
    if row and (row.get("stages") or {}).get(stage, {}).get("closed"):
        return True
    if include_college and department_id is not None:
        college = get_term_closure_row(conn, semester, None)
        if college and (college.get("stages") or {}).get(stage, {}).get("closed"):
            return True
    return False


def assert_term_writable(
    conn,
    *,
    stage: str,
    semester: str | None = None,
    department_id: int | None = None,
    force: bool = False,
) -> None:
    """يرفع TermClosedError إذا كانت المرحلة مغلقة للكتابة."""
    if force:
        return
    if stage not in ALL_STAGES:
        return
    sem = (semester or "").strip() or term_label_from_conn(conn)
    if not sem:
        return
    if is_stage_closed(conn, sem, stage, department_id, include_college=True):
        label = STAGE_LABELS_AR.get(stage, stage)
        raise TermClosedError(
            f"الفصل «{sem}» مغلق لمرحلة «{label}» — التعديل غير مسموح.",
            stage=stage,
            semester=sem,
        )


def _faculty_cycle_lock_status(conn, semester: str) -> dict[str, Any]:
    key = f"faculty_cycle_lock::{(semester or '').strip()}"
    row = conn.cursor().execute(
        "SELECT COALESCE(value_json,'false') FROM app_settings WHERE key = ? LIMIT 1",
        (key,),
    ).fetchone()
    raw = (row[0] if row else "false") or "false"
    locked = str(raw).strip().lower() in ("1", "true", "yes", "on")
    return {"locked": locked, "key": key}


def _grades_status_summary(conn, semester: str, department_id: int | None) -> dict[str, Any]:
    """ملخص خفيف — الدرجات مستثناة من إغلاق الموجة الأولى."""
    cur = conn.cursor()
    try:
        if table_exists(conn, "grade_drafts"):
            if department_id is None:
                n = cur.execute(
                    "SELECT COUNT(*) FROM grade_drafts WHERE semester = ?",
                    (semester,),
                ).fetchone()[0]
            else:
                # تقريب: حسب قسم المقرر عبر courses إن وُجد
                cols = fetch_table_columns(conn, "courses")
                if "owning_department_id" in cols:
                    n = cur.execute(
                        """
                        SELECT COUNT(*) FROM grade_drafts g
                        JOIN courses c ON c.course_name = g.course_name
                        WHERE g.semester = ? AND c.owning_department_id = ?
                        """,
                        (semester, int(department_id)),
                    ).fetchone()[0]
                else:
                    n = cur.execute(
                        "SELECT COUNT(*) FROM grade_drafts WHERE semester = ?",
                        (semester,),
                    ).fetchone()[0]
        else:
            n = 0
    except Exception:
        n = 0
    return {
        "excluded_from_first_wave": True,
        "draft_count": int(n or 0),
        "note_ar": "الدرجات غير مُقفلة بإغلاق الفصل التشغيلي؛ التصحيح من السجل متاح لرئيس القسم والأدمن الرئيسي.",
    }


def get_term_closure_status(
    conn,
    *,
    semester: str | None = None,
    department_id: int | None = None,
) -> dict[str, Any]:
    """لوحة حالة الفصل — للقراءة (المرحلة 1) ولإدارة الإغلاق."""
    ensure_term_closure_tables(conn)
    sem = (semester or "").strip() or term_label_from_conn(conn)
    if not sem:
        tname, tyear = get_current_term(conn=conn)
        sem = f"{(tname or '').strip()} {(tyear or '').strip()}".strip()

    closure = get_term_closure_row(conn, sem, department_id)
    stages = (closure or {}).get("stages") or _empty_stages()

    survey = get_semester_closure(conn, sem, department_id)
    # توافق: إن وُجدت لقطة استبيانات قديمة نعرضها كحالة surveys مقفلة منطقياً
    survey_closed = bool(survey)
    if survey_closed and not stages["surveys"].get("closed"):
        stages = dict(stages)
        stages["surveys"] = {
            **stages["surveys"],
            "closed": True,
            "closed_at": str((survey or {}).get("closed_at") or ""),
            "closed_by": str((survey or {}).get("closed_by") or ""),
            "note": "متزامن مع لقطة الاستبيانات",
            "survey_archive": str((survey or {}).get("archive_filename") or ""),
            "optional": False,
        }

    sched_pub = get_schedule_published_at(conn=conn) or ""
    exam_mid = get_exam_schedule_published_at("midterm", conn=conn) or ""
    exam_fin = get_exam_schedule_published_at("final", conn=conn) or ""
    faculty = _faculty_cycle_lock_status(conn, sem)
    grades = _grades_status_summary(conn, sem, department_id)

    stage_board = []
    for s in ALL_STAGES:
        st = stages.get(s) or {}
        board_item = {
            "stage": s,
            "label_ar": STAGE_LABELS_AR.get(s, s),
            "closed": bool(st.get("closed")),
            "closed_at": st.get("closed_at") or "",
            "closed_by": st.get("closed_by") or "",
            "optional": s in OPTIONAL_STAGES,
            "note": st.get("note") or "",
            "can_close": True,
            "can_reopen": bool(st.get("closed")),
        }
        if s == "schedule":
            board_item["publish_hint"] = {
                "published": bool(sched_pub),
                "published_at": sched_pub,
            }
        elif s == "exams":
            board_item["publish_hint"] = {
                "midterm_published": bool(exam_mid),
                "final_published": bool(exam_fin),
                "midterm_at": exam_mid,
                "final_at": exam_fin,
            }
        elif s == "surveys":
            board_item["survey_closure"] = survey
        elif s == "grades":
            board_item["grades_hint"] = grades
        stage_board.append(board_item)

    operational_complete = all(
        bool((stages.get(s) or {}).get("closed")) for s in REQUIRED_FOR_ARCHIVE
    )
    archive_name = (closure or {}).get("archive_filename") or ""

    return {
        "status": "ok",
        "semester": sem,
        "scope_key": term_scope_key(department_id),
        "department_id": department_id,
        "department_label": _department_label(conn, department_id),
        "stages": stages,
        "stage_board": stage_board,
        "operational_complete": operational_complete,
        "archive_filename": archive_name,
        "archive_url": (
            f"/academic_quality/term_closure/archives/{archive_name}"
            if archive_name
            else ""
        ),
        "archive_built_at": (closure or {}).get("archive_built_at") or "",
        "faculty_cycle_lock": faculty,
        "grades_policy": grades,
        "closure_id": (closure or {}).get("id"),
        "updated_at": (closure or {}).get("updated_at") or "",
    }


def close_term_stage(
    conn,
    *,
    stage: str,
    semester: str | None = None,
    department_id: int | None = None,
    actor: str = "",
    force: bool = False,
    note: str = "",
    build_archive: bool = True,
) -> dict[str, Any]:
    stage = (stage or "").strip().lower()
    if stage not in ALL_STAGES:
        raise ValueError(f"مرحلة غير معروفة: {stage}")
    sem = (semester or "").strip() or term_label_from_conn(conn)
    if not sem:
        raise ValueError("الفصل مطلوب")

    existing = get_term_closure_row(conn, sem, department_id)
    stages = (existing or {}).get("stages") or _empty_stages()
    if stages.get(stage, {}).get("closed") and not force:
        raise ValueError(
            f"مرحلة «{STAGE_LABELS_AR.get(stage, stage)}» مغلقة مسبقاً لهذا الفصل/النطاق. استخدم force لإعادة الإغلاق."
        )

    now = _now_iso()
    actor = (actor or "").strip() or "system"
    note = (note or "").strip()

    survey_meta: dict[str, Any] = {}
    if stage == "surveys":
        survey_result = close_semester_and_snapshot(
            conn,
            semester=sem,
            department_id=department_id,
            actor=actor,
            force=force,
        )
        survey_meta = {
            "survey_archive": survey_result.get("archive_filename") or "",
            "survey_snapshot_count": survey_result.get("snapshot_count") or 0,
            "survey_archive_url": survey_result.get("archive_url") or "",
        }

    stages[stage] = {
        "closed": True,
        "closed_at": now,
        "closed_by": actor,
        "note": note,
        "optional": stage in OPTIONAL_STAGES,
        **survey_meta,
    }

    operational_complete = all(
        bool((stages.get(s) or {}).get("closed")) for s in REQUIRED_FOR_ARCHIVE
    )
    archive_filename = ""
    archive_built_at = ""
    closed_at = ""
    closed_by = ""
    if operational_complete and build_archive:
        arch = build_term_archive_zip(
            conn,
            semester=sem,
            department_id=department_id,
            actor=actor,
            stages=stages,
        )
        archive_filename = arch.get("archive_filename") or ""
        archive_built_at = arch.get("archive_built_at") or now
        closed_at = now
        closed_by = actor

    row = _upsert_term_closure(
        conn,
        semester=sem,
        department_id=department_id,
        stages=stages,
        actor=actor,
        archive_filename=archive_filename,
        archive_built_at=archive_built_at,
        closed_at=closed_at,
        closed_by=closed_by,
        summary={
            "last_stage": stage,
            "operational_complete": operational_complete,
        },
    )
    status = get_term_closure_status(
        conn, semester=sem, department_id=department_id
    )
    status["last_closed_stage"] = stage
    status["closure_row"] = row
    return status


def reopen_term_stage(
    conn,
    *,
    stage: str,
    semester: str | None = None,
    department_id: int | None = None,
    actor: str = "",
    reason: str = "",
) -> dict[str, Any]:
    stage = (stage or "").strip().lower()
    if stage not in ALL_STAGES:
        raise ValueError(f"مرحلة غير معروفة: {stage}")
    reason = (reason or "").strip()
    if len(reason) < 5:
        raise ValueError("سبب إعادة الفتح مطلوب (٥ أحرف على الأقل).")
    sem = (semester or "").strip() or term_label_from_conn(conn)
    existing = get_term_closure_row(conn, sem, department_id)
    stages = (existing or {}).get("stages") or _empty_stages()
    if not stages.get(stage, {}).get("closed"):
        raise ValueError("المرحلة ليست مغلقة.")
    stages[stage] = {
        "closed": False,
        "closed_at": "",
        "closed_by": "",
        "note": f"أُعيد فتحها بواسطة {actor}: {reason}",
        "optional": stage in OPTIONAL_STAGES,
    }
    # إعادة الفتح تُلغي اعتبار الأرشيف نهائياً حتى يُبنى من جديد
    _upsert_term_closure(
        conn,
        semester=sem,
        department_id=department_id,
        stages=stages,
        actor=actor,
        archive_filename="",
        archive_built_at="",
        closed_at="",
        closed_by="",
        summary={"reopened_stage": stage, "reason": reason},
    )
    return get_term_closure_status(conn, semester=sem, department_id=department_id)


def _slug(text: str) -> str:
    s = re.sub(r"[^\w\u0600-\u06FF\-]+", "_", (text or "").strip())
    return (s.strip("_") or "term")[:80]


def build_term_archive_zip(
    conn,
    *,
    semester: str,
    department_id: int | None = None,
    actor: str = "",
    stages: dict | None = None,
) -> dict[str, Any]:
    """يبني حزمة ZIP رسمية للفصل/النطاق."""
    ensure_term_closure_tables(conn)
    sem = (semester or "").strip()
    if not sem:
        raise ValueError("الفصل مطلوب للأرشيف")
    sk = term_scope_key(department_id)
    ts = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    fname = f"term_archive_{_slug(sk)}_{_slug(sem)}_{ts}.zip"
    out_dir = term_archive_dir()
    out_path = os.path.join(out_dir, fname)

    meta = {
        "semester": sem,
        "scope_key": sk,
        "department_id": department_id,
        "department_label": _department_label(conn, department_id),
        "built_at": _now_iso(),
        "built_by": actor or "",
        "stages": stages or ((get_term_closure_row(conn, sem, department_id) or {}).get("stages")),
        "grades_in_archive": False,
        "note_ar": "الدرجات مستثناة من أرشيف الموجة الأولى (تُضاف لاحقاً عند إغلاق الدرجات اختيارياً).",
    }

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("meta.json", json.dumps(meta, ensure_ascii=False, indent=2))
        try:
            zf.writestr(
                "registrations.csv",
                _export_registrations_csv(conn, department_id),
            )
        except Exception as exc:
            zf.writestr("registrations_error.txt", str(exc))
        try:
            zf.writestr(
                "schedule.csv",
                _export_schedule_csv(conn, sem, department_id),
            )
        except Exception as exc:
            zf.writestr("schedule_error.txt", str(exc))
        try:
            zf.writestr("exams.csv", _export_exams_csv(conn, department_id))
        except Exception as exc:
            zf.writestr("exams_error.txt", str(exc))

        # إرفاق أرشيف الاستبيانات إن وُجد
        survey = get_semester_closure(conn, sem, department_id)
        arch_name = (survey or {}).get("archive_filename") or ""
        if not arch_name and stages:
            arch_name = str((stages.get("surveys") or {}).get("survey_archive") or "")
        if arch_name:
            src = os.path.join(survey_archive_dir(), os.path.basename(arch_name))
            if os.path.isfile(src):
                zf.write(src, arcname=f"surveys/{os.path.basename(arch_name)}")

    with open(out_path, "wb") as f:
        f.write(buf.getvalue())

    return {
        "archive_filename": fname,
        "archive_built_at": meta["built_at"],
        "archive_path": out_path,
        "archive_url": f"/academic_quality/term_closure/archives/{fname}",
    }


def _csv_escape(v: Any) -> str:
    s = "" if v is None else str(v)
    if any(c in s for c in (",", '"', "\n", "\r")):
        return '"' + s.replace('"', '""') + '"'
    return s


def _rows_to_csv(headers: list[str], rows: list[tuple | list]) -> str:
    lines = [",".join(_csv_escape(h) for h in headers)]
    for r in rows:
        lines.append(",".join(_csv_escape(c) for c in r))
    return "\n".join(lines) + "\n"


def _export_registrations_csv(conn, department_id: int | None) -> str:
    from backend.core.department_scope_policy import student_ids_for_department

    cur = conn.cursor()
    cols = fetch_table_columns(conn, "registrations")
    select_cols = ["student_id", "course_name"]
    for c in ("course_code", "units", "teaching_group_id"):
        if c in cols:
            select_cols.append(c)
    sql = f"SELECT {', '.join(select_cols)} FROM registrations"
    params: tuple = ()
    if department_id is not None:
        ids = sorted(student_ids_for_department(conn, int(department_id)))
        if not ids:
            return _rows_to_csv(select_cols, [])
        ph = ",".join("?" for _ in ids)
        sql += f" WHERE student_id IN ({ph})"
        params = tuple(ids)
    rows = cur.execute(sql, params).fetchall()
    data = [tuple(r) if not hasattr(r, "keys") else tuple(r[c] for c in select_cols) for r in rows]
    return _rows_to_csv(select_cols, data)


def _export_schedule_csv(conn, semester: str, department_id: int | None) -> str:
    cur = conn.cursor()
    cols = fetch_table_columns(conn, "schedule")
    select_cols = [c for c in ("course_name", "day", "time", "room", "instructor", "semester", "department_id") if c in cols]
    if not select_cols:
        select_cols = list(cols)[:8] or ["course_name"]
    sql = f"SELECT {', '.join(select_cols)} FROM schedule WHERE 1=1"
    params: list[Any] = []
    if "semester" in cols:
        sql += " AND semester = ?"
        params.append(semester)
    if department_id is not None and "department_id" in cols:
        sql += " AND department_id = ?"
        params.append(int(department_id))
    rows = cur.execute(sql, tuple(params)).fetchall()
    data = [
        tuple(r) if not hasattr(r, "keys") else tuple(r[c] for c in select_cols)
        for r in rows
    ]
    return _rows_to_csv(select_cols, data)


def _export_exams_csv(conn, department_id: int | None) -> str:
    cur = conn.cursor()
    # جداول الامتحانات قد تكون exam_schedule أو جداول حسب النوع
    for table in ("exam_schedule", "exams", "exam_rows"):
        if not table_exists(conn, table):
            continue
        cols = fetch_table_columns(conn, table)
        select_cols = list(cols)[:12]
        sql = f"SELECT {', '.join(select_cols)} FROM {table}"
        params: tuple = ()
        if department_id is not None and "department_id" in cols:
            sql += " WHERE department_id = ?"
            params = (int(department_id),)
        rows = cur.execute(sql, params).fetchall()
        data = [
            tuple(r) if not hasattr(r, "keys") else tuple(r[c] for c in select_cols)
            for r in rows
        ]
        return _rows_to_csv(select_cols, data)
    return _rows_to_csv(["note"], [("لا يوجد جدول امتحانات قابل للتصدير",)])
