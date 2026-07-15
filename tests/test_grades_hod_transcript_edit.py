"""تصحيح الدرجة من السجل بعد النشر — رئيس القسم والأدمن الرئيسي."""
from backend.services.grades import (
    _audit_changed_by,
    _is_college_transcript_editor,
    _require_post_publish_reason,
)


class TestHodPostPublishReason:
    def test_reason_required_when_flag_true(self):
        try:
            _require_post_publish_reason("abc", required=True)
            assert False, "expected ValueError"
        except ValueError as exc:
            assert "سبب التصحيح" in str(exc)

    def test_reason_accepted(self):
        assert _require_post_publish_reason("تصحيح رقمي معتمد", required=True) == "تصحيح رقمي معتمد"

    def test_reason_optional_for_admin(self):
        assert _require_post_publish_reason("", required=False) == ""

    def test_audit_changed_by_includes_reason(self):
        # actor comes from session; without request context falls back to system
        stamp = _audit_changed_by(reason="خطأ إدخال", kind="post_publish")
        assert "post_publish" in stamp
        assert "خطأ إدخال" in stamp

    def test_college_editor_false_outside_request(self):
        assert _is_college_transcript_editor() is False
