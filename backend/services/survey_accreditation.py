"""ربط نتائج الاستبيانات بمؤشرات الاعتماد (المرحلة 3)."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

from backend.core.accreditation_catalog import resolve_catalog_version
from backend.core.survey_platform import LINK_TYPE_LABELS_AR
from backend.services.accreditation_manual import _indicator_id_by_code
from backend.services.multi_surveys import aggregate_template

HYBRID_MANUAL_WEIGHT = 0.4
HYBRID_SURVEY_WEIGHT = 0.6
FF01_SURVEY_TEMPLATE = "student_facilities"


def accreditation_links_display(
    template_code: str,
    conn=None,
    *,
    catalog_version: str | None = None,
    semester: str | None = None,
    department_id: int | None = None,
    link_cache=None,
) -> list[dict[str, str]]:
    if conn is None:
        return []
    from backend.services.survey_accreditation_links import (
        resolve_survey_accreditation_links,
    )

    return resolve_survey_accreditation_links(
        conn,
        template_code,
        catalog_version=catalog_version,
        semester=semester,
        department_id=department_id,
        link_cache=link_cache,
    )


def primary_evidence_indicator_code(
    template_code: str,
    conn=None,
    *,
    catalog_version: str | None = None,
    semester: str | None = None,
    department_id: int | None = None,
    link_cache=None,
) -> str | None:
    if conn is None:
        return None
    from backend.services.survey_accreditation_links import (
        primary_evidence_indicator_code_resolved,
    )

    return primary_evidence_indicator_code_resolved(
        conn,
        template_code,
        catalog_version=catalog_version,
        semester=semester,
        department_id=department_id,
        link_cache=link_cache,
    )


def survey_template_aggregate(
    conn,
    template_code: str,
    *,
    semester: str,
    department_id: int | None = None,
) -> dict[str, Any]:
    """نتيجة مجمّعة لقالب استبيان (أو تقييم المقرر)."""
    code = (template_code or "").strip()
    if code == "student_course":
        from backend.services.survey_analytics import build_course_eval_report

        return build_course_eval_report(conn, semester=semester, department_id=department_id)
    return aggregate_template(conn, code, semester=semester, department_id=department_id)


def hybrid_ff01_score(
    manual_percent: float,
    survey_agg: dict[str, Any],
) -> tuple[float, str]:
    """دمج الإدخال اليدوي مع استبيان المرافق."""
    manual = float(manual_percent or 0)
    if survey_agg.get("aggregated") and survey_agg.get("overall_score_percent") is not None:
        survey = float(survey_agg["overall_score_percent"])
        combined = manual * HYBRID_MANUAL_WEIGHT + survey * HYBRID_SURVEY_WEIGHT
        detail = (
            f"هجين FF-01-1: إدخال يدوي {manual:.1f}% + استبيان المرافق {survey:.1f}% "
            f"(أوزان {int(HYBRID_MANUAL_WEIGHT * 100)}/{int(HYBRID_SURVEY_WEIGHT * 100)}) "
            f"→ {combined:.1f}%"
        )
        return round(combined, 1), detail
    return round(manual, 1), f"تقييم البنية التحتية (إدخال يدوي): {manual:.1f}%"


def compute_hybrid_infrastructure_rating(
    conn,
    *,
    semester: str,
    department_id: int | None = None,
) -> tuple[float, str]:
    from backend.services.quality_metrics import _institutional_inputs, term_label_from_conn

    sem = (semester or term_label_from_conn(conn)).strip()
    cur = conn.cursor()
    inst = _institutional_inputs(cur, sem, department_id)
    manual = float(inst.get("infrastructure_rating") or 75.0)
    survey_agg = survey_template_aggregate(
        conn, FF01_SURVEY_TEMPLATE, semester=sem, department_id=department_id
    )
    return hybrid_ff01_score(manual, survey_agg)


def survey_supplementary_notes(
    conn,
    *,
    semester: str,
    department_id: int | None,
    indicator_code: str,
) -> str:
    """ملاحظات من استبيانات مربوطة يدوياً بالمؤشر."""
    code = (indicator_code or "").strip().upper()
    parts: list[str] = []
    from backend.services.accreditation_evidence_bindings import list_bindings

    seen_tpl: set[str] = set()
    for b in list_bindings(
        conn, semester=semester, department_id=department_id, indicator_id=None
    ):
        if (b.get("indicator_code") or "").strip().upper() != code:
            continue
        if (b.get("binding_kind") or "").strip().lower() != "survey":
            continue
        ref = (b.get("source_ref") or "").strip()
        if not ref.startswith("survey:"):
            continue
        tpl_code = ref.split(":", 1)[1].strip()
        if not tpl_code or tpl_code in seen_tpl:
            continue
        seen_tpl.add(tpl_code)
        agg = survey_template_aggregate(
            conn, tpl_code, semester=semester, department_id=department_id
        )
        if not agg.get("aggregated") or agg.get("overall_score_percent") is None:
            continue
        title = (agg.get("title_ar") or tpl_code)[:40]
        parts.append(f"{title}: {agg['overall_score_percent']}%")
    try:
        from backend.services.survey_external_analytics import (
            latest_external_aggregate_for_indicator,
        )

        parts.extend(latest_external_aggregate_for_indicator(conn, code))
    except Exception:
        pass
    return "؛ ".join(parts[:6])


def resolve_indicator_id(
    conn, indicator_code: str, catalog_version: str | None = None
) -> int | None:
    from backend.core.accreditation_catalog import CATALOG_VERSION

    code = (indicator_code or "").strip().upper()
    if not code:
        return None
    if catalog_version:
        return _indicator_id_by_code(conn, code, catalog_version.strip())
    for ver in (
        resolve_catalog_version(conn),
        "QAA-2023.4-INST",
        "QAA-2023.4-PROG-UG",
        CATALOG_VERSION,
    ):
        iid = _indicator_id_by_code(conn, code, ver)
        if iid:
            return iid
    return None


def build_survey_export_bytes(
    conn,
    template_code: str,
    *,
    semester: str,
    department_id: int | None = None,
    export_format: str | None = None,
) -> tuple[bytes, str, dict[str, Any]]:
    """إنشاء ملف Excel أو Word كشاهد لاستبيان واحد."""
    from backend.services.survey_analytics import (
        build_course_eval_report,
        build_survey_report,
        course_eval_sections_export_bytes,
        single_survey_excel_frames,
    )
    from backend.services.utilities import excel_bytes_from_frames

    from backend.core.survey_platform import EXTERNAL_SURVEY_CODES

    code = (template_code or "").strip()
    if code == "course_eval_sections":
        return course_eval_sections_export_bytes(
            conn,
            semester=semester,
            department_id=department_id,
            fmt=export_format or "docx",
        )
    if code == "student_course":
        report = build_course_eval_report(conn, semester=semester, department_id=department_id)
    elif code in EXTERNAL_SURVEY_CODES:
        from backend.services.survey_external_analytics import build_external_export_bytes

        raw, filename, report = build_external_export_bytes(
            conn, code, cycle_label=semester
        )
        return raw, filename, report
    else:
        report = build_survey_report(conn, code, semester=semester, department_id=department_id)
    raw = excel_bytes_from_frames(single_survey_excel_frames(report))
    sem_slug = re.sub(r"[^\w\-]+", "_", (semester or "report"))[:40]
    filename = f"survey_{code}_{sem_slug}.xlsx"
    return raw, filename, report


def register_survey_as_evidence(
    conn,
    *,
    template_code: str,
    semester: str,
    department_id: int | None,
    indicator_code: str | None,
    uploaded_by: str,
    export_format: str | None = None,
) -> dict[str, Any]:
    """رفع تقرير استبيان كشاهد في خريطة الامتثال."""
    from backend.services.accreditation_evidence import save_file_evidence

    ind_code = (indicator_code or "").strip().upper()
    iid = resolve_indicator_id(conn, ind_code) if ind_code else None
    if ind_code and not iid:
        raise ValueError(f"المؤشر {ind_code} غير موجود في كتالوج الاعتماد")

    raw, filename, report = build_survey_export_bytes(
        conn,
        template_code,
        semester=semester,
        department_id=department_id,
        export_format=export_format,
    )
    dept_label = (report.get("department_label") or "").strip()
    title_base = report.get("title_ar") or template_code
    if dept_label:
        title_ar = f"{title_base} — {dept_label} — {semester}"
    else:
        title_ar = f"نتائج {title_base} — {semester}"
    score_txt = report.get("overall_score_percent")
    score_part = f"{score_txt}%" if score_txt is not None else "بانتظار التجميع"
    if template_code == "course_eval_sections":
        description = (
            f"تصدير آلي من منصة الاستبيانات — تقييم المقررات حسب الشعبة. "
            f"متوسط النتائج المجمّعة: {score_part}. "
            f"شعب مجمّعة: {report.get('response_count') or 0}."
        )
    else:
        description = (
            f"تصدير آلي من منصة الاستبيانات."
            + (f" المؤشر: {ind_code}." if ind_code else "")
            + f" النتيجة المجمّعة: {score_part}. "
            f"عدد الإجابات: {report.get('response_count') or 0}."
        )
    mime = report.get("_mime") or "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    result = save_file_evidence(
        conn,
        semester=semester,
        department_id=department_id,
        raw=raw,
        original_name=filename,
        mime_type=mime,
        uploaded_by=uploaded_by,
        indicator_id=iid,
        title_ar=title_ar,
        description=description,
    )
    from backend.core.survey_platform import EXTERNAL_SURVEY_CODES

    map_q = (
        f"cycle={quote(semester, safe='')}"
        if template_code in EXTERNAL_SURVEY_CODES
        else f"semester={quote(semester, safe='')}"
    )
    out = {
        **result,
        "template_code": template_code,
        "compliance_map_url": f"/academic_quality/accreditation/map?{map_q}",
    }
    if ind_code:
        out["indicator_code"] = ind_code
    return out


def build_program_survey_summary(
    conn,
    *,
    semester: str,
    department_id: int | None = None,
) -> dict[str, Any]:
    """ملخص استبيانات للتقرير البرامجي."""
    from backend.services.survey_analytics import build_combined_survey_report

    combined = build_combined_survey_report(
        conn, semester=semester, department_id=department_id, include_course_eval=True
    )
    rows: list[dict[str, Any]] = []
    for r in combined.get("reports") or []:
        rows.append(
            {
                "title_ar": r.get("title_ar"),
                "template_code": r.get("template_code"),
                "respondent_label": r.get("respondent_label"),
                "response_count": r.get("response_count"),
                "min_aggregate": r.get("min_aggregate"),
                "aggregated": r.get("aggregated"),
                "overall_score_percent": r.get("overall_score_percent"),
                "primary_indicator": _primary_indicator_for_template(
                    r.get("template_code") or "", conn
                ),
                "primary_indicator_title": primary_indicator_title_for_template(
                    r.get("template_code") or "", conn
                ),
            }
        )
    ce = combined.get("course_eval")
    if ce:
        rows.append(
            {
                "title_ar": ce.get("title_ar"),
                "template_code": "student_course",
                "respondent_label": ce.get("respondent_label"),
                "response_count": ce.get("response_count"),
                "min_aggregate": ce.get("min_aggregate"),
                "aggregated": ce.get("aggregated"),
                "overall_score_percent": ce.get("overall_score_percent"),
                "primary_indicator": _primary_indicator_for_template("student_course", conn),
                "primary_indicator_title": primary_indicator_title_for_template(
                    "student_course", conn
                ),
            }
        )
    external_rows: list[dict[str, Any]] = []
    try:
        from backend.services.survey_external_analytics import (
            build_combined_external_report,
            survey_external_metrics_summary,
        )
        from backend.services.survey_invites import list_external_cycles

        ext = survey_external_metrics_summary(conn)
        for code, info in (ext.get("templates") or {}).items():
            if not info.get("latest_cycle"):
                continue
            external_rows.append(
                {
                    "title_ar": info.get("title_ar") or code,
                    "template_code": code,
                    "respondent_label": "خارجي",
                    "cycle_label": info.get("latest_cycle"),
                    "response_count": info.get("response_count"),
                    "min_aggregate": info.get("min_aggregate"),
                    "aggregated": info.get("aggregated"),
                    "overall_score_percent": info.get("overall_score_percent"),
                    "primary_indicator": _primary_indicator_for_template(code, conn),
                    "primary_indicator_title": primary_indicator_title_for_template(code, conn),
                }
            )
    except Exception:
        external_rows = []

    return {
        "semester": combined.get("semester"),
        "department_label": combined.get("department_label"),
        "aggregated_count": combined.get("aggregated_survey_count"),
        "total_count": combined.get("total_survey_count"),
        "rows": rows,
        "external_rows": external_rows,
        "external_cycles": list_external_cycles(conn) if external_rows else [],
    }


def _primary_indicator_for_template(template_code: str, conn=None) -> str:
    code = primary_evidence_indicator_code(template_code, conn)
    return code if code else "—"


def primary_indicator_title_for_template(
    template_code: str,
    conn=None,
    *,
    semester: str | None = None,
    department_id: int | None = None,
) -> str:
    if conn is None:
        return "—"
    from backend.services.survey_accreditation_links import primary_survey_link

    lk = primary_survey_link(
        conn,
        template_code,
        semester=semester,
        department_id=department_id,
    )
    if not lk:
        return "—"
    return (
        lk.get("indicator_title_ar")
        or lk.get("usage_ar")
        or lk.get("indicator_code")
        or "—"
    ).strip()
