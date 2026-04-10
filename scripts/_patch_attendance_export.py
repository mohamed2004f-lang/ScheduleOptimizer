from pathlib import Path

p = Path(__file__).resolve().parent.parent / "backend" / "services" / "students.py"
text = p.read_text(encoding="utf-8")
start = text.find(
    '    raw_courses = request.args.getlist("course") or request.args.getlist("courses")'
)
if start < 0:
    raise SystemExit("start not found")
end = text.find(
    '        return excel_response_from_frames(frames, filename_prefix="attendance")\n    except Exception:',
    start,
)
if end < 0:
    raise SystemExit("end not found")
end += len('        return excel_response_from_frames(frames, filename_prefix="attendance")\n')

new_block = r'''    try:
        r = _collect_attendance_export_state(get_connection, get_current_term, normalize_sid, course_name_lock=None)
        if r["kind"] == "http":
            return r["response"]
        if r["kind"] == "empty_excel":
            frames = [("ملخص", pd.DataFrame(r["summaries"]))]
            return excel_response_from_frames(frames, filename_prefix="attendance")

        weeks = r["weeks"]
        selected_courses = r["selected_courses"]
        course_students = r["course_students"]
        attendance_map = r["attendance_map"]
        missing_courses = r["missing_courses"]

        summaries = []
        frames = []
        week_columns = [f"الأسبوع {i}" for i in range(1, weeks + 1)]

        for course_name in selected_courses:
            students_list = course_students.get(course_name, [])
            notes = ""
            if not students_list:
                notes = "لا توجد تسجيلات للمقرر"
            summaries.append({
                "المقرر": course_name,
                "عدد الطلبة": len(students_list),
                "عدد الأسابيع": weeks,
                "ملاحظات": notes
            })

            rows = []
            for student in students_list:
                sid = student["student_id"]
                row = {
                    "الرقم الدراسي": sid,
                    "اسم الطالب": student["student_name"]
                }
                week_statuses = attendance_map.get((course_name, sid), {})
                for idx, col in enumerate(week_columns, start=1):
                    row[col] = week_statuses.get(idx, "")
                rows.append(row)

            if rows:
                df = pd.DataFrame(rows)
            else:
                df = pd.DataFrame(columns=["الرقم الدراسي", "اسم الطالب", *week_columns])
            frames.append((course_name, df))

        seen_missing = set()
        for missing in missing_courses:
            mk = missing.lower()
            if mk in seen_missing:
                continue
            seen_missing.add(mk)
            summaries.append({
                "المقرر": missing,
                "عدد الطلبة": 0,
                "عدد الأسابيع": weeks,
                "ملاحظات": "المقرر غير موجود في قاعدة البيانات"
            })

        summary_df = pd.DataFrame(summaries)
        frames.insert(0, ("ملخص", summary_df))

        return excel_response_from_frames(frames, filename_prefix="attendance")
'''

text2 = text[:start] + new_block + text[end:]
p.write_text(text2, encoding="utf-8")
print("patched", start, end)
