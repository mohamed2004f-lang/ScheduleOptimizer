"""اختبارات النسخ الاحتياطي من الواجهة."""

from __future__ import annotations

from backend.services.backup_jobs import backup_status, run_full_backup


def test_backup_status_shape():
    s = backup_status()
    assert "mirror_root" in s
    assert "local_latest_dump" in s
    assert "mirror_latest_dump" in s
    assert "retention_days" in s


def test_run_full_backup_skip_dump(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKUP_MIRROR_ROOT", str(tmp_path))
    monkeypatch.setenv("BACKUP_RETENTION_DAYS", "30")
    pg_local = tmp_path / "proj" / "backups" / "pg_dump"
    pg_local.mkdir(parents=True)
    dump = pg_local / "test_manual.dump"
    dump.write_bytes(b"fake")
    uploads = tmp_path / "proj" / "backend" / "uploads"
    uploads.mkdir(parents=True)
    (uploads / "a.txt").write_text("x", encoding="utf-8")

    import backend.services.backup_jobs as bj

    monkeypatch.setattr(bj, "ROOT", tmp_path / "proj")
    monkeypatch.setattr(bj, "_run_pg_dump", lambda: dump)

    out = run_full_backup(skip_db_dump=True)
    assert out["uploads_mirrored"] is True
    assert (tmp_path / "pg_dump" / "test_manual.dump").is_file()
    assert (tmp_path / "uploads" / "latest" / "a.txt").is_file()
