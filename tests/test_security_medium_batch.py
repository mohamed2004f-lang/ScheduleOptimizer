"""اختبارات إصلاحات الأمان متوسطة الخطورة (فلتر HOD، هاتف، Fernet)."""
from backend.services.survey_analytics import _course_eval_dept_filter
from backend.services.survey_invites import (
    _phone_hash,
    _phone_hash_legacy,
    _phone_hash_matches,
    _normalize_phone_digits,
)


def test_course_eval_dept_filter_omits_instructor_home(db_conn):
    sql, params = _course_eval_dept_filter(db_conn, 1)
    assert "instructors" not in sql.lower()
    assert "teaching_groups" in sql.lower() or "schedule" in sql.lower()
    assert params
    assert all(p == 1 for p in params)


def test_phone_hash_uses_pepper_and_matches_legacy():
    phone = "+218-91-234-5678"
    norm = _normalize_phone_digits(phone)
    current = _phone_hash(phone)
    legacy = _phone_hash_legacy(norm)
    assert current
    assert legacy
    assert current != legacy
    assert _phone_hash_matches(current, phone)
    assert _phone_hash_matches(legacy, phone)
    assert not _phone_hash_matches(current, "999999999")
