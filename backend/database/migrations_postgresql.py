"""ترقيات PostgreSQL التوافقية (طوارئ / Alembic 0002)."""
from __future__ import annotations

import logging
import os

from backend.database.backfills import (
    backfill_academic_pathway_defaults,
    backfill_instructor_cross_department_data,
)
from backend.database.connection import get_connection
from backend.database.schema_ddl import INDEXES

logger = logging.getLogger("backend.database")

def _ensure_tables_postgresql() -> None:
    """ترقيات خفيفة على PostgreSQL (إنشاء المخطط الأساسي عبر ``alembic upgrade head``)."""
    pg_alters = [
        "ALTER TABLE schedule ADD COLUMN IF NOT EXISTS id BIGINT",
        "ALTER TABLE students ADD COLUMN IF NOT EXISTS join_year TEXT",
        "ALTER TABLE students ADD COLUMN IF NOT EXISTS university_number TEXT",
        "ALTER TABLE students ADD COLUMN IF NOT EXISTS email TEXT",
        "ALTER TABLE students ADD COLUMN IF NOT EXISTS phone TEXT",
        "ALTER TABLE students ADD COLUMN IF NOT EXISTS updated_at TEXT",
        "ALTER TABLE students ADD COLUMN IF NOT EXISTS department_id BIGINT",
        "ALTER TABLE students ADD COLUMN IF NOT EXISTS admission_program_id BIGINT",
        "ALTER TABLE students ADD COLUMN IF NOT EXISTS current_program_id BIGINT",
        "ALTER TABLE students ADD COLUMN IF NOT EXISTS track_code TEXT",
        "ALTER TABLE accreditation_assessments ADD COLUMN IF NOT EXISTS program_id BIGINT",
        "ALTER TABLE accreditation_evidence ADD COLUMN IF NOT EXISTS program_id BIGINT",
        "ALTER TABLE accreditation_manual_inputs ADD COLUMN IF NOT EXISTS program_id BIGINT",
        "ALTER TABLE accreditation_improvement_plans ADD COLUMN IF NOT EXISTS program_id BIGINT",
        "ALTER TABLE accreditation_evidence_bindings ADD COLUMN IF NOT EXISTS program_id BIGINT",
        "ALTER TABLE students ADD COLUMN IF NOT EXISTS specialized_at_term TEXT",
        (
            "ALTER TABLE students ADD COLUMN IF NOT EXISTS enrollment_status TEXT "
            "NOT NULL DEFAULT 'active'"
        ),
        "ALTER TABLE students ADD COLUMN IF NOT EXISTS status_changed_at TEXT",
        "ALTER TABLE students ADD COLUMN IF NOT EXISTS status_reason TEXT",
        "ALTER TABLE students ADD COLUMN IF NOT EXISTS status_changed_term TEXT",
        "ALTER TABLE students ADD COLUMN IF NOT EXISTS status_changed_year TEXT",
        "ALTER TABLE students ADD COLUMN IF NOT EXISTS graduation_plan TEXT DEFAULT ''",
        "ALTER TABLE students ADD COLUMN IF NOT EXISTS join_term TEXT DEFAULT ''",
        "ALTER TABLE courses ADD COLUMN IF NOT EXISTS is_archived INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE courses ADD COLUMN IF NOT EXISTS course_master_id BIGINT",
        "ALTER TABLE courses ADD COLUMN IF NOT EXISTS owning_department_id BIGINT",
        "ALTER TABLE academic_calendar ADD COLUMN IF NOT EXISTS is_deleted INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE academic_calendar ADD COLUMN IF NOT EXISTS event_date_start TEXT",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS instructor_id INTEGER",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS department_id BIGINT",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_supervisor INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active INTEGER NOT NULL DEFAULT 1",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_college_quality_lead INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_system_account INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS role_profile_id BIGINT",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS display_title_ar TEXT",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_dept_quality_coordinator INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_secret TEXT",
        "ALTER TABLE survey_invites ADD COLUMN IF NOT EXISTS token_hash TEXT",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_enabled INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE courses ADD COLUMN IF NOT EXISTS category TEXT NOT NULL DEFAULT 'required'",
        "ALTER TABLE courses ADD COLUMN IF NOT EXISTS grading_mode TEXT NOT NULL DEFAULT 'partial_final'",
        "ALTER TABLE courses ADD COLUMN IF NOT EXISTS assessment_type TEXT NOT NULL DEFAULT 'theoretical'",
        "ALTER TABLE courses ADD COLUMN IF NOT EXISTS coursework_weight REAL",
        "ALTER TABLE courses ADD COLUMN IF NOT EXISTS midterm_weight REAL",
        "ALTER TABLE courses ADD COLUMN IF NOT EXISTS final_exam_weight REAL",
        "ALTER TABLE enrollment_plans ADD COLUMN IF NOT EXISTS prereq_validation_json TEXT",
        (
            "ALTER TABLE enrollment_plans ADD COLUMN IF NOT EXISTS prereq_ack_by_student "
            "INTEGER NOT NULL DEFAULT 0"
        ),
        "ALTER TABLE enrollment_plans ADD COLUMN IF NOT EXISTS prereq_ack_reason TEXT DEFAULT ''",
        "ALTER TABLE schedule ADD COLUMN IF NOT EXISTS instructor_id INTEGER",
        "ALTER TABLE schedule ADD COLUMN IF NOT EXISTS program_course_id BIGINT",
        "ALTER TABLE schedule ADD COLUMN IF NOT EXISTS department_id BIGINT",
        "ALTER TABLE schedule ADD COLUMN IF NOT EXISTS teaching_group_id BIGINT",
        """
        CREATE TABLE IF NOT EXISTS teaching_groups (
            id BIGSERIAL PRIMARY KEY,
            course_name TEXT NOT NULL,
            semester TEXT NOT NULL,
            department_id BIGINT NOT NULL REFERENCES departments(id),
            group_code TEXT NOT NULL DEFAULT '—',
            group_kind TEXT NOT NULL DEFAULT 'single' CHECK (group_kind IN ('single', 'split')),
            instructor_id BIGINT NOT NULL REFERENCES instructors(id),
            capacity_max INTEGER,
            program_course_id BIGINT,
            note TEXT DEFAULT '',
            is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (course_name, semester, department_id, group_code)
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_schedule_teaching_group ON schedule(teaching_group_id)",
        "CREATE INDEX IF NOT EXISTS idx_teaching_groups_semester ON teaching_groups(semester)",
        "CREATE INDEX IF NOT EXISTS idx_teaching_groups_course_sem ON teaching_groups(course_name, semester)",
        "CREATE INDEX IF NOT EXISTS idx_teaching_groups_dept_sem ON teaching_groups(department_id, semester)",
        "ALTER TABLE registrations ADD COLUMN IF NOT EXISTS program_course_id BIGINT",
        "ALTER TABLE registrations ADD COLUMN IF NOT EXISTS teaching_group_id BIGINT",
        "ALTER TABLE registrations ADD COLUMN IF NOT EXISTS semester TEXT DEFAULT ''",
        "ALTER TABLE term_windows ADD COLUMN IF NOT EXISTS grace_until TEXT",
        "ALTER TABLE enrollment_plan_items ADD COLUMN IF NOT EXISTS teaching_group_id BIGINT",
        "CREATE INDEX IF NOT EXISTS idx_regs_teaching_group ON registrations(teaching_group_id)",
        "ALTER TABLE course_evaluations ADD COLUMN IF NOT EXISTS teaching_group_id BIGINT",
        "CREATE INDEX IF NOT EXISTS idx_course_eval_teaching_group ON course_evaluations(teaching_group_id, semester)",
        "ALTER TABLE grade_drafts ADD COLUMN IF NOT EXISTS teaching_group_id BIGINT",
        "ALTER TABLE grades ADD COLUMN IF NOT EXISTS program_course_id BIGINT",
        "ALTER TABLE grades ADD COLUMN IF NOT EXISTS course_master_id BIGINT",
        "ALTER TABLE program_courses ADD COLUMN IF NOT EXISTS plan_applicability TEXT NOT NULL DEFAULT 'both'",
        "ALTER TABLE program_courses ADD COLUMN IF NOT EXISTS requirement_scope TEXT NOT NULL DEFAULT 'dept_common'",
        "ALTER TABLE students ADD COLUMN IF NOT EXISTS pathway_stage TEXT NOT NULL DEFAULT 'dept_admitted'",
        """
        CREATE TABLE IF NOT EXISTS pathway_regulation_items (
            id BIGSERIAL PRIMARY KEY,
            department_id BIGINT NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
            rule_key TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            category TEXT NOT NULL DEFAULT 'other',
            value_number DOUBLE PRECISION,
            value_text TEXT,
            sort_order INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (department_id, rule_key)
        )
        """,
        "ALTER TABLE department_graduation_policies ADD COLUMN IF NOT EXISTS effective_from_term TEXT DEFAULT ''",
        "ALTER TABLE department_graduation_policies ADD COLUMN IF NOT EXISTS effective_from_year TEXT DEFAULT ''",
        "ALTER TABLE instructors ADD COLUMN IF NOT EXISTS department_id BIGINT",
        "ALTER TABLE instructors ADD COLUMN IF NOT EXISTS external_scope TEXT NOT NULL DEFAULT 'within_college'",
        "ALTER TABLE grade_drafts ADD COLUMN IF NOT EXISTS section_id INTEGER",
        "ALTER TABLE grade_draft_items ADD COLUMN IF NOT EXISTS coursework REAL",
        "ALTER TABLE grade_draft_items ADD COLUMN IF NOT EXISTS midterm REAL",
        "ALTER TABLE grade_draft_items ADD COLUMN IF NOT EXISTS final_exam REAL",
        "ALTER TABLE grade_draft_items ADD COLUMN IF NOT EXISTS absent_midterm INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE grade_draft_items ADD COLUMN IF NOT EXISTS absent_final_exam INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE course_closure_reports ADD COLUMN IF NOT EXISTS curriculum_coverage_percent INTEGER",
        "ALTER TABLE course_closure_reports ADD COLUMN IF NOT EXISTS student_success_rate REAL",
        "ALTER TABLE course_closure_reports ADD COLUMN IF NOT EXISTS student_failure_rate REAL",
        "ALTER TABLE course_closure_reports ADD COLUMN IF NOT EXISTS results_analysis TEXT DEFAULT ''",
        "ALTER TABLE course_closure_reports ADD COLUMN IF NOT EXISTS challenges TEXT DEFAULT ''",
        "ALTER TABLE course_closure_reports ADD COLUMN IF NOT EXISTS action_plan TEXT DEFAULT ''",
        "ALTER TABLE course_closure_reports ADD COLUMN IF NOT EXISTS ilo_achievement_percent INTEGER",
        # أرقام معرفات طويلة (وطني/داخلي) تتجاوز INTEGER في PostgreSQL
        "ALTER TABLE users ALTER COLUMN instructor_id TYPE BIGINT USING instructor_id::bigint",
    ]
    pg_constraints = [
        (
            "users_student_requires_student_id_chk",
            """
            ALTER TABLE users
            ADD CONSTRAINT users_student_requires_student_id_chk
            CHECK (
                role <> 'student'
                OR (
                    student_id IS NOT NULL
                    AND btrim(student_id) <> ''
                )
            ) NOT VALID
            """,
        ),
        (
            "users_staff_requires_instructor_id_chk",
            """
            ALTER TABLE users
            ADD CONSTRAINT users_staff_requires_instructor_id_chk
            CHECK (
                role NOT IN ('instructor', 'head_of_department')
                OR instructor_id IS NOT NULL
            ) NOT VALID
            """,
        ),
    ]
    enable_lower_username_unique = (os.environ.get("ENABLE_USERS_LOWER_UNIQUE_IDX") or "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    with get_connection() as conn:
        cur = conn.cursor()
        # كل جملة في معاملة منفصلة حتى لا يُلغى تنفيذ الباقي بعد فشل واحد (PostgreSQL يرفض المتابعة في نفس المعاملة)
        for stmt in pg_alters:
            try:
                cur.execute(stmt)
                conn.commit()
            except Exception as e:
                logger.debug("postgresql alter skipped: %s", e)
                try:
                    conn.rollback()
                except Exception:
                    pass
        # مرحلة انتقالية: تعبئة id من rowid عند وجود بيانات قديمة.
        try:
            cur.execute("UPDATE schedule SET id = rowid WHERE id IS NULL")
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
        for idx_stmt in INDEXES:
            try:
                cur.execute(idx_stmt)
                conn.commit()
            except Exception as e:
                logger.warning("Could not create index on PostgreSQL: %s", e)
                try:
                    conn.rollback()
                except Exception:
                    pass
        for constraint_name, ddl in pg_constraints:
            try:
                exists_row = cur.execute(
                    """
                    SELECT 1
                    FROM pg_constraint
                    WHERE conname = %s
                    LIMIT 1
                    """,
                    (constraint_name,),
                ).fetchone()
                if not exists_row:
                    cur.execute(ddl)
                    conn.commit()
            except Exception as e:
                logger.warning("Could not create PostgreSQL constraint %s: %s", constraint_name, e)
                try:
                    conn.rollback()
                except Exception:
                    pass
        if enable_lower_username_unique:
            try:
                cur.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username_lower_unique ON users (lower(username))"
                )
                conn.commit()
            except Exception as e:
                logger.warning("Could not create optional unique lower(username) index: %s", e)
                try:
                    conn.rollback()
                except Exception:
                    pass
        else:
            logger.info("Skipping optional lower(username) unique index (ENABLE_USERS_LOWER_UNIQUE_IDX is off)")

        # الجداول الجديدة (Multi-department / programs / course master)
        # تُنشأ هنا كترقية توافقية لأن بعض البيئات لا تستخدم alembic بعد.
        try:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS departments (
                    id BIGSERIAL PRIMARY KEY,
                    code TEXT NOT NULL UNIQUE,
                    name_ar TEXT NOT NULL,
                    name_en TEXT DEFAULT '',
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    CONSTRAINT departments_active_chk CHECK (is_active IN (0, 1))
                )
                """
            )
            conn.commit()
        except Exception as e:
            logger.warning("Could not ensure departments on PostgreSQL: %s", e)
            try:
                conn.rollback()
            except Exception:
                pass
        try:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS programs (
                    id BIGSERIAL PRIMARY KEY,
                    department_id BIGINT,
                    code TEXT NOT NULL,
                    name_ar TEXT NOT NULL,
                    name_en TEXT DEFAULT '',
                    phase TEXT NOT NULL DEFAULT 'major',
                    track_group TEXT DEFAULT '',
                    min_total_units INTEGER DEFAULT 0,
                    rules_json TEXT DEFAULT '',
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (department_id, code),
                    CONSTRAINT programs_phase_chk CHECK (phase IN ('general', 'major')),
                    CONSTRAINT programs_active_chk CHECK (is_active IN (0, 1)),
                    CONSTRAINT programs_dept_fk FOREIGN KEY (department_id)
                        REFERENCES departments(id) ON DELETE SET NULL
                )
                """
            )
            conn.commit()
        except Exception as e:
            logger.warning("Could not ensure programs on PostgreSQL: %s", e)
            try:
                conn.rollback()
            except Exception:
                pass
        try:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS course_master (
                    id BIGSERIAL PRIMARY KEY,
                    title_ar TEXT NOT NULL,
                    title_en TEXT DEFAULT '',
                    description TEXT DEFAULT '',
                    default_units INTEGER DEFAULT 0,
                    grading_mode TEXT NOT NULL DEFAULT 'partial_final',
                    assessment_type TEXT NOT NULL DEFAULT 'theoretical',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    CONSTRAINT course_master_grading_mode_chk
                        CHECK (grading_mode IN ('partial_final', 'final_total_only'))
                )
                """
            )
            conn.commit()
        except Exception as e:
            logger.warning("Could not ensure course_master on PostgreSQL: %s", e)
            try:
                conn.rollback()
            except Exception:
                pass
        try:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS program_courses (
                    id BIGSERIAL PRIMARY KEY,
                    program_id BIGINT NOT NULL,
                    course_master_id BIGINT NOT NULL,
                    course_code TEXT NOT NULL,
                    course_name_override TEXT DEFAULT '',
                    plan_applicability TEXT NOT NULL DEFAULT 'both',
                    level_no INTEGER DEFAULT 0,
                    term_hint TEXT DEFAULT '',
                    units_override INTEGER,
                    category TEXT NOT NULL DEFAULT 'required',
                    is_required INTEGER NOT NULL DEFAULT 1,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (program_id, course_code),
                    CONSTRAINT program_courses_req_chk CHECK (is_required IN (0, 1)),
                    CONSTRAINT program_courses_active_chk CHECK (is_active IN (0, 1)),
                    CONSTRAINT program_courses_program_fk FOREIGN KEY (program_id)
                        REFERENCES programs(id) ON DELETE CASCADE,
                    CONSTRAINT program_courses_master_fk FOREIGN KEY (course_master_id)
                        REFERENCES course_master(id) ON DELETE CASCADE
                )
                """
            )
            conn.commit()
        except Exception as e:
            logger.warning("Could not ensure program_courses on PostgreSQL: %s", e)
            try:
                conn.rollback()
            except Exception:
                pass
        try:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS program_course_prereqs (
                    id BIGSERIAL PRIMARY KEY,
                    program_course_id BIGINT NOT NULL,
                    required_course_master_id BIGINT,
                    required_program_course_id BIGINT,
                    note TEXT DEFAULT '',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    CONSTRAINT program_course_prereqs_req_chk
                        CHECK (required_course_master_id IS NOT NULL OR required_program_course_id IS NOT NULL),
                    UNIQUE (program_course_id, required_course_master_id, required_program_course_id),
                    CONSTRAINT program_course_prereqs_pc_fk FOREIGN KEY (program_course_id)
                        REFERENCES program_courses(id) ON DELETE CASCADE,
                    CONSTRAINT program_course_prereqs_master_fk FOREIGN KEY (required_course_master_id)
                        REFERENCES course_master(id) ON DELETE CASCADE,
                    CONSTRAINT program_course_prereqs_req_pc_fk FOREIGN KEY (required_program_course_id)
                        REFERENCES program_courses(id) ON DELETE CASCADE
                )
                """
            )
            conn.commit()
        except Exception as e:
            logger.warning("Could not ensure program_course_prereqs on PostgreSQL: %s", e)
            try:
                conn.rollback()
            except Exception:
                pass
        try:
            cur.execute("DROP TABLE IF EXISTS program_course_sections CASCADE")
            conn.commit()
        except Exception as e:
            logger.warning("Could not drop program_course_sections on PostgreSQL: %s", e)
            try:
                conn.rollback()
            except Exception:
                pass
        try:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS faculty_section_axis_status (
                    section_id INTEGER NOT NULL,
                    instructor_id BIGINT NOT NULL,
                    axis_key TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (section_id, instructor_id, axis_key),
                    CONSTRAINT faculty_axis_status_chk CHECK (status IN ('pending', 'done', 'na'))
                )
                """
            )
            conn.commit()
        except Exception as e:
            logger.warning("Could not ensure faculty_section_axis_status on PostgreSQL: %s", e)
            try:
                conn.rollback()
            except Exception:
                pass
        try:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS faculty_course_plans (
                    section_id INTEGER NOT NULL,
                    instructor_id BIGINT NOT NULL,
                    week_no INTEGER NOT NULL,
                    week_topic TEXT DEFAULT '',
                    lecture_status TEXT NOT NULL DEFAULT 'planned',
                    resources_text TEXT DEFAULT '',
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_by TEXT DEFAULT '',
                    PRIMARY KEY (section_id, instructor_id, week_no),
                    CONSTRAINT faculty_course_plans_status_chk
                        CHECK (lecture_status IN ('planned', 'done', 'postponed', 'compensated'))
                )
                """
            )
            conn.commit()
        except Exception as e:
            logger.warning("Could not ensure faculty_course_plans on PostgreSQL: %s", e)
            try:
                conn.rollback()
            except Exception:
                pass
        try:
            cur.execute("ALTER TABLE faculty_course_plans ADD COLUMN linked_clo TEXT DEFAULT ''")
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
        try:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS faculty_course_announcements (
                    id BIGSERIAL PRIMARY KEY,
                    section_id INTEGER NOT NULL,
                    instructor_id BIGINT NOT NULL,
                    title TEXT DEFAULT '',
                    body TEXT NOT NULL,
                    announcement_type TEXT NOT NULL DEFAULT 'general',
                    lecture_date TEXT,
                    published_to_students INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    created_by TEXT DEFAULT '',
                    CONSTRAINT faculty_course_ann_type_chk
                        CHECK (announcement_type IN ('general', 'postponement', 'makeup', 'extra_lecture')),
                    CONSTRAINT faculty_course_ann_pub_chk
                        CHECK (published_to_students IN (0, 1))
                )
                """
            )
            conn.commit()
        except Exception as e:
            logger.warning("Could not ensure faculty_course_announcements on PostgreSQL: %s", e)
            try:
                conn.rollback()
            except Exception:
                pass
        try:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS faculty_course_syllabi (
                    section_id INTEGER NOT NULL,
                    instructor_id BIGINT NOT NULL,
                    syllabus_text TEXT DEFAULT '',
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_by TEXT DEFAULT '',
                    PRIMARY KEY (section_id, instructor_id)
                )
                """
            )
            conn.commit()
        except Exception as e:
            logger.warning("Could not ensure faculty_course_syllabi on PostgreSQL: %s", e)
            try:
                conn.rollback()
            except Exception:
                pass
        try:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS faculty_assignments (
                    id BIGSERIAL PRIMARY KEY,
                    instructor_id BIGINT NOT NULL,
                    assignment_type TEXT NOT NULL,
                    section_id INTEGER,
                    title TEXT NOT NULL DEFAULT '',
                    decision_ref TEXT NOT NULL DEFAULT '',
                    assignment_date TEXT DEFAULT CURRENT_TIMESTAMP,
                    start_date TEXT DEFAULT '',
                    end_date TEXT DEFAULT '',
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    created_by TEXT DEFAULT '',
                    CONSTRAINT faculty_assignments_type_chk
                        CHECK (assignment_type IN ('course', 'committee', 'service', 'quality', 'supervision')),
                    CONSTRAINT faculty_assignments_active_chk
                        CHECK (is_active IN (0, 1))
                )
                """
            )
            conn.commit()
        except Exception as e:
            logger.warning("Could not ensure faculty_assignments on PostgreSQL: %s", e)
            try:
                conn.rollback()
            except Exception:
                pass
        try:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS faculty_assignment_logs (
                    id BIGSERIAL PRIMARY KEY,
                    assignment_id BIGINT NOT NULL,
                    instructor_id BIGINT NOT NULL,
                    section_id INTEGER,
                    log_type TEXT NOT NULL,
                    notes TEXT NOT NULL DEFAULT '',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    created_by TEXT DEFAULT '',
                    approval_status TEXT NOT NULL DEFAULT 'draft',
                    approved_at TEXT,
                    approved_by TEXT,
                    CONSTRAINT faculty_logs_assignment_fk
                        FOREIGN KEY (assignment_id) REFERENCES faculty_assignments(id) ON DELETE CASCADE,
                    CONSTRAINT faculty_logs_type_chk
                        CHECK (log_type IN ('communication', 'supervision_session', 'quality_report')),
                    CONSTRAINT faculty_logs_approval_chk
                        CHECK (approval_status IN ('draft', 'submitted', 'approved', 'rejected'))
                )
                """
            )
            conn.commit()
        except Exception as e:
            logger.warning("Could not ensure faculty_assignment_logs on PostgreSQL: %s", e)
            try:
                conn.rollback()
            except Exception:
                pass
        try:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS grade_special_cases (
                    id BIGSERIAL PRIMARY KEY,
                    semester TEXT NOT NULL,
                    section_id INTEGER NOT NULL,
                    course_name TEXT NOT NULL,
                    instructor_id BIGINT NOT NULL,
                    student_id TEXT NOT NULL,
                    case_type TEXT NOT NULL,
                    reason TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'submitted',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    created_by TEXT DEFAULT '',
                    reviewed_at TEXT,
                    reviewed_by TEXT,
                    review_note TEXT DEFAULT '',
                    CONSTRAINT grade_special_case_type_chk
                        CHECK (case_type IN ('postponed', 'deprivation', 'cheating')),
                    CONSTRAINT grade_special_case_status_chk
                        CHECK (status IN ('submitted', 'approved', 'rejected'))
                )
                """
            )
            conn.commit()
        except Exception as e:
            logger.warning("Could not ensure grade_special_cases on PostgreSQL: %s", e)
            try:
                conn.rollback()
            except Exception:
                pass
        try:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS grade_correction_requests (
                    id BIGSERIAL PRIMARY KEY,
                    semester TEXT NOT NULL,
                    draft_id BIGINT NOT NULL,
                    course_name TEXT NOT NULL,
                    section_id INTEGER,
                    instructor_id BIGINT NOT NULL,
                    requested_by TEXT NOT NULL DEFAULT '',
                    reason TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'pending',
                    review_note TEXT NOT NULL DEFAULT '',
                    reviewed_by TEXT,
                    reviewed_at TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    CONSTRAINT grade_correction_status_chk
                        CHECK (status IN ('pending', 'approved', 'rejected'))
                )
                """
            )
            conn.commit()
        except Exception as e:
            logger.warning("Could not ensure grade_correction_requests on PostgreSQL: %s", e)
            try:
                conn.rollback()
            except Exception:
                pass
        try:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS course_closure_reports (
                    id BIGSERIAL PRIMARY KEY,
                    section_id INTEGER NOT NULL,
                    instructor_id BIGINT NOT NULL,
                    semester TEXT NOT NULL,
                    implementation_summary TEXT DEFAULT '',
                    improvement_notes TEXT DEFAULT '',
                    reflection_text TEXT DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'draft',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    created_by TEXT DEFAULT '',
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_by TEXT DEFAULT '',
                    approved_at TEXT,
                    approved_by TEXT,
                    review_note TEXT DEFAULT '',
                    CONSTRAINT course_closure_status_chk
                        CHECK (status IN ('draft', 'submitted', 'approved', 'rejected', 'admin_closed')),
                    UNIQUE (section_id, instructor_id, semester)
                )
                """
            )
            conn.commit()
        except Exception as e:
            logger.warning("Could not ensure course_closure_reports on PostgreSQL: %s", e)
            try:
                conn.rollback()
            except Exception:
                pass
        try:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS governance_audit_logs (
                    id BIGSERIAL PRIMARY KEY,
                    ts TEXT DEFAULT CURRENT_TIMESTAMP,
                    actor TEXT DEFAULT '',
                    action TEXT NOT NULL,
                    scope_type TEXT DEFAULT '',
                    scope_id TEXT DEFAULT '',
                    old_value TEXT DEFAULT '',
                    new_value TEXT DEFAULT '',
                    reason TEXT DEFAULT ''
                )
                """
            )
            conn.commit()
        except Exception as e:
            logger.warning("Could not ensure governance_audit_logs on PostgreSQL: %s", e)
            try:
                conn.rollback()
            except Exception:
                pass
        for _tbl, _ddl in (
            (
                "course_evaluations",
                """
                CREATE TABLE IF NOT EXISTS course_evaluations (
                    id BIGSERIAL PRIMARY KEY,
                    student_id TEXT NOT NULL,
                    section_id BIGINT,
                    course_name TEXT NOT NULL,
                    instructor_id BIGINT NOT NULL,
                    semester TEXT NOT NULL,
                    instructor_punctuality INTEGER,
                    course_clarity INTEGER,
                    assessment_fairness INTEGER,
                    material_relevance INTEGER,
                    communication_quality INTEGER,
                    comments TEXT DEFAULT '',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (student_id, section_id, semester)
                )
                """,
            ),
            (
                "supervisor_quality_reports",
                """
                CREATE TABLE IF NOT EXISTS supervisor_quality_reports (
                    id BIGSERIAL PRIMARY KEY,
                    supervisor_instructor_id BIGINT NOT NULL,
                    semester TEXT NOT NULL,
                    at_risk_students_count INTEGER DEFAULT 0,
                    intervention_actions TEXT DEFAULT '',
                    success_rate REAL,
                    submitted_by TEXT DEFAULT '',
                    submitted_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (supervisor_instructor_id, semester)
                )
                """,
            ),
            (
                "evaluation_survey_questions",
                """
                CREATE TABLE IF NOT EXISTS evaluation_survey_questions (
                    id BIGSERIAL PRIMARY KEY,
                    legacy_key TEXT,
                    label_ar TEXT NOT NULL,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
                    question_type TEXT NOT NULL DEFAULT 'likert_5',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """,
            ),
            (
                "evaluation_survey_answers",
                """
                CREATE TABLE IF NOT EXISTS evaluation_survey_answers (
                    id BIGSERIAL PRIMARY KEY,
                    evaluation_id BIGINT NOT NULL,
                    question_id BIGINT NOT NULL,
                    rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
                    UNIQUE (evaluation_id, question_id),
                    CONSTRAINT esa_eval_fk FOREIGN KEY (evaluation_id)
                        REFERENCES course_evaluations(id) ON DELETE CASCADE,
                    CONSTRAINT esa_question_fk FOREIGN KEY (question_id)
                        REFERENCES evaluation_survey_questions(id) ON DELETE RESTRICT
                )
                """,
            ),
            (
                "survey_templates",
                """
                CREATE TABLE IF NOT EXISTS survey_templates (
                    id BIGSERIAL PRIMARY KEY,
                    code TEXT NOT NULL UNIQUE,
                    title_ar TEXT NOT NULL,
                    respondent_role TEXT NOT NULL,
                    subject_type TEXT NOT NULL,
                    is_anonymous INTEGER NOT NULL DEFAULT 1 CHECK (is_anonymous IN (0, 1)),
                    min_aggregate INTEGER NOT NULL DEFAULT 3,
                    department_scoped INTEGER NOT NULL DEFAULT 0 CHECK (department_scoped IN (0, 1)),
                    legacy_course_eval INTEGER NOT NULL DEFAULT 0 CHECK (legacy_course_eval IN (0, 1)),
                    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """,
            ),
            (
                "survey_questions",
                """
                CREATE TABLE IF NOT EXISTS survey_questions (
                    id BIGSERIAL PRIMARY KEY,
                    template_id BIGINT NOT NULL REFERENCES survey_templates(id) ON DELETE CASCADE,
                    label_ar TEXT NOT NULL,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    question_type TEXT NOT NULL DEFAULT 'likert_5',
                    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """,
            ),
            (
                "survey_responses",
                """
                CREATE TABLE IF NOT EXISTS survey_responses (
                    id BIGSERIAL PRIMARY KEY,
                    template_id BIGINT NOT NULL REFERENCES survey_templates(id) ON DELETE RESTRICT,
                    template_code TEXT NOT NULL,
                    semester TEXT NOT NULL,
                    respondent_role TEXT NOT NULL,
                    respondent_id TEXT NOT NULL,
                    subject_type TEXT NOT NULL,
                    subject_id BIGINT NOT NULL DEFAULT 0,
                    department_id BIGINT,
                    comments TEXT DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'submitted',
                    submitted_by TEXT DEFAULT '',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    submitted_at TEXT,
                    UNIQUE (template_code, semester, respondent_role, respondent_id, subject_type, subject_id)
                )
                """,
            ),
            (
                "survey_answers",
                """
                CREATE TABLE IF NOT EXISTS survey_answers (
                    id BIGSERIAL PRIMARY KEY,
                    response_id BIGINT NOT NULL REFERENCES survey_responses(id) ON DELETE CASCADE,
                    question_id BIGINT NOT NULL REFERENCES survey_questions(id) ON DELETE RESTRICT,
                    rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
                    UNIQUE (response_id, question_id)
                )
                """,
            ),
            (
                "quality_metrics_snapshots",
                """
                CREATE TABLE IF NOT EXISTS quality_metrics_snapshots (
                    id BIGSERIAL PRIMARY KEY,
                    semester TEXT NOT NULL,
                    department_id BIGINT,
                    program_student_satisfaction REAL,
                    program_course_reports_completion REAL,
                    program_ilo_achievement REAL,
                    program_graduation_rate REAL,
                    institutional_faculty_qualifications REAL,
                    institutional_student_to_faculty_ratio REAL,
                    institutional_infrastructure_rating REAL,
                    overall_accreditation_score REAL,
                    accreditation_status TEXT DEFAULT '',
                    metrics_json TEXT DEFAULT '',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    created_by TEXT DEFAULT ''
                )
                """,
            ),
            (
                "quality_institutional_inputs",
                """
                CREATE TABLE IF NOT EXISTS quality_institutional_inputs (
                    id BIGSERIAL PRIMARY KEY,
                    semester TEXT NOT NULL,
                    department_id BIGINT,
                    faculty_qualifications_percent REAL,
                    infrastructure_rating REAL,
                    notes TEXT DEFAULT '',
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_by TEXT DEFAULT '',
                    UNIQUE (semester, department_id)
                )
                """,
            ),
            (
                "accreditation_standards",
                """
                CREATE TABLE IF NOT EXISTS accreditation_standards (
                    id BIGSERIAL PRIMARY KEY,
                    catalog_version TEXT NOT NULL DEFAULT 'QAA-2023.4-INST',
                    domain_code TEXT NOT NULL,
                    code TEXT NOT NULL,
                    title_ar TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    weight_percent REAL DEFAULT 0,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (catalog_version, code)
                )
                """,
            ),
            (
                "accreditation_indicators",
                """
                CREATE TABLE IF NOT EXISTS accreditation_indicators (
                    id BIGSERIAL PRIMARY KEY,
                    standard_id BIGINT NOT NULL,
                    code TEXT NOT NULL,
                    title_ar TEXT NOT NULL,
                    source_type TEXT NOT NULL DEFAULT 'manual',
                    target_hint_ar TEXT DEFAULT '',
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (standard_id, code),
                    CONSTRAINT accred_ind_std_fk FOREIGN KEY (standard_id)
                        REFERENCES accreditation_standards(id) ON DELETE CASCADE
                )
                """,
            ),
            (
                "accreditation_assessments",
                """
                CREATE TABLE IF NOT EXISTS accreditation_assessments (
                    id BIGSERIAL PRIMARY KEY,
                    semester TEXT NOT NULL,
                    department_id BIGINT,
                    program_id BIGINT,
                    indicator_id BIGINT NOT NULL,
                    score_percent REAL,
                    compliance_status TEXT NOT NULL DEFAULT 'not_started',
                    notes TEXT DEFAULT '',
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_by TEXT DEFAULT '',
                    UNIQUE (semester, department_id, indicator_id),
                    CONSTRAINT accred_asm_ind_fk FOREIGN KEY (indicator_id)
                        REFERENCES accreditation_indicators(id) ON DELETE CASCADE
                )
                """,
            ),
            (
                "accreditation_evidence",
                """
                CREATE TABLE IF NOT EXISTS accreditation_evidence (
                    id BIGSERIAL PRIMARY KEY,
                    semester TEXT NOT NULL,
                    department_id BIGINT,
                    indicator_id BIGINT,
                    standard_id BIGINT,
                    checklist_key TEXT,
                    title_ar TEXT NOT NULL DEFAULT '',
                    description TEXT DEFAULT '',
                    evidence_type TEXT NOT NULL DEFAULT 'file',
                    external_url TEXT DEFAULT '',
                    original_name TEXT DEFAULT '',
                    stored_path TEXT DEFAULT '',
                    mime_type TEXT DEFAULT '',
                    file_size BIGINT DEFAULT 0,
                    sha256 TEXT DEFAULT '',
                    uploaded_by TEXT DEFAULT '',
                    uploaded_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    CONSTRAINT accred_ev_ind_fk FOREIGN KEY (indicator_id)
                        REFERENCES accreditation_indicators(id) ON DELETE SET NULL,
                    CONSTRAINT accred_ev_std_fk FOREIGN KEY (standard_id)
                        REFERENCES accreditation_standards(id) ON DELETE SET NULL
                )
                """,
            ),
            (
                "accreditation_manual_inputs",
                """
                CREATE TABLE IF NOT EXISTS accreditation_manual_inputs (
                    id BIGSERIAL PRIMARY KEY,
                    semester TEXT NOT NULL,
                    department_id BIGINT,
                    classrooms_count INTEGER,
                    labs_count INTEGER,
                    facilities_rating REAL,
                    facilities_notes TEXT DEFAULT '',
                    annual_budget_million REAL,
                    budget_execution_percent REAL,
                    finance_notes TEXT DEFAULT '',
                    governance_meetings_count INTEGER,
                    policies_active_count INTEGER,
                    governance_notes TEXT DEFAULT '',
                    community_events_count INTEGER,
                    community_beneficiaries_count INTEGER,
                    research_outputs_count INTEGER,
                    community_notes TEXT DEFAULT '',
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_by TEXT DEFAULT '',
                    UNIQUE (semester, department_id)
                )
                """,
            ),
            (
                "accreditation_improvement_plans",
                """
                CREATE TABLE IF NOT EXISTS accreditation_improvement_plans (
                    id BIGSERIAL PRIMARY KEY,
                    semester TEXT NOT NULL,
                    department_id BIGINT,
                    indicator_id BIGINT,
                    title_ar TEXT NOT NULL,
                    action_ar TEXT DEFAULT '',
                    target_date TEXT DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'planned',
                    priority TEXT DEFAULT 'medium',
                    owner_ar TEXT DEFAULT '',
                    notes TEXT DEFAULT '',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_by TEXT DEFAULT '',
                    is_active INTEGER NOT NULL DEFAULT 1,
                    CONSTRAINT accred_plan_ind_fk FOREIGN KEY (indicator_id)
                        REFERENCES accreditation_indicators(id) ON DELETE SET NULL
                )
                """,
            ),
            (
                "accreditation_evidence_types",
                """
                CREATE TABLE IF NOT EXISTS accreditation_evidence_types (
                    id BIGSERIAL PRIMARY KEY,
                    code TEXT NOT NULL UNIQUE,
                    title_ar TEXT NOT NULL,
                    description_ar TEXT DEFAULT '',
                    category TEXT NOT NULL DEFAULT 'file',
                    source_module TEXT DEFAULT '',
                    source_ref TEXT DEFAULT '',
                    is_system INTEGER NOT NULL DEFAULT 0,
                    is_editable INTEGER NOT NULL DEFAULT 1,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """,
            ),
            (
                "accreditation_indicator_evidence_rules",
                """
                CREATE TABLE IF NOT EXISTS accreditation_indicator_evidence_rules (
                    id BIGSERIAL PRIMARY KEY,
                    catalog_version TEXT NOT NULL,
                    indicator_id BIGINT NOT NULL,
                    evidence_type_id BIGINT NOT NULL,
                    link_mode TEXT NOT NULL DEFAULT 'evidence',
                    is_required INTEGER NOT NULL DEFAULT 1,
                    weight_percent REAL DEFAULT 0,
                    config_json TEXT DEFAULT '',
                    notes_ar TEXT DEFAULT '',
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_by TEXT DEFAULT '',
                    UNIQUE (catalog_version, indicator_id, evidence_type_id),
                    CONSTRAINT accred_ev_rule_ind_fk FOREIGN KEY (indicator_id)
                        REFERENCES accreditation_indicators(id) ON DELETE CASCADE,
                    CONSTRAINT accred_ev_rule_type_fk FOREIGN KEY (evidence_type_id)
                        REFERENCES accreditation_evidence_types(id) ON DELETE CASCADE
                )
                """,
            ),
            (
                "accreditation_evidence_bindings",
                """
                CREATE TABLE IF NOT EXISTS accreditation_evidence_bindings (
                    id BIGSERIAL PRIMARY KEY,
                    semester TEXT NOT NULL,
                    department_id BIGINT,
                    indicator_id BIGINT NOT NULL,
                    evidence_type_id BIGINT NOT NULL,
                    rule_id BIGINT,
                    binding_kind TEXT NOT NULL,
                    source_ref TEXT NOT NULL DEFAULT '',
                    label_ar TEXT DEFAULT '',
                    notes_ar TEXT DEFAULT '',
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    created_by TEXT DEFAULT '',
                    updated_by TEXT DEFAULT '',
                    UNIQUE (semester, department_id, indicator_id, evidence_type_id),
                    CONSTRAINT accred_bind_ind_fk FOREIGN KEY (indicator_id)
                        REFERENCES accreditation_indicators(id) ON DELETE CASCADE,
                    CONSTRAINT accred_bind_type_fk FOREIGN KEY (evidence_type_id)
                        REFERENCES accreditation_evidence_types(id) ON DELETE CASCADE,
                    CONSTRAINT accred_bind_rule_fk FOREIGN KEY (rule_id)
                        REFERENCES accreditation_indicator_evidence_rules(id) ON DELETE SET NULL
                )
                """,
            ),
            (
                "program_learning_outcomes",
                """
                CREATE TABLE IF NOT EXISTS program_learning_outcomes (
                    id BIGSERIAL PRIMARY KEY,
                    program_id BIGINT NOT NULL,
                    code TEXT NOT NULL,
                    title_ar TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (program_id, code),
                    CONSTRAINT plo_program_fk FOREIGN KEY (program_id)
                        REFERENCES programs(id) ON DELETE CASCADE
                )
                """,
            ),
            (
                "program_course_learning_outcomes",
                """
                CREATE TABLE IF NOT EXISTS program_course_learning_outcomes (
                    program_course_id BIGINT NOT NULL,
                    outcome_id BIGINT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (program_course_id, outcome_id),
                    CONSTRAINT pclo_course_fk FOREIGN KEY (program_course_id)
                        REFERENCES program_courses(id) ON DELETE CASCADE,
                    CONSTRAINT pclo_outcome_fk FOREIGN KEY (outcome_id)
                        REFERENCES program_learning_outcomes(id) ON DELETE CASCADE
                )
                """,
            ),
            (
                "plo_course_master_links",
                """
                CREATE TABLE IF NOT EXISTS plo_course_master_links (
                    program_id BIGINT NOT NULL,
                    outcome_id BIGINT NOT NULL,
                    course_master_id BIGINT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (program_id, outcome_id, course_master_id),
                    CONSTRAINT plocm_program_fk FOREIGN KEY (program_id)
                        REFERENCES programs(id) ON DELETE CASCADE,
                    CONSTRAINT plocm_outcome_fk FOREIGN KEY (outcome_id)
                        REFERENCES program_learning_outcomes(id) ON DELETE CASCADE,
                    CONSTRAINT plocm_master_fk FOREIGN KEY (course_master_id)
                        REFERENCES course_master(id) ON DELETE CASCADE
                )
                """,
            ),
            (
                "section_ilo_assessments",
                """
                CREATE TABLE IF NOT EXISTS section_ilo_assessments (
                    id BIGSERIAL PRIMARY KEY,
                    section_id BIGINT NOT NULL,
                    instructor_id BIGINT NOT NULL,
                    semester TEXT NOT NULL,
                    outcome_id BIGINT NOT NULL,
                    achievement_percent INTEGER,
                    notes TEXT DEFAULT '',
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (section_id, instructor_id, semester, outcome_id),
                    CONSTRAINT silo_outcome_fk FOREIGN KEY (outcome_id)
                        REFERENCES program_learning_outcomes(id) ON DELETE CASCADE
                )
                """,
            ),
        ):
            try:
                cur.execute(_ddl)
                conn.commit()
            except Exception as e:
                logger.warning("Could not ensure %s on PostgreSQL: %s", _tbl, e)
                try:
                    conn.rollback()
                except Exception:
                    pass
        # جداول إسناد الأستاذ لأكثر من قسم + تكافؤ المقررات
        for ddl in (
            """
            CREATE TABLE IF NOT EXISTS instructor_department_assignments (
                id BIGSERIAL PRIMARY KEY,
                instructor_id BIGINT NOT NULL,
                department_id BIGINT NOT NULL,
                schedule_section_id BIGINT NOT NULL DEFAULT -1,
                semester TEXT NOT NULL DEFAULT '',
                is_primary INTEGER NOT NULL DEFAULT 0
                    CHECK (is_primary IN (0, 1)),
                is_active INTEGER NOT NULL DEFAULT 1
                    CHECK (is_active IN (0, 1)),
                migration_source TEXT DEFAULT 'manual',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (instructor_id, department_id, schedule_section_id, semester),
                CONSTRAINT ida_instructor_fk FOREIGN KEY (instructor_id)
                    REFERENCES instructors(id) ON DELETE CASCADE,
                CONSTRAINT ida_department_fk FOREIGN KEY (department_id)
                    REFERENCES departments(id) ON DELETE CASCADE
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS course_equivalence_groups (
                id BIGSERIAL PRIMARY KEY,
                group_key TEXT NOT NULL UNIQUE,
                title TEXT DEFAULT '',
                is_active INTEGER NOT NULL DEFAULT 1
                    CHECK (is_active IN (0, 1)),
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS course_equivalence_items (
                id BIGSERIAL PRIMARY KEY,
                group_id BIGINT NOT NULL,
                department_id BIGINT NOT NULL,
                course_name TEXT NOT NULL,
                course_code TEXT DEFAULT '',
                program_course_id BIGINT,
                is_active INTEGER NOT NULL DEFAULT 1
                    CHECK (is_active IN (0, 1)),
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (group_id, department_id, course_name),
                CONSTRAINT cei_group_fk FOREIGN KEY (group_id)
                    REFERENCES course_equivalence_groups(id) ON DELETE CASCADE,
                CONSTRAINT cei_department_fk FOREIGN KEY (department_id)
                    REFERENCES departments(id) ON DELETE CASCADE
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS department_graduation_policies (
                id BIGSERIAL PRIMARY KEY,
                department_id BIGINT NOT NULL,
                plan_code TEXT NOT NULL
                    CHECK (plan_code IN ('150', '155')),
                min_total_units INTEGER NOT NULL DEFAULT 0
                    CHECK (min_total_units >= 0),
                effective_from_term TEXT DEFAULT '',
                effective_from_year TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'draft'
                    CHECK (status IN ('draft','pending_approval','approved','rejected')),
                submitted_at TEXT,
                approved_at TEXT,
                rejected_at TEXT,
                rejection_reason TEXT DEFAULT '',
                created_by TEXT DEFAULT '',
                approved_by TEXT DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT dgp_department_fk FOREIGN KEY (department_id)
                    REFERENCES departments(id) ON DELETE CASCADE
            )
            """,
        ):
            try:
                cur.execute(ddl)
                conn.commit()
            except Exception as e:
                logger.warning("Could not ensure cross-department tables on PostgreSQL: %s", e)
                try:
                    conn.rollback()
                except Exception:
                    pass
        for idx_stmt in (
            "CREATE INDEX IF NOT EXISTS idx_ida_instructor_dept ON instructor_department_assignments(instructor_id, department_id)",
            "CREATE INDEX IF NOT EXISTS idx_ida_department_sem ON instructor_department_assignments(department_id, semester)",
            "CREATE INDEX IF NOT EXISTS idx_ida_schedule_section ON instructor_department_assignments(schedule_section_id)",
            "CREATE INDEX IF NOT EXISTS idx_course_equiv_items_dept ON course_equivalence_items(department_id)",
            "CREATE INDEX IF NOT EXISTS idx_course_equiv_items_course ON course_equivalence_items(course_name)",
            "CREATE INDEX IF NOT EXISTS idx_dept_grad_policy_dept_status ON department_graduation_policies(department_id, status)",
        ):
            try:
                cur.execute(idx_stmt)
                conn.commit()
            except Exception as e:
                logger.warning("Could not create cross-department index on PostgreSQL: %s", e)
                try:
                    conn.rollback()
                except Exception:
                    pass
        try:
            backfill_instructor_cross_department_data(conn)
        except Exception as e:
            logger.warning("backfill instructor cross-department (postgresql): %s", e)
        try:
            backfill_academic_pathway_defaults(conn)
            from backend.services.pathway_regulations import ensure_pathway_regulation_defaults

            ensure_pathway_regulation_defaults(conn)
        except Exception as e:
            logger.warning("backfill academic pathway (postgresql): %s", e)
            try:
                conn.rollback()
            except Exception:
                pass
        try:
            from backend.core.plo_schema import ensure_plo_enhancement_schema

            ensure_plo_enhancement_schema(conn)
        except Exception as e:
            logger.warning("plo enhancement schema (postgresql): %s", e)
        try:
            from backend.core.course_master_catalog import ensure_course_master_catalog_schema

            ensure_course_master_catalog_schema(conn)
        except Exception as e:
            logger.warning("course_master catalog schema (postgresql): %s", e)
        try:
            from backend.core.academic_pathway import ensure_program_course_plan_schema

            ensure_program_course_plan_schema(conn)
        except Exception as e:
            logger.warning("program_courses plan schema (postgresql): %s", e)
        try:
            cur.execute("DROP TABLE IF EXISTS program_course_sections CASCADE")
            conn.commit()
        except Exception as e:
            logger.warning("drop program_course_sections (postgresql): %s", e)
            try:
                conn.rollback()
            except Exception:
                pass
        try:
            from backend.services.course_delivery import ensure_course_delivery_schema

            ensure_course_delivery_schema(conn)
        except Exception as e:
            logger.warning("course_delivery schema (postgresql): %s", e)
        try:
            from backend.core.college_identity_schema import ensure_college_identity_schema

            ensure_college_identity_schema(conn)
        except Exception as e:
            logger.warning("college identity schema (postgresql): %s", e)
        try:
            from backend.services.multi_surveys import ensure_survey_platform_tables

            ensure_survey_platform_tables(conn)
        except Exception as e:
            logger.warning("survey platform schema (postgresql): %s", e)
        try:
            from backend.services.term_engine import ensure_term_engine_tables

            ensure_term_engine_tables(conn)
        except Exception as e:
            logger.warning("term_engine schema (postgresql): %s", e)
        try:
            from backend.services.term_engine import backfill_term_engine_from_legacy

            backfill_term_engine_from_legacy(conn)
        except Exception as e:
            logger.warning("term_engine backfill (postgresql): %s", e)
        try:
            from backend.boot.role_profiles_seed import migrate_legacy_admin_to_system, seed_role_profiles

            seed_role_profiles(conn)
            try:
                from config import ADMIN_USERNAME

                migrate_legacy_admin_to_system(conn, ADMIN_USERNAME)
            except Exception:
                migrate_legacy_admin_to_system(conn, None)
        except Exception as e:
            logger.warning("role profiles seed (postgresql): %s", e)
        try:
            from backend.services.course_closure_admin import ensure_admin_closed_status_allowed

            ensure_admin_closed_status_allowed(conn)
            conn.commit()
        except Exception as e:
            logger.warning("admin_closed status constraint (postgresql): %s", e)
            try:
                conn.rollback()
            except Exception:
                pass
    logger.info("PostgreSQL compatibility migrations applied")
