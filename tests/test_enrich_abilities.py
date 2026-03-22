"""Tests for pf2_enrich_abilities helper functions."""

import importlib.util
import os
import types

import pytest

# Import the bin script as a module (no .py extension, so we need submodule_search_locations)
_script_path = os.path.join(os.path.dirname(__file__), "..", "bin", "pf2_enrich_abilities")
_loader = importlib.machinery.SourceFileLoader("pf2_enrich_abilities", _script_path)
_spec = importlib.util.spec_from_loader("pf2_enrich_abilities", _loader)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

_format_regex_result = _mod._format_regex_result
_format_missed_reason = _mod._format_missed_reason


class TestFormatRegexResult:
    def test_new_saving_throw(self):
        result = {"saving_throw": [{"dc": 30}]}
        ability = {}
        fields = _format_regex_result(result, ability)
        assert fields == ["DC 30"]

    def test_existing_saving_throw_skipped(self):
        result = {"saving_throw": [{"dc": 30}]}
        ability = {"saving_throw": {"existing": True}}
        fields = _format_regex_result(result, ability)
        assert fields == []

    def test_new_area_single(self):
        result = {"area": [{"size": 30, "shape": "cone"}]}
        ability = {}
        fields = _format_regex_result(result, ability)
        assert fields == ["30-foot cone"]

    def test_new_area_multiple(self):
        result = {"area": [{"size": 30, "shape": "cone"}, {"size": 60, "shape": "line"}]}
        ability = {}
        fields = _format_regex_result(result, ability)
        assert "30-foot cone" in fields
        assert "60-foot line" in fields

    def test_existing_area_skipped(self):
        result = {"area": [{"size": 30, "shape": "cone"}]}
        ability = {"area": [{"existing": True}]}
        fields = _format_regex_result(result, ability)
        assert fields == []

    def test_new_damage(self):
        result = {"damage": [{"formula": "2d6", "damage_type": "fire"}]}
        ability = {}
        fields = _format_regex_result(result, ability)
        assert fields == ["2d6 fire"]

    def test_damage_without_type(self):
        result = {"damage": [{"formula": "3d8"}]}
        ability = {}
        fields = _format_regex_result(result, ability)
        assert fields == ["3d8 untyped"]

    def test_multiple_damage(self):
        result = {
            "damage": [
                {"formula": "2d6", "damage_type": "fire"},
                {"formula": "1d8", "damage_type": "cold"},
            ]
        }
        ability = {}
        fields = _format_regex_result(result, ability)
        assert "2d6 fire" in fields
        assert "1d8 cold" in fields

    def test_existing_damage_skipped(self):
        result = {"damage": [{"formula": "2d6", "damage_type": "fire"}]}
        ability = {"damage": [{"existing": True}]}
        fields = _format_regex_result(result, ability)
        assert fields == []

    def test_new_frequency(self):
        result = {"frequency": "1d4 rounds"}
        ability = {}
        fields = _format_regex_result(result, ability)
        assert fields == ["freq: 1d4 rounds"]

    def test_existing_frequency_skipped(self):
        result = {"frequency": "1d4 rounds"}
        ability = {"frequency": "once per day"}
        fields = _format_regex_result(result, ability)
        assert fields == []

    def test_all_fields_new(self):
        result = {
            "saving_throw": [{"dc": 25}],
            "area": [{"size": 60, "shape": "cone"}],
            "damage": [{"formula": "10d6", "damage_type": "acid"}],
            "frequency": "1d4 rounds",
        }
        ability = {}
        fields = _format_regex_result(result, ability)
        assert len(fields) == 4

    def test_empty_result(self):
        fields = _format_regex_result({}, {})
        assert fields == []


class TestFormatMissedReason:
    def test_single_keyword_zero_extracted(self):
        missed = {"dc": (1, 0)}
        assert _format_missed_reason(missed) == "unextracted: dc(1)"

    def test_single_keyword_partial_extracted(self):
        missed = {"damage": (3, 1)}
        assert _format_missed_reason(missed) == "unextracted: damage(1/3)"

    def test_multiple_keywords_sorted(self):
        missed = {"dc": (1, 0), "area": (2, 0)}
        reason = _format_missed_reason(missed)
        assert reason == "unextracted: area(2), dc(1)"

    def test_mixed_formats(self):
        missed = {"dc": (1, 0), "damage": (2, 1)}
        reason = _format_missed_reason(missed)
        assert reason == "unextracted: damage(1/2), dc(1)"
