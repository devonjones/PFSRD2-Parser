"""Ability enrichment pass for the creature parser pipeline.

Populates the enrichment DB with ability records and creature links.
When enriched data exists, merges it into the ability objects.
"""

import json

from pfsrd2.ability_identity import ability_to_raw_json, compute_identity_hash
from pfsrd2.sql.enrichment import (
    fetch_ability_by_hash,
    get_enrichment_db_connection,
    insert_ability_record,
    insert_creature_link,
    mark_stale,
)

# Fields that enrichment can add to an ability object.
# These are the structured mechanics extracted from text.
ENRICHMENT_FIELDS = ("saving_throw", "damage", "area", "range", "frequency")


def _get_creature_metadata(struct):
    """Extract creature-level metadata for the link table."""
    sb = struct.get("stat_block", {})
    ct = sb.get("creature_type", {})
    trait_names = [
        t["name"] for t in ct.get("traits", [])
        if isinstance(t, dict) and "name" in t
    ]
    sources = struct.get("sources", [])
    source_name = sources[0]["name"] if sources else None
    return {
        "creature_game_id": str(struct.get("aonid", "")),
        "creature_name": struct.get("name", ""),
        "creature_level": ct.get("level"),
        "creature_traits": trait_names,
        "source_name": source_name,
    }


def _walk_abilities(struct):
    """Yield (category, ability) tuples from a creature's stat block.

    Category is one of: "automatic", "reactive", "offensive".
    """
    sb = struct.get("stat_block", {})
    defense = sb.get("defense", {})

    for ability in defense.get("automatic_abilities", []):
        if ability.get("subtype") == "ability":
            yield "automatic", ability

    for ability in defense.get("reactive_abilities", []):
        if ability.get("subtype") == "ability":
            yield "reactive", ability

    for oa in sb.get("offense", {}).get("offensive_actions", []):
        if oa.get("offensive_action_type") == "ability":
            ability = oa.get("ability")
            if ability:
                yield "offensive", ability


def _dc_key(save_dc):
    """Identity key for deduplicating save DCs."""
    return (save_dc.get("dc"), save_dc.get("save_type"))


def _merge_saving_throws(ability, enriched):
    """Merge saving_throw lists, deduplicating by DC+save_type.

    Handles both single object and array formats from parser/enrichment.
    Always produces an array.
    """
    existing = ability.get("saving_throw")
    new = enriched.get("saving_throw")
    if not new:
        return

    # Normalize both to lists
    if existing and not isinstance(existing, list):
        existing = [existing]
    elif not existing:
        existing = []
    if not isinstance(new, list):
        new = [new]

    # Deduplicate: keep existing, add new DCs not already present
    existing_keys = {_dc_key(s) for s in existing}
    for save in new:
        if _dc_key(save) not in existing_keys:
            existing.append(save)
            existing_keys.add(_dc_key(save))

    if existing:
        ability["saving_throw"] = existing


def _normalize_to_list(value):
    """Normalize a value to a list."""
    if isinstance(value, list):
        return value
    return [value] if value else []


def _area_key(area):
    """Identity key for deduplicating areas."""
    return (area.get("size"), area.get("shape"), area.get("unit"))


def _damage_key(damage):
    """Identity key for deduplicating damage."""
    return (damage.get("formula"), damage.get("damage_type"),
            damage.get("persistent", False))


def _merge_list_field(ability, enriched, field, key_fn):
    """Merge a list field, deduplicating by key function.

    Handles both single object and array formats.
    Produces an array if there are multiple items, single object if one.
    """
    new = enriched.get(field)
    if not new:
        return

    existing = _normalize_to_list(ability.get(field))
    new = _normalize_to_list(new)

    existing_keys = {key_fn(item) for item in existing}
    for item in new:
        if key_fn(item) not in existing_keys:
            existing.append(item)
            existing_keys.add(key_fn(item))

    if existing:
        ability[field] = existing


def _merge_enrichment(ability, enriched_json):
    """Merge enriched fields into the ability object in-place.

    For list-capable fields (saving_throw, area, damage), merges and
    deduplicates. For scalar fields, only adds if not already present.
    """
    enriched = json.loads(enriched_json)

    # List-capable fields get merge logic
    _merge_list_field(ability, enriched, "saving_throw", _dc_key)
    _merge_list_field(ability, enriched, "area", _area_key)
    _merge_list_field(ability, enriched, "damage", _damage_key)

    # Scalar fields: simple add-if-missing
    for field in ENRICHMENT_FIELDS:
        if field in ("saving_throw", "area", "damage"):
            continue
        if field in enriched and field not in ability:
            ability[field] = enriched[field]


def ability_enrichment_pass(struct, conn=None):
    """Populate the enrichment DB and apply enrichments to abilities.

    First run: inserts raw records + creature links (no output changes).
    Subsequent runs: if enriched data exists and isn't stale, merges
    structured fields into the ability objects.

    If conn is provided, uses it (caller manages lifecycle).
    Otherwise opens and closes its own connection.
    """
    meta = _get_creature_metadata(struct)
    owns_conn = conn is None
    if owns_conn:
        conn = get_enrichment_db_connection()
    try:
        curs = conn.cursor()
        for category, ability in _walk_abilities(struct):
            identity_hash = compute_identity_hash(ability)
            raw_json = ability_to_raw_json(ability)

            existing = fetch_ability_by_hash(curs, identity_hash)

            if existing is None:
                ability_id = insert_ability_record(
                    curs, ability["name"], identity_hash, raw_json
                )
            else:
                ability_id = existing["ability_id"]
                if existing["raw_json"] != raw_json:
                    mark_stale(curs, ability_id, raw_json)

                # Apply enrichment if available and not stale
                if (existing["enriched_json"]
                        and not existing["stale"]):
                    _merge_enrichment(ability, existing["enriched_json"])

            insert_creature_link(
                curs,
                ability_id,
                meta["creature_game_id"],
                meta["creature_name"],
                meta["creature_level"],
                meta["creature_traits"],
                meta["source_name"],
                category,
            )

        conn.commit()
    finally:
        if owns_conn:
            conn.close()
