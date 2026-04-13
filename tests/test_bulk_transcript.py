"""
اختبارات وحدة لدالة _load_all_transcripts_bulk الجديدة في grades.py.

تتحقق من:
- جلب بيانات الدرجات لعدة طلاب دفعة واحدة.
- تطابق النتائج مع _load_transcript_data لطالب واحد.
- التعامل مع قائمة فارغة وطالب غير موجود.
- حساب المعدل التراكمي والوحدات المنجزة بشكل صحيح.
"""
import pytest


class TestLoadAllTranscriptsBulk:
    """اختبارات دالة _load_all_transcripts_bulk."""

    def test_bulk_returns_dict(self, db_conn):
        """يجب أن ترجع dict."""
        from backend.services.grades import _load_all_transcripts_bulk
        result = _load_all_transcripts_bulk()
        assert isinstance(result, dict)

    def test_bulk_contains_seeded_students(self, db_conn):
        """يجب أن تحتوي على الطلاب المضافين في البيانات التجريبية."""
        from backend.services.grades import _load_all_transcripts_bulk
        result = _load_all_transcripts_bulk(["S001", "S002"])
        assert "S001" in result
        assert "S002" in result

    def test_bulk_student_has_expected_keys(self, db_conn):
        """يجب أن يحتوي كل طالب على المفاتيح المتوقعة."""
        from backend.services.grades import _load_all_transcripts_bulk
        result = _load_all_transcripts_bulk(["S001"])
        s = result["S001"]
        expected_keys = {
            "student_id",
            "student_name",
            "graduation_plan",
            "join_term",
            "join_year",
            "transcript",
            "ordered_semesters",
            "semester_gpas",
            "semester_completed_units",
            "cumulative_gpa",
            "completed_units",
        }
        assert expected_keys.issubset(set(s.keys()))

    def test_bulk_gpa_calculation(self, db_conn):
        """يجب أن يحسب المعدل التراكمي بشكل صحيح."""
        from backend.services.grades import _load_all_transcripts_bulk
        result = _load_all_transcripts_bulk(["S001"])
        s = result["S001"]
        # S001 has: رياضيات 1 (3 units, 85) + فيزياء 1 (3 units, 70)
        # GPA = (85*3 + 70*3) / (3+3) = 465/6 = 77.5
        assert abs(s["cumulative_gpa"] - 77.5) < 0.01

    def test_bulk_completed_units(self, db_conn):
        """يجب أن يحسب الوحدات المنجزة بشكل صحيح."""
        from backend.services.grades import _load_all_transcripts_bulk
        result = _load_all_transcripts_bulk(["S001"])
        s = result["S001"]
        # S001: both courses passed (85 >= 50, 70 >= 50), total 6 units
        assert s["completed_units"] == 6

    def test_bulk_failed_student_completed_units(self, db_conn):
        """الطالب الراسب يجب ألا تُحسب وحداته الراسبة."""
        from backend.services.grades import _load_all_transcripts_bulk
        result = _load_all_transcripts_bulk(["S002"])
        s = result["S002"]
        # S002: رياضيات 1 (grade=40 < 50, failed) + كيمياء 1 (grade=90, passed 2 units)
        assert s["completed_units"] == 2

    def test_bulk_empty_list(self, db_conn):
        """قائمة فارغة يجب أن ترجع dict فارغ."""
        from backend.services.grades import _load_all_transcripts_bulk
        result = _load_all_transcripts_bulk([])
        assert result == {}

    def test_bulk_nonexistent_student(self, db_conn):
        """طالب غير موجود يجب ألا يظهر في النتائج."""
        from backend.services.grades import _load_all_transcripts_bulk
        result = _load_all_transcripts_bulk(["NONEXISTENT"])
        assert "NONEXISTENT" not in result

    def test_bulk_matches_single_load(self, db_conn):
        """
        نتائج bulk يجب أن تتطابق مع _load_transcript_data لنفس الطالب
        في المفاتيح الأساسية (cumulative_gpa, completed_units, ordered_semesters).
        """
        from backend.services.grades import _load_all_transcripts_bulk, _load_transcript_data
        bulk = _load_all_transcripts_bulk(["S001"])
        single = _load_transcript_data("S001")

        assert bulk["S001"]["cumulative_gpa"] == single["cumulative_gpa"]
        assert bulk["S001"]["completed_units"] == single["completed_units"]
        assert bulk["S001"]["ordered_semesters"] == single["ordered_semesters"]

    def test_bulk_semester_gpas(self, db_conn):
        """يجب أن تحتوي semester_gpas على الفصول الصحيحة."""
        from backend.services.grades import _load_all_transcripts_bulk
        result = _load_all_transcripts_bulk(["S001"])
        s = result["S001"]
        assert "خريف 44-45" in s["semester_gpas"]

    def test_bulk_all_students_no_filter(self, db_conn):
        """استدعاء بدون تحديد student_ids يجب أن يرجع جميع الطلاب."""
        from backend.services.grades import _load_all_transcripts_bulk
        result = _load_all_transcripts_bulk()
        # At least the 2 seeded students
        assert len(result) >= 2
