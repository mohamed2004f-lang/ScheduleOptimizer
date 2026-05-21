"""دفتر اعتماد — أطر Excel/PDF من خريطة الامتثال (هـ-5)."""

from __future__ import annotations

from typing import Any

import pandas as pd

from backend.core.accreditation_catalog import COMPLIANCE_STATUS_LABELS, DOMAIN_LABELS
from backend.core.accreditation_evidence_catalog import INSTITUTIONAL_EVIDENCE_CHECKLIST
from backend.services.accreditation_manual import PLAN_PRIORITY_LABELS, PLAN_STATUS_LABELS


def frames_for_accreditation_workbook(
    map_data: dict[str, Any],
    *,
    manual_bundle: dict[str, Any] | None = None,
    checklist: list[dict[str, Any]] | None = None,
    plans: list[dict[str, Any]] | None = None,
) -> list[tuple[str, pd.DataFrame]]:
    """بناء أوراق دفتر الاعتماد."""
    if map_data.get("status") != "ok":
        return [("خطأ", pd.DataFrame([{"رسالة": map_data.get("message", "خطأ")}]))]

    summary = map_data.get("summary") or {}
    summary_df = pd.DataFrame(
        [
            {
                "إصدار_الكتالوج": map_data.get("catalog_version"),
                "الفصل": map_data.get("semester"),
                "النطاق": map_data.get("scope_label_ar"),
                "إجمالي_المؤشرات": summary.get("indicators_total"),
                "لم_يبدأ": summary.get("not_started"),
                "قيد_التنفيذ": summary.get("in_progress"),
                "جزئي": summary.get("partial"),
                "متحقق": summary.get("met"),
                "فجوة": summary.get("gap"),
                "تقدم_التوثيق_%": summary.get("documented_progress_percent"),
            }
        ]
    )

    indicator_rows: list[dict[str, Any]] = []
    for dom in map_data.get("domains") or []:
        dom_label = dom.get("label") or DOMAIN_LABELS.get(dom.get("code"), dom.get("code"))
        for st in dom.get("standards") or []:
            for ind in st.get("indicators") or []:
                asm = ind.get("assessment") or {}
                indicator_rows.append(
                    {
                        "المحور": dom_label,
                        "رمز_المعيار": st.get("code"),
                        "المعيار": st.get("title_ar"),
                        "رمز_المؤشر": ind.get("code"),
                        "المؤشر": ind.get("title_ar"),
                        "المصدر": ind.get("source_type_label"),
                        "الحالة": asm.get("compliance_status_label")
                        or COMPLIANCE_STATUS_LABELS.get(
                            asm.get("compliance_status"), asm.get("compliance_status")
                        ),
                        "الدرجة_%": asm.get("score_percent"),
                        "ملاحظات": asm.get("notes") or "",
                        "عدد_الأدلة": ind.get("evidence_count", 0),
                    }
                )
    indicators_df = pd.DataFrame(indicator_rows) if indicator_rows else pd.DataFrame()

    manual_rows: list[dict[str, Any]] = []
    for sec in (manual_bundle or {}).get("sections") or []:
        for f in sec.get("fields") or []:
            manual_rows.append(
                {
                    "القسم": sec.get("title_ar"),
                    "الحقل": f.get("label_ar"),
                    "القيمة": (sec.get("values") or {}).get(f.get("key")),
                }
            )
    manual_df = pd.DataFrame(manual_rows) if manual_rows else pd.DataFrame()

    chk_rows = []
    for item in checklist or []:
        chk_rows.append(
            {
                "البند": item.get("title_ar"),
                "الوصف": item.get("description_ar"),
                "مرفقات": item.get("attached_count", 0),
                "مكتمل": "نعم" if item.get("has_evidence") else "لا",
            }
        )
    if not chk_rows:
        for key, title, desc, _ in INSTITUTIONAL_EVIDENCE_CHECKLIST:
            chk_rows.append({"البند": title, "الوصف": desc, "مرفقات": 0, "مكتمل": "لا"})
    checklist_df = pd.DataFrame(chk_rows)

    plan_rows = []
    for p in plans or []:
        plan_rows.append(
            {
                "العنوان": p.get("title_ar"),
                "الإجراء": p.get("action_ar"),
                "المؤشر": p.get("indicator_code") or "",
                "الموعد": p.get("target_date"),
                "الحالة": p.get("status_label") or PLAN_STATUS_LABELS.get(p.get("status"), ""),
                "الأولوية": p.get("priority_label") or PLAN_PRIORITY_LABELS.get(p.get("priority"), ""),
                "المسؤول": p.get("owner_ar"),
                "ملاحظات": p.get("notes"),
            }
        )
    plans_df = pd.DataFrame(plan_rows) if plan_rows else pd.DataFrame()

    return [
        ("ملخص", summary_df),
        ("المؤشرات", indicators_df),
        ("إدخال_يدوي", manual_df),
        ("قائمة_التحقق", checklist_df),
        ("خطط_التحسين", plans_df),
    ]


def html_for_accreditation_workbook(map_data: dict[str, Any], **extras) -> str:
    """HTML مبسط لتصدير PDF."""
    frames = frames_for_accreditation_workbook(map_data, **extras)
    parts = [
        "<html><head><meta charset='utf-8'>",
        "<style>body{font-family:Tahoma,Arial;direction:rtl;}",
        "table{border-collapse:collapse;width:100%;margin:12px 0;font-size:12px;}",
        "th,td{border:1px solid #ccc;padding:6px;text-align:right;}",
        "th{background:#eee;} h2{font-size:16px;}</style></head><body>",
        f"<h1>دفتر اعتماد مؤسسي — {map_data.get('semester', '')}</h1>",
        f"<p>{map_data.get('scope_label_ar', '')} · إصدار {map_data.get('catalog_version', '')}</p>",
    ]
    for sheet_name, df in frames:
        if df.empty:
            continue
        parts.append(f"<h2>{sheet_name}</h2>")
        parts.append(df.to_html(index=False, escape=True))
    parts.append("</body></html>")
    return "".join(parts)
