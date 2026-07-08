"""Tests for curated cross-type equivalence links."""

import json

from pfsrd2.equivalents import _EQUIVALENTS_PATH, equivalent_link_pass


class TestEquivalentLinkPass:
    def test_paired_doc_gets_link(self):
        # BotD ghost template -> Monster Core ghost family
        struct = {"game-id": "c3f766c1fb2f2d3a127c6b5059e29eef"}
        equivalent_link_pass(struct)
        link = struct["equivalent_link"]
        assert link["game_id"] == "03e8544746de64ca7b79b2bcd87a9481"
        assert link["entry_type"] == "monster_families"
        assert link["edition"] == "remastered"

    def test_reverse_direction(self):
        struct = {"game-id": "03e8544746de64ca7b79b2bcd87a9481"}
        equivalent_link_pass(struct)
        assert struct["equivalent_link"]["entry_type"] == "monster_templates"
        assert struct["equivalent_link"]["edition"] == "legacy"

    def test_unpaired_doc_untouched(self):
        struct = {"game-id": "not-a-real-id"}
        equivalent_link_pass(struct)
        assert "equivalent_link" not in struct

    def test_pairs_are_cross_edition(self):
        # the map exists for cross-edition type changes; same-edition
        # duplicates (military/guerrilla) are deliberately excluded
        pairs = json.load(open(_EQUIVALENTS_PATH))["equivalents"]
        for p in pairs:
            assert p["a"]["edition"] != p["b"]["edition"], p["note"]
            assert p["a"]["entry_type"] != p["b"]["entry_type"], p["note"]
