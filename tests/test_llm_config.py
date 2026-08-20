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
