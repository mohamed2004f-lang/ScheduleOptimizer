"""نسخ احتياطي كامل: PostgreSQL + مرفقات → مجلد مرآة (افتراضياً D: على Windows)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


def _in_docker() -> bool:
    return os.path.exists("/.dockerenv")


def _default_mirror_root() -> str:
    if _in_docker():
        return "/app/backups/mirror"
    if sys.platform == "win32":
        return r"D:\ScheduleOptimizer_Backups"
    return str(ROOT / "backups" / "mirror")


def _mirror_root() -> str:
    return (os.environ.get("BACKUP_MIRROR_ROOT") or _default_mirror_root()).strip()


def _retention_days() -> int:
    raw = (os.environ.get("BACKUP_RETENTION_DAYS") or "30").strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return 30


def _mirror_available(mirror: Path) -> bool:
    """Windows: تحقق من القرص. Docker/Linux: تحقق من إمكانية الكتابة."""
    if sys.platform == "win32" and not _in_docker():
        drive = mirror.anchor
        if drive and len(drive) >= 2 and drive[1] == ":":
            return Path(drive).exists()
    try:
        mirror.mkdir(parents=True, exist_ok=True)
        probe = mirror / ".mirror_probe"
        probe.write_text("1", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def _scheduled_hint() -> str:
    if _in_docker():
        return (
            "Docker: النسخ اليدوي من هذه الصفحة. "
            "المجلد مربوط بقرص المضيف (BACKUP_MIRROR_HOST). "
            "للجدولة على Windows استخدم scripts\\backup_full_to_d.ps1."
        )
    return "يومياً 23:30 عبر مهمة Windows (setup_backup_tasks.bat)"


def _latest_dump_in(dir_path: Path) -> dict[str, Any]:
    if not dir_path.is_dir():
        return {"exists": False, "name": "", "path": "", "mtime_utc": None, "size_bytes": 0}
    files = sorted(dir_path.glob("*.dump"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        return {"exists": False, "name": "", "path": "", "mtime_utc": None, "size_bytes": 0}
    latest = files[0]
    ts = datetime.fromtimestamp(latest.stat().st_mtime, tz=timezone.utc)
    return {
        "exists": True,
        "name": latest.name,
        "path": str(latest),
        "mtime_utc": ts.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "size_bytes": latest.stat().st_size,
    }


def backup_status() -> dict[str, Any]:
    mirror = Path(_mirror_root())
    local_pg = ROOT / "backups" / "pg_dump"
    uploads_latest = mirror / "uploads" / "latest"
    log_file = mirror / "logs" / "backup.log"
    return {
        "mirror_root": str(mirror),
        "mirror_drive_available": _mirror_available(mirror),
        "retention_days": _retention_days(),
        "local_latest_dump": _latest_dump_in(local_pg),
        "mirror_latest_dump": _latest_dump_in(mirror / "pg_dump"),
        "uploads_latest_exists": uploads_latest.is_dir(),
        "uploads_latest_mtime_utc": (
            datetime.fromtimestamp(uploads_latest.stat().st_mtime, tz=timezone.utc).strftime(
                "%Y-%m-%d %H:%M:%S UTC"
            )
            if uploads_latest.is_dir()
            else None
        ),
        "log_tail": _read_log_tail(log_file, 12),
        "scheduled_hint": _scheduled_hint(),
        "in_docker": _in_docker(),
    }


def _read_log_tail(path: Path, lines: int) -> list[str]:
    if not path.is_file():
        return []
    try:
        content = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return content[-lines:]
    except OSError:
        return []


def _run_pg_dump() -> Path:
    py = ROOT / ".venv" / "Scripts" / "python.exe"
    if not py.is_file():
        py = Path(sys.executable)
    script = ROOT / "scripts" / "pg_dump_via_env.py"
    proc = subprocess.run(
        [str(py), str(script)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
        raise RuntimeError(err)
    lines = [ln.strip() for ln in (proc.stdout or "").splitlines() if ln.strip()]
    if not lines:
        raise RuntimeError("pg_dump لم يُرجع مسار الملف")
    dump_path = Path(lines[-1])
    if not dump_path.is_file():
        raise RuntimeError(f"ملف النسخة غير موجود: {dump_path}")
    return dump_path


def _sync_tree(src: Path, dst: Path) -> None:
    if not src.is_dir():
        return
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        target = dst / item.name
        if item.is_dir():
            _sync_tree(item, target)
        else:
            shutil.copy2(item, target)


def _prune_old_dumps(dir_path: Path, days: int) -> int:
    if not dir_path.is_dir():
        return 0
    cutoff = datetime.now() - timedelta(days=days)
    removed = 0
    for f in dir_path.glob("*.dump"):
        if datetime.fromtimestamp(f.stat().st_mtime) < cutoff:
            f.unlink(missing_ok=True)
            removed += 1
    return removed


def _prune_old_upload_snapshots(uploads_dir: Path, days: int) -> int:
    if not uploads_dir.is_dir():
        return 0
    cutoff = datetime.now() - timedelta(days=days)
    removed = 0
    for d in uploads_dir.iterdir():
        if d.is_dir() and d.name.startswith("uploads_"):
            if datetime.fromtimestamp(d.stat().st_mtime) < cutoff:
                shutil.rmtree(d, ignore_errors=True)
                removed += 1
    return removed


def run_full_backup(*, skip_db_dump: bool = False) -> dict[str, Any]:
    mirror = Path(_mirror_root())
    if not _mirror_available(mirror):
        raise RuntimeError(f"مجلد النسخ غير متاح أو غير قابل للكتابة: {mirror}")

    mirror.mkdir(parents=True, exist_ok=True)
    pg_mirror = mirror / "pg_dump"
    pg_local = ROOT / "backups" / "pg_dump"
    uploads_src = ROOT / "backend" / "uploads"
    uploads_latest = mirror / "uploads" / "latest"
    uploads_daily = mirror / "uploads" / f"uploads_{datetime.now().strftime('%Y%m%d')}"
    retention = _retention_days()
    steps: list[str] = []

    dump_path: Path | None = None
    if not skip_db_dump:
        dump_path = _run_pg_dump()
        steps.append(f"pg_dump: {dump_path.name}")

    pg_local.mkdir(parents=True, exist_ok=True)
    pg_mirror.mkdir(parents=True, exist_ok=True)
    for src in pg_local.glob("*.dump"):
        shutil.copy2(src, pg_mirror / src.name)
    steps.append(f"mirror pg_dump → {pg_mirror}")

    uploads_mirrored = False
    if uploads_src.is_dir():
        _sync_tree(uploads_src, uploads_latest)
        uploads_mirrored = True
        steps.append(f"mirror uploads → {uploads_latest}")
        if not uploads_daily.is_dir():
            shutil.copytree(uploads_src, uploads_daily)
            steps.append(f"daily snapshot → {uploads_daily.name}")

    pruned_dumps = _prune_old_dumps(pg_local, retention) + _prune_old_dumps(pg_mirror, retention)
    pruned_uploads = _prune_old_upload_snapshots(mirror / "uploads", retention)
    if pruned_dumps or pruned_uploads:
        steps.append(f"pruned dumps={pruned_dumps}, upload_dirs={pruned_uploads}")

    _append_mirror_log(mirror, "=== admin full backup OK ===")
    latest = _latest_dump_in(pg_mirror if pg_mirror.is_dir() else pg_local)
    return {
        "mirror_root": str(mirror),
        "dump_name": latest.get("name") or (dump_path.name if dump_path else ""),
        "dump_path_mirror": str(pg_mirror / latest["name"]) if latest.get("name") else "",
        "uploads_mirrored": uploads_mirrored,
        "steps": steps,
        "retention_days": retention,
    }


def _append_mirror_log(mirror: Path, line: str) -> None:
    log_dir = mirror / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "backup.log"
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with log_file.open("a", encoding="utf-8") as fh:
            fh.write(f"{stamp} {line}\n")
    except OSError:
        pass
