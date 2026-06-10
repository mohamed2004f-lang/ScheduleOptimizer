"""بذرة أنواع الأدلة وقواعد الربط بالمؤشرات."""

from __future__ import annotations

import json
from typing import Any

from backend.core.accreditation_evidence_types import (
    DEFAULT_EVIDENCE_TYPES,
    KEYWORD_EVIDENCE_RULES,
    SURVEY_TEMPLATE_TO_EVIDENCE_TYPE,
)
from backend.core.survey_platform import SURVEY_ACCREDITATION_MAP
from backend.core.qaa_survey_accreditation_map import (
    QAA_SURVEY_ACCREDITATION_MAP,
    qaa_links_for_template,
)
from backend.database.database import is_postgresql


def _row_val(row, idx=0, key=None):
    if row is None:
        return None
    if hasattr(row, "keys") and key:
        try:
            return row[key]
        except (KeyError, TypeError):
            pass
    try:
        return row[idx]
    except (TypeError, IndexError):
        return None


def ensure_evidence_types(conn) -> int:
    cur = conn.cursor()
    n = 0
    pg = is_postgresql()
    for (
        code,
        title,
        desc,
        category,
        module,
        ref,
        is_system,
        sort_order,
    ) in DEFAULT_EVIDENCE_TYPES:
        if pg:
            cur.execute(
                """
                INSERT INTO accreditation_evidence_types
                (code, title_ar, description_ar, category, source_module, source_ref,
                 is_system, is_editable, sort_order, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, 1)
                ON CONFLICT (code) DO UPDATE SET
                    title_ar = EXCLUDED.title_ar,
                    description_ar = EXCLUDED.description_ar,
                    category = EXCLUDED.category,
                    source_module = EXCLUDED.source_module,
                    source_ref = EXCLUDED.source_ref,
                    is_system = EXCLUDED.is_system,
                    sort_order = EXCLUDED.sort_order,
                    is_active = 1
                """,
                (code, title, desc, category, module, ref, int(is_system), sort_order),
            )
        else:
            cur.execute(
                """
                INSERT OR IGNORE INTO accreditation_evidence_types
                (code, title_ar, description_ar, category, source_module, source_ref,
                 is_system, is_editable, sort_order, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, 1)
                """,
                (code, title, desc, category, module, ref, int(is_system), sort_order),
            )
            cur.execute(
                """
                UPDATE accreditation_evidence_types SET
                    title_ar = ?, description_ar = ?, category = ?,
                    source_module = ?, source_ref = ?, is_system = ?,
                    sort_order = ?, is_active = 1
                WHERE code = ?
                """,
                (title, desc, category, module, ref, int(is_system), sort_order, code),
            )
        n += 1
    conn.commit()
    return n


def _type_id_by_code(conn, code: str) -> int | None:
    cur = conn.cursor()
    row = cur.execute(
        "SELECT id FROM accreditation_evidence_types WHERE code = ? AND COALESCE(is_active, 1) = 1",
        (code.strip(),),
    ).fetchone()
    v = _row_val(row, 0, "id")
    return int(v) if v is not None else None


def _indicator_id_by_code(conn, catalog_version: str, indicator_code: str) -> int | None:
    cur = conn.cursor()
    row = cur.execute(
        """
        SELECT i.id FROM accreditation_indicators i
        INNER JOIN accreditation_standards s ON s.id = i.standard_id
        WHERE s.catalog_version = ? AND i.code = ?
          AND COALESCE(i.is_active, 1) = 1 AND COALESCE(s.is_active, 1) = 1
        LIMIT 1
        """,
        (catalog_version, indicator_code.strip().upper()),
    ).fetchone()
    v = _row_val(row, 0, "id")
    return int(v) if v is not None else None


def _upsert_rule(
    conn,
    *,
    catalog_version: str,
    indicator_id: int,
    evidence_type_id: int,
    link_mode: str,
    is_required: bool = True,
    notes_ar: str = "",
    sort_order: int = 0,
    config: dict | None = None,
) -> bool:
    cur = conn.cursor()
    cfg = json.dumps(config or {}, ensure_ascii=False)
    lm = (link_mode or "evidence").strip().lower()
    if lm not in ("auto", "hybrid", "manual", "evidence"):
        lm = "evidence"
    if is_postgresql():
        cur.execute(
            """
            INSERT INTO accreditation_indicator_evidence_rules
            (catalog_version, indicator_id, evidence_type_id, link_mode, is_required,
             weight_percent, config_json, notes_ar, sort_order, is_active)
            VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, 1)
            ON CONFLICT (catalog_version, indicator_id, evidence_type_id) DO UPDATE SET
                link_mode = EXCLUDED.link_mode,
                is_required = EXCLUDED.is_required,
                notes_ar = EXCLUDED.notes_ar,
                sort_order = EXCLUDED.sort_order,
                config_json = EXCLUDED.config_json,
                is_active = 1
            """,
            (
                catalog_version,
                indicator_id,
                evidence_type_id,
                lm,
                1 if is_required else 0,
                cfg,
                notes_ar[:2000],
                sort_order,
            ),
        )
    else:
        cur.execute(
            """
            INSERT OR IGNORE INTO accreditation_indicator_evidence_rules
            (catalog_version, indicator_id, evidence_type_id, link_mode, is_required,
             weight_percent, config_json, notes_ar, sort_order, is_active)
            VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, 1)
            """,
            (
                catalog_version,
                indicator_id,
                evidence_type_id,
                lm,
                1 if is_required else 0,
                cfg,
                notes_ar[:2000],
                sort_order,
            ),
        )
        cur.execute(
            """
            UPDATE accreditation_indicator_evidence_rules SET
                link_mode = ?, is_required = ?, notes_ar = ?, sort_order = ?,
                config_json = ?, is_active = 1
            WHERE catalog_version = ? AND indicator_id = ? AND evidence_type_id = ?
            """,
            (lm, 1 if is_required else 0, notes_ar[:2000], sort_order, cfg, catalog_version, indicator_id, evidence_type_id),
        )
    return True


def _rules_count_for_catalog(conn, catalog_version: str) -> int:
    cur = conn.cursor()
    row = cur.execute(
        """
        SELECT COUNT(*) FROM accreditation_indicator_evidence_rules
        WHERE catalog_version = ? AND COALESCE(is_active, 1) = 1
        """,
        (catalog_version,),
    ).fetchone()
    return int(_row_val(row, 0) or 0)


def _expected_qaa_survey_rule_count(catalog_version: str) -> int:
    n = 0
    for links in QAA_SURVEY_ACCREDITATION_MAP.values():
        n += sum(1 for lk in links if (lk.get("catalog_version") or "") == catalog_version)
    return n


def _qaa_survey_rules_count(conn, catalog_version: str) -> int:
    cur = conn.cursor()
    row = cur.execute(
        """
        SELECT COUNT(*) FROM accreditation_indicator_evidence_rules
        WHERE catalog_version = ? AND COALESCE(is_active, 1) = 1
          AND config_json LIKE ?
        """,
        (catalog_version, '%"qaa_official": true%'),
    ).fetchone()
    return int(_row_val(row, 0) or 0)


def deactivate_auto_seeded_evidence_rules(conn, catalog_version: str) -> int:
    """
    إيقاف قواعد الأدلة المُولَّدة آلياً (كلمات مفتاحية، QAA، ملف عام لكل مؤشر).
    يبقى للمسؤول تعريف قواعد يدوياً من تبويب إدارة الكتالوج فقط.
    """
    ver = (catalog_version or "").strip()
    if not ver:
        return 0
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE accreditation_indicator_evidence_rules SET
            is_active = 0,
            is_required = 0,
            link_mode = CASE
                WHEN link_mode IN ('auto', 'hybrid') THEN 'evidence'
                ELSE link_mode
            END
        WHERE catalog_version = ?
          AND COALESCE(is_active, 1) = 1
          AND (
            notes_ar LIKE '%%مقترح تلقائي%%'
            OR notes_ar LIKE '%%رفع ملف أو رابط داعم%%'
            OR config_json LIKE '%%"qaa_official": true%%'
            OR config_json LIKE '%%"survey_template"%%'
          )
        """,
        (ver,),
    )
    n = int(cur.rowcount or 0)
    conn.commit()
    return n


def demote_qaa_survey_auto_rules(conn, catalog_version: str) -> int:
    """
    إلغاء الربط الآلي/الإلزامي لقواعد الاستبيانات المزروعة سابقاً.
    الاستبيانات تبقى شواهد اختيارية يُربطها المنسق يدوياً من واجهة «إدارة».
    """
    ver = (catalog_version or "").strip()
    if not ver:
        return 0
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE accreditation_indicator_evidence_rules SET
            link_mode = 'evidence',
            is_required = 0,
            notes_ar = CASE
                WHEN notes_ar LIKE '%%[يدوي]%%' THEN notes_ar
                ELSE TRIM(notes_ar || ' [يدوي — اختياري]')
            END
        WHERE catalog_version = ?
          AND COALESCE(is_active, 1) = 1
          AND (
            config_json LIKE '%%"qaa_official": true%%'
            OR (config_json LIKE '%%survey_template%%' AND link_mode = 'auto')
          )
        """,
        (ver,),
    )
    n = int(cur.rowcount or 0)
    conn.commit()
    return n


def seed_qaa_survey_map_rules(conn, catalog_version: str, *, force: bool = False) -> int:
    """مهمل — لم يعد يُستدعى تلقائياً. الربط يدوي فقط من واجهة امتثال → إدارة."""
    ensure_evidence_types(conn)
    ver = (catalog_version or "").strip()
    if not ver.startswith("QAA-"):
        return 0
    expected = _expected_qaa_survey_rule_count(ver)
    if not force and expected > 0 and _qaa_survey_rules_count(conn, ver) >= expected:
        return 0
    added = 0
    sort_i = 0
    for tpl_code in QAA_SURVEY_ACCREDITATION_MAP:
        et_code = SURVEY_TEMPLATE_TO_EVIDENCE_TYPE.get(tpl_code)
        if not et_code:
            continue
        et_id = _type_id_by_code(conn, et_code)
        if not et_id:
            continue
        for link in qaa_links_for_template(tpl_code, catalog_version=ver):
            ind_code = (link.get("indicator_code") or "").strip()
            if not ind_code:
                continue
            iid = _indicator_id_by_code(conn, ver, ind_code)
            if not iid:
                continue
            sort_i += 1
            _upsert_rule(
                conn,
                catalog_version=ver,
                indicator_id=iid,
                evidence_type_id=et_id,
                link_mode=(link.get("link_type") or "evidence"),
                is_required=(link.get("link_type") or "") == "auto",
                notes_ar=(link.get("usage_ar") or "")[:2000],
                sort_order=sort_i,
                config={"survey_template": tpl_code, "qaa_official": True},
            )
            added += 1
    conn.commit()
    return added


def seed_survey_map_rules(conn, catalog_version: str) -> int:
    """قواعد من SURVEY_ACCREDITATION_MAP للكتالوج الداخلي."""
    added = 0
    for tpl_code, links in SURVEY_ACCREDITATION_MAP.items():
        et_code = SURVEY_TEMPLATE_TO_EVIDENCE_TYPE.get(tpl_code)
        if not et_code:
            continue
        et_id = _type_id_by_code(conn, et_code)
        if not et_id:
            continue
        for link in links:
            ind_code = (link.get("indicator_code") or "").strip()
            if not ind_code:
                continue
            iid = _indicator_id_by_code(conn, catalog_version, ind_code)
            if not iid:
                continue
            _upsert_rule(
                conn,
                catalog_version=catalog_version,
                indicator_id=iid,
                evidence_type_id=et_id,
                link_mode=(link.get("link_type") or "evidence"),
                notes_ar=(link.get("usage_ar") or "")[:2000],
                config={"survey_template": tpl_code},
            )
            added += 1
    conn.commit()
    return added


def seed_keyword_rules(conn, catalog_version: str) -> int:
    """قواعد بالكلمات المفتاحية في عناوين مؤشرات كتالوج المركز."""
    if not catalog_version.startswith("QAA-"):
        return 0
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT i.id, i.title_ar FROM accreditation_indicators i
        INNER JOIN accreditation_standards s ON s.id = i.standard_id
        WHERE s.catalog_version = ?
          AND COALESCE(i.is_active, 1) = 1 AND COALESCE(s.is_active, 1) = 1
        """,
        (catalog_version,),
    ).fetchall()
    added = 0
    sort_i = 0
    for row in rows or []:
        iid = int(_row_val(row, 0, "id") or 0)
        title = str(_row_val(row, 1, "title_ar") or "")
        if not iid or not title:
            continue
        for keywords, et_code, link_mode in KEYWORD_EVIDENCE_RULES:
            if not all(kw in title for kw in keywords):
                continue
            et_id = _type_id_by_code(conn, et_code)
            if not et_id:
                continue
            sort_i += 1
            _upsert_rule(
                conn,
                catalog_version=catalog_version,
                indicator_id=iid,
                evidence_type_id=et_id,
                link_mode=link_mode,
                notes_ar=f"مقترح تلقائي من نص المؤشر: {', '.join(keywords)}",
                sort_order=sort_i,
            )
            added += 1
    # كل مؤشر يحتاج على الأقل شاهد ملف عام
    for row in rows or []:
        iid = int(_row_val(row, 0, "id") or 0)
        if not iid:
            continue
        et_id = _type_id_by_code(conn, "generic_file_upload")
        if et_id:
            _upsert_rule(
                conn,
                catalog_version=catalog_version,
                indicator_id=iid,
                evidence_type_id=et_id,
                link_mode="evidence",
                is_required=False,
                notes_ar="رفع ملف أو رابط داعم اختياري.",
                sort_order=999,
            )
            added += 1
    conn.commit()
    return added


def ensure_evidence_rules_for_catalog(conn, catalog_version: str) -> dict[str, Any]:
    """أنواع الأدلة + إيقاف أي قواعد آلية قديمة (الربط يدوي فقط)."""
    ensure_evidence_types(conn)
    ver = (catalog_version or "").strip()
    if not ver:
        return {"catalog_version": ver, "status": "skipped"}
    added = 0
    added += demote_qaa_survey_auto_rules(conn, ver)
    added += deactivate_auto_seeded_evidence_rules(conn, ver)

    status = "synced" if added else "ok"
    return {
        "catalog_version": ver,
        "status": status,
        "reason": None,
        "rules_added": added,
        "rules_count": _rules_count_for_catalog(conn, ver),
    }
