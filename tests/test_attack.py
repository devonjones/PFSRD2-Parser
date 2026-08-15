"""Tests for universal/attack.py.

The module was nested inside pfsrd2/creatures.py until it was hoisted for
hazards to share. parse_attack_damage had tests via test_creatures.py;
parse_attack_action and remove_html_weapon were private and had none, so most
of the module was only ever exercised through full-corpus parser runs.
"""

import pytest

from universal.attack import parse_attack_action, parse_attack_damage, remove_html_weapon

MAP_LINK = '<a aonid="322" game-obj="Rules">+12/+8</a>'


def _attack(text, attack_type="melee", **extra):
    section = {"name": "Melee", "text": text}
    section.update(extra)
    parse_attack_action(section, attack_type)
    return section["attack"]


class TestAttackBonus:
    def test_the_multiple_attack_progression_is_kept(self):
        # A creature prints all three; losing the bracket loses two of them.
        attack = _attack(f"tentacle +16 [{MAP_LINK}], Damage 2d8+10 bludgeoning")
        assert attack["bonus"]["bonuses"] == [16, 12, 8]
        assert attack["bonus"]["link"]["aonid"] == 322

    def test_the_progression_survives_alongside_traits(self):
        attack = _attack(
            f"tentacle +16 [{MAP_LINK}] "
            '(<a aonid="170" game-obj="Traits">agile</a>), Damage 2d8+10 bludgeoning'
        )
        assert attack["bonus"]["bonuses"] == [16, 12, 8]
        assert [t["name"] for t in attack["traits"]] == ["agile"]

    def test_a_single_bonus_when_no_bracket_is_printed(self):
        # How every hazard publishes it.
        assert _attack("clockwork fist +29, Damage 2d10+18 bludgeoning")["bonus"]["bonuses"] == [29]

    def test_a_negative_bonus(self):
        assert _attack("rusty blade -2, Damage 1d6 slashing")["bonus"]["bonuses"] == [-2]

    def test_a_space_between_the_sign_and_the_digits(self):
        # Defensive: the hoisted normalisation exists for HTML5 spacing
        # artefacts, though no current attack line carries one.
        assert _attack("pincer + 14, Damage 1d8 bludgeoning")["bonus"]["bonuses"] == [14]

    def test_an_unparseable_line_fails_loudly(self):
        with pytest.raises(AssertionError, match="Failed to parse"):
            _attack("stalactite +16")


class TestWeapon:
    def test_the_weapon_name_is_kept(self):
        assert _attack("scythe +25, Damage 2d12 slashing")["weapon"] == "scythe"

    def test_a_linked_weapon_keeps_its_link_and_loses_its_markup(self):
        attack = _attack('<a aonid="1" game-obj="Equipment">longsword</a> +20, Damage 1d8 slashing')
        assert attack["weapon"] == "longsword"
        assert [link["name"] for link in attack["links"]] == ["longsword"]

    def test_remove_html_weapon_unwraps_an_italic_name(self):
        section = {}
        assert remove_html_weapon("<i>spectral hand</i>", section) == "spectral hand"

    def test_remove_html_weapon_harvests_links(self):
        section = {}
        out = remove_html_weapon('<a aonid="7" game-obj="Equipment">maul</a>', section)
        assert out == "maul"
        assert [link["aonid"] for link in section["links"]] == [7]


class TestRequirements:
    def test_a_requirement_after_the_damage_is_split_out(self):
        # "coils +20 [...], Damage 2d12+9 bludgeoning; Requirements ..." is how
        # the source publishes it.
        attack = _attack(
            "coils +20, <b>Damage</b> 2d12+9 bludgeoning; "
            "<b>Requirements</b> The serpent is in constrictor mode"
        )
        assert attack["requirement"] == "The serpent is in constrictor mode"
        assert attack["damage"][0]["formula"] == "2d12+9"

    def test_a_line_without_requirements_gets_none(self):
        assert "requirement" not in _attack("claw +20, Damage 1d6 slashing")


class TestDamage:
    def test_formula_and_type(self):
        damage = parse_attack_damage("2d8+10 bludgeoning")[0]
        assert (damage["formula"], damage["damage_type"]) == ("2d8+10", "bludgeoning")

    def test_persistent_damage_is_flagged(self):
        damage = parse_attack_damage("1d6 persistent bleed")[0]
        assert damage["persistent"] is True
        assert damage["damage_type"] == "bleed"

    def test_splash_damage_is_flagged(self):
        damage = parse_attack_damage("1d6 fire splash")[0]
        assert damage.get("splash") is True

    def test_an_en_dash_is_normalised_to_a_minus(self):
        # Not on any attack line today; the normalisation came with the hoist.
        assert parse_attack_damage("2d6–1 slashing")[0]["formula"] == "2d6-1"

    def test_a_redundant_damage_suffix_is_dropped(self):
        assert parse_attack_damage("5d8+18 positive damage")[0]["damage_type"] == "positive"

    def test_a_bare_damage_type_means_it_varies(self):
        damage = parse_attack_damage("2d10 damage (fire from the city, sonic from the storm)")[0]
        assert damage["damage_type"] == "varies"

    def test_a_link_inside_the_damage_type_is_harvested(self):
        damage = parse_attack_damage('1d6 <a aonid="29" game-obj="Conditions">bleed</a>')[0]
        assert [link["name"] for link in damage["links"]] == ["bleed"]

    def test_a_link_inside_a_parenthetical_note_is_harvested(self):
        damage = parse_attack_damage('2d6 slashing (<a aonid="170" game-obj="Traits">agile</a>)')[0]
        assert [link["name"] for link in damage["links"]] == ["agile"]

    def test_plus_separates_two_instances(self):
        damages = parse_attack_damage("4d6+10 slashing plus 1d6 fire")
        assert [d["damage_type"] for d in damages] == ["slashing", "fire"]

    def test_an_effect_tail_becomes_an_effect_entry(self):
        damages = parse_attack_damage("2d6 slashing plus grab")
        assert damages[1]["effect"] == "grab"


class TestAbilityDamageDelegation:
    """universal/ability.py parses ability damage with this module.

    The link used to be a lazy import wrapped in `except ImportError: pass`,
    so when it broke the damage silently degraded to an unparsed blob. Nothing
    else pins that ability.py still calls through.
    """

    def test_ability_damage_is_parsed_not_dumped_into_effect(self):
        from universal.ability import _parse_damage

        damage = _parse_damage("2d6 fire")[0]
        assert (damage["formula"], damage["damage_type"]) == ("2d6", "fire")
        assert "effect" not in damage

    def test_empty_damage_yields_nothing(self):
        from universal.ability import _parse_damage

        assert _parse_damage("") == []
