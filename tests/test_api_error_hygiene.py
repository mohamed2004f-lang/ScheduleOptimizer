"""إخفاء تفاصيل الأخطاء الداخلية عن العميل."""


def test_students_api_handle_errors_hides_exception_details(app):
    from backend.api.students_api import handle_errors

    @handle_errors
    def boom():
        raise RuntimeError("secret-sql-trace")

    with app.test_request_context():
        resp, status = boom()
    assert status == 500
    data = resp.get_json()
    assert data["error"] == "Internal server error"
    assert "details" not in data
    assert "secret-sql-trace" not in str(data)


def test_instructors_api_handle_errors_hides_exception_details(app):
    from backend.api.instructors_api import handle_errors

    @handle_errors
    def boom():
        raise RuntimeError("secret-sql-trace")

    with app.test_request_context():
        resp, status = boom()
    assert status == 500
    data = resp.get_json()
    assert data["error"] == "Internal server error"
    assert "details" not in data
    assert "secret-sql-trace" not in str(data)
