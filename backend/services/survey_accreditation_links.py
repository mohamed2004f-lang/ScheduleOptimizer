"""حل روابط الاستبيانات بمؤشرات الاعتماد — DB + QAA + كتالوج داخلي."""

from __future__ import annotations

import json
from typing import Any

from backend.core.accreditation_catalog import resolve_catalog_version
from backend.core.accreditation_evidence_types import SURVEY_TEMPLATE_TO_EVIDENCE_TYPE
from backend.core.survey_platform import LINK_TYPE_LABELS_AR


def _link_display(link: dict[str, Any]) -> dict[str, Any]:
    lt = (link.get("link_type") or "evidence").strip().lower()
    return {
        **link,
        "link_type": lt,
        "link_type_ar": LINK_TYPE_LABELS_AR.get(lt, lt),
        "indicator_title_ar": link.get("indicator_title_ar") or link.get("usage_ar") or "",
    }


def _rules_from_db(
    conn,
    *,
    template_code: str,
    catalog_version: str,
) -> list[dict[str, Any]]:
    from backend.services.accreditation_evidence_matrix import list_evidence_rules

    tpl = (template_code or "").strip()
    out: list[dict[str, Any]] = []
    for rule in list_evidence_rules(conn, catalog_version=catalog_version):
        cfg = rule.get("config") or {}
        if isinstance(cfg, str):
            try:
                cfg = json.loads(cfg)
            except json.JSONDecodeError:
                cfg = {}
        st = (cfg.get("survey_template") or "").strip()
        if not st and (rule.get("source_module") or "") == "multi_surveys":
            st = (rule.get("source_ref") or "").strip()
        if st != tpl:
            continue
        out.append(
            {
                "catalog_version": catalog_version,
                "indicator_code": rule.get("indicator_code") or "",
                "indicator_title_ar": rule.get("indicator_title_ar") or "",
                "link_type": rule.get("link_mode") or "evidence",
                "usage_ar": rule.get("notes_ar") or "",
                "evidence_type_code": rule.get("evidence_type_code"),
                "evidence_type_id": rule.get("evidence_type_id"),
                "rule_id": rule.get("id"),
            }
        )
    return out


def _links_from_bindings(
    conn,
    *,
    template_code: str,
    semester: str,
    department_id: int | None = None,
) -> list[dict[str, Any]]:
    """روابط فعلية من جدول bindings — الربط اليدوي فقط."""
    from backend.services.accreditation_evidence_bindings import list_bindings

    tpl = (template_code or "").strip()
    if not tpl:
        return []
    sem = (semester or "").strip()
    if not sem:
        return []
    source_ref = f"survey:{tpl}"
    out: list[dict[str, Any]] = []
    for b in list_bindings(
        conn, semester=sem, department_id=department_id, indicator_id=None
    ):
        if (b.get("binding_kind") or "").strip().lower() != "survey":
            continue
        ref = (b.get("source_ref") or "").strip()
        if ref != source_ref:
            continue
        code = (b.get("indicator_code") or "").strip().upper()
        if not code:
            continue
        out.append(
            {
                "catalog_version": "",
                "indicator_code": code,
                "indicator_title_ar": (b.get("label_ar") or code)[:200],
                "link_type": "evidence",
                "usage_ar": "ربط يدوي من خريطة الامتثال",
                "binding_id": b.get("id"),
            }
        )
    return out


def resolve_survey_accreditation_links(
    conn,
    template_code: str,
    *,
    catalog_version: str | None = None,
    semester: str | None = None,
    department_id: int | None = None,
) -> list[dict[str, Any]]:
    """روابط استبيان → مؤشرات — قواعد كتالوج نشطة + bindings فعلية فقط (بدون خرائط ثابتة)."""
    tpl = (template_code or "").strip()
    if not tpl:
        return []
    cat = resolve_catalog_version(conn, catalog_version)
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()

    if semester:
        for lk in _links_from_bindings(
            conn, template_code=tpl, semester=semester, department_id=department_id
        ):
            code = (lk.get("indicator_code") or "").upper()
            if code in seen:
                continue
            seen.add(code)
            merged.append(lk)

    for lk in _rules_from_db(conn, template_code=tpl, catalog_version=cat):
        code = (lk.get("indicator_code") or "").upper()
        if not code or code in seen:
            continue
        seen.add(code)
        merged.append(lk)

    return [_link_display(lk) for lk in merged]


def resolve_survey_links_all_catalogs(
    conn,
    template_code: str,
) -> list[dict[str, Any]]:
    """روابط QAA لكل كتالوجات المركز (للربط التلقائي عند الإغلاق)."""
    from backend.core.qaa_survey_accreditation_map import QAA_CATALOG_VERSIONS

    tpl = (template_code or "").strip()
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for cat in QAA_CATALOG_VERSIONS:
        for lk in resolve_survey_accreditation_links(conn, tpl, catalog_version=cat):
            key = (cat, (lk.get("indicator_code") or "").upper())
            if key in seen:
                continue
            seen.add(key)
            merged.append(lk)
    return merged


def primary_survey_link(
    conn,
    template_code: str,
    *,
    catalog_version: str | None = None,
    semester: str | None = None,
    department_id: int | None = None,
) -> dict[str, Any] | None:
    links = resolve_survey_accreditation_links(
        conn,
        template_code,
        catalog_version=catalog_version,
        semester=semester,
        department_id=department_id,
    )
    if not links:
        return None
    return links[0]


def primary_evidence_indicator_code_resolved(
    conn,
    template_code: str,
    *,
    catalog_version: str | None = None,
    semester: str | None = None,
    department_id: int | None = None,
) -> str | None:
    lk = primary_survey_link(
        conn,
        template_code,
        catalog_version=catalog_version,
        semester=semester,
        department_id=department_id,
    )
    if not lk:
        return None
    code = (lk.get("indicator_code") or "").strip().upper()
    return code or None


def evidence_type_code_for_template(template_code: str) -> str | None:
    return SURVEY_TEMPLATE_TO_EVIDENCE_TYPE.get((template_code or "").strip())
