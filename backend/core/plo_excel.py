"""استيراد/تصدير مخرجات البرنامج (PLO) عبر Excel."""

from __future__ import annotations

import io
from typing import Any

import pandas as pd

PLO_EXPORT_COLUMNS: tuple[tuple[str, str], ...] = (
    ("code", "الرمز"),
    ("title_ar", "العنوان_عربي"),
    ("title_en", "العنوان_انجليزي"),
    ("domain", "المجال"),
    ("bloom_level", "بلوم"),
    ("performance_indicator", "مؤشر_الاداء"),
    ("accreditation_tag", "اعتماد"),
    ("parent_glo_code", "GLO"),
    ("description", "الوصف"),
    ("sort_order", "ترتيب"),
    ("governance_status", "حوكمة"),
    ("effective_from", "ساري_من"),
    ("is_active", "نشط"),
)

_HEADER_TO_FIELD: dict[str, str] = {}
for field, ar in PLO_EXPORT_COLUMNS:
    _HEADER_TO_FIELD[field.lower()] = field
    _HEADER_TO_FIELD[ar] = field
    _HEADER_TO_FIELD[ar.replace("_", " ")] = field

_VALID_DOMAINS = frozenset({"knowledge", "skills", "values", "professional"})
_VALID_GOV = frozenset({"draft", "approved", "retired"})


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    rename = {}
    for col in df.columns:
        key = str(col or "").strip().lower().replace(" ", "_")
        if key in _HEADER_TO_FIELD:
            rename[col] = _HEADER_TO_FIELD[key]
        elif key.replace("_", "") in {k.replace("_", "") for k in _HEADER_TO_FIELD}:
            for hk, fv in _HEADER_TO_FIELD.items():
                if hk.replace("_", "") == key.replace("_", ""):
                    rename[col] = fv
                    break
    return df.rename(columns=rename)


def template_xlsx_bytes() -> bytes:
    row = {
        "code": "PLO1",
        "title_ar": "مثال: حل المشكلات الهندسية",
        "title_en": "Engineering Problem Solving",
        "domain": "skills",
        "bloom_level": "analyze",
        "performance_indicator": "يحقق ≥80% في التقييم",
        "accreditation_tag": "ABET-1",
        "parent_glo_code": "GLO2",
        "description": "وصف المخرج",
        "sort_order": 10,
        "governance_status": "draft",
        "effective_from": "2025-2026",
        "is_active": 1,
    }
    df = pd.DataFrame([row])
    cols = [f for f, _ar in PLO_EXPORT_COLUMNS]
    df = df[cols]
    df.columns = [ar for _f, ar in PLO_EXPORT_COLUMNS]
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="PLO")
        wb = writer.book
        ws = writer.sheets["PLO"]
        note = wb.add_worksheet("تعليمات")
        note.write(0, 0, "المجال: knowledge | skills | values | professional")
        note.write(1, 0, "حوكمة: draft | approved | retired")
        note.write(2, 0, "الرمز فريد لكل برنامج — الصفوف الفارغة تُتخطى")
    return buf.getvalue()


def export_program_outcomes_xlsx(rows: list[dict[str, Any]]) -> bytes:
    cols = [f for f, _ar in PLO_EXPORT_COLUMNS]
    data = []
    for r in rows or []:
        data.append({f: r.get(f, "") for f in cols})
    df = pd.DataFrame(data or [{f: "" for f in cols}])
    df.columns = [ar for _f, ar in PLO_EXPORT_COLUMNS]
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="PLO")
    return buf.getvalue()


def import_outcomes_from_xlsx(
    cur,
    program_id: int,
    file_bytes: bytes,
    *,
    merge: bool = True,
) -> dict[str, Any]:
    try:
        df = pd.read_excel(io.BytesIO(file_bytes), sheet_name=0)
    except Exception as e:
        return {"status": "error", "message": f"تعذر قراءة الملف: {e}"}
    if df is None or df.empty:
        return {"status": "error", "message": "الملف فارغ"}
    df = _normalize_columns(df)
    inserted = updated = skipped = errors = 0
    err_list: list[str] = []
    for idx, row in df.iterrows():
        code = str(row.get("code") or "").strip()
        title_ar = str(row.get("title_ar") or "").strip()
        if not code or not title_ar:
            skipped += 1
            continue
        domain = str(row.get("domain") or "skills").strip().lower() or "skills"
        if domain not in _VALID_DOMAINS:
            domain = "skills"
        gov = str(row.get("governance_status") or "draft").strip().lower() or "draft"
        if gov not in _VALID_GOV:
            gov = "draft"
        try:
            sort_order = int(row.get("sort_order") or 0)
        except (TypeError, ValueError):
            sort_order = 0
        try:
            is_active = 1 if int(row.get("is_active", 1)) else 0
        except (TypeError, ValueError):
            is_active = 1
        payload = (
            title_ar,
            str(row.get("title_en") or "").strip(),
            str(row.get("description") or "").strip(),
            domain,
            str(row.get("bloom_level") or "").strip(),
            str(row.get("performance_indicator") or "").strip(),
            str(row.get("accreditation_tag") or "").strip(),
            str(row.get("parent_glo_code") or "").strip(),
            sort_order,
            gov,
            str(row.get("effective_from") or "").strip(),
            is_active,
            int(program_id),
            code,
        )
        exists = cur.execute(
            "SELECT id FROM program_learning_outcomes WHERE program_id = ? AND code = ?",
            (int(program_id), code),
        ).fetchone()
        if exists:
            if not merge:
                skipped += 1
                continue
            oid = int(exists[0] if not hasattr(exists, "keys") else exists["id"])
            cur.execute(
                """
                UPDATE program_learning_outcomes SET
                    title_ar = ?, title_en = ?, description = ?, domain = ?,
                    bloom_level = ?, performance_indicator = ?, accreditation_tag = ?,
                    parent_glo_code = ?, sort_order = ?, governance_status = ?,
                    effective_from = ?, is_active = ?
                WHERE id = ?
                """,
                (
                    title_ar,
                    str(row.get("title_en") or "").strip(),
                    str(row.get("description") or "").strip(),
                    domain,
                    str(row.get("bloom_level") or "").strip(),
                    str(row.get("performance_indicator") or "").strip(),
                    str(row.get("accreditation_tag") or "").strip(),
                    str(row.get("parent_glo_code") or "").strip(),
                    sort_order,
                    gov,
                    str(row.get("effective_from") or "").strip(),
                    is_active,
                    oid,
                ),
            )
            updated += 1
        else:
            cur.execute(
                """
                INSERT INTO program_learning_outcomes (
                    title_ar, title_en, description, domain, bloom_level,
                    performance_indicator, accreditation_tag, parent_glo_code,
                    sort_order, governance_status, effective_from, is_active,
                    program_id, code, version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                """,
                payload,
            )
            inserted += 1
    return {
        "status": "ok",
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
        "errors": errors,
        "error_messages": err_list[:20],
    }
