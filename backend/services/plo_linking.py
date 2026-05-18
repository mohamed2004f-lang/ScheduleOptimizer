"""ربط مخرجات التعلم بمقررات الخطة وكتالوج course_master."""

from __future__ import annotations

from backend.database.database import is_postgresql


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


def set_master_link(cur, program_id: int, outcome_id: int, course_master_id: int, linked: bool) -> None:
    if linked:
        if is_postgresql():
            cur.execute(
                """
                INSERT INTO plo_course_master_links (program_id, outcome_id, course_master_id)
                VALUES (?, ?, ?)
                ON CONFLICT (program_id, outcome_id, course_master_id) DO NOTHING
                """,
                (int(program_id), int(outcome_id), int(course_master_id)),
            )
        else:
            cur.execute(
                """
                INSERT OR IGNORE INTO plo_course_master_links (program_id, outcome_id, course_master_id)
                VALUES (?, ?, ?)
                """,
                (int(program_id), int(outcome_id), int(course_master_id)),
            )
    else:
        cur.execute(
            """
            DELETE FROM plo_course_master_links
            WHERE program_id = ? AND outcome_id = ? AND course_master_id = ?
            """,
            (int(program_id), int(outcome_id), int(course_master_id)),
        )


def set_pc_link(cur, program_course_id: int, outcome_id: int, linked: bool) -> None:
    if linked:
        if is_postgresql():
            cur.execute(
                """
                INSERT INTO program_course_learning_outcomes (program_course_id, outcome_id)
                VALUES (?, ?)
                ON CONFLICT (program_course_id, outcome_id) DO NOTHING
                """,
                (int(program_course_id), int(outcome_id)),
            )
        else:
            cur.execute(
                """
                INSERT OR IGNORE INTO program_course_learning_outcomes (program_course_id, outcome_id)
                VALUES (?, ?)
                """,
                (int(program_course_id), int(outcome_id)),
            )
    else:
        cur.execute(
            """
            DELETE FROM program_course_learning_outcomes
            WHERE program_course_id = ? AND outcome_id = ?
            """,
            (int(program_course_id), int(outcome_id)),
        )


def propagate_master_to_program_courses(cur, program_id: int, course_master_id: int, outcome_id: int, linked: bool) -> None:
    rows = cur.execute(
        """
        SELECT id FROM program_courses
        WHERE program_id = ? AND course_master_id = ? AND COALESCE(is_active, 1) = 1
        """,
        (int(program_id), int(course_master_id)),
    ).fetchall()
    for r in rows or []:
        pcid = int(r[0] if not hasattr(r, "keys") else r["id"])
        set_pc_link(cur, pcid, outcome_id, linked)


def set_cell_link(
    cur,
    program_id: int,
    outcome_id: int,
    *,
    program_course_id: int | None = None,
    course_master_id: int | None = None,
    linked: bool,
    sync_master: bool = True,
) -> None:
    """ربط/فك خلية في المصفوفة مع مزامنة course_master عند الطلب."""
    if program_course_id is not None:
        set_pc_link(cur, int(program_course_id), outcome_id, linked)
        cmid = _pc_master_id(cur, int(program_course_id))
        if sync_master and cmid is not None:
            set_master_link(cur, program_id, outcome_id, cmid, linked)
            propagate_master_to_program_courses(cur, program_id, cmid, outcome_id, linked)
        return
    if course_master_id is not None:
        set_master_link(cur, program_id, outcome_id, int(course_master_id), linked)
        propagate_master_to_program_courses(cur, program_id, int(course_master_id), outcome_id, linked)


def cell_is_linked(
    cur,
    program_id: int,
    outcome_id: int,
    *,
    program_course_id: int | None = None,
    course_master_id: int | None = None,
) -> tuple[bool, str]:
    if program_course_id is not None:
        pc = pc_link_exists(cur, int(program_course_id), outcome_id)
        cmid = _pc_master_id(cur, int(program_course_id))
        master = master_link_exists(cur, program_id, outcome_id, cmid) if cmid else False
        if pc and master:
            return True, "both"
        if pc:
            return True, "pc"
        if master:
            return True, "master"
        return False, ""
    if course_master_id is not None:
        if master_link_exists(cur, program_id, outcome_id, int(course_master_id)):
            return True, "master"
        return False, ""
    return False, ""


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
