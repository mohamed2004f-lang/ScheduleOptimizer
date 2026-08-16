"""تشفير كلمات المرور والتحقق منها."""
from __future__ import annotations

import hashlib

try:
    from werkzeug.security import check_password_hash, generate_password_hash
except Exception:  # pragma: no cover
    generate_password_hash = None
    check_password_hash = None

_LEGACY_SALT = "schedule_optimizer_salt_2024"


def hash_password(password: str) -> str:
    """تشفير كلمة المرور (Werkzeug إذا توفر، وإلا SHA-256 القديم مع salt)."""
    if generate_password_hash is not None:
        return generate_password_hash(password)
    return hashlib.sha256(f"{_LEGACY_SALT}{password}".encode()).hexdigest()


def verify_password(password: str, hashed: str) -> bool:
    """التحقق من كلمة المرور (يدعم الهاش الجديد + القديم)."""
    if not hashed:
        return False
    if (hashed.startswith("pbkdf2:") or hashed.startswith("scrypt:")) and check_password_hash is not None:
        return check_password_hash(hashed, password)
    old_hash = hashlib.sha256(f"{_LEGACY_SALT}{password}".encode()).hexdigest()
    return old_hash == hashed
