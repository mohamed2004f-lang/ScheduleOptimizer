"""دعوات الاستبيانات الخارجية (خريجون، جهات عمل) عبر رابط."""

from __future__ import annotations

import datetime
import hashlib
import json
import secrets
from typing import Any

from backend.core.survey_platform import (
    ALUMNI_EMPLOYED_STATUSES,
    ALUMNI_EMPLOYMENT_STATUSES,
    ALUMNI_ENGINEERING_QUAL_OPTIONS,
    ALUMNI_INTRO_AR,
    ALUMNI_OPEN_COMMENT_LABEL,
    ALUMNI_PROGRAM_DEVELOPMENT_OPTIONS,
    ALUMNI_PROGRAM_FREEZE_QUESTION_AR,
    ALUMNI_PROGRAM_FREEZE_SUPPORT_QUESTION_AR,
    ALUMNI_PROGRAM_TERMINOLOGY_AR,
    ALUMNI_PROGRAM_SCOPE_HINT_AR,
    ALUMNI_QUESTION_SECTIONS,
    ALUMNI_DEPARTMENT_FIELD_LABEL,
    ALUMNI_DEPARTMENT_FIELD_HINT,
    ALUMNI_TRACK_FIELD_LABEL,
    ALUMNI_TRACK_FIELD_HINT,
    ALUMNI_TRACK_CUSTOM_OPTION_LABEL,
    ALUMNI_TRACK_CUSTOM_FIELD_LABEL,
    ALUMNI_TAIL_PROGRAM_HINT_AR,
    EMPLOYER_OPEN_COMMENT_LABEL,
    EMPLOYER_ORG_TYPES,
    EMPLOYER_HIRE_DEPARTMENTS_LABEL,
    EMPLOYER_HIRE_DEPARTMENTS_HINT,
    EMPLOYER_HIRE_NEEDS_FIELD_LABEL,
    EMPLOYER_HIRE_NEEDS_FIELD_HINT,
    EXTERNAL_SURVEY_CODES,
)
from backend.database.database import conn_is_postgresql, fetch_table_columns, is_postgresql, table_exists
from backend.services.multi_surveys import (
    get_template_by_code,
    list_template_questions,
    parse_answers_payload,
)
from backend.services.evaluation_survey import likert_labels_ar, likert_scale_context

logger = __import__("logging").getLogger(__name__)


def _row_dict(row) -> dict:
    if row is None:
        return {}
    if hasattr(row, "keys"):
        return dict(row)
    return {}


def ensure_survey_invite_schema(conn) -> None:
    """جداول الدعوات وأعمدة الاستجابة الخارجية."""
    if not table_exists(conn, "survey_templates"):
        return
    cur = conn.cursor()
    pg = conn_is_postgresql(conn)

    if not table_exists(conn, "survey_invites"):
        if pg:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS survey_invites (
                    id BIGSERIAL PRIMARY KEY,
                    token TEXT NOT NULL UNIQUE,
                    template_code TEXT NOT NULL,
                    cycle_label TEXT NOT NULL,
                    invite_kind TEXT NOT NULL DEFAULT 'campaign',
                    label_ar TEXT DEFAULT '',
                    expires_at TEXT,
                    max_uses INTEGER NOT NULL DEFAULT 0,
                    use_count INTEGER NOT NULL DEFAULT 0,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_by TEXT DEFAULT '',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    notes TEXT DEFAULT ''
                )
                """
            )
        else:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS survey_invites (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    token TEXT NOT NULL UNIQUE,
                    template_code TEXT NOT NULL,
                    cycle_label TEXT NOT NULL,
                    invite_kind TEXT NOT NULL DEFAULT 'campaign',
                    label_ar TEXT DEFAULT '',
                    expires_at TEXT,
                    max_uses INTEGER NOT NULL DEFAULT 0,
                    use_count INTEGER NOT NULL DEFAULT 0,
                    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
                    created_by TEXT DEFAULT '',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    notes TEXT DEFAULT ''
                )
                """
            )
        try:
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_survey_invites_template "
                "ON survey_invites(template_code, is_active)"
            )
        except Exception:
            pass

    resp_cols = fetch_table_columns(conn, "survey_responses") if table_exists(conn, "survey_responses") else {}
    if resp_cols:
        if "respondent_profile_json" not in resp_cols:
            ddl = "TEXT DEFAULT ''" if not pg else "TEXT DEFAULT ''"
            try:
                if pg:
                    cur.execute(
                        "ALTER TABLE survey_responses "
                        "ADD COLUMN IF NOT EXISTS respondent_profile_json TEXT DEFAULT ''"
                    )
                else:
                    cur.execute(
                        f"ALTER TABLE survey_responses ADD COLUMN respondent_profile_json {ddl}"
                    )
            except Exception as e:
                logger.debug("respondent_profile_json: %s", e)
        if "invite_id" not in resp_cols:
            try:
                if pg:
                    cur.execute(
                        "ALTER TABLE survey_responses ADD COLUMN IF NOT EXISTS invite_id BIGINT"
                    )
                else:
                    cur.execute("ALTER TABLE survey_responses ADD COLUMN invite_id INTEGER")
            except Exception as e:
                logger.debug("invite_id: %s", e)
    try:
        conn.commit()
    except Exception:
        pass


def generate_invite_token() -> str:
    return secrets.token_urlsafe(32)


def create_survey_invite(
    conn,
    *,
    template_code: str,
    cycle_label: str,
    invite_kind: str = "campaign",
    label_ar: str = "",
    expires_days: int = 90,
    max_uses: int = 0,
    created_by: str = "",
    notes: str = "",
) -> dict:
    ensure_survey_invite_schema(conn)
    code = (template_code or "").strip()
    if code not in EXTERNAL_SURVEY_CODES:
        raise ValueError("قالب الاستبيان غير مدعوم للدعوات الخارجية")
    if not get_template_by_code(conn, code):
        raise ValueError("قالب الاستبيان غير موجود")
    cycle = (cycle_label or "").strip()
    if not cycle:
        raise ValueError("اسم الدورة مطلوب")
    kind = (invite_kind or "campaign").strip().lower()
    if kind not in ("campaign", "personal"):
        raise ValueError("نوع الدعوة غير صالح")
    if kind == "personal" and max_uses <= 0:
        max_uses = 1

    token = generate_invite_token()
    now = datetime.datetime.utcnow()
    expires_at = (now + datetime.timedelta(days=max(1, int(expires_days)))).isoformat()
    created_at = now.isoformat()
    cur = conn.cursor()
    if is_postgresql():
        cur.execute(
            """
            INSERT INTO survey_invites (
                token, template_code, cycle_label, invite_kind, label_ar,
                expires_at, max_uses, use_count, is_active, created_by, created_at, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, 1, ?, ?, ?)
            RETURNING id
            """,
            (
                token,
                code,
                cycle,
                kind,
                (label_ar or "").strip(),
                expires_at,
                int(max_uses),
                (created_by or "").strip(),
                created_at,
                (notes or "").strip(),
            ),
        )
        invite_id = int(cur.fetchone()[0])
    else:
        cur.execute(
            """
            INSERT INTO survey_invites (
                token, template_code, cycle_label, invite_kind, label_ar,
                expires_at, max_uses, use_count, is_active, created_by, created_at, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, 1, ?, ?, ?)
            """,
            (
                token,
                code,
                cycle,
                kind,
                (label_ar or "").strip(),
                expires_at,
                int(max_uses),
                (created_by or "").strip(),
                created_at,
                (notes or "").strip(),
            ),
        )
        invite_id = int(cur.lastrowid or 0)
    return get_invite_by_token(conn, token) or {"id": invite_id, "token": token}


def list_survey_invites(conn, *, template_code: str | None = None, limit: int = 200) -> list[dict]:
    ensure_survey_invite_schema(conn)
    if not table_exists(conn, "survey_invites"):
        return []
    cur = conn.cursor()
    params: list[Any] = []
    sql = "SELECT * FROM survey_invites WHERE 1=1"
    if template_code:
        sql += " AND template_code = ?"
        params.append(template_code.strip())
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(int(limit))
    rows = cur.execute(sql, tuple(params)).fetchall()
    return [_row_dict(r) for r in rows or []]


def get_invite_by_token(conn, token: str) -> dict | None:
    ensure_survey_invite_schema(conn)
    if not table_exists(conn, "survey_invites"):
        return None
    cur = conn.cursor()
    row = cur.execute(
        "SELECT * FROM survey_invites WHERE token = ? LIMIT 1",
        ((token or "").strip(),),
    ).fetchone()
    return _row_dict(row) if row else None


def validate_invite(conn, token: str) -> dict:
    invite = get_invite_by_token(conn, token)
    if not invite:
        raise ValueError("رابط الدعوة غير صالح")
    if not int(invite.get("is_active") or 0):
        raise ValueError("انتهت صلاحية هذه الدعوة")
    expires = (invite.get("expires_at") or "").strip()
    if expires:
        try:
            exp_dt = datetime.datetime.fromisoformat(expires.replace("Z", "+00:00"))
            if exp_dt.tzinfo:
                exp_dt = exp_dt.replace(tzinfo=None)
            if datetime.datetime.utcnow() > exp_dt:
                raise ValueError("انتهت صلاحية رابط الدعوة")
        except ValueError:
            raise
        except Exception:
            pass
    max_uses = int(invite.get("max_uses") or 0)
    use_count = int(invite.get("use_count") or 0)
    if max_uses > 0 and use_count >= max_uses:
        raise ValueError("تم استخدام هذا الرابط بالكامل")
    template = get_template_by_code(conn, invite.get("template_code") or "")
    if not template:
        raise ValueError("قالب الاستبيان غير متاح")
    return invite


def _phone_hash(phone: str) -> str:
    normalized = "".join(ch for ch in (phone or "") if ch.isdigit())
    if not normalized:
        return ""
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:32]


def _normalize_person_name(name: str) -> str:
    """تطبيع الاسم للمقارنة (مسافات + حالة الأحرف). الاسم الفارغ → ''."""
    return " ".join((name or "").split()).casefold()


def _resolve_public_department(conn, department_id: int) -> str:
    """اسم قسم مسموح به في استبيان الخريج (يستبعد القسم العام)."""
    if not table_exists(conn, "departments"):
        raise ValueError("القسم غير صالح")
    cur = conn.cursor()
    row = cur.execute(
        """
        SELECT COALESCE(name_ar, name_en, code) AS name_ar
        FROM departments
        WHERE id = ? AND COALESCE(is_active, 1) = 1
          AND UPPER(COALESCE(code, '')) != 'GENERAL'
        """,
        (int(department_id),),
    ).fetchone()
    if not row:
        raise ValueError("القسم غير صالح")
    d = _row_dict(row)
    return (d.get("name_ar") or "").strip() or "قسم"


def _validate_alumni_profile(profile: dict) -> dict:
    year = profile.get("graduation_year")
    try:
        grad_year = int(year)
    except (TypeError, ValueError):
        raise ValueError("سنة التخرج مطلوبة")
    current_year = datetime.datetime.utcnow().year
    if grad_year < 1980 or grad_year > current_year + 1:
        raise ValueError("سنة التخرج غير صالحة")
    dept_id = profile.get("department_id")
    if dept_id in (None, "", "other"):
        raise ValueError("القسم مطلوب")
    try:
        dept_id = int(dept_id)
    except (TypeError, ValueError):
        raise ValueError("القسم غير صالح")
    if dept_id <= 0:
        raise ValueError("القسم غير صالح")

    track_code = (profile.get("track_code") or "").strip()
    if track_code == "unknown":
        track_code = ""
    track_label = (profile.get("track_label") or "").strip()
    if track_code == "custom":
        track_label = (profile.get("track_custom_label") or track_label or "").strip()
        if not track_label:
            raise ValueError("يرجى كتابة اسم المسار/الشعبة غير المدرجة")
        track_code = "custom"
    elif not track_code:
        track_label = ""

    employment_status = (profile.get("employment_status") or "").strip()
    valid_employment = {k for k, _ in ALUMNI_EMPLOYMENT_STATUSES}
    if employment_status not in valid_employment:
        raise ValueError("الحالة المهنية الحالية مطلوبة")

    engineering_qualification = ""
    if employment_status in ALUMNI_EMPLOYED_STATUSES:
        engineering_qualification = (profile.get("engineering_qualification") or "").strip()
        valid_qual = {k for k, _ in ALUMNI_ENGINEERING_QUAL_OPTIONS}
        if engineering_qualification not in valid_qual:
            raise ValueError("يرجى الإجابة: هل تتطلب وظيفتك مؤهلاً هندسياً في تخصصك أو مجال قريب؟")

    job_rejection = ""
    job_rejection_reason = ""
    if employment_status in ALUMNI_EMPLOYED_STATUSES or employment_status == "job_seeking":
        job_rejection = (profile.get("job_rejection") or "").strip().lower()
        if job_rejection not in ("yes", "no"):
            raise ValueError("يرجى الإجابة: هل واجهت رفضاً عند التقديم على وظائف بعد التخرج؟")
        if job_rejection == "yes":
            job_rejection_reason = (profile.get("job_rejection_reason") or "").strip()

    recommend_enrollment = (profile.get("recommend_enrollment") or "").strip().lower()
    if recommend_enrollment not in ("yes", "no"):
        raise ValueError("يرجى الإجابة: هل تنصح الطلاب الجدد بالالتحاق بهذا البرنامج؟")

    program_freeze_support = (profile.get("program_freeze_support") or "").strip().lower()
    if program_freeze_support not in ("yes", "no"):
        raise ValueError("يرجى الإجابة: هل تؤيد تجميد البرنامج في ظل الظروف الحالية؟")

    program_development_choice = ""
    valid_program = {k for k, _ in ALUMNI_PROGRAM_DEVELOPMENT_OPTIONS}
    if program_freeze_support == "yes":
        program_development_choice = (profile.get("program_development_choice") or "").strip()
        if program_development_choice not in valid_program:
            raise ValueError("يرجى اختيار مقترحكم في حال تجميد البرنامج")

    employment_labels = dict(ALUMNI_EMPLOYMENT_STATUSES)
    qual_labels = dict(ALUMNI_ENGINEERING_QUAL_OPTIONS)
    from backend.core.survey_platform import program_development_label

    program_labels = {k: program_development_label(k) for k in valid_program}
    return {
        "full_name": (profile.get("full_name") or "").strip(),
        "graduation_year": grad_year,
        "department_id": dept_id,
        "department_label": "",
        "track_code": track_code,
        "track_label": track_label,
        "employment_status": employment_status,
        "employment_status_label": employment_labels.get(employment_status, employment_status),
        "current_role_text": (profile.get("current_role_text") or "").strip(),
        "engineering_qualification": engineering_qualification,
        "engineering_qualification_label": qual_labels.get(engineering_qualification, engineering_qualification),
        "job_rejection": job_rejection,
        "job_rejection_reason": job_rejection_reason,
        "recommend_enrollment": recommend_enrollment,
        "recommend_reason_text": (profile.get("recommend_reason_text") or "").strip(),
        "program_freeze_support": program_freeze_support,
        "program_freeze_support_label": {"yes": "نعم", "no": "لا"}.get(program_freeze_support, ""),
        "program_development_choice": program_development_choice,
        "program_development_label": program_labels.get(
            program_development_choice, program_development_choice
        ) if program_development_choice else "",
        "open_missing_skill": (profile.get("open_missing_skill") or "").strip(),
        "open_adaptation_difficulty": (profile.get("open_adaptation_difficulty") or "").strip(),
        "open_missing_technology": (profile.get("open_missing_technology") or "").strip(),
        "phone_hash": _phone_hash(profile.get("phone") or ""),
    }


def _parse_int_list(raw) -> list[int]:
    """تحويل قائمة معرفات من JSON أو قائمة أو نص مفصول بفواصل."""
    if raw is None:
        return []
    if isinstance(raw, list):
        out: list[int] = []
        for item in raw:
            try:
                val = int(item)
            except (TypeError, ValueError):
                continue
            if val > 0:
                out.append(val)
        return out
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return []
        if s.startswith("["):
            try:
                return _parse_int_list(json.loads(s))
            except Exception:
                pass
        return _parse_int_list([p.strip() for p in s.split(",") if p.strip()])
    return []


def _parse_hire_department_needs(profile: dict, hire_department_ids: list[int]) -> list[dict[str, Any]]:
    """استخراج احتياجات التخصص/الشعبة لكل قسم (نص حر)."""
    raw = profile.get("hire_department_needs")
    parsed: list[dict[str, Any]] = []
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                dept_id = int(item.get("department_id"))
            except (TypeError, ValueError):
                continue
            text = str(item.get("specialty_needs_text") or item.get("needs_text") or "").strip()
            if dept_id > 0 and text:
                parsed.append({"department_id": dept_id, "specialty_needs_text": text})
    if parsed:
        return parsed
    for dept_id in hire_department_ids:
        key = f"hire_needs_{dept_id}"
        text = str(profile.get(key) or "").strip()
        if text:
            parsed.append({"department_id": int(dept_id), "specialty_needs_text": text})
    return parsed


def _validate_employer_profile(profile: dict, conn=None) -> dict:
    org_type = (profile.get("org_type") or "").strip()
    valid_types = {k for k, _ in EMPLOYER_ORG_TYPES}
    if org_type not in valid_types:
        raise ValueError("نوع الجهة مطلوب")
    org_name = (profile.get("org_name") or "").strip()
    if not org_name:
        raise ValueError("اسم الجهة مطلوب")
    hires = (profile.get("hires_graduates") or "").strip().lower()
    if hires not in ("yes", "no", "sometimes"):
        raise ValueError("يرجى الإجابة: هل توظّفون خريجين من الكلية؟")

    hire_department_ids = _parse_int_list(profile.get("hire_department_ids"))
    if hires in ("yes", "sometimes") and not hire_department_ids:
        raise ValueError("يرجى اختيار قسم واحد على الأقل الذي توظّفون من خريجيه")

    hire_department_labels: list[str] = []
    hire_department_needs: list[dict[str, Any]] = []
    if conn is not None and hire_department_ids:
        for dept_id in hire_department_ids:
            try:
                hire_department_labels.append(_resolve_public_department(conn, dept_id))
            except ValueError:
                raise ValueError(f"قسم غير صالح في قائمة التوظيف: {dept_id}") from None
        hire_department_needs = _parse_hire_department_needs(profile, hire_department_ids)
        allowed = set(hire_department_ids)
        hire_department_needs = [
            n for n in hire_department_needs if int(n["department_id"]) in allowed
        ]
        needs_by_dept = {int(n["department_id"]): n for n in hire_department_needs}
        for idx, dept_id in enumerate(hire_department_ids):
            if dept_id not in needs_by_dept:
                raise ValueError(
                    f"يرجى كتابة التخصص/الشعبة المطلوبة للقسم: {hire_department_labels[idx]}"
                )
            text = needs_by_dept[dept_id]["specialty_needs_text"]
            if len(text) < 2:
                raise ValueError(
                    f"يرجى وصف التخصص/الشعبة المطلوبة بشكل أوضح للقسم: {hire_department_labels[idx]}"
                )
        label_by_id = dict(zip(hire_department_ids, hire_department_labels))
        for item in hire_department_needs:
            item["department_label"] = label_by_id.get(int(item["department_id"]), "")

    org_type_label = dict(EMPLOYER_ORG_TYPES).get(org_type, org_type)
    return {
        "org_type": org_type,
        "org_type_label": org_type_label,
        "org_name": org_name,
        "sector_label": (profile.get("sector_label") or "").strip(),
        "position_text": (profile.get("position_text") or "").strip(),
        "hires_graduates": hires,
        "hire_department_ids": hire_department_ids,
        "hire_department_labels": hire_department_labels,
        "hire_department_needs": hire_department_needs,
    }


def validate_respondent_profile(template_code: str, profile: dict, conn=None) -> dict:
    code = (template_code or "").strip()
    if code == "alumni":
        return _validate_alumni_profile(profile or {})
    if code == "employer_strategic":
        return _validate_employer_profile(profile or {}, conn=conn)
    raise ValueError("قالب غير مدعوم")


def _check_duplicate_submission(conn, invite: dict, profile: dict) -> None:
    kind = (invite.get("invite_kind") or "").strip()
    if kind == "personal" and int(invite.get("use_count") or 0) > 0:
        raise ValueError("تم استخدام هذا الرابط مسبقاً")

    cycle = (invite.get("cycle_label") or "").strip()
    code = (invite.get("template_code") or "").strip()
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT respondent_profile_json FROM survey_responses
        WHERE template_code = ? AND semester = ? AND status = 'submitted'
        """,
        (code, cycle),
    ).fetchall()

    # خريج: اسم غير فارغ + نفس القسم + نفس الدورة → رفض
    if code == "alumni":
        name_norm = _normalize_person_name(profile.get("full_name") or "")
        dept_id = profile.get("department_id")
        if name_norm and isinstance(dept_id, int) and dept_id > 0:
            for row in rows or []:
                raw = row[0] if not hasattr(row, "keys") else row["respondent_profile_json"]
                try:
                    existing = json.loads(raw or "{}")
                except Exception:
                    existing = {}
                existing_name = _normalize_person_name(existing.get("full_name") or "")
                if not existing_name:
                    continue
                try:
                    existing_dept = int(existing.get("department_id"))
                except (TypeError, ValueError):
                    continue
                if existing_name == name_norm and existing_dept == int(dept_id):
                    raise ValueError(
                        "يبدو أن ردّاً بنفس الاسم والقسم سُجّل في هذه الدورة مسبقاً. "
                        "إن لم تكن أنت من أرسله، اترك حقل الاسم فارغاً أو راجع منسق الجودة."
                    )

    phone_hash = profile.get("phone_hash") or ""
    if not phone_hash:
        return
    for row in rows or []:
        raw = row[0] if not hasattr(row, "keys") else row["respondent_profile_json"]
        try:
            existing = json.loads(raw or "{}")
        except Exception:
            existing = {}
        if existing.get("phone_hash") == phone_hash:
            raise ValueError("تم تسجيل رد بهذا الرقم في هذه الحملة مسبقاً")


def submit_invite_survey(
    conn,
    *,
    token: str,
    profile: dict,
    answers_payload: dict,
    comments: str = "",
) -> int:
    invite = validate_invite(conn, token)
    template_code = (invite.get("template_code") or "").strip()
    cleaned_profile = validate_respondent_profile(template_code, profile, conn=conn)
    if template_code == "alumni":
        dept_id = cleaned_profile.get("department_id")
        if isinstance(dept_id, int):
            cleaned_profile["department_label"] = _resolve_public_department(conn, dept_id)
    elif template_code == "employer_strategic" and cleaned_profile.get("hire_department_ids"):
        cleaned_profile["hire_department_labels"] = [
            _resolve_public_department(conn, int(d))
            for d in cleaned_profile["hire_department_ids"]
        ]
    _check_duplicate_submission(conn, invite, cleaned_profile)

    template = get_template_by_code(conn, template_code)
    assert template
    questions = list_template_questions(conn, int(template["id"]))
    answers = parse_answers_payload(dict(answers_payload), questions)

    cycle = (invite.get("cycle_label") or "").strip()
    respondent_role = (template.get("respondent_role") or "").strip()
    respondent_id = f"invite:{invite['id']}:{secrets.token_hex(6)}"
    subject_type = (template.get("subject_type") or "external").strip()
    invite_id = int(invite.get("id") or 0)

    now = datetime.datetime.utcnow().isoformat()
    cur = conn.cursor()
    tid = int(template["id"])
    profile_json = json.dumps(cleaned_profile, ensure_ascii=False)
    response_dept_id = cleaned_profile.get("department_id")
    if template_code == "employer_strategic":
        hire_ids = cleaned_profile.get("hire_department_ids") or []
        response_dept_id = int(hire_ids[0]) if hire_ids else None

    if is_postgresql():
        cur.execute(
            """
            INSERT INTO survey_responses (
                template_id, template_code, semester,
                respondent_role, respondent_id,
                subject_type, subject_id, department_id,
                comments, status, submitted_by, created_at, submitted_at,
                respondent_profile_json, invite_id
            ) VALUES (?,?,?,?,?,?,?,?,?,'submitted',?,?,?,?,?)
            RETURNING id
            """,
            (
                tid,
                template_code,
                cycle,
                respondent_role,
                respondent_id,
                subject_type,
                0,
                response_dept_id,
                (comments or "").strip(),
                f"invite:{token[:12]}",
                now,
                now,
                profile_json,
                invite_id,
            ),
        )
        rid = int(cur.fetchone()[0])
    else:
        cur.execute(
            """
            INSERT INTO survey_responses (
                template_id, template_code, semester,
                respondent_role, respondent_id,
                subject_type, subject_id, department_id,
                comments, status, submitted_by, created_at, submitted_at,
                respondent_profile_json, invite_id
            ) VALUES (?,?,?,?,?,?,?,?,?,'submitted',?,?,?,?,?)
            """,
            (
                tid,
                template_code,
                cycle,
                respondent_role,
                respondent_id,
                subject_type,
                0,
                response_dept_id,
                (comments or "").strip(),
                f"invite:{token[:12]}",
                now,
                now,
                profile_json,
                invite_id,
            ),
        )
        rid = int(cur.lastrowid or 0)

    for qid, rating in answers.items():
        cur.execute(
            "INSERT INTO survey_answers (response_id, question_id, rating) VALUES (?, ?, ?)",
            (rid, int(qid), int(rating)),
        )

    cur.execute(
        "UPDATE survey_invites SET use_count = COALESCE(use_count, 0) + 1 WHERE id = ?",
        (invite_id,),
    )
    return rid


def _alumni_form_items(questions: list[dict]) -> list[dict[str, Any]]:
    """دمج عناوين المحاور مع بنود الاستبيان لعرضها في واجهة التعبئة."""
    sections = list(ALUMNI_QUESTION_SECTIONS)
    next_section = 0
    items: list[dict[str, Any]] = []
    for q in questions:
        sort_order = int(q.get("sort_order") or 0)
        while next_section < len(sections) and sort_order >= int(sections[next_section][0]):
            items.append({"kind": "section", "title_ar": sections[next_section][1]})
            next_section += 1
        items.append({"kind": "question", **q})
    return items


def invite_fill_context(conn, token: str) -> dict[str, Any]:
    invite = validate_invite(conn, token)
    template_code = (invite.get("template_code") or "").strip()
    template = get_template_by_code(conn, template_code)
    if not template:
        raise ValueError("قالب الاستبيان غير متاح")
    questions = list_template_questions(conn, int(template["id"]))
    open_label = ALUMNI_OPEN_COMMENT_LABEL
    if template_code == "employer_strategic":
        open_label = EMPLOYER_OPEN_COMMENT_LABEL

    ctx: dict[str, Any] = {
        "invite": invite,
        "template": template,
        "questions": questions,
        "likert_labels": likert_labels_ar(),
        "open_comment_label": open_label,
        "template_code": template_code,
        "cycle_label": invite.get("cycle_label"),
        "scale_guide_note": "اختر الرقم الذي يعبّر عن رأيك في كل بند.",
        **likert_scale_context(questions),
    }
    if template_code == "employer_strategic":
        from backend.services.survey_identity_context import build_employer_identity_panel

        ctx["identity_panel"] = build_employer_identity_panel(conn)
        ctx["employer_hire_departments_label"] = EMPLOYER_HIRE_DEPARTMENTS_LABEL
        ctx["employer_hire_departments_hint"] = EMPLOYER_HIRE_DEPARTMENTS_HINT
        ctx["employer_hire_needs_field_label"] = EMPLOYER_HIRE_NEEDS_FIELD_LABEL
        ctx["employer_hire_needs_field_hint"] = EMPLOYER_HIRE_NEEDS_FIELD_HINT
        ctx["public_departments"] = list_public_departments(conn)
    elif template_code == "alumni":
        ctx["alumni_intro_ar"] = ALUMNI_INTRO_AR
        ctx["alumni_employment_statuses"] = list(ALUMNI_EMPLOYMENT_STATUSES)
        ctx["alumni_engineering_qual_options"] = list(ALUMNI_ENGINEERING_QUAL_OPTIONS)
        ctx["alumni_program_development_options"] = list(ALUMNI_PROGRAM_DEVELOPMENT_OPTIONS)
        ctx["alumni_program_freeze_support_question_ar"] = ALUMNI_PROGRAM_FREEZE_SUPPORT_QUESTION_AR
        ctx["alumni_program_freeze_question_ar"] = ALUMNI_PROGRAM_FREEZE_QUESTION_AR
        ctx["alumni_program_terminology_ar"] = ALUMNI_PROGRAM_TERMINOLOGY_AR
        ctx["alumni_program_scope_hint_ar"] = ALUMNI_PROGRAM_SCOPE_HINT_AR
        ctx["alumni_department_field_label"] = ALUMNI_DEPARTMENT_FIELD_LABEL
        ctx["alumni_department_field_hint"] = ALUMNI_DEPARTMENT_FIELD_HINT
        ctx["alumni_track_field_label"] = ALUMNI_TRACK_FIELD_LABEL
        ctx["alumni_track_field_hint"] = ALUMNI_TRACK_FIELD_HINT
        ctx["alumni_track_custom_option_label"] = ALUMNI_TRACK_CUSTOM_OPTION_LABEL
        ctx["alumni_track_custom_field_label"] = ALUMNI_TRACK_CUSTOM_FIELD_LABEL
        ctx["alumni_tail_program_hint_ar"] = ALUMNI_TAIL_PROGRAM_HINT_AR
        ctx["alumni_form_items"] = _alumni_form_items(questions)
    return ctx


def list_external_cycles(conn, template_code: str | None = None) -> list[str]:
    if not table_exists(conn, "survey_responses"):
        return []
    cur = conn.cursor()
    params: list[Any] = list(EXTERNAL_SURVEY_CODES)
    placeholders = ",".join("?" for _ in EXTERNAL_SURVEY_CODES)
    sql = f"""
        SELECT DISTINCT semester FROM survey_responses
        WHERE template_code IN ({placeholders}) AND status = 'submitted'
    """
    if template_code:
        sql += " AND template_code = ?"
        params.append(template_code.strip())
    sql += " ORDER BY semester DESC"
    rows = cur.execute(sql, tuple(params)).fetchall()
    out: list[str] = []
    for row in rows or []:
        val = row[0] if not hasattr(row, "keys") else row["semester"]
        if val and str(val).strip():
            out.append(str(val).strip())
    return out


def list_public_departments(conn) -> list[dict]:
    if not table_exists(conn, "departments"):
        return []
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT id, code, COALESCE(name_ar, name_en, code) AS name_ar
        FROM departments
        WHERE COALESCE(is_active, 1) = 1
          AND UPPER(COALESCE(code, '')) != 'GENERAL'
        ORDER BY name_ar, code
        """
    ).fetchall()
    return [_row_dict(r) for r in rows or []]


def list_public_tracks_for_department(conn, department_id: int) -> list[dict]:
    """مسارات/شعب التخصص النشطة فقط (لا تُعرض البرامج المجمّدة)."""
    if not table_exists(conn, "programs"):
        return []
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT DISTINCT COALESCE(p.track_group, '') AS track_group,
               COALESCE(p.name_ar, p.code) AS program_name
        FROM programs p
        WHERE p.department_id = ?
          AND COALESCE(p.is_active, 1) = 1
          AND COALESCE(p.track_group, '') != ''
        ORDER BY track_group
        """,
        (int(department_id),),
    ).fetchall()
    items: list[dict] = []
    seen: set[str] = set()
    for row in rows or []:
        d = _row_dict(row)
        tg = (d.get("track_group") or "").strip()
        if not tg or tg in seen:
            continue
        seen.add(tg)
        label = (d.get("program_name") or tg).strip()
        items.append({"track_code": tg, "track_label": label})
    return items
