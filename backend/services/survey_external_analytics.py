"""تقارير وتصدير استبيانات الدعوات الخارجية (المرحلة 9)."""

from __future__ import annotations

import datetime
import json
from collections import Counter, defaultdict
from typing import Any

import pandas as pd

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


def _profile_breakdown_alumni(rows: list[dict]) -> dict[str, list[dict]]:
    by_year: Counter[int] = Counter()
    by_dept: Counter[str] = Counter()
    by_track: Counter[str] = Counter()
    for r in rows:
        p = r.get("profile") or {}
        y = p.get("graduation_year")
        if y:
            by_year[int(y)] += 1
        dept = (p.get("department_label") or "").strip()
        if not dept and p.get("department_id"):
            dept = f"قسم #{p.get('department_id')}"
        if dept:
            by_dept[dept] += 1
        track = (p.get("track_label") or p.get("track_code") or "").strip()
        if track:
            by_track[track] += 1
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
    }


def _profile_breakdown_employer(rows: list[dict]) -> dict[str, list[dict]]:
    by_type: Counter[str] = Counter()
    by_hires: Counter[str] = Counter()
    by_sector: Counter[str] = Counter()
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

    return {
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


def external_package_excel_frames(combined: dict[str, Any]) -> list[tuple[str, pd.DataFrame]]:
    reports = combined.get("reports") or []
    frames: list[tuple[str, pd.DataFrame]] = [
        ("ملخص_تنفيذي", pd.DataFrame(external_executive_summary_rows(reports))),
        ("ربط_المعايير", pd.DataFrame(external_accreditation_map_rows(reports))),
    ]
    for r in reports:
        code = r.get("template_code") or ""
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
        comments = r.get("open_comments") or []
        if comments:
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
    comments = report.get("open_comments") or []
    if comments:
        frames.append(
            ("تعليقات_مفتوحة", pd.DataFrame([{"تعليق": c} for c in comments]))
        )
    return frames


def export_external_package_xlsx(conn, *, cycle_label: str):
    combined = build_combined_external_report(conn, cycle_label=cycle_label)
    slug = (cycle_label or "external").replace(" ", "_")[:40]
    return excel_response_from_frames(
        external_package_excel_frames(combined),
        filename_prefix=f"survey_external_{slug}",
    )


def prepare_external_combined_pdf_context(conn, *, cycle_label: str) -> dict[str, Any]:
    combined = build_combined_external_report(conn, cycle_label=cycle_label)
    for r in combined.get("reports") or []:
        if not r.get("interpretation_ar"):
            r["interpretation_ar"] = interpret_overall_score_ar(
                r.get("overall_score_percent"), r.get("aggregated")
            )
    return {
        **combined,
        "for_pdf": True,
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
        "narrative_paragraphs": [
            f"تقرير دورة استبيانات خارجية (دعوات): «{cycle_label}». "
            f"يشمل استشارة القطاع واستبيان الخريج عند توفر بيانات.",
        ],
        "title": f"تقرير الاستبيانات الخارجية — {cycle_label}",
        "course_eval": None,
    }


def prepare_external_single_pdf_context(
    conn,
    template_code: str,
    *,
    cycle_label: str,
) -> dict[str, Any] | None:
    code = (template_code or "").strip()
    if code not in EXTERNAL_SURVEY_CODES:
        return None
    report = build_external_survey_report(conn, code, cycle_label=cycle_label)
    return {
        "report": report,
        "title": f"تقرير {report.get('title_ar') or code}",
        "for_pdf": True,
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


def build_external_export_bytes(
    conn,
    template_code: str,
    *,
    cycle_label: str,
) -> tuple[bytes, str, dict[str, Any]]:
    from backend.services.utilities import excel_bytes_from_frames

    report = build_external_survey_report(conn, template_code, cycle_label=cycle_label)
    raw = excel_bytes_from_frames(external_single_survey_excel_frames(report))
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
