"""Tests for the hazard parser (pfsrd2/hazard.py)."""

import json
import os

import pytest
from bs4 import BeautifulSoup

from pfsrd2.hazard import (
    FIELD_LABELS,
    _component_label,
    _extract_component_durability,
    _extract_sources,
    _extract_traits,
    _hazard_filename,
    _hazard_trait_pre_process,
    _parse_defenses,
    _structure_fields,
    _unwrap_field_links,
    _unwrap_inline_refs,
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
        assert hazard["stealth"]["dc"] == 18
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
        assert saves == {"Fort": 1, "Ref": 3}

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

    def test_trailing_separator_is_trimmed(self):
        # A trailing separator otherwise yields a nameless entry, which
        # remove_empty_fields later strips into an invalid object.
        assert [e["name"] for e in _parse_defenses("fire, ", "immunity")] == ["fire"]

    def test_a_gap_between_separators_fails_loudly(self):
        # Malformed HTML, not a routine trailing separator.
        with pytest.raises(AssertionError, match="Empty entry"):
            _parse_defenses("fire,, cold", "immunity")


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
    def test_unparseable_stat_fails_loudly(self):
        # Dropping it would ship a hazard missing a published AC and report success.
        with pytest.raises(AssertionError, match="no number in it"):
            _structure_fields({"ac": "—", "name": "Hidden Pit"})

    def test_unparseable_save_fails_loudly(self):
        with pytest.raises(AssertionError, match="no number in it"):
            _structure_fields({"fort": "—", "name": "Hidden Pit"})

    def test_break_threshold_is_read_out_of_hp(self):
        # BT is never its own bold label; it rides inside HP as "90 (BT 45)".
        hazard = {"hp": "90 (BT 45)", "name": "Hidden Pit"}
        _structure_fields(hazard)
        assert (hazard["hp"], hazard["bt"]) == (90, 45)

    def test_hp_without_a_break_threshold_gets_no_bt(self):
        hazard = {"hp": "32", "name": "Hidden Pit"}
        _structure_fields(hazard)
        assert "bt" not in hazard


class TestInlineRefs:
    def test_bolded_area_ref_becomes_plain_text(self):
        # Adventure hazards bold the map square mid-sentence; every other bold
        # is a label, so leaving it makes the ability parser read "C2" as one.
        bs = BeautifulSoup("A creature enters from area <b>C2</b> or <b>C4</b>.", "html.parser")
        _unwrap_inline_refs(bs)
        assert bs.find("b") is None
        assert bs.get_text() == "A creature enters from area C2 or C4."

    def test_a_bold_starting_a_run_is_left_for_the_parser_to_fail_on(self):
        # Shape alone is not enough: a bold "C2" with nothing before it is a
        # label this parser has not seen, and hiding it would hide that.
        bs = BeautifulSoup("<b>C2</b> some value", "html.parser")
        _unwrap_inline_refs(bs)
        assert bs.find("b") is not None

    def test_real_labels_keep_their_bold(self):
        bs = BeautifulSoup("<b>Trigger</b> x <b>Effect</b> y", "html.parser")
        _unwrap_inline_refs(bs)
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


class TestResultBlocks:
    """Degrees of success belong to the ability that rolled the save."""

    ABILITY = (
        '<b>Source</b> <a game-obj="Sources" aonid="1"><i>Core pg. 1</i></a><br/>'
        "<b>Pitfall</b> "
        '<span class="action" title="Reaction">[reaction]</span> '
        "<b>Effect</b> The creature falls in. "
        "<b>Critical Success</b> No damage. "
        "<b>Success</b> Half damage. "
        "<b>Failure</b> Full damage. "
        "<b>Critical Failure</b> Double damage."
    )

    def test_result_labels_do_not_become_their_own_abilities(self):
        assert [a["name"] for a in _parsed(text=self.ABILITY)["abilities"]] == ["Pitfall"]

    def test_each_degree_lands_on_the_ability(self):
        ability = _parsed(text=self.ABILITY)["abilities"][0]
        assert ability["critical_success"] == "No damage."
        assert ability["success"] == "Half damage."
        assert ability["failure"] == "Full damage."
        assert ability["critical_failure"] == "Double damage."


class TestTraitPreProcess:
    def test_known_trait_is_left_alone(self, monkeypatch):
        monkeypatch.setattr("pfsrd2.hazard.fetch_trait_by_name", lambda curs, name: {"name": name})
        trait = {"name": "magical"}
        _hazard_trait_pre_process(trait, None, None)
        assert trait == {"name": "magical"}

    def test_unknown_valued_trait_is_split(self, monkeypatch):
        # "thrown 10 feet" is one string in the source; the table knows "thrown".
        monkeypatch.setattr(
            "pfsrd2.hazard.fetch_trait_by_name",
            lambda curs, name: {"name": name} if name == "thrown" else None,
        )
        trait = {"name": "thrown 10 feet"}
        _hazard_trait_pre_process(trait, None, None)
        assert (trait["name"], trait["value"]) == ("thrown", "10 feet")

    def test_a_split_that_does_not_resolve_is_rolled_back(self, monkeypatch):
        # Otherwise an unknown two-word trait is reshaped into something
        # plausible and the DB never gets to reject it.
        monkeypatch.setattr("pfsrd2.hazard.fetch_trait_by_name", lambda curs, name: None)
        trait = {"name": "utter nonsense"}
        _hazard_trait_pre_process(trait, None, None)
        assert trait == {"name": "utter nonsense"}

    def test_unknown_single_word_trait_is_left_for_the_db_to_reject(self, monkeypatch):
        monkeypatch.setattr("pfsrd2.hazard.fetch_trait_by_name", lambda curs, name: None)
        trait = {"name": "nonsense"}
        _hazard_trait_pre_process(trait, None, None)
        assert trait == {"name": "nonsense"}


class TestSources:
    def test_source_is_extracted(self):
        assert _parsed()["sources"][0]["name"] == "Core Rulebook"

    def test_the_source_page_is_kept(self):
        assert _parsed()["sources"][0]["page"] == 522

    def test_a_hazard_with_no_source_fails_loudly(self):
        hazard, bs = {"name": "Hidden Pit"}, BeautifulSoup(
            "<b>Complexity</b> Simple", "html.parser"
        )
        with pytest.raises(AssertionError, match="No source found"):
            _extract_sources(hazard, bs)


class TestResidue:
    def test_prose_the_ability_parser_could_not_claim_is_kept(self):
        text = (
            '<b>Source</b> <a game-obj="Sources" aonid="1"><i>Core pg. 1</i></a><br/>'
            "<b>Pitfall</b> "
            '<span class="action" title="Reaction">[reaction]</span> '
            "<b>Effect</b> The creature falls in.<br/>"
            "The pit is lined with spikes."
        )
        assert "The pit is lined with spikes." in _parsed(text=text)["text"]

    def test_a_fully_claimed_block_leaves_no_text(self):
        # Otherwise every hazard would carry a text key of leftover punctuation.
        assert "text" not in _parsed()


class TestFilenames:
    def _write(self, tmp_path, aonid, name="Glyph of Warding"):
        struct = {"name": name, "aonid": aonid, "game-obj": "Hazards"}
        path = _hazard_filename(str(tmp_path), struct)
        with open(path, "w") as fp:
            json.dump(struct, fp)
        return os.path.basename(path)

    def test_a_lone_hazard_keeps_the_plain_name(self, tmp_path):
        assert self._write(tmp_path, 263) == "glyph_of_warding.json"

    def test_two_hazards_sharing_a_name_both_survive(self, tmp_path):
        # Pathfinder #184 publishes two "Glyph of Warding" (levels 13 and 14);
        # one plain path silently loses whichever is written first.
        self._write(tmp_path, 263)
        second = self._write(tmp_path, 266)
        assert sorted(os.listdir(tmp_path)) == [
            "glyph_of_warding_263.json",
            "glyph_of_warding_266.json",
        ]
        assert second == "glyph_of_warding_266.json"

    def test_the_same_hazard_rewrites_its_own_file(self, tmp_path):
        self._write(tmp_path, 263)
        self._write(tmp_path, 263)
        assert os.listdir(tmp_path) == ["glyph_of_warding.json"]

    def test_three_hazards_sharing_a_name_all_take_a_suffix(self, tmp_path):
        for aonid in (263, 266, 999):
            self._write(tmp_path, aonid)
        assert sorted(os.listdir(tmp_path)) == [
            "glyph_of_warding_263.json",
            "glyph_of_warding_266.json",
            "glyph_of_warding_999.json",
        ]

    def test_an_unreadable_existing_file_says_which_one(self, tmp_path):
        with open(tmp_path / "glyph_of_warding.json", "w") as fp:
            fp.write("not json")
        with pytest.raises(ValueError, match="not readable JSON"):
            self._write(tmp_path, 263)

    def test_collision_naming_is_independent_of_order(self, tmp_path):
        for order in ([263, 266, 999], [999, 266, 263], [266, 999, 263]):
            for f in os.listdir(tmp_path):
                os.remove(os.path.join(tmp_path, f))
            for aonid in order:
                self._write(tmp_path, aonid)
            assert sorted(os.listdir(tmp_path)) == [
                "glyph_of_warding_263.json",
                "glyph_of_warding_266.json",
                "glyph_of_warding_999.json",
            ], order


class TestFieldFlattening:
    def test_action_spans_in_a_field_become_bracket_text(self):
        # A Routine or Disable can name an action inline, and the markdown
        # pass accepts no tags.
        hazard = {"routine": '<span class="action" title="Reaction">[reaction]</span> then strike'}
        _unwrap_field_links(hazard)
        assert hazard["routine"] == "[reaction] then strike"

    def test_links_in_a_field_are_collected_and_unwrapped(self):
        hazard = {"disable": '<a game-obj="Skills" aonid="17">Thievery</a> DC 12'}
        _unwrap_field_links(hazard)
        assert hazard["disable"] == "Thievery DC 12"
        assert [link["name"] for link in hazard["links"]] == ["Thievery"]

    def test_a_field_with_no_markup_is_left_alone(self):
        hazard = {"complexity": "Simple"}
        _unwrap_field_links(hazard)
        assert hazard == {"complexity": "Simple"}


class TestAbilityLeftovers:
    def test_prose_between_abilities_is_not_dropped(self):
        # _extract_abilities removes every node from the first ability bold
        # onward; anything the ability parser cannot claim has to come back.
        text = (
            '<b>Source</b> <a game-obj="Sources" aonid="1"><i>Core pg. 1</i></a><br/>'
            "<b>Pitfall</b> "
            '<span class="action" title="Reaction">[reaction]</span> '
            "<b>Effect</b> The creature falls in.<br/>"
            "Both traps share one trigger."
        )
        hazard = _parsed(text=text)
        assert hazard["abilities"][0]["name"] == "Pitfall"
        assert "Both traps share one trigger." in hazard["text"]


class TestStatQualifiers:
    def test_a_per_component_qualifier_is_kept(self):
        # "22 HP per instrument" — taking only the integer drops the qualifier.
        hazard = {"hp": "22 per instrument", "name": "Hidden Pit"}
        _structure_fields(hazard)
        assert (hazard["hp"], hazard["hp_note"]) == (22, "per instrument")

    def test_a_qualifier_alongside_a_break_threshold(self):
        hazard = {"hp": "22 per instrument (BT 11)", "name": "Hidden Pit"}
        _structure_fields(hazard)
        assert (hazard["hp"], hazard["bt"], hazard["hp_note"]) == (22, 11, "per instrument")

    def test_a_parenthetical_qualifier_on_hardness(self):
        hazard = {"hardness": "9 (wall)", "name": "Hidden Pit"}
        _structure_fields(hazard)
        assert (hazard["hardness"], hazard["hardness_note"]) == (9, "(wall)")

    def test_a_plain_value_gets_no_note(self):
        hazard = {"hp": "32 (BT 16)", "name": "Hidden Pit"}
        _structure_fields(hazard)
        assert "hp_note" not in hazard


class TestUniversalMonsterAbilityEnrichment:
    def test_the_db_pass_is_wired_into_the_pipeline(self):
        # A hazard ability can name a universal monster ability; without this
        # pass it ships with an empty game-id and the schema rejects it.
        import inspect

        from pfsrd2 import hazard

        source = inspect.getsource(hazard.parse_hazard)
        assert "monster_ability_db_pass(struct)" in source
        assert source.index("game_id_pass(struct)") < source.index("monster_ability_db_pass")


class TestSaveOrder:
    def test_saves_are_ordered_fort_ref_will(self):
        hazard = {"fort": "+1", "ref": "+3", "will": "+5", "name": "Hidden Pit"}
        _structure_fields(hazard)
        assert [s["name"] for s in hazard["saves"]] == ["Fort", "Ref", "Will"]

    def test_a_partial_set_keeps_that_order(self):
        hazard = {"will": "+5", "fort": "+1", "name": "Hidden Pit"}
        _structure_fields(hazard)
        assert [s["name"] for s in hazard["saves"]] == ["Fort", "Will"]


class TestWiderInlineRefs:
    @pytest.mark.parametrize("ref", ["C2", "B4a", "K13", "41", "3"])
    def test_reference_shapes_are_demoted_mid_sentence(self, ref):
        # Map squares, sub-lettered rooms, DCs and numbered effect entries are
        # all bolded mid-sentence by the source.
        bs = BeautifulSoup(f"a creature in area <b>{ref}</b> takes damage", "html.parser")
        _unwrap_inline_refs(bs)
        assert bs.find("b") is None

    @pytest.mark.parametrize("label", ["Trigger", "Effect", "Reset", "Melee"])
    def test_word_labels_keep_their_bold(self, label):
        bs = BeautifulSoup(f"text <b>{label}</b> more", "html.parser")
        _unwrap_inline_refs(bs)
        assert bs.find("b") is not None


class TestDuplicateLabels:
    def test_a_repeated_label_fails_loudly(self):
        # extract_bold_fields assigns rather than accumulates, so the second
        # value silently replaces the first — and a component's HP worn by the
        # hazard reads as plausible data, not as a failure.
        text = (
            '<b>Source</b> <a game-obj="Sources" aonid="1"><i>Core pg. 1</i></a><br/>'
            "<b>HP</b> 54 (BT 27)<br/><b>HP</b> 30"
        )
        with pytest.raises(AssertionError, match="appears twice"):
            _parsed(text=text)

    def test_the_same_label_on_a_named_part_is_fine(self):
        text = (
            '<b>Source</b> <a game-obj="Sources" aonid="1"><i>Core pg. 1</i></a><br/>'
            "<b>HP</b> 54 (BT 27)<br/><b>Reflection HP</b> 30"
        )
        hazard = _parsed(text=text)
        assert (hazard["hp"], hazard["bt"]) == (54, 27)
        assert hazard["components"][0]["hp"] == 30


class TestComponentDefences:
    def test_a_component_carries_its_own_ac_saves_and_immunities(self):
        text = (
            '<b>Source</b> <a game-obj="Sources" aonid="1"><i>Core pg. 1</i></a><br/>'
            "<b>AC</b> 21, <b>Fort</b> +17<br/>"
            "<b>Reflection AC</b> 24; <b>Reflection Fort</b> +11; "
            "<b>Reflection Immunities</b> object immunities"
        )
        hazard = _parsed(text=text)
        assert hazard["ac"] == 21
        assert [(s["name"], s["value"]) for s in hazard["saves"]] == [("Fort", 17)]
        component = hazard["components"][0]
        assert component["name"] == "Reflection"
        assert component["ac"] == 24
        assert [(s["name"], s["value"]) for s in component["saves"]] == [("Fort", 11)]
        assert [i["name"] for i in component["immunities"]] == ["object immunities"]


class TestComponentQualifiers:
    def test_a_component_keeps_its_qualifier_and_break_threshold(self):
        text = (
            '<b>Source</b> <a game-obj="Sources" aonid="1"><i>Core pg. 1</i></a><br/>'
            "<b>Spider HP</b> 40 per spider (BT 20)"
        )
        component = _parsed(text=text)["components"][0]
        assert (component["hp"], component["bt"], component["hp_note"]) == (40, 20, "per spider")

    def test_a_plain_component_stat_gets_no_note(self):
        text = (
            '<b>Source</b> <a game-obj="Sources" aonid="1"><i>Core pg. 1</i></a><br/>'
            "<b>Trapdoor Hardness</b> 3"
        )
        component = _parsed(text=text)["components"][0]
        assert component["hardness"] == 3 and "hardness_note" not in component

    def test_a_signed_value_leaves_no_note(self):
        # The sign belongs to the number; "+11" must not yield a note of "+".
        text = (
            '<b>Source</b> <a game-obj="Sources" aonid="1"><i>Core pg. 1</i></a><br/>'
            "<b>Reflection Fort</b> +11"
        )
        component = _parsed(text=text)["components"][0]
        assert [(s["name"], s["value"]) for s in component["saves"]] == [("Fort", 11)]
        assert not any(k.endswith("_note") for k in component)


class TestSplitComponentGuard:
    def test_a_component_split_across_two_bolds_fails_loudly(self):
        # "<b>Spout</b> HP 32" reads as an ability named Spout whose body is a
        # stat line; silently it becomes junk and the component loses its stats.
        text = (
            '<b>Source</b> <a game-obj="Sources" aonid="1"><i>Core pg. 1</i></a><br/>'
            "<b>Spout</b> HP 32 (BT 16);"
        )
        with pytest.raises(AssertionError, match="component stat in its body"):
            _parsed(text=text)

    def test_a_qualifier_in_the_bold_label_fails_loudly(self):
        # The other half of the same split: "<b>HP (per mannequin)</b> 70"
        # puts the stat in the ability's name rather than its body.
        text = (
            '<b>Source</b> <a game-obj="Sources" aonid="1"><i>Core pg. 1</i></a><br/>'
            "<b>HP (per mannequin)</b> 70 (BT 35);"
        )
        with pytest.raises(AssertionError, match="component stat in its name"):
            _parsed(text=text)

    def test_the_joined_form_is_a_component(self):
        text = (
            '<b>Source</b> <a game-obj="Sources" aonid="1"><i>Core pg. 1</i></a><br/>'
            "<b>Spout HP</b> 32 (BT 16);"
        )
        component = _parsed(text=text)["components"][0]
        assert (component["name"], component["hp"], component["bt"]) == ("Spout", 32, 16)

    def test_a_real_ability_is_untouched(self):
        text = (
            '<b>Source</b> <a game-obj="Sources" aonid="1"><i>Core pg. 1</i></a><br/>'
            "<b>Pitfall</b> "
            '<span class="action" title="Reaction">[reaction]</span> '
            "<b>Effect</b> The creature falls in."
        )
        assert _parsed(text=text)["abilities"][0]["name"] == "Pitfall"


class TestDuplicateComponentLabels:
    def test_a_repeated_component_stat_fails_loudly(self):
        # Same silent-overwrite class the hazard-level guard catches.
        text = (
            '<b>Source</b> <a game-obj="Sources" aonid="1"><i>Core pg. 1</i></a><br/>'
            "<b>Spout HP</b> 32<br/><b>Spout HP</b> 40"
        )
        with pytest.raises(AssertionError, match="appears twice on hazard"):
            _parsed(text=text)

    def test_different_stats_on_one_component_are_fine(self):
        text = (
            '<b>Source</b> <a game-obj="Sources" aonid="1"><i>Core pg. 1</i></a><br/>'
            "<b>Spout Hardness</b> 8, <b>Spout HP</b> 32"
        )
        component = _parsed(text=text)["components"][0]
        assert (component["hardness"], component["hp"]) == (8, 32)

    def test_the_same_stat_on_two_components_is_fine(self):
        text = (
            '<b>Source</b> <a game-obj="Sources" aonid="1"><i>Core pg. 1</i></a><br/>'
            "<b>Spout HP</b> 32, <b>Trapdoor HP</b> 60"
        )
        assert [c["hp"] for c in _parsed(text=text)["components"]] == [32, 60]


class TestAttacks:
    """Melee/Ranged are Strikes, modelled the way creatures model them."""

    SOURCE = '<b>Source</b> <a game-obj="Sources" aonid="1"><i>Core pg. 1</i></a><br/>'

    def test_a_strike_becomes_an_attack_not_an_ability(self):
        text = (
            self.SOURCE + "<b>Melee</b> "
            '<span class="action" title="Single Action">[one-action]</span> '
            "clockwork fist +29, <b>Damage</b> 2d10+18 bludgeoning"
        )
        hazard = _parsed(text=text)
        assert "abilities" not in hazard
        attack = hazard["attacks"][0]
        assert attack["weapon"] == "clockwork fist"
        assert attack["attack_type"] == "melee"
        assert attack["bonus"]["bonuses"] == [29]
        assert attack["damage"][0]["formula"] == "2d10+18"

    def test_a_ranged_strike_keeps_its_traits(self):
        text = (
            self.SOURCE + "<b>Ranged</b> eye beam +20 "
            '(<a game-obj="Traits" aonid="102">divine</a>, '
            '<a game-obj="Traits" aonid="248">range 120 feet</a>), '
            "<b>Damage</b> 4d6 fire"
        )
        attack = _parsed(text=text)["attacks"][0]
        assert attack["attack_type"] == "ranged"
        # Attacks are pulled out before the ability parser unwraps the links,
        # so the shared creature parser reads the traits off the live markup.
        # The magnitude is split off later, by trait_db_pass.
        assert [t["name"] for t in attack["traits"]] == ["divine", "range 120 feet"]

    def test_a_strike_published_whole_is_parsed_the_creature_way(self):
        # 14 attack lines across 11 hazards put the damage on the same line.
        text = self.SOURCE + "<b>Melee</b> water jet +11, Damage 2d8 piercing"
        attack = _parsed(text=text)["attacks"][0]
        assert (attack["weapon"], attack["damage"][0]["damage_type"]) == ("water jet", "piercing")

    def test_a_strike_that_resolves_to_an_effect(self):
        # "jaws +17, Effect devour" — creatures model this as damage carrying
        # the effect text rather than a formula.
        text = self.SOURCE + "<b>Melee</b> jaws +17, <b>Effect</b> the target is devoured"
        attack = _parsed(text=text)["attacks"][0]
        assert attack["weapon"] == "jaws"
        assert attack["damage"][0]["effect"] == "the target is devoured"

    def test_a_strike_with_neither_damage_nor_effect_fails_loudly(self):
        text = self.SOURCE + "<b>Melee</b> stalactite +16"
        with pytest.raises(AssertionError, match="Failed to parse"):
            _parsed(text=text)

    def test_a_trait_appearing_twice_is_kept_once(self):
        # A trait named twice on one line is one trait on the Strike.
        text = (
            self.SOURCE + "<b>Melee</b> breath +20 "
            '(<a game-obj="Traits" aonid="1">fear</a>), <b>Damage</b> 4d6 mental plus '
            '<a game-obj="Traits" aonid="1">fear</a>'
        )
        attack = _parsed(text=text)["attacks"][0]
        assert [t["name"] for t in attack["traits"]] == ["fear"]

    def test_a_condition_in_the_damage_is_not_mistaken_for_a_trait(self):
        text = (
            self.SOURCE + "<b>Melee</b> claw +20 "
            '(<a game-obj="Traits" aonid="1">agile</a>), <b>Damage</b> 2d6 slashing plus '
            '<a game-obj="Conditions" aonid="29">bleed</a>'
        )
        attack = _parsed(text=text)["attacks"][0]
        assert [t["name"] for t in attack["traits"]] == ["agile"]
        # A condition named in the damage belongs to that damage entry, which
        # is where creatures put it, not to the Strike as a whole.
        assert [link["name"] for link in attack["damage"][1]["links"]] == ["bleed"]

    def test_other_abilities_are_left_alone(self):
        text = (
            self.SOURCE + "<b>Pitfall</b> "
            '<span class="action" title="Reaction">[reaction]</span> '
            "<b>Effect</b> The creature falls in."
        )
        hazard = _parsed(text=text)
        assert "attacks" not in hazard
        assert hazard["abilities"][0]["name"] == "Pitfall"


class TestStealth:
    SOURCE = '<b>Source</b> <a game-obj="Sources" aonid="1"><i>Core pg. 1</i></a><br/>'

    def test_a_simple_hazard_publishes_a_detection_dc(self):
        hazard = _parsed(text=self.SOURCE + "<b>Stealth</b> DC 37 (expert)")
        assert hazard["stealth"]["dc"] == 37
        assert hazard["stealth"]["proficiency"] == "expert"
        assert "value" not in hazard["stealth"]

    def test_a_complex_hazard_publishes_an_initiative_modifier(self):
        # GM Core 100: a modifier for a complex hazard, a DC for a simple one.
        hazard = _parsed(text=self.SOURCE + "<b>Stealth</b> +17 (trained)")
        assert hazard["stealth"]["value"] == 17
        assert "dc" not in hazard["stealth"]

    def test_a_negative_modifier(self):
        assert _parsed(text=self.SOURCE + "<b>Stealth</b> -10")["stealth"]["value"] == -10

    def test_prose_after_the_value_is_kept(self):
        hazard = _parsed(text=self.SOURCE + "<b>Stealth</b> +38 (master) to hear the sounds")
        assert hazard["stealth"]["proficiency"] == "master"
        assert hazard["stealth"]["note"] == "to hear the sounds"

    def test_a_parenthetical_that_is_not_a_proficiency_is_a_note(self):
        hazard = _parsed(text=self.SOURCE + "<b>Stealth</b> +0 (the lake is obvious)")
        assert "proficiency" not in hazard["stealth"]
        assert hazard["stealth"]["note"] == "the lake is obvious"

    def test_an_unparseable_stealth_fails_loudly(self):
        with pytest.raises(AssertionError, match="and this is neither"):
            _parsed(text=self.SOURCE + "<b>Stealth</b> obvious")

    def test_a_bare_number_fails_loudly(self):
        # It says neither which it is nor which the hazard needs, and the
        # corpus has Complex hazards publishing a DC and Simple ones a
        # modifier, so the complexity cannot decide it either.
        with pytest.raises(AssertionError, match="and this is neither"):
            _parsed(text=self.SOURCE + "<b>Stealth</b> 28")

    def test_a_proficiency_followed_by_prose_keeps_both(self):
        hazard = _parsed(text=self.SOURCE + "<b>Stealth</b> DC 30 (trained; behind the arras)")
        assert hazard["stealth"]["proficiency"] == "trained"
        assert hazard["stealth"]["note"] == "behind the arras"


class TestSavingThrow:
    SOURCE = '<b>Source</b> <a game-obj="Sources" aonid="1"><i>Core pg. 1</i></a><br/>'

    def test_dc_first(self):
        save = _parsed(text=self.SOURCE + "<b>Saving Throw</b> DC 21 Fortitude")["saving_throw"]
        assert (save["save_type"], save["dc"]) == ("Fort", 21)

    def test_save_first(self):
        # Both orders appear in the corpus.
        save = _parsed(text=self.SOURCE + "<b>Saving Throw</b> Fortitude DC 21")["saving_throw"]
        assert (save["save_type"], save["dc"]) == ("Fort", 21)

    def test_the_published_text_is_kept(self):
        save = _parsed(text=self.SOURCE + "<b>Saving Throw</b> DC 17 Will")["saving_throw"]
        assert save["text"] == "DC 17 Will" and save["save_type"] == "Will"

    def test_an_unparseable_saving_throw_fails_loudly(self):
        with pytest.raises(AssertionError, match="Saves must have DCs"):
            _parsed(text=self.SOURCE + "<b>Saving Throw</b> see below")


class TestTrailingDetails:
    def test_an_unstructured_trailing_detail_fails_loudly(self):
        details = _details()
        details.append("leftover prose")
        with pytest.raises(AssertionError, match="Unstructured trailing detail"):
            restructure_hazard_pass(details)


class TestAttackExtractionOrder:
    """Attacks come out before the ability parser, which is what makes the
    shared creature parser usable on them."""

    SOURCE = '<b>Source</b> <a game-obj="Sources" aonid="1"><i>Core pg. 1</i></a><br/>'

    def test_the_attack_is_not_also_left_as_an_ability(self):
        text = self.SOURCE + "<b>Melee</b> claw +20, <b>Damage</b> 2d6 slashing"
        hazard = _parsed(text=text)
        assert len(hazard["attacks"]) == 1
        assert "abilities" not in hazard

    def test_an_ability_after_an_attack_still_parses(self):
        text = (
            self.SOURCE + "<b>Melee</b> claw +20, <b>Damage</b> 2d6 slashing<br/>"
            "<b>Pitfall</b> "
            '<span class="action" title="Reaction">[reaction]</span> '
            "<b>Effect</b> The creature falls in."
        )
        hazard = _parsed(text=text)
        assert [a["weapon"] for a in hazard["attacks"]] == ["claw"]
        assert [a["name"] for a in hazard["abilities"]] == ["Pitfall"]

    def test_two_attacks_both_survive(self):
        text = (
            self.SOURCE + "<b>Melee</b> claw +20, <b>Damage</b> 2d6 slashing<br/>"
            "<b>Ranged</b> spike +18, <b>Damage</b> 1d8 piercing"
        )
        attacks = _parsed(text=text)["attacks"]
        assert [(a["weapon"], a["attack_type"]) for a in attacks] == [
            ("claw", "melee"),
            ("spike", "ranged"),
        ]

    def test_the_action_type_is_kept(self):
        text = (
            self.SOURCE + "<b>Melee</b> "
            '<span class="action" title="Single Action">[one-action]</span> '
            "claw +20, <b>Damage</b> 2d6 slashing"
        )
        assert _parsed(text=text)["attacks"][0]["action_type"]["name"] == "One Action"


class TestUnlinkedAttackTraits:
    """An unlinked trait is a source problem, so it has to be visible."""

    SOURCE = '<b>Source</b> <a game-obj="Sources" aonid="1"><i>Core pg. 1</i></a><br/>'

    def test_an_unlinked_trait_fails_loudly(self):
        # extract_starting_traits only objects when SOME traits are linked, so
        # a wholly unlinked parenthetical would otherwise vanish.
        text = self.SOURCE + "<b>Melee</b> claw +20 (magical), <b>Damage</b> 2d6 slashing"
        with pytest.raises(AssertionError, match="link them in the source"):
            _parsed(text=text)

    def test_a_linked_trait_is_fine(self):
        text = (
            self.SOURCE + "<b>Melee</b> claw +20 "
            '(<a game-obj="Traits" aonid="103">magical</a>), <b>Damage</b> 2d6 slashing'
        )
        assert [t["name"] for t in _parsed(text=text)["attacks"][0]["traits"]] == ["magical"]

    def test_a_note_in_the_traits_slot_is_kept_not_flagged(self):
        # "can target any creature in area A8" is published content, not traits.
        text = (
            self.SOURCE + "<b>Melee</b> bolt +35 (can target any creature in area A8), "
            "<b>Damage</b> 4d10 force"
        )
        attack = _parsed(text=text)["attacks"][0]
        assert attack["note"] == "can target any creature in area A8"
        # parse_attack_action always sets traits; remove_empty_fields drops the
        # empty list later in the pipeline.
        assert not attack["traits"]
