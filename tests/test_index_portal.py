"""Tests for index Excel parse helpers."""
import io

import pandas as pd
import pytest

from backend.services.index_portal import _map_columns, _records_from_excel


def test_map_columns_students_arabic_headers():
    df = pd.DataFrame([{"الرقم الدراسي": "1200", "اسم الطالب": "أحمد"}])
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
    out = _map_columns(df, "students")
    assert list(out.columns) == ["student_id", "student_name"]
    assert out.iloc[0]["student_id"] == "1200"


def test_records_from_excel_students():
    buf = io.BytesIO()
    pd.DataFrame(
        [{"student_id": "99", "student_name": "Test"}],
    ).to_excel(buf, index=False)
    buf.seek(0)
    rows = _records_from_excel(buf, "students")
    assert len(rows) == 1
    assert rows[0]["student_id"] == "99"
