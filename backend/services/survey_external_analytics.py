"""تقارير وتصدير استبيانات الدعوات الخارجية (المرحلة 9)."""

from __future__ import annotations

import datetime
import io
import json
from collections import Counter, defaultdict
from typing import Any

import pandas as pd
from flask import send_file

from backend.core.survey_platform import EXTERNAL_SURVEY_CODES, RESPONDENT_ROLE_LABELS
from backend.services.multi_surveys import aggregate_template, get_template_by_code
from backend.services.survey_analytics import (
    COMPLIANCE_STATUS_LABELS_AR,
    LINK_TYPE_LABELS_AR,
    _enrich_questions,
    _metadata_rows,
    _primary_accreditation_label,
    _question_rows,
    _sheet_name_for_code,
    _weakest_strongest,
    accreditation_links_for,
    classify_compliance_status,
    generate_recommendations,
    interpret_overall_score_ar,
)
from backend.services.survey_invites import list_external_cycles
from backend.services.utilities import excel_response_from_frames

EXTERNAL_SCOPE_KEY = "external"


def _row_val(row, idx: int = 0, key: str | None = None):
    if row is None:
        return None
    if hasattr(row, "keys") and key:
        return row[key]
    return row[idx] if not hasattr(row, "keys") else list(row.values())[idx]


def fetch_external_response_rows(
    conn,
    template_code: str,
    cycle_label: str,
) -> list[dict[str, Any]]:
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT id, comments, respondent_profile_json, submitted_at
        FROM survey_responses
        WHERE template_code = ? AND semester = ? AND status = 'submitted'
        ORDER BY id
        """,
        ((template_code or "").strip(), (cycle_label or "").strip()),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows or []:
        if hasattr(row, "keys"):
            d = dict(row)
        else:
            d = {
                "id": row[0],
                "comments": row[1],
                "respondent_profile_json": row[2],
                "submitted_at": row[3],
            }
        try:
            d["profile"] = json.loads(d.get("respondent_profile_json") or "{}")
        except Exception:
            d["profile"] = {}
        out.append(d)
    return out


def _yes_no_ar(value: str) -> str:
    return {"yes": "نعم", "no": "لا"}.get((value or "").strip().lower(), "")


def _profile_breakdown_alumni(rows: list[dict]) -> dict[str, list[dict]]:
    """تجميع أولاً (الواقع المهني) وخامساً (التوصيات ومستقبل البرنامج)."""
    by_year: Counter[int] = Counter()
    by_dept: Counter[str] = Counter()
    by_track: Counter[str] = Counter()
    by_employment: Counter[str] = Counter()
    by_eng_qual: Counter[str] = Counter()
    by_job_rejection: Counter[str] = Counter()
    by_recommend: Counter[str] = Counter()
    by_freeze_support: Counter[str] = Counter()
    by_program_choice: Counter[str] = Counter()
    for r in rows:
        p = r.get("profile") or {}
        y = p.get("graduation_year")
        if y:
            try:
                by_year[int(y)] += 1
            except (TypeError, ValueError):
                pass
        dept = (p.get("department_label") or "").strip()
        if not dept and p.get("department_id"):
            dept = f"قسم #{p.get('department_id')}"
        if dept:
            by_dept[dept] += 1
        track = (p.get("track_label") or p.get("track_code") or "").strip()
        if track:
            by_track[track] += 1
        emp = (p.get("employment_status_label") or p.get("employment_status") or "").strip()
        if emp:
            by_employment[emp] += 1
        eng = (p.get("engineering_qualification_label") or "").strip()
        if not eng:
            eng = _yes_no_ar(p.get("engineering_qualification") or "")
        if eng:
            by_eng_qual[eng] += 1
        rej = _yes_no_ar(p.get("job_rejection") or "")
        if rej:
            by_job_rejection[rej] += 1
        rec = _yes_no_ar(p.get("recommend_enrollment") or "")
        if rec:
            by_recommend[rec] += 1
        freeze = (p.get("program_freeze_support_label") or "").strip() or _yes_no_ar(
            p.get("program_freeze_support") or ""
        )
        if freeze:
            by_freeze_support[freeze] += 1
        prog_key = (p.get("program_development_choice") or "").strip()
        prog_lbl = (p.get("program_development_label") or "").strip()
        if prog_lbl or prog_key:
            from backend.core.survey_platform import program_development_label

            prog = prog_lbl or program_development_label(prog_key)
            by_program_choice[prog] += 1
    return {
        "by_graduation_year": [
            {"سنة_التخرج": y, "عدد_الردود": c} for y, c in sorted(by_year.items())
        ],
        "by_department": [
            {"القسم": k, "عدد_الردود": v} for k, v in by_dept.most_common()
        ],
        "by_track": [
            {"الشعبة_أو_المسار": k, "عدد_الردود": v} for k, v in by_track.most_common()
        ],
        "by_employment_status": [
            {"الحالة_المهنية": k, "عدد_الردود": v} for k, v in by_employment.most_common()
        ],
        "by_engineering_qualification": [
            {"مؤهل_هندسي_مطلوب": k, "عدد_الردود": v} for k, v in by_eng_qual.most_common()
        ],
        "by_job_rejection": [
            {"واجه_رفضاً_وظيفياً": k, "عدد_الردود": v} for k, v in by_job_rejection.most_common()
        ],
        "by_recommend_enrollment": [
            {"ينصح_بالالتحاق": k, "عدد_الردود": v} for k, v in by_recommend.most_common()
        ],
        "by_program_freeze_support": [
            {"يؤيد_التجميد": k, "عدد_الردود": v} for k, v in by_freeze_support.most_common()
        ],
        "by_program_development_choice": [
            {"مقترح_تطوير_البرنامج": k, "عدد_الردود": v} for k, v in by_program_choice.most_common()
        ],
    }


def _normalize_open_text_key(text: str) -> str:
    """مفتاح مقارنة للنصوص الحرة (مسافات + حالة الأحرف)."""
    return " ".join((text or "").split()).casefold()


def _dedupe_open_text_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    دمج النصوص المتطابقة: ظهور مرة واحدة مع حقل العدد.
    يحافظ على ترتيب أول ظهور.
    """
    order: list[str] = []
    by_key: dict[str, dict[str, Any]] = {}
    for entry in entries or []:
        text = str(entry.get("النص") or "").strip()
        if not text:
            continue
        key = _normalize_open_text_key(text)
        name = str(entry.get("الاسم") or "").strip() or "—"
        if key not in by_key:
            order.append(key)
            by_key[key] = {
                "النص": text,
                "العدد": 1,
                "الاسم": name,
                "القسم": str(entry.get("القسم") or "").strip(),
                "المسار": str(entry.get("المسار") or "").strip(),
                "_names": [name],
            }
            continue
        by_key[key]["العدد"] = int(by_key[key]["العدد"]) + 1
        names: list[str] = by_key[key]["_names"]
        if name not in names:
            names.append(name)

    out: list[dict[str, Any]] = []
    for key in order:
        item = by_key[key]
        count = int(item["العدد"])
        names = [n for n in item.pop("_names", []) if n and n != "—"]
        if count > 1:
            item["الاسم"] = "، ".join(names) if names else "عدة مستجيبين"
            item["النص_المعروض"] = f"{item['النص']} (×{count})"
        else:
            item["النص_المعروض"] = item["النص"]
        out.append(item)
    return out


def _alumni_profile_open_texts(rows: list[dict]) -> dict[str, list[dict[str, Any]]]:
    """نصوص حرة من أولاً/خامساً مع دمج المتطابقات وعدد التكرار."""
    buckets: dict[str, list[dict[str, Any]]] = {
        "recommend_reasons": [],
        "job_rejection_reasons": [],
        "adaptation_difficulties": [],
        "missing_skills": [],
        "missing_technologies": [],
        "open_comments": [],
    }
    for r in rows:
        p = r.get("profile") or {}
        name = (p.get("full_name") or "").strip() or "—"
        dept = (p.get("department_label") or "").strip()
        track = (p.get("track_label") or "").strip()

        def _add(key: str, text: str) -> None:
            t = (text or "").strip()
            if not t:
                return
            buckets[key].append(
                {
                    "الاسم": name,
                    "القسم": dept,
                    "المسار": track,
                    "النص": t,
                }
            )

        _add("recommend_reasons", p.get("recommend_reason_text") or "")
        _add("job_rejection_reasons", p.get("job_rejection_reason") or "")
        _add("adaptation_difficulties", p.get("open_adaptation_difficulty") or "")
        _add("missing_skills", p.get("open_missing_skill") or "")
        _add("missing_technologies", p.get("open_missing_technology") or "")
        _add("open_comments", r.get("comments") or "")
    return {k: _dedupe_open_text_entries(v) for k, v in buckets.items()}


def _filter_rows_for_segment(rows: list[dict], seg: dict) -> list[dict]:
    """تصفية الردود حسب شريحة قسم/برنامج."""
    level = (seg.get("segment_level") or "").strip()
    try:
        dept_id = int(seg.get("department_id") or 0)
    except (TypeError, ValueError):
        dept_id = 0
    track_code = (seg.get("track_code") or "").strip()
    out: list[dict] = []
    for r in rows:
        p = r.get("profile") or {}
        try:
            rid = int(p.get("department_id") or 0)
        except (TypeError, ValueError):
            continue
        if dept_id and rid != dept_id:
            continue
        if level == "برنامج":
            if (p.get("track_code") or "").strip() != track_code:
                continue
        out.append(r)
    return out


def _row_cells(row) -> list[Any]:
    """تحويل صف SQLite/Postgres إلى قائمة قيم مرتبة."""
    if row is None:
        return []
    if hasattr(row, "keys"):
        try:
            return [row[k] for k in row.keys()]
        except Exception:
            pass
    try:
        return list(row)
    except TypeError:
        return []


def build_alumni_raw_export_rows(conn, response_rows: list[dict]) -> list[dict[str, Any]]:
    """صف لكل خريج بكل بيانات الملف الشخصي + درجات البنود (للتصدير Excel)."""
    if not response_rows:
        return []
    response_ids = [int(r["id"]) for r in response_rows if r.get("id") is not None]
    answers_by_resp: dict[int, dict[int, float | None]] = defaultdict(dict)
    question_meta: list[tuple[int, int, str]] = []  # sort_order, qid, label
    seen_q: set[int] = set()
    if response_ids:
        cur = conn.cursor()
        placeholders = ",".join("?" for _ in response_ids)
        ans_rows = cur.execute(
            f"""
            SELECT a.response_id AS response_id,
                   a.question_id AS question_id,
                   a.rating AS rating,
                   COALESCE(q.label_ar, '') AS label_ar,
                   COALESCE(q.sort_order, 0) AS sort_order
            FROM survey_answers a
            LEFT JOIN survey_questions q ON q.id = a.question_id
            WHERE a.response_id IN ({placeholders})
            ORDER BY COALESCE(q.sort_order, 0), a.question_id
            """,
            tuple(response_ids),
        ).fetchall()
        for row in ans_rows or []:
            # دعم dict-like و tuple
            if hasattr(row, "keys"):
                keys = set(row.keys())
                rid = int(row["response_id"] if "response_id" in keys else _row_cells(row)[0])
                qid = int(row["question_id"] if "question_id" in keys else _row_cells(row)[1])
                rating = row["rating"] if "rating" in keys else None
                label = str(row["label_ar"] if "label_ar" in keys else "").strip() or f"بند_{qid}"
                sort_raw = row["sort_order"] if "sort_order" in keys else 0
            else:
                vals = _row_cells(row)
                rid = int(vals[0])
                qid = int(vals[1])
                rating = vals[2] if len(vals) > 2 else None
                label = (str(vals[3] or "").strip() if len(vals) > 3 else "") or f"بند_{qid}"
                sort_raw = vals[4] if len(vals) > 4 else 0
            try:
                sort_order = int(sort_raw or 0)
            except (TypeError, ValueError):
                sort_order = 0
            if qid not in seen_q:
                seen_q.add(qid)
                question_meta.append((sort_order, qid, label))
            try:
                answers_by_resp[rid][qid] = float(rating) if rating is not None else None
            except (TypeError, ValueError):
                answers_by_resp[rid][qid] = None

    question_meta.sort(key=lambda t: (t[0], t[1]))

    rows_out: list[dict[str, Any]] = []
    for r in response_rows:
        p = r.get("profile") or {}
        rid = int(r["id"]) if r.get("id") is not None else 0
        base: dict[str, Any] = {
            "معرّف_الرد": rid,
            "تاريخ_الإرسال": r.get("submitted_at") or "",
            "الاسم_الثلاثي": (p.get("full_name") or "").strip(),
            "سنة_التخرج": p.get("graduation_year") or "",
            "القسم": (p.get("department_label") or "").strip(),
            "معرّف_القسم": p.get("department_id") or "",
            "رمز_المسار": (p.get("track_code") or "").strip(),
            "المسار_أو_الشعبة": (p.get("track_label") or "").strip(),
            "الحالة_المهنية": (
                p.get("employment_status_label") or p.get("employment_status") or ""
            ).strip(),
            "المسمى_الوظيفي": (p.get("current_role_text") or "").strip(),
            "مؤهل_هندسي_مطلوب": (
                p.get("engineering_qualification_label")
                or _yes_no_ar(p.get("engineering_qualification") or "")
            ),
            "واجه_رفضاً_وظيفياً": _yes_no_ar(p.get("job_rejection") or ""),
            "سبب_الرفض": (p.get("job_rejection_reason") or "").strip(),
            "ينصح_بالالتحاق": _yes_no_ar(p.get("recommend_enrollment") or ""),
            "سبب_النصح": (p.get("recommend_reason_text") or "").strip(),
            "يؤيد_تجميد_البرنامج": (
                p.get("program_freeze_support_label")
                or _yes_no_ar(p.get("program_freeze_support") or "")
            ),
            "مقترح_تطوير_البرنامج": (p.get("program_development_label") or "").strip(),
            "صعوبة_بدء_العمل": (p.get("open_adaptation_difficulty") or "").strip(),
            "مهارة_تقنية_مفقودة": (p.get("open_missing_skill") or "").strip(),
            "تقنيات_مطلوبة_غير_مغطاة": (p.get("open_missing_technology") or "").strip(),
            "تعليق_مفتوح": (r.get("comments") or "").strip(),
        }
        ans_map = answers_by_resp.get(rid) or {}
        for _sort, qid, label in question_meta:
            col = f"Q{qid}_{label}"[:90]
            base[col] = ans_map.get(qid)
        rows_out.append(base)
    return rows_out


def _profile_breakdown_employer(rows: list[dict]) -> dict[str, list[dict]]:
    by_type: Counter[str] = Counter()
    by_hires: Counter[str] = Counter()
    by_sector: Counter[str] = Counter()
    by_hire_dept: Counter[str] = Counter()
    hire_needs_rows: list[dict[str, str]] = []
    hires_labels = {"yes": "نعم", "no": "لا", "sometimes": "أحياناً"}
    for r in rows:
        p = r.get("profile") or {}
        ot = (p.get("org_type_label") or p.get("org_type") or "").strip()
        if ot:
            by_type[ot] += 1
        h = hires_labels.get((p.get("hires_graduates") or "").strip(), "")
        if h:
            by_hires[h] += 1
        sec = (p.get("sector_label") or "").strip()
        if sec:
            by_sector[sec] += 1
        if (p.get("hires_graduates") or "").strip().lower() in ("yes", "sometimes"):
            dept_labels = p.get("hire_department_labels") or []
            dept_ids = p.get("hire_department_ids") or []
            for i, lbl in enumerate(dept_labels):
                name = (lbl or "").strip()
                if not name and i < len(dept_ids):
                    name = f"قسم #{dept_ids[i]}"
                if name:
                    by_hire_dept[name] += 1
            for item in p.get("hire_department_needs") or []:
                if not isinstance(item, dict):
                    continue
                dept_name = (item.get("department_label") or "").strip()
                if not dept_name:
                    did = item.get("department_id")
                    dept_name = f"قسم #{did}" if did else "—"
                need_text = (item.get("specialty_needs_text") or item.get("needs_text") or "").strip()
                if need_text:
                    hire_needs_rows.append(
                        {
                            "الجهة": (p.get("org_name") or "").strip(),
                            "قسم_التوظيف": dept_name,
                            "التخصص_أو_الشعبة_المطلوبة": need_text,
                        }
                    )
    return {
        "by_org_type": [
            {"نوع_الجهة": k, "عدد_الردود": v} for k, v in by_type.most_common()
        ],
        "by_hires_graduates": [
            {"يوظّف_خريجين": k, "عدد_الردود": v} for k, v in by_hires.most_common()
        ],
        "by_sector": [
            {"القطاع": k, "عدد_الردود": v} for k, v in by_sector.most_common()
        ],
        "by_hire_department": [
            {"قسم_التوظيف": k, "عدد_الجهات": v} for k, v in by_hire_dept.most_common()
        ],
        "by_hire_department_needs": hire_needs_rows,
    }


def build_external_survey_report(
    conn,
    template_code: str,
    *,
    cycle_label: str,
) -> dict[str, Any]:
    """تقرير تحليلي لاستبيان خارجي (دورة دعوة)."""
    code = (template_code or "").strip()
    cycle = (cycle_label or "").strip()
    agg = aggregate_template(conn, code, semester=cycle, department_id=None)
    tpl = get_template_by_code(conn, code) or {}
    questions = _enrich_questions(agg.get("questions") or [])
    weakest, strongest = _weakest_strongest(questions)
    score = agg.get("overall_score_percent")
    compliance = classify_compliance_status(score if agg.get("aggregated") else None)
    response_rows = fetch_external_response_rows(conn, code, cycle)
    open_comments = [
        (r.get("comments") or "").strip()
        for r in response_rows
        if (r.get("comments") or "").strip()
    ]
    if code == "alumni":
        profile_breakdown = _profile_breakdown_alumni(response_rows)
    elif code == "employer_strategic":
        profile_breakdown = _profile_breakdown_employer(response_rows)
    else:
        profile_breakdown = {}

    report = {
        **agg,
        "template_code": code,
        "semester": cycle,
        "cycle_label": cycle,
        "report_kind": "external",
        "department_id": None,
        "department_label": "الكلية — مستجيبون خارجيون",
        "respondent_role": tpl.get("respondent_role"),
        "respondent_label": RESPONDENT_ROLE_LABELS.get(
            (tpl.get("respondent_role") or "").strip(), "—"
        ),
        "questions": questions,
        "weakest_item": weakest,
        "strongest_item": strongest,
        "compliance_status": compliance,
        "compliance_status_ar": COMPLIANCE_STATUS_LABELS_AR.get(compliance, compliance),
        "accreditation_links": accreditation_links_for(
            code, conn, semester=cycle, department_id=None
        ),
        "primary_accreditation": _primary_accreditation_label(
            conn, code, semester=cycle, department_id=None
        ),
        "recommendations": generate_recommendations(questions, agg.get("title_ar") or code),
        "profile_breakdown": profile_breakdown,
        "open_comments": open_comments,
        "interpretation_ar": interpret_overall_score_ar(
            score if agg.get("aggregated") else None, bool(agg.get("aggregated"))
        ),
    }
    from backend.services.survey_external_segments import attach_external_segment_bundle

    report = attach_external_segment_bundle(conn, report, response_rows)
    report = enrich_external_report_segments(report, response_rows)
    if code == "alumni":
        try:
            report["raw_response_rows"] = build_alumni_raw_export_rows(conn, response_rows)
        except Exception:
            import logging

            logging.getLogger(__name__).exception("build_alumni_raw_export_rows failed")
            report["raw_response_rows"] = []
        report["profile_open_texts"] = _alumni_profile_open_texts(response_rows)
    return report


def segment_to_external_report(parent: dict[str, Any], seg: dict[str, Any]) -> dict[str, Any]:
    """تحويل شريحة (قسم/برنامج) إلى تقرير مستقل للعرض والتحليل."""
    score = seg.get("overall_score_percent")
    aggregated = bool(seg.get("aggregated"))
    compliance = classify_compliance_status(score if aggregated else None)
    questions = seg.get("questions") or []
    seg_label = (seg.get("segment_label") or "").strip() or "—"
    level = (seg.get("segment_level") or "").strip()
    title = (parent.get("title_ar") or parent.get("template_code") or "الاستبيان").strip()
    return {
        **seg,
        "template_code": parent.get("template_code"),
        "title_ar": f"{title} — {seg_label}",
        "semester": parent.get("cycle_label"),
        "cycle_label": parent.get("cycle_label"),
        "department_label": seg_label,
        "respondent_label": parent.get("respondent_label"),
        "compliance_status": compliance,
        "compliance_status_ar": COMPLIANCE_STATUS_LABELS_AR.get(compliance, compliance),
        "recommendations": generate_recommendations(questions, seg_label),
        "interpretation_ar": interpret_overall_score_ar(score if aggregated else None, aggregated),
        "scope_note_ar": (
            f"هذا القسم يعرض نتائج «{seg_label}» فقط ({seg.get('response_count') or 0} رد) "
            f"— {level or 'شريحة'} — دون خلط مع أقسام أو برامج أخرى."
        ),
        "accreditation_links": parent.get("accreditation_links") or [],
        "primary_accreditation": parent.get("primary_accreditation"),
    }


def enrich_external_report_segments(
    report: dict[str, Any],
    response_rows: list[dict] | None = None,
) -> dict[str, Any]:
    """إثراء شرائح القسم/البرنامج بتحليل وتقرير تفصيلي منفصل لكل شريحة."""
    from backend.services.survey_analytics import build_survey_report_analysis
    from backend.services.survey_report_charts import build_chart_data_for_survey

    rows = response_rows or []
    code = (report.get("template_code") or "").strip()

    def _attach_profile(seg: dict, filtered: list[dict]) -> None:
        if code != "alumni" or not filtered:
            return
        seg["profile_breakdown"] = _profile_breakdown_alumni(filtered)
        seg["profile_open_texts"] = _alumni_profile_open_texts(filtered)

    def _enrich_group(segments: list[dict] | None) -> list[dict]:
        out: list[dict] = []
        for raw in segments or []:
            seg = dict(raw)
            filtered = _filter_rows_for_segment(rows, seg) if rows else []
            _attach_profile(seg, filtered)
            if not seg.get("aggregated"):
                out.append(seg)
                continue
            detail = segment_to_external_report(report, seg)
            detail["profile_breakdown"] = seg.get("profile_breakdown") or {}
            detail["profile_open_texts"] = seg.get("profile_open_texts") or {}
            seg["detail_report"] = detail
            seg["analysis"] = build_survey_report_analysis(detail)
            chart_data = build_chart_data_for_survey(detail, seg["analysis"])
            if chart_data.get("has_data"):
                seg["chart_data"] = chart_data
            out.append(seg)
        return out

    report["department_segments"] = _enrich_group(report.get("department_segments"))
    report["program_segments"] = _enrich_group(report.get("program_segments"))
    report["hire_department_segments"] = _enrich_group(report.get("hire_department_segments"))

    has_detail = any(
        s.get("aggregated")
        for group in (
            report.get("department_segments") or [],
            report.get("program_segments") or [],
            report.get("hire_department_segments") or [],
        )
        for s in group
    )
    report["has_segment_detail"] = has_detail
    if has_detail:
        report["scope_note_ar"] = (
            "الملخص التالي يجمع كل الأقسام/الشرائح للنظرة العامة ومقارنة سريعة فقط. "
            "التحليل التفصيلي والبنود و«الواقع المهني» و«التوصيات ومستقبل البرنامج» "
            "لكل قسم أو برنامج في الأقسام المنفصلة أدناه — دون خلط النتائج."
        )
        report["suppress_college_item_detail"] = True
    return report


def build_combined_external_report(
    conn,
    *,
    cycle_label: str,
    template_codes: list[str] | None = None,
) -> dict[str, Any]:
    cycle = (cycle_label or "").strip()
    codes = template_codes or sorted(EXTERNAL_SURVEY_CODES)
    reports: list[dict[str, Any]] = []
    for code in codes:
        if code not in EXTERNAL_SURVEY_CODES:
            continue
        if not get_template_by_code(conn, code):
            continue
        reports.append(build_external_survey_report(conn, code, cycle_label=cycle))
    aggregated_count = sum(1 for r in reports if r.get("aggregated"))
    scored = [
        r for r in reports
        if r.get("aggregated") and r.get("overall_score_percent") is not None
    ]
    top3 = sorted(scored, key=lambda x: float(x["overall_score_percent"]), reverse=True)[:3]
    bottom3 = sorted(scored, key=lambda x: float(x["overall_score_percent"]))[:3]
    return {
        "semester": cycle,
        "cycle_label": cycle,
        "report_kind": "external",
        "department_id": None,
        "department_label": "استبيانات خارجية (دعوات)",
        "generated_at": datetime.datetime.utcnow().isoformat(timespec="seconds"),
        "reports": reports,
        "course_eval": None,
        "aggregated_survey_count": aggregated_count,
        "total_survey_count": len(reports),
        "top_surveys": top3,
        "bottom_surveys": bottom3,
    }


def external_executive_summary_rows(reports: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for r in reports:
        rows.append(
            {
                "الاستبيان": r.get("title_ar"),
                "الرمز": r.get("template_code"),
                "الدورة": r.get("cycle_label"),
                "الفئة": r.get("respondent_label"),
                "عدد_الإجابات": r.get("response_count"),
                "الحد_الأدنى": r.get("min_aggregate"),
                "حالة_التجميع": "مكتمل" if r.get("aggregated") else "ناقص",
                "النتيجة_%": r.get("overall_score_percent"),
                "أضعف_بند": r.get("weakest_item", "—"),
                "أقوى_بند": r.get("strongest_item", "—"),
                "معيار_الاعتماد": r.get("primary_accreditation"),
                "حالة_الامتثال": r.get("compliance_status_ar"),
            }
        )
    return rows


def external_accreditation_map_rows(reports: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for r in reports:
        code = r.get("template_code") or ""
        for link in r.get("accreditation_links") or []:
            rows.append(
                {
                    "الاستبيان": r.get("title_ar"),
                    "رمز_الاستبيان": code,
                    "الدورة": r.get("cycle_label"),
                    "المعيار": link.get("standard_code"),
                    "المؤشر": link.get("indicator_code"),
                    "عنوان_المؤشر": link.get("indicator_title_ar"),
                    "نوع_الربط": LINK_TYPE_LABELS_AR.get(
                        link.get("link_type", ""), link.get("link_type")
                    ),
                    "كيفية_الاستفادة": link.get("usage_ar"),
                    "نتيجة_الاستبيان_%": r.get("overall_score_percent"),
                    "حالة_الامتثال": r.get("compliance_status_ar"),
                }
            )
    return rows


def _segment_excel_frames_for_report(report: dict[str, Any]) -> list[tuple[str, pd.DataFrame]]:
    """أوراق مقارنة الشرائح (قسم / برنامج / توظيف)."""
    frames: list[tuple[str, pd.DataFrame]] = []
    code = report.get("template_code") or ""

    dept_rows = report.get("department_comparison_rows") or []
    if dept_rows:
        frames.append(("مقارنة_الأقسام", pd.DataFrame(dept_rows)))

    prog_rows = report.get("program_comparison_rows") or []
    if prog_rows:
        frames.append(("مقارنة_البرامج", pd.DataFrame(prog_rows)))

    hire_rows = report.get("hire_department_comparison_rows") or []
    if hire_rows:
        frames.append(("مقارنة_توظيف_الأقسام", pd.DataFrame(hire_rows)))

    for seg in report.get("department_segments") or []:
        if not seg.get("aggregated"):
            continue
        name = _sheet_name_for_code(f"{code}_dept_{seg.get('department_id')}", seg.get("segment_label") or "")
        frames.append((name[:31], pd.DataFrame(_question_rows(seg))))

    for seg in report.get("program_segments") or []:
        if not seg.get("aggregated"):
            continue
        name = _sheet_name_for_code(
            f"{code}_prog_{seg.get('department_id')}_{seg.get('track_code')}",
            seg.get("segment_label") or "",
        )
        frames.append((name[:31], pd.DataFrame(_question_rows(seg))))

    for seg in report.get("hire_department_segments") or []:
        if not seg.get("aggregated"):
            continue
        name = _sheet_name_for_code(
            f"{code}_hire_{seg.get('department_id')}",
            seg.get("segment_label") or "",
        )
        frames.append((name[:31], pd.DataFrame(_question_rows(seg))))

    return frames


def _append_alumni_raw_and_open_frames(
    frames: list[tuple[str, pd.DataFrame]],
    report: dict[str, Any],
) -> None:
    raw_rows = report.get("raw_response_rows") or []
    if raw_rows:
        frames.append(("بيانات_الخريجين_كاملة", pd.DataFrame(raw_rows)))
    open_texts = report.get("profile_open_texts") or {}
    for key, sheet in (
        ("recommend_reasons", "أسباب_النصح_كلية"),
        ("job_rejection_reasons", "أسباب_الرفض_كلية"),
        ("adaptation_difficulties", "صعوبات_العمل_كلية"),
        ("missing_skills", "مهارات_مفقودة_كلية"),
        ("missing_technologies", "تقنيات_مفقودة_كلية"),
        ("open_comments", "تعليقات_بالأسماء"),
    ):
        rows = open_texts.get(key) or []
        if rows:
            frames.append((sheet[:31], pd.DataFrame(rows)))


def external_package_excel_frames(combined: dict[str, Any]) -> list[tuple[str, pd.DataFrame]]:
    from backend.services.survey_analytics import _analysis_excel_frames

    reports = combined.get("reports") or []
    frames: list[tuple[str, pd.DataFrame]] = [
        ("ملخص_تنفيذي", pd.DataFrame(external_executive_summary_rows(reports))),
        ("ربط_المعايير", pd.DataFrame(external_accreditation_map_rows(reports))),
    ]
    analysis = combined.get("analysis")
    if analysis:
        insert_at = 1
        for af_name, af_df in _analysis_excel_frames(analysis):
            frames.insert(insert_at, (af_name, af_df))
            insert_at += 1
    for r in reports:
        code = r.get("template_code") or ""
        for seg_name, seg_df in _segment_excel_frames_for_report(r):
            frames.append((seg_name, seg_df))
        frames.append(
            (_sheet_name_for_code(code, r.get("title_ar") or ""), pd.DataFrame(_question_rows(r)))
        )
        pb = r.get("profile_breakdown") or {}
        for sheet_suffix, rows in pb.items():
            if rows:
                frames.append(
                    (
                        _sheet_name_for_code(f"{code}_{sheet_suffix}", sheet_suffix)[:31],
                        pd.DataFrame(rows),
                    )
                )
        _append_alumni_raw_and_open_frames(frames, r)
        comments = r.get("open_comments") or []
        if comments and not (r.get("profile_open_texts") or {}).get("open_comments"):
            frames.append(
                (
                    _sheet_name_for_code(f"{code}_comments", "تعليقات")[:31],
                    pd.DataFrame([{"تعليق_مفتوح": c} for c in comments]),
                )
            )
    meta = _metadata_rows(combined)
    meta.append({"البند": "نوع_التقرير", "القيمة": "استبيانات خارجية (دعوات)"})
    meta.append({"البند": "الدورة", "القيمة": combined.get("cycle_label")})
    frames.append(("بيانات_وصفية", pd.DataFrame(meta)))
    return frames


def external_single_survey_excel_frames(report: dict[str, Any]) -> list[tuple[str, pd.DataFrame]]:
    from backend.services.survey_analytics import single_survey_excel_frames

    frames = single_survey_excel_frames(report)
    seg_frames = _segment_excel_frames_for_report(report)
    for i, seg_frame in enumerate(seg_frames):
        frames.insert(1 + i, seg_frame)
    summary_patch = {
        "الدورة": report.get("cycle_label"),
        "نوع_التقرير": "خارجي (دعوة)",
    }
    if frames and frames[0][0] == "ملخص" and not frames[0][1].empty:
        row = frames[0][1].iloc[0].to_dict()
        row.update(summary_patch)
        frames[0] = ("ملخص", pd.DataFrame([row]))
    pb = report.get("profile_breakdown") or {}
    code = report.get("template_code") or ""
    for sheet_suffix, rows in pb.items():
        if rows:
            frames.append(
                (
                    _sheet_name_for_code(f"{sheet_suffix}", sheet_suffix)[:31],
                    pd.DataFrame(rows),
                )
            )
    _append_alumni_raw_and_open_frames(frames, report)
    comments = report.get("open_comments") or []
    if comments and not (report.get("profile_open_texts") or {}).get("open_comments"):
        frames.append(
            ("تعليقات_مفتوحة", pd.DataFrame([{"تعليق": c} for c in comments]))
        )
    return frames


def export_external_package_xlsx(conn, *, cycle_label: str):
    from backend.services.survey_analytics import (
        build_combined_survey_analysis,
        survey_excel_bytes_from_frames,
    )
    from backend.services.survey_report_charts import build_chart_data_for_combined

    combined = build_combined_external_report(conn, cycle_label=cycle_label)
    combined["analysis"] = build_combined_survey_analysis(combined)
    chart_data = build_chart_data_for_combined(combined, combined["analysis"])
    slug = (cycle_label or "external").replace(" ", "_")[:40]
    now = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    fname = f"survey_external_{slug}_{now}.xlsx"
    raw = survey_excel_bytes_from_frames(
        external_package_excel_frames(combined), chart_data=chart_data
    )
    return send_file(
        io.BytesIO(raw),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=fname,
    )


def prepare_external_combined_pdf_context(conn, *, cycle_label: str) -> dict[str, Any]:
    from backend.services.survey_analytics import (
        build_combined_survey_analysis,
        enrich_survey_export_context,
    )

    combined = build_combined_external_report(conn, cycle_label=cycle_label)
    for r in combined.get("reports") or []:
        if not r.get("interpretation_ar"):
            r["interpretation_ar"] = interpret_overall_score_ar(
                r.get("overall_score_percent"), r.get("aggregated")
            )
    combined["analysis"] = build_combined_survey_analysis(combined)
    ctx = {
        **combined,
        "filename_prefix": f"survey_external_{(cycle_label or 'report').replace(' ', '_')[:40]}",
        "is_external_report": True,
        "executive_summary": external_executive_summary_rows(combined.get("reports") or []),
        "accreditation_rows": external_accreditation_map_rows(combined.get("reports") or []),
        "comparative_rows": [],
        "metadata_rows": _metadata_rows(combined)
        + [
            {"البند": "نوع_التقرير", "القيمة": "استبيانات خارجية"},
            {"البند": "الدورة", "القيمة": cycle_label},
        ],
        "narrative_paragraphs": (combined.get("analysis") or {}).get("narrative_paragraphs")
        or [
            f"تقرير دورة استبيانات خارجية (دعوات): «{cycle_label}». "
            f"يشمل استشارة القطاع واستبيان الخريج عند توفر بيانات.",
        ],
        "title": f"تقرير الاستبيانات الخارجية — {cycle_label}",
        "course_eval": None,
    }
    return enrich_survey_export_context(ctx, for_pdf=False)


def prepare_external_single_pdf_context(
    conn,
    template_code: str,
    *,
    cycle_label: str,
) -> dict[str, Any] | None:
    from backend.services.survey_analytics import (
        build_survey_report_analysis,
        enrich_survey_export_context,
    )

    code = (template_code or "").strip()
    if code not in EXTERNAL_SURVEY_CODES:
        return None
    report = build_external_survey_report(conn, code, cycle_label=cycle_label)
    if report.get("has_segment_detail"):
        report["analysis"] = None
    else:
        report["analysis"] = build_survey_report_analysis(report)
    ctx = {
        "report": report,
        "title": f"تقرير {report.get('title_ar') or code}",
        "filename_prefix": f"survey_{code}_{(cycle_label or 'report').replace(' ', '_')[:30]}",
        "is_external_report": True,
        "metadata_rows": [
            {"البند": "الدورة", "القيمة": cycle_label},
            {"البند": "نوع_التقرير", "القيمة": "خارجي (دعوة)"},
            {"البند": "فئة_المستجيب", "القيمة": report.get("respondent_label")},
            {"البند": "عدد_الإجابات", "القيمة": report.get("response_count")},
            {"البند": "النتيجة_%", "القيمة": report.get("overall_score_percent")},
        ],
    }
    return enrich_survey_export_context(ctx, for_pdf=False)


def build_external_export_bytes(
    conn,
    template_code: str,
    *,
    cycle_label: str,
) -> tuple[bytes, str, dict[str, Any]]:
    from backend.services.survey_analytics import (
        build_survey_report_analysis,
        survey_excel_bytes_from_frames,
    )
    from backend.services.survey_report_charts import build_chart_data_for_survey

    report = build_external_survey_report(conn, template_code, cycle_label=cycle_label)
    report["analysis"] = build_survey_report_analysis(report)
    chart_data = build_chart_data_for_survey(report, report["analysis"])
    raw = survey_excel_bytes_from_frames(
        external_single_survey_excel_frames(report), chart_data=chart_data
    )
    slug = (cycle_label or "report").replace(" ", "_")[:40]
    filename = f"survey_{template_code}_{slug}.xlsx"
    return raw, filename, report


def survey_external_metrics_summary(conn) -> dict[str, Any]:
    """ملخص أحدث دورات الاستبيانات الخارجية للوحة الجودة."""
    out: dict[str, Any] = {"cycles": list_external_cycles(conn), "templates": {}}
    for code in sorted(EXTERNAL_SURVEY_CODES):
        cycles = list_external_cycles(conn, code)
        latest = cycles[0] if cycles else None
        entry: dict[str, Any] = {"latest_cycle": latest, "cycles": cycles}
        if latest:
            agg = aggregate_template(conn, code, semester=latest, department_id=None)
            entry.update(
                {
                    "title_ar": agg.get("title_ar"),
                    "response_count": agg.get("response_count"),
                    "min_aggregate": agg.get("min_aggregate"),
                    "aggregated": agg.get("aggregated"),
                    "overall_score_percent": agg.get("overall_score_percent"),
                }
            )
        out["templates"][code] = entry
    return out


def latest_external_aggregate_for_indicator(
    conn,
    indicator_code: str,
) -> list[str]:
    """نصوص داعمة من أحدث دورة خارجية لكل استبيان مرتبط بالمؤشر."""
    from backend.core.survey_platform import SURVEY_ACCREDITATION_MAP

    code_u = (indicator_code or "").strip().upper()
    parts: list[str] = []
    for tpl_code, links in SURVEY_ACCREDITATION_MAP.items():
        if tpl_code not in EXTERNAL_SURVEY_CODES:
            continue
        if not any((l.get("indicator_code") or "").upper() == code_u for l in links):
            continue
        cycles = list_external_cycles(conn, tpl_code)
        if not cycles:
            continue
        cycle = cycles[0]
        agg = aggregate_template(conn, tpl_code, semester=cycle, department_id=None)
        if not agg.get("aggregated") or agg.get("overall_score_percent") is None:
            continue
        title = (agg.get("title_ar") or tpl_code)[:36]
        parts.append(f"{title} [{cycle}]: {agg['overall_score_percent']}%")
    return parts
