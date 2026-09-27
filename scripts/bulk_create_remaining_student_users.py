#!/usr/bin/env python3
"""إنشاء حسابات طلبة متبقية من قائمة Excel (بعد student22178)."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
from werkzeug.security import generate_password_hash

# يُشغَّل داخل حاوية schedule-optimizer
sys.path.insert(0, "/app")

from backend.services.utilities import get_connection  # noqa: E402


EXCEL_PATH = Path("/tmp/students_accounts.xlsx")
AFTER_STUDENT_ID = "22178"


def _cell(v) -> str:
    if v is None:
        return ""
    try:
        if pd.isna(v):
            return ""
    except (TypeError, ValueError):
        pass
    if isinstance(v, float) and v == int(v):
        return str(int(v))
    return str(v).strip()


def main() -> int:
    if not EXCEL_PATH.is_file():
        print("MISSING_EXCEL", EXCEL_PATH)
        return 2

    df = pd.read_excel(EXCEL_PATH)
    rename = {}
    for c in df.columns:
        cl = str(c).strip().lower()
        if cl in ("اسم المستخدم", "username"):
            rename[c] = "username"
        elif cl in ("كلمة المرور", "password"):
            rename[c] = "password"
        elif cl == "student_id":
            rename[c] = "student_id"
        elif cl == "student_name":
            rename[c] = "student_name"
    df = df.rename(columns=rename)
    for col in ("student_id", "student_name", "username", "password"):
        if col not in df.columns:
            print("MISSING_COL", col, list(df.columns))
            return 2

    rows = []
    passed = False
    for _, r in df.iterrows():
        sid = _cell(r.get("student_id"))
        if not sid:
            continue
        if not passed:
            if sid == AFTER_STUDENT_ID:
                passed = True
            continue
        rows.append(
            {
                "student_id": sid,
                "student_name": _cell(r.get("student_name")),
                "username": _cell(r.get("username")).lower(),
                "password": _cell(r.get("password")),
            }
        )

    print(f"REMAINING_ROWS={len(rows)}")
    if not rows:
        print("NOTHING_TO_DO")
        return 0

    created = 0
    updated = 0
    skipped = 0
    errors: list[str] = []

    with get_connection() as conn:
        cur = conn.cursor()
        dept = cur.execute(
            """
            SELECT id FROM departments
            WHERE upper(code) = 'CIVIL'
               OR name_ar LIKE '%مدني%'
               OR name_en ILIKE '%civil%'
            ORDER BY id
            LIMIT 1
            """
        ).fetchone()
        if not dept:
            # fallback: department of an already-created student in the batch prefix
            dept = cur.execute(
                """
                SELECT department_id FROM students
                WHERE student_id = ?
                LIMIT 1
                """,
                (AFTER_STUDENT_ID,),
            ).fetchone()
        dept_id = int(dept[0]) if dept and dept[0] is not None else None
        print(f"DEPARTMENT_ID={dept_id}")

        for row in rows:
            sid = row["student_id"]
            name = row["student_name"]
            username = row["username"]
            password = row["password"]
            if not username or not password:
                errors.append(f"{sid}: missing username/password")
                continue

            # ensure student registry row
            st = cur.execute(
                "SELECT student_id, department_id FROM students WHERE student_id = ? LIMIT 1",
                (sid,),
            ).fetchone()
            if not st:
                cur.execute(
                    "INSERT INTO students (student_id, student_name, department_id) VALUES (?, ?, ?)",
                    (sid, name, dept_id),
                )
            else:
                if name:
                    cur.execute(
                        "UPDATE students SET student_name = ? WHERE student_id = ?",
                        (name, sid),
                    )
                if dept_id is not None and (st[1] is None or str(st[1]).strip() == ""):
                    cur.execute(
                        "UPDATE students SET department_id = ? WHERE student_id = ?",
                        (dept_id, sid),
                    )

            existing = cur.execute(
                """
                SELECT username, role, student_id FROM users
                WHERE lower(username) = lower(?) OR student_id = ?
                LIMIT 1
                """,
                (username, sid),
            ).fetchone()

            pw_hash = generate_password_hash(password)
            if existing:
                ex_user = existing[0]
                # لا نعيد كتابة حساب موجود إلا إذا كان لنفس الطالب وطلبنا إكمالاً — نتخطى الموجودين
                if str(existing[2] or "").strip() == sid and str(ex_user).lower() == username.lower():
                    skipped += 1
                    print(f"SKIP_EXISTS {username} sid={sid}")
                    continue
                # تعارض: username موجود لطالب آخر أو student_id مربوط بغير هذا الـ username
                errors.append(
                    f"{sid}: conflict existing user={ex_user} role={existing[1]} sid={existing[2]}"
                )
                continue

            cur.execute(
                """
                INSERT INTO users (username, password_hash, role, student_id, is_active, department_id)
                VALUES (?, ?, 'student', ?, 1, ?)
                """,
                (username, pw_hash, sid, dept_id),
            )
            created += 1
            print(f"CREATED {username} sid={sid}")

        conn.commit()

    print(
        f"DONE created={created} updated={updated} skipped={skipped} errors={len(errors)}"
    )
    for e in errors:
        print("ERR", e)
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
