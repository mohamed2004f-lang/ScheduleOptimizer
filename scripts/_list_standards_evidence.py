from backend.database.database import get_connection

with get_connection() as conn:
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT id, checklist_key, title_ar, original_name, mime_type,
               semester, department_id, indicator_id, stored_path, uploaded_at
        FROM accreditation_evidence
        WHERE COALESCE(is_active, 1) = 1
        ORDER BY id DESC
        """
    ).fetchall()
    print(f"Total evidence: {len(rows)}")
    for r in rows:
        d = dict(r) if hasattr(r, "keys") else {
            "id": r[0], "checklist_key": r[1], "title_ar": r[2],
            "original_name": r[3], "mime_type": r[4],
        }
        if d.get("checklist_key") in ("standards_pdf", "self_study", "program_descriptor", "audit_docs_list") or (
            d.get("title_ar") and "معايير" in str(d.get("title_ar"))
        ):
            print("---")
            for k, v in (dict(r) if hasattr(r, "keys") else {}).items() if hasattr(r, "keys") else []:
                print(f"  {k}: {v}")
            if not hasattr(r, "keys"):
                print(r)
