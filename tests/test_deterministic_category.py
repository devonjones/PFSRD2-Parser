"""Tests for deterministic_ability_category in ability_placement.py."""

from pfsrd2.ability_placement import deterministic_ability_category


class TestDeterministicCategory:
    def test_reaction_is_reactive(self):
        ability = {
            "action_type": {
                "type": "stat_block_section",
                "subtype": "action_type",
                "name": "Reaction",
            }
        }
        assert deterministic_ability_category(ability) == "reactive"

    def test_one_action_is_offensive(self):
        ability = {
            "action_type": {
                "type": "stat_block_section",
                "subtype": "action_type",
                "name": "One Action",
            }
        }
        assert deterministic_ability_category(ability) == "offensive"

    def test_two_actions_is_offensive(self):
        ability = {
            "action_type": {
                "type": "stat_block_section",
                "subtype": "action_type",
                "name": "Two Actions",
            }
        }
        assert deterministic_ability_category(ability) == "offensive"

    def test_three_actions_is_offensive(self):
        ability = {
            "action_type": {
                "type": "stat_block_section",
                "subtype": "action_type",
                "name": "Three Actions",
            }
        }
        assert deterministic_ability_category(ability) == "offensive"

    def test_free_action_with_trigger_is_reactive(self):
        ability = {
            "action_type": {
                "type": "stat_block_section",
                "subtype": "action_type",
                "name": "Free Action",
            },
            "trigger": "An enemy enters your reach.",
        }
        assert deterministic_ability_category(ability) == "reactive"

    def test_free_action_without_trigger_is_none(self):
        ability = {
            "action_type": {
                "type": "stat_block_section",
                "subtype": "action_type",
                "name": "Free Action",
            }
        }
        assert deterministic_ability_category(ability) is None

    def test_no_action_type_returns_none(self):
        ability = {"name": "Darkvision", "text": "Can see in the dark."}
        assert deterministic_ability_category(ability) is None

    def test_action_type_not_dict_returns_none(self):
        ability = {"action_type": "One Action"}
        assert deterministic_ability_category(ability) is None

    def test_empty_ability_returns_none(self):
        assert deterministic_ability_category({}) is None
