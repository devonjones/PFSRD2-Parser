from pfsrd2.ability_identity import ability_to_raw_json, compute_identity_hash, normalize_text


class TestNormalizeText:
    def test_strips_whitespace(self):
        assert normalize_text("  hello  ") == "hello"

    def test_collapses_internal_whitespace(self):
        assert normalize_text("hello   world") == "hello world"

    def test_handles_newlines_and_tabs(self):
        assert normalize_text("hello\n\tworld") == "hello world"

    def test_empty_string(self):
        assert normalize_text("") == ""

    def test_none(self):
        assert normalize_text(None) == ""

    def test_unicode_normalization(self):
        # NFC normalizes composed vs decomposed unicode
        composed = "\u00e9"  # é as single codepoint
        decomposed = "e\u0301"  # e + combining acute
        assert normalize_text(composed) == normalize_text(decomposed)

    def test_curly_apostrophe(self):
        # Common in AoN text
        text = "can\u2019t use Breath Weapon again"
        result = normalize_text(text)
        assert "\u2019" in result  # preserved, just normalized


class TestComputeIdentityHash:
    def test_same_ability_same_hash(self):
        ability = {
            "name": "Breath Weapon",
            "type": "stat_block_section",
            "subtype": "ability",
            "ability_type": "offensive",
            "text": "The dragon breathes acid.",
        }
        assert compute_identity_hash(ability) == compute_identity_hash(ability)

    def test_different_text_different_hash(self):
        a1 = {"name": "Breath Weapon", "text": "12d6 acid damage"}
        a2 = {"name": "Breath Weapon", "text": "16d6 acid damage"}
        assert compute_identity_hash(a1) != compute_identity_hash(a2)

    def test_different_name_different_hash(self):
        a1 = {"name": "Breath Weapon", "text": "same text"}
        a2 = {"name": "Draconic Frenzy", "text": "same text"}
        assert compute_identity_hash(a1) != compute_identity_hash(a2)

    def test_whitespace_normalized(self):
        a1 = {"name": "Breath Weapon", "text": "hello  world"}
        a2 = {"name": "Breath Weapon", "text": "hello world"}
        assert compute_identity_hash(a1) == compute_identity_hash(a2)

    def test_trait_order_independent(self):
        a1 = {
            "name": "Breath Weapon",
            "traits": [
                {"name": "Acid", "type": "trait"},
                {"name": "Arcane", "type": "trait"},
            ],
        }
        a2 = {
            "name": "Breath Weapon",
            "traits": [
                {"name": "Arcane", "type": "trait"},
                {"name": "Acid", "type": "trait"},
            ],
        }
        assert compute_identity_hash(a1) == compute_identity_hash(a2)

    def test_different_traits_different_hash(self):
        a1 = {
            "name": "Breath Weapon",
            "traits": [{"name": "Acid", "type": "trait"}],
        }
        a2 = {
            "name": "Breath Weapon",
            "traits": [{"name": "Fire", "type": "trait"}],
        }
        assert compute_identity_hash(a1) != compute_identity_hash(a2)

    def test_action_type_included(self):
        a1 = {
            "name": "Breath Weapon",
            "action_type": {"name": "Two Actions"},
        }
        a2 = {
            "name": "Breath Weapon",
            "action_type": {"name": "One Action"},
        }
        assert compute_identity_hash(a1) != compute_identity_hash(a2)

    def test_missing_optional_fields(self):
        # Minimal ability should hash without error
        a1 = {"name": "Grab"}
        h = compute_identity_hash(a1)
        assert isinstance(h, str)
        assert len(h) == 64  # sha256 hex

    def test_frequency_changes_hash(self):
        a1 = {"name": "Corrupt Water", "frequency": "Once per day"}
        a2 = {"name": "Corrupt Water"}
        assert compute_identity_hash(a1) != compute_identity_hash(a2)

    def test_effect_changes_hash(self):
        a1 = {"name": "Corrupt Water", "effect": "Befouls 10 cubic feet"}
        a2 = {"name": "Corrupt Water", "effect": "Befouls 20 cubic feet"}
        assert compute_identity_hash(a1) != compute_identity_hash(a2)

    def test_hash_stability(self):
        """Hash should be deterministic across calls."""
        ability = {
            "name": "Breath Weapon",
            "type": "stat_block_section",
            "subtype": "ability",
            "ability_type": "offensive",
            "text": "The dragon breathes a spray of acid.",
            "frequency": None,
            "action_type": {"name": "Two Actions"},
            "traits": [
                {"name": "Acid", "type": "trait"},
                {"name": "Arcane", "type": "trait"},
                {"name": "Evocation", "type": "trait"},
            ],
        }
        h1 = compute_identity_hash(ability)
        h2 = compute_identity_hash(ability)
        assert h1 == h2

    def test_extra_fields_ignored(self):
        """Fields not in the identity set should not affect the hash."""
        a1 = {
            "name": "Grab",
            "text": "The creature grabs.",
            "links": [{"type": "link", "name": "grabbed"}],
        }
        a2 = {
            "name": "Grab",
            "text": "The creature grabs.",
        }
        assert compute_identity_hash(a1) == compute_identity_hash(a2)


class TestAbilityToRawJson:
    def test_deterministic(self):
        ability = {"name": "Grab", "text": "The creature grabs.", "type": "ability"}
        assert ability_to_raw_json(ability) == ability_to_raw_json(ability)

    def test_sorted_keys(self):
        a1 = {"z": 1, "a": 2}
        a2 = {"a": 2, "z": 1}
        assert ability_to_raw_json(a1) == ability_to_raw_json(a2)

    def test_unicode_preserved(self):
        ability = {"name": "Test", "text": "can\u2019t use"}
        result = ability_to_raw_json(ability)
        assert "\u2019" in result
