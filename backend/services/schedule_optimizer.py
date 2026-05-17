"""
محرك اقتراح نقل مقررات الجدول (قواعد + بحث عن خانات فارغة).
لا يعتمد على OR-Tools؛ يمكن استبداله لاحقاً بمحسّن CP-SAT.
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from backend.database.database import table_exists

logger = logging.getLogger(__name__)


@dataclass
class OptimizeParams:
    max_alternatives_per_section: int = 3
    move_cost: float = 1.0
    add_room_conflict: bool = True
    add_instructor_conflict: bool = True
    time_limit_seconds: int = 30

    @classmethod
    def from_dict(cls, data: dict | None) -> OptimizeParams:
        data = data or {}
        try:
            max_alt = int(data.get("max_alternatives_per_section") or 3)
        except (TypeError, ValueError):
            max_alt = 3
        try:
            move_cost = float(data.get("move_cost") or 1.0)
        except (TypeError, ValueError):
            move_cost = 1.0
        try:
            tlim = int(data.get("time_limit_seconds") or 30)
        except (TypeError, ValueError):
            tlim = 30
        return cls(
            max_alternatives_per_section=max(1, min(10, max_alt)),
            move_cost=max(0.0, move_cost),
            add_room_conflict=bool(data.get("add_room_conflict", True)),
            add_instructor_conflict=bool(data.get("add_instructor_conflict", True)),
            time_limit_seconds=max(5, min(120, tlim)),
        )


def _schedule_helpers():
    from backend.services import schedule as sched

    return sched


def _section_id_sql(pk: str) -> str:
    """تعبير معرّف الصف — يدعم SQLite حيث id قد يكون NULL ويُستخدم rowid."""
    if pk == "id":
        return "COALESCE(s.id, s.rowid)"
    return f"s.{pk}"


def _load_sections(conn) -> list[dict[str, Any]]:
    sched = _schedule_helpers()
    sched._sync_schedule_pk_col(conn)
    pk = sched.SCHEDULE_PK_COL
    sid_expr = _section_id_sql(pk)
    cur = conn.cursor()
    rows = cur.execute(
        f"""
        SELECT {sid_expr} AS section_id,
               COALESCE(s.course_name,'') AS course_name,
               COALESCE(s.day,'') AS day,
               COALESCE(s.time,'') AS time,
               COALESCE(s.room,'') AS room,
               COALESCE(s.instructor,'') AS instructor
        FROM schedule s
        WHERE COALESCE(s.course_name,'') <> ''
          AND COALESCE(s.day,'') <> ''
          AND COALESCE(s.time,'') <> ''
        """
    ).fetchall()
    out = []
    sched_mod = sched
    for r in rows or []:
        d = dict(r)
        if d.get("section_id") is None:
            continue
        start_min, end_min = sched_mod._parse_time_range_to_minutes(d.get("time") or "")
        if start_min is None or end_min is None:
            continue
        d["start_min"] = start_min
        d["end_min"] = end_min
        d["section_id"] = int(d["section_id"])
        out.append(d)
    return out


def _overlap_groups(items: list[dict], key_fn) -> list[list[dict]]:
    """مجموعات عناصر متعارضة زمنياً ضمن نفس مفتاح التجميع."""
    sched = _schedule_helpers()
    by_key: dict[Any, list[dict]] = defaultdict(list)
    for it in items:
        by_key[key_fn(it)].append(it)

    groups: list[list[dict]] = []
    for lst in by_key.values():
        if len(lst) < 2:
            continue
        lst = sorted(lst, key=lambda x: (x["start_min"], x["end_min"], x["section_id"]))
        n = len(lst)
        adj = [[] for _ in range(n)]
        for i in range(n):
            for j in range(i + 1, n):
                if sched._ranges_overlap(
                    lst[i]["start_min"],
                    lst[i]["end_min"],
                    lst[j]["start_min"],
                    lst[j]["end_min"],
                ):
                    adj[i].append(j)
                    adj[j].append(i)
        seen = [False] * n
        for i in range(n):
            if seen[i]:
                continue
            stack = [i]
            comp = []
            seen[i] = True
            while stack:
                u = stack.pop()
                comp.append(lst[u])
                for v in adj[u]:
                    if not seen[v]:
                        seen[v] = True
                        stack.append(v)
            if len(comp) >= 2:
                groups.append(comp)
    return groups


def _room_conflict_section_ids(sections: list[dict]) -> set[int]:
    with_room = [s for s in sections if (s.get("room") or "").strip()]
    ids: set[int] = set()
    for grp in _overlap_groups(with_room, lambda s: ((s.get("day") or "").strip(), (s.get("room") or "").strip())):
        for s in grp[1:]:
            ids.add(int(s["section_id"]))
    return ids


def _instructor_conflict_section_ids(sections: list[dict]) -> set[int]:
    with_inst = [s for s in sections if (s.get("instructor") or "").strip()]
    ids: set[int] = set()
    for grp in _overlap_groups(
        with_inst,
        lambda s: ((s.get("instructor") or "").strip(), (s.get("day") or "").strip()),
    ):
        for s in grp[1:]:
            ids.add(int(s["section_id"]))
    return ids


def _slot_occupied(
    sections: list[dict],
    day: str,
    time_slot: str,
    *,
    room: str,
    instructor: str,
    exclude_section_id: int,
    check_room: bool,
    check_instructor: bool,
) -> bool:
    sched = _schedule_helpers()
    cand_start, cand_end = sched._parse_time_range_to_minutes(time_slot)
    if cand_start is None or cand_end is None:
        return True
    for s in sections:
        if int(s["section_id"]) == exclude_section_id:
            continue
        if (s.get("day") or "").strip() != day:
            continue
        if not sched._ranges_overlap(s["start_min"], s["end_min"], cand_start, cand_end):
            continue
        if check_room and room and (s.get("room") or "").strip() == room:
            return True
        if check_instructor and instructor and (s.get("instructor") or "").strip() == instructor:
            return True
    return False


def _candidate_slots(
    conn,
    section: dict,
    sections: list[dict],
    params: OptimizeParams,
    deadline: float,
) -> list[tuple[str, str, float]]:
    sched = _schedule_helpers()
    slots_info = sched._get_time_slots_setting(conn)
    time_slots = slots_info.get("slots") or sched._default_time_slots()
    days = sched._days_ar()

    room = (section.get("room") or "").strip()
    instructor = (section.get("instructor") or "").strip()
    orig_day = (section.get("day") or "").strip()
    orig_time = (section.get("time") or "").strip()
    sid = int(section["section_id"])

    candidates: list[tuple[str, str, float]] = []
    for day in days:
        if time.time() > deadline:
            break
        for ts in time_slots:
            if time.time() > deadline:
                break
            ts = (ts or "").strip()
            if not ts or (day == orig_day and ts == orig_time):
                continue
            if _slot_occupied(
                sections,
                day,
                ts,
                room=room,
                instructor=instructor,
                exclude_section_id=sid,
                check_room=params.add_room_conflict,
                check_instructor=params.add_instructor_conflict,
            ):
                continue
            cost = params.move_cost
            if day != orig_day:
                cost += params.move_cost * 0.5
            candidates.append((day, ts, cost))

    candidates.sort(key=lambda x: (x[2], x[0] != orig_day, x[0], x[1]))
    return candidates[: params.max_alternatives_per_section]


def generate_proposed_moves(conn, params: OptimizeParams | None = None) -> list[dict[str, Any]]:
    """يحسب اقتراحات النقل ويخزّنها في proposed_moves."""
    params = params or OptimizeParams()
    if not table_exists(conn, "proposed_moves"):
        return []

    sections = _load_sections(conn)
    if not sections:
        return []

    conflict_ids: set[int] = set()
    if params.add_room_conflict:
        conflict_ids |= _room_conflict_section_ids(sections)
    if params.add_instructor_conflict:
        conflict_ids |= _instructor_conflict_section_ids(sections)

    by_id = {int(s["section_id"]): s for s in sections}
    deadline = time.time() + params.time_limit_seconds
    moves: list[dict[str, Any]] = []

    for sid in sorted(conflict_ids):
        if time.time() > deadline:
            break
        sec = by_id.get(sid)
        if not sec:
            continue
        for day, ts, cost in _candidate_slots(conn, sec, sections, params, deadline):
            moves.append(
                {
                    "section_id": sid,
                    "course_name": sec.get("course_name") or "",
                    "orig_day": sec.get("day") or "",
                    "orig_time": sec.get("time") or "",
                    "new_day": day,
                    "new_time": ts,
                    "move_cost": cost,
                }
            )

    persist_proposed_moves(conn, moves)
    return moves


def persist_proposed_moves(conn, moves: list[dict[str, Any]]) -> None:
    if not table_exists(conn, "proposed_moves"):
        return
    cur = conn.cursor()
    cur.execute("DELETE FROM proposed_moves")
    for m in moves:
        cur.execute(
            """
            INSERT INTO proposed_moves (section_id, orig_day, orig_time, new_day, new_time, move_cost)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                m["section_id"],
                m["orig_day"],
                m["orig_time"],
                m["new_day"],
                m["new_time"],
                m["move_cost"],
            ),
        )


def list_proposed_moves(conn) -> list[dict[str, Any]]:
    if not table_exists(conn, "proposed_moves"):
        return []
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT id, section_id, orig_day, orig_time, new_day, new_time, move_cost
        FROM proposed_moves
        ORDER BY move_cost ASC, id ASC
        """
    ).fetchall()
    out = []
    sections = {int(s["section_id"]): s for s in _load_sections(conn)}
    for r in rows or []:
        d = dict(r)
        sid = int(d.get("section_id") or 0)
        sec = sections.get(sid) or {}
        out.append(
            {
                "id": d.get("id"),
                "section_id": sid,
                "course_name": sec.get("course_name") or "",
                "room": sec.get("room") or "",
                "instructor": sec.get("instructor") or "",
                "orig_day": d.get("orig_day") or "",
                "orig_time": d.get("orig_time") or "",
                "new_day": d.get("new_day") or "",
                "new_time": d.get("new_time") or "",
                "move_cost": d.get("move_cost"),
            }
        )
    return out


def apply_proposed_move(conn, section_id: int, move_id: int | None = None) -> dict[str, Any]:
    """تطبيق اقتراح نقل على schedule ثم مزامنة optimized_schedule."""
    if not table_exists(conn, "proposed_moves"):
        raise ValueError("جدول proposed_moves غير موجود")

    cur = conn.cursor()
    if move_id is not None:
        row = cur.execute(
            "SELECT id, section_id, new_day, new_time FROM proposed_moves WHERE id = ? AND section_id = ?",
            (move_id, section_id),
        ).fetchone()
    else:
        row = cur.execute(
            """
            SELECT id, section_id, new_day, new_time FROM proposed_moves
            WHERE section_id = ?
            ORDER BY move_cost ASC, id ASC
            LIMIT 1
            """,
            (section_id,),
        ).fetchone()
    if not row:
        raise ValueError("لا يوجد اقتراح نقل لهذا القسم")

    d = dict(row)
    mid = int(d["id"])
    new_day = (d.get("new_day") or "").strip()
    new_time = (d.get("new_time") or "").strip()
    if not new_day or not new_time:
        raise ValueError("اقتراح النقل ناقص (يوم/وقت)")

    sched = _schedule_helpers()
    sched._sync_schedule_pk_col(conn)
    pk = sched.SCHEDULE_PK_COL

    from backend.core.services import ScheduleService

    ScheduleService.update_schedule_row(int(section_id), day=new_day, time=new_time)

    cur.execute("DELETE FROM proposed_moves WHERE section_id = ?", (section_id,))
    if table_exists(conn, "optimized_schedule"):
        cur.execute(
            """
            UPDATE optimized_schedule
            SET day = ?, time = ?
            WHERE section_id = ?
            """,
            (new_day, new_time, section_id),
        )
    conn.commit()

    return {
        "status": "ok",
        "message": "تم تطبيق اقتراح النقل",
        "move_id": mid,
        "section_id": int(section_id),
        "new_day": new_day,
        "new_time": new_time,
    }


def optimize_with_move_suggestions(
    conn,
    params: OptimizeParams | None = None,
    *,
    sync_optimized: bool = True,
    prefer_cpsat: bool = True,
) -> dict[str, Any]:
    """
    تشغيل التحسين: مزامنة الجدول المعروض، اقتراحات النقل، إعادة حساب تعارضات الطلبة.
    يحاول CP-SAT أولاً عند توفر OR-Tools، ثم القواعد كاحتياط.
    """
    import os

    from backend.services.schedule import _sync_optimized_schedule_from_current
    from backend.services.students import recompute_conflict_report

    params = params or OptimizeParams()
    rows_synced = 0
    if sync_optimized:
        rows_synced = _sync_optimized_schedule_from_current(conn)

    sections = _load_sections(conn)
    moves: list[dict[str, Any]] = []
    optimizer = "rule_based_slots"

    use_cpsat = prefer_cpsat and (os.environ.get("OPTIMIZER_USE_CPSAT", "1").strip().lower() not in ("0", "false", "no"))
    if use_cpsat:
        try:
            from backend.services.schedule_cpsat import cpsat_available, generate_moves_cpsat

            if cpsat_available():
                moves = generate_moves_cpsat(conn, params, sections=sections)
                if moves:
                    persist_proposed_moves(conn, moves)
                    optimizer = "cp_sat"
        except Exception as exc:
            logger.warning("CP-SAT optimizer failed, falling back to rules: %s", exc)

    if optimizer != "cp_sat":
        moves = generate_proposed_moves(conn, params)

    conflict_count = recompute_conflict_report(conn)
    conn.commit()

    return {
        "schedule_rows": rows_synced,
        "proposed_moves_count": len(moves),
        "conflict_count": conflict_count,
        "optimizer": optimizer,
        "params": {
            "max_alternatives_per_section": params.max_alternatives_per_section,
            "move_cost": params.move_cost,
            "add_room_conflict": params.add_room_conflict,
            "add_instructor_conflict": params.add_instructor_conflict,
        },
    }
