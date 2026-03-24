import json

from pfsrd2.change_identity import change_to_raw_json, compute_change_hash


class TestComputeChangeHash:
    def test_same_inputs_same_hash(self):
        h1 = compute_change_hash("Vampire", "monster_template", "Add the undead trait.")
        h2 = compute_change_hash("Vampire", "monster_template", "Add the undead trait.")
        assert h1 == h2

    def test_different_source_name_different_hash(self):
        h1 = compute_change_hash("Vampire", "monster_template", "Add the undead trait.")
        h2 = compute_change_hash("Zombie", "monster_template", "Add the undead trait.")
        assert h1 != h2

    def test_different_source_type_different_hash(self):
        h1 = compute_change_hash("Vampire", "monster_template", "Add the undead trait.")
        h2 = compute_change_hash("Vampire", "monster_family", "Add the undead trait.")
        assert h1 != h2

    def test_different_change_text_different_hash(self):
        h1 = compute_change_hash("Vampire", "monster_template", "Add the undead trait.")
        h2 = compute_change_hash("Vampire", "monster_template", "Increase AC by 2.")
        assert h1 != h2

    def test_whitespace_normalization(self):
        h1 = compute_change_hash("Vampire", "monster_template", "Add  the   undead trait.")
        h2 = compute_change_hash("Vampire", "monster_template", "Add the undead trait.")
        assert h1 == h2

    def test_returns_hex_string(self):
        h = compute_change_hash("Vampire", "monster_template", "Add the undead trait.")
        assert isinstance(h, str)
        assert len(h) == 64  # sha256 hex
        # All hex characters
        int(h, 16)

    def test_deterministic(self):
        h1 = compute_change_hash("Test", "monster_template", "Some text")
        h2 = compute_change_hash("Test", "monster_template", "Some text")
        assert h1 == h2


class TestChangeToRawJson:
    def test_produces_valid_json(self):
        change = {"text": "Add the undead trait.", "type": "stat_block_section"}
        result = change_to_raw_json(change)
        parsed = json.loads(result)
        assert parsed["text"] == "Add the undead trait."

    def test_sorted_keys(self):
        change = {"z_field": 1, "a_field": 2, "m_field": 3}
        result = change_to_raw_json(change)
        keys = list(json.loads(result).keys())
        assert keys == sorted(keys)

    def test_unicode_preserved(self):
        change = {"text": "creature\u2019s level"}
        result = change_to_raw_json(change)
        assert "\u2019" in result
