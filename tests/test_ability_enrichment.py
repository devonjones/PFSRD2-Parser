"""Tests for the ability enrichment pass."""

import json

import pytest

from pfsrd2.ability_enrichment import (
    _get_creature_metadata,
    _walk_abilities,
    ability_enrichment_pass,
)
from pfsrd2.ability_identity import (
    compute_identity_hash,
)
from pfsrd2.sql.enrichment import (
    count_ability_records,
    fetch_abilities_for_creature,
    fetch_ability_by_hash,
    fetch_creatures_for_ability,
    get_enrichment_db_connection,
    update_enriched_json,
)


def _make_ability(name, text="", traits=None, action_type=None, frequency=None, effect=None):
    ability = {
        "type": "stat_block_section",
        "subtype": "ability",
        "ability_type": "offensive",
        "name": name,
    }
    if text:
        ability["text"] = text
    if traits:
        ability["traits"] = [{"name": t, "type": "trait"} for t in traits]
    if action_type:
        ability["action_type"] = {
            "type": "stat_block_section",
            "subtype": "action_type",
            "name": action_type,
        }
    if frequency:
        ability["frequency"] = frequency
    if effect:
        ability["effect"] = effect
    return ability


def _make_special_sense(name):
    return {
        "type": "stat_block_section",
        "subtype": "ability",
        "ability_type": "special_sense",
        "name": name,
    }


def _make_creature(name, aonid, level, traits, source, abilities):
    """Build a minimal creature struct with abilities in various locations."""
    auto_abilities = []
    reactive_abilities = []
    hp_auto_abilities = []
    interaction_abilities = []
    communication_abilities = []
    offensive_actions = []
    special_senses = []

    for ab_type, ability in abilities:
        if ab_type == "automatic":
            auto_abilities.append(ability)
        elif ab_type == "reactive":
            reactive_abilities.append(ability)
        elif ab_type == "hp_automatic":
            hp_auto_abilities.append(ability)
        elif ab_type == "interaction":
            interaction_abilities.append(ability)
        elif ab_type == "communication":
            communication_abilities.append(ability)
        elif ab_type == "special_sense":
            special_senses.append(ability)
        elif ab_type == "offensive":
            offensive_actions.append(
                {
                    "name": ability["name"],
                    "type": "stat_block_section",
                    "subtype": "offensive_action",
                    "offensive_action_type": "ability",
                    "ability": ability,
                }
            )

    struct = {
        "name": name,
        "aonid": aonid,
        "sources": [{"name": source, "type": "source"}],
        "stat_block": {
            "creature_type": {
                "level": level,
                "traits": [{"name": t, "type": "trait"} for t in traits],
            },
            "defense": {
                "automatic_abilities": auto_abilities,
                "reactive_abilities": reactive_abilities,
                "hitpoints": (
                    [{"automatic_abilities": hp_auto_abilities}] if hp_auto_abilities else []
                ),
            },
            "senses": {
                "special_senses": special_senses,
            },
            "statistics": {
                "languages": {
                    "communication_abilities": communication_abilities,
                },
            },
            "interaction_abilities": interaction_abilities,
            "offense": {
                "offensive_actions": offensive_actions,
            },
        },
    }
    return struct


class TestGetCreatureMetadata:
    def test_extracts_metadata(self):
        struct = _make_creature("Adult Black Dragon", 128, 11, ["Dragon", "Acid"], "Bestiary", [])
        meta = _get_creature_metadata(struct)
        assert meta["creature_game_id"] == "128"
        assert meta["creature_name"] == "Adult Black Dragon"
        assert meta["creature_level"] == 11
        assert meta["creature_traits"] == ["Dragon", "Acid"]
        assert meta["source_name"] == "Bestiary"


class TestWalkAbilities:
    def test_walks_all_ability_locations(self):
        auto = _make_ability("Frightful Presence")
        reactive = _make_ability("Attack of Opportunity")
        hp_auto = _make_ability("Negative Healing")
        interaction = _make_ability("Smoke Vision")
        communication = _make_ability("Telepathy")
        offensive = _make_ability("Breath Weapon", text="12d6 acid")
        darkvision = _make_special_sense("darkvision")

        struct = _make_creature(
            "Dragon",
            1,
            11,
            [],
            "Bestiary",
            [
                ("automatic", auto),
                ("reactive", reactive),
                ("hp_automatic", hp_auto),
                ("interaction", interaction),
                ("communication", communication),
                ("offensive", offensive),
                ("special_sense", darkvision),
            ],
        )
        results = list(_walk_abilities(struct))
        assert [(c, a["name"]) for c, a in results] == [
            ("automatic", "Frightful Presence"),
            ("reactive", "Attack of Opportunity"),
            ("hp_automatic", "Negative Healing"),
            ("interaction", "Smoke Vision"),
            ("communication", "Telepathy"),
            ("offensive", "Breath Weapon"),
            ("special_sense", "darkvision"),
        ]

    def test_walks_original_three_categories(self):
        """Backward compatibility — the original 3 categories still work."""
        auto = _make_ability("Frightful Presence")
        reactive = _make_ability("Attack of Opportunity")
        offensive = _make_ability("Breath Weapon", text="12d6 acid")

        struct = _make_creature(
            "Dragon",
            1,
            11,
            [],
            "Bestiary",
            [("automatic", auto), ("reactive", reactive), ("offensive", offensive)],
        )
        results = list(_walk_abilities(struct))
        categories = [c for c, _ in results]
        assert "automatic" in categories
        assert "reactive" in categories
        assert "offensive" in categories

    def test_skips_non_abilities(self):
        struct = {
            "stat_block": {
                "defense": {
                    "automatic_abilities": [
                        {"name": "Not Ability", "subtype": "something_else"},
                    ],
                },
                "offense": {
                    "offensive_actions": [
                        {
                            "name": "Melee",
                            "offensive_action_type": "attack",
                        },
                    ],
                },
            },
        }
        names = list(_walk_abilities(struct))
        assert names == []


class TestAbilityEnrichmentPass:
    @pytest.fixture
    def db(self):
        conn = get_enrichment_db_connection(db_path=":memory:")
        yield conn
        conn.close()

    def test_populates_db_on_first_run(self, db):
        breath = _make_ability(
            "Breath Weapon",
            text="12d6 acid damage",
            traits=["Acid", "Arcane"],
            action_type="Two Actions",
        )
        struct = _make_creature(
            "Adult Black Dragon", 128, 11, ["Dragon", "Acid"], "Bestiary", [("offensive", breath)]
        )

        ability_enrichment_pass(struct, conn=db)

        curs = db.cursor()
        counts = count_ability_records(curs)
        assert counts["total"] == 1
        # Inline enrichment now enriches on first run (regex extracts
        # "12d6 acid damage" → damage field)
        assert counts["unenriched"] == 0

        abilities = fetch_abilities_for_creature(curs, "128")
        assert len(abilities) == 1
        assert abilities[0]["name"] == "Breath Weapon"

    def test_deduplicates_shared_abilities(self, db):
        grab = _make_ability("Grab", text="The creature grabs.")

        struct1 = _make_creature("Goblin", 1, -1, ["Goblin"], "Bestiary", [("offensive", grab)])
        struct2 = _make_creature("Bugbear", 2, 2, ["Goblin"], "Bestiary", [("offensive", grab)])

        ability_enrichment_pass(struct1, conn=db)
        ability_enrichment_pass(struct2, conn=db)

        curs = db.cursor()
        counts = count_ability_records(curs)
        assert counts["total"] == 1

        identity_hash = compute_identity_hash(grab)
        record = fetch_ability_by_hash(curs, identity_hash)
        links = fetch_creatures_for_ability(curs, record["ability_id"])
        assert len(links) == 2
        creature_names = {l["creature_name"] for l in links}
        assert creature_names == {"Goblin", "Bugbear"}

    def test_different_text_creates_separate_records(self, db):
        breath_young = _make_ability("Breath Weapon", text="6d6 acid damage")
        breath_adult = _make_ability("Breath Weapon", text="12d6 acid damage")

        struct1 = _make_creature(
            "Young Dragon", 1, 5, [], "Bestiary", [("offensive", breath_young)]
        )
        struct2 = _make_creature(
            "Adult Dragon", 2, 11, [], "Bestiary", [("offensive", breath_adult)]
        )

        ability_enrichment_pass(struct1, conn=db)
        ability_enrichment_pass(struct2, conn=db)

        curs = db.cursor()
        counts = count_ability_records(curs)
        assert counts["total"] == 2

    def test_no_output_changes_on_first_run(self, db):
        """First run should not modify struct — just populates DB."""
        breath = _make_ability("Breath Weapon", text="12d6 acid")
        struct = _make_creature("Dragon", 1, 11, [], "Bestiary", [("offensive", breath)])

        before = json.dumps(struct, sort_keys=True)
        ability_enrichment_pass(struct, conn=db)
        after = json.dumps(struct, sort_keys=True)

        assert before == after

    def test_merges_enrichment_on_second_run(self, db):
        """Second run should merge enriched fields into ability."""
        breath = _make_ability(
            "Breath Weapon",
            text="12d6 acid damage in an 80-foot line (DC 30 basic Reflex save).",
        )
        struct = _make_creature("Dragon", 1, 11, [], "Bestiary", [("offensive", breath)])

        # First run: populate
        ability_enrichment_pass(struct, conn=db)

        # Simulate offline enrichment
        curs = db.cursor()
        identity_hash = compute_identity_hash(breath)
        record = fetch_ability_by_hash(curs, identity_hash)
        enriched = dict(breath)
        enriched["saving_throw"] = [
            {
                "type": "stat_block_section",
                "subtype": "save_dc",
                "text": "DC 30 basic Reflex save",
                "dc": 30,
                "save_type": "Ref",
                "basic": True,
            }
        ]
        enriched["area"] = {
            "type": "stat_block_section",
            "subtype": "area",
            "text": "80-foot line",
            "shape": "line",
            "size": 80,
            "unit": "feet",
        }
        update_enriched_json(
            curs, record["ability_id"], json.dumps(enriched, sort_keys=True), 1, "regex"
        )
        db.commit()

        # Second run: should merge enrichment into ability
        breath2 = _make_ability(
            "Breath Weapon",
            text="12d6 acid damage in an 80-foot line (DC 30 basic Reflex save).",
        )
        struct2 = _make_creature("Dragon", 1, 11, [], "Bestiary", [("offensive", breath2)])
        ability_enrichment_pass(struct2, conn=db)

        # Check ability got enriched
        oa = struct2["stat_block"]["offense"]["offensive_actions"][0]
        ab = oa["ability"]
        assert "saving_throw" in ab
        assert ab["saving_throw"][0]["dc"] == 30
        assert "area" in ab
        assert ab["area"][0]["shape"] == "line"
        # Text should be untouched
        assert ab["text"] == breath["text"]

    def test_does_not_overwrite_existing_fields(self, db):
        """Enrichment should not overwrite fields already on the ability."""
        breath = _make_ability(
            "Breath Weapon",
            text="12d6 acid damage",
            frequency="once per day",
        )
        struct = _make_creature("Dragon", 1, 11, [], "Bestiary", [("offensive", breath)])

        # Populate
        ability_enrichment_pass(struct, conn=db)

        # Enrich with a different frequency
        curs = db.cursor()
        identity_hash = compute_identity_hash(breath)
        record = fetch_ability_by_hash(curs, identity_hash)
        enriched = dict(breath)
        enriched["frequency"] = "1d4 rounds"  # different from original
        update_enriched_json(
            curs, record["ability_id"], json.dumps(enriched, sort_keys=True), 1, "regex"
        )
        db.commit()

        # Re-run
        breath2 = _make_ability(
            "Breath Weapon",
            text="12d6 acid damage",
            frequency="once per day",
        )
        struct2 = _make_creature("Dragon", 1, 11, [], "Bestiary", [("offensive", breath2)])
        ability_enrichment_pass(struct2, conn=db)

        oa = struct2["stat_block"]["offense"]["offensive_actions"][0]
        ab = oa["ability"]
        # Original frequency preserved
        assert ab["frequency"] == "once per day"

    def test_merges_additional_dcs(self, db):
        """Enrichment should add new DCs not already on the ability."""
        # Ability already has one DC from parser (single object)
        breath = _make_ability(
            "Chill Breath",
            text="7d6 cold damage (DC 36 basic Reflex save). Escape DC 36.",
        )
        # Simulate parser having already set saving_throw as single object
        breath["saving_throw"] = {
            "type": "stat_block_section",
            "subtype": "save_dc",
            "text": "DC 36 Reflex",
            "dc": 36,
            "save_type": "Ref",
        }
        struct = _make_creature("Frost Giant", 1, 14, [], "Bestiary", [("offensive", breath)])

        ability_enrichment_pass(struct, conn=db)

        # Enrich with two DCs — one matching parser's, one new
        curs = db.cursor()
        identity_hash = compute_identity_hash(breath)
        record = fetch_ability_by_hash(curs, identity_hash)
        enriched = dict(breath)
        enriched["saving_throw"] = [
            {
                "type": "stat_block_section",
                "subtype": "save_dc",
                "text": "DC 36 basic Reflex save",
                "dc": 36,
                "save_type": "Ref",
                "basic": True,
            },
            {
                "type": "stat_block_section",
                "subtype": "save_dc",
                "text": "DC 36",
                "dc": 36,
            },  # Escape DC, no save_type
        ]
        update_enriched_json(
            curs, record["ability_id"], json.dumps(enriched, sort_keys=True), 1, "regex"
        )
        db.commit()

        # Re-run with same ability
        breath2 = _make_ability(
            "Chill Breath",
            text="7d6 cold damage (DC 36 basic Reflex save). Escape DC 36.",
        )
        breath2["saving_throw"] = {
            "type": "stat_block_section",
            "subtype": "save_dc",
            "text": "DC 36 Reflex",
            "dc": 36,
            "save_type": "Ref",
        }
        struct2 = _make_creature("Frost Giant", 1, 14, [], "Bestiary", [("offensive", breath2)])
        ability_enrichment_pass(struct2, conn=db)

        oa = struct2["stat_block"]["offense"]["offensive_actions"][0]
        ab = oa["ability"]
        # Should now be a list with both DCs
        assert isinstance(ab["saving_throw"], list)
        assert len(ab["saving_throw"]) == 2
        dcs = {(s["dc"], s.get("save_type")) for s in ab["saving_throw"]}
        assert (36, "Ref") in dcs
        assert (36, None) in dcs  # Escape DC (bare, no save_type)

    def test_stale_enrichment_not_applied(self, db):
        """Stale enrichments should not be applied."""
        breath = _make_ability("Breath Weapon", text="12d6 acid damage")
        struct = _make_creature("Dragon", 1, 11, [], "Bestiary", [("offensive", breath)])

        ability_enrichment_pass(struct, conn=db)

        # Enrich then mark stale
        curs = db.cursor()
        identity_hash = compute_identity_hash(breath)
        record = fetch_ability_by_hash(curs, identity_hash)
        enriched = dict(breath)
        enriched["saving_throw"] = [{"dc": 30}]
        update_enriched_json(
            curs, record["ability_id"], json.dumps(enriched, sort_keys=True), 1, "regex"
        )
        from pfsrd2.sql.enrichment import mark_stale

        mark_stale(curs, record["ability_id"], record["raw_json"])
        db.commit()

        # Re-run — stale should not be applied
        breath2 = _make_ability("Breath Weapon", text="12d6 acid damage")
        struct2 = _make_creature("Dragon", 1, 11, [], "Bestiary", [("offensive", breath2)])
        ability_enrichment_pass(struct2, conn=db)

        oa = struct2["stat_block"]["offense"]["offensive_actions"][0]
        ab = oa["ability"]
        assert "saving_throw" not in ab
