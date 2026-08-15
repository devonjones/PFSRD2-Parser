"""Tests for pfsrd2/affliction.py.

The corpus run is a weak check here: curses and diseases both parsed 0 errors
while 19 curses were being silently overwritten, so these pin the behaviours
that a clean run cannot see — the level badge variants, the stage/escalation
split, saves published without a DC, and the overwrite guard itself.
"""

import json

import pytest
from bs4 import BeautifulSoup

from pfsrd2.affliction import (
    FIELD_LABELS,
    _assert_no_unknown_labels,
    _extract_escalations,
    _extract_stages,
    _split_trailing_prose,
    _structure_fields,
    affliction_extract_pass,
    find_affliction,
    restructure_affliction_pass,
)
from universal.universal import edition_pass


def _soup(html):
    return BeautifulSoup(html, "html.parser")


def _stages(html, name="Test Affliction"):
    affliction = {"name": name}
    _extract_stages(affliction, _soup(html))
    return affliction.get("stages", [])


class TestLevelBadge:
    def test_a_numeric_badge_becomes_the_level(self):
        struct = restructure_affliction_pass(
            [{"name": "Droskar's Gloom", "subname": "Curse 6", "text": "<b>Effect</b> x"}], "curse"
        )
        assert struct["sections"][0]["level"] == 6

    def test_a_negative_level_is_kept(self):
        struct = restructure_affliction_pass(
            [{"name": "Minor Ill", "subname": "Disease -1", "text": "x"}], "disease"
        )
        assert struct["sections"][0]["level"] == -1

    def test_level_varies_is_recorded_not_invented(self):
        # Grave Curse publishes "Curse Level Varies" — the level depends on the
        # ritual that inflicted it. Defaulting it to 0 would be a fabrication.
        sb = restructure_affliction_pass(
            [{"name": "Grave Curse", "subname": "Curse Level Varies", "text": "x"}], "curse"
        )["sections"][0]
        assert sb["level_text"] == "Curse Level Varies"
        assert "level" not in sb

    def test_an_unrecognised_badge_fails_loudly(self):
        with pytest.raises(AssertionError, match="is neither a Curse level"):
            restructure_affliction_pass(
                [{"name": "Odd", "subname": "Curse Sometimes", "text": "x"}], "curse"
            )

    def test_a_missing_badge_fails_loudly(self):
        with pytest.raises(AssertionError, match="No level badge"):
            restructure_affliction_pass([{"name": "Odd", "subname": "", "text": "x"}], "curse")


class TestStatBlockLocation:
    def test_text_on_the_entry_is_used_directly(self):
        struct = restructure_affliction_pass(
            [{"name": "Plain", "subname": "Curse 1", "text": "<b>Effect</b> x"}], "curse"
        )
        assert struct["sections"][0]["text"] == "<b>Effect</b> x"

    def test_a_spoiler_warning_nests_the_stat_block_a_level_deeper(self):
        # Blightburn Sickness renders "may contain spoilers" as an h2 between
        # the h1 and the Legacy Content h3, so the text is two levels down.
        details = [
            {
                "name": "Blightburn Sickness",
                "subname": "Disease 15",
                "sections": [
                    {
                        "name": "This Disease may contain spoilers",
                        "sections": [{"name": "Legacy Content", "text": "<b>Onset</b> 1 day"}],
                    }
                ],
            }
        ]
        struct = restructure_affliction_pass(details, "disease")
        assert struct["sections"][0]["text"] == "<b>Onset</b> 1 day"

    def test_the_nested_carrier_keeps_its_name_after_the_text_is_taken(self):
        # The text must move out (or the unparsed block ships twice), but the
        # section itself must stay: edition_pass decides legacy vs remastered
        # by finding a section named "Legacy Content".
        details = [
            {
                "name": "Blightburn Sickness",
                "subname": "Disease 15",
                "sections": [
                    {
                        "name": "Spoilers",
                        "sections": [{"name": "Legacy Content", "text": "<b>Onset</b> 1 day"}],
                    }
                ],
            }
        ]
        struct = restructure_affliction_pass(details, "disease")
        spoiler = [s for s in struct["sections"] if s.get("name") == "Spoilers"][0]
        # The husk stays so edition_pass can still read its name; only the
        # text moves. remove_empty_sections_pass drops it later.
        assert spoiler["sections"][0]["name"] == "Legacy Content"
        assert "text" not in spoiler["sections"][0]

    def test_a_page_with_no_stat_block_text_fails_loudly(self):
        with pytest.raises(AssertionError, match="No stat block text"):
            restructure_affliction_pass(
                [{"name": "Empty", "subname": "Curse 1", "sections": [{"name": "Nothing"}]}],
                "curse",
            )


class TestStages:
    def test_stages_are_numbered_and_ordered(self):
        stages = _stages("<b>Stage 1</b> sickened 1 (1 day); <b>Stage 2</b> sickened 2 (1 day)")
        assert [s["stage"] for s in stages] == [1, 2]

    def test_the_trailing_duration_is_split_out(self):
        stage = _stages("<b>Stage 1</b> sickened 1 (1 day)")[0]
        assert stage["duration"] == "1 day"
        assert stage["effect"] == "sickened 1"

    def test_a_separator_after_the_duration_still_splits(self):
        # Every stage but the last carries a trailing ";", which defeated the
        # anchored duration match and left the paren inside the effect text.
        stage = _stages("<b>Stage 1</b> sickened 1 (1 day); <b>Stage 2</b> dead (1 day)")[0]
        assert stage["duration"] == "1 day"
        assert stage["effect"] == "sickened 1"

    def test_a_stage_without_a_duration_keeps_its_whole_effect(self):
        stage = _stages("<b>Stage 1</b> the victim dies")[0]
        assert stage["effect"] == "the victim dies"
        assert "duration" not in stage

    def test_links_inside_a_stage_are_harvested(self):
        stage = _stages(
            '<b>Stage 1</b> <a aonid="29" game-obj="Conditions">sickened</a> 1 (1 day)'
        )[0]
        assert [link["name"] for link in stage["links"]] == ["sickened"]

    def test_an_empty_stage_fails_loudly(self):
        with pytest.raises(AssertionError, match="no effect text"):
            _stages("<b>Stage 1</b>")

    def test_stages_that_do_not_run_from_one_fail_loudly(self):
        with pytest.raises(AssertionError, match="not a run from 1"):
            _stages("<b>Stage 2</b> sickened 1 (1 day)")


class TestEscalations:
    def test_a_later_curse_level_is_an_escalation_not_a_stage(self):
        # All-Consuming Hubris is "Curse 4" and publishes "Curse 5"/"Curse 6"
        # bolds. Reading those as stages would invent a staged affliction.
        affliction = {"name": "All-Consuming Hubris"}
        soup = _soup("<b>Curse 5</b> increase the spirit damage to 2d10.")
        _extract_escalations(affliction, soup, "curse")
        assert affliction["escalations"][0]["level"] == 5
        assert "stages" not in affliction

    def test_the_escalation_text_is_kept(self):
        affliction = {"name": "x"}
        _extract_escalations(affliction, _soup("<b>Disease 7</b> the onset halves."), "disease")
        assert affliction["escalations"][0]["effect"] == "the onset halves."

    def test_an_empty_escalation_fails_loudly(self):
        with pytest.raises(AssertionError, match="not understood"):
            _extract_escalations({"name": "x"}, _soup("<b>Curse 5</b>"), "curse")


class TestSavingThrow:
    def test_a_numeric_dc_is_structured(self):
        affliction = {"saving_throw": "DC 22 Fortitude"}
        _structure_fields(affliction)
        assert affliction["saving_throw"]["dc"] == 22

    def test_prose_mentioning_dc_without_a_number_is_not_treated_as_a_dc(self):
        # "with a high spell DC for a monster of its level" contains "DC" but
        # publishes no number; parsing it as one crashes on a broken DC.
        affliction = {"saving_throw": "Will save, with a high spell DC for a monster of its level"}
        _structure_fields(affliction)
        save = affliction["saving_throw"]
        assert "dc" not in save
        assert save["save_type"] == "Will"
        assert save["text"].startswith("Will save")

    def test_a_bare_save_name_keeps_its_type(self):
        affliction = {"saving_throw": "Fortitude; creatures with addictive exhaustion can't"}
        _structure_fields(affliction)
        assert affliction["saving_throw"]["save_type"] == "Fort"

    def test_trailing_separators_are_stripped_from_text_fields(self):
        affliction = {"effect": "you are cursed ;"}
        _structure_fields(affliction)
        assert affliction["effect"] == "you are cursed"


class TestTrailingProse:
    def test_the_last_field_does_not_swallow_the_description(self):
        # extract_bold_fields runs a value to the next bold, so Usage on a
        # curse with no stages otherwise absorbs the entire description.
        affliction = {"usage": "held in one hand<br/>The blade whispers to its wielder."}
        prose = _split_trailing_prose(affliction)
        assert affliction["usage"] == "held in one hand"
        assert prose == "The blade whispers to its wielder."

    def test_a_field_without_a_break_is_untouched(self):
        affliction = {"effect": "you are cursed"}
        assert _split_trailing_prose(affliction) == ""
        assert affliction["effect"] == "you are cursed"


class TestUnknownLabels:
    def test_an_unrecognised_bold_fails_loudly(self):
        with pytest.raises(AssertionError, match="Unknown bold label"):
            _assert_no_unknown_labels({"name": "x"}, ["Mystery Field"], "curse")

    def test_an_empty_bold_is_ignored(self):
        _assert_no_unknown_labels({"name": "x"}, [""], "curse")


SAMPLE = (
    '<span class="traituncommon"><a aonid="159" game-obj="Traits">Uncommon</a></span>'
    '<span class="trait"><a aonid="46" game-obj="Traits">Disease</a></span>'
    "<br/><b>Source</b> "
    '<a aonid="33" game-obj="Sources"><i>Pathfinder #155: Lord of the Black Sands pg. 73</i></a>'
    "<hr/>"
    "The crystals sicken those who linger."
    '<br/><b>Saving Throw</b> DC 20 <a aonid="1" game-obj="Rules">Fortitude</a>'
    "; <b>Onset</b> 1 day"
    '; <b>Stage 1</b> <a aonid="29" game-obj="Conditions">sickened</a> 1 (1 day)'
    "; <b>Stage 2</b> sickened 2 (1 day)"
)


def _details(text=SAMPLE, subname="Disease 15", wrap_section=False):
    entry = {"name": "Blightburn Sickness", "subname": subname, "sections": []}
    if wrap_section:
        entry["sections"] = [{"name": "Legacy Content", "type": "section", "text": text}]
    else:
        entry["text"] = text
    return [entry]


def _parsed(subtype="disease", **kwargs):
    struct = restructure_affliction_pass(_details(**kwargs), subtype)
    affliction_extract_pass(struct)
    return struct["sections"][0]


class TestExtractPass:
    """affliction_extract_pass wires every helper together.

    Tested through the whole pass rather than helper by helper: the first
    version of these tests exercised only the helpers, and 13 of 14 mutations
    to this function survived the suite.
    """

    def test_every_rarity_class_is_a_trait(self):
        # AoN marks rarity with traituncommon/traitrare, not plain "trait".
        assert [t["name"] for t in _parsed()["traits"]] == ["Uncommon", "Disease"]

    def test_trait_spans_do_not_survive_into_the_description(self):
        assert "Uncommon" not in _parsed()["description"]

    def test_an_affliction_with_no_traits_gets_no_key(self):
        text = '<b>Source</b> <a aonid="1" game-obj="Sources">Core pg. 1</a><br/>Prose.'
        assert "traits" not in _parsed(text=text)

    def test_the_source_is_structured(self):
        source = _parsed()["sources"][0]
        assert source["name"] == "Pathfinder #155: Lord of the Black Sands"
        assert source["page"] == 73

    def test_an_affliction_with_no_source_fails_loudly(self):
        with pytest.raises(AssertionError, match="No source found"):
            _parsed(text="<b>Onset</b> 1 day")

    def test_separators_do_not_bleed_into_the_output(self):
        # An <hr/> left in place becomes "---" once markdown runs.
        assert "<hr" not in json.dumps(_parsed())

    def test_stages_and_fields_are_both_extracted(self):
        # Pins the ordering the comment defends: run extract_bold_fields
        # before the stages and every Stage N becomes an unknown label.
        affliction = _parsed()
        assert affliction["saving_throw"]["dc"] == 20
        assert [s["stage"] for s in affliction["stages"]] == [1, 2]

    def test_field_values_are_flattened_and_their_links_kept(self):
        # A surviving <a> in a field value fails markdown validation later.
        text = (
            '<b>Source</b> <a aonid="1" game-obj="Sources">Core pg. 1</a>'
            '<br/><b>Effect</b> you are <a aonid="29" game-obj="Conditions">sickened</a> 1'
        )
        affliction = _parsed(text=text)
        assert affliction["effect"] == "you are sickened 1"
        assert "sickened" in [link["name"] for link in affliction["links"]]

    def test_the_unlabelled_prose_becomes_the_description(self):
        # <br/> survives until the later markdown pass; the prose is what matters.
        assert "The crystals sicken those who linger." in _parsed()["description"]

    def test_a_block_with_no_spare_prose_gets_no_description(self):
        # Otherwise every affliction ships a description of leftover punctuation.
        text = (
            '<b>Source</b> <a aonid="1" game-obj="Sources">Core pg. 1</a>' "<br/><b>Onset</b> 1 day"
        )
        assert "description" not in _parsed(text=text)

    def test_prose_a_field_swallowed_comes_back_into_the_description(self):
        # Usage is last in the block, so extract_bold_fields runs its value on
        # into the description that follows it.
        text = (
            '<b>Source</b> <a aonid="1" game-obj="Sources">Core pg. 1</a>'
            "<br/><b>Usage</b> held in one hand<br/>The blade whispers."
        )
        affliction = _parsed(subtype="curse", subname="Curse 3", text=text)
        assert affliction["usage"] == "held in one hand"
        assert "The blade whispers." in affliction["description"]

    def test_links_in_the_description_become_plain_text(self):
        # Surviving <a> tags fail markdown validation a thousand files later.
        text = (
            '<b>Source</b> <a aonid="1" game-obj="Sources">Core pg. 1</a>'
            '<br/>It inflicts <a aonid="29" game-obj="Conditions">sickened</a>.'
        )
        affliction = _parsed(text=text)
        assert affliction["description"] == "It inflicts sickened."
        assert "sickened" in [link["name"] for link in affliction["links"]]

    def test_a_label_consumed_before_the_check_still_fails(self):
        # The check reads a snapshot taken before extraction; reading the
        # residue instead would make a consumed label invisible by design.
        text = (
            '<b>Source</b> <a aonid="1" game-obj="Sources">Core pg. 1</a>'
            "<br/><b>Mystery</b> value"
        )
        with pytest.raises(AssertionError, match="Unknown bold label 'Mystery'"):
            _parsed(text=text)

    def test_an_escalation_label_of_the_other_type_is_unknown(self):
        text = (
            '<b>Source</b> <a aonid="1" game-obj="Sources">Core pg. 1</a>'
            "<br/><b>Curse 7</b> it worsens"
        )
        with pytest.raises(AssertionError, match="Unknown bold label"):
            _parsed(subtype="disease", text=text)


class TestFieldLabels:
    def test_the_label_set_is_closed(self):
        assert {
            "Saving Throw",
            "Onset",
            "Maximum Duration",
            "Effect",
            "Usage",
            "Special",
            "Tempted Curse",
        } == FIELD_LABELS


class TestEdition:
    """The stat block on a legacy page IS the "Legacy Content" section.

    Taking that section out of the tree — rather than just its text — leaves
    edition_pass nothing to read, and every legacy affliction silently ships
    as remastered. That was 39 of 99 files.
    """

    def test_the_legacy_marker_survives_the_text_being_taken(self):
        struct = restructure_affliction_pass(_details(wrap_section=True), "disease")
        assert edition_pass(struct["sections"]) == "legacy"

    def test_a_page_without_the_marker_is_remastered(self):
        struct = restructure_affliction_pass(_details(), "disease")
        assert edition_pass(struct["sections"]) == "remastered"


class TestAfflictionType:
    def test_a_badge_of_the_wrong_type_fails_loudly(self):
        # affliction_type comes from the command line; the badge is the only
        # thing in the HTML that can contradict it.
        with pytest.raises(AssertionError, match="is neither a Disease level"):
            restructure_affliction_pass(_details(subname="Curse 4"), "disease")

    def test_the_type_reaches_the_stat_block(self):
        assert _parsed(subtype="disease")["affliction_type"] == "disease"


class TestFindAffliction:
    def test_it_picks_the_affliction_section_not_the_first(self):
        struct = {"sections": [{"subtype": "other"}, {"subtype": "affliction", "name": "X"}]}
        assert find_affliction(struct)["name"] == "X"

    def test_a_struct_with_no_stat_block_fails_loudly(self):
        with pytest.raises(AssertionError, match="No affliction stat block found"):
            find_affliction({"name": "Ghoul Fever", "sections": [{"subtype": "other"}]})
