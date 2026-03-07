"""Unit tests for skill.py helper functions."""

import pytest
from bs4 import BeautifulSoup

from pfsrd2.skill import (
    KINGDOM_ATTRIBUTES,
    SKILL_ATTRIBUTES,
    _extract_action_type_from_name,
    _extract_bold_fields,
    _extract_key_ability,
    _extract_result_blocks,
    _extract_sample_tasks,
    _is_empty,
    _remove_empty_fields,
    _strip_block_tags,
    find_skill,
)


def _make_skill_section(name, sections=None):
    """Helper to build a minimal struct with a skill section."""
    skill = {
        "type": "stat_block_section",
        "subtype": "skill",
        "name": name,
        "sections": sections or [],
    }
    return {"sections": [skill]}


class TestFindSkill:
    def test_finds_skill_section(self):
        struct = _make_skill_section("Acrobatics (Dex)")
        assert find_skill(struct) is not None
        assert find_skill(struct)["name"] == "Acrobatics (Dex)"

    def test_returns_none_when_no_skill(self):
        struct = {"sections": [{"type": "section", "name": "Foo"}]}
        assert find_skill(struct) is None


class TestExtractKeyAbility:
    def test_character_skill_dex(self):
        struct = _make_skill_section("Acrobatics (Dex)")
        _extract_key_ability(struct)
        skill = find_skill(struct)
        assert skill["key_ability"] == "dex"
        assert skill["skill_type"] == "character_skill"
        assert skill["name"] == "Acrobatics"

    def test_character_skill_int(self):
        struct = _make_skill_section("Arcana (Int)")
        _extract_key_ability(struct)
        skill = find_skill(struct)
        assert skill["key_ability"] == "int"
        assert skill["skill_type"] == "character_skill"

    def test_kingdom_skill(self):
        struct = _make_skill_section("Engineering (Stability)")
        _extract_key_ability(struct)
        skill = find_skill(struct)
        assert skill["key_kingdom_ability"] == "stability"
        assert skill["skill_type"] == "kingdom_skill"
        assert skill["name"] == "Engineering"
        assert "key_ability" not in skill

    def test_no_parens_is_character_skill(self):
        struct = _make_skill_section("Lore")
        _extract_key_ability(struct)
        skill = find_skill(struct)
        assert skill["skill_type"] == "character_skill"
        assert "key_ability" not in skill

    def test_unknown_parens_asserts(self):
        struct = _make_skill_section("Foo (Unknown)")
        with pytest.raises(AssertionError, match="Unknown parenthesized attribute"):
            _extract_key_ability(struct)

    def test_all_character_abilities(self):
        for attr in SKILL_ATTRIBUTES:
            struct = _make_skill_section(f"Test ({attr.title()})")
            _extract_key_ability(struct)
            skill = find_skill(struct)
            assert skill["key_ability"] == attr

    def test_all_kingdom_abilities(self):
        for attr in KINGDOM_ATTRIBUTES:
            struct = _make_skill_section(f"Test ({attr.title()})")
            _extract_key_ability(struct)
            skill = find_skill(struct)
            assert skill["key_kingdom_ability"] == attr


class TestExtractActionTypeFromName:
    def _make_section(self, name):
        return {"name": name, "type": "section"}

    def test_single_action(self):
        section = self._make_section(
            'Balance <span class="action" title="Single Action">[#]</span>'
        )
        _extract_action_type_from_name(section)
        assert section["action_type"]["name"] == "One Action"

    def test_two_actions(self):
        section = self._make_section('Disarm <span class="action" title="Two Actions">[##]</span>')
        _extract_action_type_from_name(section)
        assert section["action_type"]["name"] == "Two Actions"

    def test_reaction(self):
        section = self._make_section('Grab Edge <span class="action" title="Reaction">[@]</span>')
        _extract_action_type_from_name(section)
        assert section["action_type"]["name"] == "Reaction"

    def test_no_action_span(self):
        section = self._make_section("Common Lore Subcategories")
        _extract_action_type_from_name(section)
        assert "action_type" not in section

    def test_unknown_title_asserts(self):
        section = self._make_section('Foo <span class="action" title="Unknown Action">[?]</span>')
        with pytest.raises(AssertionError, match="Unknown action title"):
            _extract_action_type_from_name(section)


class TestExtractSampleTasks:
    def test_parses_proficiency_levels(self):
        section = {
            "name": "Test",
            "sections": [
                {
                    "name": "Sample Acrobatics Tasks",
                    "text": "<b>Untrained</b> cross a narrow ledge<br/>"
                    "<b>Trained</b> walk a tightrope<br/>"
                    "<b>Expert</b> balance on a razor edge<br/>",
                }
            ],
        }
        _extract_sample_tasks(section)
        assert "sample_tasks" in section
        tasks = section["sample_tasks"]
        assert len(tasks) == 3
        assert tasks[0]["proficiency"] == "untrained"
        assert tasks[0]["name"] == "cross a narrow ledge"
        assert tasks[1]["proficiency"] == "trained"
        assert tasks[2]["proficiency"] == "expert"

    def test_comma_separated_tasks(self):
        section = {
            "name": "Test",
            "sections": [
                {
                    "name": "Sample Tasks",
                    "text": "<b>Untrained</b> task one, task two, task three<br/>",
                }
            ],
        }
        _extract_sample_tasks(section)
        tasks = section["sample_tasks"]
        assert len(tasks) == 3
        assert all(t["proficiency"] == "untrained" for t in tasks)
        assert tasks[0]["name"] == "task one"
        assert tasks[1]["name"] == "task two"
        assert tasks[2]["name"] == "task three"

    def test_non_sample_tasks_preserved(self):
        section = {
            "name": "Test",
            "sections": [
                {"name": "Other Section", "text": "keep me"},
                {
                    "name": "Sample Tasks",
                    "text": "<b>Trained</b> a task<br/>",
                },
            ],
        }
        _extract_sample_tasks(section)
        assert len(section["sections"]) == 1
        assert section["sections"][0]["name"] == "Other Section"
        assert len(section["sample_tasks"]) == 1

    def test_no_sample_tasks_no_field(self):
        section = {
            "name": "Test",
            "sections": [{"name": "Other", "text": "nothing here"}],
        }
        _extract_sample_tasks(section)
        assert "sample_tasks" not in section

    def test_all_proficiency_levels(self):
        section = {
            "name": "Test",
            "sections": [
                {
                    "name": "Sample Tasks",
                    "text": "<b>Untrained</b> a<br/>"
                    "<b>Trained</b> b<br/>"
                    "<b>Expert</b> c<br/>"
                    "<b>Master</b> d<br/>"
                    "<b>Legendary</b> e<br/>",
                }
            ],
        }
        _extract_sample_tasks(section)
        levels = [t["proficiency"] for t in section["sample_tasks"]]
        assert levels == ["untrained", "trained", "expert", "master", "legendary"]


class TestExtractBoldFields:
    def test_extracts_requirement(self):
        section = {}
        text = "<b>Requirements</b> You have a shield raised."
        _extract_bold_fields(section, text)
        assert section["requirement"] == "You have a shield raised."

    def test_singular_requirement_normalizes(self):
        section = {}
        text = "<b>Requirement</b> You are trained."
        _extract_bold_fields(section, text)
        assert section["requirement"] == "You are trained."

    def test_extracts_trigger(self):
        section = {}
        text = "<b>Trigger</b> An enemy hits you."
        _extract_bold_fields(section, text)
        assert section["trigger"] == "An enemy hits you."

    def test_extracts_frequency(self):
        section = {}
        text = "<b>Frequency</b> once per day"
        _extract_bold_fields(section, text)
        assert section["frequency"] == "once per day"

    def test_extracts_cost(self):
        section = {}
        text = "<b>Cost</b> 1 Focus Point"
        _extract_bold_fields(section, text)
        assert section["cost"] == "1 Focus Point"

    def test_strips_trailing_semicolon(self):
        section = {}
        text = "<b>Requirements</b> You have a shield raised;"
        _extract_bold_fields(section, text)
        assert section["requirement"] == "You have a shield raised"

    def test_multiple_fields(self):
        section = {}
        text = "<b>Requirements</b> trained;<b>Trigger</b> enemy moves"
        _extract_bold_fields(section, text)
        assert section["requirement"] == "trained"
        assert section["trigger"] == "enemy moves"

    def test_ignores_unknown_bold(self):
        section = {}
        text = "<b>Unknown</b> some text"
        _extract_bold_fields(section, text)
        assert "unknown" not in section


class TestExtractResultBlocks:
    def test_extracts_all_results(self):
        section = {}
        html = (
            "<b>Critical Success</b> You do great."
            "<b>Success</b> You do OK."
            "<b>Failure</b> You fail."
            "<b>Critical Failure</b> You fail badly."
        )
        bs = BeautifulSoup(html, "html.parser")
        _extract_result_blocks(section, bs)
        assert section["critical_success"] == "You do great."
        assert section["success"] == "You do OK."
        assert section["failure"] == "You fail."
        assert section["critical_failure"] == "You fail badly."

    def test_partial_results(self):
        section = {}
        html = "<b>Success</b> You succeed.<b>Failure</b> You fail."
        bs = BeautifulSoup(html, "html.parser")
        _extract_result_blocks(section, bs)
        assert section["success"] == "You succeed."
        assert section["failure"] == "You fail."
        assert "critical_success" not in section
        assert "critical_failure" not in section

    def test_non_result_bold_preserved(self):
        section = {}
        html = "<b>Note</b> This is important.<b>Success</b> You succeed."
        bs = BeautifulSoup(html, "html.parser")
        _extract_result_blocks(section, bs)
        assert section["success"] == "You succeed."
        # The non-result bold should still be in the soup
        remaining = str(bs)
        assert "Note" in remaining

    def test_result_blocks_removed_from_soup(self):
        section = {}
        html = "Some text.<b>Success</b> You succeed.<b>Failure</b> You fail."
        bs = BeautifulSoup(html, "html.parser")
        _extract_result_blocks(section, bs)
        remaining = str(bs)
        assert "Success" not in remaining
        assert "Failure" not in remaining
        assert "Some text." in remaining


class TestIsEmpty:
    def test_none_is_empty(self):
        assert _is_empty(None) is True

    def test_empty_string_is_empty(self):
        assert _is_empty("") is True

    def test_empty_list_is_empty(self):
        assert _is_empty([]) is True

    def test_empty_dict_is_empty(self):
        assert _is_empty({}) is True

    def test_nonempty_string(self):
        assert _is_empty("hello") is False

    def test_nonempty_list(self):
        assert _is_empty([1]) is False

    def test_nonempty_dict(self):
        assert _is_empty({"a": 1}) is False

    def test_zero_is_not_empty(self):
        assert _is_empty(0) is False

    def test_false_is_not_empty(self):
        assert _is_empty(False) is False


class TestRemoveEmptyFields:
    def test_removes_empty_string(self):
        obj = {"a": "hello", "b": ""}
        _remove_empty_fields(obj)
        assert obj == {"a": "hello"}

    def test_removes_none(self):
        obj = {"a": 1, "b": None}
        _remove_empty_fields(obj)
        assert obj == {"a": 1}

    def test_removes_empty_list(self):
        obj = {"a": [1], "b": []}
        _remove_empty_fields(obj)
        assert obj == {"a": [1]}

    def test_removes_empty_dict(self):
        obj = {"a": {"x": 1}, "b": {}}
        _remove_empty_fields(obj)
        assert obj == {"a": {"x": 1}}

    def test_recursive_dict(self):
        obj = {"a": {"b": {"c": ""}}}
        _remove_empty_fields(obj)
        assert obj == {}

    def test_recursive_list(self):
        obj = {"a": [{"b": ""}]}
        _remove_empty_fields(obj)
        assert obj == {}

    def test_preserves_nonempty(self):
        obj = {"a": "x", "b": 0, "c": False, "d": [1], "e": {"f": "g"}}
        _remove_empty_fields(obj)
        assert obj == {"a": "x", "b": 0, "c": False, "d": [1], "e": {"f": "g"}}

    def test_list_filtering(self):
        obj = {"items": [{"a": ""}, {"b": "keep"}]}
        _remove_empty_fields(obj)
        assert obj == {"items": [{"b": "keep"}]}


class TestStripBlockTags:
    def test_unwraps_p_tags(self):
        struct = {"text": "<p>Hello world</p>"}
        _strip_block_tags(struct)
        assert "<p" not in struct["text"]
        assert "Hello world" in struct["text"]

    def test_unwraps_nonempty_div(self):
        struct = {"text": '<div class="something">Content</div>'}
        _strip_block_tags(struct)
        assert "<div" not in struct["text"]
        assert "Content" in struct["text"]

    def test_decomposes_empty_div(self):
        struct = {"text": '<div class="clear"></div>More text'}
        _strip_block_tags(struct)
        assert "<div" not in struct["text"]
        assert "More text" in struct["text"]

    def test_no_block_tags_unchanged(self):
        struct = {"text": "plain text with <b>bold</b>"}
        _strip_block_tags(struct)
        assert struct["text"] == "plain text with <b>bold</b>"

    def test_recursive(self):
        struct = {"inner": {"text": "<p>nested</p>"}}
        _strip_block_tags(struct)
        assert "<p" not in struct["inner"]["text"]

    def test_recursive_list(self):
        struct = {"items": [{"text": "<p>in list</p>"}]}
        _strip_block_tags(struct)
        assert "<p" not in struct["items"][0]["text"]
