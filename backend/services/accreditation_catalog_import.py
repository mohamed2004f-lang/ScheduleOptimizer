"""استيراد كتالوج معايير الاعتماد من Excel (هـ-5)."""

from __future__ import annotations

import io
import re
from typing import Any

import pandas as pd

from backend.core.accreditation_catalog import DOMAIN_LABELS, SOURCE_TYPE_LABELS
from backend.database.database import is_postgresql

# أعمدة القالب (إنجليزي) — يقبل مرادفات عربية جزئية
_COLUMN_ALIASES: dict[str, set[str]] = {
    "catalog_version": {"catalog_version", "version", "إصدار", "اصدار", "الإصدار"},
    "domain_code": {"domain_code", "domain", "المحور", "رمز_المحور", "محور"},
    "standard_code": {"standard_code", "std_code", "رمز_المعيار", "معيار"},
    "standard_title_ar": {"standard_title_ar", "standard_title", "عنوان_المعيار", "المعيار"},
    "standard_description": {"standard_description", "standard_desc", "description", "وصف_المعيار"},
    "weight_percent": {"weight_percent", "weight", "الوزن", "weight_%"},
    "indicator_code": {"indicator_code", "ind_code", "رمز_المؤشر", "مؤشر"},
    "indicator_title_ar": {"indicator_title_ar", "indicator_title", "عنوان_المؤشر"},
    "source_type": {"source_type", "source", "المصدر", "نوع_المصدر"},
    "target_hint_ar": {"target_hint_ar", "target_hint", "الهدف", "تلميح"},
}


def _norm_col(name: str) -> str:
    s = (name or "").strip().lower()
    s = re.sub(r"[\s\-]+", "_", s)
    return s


def _map_columns(df: pd.DataFrame) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for col in df.columns:
        n = _norm_col(str(col))
        for canonical, aliases in _COLUMN_ALIASES.items():
            if n in aliases or n == canonical:
                mapping[canonical] = col
                break
    required = {
        "catalog_version",
        "domain_code",
        "standard_code",
        "standard_title_ar",
        "indicator_code",
        "indicator_title_ar",
    }
    missing = required - set(mapping)
    if missing:
        raise ValueError(
            "أعمدة ناقصة في الملف: "
            + ", ".join(sorted(missing))
            + ". استخدم قالب الاستيراد من النظام."
        )
    return mapping


def template_rows() -> list[dict[str, Any]]:
    """صفوف مثال للقالب."""
    return [
        {
            "catalog_version": "2026.2",
            "domain_code": "governance",
            "standard_code": "GV-99",
            "standard_title_ar": "مثال معيار",
            "standard_description": "وصف المعيار",
            "weight_percent": 5,
            "indicator_code": "GV-99-1",
            "indicator_title_ar": "مثال مؤشر",
            "source_type": "manual",
            "target_hint_ar": "هدف قابل للقياس",
        }
    ]


def import_catalog_from_excel(
    conn,
    raw: bytes,
    *,
    deactivate_previous: bool = False,
    actor: str = "",
) -> dict[str, Any]:
    """قراءة Excel وإدراج/تحديث معايير ومؤشرات لإصدار جديد."""
    if not raw:
        raise ValueError("ملف فارغ")
    try:
        df = pd.read_excel(io.BytesIO(raw), engine="openpyxl")
    except Exception as exc:
        raise ValueError(f"تعذر قراءة Excel: {exc}") from exc
    if df.empty:
        raise ValueError("لا توجد صفوف في الملف")

    colmap = _map_columns(df)
    rows_parsed: list[dict[str, Any]] = []
    versions: set[str] = set()

    for _, row in df.iterrows():
        ver = str(row[colmap["catalog_version"]]).strip()
        if not ver or ver.lower() == "nan":
            continue
        domain = str(row[colmap["domain_code"]]).strip()
        if domain not in DOMAIN_LABELS:
            raise ValueError(f"محور غير معروف: {domain}")
        std_code = str(row[colmap["standard_code"]]).strip()
        ind_code = str(row[colmap["indicator_code"]]).strip()
        if not std_code or not ind_code:
            continue
        src = "manual"
        if "source_type" in colmap:
            src = str(row[colmap["source_type"]]).strip().lower() or "manual"
        if src not in SOURCE_TYPE_LABELS:
            src = "manual"
        weight = 0.0
        if "weight_percent" in colmap:
            try:
                weight = float(row[colmap["weight_percent"]] or 0)
            except (TypeError, ValueError):
                weight = 0.0
        desc = ""
        if "standard_description" in colmap:
            v = row[colmap["standard_description"]]
            desc = "" if pd.isna(v) else str(v).strip()
        hint = ""
        if "target_hint_ar" in colmap:
            v = row[colmap["target_hint_ar"]]
            hint = "" if pd.isna(v) else str(v).strip()
        versions.add(ver)
        rows_parsed.append(
            {
                "catalog_version": ver,
                "domain_code": domain,
                "standard_code": std_code,
                "standard_title_ar": str(row[colmap["standard_title_ar"]]).strip(),
                "standard_description": desc,
                "weight_percent": weight,
                "indicator_code": ind_code,
                "indicator_title_ar": str(row[colmap["indicator_title_ar"]]).strip(),
                "source_type": src,
                "target_hint_ar": hint,
            }
        )

    if not rows_parsed:
        raise ValueError("لم يُستخرج أي صف صالح")
    if len(versions) > 1:
        raise ValueError("يجب أن يكون catalog_version واحداً لكل الملف")

    catalog_version = next(iter(versions))
    cur = conn.cursor()
    pg = is_postgresql()

    if deactivate_previous:
        cur.execute(
            "UPDATE accreditation_standards SET is_active = 0 WHERE catalog_version <> ?",
            (catalog_version,),
        )

    standards = 0
    indicators = 0
    sort_std = 0

    for item in rows_parsed:
        sort_std += 1
        if pg:
            cur.execute(
                """
                INSERT INTO accreditation_standards
                (catalog_version, domain_code, code, title_ar, description, weight_percent, sort_order, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                ON CONFLICT (catalog_version, code) DO UPDATE SET
                    title_ar = EXCLUDED.title_ar,
                    description = EXCLUDED.description,
                    weight_percent = EXCLUDED.weight_percent,
                    domain_code = EXCLUDED.domain_code,
                    is_active = 1
                RETURNING id
                """,
                (
                    item["catalog_version"],
                    item["domain_code"],
                    item["standard_code"],
                    item["standard_title_ar"],
                    item["standard_description"],
                    item["weight_percent"],
                    sort_std,
                ),
            )
            row = cur.fetchone()
            std_id = int(row[0]) if row else None
            if std_id is None:
                cur.execute(
                    "SELECT id FROM accreditation_standards WHERE catalog_version = ? AND code = ?",
                    (item["catalog_version"], item["standard_code"]),
                )
                r2 = cur.fetchone()
                std_id = int(r2[0]) if r2 else None
        else:
            cur.execute(
                """
                INSERT OR IGNORE INTO accreditation_standards
                (catalog_version, domain_code, code, title_ar, description, weight_percent, sort_order, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (
                    item["catalog_version"],
                    item["domain_code"],
                    item["standard_code"],
                    item["standard_title_ar"],
                    item["standard_description"],
                    item["weight_percent"],
                    sort_std,
                ),
            )
            cur.execute(
                "SELECT id FROM accreditation_standards WHERE catalog_version = ? AND code = ?",
                (item["catalog_version"], item["standard_code"]),
            )
            r2 = cur.fetchone()
            std_id = int(r2[0]) if r2 else None
            if std_id:
                cur.execute(
                    """
                    UPDATE accreditation_standards SET
                        title_ar = ?, description = ?, weight_percent = ?,
                        domain_code = ?, is_active = 1
                    WHERE id = ?
                    """,
                    (
                        item["standard_title_ar"],
                        item["standard_description"],
                        item["weight_percent"],
                        item["domain_code"],
                        std_id,
                    ),
                )
        if not std_id:
            continue
        standards += 1

        if pg:
            cur.execute(
                """
                INSERT INTO accreditation_indicators
                (standard_id, code, title_ar, source_type, target_hint_ar, sort_order, is_active)
                VALUES (?, ?, ?, ?, ?, 0, 1)
                ON CONFLICT (standard_id, code) DO UPDATE SET
                    title_ar = EXCLUDED.title_ar,
                    source_type = EXCLUDED.source_type,
                    target_hint_ar = EXCLUDED.target_hint_ar,
                    is_active = 1
                """,
                (
                    std_id,
                    item["indicator_code"],
                    item["indicator_title_ar"],
                    item["source_type"],
                    item["target_hint_ar"],
                ),
            )
        else:
            cur.execute(
                """
                INSERT OR IGNORE INTO accreditation_indicators
                (standard_id, code, title_ar, source_type, target_hint_ar, sort_order, is_active)
                VALUES (?, ?, ?, ?, ?, 0, 1)
                """,
                (
                    std_id,
                    item["indicator_code"],
                    item["indicator_title_ar"],
                    item["source_type"],
                    item["target_hint_ar"],
                ),
            )
            cur.execute(
                """
                UPDATE accreditation_indicators SET
                    title_ar = ?, source_type = ?, target_hint_ar = ?, is_active = 1
                WHERE standard_id = ? AND code = ?
                """,
                (
                    item["indicator_title_ar"],
                    item["source_type"],
                    item["target_hint_ar"],
                    std_id,
                    item["indicator_code"],
                ),
            )
        indicators += 1

    conn.commit()
    return {
        "status": "ok",
        "catalog_version": catalog_version,
        "standards_upserted": standards,
        "indicators_upserted": indicators,
        "rows_processed": len(rows_parsed),
        "imported_by": actor,
    }
