"""Compare survey_responses in backup dump vs live DB."""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.pg_dump_via_env import _find_pg_dump  # noqa: E402
from backend.services.utilities import get_connection  # noqa: E402


def pg_restore_bin() -> str:
    pg_dump = _find_pg_dump()
    if not pg_dump:
        raise RuntimeError("pg_restore/pg_dump not found")
    p = Path(pg_dump)
    name = "pg_restore.exe" if p.name.lower().endswith(".exe") else "pg_restore"
    candidate = p.parent / name
    if candidate.is_file():
        return str(candidate)
    import shutil
    found = shutil.which("pg_restore")
    if found:
        return found
    raise RuntimeError("pg_restore not found")


def extract_survey_keys_from_dump(dump_path: Path) -> list[dict]:
    """Parse survey_responses rows from pg_restore SQL output."""
    out_sql = tempfile.NamedTemporaryFile(suffix=".sql", delete=False, mode="w", encoding="utf-8")
    out_sql.close()
    sql_path = out_sql.name
    try:
        subprocess.run(
            [pg_restore_bin(), "-f", sql_path, "--data-only", "-t", "survey_responses", str(dump_path)],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        err = (e.stderr or e.stdout or "").strip()
        raise RuntimeError(f"pg_restore failed: {err}") from e

    text = Path(sql_path).read_text(encoding="utf-8", errors="replace")
    rows: list[dict] = []
    in_copy = False
    cols: list[str] = []
    for line in text.splitlines():
        if line.startswith("COPY public.survey_responses (") or line.startswith("COPY survey_responses ("):
            m = re.search(r"\(([^)]+)\)", line)
            if m:
                cols = [c.strip() for c in m.group(1).split(",")]
            in_copy = True
            continue
        if in_copy:
            if line.strip() == "\\.":
                in_copy = False
                cols = []
                continue
            if not cols:
                continue
            parts = line.split("\t")
            if len(parts) < len(cols):
                continue
            row = dict(zip(cols, parts))
            rows.append(row)
    return rows


def response_key(row: dict) -> tuple:
    return (
        (row.get("template_code") or "").strip(),
        (row.get("semester") or "").strip(),
        (row.get("respondent_role") or "").strip(),
        (row.get("respondent_id") or "").strip(),
        (row.get("subject_type") or "").strip(),
        str(row.get("subject_id") or "0").strip(),
    )


def live_survey_keys() -> set[tuple]:
    with get_connection() as conn:
        cur = conn.cursor()
        rows = cur.execute(
            """
            SELECT template_code, semester, respondent_role, respondent_id,
                   subject_type, subject_id
            FROM survey_responses
            """
        ).fetchall()
    keys: set[tuple] = set()
    for r in rows:
        if hasattr(r, "keys"):
            keys.add(response_key(dict(r)))
        else:
            keys.add((str(r[0] or ""), str(r[1] or ""), str(r[2] or ""), str(r[3] or ""), str(r[4] or ""), str(r[5] or "0")))
    return keys


def student_names(ids: set[str]) -> dict[str, str]:
    if not ids:
        return {}
    with get_connection() as conn:
        cur = conn.cursor()
        ph = ",".join("?" for _ in ids)
        rows = cur.execute(
            f"SELECT student_id, COALESCE(student_name,'') FROM students WHERE student_id IN ({ph})",
            tuple(ids),
        ).fetchall()
    out = {}
    for r in rows:
        sid = r[0] if not hasattr(r, "keys") else r["student_id"]
        name = (r[1] if not hasattr(r, "keys") else (r.get("student_name") or r[0] or "")) or ""
        out[str(sid).strip()] = (name or "").strip()
    return out


def compare_dump(dump_path: Path, label: str) -> None:
    print(f"\n=== {label} ===")
    print(f"File: {dump_path}")
    backup_rows = extract_survey_keys_from_dump(dump_path)
    backup_keys = {response_key(r): r for r in backup_rows}
    live_keys = live_survey_keys()
    missing = [backup_keys[k] for k in backup_keys if k not in live_keys]
    print(f"Backup responses: {len(backup_keys)}")
    print(f"Live responses:   {len(live_keys)}")
    print(f"Missing in live:  {len(missing)}")
    if not missing:
        print("No missing survey responses vs this backup.")
        return

    student_ids: set[str] = set()
    by_student: dict[str, list[dict]] = {}
    for r in missing:
        role = (r.get("respondent_role") or "").strip().lower()
        rid = (r.get("respondent_id") or "").strip()
        if role == "student" and rid:
            student_ids.add(rid)
            by_student.setdefault(rid, []).append(r)

    names = student_names(student_ids)
    print(f"\nStudents with missing responses: {len(by_student)}")
    for sid in sorted(by_student.keys()):
        name = names.get(sid) or "—"
        items = by_student[sid]
        print(f"  {sid} — {name} ({len(items)} response(s))")
        for it in items[:5]:
            print(
                f"    - {it.get('template_code')} | {it.get('semester')} | "
                f"submitted: {it.get('submitted_at') or it.get('created_at') or '—'}"
            )


def main() -> int:
    dumps = [
        Path(r"D:\ScheduleOptimizer_Backups\pg_dump\20260622_190432_schedule_optimizer.dump"),
        Path(r"D:\ScheduleOptimizer_Backups\pg_dump\20260622_193548_schedule_optimizer.dump"),
        Path(r"D:\ScheduleOptimizer_Backups\pg_dump\20260620_233002_schedule_optimizer.dump"),
    ]
    for d in dumps:
        if d.is_file():
            try:
                compare_dump(d, d.name)
            except Exception as exc:
                print(f"\n=== {d.name} === ERROR: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
