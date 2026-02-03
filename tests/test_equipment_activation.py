"""Tests for equipment activation parsing."""

import json
import os
import subprocess
import sys

import pytest


def parse_equipment_file(filename, equipment_type="equipment"):
    """Parse an equipment file and return the JSON output."""
    bin_dir = os.path.join(os.path.dirname(__file__), "..", "bin")
    script = os.path.join(bin_dir, "pf2_equipment_parse")

    result = subprocess.run(
        [sys.executable, script, equipment_type, filename, "-d", "-s", "--skip-schema"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Parse failed: {result.stderr}")
    return json.loads(result.stdout)


class TestActivationCruftCleanup:
    """Test that activation cruft is removed from stat_block text."""

    def test_item_489_text_cleaned(self):
        """Item 489 (Demilich Eye Gem) should have clean text without activation cruft.

        The text should not contain **Activate**, <b>Activate</b>, or related cruft
        after the activation is extracted into the abilities array.
        """
        test_file = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "pfsrd2-web",
            "2e.aonprd.com",
            "Equipment",
            "Equipment.aspx.ID_489.html",
        )
        if not os.path.exists(test_file):
            pytest.skip(f"Test file not found: {test_file}")

        result = parse_equipment_file(test_file)
        sb = result["stat_block"]

        # Text should not contain activation patterns
        text = sb.get("text", "")
        assert "Activate" not in text, f"Text should not contain 'Activate': {text}"
        assert "Frequency" not in text, f"Text should not contain 'Frequency': {text}"

        # Text should still have the description
        assert "demilich" in text.lower(), f"Text should contain description: {text}"

    def test_item_489_activation_extracted(self):
        """Item 489 should have activation properly extracted into abilities."""
        test_file = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "pfsrd2-web",
            "2e.aonprd.com",
            "Equipment",
            "Equipment.aspx.ID_489.html",
        )
        if not os.path.exists(test_file):
            pytest.skip(f"Test file not found: {test_file}")

        result = parse_equipment_file(test_file)
        statistics = result["stat_block"].get("statistics", {})
        abilities = statistics.get("abilities", [])

        # Should have at least one activation
        assert len(abilities) >= 1, "Should have at least one ability"

        # Find the activation
        activations = [a for a in abilities if a.get("subtype") == "activation"]
        assert len(activations) >= 1, "Should have at least one activation"

        activation = activations[0]
        assert activation["name"] == "Activate", "Activation name should be 'Activate'"
        assert (
            activation["frequency"] == "once per day"
        ), f"Frequency should be 'once per day', got: {activation.get('frequency')}"
        assert "effect" in activation, "Activation should have effect field"


class TestMultipleActivationTypes:
    """Test that multiple activation types are properly parsed as list of objects."""

    def test_item_489_activation_types_as_list(self):
        """Item 489 activation should be a list of activation_type objects."""
        test_file = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "pfsrd2-web",
            "2e.aonprd.com",
            "Equipment",
            "Equipment.aspx.ID_489.html",
        )
        if not os.path.exists(test_file):
            pytest.skip(f"Test file not found: {test_file}")

        result = parse_equipment_file(test_file)
        statistics = result["stat_block"].get("statistics", {})
        abilities = statistics.get("abilities", [])
        activations = [a for a in abilities if a.get("subtype") == "activation"]
        activation = activations[0]

        # Activation should be a list
        assert isinstance(
            activation.get("activation_types"), list
        ), f"Activation should be a list, got: {type(activation.get('activation'))}"

        # Should have both "command" and "interact" (lowercased)
        activation_values = [at["value"] for at in activation["activation_types"]]
        assert (
            "command" in activation_values
        ), f"Activation should contain 'command', got: {activation_values}"
        assert (
            "interact" in activation_values
        ), f"Activation should contain 'interact', got: {activation_values}"

    def test_item_759_multiple_activation_types(self):
        """Item 759 should have activation with command and Interact as separate objects."""
        test_file = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "pfsrd2-web",
            "2e.aonprd.com",
            "Equipment",
            "Equipment.aspx.ID_759.html",
        )
        if not os.path.exists(test_file):
            pytest.skip(f"Test file not found: {test_file}")

        result = parse_equipment_file(test_file)
        statistics = result["stat_block"].get("statistics", {})
        abilities = statistics.get("abilities", [])

        # Find the activation
        activations = [a for a in abilities if a.get("subtype") == "activation"]
        assert len(activations) >= 1, "Should have at least one activation"

        activation = activations[0]

        # Activation should be a list of activation_type objects
        assert isinstance(
            activation.get("activation_types"), list
        ), f"Activation should be a list, got: {type(activation.get('activation'))}"
        assert (
            len(activation["activation_types"]) == 2
        ), f"Should have 2 activation types, got: {len(activation['activation'])}"

        # Each should be a proper activation_type object
        for at in activation["activation_types"]:
            assert at["type"] == "stat_block_section", f"Type should be 'stat_block_section': {at}"
            assert at["subtype"] == "activation_type", f"Subtype should be 'activation_type': {at}"
            assert "value" in at, f"Should have 'value' field: {at}"

        # Should have both "command" and "interact" (lowercased)
        activation_values = [at["value"] for at in activation["activation_types"]]
        assert (
            "command" in activation_values
        ), f"Activation should contain 'command', got: {activation_values}"
        assert (
            "interact" in activation_values
        ), f"Activation should contain 'interact', got: {activation_values}"


class TestPriceParsing:
    """Test price string parsing into structured object."""

    def test_item_489_price_with_modifier(self):
        """Item 489 should have price as structured object with modifier."""
        test_file = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "pfsrd2-web",
            "2e.aonprd.com",
            "Equipment",
            "Equipment.aspx.ID_489.html",
        )
        if not os.path.exists(test_file):
            pytest.skip(f"Test file not found: {test_file}")

        result = parse_equipment_file(test_file)
        sb = result["stat_block"]

        # Price should be an object, not a string
        price = sb.get("price")
        assert isinstance(price, dict), f"Price should be a dict, got: {type(price)}"

        # Check structure
        assert price["type"] == "stat_block_section", f"Price type: {price.get('type')}"
        assert price["subtype"] == "price", f"Price subtype: {price.get('subtype')}"
        assert price["value"] == 3000, f"Price value should be 3000, got: {price.get('value')}"
        assert (
            price["currency"] == "gp"
        ), f"Price currency should be 'gp', got: {price.get('currency')}"
        assert (
            price["text"] == "3,000 gp"
        ), f"Price text should be '3,000 gp', got: {price.get('text')}"

        # Should have modifier
        modifiers = price.get("modifiers", [])
        assert len(modifiers) == 1, f"Should have 1 modifier, got: {len(modifiers)}"
        assert (
            modifiers[0]["name"] == "can't be crafted"
        ), f"Modifier name: {modifiers[0].get('name')}"

    def test_item_150_price_without_modifier(self):
        """Item 150 (Demon Armor) should have price without modifiers."""
        test_file = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "pfsrd2-web",
            "2e.aonprd.com",
            "Equipment",
            "Equipment.aspx.ID_150.html",
        )
        if not os.path.exists(test_file):
            pytest.skip(f"Test file not found: {test_file}")

        result = parse_equipment_file(test_file)
        sb = result["stat_block"]

        # Price should be an object
        price = sb.get("price")
        assert isinstance(price, dict), f"Price should be a dict, got: {type(price)}"

        # Check structure - Demon Armor costs 2,500 gp
        assert price["value"] == 2500, f"Price value should be 2500, got: {price.get('value')}"
        assert (
            price["currency"] == "gp"
        ), f"Price currency should be 'gp', got: {price.get('currency')}"

        # Should not have modifiers
        assert (
            "modifiers" not in price or len(price.get("modifiers", [])) == 0
        ), f"Should not have modifiers, got: {price.get('modifiers')}"


class TestCraftRequirements:
    """Test craft requirements text normalization."""

    def test_item_489_craft_requirements_no_newlines(self):
        """Item 489 craft_requirements should have no newlines in text."""
        test_file = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "pfsrd2-web",
            "2e.aonprd.com",
            "Equipment",
            "Equipment.aspx.ID_489.html",
        )
        if not os.path.exists(test_file):
            pytest.skip(f"Test file not found: {test_file}")

        result = parse_equipment_file(test_file)
        sb = result["stat_block"]

        craft_req = sb.get("craft_requirements", "")
        assert (
            "\n" not in craft_req
        ), f"Craft requirements should not contain newlines: {repr(craft_req)}"
        assert "Demilich eye gems" in craft_req, f"Should contain item name: {craft_req}"
        assert "can't be crafted" in craft_req, f"Should contain restriction: {craft_req}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
