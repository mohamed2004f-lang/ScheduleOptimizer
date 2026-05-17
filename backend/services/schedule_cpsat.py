"""
تحسين الجدول باستخدام Google OR-Tools CP-SAT.
يُعيد اقتراحات نقل للمقاطع المتعارضة (قاعة / أستاذ).
"""
from __future__ import annotations

import logging
from typing import Any

from backend.services.schedule_optimizer import (
    OptimizeParams,
    _instructor_conflict_section_ids,
    _load_sections,
    _room_conflict_section_ids,
    _schedule_helpers,
)

logger = logging.getLogger(__name__)

_CPSAT_AVAILABLE: bool | None = None


def cpsat_available() -> bool:
    global _CPSAT_AVAILABLE
    if _CPSAT_AVAILABLE is None:
        try:
            from ortools.sat.python import cp_model  # noqa: F401

            _CPSAT_AVAILABLE = True
        except ImportError:
            _CPSAT_AVAILABLE = False
    return _CPSAT_AVAILABLE


def _build_slots(conn) -> list[tuple[str, str]]:
    sched = _schedule_helpers()
    info = sched._get_time_slots_setting(conn)
    slots_list = info.get("slots") or sched._default_time_slots()
    days = sched._days_ar()
    return [(d, (ts or "").strip()) for d in days for ts in slots_list if (ts or "").strip()]


def _slot_index(slots: list[tuple[str, str]], day: str, time_str: str) -> int | None:
    key = ((day or "").strip(), (time_str or "").strip())
    for i, s in enumerate(slots):
        if s == key:
            return i
    return None


def _forbidden_slots_for_section(
    section: dict,
    slots: list[tuple[str, str]],
    fixed_sections: list[dict],
    params: OptimizeParams,
) -> set[int]:
    """خانات ممنوعة بسبب مقاطع ثابتة (غير قيد إعادة التوزيع)."""
    sched = _schedule_helpers()
    forbidden: set[int] = set()
    room = (section.get("room") or "").strip()
    instructor = (section.get("instructor") or "").strip()
    for j, (day, ts) in enumerate(slots):
        cs, ce = sched._parse_time_range_to_minutes(ts)
        if cs is None:
            forbidden.add(j)
            continue
        for other in fixed_sections:
            if (other.get("day") or "").strip() != day:
                continue
            if not sched._ranges_overlap(cs, ce, other["start_min"], other["end_min"]):
                continue
            if params.add_room_conflict and room and (other.get("room") or "").strip() == room:
                forbidden.add(j)
                break
            if params.add_instructor_conflict and instructor and (other.get("instructor") or "").strip() == instructor:
                forbidden.add(j)
                break
    return forbidden


def generate_moves_cpsat(
    conn,
    params: OptimizeParams,
    sections: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """
    يُعيد قائمة اقتراحات نقل (بدون كتابة DB).
    يرمي RuntimeError إذا OR-Tools غير متاح أو لا يوجد حل.
    """
    if not cpsat_available():
        raise RuntimeError("OR-Tools غير مثبت")

    from ortools.sat.python import cp_model

    sections = sections or _load_sections(conn)
    if not sections:
        return []

    slots = _build_slots(conn)
    if not slots:
        raise RuntimeError("لا توجد خانات زمنية للتحسين")

    conflict_ids = set()
    if params.add_room_conflict:
        conflict_ids |= _room_conflict_section_ids(sections)
    if params.add_instructor_conflict:
        conflict_ids |= _instructor_conflict_section_ids(sections)

    if not conflict_ids:
        return []

    conflict_secs = [s for s in sections if int(s["section_id"]) in conflict_ids]
    fixed_secs = [s for s in sections if int(s["section_id"]) not in conflict_ids]

    n = len(conflict_secs)
    m = len(slots)
    model = cp_model.CpModel()

    x: dict[tuple[int, int], Any] = {}
    for i in range(n):
        orig_j = _slot_index(slots, conflict_secs[i].get("day") or "", conflict_secs[i].get("time") or "")
        forbidden = _forbidden_slots_for_section(conflict_secs[i], slots, fixed_secs, params)
        for j in range(m):
            x[i, j] = model.NewBoolVar(f"assign_{i}_{j}")
            if j in forbidden:
                model.Add(x[i, j] == 0)

        model.Add(sum(x[i, j] for j in range(m)) == 1)
        if orig_j is not None and orig_j not in forbidden:
            pass  # يُسمح بالبقاء في الموضع الأصلي

    # قاعة واحدة لكل خانة
    if params.add_room_conflict:
        rooms = {(s.get("room") or "").strip() for s in conflict_secs if (s.get("room") or "").strip()}
        for room in rooms:
            idxs = [i for i, s in enumerate(conflict_secs) if (s.get("room") or "").strip() == room]
            for j in range(m):
                model.Add(sum(x[i, j] for i in idxs) <= 1)

    # أستاذ واحد لكل خانة
    if params.add_instructor_conflict:
        insts = {(s.get("instructor") or "").strip() for s in conflict_secs if (s.get("instructor") or "").strip()}
        for inst in insts:
            idxs = [i for i, s in enumerate(conflict_secs) if (s.get("instructor") or "").strip() == inst]
            for j in range(m):
                model.Add(sum(x[i, j] for i in idxs) <= 1)

    # تكلفة النقل
    costs = []
    for i, sec in enumerate(conflict_secs):
        orig_j = _slot_index(slots, sec.get("day") or "", sec.get("time") or "")
        for j in range(m):
            c = 0 if j == orig_j else int(params.move_cost * 100)
            costs.append(c * x[i, j])
    if costs:
        model.Minimize(sum(costs))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(params.time_limit_seconds)
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise RuntimeError("لم يجد CP-SAT حلاً ضمن المهلة")

    moves: list[dict[str, Any]] = []
    for i, sec in enumerate(conflict_secs):
        chosen = None
        for j in range(m):
            if solver.Value(x[i, j]):
                chosen = j
                break
        if chosen is None:
            continue
        orig_j = _slot_index(slots, sec.get("day") or "", sec.get("time") or "")
        if chosen == orig_j:
            continue
        day, ts = slots[chosen]
        moves.append(
            {
                "section_id": int(sec["section_id"]),
                "course_name": sec.get("course_name") or "",
                "orig_day": sec.get("day") or "",
                "orig_time": sec.get("time") or "",
                "new_day": day,
                "new_time": ts,
                "move_cost": float(params.move_cost) * (1.5 if day != (sec.get("day") or "").strip() else 1.0),
            }
        )
    return moves
