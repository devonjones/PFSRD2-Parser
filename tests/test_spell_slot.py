"""Tests for spell slot decoration (pfsrd2/spell_slot.py)."""

import pytest

from pfsrd2.spell_slot import parse_spell_entries, spell_slot_pass, variant_rank


def _staff(name, text=None, variants=None, abilities=None, links=None):
    stat_block = {
        "type": "stat_block",
        "subtype": "equipment",
        "item_category": "Staves",
    }
    if text:
        stat_block["text"] = text
    if links:
        stat_block["links"] = links
    if variants:
        stat_block["variants"] = variants
    if abilities:
        stat_block["statistics"] = {
            "type": "stat_block_section",
            "subtype": "statistics",
            "abilities": abilities,
        }
    return {"name": name, "stat_block": stat_block}


def _template(name, category, variants, craft=None, links=None, subcategory=None):
    stat_block = {
        "type": "stat_block",
        "subtype": "equipment",
        "item_category": category,
        "variants": [{"name": v} for v in variants],
    }
    if subcategory:
        stat_block["item_subcategory"] = subcategory
    if craft:
        stat_block["craft_requirements"] = craft
    if links:
        stat_block["links"] = links
    return {"name": name, "stat_block": stat_block}


LINKS = [
    {"game-obj": "Spells", "name": "light", "aonid": 171},
    {"game-obj": "Spells", "name": "everlight", "aonid": 1518},
    {"game-obj": "Spells", "name": "holy light", "aonid": 1557},
]


class TestParseSpellEntries:
    def test_bold_bullets(self):
        text = "* **Cantrip** *light*\n* **2nd** *everlight*\n* **3rd** *everlight*, *holy light*"
        entries = parse_spell_entries(text, LINKS)
        assert [e["rank"] for e in entries] == ["cantrip", 2, 3]
        assert [s["name"] for s in entries[2]["spells"]] == ["everlight", "holy light"]

    def test_plain_bullets(self):
        entries = parse_spell_entries("* Cantrip daze\n* 1st fear, phantom pain")
        assert [e["rank"] for e in entries] == ["cantrip", 1]
        assert [s["name"] for s in entries[1]["spells"]] == ["fear", "phantom pain"]

    def test_prose_preamble_is_ignored(self):
        text = "You expend a number of charges.\n* **Cantrip** *light*\n* **2nd** *everlight*"
        assert [e["rank"] for e in parse_spell_entries(text, LINKS)] == ["cantrip", 2]

    def test_aonids_come_from_links(self):
        entries = parse_spell_entries("* **Cantrip** *light*", LINKS)
        assert entries[0]["spells"][0]["aonid"] == 171

    def test_spell_without_a_link_still_parses(self):
        entries = parse_spell_entries("* 1st obscure spell")
        assert entries[0]["spells"][0]["name"] == "obscure spell"
        assert "aonid" not in entries[0]["spells"][0]

    def test_trailing_qualifier_becomes_a_note(self):
        entries = parse_spell_entries("* 6th summon dragon (6th)")
        spell = entries[0]["spells"][0]
        assert spell["name"] == "summon dragon"
        assert spell["note"] == "6th"

    def test_comma_inside_a_qualifier_does_not_split_the_spell(self):
        # "not a tree)" was a phantom spell before the paren-aware split.
        text = "* 4th summon plant or fungus (fungus only, not a tree), wall of thorns"
        spells = parse_spell_entries(text)[0]["spells"]
        assert [s["name"] for s in spells] == ["summon plant or fungus", "wall of thorns"]
        assert spells[0]["note"] == "fungus only, not a tree"

    def test_no_bullets_yields_nothing(self):
        assert parse_spell_entries("This staff is made of hawthorn.") == []

    def test_empty_text(self):
        assert parse_spell_entries(None) == []
        assert parse_spell_entries("") == []


class TestVariantRank:
    @pytest.mark.parametrize(
        "name,expected",
        [
            ("Magic Wand (3rd-rank Spell)", 3),
            ("Magic Wand (2nd-Level Spell)", 2),
            ("1st-rank Scroll", 1),
            ("10th-rank Scroll", 10),
            ("Wand of Widening (9th-rank Spell)", 9),
            ("Staff of Healing (Greater)", None),
        ],
    )
    def test_rank_extraction(self, name, expected):
        assert variant_rank(name) == expected


class TestStaffPass:
    def test_list_in_an_activation_ability(self):
        struct = _staff(
            "Staff of Illumination",
            abilities=[
                {"name": "Activate", "effect": "Interact; light the gem."},
                {
                    "name": "Activate",
                    "effect": "* **Cantrip** *light*\n* **2nd** *everlight*",
                    "links": LINKS,
                },
            ],
        )
        spell_slot_pass(struct)
        slots = struct["stat_block"]["spell_slots"]
        assert slots["holder"] == "staff"
        assert slots["cantrips_free"] is True
        assert [e["rank"] for e in slots["entries"]] == ["cantrip", 2]

    def test_list_in_variants_is_cumulative(self):
        struct = _staff(
            "Staff of Impossible Visions",
            variants=[
                {"name": "Base", "text": "* Cantrip daze\n* 1st fear"},
                {"name": "Greater", "text": "* 3rd hypnotic pattern"},
            ],
        )
        spell_slot_pass(struct)
        base, greater = struct["stat_block"]["variants"]
        assert base["spell_slots"]["cumulative"] is True
        assert [e["rank"] for e in base["spell_slots"]["entries"]] == ["cantrip", 1]
        assert [e["rank"] for e in greater["spell_slots"]["entries"]] == [3]
        # The holder block stays, carrying the charge rule.
        assert struct["stat_block"]["spell_slots"]["holder"] == "staff"

    def test_variants_win_over_an_ability_list(self):
        struct = _staff(
            "Both",
            variants=[{"name": "Base", "text": "* 1st fear"}],
            abilities=[{"name": "Activate", "effect": "* 9th meteor swarm"}],
        )
        spell_slot_pass(struct)
        assert "entries" not in struct["stat_block"]["spell_slots"]
        assert struct["stat_block"]["variants"][0]["spell_slots"]["entries"][0]["rank"] == 1

    def test_list_in_item_text(self):
        struct = _staff("Musket Staff", text="A firearm and staff.\n* 1st gust of wind")
        spell_slot_pass(struct)
        assert struct["stat_block"]["spell_slots"]["entries"][0]["rank"] == 1

    def test_staff_with_no_list_still_gets_the_holder_block(self):
        # Whispering Staff functions as another staff and lists nothing.
        struct = _staff("Whispering Staff", text="It functions as a major staff.")
        spell_slot_pass(struct)
        slots = struct["stat_block"]["spell_slots"]
        assert slots["holder"] == "staff"
        assert "entries" not in slots


class TestTemplatePass:
    def test_wand_ceiling_and_exclusions(self):
        struct = _template("Magic Wand", "Wands", ["Magic Wand (1st-rank Spell)"])
        spell_slot_pass(struct)
        slots = struct["stat_block"]["spell_slots"]
        assert slots["holder"] == "wand"
        assert slots["capacity"] == 1
        assert slots["max_rank"] == 9
        assert slots["excluded_spell_types"] == ["cantrip", "focus", "ritual"]

    def test_scroll_ceiling_is_ten_and_has_no_exclusions(self):
        struct = _template(
            "Magic Scroll", "Consumables", ["10th-rank Scroll"], subcategory="Scrolls"
        )
        spell_slot_pass(struct)
        slots = struct["stat_block"]["spell_slots"]
        assert slots["holder"] == "scroll"
        assert slots["max_rank"] == 10
        assert "excluded_spell_types" not in slots

    def test_variants_carry_their_rank(self):
        struct = _template(
            "Magic Wand",
            "Wands",
            ["Magic Wand (1st-rank Spell)", "Magic Wand (5th-rank Spell)"],
        )
        spell_slot_pass(struct)
        assert [v["spell_rank"] for v in struct["stat_block"]["variants"]] == [1, 5]

    def test_fixed_spell_wand(self):
        struct = _template(
            "Wand of Shardstorm",
            "Wands",
            ["Wand of Shardstorm (1st-rank Spell)"],
            craft="Supply a casting of *force barrage* of the appropriate rank.",
            links=[{"game-obj": "Spells", "name": "force barrage", "aonid": 999}],
        )
        spell_slot_pass(struct)
        spell = struct["stat_block"]["spell_slots"]["spell"]
        assert spell["name"] == "force barrage"
        assert spell["aonid"] == 999

    def test_open_slot_wand_records_no_constraint(self):
        struct = _template(
            "Magic Wand",
            "Wands",
            ["Magic Wand (1st-rank Spell)"],
            craft="Supply a casting of the spell at the listed rank.",
        )
        spell_slot_pass(struct)
        slots = struct["stat_block"]["spell_slots"]
        assert "spell" not in slots and "constraint_text" not in slots

    def test_specialty_wand_keeps_its_predicate_as_prose(self):
        craft = (
            "Supply a casting of a spell of the appropriate rank. The spell must have a "
            "casting time of [#] or [##], can't have a duration, and must have an area."
        )
        struct = _template(
            "Wand of Widening", "Wands", ["Wand of Widening (1st-rank Spell)"], craft=craft
        )
        spell_slot_pass(struct)
        assert struct["stat_block"]["spell_slots"]["constraint_text"] == craft

    def test_variant_without_a_rank_fails_loudly(self):
        struct = _template("Magic Wand", "Wands", ["Magic Wand (Greater)"])
        with pytest.raises(AssertionError, match="names no spell rank"):
            spell_slot_pass(struct)

    def test_wand_variant_above_the_rank_ceiling_fails_loudly(self):
        # Wands stop at 9th; a 10th-rank wand means the parse crossed a scroll.
        struct = _template("Magic Wand", "Wands", ["Magic Wand (10th-rank Spell)"])
        with pytest.raises(AssertionError, match="above the 9 the rules allow"):
            spell_slot_pass(struct)

    def test_non_holder_equipment_is_untouched(self):
        struct = {"name": "Rope", "stat_block": {"item_category": "Adventuring Gear"}}
        spell_slot_pass(struct)
        assert "spell_slots" not in struct["stat_block"]

    def test_struct_without_a_stat_block_is_a_no_op(self):
        struct = {"name": "Broken"}
        spell_slot_pass(struct)
        assert struct == {"name": "Broken"}
