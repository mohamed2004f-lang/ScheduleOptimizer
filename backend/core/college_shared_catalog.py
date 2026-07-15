"""سجل المقررات المشتركة بين الأقسام — بيانات مرجعية ومزامنة تشغيلية."""

from __future__ import annotations

import re
from typing import Any

from backend.core.academic_pathway import normalize_requirement_scope
from backend.core.course_master_catalog import (
    LIFECYCLE_SHARED,
    ensure_course_master_catalog_schema,
    normalize_catalog_lifecycle,
)
from backend.core.department_scope_policy import (
    major_program_id_for_department,
    resolve_college_general_department_id,
)
from backend.database.database import fetch_table_columns, is_postgresql

SHARE_TYPES = ("unified", "multi_code", "subset")

SHARE_TYPE_LABELS = {
    "unified": "موحّد — نفس الاسم والرمز (GS)",
    "multi_code": "مشترك كلية — رمز مختلف لكل قسم",
    "subset": "مشترك بين أقسام محددة",
}


def ensure_college_shared_catalog_schema(conn) -> None:
    ensure_course_master_catalog_schema(conn)
    cur = conn.cursor()
    if is_postgresql():
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS college_shared_catalog (
                id BIGSERIAL PRIMARY KEY,
                catalog_key TEXT NOT NULL UNIQUE,
                share_type TEXT NOT NULL DEFAULT 'unified'
                    CHECK (share_type IN ('unified', 'multi_code', 'subset')),
                canonical_course_name TEXT NOT NULL,
                canonical_course_code TEXT NOT NULL DEFAULT '',
                units INTEGER NOT NULL DEFAULT 0,
                requirement_scope TEXT NOT NULL DEFAULT 'pre_track',
                course_master_id BIGINT,
                notes TEXT DEFAULT '',
                is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS college_shared_catalog_depts (
                id BIGSERIAL PRIMARY KEY,
                catalog_id BIGINT NOT NULL,
                department_id BIGINT NOT NULL,
                plan_course_code TEXT NOT NULL DEFAULT '',
                plan_course_name_override TEXT NOT NULL DEFAULT '',
                program_course_id BIGINT,
                is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
                UNIQUE (catalog_id, department_id),
                CONSTRAINT cscd_catalog_fk FOREIGN KEY (catalog_id)
                    REFERENCES college_shared_catalog(id) ON DELETE CASCADE,
                CONSTRAINT cscd_department_fk FOREIGN KEY (department_id)
                    REFERENCES departments(id) ON DELETE CASCADE
            )
            """
        )
    else:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS college_shared_catalog (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                catalog_key TEXT NOT NULL UNIQUE,
                share_type TEXT NOT NULL DEFAULT 'unified',
                canonical_course_name TEXT NOT NULL,
                canonical_course_code TEXT NOT NULL DEFAULT '',
                units INTEGER NOT NULL DEFAULT 0,
                requirement_scope TEXT NOT NULL DEFAULT 'pre_track',
                course_master_id INTEGER,
                notes TEXT DEFAULT '',
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS college_shared_catalog_depts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                catalog_id INTEGER NOT NULL,
                department_id INTEGER NOT NULL,
                plan_course_code TEXT NOT NULL DEFAULT '',
                plan_course_name_override TEXT NOT NULL DEFAULT '',
                program_course_id INTEGER,
                is_active INTEGER NOT NULL DEFAULT 1,
                UNIQUE (catalog_id, department_id),
                FOREIGN KEY (catalog_id) REFERENCES college_shared_catalog(id) ON DELETE CASCADE,
                FOREIGN KEY (department_id) REFERENCES departments(id) ON DELETE CASCADE
            )
            """
        )


def _row_id(row) -> int | None:
    if not row:
        return None
    if hasattr(row, "keys"):
        try:
            v = row["id"]
        except (KeyError, IndexError, TypeError):
            v = row[0]
        return int(v) if v is not None else None
    return int(row[0])


def _slug_key(name: str, code: str = "") -> str:
    base = (code or name or "shared").strip().lower()
    base = re.sub(r"[^\w\u0600-\u06ff]+", "_", base, flags=re.UNICODE)
    base = re.sub(r"_+", "_", base).strip("_")
    return (base or "shared_course")[:64]


def list_specialty_departments(conn) -> list[dict[str, Any]]:
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT id, code, name_ar, name_en
        FROM departments
        WHERE COALESCE(is_active, 1) = 1
          AND UPPER(TRIM(COALESCE(code, ''))) <> 'GENERAL'
        ORDER BY name_ar, id
        """
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        if hasattr(r, "keys"):
            out.append(
                {
                    "id": int(r["id"]),
                    "code": r["code"] or "",
                    "name_ar": r["name_ar"] or "",
                    "name_en": (r["name_en"] if "name_en" in r.keys() else "") or "",
                }
            )
        else:
            out.append(
                {
                    "id": int(r[0]),
                    "code": r[1] or "",
                    "name_ar": r[2] or "",
                    "name_en": r[3] or "",
                }
            )
    return out


def _catalog_row_to_dict(row) -> dict[str, Any]:
    if hasattr(row, "keys"):
        d = {k: row[k] for k in row.keys()}
    else:
        keys = [
            "id",
            "catalog_key",
            "share_type",
            "canonical_course_name",
            "canonical_course_code",
            "units",
            "requirement_scope",
            "course_master_id",
            "notes",
            "is_active",
            "created_at",
            "updated_at",
        ]
        d = {keys[i]: row[i] for i in range(len(row))}
    d["share_type_label"] = SHARE_TYPE_LABELS.get(str(d.get("share_type") or ""), "")
    d["is_active"] = bool(int(d.get("is_active") or 0))
    return d


def list_catalog_entries(conn, *, include_inactive: bool = False) -> list[dict[str, Any]]:
    ensure_college_shared_catalog_schema(conn)
    cur = conn.cursor()
    q = "SELECT * FROM college_shared_catalog"
    if not include_inactive:
        q += " WHERE COALESCE(is_active, 1) = 1"
    q += " ORDER BY canonical_course_name, id"
    rows = cur.execute(q).fetchall()
    items = [_catalog_row_to_dict(r) for r in rows]
    if not items:
        return []
    ids = [int(x["id"]) for x in items]
    ph = ",".join("?" for _ in ids)
    dept_rows = cur.execute(
        f"""
        SELECT d.catalog_id, d.department_id, d.plan_course_code, d.plan_course_name_override,
               d.program_course_id, d.is_active, dep.code AS department_code, dep.name_ar AS department_name
        FROM college_shared_catalog_depts d
        INNER JOIN departments dep ON dep.id = d.department_id
        WHERE d.catalog_id IN ({ph})
        ORDER BY dep.name_ar
        """,
        tuple(ids),
    ).fetchall()
    by_cat: dict[int, list[dict]] = {i: [] for i in ids}
    for r in dept_rows:
        if hasattr(r, "keys"):
            cid = int(r["catalog_id"])
            by_cat.setdefault(cid, []).append(
                {
                    "department_id": int(r["department_id"]),
                    "department_code": r["department_code"] or "",
                    "department_name": r["department_name"] or "",
                    "plan_course_code": r["plan_course_code"] or "",
                    "plan_course_name_override": r["plan_course_name_override"] or "",
                    "program_course_id": r["program_course_id"],
                    "is_active": bool(int(r["is_active"] or 0)),
                }
            )
        else:
            cid = int(r[0])
            by_cat.setdefault(cid, []).append(
                {
                    "department_id": int(r[1]),
                    "plan_course_code": r[2] or "",
                    "plan_course_name_override": r[3] or "",
                    "program_course_id": r[4],
                    "is_active": bool(int(r[5] or 0)),
                    "department_code": r[6] or "",
                    "department_name": r[7] or "",
                }
            )
    for item in items:
        item["departments"] = by_cat.get(int(item["id"]), [])
        item["department_count"] = len([x for x in item["departments"] if x.get("is_active")])
    return items


def get_catalog_entry(conn, catalog_id: int) -> dict[str, Any] | None:
    items = [x for x in list_catalog_entries(conn, include_inactive=True) if int(x["id"]) == int(catalog_id)]
    return items[0] if items else None


def _normalize_departments_payload(
    conn,
    share_type: str,
    canonical_name: str,
    canonical_code: str,
    departments: list[dict] | None,
) -> list[dict[str, Any]]:
    st = (share_type or "unified").strip().lower()
    if st not in SHARE_TYPES:
        raise ValueError("نوع المشاركة غير صالح.")
    raw = list(departments or [])
    if st == "unified":
        all_deps = list_specialty_departments(conn)
        code = (canonical_code or "").strip()
        if not code:
            raise ValueError("الرمز المرجعي مطلوب للمقرر الموحّد.")
        out: list[dict[str, Any]] = []
        active_ids = {
            int(x.get("department_id"))
            for x in raw
            if x.get("is_active", True) and x.get("department_id") not in (None, "")
        }
        for dep in all_deps:
            did = int(dep["id"])
            if raw and did not in active_ids and active_ids:
                continue
            override = ""
            for x in raw:
                if int(x.get("department_id") or -1) == did:
                    override = (x.get("plan_course_name_override") or "").strip()
                    break
            out.append(
                {
                    "department_id": did,
                    "plan_course_code": code,
                    "plan_course_name_override": override,
                    "is_active": 1,
                }
            )
        if not out:
            raise ValueError("لا توجد أقسام نشطة للمشاركة.")
        return out
    if not raw:
        raise ValueError("حدّد قسماً واحداً على الأقل.")
    out = []
    for x in raw:
        did = x.get("department_id")
        if did in (None, ""):
            continue
        pcode = (x.get("plan_course_code") or canonical_code or "").strip()
        if not pcode:
            raise ValueError(f"رمز الخطة مطلوب للقسم {did}.")
        out.append(
            {
                "department_id": int(did),
                "plan_course_code": pcode,
                "plan_course_name_override": (x.get("plan_course_name_override") or "").strip(),
                "is_active": 1 if x.get("is_active", True) else 0,
            }
        )
    if not out:
        raise ValueError("حدّد قسماً واحداً على الأقل.")
    if st == "subset" and len([x for x in out if x["is_active"]]) < 2:
        raise ValueError("المقرر المشترك بين أقسام محددة يتطلب قسمين على الأقل.")
    return out


def _upsert_course_master(cur, title: str, units: int) -> int:
    title = (title or "").strip()
    row = cur.execute(
        "SELECT id FROM course_master WHERE lower(trim(title_ar)) = lower(trim(?)) LIMIT 1",
        (title,),
    ).fetchone()
    if row:
        mid = _row_id(row)
        cur.execute(
            """
            UPDATE course_master
            SET default_units = ?, catalog_lifecycle = ?, title_ar = ?
            WHERE id = ?
            """,
            (max(0, int(units)), LIFECYCLE_SHARED, title, int(mid)),
        )
        return int(mid)
    if is_postgresql():
        cur.execute(
            """
            INSERT INTO course_master (title_ar, default_units, grading_mode, assessment_type, catalog_lifecycle)
            VALUES (?, ?, 'partial_final', 'theoretical', ?)
            RETURNING id
            """,
            (title, max(0, int(units)), LIFECYCLE_SHARED),
        )
        return int(_row_id(cur.fetchone()))
    cur.execute(
        """
        INSERT INTO course_master (title_ar, default_units, grading_mode, assessment_type, catalog_lifecycle)
        VALUES (?, ?, 'partial_final', 'theoretical', ?)
        """,
        (title, max(0, int(units)), LIFECYCLE_SHARED),
    )
    return int(getattr(cur, "lastrowid", None) or cur.execute("SELECT last_insert_rowid()").fetchone()[0])


def _upsert_operational_course(conn, cur, *, name: str, code: str, units: int, gen_dept_id: int, master_id: int) -> None:
    cols = set(fetch_table_columns(conn, "courses") or [])
    cname = (name or "").strip()
    ccode = (code or "").strip()
    if not cname:
        raise ValueError("اسم المقرر مطلوب.")
    if "owning_department_id" in cols and "course_master_id" in cols:
        cur.execute(
            """
            INSERT INTO courses (course_name, course_code, units, owning_department_id, course_master_id)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(course_name) DO UPDATE SET
              course_code = excluded.course_code,
              units = excluded.units,
              course_master_id = excluded.course_master_id,
              owning_department_id = excluded.owning_department_id
            """,
            (cname, ccode, max(0, int(units)), int(gen_dept_id), int(master_id)),
        )
    elif "owning_department_id" in cols:
        cur.execute(
            """
            INSERT INTO courses (course_name, course_code, units, owning_department_id)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(course_name) DO UPDATE SET
              course_code = excluded.course_code,
              units = excluded.units,
              owning_department_id = excluded.owning_department_id
            """,
            (cname, ccode, max(0, int(units)), int(gen_dept_id)),
        )
    else:
        cur.execute(
            """
            INSERT INTO courses (course_name, course_code, units)
            VALUES (?, ?, ?)
            ON CONFLICT(course_name) DO UPDATE SET
              course_code = excluded.course_code,
              units = excluded.units
            """,
            (cname, ccode, max(0, int(units))),
        )


def _upsert_program_course(
    cur,
    *,
    program_id: int,
    master_id: int,
    plan_code: str,
    name_override: str,
    req_scope: str,
    units: int,
) -> int:
    pg = is_postgresql()
    params = (
        int(program_id),
        int(master_id),
        plan_code,
        (name_override or "").strip(),
        req_scope,
        max(0, int(units)),
    )
    if pg:
        cur.execute(
            """
            INSERT INTO program_courses
            (program_id, course_master_id, course_code, course_name_override,
             plan_applicability, requirement_scope, level_no, units_override,
             category, is_required, is_active)
            VALUES (?, ?, ?, ?, 'both', ?, 0, ?, 'required', 1, 1)
            ON CONFLICT (program_id, course_code) DO UPDATE SET
              course_master_id = EXCLUDED.course_master_id,
              course_name_override = EXCLUDED.course_name_override,
              requirement_scope = EXCLUDED.requirement_scope,
              units_override = EXCLUDED.units_override,
              is_active = 1
            RETURNING id
            """,
            params,
        )
        return int(_row_id(cur.fetchone()))
    cur.execute(
        """
        INSERT INTO program_courses
        (program_id, course_master_id, course_code, course_name_override,
         plan_applicability, requirement_scope, level_no, units_override,
         category, is_required, is_active)
        VALUES (?, ?, ?, ?, 'both', ?, 0, ?, 'required', 1, 1)
        ON CONFLICT (program_id, course_code) DO UPDATE SET
          course_master_id = excluded.course_master_id,
          course_name_override = excluded.course_name_override,
          requirement_scope = excluded.requirement_scope,
          units_override = excluded.units_override,
          is_active = 1
        """,
        params,
    )
    row = cur.execute(
        "SELECT id FROM program_courses WHERE program_id = ? AND course_code = ? LIMIT 1",
        (int(program_id), plan_code),
    ).fetchone()
    return int(_row_id(row))


def sync_catalog_entry(conn, catalog_id: int) -> dict[str, Any]:
    entry = get_catalog_entry(conn, int(catalog_id))
    if not entry:
        raise ValueError("السجل غير موجود.")
    if not entry.get("is_active"):
        raise ValueError("السجل غير نشط.")
    gen_id = resolve_college_general_department_id(conn)
    if gen_id is None:
        raise ValueError("قسم GENERAL غير موجود.")
    cur = conn.cursor()
    cname = (entry["canonical_course_name"] or "").strip()
    ccode = (entry["canonical_course_code"] or "").strip()
    units = int(entry.get("units") or 0)
    req_scope = normalize_requirement_scope(entry.get("requirement_scope") or "pre_track")
    master_id = _upsert_course_master(cur, cname, units)
    _upsert_operational_course(
        conn,
        cur,
        name=cname,
        code=ccode,
        units=units,
        gen_dept_id=int(gen_id),
        master_id=int(master_id),
    )
    synced = 0
    dept_rows: list[dict] = []
    for dep in entry.get("departments") or []:
        if not dep.get("is_active"):
            continue
        did = int(dep["department_id"])
        prog_id = major_program_id_for_department(conn, did)
        if prog_id is None:
            continue
        pcode = (dep.get("plan_course_code") or ccode or "").strip()
        if not pcode:
            continue
        pcid = _upsert_program_course(
            cur,
            program_id=int(prog_id),
            master_id=int(master_id),
            plan_code=pcode,
            name_override=(dep.get("plan_course_name_override") or "").strip(),
            req_scope=req_scope,
            units=units,
        )
        cur.execute(
            """
            UPDATE college_shared_catalog_depts
            SET program_course_id = ?
            WHERE catalog_id = ? AND department_id = ?
            """,
            (int(pcid), int(catalog_id), did),
        )
        synced += 1
        dept_rows.append({"department_id": did, "program_course_id": pcid})
    cur.execute(
        """
        UPDATE college_shared_catalog
        SET course_master_id = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (int(master_id), int(catalog_id)),
    )
    return {
        "catalog_id": int(catalog_id),
        "course_master_id": int(master_id),
        "operational_course_name": cname,
        "owning_department_id": int(gen_id),
        "departments_synced": synced,
        "departments": dept_rows,
    }


def save_catalog_entry(conn, payload: dict[str, Any]) -> dict[str, Any]:
    ensure_college_shared_catalog_schema(conn)
    catalog_id = payload.get("id")
    try:
        catalog_id = int(catalog_id) if catalog_id not in (None, "") else None
    except (TypeError, ValueError):
        catalog_id = None
    cname = (payload.get("canonical_course_name") or "").strip()
    if not cname:
        raise ValueError("الاسم الرسمي للمقرر مطلوب.")
    ccode = (payload.get("canonical_course_code") or "").strip()
    share_type = (payload.get("share_type") or "unified").strip().lower()
    if share_type not in SHARE_TYPES:
        raise ValueError("نوع المشاركة غير صالح.")
    units = max(0, int(payload.get("units") or 0))
    req_scope = normalize_requirement_scope(payload.get("requirement_scope") or "pre_track")
    notes = (payload.get("notes") or "").strip()
    catalog_key = (payload.get("catalog_key") or "").strip() or _slug_key(cname, ccode)
    dept_rows = _normalize_departments_payload(
        conn, share_type, cname, ccode, payload.get("departments")
    )
    cur = conn.cursor()
    if catalog_id is None:
        if is_postgresql():
            cur.execute(
                """
                INSERT INTO college_shared_catalog
                (catalog_key, share_type, canonical_course_name, canonical_course_code,
                 units, requirement_scope, notes, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                RETURNING id
                """,
                (catalog_key, share_type, cname, ccode, units, req_scope, notes),
            )
            catalog_id = int(_row_id(cur.fetchone()))
        else:
            cur.execute(
                """
                INSERT INTO college_shared_catalog
                (catalog_key, share_type, canonical_course_name, canonical_course_code,
                 units, requirement_scope, notes, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (catalog_key, share_type, cname, ccode, units, req_scope, notes),
            )
            catalog_id = int(getattr(cur, "lastrowid", None) or cur.execute("SELECT last_insert_rowid()").fetchone()[0])
    else:
        cur.execute(
            """
            UPDATE college_shared_catalog
            SET catalog_key = ?, share_type = ?, canonical_course_name = ?, canonical_course_code = ?,
                units = ?, requirement_scope = ?, notes = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (catalog_key, share_type, cname, ccode, units, req_scope, notes, int(catalog_id)),
        )
    cur.execute("DELETE FROM college_shared_catalog_depts WHERE catalog_id = ?", (int(catalog_id),))
    for dep in dept_rows:
        cur.execute(
            """
            INSERT INTO college_shared_catalog_depts
            (catalog_id, department_id, plan_course_code, plan_course_name_override, is_active)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                int(catalog_id),
                int(dep["department_id"]),
                dep["plan_course_code"],
                dep.get("plan_course_name_override") or "",
                int(dep.get("is_active") or 1),
            ),
        )
    sync_result = sync_catalog_entry(conn, int(catalog_id))
    entry = get_catalog_entry(conn, int(catalog_id))
    return {"entry": entry, "sync": sync_result}


def set_catalog_active(conn, catalog_id: int, *, active: bool) -> None:
    cur = conn.cursor()
    cur.execute(
        "UPDATE college_shared_catalog SET is_active = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (1 if active else 0, int(catalog_id)),
    )
    if cur.rowcount == 0:
        raise ValueError("السجل غير موجود.")


def course_has_usage(conn, course_name: str) -> bool:
    cname = (course_name or "").strip()
    if not cname:
        return False
    from backend.database.database import table_exists

    cur = conn.cursor()
    for table, col in (("registrations", "course_name"), ("grades", "course_name"), ("schedule", "course_name")):
        if not table_exists(conn, table):
            continue
        row = cur.execute(
            f"SELECT 1 FROM {table} WHERE lower(trim({col})) = lower(trim(?)) LIMIT 1",
            (cname,),
        ).fetchone()
        if row:
            return True
    return False


def delete_catalog_entry(conn, catalog_id: int, *, force: bool = False) -> None:
    entry = get_catalog_entry(conn, int(catalog_id))
    if not entry:
        raise ValueError("السجل غير موجود.")
    cname = (entry.get("canonical_course_name") or "").strip()
    if not force and course_has_usage(conn, cname):
        set_catalog_active(conn, int(catalog_id), active=False)
        raise ValueError(
            "المقرر مستخدم في تسجيلات أو درجات أو جدول — تم إيقافه بدلاً من الحذف."
        )
    cur = conn.cursor()
    cur.execute("DELETE FROM college_shared_catalog WHERE id = ?", (int(catalog_id),))


def build_import_template_bytes() -> bytes:
    """قالب Excel للاستيراد (ورقتان: مقررات + أقسام)."""
    import io

    import pandas as pd

    courses = pd.DataFrame(
        [
            {
                "catalog_key": "math_iii",
                "share_type": "unified",
                "canonical_name": "رياضيات III",
                "canonical_code": "GS 201",
                "units": 3,
                "requirement_scope": "pre_track",
                "notes": "",
            },
            {
                "catalog_key": "mech_eng_ii",
                "share_type": "multi_code",
                "canonical_name": "ميكانيكا هندسية II",
                "canonical_code": "ME 205",
                "units": 3,
                "requirement_scope": "pre_track",
                "notes": "مثال — أضف صفوف الأقسام في الورقة الثانية",
            },
        ]
    )
    depts = pd.DataFrame(
        [
            {
                "catalog_key": "mech_eng_ii",
                "department_code": "MECH",
                "plan_course_code": "ME 205",
                "plan_name_override": "",
            },
            {
                "catalog_key": "mech_eng_ii",
                "department_code": "CIVIL",
                "plan_course_code": "CE 205",
                "plan_name_override": "",
            },
        ]
    )
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        courses.to_excel(w, sheet_name="courses", index=False)
        depts.to_excel(w, sheet_name="departments", index=False)
    buf.seek(0)
    return buf.getvalue()


def _resolve_department_id_by_code(conn, code: str) -> int | None:
    c = (code or "").strip().upper()
    if not c:
        return None
    row = conn.cursor().execute(
        "SELECT id FROM departments WHERE UPPER(TRIM(code)) = ? LIMIT 1",
        (c,),
    ).fetchone()
    if not row:
        return None
    return int(row[0] if not hasattr(row, "keys") else row["id"])


def import_catalog_workbook(conn, file_obj) -> dict[str, Any]:
    """استيراد سجل المقررات المشتركة من Excel (ورقة courses + departments)."""
    import pandas as pd

    ensure_college_shared_catalog_schema(conn)
    xls = pd.ExcelFile(file_obj)
    sheet_names = {s.lower(): s for s in xls.sheet_names}
    courses_key = sheet_names.get("courses") or sheet_names.get("مقررات") or xls.sheet_names[0]
    df_c = pd.read_excel(xls, sheet_name=courses_key)
    df_c.columns = [str(c).strip().lower() for c in df_c.columns]
    dept_key = sheet_names.get("departments") or sheet_names.get("اقسام")
    df_d = pd.read_excel(xls, sheet_name=dept_key) if dept_key else pd.DataFrame()
    if not df_d.empty:
        df_d.columns = [str(c).strip().lower() for c in df_d.columns]

    def _col(row, *names, default=""):
        for n in names:
            if n in row.index and pd.notna(row.get(n)):
                return str(row.get(n)).strip()
        return default

    dept_by_key: dict[str, list[dict]] = {}
    if not df_d.empty:
        for _, row in df_d.iterrows():
            key = _col(row, "catalog_key", "key")
            if not key:
                continue
            dep_code = _col(row, "department_code", "dept_code", "code")
            did = _resolve_department_id_by_code(conn, dep_code)
            if did is None:
                raise ValueError(f"قسم غير معروف: {dep_code} (catalog_key={key})")
            dept_by_key.setdefault(key, []).append(
                {
                    "department_id": did,
                    "plan_course_code": _col(row, "plan_course_code", "course_code"),
                    "plan_course_name_override": _col(row, "plan_name_override", "name_override"),
                    "is_active": True,
                }
            )

    imported = 0
    errors: list[str] = []
    for _, row in df_c.iterrows():
        key = _col(row, "catalog_key", "key")
        cname = _col(row, "canonical_name", "course_name", "name")
        if not cname:
            continue
        try:
            units_raw = row.get("units")
            units = int(units_raw) if pd.notna(units_raw) else 0
        except (TypeError, ValueError):
            units = 0
        payload = {
            "catalog_key": key or _slug_key(cname, _col(row, "canonical_code", "course_code")),
            "share_type": _col(row, "share_type", default="unified").lower(),
            "canonical_course_name": cname,
            "canonical_course_code": _col(row, "canonical_code", "course_code"),
            "units": units,
            "requirement_scope": _col(row, "requirement_scope", default="pre_track"),
            "notes": _col(row, "notes"),
            "departments": dept_by_key.get(key or _slug_key(cname, _col(row, "canonical_code", "course_code")), []),
        }
        save_catalog_entry(conn, payload)
        imported += 1
    return {"imported": imported, "errors": errors}
