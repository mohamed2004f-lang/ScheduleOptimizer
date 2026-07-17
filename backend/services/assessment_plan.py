"""خطة تقييم المقرر: 4 تصنيفات رئيسية + بنود أعمال المقرر — المجموع = 100%."""
from __future__ import annotations

import json
from typing import Any

ASSESSMENT_MAIN_CODES = (
    ("midterm", "اختبار جزئي"),
    ("practical", "اختبار عملي"),
    ("final", "اختبار نهائي"),
)
ASSESSMENT_COURSEWORK_CODES = (
    ("quiz", "اختبارات قصيرة"),
    ("assignment", "واجبات"),
    ("report", "تقرير"),
    ("participation", "مشاركة"),
    ("presentation", "عرض تقديمي"),
    ("worksheet", "ورقة عمل"),
    ("other", "أخرى"),
)


def empty_assessment_plan() -> dict:
    return {
        "midterm": 0,
        "practical": 0,
        "final": 0,
        "coursework": {
            "quiz": 0,
            "assignment": 0,
            "report": 0,
            "participation": 0,
            "presentation": 0,
            "worksheet": 0,
            "other": 0,
            "other_label": "",
        },
    }


def _as_weight(val: Any) -> float:
    try:
        if val is None or val == "":
            return 0.0
        return float(val)
    except (TypeError, ValueError):
        return 0.0


def normalize_assessment_plan(raw: Any) -> dict:
    plan = empty_assessment_plan()
    if not raw:
        return plan
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return plan
    if not isinstance(raw, dict):
        return plan
    for code, _label in ASSESSMENT_MAIN_CODES:
        plan[code] = round(_as_weight(raw.get(code)), 2)
    cw_in = raw.get("coursework") if isinstance(raw.get("coursework"), dict) else {}
    cw = plan["coursework"]
    for code, _label in ASSESSMENT_COURSEWORK_CODES:
        cw[code] = round(_as_weight(cw_in.get(code)), 2)
    cw["other_label"] = str(cw_in.get("other_label") or "").strip()
    return plan


def coursework_sum(plan: dict) -> float:
    cw = (plan or {}).get("coursework") or {}
    return round(sum(_as_weight(cw.get(code)) for code, _ in ASSESSMENT_COURSEWORK_CODES), 2)


def assessment_plan_total(plan: dict) -> float:
    plan = normalize_assessment_plan(plan)
    main = sum(_as_weight(plan.get(code)) for code, _ in ASSESSMENT_MAIN_CODES)
    return round(main + coursework_sum(plan), 2)


def validate_assessment_plan(plan: dict) -> tuple[bool, str]:
    plan = normalize_assessment_plan(plan)
    for code, label in ASSESSMENT_MAIN_CODES:
        w = _as_weight(plan.get(code))
        if w < 0 or w > 100:
            return False, f"وزن «{label}» غير صالح"
    cw = plan["coursework"]
    for code, label in ASSESSMENT_COURSEWORK_CODES:
        w = _as_weight(cw.get(code))
        if w < 0 or w > 100:
            return False, f"وزن «{label}» غير صالح"
    other_w = _as_weight(cw.get("other"))
    if other_w > 0 and not (cw.get("other_label") or "").strip():
        return False, "أدخل وصف بند «أخرى» عند تحديد وزن له"
    total = assessment_plan_total(plan)
    if abs(total - 100.0) > 0.01:
        return False, f"المجموع الكلي يجب أن يساوي 100% (الحالي: {total}%)"
    return True, ""


def assessment_plan_to_methods(plan: dict) -> list[dict]:
    plan = normalize_assessment_plan(plan)
    out: list[dict] = []
    for i, (code, label) in enumerate(ASSESSMENT_MAIN_CODES):
        w = _as_weight(plan.get(code))
        if w <= 0:
            continue
        out.append(
            {
                "code": code,
                "method_label": label,
                "weight_pct": w,
                "group": "main",
                "sort_order": i,
                "notes": "",
            }
        )
    cw = plan["coursework"]
    children = []
    for j, (code, label) in enumerate(ASSESSMENT_COURSEWORK_CODES):
        w = _as_weight(cw.get(code))
        if w <= 0:
            continue
        disp = label
        if code == "other" and (cw.get("other_label") or "").strip():
            disp = f"أخرى: {cw['other_label'].strip()}"
        children.append(
            {
                "code": code,
                "method_label": disp,
                "weight_pct": w,
                "group": "coursework_item",
                "sort_order": j,
                "notes": "",
            }
        )
    cw_total = coursework_sum(plan)
    if cw_total > 0:
        out.append(
            {
                "code": "coursework",
                "method_label": "أعمال المقرر",
                "weight_pct": cw_total,
                "group": "coursework",
                "sort_order": 50,
                "notes": "",
                "children": children,
            }
        )
    return out


def assessment_schema_payload() -> dict:
    return {
        "main": [{"code": c, "label_ar": lab} for c, lab in ASSESSMENT_MAIN_CODES],
        "coursework": [{"code": c, "label_ar": lab} for c, lab in ASSESSMENT_COURSEWORK_CODES],
        "total_required": 100,
    }


def dumps_plan(plan: dict) -> str:
    return json.dumps(normalize_assessment_plan(plan), ensure_ascii=False)
