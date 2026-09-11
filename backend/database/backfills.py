"""ترحيلات بيانات توافقية تُستدعى من ensure_tables / الاختبارات."""
from __future__ import annotations

import logging

from backend.database.db_config import is_postgresql
from backend.database.introspection import fetch_table_columns, schedule_pk_column, table_exists

logger = logging.getLogger("backend.database")

# قيمة sentinel لصف «القسم الرئيسي» بدون صف في جدول schedule (SQLite / PostgreSQL)
HOME_ASSIGNMENT_SECTION_ID = -1


def ensure_schedule_id_identity(conn) -> dict:
    """
    يضمن أن schedule.id تسلسلي صالح على PostgreSQL.

    تاريخياً أُضيف العمود كـ BIGINT بلا DEFAULT/SEQUENCE، فبقيت الصفوف id=NULL
    وتعطّل الحذف/التفريغ المعتمد على المعرّف. الدالة آمنة للتكرار.
    """
    out = {"ok": False, "filled": 0, "backend": "none"}
    if not table_exists(conn, "schedule"):
        return out
    cols = {str(c).strip().lower() for c in (fetch_table_columns(conn, "schedule") or [])}
    if "id" not in cols:
        return out
    cur = conn.cursor()
    if is_postgresql():
        out["backend"] = "postgresql"
        try:
            cur.execute("CREATE SEQUENCE IF NOT EXISTS schedule_id_seq")
            max_row = cur.execute(
                "SELECT COALESCE(MAX(id), 0) FROM schedule"
            ).fetchone()
            try:
                max_id = int(max_row[0] if max_row is not None else 0)
            except (TypeError, ValueError, KeyError):
                max_id = 0
            if max_id <= 0:
                # nextval التالي = 1
                cur.execute("SELECT setval('schedule_id_seq', 1, false)")
            else:
                cur.execute("SELECT setval('schedule_id_seq', ?)", (max_id,))
            cur.execute(
                """
                UPDATE schedule
                SET id = nextval('schedule_id_seq')
                WHERE id IS NULL
                """
            )
            filled = int(getattr(cur, "rowcount", 0) or 0)
            if filled < 0:
                filled = 0
            out["filled"] = filled
            cur.execute(
                """
                ALTER TABLE schedule
                ALTER COLUMN id SET DEFAULT nextval('schedule_id_seq')
                """
            )
            try:
                cur.execute("ALTER SEQUENCE schedule_id_seq OWNED BY schedule.id")
            except Exception:
                pass
            try:
                cur.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_schedule_id ON schedule(id)"
                )
            except Exception:
                pass
            conn.commit()
            out["ok"] = True
            if filled:
                logger.warning("schedule.id backfill: filled %s null id rows", filled)
            return out
        except Exception as e:
            logger.warning("ensure_schedule_id_identity (postgresql) failed: %s", e)
            try:
                conn.rollback()
            except Exception:
                pass
            return out

    # SQLite اختباري: id قد يكون NULL بينما rowid موجود
    out["backend"] = "sqlite"
    try:
        cur.execute("UPDATE schedule SET id = rowid WHERE id IS NULL")
        filled = int(getattr(cur, "rowcount", 0) or 0)
        if filled < 0:
            filled = 0
        out["filled"] = filled
        conn.commit()
        out["ok"] = True
        return out
    except Exception as e:
        logger.warning("ensure_schedule_id_identity (sqlite) failed: %s", e)
        try:
            conn.rollback()
        except Exception:
            pass
        return out


def backfill_instructor_cross_department_data(conn) -> None:
    """
    ترحيل توافقي لجدول instructor_department_assignments:
    - من صفوف schedule ذات instructor_id و department_id.
    - من instructors.department_id عندما لا توجد أي صفوف schedule لهذا الأستاذ.
    يمكن استدعاؤه عدة مرات (idempotent).
    """
    if not table_exists(conn, "instructor_department_assignments"):
        return
    cur = conn.cursor()
    scols = fetch_table_columns(conn, "schedule")
    pk_col = "rowid"
    try:
        pk_col = schedule_pk_column(conn)
    except Exception:
        pass

    # من الجدول الدراسي
    if "instructor_id" in scols and "department_id" in scols:
        try:
            sem_sel = "COALESCE(NULLIF(TRIM(semester), ''), '')"
            if is_postgresql():
                sem_sel = "COALESCE(NULLIF(TRIM(semester::text), ''), '')"
            rows = cur.execute(
                f"""
                SELECT {pk_col}, instructor_id, department_id, {sem_sel}
                FROM schedule
                WHERE instructor_id IS NOT NULL AND department_id IS NOT NULL
                """
            ).fetchall()
            for r in rows:
                sec_id = int(r[0])
                iid = int(r[1])
                did = int(r[2])
                sem = str(r[3] or "")
                if is_postgresql():
                    cur.execute(
                        """
                        INSERT INTO instructor_department_assignments
                        (instructor_id, department_id, schedule_section_id, semester,
                         is_primary, is_active, migration_source)
                        VALUES (%s, %s, %s, %s, 0, 1, 'schedule_backfill')
                        ON CONFLICT (instructor_id, department_id, schedule_section_id, semester) DO NOTHING
                        """,
                        (iid, did, sec_id, sem),
                    )
                else:
                    cur.execute(
                        """
                        INSERT OR IGNORE INTO instructor_department_assignments
                        (instructor_id, department_id, schedule_section_id, semester,
                         is_primary, is_active, migration_source)
                        VALUES (?, ?, ?, ?, 0, 1, 'schedule_backfill')
                        """,
                        (iid, did, sec_id, sem),
                    )
        except Exception as e:
            logger.warning("backfill instructor_department_assignments from schedule: %s", e)

    # قسم رئيسي من instructors عند غياب أي صف schedule للأستاذ
    icols = fetch_table_columns(conn, "instructors")
    if "department_id" in icols:
        try:
            rows = cur.execute(
                """
                SELECT i.id, i.department_id FROM instructors i
                WHERE i.department_id IS NOT NULL
                AND NOT EXISTS (
                    SELECT 1 FROM schedule s WHERE s.instructor_id = i.id
                )
                """
            ).fetchall()
            for r in rows:
                iid = int(r[0])
                did = int(r[1])
                if is_postgresql():
                    cur.execute(
                        """
                        INSERT INTO instructor_department_assignments
                        (instructor_id, department_id, schedule_section_id, semester,
                         is_primary, is_active, migration_source)
                        VALUES (%s, %s, %s, '', 1, 1, 'home_backfill')
                        ON CONFLICT (instructor_id, department_id, schedule_section_id, semester) DO NOTHING
                        """,
                        (iid, did, HOME_ASSIGNMENT_SECTION_ID),
                    )
                else:
                    cur.execute(
                        """
                        INSERT OR IGNORE INTO instructor_department_assignments
                        (instructor_id, department_id, schedule_section_id, semester,
                         is_primary, is_active, migration_source)
                        VALUES (?, ?, ?, '', 1, 1, 'home_backfill')
                        """,
                        (iid, did, HOME_ASSIGNMENT_SECTION_ID),
                    )
        except Exception as e:
            logger.warning("backfill instructor_department_assignments from instructors home dept: %s", e)


def backfill_academic_pathway_defaults(conn) -> None:
    """
    ترحيل افتراضي: مقررات الخطة → dept_common؛ طلاب بلا مرحلة → dept_admitted
    (من لديهم track_code → specialized). مناسب لوضع ميكانيك: الجميع داخل القسم بعد العام.
    """
    cur = conn.cursor()
    try:
        pccols = fetch_table_columns(conn, "program_courses")
    except Exception:
        pccols = []
    if "requirement_scope" in pccols:
        try:
            cur.execute(
                """
                UPDATE program_courses
                SET requirement_scope = 'dept_common'
                WHERE requirement_scope IS NULL OR TRIM(COALESCE(requirement_scope, '')) = ''
                """
            )
        except Exception as e:
            logger.warning("backfill program_courses.requirement_scope: %s", e)
    try:
        scols = fetch_table_columns(conn, "students")
    except Exception:
        scols = []
    if "pathway_stage" not in scols:
        return
    try:
        cur.execute(
            """
            UPDATE students
            SET pathway_stage = 'specialized'
            WHERE (pathway_stage IS NULL OR TRIM(COALESCE(pathway_stage, '')) = '')
              AND TRIM(COALESCE(track_code, '')) <> ''
            """
        )
        cur.execute(
            """
            UPDATE students
            SET pathway_stage = 'dept_admitted'
            WHERE pathway_stage IS NULL OR TRIM(COALESCE(pathway_stage, '')) = ''
            """
        )
    except Exception as e:
        logger.warning("backfill students.pathway_stage: %s", e)

    try:
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass

