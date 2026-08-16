"""سياسة كلمة المرور وقفل الدخول."""
from backend.core.auth_throttle import (
    is_locked,
    record_login_failure,
    record_login_success,
    reset_throttle_state,
)
from backend.core.password_policy import min_password_length, validate_new_password


def setup_function():
    reset_throttle_state()


def test_password_too_short():
    ok, err = validate_new_password("short")
    assert ok is False
    assert str(min_password_length()) in (err or "")


def test_password_must_differ_from_current():
    ok, err = validate_new_password("SameP@ss1", current="SameP@ss1")
    assert ok is False
    assert "تختلف" in (err or "")


def test_password_confirm_mismatch():
    ok, err = validate_new_password("ValidP@ss1", confirm="other")
    assert ok is False


def test_password_ok():
    ok, err = validate_new_password("ValidP@ss1", current="OldP@ss1", confirm="ValidP@ss1")
    assert ok is True
    assert err is None


def test_password_requires_letter_and_digit():
    ok, err = validate_new_password("OnlyLettersHere")
    assert ok is False
    assert "حرف" in (err or "") or "رقم" in (err or "")
    ok, err = validate_new_password("12345678")
    assert ok is False


def test_lockout_after_max_failures(monkeypatch):
    monkeypatch.setenv("LOGIN_LOCKOUT_MAX", "3")
    monkeypatch.setenv("LOGIN_LOCKOUT_SECONDS", "120")
    reset_throttle_state()
    user = "brute-target"
    assert is_locked(user)[0] is False
    assert record_login_failure(user)[0] is False
    assert record_login_failure(user)[0] is False
    locked, retry = record_login_failure(user)
    assert locked is True
    assert retry > 0
    assert is_locked(user)[0] is True
    assert is_locked("BRUTE-TARGET")[0] is True


def test_success_clears_lockout(monkeypatch):
    monkeypatch.setenv("LOGIN_LOCKOUT_MAX", "3")
    monkeypatch.setenv("LOGIN_LOCKOUT_SECONDS", "120")
    reset_throttle_state()
    user = "clear-me"
    record_login_failure(user)
    record_login_failure(user)
    record_login_failure(user)
    assert is_locked(user)[0] is True
    record_login_success(user)
    assert is_locked(user)[0] is False


def test_unknown_names_share_lock_bucket(monkeypatch):
    monkeypatch.setenv("LOGIN_LOCKOUT_MAX", "3")
    monkeypatch.setenv("LOGIN_LOCKOUT_SECONDS", "120")
    reset_throttle_state()
    record_login_failure("NoSuchUser")
    record_login_failure("nosuchuser")
    locked, _ = record_login_failure("NOSUCHUSER")
    assert locked is True
