"""حزمة ZIP لتصدير تقارير الاستبيانات (المرحلة 4)."""

from __future__ import annotations

import io
import re
import zipfile
from typing import Any, Callable

from backend.services.multi_surveys import list_templates
from backend.services.survey_analytics import (
    build_combined_survey_report,
    package_excel_frames,
    prepare_combined_pdf_context,
    prepare_single_survey_pdf_context,
)
from backend.services.survey_accreditation import build_survey_export_bytes
from backend.services.utilities import excel_bytes_from_frames, pdf_bytes_from_html

_FILENAME_SAFE = re.compile(r"[^\w\-.]+", re.UNICODE)


def _safe_zip_name(name: str) -> str:
    base = _FILENAME_SAFE.sub("_", (name or "file").strip())
    return base[:80] or "file"


def _exportable_template_codes(conn, *, include_course_eval: bool) -> list[str]:
    codes = [
        t["code"]
        for t in list_templates(conn)
        if not int(t.get("legacy_course_eval") or 0)
    ]
    if include_course_eval:
        codes.append("student_course")
    return codes


def build_survey_bundle_zip(
    conn,
    *,
    semester: str,
    department_id: int | None = None,
    include_course_eval: bool = True,
    include_pdf: bool = True,
    render_template: Callable[..., str] | None = None,
) -> tuple[bytes, str, dict[str, Any]]:
    """
    يُنشئ حزمة ZIP: package.xlsx/pdf + تقرير Excel/PDF لكل استبيان.
    render_template: دالة Flask render_template (مطلوبة لملفات PDF).
    """
    sem = (semester or "").strip()
    sem_slug = _safe_zip_name(sem.replace(" ", "_")[:40])
    combined = build_combined_survey_report(
        conn,
        semester=sem,
        department_id=department_id,
        include_course_eval=include_course_eval,
    )
    buf = io.BytesIO()
    meta: dict[str, Any] = {
        "semester": sem,
        "files": [],
        "pdf_skipped": [],
        "pdf_errors": [],
    }

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        pkg_xlsx = excel_bytes_from_frames(package_excel_frames(combined))
        zf.writestr("package.xlsx", pkg_xlsx)
        meta["files"].append("package.xlsx")

        if include_pdf and render_template:
            ctx = prepare_combined_pdf_context(
                conn,
                semester=sem,
                department_id=department_id,
                include_course_eval=include_course_eval,
            )
            html = render_template("survey_export_package.html", for_pdf=True, **ctx)
            pdf_raw, pdf_err = pdf_bytes_from_html(html)
            if pdf_raw:
                zf.writestr("package.pdf", pdf_raw)
                meta["files"].append("package.pdf")
            else:
                meta["pdf_skipped"].append("package.pdf")
                if pdf_err:
                    meta["pdf_errors"].append(f"package.pdf: {pdf_err}")

        for code in _exportable_template_codes(conn, include_course_eval=include_course_eval):
            xlsx_raw, xlsx_name, _report = build_survey_export_bytes(
                conn, code, semester=sem, department_id=department_id
            )
            zip_path = f"reports/{_safe_zip_name(code)}.xlsx"
            zf.writestr(zip_path, xlsx_raw)
            meta["files"].append(zip_path)

            if include_pdf and render_template:
                ctx = prepare_single_survey_pdf_context(
                    conn, code, semester=sem, department_id=department_id
                )
                if ctx:
                    html = render_template("survey_export_single.html", for_pdf=True, **ctx)
                    pdf_raw, pdf_err = pdf_bytes_from_html(html)
                    pdf_path = f"reports/{_safe_zip_name(code)}.pdf"
                    if pdf_raw:
                        zf.writestr(pdf_path, pdf_raw)
                        meta["files"].append(pdf_path)
                    else:
                        meta["pdf_skipped"].append(pdf_path)
                        if pdf_err:
                            meta["pdf_errors"].append(f"{pdf_path}: {pdf_err}")

        readme_lines = [
            f"حزمة تصدير استبيانات — الفصل: {sem}",
            f"عدد الملفات: {len(meta['files'])}",
            "",
            "المحتويات:",
            "- package.xlsx — تقرير موحّد متعدد الأوراق",
            "- package.pdf — تقرير PDF موحّد (إن وُجد wkhtmltopdf)",
            "- reports/ — تقرير Excel وPDF لكل استبيان",
            "",
        ]
        if meta["pdf_skipped"]:
            readme_lines.append("ملفات PDF لم تُضمَّن:")
            for p in meta["pdf_skipped"]:
                readme_lines.append(f"  - {p}")
        if meta["pdf_errors"]:
            readme_lines.append("")
            readme_lines.append("أسباب غياب PDF:")
            for e in meta["pdf_errors"][:5]:
                readme_lines.append(f"  - {e}")
        zf.writestr("README.txt", "\n".join(readme_lines).encode("utf-8"))
        meta["files"].append("README.txt")

    buf.seek(0)
    filename = f"survey_bundle_{sem_slug}.zip"
    return buf.getvalue(), filename, meta


def build_external_survey_bundle_zip(
    conn,
    *,
    cycle_label: str,
    include_pdf: bool = True,
    render_template: Callable[..., str] | None = None,
) -> tuple[bytes, str, dict[str, Any]]:
    """حزمة ZIP لدورة استبيانات خارجية (خريجون + قطاع)."""
    from backend.core.survey_platform import EXTERNAL_SURVEY_CODES
    from backend.services.survey_external_analytics import (
        build_combined_external_report,
        build_external_export_bytes,
        external_package_excel_frames,
        prepare_external_combined_pdf_context,
        prepare_external_single_pdf_context,
    )

    cycle = (cycle_label or "").strip()
    cycle_slug = _safe_zip_name(cycle.replace(" ", "_")[:40])
    combined = build_combined_external_report(conn, cycle_label=cycle)
    buf = io.BytesIO()
    meta: dict[str, Any] = {
        "cycle_label": cycle,
        "files": [],
        "pdf_skipped": [],
        "pdf_errors": [],
        "report_kind": "external",
    }

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        pkg_xlsx = excel_bytes_from_frames(external_package_excel_frames(combined))
        zf.writestr("package.xlsx", pkg_xlsx)
        meta["files"].append("package.xlsx")

        if include_pdf and render_template:
            from backend.services.survey_analytics import enrich_survey_export_context

            ctx = prepare_external_combined_pdf_context(conn, cycle_label=cycle)
            ctx = enrich_survey_export_context(ctx, for_pdf=True)
            html = render_template("survey_export_package.html", for_pdf=True, **ctx)
            pdf_raw, pdf_err = pdf_bytes_from_html(html)
            if pdf_raw:
                zf.writestr("package.pdf", pdf_raw)
                meta["files"].append("package.pdf")
            else:
                meta["pdf_skipped"].append("package.pdf")
                if pdf_err:
                    meta["pdf_errors"].append(f"package.pdf: {pdf_err}")

        for code in sorted(EXTERNAL_SURVEY_CODES):
            xlsx_raw, _name, _report = build_external_export_bytes(
                conn, code, cycle_label=cycle
            )
            zip_path = f"reports/{_safe_zip_name(code)}.xlsx"
            zf.writestr(zip_path, xlsx_raw)
            meta["files"].append(zip_path)

            if include_pdf and render_template:
                from backend.services.survey_analytics import enrich_survey_export_context

                ctx = prepare_external_single_pdf_context(conn, code, cycle_label=cycle)
                if ctx:
                    ctx = enrich_survey_export_context(ctx, for_pdf=True)
                    html = render_template("survey_export_single.html", for_pdf=True, **ctx)
                    pdf_raw, pdf_err = pdf_bytes_from_html(html)
                    pdf_path = f"reports/{_safe_zip_name(code)}.pdf"
                    if pdf_raw:
                        zf.writestr(pdf_path, pdf_raw)
                        meta["files"].append(pdf_path)
                    else:
                        meta["pdf_skipped"].append(pdf_path)
                        if pdf_err:
                            meta["pdf_errors"].append(f"{pdf_path}: {pdf_err}")

        readme_lines = [
            f"حزمة استبيانات خارجية — الدورة: {cycle}",
            f"عدد الملفات: {len(meta['files'])}",
            "",
            "المحتويات:",
            "- package.xlsx — تقرير موحّد (خريجون + قطاع)",
            "- package.pdf — PDF موحّد",
            "- reports/ — تقرير لكل استبيان خارجي",
        ]
        zf.writestr("README.txt", "\n".join(readme_lines).encode("utf-8"))
        meta["files"].append("README.txt")

    buf.seek(0)
    filename = f"survey_external_bundle_{cycle_slug}.zip"
    return buf.getvalue(), filename, meta
