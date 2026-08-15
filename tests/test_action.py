"""Unit tests for action.py helper functions."""

import pytest

from pfsrd2.action import extract_action_type


class TestExtractActionTypeOrMore:
    """Tests for 'or more' handling in extract_action_type."""

    def _action_span(self, title):
        return f'<span class="action" title="{title}"><img src="x.png" /></span>'

    def test_one_action_or_more(self):
        """Single Action + 'or more' should produce 'One Action or more'."""
        text = f'{self._action_span("Single Action")} or more (Interact); Effect text'
        remaining, action = extract_action_type(text)
        assert action["name"] == "One Action or more"
        assert "(Interact)" in remaining

    def test_two_actions_or_more(self):
        """Two Actions + 'or more' should produce 'Two Actions or more'."""
        text = f'{self._action_span("Two Actions")} or more'
        remaining, action = extract_action_type(text)
        assert action["name"] == "Two Actions or more"

    def test_remaining_text_after_or_more(self):
        """Text after 'or more' should be preserved in remaining text."""
        text = f'{self._action_span("Single Action")} or more (envision, Interact); do stuff'
        remaining, action = extract_action_type(text)
        assert action["name"] == "One Action or more"
        assert "(envision, Interact); do stuff" in remaining

    def test_single_action_without_or_more(self):
        """Single action without 'or more' should produce 'One Action'."""
        text = f'{self._action_span("Single Action")} (Interact); Effect text'
        remaining, action = extract_action_type(text)
        assert action["name"] == "One Action"


class TestExtractActionTypeBasic:
    """Basic tests for extract_action_type."""

    def _action_span(self, title):
        return f'<span class="action" title="{title}"><img src="x.png" /></span>'

    def test_reaction(self):
        """Reaction span should produce 'Reaction'."""
        text = f'{self._action_span("Reaction")} trigger text'
        remaining, action = extract_action_type(text)
        assert action["name"] == "Reaction"

    def test_free_action(self):
        """Free Action span should produce 'Free Action'."""
        text = f'{self._action_span("Free Action")} command text'
        remaining, action = extract_action_type(text)
        assert action["name"] == "Free Action"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
