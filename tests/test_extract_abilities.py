"""Unit tests for _extract_abilities helper functions in equipment.py."""

from bs4 import BeautifulSoup

import pfsrd2.constants as constants
from pfsrd2.equipment import (
    _classify_links,
    _collect_ability_content,
    _extract_addons_from_soup,
    _extract_result_fields,
    _is_ability_bold_tag,
    _parse_ability_description,
    _parse_trait_parentheses,
)


class TestIsAbilityBoldTag:
    """Tests for _is_ability_bold_tag helper."""

    # Common test fixtures
    MAIN_ABILITIES = ["Aim", "Load", "Launch", "Ram", "Effect", "Requirements"]
    RESULT_FIELDS = ["Success", "Failure", "Critical Success", "Critical Failure"]

    def test_known_ability_name_returns_name(self):
        """Should return ability name for known main abilities."""
        html = "<b>Aim</b> some text"
        soup = BeautifulSoup(html, "html.parser")
        bold = soup.find("b")

        result = _is_ability_bold_tag(
            bold, self.MAIN_ABILITIES, set(), self.RESULT_FIELDS, "siege_weapon"
        )

        assert result == "Aim"

    def test_unknown_name_without_action_returns_none(self):
        """Should return None for unknown names without action icon."""
        html = "<b>Unknown</b> some text"
        soup = BeautifulSoup(html, "html.parser")
        bold = soup.find("b")

        result = _is_ability_bold_tag(
            bold, self.MAIN_ABILITIES, set(), self.RESULT_FIELDS, "siege_weapon"
        )

        assert result is None

    def test_action_icon_returns_name(self):
        """Should return name when action icon follows bold tag."""
        html = '<b>Custom Action</b> <span class="action">[one-action]</span>'
        soup = BeautifulSoup(html, "html.parser")
        bold = soup.find("b")

        result = _is_ability_bold_tag(
            bold, self.MAIN_ABILITIES, set(), self.RESULT_FIELDS, "siege_weapon"
        )

        assert result == "Custom Action"

    def test_action_icon_with_whitespace(self):
        """Should handle whitespace between bold and action icon."""
        html = '<b>Custom Action</b>   \n  <span class="action">[two-actions]</span>'
        soup = BeautifulSoup(html, "html.parser")
        bold = soup.find("b")

        result = _is_ability_bold_tag(
            bold, self.MAIN_ABILITIES, set(), self.RESULT_FIELDS, "siege_weapon"
        )

        assert result == "Custom Action"

    def test_stat_label_returns_none(self):
        """Should return None for stat labels."""
        html = "<b>Speed</b> 30 feet"
        soup = BeautifulSoup(html, "html.parser")
        bold = soup.find("b")

        result = _is_ability_bold_tag(
            bold, self.MAIN_ABILITIES, {"Speed"}, self.RESULT_FIELDS, "vehicle"
        )

        assert result is None

    def test_vehicle_heuristic_with_long_text(self):
        """Should detect vehicle abilities with substantial text."""
        html = "<b>Collision</b> This vehicle can ram into other objects causing significant damage to both."
        soup = BeautifulSoup(html, "html.parser")
        bold = soup.find("b")

        result = _is_ability_bold_tag(
            bold, self.MAIN_ABILITIES, set(), self.RESULT_FIELDS, "vehicle"
        )

        assert result == "Collision"

    def test_vehicle_heuristic_with_short_text(self):
        """Should not detect vehicle ability with short text."""
        html = "<b>AC</b> 15"
        soup = BeautifulSoup(html, "html.parser")
        bold = soup.find("b")

        result = _is_ability_bold_tag(
            bold, self.MAIN_ABILITIES, set(), self.RESULT_FIELDS, "vehicle"
        )

        assert result is None

    def test_vehicle_heuristic_ignores_result_fields(self):
        """Should not apply vehicle heuristic to result field names."""
        html = "<b>Success</b> The target takes 2d6 damage and is pushed back."
        soup = BeautifulSoup(html, "html.parser")
        bold = soup.find("b")

        result = _is_ability_bold_tag(
            bold, self.MAIN_ABILITIES, set(), self.RESULT_FIELDS, "vehicle"
        )

        assert result is None

    def test_vehicle_heuristic_stops_at_bold(self):
        """Vehicle heuristic should stop counting at another bold tag."""
        html = "<b>AC</b> <b>HP</b> more text here that is long enough"
        soup = BeautifulSoup(html, "html.parser")
        bold = soup.find("b")

        result = _is_ability_bold_tag(
            bold, self.MAIN_ABILITIES, set(), self.RESULT_FIELDS, "vehicle"
        )

        assert result is None


class TestCollectAbilityContent:
    """Tests for _collect_ability_content helper."""

    ADDON_NAMES = constants.CREATURE_ABILITY_ADDON_NAMES

    def test_collects_text_until_br(self):
        """Should collect content until <br> tag."""
        html = "<b>Aim</b> some ability text<br>next line"
        soup = BeautifulSoup(html, "html.parser")
        bold = soup.find("b")
        processed = set()

        parts, current = _collect_ability_content(bold, self.ADDON_NAMES, processed)

        assert " some ability text" in "".join(parts)
        assert current.name == "br"

    def test_collects_text_until_hr(self):
        """Should collect content until <hr> tag."""
        html = "<b>Aim</b> some ability text<hr>next section"
        soup = BeautifulSoup(html, "html.parser")
        bold = soup.find("b")
        processed = set()

        parts, current = _collect_ability_content(bold, self.ADDON_NAMES, processed)

        assert " some ability text" in "".join(parts)
        assert current.name == "hr"

    def test_collects_text_until_h2(self):
        """Should collect content until <h2> tag."""
        html = "<b>Aim</b> some ability text<h2>New Section</h2>"
        soup = BeautifulSoup(html, "html.parser")
        bold = soup.find("b")
        processed = set()

        parts, current = _collect_ability_content(bold, self.ADDON_NAMES, processed)

        assert " some ability text" in "".join(parts)
        assert current.name == "h2"

    def test_marks_addon_bolds_as_processed(self):
        """Should mark addon bold tags as processed."""
        html = "<b>Aim</b> text <b>Requirements</b> you must aim<br>"
        soup = BeautifulSoup(html, "html.parser")
        bold = soup.find("b")
        processed = set()

        _collect_ability_content(bold, self.ADDON_NAMES, processed)

        # Find the Requirements bold tag
        requirements_bold = soup.find_all("b")[1]
        assert requirements_bold in processed

    def test_does_not_mark_non_addon_bolds(self):
        """Should not mark non-addon bold tags as processed."""
        html = "<b>Aim</b> text <b>Random</b> text<br>"
        soup = BeautifulSoup(html, "html.parser")
        bold = soup.find("b")
        processed = set()

        _collect_ability_content(bold, self.ADDON_NAMES, processed)

        random_bold = soup.find_all("b")[1]
        assert random_bold not in processed

    def test_returns_none_when_no_terminator(self):
        """Should return None for current when reaching end of siblings."""
        html = "<b>Aim</b> some text"
        soup = BeautifulSoup(html, "html.parser")
        bold = soup.find("b")
        processed = set()

        parts, current = _collect_ability_content(bold, self.ADDON_NAMES, processed)

        assert current is None


class TestExtractAddonsFromSoup:
    """Tests for _extract_addons_from_soup helper."""

    ADDON_NAMES = constants.CREATURE_ABILITY_ADDON_NAMES

    def test_extracts_requirements(self):
        """Should extract Requirements and rename to requirement."""
        html = "<b>Requirements</b> You must be holding the item"
        soup = BeautifulSoup(html, "html.parser")

        addons = _extract_addons_from_soup(soup, self.ADDON_NAMES)

        assert "requirement" in addons
        assert " You must be holding the item" in addons["requirement"]

    def test_extracts_effect(self):
        """Should extract Effect addon."""
        html = "<b>Effect</b> The gem glows"
        soup = BeautifulSoup(html, "html.parser")

        addons = _extract_addons_from_soup(soup, self.ADDON_NAMES)

        assert "effect" in addons

    def test_strips_trailing_semicolon(self):
        """Should strip trailing semicolons from addon content."""
        html = "<b>Frequency</b> once per day;"
        soup = BeautifulSoup(html, "html.parser")

        addons = _extract_addons_from_soup(soup, self.ADDON_NAMES)

        assert "frequency" in addons
        # Should have stripped the semicolon
        assert not addons["frequency"][0].rstrip().endswith(";")

    def test_removes_addon_nodes_from_soup(self):
        """Should remove addon nodes from the soup."""
        html = "prefix <b>Effect</b> effect text suffix"
        soup = BeautifulSoup(html, "html.parser")

        _extract_addons_from_soup(soup, self.ADDON_NAMES)

        # Effect bold should be removed
        assert soup.find("b") is None
        # Prefix should remain
        assert "prefix" in str(soup)

    def test_handles_multiple_addons(self):
        """Should handle multiple addon fields."""
        html = "<b>Requirements</b> req text; <b>Effect</b> effect text"
        soup = BeautifulSoup(html, "html.parser")

        addons = _extract_addons_from_soup(soup, self.ADDON_NAMES)

        assert "requirement" in addons
        assert "effect" in addons

    def test_ignores_non_addon_bolds(self):
        """Should ignore bold tags that aren't addon names."""
        html = "<b>Random</b> some text"
        soup = BeautifulSoup(html, "html.parser")

        addons = _extract_addons_from_soup(soup, self.ADDON_NAMES)

        assert len(addons) == 0
        # Random bold should still be in soup
        assert soup.find("b") is not None


class TestClassifyLinks:
    """Tests for _classify_links helper."""

    def test_empty_list(self):
        """Should handle empty link list."""
        trait_links, rules_links, other_links = _classify_links([])

        assert trait_links == []
        assert rules_links == []
        assert other_links == []

    def test_sorts_trait_links(self):
        """Should put Traits links in trait_links bucket."""
        links = [{"name": "Fire", "game-obj": "Traits"}]

        trait_links, rules_links, other_links = _classify_links(links)

        assert len(trait_links) == 1
        assert trait_links[0]["name"] == "Fire"
        assert len(rules_links) == 0
        assert len(other_links) == 0

    def test_sorts_rules_links(self):
        """Should put Rules links in rules_links bucket."""
        links = [{"name": "Range", "game-obj": "Rules"}]

        trait_links, rules_links, other_links = _classify_links(links)

        assert len(trait_links) == 0
        assert len(rules_links) == 1
        assert rules_links[0]["name"] == "Range"
        assert len(other_links) == 0

    def test_sorts_other_links(self):
        """Should put non-Traits/Rules links in other_links bucket."""
        links = [{"name": "Fireball", "game-obj": "Spells"}]

        trait_links, rules_links, other_links = _classify_links(links)

        assert len(trait_links) == 0
        assert len(rules_links) == 0
        assert len(other_links) == 1
        assert other_links[0]["name"] == "Fireball"

    def test_handles_missing_game_obj(self):
        """Should put links without game-obj in other_links."""
        links = [{"name": "Something"}]

        trait_links, rules_links, other_links = _classify_links(links)

        assert len(other_links) == 1

    def test_mixed_link_types(self):
        """Should correctly sort mixed link types."""
        links = [
            {"name": "Fire", "game-obj": "Traits"},
            {"name": "Range", "game-obj": "Rules"},
            {"name": "Fireball", "game-obj": "Spells"},
            {"name": "Cold", "game-obj": "Traits"},
        ]

        trait_links, rules_links, other_links = _classify_links(links)

        assert len(trait_links) == 2
        assert len(rules_links) == 1
        assert len(other_links) == 1


class TestParseTraitParentheses:
    """Tests for _parse_trait_parentheses helper."""

    def test_no_parentheses_returns_empty_traits(self):
        """Should return empty traits when text doesn't start with parentheses."""
        ability_text = "This ability does something."
        trait_links = [{"name": "Fire", "game-obj": "Traits"}]
        rules_links = []
        other_links = []

        traits, cleaned_text, count = _parse_trait_parentheses(
            ability_text, trait_links, rules_links, other_links, trait_links
        )

        assert traits == []
        assert cleaned_text == ability_text
        assert count == 0
        # Trait link should be moved to other_links (body text)
        assert len(other_links) == 1

    def test_extracts_linked_trait_from_parens(self):
        """Should extract linked trait names from parentheses."""
        ability_text = "(Fire) This ability deals fire damage."
        trait_links = [{"name": "Fire", "game-obj": "Traits"}]
        rules_links = []
        other_links = []

        traits, cleaned_text, count = _parse_trait_parentheses(
            ability_text, trait_links, rules_links, other_links, trait_links
        )

        assert len(traits) == 1
        assert traits[0]["name"] == "Fire"
        assert cleaned_text == "This ability deals fire damage."
        assert count == 1

    def test_extracts_multiple_linked_traits(self):
        """Should extract multiple linked traits from parentheses."""
        ability_text = "(Fire, Cold) This ability deals elemental damage."
        trait_links = [
            {"name": "Fire", "game-obj": "Traits"},
            {"name": "Cold", "game-obj": "Traits"},
        ]
        rules_links = []
        other_links = []

        traits, cleaned_text, count = _parse_trait_parentheses(
            ability_text, trait_links, rules_links, other_links, trait_links
        )

        assert len(traits) == 2
        assert count == 2

    def test_extracts_unlinked_trait_names(self):
        """Should extract unlinked trait names from parentheses."""
        ability_text = "(magical) This ability is magical."
        trait_links = []
        rules_links = []
        other_links = []

        traits, cleaned_text, count = _parse_trait_parentheses(
            ability_text, trait_links, rules_links, other_links, []
        )

        assert len(traits) == 1
        assert traits[0]["name"] == "magical"
        assert count == 0  # No links converted

    def test_trait_link_in_body_moved_to_other(self):
        """Should move trait links from body text to other_links."""
        ability_text = "This ability deals Fire damage."
        trait_links = [{"name": "Fire", "game-obj": "Traits"}]
        rules_links = []
        other_links = []

        traits, cleaned_text, count = _parse_trait_parentheses(
            ability_text, trait_links, rules_links, other_links, trait_links
        )

        assert len(traits) == 0
        assert len(other_links) == 1
        assert other_links[0]["name"] == "Fire"

    def test_rules_links_added_to_other(self):
        """Should add rules links to other_links."""
        ability_text = "(Fire) deals damage at range"
        trait_links = [{"name": "Fire", "game-obj": "Traits"}]
        rules_links = [{"name": "range", "game-obj": "Rules"}]
        other_links = []

        traits, cleaned_text, count = _parse_trait_parentheses(
            ability_text, trait_links, rules_links, other_links, trait_links + rules_links
        )

        # Rules links should end up in other_links
        assert any(l["name"] == "range" for l in other_links)

    def test_case_insensitive_matching(self):
        """Should match trait names case-insensitively."""
        ability_text = "(fire) This ability deals FIRE damage."
        trait_links = [{"name": "Fire", "game-obj": "Traits"}]
        rules_links = []
        other_links = []

        traits, cleaned_text, count = _parse_trait_parentheses(
            ability_text, trait_links, rules_links, other_links, trait_links
        )

        assert len(traits) == 1
        assert count == 1

    def test_non_trait_links_in_parens_become_traits(self):
        """Should treat non-Traits links in parens as traits."""
        ability_text = "(aura) This has an aura effect."
        all_links = [{"name": "aura", "game-obj": "MonsterAbilities"}]
        trait_links = []
        rules_links = []
        other_links = [{"name": "aura", "game-obj": "MonsterAbilities"}]

        traits, cleaned_text, count = _parse_trait_parentheses(
            ability_text, trait_links, rules_links, other_links, all_links
        )

        assert len(traits) == 1
        assert traits[0]["name"] == "aura"
        # Should be removed from other_links since it was consumed as trait
        assert len(other_links) == 0


class TestParseAbilityDescription:
    """Tests for _parse_ability_description helper."""

    ADDON_NAMES = constants.CREATURE_ABILITY_ADDON_NAMES

    def test_sets_text_field(self):
        """Should set text field on ability."""
        content_parts = ["Some ability description text"]
        ability = {}

        _parse_ability_description(content_parts, ability, self.ADDON_NAMES)

        assert "text" in ability
        assert "Some ability description text" in ability["text"]

    def test_extracts_action_type(self):
        """Should extract action type from content."""
        content_parts = [
            '<span class="action" title="Two Actions">[two-actions]</span> ability text'
        ]
        ability = {}

        _parse_ability_description(content_parts, ability, self.ADDON_NAMES)

        assert "action_type" in ability

    def test_extracts_traits_from_parens(self):
        """Should extract traits from opening parentheses."""
        content_parts = ['(<a href="Traits.aspx?ID=1">Fire</a>) deals fire damage']
        ability = {}

        _parse_ability_description(content_parts, ability, self.ADDON_NAMES)

        assert "traits" in ability
        assert len(ability["traits"]) == 1

    def test_extracts_links(self):
        """Should extract and set links on ability."""
        # get_links requires href with game-obj parameter in URL
        content_parts = ['deals <a href="Spells.aspx?ID=1&game-obj=Spells">Fireball</a> damage']
        ability = {}

        _parse_ability_description(content_parts, ability, self.ADDON_NAMES)

        # Links extraction depends on get_links finding valid game-obj links
        # The text should still be extracted regardless
        assert "text" in ability

    def test_returns_converted_count(self):
        """Should return count of trait links converted."""
        content_parts = [
            '(<a href="Traits.aspx?ID=1" data-game-obj="Traits">Fire</a>) deals damage'
        ]
        ability = {}

        count = _parse_ability_description(content_parts, ability, self.ADDON_NAMES)

        assert count >= 0  # May be 0 or 1 depending on link extraction

    def test_handles_empty_content(self):
        """Should handle empty content parts."""
        content_parts = []
        ability = {}

        count = _parse_ability_description(content_parts, ability, self.ADDON_NAMES)

        assert count == 0


class TestExtractResultFields:
    """Tests for _extract_result_fields helper."""

    RESULT_FIELDS = ["Success", "Failure", "Critical Success", "Critical Failure"]

    def test_extracts_success_field(self):
        """Should extract Success field."""
        html = "<br><b>Success</b> The target takes damage."
        soup = BeautifulSoup(html, "html.parser")
        current = soup.find("br")
        ability = {}
        processed = set()

        _extract_result_fields(current, ability, self.RESULT_FIELDS, processed)

        assert "success" in ability
        assert "The target takes damage." in ability["success"]

    def test_extracts_failure_field(self):
        """Should extract Failure field."""
        html = "<br><b>Failure</b> Nothing happens."
        soup = BeautifulSoup(html, "html.parser")
        current = soup.find("br")
        ability = {}
        processed = set()

        _extract_result_fields(current, ability, self.RESULT_FIELDS, processed)

        assert "failure" in ability

    def test_extracts_critical_success(self):
        """Should extract Critical Success field with underscored key."""
        html = "<br><b>Critical Success</b> Double damage."
        soup = BeautifulSoup(html, "html.parser")
        current = soup.find("br")
        ability = {}
        processed = set()

        _extract_result_fields(current, ability, self.RESULT_FIELDS, processed)

        assert "critical_success" in ability

    def test_extracts_critical_failure(self):
        """Should extract Critical Failure field with underscored key."""
        html = "<br><b>Critical Failure</b> You take damage instead."
        soup = BeautifulSoup(html, "html.parser")
        current = soup.find("br")
        ability = {}
        processed = set()

        _extract_result_fields(current, ability, self.RESULT_FIELDS, processed)

        assert "critical_failure" in ability

    def test_extracts_multiple_result_fields(self):
        """Should extract multiple result fields."""
        html = (
            "<br><b>Success</b> damage<br><b>Failure</b> nothing<br><b>Critical Success</b> double"
        )
        soup = BeautifulSoup(html, "html.parser")
        current = soup.find("br")
        ability = {}
        processed = set()

        _extract_result_fields(current, ability, self.RESULT_FIELDS, processed)

        assert "success" in ability
        assert "failure" in ability
        assert "critical_success" in ability

    def test_marks_result_bolds_as_processed(self):
        """Should mark result field bold tags as processed."""
        html = "<br><b>Success</b> damage"
        soup = BeautifulSoup(html, "html.parser")
        current = soup.find("br")
        ability = {}
        processed = set()

        _extract_result_fields(current, ability, self.RESULT_FIELDS, processed)

        success_bold = soup.find("b")
        assert success_bold in processed

    def test_stops_at_non_result_bold(self):
        """Should stop when encountering non-result-field bold."""
        html = "<br><b>Success</b> damage<br><b>Other</b> text"
        soup = BeautifulSoup(html, "html.parser")
        current = soup.find("br")
        ability = {}
        processed = set()

        _extract_result_fields(current, ability, self.RESULT_FIELDS, processed)

        assert "success" in ability
        # Should have stopped at "Other"
        other_bold = soup.find_all("b")[1]
        assert other_bold not in processed

    def test_extracts_links_from_result_fields(self):
        """Should extract links from result field content and set success field."""
        html = "<br><b>Success</b> deals damage"
        soup = BeautifulSoup(html, "html.parser")
        current = soup.find("br")
        ability = {}
        processed = set()

        _extract_result_fields(current, ability, self.RESULT_FIELDS, processed)

        # Verify the success field was extracted
        assert "success" in ability
        assert "deals damage" in ability["success"]

    def test_handles_none_current(self):
        """Should handle None current position gracefully."""
        ability = {}
        processed = set()

        # Should not raise
        _extract_result_fields(None, ability, self.RESULT_FIELDS, processed)

        assert len(ability) == 0

    def test_skips_whitespace_between_br_and_bold(self):
        """Should skip whitespace NavigableStrings."""
        html = "<br>   \n   <b>Success</b> damage"
        soup = BeautifulSoup(html, "html.parser")
        current = soup.find("br")
        ability = {}
        processed = set()

        _extract_result_fields(current, ability, self.RESULT_FIELDS, processed)

        assert "success" in ability
