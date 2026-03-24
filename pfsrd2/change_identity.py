"""Identity hashing for template/family change objects.

The hash is built from the fields that define a change's content identity:
the source document name, source type, and the raw change text. If the
source text changes, the hash changes and the old enrichment is marked stale.
"""

import hashlib
import json

from pfsrd2.ability_identity import normalize_text


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
