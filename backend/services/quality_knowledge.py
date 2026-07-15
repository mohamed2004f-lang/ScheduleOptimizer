"""مكتبة معرفة مساعد الجودة — رفع، اعتماد، فهرسة مقاطع، استرجاع (RAG خفيف)."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import zipfile
from collections import Counter
from typing import Any

from backend.core.quality_knowledge_catalog import (
    ALLOWED_EXTENSIONS,
    APPROVE_ROLES,
    KNOWLEDGE_CATEGORIES,
    KNOWLEDGE_STATUSES,
    LIBRARY_POLICY_AR,
    MAX_FILE_BYTES,
    UPLOAD_ROLES,
    catalog_payload,
)
from backend.database.database import is_postgresql
from backend.services.quality_metrics import term_label_from_conn


def knowledge_upload_dir() -> str:
    root = os.path.join(os.path.dirname(__file__), "..", "uploads", "quality_knowledge")
    path = os.path.abspath(root)
    os.makedirs(path, exist_ok=True)
    return path


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _row_dict(row) -> dict[str, Any]:
    if row is None:
        return {}
    if hasattr(row, "keys"):
        return {k: row[k] for k in row.keys()}
    # unlikely for named queries
    return {}


def can_upload_knowledge(role: str) -> bool:
    r = (role or "").strip().lower()
    if r == "admin":
        r = "admin_main"
    return r in UPLOAD_ROLES


def can_approve_knowledge(role: str, *, is_college_quality_lead: bool = False) -> bool:
    r = (role or "").strip().lower()
    if r == "admin":
        r = "admin_main"
    if is_college_quality_lead:
        return True
    return r in APPROVE_ROLES


def ensure_quality_knowledge_tables(conn) -> None:
    cur = conn.cursor()
    if is_postgresql():
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS quality_knowledge_docs (
                id BIGSERIAL PRIMARY KEY,
                department_id BIGINT,
                category TEXT NOT NULL DEFAULT 'other',
                title_ar TEXT NOT NULL DEFAULT '',
                source_label_ar TEXT NOT NULL DEFAULT '',
                source_url TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'draft',
                original_name TEXT NOT NULL DEFAULT '',
                stored_path TEXT NOT NULL DEFAULT '',
                mime_type TEXT NOT NULL DEFAULT '',
                file_size INTEGER NOT NULL DEFAULT 0,
                sha256 TEXT NOT NULL DEFAULT '',
                extracted_text TEXT NOT NULL DEFAULT '',
                notes_ar TEXT NOT NULL DEFAULT '',
                approved_by TEXT NOT NULL DEFAULT '',
                approved_at TEXT NOT NULL DEFAULT '',
                created_by TEXT NOT NULL DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_by TEXT NOT NULL DEFAULT '',
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                is_active INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS quality_knowledge_chunks (
                id BIGSERIAL PRIMARY KEY,
                doc_id BIGINT NOT NULL,
                chunk_index INTEGER NOT NULL DEFAULT 0,
                content TEXT NOT NULL DEFAULT '',
                token_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    else:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS quality_knowledge_docs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                department_id INTEGER,
                category TEXT NOT NULL DEFAULT 'other',
                title_ar TEXT NOT NULL DEFAULT '',
                source_label_ar TEXT NOT NULL DEFAULT '',
                source_url TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'draft',
                original_name TEXT NOT NULL DEFAULT '',
                stored_path TEXT NOT NULL DEFAULT '',
                mime_type TEXT NOT NULL DEFAULT '',
                file_size INTEGER NOT NULL DEFAULT 0,
                sha256 TEXT NOT NULL DEFAULT '',
                extracted_text TEXT NOT NULL DEFAULT '',
                notes_ar TEXT NOT NULL DEFAULT '',
                approved_by TEXT NOT NULL DEFAULT '',
                approved_at TEXT NOT NULL DEFAULT '',
                created_by TEXT NOT NULL DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_by TEXT NOT NULL DEFAULT '',
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                is_active INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS quality_knowledge_chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id INTEGER NOT NULL,
                chunk_index INTEGER NOT NULL DEFAULT 0,
                content TEXT NOT NULL DEFAULT '',
                token_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    conn.commit()


def extract_text_from_bytes(raw: bytes, original_name: str = "") -> str:
    ext = os.path.splitext(original_name or "")[1].lower()
    if ext in (".txt", ".md", ".markdown", ".json"):
        for enc in ("utf-8", "utf-8-sig", "cp1256", "latin-1"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                text = ""
        else:
            text = raw.decode("utf-8", errors="ignore")
        if ext == ".json":
            try:
                obj = json.loads(text)
                return json.dumps(obj, ensure_ascii=False, indent=2)
            except Exception:
                return text
        return text

    if ext == ".pdf":
        try:
            from pypdf import PdfReader  # type: ignore

            reader = PdfReader(io.BytesIO(raw))
            parts = []
            for page in reader.pages[:80]:
                parts.append(page.extract_text() or "")
            return "\n".join(parts).strip()
        except Exception:
            return ""

    if ext == ".docx":
        try:
            # استخراج نص بسيط من document.xml داخل docx
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                xml = zf.read("word/document.xml").decode("utf-8", errors="ignore")
            texts = re.findall(r"<w:t[^>]*>(.*?)</w:t>", xml)
            return re.sub(r"\s+", " ", " ".join(texts)).strip()
        except Exception:
            return ""

    return ""


def chunk_text(text: str, *, size: int = 700, overlap: int = 120) -> list[str]:
    clean = re.sub(r"\s+", " ", (text or "").strip())
    if not clean:
        return []
    if len(clean) <= size:
        return [clean]
    chunks = []
    i = 0
    n = len(clean)
    while i < n:
        chunk = clean[i : i + size].strip()
        if chunk:
            chunks.append(chunk)
        if i + size >= n:
            break
        i += max(1, size - overlap)
    return chunks[:200]


def _tokenize_ar(text: str) -> list[str]:
    raw = re.findall(r"[\w\u0600-\u06FF]{2,}", (text or "").lower())
    stop = {
        "من",
        "في",
        "على",
        "إلى",
        "الى",
        "هذا",
        "هذه",
        "ذلك",
        "التي",
        "الذي",
        "و",
        "أو",
        "ثم",
        "مع",
        "عن",
        "the",
        "and",
        "for",
        "with",
    }
    return [t for t in raw if t not in stop]


def rebuild_chunks_for_doc(conn, doc_id: int, text: str) -> int:
    cur = conn.cursor()
    cur.execute("DELETE FROM quality_knowledge_chunks WHERE doc_id = ?", (int(doc_id),))
    chunks = chunk_text(text)
    now = _now()
    for idx, content in enumerate(chunks):
        cur.execute(
            """
            INSERT INTO quality_knowledge_chunks (doc_id, chunk_index, content, token_count, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (int(doc_id), idx, content[:4000], len(_tokenize_ar(content)), now),
        )
    conn.commit()
    return len(chunks)


def public_doc(row: dict[str, Any]) -> dict[str, Any]:
    cat = row.get("category") or "other"
    st = row.get("status") or "draft"
    return {
        "id": int(row["id"]),
        "department_id": row.get("department_id"),
        "category": cat,
        "category_label_ar": (KNOWLEDGE_CATEGORIES.get(cat) or {}).get("title_ar") or cat,
        "title_ar": row.get("title_ar") or "",
        "source_label_ar": row.get("source_label_ar") or "",
        "source_url": row.get("source_url") or "",
        "status": st,
        "status_label_ar": KNOWLEDGE_STATUSES.get(st, st),
        "original_name": row.get("original_name") or "",
        "file_size": int(row.get("file_size") or 0),
        "notes_ar": row.get("notes_ar") or "",
        "approved_by": row.get("approved_by") or "",
        "approved_at": row.get("approved_at") or "",
        "created_by": row.get("created_by") or "",
        "created_at": row.get("created_at") or "",
        "updated_at": row.get("updated_at") or "",
        "has_text": bool((row.get("extracted_text") or "").strip()),
        "text_preview": ((row.get("extracted_text") or "")[:280]),
    }


def list_knowledge_docs(
    conn,
    *,
    department_id: int | None = None,
    status: str | None = None,
    category: str | None = None,
    include_college_wide: bool = True,
    limit: int = 200,
) -> list[dict[str, Any]]:
    ensure_quality_knowledge_tables(conn)
    cur = conn.cursor()
    sql = """
        SELECT * FROM quality_knowledge_docs
        WHERE COALESCE(is_active, 1) = 1
    """
    params: list[Any] = []
    if department_id is not None:
        if include_college_wide:
            sql += " AND (department_id = ? OR department_id IS NULL)"
            params.append(int(department_id))
        else:
            sql += " AND department_id = ?"
            params.append(int(department_id))
    if status:
        sql += " AND status = ?"
        params.append(status.strip())
    if category:
        sql += " AND category = ?"
        params.append(category.strip())
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(int(limit))
    rows = cur.execute(sql, params).fetchall() or []
    return [public_doc(_row_dict(r)) for r in rows]


def get_knowledge_doc(conn, doc_id: int) -> dict[str, Any] | None:
    ensure_quality_knowledge_tables(conn)
    cur = conn.cursor()
    row = cur.execute(
        "SELECT * FROM quality_knowledge_docs WHERE id = ? AND COALESCE(is_active, 1) = 1",
        (int(doc_id),),
    ).fetchone()
    if not row:
        return None
    d = public_doc(_row_dict(row))
    d["extracted_text"] = (_row_dict(row).get("extracted_text") or "")[:50000]
    return d


def create_knowledge_doc(
    conn,
    *,
    title_ar: str,
    actor: str,
    category: str = "other",
    department_id: int | None = None,
    source_label_ar: str = "",
    source_url: str = "",
    notes_ar: str = "",
    body_text: str = "",
    raw: bytes | None = None,
    original_name: str = "",
    mime_type: str = "",
    status: str = "draft",
) -> dict[str, Any]:
    ensure_quality_knowledge_tables(conn)
    title = (title_ar or "").strip()
    if not title:
        raise ValueError("عنوان الوثيقة مطلوب")
    cat = (category or "other").strip()
    if cat not in KNOWLEDGE_CATEGORIES:
        cat = "other"
    st = (status or "draft").strip()
    if st not in KNOWLEDGE_STATUSES:
        st = "draft"

    stored_path = ""
    sha = ""
    fsize = 0
    oname = (original_name or "").strip()
    mime = (mime_type or "").strip()
    extracted = (body_text or "").strip()

    if raw:
        if len(raw) > MAX_FILE_BYTES:
            raise ValueError("حجم الملف يتجاوز الحد المسموح")
        ext = os.path.splitext(oname or "doc.bin")[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise ValueError("صيغة غير مسموحة — استخدم: " + ", ".join(sorted(ALLOWED_EXTENSIONS)))
        sha = hashlib.sha256(raw).hexdigest()
        stored_name = f"qk__{sha[:18]}{ext}"
        stored_path = os.path.join(knowledge_upload_dir(), stored_name)
        with open(stored_path, "wb") as out:
            out.write(raw)
        fsize = len(raw)
        if not extracted:
            extracted = extract_text_from_bytes(raw, oname)

    now = _now()
    approved_by = (actor or "")[:120] if st == "approved" else ""
    approved_at = now if st == "approved" else ""
    cur = conn.cursor()
    vals = (
        int(department_id) if department_id is not None else None,
        cat,
        title[:300],
        (source_label_ar or "")[:300],
        (source_url or "")[:500],
        st[:32],
        oname[:260],
        stored_path,
        mime[:120],
        fsize,
        sha,
        extracted[:200000],
        (notes_ar or "")[:4000],
        approved_by,
        approved_at,
        (actor or "")[:120],
        now,
        (actor or "")[:120],
        now,
    )
    if is_postgresql():
        row = cur.execute(
            """
            INSERT INTO quality_knowledge_docs (
                department_id, category, title_ar, source_label_ar, source_url, status,
                original_name, stored_path, mime_type, file_size, sha256, extracted_text,
                notes_ar, approved_by, approved_at, created_by, created_at, updated_by, updated_at, is_active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            RETURNING id
            """,
            vals,
        ).fetchone()
        doc_id = int(row[0] if not hasattr(row, "keys") else row["id"])
    else:
        cur.execute(
            """
            INSERT INTO quality_knowledge_docs (
                department_id, category, title_ar, source_label_ar, source_url, status,
                original_name, stored_path, mime_type, file_size, sha256, extracted_text,
                notes_ar, approved_by, approved_at, created_by, created_at, updated_by, updated_at, is_active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            vals,
        )
        doc_id = int(cur.lastrowid)
    conn.commit()
    chunk_count = rebuild_chunks_for_doc(conn, doc_id, extracted)
    doc = get_knowledge_doc(conn, doc_id) or {"id": doc_id}
    doc["chunk_count"] = chunk_count
    doc["policy_ar"] = LIBRARY_POLICY_AR
    doc["suggestion_only"] = True
    return doc


def set_knowledge_status(
    conn,
    doc_id: int,
    *,
    status: str,
    actor: str,
) -> dict[str, Any]:
    ensure_quality_knowledge_tables(conn)
    st = (status or "").strip()
    if st not in KNOWLEDGE_STATUSES:
        raise ValueError("حالة غير صالحة")
    now = _now()
    approved_by = ""
    approved_at = ""
    if st == "approved":
        approved_by = (actor or "")[:120]
        approved_at = now
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE quality_knowledge_docs
        SET status = ?, updated_by = ?, updated_at = ?,
            approved_by = CASE WHEN ? = 'approved' THEN ? ELSE approved_by END,
            approved_at = CASE WHEN ? = 'approved' THEN ? ELSE approved_at END
        WHERE id = ? AND COALESCE(is_active, 1) = 1
        """,
        (st, (actor or "")[:120], now, st, approved_by, st, approved_at, int(doc_id)),
    )
    conn.commit()
    doc = get_knowledge_doc(conn, doc_id)
    if not doc:
        raise ValueError("الوثيقة غير موجودة")
    # أعد الفهرسة عند الاعتماد إن وُجد نص
    row = conn.cursor().execute(
        "SELECT extracted_text FROM quality_knowledge_docs WHERE id = ?",
        (int(doc_id),),
    ).fetchone()
    text = ""
    if row:
        text = row["extracted_text"] if hasattr(row, "keys") else (row[0] or "")
    if st == "approved" and text:
        rebuild_chunks_for_doc(conn, doc_id, text)
    return doc


def soft_delete_knowledge_doc(conn, doc_id: int, *, actor: str) -> None:
    ensure_quality_knowledge_tables(conn)
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE quality_knowledge_docs
        SET is_active = 0, updated_by = ?, updated_at = ?
        WHERE id = ?
        """,
        ((actor or "")[:120], _now(), int(doc_id)),
    )
    conn.commit()


def _hashed_embed(text: str, *, dim: int = 256):
    """تضمين خفيف بدون نموذج خارجي: hashing للكلمات وثلاثيات الأحرف (numpy)."""
    import numpy as np

    vec = np.zeros(dim, dtype=float)
    tokens = _tokenize_ar(text)
    blob = (text or "").lower()
    for t in tokens:
        vec[hash(t) % dim] += 1.0
        if len(t) >= 3:
            for i in range(len(t) - 2):
                vec[hash(t[i : i + 3]) % dim] += 0.35
    # أحرف عربية متتالية للأسئلة القصيرة
    compact = re.sub(r"\s+", "", blob)
    for i in range(max(0, len(compact) - 2)):
        tri = compact[i : i + 3]
        if re.search(r"[\u0600-\u06FFa-z0-9]", tri):
            vec[hash(tri) % dim] += 0.15
    norm = float(np.linalg.norm(vec))
    if norm > 1e-9:
        vec /= norm
    return vec


def retrieve_knowledge(
    conn,
    *,
    query: str,
    department_id: int | None = None,
    category: str | None = None,
    top_k: int = 6,
    approved_only: bool = True,
    prefer_department: bool = True,
) -> dict[str, Any]:
    """استرجاع RAG: تقاطع كلمات + تشابه تضمين hashing + تفضيل وثائق القسم."""
    ensure_quality_knowledge_tables(conn)
    q_tokens = _tokenize_ar(query)
    if not q_tokens and not (query or "").strip():
        return {
            "status": "ok",
            "hits": [],
            "message_ar": "اكتب كلمات أوضح للبحث في مكتبة المعرفة.",
            "suggestion_only": True,
        }

    cur = conn.cursor()
    sql = """
        SELECT c.id AS chunk_id, c.doc_id, c.chunk_index, c.content,
               d.title_ar, d.category, d.source_label_ar, d.department_id, d.status
        FROM quality_knowledge_chunks c
        JOIN quality_knowledge_docs d ON d.id = c.doc_id
        WHERE COALESCE(d.is_active, 1) = 1
    """
    params: list[Any] = []
    if approved_only:
        sql += " AND d.status = 'approved'"
    if department_id is not None:
        # القسم أولاً + الكلية؛ يُفضَّل القسم في الدرجة لاحقاً
        sql += " AND (d.department_id = ? OR d.department_id IS NULL)"
        params.append(int(department_id))
    if category:
        sql += " AND d.category = ?"
        params.append(category.strip())
    sql += " ORDER BY CASE WHEN d.department_id IS NULL THEN 1 ELSE 0 END, c.id DESC LIMIT 1500"
    rows = cur.execute(sql, params).fetchall() or []

    scored: list[tuple[float, dict[str, Any]]] = []
    qset = set(q_tokens)
    q_counts = Counter(q_tokens)
    q_vec = _hashed_embed(query or " ".join(q_tokens))
    for r in rows:
        rd = _row_dict(r)
        content = rd.get("content") or ""
        title = rd.get("title_ar") or ""
        ctoks = _tokenize_ar(f"{title} {content}")
        if not ctoks:
            continue
        cset = set(ctoks)
        overlap = qset & cset
        c_vec = _hashed_embed(f"{title}\n{content}")
        try:
            import numpy as np

            cos = float(np.dot(q_vec, c_vec))
        except Exception:
            cos = 0.0
        # قبول المرشح إن وُجد تقاطع أو تشابه معنوي معقول
        if not overlap and cos < 0.12:
            continue
        score = float(len(overlap)) * 2.0
        cc = Counter(ctoks)
        for t in overlap:
            score += min(q_counts[t], cc[t]) * 0.3
        score += cos * 8.0
        dept_id_row = rd.get("department_id")
        if prefer_department and department_id is not None:
            if dept_id_row is not None and int(dept_id_row) == int(department_id):
                score += 1.8
            elif dept_id_row is None:
                score += 0.25
        elif dept_id_row is not None and department_id is not None:
            score += 0.5
        scored.append(
            (
                score,
                {
                    "chunk_id": int(rd["chunk_id"]),
                    "doc_id": int(rd["doc_id"]),
                    "title_ar": title,
                    "category": rd.get("category") or "",
                    "category_label_ar": (KNOWLEDGE_CATEGORIES.get(rd.get("category") or "") or {}).get(
                        "title_ar"
                    )
                    or rd.get("category"),
                    "source_label_ar": rd.get("source_label_ar") or "",
                    "department_id": dept_id_row,
                    "scope_ar": (
                        "قسم"
                        if (
                            prefer_department
                            and department_id is not None
                            and dept_id_row is not None
                            and int(dept_id_row) == int(department_id)
                        )
                        else ("كلية" if dept_id_row is None else "قسم آخر")
                    ),
                    "excerpt": content[:900],
                    "score": round(score, 3),
                    "cosine": round(cos, 3),
                },
            )
        )

    scored.sort(
        key=lambda x: (
            -x[0],
            0 if (department_id is not None and x[1].get("department_id") == department_id) else 1,
            x[1].get("doc_id") or 0,
        )
    )
    hits = [h for _, h in scored[: max(1, min(top_k, 12))]]
    return {
        "status": "ok",
        "query": query,
        "hits": hits,
        "hits_count": len(hits),
        "retrieval": "keyword+hashed_embed",
        "message_ar": (
            f"عُثر على {len(hits)} مقطع(ات) من الوثائق المعتمدة."
            if hits
            else "لا نتائج في المكتبة المعتمدة — ارفع وثائق أو اعتمد المسودات."
        ),
        "suggestion_only": True,
        "policy_ar": LIBRARY_POLICY_AR,
    }


def export_approved_knowledge_zip(
    conn,
    *,
    department_id: int | None = None,
) -> bytes:
    ensure_quality_knowledge_tables(conn)
    docs = list_knowledge_docs(
        conn,
        department_id=department_id,
        status="approved",
        include_college_wide=True,
        limit=500,
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "README_AR.md",
            "\n".join(
                [
                    "# تصدير مكتبة المعرفة المعتمدة — مساعد الجودة",
                    "",
                    LIBRARY_POLICY_AR,
                    "",
                    f"عدد الوثائق: {len(docs)}",
                    f"الفصل المرجعي عند التصدير: {term_label_from_conn(conn)}",
                ]
            ),
        )
        meta = []
        for d in docs:
            full = get_knowledge_doc(conn, int(d["id"])) or d
            text = full.get("extracted_text") or ""
            safe = re.sub(r"[^\w\-]+", "_", f"{d['id']}_{d.get('title_ar') or 'doc'}")[:80]
            zf.writestr(
                f"docs/{safe}.md",
                "\n".join(
                    [
                        f"# {d.get('title_ar')}",
                        "",
                        f"- المصدر: {d.get('source_label_ar') or '—'}",
                        f"- الرابط: {d.get('source_url') or '—'}",
                        f"- التصنيف: {d.get('category_label_ar')}",
                        f"- الاعتماد: {d.get('approved_by')} @ {d.get('approved_at')}",
                        "",
                        text[:100000] or "_(لا نص مستخرج)_",
                        "",
                    ]
                ),
            )
            # انسخ الملف الأصلي إن وُجد
            row = conn.cursor().execute(
                "SELECT stored_path, original_name FROM quality_knowledge_docs WHERE id = ?",
                (int(d["id"]),),
            ).fetchone()
            if row:
                sp = row["stored_path"] if hasattr(row, "keys") else row[0]
                on = row["original_name"] if hasattr(row, "keys") else row[1]
                if sp and os.path.isfile(sp):
                    ext = os.path.splitext(on or sp)[1] or ".bin"
                    zf.write(sp, arcname=f"files/{safe}{ext}")
            meta.append(d)
        zf.writestr("manifest.json", json.dumps({"docs": meta, "policy_ar": LIBRARY_POLICY_AR}, ensure_ascii=False, indent=2))
    return buf.getvalue()


def _existing_titles(conn) -> set[str]:
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT title_ar FROM quality_knowledge_docs
        WHERE COALESCE(is_active, 1) = 1
        """
    ).fetchall() or []
    out: set[str] = set()
    for r in rows:
        if hasattr(r, "keys"):
            out.add(str(r["title_ar"] or "").strip())
        else:
            out.add(str(r[0] or "").strip())
    return out


def seed_approved_global_refs_into_knowledge(
    conn, *, actor: str = "system", force: bool = False
) -> dict[str, Any]:
    """بذر/استكمال بطاقات المراجع العالمية المعتمدة (idempotent حسب العنوان)."""
    ensure_quality_knowledge_tables(conn)
    from backend.core.quality_assistant_catalog import (
        APPROVED_GLOBAL_REFERENCES,
        approved_global_ref_to_markdown,
        knowledge_doc_title_for_global_ref,
    )

    existing = set() if force else _existing_titles(conn)
    seeded = 0
    skipped = 0
    for ref in APPROVED_GLOBAL_REFERENCES:
        title = knowledge_doc_title_for_global_ref(ref)
        if title in existing:
            skipped += 1
            continue
        create_knowledge_doc(
            conn,
            title_ar=title,
            actor=actor,
            category="global_summary",
            department_id=None,
            source_label_ar=ref.get("label_en") or ref.get("label_ar") or "مرجع عالمي",
            source_url=(ref.get("official_url") or "")[:500],
            notes_ar=f"seed_key=global_ref:{ref.get('code')}",
            body_text=approved_global_ref_to_markdown(ref),
            status="approved",
        )
        existing.add(title)
        seeded += 1
    return {
        "status": "ok",
        "seeded": seeded,
        "skipped": skipped,
        "message_ar": (
            f"تم بذر/استكمال {seeded} بطاقة مرجع عالمي معتمد"
            + (f" (تُخطي {skipped} موجودة)." if skipped else ".")
        ),
        "suggestion_only": True,
    }


def seed_specialty_packs_into_knowledge(conn, *, actor: str = "system") -> dict[str, Any]:
    """بذر حزم المراجع التخصصية كوثائق معتمدة (مرة عند الفراغ) + استكمال البطاقات العالمية."""
    ensure_quality_knowledge_tables(conn)
    cur = conn.cursor()
    n = cur.execute(
        "SELECT COUNT(*) FROM quality_knowledge_docs WHERE COALESCE(is_active,1)=1"
    ).fetchone()
    count = int(n[0] if not hasattr(n, "keys") else list(n)[0])

    packs_seeded = 0
    if count == 0:
        from backend.core.quality_assistant_catalog import (
            exportable_specialty_packs,
            specialty_pack_to_markdown,
        )

        payload = exportable_specialty_packs(primary_only=True)
        code_to_id: dict[str, int] = {}
        for r in cur.execute(
            "SELECT id, code FROM departments WHERE COALESCE(is_active,1)=1"
        ).fetchall() or []:
            if hasattr(r, "keys"):
                code_to_id[str(r["code"]).upper()] = int(r["id"])
            else:
                code_to_id[str(r[1]).upper()] = int(r[0])

        for pack in payload.get("packs") or []:
            md = specialty_pack_to_markdown(pack)
            codes = pack.get("department_codes") or []
            dept_id = None
            for c in codes:
                if str(c).upper() in code_to_id:
                    dept_id = code_to_id[str(c).upper()]
                    break
            create_knowledge_doc(
                conn,
                title_ar=f"حزمة مراجع — {pack.get('title_ar')}",
                actor=actor,
                category="global_summary",
                department_id=dept_id,
                source_label_ar="كتالوج مساعد الجودة (مراجع للنقاش)",
                source_url="",
                notes_ar="بذر تلقائي من بطاقات المراجع — للاقتراح فقط.",
                body_text=md,
                status="approved",
            )
            packs_seeded += 1

    refs = seed_approved_global_refs_into_knowledge(conn, actor=actor)
    total = packs_seeded + int(refs.get("seeded") or 0)
    if total == 0 and packs_seeded == 0:
        return {
            "status": "ok",
            "seeded": 0,
            "packs_seeded": 0,
            "refs_seeded": int(refs.get("seeded") or 0),
            "message_ar": refs.get("message_ar")
            or "المكتبة محدّثة — لا بذر جديد.",
            "suggestion_only": True,
        }
    return {
        "status": "ok",
        "seeded": total,
        "packs_seeded": packs_seeded,
        "refs_seeded": int(refs.get("seeded") or 0),
        "message_ar": (
            f"تم بذر {packs_seeded} حزمة تخصص + {refs.get('seeded') or 0} بطاقة مرجع عالمي."
        ),
        "suggestion_only": True,
    }


def library_bootstrap(
    conn,
    *,
    role: str,
    is_college_quality_lead: bool = False,
    department_id: int | None = None,
    seed_if_empty: bool = True,
) -> dict[str, Any]:
    ensure_quality_knowledge_tables(conn)
    seed_info = None
    if seed_if_empty:
        # يستكمل البطاقات العالمية حتى لو المكتبة غير فارغة
        seed_info = seed_specialty_packs_into_knowledge(conn, actor="system")
    docs = list_knowledge_docs(conn, department_id=department_id, include_college_wide=True)
    return {
        "status": "ok",
        "catalog": catalog_payload(),
        "docs": docs,
        "seed": seed_info,
        "can_upload": can_upload_knowledge(role),
        "can_approve": can_approve_knowledge(role, is_college_quality_lead=is_college_quality_lead),
        "policy_ar": LIBRARY_POLICY_AR,
        "suggestion_only": True,
    }
