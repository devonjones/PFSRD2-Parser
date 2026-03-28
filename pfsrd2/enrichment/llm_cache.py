"""Persistent LLM response cache — survives enrichment DB rebuilds.

Stores at ~/.pfsrd2/llm_cache.db. Keyed on (identity_hash, prompt_hash, model)
so identical abilities with the same prompt always return cached results.

The prompt_hash is a SHA-256 of the full prompt text, so if we change the
prompt template, old cache entries are automatically bypassed.
"""

import hashlib
import os
import sqlite3
from datetime import UTC, datetime

DB_NAME = "llm_cache.db"


def _get_db_path():
    path = os.path.expanduser("~/.pfsrd2")
    if not os.path.exists(path):
        os.makedirs(path)
    return os.path.join(path, DB_NAME)


def _ensure_table(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS llm_cache (
            prompt_hash TEXT NOT NULL,
            model TEXT NOT NULL,
            response TEXT,
            created_at TEXT NOT NULL,
            PRIMARY KEY (prompt_hash, model)
        )
    """
    )
    conn.commit()


_conn = None


def _get_conn():
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(_get_db_path(), timeout=30)
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA busy_timeout=30000")
        _ensure_table(_conn)
    return _conn


def compute_prompt_hash(prompt):
    """SHA-256 of the prompt text. Changes when the prompt template changes."""
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def cache_get(prompt_hash, model):
    """Look up a cached LLM response. Returns the response string or None."""
    conn = _get_conn()
    cur = conn.execute(
        "SELECT response FROM llm_cache WHERE prompt_hash = ? AND model = ?",
        (prompt_hash, model),
    )
    row = cur.fetchone()
    return row[0] if row else None


def cache_put(prompt_hash, model, response):
    """Store an LLM response in the cache."""
    conn = _get_conn()
    now = datetime.now(UTC).isoformat()
    conn.execute(
        "INSERT OR REPLACE INTO llm_cache (prompt_hash, model, response, created_at)"
        " VALUES (?, ?, ?, ?)",
        (prompt_hash, model, response, now),
    )
    conn.commit()


def cache_stats():
    """Return cache statistics."""
    conn = _get_conn()
    cur = conn.execute("SELECT COUNT(*) FROM llm_cache")
    total = cur.fetchone()[0]
    cur = conn.execute("SELECT COUNT(DISTINCT model) FROM llm_cache")
    models = cur.fetchone()[0]
    return {"total": total, "models": models}
