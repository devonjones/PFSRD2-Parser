"""Tests for markdown_pass div/p stripping and validation."""

import pytest

from universal.markdown import markdown_pass


class TestMarkdownDivStripping:
    """Tests that div and p tags are stripped before markdown validation."""

    def test_empty_div_stripped(self):
        struct = {"text": '<div class="clear"></div>Some text'}
        markdown_pass(struct, "test", "/test")
        assert "<div" not in struct["text"]
        assert "Some text" in struct["text"]

    def test_non_empty_div_rejected(self):
        """Non-empty divs indicate unparsed content and must fail validation."""
        struct = {"text": "<div>Content inside div</div>"}
        with pytest.raises(AssertionError):
            markdown_pass(struct, "test", "/test")

    def test_no_html_unchanged(self):
        struct = {"text": "Plain text no tags"}
        markdown_pass(struct, "test", "/test")
        assert struct["text"] == "Plain text no tags"

    def test_allowed_tags_pass(self):
        struct = {"text": "<b>bold</b> and <i>italic</i>"}
        markdown_pass(struct, "test", "/test")
        assert "bold" in struct["text"]
        assert "italic" in struct["text"]

    def test_p_tag_rejected(self):
        """p tags indicate unparsed content and must fail validation."""
        struct = {"text": "<p>Paragraph content</p>"}
        with pytest.raises(AssertionError):
            markdown_pass(struct, "test", "/test")

    def test_nested_dict_processed(self):
        struct = {"inner": {"text": "<b>nested bold</b>"}}
        markdown_pass(struct, "test", "/test")
        assert "nested bold" in struct["inner"]["text"]

    def test_license_path_allows_div_and_p(self):
        """License paths should allow div and p tags."""
        struct = {"text": "<p>License paragraph</p><div>License div</div>"}
        # /license path allows p and div
        markdown_pass(struct, "test", "/license")
        # Should not raise even though div and p are present


class TestMarkdownDisallowedTags:
    """Verify that unexpected tags cause assertion errors."""

    def test_script_tag_rejected(self):
        struct = {"text": "<script>alert('bad')</script>"}
        with pytest.raises(AssertionError):
            markdown_pass(struct, "test", "/test")

    def test_span_tag_rejected_without_callback(self):
        """span is not in the base validset."""
        struct = {"text": '<span class="action" title="Single Action">[#]</span>'}
        # Without a fxn_valid_tags callback, span should fail validation
        # But PFSRDConverter handles span with title attr, so it would be
        # caught by validation first
        with pytest.raises(AssertionError):
            markdown_pass(struct, "test", "/test")
