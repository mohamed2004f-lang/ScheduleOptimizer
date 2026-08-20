"""إقفال إداري استثنائي لتقارير المقررات — لا يُعدّ دليلاً للجودة."""
from __future__ import annotations

import datetime
import logging
from typing import Any

from backend.database.database import is_postgresql, table_exists
from backend.services.utilities import get_current_term, schedule_semester_matches_current_term

logger = logging.getLogger(__name__)

STATUS_ADMIN_CLOSED = "admin_closed"
QUALITY_CLOSURE_STATUSES = frozenset({"submitted", "approved"})
OPEN_FOR_ADMIN_CLOSE = frozenset({"", "draft", "submitted", "rejected"})
DEFAULT_ADMIN_CLOSE_NOTE = (
    "إقفال إداري استثنائي. لم يُستكمل ملف المقرر من عضو هيئة التدريس. "
    "أُدخل وأُغلق بواسطة رئيس القسم في إطار تشغيل تجريبي للمنظومة (تدريب وتطوير). "
    "لا يُعدّ هذا التقرير دليلاً مكتملاً للجودة."
)


def current_term_label(conn) -> str:
    name, year = get_current_term(conn=conn)
    return f"{(name or '').strip()} {(year or '').strip()}".strip()


def ensure_admin_closed_status_allowed(conn) -> None:
    """توسيع قيد الحالة ليشمل admin_closed (PostgreSQL وSQLite)."""
    if not table_exists(conn, "course_closure_reports"):
        return
    cur = conn.cursor()
    if is_postgresql():
        try:
            cur.execute(
                "ALTER TABLE course_closure_reports DROP CONSTRAINT IF EXISTS course_closure_status_chk"
            )
            cur.execute(
                """
                ALTER TABLE course_closure_reports
                ADD CONSTRAINT course_closure_status_chk
                CHECK (status IN ('draft', 'submitted', 'approved', 'rejected', 'admin_closed'))
                """
            )
        except Exception:
            logger.exception("ensure admin_closed constraint (postgresql)")
            try:
                conn.rollback()
            except Exception:
                pass
        return
    try:
        row = cur.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='course_closure_reports'"
        ).fetchone()
        sql = (row[0] if row else "") or ""
        if "admin_closed" in sql or "CHECK (status" not in sql.upper().replace("\n", " "):
            return
        cur.execute("PRAGMA foreign_keys=OFF")
        cur.execute("ALTER TABLE course_closure_reports RENAME TO course_closure_reports_old_chk")
        cur.execute(
            """
            CREATE TABLE course_closure_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                section_id INTEGER NOT NULL,
                instructor_id INTEGER NOT NULL,
                semester TEXT NOT NULL,
                implementation_summary TEXT DEFAULT '',
                improvement_notes TEXT DEFAULT '',
                reflection_text TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'draft',
                curriculum_coverage_percent INTEGER,
                student_success_rate REAL,
                student_failure_rate REAL,
                results_analysis TEXT DEFAULT '',
                challenges TEXT DEFAULT '',
                action_plan TEXT DEFAULT '',
                ilo_achievement_percent INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                created_by TEXT DEFAULT '',
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_by TEXT DEFAULT '',
                approved_at TEXT,
                approved_by TEXT,
                review_note TEXT DEFAULT '',
                UNIQUE (section_id, instructor_id, semester)
            )
            """
        )
        old_cols = [
            r[1]
            for r in cur.execute("PRAGMA table_info(course_closure_reports_old_chk)").fetchall()
        ]
        new_cols = [
            r[1] for r in cur.execute("PRAGMA table_info(course_closure_reports)").fetchall()
        ]
        shared = [c for c in old_cols if c in new_cols]
        col_sql = ", ".join(shared)
        cur.execute(
            f"INSERT INTO course_closure_reports ({col_sql}) SELECT {col_sql} FROM course_closure_reports_old_chk"
        )
        cur.execute("DROP TABLE course_closure_reports_old_chk")
        cur.execute("PRAGMA foreign_keys=ON")
    except Exception:
        logger.exception("ensure admin_closed constraint (sqlite)")
        try:
            conn.rollback()
        except Exception:
            pass


def _cell(row, idx: int = 0, key: str | None = None):
    if row is None:
        return None
    if key and hasattr(row, "keys"):
        try:
            return row[key]
        except (KeyError, TypeError):
            pass
    try:
        return row[idx]
    except (IndexError, KeyError, TypeError):
        return None


def list_previous_semesters(conn, current: str) -> list[str]:
    """فصول لها شعب/مجموعات تدريس تختلف عن الفصل الحالي في الإعدادات."""
    cur = conn.cursor()
    sqls = [
        """
        SELECT TRIM(COALESCE(semester, '')) AS sem
        FROM schedule
        WHERE TRIM(COALESCE(semester, '')) <> ''
        GROUP BY TRIM(COALESCE(semester, ''))
        """,
    ]
    if table_exists(conn, "teaching_groups"):
        sqls.append(
            """
            SELECT TRIM(COALESCE(semester, '')) AS sem
            FROM teaching_groups
            WHERE TRIM(COALESCE(semester, '')) <> ''
            GROUP BY TRIM(COALESCE(semester, ''))
            """
        )
    if table_exists(conn, "course_closure_reports"):
        sqls.append(
            """
            SELECT TRIM(COALESCE(semester, '')) AS sem
            FROM course_closure_reports
            WHERE TRIM(COALESCE(semester, '')) <> ''
            GROUP BY TRIM(COALESCE(semester, ''))
            """
        )
    out: list[str] = []
    seen: set[str] = set()
    for sql in sqls:
        for r in cur.execute(sql).fetchall():
            sem = str(_cell(r, 0, "sem") or "").strip()
            if not sem or sem in seen:
                continue
            if current and schedule_semester_matches_current_term(sem, current):
                continue
            seen.add(sem)
            out.append(sem)
    out.sort(reverse=True)
    return out


def list_admin_close_queue(
    conn,
    *,
    semester: str,
    department_id: int | None,
    pk_col: str,
) -> list[dict[str, Any]]:
    sem = (semester or "").strip()
    if not sem:
        return []
    cur = conn.cursor()
    sql = f"""
        SELECT s.{pk_col} AS section_id,
               COALESCE(s.course_name,'') AS course_name,
               COALESCE(s.instructor,'') AS instructor,
               COALESCE(s.instructor_id, 0) AS instructor_id,
               COALESCE(s.semester,'') AS semester,
               COALESCE(i.name,'') AS instructor_name,
               COALESCE(c.id, 0) AS report_id,
               COALESCE(c.status, '') AS closure_status
        FROM schedule s
        LEFT JOIN instructors i ON i.id = s.instructor_id
        LEFT JOIN course_closure_reports c
          ON c.section_id = s.{pk_col}
         AND c.instructor_id = s.instructor_id
         AND c.semester = s.semester
        WHERE COALESCE(s.semester,'') = ?
          AND COALESCE(s.instructor_id, 0) > 0
    """
    params: list[Any] = [sem]
    if department_id is not None:
        sql += " AND s.department_id = ?"
        params.append(int(department_id))
    sql += f" ORDER BY s.course_name, s.{pk_col}"
    rows = cur.execute(sql, tuple(params)).fetchall()
    out = []
    seen = set()
    for r in rows:
        if hasattr(r, "keys"):
            d = dict(r)
        else:
            d = {
                "section_id": r[0],
                "course_name": r[1],
                "instructor": r[2],
                "instructor_id": r[3],
                "semester": r[4],
                "instructor_name": r[5],
                "report_id": r[6],
                "closure_status": r[7],
            }
        sid = int(d.get("section_id") or 0)
        iid = int(d.get("instructor_id") or 0)
        key = (sid, iid)
        if key in seen:
            continue
        seen.add(key)
        st = str(d.get("closure_status") or "").strip().lower()
        if st not in OPEN_FOR_ADMIN_CLOSE:
            continue
        d["instructor_name"] = (d.get("instructor_name") or d.get("instructor") or "").strip()
        d["closure_status"] = st if st else "missing"
        d["open_status"] = st
        out.append(d)
    return out


def admin_close_sections(
    conn,
    *,
    semester: str,
    note: str,
    actor: str,
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    ensure_admin_closed_status_allowed(conn)
    sem = (semester or "").strip()
    reason = (note or "").strip()
    who = (actor or "").strip() or "system"
    now = datetime.datetime.utcnow().isoformat()
    summary = (
        "إقفال إداري استثنائي — لم يُستكمل ملف المقرر من عضو هيئة التدريس. "
        "أُدخل بواسطة رئيس القسم (تدريب/تطوير)."
    )
    cur = conn.cursor()
    closed = 0
    skipped = 0
    ids: list[int] = []
    for it in items:
        sid = int(it.get("section_id") or 0)
        iid = int(it.get("instructor_id") or 0)
        if sid <= 0 or iid <= 0:
            skipped += 1
            continue
        st = str(it.get("open_status") or it.get("closure_status") or "").strip().lower()
        if st == "missing":
            st = ""
        if st not in OPEN_FOR_ADMIN_CLOSE:
            skipped += 1
            continue
        rid = int(it.get("report_id") or 0)
        if rid > 0:
            cur.execute(
                """
                UPDATE course_closure_reports
                SET status = ?, review_note = ?, implementation_summary = CASE
                        WHEN COALESCE(implementation_summary,'') = '' THEN ?
                        ELSE implementation_summary
                    END,
                    approved_at = ?, approved_by = ?, updated_at = ?, updated_by = ?
                WHERE id = ?
                """,
                (STATUS_ADMIN_CLOSED, reason, summary, now, who, now, who, rid),
            )
            report_id = rid
        else:
            cur.execute(
                """
                INSERT INTO course_closure_reports
                    (section_id, instructor_id, semester, implementation_summary, improvement_notes,
                     reflection_text, status, review_note, created_at, created_by, updated_at, updated_by,
                     approved_at, approved_by)
                VALUES (?, ?, ?, ?, '', '', ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (sid, iid, sem, summary, STATUS_ADMIN_CLOSED, reason, now, who, now, who, now, who),
            )
            report_id = int(cur.lastrowid or 0)
        closed += 1
        ids.append(report_id)
    return {"closed": closed, "skipped": skipped, "report_ids": ids}
