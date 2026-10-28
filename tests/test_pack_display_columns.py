"""توزيع أعمدة التعبئة: عام أولاً ثم أقل رمز → الأقل ازدحاماً."""

from backend.core.schedule_stage_layout import (
    PACK_COL_1,
    PACK_COL_2,
    PACK_COL_3,
    assign_pack_display_columns,
    course_pack_sort_key,
)


def test_sort_general_before_dept_and_lower_code_first():
    rows = [
        {"course_name": "C", "course_code": "ME 401", "is_college_general": False},
        {"course_name": "A", "course_code": "GS 101", "is_college_general": True},
        {"course_name": "B", "course_code": "ME 205", "is_college_general": False},
    ]
    ordered = sorted(rows, key=course_pack_sort_key)
    assert [r["course_name"] for r in ordered] == ["A", "B", "C"]


def test_pack_balances_across_three_columns():
    rows = [
        {"course_name": "g1", "course_code": "GS 101", "is_college_general": True},
        {"course_name": "a", "course_code": "ME 201", "is_college_general": False},
        {"course_name": "b", "course_code": "ME 301", "is_college_general": False},
        {"course_name": "c", "course_code": "ME 401", "is_college_general": False},
        {"course_name": "d", "course_code": "ME 501", "is_college_general": False},
    ]
    packed = assign_pack_display_columns(rows)
    assert set(packed.keys()) == {PACK_COL_1, PACK_COL_2, PACK_COL_3}
    lengths = [len(packed[PACK_COL_1]), len(packed[PACK_COL_2]), len(packed[PACK_COL_3])]
    assert max(lengths) - min(lengths) <= 1
    assert sum(lengths) == 5
    # العام يُعيَّن أولاً → العمود 1
    assert packed[PACK_COL_1][0]["course_name"] == "g1"


def test_pack_prefers_lower_column_on_tie():
    rows = [
        {"course_name": "x", "course_code": "ME 101", "is_college_general": False},
    ]
    packed = assign_pack_display_columns(rows)
    assert len(packed[PACK_COL_1]) == 1
    assert packed[PACK_COL_2] == []
    assert packed[PACK_COL_3] == []
