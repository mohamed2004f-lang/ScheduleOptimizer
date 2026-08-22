"""كتالوج DDL الأساسي (SQLite-shaped) وفهارسه — مصدر Alembic 0001."""
from __future__ import annotations

# ============================================
# تعريفات الجداول المحسّنة
# ============================================

TABLES_SCHEMA = {
    # ------------------------------------------------------------
    # Multi-department / programs (college-wide) — compatible add-on
    # ------------------------------------------------------------
    'departments': """
        CREATE TABLE IF NOT EXISTS departments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL UNIQUE,
            name_ar TEXT NOT NULL,
            name_en TEXT DEFAULT '',
            is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """,

    'programs': """
        CREATE TABLE IF NOT EXISTS programs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            department_id INTEGER,
            code TEXT NOT NULL,
            name_ar TEXT NOT NULL,
            name_en TEXT DEFAULT '',
            phase TEXT NOT NULL DEFAULT 'major'
                CHECK (phase IN ('general', 'major')),
            track_group TEXT DEFAULT '',
            min_total_units INTEGER DEFAULT 0 CHECK (min_total_units >= 0),
            rules_json TEXT DEFAULT '',
            is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (department_id, code),
            FOREIGN KEY (department_id) REFERENCES departments(id)
                ON DELETE SET NULL ON UPDATE CASCADE
        )
    """,

    'course_master': """
        CREATE TABLE IF NOT EXISTS course_master (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title_ar TEXT NOT NULL,
            title_en TEXT DEFAULT '',
            description TEXT DEFAULT '',
            default_units INTEGER DEFAULT 0 CHECK (default_units >= 0),
            grading_mode TEXT NOT NULL DEFAULT 'partial_final'
                CHECK (grading_mode IN ('partial_final','final_total_only')),
            assessment_type TEXT NOT NULL DEFAULT 'theoretical',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """,

    'program_courses': """
        CREATE TABLE IF NOT EXISTS program_courses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            program_id INTEGER NOT NULL,
            course_master_id INTEGER NOT NULL,
            course_code TEXT NOT NULL,
            course_name_override TEXT DEFAULT '',
            plan_applicability TEXT NOT NULL DEFAULT 'both',
            requirement_scope TEXT NOT NULL DEFAULT 'dept_common',
            level_no INTEGER DEFAULT 0 CHECK (level_no >= 0),
            term_hint TEXT DEFAULT '',
            units_override INTEGER,
            category TEXT NOT NULL DEFAULT 'required',
            is_required INTEGER NOT NULL DEFAULT 1 CHECK (is_required IN (0, 1)),
            is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (program_id, course_code),
            FOREIGN KEY (program_id) REFERENCES programs(id)
                ON DELETE CASCADE ON UPDATE CASCADE,
            FOREIGN KEY (course_master_id) REFERENCES course_master(id)
                ON DELETE CASCADE ON UPDATE CASCADE
        )
    """,

    # prerequisites at the "program course" level (allows same master course to have different prereqs per program)
    'program_course_prereqs': """
        CREATE TABLE IF NOT EXISTS program_course_prereqs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            program_course_id INTEGER NOT NULL,
            required_course_master_id INTEGER,
            required_program_course_id INTEGER,
            note TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            CHECK (
                required_course_master_id IS NOT NULL
                OR required_program_course_id IS NOT NULL
            ),
            UNIQUE (program_course_id, required_course_master_id, required_program_course_id),
            FOREIGN KEY (program_course_id) REFERENCES program_courses(id)
                ON DELETE CASCADE ON UPDATE CASCADE,
            FOREIGN KEY (required_course_master_id) REFERENCES course_master(id)
                ON DELETE CASCADE ON UPDATE CASCADE,
            FOREIGN KEY (required_program_course_id) REFERENCES program_courses(id)
                ON DELETE CASCADE ON UPDATE CASCADE
        )
    """,

    'teaching_groups': """
        CREATE TABLE IF NOT EXISTS teaching_groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_name TEXT NOT NULL,
            semester TEXT NOT NULL,
            department_id INTEGER NOT NULL,
            group_code TEXT NOT NULL DEFAULT '—',
            group_kind TEXT NOT NULL DEFAULT 'single' CHECK (group_kind IN ('single', 'split')),
            instructor_id INTEGER NOT NULL,
            capacity_max INTEGER,
            program_course_id INTEGER,
            note TEXT DEFAULT '',
            is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (course_name, semester, department_id, group_code),
            FOREIGN KEY (course_name) REFERENCES courses(course_name)
                ON DELETE CASCADE ON UPDATE CASCADE,
            FOREIGN KEY (department_id) REFERENCES departments(id)
                ON DELETE RESTRICT ON UPDATE CASCADE,
            FOREIGN KEY (instructor_id) REFERENCES instructors(id)
                ON DELETE RESTRICT ON UPDATE CASCADE
        )
    """,

    'students': """
        CREATE TABLE IF NOT EXISTS students (
            student_id TEXT PRIMARY KEY,
            student_name TEXT NOT NULL DEFAULT '',
            university_number TEXT,
            email TEXT,
            phone TEXT,
            join_year TEXT,
            department_id INTEGER,
            admission_program_id INTEGER,
            current_program_id INTEGER,
            track_code TEXT DEFAULT '',
            specialized_at_term TEXT DEFAULT '',
            enrollment_status TEXT NOT NULL DEFAULT 'active',
            status_changed_at TEXT,
            status_reason TEXT,
            status_changed_term TEXT,
            status_changed_year TEXT,
            graduation_plan TEXT DEFAULT '',
            pathway_stage TEXT NOT NULL DEFAULT 'dept_admitted',
            join_term TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (department_id) REFERENCES departments(id)
                ON DELETE SET NULL ON UPDATE CASCADE,
            FOREIGN KEY (admission_program_id) REFERENCES programs(id)
                ON DELETE SET NULL ON UPDATE CASCADE,
            FOREIGN KEY (current_program_id) REFERENCES programs(id)
                ON DELETE SET NULL ON UPDATE CASCADE
        )
    """,
    
    'courses': """
        CREATE TABLE IF NOT EXISTS courses (
            course_name TEXT PRIMARY KEY,
            course_code TEXT,
            course_master_id INTEGER,
            owning_department_id INTEGER,
            units INTEGER DEFAULT 0 CHECK (units >= 0),
            grading_mode TEXT NOT NULL DEFAULT 'partial_final' CHECK (grading_mode IN ('partial_final','final_total_only')),
            category TEXT NOT NULL DEFAULT 'required',
            assessment_type TEXT NOT NULL DEFAULT 'theoretical',
            coursework_weight REAL,
            midterm_weight REAL,
            final_exam_weight REAL,
            is_archived INTEGER NOT NULL DEFAULT 0 CHECK (is_archived IN (0, 1)),
            description TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (course_master_id) REFERENCES course_master(id)
                ON DELETE SET NULL ON UPDATE CASCADE,
            FOREIGN KEY (owning_department_id) REFERENCES departments(id)
                ON DELETE SET NULL ON UPDATE CASCADE
        )
    """,
    
    'schedule': """
        CREATE TABLE IF NOT EXISTS schedule (
            rowid INTEGER PRIMARY KEY AUTOINCREMENT,
            course_name TEXT NOT NULL,
            program_course_id INTEGER,
            department_id INTEGER,
            day TEXT NOT NULL,
            time TEXT NOT NULL,
            room TEXT DEFAULT '',
            instructor TEXT DEFAULT '',
            instructor_id INTEGER,
            semester TEXT DEFAULT '',
            teaching_group_id INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (course_name) REFERENCES courses(course_name) 
                ON DELETE CASCADE ON UPDATE CASCADE,
            FOREIGN KEY (program_course_id) REFERENCES program_courses(id)
                ON DELETE SET NULL ON UPDATE CASCADE,
            FOREIGN KEY (department_id) REFERENCES departments(id)
                ON DELETE SET NULL ON UPDATE CASCADE
        )
    """,
    
    'registrations': """
        CREATE TABLE IF NOT EXISTS registrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL,
            course_name TEXT NOT NULL,
            program_course_id INTEGER,
            teaching_group_id INTEGER,
            semester TEXT DEFAULT '',
            registered_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (student_id, course_name, semester),
            FOREIGN KEY (student_id) REFERENCES students(student_id) 
                ON DELETE CASCADE ON UPDATE CASCADE,
            FOREIGN KEY (course_name) REFERENCES courses(course_name) 
                ON DELETE CASCADE ON UPDATE CASCADE,
            FOREIGN KEY (program_course_id) REFERENCES program_courses(id)
                ON DELETE SET NULL ON UPDATE CASCADE
        )
    """,
    
    'grades': """
        CREATE TABLE IF NOT EXISTS grades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL,
            semester TEXT NOT NULL,
            course_name TEXT NOT NULL,
            program_course_id INTEGER,
            course_master_id INTEGER,
            course_code TEXT DEFAULT '',
            units INTEGER DEFAULT 0,
            grade REAL CHECK (grade IS NULL OR (grade >= 0 AND grade <= 100)),
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (student_id, semester, course_name),
            FOREIGN KEY (student_id) REFERENCES students(student_id) 
                ON DELETE CASCADE ON UPDATE CASCADE,
            FOREIGN KEY (course_name) REFERENCES courses(course_name) 
                ON DELETE SET NULL ON UPDATE CASCADE,
            FOREIGN KEY (program_course_id) REFERENCES program_courses(id)
                ON DELETE SET NULL ON UPDATE CASCADE,
            FOREIGN KEY (course_master_id) REFERENCES course_master(id)
                ON DELETE SET NULL ON UPDATE CASCADE
        )
    """,
    
    'prereqs': """
        CREATE TABLE IF NOT EXISTS prereqs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_name TEXT NOT NULL,
            required_course_name TEXT NOT NULL,
            UNIQUE (course_name, required_course_name),
            FOREIGN KEY (course_name) REFERENCES courses(course_name) 
                ON DELETE CASCADE ON UPDATE CASCADE,
            FOREIGN KEY (required_course_name) REFERENCES courses(course_name) 
                ON DELETE CASCADE ON UPDATE CASCADE
        )
    """,
    
    'exams': """
        CREATE TABLE IF NOT EXISTS exams (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exam_type TEXT NOT NULL CHECK (exam_type IN ('midterm', 'final', 'quiz')),
            exam_id INTEGER,
            course_name TEXT NOT NULL,
            exam_date TEXT,
            exam_time TEXT,
            room TEXT DEFAULT '',
            instructor TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (course_name) REFERENCES courses(course_name) 
                ON DELETE CASCADE ON UPDATE CASCADE
        )
    """,
    
    'exam_conflicts': """
        CREATE TABLE IF NOT EXISTS exam_conflicts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exam_type TEXT NOT NULL,
            student_id TEXT NOT NULL,
            exam_date TEXT,
            conflicting_courses TEXT,
            detected_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(student_id) 
                ON DELETE CASCADE ON UPDATE CASCADE
        )
    """,
    
    'conflict_report': """
        CREATE TABLE IF NOT EXISTS conflict_report (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL,
            day TEXT,
            time TEXT,
            conflicting_sections TEXT,
            detected_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(student_id) 
                ON DELETE CASCADE ON UPDATE CASCADE
        )
    """,
    
    'ignored_conflicts': """
        CREATE TABLE IF NOT EXISTS ignored_conflicts (
            student_id TEXT NOT NULL,
            day TEXT NOT NULL,
            time TEXT NOT NULL,
            conflicting_sections TEXT NOT NULL,
            ignored_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (student_id, day, time, conflicting_sections),
            FOREIGN KEY (student_id) REFERENCES students(student_id) 
                ON DELETE CASCADE ON UPDATE CASCADE
        )
    """,
    
    'optimized_schedule': """
        CREATE TABLE IF NOT EXISTS optimized_schedule (
            section_id INTEGER PRIMARY KEY,
            course_name TEXT,
            day TEXT,
            time TEXT,
            room TEXT,
            instructor TEXT,
            semester TEXT
        )
    """,
    
    'schedule_versions': """
        CREATE TABLE IF NOT EXISTS schedule_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            semester TEXT NOT NULL,
            version_no INTEGER NOT NULL DEFAULT 1,
            snapshot_json TEXT DEFAULT '',
            generated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            generated_by TEXT DEFAULT '',
            note TEXT DEFAULT '',
            is_published INTEGER NOT NULL DEFAULT 0,
            UNIQUE (semester, version_no)
        )
    """,

    'schedule_version_events': """
        CREATE TABLE IF NOT EXISTS schedule_version_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            schedule_version_id INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            event_time TEXT DEFAULT CURRENT_TIMESTAMP,
            actor TEXT DEFAULT '',
            details TEXT DEFAULT '',
            FOREIGN KEY (schedule_version_id) REFERENCES schedule_versions(id)
                ON DELETE CASCADE ON UPDATE CASCADE
        )
    """,

    'exam_schedule_versions': """
        CREATE TABLE IF NOT EXISTS exam_schedule_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exam_type TEXT NOT NULL CHECK (exam_type IN ('midterm', 'final')),
            semester TEXT NOT NULL,
            version_no INTEGER NOT NULL DEFAULT 1,
            snapshot_json TEXT DEFAULT '',
            generated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            generated_by TEXT DEFAULT '',
            note TEXT DEFAULT '',
            is_published INTEGER NOT NULL DEFAULT 0,
            UNIQUE (exam_type, semester, version_no)
        )
    """,

    'exam_schedule_version_events': """
        CREATE TABLE IF NOT EXISTS exam_schedule_version_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exam_schedule_version_id INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            event_time TEXT DEFAULT CURRENT_TIMESTAMP,
            actor TEXT DEFAULT '',
            details TEXT DEFAULT '',
            FOREIGN KEY (exam_schedule_version_id) REFERENCES exam_schedule_versions(id)
                ON DELETE CASCADE ON UPDATE CASCADE
        )
    """,
    
    'proposed_moves': """
        CREATE TABLE IF NOT EXISTS proposed_moves (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            section_id INTEGER,
            orig_day TEXT,
            orig_time TEXT,
            new_day TEXT,
            new_time TEXT,
            move_cost REAL
        )
    """,
    
    'grade_audit': """
        CREATE TABLE IF NOT EXISTS grade_audit (
            audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL,
            semester TEXT,
            course_name TEXT,
            old_grade REAL,
            new_grade REAL,
            changed_by TEXT DEFAULT 'system',
            ts TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(student_id) 
                ON DELETE CASCADE ON UPDATE CASCADE
        )
    """,
    
    'attendance_records': """
        CREATE TABLE IF NOT EXISTS attendance_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL,
            course_name TEXT NOT NULL,
            week_number INTEGER NOT NULL,
            status TEXT CHECK (status IN ('present', 'absent', 'late', 'excused')),
            note TEXT,
            recorded_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (student_id, course_name, week_number),
            FOREIGN KEY (student_id) REFERENCES students(student_id) 
                ON DELETE CASCADE ON UPDATE CASCADE,
            FOREIGN KEY (course_name) REFERENCES courses(course_name) 
                ON DELETE CASCADE ON UPDATE CASCADE
        )
    """,
    
    'registration_changes_log': """
        CREATE TABLE IF NOT EXISTS registration_changes_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL,
            student_name TEXT DEFAULT '',
            term TEXT DEFAULT '',
            course_name TEXT NOT NULL,
            course_code TEXT DEFAULT '',
            units INTEGER DEFAULT 0,
            action TEXT NOT NULL CHECK (action IN ('add','drop','change')),
            action_phase TEXT DEFAULT '',
            action_time TEXT DEFAULT CURRENT_TIMESTAMP,
            performed_by TEXT DEFAULT '',
            reason TEXT,
            notes TEXT,
            prev_state TEXT,
            new_state TEXT,
            FOREIGN KEY (student_id) REFERENCES students(student_id)
                ON DELETE CASCADE ON UPDATE CASCADE,
            FOREIGN KEY (course_name) REFERENCES courses(course_name)
                ON DELETE SET NULL ON UPDATE CASCADE
        )
    """
    ,
    'registration_signatures': """
        CREATE TABLE IF NOT EXISTS registration_signatures (
            student_id TEXT NOT NULL,
            term TEXT NOT NULL,
            student_signed INTEGER NOT NULL DEFAULT 0,
            signed_at TEXT,
            signature_note TEXT,
            form_file_id INTEGER,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_by TEXT DEFAULT '',
            PRIMARY KEY (student_id, term),
            FOREIGN KEY (student_id) REFERENCES students(student_id)
                ON DELETE CASCADE ON UPDATE CASCADE
        )
    """,

    'registration_form_files': """
        CREATE TABLE IF NOT EXISTS registration_form_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL,
            term TEXT NOT NULL,
            original_name TEXT DEFAULT '',
            stored_path TEXT NOT NULL,
            mime_type TEXT DEFAULT '',
            file_size INTEGER DEFAULT 0,
            sha256 TEXT DEFAULT '',
            uploaded_by TEXT DEFAULT '',
            uploaded_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(student_id)
                ON DELETE CASCADE ON UPDATE CASCADE
        )
    """,

    'registration_signature_events': """
        CREATE TABLE IF NOT EXISTS registration_signature_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL,
            term TEXT NOT NULL,
            form_version_id INTEGER,
            form_version_no INTEGER DEFAULT 0,
            student_signed INTEGER NOT NULL DEFAULT 0,
            signed_at TEXT,
            signature_note TEXT,
            form_file_id INTEGER,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_by TEXT DEFAULT '',
            UNIQUE(student_id, term, form_version_id),
            FOREIGN KEY (student_id) REFERENCES students(student_id)
                ON DELETE CASCADE ON UPDATE CASCADE
        )
    """,

    'registration_form_versions': """
        CREATE TABLE IF NOT EXISTS registration_form_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL,
            semester TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'actual',
            version_no INTEGER NOT NULL DEFAULT 1,
            snapshot_json TEXT DEFAULT '',
            generated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            generated_by TEXT DEFAULT '',
            UNIQUE(student_id, semester, source, version_no),
            FOREIGN KEY (student_id) REFERENCES students(student_id)
                ON DELETE CASCADE ON UPDATE CASCADE
        )
    """,

    'activity_log': """
        CREATE TABLE IF NOT EXISTS activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            actor TEXT,
            action TEXT NOT NULL,
            details TEXT
        )
    """,

    'enrollment_plans': """
        CREATE TABLE IF NOT EXISTS enrollment_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL,
            semester TEXT NOT NULL,
            status TEXT NOT NULL,
            rejection_reason TEXT,
            created_at TEXT,
            updated_at TEXT,
            prereq_validation_json TEXT,
            prereq_ack_by_student INTEGER NOT NULL DEFAULT 0,
            prereq_ack_reason TEXT DEFAULT '',
            FOREIGN KEY (student_id) REFERENCES students(student_id) ON DELETE CASCADE
        )
    """,

    'enrollment_plan_items': """
        CREATE TABLE IF NOT EXISTS enrollment_plan_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_id INTEGER NOT NULL,
            course_name TEXT NOT NULL,
            teaching_group_id INTEGER,
            FOREIGN KEY (plan_id) REFERENCES enrollment_plans(id) ON DELETE CASCADE
        )
    """,

    'users': """
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL,
            student_id TEXT,
            instructor_id INTEGER,
            department_id INTEGER,
            is_supervisor INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY (department_id) REFERENCES departments(id)
                ON DELETE SET NULL ON UPDATE CASCADE
        )
    """,

    'user_invites': """
        CREATE TABLE IF NOT EXISTS user_invites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            email TEXT NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            used_at TEXT
        )
    """,

    'notifications': """
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user TEXT NOT NULL,
            title TEXT NOT NULL,
            body TEXT,
            is_read INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """,

    'system_settings': """
        CREATE TABLE IF NOT EXISTS system_settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """,

    'academic_calendar': """
        CREATE TABLE IF NOT EXISTS academic_calendar (
            academic_year TEXT NOT NULL,
            term TEXT NOT NULL,
            item_no INTEGER NOT NULL,
            title TEXT NOT NULL,
            event_date TEXT,
            event_date_start TEXT,
            is_deleted INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT,
            PRIMARY KEY (academic_year, term, item_no)
        )
    """,

    'term_master': """
        CREATE TABLE IF NOT EXISTS term_master (
            term_key TEXT PRIMARY KEY,
            season TEXT NOT NULL CHECK (season IN ('fall', 'spring')),
            academic_year TEXT NOT NULL,
            term_name_ar TEXT NOT NULL DEFAULT '',
            ops_year_label TEXT NOT NULL DEFAULT '',
            ops_label TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'planned',
            is_current INTEGER NOT NULL DEFAULT 0 CHECK (is_current IN (0, 1)),
            created_at TEXT,
            updated_at TEXT
        )
    """,

    'term_windows': """
        CREATE TABLE IF NOT EXISTS term_windows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            term_key TEXT NOT NULL,
            window_key TEXT NOT NULL,
            kind TEXT NOT NULL DEFAULT 'window',
            label_ar TEXT NOT NULL DEFAULT '',
            closure_stage TEXT NOT NULL DEFAULT '',
            starts_at TEXT,
            ends_at TEXT,
            status TEXT NOT NULL DEFAULT 'unset',
            calendar_item_no INTEGER,
            source TEXT NOT NULL DEFAULT 'calendar',
            grace_until TEXT,
            updated_at TEXT,
            UNIQUE (term_key, window_key)
        )
    """,

    'academic_calendar_versions': """
        CREATE TABLE IF NOT EXISTS academic_calendar_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            term_key TEXT NOT NULL,
            version_no INTEGER NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('draft', 'published', 'amended')),
            snapshot_json TEXT NOT NULL DEFAULT '[]',
            reason TEXT NOT NULL DEFAULT '',
            created_at TEXT,
            created_by TEXT NOT NULL DEFAULT '',
            UNIQUE (term_key, version_no)
        )
    """,

    'term_amendment_log': """
        CREATE TABLE IF NOT EXISTS term_amendment_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            term_key TEXT NOT NULL,
            window_key TEXT NOT NULL DEFAULT '',
            effect TEXT NOT NULL,
            apply_ops INTEGER NOT NULL DEFAULT 0,
            old_starts_at TEXT,
            old_ends_at TEXT,
            new_starts_at TEXT,
            new_ends_at TEXT,
            reason TEXT NOT NULL DEFAULT '',
            actor TEXT NOT NULL DEFAULT '',
            created_at TEXT
        )
    """,

    'term_registration_archives': """
        CREATE TABLE IF NOT EXISTS term_registration_archives (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            archived_term TEXT NOT NULL,
            student_id TEXT NOT NULL,
            course_name TEXT NOT NULL,
            program_course_id INTEGER,
            teaching_group_id INTEGER,
            semester TEXT DEFAULT '',
            archived_at TEXT,
            archived_by TEXT NOT NULL DEFAULT '',
            reason TEXT NOT NULL DEFAULT ''
        )
    """,

    'term_operation_exceptions': """
        CREATE TABLE IF NOT EXISTS term_operation_exceptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL,
            term_key TEXT NOT NULL DEFAULT '',
            operation TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'proposed'
                CHECK (status IN ('proposed', 'approved', 'rejected')),
            reason TEXT NOT NULL DEFAULT '',
            proposed_by TEXT NOT NULL DEFAULT '',
            approved_by TEXT NOT NULL DEFAULT '',
            expires_at TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    """,

    'term_course_offerings': """
        CREATE TABLE IF NOT EXISTS term_course_offerings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            term_key TEXT NOT NULL,
            course_name TEXT NOT NULL,
            department_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'offered'
                CHECK (status IN ('offered', 'cancelled')),
            proposed_instructor_id INTEGER,
            created_at TEXT,
            created_by TEXT NOT NULL DEFAULT '',
            updated_at TEXT,
            UNIQUE (term_key, course_name, department_id)
        )
    """,

    'term_offering_state': """
        CREATE TABLE IF NOT EXISTS term_offering_state (
            term_key TEXT NOT NULL,
            department_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'draft'
                CHECK (status IN ('draft', 'published')),
            published_at TEXT,
            published_by TEXT NOT NULL DEFAULT '',
            updated_at TEXT,
            updated_by TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (term_key, department_id)
        )
    """,

    'instructors': """
        CREATE TABLE IF NOT EXISTS instructors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            type TEXT NOT NULL DEFAULT 'internal',
            email TEXT,
            department_id INTEGER,
            external_scope TEXT NOT NULL DEFAULT 'within_college'
                CHECK (external_scope IN ('within_college','outside_college','outside_university')),
            is_active INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY (department_id) REFERENCES departments(id)
                ON DELETE SET NULL ON UPDATE CASCADE
        )
    """,

    'student_supervisor': """
        CREATE TABLE IF NOT EXISTS student_supervisor (
            student_id TEXT NOT NULL,
            instructor_id INTEGER NOT NULL,
            PRIMARY KEY (student_id, instructor_id),
            FOREIGN KEY (student_id) REFERENCES students(student_id) ON DELETE CASCADE,
            FOREIGN KEY (instructor_id) REFERENCES instructors(id) ON DELETE CASCADE
        )
    """,

    'student_exceptions': """
        CREATE TABLE IF NOT EXISTS student_exceptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL,
            type TEXT NOT NULL,
            note TEXT,
            created_by TEXT,
            created_at TEXT,
            is_active INTEGER NOT NULL DEFAULT 1
        )
    """,

    'academic_rules': """
        CREATE TABLE IF NOT EXISTS academic_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rule_key TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL,
            description TEXT,
            category TEXT,
            value_number REAL,
            value_text TEXT,
            is_active INTEGER NOT NULL DEFAULT 1
        )
    """,

    'pathway_regulation_items': """
        CREATE TABLE IF NOT EXISTS pathway_regulation_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            department_id INTEGER NOT NULL,
            rule_key TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            category TEXT NOT NULL DEFAULT 'other',
            value_number REAL,
            value_text TEXT,
            sort_order INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (department_id, rule_key),
            FOREIGN KEY (department_id) REFERENCES departments(id)
                ON DELETE CASCADE ON UPDATE CASCADE
        )
    """,

    'registration_requests': """
        CREATE TABLE IF NOT EXISTS registration_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL,
            term TEXT DEFAULT '',
            course_name TEXT NOT NULL,
            action TEXT NOT NULL CHECK (action IN ('add','drop')),
            status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected','executed')),
            requested_by TEXT DEFAULT '',
            reviewed_by TEXT DEFAULT '',
            request_reason TEXT,
            review_note TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(student_id) ON DELETE CASCADE,
            FOREIGN KEY (course_name) REFERENCES courses(course_name) ON DELETE SET NULL
        )
    """,

    'app_settings': """
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value_json TEXT,
            updated_at TEXT,
            updated_by TEXT
        )
    """,

    'grade_drafts': """
        CREATE TABLE IF NOT EXISTS grade_drafts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            semester TEXT NOT NULL,
            course_name TEXT NOT NULL,
            section_id INTEGER,
            instructor_id INTEGER NOT NULL,
            grading_mode TEXT NOT NULL DEFAULT 'partial_final' CHECK (grading_mode IN ('partial_final','final_total_only')),
            status TEXT NOT NULL DEFAULT 'Draft' CHECK (status IN ('Draft','Submitted','Approved','Rejected')),
            created_at TEXT,
            updated_at TEXT,
            submitted_at TEXT,
            approved_at TEXT,
            approved_by TEXT,
            note TEXT,
            UNIQUE (semester, course_name, instructor_id, section_id)
        )
    """,

    'grade_draft_items': """
        CREATE TABLE IF NOT EXISTS grade_draft_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            draft_id INTEGER NOT NULL,
            student_id TEXT NOT NULL,
            coursework REAL CHECK (coursework IS NULL OR (coursework >= 0 AND coursework <= 40)),
            midterm REAL CHECK (midterm IS NULL OR (midterm >= 0 AND midterm <= 20)),
            final_exam REAL CHECK (final_exam IS NULL OR (final_exam >= 0 AND final_exam <= 40)),
            absent_midterm INTEGER NOT NULL DEFAULT 0 CHECK (absent_midterm IN (0, 1)),
            absent_final_exam INTEGER NOT NULL DEFAULT 0 CHECK (absent_final_exam IN (0, 1)),
            partial REAL CHECK (partial IS NULL OR (partial >= 0 AND partial <= 100)),
            final REAL CHECK (final IS NULL OR (final >= 0 AND final <= 100)),
            total REAL CHECK (total IS NULL OR (total >= 0 AND total <= 100)),
            computed_total REAL CHECK (computed_total IS NULL OR (computed_total >= 0 AND computed_total <= 100)),
            updated_at TEXT,
            UNIQUE (draft_id, student_id),
            FOREIGN KEY (draft_id) REFERENCES grade_drafts(id) ON DELETE CASCADE
        )
    """,
    'grade_special_cases': """
        CREATE TABLE IF NOT EXISTS grade_special_cases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            semester TEXT NOT NULL,
            section_id INTEGER NOT NULL,
            course_name TEXT NOT NULL,
            instructor_id INTEGER NOT NULL,
            student_id TEXT NOT NULL,
            case_type TEXT NOT NULL
                CHECK (case_type IN ('postponed', 'deprivation', 'cheating')),
            reason TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'submitted'
                CHECK (status IN ('submitted', 'approved', 'rejected')),
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            created_by TEXT DEFAULT '',
            reviewed_at TEXT,
            reviewed_by TEXT,
            review_note TEXT DEFAULT ''
        )
    """,
    'grade_correction_requests': """
        CREATE TABLE IF NOT EXISTS grade_correction_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            semester TEXT NOT NULL,
            draft_id INTEGER NOT NULL,
            course_name TEXT NOT NULL,
            section_id INTEGER,
            instructor_id INTEGER NOT NULL,
            requested_by TEXT NOT NULL DEFAULT '',
            reason TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'approved', 'rejected')),
            review_note TEXT NOT NULL DEFAULT '',
            reviewed_by TEXT,
            reviewed_at TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (draft_id) REFERENCES grade_drafts(id) ON DELETE CASCADE
        )
    """,

    'faculty_section_axis_status': """
        CREATE TABLE IF NOT EXISTS faculty_section_axis_status (
            section_id INTEGER NOT NULL,
            instructor_id INTEGER NOT NULL,
            axis_key TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'done', 'na')),
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (section_id, instructor_id, axis_key)
        )
    """,

    'faculty_course_plans': """
        CREATE TABLE IF NOT EXISTS faculty_course_plans (
            section_id INTEGER NOT NULL,
            instructor_id INTEGER NOT NULL,
            week_no INTEGER NOT NULL,
            week_topic TEXT DEFAULT '',
            lecture_status TEXT NOT NULL DEFAULT 'planned'
                CHECK (lecture_status IN ('planned', 'done', 'postponed', 'compensated')),
            resources_text TEXT DEFAULT '',
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_by TEXT DEFAULT '',
            PRIMARY KEY (section_id, instructor_id, week_no)
        )
    """,

    'faculty_course_announcements': """
        CREATE TABLE IF NOT EXISTS faculty_course_announcements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            section_id INTEGER NOT NULL,
            instructor_id INTEGER NOT NULL,
            title TEXT DEFAULT '',
            body TEXT NOT NULL,
            announcement_type TEXT NOT NULL DEFAULT 'general'
                CHECK (announcement_type IN ('general', 'postponement', 'makeup', 'extra_lecture')),
            lecture_date TEXT,
            published_to_students INTEGER NOT NULL DEFAULT 1
                CHECK (published_to_students IN (0, 1)),
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            created_by TEXT DEFAULT ''
        )
    """,

    'faculty_course_syllabi': """
        CREATE TABLE IF NOT EXISTS faculty_course_syllabi (
            section_id INTEGER NOT NULL,
            instructor_id INTEGER NOT NULL,
            syllabus_text TEXT DEFAULT '',
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_by TEXT DEFAULT '',
            PRIMARY KEY (section_id, instructor_id)
        )
    """,
    'faculty_assignments': """
        CREATE TABLE IF NOT EXISTS faculty_assignments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            instructor_id INTEGER NOT NULL,
            assignment_type TEXT NOT NULL
                CHECK (assignment_type IN ('course', 'committee', 'service', 'quality', 'supervision')),
            section_id INTEGER,
            title TEXT NOT NULL DEFAULT '',
            decision_ref TEXT NOT NULL DEFAULT '',
            assignment_date TEXT DEFAULT CURRENT_TIMESTAMP,
            start_date TEXT DEFAULT '',
            end_date TEXT DEFAULT '',
            is_active INTEGER NOT NULL DEFAULT 1
                CHECK (is_active IN (0, 1)),
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            created_by TEXT DEFAULT ''
        )
    """,
    'faculty_assignment_logs': """
        CREATE TABLE IF NOT EXISTS faculty_assignment_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            assignment_id INTEGER NOT NULL,
            instructor_id INTEGER NOT NULL,
            section_id INTEGER,
            log_type TEXT NOT NULL
                CHECK (log_type IN ('communication', 'supervision_session', 'quality_report')),
            notes TEXT NOT NULL DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            created_by TEXT DEFAULT '',
            approval_status TEXT NOT NULL DEFAULT 'draft'
                CHECK (approval_status IN ('draft', 'submitted', 'approved', 'rejected')),
            approved_at TEXT,
            approved_by TEXT,
            FOREIGN KEY (assignment_id) REFERENCES faculty_assignments(id) ON DELETE CASCADE
        )
    """,
    'course_closure_reports': """
        CREATE TABLE IF NOT EXISTS course_closure_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            section_id INTEGER NOT NULL,
            instructor_id INTEGER NOT NULL,
            semester TEXT NOT NULL,
            implementation_summary TEXT DEFAULT '',
            improvement_notes TEXT DEFAULT '',
            reflection_text TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'draft'
                CHECK (status IN ('draft', 'submitted', 'approved', 'rejected', 'admin_closed')),
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            created_by TEXT DEFAULT '',
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_by TEXT DEFAULT '',
            approved_at TEXT,
            approved_by TEXT,
            review_note TEXT DEFAULT '',
            UNIQUE (section_id, instructor_id, semester)
        )
    """,
    'governance_audit_logs': """
        CREATE TABLE IF NOT EXISTS governance_audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT DEFAULT CURRENT_TIMESTAMP,
            actor TEXT DEFAULT '',
            action TEXT NOT NULL,
            scope_type TEXT DEFAULT '',
            scope_id TEXT DEFAULT '',
            old_value TEXT DEFAULT '',
            new_value TEXT DEFAULT '',
            reason TEXT DEFAULT ''
        )
    """,

    'course_evaluations': """
        CREATE TABLE IF NOT EXISTS course_evaluations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL,
            section_id INTEGER,
            teaching_group_id INTEGER,
            course_name TEXT NOT NULL,
            instructor_id INTEGER NOT NULL,
            semester TEXT NOT NULL,
            instructor_punctuality INTEGER CHECK (instructor_punctuality BETWEEN 1 AND 5),
            course_clarity INTEGER CHECK (course_clarity BETWEEN 1 AND 5),
            assessment_fairness INTEGER CHECK (assessment_fairness BETWEEN 1 AND 5),
            material_relevance INTEGER CHECK (material_relevance BETWEEN 1 AND 5),
            communication_quality INTEGER CHECK (communication_quality BETWEEN 1 AND 5),
            comments TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (student_id, section_id, semester),
            FOREIGN KEY (student_id) REFERENCES students(student_id)
                ON DELETE CASCADE ON UPDATE CASCADE
        )
    """,

    'evaluation_survey_questions': """
        CREATE TABLE IF NOT EXISTS evaluation_survey_questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            legacy_key TEXT,
            label_ar TEXT NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
            question_type TEXT NOT NULL DEFAULT 'likert_5',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """,

    'evaluation_survey_answers': """
        CREATE TABLE IF NOT EXISTS evaluation_survey_answers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            evaluation_id INTEGER NOT NULL,
            question_id INTEGER NOT NULL,
            rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
            UNIQUE (evaluation_id, question_id),
            FOREIGN KEY (evaluation_id) REFERENCES course_evaluations(id)
                ON DELETE CASCADE ON UPDATE CASCADE,
            FOREIGN KEY (question_id) REFERENCES evaluation_survey_questions(id)
                ON DELETE RESTRICT ON UPDATE CASCADE
        )
    """,

    'survey_templates': """
        CREATE TABLE IF NOT EXISTS survey_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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

    'survey_questions': """
        CREATE TABLE IF NOT EXISTS survey_questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            template_id INTEGER NOT NULL,
            label_ar TEXT NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 0,
            question_type TEXT NOT NULL DEFAULT 'likert_5',
            is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (template_id) REFERENCES survey_templates(id) ON DELETE CASCADE
        )
    """,

    'survey_responses': """
        CREATE TABLE IF NOT EXISTS survey_responses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            template_id INTEGER NOT NULL,
            template_code TEXT NOT NULL,
            semester TEXT NOT NULL,
            respondent_role TEXT NOT NULL,
            respondent_id TEXT NOT NULL,
            subject_type TEXT NOT NULL,
            subject_id INTEGER NOT NULL DEFAULT 0,
            department_id INTEGER,
            comments TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'submitted',
            submitted_by TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            submitted_at TEXT,
            UNIQUE (template_code, semester, respondent_role, respondent_id, subject_type, subject_id),
            FOREIGN KEY (template_id) REFERENCES survey_templates(id) ON DELETE RESTRICT
        )
    """,

    'survey_answers': """
        CREATE TABLE IF NOT EXISTS survey_answers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            response_id INTEGER NOT NULL,
            question_id INTEGER NOT NULL,
            rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
            UNIQUE (response_id, question_id),
            FOREIGN KEY (response_id) REFERENCES survey_responses(id) ON DELETE CASCADE,
            FOREIGN KEY (question_id) REFERENCES survey_questions(id) ON DELETE RESTRICT
        )
    """,

    'supervisor_quality_reports': """
        CREATE TABLE IF NOT EXISTS supervisor_quality_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            supervisor_instructor_id INTEGER NOT NULL,
            semester TEXT NOT NULL,
            at_risk_students_count INTEGER DEFAULT 0,
            intervention_actions TEXT DEFAULT '',
            success_rate REAL,
            submitted_by TEXT DEFAULT '',
            submitted_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (supervisor_instructor_id, semester)
        )
    """,

    'quality_metrics_snapshots': """
        CREATE TABLE IF NOT EXISTS quality_metrics_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            semester TEXT NOT NULL,
            department_id INTEGER,
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

    'quality_institutional_inputs': """
        CREATE TABLE IF NOT EXISTS quality_institutional_inputs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            semester TEXT NOT NULL,
            department_id INTEGER,
            faculty_qualifications_percent REAL,
            infrastructure_rating REAL,
            notes TEXT DEFAULT '',
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_by TEXT DEFAULT '',
            UNIQUE (semester, department_id)
        )
    """,

    'accreditation_standards': """
        CREATE TABLE IF NOT EXISTS accreditation_standards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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

    'accreditation_indicators': """
        CREATE TABLE IF NOT EXISTS accreditation_indicators (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            standard_id INTEGER NOT NULL,
            code TEXT NOT NULL,
            title_ar TEXT NOT NULL,
            source_type TEXT NOT NULL DEFAULT 'manual',
            target_hint_ar TEXT DEFAULT '',
            sort_order INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (standard_id, code),
            FOREIGN KEY (standard_id) REFERENCES accreditation_standards(id) ON DELETE CASCADE
        )
    """,

    'accreditation_assessments': """
        CREATE TABLE IF NOT EXISTS accreditation_assessments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            semester TEXT NOT NULL,
            department_id INTEGER,
            program_id INTEGER,
            indicator_id INTEGER NOT NULL,
            score_percent REAL,
            compliance_status TEXT NOT NULL DEFAULT 'not_started',
            notes TEXT DEFAULT '',
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_by TEXT DEFAULT '',
            UNIQUE (semester, department_id, indicator_id),
            FOREIGN KEY (indicator_id) REFERENCES accreditation_indicators(id) ON DELETE CASCADE
        )
    """,

    'accreditation_evidence': """
        CREATE TABLE IF NOT EXISTS accreditation_evidence (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            semester TEXT NOT NULL,
            department_id INTEGER,
            indicator_id INTEGER,
            standard_id INTEGER,
            checklist_key TEXT,
            title_ar TEXT NOT NULL DEFAULT '',
            description TEXT DEFAULT '',
            evidence_type TEXT NOT NULL DEFAULT 'file',
            external_url TEXT DEFAULT '',
            original_name TEXT DEFAULT '',
            stored_path TEXT DEFAULT '',
            mime_type TEXT DEFAULT '',
            file_size INTEGER DEFAULT 0,
            sha256 TEXT DEFAULT '',
            uploaded_by TEXT DEFAULT '',
            uploaded_at TEXT DEFAULT CURRENT_TIMESTAMP,
            is_active INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY (indicator_id) REFERENCES accreditation_indicators(id) ON DELETE SET NULL,
            FOREIGN KEY (standard_id) REFERENCES accreditation_standards(id) ON DELETE SET NULL
        )
    """,

    'accreditation_manual_inputs': """
        CREATE TABLE IF NOT EXISTS accreditation_manual_inputs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            semester TEXT NOT NULL,
            department_id INTEGER,
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

    'accreditation_improvement_plans': """
        CREATE TABLE IF NOT EXISTS accreditation_improvement_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            semester TEXT NOT NULL,
            department_id INTEGER,
            indicator_id INTEGER,
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
            FOREIGN KEY (indicator_id) REFERENCES accreditation_indicators(id) ON DELETE SET NULL
        )
    """,

    'department_archive_items': """
        CREATE TABLE IF NOT EXISTS department_archive_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            department_id INTEGER NOT NULL,
            program_id INTEGER,
            record_type TEXT NOT NULL,
            title_ar TEXT NOT NULL DEFAULT '',
            ref_number TEXT DEFAULT '',
            doc_date TEXT DEFAULT '',
            semester TEXT DEFAULT '',
            party_ar TEXT DEFAULT '',
            tags TEXT DEFAULT '',
            body_text TEXT DEFAULT '',
            follow_up_status TEXT DEFAULT 'na',
            original_name TEXT DEFAULT '',
            stored_path TEXT DEFAULT '',
            mime_type TEXT DEFAULT '',
            file_size INTEGER DEFAULT 0,
            sha256 TEXT DEFAULT '',
            created_by TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_by TEXT DEFAULT '',
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            is_active INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY (department_id) REFERENCES departments(id)
        )
    """,

    'accreditation_evidence_types': """
        CREATE TABLE IF NOT EXISTS accreditation_evidence_types (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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

    'accreditation_indicator_evidence_rules': """
        CREATE TABLE IF NOT EXISTS accreditation_indicator_evidence_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            catalog_version TEXT NOT NULL,
            indicator_id INTEGER NOT NULL,
            evidence_type_id INTEGER NOT NULL,
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
            FOREIGN KEY (indicator_id) REFERENCES accreditation_indicators(id) ON DELETE CASCADE,
            FOREIGN KEY (evidence_type_id) REFERENCES accreditation_evidence_types(id) ON DELETE CASCADE
        )
    """,

    'accreditation_evidence_bindings': """
        CREATE TABLE IF NOT EXISTS accreditation_evidence_bindings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            semester TEXT NOT NULL,
            department_id INTEGER,
            indicator_id INTEGER NOT NULL,
            evidence_type_id INTEGER NOT NULL,
            rule_id INTEGER,
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
            FOREIGN KEY (indicator_id) REFERENCES accreditation_indicators(id) ON DELETE CASCADE,
            FOREIGN KEY (evidence_type_id) REFERENCES accreditation_evidence_types(id) ON DELETE CASCADE,
            FOREIGN KEY (rule_id) REFERENCES accreditation_indicator_evidence_rules(id) ON DELETE SET NULL
        )
    """,

    'program_learning_outcomes': """
        CREATE TABLE IF NOT EXISTS program_learning_outcomes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            program_id INTEGER NOT NULL,
            code TEXT NOT NULL,
            title_ar TEXT NOT NULL,
            description TEXT DEFAULT '',
            sort_order INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (program_id, code),
            FOREIGN KEY (program_id) REFERENCES programs(id) ON DELETE CASCADE
        )
    """,

    'program_course_learning_outcomes': """
        CREATE TABLE IF NOT EXISTS program_course_learning_outcomes (
            program_course_id INTEGER NOT NULL,
            outcome_id INTEGER NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (program_course_id, outcome_id),
            FOREIGN KEY (program_course_id) REFERENCES program_courses(id) ON DELETE CASCADE,
            FOREIGN KEY (outcome_id) REFERENCES program_learning_outcomes(id) ON DELETE CASCADE
        )
    """,

    'plo_course_master_links': """
        CREATE TABLE IF NOT EXISTS plo_course_master_links (
            program_id INTEGER NOT NULL,
            outcome_id INTEGER NOT NULL,
            course_master_id INTEGER NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (program_id, outcome_id, course_master_id),
            FOREIGN KEY (program_id) REFERENCES programs(id) ON DELETE CASCADE,
            FOREIGN KEY (outcome_id) REFERENCES program_learning_outcomes(id) ON DELETE CASCADE,
            FOREIGN KEY (course_master_id) REFERENCES course_master(id) ON DELETE CASCADE
        )
    """,

    'section_ilo_assessments': """
        CREATE TABLE IF NOT EXISTS section_ilo_assessments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            section_id INTEGER NOT NULL,
            instructor_id INTEGER NOT NULL,
            semester TEXT NOT NULL,
            outcome_id INTEGER NOT NULL,
            achievement_percent INTEGER CHECK (achievement_percent BETWEEN 0 AND 100),
            notes TEXT DEFAULT '',
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (section_id, instructor_id, semester, outcome_id),
            FOREIGN KEY (outcome_id) REFERENCES program_learning_outcomes(id) ON DELETE CASCADE
        )
    """,

    # إسناد الأستاذ لأكثر من قسم + تكافؤ المقررات بين الأقسام (ترقية توافقية)
    'instructor_department_assignments': """
        CREATE TABLE IF NOT EXISTS instructor_department_assignments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            instructor_id INTEGER NOT NULL,
            department_id INTEGER NOT NULL,
            schedule_section_id INTEGER NOT NULL DEFAULT -1,
            semester TEXT NOT NULL DEFAULT '',
            is_primary INTEGER NOT NULL DEFAULT 0 CHECK (is_primary IN (0, 1)),
            is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
            migration_source TEXT DEFAULT 'manual',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (instructor_id) REFERENCES instructors(id) ON DELETE CASCADE,
            FOREIGN KEY (department_id) REFERENCES departments(id) ON DELETE CASCADE,
            UNIQUE (instructor_id, department_id, schedule_section_id, semester)
        )
    """,

    'course_equivalence_groups': """
        CREATE TABLE IF NOT EXISTS course_equivalence_groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_key TEXT NOT NULL UNIQUE,
            title TEXT DEFAULT '',
            is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """,

    'course_equivalence_items': """
        CREATE TABLE IF NOT EXISTS course_equivalence_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER NOT NULL,
            department_id INTEGER NOT NULL,
            course_name TEXT NOT NULL,
            course_code TEXT DEFAULT '',
            program_course_id INTEGER,
            is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (group_id, department_id, course_name),
            FOREIGN KEY (group_id) REFERENCES course_equivalence_groups(id) ON DELETE CASCADE,
            FOREIGN KEY (department_id) REFERENCES departments(id) ON DELETE CASCADE
        )
    """,

    # سياسات التخرج على مستوى القسم (اقتراح رئيس القسم + اعتماد admin_main)
    'department_graduation_policies': """
        CREATE TABLE IF NOT EXISTS department_graduation_policies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            department_id INTEGER NOT NULL,
            plan_code TEXT NOT NULL CHECK (plan_code IN ('150', '155')),
            min_total_units INTEGER NOT NULL DEFAULT 0 CHECK (min_total_units >= 0),
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
            FOREIGN KEY (department_id) REFERENCES departments(id) ON DELETE CASCADE
        )
    """,
}

# ============================================
# الفهارس لتحسين الأداء
# ============================================

INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_registrations_student ON registrations(student_id)",
    "CREATE INDEX IF NOT EXISTS idx_registrations_course ON registrations(course_name)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_registrations_student_course_sem ON registrations(student_id, course_name, semester)",
    "CREATE INDEX IF NOT EXISTS idx_schedule_course ON schedule(course_name)",
    "CREATE INDEX IF NOT EXISTS idx_schedule_day_time ON schedule(day, time)",
    "CREATE INDEX IF NOT EXISTS idx_schedule_instructor_id ON schedule(instructor_id)",
    "CREATE INDEX IF NOT EXISTS idx_faculty_axis_inst ON faculty_section_axis_status(instructor_id)",
    "CREATE INDEX IF NOT EXISTS idx_faculty_plan_inst_sec ON faculty_course_plans(instructor_id, section_id)",
    "CREATE INDEX IF NOT EXISTS idx_faculty_ann_sec_pub ON faculty_course_announcements(section_id, published_to_students)",
    "CREATE INDEX IF NOT EXISTS idx_faculty_syllabus_inst_sec ON faculty_course_syllabi(instructor_id, section_id)",
    "CREATE INDEX IF NOT EXISTS idx_faculty_assignments_inst_active ON faculty_assignments(instructor_id, is_active)",
    "CREATE INDEX IF NOT EXISTS idx_faculty_assignments_type ON faculty_assignments(assignment_type)",
    "CREATE INDEX IF NOT EXISTS idx_faculty_logs_assignment_time ON faculty_assignment_logs(assignment_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_faculty_logs_instructor ON faculty_assignment_logs(instructor_id)",
    "CREATE INDEX IF NOT EXISTS idx_course_closure_status ON course_closure_reports(status, semester)",
    "CREATE INDEX IF NOT EXISTS idx_course_closure_section_inst ON course_closure_reports(section_id, instructor_id)",
    "CREATE INDEX IF NOT EXISTS idx_course_eval_student_sem ON course_evaluations(student_id, semester)",
    "CREATE INDEX IF NOT EXISTS idx_course_eval_section_sem ON course_evaluations(section_id, semester)",
    "CREATE INDEX IF NOT EXISTS idx_course_eval_instructor_sem ON course_evaluations(instructor_id, semester)",
    "CREATE INDEX IF NOT EXISTS idx_course_eval_teaching_group ON course_evaluations(teaching_group_id, semester)",
    "CREATE INDEX IF NOT EXISTS idx_eval_survey_q_sort ON evaluation_survey_questions(sort_order, is_active)",
    "CREATE INDEX IF NOT EXISTS idx_eval_survey_ans_eval ON evaluation_survey_answers(evaluation_id)",
    "CREATE INDEX IF NOT EXISTS idx_eval_survey_ans_q ON evaluation_survey_answers(question_id)",
    "CREATE INDEX IF NOT EXISTS idx_survey_resp_sem ON survey_responses(template_code, semester)",
    "CREATE INDEX IF NOT EXISTS idx_survey_resp_resp ON survey_responses(respondent_role, respondent_id)",
    "CREATE INDEX IF NOT EXISTS idx_survey_ans_resp ON survey_answers(response_id)",
    "CREATE INDEX IF NOT EXISTS idx_supervisor_quality_sem ON supervisor_quality_reports(supervisor_instructor_id, semester)",
    "CREATE INDEX IF NOT EXISTS idx_quality_metrics_sem_dept ON quality_metrics_snapshots(semester, department_id)",
    "CREATE INDEX IF NOT EXISTS idx_accred_std_domain ON accreditation_standards(domain_code, catalog_version)",
    "CREATE INDEX IF NOT EXISTS idx_accred_ind_standard ON accreditation_indicators(standard_id)",
    "CREATE INDEX IF NOT EXISTS idx_accred_asm_sem ON accreditation_assessments(semester, department_id)",
    "CREATE INDEX IF NOT EXISTS idx_dept_archive_dept_sem ON department_archive_items(department_id, semester, record_type)",
    "CREATE INDEX IF NOT EXISTS idx_accred_ev_sem ON accreditation_evidence(semester, department_id, indicator_id)",
    "CREATE INDEX IF NOT EXISTS idx_accred_manual_sem ON accreditation_manual_inputs(semester, department_id)",
    "CREATE INDEX IF NOT EXISTS idx_accred_plan_sem ON accreditation_improvement_plans(semester, department_id, status)",
    "CREATE INDEX IF NOT EXISTS idx_accred_ev_rule_cat ON accreditation_indicator_evidence_rules(catalog_version, indicator_id)",
    "CREATE INDEX IF NOT EXISTS idx_accred_ev_type_cat ON accreditation_evidence_types(category, is_active)",
    "CREATE INDEX IF NOT EXISTS idx_accred_ev_bind_sem ON accreditation_evidence_bindings(semester, department_id, indicator_id)",
    "CREATE INDEX IF NOT EXISTS idx_plo_program ON program_learning_outcomes(program_id, is_active)",
    "CREATE INDEX IF NOT EXISTS idx_pclo_course ON program_course_learning_outcomes(program_course_id)",
    "CREATE INDEX IF NOT EXISTS idx_plo_cm_master ON plo_course_master_links(program_id, course_master_id)",
    "CREATE INDEX IF NOT EXISTS idx_silo_section_sem ON section_ilo_assessments(section_id, semester)",
    "CREATE INDEX IF NOT EXISTS idx_governance_audit_ts ON governance_audit_logs(ts)",
    "CREATE INDEX IF NOT EXISTS idx_governance_audit_actor ON governance_audit_logs(actor)",
    "CREATE INDEX IF NOT EXISTS idx_grades_student_semester ON grades(student_id, semester)",
    "CREATE INDEX IF NOT EXISTS idx_grade_drafts_section ON grade_drafts(section_id, semester)",
    "CREATE INDEX IF NOT EXISTS idx_grade_special_cases_scope ON grade_special_cases(section_id, student_id, semester)",
    "CREATE INDEX IF NOT EXISTS idx_grade_special_cases_status ON grade_special_cases(status, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_grade_correction_req_status ON grade_correction_requests(status, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_grade_correction_req_draft ON grade_correction_requests(draft_id)",
    "CREATE INDEX IF NOT EXISTS idx_grades_course ON grades(course_name)",
    "CREATE INDEX IF NOT EXISTS idx_conflict_report_student ON conflict_report(student_id)",
    "CREATE INDEX IF NOT EXISTS idx_exams_course ON exams(course_name)",
    "CREATE INDEX IF NOT EXISTS idx_exams_date ON exams(exam_date)",
    "CREATE INDEX IF NOT EXISTS idx_grade_audit_student ON grade_audit(student_id)",
    "CREATE INDEX IF NOT EXISTS idx_attendance_student ON attendance_records(student_id)",
    "CREATE INDEX IF NOT EXISTS idx_attendance_course ON attendance_records(course_name)",
    "CREATE INDEX IF NOT EXISTS idx_enrollment_plans_student_sem ON enrollment_plans(student_id, semester)",
    "CREATE INDEX IF NOT EXISTS idx_enrollment_items_plan ON enrollment_plan_items(plan_id)",
    'CREATE INDEX IF NOT EXISTS idx_notifications_user_created ON notifications("user", created_at)',
    "CREATE INDEX IF NOT EXISTS idx_users_role ON users(role)",
    "CREATE INDEX IF NOT EXISTS idx_academic_calendar_year_term ON academic_calendar(academic_year, term)",
    "CREATE INDEX IF NOT EXISTS idx_term_master_current ON term_master(is_current)",
    "CREATE INDEX IF NOT EXISTS idx_term_master_year_season ON term_master(academic_year, season)",
    "CREATE INDEX IF NOT EXISTS idx_term_windows_term ON term_windows(term_key)",
    "CREATE INDEX IF NOT EXISTS idx_cal_versions_term ON academic_calendar_versions(term_key, version_no)",
    "CREATE INDEX IF NOT EXISTS idx_term_amend_log_term ON term_amendment_log(term_key, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_term_reg_arch_term ON term_registration_archives(archived_term, student_id)",
    "CREATE INDEX IF NOT EXISTS idx_term_op_exc_student ON term_operation_exceptions(student_id, status)",
    "CREATE INDEX IF NOT EXISTS idx_term_offerings_term ON term_course_offerings(term_key)",
    "CREATE INDEX IF NOT EXISTS idx_term_offerings_dept ON term_course_offerings(term_key, department_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_term_offerings_term_course_dept ON term_course_offerings(term_key, course_name, department_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_courses_code_unique ON courses(course_code) WHERE course_code IS NOT NULL AND course_code <> ''",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_departments_code_unique ON departments(code) WHERE code IS NOT NULL AND code <> ''",
    "CREATE INDEX IF NOT EXISTS idx_programs_dept ON programs(department_id)",
    "CREATE INDEX IF NOT EXISTS idx_program_courses_program ON program_courses(program_id)",
    "CREATE INDEX IF NOT EXISTS idx_program_courses_master ON program_courses(course_master_id)",
    "CREATE INDEX IF NOT EXISTS idx_students_department ON students(department_id)",
    "CREATE INDEX IF NOT EXISTS idx_students_program ON students(current_program_id)",
    "CREATE INDEX IF NOT EXISTS idx_users_department ON users(department_id)",
    "CREATE INDEX IF NOT EXISTS idx_instructors_department ON instructors(department_id)",
    "CREATE INDEX IF NOT EXISTS idx_ida_instructor_dept ON instructor_department_assignments(instructor_id, department_id)",
    "CREATE INDEX IF NOT EXISTS idx_ida_department_sem ON instructor_department_assignments(department_id, semester)",
    "CREATE INDEX IF NOT EXISTS idx_ida_schedule_section ON instructor_department_assignments(schedule_section_id)",
    "CREATE INDEX IF NOT EXISTS idx_course_equiv_items_dept ON course_equivalence_items(department_id)",
    "CREATE INDEX IF NOT EXISTS idx_course_equiv_items_course ON course_equivalence_items(course_name)",
    "CREATE INDEX IF NOT EXISTS idx_dept_grad_policy_dept_status ON department_graduation_policies(department_id, status)",
    "CREATE INDEX IF NOT EXISTS idx_schedule_program_course ON schedule(program_course_id)",
    "CREATE INDEX IF NOT EXISTS idx_schedule_department ON schedule(department_id)",
    "CREATE INDEX IF NOT EXISTS idx_schedule_teaching_group ON schedule(teaching_group_id)",
    "CREATE INDEX IF NOT EXISTS idx_teaching_groups_semester ON teaching_groups(semester)",
    "CREATE INDEX IF NOT EXISTS idx_teaching_groups_course_sem ON teaching_groups(course_name, semester)",
    "CREATE INDEX IF NOT EXISTS idx_teaching_groups_dept_sem ON teaching_groups(department_id, semester)",
    "CREATE INDEX IF NOT EXISTS idx_grades_program_course ON grades(program_course_id)",
    "CREATE INDEX IF NOT EXISTS idx_regs_program_course ON registrations(program_course_id)",
    "CREATE INDEX IF NOT EXISTS idx_regs_teaching_group ON registrations(teaching_group_id)",
    "CREATE INDEX IF NOT EXISTS idx_student_supervisor_instructor ON student_supervisor(instructor_id)",
    "CREATE INDEX IF NOT EXISTS idx_reg_requests_status_created ON registration_requests(status, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_reg_requests_student ON registration_requests(student_id)",
    "CREATE INDEX IF NOT EXISTS idx_reg_changes_student_time ON registration_changes_log(student_id, action_time)",
]
