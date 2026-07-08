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
