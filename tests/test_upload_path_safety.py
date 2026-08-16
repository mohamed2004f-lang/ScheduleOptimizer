"""اختبارات حصر تنزيل الملفات داخل backend/uploads."""
from __future__ import annotations

from backend.core.security import resolve_safe_upload_path, uploads_root


def test_uploads_root_is_backend_uploads():
    root = uploads_root()
    assert root.name == "uploads"
    assert root.parent.name == "backend"


def test_rejects_empty_and_missing():
    assert resolve_safe_upload_path(None) is None
    assert resolve_safe_upload_path("") is None
    assert resolve_safe_upload_path("   ") is None
    missing = uploads_root() / "_wk1_does_not_exist.bin"
    assert resolve_safe_upload_path(str(missing)) is None


def test_accepts_file_under_uploads():
    root = uploads_root()
    root.mkdir(parents=True, exist_ok=True)
    target = root / "_wk1_safe_download.bin"
    target.write_bytes(b"ok")
    try:
        got = resolve_safe_upload_path(str(target))
        assert got is not None
        assert got.resolve() == target.resolve()
    finally:
        target.unlink(missing_ok=True)


def test_rejects_file_outside_uploads(tmp_path):
    outside = tmp_path / "secret.txt"
    outside.write_text("nope", encoding="utf-8")
    assert resolve_safe_upload_path(str(outside)) is None


def test_rejects_traversal_to_source_tree():
    traversal = str(uploads_root() / ".." / "core" / "auth.py")
    assert resolve_safe_upload_path(traversal) is None


def test_allowed_root_confines_to_subdir():
    root = uploads_root()
    a = root / "_wk1_root_a"
    b = root / "_wk1_root_b"
    a.mkdir(parents=True, exist_ok=True)
    b.mkdir(parents=True, exist_ok=True)
    target = a / "x.bin"
    target.write_bytes(b"x")
    try:
        assert resolve_safe_upload_path(str(target), allowed_root=str(a)) is not None
        assert resolve_safe_upload_path(str(target), allowed_root=str(b)) is None
    finally:
        target.unlink(missing_ok=True)
        try:
            a.rmdir()
        except OSError:
            pass
        try:
            b.rmdir()
        except OSError:
            pass
