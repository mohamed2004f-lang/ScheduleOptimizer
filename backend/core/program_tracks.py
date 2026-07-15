"""
كتالوج برامج الشعب/المسارات لكل قسم — جاهز للتوسع.

القسم MECH اليوم: برنامج أساس واحد (بدون شعبة) + برامج شعب معطّلة حتى التفعيل.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

DEFAULT_DEPT_GRADUATION_UNITS = 155

DEPT_GRADUATION_UNITS: dict[str, int] = {
    "MECH": 155,
    "CIVIL": 161,
    "ELEC": 160,
    "RENEW": 160,
}


def graduation_units_for_department_code(code: str | None) -> int:
    c = (code or "").strip().upper()
    return int(DEPT_GRADUATION_UNITS.get(c, DEFAULT_DEPT_GRADUATION_UNITS))

# أكواد البرنامج الأساسي (قديم → جديد)
LEGACY_BASE_PROGRAM_CODES = ("PROG_MAJOR",)
CANONICAL_BASE_PROGRAM_CODE = "MECH"

TRACK_GROUP_LABELS = {
    "": "خطة القسم (بدون شعبة)",
    "PWR": "شعبة القوى",
    "MFG": "شعبة الإنتاج",
    "DES": "شعبة التصميم",
    "STR": "شعبة إنشائي",
    "GEO": "شعبة جيوتقنية",
    "WTR": "شعبة مياه/بيئة",
    "COM": "شعبة اتصالات",
    "CTL": "شعبة تحكم",
    "SOL": "شعبة طاقة شمسية",
    "WND": "شعبة طاقة رياح",
}

BUILTIN_TRACK_GROUPS = frozenset(k for k in TRACK_GROUP_LABELS if k)


def parse_program_rules(rules_json: str | None) -> dict[str, Any]:
    if not rules_json or not str(rules_json).strip():
        return {}
    try:
        data = json.loads(rules_json)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def catalog_rules(rules_json: str | None) -> dict[str, Any]:
    cat = parse_program_rules(rules_json).get("catalog")
    return cat if isinstance(cat, dict) else {}


def names_customized_from_rules(rules_json: str | None) -> bool:
    return bool(catalog_rules(rules_json).get("names_customized"))


def is_custom_track_from_rules(rules_json: str | None) -> bool:
    return bool(catalog_rules(rules_json).get("custom_track"))


def merge_catalog_rules(
    rules_json: str | None,
    *,
    names_customized: bool | None = None,
    custom_track: bool | None = None,
    track_label_ar: str | None = None,
) -> str:
    data = parse_program_rules(rules_json)
    cat = dict(catalog_rules(rules_json))
    if names_customized is not None:
        cat["names_customized"] = bool(names_customized)
    if custom_track is not None:
        cat["custom_track"] = bool(custom_track)
    if track_label_ar is not None:
        t = str(track_label_ar).strip()
        if t:
            cat["track_label_ar"] = t
        elif "track_label_ar" in cat:
            del cat["track_label_ar"]
    if cat:
        data["catalog"] = cat
    elif "catalog" in data:
        del data["catalog"]
    return json.dumps(data, ensure_ascii=False) if data else ""


def _names_differ_from_template(
    current_ar: str | None,
    current_en: str | None,
    tpl: TrackProgramTemplate,
) -> bool:
    ar = (current_ar or "").strip()
    en = (current_en or "").strip()
    if ar and ar != (tpl.name_ar or "").strip():
        return True
    if en and en != (tpl.name_en or "").strip():
        return True
    return False


@dataclass(frozen=True)
class TrackProgramTemplate:
    program_code: str
    name_ar: str
    name_en: str
    track_group: str
    role: str  # base | track
    default_active: bool


# قوالب ميكانيك — يُنسخ نفس النمط لأقسام أخرى لاحقاً
MECH_TRACK_TEMPLATES: tuple[TrackProgramTemplate, ...] = (
    TrackProgramTemplate(
        CANONICAL_BASE_PROGRAM_CODE,
        "هندسة ميكانيكية — خطة القسم (بدون شعبة)",
        "Mechanical Engineering — Department Plan",
        "",
        "base",
        True,
    ),
    TrackProgramTemplate(
        "MECH-PWR",
        "هندسة ميكانيكية — شعبة القوى",
        "Mechanical Engineering — Power Track",
        "PWR",
        "track",
        False,
    ),
    TrackProgramTemplate(
        "MECH-MFG",
        "هندسة ميكانيكية — شعبة الإنتاج",
        "Mechanical Engineering — Manufacturing Track",
        "MFG",
        "track",
        False,
    ),
    TrackProgramTemplate(
        "MECH-DES",
        "هندسة ميكانيكية — شعبة التصميم",
        "Mechanical Engineering — Design Track",
        "DES",
        "track",
        False,
    ),
)

CIVIL_TRACK_TEMPLATES: tuple[TrackProgramTemplate, ...] = (
    TrackProgramTemplate(
        "CIVIL",
        "بكالوريوس الهندسة المدنية — خطة القسم",
        "Civil Engineering — Department Plan",
        "",
        "base",
        True,
    ),
    TrackProgramTemplate(
        "CIVIL-STR",
        "هندسة مدنية — شعبة إنشائي",
        "Civil Engineering — Structures",
        "STR",
        "track",
        False,
    ),
    TrackProgramTemplate(
        "CIVIL-GEO",
        "هندسة مدنية — شعبة جيوتقنية",
        "Civil Engineering — Geotechnical",
        "GEO",
        "track",
        False,
    ),
    TrackProgramTemplate(
        "CIVIL-WTR",
        "هندسة مدنية — شعبة مياه وبيئة",
        "Civil Engineering — Water & Environment",
        "WTR",
        "track",
        False,
    ),
)

ELEC_TRACK_TEMPLATES: tuple[TrackProgramTemplate, ...] = (
    TrackProgramTemplate(
        "ELEC",
        "بكالوريوس الهندسة الكهربائية — خطة القسم",
        "Electrical Engineering — Department Plan",
        "",
        "base",
        True,
    ),
    TrackProgramTemplate(
        "ELEC-PWR",
        "هندسة كهربائية — شعبة قوى",
        "Electrical Engineering — Power",
        "PWR",
        "track",
        False,
    ),
    TrackProgramTemplate(
        "ELEC-COM",
        "هندسة كهربائية — شعبة اتصالات",
        "Electrical Engineering — Communications",
        "COM",
        "track",
        False,
    ),
    TrackProgramTemplate(
        "ELEC-CTL",
        "هندسة كهربائية — شعبة تحكم",
        "Electrical Engineering — Control",
        "CTL",
        "track",
        False,
    ),
)

RENEW_TRACK_TEMPLATES: tuple[TrackProgramTemplate, ...] = (
    TrackProgramTemplate(
        "RENEW",
        "بكالوريوس هندسة الطاقات المتجددة — خطة القسم",
        "Renewable Energy — Department Plan",
        "",
        "base",
        True,
    ),
    TrackProgramTemplate(
        "RENEW-SOL",
        "طاقات متجددة — شعبة شمسية",
        "Renewable Energy — Solar",
        "SOL",
        "track",
        False,
    ),
    TrackProgramTemplate(
        "RENEW-WND",
        "طاقات متجددة — شعبة رياح",
        "Renewable Energy — Wind",
        "WND",
        "track",
        False,
    ),
)

DEPARTMENT_TRACK_CATALOGS: dict[str, tuple[TrackProgramTemplate, ...]] = {
    "MECH": MECH_TRACK_TEMPLATES,
    "CIVIL": CIVIL_TRACK_TEMPLATES,
    "ELEC": ELEC_TRACK_TEMPLATES,
    "RENEW": RENEW_TRACK_TEMPLATES,
}


def department_has_track_catalog(dept_code: str) -> bool:
    return (dept_code or "").strip().upper() in DEPARTMENT_TRACK_CATALOGS


def base_program_template(dept_code: str) -> TrackProgramTemplate | None:
    cat = DEPARTMENT_TRACK_CATALOGS.get((dept_code or "").strip().upper())
    if not cat:
        return None
    for tpl in cat:
        if tpl.role == "base":
            return tpl
    return cat[0] if cat else None


def track_template_presets(dept_code: str) -> list[dict[str, Any]]:
    """قوالب الشعب الجاهزة لقسم (للواجهة — ليس ميكانيك فقط)."""
    cat = DEPARTMENT_TRACK_CATALOGS.get((dept_code or "").strip().upper())
    if not cat:
        return []
    out: list[dict[str, Any]] = []
    for tpl in cat:
        if tpl.role != "track":
            continue
        tg = (tpl.track_group or "").strip().upper()
        out.append(
            {
                "track_group": tg,
                "program_code": tpl.program_code,
                "name_ar": tpl.name_ar,
                "name_en": tpl.name_en,
                "label_ar": track_group_label(tg) or tpl.name_ar,
            }
        )
    return out


def builtin_track_groups_for_department(dept_code: str) -> frozenset[str]:
    return frozenset(
        (p["track_group"] or "").upper()
        for p in track_template_presets(dept_code)
        if p.get("track_group")
    )


def department_tracks_note_ar(dept_code: str) -> str:
    dept = (dept_code or "").strip().upper()
    base = base_program_template(dept)
    if not base:
        return (
            "لا توجد قوالب شعب مُعرّفة لهذا القسم — استخدم «شعبة مخصصة» "
            "أو عرّف القسم في كتالوج المسارات."
        )
    tracks = track_template_presets(dept)
    tg_list = ", ".join(p["track_group"] for p in tracks) or "—"
    return (
        f"<strong>خطة القسم:</strong> برنامج <code>{base.program_code}</code> (بدون شعبة). "
        f"<strong>الشعب:</strong> قوالب ({tg_list}) أو <strong>شعبة مخصصة</strong>. "
        "التهيئة لا تستبدل الأسماء التي عدّلتها يدوياً."
    )


def track_group_label(
    track_group: str | None,
    *,
    rules_json: str | None = None,
    name_ar: str | None = None,
) -> str:
    cat = catalog_rules(rules_json)
    if cat.get("track_label_ar"):
        return str(cat["track_label_ar"]).strip()
    tg = (track_group or "").strip().upper()
    if tg in TRACK_GROUP_LABELS:
        return TRACK_GROUP_LABELS[tg]
    if tg:
        return tg
    if (name_ar or "").strip():
        return (name_ar or "").strip()
    return "—"


def program_role_label(
    track_group: str | None,
    program_code: str | None = None,
    *,
    rules_json: str | None = None,
    name_ar: str | None = None,
) -> str:
    code = (program_code or "").strip().upper()
    tg = (track_group or "").strip()
    if not tg and code in (CANONICAL_BASE_PROGRAM_CODE, *LEGACY_BASE_PROGRAM_CODES):
        return "خطة القسم"
    if not tg:
        return "خطة القسم"
    if is_custom_track_from_rules(rules_json) or (
        tg.upper() not in BUILTIN_TRACK_GROUPS
    ):
        return "شعبة مخصصة"
    return track_group_label(tg, rules_json=rules_json, name_ar=name_ar)


def _row_id(row: Any) -> int:
    if hasattr(row, "__getitem__"):
        try:
            return int(row["id"])
        except Exception:
            return int(row[0])
    raise TypeError(row)


def _find_program_id(cur, department_id: int, code: str) -> int | None:
    row = cur.execute(
        "SELECT id FROM programs WHERE department_id = ? AND code = ? LIMIT 1",
        (int(department_id), code),
    ).fetchone()
    if not row:
        return None
    return _row_id(row)


def ensure_department_track_programs(
    conn,
    department_code: str = "MECH",
    *,
    graduation_units: int | None = None,
) -> dict[str, Any]:
    """
    يضمن برنامج الأساس + قوالب الشعب (معطّلة افتراضياً).
    يُرحّل PROG_MAJOR → MECH عند الحاجة دون تكرار برنامجين أساسيين.
    """
    from backend.database.database import is_postgresql

    dept_code = (department_code or "").strip().upper()
    grad_units = (
        int(graduation_units)
        if graduation_units is not None
        else graduation_units_for_department_code(dept_code)
    )
    templates = DEPARTMENT_TRACK_CATALOGS.get(dept_code)
    if not templates:
        return {"status": "skipped", "department_code": dept_code, "reason": "no_catalog"}

    cur = conn.cursor()
    pg = is_postgresql()
    row = cur.execute(
        "SELECT id FROM departments WHERE UPPER(TRIM(code)) = ? LIMIT 1",
        (dept_code,),
    ).fetchone()
    if not row:
        return {"status": "error", "message": f"قسم {dept_code} غير موجود"}
    dept_id = _row_id(row)

    migrated_legacy = False
    legacy_id = _find_program_id(cur, dept_id, "PROG_MAJOR")
    base_id = _find_program_id(cur, dept_id, CANONICAL_BASE_PROGRAM_CODE)

    if legacy_id and not base_id:
        cur.execute(
            """
            UPDATE programs SET code = ?, name_ar = ?, name_en = ?, phase = 'major',
                track_group = '', min_total_units = ?, is_active = 1
            WHERE id = ?
            """,
            (
                CANONICAL_BASE_PROGRAM_CODE,
                templates[0].name_ar,
                templates[0].name_en,
                int(grad_units),
                legacy_id,
            ),
        )
        base_id = legacy_id
        migrated_legacy = True
    elif legacy_id and base_id and legacy_id != base_id:
        cur.execute(
            "UPDATE students SET current_program_id = ? WHERE current_program_id = ?",
            (base_id, legacy_id),
        )
        cur.execute(
            "UPDATE students SET admission_program_id = ? WHERE admission_program_id = ?",
            (base_id, legacy_id),
        )
        cur.execute("UPDATE programs SET is_active = 0 WHERE id = ?", (legacy_id,))

    results: list[dict[str, Any]] = []

    for tpl in templates:
        existing_id = _find_program_id(cur, dept_id, tpl.program_code)
        is_active = 1 if tpl.default_active else 0
        if tpl.role == "track" and existing_id:
            row_p = cur.execute(
                "SELECT is_active FROM programs WHERE id = ?",
                (existing_id,),
            ).fetchone()
            if row_p:
                cur_val = row_p[0] if not hasattr(row_p, "keys") else row_p["is_active"]
                is_active = int(cur_val or 0)

        if existing_id:
            row_ex = cur.execute(
                """
                SELECT name_ar, name_en, rules_json FROM programs WHERE id = ?
                """,
                (existing_id,),
            ).fetchone()
            cur_ar = cur_en = cur_rules = ""
            if row_ex:
                if hasattr(row_ex, "keys"):
                    cur_ar = row_ex["name_ar"] or ""
                    cur_en = row_ex["name_en"] or ""
                    cur_rules = row_ex["rules_json"] or ""
                else:
                    cur_ar, cur_en, cur_rules = row_ex[0], row_ex[1], row_ex[2]

            preserve_names = names_customized_from_rules(cur_rules) or _names_differ_from_template(
                cur_ar, cur_en, tpl
            )
            if preserve_names and not names_customized_from_rules(cur_rules):
                cur_rules = merge_catalog_rules(cur_rules, names_customized=True)

            if preserve_names:
                cur.execute(
                    """
                    UPDATE programs SET phase = 'major', track_group = ?,
                        min_total_units = ?, rules_json = NULLIF(?, '')
                    WHERE id = ?
                    """,
                    (
                        tpl.track_group,
                        int(grad_units),
                        cur_rules,
                        existing_id,
                    ),
                )
                action = "updated_preserve_names"
            else:
                cur.execute(
                    """
                    UPDATE programs SET name_ar = ?, name_en = ?, phase = 'major',
                        track_group = ?, min_total_units = ?
                    WHERE id = ?
                    """,
                    (
                        tpl.name_ar,
                        tpl.name_en,
                        tpl.track_group,
                        int(grad_units),
                        existing_id,
                    ),
                )
                action = "updated"
            pid = existing_id
        elif pg:
            cur.execute(
                """
                INSERT INTO programs
                (department_id, code, name_ar, name_en, phase, track_group,
                 min_total_units, is_active)
                VALUES (?, ?, ?, ?, 'major', ?, ?, ?)
                RETURNING id
                """,
                (
                    dept_id,
                    tpl.program_code,
                    tpl.name_ar,
                    tpl.name_en,
                    tpl.track_group,
                    int(grad_units),
                    is_active,
                ),
            )
            pid = _row_id(cur.fetchone())
            action = "created"
        else:
            cur.execute(
                """
                INSERT INTO programs
                (department_id, code, name_ar, name_en, phase, track_group,
                 min_total_units, is_active)
                VALUES (?, ?, ?, ?, 'major', ?, ?, ?)
                """,
                (
                    dept_id,
                    tpl.program_code,
                    tpl.name_ar,
                    tpl.name_en,
                    tpl.track_group,
                    int(grad_units),
                    is_active,
                ),
            )
            pid = int(
                getattr(cur, "lastrowid", None)
                or cur.execute("SELECT last_insert_rowid()").fetchone()[0]
            )
            action = "created"

        results.append(
            {
                "id": pid,
                "program_code": tpl.program_code,
                "track_group": tpl.track_group,
                "role": tpl.role,
                "is_active": is_active,
                "action": action,
            }
        )

    conn.commit()
    base = next((r for r in results if r["role"] == "base"), None)
    tracks = [r for r in results if r["role"] == "track"]
    return {
        "status": "ok",
        "department_code": dept_code,
        "department_id": dept_id,
        "migrated_prog_major_to_mech": migrated_legacy,
        "base_program": base,
        "track_programs": tracks,
        "programs": results,
    }


def resolve_base_program_id(cur, department_code: str = "MECH") -> int | None:
    """معرّف برنامج الأساس (MECH أو PROG_MAJOR)."""
    row = cur.execute(
        """
        SELECT p.id FROM programs p
        INNER JOIN departments d ON d.id = p.department_id
        WHERE UPPER(TRIM(d.code)) = UPPER(TRIM(?))
          AND TRIM(p.code) IN (?, 'PROG_MAJOR')
        ORDER BY CASE WHEN TRIM(p.code) = ? THEN 0 ELSE 1 END,
                 COALESCE(p.is_active, 1) DESC
        LIMIT 1
        """,
        (
            department_code,
            CANONICAL_BASE_PROGRAM_CODE,
            CANONICAL_BASE_PROGRAM_CODE,
        ),
    ).fetchone()
    if not row:
        return None
    return _row_id(row)
