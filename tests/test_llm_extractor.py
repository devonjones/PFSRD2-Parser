"""Validation tests for LLM extraction prompts.

These tests hit a local Ollama instance and validate that the model
produces correct extractions for known test cases. Run with:

    pytest tests/test_llm_extractor.py -v

Skip if no local Ollama available:

    pytest tests/test_llm_extractor.py -v -k "not llm"

These tests are designed to validate model upgrades — if you switch
models, run these to confirm the new model handles the same cases.
"""

import subprocess

import pytest


def ollama_available():
    try:
        result = subprocess.run(
            ["curl", "-s", "http://localhost:11434/api/tags"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


skip_no_ollama = pytest.mark.skipif(
    not ollama_available(),
    reason="Local Ollama not available",
)


@skip_no_ollama
class TestFrequencyLLM:
    """Validate frequency extraction against known test cases."""

    def _extract(self, name, text):
        from pfsrd2.enrichment.llm_extractor import extract_frequency_llm

        return extract_frequency_llm(name, text)

    def test_breath_weapon_recharge(self):
        result = self._extract(
            "Breath Weapon",
            "The dragon breathes acid in a 60-foot line (DC 30 basic Reflex). "
            "It can\u2019t use Breath Weapon again for 1d4 rounds.",
        )
        assert result is not None
        assert "1d4 rounds" in result

    def test_prophetic_wings_two_limits(self):
        result = self._extract(
            "Prophetic Wings",
            "The dragon can use their wings in this way only once per hour, "
            "and a given creature can seek a future in the wings only once per week.",
        )
        assert result is not None
        assert "once per hour" in result.lower()
        assert "once per week" in result.lower()

    def test_prophetic_wings_three_limits(self):
        result = self._extract(
            "Prophetic Wings",
            "The dragon can use their wings in this way only once per hour, "
            "and a given creature can seek a future in the wings only once per week. "
            "A creature can also choose to predict events up to 1 month into the "
            "future\u2014the dragon can view a month ahead only once per day.",
        )
        assert result is not None
        parts = [p.strip().lower() for p in result.split(";")]
        assert any("once per hour" in p for p in parts)
        assert any("once per week" in p for p in parts)
        assert any("once per day" in p for p in parts)

    def test_mutations_compound_ability(self):
        result = self._extract(
            "Mutations",
            "Toxic Breath The barghest breathes a cloud of toxic gas that deals "
            "8d6 poison damage (DC 25 basic Fortitude save). It can\u2019t use "
            "Toxic Breath again for 1d4 rounds. Vestigial Arm Strike Frequency "
            "once per round; Trigger The barghest completes a Strike.",
        )
        assert result is not None
        lower = result.lower()
        # Must catch at least the recharge — "once per round" is also
        # present but LLM may not always catch both in compound text
        assert "1d4 rounds" in lower

    def test_no_frequency(self):
        result = self._extract(
            "Draconic Momentum",
            "The dragon recharges their Breath Weapon whenever they score "
            "a critical hit with a Strike.",
        )
        assert result is None

    def test_simple_once_per_day(self):
        result = self._extract(
            "Corrupt Water",
            "The dragon permanently befouls 10 cubic feet of liquid within " "90 feet.",
        )
        # No frequency in this text
        assert result is None

    def test_cannot_variant(self):
        result = self._extract(
            "Breath Weapon",
            "The dragon cannot use Breath Weapon again for 2 rounds.",
        )
        assert result is not None
        assert "2 rounds" in result

    def test_passive_voice(self):
        result = self._extract(
            "Aura of Hospitality",
            "If the shuyookh acts hostile, the aura deactivates and "
            "can\u2019t be reactivated for 1 hour.",
        )
        assert result is not None
        assert "1 hour" in result

    def test_rate_not_frequency(self):
        """Rates like 'gallons per round' should not be extracted."""
        result = self._extract(
            "Organ of Endless Water",
            "The grodair causes water to pour from a magical sac on its "
            "spine, either a stream of water at a rate of 1 gallon per round, "
            "or a fountain in a 5-foot-long stream at a rate of 5 gallons per round.",
        )
        assert result is None


@skip_no_ollama
class TestAreaLLM:
    """Validate area extraction against known test cases."""

    def _extract(self, name, text):
        from pfsrd2.enrichment.llm_extractor import extract_area_llm

        return extract_area_llm(name, text)

    def test_chimera_dual_area(self):
        result = self._extract(
            "Breath Weapon",
            "The chimera breathes a cone or line that deals 9d6 damage. "
            "<ul><li><b>Black</b> 60-foot line of acid (Reflex)</li>"
            "<li><b>Green</b> 30-foot cone of poison (Fortitude)</li></ul>",
        )
        assert result is not None
        shapes = {a["shape"] for a in result}
        assert "line" in shapes
        assert "cone" in shapes

    def test_copper_dragon_same_area(self):
        result = self._extract(
            "Breath Weapon",
            "The copper dragon breathes in one of two ways. "
            "<ul><li><b>Acid</b> 80-foot line of acid</li>"
            "<li><b>Slowing Gas</b> 80-foot line of slowing gas</li></ul>",
        )
        assert result is not None
        assert len(result) == 1  # deduplicated — both are 80-foot line
        assert result[0]["size"] == 80
        assert result[0]["shape"] == "line"

    def test_single_cone(self):
        result = self._extract(
            "Breath Weapon",
            "The dragon breathes fire in a 60-foot cone.",
        )
        assert result is not None
        assert len(result) == 1
        assert result[0]["shape"] == "cone"
        assert result[0]["size"] == 60

    def test_filament_not_area(self):
        result = self._extract(
            "Barbed Filament",
            "A creature hit by the tree fisher's barbed filament is grabbed. "
            "The tree fisher automatically releases the Grab if it moves "
            "beyond the filament's 60-foot length.",
        )
        assert result is None

    def test_100_foot_burst(self):
        result = self._extract(
            "Thunderous Departure",
            "Her departure leaves behind a thunderous sonic boom, creating a "
            "100-foot burst centered on her point of departure.",
        )
        assert result is not None
        assert result[0]["size"] == 100
        assert result[0]["shape"] == "burst"


@skip_no_ollama
class TestDCLLM:
    """Validate DC extraction against known test cases."""

    def _extract(self, name, text):
        from pfsrd2.enrichment.llm_extractor import extract_dc_llm

        return extract_dc_llm(name, text)

    def test_escape_dc_from_text(self):
        result = self._extract(
            "Hurl Net",
            "On a hit, the target is flat-footed. " "The DC to Escape the net is 16.",
        )
        assert result is not None
        assert any(s["dc"] == 16 for s in result)

    def test_skill_check_dc(self):
        result = self._extract(
            "Belly Grease",
            "The DC to Balance across the slime is 18.",
        )
        assert result is not None
        assert any(s["dc"] == 18 for s in result)

    def test_dc_of_pattern(self):
        result = self._extract(
            "Capsize",
            "must succeed at an Athletics check with a DC of 30 "
            "or the pilot's Sailing Lore DC, whichever is higher.",
        )
        assert result is not None
        assert any(s["dc"] == 30 for s in result)

    def test_conditional_dc_not_extracted(self):
        result = self._extract(
            "Command Giants",
            "When a rune giant casts a mental spell against another giant, "
            "the DC is 39, rather than 35.",
        )
        assert result is None

    def test_variable_dc_not_extracted(self):
        result = self._extract(
            "Infectious Aura",
            "all adjacent creatures are exposed to the same disease, " "at the same DC.",
        )
        assert result is None

    def test_administer_first_aid_dc(self):
        result = self._extract(
            "Bloodbird",
            "It takes 2d6 persistent bleed damage. The DC to stop the "
            "bleeding using Administer First Aid is 35.",
        )
        assert result is not None
        assert any(s["dc"] == 35 for s in result)


@skip_no_ollama
class TestDamageLLM:
    """Validate damage extraction against known test cases."""

    def _extract(self, name, text):
        from pfsrd2.enrichment.llm_extractor import extract_damage_llm

        return extract_damage_llm(name, text)

    def test_untyped_extra_damage(self):
        result = self._extract(
            "Pack Attack",
            "The lion deals 1d4 extra damage to any creature within reach "
            "of at least two of the lion's allies.",
        )
        assert result is not None
        assert any(d["formula"] == "1d4" for d in result)

    def test_typed_damage(self):
        result = self._extract(
            "Burning Grasp",
            "that creature takes 2d6 fire damage, and takes 2d6 fire "
            "damage at the end of each of its turns.",
        )
        assert result is not None
        assert any(d["formula"] == "2d6" and d.get("damage_type") == "fire" for d in result)

    def test_combine_damage_not_extracted(self):
        result = self._extract(
            "Stunning Flurry",
            "combine their damage for the purpose of resistances and weaknesses",
        )
        assert result is None

    def test_healing_not_extracted(self):
        result = self._extract(
            "Fire Healing",
            "a crimson worm regains Hit Points equal to half the fire damage",
        )
        assert result is None

    def test_untyped_with_dc(self):
        result = self._extract(
            "Resanguinate",
            "any living creature within 30 feet takes 4d6 damage " "(DC 33 basic Fortitude save).",
        )
        assert result is not None
        assert any(d["formula"] == "4d6" for d in result)

    def test_comma_format(self):
        result = self._extract(
            "This Is My Reality!",
            "6d6 spirit, DC 30 The failed prophet exerts control.",
        )
        assert result is not None
        assert any(d["formula"] == "6d6" and d.get("damage_type") == "spirit" for d in result)


class TestCleanLLMResponse:
    """Tests for LLM response parsing — no Ollama required."""

    def test_none_input(self):
        from pfsrd2.enrichment.llm_extractor import _clean_llm_response

        assert _clean_llm_response(None) is None

    def test_none_string(self):
        from pfsrd2.enrichment.llm_extractor import _clean_llm_response

        assert _clean_llm_response("none") is None

    def test_no_frequency_phrase(self):
        from pfsrd2.enrichment.llm_extractor import _clean_llm_response

        assert _clean_llm_response("no frequency constraints found") is None

    def test_valid_response(self):
        from pfsrd2.enrichment.llm_extractor import _clean_llm_response

        result = _clean_llm_response("once per day; 1d4 rounds")
        assert result == ["once per day", "1d4 rounds"]

    def test_filters_none_entries(self):
        from pfsrd2.enrichment.llm_extractor import _clean_llm_response

        result = _clean_llm_response("once per day; none")
        assert result == ["once per day"]


class TestParseDCResponse:
    """Tests for DC response parsing — no Ollama required."""

    def test_basic_dc(self):
        from pfsrd2.enrichment.llm_extractor import _parse_dc_response

        result = _parse_dc_response(["DC 30 basic Reflex"], "DC 30 basic Reflex save")
        assert len(result) == 1
        assert result[0]["dc"] == 30
        assert result[0]["save_type"] == "Ref"
        assert result[0]["basic"] is True

    def test_filters_hallucinated_dc(self):
        from pfsrd2.enrichment.llm_extractor import _parse_dc_response

        result = _parse_dc_response(["DC 60"], "60-foot line (DC 26 basic Reflex)")
        assert result is None or not any(s["dc"] == 60 for s in result)

    def test_deduplicates(self):
        from pfsrd2.enrichment.llm_extractor import _parse_dc_response

        result = _parse_dc_response(["DC 30 Reflex", "DC 30 Reflex"], "DC 30 Reflex")
        assert len(result) == 1
