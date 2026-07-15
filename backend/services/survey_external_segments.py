"""تجميع وتحليل استبيانات خارجية حسب القسم / البرنامج / أقسام التوظيف."""

from __future__ import annotations

from typing import Any

from backend.services.multi_surveys import get_template_by_code, list_template_questions, likert_labels_ar
from backend.services.survey_analytics import (
    SECTION_SCORE_LABELS_AR,
    _enrich_questions,
    _weakest_strongest,
    classify_section_score,
)


def _profile(row: dict) -> dict:
    return row.get("profile") or {}


def aggregate_external_from_rows(
    conn,
    template_code: str,
    response_rows: list[dict],
) -> dict[str, Any]:
    """تجميع Likert من مجموعة ردود خارجية."""
    template = get_template_by_code(conn, template_code)
    if not template:
        return {"aggregated": False, "response_count": 0, "questions": []}
    min_n = int(template.get("min_aggregate") or 5)
    count = len(response_rows)
    questions_tpl = list_template_questions(conn, int(template["id"]))
    base = {
        "template_code": template_code,
        "title_ar": template.get("title_ar"),
        "response_count": count,
        "min_aggregate": min_n,
        "aggregated": count >= min_n,
        "overall_score_percent": None,
        "questions": [],
        "likert_labels": likert_labels_ar(),
    }
    if count < min_n:
        base["questions"] = [
            {
                "question_id": int(q["id"]),
                "sort_order": int(q.get("sort_order") or 0),
                "label_ar": q.get("label_ar"),
                "avg_rating": None,
                "score_percent": None,
            }
            for q in questions_tpl
        ]
        return base

    response_ids = [int(r["id"]) for r in response_rows if r.get("id") is not None]
    if not response_ids:
        return base

    cur = conn.cursor()
    placeholders = ",".join("?" for _ in response_ids)
    avg_rows = cur.execute(
        f"""
        SELECT a.question_id, AVG(a.rating * 1.0) AS avg_rating
        FROM survey_answers a
        WHERE a.response_id IN ({placeholders})
        GROUP BY a.question_id
        """,
        tuple(response_ids),
    ).fetchall()
    avg_map: dict[int, float] = {}
    for row in avg_rows or []:
        if hasattr(row, "keys"):
            qid = int(row["question_id"])
            avg_map[qid] = float(row["avg_rating"] or 0)
        else:
            qid = int(row[0])
            avg_map[qid] = float(row[1] or 0)

    per_question: list[dict] = []
    overall_vals: list[float] = []
    for q in questions_tpl:
        qid = int(q["id"])
        avg5 = avg_map.get(qid)
        pct = round((avg5 / 5.0) * 100.0, 1) if avg5 else None
        if avg5:
            overall_vals.append(float(avg5))
        per_question.append(
            {
                "question_id": qid,
                "sort_order": int(q.get("sort_order") or 0),
                "label_ar": q.get("label_ar"),
                "avg_rating": round(avg5, 2) if avg5 is not None else None,
                "score_percent": pct,
            }
        )
    overall_pct = None
    if overall_vals:
        overall_pct = round((sum(overall_vals) / len(overall_vals) / 5.0) * 100.0, 1)
    base["questions"] = per_question
    base["overall_score_percent"] = overall_pct
    return base


def _comparison_row(
    *,
    level: str,
    label: str,
    segment_key: str,
    count: int,
    agg: dict[str, Any],
    extra: dict | None = None,
) -> dict[str, Any]:
    score = agg.get("overall_score_percent")
    aggregated = bool(agg.get("aggregated"))
    cls = classify_section_score(float(score) if aggregated and score is not None else None)
    row = {
        "المستوى": level,
        "الشريحة": label,
        "segment_key": segment_key,
        "عدد_الردود": count,
        "الحد_الأدنى": agg.get("min_aggregate"),
        "النتيجة_%": score if aggregated else None,
        "التصنيف": SECTION_SCORE_LABELS_AR.get(cls, cls),
        "التجميع": "مكتمل" if aggregated else "ناقص",
    }
    if extra:
        row.update(extra)
    return row


def _build_segment_entry(
    conn,
    template_code: str,
    *,
    segment_key: str,
    segment_label: str,
    segment_level: str,
    response_rows: list[dict],
    extra_meta: dict | None = None,
) -> dict[str, Any]:
    agg = aggregate_external_from_rows(conn, template_code, response_rows)
    questions = _enrich_questions(agg.get("questions") or [])
    weakest, strongest = _weakest_strongest(questions)
    entry = {
        "segment_key": segment_key,
        "segment_label": segment_label,
        "segment_level": segment_level,
        "response_count": agg.get("response_count"),
        "min_aggregate": agg.get("min_aggregate"),
        "aggregated": agg.get("aggregated"),
        "overall_score_percent": agg.get("overall_score_percent"),
        "questions": questions,
        "weakest_item": weakest,
        "strongest_item": strongest,
        "comparison_row": _comparison_row(
            level=segment_level,
            label=segment_label,
            segment_key=segment_key,
            count=int(agg.get("response_count") or 0),
            agg=agg,
            extra=extra_meta,
        ),
    }
    if extra_meta:
        entry.update(extra_meta)
    return entry


def _filter_alumni_department(rows: list[dict], department_id: int) -> list[dict]:
    return [
        r
        for r in rows
        if int(_profile(r).get("department_id") or 0) == int(department_id)
    ]


def _filter_alumni_program(
    rows: list[dict], department_id: int, track_code: str
) -> list[dict]:
    tc = (track_code or "").strip()
    out: list[dict] = []
    for r in rows:
        p = _profile(r)
        if int(p.get("department_id") or 0) != int(department_id):
            continue
        row_track = (p.get("track_code") or "").strip()
        if row_track == tc:
            out.append(r)
    return out


def _filter_employer_hire_department(rows: list[dict], department_id: int) -> list[dict]:
    dept_id = int(department_id)
    out: list[dict] = []
    for r in rows:
        p = _profile(r)
        hire_ids = p.get("hire_department_ids") or []
        try:
            ids = {int(x) for x in hire_ids}
        except (TypeError, ValueError):
            ids = set()
        if dept_id in ids:
            out.append(r)
    return out


def build_alumni_segment_bundle(
    conn,
    template_code: str,
    response_rows: list[dict],
) -> dict[str, Any]:
    """شرائح الخريج: قسم + برنامج (قسم + مسار)."""
    dept_map: dict[int, str] = {}
    program_map: dict[str, tuple[int, str, str, str]] = {}

    for r in response_rows:
        p = _profile(r)
        dept_id = p.get("department_id")
        if dept_id is None:
            continue
        try:
            did = int(dept_id)
        except (TypeError, ValueError):
            continue
        if did <= 0:
            continue
        dept_label = (p.get("department_label") or f"قسم #{did}").strip()
        dept_map[did] = dept_label

        track_code = (p.get("track_code") or "").strip()
        track_label = (p.get("track_label") or "").strip()
        if track_code:
            prog_key = f"dept:{did}:track:{track_code}"
            prog_label = f"{dept_label} — {track_label or track_code}"
            program_map[prog_key] = (did, track_code, prog_label, track_label)

    department_segments: list[dict] = []
    department_comparison: list[dict] = []
    for did in sorted(dept_map.keys(), key=lambda x: dept_map[x]):
        filtered = _filter_alumni_department(response_rows, did)
        seg = _build_segment_entry(
            conn,
            template_code,
            segment_key=f"dept:{did}",
            segment_label=dept_map[did],
            segment_level="قسم",
            response_rows=filtered,
            extra_meta={"department_id": did, "track_code": ""},
        )
        department_segments.append(seg)
        department_comparison.append(seg["comparison_row"])

    program_segments: list[dict] = []
    program_comparison: list[dict] = []
    for prog_key in sorted(program_map.keys(), key=lambda k: program_map[k][2]):
        did, track_code, prog_label, track_label = program_map[prog_key]
        filtered = _filter_alumni_program(response_rows, did, track_code)
        seg = _build_segment_entry(
            conn,
            template_code,
            segment_key=prog_key,
            segment_label=prog_label,
            segment_level="برنامج",
            response_rows=filtered,
            extra_meta={
                "department_id": did,
                "track_code": track_code,
                "track_label": track_label,
            },
        )
        program_segments.append(seg)
        program_comparison.append(seg["comparison_row"])

    return {
        "department_segments": department_segments,
        "program_segments": program_segments,
        "department_comparison_rows": department_comparison,
        "program_comparison_rows": program_comparison,
    }


def build_employer_hire_segment_bundle(
    conn,
    template_code: str,
    response_rows: list[dict],
) -> dict[str, Any]:
    """شرائح القطاع حسب الأقسام التي توظّف منها الجهة."""
    dept_map: dict[int, str] = {}
    for r in response_rows:
        p = _profile(r)
        if (p.get("hires_graduates") or "").strip().lower() not in ("yes", "sometimes"):
            continue
        ids = p.get("hire_department_ids") or []
        labels = p.get("hire_department_labels") or []
        for i, raw_id in enumerate(ids):
            try:
                did = int(raw_id)
            except (TypeError, ValueError):
                continue
            if did <= 0:
                continue
            lbl = labels[i] if i < len(labels) else f"قسم #{did}"
            dept_map[did] = str(lbl).strip() or f"قسم #{did}"

    hire_segments: list[dict] = []
    hire_comparison: list[dict] = []
    for did in sorted(dept_map.keys(), key=lambda x: dept_map[x]):
        filtered = _filter_employer_hire_department(response_rows, did)
        seg = _build_segment_entry(
            conn,
            template_code,
            segment_key=f"hire_dept:{did}",
            segment_label=dept_map[did],
            segment_level="قسم (توظيف)",
            response_rows=filtered,
            extra_meta={"department_id": did, "hire_department_id": did},
        )
        hire_segments.append(seg)
        hire_comparison.append(seg["comparison_row"])

    return {
        "hire_department_segments": hire_segments,
        "hire_department_comparison_rows": hire_comparison,
    }


def attach_external_segment_bundle(
    conn,
    report: dict[str, Any],
    response_rows: list[dict],
) -> dict[str, Any]:
    """إرفاق شرائح التقرير حسب نوع الاستبيان."""
    code = (report.get("template_code") or "").strip()
    if code == "alumni":
        report.update(build_alumni_segment_bundle(conn, code, response_rows))
    elif code == "employer_strategic":
        report.update(build_employer_hire_segment_bundle(conn, code, response_rows))
    return report
