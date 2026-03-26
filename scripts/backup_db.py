import argparse
import os
import shutil
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "backend" / "database" / "mechanical.db"
BACKUP_DIR = ROOT / "backups" / "auto"


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _ensure_dirs() -> None:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)


def _is_valid_sqlite(path: Path) -> bool:
    try:
        con = sqlite3.connect(str(path))
        cur = con.cursor()
        cur.execute("PRAGMA integrity_check")
        row = cur.fetchone()
        con.close()
        return bool(row and str(row[0]).lower() == "ok")
    except Exception:
        return False


def _create_backup(kind: str) -> Path:
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found: {DB_PATH}")
    _ensure_dirs()
    out = BACKUP_DIR / f"{_stamp()}_{kind}_mechanical.db"
    shutil.copy2(DB_PATH, out)
    if not _is_valid_sqlite(out):
        raise RuntimeError("Backup integrity_check failed")
    return out


def _parse_backup_time(name: str):
    # expected: YYYYMMDD_HHMMSS_kind_mechanical.db
    try:
        ts = name.split("_", 2)
        return datetime.strptime(f"{ts[0]}_{ts[1]}", "%Y%m%d_%H%M%S")
    except Exception:
        return None


def _prune(daily_days: int, weekly_weeks: int) -> None:
    if not BACKUP_DIR.exists():
        return
    now = datetime.now()
    cutoff_daily = now - timedelta(days=daily_days)
    cutoff_weekly = now - timedelta(weeks=weekly_weeks)

    files = sorted(BACKUP_DIR.glob("*_mechanical.db"))
    for fp in files:
        dt = _parse_backup_time(fp.name)
        if not dt:
            continue
        name = fp.name.lower()
        if "_weekly_" in name and dt < cutoff_weekly:
            fp.unlink(missing_ok=True)
        elif "_daily_" in name and dt < cutoff_daily:
            fp.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Create and rotate ScheduleOptimizer DB backups.")
    parser.add_argument("--kind", choices=["manual", "daily", "weekly"], default="manual")
    parser.add_argument("--daily-days", type=int, default=14)
    parser.add_argument("--weekly-weeks", type=int, default=8)
    args = parser.parse_args()

    out = _create_backup(args.kind)
    _prune(args.daily_days, args.weekly_weeks)
    print(f"Backup created: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
