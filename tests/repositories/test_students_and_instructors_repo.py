from backend.repositories import instructors_repo, students_repo


def test_exists_student_id_true_for_seeded(db_conn):
    cur = db_conn.cursor()
    one = cur.execute("SELECT student_id FROM students LIMIT 1").fetchone()
    assert one is not None
    sid = one[0]
    assert students_repo.exists_student_id(db_conn, sid)
    assert not students_repo.exists_student_id(db_conn, "__no_such_student__")


def test_exists_instructor_id_after_insert(db_conn):
    cur = db_conn.cursor()
    cur.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM instructors")
    nid = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO instructors (id, name, type) VALUES (?, ?, ?)",
        (nid, "مختبر مستودع", "internal"),
    )
    db_conn.commit()
    assert instructors_repo.exists_instructor_id(db_conn, nid)
    assert not instructors_repo.exists_instructor_id(db_conn, 999_999_999)
