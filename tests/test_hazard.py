"""Tests for the hazard parser (pfsrd2/hazard.py)."""

import pytest
from bs4 import BeautifulSoup

from pfsrd2.hazard import (
    FIELD_LABELS,
    _component_label,
    _extract_component_durability,
    _extract_traits,
    _parse_defenses,
    _structure_fields,
    _unwrap_map_area_refs,
    hazard_extract_pass,
    restructure_hazard_pass,
)

TRAITS = (
    '<span class="trait"><a game-obj="Traits" aonid="105">Mechanical</a></span>'
    '<span class="traituncommon"><a game-obj="Traits" aonid="1">Uncommon</a></span>'
)

STAT_BLOCK = (
    TRAITS + "<br/>"
    '<b>Source</b> <a game-obj="Sources" aonid="1"><i>Core Rulebook pg. 522</i></a><br/>'
    "<b>Complexity</b> Simple<br/>"
    "<b>Stealth</b> DC 18<br/>"
    "<b>Description</b> A wooden trapdoor covers a pit.<hr/>"
    '<b>Disable</b> <a game-obj="Skills" aonid="17">Thievery</a> DC 12<br/>'
    "<b>AC</b> 10, <b>Fort</b> +1, <b>Ref</b> +3<br/>"
    "<b>Trapdoor Hardness</b> 3, <b>Trapdoor HP</b> 12 (BT 6); "
    "<b>Immunities</b> critical hits, object immunities<br/>"
    '<b>Pitfall</b> <span class="action" title="Reaction">[reaction]</span> '
    "<b>Trigger</b> A creature walks onto the trapdoor. "
    "<b>Effect</b> The creature falls in.<hr/>"
    "<b>Reset</b> The trapdoor must be reset manually."
)


def _details(text=STAT_BLOCK, subname="Hazard 0", wrap_section=True):
    """Shape parse_universal produces, in both published layouts."""
    entry = {
        "name": '<a game-obj="Hazards" aonid="1">Hidden Pit</a>',
        "subname": subname,
        "type": "section",
        "sections": [],
    }
    if wrap_section:
        entry["sections"] = [{"name": "Legacy Content", "type": "section", "text": text}]
    else:
        entry["text"] = text
    return [entry]


def _parsed(**kwargs):
    struct = restructure_hazard_pass(_details(**kwargs))
    hazard_extract_pass(struct)
    return struct["sections"][0]


class TestRestructure:
    def test_name_and_level_from_the_badge(self):
        struct = restructure_hazard_pass(_details())
        assert struct["name"] == "Hidden Pit"
        assert struct["sections"][0]["level"] == 0

    def test_negative_level(self):
        struct = restructure_hazard_pass(_details(subname="Hazard -1"))
        assert struct["sections"][0]["level"] == -1

    def test_remastered_layout_carries_text_on_the_entry(self):
        # Legacy wraps the stat block in a section; remastered does not.
        struct = restructure_hazard_pass(_details(wrap_section=False))
        assert struct["sections"][0]["text"] == STAT_BLOCK

    def test_sections_key_always_present(self):
        # The universal passes walk section trees unconditionally.
        struct = restructure_hazard_pass(_details())
        assert struct["sections"][0]["sections"] == []

    def test_missing_level_fails_loudly(self):
        with pytest.raises(AssertionError, match="No hazard level"):
            restructure_hazard_pass(_details(subname=""))

    def test_missing_stat_block_fails_loudly(self):
        details = _details()
        details[0]["sections"] = []
        with pytest.raises(AssertionError, match="No stat block text"):
            restructure_hazard_pass(details)


class TestTraits:
    def test_every_rarity_class_is_a_trait(self):
        # AoN marks rarity with traituncommon/traitrare/traitunique, not "trait".
        hazard = {}
        bs = BeautifulSoup(TRAITS, "html.parser")
        _extract_traits(hazard, bs)
        assert [t["name"] for t in hazard["traits"]] == ["Mechanical", "Uncommon"]

    def test_trait_spans_are_consumed(self):
        hazard = {}
        bs = BeautifulSoup(TRAITS, "html.parser")
        _extract_traits(hazard, bs)
        assert bs.find("span") is None


class TestFields:
    def test_labelled_fields(self):
        hazard = _parsed()
        assert hazard["complexity"] == "Simple"
        assert hazard["stealth"] == "DC 18"
        assert hazard["description"] == "A wooden trapdoor covers a pit."
        assert hazard["disable"] == "Thievery DC 12"

    def test_reset_survives_the_ability_split(self):
        # Abilities take everything from the first non-field bold onward, so a
        # trailing Reset is the field most at risk of being swallowed.
        assert _parsed()["reset"] == "The trapdoor must be reset manually."

    def test_separators_do_not_bleed_into_values(self):
        # An <hr> left in renders as "---" once markdown runs.
        assert "---" not in _parsed()["description"]

    def test_numeric_fields_become_integers(self):
        assert _parsed()["ac"] == 10

    def test_saves(self):
        saves = {s["name"]: s["value"] for s in _parsed()["saves"]}
        assert saves == {"fortitude": 1, "reflex": 3}

    def test_links_are_extracted_and_tags_unwrapped(self):
        hazard = _parsed()
        assert "<a" not in hazard["disable"]
        assert any(link["name"] == "Thievery" for link in hazard["links"])


class TestDefenses:
    def test_immunities(self):
        assert [i["name"] for i in _parsed()["immunities"]] == [
            "critical hits",
            "object immunities",
        ]

    def test_valued_weakness_splits_name_from_value(self):
        entries = _parse_defenses("cold 5, fire 10", "weakness")
        assert [(e["name"], e["value"]) for e in entries] == [("cold", 5), ("fire", 10)]

    def test_unvalued_entry_has_no_value(self):
        entry = _parse_defenses("precision damage", "immunity")[0]
        assert entry["name"] == "precision damage"
        assert "value" not in entry

    def test_empty_parts_are_skipped(self):
        # A trailing separator otherwise yields a nameless entry, which
        # remove_empty_fields later strips into an invalid object.
        entries = _parse_defenses("fire, ", "immunity")
        assert [e["name"] for e in entries] == ["fire"]


class TestComponents:
    def test_named_component_durability(self):
        component = _parsed()["components"][0]
        assert component["name"] == "Trapdoor"
        assert (component["hardness"], component["hp"], component["bt"]) == (3, 12, 6)

    def test_component_stats_do_not_become_the_hazards_own(self):
        hazard = _parsed()
        assert "hardness" not in hazard and "hp" not in hazard

    @pytest.mark.parametrize(
        "label,expected",
        [
            ("Trapdoor Hardness", ("Trapdoor", "Hardness")),
            ("Scythe Blade HP", ("Scythe Blade", "HP")),
            ("HP (per mannequin)", ("per mannequin", "HP")),
            ("Hardness", None),
            ("Complexity", None),
        ],
    )
    def test_component_label_detection(self, label, expected):
        assert _component_label(label) == expected

    def test_bare_durability_belongs_to_the_hazard(self):
        hazard = {}
        bs = BeautifulSoup("<b>Hardness</b> 8<br/><b>HP</b> 32 (BT 16)", "html.parser")
        _extract_component_durability(hazard, bs)
        assert "components" not in hazard


class TestAbilities:
    def test_ability_with_action_type_trigger_and_effect(self):
        ability = _parsed()["abilities"][0]
        assert ability["name"] == "Pitfall"
        assert ability["action_type"]["name"] == "Reaction"
        assert ability["trigger"] == "A creature walks onto the trapdoor."
        assert ability["effect"] == "The creature falls in."

    def test_field_labels_are_not_treated_as_abilities(self):
        assert [a["name"] for a in _parsed()["abilities"]] == ["Pitfall"]

    def test_a_hazard_with_no_abilities_is_fine(self):
        text = (
            '<b>Source</b> <a game-obj="Sources" aonid="1"><i>Core pg. 1</i></a><br/>'
            "<b>Complexity</b> Simple<br/><b>Stealth</b> DC 18"
        )
        assert "abilities" not in _parsed(text=text)


class TestFieldLabels:
    def test_the_label_set_is_closed(self):
        # The whole field/ability split rests on this staying closed; Source is
        # deliberately absent because it has its own extractor.
        assert "Source" not in FIELD_LABELS
        for label in ("Complexity", "Stealth", "Disable", "Reset", "Routine", "AC"):
            assert label in FIELD_LABELS


class TestStructureFields:
    def test_non_numeric_stat_is_dropped_rather_than_kept_as_text(self):
        hazard = {"ac": "—"}
        _structure_fields(hazard)
        assert "ac" not in hazard


class TestMapAreaRefs:
    def test_bolded_area_ref_becomes_plain_text(self):
        # Adventure hazards bold the map square mid-sentence; every other bold
        # is a label, so leaving it makes the ability parser read "C2" as one.
        bs = BeautifulSoup("A creature enters from area <b>C2</b> or <b>C4</b>.", "html.parser")
        _unwrap_map_area_refs(bs)
        assert bs.find("b") is None
        assert bs.get_text() == "A creature enters from area C2 or C4."

    def test_real_labels_keep_their_bold(self):
        bs = BeautifulSoup("<b>Trigger</b> x <b>Effect</b> y", "html.parser")
        _unwrap_map_area_refs(bs)
        assert [b.get_text() for b in bs.find_all("b")] == ["Trigger", "Effect"]

    def test_area_ref_inside_a_trigger_does_not_split_the_ability(self):
        text = (
            '<b>Source</b> <a game-obj="Sources" aonid="1"><i>Core pg. 1</i></a><br/>'
            "<b>Disorient</b> "
            '<span class="action" title="Reaction">[reaction]</span> '
            "<b>Trigger</b> A creature enters from area <b>C2</b> or <b>C4</b>. "
            "<b>Effect</b> Reality shifts."
        )
        ability = _parsed(text=text)["abilities"][0]
        assert ability["name"] == "Disorient"
        assert ability["trigger"] == "A creature enters from area C2 or C4."
