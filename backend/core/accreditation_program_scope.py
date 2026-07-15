"""نطاق اعتماد برامجي — برنامج أكاديمي (اليوم = القسم؛ لاحقاً مسار/شعبة)."""

from __future__ import annotations

from typing import Any

from backend.database.database import is_postgresql, table_exists


def _row_val(row, idx: int = 0, key: str | None = None):
    if row is None:
        return None
    if key and hasattr(row, "keys"):
        try:
            return row[key]
        except (KeyError, IndexError, TypeError):
            pass
    try:
        return row[idx]
    except (KeyError, IndexError, TypeError):
        return None


def _as_id(row, *, idx: int = 0, key: str = "id") -> int | None:
    v = _row_val(row, idx, key)
    return int(v) if v is not None else None


def ensure_accreditation_program_columns(conn) -> None:
    """إضافة program_id اختياري لجداول الاعتماد (ترحيل خفيف)."""
    from backend.database.database import fetch_table_columns, is_postgresql

    tables = (
        "accreditation_assessments",
        "accreditation_evidence",
        "accreditation_manual_inputs",
        "accreditation_improvement_plans",
        "accreditation_evidence_bindings",
    )
    pg = is_postgresql()
    cur = conn.cursor()
    for table in tables:
        try:
            cols = {c.lower() for c in fetch_table_columns(conn, table)}
        except Exception:
            continue
        if "program_id" in cols:
            continue
        try:
            if pg:
                cur.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS program_id BIGINT")
            else:
                cur.execute(f"ALTER TABLE {table} ADD COLUMN program_id INTEGER")
        except Exception:
            pass
    try:
        conn.commit()
    except Exception:
        pass


def has_accreditation_program_id_column(conn, table: str = "accreditation_assessments") -> bool:
    from backend.database.database import fetch_table_columns

    try:
        cols = {c.lower() for c in fetch_table_columns(conn, table)}
    except Exception:
        return False
    return "program_id" in cols


def list_accreditation_programs(conn) -> list[dict[str, Any]]:
    """برامج الاعتماد البرامجي المتاحة (الأساس النشط لكل قسم أولاً)."""
    if not table_exists(conn, "programs") or not table_exists(conn, "departments"):
        return []
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT p.id AS program_id, p.code AS program_code, p.name_ar AS program_name_ar,
               COALESCE(p.track_group, '') AS track_group, COALESCE(p.is_active, 1) AS is_active,
               d.id AS department_id, d.code AS department_code, d.name_ar AS department_name_ar
        FROM programs p
        INNER JOIN departments d ON d.id = p.department_id
        WHERE COALESCE(d.is_active, 1) = 1
        ORDER BY d.code,
                 CASE WHEN TRIM(COALESCE(p.track_group, '')) = '' THEN 0 ELSE 1 END,
                 COALESCE(p.is_active, 1) DESC, p.code
        """
    ).fetchall() or []
    out: list[dict[str, Any]] = []
    for r in rows:
        if hasattr(r, "keys"):
            tg = (r["track_group"] or "").strip()
            active = int(r["is_active"] or 0)
            dept_name = r["department_name_ar"] or r["department_code"]
            pname = r["program_name_ar"] or r["program_code"]
            item = {
                "program_id": int(r["program_id"]),
                "program_code": r["program_code"],
                "program_name_ar": pname,
                "track_group": tg,
                "is_base_program": tg == "",
                "is_active": active == 1,
                "department_id": int(r["department_id"]),
                "department_code": r["department_code"],
                "department_name_ar": dept_name,
                "label_ar": pname if tg else dept_name,
                "scope_ready": active == 1 and tg == "",
            }
        else:
            tg = (r[3] or "").strip()
            active = int(r[4] or 0)
            dept_name = r[7] or r[6]
            pname = r[2] or r[1]
            item = {
                "program_id": int(r[0]),
                "program_code": r[1],
                "program_name_ar": pname,
                "track_group": tg,
                "is_base_program": tg == "",
                "is_active": active == 1,
                "department_id": int(r[5]),
                "department_code": r[6],
                "department_name_ar": dept_name,
                "label_ar": pname if tg else dept_name,
                "scope_ready": active == 1 and tg == "",
            }
        out.append(item)
    return out


def ensure_default_program_for_department(conn, department_id: int) -> dict[str, Any]:
    """
    يضمن برنامجاً أساسياً للقسم (بدون شعبة).
    اليوم: برنامج واحد لكل قسم. لاحقاً: تُضاف برامج مسارات بنفس الجدول.
    """
    dept_id = int(department_id)
    cur = conn.cursor()
    dept = cur.execute(
        "SELECT id, code, name_ar, name_en FROM departments WHERE id = ? LIMIT 1",
        (dept_id,),
    ).fetchone()
    if not dept:
        return {"status": "error", "message": f"قسم #{dept_id} غير موجود"}

    if hasattr(dept, "keys"):
        dept_code = (dept["code"] or "").strip().upper()
        name_ar = (dept["name_ar"] or dept_code).strip()
        name_en = (dept["name_en"] or dept_code).strip()
    else:
        dept_code = (dept[1] or "").strip().upper()
        name_ar = (dept[2] or dept_code).strip()
        name_en = (dept[3] or dept_code).strip()

    try:
        from backend.core.program_tracks import (
            department_has_track_catalog,
            ensure_department_track_programs,
        )

        if department_has_track_catalog(dept_code):
            ensure_department_track_programs(conn, dept_code)
    except Exception:
        pass

    row = cur.execute(
        """
        SELECT id, code, name_ar FROM programs
        WHERE department_id = ?
          AND TRIM(COALESCE(track_group, '')) = ''
        ORDER BY COALESCE(is_active, 1) DESC, id ASC
        LIMIT 1
        """,
        (dept_id,),
    ).fetchone()
    if row:
        pid = _as_id(row)
        code = _row_val(row, 1, "code")
        pname = _row_val(row, 2, "name_ar") or name_ar
        cur.execute(
            "UPDATE programs SET is_active = 1 WHERE id = ? AND COALESCE(is_active, 1) = 0",
            (pid,),
        )
        conn.commit()
        return {
            "status": "ok",
            "action": "existing",
            "program_id": pid,
            "program_code": code,
            "program_name_ar": pname,
            "department_id": dept_id,
            "department_code": dept_code,
            "department_name_ar": name_ar,
            "is_base_program": True,
        }

    row = cur.execute(
        """
        SELECT id, code, name_ar, COALESCE(track_group, '') AS track_group
        FROM programs
        WHERE department_id = ? AND COALESCE(is_active, 1) = 1
        ORDER BY CASE WHEN TRIM(COALESCE(track_group, '')) = '' THEN 0 ELSE 1 END, id
        LIMIT 1
        """,
        (dept_id,),
    ).fetchone()
    if row:
        tg = str(_row_val(row, 3, "track_group") or "").strip()
        return {
            "status": "ok",
            "action": "existing_fallback",
            "program_id": _as_id(row),
            "program_code": _row_val(row, 1, "code"),
            "program_name_ar": _row_val(row, 2, "name_ar") or name_ar,
            "department_id": dept_id,
            "department_code": dept_code,
            "department_name_ar": name_ar,
            "is_base_program": tg == "",
        }

    pg = is_postgresql()
    code = dept_code or f"DEPT{dept_id}"
    if pg:
        cur.execute(
            """
            INSERT INTO programs
            (department_id, code, name_ar, name_en, phase, track_group, min_total_units, is_active)
            VALUES (?, ?, ?, ?, 'major', '', 155, 1)
            RETURNING id
            """,
            (dept_id, code, name_ar, name_en),
        )
        pid = _as_id(cur.fetchone())
    else:
        cur.execute(
            """
            INSERT INTO programs
            (department_id, code, name_ar, name_en, phase, track_group, min_total_units, is_active)
            VALUES (?, ?, ?, ?, 'major', '', 155, 1)
            """,
            (dept_id, code, name_ar, name_en),
        )
        pid = int(
            getattr(cur, "lastrowid", None)
            or cur.execute("SELECT last_insert_rowid()").fetchone()[0]
        )
    conn.commit()
    return {
        "status": "ok",
        "action": "created",
        "program_id": pid,
        "program_code": code,
        "program_name_ar": name_ar,
        "department_id": dept_id,
        "department_code": dept_code,
        "department_name_ar": name_ar,
        "is_base_program": True,
    }


def _program_scope_from_row(row) -> dict[str, Any]:
    if hasattr(row, "keys"):
        tg = (row["track_group"] or "").strip()
        dept_name = row["department_name_ar"] or row["department_code"]
        pname = row["program_name_ar"] or row["program_code"]
        return {
            "map_scope_key": "prog",
            "org_level": "program",
            "department_id": int(row["department_id"]),
            "program_id": int(row["program_id"]),
            "program_code": row["program_code"],
            "program_name_ar": pname,
            "department_code": row["department_code"],
            "department_name_ar": dept_name,
            "label_ar": pname if tg else dept_name,
            "is_base_program": tg == "",
        }
    tg = (row[3] or "").strip()
    dept_name = row[6] or row[5]
    pname = row[2] or row[1]
    return {
        "map_scope_key": "prog",
        "org_level": "program",
        "department_id": int(row[4]),
        "program_id": int(row[0]),
        "program_code": row[1],
        "program_name_ar": pname,
        "department_code": row[5],
        "department_name_ar": dept_name,
        "label_ar": pname if tg else dept_name,
        "is_base_program": tg == "",
    }


def resolve_accreditation_org_scope(
    conn,
    *,
    map_scope_key: str,
    department_id: int | None = None,
    program_id: int | None = None,
) -> dict[str, Any]:
    """
    مؤسسي → كلية (بدون قسم/برنامج).
    برامجي → برنامج واحد (اليوم = برنامج الأساس للقسم).
    """
    scope = (map_scope_key or "inst").strip().lower()

    if scope in ("inst", "institutional"):
        return {
            "map_scope_key": "inst",
            "org_level": "college",
            "department_id": None,
            "program_id": None,
            "program_code": None,
            "program_name_ar": None,
            "department_code": None,
            "department_name_ar": None,
            "label_ar": "كلية (اعتماد مؤسسي — جميع الأقسام)",
            "is_base_program": None,
        }

    if scope == "internal":
        return {
            "map_scope_key": "internal",
            "org_level": "department" if department_id is not None else "college",
            "department_id": int(department_id) if department_id is not None else None,
            "program_id": None,
            "program_code": None,
            "program_name_ar": None,
            "department_code": None,
            "department_name_ar": None,
            "label_ar": (
                f"قسم #{department_id}"
                if department_id is not None
                else "كلية (كتالوج داخلي — أرشيف)"
            ),
            "is_base_program": None,
            "archived": True,
        }

    # برامجي
    cur = conn.cursor()
    pid = int(program_id) if program_id is not None else None
    dept_id = int(department_id) if department_id is not None else None

    if pid is not None and table_exists(conn, "programs"):
        row = cur.execute(
            """
            SELECT p.id AS program_id, p.code AS program_code, p.name_ar AS program_name_ar,
                   COALESCE(p.track_group, '') AS track_group,
                   d.id AS department_id, d.code AS department_code, d.name_ar AS department_name_ar
            FROM programs p
            INNER JOIN departments d ON d.id = p.department_id
            WHERE p.id = ?
            LIMIT 1
            """,
            (pid,),
        ).fetchone()
        if row:
            return _program_scope_from_row(row)

    if dept_id is None:
        row = cur.execute(
            """
            SELECT id FROM departments
            WHERE COALESCE(is_active, 1) = 1
            ORDER BY code
            LIMIT 1
            """
        ).fetchone()
        if not row:
            return {
                "map_scope_key": "prog",
                "org_level": "program",
                "department_id": None,
                "program_id": None,
                "program_code": None,
                "program_name_ar": None,
                "department_code": None,
                "department_name_ar": None,
                "label_ar": "لم يُحدد برنامج — لا أقسام نشطة",
                "is_base_program": None,
                "needs_program_selection": True,
            }
        dept_id = _as_id(row)

    ensured = ensure_default_program_for_department(conn, dept_id)
    if ensured.get("status") != "ok":
        return {
            "map_scope_key": "prog",
            "org_level": "program",
            "department_id": dept_id,
            "program_id": None,
            "program_code": None,
            "program_name_ar": None,
            "department_code": ensured.get("department_code"),
            "department_name_ar": None,
            "label_ar": ensured.get("message") or "تعذر تحديد البرنامج",
            "is_base_program": None,
            "error": ensured.get("message"),
        }

    return {
        "map_scope_key": "prog",
        "org_level": "program",
        "department_id": int(ensured["department_id"]),
        "program_id": int(ensured["program_id"]),
        "program_code": ensured.get("program_code"),
        "program_name_ar": ensured.get("program_name_ar"),
        "department_code": ensured.get("department_code"),
        "department_name_ar": ensured.get("department_name_ar"),
        "label_ar": ensured.get("department_name_ar")
        or ensured.get("program_name_ar")
        or "برنامج",
        "is_base_program": bool(ensured.get("is_base_program", True)),
    }
