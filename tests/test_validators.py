"""اختبارات التحقق من المدخلات."""
from backend.core.validators import (
    validate_grade,
    validate_optimize_params,
    validate_schedule_row_dict,
    validate_student_id,
    validate_time_slot,
)


class TestValidators:
    def test_student_id(self):
        assert validate_student_id("20201234")[0] is True
        assert validate_student_id("")[0] is False

    def test_time_slot(self):
        assert validate_time_slot("09:00-11:00")[0] is True
        assert validate_time_slot("bad")[0] is False

    def test_grade(self):
        assert validate_grade(85)[0] is True
        assert validate_grade(150)[0] is False
        assert validate_grade(None)[0] is True

    def test_schedule_row(self):
        ok, _ = validate_schedule_row_dict(
            {"course_name": "ميكانيكا", "day": "السبت", "time": "09:00-11:00"}
        )
        assert ok is True

    def test_optimize_params(self):
        ok, _, cleaned = validate_optimize_params(
            {"max_alternatives_per_section": 3, "move_cost": 1.5}
        )
        assert ok is True
        assert cleaned["max_alternatives_per_section"] == 3
