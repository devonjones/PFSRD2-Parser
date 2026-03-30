"""Unit tests for skill.py helper functions."""

import pytest
from bs4 import BeautifulSoup

from pfsrd2.skill import (
    KINGDOM_ATTRIBUTES,
    SKILL_ATTRIBUTES,
    _clean_html_fields,
    _content_filter,
    _convert_skill_text,
    _extract_action_text,
    _extract_action_type_from_name,
    _extract_key_ability,
    _extract_sample_tasks,
    _promote_skill_fields,
    _SKILL_BOLD_LABELS,
    action_extract_pass,
    find_skill,
)
from universal.universal import extract_bold_fields
from universal.universal import extract_result_blocks, extract_source_from_bs
from universal.utils import is_empty, remove_empty_fields, strip_block_tags


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
        extract_bold_fields(section, BeautifulSoup(text, "html.parser"), _SKILL_BOLD_LABELS)
        assert section["requirement"] == "You have a shield raised."

    def test_singular_requirement_normalizes(self):
        section = {}
        text = "<b>Requirement</b> You are trained."
        extract_bold_fields(section, BeautifulSoup(text, "html.parser"), _SKILL_BOLD_LABELS)
        assert section["requirement"] == "You are trained."

    def test_extracts_trigger(self):
        section = {}
        text = "<b>Trigger</b> An enemy hits you."
        extract_bold_fields(section, BeautifulSoup(text, "html.parser"), _SKILL_BOLD_LABELS)
        assert section["trigger"] == "An enemy hits you."

    def test_extracts_frequency(self):
        section = {}
        text = "<b>Frequency</b> once per day"
        extract_bold_fields(section, BeautifulSoup(text, "html.parser"), _SKILL_BOLD_LABELS)
        assert section["frequency"] == "once per day"

    def test_extracts_cost(self):
        section = {}
        text = "<b>Cost</b> 1 Focus Point"
        extract_bold_fields(section, BeautifulSoup(text, "html.parser"), _SKILL_BOLD_LABELS)
        assert section["cost"] == "1 Focus Point"

    def test_strips_trailing_semicolon(self):
        section = {}
        text = "<b>Requirements</b> You have a shield raised;"
        extract_bold_fields(section, BeautifulSoup(text, "html.parser"), _SKILL_BOLD_LABELS)
        assert section["requirement"] == "You have a shield raised"

    def test_multiple_fields(self):
        section = {}
        text = "<b>Requirements</b> trained;<b>Trigger</b> enemy moves"
        extract_bold_fields(section, BeautifulSoup(text, "html.parser"), _SKILL_BOLD_LABELS)
        assert section["requirement"] == "trained"
        assert section["trigger"] == "enemy moves"

    def test_ignores_unknown_bold(self):
        section = {}
        text = "<b>Unknown</b> some text"
        extract_bold_fields(section, BeautifulSoup(text, "html.parser"), _SKILL_BOLD_LABELS)
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
        extract_result_blocks(section, bs)
        assert section["critical_success"] == "You do great."
        assert section["success"] == "You do OK."
        assert section["failure"] == "You fail."
        assert section["critical_failure"] == "You fail badly."

    def test_partial_results(self):
        section = {}
        html = "<b>Success</b> You succeed.<b>Failure</b> You fail."
        bs = BeautifulSoup(html, "html.parser")
        extract_result_blocks(section, bs)
        assert section["success"] == "You succeed."
        assert section["failure"] == "You fail."
        assert "critical_success" not in section
        assert "critical_failure" not in section

    def test_non_result_bold_preserved(self):
        section = {}
        html = "<b>Note</b> This is important.<b>Success</b> You succeed."
        bs = BeautifulSoup(html, "html.parser")
        extract_result_blocks(section, bs)
        assert section["success"] == "You succeed."
        # The non-result bold should still be in the soup
        remaining = str(bs)
        assert "Note" in remaining

    def test_result_blocks_removed_from_soup(self):
        section = {}
        html = "Some text.<b>Success</b> You succeed.<b>Failure</b> You fail."
        bs = BeautifulSoup(html, "html.parser")
        extract_result_blocks(section, bs)
        remaining = str(bs)
        assert "Success" not in remaining
        assert "Failure" not in remaining
        assert "Some text." in remaining


class TestIsEmpty:
    def test_noneis_empty(self):
        assert is_empty(None) is True

    def test_empty_stringis_empty(self):
        assert is_empty("") is True

    def test_empty_listis_empty(self):
        assert is_empty([]) is True

    def test_empty_dictis_empty(self):
        assert is_empty({}) is True

    def test_nonempty_string(self):
        assert is_empty("hello") is False

    def test_nonempty_list(self):
        assert is_empty([1]) is False

    def test_nonempty_dict(self):
        assert is_empty({"a": 1}) is False

    def test_zero_is_not_empty(self):
        assert is_empty(0) is False

    def test_false_is_not_empty(self):
        assert is_empty(False) is False


class TestRemoveEmptyFields:
    def test_removes_empty_string(self):
        obj = {"a": "hello", "b": ""}
        remove_empty_fields(obj)
        assert obj == {"a": "hello"}

    def test_removes_none(self):
        obj = {"a": 1, "b": None}
        remove_empty_fields(obj)
        assert obj == {"a": 1}

    def test_removes_empty_list(self):
        obj = {"a": [1], "b": []}
        remove_empty_fields(obj)
        assert obj == {"a": [1]}

    def test_removes_empty_dict(self):
        obj = {"a": {"x": 1}, "b": {}}
        remove_empty_fields(obj)
        assert obj == {"a": {"x": 1}}

    def test_recursive_dict(self):
        obj = {"a": {"b": {"c": ""}}}
        remove_empty_fields(obj)
        assert obj == {}

    def test_recursive_list(self):
        obj = {"a": [{"b": ""}]}
        remove_empty_fields(obj)
        assert obj == {}

    def test_preserves_nonempty(self):
        obj = {"a": "x", "b": 0, "c": False, "d": [1], "e": {"f": "g"}}
        remove_empty_fields(obj)
        assert obj == {"a": "x", "b": 0, "c": False, "d": [1], "e": {"f": "g"}}

    def test_list_filtering(self):
        obj = {"items": [{"a": ""}, {"b": "keep"}]}
        remove_empty_fields(obj)
        assert obj == {"items": [{"b": "keep"}]}


class TestStripBlockTags:
    def test_unwraps_p_tags(self):
        struct = {"text": "<p>Hello world</p>"}
        strip_block_tags(struct)
        assert "<p" not in struct["text"]
        assert "Hello world" in struct["text"]

    def test_unwraps_nonempty_div(self):
        struct = {"text": '<div class="something">Content</div>'}
        strip_block_tags(struct)
        assert "<div" not in struct["text"]
        assert "Content" in struct["text"]

    def test_decomposes_empty_div(self):
        struct = {"text": '<div class="clear"></div>More text'}
        strip_block_tags(struct)
        assert "<div" not in struct["text"]
        assert "More text" in struct["text"]

    def test_no_block_tags_unchanged(self):
        struct = {"text": "plain text with <b>bold</b>"}
        strip_block_tags(struct)
        assert struct["text"] == "plain text with <b>bold</b>"

    def test_recursive(self):
        struct = {"inner": {"text": "<p>nested</p>"}}
        strip_block_tags(struct)
        assert "<p" not in struct["inner"]["text"]

    def test_recursive_list(self):
        struct = {"items": [{"text": "<p>in list</p>"}]}
        strip_block_tags(struct)
        assert "<p" not in struct["items"][0]["text"]


class TestContentFilter:
    def _make_soup(self, html):
        return BeautifulSoup(html, "html.parser")

    def test_strips_nav_before_hr(self):
        soup = self._make_soup('<div id="main"><nav>Nav</nav><a>Link</a><hr/><h1>Title</h1></div>')
        _content_filter(soup)
        main = soup.find(id="main")
        assert main.find("nav") is None
        assert main.find("hr") is None
        assert main.find("h1") is not None

    def test_unwraps_span_containing_h1(self):
        soup = self._make_soup('<div id="main"><span><h1>Skill Name</h1></span></div>')
        _content_filter(soup)
        main = soup.find(id="main")
        # span should be unwrapped, h1 should remain
        assert main.find("span") is None
        assert main.find("h1") is not None

    def test_no_main_div_is_noop(self):
        soup = self._make_soup("<div>No main here</div>")
        _content_filter(soup)
        assert "No main here" in str(soup)

    def test_no_hr_keeps_content(self):
        soup = self._make_soup('<div id="main"><h1>Title</h1><p>Content</p></div>')
        _content_filter(soup)
        assert soup.find("h1") is not None
        assert soup.find("p") is not None

    def test_only_first_span_with_h1_unwrapped(self):
        soup = self._make_soup(
            '<div id="main">' "<span><h1>Title</h1></span>" "<span>Other span</span>" "</div>"
        )
        _content_filter(soup)
        main = soup.find(id="main")
        # First span unwrapped, second span preserved
        spans = main.find_all("span")
        assert len(spans) == 1
        assert "Other span" in spans[0].text


class TestActionExtractPass:
    def _make_struct(self, action_sections, section_name="Untrained Actions"):
        skill = {
            "type": "stat_block_section",
            "subtype": "skill",
            "name": "TestSkill",
            "sections": [],
        }
        actions_section = {
            "name": section_name,
            "type": "section",
            "sections": action_sections,
        }
        return {"name": "TestSkill", "type": "skill", "sections": [skill, actions_section]}

    def test_extracts_action_with_source(self):
        action = {
            "name": "Balance",
            "type": "section",
            "text": '<b>Source</b> <a href="/Sources.aspx?ID=1">Core Rulebook pg. 1</a>',
            "sections": [],
        }
        struct = self._make_struct([action])
        action_extract_pass(struct)
        skill = find_skill(struct)
        assert "actions" in skill
        assert skill["actions"][0]["subtype"] == "skill_action"
        assert skill["actions"][0]["name"] == "Balance"

    def test_trained_flag_set(self):
        action = {
            "name": "Identify",
            "type": "section",
            "text": '<b>Source</b> <a href="/Sources.aspx?ID=1">Core Rulebook pg. 1</a>',
            "sections": [],
        }
        struct = self._make_struct([action], section_name="Trained Actions")
        action_extract_pass(struct)
        skill = find_skill(struct)
        assert skill["actions"][0]["trained"] is True

    def test_untrained_flag_set(self):
        action = {
            "name": "Balance",
            "type": "section",
            "text": '<b>Source</b> <a href="/Sources.aspx?ID=1">Core Rulebook pg. 1</a>',
            "sections": [],
        }
        struct = self._make_struct([action], section_name="Untrained Actions")
        action_extract_pass(struct)
        skill = find_skill(struct)
        assert skill["actions"][0]["trained"] is False

    def test_descriptive_section_attached_to_preceding_action(self):
        real_action = {
            "name": "Balance",
            "type": "section",
            "text": '<b>Source</b> <a href="/Sources.aspx?ID=1">Core Rulebook pg. 1</a>',
            "sections": [],
        }
        descriptive = {
            "name": "Table of DCs",
            "type": "section",
            "text": "Some table data",
            "sections": [],
        }
        struct = self._make_struct([real_action, descriptive])
        action_extract_pass(struct)
        skill = find_skill(struct)
        assert len(skill["actions"]) == 1
        assert "sections" in skill["actions"][0]
        assert skill["actions"][0]["sections"][0]["name"] == "Table of DCs"

    def test_related_feats_skipped(self):
        related = {
            "name": "Related Feats",
            "type": "section",
            "text": "Some feats",
            "sections": [],
        }
        action = {
            "name": "Balance",
            "type": "section",
            "text": '<b>Source</b> <a href="/Sources.aspx?ID=1">Core Rulebook pg. 1</a>',
            "sections": [],
        }
        struct = self._make_struct([related, action])
        action_extract_pass(struct)
        skill = find_skill(struct)
        assert len(skill["actions"]) == 1
        assert skill["actions"][0]["name"] == "Balance"

    def test_non_actions_section_preserved(self):
        other = {"name": "Description", "type": "section", "text": "Desc"}
        skill = {
            "type": "stat_block_section",
            "subtype": "skill",
            "name": "TestSkill",
            "sections": [],
        }
        struct = {"name": "TestSkill", "type": "skill", "sections": [skill, other]}
        action_extract_pass(struct)
        assert any(s.get("name") == "Description" for s in struct["sections"])

    def test_no_actions_no_key(self):
        skill = {
            "type": "stat_block_section",
            "subtype": "skill",
            "name": "TestSkill",
            "sections": [],
        }
        struct = {"name": "TestSkill", "type": "skill", "sections": [skill]}
        action_extract_pass(struct)
        assert "actions" not in find_skill(struct)


class TestExtractActionText:
    def test_extracts_traits(self):
        section = {
            "text": '<span class="trait"><a href="/Traits.aspx?ID=1">Auditory</a></span> Some text',
            "sections": [],
        }
        _extract_action_text(section)
        assert "traits" in section
        assert section["traits"][0]["name"] == "Auditory"
        assert "<span" not in section["text"]

    def test_extracts_source(self):
        section = {
            "text": '<b>Source</b> <a href="/Sources.aspx?ID=1">Core Rulebook pg. 240</a><br/>Description here',
            "sections": [],
        }
        _extract_action_text(section)
        assert "source" in section

    def test_extracts_fields_from_pre_hr(self):
        section = {
            "text": "<b>Requirements</b> You have a shield raised<hr/>Description text",
            "sections": [],
        }
        _extract_action_text(section)
        assert section["requirement"] == "You have a shield raised"
        assert "Description text" in section["text"]

    def test_extracts_result_blocks(self):
        section = {
            "text": "<b>Success</b> You succeed.<b>Failure</b> You fail.",
            "sections": [],
        }
        _extract_action_text(section)
        assert section["success"] == "You succeed."
        assert section["failure"] == "You fail."

    def test_strips_leading_trailing_br(self):
        section = {
            "text": "<br/><br/>Some text<br/>",
            "sections": [],
        }
        _extract_action_text(section)
        assert section["text"] == "Some text"

    def test_strips_letter_spacing_spans(self):
        section = {
            "text": '<span style="letter-spacing:5px"> </span>Content',
            "sections": [],
        }
        _extract_action_text(section)
        assert "<span" not in section["text"]
        assert "Content" in section["text"]


class TestExtractSourceFromBs:
    def test_extracts_source_with_link(self):
        html = '<b>Source</b> <a href="/Sources.aspx?ID=1">Core Rulebook pg. 240</a>'
        bs = BeautifulSoup(html, "html.parser")
        source = extract_source_from_bs(bs)
        assert source is not None
        assert "name" in source

    def test_returns_none_when_no_source(self):
        bs = BeautifulSoup("Just some text", "html.parser")
        source = extract_source_from_bs(bs)
        assert source is None

    def test_extracts_errata(self):
        html = (
            '<b>Source</b> <a href="/Sources.aspx?ID=1">Book</a>'
            '<sup><a href="/Errata.aspx?ID=1">Errata</a></sup>'
        )
        bs = BeautifulSoup(html, "html.parser")
        source = extract_source_from_bs(bs)
        assert source is not None
        assert "errata" in source

    def test_removes_source_from_soup(self):
        html = '<b>Source</b> <a href="/Sources.aspx?ID=1">Book</a> Remaining text'
        bs = BeautifulSoup(html, "html.parser")
        extract_source_from_bs(bs)
        remaining = str(bs)
        assert "Source" not in remaining
        assert "Remaining text" in remaining

    def test_removes_trailing_br(self):
        html = '<b>Source</b> <a href="/Sources.aspx?ID=1">Book</a><br/>Text'
        bs = BeautifulSoup(html, "html.parser")
        extract_source_from_bs(bs)
        assert "<br" not in str(bs).split("Text")[0]


class TestConvertSkillText:
    def test_converts_text_to_markdown(self):
        skill = {"text": "Simple text"}
        _convert_skill_text(skill)
        assert "text" in skill

    def test_strips_nethys_note(self):
        skill = {"text": "<i>Note from Nethys: blah blah</i>Real content"}
        _convert_skill_text(skill)
        assert "Nethys" not in skill.get("text", "")

    def test_strips_details_tags(self):
        skill = {"text": "<details>Widget</details>Content"}
        _convert_skill_text(skill)
        assert "details" not in skill.get("text", "")
        assert "Content" in skill.get("text", "")

    def test_no_text_is_noop(self):
        skill = {"name": "Test"}
        _convert_skill_text(skill)
        assert "text" not in skill


class TestPromoteSkillFields:
    def test_promotes_name_and_sources(self):
        skill = {
            "name": "Acrobatics",
            "sources": [{"name": "CR", "type": "source"}],
            "type": "stat_block_section",
            "subtype": "skill",
        }
        struct = {"skill": skill, "sections": []}
        _promote_skill_fields(struct, skill)
        assert struct["name"] == "Acrobatics"
        assert struct["sources"] == [{"name": "CR", "type": "source"}]
        assert "sources" not in skill

    def test_retains_key_ability_in_skill(self):
        skill = {
            "name": "Test",
            "sources": [],
            "key_ability": "dex",
            "skill_type": "character_skill",
            "type": "stat_block_section",
            "subtype": "skill",
        }
        struct = {"skill": skill, "sections": []}
        _promote_skill_fields(struct, skill)
        assert "key_ability" not in struct
        assert "skill_type" not in struct
        assert skill["key_ability"] == "dex"
        assert skill["skill_type"] == "character_skill"

    def test_retains_kingdom_ability_in_skill(self):
        skill = {
            "name": "Test",
            "sources": [],
            "key_kingdom_ability": "stability",
            "skill_type": "kingdom_skill",
            "type": "stat_block_section",
            "subtype": "skill",
        }
        struct = {"skill": skill, "sections": []}
        _promote_skill_fields(struct, skill)
        assert "key_kingdom_ability" not in struct
        assert skill["key_kingdom_ability"] == "stability"

    def test_retains_links_in_skill(self):
        skill = {
            "name": "Test",
            "sources": [],
            "links": [{"name": "link1"}],
            "type": "stat_block_section",
            "subtype": "skill",
        }
        struct = {"skill": skill, "sections": []}
        _promote_skill_fields(struct, skill)
        assert "links" not in struct
        assert skill["links"] == [{"name": "link1"}]


class TestCleanHtmlFields:
    def test_renames_html_to_text(self):
        struct = {"sections": [{"html": "content", "name": "Test"}]}
        _clean_html_fields(struct)
        assert struct["sections"][0]["text"] == "content"
        assert "html" not in struct["sections"][0]

    def test_recursive(self):
        struct = {"sections": [{"name": "Outer", "sections": [{"html": "inner", "name": "Inner"}]}]}
        _clean_html_fields(struct)
        assert struct["sections"][0]["sections"][0]["text"] == "inner"

    def test_no_html_unchanged(self):
        struct = {"sections": [{"text": "already text", "name": "Test"}]}
        _clean_html_fields(struct)
        assert struct["sections"][0]["text"] == "already text"
