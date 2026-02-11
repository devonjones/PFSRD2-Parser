"""Unit tests for equipment.py helper functions."""

import pytest
from bs4 import BeautifulSoup

from pfsrd2.equipment import (
    DEFAULT_FIELD_DESTINATIONS,
    EQUIPMENT_TYPES,
    _clean_activation_cruft_from_text,
    _collect_equipment_ability_content,
    _count_links_in_html,
    _deduplicate_links_across_abilities,
    _extract_ability_fields,
    _extract_action_type_from_spans,
    _extract_activation_traits_from_parens,
    _extract_affliction,
    _find_ability_bolds,
    _has_affliction_pattern,
    _normalize_activate_to_ability,
    _parse_activation_content,
    _parse_activation_types,
    _parse_named_activation,
    _process_activate_content,
    _should_exclude_link,
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

    def test_non_trait_links_added_to_links(self):
        """Should add non-trait links from within parentheses to the ability's links array."""
        html = 'command (<a href="Spells.aspx?ID=123" game-obj="Spells">fireball</a>)'
        ability = {}

        _parse_activation_content(html, ability)

        assert "links" in ability
        assert len(ability["links"]) == 1
        assert ability["links"][0]["name"] == "fireball"
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

    def test_detects_stage_only_without_saving_throw(self):
        """Should detect stage-only pattern (no Saving Throw) as affliction."""
        html = "<b>Stage 1</b> stupefied 1 (1 hour); <b>Stage 2</b> stupefied 2 (1 hour)"
        soup = BeautifulSoup(html, "html.parser")

        assert _has_affliction_pattern(soup) is True

    def test_returns_false_saving_throw_without_followup(self):
        """Should return False when Saving Throw has no stage/duration/onset."""
        html = "<b>Saving Throw</b> DC 20 Fortitude; <b>Effect</b> something"
        soup = BeautifulSoup(html, "html.parser")

        assert _has_affliction_pattern(soup) is False

    def test_returns_false_for_empty_soup(self):
        """Should return False for empty soup."""
        soup = BeautifulSoup("", "html.parser")

        assert _has_affliction_pattern(soup) is False

    def test_detects_stage_with_saving_throw_in_plain_text(self):
        """Stage-only detection should still trigger even if Saving Throw is plain text."""
        html = "Saving Throw DC 20 Fortitude; <b>Stage 1</b> effect"
        soup = BeautifulSoup(html, "html.parser")

        # Stage bold is present, so stage-only pattern is detected
        assert _has_affliction_pattern(soup) is True

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


class TestExtractActivationTraitsFromParens:
    """Tests for _extract_activation_traits_from_parens shared helper."""

    def test_no_parentheses_returns_full_text(self):
        """Should return empty traits and full text when no parentheses."""
        traits, text_before, other_links, count = _extract_activation_traits_from_parens(
            "command", [{"name": "Fire", "game-obj": "Traits"}]
        )

        assert traits == []
        assert text_before == "command"
        assert len(other_links) == 1
        assert count == 0

    def test_extracts_linked_trait(self):
        """Should extract linked trait from parentheses."""
        traits, text_before, other_links, count = _extract_activation_traits_from_parens(
            "command (manipulate)", [{"name": "manipulate", "game-obj": "Traits"}]
        )

        assert len(traits) == 1
        assert traits[0]["name"] == "manipulate"
        assert text_before == "command"
        assert other_links == []
        assert count == 1

    def test_extracts_multiple_linked_traits(self):
        """Should extract multiple linked traits."""
        trait_links = [
            {"name": "manipulate", "game-obj": "Traits"},
            {"name": "divine", "game-obj": "Traits"},
        ]
        traits, text_before, other_links, count = _extract_activation_traits_from_parens(
            "command (manipulate, divine)", trait_links
        )

        assert len(traits) == 2
        assert text_before == "command"
        assert count == 2

    def test_unlinked_text_ignored_by_default(self):
        """Should not treat unlinked text as traits by default."""
        traits, text_before, other_links, count = _extract_activation_traits_from_parens(
            "command (magical)", []
        )

        assert traits == []
        assert text_before == "command"
        assert count == 0

    def test_unlinked_text_included_when_flag_set(self):
        """Should include unlinked text as traits when include_unlinked_traits=True."""
        traits, text_before, other_links, count = _extract_activation_traits_from_parens(
            "command (magical)", [], include_unlinked_traits=True
        )

        assert len(traits) == 1
        assert traits[0]["name"] == "magical"
        assert text_before == "command"
        assert count == 0  # No links converted, just unlinked text

    def test_non_matching_trait_link_goes_to_other(self):
        """Trait links not found in parens should go to other_links."""
        trait_links = [
            {"name": "manipulate", "game-obj": "Traits"},
            {"name": "fire", "game-obj": "Traits"},
        ]
        traits, text_before, other_links, count = _extract_activation_traits_from_parens(
            "command (manipulate)", trait_links
        )

        assert len(traits) == 1
        assert len(other_links) == 1
        assert other_links[0]["name"] == "fire"
        assert count == 1

    def test_case_insensitive_matching(self):
        """Should match trait names case-insensitively."""
        traits, text_before, other_links, count = _extract_activation_traits_from_parens(
            "command (Manipulate)", [{"name": "manipulate", "game-obj": "Traits"}]
        )

        assert len(traits) == 1
        assert count == 1

    def test_malformed_parens_returns_full_text(self):
        """Should handle malformed parentheses gracefully."""
        traits, text_before, other_links, count = _extract_activation_traits_from_parens(
            "command (oops", [{"name": "oops", "game-obj": "Traits"}]
        )

        # paren_end < paren_start, so should return full text
        assert traits == []
        assert text_before == "command (oops"
        assert count == 0

    def test_does_not_mutate_input_list(self):
        """Should not mutate the input trait_links list."""
        original = [{"name": "fire", "game-obj": "Traits"}]
        _extract_activation_traits_from_parens("command", original)

        assert len(original) == 1  # Not modified

    def test_semicolon_separated_traits(self):
        """Should handle semicolon-separated traits via split_comma_and_semicolon."""
        trait_links = [
            {"name": "manipulate", "game-obj": "Traits"},
            {"name": "divine", "game-obj": "Traits"},
        ]
        traits, text_before, other_links, count = _extract_activation_traits_from_parens(
            "command (manipulate; divine)", trait_links
        )

        assert len(traits) == 2
        assert text_before == "command"
        assert count == 2

    def test_mixed_comma_semicolon_traits(self):
        """Should handle mixed comma and semicolon separators."""
        trait_links = [
            {"name": "manipulate", "game-obj": "Traits"},
            {"name": "divine", "game-obj": "Traits"},
            {"name": "fire", "game-obj": "Traits"},
        ]
        traits, text_before, other_links, count = _extract_activation_traits_from_parens(
            "command (manipulate, divine; fire)", trait_links
        )

        assert len(traits) == 3
        assert text_before == "command"
        assert count == 3


class TestFindAbilityBolds:
    """Tests for _find_ability_bolds helper."""

    def test_finds_activate_bold(self):
        """Should find <b>Activate</b> tags."""
        html = "<b>Activate</b> command"
        soup = BeautifulSoup(html, "html.parser")

        result = _find_ability_bolds(soup)

        assert len(result) == 1
        assert result[0].get_text().strip() == "Activate"

    def test_finds_action_icon_bold(self):
        """Should find bold tags followed by action icon spans."""
        html = '<b>Divert Lightning</b> <span class="action">[reaction]</span>'
        soup = BeautifulSoup(html, "html.parser")

        result = _find_ability_bolds(soup)

        assert len(result) == 1
        assert result[0].get_text().strip() == "Divert Lightning"

    def test_skips_sub_field_bolds(self):
        """Should skip Frequency, Trigger, Effect, etc."""
        html = "<b>Frequency</b> once per day; <b>Trigger</b> you are hit"
        soup = BeautifulSoup(html, "html.parser")

        result = _find_ability_bolds(soup)

        assert len(result) == 0

    def test_skips_named_activation_bolds(self):
        """Should skip dash-prefixed named activation bolds."""
        html = "<b>\u2014Dim Sight</b> some text"
        soup = BeautifulSoup(html, "html.parser")

        result = _find_ability_bolds(soup)

        assert len(result) == 0

    def test_skips_regular_bolds_without_action(self):
        """Should skip bold tags not followed by action icon."""
        html = "<b>Unknown</b> some text"
        soup = BeautifulSoup(html, "html.parser")

        result = _find_ability_bolds(soup)

        assert len(result) == 0

    def test_finds_multiple_abilities(self):
        """Should find multiple ability bolds."""
        html = "<b>Activate</b> command; <b>Frequency</b> once per day; " "<b>Activate</b> Interact"
        soup = BeautifulSoup(html, "html.parser")

        result = _find_ability_bolds(soup)

        assert len(result) == 2

    def test_returns_empty_for_no_bolds(self):
        """Should return empty list when no bolds in soup."""
        soup = BeautifulSoup("just text", "html.parser")

        result = _find_ability_bolds(soup)

        assert result == []


class TestCollectEquipmentAbilityContent:
    """Tests for _collect_equipment_ability_content helper."""

    def test_collects_until_next_ability(self):
        """Should collect content until next ability bold."""
        html = "<b>Activate</b> command; <b>Effect</b> boom; <b>Activate</b> Interact"
        soup = BeautifulSoup(html, "html.parser")
        bolds = soup.find_all("b")
        first_activate = bolds[0]
        second_activate = bolds[2]  # "Activate" #2

        ability_html, elements = _collect_equipment_ability_content(
            first_activate, second_activate, [second_activate]
        )

        assert "command" in ability_html
        assert "Effect" in ability_html
        assert len(elements) >= 1

    def test_collects_until_end_when_no_next(self):
        """Should collect all remaining content when no next ability."""
        html = "<b>Activate</b> command; effect text"
        soup = BeautifulSoup(html, "html.parser")
        bold = soup.find("b")

        ability_html, elements = _collect_equipment_ability_content(bold, None, [])

        assert "command" in ability_html
        assert "effect text" in ability_html

    def test_stops_at_hr(self):
        """Should stop at <hr> tags."""
        html = "<b>Activate</b> command<hr>description after"
        soup = BeautifulSoup(html, "html.parser")
        bold = soup.find("b")

        ability_html, elements = _collect_equipment_ability_content(bold, None, [])

        assert "command" in ability_html
        assert "description after" not in ability_html

    def test_includes_bold_in_elements(self):
        """Should include the ability bold itself in elements list."""
        html = "<b>Activate</b> command"
        soup = BeautifulSoup(html, "html.parser")
        bold = soup.find("b")

        _, elements = _collect_equipment_ability_content(bold, None, [])

        assert bold in elements


class TestExtractActionTypeFromSpans:
    """Tests for _extract_action_type_from_spans helper."""

    def test_single_action(self):
        """Should extract single action type."""
        html = '<span class="action" title="One Action">[one-action]</span> text'
        soup = BeautifulSoup(html, "html.parser")

        result = _extract_action_type_from_spans(soup)

        assert result is not None
        assert result["name"] == "One Action"
        assert result["type"] == "stat_block_section"
        assert result["subtype"] == "action_type"

    def test_normalizes_single_action(self):
        """Should normalize 'Single Action' to 'One Action'."""
        html = '<span class="action" title="Single Action">[one-action]</span>'
        soup = BeautifulSoup(html, "html.parser")

        result = _extract_action_type_from_spans(soup)

        assert result["name"] == "One Action"

    def test_variable_action_cost(self):
        """Should handle variable action costs."""
        html = (
            '<span class="action" title="One Action">[one-action]</span> to '
            '<span class="action" title="Two Actions">[two-actions]</span>'
        )
        soup = BeautifulSoup(html, "html.parser")

        result = _extract_action_type_from_spans(soup)

        assert result["name"] == "One or Two Actions"

    def test_reaction(self):
        """Should handle reaction type."""
        html = '<span class="action" title="Reaction">[reaction]</span>'
        soup = BeautifulSoup(html, "html.parser")

        result = _extract_action_type_from_spans(soup)

        assert result["name"] == "Reaction"

    def test_no_spans_returns_none(self):
        """Should return None when no action spans present."""
        html = "just text without spans"
        soup = BeautifulSoup(html, "html.parser")

        result = _extract_action_type_from_spans(soup)

        assert result is None

    def test_deduplicates_action_titles(self):
        """Should deduplicate action titles from nested abilities."""
        html = (
            '<span class="action" title="One Action">[one-action]</span> '
            '<span class="action" title="One Action">[one-action]</span>'
        )
        soup = BeautifulSoup(html, "html.parser")

        result = _extract_action_type_from_spans(soup)

        assert result["name"] == "One Action"

    def test_decomposes_spans(self):
        """Should remove action spans from soup."""
        html = '<span class="action" title="One Action">[one-action]</span> text'
        soup = BeautifulSoup(html, "html.parser")

        _extract_action_type_from_spans(soup)

        assert soup.find("span", class_="action") is None


class TestDeduplicateLinksAcrossAbilities:
    """Tests for _deduplicate_links_across_abilities helper."""

    def test_removes_duplicate_from_earlier_ability(self):
        """Should remove links from earlier abilities that appear in later ones."""
        abilities = [
            {"links": [{"name": "Fireball", "game-obj": "Spells", "aonid": "1"}]},
            {"links": [{"name": "Fireball", "game-obj": "Spells", "aonid": "1"}]},
        ]

        _deduplicate_links_across_abilities(abilities)

        assert "links" not in abilities[0]
        assert len(abilities[1]["links"]) == 1

    def test_keeps_unique_links(self):
        """Should keep links that are unique to each ability."""
        abilities = [
            {"links": [{"name": "Fireball", "game-obj": "Spells", "aonid": "1"}]},
            {"links": [{"name": "Lightning Bolt", "game-obj": "Spells", "aonid": "2"}]},
        ]

        _deduplicate_links_across_abilities(abilities)

        assert len(abilities[0]["links"]) == 1
        assert len(abilities[1]["links"]) == 1

    def test_handles_single_ability(self):
        """Should do nothing for single ability."""
        abilities = [
            {"links": [{"name": "Fireball", "game-obj": "Spells", "aonid": "1"}]},
        ]

        _deduplicate_links_across_abilities(abilities)

        assert len(abilities[0]["links"]) == 1

    def test_handles_abilities_without_links(self):
        """Should handle abilities without links key."""
        abilities = [
            {"name": "Activate"},
            {"links": [{"name": "Fireball", "game-obj": "Spells", "aonid": "1"}]},
        ]

        _deduplicate_links_across_abilities(abilities)

        assert "links" not in abilities[0]
        assert len(abilities[1]["links"]) == 1

    def test_handles_empty_list(self):
        """Should handle empty abilities list."""
        abilities = []

        _deduplicate_links_across_abilities(abilities)

        assert abilities == []


class TestCleanActivationCruftFromText:
    """Tests for _clean_activation_cruft_from_text helper."""

    def test_removes_html_activate_pattern(self):
        """Should remove <b>Activate</b> pattern from text."""
        sb = {"text": "Item description.<br/><b>Activate</b> command; <b>Effect</b> boom"}

        _clean_activation_cruft_from_text(sb)

        assert "Activate" not in sb["text"]
        assert "Item description." in sb["text"]

    def test_removes_markdown_activate_pattern(self):
        """Should remove **Activate** pattern from text."""
        sb = {"text": "Item description. **Activate** command"}

        _clean_activation_cruft_from_text(sb)

        assert "Activate" not in sb["text"]
        assert "Item description." in sb["text"]

    def test_deletes_text_key_if_empty_after_cleanup(self):
        """Should delete text key if nothing remains after cleanup."""
        sb = {"text": "<b>Activate</b> command; <b>Effect</b> boom"}

        _clean_activation_cruft_from_text(sb)

        assert "text" not in sb

    def test_no_op_when_no_text_key(self):
        """Should do nothing when no text key exists."""
        sb = {"name": "Item"}

        _clean_activation_cruft_from_text(sb)

        assert "text" not in sb

    def test_no_op_when_text_empty(self):
        """Should do nothing when text is empty."""
        sb = {"text": ""}

        _clean_activation_cruft_from_text(sb)

    def test_preserves_text_without_activate(self):
        """Should preserve text that doesn't contain activation patterns."""
        sb = {"text": "This is a normal item description."}

        _clean_activation_cruft_from_text(sb)

        assert sb["text"] == "This is a normal item description."


class TestProcessActivateContent:
    """Tests for _process_activate_content helper."""

    def test_extracts_activation_type(self):
        """Should extract activation type from Activate content."""
        html = '<b>Activate</b> <a game-obj="Traits" href="">command</a>'
        soup = BeautifulSoup(html, "html.parser")
        ability = {}

        _process_activate_content(soup, ability)

        assert ability["subtype"] == "activation"
        assert "activation_types" in ability

    def test_sets_subtype_activation(self):
        """Should set subtype to 'activation'."""
        html = "<b>Activate</b> Interact"
        soup = BeautifulSoup(html, "html.parser")
        ability = {}

        _process_activate_content(soup, ability)

        assert ability["subtype"] == "activation"

    def test_no_activate_bold_returns_zero(self):
        """Should return 0 if no Activate bold found."""
        html = "<b>Other</b> something"
        soup = BeautifulSoup(html, "html.parser")
        ability = {}

        result = _process_activate_content(soup, ability)

        assert result == 0
        assert "subtype" not in ability

    def test_extracts_named_activation(self):
        """Should extract named activation (em-dash prefixed bold)."""
        html = "<b>Activate</b> <b>\u2014Dim Sight</b> command"
        soup = BeautifulSoup(html, "html.parser")
        ability = {}

        _process_activate_content(soup, ability)

        assert ability.get("activation_name") == "Dim Sight"
        assert ability["subtype"] == "activation"

    def test_strips_leading_semicolons(self):
        """Should strip leading semicolons from activation content."""
        html = "<b>Activate</b> ; command"
        soup = BeautifulSoup(html, "html.parser")
        ability = {}

        _process_activate_content(soup, ability)

        assert ability["subtype"] == "activation"

    def test_returns_trait_links_converted_count(self):
        """Should return count of trait links converted."""
        html = '<b>Activate</b> command (<a game-obj="Traits" href="">manipulate</a>)'
        soup = BeautifulSoup(html, "html.parser")
        ability = {}

        result = _process_activate_content(soup, ability)

        assert result >= 1


class TestParseActivationContentTimeBugFix:
    """Regression tests for the 'time as activation_type' bug fix.

    Previously, text like '1 minute' without parentheses was treated as
    activation_type instead of activation_time. The fix applies the time
    detection regex unconditionally, not just inside the parentheses branch.
    This affected items like Ring of Stoneshifting.
    """

    def test_bare_time_value_becomes_activation_time(self):
        """'1 minute' should become activation_time, not activation_type."""
        ability = {}
        _parse_activation_content("1 minute", ability)

        assert ability.get("activation_time") == "1 minute"
        assert "activation_types" not in ability

    def test_bare_time_with_hours(self):
        """'10 hours' should become activation_time."""
        ability = {}
        _parse_activation_content("10 hours", ability)

        assert ability.get("activation_time") == "10 hours"
        assert "activation_types" not in ability

    def test_bare_time_with_rounds(self):
        """'3 rounds' should become activation_time."""
        ability = {}
        _parse_activation_content("3 rounds", ability)

        assert ability.get("activation_time") == "3 rounds"
        assert "activation_types" not in ability

    def test_command_is_not_time(self):
        """'command' should remain an activation_type, not time."""
        ability = {}
        _parse_activation_content("command", ability)

        assert "activation_types" in ability
        assert "activation_time" not in ability

    def test_time_after_semicolon_still_works(self):
        """'command; 1 minute' should have both activation_type and time."""
        ability = {}
        _parse_activation_content("command; 1 minute", ability)

        assert "activation_types" in ability
        assert ability.get("activation_time") == "1 minute"


class TestNormalizeActivateToAbility:
    """Tests for _normalize_activate_to_ability."""

    def test_basic_activate_with_action(self):
        """Should convert basic activate HTML to ability with action type."""
        statistics = {
            "activate": '<span class="action" title="Single Action">[one-action]</span> Interact'
        }
        sb = {}

        _normalize_activate_to_ability(statistics, sb)

        assert "activate" not in statistics
        assert "abilities" in statistics
        ability = statistics["abilities"][0]
        assert ability["subtype"] == "activation"
        assert ability["action_type"]["name"] == "One Action"
        assert ability["activation_types"][0]["value"] == "interact"

    def test_no_activate_field_returns_zero(self):
        """Should return 0 when no activate field present."""
        statistics = {}
        sb = {}

        result = _normalize_activate_to_ability(statistics, sb)

        assert result == 0
        assert "abilities" not in statistics

    def test_activate_with_traits(self):
        """Should extract traits from parenthesized content."""
        statistics = {
            "activate": (
                '<span class="action" title="Single Action">[one-action]</span> '
                'command (<a game-obj="Traits" href="">manipulate</a>, '
                '<a game-obj="Traits" href="">divine</a>)'
            )
        }
        sb = {}

        result = _normalize_activate_to_ability(statistics, sb)

        ability = statistics["abilities"][0]
        assert "traits" in ability
        assert len(ability["traits"]) == 2
        assert result == 2  # Two trait links converted

    def test_activate_with_unlinked_traits(self):
        """Should include unlinked traits (legacy activate uses include_unlinked_traits=True)."""
        statistics = {
            "activate": (
                '<span class="action" title="Single Action">[one-action]</span> '
                "command (magical)"
            )
        }
        sb = {}

        _normalize_activate_to_ability(statistics, sb)

        ability = statistics["abilities"][0]
        assert "traits" in ability
        assert len(ability["traits"]) == 1
        assert ability["traits"][0]["name"] == "magical"

    def test_empty_activate_returns_zero(self):
        """Should return 0 for empty activate field."""
        statistics = {"activate": ""}
        sb = {}

        result = _normalize_activate_to_ability(statistics, sb)

        assert result == 0


class TestExtractActionTypeFromSpansEdgeCases:
    """Additional edge case tests for _extract_action_type_from_spans."""

    def test_two_or_three_actions(self):
        """Should map Two Actions + Three Actions to 'Two or Three Actions'."""
        html = '<span class="action" title="Two Actions"></span><span class="action" title="Three Actions"></span>'
        soup = BeautifulSoup(html, "html.parser")

        result = _extract_action_type_from_spans(soup)

        assert result["name"] == "Two or Three Actions"

    def test_one_to_three_actions(self):
        """Should map One + Two + Three Actions to 'One to Three Actions'."""
        html = (
            '<span class="action" title="Single Action"></span>'
            '<span class="action" title="Two Actions"></span>'
            '<span class="action" title="Three Actions"></span>'
        )
        soup = BeautifulSoup(html, "html.parser")

        result = _extract_action_type_from_spans(soup)

        assert result["name"] == "One to Three Actions"

    def test_free_action_or_single_action(self):
        """Should map Free Action + Single Action to 'Free Action or Single Action'."""
        html = '<span class="action" title="Free Action"></span><span class="action" title="Single Action"></span>'
        soup = BeautifulSoup(html, "html.parser")

        result = _extract_action_type_from_spans(soup)

        assert result["name"] == "Free Action or Single Action"

    def test_reaction_or_one_action(self):
        """Should map Reaction + Single Action to 'Reaction or One Action'."""
        html = '<span class="action" title="Reaction"></span><span class="action" title="Single Action"></span>'
        soup = BeautifulSoup(html, "html.parser")

        result = _extract_action_type_from_spans(soup)

        assert result["name"] == "Reaction or One Action"

    def test_one_or_three_actions(self):
        """Should map One Action + Three Actions to 'One or Three Actions'."""
        html = '<span class="action" title="Single Action"></span><span class="action" title="Three Actions"></span>'
        soup = BeautifulSoup(html, "html.parser")

        result = _extract_action_type_from_spans(soup)

        assert result["name"] == "One or Three Actions"

    def test_unmapped_combination_uses_or_join(self):
        """Should fall back to 'or' join for unmapped combinations."""
        html = '<span class="action" title="Free Action"></span><span class="action" title="Three Actions"></span>'
        soup = BeautifulSoup(html, "html.parser")

        result = _extract_action_type_from_spans(soup)

        assert result["name"] == "Free Action or Three Actions"


class TestFindAbilityBoldsEdgeCases:
    """Additional edge case tests for _find_ability_bolds."""

    def test_skips_en_dash_prefixed_bold(self):
        """Should skip bolds prefixed with en-dash (\\u2013)."""
        html = "<b>Activate</b> command <b>\u2013Special Power</b> text"
        soup = BeautifulSoup(html, "html.parser")

        result = _find_ability_bolds(soup)

        assert len(result) == 1
        assert result[0].get_text().strip() == "Activate"

    def test_skips_hyphen_prefixed_bold(self):
        """Should skip bolds prefixed with regular hyphen."""
        html = "<b>Activate</b> command <b>-Quick Strike</b> text"
        soup = BeautifulSoup(html, "html.parser")

        result = _find_ability_bolds(soup)

        assert len(result) == 1
        assert result[0].get_text().strip() == "Activate"

    def test_skips_all_sub_field_names(self):
        """Should skip all 9 sub-field bolds."""
        sub_fields = [
            "Frequency",
            "Trigger",
            "Effect",
            "Requirements",
            "Critical Success",
            "Success",
            "Failure",
            "Critical Failure",
            "Destruction",
        ]
        html = "<b>Activate</b> command"
        for sf in sub_fields:
            html += f" <b>{sf}</b> text"
        soup = BeautifulSoup(html, "html.parser")

        result = _find_ability_bolds(soup)

        assert len(result) == 1
        assert result[0].get_text().strip() == "Activate"


class TestExtractActivationTraitsDigitFiltering:
    """Test that digit-only strings are filtered from unlinked traits."""

    def test_digit_only_text_excluded_from_unlinked_traits(self):
        """Digit-only text in parens should not become a trait."""
        traits, text_before, other_links, count = _extract_activation_traits_from_parens(
            "command (2, magical)", [], include_unlinked_traits=True
        )

        trait_names = [t["name"] for t in traits]
        assert "magical" in trait_names
        assert "2" not in trait_names

    def test_digit_only_text_ignored_by_default(self):
        """Without include_unlinked_traits, digit text is irrelevant (no traits at all)."""
        traits, text_before, other_links, count = _extract_activation_traits_from_parens(
            "command (2, magical)", []
        )

        assert traits == []


class TestDefaultFieldDestinations:
    """Tests for DEFAULT_FIELD_DESTINATIONS consolidation."""

    TYPES_USING_DEFAULTS = ["armor", "shield", "equipment"]

    def test_base_fields_present_in_all_types(self):
        """Every base field from DEFAULT_FIELD_DESTINATIONS should appear in all 3 types."""
        for eq_type in self.TYPES_USING_DEFAULTS:
            fd = EQUIPMENT_TYPES[eq_type]["field_destinations"]
            for field, dest in DEFAULT_FIELD_DESTINATIONS.items():
                assert field in fd, f"'{field}' missing from {eq_type} field_destinations"
                assert (
                    fd[field] == dest
                ), f"'{field}' in {eq_type} is {fd[field]!r}, expected {dest!r}"

    def test_armor_has_defense_fields(self):
        """Armor should have its defense-routed fields."""
        fd = EQUIPMENT_TYPES["armor"]["field_destinations"]
        for field in ("ac_bonus", "dex_cap", "check_penalty", "speed_penalty", "armor_group"):
            assert fd[field] == "defense", f"armor '{field}' should route to defense"

    def test_armor_has_statistics_fields(self):
        """Armor should have category and strength in statistics."""
        fd = EQUIPMENT_TYPES["armor"]["field_destinations"]
        assert fd["category"] == "statistics"
        assert fd["strength"] == "statistics"

    def test_shield_has_defense_fields(self):
        """Shield should have its defense-routed fields."""
        fd = EQUIPMENT_TYPES["shield"]["field_destinations"]
        for field in ("ac_bonus", "speed_penalty", "hardness", "hp_bt"):
            assert fd[field] == "defense", f"shield '{field}' should route to defense"

    def test_shield_lacks_armor_specific_fields(self):
        """Shield should not have armor-specific fields like category or strength."""
        fd = EQUIPMENT_TYPES["shield"]["field_destinations"]
        assert "category" not in fd
        assert "strength" not in fd

    def test_equipment_has_statistics_fields(self):
        """Equipment should have its statistics-routed fields."""
        fd = EQUIPMENT_TYPES["equipment"]["field_destinations"]
        for field in (
            "hands",
            "usage",
            "activate",
            "perception",
            "communication",
            "languages",
            "skills",
            "int",
            "wis",
            "cha",
            "will",
        ):
            assert fd[field] == "statistics", f"equipment '{field}' should route to statistics"

    def test_equipment_has_offense_fields(self):
        """Equipment should have ammunition and base_weapon in offense."""
        fd = EQUIPMENT_TYPES["equipment"]["field_destinations"]
        assert fd["ammunition"] == "offense"
        assert fd["base_weapon"] == "offense"

    def test_equipment_has_defense_fields(self):
        """Equipment should have base_armor and base_shield in defense."""
        fd = EQUIPMENT_TYPES["equipment"]["field_destinations"]
        assert fd["base_armor"] == "defense"
        assert fd["base_shield"] == "defense"

    def test_legacy_types_not_affected(self):
        """Weapon, siege_weapon, vehicle should not have field_destinations."""
        for eq_type in ("weapon", "siege_weapon", "vehicle"):
            assert (
                "field_destinations" not in EQUIPMENT_TYPES[eq_type]
            ), f"{eq_type} should use shared_fields/nested_fields, not field_destinations"


class TestCountLinksInHtml:
    """Tests for _count_links_in_html - counts all <a> tags with exclusions."""

    def test_counts_game_obj_links(self):
        """Should count links with game-obj attribute."""
        html = '<a href="Spells.aspx?ID=1" game-obj="Spells">fireball</a>'
        assert _count_links_in_html(html) == 1

    def test_counts_non_game_obj_links(self):
        """Should count links WITHOUT game-obj attribute (new behavior)."""
        html = '<a href="Rules.aspx?ID=123">some rule</a>'
        assert _count_links_in_html(html) == 1

    def test_excludes_pfs_links(self):
        """Should exclude PFS icon links from count."""
        html = (
            '<a href="PFS.aspx?ID=1">PFS Standard</a>'
            '<a href="Spells.aspx?ID=1" game-obj="Spells">fireball</a>'
        )
        assert _count_links_in_html(html) == 1

    def test_excludes_self_references(self):
        """Should exclude self-reference links matching name and game-obj."""
        html = '<a href="Equipment.aspx?ID=1" game-obj="Equipment">My Item</a>'
        assert _count_links_in_html(html, exclude_name="My Item", exclude_game_obj="Equipment") == 0

    def test_excludes_trait_links_in_trait_spans(self):
        """Should exclude trait links inside <span class='trait*'> tags."""
        html = '<span class="trait"><a href="Traits.aspx?ID=1" game-obj="Traits">magical</a></span>'
        assert _count_links_in_html(html) == 0

    def test_keeps_trait_links_outside_trait_spans(self):
        """Should keep trait links that are NOT inside <span class='trait*'> tags."""
        html = '<a href="Traits.aspx?ID=1" game-obj="Traits">magical</a>'
        assert _count_links_in_html(html) == 1

    def test_excludes_version_links(self):
        """Should exclude 'more recent version' navigation links."""
        html = '<a href="Equipment.aspx?ID=2">There is a more recent version of this item.</a>'
        assert _count_links_in_html(html) == 0

    def test_excludes_group_links(self):
        """Should exclude weapon/armor group links in stat line context."""
        html = '<b>Group</b> <u><a href="Groups.aspx?ID=1" game-obj="WeaponGroups">Sword</a></u>'
        assert _count_links_in_html(html) == 0

    def test_mixed_links_counted_correctly(self):
        """Should count a mix of game-obj and non-game-obj links, excluding PFS."""
        html = (
            '<a href="Spells.aspx?ID=1" game-obj="Spells">fireball</a>'
            '<a href="Rules.aspx?ID=5">rule page</a>'
            '<a href="PFS.aspx?ID=1">PFS</a>'
        )
        assert _count_links_in_html(html) == 2


class TestShouldExcludeLink:
    """Tests for _should_exclude_link helper."""

    def test_excludes_pfs_link(self):
        """Should exclude PFS icon links."""
        html = '<a href="PFS.aspx?ID=1">PFS Standard</a>'
        link = BeautifulSoup(html, "html.parser").find("a")
        assert _should_exclude_link(link) is True

    def test_does_not_exclude_regular_link(self):
        """Should not exclude regular game links."""
        html = '<a href="Spells.aspx?ID=1" game-obj="Spells">fireball</a>'
        link = BeautifulSoup(html, "html.parser").find("a")
        assert _should_exclude_link(link) is False

    def test_excludes_trait_link_in_trait_span(self):
        """Should exclude trait links inside trait spans."""
        html = '<span class="trait"><a href="Traits.aspx?ID=1" game-obj="Traits">magical</a></span>'
        link = BeautifulSoup(html, "html.parser").find("a")
        assert _should_exclude_link(link) is True

    def test_does_not_exclude_trait_link_outside_span(self):
        """Should not exclude trait links outside of trait spans."""
        html = '<a href="Traits.aspx?ID=1" game-obj="Traits">magical</a>'
        link = BeautifulSoup(html, "html.parser").find("a")
        assert _should_exclude_link(link) is False

    def test_does_not_exclude_non_game_obj_link(self):
        """Should not exclude links without game-obj (they're now tracked)."""
        html = '<a href="Rules.aspx?ID=123">some rule</a>'
        link = BeautifulSoup(html, "html.parser").find("a")
        assert _should_exclude_link(link) is False


class TestHasAfflictionPatternStageOnly:
    """Tests for stage-only affliction detection (no Saving Throw)."""

    def test_detects_stage_only_pattern(self):
        """Should detect Stage-only patterns without Saving Throw."""
        html = "<b>Stage 1</b> effect (1 hour); <b>Stage 2</b> effect (1 hour)"
        soup = BeautifulSoup(html, "html.parser")
        assert _has_affliction_pattern(soup) is True

    def test_single_stage_without_saving_throw(self):
        """Should detect single Stage without Saving Throw."""
        html = "<b>Stage 1</b> stupefied 1 (1 round)"
        soup = BeautifulSoup(html, "html.parser")
        assert _has_affliction_pattern(soup) is True

    def test_stage_only_with_multiple_stages(self):
        """Should detect multiple stages without Saving Throw."""
        html = (
            "<b>Stage 1</b> 1d6 poison damage (1 round); "
            "<b>Stage 2</b> 2d6 poison damage (1 round); "
            "<b>Stage 3</b> 3d6 poison damage (1 round)"
        )
        soup = BeautifulSoup(html, "html.parser")
        assert _has_affliction_pattern(soup) is True


class TestExtractActionTypeFromSpansSemicolon:
    """Tests for action span semicolon filtering."""

    def test_ignores_span_after_semicolon(self):
        """Action spans after first semicolon should be ignored (they're in description text)."""
        html = 'some text; <span class="action" title="One Action">[one-action]</span> more text'
        soup = BeautifulSoup(html, "html.parser")

        result = _extract_action_type_from_spans(soup)

        assert result is None

    def test_extracts_span_before_semicolon(self):
        """Action spans before first semicolon should be extracted normally."""
        html = '<span class="action" title="One Action">[one-action]</span> command; effect text'
        soup = BeautifulSoup(html, "html.parser")

        result = _extract_action_type_from_spans(soup)

        assert result is not None
        assert result["name"] == "One Action"

    def test_extracts_span_when_no_semicolon(self):
        """Action spans should be extracted when there's no semicolon at all."""
        html = '<span class="action" title="Reaction">[reaction]</span> text'
        soup = BeautifulSoup(html, "html.parser")

        result = _extract_action_type_from_spans(soup)

        assert result is not None
        assert result["name"] == "Reaction"


class TestDeduplicateLinksReturnValue:
    """Tests for _deduplicate_links_across_abilities return value."""

    def test_returns_removed_count(self):
        """Should return the count of removed duplicate links."""
        abilities = [
            {"links": [{"name": "Fireball", "game-obj": "Spells", "aonid": "1"}]},
            {"links": [{"name": "Fireball", "game-obj": "Spells", "aonid": "1"}]},
        ]

        removed = _deduplicate_links_across_abilities(abilities)

        assert removed == 1

    def test_returns_zero_when_no_duplicates(self):
        """Should return 0 when no duplicates found."""
        abilities = [
            {"links": [{"name": "Fireball", "game-obj": "Spells", "aonid": "1"}]},
            {"links": [{"name": "Lightning", "game-obj": "Spells", "aonid": "2"}]},
        ]

        removed = _deduplicate_links_across_abilities(abilities)

        assert removed == 0

    def test_returns_zero_for_empty_list(self):
        """Should return 0 for empty abilities list."""
        removed = _deduplicate_links_across_abilities([])

        assert removed == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
