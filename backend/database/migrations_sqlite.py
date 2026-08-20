"""ensure_tables لمسار SQLite الاختباري فقط."""
from __future__ import annotations

import logging
import os

from backend.database.backfills import (
    backfill_academic_pathway_defaults,
    backfill_instructor_cross_department_data,
)
from backend.database.connection import get_connection
from backend.database.db_config import (
    DB_FILE,
    _in_pytest,
    allow_ensure_tables,
)
from backend.database.schema_ddl import INDEXES, TABLES_SCHEMA

logger = logging.getLogger("backend.database")


def ensure_sqlite_tables(db_file=None):
    """صيانة واختبارات SQLite فقط. إقلاع التطبيق يستخدم Alembic."""
    if not _in_pytest() and not allow_ensure_tables():
        raise RuntimeError(
            "SQLite schema is not applied at runtime. Use PostgreSQL and: alembic upgrade head"
        )

    db_path = db_file or DB_FILE
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    
    with get_connection(db_path) as conn:
        cur = conn.cursor()
        
        # إنشاء الجداول
        for table_name, create_stmt in TABLES_SCHEMA.items():
            try:
                cur.execute(create_stmt)
                logger.debug(f"Table {table_name} ensured")
            except Exception as e:
                logger.warning(f"Could not create table {table_name}: {e}")

        # ترقيات أعمدة جدول الطلاب لقواعد بيانات قديمة
        try:
            cols = [r[1] for r in cur.execute("PRAGMA table_info(students)").fetchall()]
            migrations = [
                ("join_year", "ALTER TABLE students ADD COLUMN join_year TEXT"),
                ("university_number", "ALTER TABLE students ADD COLUMN university_number TEXT"),
                ("email", "ALTER TABLE students ADD COLUMN email TEXT"),
                ("phone", "ALTER TABLE students ADD COLUMN phone TEXT"),
                ("updated_at", "ALTER TABLE students ADD COLUMN updated_at TEXT"),
                ("department_id", "ALTER TABLE students ADD COLUMN department_id INTEGER"),
                ("admission_program_id", "ALTER TABLE students ADD COLUMN admission_program_id INTEGER"),
                ("current_program_id", "ALTER TABLE students ADD COLUMN current_program_id INTEGER"),
                ("track_code", "ALTER TABLE students ADD COLUMN track_code TEXT DEFAULT ''"),
                ("specialized_at_term", "ALTER TABLE students ADD COLUMN specialized_at_term TEXT DEFAULT ''"),
                (
                    "enrollment_status",
                    "ALTER TABLE students ADD COLUMN enrollment_status TEXT NOT NULL DEFAULT 'active'",
                ),
                ("status_changed_at", "ALTER TABLE students ADD COLUMN status_changed_at TEXT"),
                ("status_reason", "ALTER TABLE students ADD COLUMN status_reason TEXT"),
                ("status_changed_term", "ALTER TABLE students ADD COLUMN status_changed_term TEXT"),
                ("status_changed_year", "ALTER TABLE students ADD COLUMN status_changed_year TEXT"),
                ("graduation_plan", "ALTER TABLE students ADD COLUMN graduation_plan TEXT DEFAULT ''"),
                ("pathway_stage", "ALTER TABLE students ADD COLUMN pathway_stage TEXT NOT NULL DEFAULT 'dept_admitted'"),
                ("join_term", "ALTER TABLE students ADD COLUMN join_term TEXT DEFAULT ''"),
            ]
            for col, stmt in migrations:
                if col not in cols:
                    try:
                        cur.execute(stmt)
                    except Exception:
                        pass
        except Exception as e:
            logger.warning(f"Could not migrate students table columns: {e}")

        # إنشاء الفهارس
        for idx_stmt in INDEXES:
            try:
                cur.execute(idx_stmt)
            except Exception as e:
                logger.warning(f"Could not create index: {e}")

        # بقية الترقيات الخفيفة (كانت في utilities.ensure_tables)
        try:
            cols = [r[1] for r in cur.execute("PRAGMA table_info(courses)").fetchall()]
        except Exception:
            cols = []
        if "is_archived" not in cols:
            try:
                cur.execute("ALTER TABLE courses ADD COLUMN is_archived INTEGER NOT NULL DEFAULT 0")
            except Exception:
                pass

            try:
                cur.execute("ALTER TABLE academic_calendar ADD COLUMN is_deleted INTEGER NOT NULL DEFAULT 0")
            except Exception:
                pass
            try:
                cur.execute("ALTER TABLE academic_calendar ADD COLUMN event_date_start TEXT")
            except Exception:
                pass
        try:
            cur.execute("ALTER TABLE term_windows ADD COLUMN grace_until TEXT")
        except Exception:
            pass

        for stmt in (
            "ALTER TABLE users ADD COLUMN instructor_id INTEGER",
            "ALTER TABLE users ADD COLUMN is_supervisor INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE users ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1",
            "ALTER TABLE users ADD COLUMN is_college_quality_lead INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE users ADD COLUMN is_system_account INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE users ADD COLUMN role_profile_id INTEGER",
            "ALTER TABLE users ADD COLUMN display_title_ar TEXT",
            "ALTER TABLE users ADD COLUMN is_dept_quality_coordinator INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE users ADD COLUMN totp_secret TEXT",
            "ALTER TABLE users ADD COLUMN totp_enabled INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE users ADD COLUMN department_id INTEGER",
            "ALTER TABLE grade_drafts ADD COLUMN section_id INTEGER",
            "ALTER TABLE grade_draft_items ADD COLUMN coursework REAL",
            "ALTER TABLE grade_draft_items ADD COLUMN midterm REAL",
            "ALTER TABLE grade_draft_items ADD COLUMN final_exam REAL",
            "ALTER TABLE grade_draft_items ADD COLUMN absent_midterm INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE grade_draft_items ADD COLUMN absent_final_exam INTEGER NOT NULL DEFAULT 0",
        ):
            try:
                cur.execute(stmt)
            except Exception:
                pass

        try:
            dgp_cols = [r[1] for r in cur.execute("PRAGMA table_info(department_graduation_policies)").fetchall()]
        except Exception:
            dgp_cols = []
        if dgp_cols:
            if "effective_from_term" not in dgp_cols:
                try:
                    cur.execute("ALTER TABLE department_graduation_policies ADD COLUMN effective_from_term TEXT DEFAULT ''")
                except Exception:
                    pass
            if "effective_from_year" not in dgp_cols:
                try:
                    cur.execute("ALTER TABLE department_graduation_policies ADD COLUMN effective_from_year TEXT DEFAULT ''")
                except Exception:
                    pass

        for stmt in (
            "ALTER TABLE courses ADD COLUMN category TEXT NOT NULL DEFAULT 'required'",
            "ALTER TABLE courses ADD COLUMN grading_mode TEXT NOT NULL DEFAULT 'partial_final'",
            "ALTER TABLE courses ADD COLUMN assessment_type TEXT NOT NULL DEFAULT 'theoretical'",
            "ALTER TABLE courses ADD COLUMN coursework_weight REAL",
            "ALTER TABLE courses ADD COLUMN midterm_weight REAL",
            "ALTER TABLE courses ADD COLUMN final_exam_weight REAL",
            "ALTER TABLE courses ADD COLUMN course_master_id INTEGER",
            "ALTER TABLE courses ADD COLUMN owning_department_id INTEGER",
        ):
            try:
                cur.execute(stmt)
            except Exception:
                pass

        try:
            eco = [r[1] for r in cur.execute("PRAGMA table_info(enrollment_plans)").fetchall()]
        except Exception:
            eco = []
        if "prereq_validation_json" not in eco:
            try:
                cur.execute("ALTER TABLE enrollment_plans ADD COLUMN prereq_validation_json TEXT")
            except Exception:
                pass
        if "prereq_ack_by_student" not in eco:
            try:
                cur.execute(
                    "ALTER TABLE enrollment_plans ADD COLUMN prereq_ack_by_student INTEGER NOT NULL DEFAULT 0"
                )
            except Exception:
                pass
        if "prereq_ack_reason" not in eco:
            try:
                cur.execute(
                    "ALTER TABLE enrollment_plans ADD COLUMN prereq_ack_reason TEXT DEFAULT ''"
                )
            except Exception:
                pass

        try:
            scols = [r[1] for r in cur.execute("PRAGMA table_info(schedule)").fetchall()]
        except Exception:
            scols = []
        if "instructor_id" not in scols:
            try:
                cur.execute("ALTER TABLE schedule ADD COLUMN instructor_id INTEGER")
            except Exception:
                pass
        if "program_course_id" not in scols:
            try:
                cur.execute("ALTER TABLE schedule ADD COLUMN program_course_id INTEGER")
            except Exception:
                pass
        if "department_id" not in scols:
            try:
                cur.execute("ALTER TABLE schedule ADD COLUMN department_id INTEGER")
            except Exception:
                pass
        if "teaching_group_id" not in scols:
            try:
                cur.execute("ALTER TABLE schedule ADD COLUMN teaching_group_id INTEGER")
            except Exception:
                pass

        try:
            rcols = [r[1] for r in cur.execute("PRAGMA table_info(registrations)").fetchall()]
        except Exception:
            rcols = []
        if "program_course_id" not in rcols:
            try:
                cur.execute("ALTER TABLE registrations ADD COLUMN program_course_id INTEGER")
            except Exception:
                pass
        if "teaching_group_id" not in rcols:
            try:
                cur.execute("ALTER TABLE registrations ADD COLUMN teaching_group_id INTEGER")
            except Exception:
                pass
        if "semester" not in rcols:
            try:
                cur.execute("ALTER TABLE registrations ADD COLUMN semester TEXT DEFAULT ''")
            except Exception:
                pass

        try:
            epi_cols = [r[1] for r in cur.execute("PRAGMA table_info(enrollment_plan_items)").fetchall()]
        except Exception:
            epi_cols = []
        if "teaching_group_id" not in epi_cols:
            try:
                cur.execute("ALTER TABLE enrollment_plan_items ADD COLUMN teaching_group_id INTEGER")
            except Exception:
                pass

        try:
            cecols = [r[1] for r in cur.execute("PRAGMA table_info(course_evaluations)").fetchall()]
        except Exception:
            cecols = []
        if "teaching_group_id" not in cecols:
            try:
                cur.execute("ALTER TABLE course_evaluations ADD COLUMN teaching_group_id INTEGER")
            except Exception:
                pass

        try:
            gdcols = [r[1] for r in cur.execute("PRAGMA table_info(grade_drafts)").fetchall()]
        except Exception:
            gdcols = []
        if "teaching_group_id" not in gdcols:
            try:
                cur.execute("ALTER TABLE grade_drafts ADD COLUMN teaching_group_id INTEGER")
            except Exception:
                pass

        try:
            gcols = [r[1] for r in cur.execute("PRAGMA table_info(grades)").fetchall()]
        except Exception:
            gcols = []
        if "program_course_id" not in gcols:
            try:
                cur.execute("ALTER TABLE grades ADD COLUMN program_course_id INTEGER")
            except Exception:
                pass
        if "course_master_id" not in gcols:
            try:
                cur.execute("ALTER TABLE grades ADD COLUMN course_master_id INTEGER")
            except Exception:
                pass
        try:
            pccols = [r[1] for r in cur.execute("PRAGMA table_info(program_courses)").fetchall()]
        except Exception:
            pccols = []
        if "plan_applicability" not in pccols:
            try:
                cur.execute(
                    "ALTER TABLE program_courses ADD COLUMN plan_applicability TEXT NOT NULL DEFAULT 'both'"
                )
            except Exception:
                pass
        if "requirement_scope" not in pccols:
            try:
                cur.execute(
                    "ALTER TABLE program_courses ADD COLUMN requirement_scope TEXT NOT NULL DEFAULT 'dept_common'"
                )
            except Exception:
                pass

        try:
            icols = [r[1] for r in cur.execute("PRAGMA table_info(instructors)").fetchall()]
        except Exception:
            icols = []
        if "department_id" not in icols:
            try:
                cur.execute("ALTER TABLE instructors ADD COLUMN department_id INTEGER")
            except Exception:
                pass
        if "external_scope" not in icols:
            try:
                cur.execute("ALTER TABLE instructors ADD COLUMN external_scope TEXT NOT NULL DEFAULT 'within_college'")
            except Exception:
                pass

        try:
            ccr_cols = [r[1] for r in cur.execute("PRAGMA table_info(course_closure_reports)").fetchall()]
            for col, stmt in (
                ("curriculum_coverage_percent", "ALTER TABLE course_closure_reports ADD COLUMN curriculum_coverage_percent INTEGER"),
                ("student_success_rate", "ALTER TABLE course_closure_reports ADD COLUMN student_success_rate REAL"),
                ("student_failure_rate", "ALTER TABLE course_closure_reports ADD COLUMN student_failure_rate REAL"),
                ("results_analysis", "ALTER TABLE course_closure_reports ADD COLUMN results_analysis TEXT DEFAULT ''"),
                ("challenges", "ALTER TABLE course_closure_reports ADD COLUMN challenges TEXT DEFAULT ''"),
                ("action_plan", "ALTER TABLE course_closure_reports ADD COLUMN action_plan TEXT DEFAULT ''"),
                ("ilo_achievement_percent", "ALTER TABLE course_closure_reports ADD COLUMN ilo_achievement_percent INTEGER"),
            ):
                if col not in ccr_cols:
                    try:
                        cur.execute(stmt)
                    except Exception:
                        pass
        except Exception as e:
            logger.warning("Could not migrate course_closure_reports columns: %s", e)

        try:
            from backend.services.course_closure_admin import ensure_admin_closed_status_allowed

            ensure_admin_closed_status_allowed(conn)
        except Exception as e:
            logger.warning("Could not allow admin_closed on course_closure_reports: %s", e)

        try:
            backfill_instructor_cross_department_data(conn)
        except Exception as e:
            logger.warning("backfill instructor cross-department (sqlite): %s", e)
        try:
            backfill_academic_pathway_defaults(conn)
        except Exception as e:
            logger.warning("backfill academic pathway (sqlite): %s", e)
        try:
            from backend.services.pathway_regulations import ensure_pathway_regulation_defaults

            ensure_pathway_regulation_defaults(conn)
        except Exception as e:
            logger.warning("ensure pathway regulations (sqlite): %s", e)
        try:
            from backend.core.plo_schema import ensure_plo_enhancement_schema

            ensure_plo_enhancement_schema(conn)
        except Exception as e:
            logger.warning("plo enhancement schema (sqlite): %s", e)
        try:
            from backend.core.course_master_catalog import ensure_course_master_catalog_schema

            ensure_course_master_catalog_schema(conn)
        except Exception as e:
            logger.warning("course_master catalog schema (sqlite): %s", e)
        try:
            from backend.core.academic_pathway import ensure_program_course_plan_schema

            ensure_program_course_plan_schema(conn)
        except Exception as e:
            logger.warning("program_courses plan schema (sqlite): %s", e)

        try:
            from backend.services.course_delivery import ensure_course_delivery_schema

            ensure_course_delivery_schema(conn)
        except Exception as e:
            logger.warning("course_delivery schema: %s", e)

        try:
            from backend.services.term_engine import (
                backfill_term_engine_from_legacy,
                ensure_term_engine_tables,
            )

            ensure_term_engine_tables(conn)
            backfill_term_engine_from_legacy(conn)
        except Exception as e:
            logger.warning("term_engine schema (sqlite): %s", e)

        try:
            from backend.boot.role_profiles_seed import migrate_legacy_admin_to_system, seed_role_profiles

            seed_role_profiles(conn)
            try:
                from config import ADMIN_USERNAME

                migrate_legacy_admin_to_system(conn, ADMIN_USERNAME)
            except Exception:
                migrate_legacy_admin_to_system(conn, None)
        except Exception as e:
            logger.warning("role profiles seed (sqlite): %s", e)

        conn.commit()
        logger.info("Database tables and indexes ensured")
