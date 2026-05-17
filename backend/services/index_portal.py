"""بوابة index: تحويل Excel وقوالب التحميل."""
from __future__ import annotations

import io
from typing import Any

import pandas as pd
from flask import Blueprint, jsonify, request, send_file

from backend.core.auth import login_required

index_portal_bp = Blueprint("index_portal", __name__)

_ALIASES = {
    "students": {
        "student_id": ("student_id", "id", "رقم", "الرقم", "الرقم الدراسي", "رقم الطالب"),
        "student_name": ("student_name", "name", "اسم", "اسم الطالب", "الاسم"),
    },
    "schedule": {
        "course_name": ("course_name", "course", "المقرر", "اسم المقرر", "مقرر"),
        "day": ("day", "اليوم", "يوم"),
        "time": ("time", "الوقت", "وقت", "الفترة"),
        "room": ("room", "قاعة", "القاعة", "hall"),
        "instructor": ("instructor", "professor", "أستاذ", "الأستاذ", "مدرس"),
        "semester": ("semester", "فصل", "الفصل", "term"),
    },
    "registrations": {
        "student_id": ("student_id", "id", "رقم", "الرقم", "الرقم الدراسي"),
        "course_name": ("course_name", "course", "المقرر", "اسم المقرر", "مقرر"),
    },
}

_TEMPLATE_COLUMNS = {
    "students": ["student_id", "student_name"],
    "schedule": ["course_name", "day", "time", "room", "instructor", "semester"],
    "registrations": ["student_id", "course_name"],
}

_TEMPLATE_SAMPLES = {
    "students": [{"student_id": "1200", "student_name": "أحمد محمد"}],
    "schedule": [
        {
            "course_name": "ميكانيكا_1",
            "day": "السبت",
            "time": "08:00-10:00",
            "room": "A1",
            "instructor": "د. علي",
            "semester": "خريف",
        }
    ],
    "registrations": [{"student_id": "1200", "course_name": "ميكانيكا_1"}],
}


def _norm_col(name: str) -> str:
    return str(name or "").strip().lower().replace(" ", "_")


def _map_columns(df: pd.DataFrame, kind: str) -> pd.DataFrame:
    aliases = _ALIASES.get(kind, {})
    col_map: dict[str, str] = {}
    normalized = {_norm_col(c): c for c in df.columns}
    for target, options in aliases.items():
        for opt in options:
            key = _norm_col(opt)
            if key in normalized:
                col_map[normalized[key]] = target
                break
    if not col_map:
        return df
    out = df.rename(columns=col_map)
    required = list(aliases.keys())
    missing = [c for c in required if c not in out.columns]
    if missing:
        raise ValueError(f"أعمدة مطلوبة غير موجودة: {', '.join(missing)}")
    return out[required]


def _records_from_excel(file_storage, kind: str) -> list[dict[str, Any]]:
    df = pd.read_excel(file_storage)
    if df.empty:
        return []
    df.columns = [_norm_col(c) for c in df.columns]
    df = _map_columns(df, kind)
    rows: list[dict[str, Any]] = []
    for r in df.to_dict(orient="records"):
        clean = {}
        for k, v in r.items():
            if pd.isna(v):
                clean[k] = ""
            elif isinstance(v, float) and v == int(v):
                clean[k] = str(int(v))
            else:
                clean[k] = str(v).strip() if v is not None else ""
        if kind == "students" and not clean.get("student_id"):
            continue
        if kind == "registrations" and not (clean.get("student_id") and clean.get("course_name")):
            continue
        if kind == "schedule" and not (clean.get("course_name") and clean.get("day") and clean.get("time")):
            continue
        rows.append(clean)
    return rows


@index_portal_bp.route("/parse-excel", methods=["POST"])
@login_required
def parse_excel():
    kind = (request.form.get("type") or "").strip().lower()
    if kind not in _ALIASES:
        return jsonify({"status": "error", "message": "نوع غير مدعوم"}), 400
    f = request.files.get("file")
    if not f:
        return jsonify({"status": "error", "message": "الملف مطلوب"}), 400
    try:
        rows = _records_from_excel(f, kind)
        return jsonify({"status": "ok", "type": kind, "rows": rows, "count": len(rows)}), 200
    except ValueError as e:
        return jsonify({"status": "error", "message": str(e)}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": f"تعذّر قراءة الملف: {e}"}), 500


@index_portal_bp.route("/template/<kind>", methods=["GET"])
@login_required
def download_template(kind: str):
    kind = (kind or "").strip().lower()
    if kind not in _TEMPLATE_COLUMNS:
        return jsonify({"status": "error", "message": "قالب غير موجود"}), 404
    df = pd.DataFrame(_TEMPLATE_SAMPLES.get(kind, []), columns=_TEMPLATE_COLUMNS[kind])
    buf = io.BytesIO()
    df.to_excel(buf, index=False, sheet_name=kind)
    buf.seek(0)
    return send_file(
        buf,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=f"template_{kind}.xlsx",
    )
