from flask import Blueprint, request, jsonify, send_file
from .utilities import get_connection, table_to_dicts, DB_FILE, df_from_query, excel_response_from_df, pdf_response_from_html
import sqlite3
from datetime import datetime
from collections import defaultdict

exams_bp = Blueprint("exams", __name__)

VALID_TYPES = {"midterm", "final"}

def normalize_dates(dates):
    # expect list of date strings, normalize to ISO YYYY-MM-DD
    out = []
    for d in dates:
        if not d:
            continue
        try:
            dt = datetime.fromisoformat(d) if 'T' in d else datetime.strptime(d, "%Y-%m-%d")
            out.append(dt.date().isoformat())
        except Exception:
            # try common formats
            try:
                dt = datetime.strptime(d, "%d/%m/%Y")
                out.append(dt.date().isoformat())
            except Exception:
                continue
    return sorted(list(dict.fromkeys(out)))

@exams_bp.route('/<exam_type>/rows')
def list_exam_rows(exam_type):
    if exam_type not in VALID_TYPES:
        return jsonify([])
    with get_connection() as conn:
        cur = conn.cursor()
        rows = cur.execute("SELECT rowid AS exam_id, course_name, exam_date, exam_time, room, instructor FROM exams WHERE exam_type=? ORDER BY exam_date, exam_time", (exam_type,)).fetchall()
        return jsonify([dict(r) for r in rows])

@exams_bp.route('/<exam_type>/check_conflicts', methods=['POST'])
def check_exam_conflicts(exam_type):
    """
    التحقق من التعارضات قبل إضافة امتحان جديد
    Returns: قائمة بالتعارضات المحتملة
    """
    if exam_type not in VALID_TYPES:
        return jsonify({"status":"error","message":"invalid exam type"}), 400
    
    try:
        data = request.get_json(force=True) or {}
        course_name = data.get('course_name','').strip()
        exam_date = data.get('exam_date','').strip()
        
        if not course_name or not exam_date:
            return jsonify({
                "status": "error",
                "message": "course_name and exam_date required"
            }), 400
        
        # normalize date
        nd = normalize_dates([exam_date])
        if not nd:
            return jsonify({"status":"error","message":"invalid date format"}), 400
        exam_date = nd[0]
        
        # محاكاة إضافة الامتحان مؤقتاً للتحقق من التعارضات
        with get_connection() as conn:
            cur = conn.cursor()
            
            # إضافة مؤقتة للامتحان
            cur.execute("INSERT INTO exams (exam_type, exam_id, course_name, exam_date, exam_time, room, instructor) VALUES (?,?,?,?,?,?,?)",
                        (exam_type, None, course_name, exam_date, data.get('exam_time',''), data.get('room',''), data.get('instructor','')))
            temp_rowid = cur.lastrowid
            
            # حساب التعارضات
            q = '''
            SELECT r.student_id as student_id, e.exam_date as exam_date, GROUP_CONCAT(e.course_name) as courses, COUNT(e.course_name) as ccount
            FROM exams e
            JOIN registrations r ON r.course_name = e.course_name
            WHERE e.exam_type = ?
            GROUP BY r.student_id, e.exam_date
            HAVING ccount > 1
            '''
            rows = cur.execute(q, (exam_type,)).fetchall()
            
            # تصفية التعارضات المتعلقة بالامتحان الجديد
            relevant_conflicts = []
            for r in rows:
                if r[1] == exam_date and course_name in (r[2] or ''):
                    relevant_conflicts.append({
                        'student_id': r[0] or '',
                        'exam_date': r[1] or '',
                        'conflicting_courses': r[2] or ''
                    })
            
            # حذف الإضافة المؤقتة
            cur.execute("DELETE FROM exams WHERE rowid = ?", (temp_rowid,))
            conn.commit()
            
            return jsonify({
                "status": "ok",
                "has_conflicts": len(relevant_conflicts) > 0,
                "conflicts": relevant_conflicts,
                "conflict_count": len(relevant_conflicts)
            }), 200
            
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error checking exam conflicts: {e}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": f"خطأ في التحقق من التعارضات: {str(e)}"
        }), 500

@exams_bp.route('/<exam_type>/add_row', methods=['POST'])
def add_exam_row(exam_type):
    if exam_type not in VALID_TYPES:
        return jsonify({"status":"error","message":"invalid exam type"}), 400
    data = request.get_json(force=True) or {}
    course_name = data.get('course_name','')
    exam_date = data.get('exam_date','')
    exam_time = data.get('exam_time','09:00-12:00')  # الوقت الافتراضي
    room = data.get('room','')
    instructor = data.get('instructor','')
    if not course_name or not exam_date:
        return jsonify({"status":"error","message":"course_name and exam_date required"}), 400
    # normalize date
    nd = normalize_dates([exam_date])
    if not nd:
        return jsonify({"status":"error","message":"invalid date format"}), 400
    exam_date = nd[0]
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO exams (exam_type, exam_id, course_name, exam_date, exam_time, room, instructor) VALUES (?,?,?,?,?,?,?)",
                    (exam_type, None, course_name, exam_date, exam_time, room, instructor))
        conn.commit()
    return jsonify({"status":"ok"})

@exams_bp.route('/<exam_type>/delete_row', methods=['POST'])
def delete_exam_row(exam_type):
    if exam_type not in VALID_TYPES:
        return jsonify({"status":"error"}), 400
    data = request.get_json(force=True) or {}
    exam_id = data.get('exam_id')
    if not exam_id:
        return jsonify({"status":"error","message":"exam_id required"}), 400
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute('DELETE FROM exams WHERE rowid = ? AND exam_type = ?', (exam_id, exam_type))
        conn.commit()
    return jsonify({"status":"ok"})

@exams_bp.route('/<exam_type>/distribute', methods=['POST'])
def distribute_exams(exam_type):
    """
    Body: { dates: ["YYYY-MM-DD", ...], method: "round_robin" }
    Distribute all courses found in schedule (or courses table) over given dates.
    Enforce max span <= 31 days.
    """
    if exam_type not in VALID_TYPES:
        return jsonify({"status":"error","message":"invalid exam type"}), 400
    data = request.get_json(force=True) or {}
    dates = data.get('dates') or []
    method = data.get('method','round_robin')
    dates = normalize_dates(dates)
    if not dates:
        return jsonify({"status":"error","message":"no valid dates provided"}), 400
    # enforce max span <= 31 days
    try:
        d0 = datetime.fromisoformat(dates[0]).date()
        d1 = datetime.fromisoformat(dates[-1]).date()
        span = (d1 - d0).days
        if span > 31:
            return jsonify({"status":"error","message":"date span exceeds 31 days"}), 400
    except Exception:
        pass

    with get_connection() as conn:
        cur = conn.cursor()
        # get list of distinct course names (prefer schedule table)
        try:
            course_rows = cur.execute("SELECT DISTINCT course_name FROM schedule WHERE course_name IS NOT NULL AND course_name != '' ORDER BY course_name").fetchall()
            courses = [r[0] for r in course_rows]
            if not courses:
                # fallback to courses table
                course_rows = cur.execute("SELECT DISTINCT course_name FROM courses ORDER BY course_name").fetchall()
                courses = [r[0] for r in course_rows]
        except Exception:
            courses = []

        if not courses:
            return jsonify({"status":"error","message":"no courses found to schedule"}), 400

        # clear existing exams of this type
        cur.execute('DELETE FROM exams WHERE exam_type = ?', (exam_type,))

        # assign courses to dates
        if method == 'round_robin':
            di = 0
            for c in courses:
                ed = dates[di % len(dates)]
                cur.execute('INSERT INTO exams (exam_type, exam_id, course_name, exam_date, exam_time, room, instructor) VALUES (?,?,?,?,?,?,?)',
                            (exam_type, None, c, ed, '', '', ''))
                di += 1
        else:
            # default same as round_robin
            di = 0
            for c in courses:
                ed = dates[di % len(dates)]
                cur.execute('INSERT INTO exams (exam_type, exam_id, course_name, exam_date, exam_time, room, instructor) VALUES (?,?,?,?,?,?,?)',
                            (exam_type, None, c, ed, '', '', ''))
                di += 1
        conn.commit()
    return jsonify({"status":"ok","scheduled": len(courses)})


@exams_bp.route('/available_courses')
def available_courses():
    """Return distinct course names from schedule (for populating selects)."""
    with get_connection() as conn:
        cur = conn.cursor()
        try:
            rows = cur.execute("SELECT DISTINCT course_name FROM schedule WHERE course_name IS NOT NULL AND course_name != '' ORDER BY course_name").fetchall()
            courses = [r[0] for r in rows]
        except Exception:
            rows = cur.execute("SELECT DISTINCT course_name FROM courses ORDER BY course_name").fetchall()
            courses = [r[0] for r in rows]
    return jsonify({"courses": courses})


@exams_bp.route('/<exam_type>/export')
def export_exams(exam_type):
    """Export exam rows in format=txt|xlsx|pdf (query param format)."""
    fmt = (request.args.get('format') or 'txt').lower()
    if exam_type not in VALID_TYPES:
        return jsonify({"status": "error", "message": "invalid exam type"}), 400
    # load exams
    exams = table_to_dicts('exams')
    exams = [e for e in exams if e.get('exam_type') == exam_type]
    import io
    import pandas as pd
    if fmt == 'txt':
        # tab-separated text
        df = pd.DataFrame(exams)
        buf = io.BytesIO()
        buf.write(df.to_csv(index=False, sep='\t', encoding='utf-8').encode('utf-8'))
        buf.seek(0)
        fname = f"exams_{exam_type}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.txt"
        return send_file(buf, mimetype='text/plain', as_attachment=True, download_name=fname)
    elif fmt in ('xlsx','xls'):
        df = pd.DataFrame(exams)
        return excel_response_from_df(df, filename_prefix=f"exams_{exam_type}")
    elif fmt == 'pdf':
        # build simple html
        rows_html = ''.join([f"<tr><td>{e.get('course_name','')}</td><td>{e.get('exam_date','')}</td><td>{e.get('exam_time','')}</td><td>{e.get('room','')}</td></tr>" for e in exams])
        html = f"""
        <html><head><meta charset='utf-8'><style>table{{width:100%;border-collapse:collapse}}th,td{{border:1px solid #ccc;padding:6px}}</style></head>
        <body><h2>Exams - {exam_type}</h2><table><thead><tr><th>Course</th><th>Date</th><th>Time</th><th>Room</th></tr></thead><tbody>{rows_html}</tbody></table></body></html>
        """
        return pdf_response_from_html(html, filename_prefix=f"exams_{exam_type}")
    else:
        return jsonify({"status":"error","message":"unsupported format"}), 400


@exams_bp.route('/<exam_type>/conflicts/export')
def export_conflicts(exam_type):
    fmt = (request.args.get('format') or 'txt').lower()
    if exam_type not in VALID_TYPES:
        return jsonify({"status": "error", "message": "invalid exam type"}), 400
    # reuse the conflict SQL used above
    q = '''
    SELECT r.student_id as student_id, e.exam_date as exam_date, GROUP_CONCAT(e.course_name) as conflicting_courses, COUNT(e.course_name) as ccount
    FROM exams e
    JOIN registrations r ON r.course_name = e.course_name
    WHERE e.exam_type = ?
    GROUP BY r.student_id, e.exam_date
    HAVING ccount > 1
    '''
    import io
    import pandas as pd
    rows = df_from_query(q, params=(exam_type,))
    if fmt == 'txt':
        buf = io.BytesIO()
        buf.write(rows.to_csv(index=False, sep='\t', encoding='utf-8').encode('utf-8'))
        buf.seek(0)
        fname = f"exam_conflicts_{exam_type}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.txt"
        return send_file(buf, mimetype='text/plain', as_attachment=True, download_name=fname)
    elif fmt in ('xlsx','xls'):
        return excel_response_from_df(rows, filename_prefix=f"exam_conflicts_{exam_type}")
    elif fmt == 'pdf':
        # build html table
        rows_html = ''.join([f"<tr><td>{r.student_id}</td><td>{r.exam_date}</td><td>{r.conflicting_courses}</td></tr>" for r in rows.itertuples()])
        html = f"""
        <html><head><meta charset='utf-8'><style>table{{width:100%;border-collapse:collapse}}th,td{{border:1px solid #ccc;padding:6px}}</style></head>
        <body><h2>Exam Conflicts - {exam_type}</h2><table><thead><tr><th>student_id</th><th>date</th><th>conflicting_courses</th></tr></thead><tbody>{rows_html}</tbody></table></body></html>
        """
        return pdf_response_from_html(html, filename_prefix=f"exam_conflicts_{exam_type}")
    else:
        return jsonify({"status":"error","message":"unsupported format"}), 400

@exams_bp.route('/<exam_type>/conflicts')
def exam_conflicts(exam_type):
    if exam_type not in VALID_TYPES:
        return jsonify({"conflicts": []})
    with get_connection() as conn:
        cur = conn.cursor()
        # Join exams with registrations to produce for each student the list of courses on each date
        q = '''
        SELECT r.student_id as student_id, e.exam_date as exam_date, GROUP_CONCAT(e.course_name) as courses, COUNT(e.course_name) as ccount
        FROM exams e
        JOIN registrations r ON r.course_name = e.course_name
        WHERE e.exam_type = ?
        GROUP BY r.student_id, e.exam_date
        HAVING ccount > 1
        '''
        rows = cur.execute(q, (exam_type,)).fetchall()
        out = []
        for r in rows:
            out.append({
                'student_id': r[0] or '',
                'exam_date': r[1] or '',
                'conflicting_courses': r[2] or ''
            })
        return jsonify({'conflicts': out})

@exams_bp.route('/<exam_type>/results_data')
def exam_results_data(exam_type):
    if exam_type not in VALID_TYPES:
        return jsonify({})
    exams = table_to_dicts('exams')
    exams = [e for e in exams if e.get('exam_type') == exam_type]
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute('SELECT student_id, exam_date, conflicting_courses FROM exam_conflicts WHERE exam_type = ?', (exam_type,))
        persisted = [dict(r) for r in cur.fetchall()]
        if not persisted:
            # compute on the fly
            conflicts_resp = exam_conflicts(exam_type).get_json()
            conflicts = conflicts_resp.get('conflicts', [])
        else:
            conflicts = persisted
    return jsonify({
        'exams': exams,
        'conflicts': conflicts
    })


@exams_bp.route('/<exam_type>/update_row', methods=['POST'])
def update_exam_row(exam_type):
    if exam_type not in VALID_TYPES:
        return jsonify({"status":"error","message":"invalid exam type"}), 400
    data = request.get_json(force=True) or {}
    exam_id = data.get('exam_id')
    if not exam_id:
        return jsonify({"status":"error","message":"exam_id required"}), 400
    fields = {}
    for k in ('course_name','exam_date','exam_time','room','instructor'):
        if k in data:
            fields[k] = data[k]
    if not fields:
        return jsonify({"status":"error","message":"no fields to update"}), 400
    sets = ','.join([f"{k} = ?" for k in fields.keys()])
    params = list(fields.values()) + [exam_id, exam_type]
    q = f"UPDATE exams SET {sets} WHERE rowid = ? AND exam_type = ?"
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(q, params)
        conn.commit()
    return jsonify({"status":"ok"})


@exams_bp.route('/<exam_type>/bulk_update', methods=['POST'])
def bulk_update_exam_rows(exam_type):
    if exam_type not in VALID_TYPES:
        return jsonify({"status":"error","message":"invalid exam type"}), 400
    data = request.get_json(force=True) or {}
    items = data.get('items') or []
    if not isinstance(items, list):
        return jsonify({"status":"error","message":"items must be a list"}), 400
    with get_connection() as conn:
        cur = conn.cursor()
        for it in items:
            exam_id = it.get('exam_id')
            if not exam_id:
                continue
            fields = {}
            for k in ('course_name','exam_date','exam_time','room','instructor'):
                if k in it:
                    fields[k] = it[k]
            if not fields:
                continue
            sets = ','.join([f"{k} = ?" for k in fields.keys()])
            params = list(fields.values()) + [exam_id, exam_type]
            q = f"UPDATE exams SET {sets} WHERE rowid = ? AND exam_type = ?"
            try:
                cur.execute(q, params)
            except Exception:
                # skip individual failures
                continue
        conn.commit()
    return jsonify({"status":"ok","updated": len(items)})

# helper to persist conflicts (used if we want to write to exam_conflicts)
def persist_exam_conflicts(exam_type):
    if exam_type not in VALID_TYPES:
        return 0
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute('DELETE FROM exam_conflicts WHERE exam_type = ?', (exam_type,))
        q = '''
        SELECT r.student_id as student_id, e.exam_date as exam_date, GROUP_CONCAT(e.course_name) as courses, COUNT(e.course_name) as ccount
        FROM exams e
        JOIN registrations r ON r.course_name = e.course_name
        WHERE e.exam_type = ?
        GROUP BY r.student_id, e.exam_date
        HAVING ccount > 1
        '''
        rows = cur.execute(q, (exam_type,)).fetchall()
        for r in rows:
            cur.execute('INSERT INTO exam_conflicts (exam_type, student_id, exam_date, conflicting_courses) VALUES (?,?,?,?)',
                        (exam_type, r[0] or '', r[1] or '', r[2] or ''))
        conn.commit()
        return len(rows)
