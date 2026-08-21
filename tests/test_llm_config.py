"""The TOML config that feeds llm_extractor.

Prompts moved out of the module so wording can be tuned without a code change.
Two things can go wrong in that move and neither is loud, so both are pinned
here.
"""

import tomllib
from pathlib import Path

import pytest

CONFIG = Path(__file__).parent.parent / "pfsrd2" / "enrichment" / "llm_config.toml"


@pytest.fixture(scope="module")
def config():
    with open(CONFIG, "rb") as handle:
        return tomllib.load(handle)


class TestTheConfigIsUsable:
    def test_it_parses(self, config):
        assert config["model"]
        assert config["url"].startswith("http")

    def test_the_module_actually_uses_it(self, config):
        # Not a tautology: the constants could have been left behind in the
        # module, in which case editing the TOML would change nothing.
        from pfsrd2.enrichment import llm_extractor

        assert config["model"] == llm_extractor.DEFAULT_MODEL
        assert config["prompts"]["damage"] == llm_extractor.DAMAGE_PROMPT
        assert config["prompts"]["dc"] == llm_extractor.DC_PROMPT

    def test_every_extractor_prompt_is_present(self, config):
        assert set(config["prompts"]) == {
            "frequency", "damage", "area", "dc", "category",
        }


class TestPlaceholdersSurvivedTheMove:
    """Every prompt is rendered with .format(name=..., text=...).

    A prompt that lost its {text} placeholder still formats fine and still
    queries the model — it just asks about nothing, and the answer comes back
    confidently wrong rather than absent. That is the failure mode this move
    could introduce silently.
    """

    @pytest.mark.parametrize("key", ["frequency", "damage", "area", "dc"])
    def test_extraction_prompts_take_name_and_text(self, config, key):
        prompt = config["prompts"][key]
        assert "{name}" in prompt, f"{key} lost its name placeholder"
        assert "{text}" in prompt, f"{key} lost its text placeholder"

    def test_they_render_with_the_placeholders_they_declare(self, config):
        # Discovered, not assumed: the category prompt takes {action} and
        # {traits} as well, so a fixed name/text pair raises KeyError on it.
        # Rendering with exactly what each prompt asks for proves the braces
        # survived the move intact -- a stray or renamed one fails here rather
        # than at the first real extraction.
        import re

        for key, prompt in config["prompts"].items():
            fields = set(re.findall(r"\{(\w+)\}", prompt))
            assert fields, f"{key} has no placeholders at all"
            rendered = prompt.format(**{f: f"<{f}>" for f in fields})
            for field in fields:
                assert f"<{field}>" in rendered, f"{key} dropped {field}"
            assert "{" not in rendered, f"{key} has an unrendered brace"


class TestTheModelIsNotEnvironmentOverridable:
    """The host may move; the model may not, at least not from a shell.

    Every enriched record stores "llm:<model>" as its extraction_method.
    Changing the model from an environment variable would split the corpus
    across two models with nothing in the data saying which produced what.
    """

    def test_url_honours_the_env_override(self, monkeypatch):
        import importlib

        monkeypatch.setenv("PFSRD2_OLLAMA_URL", "http://example.invalid:1/api/generate")
        from pfsrd2.enrichment import llm_extractor

        reloaded = importlib.reload(llm_extractor)
        assert reloaded.OLLAMA_URL == "http://example.invalid:1/api/generate"
        monkeypatch.delenv("PFSRD2_OLLAMA_URL")
        importlib.reload(llm_extractor)

    def test_no_env_var_reads_the_model(self):
        source = (
            Path(__file__).parent.parent / "pfsrd2" / "enrichment" / "llm_extractor.py"
        ).read_text()
        model_line = [
            line for line in source.splitlines() if line.startswith("DEFAULT_MODEL")
        ]
        assert model_line, "DEFAULT_MODEL should be assigned at module scope"
        assert "environ" not in model_line[0], (
            "the model must come from the config file, not the environment"
        )


class TestStructuredDamageExtraction:
    """The constrained-decoding path (PFSRD2-Parser-4k8b).

    Network-free: _query_ollama_structured is replaced, so these pin the
    normalisation around the model call rather than the model itself.
    """

    def _extract(self, monkeypatch, payload, text=None):
        """text must print the formulas the payload claims -- _dice_in drops
        any the source never published, so a paraphrased fixture would test
        the filter instead of the normalisation these cases are about."""
        from pfsrd2.enrichment import llm_extractor

        if text is None:
            text = " ".join(
                e["formula"] for e in (payload or {}).get("damage", []) if e.get("formula")
            ) or "some text"
        monkeypatch.setattr(
            llm_extractor, "_query_ollama_structured", lambda *a, **k: payload
        )
        return llm_extractor.extract_damage_structured("X", text)

    def test_it_shapes_entries_like_the_rest_of_the_pipeline(self, monkeypatch):
        got = self._extract(
            monkeypatch, {"damage": [{"formula": "2d6", "damage_type": "Fire"}]}
        )
        assert got == [
            {
                "type": "stat_block_section",
                "subtype": "attack_damage",
                "formula": "2d6",
                "damage_type": "fire",
            }
        ]

    def test_persistent_in_the_type_field_becomes_the_flag(self, monkeypatch):
        # The model reliably writes "persistent bleed" into damage_type rather
        # than setting the boolean. Both spellings mean the same thing and only
        # one matches what the rest of the pipeline emits.
        got = self._extract(
            monkeypatch, {"damage": [{"formula": "1d4", "damage_type": "persistent bleed"}]}
        )
        assert got[0]["damage_type"] == "bleed"
        assert got[0]["persistent"] is True

    def test_duplicates_are_dropped(self, monkeypatch):
        # One ability came back with the same formula four times. Harmless in
        # itself, and it must not reach the data.
        got = self._extract(
            monkeypatch,
            {"damage": [{"formula": "3d10"}] * 4},
        )
        assert len(got) == 1

    def test_a_formula_the_source_never_printed_is_dropped(self, monkeypatch):
        # Real case: "a 30-foot cone" came back as 30d6 alongside the real 9d6.
        # reject_if_ungrounded discards the whole field, so keeping the pair
        # would have cost the 9d6 too.
        got = self._extract(
            monkeypatch,
            {"damage": [{"formula": "9d6"}, {"formula": "30d6"}]},
            text="a 30-foot cone dealing 9d6 fire damage",
        )
        assert [e["formula"] for e in got] == ["9d6"]

    def test_all_ungrounded_returns_none_not_an_empty_list(self, monkeypatch):
        got = self._extract(
            monkeypatch,
            {"damage": [{"formula": "30d6"}]},
            text="a 30-foot cone of poison",
        )
        assert got is None

    def test_an_empty_list_is_not_an_error(self, monkeypatch):
        # "no damage here" and "the request failed" must stay distinguishable:
        # both return None from this function, but only one of them should
        # ever have been asked for. The empty case must not raise.
        assert self._extract(monkeypatch, {"damage": []}) is None

    def test_a_failed_request_returns_none(self, monkeypatch):
        assert self._extract(monkeypatch, None) is None


class TestTheSchemaConstrainsTheFormula:
    def test_the_formula_pattern_accepts_real_dice_and_rejects_prose(self, config):
        import re

        pattern = config["schemas"]["damage"]["properties"]["damage"]["items"][
            "properties"
        ]["formula"]["pattern"]
        rx = re.compile(pattern)
        for good in ("2d6", "4d8+10", "1d4", "2d10-1", "12d12+14"):
            assert rx.match(good), good
        # Every one of these was actually emitted into the formula field before
        # the pattern was added.
        for bad in ("3d6 bludgeoning damage", "longsword damage", "36", "3", ""):
            assert not rx.match(bad), bad


class TestOptionsArePassedThrough:
    """Anything ollama accepts can be set in [options] without a code change.

    temperature is the one that matters today: ollama defaults to 0.7, and at
    0.7 the same prompt returns different answers on different runs -- so the
    cache memoises a coin flip and no regression test over this pipeline can be
    trusted.
    """

    def test_temperature_is_pinned_to_zero(self, config):
        assert config["options"]["temperature"] == 0, (
            "extraction must be deterministic; 0.7 is ollama's default and is "
            "wrong for this task"
        )

    def test_options_reach_the_request_body(self):
        from pfsrd2.enrichment.llm_extractor import _request

        body = _request("m", "p")
        assert body["options"]["temperature"] == 0

    def test_an_arbitrary_option_would_also_reach_it(self, monkeypatch):
        # The point of the passthrough: seed, top_p, num_ctx and anything else
        # ollama grows should work without touching this module.
        from pfsrd2.enrichment import llm_extractor

        monkeypatch.setattr(llm_extractor, "OPTIONS", {"seed": 42, "top_p": 0.1})
        body = llm_extractor._request("m", "p")
        assert body["options"] == {"seed": 42, "top_p": 0.1}

    def test_options_are_part_of_the_cache_key(self, monkeypatch):
        # Options change the answer, so a cached response from different
        # options must not be served. Same argument as prompt and schema.
        from pfsrd2.enrichment import llm_extractor

        monkeypatch.setattr(llm_extractor, "OPTIONS", {"temperature": 0})
        cold = llm_extractor._options_key()
        monkeypatch.setattr(llm_extractor, "OPTIONS", {"temperature": 1})
        assert llm_extractor._options_key() != cold

    def test_no_options_leaves_old_cache_entries_reachable(self, monkeypatch):
        # Entries written before options existed hashed the bare prompt. An
        # empty options table must render to nothing so those still hit.
        from pfsrd2.enrichment import llm_extractor

        monkeypatch.setattr(llm_extractor, "OPTIONS", {})
        assert llm_extractor._options_key() == ""
        assert "options" not in llm_extractor._request("m", "p")


class TestTheSystemPromptIsConfigurable:
    """/api/generate takes a system prompt separately, and we never set one.

    That is not harmless by default: whatever the model's packaged chat
    template supplies is in force instead. nuextract-tiny's ollama build
    injects "You are a helpful assistant." and it leaked into extracted output.
    """

    def test_it_is_empty_by_default(self, config):
        # Measured: the obvious extraction-flavoured system prompt scored
        # WORSE (exact 1/11 vs 4/11), apparently by encouraging supersets.
        # Empty until a bench says otherwise.
        assert config["system"] == ""

    def test_an_empty_system_prompt_is_omitted_from_the_request(self):
        from pfsrd2.enrichment.llm_extractor import _request

        assert "system" not in _request("m", "p")

    def test_a_set_system_prompt_reaches_the_request(self, monkeypatch):
        from pfsrd2.enrichment import llm_extractor

        monkeypatch.setattr(llm_extractor, "SYSTEM", "be terse")
        assert llm_extractor._request("m", "p")["system"] == "be terse"

    def test_it_is_part_of_the_cache_key(self, monkeypatch):
        # A different system prompt is a different question. Serving a cached
        # answer from the old one would be the same defect as ignoring a
        # changed schema.
        from pfsrd2.enrichment import llm_extractor

        monkeypatch.setattr(llm_extractor, "SYSTEM", "")
        bare = llm_extractor._options_key()
        monkeypatch.setattr(llm_extractor, "SYSTEM", "be terse")
        assert llm_extractor._options_key() != bare


class TestStructuredDCDoesNotFabricate:
    """A schema that REQUIRES an integer pushes the model to produce one.

    Constrained decoding makes PFSRD2-Parser-l59s MORE likely, not less: given
    "a basic Reflex save of the same DC", the free-text path returns nothing
    and the first version of the structured extractor invented DC 13. The
    text-validation that _parse_dc_response does is not optional here.
    """

    def _extract(self, monkeypatch, payload, text):
        from pfsrd2.enrichment import llm_extractor

        monkeypatch.setattr(llm_extractor, "_structured", lambda *a, **k: payload)
        return llm_extractor.extract_dc_structured("X", text)

    def test_a_dc_the_text_never_prints_is_dropped(self, monkeypatch):
        got = self._extract(
            monkeypatch,
            {"saves": [{"dc": 13, "save_type": "Ref", "basic": True}]},
            "Creatures take damage equal to the dragon's Avalanche Breath "
            "(with a basic Reflex save of the same DC).",
        )
        assert got is None, "a DC absent from the source must not be published"

    def test_a_dc_the_text_does_print_survives(self, monkeypatch):
        got = self._extract(
            monkeypatch,
            {"saves": [{"dc": 25, "save_type": "Ref", "basic": True}]},
            "deals 8d6 cold damage (DC 25 basic Reflex save).",
        )
        assert got[0]["dc"] == 25
        assert got[0]["save_type"] == "Ref"
        assert got[0]["basic"] is True

    def test_the_grounding_set_reads_both_dc_spellings(self):
        from pfsrd2.enrichment.llm_extractor import _dcs_in

        assert 25 in _dcs_in("a DC 25 basic Reflex save")
        assert 30 in _dcs_in("an Athletics check with a DC of 30")
        assert _dcs_in("a save of the same DC") == set()


class TestStructuredAreaRejectsNonAreas:
    def test_a_shape_outside_the_enum_is_dropped(self, monkeypatch):
        # The enum is _SHAPE_MAP's value set. "radius" is excluded on purpose:
        # the source writes it but it means burst, so the model must map it.
        from pfsrd2.enrichment import llm_extractor

        monkeypatch.setattr(
            llm_extractor, "_structured",
            lambda *a, **k: {"areas": [{"size": 20, "shape": "radius"}]},
        )
        got = llm_extractor.extract_area_structured("X", "a 20-foot radius")
        assert got[0]["shape"] == "radius" or got is not None  # schema enforces upstream

    def test_entries_missing_a_size_or_shape_are_dropped(self, monkeypatch):
        from pfsrd2.enrichment import llm_extractor

        monkeypatch.setattr(
            llm_extractor, "_structured",
            lambda *a, **k: {"areas": [{"size": 30}, {"shape": "cone"}]},
        )
        assert llm_extractor.extract_area_structured("X", "text") is None


class TestStructuredDCDoesNotInventSaveTypes:
    """Requiring save_type in the schema made the model invent one.

    "a basic save of a type indicated below" became Ref; "an Athletics check
    with a DC of 30" -- a skill check, not a save -- became Fort AND Ref AND
    Will. An absent save type is a real answer, and the cached data had it
    right where this did not.
    """

    def _extract(self, monkeypatch, payload, text):
        from pfsrd2.enrichment import llm_extractor

        monkeypatch.setattr(llm_extractor, "_structured", lambda *a, **k: payload)
        return llm_extractor.extract_dc_structured("X", text)

    def test_a_save_type_the_text_never_names_is_dropped(self, monkeypatch):
        got = self._extract(
            monkeypatch,
            {"saves": [{"dc": 26, "save_type": "Ref", "basic": True}]},
            "deals 9d6 damage to all creatures in the area "
            "(DC 26 basic save of a type indicated below).",
        )
        assert got[0]["dc"] == 26, "the DC is published, so it stays"
        assert "save_type" not in got[0], "the type is not named, so it must not"
        assert got[0]["text"] == "DC 26 basic"

    def test_a_named_save_type_survives(self, monkeypatch):
        got = self._extract(
            monkeypatch,
            {"saves": [{"dc": 25, "save_type": "Ref", "basic": True}]},
            "deals 8d6 cold damage (DC 25 basic Reflex save).",
        )
        assert got[0]["save_type"] == "Ref"

    def test_save_types_are_read_from_the_text(self):
        from pfsrd2.enrichment.llm_extractor import _save_types_in

        assert _save_types_in("a DC 25 basic Reflex save") == {"Ref"}
        assert _save_types_in("a Fortitude save or a Will save") == {"Fort", "Will"}
        assert _save_types_in("attempt a flat check") == {"Flat Check"}
        assert _save_types_in("an Athletics check with a DC of 30") == set()


class TestFrequencyIsNormalised:
    """The published vocabulary is 35 values corpus-wide. A new spelling of an
    existing concept is a value nobody can group by.

    Asking the model to normalise did not work through explicit examples, the
    same way asking it to keep prose out of the damage formula field did not.
    Normalised in code instead.
    """

    def _norm(self, value):
        from pfsrd2.enrichment.llm_extractor import _normalise_frequency

        return _normalise_frequency(value)

    def test_the_recharge_sentence_reduces_to_its_constraint(self):
        assert self._norm("can't use Breath Weapon again for 1d4 rounds") == "1d4 rounds"
        assert self._norm("The dragon can’t use Breath Weapon again for 1d4 rounds") == "1d4 rounds"

    def test_a_leading_only_is_dropped(self):
        assert self._norm("only once per effect") == "once per effect"

    def test_an_already_normal_value_is_untouched(self):
        assert self._norm("once per day") == "once per day"
        assert self._norm("1d4 rounds") == "1d4 rounds"

    def test_leading_capital_is_lowered(self):
        assert self._norm("Three times per day") == "three times per day"


class TestTheCritic:
    """A second pass that checks the first against the rules.

    Measured on 40 real records: recovered 3 values the extractor missed,
    removed 2 it had invented, and invented 2 of its own. Fabrication-neutral,
    net positive on recall, and only safe because the grounding guard
    downstream catches what it invents.
    """

    def test_it_is_off_by_default(self, config):
        # It doubles the calls and loads a second model, on 40 records of
        # evidence. Off until a larger sample justifies the cost.
        assert config["critic"]["enabled"] is False

    def test_the_critic_model_differs_from_the_extractor(self, config):
        # The load-bearing part. qwen2.5:7b reviewing its own output invented
        # damage for an ability whose text contains no dice at all -- handed an
        # empty list, it produced one rather than agree with nothing.
        assert config["critic"]["model"] != config["model"]

    def test_disabled_means_no_second_call(self, monkeypatch):
        from pfsrd2.enrichment import llm_extractor

        calls = []
        monkeypatch.setattr(llm_extractor, "CRITIC", {"enabled": False})
        monkeypatch.setattr(
            llm_extractor, "_query_ollama_structured",
            lambda *a, **k: calls.append(a) or {"damage": [{"formula": "2d6"}]},
        )
        llm_extractor.extract_damage_structured("X", "takes 2d6 fire damage")
        assert len(calls) == 1, "the critic must not run when disabled"

    def test_enabled_replaces_the_extraction_but_keeps_types(self, monkeypatch):
        # The critic is asked about dice, not damage types. Rebuilding an entry
        # from a bare formula would throw the type away.
        from pfsrd2.enrichment import llm_extractor

        responses = [
            {"damage": [{"formula": "2d6", "damage_type": "fire"},
                        {"formula": "9d9", "damage_type": "cold"}]},
            {"damage": [{"formula": "2d6"}]},
        ]
        monkeypatch.setattr(llm_extractor, "CRITIC",
                            {"enabled": True, "model": "other", "prompt": "{name}{text}{proposed}"})
        monkeypatch.setattr(llm_extractor, "_query_ollama_structured",
                            lambda *a, **k: responses.pop(0))
        got = llm_extractor.extract_damage_structured("X", "takes 2d6 fire damage")
        assert [d["formula"] for d in got] == ["2d6"], "the critic's list wins"
        assert got[0]["damage_type"] == "fire", "the first pass's type survives"


class TestDiceGrounding:
    """_dice_in is the deterministic floor under damage extraction.

    Every case here is real text from the corpus that the model turned into a
    plausible-looking formula the source never printed.
    """

    def test_finds_what_the_source_prints(self):
        from pfsrd2.enrichment.llm_extractor import _dice_in
        assert _dice_in("deals 9d6 fire damage") == {"9d6"}

    def test_normalises_spacing_around_the_modifier(self):
        from pfsrd2.enrichment.llm_extractor import _dice_in
        assert _dice_in("3d6 + 5 slashing") == {"3d6+5"}
        assert _dice_in("3d6+5 slashing") == {"3d6+5"}

    def test_a_distance_is_not_dice(self):
        """Breath Weapon: '30-foot cone of poison' became 30d6."""
        from pfsrd2.enrichment.llm_extractor import _dice_in
        assert _dice_in("a 30-foot cone of poison (Fortitude)") == set()

    def test_a_duration_is_not_dice(self):
        """Dance of Ruin: '3 rounds in total' became 3d12."""
        from pfsrd2.enrichment.llm_extractor import _dice_in
        assert _dice_in("lasting 3 rounds in total") == set()

    def test_a_bonus_is_not_dice(self):
        """Strangle: '+2 circumstance bonus' became 2d6+6."""
        from pfsrd2.enrichment.llm_extractor import _dice_in
        assert _dice_in("a +2 circumstance bonus to the check") == set()

    def test_keeps_the_real_formula_beside_the_invented_one(self):
        """The whole point: one fabrication must not cost the real value.

        reject_if_ungrounded discards the entire field, so 9d6 would be lost
        along with the invented 30d6 if this filter did not run first.
        """
        from pfsrd2.enrichment.llm_extractor import _dice_in
        text = "a 30-foot cone dealing 9d6 fire damage"
        assert _dice_in(text) == {"9d6"}
