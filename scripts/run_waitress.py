"""
تشغيل التطبيق عبر Waitress (مناسب لويندوز بدلاً من خادم Flask التجريبي).

  pip install waitress
  python scripts/run_waitress.py

ثم افتح http://127.0.0.1:5000
للإنتاج: ضع خلف reverse proxy (IIS/nginx) وعطّل debug في الإعدادات.
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("FLASK_DEBUG", "0")

try:
    from waitress import serve
except ImportError:
    print("ثبّت waitress: pip install waitress", file=sys.stderr)
    sys.exit(1)

from app import app  # noqa: E402


def main() -> None:
    host = os.environ.get("WAITRESS_HOST", "0.0.0.0")
    port = int(os.environ.get("WAITRESS_PORT", "5000"))
    threads = int(os.environ.get("WAITRESS_THREADS", "4"))
    serve(app, host=host, port=port, threads=threads)


if __name__ == "__main__":
    main()
