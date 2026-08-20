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

    def _extract(self, monkeypatch, payload):
        from pfsrd2.enrichment import llm_extractor

        monkeypatch.setattr(
            llm_extractor, "_query_ollama_structured", lambda *a, **k: payload
        )
        return llm_extractor.extract_damage_structured("X", "some text")

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
