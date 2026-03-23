"""Tests for _pick_best_ability logic in creatures.py monster_ability_db_pass."""

import json


class TestPickBestAbilityLogic:
    """Test the _pick_best_ability logic extracted from monster_ability_db_pass."""

    @staticmethod
    def _make_ability_row(name, edition=None):
        ability = {"name": name}
        if edition is not None:
            ability["edition"] = edition
        return {"monster_ability": json.dumps(ability)}

    @staticmethod
    def _pick_best_ability(abilities, target_edition):
        """Reproduce the core logic for testing (without stderr warning)."""
        if not abilities:
            return None
        if len(abilities) == 1:
            return abilities[0]
        for ability_row in abilities:
            ability_json = json.loads(ability_row["monster_ability"])
            if ability_json.get("edition") == target_edition:
                return ability_row
        return abilities[0]

    def test_empty_returns_none(self):
        assert self._pick_best_ability([], "remastered") is None

    def test_single_ability_returns_it(self):
        row = self._make_ability_row("Grab", "legacy")
        assert self._pick_best_ability([row], "remastered") is row

    def test_matches_target_edition(self):
        legacy = self._make_ability_row("Grab", "legacy")
        remastered = self._make_ability_row("Grab", "remastered")
        result = self._pick_best_ability([legacy, remastered], "remastered")
        assert result is remastered

    def test_matches_legacy_edition(self):
        legacy = self._make_ability_row("Grab", "legacy")
        remastered = self._make_ability_row("Grab", "remastered")
        result = self._pick_best_ability([legacy, remastered], "legacy")
        assert result is legacy

    def test_no_match_returns_first(self):
        a = self._make_ability_row("Grab", "legacy")
        b = self._make_ability_row("Grab", "legacy")
        result = self._pick_best_ability([a, b], "remastered")
        assert result is a

    def test_none_edition_returns_first(self):
        a = self._make_ability_row("Grab")  # no edition field
        b = self._make_ability_row("Grab")
        result = self._pick_best_ability([a, b], "remastered")
        assert result is a
