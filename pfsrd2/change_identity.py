"""Identity hashing for template/family change objects.

The hash is built from the fields that define a change's content identity:
the source document name, source type, and the raw change text. If the
source text changes, the hash changes and the old enrichment is marked stale.
"""

import hashlib
import json
import unicodedata


def normalize_text(text):
    """Normalize text for stable identity hashing."""
    if not text:
        return ""
    text = unicodedata.normalize("NFC", text)
    return " ".join(text.split())


def compute_change_hash(source_name, source_type, change_text):
    """Compute a deterministic identity hash for a change object.

    Args:
        source_name: The template/family name (e.g., "Vampire, Strigoi")
        source_type: "monster_template" or "monster_family"
        change_text: The raw change text from the <li> element

    Returns a hex digest string.
    """
    parts = [
        normalize_text(source_name),
        normalize_text(source_type),
        normalize_text(change_text),
    ]
    identity_string = "\x00".join(parts)
    return hashlib.sha256(identity_string.encode("utf-8")).hexdigest()


def change_to_raw_json(change):
    """Serialize a change object to a stable JSON string for storage."""
    return json.dumps(change, sort_keys=True, ensure_ascii=False)
