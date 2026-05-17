"""تعديل الدرجة — ربط الرمز بدليل المقررات مع تطبيع المسافات."""
from backend.services.grades import _norm_course_code, _resolve_catalog_course


class TestGradesUpdateCatalog:
    def test_norm_course_code_ignores_spaces(self):
        assert _norm_course_code("GE 102") == _norm_course_code("GE102")

    def test_resolve_catalog_by_normalized_code(self, db_conn):
        cur = db_conn.cursor()
        cur.execute(
            """
            INSERT OR REPLACE INTO courses (course_name, course_code, units)
            VALUES ('الرسم الهندسي', 'GE102', 3)
            """
        )
        db_conn.commit()
        resolved = _resolve_catalog_course(cur, course_name="الرسم الهندسي", course_code="GE 102")
        assert resolved["course_code"] == "GE102"
        assert resolved["course_name"] == "الرسم الهندسي"
