from backend.repositories import schedule_repo


def test_group_assigned_tuples_by_course_merges_slots():
    rows = [
        (2, "فيزياء 1", "الأحد", "08:00-09:30", "قاعة 1", "أستاذ", "خريف 44-45"),
        (5, "فيزياء 1", "الاثنين", "10:00-11:30", "قاعة 2", "أستاذ", "خريف 44-45"),
    ]
    grouped = schedule_repo.group_assigned_tuples_by_course(rows)
    assert len(grouped) == 1
    assert grouped[0]["section_id"] == 2
    assert grouped[0]["section_ids"] == [2, 5]


def test_count_students_empty_course_list_is_zero(db_conn):
    cur = db_conn.cursor()
    assert schedule_repo.count_distinct_students_for_courses(cur, []) == 0
    assert schedule_repo.count_students_grouped_by_course(cur, []) == {}


def test_fetch_schedule_rows_with_student_counts_returns_seeded(db_conn):
    cur = db_conn.cursor()
    n = cur.execute("SELECT COUNT(*) FROM schedule").fetchone()[0]
    if not n:
        return
    rows = schedule_repo.fetch_schedule_rows_with_student_counts(cur, pk_col="id")
    assert len(rows) == n
    assert len(rows[0]) >= 9
    assert rows[0][8] is None or int(rows[0][8]) >= 0
