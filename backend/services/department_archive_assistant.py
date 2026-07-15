"""مساعد أرشيف القسم — اقتراح وتصنيف وصياغة وفجوات (بدون أتمتة امتثال)."""

from __future__ import annotations

from typing import Any

from backend.core.department_archive_catalog import (
    ARCHIVE_RECORD_TYPES,
    CLASSIFY_KEYWORDS,
    DRAFT_TEMPLATES,
    suggestions_for_type,
)
from backend.services.department_archive import (
    archive_checklist,
    list_archive_items,
    suggest_qaa_for_item,
)


def classify_archive_text(
    *,
    title_ar: str = "",
    body_text: str = "",
    filename: str = "",
) -> dict[str, Any]:
    blob = f"{title_ar}\n{body_text}\n{filename}".lower()
    scores: dict[str, int] = {k: 0 for k in CLASSIFY_KEYWORDS}
    for code, words in CLASSIFY_KEYWORDS.items():
        for w in words:
            if w.lower() in blob or w in f"{title_ar} {body_text} {filename}":
                scores[code] += 1
    ranked = sorted(scores.items(), key=lambda x: (-x[1], x[0]))
    best_code, best_score = ranked[0]
    if best_score <= 0:
        return {
            "status": "ok",
            "suggested_type": None,
            "confidence": "low",
            "scores": scores,
            "message_ar": "تعذّر التصنيف تلقائياً — اختر النوع يدوياً.",
            "suggestion_only": True,
        }
    meta = ARCHIVE_RECORD_TYPES[best_code]
    conf = "high" if best_score >= 3 else ("medium" if best_score == 2 else "low")
    return {
        "status": "ok",
        "suggested_type": best_code,
        "suggested_type_label_ar": meta["title_ar"],
        "confidence": conf,
        "scores": scores,
        "qaa_suggestions": suggestions_for_type(best_code),
        "message_ar": f"اقتراح التصنيف: {meta['title_ar']} (مستوى الثقة: {conf}). يحتاج موافقة المستخدم.",
        "suggestion_only": True,
    }


def draft_archive_document(
    *,
    record_type: str,
    fields: dict[str, Any] | None = None,
    department_name_ar: str = "",
) -> dict[str, Any]:
    rtype = (record_type or "").strip()
    tpl = DRAFT_TEMPLATES.get(rtype)
    if not tpl:
        raise ValueError("لا يوجد قالب لهذا النوع")
    f = dict(fields or {})
    payload = {
        "title_ar": f.get("title_ar") or "…",
        "doc_date": f.get("doc_date") or "YYYY-MM-DD",
        "ref_number": f.get("ref_number") or "—",
        "party_ar": f.get("party_ar") or "—",
        "body_text": f.get("body_text") or "…",
        "follow_up_status": f.get("follow_up_status") or "open",
        "department_name_ar": department_name_ar or f.get("department_name_ar") or "القسم",
    }
    text = tpl.format(**payload)
    return {
        "status": "ok",
        "record_type": rtype,
        "record_type_label_ar": ARCHIVE_RECORD_TYPES[rtype]["title_ar"],
        "draft_text": text,
        "message_ar": "مسودة للمراجعة البشرية — لا تُعتمد رسمياً دون تحرير وتوقيع.",
        "suggestion_only": True,
    }


def assistant_gap_report(
    conn,
    *,
    department_id: int,
    semester: str,
) -> dict[str, Any]:
    check = archive_checklist(conn, department_id=department_id, semester=semester)
    tips = []
    for row in check.get("rows") or []:
        if not row.get("ok"):
            tips.append(
                f"أضف سنداً من نوع «{row.get('title_ar')}» لهذا الفصل أو أرفق الملف الناقص."
            )
    if int(check.get("open_notes") or 0) > 0:
        tips.append("توجد ملاحظات مفتوحة — حدّث حالتها أو أغلقها بعد المتابعة.")
    if not tips:
        tips.append("لا توجد فجوات ظاهرة في قائمة التحقق الفصلية.")
    return {
        **check,
        "tips_ar": tips,
        "assistant_message_ar": " ".join(tips),
        "suggestion_only": True,
    }


def run_assistant(
    conn,
    *,
    intent: str,
    department_id: int | None = None,
    semester: str | None = None,
    title_ar: str = "",
    body_text: str = "",
    filename: str = "",
    record_type: str = "",
    fields: dict[str, Any] | None = None,
    item_id: int | None = None,
    department_name_ar: str = "",
    query: str = "",
) -> dict[str, Any]:
    """
    واجهة موحّدة للمساعد.
    intents: classify | draft | gaps | suggest_qaa | search | help
    """
    intent_l = (intent or "help").strip().lower()

    if intent_l in ("help", "hi", "start"):
        return {
            "status": "ok",
            "intent": "help",
            "message_ar": (
                "المساعد يقترح فقط: تصنيف الوثيقة، صياغة مسودة، فحص نواقص الأرشيف، "
                "واقتراح مؤشرات اعتماد للربط اليدوي. لن يغيّر حالة الامتثال تلقائياً."
            ),
            "intents": [
                {"code": "classify", "label_ar": "تصنيف وثيقة"},
                {"code": "draft", "label_ar": "صياغة مسودة"},
                {"code": "gaps", "label_ar": "نواقص الأرشيف الفصلي"},
                {"code": "suggest_qaa", "label_ar": "اقتراح مؤشرات اعتماد لسجل"},
                {"code": "search", "label_ar": "بحث في أرشيف القسم"},
            ],
            "suggestion_only": True,
        }

    if intent_l == "classify":
        return classify_archive_text(title_ar=title_ar, body_text=body_text, filename=filename)

    if intent_l == "draft":
        return draft_archive_document(
            record_type=record_type or "minutes",
            fields=fields,
            department_name_ar=department_name_ar,
        )

    if intent_l == "gaps":
        if department_id is None:
            raise ValueError("department_id مطلوب")
        return assistant_gap_report(
            conn,
            department_id=int(department_id),
            semester=(semester or "").strip(),
        )

    if intent_l in ("suggest_qaa", "suggest"):
        if item_id is None:
            # اقتراح من النوع فقط
            rtype = (record_type or "").strip()
            if not rtype:
                cls = classify_archive_text(title_ar=title_ar, body_text=body_text, filename=filename)
                rtype = cls.get("suggested_type") or "minutes"
            return {
                "status": "ok",
                "intent": "suggest_qaa",
                "record_type": rtype,
                "suggestions": suggestions_for_type(rtype),
                "policy_ar": "اقتراح فقط — أكّد الربط يدوياً من شاشة الأرشيف.",
                "suggestion_only": True,
            }
        return suggest_qaa_for_item(conn, int(item_id))

    if intent_l == "search":
        if department_id is None:
            raise ValueError("department_id مطلوب")
        items = list_archive_items(
            conn,
            department_id=int(department_id),
            semester=semester,
            q=query or title_ar or body_text,
            limit=50,
        )
        return {
            "status": "ok",
            "intent": "search",
            "count": len(items),
            "items": [
                {
                    "id": it.get("id"),
                    "title_ar": it.get("title_ar"),
                    "record_type": it.get("record_type"),
                    "record_type_label_ar": it.get("record_type_label_ar"),
                    "doc_date": it.get("doc_date"),
                    "ref_number": it.get("ref_number"),
                }
                for it in items
            ],
            "suggestion_only": True,
        }

    raise ValueError(f"نية غير معروفة: {intent}")
