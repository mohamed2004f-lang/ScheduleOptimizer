"""Tests for Chromium PDF helper (no real browser required)."""

from __future__ import annotations

from unittest.mock import patch

from backend.core.chromium_pdf import chromium_pdf_available, find_chromium_executable, pdf_bytes_from_html_chromium


def test_find_chromium_respects_env(tmp_path, monkeypatch):
    fake = tmp_path / "chromium"
    fake.write_text("", encoding="utf-8")
    monkeypatch.setenv("CHROMIUM_PATH", str(fake))
    assert find_chromium_executable() == str(fake)


def test_chromium_unavailable_message(monkeypatch):
    monkeypatch.delenv("CHROMIUM_PATH", raising=False)
    monkeypatch.delenv("GOOGLE_CHROME_BIN", raising=False)
    with patch("backend.core.chromium_pdf.shutil.which", return_value=None), patch(
        "backend.core.chromium_pdf.Path.is_file", return_value=False
    ):
        ok, msg = chromium_pdf_available()
        assert ok is False
        assert "Chromium" in msg


def test_pdf_bytes_rejects_non_pdf(tmp_path, monkeypatch):
    fake = tmp_path / "chromium"
    fake.write_text("", encoding="utf-8")
    monkeypatch.setenv("CHROMIUM_PATH", str(fake))

    class FakeProc:
        returncode = 0
        stdout = b""
        stderr = b""

    def fake_run(cmd, **kwargs):
        # write a non-PDF file where --print-to-pdf points
        out = None
        for part in cmd:
            if isinstance(part, str) and part.startswith("--print-to-pdf="):
                out = part.split("=", 1)[1]
        if out:
            Path = __import__("pathlib").Path
            Path(out).write_bytes(b"NOTPDF")
        return FakeProc()

    with patch("backend.core.chromium_pdf.subprocess.run", side_effect=fake_run):
        raw, err = pdf_bytes_from_html_chromium("<html><body>hi</body></html>")
        assert raw is None
        assert err and "غير صالح" in err
