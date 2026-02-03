"""Unit tests for equipment.py helper functions."""

import pytest
from bs4 import BeautifulSoup

from pfsrd2.equipment import (
    _extract_ability_fields,
    _extract_affliction,
    _has_affliction_pattern,
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
        """Should extract simple activation type without parentheses (lowercased)."""
        ability = {}

        _parse_activation_content("Interact", ability)

        assert "activation_types" in ability
        assert len(ability["activation_types"]) == 1
        assert ability["activation_types"][0]["value"] == "interact"  # lowercased

    def test_extracts_multiple_activation_types(self):
        """Should extract comma-separated activation types (lowercased)."""
        ability = {}

        _parse_activation_content("command, Interact", ability)

        assert len(ability["activation_types"]) == 2
        values = [at["value"] for at in ability["activation_types"]]
        assert "command" in values
        assert "interact" in values  # lowercased

    def test_extracts_traits_from_parentheses(self):
        """Should extract traits from parentheses when linked."""
        html = 'command (<a href="Traits.aspx?ID=1" game-obj="Traits">manipulate</a>)'
        ability = {}

        _parse_activation_content(html, ability)

        assert "traits" in ability
        assert len(ability["traits"]) == 1
        assert ability["traits"][0]["name"] == "manipulate"

    def test_activation_before_parentheses(self):
        """Should use text before parentheses as activation type (lowercased)."""
        html = 'Interact (<a href="Traits.aspx?ID=1" game-obj="Traits">manipulate</a>)'
        ability = {}

        _parse_activation_content(html, ability)

        assert ability["activation_types"][0]["value"] == "interact"  # lowercased

    def test_non_trait_links_require_proper_attributes(self):
        """Non-trait links require proper game-obj attributes to be extracted."""
        # Note: get_links extracts links based on specific URL patterns
        # Plain href attributes without proper game-obj won't be extracted
        html = "command"
        ability = {}

        _parse_activation_content(html, ability)

        # Without proper links, only activation_types should be set
        assert "activation_types" in ability
        assert ability["activation_types"][0]["value"] == "command"

    def test_returns_trait_links_converted_count(self):
        """Should return count of trait links converted."""
        html = 'command (<a href="Traits.aspx?ID=1" game-obj="Traits">manipulate</a>)'
        ability = {}

        count = _parse_activation_content(html, ability)

        assert count == 1

    def test_unlinked_text_in_parentheses_not_treated_as_traits(self):
        """Plain text in parentheses is NOT a trait - only Traits.aspx links become traits."""
        # Per code comment: "Plain text in parentheses (like "Treat Disease") is NOT a trait"
        html = "command (magical)"
        ability = {}

        _parse_activation_content(html, ability)

        # Unlinked text should NOT become traits
        assert "traits" not in ability

    def test_filters_known_activations_from_traits(self):
        """Should not treat known activation methods as traits."""
        html = "command (Interact)"
        ability = {}

        _parse_activation_content(html, ability)

        # Interact should not be treated as a trait (it's not a linked trait anyway)
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
        """Should parse comma-separated activation types and lowercase them."""
        result = _parse_activation_types("command, Interact")

        assert len(result) == 2
        values = [at["value"] for at in result]
        assert "command" in values
        assert "interact" in values  # lowercased

    def test_semicolon_separated_values(self):
        """Should parse semicolon-separated activation types and lowercase them."""
        result = _parse_activation_types("command; Interact")

        assert len(result) == 2
        values = [at["value"] for at in result]
        assert "command" in values
        assert "interact" in values  # lowercased

    def test_preserves_parentheses(self):
        """Should preserve text within parentheses when splitting, but lowercase."""
        result = _parse_activation_types("Cast a Spell (arcane, divine)")

        # Should be single value because parentheses protect the comma
        assert len(result) == 1
        assert result[0]["value"] == "cast a spell (arcane, divine)"  # lowercased

    def test_strips_whitespace(self):
        """Should strip whitespace from values and lowercase them."""
        result = _parse_activation_types("  command  ,  Interact  ")

        assert len(result) == 2
        assert result[0]["value"] == "command"
        assert result[1]["value"] == "interact"  # lowercased

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


class TestHasAfflictionPattern:
    """Tests for _has_affliction_pattern helper."""

    def test_detects_saving_throw_with_stage(self):
        """Should detect affliction pattern with Saving Throw + Stage."""
        html = "<b>Saving Throw</b> DC 20 Fortitude; <b>Stage 1</b> stupefied 1 (1 hour)"
        soup = BeautifulSoup(html, "html.parser")

        assert _has_affliction_pattern(soup) is True

    def test_detects_saving_throw_with_maximum_duration(self):
        """Should detect affliction pattern with Saving Throw + Maximum Duration."""
        html = "<b>Saving Throw</b> DC 20 Fortitude; <b>Maximum Duration</b> 8 hours"
        soup = BeautifulSoup(html, "html.parser")

        assert _has_affliction_pattern(soup) is True

    def test_detects_saving_throw_with_onset(self):
        """Should detect affliction pattern with Saving Throw + Onset."""
        html = "<b>Saving Throw</b> DC 33 Fortitude; <b>Onset</b> 1 minute"
        soup = BeautifulSoup(html, "html.parser")

        assert _has_affliction_pattern(soup) is True

    def test_returns_false_without_saving_throw(self):
        """Should return False when no Saving Throw tag present."""
        html = "<b>Stage 1</b> stupefied 1 (1 hour); <b>Stage 2</b> stupefied 2 (1 hour)"
        soup = BeautifulSoup(html, "html.parser")

        assert _has_affliction_pattern(soup) is False

    def test_returns_false_saving_throw_without_followup(self):
        """Should return False when Saving Throw has no stage/duration/onset."""
        html = "<b>Saving Throw</b> DC 20 Fortitude; <b>Effect</b> something"
        soup = BeautifulSoup(html, "html.parser")

        assert _has_affliction_pattern(soup) is False

    def test_returns_false_for_empty_soup(self):
        """Should return False for empty soup."""
        soup = BeautifulSoup("", "html.parser")

        assert _has_affliction_pattern(soup) is False

    def test_ignores_saving_throw_in_plain_text(self):
        """Should not detect Saving Throw in plain text (no bold tag)."""
        html = "Saving Throw DC 20 Fortitude; <b>Stage 1</b> effect"
        soup = BeautifulSoup(html, "html.parser")

        assert _has_affliction_pattern(soup) is False

    def test_detects_with_narrative_text_before(self):
        """Should detect affliction even with narrative text before it."""
        html = (
            "This drug is highly addictive.<br/>"
            "<b>Saving Throw</b> DC 20 Fortitude; "
            "<b>Maximum Duration</b> 8 hours; "
            "<b>Stage 1</b> effect (1 hour)"
        )
        soup = BeautifulSoup(html, "html.parser")

        assert _has_affliction_pattern(soup) is True


class TestExtractAffliction:
    """Tests for _extract_affliction helper."""

    def test_returns_none_when_no_saving_throw(self):
        """Should return (None, []) when no Saving Throw tag."""
        html = "<b>Effect</b> something happens"
        soup = BeautifulSoup(html, "html.parser")

        affliction, links = _extract_affliction(soup, "Test Item")

        assert affliction is None
        assert links == []

    def test_parses_saving_throw(self):
        """Should parse saving throw DC and type."""
        html = "<b>Saving Throw</b> DC 20 Fortitude; <b>Stage 1</b> effect (1 hour)"
        soup = BeautifulSoup(html, "html.parser")

        affliction, _ = _extract_affliction(soup, "Test Item")

        assert affliction["saving_throw"]["dc"] == 20
        assert affliction["saving_throw"]["save_type"] == "Fort"

    def test_parses_maximum_duration(self):
        """Should parse Maximum Duration field."""
        html = (
            "<b>Saving Throw</b> DC 20 Fortitude; "
            "<b>Maximum Duration</b> 8 hours; "
            "<b>Stage 1</b> effect (1 hour)"
        )
        soup = BeautifulSoup(html, "html.parser")

        affliction, _ = _extract_affliction(soup, "Test Item")

        assert affliction["maximum_duration"] == "8 hours"

    def test_parses_onset(self):
        """Should parse Onset field."""
        html = (
            "<b>Saving Throw</b> DC 33 Fortitude; "
            "<b>Onset</b> 1 minute; "
            "<b>Maximum Duration</b> 6 minutes; "
            "<b>Stage 1</b> dazzled (1 minute)"
        )
        soup = BeautifulSoup(html, "html.parser")

        affliction, _ = _extract_affliction(soup, "Test Item")

        assert affliction["onset"] == "1 minute"

    def test_parses_single_stage(self):
        """Should parse a single stage."""
        html = "<b>Saving Throw</b> DC 20 Fortitude; <b>Stage 1</b> stupefied 1 (1 hour)"
        soup = BeautifulSoup(html, "html.parser")

        affliction, _ = _extract_affliction(soup, "Test Item")

        assert len(affliction["stages"]) == 1
        assert affliction["stages"][0]["name"] == "Stage 1"
        assert affliction["stages"][0]["text"] == "stupefied 1 (1 hour)"

    def test_parses_multiple_stages(self):
        """Should parse multiple stages."""
        html = (
            "<b>Saving Throw</b> DC 20 Fortitude; "
            "<b>Maximum Duration</b> 6 hours; "
            "<b>Stage 1</b> flat-footed (1 round); "
            "<b>Stage 2</b> slowed 2 and flat-footed (1 round); "
            "<b>Stage 3</b> unconscious (1 round); "
            "<b>Stage 4</b> unconscious (1 round)"
        )
        soup = BeautifulSoup(html, "html.parser")

        affliction, _ = _extract_affliction(soup, "Test Item")

        assert len(affliction["stages"]) == 4
        assert affliction["stages"][0]["name"] == "Stage 1"
        assert affliction["stages"][3]["name"] == "Stage 4"

    def test_stage_objects_have_correct_structure(self):
        """Should create stage objects with correct type/subtype."""
        html = "<b>Saving Throw</b> DC 20 Fortitude; <b>Stage 1</b> effect (1 hour)"
        soup = BeautifulSoup(html, "html.parser")

        affliction, _ = _extract_affliction(soup, "Test Item")

        stage = affliction["stages"][0]
        assert stage["type"] == "stat_block_section"
        assert stage["subtype"] == "affliction_stage"

    def test_affliction_has_correct_structure(self):
        """Should create affliction object with correct type/subtype/name."""
        html = "<b>Saving Throw</b> DC 20 Fortitude; <b>Stage 1</b> effect (1 hour)"
        soup = BeautifulSoup(html, "html.parser")

        affliction, _ = _extract_affliction(soup, "Demon Dust")

        assert affliction["type"] == "stat_block_section"
        assert affliction["subtype"] == "affliction"
        assert affliction["name"] == "Demon Dust"

    def test_extracts_links(self):
        """Should extract links from affliction HTML."""
        html = (
            "<b>Saving Throw</b> DC 20 Fortitude; "
            '<b>Stage 1</b> <a href="Conditions.aspx?ID=37" game-obj="Conditions">stupefied 1</a> (1 hour)'
        )
        soup = BeautifulSoup(html, "html.parser")

        affliction, links = _extract_affliction(soup, "Test Item")

        assert len(links) == 1
        assert links[0]["name"] == "stupefied 1"
        assert affliction["links"] == links

    def test_no_links_key_when_no_links(self):
        """Should not add links key when no links present."""
        html = "<b>Saving Throw</b> DC 20 Fortitude; <b>Stage 1</b> stupefied 1 (1 hour)"
        soup = BeautifulSoup(html, "html.parser")

        affliction, links = _extract_affliction(soup, "Test Item")

        assert "links" not in affliction
        assert links == []

    def test_removes_affliction_nodes_from_soup(self):
        """Should remove affliction nodes from desc_soup after extraction."""
        html = (
            "This drug is addictive.<br/>"
            "<b>Saving Throw</b> DC 20 Fortitude; "
            "<b>Stage 1</b> stupefied 1 (1 hour)"
        )
        soup = BeautifulSoup(html, "html.parser")

        _extract_affliction(soup, "Test Item")

        remaining = soup.get_text().strip()
        assert "Saving Throw" not in remaining
        assert "Stage 1" not in remaining
        assert "addictive" in remaining

    def test_removes_preceding_br_tags(self):
        """Should remove <br> tags between narrative and affliction."""
        html = (
            "Narrative text.<br/><br/>"
            "<b>Saving Throw</b> DC 20 Fortitude; "
            "<b>Stage 1</b> effect (1 hour)"
        )
        soup = BeautifulSoup(html, "html.parser")

        _extract_affliction(soup, "Test Item")

        assert soup.find("br") is None

    def test_normalizes_whitespace_in_stages(self):
        """Should collapse whitespace and fix spaces before punctuation."""
        html = "<b>Saving Throw</b> DC 20 Fortitude; " "<b>Stage 1</b> stupefied\n1 (1\nhour)"
        soup = BeautifulSoup(html, "html.parser")

        affliction, _ = _extract_affliction(soup, "Test Item")

        assert affliction["stages"][0]["text"] == "stupefied 1 (1 hour)"

    def test_parses_effect_field(self):
        """Should parse Effect field."""
        html = "<b>Saving Throw</b> DC 20 Fortitude; " "<b>Effect</b> The target is dazed"
        soup = BeautifulSoup(html, "html.parser")

        affliction, _ = _extract_affliction(soup, "Test Item")

        assert affliction["effect"] == "The target is dazed"

    def test_full_affliction_with_all_fields(self):
        """Should correctly parse a complete affliction with all fields."""
        html = (
            "<b>Saving Throw</b> DC 33 Fortitude; "
            "<b>Onset</b> 1 minute; "
            "<b>Maximum Duration</b> 6 minutes; "
            '<b>Stage 1</b> <a href="Conditions.aspx?ID=12" game-obj="Conditions">dazzled</a> (1 minute); '
            '<b>Stage 2</b> <a href="Conditions.aspx?ID=15" game-obj="Conditions">drained 1</a> (1 minute); '
            '<b>Stage 3</b> <a href="Conditions.aspx?ID=15" game-obj="Conditions">drained 2</a> (1 minute)'
        )
        soup = BeautifulSoup(html, "html.parser")

        affliction, links = _extract_affliction(soup, "Spectral Nightshade")

        assert affliction["name"] == "Spectral Nightshade"
        assert affliction["saving_throw"]["dc"] == 33
        assert affliction["onset"] == "1 minute"
        assert affliction["maximum_duration"] == "6 minutes"
        assert len(affliction["stages"]) == 3
        assert affliction["stages"][0]["text"] == "dazzled (1 minute)"
        assert affliction["stages"][1]["text"] == "drained 1 (1 minute)"
        assert len(links) == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
