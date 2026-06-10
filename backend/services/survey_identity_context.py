"""سياق هوية الكلية لاستبيانات المستجيبين الخارجيين — بلا رموز أو اختصارات."""

from __future__ import annotations

import re
from typing import Any

_ABBREV_PAREN = re.compile(
    r"\([^)]*(?:CLO|PLO|GLO|IG|I/R/M|KPI|ABET)[^)]*\)",
    re.IGNORECASE,
)
_ABBREV_TOKEN = re.compile(
    r"\b(?:IG|GLO|PLO|CLO|KPI|CR|QA|GV|SS|FF|HR)\d*(?:\.\d+)?\b",
    re.IGNORECASE,
)


def sanitize_survey_display_text(text: str) -> str:
    """إزالة الرموز والاختصارات من النص المعروض للمستجيب الخارجي."""
    if not text:
        return ""
    cleaned = _ABBREV_PAREN.sub("", str(text))
    cleaned = _ABBREV_TOKEN.sub("", cleaned)
    return " ".join(cleaned.split())


def build_employer_identity_panel(conn) -> dict[str, Any]:
    """لوحة قراءة فقط: رؤية، رسالة، قيم، ملخص الخطة، أهداف، مخرجات خريج."""
    from backend.core.college_identity_schema import ensure_college_identity_schema
    from backend.services.college_identity_portal import _active_identity, _strategic_goals_tree

    ensure_college_identity_schema(conn)
    cur = conn.cursor()
    identity = _active_identity(cur)
    goals_tree = _strategic_goals_tree(cur)

    strategic_goals: list[dict[str, Any]] = []
    for root in goals_tree:
        item: dict[str, Any] = {
            "title_ar": sanitize_survey_display_text(root.get("title_ar") or ""),
            "description_ar": sanitize_survey_display_text(root.get("description") or ""),
            "children": [],
        }
        for child in root.get("children") or []:
            item["children"].append(
                {
                    "title_ar": sanitize_survey_display_text(child.get("title_ar") or ""),
                    "description_ar": sanitize_survey_display_text(child.get("description") or ""),
                }
            )
        strategic_goals.append(item)

    graduate_outcomes: list[dict[str, str]] = []
    try:
        rows = cur.execute(
            """
            SELECT title_ar, COALESCE(description, '') AS description
            FROM college_graduate_outcomes
            WHERE COALESCE(is_active, 1) = 1
            ORDER BY sort_order, code
            """
        ).fetchall()
        for row in rows or []:
            d = dict(row) if hasattr(row, "keys") else {"title_ar": row[0], "description": row[1]}
            graduate_outcomes.append(
                {
                    "title_ar": sanitize_survey_display_text(d.get("title_ar") or ""),
                    "description_ar": sanitize_survey_display_text(d.get("description") or ""),
                }
            )
    except Exception:
        pass

    core_values: list[dict[str, str]] = []
    for value in identity.get("values") or []:
        if not isinstance(value, dict):
            continue
        core_values.append(
            {
                "title_ar": sanitize_survey_display_text(value.get("title_ar") or ""),
                "description_ar": sanitize_survey_display_text(value.get("description") or ""),
            }
        )

    plan_summary = (identity.get("strategic_plan_summary_ar") or "").strip()
    if not plan_summary:
        plan_summary = (identity.get("intro_ar") or "").strip()

    return {
        "vision_ar": (identity.get("vision_ar") or "").strip(),
        "mission_ar": (identity.get("mission_ar") or "").strip(),
        "strategic_plan_summary_ar": sanitize_survey_display_text(plan_summary),
        "core_values": core_values,
        "strategic_goals": strategic_goals,
        "graduate_outcomes": graduate_outcomes,
        "intro_note_ar": (
            "اطلعوا أدناه على رؤية الكلية ورسالتها وأهدافها الاستراتيجية وملخص خطتها "
            "ومخرجات تعلم الخريج على مستوى الكلية، ثم أجيبوا على الأسئلة من منظور قطاعكم."
        ),
    }
