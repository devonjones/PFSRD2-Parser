import pytest

from pfsrd2.enrichment import change_extractor


@pytest.fixture(autouse=True)
def stub_trait_items(monkeypatch):
    """Keep unit tests off the real traits DB (empty in CI).

    _trait_item resolves full canonical trait objects from ~/.pfsrd2's
    traits table; unit tests get a deterministic stub instead. The real
    lookup is covered by TestTraitItem, which monkeypatches the fetch
    layer directly.
    """

    def fake_trait_item(name):
        return {
            "name": name.title(),
            "game-id": f"test-{name.lower()}",
            "game-obj": "Traits",
            "classes": [],
            "type": "trait",
        }

    monkeypatch.setattr(change_extractor, "_trait_item", fake_trait_item)


@pytest.fixture(autouse=True)
def seeded_creature_types(monkeypatch):
    """Deterministic trait routing regardless of the local/CI DB state.

    The creature_types table is empty in CI and environment-specific
    locally; unit tests pin a known set so effect shapes are stable.
    Tests that need different routing monkeypatch the cache themselves
    (their patch wins — fixtures apply first).
    """
    monkeypatch.setattr(
        change_extractor,
        "_CREATURE_TYPES_CACHE",
        frozenset(
            {
                "aquatic",
                "amphibious",
                "beast",
                "animal",
                "dragon",
                "elemental",
                "ghost",
                "human",
                "humanoid",
                "mindless",
                "plant",
                "skeleton",
                "spirit",
                "undead",
                "vampire",
                "water",
                "wood",
                "zombie",
            }
        ),
    )
