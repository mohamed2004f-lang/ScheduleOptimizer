"""
نسخ احتياطي لقاعدة PostgreSQL باستخدام pg_dump و DATABASE_URL من config (.env).

يتطلب: ثنائي pg_dump في PATH (مجلد bin لتثبيت PostgreSQL على ويندوز).

الاستخدام من جذر المشروع:
  python scripts/pg_dump_via_env.py
  python scripts/pg_dump_via_env.py --format plain --out backups/manual_dump.sql
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from sqlalchemy.engine.url import make_url
except ImportError:
    print("تثبيت SQLAlchemy مطلوب.", file=sys.stderr)
    sys.exit(1)

from config import DATABASE_URL  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--format",
        choices=("custom", "plain"),
        default="custom",
        help="custom = ملف .dump (pg_restore)؛ plain = SQL نصي",
    )
    ap.add_argument("--out", type=Path, default=None, help="مسار الملف الناتج")
    args = ap.parse_args()

    u = make_url(DATABASE_URL or "")
    if u.get_backend_name() != "postgresql":
        print("DATABASE_URL يجب أن يشير إلى PostgreSQL.", file=sys.stderr)
        return 1

    host = u.host or "localhost"
    port = int(u.port or 5432)
    user = u.username or "postgres"
    db = u.database or ""
    password = u.password or ""

    out_dir = ROOT / "backups" / "pg_dump"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if args.out:
        out = args.out.resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
    elif args.format == "custom":
        out = out_dir / f"{stamp}_{db}.dump"
    else:
        out = out_dir / f"{stamp}_{db}.sql"

    env = os.environ.copy()
    if password:
        env["PGPASSWORD"] = password

    fmt = ["-F", "c"] if args.format == "custom" else ["-F", "p"]
    cmd = [
        "pg_dump",
        "-h",
        host,
        "-p",
        str(port),
        "-U",
        user,
        "-d",
        db,
        *fmt,
        "-f",
        str(out),
    ]
    try:
        subprocess.run(cmd, env=env, check=True)
    except FileNotFoundError:
        print(
            "لم يُعثر على pg_dump. أضف مجلد bin الخاص بـ PostgreSQL إلى PATH.",
            file=sys.stderr,
        )
        return 1
    except subprocess.CalledProcessError as e:
        return int(e.returncode or 1)

    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
