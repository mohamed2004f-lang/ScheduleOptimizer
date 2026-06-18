"""حل روابط الاستبيانات بمؤشرات الاعتماد — DB + QAA + كتالوج داخلي."""

from __future__ import annotations

import json
from typing import Any

from backend.core.accreditation_catalog import resolve_catalog_version
from backend.core.accreditation_evidence_types import SURVEY_TEMPLATE_TO_EVIDENCE_TYPE
from backend.core.survey_platform import LINK_TYPE_LABELS_AR


class SurveyLinkCache:
    """Cache طلب واحد — قواعد/bindings/روابط الاعتماد (تجنّب N×list_evidence_rules)."""

    __slots__ = ("_rules_by_cat", "_bindings_by_key", "_resolved")

    def __init__(self) -> None:
        self._rules_by_cat: dict[str, list[dict[str, Any]]] = {}
        self._bindings_by_key: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
        self._resolved: dict[tuple[Any, ...], list[dict[str, Any]]] = {}

    def rules_for_catalog(self, conn, catalog_version: str) -> list[dict[str, Any]]:
        cat = (catalog_version or "").strip()
        if cat not in self._rules_by_cat:
            from backend.services.accreditation_evidence_matrix import list_evidence_rules

            self._rules_by_cat[cat] = list_evidence_rules(conn, catalog_version=cat)
        return self._rules_by_cat[cat]

    def bindings_for_term(
        self,
        conn,
        *,
        semester: str,
        department_id: int | None = None,
    ) -> list[dict[str, Any]]:
        key = (semester.strip(), department_id)
        if key not in self._bindings_by_key:
            from backend.services.accreditation_evidence_bindings import list_bindings

            self._bindings_by_key[key] = list(
                list_bindings(
                    conn,
                    semester=semester.strip(),
                    department_id=department_id,
                    indicator_id=None,
                )
            )
        return self._bindings_by_key[key]

    def resolve(
        self,
        conn,
        template_code: str,
        *,
        catalog_version: str | None = None,
        semester: str | None = None,
        department_id: int | None = None,
    ) -> list[dict[str, Any]]:
        cat = resolve_catalog_version(conn, catalog_version)
        sem = (semester or "").strip()
        tpl = (template_code or "").strip()
        key = (tpl, cat, sem, department_id)
        if key not in self._resolved:
            self._resolved[key] = _resolve_survey_accreditation_links_impl(
                conn,
                tpl,
                catalog_version=cat,
                semester=sem or None,
                department_id=department_id,
                link_cache=self,
            )
        return self._resolved[key]


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
    link_cache: SurveyLinkCache | None = None,
) -> list[dict[str, Any]]:
    tpl = (template_code or "").strip()
    rules = (
        link_cache.rules_for_catalog(conn, catalog_version)
        if link_cache is not None
        else None
    )
    if rules is None:
        from backend.services.accreditation_evidence_matrix import list_evidence_rules

        rules = list_evidence_rules(conn, catalog_version=catalog_version)
    out: list[dict[str, Any]] = []
    for rule in rules:
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
    link_cache: SurveyLinkCache | None = None,
) -> list[dict[str, Any]]:
    """روابط فعلية من جدول bindings — الربط اليدوي فقط."""
    tpl = (template_code or "").strip()
    if not tpl:
        return []
    sem = (semester or "").strip()
    if not sem:
        return []
    source_ref = f"survey:{tpl}"
    if link_cache is not None:
        all_bindings = link_cache.bindings_for_term(
            conn, semester=sem, department_id=department_id
        )
    else:
        from backend.services.accreditation_evidence_bindings import list_bindings

        all_bindings = list_bindings(
            conn, semester=sem, department_id=department_id, indicator_id=None
        )
    out: list[dict[str, Any]] = []
    for b in all_bindings:
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


def _resolve_survey_accreditation_links_impl(
    conn,
    template_code: str,
    *,
    catalog_version: str,
    semester: str | None = None,
    department_id: int | None = None,
    link_cache: SurveyLinkCache | None = None,
) -> list[dict[str, Any]]:
    """روابط استبيان → مؤشرات — قواعد كتالوج نشطة + bindings فعلية فقط."""
    tpl = (template_code or "").strip()
    if not tpl:
        return []
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()

    if semester:
        for lk in _links_from_bindings(
            conn,
            template_code=tpl,
            semester=semester,
            department_id=department_id,
            link_cache=link_cache,
        ):
            code = (lk.get("indicator_code") or "").upper()
            if code in seen:
                continue
            seen.add(code)
            merged.append(lk)

    for lk in _rules_from_db(
        conn, template_code=tpl, catalog_version=catalog_version, link_cache=link_cache
    ):
        code = (lk.get("indicator_code") or "").upper()
        if not code or code in seen:
            continue
        seen.add(code)
        merged.append(lk)

    return [_link_display(lk) for lk in merged]


def resolve_survey_accreditation_links(
    conn,
    template_code: str,
    *,
    catalog_version: str | None = None,
    semester: str | None = None,
    department_id: int | None = None,
    link_cache: SurveyLinkCache | None = None,
) -> list[dict[str, Any]]:
    """روابط استبيان → مؤشرات — قواعد كتالوج نشطة + bindings فعلية فقط (بدون خرائط ثابتة)."""
    if link_cache is not None:
        return link_cache.resolve(
            conn,
            template_code,
            catalog_version=catalog_version,
            semester=semester,
            department_id=department_id,
        )
    cat = resolve_catalog_version(conn, catalog_version)
    return _resolve_survey_accreditation_links_impl(
        conn,
        (template_code or "").strip(),
        catalog_version=cat,
        semester=(semester or "").strip() or None,
        department_id=department_id,
    )


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
    link_cache: SurveyLinkCache | None = None,
) -> dict[str, Any] | None:
    links = resolve_survey_accreditation_links(
        conn,
        template_code,
        catalog_version=catalog_version,
        semester=semester,
        department_id=department_id,
        link_cache=link_cache,
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
    link_cache: SurveyLinkCache | None = None,
) -> str | None:
    lk = primary_survey_link(
        conn,
        template_code,
        catalog_version=catalog_version,
        semester=semester,
        department_id=department_id,
        link_cache=link_cache,
    )
    if not lk:
        return None
    code = (lk.get("indicator_code") or "").strip().upper()
    return code or None


def evidence_type_code_for_template(template_code: str) -> str | None:
    return SURVEY_TEMPLATE_TO_EVIDENCE_TYPE.get((template_code or "").strip())
