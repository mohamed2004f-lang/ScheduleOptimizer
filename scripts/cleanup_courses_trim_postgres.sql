-- تشخيص فقط: مراجعة قبل تنظيف المسافات على courses (PostgreSQL)
-- للتنفيذ الآمن (فحص تعارضات، ترتيب: الرمز ثم الاسم، معاملة واحدة):
--   python scripts/cleanup_courses_trim.py
--   python scripts/cleanup_courses_trim.py --apply

-- أسماء تحتاج تقليم طرفي
SELECT course_name AS old_name, trim(course_name) AS trimmed
FROM courses
WHERE course_name <> trim(course_name)
ORDER BY course_name;

-- رموز تحتاج تقليم طرفي
SELECT course_name, course_code AS old_code, trim(course_code) AS trimmed_code
FROM courses
WHERE course_code IS NOT NULL
  AND course_code <> ''
  AND course_code <> trim(course_code)
ORDER BY course_name;

-- تعارض أسماء: أكثر من قيمة خام تتطابق بعد trim (يمنع تحديث المفتاح بأمان)
SELECT trim(course_name) AS t,
       count(*) AS row_count,
       count(DISTINCT course_name) AS distinct_raw_names
FROM courses
GROUP BY trim(course_name)
HAVING count(DISTINCT course_name) > 1;

-- تعارض رموز: أكثر من صف يشتركان بالرمز نفسه بعد trim
SELECT lower(trim(course_code)) AS k, count(*) AS n
FROM courses
WHERE course_code IS NOT NULL AND trim(course_code) <> ''
GROUP BY lower(trim(course_code))
HAVING count(*) > 1;
