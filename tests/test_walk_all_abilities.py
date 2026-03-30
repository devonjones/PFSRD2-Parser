"""Tests for _walk_all_abilities in ability_enrichment.py."""

from pfsrd2.ability_enrichment import _walk_all_abilities


def _ability(name, **kwargs):
    """Helper to build a minimal ability dict."""
    a = {"type": "stat_block_section", "subtype": "ability", "name": name}
    a.update(kwargs)
    return a


class TestWalkAllAbilities:
    def test_direct_abilities_list(self):
        struct = {"abilities": [_ability("Grab"), _ability("Swallow Whole")]}
        result = list(_walk_all_abilities(struct))
        assert len(result) == 2
        assert result[0]["name"] == "Grab"
        assert result[1]["name"] == "Swallow Whole"

    def test_nested_in_changes(self):
        struct = {
            "subtypes": [
                {
                    "changes": [
                        {"abilities": [_ability("Frightful Presence")]},
                        {"abilities": [_ability("Breath Weapon")]},
                    ]
                }
            ]
        }
        result = list(_walk_all_abilities(struct))
        assert len(result) == 2
        names = {a["name"] for a in result}
        assert names == {"Frightful Presence", "Breath Weapon"}

    def test_skips_non_abilities(self):
        """Objects with subtype != 'ability' should be skipped."""
        struct = {
            "abilities": [
                _ability("Grab"),
                {"type": "stat_block_section", "subtype": "spell", "name": "Fireball"},
            ]
        }
        result = list(_walk_all_abilities(struct))
        assert len(result) == 1
        assert result[0]["name"] == "Grab"

    def test_skips_stages(self):
        """Stages inside abilities should not be yielded."""
        struct = {
            "abilities": [
                _ability(
                    "Poison",
                    stages=[
                        {"type": "stat_block_section", "subtype": "ability", "name": "Stage 1"}
                    ],
                )
            ]
        }
        result = list(_walk_all_abilities(struct))
        assert len(result) == 1
        assert result[0]["name"] == "Poison"

    def test_skips_result_blocks(self):
        """Result block keys should not be recursed into."""
        struct = {"abilities": [_ability("Trip", critical_success="The target falls prone.")]}
        result = list(_walk_all_abilities(struct))
        assert len(result) == 1

    def test_empty_struct(self):
        assert list(_walk_all_abilities({})) == []

    def test_list_input(self):
        items = [
            {"abilities": [_ability("A")]},
            {"abilities": [_ability("B")]},
        ]
        result = list(_walk_all_abilities(items))
        assert len(result) == 2

    def test_deeply_nested(self):
        struct = {
            "monster_family": {
                "subtypes": [{"sections": [{"changes": [{"abilities": [_ability("Deep")]}]}]}]
            }
        }
        result = list(_walk_all_abilities(struct))
        assert len(result) == 1
        assert result[0]["name"] == "Deep"
