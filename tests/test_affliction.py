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
    _assert_no_unknown_labels,
    _assert_safe_overwrite,
    _extract_escalations,
    _extract_stages,
    _split_trailing_prose,
    _structure_fields,
    restructure_affliction_pass,
)


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
        with pytest.raises(AssertionError, match="neither a number nor"):
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

    def test_the_nested_carrier_is_removed_from_its_parent(self):
        # If it is only copied, the whole unparsed stat block ships a second
        # time inside the spoiler section and fails markdown validation.
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
        assert spoiler["sections"] == []

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
        _extract_escalations(affliction, soup)
        assert affliction["escalations"][0]["level"] == 5
        assert "stages" not in affliction

    def test_the_escalation_text_is_kept(self):
        affliction = {"name": "x"}
        _extract_escalations(affliction, _soup("<b>Disease 7</b> the onset halves."))
        assert affliction["escalations"][0]["effect"] == "the onset halves."

    def test_an_empty_escalation_fails_loudly(self):
        with pytest.raises(AssertionError, match="not understood"):
            _extract_escalations({"name": "x"}, _soup("<b>Curse 5</b>"))


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
        _split_trailing_prose(affliction)
        assert affliction["usage"] == "held in one hand"
        assert affliction["_trailing_prose"] == "The blade whispers to its wielder."

    def test_a_field_without_a_break_is_untouched(self):
        affliction = {"effect": "you are cursed"}
        _split_trailing_prose(affliction)
        assert affliction["effect"] == "you are cursed"
        assert "_trailing_prose" not in affliction


class TestUnknownLabels:
    def test_an_unrecognised_bold_fails_loudly(self):
        with pytest.raises(AssertionError, match="Unknown bold label"):
            _assert_no_unknown_labels({"name": "x"}, _soup("<b>Mystery Field</b> value"))

    def test_an_empty_bold_is_ignored(self):
        _assert_no_unknown_labels({"name": "x"}, _soup("<b></b>"))


class TestOverwriteGuard:
    """AoN publishes 19 curses twice; the guard must allow that and only that."""

    def _write(self, tmp_path, struct):
        path = tmp_path / "curse.json"
        path.write_text(json.dumps(struct))
        return str(path)

    def test_an_identical_body_under_a_different_aonid_passes(self, tmp_path):
        existing = {"aonid": 15, "game-id": "a", "name": "Curse of Nightmares", "level": 2}
        path = self._write(tmp_path, existing)
        _assert_safe_overwrite(path, {**existing, "aonid": 77, "game-id": "b"})

    def test_a_different_body_under_a_different_aonid_fails_loudly(self, tmp_path):
        path = self._write(tmp_path, {"aonid": 15, "name": "Shared Name", "level": 2})
        with pytest.raises(AssertionError, match="would overwrite a different affliction"):
            _assert_safe_overwrite(path, {"aonid": 77, "name": "Shared Name", "level": 9})

    def test_rewriting_our_own_output_is_allowed(self, tmp_path):
        # Reruns are routine; the guard must not fire when the parser changes
        # its own output for the same aonid.
        path = self._write(tmp_path, {"aonid": 15, "name": "x", "level": 2})
        _assert_safe_overwrite(path, {"aonid": 15, "name": "x", "level": 3})

    def test_a_fresh_path_is_allowed(self, tmp_path):
        _assert_safe_overwrite(str(tmp_path / "missing.json"), {"aonid": 1, "name": "x"})
