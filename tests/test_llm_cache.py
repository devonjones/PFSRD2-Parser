"""Tests for pfsrd2/enrichment/llm_cache.py using in-memory SQLite."""

import sqlite3

import pfsrd2.enrichment.llm_cache as llm_cache


def _setup_in_memory():
    """Replace the module's connection with an in-memory DB."""
    conn = sqlite3.connect(":memory:")
    llm_cache._ensure_table(conn)
    llm_cache._conn = conn
    return conn


class TestComputePromptHash:
    def test_deterministic(self):
        h1 = llm_cache.compute_prompt_hash("test prompt")
        h2 = llm_cache.compute_prompt_hash("test prompt")
        assert h1 == h2

    def test_different_prompts(self):
        h1 = llm_cache.compute_prompt_hash("prompt A")
        h2 = llm_cache.compute_prompt_hash("prompt B")
        assert h1 != h2

    def test_returns_hex_string(self):
        h = llm_cache.compute_prompt_hash("test")
        assert len(h) == 64  # SHA-256 hex length
        assert all(c in "0123456789abcdef" for c in h)


class TestCacheGetPut:
    def setup_method(self):
        self.conn = _setup_in_memory()

    def teardown_method(self):
        llm_cache._conn = None

    def test_miss_returns_none(self):
        assert llm_cache.cache_get("nonexistent", "model") is None

    def test_put_then_get(self):
        llm_cache.cache_put("hash1", "model1", "response text")
        result = llm_cache.cache_get("hash1", "model1")
        assert result == "response text"

    def test_different_model_is_separate(self):
        llm_cache.cache_put("hash1", "modelA", "response A")
        llm_cache.cache_put("hash1", "modelB", "response B")
        assert llm_cache.cache_get("hash1", "modelA") == "response A"
        assert llm_cache.cache_get("hash1", "modelB") == "response B"

    def test_overwrite_same_key(self):
        llm_cache.cache_put("hash1", "model1", "old")
        llm_cache.cache_put("hash1", "model1", "new")
        assert llm_cache.cache_get("hash1", "model1") == "new"

    def test_none_response_stored(self):
        llm_cache.cache_put("hash1", "model1", None)
        # None is stored and retrievable
        result = llm_cache.cache_get("hash1", "model1")
        assert result is None


class TestCacheStats:
    def setup_method(self):
        self.conn = _setup_in_memory()

    def teardown_method(self):
        llm_cache._conn = None

    def test_empty_stats(self):
        stats = llm_cache.cache_stats()
        assert stats["total"] == 0
        assert stats["models"] == 0

    def test_stats_after_inserts(self):
        llm_cache.cache_put("h1", "modelA", "r1")
        llm_cache.cache_put("h2", "modelA", "r2")
        llm_cache.cache_put("h3", "modelB", "r3")
        stats = llm_cache.cache_stats()
        assert stats["total"] == 3
        assert stats["models"] == 2
