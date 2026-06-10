"""[قديم — معطّل] ربط تلقائي للاستبيانات بمؤشرات الاعتماد عند إغلاق الفصل.

تنبيه: سياسة النظام الحالية هي «ربط يدوي فقط». لم يعد هذا المسار يُستدعى
افتراضياً (انظر `auto_bind_accreditation=False` في `survey_snapshots.py`).
يُحتفظ بالملف للرجوع التاريخي فقط؛ لا تُفعّله دون موافقة صريحة لأنه يُنشئ
روابط (bindings) تلقائية تتعارض مع الربط اليدوي.
"""

from __future__ import annotations

from typing import Any

from backend.core.qaa_survey_accreditation_map import QAA_CATALOG_VERSIONS
from backend.services.survey_accreditation_links import (
    evidence_type_code_for_template,
    resolve_survey_links_all_catalogs,
)


def auto_bind_survey_templates(
    conn,
    *,
    semester: str,
    department_id: int | None,
    actor: str = "",
    template_codes: list[str] | None = None,
    min_responses: int = 1,
) -> dict[str, Any]:
    """
    إنشاء/تحديث bindings من نوع survey لكل قالب له بيانات في الفصل.
    يُطبَّق على كتالوجات QAA المؤسسي والبرامجي.
    """
    from backend.core.accreditation_evidence_rules_seed import (
        _indicator_id_by_code,
        _type_id_by_code,
        ensure_evidence_rules_for_catalog,
    )
    from backend.services.accreditation_evidence_bindings import save_binding
    from backend.services.survey_accreditation import survey_template_aggregate

    sem = (semester or "").strip()
    if not sem:
        raise ValueError("semester مطلوب")

    for cat in QAA_CATALOG_VERSIONS:
        ensure_evidence_rules_for_catalog(conn, cat)

    codes = template_codes or []
    if not codes:
        from backend.core.qaa_survey_accreditation_map import all_qaa_survey_template_codes

        codes = all_qaa_survey_template_codes()

    bound: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for tpl in codes:
        tpl = (tpl or "").strip()
        if not tpl:
            continue
        agg = survey_template_aggregate(
            conn, tpl, semester=sem, department_id=department_id
        )
        resp = int(agg.get("response_count") or 0)
        if resp < min_responses and not agg.get("aggregated"):
            skipped.append({"template_code": tpl, "reason": "no_data"})
            continue

        label_base = (agg.get("title_ar") or tpl).strip()
        score = agg.get("overall_score_percent")
        score_txt = f" — {score}%" if score is not None else ""

        for link in resolve_survey_links_all_catalogs(conn, tpl):
            cat = (link.get("catalog_version") or "").strip()
            ind_code = (link.get("indicator_code") or "").strip().upper()
            if not cat or not ind_code:
                continue
            iid = _indicator_id_by_code(conn, cat, ind_code)
            if not iid:
                skipped.append(
                    {"template_code": tpl, "indicator_code": ind_code, "reason": "no_indicator"}
                )
                continue
            et_code = link.get("evidence_type_code") or evidence_type_code_for_template(tpl)
            et_id = link.get("evidence_type_id") or (
                _type_id_by_code(conn, et_code) if et_code else None
            )
            if not et_id:
                skipped.append(
                    {"template_code": tpl, "indicator_code": ind_code, "reason": "no_evidence_type"}
                )
                continue
            try:
                result = save_binding(
                    conn,
                    {
                        "semester": sem,
                        "department_id": department_id,
                        "indicator_id": iid,
                        "evidence_type_id": int(et_id),
                        "rule_id": link.get("rule_id"),
                        "binding_kind": "survey",
                        "source_ref": f"survey:{tpl}",
                        "label_ar": f"{label_base}{score_txt}"[:500],
                        "notes_ar": (link.get("usage_ar") or "")[:500],
                    },
                    actor=actor,
                )
                bound.append(
                    {
                        "template_code": tpl,
                        "catalog_version": cat,
                        "indicator_code": ind_code,
                        "binding_id": result.get("id"),
                    }
                )
            except ValueError as exc:
                skipped.append(
                    {
                        "template_code": tpl,
                        "indicator_code": ind_code,
                        "reason": str(exc),
                    }
                )

    return {
        "status": "ok",
        "semester": sem,
        "bound_count": len(bound),
        "skipped_count": len(skipped),
        "bound": bound,
        "skipped": skipped[:20],
    }
