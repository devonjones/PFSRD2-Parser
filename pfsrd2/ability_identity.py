import hashlib
import json
import unicodedata


def normalize_text(text):
    """Normalize text for stable identity hashing.

    Strips whitespace, collapses runs of whitespace to single space,
    and applies NFC unicode normalization.
    """
    if not text:
        return ""
    text = unicodedata.normalize("NFC", text)
    return " ".join(text.split())


def compute_identity_hash(ability):
    """Compute a deterministic identity hash for an ability object.

    The hash is built from the fields that define the ability's identity:
    name, text, effect, frequency, trigger, requirement, cost,
    action_type name, and sorted trait names.

    Returns a hex digest string.
    """
    parts = []

    # Core identity fields (order matters for hash stability)
    for field in ("name", "text", "effect", "frequency", "trigger",
                  "requirement", "cost"):
        parts.append(normalize_text(ability.get(field, "")))

    # Action type name
    action_type = ability.get("action_type")
    if action_type and isinstance(action_type, dict):
        parts.append(normalize_text(action_type.get("name", "")))
    else:
        parts.append("")

    # Sorted trait names for order-independent matching
    traits = ability.get("traits", [])
    if traits:
        trait_names = sorted(
            normalize_text(t["name"]) for t in traits if isinstance(t, dict) and "name" in t
        )
        parts.append("|".join(trait_names))
    else:
        parts.append("")

    identity_string = "\x00".join(parts)
    return hashlib.sha256(identity_string.encode("utf-8")).hexdigest()


def ability_to_raw_json(ability):
    """Serialize an ability object to a stable JSON string for storage."""
    return json.dumps(ability, sort_keys=True, ensure_ascii=False)
