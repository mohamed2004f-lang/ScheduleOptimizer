"""فحص سريع لإعدادات الأمان قبل/بعد تشغيل الإنتاج.

الاستخدام من جذر المشروع:
  python scripts/check_prod_security.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    env_path = ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=True)
except ImportError:
    pass


def _ok(msg: str) -> None:
    print(f"[OK] {msg}")


def _bad(msg: str) -> None:
    print(f"[FAIL] {msg}")


def main() -> int:
    fails = 0
    flask_env = (os.environ.get("FLASK_ENV") or "development").strip().lower()
    print(f"FLASK_ENV={flask_env}")

    secret = (os.environ.get("SECRET_KEY") or "").strip()
    if len(secret) >= 32:
        _ok(f"SECRET_KEY length={len(secret)}")
    else:
        fails += 1
        _bad("SECRET_KEY قصير أو فارغ (يلزم ≥ 32 في الإنتاج)")

    admin_pw = os.environ.get("ADMIN_PASSWORD") or ""
    try:
        from backend.core.password_policy import validate_new_password

        ok, err = validate_new_password(admin_pw)
    except Exception as exc:
        ok, err = False, str(exc)
    if ok:
        _ok("ADMIN_PASSWORD يستوفي السياسة")
    else:
        fails += 1
        _bad(f"ADMIN_PASSWORD: {err}")

    redis_url = (
        (os.environ.get("CACHE_REDIS_URL") or os.environ.get("REDIS_URL") or "")
        .strip()
    )
    in_docker = os.path.exists("/.dockerenv")
    if redis_url:
        _ok(f"Redis URL مضبوط ({redis_url.split('@')[-1] if '@' in redis_url else redis_url})")
    elif in_docker and flask_env == "production":
        fails += 1
        _bad("CACHE_REDIS_URL/REDIS_URL غير مضبوط داخل حاوية الإنتاج")
    else:
        print(
            "[WARN] Redis غير في .env — Docker Compose يحقن redis://redis:6379/0 تلقائياً. "
            "يُفضّل إضافة CACHE_REDIS_URL=redis://redis:6379/0 إلى .env للتوضيح."
        )

    pg = (os.environ.get("POSTGRES_PASSWORD") or "").strip()
    if pg:
        _ok("POSTGRES_PASSWORD مضبوط")
    else:
        print("[WARN] POSTGRES_PASSWORD فارغ — مطلوب لـ docker compose")

    mirror = (os.environ.get("BACKUP_MIRROR_ROOT") or "").strip()
    if mirror:
        _ok(f"BACKUP_MIRROR_ROOT={mirror}")
    else:
        print("[WARN] BACKUP_MIRROR_ROOT غير مضبوط — الافتراضي D:\\ScheduleOptimizer_Backups")

    if fails:
        print(f"\nالنتيجة: {fails} مشكلة/مشاكل — صحّح .env قبل الاعتماد على الإنتاج.")
        return 1
    print("\nالنتيجة: فحوصات الأمان الأساسية ناجحة.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
