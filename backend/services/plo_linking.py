"""ربط مخرجات التعلم بمقررات الخطة وكتالوج course_master."""

from __future__ import annotations

from backend.core.plo_glo import COVERAGE_CYCLE, next_coverage_level
from backend.database.database import fetch_table_columns, is_postgresql

_VALID_LEVELS = frozenset({"I", "R", "M"})


def _has_coverage_column(cur, table: str) -> bool:
    return "coverage_level" in fetch_table_columns(cur, table)


def _normalize_level(level: str | None) -> str:
    lv = (level or "").strip().upper()
    return lv if lv in _VALID_LEVELS else "I"


def _pc_master_id(cur, program_course_id: int) -> int | None:
    row = cur.execute(
        "SELECT course_master_id FROM program_courses WHERE id = ?",
        (int(program_course_id),),
    ).fetchone()
    if not row:
        return None
    v = row[0] if not hasattr(row, "keys") else row["course_master_id"]
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _get_pc_coverage(cur, program_course_id: int, outcome_id: int) -> str:
    row = cur.execute(
        """
        SELECT COALESCE(coverage_level, '') FROM program_course_learning_outcomes
        WHERE program_course_id = ? AND outcome_id = ?
        """,
        (int(program_course_id), int(outcome_id)),
    ).fetchone()
    if not row:
        return ""
    return str(row[0] if not hasattr(row, "keys") else row["coverage_level"] or "").strip().upper()


def _get_master_coverage(cur, program_id: int, outcome_id: int, course_master_id: int) -> str:
    row = cur.execute(
        """
        SELECT COALESCE(coverage_level, '') FROM plo_course_master_links
        WHERE program_id = ? AND outcome_id = ? AND course_master_id = ?
        """,
        (int(program_id), int(outcome_id), int(course_master_id)),
    ).fetchone()
    if not row:
        return ""
    return str(row[0] if not hasattr(row, "keys") else row["coverage_level"] or "").strip().upper()


def master_link_exists(cur, program_id: int, outcome_id: int, course_master_id: int) -> bool:
    row = cur.execute(
        """
        SELECT 1 FROM plo_course_master_links
        WHERE program_id = ? AND outcome_id = ? AND course_master_id = ?
        """,
        (int(program_id), int(outcome_id), int(course_master_id)),
    ).fetchone()
    return bool(row)


def pc_link_exists(cur, program_course_id: int, outcome_id: int) -> bool:
    row = cur.execute(
        """
        SELECT 1 FROM program_course_learning_outcomes
        WHERE program_course_id = ? AND outcome_id = ?
        """,
        (int(program_course_id), int(outcome_id)),
    ).fetchone()
    return bool(row)


def _upsert_pc_link(cur, program_course_id: int, outcome_id: int, level: str) -> None:
    lv = _normalize_level(level)
    if is_postgresql():
        cur.execute(
            """
            INSERT INTO program_course_learning_outcomes (program_course_id, outcome_id, coverage_level)
            VALUES (?, ?, ?)
            ON CONFLICT (program_course_id, outcome_id)
            DO UPDATE SET coverage_level = EXCLUDED.coverage_level
            """,
            (int(program_course_id), int(outcome_id), lv),
        )
        return
    if pc_link_exists(cur, program_course_id, outcome_id):
        cur.execute(
            """
            UPDATE program_course_learning_outcomes SET coverage_level = ?
            WHERE program_course_id = ? AND outcome_id = ?
            """,
            (lv, int(program_course_id), int(outcome_id)),
        )
    else:
        cur.execute(
            """
            INSERT INTO program_course_learning_outcomes (program_course_id, outcome_id, coverage_level)
            VALUES (?, ?, ?)
            """,
            (int(program_course_id), int(outcome_id), lv),
        )


def _upsert_master_link(
    cur, program_id: int, outcome_id: int, course_master_id: int, level: str
) -> None:
    lv = _normalize_level(level)
    if is_postgresql():
        cur.execute(
            """
            INSERT INTO plo_course_master_links (program_id, outcome_id, course_master_id, coverage_level)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (program_id, outcome_id, course_master_id)
            DO UPDATE SET coverage_level = EXCLUDED.coverage_level
            """,
            (int(program_id), int(outcome_id), int(course_master_id), lv),
        )
        return
    if master_link_exists(cur, program_id, outcome_id, course_master_id):
        cur.execute(
            """
            UPDATE plo_course_master_links SET coverage_level = ?
            WHERE program_id = ? AND outcome_id = ? AND course_master_id = ?
            """,
            (lv, int(program_id), int(outcome_id), int(course_master_id)),
        )
    else:
        cur.execute(
            """
            INSERT INTO plo_course_master_links (program_id, outcome_id, course_master_id, coverage_level)
            VALUES (?, ?, ?, ?)
            """,
            (int(program_id), int(outcome_id), int(course_master_id), lv),
        )


def set_master_link(
    cur,
    program_id: int,
    outcome_id: int,
    course_master_id: int,
    linked: bool,
    *,
    coverage_level: str | None = None,
) -> None:
    if linked:
        _upsert_master_link(
            cur,
            program_id,
            outcome_id,
            course_master_id,
            coverage_level or "I",
        )
    else:
        cur.execute(
            """
            DELETE FROM plo_course_master_links
            WHERE program_id = ? AND outcome_id = ? AND course_master_id = ?
            """,
            (int(program_id), int(outcome_id), int(course_master_id)),
        )


def set_pc_link(
    cur,
    program_course_id: int,
    outcome_id: int,
    linked: bool,
    *,
    coverage_level: str | None = None,
) -> None:
    if linked:
        _upsert_pc_link(cur, int(program_course_id), outcome_id, coverage_level or "I")
    else:
        cur.execute(
            """
            DELETE FROM program_course_learning_outcomes
            WHERE program_course_id = ? AND outcome_id = ?
            """,
            (int(program_course_id), int(outcome_id)),
        )


def propagate_master_to_program_courses(
    cur,
    program_id: int,
    course_master_id: int,
    outcome_id: int,
    linked: bool,
    *,
    coverage_level: str | None = None,
) -> None:
    rows = cur.execute(
        """
        SELECT id FROM program_courses
        WHERE program_id = ? AND course_master_id = ? AND COALESCE(is_active, 1) = 1
        """,
        (int(program_id), int(course_master_id)),
    ).fetchall()
    for r in rows or []:
        pcid = int(r[0] if not hasattr(r, "keys") else r["id"])
        set_pc_link(cur, pcid, outcome_id, linked, coverage_level=coverage_level)


def set_cell_link(
    cur,
    program_id: int,
    outcome_id: int,
    *,
    program_course_id: int | None = None,
    course_master_id: int | None = None,
    linked: bool,
    sync_master: bool = True,
    coverage_level: str | None = None,
) -> None:
    """ربط/فك خلية في المصفوفة مع مزامنة course_master عند الطلب."""
    if program_course_id is not None:
        set_pc_link(
            cur,
            int(program_course_id),
            outcome_id,
            linked,
            coverage_level=coverage_level,
        )
        cmid = _pc_master_id(cur, int(program_course_id))
        if sync_master and cmid is not None:
            set_master_link(
                cur,
                program_id,
                outcome_id,
                cmid,
                linked,
                coverage_level=coverage_level,
            )
            propagate_master_to_program_courses(
                cur,
                program_id,
                cmid,
                outcome_id,
                linked,
                coverage_level=coverage_level,
            )
        return
    if course_master_id is not None:
        set_master_link(
            cur,
            program_id,
            outcome_id,
            int(course_master_id),
            linked,
            coverage_level=coverage_level,
        )
        propagate_master_to_program_courses(
            cur,
            program_id,
            int(course_master_id),
            outcome_id,
            linked,
            coverage_level=coverage_level,
        )


def cell_is_linked(
    cur,
    program_id: int,
    outcome_id: int,
    *,
    program_course_id: int | None = None,
    course_master_id: int | None = None,
) -> tuple[bool, str, str]:
    """يعيد (مرتبط؟, مصدر الربط, مستوى التغطية I/R/M)."""
    if program_course_id is not None:
        pc = pc_link_exists(cur, int(program_course_id), outcome_id)
        level = _get_pc_coverage(cur, int(program_course_id), outcome_id) if pc else ""
        cmid = _pc_master_id(cur, int(program_course_id))
        master = master_link_exists(cur, program_id, outcome_id, cmid) if cmid else False
        mlevel = _get_master_coverage(cur, program_id, outcome_id, cmid) if master and cmid else ""
        if not level and mlevel:
            level = mlevel
        if pc and master:
            return True, "both", level or mlevel or "I"
        if pc:
            return True, "pc", level or "I"
        if master:
            return True, "master", mlevel or "I"
        return False, "", ""
    if course_master_id is not None:
        if master_link_exists(cur, program_id, outcome_id, int(course_master_id)):
            lv = _get_master_coverage(cur, program_id, outcome_id, int(course_master_id))
            return True, "master", lv or "I"
        return False, "", ""
    return False, "", ""


def cycle_cell_coverage(
    cur,
    program_id: int,
    outcome_id: int,
    *,
    program_course_id: int | None = None,
    course_master_id: int | None = None,
    sync_master: bool = True,
) -> tuple[bool, str, str]:
    """دورة: فارغ → I → R → M → فارغ."""
    linked, src, level = cell_is_linked(
        cur,
        program_id,
        outcome_id,
        program_course_id=program_course_id,
        course_master_id=course_master_id,
    )
    current = level if linked else ""
    nxt = next_coverage_level(current)
    new_linked = bool(nxt)
    set_cell_link(
        cur,
        program_id,
        outcome_id,
        program_course_id=program_course_id,
        course_master_id=course_master_id,
        linked=new_linked,
        sync_master=sync_master,
        coverage_level=nxt if new_linked else None,
    )
    if new_linked:
        _, src2, _ = cell_is_linked(
            cur,
            program_id,
            outcome_id,
            program_course_id=program_course_id,
            course_master_id=course_master_id,
        )
        return True, src2, nxt
    return False, "", ""


def linked_outcome_ids_for_pc(cur, program_id: int, program_course_id: int) -> set[int]:
    cmid = _pc_master_id(cur, program_course_id)
    ids: set[int] = set()
    rows = cur.execute(
        """
        SELECT outcome_id FROM program_course_learning_outcomes
        WHERE program_course_id = ?
        """,
        (int(program_course_id),),
    ).fetchall()
    for r in rows or []:
        ids.add(int(r[0] if not hasattr(r, "keys") else r["outcome_id"]))
    if cmid is not None:
        mrows = cur.execute(
            """
            SELECT outcome_id FROM plo_course_master_links
            WHERE program_id = ? AND course_master_id = ?
            """,
            (int(program_id), int(cmid)),
        ).fetchall()
        for r in mrows or []:
            ids.add(int(r[0] if not hasattr(r, "keys") else r["outcome_id"]))
    return ids
