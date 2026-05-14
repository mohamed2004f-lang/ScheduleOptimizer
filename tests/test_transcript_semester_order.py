"""ترتيب فصول كشف الدرجات زمنياً (خريف 21-22 ثم ربيع 21-22 ...)."""


def test_sort_transcript_semester_labels_year_and_term():
    from backend.services.grades import _sort_transcript_semester_labels

    labels = ["ربيع 21-22", "خريف 22-23", "خريف 21-22", "صيف 21-22", "ربيع 22-23"]
    assert _sort_transcript_semester_labels(labels) == [
        "خريف 21-22",
        "ربيع 21-22",
        "صيف 21-22",
        "خريف 22-23",
        "ربيع 22-23",
    ]


def test_sort_transcript_semester_labels_year_first():
    from backend.services.grades import _sort_transcript_semester_labels

    assert _sort_transcript_semester_labels(["21-22 ربيع", "21-22 خريف"]) == [
        "21-22 خريف",
        "21-22 ربيع",
    ]


def test_unknown_semester_labels_sort_last():
    from backend.services.grades import _sort_transcript_semester_labels

    out = _sort_transcript_semester_labels(["خريف 21-22", "بدون_سنة", "ربيع 21-22"])
    assert out[0] == "خريف 21-22"
    assert out[1] == "ربيع 21-22"
    assert out[2] == "بدون_سنة"
