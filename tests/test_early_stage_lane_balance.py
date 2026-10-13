"""توازن مساري الكتلة الأولى في مصفوفة المراحل (منطق مطابق لـ schedule-stage-grid.js)."""

from __future__ import annotations


def early_lane_from_group_code(code: str | None) -> int | None:
    c = (code or "").strip().upper()
    if not c or not c[0].isalpha() or not ("A" <= c[0] <= "Z"):
        return None
    idx = ord(c[0]) - 64
    return ((idx - 1) % 2) + 1


def balance_early_stage_lanes(courses: list[dict]) -> dict[int, list[dict]]:
    lanes: dict[int, list[dict]] = {1: [], 2: []}
    rest: list[dict] = []
    for row in courses:
        hint = early_lane_from_group_code(str(row.get("group_code") or ""))
        if hint in (1, 2):
            lanes[hint].append(row)
        else:
            rest.append(row)
    for row in rest:
        lane = 1 if len(lanes[1]) <= len(lanes[2]) else 2
        lanes[lane].append(row)
    return lanes


def test_early_lane_letter_mapping():
    assert early_lane_from_group_code("A") == 1
    assert early_lane_from_group_code("B") == 2
    assert early_lane_from_group_code("A1") == 1
    assert early_lane_from_group_code("B2") == 2
    assert early_lane_from_group_code("C") == 1
    assert early_lane_from_group_code("") is None
    assert early_lane_from_group_code("—") is None


def test_balance_pins_ab_and_fills_least_load():
    lanes = balance_early_stage_lanes(
        [
            {"course_name": "gA", "group_code": "A"},
            {"course_name": "gB", "group_code": "B"},
            {"course_name": "d1", "group_code": ""},
            {"course_name": "d2", "group_code": ""},
        ]
    )
    assert [r["course_name"] for r in lanes[1]] == ["gA", "d1"]
    assert [r["course_name"] for r in lanes[2]] == ["gB", "d2"]


def test_balance_untagged_goes_to_lighter_lane():
    lanes = balance_early_stage_lanes(
        [
            {"course_name": "gA", "group_code": "A"},
            {"course_name": "gA2", "group_code": "A2"},
            {"course_name": "dept", "group_code": ""},
        ]
    )
    assert len(lanes[1]) == 2
    assert len(lanes[2]) == 1
    assert lanes[2][0]["course_name"] == "dept"
