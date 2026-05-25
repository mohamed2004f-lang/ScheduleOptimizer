"""أهداف البرنامج (PG) وربطها بمخرجات التعلم (SO/PLO) — قالب ميكانيك."""

from __future__ import annotations

from typing import Any

MECH_PROGRAM_GOALS: tuple[dict[str, Any], ...] = (
    {
        "code": "PG1",
        "title_ar": "الكفاءة المهنية",
        "title_en": "Professional Competence",
        "description": (
            "تخريج مهندسين ميكانيكيين قادرين على تطبيق المبادئ الهندسية والرياضية "
            "والعلمية لحل المشكلات الهندسية المعقدة في مجالات التصميم والتصنيع والطاقة."
        ),
        "sort_order": 10,
    },
    {
        "code": "PG2",
        "title_ar": "التطوير المستمر",
        "title_en": "Continuous Development",
        "description": (
            "إعداد خريجين يمتلكون مهارات التعلم الذاتي والبحث العلمي والقدرة على "
            "مواكبة التطورات التكنولوجية الحديثة في الهندسة الميكانيكية."
        ),
        "sort_order": 20,
    },
    {
        "code": "PG3",
        "title_ar": "المسؤولية المجتمعية",
        "title_en": "Social Responsibility",
        "description": (
            "تخريج مهندسين يدركون الأثر الاقتصادي والبيئي والمجتمعي للحلول الهندسية، "
            "ويلتزمون بأخلاقيات المهنة."
        ),
        "sort_order": 30,
    },
    {
        "code": "PG4",
        "title_ar": "القيادة والعمل الجماعي",
        "title_en": "Leadership and Teamwork",
        "description": (
            "تزويد الخريجين بمهارات التواصل الفعال والقدرة على العمل ضمن فرق متعددة "
            "التخصصات وإدارة المشاريع الهندسية."
        ),
        "sort_order": 40,
    },
)

MECH_STUDENT_OUTCOMES: tuple[dict[str, Any], ...] = (
    {
        "code": "SO1",
        "title_ar": "المعرفة والفهم",
        "title_en": "Knowledge and Understanding",
        "domain": "knowledge",
        "bloom_level": "analyze",
        "accreditation_tag": "SO-1",
        "parent_glo_code": "GLO2",
        "description": (
            "القدرة على تحديد وصياغة وحل المشكلات الهندسية المعقدة من خلال تطبيق "
            "مبادئ الهندسة والعلوم والرياضيات."
        ),
        "sort_order": 10,
    },
    {
        "code": "SO2",
        "title_ar": "التطبيق والابتكار",
        "title_en": "Application and Innovation",
        "domain": "skills",
        "bloom_level": "create",
        "accreditation_tag": "SO-2",
        "parent_glo_code": "GLO3",
        "description": (
            "القدرة على تطبيق التصميم الهندسي لإنتاج حلول تلبي الاحتياجات المحددة مع "
            "مراعاة الصحة العامة والسلامة والرفاهية، وكذلك العوامل العالمية والثقافية "
            "والاجتماعية والبيئية والاقتصادية."
        ),
        "sort_order": 20,
    },
    {
        "code": "SO3",
        "title_ar": "التواصل",
        "title_en": "Communication",
        "domain": "professional",
        "bloom_level": "apply",
        "accreditation_tag": "SO-3",
        "parent_glo_code": "GLO6",
        "description": "القدرة على التواصل الفعال مع مجموعة من الجماهير المختلفة.",
        "sort_order": 30,
    },
    {
        "code": "SO4",
        "title_ar": "التقييم والمسؤولية",
        "title_en": "Evaluation and Responsibility",
        "domain": "values",
        "bloom_level": "evaluate",
        "accreditation_tag": "SO-4",
        "parent_glo_code": "GLO8",
        "description": (
            "القدرة على إدراك المسؤوليات الأخلاقية والمهنية في المواقف الهندسية "
            "وإصدار أحكام مستنيرة."
        ),
        "sort_order": 40,
    },
    {
        "code": "SO5",
        "title_ar": "العمل الجماعي",
        "title_en": "Teamwork",
        "domain": "professional",
        "bloom_level": "apply",
        "accreditation_tag": "SO-5",
        "parent_glo_code": "GLO5",
        "description": (
            "القدرة على العمل بفعالية في فريق يوفر أعضاؤه القيادة، ويخلقون بيئة "
            "تعاونية وشاملة، ويحددون الأهداف، ويخططون للمهام، ويلبون الأهداف."
        ),
        "sort_order": 50,
    },
    {
        "code": "SO6",
        "title_ar": "التحليل",
        "title_en": "Analysis",
        "domain": "skills",
        "bloom_level": "analyze",
        "accreditation_tag": "SO-6",
        "parent_glo_code": "GLO4",
        "description": (
            "القدرة على تطوير وإجراء التجارب المناسبة، وتحليل وتفسير البيانات، "
            "واستخدام الحكم الهندسي لاستخلاص الاستنتاجات."
        ),
        "sort_order": 60,
    },
)

# goal_code -> outcome_codes
MECH_GOAL_OUTCOME_LINKS: dict[str, tuple[str, ...]] = {
    "PG1": ("SO1", "SO2"),
    "PG2": ("SO1", "SO6"),
    "PG3": ("SO4", "SO2"),
    "PG4": ("SO3", "SO5"),
}


def _row_id(row: Any) -> int | None:
    if not row:
        return None
    if hasattr(row, "keys"):
        return int(row["id"])
    return int(row[0])


def _upsert_goal(
    cur,
    program_id: int,
    goal: dict[str, Any],
    *,
    merge: bool,
) -> tuple[str, int | None]:
    code = (goal.get("code") or "").strip()
    if not code:
        return "skip", None
    exists = cur.execute(
        "SELECT id FROM program_goals WHERE program_id = ? AND code = ?",
        (int(program_id), code),
    ).fetchone()
    gid = _row_id(exists)
    if gid and merge:
        cur.execute(
            """
            UPDATE program_goals SET
                title_ar = ?, title_en = ?, description = ?,
                sort_order = ?, is_active = 1
            WHERE id = ?
            """,
            (
                goal.get("title_ar") or code,
                goal.get("title_en") or "",
                goal.get("description") or "",
                int(goal.get("sort_order") or 0),
                gid,
            ),
        )
        return "updated", gid
    if gid:
        return "skipped", gid
    cur.execute(
        """
        INSERT INTO program_goals (
            program_id, code, title_ar, title_en, description,
            sort_order, governance_status, is_active
        ) VALUES (?, ?, ?, ?, ?, ?, 'approved', 1)
        """,
        (
            int(program_id),
            code,
            goal.get("title_ar") or code,
            goal.get("title_en") or "",
            goal.get("description") or "",
            int(goal.get("sort_order") or 0),
        ),
    )
    row = cur.execute(
        "SELECT id FROM program_goals WHERE program_id = ? AND code = ?",
        (int(program_id), code),
    ).fetchone()
    return "inserted", _row_id(row)


def _upsert_outcome(
    cur,
    program_id: int,
    oc: dict[str, Any],
    *,
    merge: bool,
) -> tuple[str, int | None]:
    code = (oc.get("code") or "").strip()
    if not code:
        return "skip", None
    exists = cur.execute(
        "SELECT id FROM program_learning_outcomes WHERE program_id = ? AND code = ?",
        (int(program_id), code),
    ).fetchone()
    oid = _row_id(exists)
    if oid and merge:
        cur.execute(
            """
            UPDATE program_learning_outcomes SET
                title_ar = ?, title_en = ?, description = ?,
                domain = ?, bloom_level = ?, accreditation_tag = ?,
                parent_glo_code = ?, sort_order = ?, is_active = 1
            WHERE id = ?
            """,
            (
                oc.get("title_ar") or code,
                oc.get("title_en") or "",
                oc.get("description") or "",
                oc.get("domain") or "skills",
                oc.get("bloom_level") or "",
                oc.get("accreditation_tag") or "",
                oc.get("parent_glo_code") or "",
                int(oc.get("sort_order") or 0),
                oid,
            ),
        )
        return "updated", oid
    if oid:
        return "skipped", oid
    cur.execute(
        """
        INSERT INTO program_learning_outcomes (
            program_id, code, title_ar, title_en, description,
            domain, bloom_level, performance_indicator, accreditation_tag,
            parent_glo_code, sort_order, governance_status, version, effective_from, is_active
        ) VALUES (?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?, 'approved', 1, '', 1)
        """,
        (
            int(program_id),
            code,
            oc.get("title_ar") or code,
            oc.get("title_en") or "",
            oc.get("description") or "",
            oc.get("domain") or "skills",
            oc.get("bloom_level") or "",
            oc.get("accreditation_tag") or "MECH-SO",
            oc.get("parent_glo_code") or "",
            int(oc.get("sort_order") or 0),
        ),
    )
    row = cur.execute(
        "SELECT id FROM program_learning_outcomes WHERE program_id = ? AND code = ?",
        (int(program_id), code),
    ).fetchone()
    return "inserted", _row_id(row)


def _sync_goal_outcome_links(cur, program_id: int) -> int:
    goal_rows = cur.execute(
        """
        SELECT id, code FROM program_goals
        WHERE program_id = ? AND COALESCE(is_active, 1) = 1
        """,
        (int(program_id),),
    ).fetchall()
    outcome_rows = cur.execute(
        """
        SELECT id, code FROM program_learning_outcomes
        WHERE program_id = ? AND COALESCE(is_active, 1) = 1
        """,
        (int(program_id),),
    ).fetchall()
    goals_by_code = {
        (r["code"] if hasattr(r, "keys") else r[1]): int(
            r["id"] if hasattr(r, "keys") else r[0]
        )
        for r in goal_rows or []
    }
    outcomes_by_code = {
        (r["code"] if hasattr(r, "keys") else r[1]): int(
            r["id"] if hasattr(r, "keys") else r[0]
        )
        for r in outcome_rows or []
    }
    linked = 0
    for gcode, socodes in MECH_GOAL_OUTCOME_LINKS.items():
        gid = goals_by_code.get(gcode)
        if not gid:
            continue
        for soc in socodes:
            oid = outcomes_by_code.get(soc)
            if not oid:
                continue
            dup = cur.execute(
                """
                SELECT 1 FROM program_goal_outcome_links
                WHERE goal_id = ? AND outcome_id = ?
                """,
                (gid, oid),
            ).fetchone()
            if not dup:
                cur.execute(
                    """
                    INSERT INTO program_goal_outcome_links (goal_id, outcome_id)
                    VALUES (?, ?)
                    """,
                    (gid, oid),
                )
                linked += 1
    return linked


def import_mech_program_profile(
    cur,
    program_id: int,
    *,
    merge: bool = True,
    sync_links: bool = True,
    actor: str = "",
) -> dict[str, Any]:
    """تحميل أهداف ومخرجات ميكانيك الرسمية + ربط PG↔SO."""
    ctx = cur.execute(
        """
        SELECT p.id, UPPER(TRIM(d.code)) AS department_code,
               COALESCE(p.track_group, '') AS track_group
        FROM programs p
        JOIN departments d ON d.id = p.department_id
        WHERE p.id = ?
        """,
        (int(program_id),),
    ).fetchone()
    if not ctx:
        return {"status": "error", "message": "البرنامج غير موجود"}
    dept = ctx["department_code"] if hasattr(ctx, "keys") else ctx[1]
    if str(dept or "").upper() != "MECH":
        return {
            "status": "error",
            "message": "القالب مخصص لبرامج قسم الهندسة الميكانيكية فقط.",
        }

    goals_stats = {"inserted": 0, "updated": 0, "skipped": 0}
    for g in MECH_PROGRAM_GOALS:
        action, _ = _upsert_goal(cur, program_id, g, merge=merge)
        goals_stats[action if action in goals_stats else "skipped"] += 1

    outcomes_stats = {"inserted": 0, "updated": 0, "skipped": 0}
    for oc in MECH_STUDENT_OUTCOMES:
        action, _ = _upsert_outcome(cur, program_id, oc, merge=merge)
        outcomes_stats[action if action in outcomes_stats else "skipped"] += 1

    links_count = 0
    if sync_links:
        links_count = _sync_goal_outcome_links(cur, program_id)

    return {
        "status": "ok",
        "program_id": program_id,
        "goals": goals_stats,
        "outcomes": outcomes_stats,
        "links_synced": links_count,
        "actor": actor,
    }


def propagate_mech_profile_to_tracks(
    cur,
    base_program_id: int,
    *,
    merge: bool = True,
    actor: str = "",
) -> dict[str, Any]:
    """نسخ أهداف البرنامج الأساسي إلى شعب MECH-PWR/MFG/DES (بالرمز)."""
    base = cur.execute(
        """
        SELECT p.id, UPPER(TRIM(d.code)) AS dept, COALESCE(p.track_group,'') AS tg,
               UPPER(TRIM(p.code)) AS pcode
        FROM programs p
        JOIN departments d ON d.id = p.department_id
        WHERE p.id = ?
        """,
        (int(base_program_id),),
    ).fetchone()
    if not base:
        return {"status": "error", "message": "البرنامج الأساسي غير موجود"}
    dept = base["dept"] if hasattr(base, "keys") else base[1]
    tg = (base["tg"] if hasattr(base, "keys") else base[2] or "").strip()
    if str(dept).upper() != "MECH" or tg:
        return {
            "status": "error",
            "message": "يجب أن يكون البرنامج الأساسي MECH بلا شعبة (track_group فارغ).",
        }

    track_rows = cur.execute(
        """
        SELECT p.id, p.code FROM programs p
        JOIN departments d ON d.id = p.department_id
        WHERE d.id = (SELECT department_id FROM programs WHERE id = ?)
          AND COALESCE(p.track_group,'') <> ''
          AND COALESCE(p.is_active, 1) = 1
        """,
        (int(base_program_id),),
    ).fetchall()

    propagated: list[dict[str, Any]] = []
    for tr in track_rows or []:
        tid = int(tr["id"] if hasattr(tr, "keys") else tr[0])
        tcode = tr["code"] if hasattr(tr, "keys") else tr[1]
        res = import_mech_program_profile(
            cur, tid, merge=merge, sync_links=True, actor=actor
        )
        propagated.append({"program_id": tid, "code": tcode, "result": res})

    return {
        "status": "ok",
        "base_program_id": base_program_id,
        "tracks": propagated,
        "actor": actor,
    }


def outcome_has_active_links(cur, outcome_id: int) -> bool:
    checks = (
        (
            "SELECT 1 FROM plo_course_master_links WHERE outcome_id = ? LIMIT 1",
            (int(outcome_id),),
        ),
        (
            "SELECT 1 FROM program_course_learning_outcomes WHERE outcome_id = ? LIMIT 1",
            (int(outcome_id),),
        ),
        (
            "SELECT 1 FROM clo_plo_links WHERE outcome_id = ? LIMIT 1",
            (int(outcome_id),),
        ),
        (
            "SELECT 1 FROM program_goal_outcome_links WHERE outcome_id = ? LIMIT 1",
            (int(outcome_id),),
        ),
        (
            "SELECT 1 FROM section_ilo_assessments WHERE outcome_id = ? LIMIT 1",
            (int(outcome_id),),
        ),
    )
    for sql, params in checks:
        try:
            if cur.execute(sql, params).fetchone():
                return True
        except Exception:
            pass
    return False


def goal_has_active_links(cur, goal_id: int) -> bool:
    row = cur.execute(
        "SELECT 1 FROM program_goal_outcome_links WHERE goal_id = ? LIMIT 1",
        (int(goal_id),),
    ).fetchone()
    return bool(row)
