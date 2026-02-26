"""Tests for edition detection and source override functions."""

from universal.universal import edition_from_alternate_link, source_edition_override_pass


class TestEditionFromAlternateLink:
    """Tests for edition_from_alternate_link()."""

    def test_no_alternate_link_returns_none(self):
        struct = {"name": "Longsword"}
        assert edition_from_alternate_link(struct) is None

    def test_alternate_link_none_returns_none(self):
        struct = {"name": "Longsword", "alternate_link": None}
        assert edition_from_alternate_link(struct) is None

    def test_remastered_alternate_type_means_legacy(self):
        """If the alternate version is remastered, THIS item is legacy."""
        struct = {
            "alternate_link": {
                "alternate_type": "remastered",
                "name": "Tethered (Remastered)",
            }
        }
        assert edition_from_alternate_link(struct) == "legacy"

    def test_legacy_alternate_type_means_remastered(self):
        """If the alternate version is legacy, THIS item is remastered."""
        struct = {
            "alternate_link": {
                "alternate_type": "legacy",
                "name": "Tethered (Legacy)",
            }
        }
        assert edition_from_alternate_link(struct) == "remastered"

    def test_unknown_alternate_type_returns_none(self):
        struct = {
            "alternate_link": {
                "alternate_type": "unknown",
            }
        }
        assert edition_from_alternate_link(struct) is None

    def test_missing_alternate_type_returns_none(self):
        struct = {
            "alternate_link": {
                "name": "Some Link",
            }
        }
        assert edition_from_alternate_link(struct) is None


class TestSourceEditionOverridePass:
    """Tests for source_edition_override_pass()."""

    def test_no_edition_does_nothing(self):
        struct = {"sources": [{"name": "Treasure Vault"}]}
        source_edition_override_pass(struct)
        assert struct["sources"][0]["name"] == "Treasure Vault"

    def test_legacy_treasure_vault_unchanged(self):
        """Legacy Treasure Vault items keep the original source name."""
        struct = {
            "edition": "legacy",
            "sources": [{"name": "Treasure Vault"}],
        }
        source_edition_override_pass(struct)
        assert struct["sources"][0]["name"] == "Treasure Vault"

    def test_remastered_treasure_vault_renamed(self):
        """Remastered Treasure Vault items get renamed source."""
        struct = {
            "edition": "remastered",
            "sources": [{"name": "Treasure Vault"}],
        }
        source_edition_override_pass(struct)
        assert struct["sources"][0]["name"] == "Treasure Vault (Remastered)"

    def test_remastered_treasure_vault_link_updated(self):
        """Source link name and alt are updated when source is renamed."""
        struct = {
            "edition": "remastered",
            "sources": [
                {
                    "name": "Treasure Vault",
                    "link": {
                        "name": "Treasure Vault",
                        "alt": "Treasure Vault",
                        "href": "Sources.aspx?ID=191",
                    },
                }
            ],
        }
        source_edition_override_pass(struct)
        assert struct["sources"][0]["link"]["name"] == "Treasure Vault (Remastered)"
        assert struct["sources"][0]["link"]["alt"] == "Treasure Vault (Remastered)"

    def test_unrelated_source_unchanged(self):
        """Sources not in the override map are never renamed."""
        struct = {
            "edition": "remastered",
            "sources": [{"name": "Player Core"}],
        }
        source_edition_override_pass(struct)
        assert struct["sources"][0]["name"] == "Player Core"

    def test_multiple_sources_only_matching_renamed(self):
        struct = {
            "edition": "remastered",
            "sources": [
                {"name": "Treasure Vault"},
                {"name": "Player Core"},
            ],
        }
        source_edition_override_pass(struct)
        assert struct["sources"][0]["name"] == "Treasure Vault (Remastered)"
        assert struct["sources"][1]["name"] == "Player Core"

    def test_no_sources_does_not_crash(self):
        struct = {"edition": "remastered"}
        source_edition_override_pass(struct)  # Should not raise
