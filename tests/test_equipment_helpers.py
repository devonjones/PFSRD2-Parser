"""Unit tests for equipment.py helper functions."""

import pytest
from bs4 import BeautifulSoup

from pfsrd2.equipment import (
    _extract_ability_fields,
    _parse_activation_content,
    _parse_activation_types,
    _parse_named_activation,
)


class TestExtractAbilityFields:
    """Tests for _extract_ability_fields helper."""

    def test_extracts_frequency(self):
        """Should extract Frequency field."""
        html = "<b>Activate</b> command; <b>Frequency</b> once per day"
        soup = BeautifulSoup(html, "html.parser")
        ability = {}

        _extract_ability_fields(soup, ability)

        assert ability["frequency"] == "once per day"

    def test_extracts_trigger(self):
        """Should extract Trigger field."""
        html = "<b>Activate</b> reaction; <b>Trigger</b> you are hit by an attack"
        soup = BeautifulSoup(html, "html.parser")
        ability = {}

        _extract_ability_fields(soup, ability)

        assert ability["trigger"] == "you are hit by an attack"

    def test_extracts_effect(self):
        """Should extract Effect field."""
        html = "<b>Activate</b> command; <b>Effect</b> The gem glows brightly."
        soup = BeautifulSoup(html, "html.parser")
        ability = {}

        _extract_ability_fields(soup, ability)

        assert ability["effect"] == "The gem glows brightly."

    def test_extracts_requirements_as_requirement(self):
        """Should extract Requirements field as 'requirement' key."""
        html = "<b>Activate</b> command; <b>Requirements</b> You are holding the item"
        soup = BeautifulSoup(html, "html.parser")
        ability = {}

        _extract_ability_fields(soup, ability)

        assert ability["requirement"] == "You are holding the item"

    def test_extracts_multiple_fields(self):
        """Should extract multiple fields from same ability."""
        html = (
            "<b>Activate</b> command; "
            "<b>Frequency</b> once per day; "
            "<b>Trigger</b> you see an enemy; "
            "<b>Effect</b> You strike fear."
        )
        soup = BeautifulSoup(html, "html.parser")
        ability = {}

        _extract_ability_fields(soup, ability)

        assert ability["frequency"] == "once per day"
        assert ability["trigger"] == "you see an enemy"
        assert ability["effect"] == "You strike fear."

    def test_cleans_leading_semicolons(self):
        """Should remove leading semicolons from values."""
        html = "<b>Activate</b> command; <b>Frequency</b>; once per day"
        soup = BeautifulSoup(html, "html.parser")
        ability = {}

        _extract_ability_fields(soup, ability)

        assert ability["frequency"] == "once per day"

    def test_extracts_links(self):
        """Should extract links from field values."""
        html = (
            "<b>Activate</b> command; "
            '<b>Effect</b> Cast <a href="Spells.aspx?ID=123" game-obj="Spells">fireball</a>.'
        )
        soup = BeautifulSoup(html, "html.parser")
        ability = {}

        _extract_ability_fields(soup, ability)

        assert "links" in ability
        assert len(ability["links"]) == 1
        assert ability["links"][0]["name"] == "fireball"

    def test_no_fields_present(self):
        """Should handle HTML with no extractable fields."""
        html = "<b>Activate</b> command"
        soup = BeautifulSoup(html, "html.parser")
        ability = {}

        _extract_ability_fields(soup, ability)

        assert "frequency" not in ability
        assert "trigger" not in ability
        assert "effect" not in ability
        assert "requirement" not in ability


class TestParseNamedActivation:
    """Tests for _parse_named_activation helper."""

    def test_detects_em_dash_named_activation(self):
        """Should detect named activation with em-dash prefix."""
        html = "<b>—Dim Sight</b>"
        soup = BeautifulSoup(html, "html.parser")
        bold = soup.find("b")

        ability_name, next_sib = _parse_named_activation(bold)

        assert ability_name == "Dim Sight"

    def test_detects_en_dash_named_activation(self):
        """Should detect named activation with en-dash prefix."""
        html = "<b>–Power Strike</b>"
        soup = BeautifulSoup(html, "html.parser")
        bold = soup.find("b")

        ability_name, next_sib = _parse_named_activation(bold)

        assert ability_name == "Power Strike"

    def test_detects_hyphen_named_activation(self):
        """Should detect named activation with regular hyphen prefix."""
        html = "<b>-Quick Draw</b>"
        soup = BeautifulSoup(html, "html.parser")
        bold = soup.find("b")

        ability_name, next_sib = _parse_named_activation(bold)

        assert ability_name == "Quick Draw"

    def test_returns_none_for_non_named(self):
        """Should return None for bold tags without dash prefix."""
        html = "<b>Frequency</b>"
        soup = BeautifulSoup(html, "html.parser")
        bold = soup.find("b")

        ability_name, next_sib = _parse_named_activation(bold)

        assert ability_name is None
        assert next_sib == bold

    def test_returns_none_for_non_tag(self):
        """Should return None for non-Tag elements."""
        soup = BeautifulSoup("plain text", "html.parser")
        text_node = soup.string

        ability_name, next_sib = _parse_named_activation(text_node)

        assert ability_name is None

    def test_returns_none_for_empty_bold(self):
        """Should return None for empty bold tag."""
        html = "<b></b>"
        soup = BeautifulSoup(html, "html.parser")
        bold = soup.find("b")

        ability_name, next_sib = _parse_named_activation(bold)

        assert ability_name is None

    def test_returns_next_sibling(self):
        """Should return next sibling when named activation detected."""
        html = "<b>—Named</b> following content"
        soup = BeautifulSoup(html, "html.parser")
        bold = soup.find("b")

        ability_name, next_sib = _parse_named_activation(bold)

        assert ability_name == "Named"
        assert next_sib is not None
        assert "following" in str(next_sib)

    def test_strips_whitespace_from_name(self):
        """Should strip whitespace from extracted name."""
        html = "<b>—  Spaced Name  </b>"
        soup = BeautifulSoup(html, "html.parser")
        bold = soup.find("b")

        ability_name, next_sib = _parse_named_activation(bold)

        assert ability_name == "Spaced Name"


class TestParseActivationContent:
    """Tests for _parse_activation_content helper."""

    def test_extracts_simple_activation_type(self):
        """Should extract simple activation type without parentheses."""
        ability = {}

        _parse_activation_content("Interact", ability)

        assert "activation_types" in ability
        assert len(ability["activation_types"]) == 1
        assert ability["activation_types"][0]["value"] == "Interact"

    def test_extracts_multiple_activation_types(self):
        """Should extract comma-separated activation types."""
        ability = {}

        _parse_activation_content("command, Interact", ability)

        assert len(ability["activation_types"]) == 2
        values = [at["value"] for at in ability["activation_types"]]
        assert "command" in values
        assert "Interact" in values

    def test_extracts_traits_from_parentheses(self):
        """Should extract traits from parentheses."""
        html = 'command (<a href="Traits.aspx?ID=1" game-obj="Traits">manipulate</a>)'
        ability = {}

        _parse_activation_content(html, ability)

        assert "traits" in ability
        assert len(ability["traits"]) == 1
        assert ability["traits"][0]["name"] == "manipulate"

    def test_activation_before_parentheses(self):
        """Should use text before parentheses as activation type."""
        html = 'Interact (<a href="Traits.aspx?ID=1" game-obj="Traits">manipulate</a>)'
        ability = {}

        _parse_activation_content(html, ability)

        assert ability["activation_types"][0]["value"] == "Interact"

    def test_non_trait_links_added_to_links(self):
        """Should add non-trait links to ability links array."""
        html = 'command; see <a href="Spells.aspx?ID=123" game-obj="Spells">fireball</a>'
        ability = {}

        _parse_activation_content(html, ability)

        assert "links" in ability
        assert len(ability["links"]) == 1
        assert ability["links"][0]["name"] == "fireball"

    def test_returns_trait_links_converted_count(self):
        """Should return count of trait links converted."""
        html = 'command (<a href="Traits.aspx?ID=1" game-obj="Traits">manipulate</a>)'
        ability = {}

        count = _parse_activation_content(html, ability)

        assert count == 1

    def test_handles_unlinked_traits_in_parentheses(self):
        """Should handle unlinked trait names in parentheses."""
        html = "command (magical)"
        ability = {}

        _parse_activation_content(html, ability)

        assert "traits" in ability
        assert ability["traits"][0]["name"] == "magical"

    def test_filters_known_activations_from_traits(self):
        """Should not treat known activation methods as traits."""
        html = "command (Interact)"
        ability = {}

        _parse_activation_content(html, ability)

        # Interact should not be treated as a trait
        assert "traits" not in ability or len(ability.get("traits", [])) == 0

    def test_activation_type_objects_have_correct_structure(self):
        """Should create activation_type objects with correct structure."""
        ability = {}

        _parse_activation_content("command", ability)

        at = ability["activation_types"][0]
        assert at["type"] == "stat_block_section"
        assert at["subtype"] == "activation_type"
        assert at["value"] == "command"


class TestParseActivationTypes:
    """Tests for _parse_activation_types helper."""

    def test_empty_string_returns_empty_list(self):
        """Should return empty list for empty string."""
        result = _parse_activation_types("")

        assert result == []

    def test_none_returns_empty_list(self):
        """Should return empty list for None input."""
        result = _parse_activation_types(None)

        assert result == []

    def test_single_value(self):
        """Should parse single activation type."""
        result = _parse_activation_types("command")

        assert len(result) == 1
        assert result[0]["value"] == "command"

    def test_comma_separated_values(self):
        """Should parse comma-separated activation types."""
        result = _parse_activation_types("command, Interact")

        assert len(result) == 2
        values = [at["value"] for at in result]
        assert "command" in values
        assert "Interact" in values

    def test_semicolon_separated_values(self):
        """Should parse semicolon-separated activation types."""
        result = _parse_activation_types("command; Interact")

        assert len(result) == 2
        values = [at["value"] for at in result]
        assert "command" in values
        assert "Interact" in values

    def test_preserves_parentheses(self):
        """Should preserve text within parentheses when splitting."""
        result = _parse_activation_types("Cast a Spell (arcane, divine)")

        # Should be single value because parentheses protect the comma
        assert len(result) == 1
        assert result[0]["value"] == "Cast a Spell (arcane, divine)"

    def test_strips_whitespace(self):
        """Should strip whitespace from values."""
        result = _parse_activation_types("  command  ,  Interact  ")

        assert len(result) == 2
        assert result[0]["value"] == "command"
        assert result[1]["value"] == "Interact"

    def test_filters_empty_values(self):
        """Should filter out empty values."""
        result = _parse_activation_types("command, , Interact")

        assert len(result) == 2
        values = [at["value"] for at in result]
        assert "" not in values

    def test_correct_object_structure(self):
        """Should create objects with correct structure."""
        result = _parse_activation_types("command")

        assert result[0]["type"] == "stat_block_section"
        assert result[0]["subtype"] == "activation_type"
        assert "value" in result[0]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
