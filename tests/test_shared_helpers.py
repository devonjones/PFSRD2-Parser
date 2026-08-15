"""Tests for universal/creatures.py:parse_save_dc.

Hoisted out of universal/ability.py so afflictions could share it. That gave
it a new `strict` parameter and six times the callers, and the first version
of the hoist silently lost "DC varies" for every creature — the gate was
narrowed to a numeric DC, which universal_handle_save_dc never required.
"""

import pytest

from universal.creatures import parse_save_dc


class TestNumericDC:
    def test_a_dc_and_a_save_type(self):
        save = parse_save_dc("DC 22 Fortitude")
        assert (save["dc"], save["save_type"]) == (22, "Fort")

    def test_the_save_name_may_come_first(self):
        assert parse_save_dc("Fortitude DC 22")["dc"] == 22


class TestNonNumericDC:
    def test_a_varying_dc_keeps_its_text(self):
        # The whole reason the gate cannot be "is there a number here".
        save = parse_save_dc("Fortitude DC varies")
        assert save["dc_text"] == "varies"
        assert save["save_type"] == "Fort"

    def test_a_varying_dc_with_no_save_name(self):
        assert parse_save_dc("DC varies")["dc_text"] == "varies"

    def test_a_formula_dc_falls_back_to_what_was_published(self):
        # "the high spell DC for the ghoul's level" is a formula, not a bug.
        save = parse_save_dc("Will save, with a high spell DC for a monster of its level")
        assert "dc" not in save
        assert save["save_type"] == "Will"
        assert save["text"].startswith("Will save")


class TestSaveNames:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("Fortitude", "Fort"),
            ("Fort", "Fort"),
            ("Reflex", "Ref"),
            ("Ref", "Ref"),
            ("Will", "Will"),
        ],
    )
    def test_abbreviated_and_full_names_both_resolve(self, text, expected):
        # The abbreviations are why this was hoisted: reading only the full
        # names gave the same text different answers by content type.
        assert parse_save_dc(f"{text} save, with a high spell DC")["save_type"] == expected

    def test_an_unnamed_save_gets_no_type(self):
        assert "save_type" not in parse_save_dc("something else entirely")


class TestStrict:
    def test_strict_still_accepts_a_non_numeric_dc(self):
        # strict is about numbers that will not parse, not about prose.
        assert parse_save_dc("Fortitude DC varies", strict=True)["dc_text"] == "varies"

    def test_strict_refuses_to_degrade_a_broken_numeric_dc(self):
        with pytest.raises(AssertionError):
            parse_save_dc("DC 22 and then some nonsense ;;", strict=True)

    def test_lenient_degrades_the_same_input_to_prose(self):
        assert "dc" not in parse_save_dc("DC 22 and then some nonsense ;;")


class TestEmpty:
    def test_empty_text_yields_an_empty_save(self):
        assert parse_save_dc("") == {
            "type": "stat_block_section",
            "subtype": "save_dc",
            "text": "",
        }


class TestSharedHelpers:
    """The hoisted helpers, tested where they now live.

    Each was private to one parser before this change and is now imported by
    up to seven, so a regression here is a regression everywhere.
    """

    def test_sidebar_filter_unwraps_without_dropping_content(self):
        from bs4 import BeautifulSoup

        from universal.utils import sidebar_filter

        soup = BeautifulSoup('<div class="sidebar-nofloat"><b>Keep</b> me</div>', "html.parser")
        sidebar_filter(soup)
        assert soup.find("div") is None
        assert "Keep" in str(soup)

    def test_plain_text_strips_markup(self):
        from universal.utils import plain_text

        assert plain_text('<a href="x">Thievery</a> DC 12') == "Thievery DC 12"

    def test_nodes_after_stops_at_the_next_bold(self):
        from bs4 import BeautifulSoup

        from universal.utils import nodes_after

        soup = BeautifulSoup("<b>A</b> one <b>B</b> two", "html.parser")
        run = "".join(str(n) for n in nodes_after(soup.find("b")))
        assert run.strip() == "one"

    def test_flatten_fields_keeps_links_and_leaves_plain_values(self):
        from universal.utils import flatten_fields

        section = {"disable": '<a game-obj="Skills" aonid="17">Thievery</a> DC 12', "x": "Simple"}
        flatten_fields(section, ("disable", "x"))
        assert section["disable"] == "Thievery DC 12"
        assert section["x"] == "Simple"
        assert [link["name"] for link in section["links"]] == ["Thievery"]

    def test_take_stat_block_text_leaves_the_section_behind(self):
        from universal.universal import take_stat_block_text

        sections = [{"name": "Legacy Content", "text": "body"}]
        assert take_stat_block_text(sections) == "body"
        assert sections[0]["name"] == "Legacy Content"
        assert "text" not in sections[0]

    def test_take_stat_block_text_descends(self):
        from universal.universal import take_stat_block_text

        sections = [{"name": "Spoilers", "sections": [{"name": "Legacy Content", "text": "b"}]}]
        assert take_stat_block_text(sections) == "b"

    def test_drop_marker_sections_removes_a_nested_husk(self):
        from universal.universal import drop_marker_sections

        struct = {
            "name": "X",
            "sections": [{"name": "Spoilers", "sections": [{"name": "Legacy Content"}]}],
        }
        drop_marker_sections(struct)
        assert struct["sections"][0]["sections"] == []

    def test_drop_marker_sections_refuses_to_drop_content(self):
        from universal.universal import drop_marker_sections

        struct = {"name": "X", "sections": [{"name": "Legacy Content", "text": "real"}]}
        with pytest.raises(AssertionError, match="still carries text"):
            drop_marker_sections(struct)

    def test_disambiguated_filename_ignores_an_unrelated_longer_name(self, tmp_path):
        # char_replace maps spaces to underscores, so a bare _* glob would
        # treat "glyph_of_warding_trap.json" as a collision suffix.
        import json as _json

        from universal.files import disambiguated_filename

        (tmp_path / "glyph_of_warding_trap.json").write_text("{}")
        struct = {"name": "Glyph of Warding", "aonid": 263}
        assert disambiguated_filename(str(tmp_path), struct, "hazard").endswith(
            "glyph_of_warding.json"
        )
        (tmp_path / "glyph_of_warding.json").write_text(_json.dumps({"aonid": 263}))
        assert disambiguated_filename(str(tmp_path), struct, "hazard").endswith(
            "glyph_of_warding.json"
        )


class TestDisambiguatedFilenameGuards:
    def test_an_existing_file_without_an_aonid_fails_loudly(self, tmp_path):
        # Two writers share this now, so a foreign file in the output tree
        # must not be silently treated as a collision partner.
        from universal.files import disambiguated_filename

        (tmp_path / "hidden_pit.json").write_text("{}")
        with pytest.raises(AssertionError, match="has no aonid"):
            disambiguated_filename(str(tmp_path), {"name": "Hidden Pit", "aonid": 1}, "hazard")

    def test_unreadable_json_says_which_file(self, tmp_path):
        from universal.files import disambiguated_filename

        (tmp_path / "hidden_pit.json").write_text("not json")
        with pytest.raises(ValueError, match="not readable JSON"):
            disambiguated_filename(str(tmp_path), {"name": "Hidden Pit", "aonid": 1}, "hazard")
