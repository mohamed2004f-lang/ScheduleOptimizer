"""تحميل كتالوج معايير المركز (إصدار 4، 2023) من ملفات JSON."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.services.accreditation_catalog_import import import_catalog_rows

_DATA_DIR = Path(__file__).resolve().parents[1] / "data"
_QAA_FILES: dict[str, Path] = {
    "QAA-2023.4-INST": _DATA_DIR / "qaa_catalog_inst_2023.json",
    "QAA-2023.4-PROG-UG": _DATA_DIR / "qaa_catalog_prog_ug_2023.json",
}


def _catalog_has_placeholder_titles(conn, catalog_version: str) -> bool:
    """هل ما زالت عناوين مؤشرات نائبة (مؤشر 1) من استخراج ناقص؟"""
    cur = conn.cursor()
    row = cur.execute(
        """
        SELECT COUNT(*) FROM accreditation_indicators i
        INNER JOIN accreditation_standards s ON s.id = i.standard_id
        WHERE s.catalog_version = ?
          AND COALESCE(i.is_active, 1) = 1
          AND i.title_ar LIKE ?
        """,
        (catalog_version, "مؤشر %"),
    ).fetchone()
    try:
        n = int(row[0] if not hasattr(row, "keys") else row[0])
    except (TypeError, IndexError, KeyError):
        n = 0
    return n > 5


def _catalog_version_exists(conn, catalog_version: str) -> bool:
    cur = conn.cursor()
    row = cur.execute(
        """
        SELECT 1 FROM accreditation_standards
        WHERE catalog_version = ? AND COALESCE(is_active, 1) = 1
        LIMIT 1
        """,
        (catalog_version,),
    ).fetchone()
    return bool(row)


def _load_rows(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"تنسيق غير متوقع في {path.name}")
    return raw


def seed_qaa_catalog_version(
    conn,
    catalog_version: str,
    *,
    force: bool = False,
    actor: str = "qaa_seed",
) -> dict[str, Any]:
    """استيراد إصدار واحد من JSON إن وُجد الملف."""
    path = _QAA_FILES.get(catalog_version)
    if not path or not path.exists():
        return {
            "catalog_version": catalog_version,
            "status": "skipped",
            "reason": "missing_json",
        }
    exists = _catalog_version_exists(conn, catalog_version)
    if (
        not force
        and exists
        and not _catalog_has_placeholder_titles(conn, catalog_version)
    ):
        return {
            "catalog_version": catalog_version,
            "status": "skipped",
            "reason": "already_seeded",
        }
    rows = _load_rows(path)
    result = import_catalog_rows(conn, rows, actor=actor)
    result["status"] = "ok"
    return result


def ensure_qaa_catalog(conn, *, force: bool = False) -> dict[str, Any]:
    """تحميل إصداري INST و PROG-UG عند غيابهما."""
    out: dict[str, Any] = {"versions": {}}
    for ver in _QAA_FILES:
        out["versions"][ver] = seed_qaa_catalog_version(conn, ver, force=force)
    return out
