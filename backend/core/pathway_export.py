"""تصدير Excel لشبكة الخطة وتقدم المسار."""

from __future__ import annotations

from typing import Any

import pandas as pd

from backend.core.pathway_plan_grid import build_program_plan_grid


def frames_for_program_plan_export(cur, program_id: int, program_code: str = "") -> list[tuple[str, pd.DataFrame]]:
    grid = build_program_plan_grid(cur, int(program_id))
    rows_level = []
    for lv in grid.get("levels") or []:
        for c in lv.get("courses") or []:
            rows_level.append(
                {
                    "المستوى": lv.get("level_no"),
                    "الرمز": c.get("course_code"),
                    "العنوان": c.get("title_ar"),
                    "الوحدات": c.get("units"),
                    "النطاق": c.get("requirement_scope_label"),
                }
            )
    rows_edges = []
    for e in grid.get("edges") or []:
        rows_edges.append(
            {
                "المقرر": e.get("to_code"),
                "يتطلب سابقاً": e.get("from_code"),
                "ملاحظة": e.get("note"),
            }
        )
    summary = pd.DataFrame(
        [
            {
                "program_id": program_id,
                "program_code": program_code,
                "عدد_المستويات": grid.get("level_count"),
                "عدد_المقررات": grid.get("course_count"),
                "أعلى_مستوى": grid.get("max_level"),
            }
        ]
    )
    return [
        ("ملخص", summary),
        ("شبكة_المستويات", pd.DataFrame(rows_level) if rows_level else pd.DataFrame()),
        ("متطلبات_سابقة", pd.DataFrame(rows_edges) if rows_edges else pd.DataFrame()),
    ]


def frames_for_pathway_progress_export(data: dict[str, Any]) -> list[tuple[str, pd.DataFrame]]:
    if data.get("status") != "ok":
        return [("خطأ", pd.DataFrame([{"رسالة": data.get("message", "خطأ")}]))]
    totals = data.get("totals") or {}
    summary = pd.DataFrame(
        [
            {
                "الرقم": data.get("student_id"),
                "الاسم": data.get("student_name"),
                "مرحلة_المسار": data.get("pathway_stage"),
                "الشعبة": data.get("track_code"),
                "وضع_التشغيل": data.get("operating_mode"),
                "منجز_الخطة": totals.get("plan_completed_units"),
                "هدف_التخرج": totals.get("graduation_target"),
                "متبقي_التخرج": totals.get("graduation_remaining"),
                "اتجاه_عام_منجز": totals.get("college_general_completed"),
                "اتجاه_عام_هدف": totals.get("college_general_target"),
            }
        ]
    )
    scope_rows = []
    for sc, b in (data.get("by_scope") or {}).items():
        scope_rows.append(
            {
                "النطاق": b.get("label") or sc,
                "منجز": b.get("completed_units"),
                "مطلوب": b.get("required_units"),
                "متبقي": b.get("remaining_units"),
            }
        )
    pre = data.get("summary_pre_track")
    if pre:
        scope_rows.append(
            {
                "النطاق": pre.get("label"),
                "منجز": pre.get("completed_units"),
                "مطلوب": pre.get("required_units"),
                "متبقي": pre.get("remaining_units"),
            }
        )
    course_rows = []
    for c in data.get("courses") or []:
        course_rows.append(
            {
                "الرمز": c.get("course_code"),
                "العنوان": c.get("title_ar"),
                "النطاق": c.get("requirement_scope_label"),
                "الوحدات": c.get("units"),
                "منجز": "نعم" if c.get("completed") else "لا",
                "برنامج": c.get("program_code"),
            }
        )
    gap_rows = []
    for c in data.get("plan_gaps") or []:
        gap_rows.append(
            {
                "الرمز": c.get("course_code"),
                "العنوان": c.get("title_ar"),
                "النطاق": c.get("requirement_scope_label"),
            }
        )
    return [
        ("ملخص", summary),
        ("حسب_النطاق", pd.DataFrame(scope_rows) if scope_rows else pd.DataFrame()),
        ("المقررات", pd.DataFrame(course_rows) if course_rows else pd.DataFrame()),
        ("فجوات", pd.DataFrame(gap_rows) if gap_rows else pd.DataFrame()),
    ]
