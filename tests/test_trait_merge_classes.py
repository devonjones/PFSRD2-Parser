"""Tests for _merge_classes behavior in trait_db_pass."""


class TestMergeClassesLogic:
    """Test the merge logic extracted from trait_db_pass._merge_classes.

    The actual function is an inner function, so we test the logic directly.
    """

    @staticmethod
    def _merge_classes(trait, db_trait):
        """Reproduce the _merge_classes logic for testing."""
        trait_classes = set(trait.get("classes", []))
        db_trait_classes = set(db_trait.get("classes", []))
        merged = sorted(trait_classes | db_trait_classes)
        if merged:
            db_trait["classes"] = merged
        else:
            db_trait.pop("classes", None)

    def test_both_have_classes(self):
        trait = {"classes": ["combat"]}
        db_trait = {"classes": ["general"]}
        self._merge_classes(trait, db_trait)
        assert db_trait["classes"] == ["combat", "general"]

    def test_both_empty(self):
        trait = {}
        db_trait = {"classes": []}
        self._merge_classes(trait, db_trait)
        assert "classes" not in db_trait

    def test_trait_has_classes_db_does_not(self):
        trait = {"classes": ["combat"]}
        db_trait = {}
        self._merge_classes(trait, db_trait)
        assert db_trait["classes"] == ["combat"]

    def test_db_has_classes_trait_does_not(self):
        trait = {}
        db_trait = {"classes": ["general"]}
        self._merge_classes(trait, db_trait)
        assert db_trait["classes"] == ["general"]

    def test_overlapping_classes(self):
        trait = {"classes": ["combat", "general"]}
        db_trait = {"classes": ["general", "skill"]}
        self._merge_classes(trait, db_trait)
        assert db_trait["classes"] == ["combat", "general", "skill"]

    def test_result_is_sorted(self):
        trait = {"classes": ["skill", "combat"]}
        db_trait = {"classes": ["general"]}
        self._merge_classes(trait, db_trait)
        assert db_trait["classes"] == ["combat", "general", "skill"]

    def test_both_none_no_key(self):
        trait = {}
        db_trait = {}
        self._merge_classes(trait, db_trait)
        assert "classes" not in db_trait
