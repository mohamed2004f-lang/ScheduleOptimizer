"""تدقيق رموز مخرجات البرنامج (PLO/SO) وإصلاح خلط القوالب — خاصة ميكانيك."""

from __future__ import annotations

import re
from typing import Any

from backend.core.plo_glo import GLO_CODE_DOMAIN
from backend.core.program_goals import MECH_STUDENT_OUTCOMES

MECH_SO_CODES: frozenset[str] = frozenset(
    oc["code"] for oc in MECH_STUDENT_OUTCOMES if oc.get("code")
)
MECH_SO_GLO: dict[str, str] = {
    (oc.get("code") or "").strip().upper(): (oc.get("parent_glo_code") or "").strip().upper()
    for oc in MECH_STUDENT_OUTCOMES
    if oc.get("code")
}
ABET_PLO_TO_MECH_SO: dict[str, str] = {
    "PLO1": "SO1",
    "PLO2": "SO2",
    "PLO3": "SO3",
    "PLO4": "SO4",
    "PLO5": "SO5",
    "PLO6": "SO6",
}
MECH_TRACK_SUPPLEMENT_CODES: frozenset[str] = frozenset({"PLO8"})
_PLO_NUM = re.compile(r"^PLO(\d+)$", re.IGNORECASE)
_SO_NUM = re.compile(r"^SO(\d+)$", re.IGNORECASE)
_VALID_GLO = frozenset(GLO_CODE_DOMAIN.keys())


def _row_dict(row: Any) -> dict[str, Any]:
    if hasattr(row, "keys"):
        return dict(row)
    return {
        "id": row[0],
        "code": row[1],
        "parent_glo_code": row[2] if len(row) > 2 else "",
        "is_active": row[3] if len(row) > 3 else 1,
        "governance_status": row[4] if len(row) > 4 else "",
    }


def _program_context(cur, program_id: int) -> dict[str, Any] | None:
    row = cur.execute(
        """
        SELECT p.id, UPPER(TRIM(d.code)) AS department_code,
               COALESCE(p.track_group, '') AS track_group,
               UPPER(TRIM(p.code)) AS program_code
        FROM programs p
        JOIN departments d ON d.id = p.department_id
        WHERE p.id = ?
        """,
        (int(program_id),),
    ).fetchone()
    if not row:
        return None
    if hasattr(row, "keys"):
        return dict(row)
    return {
        "id": row[0],
        "department_code": row[1],
        "track_group": row[2] or "",
        "program_code": row[3],
    }


def _active_outcomes(cur, program_id: int) -> list[dict[str, Any]]:
    rows = cur.execute(
        """
        SELECT id, code, COALESCE(parent_glo_code, '') AS parent_glo_code,
               COALESCE(is_active, 1) AS is_active,
               COALESCE(governance_status, '') AS governance_status
        FROM program_learning_outcomes
        WHERE program_id = ?
        ORDER BY sort_order, code
        """,
        (int(program_id),),
    ).fetchall()
    return [_row_dict(r) for r in rows or []]


def audit_program_outcome_symbols(cur, program_id: int) -> dict[str, Any]:
    """يفحص تناسق الرموز ويرجع قائمة ملاحظات قابلة للعرض."""
    ctx = _program_context(cur, program_id)
    if not ctx:
        return {"status": "error", "message": "البرنامج غير موجود", "issues": []}

    dept = str(ctx.get("department_code") or "").upper()
    track = str(ctx.get("track_group") or "").strip()
    rows = _active_outcomes(cur, program_id)
    active = [r for r in rows if int(r.get("is_active") or 0) != 0]
    codes = [(r.get("code") or "").strip().upper() for r in active]
    code_set = set(codes)
    issues: list[dict[str, str]] = []

    plos = {c for c in code_set if _PLO_NUM.match(c)}
    sos = {c for c in code_set if _SO_NUM.match(c)}

    if dept == "MECH":
        if not track:
            stray = sorted(c for c in plos if c not in MECH_TRACK_SUPPLEMENT_CODES)
            if stray:
                issues.append(
                    {
                        "severity": "error",
                        "code": "stray_plo_on_mech",
                        "message_ar": (
                            f"برنامج ميكانيك الأساسي يجب أن يستخدم SO1–SO6 فقط؛ "
                            f"وُجدت رموز PLO زائدة: {', '.join(stray)}"
                        ),
                    }
                )
            missing = sorted(MECH_SO_CODES - code_set)
            if missing:
                issues.append(
                    {
                        "severity": "warning",
                        "code": "missing_mech_so",
                        "message_ar": f"مخرجات SO ناقصة: {', '.join(missing)}",
                    }
                )
            if plos and sos:
                issues.append(
                    {
                        "severity": "error",
                        "code": "mixed_plo_so",
                        "message_ar": (
                            "خلط بين قالب ABET (PLO) وقالب ميكانيك (SO) في نفس البرنامج — "
                            "يُفضّل SO1–SO6 فقط."
                        ),
                    }
                )
        else:
            bad_plo = sorted(c for c in plos if c not in MECH_TRACK_SUPPLEMENT_CODES)
            if bad_plo:
                issues.append(
                    {
                        "severity": "error",
                        "code": "stray_plo_on_track",
                        "message_ar": (
                            f"شعبة ميكانيك: المسموح SO1–SO6 + PLO8 فقط؛ "
                            f"زائد: {', '.join(bad_plo)}"
                        ),
                    }
                )
            if not sos:
                issues.append(
                    {
                        "severity": "warning",
                        "code": "missing_mech_so",
                        "message_ar": "الشعبة تفتقد مخرجات SO الأساسية — طبّق قالب ميكانيك أولاً.",
                    }
                )

        for r in active:
            code = (r.get("code") or "").strip().upper()
            expected_glo = MECH_SO_GLO.get(code)
            if not expected_glo:
                continue
            actual = (r.get("parent_glo_code") or "").strip().upper()
            if actual and actual != expected_glo:
                issues.append(
                    {
                        "severity": "warning",
                        "code": "wrong_glo_mapping",
                        "message_ar": (
                            f"{code} مربوط بـ {actual} بينما القالب الرسمي يتطلب {expected_glo}"
                        ),
                    }
                )
    else:
        if sos and plos:
            issues.append(
                {
                    "severity": "warning",
                    "code": "mixed_plo_so",
                    "message_ar": "خلط رموز SO (ميكانيك) مع PLO في برنامج غير ميكانيك.",
                }
            )

    for r in active:
        glo = (r.get("parent_glo_code") or "").strip().upper()
        code = (r.get("code") or "").strip().upper()
        if glo and glo not in _VALID_GLO:
            issues.append(
                {
                    "severity": "error",
                    "code": "invalid_glo",
                    "message_ar": f"{code}: رمز GLO غير معروف ({glo})",
                }
            )

    ok = not any(i["severity"] == "error" for i in issues)
    convention = "SO" if dept == "MECH" else "PLO"
    return {
        "status": "ok",
        "program_id": int(program_id),
        "department_code": dept,
        "track_group": track,
        "recommended_convention": convention,
        "active_outcome_count": len(active),
        "codes": sorted(code_set),
        "ok": ok,
        "issues": issues,
    }


def _outcome_id_by_code(cur, program_id: int, code: str) -> int | None:
    row = cur.execute(
        """
        SELECT id FROM program_learning_outcomes
        WHERE program_id = ? AND UPPER(TRIM(code)) = ?
        """,
        (int(program_id), code.strip().upper()),
    ).fetchone()
    if not row:
        return None
    return int(row[0] if not hasattr(row, "keys") else row["id"])


def _migrate_outcome_links(cur, from_id: int, to_id: int) -> int:
    if from_id == to_id:
        return 0
    moved = 0

    def _repoint(table: str, key_col: str) -> None:
        nonlocal moved
        rows = cur.execute(
            f"SELECT {key_col} FROM {table} WHERE outcome_id = ?",
            (int(from_id),),
        ).fetchall()
        for r in rows or []:
            key_val = r[0] if not hasattr(r, "keys") else r[key_col]
            dup = cur.execute(
                f"SELECT 1 FROM {table} WHERE {key_col} = ? AND outcome_id = ?",
                (key_val, int(to_id)),
            ).fetchone()
            if dup:
                cur.execute(
                    f"DELETE FROM {table} WHERE {key_col} = ? AND outcome_id = ?",
                    (key_val, int(from_id)),
                )
            else:
                cur.execute(
                    f"UPDATE {table} SET outcome_id = ? WHERE {key_col} = ? AND outcome_id = ?",
                    (int(to_id), key_val, int(from_id)),
                )
            moved += 1

    for tbl, col in (
        ("program_course_learning_outcomes", "program_course_id"),
        ("plo_course_master_links", "course_master_id"),
        ("clo_plo_links", "clo_id"),
        ("program_goal_outcome_links", "goal_id"),
        ("section_ilo_assessments", "section_id"),
    ):
        try:
            _repoint(tbl, col)
        except Exception:
            pass
    return moved


def _retire_outcome(cur, outcome_id: int) -> None:
    cur.execute(
        """
        UPDATE program_learning_outcomes
        SET is_active = 0, governance_status = 'retired'
        WHERE id = ?
        """,
        (int(outcome_id),),
    )


def cleanup_mech_stray_outcomes(cur, program_id: int) -> dict[str, Any]:
    """إيقاف PLO1–PLO7 الزائدة على ميكانيك ونقل الروابط إلى SO المكافئ."""
    ctx = _program_context(cur, program_id)
    if not ctx:
        return {"status": "error", "message": "البرنامج غير موجود"}
    if str(ctx.get("department_code") or "").upper() != "MECH":
        return {"status": "skipped", "message": "ليس برنامج ميكانيك"}

    track = str(ctx.get("track_group") or "").strip()
    allowed_plo = MECH_TRACK_SUPPLEMENT_CODES if track else frozenset()
    retired: list[str] = []
    migrated_links = 0

    rows = _active_outcomes(cur, program_id)
    for r in rows:
        if int(r.get("is_active") or 0) == 0:
            continue
        code = (r.get("code") or "").strip().upper()
        if not _PLO_NUM.match(code) or code in allowed_plo:
            continue
        oid = int(r["id"])
        target_code = ABET_PLO_TO_MECH_SO.get(code)
        if target_code:
            tid = _outcome_id_by_code(cur, program_id, target_code)
            if tid:
                migrated_links += _migrate_outcome_links(cur, oid, tid)
        _retire_outcome(cur, oid)
        retired.append(code)

    audit = audit_program_outcome_symbols(cur, program_id)
    return {
        "status": "ok",
        "program_id": int(program_id),
        "retired_codes": retired,
        "migrated_links": migrated_links,
        "audit": audit,
    }


def audit_all_programs(cur) -> list[dict[str, Any]]:
    rows = cur.execute(
        """
        SELECT p.id FROM programs p
        WHERE COALESCE(p.is_active, 1) = 1
        ORDER BY p.id
        """
    ).fetchall()
    reports = []
    for r in rows or []:
        pid = int(r[0] if not hasattr(r, "keys") else r["id"])
        rep = audit_program_outcome_symbols(cur, pid)
        if rep.get("issues"):
            reports.append(rep)
    return reports
