"""توليد PDF عبر Chromium (جودة عربية أفضل من wkhtmltopdf)."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

_CHROMIUM_CANDIDATES = (
    "CHROMIUM_PATH",
    "GOOGLE_CHROME_BIN",
)


def find_chromium_executable() -> str | None:
    """مسار Chromium/Chrome المتاح في النظام."""
    for env_key in _CHROMIUM_CANDIDATES:
        path = (os.environ.get(env_key) or "").strip()
        if path and Path(path).is_file():
            return path
    for name in (
        "chromium",
        "chromium-browser",
        "google-chrome",
        "google-chrome-stable",
        "chrome",
    ):
        found = shutil.which(name)
        if found:
            return found
    # مسارات شائعة داخل Docker/Debian
    for path in (
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
    ):
        if Path(path).is_file():
            return path
    return None


def chromium_pdf_available() -> tuple[bool, str]:
    exe = find_chromium_executable()
    if not exe:
        return False, "Chromium غير مثبت"
    return True, exe


def pdf_bytes_from_html_chromium(
    html: str,
    *,
    timeout_sec: int = 120,
) -> tuple[bytes | None, str | None]:
    """
    طباعة HTML إلى PDF عبر Chromium headless.
    يعتمد على @page في CSS للهوامش — نفس محرك المعاينة تقريباً.
    """
    ok, info = chromium_pdf_available()
    if not ok:
        return None, info
    chromium = info
    html_doc = html or ""
    # تأكد من charset
    if "<meta charset" not in html_doc.lower():
        html_doc = html_doc.replace(
            "<head>",
            '<head>\n  <meta charset="utf-8">',
            1,
        )
    try:
        with tempfile.TemporaryDirectory(prefix="so_pdf_") as tmp:
            html_path = Path(tmp) / "report.html"
            pdf_path = Path(tmp) / "report.pdf"
            html_path.write_text(html_doc, encoding="utf-8")
            # file:// URI بصيغة يفهمها Chromium على Linux/Windows
            file_url = html_path.resolve().as_uri()
            cmd = [
                chromium,
                "--headless=new",
                "--disable-gpu",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-software-rasterizer",
                "--font-render-hinting=medium",
                "--run-all-compositor-stages-before-draw",
                "--virtual-time-budget=8000",
                "--no-pdf-header-footer",
                f"--print-to-pdf={pdf_path}",
                file_url,
            ]
            proc = subprocess.run(
                cmd,
                capture_output=True,
                timeout=timeout_sec,
                check=False,
            )
            if proc.returncode != 0 or not pdf_path.is_file():
                err = (proc.stderr or proc.stdout or b"").decode("utf-8", errors="replace")
                logger.warning("chromium pdf failed rc=%s err=%s", proc.returncode, err[:500])
                return None, f"فشل Chromium PDF: {err[:300] or proc.returncode}"
            raw = pdf_path.read_bytes()
            if not raw.startswith(b"%PDF"):
                return None, "ملف PDF غير صالح من Chromium"
            return raw, None
    except subprocess.TimeoutExpired:
        return None, "انتهت مهلة توليد PDF عبر Chromium"
    except Exception as exc:
        logger.exception("chromium pdf error")
        return None, f"فشل توليد PDF عبر Chromium: {exc}"
