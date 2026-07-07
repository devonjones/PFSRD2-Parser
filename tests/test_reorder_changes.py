from pfsrd2.monster_template import reorder_changes_pass


def _change(category, text):
    return {
        "type": "stat_block_section",
        "subtype": "change",
        "change_category": category,
        "text": text,
    }


def _struct(categories):
    return {"monster_template": {"changes": [_change(c, f"- {c} text") for c in categories]}}


class TestReorderChangesPass:
    def test_hit_points_moves_before_level(self):
        # monster_core Elite source order
        struct = _struct(["level", "combat_stats", "damage", "hit_points"])
        reorder_changes_pass(struct)
        cats = [c["change_category"] for c in struct["monster_template"]["changes"]]
        assert cats == ["hit_points", "level", "combat_stats", "damage"]

    def test_no_level_change_keeps_source_order(self):
        # bestiary Elite has no explicit level change
        struct = _struct(["combat_stats", "damage", "hit_points"])
        reorder_changes_pass(struct)
        cats = [c["change_category"] for c in struct["monster_template"]["changes"]]
        assert cats == ["combat_stats", "damage", "hit_points"]

    def test_no_hit_points_change_keeps_source_order(self):
        struct = _struct(["level", "combat_stats"])
        reorder_changes_pass(struct)
        cats = [c["change_category"] for c in struct["monster_template"]["changes"]]
        assert cats == ["level", "combat_stats"]

    def test_already_ordered_is_stable(self):
        struct = _struct(["hit_points", "level", "damage"])
        original = [c["text"] for c in struct["monster_template"]["changes"]]
        reorder_changes_pass(struct)
        assert [c["text"] for c in struct["monster_template"]["changes"]] == original

    def test_multiple_hit_points_changes_keep_relative_order(self):
        struct = _struct(["damage", "hit_points", "level", "hit_points"])
        struct["monster_template"]["changes"][1]["text"] = "- hp first"
        struct["monster_template"]["changes"][3]["text"] = "- hp second"
        reorder_changes_pass(struct)
        changes = struct["monster_template"]["changes"]
        cats = [c["change_category"] for c in changes]
        assert cats == ["damage", "hit_points", "hit_points", "level"]
        hp_texts = [c["text"] for c in changes if c["change_category"] == "hit_points"]
        assert hp_texts == ["- hp first", "- hp second"]

    def test_uncategorized_changes_are_untouched(self):
        # First cold-start parse has no categories merged yet
        struct = _struct([None, None])
        reorder_changes_pass(struct)
        assert len(struct["monster_template"]["changes"]) == 2

    def test_missing_changes_is_a_noop(self):
        reorder_changes_pass({"monster_template": {}})
        reorder_changes_pass({})
