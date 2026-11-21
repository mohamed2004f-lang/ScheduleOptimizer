"""توزيع أعمدة التعبئة: مرحلة مفضّلة + RR يومي + تفريغ الصف."""

from backend.core.schedule_stage_layout import (
    PACK_COL_1,
    PACK_COL_2,
    PACK_COL_3,
    assign_pack_display_columns,
    build_sticky_pack_map,
    course_pack_identity,
    manual_pack_prefer_index,
    stage_pack_prefer_index,
    sticky_pack_lookup_key,
)


def test_stage_prefer_index_mapping():
    assert stage_pack_prefer_index({"course_code": "GS 101", "is_college_general": True}) == 1
    assert stage_pack_prefer_index({"course_code": "ME 101", "is_college_general": False}) == 1
    assert stage_pack_prefer_index({"course_code": "ME 201", "is_college_general": False}) == 2
    assert stage_pack_prefer_index({"course_code": "ME 301", "is_college_general": False}) == 2
    assert stage_pack_prefer_index({"course_code": "ME 401", "is_college_general": False}) == 3
    assert stage_pack_prefer_index({"course_code": "ME 501", "is_college_general": False}) == 3


def test_alone_in_slot_uses_stage_column():
    packed = assign_pack_display_columns(
        [{"course_name": "x", "course_code": "ME 501", "is_college_general": False}]
    )
    assert packed[PACK_COL_3][0]["course_name"] == "x"
    assert packed[PACK_COL_1] == []
    assert packed[PACK_COL_2] == []


def test_same_stage_day_round_robin_spreads_columns():
    """عدة مقررات مرحلة 1 في أوقات مختلفة لنفس اليوم لا تتكدس كلها في العمود 1."""
    rows = [
        {"course_name": "A", "course_code": "ME 101", "day": "السبت", "time": "09:00-11:00"},
        {"course_name": "B", "course_code": "ME 102", "day": "السبت", "time": "11:00-13:00"},
        {"course_name": "C", "course_code": "ME 103", "day": "السبت", "time": "13:00-15:00"},
    ]
    sticky = build_sticky_pack_map(rows)
    assert sticky[sticky_pack_lookup_key("السبت", rows[0])] == PACK_COL_1
    assert sticky[sticky_pack_lookup_key("السبت", rows[1])] == PACK_COL_2
    assert sticky[sticky_pack_lookup_key("السبت", rows[2])] == PACK_COL_3

    p0 = assign_pack_display_columns([rows[0]], sticky_map=sticky, day="السبت")
    p1 = assign_pack_display_columns([rows[1]], sticky_map=sticky, day="السبت")
    p2 = assign_pack_display_columns([rows[2]], sticky_map=sticky, day="السبت")
    assert p0[PACK_COL_1][0]["course_name"] == "A"
    assert p1[PACK_COL_2][0]["course_name"] == "B"
    assert p2[PACK_COL_3][0]["course_name"] == "C"


def test_same_slot_spill_when_preferred_taken():
    """مقرران بنفس الوقت ونفس المرحلة: الأول بالمفضّل والثاني يُفرَّغ."""
    rows = [
        {"course_name": "A", "course_code": "ME 101", "day": "الثلاثاء"},
        {"course_name": "B", "course_code": "ME 102", "day": "الثلاثاء"},
    ]
    sticky = build_sticky_pack_map(rows)
    # RR يومي: A→1 ، B→2 — لا تعارض أصلاً
    packed = assign_pack_display_columns(rows, sticky_map=sticky, day="الثلاثاء")
    assert len(packed[PACK_COL_1]) == 1
    assert len(packed[PACK_COL_2]) == 1
    assert packed[PACK_COL_3] == []


def test_concurrent_different_stages_use_preferred():
    rows = [
        {"course_name": "g", "course_code": "GS 101", "is_college_general": True, "day": "الأحد"},
        {"course_name": "y3", "course_code": "ME 301", "is_college_general": False, "day": "الأحد"},
        {"course_name": "y5", "course_code": "ME 501", "is_college_general": False, "day": "الأحد"},
    ]
    sticky = build_sticky_pack_map(rows)
    packed = assign_pack_display_columns(rows, sticky_map=sticky, day="الأحد")
    assert packed[PACK_COL_1][0]["course_name"] == "g"
    assert packed[PACK_COL_2][0]["course_name"] == "y3"
    assert packed[PACK_COL_3][0]["course_name"] == "y5"


def test_course_sticky_within_day_across_times():
    rows = [
        {"course_name": "A", "course_code": "ME 101", "day": "السبت", "time": "09:00-11:00"},
        {"course_name": "A", "course_code": "ME 101", "day": "السبت", "time": "12:00-14:00"},
        {"course_name": "B", "course_code": "ME 102", "day": "السبت", "time": "11:00-13:00"},
    ]
    sticky = build_sticky_pack_map(rows)
    kid_a = course_pack_identity(rows[0])
    assert sticky[f"السبت|{kid_a}"] == PACK_COL_1
    p_morning = assign_pack_display_columns([rows[0]], sticky_map=sticky, day="السبت")
    p_afternoon = assign_pack_display_columns([rows[1]], sticky_map=sticky, day="السبت")
    assert p_morning[PACK_COL_1][0]["course_name"] == "A"
    assert p_afternoon[PACK_COL_1][0]["course_name"] == "A"


def test_manual_pack_column_overrides_stage():
    """تجاوز يدوي: مرحلة 1 تُثبَّت في العمود 3 إن اختير يدوياً."""
    row = {
        "course_name": "A",
        "course_code": "ME 101",
        "day": "الأحد",
        "pack_display_column": 3,
    }
    assert manual_pack_prefer_index(row) == 3
    sticky = build_sticky_pack_map([row])
    assert sticky[sticky_pack_lookup_key("الأحد", row)] == PACK_COL_3
    packed = assign_pack_display_columns([row], sticky_map=sticky, day="الأحد")
    assert packed[PACK_COL_3][0]["course_name"] == "A"
    assert packed[PACK_COL_1] == []


def test_manual_wins_before_auto_in_same_slot():
    rows = [
        {
            "course_name": "auto",
            "course_code": "ME 101",
            "day": "الإثنين",
            "is_college_general": False,
        },
        {
            "course_name": "manual",
            "course_code": "ME 501",
            "day": "الإثنين",
            "pack_display_column": 1,
        },
    ]
    sticky = build_sticky_pack_map(rows)
    packed = assign_pack_display_columns(rows, sticky_map=sticky, day="الإثنين")
    assert packed[PACK_COL_1][0]["course_name"] == "manual"
    # الآلي مرحلة 1 يُفرَّغ للعمود 2 لأن 1 مشغول باليدوي
    assert packed[PACK_COL_2][0]["course_name"] == "auto"
