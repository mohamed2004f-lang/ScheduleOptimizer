"""تصدير Excel بمصفوفة المراحل (نفس شبكة الطباعة)."""

from __future__ import annotations

from backend.services.schedule import (
    _build_stage_matrix_excel_bytes,
    _excel_cell_join,
    _excel_course_label,
)


def test_excel_course_label_includes_group_code():
    assert _excel_course_label({"course_name": "فيزياء I", "group_code": "A"}) == "فيزياء I (A)"
    assert _excel_course_label({"course_name": "فيزياء I", "group_code": "—"}) == "فيزياء I"


def test_excel_cell_join_separator():
    assert _excel_cell_join([]) == "—"
    assert "-----" in _excel_cell_join(["أ", "ب"])


def test_stage_matrix_excel_bytes_nonempty():
    rows = [
        {
            "course_name": "فيزياء I",
            "day": "السبت",
            "time": "09:00-12:00",
            "room": "1",
            "instructor": "أ. اختبار",
            "group_code": "A",
            "stage_bucket": "general_or_y1",
        },
        {
            "course_name": "تصميم آلات",
            "day": "السبت",
            "time": "09:00-12:00",
            "room": "2",
            "instructor": "د. اختبار",
            "group_code": "—",
            "stage_bucket": "y3",
        },
    ]
    data = _build_stage_matrix_excel_bytes(
        rows, department_name="الهندسة الميكانيكية", term_label="خريف 2026/2027"
    )
    assert isinstance(data, (bytes, bytearray))
    assert len(data) > 1000
    assert data[:2] == b"PK"  # zip/xlsx
