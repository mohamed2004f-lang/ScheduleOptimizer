"""أعمدة عرض جدول الاتجاه العام (مسارات قابلة للتسمية من صفحة المجموعات)."""

from __future__ import annotations

from typing import Any

from backend.database.database import fetch_table_columns, table_exists
from backend.services.utilities import get_current_term

MIN_DISPLAY_TRACKS = 1
MAX_DISPLAY_TRACKS = 4
DEFAULT_TRACK_COUNT = 2
DEFAULT_TRACK_LABELS = ("مجموعة 1", "مجموعة 2", "مجموعة 3", "مجموعة 4")


def _now_iso() -> str:
    import datetime

    return datetime.datetime.utcnow().isoformat(timespec="seconds")


def _row_val(row, idx: int = 0, key: str | None = None, default=None):
    if row is None:
        return default
    if key and hasattr(row, "keys"):
        try:
            if key in row.keys():
                return row[key]
        except Exception:
            pass
    try:
        return row[idx]
    except Exception:
        return default


def default_track_defs(count: int = DEFAULT_TRACK_COUNT) -> list[dict[str, Any]]:
    n = max(MIN_DISPLAY_TRACKS, min(MAX_DISPLAY_TRACKS, int(count or DEFAULT_TRACK_COUNT)))
    return [
        {"index": i, "label": DEFAULT_TRACK_LABELS[i - 1] if i <= len(DEFAULT_TRACK_LABELS) else f"مجموعة {i}"}
        for i in range(1, n + 1)
    ]


def resolve_semester_label(conn, semester: str | None = None) -> str:
    sem = (semester or "").strip()
    if sem:
        return sem
    tname, tyear = get_current_term(conn=conn)
    return f"{(tname or '').strip()} {(tyear or '').strip()}".strip()


def list_display_tracks(
    conn,
    *,
    semester: str | None = None,
    department_id: int,
    ensure_defaults: bool = True,
) -> list[dict[str, Any]]:
    """قائمة أعمدة العرض النشطة لقسم/فصل. إن لم تُعرَّف يُرجع الافتراضي (بدون كتابة)."""
    dept = int(department_id or 0)
    if dept <= 0:
        return default_track_defs()
    sem = resolve_semester_label(conn, semester)
    ensure_display_tracks_schema(conn)
    if not table_exists(conn, "schedule_display_tracks"):
        return default_track_defs()
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT track_index, label, is_active
        FROM schedule_display_tracks
        WHERE semester = ? AND department_id = ? AND is_active = 1
        ORDER BY track_index
        """,
        (sem, dept),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        idx = int(_row_val(r, 0, "track_index") or 0)
        label = str(_row_val(r, 1, "label") or "").strip()
        if idx < MIN_DISPLAY_TRACKS or idx > MAX_DISPLAY_TRACKS:
            continue
        if not label:
            label = DEFAULT_TRACK_LABELS[idx - 1] if idx <= len(DEFAULT_TRACK_LABELS) else f"مجموعة {idx}"
        out.append({"index": idx, "label": label})
    if out:
        return out
    if ensure_defaults:
        return default_track_defs()
    return []


def save_display_tracks(
    conn,
    *,
    semester: str,
    department_id: int,
    tracks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """يستبدل أعمدة العرض للقسم/الفصل. tracks: [{index|track_index, label}, ...]"""
    dept = int(department_id or 0)
    sem = (semester or "").strip()
    if dept <= 0 or not sem:
        raise ValueError("semester و department_id مطلوبان")
    ensure_display_tracks_schema(conn)
    if not table_exists(conn, "schedule_display_tracks"):
        raise ValueError("جدول أعمدة العرض غير متوفر — شغّل الترحيل")
    cleaned: list[dict[str, Any]] = []
    seen: set[int] = set()
    for t in tracks or []:
        try:
            idx = int(t.get("index") if t.get("index") is not None else t.get("track_index") or 0)
        except (TypeError, ValueError):
            continue
        if idx < MIN_DISPLAY_TRACKS or idx > MAX_DISPLAY_TRACKS or idx in seen:
            continue
        label = str(t.get("label") or "").strip()
        if not label:
            label = DEFAULT_TRACK_LABELS[idx - 1] if idx <= len(DEFAULT_TRACK_LABELS) else f"مجموعة {idx}"
        seen.add(idx)
        cleaned.append({"index": idx, "label": label})
    if not cleaned:
        raise ValueError("يجب تعريف عمود عرض واحد على الأقل")
    cleaned.sort(key=lambda x: x["index"])
    # أعد ترقيم 1..N متتابعاً حسب الترتيب
    renumbered = []
    for i, t in enumerate(cleaned, start=1):
        if i > MAX_DISPLAY_TRACKS:
            break
        renumbered.append({"index": i, "label": t["label"]})
    cur = conn.cursor()
    now = _now_iso()
    cur.execute(
        "DELETE FROM schedule_display_tracks WHERE semester = ? AND department_id = ?",
        (sem, dept),
    )
    for t in renumbered:
        cur.execute(
            """
            INSERT INTO schedule_display_tracks
                (semester, department_id, track_index, label, is_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, 1, ?, ?)
            """,
            (sem, dept, int(t["index"]), t["label"], now, now),
        )
    conn.commit()
    return renumbered


def _is_postgres(conn) -> bool:
    try:
        name = str(getattr(getattr(conn, "dialect", None), "name", "") or "").lower()
        if name == "postgresql":
            return True
    except Exception:
        pass
    try:
        mod = type(conn).__module__ or ""
        return "psycopg" in mod or "pg_compat" in mod
    except Exception:
        return False


def ensure_display_tracks_schema(conn) -> None:
    """إنشاء الجدول/العمود إن نُقصا (توافق اختبارات وترحيل متأخر)."""
    cur = conn.cursor()
    pg = _is_postgres(conn)
    try:
        if not table_exists(conn, "schedule_display_tracks"):
            if pg:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS schedule_display_tracks (
                        id BIGSERIAL PRIMARY KEY,
                        semester TEXT NOT NULL,
                        department_id BIGINT NOT NULL,
                        track_index INTEGER NOT NULL,
                        label TEXT NOT NULL DEFAULT '',
                        is_active INTEGER NOT NULL DEFAULT 1,
                        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE (semester, department_id, track_index)
                    )
                    """
                )
            else:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS schedule_display_tracks (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        semester TEXT NOT NULL,
                        department_id INTEGER NOT NULL,
                        track_index INTEGER NOT NULL,
                        label TEXT NOT NULL DEFAULT '',
                        is_active INTEGER NOT NULL DEFAULT 1,
                        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE (semester, department_id, track_index)
                    )
                    """
                )
        if table_exists(conn, "teaching_groups"):
            cols = {c.lower() for c in fetch_table_columns(conn, "teaching_groups")}
            if "display_column" not in cols:
                try:
                    if pg:
                        cur.execute(
                            "ALTER TABLE teaching_groups ADD COLUMN IF NOT EXISTS display_column INTEGER"
                        )
                    else:
                        cur.execute("ALTER TABLE teaching_groups ADD COLUMN display_column INTEGER")
                except Exception:
                    pass
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass


def teaching_groups_has_display_column(conn) -> bool:
    if not table_exists(conn, "teaching_groups"):
        return False
    ensure_display_tracks_schema(conn)
    cols = {c.lower() for c in fetch_table_columns(conn, "teaching_groups")}
    return "display_column" in cols


def clamp_display_column(value: Any, tracks_n: int) -> int | None:
    try:
        if value is None or value == "":
            return None
        n = int(value)
    except (TypeError, ValueError):
        return None
    tn = max(MIN_DISPLAY_TRACKS, int(tracks_n or DEFAULT_TRACK_COUNT))
    if n < 1:
        return None
    return min(n, tn)


def auto_display_column_for_group_code(
    group_code: str | None,
    *,
    sibling_codes: list[str],
    tracks_n: int,
) -> int:
    """توزيع تلقائي: رتّب رموز المجموعات ثم عمود = min(رتبة، N)."""
    from backend.services.teaching_groups import DEFAULT_GROUP_CODE, normalize_group_code

    tn = max(MIN_DISPLAY_TRACKS, min(MAX_DISPLAY_TRACKS, int(tracks_n or DEFAULT_TRACK_COUNT)))
    code = normalize_group_code(group_code)
    codes = sorted(
        {normalize_group_code(c) for c in (sibling_codes or []) if normalize_group_code(c)},
        key=lambda c: (c == DEFAULT_GROUP_CODE, c),
    )
    if not codes:
        return 1
    try:
        rank = codes.index(code) if code in codes else 0
    except ValueError:
        rank = 0
    return min(rank + 1, tn)


def enrich_schedule_rows_display_columns(
    conn,
    rows: list[dict[str, Any]],
    *,
    tracks_n: int | None = None,
) -> None:
    """يملأ display_column على صفوف الجدول (صريح أو تلقائي حسب group_code للمقرر)."""
    if not rows:
        return
    tn = int(tracks_n or DEFAULT_TRACK_COUNT)
    tn = max(MIN_DISPLAY_TRACKS, min(MAX_DISPLAY_TRACKS, tn))

    # sibling codes لكل مقرر في نفس الفصل
    by_course: dict[str, set[str]] = {}
    for r in rows:
        cname = str(r.get("course_name") or "").strip().lower()
        if not cname:
            continue
        gcode = str(r.get("group_code") or r.get("tg_group_code") or "").strip()
        by_course.setdefault(cname, set())
        if gcode:
            by_course[cname].add(gcode)

    for r in rows:
        explicit = clamp_display_column(r.get("display_column"), tn)
        if explicit is None:
            explicit = clamp_display_column(r.get("tg_display_column"), tn)
        if explicit is not None:
            r["display_column"] = explicit
            continue
        cname = str(r.get("course_name") or "").strip().lower()
        gcode = str(r.get("group_code") or r.get("tg_group_code") or "")
        siblings = sorted(by_course.get(cname) or [])
        r["display_column"] = auto_display_column_for_group_code(
            gcode, sibling_codes=siblings, tracks_n=tn
        )
