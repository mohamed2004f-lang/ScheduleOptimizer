"""لقطات إغلاق الفصل وتقارير الاستبيانات (مقارنة عبر الفصول)."""

from __future__ import annotations

import datetime
import json
import os
import re
from typing import Any

from backend.database.database import is_postgresql, table_exists
from backend.services.quality_metrics import _row_val, term_label_from_conn
from backend.services.survey_analytics import (
    build_combined_survey_report,
    package_excel_frames,
)
from backend.services.utilities import excel_bytes_from_frames

ARCHIVE_SUBDIR = ("uploads", "survey_archives")


def scope_key(department_id: int | None) -> str:
    return "college" if department_id is None else f"dept:{int(department_id)}"


def survey_archive_dir() -> str:
    base = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", *ARCHIVE_SUBDIR)
    )
    os.makedirs(base, exist_ok=True)
    return base


def ensure_survey_snapshot_tables(conn) -> None:
    if table_exists(conn, "survey_semester_closures"):
        return
    cur = conn.cursor()
    if is_postgresql():
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS survey_semester_closures (
                id BIGSERIAL PRIMARY KEY,
                semester TEXT NOT NULL,
                scope_key TEXT NOT NULL,
                department_id BIGINT,
                department_label TEXT DEFAULT '',
                closed_at TEXT NOT NULL,
                closed_by TEXT DEFAULT '',
                snapshot_count INTEGER DEFAULT 0,
                archive_filename TEXT DEFAULT '',
                summary_json TEXT DEFAULT '',
                UNIQUE (semester, scope_key)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS survey_semester_snapshots (
                id BIGSERIAL PRIMARY KEY,
                closure_id BIGINT NOT NULL REFERENCES survey_semester_closures(id) ON DELETE CASCADE,
                semester TEXT NOT NULL,
                scope_key TEXT NOT NULL,
                template_code TEXT NOT NULL,
                title_ar TEXT DEFAULT '',
                response_count INTEGER DEFAULT 0,
                min_aggregate INTEGER DEFAULT 0,
                aggregated INTEGER DEFAULT 0,
                overall_score_percent REAL,
                compliance_status_ar TEXT DEFAULT '',
                weakest_item TEXT DEFAULT '',
                strongest_item TEXT DEFAULT '',
                primary_accreditation TEXT DEFAULT '',
                questions_json TEXT DEFAULT '[]',
                UNIQUE (semester, scope_key, template_code)
            )
            """
        )
    else:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS survey_semester_closures (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                semester TEXT NOT NULL,
                scope_key TEXT NOT NULL,
                department_id INTEGER,
                department_label TEXT DEFAULT '',
                closed_at TEXT NOT NULL,
                closed_by TEXT DEFAULT '',
                snapshot_count INTEGER DEFAULT 0,
                archive_filename TEXT DEFAULT '',
                summary_json TEXT DEFAULT '',
                UNIQUE (semester, scope_key)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS survey_semester_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                closure_id INTEGER NOT NULL,
                semester TEXT NOT NULL,
                scope_key TEXT NOT NULL,
                template_code TEXT NOT NULL,
                title_ar TEXT DEFAULT '',
                response_count INTEGER DEFAULT 0,
                min_aggregate INTEGER DEFAULT 0,
                aggregated INTEGER DEFAULT 0,
                overall_score_percent REAL,
                compliance_status_ar TEXT DEFAULT '',
                weakest_item TEXT DEFAULT '',
                strongest_item TEXT DEFAULT '',
                primary_accreditation TEXT DEFAULT '',
                questions_json TEXT DEFAULT '[]',
                UNIQUE (semester, scope_key, template_code),
                FOREIGN KEY (closure_id) REFERENCES survey_semester_closures(id) ON DELETE CASCADE
            )
            """
        )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_survey_closure_sem ON survey_semester_closures(semester, scope_key)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_survey_snapshot_sem ON survey_semester_snapshots(semester, scope_key)"
    )
    conn.commit()


def get_semester_closure(
    conn,
    semester: str,
    department_id: int | None = None,
) -> dict[str, Any] | None:
    ensure_survey_snapshot_tables(conn)
    sk = scope_key(department_id)
    cur = conn.cursor()
    row = cur.execute(
        """
        SELECT id, semester, scope_key, department_id, department_label,
               closed_at, closed_by, snapshot_count, archive_filename, summary_json
        FROM survey_semester_closures
        WHERE semester = ? AND scope_key = ?
        LIMIT 1
        """,
        (semester.strip(), sk),
    ).fetchone()
    if not row:
        return None
    if hasattr(row, "keys"):
        d = dict(row)
    else:
        d = {
            "id": row[0],
            "semester": row[1],
            "scope_key": row[2],
            "department_id": row[3],
            "department_label": row[4],
            "closed_at": row[5],
            "closed_by": row[6],
            "snapshot_count": row[7],
            "archive_filename": row[8],
            "summary_json": row[9],
        }
    d["is_closed"] = True
    if d.get("archive_filename"):
        d["archive_url"] = (
            f"/academic_quality/surveys/archives/{d['archive_filename']}"
        )
    return d


def is_semester_closed(conn, semester: str, department_id: int | None = None) -> bool:
    return get_semester_closure(conn, semester, department_id) is not None


def list_closed_semesters(
    conn,
    *,
    department_id: int | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    ensure_survey_snapshot_tables(conn)
    sk = scope_key(department_id)
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT semester, closed_at, closed_by, snapshot_count, archive_filename, department_label
        FROM survey_semester_closures
        WHERE scope_key = ?
        ORDER BY closed_at DESC
        LIMIT ?
        """,
        (sk, int(limit)),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        if hasattr(row, "keys"):
            d = dict(row)
        else:
            d = {
                "semester": row[0],
                "closed_at": row[1],
                "closed_by": row[2],
                "snapshot_count": row[3],
                "archive_filename": row[4],
                "department_label": row[5],
            }
        if d.get("archive_filename"):
            d["archive_url"] = (
                f"/academic_quality/surveys/archives/{d['archive_filename']}"
            )
        out.append(d)
    return out


def list_semester_snapshots(
    conn,
    semester: str,
    department_id: int | None = None,
) -> list[dict[str, Any]]:
    ensure_survey_snapshot_tables(conn)
    sk = scope_key(department_id)
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT template_code, title_ar, response_count, min_aggregate, aggregated,
               overall_score_percent, compliance_status_ar, weakest_item, strongest_item,
               primary_accreditation, questions_json
        FROM survey_semester_snapshots
        WHERE semester = ? AND scope_key = ?
        ORDER BY template_code
        """,
        (semester.strip(), sk),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        if hasattr(row, "keys"):
            d = dict(row)
        else:
            d = {
                "template_code": row[0],
                "title_ar": row[1],
                "response_count": row[2],
                "min_aggregate": row[3],
                "aggregated": row[4],
                "overall_score_percent": row[5],
                "compliance_status_ar": row[6],
                "weakest_item": row[7],
                "strongest_item": row[8],
                "primary_accreditation": row[9],
                "questions_json": row[10],
            }
        try:
            d["questions"] = json.loads(d.get("questions_json") or "[]")
        except (TypeError, json.JSONDecodeError):
            d["questions"] = []
        out.append(d)
    return out


def list_semester_snapshots_batch(
    conn,
    semesters: list[str],
    department_id: int | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """جلب لقطات عدة فصول في استعلام واحد."""
    sems = [s.strip() for s in semesters if (s or "").strip()]
    if not sems:
        return {}
    ensure_survey_snapshot_tables(conn)
    sk = scope_key(department_id)
    cur = conn.cursor()
    placeholders = ", ".join("?" * len(sems))
    rows = cur.execute(
        f"""
        SELECT semester, template_code, title_ar, response_count, min_aggregate, aggregated,
               overall_score_percent, compliance_status_ar, weakest_item, strongest_item,
               primary_accreditation, questions_json
        FROM survey_semester_snapshots
        WHERE scope_key = ? AND semester IN ({placeholders})
        ORDER BY semester, template_code
        """,
        tuple([sk] + sems),
    ).fetchall()
    out: dict[str, list[dict[str, Any]]] = {s: [] for s in sems}
    for row in rows:
        if hasattr(row, "keys"):
            d = dict(row)
        else:
            d = {
                "semester": row[0],
                "template_code": row[1],
                "title_ar": row[2],
                "response_count": row[3],
                "min_aggregate": row[4],
                "aggregated": row[5],
                "overall_score_percent": row[6],
                "compliance_status_ar": row[7],
                "weakest_item": row[8],
                "strongest_item": row[9],
                "primary_accreditation": row[10],
                "questions_json": row[11],
            }
        try:
            d["questions"] = json.loads(d.get("questions_json") or "[]")
        except (TypeError, json.JSONDecodeError):
            d["questions"] = []
        sem_key = (d.get("semester") or "").strip()
        if sem_key in out:
            out[sem_key].append(d)
    return out


def _questions_payload(questions: list[dict] | None) -> str:
    slim = []
    for q in questions or []:
        slim.append(
            {
                "label_ar": q.get("label_ar"),
                "avg_rating": q.get("avg_rating"),
                "score_percent": q.get("score_percent"),
                "classification_ar": q.get("classification_ar"),
            }
        )
    return json.dumps(slim, ensure_ascii=False)


def _reports_for_snapshot(combined: dict[str, Any]) -> list[dict[str, Any]]:
    reports = list(combined.get("reports") or [])
    if combined.get("course_eval"):
        reports.append(combined["course_eval"])
    return reports


def _save_archive_xlsx(combined: dict[str, Any], *, scope: str, semester: str) -> str:
    raw = excel_bytes_from_frames(package_excel_frames(combined))
    sem_slug = re.sub(r"[^\w\-]+", "_", semester)[:40]
    ts = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"survey_package_{scope}_{sem_slug}_{ts}.xlsx"
    path = os.path.join(survey_archive_dir(), filename)
    with open(path, "wb") as f:
        f.write(raw)
    return filename


def close_semester_and_snapshot(
    conn,
    *,
    semester: str | None = None,
    department_id: int | None = None,
    actor: str = "",
    force: bool = False,
    register_package_evidence: bool = False,
    auto_bind_accreditation: bool = False,
) -> dict[str, Any]:
    """
    إغلاق الفصل: حفظ لقطات مجمّعة + أرشيف Excel.
    force=True يستبدل لقطة سابقة لنفس الفصل والنطاق.
    """
    ensure_survey_snapshot_tables(conn)
    sem = (semester or term_label_from_conn(conn)).strip()
    sk = scope_key(department_id)
    existing = get_semester_closure(conn, sem, department_id)
    if existing and not force:
        raise ValueError(
            f"الفصل «{sem}» مُغلق مسبقاً بتاريخ {existing.get('closed_at')}. "
            "استخدم force=true لإعادة اللقطة."
        )

    combined = build_combined_survey_report(
        conn, semester=sem, department_id=department_id, include_course_eval=True
    )
    reports = _reports_for_snapshot(combined)
    if not reports:
        raise ValueError("لا توجد بيانات استبيانات لهذا الفصل")

    cur = conn.cursor()
    if existing and force:
        cid = int(existing["id"])
        cur.execute("DELETE FROM survey_semester_snapshots WHERE closure_id = ?", (cid,))
        cur.execute("DELETE FROM survey_semester_closures WHERE id = ?", (cid,))
        conn.commit()

    now = datetime.datetime.utcnow().isoformat(timespec="seconds")
    archive_filename = _save_archive_xlsx(combined, scope=sk, semester=sem)
    summary = {
        "aggregated_survey_count": combined.get("aggregated_survey_count"),
        "total_survey_count": combined.get("total_survey_count"),
        "department_label": combined.get("department_label"),
        "generated_at": combined.get("generated_at"),
    }

    if is_postgresql():
        row = cur.execute(
            """
            INSERT INTO survey_semester_closures (
                semester, scope_key, department_id, department_label,
                closed_at, closed_by, snapshot_count, archive_filename, summary_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            (
                sem,
                sk,
                department_id,
                combined.get("department_label") or "",
                now,
                actor,
                len(reports),
                archive_filename,
                json.dumps(summary, ensure_ascii=False),
            ),
        ).fetchone()
        closure_id = int(_row_val(row, 0, "id") or 0)
    else:
        cur.execute(
            """
            INSERT INTO survey_semester_closures (
                semester, scope_key, department_id, department_label,
                closed_at, closed_by, snapshot_count, archive_filename, summary_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                sem,
                sk,
                department_id,
                combined.get("department_label") or "",
                now,
                actor,
                len(reports),
                archive_filename,
                json.dumps(summary, ensure_ascii=False),
            ),
        )
        closure_id = int(cur.lastrowid or 0)

    for r in reports:
        code = (r.get("template_code") or "").strip()
        if not code:
            continue
        cur.execute(
            """
            INSERT INTO survey_semester_snapshots (
                closure_id, semester, scope_key, template_code, title_ar,
                response_count, min_aggregate, aggregated, overall_score_percent,
                compliance_status_ar, weakest_item, strongest_item,
                primary_accreditation, questions_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                closure_id,
                sem,
                sk,
                code,
                r.get("title_ar") or code,
                int(r.get("response_count") or 0),
                int(r.get("min_aggregate") or 0),
                1 if r.get("aggregated") else 0,
                r.get("overall_score_percent"),
                r.get("compliance_status_ar") or "",
                r.get("weakest_item") or "",
                r.get("strongest_item") or "",
                r.get("primary_accreditation") or "",
                _questions_payload(r.get("questions")),
            ),
        )

    try:
        from backend.services.quality_metrics import compute_quality_metrics, save_metrics_snapshot

        metrics = compute_quality_metrics(conn, semester=sem, department_id=department_id)
        save_metrics_snapshot(conn, metrics, actor=actor)
    except Exception:
        pass

    evidence_result = None
    if register_package_evidence:
        try:
            from backend.services.accreditation_evidence import save_file_evidence
            from backend.services.survey_accreditation import resolve_indicator_id

            iid = resolve_indicator_id(conn, "QA-01-1")
            if iid:
                archive_path = os.path.join(survey_archive_dir(), archive_filename)
                with open(archive_path, "rb") as af:
                    raw = af.read()
                evidence_result = save_file_evidence(
                    conn,
                    semester=sem,
                    department_id=department_id,
                    raw=raw,
                    original_name=archive_filename,
                    mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    uploaded_by=actor,
                    indicator_id=iid,
                    title_ar=f"لقطة استبيانات الفصل — {sem}",
                    description=(
                        f"أرشيف Excel موحّد عند إغلاق الفصل. "
                        f"عدد الاستبيانات في اللقطة: {len(reports)}."
                    ),
                )
        except Exception:
            evidence_result = None

    bindings_result = None
    if auto_bind_accreditation:
        try:
            from backend.services.accreditation_auto_bind import auto_bind_survey_templates

            tpl_codes = [
                (r.get("template_code") or "").strip()
                for r in reports
                if (r.get("template_code") or "").strip()
            ]
            bindings_result = auto_bind_survey_templates(
                conn,
                semester=sem,
                department_id=department_id,
                actor=actor,
                template_codes=tpl_codes,
            )
        except Exception:
            bindings_result = None

    conn.commit()
    closure = get_semester_closure(conn, sem, department_id) or {}
    return {
        "status": "ok",
        "semester": sem,
        "scope_key": sk,
        "closure_id": closure_id,
        "snapshot_count": len(reports),
        "closed_at": now,
        "archive_url": f"/academic_quality/surveys/archives/{archive_filename}",
        "compliance_map_url": f"/academic_quality/accreditation/map?semester={sem}",
        "trends_url": "/academic_quality/surveys/trends",
        "evidence": evidence_result,
        "accreditation_bindings": bindings_result,
        "closure": closure,
    }


def compare_semester_snapshots(
    conn,
    semester_a: str,
    semester_b: str,
    *,
    department_id: int | None = None,
) -> dict[str, Any]:
    """مقارنة لقطتين مُغلقتين (أو لقطة + فارغ)."""
    sem_a = semester_a.strip()
    sem_b = semester_b.strip()
    snaps_a = {s["template_code"]: s for s in list_semester_snapshots(conn, sem_a, department_id)}
    snaps_b = {s["template_code"]: s for s in list_semester_snapshots(conn, sem_b, department_id)}
    codes = sorted(set(snaps_a) | set(snaps_b))
    rows: list[dict[str, Any]] = []
    for code in codes:
        a = snaps_a.get(code) or {}
        b = snaps_b.get(code) or {}
        sa = a.get("overall_score_percent")
        sb = b.get("overall_score_percent")
        delta = None
        trend = "—"
        if sa is not None and sb is not None:
            delta = round(float(sb) - float(sa), 1)
            if delta > 0.5:
                trend = "تحسّن"
            elif delta < -0.5:
                trend = "تراجع"
            else:
                trend = "ثابت"
        rows.append(
            {
                "template_code": code,
                "title_ar": a.get("title_ar") or b.get("title_ar") or code,
                "semester_a": sem_a,
                "score_a": sa,
                "aggregated_a": bool(a.get("aggregated")),
                "semester_b": sem_b,
                "score_b": sb,
                "aggregated_b": bool(b.get("aggregated")),
                "delta": delta,
                "trend": trend,
            }
        )
    return {
        "semester_a": sem_a,
        "semester_b": sem_b,
        "has_closure_a": is_semester_closed(conn, sem_a, department_id),
        "has_closure_b": is_semester_closed(conn, sem_b, department_id),
        "rows": rows,
    }


def list_closed_semesters_chronological(
    conn,
    *,
    department_id: int | None = None,
    limit: int = 24,
) -> list[dict[str, Any]]:
    """فصول مُغلقة من الأقدم إلى الأحدث (للرسوم البيانية)."""
    ensure_survey_snapshot_tables(conn)
    sk = scope_key(department_id)
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT semester, closed_at, closed_by, snapshot_count, archive_filename, department_label
        FROM survey_semester_closures
        WHERE scope_key = ?
        ORDER BY closed_at ASC
        LIMIT ?
        """,
        (sk, int(limit)),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        if hasattr(row, "keys"):
            d = dict(row)
        else:
            d = {
                "semester": row[0],
                "closed_at": row[1],
                "closed_by": row[2],
                "snapshot_count": row[3],
                "archive_filename": row[4],
                "department_label": row[5],
            }
        if d.get("archive_filename"):
            d["archive_url"] = (
                f"/academic_quality/surveys/archives/{d['archive_filename']}"
            )
        out.append(d)
    return out


def build_trends_chart_data(
    conn,
    *,
    department_id: int | None = None,
    limit: int = 12,
) -> dict[str, Any]:
    """بيانات رسوم الاتجاهات من اللقطات المُغلقة."""
    closed = list_closed_semesters_chronological(
        conn, department_id=department_id, limit=limit
    )
    semesters = [c["semester"] for c in closed]
    if not semesters:
        return {
            "semesters": [],
            "overall_avg": [],
            "surveys": [],
            "has_data": False,
        }

    surveys_map: dict[str, dict[str, Any]] = {}
    overall_avg: list[float | None] = []
    snaps_by_sem = list_semester_snapshots_batch(conn, semesters, department_id)

    for sem in semesters:
        snaps = snaps_by_sem.get(sem) or []
        scored = [
            float(s["overall_score_percent"])
            for s in snaps
            if s.get("aggregated") and s.get("overall_score_percent") is not None
        ]
        overall_avg.append(round(sum(scored) / len(scored), 1) if scored else None)
        for s in snaps:
            code = s.get("template_code") or ""
            if not code:
                continue
            if code not in surveys_map:
                surveys_map[code] = {
                    "template_code": code,
                    "title_ar": s.get("title_ar") or code,
                    "scores": [],
                }
            val = (
                float(s["overall_score_percent"])
                if s.get("aggregated") and s.get("overall_score_percent") is not None
                else None
            )
            surveys_map[code]["scores"].append(val)

    surveys_list = sorted(
        surveys_map.values(),
        key=lambda x: sum(1 for v in x["scores"] if v is not None),
        reverse=True,
    )
    return {
        "semesters": semesters,
        "overall_avg": overall_avg,
        "surveys": surveys_list,
        "has_data": bool(semesters),
        "closed_count": len(closed),
    }


def closure_reminder_status(
    conn,
    semester: str,
    department_id: int | None = None,
    *,
    aggregated_count: int | None = None,
    total_survey_count: int | None = None,
    department_label: str | None = None,
) -> dict[str, Any]:
    """
    تذكير بإغلاق الفصل عند وجود نتائج مجمّعة دون لقطة مُقفلة.
    """
    sem = (semester or "").strip()
    if not sem:
        return {"show": False}
    if is_semester_closed(conn, sem, department_id):
        return {"show": False, "reason": "already_closed"}

    if aggregated_count is None:
        agg, total = _closure_aggregate_counts(conn, sem, department_id)
    else:
        agg = int(aggregated_count)
        total = int(total_survey_count if total_survey_count is not None else aggregated_count)

    if agg == 0:
        return {"show": False, "reason": "no_aggregated_data"}

    if department_label is None:
        from backend.services.survey_analytics import _department_label

        department_label = _department_label(conn, department_id)

    return {
        "show": True,
        "semester": sem,
        "aggregated_count": agg,
        "total_count": total,
        "department_label": department_label,
        "title_ar": "تذكير: إكمال إغلاق الفصل",
        "message_ar": (
            f"الفصل «{sem}» لديه {agg} استبيان(ات) مجمّعة من أصل {total} "
            "— يُنصح بإكمال مرحلة الاستبيانات من لوحة إغلاق الفصل الموحّد "
            "قبل بدء فصل جديد للمقارنة عبر السنوات ولأرشفة الشواهد."
        ),
        "action_url": "/academic_quality/term_closure",
    }


def _closure_aggregate_counts(
    conn,
    semester: str,
    department_id: int | None = None,
) -> tuple[int, int]:
    """عدّ التجميعات دون build_combined_survey_report."""
    from backend.core.survey_platform import EXTERNAL_SURVEY_CODES
    from backend.services.multi_surveys import aggregate_template, list_templates
    from backend.services.survey_analytics import build_course_eval_report

    sem = (semester or "").strip()
    total = 0
    agg = 0
    for t in list_templates(conn):
        if int(t.get("legacy_course_eval") or 0):
            continue
        tc = (t.get("code") or "").strip()
        if not tc or tc in EXTERNAL_SURVEY_CODES:
            continue
        total += 1
        a = aggregate_template(conn, tc, semester=sem, department_id=department_id)
        if a.get("aggregated"):
            agg += 1
    total += 1
    ce = build_course_eval_report(conn, semester=sem, department_id=department_id)
    if ce.get("aggregated"):
        agg += 1
    return agg, total


def get_cycle_closure(conn, cycle_label: str) -> dict[str, Any] | None:
    """لقطة إغلاق دورة استبيانات خارجية."""
    from backend.services.survey_external_analytics import EXTERNAL_SCOPE_KEY

    return _get_closure_by_scope(conn, cycle_label, EXTERNAL_SCOPE_KEY)


def _get_closure_by_scope(conn, label: str, sk: str) -> dict[str, Any] | None:
    ensure_survey_snapshot_tables(conn)
    cur = conn.cursor()
    row = cur.execute(
        """
        SELECT id, semester, scope_key, department_id, department_label,
               closed_at, closed_by, snapshot_count, archive_filename, summary_json
        FROM survey_semester_closures
        WHERE semester = ? AND scope_key = ?
        LIMIT 1
        """,
        (label.strip(), sk),
    ).fetchone()
    if not row:
        return None
    d = dict(row) if hasattr(row, "keys") else {
        "id": row[0], "semester": row[1], "scope_key": row[2],
        "department_id": row[3], "department_label": row[4],
        "closed_at": row[5], "closed_by": row[6], "snapshot_count": row[7],
        "archive_filename": row[8], "summary_json": row[9],
    }
    if d.get("archive_filename"):
        d["archive_url"] = f"/academic_quality/surveys/archives/{d['archive_filename']}"
    d["cycle_label"] = d.get("semester")
    return d


def is_cycle_closed(conn, cycle_label: str) -> bool:
    from backend.services.survey_external_analytics import EXTERNAL_SCOPE_KEY

    return _get_closure_by_scope(conn, cycle_label, EXTERNAL_SCOPE_KEY) is not None


def list_closed_cycles(conn, *, limit: int = 20) -> list[dict[str, Any]]:
    from backend.services.survey_external_analytics import EXTERNAL_SCOPE_KEY

    ensure_survey_snapshot_tables(conn)
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT semester, closed_at, closed_by, snapshot_count, archive_filename, department_label
        FROM survey_semester_closures
        WHERE scope_key = ?
        ORDER BY closed_at DESC
        LIMIT ?
        """,
        (EXTERNAL_SCOPE_KEY, int(limit)),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        if hasattr(row, "keys"):
            d = dict(row)
        else:
            d = {
                "semester": row[0],
                "closed_at": row[1],
                "closed_by": row[2],
                "snapshot_count": row[3],
                "archive_filename": row[4],
                "department_label": row[5],
            }
        d["cycle_label"] = d.get("semester")
        if d.get("archive_filename"):
            d["archive_url"] = f"/academic_quality/surveys/archives/{d['archive_filename']}"
        out.append(d)
    return out


def list_cycle_snapshots(conn, cycle_label: str) -> list[dict[str, Any]]:
    from backend.services.survey_external_analytics import EXTERNAL_SCOPE_KEY

    return _list_snapshots_by_scope(conn, cycle_label, EXTERNAL_SCOPE_KEY)


def _list_snapshots_by_scope(conn, label: str, sk: str) -> list[dict[str, Any]]:
    ensure_survey_snapshot_tables(conn)
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT template_code, title_ar, response_count, min_aggregate, aggregated,
               overall_score_percent, compliance_status_ar, weakest_item, strongest_item,
               primary_accreditation, questions_json
        FROM survey_semester_snapshots
        WHERE semester = ? AND scope_key = ?
        ORDER BY template_code
        """,
        (label.strip(), sk),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        if hasattr(row, "keys"):
            d = dict(row)
        else:
            d = {
                "template_code": row[0], "title_ar": row[1], "response_count": row[2],
                "min_aggregate": row[3], "aggregated": row[4],
                "overall_score_percent": row[5], "compliance_status_ar": row[6],
                "weakest_item": row[7], "strongest_item": row[8],
                "primary_accreditation": row[9], "questions_json": row[10],
            }
        try:
            d["questions"] = json.loads(d.get("questions_json") or "[]")
        except (TypeError, json.JSONDecodeError):
            d["questions"] = []
        out.append(d)
    return out


def _save_external_archive_xlsx(combined: dict[str, Any], *, cycle_label: str) -> str:
    from backend.services.survey_external_analytics import (
        EXTERNAL_SCOPE_KEY,
        external_package_excel_frames,
    )

    raw = excel_bytes_from_frames(external_package_excel_frames(combined))
    slug = re.sub(r"[^\w\-]+", "_", cycle_label)[:40]
    ts = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"survey_external_{EXTERNAL_SCOPE_KEY}_{slug}_{ts}.xlsx"
    path = os.path.join(survey_archive_dir(), filename)
    with open(path, "wb") as f:
        f.write(raw)
    return filename


def close_cycle_and_snapshot(
    conn,
    *,
    cycle_label: str,
    actor: str = "",
    force: bool = False,
    register_package_evidence: bool = False,
) -> dict[str, Any]:
    """إغلاق دورة استبيانات خارجية وحفظ لقطة + أرشيف."""
    from backend.services.survey_external_analytics import (
        EXTERNAL_SCOPE_KEY,
        build_combined_external_report,
    )

    ensure_survey_snapshot_tables(conn)
    cycle = (cycle_label or "").strip()
    if not cycle:
        raise ValueError("اسم الدورة مطلوب")
    sk = EXTERNAL_SCOPE_KEY
    existing = _get_closure_by_scope(conn, cycle, sk)
    if existing and not force:
        raise ValueError(
            f"الدورة «{cycle}» مُغلقة مسبقاً بتاريخ {existing.get('closed_at')}. "
            "استخدم force=true لإعادة اللقطة."
        )

    combined = build_combined_external_report(conn, cycle_label=cycle)
    reports = list(combined.get("reports") or [])
    if not reports or not any(int(r.get("response_count") or 0) > 0 for r in reports):
        raise ValueError("لا توجد إجابات لهذه الدورة")

    cur = conn.cursor()
    if existing and force:
        cid = int(existing["id"])
        cur.execute("DELETE FROM survey_semester_snapshots WHERE closure_id = ?", (cid,))
        cur.execute("DELETE FROM survey_semester_closures WHERE id = ?", (cid,))
        conn.commit()

    now = datetime.datetime.utcnow().isoformat(timespec="seconds")
    archive_filename = _save_external_archive_xlsx(combined, cycle_label=cycle)
    summary = {
        "aggregated_survey_count": combined.get("aggregated_survey_count"),
        "total_survey_count": combined.get("total_survey_count"),
        "report_kind": "external",
        "generated_at": combined.get("generated_at"),
    }

    if is_postgresql():
        row = cur.execute(
            """
            INSERT INTO survey_semester_closures (
                semester, scope_key, department_id, department_label,
                closed_at, closed_by, snapshot_count, archive_filename, summary_json
            ) VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            (
                cycle, sk, combined.get("department_label") or "خارجي",
                now, actor, len(reports), archive_filename,
                json.dumps(summary, ensure_ascii=False),
            ),
        ).fetchone()
        closure_id = int(_row_val(row, 0, "id") or 0)
    else:
        cur.execute(
            """
            INSERT INTO survey_semester_closures (
                semester, scope_key, department_id, department_label,
                closed_at, closed_by, snapshot_count, archive_filename, summary_json
            ) VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?)
            """,
            (
                cycle, sk, combined.get("department_label") or "خارجي",
                now, actor, len(reports), archive_filename,
                json.dumps(summary, ensure_ascii=False),
            ),
        )
        closure_id = int(cur.lastrowid or 0)

    for r in reports:
        code = (r.get("template_code") or "").strip()
        if not code:
            continue
        cur.execute(
            """
            INSERT INTO survey_semester_snapshots (
                closure_id, semester, scope_key, template_code, title_ar,
                response_count, min_aggregate, aggregated, overall_score_percent,
                compliance_status_ar, weakest_item, strongest_item,
                primary_accreditation, questions_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                closure_id, cycle, sk, code, r.get("title_ar") or code,
                int(r.get("response_count") or 0), int(r.get("min_aggregate") or 0),
                1 if r.get("aggregated") else 0, r.get("overall_score_percent"),
                r.get("compliance_status_ar") or "", r.get("weakest_item") or "",
                r.get("strongest_item") or "", r.get("primary_accreditation") or "",
                _questions_payload(r.get("questions")),
            ),
        )

    evidence_result = None
    if register_package_evidence:
        try:
            from backend.services.accreditation_evidence import save_file_evidence
            from backend.services.survey_accreditation import resolve_indicator_id

            iid = resolve_indicator_id(conn, "GV-01-1")
            if iid:
                archive_path = os.path.join(survey_archive_dir(), archive_filename)
                with open(archive_path, "rb") as af:
                    raw = af.read()
                evidence_result = save_file_evidence(
                    conn,
                    semester=cycle,
                    department_id=None,
                    raw=raw,
                    original_name=archive_filename,
                    mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    uploaded_by=actor,
                    indicator_id=iid,
                    title_ar=f"لقطة استبيانات خارجية — {cycle}",
                    description=(
                        f"أرشيف Excel لدورة استشارة القطاع/الخريج. "
                        f"عدد الاستبيانات: {len(reports)}."
                    ),
                )
        except Exception:
            evidence_result = None

    conn.commit()
    closure = _get_closure_by_scope(conn, cycle, sk) or {}
    return {
        "status": "ok",
        "cycle_label": cycle,
        "scope_key": sk,
        "closure_id": closure_id,
        "snapshot_count": len(reports),
        "closed_at": now,
        "archive_url": f"/academic_quality/surveys/archives/{archive_filename}",
        "compliance_map_url": f"/academic_quality/accreditation/map?cycle={cycle}",
        "results_url": f"/academic_quality/surveys/results?view=external&cycle={cycle}",
        "evidence": evidence_result,
        "closure": closure,
    }


def compare_cycle_snapshots(conn, cycle_a: str, cycle_b: str) -> dict[str, Any]:
    """مقارنة لقطتين لدورتين خارجيتين مُغلقتين."""
    ca = cycle_a.strip()
    cb = cycle_b.strip()
    snaps_a = {s["template_code"]: s for s in list_cycle_snapshots(conn, ca)}
    snaps_b = {s["template_code"]: s for s in list_cycle_snapshots(conn, cb)}
    codes = sorted(set(snaps_a) | set(snaps_b))
    rows: list[dict[str, Any]] = []
    for code in codes:
        a = snaps_a.get(code) or {}
        b = snaps_b.get(code) or {}
        sa = a.get("overall_score_percent")
        sb = b.get("overall_score_percent")
        delta = None
        trend = "—"
        if sa is not None and sb is not None:
            delta = round(float(sb) - float(sa), 1)
            if delta > 0.5:
                trend = "تحسّن"
            elif delta < -0.5:
                trend = "تراجع"
            else:
                trend = "ثابت"
        rows.append(
            {
                "template_code": code,
                "title_ar": a.get("title_ar") or b.get("title_ar") or code,
                "semester_a": ca,
                "score_a": sa,
                "aggregated_a": bool(a.get("aggregated")),
                "semester_b": cb,
                "score_b": sb,
                "aggregated_b": bool(b.get("aggregated")),
                "delta": delta,
                "trend": trend,
            }
        )
    return {
        "semester_a": ca,
        "semester_b": cb,
        "cycle_a": ca,
        "cycle_b": cb,
        "rows": rows,
        "is_external": True,
    }


def list_available_cycles_for_trends(conn, *, limit: int = 30) -> list[str]:
    """دورات خارجية لها إغلاق أو إجابات دعوة."""
    cycles: set[str] = set()
    for c in list_closed_cycles(conn, limit=limit):
        if c.get("cycle_label"):
            cycles.add(str(c["cycle_label"]))
    try:
        from backend.services.survey_invites import list_external_cycles

        for c in list_external_cycles(conn):
            if c:
                cycles.add(str(c))
    except Exception:
        pass
    return sorted(cycles, reverse=True)


def build_external_trends_chart_data(conn, *, limit: int = 12) -> dict[str, Any]:
    """اتجاهات دورات الاستبيانات الخارجية المُغلقة."""
    from backend.services.survey_external_analytics import EXTERNAL_SCOPE_KEY

    closed = list_closed_cycles(conn, limit=limit)
    closed = sorted(closed, key=lambda c: c.get("closed_at") or "")
    cycles = [c["cycle_label"] for c in closed if c.get("cycle_label")]
    if not cycles:
        return {"cycles": [], "overall_avg": [], "surveys": [], "has_data": False}

    surveys_map: dict[str, dict[str, Any]] = {}
    overall_avg: list[float | None] = []

    for cycle in cycles:
        snaps = _list_snapshots_by_scope(conn, cycle, EXTERNAL_SCOPE_KEY)
        scored = [
            float(s["overall_score_percent"])
            for s in snaps
            if s.get("aggregated") and s.get("overall_score_percent") is not None
        ]
        overall_avg.append(round(sum(scored) / len(scored), 1) if scored else None)
        for s in snaps:
            code = s.get("template_code") or ""
            if not code:
                continue
            if code not in surveys_map:
                surveys_map[code] = {
                    "template_code": code,
                    "title_ar": s.get("title_ar") or code,
                    "scores": [],
                }
            val = (
                float(s["overall_score_percent"])
                if s.get("aggregated") and s.get("overall_score_percent") is not None
                else None
            )
            surveys_map[code]["scores"].append(val)

    return {
        "cycles": cycles,
        "semesters": cycles,
        "overall_avg": overall_avg,
        "surveys": sorted(surveys_map.values(), key=lambda x: x["template_code"]),
        "has_data": bool(cycles),
        "closed_count": len(closed),
        "is_external": True,
    }


def list_available_semesters_for_trends(conn, department_id: int | None = None) -> list[str]:
    """فصول لها إغلاق أو إجابات."""
    ensure_survey_snapshot_tables(conn)
    cur = conn.cursor()
    sems: set[str] = set()
    for row in cur.execute(
        "SELECT DISTINCT semester FROM survey_semester_closures ORDER BY semester DESC"
    ).fetchall():
        sems.add(str(_row_val(row, 0) or row[0]))
    if table_exists(conn, "survey_responses"):
        for row in cur.execute(
            "SELECT DISTINCT semester FROM survey_responses WHERE status = 'submitted'"
        ).fetchall():
            sems.add(str(_row_val(row, 0) or row[0]))
    if table_exists(conn, "course_evaluations"):
        for row in cur.execute("SELECT DISTINCT semester FROM course_evaluations").fetchall():
            sems.add(str(_row_val(row, 0) or row[0]))
    return sorted(sems, reverse=True)
