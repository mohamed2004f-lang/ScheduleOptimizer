"""سياسة كلمة المرور — حد أدنى موحّد لتعيين/تغيير الكلمة."""
from __future__ import annotations

import os
from typing import Optional, Tuple


def min_password_length() -> int:
    try:
        n = int(os.environ.get("PASSWORD_MIN_LENGTH", "8"))
    except ValueError:
        n = 8
    return max(8, min(n, 64))


def validate_new_password(
    password: str,
    *,
    current: Optional[str] = None,
    confirm: Optional[str] = None,
) -> Tuple[bool, Optional[str]]:
    """
    Returns (ok, error_message).
    """
    pw = password if isinstance(password, str) else ""
    if not pw or not pw.strip() or pw != pw.strip():
        return False, "كلمة المرور غير صالحة"
    min_len = min_password_length()
    if len(pw) < min_len:
        return False, f"كلمة المرور يجب ألا تقل عن {min_len} أحرف"
    if len(pw) > 128:
        return False, "كلمة المرور طويلة جداً"
    has_letter = any(ch.isalpha() for ch in pw)
    has_digit = any(ch.isdigit() for ch in pw)
    if not (has_letter and has_digit):
        return False, "كلمة المرور يجب أن تحتوي على حرف ورقم على الأقل"
    if current is not None and pw == current:
        return False, "كلمة المرور الجديدة يجب أن تختلف عن الحالية"
    if confirm is not None and confirm != "" and confirm != pw:
        return False, "كلمتا المرور غير متطابقتين"
    return True, None
